# -*- coding: utf-8 -*-
"""v14.233 transparent pipeline smoke test: keying correctness + PyAV exports."""
import os
import sys
import tempfile
import traceback

PLUGIN = r"G:\BSAI-ComfyUI-intel-XPU-GPU-NPU-aki\ComfyUI\custom_nodes\BSAI-ComfyUI-H3-Film-Factory"
sys.path.insert(0, PLUGIN)

import numpy as np
import torch

results = []
def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS" if cond else "FAIL"), name, detail)

# ---- 1. module import + INPUT_TYPES ----
try:
    import bsai_h3_transparent as T
    k_types = T.BSAI_H3_TransparentKey.INPUT_TYPES()
    s_types = T.BSAI_H3_SaveTransparentVideo.INPUT_TYPES()
    check("import bsai_h3_transparent", True, f"nodes={list(T.NODE_CLASS_MAPPINGS)}")
    check("key INPUT_TYPES", "images" in k_types["required"], str(list(k_types["required"]))[:120])
    check("save INPUT_TYPES", "images_rgba" in s_types["required"], str(list(s_types["required"]))[:120])
except Exception:
    check("module import", False, traceback.format_exc())

# ---- 2. keying correctness on synthetic frames ----
try:
    H = W = 128
    yv, xv = np.mgrid[0:H, 0:W]
    plane = np.zeros((H, W, 3), dtype=np.float32)
    plane[..., 1] = 1.0                     # G = 1 pure green backdrop
    dist = np.sqrt((yv - H / 2) ** 2 + (xv - W / 2) ** 2)
    subj = dist < 28
    edge = (dist >= 28) & (dist < 34)
    plane[subj] = [0.2, 0.3, 0.9]           # subject color (blue-ish, not green)
    plane[edge] = [0.4, 0.55, 0.7]          # soft hair-ish edge ring (partial alpha zone)
    frames = np.repeat(plane[None, ...], 3, axis=0)
    im = torch.from_numpy(frames)
    key = T.BSAI_H3_TransparentKey()
    rgba, matte, prev = key.key(im, "绿幕 Green", "平衡（毛发/烟雾）Balanced",
                                0.5, 0.0, 0.0, 2, 1, 0.0, 0.5, False, None)
    a = rgba[..., 3]                       # (B,H,W)
    bg_a = a[:, ~subj & ~edge].mean().item()
    subj_a = a[:, subj].mean().item()
    edge_a = a[:, edge].mean().item()
    check("green key: backdrop transparent", bg_a < 0.08, f"bg alpha={bg_a:.3f}")
    check("green key: subject opaque", subj_a > 0.95, f"subject alpha={subj_a:.3f}")
    check("green key: edge soft", 0.05 < edge_a < 0.95, f"edge alpha={edge_a:.3f}")
    check("rgba 4ch", rgba.shape[-1] == 4 and rgba.shape[0] == 3, str(rgba.shape))
    check("matte/preview shapes", matte.shape == rgba.shape[:3] + (3,) and
          prev.shape == rgba.shape[:3] + (3,), str((matte.shape, prev.shape)))

    # pure black keying (fire): bright center opaque, black bg transparent
    frames2 = np.zeros((1, H, W, 3), dtype=np.float32)
    bright = np.clip(1.0 - dist / 60.0, 0.0, 1.0)
    frames2[..., 0] = bright * 1.0
    frames2[..., 1] = bright * 0.6
    frames2[..., 2] = bright * 0.2
    rgba2, _, _ = key.key(torch.from_numpy(frames2), "纯黑 Pure Black",
                          "平衡（毛发/烟雾）Balanced", 0.5, 0.0, 0.0, 0, 1, 0.0, 0.0, False, None)
    a2 = rgba2[..., 3]
    check("black key: dark bg transparent", a2[:, dist > 55].mean().item() < 0.1,
          f"bg alpha={a2[:, dist > 55].mean().item():.3f}")
    check("black key: bright core opaque", a2[:, dist < 20].mean().item() > 0.9,
          f"core alpha={a2[:, dist < 20].mean().item():.3f}")
except Exception:
    check("keying smoke", False, traceback.format_exc())

# ---- 3. export smoke (PyAV formats) ----
try:
    work = tempfile.mkdtemp(prefix="bsai_h3_transparent_test_")
    os.chdir(work)
    # 8 frames 96x64 RGBA: solid subject block with alpha gradient
    frm = np.zeros((8, 64, 96, 4), dtype=np.float32)
    frm[..., 0] = 0.9; frm[..., 1] = 0.2; frm[..., 2] = 0.3
    xcoord = np.mgrid[0:96]
    frm[..., 3] = np.broadcast_to((xcoord / 96.0)[None, None, :], (8, 64, 96))
    im_rgba = torch.from_numpy(frm)
    audio = {"waveform": torch.zeros((1, 1, 4800), dtype=torch.float32),
             "sample_rate": 24000}
    writer = T.BSAI_H3_SaveTransparentVideo()
    outdir = os.path.join(work, "output")
    os.makedirs(outdir, exist_ok=True)
    if T.folder_paths is not None:          # 测试不污染真实 output 目录
        T.folder_paths.get_output_directory = lambda: outdir
    fmts = ["ProRes 4444 (.mov, 真Alpha)", "RGBA PNG 序列 (.png)"]
    for f in fmts:
        try:
            folder, alpha_file, prev_file, prev_imgs = writer.export(
                im_rgba, f, 24, "smoke_test", audio=audio)
            ok = os.path.exists(alpha_file) and os.path.getsize(alpha_file) > 0
            check(f"export {f}", ok, f"{alpha_file} ({os.path.getsize(alpha_file) if ok else 0} B)")
            check(f"preview {f}", prev_file and os.path.exists(prev_file),
                  prev_file or "no preview")
            check(f"preview imgs {f}", prev_imgs.shape[0] == 8, str(prev_imgs.shape))
        except Exception as e:
            check(f"export {f}", False, traceback.format_exc()[:600])
    # WebM VP9: 本构建 libvpx-vp9 不支持 Alpha -> 必须诚实报错且不留假透明文件
    try:
        writer.export(im_rgba, "WebM VP9 (.webm, Alpha)", 24, "smoke_webm", audio=audio)
        check("export WebM honest-fail", False, "未报错：构建支持 Alpha 时应输出 yuva 文件")
    except RuntimeError as e:
        msg = str(e)
        check("export WebM honest-fail", "VP9" in msg and "Alpha" in msg, msg[:80])
    except Exception as e:
        check("export WebM honest-fail", False, traceback.format_exc()[:400])
    webm_left = []
    base_sub = os.path.join(outdir, "H3_transparent_video")
    if os.path.isdir(base_sub):
        for sub in os.listdir(base_sub):
            adir = os.path.join(base_sub, sub, "alpha")
            if os.path.isdir(adir):
                webm_left += [f for f in os.listdir(adir) if f.endswith(".webm")]
    check("WebM no leftover file", not webm_left, str(webm_left)[:120])
except Exception:
    check("export framework", False, traceback.format_exc())

failed = [r for r in results if not r[1]]
print()
print("=" * 60)
print(f"SMOKE RESULT: {len(results) - len(failed)}/{len(results)} PASSED")
if failed:
    for name, _, detail in failed:
        print("FAILED:", name, "|", detail)
sys.exit(1 if failed else 0)
