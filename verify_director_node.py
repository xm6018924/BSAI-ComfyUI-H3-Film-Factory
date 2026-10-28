# -*- coding: utf-8 -*-
"""v14.238 Director 极速双采移植 —— 节点级注册验证。
断言:
  1) render_pipeline 组合包含新档位「Director 极速双采 (MiniMaxH3 Director 移植)」
  2) optional 包含 refine_sampler / director_fast_first_mp / director_fast_target_mp / refine_sigmas
  3) _sample_h3 签名含 refine_sampler / refine_sigmas 参数
  4) 管道分支变量可访问(import 期无 NameError)
"""
import os
import sys
import importlib.util
import types

COMFY_ROOT = r"C:\BSAI\ComfyUI-BSAI_pro_v36_lig\ComfyUI"
FF_DIR = os.path.join(COMFY_ROOT, "custom_nodes", "BSAI-ComfyUI-H3-Film-Factory")
sys.path.insert(0, COMFY_ROOT)
sys.path.append(FF_DIR)

import torch  # noqa: E402

_PKG = "bsai_h3_ff_verify2"
_pkg = types.ModuleType(_PKG)
_pkg.__path__ = [FF_DIR]
sys.modules[_PKG] = _pkg

for _stem in ("motion_context_ram", "prompt_bridge", "motion_context_disk", "patch_h3_audio_row_order"):
    _spec = importlib.util.spec_from_file_location(f"{_PKG}.{_stem}", os.path.join(FF_DIR, f"{_stem}.py"))
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[f"{_PKG}.{_stem}"] = _mod
    try:
        _spec.loader.exec_module(_mod)
    except Exception as _pre_err:
        print(f"[preload] {_stem} skip: {_pre_err}")

_ext_spec = importlib.util.spec_from_file_location(f"{_PKG}.extender", os.path.join(FF_DIR, "extender.py"))
EX = importlib.util.module_from_spec(_ext_spec)
sys.modules[f"{_PKG}.extender"] = EX

try:
    from server import PromptServer  # noqa: E402
    class _MockRoutes:
        def __getattr__(self, name):
            def deco(*a, **k):
                def wrap(fn):
                    return fn
                return wrap
            return deco
    class _MockServer:
        routes = _MockRoutes()
        def send_sync(self, *a, **k):
            return None
    if getattr(PromptServer, "instance", None) is None:
        PromptServer.instance = _MockServer()
except Exception as _ps_err:
    print(f"[mock PromptServer] fail: {_ps_err}")

_ext_spec.loader.exec_module(EX)

PASS = FAIL = 0
def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name} {detail}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")

NEW_PIPELINE = "Director 极速双采 (MiniMaxH3 Director 移植)"

# 1) INPUT_TYPES 完整构建
try:
    it = EX.BSAIH3FilmFactory.INPUT_TYPES()
    check("INPUT_TYPES() 构建成功", isinstance(it, dict))
except Exception as e:
    it = None
    check("INPUT_TYPES() 构建成功", False, f"err={e}")

if it:
    opt = it.get("optional", {})
    rp = opt.get("render_pipeline", [None])[0]
    check("render_pipeline 含新档位", isinstance(rp, list) and NEW_PIPELINE in rp,
          f"共 {len(rp) if isinstance(rp, list) else 0} 档")
    check("optional.refine_sampler 存在", "refine_sampler" in opt)
    check("optional.director_fast_first_mp 存在", "director_fast_first_mp" in opt)
    check("optional.director_fast_target_mp 存在", "director_fast_target_mp" in opt)
    check("optional.refine_sigmas 存在(SIGMAS 端口)", "refine_sigmas" in opt)
    if "refine_sigmas" in opt:
        check("refine_sigmas 类型为 SIGMAS", opt["refine_sigmas"][0] == "SIGMAS",
              f"type={opt['refine_sigmas'][0]}")
    if "refine_sampler" in opt:
        rs_opts = opt["refine_sampler"][0]
        check("refine_sampler 组合含 euler/inherit", "inherit (跟随一采)" in rs_opts and "euler" in rs_opts)
    # required 不变性抽查: 旧键仍在
    req = it.get("required", {})
    for k in ("run_mode", "width", "height", "steps", "sampler_name", "scheduler", "refine_enable"):
        check(f"required 旧键 {k} 保留", k in req)

# 2) _sample_h3 签名
import inspect
sig = inspect.signature(EX._sample_h3)
params = list(sig.parameters.keys())
check("_sample_h3 含 refine_sampler 参数", "refine_sampler" in params)
check("_sample_h3 含 refine_sigmas 参数", "refine_sigmas" in params)
check("_sample_h3 默认参数值", sig.parameters["refine_sampler"].default is None
      and sig.parameters["refine_sigmas"].default is None)

# 3) 管道分支引用变量存在性(import 期已证明, 这里只确认模块级辅助函数)
for fn in ("_ff_director_canvas", "_ff_director_refine_factor", "_ff_sigmas_override_tensor"):
    check(f"辅助函数 {fn} 已定义", callable(getattr(EX, fn, None)))

# 4) 节点注册表
check("NODE_CLASS_MAPPINGS 含 BSAIH3FilmFactory", "BSAIH3FilmFactory" in EX.NODE_CLASS_MAPPINGS)

print(f"\n===== 结果: PASS={PASS} FAIL={FAIL} =====")
sys.exit(1 if FAIL else 0)
