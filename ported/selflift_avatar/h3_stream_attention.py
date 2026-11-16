# Adapted for selflift-Avatar from Fish4AI/comfyui-SelfLift-Fish.
# Full-sequence H3 attention context is retained; Avatar masks stay on the full packed sequence.
"""Full-context head streaming on GPU; no host QKV/output staging.

Slice only independent QKV OUTPUT channels, retaining the native weight dtype,
quantization and the complete token/key axis. Gather every head's attention
result in GPU memory before the unchanged full output projection.
"""
from contextlib import contextmanager
import dataclasses
import logging

import torch
import torch.nn.functional as F

import comfy.model_management as mm
import comfy.model_prefetch
import comfy.ops
from comfy.quant_ops import QuantizedTensor
import comfy_kitchen as ck
from comfy.ldm.minimax.model import _mod_gate, _mod_scale_shift
from .h3_global_tiling import _segments_slice, _chunk_mlp
from .h3_prepared_weights import prepared_block


def select_weight_rows(weight, rows):
    """Avoid QuantizedTensor slicing's implicit full dequantization fallback."""
    if not isinstance(weight, QuantizedTensor):
        return weight.index_select(0, rows)
    if weight._layout_cls != "TensorWiseINT8Layout" or getattr(weight._params,"transposed",False):
        raise ValueError("selflift-Avatar global_stream currently supports standard and TensorWiseINT8Layout QKV weights")
    p=weight._params
    scale=p.scale
    if scale.numel()>1:
        if scale.shape[0]!=weight.shape[0] or scale.numel()!=weight.shape[0]:
            raise ValueError("selflift-Avatar global_stream: unsupported QKV scale geometry")
        scale=scale.index_select(0,rows)
    params=dataclasses.replace(p,orig_shape=(rows.numel(),weight.shape[1]),scale=scale)
    return QuantizedTensor(weight._qdata.index_select(0,rows),weight._layout_cls,params)


def validate_projection(linear):
    if (getattr(linear,"_full_precision_mm",False) or getattr(linear,"comfy_force_cast_weights",False)
            or len(getattr(linear,"weight_function",[])) or len(getattr(linear,"bias_function",[]))):
        raise ValueError("selflift-Avatar global_stream does not support custom QKV weight transforms")
    weight=linear.weight
    if isinstance(weight,QuantizedTensor):
        if weight._layout_cls!="TensorWiseINT8Layout":
            raise ValueError("selflift-Avatar global_stream currently supports standard and TensorWiseINT8Layout QKV weights")
    elif weight.dtype not in (torch.bfloat16,torch.float16,torch.float32):
        raise ValueError("selflift-Avatar global_stream requires BF16/FP16/FP32 or native TensorWise INT8 QKV weights")


@contextmanager
def cast_projection(linear, device, dtype):
    validate_projection(linear)
    quantized=isinstance(linear.weight,QuantizedTensor)
    with comfy.ops.CastBiasWeightContext(
            linear,input=None,dtype=linear.weight.dtype if quantized else dtype,device=device,
            bias_dtype=dtype,offloadable=True,compute_dtype=dtype,want_requant=quantized) as (weight,bias):
        yield weight.to(dtype=dtype),bias


def sparse_block(block,x,t_emb,segments,rope,options,chunk_size,spec,block_index,head_chunk=8):
    with prepared_block(block,x.device,x.dtype):
        return _sparse_block(block,x,t_emb,segments,rope,options,chunk_size,spec,block_index,head_chunk)


def _sparse_block(block,x,t_emb,segments,rope,options,chunk_size,spec,block_index,head_chunk=8):
    if torch.is_grad_enabled():
        raise RuntimeError("selflift-Avatar global_stream is inference-only")
    patch,_=spec
    attn=block.attn
    n,heads,dim=x.shape[0],attn.heads,attn.head_dim
    if head_chunk<1:
        raise ValueError("selflift-Avatar global_stream head group must be positive")
    chunk_size=max(64,int(chunk_size)//64*64)
    shift,scale,gate,mshift,mscale,mgate=block.adaln_proj(t_emb)
    qw=mm.cast_to(attn.q_norm.weight,device=x.device)
    kw=mm.cast_to(attn.k_norm.weight,device=x.device)
    key=(block_index,n,tuple(options.get("uuids",())))
    with comfy.model_prefetch.pause_malloc_graph():
        pooled=patch.pooled.get(key)
        first=pooled is None
        if first:
            pooled=(torch.empty(heads,dim,dtype=torch.float32,device=x.device),
                    torch.empty(heads,dim,dtype=torch.float32,device=x.device))
    sink,sink_q=patch.sinks(options,n)
    output=torch.empty(n,heads,dim,dtype=x.dtype,device=x.device)
    smoothing=getattr(attn.qkv_proj,"pre_quant_scale",None)
    if smoothing is not None:
        smoothing=mm.cast_to_device(smoothing,x.device,x.dtype)
    with cast_projection(attn.qkv_proj,x.device,x.dtype) as (full_weight,full_bias):
        for a in range(0,heads,head_chunk):
            b=min(heads,a+head_chunk)
            indices=torch.arange(a*dim,b*dim,device=x.device)
            rows=torch.cat([indices+i*heads*dim for i in range(3)])
            weight=select_weight_rows(full_weight,rows)
            bias=full_bias.index_select(0,rows) if full_bias is not None else None
            def chunks():
                for start in range(0,n,chunk_size):
                    end=min(n,start+chunk_size)
                    h=_mod_scale_shift(block.norm1(x[start:end]),shift,scale,_segments_slice(segments,start,end))
                    if smoothing is not None:
                        h=h*smoothing
                    yield F.linear(h,weight,bias)
            out,kmean,vscale=ck.sol_attn_chunked(
                chunks,n,b-a,rope,(qw,kw),
                kmean=None if first else pooled[0][a:b],vscale=None if first else pooled[1][a:b],
                tau=patch.tau,topk_ratio=patch.topk_ratio,token_aug=patch.extra_tokens,
                sink_blocks=list(sink),sink_q=list(sink_q),rope_eps=attn.q_norm.eps)
            output[:,a:b].copy_(out.view(n,b-a,dim))
            pooled[0][a:b].copy_(kmean);pooled[1][a:b].copy_(vscale)
            del out,kmean,vscale,weight,bias,rows,indices
    patch.pooled[key]=pooled
    output=output.view(n,heads*dim)
    for start in range(0,n,chunk_size):
        end=min(n,start+chunk_size)
        projected=attn.out_proj(output[start:end])
        _mod_gate(x[start:end],gate,projected,_segments_slice(segments,start,end))
        del projected
    del output
    _chunk_mlp(block,x,mshift,mscale,mgate,segments,chunk_size)
    log_key=("selflift_stream_v5",n,chunk_size,head_chunk)
    if log_key not in patch._logged:
        patch._logged.add(log_key)
        logging.info("[selflift-Avatar global stream] tokens=%d heads=%d group=%d; GPU-only, original quantization, full token layout",n,heads,head_chunk)
    return x
