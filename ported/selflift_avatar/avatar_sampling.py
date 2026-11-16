"""Use ComfyUI's native mask conditioning with a separate clean inpaint anchor."""

import logging

import comfy.patcher_extension
import comfy.samplers
import comfy.utils


def anchored_sampler(sampler, anchor):
    def sample_with_anchor(model_k, x, sigmas, **kwargs):
        # KSAMPLER already built x from the (possibly noisy) resume latent.
        # Only the native inpaint anchor is replaced, not that initial state.
        model_k.latent_image = model_k.inner_model.inner_model.process_latent_in(anchor.to(x))
        return sampler.sampler_function(model_k, x, sigmas, **kwargs)

    return comfy.samplers.KSAMPLER(sample_with_anchor, sampler.extra_options.copy(), sampler.inpaint_options.copy())


def native_mask_model(base, anchors, masks, nested):
    if masks is None:
        return base
    if nested:
        anchor, _ = comfy.utils.pack_latents(anchors)
        mask, _ = comfy.utils.pack_latents([m.to(a.device).expand_as(a) for m, a in zip(masks, anchors)])
    else:
        anchor, mask = anchors[0], masks[0].expand_as(anchors[0])
    patched = base.clone()
    if "denoise_mask_function" in patched.model_options:
        patched.model_options.pop("denoise_mask_function")
        logging.warning("selflift-Avatar: uses static input masks; dynamic denoise_mask_function is not applied")

    def inject_mask(executor, noise, latent_image, sampler, sigmas, denoise_mask=None,
                    callback=None, disable_pbar=False, seed=None, latent_shapes=None):
        # Inject before inner_sample/process_conds, after generic mask reshaping.
        # This preserves audio channels and supplies H3 audio_denoise_mask labels.
        device = executor.class_obj.model_patcher.load_device
        return executor(noise, latent_image, anchored_sampler(sampler, anchor), sigmas,
                        mask.to(device=device), callback, disable_pbar, seed,
                        latent_shapes=latent_shapes)

    patched.add_wrapper_with_key(comfy.patcher_extension.WrappersMP.OUTER_SAMPLE,
                                 "selflift_avatar_static_mask", inject_mask)
    return patched
