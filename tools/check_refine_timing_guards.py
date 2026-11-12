# -*- coding: utf-8 -*-
"""v14.377 二采耗时/可中断 静态自检。

盯三件实机查得出、静态也能守住的事：
  1. 分块 tile forward 内 SelfLift TST 必须被显式暂停（并在结束后复位）。
  2. 分块二采循环必须每块检查中断（否则 UI 取消无效）。
  3. reserve 下限 5.0 只在分块场景生效；非分块必须保持 6.0（v1.88 全幅死锁数），
     且 v14.250 的「>130k 无条件让位」在分块场景必须让位给真实试分配。

用法: python tools/check_refine_timing_guards.py
"""
import io
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = {
    "extender": os.path.join(BASE, "extender.py"),
    "tiles": os.path.join(BASE, "bsai_h3_spatial_tiles.py"),
    "tst": os.path.join(BASE, "vendor", "selflift_tst", "h3_tst.py"),
}

PASS = []
FAIL = []


def _read(key):
    with io.open(FILES[key], "r", encoding="utf-8") as f:
        return f.read()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("[PASS] " if ok else "[FAIL] ") + name + (("  -> " + detail) if detail else ""))


def main():
    src = {k: _read(k) for k in FILES}

    # 1) TST: skip_tiles 短路 + state 暴露
    tst = src["tst"]
    check("TST 有 skip_tiles 短路分支(置位时直接回落原生 attention)",
          'state.get("skip_tiles")' in tst and "_TILE_SKIP_DEPTH" in tst
          and "return func(q, k, v, heads, mask=mask, **kwargs)" in tst)
    # v14.379: v14.377 的 per-model 标志在实机上取不到(见 check_tst_tile_skip.py),
    # 必须有进程级 push/pop 兜底, 否则二采仍是每层空转 eigvalsh。
    check("TST 有进程级开关 push/pop(不依赖属性查找是否命中)",
          "def push_tile_skip()" in tst and "def pop_tile_skip()" in tst
          and "def tile_skip_active()" in tst)
    check("TST 把 state 暴露给宿主(patched._bsai_tst_state)",
          "patched._bsai_tst_state = state" in tst)
    check("TST state 默认 skip_tiles=False(一采不受影响)",
          '"skip_tiles": False' in tst)

    # 2) 分块模块: 置位/复位 + 中断检查
    tiles = src["tiles"]
    check("分块 tile 循环前置位 skip_tiles",
          'state["skip_tiles"] = True' in tiles or '_tst_state["skip_tiles"] = True' in tiles)
    check("分块 finally 复位 skip_tiles(不污染一采/全帧二采)",
          '_tst_state["skip_tiles"] = _tst_prev_skip' in tiles)
    check("分块循环每块检查中断(UI 取消可生效)",
          "throw_exception_if_processing_interrupted" in tiles
          and "_mm_interrupt" in tiles)

    # 3) extender: reserve 下限 / 非分块 6.0 / 探针门
    ext = src["extender"]
    check("分块 reserve 下限 5.0 生效",
          "if tiled_refine:\n                                _r_reserve_gb = max(_r_reserve_gb, 5.0)" in ext)
    check("非分块 workspace 兜底保持 6.0(v1.88 全幅死锁数)",
          "else max(6.0, _r_reserve_gb)" in ext)
    check("v14.250 '>130k 无条件让位' 已限定为非分块",
          "(not _tiled_probe377) and _r_tok_probe250 > 130000" in ext)
    check("分块试分配通过时有专属播报(实机可判 5.0 是否保住)",
          "v14.381 分块 workspace 探针通过" in ext)
    # v14.381: 探针必须先按「v14.181 会不会自动分块」预测, 再按块几何估 workspace ——
    # 否则 709,920 tokens 的分块段会被当成全帧规模, reserve 6.8->8.9、resident
    # 14.4->10.9GB, 每条 forward 多搬 3.4GB 权重(实机二采每块 108.4s)。
    check("v14.381 分块预测与 v14.181 同判据(tokens>130k 即分块)",
          "_will_tile381 = bool(tiled_refine) or _r_tok_probe250 > 130000" in ext)
    check("v14.381 workspace 按块几何缩放(ws_tile = ws_full / n_tiles × 余量)",
          "_ws381 = max(2.0, _ws65 * (1.0 / float(_ntile381)) * 1.5)" in ext)
    check("v14.381 探针按 ws_tile 试分配(不再拿全帧 ws 判让位)",
          "_pb240 = int((_ws381 + 0.5) * 1024 ** 3)" in ext)
    # v14.382: 分块段不再沿用全帧测出的 reserve 提示 —— 6.8GB 会把 resident 压到
    # 14.4GB(offload 6.3GB), 二采每块 >150s 常驻 cast_bias_weight。
    check("v14.382 分块段 reserve 上限 5.5GB(驻留 ~17GB)",
          "_r_reserve_gb = min(_r_reserve_gb, 5.5)" in ext)
    check("v14.382 分块段跳过全帧 reserve 提示",
          "_hint240 = None if tiled_refine else _REFINE_WS_RESERVE_HINT.get(" in ext)
    # v14.383: reserve 由「实测空闲显存」闭环定档, 不再用经验常数(目标带 3.0-6.2GB)
    check("v14.383 二采 free-VRAM 闭环存在",
          "_free383" in ext and "while _it383 < 3 and (_free383 < 3.0 or _free383 > 6.2)" in ext)
    check("v14.383 闭环按 free 缺口双向调整 reserve",
          "_d383 = (3.8 - _free383)" in ext and "_d383 = -min(_free383 - 3.8, 2.5)" in ext)
    tiles = io.open(os.path.join(BASE, "bsai_h3_spatial_tiles.py"), "r", encoding="utf-8").read()
    check("v14.383 每块落起算 free VRAM",
          "v14.383 分块二采: tile %d/%d 起算 free=%.1fGB tokens≈%s" in tiles)
    check("_probe_ok240 有初值(避免 free 足够时 NameError 被外层 except 吞掉)",
          "_ws65 = _ws_tbl.get(round(_r_factor, 1), 2.6)\n                            _probe_ok240 = True" in ext)
    check("版本注释已改为 v14.377(不再误标 v14.341)",
          "v14.341 分块下限 7.5 -> v14.377 5.0" in ext)

    print()
    if FAIL:
        print("FAILED %d / %d" % (len(FAIL), len(FAIL) + len(PASS)))
        for f in FAIL:
            print("  - " + f)
        return 1
    print("全部通过 (%d 条 v14.377 二采耗时/可中断静态自检)" % len(PASS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
