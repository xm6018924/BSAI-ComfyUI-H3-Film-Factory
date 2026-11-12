# -*- coding: utf-8 -*-
"""渲染管道步数/标签自检 (v14.386 DMAD 8+2 / v14.387 ACC 8+4)。

为什么需要: 步数配方在两条代码路径里各写一份 ——
  ① `_rp_mode == "<中文内部值>"`(渲染管道下拉的正式入口)
  ② `speed_preset == "<中文内部值>"`(v14.170 以前旧工作流遗留的速度档值)
并且下拉标签是**英文**、内部值走 `_RENDER_PIPELINE_EN2ZH` 映射 —— 标签/映射/分支
三处任何一处对不上, 这一档就等于没接上(下拉选了也没反应)。本脚本一并守这三处。

判据:
  DMAD  : 两分支都是 steps 8 + refine 2; 旧 4+2 已清; shift 12/2; 强制 lcm
  ACC   : 英文标签在 combo 列表里; EN2ZH 映射到中文内部值; 该内部值有 elif 分支;
          步数 8+4; euler + simple; shift 12/3; 二采放大 x2.0; 提示禁叠第二个加速 LoRA
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


def section(text, start_pat, span=2200):
    m = re.search(start_pat, text)
    if not m:
        return ""
    return text[m.start():m.start() + span]


def main():
    src = io.open(SRC, encoding="utf-8").read()

    # ── DMAD ────────────────────────────────────────────────────────────
    rp = section(src, r'e(?:l)?if _rp_mode == "DMAD-4步"')
    sp = section(src, r'e(?:l)?if speed_preset == "DMAD-4步"')

    check("DMAD: 渲染管道分支存在", bool(rp))
    check("DMAD: 旧速度档分支存在", bool(sp))

    for tag, seg in (("渲染管道", rp), ("旧速度档", sp)):
        check(f"DMAD {tag}: 一采 8 步 + 二采 2 步",
              "steps, refine_steps, tile_count, refine_denoise = 8, 2," in seg)
        check(f"DMAD {tag}: 旧 4+2 已清掉",
              not re.search(r"steps, refine_steps, tile_count, refine_denoise\s*=\s*4,\s*2,", seg))
        check(f"DMAD {tag}: shift 双轨迹仍是 12/2",
              "shift_video, shift_audio = 12.0, 2.0" in seg)
        check(f"DMAD {tag}: 采样器仍强制 lcm",
              'sampler_name = "lcm"' in seg)

    check("DMAD: 下拉标签保持不变(旧工作流兼容)",
          '"DMAD 4-step"' in src and '"DMAD-4步"' in src)

    # ── ACC ─────────────────────────────────────────────────────────────
    en = "ACC 8-step SelfLift Dual-Pass (8+4)"
    zh = "ACC 8步 SelfLift 双采 (8+4)"
    LABEL_JS = "ACC 8-Step SelfLift Dual-Pass (8+4)"

    check("ACC: 英文标签进了渲染管道 combo 列表",
          f'"{en}"' in src, en)
    check("ACC: EN2ZH 映射存在且指向中文内部值",
          f'"{en}": "{zh}"' in src, f'{en} -> {zh}')
    check("ACC: 中文内部值有对应的 elif 分支(否则下拉选了也没反应)",
          f'_rp_mode == "{zh}"' in src, zh)

    acc = section(src, rf'e(?:l)?if _rp_mode == "{re.escape(zh)}"')
    check("ACC: 一采 8 步 + 二采 4 步",
          "steps, refine_steps = 8, 4" in acc)
    check("ACC: 二采 denoise 0.45 / 分块 16 / overlap 128",
          "tile_count, refine_denoise = 16, 0.45" in acc
          and "tile_overlap = 128" in acc)
    check("ACC: 二采开启且 x2.0 放大(2K 直出)",
          "refine_enable = True" in acc
          and "refine_upscale_factor = 2.0" in acc
          and "refine_align_to = 32" in acc)
    check("ACC: euler + simple(8 步蒸馏契约)",
          'sampler_name = "euler"' in acc and 'scheduler = "simple"' in acc)
    check("ACC: shift 双轨迹 12/3",
          "shift_video, shift_audio = 12.0, 3.0" in acc)
    check("ACC: 一采 denoise = 1.0(全生成, 不是续描)",
          "denoise = 1.0" in acc)
    check("ACC: 明示禁叠第二个加速 LoRA",
          "不要再叠加第二个加速 LoRA" in acc)
    check("ACC: 明示 Ref2VA / FL2VA 两个权重的挂法",
          "Ref2VA-Acc-8Step" in acc and "FL2VA-Acc-8Step" in acc)

    # ── 共同前提 ────────────────────────────────────────────────────────
    check("二采不重绘默认开(8+4 的 4 步不产生额外重绘)",
          '_FF_REFINE_NO_REDRAW = str(os.environ.get("BSAI_H3_REFINE_REDRAW", "0"))'
          in src)

    # ── 前端三张同序号表(cycle / cycleLabels / tints) ──────────────────
    # 后端加档而前端没跟 -> 下拉里选不到(v14.213 的坑); tints 少一条 ->
    # 最后一条档位画到它时 color 是 undefined(v14.387 顺手补的那个既存缺陷)。
    js_path = os.path.join(os.path.dirname(HERE), "web", "extender.js")
    if not os.path.exists(js_path):
        check("前端 web/extender.js 存在", False, js_path)
    else:
        js = io.open(js_path, encoding="utf-8").read()
        rp_pos = js.find('{ key: "render_pipeline"')
        check("前端: 找到 render_pipeline 的 QUICK_DEFS", rp_pos > 0)
        if rp_pos > 0:
            c_s = js.find("cycle: [", rp_pos); c_e = js.find("]", c_s)
            cyc = re.findall(r'"([^"]*)"', js[c_s:c_e])
            l_s = js.find("cycleLabels: [", rp_pos); l_e = js.find("]", l_s)
            labs = re.findall(r'"([^"]*)"', js[l_s:l_e])
            t_s = js.find("tints: [", rp_pos); t_e = js.find("]", t_s)
            tints = re.findall(r'color:\s*"([^"]+)"', js[t_s:t_e])

            check("前端 cycle / cycleLabels / tints 三表等长(色带表不许少条)",
                  len(cyc) == len(labs) == len(tints),
                  f"cycle={len(cyc)} labels={len(labs)} tints={len(tints)}")
            check("前端 cycle 含 ACC 且与后端同一序号(第 28 位)",
                  en in cyc and cyc.index(en) == 28, str(cyc.index(en) if en in cyc else -1))
            check("前端 cycleLabels 同序号有 ACC",
                  LABEL_JS in labs and labs.index(LABEL_JS) == cyc.index(en))
            check("前端 cycleAliases / ALIAS_CANON 都带 ACC 中文别名",
                  js.count(f'"ACC 8步 SelfLift 双采 (8+4)": "ACC 8-step SelfLift Dual-Pass (8+4)"') == 2,
                  str(js.count('"ACC 8步 SelfLift 双采 (8+4)"')))

    print()
    if ok:
        print("全部通过 (v14.386 DMAD 8+2 / v14.387 ACC 8+4 渲染管道自检)")
        return 0
    print(f"失败 {len(fails)} 项: {fails}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
