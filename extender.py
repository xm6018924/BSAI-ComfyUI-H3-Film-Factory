"""
MiniMax H3 Extender
===================

One horizontal, JS-driven sequence node that replaces the repeated
Ref2VA -> Motion Context -> Sampler -> Disk Join graph while keeping the
validated disk cache and the separate Final Decode / Preview node.

The node intentionally accepts an already-patched H3 MODEL. Sigma-shift,
LoRA, Spectrum or other model patches therefore remain external and compose
normally before the Extender.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import datetime as _datetime
import hashlib
import io
import json
import math
import os
import re
from pathlib import Path
import secrets
import shutil
import subprocess
import time
import uuid
import zipfile
import numpy as np
import torch
import torchaudio
import comfy.model_management
import comfy.nested_tensor
import comfy.sample
import comfy.samplers
import comfy.utils
import latent_preview
import node_helpers
import folder_paths
import threading
from aiohttp import web
from PIL import Image, ImageEnhance, ImageOps
from server import PromptServer

from .motion_context_ram import MiniMaxH3MotionContextRAM
from .prompt_bridge import PROMPT_PACK_TYPE, _prompt_pack_signature
from .motion_context_disk import (
    CACHE_VERSION,
    CACHE_TYPE,
    _DATA_START,
    _chain_paths,
    _decoded_preview_cache_path,
    _decoded_preview_video_cache_path,
    _ensure_cache_root,
    _safe_name,
    _write_json_atomic,
    MiniMaxH3MotionContextDiskJoin,
    MiniMaxH3MotionContextDiskFinalDecode,
    _cache_size_mb,
    _load_manifest_from_paths,
    _manifest_for_first,
    _truncate_chain,
    _export_live_candidate_preview,
    _decode_single_clip_to_blob,
    _load_segment_video,
    _load_segment_audio,
    _decode_single_audio,
    _find_ffmpeg,
    _copy_blob_to_file,
    _next_output_path,
    _comfy_media_item,
    _save_tail_latents,
    _restore_tail_latents,
    _save_tail_latents_to_disk,
    _load_tail_latents_from_disk,
    _delete_tail_latents_from_disk,
    _has_tail_latents_on_disk,
)

BUILD = "minimax-h3-extender-v14.67-compact-prompt-bridge"
FPS = 24
AUDIO_LATENT_FPS = 40


def _decode_single_clip_preview(owner, clip_index, vae, audio_vae, fps, ffmpeg=None):
    """Decode a single cached clip to MP4 and store as blob for frontend preview."""
    return _decode_single_clip_to_blob(
        owner_id=owner,
        clip_index=clip_index,
        vae=vae,
        audio_vae=audio_vae,
        fps=fps,
        ffmpeg=ffmpeg,
    )


# ---------------------------------------------------------------------------
# IMAGE + AUDIO per-CLIP streaming outputs (BSAI H3 Film Factory v14.70)
#
# Every clip is decoded to an IMAGE tensor [T,H,W,C] (float32, 0..1) plus an
# AUDIO dict as soon as it finishes sampling, pushed to the frontend over
# WebSocket (h3_extender_clip_av) and accumulated into the final IMAGE/AUDIO
# output ports.  This lets downstream upscale nodes (e.g. BSAI-H3-upscale-4K)
# consume the film as soon as the run returns, without a second VAE decode.
# ---------------------------------------------------------------------------


def _decode_clip_to_av(owner, clip_index, vae, audio_vae, fps):
    """Decode one cached clip to (IMAGE tensor, AUDIO dict), trimmed of the
    leading context overlap so downstream concatenation matches the Final
    Decode & Export output exactly."""
    data_path, manifest_path = _chain_paths(f"extender_{_safe_name(str(owner))}")
    manifest = _load_manifest_from_paths(data_path, manifest_path)
    if manifest is None:
        return None, None
    segments = [dict(x) for x in manifest.get("segments", [])]
    i = int(clip_index)
    if i < 0 or i >= len(segments):
        return None, None
    curr = segments[i]

    # Video latent -> pixels [T,C,H,W] in [0,1]
    try:
        v = _load_segment_video(data_path, curr)
        video = vae.decode(v)
        if video.ndim == 5:
            video = video.reshape(-1, video.shape[-3], video.shape[-2], video.shape[-1])
    except Exception as _e:
        print(f"[H3 Extender] _decode_clip_to_av video decode failed clip={i}: {_e}")
        return None, None

    trim = int(curr.get("trim_frames", 0)) if i > 0 else 0
    if trim > 0:
        video = video[trim:]
    if video.shape[0] == 0:
        return None, None
    images = video.movedim(1, -1).float().cpu().contiguous()  # [T,H,W,C]

    # Audio latent -> {waveform [B,C,L], sample_rate}
    audio = None
    try:
        if audio_vae is not None:
            audio = _decode_single_audio(data_path, curr, audio_vae, float(fps))
            if audio is not None and trim > 0:
                sr = int(audio["sample_rate"])
                trim_samples = int(round(float(trim) / float(fps) * sr))
                wave = audio["waveform"]
                if trim_samples > 0 and trim_samples < int(wave.shape[-1]):
                    audio = dict(audio)
                    audio["waveform"] = wave[..., trim_samples:]
    except Exception as _e:
        print(f"[H3 Extender] _decode_clip_to_av audio decode failed clip={i}: {_e}")
        audio = None

    return images, audio


def _send_clip_av_output(node_id, clip_index, clip_count, images, audio):
    """Lightweight per-clip readiness signal for the frontend.  The heavy
    IMAGE/AUDIO payloads travel through the node output ports; this event only
    tells the UI which clip just became available (each CLIP finishes -> its
    IMAGE+AUDIO are emitted before the next clip starts)."""
    try:
        server = PromptServer.instance
        if server is None:
            return
        payload = {
            "node": str(node_id),
            "clip_index": int(clip_index),
            "clip_count": int(clip_count),
            "frames": int(images.shape[0]) if images is not None else 0,
            "width": int(images.shape[2]) if images is not None else 0,
            "height": int(images.shape[1]) if images is not None else 0,
            "sample_rate": int(audio["sample_rate"]) if audio is not None else 0,
            "ready": True,
        }
        server.send_sync(
            "h3_extender_clip_av",
            payload,
            getattr(server, "client_id", None),
        )
    except Exception as _e:
        print(f"[H3 Extender] _send_clip_av_output error: {_e}")


def _concat_clip_av(images_list, audios_list):
    """Concatenate per-clip IMAGE tensors and AUDIO dicts into one IMAGE batch
    + one AUDIO dict (same format as ComfyUI IMAGE/AUDIO)."""
    imgs = [im for im in images_list if im is not None and int(im.shape[0]) > 0]
    if imgs:
        images = torch.cat(imgs, dim=0).float().cpu().contiguous()
    else:
        images = torch.zeros((0, 64, 64, 3), dtype=torch.float32)

    audios = [a for a in audios_list if a is not None and int(a["waveform"].shape[-1]) > 1]
    if audios:
        sr = int(audios[0]["sample_rate"])
        waves = [a["waveform"].cpu().float() for a in audios]
        max_ch = max(int(w.shape[1]) for w in waves)
        padded = []
        for w in waves:
            if int(w.shape[1]) < max_ch:
                pad = torch.zeros((w.shape[0], max_ch, w.shape[2]), dtype=w.dtype)
                pad[:, :w.shape[1], :] = w
                w = pad
            padded.append(w)
        waveform = torch.cat(padded, dim=-1)
        audio = {"waveform": waveform, "sample_rate": sr}
    else:
        audio = {"waveform": torch.zeros(1, 1, 1), "sample_rate": 32000}
    return images, audio


def _apply_h3_block_cache(model, residual_diff_threshold=0.12, cache_device="cpu"):
    """Best-effort integration of the F1B0 block-cache acceleration (from the
    T8 MiniMax H3 Block Cache plugin) straight into the Extender's own
    sequential clip sampling.  Reuses the proven residual cache so consecutive
    clips that stay temporally stable skip most DiT blocks.  If the T8 plugin
    is not installed, sampling silently continues without acceleration."""
    try:
        from comfy.ldm.minimax.model import MiniMaxH3Model
        diffusion_model = model.model.diffusion_model
        if not isinstance(diffusion_model, MiniMaxH3Model):
            print("[H3 Extender] block cache skipped: not a native MiniMax H3 model")
            return model

        import os as _os
        import sys as _sys
        t8_dir = None
        try:
            cnode_paths = folder_paths.get_folder_paths("custom_nodes")
        except Exception:
            cnode_paths = []
        for base in list(cnode_paths) + [os.path.join(folder_paths.base_path, "custom_nodes")]:
            cand = os.path.join(str(base), "comfyui-minimax-h3-blockcache-T8")
            if os.path.isdir(cand):
                t8_dir = cand
                break
        if t8_dir is None:
            raise RuntimeError("comfyui-minimax-h3-blockcache-T8 not installed")
        if t8_dir not in _sys.path:
            _sys.path.insert(0, t8_dir)

        import importlib.util as _ilu
        import types as _types
        cache_spec = _ilu.spec_from_file_location("_t8_h3_block_cache", os.path.join(t8_dir, "h3_block_cache.py"))
        cache_mod = _ilu.module_from_spec(cache_spec)
        cache_spec.loader.exec_module(cache_mod)
        CACHE_KEY = cache_mod.CACHE_KEY
        H3BlockCache = cache_mod.H3BlockCache
        H3BlockCacheConfig = cache_mod.H3BlockCacheConfig
        H3BlockPatch = cache_mod.H3BlockPatch
        _pkg = _types.ModuleType("_t8_plugin")
        _pkg.__path__ = [t8_dir]
        _sys.modules["_t8_plugin"] = _pkg
        _sys.modules["_t8_plugin.h3_block_cache"] = cache_mod
        nodes_spec = _ilu.spec_from_file_location("_t8_plugin.nodes", os.path.join(t8_dir, "nodes.py"))
        nodes_mod = _ilu.module_from_spec(nodes_spec)
        nodes_spec.loader.exec_module(nodes_mod)
        h3_block_cache_sample_wrapper = nodes_mod.h3_block_cache_sample_wrapper
        h3_block_cache_diffusion_wrapper = nodes_mod.h3_block_cache_diffusion_wrapper
        import comfy.patcher_extension as _pe

        total_blocks = len(diffusion_model.blocks)
        if total_blocks < 2:
            raise RuntimeError("H3 model has fewer than 2 DiT blocks")

        transformer_options = model.model_options["transformer_options"]
        if CACHE_KEY in transformer_options or "easycache" in transformer_options:
            print("[H3 Extender] block cache skipped: another cache already active")
            return model

        model = model.clone()
        config = H3BlockCacheConfig(
            residual_diff_threshold=float(residual_diff_threshold),
            start_percent=0.08,
            end_percent=0.95,
            max_consecutive_hits=2,
            cache_device=str(cache_device),
            metric_stride=8,
            verbose=False,
        )
        to = model.model_options["transformer_options"].copy()
        to[CACHE_KEY] = H3BlockCache(config, total_blocks)
        model.model_options["transformer_options"] = to

        model.set_model_patch_replace(H3BlockPatch(0), "dit", "double_block", 0)
        model.set_model_patch_replace(
            H3BlockPatch(total_blocks - 1), "dit", "double_block", total_blocks - 1
        )
        model.add_wrapper_with_key(
            _pe.WrappersMP.OUTER_SAMPLE, "minimax_h3_block_cache_t8", h3_block_cache_sample_wrapper
        )
        model.add_wrapper_with_key(
            _pe.WrappersMP.DIFFUSION_MODEL, "minimax_h3_block_cache_t8", h3_block_cache_diffusion_wrapper
        )
        print(f"[H3 Extender] block cache ACTIVE threshold={residual_diff_threshold} device={cache_device}")
        return model
    except Exception as _e:
        print(f"[H3 Extender] block cache unavailable, running without acceleration: {_e}")
        return model


def _apply_cache_dit(model, model_type="Auto", warmup_steps=0, skip_interval=0, print_summary=True):
    """Best-effort integration of ComfyUI-CacheDiT (DiT inter-step residual
    caching; MiniMax-H3 supported, ~1.41-1.50x) into the Extender's own clip
    sampling. If the plugin is not installed, sampling silently continues
    without it."""
    try:
        import os as _os
        import sys as _sys
        import importlib.util as _ilu
        import types as _types

        cd_dir = None
        try:
            cnode_paths = folder_paths.get_folder_paths("custom_nodes")
        except Exception:
            cnode_paths = []
        for base in list(cnode_paths) + [os.path.join(folder_paths.base_path, "custom_nodes")]:
            cand = os.path.join(str(base), "ComfyUI-CacheDiT")
            if os.path.isdir(cand):
                cd_dir = cand
                break
        if cd_dir is None:
            raise RuntimeError("ComfyUI-CacheDiT not installed")

        if cd_dir not in _sys.path:
            _sys.path.insert(0, cd_dir)

        _pkg = _types.ModuleType("_cache_dit_pkg")
        _pkg.__path__ = [cd_dir]
        _sys.modules["_cache_dit_pkg"] = _pkg

        utils_spec = _ilu.spec_from_file_location("_cache_dit_pkg.utils", os.path.join(cd_dir, "utils.py"))
        utils_mod = _ilu.module_from_spec(utils_spec)
        utils_spec.loader.exec_module(utils_mod)
        _sys.modules["_cache_dit_pkg.utils"] = utils_mod

        nodes_spec = _ilu.spec_from_file_location("_cache_dit_pkg.nodes", os.path.join(cd_dir, "nodes.py"))
        nodes_mod = _ilu.module_from_spec(nodes_spec)
        nodes_spec.loader.exec_module(nodes_mod)

        optimizer_cls = nodes_mod.CacheDiT_Model_Optimizer
        opt = optimizer_cls()
        out = opt.optimize(
            model,
            enable=True,
            model_type=str(model_type),
            warmup_steps=int(warmup_steps),
            skip_interval=int(skip_interval),
            print_summary=bool(print_summary),
        )
        if isinstance(out, (tuple, list)):
            out = out[0]
        print(f"[H3 Extender] CacheDiT ACTIVE model_type={model_type}")
        return out
    except Exception as _e:
        print(f"[H3 Extender] CacheDiT unavailable, running without it: {_e}")
        return model


CANVAS_MULTIPLE = 32
REF_IMAGE_SHORT_EDGE = 2048
MAX_CLIPS = 512
DEFAULT_DURATION = 10.0
DEFAULT_MEGAPIXELS = 0.40
MAX_RESOLUTION = 4096
DEFAULT_SEED_MAX = (1 << 53) - 1  # exact integer range in browser JS

PROJECT_FORMAT = "MiniMax H3 Extender Project"
PROJECT_FORMAT_VERSION = 2
PROJECT_SUPPORTED_VERSIONS = {1, 2}
PROJECT_JSON_MAX_BYTES = 16 * 1024 * 1024
PROJECT_DOWNLOAD_TTL_SECONDS = 2 * 60 * 60
PROJECT_COPY_CHUNK = 8 * 1024 * 1024
MAX_IMAGE_REFS = 9
REFS_JSON_VERSION = 2
MAX_REF_UPLOAD_BYTES = 256 * 1024 * 1024
MAX_REF_PIXELS = 120_000_000
_PROJECT_DOWNLOADS = {}


def _align_frame_count(n: int) -> int:
    n = max(5, int(n))
    while n % 17 != 5:
        n += 1
    return n


def _video_latent_t(frame_count: int) -> int:
    return 2 if frame_count <= 5 else ((frame_count - 5) // 17) * 5 + 2


def _duration_to_frames(seconds: float) -> int:
    raw = max(5, int(round(float(seconds) * FPS)))
    return _align_frame_count(raw)


def _empty_av_latent(width: int, height: int, frame_count: int):
    frame_count = _align_frame_count(frame_count)
    latent_t = _video_latent_t(frame_count)
    duration = frame_count / float(FPS)
    audio_t = round(duration * AUDIO_LATENT_FPS)
    device = comfy.model_management.intermediate_device()
    video = torch.zeros(
        [1, 24, latent_t, int(height) // 16, int(width) // 16],
        device=device,
    )
    audio = torch.zeros(
        [1, 32, 2, int(audio_t)],
        device=device,
    )
    return {"samples": comfy.nested_tensor.NestedTensor((video, audio))}


def _manual_effective_resolution(width: int, height: int):
    """Snap Manual/fallback resolution to MiniMax H3's 32-pixel canvas grid."""
    step = CANVAS_MULTIPLE
    w = max(step, min(MAX_RESOLUTION, (int(width) // step) * step))
    h = max(step, min(MAX_RESOLUTION, (int(height) // step) * step))
    return w, h


def _auto_resolution_from_dimensions(src_w: int, src_h: int, megapixels: float):
    """Auto resolution on H3's 32-pixel grid without exceeding the MP budget.

    H3's standard workflows use resolution_steps=32. For the Extender we snap
    DOWN to that grid rather than to the nearest value: this keeps every Auto
    canvas divisible by 32 while avoiding an upward size jump on borderline
    Dynamic-VRAM/AIMDO setups.

    Manual/fallback mode uses the same 32-pixel canvas grid, so every newly
    requested H3 resolution follows the same alignment rule.
    """
    src_w = int(src_w)
    src_h = int(src_h)
    if src_w <= 0 or src_h <= 0:
        raise ValueError("MiniMax H3 Extender: reference image has invalid dimensions.")

    mp = max(0.01, min(16.0, float(megapixels)))
    total = mp * 1024.0 * 1024.0
    scale_by = math.sqrt(total / float(src_w * src_h))
    scaled_w = float(src_w) * scale_by
    scaled_h = float(src_h) * scale_by

    if scaled_w > MAX_RESOLUTION or scaled_h > MAX_RESOLUTION:
        shrink = min(MAX_RESOLUTION / scaled_w, MAX_RESOLUTION / scaled_h)
        scaled_w *= shrink
        scaled_h *= shrink

    step = int(CANVAS_MULTIPLE)
    w = max(step, min(MAX_RESOLUTION, int(math.floor(scaled_w / step)) * step))
    h = max(step, min(MAX_RESOLUTION, int(math.floor(scaled_h / step)) * step))
    return w, h


def _auto_resolution_from_image(image, megapixels: float):
    if image is None or getattr(image, "ndim", 0) < 4:
        raise ValueError("MiniMax H3 Extender: invalid reference image for auto resolution.")
    return _auto_resolution_from_dimensions(
        int(image.shape[2]),
        int(image.shape[1]),
        megapixels,
    )


def _refs_root():
    root = _ensure_cache_root() / "_refs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _ref_id_is_safe(value):
    value = str(value or "").lower()
    return len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def _ref_path(ref_id):
    ref_id = str(ref_id or "").lower()
    if not _ref_id_is_safe(ref_id):
        raise ValueError("MiniMax H3 Extender: invalid internal reference id.")
    return _refs_root() / f"{ref_id}.png"


def _empty_refs():
    return [None for _ in range(MAX_IMAGE_REFS)]


def _normalize_ref_descriptor(value):
    if not isinstance(value, dict):
        return None
    ref_id = str(value.get("id") or value.get("ref_id") or "").lower().strip()
    if not _ref_id_is_safe(ref_id):
        return None
    try:
        width = int(value.get("width", 0) or 0)
        height = int(value.get("height", 0) or 0)
    except Exception:
        width = height = 0
    try:
        size_bytes = int(value.get("size_bytes", 0) or 0)
    except Exception:
        size_bytes = 0
    source_id = str(value.get("source_id") or value.get("original_id") or ref_id).lower().strip()
    if not _ref_id_is_safe(source_id):
        source_id = ref_id

    def _adjustment(name):
        try:
            number = float(value.get(name, 100) or 100)
        except Exception:
            number = 100.0
        if not math.isfinite(number):
            number = 100.0
        return max(0.0, min(200.0, number))

    return {
        "id": ref_id,
        "source_id": source_id,
        "original_name": str(value.get("original_name") or value.get("name") or "reference.png"),
        "width": max(0, width),
        "height": max(0, height),
        "size_bytes": max(0, size_bytes),
        "saturation": _adjustment("saturation"),
        "contrast": _adjustment("contrast"),
        "brightness": _adjustment("brightness"),
    }


def _normalize_ref_descriptors(refs):
    """Normalize nine stable logical ref slots without compacting holes."""
    source = list(refs or [])[:MAX_IMAGE_REFS]
    normalized = []
    for value in source:
        normalized.append(_normalize_ref_descriptor(value))
    normalized += [None] * (MAX_IMAGE_REFS - len(normalized))
    return normalized


def _parse_refs_json(raw):
    if isinstance(raw, dict):
        payload = raw
    else:
        try:
            payload = json.loads(str(raw or "{}"))
        except Exception:
            payload = {}
    values = payload.get("refs") if isinstance(payload, dict) else None
    if not isinstance(values, list):
        values = []
    refs = [_normalize_ref_descriptor(value) for value in values[:MAX_IMAGE_REFS]]
    refs += [None] * (MAX_IMAGE_REFS - len(refs))
    return _normalize_ref_descriptors(refs)


def _refs_json(refs):
    return json.dumps(
        {"version": REFS_JSON_VERSION, "refs": _normalize_ref_descriptors(refs)},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _refs_signature(refs):
    ids = [ref.get("id") if isinstance(ref, dict) else None for ref in _normalize_ref_descriptors(refs)]
    raw = json.dumps(ids, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _reference_count(refs):
    return sum(1 for ref in refs or [] if ref is not None)


def _validate_reference_file(path):
    path = Path(path)
    with Image.open(path) as image:
        width, height = map(int, image.size)
        if width <= 0 or height <= 0:
            raise ValueError("MiniMax H3 Extender: reference image has invalid dimensions.")
        if width * height > MAX_REF_PIXELS:
            raise ValueError(
                f"MiniMax H3 Extender: reference image is too large ({width}x{height})."
            )
        image.verify()
    return width, height


def _hash_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(PROJECT_COPY_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _store_uploaded_reference(source_path, original_name):
    """Normalize an uploaded reference to RGB PNG and store it content-addressed."""
    source_path = Path(source_path)
    temp_png = _refs_root() / f".upload_{uuid.uuid4().hex}.png"
    try:
        with Image.open(source_path) as source:
            source = ImageOps.exif_transpose(source)
            width, height = map(int, source.size)
            if width <= 0 or height <= 0:
                raise ValueError("MiniMax H3 Extender: reference image has invalid dimensions.")
            if width * height > MAX_REF_PIXELS:
                raise ValueError(
                    f"MiniMax H3 Extender: reference image is too large ({width}x{height})."
                )
            rgb = source.convert("RGB")
            rgb.save(temp_png, format="PNG", optimize=False, compress_level=4)

        ref_id = _hash_file(temp_png)
        target = _ref_path(ref_id)
        if target.exists():
            temp_png.unlink(missing_ok=True)
        else:
            os.replace(temp_png, target)
        return {
            "id": ref_id,
            "source_id": ref_id,
            "original_name": str(original_name or source_path.name or "reference.png"),
            "width": int(width),
            "height": int(height),
            "size_bytes": int(target.stat().st_size),
            "saturation": 100.0,
            "contrast": 100.0,
            "brightness": 100.0,
        }
    finally:
        try:
            temp_png.unlink(missing_ok=True)
        except Exception:
            pass


def _edit_internal_reference(source_id, original_name, brightness, contrast, saturation):
    """Render absolute photographic adjustments from the immutable source ref.

    Every edited descriptor keeps ``source_id`` pointing at the pixels that were
    originally loaded. Re-opening the editor therefore has an actual baseline:
    Reset = 100/100/100 against those original pixels, rather than 100% against
    the already edited derivative.
    """
    source_id = str(source_id or "").lower().strip()
    if not _ref_id_is_safe(source_id):
        raise ValueError("MiniMax H3 Extender: invalid source reference id.")

    source_path = _ref_path(source_id)
    if not source_path.exists():
        raise ValueError("MiniMax H3 Extender: original reference image not found.")

    def _factor(value, label):
        try:
            number = float(value)
        except Exception as exc:
            raise ValueError(f"MiniMax H3 Extender: invalid {label} value.") from exc
        if not math.isfinite(number) or number < 0.0 or number > 200.0:
            raise ValueError(f"MiniMax H3 Extender: {label} must be between 0 and 200 percent.")
        return number, number / 100.0

    brightness_value, brightness_factor = _factor(brightness, "brightness")
    contrast_value, contrast_factor = _factor(contrast, "contrast")
    saturation_value, saturation_factor = _factor(saturation, "saturation")

    temp_png = _refs_root() / f".edit_{uuid.uuid4().hex}.png"
    try:
        with Image.open(source_path) as source:
            image = source.convert("RGB")
            width, height = map(int, image.size)
            if width <= 0 or height <= 0:
                raise ValueError("MiniMax H3 Extender: reference image has invalid dimensions.")
            if width * height > MAX_REF_PIXELS:
                raise ValueError(
                    f"MiniMax H3 Extender: reference image is too large ({width}x{height})."
                )

            # Keep the order identical to the browser preview filter chain.
            if abs(brightness_factor - 1.0) > 1e-9:
                image = ImageEnhance.Brightness(image).enhance(brightness_factor)
            if abs(contrast_factor - 1.0) > 1e-9:
                image = ImageEnhance.Contrast(image).enhance(contrast_factor)
            if abs(saturation_factor - 1.0) > 1e-9:
                image = ImageEnhance.Color(image).enhance(saturation_factor)

            image.save(temp_png, format="PNG", optimize=False, compress_level=4)

        new_id = _hash_file(temp_png)
        target = _ref_path(new_id)
        if target.exists():
            temp_png.unlink(missing_ok=True)
        else:
            os.replace(temp_png, target)

        return {
            "id": new_id,
            "source_id": source_id,
            "original_name": str(original_name or "reference.png"),
            "width": int(width),
            "height": int(height),
            "size_bytes": int(target.stat().st_size),
            "saturation": float(saturation_value),
            "contrast": float(contrast_value),
            "brightness": float(brightness_value),
        }
    finally:
        try:
            temp_png.unlink(missing_ok=True)
        except Exception:
            pass

def _store_project_reference(source_path, original_name):
    """Validate an archived PNG and preserve its exact bytes/hash on import."""
    source_path = Path(source_path)
    width, height = _validate_reference_file(source_path)
    ref_id = _hash_file(source_path)
    target = _ref_path(ref_id)
    if not target.exists():
        temp = _refs_root() / f".import_{uuid.uuid4().hex}.png"
        shutil.copyfile(source_path, temp)
        try:
            os.replace(temp, target)
        finally:
            try:
                temp.unlink(missing_ok=True)
            except Exception:
                pass
    return {
        "id": ref_id,
        "source_id": ref_id,
        "original_name": str(original_name or "reference.png"),
        "width": int(width),
        "height": int(height),
        "size_bytes": int(target.stat().st_size),
        "saturation": 100.0,
        "contrast": 100.0,
        "brightness": 100.0,
    }


def _load_reference_tensor(ref):
    if not isinstance(ref, dict):
        raise ValueError("MiniMax H3 Extender: invalid internal reference metadata.")
    path = _ref_path(ref.get("id"))
    if not path.exists():
        raise FileNotFoundError(
            f"MiniMax H3 Extender: internal reference '{ref.get('original_name') or ref.get('id')}' is missing. "
            "Reload the reference image or load the portable .ext project that contains it."
        )
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        array = np.asarray(image, dtype=np.float32) / 255.0
    return torch.from_numpy(np.ascontiguousarray(array)).unsqueeze(0)


def _refs_from_project_payload(project_payload):
    extender = project_payload.get("extender", {}) if isinstance(project_payload, dict) else {}
    raw = extender.get("refs_json") if isinstance(extender, dict) else None
    if not raw:
        settings = extender.get("settings", {}) if isinstance(extender, dict) else {}
        raw = settings.get("refs_json") if isinstance(settings, dict) else None
    if not raw and isinstance(extender, dict) and isinstance(extender.get("references"), list):
        raw = {"version": REFS_JSON_VERSION, "refs": extender.get("references")}
    return _parse_refs_json(raw)


def _write_refs_to_project_payload(project_payload, refs):
    refs = _normalize_ref_descriptors(refs)
    extender = project_payload.setdefault("extender", {})
    raw = _refs_json(refs)
    extender["refs_json"] = raw
    extender["references"] = copy.deepcopy(refs)
    settings = extender.setdefault("settings", {})
    if isinstance(settings, dict):
        settings["refs_json"] = raw
    return refs


def _reference_dimensions(ref):
    if ref is None:
        return None
    if isinstance(ref, dict):
        try:
            width = int(ref.get("width", 0) or 0)
            height = int(ref.get("height", 0) or 0)
        except Exception:
            return None
        if width > 0 and height > 0:
            return width, height
        path = _ref_path(ref.get("id"))
        if path.exists():
            width, height = _validate_reference_file(path)
            ref["width"] = int(width)
            ref["height"] = int(height)
            return width, height
        return None
    if getattr(ref, "ndim", 0) >= 4:
        return int(ref.shape[2]), int(ref.shape[1])
    return None


def _select_resolution_guide(refs):
    """Ref 1 wins; otherwise the first available internal reference wins."""
    if refs and refs[0] is not None:
        return 1, refs[0]
    for index, image in enumerate(refs or [], start=1):
        if image is not None:
            return index, image
    return None, None


def _resolve_generation_resolution(resolution_mode, megapixels, width, height, refs):
    manual_w, manual_h = _manual_effective_resolution(width, height)
    mode = str(resolution_mode or "auto_from_ref")
    if mode == "manual":
        return {
            "width": manual_w,
            "height": manual_h,
            "mode": "manual",
            "guide_ref": None,
            "guide_src_width": 0,
            "guide_src_height": 0,
            "fallback": False,
            "megapixels": float(megapixels),
        }

    guide_index, guide = _select_resolution_guide(refs)
    dims = _reference_dimensions(guide) if guide is not None else None
    if guide is None or dims is None:
        return {
            "width": manual_w,
            "height": manual_h,
            "mode": "manual_fallback",
            "guide_ref": None,
            "guide_src_width": 0,
            "guide_src_height": 0,
            "fallback": True,
            "megapixels": float(megapixels),
        }

    src_w, src_h = dims
    resolved_w, resolved_h = _auto_resolution_from_dimensions(src_w, src_h, megapixels)
    return {
        "width": resolved_w,
        "height": resolved_h,
        "mode": "auto_from_ref",
        "guide_ref": int(guide_index),
        "guide_src_width": int(src_w),
        "guide_src_height": int(src_h),
        "fallback": False,
        "megapixels": float(megapixels),
    }

def _resolution_from_manifest(manifest):
    if not isinstance(manifest, dict):
        return None
    geom = manifest.get("geometry")
    if not isinstance(geom, dict):
        return None
    try:
        w = int(geom.get("video_w", 0)) * 16
        h = int(geom.get("video_h", 0)) * 16
    except Exception:
        return None
    if w <= 0 or h <= 0:
        return None
    return {"width": w, "height": h}


def _resize(image, width: int, height: int):
    samples = image[..., :3].movedim(-1, 1)
    samples = comfy.utils.common_upscale(
        samples, int(width), int(height), "lanczos", "disabled"
    )
    return samples.movedim(1, -1)


def _encode_ref_audio(audio_vae, audio):
    """Encode one standalone Ref2VA audio reference exactly like ComfyUI native H3."""
    waveform = audio["waveform"]  # [B, C, L]
    sr = int(audio["sample_rate"])
    vae_sr = int(getattr(audio_vae, "audio_sample_rate", 32000))
    if sr != vae_sr:
        waveform = torchaudio.functional.resample(waveform, sr, vae_sr)
    latent = audio_vae.encode(waveform[:1].movedim(1, -1))  # [1, 32, 2, T]
    return latent, int(latent.shape[-1])


def _prepare_shared_refs(
    vae,
    audio_vae,
    width: int,
    height: int,
    ref_image_size: str,
    refs,
    ref_audio=None,
):
    """Encode shared Ref2VA image refs plus one optional standalone audio ref.

    Ref slots are stable logical identities. Native H3 numbers only the active
    images contiguously, so we also return the logical slot order and remap
    <Picture N> tags just before tokenization. This lets Ref 3 stay Ref 3 even
    when Ref 2 is empty, without feeding a fake placeholder image to the model.
    """
    active = [
        (slot, image)
        for slot, image in enumerate(refs, start=1)
        if image is not None
    ]

    ref_items = []
    ref_blocks = []
    active_picture_slots = []
    for slot, ref in active:
        img = _load_reference_tensor(ref) if isinstance(ref, dict) else ref
        h, w = int(img.shape[1]), int(img.shape[2])
        if ref_image_size == "match":
            scale = min(1.0, math.sqrt((int(width) * int(height)) / float(w * h)))
        else:
            scale = min(1.0, REF_IMAGE_SHORT_EDGE / float(min(w, h)))

        tw = max(
            CANVAS_MULTIPLE,
            round(w * scale / CANVAS_MULTIPLE) * CANVAS_MULTIPLE,
        )
        th = max(
            CANVAS_MULTIPLE,
            round(h * scale / CANVAS_MULTIPLE) * CANVAS_MULTIPLE,
        )

        resized = _resize(img[:1], tw, th)
        z = vae.encode(resized)
        ref_items.append({"type": "image", "data": resized})
        active_picture_slots.append(int(slot))
        ref_blocks.append(
            {
                "kind": "image",
                "latent_h": th // 16,
                "latent_w": tw // 16,
                "latent": z,
            }
        )

    # Official Ref2VA presentation order is images first, then standalone audio.
    # The tokenizer assigns the standalone input the prompt label <Audio 1>.
    if ref_audio is not None:
        if audio_vae is None:
            raise ValueError(
                "MiniMax H3 Extender: ref_audio is connected but audio_vae is not. "
                "Connect the MiniMax H3 Audio VAE to audio_vae."
            )
        if not active:
            raise ValueError(
                "MiniMax H3 Extender: MiniMax H3 Ref2VA requires an audio "
                "reference to be used together with at least one image reference."
            )
        audio_latent, ref_audio_t = _encode_ref_audio(audio_vae, ref_audio)
        ref_items.append({"type": "audio"})
        ref_blocks.append(
            {
                "kind": "audio",
                "ref_audio_t": int(ref_audio_t),
                "audio_latent": audio_latent,
            }
        )

    return ref_items, ref_blocks, active_picture_slots


# ---------------------------------------------------------------------------
# v1.8 Ref2VA conditioning disk cache (CLIPCached-style, 2026-09).
# Image-reference VAE latents are content-addressed by ref hash + output size
# + ref_image_size. Re-running identical refs (new prompt / new seed) skips
# the repeated multi-image 2K VAE encode. Audio refs are re-encoded fresh.
# ---------------------------------------------------------------------------
_REF2VA_CACHE_DIRNAME = "_ref2va_cache"


def _ref2va_cache_key(vae, width, height, ref_image_size, refs):
    sig = _refs_signature(refs)
    vae_tag = vae.__class__.__name__ if vae is not None else "novae"
    try:
        vae_tag += ":" + str(getattr(vae, "model_name", "") or "")
    except Exception:
        pass
    raw = f"r2v|{sig}|{int(width)}x{int(height)}|{str(ref_image_size)}|{vae_tag}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:40]


def _ref2va_cache_path(key):
    root = _ensure_cache_root() / _REF2VA_CACHE_DIRNAME
    root.mkdir(parents=True, exist_ok=True)
    return root / (key + ".pt")


def _ref2va_cache_load(key):
    path = _ref2va_cache_path(key)
    if not path.exists():
        return None
    try:
        data = torch.load(path, map_location=comfy.model_management.intermediate_device())
        if isinstance(data, dict) and "items" in data and "blocks" in data and "slots" in data:
            return data
    except Exception as _e:
        print(f"[H3 Extender] ref2va cache load failed, will re-encode: {_e}")
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
    return None


def _ref2va_cache_save(key, items, blocks, slots):
    path = _ref2va_cache_path(key)
    tmp = path.with_suffix(".tmp")
    try:
        torch.save({"items": items, "blocks": blocks, "slots": slots}, tmp)
        os.replace(tmp, path)
    except Exception as _e:
        print(f"[H3 Extender] ref2va cache save failed (will re-encode next time): {_e}")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _prepare_shared_refs_cached(
    vae,
    audio_vae,
    width,
    height,
    ref_image_size,
    refs,
    ref_audio=None,
    enable_cache=True,
):
    """_prepare_shared_refs + disk cache for image-reference VAE latents."""
    if not enable_cache or not any(r is not None for r in refs or []):
        items, blocks, slots = _prepare_shared_refs(
            vae, audio_vae, width, height, ref_image_size, refs, ref_audio=ref_audio
        )
        return items, blocks, slots, False

    key = _ref2va_cache_key(vae, width, height, ref_image_size, refs)
    cached = _ref2va_cache_load(key)
    if cached is not None:
        items = list(cached["items"])
        blocks = list(cached["blocks"])
        slots = list(cached["slots"])
        if ref_audio is not None:
            if audio_vae is None:
                raise ValueError(
                    "MiniMax H3 Extender: ref_audio is connected but audio_vae is not. "
                    "Connect the MiniMax H3 Audio VAE to audio_vae."
                )
            if not items:
                raise ValueError(
                    "MiniMax H3 Extender: MiniMax H3 Ref2VA requires an audio "
                    "reference to be used together with at least one image reference."
                )
            audio_latent, ref_audio_t = _encode_ref_audio(audio_vae, ref_audio)
            items = items + [{"type": "audio"}]
            blocks = blocks + [
                {"kind": "audio", "ref_audio_t": int(ref_audio_t), "audio_latent": audio_latent}
            ]
        print(f"[H3 Extender] ref2va image cache HIT ({len(items)} ref_items) - skipped VAE encode")
        return items, blocks, slots, True

    items, blocks, slots = _prepare_shared_refs(
        vae, audio_vae, width, height, ref_image_size, refs, ref_audio=ref_audio
    )
    img_items = [it for it in items if it.get("type") == "image"]
    img_blocks = [b for b in blocks if b.get("kind") == "image"]
    _ref2va_cache_save(key, img_items, img_blocks, slots)
    print(f"[H3 Extender] ref2va cache MISS - encoded & saved ({len(img_items)} image refs)")
    return items, blocks, slots, False


_PICTURE_TAG_RE = re.compile(r"<Picture\s+(\d+)>", re.IGNORECASE)


def _remap_picture_tags(prompt: str, active_picture_slots):
    """Map stable UI Ref slots to H3's contiguous active Picture ordinals."""
    slot_to_ordinal = {
        int(slot): ordinal
        for ordinal, slot in enumerate(active_picture_slots or [], start=1)
    }

    def replace(match):
        slot = int(match.group(1))
        if slot < 1 or slot > MAX_IMAGE_REFS:
            return match.group(0)
        ordinal = slot_to_ordinal.get(slot)
        # Do not police the user's prompt. An empty logical slot may be an
        # accidental reference or an intentional use of native H3 numbering.
        # In that case leave the tag exactly as written and let H3 interpret it.
        if ordinal is None:
            return match.group(0)
        return f"<Picture {ordinal}>"

    return _PICTURE_TAG_RE.sub(replace, str(prompt))


def _make_ref2va_conditioning(
    clip,
    vae,
    prompt: str,
    width: int,
    height: int,
    frame_count: int,
    ref_items,
    ref_blocks,
    active_picture_slots,
):
    latent = _empty_av_latent(width, height, frame_count)
    resolved_prompt = _remap_picture_tags(prompt, active_picture_slots)
    print(f"[H3 Extender] _make_ref2va_conditioning: prompt='{resolved_prompt[:100]}'")
    print(f"[H3 Extender]   ref_items={len(ref_items) if ref_items else 0}, "
          f"ref_blocks={len(ref_blocks) if ref_blocks else 0}, "
          f"active_picture_slots={active_picture_slots}")
    if ref_items:
        for ri, item in enumerate(ref_items):
            if isinstance(item, dict):
                data = item.get("data")
                shape = tuple(data.shape) if data is not None and hasattr(data, 'shape') else None
                print(f"[H3 Extender]   ref_item[{ri}]: type={item.get('type')}, data_shape={shape}")
    tokens = clip.tokenize(resolved_prompt, minimax_ref_items=ref_items)
    # v1.23: TE 文本编码回到 GPU 且独占显存——编码前把其他已加载模型（尤其 H3 主模型）
    # 的权重强制移回 CPU（partially_unload(offload, 1e32) 才是真正释放显存的路径；
    # unload_all_models 走 detach 分支不释放 dynamic 显存，此前 OOM 根因）。编码完 TE 自动让位，采样时 H3 按需重载。
    try:
        import comfy.model_management as _cmm
        for _lm in list(_cmm.current_loaded_models):
            try:
                if _lm.model is not getattr(clip, "patcher", None):
                    _lm.model.partially_unload(_lm.model.offload_device, 1e32)
            except Exception:
                pass
        _cmm.soft_empty_cache(force=True)
    except Exception:
        pass
    try:
        cond = clip.encode_from_tokens_scheduled(tokens)
    finally:
        try:
            import torch as _torch
            _torch.cuda.synchronize()
        except Exception:
            pass
    if ref_blocks:
        cond = node_helpers.conditioning_set_values(
            cond, {"minimax_refs": ref_blocks}
        )
        print(f"[H3 Extender]   conditioning set with {len(ref_blocks)} minimax_refs blocks")
    else:
        print("[H3 Extender]   WARNING: no ref_blocks, conditioning has NO minimax_refs!")
    return cond, latent


class _BasicGuider(comfy.samplers.CFGGuider):
    def set_conds(self, positive):
        self.inner_set_conds({"positive": positive})


def _sigmas(model, scheduler: str, steps: int, denoise: float):
    steps = max(1, int(steps))
    denoise = float(denoise)
    if denoise <= 0.0:
        return torch.FloatTensor([])
    total_steps = steps
    if denoise < 1.0:
        total_steps = max(steps, int(steps / denoise))
    sigmas = comfy.samplers.calculate_sigmas(
        model.get_model_object("model_sampling"),
        str(scheduler),
        total_steps,
    ).cpu()
    return sigmas[-(steps + 1):]


def _sample_h3(model, conditioning, latent, seed: int, sampler_name: str, scheduler: str, steps: int, denoise: float,
               owner_id=None, clip_index=-1):
    if int(steps) < 1:
        raise ValueError("MiniMax H3 Extender: steps must be >= 1.")

    guider = _BasicGuider(model)
    guider.set_conds(conditioning)
    sampler = comfy.samplers.sampler_object(str(sampler_name))
    sigmas = _sigmas(model, scheduler, steps, denoise)

    latent_out = latent.copy()
    latent_image = latent["samples"]
    latent_image = comfy.sample.fix_empty_latent_channels(
        model,
        latent_image,
        latent.get("downscale_ratio_spacial", None),
        latent.get("downscale_ratio_temporal", None),
    )
    latent_out["samples"] = latent_image

    batch_inds = latent_out.get("batch_index", None)
    noise = comfy.sample.prepare_noise(latent_image, int(seed), batch_inds)
    noise_mask = latent_out.get("noise_mask", None)

    x0_output = {}
    total_steps = sigmas.shape[0] - 1

    # Create a custom callback that sends latent preview frames to the
    # frontend CLIP preview panel (instead of ComfyUI's built-in node preview).
    previewer = None
    if owner_id is not None and clip_index >= 0:
        try:
            previewer = latent_preview.get_previewer(model.load_device, model.model.latent_format)
        except Exception as _e:
            print(f"[H3 Extender] latent previewer init failed: {_e}")
            previewer = None
        if previewer is None:
            # Fallback: create a simple latent2rgb previewer using first 3 channels
            try:
                preview_x0_test = latent_image[:1]
                if hasattr(preview_x0_test, "is_nested") and preview_x0_test.is_nested:
                    preview_x0_test = preview_x0_test.tensors[0]
                ch = int(preview_x0_test.shape[1])
                # Build simple identity-like factors: map first 3 channels to RGB
                factors = [[1.0 if i == c else 0.0 for i in range(ch)] for c in range(min(3, ch))]
                while len(factors) < 3:
                    factors.append([0.0] * ch)
                previewer = latent_preview.Latent2RGBPreviewer(factors)
                print(f"[H3 Extender] using fallback Latent2RGB previewer (channels={ch})")
            except Exception as _e2:
                print(f"[H3 Extender] fallback previewer also failed: {_e2}")
                previewer = None

    pbar = comfy.utils.ProgressBar(total_steps)
    _last_sent_step = {"v": -1}

    def _latent_preview_callback(step, x0, x, total_steps_arg):
        pbar.update_absolute(step + 1, total_steps_arg)
        if owner_id is not None:
            # Only send every 2nd step to reduce bandwidth
            if step == total_steps_arg - 1 or step % 2 == 0:
                try:
                    preview_x0 = x0
                    if hasattr(preview_x0, "is_nested") and preview_x0.is_nested:
                        preview_x0 = preview_x0.tensors[0]
                    if previewer is not None:
                        img = previewer.decode_latent_to_preview(preview_x0)
                    else:
                        # Manual fallback: take first 3 channels, normalize to 0-255
                        # Handle 5D video latents by taking the first time step
                        t = preview_x0
                        if t.ndim == 5:
                            t = t[:, :, 0]
                        t = t[:1, :3] if t.shape[1] >= 3 else t[:1, :1].expand(1, 3, -1, -1)
                        t = ((t - t.min()) / (t.max() - t.min() + 1e-8) * 255).clamp(0, 255)
                        t = t.to(device="cpu", dtype=torch.uint8)
                        img = Image.fromarray(t[0].movedim(0, 2).numpy())
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=60)
                    jpeg_bytes = buf.getvalue()
                    if step == 0 or step == total_steps_arg - 1:
                        print(f"[H3 Extender] latent preview: clip={clip_index} step={step+1}/{total_steps_arg} "
                              f"bytes={len(jpeg_bytes)} previewer={'yes' if previewer else 'manual'}")
                    _send_latent_preview_frame(owner_id, clip_index, step + 1, total_steps_arg, jpeg_bytes)
                except Exception as _e:
                    print(f"[H3 Extender] latent preview callback error: {_e}")
                    import traceback
                    traceback.print_exc()

    callback = _latent_preview_callback if owner_id is not None else None
    disable_pbar = not comfy.utils.PROGRESS_BAR_ENABLED
    samples = guider.sample(
        noise,
        latent_image,
        sampler,
        sigmas,
        denoise_mask=noise_mask,
        callback=callback,
        disable_pbar=disable_pbar,
        seed=int(seed),
    )
    samples = samples.to(comfy.model_management.intermediate_device())

    out = latent_out.copy()
    out.pop("downscale_ratio_spacial", None)
    out.pop("downscale_ratio_temporal", None)
    out["samples"] = samples
    return out


def _normalize_color_adjustment(value=None):
    raw = value if isinstance(value, dict) else {}

    def _v(name, default=100.0, low=0.0, high=200.0):
        try:
            x = float(raw.get(name, default))
        except Exception:
            x = float(default)
        return max(float(low), min(float(high), x))

    return {
        "saturation": _v("saturation", 100.0, 0.0, 200.0),
        "contrast": _v("contrast", 100.0, 50.0, 150.0),
        "brightness": _v("brightness", 100.0, 50.0, 150.0),
    }


def _default_clip(index: int = 0):
    return {
        "id": f"clip_{index + 1}",
        "name": "",
        "prompt": "",
        "seed": int(secrets.randbelow(DEFAULT_SEED_MAX)),
        "seed_mode": "randomize",
        "duration": DEFAULT_DURATION,
        "validated": False,
        "context_enabled": True,
        "color_adjustment": _normalize_color_adjustment(),
    }


def _parse_clips_json(value: str):
    try:
        payload = json.loads(value or "{}")
    except Exception as exc:
        raise ValueError(f"MiniMax H3 Extender: invalid clips JSON: {exc}") from exc

    if isinstance(payload, list):
        clips = payload
    elif isinstance(payload, dict):
        clips = payload.get("clips", [])
    else:
        clips = []

    if not clips:
        clips = [_default_clip(0)]
    if len(clips) > MAX_CLIPS:
        raise ValueError(
            f"MiniMax H3 Extender: {len(clips)} clips requested; max is {MAX_CLIPS}."
        )

    out = []
    for i, raw in enumerate(clips):
        raw = raw if isinstance(raw, dict) else {}
        try:
            seed = int(raw.get("seed", 0))
        except Exception:
            seed = 0
        seed = max(0, min(DEFAULT_SEED_MAX, seed))

        try:
            duration = float(raw.get("duration", DEFAULT_DURATION))
        except Exception:
            duration = DEFAULT_DURATION
        duration = max(0.25, min(150.0, duration))

        seed_mode = str(raw.get("seed_mode", "randomize"))
        if seed_mode not in {"randomize", "fixed", "increment", "decrement"}:
            seed_mode = "randomize"

        out.append(
            {
                "id": str(raw.get("id") or f"clip_{i + 1}"),
                "name": str(raw.get("name", "")),
                "prompt": str(raw.get("prompt", "")),
                "seed": seed,
                "seed_mode": seed_mode,
                "duration": duration,
                "validated": bool(raw.get("validated", False)),
                "context_enabled": bool(raw.get("context_enabled", True)),
                "color_adjustment": _normalize_color_adjustment(raw.get("color_adjustment")),
                "render_enabled": bool(raw.get("render_enabled", True)),
                "replace_mode": bool(raw.get("replace_mode", False)),
            }
        )

    # Validation must always be a continuous prefix. Anything after the first
    # unvalidated clip depends on a clip that is not frozen yet.
    found_open = False
    for clip in out:
        if found_open:
            clip["validated"] = False
        elif not clip["validated"]:
            found_open = True

    return out


def _prompt_pack_signature_from_state(value):
    if isinstance(value, dict):
        payload = value
    else:
        try:
            payload = json.loads(str(value or "{}"))
        except Exception:
            payload = {}
    if not isinstance(payload, dict):
        return ""
    signature = str(payload.get("prompt_pack_signature") or "").lower().strip()
    if len(signature) != 64 or any(ch not in "0123456789abcdef" for ch in signature):
        return ""
    return signature


def _parse_clip_select(value, total_clips):
    """Parse clip_select string into a set of 0-indexed clip indices.

    Accepts: "all", "2", "2,3", "2-5", "1,3-5"
    Returns None for "all" (meaning: render every clip normally).
    Returns a set of 0-indexed ints for specific clips.
    """
    raw = str(value or "all").strip().lower()
    if not raw or raw == "all":
        return None

    indices = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(\d+)\s*-\s*(\d+)$", part)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if lo > hi:
                lo, hi = hi, lo
            for n in range(lo, hi + 1):
                idx = n - 1
                if 0 <= idx < total_clips:
                    indices.add(idx)
        else:
            try:
                idx = int(part) - 1
            except ValueError:
                continue
            if 0 <= idx < total_clips:
                indices.add(idx)

    if not indices:
        return None
    return indices


def _state_json(clips, prompt_pack_signature="", merge_output=False):
    payload = {"version": 1, "clips": clips}
    signature = str(prompt_pack_signature or "").lower().strip()
    if len(signature) == 64 and all(ch in "0123456789abcdef" for ch in signature):
        payload["prompt_pack_signature"] = signature
    if merge_output:
        payload["merge_output"] = True
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _merge_output_from_state(value: str):
    """Extract merge_output flag from clips_json state."""
    try:
        payload = json.loads(value or "{}")
        if isinstance(payload, dict):
            return bool(payload.get("merge_output", False))
    except Exception:
        pass
    return False


def _normalize_external_prompt_pack(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("MiniMax H3 Extender: external prompt pack is invalid.")

    prompts_raw = value.get("prompts")
    if not isinstance(prompts_raw, (list, tuple)):
        raise ValueError("MiniMax H3 Extender: external prompt pack has no prompt list.")

    prompts = []
    found_empty = False
    for index, raw in enumerate(list(prompts_raw)[:10], start=1):
        text = "" if raw is None else str(raw)
        if not text.strip():
            found_empty = True
            continue
        if found_empty:
            raise ValueError(
                "MiniMax H3 Extender: external prompt pack contains a gap before "
                f"prompt {index}."
            )
        prompts.append(text)

    if not prompts:
        raise ValueError("MiniMax H3 Extender: external prompt pack contains no prompts.")

    signature = _prompt_pack_signature(prompts)
    return {
        "type": PROMPT_PACK_TYPE,
        "version": int(value.get("version", 1) or 1),
        "source": str(value.get("source") or "External prompt pack"),
        "count": len(prompts),
        "prompts": prompts,
        "signature": signature,
    }


def _sync_clips_from_prompt_pack(clips, pack, stored_signature=""):
    """Import a changed pack into normal clip prompts and sync card count.

    A pack is an import source, not a second runtime prompt path. Once imported,
    the textarea prompt remains authoritative and can be edited normally. The
    same connected pack is therefore not copied again unless its content changes
    or the user changes the number of Extender cards while it is connected.
    """
    if pack is None:
        return clips, str(stored_signature or ""), False, False

    prompts = list(pack.get("prompts") or [])
    desired_count = len(prompts)
    signature = str(pack.get("signature") or "")
    count_changed = len(clips) != desired_count
    content_changed = signature != str(stored_signature or "")
    should_import = bool(count_changed or content_changed)

    if not should_import:
        return clips, signature, False, False

    synced = [dict(c) for c in list(clips)[:desired_count]]
    while len(synced) < desired_count:
        synced.append(_default_clip(len(synced)))

    for index, prompt in enumerate(prompts):
        synced[index]["prompt"] = str(prompt)

    return synced, signature, True, count_changed


def _manifest_for_extender(owner_id, fps=24.0):
    return _manifest_for_first(f"extender_{owner_id}", fps)


EXTENDER_PROGRESS_EVENT = "h3_extender_progress"
EXTENDER_LATENT_PREVIEW_EVENT = "h3_extender_latent_preview"
EXTENDER_PROMPT_PACK_EVENT = "h3_extender_prompt_pack_import"


def _send_extender_prompt_pack_import(node_id, clips_json, prompt_count, source=""):
    try:
        server = PromptServer.instance
        if server is None:
            return
        server.send_sync(
            EXTENDER_PROMPT_PACK_EVENT,
            {
                "node": str(node_id),
                "clips_json": str(clips_json),
                "prompt_count": int(prompt_count),
                "source": str(source or "External prompt pack"),
            },
            getattr(server, "client_id", None),
        )
    except Exception:
        # Prompt import UI feedback must never be able to break generation.
        pass


def _send_extender_progress(
    node_id,
    clip_index,
    clip_count,
    phase,
    message="",
):
    """
    Send a tiny live UI event while the single Extender node is still running.

    clip_index is 0-based internally. Use -1 to clear the active card.
    """
    try:
        server = PromptServer.instance
        if server is None:
            return
        payload = {
            "node": str(node_id),
            "clip_index": int(clip_index),
            "clip_count": int(clip_count),
            "phase": str(phase),
            "message": str(message),
        }
        # Target the currently connected execution client when available.
        server.send_sync(
            EXTENDER_PROGRESS_EVENT,
            payload,
            getattr(server, "client_id", None),
        )
    except Exception:
        # Progress UI must never be able to break generation.
        pass


# ---------------------------------------------------------------------------
# 暂停渲染控制（CLIP 选择生成 + 每 CLIP 间暂停/继续/仅当前/中止）
# ---------------------------------------------------------------------------
_render_ctl_lock = threading.Lock()
_render_ctl = {}


@PromptServer.instance.routes.post("/h3_extender/render_control")
async def render_control(request):
    """前端暂停控制端点：pause / resume / stop_after / abort。"""
    try:
        data = await request.json()
    except Exception:
        data = {}
    node_id = str(data.get("node") or "")
    action = str(data.get("action") or "")
    with _render_ctl_lock:
        ctl = _render_ctl.get(node_id)
        if ctl is None:
            return web.json_response({"ok": True, "state": "idle", "message": "当前无渲染进行"})
        if action == "pause":
            ctl["state"] = "pause_requested"
        elif action == "resume":
            ctl["state"] = "resume"
            ctl["event"].set()
        elif action == "stop_after":
            ctl["state"] = "stop_after"
            ctl["event"].set()
        elif action == "abort":
            ctl["state"] = "abort"
            ctl["event"].set()
            # 立即中断当前采样：终止即时生效，不等当前CLIP跑完
            try:
                comfy.model_management.interrupt_current_processing()
            except Exception as _ie:
                print(f"[H3 Extender] interrupt_current_processing failed: {_ie}")
        else:
            return web.json_response({"ok": False, "error": f"unknown action {action}"})
        return web.json_response({"ok": True, "state": ctl["state"]})


def _register_render_ctl(node_id):
    """开始渲染前注册控制条目（总是重置为运行态）。"""
    with _render_ctl_lock:
        _render_ctl[str(node_id)] = {"state": "running", "event": threading.Event()}


def _release_render_ctl(node_id):
    """渲染结束/中断后清理控制条目。"""
    with _render_ctl_lock:
        _render_ctl.pop(str(node_id), None)


def _maybe_pause_between(node_id, clip_index, loop_end, total, timeout):
    """每个CLIP生成完后、下一个开始前调用。

    仅当用户在前端点过「暂停」时才阻塞；否则立即返回 True。
    返回 True=继续渲染下一个；False=停止后续渲染（保留已生成的CLIP）。
    """
    with _render_ctl_lock:
        ctl = _render_ctl.get(str(node_id))
        if ctl is None or ctl.get("state") != "pause_requested":
            return True
        ctl["state"] = "paused"
        ctl["event"].clear()
    _send_extender_progress(
        node_id, clip_index, total, "paused",
        f"Clip {clip_index + 1} 已生成完成，渲染已暂停 — 可点「继续 / 仅当前 / 中止」，无干预 {int(timeout)}s 后自动继续",
    )
    decided = ctl["event"].wait(timeout)
    with _render_ctl_lock:
        state = ctl.get("state", "running")
        ctl["state"] = "running"
    if not decided:
        _send_extender_progress(
            node_id, clip_index, total, "resumed",
            f"暂停超时无干预 → 自动继续渲染 Clip {clip_index + 2}",
        )
        return True
    if state == "resume":
        _send_extender_progress(
            node_id, clip_index, total, "resumed",
            f"用户点击「继续」→ 渲染 Clip {clip_index + 2}",
        )
        return True
    if state == "stop_after":
        _send_extender_progress(
            node_id, clip_index, total, "stopped",
            "已停止后续渲染：仅保留已生成的 CLIP（可点「合并输出」合成视频）",
        )
        return False
    if state == "abort":
        _send_extender_progress(
            node_id, clip_index, total, "aborted",
            "渲染已中止",
        )
        return False
    return True


def _send_latent_preview_frame(node_id, clip_index, step, total_steps, jpeg_bytes):
    """Send a single latent preview frame (as base64 JPEG) to the frontend."""
    try:
        server = PromptServer.instance
        if server is None or not jpeg_bytes:
            return
        b64 = base64.b64encode(jpeg_bytes).decode("ascii")
        payload = {
            "node": str(node_id),
            "clip_index": int(clip_index),
            "step": int(step),
            "total_steps": int(total_steps),
            "image": "data:image/jpeg;base64," + b64,
        }
        server.send_sync(
            EXTENDER_LATENT_PREVIEW_EVENT,
            payload,
            getattr(server, "client_id", None),
        )
    except Exception as _e:
        print(f"[H3 Extender] _send_latent_preview_frame error: {_e}")


def _project_now_iso():
    return _datetime.datetime.now(_datetime.timezone.utc).isoformat()


def _project_filename(value):
    stem = _safe_name(Path(str(value or "MiniMax_H3_Project")).stem)
    return f"{stem}.ext"


def _project_temp_root():
    root = _ensure_cache_root() / "_projects"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_project_downloads():
    now = time.time()
    stale = []
    for token, info in list(_PROJECT_DOWNLOADS.items()):
        if now - float(info.get("created_at", 0.0)) > PROJECT_DOWNLOAD_TTL_SECONDS:
            stale.append((token, info))
    for token, info in stale:
        _PROJECT_DOWNLOADS.pop(token, None)
        try:
            Path(info.get("path", "")).unlink(missing_ok=True)
        except Exception:
            pass
    # Also clean abandoned downloads left by a previous ComfyUI process where
    # the in-memory token table no longer exists.
    try:
        for path in _project_temp_root().glob("download_*.ext"):
            if now - float(path.stat().st_mtime) > PROJECT_DOWNLOAD_TTL_SECONDS:
                path.unlink(missing_ok=True)
    except Exception:
        pass


def _prompt_pack_signature_from_project_payload(project_payload):
    extender = project_payload.get("extender", {}) if isinstance(project_payload, dict) else {}
    raw = extender.get("clips_json")
    if not isinstance(raw, str) or not raw.strip():
        settings = extender.get("settings", {}) if isinstance(extender, dict) else {}
        raw = settings.get("clips_json") if isinstance(settings, dict) else None
    return _prompt_pack_signature_from_state(raw)


def _clips_from_project_payload(project_payload):
    extender = project_payload.get("extender", {}) if isinstance(project_payload, dict) else {}
    raw = extender.get("clips_json")
    if not isinstance(raw, str) or not raw.strip():
        settings = extender.get("settings", {}) if isinstance(extender, dict) else {}
        raw = settings.get("clips_json") if isinstance(settings, dict) else None
    if not isinstance(raw, str) or not raw.strip():
        clips = extender.get("clips") if isinstance(extender, dict) else None
        if isinstance(clips, list):
            raw = json.dumps({"version": 1, "clips": clips}, ensure_ascii=False)
    if not isinstance(raw, str) or not raw.strip():
        raw = _state_json([_default_clip(0)])
    return _parse_clips_json(raw)


def _project_cache_snapshot(owner_id, project_payload):
    """Return a coherent, immutable manifest snapshot and byte limit.

    The .h3cache is append-only for a live tail. We snapshot the atomically-written
    manifest first, then copy only through the last referenced segment_end. If a
    generation starts concurrently, extra bytes appended after that boundary are
    intentionally excluded from the project.
    """
    data_path, manifest_path = _chain_paths(f"extender_{_safe_name(owner_id)}")
    if not data_path.exists() or not manifest_path.exists():
        return None

    manifest = _load_manifest_from_paths(data_path, manifest_path)
    if manifest is None:
        return None
    manifest = copy.deepcopy(manifest)
    segments = [dict(x) for x in manifest.get("segments", [])]

    # The UI state is the authority for explicit validation. Persist it into the
    # project snapshot without mutating the user's live cache manifest.
    try:
        clips = _clips_from_project_payload(project_payload)
    except Exception:
        clips = []
    for i, desc in enumerate(segments):
        desc["validated"] = bool(i < len(clips) and clips[i].get("validated", False))
    manifest["segments"] = segments

    if segments:
        data_limit = int(segments[-1].get("segment_end", 0))
    else:
        data_limit = int(_DATA_START)
    if data_limit < int(_DATA_START):
        raise ValueError("MiniMax H3 Extender Project: invalid cache byte boundary.")
    if int(data_path.stat().st_size) < data_limit:
        raise IOError("MiniMax H3 Extender Project: cache changed while snapshotting; retry Save Project.")

    return {
        "data_path": data_path,
        "manifest_path": manifest_path,
        "preview_path": _decoded_preview_cache_path(data_path),
        "manifest": manifest,
        "data_limit": data_limit,
    }


def _zip_write_prefix(zf, arcname, source_path, byte_limit):
    source_path = Path(source_path)
    remaining = int(byte_limit)
    info = zipfile.ZipInfo(str(arcname))
    info.compress_type = zipfile.ZIP_STORED
    info.date_time = time.localtime(source_path.stat().st_mtime)[:6]
    with open(source_path, "rb") as src, zf.open(info, "w", force_zip64=True) as dst:
        while remaining > 0:
            chunk = src.read(min(PROJECT_COPY_CHUNK, remaining))
            if not chunk:
                raise IOError(
                    f"MiniMax H3 Extender Project: source cache ended {remaining} byte(s) early."
                )
            dst.write(chunk)
            remaining -= len(chunk)


def _build_project_archive(owner_id, requested_name, project_payload, output_path):
    project_payload = copy.deepcopy(project_payload)
    refs = _refs_from_project_payload(project_payload)
    refs = _write_refs_to_project_payload(project_payload, refs)

    # A portable project is only useful when every referenced image is actually
    # embedded. Fail loudly instead of silently writing a project that depends on
    # a local cache entry which may not exist on the destination machine.
    ref_files = []
    source_ref_files = []
    for index, ref in enumerate(refs, start=1):
        if ref is None:
            continue
        path = _ref_path(ref.get("id"))
        if not path.exists():
            raise FileNotFoundError(
                f"MiniMax H3 Extender Project: reference {index} is missing from the internal store. "
                "Reload that reference image before saving the project."
            )
        width, height = _validate_reference_file(path)
        ref["width"] = int(width)
        ref["height"] = int(height)
        ref["size_bytes"] = int(path.stat().st_size)
        ref_files.append((index, ref, path))

        # If the visible ref is an edited derivative, also embed the immutable
        # source pixels. This keeps Reset meaningful after Save/Load and on
        # another machine.
        source_id = str(ref.get("source_id") or ref.get("id") or "").lower().strip()
        if source_id != str(ref.get("id") or "").lower().strip():
            source_path = _ref_path(source_id)
            if not source_path.exists():
                raise FileNotFoundError(
                    f"MiniMax H3 Extender Project: original source for reference {index} is missing. "
                    "Reload that reference image before saving the project."
                )
            _validate_reference_file(source_path)
            source_ref_files.append((index, source_id, source_path))
    _write_refs_to_project_payload(project_payload, refs)

    snapshot = _project_cache_snapshot(owner_id, project_payload)

    if snapshot is not None:
        cache_resolution = _resolution_from_manifest(snapshot.get("manifest"))
        if cache_resolution is not None:
            extender_payload = project_payload.setdefault("extender", {})
            resolution = extender_payload.setdefault("resolution", {})
            if isinstance(resolution, dict):
                resolution["resolved_width"] = int(cache_resolution["width"])
                resolution["resolved_height"] = int(cache_resolution["height"])
                resolution["source"] = "disk_cache"

    archive_meta = {
        "format": PROJECT_FORMAT,
        "format_version": PROJECT_FORMAT_VERSION,
        "created_at": _project_now_iso(),
        "extender_build": BUILD,
        "cache_version": CACHE_VERSION,
        "source_owner_id": str(owner_id),
        "project_name": Path(_project_filename(requested_name)).stem,
        "project": project_payload,
        "references": {
            "count": int(len(ref_files)),
            "embedded": True,
            "original_sources": int(len(source_ref_files)),
        },
        "cache": {
            "present": snapshot is not None,
            "clip_count": int(len(snapshot["manifest"].get("segments", []))) if snapshot else 0,
            "frame_count": int(snapshot["manifest"].get("final_frame_count", 0)) if snapshot else 0,
            "has_committed_preview": bool(snapshot and snapshot["preview_path"].exists()),
        },
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        project_bytes = json.dumps(
            archive_meta,
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")
        zf.writestr("project.json", project_bytes, compress_type=zipfile.ZIP_DEFLATED)

        for index, ref, path in ref_files:
            zf.write(
                path,
                arcname=f"refs/ref_{index}.png",
                compress_type=zipfile.ZIP_STORED,
            )
        for index, source_id, source_path in source_ref_files:
            zf.write(
                source_path,
                arcname=f"refs/original_ref_{index}.png",
                compress_type=zipfile.ZIP_STORED,
            )

        if snapshot is not None:
            manifest_bytes = json.dumps(
                snapshot["manifest"],
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            zf.writestr("cache/chain.json", manifest_bytes, compress_type=zipfile.ZIP_DEFLATED)
            _zip_write_prefix(
                zf,
                "cache/chain.h3cache",
                snapshot["data_path"],
                snapshot["data_limit"],
            )
            if snapshot["preview_path"].exists():
                zf.write(
                    snapshot["preview_path"],
                    arcname="cache/chain.preview.mp4",
                    compress_type=zipfile.ZIP_STORED,
                )
    return archive_meta

def _safe_zip_member(name):
    value = str(name or "").replace("\\", "/")
    if not value or value.startswith("/"):
        return False
    parts = [p for p in value.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return False
    return True


def _zip_copy_member(zf, member_name, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zf.open(member_name, "r") as src, open(destination, "wb") as dst:
        while True:
            chunk = src.read(PROJECT_COPY_CHUNK)
            if not chunk:
                break
            dst.write(chunk)
        dst.flush()
        os.fsync(dst.fileno())


def _replace_cache_transaction(owner_id, new_data=None, new_manifest=None, new_preview=None):
    target_data, target_manifest = _chain_paths(f"extender_{_safe_name(owner_id)}")
    target_preview = _decoded_preview_cache_path(target_data)
    target_preview_video = _decoded_preview_video_cache_path(target_data)
    # The video-only preview prefix is a derived v14.42 sidecar. It is not
    # required in .ext archives, but it MUST be cleared on project replacement
    # so a previous project's prefix can never be reused accidentally.
    targets = [target_data, target_manifest, target_preview, target_preview_video]
    backups = []
    token = uuid.uuid4().hex[:10]

    try:
        for target in targets:
            if target.exists():
                backup = target.with_name(target.name + f".project_backup_{token}")
                os.replace(target, backup)
                backups.append((target, backup))

        if new_data is not None and new_manifest is not None:
            os.replace(str(new_data), target_data)
            os.replace(str(new_manifest), target_manifest)
            if new_preview is not None and Path(new_preview).exists():
                os.replace(str(new_preview), target_preview)
        # No imported cache means an intentionally empty project. The old cache
        # remains only in backups until this transaction succeeds.
    except Exception:
        for target in targets:
            try:
                target.unlink(missing_ok=True)
            except Exception:
                pass
        for target, backup in reversed(backups):
            if backup.exists():
                os.replace(backup, target)
        raise
    else:
        for _, backup in backups:
            try:
                backup.unlink(missing_ok=True)
            except Exception:
                pass


def _import_project_archive(owner_id, archive_path):
    archive_path = Path(archive_path)
    work_root = _project_temp_root() / f"import_{uuid.uuid4().hex}"
    work_root.mkdir(parents=True, exist_ok=True)
    new_data = work_root / "chain.h3cache"
    new_manifest = work_root / "chain.json"
    new_preview = work_root / "chain.preview.mp4"

    try:
        with zipfile.ZipFile(archive_path, "r", allowZip64=True) as zf:
            for info in zf.infolist():
                if not _safe_zip_member(info.filename):
                    raise ValueError(
                        f"MiniMax H3 Extender Project: unsafe ZIP entry '{info.filename}'."
                    )

            names = set(zf.namelist())
            if "project.json" not in names:
                raise ValueError("MiniMax H3 Extender Project: project.json is missing.")
            pinfo = zf.getinfo("project.json")
            if int(pinfo.file_size) > PROJECT_JSON_MAX_BYTES:
                raise ValueError("MiniMax H3 Extender Project: project.json is unexpectedly large.")

            with zf.open("project.json", "r") as f:
                archive_meta = json.loads(f.read().decode("utf-8"))
            if archive_meta.get("format") != PROJECT_FORMAT:
                raise ValueError("MiniMax H3 Extender Project: unsupported project file.")
            format_version = int(archive_meta.get("format_version", -1))
            if format_version not in PROJECT_SUPPORTED_VERSIONS:
                supported = ", ".join(str(v) for v in sorted(PROJECT_SUPPORTED_VERSIONS))
                raise ValueError(
                    "MiniMax H3 Extender Project: incompatible project format "
                    f"{format_version} (supported: {supported})."
                )

            project_payload = archive_meta.get("project", {})
            if not isinstance(project_payload, dict):
                raise ValueError("MiniMax H3 Extender Project: invalid project metadata.")
            clips = _clips_from_project_payload(project_payload)
            project_prompt_pack_signature = _prompt_pack_signature_from_project_payload(project_payload)

            # v2 embeds the real reference pixels. Import each image into the
            # Extender's content-addressed store and rewrite the returned project
            # metadata to the local ids. v1 projects remain fully loadable; they
            # simply have no embedded internal references.
            saved_refs = _refs_from_project_payload(project_payload)
            imported_refs = _empty_refs()
            if format_version >= 2:
                for index in range(1, MAX_IMAGE_REFS + 1):
                    member = f"refs/ref_{index}.png"
                    saved = saved_refs[index - 1]
                    if member not in names:
                        if saved is not None:
                            raise ValueError(
                                f"MiniMax H3 Extender Project: embedded reference {index} is missing."
                            )
                        continue
                    ref_info = zf.getinfo(member)
                    if int(ref_info.file_size) > MAX_REF_UPLOAD_BYTES:
                        raise ValueError(
                            f"MiniMax H3 Extender Project: reference {index} exceeds the allowed image size."
                        )
                    extracted = work_root / f"ref_{index}.png"
                    _zip_copy_member(zf, member, extracted)
                    desc = _store_project_reference(
                        extracted,
                        (saved or {}).get("original_name") if isinstance(saved, dict) else f"ref_{index}.png",
                    )
                    if isinstance(saved, dict) and saved.get("id") and desc["id"] != saved.get("id"):
                        raise ValueError(
                            f"MiniMax H3 Extender Project: reference {index} failed its integrity check."
                        )

                    saved_source_id = (
                        str(saved.get("source_id") or saved.get("id") or desc["id"]).lower().strip()
                        if isinstance(saved, dict)
                        else desc["id"]
                    )
                    source_member = f"refs/original_ref_{index}.png"
                    if source_member in names:
                        source_info = zf.getinfo(source_member)
                        if int(source_info.file_size) > MAX_REF_UPLOAD_BYTES:
                            raise ValueError(
                                f"MiniMax H3 Extender Project: original reference {index} exceeds the allowed image size."
                            )
                        source_extracted = work_root / f"original_ref_{index}.png"
                        _zip_copy_member(zf, source_member, source_extracted)
                        source_desc = _store_project_reference(
                            source_extracted,
                            (saved or {}).get("original_name") if isinstance(saved, dict) else f"ref_{index}.png",
                        )
                        if _ref_id_is_safe(saved_source_id) and source_desc["id"] != saved_source_id:
                            raise ValueError(
                                f"MiniMax H3 Extender Project: original reference {index} failed its integrity check."
                            )
                        desc["source_id"] = source_desc["id"]
                    else:
                        # v2 projects created before v14.49 only embedded the
                        # currently used pixels. They remain loadable; that image
                        # becomes their reset baseline because the older archive
                        # contains no recoverable original.
                        desc["source_id"] = desc["id"]

                    if isinstance(saved, dict) and desc["source_id"] != desc["id"]:
                        for key in ("saturation", "contrast", "brightness"):
                            try:
                                desc[key] = max(0.0, min(200.0, float(saved.get(key, 100) or 100)))
                            except Exception:
                                desc[key] = 100.0
                    imported_refs[index - 1] = desc
                imported_refs = _normalize_ref_descriptors(imported_refs)
            _write_refs_to_project_payload(project_payload, imported_refs)

            has_data = "cache/chain.h3cache" in names
            has_manifest = "cache/chain.json" in names
            if has_data != has_manifest:
                raise ValueError("MiniMax H3 Extender Project: incomplete cache payload.")

            imported_manifest = None
            if has_data:
                _zip_copy_member(zf, "cache/chain.h3cache", new_data)
                _zip_copy_member(zf, "cache/chain.json", new_manifest)
                if "cache/chain.preview.mp4" in names:
                    _zip_copy_member(zf, "cache/chain.preview.mp4", new_preview)

                imported_manifest = _load_manifest_from_paths(new_data, new_manifest)
                if imported_manifest is None:
                    raise ValueError("MiniMax H3 Extender Project: cache manifest is empty.")

                # A hand-edited project may contain fewer cards than cached clips.
                # Keep only the portable prefix represented by the saved UI state.
                if len(imported_manifest.get("segments", [])) > len(clips):
                    imported_manifest = _truncate_chain(
                        new_data,
                        new_manifest,
                        imported_manifest,
                        len(clips),
                    )

                segments = [dict(x) for x in imported_manifest.get("segments", [])]
                for i, desc in enumerate(segments):
                    desc["validated"] = bool(i < len(clips) and clips[i].get("validated", False))
                imported_manifest = dict(imported_manifest)
                imported_manifest["segments"] = segments
                imported_manifest["owner_id"] = f"extender_{_safe_name(owner_id)}"
                imported_manifest["imported_at"] = time.time()
                imported_manifest["updated_at"] = time.time()
                _write_json_atomic(new_manifest, imported_manifest)

                imported_resolution = _resolution_from_manifest(imported_manifest)
                if imported_resolution is not None:
                    extender_payload = project_payload.setdefault("extender", {})
                    resolution = extender_payload.setdefault("resolution", {})
                    if isinstance(resolution, dict):
                        resolution["resolved_width"] = int(imported_resolution["width"])
                        resolution["resolved_height"] = int(imported_resolution["height"])
                        resolution["source"] = "disk_cache"

            cached_count = int(len(imported_manifest.get("segments", []))) if imported_manifest else 0
            # A clip can only remain validated when its physical cached segment is
            # present. Normalize the returned UI state accordingly.
            for i in range(cached_count, len(clips)):
                clips[i]["validated"] = False
            found_open = False
            for clip_cfg in clips:
                if found_open:
                    clip_cfg["validated"] = False
                elif not clip_cfg["validated"]:
                    found_open = True

            normalized_clips_json = _state_json(clips, project_prompt_pack_signature)
            extender_payload = project_payload.setdefault("extender", {})
            extender_payload["clips_json"] = normalized_clips_json
            extender_payload["clips"] = clips
            settings = extender_payload.setdefault("settings", {})
            if isinstance(settings, dict):
                settings["clips_json"] = normalized_clips_json

            _replace_cache_transaction(
                owner_id,
                new_data if imported_manifest is not None else None,
                new_manifest if imported_manifest is not None else None,
                new_preview if imported_manifest is not None and new_preview.exists() else None,
            )

            validated_count = 0
            if imported_manifest is not None:
                for desc in imported_manifest.get("segments", []):
                    if not bool(desc.get("validated", False)):
                        break
                    validated_count += 1

            loaded_resolution = _resolution_from_manifest(imported_manifest)
            return {
                "project_name": str(archive_meta.get("project_name") or archive_path.stem),
                "project": project_payload,
                "references": {
                    "count": int(_reference_count(imported_refs)),
                    "refs_json": _refs_json(imported_refs),
                },
                "cache": {
                    "present": imported_manifest is not None,
                    "cached_count": cached_count,
                    "validated_count": int(validated_count),
                    "frame_count": int(imported_manifest.get("final_frame_count", 0)) if imported_manifest else 0,
                    "resolved_width": int(loaded_resolution["width"]) if loaded_resolution else 0,
                    "resolved_height": int(loaded_resolution["height"]) if loaded_resolution else 0,
                },
            }
    finally:
        shutil.rmtree(work_root, ignore_errors=True)



class BSAIH3FilmFactory:
    @classmethod
    def INPUT_TYPES(cls):
        sampler_names = list(comfy.samplers.SAMPLER_NAMES)
        scheduler_names = list(comfy.samplers.SCHEDULER_NAMES)
        default_sampler = "euler" if "euler" in sampler_names else sampler_names[0]
        default_scheduler = "simple" if "simple" in scheduler_names else scheduler_names[0]

        required = {
            "model": ("MODEL",),
            "clip": ("CLIP",),
            "vae": ("VAE",),
            "run_mode": (["clip_by_clip", "full_batch"], {"default": "clip_by_clip"}),
            "width": (
                "INT",
                {
                    "default": 896, "min": 32, "max": 4096, "step": 32,
                    "tooltip": "Manual resolution width, also used as Auto fallback when no internal image reference is loaded.",
                },
            ),
            "height": (
                "INT",
                {
                    "default": 576, "min": 32, "max": 4096, "step": 32,
                    "tooltip": "Manual resolution height, also used as Auto fallback when no internal image reference is loaded.",
                },
            ),
            "ref_image_size": (["match", "max"], {"default": "match"}),
            "steps": ("INT", {"default": 4, "min": 1, "max": 10000, "step": 1}),
            "sampler_name": (sampler_names, {"default": default_sampler}),
            "scheduler": (scheduler_names, {"default": default_scheduler}),
            "denoise": ("FLOAT", {"default": 1.0, "min": 0.01, "max": 1.0, "step": 0.01}),
            "context_length": (["22", "5", "39", "56"], {"default": "22"}),
            "audio_context_length": ("INT", {"default": 0, "min": 0, "max": 240, "step": 1}),
            "clips_json": (
                "STRING",
                {
                    "default": _state_json([_default_clip(0)]),
                    "multiline": True,
                },
            ),
            # Keep these AFTER clips_json so pre-v14.25 workflow widget arrays
            # keep their original positional mapping. The frontend migrates old
            # workflows/projects to Manual mode on load.
            "resolution_mode": (
                ["auto_from_ref", "manual"],
                {
                    "default": "auto_from_ref",
                    "tooltip": "Auto uses internal Ref 1 as the aspect-ratio guide; with no internal image references it falls back to width/height.",
                },
            ),
            "megapixels": (
                "FLOAT",
                {
                    "default": DEFAULT_MEGAPIXELS, "min": 0.01, "max": 16.0, "step": 0.01,
                    "tooltip": "Target total pixels for Auto resolution. Auto and Manual canvases use the MiniMax H3 32-pixel grid; Auto snaps downward without exceeding the requested pixel budget.",
                },
            ),
            # Internal image-reference manager state. Appended after the v14.25
            # widgets so older positional workflow widget arrays keep mapping.
            "refs_json": (
                "STRING",
                {
                    "default": _refs_json(_empty_refs()),
                    "multiline": True,
                },
            ),
            "output_mode": (
                ["none", "per_clip", "merged", "both"],
                {
                    "default": "none",
                    "tooltip": "none: 仅缓存，使用Final Decode节点输出。per_clip: 按CLIP分段保存MP4。merged: 合并所有CLIP为一个MP4。both: 同时保存分段和合并。",
                },
            ),
            "filename_prefix": (
                "STRING",
                {
                    "default": "H3_Extender",
                    "tooltip": "输出文件名前缀。分段输出时自动追加_clipN.mp4。",
                },
            ),
            "output_image_audio": (
                "BOOLEAN",
                {
                    "default": True,
                    "tooltip": "每个CLIP生成好立即解码为IMAGE+AUDIO，经image/audio输出端口流出（可接超分放大节点）。关闭则仅缓存、用Final Decode导出。",
                },
            ),
            "block_cache": (
                "BOOLEAN",
                {
                    "default": False,
                    "tooltip": "启用MiniMax H3 Block Cache（F1B0残差缓存）加速：顺序CLIP画面稳定时跳过大部分DiT块，多CLIP连续生成显著提速。依赖已安装的comfyui-minimax-h3-blockcache-T8插件。",
                },
            ),
            "block_cache_threshold": (
                "FLOAT",
                {
                    "default": 0.12, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "Block Cache命中阈值。越高越容易命中、加速越多，但结果可能变化。",
                },
            ),
            "block_cache_device": (
                ["cpu", "gpu"],
                {
                    "default": "cpu",
                    "tooltip": "Block Cache缓存设备。cpu省显存，gpu减少传输但占显存。",
                },
            ),
            "ref_cache": (
                "BOOLEAN",
                {
                    "default": True,
                    "tooltip": "Ref2VA 参考图VAE编码磁盘缓存（CLIPCached同款，2026.09）：参考图内容未变时复用已编码的Image Latent，跳过每次重复编码——调提示词/换种子重跑显著提速；参考图变化自动失效。",
                },
            ),
            "cache_dit": (
                "BOOLEAN",
                {
                    "default": False,
                    "tooltip": "CacheDiT 步间缓存加速（ComfyUI-CacheDiT，H3 约1.4-1.5x，2026.08新增H3支持）：自动检测并应用，需已安装 ComfyUI-CacheDiT 插件（未装自动回退）。与 Block Cache 互斥，开启时优先使用 CacheDiT。",
                },
            ),
            "clip_select_enable": (
                "BOOLEAN",
                {
                    "default": False,
                    "tooltip": "CLIP 选择生成开关：开启后仅渲染 clip_select 指定的 CLIP，未选中的保留缓存、不重新生成。",
                },
            ),
            "clip_select": (
                "STRING",
                {
                    "default": "all",
                    "multiline": False,
                    "tooltip": "要渲染的 CLIP（1 起）：all=全部；单个如 1；多选如 1,3；范围如 2-5；混合如 1,3-5。仅 clip_select_enable 开启时生效。",
                },
            ),
            "pause_enable": (
                "BOOLEAN",
                {
                    "default": False,
                    "tooltip": "暂停渲染开关：开启后每个 CLIP 生成完、开始下一个前可暂停。前端提供「暂停/继续/仅当前/中止」，用户无干预则超时自动继续。",
                },
            ),
            "pause_timeout": (
                "FLOAT",
                {
                    "default": 120.0, "min": 5.0, "max": 3600.0, "step": 5.0,
                    "tooltip": "暂停后无干预自动继续渲染的等待秒数。",
                },
            ),
        }

        # Standalone audio remains an external socket for now. Image refs are
        # deliberately no longer graph inputs: they are loaded/previewed/stored
        # by the Extender itself and embedded in portable .ext projects.
        optional = {
            "audio_vae": ("VAE", {"forceInput": True}),
            "ref_audio": ("AUDIO", {"forceInput": True}),
            "prompt_source": ("STRING", {"forceInput": True, "tooltip": "Unified external prompt source. Auto-split at first [分镜N] marker: text before → global prompt, text from [分镜N] onwards → storyboard segments (auto-create N CLIPs with prompts and durations)."}),
            "prompt_pack": (
                PROMPT_PACK_TYPE,
                {
                    "tooltip": "Optional external prompt pack. New/changed packs are imported into the normal clip textareas and synchronize the clip count."
                },
            ),
            "asset_library": ("ASSET_LIBRARY", {"forceInput": True, "tooltip": "Connect BSAI_AssetLibraryInput to resolve @图N/@视频N/@音频N references in clip prompts."}),
        }

        return {
            "required": required,
            "optional": optional,
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = (CACHE_TYPE, "INT", "INT", "STRING", "FLOAT", "STRING", "STRING", "IMAGE", "AUDIO")
    RETURN_NAMES = (
        "cache",
        "clip_count",
        "validated_count",
        "status",
        "cache_size_mb",
        "build",
        "clip_videos",
        "images",
        "audios",
    )
    FUNCTION = "extend"
    CATEGORY = "BSAI/H3 Film Factory"
    OUTPUT_NODE = True

    @staticmethod
    def _resolve_asset_library_refs(clips, asset_library):
        """Resolve @图N/@视频N/@音频N tags in clip prompts against the connected Asset Library.
        Replaces @图N with <Picture N>, @视频N with <Video N>, @音频N with <Audio 1>.
        Also loads referenced images as internal refs and audio as ref_audio path.
        Returns (clips_with_resolved_prompts, resolved_image_paths, resolved_audio_paths).
        """
        if not asset_library:
            print("[H3 Extender] asset_library is empty or None, skipping @图N resolution")
            return clips, [], []

        # asset_library can be a dict with 'images'/'videos'/'audios' lists
        if isinstance(asset_library, dict):
            images = asset_library.get("images", [])
            videos = asset_library.get("videos", [])
            audios = asset_library.get("audios", [])
        elif isinstance(asset_library, (list, tuple)):
            images = list(asset_library)
            videos = []
            audios = []
        else:
            print(f"[H3 Extender] asset_library is unexpected type: {type(asset_library)}")
            return clips, [], []

        print(f"[H3 Extender] asset_library received: {len(images)} images, {len(videos)} videos, {len(audios)} audios")
        for i, img in enumerate(images[:3]):
            if isinstance(img, dict):
                print(f"[H3 Extender]   image[{i}]: index={img.get('index')}, name={img.get('name')}, path={img.get('path', '')[:80]}")

        import re
        resolved_image_paths = []
        resolved_audio_paths = []

        def _find_asset_by_index(items, tag_num):
            """Find an asset by its 'index' field, falling back to positional."""
            for item in items:
                if isinstance(item, dict) and item.get("index") == tag_num:
                    return item
            idx = tag_num - 1
            if 0 <= idx < len(items):
                return items[idx]
            return None

        for clip_idx, clip in enumerate(clips):
            prompt = clip.get("prompt", "")
            original_prompt = prompt

            # Resolve @图N -> load image path, replace tag with <Picture N>
            # Use re.sub to avoid str.replace bug with multi-digit tags (e.g. @图1 in @图10)
            def _replace_image_tag(m):
                tag_num = int(m.group(1))
                img_entry = _find_asset_by_index(images, tag_num)
                if img_entry is None:
                    print(f"[H3 Extender] @图{tag_num} not found in asset library (has {len(images)} images)")
                    return m.group(0)
                img_path = img_entry.get("path", img_entry.get("filename", "")) if isinstance(img_entry, dict) else str(img_entry)
                if not img_path:
                    print(f"[H3 Extender] @图{tag_num} found but path is empty")
                    return m.group(0)
                if img_path not in resolved_image_paths:
                    resolved_image_paths.append(img_path)
                ref_num = resolved_image_paths.index(img_path) + 1
                return f"<Picture {ref_num}>"
            prompt = re.sub(r'@图(\d+)', _replace_image_tag, prompt)

            # Resolve @视频N -> <Video N>
            def _replace_video_tag(m):
                tag_num = int(m.group(1))
                vid_entry = _find_asset_by_index(videos, tag_num)
                if vid_entry is None:
                    return m.group(0)
                return f"<Video {tag_num}>"
            prompt = re.sub(r'@视频(\d+)', _replace_video_tag, prompt)

            # Resolve @音频N -> load audio path
            def _replace_audio_tag(m):
                tag_num = int(m.group(1))
                aud_entry = _find_asset_by_index(audios, tag_num)
                if aud_entry is None:
                    return m.group(0)
                aud_path = aud_entry.get("path", aud_entry.get("filename", "")) if isinstance(aud_entry, dict) else str(aud_entry)
                if aud_path and aud_path not in resolved_audio_paths:
                    resolved_audio_paths.append(aud_path)
                return "<Audio 1>"
            prompt = re.sub(r'@音频(\d+)', _replace_audio_tag, prompt)

            if prompt != original_prompt:
                print(f"[H3 Extender] clip[{clip_idx}] prompt resolved: '{original_prompt[:60]}' -> '{prompt[:60]}'")
            clip["prompt"] = prompt

        print(f"[H3 Extender] resolved {len(resolved_image_paths)} image paths, {len(resolved_audio_paths)} audio paths")
        for i, p in enumerate(resolved_image_paths):
            print(f"[H3 Extender]   resolved_img[{i}]: {p}")

        return clips, resolved_image_paths, resolved_audio_paths

    def extend(
        self,
        model,
        clip,
        vae,
        run_mode,
        width,
        height,
        ref_image_size,
        steps,
        sampler_name,
        scheduler,
        denoise,
        context_length,
        audio_context_length,
        clips_json,
        resolution_mode="auto_from_ref",
        megapixels=DEFAULT_MEGAPIXELS,
        refs_json=None,
        output_mode="none",
        filename_prefix="H3_Extender",
        prompt_pack=None,
        asset_library=None,
        prompt_source=None,
        output_image_audio=True,
        block_cache=False,
        block_cache_threshold=0.12,
        block_cache_device="cpu",
        ref_cache=True,
        cache_dit=False,
        clip_select_enable=False,
        clip_select="all",
        pause_enable=False,
        pause_timeout=120.0,
        unique_id=None,
        **kwargs,
    ):
        stored_prompt_pack_signature = _prompt_pack_signature_from_state(clips_json)
        clips = _parse_clips_json(clips_json)
        merge_output = _merge_output_from_state(clips_json)

        # Split unified prompt_source at first [分镜N] marker:
        # text before → global_prompt, text from [分镜N] onwards → storyboard
        # (storyboard segments are handled by frontend JS auto-CLIP creation)
        global_prompt = None
        if prompt_source:
            import re as _re
            sb_match = _re.search(r'\[(?:分镜|Shot|shot|SHOT)\s*\d+\]', str(prompt_source))
            if sb_match:
                global_prompt = str(prompt_source)[:sb_match.start()].strip()
            else:
                global_prompt = str(prompt_source).strip()

        # Resolve @图N/@视频N/@音频N from connected Asset Library.
        # Include the global prompt as a pseudo-clip so its @图N tags are
        # resolved with the same image numbering as clip prompts.
        if global_prompt:
            print(f"[H3 Extender] global_prompt received (len={len(str(global_prompt))}): '{str(global_prompt)[:80]}'")
            gp_clip = {"prompt": str(global_prompt)}
            resolved_all, resolved_img_paths, resolved_aud_paths = self._resolve_asset_library_refs(
                [gp_clip] + clips, asset_library
            )
            global_prompt = resolved_all[0]["prompt"]
            clips = resolved_all[1:]
            print(f"[H3 Extender] global_prompt after resolution: '{str(global_prompt)[:80]}'")
        else:
            print("[H3 Extender] no global_prompt connected")
            clips, resolved_img_paths, resolved_aud_paths = self._resolve_asset_library_refs(clips, asset_library)
        external_prompt_pack = _normalize_external_prompt_pack(prompt_pack)
        clips, active_prompt_pack_signature, prompt_pack_imported, _prompt_pack_count_changed = (
            _sync_clips_from_prompt_pack(
                clips,
                external_prompt_pack,
                stored_prompt_pack_signature,
            )
        )
        owner = str(unique_id if unique_id is not None else "h3_extender")
        _register_render_ctl(owner)
        # CLIP 自定义选择生成：None=全部；set=指定渲染范围。
        # 单选（如 2）语义：从该 CLIP 起连续渲染到结束（自动依次生成后续 CLIP），
        # 除非用户手动暂停或手动选择「合并输出」，才执行合并。多选/范围保留原「仅渲染指定段」语义。
        select_override = None
        if int(clip_select_enable):
            select_override = _parse_clip_select(clip_select, len(clips))
            if select_override is not None and len(select_override) == 1:
                _sel_start = min(select_override)
                select_override = set(range(_sel_start, len(clips)))
            if select_override:
                _so_list = sorted(n + 1 for n in select_override)
                print(f"[H3 Extender] CLIP 选择生成: 从 {_so_list[0]} 起连续渲染 {len(select_override)} 个 CLIP {_so_list}")
        # v1.13: 仅「全量渲染且未干预」才自动合并；部分选择/重渲染/暂停均禁止自动合并
        render_partial = (
            select_override is not None
            and set(select_override) != set(range(len(clips)))
        )
        if external_prompt_pack is None:
            active_prompt_pack_signature = ""
        data_path, manifest_path, manifest = _manifest_for_extender(owner, FPS)

        # If cards were removed, trim the physical cache immediately.
        if len(manifest.get("segments", [])) > len(clips):
            manifest = _truncate_chain(
                data_path, manifest_path, manifest, len(clips)
            )

        # Clear stale tail latents before a full render pass.
        # Tail latents are only valid between a "per-clip replace" operation
        # and the next "合并输出 / Merge Output" click.  Any other execution
        # path (full re-render, storyboard edit, prompt change, etc.) means
        # the tail latents on disk are stale and must be discarded — otherwise
        # the auto-merge_output guard can trigger and skip the entire render,
        # producing a merged video from the old cached content.
        if not merge_output and _has_tail_latents_on_disk(owner):
            any_replace = any(c.get("replace_mode", False) for c in clips)
            if not any_replace:
                _delete_tail_latents_from_disk(owner)
                print(f"[H3 Extender] Cleared stale tail latents before full re-render "
                      f"(clips={len(clips)})")
            else:
                # In per-clip replace mode, still clear tail if clip count
                # changed since the tail was saved.
                cached_seg_count = len(manifest.get("segments", []))
                if cached_seg_count != len(clips):
                    _delete_tail_latents_from_disk(owner)
                    print(f"[H3 Extender] Cleared stale tail latents "
                          f"(clips={len(clips)}, cache={cached_seg_count})")

        segments = manifest.get("segments", [])

        # A TRUE toggle can only validate a clip that actually exists on disk.
        # This also protects old workflow JSON with stale downstream TRUE values.
        if len(segments) < len(clips):
            for i in range(len(segments), len(clips)):
                if clips[i]["validated"]:
                    for j in range(i, len(clips)):
                        clips[j]["validated"] = False
                    break

        refs = _parse_refs_json(refs_json)

        # Load asset library images as reference tensors. When @图N tags are
        # used, the asset images replace the internal refs list entirely so
        # that <Picture N> tags in prompts match the ref slot numbers.
        if resolved_img_paths:
            print(f"[H3 Extender] Loading {len(resolved_img_paths)} asset images as ref tensors")
            asset_tensors = []
            for img_path in resolved_img_paths:
                try:
                    with Image.open(img_path) as image:
                        image = ImageOps.exif_transpose(image).convert("RGB")
                        array = np.asarray(image, dtype=np.float32) / 255.0
                    tensor = torch.from_numpy(np.ascontiguousarray(array)).unsqueeze(0)
                    asset_tensors.append(tensor)
                    print(f"[H3 Extender]   loaded asset image: {img_path} -> shape {tuple(tensor.shape)}")
                except Exception as _e:
                    print(f"[H3 Extender] FAILED to load asset image {img_path}: {_e}")

            if asset_tensors:
                refs = asset_tensors[:MAX_IMAGE_REFS]
                refs += [None] * (MAX_IMAGE_REFS - len(refs))
                print(f"[H3 Extender] refs replaced with {len(asset_tensors)} asset tensors (padded to {len(refs)} slots)")
                for i, r in enumerate(refs):
                    if r is not None:
                        print(f"[H3 Extender]   refs[{i}]: tensor shape {tuple(r.shape)}")
            else:
                print("[H3 Extender] WARNING: resolved_img_paths was non-empty but no tensors were loaded!")
        else:
            print(f"[H3 Extender] no resolved_img_paths, using UI refs: {sum(1 for r in refs if r is not None)} active")

        # Set ref_audio from asset library if audio refs were resolved
        if resolved_aud_paths and not kwargs.get("ref_audio"):
            kwargs["ref_audio"] = resolved_aud_paths[0]

        refs_signature = _refs_signature(refs)
        requested_resolution = _resolve_generation_resolution(
            resolution_mode,
            megapixels,
            width,
            height,
            refs,
        )

        cache_resolution = _resolution_from_manifest(manifest)
        cache_has_segments = bool(segments) and cache_resolution is not None

        # Resolution is a live generation setting again. Auto/MP or Manual
        # width/height may be changed at any time, exactly like the old external
        # Scale Image -> Get Image Size workflow. A latent chain cannot mix two
        # geometries, so when the requested size changes we restart only the
        # generated cache while preserving every card/prompt/seed/config.
        #
        # A .ext Load is handled in the frontend by putting the exact archived
        # cache width/height into Manual mode. Therefore the imported project
        # continues at its stored geometry until the user explicitly changes the
        # resolution controls afterwards.
        resolution = dict(requested_resolution)
        resolution["requested_width"] = int(requested_resolution["width"])
        resolution["requested_height"] = int(requested_resolution["height"])
        resolution["cache_reset"] = False

        resolved_width = int(resolution["width"])
        resolved_height = int(resolution["height"])

        requested_mismatch = bool(
            cache_has_segments
            and (
                int(cache_resolution["width"]) != resolved_width
                or int(cache_resolution["height"]) != resolved_height
            )
        )
        previous_cache_resolution = dict(cache_resolution) if requested_mismatch else None

        if requested_mismatch:
            # Resolution is the one unavoidable global invalidation: latent
            # geometry cannot be mixed inside one sequential disk chain.
            manifest = _truncate_chain(data_path, manifest_path, manifest, 0)
            segments = []
            cache_resolution = None
            cache_has_segments = False
            resolution["cache_reset"] = True
            for cfg in clips:
                cfg["validated"] = False
            try:
                preview_path = _decoded_preview_cache_path(data_path)
                if preview_path.exists():
                    preview_path.unlink()
            except Exception:
                pass

        if prompt_pack_imported and external_prompt_pack is not None:
            imported_json = _state_json(clips, active_prompt_pack_signature)
            _send_extender_prompt_pack_import(
                owner,
                imported_json,
                len(external_prompt_pack.get("prompts") or []),
                external_prompt_pack.get("source") or "External prompt pack",
            )

        # References are intentionally user-controlled. The Extender never
        # associates a Ref number with a clip number and never decides which clip
        # becomes obsolete after a reference edit. Keep this fingerprint as
        # informational project/cache metadata, never as an invalidation key.
        #
        # Exception: when @图N asset library refs are used, the refs list is
        # replaced with asset tensors. If the cache was built with different
        # refs (e.g. UI refs or no refs), the cached clips must be invalidated
        # so they re-render with the asset library characters.
        asset_refs_key = ""
        if resolved_img_paths:
            asset_refs_key = hashlib.sha256(
                "|".join(resolved_img_paths).encode("utf-8")
            ).hexdigest()

        manifest = _load_manifest_from_paths(data_path, manifest_path) or manifest
        manifest = dict(manifest)
        prev_asset_refs_key = manifest.get("asset_refs_key", "")
        if asset_refs_key and prev_asset_refs_key and asset_refs_key != prev_asset_refs_key:
            print(f"[H3 Extender] Asset library refs changed, invalidating all cached clips")
            manifest = _truncate_chain(data_path, manifest_path, manifest, 0)
            for cfg in clips:
                cfg["validated"] = False
        elif asset_refs_key and not prev_asset_refs_key and manifest.get("segments"):
            print(f"[H3 Extender] Asset library refs newly connected, invalidating all cached clips")
            manifest = _truncate_chain(data_path, manifest_path, manifest, 0)
            for cfg in clips:
                cfg["validated"] = False

        manifest["asset_refs_key"] = asset_refs_key
        manifest["extender_refs_signature"] = refs_signature
        manifest["extender_ref_ids"] = [
            ref.get("id") if isinstance(ref, dict) else None for ref in refs
        ]
        manifest["updated_at"] = time.time()
        _write_json_atomic(manifest_path, manifest)

        resolution_mismatch = False

        audio_vae = kwargs.get("audio_vae")
        ref_audio = kwargs.get("ref_audio")
        ref_items = None
        ref_blocks = None
        active_picture_slots = None

        disk_join = MiniMaxH3MotionContextDiskJoin()
        motion = MiniMaxH3MotionContextRAM()

        previous_handle = None
        previous_proxy = None
        generated = []
        statuses = []

        # ── Merge Output mode: restore tail + produce merged video ────
        # When user clicks "合并输出" button, this flag is set. We skip all
        # rendering, restore any saved tail latents from disk, mark all clips
        # as validated, and produce the merged output.
        #
        # Also auto-trigger merge_output if there are saved tail latents on
        # disk and no replace_mode is active — this prevents accidental
        # re-rendering of tail clips when the user clicks Queue without
        # explicitly clicking "合并输出".
        if merge_output or (not any(c.get("replace_mode", False) for c in clips)
                             and _has_tail_latents_on_disk(owner)):
            print("[H3 Extender] merge_output mode: restoring tail + producing merged output")
            # Clear all replace_mode flags
            for cfg in clips:
                cfg["replace_mode"] = False

            # Load saved tail latents from disk (if any)
            disk_tail = _load_tail_latents_from_disk(owner)
            if disk_tail is not None:
                print(f"[H3 Extender] merge_output: restoring {len(disk_tail)} tail clip(s) from disk")
                restored_manifest = _restore_tail_latents(data_path, manifest_path, disk_tail)
                if restored_manifest is not None:
                    manifest = restored_manifest
                _delete_tail_latents_from_disk(owner)
            else:
                print("[H3 Extender] merge_output: no saved tail latents found, using existing chain as-is")

            # Mark all clips as validated
            final_manifest = _load_manifest_from_paths(data_path, manifest_path)
            if final_manifest is not None:
                segs = [dict(x) for x in final_manifest.get("segments", [])]
                changed = False
                for i in range(min(len(clips), len(segs))):
                    if not bool(segs[i].get("validated", False)):
                        segs[i]["validated"] = True
                        changed = True
                    clips[i]["validated"] = True
                    clips[i]["replace_mode"] = False
                if changed:
                    final_manifest = dict(final_manifest)
                    final_manifest["segments"] = segs
                    final_manifest["build"] = BUILD
                    final_manifest["updated_at"] = time.time()
                    _write_json_atomic(manifest_path, final_manifest)

            # Walk the chain to set previous_handle/proxy for Final Decode
            final_manifest = _load_manifest_from_paths(data_path, manifest_path)
            cached_count = len(final_manifest.get("segments", [])) if final_manifest else 0
            for i in range(cached_count):
                result = disk_join.join(
                    samples=None,
                    trim_frames=None,
                    validated=True,
                    run_mode=str(run_mode),
                    fps=float(FPS),
                    previous_cache=previous_handle,
                    unique_id=f"extender_{owner}",
                )
                previous_handle = result[0]
                previous_proxy = result[1]
                statuses.append(result[4])

            if previous_handle is None:
                raise RuntimeError("MiniMax H3 Extender: merge_output produced no cache handle.")

            validated_count = cached_count
            normalized_json = _state_json(clips, active_prompt_pack_signature)
            resolution_text = f"{resolved_width}x{resolved_height}"
            status = f"merge_output | {resolution_text} | cached {cached_count}/{len(clips)} | validated {validated_count} | merged"
            cache_mb = _cache_size_mb(data_path, manifest_path)

            _send_extender_progress(owner, -1, len(clips), "idle", status)

            # v1.18: 单独选择生成（render_partial）时跳过了 preview 解码，
            # decoded_mp4_blob 缺失——合并输出前对缺失段自动补解码，保证 merged 可产出。
            if final_manifest is not None:
                try:
                    _segs = [dict(x) for x in final_manifest.get("segments", [])]
                    for _si, _seg in enumerate(_segs):
                        if _seg.get("decoded_mp4_blob") is None and int(_seg.get("frames", 0)) > 0:
                            print(f"[H3 Extender] merge_output: 补解码 segment {_si}（单独生成未产 blob）")
                            _decode_single_clip_preview(owner, _si, vae, audio_vae, float(FPS), _find_ffmpeg())
                    final_manifest = _load_manifest_from_paths(data_path, manifest_path) or final_manifest
                except Exception as _me:
                    print(f"[H3 Extender] merge_output: blob 补解码失败 {_me}")

            # Produce merged output directly — merge_output always produces
            # a merged video regardless of the output_mode widget setting.
            output_ui_videos = []
            if final_manifest is not None:
                try:
                    out_dir = Path(folder_paths.get_output_directory()).resolve()
                except Exception:
                    out_dir = (Path.cwd() / "output").resolve()
                out_dir.mkdir(parents=True, exist_ok=True)
                prefix = _safe_name(str(filename_prefix or "H3_Extender"))
                segments_out = [dict(x) for x in final_manifest.get("segments", [])]
                ff = None
                try:
                    ff = _find_ffmpeg()
                except Exception:
                    ff = None

                want_per_clip = str(output_mode) in ("per_clip", "both")
                want_merged = True  # merge_output always produces merged video

                if want_per_clip:
                    for si, seg in enumerate(segments_out):
                        blob = seg.get("decoded_mp4_blob")
                        if blob is None:
                            continue
                        clip_path = out_dir / f"{prefix}_clip{si + 1:02d}.mp4"
                        try:
                            _copy_blob_to_file(data_path, blob, clip_path)
                            item = _comfy_media_item(clip_path, float(FPS), "output")
                            output_ui_videos.append(item)
                            print(f"[H3 Extender] saved per-clip video: {clip_path}")
                        except Exception as _e:
                            print(f"[H3 Extender] failed to save clip {si+1}: {_e}")

                if want_merged and len(segments_out) > 0:
                    temp_root = _ensure_cache_root()
                    concat_list = temp_root / f"_concat_{owner}_{uuid.uuid4().hex[:8]}.txt"
                    clip_paths = []
                    for si, seg in enumerate(segments_out):
                        blob = seg.get("decoded_mp4_blob")
                        if blob is None:
                            continue
                        cp = temp_root / f"_mergeclip_{owner}_{si}_{uuid.uuid4().hex[:8]}.mp4"
                        try:
                            _copy_blob_to_file(data_path, blob, cp)
                            clip_paths.append(cp)
                        except Exception:
                            pass

                    if clip_paths:
                        with open(concat_list, "w", encoding="utf-8") as f:
                            for cp in clip_paths:
                                f.write(f"file '{cp.as_posix()}'\n")

                        merged_path = out_dir / f"{prefix}_merged.mp4"
                        if len(clip_paths) == 1:
                            shutil.copy2(clip_paths[0], merged_path)
                        elif ff:
                            cmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(merged_path)]
                            try:
                                subprocess.run(cmd, check=True, capture_output=True, timeout=120)
                            except Exception as _e:
                                print(f"[H3 Extender] ffmpeg merge failed: {_e}")

                        try:
                            item = _comfy_media_item(merged_path, float(FPS), "output")
                            output_ui_videos.append(item)
                            print(f"[H3 Extender] saved merged video: {merged_path}")
                        except Exception as _e:
                            print(f"[H3 Extender] failed to create media item for merged: {_e}")

                        for cp in clip_paths:
                            try:
                                cp.unlink()
                            except Exception:
                                pass
                        try:
                            concat_list.unlink()
                        except Exception:
                            pass

            return {
                "ui": {
                    "videos": output_ui_videos,
                    "h3_extender_state": [{
                        "clips_json": normalized_json,
                        "clip_count": len(clips),
                        "cached_count": cached_count,
                        "validated_count": validated_count,
                        "generated": [],
                        "status": status,
                        "resolved_width": resolved_width,
                        "resolved_height": resolved_height,
                        "build": BUILD,
                    }],
                },
                "result": (
                    previous_handle,
                    len(clips),
                    validated_count,
                    status,
                    cache_mb,
                    BUILD,
                ),
            }

        # ── Per-clip selective rendering ──────────────────────────────
        # Build selected_set from per-clip flags:
        #   - replace_mode=True  → re-render this clip (replaces previous output)
        #   - render_enabled=False → skip this clip (keep cached, don't generate)
        # When any clip has replace_mode, the chain is truncated to just
        # before the first such clip, and only the selected clip(s) are
        # re-rendered. Tail latents are saved to disk (not restored
        # automatically); the user must click "合并输出" to merge.
        saved_tail = None
        single_clip_replace = False
        loop_end = len(clips)
        first_sel = None
        last_sel = None
        selected_set = set()
        any_replace = False
        for i, cfg in enumerate(clips):
            if cfg.get("replace_mode", False):
                selected_set.add(i)
                any_replace = True
                if first_sel is None:
                    first_sel = i
                last_sel = i

        if any_replace:
            single_clip_replace = True
            manifest = _load_manifest_from_paths(data_path, manifest_path) or manifest
            segments = manifest.get("segments", [])

            # 2026-09-04 v1.12: 重渲染单个/多个 CLIP 后，不再保存/截断尾部 latent、
            # 不再自动合并 —— 改为从最早选中段(first_sel)起连续渲染到结束
            # （自动依次生成后续 CLIP），除非用户手动暂停或手动「合并输出」。
            # 主循环依据 validated=False 从 first_sel 起逐个重新采样覆盖旧段。
            render_partial = True  # 重渲染 = 部分渲染，禁止自动合并
            if _has_tail_latents_on_disk(owner):
                _delete_tail_latents_from_disk(owner)
                print("[H3 Extender] per-clip replace: deleted stale tail latents from disk")
            saved_tail = None

            # Override validated flags: first_sel 之前的保留缓存（join），
            # first_sel 及之后全部置为未验证 → 主循环连续重新渲染到结束。
            for i, cfg in enumerate(clips):
                if i < first_sel and i < len(segments):
                    cfg["validated"] = True
                else:
                    cfg["validated"] = False

        # v1.17: 前置 latent 链完整性检查 —— 部分选择 / 重渲染时，若磁盘 latent 链
        # 不足以支撑所选段的前置段，自动补渲染缺失段建立完整链（H3 必须依赖前置
        # latent 做 motion context），并明确打印提示，让用户知情而非报错/静默。
        _need_pre = None
        if select_override is not None:
            _need_pre = min(select_override)
        elif any_replace and first_sel > 0:
            _need_pre = first_sel
        if _need_pre is not None:
            _pre_m = _load_manifest_from_paths(data_path, manifest_path)
            _pre_n = len(_pre_m.get("segments", [])) if _pre_m else 0
            if _pre_n < _need_pre:
                _from = max(0, _pre_n)
                if select_override is not None:
                    select_override = set(range(_from, len(clips)))
                    print(
                        f"[H3 Extender] v1.17 前置 latent 链缺失（磁盘仅 {_pre_n} 段，"
                        f"不足所选 CLIP{_need_pre + 1} 所需的 {_need_pre} 段）：自动从 "
                        f"CLIP{_from + 1} 补渲染建立完整链，随后从所选 CLIP 连续生成到结束。"
                    )
                else:
                    first_sel = _from
                    print(
                        f"[H3 Extender] v1.17 前置 latent 链缺失（磁盘仅 {_pre_n} 段，"
                        f"不足重渲染 CLIP{_need_pre + 1} 所需的 {_need_pre} 段）：自动从 "
                        f"CLIP{_from + 1} 补渲染建立完整链，随后连续生成到结束。"
                    )

        # Build the accelerated sampling model once for the whole pass.
        sampling_model = model
        if int(cache_dit):
            sampling_model = _apply_cache_dit(
                model,
                model_type="Auto",
                warmup_steps=0,
                skip_interval=0,
                print_summary=True,
            )
        elif int(block_cache):
            sampling_model = _apply_h3_block_cache(
                model,
                residual_diff_threshold=float(block_cache_threshold),
                cache_device=str(block_cache_device),
            )

        # Per-CLIP IMAGE+AUDIO streaming outputs.
        out_images = []
        out_audios = []
        _av_decoded = set()
        paused_break = False  # v1.13: 用户暂停/停止后禁止自动合并

        # Walk the card list in order. Cached TRUE clips are metadata-only;
        # active clips sample and are written immediately to disk.
        for i, cfg in enumerate(clips[:loop_end]):
            # Clips with render_enabled=False are skipped entirely: they keep
            # their cached latent (if any) and are not re-rendered.  This lets
            # the user turn off generation for specific clips without removing
            # them from the sequence. CLIP 选择生成时，未选中的同样跳过（保留缓存）。
            if not cfg.get("render_enabled", True) or (
                select_override is not None and i not in select_override
            ):
                current_manifest = _load_manifest_from_paths(data_path, manifest_path)
                existing_count = len(current_manifest.get("segments", [])) if current_manifest else 0
                if i < existing_count:
                    result = disk_join.join(
                        samples=None,
                        trim_frames=None,
                        validated=True,
                        run_mode=str(run_mode),
                        fps=float(FPS),
                        previous_cache=previous_handle,
                        unique_id=f"extender_{owner}",
                    )
                    previous_handle = result[0]
                    previous_proxy = result[1]
                    statuses.append(result[4])
                continue

            # Refresh manifest state every iteration because Disk Join can
            # truncate or append the physical chain.
            current_manifest = _load_manifest_from_paths(data_path, manifest_path)
            existing_count = len(current_manifest.get("segments", [])) if current_manifest else 0
            existing = i < existing_count

            if cfg["validated"] and existing:
                result = disk_join.join(
                    samples=None,
                    trim_frames=None,
                    validated=True,
                    run_mode=str(run_mode),
                    fps=float(FPS),
                    previous_cache=previous_handle,
                    unique_id=f"extender_{owner}",
                )
                previous_handle = result[0]
                previous_proxy = result[1]
                statuses.append(result[4])
                continue

            # Any active clip is unvalidated. Make sure everything after it is
            # false in the serialized state as well.
            _send_extender_progress(
                owner,
                i,
                len(clips),
                "preparing",
                f"Preparing clip {i + 1}/{len(clips)}",
            )
            cfg["validated"] = False
            for j in range(i + 1, loop_end):
                clips[j]["validated"] = False

            if ref_items is None or ref_blocks is None or active_picture_slots is None:
                ref_items, ref_blocks, active_picture_slots, _ref_cache_hit = _prepare_shared_refs_cached(
                    vae,
                    audio_vae,
                    resolved_width,
                    resolved_height,
                    str(ref_image_size),
                    refs,
                    ref_audio=ref_audio,
                    enable_cache=bool(ref_cache),
                )
                if not _ref_cache_hit:
                    print(f"[H3 Extender] _prepare_shared_refs: {len(ref_items)} ref_items, "
                          f"{len(ref_blocks)} ref_blocks, active_picture_slots={active_picture_slots}")

            frame_count = _duration_to_frames(cfg["duration"])
            # Prepend global prompt if connected from an external node
            effective_prompt = str(cfg["prompt"] or "")
            if global_prompt:
                gp = str(global_prompt).strip()
                if gp:
                    effective_prompt = gp + "\n" + effective_prompt
            print(f"[H3 Extender] clip[{i}] effective_prompt: '{effective_prompt[:100]}'")
            # v1.21: 多 CLIP 连续渲染时，上一 CLIP 的 H3 主模型（~20GB）仍驻留显存，
            # 会挤占本 CLIP 的 TE 文本编码空间导致 OOM——先卸载全部模型释放显存。
            # v1.23: unload_all_models 走 detach 分支不释放 dynamic 显存（OOM 根因），
            # 改为 partially_unload(offload, 1e32) 强制 weights 回 CPU 真释放。
            if i > 0:
                try:
                    import comfy.model_management as _mm
                    import torch as _torch
                    for _lm in list(_mm.current_loaded_models):
                        try:
                            _lm.model.partially_unload(_lm.model.offload_device, 1e32)
                        except Exception:
                            pass
                    _mm.soft_empty_cache(force=True)
                    _torch.cuda.synchronize()
                    _torch.cuda.empty_cache()
                    _a = _torch.cuda.memory_allocated() / 1024 ** 3
                    _r = _torch.cuda.memory_reserved() / 1024 ** 3
                    print(f"[H3 Extender] clip[{i}] 显存已释放：allocated={_a:.2f}GB reserved={_r:.2f}GB")
                except Exception as _me:
                    print(f"[H3 Extender] 显存清理失败(可忽略): {_me}")
            positive, latent = _make_ref2va_conditioning(
                clip,
                vae,
                effective_prompt,
                resolved_width,
                resolved_height,
                frame_count,
                ref_items,
                ref_blocks,
                active_picture_slots,
            )

            trim_frames = None
            # v1.14: previous_proxy 为 None（前段无缓存）时不再 raise，防御性跳过
            # motion context（从当前段独立渲染，链拼接由 disk_join 的 previous_cache 保证）。
            if i > 0 and cfg.get("context_enabled", True) and previous_proxy is not None:
                positive, trim_frames, _, _, _ = motion.apply(
                    positive,
                    latent,
                    previous_proxy,
                    str(context_length),
                    int(audio_context_length),
                )

            _send_extender_progress(
                owner,
                i,
                len(clips),
                "sampling",
                f"Rendering clip {i + 1}/{len(clips)}",
            )

            try:
                sampled = _sample_h3(
                    sampling_model,
                    positive,
                    latent,
                    cfg["seed"],
                    str(sampler_name),
                    str(scheduler),
                    int(steps),
                    float(denoise),
                    owner_id=owner,
                    clip_index=i,
                )
            except comfy.model_management.InterruptProcessingException:
                _send_extender_progress(
                    owner, i, len(clips), "aborted",
                    "用户终止：渲染已中止（已保留已生成 CLIP）",
                )
                print("[H3 Extender] 用户终止渲染，停止后续 CLIP")
                break

            result = disk_join.join(
                samples=sampled,
                trim_frames=trim_frames,
                validated=False,
                run_mode=str(run_mode),
                fps=float(FPS),
                previous_cache=previous_handle,
                unique_id=f"extender_{owner}",
            )
            previous_handle = result[0]
            previous_proxy = result[1]
            statuses.append(result[4])
            generated.append(i)

            # Drop full sampled/conditioning references before the next clip.
            del sampled, positive, latent

            # 暂停渲染：当前CLIP生成完、下一个开始前——
            #   pause_enable=False：手动暂停键始终可用（用户点过「暂停」才等待）
            #   pause_enable=True ：每个CLIP生成完自动暂停等待（继续/仅当前/中止，无干预超时自动继续）
            if i < loop_end - 1:
                if int(pause_enable):
                    with _render_ctl_lock:
                        _ctl_now = _render_ctl.get(str(owner))
                        if _ctl_now is not None:
                            _ctl_now["state"] = "pause_requested"
                if not _maybe_pause_between(
                    owner, i, loop_end, len(clips), float(pause_timeout)
                ):
                    print(f"[H3 Extender] 渲染已暂停停止：保留已生成的 CLIP（共 {i + 1} 段），不自动合并")
                    paused_break = True
                    break
            # Decode this clip to MP4 so the frontend preview panel can play it
            # immediately without waiting for the Final Decode node.
            # v1.19: 暂停停止（paused_break）或单独生成（render_partial）时静默——跳过 preview 解码，
            # 只保留 latent 缓存，等待用户下一步（合并输出 / 全量渲染）。
            _preview_error = None
            if not paused_break and not render_partial:
                try:
                    _send_extender_progress(
                        owner, i, len(clips), "decoding_preview",
                        f"Decoding preview for clip {i + 1}/{len(clips)}",
                    )
                    _ff = _find_ffmpeg()
                    print(f"[H3 Extender] preview decode: clip={i} ffmpeg={_ff} vae={type(vae).__name__} audio_vae={type(audio_vae).__name__ if audio_vae else 'None'}")
                    _decode_single_clip_preview(
                        owner=owner,
                        clip_index=i,
                        vae=vae,
                        audio_vae=audio_vae,
                        fps=float(FPS),
                        ffmpeg=_ff,
                    )
                except Exception as _pv_err:
                    # Preview decode failure should never abort the main render loop.
                    _preview_error = str(_pv_err)
                    print(f"[H3 Extender] clip preview decode failed: {_pv_err}")
                    import traceback
                    traceback.print_exc()

            _send_extender_progress(
                owner,
                i,
                len(clips),
                "complete",
                f"Clip {i + 1}/{len(clips)} complete"
                + (f" (preview error: {_preview_error})" if _preview_error else ""),
            )

            # Each CLIP is decoded to IMAGE+AUDIO as soon as it finishes and
            # emitted before the next clip starts (streaming output).
            # v1.19: 暂停停止/单独生成静默，跳过 per-clip AV 解码。
            if not paused_break and int(output_image_audio) and not render_partial:
                try:
                    cimg, caud = _decode_clip_to_av(owner, i, vae, audio_vae, float(FPS))
                    if cimg is not None and int(cimg.shape[0]) > 0:
                        out_images.append(cimg)
                        _av_decoded.add(i)
                    if caud is not None:
                        out_audios.append(caud)
                    _send_clip_av_output(owner, i, len(clips), cimg, caud)
                except Exception as _av_err:
                    print(f"[H3 Extender] per-clip AV output failed clip={i}: {_av_err}")


        # All clips rendered; the last handle is the active cached prefix
        # expected by Final Decode.
        if previous_handle is None:
            # This can only happen if the workflow contains no valid cards,
            # which _parse_clips_json prevents. Keep a defensive error anyway.
            raise RuntimeError("MiniMax H3 Extender: sequence produced no cache handle.")

        # Restore saved tail latents after selective re-rendering.
        # This block is for legacy in-memory tail restore. In single-clip
        # replace mode, saved_tail is None (tail is on disk instead).
        if saved_tail is not None:
            print(f"[H3 Extender] per-clip replace: restoring {len(saved_tail)} tail clip(s)")
            restored_manifest = _restore_tail_latents(data_path, manifest_path, saved_tail)
            if restored_manifest is not None:
                manifest = restored_manifest
            m = _load_manifest_from_paths(data_path, manifest_path)
            if m is not None:
                segs = [dict(x) for x in m.get("segments", [])]
                changed = False
                for i in range(first_sel, min(len(clips), len(segs))):
                    if not bool(segs[i].get("validated", False)):
                        segs[i]["validated"] = True
                        changed = True
                    clips[i]["validated"] = True
                    clips[i]["replace_mode"] = False
                if changed:
                    m = dict(m)
                    m["segments"] = segs
                    m["build"] = BUILD
                    m["updated_at"] = time.time()
                    _write_json_atomic(manifest_path, m)

        # In single-clip replace mode, clear replace_mode flags and mark
        # the re-rendered clip as validated. Tail latents are on disk and
        # will be restored when user clicks "合并输出" (merge_output).
        if single_clip_replace:
            m = _load_manifest_from_paths(data_path, manifest_path)
            if m is not None:
                segs = [dict(x) for x in m.get("segments", [])]
                changed = False
                for i in range(min(len(clips), len(segs))):
                    if i in selected_set and not bool(segs[i].get("validated", False)):
                        segs[i]["validated"] = True
                        changed = True
                    if i in selected_set:
                        clips[i]["validated"] = True
                        clips[i]["replace_mode"] = False
                if changed:
                    m = dict(m)
                    m["segments"] = segs
                    m["build"] = BUILD
                    m["updated_at"] = time.time()
                    _write_json_atomic(manifest_path, m)

        # ── v1.12: 重渲染单个/多个 CLIP 后不再自动恢复尾部 + 自动合并 ──
        # 链已由主循环从选中段连续渲染到结束，直接标记完成、正常输出。
        auto_merged = False
        if single_clip_replace:
            single_clip_replace = False
            for cfg in clips:
                cfg["validated"] = True
                cfg["replace_mode"] = False
            print("[H3 Extender] per-clip replace complete → chain rendered continuously to end (no auto-merge)")

        final_manifest = _load_manifest_from_paths(data_path, manifest_path)
        # Color grading is montage metadata only. Keep it attached to each cached
        # decoded segment without invalidating latents or validation state.
        if final_manifest is not None:
            color_segments = [dict(x) for x in final_manifest.get("segments", [])]
            color_changed = False
            for color_i, desc in enumerate(color_segments):
                if color_i >= len(clips):
                    break
                wanted = _normalize_color_adjustment(clips[color_i].get("color_adjustment"))
                if desc.get("color_adjustment") != wanted:
                    desc["color_adjustment"] = wanted
                    color_segments[color_i] = desc
                    color_changed = True
            if color_changed:
                final_manifest = dict(final_manifest)
                final_manifest["segments"] = color_segments
                final_manifest["updated_at"] = time.time()
                _write_json_atomic(manifest_path, final_manifest)

        final_cache_resolution = _resolution_from_manifest(final_manifest)
        cached_count = len(final_manifest.get("segments", []))
        validated_count = 0
        for desc in final_manifest.get("segments", []):
            if bool(desc.get("validated", False)):
                validated_count += 1
            else:
                break

        normalized_json = _state_json(clips, active_prompt_pack_signature)
        if resolution.get("mode") == "auto_from_ref" and resolution.get("guide_ref") is not None:
            resolution_text = (
                f"{resolved_width}x{resolved_height} from ref_{int(resolution['guide_ref'])} "
                f"@ {float(resolution['megapixels']):.2f}MP"
            )
        elif resolution.get("fallback"):
            resolution_text = f"{resolved_width}x{resolved_height} manual fallback (no image ref)"
        else:
            resolution_text = f"{resolved_width}x{resolved_height} manual"

        if resolution.get("cache_reset") and previous_cache_resolution:
            resolution_text += (
                f" | resolution changed from "
                f"{int(previous_cache_resolution['width'])}x{int(previous_cache_resolution['height'])}: cache restarted"
            )
        prompt_pack_text = ""
        if external_prompt_pack is not None:
            prompt_pack_text = (
                f" | prompt pack {len(external_prompt_pack.get('prompts') or [])}"
                + (" imported" if prompt_pack_imported else " linked")
            )
        clip_select_text = ""
        if auto_merged:
            replaced = ",".join(str(i + 1) for i in sorted(selected_set))
            clip_select_text = f" | regenerated {replaced} | auto-merged"
        elif single_clip_replace:
            replaced = ",".join(str(i + 1) for i in sorted(selected_set))
            clip_select_text = f" | regenerated {replaced} | pending merge"
        elif any_replace:
            replaced = ",".join(str(i + 1) for i in sorted(selected_set))
            clip_select_text = f" | replace {replaced}"
        disabled = [i + 1 for i, c in enumerate(clips) if not c.get("render_enabled", True)]
        if disabled:
            clip_select_text += f" | skip {','.join(str(n) for n in disabled)}"
        if select_override is not None:
            _sel_min = min(select_override)
            if set(select_override) == set(range(_sel_min, len(clips))):
                sel_list = f"{_sel_min + 1}-{len(clips)}"
            else:
                sel_list = ",".join(str(n) for n in sorted(n + 1 for n in select_override))
            clip_select_text += f" | clip_select {{{sel_list}}}"
        status = (
            f"{str(run_mode)} | {resolution_text} | refs {_reference_count(refs)} | cached {cached_count}/{len(clips)} | "
            f"validated {validated_count}{prompt_pack_text}{clip_select_text} | "
            + (
                "generated " + ",".join(str(i + 1) for i in generated)
                if generated
                else "disk only"
            )
        )
        cache_mb = _cache_size_mb(data_path, manifest_path)

        _send_extender_progress(
            owner,
            -1,
            len(clips),
            "idle",
            status,
        )
        _release_render_ctl(owner)

        # ── Direct video output (per_clip / merged / both) ──────────────
        # Skip output only when single-clip replace is still pending (tail
        # latents not yet restored). After auto-restore, single_clip_replace
        # is set to False so output proceeds normally.
        output_ui_videos = []
        # v1.13: 单独选择生成 / 重渲染 / 暂停停止后禁止自动合并输出（merged）。
        # 仅「全量渲染且未干预」才自动合成 merged.mp4；否则只保留 per-clip 片段，
        # 由用户手动点「合并输出」按钮合成。
        suppress_auto_merge = bool(render_partial or paused_break)
        if suppress_auto_merge:
            print("[H3 Extender] 单独生成/暂停：跳过合并与一切视频输出，仅保留 latent 缓存，静默等待新指令（v1.18）")
        if str(output_mode) != "none" and final_manifest is not None and not single_clip_replace:
            try:
                out_dir = Path(folder_paths.get_output_directory()).resolve()
            except Exception:
                out_dir = (Path.cwd() / "output").resolve()
            out_dir.mkdir(parents=True, exist_ok=True)
            prefix = _safe_name(str(filename_prefix or "H3_Extender"))
            segments_out = [dict(x) for x in final_manifest.get("segments", [])]
            ff = None
            try:
                ff = _find_ffmpeg()
            except Exception:
                ff = None

            want_per_clip = str(output_mode) in ("per_clip", "both") and not suppress_auto_merge
            want_merged = str(output_mode) in ("merged", "both") and not suppress_auto_merge

            if want_per_clip:
                for si, seg in enumerate(segments_out):
                    blob = seg.get("decoded_mp4_blob")
                    if blob is None:
                        continue
                    clip_path = out_dir / f"{prefix}_clip{si + 1:02d}.mp4"
                    try:
                        _copy_blob_to_file(data_path, blob, clip_path)
                        item = _comfy_media_item(clip_path, float(FPS), "output")
                        output_ui_videos.append(item)
                        print(f"[H3 Extender] saved per-clip video: {clip_path}")
                    except Exception as _e:
                        print(f"[H3 Extender] failed to save clip {si+1}: {_e}")

            if want_merged and len(segments_out) > 0:
                # Build a concat list and merge all clip MP4s into one file
                temp_root = _ensure_cache_root()
                concat_list = temp_root / f"_concat_{owner}_{uuid.uuid4().hex[:8]}.txt"
                clip_paths = []
                for si, seg in enumerate(segments_out):
                    blob = seg.get("decoded_mp4_blob")
                    if blob is None:
                        continue
                    cp = temp_root / f"_mergeclip_{owner}_{si}_{uuid.uuid4().hex[:8]}.mp4"
                    try:
                        _copy_blob_to_file(data_path, blob, cp)
                        clip_paths.append(cp)
                    except Exception:
                        pass

                if clip_paths:
                    with open(concat_list, "w", encoding="utf-8") as f:
                        for cp in clip_paths:
                            f.write(f"file '{cp.as_posix()}'\n")

                    merged_path = out_dir / f"{prefix}_merged.mp4"
                    if len(clip_paths) == 1:
                        shutil.copy2(clip_paths[0], merged_path)
                    elif ff:
                        merge_cmd = [
                            ff, "-y", "-f", "concat", "-safe", "0",
                            "-i", str(concat_list),
                            "-c", "copy",
                            str(merged_path),
                        ]
                        merge_log = temp_root / f"_merge_{owner}_{uuid.uuid4().hex[:8]}.log"
                        try:
                            with open(merge_log, "wb") as lf:
                                subprocess.run(merge_cmd, stdout=subprocess.DEVNULL, stderr=lf, check=True)
                            print(f"[H3 Extender] saved merged video: {merged_path}")
                        except Exception as _e:
                            print(f"[H3 Extender] ffmpeg concat failed, trying re-encode: {_e}")
                            merge_cmd = [
                                ff, "-y", "-f", "concat", "-safe", "0",
                                "-i", str(concat_list),
                                "-c:v", "libx264", "-preset", "fast", "-crf", "17",
                                "-pix_fmt", "yuv420p",
                                str(merged_path),
                            ]
                            try:
                                with open(merge_log, "wb") as lf:
                                    subprocess.run(merge_cmd, stdout=subprocess.DEVNULL, stderr=lf, check=True)
                                print(f"[H3 Extender] saved merged video (re-encoded): {merged_path}")
                            except Exception as _e2:
                                print(f"[H3 Extender] merged re-encode also failed: {_e2}")
                    else:
                        shutil.copy2(clip_paths[0], merged_path)

                    if merged_path.exists():
                        item = _comfy_media_item(merged_path, float(FPS), "output")
                        output_ui_videos.append(item)

                    # Clean up temp files
                    for cp in clip_paths:
                        try:
                            cp.unlink()
                        except Exception:
                            pass
                    try:
                        concat_list.unlink()
                    except Exception:
                        pass

            if output_ui_videos:
                status += f" | saved {len(output_ui_videos)} video(s) to output"

        ui_state = {
            "clips_json": normalized_json,
            "clip_count": len(clips),
            "cached_count": cached_count,
            "validated_count": validated_count,
            "generated": [i + 1 for i in generated],
            "status": status,
            "resolved_width": resolved_width,
            "resolved_height": resolved_height,
            "resolution_mode": str(resolution.get("mode") or "manual"),
            "resolution_guide": (
                f"ref_{int(resolution['guide_ref'])}"
                if resolution.get("guide_ref") is not None
                else ""
            ),
            "resolution_guide_width": int(resolution.get("guide_src_width", 0) or 0),
            "resolution_guide_height": int(resolution.get("guide_src_height", 0) or 0),
            "resolution_fallback": bool(resolution.get("fallback", False)),
            "megapixels": float(resolution.get("megapixels", megapixels)),
            "cache_width": int(final_cache_resolution["width"]) if final_cache_resolution else 0,
            "cache_height": int(final_cache_resolution["height"]) if final_cache_resolution else 0,
            "resolution_mismatch": False,
            "resolution_cache_locked": False,
            "resolution_cache_reset": bool(resolution.get("cache_reset", False)),
            "reference_cache_reset": False,
            "reference_count": int(_reference_count(refs)),
            "refs_json": _refs_json(refs),
            "requested_width": int(resolution.get("requested_width", resolved_width)),
            "requested_height": int(resolution.get("requested_height", resolved_height)),
            "prompt_pack_connected": external_prompt_pack is not None,
            "prompt_pack_imported": bool(prompt_pack_imported),
            "prompt_pack_count": int(len(external_prompt_pack.get("prompts") or [])) if external_prompt_pack is not None else 0,
            "prompt_pack_signature": str(active_prompt_pack_signature or ""),
            "global_prompt_connected": bool(prompt_source),
            "global_prompt_value": str(global_prompt or "")[:200],
            "prompt_source_connected": bool(prompt_source),
            "prompt_source_value": str(prompt_source or "")[:200],
            "asset_library_connected": bool(asset_library),
            "asset_image_count": len(resolved_img_paths) if 'resolved_img_paths' in locals() else 0,
            "build": BUILD,
        }

        ui_payload = {"h3_extender_state": [ui_state]}
        if output_ui_videos:
            ui_payload["h3_video"] = output_ui_videos

        if previous_handle and isinstance(previous_handle, dict):
            print(f"[H3 Extender] RETURNING cache handle: nonce={previous_handle.get('exec_nonce','N/A')} run_token={previous_handle.get('run_token','N/A')} next_index={previous_handle.get('next_index','N/A')}")

        # ── Extract per-clip preview MP4 files for BSAI Premiere Pro ──
        # Each clip's decoded MP4 blob is extracted from the .h3cache data
        # file to a standalone MP4 in ComfyUI's temp directory. The file
        # paths + metadata are returned as a JSON string so the Premiere
        # Pro node can add them to its timeline.
        clip_videos_json = "[]"
        # v1.18: 单独生成/暂停后静默，不提取 clip_videos（等用户后续合并输出/全量渲染）。
        if not suppress_auto_merge:
            try:
                final_manifest = _load_manifest_from_paths(data_path, manifest_path)
                if final_manifest and final_manifest.get("segments"):
                    segments = [dict(x) for x in final_manifest["segments"]]
                    root = _ensure_cache_root()
                    import folder_paths as _fp
                    temp_dir = Path(_fp.get_temp_directory())
                    clips_info = []
                    for si, seg in enumerate(segments):
                        blob = seg.get("decoded_mp4_blob")
                        if blob is None:
                            print(f"[H3 Extender] clip_videos: segment {si} has no decoded blob, skipping")
                            continue
                        clip_name = clips[si].get("name", f"CLIP{si+1}") if si < len(clips) else f"CLIP{si+1}"
                        out_name = f"h3_clip_{owner}_{si+1}_{int(time.time())}.mp4"
                        out_path = temp_dir / out_name
                        _copy_blob_to_file(data_path, blob, out_path)
                        trim = int(seg.get("trim_frames", 0)) if si > 0 else 0
                        total_frames = int(seg.get("frames", 0))
                        out_frames = total_frames - trim
                        clip_fps = float(final_manifest.get("fps", FPS))
                        duration = float(out_frames) / clip_fps if clip_fps > 0 else 0.0
                        has_audio = bool(seg.get("decoded_mp4_has_audio", False))
                        w = int(seg.get("width", resolved_width))
                        h = int(seg.get("height", resolved_height))
                        clips_info.append({
                            "clip_index": si,
                            "clip_name": clip_name,
                            "file_path": str(out_path),
                            "file_name": out_name,
                            "duration": round(duration, 3),
                            "width": w,
                            "height": h,
                            "fps": clip_fps,
                            "has_audio": has_audio,
                            "frames": out_frames,
                        })
                        print(f"[H3 Extender] clip_videos: extracted clip {si+1} -> {out_path} ({out_frames} frames, {duration:.1f}s)")
                    clip_videos_json = json.dumps(clips_info, ensure_ascii=False)
                    print(f"[H3 Extender] clip_videos: {len(clips_info)} clip(s) ready for Premiere Pro")
            except Exception as _cv_err:
                print(f"[H3 Extender] clip_videos extraction failed: {_cv_err}")
                import traceback
                traceback.print_exc()

        # Decode any validated (cached, not re-generated) clips so the
        # IMAGE/AUDIO outputs always carry the complete film.
        # v1.18: render_partial 静默，跳过 AV 汇总解码。
        if int(output_image_audio) and not suppress_auto_merge:
            try:
                final_m = _load_manifest_from_paths(data_path, manifest_path)
                if final_m is not None:
                    segs = [dict(x) for x in final_m.get("segments", [])]
                    for ci in range(len(segs)):
                        if ci in _av_decoded:
                            continue
                        cimg, caud = _decode_clip_to_av(owner, ci, vae, audio_vae, float(FPS))
                        if cimg is not None and int(cimg.shape[0]) > 0:
                            out_images.append(cimg)
                        if caud is not None:
                            out_audios.append(caud)
            except Exception as _av2:
                print(f"[H3 Extender] cached-clip AV decode failed: {_av2}")

        out_images_t, out_audios_t = _concat_clip_av(out_images, out_audios)
        if len(out_images) > 0:
            print(f"[H3 Extender] AV outputs: {int(out_images_t.shape[0])} frames, "
                  f"audio {int(out_audios_t['waveform'].shape[-1])} samples @ "
                  f"{int(out_audios_t['sample_rate'])}Hz")

        return {
            "ui": ui_payload,
            "result": (
                previous_handle,
                int(len(clips)),
                int(validated_count),
                status,
                float(cache_mb),
                BUILD,
                clip_videos_json,
                out_images_t,
                out_audios_t,
            ),
        }


NODE_CLASS_MAPPINGS = {
    "BSAIH3FilmFactory": BSAIH3FilmFactory,
    # Intermediate name kept for backward compat with workflows
    # created during the rename transition period.
    "BSAIMiniMaxH3Extender": BSAIH3FilmFactory,
    # Final Decode node — reads from our plugin's cache directory
    "BSAIH3FilmFactoryFinalDecode": MiniMaxH3MotionContextDiskFinalDecode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "BSAIH3FilmFactory": "BSAI ComfyUI H3 Film Factory",
    "BSAIMiniMaxH3Extender": "BSAI ComfyUI H3 Film Factory",
    "BSAIH3FilmFactoryFinalDecode": "BSAI H3 Final Decode & Export",
}


if getattr(PromptServer, "instance", None) is not None:
    @PromptServer.instance.routes.post("/h3_extender/ref/upload")
    async def h3_extender_ref_upload(request):
        """Upload one image reference and store the actual pixels internally."""
        temp_path = _project_temp_root() / f"ref_upload_{uuid.uuid4().hex}.bin"
        original_name = "reference.png"
        got_file = False
        size = 0
        try:
            reader = await request.multipart()
            while True:
                part = await reader.next()
                if part is None:
                    break
                if part.name != "ref_file":
                    continue
                original_name = str(part.filename or "reference.png")
                with open(temp_path, "wb") as f:
                    while True:
                        chunk = await part.read_chunk(size=PROJECT_COPY_CHUNK)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > MAX_REF_UPLOAD_BYTES:
                            raise ValueError(
                                f"MiniMax H3 Extender: reference upload exceeds {MAX_REF_UPLOAD_BYTES // (1024 * 1024)} MB."
                            )
                        f.write(chunk)
                    f.flush()
                    os.fsync(f.fileno())
                got_file = True
                break

            if not got_file or not temp_path.exists() or temp_path.stat().st_size <= 0:
                return web.json_response(
                    {"ok": False, "error": "No reference image was uploaded."}, status=400
                )
            try:
                ref = await asyncio.to_thread(
                    _store_uploaded_reference,
                    temp_path,
                    original_name,
                )
            except Exception as exc:
                return web.json_response({"ok": False, "error": str(exc)}, status=400)
            return web.json_response({"ok": True, "ref": ref})
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass

    @PromptServer.instance.routes.post("/h3_extender/ref/edit")
    async def h3_extender_ref_edit(request):
        """Apply simple photographic adjustments to an internal reference."""
        try:
            body = await request.json()
            source_id = str(body.get("source_id") or body.get("ref_id") or "").lower().strip()
            if not _ref_id_is_safe(source_id):
                return web.json_response(
                    {"ok": False, "error": "Invalid source reference id."}, status=400
                )

            ref = await asyncio.to_thread(
                _edit_internal_reference,
                source_id,
                str(body.get("original_name") or "reference.png"),
                body.get("brightness", 100),
                body.get("contrast", 100),
                body.get("saturation", 100),
            )
            return web.json_response({"ok": True, "ref": ref})
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    @PromptServer.instance.routes.get("/h3_extender/ref/image")
    async def h3_extender_ref_image(request):
        """Serve an internally managed reference thumbnail/full preview."""
        ref_id = str(request.query.get("id", "")).lower().strip()
        if not _ref_id_is_safe(ref_id):
            return web.Response(status=400, text="Invalid reference id.")
        path = _ref_path(ref_id)
        if not path.exists():
            return web.Response(status=404, text="Reference image not found.")
        return web.FileResponse(
            path,
            headers={
                "Content-Type": "image/png",
                "Cache-Control": "public, max-age=31536000, immutable",
            },
        )

    @PromptServer.instance.routes.get("/h3_extender/cache/open")
    async def h3_extender_cache_open(request):
        """v1.16: 打开 latent 缓存目录 / CLIP 视频输出目录，并返回路径+文件列表。
        kind=latent -> cache/（chain_extender_*.h3cache 等）
        kind=clips  -> ComfyUI temp/（h3_clip_*.mp4，即 BSAI Premiere Pro 接收端口读取的文件目录）"""
        kind = str(request.query.get("kind", "latent")).strip().lower()
        try:
            if kind == "clips":
                d = Path(folder_paths.get_temp_directory())
            else:
                d = _ensure_cache_root()
            d = d.resolve()
            files = []
            if d.exists() and d.is_dir():
                for p in sorted(d.iterdir()):
                    if p.is_file():
                        try:
                            st = p.stat()
                            files.append({
                                "name": p.name,
                                "size": st.st_size,
                                "mtime": st.st_mtime,
                            })
                        except Exception:
                            pass
            opened = False
            try:
                if os.name == "nt":
                    os.startfile(str(d))
                    opened = True
                else:
                    import subprocess
                    subprocess.Popen(["xdg-open", str(d)])
                    opened = True
            except Exception:
                opened = False
            return web.json_response({
                "ok": True,
                "kind": kind,
                "path": str(d),
                "opened": opened,
                "files": files,
            })
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    @PromptServer.instance.routes.post("/h3_extender/project/prepare_save")
    async def h3_extender_project_prepare_save(request):
        """Build a portable .ext archive without buffering the cache in RAM."""
        try:
            body = await request.json()
            owner_id = str(body.get("owner_id", "")).strip()
            if not owner_id:
                return web.json_response(
                    {"ok": False, "error": "Missing Extender node id."}, status=400
                )
            project_payload = body.get("project", {})
            if not isinstance(project_payload, dict):
                return web.json_response(
                    {"ok": False, "error": "Invalid project metadata."}, status=400
                )

            _cleanup_project_downloads()
            filename = _project_filename(body.get("project_name", "MiniMax_H3_Project"))
            token = uuid.uuid4().hex
            temp_path = _project_temp_root() / f"download_{token}.ext"

            try:
                archive_meta = await asyncio.to_thread(
                    _build_project_archive,
                    owner_id,
                    filename,
                    project_payload,
                    temp_path,
                )
            except Exception as exc:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass
                return web.json_response(
                    {"ok": False, "error": str(exc)}, status=500
                )

            _PROJECT_DOWNLOADS[token] = {
                "path": str(temp_path),
                "filename": filename,
                "created_at": time.time(),
            }
            return web.json_response({
                "ok": True,
                "token": token,
                "filename": filename,
                "size_bytes": int(temp_path.stat().st_size),
                "cache": archive_meta.get("cache", {}),
                "references": archive_meta.get("references", {}),
            })
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=500)

    @PromptServer.instance.routes.get("/h3_extender/project/download")
    async def h3_extender_project_download(request):
        """Stream a prepared .ext directly to the browser, then remove the temp file."""
        _cleanup_project_downloads()
        token = str(request.query.get("token", "")).strip()
        info = _PROJECT_DOWNLOADS.pop(token, None)
        if not info:
            return web.Response(status=404, text="Project download expired or was not found.")

        path = Path(info["path"])
        if not path.exists():
            return web.Response(status=404, text="Project file no longer exists.")

        filename = _project_filename(info.get("filename", "MiniMax_H3_Project.ext"))
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(path.stat().st_size),
                "Cache-Control": "no-store",
            },
        )
        try:
            await response.prepare(request)
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(PROJECT_COPY_CHUNK)
                    if not chunk:
                        break
                    await response.write(chunk)
            await response.write_eof()
            return response
        finally:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass

    @PromptServer.instance.routes.post("/h3_extender/project/load")
    async def h3_extender_project_load(request):
        """Import a .ext into the cache owned by the Extender node making the request."""
        upload_path = _project_temp_root() / f"upload_{uuid.uuid4().hex}.ext"
        owner_id = ""
        original_name = ""
        got_file = False
        try:
            reader = await request.multipart()
            while True:
                part = await reader.next()
                if part is None:
                    break
                if part.name == "owner_id":
                    owner_id = (await part.text()).strip()
                elif part.name == "project_file":
                    original_name = str(part.filename or "project.ext")
                    with open(upload_path, "wb") as f:
                        while True:
                            chunk = await part.read_chunk(size=PROJECT_COPY_CHUNK)
                            if not chunk:
                                break
                            f.write(chunk)
                        f.flush()
                        os.fsync(f.fileno())
                    got_file = True

            if not owner_id:
                return web.json_response(
                    {"ok": False, "error": "Missing Extender node id."}, status=400
                )
            if not got_file or not upload_path.exists():
                return web.json_response(
                    {"ok": False, "error": "No .ext project file was uploaded."}, status=400
                )

            try:
                imported = await asyncio.to_thread(
                    _import_project_archive,
                    owner_id,
                    upload_path,
                )
            except zipfile.BadZipFile:
                return web.json_response(
                    {"ok": False, "error": "The selected .ext file is not a valid project archive."},
                    status=400,
                )
            except Exception as exc:
                return web.json_response(
                    {"ok": False, "error": str(exc)}, status=400
                )

            imported["ok"] = True
            imported["source_filename"] = original_name
            return web.json_response(imported)
        finally:
            try:
                upload_path.unlink(missing_ok=True)
            except Exception:
                pass
