# -*- coding: utf-8 -*-
"""渲染管道步数表自检 (v14.386)。

为什么需要: 步数在两条代码路径里各写一份 ——
  ① `_rp_mode == "DMAD-4步"`(渲染管道下拉的正式入口)
  ② `speed_preset == "DMAD-4步"`(v14.170 以前旧工作流遗留的速度档值)
两处必须一致, 且以用户口径为准。DMAD 口径 = 1 采 8 步 + 2 采 2 步(v14.386)。

本脚本做源码静态扫描(不 import 整个后端), 判据:
  * 两个分支里都出现 `steps, refine_steps, tile_count, refine_denoise = 8, 2, 4, ...`
  * 两个分支里都不再出现 `= 4, 2, 4, ...`(旧 4+2 值)
  * shift 双轨迹仍是 12/2(DMAD 官方配方), 采样器仍强制 lcm
  * 下拉标签保持 "DMAD 4-step" 不变更(旧工作流兼容)
"""

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "extender.py")

ok = True
fails = []


def check(name, cond, detail=""):
    global ok
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + ((f"  -> {detail}" if detail else "") if not cond else ""))
    if not cond:
        ok = False
        fails.append(name)


def section(text, start_pat, span=1600):
    m = re.search(start_pat, text)
    if not m:
        return ""
    return text[m.start():m.start() + span]


def main():
    src = io.open(SRC, encoding="utf-8").read()

    rp = section(src, r'e(?:l)?if _rp_mode == "DMAD-4步"')
    sp = section(src, r'e(?:l)?if speed_preset == "DMAD-4步"')

    check("渲染管道分支存在", bool(rp))
    check("旧速度档分支存在", bool(sp))

    for tag, seg in (("渲染管道", rp), ("旧速度档", sp)):
        check(f"{tag}: 一采 8 步 + 二采 2 步",
              "steps, refine_steps, tile_count, refine_denoise = 8, 2," in seg,
              seg[:80].replace("\n", " "))
        check(f"{tag}: 旧 4+2 已清掉",
              not re.search(r"steps, refine_steps, tile_count, refine_denoise\s*=\s*4,\s*2,", seg),
              "found 4,2")
        check(f"{tag}: shift 双轨迹仍是 12/2",
              "shift_video, shift_audio = 12.0, 2.0" in seg)
        check(f"{tag}: 采样器仍强制 lcm",
              'sampler_name = "lcm"' in seg)

    check("下拉标签保持不变(旧工作流兼容)",
          '"DMAD 4-step"' in src and '"DMAD-4步"' in src)

    # 二采不重绘开关仍在默认开 —— 8+2 的 2 步只在旧重绘路径上生效
    check("二采不重绘默认开(2 步不产生额外重绘)",
          '_FF_REFINE_NO_REDRAW = str(os.environ.get("BSAI_H3_REFINE_REDRAW", "0"))'
          in src)

    print()
    if ok:
        print("全部通过 (v14.386 DMAD 8+2 渲染管道步数自检)")
        return 0
    print(f"失败 {len(fails)} 项: {fails}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
