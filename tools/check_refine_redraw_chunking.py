#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v14.390 二采「真重绘」的时间分块强制契约自检。

背景(实机 2026-11-12 14:55 那轮): v14.389 把二采重绘打开后, FastH3/PIKA 双采档
在二采第 1 块就死等 ——
  日志: v14.383 分块二采 tile 1/4 起算 free=3.5GB tokens≈272,136, 之后 20 分钟无输出
  py-spy: _tiled_model_call -> _invoke_model -> cast_bias_weight
  硬件: GPU util 100% 但 98W、显存带宽利用率 1%、主机单核 100%
根因是两道否决同时生效, 让 v14.270 的「每前向 tokens 超预算就时间分块」在真重绘
路径上从未生效:
  ① _CHUNKED_DENOISE_ON 默认 0(v14.306 的「整段一次」)
  ② refine_no_temp_chunk(v14.281 MV 双采的「原版 temporal_chunk_tokens=0」)
本脚本守的是修法不被回退。

静态断言, 不加载 ComfyUI:
  1) 真重绘判定 _redraw390 存在且在自动分块之前
  2) 自动分块条件同时接受 _CHUNKED_DENOISE_ON 与 _redraw390
  3) 真重绘不再被 refine_no_temp_chunk 否决(_tc_override390)
  4) 真重绘的分块目标压到 64k 档(BSAI_H3_REFINE_TILE_TOKEN_TARGET, 默认 65536)
  5) BSAI_H3_TEMPORAL_TRIGGER=off 在真重绘 + 超预算时被显式忽略
  6) 纯超分(denoise=0)仍保留 v14.281 的「整段一次」口子
  7) 分块策略 env(BSAI_H3_REFINE_REDRAW_MEM)存在
"""
import io
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.join(BASE, "extender.py")

PASS = 0
FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}" + (f"  -> {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"[FAIL] {name}" + (f"  -> {detail}" if detail else ""))


def main():
    src = io.open(EXT, "r", encoding="utf-8").read()

    i_red = src.find("_redraw390 = _r_denoise > 1e-6")
    i_auto = src.find("if ((_CHUNKED_DENOISE_ON or _redraw390)")
    check("真重绘判定 _redraw390 存在", i_red > 0, f"at {i_red}")
    check("_redraw390 在自动时间分块之前", 0 < i_red < i_auto, f"red={i_red} auto={i_auto}")
    check("自动分块条件接受 _redraw390(不再只看 _CHUNKED_DENOISE_ON)",
          "(_CHUNKED_DENOISE_ON or _redraw390)" in src)
    check("真重绘不再被 refine_no_temp_chunk 否决",
          "and (not refine_no_temp_chunk or _tc_override390)" in src)
    check("_tc_override390 定义为「双采 + 真重绘」",
          "_tc_override390 = bool(refine_no_temp_chunk) and not _use_temporal and _redraw390" in src)

    # 64k 分块目标
    check("真重绘分块目标常量存在(默认 65536)",
          'os.environ.get(\n                                    "BSAI_H3_REFINE_TILE_TOKEN_TARGET", "65536")' in src
          or 'os.environ.get("BSAI_H3_REFINE_TILE_TOKEN_TARGET", "65536")' in src)
    i_tgt = src.find('"BSAI_H3_REFINE_TILE_TOKEN_TARGET"')
    check("真重绘目标只向下压(min), 不抬高别人的预算",
          i_tgt > 0 and "_tok_tgt270 = min(_tok_tgt270, max(16384.0, _tok_tgt390))" in src)
    check("目标带下限护栏(>=16k, 防切成单 token 段)",
          "max(16384.0, _tok_tgt390)" in src)
    check("真重绘目标不作用于 global 全上下文模式(那里靠稀疏注意力)",
          "if _redraw390 and not _is_global_mem226:" in src)

    # off 开关让位
    i_off = src.find('if _trig270 == "off":')
    check("BSAI_H3_TEMPORAL_TRIGGER=off 分支存在", i_off > 0, f"at {i_off}")
    seg_off = src[i_off:i_off + 900] if i_off > 0 else ""
    check("off 在真重绘 + 超预算时被显式推翻",
          "_redraw390 and _per_tile226 > _tok_tgt270" in seg_off
          and "忽略 BSAI_H3_TEMPORAL_TRIGGER=off" in seg_off)

    # 纯超分仍保留整段一次
    check("纯超分仍打印 v14.281 的『整段一次』",
          "v14.281 MV 双采: 按原版 temporal_chunk_tokens=0" in src)
    check("真重绘会明说撤销了 v14.281",
          "撤销 v14.281" in src)

    # 分块策略 env
    check("分块策略 env BSAI_H3_REFINE_REDRAW_MEM 存在",
          '"BSAI_H3_REFINE_REDRAW_MEM"' in src)
    check("策略只接受 global / spatial 两个值",
          'in ("global", "spatial")' in src)

    print()
    if FAIL:
        print(f"有 {FAIL} 条失败 / 共 {PASS + FAIL} 条")
        return 1
    print(f"全部通过 ({PASS} 条 v14.390 二采真重绘分块自检)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
