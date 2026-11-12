#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v14.389 二采「重绘 + 内容锁」静态自检。

背景(用户口径): 电影工厂所有渲染管线的二采都开重绘, 但二采结果必须和一采内容
一样, 不得重绘成别的画面。

v14.384 曾经是「一律不重绘」(denoise 归零 + _FFRefineSkip 跳出整个重绘段) ——
那条结论已被本次诉求反转, 本脚本随之改写, 现在守的是三道同时成立的闸门:

  1) 默认值: env 未设 = 重绘开; 只有 BSAI_H3_REFINE_NO_REDRAW=1
     (或 BSAI_H3_REFINE_REDRAW=0) 才回到 v14.384 的纯超分行为。
  2) 噪声上限: 二采 denoise 一律夹到 _FF_REFINE_LOCK_DENOISE(默认 0.20), 覆盖
     各管线表里的 0.45/0.5/0.55/1.0。
  3) 结构闸门: 采样完成后与「一采放大后的快照」做 4x4 低通余弦相似度,
     低于 _FF_REFINE_CONTENT_MIN(默认 0.85) 即丢弃二采结果、回退一采放大。
  4) 音频: 内容锁期间音频默认锁死(沿用一采), env 可放开。

本脚本只做静态断言, 不加载 ComfyUI。
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

    # 1) 默认值翻转
    i_flag = src.find("_FF_REFINE_NO_REDRAW = (")
    check("模块级开关 _FF_REFINE_NO_REDRAW 存在(新式双 env 定义)", i_flag > 0, f"at {i_flag}")
    seg = src[i_flag:i_flag + 400] if i_flag > 0 else ""
    check("默认是「重绘开」: NO_REDRAW 默认 0", 'get("BSAI_H3_REFINE_NO_REDRAW", "0")' in seg)
    check("保留反向开关: REFINE_REDRAW 默认 1(设 0 即回到纯超分)",
          'get("BSAI_H3_REFINE_REDRAW", "1")' in seg)
    check("内部信号 _FFRefineSkip 仍存在(供 NO_REDRAW 路径使用)",
          "class _FFRefineSkip(Exception):" in src)

    # 2) 噪声上限(v14.393: 0.20 -> 0.55, 并新增 0.45 下限; 数值口径见
    #    check_refine_sigma_start.py —— 那边会用 ComfyUI 自己的 ModelSamplingAV 复算 σ0)
    check("内容锁 denoise 上限常量存在(默认 0.55)",
          '_FF_REFINE_LOCK_DENOISE = float(os.environ.get("BSAI_H3_REFINE_DENOISE_MAX", "0.55"))' in src)
    check("内容锁 denoise 下限常量存在(默认 0.45)",
          '_FF_REFINE_FLOOR_DENOISE = float(os.environ.get("BSAI_H3_REFINE_DENOISE_MIN", "0.45"))' in src)
    check("内容锁 denoise 上限被夹进 [0.05, 1.0] 合法区",
          "_FF_REFINE_LOCK_DENOISE = max(0.05, min(1.0, _FF_REFINE_LOCK_DENOISE))" in src)
    idx_entry = src.find("if _FF_REFINE_NO_REDRAW:")
    idx_else = src.find("elif _r_denoise > _FF_REFINE_LOCK_DENOISE:", idx_entry)
    check("refine 入口按开关分支(NO_REDRAW=1 仍回纯超分)",
          idx_entry > 0 and idx_else > idx_entry, f"entry={idx_entry} else={idx_else}")
    seg2 = src[idx_else:idx_else + 800] if idx_else > 0 else ""
    check("重绘路径把 denoise 夹到内容锁上限", "_r_denoise = _FF_REFINE_LOCK_DENOISE" in seg2)
    idx_floor = src.find("elif _r_denoise > 1e-6 and _r_denoise < _FF_REFINE_FLOOR_DENOISE:", idx_else)
    check("轻档被抬到真重绘下限(v14.393)", idx_floor > idx_else
          and "_r_denoise = _FF_REFINE_FLOOR_DENOISE" in src[idx_floor:idx_floor + 900],
          f"floor at {idx_floor}")

    # 3) 一采快照 + 结构闸门
    idx_snap = src.find("_refine_base_snapshot = None")
    idx_assign = src.find("_refine_base_snapshot = (")
    idx_up = src.find("Refine 潜空间放大: clip=")
    idx_skip = src.find("raise _FFRefineSkip()")
    check("一采快照先占位(二采未启用时闸门不会 NameError)", idx_snap > 0, f"at {idx_snap}")
    check("快照在_放大之后_、跳出点之前拍(拿到的是一采放大后的底图)",
          0 < idx_up < idx_assign < idx_skip,
          f"up={idx_up} assign={idx_assign} skip={idx_skip}")
    check("快照存 CPU float32(不在二采最吃 VRAM 时再占一份显存)",
          'detach().to("cpu", dtype=torch.float32)' in src[idx_assign:idx_assign + 400])
    idx_gate = src.find("_g_cos = float(")
    check("内容闸门存在", idx_gate > 0, f"at {idx_gate}")
    check("闸门在采样之后(位于塌陷检测之后、几何对齐之前)",
          idx_gate > idx_skip
          and idx_gate < src.find("v1.74b (2026-09-15 fix #10)"))
    seg3 = src[idx_gate - 1200:idx_gate + 2600] if idx_gate > 0 else ""
    check("闸门用 4x4 低通(只比结构, 不比细节纹理)",
          "avg_pool2d" in seg3 and "4, ceil_mode=True" in seg3.replace(" ", " "))
    check("闸门用余弦相似度",
          "cosine_similarity" in seg3)
    check("闸门按阈值判定, 低于阈值即丢弃二采",
          "_FF_REFINE_CONTENT_MIN" in seg3 and "if _g_cos <" in seg3)
    check("丢弃二采时回退到一采放大快照",
          "_g_back = _g_base.to(" in seg3 and "_g_nst" in seg3)
    check("回退时大声打印(实机可在日志里看到相似度与回退)",
          "判定重绘成别的画面" in seg3 and "_g_cos:.3f" in seg3)
    check("回退时推送告警(不只写日志)",
          "_send_extender_warning" in seg3)

    # 4) 音频锁
    idx_audio = src.find("v14.389 二采内容锁: 音频重绘")
    check("内容锁期间音频默认锁死", idx_audio > 0, f"at {idx_audio}")
    check("音频锁有 env 放开口",
          'os.environ.get("BSAI_H3_REFINE_AUDIO_REDRAW", "0")' in src)
    check("音频锁分支排在 lip_audio 分支之前(先锁后判)",
          0 < idx_audio < src.find("v14.195 lip_audio 对口型"))

    print()
    if FAIL:
        print(f"有 {FAIL} 条失败 / 共 {PASS + FAIL} 条")
        return 1
    print(f"全部通过 ({PASS} 条 v14.389 二采重绘+内容锁自检)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
