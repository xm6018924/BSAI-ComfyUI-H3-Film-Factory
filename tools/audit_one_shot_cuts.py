# -*- coding: utf-8 -*-
"""一镜到底成片切镜审计 (离线, 不需要 ComfyUI 在跑)。

用法:
    python tools\\audit_one_shot_cuts.py                       # 扫默认 output\\bsai_clips
    python tools\\audit_one_shot_cuts.py <clip1.mp4> <clip2.mp4> ...
    python tools\\audit_one_shot_cuts.py --dir <目录> [--cut 2.0] [--seam 2.0]

判据 (与本插件 v14.289 的实测口径一致):
  * 段内切镜: 相邻帧灰度平均绝对差 / 该 clip 差分中位数  >= --cut   (默认 2.0)
  * 段间接缝: 上一段末帧 vs 下一段首帧 的差 / 下一段内部差分中位数 >= --seam (默认 2.0)
               同时给出最佳对齐位移(帧), 正位移说明下一段首帧其实对应上一段更早的帧
               (即接缝处模型仍在重放上一段), 负位移说明下一段首帧比上一段末帧"超前".

  * 段内叠化: 差分平顶(每帧 1.2~3.0x)且中间帧是首尾两帧的线性混合(α 斜坡法),
               双重曝光, 肉眼可见 —— 尖峰判据抓不到, 由 detect_dissolves 单独识别

退出码: 0 = 全部通过; 1 = 发现切镜/叠化/断裂。
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys

import numpy as np

DEFAULT_DIR = r"C:\BSAI\ComfyUI-BSAI_pro_v36_lig\ComfyUI\output\bsai_clips"
GLOB_PAT = "h3_clip_*_*.mp4"


def find_ffmpeg():
    cands = []
    w = shutil.which("ffmpeg")
    if w:
        cands.append(w)
    cands.append(r"C:\Program Files\ffmpeg\bin\ffmpeg.exe")
    try:
        import imageio_ffmpeg
        cands.append(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        pass
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def load_gray(ff, path, width=480, height=272):
    """解码成 (n, height, width) uint8 灰度帧。固定缩放尺寸, 从字节数反推帧数,
    不依赖 ffprobe。"""
    raw = subprocess.run(
        [ff, "-v", "error", "-i", path, "-vf", "scale=%d:%d" % (width, height),
         "-pix_fmt", "gray", "-f", "rawvideo", "-"],
        capture_output=True).stdout
    n = len(raw) // (width * height)
    if n <= 0:
        return None
    a = np.frombuffer(raw[:n * width * height], dtype=np.uint8)
    return a.reshape(n, height, width).astype(np.float32)


def detect_dissolves(g, diff, med, ratio_lo=1.2, n_mid_min=3, blend_tol=0.35):
    """检测叠化(双重曝光)段落。

    g     : (n, h, w) 灰度帧
    diff  : (n,) 相邻帧平均绝对差
    med   : 该 clip 的差分中位数

    返回 [(i0, i1, peak_ratio, n_mid), ...]
    """
    if med <= 0 or len(g) < 12:
        return []
    n = len(g)
    # 候选区间: 差分 >= ratio_lo x 中位数的极大连续段
    cands = []
    i = 1
    while i < n:
        if diff[i] / med >= ratio_lo:
            j = i
            while j < n and diff[j] / med >= ratio_lo:
                j += 1
            cands.append((i, j - 1))
            i = j
        else:
            i += 1
    out = []
    for (i0, i1) in cands:
        a_i, b_i = i0 - 3, i1 + 3
        if a_i < 0 or b_i >= n:
            continue
        A = g[a_i].astype(np.float32)
        B = g[b_i].astype(np.float32)
        ab = float(np.abs(B - A).mean())
        if ab < 1.0:
            continue
        D = (B - A).reshape(-1)
        den = float((D * D).sum())
        if den < 1e-6:
            continue
        n_mid = 0
        for t in range(i0, i1 + 1):
            G = g[t].astype(np.float32).reshape(-1)
            al = float(((G - A.reshape(-1)) * D).sum() / den)
            al = max(0.0, min(1.0, al))
            blend = (1.0 - al) * A + al * B
            res = float(np.abs(G - blend.reshape(-1)).mean())
            if 0.10 < al < 0.90 and res < blend_tol * ab:
                n_mid += 1
        peak = float(max(diff[i] for i in range(i0, i1 + 1)) / med)
        if n_mid >= n_mid_min and peak < 3.0:
            out.append((i0, i1, peak, n_mid))
    return out


def analyze(ff, path):
    g = load_gray(ff, path)
    if g is None:
        return None
    n = len(g)
    d = np.zeros(n, dtype=np.float32)
    for i in range(1, n):
        d[i] = float(np.abs(g[i] - g[i - 1]).mean())
    body = d[1:]
    med = float(np.median(body)) if len(body) else 0.0
    cuts = []
    if med > 0:
        for i in range(1, n):
            r = d[i] / med
            if r >= 2.0:
                cuts.append((i, float(d[i]), float(r)))
    return {"path": path, "frames": n, "gray": g, "diff": d, "median": med, "cuts": cuts,
            "dissolves": detect_dissolves(g, d, med)}


def seam(prev, cur):
    """接缝质量: prev 末帧 vs cur 前若干帧的最佳对齐。"""
    a = prev["gray"]
    b = cur["gray"]
    tail = a[-1]
    best = None
    best_rows = []
    for k in range(min(24, len(b))):
        v = float(np.abs(b[k] - tail).mean())
        best_rows.append((k, v))
        if best is None or v < best[1]:
            best = (k, v)
    base = cur["median"]
    ratio = (best[1] / base) if base > 0 else 0.0
    return {"best_k": best[0], "best_diff": best[1], "ratio": ratio,
            "head_diff": float(np.abs(b[0] - tail).mean()), "rows": best_rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--dir", default=None)
    ap.add_argument("--cut", type=float, default=3.0)
    ap.add_argument("--seam", type=float, default=2.0)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    ff = find_ffmpeg()
    if not ff:
        print("!! 找不到 ffmpeg, 请安装或加入 PATH")
        return 2

    files = list(a.files)
    if not files:
        d = a.dir or DEFAULT_DIR
        files = sorted(glob.glob(os.path.join(d, GLOB_PAT)),
                       key=lambda p: (os.path.basename(p).split("_")[2] if "_" in os.path.basename(p) else p))
    if not files:
        print("!! 没有找到 clip 文件 (目录: %s)" % (a.dir or DEFAULT_DIR))
        return 2

    print("ffmpeg: %s" % ff)
    print("待审: %d 个 clip\n" % len(files))
    infos = []
    for p in files:
        if not os.path.isfile(p):
            continue
        info = analyze(ff, p)
        if info:
            infos.append(info)

    failed = False
    for info in infos:
        name = os.path.basename(info["path"])
        cuts = [c for c in info["cuts"] if c[2] >= a.cut]
        dis = info.get("dissolves") or []
        status = "OK " if not cuts and not dis else "CUT"
        if cuts or dis:
            failed = True
        print("=" * 88)
        print("[%s] %s  frames=%d  帧差中位数=%.3f" % (status, name, info["frames"], info["median"]))
        if cuts:
            print("   段内切镜 %d 处 (阈值 %.1f× 中位数), 按强度列前 12:" % (len(cuts), a.cut))
            for i, v, r in sorted(cuts, key=lambda x: -x[2])[:12]:
                print("      f%-5d t=%6.3fs  diff=%8.3f  x_median=%5.2f" % (i, i / 24.0, v, r))
        if dis:
            print("   段内叠化 %d 处 (双重曝光, 尖峰判据抓不到):" % len(dis))
            for (i0, i1, peak, n_mid) in dis:
                print("      f%-5d..f%-5d  峰值=%.2f×中位数  中间态帧=%d" % (i0, i1, peak, n_mid))
        if not cuts and not dis and not a.quiet:
            top = np.argsort(-info["diff"][1:])[:3] + 1
            print("   段内无切镜。最陡的 3 帧: " +
                  ", ".join("f%d(x%.2f)" % (int(i), info["diff"][int(i)] / info["median"]) for i in sorted(top)))
        print("   头部对齐搜索(末帧 vs 本段前 24 帧): " +
              " ".join("f%d:%.1f" % (k, v) for k, v in seam(info, info)["rows"][:12]))

    if len(infos) >= 2:
        print("=" * 88)
        print("段间接缝:")
        for i in range(1, len(infos)):
            s = seam(infos[i - 1], infos[i])
            bad = s["ratio"] >= a.seam
            if bad:
                failed = True
            print("   [%s] %s -> %s : 最佳对齐 f%d, diff=%.3f, x_median=%.2f"
                  % ("CUT" if bad else "OK ",
                     os.path.basename(infos[i - 1]["path"]),
                     os.path.basename(infos[i]["path"]),
                     s["best_k"], s["best_diff"], s["ratio"]))

    print()
    print("结论: %s" % ("发现切镜/叠化/断裂 —— 见上面 CUT 标记" if failed else "全部通过 (无段内切镜、无叠化、接缝连续)"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
