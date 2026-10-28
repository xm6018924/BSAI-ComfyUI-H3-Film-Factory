"""
MiniMax H3 Motion Context - disk-backed sequential chain (v13 clean).

Two-node design:
  * MiniMax H3 Motion Context Disk Join
  * MiniMax H3 Motion Context Disk Final Decode

Goals:
  * full_batch and clip_by_clip workflows with the SAME graph
  * validated clips never require their sampler branch again
  * one .h3cache + one .json per chain, stored in this custom-node folder/cache
  * rerendering truncates/reuses the cache tail instead of creating files forever
  * cached LATENT output is memory-mapped/lazy; validated prefix does not fill RAM
  * final export decodes one seam pair at a time and streams to ffmpeg

The v10 RAM Motion Context conditioning and its validated seam corrections remain
unchanged. This module only changes persistence/execution and final streaming.
"""

import asyncio
import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import uuid

import numpy as np
import torch
import comfy.nested_tensor
import comfy.utils

try:
    from aiohttp import web
    from server import PromptServer
except Exception:  # static tests outside ComfyUI
    web = None
    PromptServer = None

try:
    import folder_paths
except Exception:  # static tests outside ComfyUI
    folder_paths = None

from .motion_context_ram import (
    FPS,
    _audio_exact_frames,
    _audio_t_for_frames,
    _auto_early_seam_shift,
    _frames_from_video_t,
    _photometric_match_segment,
    _pixel_frames,
    _steps_for_frames,
    _streams_from_latent,
)

BUILD = "motion-context-disk-v14.61-compact-prompt-bridge"
PREVIEW_AUDIO_MODE = "pcm_single_aac_gain_chain_v3_entry_ramp"
CACHE_VERSION = 12
PREVIEW_ROTATION_SLOTS = 3


def _parse_export_clips(value, total_clips):
    """Parse export_clips string into a set of 0-indexed clip indices.

    Accepts: "all", "2", "2,3", "2-5", "1,3-5"
    Returns None for "all" (meaning: export everything merged).
    Returns a set of 0-indexed ints for specific clips.
    """
    import re as _re
    raw = str(value or "all").strip().lower()
    if not raw or raw == "all":
        return None

    indices = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        m = _re.match(r"^(\d+)\s*-\s*(\d+)$", part)
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


class _FinalDecodeNativeProgress:
    """Native ComfyUI progress bound to the *currently executing* Final Decode node.

    We deliberately drive both paths used by recent ComfyUI versions:
      1. comfy.utils.ProgressBar -> normal global progress hook / legacy progress event
      2. comfy_execution.progress registry -> native per-node progress_state

    The registry path is optional so the custom node remains import-compatible with
    older ComfyUI versions.  No custom JS or websocket event is involved.
    """

    def __init__(self, unique_id, total):
        self.total = max(1, int(total))
        self.value = 0
        self.registry = None

        # The execution context is the authoritative runtime node id.  UNIQUE_ID is
        # retained as a fallback for older executors / direct tests.
        context_node_id = None
        try:
            from comfy_execution.utils import get_executing_context

            ctx = get_executing_context()
            context_node_id = getattr(ctx, "node_id", None) if ctx is not None else None
        except Exception:
            context_node_id = None

        raw_node_id = context_node_id if context_node_id is not None else unique_id
        self.node_id = None if raw_node_id is None else str(raw_node_id)

        try:
            self.pbar = comfy.utils.ProgressBar(self.total, node_id=self.node_id)
        except TypeError:
            # Compatibility with older ComfyUI ProgressBar signatures.
            self.pbar = comfy.utils.ProgressBar(self.total)

        try:
            from comfy_execution.progress import get_progress_state

            self.registry = get_progress_state()
            if self.node_id is not None:
                self.registry.start_progress(self.node_id)
        except Exception:
            self.registry = None

        # Send a non-zero first state immediately, before the first long VAE decode.
        self.update_absolute(1)

    def update_absolute(self, value):
        value = max(0, min(int(value), self.total))
        if value < self.value:
            return
        self.value = value

        # This is the exact native ProgressBar API sampler callbacks use.
        self.pbar.update_absolute(self.value, self.total)

        # On current ComfyUI, the inline node bar is sourced from progress_state.
        # Drive it explicitly as well; this is harmless if the global hook already
        # updated the same registry entry.
        if self.registry is not None and self.node_id is not None:
            try:
                self.registry.update_progress(
                    self.node_id, self.value, self.total, None
                )
            except Exception:
                pass

    def advance(self, units=1):
        self.update_absolute(self.value + max(0, int(units)))

    def finish(self):
        self.update_absolute(self.total)
        if self.registry is not None and self.node_id is not None:
            try:
                self.registry.finish_progress(self.node_id)
            except Exception:
                pass


CACHE_TYPE = "H3_MOTION_DISK_CACHE"
_LOG = logging.getLogger("minimax_h3_tail_from_latent.motion_context_disk")

_NODE_DIR = Path(__file__).resolve().parent
# v1.82 (2026-09-15 fix #12): 链缓存目录迁移到 ComfyUI 根下独立目录。
# 4090 重启后 custom_nodes\...\cache 被外部(启动脚本/Gigabyte 备份软件等)
# 整个清空重建, 443MB h3cache 链缓存丢失只能从头渲染。新目录
# bsai_h3_chain_cache 位于 ComfyUI 根下, 与 custom_nodes 和系统 Temp 隔离,
# 避开常见清空源。旧目录数据由 _ensure_cache_root() 首次使用时自动迁移。
_CACHE_ROOT = (_NODE_DIR.parents[1] / "bsai_h3_chain_cache")
_SAFE_NAME_RE = re.compile(r"[A-Za-z0-9_\-]+\.mp4")
_DATA_MAGIC = b"H3MCACHE12\x00"
_DATA_START = len(_DATA_MAGIC)

_DTYPE_MAP = {
    "float64": torch.float64,
    "float32": torch.float32,
    "float16": torch.float16,
    "bfloat16": torch.bfloat16,
    "uint8": torch.uint8,
    "int8": torch.int8,
    "int16": torch.int16,
    "int32": torch.int32,
    "int64": torch.int64,
    "bool": torch.bool,
}
# Float8 names exist only on recent torch builds.
for _name in (
    "float8_e4m3fn", "float8_e5m2", "float8_e4m3fnuz", "float8_e5m2fnuz"
):
    _dt = getattr(torch, _name, None)
    if _dt is not None:
        _DTYPE_MAP[_name] = _dt


def _safe_name(value):
    value = str(value or "").strip()
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return value or "h3_chain"


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
            return Path(_fp.get_temp_directory())
        except Exception:
            import tempfile as _tf
            return Path(_tf.gettempdir())


def _ensure_cache_root():
    _CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    # v1.82: 首次使用新目录时, 若旧 cache 目录有链缓存(h3cache/json/ref2va),
    # 自动复制迁移, 避免升级后旧链丢失。只迁移 >1KB 的持久文件, 不迁临时垃圾。
    _flag = _CACHE_ROOT / ".migrated_v182"
    if not _flag.exists():
        try:
            _legacy = _NODE_DIR / "cache"
            _has_legacy = False
            _any_fail = False
            if _legacy.exists() and _legacy != _CACHE_ROOT:
                import shutil as _sh82
                _moved = False
                for _p in _legacy.iterdir():
                    _has_legacy = True
                    try:
                        if _p.is_dir():
                            _dst = _CACHE_ROOT / _p.name
                            if not _dst.exists():
                                _sh82.copytree(_p, _dst)
                                _moved = True
                        elif _p.suffix in (".json", ".h3cache", ".bak", ".pt", ".mp4") \
                                and _p.stat().st_size > 1024:
                            _dst = _CACHE_ROOT / _p.name
                            if not _dst.exists():
                                _sh82.copy2(_p, _dst)
                                # v1.84: 复制后校验大小, 防止 772MB h3cache 静默失败丢链
                                if _dst.stat().st_size != _p.stat().st_size:
                                    raise RuntimeError("copy size mismatch")
                                _moved = True
                    except Exception as _e84:
                        _any_fail = True
                        print(f"[H3 Extender] v1.82 迁移跳过 {_p.name}: {_e84}")
                if _moved:
                    if not _any_fail:
                        _flag.touch()
                        print("[H3 Extender] v1.82 链缓存已迁移: "
                              "custom_nodes/.../cache -> ComfyUI/bsai_h3_chain_cache")
                    else:
                        # 部分失败: 不标记, 下次启动自动重试补齐
                        print("[H3 Extender] v1.82 迁移部分完成, 未标记, 下次启动重试")
            if not _has_legacy:
                _flag.touch()
        except Exception as _m82:
            print(f"[H3 Extender] v1.82 缓存迁移异常(下次重试): {_m82}")
    return _CACHE_ROOT


def _chain_paths(owner_id):
    root = _ensure_cache_root()
    stem = "chain_" + _safe_name(owner_id)
    return root / f"{stem}.h3cache", root / f"{stem}.json"


def _rooted_chain_path(stored):
    """Derive a chain file path strictly under the H3 cache root.

    The cache handle dict is untrusted input: its stored data_path /
    manifest_path values are re-derived from the cache root using only the
    file's own name. An absolute path or '..' traversal embedded in the handle
    therefore cannot read/write/delete files outside the cache directory."""
    root = _ensure_cache_root()
    name = os.path.basename(os.path.realpath(str(stored)))
    if not name or name in (".", ".."):
        raise ValueError("MiniMax H3 Disk Cache: invalid path in cache handle.")
    final = os.path.realpath(str(root / name))
    base = os.path.realpath(str(root))
    if os.path.commonpath([base, final]) != base:
        raise ValueError("MiniMax H3 Disk Cache: cache path escapes cache root.")
    return Path(final)


def _write_json_atomic(path, payload):
    """v1.79: 原子写 + .bak 双保险。manifest 丢失(0字节/损坏)会导致
    断点续跑失效(h3cache 有数据但段数只能从 json 读), 故每写一份主文件
    就同步写一份 .bak, 读取时可回退。"""
    import time
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    # Windows: Final Decode 可能正在读此文件, os.replace 会 PermissionError
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            break
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.5 * (attempt + 1))
    try:
        bak = path.with_name(path.name + ".bak")
        bak.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _dtype_name(tensor):
    return str(tensor.dtype).replace("torch.", "")


def _dtype_from_name(name):
    dt = _DTYPE_MAP.get(str(name))
    if dt is None:
        raise ValueError(f"H3 Disk Cache: unsupported tensor dtype '{name}'.")
    return dt


def _new_data_file(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # v2.62: 如果文件已存在且包含超过 magic header 字节的真实数据,
    # 不要再覆写, 否则会清掉用户恢复出来的 118MB h3cache.
    # 这是 ♻️ 恢复缓存按钮 + clip_select 单选跳过 1~14 渲染修复链的关键一环.
    if path.exists():
        try:
            cur_size = int(path.stat().st_size)
            if cur_size > len(_DATA_MAGIC):
                # 已有真实数据 (118MB 等), 保留
                return
        except Exception:
            pass
    with open(path, "wb") as f:
        f.write(_DATA_MAGIC)
        f.flush()
        os.fsync(f.fileno())


def _ensure_data_file(path):
    path = Path(path)
    if not path.exists():
        _new_data_file(path)
        return
    with open(path, "rb") as f:
        magic = f.read(_DATA_START)
    if magic != _DATA_MAGIC:
        raise ValueError(f"H3 Disk Cache: invalid cache data file: {path}")


def _geometry(video, audio):
    return {
        "video_batch": int(video.shape[0]),
        "video_channels": int(video.shape[1]),
        "video_h": int(video.shape[3]),
        "video_w": int(video.shape[4]),
        "audio_batch": int(audio.shape[0]),
        "audio_channels": int(audio.shape[1]),
        "audio_planes": int(audio.shape[2]),
    }


def _validate_batch_one(video, audio):
    if int(video.shape[0]) != 1 or int(audio.shape[0]) != 1:
        raise ValueError("MiniMax H3 Disk Join supports batch size 1 only.")


def _validate_geometry(manifest, video, audio):
    current = _geometry(video, audio)
    expected = manifest.get("geometry")
    if expected is not None and current != expected:
        raise ValueError(
            "MiniMax H3 Disk Join: latent geometry changed between clips. "
            f"Expected {expected}, got {current}."
        )


def _final_frame_count(segments):
    if not segments:
        return 0
    total = int(segments[0]["frames"])
    for desc in segments[1:]:
        total += int(desc["frames"]) - int(desc["trim_frames"])
    return int(total)


def _segment_end(desc):
    return int(desc["segment_end"])


def _segment_start(desc):
    return int(desc["video"]["offset"])


def _recover_manifest(data_path, manifest_path, manifest):
    """Recover a safe prefix after an interrupted tail rewrite.

    v2.62: 当 data_path 只有 11 字节 (即只有 magic header, 没有真实 latent)
    但 manifest 自称有 N 段时, 视为 manifest 与磁盘不一致, 返回 None 让
    上层 _manifest_for_first 走"重新建"分支. 修复 clip_select=15 但磁盘
    chain 是损坏空文件时 join() 抛 'invalid chain index 0/0' 的问题.
    """
    data_path = Path(data_path)
    manifest_path = Path(manifest_path)
    _ensure_data_file(data_path)
    size = int(data_path.stat().st_size)
    n_segments = len(manifest.get("segments", []))
    # v2.62: manifest 说有段但磁盘只有 magic header -> 不一致, 让上层重建
    if n_segments > 0 and size <= len(_DATA_MAGIC):
        _LOG.warning(
            "H3 Disk Cache: manifest claims %d segment(s) but data_path only "
            "has %d byte(s); treating chain as missing. Caller should rebuild.",
            n_segments, size,
        )
        return None
    good = []
    for desc in manifest.get("segments", []):
        try:
            start = _segment_start(desc)
            end = _segment_end(desc)
            if start < _DATA_START or end < start or end > size:
                break
            good.append(desc)
        except Exception:
            break

    if len(good) != n_segments:
        # v2.62: 全部段都坏 (good=[]) 也返回 None, 让 _manifest_for_first 重建
        if len(good) == 0 and n_segments > 0:
            _LOG.warning(
                "H3 Disk Cache: all %d segment(s) invalid in manifest; "
                "returning None to trigger rebuild.",
                n_segments,
            )
            return None
        fixed = dict(manifest)
        fixed["segments"] = [dict(x) for x in good]
        fixed["final_frame_count"] = _final_frame_count(good)
        fixed["updated_at"] = time.time()
        _write_json_atomic(manifest_path, fixed)
        manifest = fixed
        _LOG.warning(
            "H3 Disk Cache recovered %d valid clip(s) after incomplete tail write.",
            len(good),
        )
    return manifest


def _load_manifest_from_paths(data_path, manifest_path):
    data_path = Path(data_path)
    manifest_path = Path(manifest_path)
    manifest = None
    candidates = [manifest_path]
    bak = manifest_path.with_name(manifest_path.name + ".bak")
    if not manifest_path.exists() and bak.exists():
        candidates = [bak]
    elif manifest_path.exists():
        candidates = [manifest_path]
        if bak.exists():
            candidates.append(bak)
    elif not bak.exists():
        return None
    last_err = None
    for cand in candidates:
        try:
            text = cand.read_text(encoding="utf-8")
            if not text.strip():
                continue
            parsed = json.loads(text)
            if int(parsed.get("version", -1)) != CACHE_VERSION:
                continue
            manifest = parsed
            break
        except Exception as exc:
            last_err = exc
            continue
    if manifest is None:
        if last_err is not None:
            return None
        return None
    try:
        recovered = _recover_manifest(data_path, manifest_path, manifest)
        # v2.62: _recover_manifest 返回 None 表示 manifest 与磁盘不一致,
        # 清掉坏文件让 _manifest_for_first 走"重新建"分支. 否则后续 join()
        # 会因为 manifest 说有 N 段但磁盘 0 段而抛 RuntimeError.
        if recovered is None:
            try:
                if manifest_path.exists():
                    manifest_path.unlink()
                if bak.exists():
                    bak.unlink()
            except Exception:
                pass
            return None
        return recovered
    except Exception:
        return manifest


def _load_manifest(cache):
    if not isinstance(cache, dict):
        raise ValueError("MiniMax H3 Disk Cache: invalid cache handle.")
    data_path = _rooted_chain_path(cache["data_path"])
    manifest_path = _rooted_chain_path(cache["manifest_path"])
    manifest = _load_manifest_from_paths(data_path, manifest_path)
    if manifest is None:
        raise FileNotFoundError(f"H3 Disk Cache manifest not found: {manifest_path}")
    return data_path, manifest_path, manifest


def _make_handle(
    data_path, manifest_path, manifest, run_mode, stop=False, status="", next_index=None
):
    if next_index is None:
        next_index = len(manifest.get("segments", []))
    return {
        "version": CACHE_VERSION,
        "data_path": str(Path(data_path).resolve()),
        "manifest_path": str(Path(manifest_path).resolve()),
        "run_mode": str(run_mode),
        "stop": bool(stop),
        "next_index": int(next_index),
        "status": str(status),
        "run_token": float(manifest.get("updated_at", 0)),
        "exec_nonce": str(uuid.uuid4()),
    }


def _cache_size_mb(data_path, manifest_path):
    total = 0
    data_path = Path(data_path)
    preview_path = data_path.with_suffix(".preview.mp4")
    preview_video_path = data_path.with_suffix(".preview.video.mp4")
    for p in (data_path, Path(manifest_path), preview_path, preview_video_path):
        try:
            total += p.stat().st_size
        except OSError:
            pass
    return float(total / (1024.0 * 1024.0))


def _write_tensor_raw(file_obj, tensor):
    """Write one contiguous tensor without a giant serialization bytes object."""
    x = tensor.detach()
    if x.device.type != "cpu":
        x = x.to(device="cpu")
    if not x.is_contiguous():
        x = x.contiguous()

    offset = int(file_obj.tell())
    shape = [int(v) for v in x.shape]
    dtype_name = _dtype_name(x)
    nbytes = int(x.numel() * x.element_size())

    # Viewing as uint8 makes numpy() work for BF16/FP8 too; memoryview avoids
    # another full-size bytes copy in Python.
    raw = x.view(torch.uint8).numpy()
    written = int(file_obj.write(memoryview(raw)))
    if written != nbytes:
        raise IOError(f"H3 Disk Cache short write: {written}/{nbytes} bytes.")

    return {
        "offset": offset,
        "nbytes": nbytes,
        "shape": shape,
        "dtype": dtype_name,
    }


def _map_tensor(data_path, spec):
    """Memory-map one tensor. Pages are faulted in only when actually touched."""
    data_path = Path(data_path)
    offset = int(spec["offset"])
    nbytes = int(spec["nbytes"])
    shape = tuple(int(v) for v in spec["shape"])
    dtype = _dtype_from_name(spec["dtype"])

    if nbytes <= 0:
        raise ValueError("H3 Disk Cache: invalid zero-sized tensor.")
    mm = np.memmap(
        str(data_path), mode="c", dtype=np.uint8, offset=offset, shape=(nbytes,)
    )
    raw = torch.from_numpy(mm)
    tensor = raw.view(dtype).reshape(shape)
    return tensor


def _load_segment_video(data_path, desc):
    video = _map_tensor(data_path, desc["video"])
    if video.ndim == 4:
        video = video.unsqueeze(0)
    if video.ndim != 5 or int(video.shape[0]) != 1:
        raise ValueError(f"Invalid cached H3 video shape: {tuple(video.shape)}")
    return video


def _load_segment_audio(data_path, desc):
    audio = _map_tensor(data_path, desc["audio"])
    if audio.ndim == 3:
        audio = audio.unsqueeze(0)
    if audio.ndim != 4 or int(audio.shape[0]) != 1:
        raise ValueError(f"Invalid cached H3 audio shape: {tuple(audio.shape)}")
    return audio


def _append_segment(data_path, latent, index, trim_frames, validated, manifest):
    video, audio = _streams_from_latent(latent, "samples")
    _validate_batch_one(video, audio)
    if manifest.get("geometry") is not None:
        _validate_geometry(manifest, video, audio)

    trim = int(trim_frames)
    frames = _frames_from_video_t(int(video.shape[2]))
    if index == 0:
        trim = 0
    else:
        if trim < 0:
            raise ValueError("MiniMax H3 Disk Join: trim_frames cannot be negative.")
        if trim > 0 and _steps_for_frames(trim) is None:
            raise ValueError(
                f"MiniMax H3 Disk Join: trim_frames={trim} is not on H3 grid."
            )
        if trim >= frames:
            raise ValueError("MiniMax H3 Disk Join: trim removes the entire clip.")

    _ensure_data_file(data_path)
    with open(data_path, "ab", buffering=0) as f:
        video_spec = _write_tensor_raw(f, video)
        audio_spec = _write_tensor_raw(f, audio)
        segment_end = int(f.tell())
        f.flush()
        os.fsync(f.fileno())

    return {
        "index": int(index),
        "validated": bool(validated),
        "frames": int(frames),
        "trim_frames": int(trim),
        "video": video_spec,
        "audio": audio_spec,
        "segment_end": segment_end,
    }, _geometry(video, audio)


def _backup_chain_before_truncate(data_path, manifest_path, reason):
    """v1.97: truncate 前自动备份链(数据+manifest), 误清可恢复。
    备份到同目录 chain_<name>.<ts>.preclear.h3cache/.json, 保留最近 3 份。"""
    try:
        import time as _t, shutil as _sh
        stem = Path(manifest_path).name
        name = stem[:-5] if stem.endswith(".json") else stem
        ts = _t.strftime("%Y%m%d_%H%M%S")
        if Path(data_path).exists() and Path(data_path).stat().st_size > 0:
            _sh.copy2(data_path, Path(data_path).with_name(f"{name}.{ts}.preclear.h3cache"))
        if Path(manifest_path).exists():
            _sh.copy2(manifest_path, Path(manifest_path).with_name(f"{name}.{ts}.preclear.json"))
        print(f"[H3 Extender] v1.97 清链前备份: {name}.{ts}.preclear.* (reason={reason})")
        # 只保留最近 3 份备份
        try:
            backups = sorted(Path(manifest_path).parent.glob(f"{name}.*.preclear.json"))
            for old in backups[:-3]:
                old.unlink(missing_ok=True)
                Path(str(old).replace(".preclear.json", ".preclear.h3cache")).unlink(missing_ok=True)
        except Exception:
            pass
    except Exception as _bk:
        print(f"[H3 Extender] v1.97 备份失败: {_bk}")


def _snapshot_chain(data_path, manifest_path, reason):
    """v1.98: 渲染完成后自动快照整条链（data+manifest）。
    命名 chain_<name>.<ts>.snapshot.h3cache/.json，保留最近 5 份。
    与 preclear（截断前）备份互补：snapshot 是「渲染成果」的最新状态。"""
    try:
        import time as _t, shutil as _sh
        stem = Path(manifest_path).name
        name = stem[:-5] if stem.endswith(".json") else stem
        ts = _t.strftime("%Y%m%d_%H%M%S")
        if Path(data_path).exists() and Path(data_path).stat().st_size > 0:
            _sh.copy2(data_path, Path(data_path).with_name(f"{name}.{ts}.snapshot.h3cache"))
        if Path(manifest_path).exists():
            _sh.copy2(manifest_path, Path(manifest_path).with_name(f"{name}.{ts}.snapshot.json"))
        print(f"[H3 Disk Cache] 渲染完成自动快照: {name}.{ts}.snapshot.* (reason={reason})")
        _prune_snapshots(Path(manifest_path).parent, name, keep=5)
        return True
    except Exception as _e:
        print(f"[H3 Disk Cache] 快照失败: {_e}")
        return False


def _prune_snapshots(directory, name, keep=5):
    try:
        snaps = sorted(directory.glob(f"{name}.*.snapshot.json"))
        for old in snaps[:-keep]:
            old.unlink(missing_ok=True)
            Path(str(old).replace(".snapshot.json", ".snapshot.h3cache")).unlink(missing_ok=True)
    except Exception:
        pass


# v2.66: per-clip 滚动快照——每段提交后覆盖同一份 latest.snapshot。
# 与 _snapshot_chain（时间戳命名、保留 5 份、仅在 merge/render-complete 触发）互补：
# latest.snapshot 永远是「上一段成功提交后」的完好链状态，崩溃/误删后最多丢最后一段。
def _snapshot_latest(data_path, manifest_path, reason=""):
    """每段 commit 后滚动快照，固定命名 latest.snapshot.*，每次覆盖。
    只备份非空链（数据>1MB），空链不覆盖已有有效快照。"""
    try:
        import shutil as _sh
        dp = Path(data_path)
        mp = Path(manifest_path)
        if not dp.exists() or dp.stat().st_size < (1024 * 1024):
            return False
        stem = mp.name
        name = stem[:-5] if stem.endswith(".json") else stem
        snap_data = dp.with_name(f"{name}.latest.snapshot.h3cache")
        snap_man = mp.with_name(f"{name}.latest.snapshot.json")
        _sh.copy2(dp, snap_data)
        _sh.copy2(mp, snap_man)
        print(f"[H3 Disk Cache] per-clip 快照: {snap_data.name} ({dp.stat().st_size // (1024*1024)} MB) reason={reason}")
        return True
    except Exception as _e:
        print(f"[H3 Disk Cache] per-clip 快照失败(可忽略): {_e}")
        return False


def _backup_segment_count(manifest_path):
    """读一个备份 manifest 的段数（容错，读不到返回 -1）。"""
    try:
        import json as _json
        with open(manifest_path, encoding="utf-8") as _f:
            return len(_json.load(_f).get("segments", []))
    except Exception:
        return -1


def _list_snapshot_backups(data_path, manifest_path):
    """列出可用的 snapshot 备份（最新在前），供恢复入口使用。"""
    try:
        stem = Path(manifest_path).name
        name = stem[:-5] if stem.endswith(".json") else stem
        snaps = sorted(Path(manifest_path).parent.glob(f"{name}.*.snapshot.json"))
        out = []
        for s in snaps:
            h3 = Path(str(s).replace(".snapshot.json", ".snapshot.h3cache"))
            if h3.exists():
                _parts = Path(s).stem.split(".")
                _ts = _parts[-2] if len(_parts) >= 2 else ""
                out.append({"manifest": str(s), "data": str(h3), "ts": _ts})
        return list(reversed(out))
    except Exception:
        return []


def _restore_latest_backup(data_path, manifest_path, source="auto"):
    """v2.66: 从最近一次有效备份恢复主链。
    优先级: latest.snapshot(每段提交滚动快照) > 时间戳 snapshot > preclear。
    安全网:
      1) 跳过空壳备份(段数=0 或 h3cache<1MB)——防空壳覆盖非空主链;
      2) 当前主链非空(段数>0)且备份段数更少时拒绝覆盖——保护已渲染成果;
      3) 恢复前仍把当前主链备份为 preclear 可回滚。
    返回 (ok, segments_count, kind, ts)。"""
    try:
        import shutil as _sh
        stem = Path(manifest_path).name
        name = stem[:-5] if stem.endswith(".json") else stem
        parent = Path(manifest_path).parent

        # 收集候选备份，按优先级排序: latest.snapshot > 历史 snapshot > preclear
        candidates = []  # (priority, manifest_path_str, kind)
        latest_man = parent / f"{name}.latest.snapshot.json"
        if latest_man.exists():
            candidates.append((0, str(latest_man), "latest"))
        if source == "auto":
            for s in _list_snapshot_backups(data_path, manifest_path):
                candidates.append((1, s["manifest"], "snapshot"))
        for p in sorted(parent.glob(f"{name}.*.preclear.json")):
            candidates.append((2, str(p), "preclear"))

        # 当前主链段数(用于保护非空主链)
        try:
            cur_m = _load_manifest_from_paths(data_path, manifest_path) or {}
            cur_n = len(cur_m.get("segments", []))
        except Exception:
            cur_n = 0

        src_manifest = None
        src_kind = ""
        skipped_empty = []
        for prio, mp, kind in sorted(candidates, key=lambda x: x[0]):
            dp = mp.replace(".snapshot.json", ".snapshot.h3cache").replace(".preclear.json", ".preclear.h3cache")
            dp = dp.replace(".latest.", ".latest.")
            if not Path(dp).exists():
                continue
            seg_n = _backup_segment_count(mp)
            # 防空壳: 段数必须>0 且数据文件>1MB
            if seg_n <= 0 or Path(dp).stat().st_size < (1024 * 1024):
                skipped_empty.append((Path(mp).name, seg_n, Path(dp).stat().st_size))
                continue
            # 保护非空主链: 备份段数 < 当前主链段数 -> 不覆盖(避免用旧备份回退)
            if cur_n > 0 and seg_n < cur_n:
                print(f"[H3 Disk Cache] 恢复缓存跳过 {Path(mp).name}: 备份仅 {seg_n} 段 < 当前主链 {cur_n} 段，不回退")
                continue
            src_manifest = mp
            src_kind = kind
            break

        if skipped_empty:
            print(f"[H3 Disk Cache] 恢复缓存: 已跳过 {len(skipped_empty)} 个空壳备份(段数=0或数据<1MB): "
                  f"{', '.join(n for n,_,_ in skipped_empty)}")
        if not src_manifest:
            print("[H3 Disk Cache] 恢复缓存: 未找到任何有效(非空)快照/备份，无法恢复。"
                  "若主链确已丢失，请确认是否有 latest.snapshot 或 .snapshot.* 文件")
            return (False, 0, "none", "")

        src_data = src_manifest.replace(".snapshot.json", ".snapshot.h3cache").replace(".preclear.json", ".preclear.h3cache")
        # 当前主链先备份(可回滚)
        _backup_chain_before_truncate(data_path, manifest_path, reason="before-restore")
        # 复制回主路径
        _sh.copy2(src_data, data_path)
        _sh.copy2(src_manifest, manifest_path)
        try:
            _m = _load_manifest_from_paths(data_path, manifest_path) or {}
            seg_count = len(_m.get("segments", []))
        except Exception:
            seg_count = 0
        _parts = Path(src_manifest).stem.split(".")
        _ts = _parts[-2] if len(_parts) >= 2 else ""
        print(f"[H3 Disk Cache] 恢复缓存成功: 从 {Path(src_manifest).name} 恢复 {seg_count} 段"
              f" ({src_kind} {_ts})，主链已回滚，仅需渲染新增 CLIP")
        return (True, seg_count, src_kind, _ts)
    except Exception as _e:
        print(f"[H3 Disk Cache] 恢复缓存失败: {_e}")
        return (False, 0, "none", "")


def _truncate_chain(data_path, manifest_path, manifest, index, reason=""):
    """
    Keep clips [0:index), discard index and everything after it.
    Manifest prefix is committed first, so an interruption can only roll back.
    """
    index = max(0, int(index))
    old = [dict(x) for x in manifest.get("segments", [])]
    if old:
        # v1.98: 任何截断（含部分截断）前都无条件自动备份，保护已渲染缓存；
        # 恢复入口可一键回滚，避免从 clip1 重新渲染补链。
        _backup_chain_before_truncate(data_path, manifest_path, reason or f"truncate{index}")
    prefix = old[:index]
    truncate_at = _DATA_START if not prefix else _segment_end(prefix[-1])

    reduced = dict(manifest)
    reduced["segments"] = prefix
    if index == 0:
        reduced["geometry"] = None
    reduced["final_frame_count"] = _final_frame_count(prefix)
    # Clamp preview_committed_count to the new chain length: any committed
    # preview content beyond the truncation point is no longer valid.
    # Also delete the committed preview files so that _sync_committed_preview
    # rebuilds from scratch instead of using a stale prefix that contains
    # more clips than the truncated chain.
    old_commit = int(reduced.get("preview_committed_count", 0))
    if old_commit > index:
        reduced["preview_committed_count"] = int(index)
        # Delete committed preview files to force full rebuild
        for p in (_decoded_preview_cache_path(data_path),
                  _decoded_preview_video_cache_path(data_path)):
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass
    reduced["updated_at"] = time.time()
    _write_json_atomic(manifest_path, reduced)

    _ensure_data_file(data_path)
    with open(data_path, "r+b") as f:
        f.truncate(truncate_at)
        f.flush()
        os.fsync(f.fileno())
    return reduced


def _save_tail_latents(data_path, manifest, from_index):
    """Clone video and audio latents from from_index onwards for later re-append."""
    segments = manifest.get("segments", [])
    saved = []
    for i in range(int(from_index), len(segments)):
        seg = segments[i]
        video = _load_segment_video(data_path, seg).clone()
        audio = _load_segment_audio(data_path, seg).clone()
        saved.append({
            "video": video,
            "audio": audio,
            "frames": int(seg["frames"]),
            "trim_frames": int(seg.get("trim_frames", 0)),
            "color_adjustment": seg.get("color_adjustment"),
        })
    return saved


def _restore_tail_latents(data_path, manifest_path, saved_latents):
    """Re-append saved latent tensors after a selective re-render.

    Each saved item is written as a new validated segment so the chain
    regains its original length.  The decoded_mp4_blob / decoded_audio
    caches are NOT copied: they will be regenerated by Final Decode.
    """
    for item in saved_latents:
        manifest = _load_manifest_from_paths(data_path, manifest_path)
        if manifest is None:
            raise RuntimeError("H3 Disk Cache: manifest disappeared during tail restore.")
        segments = manifest.get("segments", [])
        index = len(segments)
        latent = {"samples": (item["video"], item["audio"])}
        desc, geom = _append_segment(
            data_path,
            latent,
            index=index,
            trim_frames=int(item["trim_frames"]),
            validated=True,
            manifest=manifest,
        )
        if item.get("color_adjustment") is not None:
            desc["color_adjustment"] = item["color_adjustment"]
        segments.append(desc)
        manifest = dict(manifest)
        manifest["segments"] = segments
        manifest["final_frame_count"] = _final_frame_count(segments)
        manifest["build"] = BUILD
        manifest["updated_at"] = time.time()
        _write_json_atomic(manifest_path, manifest)
    return _load_manifest_from_paths(data_path, manifest_path)


def _save_tail_latents_to_disk(data_path, manifest, from_index, owner_id):
    """Save tail latents to a .pt file on disk for cross-execution persistence.

    This is used by the single-clip regenerate flow: when the user clicks ↻
    on one clip, tail latents are saved to disk before truncation, and restored
    later when the user clicks '合并输出' (Merge Output).
    """
    import torch
    root = _ensure_cache_root()
    tail_file = root / f"tail_{_safe_name(owner_id)}.pt"

    segments = manifest.get("segments", [])
    saved = []
    for i in range(int(from_index), len(segments)):
        seg = segments[i]
        video = _load_segment_video(data_path, seg).clone()
        audio = _load_segment_audio(data_path, seg).clone()
        saved.append({
            "video": video,
            "audio": audio,
            "frames": int(seg["frames"]),
            "trim_frames": int(seg.get("trim_frames", 0)),
            "color_adjustment": seg.get("color_adjustment"),
        })

    torch.save(saved, str(tail_file))
    print(f"[H3 Disk Cache] Saved {len(saved)} tail clip(s) to disk: {tail_file}")
    return saved


def _load_tail_latents_from_disk(owner_id):
    """Load previously saved tail latents from disk.

    Returns the saved list or None if no file exists.
    """
    import torch
    root = _ensure_cache_root()
    tail_file = root / f"tail_{_safe_name(owner_id)}.pt"
    if not tail_file.exists():
        return None
    try:
        saved = torch.load(str(tail_file), weights_only=False)
        print(f"[H3 Disk Cache] Loaded {len(saved)} tail clip(s) from disk: {tail_file}")
        return saved
    except Exception as e:
        print(f"[H3 Disk Cache] Failed to load tail latents: {e}")
        return None


def _delete_tail_latents_from_disk(owner_id):
    """Delete the saved tail latents file after successful merge."""
    root = _ensure_cache_root()
    tail_file = root / f"tail_{_safe_name(owner_id)}.pt"
    if tail_file.exists():
        try:
            tail_file.unlink()
            print(f"[H3 Disk Cache] Deleted tail latents file: {tail_file}")
        except Exception as e:
            print(f"[H3 Disk Cache] Failed to delete tail latents: {e}")


def _has_tail_latents_on_disk(owner_id):
    """Check if saved tail latents exist on disk."""
    root = _ensure_cache_root()
    tail_file = root / f"tail_{_safe_name(owner_id)}.pt"
    return tail_file.exists()


class _LazyDiskLatent(dict):
    """Small LATENT-compatible proxy; tensors stay mmap-backed until consumed."""

    def __init__(self, data_path, desc):
        super().__init__()
        self.data_path = str(data_path)
        self.desc = dict(desc)

    def _samples(self):
        video = _load_segment_video(self.data_path, self.desc)
        audio = _load_segment_audio(self.data_path, self.desc)
        return comfy.nested_tensor.NestedTensor((video, audio))

    def get(self, key, default=None):
        if key == "samples":
            return self._samples()
        if key in ("noise_mask", "batch_index"):
            return default
        return default

    def __getitem__(self, key):
        if key == "samples":
            return self._samples()
        raise KeyError(key)

    def __contains__(self, key):
        return key == "samples"

    def keys(self):
        return ("samples",)

    def copy(self):
        # Compatibility with nodes that copy LATENT dictionaries.
        return {"samples": self._samples()}


def _proxy_at(data_path, manifest, index):
    segments = manifest.get("segments", [])
    index = int(index)
    if index < 0 or index >= len(segments):
        raise ValueError(
            f"MiniMax H3 Disk Join: cached clip {index + 1} is unavailable."
        )
    return _LazyDiskLatent(data_path, segments[index])


def _last_proxy(data_path, manifest):
    segments = manifest.get("segments", [])
    if not segments:
        raise ValueError("MiniMax H3 Disk Join: cache contains no clip.")
    return _proxy_at(data_path, manifest, len(segments) - 1)


def _manifest_for_first(owner_id, fps):
    data_path, manifest_path = _chain_paths(owner_id)
    manifest = _load_manifest_from_paths(data_path, manifest_path)
    if manifest is None:
        _new_data_file(data_path)
        manifest = {
            "version": CACHE_VERSION,
            "build": BUILD,
            "owner_id": str(owner_id),
            "fps": float(fps),
            "geometry": None,
            "segments": [],
            "final_frame_count": 0,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        _write_json_atomic(manifest_path, manifest)
    return data_path, manifest_path, manifest


def _effective_state(previous_cache, run_mode, fps, unique_id):
    if previous_cache is not None:
        data_path, manifest_path, manifest = _load_manifest(previous_cache)
        mode = str(previous_cache.get("run_mode", run_mode))
        stop = bool(previous_cache.get("stop", False))
        index = int(previous_cache.get("next_index", len(manifest.get("segments", []))))
    else:
        owner = unique_id if unique_id is not None else "first_join"
        data_path, manifest_path, manifest = _manifest_for_first(owner, fps)
        mode = str(run_mode)
        stop = False
        index = 0

    if mode not in ("full_batch", "clip_by_clip"):
        mode = "full_batch"
    if abs(float(manifest.get("fps", fps)) - float(fps)) > 1e-6:
        raise ValueError(
            f"MiniMax H3 Disk Join: chain fps={manifest.get('fps')} but node fps={fps}."
        )
    return data_path, manifest_path, manifest, mode, stop, index


class MiniMaxH3MotionContextDiskJoin:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "samples": ("LATENT", {"lazy": True}),
                "validated": ("BOOLEAN", {"default": False}),
                "run_mode": (
                    ["full_batch", "clip_by_clip"],
                    {"default": "full_batch"},
                ),
                "fps": (
                    "FLOAT",
                    {"default": 24.0, "min": 1.0, "max": 240.0, "step": 0.001},
                ),
            },
            "optional": {
                "previous_cache": (CACHE_TYPE,),
                "trim_frames": ("INT", {"forceInput": True, "lazy": True}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = (CACHE_TYPE, "LATENT", "INT", "INT", "STRING", "FLOAT", "STRING", "STRING")
    RETURN_NAMES = (
        "cache",
        "cached_samples",
        "clip_count",
        "frame_count",
        "status",
        "cache_size_mb",
        "cache_path",
        "build",
    )
    FUNCTION = "join"
    CATEGORY = "BSAI/H3 Film Factory"

    def check_lazy_status(
        self,
        samples=None,
        trim_frames=None,
        validated=False,
        run_mode="full_batch",
        fps=24.0,
        previous_cache=None,
        unique_id=None,
    ):
        try:
            data_path, manifest_path, manifest, mode, stop, index = _effective_state(
                previous_cache, run_mode, fps, unique_id
            )
        except Exception:
            # Let execute surface the real error; request the minimum normal path.
            needed = []
            if samples is None:
                needed.append("samples")
            if previous_cache is not None and trim_frames is None:
                needed.append("trim_frames")
            return needed

        # In clip-by-clip mode, once the first candidate has been generated,
        # every later Disk Join becomes a metadata-only pass-through. Its
        # sampler/RAM branch is therefore never requested in this execution.
        if mode == "clip_by_clip" and stop:
            return []

        segments = manifest.get("segments", [])
        existing = index < len(segments)

        # A validated cached clip is immutable and needs no sampler branch.
        if bool(validated) and existing:
            return []

        needed = []
        if samples is None:
            needed.append("samples")
        if index > 0 and trim_frames is None:
            needed.append("trim_frames")
        return needed

    def join(
        self,
        samples=None,
        trim_frames=None,
        validated=False,
        run_mode="full_batch",
        fps=24.0,
        previous_cache=None,
        unique_id=None,
    ):
        data_path, manifest_path, manifest, mode, stop, index = _effective_state(
            previous_cache, run_mode, fps, unique_id
        )
        segments = [dict(x) for x in manifest.get("segments", [])]

        # Downstream of the first unvalidated clip in incremental mode:
        # preserve the same cache handle and do not touch any sampler input.
        if mode == "clip_by_clip" and stop:
            status = f"skipped after clip {len(segments)} (clip_by_clip)"
            handle = _make_handle(
                data_path, manifest_path, manifest, mode, stop=True, status=status
            )
            size = _cache_size_mb(data_path, manifest_path)
            return (
                handle,
                _last_proxy(data_path, manifest),
                len(segments),
                int(manifest.get("final_frame_count", 0)),
                status,
                size,
                str(data_path.parent),
                BUILD,
            )

        if index < 0 or index > len(segments):
            raise RuntimeError(
                f"MiniMax H3 Disk Join: invalid chain index {index}/{len(segments)}."
            )

        existing = index < len(segments)

        if bool(validated) and index > 0:
            if not all(bool(x.get("validated", False)) for x in segments[:index]):
                raise ValueError(
                    f"MiniMax H3 Disk Join: clip {index + 1} cannot be validated "
                    "before every previous clip is validated."
                )

        if bool(validated) and existing:
            # Commit/freeze the existing candidate without evaluating samples.
            if not bool(segments[index].get("validated", False)):
                segments[index]["validated"] = True
                manifest = dict(manifest)
                manifest["segments"] = segments
                manifest["build"] = BUILD
                manifest["updated_at"] = time.time()
                _write_json_atomic(manifest_path, manifest)
                status = f"clip {index + 1} validated from disk"
            else:
                status = f"clip {index + 1} validated (disk)"

        else:
            # OFF means candidate: every active execution rewrites this clip and
            # invalidates/truncates the entire downstream tail in one operation.
            if samples is None:
                raise RuntimeError("MiniMax H3 Disk Join: active clip needs samples.")
            trim = 0 if index == 0 else int(trim_frames if trim_frames is not None else 22)

            if existing or len(segments) > index:
                manifest = _truncate_chain(data_path, manifest_path, manifest, index)
                segments = [dict(x) for x in manifest.get("segments", [])]

            desc, geom = _append_segment(
                data_path,
                samples,
                index=index,
                trim_frames=trim,
                validated=bool(validated),
                manifest=manifest,
            )
            segments = [dict(x) for x in manifest.get("segments", [])] + [desc]
            manifest = dict(manifest)
            manifest["geometry"] = geom if manifest.get("geometry") is None else manifest["geometry"]
            manifest["segments"] = segments
            manifest["final_frame_count"] = _final_frame_count(segments)
            manifest["build"] = BUILD
            manifest["updated_at"] = time.time()
            _write_json_atomic(manifest_path, manifest)
            status = (
                f"clip {index + 1} validated + cached"
                if bool(validated)
                else f"clip {index + 1} candidate cached"
            )

        # Always continue to the next clip; the extender loop handles sequencing.
        stop_out = False
        handle = _make_handle(
            data_path, manifest_path, manifest, mode, stop=stop_out, status=status,
            next_index=index + 1,
        )
        size = _cache_size_mb(data_path, manifest_path)

        _LOG.info(
            "H3 Disk Join: mode=%s clip=%d validated=%s stop=%s clips=%d frames=%d cache=%.1f MB",
            mode,
            index + 1,
            bool(validated),
            stop_out,
            len(manifest.get("segments", [])),
            int(manifest.get("final_frame_count", 0)),
            size,
        )

        return (
            handle,
            _proxy_at(data_path, manifest, index),
            len(manifest.get("segments", [])),
            int(manifest.get("final_frame_count", 0)),
            status,
            size,
            str(data_path.parent),
            BUILD,
        )


# -----------------------------------------------------------------------------
# Final streaming decode - minimum RAM path: one seam pair at a time.
# -----------------------------------------------------------------------------


def _build_pair_video(data_path, prev_desc, curr_desc):
    prev_v = _load_segment_video(data_path, prev_desc)
    next_v = _load_segment_video(data_path, curr_desc)

    if tuple(prev_v.shape[:2]) != tuple(next_v.shape[:2]) or tuple(prev_v.shape[3:]) != tuple(next_v.shape[3:]):
        raise ValueError("Disk Final Decode: video latent geometry mismatch.")

    previous_frames = _frames_from_video_t(int(prev_v.shape[2]))
    next_frames = _frames_from_video_t(int(next_v.shape[2]))
    trim = int(curr_desc["trim_frames"])
    video_trim_t = 0 if trim == 0 else _steps_for_frames(trim)
    if trim > 0 and video_trim_t is None:
        raise ValueError(f"Disk Final Decode: trim_frames={trim} is not on H3 grid.")
    if int(video_trim_t) >= int(next_v.shape[2]):
        raise ValueError("Disk Final Decode: trim removes entire continuation.")

    warmup_video_t = 5 if int(video_trim_t) >= 7 else 0
    decode_start_t = int(video_trim_t) - int(warmup_video_t)
    warmup_start_frames = _pixel_frames(decode_start_t) if decode_start_t > 0 else 0
    warmup_frames = trim - warmup_start_frames
    if warmup_frames < 0:
        raise RuntimeError("Disk Final Decode: negative VAE warm-up.")

    if (int(prev_v.shape[2]) - decode_start_t) % 5 != 0:
        raise RuntimeError("Disk Final Decode: H3 temporal phase mismatch.")

    chain = torch.cat((prev_v, next_v[:, :, decode_start_t:, :, :]), dim=2)
    decode_frames = _frames_from_video_t(int(chain.shape[2]))
    expected = previous_frames + next_frames - warmup_start_frames
    if decode_frames != expected:
        raise RuntimeError(
            f"Disk Final Decode: pair decode frames {decode_frames} != {expected}."
        )

    meta = {
        "previous_frames": int(previous_frames),
        "next_frames": int(next_frames),
        "trim_frames": int(trim),
        "warmup_frames": int(warmup_frames),
        "continued_frames": int(next_frames - trim),
        "decode_frames": int(decode_frames),
    }
    return chain, meta


def _decode_pair_video(vae, chain, meta):
    decoded = vae.decode(chain)
    if decoded.ndim == 5:
        decoded = decoded.reshape(
            -1, decoded.shape[-3], decoded.shape[-2], decoded.shape[-1]
        )
    if int(decoded.shape[0]) != int(meta["decode_frames"]):
        raise RuntimeError(
            f"Disk Final Decode: VAE returned {decoded.shape[0]}, "
            f"expected {meta['decode_frames']}."
        )

    prev_frames = int(meta["previous_frames"])
    warmup = int(meta["warmup_frames"])
    shift = _auto_early_seam_shift(
        decoded,
        previous_frames=prev_frames,
        warmup_frames=warmup,
        max_early=2,
    )
    start = prev_frames + warmup + int(shift)
    end = start + int(meta["continued_frames"])
    if start < 0 or end > int(decoded.shape[0]):
        raise RuntimeError("Disk Final Decode: seam crop lies outside decoded pair.")

    previous_raw = decoded[:prev_frames]
    current_raw = decoded[start:end]
    return decoded, previous_raw, current_raw, int(shift)


def _oneshoot_dissolve_current_head(previous_raw, current_raw, frames=4):
    # v14.178 一镜到底全球方案落地 P0-4: 接缝像素域硬切 → 三角窗溶解(Diff-VF WWS)。
    # 旧: current_raw 原样硬切接在上一段尾帧后(诊断: 接缝 PSNR 仅 18.95dB, 直方图
    # 相关 0.977, "再生成漂移"型跳变)。现: 本段头部 W=4 帧与上段尾部 W 帧线性混合 ——
    # 距接缝(段头起点)越近越偏上段外观, 越远越偏本段。4 帧 ≈ 0.17s(24fps):
    # 消除硬切跳变, 又不造成可感时间冻结(22 帧长窗需真时间重叠帧, 本管线无重复
    # 时间区, 会拖出 0.92s 冻结感 —— 故取实测 4 帧值)。帧总数守恒(就地替换)。
    # v14.179 OOM 修复: 旧实现 out=current_raw.clone()(整段 2.35GB) 且 linspace
    # dtype=uint8 权重 0.33/0.66 被截断成 0 → 溶解退化为"复制上段尾帧"(断帧/冻结感
    # 来源)。现改 float32 域混合 + 就地写回头部 W 帧, 按输入 dtype 自适应归一化。
    frames = int(frames)
    if frames <= 0:
        return current_raw
    if previous_raw.shape[0] < frames or current_raw.shape[0] < frames:
        return current_raw
    w = torch.linspace(0.0, 1.0, frames, device=current_raw.device, dtype=torch.float32)
    w = w.view(frames, *([1] * (current_raw.ndim - 1)))
    prev_t = previous_raw[-frames:].to(torch.float32)
    cur_t = current_raw[:frames].to(torch.float32)
    mix = prev_t * (1.0 - w) + cur_t * w
    if current_raw.is_floating_point():
        mix = mix.clamp(0.0, 1.0)
    else:
        mix = mix.clamp(0.0, 255.0).round()
    current_raw[:frames] = mix.to(current_raw.dtype)
    return current_raw


def _correct_current_segment(previous_raw, current_raw):
    tail_n = min(4, int(previous_raw.shape[0]))
    if tail_n < 1:
        return current_raw
    # v14.179 OOM 修复: 光度匹配只对"接缝窗口"(上段尾 4 帧 + 本段头 ≤64 帧)就地
    # 校正, 不再 cat+clone 整段全分辨率像素(1920×1088×374帧 float32 ≈9.4GB CPU
    # 分配, 实测崩于 alloc_cpu.cpp:117)。接缝平滑只依赖 seam 附近, 窗口外帧
    # 无需重写; 校正语义(全局 gamma/gain/contrast + 首帧局部稳定)保持不变。
    win = min(64, int(current_raw.shape[0]))
    pair = torch.cat((previous_raw[-tail_n:], current_raw[:win]), dim=0)
    pair = _photometric_match_segment(
        pair,
        seam_frame=tail_n,
        detect_window=4,
        end_frame=int(pair.shape[0]),
    )
    current_raw[:win] = pair[tail_n:]
    # v14.178 P0-4: 亮度匹配后再做 4 帧三角窗溶解, 接缝平滑。
    return _oneshoot_dissolve_current_head(previous_raw, current_raw)


def _find_ffmpeg():
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).exists():
            return str(exe)
    except Exception:
        pass
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    raise RuntimeError("MiniMax H3 Disk Final Decode: ffmpeg executable not found.")


def _next_output_path(output_dir, prefix, extension):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = _safe_name(prefix)
    first = output_dir / f"{stem}.{extension}"
    if not first.exists():
        return first
    for i in range(1, 1000000):
        p = output_dir / f"{stem}_{i:05d}.{extension}"
        if not p.exists():
            return p
    raise RuntimeError("Disk Final Decode: could not allocate output filename.")


def _replace_output_from_preview(
    preview_path, output_dir, filename_prefix, ffmpeg=None, color_timeline=None
):
    """Atomically update the clip-by-clip autosave from the current full preview.

    The rolling browser preview stays neutral/non-destructive. User color
    adjustments are baked only into the persistent autosave copy.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{_safe_name(filename_prefix)}.mp4"
    tmp = output_dir / f".{destination.stem}.{uuid.uuid4().hex[:10]}.tmp.mp4"
    try:
        if not Path(preview_path).exists():
            print(f"[H3 Final Decode] preview file not found, skipping autosave: {preview_path}")
            return None
        if ffmpeg is not None and _timeline_has_color(color_timeline):
            _apply_color_timeline_to_file(
                ffmpeg, preview_path, tmp, color_timeline,
                codec="H.264", crf=17, preset="fast",
            )
        else:
            shutil.copy2(Path(preview_path), tmp)
        os.replace(tmp, destination)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
    return destination


_NVENC_PRESET = {"ultrafast": "p1", "superfast": "p1", "veryfast": "p2", "faster": "p3",
                 "fast": "p4", "medium": "p5", "slow": "p6", "slower": "p7"}


def _nvenc_available(ffmpeg, codec="h264"):
    """v1.66: 检测 ffmpeg 是否支持 NVENC 硬编(结果缓存). RTX 5090 硬编比
    libx264/libx265 软编快 5-10 倍, 用于 preview blob / final export.
    v2.118: 强制启用 NVENC — 用户 RTX 5090 已确认 h264_nvenc/hevc_nvenc 可用,
    运行时检测因 GPU 高负载超时导致回退 libx264(每个 clip 多花 300 秒)."""
    import subprocess as _sp
    import tempfile
    key = (str(ffmpeg), codec)
    _cache = getattr(_nvenc_available, "_cache", {})
    if key in _cache:
        return _cache[key]
    # v2.118: 直接返回 True (RTX 5090 + imageio-ffmpeg v7.1 已确认支持 NVENC)
    ok = True
    _cache[key] = ok
    _nvenc_available._cache = _cache
    return ok


def _h264_enc_args(ffmpeg, preset="fast", crf=17):
    # v14.140: 显式 GOP=48 帧(2s@24fps)。旧默认 GOP=250(10.4s)导致 15s 预览
    # 尾部 4.6s 无 IDR(P帧链)，播放器 seek/播放尾部花屏雪花；2s IDR 间隔后
    # 任意位置解码/拖拽均正常。编码效率损失 <2%，可忽略。
    if _nvenc_available(ffmpeg, "h264"):
        p = _NVENC_PRESET.get(str(preset), "p4")
        return ["-c:v", "h264_nvenc", "-preset", p, "-cq", str(int(crf)),
                "-rc", "vbr", "-g", "48",
                "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", str(preset), "-crf", str(int(crf)),
            "-g", "48", "-keyint_min", "48", "-pix_fmt", "yuv420p"]


def _hevc_enc_args(ffmpeg, preset="fast", crf=17):
    # v14.140: 同 h264，GOP=48 帧(2s) 防止长片/预览尾部无 IDR 花屏。
    if _nvenc_available(ffmpeg, "hevc"):
        p = _NVENC_PRESET.get(str(preset), "p4")
        return ["-c:v", "hevc_nvenc", "-preset", p, "-cq", str(int(crf)),
                "-rc", "vbr", "-g", "48",
                "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx265", "-preset", str(preset), "-crf", str(int(crf)),
            "-g", "48", "-pix_fmt", "yuv420p"]


def _start_video_encoder(ffmpeg, temp_video, width, height, fps, codec, crf, preset, log_path):
    if str(codec) == "H.265 / HEVC":
        enc = _hevc_enc_args(ffmpeg, preset, crf)
    elif str(codec) == "FFV1 lossless":
        enc = ["-c:v", "ffv1", "-level", "3", "-pix_fmt", "gbrp"]
    else:
        enc = _h264_enc_args(ffmpeg, preset, crf)

    cmd = [
        ffmpeg, "-y",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s:v", f"{int(width)}x{int(height)}",
        "-r", f"{float(fps):.9f}",
        "-i", "pipe:0",
        "-an",
        *enc,
        str(temp_video),
    ]
    log_f = open(log_path, "wb")
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log_f
    )
    return proc, log_f


def _despeckle_frames(images, chroma_radius=13, chroma_knee=0.07, chroma_span=0.12,
                      luma_thr=0.16, luma_span=0.12, luma_ratio=2.5):
    """v14.190: 去除 VAE 解码产生的彩点/亮点(青/绿/品红/红/白 小块色斑)。

    成因: 低步数采样后 VAE 解码在轮廓/高光处逐通道过冲(如 R=1.4/G=0.1/B=0.05),
    写 uint8 时按通道硬截断 → 2~6px 的高饱和色块。淡彩/低饱和画面里这些点成为
    画面唯一的高饱和像素, 所以格外刺眼。

    做法(只改彩度与孤立亮点, 不改结构):
      ① 转 YCbCr;
      ② 彩度: 以大半径(chroma_radius)均值作为参考彩度, 像素彩度与参考的差 d
         超过 knee 后按 span 线性过渡(0→1)把 Cb/Cr 混向参考值; **Y 原样保留**,
         所以轮廓/纹理锐度不变, 大面积真实色块因自身占满窗口而不被改动;
      ③ 亮度: 仅对"孤立"亮点/暗点(|Y - 邻域均值| 大, 且邻域本身平坦)整像素
         混向 5×5 均值; 真实高对比边缘的邻域不平坦, 因此锐度不受影响。
    实测(1920×1088 成片): PSNR≈39.9dB, 改动像素≈0.18%/帧, 彩点清除率>95%。

    入参/返回: [T,H,W,C] float(0..1); uint8 输入按 uint8 返回。
    """
    import torch as _t
    if images is None or int(images.numel()) == 0 or int(images.shape[-1]) < 3:
        return images
    _was_u8 = images.dtype == _t.uint8
    _x = images[..., :3].to(_t.float32)
    if _was_u8:
        _x = _x.div_(255.0)
    _lw = _t.tensor([0.299, 0.587, 0.114], dtype=_x.dtype, device=_x.device)
    _y = (_x * _lw).sum(dim=-1, keepdim=True)
    _cb = (_x[..., 2:3] - _y) * 0.564
    _cr = (_x[..., 0:1] - _y) * 0.713
    _pad = _t.nn.functional.pad
    _pool = _t.nn.functional.avg_pool2d
    _R = max(3, int(chroma_radius) | 1)

    # 彩度参考 = 大半径均值; 差异越大混合越强
    _cbcr = _t.cat([_cb, _cr], dim=-1).permute(0, 3, 1, 2)
    _ref = _pool(_pad(_cbcr, (_R // 2,) * 4, mode="replicate"), _R, 1).permute(0, 2, 3, 1)
    _d = (_t.cat([_cb, _cr], dim=-1) - _ref).abs().amax(dim=-1, keepdim=True)
    _al = ((_d - float(chroma_knee)) / max(1e-6, float(chroma_span))).clamp_(0.0, 1.0)
    _cb2 = _cb + (_ref[..., 0:1] - _cb) * _al
    _cr2 = _cr + (_ref[..., 1:2] - _cr) * _al

    # 亮度脉冲: 只处理"孤立亮点/暗点"——邻域本身平坦(mad 小)且自身偏离大,
    # 因此真实高对比边缘(mad 大)不会被磨掉
    _yp = _y.permute(0, 3, 1, 2)
    _m3 = _pool(_pad(_yp, (1, 1, 1, 1), mode="replicate"), 3, 1)
    _m8 = (_m3 * 9.0 - _yp) / 8.0          # 3×3 邻域(不含中心)均值
    _dev = (_yp - _m8).abs()
    _mad3 = _pool(_pad(_dev, (1, 1, 1, 1), mode="replicate"), 3, 1)
    _mad = (_mad3 * 9.0 - _dev) / 8.0      # 邻域自身的平坦度(也不含中心)
    _aly = ((_dev - float(luma_thr)) / max(1e-6, float(luma_span))).clamp_(0.0, 1.0)
    # 孤立性: 真实边缘的偏离/邻域起伏比约 1.5, 单像素脉冲可达 6+
    _aly = _aly * ((_dev / (_mad + 0.02) - float(luma_ratio)) / 1.5).clamp_(0.0, 1.0)
    _y2 = _yp + (_pool(_pad(_yp, (2, 2, 2, 2), mode="replicate"), 5, 1) - _yp) * _aly
    _y2 = _y2.permute(0, 2, 3, 1)

    _out = _t.cat([
        _y2 + 1.402 * _cr2,
        _y2 - 0.344 * _cb2 - 0.714 * _cr2,
        _y2 + 1.772 * _cb2,
    ], dim=-1).clamp_(0.0, 1.0)
    del _cbcr, _ref, _cb, _cr, _y, _yp, _m3, _m8, _dev, _mad3, _mad, _al, _aly
    if _was_u8:
        return _out.mul(255.0).add_(0.5).clamp_(0, 255).to(_t.uint8)
    return _out


def _write_image_frames(proc, images, batch_frames=64):
    """v1.69: batch 8->64——362 帧 1080p raw 传输 2.2GB, 大 batch 减少 Python
    循环/pipe 小写次数, 缓解 CPU/内存压力下的编码瓶颈(实测 132s -> 预期 ~50s).
    v1.70: uint8 CPU tensor 直写快路径(async encode 预转产物, 不再逐批转换)."""
    if proc.stdin is None:
        raise RuntimeError("Disk Final Decode: ffmpeg stdin is closed.")
    n = int(images.shape[0])
    # v14.190: 去彩点(色度去斑) 按 16 帧分块, 限制临时张量峰值(1080p/块约 1.4GB)
    _dp = 16
    if images.dtype == torch.uint8 and not images.is_cuda:
        for i in range(0, n, int(batch_frames)):
            part = images[i:i + int(batch_frames)]
            for s in range(0, int(part.shape[0]), _dp):
                proc.stdin.write(
                    _despeckle_frames(part[s:s + _dp]).contiguous().numpy().tobytes(order="C")
                )
            del part
        return
    for i in range(0, n, int(batch_frames)):
        part = images[i:i + int(batch_frames), ..., :3]
        part = (
            part.detach().float().clamp(0.0, 1.0)
        )
        for s in range(0, int(part.shape[0]), _dp):
            sub = _despeckle_frames(part[s:s + _dp])
            sub = sub.mul(255.0).add_(0.5).to(torch.uint8).cpu().contiguous()
            proc.stdin.write(sub.numpy().tobytes(order="C"))
            del sub
        del part


def _finish_process(proc, log_f, log_path, label):
    if proc.stdin is not None and not proc.stdin.closed:
        proc.stdin.close()
    code = proc.wait()
    log_f.close()
    if code != 0:
        tail = ""
        try:
            tail = Path(log_path).read_bytes()[-12000:].decode("utf-8", errors="replace")
        except Exception:
            pass
        raise RuntimeError(f"{label} failed with code {code}.\n{tail}")


def _audio_dirty_score(x_mix, sr):
    """v14.195: 病态音频门控 —— 仅在"恒定低频轰鸣"信号上启用清洗。

    渲染侧修复(v14.195 extender 音频质量保护)后, 音频要么是锁定的参考原声
    (干净), 要么是 ≥12 步生成的达标配音 —— 两者都不该被后处理改变音色/响度
    (完美标准: 参考原声 100-200Hz 仅 3.6%、200-400Hz 人声占 73%、有停顿静音)。
    旧渲染的低步数伪影特征: 100-250Hz 能量 >25% 且 200ms 窗 min RMS>0.02
    (全程无静音帧)。两者同时满足才视为病态(重低音音乐/男低音通常有动态与
    停顿, min RMS 低, 不会误判)。
    """
    if x_mix is None or int(x_mix.shape[0]) < 4096:
        return False
    try:
        seg = x_mix[: int(sr * 10)] if x_mix.shape[0] > int(sr * 10) else x_mix
        sp = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
        fr = np.fft.rfftfreq(len(seg), 1.0 / float(sr))
        tot = np.sum(sp ** 2) + 1e-30
        m = (fr >= 100.0) & (fr < 250.0)
        lf_ratio = float(np.sum(sp[m] ** 2) / tot)
        fl = int(sr * 0.2)
        nf = int(x_mix.shape[0]) // fl
        frm = np.sqrt(np.mean(x_mix[: nf * fl].reshape(nf, fl) ** 2, axis=1))
        return bool(lf_ratio > 0.25 and float(frm.min()) > 0.02)
    except Exception:
        return False


def _clean_audio_waveform(wave, sr, enabled=True):
    """v14.194: H3 audio latent 解码后的波形后处理 —— 消除恒定低频轰鸣/底噪/失真。

    诊断依据(h3_clip_250_1_1792842036, 一采8步+二采音频重绘0.7): 解码音频带
    恒定低频噪声底, ~95-200Hz 占全频能量~60%、50/100/150Hz 呈密集谐波串、全程
    无静音帧, 低频把人声盖在下面; AAC 编码/段间拼接/削波均排除, 噪声源头在
    模型侧 audio latent 解码输出, 旧管线无任何后处理滤波。

    处理(纯 numpy, CPU 秒级, <1s/15s音频):
      ① 去 DC(全局均值, 无瞬态);
      ② 低频轰鸣削减: STFT 域平滑增益曲线(≤50Hz -22dB → 150Hz -11.5dB →
         200Hz -9dB → 350Hz 0dB, 人声/音乐主体不动), 实测该信号各频点幅度
         无静音间隙(噪声估计≈中位数一半), 谱减/逐 bin min 估计会吞人声,
         故用确定性低频削减;
      ③ 语音带(300-3000Hz)噪声门: 包络 p3 估底×2.2 阈值, 停顿帧衰减 0.15,
         增益 ~0.13s 时间平滑防泵浦/爆音, 恢复停顿处静音;
      ④ 输出: 目标 RMS≈0.12(-18.4dBFS) 归一 + 峰值≤0.95 硬限。
    """
    if not enabled or wave is None or int(wave.shape[-1]) < 256:
        return wave
    try:
        _device = wave.device
        _dtype = wave.dtype
        x = wave.detach().float().cpu().numpy()
        orig_shape = x.shape
        if x.ndim == 1:
            x = x.reshape(1, 1, -1)
        elif x.ndim == 2:
            x = x.reshape(1, x.shape[0], x.shape[1])
        elif x.ndim != 3:
            return wave
        # v14.195: 病态门控 —— 渲染侧修复后音频已干净(参考原声/≥12步配音),
        # 非病态信号原样返回(不动音色/响度, 即"以完美音频为标准");
        # 仅恒定低频轰鸣(旧低步数渲染伪影)才进清洗兜底。
        if not _audio_dirty_score(np.mean(x, axis=(0, 1)), int(sr)):
            return wave
        B, C, _T = x.shape
        out = np.empty_like(x)
        for _b in range(B):
            for _c in range(C):
                out[_b, _c] = _clean_audio_channel(x[_b, _c], int(sr))
        return torch.from_numpy(out).to(device=_device, dtype=_dtype).reshape(orig_shape)
    except Exception:
        # 后处理失败绝不影响成片: 回退原始波形。
        return wave


def _lf_cut_gain(freqs, sr):
    """低频轰鸣削减曲线(纯增益, 无硬零 → 无时域瞬态):
       ≤50Hz  -22dB;  100Hz ≈ -15dB;  150Hz ≈ -11.5dB;  200Hz ≈ -9dB;
       250Hz ≈ -3.5dB;  300Hz ≈ -1dB;  350Hz 以上 ≈ 0dB(人声/音乐主体不动)。
       log-f 分段线性。
    """
    f = np.maximum(np.asarray(freqs, dtype=np.float64), 1e-3)
    g = np.ones_like(f)
    lo1, hi1 = 50.0, 200.0
    lo2, hi2 = 200.0, 350.0
    g_lo = 0.08
    g_mid = 0.35
    t1 = np.clip((np.log(f) - np.log(lo1)) / (np.log(hi1) - np.log(lo1)), 0.0, 1.0)
    t2 = np.clip((np.log(f) - np.log(lo2)) / (np.log(hi2) - np.log(lo2)), 0.0, 1.0)
    g = np.where(f < hi1, g_lo + (g_mid - g_lo) * t1, g_mid + (1.0 - g_mid) * t2)
    g[f <= lo1] = g_lo
    g[f >= hi2] = 1.0
    return g.astype(np.float32)


def _gate_gain(mag, freqs, sr, hop):
    """语音带(300-3000Hz)噪声门: 恒定低频噪声让全程无静音, 语音带包络在
    停顿处有真实低谷(声道随内容移动)。以包络 p3 估噪声底, 阈值=底×2.2,
    停顿帧衰减到 0.15, 增益做 ~0.13s 时间平滑防泵浦/爆音。"""
    band = (freqs >= 300.0) & (freqs <= 3000.0)
    if not np.any(band):
        return None
    env = np.sqrt(np.mean(mag[:, band] ** 2, axis=1))
    n = int(env.shape[0])
    fps_f = float(sr) / float(hop)
    w_sm = max(3, min(n, int(round(0.16 * fps_f))))
    # 包络平滑(移动平均)
    c = np.cumsum(np.concatenate([[0.0], env]))
    sm = np.empty_like(env)
    h = w_sm // 2
    for _i in range(n):
        lo = max(0, _i - h); hi = min(n, _i + h + 1)
        sm[_i] = (c[hi] - c[lo]) / float(hi - lo)
    thr = max(0.0025, float(np.percentile(sm, 3)) * 2.2)
    g = np.where(sm < thr, 0.15, 1.0).astype(np.float32)
    # 增益时间平滑(~0.13s)防帧间跳变
    w_g = max(3, min(n, int(round(0.13 * fps_f))))
    cg = np.cumsum(np.concatenate([[0.0], g.astype(np.float64)]))
    hg = w_g // 2
    gs = np.empty_like(g)
    for _i in range(n):
        lo = max(0, _i - hg); hi = min(n, _i + hg + 1)
        gs[_i] = np.float32((cg[hi] - cg[lo]) / float(hi - lo))
    return gs


def _clean_audio_channel(x, sr):
    n_fft = 2048 if int(sr) >= 32000 else 1024
    hop = n_fft // 2
    if x.shape[0] < n_fft:
        x = np.pad(x, (0, n_fft - x.shape[0]))
    x = x - float(np.mean(x))  # ① 去 DC(全局均值, 无瞬态)
    win = np.hanning(n_fft).astype(np.float32)
    n_frames = 1 + (x.shape[0] - n_fft) // hop
    frames = np.lib.stride_tricks.sliding_window_view(x, n_fft)[::hop][:n_frames]
    S = np.fft.rfft(frames * win, axis=1)
    mag = np.abs(S)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / float(sr))

    # ② 低频轰鸣削减 + ③ 语音带噪声门(恢复停顿处静音)。
    #    谱减/min-stat 在此信号上不可行(实测各频点幅度无静音间隙,
    #    噪声估计≈中位数一半, 逐 bin 减法必然吞人声)。
    g = _lf_cut_gain(freqs, sr)
    gg = _gate_gain(mag, freqs, sr, hop)
    if gg is not None:
        g = g * gg[:, None]
    S_out = S * g

    # ISTFT (50% overlap-add, win² 归一)。
    out = np.zeros(x.shape[0], dtype=np.float32)
    wsum = np.zeros(x.shape[0], dtype=np.float32)
    for _i in range(n_frames):
        seg = np.fft.irfft(S_out[_i], n=n_fft)
        _s = _i * hop
        out[_s:_s + n_fft] += seg * win
        wsum[_s:_s + n_fft] += win * win
    wsum[wsum < 1e-8] = 1.0
    out = out / wsum

    # ④ 归一限幅: 目标 RMS≈0.12(-18.4dBFS), 峰值≤0.95。
    rms = float(np.sqrt(np.mean(out * out)))
    if rms > 1e-6:
        out = out * (0.12 / rms)
    peak = float(np.max(np.abs(out)))
    if peak > 0.95:
        out = out * (0.95 / peak)
    return out


def _decode_audio_latent(audio_vae, latent, frames, fps):
    waveform = audio_vae.decode(latent).movedim(-1, 1)
    std = torch.std(waveform, dim=[1, 2], keepdim=True) * 5.0
    std[std < 1.0] = 1.0
    waveform = waveform / std
    sr = int(
        getattr(
            audio_vae,
            "audio_sample_rate_output",
            getattr(audio_vae, "audio_sample_rate", 32000),
        )
    )
    # v14.194: 解码后处理——去恒定低频轰鸣/底噪/失真(纯 numpy, 秒级)。
    # 环境变量 BSAI_H3_AUDIO_CLEAN=0 可关闭以便 A/B 对比。
    if os.environ.get("BSAI_H3_AUDIO_CLEAN", "1") != "0":
        waveform = _clean_audio_waveform(waveform, sr)
    return _audio_exact_frames(
        {"waveform": waveform, "sample_rate": sr}, int(frames), float(fps)
    )


def _decode_single_audio(data_path, desc, audio_vae, fps):
    latent = _load_segment_audio(data_path, desc)
    return _decode_audio_latent(audio_vae, latent, int(desc["frames"]), fps)


def _decode_pair_audio(data_path, prev_desc, curr_desc, audio_vae, fps, seam_shift):
    prev_a = _load_segment_audio(data_path, prev_desc)
    next_a = _load_segment_audio(data_path, curr_desc)

    previous_frames = int(prev_desc["frames"])
    next_frames = int(curr_desc["frames"])
    trim = int(curr_desc["trim_frames"])
    video_trim_t = 0 if trim == 0 else _steps_for_frames(trim)
    if trim > 0 and video_trim_t is None:
        raise ValueError("Disk Final Decode audio: invalid H3 trim grid.")

    warmup_video_t = 5 if int(video_trim_t) >= 7 else 0
    decode_start_t = int(video_trim_t) - int(warmup_video_t)
    warmup_start_frames = _pixel_frames(decode_start_t) if decode_start_t > 0 else 0
    warmup_frames = trim - warmup_start_frames

    decode_frames = previous_frames + next_frames - warmup_start_frames
    target_audio_t = _audio_t_for_frames(decode_frames)
    audio_start_t = int(prev_a.shape[-1]) + int(next_a.shape[-1]) - int(target_audio_t)
    if audio_start_t < 0 or audio_start_t >= int(next_a.shape[-1]):
        raise RuntimeError("Disk Final Decode audio: invalid warm-up start.")

    chain_audio = torch.cat((prev_a, next_a[..., audio_start_t:]), dim=-1)
    decoded = _decode_audio_latent(audio_vae, chain_audio, decode_frames, fps)
    w = decoded["waveform"]
    sr = int(decoded["sample_rate"])

    prev_n = int(round(float(previous_frames) / float(fps) * sr))
    effective_warm = max(0, int(warmup_frames) + int(seam_shift))
    warm_n = int(round(float(effective_warm) / float(fps) * sr))
    cut_b = prev_n + warm_n
    if cut_b >= int(w.shape[-1]):
        raise RuntimeError("Disk Final Decode audio: warm-up removes continuation.")

    # v14.178 一镜到底全球方案落地 P0-4: 接缝 PCM 硬切 → 15ms 线性 crossfade de-click。
    # 旧: cat(w[:prev_n], w[cut_b:]) 样本级硬切(诊断: 段间边界爆音/音色突变)。
    # 现: 本段头 fade_n=15ms 样本与上段尾同长样本线性混合 —— 时间轴与样本数守恒
    # (就地替换 curr 段头), 15ms 内人耳不可感停顿, 只消除开关式瞬态。
    prev_part = w[..., :prev_n]
    curr_part = w[..., cut_b:]
    fade_n = int(round(0.015 * sr))
    if fade_n > 0 and prev_part.shape[-1] >= fade_n and curr_part.shape[-1] > fade_n:
        ramp = torch.linspace(0.0, 1.0, fade_n, device=w.device, dtype=w.dtype)
        _prev_tail = prev_part[..., -fade_n:]
        _curr_head = curr_part[..., :fade_n]
        _blended = _prev_tail * (1.0 - ramp) + _curr_head * ramp
        curr_part = torch.cat((_blended, curr_part[..., fade_n:]), dim=-1)
    pair = {
        "waveform": torch.cat((prev_part, curr_part), dim=-1),
        "sample_rate": sr,
    }
    final_frames = previous_frames + next_frames - trim
    pair = _audio_exact_frames(pair, final_frames, fps)
    return pair, previous_frames, next_frames - trim


def _smooth_segment_entry_level(
    previous_tail,
    current,
    sample_rate,
    level_milliseconds=10.0,
    ramp_milliseconds=300.0,
    max_atten_db=18.0,
):
    """Soften a local upward loudness step without moving the audio timeline.

    H3 can generate a genuinely different musical state for the continuation
    clip. That cannot be repaired by a splice operation, but a sudden onset
    right after a quiet clip tail is especially audible as a bump. Measure the
    *very end* of the accepted previous PCM (10 ms) and the beginning of the
    new clip, then attenuate only the new clip when needed and let it rise
    smoothly to its native level over 300 ms. We deliberately never boost a
    quiet continuation: this is a seam mask, not loudness mastering.
    """
    if previous_tail is None or int(previous_tail.shape[-1]) < 2 or int(current.shape[-1]) < 2:
        return current

    sr = max(1, int(sample_rate))
    level_n = int(round(float(level_milliseconds) * 0.001 * sr))
    level_n = max(2, min(level_n, int(previous_tail.shape[-1]), int(current.shape[-1])))
    ramp_n = int(round(float(ramp_milliseconds) * 0.001 * sr))
    ramp_n = max(2, min(ramp_n, int(current.shape[-1])))

    prev = previous_tail[..., -level_n:].detach().float()
    head = current[..., :level_n].detach().float()
    prev_level = float(torch.sqrt(torch.mean(prev * prev) + 1.0e-12).item())
    curr_level = float(torch.sqrt(torch.mean(head * head) + 1.0e-12).item())
    if not math.isfinite(prev_level) or not math.isfinite(curr_level) or curr_level <= 1.0e-8:
        return current

    start_gain = min(1.0, prev_level / curr_level)
    min_gain = math.pow(10.0, -abs(float(max_atten_db)) / 20.0)
    start_gain = max(min_gain, start_gain)
    # Ignore tiny changes; they are less audible than touching the waveform.
    if start_gain >= math.pow(10.0, -0.5 / 20.0):
        return current

    out = current.clone()
    k = torch.arange(ramp_n, device=out.device, dtype=out.dtype)
    phase = torch.tensor(math.pi, device=out.device, dtype=out.dtype) * k / float(ramp_n - 1)
    rise = 0.5 * (1.0 - torch.cos(phase))
    gain = float(start_gain) + (1.0 - float(start_gain)) * rise
    out[..., :ramp_n] = out[..., :ramp_n] * gain
    return out


def _declick_segment(previous_tail, current, sample_rate, milliseconds=12.0):
    if previous_tail is None or int(previous_tail.shape[-1]) < 2 or int(current.shape[-1]) < 2:
        return current
    n = int(round(float(milliseconds) * 0.001 * int(sample_rate)))
    n = max(2, min(n, int(current.shape[-1])))
    out = current.clone()
    prev2 = previous_tail[..., -2]
    prev1 = previous_tail[..., -1]
    first = out[..., 0]
    target = prev1 + (prev1 - prev2)
    correction = first - target
    k = torch.arange(n, device=out.device, dtype=out.dtype)
    decay = 0.5 * (
        1.0 + torch.cos(
            torch.tensor(math.pi, device=out.device, dtype=out.dtype)
            * k / float(n - 1)
        )
    )
    out[..., :n] = out[..., :n] - correction.unsqueeze(-1) * decay
    return out


def _audio_seam_tail(wave, sample_rate, milliseconds=25.0):
    if wave is None or int(wave.shape[-1]) < 2:
        return None
    n = int(round(float(milliseconds) * 0.001 * max(1, int(sample_rate))))
    n = max(2, min(n, int(wave.shape[-1])))
    return wave[..., -n:].detach().clone()


def _audio_level_for_gain_match(wave, sample_rate):
    """Stable level estimate for two decodes of the same previous clip."""
    if wave is None or int(wave.shape[-1]) < 2:
        return None
    n = int(wave.shape[-1])
    edge = min(int(round(0.100 * int(sample_rate))), max(0, n // 4))
    if n - (2 * edge) >= max(32, int(round(0.250 * int(sample_rate)))):
        x = wave[..., edge:n - edge]
    else:
        x = wave
    level = float(torch.std(x.detach().float()).item())
    if not math.isfinite(level) or level < 1.0e-5:
        return None
    return level


def _match_pair_gain_to_previous(previous_timeline, pair_previous, sample_rate):
    """Recover the gain offset introduced by independent H3 pair decodes.

    The compared tails represent the same previous clip. The resulting scalar is
    applied to the new section of the pair, preserving its internal dynamics.
    """
    if previous_timeline is None or pair_previous is None:
        return 1.0
    common = min(int(previous_timeline.shape[-1]), int(pair_previous.shape[-1]))
    if common < max(32, int(round(0.250 * int(sample_rate)))):
        return 1.0
    ref = previous_timeline[..., -common:]
    cand = pair_previous[..., -common:]
    ref_level = _audio_level_for_gain_match(ref, sample_rate)
    cand_level = _audio_level_for_gain_match(cand, sample_rate)
    if ref_level is None or cand_level is None:
        return 1.0
    gain = float(ref_level / cand_level)
    limit = 10.0 ** (12.0 / 20.0)
    return max(1.0 / limit, min(limit, gain))


def _fit_audio_segment_to_cumulative(wave, target_total, written_total):
    need = max(0, int(target_total) - int(written_total))
    if int(wave.shape[-1]) > need:
        wave = wave[..., :need]
    elif int(wave.shape[-1]) < need:
        wave = torch.nn.functional.pad(wave, (0, need - int(wave.shape[-1])))
    return wave


def _write_audio_raw(file_obj, wave):
    x = wave[0].detach().float().transpose(0, 1).cpu().contiguous()
    file_obj.write(x.numpy().astype("float32", copy=False).tobytes(order="C"))


def _mux_final(ffmpeg, temp_video, raw_audio, output_path, sr, channels, codec, audio_bitrate, log_path):
    audio_args = ["-c:a", "flac"] if str(codec) == "FFV1 lossless" else ["-c:a", "aac", "-b:a", str(audio_bitrate)]
    cmd = [
        ffmpeg, "-y",
        "-i", str(temp_video),
        "-f", "f32le",
        "-ar", str(int(sr)),
        "-ac", str(int(channels)),
        "-i", str(raw_audio),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        *audio_args,
    ]
    if str(output_path).lower().endswith(".mp4"):
        cmd += ["-movflags", "+faststart"]
    cmd.append(str(output_path))

    with open(log_path, "wb") as log_f:
        p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=log_f)
    if p.returncode != 0:
        tail = ""
        try:
            tail = Path(log_path).read_bytes()[-12000:].decode("utf-8", errors="replace")
        except Exception:
            pass
        raise RuntimeError(f"Disk Final Decode mux failed with code {p.returncode}.\n{tail}")


def _comfy_media_item(path, fps, media_type):
    """
    Build a normal ComfyUI /view media descriptor.
    media_type must be 'temp' or 'output'.
    """
    path = Path(path).resolve()

    if folder_paths is None:
        return {
            "filename": path.name,
            "subfolder": "",
            "type": str(media_type),
            "format": "video/mp4",
            "frame_rate": float(fps),
        }

    if str(media_type) == "temp":
        root = _comfyui_temp_dir().resolve()
    else:
        root = Path(folder_paths.get_output_directory()).resolve()

    try:
        rel = path.relative_to(root)
        subfolder = "" if str(rel.parent) == "." else str(rel.parent).replace("\\", "/")
        filename = rel.name
    except Exception:
        # Custom output directories are not served by /view. The caller should
        # publish a temp preview copy first.
        subfolder = ""
        filename = path.name

    return {
        "filename": filename,
        "subfolder": subfolder,
        "type": str(media_type),
        "format": "video/mp4",
        "frame_rate": float(fps),
    }


def _preview_temp_root():
    if folder_paths is not None:
        root = _comfyui_temp_dir().resolve()
    else:
        root = _ensure_cache_root() / "_preview"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _preview_temp_path(unique_id, slot=0):
    root = _preview_temp_root()
    return root / f"h3_motion_preview_{_safe_name(unique_id)}_{int(slot)}.mp4"


def _preview_temp_legacy_path(unique_id):
    return _preview_temp_root() / f"h3_motion_preview_{_safe_name(unique_id)}.mp4"


def _preview_rotation_order(unique_id):
    slots = [
        _preview_temp_path(unique_id, i) for i in range(int(PREVIEW_ROTATION_SLOTS))
    ]
    existing = [(i, p.stat().st_mtime) for i, p in enumerate(slots) if p.exists()]
    if not existing:
        return list(range(int(PREVIEW_ROTATION_SLOTS)))
    latest_idx = max(existing, key=lambda x: x[1])[0]
    return [
        (latest_idx + step) % int(PREVIEW_ROTATION_SLOTS)
        for step in range(1, int(PREVIEW_ROTATION_SLOTS) + 1)
    ]


def _reserve_preview_temp_path(unique_id):
    """Pick the next preview slot in a 3-file rotation.

    We never touch the slot that was most recently published first, because on
    Windows the browser/video player may keep it locked for a long time. We try
    the other two slots first and only reuse a slot when it can actually be
    deleted/replaced.
    """
    # Best-effort cleanup of the pre-v14.50 single preview file.
    legacy = _preview_temp_legacy_path(unique_id)
    if legacy.exists():
        try:
            legacy.unlink()
        except OSError:
            pass

    # Clean up ALL rotation slots first — the browser may have released
    # locks on older slots since the last restore. This prevents temp
    # files from accumulating across multiple page refreshes.
    for idx in range(int(PREVIEW_ROTATION_SLOTS)):
        p = _preview_temp_path(unique_id, idx)
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass

    last_error = None
    for idx in _preview_rotation_order(unique_id):
        candidate = _preview_temp_path(unique_id, idx)
        if candidate.exists():
            try:
                candidate.unlink()
            except OSError as e:
                last_error = e
                continue
        return candidate

    raise PermissionError(
        "H3 preview rotation: all preview slots are currently locked by another "
        f"process for node {unique_id!r}."
    ) from last_error


def _latest_preview_temp_path(unique_id):
    candidates = [
        _preview_temp_path(unique_id, i) for i in range(int(PREVIEW_ROTATION_SLOTS))
    ]
    existing = [p for p in candidates if p.exists()]
    if not existing:
        legacy = _preview_temp_legacy_path(unique_id)
        if legacy.exists():
            return legacy
        return None
    return max(existing, key=lambda p: p.stat().st_mtime)


def _normalize_color_adjustment(value=None):
    raw = value if isinstance(value, dict) else {}

    def _v(name, default, low, high):
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


def _color_is_neutral(value):
    c = _normalize_color_adjustment(value)
    return all(abs(float(c[k]) - 100.0) < 1e-6 for k in ("saturation", "contrast", "brightness"))


def _color_timeline(segments, fps):
    fps = float(fps or FPS)
    cursor = 0
    out = []
    for i, desc in enumerate(segments or []):
        contribution = int(desc.get("frames", 0))
        if i > 0:
            contribution -= int(desc.get("trim_frames", 0))
        contribution = max(0, contribution)
        start = float(cursor / fps)
        cursor += contribution
        end = float(cursor / fps)
        adjustment = _normalize_color_adjustment(desc.get("color_adjustment"))
        out.append({
            "index": int(i),
            "start": start,
            "end": end,
            "adjustment": adjustment,
            "modified": not _color_is_neutral(adjustment),
        })
    return out


def _timeline_has_color(timeline):
    return any(bool(item.get("modified")) for item in (timeline or []))


def _ffmpeg_color_filter(timeline):
    """Build filters that closely mirror browser CSS saturate/contrast/brightness.

    Keeping the live editor and the baked FFmpeg result on the same transform
    model makes the adjustment effectively WYSIWYG while preserving a neutral
    decoded source in cache.
    """
    filters = []
    for item in timeline or []:
        if not bool(item.get("modified")):
            continue
        c = _normalize_color_adjustment(item.get("adjustment"))
        sat = float(c["saturation"]) / 100.0
        contrast = float(c["contrast"]) / 100.0
        brightness = float(c["brightness"]) / 100.0
        start = float(item.get("start", 0.0))
        end = float(item.get("end", start))
        enable = f"gte(t\\,{start:.6f})*lt(t\\,{end:.6f})"

        # CSS saturate() matrix (Filter Effects spec luminance coefficients).
        rr = 0.213 + 0.787 * sat
        rg = 0.715 - 0.715 * sat
        rb = 0.072 - 0.072 * sat
        gr = 0.213 - 0.213 * sat
        gg = 0.715 + 0.285 * sat
        gb = 0.072 - 0.072 * sat
        br = 0.213 - 0.213 * sat
        bg = 0.715 - 0.715 * sat
        bb = 0.072 + 0.928 * sat
        filters.append(
            "colorchannelmixer="
            f"rr={rr:.8f}:rg={rg:.8f}:rb={rb:.8f}:"
            f"gr={gr:.8f}:gg={gg:.8f}:gb={gb:.8f}:"
            f"br={br:.8f}:bg={bg:.8f}:bb={bb:.8f}:"
            f"enable='{enable}'"
        )

        # CSS contrast() followed by brightness(), combined as one affine RGB LUT.
        gain = contrast * brightness
        offset = 255.0 * (0.5 * (1.0 - contrast) * brightness)
        expr = f"clip(val*{gain:.8f}{offset:+.8f},0,255)"
        filters.append(
            "lutrgb="
            f"r='{expr}':g='{expr}':b='{expr}':enable='{enable}'"
        )
    return ",".join(filters)


def _video_reencode_args(codec, crf, preset):
    if str(codec) == "H.265 / HEVC":
        return _hevc_enc_args(_find_ffmpeg(), preset, crf)
    if str(codec) == "FFV1 lossless":
        return ["-c:v", "ffv1", "-level", "3", "-pix_fmt", "gbrp"]
    return _h264_enc_args(_find_ffmpeg(), preset, crf)


def _apply_color_timeline_to_file(
    ffmpeg,
    source_path,
    destination_path,
    timeline,
    codec="H.264",
    crf=17,
    preset="fast",
):
    source = Path(source_path)
    destination = Path(destination_path)
    vf = _ffmpeg_color_filter(timeline)
    if not vf:
        shutil.copy2(source, destination)
        return destination

    log_path = _ensure_cache_root() / f"_color_{uuid.uuid4().hex[:10]}.log"
    cmd = [
        ffmpeg, "-y",
        "-i", str(source),
        "-map", "0:v:0",
        "-map", "0:a?",
        "-vf", vf,
        *_video_reencode_args(codec, crf, preset),
        "-c:a", "copy",
    ]
    if str(destination).lower().endswith(".mp4"):
        cmd += ["-movflags", "+faststart"]
    cmd.append(str(destination))
    try:
        with open(log_path, "wb") as log_f:
            proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=log_f)
        if proc.returncode != 0:
            tail = ""
            try:
                tail = log_path.read_bytes()[-12000:].decode("utf-8", errors="replace")
            except Exception:
                pass
            raise RuntimeError(f"H3 color correction failed with ffmpeg code {proc.returncode}.\n{tail}")
        return destination
    finally:
        try:
            log_path.unlink(missing_ok=True)
        except Exception:
            pass


def _publish_full_preview(output_path, unique_id):
    """
    Put the final file under ComfyUI temp so the in-node browser player always
    has a /view-compatible URL, including when output_directory is custom.
    Uses a 3-file rotation so the UI never tries to replace the MP4 that is
    currently opened by the browser player on Windows.
    """
    src = Path(output_path).resolve()
    dst = _reserve_preview_temp_path(unique_id)

    try:
        os.link(src, dst)
    except Exception:
        shutil.copy2(src, dst)
    return dst



def _saved_preview_output_path():
    """Return a unique human-readable MP4 path in the normal ComfyUI output dir."""
    if folder_paths is not None:
        root = Path(folder_paths.get_output_directory()).resolve()
    else:
        root = _ensure_cache_root() / "_saved_previews"
    root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return root / f"MiniMax_H3_preview_{stamp}_{uuid.uuid4().hex[:4]}.mp4"


def _ffmetadata_escape(value):
    """Escape one single-line ffmetadata value without putting JSON on argv."""
    text = str(value)
    text = text.replace("\\", "\\\\")
    text = text.replace("=", "\\=")
    text = text.replace(";", "\\;")
    text = text.replace("#", "\\#")
    text = text.replace("\r", "")
    text = text.replace("\n", "\\\n")
    return text


def _save_preview_with_metadata(source_path, workflow=None, prompt=None, color_timeline=None):
    """Save the assembled preview to output with ComfyUI-compatible MP4 metadata.

    The rolling preview itself stays non-destructive/neutral. If per-clip color
    adjustments exist, bake them only into the saved copy, then attach the same
    `workflow` / `prompt` tags used by ComfyUI SaveVideo.
    """
    source = Path(source_path).resolve()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError("H3 Save Preview: current preview file was not found.")

    ffmpeg = _find_ffmpeg()
    output = _saved_preview_output_path()
    root = _ensure_cache_root()
    token = f"save_preview_{uuid.uuid4().hex[:10]}"
    metadata_path = root / f"_{token}.ffmeta"
    log_path = root / f"_{token}.log"
    corrected_path = root / f"_{token}_color.mp4"

    metadata = {}
    if workflow is not None:
        metadata["workflow"] = workflow
    if prompt is not None:
        metadata["prompt"] = prompt

    try:
        source_for_metadata = source
        if _timeline_has_color(color_timeline):
            _apply_color_timeline_to_file(
                ffmpeg, source, corrected_path, color_timeline,
                codec="H.264", crf=17, preset="fast",
            )
            source_for_metadata = corrected_path

        lines = [";FFMETADATA1"]
        for key, value in metadata.items():
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            lines.append(f"{key}={_ffmetadata_escape(encoded)}")
        metadata_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        cmd = [
            ffmpeg,
            "-y",
            "-i", str(source_for_metadata),
            "-f", "ffmetadata",
            "-i", str(metadata_path),
            "-map", "0",
            "-map_metadata", "1",
            "-c", "copy",
            "-movflags", "use_metadata_tags+faststart",
            str(output),
        ]
        with open(log_path, "wb") as log_f:
            proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=log_f)
        if proc.returncode != 0:
            tail = ""
            try:
                tail = log_path.read_bytes()[-12000:].decode("utf-8", errors="replace")
            except Exception:
                pass
            try:
                output.unlink(missing_ok=True)
            except Exception:
                pass
            raise RuntimeError(
                f"H3 Save Preview failed with ffmpeg code {proc.returncode}.\n{tail}"
            )
        return output
    finally:
        for path in (metadata_path, log_path, corrected_path):
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass



# -----------------------------------------------------------------------------
# v12.5 - progressive FULL decoded preview cache
# -----------------------------------------------------------------------------

def _decoded_preview_cache_path(data_path):
    return Path(data_path).with_suffix(".preview.mp4")


def _decoded_preview_video_cache_path(data_path):
    return Path(data_path).with_suffix(".preview.video.mp4")


def _validated_prefix_count(segments):
    n = 0
    for desc in segments:
        if not bool(desc.get("validated", False)):
            break
        n += 1
    return n


def _latent_payload_end(desc):
    a = desc["audio"]
    return int(a["offset"]) + int(a["nbytes"])


def _write_blob_raw(file_obj, source_path):
    source_path = Path(source_path)
    spec = {
        "offset": int(file_obj.tell()),
        "nbytes": int(source_path.stat().st_size),
    }
    with open(source_path, "rb") as src:
        while True:
            chunk = src.read(8 * 1024 * 1024)
            if not chunk:
                break
            file_obj.write(chunk)
    return spec


def _copy_blob_to_file(data_path, spec, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    remaining = int(spec["nbytes"])
    with open(data_path, "rb") as src, open(destination, "wb") as dst:
        src.seek(int(spec["offset"]))
        while remaining > 0:
            chunk = src.read(min(remaining, 8 * 1024 * 1024))
            if not chunk:
                raise IOError("H3 decoded-render blob is truncated.")
            dst.write(chunk)
            remaining -= len(chunk)


def _cache_candidate_render(
    data_path,
    manifest_path,
    manifest,
    clip_index,
    rendered_mp4,
    rendered_audio,
):
    """Persist the corrected candidate render next to its latent payload.

    The MP4 blob is video-only and is kept for the already-decoded video cache.
    Starting with v14.42 we ALSO persist the corrected decoded waveform losslessly. Full
    previews can then concatenate PCM and perform one AAC encode for the whole
    timeline instead of stream-copying independently primed AAC streams at each
    seam.
    """
    segments = [dict(x) for x in manifest.get("segments", [])]
    idx = int(clip_index)
    if idx != len(segments) - 1:
        raise RuntimeError(
            "H3 progressive preview can cache only the current tail candidate."
        )

    desc = dict(segments[idx])
    latent_end = int(desc.get("latent_end", _latent_payload_end(desc)))

    wave = rendered_audio["waveform"]
    if wave.ndim == 2:
        wave = wave.unsqueeze(0)
    if wave.ndim != 3 or int(wave.shape[0]) != 1:
        raise ValueError(
            f"H3 progressive preview: invalid decoded audio shape {tuple(wave.shape)}."
        )

    with open(data_path, "r+b", buffering=0) as f:
        f.truncate(latent_end)
        f.seek(latent_end)
        render_spec = _write_blob_raw(f, rendered_mp4)
        audio_spec = _write_tensor_raw(f, wave)
        segment_end = int(f.tell())
        f.flush()
        os.fsync(f.fileno())

    desc["latent_end"] = latent_end
    desc["decoded_mp4_blob"] = render_spec
    desc["decoded_audio"] = {
        "waveform": audio_spec,
        "sample_rate": int(rendered_audio["sample_rate"]),
        "timeline_gain": 1.0,
    }
    desc["segment_end"] = segment_end
    segments[idx] = desc

    updated = dict(manifest)
    updated["segments"] = segments
    updated["build"] = BUILD
    updated["updated_at"] = time.time()
    _write_json_atomic(manifest_path, updated)
    return updated, desc


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


def _rescale_segment_blob(owner_id, clip_index, target_w, target_h, fps, ffmpeg=None):
    """v14.156: 把已缓存的 decoded MP4 blob 精确重采样到工作流声明的输出尺寸。

    显存预算不足时二采倍率会被静默降级（x2.0 -> x1.5），旧 blob 的像素因此
    小于声明尺寸。这里用 ffmpeg 重编码视频轨（GOP=48，与预览编码一致）并直接
    copy 音频轨：既避免逐段 VAE 重解码（慢），也不会丢失对口型模式的歌曲混音。
    数据文件是 append-only 布局（每段 latent -> blob -> decoded_audio），因此新
    blob 一律追加到文件末尾并更新偏移，绝不 truncate，避免删除后续段的 latent
    （也避免删掉此前追加的 blob）。
    """
    data_path, manifest_path = _chain_paths(f"extender_{_safe_name(str(owner_id))}")
    manifest = _load_manifest_from_paths(data_path, manifest_path)
    if manifest is None:
        return None
    segments = [dict(x) for x in manifest.get("segments", [])]
    i = int(clip_index)
    if i < 0 or i >= len(segments):
        return None
    curr = segments[i]
    blob = curr.get("decoded_mp4_blob")
    if blob is None:
        return None
    target_w = int(target_w)
    target_h = int(target_h)
    if target_w <= 0 or target_h <= 0:
        return None
    if (int(curr.get("decoded_mp4_width", 0) or 0) == target_w
            and int(curr.get("decoded_mp4_height", 0) or 0) == target_h):
        return curr
    if ffmpeg is None:
        try:
            ffmpeg = _find_ffmpeg()
        except Exception:
            ffmpeg = None
    if ffmpeg is None:
        return None

    root = _ensure_cache_root()
    token = f"clipscale_{_safe_name(str(owner_id))}_{i}_{uuid.uuid4().hex[:8]}"
    src = root / f"_{token}_in.mp4"
    dst = root / f"_{token}_out.mp4"
    log_path = root / f"_{token}.log"
    try:
        _copy_blob_to_file(data_path, blob, src)
        enc = _h264_enc_args(ffmpeg, "veryfast", 15)
        cmd = [
            ffmpeg, "-y",
            "-i", str(src),
            "-vf", f"scale={target_w}:{target_h}:flags=lanczos,setsar=1",
            "-r", f"{float(fps):.9f}",
            "-c:a", "copy",
            *enc,
            "-movflags", "+faststart",
            str(dst),
        ]
        with open(log_path, "wb") as log_f:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=log_f,
                           check=True, timeout=900)
        if not dst.exists() or dst.stat().st_size <= 0:
            raise RuntimeError("rescaled mp4 is empty")
        print(f"[H3 Extender] 输出尺寸校正 clip={i + 1}: "
              f"-> {target_w}x{target_h} (保留原音轨)")

        is_tail = (i == len(segments) - 1)
        latent_end = int(curr.get("latent_end", _latent_payload_end(curr)))
        # v14.156: 只追加、不截断。数据文件是 append-only 布局，非尾段 truncate
        # 会删除后续段的 latent；而任何一次追加之后，尾段的 truncate 也会删掉
        # 这些新 blob。新增 latent 时 EOF 恰好等于 latent_end，追加与重写等价。
        with open(data_path, "ab", buffering=0) as f:
            f.seek(0, 2)
            render_spec = _write_blob_raw(f, dst)
            if is_tail:
                curr["segment_end"] = int(f.tell())
            f.flush()
            os.fsync(f.fileno())

        curr["latent_end"] = latent_end
        curr["decoded_mp4_blob"] = render_spec
        curr["decoded_mp4_version"] = 6  # v14.236: v6 = 时间分块解码加块间上下文(修复 ~16 帧亮度闪烁); v5 blob 不再复用
        curr["decoded_mp4_width"] = target_w
        curr["decoded_mp4_height"] = target_h
        segments[i] = curr

        updated = dict(manifest)
        updated["segments"] = segments
        updated["build"] = BUILD
        updated["updated_at"] = time.time()
        _write_json_atomic(manifest_path, updated)
        return curr
    except Exception as _e:
        print(f"[H3 Extender] 输出尺寸校正 clip={i + 1} 失败: {_e}")
        return None
    finally:
        for _p in (src, dst, log_path):
            try:
                if _p.exists():
                    _p.unlink()
            except Exception:
                pass


def _decode_single_clip_to_blob(
    owner_id,
    clip_index,
    vae,
    audio_vae,
    fps,
    ffmpeg=None,
    async_encode=False,
    lip_audio_segment=None,
):
    """Decode one cached clip's latent to an MP4 blob and persist it in the segment.

    Unlike _export_live_candidate_preview, this does NOT require the clip to be
    the single unvalidated tail candidate. It works on any cached clip index.

    For clip_index > 0, the leading trim_frames (context overlap with the
    previous clip) are removed from both video and audio so that:
      1. Per-clip previews show only the clip's unique content
      2. Simple ffmpeg-concat of per-clip MP4s produces a correct merged video
         without duplicated frames at clip boundaries
    """
    data_path, manifest_path = _chain_paths(f"extender_{_safe_name(str(owner_id))}")
    manifest = _load_manifest_from_paths(data_path, manifest_path)
    if manifest is None:
        print(f"[H3 Extender] _decode_single_clip_to_blob: no manifest for owner={owner_id}")
        return None
    segments = [dict(x) for x in manifest.get("segments", [])]
    i = int(clip_index)
    if i < 0 or i >= len(segments):
        print(f"[H3 Extender] _decode_single_clip_to_blob: clip {i} out of range (have {len(segments)} segments)")
        return None
    curr = segments[i]

    # v14.156: 工作流声明的最终输出尺寸（一采像素 × 声明二采倍率）。显存预算
    # 不足时二采倍率会被静默降级（x2.0 -> x1.5），latent/解码像素随之变小；
    # 这里记下目标尺寸，解码后精确重采样，保证成片始终是声明尺寸。
    _tgt_w = int(manifest.get("output_width", 0) or 0)
    _tgt_h = int(manifest.get("output_height", 0) or 0)
    # v14.157: 旧链 / 续跑恢复的链可能没有 output_width/height —— 用
    # 一采尺寸 × 声明二采倍率补算，避免被显存预算降级过的段以 1440x800
    # 直接混进成片（声明是 1920x1088）。
    if _tgt_w <= 0 or _tgt_h <= 0:
        try:
            _f_dec = float(manifest.get("declared_refine_factor", 0) or 0)
            _fpw = int(manifest.get("first_pass_width", 0) or 0)
            _fph = int(manifest.get("first_pass_height", 0) or 0)
            if _f_dec > 1.0 and _fpw > 0 and _fph > 0:
                _tgt_w = int(round(float(_fpw) * _f_dec))
                _tgt_h = int(round(float(_fph) * _f_dec))
                print(f"[H3 Extender] v14.157 补算声明输出尺寸: "
                      f"{_fpw}x{_fph} × x{_f_dec:.1f} -> {_tgt_w}x{_tgt_h}")
        except Exception:
            pass

    # If already decoded with the current version, skip.
    # v2 = trimmed overlap + audio included.  Old blobs (no version marker)
    # contained full frames (with overlap) and no audio, so we must rebuild.
    # v14.141: decoded_mp4_version 升到 3 —— v2 blob 的编码 GOP=250(10.4s) 导致
    # 预览/成片尾部无 IDR 关键帧而雪花；升版后旧 blob 全部失效、按 GOP=48(2s)
    # 重新编码，预览/渐进全片/最终成片尾部均可独立解码。
    # v14.236: decoded_mp4_version 升到 6 —— v5 blob 由 v14.232 裸 16 帧分块解码
    # 生成, 块间无时间上下文, 每 ~16 帧亮度闪烁; 升版强制重解码以应用修复。
    if curr.get("decoded_mp4_blob") is not None and curr.get("decoded_mp4_version", 0) >= 6:
        _cur_w = int(curr.get("decoded_mp4_width", 0) or 0)
        _cur_h = int(curr.get("decoded_mp4_height", 0) or 0)
        if _tgt_w <= 0 or _tgt_h <= 0 or (_cur_w == _tgt_w and _cur_h == _tgt_h):
            return curr
        # 已有 blob 像素与声明尺寸不符：优先 ffmpeg 重采样（保留原音轨/歌曲混音），
        # 不改动 latent 链，避免逐段 VAE 重解码。失败才继续走完整重解码。
        _scaled = _rescale_segment_blob(owner_id, i, _tgt_w, _tgt_h, fps, ffmpeg)
        if _scaled is not None:
            return _scaled

    print(f"[H3 Extender] _decode_single_clip_to_blob: clip={i} data_path={data_path} ffmpeg={ffmpeg}")
    import time as _t66
    _t66_t0 = _t66.time()
    def _t66_mark(tag):
        print(f"[H3 Extender]   decode耗时[{tag}]: {_t66.time()-_t66_t0:.1f}s (累计)")

    trim = int(curr.get("trim_frames", 0)) if i > 0 else 0
    total_frames = int(curr["frames"])
    out_frames = total_frames - trim

    # Decode video latent
    print(f"[H3 Extender]   step 1: loading segment video...")
    # v14.225 (2026-10-27): decode VRAM 加固 —— 解码前把 DiT 完全请出 GPU。
    # 旧逻辑 partially_unload + 跳过 ck-quant(量化 DiT), 导致 17.5GB 量化 DiT 仍
    # 驻留 GPU; 叠加 HyperVAE 2x 解码(allocated 13.31GB) 峰值超 24GB 卡, 解码
    # 陷入 DynamicVRAM 换页泥潭 → vae.decode 停滞(实测 1h+ 无产物、前端断连)。
    # 现摘除除 VAE 外全部 LoadedModel(含量化 DiT; 安全: DynamicVRAM staged 权重
    # 在 RAM, forward 按需搬运, 不丢失) + GC + 双重清缓存, 给解码腾满显存;
    # 后续 clip 采样前插件驻留补丁会自动重载 DiT。
    try:
        import comfy.model_management as _mm
        import torch as _torch
        import gc as _gc_dv
        # v14.235/238: 修复解码前 DiT 卸载失效(2026-10-28 实机日志佐证:
        # popped=1 但 allocated=18.47GB free=0 -> clip 预览 VAE decode OOM,
        # 整段+tiled 重试均 OOM, allocated 23.35GiB requested 932MiB/1.7GiB)。
        # 根因1: free_memory(for_dynamic=True) 对 DynamicVRAM 量化 DiT 直接跳过
        #   (model_management.free_memory 里 is_dynamic and for_dynamic -> 不卸载);
        # 根因2: 手动 .to('cpu') 对 DynamicVRAM staged 权重无效(量化权重在自定义
        #   staged 容器, Module.to 不迁移) -> 权重纹丝不动;
        # 根因3(v14.238 实测复盘): partially_unload(offload_device,1e32) 只处理
        #   comfy_patched_weights 模块(comfy/model_patcher.py:1215), 对 DynamicVRAM
        #   vbar/pin 权重(delegate)无效 —— 卸载 0 字节, 仅 remove 注册表。
        # v14.238 修复: dynamic 量化模型走 ModelPatcherDynamic.unpatch_model 官方
        #   eject 路径(内部 = partially_unload(None,1e32)+partially_unload_ram+
        #   move_weight_functions); 卸载后一律摘除注册; 加 GC3 轮回收 delegate
        #   残留 + allocated>8GB 警告。严禁对非 dynamic 量化块 detach/unpatch/
        #   free_memory(不带 for_dynamic) 的 self.model.to(cpu) —— comfy_kitchen
        #   QuantizedTensor._handle_to 原生 access violation(round3 崩溃链)。
        #   VAE/audioVAE 条目按真实模型身份保留; 下 clip 采样前驻留补丁自动重载 DiT。
        _keep_entries = []
        for _entry in list(_mm.current_loaded_models):
            try:
                _p = _entry.model  # weakref property 解引用 -> ModelPatcher
                _real = getattr(_p, "model", None)
            except Exception:
                _real = None
            if _real is vae or _real is getattr(vae, "model", None) \
               or _real is audio_vae or _real is getattr(audio_vae, "model", None):
                _keep_entries.append(_entry)
        _keep_ids = {id(e) for e in _keep_entries}
        _popped = 0
        for _entry in list(_mm.current_loaded_models):
            if id(_entry) in _keep_ids:
                continue
            try:
                _m = _entry.model
                if _m is None:
                    _mm.current_loaded_models.remove(_entry)
                    _popped += 1
                    continue
                if _m.is_dynamic():
                    # v14.238 (2026-10-28): DynamicVRAM 模型(如 H3 量化 DiT)走官方
                    # eject 卸载 —— unpatch_model 的 ModelPatcherDynamic override 内部
                    # = partially_unload(None,1e32) + partially_unload_ram + 
                    # move_weight_functions, 是 ComfyUI 的完整卸载路径。此前用的
                    # partially_unload(offload_device) 只处理 comfy_patched_weights
                    # 模块, 对 DynamicVRAM vbar/pin 权重无效(实机日志: loaded_size
                    # 18.4GB 纹丝不动, 仅 remove 注册 -> decode OOM 复现)。
                    # 非 dynamic 量化块严禁 detach/unpatch(comfy_kitchen _handle_to
                    # 原生崩溃, round3 链, try/except 捕不住)。
                    try:
                        _m.unpatch_model(_m.offload_device, unpatch_weights=True)
                        _torch.cuda.synchronize()
                    except Exception as _ue:
                        print(f"[H3 Extender] v14.238 dynamic unpatch_model 回退 partially_unload: {_ue}")
                        try:
                            _m.partially_unload(_m.offload_device, 1e32)
                            _torch.cuda.synchronize()
                        except Exception:
                            pass
                    try:
                        _mm.current_loaded_models.remove(_entry)
                        _popped += 1
                    except Exception:
                        pass
                else:
                    _mm.current_loaded_models.remove(_entry)
                    _popped += 1
            except Exception:
                pass
        # v14.238: GC 3 轮回收 DynamicVRAM delegate/eject 残留(远端 v1.96 同款思路,
        # 实测 eject 后 delegate 权重 Python 引用残留可达 14.5GB 不释放), 再清缓存
        # 腾满显存给 VAE 解码。
        for _gc_round in range(3):
            _gc_dv.collect()
            _torch.cuda.empty_cache()
            _torch.cuda.synchronize()
        _mm.soft_empty_cache(force=True)
        _torch.cuda.synchronize()
        _a = _torch.cuda.memory_allocated() / 1024 ** 3
        _free = _torch.cuda.mem_get_info()[0] / 1024 ** 3
        print(f"[H3 Extender]   decode VRAM prepared (popped={_popped}, gc3x): allocated={_a:.2f}GB free={_free:.2f}GB")
        if _a > 8.0:
            print(f"[H3 Extender]   ⚠️ decode VRAM: allocated={_a:.1f}GB 偏高(dynamic 卸载残留), "
                  f"VAE decode 可能 OOM; 若崩溃需重启 ComfyUI")
    except Exception as _e:
        print(f"[H3 Extender]   decode VRAM cleanup skipped: {_e}")

    v = _load_segment_video(data_path, curr)
    print(f"[H3 Extender]   step 2: vae.decode (shape={tuple(v.shape)})...")
    # v1.82b: 覆盖 VAE output_device 到 GPU —— lowvram/dynamic 模式下 ComfyUI
    # intermediate_device() 会把整段 1920x1088 float32 视频直接输出到 CPU
    # (8.5GB/段), 渲染进程内存压力下 alloc_cpu OOM. 强制 GPU 输出, 配合下方
    # 分批 uint8 转换, 彻底消除 CPU 侧大分配. decode 为单线程调用, try/finally
    # 立即恢复原值, 不影响后续路径.
    _od_prev = getattr(vae, "output_device", None)
    _od_overridden = bool(
        _od_prev is not None
        and getattr(getattr(vae, "device", None), "type", None) == "cuda"
        and getattr(_od_prev, "type", None) != "cuda"
    )
    if _od_overridden:
        vae.output_device = vae.device
    try:
        # v14.232: 时间维分块 decode —— 整段 107 帧 decode_tiled_3d 预分配
        # 8.45GB output buffer, DiT 残留 17.58GB + 8.45GB 超 24GB OOM。
        # 切 16 latent 帧/块逐块 decode, 每块 output 仅 ~1.3GB, 峰值可控。
        # v14.236 (fix): v14.232 裸切 16 帧/块截断了块间时间上下文 —— H3 为
        # 视频 VAE, 独立小块丢失前后帧上下文, 块内出现亮度异常帧, 视觉即
        # "每 ~16 帧闪一下" + 8bit 编码 banding 细横条纹。修复: 每块沿 T 向
        # 两侧各扩展 _dec_ctx=8 帧上下文再 decode, 只取原块范围输出; 块间
        # 输出帧仍严格不重叠, 峰值仅 ~2.6GB/块, 保持 24GB 卡不 OOM。
        _dec_t_block = 16
        _dec_ctx = 8
        _dec_t_total = int(v.shape[2])
        if _dec_t_total > _dec_t_block:
            _dec_parts = []
            for _t0 in range(0, _dec_t_total, _dec_t_block):
                _t1 = min(_t0 + _dec_t_block, _dec_t_total)
                _s0 = max(0, _t0 - _dec_ctx)
                _s1 = min(_dec_t_total, _t1 + _dec_ctx)
                _vk = v[:, :, _s0:_s1].contiguous()
                _dec_k = vae.decode(_vk)
                if _dec_k.ndim == 5:
                    _dec_k = _dec_k.reshape(-1, _dec_k.shape[-3], _dec_k.shape[-2], _dec_k.shape[-1])
                # 只保留本块对应帧(裁掉上下文扩展段), 块间输出严格不重叠
                _lo = _t0 - _s0
                _hi = _t1 - _s0
                _dec_k = _dec_k[_lo:_hi]
                _dec_parts.append(_dec_k.detach().cpu())
                print(f"[H3 Extender]   decode block [{_t0}:{_t1}/{_dec_t_total}] "
                      f"(ctx=[{_s0}:{_s1}]) done")
                import gc as _gc_dec; _gc_dec.collect()
            video = torch.cat(_dec_parts, dim=0)
            del _dec_parts
        else:
            video = vae.decode(v)
    finally:
        if _od_overridden:
            vae.output_device = _od_prev
    if video.ndim == 5:
        video = video.reshape(-1, video.shape[-3], video.shape[-2], video.shape[-1])
    print(f"[H3 Extender]   step 2 done: video shape={tuple(video.shape)}")
    _t66_mark("VAE decode")

    # Trim leading context overlap (clip 2+)
    if trim > 0:
        video = video[trim:]
        print(f"[H3 Extender]   trimmed {trim} leading overlap frames -> {video.shape[0]} frames")

    # Decode audio
    print(f"[H3 Extender]   step 3: decoding audio (audio_vae={type(audio_vae).__name__ if audio_vae else 'None'})...")
    try:
        audio = _decode_single_audio(data_path, curr, audio_vae, fps)
    except Exception as _aud_err:
        print(f"[H3 Extender]   audio decode failed (non-fatal): {_aud_err}")
        audio = {"waveform": torch.zeros(1, 1, 1), "sample_rate": 32000}

    # Trim audio to match video
    if trim > 0 and audio.get("waveform") is not None:
        sr = int(audio["sample_rate"])
        trim_samples = int(round(float(trim) / float(fps) * sr))
        wave = audio["waveform"]
        if trim_samples < int(wave.shape[-1]):
            audio = dict(audio)
            audio["waveform"] = wave[..., trim_samples:]
            print(f"[H3 Extender]   trimmed {trim_samples} audio samples ({trim} frames @ {sr}Hz)")

    # v2.117f: lip_audio 模式时长对齐 — H3 时间网格把 12s 对齐到 294 帧(多 ~6 帧),
    # 而对口型歌曲段只有 11.98s(288 帧)。多出来的对齐帧被模型生成为延续画面,
    # 累积后每段都像"吃了上一段尾巴"。裁掉视频末尾的对齐帧, 让视频时长精确匹配歌曲段。
    if lip_audio_segment is not None and video.shape[0] > 0:
        try:
            _lip_wl = int(lip_audio_segment["waveform"].shape[-1])
            _lip_sr2 = int(lip_audio_segment["sample_rate"])
            _exp_frames = int(round(_lip_wl / float(_lip_sr2) * fps))
            _diff = int(video.shape[0] - _exp_frames)
            if 0 < _diff <= 12:
                video = video[:_exp_frames]
                out_frames = _exp_frames  # v2.117g: 同步给 MP4 编码用
                print(f"[H3 Extender]   lip_audio 时长对齐: 裁末尾 {_diff} 帧 -> {_exp_frames} 帧 "
                      f"(匹配歌曲段 {_lip_wl/float(_lip_sr2):.2f}s)")
                if audio.get("waveform") is not None:
                    _tail_samples = int(round(_diff / float(fps) * float(audio["sample_rate"])))
                    _aw = audio["waveform"]
                    if 0 < _tail_samples < int(_aw.shape[-1]):
                        audio = dict(audio)
                        audio["waveform"] = _aw[..., :-_tail_samples]
        except Exception as _te:
            print(f"[H3 Extender]   lip_audio 末尾对齐跳过: {_te}")

    # ── 对口型纯输出模式(v2.118 双重保险): 只输出 lip_audio 歌曲原音,
    # 完全丢弃模型生成的任何音频(环境音/呼吸/自生成音乐). 模型音频仅用于
    # 潜空间条件(驱动口型), 不出现在最终输出中.
    if lip_audio_segment is not None and audio.get("waveform") is not None:
        try:
            import torchaudio as _ta_mix
            _model_wave = audio["waveform"].float()
            _model_sr = int(audio["sample_rate"])
            _lip_wave = lip_audio_segment["waveform"].float()
            _lip_sr = int(lip_audio_segment["sample_rate"])
            # v14.154 (fix): 重叠切割必须在段原始采样率域执行 —— overlap_samples 由
            # _split_lip_audio_by_clips 按段原始 sr 计算并记入段 dict。旧顺序先重采样
            # 到 _model_sr 再按原 sr 的 _ov 切割: 44.1kHz 歌曲段在 32kHz 域切 88200
            # 样本 = 2.756s(应切 2.0s), clip2+ 输出音频整体晚 ~0.75s → 衔接处音频
            # 跳针 + 整段口型与音频错位。现在先在原 sr 域切重叠, 再重采样。
            _ov = int(lip_audio_segment.get("overlap_samples", 0))
            if _ov > 0 and int(_lip_wave.shape[-1]) > _ov:
                _lip_wave = _lip_wave[..., _ov:]
            # 统一到模型音频的采样率
            if _lip_sr != _model_sr:
                _lip_wave = _ta_mix.functional.resample(_lip_wave, _lip_sr, _model_sr)
            # 维度对齐 [B, C, L]
            if _lip_wave.ndim == 2:
                _lip_wave = _lip_wave.unsqueeze(0)
            if _model_wave.ndim == 2:
                _model_wave = _model_wave.unsqueeze(0)
            # 声道对齐
            if _lip_wave.shape[1] != _model_wave.shape[1]:
                if _lip_wave.shape[1] == 1 and _model_wave.shape[1] == 2:
                    _lip_wave = _lip_wave.repeat(1, 2, 1)
                elif _model_wave.shape[1] == 1 and _lip_wave.shape[1] == 2:
                    _model_wave = _model_wave.repeat(1, 2, 1)
            # 长度对齐到模型音频长度(歌曲段可能略长/略短)
            _target = int(_model_wave.shape[-1])
            if int(_lip_wave.shape[-1]) >= _target:
                _lip_aligned = _lip_wave[..., :_target]
            else:
                _pad = _target - int(_lip_wave.shape[-1])
                _lip_aligned = torch.cat([
                    _lip_wave,
                    torch.zeros(_lip_wave.shape[0], _lip_wave.shape[1], _pad,
                                dtype=_lip_wave.dtype, device=_lip_wave.device)
                ], dim=-1)
            # v2.118: 纯歌曲输出 — 不混入任何模型音频
            audio = dict(audio)
            audio["waveform"] = _lip_aligned
            print(f"[H3 LipSync]   clip[{i}] 纯歌曲输出(模型音频已丢弃): "
                  f"{int(_lip_aligned.shape[-1])} samples @ {_model_sr}Hz, "
                  f"跳过重叠 {_ov} samples")
        except Exception as _mix_err:
            print(f"[H3 LipSync]   clip[{i}] 纯歌曲输出失败(回退模型原音): {_mix_err}")

    # v1.70: encode 段拆为内部函数——统一预转 uint8 CPU 后编码(不再逐批 GPU->CPU
    # 拷贝); async_encode=True 时在后台线程执行(encode ~55s 与下一段 GPU 工作
    # 并行, 省 ~55s/段), 主线程立即继续; encode 只占 CPU pipe + NVENC, 与主
    # 线程 GPU 无显存冲突. 同步路径(安全回退)行为与 v1.69 完全一致.
    # v1.82: 高清档(1920x1088)整段 float32 转换峰值 8.5GB(340帧*1088*1920*3*4B),
    # 渲染进程内存压力下 OOM(alloc_cpu.cpp:117)。改为逐批 float->uint8:
    # GPU 输入在 GPU 上逐批算, 仅 uint8 分批拷 CPU; CPU 输入逐批转。
    # 每批峰值 <= _BS 帧 float32(= _BS*H*W*3*4B) + _BS 帧 uint8, 16帧约 0.6GB。
    _BS = 16
    _vid = video.detach()
    # v14.156: 二采倍率被显存预算降级时，解码像素小于声明最终尺寸；逐批
    # bicubic(antialias) 重采样到 output_width/height，失败回退 bilinear。
    _need_scale = bool(
        _tgt_w > 0 and _tgt_h > 0
        and (int(_vid.shape[2]) != _tgt_w or int(_vid.shape[1]) != _tgt_h)
    )
    if _need_scale:
        print(f"[H3 Extender]   输出重采样: {int(_vid.shape[2])}x{int(_vid.shape[1])} "
              f"-> {_tgt_w}x{_tgt_h} (bicubic, antialias)")
    _parts = []
    for _s in range(0, int(_vid.shape[0]), _BS):
        _chunk = _vid[_s:_s + _BS].float().clamp(0.0, 1.0)
        if _need_scale:
            _ct = _chunk.permute(0, 3, 1, 2)
            try:
                _ct = torch.nn.functional.interpolate(
                    _ct, size=(_tgt_h, _tgt_w), mode="bicubic", antialias=True)
            except Exception:
                _ct = torch.nn.functional.interpolate(
                    _ct, size=(_tgt_h, _tgt_w), mode="bilinear", antialias=True)
            _chunk = _ct.permute(0, 2, 3, 1)
        # v14.190: 去彩点(色度去斑) —— VAE 解码+重采样后可能出现单像素饱和彩点
        _chunk = _despeckle_frames(_chunk)
        _parts.append(
            _chunk.mul(255.0).add_(0.5).to(torch.uint8).cpu()
        )
    video_cpu = torch.cat(_parts, dim=0).contiguous()
    del _parts, _vid
    del video

    def _encode_and_store(video_u8, audio_in):
        # Encode to MP4 (video + audio)
        root = _ensure_cache_root()
        token = f"clipdec_{_safe_name(str(owner_id))}_{i}_{uuid.uuid4().hex[:8]}"
        temp_mp4 = root / f"_{token}.mp4"

        print(f"[H3 Extender]   step 4: encoding MP4 with audio (ffmpeg={ffmpeg}, temp={temp_mp4}, frames={out_frames})...")
        if ffmpeg is None:
            raise TypeError(f"ffmpeg is None — cannot encode preview. _find_ffmpeg() should have raised RuntimeError.")

        # Write raw PCM audio to a temp file for ffmpeg
        temp_wav = None
        has_audio = audio.get("waveform") is not None and int(audio["waveform"].shape[-1]) > 1
        if has_audio:
            try:
                sr = int(audio["sample_rate"])
                wave = audio["waveform"]
                # Ensure stereo
                if wave.ndim == 3:
                    wave = wave.squeeze(0)
                if wave.shape[0] == 1:
                    wave = wave.repeat(2, 1)
                # Convert float -> int16
                wav_np = (wave.detach().float().clamp(-1.0, 1.0) * 32767.0).to(torch.int16).cpu().numpy()
                import wave as _wave
                temp_wav = root / f"_{token}.wav"
                with _wave.open(str(temp_wav), "wb") as wf:
                    wf.setnchannels(2)
                    wf.setsampwidth(2)
                    wf.setframerate(sr)
                    wf.writeframes(wav_np.T.tobytes())
                print(f"[H3 Extender]   audio PCM ready: {temp_wav.name}, {wav_np.shape[1]} samples @ {sr}Hz")
            except Exception as _wav_err:
                print(f"[H3 Extender]   audio PCM write failed, falling back to video-only: {_wav_err}")
                has_audio = False
                if temp_wav and temp_wav.exists():
                    try:
                        temp_wav.unlink()
                    except Exception:
                        pass
                temp_wav = None

        # Encode video and mux audio in one pass
        h, w = int(video_u8.shape[1]), int(video_u8.shape[2])
        video_log = root / f"_{token}_video.log"
        proc = None
        log_f = None
        try:
            _enc_args = _h264_enc_args(ffmpeg, "veryfast", 15)
            _enc_name = "h264_nvenc" if "nvenc" in " ".join(_enc_args) else "libx264"
            print(f"[H3 Extender]   编码器: {_enc_name} @ {w}x{h}")
            cmd = [
                ffmpeg, "-y",
                "-f", "rawvideo",
                "-pix_fmt", "rgb24",
                "-s:v", f"{w}x{h}",
                "-r", f"{float(fps):.9f}",
                "-i", "pipe:0",
            ]
            if has_audio and temp_wav is not None:
                cmd += ["-i", str(temp_wav)]
                cmd += _enc_args
                cmd += ["-c:a", "aac", "-b:a", "192k"]
                cmd += ["-shortest"]
            else:
                cmd += ["-an"]
                cmd += _enc_args
            cmd += [str(temp_mp4)]

            log_f = open(video_log, "wb")
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log_f)
            _write_image_frames(proc, video_u8)
            _finish_process(proc, log_f, video_log, "H3 clip preview encoder")
            proc = None
            log_f = None
        finally:
            if proc is not None:
                try:
                    if proc.stdin is not None:
                        proc.stdin.close()
                except Exception:
                    pass
                try:
                    proc.kill()
                except Exception:
                    pass
            if log_f is not None:
                try:
                    log_f.close()
                except Exception:
                    pass
            try:
                if video_log.exists():
                    video_log.unlink()
            except OSError:
                pass
            if temp_wav and temp_wav.exists():
                try:
                    temp_wav.unlink()
                except Exception:
                    pass

        if not temp_mp4.exists():
            print(f"[H3 Extender]   step 4 failed: temp_mp4 does not exist after encode")
            return None
        print(f"[H3 Extender]   step 4 done: mp4 size={temp_mp4.stat().st_size}")
        _t66_mark("MP4 encode")

        # Read encoded MP4 and store as blob in the cache file
        # v14.156: 只追加、不截断。数据文件是 append-only 布局（每段 latent ->
        # blob -> decoded_audio），非尾段 truncate 会删除后续段的 latent；
        # 且任何追加之后，尾段 truncate 也会删掉这些新 blob。新段写入时
        # EOF 恰好等于 latent_end，追加与重写完全等价。
        latent_end = int(curr.get("latent_end", _latent_payload_end(curr)))
        _is_tail = (i == len(segments) - 1)
        with open(data_path, "ab", buffering=0) as f:
            f.seek(0, 2)
            render_spec = _write_blob_raw(f, temp_mp4)
            audio_spec = _write_tensor_raw(f, audio["waveform"])
            segment_end = int(f.tell())
            f.flush()
            os.fsync(f.fileno())

        # Clean up temp file
        try:
            temp_mp4.unlink()
        except Exception:
            pass

        # Update manifest
        curr["latent_end"] = latent_end
        curr["decoded_mp4_blob"] = render_spec
        curr["decoded_mp4_version"] = 6  # v14.236: v6 = 时间分块解码加块间上下文(修复 ~16 帧亮度闪烁)；v5 blob 不再复用，自动重编码
        curr["decoded_mp4_width"] = int(video_u8.shape[2])
        curr["decoded_mp4_height"] = int(video_u8.shape[1])
        curr["decoded_mp4_has_audio"] = has_audio
        curr["decoded_audio"] = {
            "waveform": audio_spec,
            "sample_rate": int(audio["sample_rate"]),
            "timeline_gain": 1.0,
        }
        if _is_tail:
            curr["segment_end"] = segment_end
        segments[i] = curr

        updated = dict(manifest)
        updated["segments"] = segments
        updated["build"] = BUILD
        updated["updated_at"] = time.time()
        _write_json_atomic(manifest_path, updated)
        return curr



    if async_encode:
        # v1.70: RAM 保护——encode 线程持有 video_cpu(0.7GB uint8), 系统内存
        # 严重不足(<1.5GB free)时回退同步编码, 避免与主线程/系统换页叠加.
        try:
            import psutil as _ps70
            _ram_free70 = _ps70.virtual_memory().available / 2**30
        except Exception:
            _ram_free70 = 99.0
        if _ram_free70 < 1.5:
            print(f'[H3 Extender]   encode async 跳过(RAM free={_ram_free70:.1f}GB < 1.5GB), 同步编码')
            return _encode_and_store(video_cpu, audio)
        import threading as _thr70
        _ev70 = _thr70.Event()

        def _run_async():
            try:
                _encode_and_store(video_cpu, audio)
            except Exception as _enc70:
                print(f"[H3 Extender]   async encode failed: {_enc70}")
                import traceback as _tb70
                _tb70.print_exc()
            finally:
                _ev70.set()

        _thr70.Thread(target=_run_async, daemon=True).start()
        print(f"[H3 Extender]   encode async: 后台线程已启动, 主线程继续下一段")
        return {"async": True, "done_event": _ev70}
    else:
        return _encode_and_store(video_cpu, audio)

def _encode_corrected_segment_video_mp4(
    ffmpeg,
    video,
    fps,
    target_path,
    token,
):
    """Encode one corrected preview segment as VIDEO ONLY.

    Keeping AAC out of the per-clip cache avoids both audio encoder priming and
    MP4 audio edit-list timestamps from ever participating in an internal join.
    The matching lossless PCM is stored separately inside .h3cache.
    """
    root = _ensure_cache_root()
    video_log = root / f"_{token}_video.log"
    proc = None
    log_f = None
    try:
        h, w = int(video.shape[1]), int(video.shape[2])
        proc, log_f = _start_video_encoder(
            ffmpeg,
            target_path,
            w,
            h,
            fps,
            "H.264",
            14,
            "fast",
            video_log,
        )
        _write_image_frames(proc, video)
        _finish_process(proc, log_f, video_log, "H3 progressive cache video encoder")
        proc = None
        log_f = None
    finally:
        if proc is not None:
            try:
                if proc.stdin is not None:
                    proc.stdin.close()
            except Exception:
                pass
            try:
                proc.kill()
            except Exception:
                pass
        if log_f is not None:
            try:
                log_f.close()
            except Exception:
                pass
        try:
            if video_log.exists():
                video_log.unlink()
        except OSError:
            pass


def _load_cached_decoded_audio(data_path, desc):
    meta = desc.get("decoded_audio")
    if not isinstance(meta, dict):
        return None
    spec = meta.get("waveform")
    if not isinstance(spec, dict):
        return None
    wave = _map_tensor(data_path, spec)
    if wave.ndim == 2:
        wave = wave.unsqueeze(0)
    if wave.ndim != 3 or int(wave.shape[0]) != 1:
        raise ValueError(
            f"H3 progressive preview: invalid cached decoded audio shape {tuple(wave.shape)}."
        )
    gain = float(meta.get("timeline_gain", 1.0))
    if not math.isfinite(gain) or gain <= 0.0:
        gain = 1.0
    if abs(gain - 1.0) > 1.0e-8:
        wave = wave * gain
    return {
        "waveform": wave,
        "sample_rate": int(meta.get("sample_rate", 32000)),
    }


def _decode_legacy_segment_mp4_audio(
    ffmpeg,
    data_path,
    desc,
    sample_rate,
    channels,
    token,
):
    """Compatibility path for v14.41-and-older decoded MP4 blobs.

    Old caches contain AAC only.  Decode that *individual* clip before fitting
    it to the exact frame-derived sample count.  This removes AAC priming at the
    internal seam instead of stream-copying it into the full preview.
    """
    blob = desc.get("decoded_mp4_blob")
    if blob is None:
        return None

    root = _ensure_cache_root()
    temp_mp4 = root / f"_{token}_legacy_audio.mp4"
    try:
        _copy_blob_to_file(data_path, blob, temp_mp4)
        cmd = [
            ffmpeg, "-v", "error",
            "-i", str(temp_mp4),
            "-map", "0:a:0",
            "-vn",
            "-f", "f32le",
            "-acodec", "pcm_f32le",
            "-ar", str(int(sample_rate)),
            "-ac", str(int(channels)),
            "pipe:1",
        ]
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode != 0:
            tail = p.stderr[-12000:].decode("utf-8", errors="replace")
            raise RuntimeError(
                f"H3 progressive preview legacy audio decode failed with "
                f"code {p.returncode}.\n{tail}"
            )
        raw = np.frombuffer(p.stdout, dtype=np.float32)
        if raw.size == 0 or raw.size % int(channels) != 0:
            raise RuntimeError("H3 progressive preview: invalid legacy PCM decode.")
        frames = raw.size // int(channels)
        arr = raw.reshape(frames, int(channels)).T.copy()
        return torch.from_numpy(arr).unsqueeze(0)
    finally:
        try:
            if temp_mp4.exists():
                temp_mp4.unlink()
        except OSError:
            pass


def _upgrade_cached_audio_gain_chain(
    data_path,
    manifest_path,
    manifest,
    audio_vae,
    fps,
):
    """Non-destructive v14.42 PCM migration to the v14.43 gain chain."""
    segments = [dict(x) for x in manifest.get("segments", [])]
    if not segments:
        return manifest

    changed = False
    first_meta = segments[0].get("decoded_audio")
    if isinstance(first_meta, dict) and "timeline_gain" not in first_meta:
        first_meta = dict(first_meta)
        first_meta["timeline_gain"] = 1.0
        segments[0]["decoded_audio"] = first_meta
        changed = True

    for i in range(1, len(segments)):
        meta = segments[i].get("decoded_audio")
        if not isinstance(meta, dict) or "timeline_gain" in meta:
            continue
        previous_cached = _load_cached_decoded_audio(data_path, segments[i - 1])
        if previous_cached is None:
            continue
        pair, prev_frames, _ = _decode_pair_audio(
            data_path, segments[i - 1], segments[i], audio_vae, fps, 0
        )
        sr = int(pair["sample_rate"])
        if sr != int(previous_cached["sample_rate"]):
            del pair
            continue
        prev_n = int(round(float(prev_frames) / float(fps) * sr))
        pair_previous = pair["waveform"][..., :prev_n]
        gain = _match_pair_gain_to_previous(
            previous_cached["waveform"], pair_previous, sr
        )
        meta = dict(meta)
        meta["timeline_gain"] = float(gain)
        segments[i]["decoded_audio"] = meta
        changed = True
        del pair, pair_previous

    if not changed:
        return manifest

    updated = dict(manifest)
    updated["segments"] = segments
    updated.pop("preview_audio_mode", None)
    updated["build"] = BUILD
    updated["updated_at"] = time.time()
    _write_json_atomic(manifest_path, updated)
    return updated


def _write_preview_pcm_audio(
    ffmpeg,
    data_path,
    segments,
    count,
    fps,
    raw_audio_path,
    token,
    audio_overrides=None,
):
    """Write exact timeline PCM for a progressive preview.

    Each clip contributes only its final corrected audio duration.  Segment
    boundaries are therefore sample-exact before ONE AAC encode is performed
    by _mux_final.  No AAC packet/padding is ever concatenated internally.
    """
    count = max(0, min(int(count), len(segments)))
    if count <= 0:
        raise ValueError("H3 progressive preview PCM builder has no segments.")
    audio_overrides = audio_overrides or {}

    sample_rate = None
    channels = None
    for i in range(count):
        override = audio_overrides.get(i)
        cached = override if override is not None else _load_cached_decoded_audio(data_path, segments[i])
        if cached is not None:
            sample_rate = int(cached["sample_rate"])
            wave = cached["waveform"]
            channels = int(wave.shape[1])
            break

    if sample_rate is None:
        # Native H3 audio output is 32 kHz stereo.  This branch exists only for
        # legacy caches where every decoded waveform predates v14.42.
        sample_rate = 32000
        channels = 2

    written_samples = 0
    cumulative_frames = 0
    previous_tail = None
    with open(raw_audio_path, "wb") as af:
        for i in range(count):
            desc = segments[i]
            audio = audio_overrides.get(i)
            if audio is None:
                audio = _load_cached_decoded_audio(data_path, desc)

            if audio is not None:
                sr = int(audio["sample_rate"])
                wave = audio["waveform"]
                if int(wave.shape[1]) != int(channels):
                    raise RuntimeError("H3 progressive preview: cached audio channel count changed.")
                if sr != int(sample_rate):
                    raise RuntimeError("H3 progressive preview: cached audio sample rate changed.")
            else:
                wave = _decode_legacy_segment_mp4_audio(
                    ffmpeg,
                    data_path,
                    desc,
                    sample_rate,
                    channels,
                    f"{token}_{i}",
                )
                if wave is None:
                    raise RuntimeError(
                        "H3 progressive preview: decoded audio cache is missing."
                    )

            if i > 0:
                wave = _smooth_segment_entry_level(previous_tail, wave, sample_rate)
                wave = _declick_segment(previous_tail, wave, sample_rate, 12.0)

            out_frames = int(desc["frames"])
            if i > 0:
                out_frames -= int(desc.get("trim_frames", 0))
            cumulative_frames += int(out_frames)
            target = int(round(float(cumulative_frames) / float(fps) * int(sample_rate)))
            wave = _fit_audio_segment_to_cumulative(
                wave, target, written_samples
            )
            _write_audio_raw(af, wave)
            written_samples += int(wave.shape[-1])
            previous_tail = _audio_seam_tail(wave, sample_rate)
            del wave

    return int(sample_rate), int(channels), int(written_samples)


def _concat_mp4_video_stream_copy(ffmpeg, inputs, output_path, log_path):
    """Concatenate only H.264 video packets; audio is rebuilt from PCM."""
    inputs = [Path(p) for p in inputs if p is not None and Path(p).exists()]
    if not inputs:
        raise ValueError("H3 progressive preview video concat has no input.")

    if len(inputs) == 1:
        if Path(output_path).resolve() != inputs[0].resolve():
            shutil.copy2(inputs[0], output_path)
        return

    list_path = Path(log_path).with_suffix(".concat.txt")
    try:
        lines = []
        for p in inputs:
            escaped = str(p.resolve()).replace("'", "'\\''")
            lines.append(f"file '{escaped}'")
        list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        cmd = [
            ffmpeg, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_path),
            "-map", "0:v:0",
            "-c:v", "copy",
            "-an",
            "-movflags", "+faststart",
            str(output_path),
        ]
        with open(log_path, "wb") as log_f:
            p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=log_f)
        if p.returncode != 0:
            tail = ""
            try:
                tail = Path(log_path).read_bytes()[-12000:].decode(
                    "utf-8", errors="replace"
                )
            except Exception:
                pass
            raise RuntimeError(
                f"H3 progressive preview video concat failed with code "
                f"{p.returncode}.\n{tail}"
            )
    finally:
        try:
            if list_path.exists():
                list_path.unlink()
        except OSError:
            pass


def _assemble_progressive_preview(
    ffmpeg,
    video_inputs,
    data_path,
    segments,
    count,
    fps,
    output_path,
    token,
    audio_overrides=None,
):
    """Assemble a full preview with video stream-copy + one AAC encode."""
    root = _ensure_cache_root()
    temp_video = root / f"_{token}_joined_video.mp4"
    raw_audio = root / f"_{token}_joined_audio.f32le"
    video_log = root / f"_{token}_video_concat.log"
    mux_log = root / f"_{token}_audio_mux.log"
    try:
        _concat_mp4_video_stream_copy(
            ffmpeg, video_inputs, temp_video, video_log
        )
        sr, channels, _ = _write_preview_pcm_audio(
            ffmpeg,
            data_path,
            segments,
            count,
            fps,
            raw_audio,
            token,
            audio_overrides=audio_overrides,
        )
        if Path(output_path).exists():
            Path(output_path).unlink()
        _mux_final(
            ffmpeg,
            temp_video,
            raw_audio,
            output_path,
            sr,
            channels,
            "H.264",
            "192k",
            mux_log,
        )
    finally:
        for p in (temp_video, raw_audio, video_log, mux_log):
            try:
                if Path(p).exists():
                    Path(p).unlink()
            except OSError:
                pass


def _render_one_final_segment(
    data_path,
    segments,
    index,
    vae,
    audio_vae,
    fps,
    progress=None,
):
    i = int(index)
    curr = segments[i]

    if i == 0:
        v = _load_segment_video(data_path, curr)
        video = vae.decode(v)
        if progress is not None:
            progress.advance()
        if video.ndim == 5:
            video = video.reshape(
                -1, video.shape[-3], video.shape[-2], video.shape[-1]
            )
        expected = int(curr["frames"])
        if int(video.shape[0]) != expected:
            raise RuntimeError(
                f"H3 progressive preview: clip 1 decoded {video.shape[0]}, "
                f"expected {expected}."
            )
        audio = _decode_single_audio(data_path, curr, audio_vae, fps)
        if progress is not None:
            progress.advance()
        return video, audio, 0

    prev = segments[i - 1]

    # trim=0 means the current clip is kept in full and directly follows the
    # previous one (no overlap to trim). Concatenating two H3 video latents
    # directly would break the 2-mod-5 temporal grid (the combined T is not
    # decodable by the VAE), so decode this segment standalone, same policy
    # as the first clip. Audio has no 2-mod-5 constraint and stays exact.
    if int(curr.get("trim_frames", 0)) == 0:
        v = _load_segment_video(data_path, curr)
        video = vae.decode(v)
        if progress is not None:
            progress.advance()
        if video.ndim == 5:
            video = video.reshape(
                -1, video.shape[-3], video.shape[-2], video.shape[-1]
            )
        expected = int(curr["frames"])
        if int(video.shape[0]) != expected:
            raise RuntimeError(
                f"H3 progressive preview: clip {i + 1} decoded {video.shape[0]}, "
                f"expected {expected}."
            )
        audio = _decode_single_audio(data_path, curr, audio_vae, fps)
        if progress is not None:
            progress.advance()
        return video, audio, 0

    chain, meta = _build_pair_video(data_path, prev, curr)
    decoded, previous_raw, current_raw, shift = _decode_pair_video(
        vae, chain, meta
    )
    if progress is not None:
        progress.advance()
    current_video = _correct_current_segment(previous_raw, current_raw)

    pair_audio, prev_frames, curr_frames = _decode_pair_audio(
        data_path,
        prev,
        curr,
        audio_vae,
        fps,
        int(shift),
    )
    if progress is not None:
        progress.advance()
    sr = int(pair_audio["sample_rate"])
    wave = pair_audio["waveform"]

    prev_samples = int(round(float(prev_frames) / float(fps) * sr))
    previous_audio = wave[..., :prev_samples]
    current_audio = wave[..., prev_samples:]

    previous_cached = _load_cached_decoded_audio(data_path, prev)
    if previous_cached is not None and int(previous_cached["sample_rate"]) == sr:
        gain = _match_pair_gain_to_previous(
            previous_cached["waveform"], previous_audio, sr
        )
        if abs(gain - 1.0) > 1.0e-8:
            current_audio = current_audio * gain

    # The click repair is deliberately deferred to full PCM assembly, where
    # the exact previous timeline tail is known.
    wanted = int(round(float(curr_frames) / float(fps) * sr))
    current_audio = _fit_audio_segment_to_cumulative(
        current_audio, wanted, 0
    )

    audio = {
        "waveform": current_audio,
        "sample_rate": sr,
    }

    del chain, decoded, previous_raw, current_raw, pair_audio, wave, previous_audio
    return current_video, audio, int(shift)


def _sync_committed_preview(
    data_path,
    manifest_path,
    manifest,
    target_count,
    vae,
    audio_vae,
    fps,
    ffmpeg,
    token,
):
    target = max(0, int(target_count))
    segments = [dict(x) for x in manifest.get("segments", [])]
    committed_path = _decoded_preview_cache_path(data_path)
    committed_video_path = _decoded_preview_video_cache_path(data_path)
    current_count = int(manifest.get("preview_committed_count", 0))
    current_audio_mode = str(manifest.get("preview_audio_mode", ""))

    if target <= 0:
        for p in (committed_path, committed_video_path):
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass
        updated = dict(manifest)
        updated["preview_committed_count"] = 0
        updated.pop("preview_audio_mode", None)
        updated["build"] = BUILD
        updated["updated_at"] = time.time()
        _write_json_atomic(manifest_path, updated)
        return updated, committed_path, committed_video_path

    # Both persistent files are needed: the normal muxed preview for immediate
    # display, and a video-only prefix so future candidates can be appended
    # without any AAC/edit-list timestamps taking part in the video join.
    if (
        current_count == target
        and current_audio_mode == PREVIEW_AUDIO_MODE
        and committed_path.exists()
        and committed_video_path.exists()
    ):
        # Guard: only fast-return when every committed segment has its
        # decoded caches (decoded_mp4_blob AND decoded_audio).  If any
        # segment is missing either one, the committed preview file may
        # be stale (e.g. after a per-clip replace + tail restore where
        # the count matches but content changed).
        cache_ok = True
        for i in range(current_count):
            seg = segments[i]
            has_blob = seg.get("decoded_mp4_blob") is not None
            has_audio = isinstance(seg.get("decoded_audio"), dict)
            if not has_blob or not has_audio:
                cache_ok = False
                break
        if cache_ok:
            return manifest, committed_path, committed_video_path

    rebuild = (
        current_audio_mode != PREVIEW_AUDIO_MODE
        or current_count <= 0
        or current_count > target
        or not committed_video_path.exists()
    )
    if not rebuild:
        for i in range(current_count):
            seg = segments[i]
            if not isinstance(seg.get("decoded_audio"), dict) and seg.get("decoded_mp4_blob") is None:
                rebuild = True
                break
    start_i = 0 if rebuild else current_count
    video_inputs = [] if rebuild else [committed_video_path]
    temp_segments = []
    audio_overrides = {}
    rendered_segments = {}
    root = _ensure_cache_root()
    joined_video_tmp = committed_video_path.with_name(
        committed_video_path.stem + f"_{token}.tmp.mp4"
    )
    committed_tmp = committed_path.with_name(
        committed_path.stem + f"_{token}.tmp.mp4"
    )
    raw_audio = root / f"_{token}_commit_audio.f32le"
    video_log = root / f"_{token}_commit_video.log"
    mux_log = root / f"_{token}_commit_mux.log"

    try:
        for i in range(start_i, target):
            desc = segments[i]
            segment_tmp = root / f"_{token}_commit_{i:04d}.mp4"
            blob = desc.get("decoded_mp4_blob")
            if blob is not None:
                _copy_blob_to_file(data_path, blob, segment_tmp)
            else:
                # Legacy/recovery path only. Keep constant-memory video decode
                # and retain the exact decoded PCM for the single final AAC pass.
                video, audio, _ = _render_one_final_segment(
                    data_path,
                    segments,
                    i,
                    vae,
                    audio_vae,
                    fps,
                )
                _encode_corrected_segment_video_mp4(
                    ffmpeg,
                    video,
                    fps,
                    segment_tmp,
                    f"{token}_bootstrap_{i}",
                )
                audio_overrides[i] = audio
                rendered_segments[i] = segment_tmp
                del video

            video_inputs.append(segment_tmp)
            temp_segments.append(segment_tmp)

        persist_indices = [
            i for i in sorted(rendered_segments)
            if not isinstance(segments[i].get("decoded_audio"), dict)
        ]
        if persist_indices:
            with open(data_path, "r+b", buffering=0) as f:
                f.seek(0, 2)
                for i in persist_indices:
                    blob_spec = _write_blob_raw(f, rendered_segments[i])
                    audio = audio_overrides[i]
                    wave = audio["waveform"]
                    if wave.ndim == 2:
                        wave = wave.unsqueeze(0)
                    if wave.ndim != 3 or int(wave.shape[0]) != 1:
                        raise ValueError(
                            f"H3 progressive preview: invalid override audio shape {tuple(wave.shape)}."
                        )
                    audio_spec = _write_tensor_raw(f, wave)
                    segments[i]["decoded_mp4_blob"] = blob_spec
                    segments[i]["decoded_audio"] = {
                        "waveform": audio_spec,
                        "sample_rate": int(audio["sample_rate"]),
                        "timeline_gain": 1.0,
                    }
                f.flush()
                os.fsync(f.fileno())

        _concat_mp4_video_stream_copy(
            ffmpeg,
            video_inputs,
            joined_video_tmp,
            video_log,
        )

        sr, channels, _ = _write_preview_pcm_audio(
            ffmpeg,
            data_path,
            segments,
            target,
            fps,
            raw_audio,
            f"{token}_commit_pcm",
            audio_overrides=audio_overrides,
        )
        _mux_final(
            ffmpeg,
            joined_video_tmp,
            raw_audio,
            committed_tmp,
            sr,
            channels,
            "H.264",
            "192k",
            mux_log,
        )

        os.replace(joined_video_tmp, committed_video_path)
        os.replace(committed_tmp, committed_path)
    finally:
        for p in temp_segments:
            try:
                if Path(p).exists():
                    Path(p).unlink()
            except OSError:
                pass
        for p in (joined_video_tmp, committed_tmp, raw_audio, video_log, mux_log):
            try:
                if Path(p).exists():
                    Path(p).unlink()
            except OSError:
                pass

    updated = dict(manifest)
    updated["segments"] = segments
    updated["preview_committed_count"] = target
    updated["preview_audio_mode"] = PREVIEW_AUDIO_MODE
    updated["build"] = BUILD
    updated["updated_at"] = time.time()
    _write_json_atomic(manifest_path, updated)
    return updated, committed_path, committed_video_path



def _export_live_candidate_preview(
    data_path,
    manifest_path,
    manifest,
    segments,
    vae,
    audio_vae,
    fps,
    ffmpeg,
    unique_id,
    progress=None,
):
    segments = [dict(x) for x in segments]
    if not segments:
        raise ValueError("H3 progressive preview: empty chain.")

    validated_count = _validated_prefix_count(segments)
    token = f"v125_{_safe_name(unique_id)}_{uuid.uuid4().hex[:8]}"
    preview_path = None
    root = _ensure_cache_root()

    # Upgrade v14.42 lossless cached PCM once. This changes only small gain
    # metadata in the manifest; latents and validation states stay untouched.
    manifest = _upgrade_cached_audio_gain_chain(
        data_path, manifest_path, manifest, audio_vae, fps
    )
    segments = [dict(x) for x in manifest.get("segments", [])]

    # Commit already validated clips into ONE persistent full preview cache.
    manifest, committed_path, committed_video_path = _sync_committed_preview(
        data_path,
        manifest_path,
        manifest,
        validated_count,
        vae,
        audio_vae,
        fps,
        ffmpeg,
        token,
    )
    segments = [dict(x) for x in manifest.get("segments", [])]

    # Everything currently present is validated: show cache directly.
    if validated_count >= len(segments):
        if not committed_path.exists():
            raise RuntimeError(
                "H3 progressive preview: validated preview cache is missing."
            )
        preview_path = _reserve_preview_temp_path(unique_id)
        try:
            os.link(committed_path, preview_path)
        except Exception:
            shutil.copy2(committed_path, preview_path)

        # Small compatibility output only: recover last frame from the last
        # segment. This does not affect the full preview cache itself.
        last_i = len(segments) - 1
        video, audio, shift = _render_one_final_segment(
            data_path,
            segments,
            last_i,
            vae,
            audio_vae,
            fps,
            progress=progress,
        )
        last_frame = video[-1:].detach().cpu().clone()
        del video, audio

        return (
            preview_path,
            last_frame,
            int(manifest.get("final_frame_count", 0)),
            int(shift),
            None,
            "committed_full_cache",
        )

    candidate_index = validated_count
    if candidate_index != len(segments) - 1:
        raise RuntimeError(
            "H3 progressive preview expects one unvalidated tail candidate."
        )

    # Normal VAE cost:
    #   clip 1 alone, otherwise ONLY previous + current pair.
    current_video, current_audio, seam_shift = _render_one_final_segment(
        data_path,
        segments,
        candidate_index,
        vae,
        audio_vae,
        fps,
        progress=progress,
    )

    candidate_mp4 = root / f"_{token}_candidate.mp4"

    try:
        _encode_corrected_segment_video_mp4(
            ffmpeg,
            current_video,
            fps,
            candidate_mp4,
            token,
        )

        # Save candidate's already decoded/corrected render in .h3cache.
        manifest, _ = _cache_candidate_render(
            data_path,
            manifest_path,
            manifest,
            candidate_index,
            candidate_mp4,
            current_audio,
        )

        preview_path = _reserve_preview_temp_path(unique_id)

        # FULL VIDEO preview: stream-copy only the H.264 video.  Audio is
        # rebuilt from lossless per-clip PCM and encoded ONCE for the complete
        # preview, so AAC priming/padding can never sit on an internal seam.
        video_inputs = (
            [committed_video_path, candidate_mp4]
            if committed_video_path.exists() and validated_count > 0
            else [candidate_mp4]
        )
        segments = [dict(x) for x in manifest.get("segments", [])]
        _assemble_progressive_preview(
            ffmpeg,
            video_inputs,
            data_path,
            segments,
            len(segments),
            fps,
            preview_path,
            f"{token}_candidate_full",
        )

        last_frame = current_video[-1:].detach().cpu().clone()
        total_frames = int(manifest.get("final_frame_count", 0))

        _LOG.info(
            "H3 v12.5 FULL preview: cached validated clips=%d, candidate=%d, "
            "shift=%d; VAE decoded only %s",
            validated_count,
            candidate_index + 1,
            int(seam_shift),
            (
                "clip 1"
                if candidate_index == 0
                else f"pair {candidate_index}->{candidate_index + 1}"
            ),
        )

        return (
            preview_path,
            last_frame,
            total_frames,
            int(seam_shift),
            None if candidate_index == 0 else int(candidate_index),
            "full_cached_prefix_plus_candidate",
        )

    finally:
        for p in (candidate_mp4,):
            try:
                if Path(p).exists():
                    Path(p).unlink()
            except Exception:
                pass



def _restore_cached_preview_without_decode(owner_id, final_id):
    """
    Rebuild the current full preview using ONLY already cached decoded MP4 blobs.

    This is used when ComfyUI starts and the workflow is restored. No sampler,
    video VAE or audio VAE is executed. The cache owner is derived from the
    upstream MiniMax H3 Extender node id.
    """
    owner = _safe_name(owner_id)
    final = _safe_name(final_id)

    data_path, manifest_path = _chain_paths(f"extender_{owner}")
    if not data_path.exists() or not manifest_path.exists():
        return None

    manifest = _load_manifest_from_paths(data_path, manifest_path)
    if manifest is None:
        return None

    segments = [dict(x) for x in manifest.get("segments", [])]
    if not segments:
        return None

    preview_path = None
    committed_path = _decoded_preview_cache_path(data_path)
    committed_video_path = _decoded_preview_video_cache_path(data_path)
    committed_count = int(manifest.get("preview_committed_count", 0))

    # Fastest path: the persistent committed preview already contains every
    # cached clip. Just republish it to ComfyUI temp for /view.
    if (
        committed_count >= len(segments)
        and committed_path.exists()
        and str(manifest.get("preview_audio_mode", "")) == PREVIEW_AUDIO_MODE
    ):
        preview_path = _reserve_preview_temp_path(final_id)
        try:
            os.link(committed_path, preview_path)
        except Exception:
            shutil.copy2(committed_path, preview_path)

        return {
            "path": preview_path,
            "clip_count": int(len(segments)),
            "frame_count": int(manifest.get("final_frame_count", 0)),
            "fps": float(manifest.get("fps", FPS)),
            "cache_mode": "committed_preview",
        }

    # Otherwise rebuild the full current preview from the per-clip decoded video
    # blobs plus cached PCM already stored inside .h3cache. Video is stream-copied
    # and audio gets one cheap AAC encode; no VAE/sampler runs on application load.
    # It remains available even if the last clip was only a candidate when the
    # application was closed.
    root = _ensure_cache_root()
    token = f"restore_{final}_{uuid.uuid4().hex[:8]}"
    segment_files = []
    temp_preview = root / f"_{token}.mp4"

    try:
        video_inputs = []
        start_i = 0
        if (
            committed_count > 0
            and committed_count < len(segments)
            and committed_video_path.exists()
        ):
            video_inputs.append(committed_video_path)
            start_i = committed_count

        for i in range(start_i, len(segments)):
            desc = segments[i]
            blob = desc.get("decoded_mp4_blob")
            if blob is None:
                # Old cache created before decoded candidate blobs existed:
                # restoring it would require a VAE decode, which must never
                # happen automatically just by opening ComfyUI.
                return None

            segment_path = root / f"_{token}_{i:04d}.mp4"
            _copy_blob_to_file(data_path, blob, segment_path)
            segment_files.append(segment_path)
            video_inputs.append(segment_path)

        ffmpeg = _find_ffmpeg()
        _assemble_progressive_preview(
            ffmpeg,
            video_inputs,
            data_path,
            segments,
            len(segments),
            float(manifest.get("fps", FPS)),
            temp_preview,
            token,
        )

        preview_path = _reserve_preview_temp_path(final_id)
        os.replace(temp_preview, preview_path)

        return {
            "path": preview_path,
            "clip_count": int(len(segments)),
            "frame_count": int(manifest.get("final_frame_count", 0)),
            "fps": float(manifest.get("fps", FPS)),
            "cache_mode": "decoded_blobs",
        }
    finally:
        for tmp in segment_files:
            try:
                if Path(tmp).exists():
                    Path(tmp).unlink()
            except OSError:
                pass
        for tmp in (temp_preview,):
            try:
                if Path(tmp).exists():
                    Path(tmp).unlink()
            except OSError:
                pass


if web is not None and PromptServer is not None and getattr(PromptServer, "instance", None) is not None:
    @PromptServer.instance.routes.get("/h3_extender/color_editor_info")
    async def h3_extender_color_editor_info(request):
        owner_id = request.query.get("owner_id", "")
        final_id = request.query.get("final_id", "")
        clip_index = request.query.get("clip_index", "")
        if not owner_id or not final_id or clip_index == "":
            return web.json_response({"ok": False, "error": "Missing owner/final/clip id."}, status=400)
        try:
            idx = int(clip_index)
            data_path, manifest_path = _chain_paths(f"extender_{_safe_name(owner_id)}")
            manifest = _load_manifest_from_paths(data_path, manifest_path)
            if manifest is None:
                return web.json_response({"ok": False, "error": "No cached H3 sequence found."}, status=404)
            segments = [dict(x) for x in manifest.get("segments", [])]
            if idx < 0 or idx >= len(segments):
                return web.json_response({"ok": False, "error": "This clip has not been rendered yet."}, status=400)
            preview_path = _latest_preview_temp_path(final_id)
            if preview_path is None or not preview_path.exists():
                return web.json_response({
                    "ok": False,
                    "error": "No decoded preview is available yet. Run Final Decode/Preview once first.",
                }, status=404)
            timeline = _color_timeline(segments, float(manifest.get("fps", FPS)))
            return web.json_response({
                "ok": True,
                "video": _comfy_media_item(preview_path, float(manifest.get("fps", FPS)), "temp"),
                "timeline": timeline,
                "clip_index": idx,
                "total_clips": len(segments),
            })
        except Exception as exc:
            _LOG.exception("H3 color editor info failed")
            return web.json_response({"ok": False, "error": str(exc)}, status=500)

    @PromptServer.instance.routes.post("/h3_extender/color_adjust")
    async def h3_extender_color_adjust(request):
        try:
            body = await request.json()
            owner_id = str(body.get("owner_id") or "")
            idx = int(body.get("clip_index"))
            if not owner_id:
                return web.json_response({"ok": False, "error": "Missing owner id."}, status=400)
            data_path, manifest_path = _chain_paths(f"extender_{_safe_name(owner_id)}")
            manifest = _load_manifest_from_paths(data_path, manifest_path)
            if manifest is None:
                return web.json_response({"ok": False, "error": "No cached H3 sequence found."}, status=404)
            segments = [dict(x) for x in manifest.get("segments", [])]
            if idx < 0 or idx >= len(segments):
                return web.json_response({"ok": False, "error": "This clip has not been rendered yet."}, status=400)
            adjustment = _normalize_color_adjustment(body.get("adjustment"))
            desc = dict(segments[idx])
            desc["color_adjustment"] = adjustment
            segments[idx] = desc
            manifest = dict(manifest)
            manifest["segments"] = segments
            manifest["updated_at"] = time.time()
            _write_json_atomic(manifest_path, manifest)
            timeline = _color_timeline(segments, float(manifest.get("fps", FPS)))
            return web.json_response({
                "ok": True,
                "adjustment": adjustment,
                "modified": not _color_is_neutral(adjustment),
                "timeline": timeline,
            })
        except Exception as exc:
            _LOG.exception("H3 color adjustment failed")
            return web.json_response({"ok": False, "error": str(exc)}, status=500)

    @PromptServer.instance.routes.post("/h3_extender/save_preview")
    async def h3_extender_save_preview(request):
        """Save only the currently assembled Final Decode preview to output."""
        try:
            body = await request.json()
            owner_id = str(body.get("owner_id") or "").strip()
            filename = str(body.get("filename") or "").strip()
            media_type = str(body.get("type") or "temp").strip()
            subfolder = str(body.get("subfolder") or "").strip()

            if media_type != "temp" or subfolder not in ("", "."):
                return web.json_response(
                    {"ok": False, "error": "Save Preview only accepts the Extender temp preview."},
                    status=400,
                )
            if Path(filename).name != filename or not re.fullmatch(
                r"h3_motion_preview_[A-Za-z0-9._-]+_[0-2]\.mp4", filename
            ):
                return web.json_response(
                    {"ok": False, "error": "Invalid H3 preview filename."}, status=400
                )

            source = (_preview_temp_root() / filename).resolve()
            if source.parent != _preview_temp_root().resolve():
                return web.json_response(
                    {"ok": False, "error": "Invalid H3 preview path."}, status=400
                )
            if not source.exists():
                return web.json_response(
                    {"ok": False, "error": "The currently displayed preview no longer exists."},
                    status=404,
                )

            workflow = body.get("workflow")
            prompt = body.get("prompt")
            color_timeline = None
            if owner_id:
                try:
                    data_path, manifest_path = _chain_paths(f"extender_{_safe_name(owner_id)}")
                    manifest = _load_manifest_from_paths(data_path, manifest_path)
                    if manifest is not None:
                        color_timeline = _color_timeline(
                            manifest.get("segments", []), float(manifest.get("fps", FPS))
                        )
                except Exception:
                    color_timeline = None
            output = await asyncio.to_thread(
                _save_preview_with_metadata,
                source,
                workflow,
                prompt,
                color_timeline,
            )
            return web.json_response({
                "ok": True,
                "video": _comfy_media_item(output, float(body.get("fps") or FPS), "output"),
                "filename": output.name,
            })
        except Exception as exc:
            _LOG.exception("H3 Save Preview failed")
            return web.json_response({"ok": False, "error": str(exc)}, status=500)

    @PromptServer.instance.routes.get("/h3_extender/cache_state")
    async def h3_extender_cache_state(request):
        """Restore Extender card cache/validation UI state without execution."""
        owner_id = request.query.get("owner_id", "")
        if not owner_id:
            return web.json_response({"found": False, "reason": "missing_id"})

        try:
            data_path, manifest_path = _chain_paths(
                f"extender_{_safe_name(owner_id)}"
            )
            if not data_path.exists() or not manifest_path.exists():
                return web.json_response({"found": False})

            manifest = _load_manifest_from_paths(data_path, manifest_path)
            if manifest is None:
                return web.json_response({"found": False})

            segments = [dict(x) for x in manifest.get("segments", [])]
            validated_count = _validated_prefix_count(segments)
            geometry = manifest.get("geometry") if isinstance(manifest.get("geometry"), dict) else {}
            resolved_width = int(geometry.get("video_w", 0) or 0) * 16
            resolved_height = int(geometry.get("video_h", 0) or 0) * 16
            return web.json_response({
                "found": True,
                "cached_count": int(len(segments)),
                "validated_count": int(validated_count),
                "frame_count": int(manifest.get("final_frame_count", 0)),
                "resolved_width": int(resolved_width),
                "resolved_height": int(resolved_height),
                # v1.100: 返回持久化的资产链接信息, 前端刷新后无需重新输入全局提示词
                "global_prompt": str(manifest.get("global_prompt") or ""),
                "clip_asset_paths": manifest.get("clip_asset_paths") or [],
                "global_asset_paths": manifest.get("global_asset_paths") or [],
            })
        except Exception as exc:
            _LOG.warning("H3 restore Extender cache state failed: %s", exc)
            return web.json_response({
                "found": False,
                "reason": "restore_failed",
            })

    @PromptServer.instance.routes.get("/h3_extender/restored_preview")
    async def h3_extender_restored_preview(request):
        """
        Frontend startup helper. It exposes only the deterministic cache belonging
        to an Extender node id; it never accepts an arbitrary filesystem path.
        """
        owner_id = request.query.get("owner_id", "")
        final_id = request.query.get("final_id", "")
        if not owner_id or not final_id:
            return web.json_response({"found": False, "reason": "missing_id"})

        try:
            restored = _restore_cached_preview_without_decode(owner_id, final_id)
            if restored is None:
                return web.json_response({"found": False})

            item = _comfy_media_item(
                restored["path"],
                restored["fps"],
                "temp",
            )
            data_path, manifest_path = _chain_paths(
                f"extender_{_safe_name(owner_id)}"
            )
            manifest = _load_manifest_from_paths(data_path, manifest_path)
            color_timeline = _color_timeline(
                manifest.get("segments", []) if manifest else [],
                float(manifest.get("fps", FPS)) if manifest else FPS,
            )
            return web.json_response({
                "found": True,
                "video": item,
                "clip_count": restored["clip_count"],
                "frame_count": restored["frame_count"],
                "cache_mode": restored["cache_mode"],
                "color_timeline": color_timeline,
            })
        except Exception as exc:
            _LOG.warning("H3 restore preview on load failed: %s", exc)
            return web.json_response({
                "found": False,
                "reason": "restore_failed",
            })

    @PromptServer.instance.routes.post("/h3_extender/clear_preview")
    async def h3_extender_clear_preview(request):
        """
        Delete all cached preview files (temp rotation slots, committed
        preview cache, and manifest segments) for a given Extender owner and
        Final Decode node. Called when the user clears the external prompt
        source so that a page refresh does not restore a stale preview.
        """
        body = await request.json()
        owner_id = str(body.get("owner_id", ""))
        final_id = str(body.get("final_id", ""))
        if not owner_id or not final_id:
            return web.json_response({"ok": False, "error": "missing_id"})

        try:
            # 1. Delete temp directory preview files for final_id
            for slot in range(int(PREVIEW_ROTATION_SLOTS)):
                p = _preview_temp_path(final_id, slot)
                try:
                    if p.exists():
                        p.unlink()
                except OSError:
                    pass
            legacy = _preview_temp_legacy_path(final_id)
            try:
                if legacy.exists():
                    legacy.unlink()
            except OSError:
                pass

            # 2. Delete committed preview cache files and reset manifest
            data_path, manifest_path = _chain_paths(
                f"extender_{_safe_name(owner_id)}"
            )
            for p in (
                _decoded_preview_cache_path(data_path),
                _decoded_preview_video_cache_path(data_path),
            ):
                try:
                    if p.exists():
                        p.unlink()
                except OSError:
                    pass

            if manifest_path.exists():
                manifest = _load_manifest_from_paths(data_path, manifest_path)
                if manifest is not None:
                    manifest["segments"] = []
                    manifest["final_frame_count"] = 0
                    manifest["geometry"] = None
                    manifest["preview_committed_count"] = 0
                    manifest.pop("preview_audio_mode", None)
                    manifest["build"] = BUILD
                    manifest["updated_at"] = time.time()
                    _write_json_atomic(manifest_path, manifest)

                    _ensure_data_file(data_path)
                    with open(data_path, "r+b") as f:
                        f.truncate(_DATA_START)
                        f.flush()
                        os.fsync(f.fileno())

            return web.json_response({"ok": True})
        except Exception as exc:
            _LOG.warning("H3 clear preview failed: %s", exc)
            return web.json_response({"ok": False, "error": str(exc)})

    @PromptServer.instance.routes.get("/h3_extender/clip_preview")
    async def h3_extender_clip_preview(request):
        """Return a playable MP4 for a single cached clip's decoded video blob."""
        owner_id = request.query.get("owner_id", "")
        clip_index = request.query.get("clip_index", "")
        if not owner_id or clip_index == "":
            return web.json_response({"ok": False, "error": "Missing owner_id or clip_index."}, status=400)
        try:
            # v2.69 fix: 前端 fetchClipPreview 传入的是 1-based clip_index
            # (extender.js: idxOneBased = clipIndex + 1)，但 manifest segments 数组
            # 是 0-based。此前直接 segments[idx] 导致每个卡片的预览整体错位一位：
            # CLIP1 读到 segments[1](clip2 的 blob)、CLIP2 越界走磁盘 fallback，
            # 用户看到 "Clip1/Clip2 预览都是 clip2 视频"。这里统一 -1 转 0-based；
            # clip_index=0(非法) 会得到 -1 并被下方边界检查拦截(返回 400)。
            idx = int(clip_index) - 1
            data_path, manifest_path = _chain_paths(f"extender_{_safe_name(owner_id)}")
            manifest = _load_manifest_from_paths(data_path, manifest_path)
            if manifest is None:
                return web.json_response({"ok": False, "error": "No cached H3 sequence found."}, status=404)
            segments = [dict(x) for x in manifest.get("segments", [])]
            if idx < 0 or idx >= len(segments):
                return web.json_response({"ok": False, "error": "This clip has not been rendered yet."}, status=400)
            blob = segments[idx].get("decoded_mp4_blob")
            if blob is None:
                return web.json_response({"ok": False, "error": "Clip has no decoded video yet."}, status=404)
            fps = float(manifest.get("fps", FPS))
            if folder_paths is not None:
                temp_dir = _comfyui_temp_dir()
            else:
                temp_dir = _ensure_cache_root()
            temp_dir.mkdir(parents=True, exist_ok=True)
            token = f"clippv_{_safe_name(owner_id)}_{idx}_{uuid.uuid4().hex[:8]}"
            temp_mp4 = temp_dir / f"_{token}.mp4"
            _copy_blob_to_file(data_path, blob, temp_mp4)
            item = _comfy_media_item(temp_mp4, fps, "temp")
            return web.json_response({
                "ok": True,
                "video": item,
                "clip_index": idx,
                "fps": fps,
                "total_clips": len(segments),
            })
        except Exception as exc:
            _LOG.exception("H3 clip preview failed")
            return web.json_response({"ok": False, "error": str(exc)}, status=500)

    @PromptServer.instance.routes.get("/h3_extender/clip_preview/file")
    async def h3_extender_clip_preview_file(request):
        """v1.84: 插件自服务预览 MP4, 绕开 ComfyUI /view?type=temp 的
        folder_paths.get_temp_directory() 解析不一致 (4090 的 temp 被其它插件
        set_temp_directory() 改到系统 Temp 后, /view 读不到 ComfyUI\temp 里的
        文件 → 404 无法播放). 本路由直接从 _comfyui_temp_dir() 读, 写读同源."""
        name = str(request.query.get("name", "")).strip()
        if not name or not _SAFE_NAME_RE.fullmatch(name):
            return web.Response(status=400, text="Invalid preview file name")
        path = _comfyui_temp_dir() / name
        if not path.exists() or not path.is_file():
            # v1.85: 文件缺失(重启清空 temp/外部清理)时, 从链 manifest blob 重建,
            # 任何机器重启后预览自动恢复. 文件名格式: _clippv_{owner}_{idx}_{hex}.mp4
            _m85 = re.match(r"^_clippv_([A-Za-z0-9_\-]+)_(\d+)_[A-Fa-f0-9]+\.mp4$", name)
            if _m85:
                _o85, _i85 = _m85.group(1), int(_m85.group(2))
                try:
                    _dp85, _mp85 = _chain_paths(f"extender_{_safe_name(_o85)}")
                    _mf85 = _load_manifest_from_paths(_dp85, _mp85)
                    _segs85 = [dict(x) for x in _mf85.get("segments", [])] if _mf85 else []
                    if 0 <= _i85 < len(_segs85):
                        _blob85 = _segs85[_i85].get("decoded_mp4_blob")
                        if _blob85:
                            path.parent.mkdir(parents=True, exist_ok=True)
                            _copy_blob_to_file(_dp85, _blob85, path)
                except Exception as _e85:
                    _LOG.warning("H3 preview rebuild failed for %s: %s", name, _e85)
        if not path.exists() or not path.is_file():
            return web.Response(status=404, text="Preview file not found")
        return web.FileResponse(
            path,
            headers={
                "Content-Type": "video/mp4",
                "Cache-Control": "no-store",
            },
        )

    @PromptServer.instance.routes.get("/h3_extender/rendered_clips")
    async def h3_extender_rendered_clips(request):
        """v2.61: 扫描 ComfyUI/output/bsai_clips/ 列出该 owner 真正渲染过的
        clip_index, 让前端恢复缓存后立刻知道哪些 CLIP 该出预览.

        manifest segments 数组为空时(典型场景是缓存文件损坏/丢失), bsai_clips/
        里的 h3_clip_<owner>_<idx>_<ts>.mp4 仍是真凭实据. 该路由扫描这些 mp4
        把 idx 去重, 时间戳最大的视为最新."""
        owner = str(request.query.get("owner_id") or "").strip()
        if not owner or not re.fullmatch(r"\d+", owner):
            return web.json_response({"ok": False, "error": "invalid owner_id"}, status=400)
        try:
            _root = Path(__file__).resolve().parents[2]
            clips_dir = _root / "output" / "bsai_clips"
        except Exception as e:
            return web.json_response({"ok": False, "error": f"resolve failed: {e}"})
        if not clips_dir.exists():
            return web.json_response({"ok": True, "rendered": [], "latest_ts_by_idx": {}})
        by_idx = {}
        pattern = f"h3_clip_{owner}_"
        for p in clips_dir.glob(f"{pattern}*.mp4"):
            stem = p.stem  # h3_clip_250_1_<ts>
            parts = stem.split("_")
            # parts[0]='h3', parts[1]='clip', parts[2]='250', parts[3]=idx, parts[4]=ts
            if len(parts) < 5:
                continue
            try:
                idx = int(parts[3])
                ts = int(parts[4])
            except Exception:
                continue
            prev = by_idx.get(idx)
            if prev is None or ts > prev[1]:
                by_idx[idx] = (p.name, ts)
        rendered = sorted(by_idx.keys())
        latest_ts_by_idx = {str(idx): by_idx[idx][1] for idx in rendered}
        latest_filename_by_idx = {str(idx): by_idx[idx][0] for idx in rendered}
        return web.json_response({
            "ok": True,
            "rendered": rendered,
            "latest_ts_by_idx": latest_ts_by_idx,
            "latest_filename_by_idx": latest_filename_by_idx,
        })


class MiniMaxH3MotionContextDiskFinalDecode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "cache": (CACHE_TYPE,),
                "vae": ("VAE",),
                "audio_vae": ("VAE",),
                "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 240.0, "step": 0.001}),
                "filename_prefix": ("STRING", {"default": "MiniMax_H3_cached"}),
                "output_directory": ("STRING", {"default": ""}),
                "codec": (["H.264", "H.265 / HEVC", "FFV1 lossless"], {"default": "H.264"}),
                "crf": ("INT", {"default": 17, "min": 0, "max": 51, "step": 1}),
                "preset": (["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"], {"default": "fast"}),
                "audio_bitrate": (["128k", "192k", "256k", "320k"], {"default": "192k"}),
                "export_clips": (
                    "STRING",
                    {
                        "default": "all",
                        "tooltip": "CLIP numbers to export (1-based). all = export all and merge; 2 = only the 2nd; 2,3 = 2nd and 3rd; 2-5 = 2nd through 5th. When not all, per-segment MP4s are exported for the selected range.",
                    },
                ),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ()
    RETURN_NAMES = ()
    FUNCTION = "export"
    CATEGORY = "BSAI/H3 Film Factory"
    OUTPUT_NODE = True

    def export(
        self,
        cache,
        vae,
        audio_vae,
        fps,
        filename_prefix,
        output_directory,
        codec,
        crf,
        preset,
        audio_bitrate,
        export_clips="all",
        unique_id=None,
    ):
        print(f"[H3 Final Decode] export() CALLED: nonce={cache.get('exec_nonce','N/A') if isinstance(cache, dict) else 'N/A'}")
        data_path, manifest_path, manifest = _load_manifest(cache)
        print(f"[H3 Final Decode] manifest loaded: {manifest_path} segments={len(manifest.get('segments',[]))} updated_at={manifest.get('updated_at','N/A')}")
        if abs(float(manifest["fps"]) - float(fps)) > 1e-6:
            raise ValueError(
                f"Disk Final Decode fps is {manifest['fps']}, export requested {fps}."
            )
        segments = [dict(x) for x in manifest.get("segments", [])]
        if not segments:
            raise ValueError("Disk Final Decode: empty cache.")

        # ── Validate all unvalidated segments upfront ────────────────
        # The Extender renders clips with validated=False in clip_by_clip
        # mode.  Before any export path (progressive preview, full batch,
        # or selective), ensure every segment is marked validated so the
        # downstream code can take the "all committed" fast path and does
        # not trip the "expects one unvalidated tail candidate" guard.
        unvalidated = [i for i, s in enumerate(segments)
                       if not bool(s.get("validated", False))]
        if unvalidated:
            for i in unvalidated:
                segments[i]["validated"] = True
            manifest = dict(manifest)
            manifest["segments"] = segments
            manifest["build"] = BUILD
            manifest["updated_at"] = time.time()
            _write_json_atomic(manifest_path, manifest)
            _LOG.info(
                "H3 Final Decode: validated %d pending segment(s) before export.",
                len(unvalidated),
            )

        color_timeline = _color_timeline(segments, float(fps))

        ffmpeg = _find_ffmpeg()

        if folder_paths is not None:
            default_out = Path(folder_paths.get_output_directory()).resolve()
        else:
            default_out = (Path.cwd() / "output").resolve()
        # Security: confine the FinalDecode output_directory widget to the
        # ComfyUI output directory. Absolute paths and '..' escapes outside it
        # are rejected (fall back to the default output dir).
        out_dir = default_out
        custom_out = str(output_directory or "").strip()
        if custom_out:
            cand = Path(custom_out).expanduser().resolve()
            try:
                if os.path.commonpath([str(default_out), str(cand)]) == str(default_out):
                    out_dir = cand
                else:
                    _LOG.warning(
                        "H3 Final Decode: output_directory %r escapes the output dir; "
                        "falling back to %s",
                        custom_out, default_out,
                    )
            except Exception:
                _LOG.warning(
                    "H3 Final Decode: output_directory %r invalid; falling back to %s",
                    custom_out, default_out,
                )
        out_dir.mkdir(parents=True, exist_ok=True)

        # ── Selective clip export ─────────────────────────────────────
        # When export_clips specifies particular clips, decode and export
        # only those clips as individual MP4s instead of the full merge.
        export_set = _parse_export_clips(export_clips, len(segments))
        if export_set is not None:
            progress = _FinalDecodeNativeProgress(unique_id, total=len(export_set) * 2)
            output_ui_videos = []
            for ci in sorted(export_set):
                if ci >= len(segments):
                    continue
                seg = segments[ci]
                _LOG.info("H3 selective export: clip %d/%d", ci + 1, len(segments))

                video, audio, _ = _render_one_final_segment(
                    data_path, segments, ci, vae, audio_vae, float(fps),
                    progress=progress,
                )

                ext = "mkv" if str(codec) == "FFV1 lossless" else "mp4"
                clip_path = out_dir / f"{_safe_name(filename_prefix)}_clip{ci + 1:02d}.{ext}"
                h, w = int(video.shape[1]), int(video.shape[2])
                temp_root = _ensure_cache_root()
                video_log = temp_root / f"_sel_export_{ci}_{uuid.uuid4().hex[:8]}.log"
                mux_log = temp_root / f"_sel_mux_{ci}_{uuid.uuid4().hex[:8]}.log"
                raw_audio = temp_root / f"_sel_audio_{ci}_{uuid.uuid4().hex[:8]}.f32le"
                temp_video = temp_root / f"_sel_video_{ci}_{uuid.uuid4().hex[:8]}.{ext}"
                try:
                    video_proc, video_log_f = _start_video_encoder(
                        ffmpeg, temp_video, w, h, fps, codec, crf, preset, video_log
                    )
                    _write_image_frames(video_proc, video)
                    _finish_process(video_proc, video_log_f, video_log, "H3 selective export encoder")

                    sr = int(audio["sample_rate"])
                    wave = audio["waveform"]
                    channels = int(wave.shape[1])
                    target = int(round(float(seg["frames"]) / float(fps) * sr))
                    if ci > 0:
                        target -= int(round(float(seg.get("trim_frames", 0)) / float(fps) * sr))
                    wave = _fit_audio_segment_to_cumulative(wave, target, 0)
                    with open(raw_audio, "wb") as af:
                        _write_audio_raw(af, wave)
                    _mux_final(ffmpeg, temp_video, raw_audio, clip_path, sr, channels, codec, audio_bitrate, mux_log)

                    item = _comfy_media_item(clip_path, fps, "output")
                    output_ui_videos.append(item)
                    print(f"[H3 Extender] selective export saved: {clip_path}")
                finally:
                    for p in (video_log, mux_log, raw_audio, temp_video):
                        try:
                            if Path(p).exists():
                                Path(p).unlink()
                        except OSError:
                            pass

                progress.advance()

            progress.finish()
            return {
                "ui": {
                    "h3_video": output_ui_videos,
                    "h3_preview_info": [{
                        "mode": "selective_export",
                        "export_clips": str(export_clips),
                        "exported_count": len(output_ui_videos),
                        "total_clips": int(len(segments)),
                    }],
                },
                "result": (),
            }

        # clip_by_clip keeps its fast progressive-preview path, but now also
        # persists that complete current sequence after every rendered clip.
        # The already encoded preview is reused directly: no extra sampling and
        # no second VAE decode are performed for the autosave.
        effective_mode = str(cache.get("run_mode", "full_batch")) if isinstance(cache, dict) else "full_batch"
        if effective_mode == "clip_by_clip":
            progress = _FinalDecodeNativeProgress(unique_id, total=6)

            (
                preview_path,
                last_frame,
                preview_frames,
                seam_shift,
                previous_clip,
                preview_cache_mode,
            ) = _export_live_candidate_preview(
                data_path=data_path,
                manifest_path=manifest_path,
                manifest=manifest,
                segments=segments,
                vae=vae,
                audio_vae=audio_vae,
                fps=float(fps),
                ffmpeg=ffmpeg,
                unique_id=unique_id,
                progress=progress,
            )
            progress.advance()  # preview encode/cache/concat completed

            # Keep one continuously updated real file in the requested output
            # directory.  Re-rendering the same candidate replaces it atomically,
            # so clip-by-clip testing never creates a pile of numbered files.
            autosave_path = _replace_output_from_preview(
                preview_path, out_dir, filename_prefix,
                ffmpeg=ffmpeg, color_timeline=color_timeline,
            )
            progress.advance()

            total_frames = int(manifest.get("final_frame_count", 0))
            total_duration = float(total_frames / float(fps))
            size = _cache_size_mb(data_path, manifest_path)
            item = _comfy_media_item(preview_path, fps, "temp")
            progress.finish()
            status_shift = (
                f"full_preview_cached_{len(segments)}_clips_shift_{int(seam_shift)}"
            )

            return {
                "ui": {
                    "h3_video": [item],
                    "h3_preview_info": [{
                        "mode": "clip_by_clip",
                        "clip": int(len(segments)),
                        "previous_clip": (
                            None if previous_clip is None else int(previous_clip)
                        ),
                        "seam_shift": int(seam_shift),
                        "cache_mode": str(preview_cache_mode),
                        "preview_frames": int(preview_frames),
                        "total_clips": int(len(segments)),
                        "autosave_path": str(autosave_path),
                        "color_timeline": color_timeline,
                        "color_preview_baked": False,
                    }],
                },
                "result": (),
            }

        extension = "mkv" if str(codec) == "FFV1 lossless" else "mp4"
        output_path = _next_output_path(out_dir, filename_prefix, extension)
        expected_frames = int(manifest["final_frame_count"])
        decode_units = max(1, len(segments) - 1)
        progress = _FinalDecodeNativeProgress(
            unique_id, total=4 + (2 * decode_units) + (1 if _timeline_has_color(color_timeline) else 0)
        )
        seam_shifts = {}
        written_frames = 0
        last_frame = None
        video_proc = None
        video_log_f = None

        # Temp artifacts are one set only and are always removed afterwards.
        temp_root = _ensure_cache_root()
        token = uuid.uuid4().hex[:10]
        temp_video = temp_root / f"_export_{token}_video.{extension}"
        raw_audio = temp_root / f"_export_{token}_audio.f32le"
        video_log = temp_root / f"_export_{token}_video.log"
        mux_log = temp_root / f"_export_{token}_mux.log"
        color_temp = temp_root / f"_export_{token}_color.{extension}"

        try:
            # VIDEO - strict constant-memory path: one clip for N=1, otherwise
            # exactly one adjacent pair per seam. Nothing accumulated in IMAGE.
            if len(segments) == 1:
                v = _load_segment_video(data_path, segments[0])
                decoded = vae.decode(v)
                progress.advance()
                if decoded.ndim == 5:
                    decoded = decoded.reshape(-1, decoded.shape[-3], decoded.shape[-2], decoded.shape[-1])
                expected0 = int(segments[0]["frames"])
                if int(decoded.shape[0]) != expected0:
                    raise RuntimeError(
                        f"Disk Final Decode: VAE returned {decoded.shape[0]}, expected {expected0}."
                    )
                h, w = int(decoded.shape[1]), int(decoded.shape[2])
                video_proc, video_log_f = _start_video_encoder(
                    ffmpeg, temp_video, w, h, fps, codec, crf, preset, video_log
                )
                _write_image_frames(video_proc, decoded)
                written_frames = int(decoded.shape[0])
                last_frame = decoded[-1:].detach().cpu().clone()
                del decoded, v
            else:
                for i in range(1, len(segments)):
                    prev_desc = segments[i - 1]
                    curr_desc = segments[i]

                    if int(curr_desc.get("trim_frames", 0)) == 0:
                        # trim=0: clip 首尾相接、无重叠裁剪。H3 video latent
                        # 直接拼接会破坏 2mod5 时间网格（合并 T 无法被 VAE
                        # 解码），因此逐段单独解码并顺序写入；进度计数与
                        # pair 路径一致（每个 seam 一次 advance）。
                        seam_shifts[i] = 0
                        if video_proc is None:
                            pv = _load_segment_video(data_path, prev_desc)
                            dec_p = vae.decode(pv)
                            if dec_p.ndim == 5:
                                dec_p = dec_p.reshape(-1, dec_p.shape[-3], dec_p.shape[-2], dec_p.shape[-1])
                            exp_p = int(prev_desc["frames"])
                            if int(dec_p.shape[0]) != exp_p:
                                raise RuntimeError(
                                    f"Disk Final Decode: VAE returned {dec_p.shape[0]}, expected {exp_p}."
                                )
                            h, w = int(dec_p.shape[1]), int(dec_p.shape[2])
                            video_proc, video_log_f = _start_video_encoder(
                                ffmpeg, temp_video, w, h, fps, codec, crf, preset, video_log
                            )
                            _write_image_frames(video_proc, dec_p)
                            written_frames += int(dec_p.shape[0])
                            last_frame = dec_p[-1:].detach().cpu().clone()
                            del dec_p, pv

                        cv = _load_segment_video(data_path, curr_desc)
                        dec_c = vae.decode(cv)
                        progress.advance()
                        if dec_c.ndim == 5:
                            dec_c = dec_c.reshape(-1, dec_c.shape[-3], dec_c.shape[-2], dec_c.shape[-1])
                        exp_c = int(curr_desc["frames"])
                        if int(dec_c.shape[0]) != exp_c:
                            raise RuntimeError(
                                f"Disk Final Decode: VAE returned {dec_c.shape[0]}, expected {exp_c}."
                            )
                        _write_image_frames(video_proc, dec_c)
                        written_frames += int(dec_c.shape[0])
                        last_frame = dec_c[-1:].detach().cpu().clone()
                        del dec_c, cv
                        continue

                    chain, meta = _build_pair_video(data_path, prev_desc, curr_desc)
                    decoded, previous_raw, current_raw, shift = _decode_pair_video(vae, chain, meta)
                    progress.advance()
                    seam_shifts[i] = int(shift)

                    if video_proc is None:
                        h, w = int(previous_raw.shape[1]), int(previous_raw.shape[2])
                        video_proc, video_log_f = _start_video_encoder(
                            ffmpeg, temp_video, w, h, fps, codec, crf, preset, video_log
                        )
                        # First pair supplies clip 1 exactly once.
                        _write_image_frames(video_proc, previous_raw)
                        written_frames += int(previous_raw.shape[0])
                        last_frame = previous_raw[-1:].detach().cpu().clone()

                    current_out = _correct_current_segment(previous_raw, current_raw)
                    _write_image_frames(video_proc, current_out)
                    written_frames += int(current_out.shape[0])
                    last_frame = current_out[-1:].detach().cpu().clone()
                    del current_out, previous_raw, current_raw, decoded, chain

            if video_proc is None or video_log_f is None:
                raise RuntimeError("Disk Final Decode: encoder never started.")
            _finish_process(video_proc, video_log_f, video_log, "Disk Final Decode encoder")
            progress.advance()
            video_proc = None
            video_log_f = None

            if int(written_frames) != int(expected_frames):
                raise RuntimeError(
                    f"Disk Final Decode wrote {written_frames} frames, expected {expected_frames}."
                )

            # AUDIO - same pair-local policy, exact video seam shift, streaming
            # raw f32 to disk. RAM holds only the current pair plus one small
            # previous-clip PCM reference used to keep pair normalization gain
            # continuous across the timeline.
            written_samples = 0
            cumulative_frames = 0
            previous_tail = None
            previous_clip_wave = None
            sample_rate = None
            channels = None

            with open(raw_audio, "wb") as af:
                if len(segments) == 1:
                    audio0 = _decode_single_audio(data_path, segments[0], audio_vae, fps)
                    progress.advance()
                    sample_rate = int(audio0["sample_rate"])
                    wave0 = audio0["waveform"]
                    channels = int(wave0.shape[1])
                    cumulative_frames = int(segments[0]["frames"])
                    target = int(round(float(cumulative_frames) / float(fps) * sample_rate))
                    wave0 = _fit_audio_segment_to_cumulative(wave0, target, written_samples)
                    _write_audio_raw(af, wave0)
                    written_samples += int(wave0.shape[-1])
                    previous_tail = _audio_seam_tail(wave0, sample_rate)
                    del audio0, wave0
                else:
                    for i in range(1, len(segments)):
                        pair, prev_frames, curr_frames = _decode_pair_audio(
                            data_path,
                            segments[i - 1],
                            segments[i],
                            audio_vae,
                            fps,
                            int(seam_shifts.get(i, 0)),
                        )
                        progress.advance()
                        sr = int(pair["sample_rate"])
                        w = pair["waveform"]
                        prev_n = int(round(float(prev_frames) / float(fps) * sr))
                        pair_previous = w[..., :prev_n]
                        current = w[..., prev_n:]

                        if sample_rate is None:
                            sample_rate = sr
                            channels = int(w.shape[1])
                            cumulative_frames = int(prev_frames)
                            target = int(round(float(cumulative_frames) / float(fps) * sr))
                            first = _fit_audio_segment_to_cumulative(
                                pair_previous, target, written_samples
                            )
                            _write_audio_raw(af, first)
                            written_samples += int(first.shape[-1])
                            previous_tail = _audio_seam_tail(first, sr)
                            previous_clip_wave = first.detach().clone()
                            del first
                        else:
                            if sr != sample_rate:
                                raise RuntimeError("Disk Final Decode: audio sample rate changed.")
                            gain = _match_pair_gain_to_previous(
                                previous_clip_wave, pair_previous, sr
                            )
                            if abs(gain - 1.0) > 1.0e-8:
                                current = current * gain

                        current = _smooth_segment_entry_level(previous_tail, current, sr)
                        current = _declick_segment(previous_tail, current, sr, 12.0)
                        cumulative_frames += int(curr_frames)
                        target = int(round(float(cumulative_frames) / float(fps) * sr))
                        current = _fit_audio_segment_to_cumulative(current, target, written_samples)
                        _write_audio_raw(af, current)
                        written_samples += int(current.shape[-1])
                        previous_tail = _audio_seam_tail(current, sr)
                        previous_clip_wave = current.detach().clone()
                        del pair, w, pair_previous, current

            if int(cumulative_frames) != int(expected_frames):
                raise RuntimeError(
                    f"Disk Final Decode audio represents {cumulative_frames} frames, "
                    f"expected {expected_frames}."
                )

            _mux_final(
                ffmpeg,
                temp_video,
                raw_audio,
                output_path,
                sample_rate,
                channels,
                codec,
                audio_bitrate,
                mux_log,
            )
            progress.advance()

            # Publish the neutral seam-corrected decode to the browser first.
            # The UI applies per-clip grading live, while the persistent output
            # below receives the same settings baked in non-destructively.
            preview_path = _publish_full_preview(output_path, unique_id)
            if _timeline_has_color(color_timeline):
                _apply_color_timeline_to_file(
                    ffmpeg, output_path, color_temp, color_timeline,
                    codec=codec, crf=crf, preset=preset,
                )
                os.replace(color_temp, output_path)
                progress.advance()

            shifts_text = ",".join(
                f"{i}:{int(seam_shifts.get(i, 0))}" for i in range(1, len(segments))
            )
            size = _cache_size_mb(data_path, manifest_path)
            duration = float(expected_frames / float(fps))
            _LOG.info(
                "H3 Disk Final Decode: clips=%d frames=%d duration=%.3fs output=%s",
                len(segments), expected_frames, duration, output_path,
            )

            item = _comfy_media_item(preview_path, fps, "temp")
            progress.finish()

            return {
                "ui": {
                    "h3_video": [item],
                    "h3_preview_info": [{
                        "mode": "full_batch",
                        "clip": int(len(segments)),
                        "preview_frames": int(expected_frames),
                        "total_clips": int(len(segments)),
                        "color_timeline": color_timeline,
                        "color_preview_baked": False,
                    }],
                },
                "result": (),
            }

        finally:
            if video_proc is not None:
                try:
                    if video_proc.stdin is not None:
                        video_proc.stdin.close()
                except Exception:
                    pass
                try:
                    video_proc.kill()
                except Exception:
                    pass
            if video_log_f is not None:
                try:
                    video_log_f.close()
                except Exception:
                    pass
            for p in (temp_video, raw_audio, video_log, mux_log, color_temp):
                try:
                    if Path(p).exists():
                        Path(p).unlink()
                except Exception:
                    pass


NODE_CLASS_MAPPINGS = {
    "MiniMaxH3MotionContextDiskJoin": MiniMaxH3MotionContextDiskJoin,
    "MiniMaxH3MotionContextDiskFinalDecode": MiniMaxH3MotionContextDiskFinalDecode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3MotionContextDiskJoin": "BSAI H3 Film Factory | Motion Context Disk Join",
    "MiniMaxH3MotionContextDiskFinalDecode": "BSAI H3 Film Factory | Final Decode / Preview",
}
