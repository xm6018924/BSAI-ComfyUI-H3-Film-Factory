# Adapted for selflift-Avatar from Fish4AI/comfyui-SelfLift-Fish.
# Full-sequence H3 attention context is retained; Avatar masks stay on the full packed sequence.
"""Bound native H3 input-projection and final-head scratch without changing attention math."""
from contextlib import contextmanager
from functools import partial
import torch
import logging
import comfy.model_prefetch
from comfy.ldm.minimax.model import patchify_video, pack_audio, MiniMaxH3Model


def trim_workspace_cache(device):
    """Reclaim large inactive scratch left by upscalers/previews at a boundary.

    This does not free live tensors, unload weights or clear attention caches.
    Normal bounded model scratch is kept; only a large pool with substantial
    inactive space is trimmed before the next model forward.
    """
    if device.type!='cuda':return
    reserved=torch.cuda.memory_reserved(device)
    allocated=torch.cuda.memory_allocated(device)
    total=torch.cuda.get_device_properties(device).total_memory
    if reserved<=max(2*2**30,total*.4) or reserved-allocated<=2*2**30:return
    with torch.cuda.device(device),comfy.model_prefetch.pause_malloc_graph():
        torch.cuda.empty_cache()
    logging.info('[selflift-Avatar global stream v5 workspace] inactive pool trimmed: reserved %.2f -> %.2f GiB; live tensors and attention caches retained',reserved/2**30,torch.cuda.memory_reserved(device)/2**30)


def chunked_projection(original, chunk_size, x):
    """Apply a weight-stable projection in independent row chunks.

    H3 versions that inline their input packing still project the complete
    video/audio row buffer at once. Chunking only the row axis keeps the result
    identical while bounding that temporary activation.
    """
    chunk_size = max(1, int(chunk_size))
    if x.shape[0] <= chunk_size:
        return original(x)
    return torch.cat([original(x[start:start + chunk_size])
                      for start in range(0, x.shape[0], chunk_size)], dim=0)


def _install_projection_chunking(network, chunk_size):
    installed = []
    for name in ("video_patch_proj", "audio_patch_proj"):
        module = getattr(network, name, None)
        if module is None or not hasattr(module, "forward"):
            continue
        had_forward = "forward" in module.__dict__
        original = module.forward
        module.forward = partial(chunked_projection, original, max(1, int(chunk_size)))
        installed.append((module, had_forward, original))
    return installed


def _restore_projection_chunking(installed):
    for module, had_forward, original in reversed(installed):
        if had_forward:
            module.forward = original
        else:
            del module.forward


def chunked_embed(network,chunk_size,video_x,audio_x,context,layout,payload,transformer_options):
    """Project into the packed hidden buffer without a full FP32 video embed."""
    device,dtype=video_x.device,context.dtype
    img_update=layout.img_update.to(device)
    audio_update=layout.audio_update.to(device)
    video_rows=patchify_video(video_x.to(torch.float32),network.patch_size)
    audio_rows=pack_audio(audio_x.to(torch.float32))
    cond_video_rows=network._cond_video_rows(payload,device)
    cond_audio_rows=network._cond_audio_rows(payload,device)
    all_video_rows=video_rows
    if cond_video_rows is not None:
        all_video_rows=torch.empty(img_update.shape[0],video_rows.shape[1],dtype=torch.float32,device=device)
        all_video_rows[~img_update]=cond_video_rows
        all_video_rows[img_update]=video_rows
    all_audio_rows=audio_rows
    if cond_audio_rows is not None:
        all_audio_rows=torch.empty(audio_update.shape[0],audio_rows.shape[1],dtype=torch.float32,device=device)
        all_audio_rows[~audio_update]=cond_audio_rows
        all_audio_rows[audio_update]=audio_rows
    text=context[0]
    if text.shape[-1]!=network.hidden_size:
        text=network.token_refiner(network.condition_proj(text),transformer_options=transformer_options)
    h=torch.empty(layout.seq_len,network.hidden_size,dtype=dtype,device=device)
    voff=aoff=0
    for start,end,kind in layout.segments:
        n=end-start
        if kind=='text':
            h[start:end]=text
            continue
        is_video=kind in ('cond','ref_img','video')
        rows,projection,offset=(all_video_rows,network.video_patch_proj,voff) if is_video else (all_audio_rows,network.audio_patch_proj,aoff)
        for j in range(0,n,chunk_size):
            k=min(j+chunk_size,n)
            h[start+j:start+k]=projection(rows[offset+j:offset+k]).to(dtype)
        if is_video:voff+=n
        else:aoff+=n
    return h


def chunked_final(original, chunk_size, x, t_emb, video_seg, audio_seg, sigma, sample_sigmas, shifts):
    """Call the original output head on independent row ranges.

    Keep native normalization, per-row modulation, FP32 islands and PDD head
    selection. Only split their independent token rows; attention is complete.
    """
    sizes=[seg[1]-seg[0] for seg in (video_seg,audio_seg)]
    if max(sizes)<=chunk_size:
        return original(x,t_emb,video_seg,audio_seg,sigma,sample_sigmas,shifts)
    outputs=None
    for offset in range(0,max(sizes),chunk_size):
        segments=[]
        for seg,size in zip((video_seg,audio_seg),sizes):
            a,b,row=seg
            start=min(offset,size);end=min(offset+chunk_size,size)
            if isinstance(row,torch.Tensor) and row.ndim>0:
                row=row[start:end]
            segments.append((a+start,a+end,row))
        parts=original(x,t_emb,*segments,sigma,sample_sigmas,shifts)
        if outputs is None:
            outputs=[part.new_empty((size,)+part.shape[1:]) for part,size in zip(parts,sizes)]
        for output,part,size in zip(outputs,parts,sizes):
            start=min(offset,size);end=min(offset+chunk_size,size)
            output[start:end].copy_(part)
        del parts
    return tuple(outputs)


@contextmanager
def output_chunking(network,chunk_size):
    """Scope the native final-head wrapper to this forward and restore exactly."""
    final=network.final_layer
    had_instance_forward='forward' in final.__dict__
    original=final.forward
    final.forward=partial(chunked_final,original,max(1,int(chunk_size)))
    original_embed=getattr(network,'_embed_and_pack',None)
    native_embed_method=getattr(MiniMaxH3Model,'_embed_and_pack',None)
    native_embed=(native_embed_method is not None
                  and getattr(original_embed,'__func__',None) is native_embed_method)
    had_embed='_embed_and_pack' in network.__dict__
    if native_embed:
        network._embed_and_pack=partial(chunked_embed,network,max(1,int(chunk_size)))
    installed = _install_projection_chunking(network, chunk_size)
    try:
        yield
    finally:
        _restore_projection_chunking(installed)
        if native_embed:
            if had_embed:network._embed_and_pack=original_embed
            else:del network._embed_and_pack
        if had_instance_forward:
            final.forward=original
        else:
            del final.forward
