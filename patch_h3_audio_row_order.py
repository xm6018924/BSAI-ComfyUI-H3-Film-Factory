# -*- coding: utf-8 -*-
"""Owner-agnostic guard for the MiniMax H3 conditioning row invariant.

Why this exists
---------------
``PackedLayout`` (comfy/ldm/minimax/model.py) reserves conditioning rows in a
fixed segment order::

    keyframes carrying ``latent``       -> ``cond``      (and ``cond_audio``)
    refs                                -> ``ref_img``   (and ``ref_audio``)
    target audio / video               -> ``audio`` / ``video``

``_embed_and_pack`` then fills exactly those reserved rows with two masked
scatter assignments, one per modality::

    all_video_rows[~img_update]   = cond_video_rows
    all_audio_rows[~audio_update] = cond_audio_rows

Both right-hand sides are produced by walking ``payload["cond_*_latents"]``
**in list order**, two/four rows per entry. So those lists are not free-form
bags: any disagreement between what the layout reserved and what the payload
supplies is a hard crash, not a soft quality issue::

    RuntimeError: shape mismatch: value tensor of shape [1054, 32]
    cannot be broadcast to indexing result of shape [1128, 32]

Third-party wrappers on this exact site have shipped that bug. Both
``comfyui-h3-multishot/h3_avbank_probe.py`` and this plugin's
``patch_motion_payload.py`` rebuilt ``cond_audio_latents`` from
``minimax_refs`` ALONE, discarding the keyframe half - while the layout was
still reserving a ``cond_audio`` segment for every keyframe that carries
``audio_latent``. It stays hidden while no graph mixes keyframe audio WITH a
ref audio; the native Motion-Context guide audio (37 latent steps = 74 rows
here) plus a Ref2VA audio reference is exactly that case.

This module is the plugin-owned backstop: it wraps whatever
``MiniMaxH3.extra_conds`` currently is - whichever third-party wrapper won the
site - and rewrites the two lists into the layout's own order.

Why it claims the shared ABI markers
------------------------------------
A wrapper that stacks on top of this one re-breaks the list it just fixed. So
``apply_patch()`` claims the markers the other packs negotiate with
(``_h3_avbank_merge``, ``_h3_motion_context_payload_patch``). Both of them
explicitly stand down when they see a marker they recognise, rather than
wrapping - and both of their merges are now redundant anyway, because current
stock ``extra_conds`` already appends the ref latents instead of overwriting.
That is what makes import-time installation safe.

Why it is installed twice
-------------------------
``apply_patch()`` runs at import *and* is re-asserted at first execution (the
Motion-Context node, or the Film-Factory sampler).

- Import time closes the gap this module originally had: a hand-wired
  ``H3KeyframeInject`` plus a stock ``KSampler`` never reaches
  ``_sample_h3()`` / ``_ensure_patches()``, so without this the guard would
  simply not be installed for that graph - even though it carries exactly the
  keyframe + reference payload that triggers the bug.
- First execution is the safety net for the reverse ordering: anything that
  does manage to stack after startup gets wrapped over, putting the guard back
  on top.

Both call sites are safe to repeat: ``apply_patch()`` is self-detecting through
its own marker, so the second call is a cheap no-op.
"""
from __future__ import annotations

import functools
import logging

import comfy.model_base as _mb

_LOG = logging.getLogger("minimax_h3_film_factory.payload_row_order")

# Our own marker, plus the two ABI markers other packs already negotiate with:
#   _h3_motion_context_payload_patch : ComfyUI-H3-Motion-Context (this plugin's
#       own patch_motion_payload.py)
#   _h3_avbank_merge                : comfyui-h3-multishot/h3_avbank_probe.py
# Claiming them means a late-importing wrapper stands down instead of stacking
# on top of us - which would re-introduce the very bug this module removes.
MARKER = "_h3_film_factory_row_order"
_CLAIMED_MARKERS = (MARKER, "_h3_motion_context_payload_patch", "_h3_avbank_merge")

_reported = set()


def _expected_video_latents(keyframes, refs):
    """Latents in the order PackedLayout reserves their cond/ref_img rows.

    ``is not None`` rather than ``in``: the layout skips a None latent, so a
    present-but-None entry would shift every later row by one.
    """
    rows = [kf["latent"] for kf in (keyframes or ()) if kf.get("latent") is not None]
    rows += [r["latent"] for r in (refs or ()) if r.get("latent") is not None]
    return rows


def _expected_audio_latents(keyframes, refs):
    """Audio latents in the order PackedLayout reserves their cond/ref_audio rows."""
    rows = [kf["audio_latent"] for kf in (keyframes or ()) if kf.get("audio_latent") is not None]
    rows += [r["audio_latent"] for r in (refs or ()) if r.get("audio_latent") is not None]
    return rows


def _rows(latents):
    """Total rows a latent list contributes (pack_audio/patchify = 2*T / 4 rows)."""
    total = 0
    for z in latents:
        try:
            total += 2 * int(z.shape[-1])
        except Exception:
            return -1
    return total


def _normalize(payload, keyframes, refs):
    """Rewrite cond_*_latents to match the layout. Returns repaired field names."""
    fixed = []
    for field, expected in (
        ("cond_video_latents", _expected_video_latents(keyframes, refs)),
        ("cond_audio_latents", _expected_audio_latents(keyframes, refs)),
    ):
        current = payload.get(field) or []
        if len(current) == len(expected) and all(a is b for a, b in zip(current, expected)):
            continue
        # Identity, not equality: these are tensors, and == would broadcast.
        payload[field] = expected
        fixed.append((field, len(current), len(expected)))
    return fixed


def apply_patch():
    """Wrap the current MiniMaxH3.extra_conds. Idempotent; safe to call late."""
    cls = getattr(_mb, "MiniMaxH3", None)
    if cls is None or not hasattr(cls, "extra_conds"):
        _LOG.warning(
            "MiniMax H3 payload row-order guard: MiniMaxH3.extra_conds not found; "
            "keyframe/reference conditioning rows may mismatch the packed layout."
        )
        return False

    current = cls.extra_conds
    if getattr(current, MARKER, False):
        return True                      # already outermost, nothing to do

    @functools.wraps(current)
    def extra_conds(self, **kwargs):
        out = current(self, **kwargs)
        try:
            keyframes = kwargs.get("minimax_keyframes")
            refs = kwargs.get("minimax_refs")
            if not keyframes or not refs:
                return out               # one mechanism in play - leave it alone
            cond = out.get("minimax_payload", None)
            payload = getattr(cond, "cond", None) if cond is not None else None
            if not isinstance(payload, dict):
                return out
            for field, was, now in _normalize(payload, keyframes, refs):
                sig = (field, was, now)
                if sig in _reported:
                    continue
                _reported.add(sig)
                _LOG.warning(
                    "MiniMax H3 payload row-order guard: %s had %d entries, layout "
                    "order needs %d - rebuilt to match PackedLayout "
                    "(keyframes first, then references). Without this the sampler "
                    "fails with a raw 'shape mismatch' in _embed_and_pack.",
                    field, was, now,
                )
        except Exception:                 # never break conditioning
            _LOG.exception("MiniMax H3 payload row-order guard: repair failed; continuing.")
        return out

    for marker in _CLAIMED_MARKERS:
        setattr(extra_conds, marker, True)
    cls.extra_conds = extra_conds
    _LOG.info(
        "MiniMax H3 payload row-order guard active on top of %s",
        getattr(current, "__qualname__", repr(current)),
    )
    return True


def is_applied():
    cls = getattr(_mb, "MiniMaxH3", None)
    return bool(cls is not None and getattr(getattr(cls, "extra_conds", None), MARKER, False))


# Import-time install. Safe to do here because apply_patch() claims the avbank /
# motion-context ABI markers, so any wrapper that imports later recognises a
# compatible owner and stands down instead of stacking back over this fix (and
# their merges are redundant against current stock anyway). This is what covers
# hand-wired H3KeyframeInject + stock KSampler graphs that never reach
# _sample_h3() / _ensure_patches(). The execution-time call sites stay as a
# safety net and are no-ops once this has run.
try:
    apply_patch()
except Exception as _exc:               # never block node loading
    _LOG.warning("MiniMax H3 payload row-order guard: import-time install failed: %s", _exc)
