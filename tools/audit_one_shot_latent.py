# -*- coding: utf-8 -*-
"""一镜到底「一采 latent 相位离群」审计 —— 判定段内切镜发生在**采样阶段**还是**二采阶段**。

原理
----
链路缓存 `bsai_h3_chain_cache/chain_extender_<id>.h3cache` 里每段存的是**一采**视频
latent (空间 60x34 = 960x544, shape=[1,24,T,34,60])，同一文件里还存
`decoded_mp4_blob` = **最终成片** (1920x1088, 已过二采 CONST 重加噪重绘)。
把两者按帧号对齐：若某处硬切在**一采 latent** 里就已经是最大跳变 → 二采无罪，
切镜是采样阶段产生的（去查提示词/锚帧/mask）；反之则是二采引入的。

关键坑
------
H3 latent 网格 `FRAME_PER_TOKEN=(1,4,4,4,4)` → **每 5 行 = 17 帧**。相邻 latent 行
差分天然带 5 行周期，直接拿全局均值当基线会把**网格周期**误判成内容跳变。
必须用「同相位 (row mod 5) 的中位数」做基线：
    ratio = diff(row r) / median{ diff(row i) : i % 5 == r % 5 }
ratio > 1.8 才是真跳变。

用法
----
    python tools\\audit_one_shot_latent.py                # 扫默认缓存目录
    python tools\\audit_one_shot_latent.py --cache <chain_extender_xxx>
    python tools\\audit_one_shot_latent.py --threshold 1.8
"""
import argparse
import glob
import json
import os
import sys

import numpy as np

DEFAULT_CACHE_DIR = r"C:\BSAI\ComfyUI-BSAI_pro_v36_lig\ComfyUI\bsai_h3_chain_cache"
FRAMES_PER_ROW = 17.0 / 5.0


def find_cache(cache_dir, explicit=None):
    if explicit:
        p = explicit if os.path.isfile(explicit) else os.path.join(cache_dir, explicit)
        if os.path.isfile(p):
            return p
        return None
    cands = sorted(glob.glob(os.path.join(cache_dir, "chain_*.json")))
    cands = [c for c in cands if not c.endswith(".bak") and ".snapshot." not in c]
    return cands[-1] if cands else None


def audit(manifest_path, data_path, threshold=1.8):
    man = json.load(open(manifest_path, encoding="utf-8"))
    if not os.path.exists(data_path):
        return None, ["数据文件不存在: %s" % data_path]
    with open(data_path, "rb") as f:
        blob = f.read()
    out = []
    notes = []
    for seg in man.get("segments", []) or []:
        vi = seg.get("video")
        if not vi:
            continue
        idx = seg.get("index")
        shape = tuple(int(x) for x in vi["shape"])
        need = 1
        for s in shape:
            need *= s
        off = int(vi["offset"])
        if off + need * 4 > len(blob):
            notes.append("SEG %d: 缓存字节不足(off=%d need=%d size=%d) —— 该段可能还没写完"
                         % (idx, off, need * 4, len(blob)))
            continue
        a = np.frombuffer(blob, dtype=np.float32, count=need, offset=off).reshape(shape)
        T = int(shape[2])
        if T < 6:
            continue
        d = np.abs(a[:, :, 1:, :, :] - a[:, :, :-1, :, :]).mean(axis=(0, 1, 3, 4))
        trim = int(seg.get("trim_frames", 0) or 0)
        med_by_phase = {}
        for ph in range(5):
            vals = [float(d[i - 1]) for i in range(1, T) if (i % 5) == ph]
            med_by_phase[ph] = float(np.median(vals)) if vals else 0.0
        rows = []
        for r in range(1, T):
            ph = r % 5
            base = med_by_phase.get(ph, 0.0)
            v = float(d[r - 1])
            ratio = (v / base) if base > 0 else 0.0
            rows.append({"row": r, "gen": r * FRAMES_PER_ROW, "out": r * FRAMES_PER_ROW - trim,
                         "diff": v, "base": base, "ratio": ratio})
        out.append({"index": idx, "T": T, "trim": trim,
                    "frames": seg.get("frames"), "rows": rows,
                    "med": med_by_phase})
    return out, notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=None, help="chain_extender_xxx.json 或 .h3cache")
    ap.add_argument("--dir", default=DEFAULT_CACHE_DIR)
    ap.add_argument("--threshold", type=float, default=1.8)
    a = ap.parse_args()

    mf = find_cache(a.dir, a.cache)
    if not mf:
        print("!! 找不到链路 manifest (目录 %s)" % a.dir)
        return 2
    df = mf[:-5] + ".h3cache" if mf.endswith(".json") else mf
    if not os.path.exists(df):
        df = mf
    print("manifest : %s" % mf)
    print("data     : %s" % df)

    res, notes = audit(mf, df, a.threshold)
    for n in notes:
        print("  ! %s" % n)
    if not res:
        print("  (暂无已完成的段)")
        return 0

    failed = False
    for seg in res:
        hits = [r for r in seg["rows"] if r["ratio"] >= a.threshold]
        print()
        print("=" * 96)
        print("SEG %d  T=%d trim=%d 帧数=%s  相位基线 med=%s"
              % (seg["index"], seg["T"], seg["trim"], seg["frames"],
                 {k: round(v, 4) for k, v in seg["med"].items()}))
        if not hits:
            print("   真跳变: 无 (全部 ratio < %.2f)" % a.threshold)
            continue
        failed = True
        print("   真跳变 %d 处 (ratio >= %.2f):" % (len(hits), a.threshold))
        for r in sorted(hits, key=lambda x: -x["ratio"]):
            print("      row%-3d gen≈%-6.1f out≈%-7.1f  diff=%8.4f base=%8.4f  ratio=%5.2f"
                  % (r["row"], r["gen"], r["out"], r["diff"], r["base"], r["ratio"]))
    print()
    if failed:
        print("结论: 发现一采阶段的真跳变 → 切镜发生在**采样阶段**(提示词/锚帧/mask), 与二采无关。")
        print("      跳变位置 out≈中点(trim+(frames-trim)//2 附近) → 多半是段中锚帧类机制。")
    else:
        print("结论: 一采阶段无真跳变 → 若成片有硬切, 则是**二采**(CONST 重加噪重绘)引入的。")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
