
"""
MiniMax H3 payload patch allowing motion-context keyframes and Ref2VA refs
to coexist.

Derived from:
https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context
(GPL-3.0)
"""
import logging

import comfy.model_base as model_base

MC_KEY = "motion_context_index"
MC_AUDIO_KEY = "motion_context_audio_end_frame"
PATCH_MARKER = "_h3_motion_context_payload_patch"

_LOG = logging.getLogger("minimax_h3_tail_from_latent.motion_context")
_orig_extra_conds = None
_applied = False


def _patched_extra_conds(self, **kwargs):
    out = _orig_extra_conds(self, **kwargs)

    keyframes = kwargs.get("minimax_keyframes", None)
    refs = kwargs.get("minimax_refs", None)

    if not keyframes or not refs:
        return out

    if not (
        any(MC_KEY in kf for kf in keyframes)
        or any(MC_AUDIO_KEY in ref for ref in refs)
    ):
        # Completely unrelated H3 graph: preserve stock behavior exactly.
        return out

    cond = out.get("minimax_payload", None)
    payload = getattr(cond, "cond", None) if cond is not None else None
    if not isinstance(payload, dict):
        _LOG.warning(
            "MiniMax H3 Motion Context RAM: could not access minimax_payload; "
            "Ref2VA refs may overwrite carried video conditioning."
        )
        return out

    # Layout order is: keyframe cond rows first, then Ref2VA reference rows.
    payload["cond_video_latents"] = (
        [kf["latent"] for kf in keyframes if "latent" in kf]
        + [ref["latent"] for ref in refs if "latent" in ref]
    )
    payload["cond_audio_latents"] = [
        ref["audio_latent"]
        for ref in refs
        if ref.get("audio_latent") is not None
    ]

    frame_count = kwargs.get("minimax_frame_count", None)
    if frame_count is not None:
        payload["frame_count"] = frame_count

    return out


setattr(_patched_extra_conds, PATCH_MARKER, True)


def _already_patched(cls):
    fn = getattr(cls, "extra_conds", None)
    if fn is None:
        return None
    if getattr(fn, PATCH_MARKER, False):
        return "same"
    if getattr(fn, "__name__", "") == "_patched_extra_conds":
        return "other"
    if hasattr(fn, "__wrapped__"):
        return "foreign"
    home = getattr(cls, "__module__", None)
    where = getattr(fn, "__module__", None)
    if home and where and where != home:
        return "foreign"
    return None


def apply_patch():
    global _orig_extra_conds, _applied

    if _applied:
        return True

    cls = getattr(model_base, "MiniMaxH3", None)
    if cls is None or not hasattr(cls, "extra_conds"):
        _LOG.warning(
            "MiniMax H3 Motion Context RAM: MiniMaxH3.extra_conds not found."
        )
        return False

    who = _already_patched(cls)
    if who == "foreign":
        _LOG.warning(
            "MiniMax H3 Motion Context RAM: another custom node already owns "
            "MiniMaxH3.extra_conds; refusing to stack incompatible patches."
        )
        return False

    if who in ("same", "other"):
        _applied = True
        _LOG.info(
            "MiniMax H3 Motion Context RAM: compatible keyframe/ref payload "
            "patch already active; standing down."
        )
        return True

    _orig_extra_conds = cls.extra_conds
    cls.extra_conds = _patched_extra_conds
    _applied = True
    _LOG.info(
        "MiniMax H3 Motion Context RAM: keyframe/ref coexistence enabled"
    )
    return True


def is_applied():
    return _applied
