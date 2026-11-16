# Adapted for selflift-Avatar from Fish4AI/comfyui-SelfLift-Fish.
# Full-sequence H3 attention context is retained; Avatar masks stay on the full packed sequence.
"""RAM staging for full-sequence native H3 Sol-Attn/SLA, grouped over heads.

Heads are independent inside native attention. Compute each head group over
ALL tokens, then concatenate in the original order before the output linear.
Raw BF16 QKV and completed head outputs live in RAM; no spatial/key cropping,
extra quantization, changed sparse budget or repeated QKV projection is used.
"""
import logging

import psutil
import torch

import comfy.model_management
import comfy.model_prefetch
import comfy_kitchen as ck
from comfy.ldm.minimax.model import _mod_gate, _mod_scale_shift


def _segments_slice(segments, start, end):
    result = []
    for a, b, row in segments:
        lo, hi = max(a, start), min(b, end)
        if lo < hi:
            if torch.is_tensor(row) and row.ndim:
                row = row[lo-a:hi-a]
            result.append((lo-start, hi-start, row))
    return result


class HostBuffers:
    """One arena per model forward, reused by every eligible transformer block."""
    def __init__(self, n, heads, dim, dtype, head_chunk):
        self.signature = (n, heads, dim, dtype, head_chunk)
        self.groups = [(a, min(heads, a+head_chunk)) for a in range(0, heads, head_chunk)]
        self.bytes = n * heads * dim * torch.empty((), dtype=dtype).element_size() * 4
        available = psutil.virtual_memory().available
        if available < self.bytes + 2 * 1024**3:
            raise RuntimeError(
                f"selflift-Avatar global_ram needs {self.bytes/1024**3:.2f} GiB staging RAM plus 2 GiB headroom; "
                f"only {available/1024**3:.2f} GiB available. Reduce duration/resolution or use global.")
        # Pageable RAM remains correct if the OS cannot pin a large arena.
        def allocate(shape):
            try:
                return torch.empty(shape, dtype=dtype, device="cpu", pin_memory=True)
            except RuntimeError:
                logging.warning("[selflift-Avatar global RAM] pinned allocation unavailable; using pageable RAM")
                return torch.empty(shape, dtype=dtype, device="cpu")
        self.qkv = allocate((n, 3, heads, dim))
        self.outputs = [allocate((n, b-a, dim)) for a, b in self.groups]
        logging.info("[selflift-Avatar global RAM v3] tokens=%d heads=%d group=%d groups=%d host_staging=%.2f GiB; complete token layout",
                     n, heads, head_chunk, len(self.groups), self.bytes/1024**3)


def sparse_block(block, x, t_emb, segments, rope, options, chunk_size, spec,
                 block_index, state, head_chunk=8):
    """Called only when the native sparse H3 producer is eligible."""
    if torch.is_grad_enabled():
        raise RuntimeError("selflift-Avatar global_ram is inference-only")
    if head_chunk < 1:
        raise ValueError("selflift-Avatar global_ram head group must be positive")
    patch, _ = spec
    attn = block.attn
    n, heads, dim = x.shape[0], attn.heads, attn.head_dim
    chunk_size = max(64, int(chunk_size)//64*64)
    signature = (n, heads, dim, x.dtype, head_chunk)
    buffers = state.get("buffers")
    if buffers is None or buffers.signature != signature:
        # Persistent arena ownership belongs to this forward, outside the
        # dynamic GPU allocation graph. The enclosing wrapper clears it.
        with comfy.model_prefetch.pause_malloc_graph():
            buffers = HostBuffers(n, heads, dim, x.dtype, head_chunk)
        state["buffers"] = buffers
    shift, scale, gate, mshift, mscale, mgate = block.adaln_proj(t_emb)

    # Project all heads ONCE. Synchronous D2H copies keep the GPU source alive
    # until host writes complete and prevent CPU readers racing the DMA.
    for start in range(0, n, chunk_size):
        end = min(n, start+chunk_size)
        seg = _segments_slice(segments, start, end)
        h = _mod_scale_shift(block.norm1(x[start:end]), shift, scale, seg)
        qkv = attn.qkv_proj(h).view(end-start, 3, heads, dim)
        buffers.qkv[start:end].copy_(qkv, non_blocking=False)
        del h, qkv

    qw = comfy.model_management.cast_to(attn.q_norm.weight, device=x.device)
    kw = comfy.model_management.cast_to(attn.k_norm.weight, device=x.device)
    key = (block_index, n, tuple(options.get("uuids", ())))
    with comfy.model_prefetch.pause_malloc_graph():
        pooled = patch.pooled.get(key)
        first = pooled is None
        if first:
            pooled = (torch.empty((heads, dim), dtype=torch.float32, device=x.device),
                      torch.empty((heads, dim), dtype=torch.float32, device=x.device))
    sink, sink_q = patch.sinks(options, n)
    for group_index, (a, b) in enumerate(buffers.groups):
        def chunks(a=a, b=b):
            for start in range(0, n, chunk_size):
                end = min(n, start+chunk_size)
                # Pack on CPU, transfer only this group's raw projections.
                host = buffers.qkv[start:end, :, a:b].contiguous().view(end-start, 3*(b-a)*dim)
                yield host.to(device=x.device, non_blocking=False)
        out, kmean, vscale = ck.sol_attn_chunked(
            chunks, n, b-a, rope, (qw, kw),
            kmean=None if first else pooled[0][a:b], vscale=None if first else pooled[1][a:b],
            tau=patch.tau, topk_ratio=patch.topk_ratio, token_aug=patch.extra_tokens,
            sink_blocks=list(sink), sink_q=list(sink_q), rope_eps=attn.q_norm.eps)
        pooled[0][a:b].copy_(kmean)
        pooled[1][a:b].copy_(vscale)
        buffers.outputs[group_index].copy_(out.view(n, b-a, dim), non_blocking=False)
        del out, kmean, vscale
    patch.pooled[key] = pooled

    # All groups are finished before touching x. Restore the original head
    # order, then run the SAME unsliced output linear and residual per chunk.
    for start in range(0, n, chunk_size):
        end = min(n, start+chunk_size)
        host = torch.cat([out[start:end] for out in buffers.outputs], dim=1).view(end-start, heads*dim)
        full_heads = host.to(device=x.device, non_blocking=False)
        projected = attn.out_proj(full_heads)
        _mod_gate(x[start:end], gate, projected, _segments_slice(segments, start, end))
        del host, full_heads, projected
    for start in range(0, n, chunk_size):
        end = min(n, start+chunk_size)
        seg = _segments_slice(segments, start, end)
        h = _mod_scale_shift(block.norm2(x[start:end]), mshift, mscale, seg)
        out = block.mlp(h)
        _mod_gate(x[start:end], mgate, out, seg)
        del h, out
    return x
