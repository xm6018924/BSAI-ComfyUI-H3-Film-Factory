# Adapted for selflift-Avatar from Fish4AI/comfyui-SelfLift-Fish.
# Full-sequence H3 attention context is retained; Avatar masks stay on the full packed sequence.
"""Block-local reuse of native prepared non-resident LoRA weights.

Comfy's normal prefetch resolves resident VBAR weights once. When fault() is
declined, the streamed weight remains `resident=False`, so each token chunk
can repeat the same LoRA merge/requantization. Keep its native prepared GPU
tensor for this block only, then restore every prefetch field before cleanup.
"""
from contextlib import ExitStack, contextmanager
import logging

import comfy.ops

_MISSING=object()

@contextmanager
def weight_cache_budget(patcher,budget_gib):
    """Temporarily cap only this model's VBAR cache; restore its prior cursor.

    set_watermark_limit is an eviction FLOOR, not a cache ceiling. Use the
    native set_watermark API, whose out-of-range weights stream normally.
    """
    if budget_gib<0:
        raise ValueError("SelfLift weight-cache budget must be nonnegative")
    if budget_gib==0 or patcher is None or not patcher.is_dynamic():
        yield
        return
    vbar=patcher._vbar_get(create=False)
    if vbar is None:
        yield
        return
    previous=vbar.get_watermark()*(32*1024**2)
    ceiling=min(previous,int(budget_gib*1024**3))
    vbar.set_watermark(ceiling)
    try:
        yield
    finally:
        # Restoring the cursor allocates no weight pages by itself.
        vbar.set_watermark(previous)

@contextmanager
def prepared_block(block,device,dtype):
    restored=[]
    with ExitStack() as stack:
        try:
            for module in (block.attn.qkv_proj,block.attn.out_proj,block.mlp.fc1,block.mlp.fc2):
                prefetch=getattr(module,"_prefetch",None)
                if (prefetch is None or prefetch.get("signature") is not None or prefetch.get("resident")
                        or getattr(module,"weight_lowvram_function",None) is None
                        or len(getattr(module,"weight_function",[])) or len(getattr(module,"bias_function",[]))
                        or module.weight.dtype!=dtype or getattr(module,"_full_precision_mm",False)):
                    continue
                weight,bias=stack.enter_context(comfy.ops.CastBiasWeightContext(
                    module,input=None,dtype=module.weight.dtype,device=device,bias_dtype=dtype,
                    offloadable=True,compute_dtype=dtype,want_requant=True))
                restored.append((module,prefetch,prefetch.get("resident"),
                                 getattr(module,"_v_weight",_MISSING),getattr(module,"_v_bias",_MISSING)))
                # No VBAR fault/signature/pin is fabricated. This is a real
                # prepared GPU tensor, owned until this scope exits. Native
                # forward/input_act paths and all module hooks remain intact.
                module._v_weight=weight
                module._v_bias=bias
                prefetch["resident"]=True
            if restored:
                logging.debug("[SelfLift prepared weights] reused %d streamed LoRA weights for this block",len(restored))
            yield len(restored)
        finally:
            for module,prefetch,resident,weight,bias in reversed(restored):
                prefetch["resident"]=resident
                for key,value in (("_v_weight",weight),("_v_bias",bias)):
                    if value is _MISSING:
                        if hasattr(module,key):
                            delattr(module,key)
                    else:
                        setattr(module,key,value)
