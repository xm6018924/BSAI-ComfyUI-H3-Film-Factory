
"""
MiniMax H3 interior keyframe + timeline-audio patch.

Derived from the mechanism published in:
https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context
(GPL-3.0)

This copy is intentionally small and gated: stock H3 graphs remain untouched.
"""
import logging

import comfy.ldm.minimax.model as mm

MC_KEY = "motion_context_index"
MC_AUDIO_KEY = "motion_context_audio_end_frame"
PATCH_MARKER = "_h3_motion_context_layout_patch"

_LOG = logging.getLogger("minimax_h3_tail_from_latent.motion_context")
_orig_init = None
_applied = False

REF_SEGMENT_KINDS = ("ref_img", "ref_audio")


def _target_origin(layout):
    a, b, kind = layout.segments[-1]
    if kind != "video" or b <= a:
        raise RuntimeError(
            "MiniMax H3 Motion Context RAM: expected target video as final "
            f"PackedLayout segment, got {kind!r}."
        )
    return float(layout.position_ids[a, 0])


def _expected_ref_segments(blk):
    kind = blk.get("kind")
    if kind == "image":
        return ("ref_img",)
    if kind == "audio":
        return ("ref_audio",) if int(blk.get("ref_audio_t", 0)) > 0 else ()
    if kind in ("video", "video_audio"):
        if int(blk.get("ref_audio_t", 0)) > 0:
            return ("ref_audio", "ref_img")
        return ("ref_img",)
    raise RuntimeError(
        f"MiniMax H3 Motion Context RAM: unknown reference kind {kind!r}."
    )


def _ref_segment_map(layout, refs):
    ref_segs = [
        (a, b, kind)
        for a, b, kind in layout.segments
        if kind in REF_SEGMENT_KINDS
    ]
    wanted = [
        (idx, kind)
        for idx, blk in enumerate(refs or [])
        for kind in _expected_ref_segments(blk)
    ]
    if len(wanted) != len(ref_segs):
        raise RuntimeError(
            "MiniMax H3 Motion Context RAM: reference/layout segment count "
            f"mismatch ({len(wanted)} expected, {len(ref_segs)} present)."
        )

    out = {}
    for (idx, wanted_kind), (a, b, got_kind) in zip(wanted, ref_segs):
        if got_kind != wanted_kind:
            raise RuntimeError(
                "MiniMax H3 Motion Context RAM: reference segment order changed "
                f"upstream ({wanted_kind!r} expected, {got_kind!r} found)."
            )
        out.setdefault(idx, {})[wanted_kind] = (a, b)
    return out


def _cond_t(text_len, latent_t, frame_count, pixel_index):
    p = float(pixel_index)
    if p == 0.0:
        return float(text_len)
    if (
        frame_count is not None
        and abs(p - float(frame_count - 1)) < 1e-12
    ):
        return (
            float(text_len)
            + sum(mm._video_t_spans(latent_t))
            - mm.FRAME_RESCALE
        )
    return float(text_len) + mm.FRAME_RESCALE * p


def _fixup_keyframes(layout, text_len, latent_t, frame_count, keyframes):
    # Ref2VA reference blocks move the target origin forward. Motion-context
    # anchors must move with the target rather than staying glued to text_len.
    offset = _target_origin(layout) - float(text_len)

    if offset and any(kf.get(MC_KEY) is None for kf in keyframes):
        raise RuntimeError(
            "MiniMax H3 Motion Context RAM: stock keyframes and motion-context "
            "keyframes are mixed while Ref2VA references are present. Refusing "
            "to produce misaligned temporal coordinates."
        )

    cond_spans = [
        (a, b)
        for a, b, kind in layout.segments
        if kind == "cond"
    ]
    if len(cond_spans) != len(keyframes):
        raise RuntimeError(
            "MiniMax H3 Motion Context RAM: PackedLayout cond segment count "
            "does not match keyframe count."
        )

    for (a, b), kf in zip(cond_spans, keyframes):
        p = kf.get(MC_KEY)
        if p is None:
            continue
        layout.position_ids[a:b, 0] = (
            _cond_t(text_len, latent_t, frame_count, p) + offset
        )


def _fixup_audio(layout, refs):
    marked = [
        idx
        for idx, ref in enumerate(refs or [])
        if ref.get(MC_AUDIO_KEY) is not None
    ]
    if len(marked) != 1:
        raise RuntimeError(
            "MiniMax H3 Motion Context RAM: expected exactly one continuation "
            f"audio reference marker, found {len(marked)}."
        )

    idx = marked[0]
    blk = refs[idx]
    if blk.get("kind") != "audio":
        raise RuntimeError(
            "MiniMax H3 Motion Context RAM: timeline audio marker was attached "
            f"to {blk.get('kind')!r}, not an audio ref."
        )

    rt = int(blk.get("ref_audio_t", 0))
    if rt <= 0:
        return

    seg = _ref_segment_map(layout, refs).get(idx, {}).get("ref_audio")
    if seg is None:
        raise RuntimeError(
            "MiniMax H3 Motion Context RAM: continuation audio produced no "
            "ref_audio segment."
        )

    a, b = seg
    if b - a != 2 * rt:
        raise RuntimeError(
            "MiniMax H3 Motion Context RAM: unexpected audio row count "
            f"{b-a} for {rt} stereo latent steps."
        )

    target_origin = _target_origin(layout)
    slot_start = float(layout.position_ids[a, 0])
    end_frame = float(blk[MC_AUDIO_KEY])

    # End-align the carried audio to the end of the pinned picture on the
    # NEW clip's own timeline. This is the critical difference between
    # continuation and "reference audio that merely sounds similar".
    desired_start = (
        target_origin
        + mm.FRAME_RESCALE * end_frame
        - float(rt)
    )
    layout.position_ids[a:b, 0] = (
        layout.position_ids[a:b, 0] + (desired_start - slot_start)
    )


def _patched_init(
    self,
    text_len,
    latent_t,
    latent_h,
    latent_w,
    audio_t,
    keyframes=None,
    refs=None,
    frame_count=None,
):
    _orig_init(
        self,
        text_len,
        latent_t,
        latent_h,
        latent_w,
        audio_t,
        keyframes=keyframes,
        refs=refs,
        frame_count=frame_count,
    )

    if keyframes and any(kf.get(MC_KEY) is not None for kf in keyframes):
        _fixup_keyframes(
            self, text_len, latent_t, frame_count, keyframes
        )

    if refs and any(ref.get(MC_AUDIO_KEY) is not None for ref in refs):
        _fixup_audio(self, refs)


setattr(_patched_init, PATCH_MARKER, True)


def _already_patched():
    cls = getattr(mm, "PackedLayout", None)
    init = getattr(cls, "__init__", None)
    if init is None:
        return None
    if getattr(init, PATCH_MARKER, False):
        return "same"
    if getattr(init, "__name__", "") == "_patched_init":
        return "other"
    if hasattr(init, "__wrapped__"):
        return "foreign"
    home = getattr(cls, "__module__", None)
    where = getattr(init, "__module__", None)
    if home and where and where != home:
        return "foreign"
    return None


def _self_test():
    # Keep the test deliberately small but meaningful: stock builds both
    # condition blocks at frame 0, then our fixup must place the second at
    # frame 5 while preserving the reference-derived target origin.
    text_len, latent_t, lh, lw, audio_t = 7, 7, 8, 8, 16
    frame_count = sum(
        mm.FRAME_PER_TOKEN[k % 5] for k in range(latent_t)
    )

    dummy = object()
    kf = [
        {
            "resolved_frame_index": 0,
            MC_KEY: 0,
            "latent": dummy,
        },
        {
            "resolved_frame_index": 0,
            MC_KEY: 5,
            "latent": dummy,
        },
    ]

    lay = mm.PackedLayout.__new__(mm.PackedLayout)
    _orig_init(
        lay,
        text_len,
        latent_t,
        lh,
        lw,
        audio_t,
        keyframes=kf,
        refs=None,
        frame_count=frame_count,
    )
    _fixup_keyframes(lay, text_len, latent_t, frame_count, kf)

    cond_spans = [
        (a, b)
        for a, b, kind in lay.segments
        if kind == "cond"
    ]
    if len(cond_spans) != 2:
        raise RuntimeError("self-test: two cond spans were not built")

    t0 = float(lay.position_ids[cond_spans[0][0], 0])
    t1 = float(lay.position_ids[cond_spans[1][0], 0])
    if abs(t0 - float(text_len)) > 1e-9:
        raise RuntimeError(
            f"self-test: first anchor at {t0}, expected {text_len}"
        )
    expected = float(text_len) + mm.FRAME_RESCALE * 5.0
    if abs(t1 - expected) > 1e-9:
        raise RuntimeError(
            f"self-test: interior anchor at {t1}, expected {expected}"
        )


def apply_patch():
    global _orig_init, _applied

    if _applied:
        return True

    who = _already_patched()
    if who == "foreign":
        _LOG.warning(
            "MiniMax H3 Motion Context RAM: another custom node already owns "
            "PackedLayout.__init__; refusing to stack incompatible patches."
        )
        return False

    if who in ("same", "other"):
        _applied = True
        _LOG.info(
            "MiniMax H3 Motion Context RAM: compatible interior-anchor patch "
            "already active; standing down."
        )
        return True

    if not hasattr(mm, "PackedLayout") or not hasattr(mm, "FRAME_RESCALE"):
        _LOG.warning(
            "MiniMax H3 Motion Context RAM: current ComfyUI H3 model does not "
            "expose the expected PackedLayout API."
        )
        return False

    _orig_init = mm.PackedLayout.__init__
    try:
        _self_test()
    except Exception as exc:
        _orig_init = None
        _LOG.warning(
            "MiniMax H3 Motion Context RAM: layout self-test failed: %s", exc
        )
        return False

    mm.PackedLayout.__init__ = _patched_init
    _applied = True
    _LOG.info(
        "MiniMax H3 Motion Context RAM: interior keyframe anchors enabled"
    )
    return True


def is_applied():
    return _applied
