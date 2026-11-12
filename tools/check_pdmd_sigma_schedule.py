# -*- coding: utf-8 -*-
"""v14.388 自检: PDMD 4 步档必须用蒸馏学生的训练噪声边界, 不能用 simple 等间距。

背景(2026-11-12 实机): PDMD 4 步档之前强改 scheduler="simple", 六段出片全是噪点。
根因 = simple 生成 u=linspace(1,0,5)=[1.0,0.75,0.5,0.25,0.0], 经 shift 12 映射成
σ=[1.0,0.973,0.9231,0.8,0.0]; 而 DMD 系 4-NFE 学生的训练边界是
base_schedule [1.0,0.7,0.4,0.15,0.0](5 边界 / 4 NFE), 同样经 shift 12 映射成
σ=[1.0,0.96552,0.88889,0.67925,0.0]。学生只在后者见过的噪声位置上有效。

本工具做三件事:
  1) 用 ComfyUI 自己的 model_sampling 复算两条曲线, 断言 pdmd_manual 的 σ 与预期一致;
  2) 断言 extender.py 的 PDMD 4 步分支确实设 scheduler="pdmd_manual" 且不再设 "simple";
  3) 把 simple / beta / pdmd_manual 三条曲线并排打出来, 供对照留档。

用法: <ComfyUI python> tools\\check_pdmd_sigma_schedule.py
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUG = os.path.dirname(HERE)
COMFY_ROOT = os.path.dirname(os.path.dirname(PLUG))   # ...\ComfyUI
sys.path.insert(0, COMFY_ROOT)

import torch                                   # noqa: E402
import comfy.samplers                          # noqa: E402
from comfy.model_sampling import ModelSamplingAV  # noqa: E402

KNOTS = (1000.0, 700.0, 400.0, 150.0, 0.0)
EXPECT = [1.0, 0.96552, 0.88889, 0.67925, 0.0]
PASS = []


def check(name, ok, detail=""):
    PASS.append(bool(ok))
    print(("[PASS] " if ok else "[FAIL] ") + name + (("  | " + str(detail)) if detail else ""))


def sample_ms(shift=12.0, audio=3.0):
    ms = ModelSamplingAV()
    try:
        ms.set_parameters(shift=float(shift), audio_shift=float(audio))
    except TypeError:
        ms.set_parameters(shift=float(shift))
    return ms


ms = sample_ms()

# 1) 训练边界曲线
pd = ms.sigma(torch.tensor(KNOTS, dtype=torch.float32)).cpu()
got = [round(float(v), 5) for v in pd.tolist()]
check("PDMD 训练边界经 shift 12 映射 = 预期 σ 表", got == EXPECT, got)
check("边界数 = 5(4 NFE)", len(got) == 5)
check("首尾钉死 1.0 → 0.0", got[0] == 1.0 and got[-1] == 0.0)
check("严格单调不增", all(got[i] >= got[i + 1] for i in range(len(got) - 1)))

# 对照: 错的那两条
simple4 = [round(float(v), 4) for v in comfy.samplers.calculate_sigmas(ms, "simple", 4).cpu().tolist()]
beta4 = [round(float(v), 4) for v in comfy.samplers.calculate_sigmas(ms, "beta", 4).cpu().tolist()]
print()
print("对照(同 shift 12/3, 4 步):")
print("  simple(错)      σ =", simple4)
print("  beta(底模/非此档) σ =", beta4)
print("  pdmd_manual(对) σ =", got)
check("simple 的末个非零 σ = 0.8(学生没训练过的位置)", simple4[-2] == 0.8, simple4[-2])
print()

# 2) 源码断言
src = io.open(os.path.join(PLUG, "extender.py"), encoding="utf-8").read()
i_pdmd = src.find('elif _rp_mode == "PDMD 4步 SelfLift 双采 (4+2)":')
check("源码里能找到 PDMD 4 步分支", i_pdmd > 0)
if i_pdmd > 0:
    nxt = src.find("elif _rp_mode ==", i_pdmd + 10)
    body = src[i_pdmd:nxt]
    check("PDMD 4 步分支设 scheduler = \"pdmd_manual\"", 'scheduler = "pdmd_manual"' in body)
    check("PDMD 4 步分支不再设 scheduler = \"simple\"", 'scheduler = "simple"' not in body)
    check("PDMD 4 步分支仍是 4 步一采", "steps, refine_steps, tile_count, refine_denoise = 4, 2" in body)
    check("PDMD 4 步分支仍 shift 12/3", "shift_video, shift_audio = 12.0, 3.0" in body)
check("_PDMD_H3_SIGMA_KNOTS 常量存在", "_PDMD_H3_SIGMA_KNOTS = (1000.0, 700.0, 400.0, 150.0, 0.0)" in src)
check("_sigmas 里有 pdmd_manual 分支",
      'if str(scheduler) == "pdmd_manual":' in src)

# 3) 4 步以外的步数: 只重采样同一条曲线, 不引入新位置
from types import SimpleNamespace  # noqa: E402

print()
print("全部通过: %d/%d" % (sum(PASS), len(PASS)))
sys.exit(0 if all(PASS) else 1)
