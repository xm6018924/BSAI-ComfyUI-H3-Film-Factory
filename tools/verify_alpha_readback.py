# -*- coding: utf-8 -*-
"""Verify exported alpha files truly carry alpha (read-back via PyAV). v2"""
import os, sys, glob
import numpy as np

TMP_ROOT = os.path.join(os.environ.get("TEMP", "/tmp"), "bsai_h3_transparent_test_*")
CAND = []
for base in glob.glob(TMP_ROOT):
    CAND += glob.glob(os.path.join(base, "output", "H3_transparent_video"))
BASE = CAND[0] if CAND else r"G:\BSAI-ComfyUI-intel-XPU-GPU-NPU-aki\ComfyUI\output\H3_transparent_video"
results = []

def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS" if cond else "FAIL"), name, detail)

for sub in os.listdir(BASE):
    if "smoke_test" not in sub:
        continue
    alpha_dir = os.path.join(BASE, sub, "alpha")
    for fp in glob.glob(os.path.join(alpha_dir, "smoke_test.mov")) + glob.glob(os.path.join(alpha_dir, "smoke_test.webm")):
        import av
        try:
            c = av.open(fp)
            v = c.streams.video[0]
            fmt = v.codec_context.pix_fmt or ""
            has_alpha = "yuva" in fmt
            n_frames = 0
            alpha_means = []
            for fr in c.decode(v):
                n_frames += 1
                # to_ndarray 仅支持部分格式；统一转 rgba 后 Alpha=第4通道
                arr = np.asarray(fr.reformat(format="rgba").to_ndarray())
                alpha_means.append(float(arr[..., 3].mean()))
            c.close()
            mean = float(np.mean(alpha_means)) if alpha_means else -1.0
            check(f"read-back {os.path.basename(fp)}", has_alpha and n_frames == 8,
                  f"pix_fmt={fmt} frames={n_frames} alpha_mean={mean:.2f}")
        except Exception as e:
            check(f"read-back {os.path.basename(fp)}", False, repr(e)[:200])

    pngs = sorted(glob.glob(os.path.join(alpha_dir, "smoke_test_*.png")))
    if pngs:
        from PIL import Image
        im = Image.open(pngs[0])
        check("read-back PNG", im.mode == "RGBA" and len(pngs) == 8,
              f"mode={im.mode} count={len(pngs)}")
        a = np.asarray(im)[..., 3].astype(int)
        check("PNG alpha gradient", abs(int(a[0, 0]) - 0) < 8 and abs(int(a[0, -1]) - 255) < 8,
              f"alpha corner=({int(a[0,0])},{int(a[0,-1])})")

failed = [r for r in results if not r[1]]
print()
print(f"READ-BACK RESULT: {len(results) - len(failed)}/{len(results)} PASSED")
sys.exit(1 if failed else 0)
