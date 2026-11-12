# -*- coding: utf-8 -*-
"""v14.379 分块二采 TST 跳过自检。

实机故障(2026-11-12 09:58): 二采 16 分钟零进展, py-spy 栈顶仍在 _spectral_tension,
GPU 100% 占用但功耗只有 96W/450W —— v14.377 的 per-model skip 标志根本没置上:
分块模块拿到的是 BaseModel 外层, state 挂在被 patch 的内层 MiniMaxH3Model 上。

本检查覆盖三条, 任何一条回归都会让二采重新退化成每分钟一层的空转:
  1) 模块级 push_tile_skip() 能让 attention override 直接回落原生实现(与对象层级无关);
  2) _find_tst_state() 能沿 BaseModel -> inner_model 链条找到挂在最内层的 state;
  3) 分块循环里有 push/pop 与每块耗时日志(否则又变成"无动静")。
"""
import importlib.util
import os
import sys
import types

import torch

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("[PASS] " if ok else "[FAIL] ") + name + (("  -> " + str(detail)) if detail else ""))


def load(mod_name, rel):
    spec = importlib.util.spec_from_file_location(mod_name, os.path.join(BASE, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    tst = load("v379_h3_tst", os.path.join("vendor", "selflift_tst", "h3_tst.py"))
    tiles = load("v379_tiles", "bsai_h3_spatial_tiles.py")

    # 1) 模块级开关生效(per-model state 故意不置位, 模拟实机取不到 state 的情形)
    state = {"tau": 0.2, "log_diagnostics": False, "exact_debug": False, "skip_tiles": False,
             "frames": 2, "rows_per_frame": 1, "step": 0, "total_steps": 1, "layers": 2,
             "calls_this_forward": 0, "guard_misses": 0, "warned_inactive": False,
             "fw_abs_tension": [], "fw_abs_tension_post": [], "fw_gamma": [], "fw_active": [],
             "fw_tst_time": [], "fw_events": []}
    calls = {"n": 0}

    def _base(q, k, v, heads, mask=None, **kw):
        calls["n"] += 1
        return "BASE-ATTN"

    ov = tst._attention_override(state)
    q = torch.randn(1, 2, 1024, 8)      # s=1024 > frames*rows=2 -> 长度 guard 放行
    k = torch.randn(1, 2, 1024, 8)
    v = torch.randn(1, 2, 1024, 8)

    tst.push_tile_skip()
    r = ov(_base, q, k, v, 2)
    tst.pop_tile_skip()
    check("push_tile_skip() 期间 TST 短路(不跑 eigvalsh)", r == "BASE-ATTN" and calls["n"] == 1,
          f"r={r} calls={calls['n']}")
    check("短路期间 guard_misses 累加(便于日志判 inactive)", state["guard_misses"] >= 1,
          state["guard_misses"])
    check("pop 之后恢复正常(仍会进 TST)", not tst.tile_skip_active(), tst.tile_skip_active())
    check("tile_skip_active() 反映嵌套深度",
          (tst.push_tile_skip() or True) and tst.tile_skip_active()
          and (tst.pop_tile_skip() or True) and not tst.tile_skip_active())

    # 2) 深链查找: state 只挂在内层
    inner = types.SimpleNamespace(_bsai_tst_state={"skip_tiles": False})
    cfg = types.SimpleNamespace(inner_model=inner)
    outer = types.SimpleNamespace(inner_model=cfg, model=None)
    hit = tiles._find_tst_state(outer, cfg, inner)
    check("_find_tst_state 能沿 inner_model 链找到最内层 state", isinstance(hit, dict), hit)
    check("_find_tst_state 对无 state 的对象返回 None",
          tiles._find_tst_state(types.SimpleNamespace(inner_model=None)) is None)

    # 3) 分块循环: push/pop + 每块耗时日志 + 测试模块能被找到
    src = open(os.path.join(BASE, "bsai_h3_spatial_tiles.py"), "r", encoding="utf-8").read()
    check("分块循环内调用 push_tile_skip()", "push_tile_skip()" in src)
    check("finally 内调用 pop_tile_skip() 复位", "pop_tile_skip()" in src)
    check("每块耗时落日志(不再出现无动静)", "分块二采: tile %d/%d 用时 %.1fs" in src)
    sys.modules["h3_tst"] = tst
    check("_find_tst_module() 能定位到已加载的 h3_tst",
          tiles._find_tst_module() is tst, tiles._find_tst_module())

    print()
    if FAIL:
        print("FAILED %d / %d" % (len(FAIL), len(FAIL) + len(PASS)))
        for f in FAIL:
            print("  - " + f)
        return 1
    print("全部通过 (%d 条 v14.379 分块二采 TST 跳过自检)" % len(PASS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
