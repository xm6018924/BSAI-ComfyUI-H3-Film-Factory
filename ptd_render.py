"""v14.314: 工厂内 PTD 单采接管 —— 独立环节（独立模块，不侵入其它渲染管道）。

为什么单独成文件：
- 工厂 `extender.py` 已有十余条渲染管道（双采/SelfLift/PDMD/Pika/TaoMate …）。
  为了"选 PTD 档即走 PTD fixed-hop 采样"，只允许在**档位明确命中**时由一个
  独立函数接管，且它返回"接管失败"时调用方原样走既有采样路径。
- 本模块不改 `extender.py` 的任何既有分支，只在 `_sample_h3` 里被显式调用。

契约（来自 ptd_compact 与 PTD 官方文档）：
- PTD 是 fixed-hop sampler，不是调度器：步数/时间网格由适配器文件决定，
  必须用 `ptd_compact.compact.sigmas(model)` 的精确网格，不能自己算 sigma。
- Ref2VA 适配器必须配 ref2va 底模 + MiniMax H3 Reference to Video 条件化
  （conditioning 里带 `minimax_refs`）。纯 fl2va 文本生视频选此档不适用。
- PTD patch 会自己接管 `model_sampling` 与 `model_unet_function_wrapper`，
  因此调用方在接管成功后**必须跳过**工厂的双轨迹 shift / TST 注入。
"""
from __future__ import annotations

import os
import weakref
from pathlib import Path

# 优先选用的适配器（本机已落盘并校验通过的 int8 4 步 Ref2VA 版）
ADAPTER_PREFERENCE = ("ptd_h3_ref2va_4step_int8.safetensors",)

# 默认内核：exact = PTD 参考块数学（适配器训练时的一致性最高）
DEFAULT_KERNELS = "exact (PTD reference)"

# 同一 MODEL 只 patch 一次：lip/长片分段时 _sample_h3 会被多次调用，
# 每段重复读 2.67GB 适配器并重建 bank 不可接受（也会让内存翻倍）。
# 缓存用弱引用持有原 MODEL，MODEL 被 ComfyUI 释放时条目自动失效。
_CACHE = {}
_CACHE_LIMIT = 3


def clear_cache():
    """释放已缓存的 PTD patch 结果（排查问题或换适配器时手动调用）。"""
    _CACHE.clear()


def _cache_lookup(model, adapter_path, kernels):
    for _, (ref, patched, sampler, sigmas, info) in list(_CACHE.items()):
        try:
            if ref() is model and info.get("adapter_path") == adapter_path \
                    and info.get("kernels") == kernels:
                return patched, sampler, sigmas, dict(info, cached=True)
        except Exception:
            continue
    return None


def _cache_store(model, patched, sampler, sigmas, info):
    if len(_CACHE) >= _CACHE_LIMIT:
        _CACHE.pop(next(iter(_CACHE)), None)
    try:
        ref = weakref.ref(model)
    except TypeError:
        ref = (lambda m=model: m)
    _CACHE[(id(model), info.get("adapter_path"), info.get("kernels"))] = (
        ref, patched, sampler, sigmas, dict(info))


def _ensure_folder():
    """确保 folder_paths 认识 ptd 目录（与 ptd_compact/nodes.py 同一逻辑，幂等）。"""
    import folder_paths

    if "ptd" not in folder_paths.folder_names_and_paths:
        folder_paths.add_model_folder_path("ptd", str(Path(folder_paths.models_dir) / "ptd"))
    return folder_paths


def list_adapters():
    """models/ptd 下所有可用的 PTD 适配器文件名（未安装返回空列表，不抛异常）。"""
    try:
        fp = _ensure_folder()
        return [f for f in fp.get_filename_list("ptd") if str(f).endswith(".safetensors")]
    except Exception:
        return []


def resolve_adapter(name=None):
    """返回适配器的绝对路径；找不到返回 None（不抛异常）。"""
    try:
        fp = _ensure_folder()
        files = [f for f in fp.get_filename_list("ptd") if str(f).endswith(".safetensors")]
        if name and name in files:
            return fp.get_full_path("ptd", name)
        for pref in ADAPTER_PREFERENCE:
            if pref in files:
                return fp.get_full_path("ptd", pref)
        # 没有首选文件时，任何含 ref2va 的 4 步 int8 文件都可用于本档
        for f in files:
            if "ref2va" in f.lower() and "4step" in f.lower():
                return fp.get_full_path("ptd", f)
    except Exception:
        return None
    return None


def conditioning_has_refs(conditioning):
    """conditioning 里是否带 Ref2VA 的参考图块（minimax_refs / minimax_keyframes）。"""
    try:
        for item in conditioning or []:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            meta = item[1]
            if not isinstance(meta, dict):
                continue
            if meta.get("minimax_refs") or meta.get("minimax_keyframes"):
                return True
            for key in meta.keys():
                if isinstance(key, str) and key.startswith("minimax_ref"):
                    return True
    except Exception:
        return False
    return False


def precheck(model, conditioning, adapter_name=None):
    """接管前的可判定检查。返回 (ok, info)。ok=False 时 info["reason"] 说明原因。"""
    info = {"ok": False, "reason": "", "adapter": None, "kernels": DEFAULT_KERNELS}
    try:
        from .ptd_compact import compact  # noqa: F401  确认子包可导入
    except Exception as e:
        info["reason"] = f"ptd_compact 子包不可用: {type(e).__name__}: {e}"
        return False, info

    path = resolve_adapter(adapter_name)
    if not path:
        info["reason"] = "models/ptd 下没有可用的 PTD 适配器（先放 ptd_h3_ref2va_4step_int8.safetensors）"
        return False, info
    info["adapter"] = os.path.basename(path)
    info["adapter_path"] = path

    if model is None:
        info["reason"] = "没有可用的 MODEL 输入"
        return False, info

    try:
        controller_key = None
        opts = getattr(model, "model_options", {}) or {}
        for key in opts.keys():
            if isinstance(key, str) and "ptd" in key.lower() and "controller" in key.lower():
                controller_key = key
                break
        if controller_key:
            info["reason"] = "该 MODEL 已经装过 PTD 适配器（上游接了 PTD 节点），本档不重复接管"
            return False, info
    except Exception:
        pass

    if not conditioning_has_refs(conditioning):
        info["reason"] = ("conditioning 中没有 minimax_refs / minimax_keyframes —— "
                          "Ref2VA(参考图生视频)条件化未接通，PTD Ref2VA 适配器不适用")
        return False, info

    info["ok"] = True
    return True, info


def try_ptd_single_pass(model, conditioning, adapter_name=None, kernels=None):
    """尝试接管成 PTD fixed-hop 单采。

    返回 (patched_model, sampler, sigmas, info)：
    - 接管成功：patched_model 非 None，sampler/sigmas 为 PTD 的 SAMPLER / SIGMAS；
    - 接管失败：三者均为 None，info["ok"]=False 且 info["reason"] 给出原因。
    本函数**从不抛异常**：调用方据此决定是否回退既有采样路径。
    """
    kernels = kernels or os.environ.get("BSAI_H3_PTD_KERNELS", DEFAULT_KERNELS)
    ok, info = precheck(model, conditioning, adapter_name)
    if not ok:
        return None, None, None, info

    try:
        from .ptd_compact import compact

        if kernels not in compact.KERNELS:
            info["kernels"] = DEFAULT_KERNELS
            kernels = DEFAULT_KERNELS
        info["kernels"] = kernels

        # 同一 MODEL 命中缓存：多段(lip/长片)不再重复读适配器与重建 bank
        hit = _cache_lookup(model, info["adapter_path"], kernels)
        if hit is not None:
            info.update(hit[3])
            info["cached"] = True
            return hit[0], hit[1], hit[2], info

        patched = compact.patch_compact(model, info["adapter_path"], kernels)
        sampler = compact.make_sampler(patched)
        sigmas = compact.sigmas(patched)

        # 记录 hop 网格信息（便于日志核对；拿不到不影响接管）
        try:
            controller = patched.model_options.get("ptd_native_controller")
            if controller is None:
                from .ptd_compact.ptd_inference.ptd_comfy import patcher as _ptd_patcher

                controller = _ptd_patcher.get_ptd_controller(patched)
            info["hops"] = int(getattr(controller, "hops", 0) or 0)
            info["steps"] = int(getattr(controller, "steps", 0) or 0)
            info["sigmas"] = [round(float(v), 5) for v in list(sigmas)[: info["hops"] + 1]]
        except Exception:
            pass

        info["ok"] = True
        info["reason"] = "PTD fixed-hop 接管成功"
        try:
            _cache_store(model, patched, sampler, sigmas, info)
        except Exception:
            pass
        return patched, sampler, sigmas, info
    except Exception as e:
        info["ok"] = False
        info["reason"] = f"PTD patch 失败: {type(e).__name__}: {e}"
        return None, None, None, info
