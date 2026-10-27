"""
BSAI-ComfyUI-H3 Film Factory
A complete film production toolkit for MiniMax H3 workflows.

Core H3 nodes (from original MiniMax H3 Extender):
  - MiniMaxH3Extender: Full H3 video generation pipeline with CLIP sequencing
  - MiniMaxH3MotionContextRAM: In-RAM motion context chaining
  - MiniMaxH3MotionContextDiskJoin: Disk-based motion context join
  - MiniMaxH3MotionContextDiskFinalDecode: Final decode/export with codec settings
  - MiniMaxH3TailFromLatent: Tail frame/audio extraction from latent
  - MiniMaxH3PromptPackBridge: Dynamic prompt input packer

Film Factory nodes (new):
  - BSAI_ContextualSeriesExtract/Load: Contextual frame extraction
  - BSAI_AssetLibraryInput/RefSelector/ImageBatchSplitter: Asset management
  - BSAI_ClipComposer/ClipSequencer: Clip editing and sequencing
  - BSAI_SubtitleConfig/SubtitleRenderer: Subtitle rendering
  - BSAI_VideoCombiner/AudioCombiner: Media combining
"""

# === 崩溃栈自动落盘（v14.155 诊断）===
# torch 2.13.0+cu130 原生层偶发 access violation（torch_cpu.dll read@0x0，
# WER 记录同族崩溃 50+ 次）。控制台窗口易被误关导致 faulthandler 堆栈丢失，
# 改为直接写插件目录日志文件：进程崩溃时 Python 栈必落盘，不再依赖控制台。
try:
    import faulthandler as _fh, os as _os, datetime as _dt
    _crash_log = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                               "_crash_faulthandler.log")
    _crash_fp = open(_crash_log, "a", buffering=1, encoding="utf-8", errors="replace")
    _crash_fp.write(f"\n===== faulthandler armed {_dt.datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
    if _fh.is_enabled():
        _fh.disable()
    _fh.enable(file=_crash_fp)
except Exception:
    pass

# === BSAI H3 VAE 全量加载统一补丁（宿主 BSAI-ComfyUI-Sol-H3）===
# 修复 0.39 + --enable-dynamic-vram 下 H3 AudioVAE/VideoVAE 走 DynamicVRAM
# 权重量流导致的解码极慢（5s 音频 209~324s -> 全量加载约 1.6s）。
# 统一逻辑见 Sol-H3/bsai_h3_vae_full.py；try/except 容错，宿主缺失则 no-op。
try:
    import sys as _sys, os as _os
    _SOL = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                         "..", "BSAI-ComfyUI-Sol-H3")
    if _SOL not in _sys.path:
        _sys.path.insert(0, _SOL)
    import bsai_h3_vae_full as _h3v
    _h3v.apply_global_patch("BSAI-H3-Film-Factory")
except Exception:
    pass

# === WinError 10054 noise suppression (Windows asyncio browser disconnect) ===
# Browser refresh / tab close causes asyncio proactor to raise ConnectionResetError
# when shutting down an already-dead socket. This patch swallows it silently.
import asyncio as _asyncio
import socket as _socket

try:
    from asyncio import proactor_events as _proactor_events
    _orig_call_connection_lost = _proactor_events._ProactorBasePipeTransport._call_connection_lost
    def _silent_call_connection_lost(self, exc):
        try:
            _orig_call_connection_lost(self, exc)
        except (ConnectionResetError, BrokenPipeError):
            pass
    _proactor_events._ProactorBasePipeTransport._call_connection_lost = _silent_call_connection_lost
except Exception:
    pass

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

# === Core H3 nodes (from original MiniMax H3 Extender) ===
try:
    from .node import (
        NODE_CLASS_MAPPINGS as UTILITY_NODE_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as UTILITY_NODE_DISPLAY_NAME_MAPPINGS,
    )
    NODE_CLASS_MAPPINGS.update(UTILITY_NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(UTILITY_NODE_DISPLAY_NAME_MAPPINGS)
except Exception as e:
    print(f"[H3 Film Factory] node.py import failed: {e}")

try:
    from .motion_context_ram import (
        NODE_CLASS_MAPPINGS as MOTION_CONTEXT_NODE_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as MOTION_CONTEXT_NODE_DISPLAY_NAME_MAPPINGS,
    )
    NODE_CLASS_MAPPINGS.update(MOTION_CONTEXT_NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(MOTION_CONTEXT_NODE_DISPLAY_NAME_MAPPINGS)
except Exception as e:
    print(f"[H3 Film Factory] motion_context_ram.py import failed: {e}")

try:
    from .extender import (
        NODE_CLASS_MAPPINGS as EXTENDER_NODE_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as EXTENDER_NODE_DISPLAY_NAME_MAPPINGS,
    )
    NODE_CLASS_MAPPINGS.update(EXTENDER_NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(EXTENDER_NODE_DISPLAY_NAME_MAPPINGS)
except Exception as e:
    print(f"[H3 Film Factory] extender.py import failed: {e}")

try:
    from .motion_context_disk import (
        NODE_CLASS_MAPPINGS as MOTION_CONTEXT_DISK_NODE_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as MOTION_CONTEXT_DISK_NODE_DISPLAY_NAME_MAPPINGS,
    )
    NODE_CLASS_MAPPINGS.update(MOTION_CONTEXT_DISK_NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(MOTION_CONTEXT_DISK_NODE_DISPLAY_NAME_MAPPINGS)
except Exception as e:
    print(f"[H3 Film Factory] motion_context_disk.py import failed: {e}")

try:
    from .prompt_bridge import (
        NODE_CLASS_MAPPINGS as PROMPT_BRIDGE_NODE_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as PROMPT_BRIDGE_NODE_DISPLAY_NAME_MAPPINGS,
    )
    NODE_CLASS_MAPPINGS.update(PROMPT_BRIDGE_NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(PROMPT_BRIDGE_NODE_DISPLAY_NAME_MAPPINGS)
except Exception as e:
    print(f"[H3 Film Factory] prompt_bridge.py import failed: {e}")

# === Film Factory nodes (new) ===
try:
    from .nodes import NODE_CLASS_MAPPINGS as CONTEXTUAL_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS as CONTEXTUAL_DISPLAY
    NODE_CLASS_MAPPINGS.update(CONTEXTUAL_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(CONTEXTUAL_DISPLAY)
except Exception as e:
    print(f"[H3 Film Factory] nodes.py import failed: {e}")

try:
    from .nodes_asset import NODE_CLASS_MAPPINGS as ASSET_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS as ASSET_DISPLAY
    NODE_CLASS_MAPPINGS.update(ASSET_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(ASSET_DISPLAY)
except Exception as e:
    print(f"[H3 Film Factory] nodes_asset.py import failed: {e}")

try:
    from .nodes_clip import NODE_CLASS_MAPPINGS as CLIP_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS as CLIP_DISPLAY
    NODE_CLASS_MAPPINGS.update(CLIP_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(CLIP_DISPLAY)
except Exception as e:
    print(f"[H3 Film Factory] nodes_clip.py import failed: {e}")

try:
    from .nodes_subtitle import NODE_CLASS_MAPPINGS as SUBTITLE_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS as SUBTITLE_DISPLAY
    NODE_CLASS_MAPPINGS.update(SUBTITLE_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(SUBTITLE_DISPLAY)
except Exception as e:
    print(f"[H3 Film Factory] nodes_subtitle.py import failed: {e}")

try:
    from .nodes_media import NODE_CLASS_MAPPINGS as MEDIA_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS as MEDIA_DISPLAY
    NODE_CLASS_MAPPINGS.update(MEDIA_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(MEDIA_DISPLAY)
except Exception as e:
    print(f"[H3 Film Factory] nodes_media.py import failed: {e}")

try:
    from .bsai_h3_3dlatent_upscale import (
        NODE_CLASS_MAPPINGS as H3_3D_UPSCALE_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as H3_3D_UPSCALE_DISPLAY,
    )
    NODE_CLASS_MAPPINGS.update(H3_3D_UPSCALE_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(H3_3D_UPSCALE_DISPLAY)
except Exception as e:
    print(f"[H3 Film Factory] bsai_h3_3dlatent_upscale.py import failed: {e}")

# v14.233: 透明视频管道 —— 抠像台 + 透明导出（B站 BV1arJX69E7L 配方）
try:
    from .bsai_h3_transparent import (
        NODE_CLASS_MAPPINGS as TRANSPARENT_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as TRANSPARENT_DISPLAY,
    )
    NODE_CLASS_MAPPINGS.update(TRANSPARENT_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(TRANSPARENT_DISPLAY)
except Exception as e:
    print(f"[H3 Film Factory] bsai_h3_transparent.py import failed: {e}")

# === Server-side API endpoints ===
try:
    from . import server
except Exception as e:
    print(f"[H3 Film Factory] server module load failed: {e}")

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]

WEB_DIRECTORY = "./web"
