# -*- coding: utf-8 -*-
"""ported — 原独立插件节点移植区。

原先单独安装的 Custom Node 插件已整体并入电影工厂，节点类名（NODE_CLASS_MAPPINGS
键名）与显示名保持不变，因此旧工作流无需改节点即可直接运行：

  librosa_beat_cue.py     <- A_LibrosaBeatCue 插件
                             A_LibrosaBeatCue / A_TextInjectCue
  h3_context_pro/         <- H3ContextContinuationPro 插件
                             H3ContextInjectPro / H3ContextTrimPro
  vhs_custom_path.py      <- ComfyUI-VideoCombineCustomPath 插件
                             VHS_VideoCombineCustomPath / VHS_LoadVideoCustomLatest
  selflift_avatar/        <- selflift-Avatar 插件（整套算法模块一并保留）
                             SelfLiftAvatarH3Sampler 等
  vrgdg_video_compare.py  <- VRGDG_VideoCompare 插件
                             VRGDG_VideoCompareSlider
  h3_sigma_refiner.py     <- ComfyUI-YCNodes-MiniMax-H3 插件
                             H3SigmaRefiner
  h3_dynamic_cfg_scheduler.py <- 同上（同插件另一个节点）
                             H3DynamicCFGScheduler

各子模块独立 try/except：单个移植节点加载失败不会拖垮电影工厂其余节点。
"""

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

import traceback as _traceback

_PREFIX = "[H3 Film Factory]"


def _merge(tag, module):
    class_mappings = getattr(module, "NODE_CLASS_MAPPINGS", None) or {}
    display_mappings = getattr(module, "NODE_DISPLAY_NAME_MAPPINGS", None) or {}
    NODE_CLASS_MAPPINGS.update(class_mappings)
    NODE_DISPLAY_NAME_MAPPINGS.update(display_mappings)
    print(f"{_PREFIX} ported.{tag} loaded: {len(class_mappings)} node(s) -> {sorted(class_mappings)}")


def _load(tag, importer):
    try:
        _merge(tag, importer())
    except Exception as exc:
        print(f"{_PREFIX} ported.{tag} import failed: {exc}")
        _traceback.print_exc()


def _librosa():
    from . import librosa_beat_cue as m
    return m


def _context_pro():
    from . import h3_context_pro as m
    return m


def _vhs():
    from . import vhs_custom_path as m
    return m


def _selflift():
    from . import selflift_avatar as m
    return m


def _vrgdg():
    from . import vrgdg_video_compare as m
    return m


def _yc_sigma_refiner():
    from . import h3_sigma_refiner as m
    return m


def _yc_dynamic_cfg():
    from . import h3_dynamic_cfg_scheduler as m
    return m


_load("librosa_beat_cue", _librosa)
_load("h3_context_pro", _context_pro)
_load("vhs_custom_path", _vhs)
_load("selflift_avatar", _selflift)
_load("vrgdg_video_compare", _vrgdg)
_load("h3_sigma_refiner", _yc_sigma_refiner)
_load("h3_dynamic_cfg_scheduler", _yc_dynamic_cfg)

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
