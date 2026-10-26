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
import contextlib
import secrets
import shutil
import subprocess
import tempfile
import time
import uuid
import zipfile
import numpy as np
import torch
import torchaudio
import types
import comfy.model_management
import comfy.nested_tensor
import comfy.ops
import comfy.quant_ops
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

# ==== BSAI 插件协同 SDK：加载即自动注册（失败不拖垮插件） ====
try:
    import sys as _bsai_sys, os as _bsai_os
    _BSAI_ORCH_DIR = _bsai_os.path.join(
        _bsai_os.path.dirname(_bsai_os.path.abspath(__file__)),
        "..", "BSAI-ComfyUI-Orchestrator")
    if _bsai_os.path.isdir(_BSAI_ORCH_DIR) and _BSAI_ORCH_DIR not in _bsai_sys.path:
        _bsai_sys.path.insert(0, _BSAI_ORCH_DIR)
    from bsai_orch_client import BSAIOrch  # noqa: E402
    BSAIOrch.register(
        name="BSAI-H3-Film-Factory",
        kind="sampling",
        hardware=["cuda"],
    )
except Exception as _bsai_e:  # 注册失败不得拖垮插件
    print(f"[BSAI SDK] BSAI-H3-Film-Factory 注册失败(忽略): {_bsai_e}")
# ==== BSAI SDK 块结束 ====

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
    _backup_chain_before_truncate,
    _decode_single_audio,
    _find_ffmpeg,
    _copy_blob_to_file,
    _despeckle_frames,
    _next_output_path,
    _comfy_media_item,
    _save_tail_latents,
    _restore_tail_latents,
    _save_tail_latents_to_disk,
    _load_tail_latents_from_disk,
    _delete_tail_latents_from_disk,
    _has_tail_latents_on_disk,
    _snapshot_chain,
    _snapshot_latest,
    _restore_latest_backup,
)
# v14.81: payload row-order guard. Wraps whatever MiniMaxH3.extra_conds
# currently owns the site (whichever third-party pack won it) and rebuilds
# cond_*_latents into PackedLayout's own order. Installed at import by the
# module itself; re-asserted below at execution time as a safety net.
# See the module docstring.
from .patch_h3_audio_row_order import (
    apply_patch as _apply_row_order_patch,
    is_applied as _row_order_patch_applied,
)

BUILD = "minimax-h3-extender-v14.209-refine-residency-patch"

# ── v14.79: 删除 v14.78 的 _patch_h3_audio_row_pad 死代码 ──
# 那段 "补零/截断 cond_audio_rows" 的 monkey-patch 从定义起就没有任何调用点,
# 从未生效过——所以 v14.78 报"已修复"的 shape mismatch 其实一次都没被拦住。
# 而且它本身是错的: 它照抄了一份过时的打包实现, 用 layout.img_pos/audio_pos
# 直接铺行, 既不填 text 段(那一段会留在 torch.empty 的未初始化内存里),
# 也不走 token_refiner, 宽度还取 max(video, audio) 再喂给 Linear。
# 真被调用的话不是修 crash, 而是静默出花屏 + NaN。
#
# 真正的成因在 payload 侧, 已就地根治 (无需在此兜底):
#   comfyui-h3-multishot/h3_avbank_probe.py  与
#   BSAI-ComfyUI-H3-Film-Factory/patch_motion_payload.py
# 两个 extra_conds 包装都只用 refs 重建 cond_audio_latents, 丢掉了
# PackedLayout 已经为 keyframe 音频预留的 cond_audio 段, 于是预留行数
# (1128) > 实到行数 (1054), 差 74 行 = 一段 37 步 motion-context 引导音频 x2。
# 两个包装都已改成 keyframe 音频 + ref 音频, 与 PackedLayout 的分段顺序一致。
#
# 不要再在这里加"补零"兜底: 行数不一致是上游语义错误, 补零只会把崩溃换成
# 静默错帧。正确的防线是让 cond_*_latents 与 layout 的预留严格同序同量。
FPS = 24
AUDIO_LATENT_FPS = 40

# v14.205: 多视图参考图纪律。ref2va 的多参生视频普遍输入 3/4 视图角色设定拼版，
# 模型会把拼版里其它视角的身体/手臂当成场景内容复制进画面（实测：主画面左侧
# 悬浮一条白袖手臂）。不裁剪参考图（多视图是通用用法），改为在 @图N 解析后
# 统一注入一次只取单一实体的约束，对单视图参考无副作用。
_REF_SHEET_RULE = (
    "【参考图纪律】<Picture N> 常为同一角色的多角度/多视图设定拼版：只采信其中一位角色的"
    "外形、发型与服装，全片同一角色只出现一次、只保留两条手臂；参考图中的其他视角、"
    "其他身体、半截肢体与局部特写仅供外形参考，绝不复制进画面。\n"
)


def _comfyui_temp_dir():
    """插件安装的 ComfyUI 根目录/temp——不依赖 folder_paths.get_temp_directory(),
    避免被其它插件 set_temp_directory() 改到系统 Temp(如 latentsync_*), 保证每台
    机器上预览/CLIP 临时文件都落在各自的 .\\ComfyUI\\temp。"""
    try:
        _root = Path(__file__).resolve().parents[2]
        _d = _root / "temp"
        _d.mkdir(parents=True, exist_ok=True)
        return _d
    except Exception:
        try:
            import folder_paths as _fp
            return _comfyui_temp_dir()
        except Exception:
            import tempfile as _tf
            return Path(_tf.gettempdir())


def _clip_output_dir():
    """v1.94: 正式 clip 成片(h3_clip_*.mp4)的持久目录——ComfyUI/output/bsai_clips/.
    ComfyUI 启动会清空 temp, 重启后 Premiere Pro 时间线上的 clip 路径全部失效
    (Video track V1 produced no output) 且无法挑选 clipN 复用. output 目录重启
    保留, 与链缓存 bsai_h3_chain_cache 同级持久化. 预览 _clippv_* 仍走 temp
    (v1.85 已支持从 manifest blob 重建)."""
    try:
        _root = Path(__file__).resolve().parents[2]
        _d = _root / "output" / "bsai_clips"
        _d.mkdir(parents=True, exist_ok=True)
        return _d
    except Exception:
        return _comfyui_temp_dir()


@contextlib.contextmanager
def _aimdo_disabled():
    """v1.78: H3 分块采样与 aimdo 内存图(malloc_graph)不兼容。
    4090 ComfyUI 0.35 跑后期 clip 二采时显存不足, malloc_graph_push 报
    'aimdo memory compile error' 断链。采样期间临时禁用 malloc_graph_begin/end,
    采样后恢复, 不影响其它节点/工作流。"""
    _mp = None
    try:
        import comfy.model_prefetch as _mp
        _ob, _oe = _mp.malloc_graph_begin, _mp.malloc_graph_end
        _mp.malloc_graph_begin = lambda device: None
        _mp.malloc_graph_end = lambda: None
    except Exception:
        _mp = None
    try:
        yield
    finally:
        if _mp is not None:
            try:
                _mp.malloc_graph_begin, _mp.malloc_graph_end = _ob, _oe
            except Exception:
                pass


def _release_dynamic_vram(tag=""):
    """v1.81 (2026-09-15 fix #11): 4090 DynamicVRAM 二采前 staged 池残留致 CUDA abort。

    现象: 4090 (ComfyUI 0.35 + DynamicVRAM 流式) 一采完成后, 模型权重仍留在
    prefetch/vbar staged 池 (21833MB Staged), ComfyUI 标准 unload_all_models()
    对 dynamic 模型返回 "0 models unloaded" 无效; 二采前 device_free 只剩
    ~1GB, 分块采样触发 21.8GB 重载 + workspace 分配 -> CUDA 驱动级
    "Fatal Python error: Aborted" (线程 dump 在 bsai_h3_spatial_tiles.py)。
    修复: 调用 comfy.model_prefetch.cleanup_prefetch_queues() (vbar_unpin
    释放 staged 权重) + cleanup_malloc_graph() + unload_all_models() +
    empty_cache, 让二采前显存回到 20GB+。对非 DynamicVRAM (5090) 为 no-op。
    """
    import torch as _t81
    try:
        import comfy.model_prefetch as _mp81
        for _fn81 in ("cleanup_prefetch_queues", "cleanup_malloc_graph"):
            _f81 = getattr(_mp81, _fn81, None)
            if _f81 is not None:
                try:
                    _f81()
                except Exception:
                    pass
    except Exception:
        pass
    try:
        import comfy.model_management as _mm81
        try:
            # v2.120b: unload_all_models() 会对注册中的 dynamic 量化 DiT 走 model_unload->
            # detach->unpatch_model->self.model.to(cpu), 量化块 GPU→CPU 拷贝触发 comfy_kitchen
            # _handle_to 原生 access violation(round3 崩溃链)。free_memory(..., for_dynamic=True)
            # 对动态模型设 memory_to_free=0 跳过, 只卸载非量化模型, 动态模型交 DynamicVRAM 调度。
            _mm81.free_memory(1e30, _mm81.get_torch_device(), for_dynamic=True)
        except Exception:
            pass
    except Exception:
        pass
    try:
        _t81.cuda.empty_cache()
        _t81.cuda.synchronize()
    except Exception:
        pass
    try:
        _f81, _t81b = _t81.cuda.mem_get_info()
        print(f"[H3 Extender] v1.81 显存释放[{tag}]: "
              f"free={_f81/1024**3:.2f}GB/{_t81b/1024**3:.2f}GB")
    except Exception:
        pass


def _release_text_encoder(clip, tag=""):
    """v14.214 (2026-10-26): 采样前强制释放文本编码器(TE)在 GPU 上的权重。

    实测根因(本机 RTX 4090 24GB / 一镜到底 19 段, 2026-10-26 13:32 那次):
      · 第 1 段采样前 free=22.27GB → DiT 20.6GB 走 DynamicVRAM 流式, 8 步跑通;
      · 第 2 段采样前 free 只剩 15.57GB —— TE(qwen3vl_32b_minimax_h3_nvfp4_awq,
        量化权重 14.6GB) 仍以 "loaded partially; 8905.26 MB loaded" 常驻显存,
        可用余量 15.6-4.0=11.6GB 装不下 DiT, 第一次 int8_linear 的 torch.empty
        权重块分配失败 → "CUDA error: out of memory"。

    为什么现有两条释放逻辑都漏了 TE:
      · extender.py 的 TE 释放块对带 comfy_kitchen 量化权重的模型直接 continue
        (_mp_has_ck_quant_weights) —— 实测 TE 正是 comfy_kitchen 量化
        (patcher=ModelPatcher / MiniMaxH3TEModel_, is_dynamic()=False);
      · _release_dynamic_vram() 的 free_memory(..., for_dynamic=True) 只能扫到
        ComfyUI current_loaded_models 里的模型, 而 v1.53 块早已把 clip.patcher
        从该表摘除, 下一段重新加载后并不保证能被扫到。

    这里按"身份"(clip.patcher)释放而不是扫注册表, 不依赖 ComfyUI 的卸载分支。
    实测(复现"部分加载"状态: 占用 12GB 后 TE 载入 8522MB):
      te.partially_unload(offload_device, 1e32) → 释放 8522MB, loaded_size 归零, 进程存活
      te.detach(True)                               → 释放 8522MB, loaded_size 归零, 进程存活
    下一段需要 TE 时 ComfyUI 会自动重新加载(CLIP.load_model → load_models_gpu),
    不影响文本编码, 代价约 6s。
    """
    try:
        import torch as _t214
    except Exception:
        return
    te = getattr(clip, "patcher", None)
    if te is None:
        return
    try:
        before = int(te.loaded_size())
    except Exception:
        before = 0
    if before <= 0:
        return
    try:
        te.partially_unload(te.offload_device, 1e32)
    except Exception:
        try:
            te.detach(True)
        except Exception as _te_err:
            print(f"[H3 Extender] v14.214 文本编码器释放失败(忽略, 不影响采样): {_te_err}")
    try:
        after = int(te.loaded_size())
    except Exception:
        after = 0
    try:
        import comfy.model_management as _cmm214
        for _lm in list(_cmm214.current_loaded_models):
            try:
                if getattr(_lm, "model", None) is te:
                    _cmm214.current_loaded_models.remove(_lm)
            except Exception:
                pass
    except Exception:
        pass
    try:
        import gc as _gc214
        _gc214.collect()
        _t214.cuda.synchronize()
        _t214.cuda.empty_cache()
        _t214.cuda.ipc_collect()
    except Exception:
        pass
    try:
        _f214, _tt214 = _t214.cuda.mem_get_info()
        print(f"[H3 Extender] v14.214 文本编码器显存释放[{tag}]: "
              f"TE {before / 1024 ** 2:.0f}MB -> {after / 1024 ** 2:.0f}MB, "
              f"GPU free={_f214 / 1024 ** 3:.2f}GB/{_tt214 / 1024 ** 3:.2f}GB")
    except Exception:
        pass


def _ff_unregister_model(model, label=""):
    """v14.175 (2026-10-23): 从 current_loaded_models 摘除指定模型的 LoadedModel。

    ComfyUI 没有公开 API 做这件事:
      - unload_model()     : 不存在 (silent AttributeError, 全局多处误用)
      - unload_model_and_clones(): 会连带 clone_base 一起卸, dynamic 量化 DiT
                                  会触发 unpatch -> .to(cpu) -> access violation
      - free_memory(..., for_dynamic=True): 对 dynamic 模型 memory_to_free=0,
                                  跳过不卸载

    所以手工从 current_loaded_models 里 pop LoadedModel + GC + soft_empty_cache,
    让后续 load_models_gpu 按新 reserve 预算重新登记。DynamicVRAM 的 staged 权重
    在 RAM, 卸载后 forward 会按需自动搬运, 不会丢失。

    返回: 摘除的 LoadedModel 数量 (int)
    """
    import gc as _gc_ur
    _removed = 0
    try:
        import comfy.model_management as _mm_ur
        _clm = getattr(_mm_ur, "current_loaded_models", None)
        if _clm is not None:
            for _i in range(len(_clm) - 1, -1, -1):
                if getattr(_clm[_i], "model", None) is model:
                    _clm.pop(_i)
                    _removed += 1
        _gc_ur.collect()
        try:
            _mm_ur.soft_empty_cache(force=True)
        except Exception:
            pass
    except Exception:
        pass
    if _removed > 0 or label:
        print(f"[H3 Extender] v14.175 _unregister{label}: 摘除 {_removed} 个 LoadedModel")
    return _removed


def _decode_single_clip_preview(owner, clip_index, vae, audio_vae, fps, ffmpeg=None, async_encode=False, lip_audio_segment=None):
    """Decode a single cached clip to MP4 and store as blob for frontend preview.
    v1.70: async_encode=True 时 encode 段在后台线程执行, 返回
    {"async": True, "done_event": threading.Event}.
    lip_audio_segment: 对口型模式下该 CLIP 对应的歌曲片段，会与模型环境音混音。"""
    return _decode_single_clip_to_blob(
        owner_id=owner,
        clip_index=clip_index,
        vae=vae,
        audio_vae=audio_vae,
        fps=fps,
        ffmpeg=ffmpeg,
        async_encode=async_encode,
        lip_audio_segment=lip_audio_segment,
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


def _read_frames_from_mp4(path, ffmpeg, total_frames, trim, width, height):
    """v1.67: 从已编码 MP4 blob 读帧(preview decode 产物), 返回 [T,H,W,C] float 0-1
    cpu tensor. 替代 _decode_clip_to_av 里重复的 VAE decode(2X 时每段省 ~30-60s).
    MP4 已按 trim 裁剪, 帧数以实际 raw 数据为准(编码器可能微调)."""
    import subprocess as _sp
    import numpy as _np
    n = max(0, int(total_frames) - int(trim))
    if n == 0:
        return None
    try:
        _p = _sp.run(
            [str(ffmpeg), "-y", "-i", str(path),
             "-f", "rawvideo", "-pix_fmt", "rgb24",
             "-s:v", f"{int(width)}x{int(height)}", "-"],
            stdout=_sp.PIPE, stderr=_sp.DEVNULL, timeout=600,
        )
    except Exception as _e:
        print(f"[H3 Extender] MP4 读帧失败: {_e}")
        return None
    raw = _p.stdout
    one = int(width) * int(height) * 3
    actual = len(raw) // one
    if actual == 0:
        return None
    arr = _np.frombuffer(raw[:actual * one], dtype=_np.uint8).reshape(
        actual, int(height), int(width), 3)
    return torch.from_numpy(arr.copy()).float().div_(255.0)


def _mp_has_ck_quant_weights(model):
    """检测 ModelPatcher 是否携带 comfy_kitchen 量化权重（QuantizedTensor 参数）。

    partially_unload(offload_device, 1e32) 会对 comfy_patched_weights 的模块执行
    m.to(cpu)，QuantizedTensor._handle_to 在该路径下原生 access violation 崩溃
    （Python try/except 无法捕获，直接杀进程）。此类模型必须跳过强制卸载循环，
    交由 DynamicVRAM 调度 / delegate 收尾 / unload_all_models()（detach 路径）卸载。
    """
    try:
        raw = getattr(model, "model", None)
        if raw is None:
            return False
        for _p in raw.parameters():
            if "comfy_kitchen" in (type(_p).__module__ or ""):
                return True
    except Exception:
        pass
    return False


def _mp_ck_offload_or_pop(_lm, _mm):
    """量化模型安全卸载(round3 同类路径封堵)。

    dynamic 量化模型(如 H3 量化 DiT): 走 ComfyUI 标准 partially_unload(1e32) 块级卸载,
    该路径对本模型多次实测安全(日志 'Unloaded partially: 14719.41 MB freed, 0.00 MB
    remains loaded'); 卸载后若仍有 GPU 驻留(loaded_size>1MB), 按身份从
    current_loaded_models 摘除, 避免后续任何 detach/unpatch_model 的
    self.model.to(cpu) 对量化块触发 comfy_kitchen _handle_to 原生崩溃。
    非 dynamic 量化模型(如二采 delegate 克隆, round1 崩溃对象): 不触碰
    partially_unload(其 m.to(cpu) 会原生崩溃), 直接摘除注册, 由 GC/empty_cache 回收。
    """
    try:
        _m = getattr(_lm, "model", None)
        if _m is None:
            return
        import torch as _t
        if _m.is_dynamic():
            try:
                _m.partially_unload(_m.offload_device, 1e32)
                try:
                    _t.cuda.synchronize()
                except Exception:
                    pass
            except Exception:
                pass
            try:
                if _m.loaded_size() > 1024 * 1024:
                    _mm.current_loaded_models.remove(_lm)
            except Exception:
                pass
        else:
            try:
                _mm.current_loaded_models.remove(_lm)
            except Exception:
                pass
    except Exception:
        pass


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

    # v1.25 + v14.153: free VRAM before decode - 终极清理:
    # 二采(时间分块/delegate驻留)后模型注册残留会导致加载 VideoVAE 时竞态闪退,
    # 这里摘除全部注册模型 + 标准卸载 + 双重清缓存, 给 VAE decode 干净显存。
    try:
        import comfy.model_management as _mm
        import torch as _torch
        # 1) 摘除全部注册模型(含二采 delegate 驻留的量化 DiT)
        _popped = 0
        for _lm in list(_mm.current_loaded_models):
            try:
                _mm.current_loaded_models.remove(_lm)
                _popped += 1
            except Exception:
                pass
        # 2) 标准卸载(对已摘除的为 no-op, 兜底仍有注册的)
        try:
            _mm.unload_all_models()
        except Exception:
            pass
        # 3) 双重清缓存 + 同步
        _mm.soft_empty_cache(force=True)
        _torch.cuda.synchronize()
        _torch.cuda.empty_cache()
        _torch.cuda.synchronize()
        _torch.cuda.empty_cache()
        _a = _torch.cuda.memory_allocated() / 1024 ** 3
        print(f"[H3 Extender]   decode VRAM prepared (popped={_popped}): allocated={_a:.2f}GB")
    except Exception as _e:
        print(f"[H3 Extender]   decode VRAM cleanup skipped: {_e}")

    # v1.67: 优先从 preview decode 已产出的 MP4 blob 读帧(预览画质), 省一次
    # 2X VAE decode(~30-60s/段). 音频仍走音频 VAE(秒级). blob 缺失/失败回退 VAE.
    _blob = curr.get("decoded_mp4_blob")
    if _blob is not None:
        try:
            _root = _ensure_cache_root()
            _tmp = _root / f"_avread_{uuid.uuid4().hex[:8]}.mp4"
            _copy_blob_to_file(data_path, _blob, _tmp)
            _imgs = _read_frames_from_mp4(
                str(_tmp), _find_ffmpeg(),
                int(curr.get("frames", 0)), int(curr.get("trim_frames", 0)) if i > 0 else 0,
                int(curr.get("width", 1920)), int(curr.get("height", 1080)),
            )
            try:
                _tmp.unlink()
            except Exception:
                pass
            if _imgs is not None and int(_imgs.shape[0]) > 0:
                images = _imgs
                audio = None
                try:
                    if audio_vae is not None:
                        audio = _decode_single_audio(data_path, curr, audio_vae, float(fps))
                        if audio is not None and int(curr.get("trim_frames", 0)) > 0:
                            sr = int(audio["sample_rate"])
                            trim_samples = int(round(float(int(curr.get("trim_frames", 0))) / float(fps) * sr))
                            wave = audio["waveform"]
                            if trim_samples > 0 and trim_samples < int(wave.shape[-1]):
                                audio = dict(audio)
                                audio["waveform"] = wave[..., trim_samples:]
                except Exception as _e:
                    print(f"[H3 Extender] _decode_clip_to_av audio decode failed clip={i}: {_e}")
                    audio = None
                print(f"[H3 Extender] _decode_clip_to_av: clip={i} 复用 MP4 blob ({images.shape[0]} 帧, 跳过 VAE decode)")
                return images, audio
        except Exception as _mp4err:
            print(f"[H3 Extender] _decode_clip_to_av MP4 读帧失败, 回退 VAE decode: {_mp4err}")

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
    # v14.190: 去彩点(色度去斑) —— VAE 解码在轮廓处逐通道截断产生的单像素饱和彩点
    try:
        _dp_parts = []
        for _s in range(0, int(images.shape[0]), 16):
            _dp_parts.append(_despeckle_frames(images[_s:_s + 16]))
        if _dp_parts:
            images = torch.cat(_dp_parts, dim=0).contiguous()
        del _dp_parts
    except Exception as _dp_err:
        print(f"[H3 Extender] 彩点修复跳过 clip={i}: {_dp_err}")

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


def _send_clip_av_output(node_id, clip_index, clip_count, images, audio, video_path=None, clip_name=None):
    """Lightweight per-clip readiness signal for the frontend. Includes
    video_path (temp MP4) so downstream nodes like BSAI Premiere Pro can
    auto-import the clip to their timeline without waiting for the full run."""
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
            "video_path": str(video_path) if video_path else None,
            "clip_name": str(clip_name) if clip_name else None,
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
        try:
            # v2.119: 尺寸统一兜底 — 若各 clip 帧尺寸不一致(如 1080 vs 1088,
            # 来源: 参考图分辨率污染 / 损坏缓存 / ffmpeg 异步编码异常写出畸形容器),
            # torch.cat 会直接报尺寸不匹配。检测到不一致时统一 resize 到最大
            # WxH 再拼接(保留完整预览); 尺寸一致时零开销走原路径。
            _sp = {(int(im.shape[1]), int(im.shape[2])) for im in imgs}
            if len(_sp) > 1:
                _max_h = max(int(im.shape[1]) for im in imgs)
                _max_w = max(int(im.shape[2]) for im in imgs)
                _norm = []
                for _im in imgs:
                    if int(_im.shape[1]) == _max_h and int(_im.shape[2]) == _max_w:
                        _norm.append(_im)
                    else:
                        _imf = _im.float().permute(0, 3, 1, 2).contiguous()
                        _imf = torch.nn.functional.interpolate(
                            _imf, size=(_max_h, _max_w), mode="bilinear", align_corners=False
                        )
                        _norm.append(_imf.permute(0, 2, 3, 1).contiguous())
                print(f"[H3 Extender] _concat_clip_av 尺寸统一: {sorted(_sp)} -> ({_max_h}, {_max_w})")
                imgs = _norm
            images = torch.cat(imgs, dim=0).float().cpu().contiguous()
        except Exception as _cat_err:
            # v2.118: 22 段 1080p 全分辨率 concat 会要 ~157GB 内存(OOM 崩节点)。
            # per-clip MP4 与 merged.mp4 早已落盘, 节点输出 tensor 仅用于 UI 预览,
            # concat 失败时降级为单帧占位, 不让整次渲染收尾崩掉。
            print(f"[H3 Extender] _concat_clip_av 大内存拼接跳过(MP4 已落盘): {_cat_err}")
            images = imgs[0][:1].float().cpu().contiguous()
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


def _split_lip_audio_by_clips(lip_audio, clips, fps=24.0, context_frames=0):
    """Split a full lip-sync audio into per-clip segments based on clip durations.

    Args:
        lip_audio: AUDIO dict {"waveform": [B,C,L], "sample_rate": int}
        clips: list of clip dicts, each with "duration" (seconds)
        fps: video frame rate (used to align clip durations to frame grid)
        context_frames: motion context 帧数 (context_length, 默认39)。
            ctx_on 段的头部被上一段尾部的 motion context 占用, 模型净输出 =
            标称时长 - context_frames/fps 秒。切分推进必须按净时长, 否则每个
            段间边界原曲被跳过 1.625s(39帧@24fps) → 歌曲听感"断了一截"。

    Returns:
        list of AUDIO dicts, one per clip. Length = len(clips).
        If lip_audio is None, returns [None] * len(clips).
    """
    if lip_audio is None:
        return [None] * len(clips)

    waveform = lip_audio["waveform"]
    sr = int(lip_audio["sample_rate"])
    total_samples = int(waveform.shape[-1])
    total_duration = float(total_samples) / float(sr)

    # Calculate per-clip durations aligned to H3 frame grid
    clip_durations = []
    for cfg in clips:
        dur = float(cfg.get("duration", 5.0))
        frames = _duration_to_frames(dur)
        clip_durations.append(float(frames) / fps)

    sum_clip_dur = sum(clip_durations)

    # If clip total > audio total, scale down proportionally
    if sum_clip_dur > total_duration + 0.01:
        scale = total_duration / sum_clip_dur
        clip_durations = [d * scale for d in clip_durations]
        print(f"[H3 LipSync] CLIP总时长({sum_clip_dur:.1f}s) > 音频总时长({total_duration:.1f}s)，按比例缩放到 {scale:.3f}x")

    # Split audio into segments
    # v2: For clips after the first, extend the segment backward by ~1s to cover
    # the motion context's audio overlap (carry-over from previous clip).
    # The H3 model's motion context carries ~22 video frames (~0.9s) from the
    # previous clip, which adds ~74 audio latent rows. Without this overlap,
    # cond_audio_rows is shorter than all_audio_rows[~audio_update] → shape mismatch.
    # v2.111 (fix): 重叠只对"开启上下文参考"的 CLIP 生效。用户关闭 context_enabled
    # 时模型不带 motion context，若仍切重叠会(1)渲染条件多 1.2s 音频、(2)输出混音
    # 把上一段尾部音乐带进本段 → clip2+ 与 lip_audio 原始音频错位。现在：
    #   - context_enabled=True  → 段头部含 overlap_samples 重叠(模型 latent 行需要)，
    #     同时把 overlap_samples 记进段 dict，解码混音时精确跳过 → 输出仍与原始对齐。
    #   - context_enabled=False → 纯净切分(零重叠)，输入/输出双侧都与原始音频对齐。
    # v14.178 曾把重叠改成 0 (2s 重叠在长链上累积回声)。但实测 3 段成片:
    # clip2 覆盖原曲 [13.55, 24.18], clip3 从 25.8 开始 —— 每个 ctx_on 边界
    # 原曲被跳过 1.625s(39 帧@24fps), 听感"音频断了一截"。
    # 根因: motion context 占用段头部 context_frames 帧(视频=上一段尾部,
    # 音频也必须是上一段尾部对应的原曲), 模型净输出 = 标称 - context。零重叠
    # 时输入/输出都缺这 1.625s → 段间缺口 + 尾对齐后新帧音频整体前移(口型错位)。
    # 现按 context_frames/fps 精确切重叠:
    #   段 = [current - overlap, current - overlap + N)  (N = 标称帧数)
    #   推进 = N - overlap = 模型净输出 → 段间零缺口, 口型与音频严格同源。
    _ctx_frames = 0
    try:
        _ctx_frames = max(0, int(context_frames))
    except (TypeError, ValueError):
        _ctx_frames = 0
    _ctx_ov_samples = int(round(_ctx_frames / float(fps) * sr)) if _ctx_frames else 0

    segments = []
    current_sample = 0
    for idx, dur in enumerate(clip_durations):
        nominal_samples = max(1, int(round(dur * sr)))

        _ctx_on = bool(clips[idx].get("context_enabled", True)) if idx < len(clips) else True
        _overlap = min(_ctx_ov_samples, max(0, nominal_samples - 1)) if (idx > 0 and _ctx_on) else 0
        _content_samples = max(1, nominal_samples - _overlap)

        seg_start = max(0, current_sample - _overlap)
        end_sample = min(current_sample + _content_samples, total_samples)
        actual_samples = end_sample - seg_start

        if actual_samples <= 0:
            silent = torch.zeros(waveform.shape[0], waveform.shape[1], nominal_samples,
                                 dtype=waveform.dtype, device=waveform.device)
            segments.append({"waveform": silent, "sample_rate": sr, "overlap_samples": 0})
        else:
            seg_wave = waveform[..., seg_start:end_sample].clone()
            if seg_wave.shape[-1] < nominal_samples:
                pad_len = nominal_samples - seg_wave.shape[-1]
                pad = torch.zeros(waveform.shape[0], waveform.shape[1], pad_len,
                                  dtype=waveform.dtype, device=waveform.device)
                seg_wave = torch.cat([seg_wave, pad], dim=-1)
            segments.append({"waveform": seg_wave, "sample_rate": sr, "overlap_samples": _overlap})

        current_sample = end_sample

    print(f"[H3 LipSync] 音频分割完成: {len(segments)} 段, 总时长 {total_duration:.2f}s / {total_samples} samples")
    for i, seg in enumerate(segments[:8]):
        if seg:
            d = int(seg["waveform"].shape[-1]) / float(sr)
            _ov_d = int(seg.get("overlap_samples", 0)) / float(sr)
            print(f"  clip[{i+1}]: {d:.2f}s ({int(seg['waveform'].shape[-1])} samples, 头部重叠 {_ov_d:.2f}s)")
    if len(segments) > 5:
        print(f"  ... 共 {len(segments)} 段")

    return segments


def _ff_fit_audio_duration(audio, target_sec, max_ratio=0.20):
    """v14.203: lip_voice 台词音频按视频总时长做 atempo 变速(不变调)。

    lip_voice(TTS 口播稿) 的时长由合成引擎决定, 与分镜总时长几乎不可能正好相等:
      - 比视频短 → _split_lip_audio_by_clips 按比例缩短每段, 每段尾部留静音,
        口型在线尾前就闭合;
      - 比视频长 → 单句台词被段边界截断, 或触发自动追加延续 CLIP。
    这里用 ffmpeg atempo 把整条语音压/拉到视频总时长, 再交给切分, 段边界永远
    落在整句台词之间。只对 lip_voice 生效(lip_audio 歌曲不做变速)。
    比例超出 ±max_ratio 时不做处理, 交给原有缩放/追加 CLIP 逻辑兜底。
    """
    try:
        wf = audio["waveform"]
        sr = int(audio["sample_rate"])
        dur = float(wf.shape[-1]) / float(sr)
        if dur <= 0 or target_sec <= 0:
            return None
        ratio = float(target_sec) / dur
        if abs(ratio - 1.0) <= 0.02:
            return None
        if abs(ratio - 1.0) > max_ratio:
            print(f"[H3 LipSync] lip_voice 时长 {dur:.2f}s 与视频 {target_sec:.2f}s 相差 "
                  f"{(ratio - 1.0) * 100:+.0f}%，超出 ±{max_ratio * 100:.0f}% 变速范围，按原速切分")
            return None
        ffmpeg = _find_ffmpeg()
        tempo = 1.0 / ratio
        with tempfile.TemporaryDirectory(prefix="bsai_lipvoice_fit_") as td:
            src = os.path.join(td, "in.wav")
            dst = os.path.join(td, "out.wav")
            torchaudio.save(src, wf[0].detach().cpu().float(), sr)
            subprocess.run(
                [ffmpeg, "-y", "-loglevel", "error", "-i", src,
                 "-filter:a", f"atempo={tempo:.5f}", dst],
                check=True, capture_output=True,
            )
            out, out_sr = torchaudio.load(dst)
        print(f"[H3 LipSync] ✅ lip_voice 时长自适应: {dur:.2f}s -> {target_sec:.2f}s "
              f"(atempo={tempo:.3f}, 变速不变调)")
        return {"waveform": out.unsqueeze(0), "sample_rate": int(out_sr)}
    except Exception as _fit_err:
        print(f"[H3 LipSync] lip_voice 时长自适应失败(按原速切分): {_fit_err}")
        return None


def _detect_speech_in_audio(audio, sr=32000, threshold_db=-35.0, min_duration=0.15):
    """Detect speech/singing segments in audio based on RMS energy.

    Returns list of (start_sec, end_sec) tuples where audio energy is above threshold.
    Used to determine which parts of a clip should have lip-sync and which shouldn't.
    """
    import numpy as np

    waveform = audio["waveform"]
    if waveform.dim() > 2:
        waveform = waveform[0]  # take first batch
    if waveform.shape[0] > 1:
        mono = waveform.mean(dim=0)
    else:
        mono = waveform[0]

    mono_np = mono.cpu().numpy().astype(np.float32)
    total_samples = len(mono_np)

    # Frame size for energy calculation (20ms windows)
    frame_len = max(1, int(sr * 0.02))
    hop_len = frame_len // 2

    # Compute RMS per frame
    num_frames = max(1, (total_samples - frame_len) // hop_len + 1)
    rms_values = np.zeros(num_frames, dtype=np.float32)
    for f in range(num_frames):
        start = f * hop_len
        end = min(start + frame_len, total_samples)
        frame = mono_np[start:end]
        rms_values[f] = np.sqrt(np.mean(frame ** 2) + 1e-10)

    # Convert to dB
    rms_db = 20.0 * np.log10(rms_values + 1e-10)

    threshold_linear = 10.0 ** (threshold_db / 20.0)
    mask = rms_values > threshold_linear

    # Find contiguous segments
    segments = []
    in_seg = False
    seg_start = 0
    min_frames = max(1, int(min_duration * sr / hop_len))

    for f in range(num_frames):
        if mask[f] and not in_seg:
            seg_start = f
            in_seg = True
        elif not mask[f] and in_seg:
            if f - seg_start >= min_frames:
                start_sec = seg_start * hop_len / float(sr)
                end_sec = f * hop_len / float(sr)
                segments.append((start_sec, end_sec))
            in_seg = False

    if in_seg:
        if num_frames - seg_start >= min_frames:
            start_sec = seg_start * hop_len / float(sr)
            end_sec = num_frames * hop_len / float(sr)
            segments.append((start_sec, end_sec))

    return segments


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


# ============================================================
# v1.40 (2026-09-13): 自动注入 MiniMax H3 省显存 patches
# v1.39 失败原因: 我试图复制 KJNodes 的 forward 逻辑, 但 cast_to_input /
# self.kj_num_chunks / quant_ops.ck 几个 API 签名/属性对不上, 抄错了.
#
# v1.40 改用: 直接 import KJNodes 已经验证过的 3 个 plain function
# (minimax_mlp_chunked_forward / minimax_attn_lowmem_forward /
# minimax_block_lowmem_forward), 然后用 KJNodes 自己的 MiniMaxChunkFeedForward
# + MiniMaxLowVRAMAttention 节点里完全相同的 add_object_patch 流程. 不
# 再自己抄代码, 复用 KJNodes 已经能跑通的实现.
#
# 24GB 物理卡跑 1.5x/2.0x 二采的硬性要求:
#   - FFN SwiGLU token 切 2 块 → peak FFN 显存减半
#   - attention 头切 4 块 → sol_attn workspace 缩 1/4 (6.46GB → ~1.6GB)
# ============================================================

# Lazy import KJNodes pure functions (避免 ComfyUI 启动时硬依赖)
def _ff_get_kj_forward_fns():
    """返回 KJNodes 已经验证过的 3 个 plain function. 失败时返回 None.

    v1.41: 之前用 from custom_nodes.ComfyUI_KJNodes 失败 — 插件文件夹名是
    ComfyUI-KJNodes (带连字符), Python module 名不允许连字符, 必须用
    importlib.util.spec_from_file_location 走文件直加载. 此函数只取
    minimax_mlp_chunked_forward / minimax_attn_lowmem_forward /
    minimax_block_lowmem_forward 三个 plain function, 它们的源码在
    ComfyUI-KJNodes/nodes/minimax_nodes.py 顶部 def 段, 不依赖 KJNodes
    自己的 nodes.py 顶层 (那里会拉 comfy_aimdo.vram_buffer 等可选依赖).
    """
    import importlib.util as _ilu
    import os as _os
    # 找 ComfyUI-KJNodes 目录
    try:
        import folder_paths as _fp
        _bases = list(_fp.get_folder_paths("custom_nodes")) + [_fp.base_path]
    except Exception:
        _bases = []
    kj_root = None
    for _b in _bases:
        _cand = _os.path.join(str(_b), "ComfyUI-KJNodes")
        if _os.path.isdir(_cand):
            kj_root = _cand
            break
    if kj_root is None:
        print("[H3 Extender] v1.41 KJNodes 目录未找到 (在 custom_nodes 下找不到 ComfyUI-KJNodes)")
        return None
    # 直加载 minimax_nodes.py
    fpath = _os.path.join(kj_root, "nodes", "minimax_nodes.py")
    if not _os.path.isfile(fpath):
        print(f"[H3 Extender] v1.41 找不到 {fpath}")
        return None
    spec = _ilu.spec_from_file_location("_kj_minimax_v141", fpath)
    if spec is None or spec.loader is None:
        print(f"[H3 Extender] v1.41 spec_from_file_location 失败")
        return None
    mod = _ilu.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as _ex:
        # minimax_nodes.py 顶部会 import comfy.model_management / comfy.ops /
        # comfy.quant_ops, 其中任一个缺都会 raise. 但 你的 ComfyUI venv 已
        # 经能加载这些 (Sol-H3 也 import), 所以这个 _ex 几乎不会发生.
        print(f"[H3 Extender] v1.41 exec_module 失败: {_ex}")
        return None
    if not all(hasattr(mod, n) for n in ("minimax_mlp_chunked_forward",
                                          "minimax_attn_lowmem_forward",
                                          "minimax_block_lowmem_forward")):
        print("[H3 Extender] v1.41 mod 缺 3 个函数")
        return None
    return (mod.minimax_mlp_chunked_forward,
            mod.minimax_attn_lowmem_forward,
            mod.minimax_block_lowmem_forward)


def _ff_apply_h3_lowvram_patches(model, ff_chunks=2, ff_seq_threshold=4096,
                                 attn_head_chunks=4, verbose=True):
    """v1.40: 在 Extender 内部为 H3 model 注入 KJNodes 已验证的省显存 patches.

    完整复刻 ComfyUI-KJNodes 的 MiniMaxChunkFeedForward.execute + MiniMaxLowVRAMAttention.execute
    流程 (mm.cast_to(weight, device) 2 个位置参数 + add_object_patch + transformer_options 写
    minimax_head_chunks + sol_take_forward). 不再自己抄 forward 内部, 完全交给 KJNodes 实现.
    """
    try:
        if model is None:
            return model
        # 1) 拿 KJNodes 纯函数
        kj = _ff_get_kj_forward_fns()
        if kj is None:
            print("[H3 Extender] v1.40 KJNodes 不可用, 跳过省显存 patches (会按老路径 OOM)")
            return model
        kj_mlp, kj_attn, kj_block = kj

        # 2) 幂等性: 已在 model_options 里有 minimax_head_chunks, 不重复套
        to = model.model_options.get("transformer_options", {}) or {}
        already_lowvram = to.get("minimax_head_chunks") is not None
        m = model if already_lowvram else model.clone()
        diffusion_model = m.get_model_object("diffusion_model")
        blocks = getattr(diffusion_model, "blocks", None)
        if not blocks or not hasattr(blocks[0], "attn") or not hasattr(blocks[0].attn, "qkv_proj"):
            print("[H3 Extender] v1.40 model 不是 MiniMax H3 (无 attn.qkv_proj), 跳过")
            return model

        # 3) FFN chunking — 复用 KJNodes 的 MiniMaxFFNChunkPatch + minimax_mlp_chunked_forward
        if ff_chunks > 1 and not already_lowvram and hasattr(blocks[0], "mlp"):
            for idx, block in enumerate(blocks):
                # 先设属性, 然后调 KJNodes minimax_mlp_chunked_forward
                # 它的逻辑是 self.kj_seq_threshold / self.kj_num_chunks
                block.mlp.kj_num_chunks = ff_chunks
                block.mlp.kj_seq_threshold = ff_seq_threshold
                m.add_object_patch(
                    f"diffusion_model.blocks.{idx}.mlp.forward",
                    types.MethodType(kj_mlp, block.mlp),
                )

        # 4) attention low-mem — 完全照搬 KJNodes MiniMaxLowVRAMAttention.execute
        if attn_head_chunks > 1:
            m.model_options.setdefault("transformer_options", {})
            m.model_options["transformer_options"]["minimax_head_chunks"] = attn_head_chunks
        # sol_take_forward 每次都设 (幂等)
        m.model_options["transformer_options"]["sol_take_forward"] = kj_attn

        for idx, block in enumerate(blocks):
            m.add_object_patch(
                f"diffusion_model.blocks.{idx}.forward",
                types.MethodType(kj_block, block),
            )
            attn_key = f"diffusion_model.blocks.{idx}.attn.forward"
            if attn_key in m.object_patches:
                # 已有其他 patch (如 Sol-Attn 走 _uses_optimized_attention 路径),
                # 保留它, 它会从 transformer_options 读 head_chunks
                continue
            m.add_object_patch(attn_key, types.MethodType(kj_attn, block.attn))

        if verbose:
            print(f"[H3 Extender] v1.40 注入 H3 低显存 patches (复用 KJNodes): "
                  f"ff_chunks={ff_chunks} attn_head_chunks={attn_head_chunks} "
                  f"blocks={len(blocks)} already_patched={already_lowvram}")
        return m
    except Exception as _pv_err:
        print(f"[H3 Extender] v1.40 注入失败(回退原 model, 24GB 卡会 OOM): {_pv_err}")
        import traceback
        traceback.print_exc()
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
# v1.25: 短边从 2048 降到 1024——2048 短边的大图单图产生 ~18000 visual tokens，
# 7 张 ref 总 token ~78000，TE 自注意力 causal_mask N×N 在 24GB 卡上直接 OOM。
# v1.29: 短边从 1024 降到 768——expandable_segments 生效后 TE 编码峰值从 23GB 降到 5.5GB，
# 但 TE 是 ModelPatcherDynamic（VBAR 虚拟地址空间），绕过 cudaMallocAsync 池，MLP down_proj
# 需要 1.19GB 连续块时 VBAR 无法提供导致 OOM（allocated 仅 5GB 但 free=0）。
# 768 短边 visual token 再减 ~45%（1024: ~46000 → 768: ~25000），MLP 激活内存同比下降，
# 角色参考图细节仍足够识别（ref 图仅用于特征提取，不影响输出分辨率 768×1344）。
REF_IMAGE_SHORT_EDGE = 768
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


def _asset_paths_signature(paths):
    """Content-ish signature of the @图N-resolved asset image paths.

    When asset-library images replace the internal refs, the refs are plain
    tensors: _normalize_ref_descriptor() drops them to None, so _refs_signature()
    is constant and the ref2va cache key never changes even after the user swaps
    the asset library for entirely different images. That made the cached VAE
    latents of the *old* assets keep being re-used. Path + mtime + size changes
    whenever the library is edited or same-named files are replaced, so the key
    invalidates and the new assets are encoded.
    """
    if not paths:
        return ""
    parts = []
    for p in paths[:MAX_IMAGE_REFS]:
        try:
            st = Path(p).stat()
            parts.append(f"{p}|{int(st.st_mtime)}|{int(st.st_size)}")
        except Exception:
            parts.append(str(p))
    raw = "|".join(parts).encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()[:16]


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


def _clip_asset_fp(paths):
    """v1.99: per-clip 资产指纹——依赖图路径 + 文件 mtime + size。
    路径或文件内容(替换同名图)变化 -> 指纹变 -> 仅该 clip 重渲。"""
    paths = list(paths or [])
    if not paths:
        return ""
    parts = []
    for _p in paths:
        try:
            _st = os.stat(_p)
            parts.append("{}|{}|{}".format(_p, int(_st.st_mtime), int(_st.st_size)))
        except Exception:
            parts.append(str(_p))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


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


def _ref2va_cache_key(vae, width, height, ref_image_size, refs, cache_bias=""):
    sig = _refs_signature(refs)
    vae_tag = vae.__class__.__name__ if vae is not None else "novae"
    try:
        vae_tag += ":" + str(getattr(vae, "model_name", "") or "")
    except Exception:
        pass
    # v1.26: 缓存key必须包含REF_IMAGE_SHORT_EDGE——此前key不含该常量，
    # 改短边从2048降到1024后key不变，仍命中旧缓存(2048短边)跳过resize，
    # 导致1024短边修复完全不生效，clip[1] TE编码继续OOM。
    # v1.27: cache_bias 携带 @图N 资产图片路径签名——资产库更换后 key 变化，
    # 否则张量 refs 的 _refs_signature 恒定，ref2va 命中旧资产 VAE 编码。
    raw = f"r2v|{sig}|{int(width)}x{int(height)}|{str(ref_image_size)}|se{REF_IMAGE_SHORT_EDGE}|{vae_tag}|b{cache_bias}".encode("utf-8")
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
    cache_bias="",
):
    """_prepare_shared_refs + disk cache for image-reference VAE latents."""
    if not enable_cache or not any(r is not None for r in refs or []):
        items, blocks, slots = _prepare_shared_refs(
            vae, audio_vae, width, height, ref_image_size, refs, ref_audio=ref_audio
        )
        return items, blocks, slots, False

    key = _ref2va_cache_key(vae, width, height, ref_image_size, refs, cache_bias=cache_bias)
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

_ARCHIVE_SECTION_RE = re.compile(r"^\s*\[[^\[\]\n]*档案[^\[\]\n]*\]", re.MULTILINE)


def _strip_singing_talk_descriptions(text):
    """lip_audio 模式: 不再删除唱歌/开口描述。
    音频已注入 AV latent 并锁定, 模型需要知道角色要跟随音频动嘴。
    此函数保留为空操作(兼容调用), 实际不删除任何描述。
    """
    return text


def _strip_archive_sections(text):
    """Remove [角色档案]/[道具档案]/[场景档案] sections (heading plus their
    item lines) from a global prompt. Those character/prop/scene inventories
    must never leak into a CLIP's render prompt — otherwise the model draws
    every listed character and scene in every card. Other sections (e.g.
    [整体风格]) are kept as pure text style, without any picture refs."""
    if not text:
        return ""
    lines = str(text).splitlines()
    out = []
    skipping = False
    for ln in lines:
        if _ARCHIVE_SECTION_RE.match(ln):
            skipping = True
            continue
        if skipping:
            # A new bracket section ends the skipped archive block. Plain item
            # lines (e.g. "凌薇@图1，...") stay inside the skipped block.
            if re.match(r"^\s*\[", ln):
                skipping = False
            else:
                continue
        out.append(ln)
    return "\n".join(out).strip()


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
    semantic_bridge_pack=None,
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
        import gc as _gc
        _gc.collect()
        import comfy.model_management as _cmm
        _cmm.cleanup_models_gc()
        # v2.121 (round4): TE 编码期间 ComfyUI 内部 free_memory 会扫描 current_loaded_models
        # 腾显存。若量化 DiT/delegate 仍在列表里(哪怕 loaded_size<1MB), 内部路径会走
        # detach->unpatch_model->to(cpu) 触发 comfy_kitchen _handle_to 原生 access violation。
        # 修复: 对所有带 ck 量化权重的模型, 一律直接从 current_loaded_models 摘除,
        # 不走 partially_unload(二采 delegate 与 DiT 共享权重, partially_unload 卸不干净),
        # 摘完 gc+empty_cache 让 GPU 权重物理回收。这样 ComfyUI 内部 free_memory 扫不到量化模型。
        for _lm in list(_cmm.current_loaded_models):
            try:
                if _lm.model is getattr(clip, "patcher", None):
                    continue
                if _mp_has_ck_quant_weights(_lm.model):
                    try:
                        _cmm.current_loaded_models.remove(_lm)
                    except Exception:
                        pass
                    continue
                _lm.model.partially_unload(_lm.model.offload_device, 1e32)
            except Exception:
                pass
        _gc.collect()
        _cmm.soft_empty_cache(force=True)
    except Exception:
        pass
    # v1.24: TE 计算临时切 bf16——ComfyUI sd1_clip forward 把 dtype hardcode 为 float32，
    # 导致 TE 编码峰值 ~22GB，在 24GB 卡（扣 reserve 后 ~22.3GB 可用）上贴边 OOM。
    # H3 主模型本身就是 bf16，TE 嵌入用 bf16 精度匹配且显存减半，编码后恢复原 forward。
    _te_bf16_patched = False
    _orig_tf_forward = None
    _tf_target = None
    try:
        _csm = getattr(clip, "cond_stage_model", None)
        _tf = getattr(_csm, "transformer", None) if _csm is not None else None
        if _tf is not None and hasattr(_tf, "forward"):
            _orig_tf_forward = _tf.forward
            _tf_target = _tf
            def _bf16_tf_forward(*args, **kwargs):
                kwargs["dtype"] = torch.bfloat16
                return _orig_tf_forward(*args, **kwargs)
            _tf.forward = _bf16_tf_forward
            _te_bf16_patched = True
    except Exception:
        _te_bf16_patched = False
    # v1.25: 编码前最后清一次 CUDA 缓存——clip[0] 渲染+解码后 cudaMallocAsync 池有碎片，
    # TE 编码需要大块连续内存（causal_mask N×N），碎片会导致 allocated 很低但 free=0 的伪 OOM。
    # v1.28: 加强为 reset_peak_memory_stats + 双轮 synchronize/empty_cache，配合启动脚本
    # PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True 根治 cudaMallocAsync 碎片。
    # v1.29: 加 ipc_collect() 清理 IPC 共享内存段；TE 是 ModelPatcherDynamic（VBAR），
    # 绕过 cudaMallocAsync 池，需尽可能清理所有可能占用虚拟地址空间的残留。
    try:
        import torch as _torch
        _torch.cuda.synchronize()
        _torch.cuda.empty_cache()
        _torch.cuda.ipc_collect()
        _torch.cuda.reset_peak_memory_stats()
        _torch.cuda.synchronize()
        _torch.cuda.empty_cache()
    except Exception:
        pass
    try:
        cond = clip.encode_from_tokens_scheduled(tokens)
    finally:
        if _te_bf16_patched and _tf_target is not None and _orig_tf_forward is not None:
            try:
                _tf_target.forward = _orig_tf_forward
            except Exception:
                pass
        # v1.27: TE编码完成后立即释放TE模型——参考MiniMaxH3 Director的vram_cleanup方案，
        # TE是普通ModelPatcher（非dynamic），unload_all_models+cleanup_models可真正释放TE权重显存，
        # 让H3主模型采样时独占GPU，避免TE驻留与H3加载竞争导致OOM。
        try:
            import gc as _gc2
            _gc2.collect()
            import comfy.model_management as _cmm2
            _cmm2.cleanup_models_gc()
            # v1.49: TE 是 ModelPatcherDynamic(VBAR), unload_all_models() 走 detach 分支
            # 不释放 VBAR 显存(同 :1386-1387 自证)。实测 TE 11.7GB 常驻不松, 导致 21.8GB
            # DiT 只能流式(89s/it)。改为对所有已加载模型(含 TE 自身, 不跳过 clip.patcher)
            # 走 partially_unload(offload_device, 1e32) VBAR 真释放路径, 再 unload_all + 空缓存。
            # 二采复用已编码 conditioning(不重 encode), 此处卸 TE 不影响二采/VAE/3D upscaler。
            for _lm2 in list(_cmm2.current_loaded_models):
                try:
                    if _mp_has_ck_quant_weights(_lm2.model):
                        continue
                    _lm2.model.partially_unload(_lm2.model.offload_device, 1e32)
                except Exception:
                    pass
            # v2.120b (round3): 崩溃链 extender.py:1938 -> unload_all_models()->
            # free_memory(1e30)->model_unload->detach->unpatch_model->self.model.to(cpu),
            # 对 GPU 驻留量化块触发 comfy_kitchen _handle_to 原生 access violation
            # (clip16→17 复现; 前 15 clip 未崩只因 DiT 恰好被 TE/VAE 加载挤成全 CPU)。
            # 改为 free_memory(..., for_dynamic=True): 动态模型(量化 DiT)memory_to_free=0
            # 跳过、不 detach, 非动态 TE/VAE 正常卸载, 量化权重不再走 GPU→CPU 拷贝。
            try:
                _cmm2.free_memory(1e30, _cmm2.get_torch_device(), for_dynamic=True)
            except Exception:
                pass
            _cmm2.cleanup_models()
            _cmm2.soft_empty_cache(force=True)
            import torch as _torch2
            _torch2.cuda.synchronize()
            _torch2.cuda.empty_cache()
            _torch2.cuda.ipc_collect()
        except Exception:
            pass
        # v1.53: ComfyUI 的 unload 只把权重移回 CPU RAM（current_loaded_models 保留引用，
        # 物理内存不释放）。TE 15GB + DiT 21.8GB + VAE 驻留会把系统物理内存顶满，
        # cudaHostRegister 锁页注册失败 → "Pin error." 刷屏 + offload 换页拖慢。
        # 配合 bat --cache-none（禁用节点结果缓存，消除 CLIPLoader 输出对 clip 的跨轮持有），
        # 此处把 TE 从 current_loaded_models 摘除，函数返回后 clip 引用归零，gc 真正释放 ~15GB RAM。
        try:
            import gc as _gc53
            import comfy.model_management as _cmm53
            _te_patcher53 = getattr(clip, "patcher", None)
            for _lm53 in list(_cmm53.current_loaded_models):
                try:
                    if _lm53.model is _te_patcher53:
                        _cmm53.current_loaded_models.remove(_lm53)
                except Exception:
                    pass
            _gc53.collect()
        except Exception:
            pass
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
    # v2.19 Semantic-Bridge: 可开可关(默认关). 对 cond[0][0] token 张量做小 MLP 残差混合.
    if isinstance(semantic_bridge_pack, dict) and semantic_bridge_pack.get("enabled"):
        try:
            import os as _os_sb, importlib.util as _ilu_sb
            _sb_path = _os_sb.path.join(_os_sb.path.dirname(_os_sb.path.abspath(__file__)),
                                        "bsai_h3_semantic_bridge.py")
            _sb_spec = _ilu_sb.spec_from_file_location("bsai_h3_semantic_bridge", _sb_path)
            _sb = _ilu_sb.module_from_spec(_sb_spec)
            _sb_spec.loader.exec_module(_sb)
            cond, _sb_note = _sb.apply(
                cond,
                semantic_bridge_pack.get("adapter", ""),
                float(semantic_bridge_pack.get("alpha", 0.15)),
                bool(semantic_bridge_pack.get("magnitude_match", True)),
            )
            if _sb_note:
                print(f"[H3 Extender]   {_sb_note}")
        except Exception as _sb_err:
            print(f"[H3 Extender]   Semantic Bridge 加载失败(忽略, 按无桥继续): {_sb_err}")
    return cond, latent


class _BasicGuider(comfy.samplers.CFGGuider):
    def set_conds(self, positive):
        self.inner_set_conds({"positive": positive})

    # v1.52: 不再覆写 outer_sample. force_full_load=True 把 21.8GB 全拉满会在
    # process_conds 阶段 OOM (23.86GB 物理上限). 改由 EXTRA_RESERVED_VRAM 抬到 ~5.5GB,
    # 让 ComfyUI 自动把权重驻留预算压到 ~16GB, 尾部 ~5.8GB offload, 留 ~6GB 给 conds/workspace.


# ============================================================
# P0 (2026-10-17): 官方双轨迹采样 —— MiniMaxH3SigmaShift 等效注入
#   video shift 驱动采样器 sigma 调度 (ModelSamplingAV + CONST),
#   audio schedule 由模型 forward 内部从共享 base grid 推导.
#   与 comfy_extras.nodes_minimax_h3.MiniMaxH3SigmaShift 实现一致, 幂等.
# ============================================================
def _apply_h3_dual_track_shift(model, shift_video, shift_audio):
    if model is None:
        return model
    try:
        # v14.152: shift_audio 可为 None（老工作流 0.0 的映射）→ 关闭音频 shift
        _sa = None if shift_audio is None else float(shift_audio)
        to = model.model_options.get("transformer_options", {}) or {}
        if (to.get("minimax_h3_sigma_shift_video") == float(shift_video)
                and to.get("minimax_h3_sigma_shift_audio") == _sa
                and model.model_options.get("_bsai_dual_track_applied")):
            return model  # 幂等: 已注入同值 shift
        import comfy.model_sampling as _cms
        m = model.clone()
        class _MSAV(_cms.ModelSamplingAV, _cms.CONST):
            pass
        original = m.get_model_object("model_sampling")
        ms = _MSAV(m.model.model_config)
        ms.set_parameters(shift=float(shift_video), audio_shift=_sa)
        if hasattr(original, "noise_scale"):
            try:
                ms.set_noise_scale(original.noise_scale)
            except Exception:
                pass
        m.add_object_patch("model_sampling", ms)
        to2 = m.model_options.get("transformer_options", {}).copy()
        to2["minimax_h3_sigma_shift_video"] = float(shift_video)
        to2["minimax_h3_sigma_shift_audio"] = _sa
        m.model_options["transformer_options"] = to2
        m.model_options["_bsai_dual_track_applied"] = True
        print(f"[H3 Extender] P0 双轨迹采样注入: shift_video={shift_video} shift_audio={_sa}", flush=True)
        return m
    except Exception as _e:
        print(f"[H3 Extender] P0 双轨迹注入失败(回退原模型): {_e}", flush=True)
        return model


# ============================================================
# P2 (2026-10-17): SelfLift H3 TST 时间状态传输 —— 少步数画质补偿
#   arXiv:2609.08505, 校正 H3 视频时间不平衡(闪烁/身份漂移/不合理运动).
#   依赖 comfyui-SelfLift (facok) 已安装; 未安装自动跳过.
# ============================================================
def _apply_h3_tst(model, enable, tau):
    if model is None or not enable:
        return model
    try:
        import sys as _sys_tst, os as _os_tst, importlib.util as _ilu_tst
        _tst_patch = None
        _src_tag = None
        # v14.163 (2026-10-22): TST 内置化 —— 优先从插件自带 vendor/selflift_tst/h3_tst.py
        # 加载 (importlib 按文件加载, 不污染 sys.path), 粉丝无需再单独安装 comfyui-SelfLift。
        _builtin_tst = _os_tst.path.join(
            _os_tst.path.dirname(_os_tst.path.abspath(__file__)),
            "vendor", "selflift_tst", "h3_tst.py",
        )
        if _os_tst.path.isfile(_builtin_tst):
            try:
                _spec_tst = _ilu_tst.spec_from_file_location("bsai_selflift_tst", _builtin_tst)
                _mod_tst = _ilu_tst.module_from_spec(_spec_tst)
                _spec_tst.loader.exec_module(_mod_tst)
                _tst_patch = getattr(_mod_tst, "patch_model", None)
                _src_tag = "内置 vendor/selflift_tst"
            except Exception as _be:
                print(f"[H3 Extender] 内置 TST 加载失败(回退外部): {_be}", flush=True)
        # 回退: 外部 comfyui-SelfLift（双保险保留，兼容老用户既有安装）
        if _tst_patch is None:
            _sl_dir = _os_tst.path.join(
                _os_tst.path.dirname(_os_tst.path.dirname(_os_tst.path.abspath(__file__))),
                "comfyui-SelfLift",
            )
            if not _os_tst.path.isfile(_os_tst.path.join(_sl_dir, "h3_tst.py")):
                try:
                    _cn_roots = folder_paths.get_folder_paths("custom_nodes")
                    _sl_dir = _os_tst.path.join(_cn_roots[0], "comfyui-SelfLift")
                except Exception:
                    pass
            if _os_tst.path.isfile(_os_tst.path.join(_sl_dir, "h3_tst.py")):
                if _sl_dir not in _sys_tst.path:
                    _sys_tst.path.insert(0, _sl_dir)
                from h3_tst import patch_model as _tst_patch_ext
                _tst_patch = _tst_patch_ext
                _src_tag = "外部 comfyui-SelfLift"
            else:
                print(f"[H3 Extender] P2 TST 注入跳过: 内置 vendor 与外部 comfyui-SelfLift "
                      f"均未找到 h3_tst.py (内置 {_builtin_tst} / 外部 {_sl_dir})", flush=True)
                return model
        m = model.clone()
        patched = _tst_patch(m, float(tau), False)
        print(f"[H3 Extender] P2 SelfLift H3 TST 注入({_src_tag}): tau={tau}", flush=True)
        return patched
    except Exception as _e:
        print(f"[H3 Extender] P2 TST 注入失败(继续无补偿): {_e}", flush=True)
        return model


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


# ============================================================
# v1.31: Sol-H3 Self-Lift 双采技术集成（一采 + 二采直出高清）
# 移植自 BSAI-ComfyUI-Sol-H3 的 LatentUpscaleAlign 核心语义:
#   latent 直接放大(不经过VAE) + 像素对齐(H3官方32px) + CONST 重加噪
#   + 音频锁定(默认) + DisableNoise 二采完整去噪
# ============================================================
_FF_UPSCALER_MOD = None
# v14.157: 3D 语义放大回退记录 —— 过去只打一行控制台日志就静默降为
# bilinear 插值, 用户完全看不到。这里记录状态, 由调用处推到前端状态栏。
_FF_UPSCALER_FELL_BACK = {"hit": False, "reason": "", "clip": -1}
try:
    import sys as _sys, os as _os
    _ff_up_dir = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                               "Comfyui_Minimax_h3_latent_Upscaler", "nodes")
    if _os.path.isdir(_ff_up_dir) and _ff_up_dir not in _sys.path:
        _sys.path.insert(0, _ff_up_dir)
    import minimax_h3_latent_upscaler_3d as _FF_UPSCALER_MOD
    try:
        _fp = folder_paths
        _ff_up_models = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                                      "Comfyui_Minimax_h3_latent_Upscaler", "models", "h3_latent_upscalers")
        if _os.path.isdir(_ff_up_models):
            _fp.add_model_folder_path("h3_latent_upscalers", _ff_up_models)
    except Exception:
        pass
except Exception:
    _FF_UPSCALER_MOD = None


def _ff_get_upscaler_models():
    """获取可用的 3D latent upscaler 模型列表; 不可用时返回仅插值选项。"""
    opts = ["(bilinear interpolation, no model)", "(bilinear插值, 无需模型)"]
    if _FF_UPSCALER_MOD is not None:
        try:
            names = _FF_UPSCALER_MOD.scan_models()
            opts.extend(sorted(n for n in names if not n.startswith("(")))
        except Exception:
            pass
    return opts


def _ff_is_nested(samples):
    return isinstance(samples, comfy.nested_tensor.NestedTensor)


def _ff_extract_members(samples):
    """NestedTensor -> members 列表; 普通 tensor 原样返回。"""
    if _ff_is_nested(samples):
        return list(samples.unbind()), True
    return [samples], False


def _ff_wrap_members(members, was_nested):
    if was_nested:
        return comfy.nested_tensor.NestedTensor(members)
    return members[0]


def _ff_auto_refine_tile_count(samples, requested, overlap_px, max_tiles=8):
    """v14.179 (2026-10-23): 二采分块粒度自适应 —— 不再盲目扩块到 Sol-Attn 健康区。

    实测修正(实机 5090 24GB):
      - v14.149 固定 4 块(每块 ~334k 灰色区) = 399s/步;
      - v14.164 扩到 8 块(每块 <=270k 健康区) = 545s/步 —— 块间 overlap 重复计算
        翻倍, 且 tile 实际走 KJNodes head 分组(实测 0.26~0.55s/k tokens), 并非
        注释假设的 Sol-Attn 0.7s/块, 扩块反而更慢。
    → 结论: 每块 <=450k(病态边缘) 一律尊重请求值(分块越少 forward/搬运/重叠越少);
      每块 > 450k 才提升到每块 <=450k 的最少块数, 绕开 440k+ 病态 kernel。
    """
    try:
        _mm164, _ = _ff_extract_members(samples)
        if _mm164 is None or getattr(_mm164[0], "ndim", 0) < 5:
            return int(requested)
        _b164, _c164, _t164, _h164, _w164 = (int(x) for x in _mm164[0].shape)
        _axis = max(_h164, _w164)
        _minhw = min(_h164, _w164)
        if _axis <= 1 or _minhw <= 1 or _t164 <= 1:
            return int(requested)
        # v14.181: 恢复 overlap 128px 估算(回滚 v14.179 的 64px 钳制)。
        # 64px 接缝仅靠 motion-context keyframe 兜底(一镜到底模式), 分镜模式
        # 无兜底会画面崩坏; 128px 是分镜模式接缝融合的安全值。
        overlap_px = min(int(overlap_px), 128)
        # VAE_SPATIAL=16: overlap_px 转 latent 格(128px -> 8 latent)
        _ov = max(1, int(overlap_px) // 16)
        # 每块 token ≈ T * minHW * (axis/n + 2*ov)
        _target = 450000
        _req = max(1, int(requested))
        if _req > 1:
            _per_req = _t164 * _minhw * (_axis // _req + 2 * _ov)
        else:
            _per_req = _t164 * _minhw * _axis
        # 请求值每块未达病态边缘 -> 尊重请求(分块越少 forward/搬运/重叠越少)
        if _per_req <= _target:
            print(f"[H3 Extender] v14.179 分块粒度: 请求 n_tiles={requested} -> {_req} "
                  f"(每块约 {_per_req:,} tokens <= 450k 安全区, 尊重请求不扩块)")
            return _req
        # 请求值落在病态区 -> 提升到每块 <= 450k 的最少块数
        _den = _target / (_t164 * _minhw) - 2 * _ov
        if _den <= 0:
            return max_tiles
        _n = int(_axis / _den) + 1
        _n = max(_req + 1, min(max_tiles, _n))
        _per = _t164 * _minhw * (_axis // _n + 2 * _ov)
        print(f"[H3 Extender] v14.179 分块粒度: 请求 n_tiles={requested} -> {_n} "
              f"(每块约 {_per:,} tokens <= 450k 安全区, 绕开病态 kernel)")
        return _n
    except Exception:
        return int(requested)


def _ff_snap_to_multiple(n, m):
    m = max(1, int(m))
    return max(m, (int(n) // m) * m)


def _ff_upscale_video_latent(video, scale, align_to_px, method, upscaler_model=""):
    """v1.31: 视频 latent [B,C,T,H,W] 空间放大 + 像素对齐(不经过 VAE, 无编解码损失)。

    H3 空间下采样率 16(1920->120 latent); 放大后先按 align_to_px(默认32px) 对齐
    再换算回 latent 尺寸, 避免官方节点不取整导致的分辨率偏移与边缘色条。
    音频 latent 保持不动(只放大视频成员)。

    upscaler_model: 选中 3D latent upscaler 文件名时用神经网络语义放大, 否则 bilinear 插值。
    """
    import comfy.utils
    if video.ndim < 4:
        raise ValueError(f"视频latent至少需要4维 [B,C,H,W], 实际 {tuple(video.shape)}")

    h_lat, w_lat = video.shape[-2], video.shape[-1]
    latent_mult = max(1, int(align_to_px) // 16)  # 像素32 -> latent步进2(H3下采样16)
    new_h = _ff_snap_to_multiple(round(h_lat * scale), latent_mult)
    new_w = _ff_snap_to_multiple(round(w_lat * scale), latent_mult)
    if new_h == h_lat and new_w == w_lat:
        return video

    orig_dtype = video.dtype
    use_model = (upscaler_model and _FF_UPSCALER_MOD is not None
                 and not upscaler_model.startswith("("))
    if use_model:
        try:
            dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            model_dtype = torch.bfloat16
            s = video.to(device=dev, dtype=model_dtype, copy=True)
            if s.ndim == 4:
                s = s.unsqueeze(2)
            T = s.shape[2]
            model = _FF_UPSCALER_MOD.load_model(upscaler_model, dev, "bf16")
            norm_mean, norm_std = _FF_UPSCALER_MOD._make_norm_tensors(dev, model_dtype)
            with torch.inference_mode():
                s.sub_(norm_mean).div_(norm_std)
                out = model(s, scale=float(scale), target_size=(T, new_h, new_w))
                del s
                out.mul_(norm_std).add_(norm_mean)
            out = out.to(device="cpu", dtype=orig_dtype)
            if dev.type == "cuda":
                torch.cuda.empty_cache()
            print(f"[H3 Extender] Refine 3D upscaler: {tuple(video.shape)} -> {tuple(out.shape)} "
                  f"model={upscaler_model}")
            return out
        except Exception as e:
            print(f"[H3 Extender] Refine 3D upscaler 失败({e}), fallback bilinear")
            # v14.157: 记录回退原因, 调用处会推送前端显式警告
            _FF_UPSCALER_FELL_BACK["hit"] = True
            _FF_UPSCALER_FELL_BACK["reason"] = str(e)[:180]

    # fp16/bf16 插值会量化新网格, 二采出现斑点; 统一 fp32 放大后转回原精度
    samples = video.float() if video.dtype in (torch.float16, torch.bfloat16) else video
    _method = "nearest-exact" if str(method) == "nearest" else str(method)
    out = comfy.utils.common_upscale(samples, new_w, new_h, _method, "disabled")
    return out.to(dtype=orig_dtype)


# ── v14.83/84/85: 像素域超分旁支（per-clip 逐段 + final 全片，默认关）────────
def _ff_clip_upscale_enabled(clip, master):
    """CLIP 级超分开关优先于总开关 upscale_per_clip：
    None=跟随总开关；True=强制本 CLIP 超分；False=强制本 CLIP 不超分。"""
    if clip is None:
        return bool(master)
    v = clip.get("upscale")
    if v is None:
        return bool(master)
    return bool(v)


def _ff_resolve_upscale_mode(mode, factor, engine):
    """v14.84 upscale mode preset -> (factor, engine). Default: Balanced (quality+speed)."""
    if mode in ("Quality first", "质量优先"):
        return 3.0, "realesr"
    if mode in ("Speed first", "速度优先"):
        return 1.5, "auto"
    if mode in ("Custom", "自定义"):
        return float(factor), str(engine)
    return 2.0, "auto"


def _ff_probe_video(path, ff):
    """返回 (width, height, fps_float, frame_count)。失败返回 None。"""
    try:
        r = subprocess.run(
            [ff, "-i", str(path), "-f", "null", "-"],
            capture_output=True, timeout=60,
        )
        stderr = (r.stderr or b"").decode("utf-8", "replace")
        import re as _re
        w = h = None
        m = _re.search(r"(\d{2,5})x(\d{2,5})", stderr)
        if m:
            w, h = int(m.group(1)), int(m.group(2))
        fps = None
        m2 = _re.search(r"(\d+(?:\.\d+)?)\s*fps", stderr)
        if m2:
            fps = float(m2.group(1))
        frames = None
        m3 = _re.search(r"(\d+)\s*frames\s*$", stderr, _re.MULTILINE)
        if m3:
            frames = int(m3.group(1))
        return (w, h, fps, frames)
    except Exception:
        return None


def _ff_get_duration(path, ff):
    """Return duration in seconds, or 0.0 on failure."""
    try:
        r = subprocess.run([ff, "-i", str(path), "-f", "null", "-"],
                           capture_output=True, timeout=30)
        import re as _re
        m = _re.search(r"time=(\d+):(\d+):(\d+\.\d+)", r.stderr.decode("utf-8", "replace"))
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    except Exception:
        pass
    return 0.0


def _ff_build_xfade_merge_cmd(ff, clip_paths, output_path, vfade=0.5, afade=0.3):
    """Build ffmpeg command that chains xfade (video) + acrossfade (audio) for N clips.
    Returns (cmd_list, duration_log). Falls back to re-encoded concat if any clip too short."""
    durations = [_ff_get_duration(cp, ff) for cp in clip_paths]
    n = len(clip_paths)
    if n < 2:
        return None, durations
    if any(d < vfade * 2 for d in durations):
        return None, durations  # too short for xfade, caller falls back

    # Build chained xfade video filter
    vparts = []
    aparts = []
    vlabel = "0:v"
    alabel = "0:a"
    cum_dur = durations[0]
    for i in range(1, n):
        out_v = f"[v{i:02d}]"
        out_a = f"[a{i:02d}]"
        offset = max(0.1, cum_dur - vfade)
        vparts.append(f"[{vlabel}][{i}:v]xfade=transition=fade:duration={vfade}:offset={offset:.3f}{out_v}")
        aparts.append(f"[{alabel}][{i}:a]acrossfade=d={afade}:c1=tri:c2=tri{out_a}")
        vlabel = out_v
        alabel = out_a
        cum_dur = cum_dur + durations[i] - vfade  # cumulative after overlap

    filter_complex = ";".join(vparts + aparts)
    cmd = [ff, "-y"]
    for cp in clip_paths:
        cmd += ["-i", str(cp)]
    cmd += [
        "-filter_complex", filter_complex,
        "-map", vlabel,
        "-map", alabel,
        "-c:v", "libx264", "-preset", "fast", "-crf", "17",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        str(output_path),
    ]
    return cmd, durations


def _ff_upscale_video_file(path, factor, engine, model, fp16, tile, batch, face_restore):
    """对已生成的视频文件做像素超分重编码（原子替换原文件）。

    引擎：
      bicubic —— ffmpeg scale 滤镜（最快、无模型依赖、内存安全）；
      realesr —— 逐帧读入 → ComfyUI UpscaleModelLoader → 重编码（质量优先）；
      dlss5  —— 预留（需 NVIDIA DLSS SDK 与驱动），暂回退 bicubic；
      auto   —— 按可用性自动选择。
    默认平衡档=auto → realesr 可用则 realesr，否则 bicubic。
    """
    import torch
    import torch.nn.functional as F
    try:
        factor = float(factor)
        if factor <= 1.0:
            return True
        ff = _find_ffmpeg()
        if not ff:
            print("[H3 Extender] 超分: 找不到 ffmpeg, 跳过")
            return False
        path = Path(path)
        if not path.exists():
            return False
        probe = _ff_probe_video(path, ff)
        if not probe or not probe[0] or not probe[1]:
            print("[H3 Extender] 超分: 无法探测视频尺寸, 跳过")
            return False
        w, h, fps, _frames = probe
        fw = max(2, int(round(w * factor)) // 2 * 2)
        fh = max(2, int(round(h * factor)) // 2 * 2)
        engine_eff = str(engine)
        if engine_eff == "auto":
            engine_eff = "realesr" if _ff_realesr_available(model) else "bicubic"
        tmp = path.with_name(path.stem + ".upscaled" + path.suffix)
        if engine_eff == "bicubic":
            cmd = [
                ff, "-y", "-i", str(path),
                "-vf", f"scale={fw}:{fh}:flags=bicubic",
                "-c:v", "libx264", "-crf", "18", "-preset", "slow",
                "-pix_fmt", "yuv420p",
                str(tmp),
            ]
            subprocess.run(cmd, check=True, capture_output=True, timeout=7200)
        elif engine_eff == "realesr":
            _ff_upscale_video_realesr(path, tmp, ff, fw, fh, fps, model, fp16, tile, batch)
        else:
            # dlss5 预留：无 SDK 时回退 bicubic
            print(f"[H3 Extender] 超分引擎 {engine_eff} 暂不可用, 回退 bicubic")
            cmd = [
                ff, "-y", "-i", str(path),
                "-vf", f"scale={fw}:{fh}:flags=bicubic",
                "-c:v", "libx264", "-crf", "18", "-preset", "slow",
                "-pix_fmt", "yuv420p",
                str(tmp),
            ]
            subprocess.run(cmd, check=True, capture_output=True, timeout=7200)
        os.replace(tmp, path)
        print(f"[H3 Extender] 像素超分完成: {path.name} {w}x{h} -> {fw}x{fh} engine={engine_eff}")
        if face_restore:
            _ff_face_restore_file(path, ff)
        return True
    except Exception as e:
        print(f"[H3 Extender] 像素超分失败: {e}")
        try:
            if tmp and Path(tmp).exists():
                Path(tmp).unlink()
        except Exception:
            pass
        return False


def _ff_realesr_available(model):
    """检查 ComfyUI 的 UpscaleModelLoader 链路是否可用（bicubic 无需模型）。"""
    try:
        import importlib.util as _ilu_r
        import comfy_extras.nodes_upscale_model as _num
        import comfy.ldm.modules.upscale as _lmu
        return bool(model and _num.UpscaleModelLoader and _lmu.ImageUpscaleWithModel)
    except Exception:
        return False


def _ff_upscale_video_realesr(path, tmp, ff, fw, fh, fps, model, fp16, tile, batch):
    """realesr 逐帧超分：ffmpeg 抽帧(rgb24) → torch → UpscaleModelLoader → 重编码。"""
    import numpy as np
    import torch
    import torch.nn.functional as F
    import comfy_extras.nodes_upscale_model as _num
    import comfy.ldm.modules.upscale as _lmu
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    loader = _num.UpscaleModelLoader()
    up_model = loader.load_model(model).to(dev)
    if fp16 and dev.type == "cuda":
        up_model = up_model.half()
    raw = str(tmp) + ".raw"
    # 抽原始帧
    subprocess.run(
        [ff, "-y", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", raw],
        check=True, capture_output=True, timeout=7200,
    )
    nbytes = os.path.getsize(raw)
    fw_in, fh_in = _ff_probe_video(path, ff)[0], _ff_probe_video(path, ff)[1]
    fw_in = fw_in or 1
    fh_in = fh_in or 1
    per_frame = fw_in * fh_in * 3
    n_frames = max(1, nbytes // per_frame)
    bs = max(1, int(batch))
    arr = np.frombuffer(open(raw, "rb").read(), dtype=np.uint8)
    out_frames = []
    with torch.inference_mode():
        for s in range(0, n_frames, bs):
            chunk = arr[s * per_frame:(s + bs) * per_frame]
            t = torch.from_numpy(chunk).reshape(-1, fh_in, fw_in, 3).permute(0, 3, 1, 2).float().div_(255.0).to(dev)
            if fp16 and dev.type == "cuda":
                t = t.half()
            t = up_model(t, tile_size=int(tile) if int(tile) > 0 else None, tile_overlap=16, scale=1.0)
            if fp16 and dev.type == "cuda":
                t = t.float()
            out_frames.append(t.clamp_(0.0, 1.0).mul_(255.0).byte().cpu())
    os.unlink(raw)
    if not out_frames:
        raise RuntimeError("realesr: 无输出帧")
    cat = torch.cat(out_frames, dim=0).permute(0, 2, 3, 1).numpy()
    tmpraw = str(tmp) + ".out.raw"
    cat.tofile(tmpraw)
    subprocess.run(
        [ff, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{fw}x{fh}",
         "-r", str(fps or 30.0), "-i", tmpraw,
         "-c:v", "libx264", "-crf", "18", "-preset", "slow", "-pix_fmt", "yuv420p",
         str(tmp)],
        check=True, capture_output=True, timeout=7200,
    )
    os.unlink(tmpraw)


def _ff_face_restore_file(path, ff):
    """人脸修复预留：检测到 codeformer/gfpgan 权重时启用，否则打印提示跳过。"""
    try:
        import folder_paths as _fp_fr
        has = _fp_fr.get_filename_list("facerestore_models")
        if not has:
            print("[H3 Extender] 人脸修复: 无 facerestore_models 权重, 跳过")
            return
        print(f"[H3 Extender] 人脸修复: 检测到 {len(has)} 个权重, 预留接入 FaceRestore (后续)")
    except Exception:
        pass


def _ff_const_add_noise(model, noise_tensor, sigmas, latent, audio_denoise):
    """v1.31: CONST 重加噪(对齐 Sol-H3 LatentUpscaleAlign 语义, 输入为噪声 tensor):
    process_latent_in/out 作用于整体 NestedTensor, 在 sigmas[0] 处混合,
    再 inverse_noise_scaling, 使二采以 σ·ε+(1-σ)·x 而非 (1-σ)²·x 重构。
    音频锁定: 音频成员噪声置零 + noise_mask 音频=0 (audio_denoise<0.5 时)。
    """
    if len(sigmas) == 0 or "samples" not in latent:
        return latent

    out = dict(latent)
    latent_image = latent["samples"]
    members, was_nested = _ff_extract_members(latent_image)
    n_members, n_was_nested = _ff_extract_members(noise_tensor)
    if len(n_members) != len(members):
        raise ValueError(f"噪声成员数 {len(n_members)} 与 latent 成员数 {len(members)} 不一致")

    lock_audio = len(members) >= 2 and float(audio_denoise) < 0.5
    if lock_audio:
        # 音频成员噪声置零(保持一采音频)
        n_members = [torch.zeros_like(t) if i == 1 else t for i, t in enumerate(n_members)]

    # noise_mask: 音频=0(保持), 视频=1(重噪); H3 joint DiT 仍需 mask 显式锁定
    if lock_audio and was_nested:
        mask_members = []
        for i, m in enumerate(members):
            if i == 0:
                mask_members.append(torch.ones(
                    (m.shape[0], 1, m.shape[2], m.shape[3], m.shape[4]),
                    device=m.device, dtype=torch.float32))
            elif i == 1:
                mask_members.append(torch.zeros(
                    (m.shape[0], 1, m.shape[2], m.shape[3]),
                    device=m.device, dtype=torch.float32))
            else:
                mask_members.append(torch.ones_like(m[:1, :1]))
        out["noise_mask"] = _ff_wrap_members(mask_members, was_nested=True)

    model_sampling = model.get_model_object("model_sampling")
    process_latent_out = model.get_model_object("process_latent_out")
    process_latent_in = model.get_model_object("process_latent_in")
    sigma_start = sigmas[0]

    latent_image = process_latent_in(latent_image)
    lat_members, _ = _ff_extract_members(latent_image)
    mixed = []
    for lat, noi in zip(lat_members, n_members):
        m = model_sampling.noise_scaling(sigma_start, noi, lat)
        if hasattr(model_sampling, "inverse_noise_scaling"):
            m = model_sampling.inverse_noise_scaling(sigma_start, m)
        mixed.append(m)
    mixed_nt = _ff_wrap_members(mixed, was_nested=was_nested or n_was_nested)
    mixed_nt = process_latent_out(mixed_nt)
    m_members, _ = _ff_extract_members(mixed_nt)
    out["samples"] = _ff_wrap_members(
        [torch.nan_to_num(t, nan=0.0, posinf=0.0, neginf=0.0) for t in m_members],
        was_nested=was_nested)
    return out


def _upscale_latent_spatial(samples, factor):
    """v1.30: H3 AV latent 空间维度放大。
    H3 latent 为 5D (B, C, T, H, W)，空间下采样率 16（输出 768×1344 → latent 48×84）。
    仅放大 H/W，保持 B/C/T 不变；放大后对齐到 2 的倍数（对应像素 32 网格）。
    4D latent 走 common_upscale 兜底。
    v1.21: 兼容 NestedTensor（H3 采样器可能返回 NestedTensor，无 .reshape 方法）。
    """
    factor = max(1.0, float(factor))
    if factor <= 1.0:
        return samples
    # NestedTensor 兼容：无 .reshape 方法时尝试转为 padded tensor
    if not hasattr(samples, "reshape"):
        try:
            if hasattr(samples, "to_padded_tensor"):
                samples = samples.to_padded_tensor(0.0)
                print(f"[H3 Extender] _upscale_latent_spatial: converted NestedTensor -> padded tensor shape={tuple(samples.shape)}")
            else:
                print(f"[H3 Extender] _upscale_latent_spatial: unsupported type {type(samples).__name__}, skip upscale")
                return samples
        except Exception as _conv_err:
            print(f"[H3 Extender] _upscale_latent_spatial: NestedTensor convert failed ({_conv_err}), skip upscale")
            return samples
    if samples.ndim == 4:
        _, _, H, W = samples.shape
        nH = max(2, (int(H * factor) // 2) * 2)
        nW = max(2, (int(W * factor) // 2) * 2)
        return comfy.utils.common_upscale(samples, nW, nH, "bilinear", "center")
    # 5D (B, C, T, H, W)
    B, C, T, H, W = samples.shape
    nH = max(2, (int(H * factor) // 2) * 2)
    nW = max(2, (int(W * factor) // 2) * 2)
    bt = B * T
    reshaped = samples.reshape(bt, C, H, W)
    # v2.0: bilinear 替代 bicubic，减少 latent 放大后的鬼影/重影
    up = torch.nn.functional.interpolate(reshaped, size=(nH, nW), mode="bilinear", align_corners=False)
    return up.reshape(B, C, T, nH, nW)


def _drop_mismatched_adaln_patches(model):
    """Shape-aware drop of lora adaln patches whose delta does not match the base adaln weight.

    pruned base adaln_proj.linear.weight=[96768,8], but full-width loras (e.g. cinematic lora)
    carry adaln delta=[96768,2688]. The rgthree stack applies AFTER SolH3 without SolH3's
    _shape_filter, so calculate_weight fails to reshape every block every step (spam+slow).
    We compare each patch expected shape against model_state_dict real shape and drop only the
    mismatched entries; attn/mlp detail enhancement stays. Full-width bases keep matching adaln.
    """
    try:
        model_sd = model.model_state_dict()
    except Exception:
        return 0
    dropped = 0
    for k in list(getattr(model, "patches", {}).keys()):
        if "adaln_proj.linear" not in k:
            continue
        if k not in model_sd:
            continue
        mw_shape = tuple(model_sd[k].shape)
        kept = []
        for entry in model.patches[k]:
            try:
                patch_obj = entry[1]
                mat1 = patch_obj.weights[0]
                mat2 = patch_obj.weights[1]
                exp = (tuple(mat1.shape)[0], tuple(mat2.shape)[1])
            except Exception:
                kept.append(entry)
                continue
            if tuple(exp) == tuple(mw_shape):
                kept.append(entry)
            else:
                dropped += 1
        if kept:
            model.patches[k] = kept
        else:
            del model.patches[k]
    return dropped


def _sample_h3(model, conditioning, latent, seed: int, sampler_name: str, scheduler: str, steps: int, denoise: float,
               owner_id=None, clip_index=-1,
               refine_enable=True, refine_denoise=0.45, refine_steps=2, refine_upscale_factor=2.0,
               refine_upscaler_model="", refine_align_to=40, refine_audio_denoise=0.0,
               tiled_refine=False, tile_count=4, tile_overlap=128,
               refine_mem_mode="spatial",
               temporal_chunk_tokens=0, temporal_overlap_tokens=8,
               dual_track_shift=True, shift_video=12.0, shift_audio=3.0,
               tst_enable=True, tst_tau=0.2, omni_8step_mode=False,
               honor_manual_steps=False):
    if int(steps) < 1:
        raise ValueError("MiniMax H3 Extender: steps must be >= 1.")

    # v14.195: 音频渲染质量保护（渲染环节治本, 非渲染后处理）——
    # 诊断(h3_clip_250 样本 + 5 个历史渲染): 所有电影工厂渲染输出均带恒定
    # 低频轰鸣(100-200Hz 占全频 ~60%、全程无静音、200-400Hz 人声带被盖住),
    # 而参考音频(lip_audio)本身干净(完美标准: 200-400Hz 占 73%)。根因:
    # ① lip_audio 对口型模式一采音频=参考原声 latent 锁定(干净), 二采
    #   refine_audio_denoise=0.7 把它 70% 重噪后仅 4 步重画(官方音频下限
    #   12 步) → 干净参考被重绘成低频轰鸣; ② 非 lip 模式(ref_audio 条件
    #   配音)一采 <12 步生成音频同样劣化。
    # 修复: 音频要么锁定保持原声(lip 模式默认), 要么 ≥12 步生成/重绘;
    # 环境变量 BSAI_H3_AUDIO_QUALITY=0 可一键关闭全部自动行为(回退旧参数)。
    _has_audio = False
    _lip_locked = False
    try:
        _m_probe = latent.get("samples")
        _mem_probe, _nt_probe = _ff_extract_members(_m_probe)
        if _nt_probe and len(_mem_probe) >= 2:
            _has_audio = True
            _nm_probe = latent.get("noise_mask")
            if _nm_probe is not None:
                _nmm_probe, _ = _ff_extract_members(_nm_probe)
                if len(_nmm_probe) >= 2 and int(torch.count_nonzero(_nmm_probe[1])) == 0:
                    _lip_locked = True
    except Exception as _probe_err:
        _has_audio, _lip_locked = False, False
    _audio_quality_on = os.environ.get("BSAI_H3_AUDIO_QUALITY", "1") != "0"
    if _has_audio:
        print(f"[H3 Extender] v14.195 音频渲染质量保护: 检测到 AV 双成员 latent, "
              f"lip_audio锁定={'是' if _lip_locked else '否'}, 自动保护={'开' if _audio_quality_on else '关(环境变量)'}")

    # v14.81: safety net for the payload row-order guard. The module installs
    # itself at import; re-asserting here puts it back on top in the rare case
    # something stacked over it after startup, and covers graphs that reached
    # the sampler before the import-time install could. Self-detecting, so the
    # per-clip calls after the first are a cheap no-op.
    if not _row_order_patch_applied():
        _apply_row_order_patch()

    _n_dropped = _drop_mismatched_adaln_patches(model)
    if _n_dropped:
        print(f"[H3 Extender] shape-aware dropped {_n_dropped} adaln lora patches mismatched with base (pruned/full auto, attn/mlp kept)", flush=True)

    # P0 (2026-10-17): 官方双轨迹采样注入 (MiniMaxH3SigmaShift 等效).
    # 在 guider 创建前对 model clone+patch: ModelSamplingAV 驱动采样器 sigma,
    # transformer_options 双 shift 让模型内部推导 audio schedule.
    if dual_track_shift:
        # v14.152: shift_audio 可能已是 None（0.0 的映射），不再 float()
        model = _apply_h3_dual_track_shift(model, float(shift_video), shift_audio)
    # P2 (2026-10-17): SelfLift H3 TST 少步数画质补偿 (时间状态传输).
    if tst_enable:
        model = _apply_h3_tst(model, True, float(tst_tau))

    # v14.195: 一采音频步数保护 —— 音频由模型生成时(非 lip 锁定), 一采步数
    # <12(官方音频可用下限)会把配音生成出恒定低频轰鸣/含混吞音(实测 8 步
    # 档样本: 100-200Hz 占 59.5%, 全程无静音)。lip 锁定模式一采音频不采样
    # (mask=0), 步数不影响音频, 不提升(保持档位速度与画质)。
    if _has_audio and not _lip_locked and _audio_quality_on and int(steps) < 12:
        if honor_manual_steps:
            print(f"[H3 Extender] v14.205 custom 手动步数优先: 一采 {int(steps)} 步 < 音频 12 步下限, "
                  f"按用户设置执行(配音质量可能下降; 要干净配音请接 lip_voice 或设 12 步)")
        else:
            print(f"[H3 Extender] v14.195 音频生成保护: 一采 {int(steps)} 步 < 官方音频 "
                  f"12 步下限, 自动提升到 12 步(根治低频轰鸣/含混配音; 如须回退 "
                  f"设 BSAI_H3_AUDIO_QUALITY=0)")
            steps = 12

    guider = _BasicGuider(model)
    # v14.169: FastH3 Omni 蒸馏契约 = guidance 1.0 单前向(无 CFG)。
    # CFGGuider 默认 cfg=8 双前向会过驱动蒸馏模型 → 过曝/伪影/糊
    # (cfg=8 是 FastH3 V2 老模型的用法; Omni 8步蒸馏必须 guidance 1.0)。
    if omni_8step_mode:
        guider.cfg_scale = 1.0
        print("[H3 Extender] v14.169 Omni 8步单采: 一采 guidance 1.0 (官方蒸馏契约, 单前向)")
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
                # v1.75 (2026-09-15 fix #11): 兼容不同 ComfyUI 版本的 Latent2RGBPreviewer。
                # 新版构造时 transpose(0,1) (linear 需要 (in,out)); 4090 pro_v36_lig 等旧版
                # 不转置 (linear 直接 x@W 需 (in,out) 语义不同), 传 (3,24) 会每步刷
                # "mat1 and mat2 shapes cannot be multiplied" 报错。
                # 解法: 构造后用 2x2 探针实测 decode, 失败自动用转置 factors 重试,
                # 再失败回退 None (走下方手动 RGB 预览, 不依赖 latent_preview 实现)。
                previewer = None
                _probe_ok = False
                for _factors_try in (factors, [list(r) for r in zip(*factors)]):
                    try:
                        _pv_try = latent_preview.Latent2RGBPreviewer(_factors_try)
                        _probe = _pv_try.decode_latent_to_preview(
                            preview_x0_test[:, :, :2, :2]
                            if preview_x0_test.ndim == 4 else preview_x0_test[:, :, 0, :2, :2])
                        previewer = _pv_try
                        _probe_ok = True
                        break
                    except Exception:
                        continue
                if _probe_ok:
                    print(f"[H3 Extender] using fallback Latent2RGB previewer (channels={ch})")
                else:
                    print(f"[H3 Extender] fallback previewer 两种 factors 均失败, 用手动 RGB 预览")
            except Exception as _e2:
                print(f"[H3 Extender] fallback previewer also failed: {_e2}")
                previewer = None

    pbar = comfy.utils.ProgressBar(total_steps)
    _last_sent_step = {"v": -1}

    _cb_t0 = {"t": None}
    def _latent_preview_callback(step, x0, x, total_steps_arg):
        # v1.55: 每步耗时诊断——定位第 4 步固定 ~430s 的瓶颈(计算/IO/卸载)
        try:
            import time as _t55
            _now55 = _t55.time()
            if _cb_t0["t"] is not None:
                print(f"[H3 Extender] step耗时诊断: step={step}/{total_steps_arg} 距上步 {_now55-_cb_t0['t']:.1f}s")
            _cb_t0["t"] = _now55
        except Exception:
            pass
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
                        # v1.46: H3 latent 预览是 latent 格点直接映射(60x34 等),
                        # 不放大则前端看到的就是一张极小的缩略图, 视觉上"糊成一片"。
                        # 放大到实际视频分辨率(LANCZOS 平滑), 让一采预览真实可辨。
                        try:
                            _pv_w, _pv_h = img.size
                            _pv_scale = 16
                            if _pv_w < 320 or _pv_h < 320:
                                img = img.resize(
                                    (_pv_w * _pv_scale, _pv_h * _pv_scale),
                                    Image.LANCZOS,
                                )
                        except Exception:
                            pass
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
    # v1.52: force_full_load=True 把 21.8GB 全拉满 -> process_conds OOM (物理 23.86GB).
    # 改走 ComfyUI 自带预算: 把 EXTRA_RESERVED_VRAM 从 CLI 的 0 抬到 5.5GB, 让
    # minimum_inference_memory = 0.8+5.5 = 6.3GB; lowvram_model_memory = free - minimum_inference
    # ≈ 22 - 6.3 = 15.7GB 权重驻留, 尾部 ~6GB offload, 留 ~6GB 给 conds(cross_attn)+workspace.
    # 不再 force_full_load, 也不覆写 outer_sample. ComfyUI 自己按预算装, process_conds 有地放.
    try:
        import torch as _t1
        import comfy.model_management as _mm1
        # v1.84: 根治量化权重低显存流转的无声闪退。用户启动参数 --async-offload
        # 使 NUM_STREAMS>=1, int8量化权重(comfy_quant)在 CPU<->GPU 异步搬运时
        # 与 forward 复用存在竞态, 导致 step2/8 后进程无声消失(无traceback/驱动事件)。
        # 这里强制 NUM_STREAMS=0 (等价 --disable-async-offload), 搬运同步化。
        try:
            if getattr(_mm1, "NUM_STREAMS", 0) != 0:
                _mm1.NUM_STREAMS = 0
                print("[H3 Extender] 已禁用异步 offload (NUM_STREAMS=0, 同步搬运防量化权重竞态闪退)", flush=True)
        except Exception:
            pass
        # v1.81: 一采前也释放 DynamicVRAM staged, 保证一采起始显存充足 (4090 保险)。
        try:
            _release_dynamic_vram("pass1")
        except Exception:
            pass
        _t1.cuda.empty_cache()
        try: _t1.cuda.ipc_collect()
        except Exception: pass
        _free_os, _tot_os = _t1.cuda.mem_get_info()
        _free_os /= 1024 ** 3; _tot_os /= 1024 ** 3
        # v1.84: reserve 5.5->4.0GB（实测: 2.0全量驻留->free=0 process_conds OOM;
        # 3.0->free=0.22GB 仍OOM; 5.5->驻留16.2+offload3.7 流转崩; 4.0->驻留~17.5GB
        # +offload~2GB, free~2.5GB, 流转量减半）。量化权重低显存流转在
        # cudaMallocAsync+async-offload 下会无声硬崩(step2/8 后进程消失),
        # 配合启动参数去掉 --async-offload 根治。
        try: _mm1.EXTRA_RESERVED_VRAM = int(4.0 * 1024 ** 3)
        except Exception: pass
        print(f"[H3 Extender] 一采前显存: OS free={_free_os:.2f}GB / {_tot_os:.1f}GB (allocated={_t1.cuda.memory_allocated()/1024**3:.2f}GB), reserve->4.0GB")
        # v1.91: 一采前同样解除 16GB fraction 限制(与二采一致), 避免
        # staged 15.25GB + workspace 临界超限. 全链路可用物理 23.86GB.
        try:
            _cur_frac91b = _t1.cuda.get_per_process_memory_fraction()
            if _cur_frac91b < 1.0:
                _t1.cuda.set_per_process_memory_fraction(1.0)
                print(f"[H3 Extender] v1.91 一采前解除 fraction 限制: {_cur_frac91b:.3f} -> 1.0")
        except Exception as _e91b:
            print(f"[H3 Extender] v1.91 一采前 fraction reset 失败: {_e91b}")
        # v14.186: 显存预算自检 —— 权重装不下时明确告警，避免用户白跑一整轮
        # (实测 19.5GB DiT 在 24GB 卡上不走驻留 → 每步 800s+，而驻留时 100-200s)。
        def _h3_warn_stream_fallback(_total_gb, _free_gb):
            _avail = max(0.0, float(_free_gb) - 4.0)
            print(f"[H3 Extender] ⚠️ v14.186 显存预算不足: DiT 权重 {float(_total_gb):.1f}GB > "
                  f"可用 {float(_free_gb):.1f}GB − reserve 4.0GB = {_avail:.1f}GB")
            print("[H3 Extender] ⚠️ 本段将走 DynamicVRAM 逐层流式搬运(同步, 无法与计算重叠): "
                  "实测每步可能 600-900s (权重整块驻留时 100-200s)")
            print("[H3 Extender] ⚠️ 建议: ①换剪枝/int8 小模型(如 fasth3_omniref_8step_pruned_int8_convrot, "
                  "配「FastH3 Omni 8步单采」档)让权重整块驻留; ②或换更大显存显卡; "
                  "③降低分辨率/上下文只能减 activation, 解决不了权重装不下")
        if _free_os >= 18.0:
            _mm1.load_models_gpu([model])   # reserve 4.0 预算: 驻留 ~17.5GB, 尾部 ~2GB offload
            _t1.cuda.synchronize()
            try:
                _res = model.loaded_size() / 1024 ** 3
                _tot = model.model_size() / 1024 ** 3
                print(f"[H3 Extender] 一采前 DiT 驻留: resident={_res:.1f}GB / total={_tot:.1f}GB (offload ~{_tot-_res:.1f}GB)")
                # v14.174 (2026-10-23): load_models_gpu 后 resident 无效回退.
                # int8 H3 total≈20.6GB, 24GB 卡 reserve 4GB 可用 ~20GB —— 装不下
                # 全量, load_models_gpu 静默返回 resident=0.0GB. 但它会往
                # current_loaded_models 里插 LoadedModel 占位, 污染 DynamicVRAM
                # staged 按需加载的调度状态, 导致采样时每次 forward 都走全流式
                # CPU↔GPU 搬运 + workspace 临界 → step 0/4 直接 OOM
                # (int8_linear 申请 int32 输出缓冲时爆掉).
                # 修复: resident < 4GB 说明连核心 transformer 层都没驻留,
                # 调用 _ff_unregister_model 摘除 LoadedModel + soft_empty_cache,
                # 让 DynamicVRAM 回到干净 staged 状态, forward 时按需搬运.
                # 注: ComfyUI 无公开 unload_model() API (全局 _mm.unload_model 都是
                # silent no-op, 已统一替换为 _ff_unregister_model).
                if _res < 4.0:
                    _ff_unregister_model(model, label="一采-resident无效")
                    print(f"[H3 Extender] v14.174 驻留无效(resident={_res:.1f}GB<4GB), "
                          f"回退 DynamicVRAM 按需流式 (total={_tot:.1f}GB > 可用{_free_os:.1f}GB-reserve)")
                    _h3_warn_stream_fallback(_tot, _free_os)
            except Exception: pass
        else:
            print(f"[H3 Extender] 一采前 free={_free_os:.1f}GB < 18GB, 走 ComfyUI 按需流式")
            try:
                _h3_warn_stream_fallback(model.model_size() / 1024 ** 3, _free_os)
            except Exception:
                pass
    except Exception as _lp1:
        print(f"[H3 Extender] 一采前驻留预算设置失败(走按需流式): {_lp1}")
    # ---- BSAI 协同：GPU 主采样租约（失败不阻断采样，仅叠加租约管理） ----
    _bsai_alloc = None
    try:
        _bsai_alloc = BSAIOrch.allocate("sampling", requester="8191")
        if not _bsai_alloc.ok:
            print(f"[H3 Extender] SDK 未取得 gpu1_sampling 租约({_bsai_alloc.reason})，仍按原逻辑采样", flush=True)
    except Exception as _bsai_ae:
        print(f"[H3 Extender] SDK allocate 异常(忽略): {_bsai_ae}", flush=True)
        _bsai_alloc = None
    # v14.198 首步拆分诊断: 实测一采 step1=1217s, step2~12=45-48s。探针在首次
    # DIFFUSION_MODEL 前向入口打印"采样开始→前向"间隔(= process_conds/编码),
    # 前向返回后再打一次, 用来判定 1217s 花在 conds 还是首次前向(权重换页/op 编译).
    _ff_probe198 = {"t0": time.time(), "t1": None, "done": False}
    def _ff_first_forward_probe198(executor, x, timestep, context, transformer_options, **kwargs):
        if _ff_probe198["t1"] is None:
            _ff_probe198["t1"] = time.time()
            print(f"[H3 Extender] v14.198 首步拆分: 采样开始→首次前向 "
                  f"{_ff_probe198['t1'] - _ff_probe198['t0']:.1f}s (process_conds/编码)", flush=True)
        out = executor(x, timestep, context, transformer_options, **kwargs)
        if not _ff_probe198["done"]:
            _ff_probe198["done"] = True
            print(f"[H3 Extender] v14.198 首步拆分: 首次前向 "
                  f"{time.time() - _ff_probe198['t1']:.1f}s (含权重换页/op 编译), "
                  f"首步合计 {time.time() - _ff_probe198['t0']:.1f}s", flush=True)
        return out
    try:
        import comfy.patcher_extension as _pe198
        model.add_wrapper_with_key(_pe198.WrappersMP.DIFFUSION_MODEL,
                                   "bsai_first_step_probe", _ff_first_forward_probe198)
    except Exception as _e198:
        print(f"[H3 Extender] v14.198 首步探针安装失败(忽略): {_e198}")
    try:
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
    finally:
        try:
            model.model_options["wrappers"][_pe198.WrappersMP.DIFFUSION_MODEL].pop(
                "bsai_first_step_probe", None)
        except Exception:
            pass
        if _bsai_alloc is not None:
            try:
                _bsai_alloc.release()
            except Exception:
                pass
    samples = samples.to(comfy.model_management.intermediate_device())

    # v1.31: 二采升级为 Sol-H3 Self-Lift 双采（一采 + 二采直出高清）
    # 技术流程（对齐 BSAI-ComfyUI-Sol-H3 LatentUpscaleAlign 极速版）：
    #   1) 一采潜空间结果直接放大（不经过 VAE，无编解码画质损失）：
    #      NestedTensor 感知——只放大视频成员，音频 latent 保持不动；
    #      放大后像素对齐 H3 官方 32px 网格（1920x1088 = 120x68 latent）；
    #      可选 3D latent upscaler 神经网络语义放大（细节更丰富）。
    #   2) CONST 重加噪：视频重噪到 sigma_start（σ·ε+(1-σ)·x 语义），
    #      音频默认锁定（零噪声 + noise_mask=0，保持一采音频不重绘）。
    #   3) DisableNoise 二采：从 CONST 加噪 latent 走完整去噪曲线
    #      （refine_denoise=1.0 时全量重绘，=0.55 时保留 45% 底图信息）。
    if refine_enable:
        try:
            _r_factor = float(refine_upscale_factor)
            _r_steps = max(1, int(refine_steps))
            _r_denoise = max(0.05, min(1.0, float(refine_denoise)))
            _r_audio = float(refine_audio_denoise)
            _r_align = max(8, int(refine_align_to))
            # v14.195: 二采音频质量保护(渲染环节)——
            # ① lip_audio 对口型模式: 一采音频=参考原声 latent 已锁定(完美),
            #    二采音频重绘(0.7)会把干净参考 70% 重噪后低步数重画 → 低频
            #    轰鸣(实测根因)。默认保持锁定(输出=参考原声, 即"完美标准");
            #    环境变量 BSAI_H3_LIP_AUDIO_REDRAW=1 可恢复重绘(此时步数下限
            #    12 兜底)。② 音频重绘开启且二采步数 <12 → 自动提升到 12(官方
            #    音频下限), 根治"从噪声画 4 步音频"的轰鸣/崩坏。
            if _has_audio and float(_r_audio) >= 0.5:
                if _lip_locked and os.environ.get("BSAI_H3_LIP_AUDIO_REDRAW", "0") != "1":
                    _r_audio = 0.0
                    print(f"[H3 Extender] v14.195 lip_audio 对口型: 参考原声已锁定, "
                          f"二采音频重绘 {float(refine_audio_denoise):.1f} 会把它重绘成 "
                          f"低频轰鸣(实测根因), 已保持锁定(输出=参考原声)。如确需重绘 "
                          f"设 BSAI_H3_LIP_AUDIO_REDRAW=1(此时步数自动 ≥12)")
                elif _audio_quality_on and int(_r_steps) < 12:
                    # v14.196: 不再把二采步数 4→12 (实测 4 步 324s/步 = 65 分钟/15秒片段,
                    # 用户无法接受)。一采音频已按 12 步生成(上面的音频生成保护保证),
                    # 二采只需锁住音频不再重绘即可保留同一份音频, 步数尊重用户设置。
                    # 效果等同: 音频质量不降, 二采少跑 8 步。
                    _r_audio = 0.0
                    print(f"[H3 Extender] v14.196 音频重绘保护: 二采 {int(refine_steps)} 步 < "
                          f"音频 12 步下限, 改为锁定音频(保留一采 12 步音频, 不重绘), "
                          f"二采步数按设置 {int(_r_steps)} 步执行(不做 4→12 提升, 省 8 步)。"
                          f"如须重绘并提升步数 设 BSAI_H3_AUDIO_QUALITY=0")
            # v1.44: 选了 3D upscaler 模型但 factor<=1.0 时自动提升到 1.5.
            # factor=1.0 会跳过 _ff_upscale_video_latent(), 3D upscaler
            # 白选了, 二采只是对同分辨率 latent 重加噪再去噪, 画质必糊.
            _has_upscaler = (refine_upscaler_model
                             and not str(refine_upscaler_model).startswith("(")
                             and _FF_UPSCALER_MOD is not None)
            if _has_upscaler and _r_factor <= 1.0:
                print(f"[H3 Extender] Refine: 选了 3D upscaler 但 factor={_r_factor}, "
                      f"自动提升到 1.5 以启用语义放大")
                _r_factor = 1.5
            print(f"[H3 Extender] Refine 双采(Sol-H3 Self-Lift): clip={clip_index} "
                  f"upscale=x{_r_factor} align={_r_align}px steps={_r_steps} denoise={_r_denoise:.2f} audio={_r_audio}")

            # v1.43 (2026-09-13 fix #4): 不再 unload_all_models()!
            # v1.32~v1.36 的 unload_all_models() 虽然释放了显存, 但把
            # diffusion 模型也卸了, 导致二采采样时 ComfyUI 以 full
            # lowvram 模式重载 (日志: "0.00 MB loaded, 19996.14 MB
            # offloaded"), 每个 layer 都要 CPU↔GPU 搬运, 造成显存碎片
            # 和峰值飙升, 必然 OOM.
            #
            # 参考 Sol-H3 双采极速版工作流: 一采和二采共用同一 model
            # 对象, 模型始终保持 loaded 状态, 二采只需额外 attention
            # workspace (~1-2GB), 总计 ~22GB 能装进 24GB 卡.
            #
            # 策略: 只做 GC + empty_cache 清理中间张量, 保留 diffusion
            # 在 VRAM. 3D upscaler 缓存在 _ff_upscale_video_latent()
            # 之后单独清理.
            try:
                import comfy.model_management as _mm
                import torch as _torch
                import gc as _gc
                _gc.collect()
                _mm.soft_empty_cache(force=True)
                _torch.cuda.synchronize()
                _torch.cuda.empty_cache()
                try:
                    _torch.cuda.ipc_collect()
                except Exception:
                    pass
                _a = _torch.cuda.memory_allocated() / 1024 ** 3
                _r = _torch.cuda.memory_reserved() / 1024 ** 3
                _f, _t = _torch.cuda.mem_get_info()
                _free_gb = _f / 1024 ** 3
                _total_gb = _t / 1024 ** 3
                print(f"[H3 Extender] Refine 二采前显存状态(v1.43 保留diffusion): "
                      f"allocated={_a:.2f}GB reserved={_r:.2f}GB "
                      f"device_free={_free_gb:.2f}GB/{_total_gb:.2f}GB")
            except Exception as _ve:
                print(f"[H3 Extender] Refine 二采前显存清理失败(可忽略): {_ve}")

            # v1.81: 二采前强制释放 DynamicVRAM staged 池 (4090 CUDA abort 修复),
            # 必须在显存预算检查之前, 让预算看到释放后的真实可用显存。
            try:
                _release_dynamic_vram("refine")
            except Exception as _rv81:
                print(f"[H3 Extender] v1.81 二采前显存释放异常(可忽略): {_rv81}")

            # v1.47 (2026-09-13 fix #6 二采卡死根治)
            # 问题(实锤, 与 BSAI-H3-MotionFix v2.9 记录的卡死同根因):
            #   DynamicVRAM 开启时 H3 int8 模型(21.8GB)以流式加载, 一采后
            #   完全释放显存(allocated≈0GB); 二采 _r_guider.sample() 触发
            #   21.8GB 全量重载 + 大 latent attention workspace(x2.0≈4.5GB),
            #   24GB 卡显存/内存耗尽 → Python 线程阻塞假死(日志停在
            #   "Model Initializing ... 0/4", 重启复现).
            #   对照: 11:05 成功运行(DynamicVRAM off)二采前模型驻留 9.19GB,
            #   二采无需全量重载, 4 步跑通; 17:40 卡死(DynamicVRAM on)
            #   二采前模型 0.02GB.
            # 修复: 1) 显存预算预检, 模型不在显存时按流式重载估算, 超限
            #   自动降级放大倍率(2.0→1.5→1.0)并醒目提示; 2) 二采采样前
            #   主动 load_model_gpu() 确保模型驻留(防 DynamicVRAM 重载
            #   假死); 3) 失败走已有 fallback, 绝不假死.
            try:
                import torch as _torch2
                _gpu_free_gb2, _gpu_total_gb2 = _torch2.cuda.mem_get_info()
                _gpu_free_gb2 /= 1024 ** 3
                _gpu_total_gb2 /= 1024 ** 3
                _alloc_gb2 = _torch2.cuda.memory_allocated() / 1024 ** 3
                _model_gb2 = 0.0
                try:
                    _dm2 = getattr(model, "model", None)
                    if _dm2 is not None:
                        _model_gb2 = sum(
                            p.numel() * p.element_size()
                            for p in _dm2.parameters()) / 1024 ** 3
                except Exception:
                    _model_gb2 = 0.0
                # int8 量化模型: 参数以 fp16 尺寸存于内存(41GB 量级), 实际
                # 显存占用≈参数量×0.53 (int8 每权重 1 字节 vs fp16 2 字节).
                # 实测: 参数 41.06GB → int8 显存 21.8GB (日志 21833MB Staged).
                if _model_gb2 > 0.0:
                    _model_gb2 *= 0.53
                if _model_gb2 <= 0.0:
                    _model_gb2 = 21.8  # int8 H3 经验值兜底
                # workspace 实测表: 60x34→1.5GB(一采) 90x50→2.6GB(11:05 二采)
                # 120x68→4.5GB(代码注释实测峰值)
                _ws_tbl = {1.0: 1.5, 1.5: 2.6, 2.0: 4.5}
                _orig_f = float(_r_factor)
                # 候选倍率从当前值开始逐级下降
                _cands = [f for f in (2.0, 1.5, 1.0) if _orig_f >= f - 1e-6]
                if not _cands:
                    _cands = [max(1.0, _orig_f)]
                # 需求估算:
                #  - 模型未驻留(alloc<4GB, DynamicVRAM 流式): 重载峰值≈35% 权重
                #  - 模型部分驻留(lowvram, 4GB<=alloc<全量): 二采需把 offloaded
                #    部分搬回 GPU, 搬运峰值≈(全量-已载)×0.6.
                #    实测校准: 11:05 x1.5 成功(起点 loaded 9.19GB, ws 2.6GB);
                #    19:13 x2.0 OOM(起点 loaded 10.34GB, ws 4.5GB, free 0).
                #    0.6 系数: x2.0 必拦, x1.5 放行(与 11:05 成功经验一致).
                # v1.65 (2026-09-14 fix #9 二采 x2.0 OOM 根治):
                # 实测 19:34 二采 x2.0: 旧预算(0.6 系数)算出需求 15.1GB<18.1GB
                # 放行, 但 load_models_gpu 全量驻留 21.72GB, Sol-Attn kernel
                # 连 603MB workspace 都分不出 → kernel failed×3 → fallback 到
                # 普通注意力 workspace 9.23GB 更大 → 二次 OOM → 回退一采.
                # 新预算: 驻留目标 = min(free,total) - workspace - 3GB 余量,
                # 驻留 <10GB 视为换页过重 → 逐级降 factor(在放大前拦截).
                _chosen2 = None
                for _f2 in _cands:
                    _ws2 = _ws_tbl.get(round(_f2, 1), 2.6)
                    _resident_target2 = min(_gpu_free_gb2, _gpu_total_gb2) - _ws2 - 3.0
                    if _resident_target2 >= 10.0:
                        _chosen2 = _f2
                        break
                # v14.157: 宁可分块, 不降倍率。
                # 旧逻辑在预算不足时直接把二采倍率 x2.0 降到 x1.5, 成片像素
                # 从声明的 1920x1088 悄悄缩水到 1440x800（线性 -25%, 人脸直接糊掉）。
                # 分块二采把 attention workspace 从 x2.0 的 4.5GB 压到 ~1.1GB,
                # 24GB 卡足以原地跑满原倍率; 只有分块也放不下时才真正降档。
                _auto_tiled = False
                if (not tiled_refine) and (_chosen2 is None or _chosen2 < _orig_f - 1e-6):
                    _ws_tiled_tbl = {1.0: 0.8, 1.5: 0.9, 2.0: 1.1}
                    _ws_tiled = _ws_tiled_tbl.get(round(_orig_f, 1), 1.1)
                    if min(_gpu_free_gb2, _gpu_total_gb2) - _ws_tiled - 3.0 >= 10.0:
                        tiled_refine = True
                        _auto_tiled = True
                        _chosen2 = _orig_f
                        print(f"[H3 Extender] v14.157 全帧二采 x{_orig_f} 显存不足, "
                              f"自动启用分块二采(tile_count={tile_count})保住原倍率, "
                              f"成片不再缩水到 x{_chosen2}")
                print(f"[H3 Extender] Refine 显存预算(v1.65): 模型~{_model_gb2:.1f}GB "
                      f"驻留alloc={_alloc_gb2:.1f}GB 可用显存={_gpu_free_gb2:.1f}GB/"
                      f"{_gpu_total_gb2:.0f}GB 驻留目标~{min(_gpu_free_gb2, _gpu_total_gb2) - _ws_tbl.get(round(_orig_f, 1), 2.6) - 3.0:.1f}GB")
                # v1.74 (2026-09-15 fix #10): 链几何一致性 —— 链上已有段时禁止 per-clip 降级。
                # 实测: 全量链渲染到 clip=7 时显存预算波动, 自动降级 2.0->1.5,
                # 二采 latent 从 120x68 变成 90x50, 与前段几何不一致,
                # Disk Join 报 "latent geometry changed" 中断整链 (4.5h 白跑).
                # 第一段(链空)允许降级(全局一致); 链上已有段时保持原 factor,
                # 若 OOM 由 v1.74b 把 fallback 输出 bilinear 对齐到链上几何。
                try:
                    _cp74, _cmp74 = _chain_paths(f"extender_{_safe_name(str(owner_id))}")
                    _cm74 = _load_manifest_from_paths(_cp74, _cmp74)
                    _cg74 = _cm74.get("geometry") if _cm74 is not None else None
                    if _cg74 is not None:
                        _chh74 = int(_cg74.get("video_h", 0))
                        _chw74 = int(_cg74.get("video_w", 0))
                        if _chh74 > 0 and _chw74 > 0 and _chosen2 is not None \
                                and _chosen2 < _orig_f - 1e-6:
                            _snap74 = max(1, _r_align // 16)
                            _m74a, _w74a = _ff_extract_members(samples)
                            _cur_h74, _cur_w74 = _m74a[0].shape[-2:]
                            _dg_h74 = _ff_snap_to_multiple(round(_cur_h74 * _chosen2), _snap74)
                            _dg_w74 = _ff_snap_to_multiple(round(_cur_w74 * _chosen2), _snap74)
                            if (_dg_h74, _dg_w74) != (_chh74, _chw74):
                                print(f"[H3 Extender] v1.74: 链上已有 {_chw74}x{_chh74} 段, "
                                      f"降级 x{_orig_f}->x{_chosen2} 会变几何 "
                                      f"({_dg_w74}x{_dg_h74}), 禁止 per-clip 降级(避免断链), "
                                      f"保持 x{_orig_f}")
                                _chosen2 = _orig_f
                except Exception as _ga74:
                    print(f"[H3 Extender] v1.74 链几何检查失败(可忽略): {_ga74}")
                if _chosen2 is not None and _chosen2 < _orig_f - 1e-6:
                    _r_factor = _chosen2
                    print(f"[H3 Extender] Refine 放大倍率已自动降级: x{_orig_f} -> x{_chosen2} "
                          f"(24GB 级显存 + int8 {_model_gb2:.1f}GB 模型下 x{_orig_f} 二采会假死, "
                          f"见 v1.47 显存预算)")
                    _send_extender_warning(
                        owner_id,
                        f"二采倍率被显存预算降级 x{_orig_f}→x{_chosen2}，"
                        f"本段成片像素低于声明值（细节会明显变软）",
                        clip_index=clip_index,
                    )
                elif _auto_tiled:
                    _send_extender_warning(
                        owner_id,
                        f"显存不足，已自动启用分块二采保住 x{_orig_f} 倍率"
                        f"（速度略降，画质不缩水）",
                        clip_index=clip_index,
                    )
                elif _chosen2 is None:
                    print(f"[H3 Extender] Refine 警告: 显存预算不足(需求>可用), "
                          f"二采将尝试流式采样, 若卡死请关闭 DynamicVRAM 启动 "
                          f"(--disable-dynamic-vram) 或换 w4a8 轻量模型")
            except Exception as _mp2:
                print(f"[H3 Extender] Refine 显存预算预检失败(可忽略): {_mp2}")

            # v1.38 (2026-09-13 fix): 在放大前 deep copy 一采原始 samples,
            # 留作 OOM fallback 用. 120x68 (2.0x) OOM 后, 重跑时直接用
            # 60x34 一采原始尺寸, attention workspace 从 4.47GB 降到
            # ~1.5GB, 24GB 卡稳过. 注意: 仅在 _r_factor > 1.0 时备份,
            # 省一份显存; 同时 audio latent 不备份 (audio 不放大不重画).
            # v14.206: 备份逻辑对 AV NestedTensor 修正。comfy.nested_tensor.NestedTensor
            # 没有 .clone(). 旧代码 hasattr(samples,"clone") 恒为 False, 于是二采这里
            # 从来就没备份成功过 —— OOM fallback 与塌陷回退都拿不到一采 latent。
            _samples_pre_upscale = None
            if _r_factor > 1.0:
                try:
                    if _ff_is_nested(samples):
                        _samples_pre_upscale = comfy.nested_tensor.NestedTensor(
                            [t.clone() for t in samples.unbind()])
                    elif hasattr(samples, "clone"):
                        _samples_pre_upscale = samples.clone()
                except Exception as _bp_err:
                    print(f"[H3 Extender] Refine 备份一采 samples 失败(可忽略): {_bp_err}")
                    _samples_pre_upscale = None

            # 1) NestedTensor 感知 latent 放大（仅视频，音频保持）+ 像素对齐 + 可选 3D upscaler
            if _r_factor > 1.0:
                _members, _was_nested = _ff_extract_members(samples)
                _old_hw = (tuple(_members[0].shape[-2:]) if _members else None)
                _FF_UPSCALER_FELL_BACK["hit"] = False
                _FF_UPSCALER_FELL_BACK["reason"] = ""
                _up_video = _ff_upscale_video_latent(
                    _members[0], _r_factor, _r_align, "bilinear", refine_upscaler_model)
                # v14.157: 3D 语义放大失败不再静默 —— 会退化成 bilinear,
                # 画质明显变软, 必须让用户在状态栏看到。
                if _FF_UPSCALER_FELL_BACK["hit"]:
                    _send_extender_warning(
                        owner_id,
                        f"3D 语义放大失败，已回退 bilinear 插值"
                        f"（{_FF_UPSCALER_FELL_BACK['reason']}）",
                        clip_index=clip_index,
                    )
                if tuple(_up_video.shape[-2:]) != tuple(_members[0].shape[-2:]):
                    samples = _ff_wrap_members([_up_video] + list(_members[1:]), _was_nested)
                    print(f"[H3 Extender] Refine 潜空间放大: clip={clip_index} "
                          f"{_old_hw[1]}x{_old_hw[0]} -> {_up_video.shape[-1]}x{_up_video.shape[-2]} (x{_r_factor})")

            # v14.162 (2026-10-22 fix): 一镜到底连续性修复 —— 二采保留 motion-context keyframe。
            # 旧 v2.55b 在二采完全清空 minimax_keyframes，但二采是 denoise=0.55 的重新采样
            # （会改变画面内容），清空后二采失去"上一段尾帧"锚定 → 段间画面漂移/虚影，
            # 一镜到底的尾帧引导链在一采生效后又被二采冲掉（4090 实机 3 clip 验证）。
            # 修复：把一采 keyframe latent 空间 trilinear resize 到二采 latent 分辨率后
            # 保留注入，使"上一段尾帧引导"贯穿一采+二采，接缝处无缝衔接。
            if _r_factor > 1.0:
                try:
                    _cond_kc = conditioning[0][1] if isinstance(conditioning, list) else conditioning
                    if isinstance(_cond_kc, dict) and _cond_kc.get("minimax_keyframes"):
                        _kfs = _cond_kc["minimax_keyframes"]
                        _memb14, _nst14 = _ff_extract_members(samples)
                        _tgt_hw14 = tuple(_memb14[0].shape[-2:]) if _memb14 else None
                        if _tgt_hw14 is not None:
                            _nfs14 = []
                            _resized14 = 0
                            for _kf14 in _kfs:
                                _kl14 = _kf14.get("latent")
                                if _kl14 is not None and _kl14.ndim == 5 \
                                        and tuple(_kl14.shape[-2:]) != _tgt_hw14:
                                    try:
                                        _kl14 = torch.nn.functional.interpolate(
                                            _kl14,
                                            size=(
                                                int(_kl14.shape[2]),
                                                int(_tgt_hw14[0]),
                                                int(_tgt_hw14[1]),
                                            ),
                                            mode="trilinear",
                                            align_corners=False,
                                        )
                                        _resized14 += 1
                                    except Exception:
                                        pass
                                _nkf14 = dict(_kf14)
                                _nkf14["latent"] = _kl14
                                _nfs14.append(_nkf14)
                            _cond_kc["minimax_keyframes"] = _nfs14
                            print(f"[H3 Extender] v14.162 二采保留 {len(_nfs14)} 个 motion-context keyframe"
                                  f" (resize {_resized14} 块到 {_tgt_hw14[1]}x{_tgt_hw14[0]} 二采空间), "
                                  f"一镜到底尾帧引导贯穿一采+二采")
                except Exception as _ekc:
                    print(f"[H3 Extender] v14.162 keyframe 保留失败(可忽略): {_ekc}")

            # v1.43: 3D upscaler 用完后立即清缓存, 释放 VRAM 给二采 diffusion.
            # MODEL_CACHE 不受 ComfyUI model_management 管理 (不在
            # current_loaded_models 里), ComfyUI 无法自动让位, 必须手动清.
            if _r_factor > 1.0 and refine_upscaler_model and _FF_UPSCALER_MOD is not None:
                try:
                    _cache = getattr(_FF_UPSCALER_MOD, "MODEL_CACHE", None)
                    if isinstance(_cache, dict) and _cache:
                        for _k, _m in list(_cache.items()):
                            try:
                                _m.to("cpu")
                            except Exception:
                                pass
                            del _m
                            del _cache[_k]
                        import gc as _gc
                        import torch as _torch
                        _gc.collect()
                        _torch.cuda.synchronize()
                        _torch.cuda.empty_cache()
                        print(f"[H3 Extender] Refine 3D upscaler 缓存已清理, 释放 VRAM 给二采")
                except Exception as _uc_err:
                    print(f"[H3 Extender] Refine 清 3D upscaler cache 失败(可忽略): {_uc_err}")

            # 2) CONST 重加噪（视频重噪到 sigma_start，音频锁定/重绘）
            # v1.33: 二采调度器对齐官方示例工作流（Sol-H3 双采极速版）——beta + denoise 0.55 保留底图细化
            _r_sigmas = _sigmas(model, "beta", _r_steps, _r_denoise)
            # v1.45 (2026-09-13 fix #5 画面糊成一片根因): CONST 加噪的噪声必须用真实随机噪声
            # (σ·ε+(1-σ)·x 混合), 但喂给 KSAMPLER.sample 的 noise 参数必须用空噪声!
            # 原因: CFGGuider.sample -> KSAMPLER.sample 内部会对 noise 再执行一次
            #   noise = model_sampling.noise_scaling(sigmas[0], noise, latent_image)
            #   即 latent_image + noise*sigma. 若把 CONST 已加噪的 latent 与真实噪声同时传入,
            #   会二次加噪(双重噪声), 二采从过噪起点开始, 4步去噪不足, 输出残留噪声/细节丢失,
            #   画面"糊成一片+像素化故障风". 官方 Sol-H3 DualSample 工作流二采正是用
            #   DisableNoise(Noise_EmptyNoise -> prepare_empty_noise 全零噪声) 走同一入口,
            #   此处完全对齐.
            _use_temporal = bool(temporal_chunk_tokens) and int(temporal_chunk_tokens) > 0
            # v2.02b: chunk 过小(如当开关填 1)会切成大量单 token 段, 每段都要完整跑
            # 4 步空间分块采样, 总耗时爆炸(T=107 时 107 段≈100 分钟). 低于 16 一律按 16 执行.
            if _use_temporal and int(temporal_chunk_tokens) < 16:
                print(f"[H3 Extender] v2.02 temporal_chunk_tokens={int(temporal_chunk_tokens)} 过小, "
                      f"已按 16 执行 (T~107 建议 40~60, 0=关闭)", flush=True)
                temporal_chunk_tokens = 16
            # v14.200: 删除 v14.199 的"分块二采强制锁音频"。
            # 根因不再靠锁定规避: bsai_h3_spatial_tiles.py 现在直接取第 1 块
            # 的音频预测(音频 latent 无空间维度, 各块都给出完整音频估计),
            # 不再把 N 块相位不一致的预测求平均 → 没有低频轰鸣, 音频也能照常
            # 参与二采重绘。锁定会上游 v14.196 已按步数条件处理。
            if not _use_temporal:
                _r_noise = comfy.sample.prepare_noise(samples, int(seed) + 1, None)
                _r_latent = _ff_const_add_noise(model, _r_noise, _r_sigmas, {"samples": samples}, _r_audio)
            else:
                _r_noise = None
                _r_latent = None

            # 3) DisableNoise 二采：从 CONST 加噪 latent 完整去噪（不再 prepare_noise 覆盖）
            # v1.47: 采样前主动确保 diffusion 模型驻留显存. DynamicVRAM
            # 模式下模型一采后会被完全释放(allocated≈0GB), 若依赖按需重载,
            # 21.8GB 全量加载在 24GB 卡上会假死(见 v1.47 预算注释).
            # load_model_gpu 同步加载, OOM 抛异常可走下方 fallback, 不静默卡死.
            _refine_model = model  # v14.142: 二采用模型（DynamicVRAM 时替换为 non-dynamic delegate）
            _ext_resv_orig = None  # v14.142: delegate 路径进入前的 EXTRA_RESERVED_VRAM 原值
            try:
                import torch as _torch3
                import comfy.model_management as _mm3
                # v1.54: 一采后 allocated≈3.7GB(显存碎片/cache) 不代表模型驻留——原判断
                # `allocated<1.0` 会漏判(3.75>1.0 跳过加载), 二采 0 驻留全流式,
                # 每步 21.8GB 换页 → 实测 209s/it. 改以 model.loaded_size() 判断
                # 实际权重驻留, <12GB 即主动重驻留(reserve 5.5GB 预算: 驻留 ~11-16GB,
                # 尾部 offload, 比全流式少换一半以上权重).
                _res_gb = 0.0
                try:
                    _res_gb = model.loaded_size() / 1024 ** 3
                except Exception:
                    pass
                if _res_gb < 12.0:
                    # v1.89: DynamicVRAM 模式检测——模型 is_dynamic() 时 load_models_gpu
                    # 只重新 staged(不真正驻留), 且 staged ~20GB 分配占满显存, 分块
                    # 初始化死等 staged 完成 -> 死锁(4090 实测: resident=0.0GB,
                    # 卡 0/6 Model Initializing)。dynamic 模式跳过手动重驻留,
                    # 交 DynamicVRAM 自身调度(一采同路径实测正常)。
                    # v1.89b: is_dynamic() 是 ModelPatcher 方法(model_patcher.py L403),
                    # 直接调 model.is_dynamic(), 不要取 model.model(v1.89 误写导致检测失效)。
                    try:
                        _is_dyn = bool(model.is_dynamic())
                    except Exception:
                        _is_dyn = False
                    if _is_dyn:
                        # v14.142 (2026-10-13): DynamicVRAM 二采 0 驻留全流式换页根治。
                        # 根因: DynamicVRAM 开启时一采后模型被完全卸载(allocated≈0GB),
                        # 二采交 staged 调度 = 每步 21.8GB CPU↔GPU 逐层换页 → 实测 637s/it
                        # (历史同根因: v1.54 209s、v1.87 313s、v1.90 分块 900s/步)。
                        # 修复: 用官方 get_non_dynamic_delegate()/clone(disable_dynamic=True)
                        # 生成非 dynamic delegate, 对 delegate 走标准 load_models_gpu 部分驻留
                        # (reserve 预算内驻留 + offload 尾部, 换页量减 2/3, 提速 2-3 倍)。
                        # delegate 与原 model 共享底层权重(模型缓存命中), 采样语义不变;
                        # 失败回退原路径(维持现状, 不会更糟)。
                        try:
                            _r_ws_dyn = _ws_tbl.get(round(_r_factor, 1), 2.6)
                            _r_resv_dyn = _model_gb2 - (_gpu_total_gb2 - _r_ws_dyn - 3.0 - 1.5)
                            _r_resv_dyn = max(3.0, min(8.0, _r_resv_dyn))
                            if tiled_refine:
                                _r_resv_dyn = max(_r_resv_dyn, 7.5)
                            _r_delegate_dyn = None
                            try:
                                if hasattr(model, "get_non_dynamic_delegate"):
                                    _r_delegate_dyn = model.get_non_dynamic_delegate()
                            except Exception:
                                _r_delegate_dyn = None
                            if _r_delegate_dyn is None:
                                _r_delegate_dyn = model.clone(disable_dynamic=True)
                            # v14.143 (2026-10-13): 曾以为 delegate 是 cached_patcher_init 重新
                            # 加载的全新模型对象, KJNodes 补丁(MethodType 绑定原模型 block 实例)
                            # 被 clone 复制后必然错位 -> 删掉补丁走原生 forward。实机证明这是
                            # 错误方向(v14.144 实测): 全幅 latent 中间激活暴涨到 6.35GB
                            # (allocated 18.05GB = 驻留 11.7 + 中间 6.35), Sol-Attn workspace
                            # 6.33GB 挤不下(24.38 > 23.86, 差 0.5GB), 连 sage 3.03GB 也失败,
                            # 依次降级到 pytorch attention, 二采失去稀疏加速。
                            # 参考插件(v14.82, 用户实测二采 240s/步 无雪花)恰恰是【保留
                            # KJNodes lowmem 分块 + Sol-Attn 的原 model 重驻留】: qkv GEMM 后
                            # 立即释放 h/qkv 缓冲 + minimax_head_chunks 按 head 分组, 中间
                            # 激活被压到 ~1GB 级, Sol-Attn workspace 才有空间。
                            # v14.145 正确修法: 不是删除补丁, 而是在 delegate 上【重新绑定】
                            # KJNodes 补丁到 delegate 自己的 block/attn 实例(MethodType 的
                            # self 指向 delegate 对象, 消除 clone 复制导致的错位), 并从原
                            # model 恢复 minimax_head_chunks / sol_take_forward。
                            try:
                                import sys as _sys_kn145
                                import types as _types_kn145
                                _kj_mod145 = None
                                for _m145 in list(_sys_kn145.modules.values()):
                                    _mf145 = getattr(_m145, "__file__", "") or ""
                                    if _mf145.replace("\\", "/").endswith("nodes/minimax_nodes.py"):
                                        _kj_mod145 = _m145
                                        break
                                if _kj_mod145 is None:
                                    import importlib.util as _ilu_kn145
                                    _kj_path145 = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                "..", "ComfyUI-KJNodes", "nodes", "minimax_nodes.py")
                                    if os.path.exists(_kj_path145):
                                        _kj_spec145 = _ilu_kn145.spec_from_file_location("bsai_kj_minimax145", _kj_path145)
                                        _kj_mod145 = _ilu_kn145.module_from_spec(_kj_spec145)
                                        _kj_spec145.loader.exec_module(_kj_mod145)
                                _r_deleg_diff145 = _r_delegate_dyn.get_model_object("diffusion_model")
                                _r_deleg_blocks145 = getattr(_r_deleg_diff145, "blocks", None)
                                if (_kj_mod145 is not None
                                        and getattr(_kj_mod145, "minimax_block_lowmem_forward", None)
                                        and _r_deleg_blocks145):
                                    for _bi145, _blk145 in enumerate(_r_deleg_blocks145):
                                        _r_delegate_dyn.object_patches[f"diffusion_model.blocks.{_bi145}.forward"] = \
                                            _types_kn145.MethodType(_kj_mod145.minimax_block_lowmem_forward, _blk145)
                                        _attn145 = getattr(_blk145, "attn", None)
                                        if _attn145 is not None and hasattr(_attn145, "qkv_proj"):
                                            _r_delegate_dyn.object_patches[f"diffusion_model.blocks.{_bi145}.attn.forward"] = \
                                                _types_kn145.MethodType(_kj_mod145.minimax_attn_lowmem_forward, _attn145)
                                    # 从原 model 恢复 KJNodes 写入的 transformer_options 键
                                    _r_to145 = _r_delegate_dyn.model_options.get("transformer_options", {})
                                    _r_to_orig145 = model.model_options.get("transformer_options", {})
                                    if isinstance(_r_to145, dict) and isinstance(_r_to_orig145, dict):
                                        if "minimax_head_chunks" in _r_to_orig145:
                                            _r_to145["minimax_head_chunks"] = _r_to_orig145["minimax_head_chunks"]
                                        if "sol_take_forward" in _r_to_orig145:
                                            _r_to145["sol_take_forward"] = _r_to_orig145["sol_take_forward"]
                                        # v14.179 (2026-10-23): 回退 v14.166 的 head_chunks 4->1。
                                        # 实测: v14.166 把 delegate head 分组 4->1 后, 每块走
                                        # KJNodes 分组稀疏的注意力退化成全 head dense 路径,
                                        # 8 块二采 545s/步 > v14.149(4块+head4) 399s/步。
                                        # 恢复 head 分组 4, 让 KJNodes 低显存分组生效。
                                        # (v14.166 注释称"单次并行 kernel 注意力减半"与实机不符)
                                        _r_hc166 = int(_r_to145.get("minimax_head_chunks", 4))
                                        _r_to145["minimax_head_chunks"] = 4
                                        if _r_hc166 != 4:
                                            print(f"[H3 Extender] v14.179 二采 delegate head_chunks "
                                                  f"{_r_hc166}->4 (回退 v14.166, 恢复 KJNodes 分组稀疏)")
                                    print(f"[H3 Extender] v14.145 KJNodes 低显存补丁已重建绑定到 delegate({len(_r_deleg_blocks145)} blocks)")
                                else:
                                    print(f"[H3 Extender] v14.145 KJNodes 补丁重建跳过(模块/blocks 不可用), 走原生 forward")
                            except Exception as _re145:
                                print(f"[H3 Extender] v14.145 KJNodes 补丁重建失败(回退原生 forward): {_re145}")
                            # v14.144 (2026-10-13): Sol-Attn workspace 让位——曾因原生 forward
                            # 中间激活 6.35GB 挤爆, 临时把 reserve 上调 2.5GB。v14.145 恢复
                            # KJNodes lowmem 分块(head 分组)后中间激活与 Sol-Attn workspace
                            # 同步缩小(minimax_head_chunks 使 kernel 内部暂存随 head 组缩水),
                            # 还原为参考插件标准 reserve 公式(与 v14.82 逐行一致, 实测 240s/步)。
                            # 检测 Sol-Attn 挂载键仅用于日志提示, 不再额外让位。
                            try:
                                _r_to3 = _r_delegate_dyn.model_options.get("transformer_options", {})
                                if isinstance(_r_to3, dict) and (
                                        _r_to3.get("optimized_attention_override") or _r_to3.get("sol_compose")):
                                    print(f"[H3 Extender] v14.145 Sol-Attn 已挂载, 走 KJNodes head 分组稀疏路径")
                            except Exception:
                                pass
                            try:
                                _ext_resv_orig = _mm3.EXTRA_RESERVED_VRAM
                            except Exception:
                                _ext_resv_orig = None
                            _mm3.EXTRA_RESERVED_VRAM = int(_r_resv_dyn * 1024 ** 3)
                            _mm3.load_models_gpu([_r_delegate_dyn])
                            _torch3.cuda.synchronize()
                            try:
                                _res2d = _r_delegate_dyn.loaded_size() / 1024 ** 3
                                print(f"[H3 Extender] v14.145 DynamicVRAM 二采改用 non-dynamic delegate 驻留(KJNodes补丁重建): "
                                      f"resident={_res2d:.1f}GB / total={_r_delegate_dyn.model_size()/1024**3:.1f}GB "
                                      f"reserve={_r_resv_dyn:.1f}GB")
                            except Exception:
                                pass
                            _refine_model = _r_delegate_dyn
                        except Exception as _de142:
                            _refine_model = model
                            print(f"[H3 Extender] v14.145 non-dynamic delegate 创建失败, 回退 DynamicVRAM 流式: {_de142}")
                        if _refine_model is model:
                            print(f"[H3 Extender] DynamicVRAM 模式: 跳过手动重驻留, 交 DynamicVRAM staged 调度")
                        else:
                            print(f"[H3 Extender] v14.145 delegate 已接管二采采样模型(非 DynamicVRAM 驻留路径)")
                    else:
                        # v1.87: 分块二采也走重驻留。v1.68 曾对 tile_count>1 跳过重载
                        # 导致二采 0 loaded + 20GB 全流式换页(实测 313s/it, 极速-VDN
                        # 二采 3步x4tile ≈ 60min)。实测 reserve 8.0 预算下 19.5GB 基座
                        # 可驻留 ~13.6GB + offload ~6GB, 换页量减少 2/3, 分块采样提速
                        # 2-3 倍。prepare(CONST加噪)在 load 之前已完成, 不会被卸。
                        # v1.65: 二采前驻留控制——先卸载再按 reserve 重载, 让加载器按
                        # reserve 预算重新平衡驻留量, 给 Sol-Attn workspace 让位.
                        # 实测 19:34 x2.0: 直接 load_models_gpu 全量驻留 21.72GB,
                        # Sol-Attn kernel 603MB workspace 分不出 → OOM.
                        # reserve = 模型 - (total - ws - 3GB 余量 - 1.5GB conds):
                        #   x2.0(ws4.5): ~6.8GB -> 驻留 ~15GB
                        #   x1.5(ws2.6): ~4.9GB -> 驻留 ~17GB
                        #   x1.0(ws1.5): ~4.2GB -> 驻留 ~17.5GB
                        try:
                            _ws_need2 = _ws_tbl.get(round(_r_factor, 1), 2.6)
                            _r_reserve_gb = _model_gb2 - (_gpu_total_gb2 - _ws_need2 - 3.0 - 1.5)
                            _r_reserve_gb = max(3.0, min(8.0, _r_reserve_gb))
                            # v1.88: 分块二采时 ComfyUI 按全幅估算 workspace(ws_need2)并判断
                            # free < ws+2GB 就卸载驻留模型(实测: reserve5.0->驻留16.3GB free5.2GB
                            # <6.5GB -> Unloaded到0 loaded -> 分块forward死锁0/3)。
                            # 分块时提高 reserve 下限至 7.5GB: 驻留~14.3GB + offload~5.2GB +
                            # free~7.2GB > ws6.5GB, ComfyUI 不再卸载, 分块forward正常换页。
                            if tiled_refine:
                                _r_reserve_gb = max(_r_reserve_gb, 7.5)
                            _ff_unregister_model(model, label="二采-reserve-branch")
                            _mm3.EXTRA_RESERVED_VRAM = int(_r_reserve_gb * 1024 ** 3)
                        except Exception:
                            _r_reserve_gb = 8.0 if tiled_refine else 5.5
                            _ff_unregister_model(model, label="二采-reserve-fallback")
                            _mm3.EXTRA_RESERVED_VRAM = int(_r_reserve_gb * 1024 ** 3)
                        print(f"[H3 Extender] Refine 二采前 DiT 驻留 {_res_gb:.1f}GB < 12GB, 重新驻留到 VRAM (reserve->{_r_reserve_gb:.1f}GB) ...")
                        _mm3.load_models_gpu([model])
                        _torch3.cuda.synchronize()
                        try:
                            _res2 = model.loaded_size() / 1024 ** 3
                            print(f"[H3 Extender] Refine 二采前 DiT 驻留: resident={_res2:.1f}GB / total={model.model_size()/1024**3:.1f}GB")
                        except Exception:
                            pass
                        # v1.65: 验证 Sol-Attn workspace 空间, 不足时醒目提示(采样走
                        # lowvram 换页兜底, 不会静默 OOM; 下次跑会在预算区提前降级).
                        try:
                            import torch as _torch65
                            _f65, _t65 = _torch65.cuda.mem_get_info()
                            _free65 = _f65 / 1024 ** 3
                            _ws65 = _ws_tbl.get(round(_r_factor, 1), 2.6)
                            if _free65 < _ws65 + 2.0:
                                print(f"[H3 Extender] Refine 警告: 二采 workspace 空间不足 "
                                      f"(free={_free65:.1f}GB < ws {_ws65:.1f}GB+2GB), "
                                      f"采样将靠 lowvram 换页兜底, 建议下次降低 refine_upscale_factor")
                        except Exception:
                            pass
            except Exception as _lg2:
                print(f"[H3 Extender] Refine 主动加载模型失败, 走 DynamicVRAM 按需流式: {_lg2}")
            _r_sampler = comfy.samplers.sampler_object(str(sampler_name))
            # v1.48 分块二采(默认关): 长空间轴分块, 激活/attention workspace 随 tile_count
            # 线性下降. 算法移植自 MiniMaxH3 Director spatial_tiled_sampling.py (Apache-2.0).
            # 包装器对非 packed latent / 小尺寸自动回退全帧, 不破坏既有流程.
            _r_restore_tiles = None
            if tiled_refine and refine_mem_mode != "global":
                try:
                    import os as _os_t, importlib.util as _ilu_t
                    _tiles_path = _os_t.path.join(_os_t.path.dirname(_os_t.path.abspath(__file__)), "bsai_h3_spatial_tiles.py")
                    _tiles_spec = _ilu_t.spec_from_file_location("bsai_h3_spatial_tiles", _tiles_path)
                    _tiles_mod = _ilu_t.module_from_spec(_tiles_spec)
                    _tiles_spec.loader.exec_module(_tiles_mod)
                    _r_tiles_n164 = _ff_auto_refine_tile_count(samples, tile_count, tile_overlap)
                    _r_restore_tiles = _tiles_mod.wrap_sampler_spatial_tiles(
                        _r_sampler, n_tiles=_r_tiles_n164, overlap_pixels=int(tile_overlap))
                    print(f"[H3 Extender] Refine 分块二采已启用: n_tiles={_r_tiles_n164} overlap={tile_overlap}px (v14.181 恢复 128px 接缝融合)")
                except Exception as _te_t:
                    print(f"[H3 Extender] Refine 分块包装失败(回退全帧): {_te_t}")
                    _r_restore_tiles = None
            # v1.56: 二采挂耗时诊断 callback——一采 callback 是外层函数局部变量,
            # 二采取不到, 且二采 callback=None 无法定位第 4 步固定 ~420s 的瓶颈.
            _r_cb_t0 = {"t": None}
            def _r_step_cb(step, x0, x, total):
                try:
                    import time as _t56
                    _now56 = _t56.time()
                    if _r_cb_t0["t"] is not None:
                        print(f"[H3 Extender] refine耗时诊断: step={step+1}/{total} 距上步 {_now56-_r_cb_t0['t']:.1f}s")
                    _r_cb_t0["t"] = _now56
                except Exception:
                    pass
                # v1.62: Sol-Attn sigma 门修复(工作流 end_percent 0.9->1.0)已验证:
                # step4 428s -> 134s. 原 sol_attn 计数诊断因模块以 spec 方式加载
                # 无法共享 _stats, 移除, 保留耗时诊断即可.
            # v14.148 (2026-10-13): 方案A —— Sol-Attn kernel 病态规模门。
            # 独立基准实测(comfy_kitchen ck.sol_attn, RTX 5090 24GB, 与实机同参):
            #   n=218,280 -> 0.97s / n=293,760 -> 0.70s (健康)
            #   n=440,640 -> >45s / n=873,120 topk -> >600s / n=873,120 dense -> >60s (病态)
            # 病态与 topk routing 无关, 是 kernel 在 n>=~440k 时超线性恶化.
            # 二采整段 latent 120x68x107 = 873,120 tokens 必命中病态区 -> 第1步 75min 未完成.
            # 门: 单段 latent token > 阈值时向 transformer_options 注入 sol_max_tokens,
            # Sol-Attn make_override 读取后直接 dense 回退(KJNodes 分组+SageAttention,
            # 对齐参考插件 v14.82 实测 240s/步 无雪花). 一采 218k 低于阈值不受影响.
            _REFINE_MAX_SOL_TOKENS = 350000
            try:
                _r_tok_gate = 0
                _r_m_gate, _ = _ff_extract_members(samples)
                if _r_m_gate is not None and getattr(_r_m_gate[0], "ndim", 0) >= 4:
                    _r_tok_gate = int(_r_m_gate[0].shape[2]) * int(_r_m_gate[0].shape[-2]) * int(_r_m_gate[0].shape[-1])
            except Exception:
                _r_tok_gate = 0
            # v14.164 (2026-10-22 fix #v14.173): 方案A — 先分块再决定 dense 降级。
            # 旧顺序(v14.148 先注入 sol_max_tokens -> v14.164 后分块)导致分块成功后
            # dense 门仍留在 transformer_options 里, 每个 262k token 的 tile 强制
            # 走 dense attention (KJNodes+SageAttention) 而非稀疏 Sol-Attn —— 实机
            # 4090 二采每步 411s, 远高于稀疏 0.7s/块 × 6 块 = ~4.2s 的理论值.
            # 修复: 先做 v14.164 分块决策, 再基于"是否已分块"决定要不要给整段注入
            # dense 门. 分块成功时每块 ~262k tokens 已在 Sol-Attn 健康区, 不需要
            # dense 回退. 同时显式清理 transformer_options 里可能从上个 clip 残留
            # 的 sol_max_tokens.
            if _r_tok_gate > _REFINE_MAX_SOL_TOKENS and _r_restore_tiles is None and refine_mem_mode != "global":
                try:
                    import os as _os_t3, importlib.util as _ilu_t3
                    _tiles_path3 = _os_t3.path.join(_os_t3.path.dirname(_os_t3.path.abspath(__file__)), "bsai_h3_spatial_tiles.py")
                    _tiles_spec3 = _ilu_t3.spec_from_file_location("bsai_h3_spatial_tiles", _tiles_path3)
                    _tiles_mod3 = _ilu_t3.module_from_spec(_tiles_spec3)
                    _tiles_spec3.loader.exec_module(_tiles_mod3)
                    _r_restore_tiles = _tiles_mod3.wrap_sampler_spatial_tiles(
                        _r_sampler, n_tiles=_ff_auto_refine_tile_count(samples, 4, tile_overlap), overlap_pixels=int(tile_overlap))
                    print(f"[H3 Extender] v14.181 方案A: latent tokens={_r_tok_gate:,} > 阈值, "
                          f"自动启用分块二采 overlap={tile_overlap}px, n_tiles 按请求值(不扩块) "
                          f"(v14.149 固定 4 块 ~334k/块灰色区 399s/步 -> v14.164 扩 8 块 545s/步 反而更慢 -> v14.179 回退 -> v14.181 恢复 128px 接缝))")
                    # v14.173: 分块成功 —— 显式清理 transformer_options 里的 sol_max_tokens.
                    # 防止同一个 _refine_model 对象被二次调用时(链式 clip) 残留
                    # 上次注入的 dense 门, 把本该稀疏的 tile 强制降级.
                    try:
                        _r_to_clean = _refine_model.model_options.get("transformer_options", {})
                        if isinstance(_r_to_clean, dict) and "sol_max_tokens" in _r_to_clean:
                            _r_to_clean.pop("sol_max_tokens", None)
                            print(f"[H3 Extender] v14.173 清理残留 sol_max_tokens="
                                  f"已移除 (分块二启用, tile 稀疏保留)")
                    except Exception as _ec173:
                        print(f"[H3 Extender] v14.173 清理 sol_max_tokens 失败(可忽略): {_ec173}")
                except Exception as _te_t3:
                    print(f"[H3 Extender] v14.149 自动分块失败(走 v14.148 dense 回退门): {_te_t3}")
            # v14.148 (2026-10-13): 方案A — Sol-Attn kernel 病态规模门.
            # 独立基准实测(comfy_kitchen ck.sol_attn, RTX 5090 24GB, 与实机同参):
            #   n=218,280 -> 0.97s / n=293,760 -> 0.70s (健康)
            #   n=440,640 -> >45s / n=873,120 topk -> >600s / n=873,120 dense -> >60s (病态)
            # 病态与 topk routing 无关, 是 kernel 在 n>=~440k 时超线性恶化.
            # 只有在 v14.164 分块 **失败或被跳过** 时才触发 dense 降级 —— 此时整段
            # latent tokens 命中病态区, 才需要强制 dense 回退 (KJNodes 分组+
            # SageAttention). 分块成功时 tile 级 token 已在健康区, 稀疏 Sol-Attn
            # 直接跑通, 不注入 sol_max_tokens.
            if _r_tok_gate > _REFINE_MAX_SOL_TOKENS and _r_restore_tiles is None:
                try:
                    _r_to_gate = _refine_model.model_options.get("transformer_options", {})
                    if isinstance(_r_to_gate, dict):
                        _r_to_gate["sol_max_tokens"] = _REFINE_MAX_SOL_TOKENS
                        print(f"[H3 Extender] v14.148 方案A: 二采 latent tokens={_r_tok_gate:,} > "
                              f"{_REFINE_MAX_SOL_TOKENS:,} 且未启用分块, "
                              f"Sol-Attn 已降级 dense(KJNodes 分组+SageAttention), "
                              f"绕开病态 kernel(基准: 293k=0.7s 健康 / 440k>45s / 873k>600s)")
                except Exception as _eg:
                    print(f"[H3 Extender] v14.148 方案A 注入 sol_max_tokens 失败(可忽略): {_eg}")
            elif _r_restore_tiles is not None:
                print(f"[H3 Extender] v14.148 方案A: 二采 latent tokens={_r_tok_gate:,} > "
                      f"{_REFINE_MAX_SOL_TOKENS:,}, 分块二启用 — tile 级 token 在健康区, "
                      f"Sol-Attn 稀疏保留")
            else:
                print(f"[H3 Extender] v14.148 方案A: 二采 latent tokens={_r_tok_gate:,} <= "
                      f"{_REFINE_MAX_SOL_TOKENS:,}, Sol-Attn 稀疏保留(健康区)")
            # v14.153 (2026-10-20): 二采省显存模式 global —— 移植 selflift-Avatar
            # (commit 5b93b6c) global-context 路径, 暂存源码 vendor/selflift_avatar/。
            # 与 spatial(v14.149 4 块分块)互斥: global 跳过空间分块, 对二采模型加
            # tiled_model() 全序列包装 —— attention 全序列一次跑(无接缝/背景膨胀,
            # query 永不见裁剪), norm/proj/MLP 按 token_chunk 分块压激活显存。
            # 与本插件现有机制协同(已验证源码级兼容):
            #   - KJNodes head 分组(object_patches ...attn.forward): vendor
            #     _native_attention_chunked_mlp 调 block.attn(...) 仍走 KJNodes 路径;
            #   - Sol-Attn override: vendor 判为 unknown override -> 自动回退 global
            #     纯 dense 分块路径(use_stream/use_ram 强制关, 上游语义), v14.148
            #     sol_max_tokens 门保持注入(全序列 873k 仍需 dense 回退防病态 kernel);
            #   - v14.145 delegate(KJNodes 补丁重建): wrapper 在 DIFFUSION_MODEL 层,
            #     object_patches 同为 block/attn 层, 叠加不冲突。
            # 包装失败时打印警告并回退 spatial 行为(此时 v14.149 自动分块已因
            # refine_mem_mode 被跳过, 需补一次分块包装保底)。
            _r_global_fallback_tiles = False
            if refine_mem_mode == "global":
                try:
                    import os as _os_g, importlib as _ilg
                    import sys as _sys_g
                    _venv_dir = _os_g.path.join(_os_g.path.dirname(_os_g.path.abspath(__file__)), "vendor")
                    if _venv_dir not in _sys_g.path:
                        _sys_g.path.insert(0, _venv_dir)
                    _gt = _ilg.import_module("selflift_avatar.h3_global_tiling")
                    _r_original_refine_model = _refine_model
                    _refine_model = _gt.tiled_model(_refine_model, 4096)
                    _fb = getattr(_refine_model, "_selflift_global_fallback", None)
                    print(f"[H3 Extender] v14.153 二采省显存模式: global 全上下文路径已包装 "
                          f"(token_chunk=4096, 无空间分块)"
                          + (f", 上游回退: {_fb}(检测到自制注意力 override, 走全序列 attention+分块 MLP)" if _fb else ""))
                    if _fb:
                        # v14.208: tiled_model 成功但被检测出 attention override,
                        # 自动回退到 dense full-sequence attention——1.3M tokens 的
                        # dense attention workspace 在 24GB 卡上 OOM.
                        # 恢复原模型 + 切 spatial 分块 (tile 级 token 在 Sol-Attn 健康区).
                        _refine_model = _r_original_refine_model
                        del _r_original_refine_model
                        refine_mem_mode = "spatial"
                        _r_global_fallback_tiles = True
                        print(f"[H3 Extender] v14.208 global 回退 attention override({_fb}), "
                              f"恢复原模型 + 切 spatial 分块以避免全序列 attention OOM")
                        # tiled_model 内部 model.clone() 会创建权重副本 / cast buffer,
                        # 显式 GC + empty_cache 回收 VRAM, 防止后续 spatial 分块 forward
                        # 因碎片伪 OOM (allocated 低但 free=0).
                        try:
                            import gc as _gc208, torch as _t208
                            _gc208.collect()
                            _t208.cuda.empty_cache()
                        except Exception:
                            pass
                except Exception as _eg15:
                    print(f"[H3 Extender] v14.153 global 包装失败, 回退 spatial 分块保底: {_eg15}")
                    refine_mem_mode = "spatial"
                    _r_global_fallback_tiles = True
            if _r_global_fallback_tiles and _r_tok_gate > _REFINE_MAX_SOL_TOKENS and _r_restore_tiles is None:
                try:
                    import os as _os_t4, importlib.util as _ilu_t4
                    _tiles_path4 = _os_t4.path.join(_os_t4.path.dirname(_os_t4.path.abspath(__file__)), "bsai_h3_spatial_tiles.py")
                    _tiles_spec4 = _ilu_t4.spec_from_file_location("bsai_h3_spatial_tiles", _tiles_path4)
                    _tiles_mod4 = _ilu_t4.module_from_spec(_tiles_spec4)
                    _tiles_spec4.loader.exec_module(_tiles_mod4)
                    _r_restore_tiles = _tiles_mod4.wrap_sampler_spatial_tiles(
                        _r_sampler, n_tiles=4, overlap_pixels=int(tile_overlap))
                    print(f"[H3 Extender] v14.180 回退保底: 已补启用 spatial 分块 n_tiles=4 overlap={tile_overlap}px")
                    # v14.208: 与 v14.173 同逻辑——spatial fallback 装好后,
                    # 若 transformer_options 里有之前注入的 sol_max_tokens (来自 v14.148),
                    # 必须清掉, 否则每个 tile (~262k tokens) 被强制 dense attention,
                    # 比稀疏 Sol-Attn 慢 60x 且可能再次 OOM.
                    try:
                        _r_to_clean4 = _refine_model.model_options.get("transformer_options", {})
                        if isinstance(_r_to_clean4, dict) and "sol_max_tokens" in _r_to_clean4:
                            _r_to_clean4.pop("sol_max_tokens", None)
                            print(f"[H3 Extender] v14.208 spatial fallback: 清理残留 sol_max_tokens="
                                  f"已移除 (tile 级 token 在健康区, Sol-Attn 稀疏保留)")
                    except Exception as _ec208:
                        pass
                except Exception as _te_t4:
                    print(f"[H3 Extender] v14.153 回退补分块失败(仅 v14.148 dense 门兜底): {_te_t4}")
            _r_guider = _BasicGuider(_refine_model)
            _r_guider.set_conds(conditioning)
            # v1.64: 恢复 v1.59 驻留补丁(v1.61 改诊断时误删)——二采采样前
            # 跳过 sampler_helpers._prepare_sampling 的 load_models_gpu/free_memory,
            # 防止 prepare 按全幅 latent 估算把刚驻留的模型全卸(0.00 MB remains,
            # 全流式换页 21.8GB/步). v1.63 已修分块+refs mismatch, 分块重新启用.
            # 驻留量由 reserve(分块 8GB/非分块 5.5GB) 决定, 换页只限 offload 尾部.
            import comfy.sampler_helpers as _sh59
            _bsai_orig_prepare = _sh59._prepare_sampling
            def _bsai_refine_prepare(model, noise_shape, conds, model_options=None, force_full_load=False, force_offload=False):
                try:
                    # 模型已驻留, 跳过 load_models_gpu 防 free_memory 全卸
                    return model.model, conds, []
                except Exception as _pe59:
                    print(f"[H3 Extender] v1.64 跳过prepare-load失败, 回退原路径: {_pe59}")
                    return _bsai_orig_prepare(model, noise_shape, conds, model_options=model_options,
                                              force_full_load=force_full_load, force_offload=force_offload)
            # v14.209: 总是安装驻留补丁, 包括分块/spatial fallback.
            # v1.65 曾因 DynamicVRAM 分块驻留 OOM 跳过分块路径——但 v14.142
            # 已用 clone(disable_dynamic=True) 生成 non-dynamic delegate,
            # 彻底消除 DynamicVRAM staged 全量加载根因.
            # 原 guard `if not (tile_count and int(tile_count) > 1)` 还有两个 bug:
            #   a) tile_count 默认就是 4(函数签名), 导致非分块场景补丁也装不上;
            #   b) 即使 tiled_refine=False 且 tile_count=4, 用户走 v14.208 spatial
            #      fallback 装了 _r_restore_tiles 但驻留仍被跳过, 每 step 从 0MB
            #      全流式换页 21GB -> 797s/it.
            # 修复后: 跳过原生 prepare 的 load_models_gpu/free_memory, 保持已驻留
            # 的 13.8GB 在 GPU, 仅 offload 尾部 6.8GB 换页 -> 预计 200-300s/it.
            _sh59._prepare_sampling = _bsai_refine_prepare
            print(f"[H3 Extender] v14.209 驻留补丁已安装 (tile_count={tile_count}, "
                  f"跳过原生 prepare 的全卸, 保持已驻留权重在 GPU)")
            # v1.91: 解除 torch allocator 人为 16GB fraction 限制——运行中
            # 某库调用过 set_per_process_memory_fraction, 使 torch 可用上限
            # 仅 16GB, 二采全帧 staged 15.25GB + 4K workspace 3.05GB = 18.3GB
            # 被判 OOM 回退一采. reset 1.0 后 torch 用满物理 23.86GB,
            # 全帧二采不再 OOM. LLM 全在 CPU, 无其他显存用户, reset 安全.
            # v1.93 (2026-09-16): 释放 aimdo VRAMBuffer(cast buffer, 一采加载期
            # 累积至 ~8.5GB 后常驻不释放). 主二采全程 _aimdo_disabled(), 该缓冲
            # 在二采阶段纯占显存——释放后 factor 2.0 全帧二采账本:
            # staged 15.4GB + workspace 3.08GB = 18.5GB < 23.86GB, 不再 OOM.
            try:
                import comfy.model_management as _mm93
                _released93 = 0
                for _k93 in list(_mm93.STREAM_AIMDO_CAST_BUFFERS):
                    try:
                        _buf93 = _mm93.STREAM_AIMDO_CAST_BUFFERS.pop(_k93)
                        del _buf93
                        _released93 += 1
                    except Exception:
                        pass
                if _released93:
                    import gc as _gc93
                    import torch as _torch93
                    _gc93.collect()
                    _torch93.cuda.synchronize()
                    _torch93.cuda.empty_cache()
                    print(f"[H3 Extender] v1.93 已释放 aimdo cast buffer x{_released93} (~8GB VRAM 回归可用)")
                else:
                    print(f"[H3 Extender] v1.93 无 aimdo cast buffer 需释放")
            except Exception as _e93:
                print(f"[H3 Extender] v1.93 释放 aimdo cast buffer 失败: {_e93}")
            try:
                import torch as _t91
                _cur_frac91 = _t91.cuda.get_per_process_memory_fraction()
                _t91.cuda.set_per_process_memory_fraction(1.0)
                if _cur_frac91 < 1.0:
                    print(f"[H3 Extender] v1.91 解除 fraction 限制: {_cur_frac91:.3f} -> 1.0 (二采可用 23.86GB)")
                else:
                    print(f"[H3 Extender] v1.91 fraction 已是 1.0, 无需解除")
            except Exception as _e91:
                print(f"[H3 Extender] v1.91 fraction reset 失败: {_e91}")
            try:
                if _use_temporal:
                    # v2.02 时间分块二采: 沿 T 切段, 逐段走已有(空间分块)采样器,
                    # 重叠区 denoise_mask 冻结 + smoothstep 接管. 见 bsai_h3_temporal_chunks.py
                    import os as _os_tc, importlib.util as _ilu_tc
                    _tc_path = _os_tc.path.join(_os_tc.path.dirname(_os_tc.path.abspath(__file__)), "bsai_h3_temporal_chunks.py")
                    _tc_spec = _ilu_tc.spec_from_file_location("bsai_h3_temporal_chunks", _tc_path)
                    _tc = _ilu_tc.module_from_spec(_tc_spec)
                    _tc_spec.loader.exec_module(_tc)
                    _mem_full, _was_nested_tc = _ff_extract_members(samples)
                    _vid_full = _mem_full[0]
                    _aud_full = _mem_full[1]
                    _T_full = int(_vid_full.shape[2])
                    _segs = _tc.plan_temporal_segments(_T_full, int(temporal_chunk_tokens), int(temporal_overlap_tokens))
                    if len(_segs) <= 1:
                        print(f"[H3 Extender] v2.02 时间分块: T={_T_full} <= chunk, 退化为整段二采")
                    else:
                        print(f"[H3 Extender] v2.02 时间分块二采: T={_T_full} chunk={temporal_chunk_tokens} "
                              f"overlap={temporal_overlap_tokens} -> {len(_segs)} 段 {_segs}", flush=True)
                    _acc_v = None
                    for _ki, (_st, _et) in enumerate(_segs):
                        _cv, _ca = _tc.slice_nested_temporal(_mem_full, _st, _et)
                        _ov_here = 0
                        _mask_ki = None
                        if _acc_v is not None:
                            _ov_here = max(0, int(_acc_v.shape[2]) - _st)
                            _ov_here = min(_ov_here, int(_cv.shape[2]))
                        if _ov_here > 0:
                            _cv = _cv.clone()
                            _cv[:, :, :_ov_here] = _acc_v[:, :, _st:_st + _ov_here]
                            _mask_ki, _lock_n, _ = _tc.build_temporal_mask(
                                int(_cv.shape[2]), _ov_here, dtype=_cv.dtype, device=_cv.device)
                        else:
                            _lock_n = 0
                        _chunk_base = comfy.nested_tensor.NestedTensor((_cv, _ca))
                        _chunk_noise = comfy.sample.prepare_noise(_chunk_base, int(seed) + 1 + _ki, None)
                        _chunk_latent = _ff_const_add_noise(_refine_model, _chunk_noise, _r_sigmas,
                                                            {"samples": _chunk_base}, _r_audio)
                        # 加噪后把整个重叠区重填为上一段干净结果:
                        # 锁区(mask=0)采样器原样保留; 过渡区(0<mask<1) KSamplerX0Inpaint
                        # 按 out*m + latent_image*(1-m) 混合, 若保留加噪底则高比例噪声
                        # 直接混进发布结果(VAE 解码后=马赛克横带), 必须同为干净内容。
                        if _lock_n > 0:
                            _cl_members, _ = _ff_extract_members(_chunk_latent["samples"])
                            _cl_members[0][:, :, :_ov_here] = _acc_v[:, :, _st:_st + _ov_here]
                            _chunk_latent["samples"] = _ff_wrap_members(_cl_members, _was_nested_tc)
                            _a_part = _chunk_latent["samples"].tensors[1]
                            # v14.179 (2026-10-23): 音频掩码跟随 refine_audio_denoise,
                            # 不再无条件锁定。旧代码此处永远 mask=0(保持一采音频), 会
                            # 把"直播配音高清"档(音频≥12步+音频重绘0.7)的二采音频精修
                            # 覆盖回锁定, 导致分块二采下配音仍乱/含混。audio_denoise>=0.5
                            # 时音频参与二采重绘(mask=1), <0.5 时锁定(mask=0)。
                            if float(_r_audio) >= 0.5:
                                _amask = torch.ones((1, 1, 1, int(_a_part.shape[-1])),
                                                    dtype=_mask_ki.dtype, device=_a_part.device)
                            else:
                                _amask = torch.zeros((1, 1, 1, int(_a_part.shape[-1])),
                                                    dtype=_mask_ki.dtype, device=_a_part.device)
                            _chunk_latent["noise_mask"] = comfy.nested_tensor.NestedTensor((_mask_ki, _amask))
                        with _aimdo_disabled():
                            _chunk_out = _r_guider.sample(
                                comfy.sample.prepare_empty_noise(_chunk_latent["samples"]),
                                _chunk_latent["samples"],
                                _r_sampler,
                                _r_sigmas,
                                denoise_mask=_chunk_latent.get("noise_mask"),
                                callback=_r_step_cb,
                                disable_pbar=not comfy.utils.PROGRESS_BAR_ENABLED,
                                seed=int(seed) + 1 + _ki,
                            )
                        _out_mem, _ = _ff_extract_members(_chunk_out)
                        _acc_v = _tc.merge_guarded(_acc_v, _out_mem[0], _st, _lock_n)
                        print(f"[H3 Extender] v2.02 时间分块: 段 {_ki+1}/{len(_segs)} "
                              f"[{_st},{_et}) 完成, 累计 T={_acc_v.shape[2]}", flush=True)
                    _r_samples = _ff_wrap_members([_acc_v, _aud_full], _was_nested_tc)
                else:
                    with _aimdo_disabled():
                        _r_samples = _r_guider.sample(
                        comfy.sample.prepare_empty_noise(samples),
                        _r_latent["samples"],
                        _r_sampler,
                        _r_sigmas,
                        denoise_mask=_r_latent.get("noise_mask"),
                        callback=_r_step_cb,
                        disable_pbar=not comfy.utils.PROGRESS_BAR_ENABLED,
                        seed=int(seed) + 1,
                    )
            finally:
                try:
                    _sh59._prepare_sampling = _bsai_orig_prepare
                except Exception:
                    pass
                if _r_restore_tiles is not None:
                    try:
                        _r_restore_tiles()
                    except Exception:
                        pass
                # v14.142: 二采完成后卸载 non-dynamic delegate, 恢复 EXTRA_RESERVED_VRAM
                # 到进入前原值, 避免 delegate 驻留残留挤压下一 CLIP 一采的 DynamicVRAM
                # staged 空间. 原 dynamic model 交给 DynamicVRAM 自身调度.
                # v2.55c: ComfyUI 无 unload_model() API (仅 unload_model_and_clones, 且会
                # 连带卸载同 clone_base_uuid 的原 dynamic DiT, 不可用), 旧调用静默 no-op,
                # delegate 的 GPU 驻留量化权重跨 clip 泄漏(二采前 device_free 逐 clip
                # 下滑), 最终 TE 加载时 ComfyUI 标准路径对 delegate 执行
                # partially_load->unpatch_model->self.model.to(cpu) 触发 QuantizedTensor
                # 原生 access violation。修复: 直接从 current_loaded_models 摘除 delegate
                # 的 LoadedModel, 释放本地引用 + GC, 让 GPU 量化权重真正回收, 不再触碰 .to()。
                try:
                    if _refine_model is not model:
                        try:
                            from comfy.model_management import current_loaded_models as _r_clm
                            for _ri in range(len(_r_clm) - 1, -1, -1):
                                if getattr(_r_clm[_ri], "model", None) is _refine_model:
                                    _r_clm.pop(_ri)
                                    break
                        except Exception:
                            pass
                        _refine_model = model
                        _r_delegate_dyn = None
                        try:
                            import gc as _gc
                            _gc.collect()
                            _mm3.soft_empty_cache(force=True)
                        except Exception:
                            pass
                    if _ext_resv_orig is not None:
                        try:
                            _mm3.EXTRA_RESERVED_VRAM = _ext_resv_orig
                        except Exception:
                            pass
                except Exception:
                    pass
                # v14.148: 清理二采注入的 sol_max_tokens 门, 防止残留影响后续 CLIP 一采
                # (一采 218k 本就不会触发, 但保持模型状态干净).
                try:
                    _r_to_clean = model.model_options.get("transformer_options", {})
                    if isinstance(_r_to_clean, dict) and "sol_max_tokens" in _r_to_clean:
                        _r_to_clean.pop("sol_max_tokens", None)
                except Exception:
                    pass
            samples = _r_samples.to(comfy.model_management.intermediate_device())
            print(f"[H3 Extender] Refine 双采完成: clip={clip_index}")
        except torch.cuda.OutOfMemoryError as _oom:
            # v1.43 (2026-09-13 fix #4): OOM fallback 不再 unload_all_models()!
            # v1.37 的 fallback 每次 unload_all_models() 都把 diffusion
            # 推入 full lowvram 模式 (0 MB loaded, 20 GB offloaded),
            # 导致 fallback 本身也 OOM.
            #
            # v1.43 策略: diffusion 保持 loaded, 只清 3D upscaler 缓存
            # + GC + empty_cache, 然后用备份的一采原始 samples (60x34)
            # 重跑二采. 原始尺寸 attention workspace ~1.5GB, 加上
            # 已加载的 diffusion ~20GB, 总计 ~22GB 能装进 24GB 卡.
            print(f"[H3 Extender] Refine OOM: {_oom}")
            print(f"[H3 Extender] 自动 fallback (v1.43 保留diffusion)")
            import gc as _gc
            import comfy.model_management as _mm
            import torch as _torch
            _gc.collect()
            # 清 3D upscaler 缓存释放 VRAM
            if _FF_UPSCALER_MOD is not None:
                try:
                    _cache = getattr(_FF_UPSCALER_MOD, "MODEL_CACHE", None)
                    if isinstance(_cache, dict) and _cache:
                        for _k, _m in list(_cache.items()):
                            try:
                                _m.to("cpu")
                            except Exception:
                                pass
                            del _m
                            del _cache[_k]
                except Exception:
                    pass
            _gc.collect()
            _mm.soft_empty_cache(force=True)
            _torch.cuda.synchronize()
            _torch.cuda.empty_cache()
            try:
                _torch.cuda.ipc_collect()
            except Exception:
                pass
            _torch.cuda.synchronize()
            _torch.cuda.empty_cache()
            # v1.43: 如果有备份的一采原始 samples, 直接用它们重跑
            # (跳过放大, attention workspace 最小). 没有备份时,
            # 尝试用当前 (放大后) samples 重跑 (3D upscaler 已清,
            # 可能腾出足够 VRAM).
            _fb_samples = _samples_pre_upscale if _samples_pre_upscale is not None else samples
            # v1.92 (2026-09-16): 主二采全帧 OOM 时, 不再无条件卸载重载——
            # DynamicVRAM 下卸载重载实测把模型 staged 到 21.36GB, 再加
            # 2.24GB workspace 二次 OOM(5090 v1.91 实测: 15.40+3.08 后
            # fallback 21.36+2.24 仍 OOM). 策略改为:
            #   1. 保持当前 staged 状态(驻留>2GB 时绝不卸载);
            #   2. 若主二采是全帧(v1.90 极速-VDN 强制关分块), 降级安装
            #      分块包装器重跑放大版——x2.0 画质完整, 分块 workspace
            #      ~1.1GB + staged ~15.4GB < 24GB 可跑(4090 实测 374s/步);
            #   3. 仅当模型已被全卸(<2GB)或分块包装失败时, 才用原始尺寸
            #      (x1.0) 兜底, 绝不再回退到一采无增强结果.
            _fb_use_tiles = False
            try:
                if not (tile_count and int(tile_count) > 1):
                    import os as _os_t2, importlib.util as _ilu_t2
                    _tiles_path2 = _os_t2.path.join(_os_t2.path.dirname(_os_t2.path.abspath(__file__)), "bsai_h3_spatial_tiles.py")
                    _tiles_spec2 = _ilu_t2.spec_from_file_location("bsai_h3_spatial_tiles", _tiles_path2)
                    _tiles_mod2 = _ilu_t2.module_from_spec(_tiles_spec2)
                    _tiles_spec2.loader.exec_module(_tiles_mod2)
                    _r_tiles_n164b = _ff_auto_refine_tile_count(samples, tile_count if tile_count else 4, tile_overlap)
                    _r_restore_tiles = _tiles_mod2.wrap_sampler_spatial_tiles(
                        _r_sampler, n_tiles=_r_tiles_n164b, overlap_pixels=int(tile_overlap))
                    _fb_use_tiles = True
                    print(f"[H3 Extender] v1.92 fallback: 降级分块重跑放大版 n_tiles={_r_tiles_n164b} (v14.164 健康区自适应)")
            except Exception as _te2:
                _fb_use_tiles = False
                print(f"[H3 Extender] v1.92 fallback 分块包装失败, 用原始尺寸兜底: {_te2}")
            _fb_use = samples if _fb_use_tiles else _fb_samples
            # v14.207: fallback 用一采 34x60 重跑时, PackedLayout 会按输入 x 的空间网格
            # 给 keyframe cond 预留行数, 而 _cond_video_rows 按 keyframe latent 的实际
            # 尺寸 patchify —— v14.162 已把它们放大到二采 68x120, 两者差 4 倍, 首步前向
            # 直接 shape mismatch: [51648,96] vs [14928,96]。重跑前把 keyframe 缩回
            # 一采空间; 分块重跑(仍用放大版)时几何本来就一致, 不动。
            if not _fb_use_tiles:
                try:
                    _fbm, _fbst = _ff_extract_members(_fb_use)
                    _fb_hw = tuple(_fbm[0].shape[-2:]) if _fbm else None
                    _cond_fb = conditioning[0][1] if isinstance(conditioning, list) else conditioning
                    if _fb_hw and isinstance(_cond_fb, dict) and _cond_fb.get("minimax_keyframes"):
                        _kfs_fb = []
                        _kf_resized = 0
                        for _kf_fb in _cond_fb["minimax_keyframes"]:
                            _kl_fb = _kf_fb.get("latent")
                            if _kl_fb is not None and _kl_fb.ndim == 5 \
                                    and tuple(_kl_fb.shape[-2:]) != _fb_hw:
                                _kl_fb = torch.nn.functional.interpolate(
                                    _kl_fb,
                                    size=(int(_kl_fb.shape[2]), int(_fb_hw[0]), int(_fb_hw[1])),
                                    mode="trilinear", align_corners=False)
                                _kf_resized += 1
                            _nkf_fb = dict(_kf_fb)
                            _nkf_fb["latent"] = _kl_fb
                            _kfs_fb.append(_nkf_fb)
                        _cond_fb["minimax_keyframes"] = _kfs_fb
                        if _kf_resized:
                            print(f"[H3 Extender] v14.207 fallback: {_kf_resized} 个 keyframe "
                                  f"latent 已缩回一采 {int(_fb_hw[1])}x{int(_fb_hw[0])}"
                                  f"(原二采空间), 避免 cond 行数 4x 失配")
                except Exception as _fbk_e:
                    print(f"[H3 Extender] v14.207 fallback keyframe 几何对齐失败: {_fbk_e}")
            # v1.92: 仅当模型已被 ComfyUI 全卸(<2GB)时才卸载重载; 否则保持
            # 当前 staged 状态(DynamicVRAM 下卸载重载会 staged 21.36GB 二次 OOM).
            try:
                _fb_loaded_gb = model.loaded_size() / 1024 ** 3
            except Exception:
                _fb_loaded_gb = 0.0
            if _fb_loaded_gb < 2.0:
                try:
                    _ff_unregister_model(model, label="v1.92-fallback")
                    _mm.EXTRA_RESERVED_VRAM = int(10.0 * 1024 ** 3)
                    _mm.load_models_gpu([model])
                    print(f"[H3 Extender] v1.92 fallback: 模型已全卸({_fb_loaded_gb:.1f}GB), 重新驻留后重跑")
                except Exception:
                    pass
            _gc.collect()
            _torch.cuda.empty_cache()
            _r2_sigmas = _sigmas(_refine_model, "beta", _r_steps, _r_denoise)
            _r2_noise = comfy.sample.prepare_noise(_fb_use, int(seed) + 1, None)
            _r2_latent = _ff_const_add_noise(_refine_model, _r2_noise, _r2_sigmas, {"samples": _fb_use}, _r_audio)
            _r2_sampler = comfy.samplers.sampler_object(str(sampler_name))
            _r2_guider = _BasicGuider(_refine_model)
            _r2_guider.set_conds(conditioning)
            import comfy.sampler_helpers as _sh_fb
            _bsai_orig_prepare_fb = _sh_fb._prepare_sampling
            def _bsai_fb_prepare(model, noise_shape, conds, model_options=None, force_full_load=False, force_offload=False):
                try:
                    return model.model, conds, []
                except Exception:
                    return _bsai_orig_prepare_fb(model, noise_shape, conds, model_options=model_options,
                                                  force_full_load=force_full_load, force_offload=force_offload)
            _sh_fb._prepare_sampling = _bsai_fb_prepare
            try:
                with _aimdo_disabled():
                    _r2_samples = _r2_guider.sample(
                    _r2_noise,
                    _r2_latent["samples"],
                    _r2_sampler,
                    _r2_sigmas,
                    denoise_mask=_r2_latent.get("noise_mask"),
                    callback=_r_step_cb,
                    disable_pbar=not comfy.utils.PROGRESS_BAR_ENABLED,
                    seed=int(seed) + 1,
                )
                samples = _r2_samples.to(comfy.model_management.intermediate_device())
                _fb_label = "分块放大版" if _fb_use_tiles else ("原始备份" if _samples_pre_upscale is not None else "当前(放大后)")
                print(f"[H3 Extender] Refine fallback (v1.92 {_fb_label}) 完成: clip={clip_index}")
            except torch.cuda.OutOfMemoryError as _oom2:
                print(f"[H3 Extender] Refine fallback 仍 OOM: {_oom2}")
                # v14.206: 以前只打印"已回退到一采结果"却没有真的换回 samples,
                # 实际交付的是放大后未去噪的 latent(灰片)。这里补上真正的赋值。
                if _samples_pre_upscale is not None:
                    samples = _samples_pre_upscale
                    print(f"[H3 Extender] 已回退到一采 latent; 建议手动把 "
                          f"refine_upscale_factor 改成 1.0 重新跑")
            except Exception as _fb_err:
                # v14.207: fallback 自己抛非 OOM 异常(如 cond 行数/CUDA kernel 报错)时,
                # 旧代码会直接穿出 except-OOM 分支把整个 prompt 打死(实测 1.5 小时作业
                # 在 clip2 二采兜底里死于 shape mismatch)。兜底失败就不该再兜底,
                # 退回一采 latent 让成片先落地。用户取消(Interrupt)照常抛出。
                if type(_fb_err).__name__ == "InterruptProcessingException":
                    raise
                print(f"[H3 Extender] Refine fallback 失败(非 OOM): {_fb_err}")
                import traceback as _tb_fb
                _tb_fb.print_exc()
                if _samples_pre_upscale is not None:
                    samples = _samples_pre_upscale
                    print(f"[H3 Extender] 已回退到一采 latent (fallback 异常)")
            finally:
                # v1.65: 恢复 prepare_sampling, 防污染后续采样(下一 clip / 其它工作流)
                try:
                    _sh_fb._prepare_sampling = _bsai_orig_prepare_fb
                except Exception:
                    pass
                # v1.92: 恢复 fallback 安装的分块包装器
                if _fb_use_tiles and _r_restore_tiles is not None:
                    try:
                        _r_restore_tiles()
                    except Exception:
                        pass
        except Exception as _re:
            print(f"[H3 Extender] Refine 双采失败（回退主采样结果）: {_re}")
            import traceback
            traceback.print_exc()
            # v1.36 (2026-09-12 fix): 二采 OOM 兜底后, 用 unload_all_models()
            # 真把 diffusion/TE/VAE detach 掉, 避免 20GB VideoVAE 加载时
            # _decode_single_clip_to_blob 报 "loaded completely 20653MB"
            # 之后下一个 clip 又 OOM.
            try:
                import comfy.model_management as _mm
                import torch as _torch
                import gc as _gc
                _gc.collect()
                try:
                    # v2.120b (round3): 同 1942 崩溃链, unload_all_models() 对量化 DiT
                    # detach 时 .to(cpu) 原生崩溃; 改 for_dynamic=True 只卸非量化模型。
                    _mm.free_memory(1e30, _mm.get_torch_device(), for_dynamic=True)
                except Exception:
                    pass
                if _FF_UPSCALER_MOD is not None:
                    try:
                        _cache = getattr(_FF_UPSCALER_MOD, "MODEL_CACHE", None)
                        if isinstance(_cache, dict) and _cache:
                            for _k, _m in list(_cache.items()):
                                try:
                                    _m.to("cpu")
                                except Exception:
                                    pass
                                del _m
                                del _cache[_k]
                    except Exception:
                        pass
                _gc.collect()
                _mm.soft_empty_cache(force=True)
                _torch.cuda.synchronize()
                _torch.cuda.empty_cache()
                try:
                    _torch.cuda.ipc_collect()
                except Exception:
                    pass
                _torch.cuda.synchronize()
                _torch.cuda.empty_cache()
                _a = _torch.cuda.memory_allocated() / 1024 ** 3
                _f, _t = _torch.cuda.mem_get_info()
                print(f"[H3 Extender] Refine 失败后兜底释放(v1.36): allocated={_a:.2f}GB "
                      f"device_free={_f / 1024 ** 3:.2f}GB/{_t / 1024 ** 3:.2f}GB")
            except Exception as _ve2:
                print(f"[H3 Extender] Refine 失败后兜底释放失败(可忽略): {_ve2}")

    # v14.206 (2026-10-25): 二采 latent 塌陷兜底。
    # 实测(2026-10-25 灰片排查): 二采偶发把 latent 采样成近似常数场 —— 每通道空间
    # std 0.147、4x4 低通后 0.043, VAE 解码即灰雾/无画面; 健康 latent(一采 34x60)
    # 为 0.68~1.13。判据: 通道内空间离散度中位数 < 0.30 且 4x4 低通 < 0.15。
    # 命中且存在放大前一采备份时, 自动换回一采 latent(随后由 v1.74b 几何对齐到链上
    # 尺寸), 并推送告警, 避免再静默交付灰片。检测自身失败一律不打断渲染。
    try:
        _pre_up = _samples_pre_upscale
    except Exception:
        _pre_up = None
    if _pre_up is not None:
        try:
            _cm_v, _cm_nst = _ff_extract_members(samples)
            _cv = _cm_v[0] if _cm_v else None
            if _cv is not None and _cv.dim() == 5:
                _cv = _cv.detach().to("cpu", dtype=torch.float32)
                _ct = int(_cv.shape[2])
                if _ct > 8:
                    _cv = _cv[:, :, torch.linspace(0, _ct - 1, 8).long()]
                _cb, _cc, _ct, _ch, _cw = _cv.shape
                # 通道内空间离散度(每通道在 T/H/W 上的 std, 取中位数)
                _cdisp = float(_cv.reshape(_cb, _cc, -1).std(dim=2).median())
                # 4x4 低通后的离散度: 塌陷场只剩全局常量, 低通后几乎为 0
                _clp = torch.nn.functional.avg_pool2d(
                    _cv.permute(0, 2, 1, 3, 4).reshape(_cb * _ct, _cc, _ch, _cw),
                    4, ceil_mode=True)
                _clpdisp = float(
                    _clp.reshape(_clp.shape[0], _cc, -1).std(dim=2).median())
                if _cdisp < 0.30 and _clpdisp < 0.15:
                    _pre_v, _pre_nst = _ff_extract_members(_pre_up)
                    if _pre_v:
                        _pre_hw = tuple(_pre_v[0].shape[-2:])
                        samples = _ff_wrap_members(list(_pre_v), _pre_nst)
                        print(f"[H3 Extender] ⚠ 二采 latent 塌陷(clip={clip_index} "
                              f"通道内std={_cdisp:.3f}, 4x4低通std={_clpdisp:.3f}), "
                              f"已自动回退一采 latent {_pre_hw[1]}x{_pre_hw[0]}")
                        _send_extender_warning(
                            owner_id,
                            f"二采结果塌陷成灰片(通道内std={_cdisp:.3f})，"
                            f"已自动回退一采 latent；建议降低 refine_denoise / "
                            f"refine_steps，或关闭二采",
                            clip_index=clip_index,
                        )
                    else:
                        print(f"[H3 Extender] ⚠ 二采 latent 疑似塌陷(std={_cdisp:.3f}), "
                              f"但一采备份无效, 无法回退")
                else:
                    print(f"[H3 Extender] v14.206 二采 latent 健康: clip={clip_index} "
                          f"通道内std={_cdisp:.3f}, 4x4低通std={_clpdisp:.3f}")
        except Exception as _coll_err:
            print(f"[H3 Extender] 二采 latent 塌陷检测失败(可忽略): {_coll_err}")

    # v1.74b (2026-09-15 fix #10): 链几何对齐 —— 若链上已有段且本次 latent 几何不同
    # (per-clip 降级被拦截后仍可能 OOM fallback 到一采尺寸 / 异常路径),
    # bilinear 放大到链上几何, 保证 Disk Join 不断链。
    try:
        _cp74b, _cmp74b = _chain_paths(f"extender_{_safe_name(str(owner_id))}")
        _cm74b = _load_manifest_from_paths(_cp74b, _cmp74b)
        _cg74b = _cm74b.get("geometry") if _cm74b is not None else None
        if _cg74b is not None:
            _chh74b = int(_cg74b.get("video_h", 0))
            _chw74b = int(_cg74b.get("video_w", 0))
            if _chh74b > 0 and _chw74b > 0:
                _m74, _w74 = _ff_extract_members(samples)
                _v74 = _m74[0]
                _old_h74, _old_w74 = int(_v74.shape[-2]), int(_v74.shape[-1])
                if _old_h74 != _chh74b or _old_w74 != _chw74b:
                    import torch as _torch74
                    _v74 = _torch74.nn.functional.interpolate(
                        _v74, size=(int(_v74.shape[2]), _chh74b, _chw74b),
                        mode="trilinear", align_corners=False)
                    _m74[0] = _v74
                    samples = _ff_wrap_members(_m74, _w74)
                    print(f"[H3 Extender] v1.74b: latent 几何对齐到链上 "
                          f"{_chw74b}x{_chh74b} (原 {_old_w74}x{_old_h74})")
    except Exception as _ga74b:
        print(f"[H3 Extender] v1.74b 几何对齐失败(可忽略): {_ga74b}")

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


_DIALOGUE_AUDIO_LINE_RE = re.compile(
    r"^\s*(?:"
    r"【[^】]*(?:对白|台词|对话|旁白|音效|配音|配乐|voiceover|dialogue)[^】]*】"
    r"|\[[^\]\[]*(?:对白|台词|对话|旁白|音效|配音|配乐|voiceover|dialogue)[^\]\[]*\]"
    r"|[对白台词对话旁白音效配音配乐][：:]"
    r"|\([^)]*(?:对白|台词|对话|旁白|音效|配音|配乐)[^)]*\)"
    r"|（[^）]*(?:对白|台词|对话|旁白|音效|配音|配乐)[^）]*）"
    r")"
)
_ANCHOR_QUOTE_CHARS = '“”"「」『』‘’'


def _is_quote_dominated(seg):
    """句子中引号内对白内容占多数 → 纯对白句, 不参与视觉状态提取。"""
    try:
        _m = re.findall(
            r"[" + _ANCHOR_QUOTE_CHARS + r"]([^" + _ANCHOR_QUOTE_CHARS + r"]{0,80})[" + _ANCHOR_QUOTE_CHARS + r"]",
            seg,
        )
        _quoted = sum(len(x) for x in _m)
        return _quoted * 2 > len(seg)
    except Exception:
        return False


_VISUAL_ELEMENT_KEYWORDS = (
    # 角色形象/人物
    "人物", "角色", "主角", "男人", "女人", "男孩", "女孩", "少年", "少女", "老人",
    "男子", "女子", "女郎", "姑娘", "小伙", "演员", "歌手", "舞者", "士兵", "警察",
    "医生", "学生", "老师", "仆人", "士兵",
    # 外观/长相
    "面容", "脸庞", "脸色", "脸", "眼神", "眼睛", "眉毛", "鼻子", "嘴唇", "皮肤",
    "肤色", "皱纹", "胡须", "胡子", "雀斑", "妆容", "泪痕", "伤疤", "疤痕", "脸型",
    "面色", "苍白", "通红", "晒黑", "素颜", "浓妆", "淡妆",
    # 发型
    "头发", "发丝", "发髻", "刘海", "马尾", "辫子", "短发", "长发", "卷发", "直发",
    "发型", "白发", "黑发", "金发", "棕发", "盘发", "光头", "秃头",
    # 服装/服饰
    "服装", "衣着", "穿着", "衣服", "衣裳", "衣", "裙", "裤", "衫", "袍", "外套",
    "大衣", "夹克", "风衣", "毛衣", "衬衫", "T恤", "领带", "领结", "皮带", "腰带",
    "袖子", "袖口", "衣领", "领口", "制服", "校服", "礼服", "婚纱", "汉服", "旗袍",
    "背心", "睡衣", "披肩", "斗篷", "雨衣", "军装", "西装", "牛仔裤",
    # 鞋帽配饰
    "鞋", "靴", "袜", "帽", "头盔", "头巾", "围巾", "手套", "耳环", "项链", "戒指",
    "手镯", "眼镜", "口罩", "徽章", "胸针", "发卡", "发饰", "耳钉", "墨镜", "帽子",
    "腰带扣", "荷包", "香囊", "玉佩",
    # 伤势/状态变化（可见）
    "伤", "血", "绷带", "纱布", "疤", "淤青", "青紫", "肿", "破", "撕裂", "缝补",
    "补丁", "包扎", "擦伤", "伤口", "血迹", "流血", "渗血", "骨折", "断", "烧伤",
    "烫伤", "红肿",
    # 道具
    "道具", "刀", "剑", "枪", "伞", "油纸伞", "包", "袋", "杯", "瓶", "书", "手机",
    "相机", "乐器", "吉他", "琵琶", "小提琴", "钢琴", "麦克风", "话筒", "花", "灯笼",
    "蜡烛", "烛", "香烟", "酒瓶", "望远镜", "拐杖", "斧头", "绳索", "旗帜", "盾牌",
    "弓箭", "扇子", "折扇", "手帕", "钥匙", "信", "画卷",
    # 场景/布景
    "场景", "布景", "房间", "屋子", "客厅", "卧室", "厨房", "办公室", "教室", "街道",
    "马路", "巷", "广场", "公园", "森林", "树林", "山", "河", "海", "湖", "沙漠",
    "雪地", "草地", "田野", "桥", "阶梯", "台阶", "窗", "门", "墙", "桌", "椅",
    "床", "沙发", "柜", "窗帘", "地毯", "壁炉", "招牌", "路灯", "霓虹", "亭子",
    "楼", "塔", "寺庙", "教堂", "宫殿", "车站", "码头", "集市", "瀑布", "悬崖",
    "山洞", "稻田", "竹林", "花丛", "草地",
    # 天候/光影（可见）
    "光", "影", "暗", "明亮", "黄昏", "夜晚", "白天", "傍晚", "夕阳", "月光", "日光",
    "阳光", "雨", "雪", "雾", "烟", "云", "天空", "水面", "倒影", "反光", "剪影",
    "色调", "颜色", "色彩", "灰暗", "阴沉", "晨曦", "破晓", "彩虹",
)

# 可见视觉元素关键词的补充: 常用量词/方位 + 元素词组合过于发散, 这里仅做
# 优先级判定: 命中任一关键词的句子视为"含可见视觉元素", 预算紧张时优先保留,
# 保证角色形象/外观/服装/服饰/发型/鞋帽/场景/道具/布景等所有可见元素都被记录。


def _is_visual_element_sentence(seg):
    """句子是否包含可见视觉元素关键词（用于预算紧张时优先保留）。"""
    try:
        return any(_k in seg for _k in _VISUAL_ELEMENT_KEYWORDS)
    except Exception:
        return False


def _extract_visual_state(text, max_len=300):
    """v14.193 自动记录: 从分镜正文提取『全部可见视觉元素』状态。

    视觉锚点自动化的记录侧 —— 每个分镜的正文本身就是该分镜建立的视觉状态。
    按用户确认口径（v14.193），必须覆盖**所有可见视觉元素**：角色形象、外观、
    服装、服饰、发型、鞋帽、伤势、场景、道具、布景、天候光影等，全部记录为
    锚点，而不是只取末尾句子。

    策略：逐句保留所有非对白陈述句（对白/台词/旁白/音效是声音不是画面, 不参与
    锚点），保持原序；正文总长在预算（默认 300 字符）内时全量保留（分镜正文
    通常 <300 字符，即默认覆盖全部可见元素）；超预算时优先保留含可见视觉元素
    关键词的句子（_VISUAL_ELEMENT_KEYWORDS），再按原序补足其余句子，确保元素
    不因截断而丢失。

    返回清洗后的状态文本; 无可提取内容时返回 None。
    """
    try:
        if not text or not str(text).strip():
            return None
        raw = []
        for _ln in str(text).splitlines():
            _ln = _ln.strip()
            # 行级先做引号对白判定: 引号内的 。！？ 会把整行切成无配对引号的
            # 碎片, 若先切句再判引号会漏检纯对白行(如 『“快走！别管我！”』)。
            if not _ln or _DIALOGUE_AUDIO_LINE_RE.match(_ln) or _is_quote_dominated(_ln):
                continue
            for _seg in re.split(r"(?<=[。！？!?；;])", _ln):
                _seg = _seg.strip()
                if not _seg or _is_quote_dominated(_seg):
                    continue
                raw.append(_seg)
        if not raw:
            return None
        if sum(len(s) for s in raw) <= max_len:
            chosen = raw
        else:
            _vis = [s for s in raw if _is_visual_element_sentence(s)]
            _idx = {s: i for i, s in enumerate(raw)}
            chosen = []
            _used = 0
            for _s in _vis:  # 含可见元素的句子优先保底
                if _used + len(_s) <= max_len:
                    chosen.append(_s)
                    _used += len(_s)
            for _s in raw:  # 其余句子按原序补足剩余预算
                if _s in chosen:
                    continue
                if _used + len(_s) <= max_len:
                    chosen.append(_s)
                    _used += len(_s)
            chosen.sort(key=lambda _s: _idx[_s])  # 恢复原序
        state = re.sub(r"\s+", " ", "".join(chosen)).strip(" 　,，、;；:：")
        return state or None
    except Exception as _va_err:
        print(f"[H3 Extender] v14.193 视觉锚点自动记录解析失败(本次跳过): {_va_err}")
        return None


def _build_visual_anchor_snapshot(states, clip_index, max_total=1000):
    """v14.193 (2026-10-24): 视觉锚点自动注入 —— 为指定 CLIP 生成状态快照注入文本。

    参考 B站《MiniMax-H3 一键短剧导演台 V9》(BV1m2HK6DEPX) 的视觉锚点机制：
    多段连续剧情中，道具/场景/人物外观状态必须随剧情演进且持续延续，禁止漂移
    （如分镜3左臂受伤袖口破 → 后续各分镜必须保持受伤状态；分镜6医好/缝补 →
    后续保持新状态；绑纱布则延续纱布；缝补不同颜色布则延续该补丁布）。

    与 v14.186 的区别: 不再读取用户手写的『分镜N: 状态声明』文本（该手动输入
    widget 已移除，也不新增任何输入端口），改为自动记录 —— states 为与 clips
    对齐的列表（每项 = _extract_visual_state 从该分镜正文提取的全部可见视觉元素
    状态，或 None），本函数注入 clip_index 之前的**全部已建立状态**（自旧到新；
    总长超预算 max_total 时从最旧开始丢弃，最新状态最相关），确保每个分镜都
    携带此前全部可见视觉元素锚点。

    返回：为 clip_index（0-based）构造的注入文本；无有效状态时返回 None。
    """
    try:
        if not states:
            return None
        active = [(n, s) for n, s in enumerate(states[:clip_index], start=1) if s]
        if not active:
            return None
        keep = []
        _used = 0
        for _n, _s in reversed(active):  # 从最新往最旧装, 超预算丢最旧
            _cost = len(_s) + 14  # "自分镜N起: " 前缀开销
            if _used + _cost > max_total and keep:
                break
            keep.append((_n, _s))
            _used += _cost
        keep = keep[::-1]
        parts = [f"自分镜{n}起: {s}" for n, s in keep]
        snapshot = "；".join(parts)
        return (
            "\n[视觉锚点延续] 本段必须严格延续此前分镜已建立的视觉状态："
            + snapshot
            + "。禁止改变任何已建立的角色形象、外观、服装、服饰、发型、鞋帽、"
            "场景、道具、布景与伤势状态，除非本段正文明确声明了新的状态变化"
            "（如伤势治愈/包扎/缝补/换装等）；本段若声明新状态，则自本段起该"
            "新状态成为后续所有分镜的视觉锚点并强制延续，后续分镜不得回到旧状态。"
        )
    except Exception as _va_err:
        print(f"[H3 Extender] v14.193 视觉锚点注入失败(本次跳过注入): {_va_err}")
        return None


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

        # v14.85 CLIP 级独立超分开关（三态）：None=跟随总开关 upscale_per_clip；
        # True=强制本 CLIP 超分；False=强制本 CLIP 不超分（优先于总开关）。
        _up_raw = raw.get("upscale")
        if _up_raw not in (None, True, False):
            _up_raw = None

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
                "upscale": _up_raw,
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

    Accepts: "all", "2", "2,3", "2-5", "1,3-5", "3,5,7", "7-10"
    Also tolerates Chinese full-width punctuation: "3，5，7", "2－5".
    Returns None for "all" (meaning: render every clip normally).
    Returns a set of 0-indexed ints for specific clips.
    """
    raw = str(value or "all").strip().lower()
    if not raw or raw == "all":
        return None
    # v2.62: 兼容中文标点（全角逗号/顿号/分号）与空格
    raw = raw.replace("，", ",").replace("、", ",").replace("；", ";").replace(";", ",")
    raw = raw.replace(" ", "")
    # 全角连字符/波浪号归一化为半角连字符（如 2－5 / 2～5）
    raw = raw.replace("－", "-").replace("—", "-").replace("～", "-").replace("~", "-")

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


def _send_extender_warning(node_id, message, clip_index=-1, clip_count=0):
    """v14.157: 把"降级 / 回退"这类过去只写控制台的问题推到节点状态栏，
    避免用户拿到低画质成片却不知道原因。"""
    try:
        text = str(message or "").strip()
        if not text:
            return
        print(f"[H3 Extender] WARNING: {text}")
        _send_extender_progress(node_id, clip_index, clip_count, "warning", f"⚠ {text}")
    except Exception:
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


@PromptServer.instance.routes.post("/h3_extender/restore_cache")
async def restore_cache(request):
    """v2.60/v2.62: 恢复最近一次渲染的所有缓存、CLIP成品和预览文件。

    v2.62 改动: 多源 fallback 搜索链快照 (修复 v2.61 硬编码 backup 目录导致
    99% 用户备份找不到的问题). 候选目录按优先级:
      1. <plugin_root>/backup/chain_cache_2026-09-21/  (v2.60 默认)
      2. <plugin_root>/../  (ComfyUI 根)
      3. <plugin_root>/../../  (ComfyUI-BSAI_pro_v36_lig 主项目根, 用户手动放的快照)
      4. 用户主目录下 BSAI_H3_* 快照
    找到 chain_extender_*.h3cache 或 *_chain_snapshot_backup.h3cache 后,
    重命名为符合 _chain_paths() 规范的 chain_{safe_name(node_id)}.h3cache,
    拷贝到 bsai_h3_chain_cache/. 后续 v1.17 前置 latent 链检查会通过,
    clip_select 单选可以从该 CLIP 连续渲染到末尾.
    """
    try:
        data = await request.json()
    except Exception:
        data = {}
    node_id = str(data.get("node") or "")

    plugin_root = Path(__file__).resolve().parents[1]
    comfyui_root = Path(__file__).resolve().parents[2]
    project_root = Path(__file__).resolve().parents[3]
    user_home = Path.home()

    # v2.62: 多源 fallback 搜索链快照备份
    # v1.98: 最高优先级 = 主链目录本身（渲染完成自动快照 *.snapshot.* / 截断前备份 *.preclear.*）
    candidate_dirs = [
        _ensure_cache_root(),                                   # v1.98 主链目录（自动快照/截断备份所在）
        plugin_root / "backup" / "chain_cache_2026-09-21",   # v2.60 默认
        comfyui_root,                                          # ComfyUI 根
        project_root,                                          # 主项目根 (用户放 BSAI_H3_chain_snapshot_backup.* 的地方)
        user_home,                                             # 用户主目录
    ]

    chain_cache_dir = comfyui_root / "bsai_h3_chain_cache"
    temp_dir = _comfyui_temp_dir()

    # v2.62: 重命名映射 — 把任意命名的快照重命名为符合 _chain_paths() 规范的 chain_{safe_name(node_id)}.*
    safe_node = re.sub(r"[^A-Za-z0-9._-]+", "_", node_id).strip("._") or "h3_chain"
    target_stem = f"chain_extender_{safe_node}"

    def _is_readable(path):
        """占用中的文件（如活跃主链被 mmap）不可读时返回 False，跳过该候选。"""
        try:
            with open(path, "rb") as _f:
                _f.read(1)
            return True
        except Exception:
            return False

    def _find_chain_snapshot():
        """在候选目录里找链快照 .h3cache (按候选优先级). 返回 (h3cache_path, json_path_or_None)."""
        for d in candidate_dirs:
            try:
                if not d.exists():
                    continue
                # v1.98 修复: 优先明确的自动备份文件（*.snapshot.* / *.preclear.*），
                # 排除活跃主链 chain_extender_<node>.h3cache（正被 mmap 占用，复制会 WinError 32）。
                for pat, pair in (("*.snapshot.h3cache", "snapshot"), ("*.preclear.h3cache", "preclear")):
                    hits = [p for p in d.glob(pat) if p.name != f"{target_stem}.h3cache" and _is_readable(p)]
                    if hits:
                        h3 = max(hits, key=lambda p: p.stat().st_mtime)
                        jp = Path(str(h3).replace(f".{pair}.h3cache", f".{pair}.json"))
                        return h3, (jp if jp.exists() else None), str(d)
                # 其次: 用户快照 BSAI_H3_chain_snapshot_backup.h3cache
                hits = [p for p in d.glob("*chain_snapshot_backup.h3cache") if p.name != f"{target_stem}.h3cache" and _is_readable(p)]
                if hits:
                    h3 = max(hits, key=lambda p: p.stat().st_mtime)
                    jp = h3.with_suffix(".json")
                    return h3, (jp if jp.exists() else None), str(d)
                # 最后: 任意 chain_*.h3cache（排除活跃主链自身）
                hits = [p for p in d.glob("chain_*.h3cache") if p.name != f"{target_stem}.h3cache" and _is_readable(p)]
                if hits:
                    h3 = max(hits, key=lambda p: p.stat().st_mtime)
                    jp = h3.with_suffix(".json")
                    return h3, (jp if jp.exists() else None), str(d)
            except Exception as _e:
                print(f"[H3 Extender] v2.62 扫描 {d} 出错: {_e}")
        return None, None, None

    # 恢复链缓存
    restored = 0
    snapshot_used = None
    try:
        h3_src, json_src, found_dir = _find_chain_snapshot()
        if h3_src is not None and h3_src.exists():
            chain_cache_dir.mkdir(parents=True, exist_ok=True)
            dst_h3 = chain_cache_dir / f"{target_stem}.h3cache"
            shutil.copy2(h3_src, dst_h3)
            restored += 1
            snapshot_used = str(h3_src)
            # 同步拷贝 .json (若有)
            if json_src is not None and json_src.exists():
                dst_json = chain_cache_dir / f"{target_stem}.json"
                shutil.copy2(json_src, dst_json)
            # v2.72: 写「续渲染标记」——恢复按钮只复制文件, 无法把 validated
            # 标记写进工作流 json。下次渲染主循环检测到该标记后, 以磁盘 manifest
            # 为准同步已渲染段 validated, 跳过已恢复的 CLIP、从下一个继续渲染,
            # 不再从 clip1 全量重渲。标记随本次渲染消费后自动清除。
            try:
                _mk = Path(dst_h3).with_suffix(".restored_marker")
                _mk.write_text(
                    f"restored={h3_src.name}\nnode={node_id}\ntime={time.time()}",
                    encoding="utf-8",
                )
                print(f"[H3 Extender] v2.72 续渲染标记已写入: {_mk.name}")
            except Exception as _me:
                print(f"[H3 Extender] v2.72 续渲染标记写入失败: {_me}")
            print(f"[H3 Extender] v2.62 恢复链缓存: {h3_src.name} ({h3_src.stat().st_size // (1024*1024)} MB) "
                  f"-> {dst_h3.name} (来自 {found_dir}, node={node_id})")
        else:
            tried = [str(d) for d in candidate_dirs if d.exists()]
            print(f"[H3 Extender] v2.62 恢复链缓存: 未找到任何 .h3cache 快照. "
                  f"已扫描: {tried}. 请把 chain_extender_*.h3cache 或 "
                  f"BSAI_H3_chain_snapshot_backup.h3cache 放到 ComfyUI 根目录后重试.")
    except Exception as e:
        print(f"[H3 Extender] v2.62 恢复链缓存失败: {e}")
        return web.json_response({"ok": False, "error": f"恢复链缓存失败: {e}"})

    # 恢复预览文件: 多源 fallback (同时找 _clippv_*.mp4)
    restored_previews = 0
    preview_used_dir = None
    try:
        for d in candidate_dirs:
            if not d.exists():
                continue
            # 优先查 <d>/temp/_clippv_*.mp4
            cand = d / "temp"
            search_roots = [cand] if cand.exists() else []
            # 也允许直接放在 d 下的 _clippv_*.mp4
            search_roots.append(d)
            for root in search_roots:
                hits = list(root.glob("_clippv_*.mp4"))
                if hits:
                    temp_dir.mkdir(parents=True, exist_ok=True)
                    for f in hits:
                        shutil.copy2(f, temp_dir / f.name)
                        restored_previews += 1
                    preview_used_dir = str(root)
                    break
            if restored_previews > 0:
                break
        if restored_previews > 0:
            print(f"[H3 Extender] v2.62 恢复预览文件完成: {restored_previews} 个 (来自 {preview_used_dir})")
    except Exception as e:
        print(f"[H3 Extender] v2.62 恢复预览文件失败: {e}")

    # 统计已渲染的 CLIP 数量
    clips_dir = _clip_output_dir()
    clip_count = len(list(clips_dir.glob(f"h3_clip_{node_id}_*.mp4"))) if clips_dir.exists() else 0

    return web.json_response({
        "ok": True,
        "clips_restored": clip_count,
        "previews_restored": restored_previews,
        "chain_cache_restored": restored,
        "chain_cache_source": snapshot_used,
        "node_id": node_id,
        "target_filename": f"{target_stem}.h3cache",
        "message": (f"恢复完成：{clip_count} 个 CLIP, {restored_previews} 个预览, "
                    f"{restored} 个链缓存文件" + (f" (来自 {snapshot_used})" if snapshot_used else " (未找到链快照)"))
    })


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
    # v1.100: 导入/替换前持久备份保护。v1.97 的 preclear 备份只覆盖 truncate 路径,
    # 项目导入路径(_replace_cache_transaction)在"导入空包"(new_data=None)或误导入时,
    # 旧链先被移到临时备份、随后随事务成功被删除——整链静默丢失。
    # 事务前对"旧链非空"做持久备份(preclear 风格, 留 3 份), 事务成败都不删。
    try:
        if target_data.exists() and target_data.stat().st_size > 0 and target_manifest.exists():
            _backup_chain_before_truncate(target_data, target_manifest, reason="project-import")
    except Exception as _be:
        print(f"[H3 Extender] v1.100 导入前备份失败(忽略, 继续导入): {_be}")

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



def _bsai_list_semantic_bridge_adapters():
    """INPUT_TYPES 用: 列 models/semantic_bridge/ 下的语义桥权重, 至少返回占位项."""
    try:
        import os as _os_sb3, importlib.util as _ilu_sb3
        _sb_path = _os_sb3.path.join(_os_sb3.path.dirname(_os_sb3.path.abspath(__file__)),
                                     "bsai_h3_semantic_bridge.py")
        _sb_spec = _ilu_sb3.spec_from_file_location("bsai_h3_semantic_bridge", _sb_path)
        _sb = _ilu_sb3.module_from_spec(_sb_spec)
        _sb_spec.loader.exec_module(_sb)
        return _sb.list_adapters()
    except Exception:
        return ["(关闭: 无权重)"]


def _bsai_list_upscale_models():
    """INPUT_TYPES 用: 列 models/upscale_models/ 下的超分模型, 至少返回占位项."""
    try:
        import folder_paths as _fp_u
        names = list(_fp_u.get_filename_list("upscale_models"))
        names = [n for n in names if n.lower().endswith((".pth", ".pt", ".safetensors", ".onnx", ".bin"))]
        if names and "realesr-general-x4v3.pth" not in names:
            names.insert(0, "realesr-general-x4v3.pth")
        return names or ["realesr-general-x4v3.pth"]
    except Exception:
        return ["realesr-general-x4v3.pth"]


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
                    "default": 1344, "min": 32, "max": 4096, "step": 32,
                    "tooltip": "Manual resolution width, also used as Auto fallback when no internal image reference is loaded.",
                },
            ),
            "height": (
                "INT",
                {
                    "default": 768, "min": 32, "max": 4096, "step": 32,
                    "tooltip": "Manual resolution height, also used as Auto fallback when no internal image reference is loaded.",
                },
            ),
            "ref_image_size": (["match", "max"], {"default": "max"}),
            "steps": ("INT", {"default": 8, "min": 1, "max": 10000, "step": 1}),
            "sampler_name": (sampler_names, {"default": default_sampler}),
            "scheduler": (scheduler_names, {"default": default_scheduler}),
            "denoise": ("FLOAT", {"default": 1.0, "min": 0.01, "max": 1.0, "step": 0.01}),
            # v14.178 一镜到底全球方案落地 P0-1: context 默认 39→22(官方 AddGuide 尾部
            # 22 帧锚定), audio_context_length 默认 0→24(比视频多 2 帧对齐 40Hz 音频网格)。
            "context_length": (["22", "5", "39", "56"], {"default": "22"}),
            "audio_context_length": ("INT", {"default": 24, "min": 0, "max": 240, "step": 1}),
            "clips_json": (
                "STRING",
                {
                    "default": _state_json([_default_clip(0)]),
                    "multiline": True,
                    "tooltip": "Internal state: CLIP script JSON (hidden from the UI, not rendered or edited). v14.103: changed from hidden back to STRING. The ComfyUI 1.55 frontend does not create widgets of type hidden, which made buildUi miss clips_json and caused the CLIP area/UI to disappear plus a widgets-array/save-array misalignment (NaN); as a STRING the widget is created normally and extender.js v2.105 hides it.",
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
                    "tooltip": "Internal state: reference image JSON (hidden from the UI, not rendered or edited). v14.103: changed from hidden back to STRING for the same reason as clips_json (the 1.55 frontend does not create hidden widgets).",
                },
            ),
            "output_mode": (
                ["none", "per_clip", "merged", "both"],
                {
                    "default": "none",
                    "tooltip": "none: cache only, use the Final Decode node for output. per_clip: save one MP4 per CLIP segment. merged: merge all CLIPs into a single MP4. both: save per-clip and merged outputs.",
                },
            ),
            "filename_prefix": (
                "STRING",
                {
                    "default": "H3_Extender",
                    "tooltip": "Output filename prefix. Per-segment output appends _clipN.mp4 automatically.",
                },
            ),
            "output_image_audio": (
                "BOOLEAN",
                {
                    "default": True,
                    "tooltip": "Decode each finished CLIP to IMAGE+AUDIO immediately and stream it through the image/audio output ports (e.g. into an upscale node). When off, only the cache is kept and Final Decode exports the result.",
                },
            ),
            "block_cache": (
                "BOOLEAN",
                {
                    "default": False,
                    "tooltip": "Enable MiniMax H3 Block Cache (F1B0 residual cache) acceleration: when consecutive CLIP frames are stable, most DiT blocks are skipped, significantly speeding up multi-CLIP generation. Requires the comfyui-minimax-h3-blockcache-T8 plugin.",
                },
            ),
            "block_cache_threshold": (
                "FLOAT",
                {
                    "default": 0.12, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "Block Cache hit threshold. Higher values hit more often and speed up more, but the result may change.",
                },
            ),
            "block_cache_device": (
                ["cpu", "gpu"],
                {
                    "default": "cpu",
                    "tooltip": "Block Cache device. cpu saves VRAM; gpu reduces transfers but uses VRAM.",
                },
            ),
            "ref_cache": (
                "BOOLEAN",
                {
                    "default": True,
                    "tooltip": "Ref2VA reference-image VAE encode disk cache (same as CLIPCached, 2026.09): when reference images are unchanged, the encoded image latent is reused and repeated encoding is skipped — prompt/seed changes re-run much faster; cache auto-invalidates when references change.",
                },
            ),
            "cache_dit": (
                "BOOLEAN",
                {
                    "default": False,
                    "tooltip": "CacheDiT inter-step cache acceleration (ComfyUI-CacheDiT, H3 ~1.4-1.5x, H3 support added 2026.08): auto-detected and applied; requires the ComfyUI-CacheDiT plugin (falls back automatically if not installed). Mutually exclusive with Block Cache; when both are on, CacheDiT takes priority.",
                },
            ),
            "clip_select_enable": (
                "BOOLEAN",
                {
                    "default": False,
                    "tooltip": "CLIP selection switch: when enabled, only the CLIPs listed in clip_select are rendered; unselected ones keep their cache and are not regenerated.",
                },
            ),
            "clip_select": (
                "STRING",
                {
                    "default": "all",
                    "multiline": False,
                    "tooltip": "CLIPs to render (1-based): all=everything; single e.g. 1; multiple e.g. 1,3 / 3,5,7; ranges e.g. 2-5 / 7-10; mixed e.g. 1,3-5. Only effective when clip_select_enable is on.",
                },
            ),
            "pause_enable": (
                "BOOLEAN",
                {
                    "default": False,
                    "tooltip": "Pause switch: when enabled, rendering pauses after each CLIP before starting the next one. The frontend offers pause/continue/current-only/abort; it auto-resumes after a timeout when the user does not intervene.",
                },
            ),
            "pause_timeout": (
                "FLOAT",
                {
                    "default": 5.0, "min": 5.0, "max": 3600.0, "step": 5.0,
                    "tooltip": "Seconds to wait before auto-resuming after a pause (default 5s = best output pacing; ignored when pause is off).",
                },
            ),
            # v1.31: 二采升级为 Sol-H3 Self-Lift 双采（一采 + 二采直出高清）
            "refine_enable": (
                "BOOLEAN",
                {
                    "default": True,
                    "tooltip": "Refine (Sol-H3 Self-Lift) dual-pass, best quality, on by default: the first-pass latent is upscaled directly (no VAE) + CONST re-noise + a second full-denoise pass, producing HD video directly (e.g. 1920x1088). When enabled, per-CLIP render time increases by about 50%-100%.",
                },
            ),
            "refine_denoise": (
                "FLOAT",
                {
                    "default": 0.55, "min": 0.05, "max": 1.0, "step": 0.01,
                    "tooltip": "Refine CONST re-noise strength (Sol-H3 dual-pass semantics; v14.157 default 0.55 keeps 45% of the first-pass image, so shadows and faces gain real detail; 0.45 and below mostly smooth low-light shots). 1.0 = full re-noise redraw (official fast dual-pass). Only effective when refine_enable is on.",
                },
            ),
            "refine_steps": (
                "INT",
                {
                    "default": 6, "min": 1, "max": 20, "step": 1,
                    "tooltip": "Refine steps (v14.157 default 6 = 4 steps cannot resolve texture in low light or close-ups, 6 steps is visibly more solid; each step costs far less than a first pass). 2 steps only suit turbo models. Only effective when refine_enable is on.",
                },
            ),
            "refine_upscale_factor": (
                "FLOAT",
                {
                    "default": 2.0, "min": 1.0, "max": 2.0, "step": 0.1,
                    "tooltip": "Refine latent upscale factor (default 2.0 = direct 1920x1088 from a 960x544 first pass). 1.3-1.5x outputs close to 1080P; >1.5x significantly increases VRAM demand. After upscaling, CONST re-noise + refine run automatically. Only effective when refine_enable is on.",
                },
            ),
            "refine_upscaler_model": (
                _ff_get_upscaler_models(),
                {
                    "default": "(bilinear interpolation, no model)",
                    "tooltip": "Refine latent upscale method: 3D latent upscaler neural semantic upscale (richer detail; requires the Comfyui_Minimax_h3_latent_Upscaler plugin + model) or bilinear interpolation (no model needed, small quality loss) — the default.",
                },
            ),
            "refine_align_to": (
                "INT",
                {
                    "default": 40, "min": 8, "max": 256, "step": 8,
                    "tooltip": "Pixel alignment step after refine upscale (default 40, the H3-official 40px grid validated as optimal; 1920x1088 is already a multiple of 40). Other resolutions are rounded to this grid automatically to avoid edge color fringes.",
                },
            ),
            "refine_audio_denoise": (
                "FLOAT",
                {
                    "default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "Refine audio redraw strength: 0 = keep the first-pass audio locked (recommended: no audio re-noise/redraw, keeps voice/effects consistent); 0.5-1.0 = audio is re-noised and redrawn together with the video (sound may change). Only effective when refine_enable is on.",
                },
            ),
            # v14.83 对口型×二采组合预设（一采注入 lip_audio → 二采音频锁定保口型 / 二采音频参与重绘）
            "refine_lipsync_mode": (
                # v2.120c: 兼容 a78fa62 之前保存的旧工作流中文标签（运行期 5429-5432 已双语映射；
                # 仅合法值列表需同时接受中英文，避免旧工作流校验失败输出被忽略）。
                ["Lock lip-sync (recommended)", "锁定保口型(推荐)", "Audio redraw 0.7", "音频参与重绘0.7", "Full audio redraw 1.0", "音频全重绘1.0"],
                {"default": "Lock lip-sync (recommended)", "tooltip": "Lip-sync × refine preset: Lock lip-sync = keep first-pass audio, no redraw (refine_audio_denoise=0); Audio redraw 0.7 = refine_audio_denoise=0.7; Full audio redraw 1.0 = refine_audio_denoise=1.0. Only effective when refine_enable is on."},
            ),
            # v14.83 像素超分旁支：per-clip 逐段超分 + final 全片超分（双开关，默认关）
            "upscale_per_clip": (
                "BOOLEAN",
                {"default": False, "tooltip": "Per-CLIP pixel upscale after decode, segment by segment (per-segment VRAM stays manageable; the CLIP card H button takes priority over this master switch). Default off."},
            ),
            "upscale_final": (
                "BOOLEAN",
                {"default": False, "tooltip": "One-shot pixel upscale of the full merged film (processed once before final output; faster and cheaper). Default off."},
            ),
            "upscale_mode": (
                # v2.120c: 兼容旧工作流中文标签（_ff_resolve_upscale_mode 2208-2216 已双语映射）。
                ["Balanced (quality+speed)", "平衡(质量+速度)", "Quality first", "质量优先", "Speed first", "速度优先", "Custom", "自定义"],
                {"default": "Balanced (quality+speed)", "tooltip": "Upscale mode preset: Balanced = 2.0x auto (DLSS5 if available, else REALESR); Quality first = 3.0x REALESR; Speed first = 1.5x auto; Custom = explicit values from the widgets below."},
            ),
            "upscale_engine": (
                ["auto", "dlss5", "realesr", "bicubic"],
                {"default": "auto", "tooltip": "Upscale engine: auto = automatic; dlss5 = NVIDIA DLSS5 (requires an NVIDIA driver + library); realesr = RealESRGAN (upscale_models); bicubic = built-in interpolation (fastest, no model dependency)."},
            ),
            "upscale_factor": (
                "FLOAT",
                {"default": 2.0, "min": 1.0, "max": 4.0, "step": 0.5, "tooltip": "Pixel upscale factor (relative to the refine output resolution). Default 2.0x."},
            ),
            "upscale_model": (
                _bsai_list_upscale_models(),
                {"default": "realesr-general-x4v3.pth", "tooltip": "REALESR upscale model (models/upscale_models/). Only used when upscale_engine=realesr."},
            ),
            "upscale_tile": (
                "INT",
                {"default": 0, "min": 0, "max": 4096, "step": 1, "tooltip": "Upscale tile pixels (0 = full frame; set 512~1024 when VRAM is tight)."},
            ),
            "upscale_batch": (
                "INT",
                {"default": 4, "min": 1, "max": 32, "step": 1, "tooltip": "Upscale batch frame count (trades VRAM for speed; larger = faster but more VRAM)."},
            ),
            "upscale_fp16": (
                "BOOLEAN",
                {"default": True, "tooltip": "Upscale FP16 half-precision acceleration (auto when both NVIDIA and XPU support it)."},
            ),
            "upscale_face_restore": (
                "BOOLEAN",
                {"default": False, "tooltip": "Face restore after upscale (FaceRestore; requires GPFGAN/CodeFormer weights and adds time). Default off."},
            ),
            "tiled_refine": (
                "BOOLEAN",
                {"default": False, "tooltip": "v1.48 tiled refine (default off). When enabled, refine samples along the long spatial axis in tiles, so activation/attention workspace drops linearly with tile_count, fixing OOM/hang caused by a 21.8GB model + full-frame workspace when external processes squeeze VRAM. Ported from MiniMaxH3 Director spatial tiling (Apache-2.0). Keep off when VRAM is large. Only effective when refine_enable is on."},
            ),
            "tile_count": (
                "INT",
                {"default": 4, "min": 1, "max": 8, "step": 1, "tooltip": "Refine spatial tile count. Larger = less VRAM but slower (Director demo uses 4). Only effective when tiled_refine is on."},
            ),
            "tile_overlap": (
                "INT",
                {"default": 128, "min": 0, "max": 512, "step": 16, "tooltip": "Adjacent tile overlap pixels (raised-cosine blend). Director demo uses 128. Only effective when tiled_refine is on."},
            ),
            # v1.83: 速度预设 - 落地 B站 MiniMax急速工作流(comfyu-Selflift)技术:
            # 高分辨率二采只跑2步 + 一采4步, 视频验证 16G 跑 10s 200wpx 耗时 1000s 且质量保住.
            # 24G 跑 15s 208wpx(1920x1088) 极速模式预计 ~10-12 分钟/clip.
            # v14.172: 速度档仅保留基础速度/画质档(custom/极速/均衡/精细 + VDN 变体 7 项);
            # 模型配方档(FastH3-Trim/FastH3-4步VSA/Turbo-v4/DMAD-4步/武戏组合拳/Omni)
            # 已迁入「渲染管道 render_pipeline」下拉。旧工作流若遗留旧值, 下方
            # 兼容分支仍按值生效。
            "speed_preset": (
                ["custom", "极速", "均衡", "精细", "极速-VDN", "均衡-VDN", "精细-VDN"],
                {
                    "default": "custom",
                    "tooltip": "v1.86 speed preset (default custom = explicit values from the widgets below; best 8+2 dual-pass out of the box). Turbo = 4 first-pass steps + 3 refine steps + denoise 0.5 (~20min/clip); Balanced = 6 + 4 (~28min); Fine = 8 + 6 (~40min). VDN presets pair with the VDN workflows. Model recipes (FastH3-Trim / FastH3-4step VSA / Turbo-v4 / DMAD-4step / Action Combo / FastH3 Omni 8-step single-pass) have moved to the Render Pipeline dropdown. custom = explicit widget values below.",
                },
            ),
            # P0 (2026-10-17): 官方双轨迹采样 —— MiniMaxH3SigmaShift 等效注入.
            # video shift 驱动采样器 sigma 调度(ModelSamplingAV), audio schedule 由模型内部
            # 从共享 base grid 推导. 默认开(12/3, 官方推荐), 关掉则回到旧行为.
            "dual_track_shift": (
                "BOOLEAN",
                {"default": True, "tooltip": "P0: official dual-track sampling (MiniMaxH3SigmaShift equivalent). Separate video/audio flow shift improves A/V sync and few-step convergence. On by default."},
            ),
            "shift_video": (
                "FLOAT",
                {"default": 12.0, "min": 0.01, "max": 100.0, "step": 0.1, "tooltip": "Video flow shift, drives the sampler sigma schedule. Official default 12; DMAD recipe 12; Turbo v4 12."},
            ),
            "shift_audio": (
                "FLOAT",
                {"default": 3.0, "min": 0.0, "max": 100.0, "step": 0.1, "tooltip": "Audio flow shift. Official default 3; DMAD recipe 2. 0.0 = audio shift off (kept for old workflows)."},
            ),
            # P2 (2026-10-17): SelfLift H3 TST 时间状态传输 —— 少步数画质补偿.
            # 校正 H3 视频时间不平衡(闪烁/身份漂移/不合理运动), 运行时开销 1-2%.
            # 依赖 comfyui-SelfLift (facok) 已安装; 未安装时自动跳过并提示.
            "selflift_tst_enable": (
                "BOOLEAN",
                {"default": True, "tooltip": "P2: SelfLift H3 TST few-step quality compensation (corrects flicker, identity drift, implausible motion). Default tau 0.2. Requires comfyui-SelfLift to be installed."},
            ),
            "selflift_tst_tau": (
                "FLOAT",
                {"default": 0.2, "min": 0.0, "max": 1.0, "step": 0.05, "tooltip": "TST correction strength; the paper recommends 0.2, and 0.5 is too strong. 0 = diagnostics only."},
            ),
            "temporal_chunk_tokens": (
                "INT",
                {"default": 0, "min": 0, "max": 200, "step": 1, "tooltip": "v2.02 temporal chunking (along the T axis, unlike tile_count which is along H/W). 0 = off (default full-segment refine); >0 splits the refine latent along T into token segments of that length with overlap, each run through the existing (spatial-tiled) sampler, with the overlap zones frozen and taken over by smoothstep. Lowers attention/activation peaks to prevent OOM. For T~107, 40~60 is recommended."},
            ),
            "temporal_overlap_tokens": (
                "STRING",
                {"default": "8", "tooltip": "Overlap tokens between adjacent temporal chunks. Larger = more stable but slower; typically 8~12. Only effective when temporal_chunk_tokens>0. Old workflows: 'global_inherit', empty, or non-numeric values fall back to the default 8."},
            ),
            # v2.19 Semantic-Bridge 语义桥(可开可关, 默认关). 权重放 models/semantic_bridge/.
            "semantic_bridge_enable": (
                "BOOLEAN",
                {"default": False, "tooltip": "Semantic Bridge switch. When enabled, a small ~11MB MLP applies residual mixing to the text-encoder tokens so H3 follows instructions better (composition/spatial/counting, etc.). The original is distilled from FL2VA; this plugin forces Ref2VA compatibility. Default off; does not affect existing workflows."},
            ),
            "semantic_bridge_adapter": (
                _bsai_list_semantic_bridge_adapters(),
                {"tooltip": "Semantic Bridge weight file (~11MB), place in ComfyUI/models/semantic_bridge/. Downloads: speach1sdef178/MiniMax-H3-Semantic-Bridge or JOKER141/BUNNY_H3_Conditioning_Bridge (action/multi-person oriented). Choose (Off) to disable."},
            ),
            "semantic_bridge_alpha": (
                "STRING",
                {"default": "0.15", "tooltip": "Residual mix strength C=H+alpha*(S'-H). Original default 0.15; larger = tighter to the bridge, too large drifts. Old workflows: empty or non-numeric values fall back to the default 0.15."},
            ),
            "semantic_bridge_magnitude_match": (
                "BOOLEAN",
                {"default": True, "tooltip": "Align the small MLP output vector norm to the original hidden. Original default on."},
            ),
            # v2.24 模型环境音开关（对口型时是否混入H3自生成环境音；关=只留主唱/克隆语音）
            "env_audio_enable": (
                ["global_inherit", "on", "off"],
                {"default": "global_inherit", "tooltip": "Model ambient sound switch: global_inherit = follow the global default; on = mix in H3-generated ambient sound; off = keep only the main vocals/cloned voice."},
            ),
            "env_audio_gain": (
                "FLOAT",
                {"default": 0.15, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "Model ambient volume (0 = silent, 1 = full, default 0.15 as a floor)."},
            ),
            "face_lock_mode": (
                "BOOLEAN",
                {"default": False, "tooltip": "Far-shot face preservation mode (automatically locks facial-feature consistency; @imgN: @img1=full body, @img2.N=each person's face close-up)."},
            ),
            # v14.153 修正: refine_mem_mode 移出 required —— 它在 widget 序列中必须
            # 排在 optional 的 prompt_pack 之后（即所有 widget 的最末尾），否则会让
            # prompt_pack 从 index 62 挤到 63，与前端 KEYS/历史工作流布局错位，
            # 导致序列化丢 socket(model/clip/vae)。见下方 optional 末尾的真实定义。
        }

        # Standalone audio remains an external socket for now. Image refs are
        # deliberately no longer graph inputs: they are loaded/previewed/stored
        # by the Extender itself and embedded in portable .ext projects.
        optional = {
            "audio_vae": ("VAE", {"forceInput": True}),
            "ref_audio": ("AUDIO", {"forceInput": True, "tooltip": "Voice reference audio. When connected, it tells the H3 model that the character's voice/timbre/music style should follow this reference. Can be connected together with lip_audio — lip_audio drives the lip-sync while ref_audio provides the timbre reference."}),
            "lip_audio": ("AUDIO", {"forceInput": True, "tooltip": "Single song source: the complete song/dialogue audio. Once connected: (1) the lip-sync of every CLIP and @imgN character is driven entirely by the matching segment of this song; (2) the ref_audio port and @audN are ignored automatically; (3) all model-generated audio is discarded; (4) the output sound is exactly this song. It is auto-sliced per CLIP duration and the final output matches the video length."}),
            # v14.101: 回退 18:35(v14.84) — lip_voice 位置与 v2.7.json 一致（lip_audio 之后）
            # v14.174: lip_voice 升级为对口型驱动音频（同 lip_audio 语义且优先）。
            "lip_voice": ("AUDIO", {"forceInput": True, "tooltip": "Lip-sync drive audio (v14.174+): the complete dialogue audio. Once connected, it behaves exactly like lip_audio — (1) drives lip-sync of every CLIP; (2) all model-generated audio is discarded; (3) output sound is exactly this audio, auto-sliced per CLIP; (4) takes priority over lip_audio. Typical use: connect BSAI IndexTTS-2.5 synthesis output here to drive lip-sync with TTS voice lines."}),
            "prompt_source": ("STRING", {"forceInput": True, "tooltip": "Unified external prompt source. Auto-split at first [ShotN] marker: text before → global prompt, text from [ShotN] onwards → storyboard segments (auto-create N CLIPs with prompts and durations)."}),
            "prompt_pack": (
                PROMPT_PACK_TYPE,
                {
                    "tooltip": "Optional external prompt pack. New/changed packs are imported into the normal clip textareas and synchronize the clip count."
                },
            ),
            # v14.153: 二采省显存模式。必须排在 prompt_pack 之后 = 所有 widget 的最末尾
            # (index 62)，这样 0..61 的 widget 顺序与 v14.152 及更早完全一致，
            # 老工作流(58/59/63 键)零错位。若放 required 末尾会挤掉 prompt_pack → 丢 socket。
            "refine_mem_mode": (
                ["spatial (分块,兼容)", "global (全上下文省显存)"],
                {"default": "spatial (分块,兼容)", "tooltip": "Refine memory-saving mode. spatial (default) = current 4-tile spatial tiling (v14.149, may show background swelling/seams on some scenes). global = ported from selflift-Avatar global-context mode: full-sequence attention (no tiles, no seams) + token-chunked norm/MLP to bound VRAM; coexists with KJNodes head-grouping / Sol-Attn override (v14.148 dense gate stays active). Expect per-step time similar or better than 4-tile spatial."},
            ),
            # v14.158 (2026-10-21): BSAI 一镜到底旁支模式 —— 移植自 B站
            # 《MinimaxH3 长视频一镜到底工作流》(BV1rEto6eEvA) 的核心方法：
            # ① 段间用上一段尾部做 Add Guide 等效锚点引导（电影工厂已有
            #    motion context latent 级引导，一镜到底模式下强制开启）；
            # ② 每段提示词自动注入"不切场/不转场/镜头持续跟随主体"指令；
            # ③ 合并时改为无缝 concat（零转场），替代默认多镜头 xfade 渐变。
            # 作为旁支选择，off 时行为与历史版本完全一致，不影响任何旧工作流。
            "one_shot_mode": (
                ["off (分镜模式)", "on (一镜到底)"],
                {
                    "default": "off (分镜模式)",
                    "tooltip": "BSAI one-shot branch (based on the Bilibili MinimaxH3 long-take workflow + Motion Context V2 BV1T9ho6HEKP): off = default shot-by-shot editing mode (each segment generated independently and joined with xfade transitions; behavior unchanged). on = one-shot mode: (1) every segment prompt gets a 'no cuts / no transitions / camera keeps following the subject' instruction injected automatically (skipped if you already wrote it); (2) inter-segment motion context is forced on, and the tail latent of the previous segment guides the current one as an Add Guide equivalent anchor; (3) joining switches to seamless concat with zero transitions. v14.185 adds the one_shot_sampling tier (the last parameter of this node): the default 'single-pass seamless' skips the refine pass, so chained latents are never redrawn and seams have zero drift (dual-pass chaining introduces pixel drift; only pick it when you need 2K upscaling). Prompt discipline: the seam trims 22 frames, about 0.92s, so to land a timestamp at T write T+0.92s; continuation segments should only state what carries over (same rhythm / same camera / same lighting) and must not introduce new scene nouns; keep seams inside motion, never on a threshold or event; keep dialogue lines to one short sentence per 2.5s. Continuous camera moves (push / pull / follow / orbit) across all CLIP prompts are recommended; together with this mode you get 30s+ seamless long takes.",
                },
            ),
            # v14.159 (2026-10-21): 一镜到底 × 歌曲自动分 CLIP。
            # 结合现有对口型模式的歌曲驱动逻辑(_split_lip_audio_by_clips 按 CLIP
            # 时长切音频): one_shot_mode=on 且连接 lip_audio 歌曲时, 按本值(每段
            # 目标秒数) 自动把歌曲时长均分为目标 CLIP 数量, 自动补齐/对齐 CLIP
            # 卡片与每段时长。0 = 关闭自动分(保持手动 CLIP 数)。
            "one_shot_clip_duration": (
                "INT",
                {
                    "default": 12, "min": 0, "max": 60, "step": 1,
                    "tooltip": "One-shot x song: target duration per segment (seconds). When lip_audio is connected and one_shot_mode=on, the CLIP count is auto-computed as song duration / this value (rounded up), and CLIP cards are added/aligned automatically; the last segment takes the song's remaining duration. Example: a 5-minute song / 12s = 25 CLIPs. 0 = auto-split off.",
                },
            ),
            "asset_library": ("ASSET_LIBRARY", {"forceInput": True, "tooltip": "Connect BSAI_AssetLibraryInput to resolve @imgN/@vidN/@audN references in clip prompts."}),
        }

        # v1.22: per-clip external prompt input ports (clip_prompt_1..clip_prompt_12).
        # v14.101: 回退到 18:35（v14.84）节点结构 — 依据 v2.7.json 权威文件：
        # 当时即有 clip_prompt_1-12 端口（1/2 常连、3-12 预留）。均为 forceInput
        # 输入端口，不序列化，不影响 widgets_values 数组对齐。
        for _ci in range(1, 13):
            optional[f"clip_prompt_{_ci}"] = (
                "STRING",
                {
                    "forceInput": True,
                    "multiline": True,
                    "tooltip": f"External prompt override for CLIP {_ci}. If connected and non-empty, replaces CLIP {_ci}'s prompt (duration/refs/timings still come from the clip card). Leave unconnected to use the built-in clip prompt.",
                },
            )
        # v14.101: 回退 18:35(v14.84) — tts_model_TTS模型 在 optional 末尾（v2.7.json 一致）
        optional["tts_model_TTS模型"] = (
            "INDEX_TTS_MODEL",
            {"forceInput": True, "tooltip": "IndexTTS-2.5 model (connect to the tts_model output of BSAI_IndexTTS2_5Loader). Required in speech mode."},
        )
        # v14.172 (2026-10-22): 渲染管道统一管理全部模型配方档 —— 双采默认 +
        # FastH3-Trim / FastH3-4步VSA / Turbo-v4 / DMAD-4步 / 武戏组合拳 / Omni 8步单采。
        # 速度档(v14.170 曾并入的配方档)已回退为 7 项基础档, 配方档统一在此选择。
        # 注意: 必须排在 optional 全部 widget 的最末尾 (index 65 = 老工作流空槽,
        # 现有 66 键工作流 w65=''), 追加在 tts_model 端口之后不挤占任何既有 index。
        optional["render_pipeline"] = (
            ["Sol-H3 Self-Lift 双采 (默认)", "直播配音高清（音频≥12步）", "FastH3-Trim", "FastH3-4步VSA", "Turbo-v4", "DMAD-4步", "武戏组合拳", "4K直出 秘制酱料", "FastH3 Omni 8步单采", "双采2K（HyperVAE 2x 解码）", "QAD-v2-8步", "直播带货（全自动）", "FastH3 Omni × SelfLift 超分"],
            {
                "default": "Sol-H3 Self-Lift 双采 (默认)",
                "tooltip": "v14.184 render pipeline (all model recipes are selected here; Speed keeps only the 7 basic tiers): (1) Sol-H3 Self-Lift dual-pass (default, HD refine); (2) Live Dub HD = v14.179 dedicated live-commerce ref_audio dubbing: 12 first-pass steps (the usable lower bound for official audio) + 4 refine steps + audio redraw 0.7 (refines Mandarin vocals and eliminates garbled/mumbled dubbing at 6~8 steps; requires a non-8-step distilled model such as minimax_h3_ref2va_int8_convrot); (3) FastH3-Trim = nvfp4 pruned model, 8+4 dual-pass; (4) FastH3-4step VSA = 4-step distillation + VSA LoRA, 4+2 dual-pass; (5) Turbo-v4 = Turbo LoRA v4 step600 EMA, 6+4 dual-pass (shift 12/3); (6) DMAD-4step = DMAD 4-step distillation LoRA, 4+2 dual-pass (forced lcm, shift 12/2); (7) Action Combo = 8+4 dual-pass (euler; action/DMAD LoRAs are injected by H3LoraStack); (8) 4K Direct Secret Sauce = self-lift progressive sampling (6-step low-res first pass + boost x2 / 3-step detail second pass + DLSS5 4K pixel upscale, based on Bilibili BV18Vnb6UEPv); (9) FastH3 Omni 8-step single-pass = skip the refine pass and go straight from an 8-step distilled first pass (guidance 1.0 + shift 12/3; the Loader must switch to fasth3_omniref_8step_pruned_int8_convrot with BlockSparseAttention VSA keep_percent=10); (10) Dual-pass 2K = v14.184 T8 idea (BV1aiaL61Eyu): 8-step first pass (FastH3 distillation contract) + 4-step second pass (denoise 0.45) + no latent upscale (factor=1.0, about 4x faster refine) + HyperVAE 2x decoded pixels 2x (encoder 16x unchanged, decoder 32x, decode happens once with no extra sampling VRAM; weights are auto-detected from models/vae as hyper*2x*.safetensors) + audio redraw inherits w33 (0.7) — a live-commerce dubbing variant that outputs 2K directly without tiling seams. Note: v14.183 tried 10 steps + audio 0.9 and broke chained-segment audio (VAD returned 0 segments) with quality regression, so it was rolled back. (11) QAD-v2-8step = FastH3-QAD-v2 released 2026-10-20 by Hailuo AI Lab (a full quantization-aware distillation NVFP4 set, 118GB -> 30GB, with quality improving rather than dropping): 8-step distilled single pass (video shift 10 / audio shift 3, the official V2 NVFP4 schedule; note the Omni tier is 12/3 while this tier's 10/3 is QAD-v2 specific), refine pass skipped (single-pass seamless); the Loader must switch to the full QAD-v2 NVFP4 set (transformer + 50-layer text encoder qwen3vl_32b_minimax_h3_nvfp4_awq + new NVFP4 VAE decoder with 36/8 layers) with BlockSparseAttention VSA keep_percent=10; measured on RTX 5090, a 5s 480P clip takes only 12.6~14.8s (8-layer decoder). (12) Live Commerce (fully automatic) = v14.202 one-stop live-commerce ref_audio recipe: once selected, every parameter is taken over by this tier except width/height (resolution stays as the workflow defines it to prevent first-pass pixel blowup), and manual settings are ignored — 12 first-pass steps + 4 refine steps (denoise 0.55) + 3D latent upscaler x2.0 + audio redraw 0.7 (at 4 steps v14.196 automatically locks the 12-step first-pass audio) + shift 12/3 + TST tau 0.2 + tiled 4x128 refine + audio_context_length=0 (no previous-segment speech injection) + motion context disabled from clip2 on (prevents ghosting on the first frame of hard cuts). Pair with minimax_h3_ref2va_int8_convrot + 4-step LoRA. (13) FastH3 Omni x SelfLift = Bilibili BV1rtnQ6qErJ recipe: FastH3 Omni 8-step distill + SelfLift progressive upscale (4-step ~0.4x skeleton -> 3D latent upscale -> 4-step hi-res refine, 8 NFE total); prefer sol-attn over VSA (brighter/clearer frame, same speed); Loader must use fasth3_omniref_8step_pruned_int8_convrot. ⑬FastH3 Omni × SelfLift 超分 = B站《FastH3 Omni 全流程教学》(BV1rtnQ6qErJ) 配方: Omni 8步蒸馏 + SelfLift 渐进式超分(一采 4 步 ≈0.4x 搭骨架 -> 3D latent 放大 -> 二采 4 步精修, 总 8 NFE); 建议注意力 sol-attn 替代 VSA(画面清亮通透, 速度不变); Loader 需换 fasth3_omniref_8step_pruned_int8_convrot.",
            },
        )
        # v14.185 (2026-10-24): 一镜到底采样档 —— 追加在 render_pipeline 之后（optional
        # 最末尾），不挤占任何既有 widget index。
        # 参考 B站 Motion Context V2 (BV1T9ho6HEKP) 实测结论：双采 latent 续链在接缝
        # 产生像素漂移，单采接缝干净——一镜到底默认单采。
        # v14.215 (2026-10-26): 新增第三档「双采无缝 (8+4)」—— 一镜到底 + 二采
        # (1采8步 + 2采4步), 并修掉双采接缝漂移的根因(段头锁 keep 在双采分辨率下静默失效)。
        optional["one_shot_sampling"] = (
            ["单采无缝 (推荐)", "双采高清 (接缝风险)", "双采无缝 (8+4)"],
            {
                "default": "单采无缝 (推荐)",
                "tooltip": "One-shot sampling tier (only effective when one_shot_mode=on): Single-pass seamless = skip the refine pass, chained latents are never redrawn, seams have zero drift; recommended with the turbo 8-step LoRA + beta scheduler + 6-8 steps. Dual-pass HD = keep the refine upscale/refinement (can reach 2K), but the reference workflow shows dual-pass chaining introduces pixel drift at seams (blur/jitter between segments), so pick it only when you need HD upscaling. v14.215 adds 'Dual-pass seamless (8+4)': runs the refine pass (8 first-pass steps + 4 refine steps, denoise 0.45) AND repairs the inter-segment anchor so the join stays seamless - the head keep-lock used to die silently whenever the previous clip's tail was at the refined 2x resolution, which is exactly why dual-pass drifted. The 8+4 counts still come from the widget (speed_preset=custom); this tier never overrides them.",
            },
        )
        # v14.193: 视觉锚点改为全自动（自动记录 + 自动注入）—— 手动输入 widget
        # visual_anchor_notes（v14.186 曾置于 optional 最末尾 index 67）已移除：
        # 锚点状态自动从各分镜正文提取全部可见视觉元素（_extract_visual_state，
        # 角色形象/外观/服装/服饰/发型/鞋帽/场景/道具/布景等）并自动注入后续
        # 分镜，不再需要（也不新增）任何手动输入参数端口。移除的是最末尾
        # widget，不挤占/不移位任何既有 widget index（现役布局与旧 CUR68 一致）。


        # v1.21: INPUT_TYPES keys kept as pure English for workflow compatibility.
        # Bilingual labels are applied on the frontend via extender.js widget label override.
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

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        # v14.152: 带 **kwargs 的 VALIDATE_INPUTS 让 ComfyUI 跳过所有参数的
        # min/max 校验与 combo 选项校验（execution.py 1032/1060 行分支），
        # 使老版本导出的工作流（temporal_overlap_tokens='global_inherit'、
        # semantic_bridge_alpha=''、semantic_bridge_adapter=False、shift_audio=0.0
        # 等历史遗留值）能进入 extend()，由函数内容错逻辑统一归一到默认最低档。
        # 真正的类型/语义校验在 extend() 入口处完成。
        return True

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
        # v1.99: 每个 clip 依赖的资产图路径（per-clip 失效用）
        clip_asset_paths = [[] for _ in clips]

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
                if img_path not in clip_asset_paths[clip_idx]:
                    clip_asset_paths[clip_idx].append(img_path)
                ref_num = resolved_image_paths.index(img_path) + 1
                return f"<Picture {ref_num}>"
            prompt = re.sub(r'@(?:图|img)(\d+)', _replace_image_tag, prompt, flags=re.IGNORECASE)

            # Resolve @视频N -> <Video N>
            def _replace_video_tag(m):
                tag_num = int(m.group(1))
                vid_entry = _find_asset_by_index(videos, tag_num)
                if vid_entry is None:
                    return m.group(0)
                return f"<Video {tag_num}>"
            prompt = re.sub(r'@(?:视频|vid)(\d+)', _replace_video_tag, prompt, flags=re.IGNORECASE)

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
            prompt = re.sub(r'@(?:音频|aud)(\d+)', _replace_audio_tag, prompt, flags=re.IGNORECASE)

            # v14.205: 多视图参考图纪律（只加一次；无图片标签的 prompt 不加）
            if "<Picture " in prompt and _REF_SHEET_RULE not in prompt:
                prompt = _REF_SHEET_RULE + prompt

            if prompt != original_prompt:
                print(f"[H3 Extender] clip[{clip_idx}] prompt resolved: '{original_prompt[:60]}' -> '{prompt[:60]}'")
            clip["prompt"] = prompt

        print(f"[H3 Extender] resolved {len(resolved_image_paths)} image paths, {len(resolved_audio_paths)} audio paths")
        for i, p in enumerate(resolved_image_paths):
            print(f"[H3 Extender]   resolved_img[{i}]: {p}")

        return clips, resolved_image_paths, resolved_audio_paths, clip_asset_paths

    def extend(self, model, clip, vae, **kwargs):
        # v1.21: keys are pure English now, direct kwargs.get()
        run_mode = kwargs.get("run_mode")
        width = kwargs.get("width")
        height = kwargs.get("height")
        ref_image_size = kwargs.get("ref_image_size")
        # v2.58b: 强制把 match 改成 max，避免参考图太大模型直接复制参考图内容
        # (match 模式参考图和输出一样大，模型会直接复制参考图，不听提示词)
        if ref_image_size == "match":
            ref_image_size = "max"
            print("[H3 Extender] v2.58b: 强制 ref_image_size 从 match 改成 max (避免参考图太大污染提示词)")
        steps = kwargs.get("steps")
        sampler_name = kwargs.get("sampler_name")
        scheduler = kwargs.get("scheduler")
        # P0/P2 (2026-10-17): 双轨迹采样 + TST 少步数补偿参数
        dual_track_shift = bool(kwargs.get("dual_track_shift", True))
        shift_video = float(kwargs.get("shift_video", 12.0))
        shift_audio = float(kwargs.get("shift_audio", 3.0))
        # v14.152: 老工作流可能存 0.0（旧版 min 允许 0），ModelSamplingAV.audio_scale
        # = shift/audio_shift 会除零。<=0 一律映射为 None（audio_scale=1.0，关闭音频
        # shift，即最低档），保证兼容且不崩。
        if shift_audio <= 0.0:
            shift_audio = None
            print(f"[H3 Extender] shift_audio<=0 已映射为 None（关闭音频 shift，最低档）", flush=True)
        selflift_tst_enable = bool(kwargs.get("selflift_tst_enable", True))
        selflift_tst_tau = float(kwargs.get("selflift_tst_tau", 0.2))
        denoise = kwargs.get("denoise")
        context_length = kwargs.get("context_length")
        audio_context_length = kwargs.get("audio_context_length")
        clips_json = kwargs.get("clips_json")
        resolution_mode = kwargs.get("resolution_mode", "auto_from_ref")
        megapixels = kwargs.get("megapixels", DEFAULT_MEGAPIXELS)
        refs_json = kwargs.get("refs_json", None)
        output_mode = kwargs.get("output_mode", "none")
        filename_prefix = kwargs.get("filename_prefix", "H3_Extender")
        prompt_pack = kwargs.get("prompt_pack", None)
        asset_library = kwargs.get("asset_library", None)
        prompt_source = kwargs.get("prompt_source", None)
        output_image_audio = kwargs.get("output_image_audio", True)
        block_cache = kwargs.get("block_cache", False)
        block_cache_threshold = kwargs.get("block_cache_threshold", 0.12)
        block_cache_device = kwargs.get("block_cache_device", "cpu")
        ref_cache = kwargs.get("ref_cache", True)
        cache_dit = kwargs.get("cache_dit", False)
        clip_select_enable = kwargs.get("clip_select_enable", False)
        clip_select = kwargs.get("clip_select", "all")
        restore_cache = kwargs.get("restore_cache", False)
        pause_enable = kwargs.get("pause_enable", False)
        pause_timeout = kwargs.get("pause_timeout", 5.0)
        refine_enable = kwargs.get("refine_enable", True)
        refine_denoise = kwargs.get("refine_denoise", 0.45)
        refine_steps = kwargs.get("refine_steps", 2)
        refine_upscale_factor = kwargs.get("refine_upscale_factor", 2.0)
        refine_upscaler_model = kwargs.get("refine_upscaler_model", "(bilinear interpolation, no model)")
        refine_align_to = int(kwargs.get("refine_align_to", 40))
        refine_audio_denoise = float(kwargs.get("refine_audio_denoise", 0.0))
        # v14.83 对口型×二采组合预设（优先于 refine_audio_denoise 原始值）
        refine_lipsync_mode = str(kwargs.get("refine_lipsync_mode", "Lock lip-sync (recommended)"))
        if refine_lipsync_mode in ("Audio redraw 0.7", "音频参与重绘0.7"):
            refine_audio_denoise = 0.7
        elif refine_lipsync_mode in ("Full audio redraw 1.0", "音频全重绘1.0"):
            refine_audio_denoise = 1.0
        else:
            refine_audio_denoise = 0.0
        # v14.194 音频重绘防护: 官方音频≥12步可用下限——一采步数<12 时二采音频重绘
        # (≥0.5) 会在低步数上重画音频 latent, 实测产出恒定低频轰鸣/底噪/失真
        # (h3_clip_250: ~95-200Hz 占~60%能量, 全程无静音帧)。不改行为,
        # 仅提示改走"直播配音高清"(一采12步+音频0.7) 或对口型×二采=锁定音频。
        if refine_enable and float(refine_audio_denoise) >= 0.5:
            try:
                _fp_steps = max(1, int(steps))
            except Exception:
                _fp_steps = 12
            if _fp_steps < 12:
                print(f"[H3 Extender] ⚠ v14.194: 一采 {_fp_steps} 步(<官方音频12步下限) + "
                      f"二采音频重绘 {float(refine_audio_denoise):.1f} —— 低步数重画音频 latent "
                      f"易产恒定低频轰鸣/底噪/失真; 建议改用\"直播配音高清\"管道 "
                      f"(一采12步+音频0.7) 或对口型×二采=锁定音频", flush=True)
        # v14.83 像素超分旁支（双开关，默认关）+ v14.84 模式预设
        upscale_per_clip = bool(kwargs.get("upscale_per_clip", False))
        upscale_final = bool(kwargs.get("upscale_final", False))
        upscale_mode = str(kwargs.get("upscale_mode", "Balanced (quality+speed)"))
        upscale_engine = str(kwargs.get("upscale_engine", "auto"))
        upscale_factor = float(kwargs.get("upscale_factor", 2.0))
        upscale_model = str(kwargs.get("upscale_model", "realesr-general-x4v3.pth"))
        upscale_tile = int(kwargs.get("upscale_tile", 0))
        upscale_batch = int(kwargs.get("upscale_batch", 4))
        upscale_fp16 = bool(kwargs.get("upscale_fp16", True))
        upscale_face_restore = bool(kwargs.get("upscale_face_restore", False))
        _up_factor, _up_engine = _ff_resolve_upscale_mode(
            upscale_mode, upscale_factor, upscale_engine
        )
        # v2.24 模型环境音开关 / face_lock_mode（v14.83 起参数化；读取并传入渲染配置）
        env_audio_enable = str(kwargs.get("env_audio_enable", "global_inherit"))
        env_audio_gain = float(kwargs.get("env_audio_gain", 0.15))
        face_lock_mode = bool(kwargs.get("face_lock_mode", False))
        # v14.158 (2026-10-21): BSAI 一镜到底旁支模式。off 时零影响（默认）；
        # on 时：①强制段间 motion context（Add Guide 等效锚点引导）
        #       ②每段提示词自动注入一镜到底镜头指令
        #       ③合并改无缝 concat（零转场）
        one_shot_mode = str(kwargs.get("one_shot_mode", "off (分镜模式)") or "off (分镜模式)")
        one_shot_enabled = one_shot_mode.startswith("on")
        # v14.185: 一镜到底采样档 —— 单采无缝(默认)/双采高清(接缝风险)。
        # 参考 B站 Motion Context V2 (BV1T9ho6HEKP) 实测: 双采 latent 续链在接缝
        # 产生像素漂移(段间模糊/抖动), 单采接缝干净。
        one_shot_sampling = str(kwargs.get("one_shot_sampling", "单采无缝 (推荐)") or "单采无缝 (推荐)")
        one_shot_single_pass = one_shot_enabled and not one_shot_sampling.startswith("双采")
        # v14.215 (2026-10-26): 新增第三档「双采无缝 (8+4)」—— 一镜到底照跑二采,
        # 同时修掉双采接缝漂移的根因: 段头锁 keep 用的"上一段尾 latent"在双采下是
        # 二采放大后的 2x, 本段一采 latent 是 1x, 直接赋值 shape 不匹配 → 整块被
        # except 吞掉 → 噪声延续 + 段头锁 keep 全部失效 → 裁掉重叠区后接缝画面跳变。
        # one_shot_seamless_dual = 双采 + 接缝锚点修复(不跳过二采)
        one_shot_seamless_dual = one_shot_enabled and one_shot_sampling.startswith("双采无缝")
        # v14.159: 一镜到底×歌曲自动分 CLIP 的每段目标时长(秒); 0=关闭自动分
        try:
            one_shot_clip_duration = int(kwargs.get("one_shot_clip_duration", 12) or 12)
        except (TypeError, ValueError):
            one_shot_clip_duration = 12
        if one_shot_enabled:
            print("[H3 Extender] 🎬 一镜到底旁支模式已启用：无缝 concat 零转场 + 镜头跟随指令注入 + 强制 motion context")
            # v14.185: 提示词纪律引导(Motion Context V2 实测规则, 不改用户提示词)。
            print("[H3 Extender] 📝 一镜到底提示词纪律：①接缝裁切 22 帧(≈0.92s)，段内时间戳想落在 T 请写 T+0.92s；"
                  "②续写段开头只写承接(同节奏/同机位/同光照)，勿引入新景物名词；"
                  "③接缝落在运动中段(行走/奔跑中)，勿落在门槛/事件点，渐进式运镜勿跨接缝；"
                  "④台词约每 2.5s 一句短句，按句子切分段。")
        # v14.168 (2026-10-22): FastH3 Omni 8步蒸馏旁支模式。
        # 选择后 = 单采管道: 跳过二采(Self-Lift refine), 一采强制 8 步 + denoise 1.0
        # (官方 FastVideo FastH3 Omni 契约: 8步蒸馏 guidance 1.0 shift 12/3, 改步数掉画质)。
        # 模型/文本编码器/VAE 由工作流 Loader 提供(需换 fasth3_omniref_8step_pruned_int8_convrot),
        # VSA 稀疏由工作流 BlockSparseAttention 节点挂载 —— 本模式只改采样管道, 不碰模型图。
        _render_pipeline = str(kwargs.get("render_pipeline", "Sol-H3 Self-Lift 双采 (默认)") or "Sol-H3 Self-Lift 双采 (默认)")
        # v14.211: 「FastH3 Omni × SelfLift 超分」是 Omni 的渐进双采版, 不走单采强制(保留二采)。
        omni_8step_mode = _render_pipeline.startswith("FastH3 Omni") and "SelfLift" not in _render_pipeline
        if omni_8step_mode:
            # ① 跳过二采 —— 一采 latent 直接解码, 单采直出
            refine_enable = False
            # ② 一采强制 8 步蒸馏契约 (官方固定 8, 4 步掉画质)
            try:
                _steps_raw = int(steps or 8)
            except (TypeError, ValueError):
                _steps_raw = 8
            if _steps_raw != 8:
                print(f"[H3 Extender] v14.168 Omni 8步单采: 一采 steps {_steps_raw} -> 强制 8 (官方蒸馏契约)")
                steps = 8
            # ③ 完整蒸馏 = denoise 1.0 (Omni 无 latent 继承, 从零去噪)
            try:
                _denoise_raw = float(denoise or 1.0)
            except (TypeError, ValueError):
                _denoise_raw = 1.0
            if _denoise_raw != 1.0:
                print(f"[H3 Extender] v14.168 Omni 8步单采: denoise {_denoise_raw} -> 强制 1.0 (完整蒸馏)")
                denoise = 1.0
            print("[H3 Extender] 🚀 FastH3 Omni 8步单采模式已启用：跳过二采(Self-Lift)，一采 8 步蒸馏直出。"
                  "确认 Loader 使用 fasth3_omniref_8step_pruned_int8_convrot.safetensors + BlockSparseAttention(VSA keep_percent=10)。")
        tiled_refine = bool(kwargs.get("tiled_refine", False))
        tile_count = int(kwargs.get("tile_count", 4))
        # v14.181 (2026-10-23): 回滚 v14.180 的 overlap 钳制 64px -> 恢复 128px。
        # 实测崩坏(分镜模式, 22:00 渲染): v14.179 声称 overlap 64 的接缝由
        # motion-context keyframe 对齐兜底, 但该兜底仅在一镜到底(one_shot=on)
        # 时注入; 分镜模式(one_shot=off) 无 keyframe 兜底, 64px 接缝完全裸露
        # -> 画面扭曲/变形/重影/分块严重。分镜模式必须保留 128px 接缝融合区。
        # 提速不能靠砍 overlap(接缝是画质底线), 正确路径=Sol-Attn 稀疏真生效。
        tile_overlap = min(int(kwargs.get("tile_overlap", 128)), 128)
        # v14.153: 二采省显存模式（spatial=v14.149 分块路径 / global=全上下文省显存）
        refine_mem_mode = str(kwargs.get("refine_mem_mode", "spatial (分块,兼容)") or "spatial (分块,兼容)")
        refine_mem_global = refine_mem_mode.startswith("global")
        # v2.02 (2026-09-19): 时间分块(沿 T 轴)二采, 区别于上面的空间分块(沿 H/W)。
        # chunk_tokens<=0 关闭(默认), 整段一次性二采; >0 时沿 T 切块逐段走已有(空间分块)采样器。
        # v2.56 (2026-09-21): 兼容旧工作流，新增参数空值容错
        def _safe_int(val, default=0):
            if val is None or val == "":
                return default
            try:
                return int(val)
            except (ValueError, TypeError):
                return default
        def _safe_float(val, default=0.0):
            if val is None or val == "":
                return default
            try:
                return float(val)
            except (ValueError, TypeError):
                return default
        # v14.153: 工作流传布尔 true(开但没给数字) 时自动用建议值 48 (T~107 只切 2~3 段),
        # 不再被 int(True)=1 -> 强制 16 -> 切成 13 段(每段重跑 4 步, 慢 4 倍)
        _tc_raw = kwargs.get("temporal_chunk_tokens")
        if _tc_raw is True or _tc_raw == "true" or _tc_raw == 1:
            temporal_chunk_tokens = 48
        else:
            temporal_chunk_tokens = _safe_int(_tc_raw, 0)
        # v14.152: 兼容老工作流 'global_inherit' 等历史字符串 — 非数字一律取默认 8
        temporal_overlap_tokens = _safe_int(kwargs.get("temporal_overlap_tokens"), 8)
        # v2.19 Semantic-Bridge 语义桥(可开可关, 默认关). 小 MLP 残差混合 cond token.
        _sb_enable = bool(kwargs.get("semantic_bridge_enable", False))
        _sb_adapter_raw = kwargs.get("semantic_bridge_adapter", "")
        # v14.152: 老工作流可能存 False/None/空串 → 一律视为关闭（最低档）
        _sb_adapter = "" if _sb_adapter_raw in (False, None, "") else str(_sb_adapter_raw)
        # v14.152: 老工作流可能存空串 → 取默认 0.15（最低档）
        _sb_alpha = _safe_float(kwargs.get("semantic_bridge_alpha"), 0.15)
        _sb_mag = bool(kwargs.get("semantic_bridge_magnitude_match", True))
        sb_pack = {
            "enabled": _sb_enable and bool(_sb_adapter) and not _sb_adapter.startswith("("),
            "adapter": _sb_adapter,
            "alpha": _sb_alpha,
            "magnitude_match": _sb_mag,
        }
        # v1.83: 速度预设覆盖 (先于 REFINE-PARAMS 打印, 保证日志反映实际生效参数)
        speed_preset = str(kwargs.get("speed_preset", "均衡"))
        _sp_old = (steps, refine_steps, tile_count, refine_denoise)
        # v14.176: 武戏组合拳档启用 H3 17 帧块对齐 (YZ金鱼终极篇帧数公式 %17==5,
        # 防高动态武戏 latent 时间结构错位/果冻伪影)。档位分支命中后置 True,
        # lip 切段前统一把 clips duration 对齐到 17 帧块。
        _h3_align17 = False
        # v14.172: 渲染管道统一管理模型配方档 —— 非默认档时模式参数由渲染管道接管,
        # speed_preset 仅剩 7 项基础档。旧工作流遗留的配方档值(速度档里)仍由下方
        # speed_preset 兼容分支按值生效, 两源互斥不叠加。
        _rp_mode = str(kwargs.get("render_pipeline", "") or "")
        # v14.182: HyperVAE 2x 像素翻倍因子 —— 仅「双采2K」档在分支内置 2.0,
        # 其余档保持 1.0 (声明输出尺寸 = 实际解码像素, 不放大)。
        _hv2x_decl = 1.0
        if _rp_mode and _rp_mode != "Sol-H3 Self-Lift 双采 (默认)":
            _rp_handled = True
            if _rp_mode == "直播配音高清（音频≥12步）":
                # v14.179 (2026-10-23): 直播带货 ref_audio 配音模式专用配方。
                # 根因: H3 官方/社区实证 —— 音频 8 步最差, ≥12 步才可用;
                # 旧默认档 6~8 步一采 + 二采 audio_denoise=0.0 锁定音频 → 中文人声
                # 含混/吞音/切碎(VAD 10 段人声 ASR 仅转出 2 段 = 用户听到的"乱配音")。
                # 本档: 一采 12 步(音频达标) + 二采 4 步 + 音频参与重绘 0.7
                # (二采对音频重新加噪去噪, 精修人声清晰度, 同时保留 ref_audio 声线参考)。
                # 注意: 需配非 8 步蒸馏模型(如 minimax_h3_ref2va_int8_convrot),
                # 8 步蒸馏模型改 12 步会违背蒸馏契约掉画质。
                steps, refine_steps, tile_count, refine_denoise = 12, 4, 4, 0.45
                refine_audio_denoise = 0.7
                shift_video, shift_audio = 12.0, 3.0
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                    print(f"[H3 Extender] v14.179 直播配音高清(渲染管道): 采样器强制 euler + simple (配音精修配方)")
                print("[H3 Extender] 🎙️ 直播配音高清模式: 一采 12 步(音频≥12步官方可用下限) + 二采 4 步 + 音频重绘 0.7, 根治乱配音/含混吞音")
            elif _rp_mode == "FastH3-Trim":
                steps, refine_steps, tile_count, refine_denoise = 8, 4, 4, 0.45
            elif _rp_mode == "双采2K（HyperVAE 2x 解码）":
                # v14.182 (2026-10-23): T8 思路(B站 BV1aiaL61Eyu) 双采放大高分辨率。
                # 核心增量: ①二采 latent 不放大(factor=1.0) → 二采 token 少 ~4x,
                #    328s/步 -> ~80-90s/步 (同时根治 v14.180 64px overlap 接缝问题,
                #    因为压根不做 latent 放大, 无 tiles 接缝); ②解码用 HyperVAE 2x
                #    (encoder 16x 不变, decoder 32x pixel_shuffle 2x) → 二采 latent
                #    直接解成 2x 像素直出 2K, 全程只解码一次, 不增加采样显存。
                # v14.184 (2026-10-24): 回滚 v14.183 两处错误改动 ——
                #    v14.183 曾改: 一采 8->10 步 + 音频重绘 0.7->0.9 + denoise 0.45->0.5,
                #    实测 clip2(链 segment1) 音频彻底崩(VAD 0 段人声, ASR 置信度 0.43-0.70
                #    且前 8 秒无声) + 画质退化(10 步违背 FastH3 8 步蒸馏契约, 标签文字变糊)。
                #    根因: ①音频重绘 0.9 = 90% 重绘音频 latent + 二采仅 4 步 = 从噪声画
                #      4 步音频, 必崩(0.7 保留 30% 一采音频特征是安全线); ②一采 10 步
                #      破坏 8 步蒸馏契约掉画质。
                #    回滚: 一采 8 步(蒸馏契约) + denoise 0.45 + 音频重绘继承 w33(0.7)。
                #    吞音/噪点残余改用解码后处理(v14.184 双采2K 档解码端轻锐化降噪), 
                #    不动采样配方 —— 采样配方是已验证良好基线。
                steps, refine_steps, tile_count, refine_denoise = 8, 4, 4, 0.45
                shift_video, shift_audio = 12.0, 3.0
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                    print(f"[H3 Extender] v14.184 双采2K(渲染管道): 采样器强制 euler (T8 双采配方)")
                # 二采 latent 不放大 —— 由 HyperVAE 2x 解码负责像素翻倍
                try:
                    _rurf2k = float(refine_upscale_factor or 2.0)
                except (TypeError, ValueError):
                    _rurf2k = 2.0
                if _rurf2k != 1.0:
                    refine_upscale_factor = 1.0
                    print(f"[H3 Extender] v14.184 双采2K(渲染管道): refine_upscale_factor {_rurf2k} -> 1.0 (latent 不放大, 二采提速 + HyperVAE 2x 解码像素翻倍)")
                _hv2x_decl = 2.0  # v14.182: HyperVAE 2x 解码输出 = 像素 2x, 声明尺寸须翻倍
                # v14.182: 双采2K 二采 latent 不放大 —— 强制不使用 3D latent
                # upscaler (否则 L3109 会把 factor<=1.0 自动提到 1.5, 二采又放大
                # token, 双采2K 提速与 HyperVAE 2x 直出 2K 的收益全丢)。
                if refine_upscaler_model and not str(refine_upscaler_model).startswith("("):
                    _old_urm = str(refine_upscaler_model)
                    refine_upscaler_model = "(bilinear interpolation, no model)"
                    print(f"[H3 Extender] v14.184 双采2K(渲染管道): 3D upscaler '{_old_urm}' 已禁用 "
                          f"(factor=1.0 latent 不放大, 由 HyperVAE 2x 解码直出 2K)")
                # v14.184: 音频重绘继承 w33(0.7) —— v14.183 强制 0.9 致音频崩(VAD 0 段),
                # 0.7 = 保留 30% 一采音频 latent 特征(ref_audio 声线), 只精修 70%。
                print("[H3 Extender] 🎥 双采2K 模式: 一采 8 步(蒸馏契约) + 二采 4 步(factor=1.0 提速) + HyperVAE 2x 解码直出 2K, 音频重绘继承 w33(0.7)")
            elif _rp_mode == "FastH3-4步VSA":
                steps, refine_steps, tile_count, refine_denoise = 4, 2, 4, 0.45
            elif _rp_mode == "Turbo-v4":
                # v14.173: 6+4/denoise0.55 -> 8+4/denoise0.45 (一采8步结构更稳, 二采少重绘防
                # clip2 复杂场景(点火/火焰/特写) 结构漂移变形; 速度仍快于精细(8+6)二采少2步)
                steps, refine_steps, tile_count, refine_denoise = 8, 4, 4, 0.45
                shift_video, shift_audio = 12.0, 3.0
            elif _rp_mode == "DMAD-4步":
                steps, refine_steps, tile_count, refine_denoise = 4, 2, 4, 0.5
                shift_video, shift_audio = 12.0, 2.0
                if str(sampler_name) != "lcm":
                    sampler_name = "lcm"
                    print(f"[H3 Extender] v14.172 DMAD-4步(渲染管道): 采样器强制 lcm (DMAD 官方配方)")
            elif _rp_mode == "武戏组合拳":
                # v14.176: 对齐 YZ金鱼「终极篇」武戏配方 (BV1LKJm6VELc):
                # 一采6步(simple) + 二采6步(总12步, 武戏拟合更清晰),
                # shift 12/3 (官方 v4), euler+simple 调度, 帧数对齐 H3 17 块.
                # 二采 denoise 0.45 (防高动态重绘漂移), 分块4 (24GB 显存防 OOM).
                steps, refine_steps, tile_count, refine_denoise = 6, 6, 4, 0.45
                shift_video, shift_audio = 12.0, 3.0
                _h3_align17 = True
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                    print(f"[H3 Extender] v14.176 武戏组合拳(渲染管道): 采样器强制 euler + simple 调度 (YZ终极篇武戏配方)")
            elif _rp_mode == "4K直出 秘制酱料":
                # v14.178 (2026-10-23): 对齐 B站《4K直出 MiniMax H3 秘制酱料工作流》
                # (BV18Vnb6UEPv, 大凯AI/CottonByte/Yusu) —— Self-Lift 自提升渐进采样:
                # 前期低分辨率阶段(一采 960x544 由 width/2 自动, 6 步)快定构图/轮廓/大幅运动;
                # 选定时间点 RESOLUTION BOOST (refine_upscale_factor 2.0 升潜空间分辨率);
                # 后期高分辨率阶段(二采 3 步)补纹理/精细细节。配 Turbo v4 step600 加速 LoRA +
                # MysticXXX V4 去油光 LoRA, 输出经 DLSS5 像素超分直出 4K (修 H3 高光过曝/发灰)。
                # 4090/24GB 若二采慢: refine_upscale_factor 降到 1.5 (1440x816) + DLSS 2.66x 仍 4K。
                steps, refine_steps, tile_count, refine_denoise = 6, 3, 4, 0.45
                shift_video, shift_audio = 12.0, 3.0
                try:
                    _rurf_raw = float(refine_upscale_factor or 2.0)
                except (TypeError, ValueError):
                    _rurf_raw = 2.0
                if _rurf_raw < 2.0:
                    print(f"[H3 Extender] v14.178 4K直出(渲染管道): refine_upscale_factor {_rurf_raw} 保持 (1.5 搭配 DLSS 2.66x 仍可达 4K)")
                else:
                    refine_upscale_factor = 2.0
                    print(f"[H3 Extender] v14.178 4K直出(渲染管道): refine_upscale_factor -> 2.0 (自提升 boost)")
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                    print(f"[H3 Extender] v14.178 4K直出(渲染管道): 采样器强制 euler + simple (秘制酱料配方)")
                print("[H3 Extender] 🎥 4K直出 秘制酱料模式: 一采 6 步低分辨率(自提升构图/形状/运动) → boost x2 → 二采 3 步细节。"
                      "LoRA 建议: minimax_h3_turbo_v4_step600 (0.5~0.8) + MysticXXX_MMH3-V4 (0.3~0.5, 去油光/高光自然); "
                      "输出走 DLSS5 像素超分(upscale_final + dlss5) 直出 4K。")
            elif _rp_mode == "FastH3 Omni 8步单采":
                steps, refine_steps, tile_count, refine_denoise = 8, 2, 4, 0.5
                if not omni_8step_mode:
                    omni_8step_mode = True
                    refine_enable = False
                    denoise = 1.0
                    shift_video, shift_audio = 12.0, 3.0
                    print(f"[H3 Extender] v14.172 FastH3 Omni 8步单采(渲染管道): 跳过二采, 一采 8 步蒸馏直出")
            elif _rp_mode == "QAD-v2-8步":
                # v14.201 (2026-10-25): FastH3-QAD-v2 —— 2026-10-20 海螺 AI Lab 发布,
                # 量化感知蒸馏整套 NVFP4(118GB→30GB, 质量不降反升)。8 步蒸馏直出
                # 单采(同 Omni 管道, 复用 7115 一采钳制健康区防 OOM); shift 10/3 为
                # 官方 V2 NVFP4 schedule(区别于 Omni 12/3, 不可混用); 需 Loader 换
                # QAD-v2 整套 NVFP4 模型 + BlockSparseAttention VSA keep_percent=10,
                # VAE 可选 36层(1.29GB 高质量)/8层(0.31GB 快15x) 新 NVFP4 解码器。
                steps, refine_steps, tile_count, refine_denoise = 8, 2, 4, 0.5
                if not omni_8step_mode:
                    omni_8step_mode = True
                    refine_enable = False
                    denoise = 1.0
                    shift_video, shift_audio = 10.0, 3.0
                    print(f"[H3 Extender] v14.201 QAD-v2-8步(渲染管道): 跳过二采, 一采 8 步蒸馏直出, "
                          f"shift 10/3 (官方 QAD-v2 NVFP4 schedule; Loader 需 QAD-v2 整套 NVFP4 模型)")
            elif _rp_mode == "直播带货（全自动）":
                # v14.202 (2026-10-25): 直播带货 ref_audio 一站式档。
                # 用户诉求"选中这一档后所有设置按固定配方, 手动设置全部无效"。
                # 配方 = v3 参考音频版工作流(v14.200 修复后)的已验证参数:
                #   一采 12 步(官方音频≥12步下限) + 二采 4 步 denoise 0.55
                #   + 3D latent upscaler x2.0(输出 2 倍像素) + 音频重绘 0.7
                #   (二采 4 步时由 v14.196 自动锁一采 12 步音频, 不重画)
                #   + shift 12/3 + TST tau 0.2 + 分块二采 4x128
                #   + audio_context_length=0(不把上一段语音当音频上下文)
                #   + clip2 起关闭 motion context(硬切段不再做 2s 渐变 → 首帧无拖影)
                # width/height 不锁: 分辨率决定一采像素, 锁死 1920 会让一采
                # 直接涨到 1920x1088(耗时 4x), 与用户"15秒必须 1 小时内"冲突。
                steps, refine_steps, tile_count, refine_denoise = 12, 4, 4, 0.55
                refine_enable = True
                refine_audio_denoise = 0.7
                refine_upscale_factor = 2.0
                refine_upscaler_model = "minimax_h3_latent_upscaler_3d_fp32.pth"
                refine_align_to = 40
                shift_video, shift_audio = 12.0, 3.0
                dual_track_shift = True
                denoise = 1.0
                context_length = "39"
                audio_context_length = 0
                tiled_refine = False
                tile_overlap = 128
                refine_mem_mode = "spatial (分块,兼容)"
                selflift_tst_enable = True
                selflift_tst_tau = 0.2
                upscale_per_clip = True
                upscale_final = True
                upscale_mode = "质量优先"
                upscale_engine = "dlss5"
                upscale_factor = 2.0
                _up_factor, _up_engine = _ff_resolve_upscale_mode(
                    upscale_mode, upscale_factor, upscale_engine
                )
                output_mode = "both"
                output_image_audio = True
                one_shot_mode = "off (分镜模式)"
                one_shot_enabled = False
                one_shot_single_pass = False
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                scheduler = "simple"
                print("[H3 Extender] 🛒 直播带货(全自动)档: 12+4 / denoise 0.55 / latent x2.0 / "
                      "音频重绘 0.7 / shift 12-3 / TST 0.2 / 分块 4x128 / audio_context_length=0 / "
                      "clip2+ 关闭上下文 —— 除分辨率外手动参数全部由本档接管")
            elif _rp_mode == "FastH3 Omni × SelfLift 超分":
                # v14.211 (2026-10-26): B站《FastH3 Omni 全流程教学》(BV1rtnQ6qErJ) 配方落地。
                # FastH3 Omni 8 步蒸馏 + SelfLift 渐进式超分 (替代"单采 8 步 + 外部超分"):
                #   一采 4 步低分辨率(≈0.4x 搭骨架) -> 3D latent 放大 -> 二采 4 步高分辨率精修,
                #   总 8 NFE 仍满足 Omni 8 步蒸馏契约。
                # 注意力: 建议把工作流 BlockSparseAttention(VSA) 换成 sol-attn —— 默认 VSA 偏暗偏闷,
                #   换 sol-attn 画面瞬间清亮通透且速度不变。本档只改采样管道, 换节点需在工作流层做。
                # 模型: Loader 需换 fasth3_omniref_8step_pruned_int8_convrot.safetensors。
                steps, refine_steps, tile_count, refine_denoise = 4, 4, 4, 0.5
                refine_enable = True
                # 一采 = 目标分辨率 / factor -> 2.5 即一采 ≈0.4x 搭骨架, 再由 3D latent 放大回全分辨率
                refine_upscale_factor = 2.5
                shift_video, shift_audio = 12.0, 3.0
                denoise = 1.0
                selflift_tst_enable = True
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                print("[H3 Extender] 🚀 FastH3 Omni × SelfLift 超分: 一采 4 步(≈0.4x)搭骨架 -> 3D latent 放大 -> "
                      "二采 4 步高分辨精修 (总 8 NFE); 确认 Loader=fasth3_omniref_8step_pruned_int8_convrot "
                      "+ 注意力换 sol-attn(替代 VSA)。")
            else:
                _rp_handled = False
            if _rp_handled:
                print(f"[H3 Extender] v14.172 渲染管道: {_rp_mode} -> 一采steps={steps} 二采steps={refine_steps} tile={tile_count} denoise={refine_denoise} (速度档不叠加)")
                speed_preset = "custom"  # 防下方 speed_preset 分支再覆盖配方档参数
        # v14.182: 双采2K 档 —— 解码用 HyperVAE 2x (encoder 16x 不变, decoder 32x
        # pixel_shuffle 2x)。整体替换 vae: encode 路径(参考图/conditioning)输出
        # 与原生 VAE 完全一致(权重含完整 encoder, encoder_unchanged=True), decode
        # 路径自动输出 2x 像素。权重自动探测 models/vae 中 hyper*2x* 文件;
        # 加载失败回退原生 vae 并降级提示(不崩)。
        if _rp_mode == "双采2K（HyperVAE 2x 解码）":
            _hv2x_path = None
            try:
                for _hv_dir in folder_paths.get_folder_paths("vae"):
                    for _hv_file in os.listdir(_hv_dir):
                        _hv_l = _hv_file.lower()
                        if _hv_l.endswith(".safetensors") and ("hyper" in _hv_l or "2x" in _hv_l):
                            _hv2x_path = os.path.join(_hv_dir, _hv_file)
                            break
                    if _hv2x_path:
                        break
            except Exception:
                _hv2x_path = None
            if _hv2x_path:
                try:
                    from bsai_h3_hypervae_2x import load_hyper_vae_2x as _load_hv2x
                    _hv_vae, _hv_report = _load_hv2x(_hv2x_path)
                    _hv_vae.model_name = os.path.basename(_hv2x_path)  # ref2va cache key 区分
                    vae = _hv_vae
                    print(f"[H3 Extender] v14.182 双采2K: HyperVAE 2x 解码已装载 ({os.path.basename(_hv2x_path)}, "
                          f"decode_scale=2x, encode_scale=16x, 全程只解码一次)")
                except Exception as _hve:
                    print(f"[H3 Extender] ⚠️ v14.182 双采2K: HyperVAE 2x 加载失败, 回退原生 VAE: {_hve}")
                    vae = vae  # 保持原生
            else:
                print(f"[H3 Extender] ⚠️ v14.182 双采2K: models/vae 未探测到 HyperVAE 2x 权重 "
                      f"(hyperVAEKrea2Minimax_v20MinimaxX2Upscale.safetensors), 回退原生 VAE 解码(像素 1x, 档位不生效)")
        if speed_preset == "极速":
            # v1.85: 二采 2->3 步 + denoise 0.55->0.5. 写实动态(打斗)场景 2 步二采
            # 在 55% 重噪下收敛不足导致画面发糊, 3 步收敛更好保留高频细节.
            # 耗时 ~20min/clip(原~15min), 仍比均衡(6+4, ~28min)省 ~28%.
            steps, refine_steps, tile_count, refine_denoise = 4, 3, 4, 0.5
        elif speed_preset == "均衡":
            steps, refine_steps, tile_count, refine_denoise = 6, 4, 4, 0.55
        elif speed_preset == "精细":
            steps, refine_steps, tile_count, refine_denoise = 8, 6, 4, 0.55
        elif speed_preset == "极速-VDN":
            # v1.86: VDN 档 (搭配 VDN 版工作流). 一采固定 8 步(VDN DMD 蒸馏最优步数,
            # 质量≈dense 50 步, 且线性注意力长链更稳), 二采 3 步快速收敛.
            # 需用 VDN 工作流提供 model(UNETLoader+ApplyVDNH3, 跳过 FastH3 LoRA/Sol-Attn).
            # v1.90: 极速档强制关分块——实测 DynamicVRAM 下分块二采 900s/步
            # (0驻留全staged × 4 tile 序列 + overlap 重复计算), 全帧 1 次连续
            # staged 预计 ~400-500s/步. 画质档(均衡/精细/均衡-VDN/精细-VDN)
            # 保留分块防 4K 全幅 OOM. 24GB 卡全帧 DynamicVRAM staged 有兜底.
            steps, refine_steps, tile_count, refine_denoise = 8, 3, 4, 0.5
            if tiled_refine:
                tiled_refine = False
                print(f"[H3 Extender] v1.90 极速-VDN: 强制关分块(全帧二采), 原 tiled_refine=True 已覆盖")
        elif speed_preset == "均衡-VDN":
            # 一采 VDN 8 步 + 二采 4 步: 推荐档, 质量接近精细(FastH3 8+6), 时间省 ~25%.
            steps, refine_steps, tile_count, refine_denoise = 8, 4, 4, 0.55
        elif speed_preset == "精细-VDN":
            # 一采 VDN 8 步 + 二采 6 步: 与 FastH3 精细同画质, 一采更快更稳.
            steps, refine_steps, tile_count, refine_denoise = 8, 6, 4, 0.55
        elif speed_preset == "FastH3-Trim":
            # FastH3 Trim: 42层剪枝模型(nvfp4), 8步一采+4步二采双采.
            # 比V2模型一采快15%, 二采4步细节更丰富(2026-10-13 用户要求 8+4 档).
            steps, refine_steps, tile_count, refine_denoise = 8, 4, 4, 0.45
        elif speed_preset == "FastH3-4步VSA":
            # FastH3 4步VSA: 4步DMD2蒸馏+VSA稀疏注意力LoRA, 配2步二采.
            # 最快速度, 质量略低于8步但远快于50步base.
            steps, refine_steps, tile_count, refine_denoise = 4, 2, 4, 0.45
        elif speed_preset == "Turbo-v4":
            # P1 (2026-10-17): Turbo LoRA v4 step600 EMA. 6步一采(v4 画质舒适区) + 4步二采.
            # v14.173: 8+4/denoise0.45 与渲染管道档对齐 (复杂场景防结构漂移/变形)
            # 双轨迹 shift 12/3 (官方 v4 参数); 建议手动把采样器切到 res_multistep 以贴合官方配方.
            steps, refine_steps, tile_count, refine_denoise = 8, 4, 4, 0.45
            shift_video, shift_audio = 12.0, 3.0
        elif speed_preset == "DMAD-4步":
            # P1 (2026-10-17): DMAD 4-step 蒸馏 LoRA. 4步一采 + 2步二采, shift 12/2,
            # 强制 lcm 采样器(DMAD 官方配方: LCM + simple grid, 无 CFG≈1).
            steps, refine_steps, tile_count, refine_denoise = 4, 2, 4, 0.5
            shift_video, shift_audio = 12.0, 2.0
            if str(sampler_name) != "lcm":
                sampler_name = "lcm"
                print(f"[H3 Extender] DMAD-4步: 采样器强制 lcm (DMAD 官方配方)")
        elif speed_preset == "武戏组合拳":
            # v14.176: 与渲染管道档对齐 — YZ金鱼「终极篇」武戏配方 (BV1LKJm6VELc):
            # 一采6步 + 二采6步(总12步, 武戏拟合更清晰), shift 12/3, euler+simple,
            # 帧数对齐 H3 17 块。旧值 8+4 仍可用但拟合弱于 6+6。
            steps, refine_steps, tile_count, refine_denoise = 6, 6, 4, 0.45
            shift_video, shift_audio = 12.0, 3.0
            _h3_align17 = True
            if str(sampler_name) != "euler":
                sampler_name = "euler"
                print(f"[H3 Extender] v14.176 武戏组合拳: 采样器强制 euler + simple 调度 (YZ终极篇武戏配方)")
        elif speed_preset == "FastH3 Omni 8步单采":
            # v14.172 (2026-10-22): 速度档已移除 Omni 枚举(统一走渲染管道)。
            # 本分支仅兼容 v14.170 遗留旧工作流(速度档仍存有 Omni 值) —— 命中时
            # 同样联动渲染管道, 行为与 v14.170 完全一致; 新工作流请从「渲染管道」
            # 下拉选择 FastH3 Omni 8步单采。
            steps, refine_steps, tile_count, refine_denoise = 8, 2, 4, 0.5
            if not omni_8step_mode:
                omni_8step_mode = True
                _render_pipeline = "FastH3 Omni 8步单采"
                refine_enable = False
                denoise = 1.0
                shift_video, shift_audio = 12.0, 3.0
                print(f"[H3 Extender] v14.172 FastH3 Omni 8步单采(旧速度档遗留值兼容): 渲染管道已切 Omni, 跳过二采, 一采 8 步蒸馏直出")
        elif speed_preset == "QAD-v2-8步":
            # v14.196 (2026-10-25): QAD-v2-8步 也支持速度档遗留值兼容 —— 行为与
            # 渲染管道档完全一致(8 步蒸馏直出单采, shift 10/3 官方 QAD-v2 schedule)。
            # 新工作流请从「渲染管道」下拉选择 QAD-v2-8步。
            steps, refine_steps, tile_count, refine_denoise = 8, 2, 4, 0.5
            if not omni_8step_mode:
                omni_8step_mode = True
                _render_pipeline = "QAD-v2-8步"
                refine_enable = False
                denoise = 1.0
                shift_video, shift_audio = 10.0, 3.0
                print(f"[H3 Extender] v14.201 QAD-v2-8步(旧速度档遗留值兼容): 渲染管道已切 QAD-v2, 跳过二采, 一采 8 步蒸馏直出, shift 10/3 (官方 QAD-v2 NVFP4 schedule)")
        if speed_preset != "custom":
            print(f"[H3 Extender] v1.83 速度预设: {speed_preset} -> 一采steps={steps} 二采steps={refine_steps} tile={tile_count} denoise={refine_denoise} (原={_sp_old})")
        print(f"[H3 Extender] REFINE-PARAMS: enable={refine_enable!r} denoise={refine_denoise!r} steps={refine_steps!r} factor={refine_upscale_factor!r} model={refine_upscaler_model!r} align={refine_align_to!r} audio={refine_audio_denoise!r}")
        unique_id = kwargs.get("unique_id", None)
        stored_prompt_pack_signature = _prompt_pack_signature_from_state(clips_json)
        clips = _parse_clips_json(clips_json)
        merge_output = _merge_output_from_state(clips_json)

        # v1.22: per-clip external prompt overrides (clip_prompt_1..clip_prompt_12).
        # Applied before @图N resolution so asset tags in the override are resolved too.
        for _ci in range(1, 13):
            _pk = f"clip_prompt_{_ci}"
            _pv = kwargs.get(_pk)
            if _pv and _ci - 1 < len(clips) and str(_pv).strip():
                clips[_ci - 1]["prompt"] = str(_pv).strip()
                print(f"[H3 Extender] CLIP {_ci} prompt overridden by external port {_pk}")

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
        else:
            # v2.57 (2026-09-21 fix): 全局提示词为空时强制清空，避免旧缓存污染新脚本。
            # 之前 v1.100 会从 clips_json 读旧全局提示词，导致换脚本后画面还是旧内容。
            global_prompt = None
            print("[H3 Extender] v2.57: 外部全局提示词为空，强制不使用旧全局提示词缓存")

        # Resolve @图N/@视频N/@音频N from connected Asset Library.
        # Include the global prompt as a pseudo-clip so its @图N tags are
        # resolved with the same image numbering as clip prompts.
        if global_prompt:
            print(f"[H3 Extender] global_prompt received (len={len(str(global_prompt))}): '{str(global_prompt)[:80]}'")
            gp_clip = {"prompt": str(global_prompt)}
            resolved_all, resolved_img_paths, resolved_aud_paths, _all_asset_paths = self._resolve_asset_library_refs(
                [gp_clip] + clips, asset_library
            )
            global_prompt = resolved_all[0]["prompt"]
            clips = resolved_all[1:]
            global_asset_paths = _all_asset_paths[0] if _all_asset_paths else []
            clip_asset_paths = _all_asset_paths[1:] if len(_all_asset_paths) > 1 else []
            print(f"[H3 Extender] global_prompt after resolution: '{str(global_prompt)[:80]}'")
        else:
            print("[H3 Extender] no global_prompt connected")
            clips, resolved_img_paths, resolved_aud_paths, clip_asset_paths = self._resolve_asset_library_refs(clips, asset_library)
            global_asset_paths = []
        external_prompt_pack = _normalize_external_prompt_pack(prompt_pack)
        clips, active_prompt_pack_signature, prompt_pack_imported, _prompt_pack_count_changed = (
            _sync_clips_from_prompt_pack(
                clips,
                external_prompt_pack,
                stored_prompt_pack_signature,
            )
        )
        # v14.202: 直播带货(全自动)档强制分镜上下文 —— 只保留 clip1 的上下文,
        # clip2/clip3/clip4... 一律关闭。放在资产解析与 Prompt Pack 同步之后,
        # 确保外部提示词包导入新增的 CLIP 也一并覆盖; 前端 UI 的勾选/分镜脚本
        # 里的 context_enabled 在本档下不生效(用户要求"手动设置全部无效"),
        # 避免硬切段被注入上一段尾部 39 帧后做 ≈2s 渐变, 渐变尾巴落在输出头
        # 12 帧 → 首帧重影/马赛克。
        if _rp_mode == "直播带货（全自动）" and clips:
            _forced = 0
            for _ci, _cc in enumerate(clips):
                _want = (_ci == 0)
                if bool(_cc.get("context_enabled", True)) != _want:
                    _cc["context_enabled"] = _want
                    _forced += 1
            print(f"[H3 Extender] 🛒 直播带货(全自动)档: 上下文强制 clip1=开 / clip2+ 全关 "
                  f"(共 {len(clips)} 个 CLIP, 覆盖 {_forced} 个手动/导入的勾选)")
        owner = str(unique_id if unique_id is not None else "h3_extender")
        _register_render_ctl(owner)

        # ── v14.159 (2026-10-21): 一镜到底 × 歌曲自动分 CLIP ──────────────
        # 结合现有对口型模式的歌曲驱动逻辑(_split_lip_audio_by_clips 按 CLIP
        # 时长切音频): one_shot_mode=on 且连接 lip_audio 歌曲时, 按
        # one_shot_clip_duration(每段目标秒数) 自动把歌曲时长均分为目标 CLIP
        # 数量并自动补齐/对齐 CLIP 卡片与每段时长, 再交给现有 lip_audio 切分
        # 与一镜到底渲染链路。one_shot_clip_duration=0 时关闭自动分。
        if (one_shot_enabled
                and kwargs.get("lip_audio") is not None
                and int(one_shot_clip_duration) > 0):
            try:
                _os_audio = kwargs.get("lip_audio")
                _os_sr = int(_os_audio.get("sample_rate", 32000))
                _os_total = float(_os_audio["waveform"].shape[-1]) / float(_os_sr)
                _os_dur = float(one_shot_clip_duration)
                _os_target = max(1, int(math.ceil(_os_total / _os_dur)))
                _os_cur = len(clips)
                print(f"[H3 Extender] 🎵 一镜到底×歌曲: 歌曲 {_os_total:.1f}s ÷ 每段 {_os_dur:.0f}s "
                      f"→ 自动目标 CLIP 数 {_os_target} (原 {_os_cur})")
                if _os_cur != _os_target:
                    # 提示词模板: 第一个含提示词的 CLIP; 无则用内置一镜到底跟随模板
                    _os_tpl = None
                    for _c in clips:
                        if str(_c.get("prompt") or "").strip():
                            _os_tpl = dict(_c)
                            break
                    _os_tpl_prompt = ""
                    _os_tpl_name = ""
                    if _os_tpl is not None:
                        _os_tpl_prompt = str(_os_tpl.get("prompt") or "")
                        _os_tpl_name = str(_os_tpl.get("name") or "")
                    else:
                        _os_tpl_prompt = (
                            "镜头持续跟随主体运动，不切场、不转场、一镜到底，"
                            "主体在画面中连续完成动作，空间与时间连续，"
                            "音乐情绪与画面节奏同步。"
                        )
                    # 每段时长: 前 target-1 段 = 目标时长, 最后一段 = 歌曲剩余
                    _os_seg_dur = [_os_dur] * _os_target
                    _os_last = _os_total - _os_dur * (_os_target - 1)
                    if _os_last > 0.5:
                        _os_seg_dur[-1] = _os_last
                    _new_clips = []
                    for _i in range(_os_target):
                        if _i < _os_cur:
                            _nc = dict(clips[_i])
                        else:
                            _nc = dict(_default_clip(_i))
                            if _os_tpl is not None:
                                for _k in ("prompt", "name"):
                                    if _k in _os_tpl:
                                        _nc[_k] = _os_tpl[_k]
                            _nc["prompt"] = _os_tpl_prompt
                            _nc["name"] = (f"{_os_tpl_name}_{_i + 1}" if _os_tpl_name else f"CLIP{_i + 1}")
                        _nc["duration"] = float(_os_seg_dur[_i])
                        _nc["context_enabled"] = True
                        _new_clips.append(_nc)
                    clips = _new_clips
                    print(f"[H3 Extender] 一镜到底×歌曲: 已自动设置 {len(clips)} 个 CLIP, "
                          f"每段时长 {[round(float(c.get('duration', 0)), 1) for c in clips]}")
                else:
                    print(f"[H3 Extender] 一镜到底×歌曲: CLIP 数量已与歌曲匹配, 保持 {_os_cur} 个")
            except Exception as _os_err:
                print(f"[H3 Extender] 一镜到底×歌曲自动分CLIP失败(保持手动CLIP数): {_os_err}")
        # CLIP 自定义选择生成：None=全部；set=指定渲染范围。
        # 单选（如 2）语义：从该 CLIP 起连续渲染到结束（自动依次生成后续 CLIP），
        # 除非用户手动暂停或手动选择「合并输出」，才执行合并。多选/范围保留原「仅渲染指定段」语义。
        select_override = None
        if int(clip_select_enable):
            select_override = _parse_clip_select(clip_select, len(clips))
            # v2.62: 输入无法解析时明确告警（避免误以为已选择却静默渲染全部）
            if select_override is None and str(clip_select or "").strip().lower() not in ("", "all"):
                print(f"[H3 Extender] WARNING: clip_select='{clip_select}' 无法解析（支持 all / 1,3 / 2-5 / 3,5,7 / 7-10），已回退为渲染全部 CLIP")
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

        # v2.72: 恢复缓存续渲染——前端「恢复缓存」按钮只复制快照文件, 无法把
        # validated 标记写进工作流 json。按钮已写 .restored_marker 标记文件,
        # 本次渲染以磁盘 manifest(快照内已渲染段 validated=True) 为准同步 clips,
        # 跳过已恢复的 CLIP 从下一个继续渲染; 消费后清除标记, 下次无标记则按
        # 正常全量流程(不改变既有语义)。
        _marker = Path(manifest_path).with_suffix(".restored_marker")
        if _marker.exists():
            try:
                _rm = _load_manifest_from_paths(data_path, manifest_path) or manifest
                _rm_segs = _rm.get("segments", []) if isinstance(_rm, dict) else []
                _synced = 0
                for _i in range(min(len(clips), len(_rm_segs))):
                    if bool(_rm_segs[_i].get("validated", False)) and not clips[_i].get("validated", False):
                        clips[_i]["validated"] = True
                        _synced += 1
                if _synced:
                    print(f"[H3 Extender] v2.72 恢复缓存续渲染: 同步 {_synced} 段 validated, "
                          f"跳过已渲染 CLIP, 从 CLIP {_synced + 1} 继续")
                else:
                    print(f"[H3 Extender] v2.72 恢复缓存续渲染: 磁盘 manifest 无已渲染段, "
                          f"本次按正常全量渲染")
                _marker.unlink(missing_ok=True)
            except Exception as _re:
                print(f"[H3 Extender] v2.72 恢复标记处理失败: {_re}")

        # v1.98: 一键恢复缓存——从最近一次自动快照恢复主链，
        # 已渲染的 CLIP 无需从 clip1 重新渲染补链；执行完成后前端自动复位开关。
        restore_cache_done = False
        if int(restore_cache):
            _rc_ok, _rc_count, _rc_kind, _rc_ts = _restore_latest_backup(data_path, manifest_path)
            if _rc_ok:
                _restored_manifest = _load_manifest_from_paths(data_path, manifest_path) or manifest
                # v1.98d: 恢复后立即分辨率预检——latent 链不能跨分辨率复用。
                # 备份分辨率 ≠ 当前渲染设置时回滚恢复并给出明确指引，
                # 避免"恢复成功 → 又被分辨率清链 → 从 clip1 补渲染"。
                _res_ok = True
                try:
                    _bk_res = _resolution_from_manifest(_restored_manifest)
                    if _bk_res is not None:
                        if str(resolution_mode or "") == "manual":
                            _tgt_w, _tgt_h = _manual_effective_resolution(width, height)
                            _tgt_res = {"width": _tgt_w, "height": _tgt_h}
                        else:
                            _tgt_res = _resolve_generation_resolution(
                                resolution_mode, megapixels, width, height, kwargs.get("refs") or []
                            )
                        # v2.71 fix: 链存的是「放大后 latent」（一采 960x544 latent 60x34
                        # 经 refine ×2.0 -> 120x68），备份"像素"不能用 geometry×16(=1920x1088)
                        # 与当前一采设置直接比（旧逻辑在 960x544 一采下永远不匹配，
                        # 恢复必被取消）。改为 latent 几何语义比较：
                        #   备份 latent(w/h) vs 当前一采 latent(÷16) × refine 倍率。
                        _bk_geom = _restored_manifest.get("geometry") if isinstance(_restored_manifest, dict) else None
                        _bk_lw = int(_bk_geom.get("video_w", 0)) if isinstance(_bk_geom, dict) else 0
                        _bk_lh = int(_bk_geom.get("video_h", 0)) if isinstance(_bk_geom, dict) else 0
                        _res_mismatch = False
                        if _bk_lw > 0 and _bk_lh > 0:
                            _rfu_rc = float(refine_upscale_factor) if bool(refine_enable) else 1.0
                            _tgt_lw = max(1, int(_tgt_res["width"] // 16))
                            _tgt_lh = max(1, int(_tgt_res["height"] // 16))
                            _res_mismatch = (
                                int(_bk_lw) != int(round(_tgt_lw * _rfu_rc))
                                or int(_bk_lh) != int(round(_tgt_lh * _rfu_rc))
                            )
                        else:
                            _res_mismatch = (
                                int(_bk_res["width"]) != int(_tgt_res["width"])
                                or int(_bk_res["height"]) != int(_tgt_res["height"])
                            )
                        if _res_mismatch:
                            _res_ok = False
                            _rb_ok, _rb_count, _rb_kind, _rb_ts = _restore_latest_backup(data_path, manifest_path)
                            print(f"[H3 Extender] v1.98d 恢复缓存已取消: 备份 latent {_bk_lw}x{_bk_lh} "
                                  f"≠ 当前设置 {_tgt_res['width']}x{_tgt_res['height']}（latent "
                                  f"{_tgt_lw}x{_tgt_lh} × refine {_rfu_rc:.1f} = "
                                  f"{int(round(_tgt_lw * _rfu_rc))}x{int(round(_tgt_lh * _rfu_rc))}），"
                                  f"几何不同无法复用 latent 链。"
                                  f"请把分辨率参数改回一采 {_bk_lw // 2 * 16}x{_bk_lh // 2 * 16}（latent 与备份一致）后重新运行；"
                                  f"或确认使用新分辨率后正常渲染（将重新生成全部缓存）。"
                                  f"{'已回滚恢复前状态' if _rb_ok else '回滚失败，请手动检查主链缓存'}")
                except Exception as _e:
                    print(f"[H3 Extender] v1.98d 恢复缓存分辨率预检跳过: {_e}")
                if _res_ok:
                    manifest = _restored_manifest
                    for _i, _cfg in enumerate(clips):
                        if _i < _rc_count:
                            _cfg["validated"] = True
                    restore_cache_done = True
                    print(f"[H3 Extender] v1.98 恢复缓存: {_rc_count} 段已恢复({_rc_kind} {_rc_ts})，"
                          f"已标记为已渲染，不再从 clip1 补链，仅渲染新增 CLIP")
            else:
                print("[H3 Extender] v1.98 恢复缓存: 无可用备份，本次按正常流程渲染")

        # If cards were removed, trim the physical cache immediately.
        if len(manifest.get("segments", [])) > len(clips):
            print(f"[H3 Extender] v1.97 卡片数减少({len(manifest.get('segments', []))} -> {len(clips)}), 修剪尾部缓存段")
            manifest = _truncate_chain(
                data_path, manifest_path, manifest, len(clips),
                reason=f"cards_removed {len(manifest.get('segments', []))}->{len(clips)}",
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
        clip_ref_plans = None
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

                # Per-CLIP reference planning: each CLIP renders with ONLY the
                # assets its own prompt (plus the global prompt) references.
                # Other CLIPs' scene assets never leak into this shot, fixing
                # scene mixing when a CLIP references just one scene image.
                # <Picture N> tags are renumbered compactly 1..k
                # (k <= MAX_IMAGE_REFS) and both the CLIP prompt and the global
                # prompt are rewritten accordingly, so a <Picture 38> scene
                # reference still occupies a slot even when many global role
                # refs were resolved before it. Own-CLIP refs take priority
                # over global refs when the total exceeds the model's slot cap.
                _pic_re = re.compile(r'<Picture\s+(\d+)>', re.IGNORECASE)
                _gp_text = str(global_prompt or "")

                def _collect_pic_nums(text):
                    seen = []
                    for _m in _pic_re.finditer(str(text)):
                        _n = int(_m.group(1))
                        if _n not in seen and 1 <= _n <= len(asset_tensors):
                            seen.append(_n)
                    return seen

                def _remap_prompt_text(text, old_to_new):
                    def _sub(_m):
                        _n = int(_m.group(1))
                        if _n in old_to_new:
                            return f"<Picture {old_to_new[_n]}>"
                        # Refs beyond the slot cap are dropped entirely (tag
                        # removed, surrounding text kept). Leaving the original
                        # number would collide with a remapped tag and make the
                        # model reference the wrong asset.
                        return ""
                    return _pic_re.sub(_sub, str(text))

                _gp_nums = _collect_pic_nums(_gp_text)
                clip_ref_plans = []
                for _ci, _clip in enumerate(clips):
                    _clip_nums = _collect_pic_nums(_clip.get("prompt", ""))
                    _ordered = _clip_nums[:MAX_IMAGE_REFS]
                    _o2n = {_old: _idx + 1 for _idx, _old in enumerate(_ordered)}
                    _slot_refs = [None] * MAX_IMAGE_REFS
                    for _idx, _old in enumerate(_ordered):
                        _slot_refs[_idx] = asset_tensors[_old - 1]
                    clip_ref_plans.append(
                        {
                            "refs": _slot_refs,
                            "clip_prompt": _remap_prompt_text(_clip.get("prompt", ""), _o2n),
                            # Strict per-CLIP isolation: the global prompt NEVER
                            # injects picture refs into a CLIP. Only the CLIP's
                            # own @图N tags drive its reference images, so assets
                            # mentioned only in the global prompt (other scenes,
                            # other characters) never appear in this shot.
                            "global_prompt": _remap_prompt_text(_gp_text, {}),
                        }
                    )
                    print(
                        f"[H3 Extender] clip[{_ci}] ref plan: {len(_ordered)} assets "
                        f"(strict per-clip, global refs excluded), "
                        f"slots={[i + 1 for i, r in enumerate(_slot_refs) if r is not None]}"
                    )
            else:
                print("[H3 Extender] WARNING: resolved_img_paths was non-empty but no tensors were loaded!")
        else:
            print(f"[H3 Extender] no resolved_img_paths, using UI refs: {sum(1 for r in refs if r is not None)} active")

        # Set ref_audio from asset library if audio refs were resolved.
        # 若 lip_audio 已连接，则忽略 @音频N——对口型模式下 lip_audio 是唯一音频源。
        if resolved_aud_paths and not kwargs.get("ref_audio") and not kwargs.get("lip_audio"):
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

        # v14.171 (2026-10-22): Omni 单采一采钳制到 latent token 健康区。
        # 实测: 一采 1376x768 → latent(172,96,107) ≈ 177万 tokens, Sol-Attn 降级
        # dense 后 24GB 卡 attention 峰值 OOM (3/8 步崩溃, 叠加 lip_audio 音频注入
        # 峰值更高)。Omni 无二采, 直出高分辨率的代价是 attention 峰值爆炸;
        # 正确做法: 一采钳制 ≤ 960x544 (873,120 tokens, 与 v14.164 二采分块健康区
        # 同源), 最终高清由用户侧 upscale_final 超分链兜底 (保真放大, 无二采伪影)。
        if omni_8step_mode:
            _omni_max_px = 960 * 544  # Omni 一采健康像素上限
            _area = resolved_width * resolved_height
            if _area > _omni_max_px:
                _s = (_omni_max_px / float(_area)) ** 0.5
                _nw = max(32, int(round(resolved_width * _s / 32)) * 32)
                _nh = max(32, int(round(resolved_height * _s / 32)) * 32)
                # 等比取整后可能仍略超上限, 逐档 32px 收紧到像素上限内
                while _nw > 32 and _nh > 32 and _nw * _nh > _omni_max_px:
                    if _nw > _nh:
                        _nw -= 32
                    else:
                        _nh -= 32
                print(f"[H3 Extender] v14.171 Omni 一采钳制: {resolved_width}x{resolved_height} "
                      f"({_area/1e6:.2f}MP, latent {int(resolved_width/8)*int(resolved_height/8)*107:,} tokens)"
                      f" -> {_nw}x{_nh} (latent {int(_nw/8)*int(_nh/8)*107:,} tokens, 24GB 健康区; "
                      f"高清由 upscale_final 超分兜底)")
                resolved_width, resolved_height = _nw, _nh
                resolution["width"] = _nw
                resolution["height"] = _nh
                resolution["requested_width"] = _nw
                resolution["requested_height"] = _nh
            elif _area < _omni_max_px:
                # v14.212 (fix): 保底判据由"单边"改为"面积" —— 旧逻辑 (宽<960 或 高<544)
                # 会把竖版 544x960 (面积 522,240 本已 = 健康区上限 960x544) 误判为"太小",
                # 按宽度凑到 960 后高度等比跟到 1696 -> 960x1696 (1.63MP, ~2.7M tokens),
                # 一采每步 350s。改按面积等比放大: 面积达标即不动, 仅真正偏小的才提到健康区。
                _s = (_omni_max_px / float(_area or 1)) ** 0.5
                _nw = max(32, int(round(resolved_width * _s / 32)) * 32)
                _nh = max(32, int(round(resolved_height * _s / 32)) * 32)
                while _nw > 32 and _nh > 32 and _nw * _nh > _omni_max_px:
                    if _nw > _nh:
                        _nw -= 32
                    else:
                        _nh -= 32
                print(f"[H3 Extender] v14.212 Omni 一采保底: {resolved_width}x{resolved_height} "
                      f"({_area/1e6:.2f}MP) -> {_nw}x{_nh} (官方健康区 {_omni_max_px/1e6:.2f}MP, 直出更清晰)")
                resolved_width, resolved_height = _nw, _nh
                resolution["width"] = _nw
                resolution["height"] = _nh
                resolution["requested_width"] = _nw
                resolution["requested_height"] = _nh

        # v14.157: 声明的最终输出尺寸必须尽早落盘。
        # 逐段 MP4 解码靠 manifest 里的 output_width/height 才会把"二采被
        # 显存预算降级"的段重采样回声明像素；旧实现只在本函数收尾前写这两个
        # 键，续跑/恢复出来的链常常拿不到，于是成片停在 1440x800 而不是
        # 声明的 1920x1088（人脸直接糊掉）。这里在渲染开始前就写一次。
        try:
            _decl_out_f = max(1.0, float(refine_upscale_factor)) if bool(refine_enable) else 1.0
            # v14.182: 双采2K 档声明输出尺寸计入 HyperVAE 2x 像素翻倍 (latent
            # factor=1.0 不放大, 但解码输出 = 一采像素 × 2)。
            _decl_out_f = _decl_out_f * float(_hv2x_decl)
            manifest["first_pass_width"] = int(resolved_width)
            manifest["first_pass_height"] = int(resolved_height)
            manifest["declared_refine_factor"] = float(_decl_out_f)
            manifest["output_width"] = int(round(float(resolved_width) * _decl_out_f))
            manifest["output_height"] = int(round(float(resolved_height) * _decl_out_f))
            _write_json_atomic(manifest_path, manifest)
            print(f"[H3 Extender] v14.157 声明输出尺寸: 一采 {resolved_width}x{resolved_height} "
                  f"× 二采 x{_decl_out_f:.1f} -> "
                  f"{manifest['output_width']}x{manifest['output_height']}")
        except Exception as _dow:
            print(f"[H3 Extender] v14.157 声明输出尺寸写入失败(可忽略): {_dow}")

        # v1.98: 渲染前分辨率诊断——断点被清时先看这里, 一眼定位清空原因
        _diag_geom = manifest.get("geometry")
        _diag_cache = cache_resolution or {}
        print(
            f"[H3 Extender] v1.98 分辨率诊断: mode={resolution_mode} mp={megapixels} "
            f"manual=({width}x{height}) guide_idx={requested_resolution.get('guide_ref')} "
            f"guide_dim=({requested_resolution.get('guide_src_width')}x{requested_resolution.get('guide_src_height')}) "
            f"guide_fallback={requested_resolution.get('fallback')} "
            f"requested={resolved_width}x{resolved_height} "
            f"cache_segments={len(segments)} cache_geom={_diag_geom} "
            f"cache_res={int(_diag_cache.get('width', 0) or 0)}x{int(_diag_cache.get('height', 0) or 0)} "
            f"cache_has_segments={cache_has_segments}"
        )

        # v2.70 fix: 双采工作流中链以「放大后 latent」为几何基准（一采 960x544
        # latent 34x60 经 refine ×2.0 -> 68x120 入链），而 requested 是「一采
        # 像素」。旧逻辑用 geometry×16(=1920x1088) 与 requested(960x544) 直接
        # 比较，链上一有段就误判"分辨率变化"而清链。这里改用 latent 几何
        # 对比：cache geometry(video_w/h) vs 一采 latent(÷16) × refine 倍率。
        _rfu = float(refine_upscale_factor) if bool(refine_enable) else 1.0
        _req_lw = max(1, int(resolved_width // 16))
        _req_lh = max(1, int(resolved_height // 16))
        _cg_geom = manifest.get("geometry") if isinstance(manifest, dict) else None
        _cg_lw = int(_cg_geom.get("video_w", 0)) if isinstance(_cg_geom, dict) else 0
        _cg_lh = int(_cg_geom.get("video_h", 0)) if isinstance(_cg_geom, dict) else 0
        # v14.156: 显存预算不足时二采倍率会被静默降级 x2.0 -> x1.5（见 v1.74
        # 预算预检），此时链几何固定为 1.5x。若仍按声明 2.0 比较，每次执行都会
        # 误判"分辨率变化"而清链，用户被迫从 clip1 重跑。这里对唯一一种预算
        # 降级组合（声明 2.0 / 实际 1.5）做精确放行；像素尺寸由解码时的
        # output_width/height 重采样兜底，因此成片尺寸不受影响。
        _cg_implied = (float(_cg_lw) / float(_req_lw)) if _req_lw else 0.0
        _budget_degraded = bool(
            abs(_rfu - 2.0) <= 0.01
            and abs(_cg_implied - 1.5) <= 0.02
            and _req_lh > 0
            and abs(float(_cg_lh) / float(_req_lh) - _cg_implied) <= 0.02
        )
        if _budget_degraded:
            print(f"[H3 Extender] v14.156 链几何匹配显存预算降级结果（声明 x{_rfu:.2f} / "
                  f"实际 x{_cg_implied:.2f}），保留缓存继续续跑；成片将重采样到声明尺寸")
        requested_mismatch = bool(
            cache_has_segments
            and _cg_lw > 0
            and _cg_lh > 0
            and not _budget_degraded
            and (
                int(_cg_lw) != int(round(_req_lw * _rfu))
                or int(_cg_lh) != int(round(_req_lh * _rfu))
            )
        )
        previous_cache_resolution = dict(cache_resolution) if requested_mismatch else None

        if requested_mismatch:
            # Resolution is the one unavoidable global invalidation: latent
            # geometry cannot be mixed inside one sequential disk chain.
            _old_r = cache_resolution or {}
            print(
                f"[H3 Extender] v1.97 分辨率变化, 链已清空(旧 {int(_old_r.get('width',0))}x{int(_old_r.get('height',0))} "
                f"-> 新 {resolved_width}x{resolved_height}); 若这是误操作请恢复参数后从备份恢复链"
            )
            manifest = _truncate_chain(
                data_path, manifest_path, manifest, 0,
                reason=f"resolution {int(_old_r.get('width',0))}x{int(_old_r.get('height',0))}->{resolved_width}x{resolved_height}",
            )
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

        # v1.99: per-clip 资产指纹失效——只重渲引用变化图的 clip。
        # asset_refs_key 是全库路径 hash(顺序敏感), 用户改一张图/加一张图就变;
        # 全库失效 = 改一个角色/场景就全重跑, 不可接受。改为: 每个 clip 记录其
        # 依赖图的(路径+mtime+size)指纹, 只有指纹变化的 clip 标未验证, 其余
        # 完全保留缓存; 全局参考图变化则全部 clip 标未验证(整体风格变了)。
        asset_refs_key = ""
        if resolved_img_paths:
            asset_refs_key = hashlib.sha256(
                "|".join(resolved_img_paths).encode("utf-8")
            ).hexdigest()

        manifest = _load_manifest_from_paths(data_path, manifest_path) or manifest
        manifest = dict(manifest)
        prev_clip_fps = manifest.get("clip_asset_fps") or []
        prev_global_fp = manifest.get("global_asset_fp", "")
        clip_asset_fps = [_clip_asset_fp(ps) for ps in clip_asset_paths]
        global_asset_fp = _clip_asset_fp(global_asset_paths)

        # prompt pack 导入/内容变化 -> 提示词已变, 指纹基准可能错位, 全部标未验证
        if prompt_pack_imported:
            print("[H3 Extender] v1.99 prompt pack 导入/内容变化 -> 全部 clip 标未验证(提示词已变)")
            for cfg in clips:
                cfg["validated"] = False

        # 旧版本链无指纹基准时不触发失效(升级不打扰); 基准在渲染完成后写入
        if prev_clip_fps and clip_asset_fps:
            _chg_global = bool(global_asset_fp) and bool(prev_global_fp) and global_asset_fp != prev_global_fp
            if _chg_global:
                print(f"[H3 Extender] v1.99 全局参考图变化 -> 全部 clip 标未验证(整体风格变了)")
                for cfg in clips:
                    cfg["validated"] = False
            else:
                _chg_clips = [
                    i for i, fp in enumerate(clip_asset_fps)
                    if fp and (i >= len(prev_clip_fps) or prev_clip_fps[i] != fp)
                ]
                if _chg_clips:
                    print(f"[H3 Extender] v1.99 资产变化: {len(_chg_clips)} 个 clip 引用的图变了 -> 仅重渲 clip {[i + 1 for i in _chg_clips]}")
                    for i in _chg_clips:
                        clips[i]["validated"] = False
                        print(f"   clip {i + 1} 当前依赖图: {clip_asset_paths[i]}")
                else:
                    print(f"[H3 Extender] v1.99 资产指纹稳定: {len(clips)} 个 clip 全部保留缓存")
        elif clip_asset_fps:
            print(f"[H3 Extender] v1.99 首次建立 per-clip 资产指纹基准({len(clip_asset_fps)} 个 clip)")

        manifest["asset_refs_key"] = asset_refs_key
        # v1.100: 持久化 per-clip/global 资产路径与全局提示词——刷新/另存后
        # 前端可从 cache_state 恢复资产链接显示, 无需重新输入全局提示词。
        try:
            manifest["clip_asset_paths"] = [list(ps) for ps in clip_asset_paths]
            manifest["global_asset_paths"] = list(global_asset_paths)
            manifest["global_prompt"] = str(global_prompt or "")
        except Exception:
            pass
        manifest["extender_refs_signature"] = refs_signature
        manifest["extender_ref_ids"] = [
            ref.get("id") if isinstance(ref, dict) else None for ref in refs
        ]
        # v14.156: 记录工作流声明的最终输出尺寸（一采像素 × 声明二采倍率）。
        # 二采倍率可能被显存预算静默降级（x2.0 -> x1.5），解码时按此尺寸精确
        # 重采样，保证 per-clip 与 merged 成片像素与工作流声明一致。
        try:
            _decl_f = max(1.0, float(refine_upscale_factor)) if bool(refine_enable) else 1.0
            # v14.182: 双采2K 档计入 HyperVAE 2x 像素翻倍
            _decl_f = _decl_f * float(_hv2x_decl)
            manifest["output_width"] = int(round(float(resolved_width) * _decl_f))
            manifest["output_height"] = int(round(float(resolved_height) * _decl_f))
            manifest["declared_refine_factor"] = float(_decl_f)
        except Exception:
            pass
        manifest["updated_at"] = time.time()
        _write_json_atomic(manifest_path, manifest)

        resolution_mismatch = False

        audio_vae = kwargs.get("audio_vae")
        ref_audio = kwargs.get("ref_audio")
        lip_audio = kwargs.get("lip_audio")
        # v14.174: lip_voice 升级为对口型驱动音频（与 lip_audio 同语义, 且优先）。
        # 用户把 IndexTTS 合成台词音频接入 lip_voice 时, 同样要求:
        #   1) 取消模型自己生成音频  2) 直接用 lip_voice 外部音频驱动对口型。
        # 实现: lip_voice 非 None 时重赋值 lip_audio → 下方切段/AV latent注入/
        # 提示词净化/音频锁定/输出混音替换全链路自动复用, 无需复制代码。
        _lip_voice = kwargs.get("lip_voice")
        if _lip_voice is not None:
            lip_audio = _lip_voice
            print(f"[H3 LipSync] ✅ lip_voice 已连接 → 升级为对口型驱动音频"
                  f"(取消模型自生成音频, 外部音频驱动口型; lip_voice 优先于 lip_audio)")
        else:
            _lip_voice_dummy = None
        _tts_model = kwargs.get("tts_model_TTS模型")
        if _tts_model is not None:
            print(f"[H3 LipSync] 检测到 tts_model 输入连接: tts_model=已连接 — 台词合成请走独立 IndexTTS 节点，合成音频接入 lip_voice 或 lip_audio 驱动口型")
        ref_items = None
        ref_blocks = None
        active_picture_slots = None

        # ── v14.176: 武戏组合拳档 → H3 17 帧块对齐 ──
        # YZ金鱼终极篇帧数公式 max(5, round(a*24)) + (5 - x%17)%17 (即帧数 %17==5),
        # 对齐 H3 video latent 时间结构, 防高动态武戏 latent 时间错位/果冻伪影。
        # 在 lip 切段/时长换算之前统一调整 clips duration, 保证帧数与音频段一致。
        if _h3_align17 and clips:
            for _c in clips:
                _cd = _c.get("duration", 5.0)
                try:
                    _cd_f = float(_cd)
                except (TypeError, ValueError):
                    _cd_f = float(str(_cd))
                _cf = _duration_to_frames(_cd_f)
                _cfa = _cf + (5 - _cf % 17) % 17
                if _cfa != _cf:
                    _c["duration"] = float(_cfa) / float(FPS)
            print(f"[H3 Extender] v14.176 武戏组合拳: clips 帧数已对齐 H3 17 块 "
                  f"({'/'.join(str(_duration_to_frames(float(_c.get('duration', 5)))) for _c in clips)} 帧)")

        # ── Lip Sync Audio 预分割 ──
        # 连接 lip_audio 时，按各 CLIP 时长把完整音频切成 N 段，
        # 每段驱动对应 CLIP 的对口型生成。
        lip_audio_segments = None
        if lip_audio is not None:
            # v14.157: 传入 context_length 帧数 — ctx_on 段按净时长(标称-context)
            # 推进切分, 否则每个段间边界原曲被跳过 context/fps 秒(39帧=1.625s)。
            try:
                _ctx_frames = int(str(context_length))
            except (TypeError, ValueError):
                _ctx_frames = 0
            # ── v14.203: lip_voice(TTS 口播稿) 时长自适应视频总长 ──
            # 稿子时长由 TTS 引擎决定, 与分镜总长不等: 短了每段尾部留静音(口型
            # 提前闭合), 长了台词被段边界截断/被迫追加延续 CLIP。先 atempo 变速
            # 不变调拉到视频总长, 再进切分, 段边界始终落在整句之间。
            if _lip_voice is not None and clips:
                _vid_total_sec = 0.0
                for _c in clips:
                    _d = _c.get("duration", 5.0)
                    try:
                        _d = float(_d)
                    except (TypeError, ValueError):
                        _d = float(str(_d))
                    _vid_total_sec += float(_duration_to_frames(_d)) / float(FPS)
                _fit = _ff_fit_audio_duration(lip_audio, _vid_total_sec)
                if _fit is not None:
                    lip_audio = _fit
            # ── v14.175: 对口型驱动音频超长 → 自动追加延续分镜 CLIP ──
            # 外部音频总时长 > 分镜脚本 clips 总时长时(例: 音频35s / 脚本30s),
            # 自动追加一个延续上一个分镜画面的 CLIP 承载多余音频, 保证外部音频完整性,
            # 尾部台词不再被截断丢弃。
            try:
                _lip_total_dur = float(int(lip_audio["waveform"].shape[-1])) / float(lip_audio["sample_rate"])
            except Exception:
                _lip_total_dur = 0.0
            _sum_clip_dur = 0.0
            for _c in clips:
                _d = _c.get("duration", 5.0)
                try:
                    _sum_clip_dur += float(_d)
                except (TypeError, ValueError):
                    _sum_clip_dur += float(str(_d))
            if _lip_total_dur > _sum_clip_dur + 0.01 and clips:
                _extra_dur = _lip_total_dur - _sum_clip_dur
                _last = clips[-1]
                _new_clip = dict(_last)
                _new_clip["id"] = f"{str(_last.get('id', 'clip'))}_auto_ext"
                _new_clip["duration"] = float(_duration_to_frames(_extra_dur)) / float(FPS)
                # 画面延续上一个分镜: 保留原 prompt — lip 模式下提示词净化会抹掉
                # 唱歌/说话描述, 口型完全由音频驱动, 画面沿用上一分镜构图/场景。
                _new_clip["prompt"] = _last.get("prompt", "")
                _new_clip["validated"] = False
                _new_clip["seed_mode"] = "randomize"
                if _rp_mode == "直播带货（全自动）":
                    # v14.202: 本档 clip2+ 一律无 motion context, 自动追加的
                    # 延续段同样继承该规则(否则会从上一段尾部渐变出首帧拖影)。
                    _new_clip["context_enabled"] = False
                clips.append(_new_clip)
                # v14.189 (fix): 自动追加延续 CLIP 后必须同步扩展 clip_ref_plans ——
                # clip_ref_plans 在函数前部按原始 clips 构建(len=N), 此处 append 使
                # len(clips)=N+1, 渲染循环 loop_end=len(clips) 会访问 clip_ref_plans[N]
                # → IndexError: list index out of range。延续段画面沿用上一分镜构图,
                # 其 <Picture N> 引用与上一分镜相同, 直接继承最后一条 plan 即可。
                if clip_ref_plans is not None:
                    clip_ref_plans.append(dict(clip_ref_plans[-1]))
                    print(f"[H3 Extender] v14.189 clip_ref_plans 同步扩展: {len(clip_ref_plans)-1} 条 -> {len(clip_ref_plans)} 条 (继承最后一条)")
                print(f"[H3 LipSync] ✅ 对口型音频 {_lip_total_dur:.2f}s > 分镜总时长 "
                      f"{_sum_clip_dur:.2f}s → 自动追加延续分镜 CLIP +{_new_clip['duration']:.2f}s "
                      f"(id={_new_clip['id']}), 外部音频完整性已保证")
            lip_audio_segments = _split_lip_audio_by_clips(
                lip_audio, clips, fps=float(FPS), context_frames=_ctx_frames)
            print(f"[H3 LipSync] ✅ 已启用对口型模式，{len(lip_audio_segments)} 段音频已就绪 "
                  f"(context={_ctx_frames}帧, ctx_on 段按净时长推进)")
            # ── 声音参考共存模式（v2.121）──
            # lip_audio 注入 AV latent 锁定口型；ref_audio 保留为音色/风格参考（ref_block）。
            # 两者各司其职：lip_audio 驱动嘴型，ref_audio 告诉模型"这个人的声音应该什么样"。
            if ref_audio is not None:
                print("[H3 LipSync] 🎙️ ref_audio 保留为音色参考（与 lip_audio 共存）")
            # 已缓存(validated)的 CLIP 不会重渲：若它们是接歌之前生成的，口型对不上新歌。
            _cached_count = sum(1 for _c in clips if _c.get("validated"))
            if _cached_count:
                print(f"[H3 LipSync] ⚠️ 注意：{_cached_count} 个 CLIP 当前为缓存(validated)状态，"
                      f"本次不会重新渲染对口型。若它们是接入 lip_audio 之前生成的，"
                      f"请取消这些 CLIP 的 ✅ 校验标记后重渲，否则口型与歌曲不匹配。")

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
                    _tgt_w = int(final_manifest.get("output_width", 0) or 0)
                    _tgt_h = int(final_manifest.get("output_height", 0) or 0)
                    _segs = [dict(x) for x in final_manifest.get("segments", [])]
                    for _si, _seg in enumerate(_segs):
                        if int(_seg.get("frames", 0)) <= 0:
                            continue
                        _need_dec = _seg.get("decoded_mp4_blob") is None
                        _why = "单独生成未产 blob"
                        if (not _need_dec and _tgt_w > 0 and _tgt_h > 0
                                and (int(_seg.get("decoded_mp4_width", 0) or 0) != _tgt_w
                                     or int(_seg.get("decoded_mp4_height", 0) or 0) != _tgt_h)):
                            # v14.156: 旧 blob 是二采降级后的像素（如 1440x800），
                            # 与新段的声明尺寸不一致会导致 concat 失败；解码入口
                            # 会用 ffmpeg 重采样到声明尺寸并保留原音轨。
                            _need_dec = True
                            _why = (f"尺寸 {_seg.get('decoded_mp4_width', '?')}x"
                                    f"{_seg.get('decoded_mp4_height', '?')} -> {_tgt_w}x{_tgt_h}")
                        if _need_dec:
                            print(f"[H3 Extender] merge_output: 校正 segment {_si}（{_why}）")
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
                            # v14.83 per-clip 逐段超分（总开关 + CLIP 级三态优先，clips[si] 含 upscale 字段）
                            if _ff_clip_upscale_enabled(clips[si] if si < len(clips) else None, upscale_per_clip):
                                _ff_upscale_video_file(clip_path, _up_factor, _up_engine,
                                                       upscale_model, upscale_fp16,
                                                       upscale_tile, upscale_batch,
                                                       upscale_face_restore)
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
                            # v14.158: 一镜到底旁支模式 —— 无缝 concat（零转场）。
                            # 段间连续性由 motion context（Add Guide 等效锚点）保证,
                            # 不再叠加 xfade 转场, 接缝处肉眼不可见。
                            if one_shot_enabled:
                                _xcmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
                                         "-c:v", "libx264", "-preset", "fast", "-crf", "17",
                                         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(merged_path)]
                                try:
                                    subprocess.run(_xcmd, check=True, capture_output=True, timeout=600)
                                    print(f"[H3 Extender] saved merged video (一镜到底无缝 concat, {len(clip_paths)} clips): {merged_path}")
                                except Exception as _e:
                                    print(f"[H3 Extender] 一镜到底 seamless concat failed: {_e}")
                            else:
                                # v2.0: 链式 xfade 视频渐变 + acrossfade 音频渐变, N段通用
                                _xcmd, _durs = _ff_build_xfade_merge_cmd(ff, clip_paths, merged_path)
                                if _xcmd is not None:
                                    try:
                                        subprocess.run(_xcmd, check=True, capture_output=True, timeout=600)
                                        print(f"[H3 Extender] saved merged video (xfade chain, {len(clip_paths)} clips): {merged_path}")
                                    except Exception as _e:
                                        print(f"[H3 Extender] xfade chain failed, fallback re-encode concat: {_e}")
                                        _xcmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
                                                 "-c:v", "libx264", "-preset", "fast", "-crf", "17",
                                                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(merged_path)]
                                        try:
                                            subprocess.run(_xcmd, check=True, capture_output=True, timeout=600)
                                        except Exception as _e2:
                                            print(f"[H3 Extender] re-encode concat also failed: {_e2}")
                                else:
                                    # clips too short for xfade → re-encode concat with audio
                                    _xcmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
                                             "-c:v", "libx264", "-preset", "fast", "-crf", "17",
                                             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(merged_path)]
                                    try:
                                        subprocess.run(_xcmd, check=True, capture_output=True, timeout=600)
                                        print(f"[H3 Extender] saved merged video (re-encode concat): {merged_path}")
                                    except Exception as _e:
                                        print(f"[H3 Extender] ffmpeg merge failed: {_e}")

                        # v14.83 全片合并后一次性超分（默认关）
                        if upscale_final:
                            _ff_upscale_video_file(merged_path, _up_factor, _up_engine,
                                                   upscale_model, upscale_fp16,
                                                   upscale_tile, upscale_batch,
                                                   upscale_face_restore)

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

            try:
                _snapshot_chain(data_path, manifest_path, reason="merge-output")
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
                        "restore_cache_done": bool(restore_cache_done),
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

            # 2026-09-05 v1.21: 重渲染单个/多个 CLIP 后，不再保存/截断尾部 latent、
            # 不再自动合并 —— 仅渲染选中的 CLIP，渲染完即暂停静默等待。
            # 用户可手动选择合并输出、继续生成余下全部 CLIP、或选择其他单个 CLIP 重渲染。
            # 主循环依据 validated=False 仅重新采样选中段，其余段保留缓存。
            render_partial = True  # 重渲染 = 部分渲染，禁止自动合并
            if _has_tail_latents_on_disk(owner):
                _delete_tail_latents_from_disk(owner)
                print("[H3 Extender] per-clip replace: deleted stale tail latents from disk")
            saved_tail = None

            # Override validated flags: first_sel 之前的保留缓存（join），
            # 仅选中的 clip 置为未验证 → 重新渲染，其余保留缓存不重渲染。
            # v1.21: 单 clip 重渲染后立即停止，不连续渲染后续 clip，静默等待用户下一步操作。
            for i, cfg in enumerate(clips):
                if i in selected_set:
                    cfg["validated"] = False
                else:
                    cfg["validated"] = True
            # 限制循环只到最后一个选中 clip，选中 clip 渲染完即停止
            loop_end = max(selected_set) + 1
            _sel_list = ",".join(str(s + 1) for s in sorted(selected_set))
            print(f"[H3 Extender] single clip replace: selected_set={sorted(selected_set)} loop_end={loop_end} will re-render clip(s) {_sel_list}, then pause for user action")

        # v2.64: per-clip 独立渲染优先 —— 用户点击卡片「▶ 独立渲染」设置 replace_mode 时，
        # clip_select 范围选择不再生效。否则残留的 clip_select_enable=True 会让循环条件
        # `i not in select_override` 跳过用户指定渲染的 clip（如选 11-30 时点 clip9 ▶ 无效），
        # 且 v2.63 强制启用选择集内所有 clip，导致实际渲染的是选择集而不是用户点的 clip。
        if any_replace and select_override is not None:
            print("[H3 Extender] v2.64: 检测到 per-clip 独立渲染(replace_mode)，忽略 clip_select 范围选择，仅按卡片生成开关渲染。")
            select_override = None

        # v1.17: 前置 latent 链完整性检查 —— 部分选择 / 重渲染时，若磁盘 latent 链
        # 不足以支撑所选段的前置段，自动补渲染缺失段建立完整链（H3 必须依赖前置
        # latent 做 motion context），并明确打印提示，让用户知情而非报错/静默。
        _need_pre = None
        if select_override is not None:
            _need_pre = min(select_override)
        elif any_replace and first_sel > 0:
            _need_pre = first_sel
        if _need_pre is not None:
            try:
                _pre_m = _load_manifest_from_paths(data_path, manifest_path)
                _pre_n = len(_pre_m.get("segments", [])) if _pre_m else 0
            except Exception:
                _pre_m = None
                _pre_n = 0
            if _pre_n < _need_pre:
                try:
                    import os as _os
                    _jz = _os.path.getsize(manifest_path) if _os.path.exists(manifest_path) else None
                    _bz = _os.path.getsize(str(manifest_path) + ".bak") if _os.path.exists(str(manifest_path) + ".bak") else None
                    _dz = _os.path.getsize(data_path) if _os.path.exists(data_path) else None
                    print(f"[H3 Extender] v1.80 cache诊断: json={_jz}字节 bak={_bz}字节 h3cache={_dz}字节")
                except Exception:
                    pass
                _from = max(0, _pre_n)
                if select_override is not None:
                    # v2.62: 补渲染范围收窄到「选中段跨度内」，保持仅渲染指定段语义，
                    # 不再从缺口一路补到末尾（末尾未选中的 CLIP 保留缓存/不重新生成）。
                    _sel_max = max(select_override)
                    _old_sel = set(select_override)
                    select_override = set(range(_from, _sel_max + 1)) | _old_sel
                    _added = sorted(select_override - _old_sel)
                    print(
                        f"[H3 Extender] v2.62 前置 latent 链缺失（磁盘仅 {_pre_n} 段，"
                        f"不足所选 CLIP{_need_pre + 1} 所需的 {_need_pre} 段）：自动补渲染 "
                        f"CLIP {','.join(str(_p + 1) for _p in _added)} 建立完整链，随后仅渲染选中段。"
                    )
                else:
                    # v2.65: per-clip 独立渲染绝不自动补渲染其他 CLIP。
                    # 前置链不足时只警告，CLIP{N} 直接接续现有链末尾渲染（用户明确要求：
                    # 单点 CLIPN 只渲染 CLIPN，不渲染 CLIP1..N-1）。如需完整前置链请先「♻️ 恢复缓存」。
                    print(
                        f"[H3 Extender] v2.65 per-clip 独立渲染前置链不足（磁盘仅 {_pre_n} 段，"
                        f"CLIP{_need_pre + 1} 需 {_need_pre} 段）：按用户要求不补渲染其他 CLIP，"
                        f"CLIP{_need_pre + 1} 将接续现有链末尾渲染；如需完整前置链请先点「♻️ 恢复缓存」。"
                    )

        # v2.62: 中段缺口补齐 —— 选中段跨度内被跳过且磁盘无缓存的 CLIP 必须补渲染，
        # 否则 H3 链式运动上下文断链（后续段会拿错前置 latent）。
        # 典型场景：已有 CLIP1-2 缓存时输入 3,5,7，CLIP4/6 无缓存 → 自动补渲染 CLIP4/6。
        if select_override is not None:
            try:
                _gap_m = _load_manifest_from_paths(data_path, manifest_path)
                _gap_have = len(_gap_m.get("segments", [])) if _gap_m else 0
            except Exception:
                _gap_have = 0
            _sel_max = max(select_override)
            _gap_fill = set()
            for _p in range(_sel_max + 1):
                if _p not in select_override and _p >= _gap_have:
                    _gap_fill.add(_p)
            if _gap_fill:
                _gap_list = ",".join(str(_p + 1) for _p in sorted(_gap_fill))
                select_override = select_override | _gap_fill
                print(f"[H3 Extender] v2.62 中段缺口补渲染: CLIP {_gap_list} 被跳过但磁盘无缓存，为维持 H3 链式运动上下文自动补渲染。")

        # v1.21: 单 clip 重渲染时，如果前置 latent 链缺失（first_sel < 第一个选中 clip），
        # 强制渲染前置 clip（忽略前端 render_enabled=False），建立完整 latent 链。
        # 否则 disk_join 会把选中 clip 错放到索引0，导致预览解码和 Final Decode 失败。
        if any_replace and selected_set:
            _first_selected = min(selected_set)
            if first_sel < _first_selected:
                for _pre_i in range(first_sel, _first_selected):
                    if _pre_i < len(clips):
                        clips[_pre_i]["render_enabled"] = True
                        clips[_pre_i]["validated"] = False
                        print(f"[H3 Extender] v1.21: force render前置 clip {_pre_i + 1} (latent chain missing, first_sel={first_sel})")

        # v2.63: clip_select 权威选择修复 —— 选中集合（含 v2.62 自动补渲染的前置段/中段缺口）
        # 必须真正进入渲染循环。若残留 render_enabled=False（例如此前点「独立渲染▶」/「↻」
        # 留下的旧状态），循环的 `not render_enabled` 条件会静默跳过选中段：前置链补不出来、
        # 选中段不渲染、首个被渲染的 clip 被错放到链索引 0，导致 preview 越界与 Final Decode
        # 错位（典型症状：选了 11-30 却只渲染了 1 个 clip、轨道无输出）。
        # 与 v1.21「强制渲染前置 clip（忽略前端 render_enabled=False）」同一原则：
        # clip_select 显式选择时，选择集内的 render_enabled 一律强制为 True。
        if select_override is not None:
            _sel_force = [
                i for i in select_override
                if i < len(clips) and not clips[i].get("render_enabled", True)
            ]
            if _sel_force:
                for _fi in _sel_force:
                    clips[_fi]["render_enabled"] = True
                print(
                    f"[H3 Extender] v2.63 clip_select 权威选择: 选中集内 {len(_sel_force)} 个 clip 的"
                    f"生成开关处于关闭状态，已强制启用（CLIP {','.join(str(_f + 1) for _f in sorted(_sel_force))}）"
                )

        # Build the accelerated sampling model once for the whole pass.
        sampling_model = model
        # v1.44: 恢复 ff_chunks=2, attn_head_chunks=4 (对齐 Sol-H3 双采极速版).
        # v1.42 降到 chunks=1/head_chunks=2 是因为 unload_all_models() 导致
        # full lowvram 重载, CPU↔GPU 搬运越多 peak 越高. v1.43 已移除
        # unload_all_models(), diffusion 保持 loaded, 不存在 per-layer
        # 搬运开销, 可以安全使用更激进的 chunking 来降低临时张量显存,
        # 给 1.5x 二采 attention workspace 留更多余量.
        sampling_model = _ff_apply_h3_lowvram_patches(
            sampling_model,
            ff_chunks=2,
            ff_seq_threshold=4096,
            attn_head_chunks=4,
        )
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
        _pending_enc = []  # v1.70: async encode 队列 [(done_event, 链内索引, 全局clip索引)]

        # v14.158: 一镜到底旁支模式 —— 强制开启每段 motion context。
        # 电影工厂的 motion context 把上一段 latent 尾部(默认2s)注入本段 conditioning,
        # 等效 B站工作流中官方 Add Guide 节点"把上一段最后一秒作为锚点引导生成"。
        # 一镜到底必须链式衔接，因此无视卡片级 context_enabled 手动关闭，强制为 True。
        if one_shot_enabled:
            _os_forced = [i + 1 for i, _c in enumerate(clips) if not _c.get("context_enabled", True)]
            for _c in clips:
                _c["context_enabled"] = True
            if _os_forced:
                print(f"[H3 Extender] 一镜到底: 强制开启 {len(_os_forced)} 个 CLIP 的段间 motion context (Add Guide 等效): CLIP {','.join(str(x) for x in _os_forced)}")

        # v2.68 fix: 异步预览队列消费提前——encode 完成后立即推送预览/落盘，
        # 不再等下一个 CLIP 渲染完。原逻辑只在每个 CLIP 渲染完成的循环体末尾消费一次；
        # NVENC 编码(约2s)完成时主线程已进入下一 CLIP 渲染，消费被推迟整整一个
        # CLIP(~30min)，导致 per-clip 预览/MP4 延迟出现、用户以为"没生成"。
        def _flush_pending_enc(_paused_break):
            while _pending_enc and _pending_enc[0][0].is_set():
                _ev_done, _j, _gidx = _pending_enc.pop(0)
                if not (not _paused_break and int(output_image_audio)):
                    continue
                try:
                    _cimg, _caud = _decode_clip_to_av(owner, _j, vae, audio_vae, float(FPS))
                    if _cimg is not None and int(_cimg.shape[0]) > 0:
                        out_images.append(_cimg)
                        _av_decoded.add(_j)
                    if _caud is not None:
                        out_audios.append(_caud)

                    # 提取该 CLIP 的 MP4 blob 到持久目录(output/bsai_clips)，
                    # 供 BSAI Premiere Pro / 前端直接引用。
                    # v2.75: _j 是链索引(全局链=clip 索引; 局部链从 first_sel 起),
                    # _gidx 是全局 clip 索引(命名/前端定位用)。
                    _clip_video_path = None
                    _clip_name = clips[_gidx].get("name", f"CLIP{_gidx + 1}") if _gidx < len(clips) else f"CLIP{_gidx + 1}"
                    try:
                        _m = _load_manifest_from_paths(data_path, manifest_path)
                        if _m and _m.get("segments"):
                            _segs = [dict(x) for x in _m["segments"]]
                            if _j < len(_segs):
                                _blob = _segs[_j].get("decoded_mp4_blob")
                                if _blob is not None:
                                    _temp_dir = _clip_output_dir()
                                    _out_name = f"h3_clip_{owner}_{_gidx + 1}_{int(time.time())}.mp4"
                                    _out_path = _temp_dir / _out_name
                                    _copy_blob_to_file(data_path, _blob, _out_path)
                                    _clip_video_path = str(_out_path)
                                    print(f"[H3 Extender] per-clip video ready: clip {_gidx + 1} -> {_out_path}")
                    except Exception as _ve:
                        print(f"[H3 Extender] per-clip video extract failed clip={_j}: {_ve}")

                    _send_clip_av_output(owner, _gidx, len(clips), _cimg, _caud,
                                          video_path=_clip_video_path, clip_name=_clip_name)
                except Exception as _av_err:
                    print(f"[H3 Extender] per-clip AV output failed clip={_j}: {_av_err}")

        # Walk the card list in order. Cached TRUE clips are metadata-only;
        # active clips sample and are written immediately to disk.
        _os_pass_notice_done = False  # v14.185: 一镜到底采样档提示每次执行只打印一次
        # v14.193: 视觉锚点自动记录 —— 渲染前按故事顺序预提取每个分镜的
        # 全部可见视觉元素状态（来源 = 分镜正文, 与渲染提示词同源: 外部 prompt
        # 覆盖优先）。覆盖角色形象/外观/服装/服饰/发型/鞋帽/场景/道具/布景等
        # 所有可见元素。不读取任何手动输入（visual_anchor_notes 已移除），
        # 也不新增输入端口。
        _va_auto_states = []
        for _va_ci, _va_cfg in enumerate(clips):
            _va_src = str(_va_cfg.get("prompt") or "")
            if clip_ref_plans is not None and _va_ci < len(clip_ref_plans):
                _va_ov = (clip_ref_plans[_va_ci] or {}).get("clip_prompt")
                if _va_ov:
                    _va_src = str(_va_ov)
            _va_auto_states.append(_extract_visual_state(_va_src))
        for i, cfg in enumerate(clips[:loop_end]):
            # v2.68 fix: 渲染本 CLIP 之前先消费已完成的 async encode（预览实时推送）。
            _flush_pending_enc(paused_break)
            # v14.185 一镜到底采样纪律校验(首段打印一次) —— 按采样档分流。
            # 单采无缝档对齐 Motion Context V2 实测标准: turbo 蒸馏 LoRA + beta 调度
            # + 6-8 步; 蒸馏链 steps≥20 过采样会烧穿上下文一致性(历史诊断: 接缝
            # PSNR 18.95dB)。双采高清档保留旧 ≥20 校验(非蒸馏底模思路)。
            # steps/scheduler 由本节点 INPUT_TYPES 传入, 此处校验+显式警告, 不强制改写。
            if one_shot_enabled and i == 0:
                try:
                    _os_steps = int(steps)
                    _os_sched = str(scheduler)
                    if one_shot_single_pass:
                        if _os_steps >= 20:
                            print(
                                f"[H3 Extender] ⚠️ v14.185 一镜到底·单采: 当前 steps={_os_steps} ≥ 20 —— "
                                f"turbo 蒸馏链过采样会烧穿上下文一致性(接缝劣化), "
                                f"参考工作流标准为 6-8 步 + beta 调度器, 请降低步数后重渲。"
                            )
                        elif 6 <= _os_steps <= 8 and _os_sched == "beta":
                            print(f"[H3 Extender] ✅ v14.185 一镜到底·单采: steps={_os_steps} + beta 调度 (对齐 Motion Context V2 标准)")
                        else:
                            print(f"[H3 Extender] ℹ️ v14.185 一镜到底·单采: steps={_os_steps} scheduler={_os_sched} "
                                  f"(参考标准: 6-8 步 + beta; 低动态内容可 6 步, 高动态 8 步)")
                        if _os_sched != "beta":
                            print(f"[H3 Extender] ℹ️ v14.185 一镜到底·单采: 当前调度器={_os_sched}, 参考工作流标准为 beta(仅提示, 不强制)")
                    elif one_shot_seamless_dual:
                        # v14.215: 双采无缝档 = 蒸馏底模 8 步一采 + 4 步二采(不是老链的 >=20 步)
                        if _os_steps >= 20:
                            print(
                                f"[H3 Extender] ⚠️ v14.215 一镜到底·双采无缝: 当前 steps={_os_steps} >= 20 —— "
                                f"蒸馏底模过采样会烧穿上下文一致性, 推荐 8 步一采 + 4 步二采。"
                            )
                        else:
                            print(f"[H3 Extender] ✅ v14.215 一镜到底·双采无缝: 一采 steps={_os_steps} "
                                  f"+ 二采 {int(refine_steps)} 步 (denoise {float(refine_denoise):.2f}), "
                                  f"接缝锚点已修复(双采段头锁 keep 真正生效)")
                        if _os_sched != "beta":
                            print(f"[H3 Extender] ℹ️ v14.215 一镜到底·双采无缝: 当前调度器={_os_sched}, "
                                  f"参考工作流标准为 beta(仅提示, 不强制)")
                        if not bool(refine_enable):
                            print("[H3 Extender] ⚠️ v14.215 一镜到底·双采无缝: refine 开关当前是关闭的, "
                                  "二采不会跑(该档不自动改写 refine 开关), 请手动打开 refine 再重渲")
                    elif _os_steps < 20:
                        print(
                            f"[H3 Extender] ⚠️ v14.178 一镜到底·双采: 当前一采 steps={_os_steps} < 20 "
                            f"(官方链上建议 20-25; 音频 8 步最差/≥12 可用)。"
                            f"steps 由工作流节点参数控制, 无法自动强制, 请手动将采样步数提到 ≥20 后重渲。"
                        )
                    else:
                        print(f"[H3 Extender] ✅ v14.178 一镜到底·双采: 一采 steps={_os_steps} (≥20 达标)")
                except Exception:
                    pass
            # Clips with render_enabled=False are skipped entirely: they keep
            # their cached latent (if any) and are not re-rendered.  This lets
            # the user turn off generation for specific clips without removing
            # them from the sequence. CLIP 选择生成时，未选中的同样跳过（保留缓存）；
            # 选中集已在循环前（v2.63）强制 render_enabled=True，不受此条件影响。
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

            if cfg["validated"]:
                if existing:
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
                if single_clip_replace:
                    # v2.66: per-clip 独立渲染——前置段磁盘无缓存时不补渲、不 join，
                    # 直接跳过，让选中 clip 从当前链末尾接续渲染（绝不回 clip1）。
                    print(f"[H3 Extender] v2.66 独立渲染跳过前置段 clip{i+1}: validated=True 但磁盘无缓存，不补渲，选中 clip 将接续现有链末尾")
                    continue
                # validated 标记与磁盘缓存不一致（缓存被清理或路径变更）：
                # 不能静默跳过，否则 H3 链断裂且最终无 cache handle，落入下方采样路径重渲本段。
                print(f"[H3 Extender] clip{i+1} 标记为 validated 但磁盘缓存缺失，自动改为重新渲染")

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

            # Per-CLIP reference selection: this shot only conditions on the
            # assets its own prompt (plus the global prompt's) references.
            # Assets referenced by other CLIPs never leak into this scene.
            _refs_for_clip = refs
            _clip_prompt_for_cond = str(cfg["prompt"] or "")
            _gp_for_cond = global_prompt
            if clip_ref_plans is not None:
                _plan = clip_ref_plans[i]
                _refs_for_clip = _plan["refs"]
                _clip_prompt_for_cond = _plan["clip_prompt"]
                _gp_for_cond = _plan["global_prompt"]
            # Determine ref_audio for this clip.
            # lip_audio 模式：lip_audio_segment 已注入 AV latent 锁定口型，
            # 不需要再作为 ref_block。全局 ref_audio（音色参考）保留为 ref_block。
            if lip_audio_segments is not None:
                if i >= len(lip_audio_segments) or lip_audio_segments[i] is None:
                    raise RuntimeError(
                        f"[H3 LipSync] clip[{i+1}] 缺少对口型音频段（共 {len(lip_audio_segments)} 段，"
                        f"当前 clip 索引 {i}）。请检查 lip_audio 时长是否覆盖全部 CLIP。"
                    )
                _clip_ref_audio = ref_audio  # 音色参考（可能为 None）
                _seg_dur = int(lip_audio_segments[i]["waveform"].shape[-1]) / float(lip_audio_segments[i]["sample_rate"])
                print(f"[H3 LipSync] clip[{i+1}] 对口型驱动音频段: {_seg_dur:.2f}s"
                      + (f"，音色参考: 已连接" if ref_audio is not None else ""))
            else:
                _clip_ref_audio = ref_audio

            ref_items, ref_blocks, active_picture_slots, _ref_cache_hit = _prepare_shared_refs_cached(
                vae,
                audio_vae,
                resolved_width,
                resolved_height,
                str(ref_image_size),
                _refs_for_clip,
                ref_audio=_clip_ref_audio,
                enable_cache=bool(ref_cache),
                cache_bias=_asset_paths_signature(resolved_img_paths) + f"|clip{i}",
            )
            if not _ref_cache_hit:
                print(f"[H3 Extender] _prepare_shared_refs: {len(ref_items)} ref_items, "
                      f"{len(ref_blocks)} ref_blocks, active_picture_slots={active_picture_slots}")

            frame_count = _duration_to_frames(cfg["duration"])
            # v14.177 (fix): 段间衔接断裂根治 —— 渲染帧数必须包含 motion context 帧。
            # 机制: 本段将应用 motion context 时 (i>0 且 context_enabled 且前段有缓存),
            # 模型输出开头的 context 帧是上一段尾画面的延续 (join 解码时按 trim_frames
            # 裁掉, 只保留本段新内容)。旧代码 frame_count 只按目标时长构造 (12s -> 294),
            # motion.apply 返回 trim=39 后被裁 -> 每段净输出 255 帧 = 10.63s < 目标 12s,
            # 段间断帧断音、总时长 804 < 864, 成片每段短 1.37s。
            # 修复: 渲染帧数 = 目标帧 + context 帧 (经 H3 grid %17==5 对齐, 所有
            # context 档 5/22/39/56 裁后净输出均为 289 帧 ≈ 12.04s, 与目标 12s 一致)。
            if (
                i > 0
                and cfg.get("context_enabled", True)
                and previous_proxy is not None
            ):
                try:
                    _ctx_frames = int(str(context_length))
                except (TypeError, ValueError):
                    _ctx_frames = 0
                if _ctx_frames > 0:
                    _tgt_raw = int(round(float(cfg["duration"]) * FPS))
                    frame_count = _align_frame_count(_tgt_raw + _ctx_frames)
                    print(
                        f"[H3 Extender] v14.177 段间衔接: clip[{i+1}] 渲染帧数 = "
                        f"目标 {_tgt_raw} + context {_ctx_frames} -> {frame_count} "
                        f"(解码裁 {_ctx_frames} 后净输出 ≈ {frame_count - _ctx_frames} 帧)"
                    )
            # Prepend global prompt if connected from an external node.
            # The [角色档案]/[道具档案]/[场景档案] inventories are stripped so
            # the render prompt only ever describes THIS CLIP's own content.
            effective_prompt = _clip_prompt_for_cond
            # v14.84 lip-audio: 只净化本段CLIP提示词(全局提示词不受影响),
            # 抹掉唱歌/说话/开口描述, 口型完全由音频驱动。
            if lip_audio_segments is not None:
                _before = effective_prompt[:80]
                effective_prompt = _strip_singing_talk_descriptions(effective_prompt)
                if _before != effective_prompt[:80]:
                    print(f"[H3 LipSync]   clip[{i+1}] 提示词净化(去唱歌/说话描述): '{_before}' -> '{effective_prompt[:80]}'")
            if _gp_for_cond:
                gp = _strip_archive_sections(str(_gp_for_cond)).strip()
                if gp:
                    effective_prompt = gp + "\n" + effective_prompt
            # v14.193: 视觉锚点自动注入（参考 B站短剧导演台 V9 BV1m2HK6DEPX）。
            # 在 effective_prompt 组装早期注入状态快照（global prompt 之后、本段内容
            # 与 lip-audio/一镜到底指令之前），让"延续已建立状态"指令优先被模型读到。
            # 快照内容 = 本分镜前全部已自动记录的全部可见视觉元素状态（自旧到新, 有界）。
            _va_snap = _build_visual_anchor_snapshot(_va_auto_states, i)
            if _va_snap:
                effective_prompt = str(effective_prompt) + _va_snap
                print(f"[H3 Extender] v14.193 视觉锚点 clip[{i + 1}]: 已注入状态快照（自动记录·全部可见元素·延续约束）")
            # v2.120 lip-audio: 强化音频驱动提示词。
            # 参考B站最佳实践: 提示词必须明确告诉模型"人物在跟着音频唱",
            # 否则模型可能 lip-sync to nothing 或乱张嘴。
            if lip_audio_segments is not None:
                _audio_tag = (
                    "\n<Audio 1> 是本段中人物正在演唱的歌曲。"
                    "人物的嘴唇、舌头和下颌必须跟随<Audio 1>的歌声自然开合，"
                    "口型与歌词精确同步，演唱时面部表情随歌曲情绪起伏，"
                    "身体随音乐节奏微微律动。人物正在对着麦克风深情演唱。"
                )
                if "<Audio 1>" not in effective_prompt:
                    effective_prompt = effective_prompt + _audio_tag
            # v14.158: 一镜到底旁支模式 —— 提示词注入。
            # 参考 B站《MinimaxH3 长视频一镜到底工作流》: 提示词写"不切场、
            # 不转场、一镜到底、镜头始终跟随主体运动"。用户已写相关关键词则跳过,
            # 避免与用户自撰镜头指令冲突。
            if one_shot_enabled:
                _os_lower = str(effective_prompt).lower()
                _os_hit = ("一镜到底" in str(effective_prompt)
                           or "one shot" in _os_lower
                           or "不切场" in str(effective_prompt)
                           or "不转场" in str(effective_prompt))
                if not _os_hit:
                    # v14.178 一镜到底全球方案落地 P1-8: 旧版"绝不切场/不转场/镜头跟随"
                    # 纯口号替换为结构化衔接模板 —— 段头微动作承接 + 段尾预埋下一动作 +
                    # 跨段语音连续声明 + 切口标记 <scenetrans>/<cutoff>, 避免模型把"不切场"
                    # 理解成静态画面。中英文双语模板。
                    effective_prompt = str(effective_prompt) + (
                        "\n[One-Shot Continuous Take] "
                        "This clip is a seamless continuation of the same unbroken long take: "
                        "the camera space, lighting direction and subject position carry over "
                        "from the previous clip's tail without any cut or transition. "
                        "On entry: breath steadies, small motion resumes ("
                        "footsteps continue, gaze adjusts, posture settles into the ongoing action). "
                        "At the tail: the subject's pose pre-positions for the next beat of motion, "
                        "so the next clip picks up mid-gesture. "
                        "Voice continues uninterrupted across this boundary — no pause, no breath reset. "
                        "<scenetrans> voice continues uninterrupted <scenetrans> <cutoff>"
                        "\n[一镜到底] 本段为同一条不间断长镜头的延续：机位空间、光照方向与主体位置"
                        "从上一段尾部无缝带入，无任何切场或转场。段头：呼吸渐稳、微小动作自然承接"
                        "(脚步延续、视线微调、姿态汇入正在进行的动作)；段尾：姿态预先摆向下一动作，"
                        "使下一段可从动作中途接上。语音跨此边界连续不断——无停顿、无换气重置。"
                        "<scenetrans> voice continues uninterrupted <scenetrans> <cutoff>"
                    )
                    print(f"[H3 Extender] 一镜到底 clip[{i}]: 已注入结构化衔接模板(段头承接+段尾预埋+<scenetrans>/<cutoff>)")
            # v14.191: 一镜到底 —— 分拍时间标记反切镜指令(始终追加, 单采/双采都生效)。
            # 实测根因(clip1 预览 287 帧): 12s 长段提示词按 "0-3秒/3-6秒/6-9秒/9-12秒"
            # 分拍描述运镜时, 模型把每个分拍当成独立镜头, 在拍点处自行硬切
            # (实测切镜点 2.67s/6.46s ≈ 3s/6s 分拍边界, 场景检测 scene>0.18)。
            # 既有链式机制(噪声延续+头部均匀锁 keep+衔接模板)只锚定段头 ~1s,
            # 对段内中段无约束。此指令显式声明分拍=同一连续运镜的先后阶段,
            # 压制模型在拍点的蒙太奇先验。
            if one_shot_enabled:
                effective_prompt = str(effective_prompt) + (
                    "\n[Single Continuous Take — Hard Rule] "
                    "All time-range descriptions in this prompt (0-3s / 3-6s / 6-9s / 9-12s etc.) "
                    "are consecutive PHASES of ONE single unbroken camera move inside THIS clip — "
                    "they are NOT separate shots. At every phase boundary the camera must glide "
                    "continuously: no cut, no transition, no angle or shot-size jump, no time skip. "
                    "Framing may only evolve smoothly and continuously from phase to phase."
                    "\n[单镜头硬规则] 本段提示词中所有时间段描述(0-3秒/3-6秒/6-9秒/9-12秒等)"
                    "是同一个连续运镜的先后阶段，不是多个镜头。每个阶段边界镜头必须平滑连续滑过："
                    "禁止切镜、禁止转场、禁止机位角度或景别跳变、禁止时间跳跃，"
                    "构图只允许随运镜连续渐变。"
                )
                print(f"[H3 Extender] v14.191 一镜到底 clip[{i}]: 已注入分拍反切镜指令(时间段=同一连续运镜的阶段)")
            print(f"[H3 Extender] clip[{i}] effective_prompt: '{effective_prompt[:120]}'")
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
                            if _mp_has_ck_quant_weights(_lm.model):
                                # v2.121 (round4): 同 _make_ref2va_conditioning 预编码清扫,
                                # 量化模型直接摘除, 不走 partially_unload(共享权重卸不干净)。
                                try:
                                    _mm.current_loaded_models.remove(_lm)
                                except Exception:
                                    pass
                                continue
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

            # v14.162 (2026-10-22 fix): 4090 clip3 CUDA launch failure 修复 ——
            # 等待上一段异步编码线程完全结束再进入本段 TE 文本编码。
            # 实机根因: clip2 的异步编码(后台线程: VAE decode + NVENC)在 clip3 的
            # _make_ref2va_conditioning → TE encode(14.9GB 全量驻留 + comfy_kitchen
            # 量化权重 cast)期间仍在抢占 GPU → CUDA 上下文损坏, 崩在 llama o_proj
            # 的 weight.clone()。修复: 每段 conditioning 前同步等待 pending 编码
            # 全部完成并消费(解码+落盘), 杜绝主线程采样与后台编码并发抢 GPU。
            if _pending_enc:
                try:
                    for _pev_done, _pej, _peg in _pending_enc:
                        _pev_done.wait()
                    _flush_pending_enc(False)
                    print(f"[H3 Extender] v14.162 已等待 {_pej + 1} 段异步编码完成(防 TE 并发抢 GPU)")
                except Exception as _pe_err:
                    print(f"[H3 Extender] v14.162 等待异步编码完成失败(可忽略): {_pe_err}")

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
                semantic_bridge_pack=sb_pack,
            )

            # v2.119: lip_audio 注入 AV latent 音频区 + zero-denoise 锁定
            # 参考 VRGDG Audio Drive: 把歌曲编码后直接塞进 latent 音频区,
            # 采样器无法修改它, 模型必须让画面配合已锁定的音频 → 真正对口型.
            if lip_audio_segments is not None and audio_vae is not None:
                try:
                    _lip_seg = lip_audio_segments[i]
                    _lip_wave = _lip_seg["waveform"]
                    _lip_sr = int(_lip_seg["sample_rate"])
                    _vae_sr = int(getattr(audio_vae, "audio_sample_rate", 32000))
                    if _lip_sr != _vae_sr:
                        _lip_wave = torchaudio.functional.resample(_lip_wave, _lip_sr, _vae_sr)
                    _lip_latent = audio_vae.encode(_lip_wave[:1].movedim(1, -1))
                    # latent["samples"] 是 NestedTensor((video, audio))
                    _samples = latent["samples"]
                    if isinstance(_samples, comfy.nested_tensor.NestedTensor):
                        _video_t, _audio_t = _samples.tensors[0], _samples.tensors[1]
                        # 对齐时间轴长度
                        # v2.122: 改为尾对齐注入。ctx_on 时段头部含 overlap_samples
                        # 重叠(上一段的歌), 旧的头对齐会把这段歌灌进本段音频区 →
                        # 口型整体提前 ~1.2s 错位。尾对齐使注入的本段 audio 行精确
                        # 对应[段起点, 段终点], 多余重叠头自动丢弃, 与解码混音的
                        # overlap 跳过互补; ctx_off(零重叠)时尾对齐==头对齐, 行为不变。
                        _t_target = int(min(_audio_t.shape[-1], _lip_latent.shape[-1]))
                        _lip_rows = int(_lip_latent.shape[-1])
                        if _lip_rows >= _t_target:
                            _lip_cut = _lip_latent[..., -_t_target:]
                        else:
                            _lip_cut = torch.nn.functional.pad(_lip_latent, (_t_target - _lip_rows, 0))
                        _audio_locked = _audio_t.clone()
                        _audio_locked[..., :_t_target] = _lip_cut.to(_audio_t.device)
                        latent["samples"] = comfy.nested_tensor.NestedTensor((_video_t, _audio_locked))
                        # noise_mask: video=1(全去噪), audio=0(锁定不修改)
                        # v14.178 一镜到底全球方案落地 P0-5: 已核对官方网格对齐 ——
                        # 视频 mask 与 video latent 同形状(采样器内部按 2×2 latent patch
                        # 上采样), 音频 mask 整 latent 帧 0=keep/1=regen; 现实现 audio 区
                        # 全 0(锁原音)、video 区全 1, 与官方语义一致, 无需改形状。
                        _vmask = torch.ones_like(_video_t)
                        _amask = torch.zeros_like(_audio_locked)
                        latent["noise_mask"] = comfy.nested_tensor.NestedTensor((_vmask, _amask))
                        print(f"[H3 LipSync]   音频已注入AV latent并锁定: "
                              f"audio_latent={tuple(_lip_latent.shape)}, "
                              f"video_denoise=1.0, audio_denoise=0.0")
                except Exception as _inject_err:
                    print(f"[H3 LipSync]   音频注入AV latent失败(回退参考模式): {_inject_err}")

            trim_frames = None
            # v1.14: previous_proxy 为 None（前段无缓存）时不再 raise，防御性跳过
            # motion context（从当前段独立渲染，链拼接由 disk_join 的 previous_cache 保证）。
            # v2.122: 解除 v2.117b 强制 — 对口型模式下"上下文参考"恢复用户手动控制。
            # ctx_on 时上一段尾部通过 motion context keyframes 注入(视频块+音频尾部),
            # 音频上下文终点精确对齐本段起点; 音频同步由三件套保证:
            #   1) _split_lip_audio_by_clips: ctx_on 段头部切 1.2s 重叠并记录 overlap_samples
            #   2) AV latent 音频注入: 尾对齐(本段行对应[起点,终点], 重叠头丢弃)
            #   3) 解码混音: 按 overlap_samples 跳过段头重叠 → 输出与原始歌曲逐帧对齐
            _applied_ctx = False
            if i > 0 and cfg.get("context_enabled", True) and previous_proxy is not None:
                positive, trim_frames, _, _, _ = motion.apply(
                    positive,
                    latent,
                    previous_proxy,
                    str(context_length),
                    int(audio_context_length),
                )
                _applied_ctx = True
                # v14.178 一镜到底全球方案落地 P0-3: 重叠区噪声延续(HR Endless
                # video_continuation=22 语义)。官方 AddGuide 是 conditioning 语义(采样
                # 仍从空 latent 起), 接缝区模型仍会"重新想象"(诊断: 接缝 PSNR 仅 18.95dB)。
                # 这里在 latent/noise 构造路径把本段头部 overlap 帧直接取上一段尾 latent
                # +10% 扰动, 并在 noise_mask 把视频头部锁 keep(0=不去噪), 使采样器不再
                # 重画接缝区(该区最终被 join trim 裁掉)。与 P0-2 keyframes 注入双保险。
                # v14.187 (fix): 重叠区噪声延续从"一镜到底"扩展到所有上下文衔接段(分镜模式)。
                # 根因: 分镜模式 clip2+ 头部 motion context 走 conditioning(keyframes) 语义,
                # 采样 latent 仍从空噪声起, 模型在接缝区"重新想象" → clip2 前 3~4s 渐进模糊
                # (实测 Laplacian 153 vs clip1 1034, 量化确认 clip2 独有)。锁 keep 上一段尾
                # latent 后, 采样器不再重画接缝区, 前几帧从上一段尾状态延续 → 输出清晰;
                # 被锁区最终仍由 join trim 裁掉, 不进入成片。
                # v14.188 (fix): 分镜模式(场景可跳变)改"渐进锁 keep"——均匀锁 keep 会把上一段
                # 尾画面(如主播直播)强锁到新场景(如蜡烛特写)头部, 输出区前几帧被迫从旧场景
                # 演化 → 过渡帧重影/一帧崩坏(实测: clip2 首帧=主播场景重影马赛克, Laplacian
                # 突变 diff=107)。改为 noise_mask 头部 0.0→1.0 线性渐降: 首步完全 keep(无缝
                # 进入), 逐步放开重绘, 模型前几步从上一段尾状态平滑转向新场景, trim 后输出
                # 区起点已是转向完成的画面(清晰新场景, 无重影)。一镜到底(连续镜头)保持均匀
                # 锁 keep(v14.178 已验证无缝)。
                try:
                    if trim_frames:
                        _n_head = max(1, (int(trim_frames) + 16) // 17)  # 帧→latent步(stride≈17)
                        _prev_samples = previous_proxy.get("samples") if isinstance(previous_proxy, dict) else previous_proxy
                        _tail_v = None
                        if isinstance(_prev_samples, comfy.nested_tensor.NestedTensor):
                            _tail_v = _prev_samples.tensors[0]
                        elif isinstance(_prev_samples, (list, tuple)) and _prev_samples:
                            _last = _prev_samples[-1]
                            if isinstance(_last, dict) and isinstance(_last.get("samples"), comfy.nested_tensor.NestedTensor):
                                _tail_v = _last["samples"].tensors[0]
                        if _tail_v is not None:
                            _smp = latent["samples"]
                            if isinstance(_smp, comfy.nested_tensor.NestedTensor):
                                _vv, _aa = _smp.tensors[0], _smp.tensors[1]
                                _n_head = min(_n_head, _tail_v.shape[2], _vv.shape[2])
                                if _n_head >= 1:
                                    _vv2 = _vv.clone()
                                    _src = _tail_v[:, :, -_n_head:].to(_vv2.device, dtype=_vv2.dtype)
                                    # v14.215: 双采时"上一段尾 latent"是二采放大后的 2x,
                                    # 本段一采 latent 是 1x —— 直接赋值 shape 不匹配会抛异常,
                                    # 整块被 except 吞掉 → 噪声延续 + 段头锁 keep 全部失效 →
                                    # 裁掉重叠区后接缝处画面跳变(双采"接缝风险"的真根因)。
                                    # 这里把锚点按本段 latent 的空间尺寸重采样后再锁 keep,
                                    # 与 motion.apply 对 keyframe 的重采样口径保持一致。
                                    if tuple(_src.shape[-2:]) != tuple(_vv2.shape[-2:]):
                                        try:
                                            _src_r = _src
                                            if _src_r.dim() == 4:
                                                _src_r = _src_r.unsqueeze(0)
                                            _src_r = torch.nn.functional.interpolate(
                                                _src_r,
                                                size=(int(_src_r.shape[2]),
                                                      int(_vv2.shape[-2]),
                                                      int(_vv2.shape[-1])),
                                                mode="trilinear",
                                                align_corners=False,
                                            )
                                            if _src_r.dim() == 5:
                                                _src_r = _src_r.squeeze(0)
                                            _src = _src_r.to(_vv2.device, dtype=_vv2.dtype)
                                            print(f"[H3 Extender] v14.215 接缝锚点重采样: 上一段尾 latent "
                                                  f"{int(_tail_v.shape[-2]) * 16}x{int(_tail_v.shape[-1]) * 16} "
                                                  f"-> 本段 {int(_vv2.shape[-2]) * 16}x{int(_vv2.shape[-1]) * 16} "
                                                  f"(双采二采倍率所致, 已修正段头锁 keep)")
                                        except Exception as _rs_err:
                                            print(f"[H3 Extender] v14.215 接缝锚点重采样失败(可忽略): {_rs_err}")
                                            raise
                                    _vv2[:, :, :_n_head] = _src * 0.9 + torch.randn_like(_src) * 0.1
                                    latent["samples"] = comfy.nested_tensor.NestedTensor((_vv2, _aa))
                                    _m_old = latent.get("noise_mask")
                                    if isinstance(_m_old, comfy.nested_tensor.NestedTensor):
                                        _mv, _ma = _m_old.tensors[0], _m_old.tensors[1]
                                    else:
                                        _mv, _ma = torch.ones_like(_vv2), torch.ones_like(_aa)
                                    _mv = _mv.clone()
                                    if one_shot_enabled:
                                        # 一镜到底(连续镜头): 头部均匀锁 keep, 无缝延续
                                        _mv[:, :, :_n_head] = 0.0
                                        _lock_desc = "均匀锁keep"
                                    else:
                                        # 分镜模式(场景可跳变): 头部渐进锁 keep, 0.0→1.0
                                        # 线性渐降, 首步完全保持(无缝进入), 逐步放开重绘,
                                        # 前几步从上一段尾平滑转向新场景, 无重影/崩坏帧
                                        for _k in range(_n_head):
                                            _mv[:, :, _k] = _k / max(1, _n_head - 1)
                                        _lock_desc = "渐进锁keep(0→1)"
                                    latent["noise_mask"] = comfy.nested_tensor.NestedTensor((_mv, _ma))
                                    _mode_tag = "一镜到底" if one_shot_enabled else "分镜衔接"
                                    print(f"[H3 Extender] v14.188 {_mode_tag}: clip[{i+1}] 头部{trim_frames}帧({_n_head}步)"
                                          f"噪声从上一段尾latent延续(+10%扰动), noise_mask {_lock_desc}")
                except Exception as _seed_err:
                    print(f"[H3 Extender] v14.188 重叠区噪声延续失败(可忽略, 回退纯采样): {_seed_err}")
                if lip_audio is not None:
                    print(f"[H3 LipSync] clip[{i}] 对口型+上下文参考: 前段尾部已注入, 音频重叠区解码时自动跳过(与原始歌曲对齐)")
            elif i > 0 and cfg.get("context_enabled", True) and lip_audio is not None and previous_proxy is None:
                print(f"[H3 LipSync] clip[{i}] 对口型+上下文参考: 前段缓存缺失, 本段独立渲染(trim=0)")
            # v2.117d/v2.122: 本段未应用 motion context 时显式 trim=0 —
            # 绝不能让 disk_join.join 回退默认 22 帧 trim(那会把 clip2+ 自己的
            # 开头裁掉 → 段与段之间累积出空白帧)。ctx_on 且 motion.apply 已执行
            # 时保留其返回的 trim(上下文帧数), 由 join 裁掉上下文头, 与音频
            # overlap 跳过互补对齐。
            # v14.200: 不再限定 lip_audio —— ref_audio(参考音频版)下 clip 关闭
            # context_enabled 时同样必须 trim=0, 否则 join 回退 22 帧, 硬切段
            # 开头 0.9s 会被静默裁掉。
            if not _applied_ctx:
                trim_frames = 0

            _send_extender_progress(
                owner,
                i,
                len(clips),
                "sampling",
                f"Rendering clip {i + 1}/{len(clips)}",
            )

            try:
                _eff_refine = bool(refine_enable)
                # v14.185: 一镜到底·单采无缝 —— 链式 latent 不做二采重绘。
                # Motion Context V2 (BV1T9ho6HEKP) 实测: 双采 latent 续链在接缝
                # 产生像素漂移(段间模糊/抖动), 单采接缝干净(45s+ 零拼接痕迹)。
                if one_shot_enabled and _eff_refine:
                    if one_shot_single_pass:
                        _eff_refine = False
                        if not _os_pass_notice_done:
                            _os_pass_notice_done = True
                            print("[H3 Extender] 一镜到底·单采无缝：已跳过二采（refine），链式 latent 不重绘，"
                                  "接缝零漂移（对齐 Motion Context V2 单遍采样方案）；"
                                  "如需 2K/高清放大请改用「双采高清」档或分镜模式")
                    elif one_shot_seamless_dual:
                        # v14.215: 双采无缝档 —— 二采照跑(1采8步+2采4步), 接缝靠
                        # v14.215 的锚点重采样修复(段头锁 keep 真正生效)。
                        if not _os_pass_notice_done:
                            _os_pass_notice_done = True
                            print("[H3 Extender] ✅ 一镜到底·双采无缝(8+4)：二采照跑"
                                  f"(一采 {int(steps)} 步 + 二采 {int(refine_steps)} 步, denoise {float(refine_denoise):.2f})，"
                                  "v14.215 已修复双采段头锚点(上一段尾 latent 按本段尺寸重采样后再锁 keep)，"
                                  "接缝不再因锁 keep 失效而跳变")
                    elif not _os_pass_notice_done:
                        _os_pass_notice_done = True
                        print("[H3 Extender] ⚠️ 一镜到底·双采高清：二采重采样会在接缝引入像素漂移"
                              "（参考工作流实测），如出现段间模糊/抖动请改用「单采无缝」档")
                # v14.214 (2026-10-26): 采样前强制释放文本编码器(TE)显存 ——
                # 长链从第 2 段起 TE 常驻 8~15GB, 采样前 free 从 22GB 掉到 15GB;
                # 而 H3 DiT 权重 20.6GB 在 24GB 卡上必须走 DynamicVRAM 流式,
                # 余量不足时第一次 int8_linear 权重块 torch.empty 分配失败 →
                # "CUDA error: out of memory"(实测 19 段长链崩在第 2 段第 1 步)。
                # 现有两条释放逻辑都漏了 TE: comfy_kitchen 量化被跳过,
                # free_memory 又只能扫 current_loaded_models(v1.53 块已把 TE 摘除)。
                try:
                    _release_text_encoder(clip, tag=f"clip{i + 1}/{len(clips)}")
                except Exception as _te_rel_err:
                    print(f"[H3 Extender] v14.214 文本编码器释放异常(忽略): {_te_rel_err}")
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
                    refine_enable=_eff_refine,
                    refine_denoise=float(refine_denoise),
                    refine_steps=int(refine_steps),
                    refine_upscale_factor=float(refine_upscale_factor),
                    refine_upscaler_model=str(refine_upscaler_model),
                    refine_align_to=int(refine_align_to),
                    refine_audio_denoise=float(refine_audio_denoise),
                    dual_track_shift=dual_track_shift,
                    shift_video=shift_video,
                    shift_audio=shift_audio,
                    tst_enable=selflift_tst_enable,
                    tst_tau=selflift_tst_tau,
                    tiled_refine=bool(tiled_refine),
                    tile_count=int(tile_count),
                    tile_overlap=int(tile_overlap),
                    refine_mem_mode=("global" if refine_mem_global else "spatial"),
                    temporal_chunk_tokens=int(temporal_chunk_tokens),
                    temporal_overlap_tokens=int(temporal_overlap_tokens),
                    omni_8step_mode=omni_8step_mode,
                    honor_manual_steps=(str(speed_preset) == "custom"),
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

            # v2.66: 每段 commit 后滚动快照——崩溃/误删后最多丢最后一段，
            # 用户点「♻️ 恢复缓存」即可从 latest.snapshot 恢复并续渲。
            try:
                _snapshot_latest(data_path, manifest_path, reason=f"clip-{i+1}-committed")
            except Exception as _sl:
                print(f"[H3 Extender] per-clip 快照异常(可忽略): {_sl}")

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
            print(f"[H3 Extender] DEBUG clip={i} paused_break={paused_break} render_partial={render_partial} output_image_audio={output_image_audio} loop_end={loop_end}")
            if not paused_break:
                try:
                    _send_extender_progress(
                        owner, i, len(clips), "decoding_preview",
                        f"Decoding preview for clip {i + 1}/{len(clips)}",
                    )
                    _ff = _find_ffmpeg()
                    # v2.75: 链结构自适应 - 前置有缓存时链是全局索引
                    # (segments[i]=clip[i+1]); 前置无缓存时(v2.66 接续链末尾)
                    # 链是局部链(segments[0]=clip[first_sel])。按磁盘链实际
                    # 长度判断, 否则 preview/MP4 会解码到错误段
                    # (如单独渲染 clip29 却输出 clip1 内容).
                    _seg_idx = i
                    if single_clip_replace and first_sel is not None and first_sel > 0:
                        try:
                            _seg_m = _load_manifest_from_paths(data_path, manifest_path)
                            _nseg = len(_seg_m.get("segments", [])) if _seg_m else 0
                        except Exception:
                            _nseg = 0
                        if _nseg <= (i - first_sel + 1) and _nseg < i + 1:
                            _seg_idx = i - first_sel
                    print(f"[H3 Extender] preview decode: clip={i} ffmpeg={_ff} vae={type(vae).__name__} audio_vae={type(audio_vae).__name__ if audio_vae else 'None'} seg_idx={_seg_idx}")
                    _lip_seg = None
                    if lip_audio_segments is not None and i < len(lip_audio_segments):
                        _lip_seg = lip_audio_segments[i]
                    _dec_res = _decode_single_clip_preview(
                        owner=owner,
                        clip_index=_seg_idx,
                        vae=vae,
                        audio_vae=audio_vae,
                        fps=float(FPS),
                        ffmpeg=_ff,
                        async_encode=True,
                        lip_audio_segment=_lip_seg,
                    )
                    if isinstance(_dec_res, dict) and _dec_res.get("async"):
                        _pending_enc.append((_dec_res["done_event"], _seg_idx, i))
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
            # v1.21: 单 clip 重渲染也执行 per-clip AV 解码，推送 WebSocket 给 BSAI Premiere Pro。
            # v1.70: AV 输出延后处理——encode 在后台线程, blob 落盘后输出才可读.
            # encode ~55s << 一采+二采 ~29min, 队列首项已完成的先输出(FIFO 保持
            # clip 序); 本段刚启动未完成的留到下段处理. 暂停停止时跳过输出.
            print(f"[H3 Extender] DEBUG AV decode clip={i} cond={not paused_break and int(output_image_audio)} pending={len(_pending_enc)}")
            # v2.68 fix: 统一走 _flush_pending_enc（循环体末尾也消费一次，兜底）
            _flush_pending_enc(paused_break)


        # All clips rendered; the last handle is the active cached prefix
        # expected by Final Decode.
        if previous_handle is None:
            # 循环内没有任何 clip 产出 cache handle：磁盘缓存为空，且所有 CLIP
            # 均被跳过（生成开关关闭，或不在 clip_select 选择范围内）。
            raise RuntimeError(
                "MiniMax H3 Extender: sequence produced no cache handle — "
                "磁盘缓存为空且所有 CLIP 均被跳过。请开启至少一个 CLIP 的生成开关，"
                "或调整 clip_select 范围后重试。"
            )

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
        _was_single_replace = bool(single_clip_replace)
        if single_clip_replace:
            single_clip_replace = False
            # v2.66: 只清 replace_mode 开关，不把未渲染的前置段误标 validated=True。
            # 选中段已在上方标记 validated=True；其余段保持原状态，下次独立渲染 clipM
            # 时由 v2.66 跳过逻辑正确接续现有链末尾。
            for cfg in clips:
                cfg["replace_mode"] = False
            print("[H3 Extender] per-clip replace complete → 仅渲染选中 clip，已出预览，等待用户新指令（无自动合并）")

        final_manifest = _load_manifest_from_paths(data_path, manifest_path)
        # v1.99: 更新实际渲染过的 clip 的资产指纹基准——仅渲染过的更新,
        # 未渲染的保留旧指纹, 下次该 clip 引用的图变化仍能正确触发重渲。
        if final_manifest is not None and clip_asset_fps:
            try:
                _new_fps = list(final_manifest.get("clip_asset_fps") or [])
                while len(_new_fps) < len(clip_asset_fps):
                    _new_fps.append("")
                _fp_changed = False
                for _gi in generated:
                    if _gi < len(clip_asset_fps) and clip_asset_fps[_gi] and _new_fps[_gi] != clip_asset_fps[_gi]:
                        _new_fps[_gi] = clip_asset_fps[_gi]
                        _fp_changed = True
                if _fp_changed:
                    final_manifest = dict(final_manifest)
                    final_manifest["clip_asset_fps"] = _new_fps
                    if global_asset_fp:
                        final_manifest["global_asset_fp"] = global_asset_fp
                    final_manifest["updated_at"] = time.time()
                    _write_json_atomic(manifest_path, final_manifest)
            except Exception as _fp_err:
                print(f"[H3 Extender] v1.99 指纹基准写入失败: {_fp_err}")
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
        # v2.76: 独立渲染(single_clip_replace)完成后也禁止自动合并与一切视频输出,
        # 仅保留 latent 缓存+预览, 静默等待用户下一步指令(合并输出/续跑).
        suppress_auto_merge = bool(render_partial or paused_break or _was_single_replace)
        if suppress_auto_merge:
            print("[H3 Extender] 单独生成/暂停：跳过合并与一切视频输出，仅保留 latent 缓存，静默等待新指令（v1.18）")
        if str(output_mode) != "none" and final_manifest is not None and not single_clip_replace and not _was_single_replace:
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
                        # v14.83 per-clip 逐段超分（总开关 + CLIP 级三态优先）
                        if _ff_clip_upscale_enabled(seg, upscale_per_clip):
                            _ff_upscale_video_file(clip_path, _up_factor, _up_engine,
                                                   upscale_model, upscale_fp16,
                                                   upscale_tile, upscale_batch,
                                                   upscale_face_restore)
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
                        # v14.158: 一镜到底旁支模式 —— 无缝 concat（零转场）。
                        # 段间连续性由 motion context（Add Guide 等效锚点）保证,
                        # 不再叠加 xfade 转场。
                        merge_log = temp_root / f"_merge_{owner}_{uuid.uuid4().hex[:8]}.log"
                        if one_shot_enabled:
                            _xcmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
                                     "-c:v", "libx264", "-preset", "fast", "-crf", "17",
                                     "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(merged_path)]
                            try:
                                with open(merge_log, "wb") as lf:
                                    subprocess.run(_xcmd, stdout=subprocess.DEVNULL, stderr=lf, check=True)
                                print(f"[H3 Extender] saved merged video (一镜到底无缝 concat, {len(clip_paths)} clips): {merged_path}")
                            except Exception as _e:
                                print(f"[H3 Extender] 一镜到底 seamless concat failed: {_e}")
                        else:
                            # v2.0: 链式 xfade 视频渐变 + acrossfade 音频渐变, N段通用
                            _xcmd, _durs = _ff_build_xfade_merge_cmd(ff, clip_paths, merged_path)
                            merge_log = temp_root / f"_merge_{owner}_{uuid.uuid4().hex[:8]}.log"
                            if _xcmd is not None:
                                try:
                                    with open(merge_log, "wb") as lf:
                                        subprocess.run(_xcmd, stdout=subprocess.DEVNULL, stderr=lf, check=True)
                                    print(f"[H3 Extender] saved merged video (xfade chain, {len(clip_paths)} clips): {merged_path}")
                                except Exception as _e:
                                    print(f"[H3 Extender] xfade chain failed, fallback concat: {_e}")
                                    _xcmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
                                             "-c:v", "libx264", "-preset", "fast", "-crf", "17",
                                             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(merged_path)]
                                    try:
                                        with open(merge_log, "wb") as lf:
                                            subprocess.run(_xcmd, stdout=subprocess.DEVNULL, stderr=lf, check=True)
                                        print(f"[H3 Extender] saved merged video (re-encoded concat): {merged_path}")
                                    except Exception as _e2:
                                        print(f"[H3 Extender] merged re-encode also failed: {_e2}")
                            else:
                                # clips too short for xfade → re-encode concat
                                _xcmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
                                         "-c:v", "libx264", "-preset", "fast", "-crf", "17",
                                         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(merged_path)]
                                try:
                                    with open(merge_log, "wb") as lf:
                                        subprocess.run(_xcmd, stdout=subprocess.DEVNULL, stderr=lf, check=True)
                                    print(f"[H3 Extender] saved merged video (re-encoded concat): {merged_path}")
                                except Exception as _e:
                                    print(f"[H3 Extender] merged failed: {_e}")
                    else:
                        shutil.copy2(clip_paths[0], merged_path)

                    if merged_path.exists():
                        # v14.83 全片合并后一次性超分（默认关）
                        if upscale_final:
                            _ff_upscale_video_file(merged_path, _up_factor, _up_engine,
                                                   upscale_model, upscale_fp16,
                                                   upscale_tile, upscale_batch,
                                                   upscale_face_restore)
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
            "restore_cache_done": bool(restore_cache_done),
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
                    temp_dir = _clip_output_dir()
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
        # v1.70: 等待所有 async encode 完成(blob 落盘), final AV 输出才能读全.
        for _enc_entry in _pending_enc:
            try:
                _enc_entry[0].wait(timeout=600)
            except Exception:
                pass
        _pending_enc = []

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

        # ── Lip Sync 模式：最终音频 = lip_audio 主唱(满音量) + 模型环境音(压低垫底) ──
        # 视频由各 CLIP 用对应歌曲片段驱动对口型生成。出片音轨以用户接入的原始歌曲为主
        # (满音量)，模型采样时自生成的环境音/音效不丢弃，压低到 15% 音量垫在歌曲底下
        # 作为 MV 辅助音。
        if lip_audio is not None and lip_audio_segments is not None:
            try:
                import torchaudio as _ta_final
                total_video_frames = int(out_images_t.shape[0])
                video_duration = float(total_video_frames) / float(FPS)

                lip_wave = lip_audio["waveform"].float()
                lip_sr = int(lip_audio["sample_rate"])

                # 模型生成的拼接音频(out_audios_t)，作为垫底环境音
                model_wave = out_audios_t["waveform"].float()
                model_sr = int(out_audios_t["sample_rate"])

                # 歌曲重采样到模型音频采样率
                if lip_sr != model_sr:
                    lip_wave = _ta_final.functional.resample(lip_wave, lip_sr, model_sr)
                # 维度对齐 [B, C, L]
                if lip_wave.ndim == 2:
                    lip_wave = lip_wave.unsqueeze(0)
                if model_wave.ndim == 2:
                    model_wave = model_wave.unsqueeze(0)
                # 声道对齐
                if lip_wave.shape[1] != model_wave.shape[1]:
                    if lip_wave.shape[1] == 1 and model_wave.shape[1] == 2:
                        lip_wave = lip_wave.repeat(1, 2, 1)
                    elif model_wave.shape[1] == 1 and lip_wave.shape[1] == 2:
                        model_wave = model_wave.repeat(1, 2, 1)

                # 长度对齐到视频时长对应的模型采样数
                target_samples = max(1, int(video_duration * model_sr))
                # 歌曲段截/填到 target_samples
                if int(lip_wave.shape[-1]) >= target_samples:
                    lip_aligned = lip_wave[..., :target_samples]
                else:
                    _pad = target_samples - int(lip_wave.shape[-1])
                    lip_aligned = torch.cat([
                        lip_wave,
                        torch.zeros(lip_wave.shape[0], lip_wave.shape[1], _pad,
                                    dtype=lip_wave.dtype, device=lip_wave.device)
                    ], dim=-1)
                # 模型环境音截/填到 target_samples
                if int(model_wave.shape[-1]) >= target_samples:
                    model_aligned = model_wave[..., :target_samples]
                else:
                    _pad = target_samples - int(model_wave.shape[-1])
                    model_aligned = torch.cat([
                        model_wave,
                        torch.zeros(model_wave.shape[0], model_wave.shape[1], _pad,
                                    dtype=model_wave.dtype, device=model_wave.device)
                    ], dim=-1)

                # 混音: 主唱满音量 + 模型环境音 x0.15
                _FINAL_DUCK = 0.15
                final_wave = lip_aligned + model_aligned * _FINAL_DUCK
                out_audios_t = {
                    "waveform": final_wave.cpu().float().contiguous(),
                    "sample_rate": model_sr,
                }
                print(f"[H3 LipSync] ✅ 最终出片音频混音: 歌曲主唱满音量 + 模型环境音 x{_FINAL_DUCK} "
                      f"= {int(final_wave.shape[-1])} samples @ {model_sr}Hz "
                      f"({float(int(final_wave.shape[-1])) / model_sr:.2f}s)")
            except Exception as _lip_err:
                # 兜底：混音失败也要输出歌曲主体，不回退到纯模型音频。
                print(f"[H3 LipSync] ⚠️ 最终混音失败({_lip_err})，直接输出原始 lip_audio 波形兜底")
                try:
                    out_audios_t = {
                        "waveform": lip_audio["waveform"].cpu().float().contiguous(),
                        "sample_rate": int(lip_audio["sample_rate"]),
                    }
                except Exception:
                    pass

        if len(out_images) > 0:
            print(f"[H3 Extender] AV outputs: {int(out_images_t.shape[0])} frames, "
                  f"audio {int(out_audios_t['waveform'].shape[-1])} samples @ "
                  f"{int(out_audios_t['sample_rate'])}Hz")

        # v1.98: 渲染完成自动快照，保护本次渲染成果（可一键恢复）
        try:
            _snapshot_chain(data_path, manifest_path, reason="render-complete")
        except Exception:
            pass

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

# v14.144 启动标记：重启 ComfyUI 后控制台出现此行即确认加载的是最新后端
print("[BSAI-H3-Film-Factory] v14.216 backend loaded (v14.216 prestartup 收录第三方节点 SeedVR2 的启动期崩溃补丁: 它的 import 期 bf16 探针在 ComfyUI 全量环境(同进程已加载 xformers/flash_attn/sageattention/comfy_kitchen 等多个 CUDA 扩展)会触发 native access violation 直接杀掉整个进程 -> ComfyUI 起不来(实测两次崩在同一行); 已把探针换成不分配显存的设备能力查询(sm_80+ 支持 bf16), 并由 prestartup.py 在启动前自动重打, SeedVR2 节点更新后也不用手动补; v14.215 新增一镜到底第三档「双采无缝 (8+4)」: 一镜到底照跑二采(1采8步+2采4步, denoise0.45), 并修复双采接缝漂移根因(段头锁 keep 因上一段尾 latent 为二采 2x 尺寸而 shape 不匹配整块失效, 现按本段尺寸重采样后再锁 keep, 与 motion.apply keyframe 同口径); v14.214 修长链第2段起 CUDA OOM: 每段采样前按身份释放文本编码器 TE 的 GPU 权重(clip.patcher, 量化 TE 被 ck-quant 跳过 + free_memory 扫不到已摘除的 TE), 实测第2段采样前 free 从 15.6GB 回到 22GB; v14.213 前端补丁: web/extender.js 的 render_pipeline cycle/cycleLabels 补上第13档「FastH3 Omni × SelfLift 超分」(此前只加了 .py 选项, 前端自定义下拉仍只画 12 项); v14.212 修 Omni 一采保底: 判据由单边改面积, 修竖版 544x960 被误放大到 960x1696(2.7M tokens, 每步350s)的慢速 bug; v14.211 渲染管道新增档「FastH3 Omni × SelfLift 超分」: Omni 8步蒸馏 + SelfLift 渐进式超分(一采4步≈0.4x搭骨架→3D latent放大→二采4步精修, 总8NFE), 建议 sol-attn 替代 VSA(画面清亮通透); v14.207 二采 OOM fallback 走一采时同步收缩 keyframe 几何 + fallback 非 OOM 异常不再打死 prompt; v14.206 二采 latent 塌陷检测→自动回退一采+告警; 直播带货（全自动）: render_pipeline 第12档, 12+4/denoise0.55/latent x2.0/音频重绘0.7/audio_context_length=0/clip2+ 强制关上下文, 除分辨率外手动参数全部失效; v14.201 QAD-v2-8步; Omni 单采: 13档联动 + guidance 1.0 + 一采钳制≤960x544; 双采: Sol-Attn token上限门350k + 自动分块n6; v14.154 对口型纯歌曲重叠切割先于重采样)")

NODE_DISPLAY_NAME_MAPPINGS = {
    "BSAIH3FilmFactory": "BSAI ComfyUI H3 Film Factory",
    "BSAIMiniMaxH3Extender": "BSAI H3 Extender (Legacy Alias)",
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
        kind=clips  -> ComfyUI output/bsai_clips/（v1.94 持久化 h3_clip_*.mp4，
        重启不清空，Premiere Pro 时间线路径重启后仍有效）"""
        kind = str(request.query.get("kind", "latent")).strip().lower()
        try:
            if kind == "clips":
                d = _clip_output_dir()
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

    @PromptServer.instance.routes.post("/h3_extender/ref2va_cache/clear")
    async def h3_extender_ref2va_cache_clear(request):
        """v1.27: 资产库删除/更换后清空 ref2va 参考图VAE编码磁盘缓存。

        旧资产图片被删除后，其 VAE 编码（Image Latent）若仍留在磁盘缓存，
        可能被同名/同key的新资产命中而错误复用。前端在 bsai-assets-changed
        事件中调用本接口，删除所有 _ref2va_cache/*.pt，下次生成重新编码。
        """
        try:
            root = _ensure_cache_root() / _REF2VA_CACHE_DIRNAME
            removed = 0
            if root.exists() and root.is_dir():
                for p in root.glob("*.pt"):
                    try:
                        p.unlink(missing_ok=True)
                        removed += 1
                    except Exception:
                        pass
            if removed > 0:
                print(f"[H3 Extender] ref2va cache cleared on asset change: removed={removed}")
            return web.json_response({"ok": True, "removed": removed, "path": str(root)})
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    @PromptServer.instance.routes.post("/h3_extender/clear_chain_cache")
    async def h3_extender_clear_chain_cache(request):
        """清空链缓存：删除上一版生成的缓存文件，重新渲染新缓存用。

        清理范围：
        - chain_*.h3cache / chain_*.json（主链缓存）
        - _ref2va_cache/*.pt（参考图VAE编码缓存）
        - _refs/*（参考图缓存）
        - _preview/*（预览缓存）
        - _color_*.log（颜色日志）
        - bsai_clips/h3_clip_*.mp4（已渲染CLIP成片，可选）
        - _clippv_*（临时预览，temp目录）
        """
        try:
            import shutil
            body = await request.json() if request.can_read_body else {}
            clear_clips = bool(body.get("clear_clips", True))

            cache_root = _ensure_cache_root()
            removed = 0
            freed_mb = 0.0
            details = {}

            # 1. 主链缓存 chain_*.h3cache / chain_*.json
            chain_files = list(cache_root.glob("chain_*.h3cache")) + list(cache_root.glob("chain_*.json"))
            for p in chain_files:
                try:
                    sz = p.stat().st_size if p.exists() else 0
                    p.unlink(missing_ok=True)
                    removed += 1
                    freed_mb += sz / (1024 * 1024)
                except Exception:
                    pass
            details["chain_cache"] = len(chain_files)

            # 2. ref2va 缓存
            ref2va_dir = cache_root / _REF2VA_CACHE_DIRNAME
            ref2va_count = 0
            if ref2va_dir.exists() and ref2va_dir.is_dir():
                for p in ref2va_dir.glob("*.pt"):
                    try:
                        sz = p.stat().st_size
                        p.unlink(missing_ok=True)
                        ref2va_count += 1
                        freed_mb += sz / (1024 * 1024)
                    except Exception:
                        pass
            details["ref2va"] = ref2va_count

            # 3. _refs 目录
            refs_dir = cache_root / "_refs"
            refs_count = 0
            if refs_dir.exists() and refs_dir.is_dir():
                for p in refs_dir.rglob("*"):
                    if p.is_file():
                        try:
                            sz = p.stat().st_size
                            p.unlink(missing_ok=True)
                            refs_count += 1
                            freed_mb += sz / (1024 * 1024)
                        except Exception:
                            pass
            details["refs"] = refs_count

            # 4. _preview 目录
            preview_dir = cache_root / "_preview"
            preview_count = 0
            if preview_dir.exists() and preview_dir.is_dir():
                for p in preview_dir.rglob("*"):
                    if p.is_file():
                        try:
                            sz = p.stat().st_size
                            p.unlink(missing_ok=True)
                            preview_count += 1
                            freed_mb += sz / (1024 * 1024)
                        except Exception:
                            pass
            details["preview"] = preview_count

            # 5. _color_*.log
            color_logs = list(cache_root.glob("_color_*.log"))
            for p in color_logs:
                try:
                    p.unlink(missing_ok=True)
                    removed += 1
                except Exception:
                    pass
            details["color_logs"] = len(color_logs)

            # 6. CLIP 成片（可选）
            clips_count = 0
            if clear_clips:
                clips_dir = _clip_output_dir()
                if clips_dir.exists() and clips_dir.is_dir():
                    for p in clips_dir.glob("h3_clip_*.mp4"):
                        try:
                            sz = p.stat().st_size
                            p.unlink(missing_ok=True)
                            clips_count += 1
                            freed_mb += sz / (1024 * 1024)
                        except Exception:
                            pass
            details["clips"] = clips_count

            # 7. 临时预览 _clippv_*
            temp_dir = _comfyui_temp_dir()
            temp_count = 0
            if temp_dir.exists() and temp_dir.is_dir():
                for p in temp_dir.glob("_clippv_*"):
                    try:
                        if p.is_file():
                            sz = p.stat().st_size
                            p.unlink(missing_ok=True)
                            temp_count += 1
                            freed_mb += sz / (1024 * 1024)
                        elif p.is_dir():
                            shutil.rmtree(p, ignore_errors=True)
                            temp_count += 1
                    except Exception:
                        pass
            details["temp_previews"] = temp_count

            print(f"[H3 Extender] 缓存已清空: removed={removed + ref2va_count + refs_count + preview_count + clips_count + temp_count}, freed={freed_mb:.1f}MB, details={details}")
            return web.json_response({
                "ok": True,
                "removed": removed + ref2va_count + refs_count + preview_count + clips_count + temp_count,
                "freed_mb": round(freed_mb, 1),
                "details": details,
                "cache_root": str(cache_root),
            })
        except Exception as exc:
            print(f"[H3 Extender] clear_chain_cache error: {exc}")
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
