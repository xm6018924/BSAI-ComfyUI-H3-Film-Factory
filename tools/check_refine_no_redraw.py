#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v14.384 二采「只超分放大、绝不重绘」静态自检。

背景(用户口径): 电影工厂所有渲染管线的二采(8+2 / 8+4 / FastOmini /
taomate / 直播配音高清 ...)都不许重绘, 必须完全按照一采结果超分放大。
实现不是"把 denoise 调小"(那还是会重绘, 而且分块+权重换页会卡死), 而是在
潜空间放大完成的那一刻用 _FFRefineSkip 跳出整个重绘段。

本脚本只做静态断言, 不加载 ComfyUI:
  1) 模块级开关与内部信号存在
  2) refine 入口把 denoise 强制归零(覆盖所有管线表值)
  3) 跳出点在「潜空间放大」之后、任何加噪/采样之前
  4) 捕获子句排在 OOM 兜底之前(否则会被当成二采失败)
  5) 采样入口(_ff_const_add_noise / guider.sample)全部在跳出点之后
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

    check("模块级开关 _FF_REFINE_NO_REDRAW 存在",
          "_FF_REFINE_NO_REDRAW = str(os.environ.get(\"BSAI_H3_REFINE_REDRAW\"" in src)
    check("内部信号 _FFRefineSkip 存在",
          "class _FFRefineSkip(Exception):" in src)
    check("开关默认是「不重绘」(env 未设 = 生效)",
          'not in ("1", "true", "on")' in src.split("_FF_REFINE_NO_REDRAW = ")[1][:200])

    # 入口归零
    idx_entry = src.find("if _FF_REFINE_NO_REDRAW:")
    check("refine 入口按开关强制 denoise=0", idx_entry > 0, f"at {idx_entry}")
    check("入口归零后有 _r_denoise = 0.0",
          src.find("_r_denoise = 0.0", idx_entry) > idx_entry)

    # 跳出点位置
    idx_up = src.find("Refine 潜空间放大: clip=")
    idx_skip = src.find("raise _FFRefineSkip()")
    check("潜空间放大锚点存在", idx_up > 0, f"at {idx_up}")
    check("跳出点在放大之后", idx_skip > idx_up, f"up={idx_up} skip={idx_skip}")

    # 采样入口必须在跳出点之后
    idx_noise = src.find("_r_noise = comfy.sample.prepare_noise(samples")
    idx_sample = src.find("_r_guider.sample(", idx_skip)  # 二采那处(跳过点之后的第一处)
    check("二采加噪在跳出点之后", idx_noise > idx_skip, f"noise={idx_noise} skip={idx_skip}")
    check("二采采样调用在跳出点之后", idx_sample > idx_skip, f"sample={idx_sample} skip={idx_skip}")

    # 捕获子句顺序: 必须在 OOM 之前
    idx_catch = src.find("except _FFRefineSkip:")
    idx_oom = src.find("except torch.cuda.OutOfMemoryError as _oom:")
    idx_generic = src.find("except Exception as _re:", idx_oom)
    check("捕获 _FFRefineSkip 的子句存在", idx_catch > 0, f"at {idx_catch}")
    check("捕获子句排在 OOM 兜底之前", 0 < idx_catch < idx_oom, f"catch={idx_catch} oom={idx_oom}")
    check("捕获子句排在通用 except 之前", idx_oom < idx_generic)

    # 捕获子句里必须真的收工, 不能回退一采
    seg = src[idx_catch:src.find("except torch.cuda.OutOfMemoryError as _oom:")]
    check("捕获子句打印『只超分放大』", "二采只超分放大(不重绘)" in seg)
    check("捕获子句不把 samples 换回一采备份",
          "_samples_pre_upscale" not in seg)

    # 跳过段覆盖: 分块/驻留/时间分块 全在跳出点之后
    for name, anchor in (
        ("二采驻留", "Refine 二采前 DiT 驻留"),
        ("v14.181 自动分块", "v14.181 方案A"),
        ("时间分块", "v2.02 时间分块二采"),
    ):
        pos = src.find(anchor)
        check(f"{name} 在跳出点之后(不执行)", pos > idx_skip, f"{anchor} at {pos}")

    print()
    if FAIL:
        print(f"有 {FAIL} 条失败 / 共 {PASS + FAIL} 条")
        return 1
    print(f"全部通过 ({PASS} 条 v14.384 二采不重绘自检)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
