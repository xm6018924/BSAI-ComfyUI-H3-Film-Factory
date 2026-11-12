# BSAI-H3 分块二采（spatial tiling）模块
# 代码移植自 ComfyUI_MiniMaxH3_Director/director/spatial_tiled_sampling.py
# 原作者: Copyright 2026 ComfyUI-Bernini Contributors, Apache License 2.0 (见 Director LICENSE).
# 本文件按 Apache-2.0 第4节保留版权与许可声明, 仅做文件名/导入路径调整, 未改算法.
# 用途: 供 Film-Factory extender.py 的"分块二采"开关调用 wrap_sampler_spatial_tiles().

"""Optional spatial tiling for Director refine sampling.

Cuts the video latent along the long spatial axis, keeps audio whole, and
blends overlapping tile predictions inside each model call so the outer
sampler (Euler / res_multistep / …) still steps a single shared canvas.

Off by default. When disabled the caller never wraps the sampler, so the
path matches the previous full-frame sample.
"""

from __future__ import annotations

import inspect
import logging
import math
import time
from typing import Any, Callable

import torch
import torch.nn.functional as F

try:  # v14.377: 中断检查用; 单独导入本模块做单测时允许缺失
    import comfy.model_management as _mm_interrupt
except Exception:  # pragma: no cover
    _mm_interrupt = None

# v14.379 (2026-11-12): 进程级 TST 跳过开关的兜底查找（见 vendor/selflift_tst/h3_tst.py）。
# v14.377 只查 model_k._bsai_tst_state —— 实测拿不到: model_k 是 BaseModel 外层,
# state 挂在被 patch 的内层 MiniMaxH3Model 上, 于是 skip 从未置位, 二采仍在每个 tile
# 每层每个 attention 里白跑 eigvalsh (py-spy 栈顶 _spectral_tension, GPU 100%/96W)。
# 第二次实机(10:16)又被证明: 模块级开关也打不通 —— extender 用 importlib 按文件把
# h3_tst 载成 "bsai_selflift_tst", 且**不登记 sys.modules**, 宿主按模块名扫不到。
# 因此主通道改成 builtins 上的进程级计数器(与模块身份、对象层级全部无关), 模块
# push/pop 只作为附带的记账。
import builtins as _builtins
import sys as _sys

_TST_SKIP_KEY = "_BSAI_TST_TILE_SKIP"


def _find_tst_module():
    """在已加载的模块里找 h3_tst（可能按文件加载、名字也不带 h3_tst 后缀）。

    只认「文件是 h3_tst.py 或名字带 h3_tst」的模块: 全量按属性扫描会误中
    torch.ops 这类惰性命名空间(它对任意属性名都 hasattr 为真)。
    """
    for _name in ("h3_tst", "bsai_selflift_tst", "vendor.selflift_tst.h3_tst"):
        _m = _sys.modules.get(_name)
        if _m is not None and hasattr(_m, "push_tile_skip"):
            return _m
    for _name, _m in list(_sys.modules.items()):
        try:
            _f = getattr(_m, "__file__", "") or ""
        except Exception:
            _f = ""
        if not (_f.endswith("h3_tst.py") or "h3_tst" in str(_name).lower()):
            continue
        if callable(getattr(_m, "push_tile_skip", None)) and callable(
                getattr(_m, "pop_tile_skip", None)):
            return _m
    return None


def _find_tst_state(*objs):
    """沿 BaseModel -> cfg -> 内层扩散模型的链条找 TST state（哪一层挂都认）。"""
    for _o in objs:
        if _o is None:
            continue
        for _attr in ("_bsai_tst_state", "model", "inner_model"):
            try:
                _v = getattr(_o, _attr, None)
            except Exception:
                _v = None
            if _attr == "_bsai_tst_state":
                if isinstance(_v, dict):
                    return _v
            elif _v is not None and _v is not _o:
                _hit = _find_tst_state(_v)
                if _hit is not None:
                    return _hit
    return None

log = logging.getLogger("ComfyUI-MiniMaxH3-Director.director.spatial_tiles")

VAE_SPATIAL = 16
# Long-side pixel size at or below this skips tiling (same 16× latent grid as H3).
MAX_PIXELS_NO_TILE = 384
# H3 patchify 是 (1, 2, 2): latent 高宽必须是偶数, 否则 _pad_even_hw 会 replicate
# 复制末行补成偶数。块高对齐到该网格, 分块裁剪就是原始 latent 的干净切片。
PATCH_SPATIAL = 2


def clamp_n_tiles(raw: Any) -> int:
    try:
        n = int(raw if raw is not None else 2)
    except (TypeError, ValueError):
        n = 2
    return max(1, min(8, n))


def clamp_tile_overlap(raw: Any) -> int:
    try:
        n = int(raw if raw is not None else 128)
    except (TypeError, ValueError):
        n = 128
    return max(0, min(2048, n))


def compute_tile_starts(total: int, n_tiles: int, overlap: int) -> tuple[list[int], int]:
    if n_tiles <= 1:
        return [0], int(total)
    stride = int(round(total / n_tiles))
    tile_size = stride + 2 * overlap
    starts: list[int] = []
    for i in range(n_tiles):
        starts.append(max(0, i * stride - overlap))
    dedup: list[int] = []
    for start in starts:
        if not dedup or start > dedup[-1]:
            dedup.append(start)
    return dedup, tile_size


def _raised_cosine_1d(length: int, ov_left: int, ov_right: int, *, dtype, device) -> torch.Tensor:
    w = torch.ones(length, dtype=dtype, device=device)
    if ov_left > 0:
        n = min(ov_left, length // 2 + 1)
        if n > 0:
            t = torch.linspace(0, 1, n + 1, dtype=dtype, device=device)[:-1]
            fade = 0.5 - 0.5 * torch.cos(t * math.pi)
            w[:n] = torch.minimum(w[:n], fade)
    if ov_right > 0:
        n = min(ov_right, length // 2 + 1)
        if n > 0:
            t = torch.linspace(0, 1, n + 1, dtype=dtype, device=device)[:-1]
            fade = 0.5 - 0.5 * torch.cos((1.0 - t) * math.pi)
            w[-n:] = torch.minimum(w[-n:], fade)
    return w


def _overlap_latent(overlap_pixels: int) -> int:
    overlap_pixels = max(0, int(overlap_pixels))
    units = int(round(overlap_pixels / float(VAE_SPATIAL)))
    if overlap_pixels > 0 and units == 0:
        return 1
    return units


def _crop_spatial_5d(tensor: torch.Tensor, axis: str, start: int, end: int) -> torch.Tensor:
    if axis == "H":
        return tensor[:, :, :, start:end, :].contiguous()
    return tensor[:, :, :, :, start:end].contiguous()


def _pad_even_hw(video: torch.Tensor) -> tuple[torch.Tensor, int, int]:
    pad_h = (-int(video.shape[-2])) % 2
    pad_w = (-int(video.shape[-1])) % 2
    if pad_h or pad_w:
        video = F.pad(video, (0, pad_w, 0, pad_h, 0, 0), mode="replicate")
    return video, pad_h, pad_w


def _unpad_hw(video: torch.Tensor, pad_h: int, pad_w: int) -> torch.Tensor:
    if pad_h:
        video = video[:, :, :, : video.shape[-2] - pad_h, :]
    if pad_w:
        video = video[:, :, :, :, : video.shape[-1] - pad_w]
    return video


def _crop_packed(packed, full_shapes, axis: str, start: int, end: int):
    import comfy.utils

    if packed is None:
        return None, full_shapes, (0, 0)
    streams = list(comfy.utils.unpack_latents(packed, full_shapes))
    video = streams[0]
    if not isinstance(video, torch.Tensor) or video.ndim != 5:
        return packed, full_shapes, (0, 0)
    cropped = _crop_spatial_5d(video, axis, start, end)
    cropped, pad_h, pad_w = _pad_even_hw(cropped)
    streams[0] = cropped
    packed_out, tile_shapes = comfy.utils.pack_latents(streams)
    return packed_out, tile_shapes, (pad_h, pad_w)


def _crop_matching_video(tensor, full_h: int, full_w: int, axis: str, start: int, end: int):
    if not isinstance(tensor, torch.Tensor) or tensor.ndim != 5:
        return tensor
    if int(tensor.shape[-2]) != int(full_h) or int(tensor.shape[-1]) != int(full_w):
        return tensor
    cropped = _crop_spatial_5d(tensor, axis, start, end)
    cropped, _, _ = _pad_even_hw(cropped)
    return cropped


def _iter_payloads(cfg_guider):
    conds = getattr(cfg_guider, "conds", None) or {}
    for group in conds.values():
        if not group:
            continue
        for cond in group:
            if not isinstance(cond, dict):
                continue
            model_conds = cond.get("model_conds") or {}
            yield model_conds


def _rebuild_layout(payload: dict, latent_t: int, tile_h: int, tile_w: int, audio_t: int):
    from comfy.ldm.minimax.model import PackedLayout

    old = payload.get("layout")
    text_len = 0
    signature = getattr(old, "signature", None) if old is not None else None
    if signature:
        text_len = int(signature[0])
    elif old is not None and getattr(old, "segments", None):
        start, stop, kind = old.segments[0]
        if kind == "text":
            text_len = int(stop - start)
    kwargs: dict[str, Any] = {
        "keyframes": payload.get("keyframes"),
        "refs": payload.get("refs"),
    }
    try:
        params = inspect.signature(PackedLayout.__init__).parameters
        if "frame_count" in params or any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
        ):
            kwargs["frame_count"] = payload.get("frame_count")
    except (TypeError, ValueError):
        pass
    args = (text_len, int(latent_t), int(tile_h), int(tile_w), int(audio_t))
    try:
        return PackedLayout(*args, **kwargs)
    except TypeError:
        kwargs.pop("frame_count", None)
        return PackedLayout(*args, **kwargs)


def _install_tile_payloads(cfg_guider, *, axis: str, start: int, end: int, tile_shapes, full_h: int, full_w: int):
    restorations: list[tuple[Any, str, Any]] = []
    vs = tile_shapes[0]
    tile_h = (int(vs[3]) + 1) // 2 * 2
    tile_w = (int(vs[4]) + 1) // 2 * 2
    latent_t = int(vs[2])
    audio_t = int(tile_shapes[1][-1]) if len(tile_shapes) > 1 else 0

    for model_conds in _iter_payloads(cfg_guider):
        shape_cond = model_conds.get("latent_shapes")
        if shape_cond is not None and hasattr(shape_cond, "cond"):
            restorations.append((shape_cond, "cond", shape_cond.cond))
            shape_cond.cond = tile_shapes

        # denoise_mask 在 process_conds 时按全幅一次性编码进 cond (model_base extra_conds),
        # tile forward 必须同步裁剪, 否则 model.py out[0](tile W) * mask(full W) 维度不匹配。
        # audio_denoise_mask 不随空间分块裁剪(audio 流整段保留), 无需处理。
        mask_cond = model_conds.get("denoise_mask")
        mask_val = getattr(mask_cond, "cond", None) if mask_cond is not None else None
        if isinstance(mask_val, torch.Tensor) and mask_val.ndim == 5:
            restorations.append((mask_cond, "cond", mask_val))
            mask_cond.cond = _crop_matching_video(mask_val, full_h, full_w, axis, start, end)

        payload_cond = model_conds.get("minimax_payload")
        payload = getattr(payload_cond, "cond", None) if payload_cond is not None else None
        if not isinstance(payload, dict):
            continue
        restorations.append((payload_cond, "cond", payload))
        new_payload = dict(payload)
        keyframes = []
        for item in list(payload.get("keyframes") or []):
            copied = dict(item)
            kf_latent = item.get("latent")
            if isinstance(kf_latent, torch.Tensor) and kf_latent.ndim == 5:
                # v1.71: keyframes(motion context) latent 尺寸必须与目标 tile 对齐。
                # _crop_matching_video 尺寸不匹配时原样返回(1X context 60x34),
                # 但 _rebuild_layout 按 tile(2X) grid 算 keyframes 行数, latent 仍 1X 时
                # model.py:706 all_video_rows[~img_update] = cond_video_rows 行数不齐
                # (clip=1 实测 14544=24*606(2X grid) vs 11280=24*470(1X grid), 差 3264),
                # 二采整体回退一采结果。
                # v1.72: 空间语义修正 —— 先放大到全幅(与目标同尺寸), 再按 tile 裁剪,
                # 保证每个 tile 看到正确的空间区域(而非全幅压缩)。
                if (
                    int(kf_latent.shape[-2]) != int(full_h)
                    or int(kf_latent.shape[-1]) != int(full_w)
                ):
                    kf_latent = torch.nn.functional.interpolate(
                        kf_latent,
                        size=(int(kf_latent.shape[2]), int(full_h), int(full_w)),
                        mode="trilinear",
                        align_corners=False,
                    )
                kf_latent = _crop_matching_video(
                    kf_latent, full_h, full_w, axis, start, end
                )
                if (
                    int(kf_latent.shape[-2]) != int(tile_h)
                    or int(kf_latent.shape[-1]) != int(tile_w)
                ):
                    kf_latent = torch.nn.functional.interpolate(
                        kf_latent,
                        size=(int(kf_latent.shape[2]), int(tile_h), int(tile_w)),
                        mode="trilinear",
                        align_corners=False,
                    )
                copied["latent"] = kf_latent
            keyframes.append(copied)
        if keyframes:
            new_payload["keyframes"] = keyframes
        # v1.63: cond_video_latents 与 refs 同源(同尺寸), refs 段行数基于原始尺寸;
        # 若此处裁剪 cond_video_latents 而 refs 不裁剪, model.py:706 的
        # all_video_rows[~img_update] = cond_video_rows 会 shape mismatch(11280 vs 10860).
        # 修复: 保持全量, 分块只省 video 目标行. (cond_video 即 refs 的 patchify 输入)
        # v1.71: cond_video_latents 必须与裁剪/resize 后的 keyframes 对齐。
        # model.py _cond_video_rows 逐 latent patchify(按 latent 自身尺寸),
        # 与 PackedLayout 的 ~img_update 行数必须一致。顺序保持与
        # comfy/model_base.py extra_conds 拼接一致(keyframes latents + refs latents)。
        cvl_new = []
        for kf in new_payload.get("keyframes") or []:
            if kf.get("latent") is not None:
                cvl_new.append(kf["latent"])
        for r in payload.get("refs") or []:
            if "latent" in r:
                cvl_new.append(r["latent"])
        if cvl_new:
            new_payload["cond_video_latents"] = cvl_new
        new_payload["layout"] = _rebuild_layout(new_payload, latent_t, tile_h, tile_w, audio_t)
        payload_cond.cond = new_payload
    return restorations


def _restore_payloads(restorations: list[tuple[Any, str, Any]]) -> None:
    for obj, attr, value in restorations:
        setattr(obj, attr, value)


def _plan_regions(video_shape, n_tiles: int, overlap_pixels: int):
    _b, _c, _t, height, width = video_shape
    axis = "H" if int(height) >= int(width) else "W"
    axis_size = int(height if axis == "H" else width)
    max_latent = max(1, int(round(MAX_PIXELS_NO_TILE / float(VAE_SPATIAL))))
    if axis_size <= max_latent or n_tiles <= 1:
        return None
    overlap = _overlap_latent(overlap_pixels)
    starts, tile_size = compute_tile_starts(axis_size, n_tiles, overlap)
    if len(starts) <= 1:
        return None
    if tile_size >= axis_size * 0.9:
        log.warning(
            "spatial tiles: single tile %s is ~full axis %s (overlap %spx); little VRAM saved",
            tile_size,
            axis_size,
            overlap_pixels,
        )
    ranges = []
    for idx, ax_start in enumerate(starts):
        ax_end = min(ax_start + tile_size, axis_size)
        if idx == 0:
            ax_start = 0
        elif ax_start % PATCH_SPATIAL:
            # 起点前移 1 行(而非后移): 只多覆盖 1 行, 由重叠区吸收, 不会留缝。
            ax_start -= ax_start % PATCH_SPATIAL
        if idx == len(starts) - 1:
            ax_end = axis_size
        elif ax_end % PATCH_SPATIAL:
            ax_end = min(axis_size, ax_end + PATCH_SPATIAL - ax_end % PATCH_SPATIAL)
        ranges.append((ax_start, ax_end))
    regions = []
    for idx, (ax_start, ax_end) in enumerate(ranges):
        actual = ax_end - ax_start
        ov_left = 0
        ov_right = 0
        if idx > 0:
            prev_end = ranges[idx - 1][1]
            ov_left = min(actual, max(0, min(prev_end, ax_end) - ax_start))
        if idx < len(ranges) - 1:
            next_start = ranges[idx + 1][0]
            ov_right = min(actual, max(0, ax_end - max(ax_start, next_start)))
        regions.append((ax_start, ax_end, ov_left, ov_right))
    return {
        "axis": axis,
        "axis_size": axis_size,
        "tile_size": tile_size,
        "overlap_pixels": overlap_pixels,
        "overlap_latent": overlap,
        "n_tiles": len(starts),
        "regions": regions,
    }


def _invoke_model(model_k, x, sigma, denoise_mask, call_kw: dict):
    kwargs = {key: value for key, value in call_kw.items() if value is not None}
    # v1.96: 分块二采时模型按 DynamicVRAM staged 调度(大部分权重 offload),
    # tile forward 前强制同步, 消除异步 paging 搬运与 in-place modulation
    # (model.py _mod_scale_shift) 的竞态 —— 否则偶发 Fatal Python error: Aborted。
    if x.is_cuda and getattr(model_k, "_tiled_active", False):
        torch.cuda.synchronize()
    return type(model_k).__call__(model_k, x, sigma, denoise_mask, **kwargs)


def _tiled_model_call(
    model_k,
    x,
    sigma,
    *,
    denoise_mask=None,
    model_options=None,
    seed=None,
    n_tiles: int,
    overlap_pixels: int,
    **kwargs,
):
    import comfy.utils

    cfg = getattr(model_k, "inner_model", None)
    base = getattr(cfg, "inner_model", None) if cfg is not None else None
    full_shapes = getattr(base, "latent_shapes", None) if base is not None else None
    call_kw = dict(kwargs)
    if model_options is not None:
        call_kw["model_options"] = model_options
    if seed is not None:
        call_kw["seed"] = seed

    if not full_shapes or not isinstance(x, torch.Tensor):
        return _invoke_model(model_k, x, sigma, denoise_mask, call_kw)

    streams = list(comfy.utils.unpack_latents(x, full_shapes))
    _prev_tiled = getattr(model_k, "_tiled_active", False)
    model_k._tiled_active = True
    video = streams[0]
    if not isinstance(video, torch.Tensor) or video.ndim != 5:
        model_k._tiled_active = _prev_tiled
        return _invoke_model(model_k, x, sigma, denoise_mask, call_kw)

    plan = getattr(model_k, "_director_spatial_plan", None)
    if plan is None:
        plan = _plan_regions(tuple(video.shape), n_tiles, overlap_pixels)
        model_k._director_spatial_plan = plan
        if plan is None:
            log.info(
                "spatial tiling skipped (axis %dx%d, n_tiles=%s)",
                int(video.shape[-2]),
                int(video.shape[-1]),
                n_tiles,
            )
        else:
            log.info(
                "spatial tiles: axis=%s size=%s n=%s overlap=%spx/%s latent ranges=%s",
                plan["axis"],
                plan["axis_size"],
                plan["n_tiles"],
                plan["overlap_pixels"],
                plan["overlap_latent"],
                [(a, b) for a, b, *_ in plan["regions"]],
            )
    if plan is None:
        model_k._tiled_active = _prev_tiled
        return _invoke_model(model_k, x, sigma, denoise_mask, call_kw)

    axis = plan["axis"]
    full_h = int(video.shape[-2])
    full_w = int(video.shape[-1])
    device = video.device
    dtype = torch.float32
    video_acc = torch.zeros_like(video, dtype=dtype)
    weight_shape = (1, 1, 1, full_h if axis == "H" else 1, full_w if axis == "W" else 1)
    weights = torch.zeros(weight_shape, dtype=dtype, device=device)
    audio_acc = None
    saved_shapes = base.latent_shapes
    saved_latent_image = getattr(model_k, "latent_image", None)
    saved_noise = getattr(model_k, "noise", None)
    # v14.377 (2026-11-11): 分块二采期间暂停 SelfLift TST 注意力 override。
    # h3_tst.py 自己声明与 highres_tiling 不兼容、tile 调用应当跳过, 但它的长度
    # guard 是按「当前 forward 的输入 latent」推 frames/rows 的, tile forward 推出
    # 的正好是 tile 几何 → guard 放行 → 每块每层每个 attention 都白算一遍帧级
    # 谱分解。实机 py-spy(10s/1000 样本) 有 50% 主机时间落在此处, GPU 仅
    # ~100W/450W。
    # v14.379 (2026-11-12): v14.377 的 per-model 属性查找在实机上取不到 state
    # (model_k 是 BaseModel 外层), skip 从未置位 —— 二采 16 分钟零进展、栈顶仍在
    # _spectral_tension。改成双保险: ① 深链查找 state; ② h3_tst 模块级 push/pop
    # 开关(与对象层级无关, 一定生效)。tile 结束即复位, 一采/全帧二采不受影响。
    # v14.379 (2026-11-12): v14.377 的 per-model 属性查找在实机上取不到 state
    # (model_k 是 BaseModel 外层); 第二版只走 h3_tst 模块级开关, 实机(10:16)又被
    # 证明打不通 —— 该模块是 importlib 按文件载成 "bsai_selflift_tst" 且不进
    # sys.modules。第三版以 builtins 上的进程级计数器为主通道, 与模块身份/对象
    # 层级全无关; state 与模块 push/pop 都作为附带的第二、第三通道。
    _tst_state = _find_tst_state(model_k, cfg, base)
    _tst_module = _find_tst_module()
    _tst_prev_skip = None
    _tst_pushed = False
    _tst_flag_prev = int(getattr(_builtins, _TST_SKIP_KEY, 0))
    if _tst_state is not None:
        _tst_prev_skip = bool(_tst_state.get("skip_tiles"))
        _tst_state["skip_tiles"] = True
    if _tst_module is not None:
        try:
            _tst_module.push_tile_skip()
            _tst_pushed = True
        except Exception:
            _tst_pushed = False
    setattr(_builtins, _TST_SKIP_KEY, _tst_flag_prev + 1)
    log.info(
        "v14.380 分块二采: tile forward 内已暂停 SelfLift TST 注意力 override "
        "(builtins_flag=%s, module=%s, state=%s; TST 与 highres_tiling 不兼容, "
        "按模块自身声明跳过)",
        int(getattr(_builtins, _TST_SKIP_KEY, 0)),
        "found" if _tst_module is not None else "missing",
        "found" if _tst_state is not None else "missing",
    )

    try:
        for _ti, (ax_start, ax_end, ov_left, ov_right) in enumerate(plan["regions"]):
            # v14.377: 每块前检查中断。此前分块二采是一个不可打断的长循环 ——
            # 实机实测一轮二采 46 分钟日志零增长、ComfyUI /queue 已清空
            # (running=0) 却仍在算, 前端「取消」对它无效。补上后取消即可生效。
            if _mm_interrupt is not None:
                _mm_interrupt.throw_exception_if_processing_interrupted()

            tile_x, tile_shapes, (pad_h, pad_w) = _crop_packed(x, full_shapes, axis, ax_start, ax_end)
            tile_mask = None
            if denoise_mask is not None:
                tile_mask, _, _ = _crop_packed(denoise_mask, full_shapes, axis, ax_start, ax_end)
            if saved_latent_image is not None:
                model_k.latent_image, _, _ = _crop_packed(
                    saved_latent_image, full_shapes, axis, ax_start, ax_end
                )
            if saved_noise is not None:
                model_k.noise, _, _ = _crop_packed(saved_noise, full_shapes, axis, ax_start, ax_end)
            restorations = []
            try:
                restorations = _install_tile_payloads(
                    cfg,
                    axis=axis,
                    start=ax_start,
                    end=ax_end,
                    tile_shapes=tile_shapes,
                    full_h=full_h,
                    full_w=full_w,
                )
            except Exception as exc:
                _restore_payloads(restorations)
                base.latent_shapes = saved_shapes
                model_k.latent_image = saved_latent_image
                model_k.noise = saved_noise
                log.warning(
                    "spatial tile layout failed (%s); this step uses a full-frame forward",
                    exc,
                )
                return _invoke_model(model_k, x, sigma, denoise_mask, call_kw)
            base.latent_shapes = tile_shapes
            _t_tile = time.perf_counter()
            try:
                pred = _invoke_model(model_k, tile_x, sigma, tile_mask, call_kw)
            finally:
                _restore_payloads(restorations)
                base.latent_shapes = saved_shapes
                model_k.latent_image = saved_latent_image
                model_k.noise = saved_noise
            # v14.379: 每块耗时落日志 —— 二采此前 16~90 分钟"无动静"就是因为
            # 块内没有任何进度输出, 分不清是在算还是卡死。
            log.info(
                "v14.380 分块二采: tile %d/%d 用时 %.1fs",
                _ti + 1,
                len(plan["regions"]),
                time.perf_counter() - _t_tile,
            )

            pred_streams = list(comfy.utils.unpack_latents(pred, tile_shapes))
            pred_video = _unpad_hw(pred_streams[0], pad_h, pad_w).float()
            actual = ax_end - ax_start
            window = _raised_cosine_1d(
                actual, ov_left, ov_right, dtype=dtype, device=device
            )
            if axis == "H":
                win = window.view(1, 1, 1, -1, 1)
                video_acc[:, :, :, ax_start:ax_end, :] += pred_video * win
                weights[:, :, :, ax_start:ax_end, :] += win
            else:
                win = window.view(1, 1, 1, 1, -1)
                video_acc[:, :, :, :, ax_start:ax_end] += pred_video * win
                weights[:, :, :, :, ax_start:ax_end] += win
            # 音频 latent 没有空间维度: 每块都会预测同一段完整音频, 但预测随
            # 各块的视觉上下文不同而相位不同。求平均会把它们互相抵消成低频
            # 轰鸣/发闷(v14.199 实测), 所以只取第一块的音频预测作为整帧结果。
            if len(pred_streams) > 1 and audio_acc is None:
                audio_acc = pred_streams[1].float()
            del tile_x, pred, pred_streams, pred_video
            # v14.251 (2026-10-29): 提速 —— 移除块间 empty_cache。
            # 4 块串行时每块结束都 empty_cache 会强制同步 GPU + 整池回收,
            # 下一块 forward 重新 cudaMalloc + 冷池分配, 每块多付一次分配税。
            # 串行块峰值不叠加(池=历史峰值=单块峰值), 保留缓存池无 OOM 风险,
            # 改为整步(finally)后一次回收, 与采样器步间行为一致。
    finally:
        base.latent_shapes = saved_shapes
        model_k.latent_image = saved_latent_image
        model_k.noise = saved_noise
        model_k._tiled_active = _prev_tiled
        if _tst_state is not None and _tst_prev_skip is not None:
            _tst_state["skip_tiles"] = _tst_prev_skip
        if _tst_pushed and _tst_module is not None:
            try:
                _tst_module.pop_tile_skip()
            except Exception:
                pass
        setattr(_builtins, _TST_SKIP_KEY, _tst_flag_prev)
        if device.type == "cuda":
            torch.cuda.empty_cache()

    merged = [video_acc / weights.clamp(min=1e-8)]
    if audio_acc is not None and len(streams) > 1:
        merged.append(audio_acc.to(dtype=streams[1].dtype))
        merged[0] = merged[0].to(dtype=streams[0].dtype)
    else:
        merged[0] = merged[0].to(dtype=streams[0].dtype)
        if len(streams) > 1:
            merged.extend(streams[1:])
    packed, _ = comfy.utils.pack_latents(merged)
    return packed.to(dtype=x.dtype)


class _TiledModelProxy:
    """Instance ``__call__`` assignment is ignored by ``obj()``; proxy instead."""

    def __init__(self, inner, *, n_tiles: int, overlap_pixels: int):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_n_tiles", n_tiles)
        object.__setattr__(self, "_overlap_pixels", overlap_pixels)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_inner"), name)

    def __setattr__(self, name, value):
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            setattr(object.__getattribute__(self, "_inner"), name, value)

    def __call__(self, x, sigma, denoise_mask=None, model_options=None, seed=None, **call_kw):
        inner = object.__getattribute__(self, "_inner")
        return _tiled_model_call(
            inner,
            x,
            sigma,
            denoise_mask=denoise_mask,
            model_options=model_options,
            seed=seed,
            n_tiles=object.__getattribute__(self, "_n_tiles"),
            overlap_pixels=object.__getattribute__(self, "_overlap_pixels"),
            **call_kw,
        )


def wrap_sampler_spatial_tiles(
    sampler,
    *,
    n_tiles: int,
    overlap_pixels: int,
) -> Callable[[], None]:
    """Patch ``sampler.sampler_function`` so each model eval is spatially tiled.

    Returns a restore callback. No-op when n_tiles <= 1.
    """
    n_tiles = clamp_n_tiles(n_tiles)
    overlap_pixels = clamp_tile_overlap(overlap_pixels)
    if n_tiles <= 1 or sampler is None:
        return lambda: None
    orig_fn = getattr(sampler, "sampler_function", None)
    if orig_fn is None:
        return lambda: None

    def wrapped(model_k, noise, sigmas, extra_args=None, callback=None, disable=None, **kwargs):
        proxy = _TiledModelProxy(model_k, n_tiles=n_tiles, overlap_pixels=overlap_pixels)
        return orig_fn(
            proxy,
            noise,
            sigmas,
            extra_args=extra_args,
            callback=callback,
            disable=disable,
            **kwargs,
        )

    sampler.sampler_function = wrapped

    def restore() -> None:
        sampler.sampler_function = orig_fn

    return restore
