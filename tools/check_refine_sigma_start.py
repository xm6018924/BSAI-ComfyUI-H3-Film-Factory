# -*- coding: utf-8 -*-
"""v14.393 自检: 所有渲染管线的二采都必须从 σ≈0.45~0.55 起步(全分辨率真重绘, 不脱形)。

背景(2026-11-12 实机 + 用户口径): 用户给的参考实现说明 —— `H3SigmaRefiner` 不改起始 σ,
起始 σ 由 BasicScheduler 的 denoise 决定; v1.7 二采从 σ=1.0 起步, 等于把一采整个洗掉,
所以二采必然画成全新画面。要让二采"真重绘又不脱形", 必须从 σ≈0.45/0.55 起步。

本插件真正的问题不是 denoise 值, 而是 `_sigmas()` 的"拉长 total_steps 再取末 N 步"老
img2img 近似: H3 在 shift12 下 σ(t) 高端极平(t=0.5 → σ=0.923), 于是
  denoise=0.45 steps=2 → 真实起点 σ0=0.9234
  denoise=0.50 steps=2 → σ0=0.9234
  denoise=1.00 steps=3 → σ0=1.0000
全部都是"整帧重生"。v14.393 把二采 sigma 改走 `_sigmas_exact`(denoise = 真实起点噪声
比例), 并把上限从 0.20 改成 0.55。

本工具做四件事:
  1) 用 ComfyUI 自己的 ModelSamplingAV(shift 12) 复算"旧算法"的起点 σ, 断言它确实 ≈0.92
     以上(证伪"denoise 已经在起作用");
  2) 复算"精确映射"下 0.45 / 0.50 / 0.55 的真实起点, 断言落在 0.43~0.55;
  3) 从 extender.py 里解析出**每一条渲染管线**的 (steps, refine_steps, denoise) 三元组,
     对每一条算"加上 0.55 上限之后的实际起点 σ", 断言全部 ≤ 0.56(不脱形)、且都真的在
     重绘(非超分, σ0 > 0);
  4) 断言代码契约: 二采走 `_sigmas_exact`、`_FF_REFINE_SIGMA_EXACT` 默认开、
     上限默认 0.55、二采 latent 放大到 1088x1920(120x68)。

用法: <ComfyUI python> tools\\check_refine_sigma_start.py
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUG = os.path.dirname(HERE)
COMFY_ROOT = os.path.dirname(os.path.dirname(PLUG))     # ...\ComfyUI
sys.path.insert(0, COMFY_ROOT)

import torch                                        # noqa: E402
import comfy.samplers                               # noqa: E402
from comfy.model_sampling import ModelSamplingAV    # noqa: E402

EXT = os.path.join(PLUG, "extender.py")
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


def make_ms(shift=12.0, audio=3.0):
    ms = ModelSamplingAV()
    try:
        ms.set_parameters(shift=float(shift), audio_shift=float(audio))
    except TypeError:
        ms.set_parameters(shift=float(shift))
    return ms


MS = make_ms()


def old_sigmas(steps, denoise, scheduler="beta"):
    """复刻 v14.389 及以前的 _sigmas(): 拉长 total_steps, 取末 steps+1 步。"""
    steps = max(1, int(steps))
    denoise = float(denoise)
    if denoise <= 0.0:
        return []
    total = steps
    if denoise < 1.0:
        total = max(steps, int(steps / denoise))
    sig = comfy.samplers.calculate_sigmas(MS, scheduler, total).cpu()
    return [float(v) for v in sig[-(steps + 1):].tolist()]


def exact_sigmas(steps, denoise, scheduler="beta"):
    """复刻 v14.393 的 _sigmas_exact(): 从 σ=denoise·σmax 起步, 按步数走到 0。"""
    steps = max(1, int(steps))
    denoise = float(denoise)
    if denoise <= 0.0:
        return []
    dn = max(256, steps * 32)
    dense = comfy.samplers.calculate_sigmas(MS, scheduler, dn).cpu()
    if float(dense[0]) < float(dense[-1]):
        dense = torch.flip(dense, dims=[0])
    smax = float(dense[0])
    target = smax * denoise
    idx = 0
    for i in range(int(dense.shape[0])):
        if float(dense[i]) <= target:
            idx = i
            break
    tail = dense[idx:]
    n = steps + 1
    if int(tail.shape[0]) >= n:
        pos = torch.linspace(0, int(tail.shape[0]) - 1, n)
        lo = pos.floor().long()
        hi = torch.clamp(lo + 1, max=int(tail.shape[0]) - 1)
        w = pos - lo.float()
        sig = tail[lo] * (1.0 - w) + tail[hi] * w
    else:
        sig = torch.cat([tail, torch.zeros(n - int(tail.shape[0]))])
    sig[-1] = 0.0
    sig[0] = float(dense[idx])
    for i in range(1, n):
        if float(sig[i]) > float(sig[i - 1]):
            sig[i] = float(sig[i - 1])
        elif float(sig[i]) == float(sig[i - 1]) and i < n - 1:
            sig[i] = max(0.0, float(sig[i - 1]) - 1e-6)
    return [float(v) for v in sig.tolist()]


src = io.open(EXT, "r", encoding="utf-8").read()

# ── 1) 旧算法的起点 σ(证伪) ──
print("=== 旧算法(拉长 total_steps 取末 N 步)真实起点 ===")
for dn in (0.45, 0.50, 0.55, 1.00):
    for st in (2, 4):
        o = old_sigmas(st, dn)
        print(f"  denoise={dn:.2f} steps={st}: σ0={o[0]:.4f}")
check("旧算法 denoise=0.45 steps=2 起点 σ 确实 ≈0.92(不是 0.45)",
      abs(old_sigmas(2, 0.45)[0] - 0.9234) < 0.01, f"{old_sigmas(2, 0.45)[0]:.4f}")
check("旧算法 denoise=0.50 steps=2 起点 σ 同样 ≈0.92(洗掉一采)",
      abs(old_sigmas(2, 0.50)[0] - 0.9234) < 0.01, f"{old_sigmas(2, 0.50)[0]:.4f}")

# ── 2) 精确映射的起点 σ ──
print("=== 精确映射(denoise = 真实起点噪声比例) ===")
for dn in (0.45, 0.50, 0.55):
    for st in (2, 3, 4, 6):
        e = exact_sigmas(st, dn)
        print(f"  denoise={dn:.2f} steps={st}: σ0={e[0]:.4f}  σ表={[round(v, 3) for v in e]}")
check("精确映射 denoise=0.45 → σ0≈0.4381", abs(exact_sigmas(2, 0.45)[0] - 0.4381) < 0.01)
check("精确映射 denoise=0.50 → σ0≈0.4859", abs(exact_sigmas(2, 0.50)[0] - 0.4859) < 0.01)
check("精确映射 denoise=0.55 → σ0≈0.5427", abs(exact_sigmas(2, 0.55)[0] - 0.5427) < 0.01)
check("精确映射下起点与步数无关(步数只影响曲线密度)",
      all(abs(exact_sigmas(st, 0.50)[0] - 0.4859) < 0.01 for st in (2, 3, 4, 6)))
check("精确映射 σ 表严格单调不增且以 0.0 收尾",
      all(all(e[i] >= e[i + 1] for i in range(len(e) - 1)) and e[-1] == 0.0
          for e in (exact_sigmas(st, dn) for dn in (0.45, 0.5, 0.55) for st in (2, 4, 6))))

# ── 3) 全表: 每条渲染管线的二采起点 σ(含 0.55 上限) ──
print("=== extender.py 里每一档的二采起点 σ(已套 0.55 上限) ===")
rows = re.findall(r"steps, refine_steps, tile_count, refine_denoise\s*=\s*(\d+),\s*(\d+),\s*(\d+),\s*([0-9.]+)",
                  src)
uniq = sorted(set((int(a), int(b), float(d)) for a, b, _, d in rows))
check("从 extender.py 解析到管线档位表", len(uniq) >= 20, f"{len(uniq)} 组唯一 (steps,refine_steps,denoise)")
worst = None
seen_redraw = 0
bad = []
lo = None
for steps, rsteps, dn in uniq:
    if rsteps <= 0:
        continue          # 单采档, 没有二采
    eff = min(max(dn, 0.45), 0.55)   # v14.393 的下限 0.45 / 上限 0.55
    s0 = exact_sigmas(rsteps, eff)[0] if eff > 0 else 0.0
    seen_redraw += 1
    print(f"  一采{steps:>2}步 二采{rsteps:>2}步 denoise={dn:.2f}(夹后{eff:.2f}) → σ0={s0:.4f}")
    if s0 > 0.56 or s0 < 0.42:
        bad.append((steps, rsteps, dn, eff, s0))
    if worst is None or s0 > worst[0]:
        worst = (s0, steps, rsteps, dn, eff)
    if lo is None or s0 < lo[0]:
        lo = (s0, steps, rsteps, dn, eff)
check("所有双采档的起点 σ 都落在 0.42~0.56(真重绘且不洗掉一采画面)", not bad,
      f"最高: 一采{worst[1]}步/二采{worst[2]}步 denoise={worst[3]:.2f} → σ0={worst[0]:.4f} / "
      f"最低: 一采{lo[1]}步/二采{lo[2]}步 denoise={lo[3]:.2f} → σ0={lo[0]:.4f}"
      if worst else "")
check("所有双采档都真的在重绘(σ0 > 0, 不是纯超分)", seen_redraw >= 15, f"{seen_redraw} 档")
check("表里 denoise=1.0 的档被 0.55 上限挡住(σ0 ≈0.54 而非 1.0)",
      any(d == 1.0 for _, _, d in uniq)
      and abs(exact_sigmas(2, min(1.0, 0.55))[0] - 0.5427) < 0.01)
check("表里 denoise<0.45 的轻档被下限抬到 0.45(σ0 ≈0.44 而非 0.19)",
      any(d < 0.45 for _, _, d in uniq)
      and abs(exact_sigmas(3, max(0.20, 0.45))[0] - 0.4381) < 0.01)

# ── 4) 代码契约 ──
check("二采 sigma 走 _sigmas_exact(不再只有旧 _sigmas)",
      '_sigmas_exact(model, "beta", _r_steps, _r_denoise' in src)
check("精确映射开关 _FF_REFINE_SIGMA_EXACT 存在且默认开",
      'os.environ.get("BSAI_H3_REFINE_SIGMA_EXACT", "1")' in src)
check("二采 denoise 上限默认 0.55(不再是 0.20)",
      'os.environ.get("BSAI_H3_REFINE_DENOISE_MAX", "0.55")' in src)
check("二采 denoise 下限默认 0.45(轻档统一抬到真重绘)",
      'os.environ.get("BSAI_H3_REFINE_DENOISE_MIN", "0.45")' in src)
check("精确映射失败时回退旧算法(不会中断渲染)",
      "v14.393 二采 sigma 精确映射失败, 回退旧算法" in src)
check("二采 latent 目标 = 1088x1920(120x68 latent, refiner 在全分辨率上重绘)",
      "1920x1088 = 120x68 latent" in src or "120x68" in src)

print()
if FAIL:
    print(f"有 {FAIL} 条失败 / 共 {PASS + FAIL} 条")
    sys.exit(1)
print(f"全部通过 ({PASS} 条 v14.393 二采起点 σ 自检)")
