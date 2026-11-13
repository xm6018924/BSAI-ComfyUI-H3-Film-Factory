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

    # ── BSAI6+2 高低噪采样 (v14.401) ────────────────────────────────────
    # 用户口径: 一采 6 步同时作 SplitSigmas 切点, 二采 2 步; 两者相加 8 进
    # BasicScheduler(beta, denoise 1), 在 step=6 切成高噪 6 步 / 低噪 2 步,
    # 二采前 MinimaxH3LatentUpscaler3D 放大(放大不算步)。
    # 判据必须守住"两段来自同一条 8 步 beta 曲线"这一条 —— 一旦谁把一采改成
    # 独立的 6 步 beta, 切点 σ 就整体偏掉, 二采起点不再是 SplitSigmas 的切点。
    b62_en = "BSAI 6+2 High/Low-Noise Split Sampling (beta 8-step split at 6, 3D latent upscale)"
    b62_zh = "BSAI6+2高低噪采样"

    check("BSAI6+2: 英文标签进了渲染管道 combo 列表", f'"{b62_en}"' in src, b62_en)
    check("BSAI6+2: EN2ZH 映射存在", f'"{b62_en}": "{b62_zh}"' in src)
    check("BSAI6+2: 中文内部值有对应的 elif 分支", f'_rp_mode == "{b62_zh}"' in src, b62_zh)

    # 该档注释较长, 窗口放宽到 6000 字符, 否则判据落在窗口外会假 FAIL(首次即此)。
    b62 = section(src, rf'e(?:l)?if _rp_mode == "{re.escape(b62_zh)}"', span=6000)
    check("BSAI6+2: 一采 6 步 + 二采 2 步", "steps, refine_steps = 6, 2" in b62)
    check("BSAI6+2: 一采走 8 步 beta 曲线的高噪段(切点在 6)",
          'scheduler = "bsai6plus2_high"' in b62)
    check("BSAI6+2: 二采 sigma 由同一条曲线切出并直送(refine_sigmas)",
          "_bsai_6plus2_split(" in b62 and "refine_sigmas = _b62_lo" in b62)
    check("BSAI6+2: 总 8 步 = 6+2, 放大不计步(denoise 1.0 全生成)",
          "denoise = 1.0" in b62 and "refine_upscale_factor = 2.0" in b62)
    check("BSAI6+2: 二采前 3D latent 放大 + align 32",
          "refine_align_to = 32" in b62 and "minimax_h3_latent_upscaler_3d_fp16" in b62)
    check("BSAI6+2: 两段采样器都是 euler(参考工作流 KSamplerSelect)",
          'refine_sampler = "euler"' in b62 and "sampler_name = \"euler\"" in b62)
    check("BSAI6+2: shift 双轨迹 12/3", "shift_video, shift_audio = 12.0, 3.0" in b62)
    check("BSAI6+2: 打开切分采样标志(免 denoise 夹取/免结构闸门)",
          "_FF_SPLIT_SIGMA_MODE = True" in b62)

    # 曲线本体: 8 步 beta 在 step=6 切开, 且一采/二采共用同一次计算
    check("BSAI6+2: 切分常量 = 8 总步 / 6 切点",
          "_BSAI6P2_TOTAL_STEPS = 8" in src and "_BSAI6P2_SPLIT_STEP = 6" in src)
    check("BSAI6+2: 切分函数用 beta 8 步一次算好再切(_bsai_6plus2_split)",
          "def _bsai_6plus2_split(" in src
          and 'calculate_sigmas(ms, "beta", _total)' in src)
    hi = section(src, r'str\(scheduler\) in \("bsai6plus2_high", "bsai6plus2_low"\)', span=700)
    check("BSAI6+2: _sigmas 支持高噪/低噪两个哨兵调度",
          "_hi62, _lo62 = _bsai_6plus2_split(" in hi
          and '"bsai6plus2_high"' in hi and '"bsai6plus2_low"' in hi)
    check("BSAI6+2: 二采内容锁的 denoise 夹取对该档让位",
          "elif _r_denoise > _FF_REFINE_LOCK_DENOISE and not _FF_SPLIT_SIGMA_MODE:" in src)
    check("BSAI6+2: 二采重绘下限抬高对该档让位",
          "and not _FF_SPLIT_SIGMA_MODE:" in src
          and "_r_denoise < _FF_REFINE_FLOOR_DENOISE" in src)
    check("BSAI6+2: 结构相似度闸门对该档让位", 
          "if _refine_base_snapshot is not None and not _FF_SPLIT_SIGMA_MODE:" in src)
    check("BSAI6+2: 每轮进入 extend 复位切分标志",
          "global _FF_SPLIT_SIGMA_MODE" in src and "_FF_SPLIT_SIGMA_MODE = False" in src)
    check("BSAI6+2: 二采 fallback 重跑仍走低噪段",
          '"bsai6plus2_low" if _FF_SPLIT_SIGMA_MODE else "beta"' in src)
    check("BSAI6+2: 时间分块对该档硬关(分块会逐段重加噪, 破坏续算)",
          "if _FF_SPLIT_SIGMA_MODE:\n                _use_temporal = False" in src
          and "_tc_override390 = False" in src)

    # ── 共同前提 ────────────────────────────────────────────────────────
    # v14.389: 默认从「二采一律不重绘」翻成「二采一律重绘 + 内容锁」。
    check("二采重绘默认开(env 需显式 NO_REDRAW=1 才回到纯超分)",
          'os.environ.get("BSAI_H3_REFINE_NO_REDRAW", "0")' in src
          and 'os.environ.get("BSAI_H3_REFINE_REDRAW", "1")' in src)
    check("二采内容锁 denoise 上限常量存在(v14.393 默认 0.55)",
          'os.environ.get("BSAI_H3_REFINE_DENOISE_MAX", "0.55")' in src)
    check("二采重绘下限常量存在(v14.393 默认 0.45)",
          'os.environ.get("BSAI_H3_REFINE_DENOISE_MIN", "0.45")' in src)
    check("二采 sigma 走精确映射(denoise=真实起点 σ, v14.393)",
          '_FF_REFINE_SIGMA_EXACT' in src and '_sigmas_exact(model, "beta"' in src)
    check("二采内容闸门阈值常量存在",
          'os.environ.get("BSAI_H3_REFINE_CONTENT_MIN", "0.85")' in src)

    # ── v14.388: 4 步蒸馏档不许吃 ComfyUI 的等间距 simple 网格 ─────────
    # PDMD 4 步档曾强改 scheduler="simple" -> σ=[1.0,0.973,0.9231,0.8,0],
    # 与学生的训练边界 [1.0,0.7,0.4,0.15,0] 经 shift 12 映射出的
    # [1.0,0.96552,0.88889,0.67925,0] 不是同一条路线 -> 整段出纯噪声。
    i_pdmd = src.find('elif _rp_mode == "PDMD 4步 SelfLift 双采 (4+2)":')
    check("PDMD 4 步分支存在", i_pdmd > 0)
    if i_pdmd > 0:
        nxt = src.find("elif _rp_mode ==", i_pdmd + 10)
        body = src[i_pdmd:nxt]
        check("PDMD 4 步用训练边界调度(pdmd_manual)",
              'scheduler = "pdmd_manual"' in body)
        check("PDMD 4 步不再用 simple 等间距",
              'scheduler = "simple"' not in body)
        check("PDMD 训练边界常量 = [1.0,0.7,0.4,0.15,0] 的 timestep 写法",
              "_PDMD_H3_SIGMA_KNOTS = (1000.0, 700.0, 400.0, 150.0, 0.0)" in src)
    # 其余蒸馏档同理: 只要它们把 scheduler 钉成 simple, 就会重复这个坑。
    for _tag, _marker in (
        ("PIKA Flex 6+2", "pika_manual"),
        ("Viggle Remake", "_VIGGLE_REMAKE_SIGMAS"),
        ("HyperFlow Flash", "_HYPERFLOW_H3_SIGMAS"),
    ):
        check(f"{_tag} 仍走自己的固定 σ 曲线({_marker})", _marker in src)

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
            # v14.401: 新档追加在两张表的最末尾(不动既有档位序号)
            check("前端 cycle 末位是 BSAI6+2 且与后端同名",
                  bool(cyc) and cyc[-1] == "BSAI 6+2 High/Low-Noise Split Sampling (beta 8-step split at 6, 3D latent upscale)",
                  cyc[-1] if cyc else "")
            check("前端 cycleLabels 末位同序号同步",
                  bool(labs) and labs[-1] == "BSAI 6+2 High/Low-Noise Split (6+2, beta SplitSigmas)",
                  labs[-1] if labs else "")
            check("前端 cycleAliases / ALIAS_CANON 都带 BSAI6+2 中文别名",
                  js.count('"BSAI6+2高低噪采样": "BSAI 6+2 High/Low-Noise Split Sampling (beta 8-step split at 6, 3D latent upscale)"') == 2,
                  str(js.count('"BSAI6+2高低噪采样"')))
            check("前端 OPTIONS 白名单含 BSAI6+2(否则含新档的工作流会被静默回落)",
                  js.count('"BSAI 6+2 High/Low-Noise Split Sampling (beta 8-step split at 6, 3D latent upscale)"') == 4,
                  str(js.count('"BSAI 6+2 High/Low-Noise Split Sampling (beta 8-step split at 6, 3D latent upscale)"')))

    print()
    if ok:
        print("全部通过 (v14.386 DMAD 8+2 / v14.387 ACC 8+4 / v14.388 PDMD 训练边界 / v14.389 二采重绘+内容锁 / v14.401 BSAI6+2 高低噪切分 渲染管道自检)")
        return 0
    print(f"失败 {len(fails)} 项: {fails}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
