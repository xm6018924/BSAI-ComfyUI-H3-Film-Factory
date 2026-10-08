
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

    if not keyframes and not refs:
        return out

    # v1.3 (2026-10-07) audiofix 触发条件放宽：
    # 旧版仅当 keyframes 含 MC_KEY 或 refs 含 MC_AUDIO_KEY 时才拼接 keyframes
    # 音频，但 ComfyUI 新版 native 布局的 keyframes 只带
    #   {"resolved_frame_index", "latent" | "audio_latent"}（无 MC_KEY），
    # 导致 native 分支直接 return、keyframes 音频丢失 →
    #   all_audio_rows[~audio_update] = cond_audio_rows  shape mismatch
    #   (keyframes 37步*2 + refs 490步*2 = 1054 vs refs-only 980)。
    # 现在：只要 keyframes 或 refs 任一非空即按「keyframes 先、refs 后」
    # 拼接（无 keyframes 时等价于 refs 列表本身，不改变普通 ref2va 行为）。

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
        [kf["latent"] for kf in (keyframes or []) if "latent" in kf]
        + [ref["latent"] for ref in (refs or []) if "latent" in ref]
    )
    # v1.2 audiofix (2026-10-07): audio must mirror video's keyframes-first
    # order too, otherwise PackedLayout's ~audio_update rows (keyframes audio +
    # refs audio, e.g. 74 + 1200 = 1274) exceed cond_audio_rows (refs audio
    # only, 1200) -> RuntimeError in model._embed_and_pack
    #   all_audio_rows[~audio_update] = cond_audio_rows  [1274,32] vs [1200,32].
    # Only chained clips (CLIP>=1, motion-context keyframes present) hit this;
    # the first clip has no keyframes and stock path stays intact.
    payload["cond_audio_latents"] = (
        [
            kf["audio_latent"]
            for kf in (keyframes or [])
            if kf.get("audio_latent") is not None
        ]
        + [
            ref["audio_latent"]
            for ref in (refs or [])
            if ref.get("audio_latent") is not None
        ]
    )

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
