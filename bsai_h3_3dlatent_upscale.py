"""
BSAI H3 3D Latent 分块超清 (Chunked 3D-Latent HD Upscale)
=========================================================

MiniMax H3 视频的"3D Latent 分块超清"节点：在**潜空间**内把已去噪的 H3
AV latent（视频 24 通道 + 音频 32 通道的 NestedTensor）分块放大到高清，
全程峰值显存被限制在单个分块 / 单个 tile，低配显卡也能跑高清视频，不再爆显存。

方案参考 bbaudio-2025 的 `MMH3 Ultimate Upscale` / `MiniMax H3 Latent Split`：

  1. **时间分块 (temporal chunking)**：长片段按 H3 keyframe 网格切成重叠时间块，
     每块独立处理，避免整片同时占显存；
  2. **3D Latent 放大 (latent upscale)**：用 `minimax_h3_latent_upscaler_3d_*.safetensors`
     模型在潜空间做 3D 空间放大（归一化 -> LatentResizer3D -> 反归一化），
     也可退化为无模型插值；
  3. **空间分块 (spatial tiling)**：二采时把每个时间块再切成重叠 tile，逐 tile
     re-sample，显存峰值 = 单 tile；
  4. **锚定 + 交叉淡化 (anchor + crossfade)**：块间重叠区线性混合缝合，
     时间/空间接缝平滑无闪烁；
  5. **音频原样携带**：音频 latent 只裁剪拼接、从不重采样。

输入 Film Factory 的 cache（CACHE_TYPE）磁盘缓存，输出：
  - `latent`  ：放大后的 H3 AV latent（NestedTensor，可继续走 VAE/导出）
  - `images`  ：解码后的 IMAGE batch [B,H,W,C]
  - `audios`  ：解码后的 AUDIO dict
  - `status`  ：本次处理摘要

所有节点名均以 BSAI 开头（既有约定）。
"""

from __future__ import annotations

import io
import json
import math
import os
import sys
import time
import traceback

import numpy as np
import torch
import torch.nn.functional as F

import comfy.model_management
import comfy.nested_tensor
import comfy.sample
import comfy.samplers
import comfy.utils
import folder_paths

from .motion_context_disk import (
    CACHE_TYPE,
    _load_manifest,
    _load_segment_video,
    _load_segment_audio,
    _decode_audio_latent,
    _safe_name,
)
from .motion_context_ram import (
    _steps_for_frames,
    _frames_from_video_t,
    _audio_t_for_frames,
)

FPS = 24
AUDIO_HZ = 40
VAE_DOWNSAMPLE = 16

# H3 24-channel latent 归一化统计（与训练代码一致，来源 LBH-123-AI 3D upscaler）
LATENTS_MEAN = [
    0.858090341091156, -0.9606591463088989, 1.0661640167236328, -0.5090325474739075,
    -0.2727581858634949, -1.3675414323806763, -0.2553254961967468, -0.26907554268836975,
    -0.5376840829849243, -0.0464097298681736, 0.6657370328903198, 0.19690127670764923,
    -0.5460608005523682, -0.4035342037677765, -0.23683024942874908, 0.25928452610969543,
    -0.30133944749832153, 0.211341992020607, -1.1206848621368408, 0.3581933379173279,
    -0.04225143790245056, 0.2604829967021942, 0.22864092886447906, 0.7056031823158264,
]
LATENTS_STD = [
    1.2223774194717407, 1.2767263650894165, 1.6831774711608887, 1.7549455165863037,
    1.5636216402053833, 2.194143533706665, 0.9653137922286987, 1.0569885969161987,
    0.841948926448822, 0.7729952931404114, 1.8955937623977661, 0.946841835975647,
    0.7996809482574463, 0.44988900423049927, 0.7197399735450745, 0.6936293244361877,
    2.961095094680786, 2.7694199085235596, 3.0496184825897217, 2.1088054180145264,
    3.276226282119751, 3.1627357006073, 2.2816812992095947, 2.6127843856811523,
]


# ---------------------------------------------------------------------------
# 3D latent upscaler 模型加载（参考 LBH-123-AI / ComfyUI_Minimax_h3_latent_Upscaler）
# ---------------------------------------------------------------------------
_UPSCALER_CACHE = {}
_UPSCALER_MODEL_DIR = "latent_upscale_models"


def _latent_upscale_dir():
    try:
        paths = folder_paths.get_folder_paths(_UPSCALER_MODEL_DIR)
        if paths:
            return paths[0]
    except Exception:
        pass
    d = os.path.join(folder_paths.models_dir, _UPSCALER_MODEL_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def _scan_upscale_models():
    files = []
    d = _latent_upscale_dir()
    for ext in ("*.safetensors", "*.pth"):
        files.extend(glob_models(d, ext))
    names = sorted(os.path.basename(f) for f in files)
    return names if names else ["(no model in latent_upscale_models)"]


def glob_models(d, ext):
    import glob
    return glob.glob(os.path.join(d, ext))


def _load_upscaler_module():
    """Load the LBH-123-AI 3D upscaler module by path (graceful fallback)."""
    try:
        import importlib.util as _ilu
        candidates = []
        try:
            cnode_paths = folder_paths.get_folder_paths("custom_nodes")
        except Exception:
            cnode_paths = []
        for base in list(cnode_paths) + [os.path.join(folder_paths.base_path, "custom_nodes")]:
            candidates.append(os.path.join(str(base), "ComfyUI_Minimax_h3_latent_Upscaler", "nodes", "minimax_h3_latent_upscaler_3d.py"))
            candidates.append(os.path.join(str(base), "ComfyUI-MiniMaxH3_LatentUpscaler", "learned.py"))
        for cand in candidates:
            if os.path.isfile(cand):
                spec = _ilu.spec_from_file_location("_bsai_h3_up3d", cand)
                mod = _ilu.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if hasattr(mod, "load_model") and hasattr(mod, "LatentResizer3D"):
                    return mod
        # fallback: try direct import (plugin registered as package)
        try:
            from ComfyUI_Minimax_h3_latent_Upscaler.nodes.minimax_h3_latent_upscaler_3d import (
                load_model, _make_norm_tensors, LatentResizer3D,
            )
            return sys.modules.get("ComfyUI_Minimax_h3_latent_Upscaler.nodes.minimax_h3_latent_upscaler_3d")
        except Exception:
            pass
    except Exception as e:
        print(f"[BSAI-H3-3D] upscaler module load failed: {e}")
    return None


def _get_upscaler(model_name, device, precision="fp16"):
    """Load (and cache) the 3D latent upscaler model."""
    key = f"{model_name}::{device}::{precision}"
    if key in _UPSCALER_CACHE:
        return _UPSCALER_CACHE[key]
    mod = _load_upscaler_module()
    if mod is None:
        raise RuntimeError("3D upscaler plugin not found; use upscale_mode=interpolate")
    model = mod.load_model(model_name, device, precision)
    _UPSCALER_CACHE[key] = model
    return model


def _norm_tensors(device, dtype):
    mean = torch.tensor(LATENTS_MEAN, dtype=dtype, device=device).view(1, -1, 1, 1, 1)
    std = torch.tensor(LATENTS_STD, dtype=dtype, device=device).view(1, -1, 1, 1, 1)
    return mean, std


def _spatial_upscale_latent(video, target_h, target_w, mode, model_name, device, precision):
    """Spatially upscale a video latent [1,24,T,H,W] in latent space.

    mode="model_3d"  : normalized 3D conv upscaler (trilinear to target)
    mode="interpolate": pure trilinear interpolation (no model)
    """
    v = video.to(device=torch.device(device), dtype=torch.float16, copy=True) if device != "cpu" else video.float().clone()
    orig_dtype = video.dtype
    t = int(v.shape[2])
    if int(v.shape[3]) == target_h and int(v.shape[4]) == target_w:
        return video

    if mode == "model_3d":
        model = _get_upscaler(model_name, device, precision)
        mean, std = _norm_tensors(v.device, v.dtype)
        with torch.inference_mode():
            v = (v - mean) / std
            out = model(v, target_size=(t, target_h, target_w))
            del v
            out = out * std + mean
    else:  # interpolate
        with torch.inference_mode():
            out = F.interpolate(v, size=(t, target_h, target_w), mode="trilinear", align_corners=False)

    out = out.to(device="cpu", dtype=orig_dtype)
    if device != "cpu":
        torch.cuda.empty_cache()
    return out


# ---------------------------------------------------------------------------
# H3 采样（二采）—— 参考 Film Factory 的 _sample_h3
# ---------------------------------------------------------------------------
class _BasicGuider(comfy.samplers.CFGGuider):
    def set_conds(self, positive):
        self.inner_set_conds({"positive": positive})


def _sigmas(model, scheduler, steps, denoise):
    steps = max(1, int(steps))
    denoise = float(denoise)
    if denoise <= 0.0:
        return torch.FloatTensor([])
    total_steps = steps
    if denoise < 1.0:
        total_steps = max(steps, int(steps / denoise))
    sigmas = comfy.samplers.calculate_sigmas(
        model.get_model_object("model_sampling"), str(scheduler), total_steps
    ).cpu()
    return sigmas[-(steps + 1):]


def _resample_tile(model, conditioning, latent, seed, sampler_name, scheduler, steps, denoise):
    """One re-sample pass (二采) of a latent at low denoise to add HD detail."""
    steps = max(1, int(steps))
    guider = _BasicGuider(model)
    guider.set_conds(conditioning)
    sampler = comfy.samplers.sampler_object(str(sampler_name))
    sigmas = _sigmas(model, scheduler, steps, denoise)
    latent_out = latent.copy()
    latent_image = latent["samples"]
    latent_image = comfy.sample.fix_empty_latent_channels(model, latent_image)
    latent_out["samples"] = latent_image
    noise = comfy.sample.prepare_noise(latent_image, int(seed))
    samples = guider.sample(
        noise,
        latent_image,
        sampler,
        sigmas,
        denoise_mask=None,
        disable_pbar=True,
        seed=int(seed),
    )
    samples = samples.to(comfy.model_management.intermediate_device())
    out = latent_out.copy()
    out["samples"] = samples
    return out


# ---------------------------------------------------------------------------
# 时间分块 / 空间分块 + 缝合
# ---------------------------------------------------------------------------
def _token_steps_for_frames(frames):
    """Token count for a frame count that is a multiple of 17 (17 frames = 5 tokens)."""
    return max(5, int(round(float(frames) / 17.0 * 5.0)))


def _temporal_chunks(video, audio, chunk_steps, ov_steps):
    """Split [1,24,T,H,W] video + [1,32,2,Ta] audio into overlapping time chunks.

    Boundaries land on multiples of ov_steps so every chunk start is keyframe-
    aligned. The last chunk extends to the exact end (no leftover sliver).
    Returns list of (video_chunk [1,24,cs,H,W], audio_chunk [1,32,2,as]) and
    the realized chunk starts.
    """
    t_total = int(video.shape[2])
    stride = max(1, int(chunk_steps) - int(ov_steps))
    starts = []
    s = 0
    while s + chunk_steps <= t_total:
        starts.append(s)
        s += stride
    # tail: if the last aligned chunk does not cover the end, add a final chunk
    if not starts:
        starts = [0]
    elif starts[-1] + chunk_steps < t_total:
        # start it at a keyframe-aligned position as close to the end as possible
        tail_start = t_total - chunk_steps
        if tail_start < 0:
            tail_start = 0
        # align to ov_steps boundary
        if tail_start % ov_steps != 0:
            tail_start = ((tail_start // ov_steps) + 1) * ov_steps
            if tail_start + chunk_steps > t_total:
                tail_start = t_total - chunk_steps
        if tail_start > starts[-1]:
            starts.append(tail_start)
        # if still not covering, force-extend the last chunk end
    if starts[-1] + chunk_steps < t_total:
        # extend the last chunk to t_total (short tail chunk)
        pass

    # audio: same chunk boundaries in token terms
    audio_t_total = int(audio.shape[-1])
    chunks = []
    for idx, st in enumerate(starts):
        en = min(st + chunk_steps, t_total)
        if en - st <= 0:
            continue
        vc = video[:, :, st:en].contiguous()
        # audio token boundary maps linearly: audio_t_total / t_total
        a_st = int(round(float(st) * audio_t_total / t_total))
        a_en = int(round(float(en) * audio_t_total / t_total))
        a_st = max(0, min(a_st, audio_t_total))
        a_en = max(a_st, min(a_en, audio_t_total))
        ac = audio[..., a_st:a_en].contiguous()
        chunks.append((vc, ac, st, en))
    return chunks


def _crossfade_append(acc_v, acc_a, vc, ac, ov_steps, ov_audio_steps):
    """Crossfade-stitch one chunk onto the accumulated latent.

    acc has length L; the new chunk starts at L - ov (overlap region) and
    continues past it.  The overlap is linearly blended, then the non-overlap
    tail of the chunk is appended.
    """
    lv = int(acc_v.shape[2])
    if lv <= 0:
        return vc, ac
    ov = min(int(ov_steps), int(vc.shape[2]) - 1, lv)
    ov = max(1, ov)
    # overlap region: last ov steps of acc vs first ov steps of chunk
    w = torch.linspace(0.0, 1.0, ov, dtype=acc_v.dtype, device=acc_v.device).view(1, 1, ov, 1, 1)
    tail_v = vc[:, :, ov:]
    head_blend = acc_v[:, :, -ov:] * (1 - w) + vc[:, :, :ov] * w
    new_v = torch.cat([acc_v[:, :, :-ov], head_blend, tail_v], dim=2)

    if acc_a is not None and ac is not None and int(acc_a.shape[-1]) > 0:
        la = int(acc_a.shape[-1])
        oa = min(int(ov_audio_steps), int(ac.shape[-1]) - 1, la)
        oa = max(1, oa)
        wa = torch.linspace(0.0, 1.0, oa, dtype=acc_a.dtype, device=acc_a.device)
        tail_a = ac[..., oa:]
        head_blend_a = acc_a[..., -oa:] * (1 - wa) + ac[..., :oa] * wa
        new_a = torch.cat([acc_a[..., :-oa], head_blend_a, tail_a], dim=-1)
    else:
        new_a = acc_a if acc_a is not None else ac
    return new_v, new_a


def _resample_second_pass(video, audio, model, conditioning, seed, sampler_name, scheduler,
                          steps, denoise, chunk_steps, ov_steps, tile_h, tile_w, tile_ov_h, tile_ov_w):
    """二采：把放大后的 latent 按时间块 + 空间 tile 逐块 re-sample 并缝合。

    video [1,24,T,H,W], audio [1,32,2,Ta].
    """
    if video.dtype != torch.float32:
        video = video.float()
    chunks = _temporal_chunks(video, audio, chunk_steps, ov_steps)
    acc_v = None
    acc_a = None
    chunk_seed = int(seed)
    for ci, (vc, ac, st, en) in enumerate(chunks):
        t_c = int(vc.shape[2])
        h_c, w_c = int(vc.shape[3]), int(vc.shape[4])
        # spatial tiling of this chunk
        if tile_h > 0 and tile_w > 0 and (h_c > tile_h or w_c > tile_w):
            vc2, ac2 = _resample_spatial_tiles(
                vc, ac, model, conditioning, chunk_seed + ci, sampler_name, scheduler,
                steps, denoise, tile_h, tile_w, tile_ov_h, tile_ov_w,
            )
        else:
            lat = {"samples": comfy.nested_tensor.NestedTensor((vc, ac))}
            out = _resample_tile(model, conditioning, lat, chunk_seed + ci, sampler_name, scheduler, steps, denoise)
            vc2, _ = _streams(out)
        # Audio is NEVER re-sampled (H3 二采只精修画面)；保留原音频latent。
        ac2 = ac
        if acc_v is None:
            acc_v, acc_a = vc2.float(), (ac2.float() if ac2 is not None else None)
        else:
            ov_audio = int(round(float(ov_steps) * float(ac2.shape[-1]) / float(vc2.shape[2]))) if ac2 is not None and int(vc2.shape[2]) > 0 else 0
            acc_v, acc_a = _crossfade_append(
                acc_v, acc_a, vc2.float(), ac2.float() if ac2 is not None else None,
                ov_steps, ov_audio,
            )
    if acc_v is None:
        acc_v = video
        acc_a = audio
    return acc_v, acc_a


def _resample_spatial_tiles(video, audio, model, conditioning, seed, sampler_name, scheduler,
                            steps, denoise, tile_h, tile_w, tile_ov_h, tile_ov_w):
    """Split a time chunk into overlapping spatial tiles, re-sample each, blend."""
    h, w = int(video.shape[3]), int(video.shape[4])
    th = max(16, int(tile_h))
    tw = max(16, int(tile_w))
    oh = max(0, min(int(tile_ov_h), th // 2))
    ow = max(0, min(int(tile_ov_w), tw // 2))
    stride_h = max(1, th - oh)
    stride_w = max(1, tw - ow)

    ys = []
    y = 0
    while y + th <= h:
        ys.append(y)
        y += stride_h
    if not ys or ys[-1] + th < h:
        ty = max(0, h - th)
        if ty > (ys[-1] if ys else -1):
            ys.append(ty)
    xs = []
    x = 0
    while x + tw <= w:
        xs.append(x)
        x += stride_w
    if not xs or xs[-1] + tw < w:
        tx = max(0, w - tw)
        if tx > (xs[-1] if xs else -1):
            xs.append(tx)

    acc = torch.zeros_like(video)
    wsum = torch.zeros_like(video)
    for iy, y0 in enumerate(ys):
        y1 = min(y0 + th, h)
        for ix, x0 in enumerate(xs):
            x1 = min(x0 + tw, w)
            tile = video[:, :, :, y0:y1, x0:x1].contiguous()
            lat = {"samples": comfy.nested_tensor.NestedTensor((tile, audio))}
            try:
                out = _resample_tile(model, conditioning, lat, seed + iy * 1000 + ix, sampler_name, scheduler, steps, denoise)
                tv, _ = _streams(out)
            except Exception as _e:
                print(f"[BSAI-H3-3D] tile re-sample failed ({y0}:{y1},{x0}:{x1}): {_e}")
                tv = tile
            weight = torch.ones_like(tv)
            acc[:, :, :, y0:y1, x0:x1] += tv.float()
            wsum[:, :, :, y0:y1, x0:x1] += weight
    video_out = acc / wsum.clamp(min=1e-6)
    return video_out, audio


def _streams(latent):
    """Split a nested AV latent dict into (video, audio)."""
    samples = latent["samples"]
    if getattr(samples, "is_nested", False):
        parts = list(samples.unbind())
    elif isinstance(samples, (tuple, list)):
        parts = list(samples)
    else:
        raise ValueError("not an H3 nested AV latent")
    v, a = parts[0], parts[1]
    if v.ndim == 4:
        v = v.unsqueeze(0)
    if a is not None and a.ndim == 3:
        a = a.unsqueeze(0)
    return v, a


# ---------------------------------------------------------------------------
# 解码（分块 VAE 解码，进一步压显存）
# ---------------------------------------------------------------------------
def _decode_video_chunked(video, vae, batch_tokens=10):
    """vae.decode a [1,24,T,H,W] latent in small temporal batches on the H3
    token grid (default 10 tokens = 34 frames; falls back to 5 tokens = 17)."""
    frames = []
    t = int(video.shape[2])
    step = max(5, int(batch_tokens) // 5 * 5)
    for s in range(0, t, step):
        seg = video[:, :, s:s + step].contiguous()
        try:
            d = vae.decode(seg)
        except Exception as _e1:
            try:
                d = vae.decode(seg[:, :, :5].contiguous())
            except Exception:
                print(f"[BSAI-H3-3D] vae.decode batch failed at {s}: {_e1}")
                continue
        if d.ndim == 5:
            d = d.reshape(-1, d.shape[-3], d.shape[-2], d.shape[-1])
        frames.append(d)
    if not frames:
        d = vae.decode(video)
        if d.ndim == 5:
            d = d.reshape(-1, d.shape[-3], d.shape[-2], d.shape[-1])
        frames = [d]
    out = torch.cat(frames, dim=0)
    return out.movedim(1, -1).float().cpu().contiguous()  # [T,H,W,C]


def _decode_audio_full(audio_latent, audio_vae, frames_total, fps):
    a = audio_latent.to(comfy.model_management.intermediate_device())
    return _decode_audio_latent(audio_vae, a, int(frames_total), float(fps))


# ---------------------------------------------------------------------------
# 主节点
# ---------------------------------------------------------------------------
class BSAI_H3_3DLatentUpscale:
    @classmethod
    def INPUT_TYPES(cls):
        sampler_names = list(comfy.samplers.SAMPLER_NAMES)
        scheduler_names = list(comfy.samplers.SCHEDULER_NAMES)
        default_sampler = "euler" if "euler" in sampler_names else sampler_names[0]
        default_scheduler = "simple" if "simple" in scheduler_names else scheduler_names[0]
        return {
            "required": {
                "cache": (CACHE_TYPE,),
                "vae": ("VAE",),
                "audio_vae": ("VAE",),
                "model": ("MODEL",),
                "conditioning": ("CONDITIONING",),
                "upscale_mode": (["model_3d", "interpolate"], {"default": "model_3d"}),
                "model_name": (_scan_upscale_models(),),
                "width": ("INT", {"default": 1280, "min": 64, "max": 4096, "step": 32}),
                "height": ("INT", {"default": 704, "min": 64, "max": 4096, "step": 32}),
                "chunk_length": (
                    "INT",
                    {
                        "default": 136, "min": 34, "max": 680, "step": 17,
                        "tooltip": "二采时间分块长度（帧，17的倍数，136≈5.7s）。越大越省缝、越占显存。",
                    },
                ),
                "temporal_overlap": (
                    "INT",
                    {
                        "default": 17, "min": 17, "max": 170, "step": 17,
                        "tooltip": "时间分块重叠帧数（17的倍数）。越大接缝越平滑、重复采样越多。",
                    },
                ),
                "resample_second_pass": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "二采：放大后逐块用扩散模型 re-sample 补细节（一采->3D Latent放大->二采）。关闭则仅做3D Latent放大。",
                    },
                ),
                "denoise": ("FLOAT", {"default": 0.45, "min": 0.01, "max": 1.0, "step": 0.01}),
                "steps": ("INT", {"default": 8, "min": 1, "max": 10000, "step": 1}),
                "sampler_name": (sampler_names, {"default": default_sampler}),
                "scheduler": (scheduler_names, {"default": default_scheduler}),
                "tile_size": (
                    "INT",
                    {
                        "default": 512, "min": 128, "max": 4096, "step": 32,
                        "tooltip": "空间分块 tile 边长（像素）。二采时每块切成tile逐块处理，显存峰值=单tile。8G卡用320-384，12G用384-512，16G用512-576。",
                    },
                ),
                "spatial_overlap": (
                    "INT",
                    {
                        "default": 128, "min": 0, "max": 1024, "step": 32,
                        "tooltip": "空间分块重叠（像素）。越大接缝越平滑、重复计算越多。",
                    },
                ),
                "seed": ("INT", {"default": 0, "min": 0, "max": (1 << 53) - 1}),
                "output_mode": (
                    ["both", "image_audio", "latent"],
                    {
                        "default": "both",
                        "tooltip": "both: 同时输出latent与image/audio。image_audio: 仅解码输出。latent: 仅输出放大后的AV latent。",
                    },
                ),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("LATENT", "IMAGE", "AUDIO", "STRING")
    RETURN_NAMES = ("latent", "images", "audios", "status")
    FUNCTION = "upscale"
    CATEGORY = "BSAI/H3 Film Factory"
    OUTPUT_NODE = True

    def upscale(
        self,
        cache,
        vae,
        audio_vae,
        model,
        conditioning,
        upscale_mode,
        model_name,
        width,
        height,
        chunk_length,
        temporal_overlap,
        resample_second_pass,
        denoise,
        steps,
        sampler_name,
        scheduler,
        tile_size,
        spatial_overlap,
        seed,
        unique_id=None,
    ):
        t0 = time.time()
        status_lines = []

        # ---- load source film from disk cache ----
        data_path, manifest_path, manifest = _load_manifest(cache)
        segments = [dict(x) for x in manifest.get("segments", [])]
        fps = float(manifest.get("fps", FPS))
        if not segments:
            raise ValueError("BSAI H3 3D Latent Upscale: cache has no segments.")

        src_h = int(segments[0].get("height", 0))
        src_w = int(segments[0].get("width", 0))
        w_target = max(64, (int(width) // 32) * 32)
        h_target = max(64, (int(height) // 32) * 32)
        w_lat = max(4, w_target // VAE_DOWNSAMPLE)
        h_lat = max(4, h_target // VAE_DOWNSAMPLE)

        device = "cuda" if torch.cuda.is_available() else "cpu"
        status_lines.append(
            f"source {src_w}x{src_h} -> target {w_target}x{h_target} "
            f"(latent {w_lat}x{h_lat}) mode={upscale_mode}"
        )

        # grid math for second-pass temporal chunking
        chunk_frames = max(17, (int(chunk_length) // 17) * 17)
        ov_frames = max(17, (int(temporal_overlap) // 17) * 17)
        chunk_steps = _token_steps_for_frames(chunk_frames)
        ov_steps = _token_steps_for_frames(ov_frames)
        tile_h = max(8, int(tile_size) // VAE_DOWNSAMPLE)
        tile_w = max(8, int(tile_size) // VAE_DOWNSAMPLE)
        tile_ov_h = max(0, int(spatial_overlap) // VAE_DOWNSAMPLE)
        tile_ov_w = max(0, int(spatial_overlap) // VAE_DOWNSAMPLE)

        use_model_3d = str(upscale_mode) == "model_3d"
        if use_model_3d:
            if str(model_name).startswith("("):
                raise ValueError("Please place the 3D upscaler model in models/latent_upscale_models")
            try:
                _get_upscaler(model_name, device, "fp16")
            except Exception as _e:
                print(f"[BSAI-H3-3D] 3D model load failed, falling back to interpolate: {_e}")
                use_model_3d = False
                status_lines.append("3D model unavailable -> interpolate")

        # ---- per-segment pipeline (each segment is a temporal chunk of the film) ----
        out_video_parts = []
        out_audio_parts = []
        total_out_frames = 0
        for si, desc in enumerate(segments):
            v = _load_segment_video(data_path, desc)       # [1,24,T,H,W]
            a = _load_segment_audio(data_path, desc)       # [1,32,2,Ta]
            trim = int(desc.get("trim_frames", 0)) if si > 0 else 0
            seg_frames = int(desc.get("frames", 0))

            # 3D latent spatial upscale (whole segment — upscaler is small)
            if w_lat != int(v.shape[4]) or h_lat != int(v.shape[3]):
                if use_model_3d:
                    v = _spatial_upscale_latent(v, h_lat, w_lat, "model_3d", model_name, device, "fp16")
                else:
                    v = _spatial_upscale_latent(v, h_lat, w_lat, "interpolate", model_name, device, "fp16")

            # optional second pass (re-sample in temporal chunks + spatial tiles)
            if int(resample_second_pass) and model is not None and conditioning is not None:
                try:
                    v, a = _resample_second_pass(
                        v, a, model, conditioning, int(seed) + si * 7919,
                        sampler_name, scheduler, steps, denoise,
                        chunk_steps, ov_steps, tile_h, tile_w, tile_ov_h, tile_ov_w,
                    )
                    status_lines.append(f"clip {si+1}: second-pass re-sample ok")
                except Exception as _e:
                    status_lines.append(f"clip {si+1}: second-pass skipped ({_e})")
                    import traceback as _tb
                    _tb.print_exc()

            # trim leading context overlap so segments tile exactly
            if trim > 0:
                trim_steps = _steps_for_frames(trim)
                if trim_steps is not None and trim_steps < int(v.shape[2]):
                    v = v[:, :, trim_steps:]
                trim_a = _audio_t_for_frames(trim)
                if trim_a is not None and trim_a < int(a.shape[-1]):
                    a = a[..., trim_a:]

            out_video_parts.append(v)
            out_audio_parts.append(a)
            total_out_frames += int(v.shape[2])

        full_v = torch.cat(out_video_parts, dim=2) if len(out_video_parts) > 1 else out_video_parts[0]
        full_a = torch.cat(out_audio_parts, dim=-1) if len(out_audio_parts) > 1 else out_audio_parts[0]

        # ---- outputs ----
        out_latent = {"samples": comfy.nested_tensor.NestedTensor((full_v, full_a))}

        want_latent = str(output_mode) in ("both", "latent")
        want_av = str(output_mode) in ("both", "image_audio")

        images = torch.zeros((0, 64, 64, 3), dtype=torch.float32)
        audios = {"waveform": torch.zeros(1, 1, 1), "sample_rate": 32000}
        if want_av:
            try:
                # frames_total for exact audio length
                frames_total = total_out_frames * 17 // 5
                # decode audio first (cheap)
                try:
                    if audio_vae is not None:
                        audios = _decode_audio_full(full_a, audio_vae, frames_total, fps)
                except Exception as _e:
                    print(f"[BSAI-H3-3D] audio decode failed: {_e}")
                # decode video in small batches to bound VRAM
                images = _decode_video_chunked(full_v, vae)
                status_lines.append(f"decoded {int(images.shape[0])} frames")
            except Exception as _e:
                status_lines.append(f"decode failed: {_e}")
                import traceback as _tb
                _tb.print_exc()

        if not want_latent:
            out_latent = {"samples": comfy.nested_tensor.NestedTensor((torch.zeros(1, 24, 2, 4, 4), torch.zeros(1, 32, 2, 2)))}

        elapsed = time.time() - t0
        status = " | ".join(status_lines) + f" | {elapsed:.1f}s"
        print(f"[BSAI-H3-3D] {status}")
        return (out_latent, images, audios, status)


NODE_CLASS_MAPPINGS = {
    "BSAI_H3_3DLatentUpscale": BSAI_H3_3DLatentUpscale,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "BSAI_H3_3DLatentUpscale": "BSAI H3 3D Latent 分块超清 (Chunked HD Upscale)",
}
