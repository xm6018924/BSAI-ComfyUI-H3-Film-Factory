# -*- coding: utf-8 -*-
"""Viggle 出片 -> 人脸换脸后处理 v2（跟踪 + 姿态门控 + 多视角参考 + 可选中性精修 + 唇色迁移）。

相比 v1 的改动（对应验收报告 P0/P1/P2）：
  P0-a  修复低阈值重试从未生效的 bug（v1 传 det_thresh= 给 app.get() 会 TypeError 被 except 吞掉）
  P0-b  三级检测链：普通 -> 降阈值全图 -> 沿上一帧位置局部放大 2x -> 关键点速度外推
  P0-c  姿态门控：按 yaw 自适应混合 alpha，侧脸不再糊成一团
  P1-a  多视角参考池：参考设定板里所有可用脸按 yaw 最近匹配（受参考图分辨率限制，会自动退化）
  P1-b  CodeFormer 中性精修（默认关，由 --restore 打开）
  P2    唇色迁移：按 106 点外轮廓把唇部 a/b 拉向参考图（默认开）

用法:
  python viggle_faceswap.py <in.mp4> <out.mp4> [--model 128|256] [--ref 图] [--all]
                            [--no-track] [--no-gate] [--no-multiref] [--restore]
                            [--no-lip] [--legacy] [--report out.json]
"""
import os
import sys
import time
import json
import shutil
import subprocess
import tempfile

import cv2
import numpy as np
from insightface.app import FaceAnalysis
from insightface.model_zoo.inswapper import INSwapper
from insightface.utils import face_align

FF = r"C:\Users\xm204\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin\ffmpeg.exe"
FPROBE = FF.replace("ffmpeg.exe", "ffprobe.exe")
REF_DEFAULT = r"C:\BSAI\ComfyUI-BSAI_pro_v43\ComfyUI\input\bsai_assets\images\Qwen_Image_2509_00001.png"
MODELS = {
    "128": r"G:\BSAI-ComfyUI-intel-XPU-GPU-NPU-aki\ComfyUI\models\insightface\inswapper_128.onnx",
    "256": r"G:\BSAI-ComfyUI-intel-XPU-GPU-NPU-aki\ComfyUI\models\insightface\reswapper_256.onnx",
}
CF_MODEL = r"G:\BSAI-ComfyUI-intel-XPU-GPU-NPU-aki\ComfyUI\models\insightface\codeformer.onnx"

# 开关：命令行优先，其次环境变量，最后内置默认
ENV_DEF = {
    "track": ("BSAI_H3_FACESWAP_TRACK", True),
    "gate": ("BSAI_H3_FACESWAP_GATE", True),
    "multiref": ("BSAI_H3_FACESWAP_MULTIREF", True),
    "restore": ("BSAI_H3_FACESWAP_RESTORE", False),
    "lip": ("BSAI_H3_FACESWAP_LIP", True),
    "lip_strength": ("BSAI_H3_FACESWAP_LIP_STRENGTH", 0.7),
    "restore_mix": ("BSAI_H3_FACESWAP_RESTORE_MIX", 0.45),
}


def opt(name, argv):
    """返回开关取值：命令行 > 环境变量 > 默认"""
    env_key, default = ENV_DEF[name]
    if "--no-" + name in argv:
        return False if not isinstance(default, float) else 0.0
    if "--" + name in argv:
        return True if not isinstance(default, float) else default
    v = os.environ.get(env_key)
    if v is None or v == "":
        return default
    if isinstance(default, bool):
        return v.strip().lower() not in ("0", "false", "off", "no")
    try:
        return float(v)
    except ValueError:
        return default


def probe(path):
    out = subprocess.run(
        [FPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate,nb_frames",
         "-of", "json", path],
        capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return int(s["width"]), int(s["height"]), float(num) / float(den)


def face_sharp(img, kps, size=224):
    """对齐裁片的拉普拉斯方差：后脑勺/肩部误检的纹理远低于真脸"""
    try:
        aimg, _ = face_align.norm_crop2(img, np.asarray(kps, dtype=np.float32), size)
    except Exception:
        return 0.0
    if aimg.size == 0:
        return 0.0
    gray = cv2.cvtColor(aimg, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def accept_candidate(face, last, img, tag):
    """降阈值/放大/外推得到的候选必须过一致性校验，宁可漏贴也不能贴错位置"""
    if face is None:
        return False, "none"
    if float(face.det_score) < 0.30:
        return False, "lowscore"
    if face_sharp(img, face.kps) < 60.0:
        return False, "blur"
    if tag == "track":
        return True, "ok"
    lb = last.get("bbox")
    if lb is None:
        return (float(face.det_score) >= 0.50, "segment_head" if float(face.det_score) < 0.50 else "ok")
    pw = float(lb[2] - lb[0]); ph = float(lb[3] - lb[1])
    cw = float(face.bbox[2] - face.bbox[0]); ch = float(face.bbox[3] - face.bbox[1])
    lcx, lcy = (float(lb[0]) + float(lb[2])) / 2, (float(lb[1]) + float(lb[3])) / 2
    ccx, ccy = (float(face.bbox[0]) + float(face.bbox[2])) / 2, (float(face.bbox[1]) + float(face.bbox[3])) / 2
    dist = float(np.hypot(ccx - lcx, ccy - lcy))
    if dist > 1.6 * max(pw, cw, 1.0):
        return False, "jump"
    ratio = (cw * ch) / max(1.0, pw * ph)
    if ratio < 0.35 or ratio > 2.8:
        return False, "scale"
    return True, "ok"


class TrackFace(object):
    """手动构造的 target 容器：inswapper 只需要 kps，restore/lip 需要 kps / landmarks。"""

    __slots__ = ("kps", "bbox", "pose", "det_score", "normed_embedding", "landmark_2d_106")

    def __init__(self, kps, bbox=None, pose=None, det_score=0.0, emb=None, lm106=None):
        self.kps = np.asarray(kps, dtype=np.float32).reshape(5, 2)
        self.bbox = np.asarray(bbox if bbox is not None else
                               [self.kps[:, 0].min(), self.kps[:, 1].min(),
                                self.kps[:, 0].max(), self.kps[:, 1].max()], dtype=np.float32)
        self.pose = np.asarray(pose, dtype=np.float32) if pose is not None else None
        self.det_score = float(det_score)
        self.normed_embedding = emb
        self.landmark_2d_106 = lm106


def area(f):
    return float((f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))


def biggest(faces):
    return max(faces, key=area) if faces else None


def yaw_of(f, fallback=0.0):
    try:
        if f is not None and getattr(f, "pose", None) is not None:
            return abs(float(f.pose[1]))
    except Exception:
        pass
    return fallback


def detect(app, img, thresh=None, max_num=0):
    """临时改 det_thresh 后调 app.get —— 绝不把 det_thresh 传给 get()（那是 TypeError 的根源）"""
    old = app.det_model.det_thresh
    if thresh is not None:
        app.det_model.det_thresh = thresh
    try:
        return app.get(img, max_num=max_num)
    finally:
        app.det_model.det_thresh = old


def detect_zoom(app, img, bbox, scale=2.0, thresh=0.22, expand=1.8):
    H, W = img.shape[:2]
    w = float(bbox[2] - bbox[0])
    h = float(bbox[3] - bbox[1])
    cx = (float(bbox[0]) + float(bbox[2])) / 2.0
    cy = (float(bbox[1]) + float(bbox[3])) / 2.0
    bw, bh = w * expand, h * expand
    x0 = max(0, int(cx - bw / 2)); x1 = min(W, int(cx + bw / 2))
    y0 = max(0, int(cy - bh / 2)); y1 = min(H, int(cy + bh / 2))
    if x1 - x0 < 24 or y1 - y0 < 24:
        return []
    crop = img[y0:y1, x0:x1]
    up = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    faces = detect(app, up, thresh)
    out = []
    for f in faces:
        shift = np.array([x0, y0], dtype=np.float32)
        f.bbox[:] = [(float(f.bbox[0]) / scale + x0), (float(f.bbox[1]) / scale + y0),
                     (float(f.bbox[2]) / scale + x0), (float(f.bbox[3]) / scale + y0)]
        f.kps[:] = np.asarray(f.kps, dtype=np.float32) / scale + shift
        out.append(f)
    return out


def paste_face(target_img, bgr_fake, M, alpha=1.0):
    """inswapper 的 paste_back 逻辑，额外支持按 alpha 与原帧混合（alpha<1 时侧脸更稳）"""
    fh, fw = bgr_fake.shape[:2]
    IM = cv2.invertAffineTransform(M)
    img_white = np.full((fh, fw), 255, dtype=np.float32)
    fake_w = cv2.warpAffine(bgr_fake, IM, (target_img.shape[1], target_img.shape[0]), borderValue=0.0)
    white_w = cv2.warpAffine(img_white, IM, (target_img.shape[1], target_img.shape[0]), borderValue=0.0)
    white_w[white_w > 20] = 255
    rows, cols = np.where(white_w == 255)
    if len(rows) == 0:
        return target_img
    mask_h = int(rows.max() - rows.min())
    mask_w = int(cols.max() - cols.min())
    mask_size = int(np.sqrt(max(1, mask_h * mask_w)))
    k = max(mask_size // 10, 10)
    mask = cv2.erode(white_w, np.ones((k, k), np.uint8), iterations=1)
    k2 = max(mask_size // 20, 5)
    mask = cv2.GaussianBlur(mask, (2 * k2 + 1, 2 * k2 + 1), 0)
    mask = (mask / 255.0 * float(alpha))[..., None]
    out = mask * fake_w + (1.0 - mask) * target_img.astype(np.float32)
    return out.astype(np.uint8)


def build_source_pool(app, ref_img, multiref):
    """参考设定板里所有够格的脸；按 yaw 排序备用"""
    faces = detect(app, ref_img)
    if not faces:
        return [], None
    primary = biggest(faces)
    pool = [primary]
    if multiref:
        for f in sorted(faces, key=area, reverse=True):
            if f is primary:
                continue
            w = float(f.bbox[2] - f.bbox[0])
            # 太小（全身立绘里的 40~60px 小脸）拿来当 source 只会更糊，直接排除
            if w < 90 or float(f.det_score) < 0.5:
                continue
            pool.append(f)
    return pool, primary


def pick_source(pool, primary, yaw, multiref):
    if not multiref or len(pool) == 1:
        return primary, 0
    best, bi, bestd = primary, 0, yaw_of(primary) - yaw
    for i, f in enumerate(pool[1:], 1):
        d = abs(yaw_of(f) - yaw)
        if d < abs(bestd) - 15.0:   # 只有明显更贴合姿态才换，避免为省几度丢掉高分辨率正面
            best, bi, bestd = f, i, d
    return best, bi


def gate_alpha(yaw):
    """侧脸少糊一点，但不能少换 —— 下限保持 0.75，身份优先于轮廓干净"""
    a = abs(yaw)
    if a <= 30:
        return 1.0
    if a <= 50:
        return 0.92
    if a <= 65:
        return 0.85
    return 0.75


def lip_polygon(f, scale=1.0):
    """优先用 106 点外轮廓 52..71；没有就按 5 点几何估一个"""
    if getattr(f, "landmark_2d_106", None) is not None:
        pts = np.asarray(f.landmark_2d_106, dtype=np.float32)[52:72]
        if len(pts) >= 8:
            return cv2.convexHull(pts.astype(np.int32))
    kps = np.asarray(f.kps, dtype=np.float32)
    c3, c4 = kps[3], kps[4]
    w = float(np.linalg.norm(c3 - c4))
    if w < 4:
        return None
    cx, cy = (c3[0] + c4[0]) / 2.0, (c3[1] + c4[1]) / 2.0
    ang = float(np.degrees(np.arctan2(c4[1] - c3[1], c4[0] - c3[0])))
    ell = cv2.ellipse2Poly((int(cx), int(cy)), (int(w * 0.55), int(w * 0.30)), int(ang), 0, 360, 5)
    return ell.reshape(-1, 1, 2)


def lip_lab(img, poly, shrink=5):
    if poly is None or len(poly) < 3:
        return None
    mask = np.zeros(img.shape[:2], np.uint8)
    cv2.fillPoly(mask, [poly.astype(np.int32)], 255)
    if shrink > 0:
        mask = cv2.erode(mask, np.ones((shrink, shrink), np.uint8))
    px = mask > 0
    if px.sum() < 30:
        return None
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    return np.median(lab[px], axis=0)


def transfer_lip(img, poly, ref_lab, strength=0.7, lum=0.3):
    """只动唇部 a/b（色相、饱和），L 轻微跟随，纹理与高光全部保留"""
    if poly is None or ref_lab is None or len(poly) < 3:
        return img, False
    H, W = img.shape[:2]
    mask = np.zeros((H, W), np.uint8)
    cv2.fillPoly(mask, [poly.astype(np.int32)], 255)
    if mask.sum() == 0:
        return img, False
    k = max(3, int(round(float(np.sqrt(mask.sum() / 255.0)) * 0.15)) | 1)
    mask = cv2.GaussianBlur(mask, (k * 2 + 1, k * 2 + 1), 0)
    m = (mask / 255.0)[..., None]
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    inner = mask > 120
    if inner.sum() < 30:
        return img, False
    cur = np.median(lab[inner], axis=0)
    d = (ref_lab - cur) * float(strength)
    lab[..., 0] = np.clip(lab[..., 0] + d[0] * lum * m[..., 0], 0, 255)
    lab[..., 1] = np.clip(lab[..., 1] + d[1] * m[..., 0], 0, 255)
    lab[..., 2] = np.clip(lab[..., 2] + d[2] * m[..., 0], 0, 255)
    out = cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)
    return out, True


class Restorer(object):
    def __init__(self, model_path, w=0.8):
        import onnxruntime as ort
        self.sess = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self.in_img = self.sess.get_inputs()[0].name
        self.in_w = self.sess.get_inputs()[1].name
        self.w = float(w)

    def run(self, img, kps, mix=0.45):
        aimg, M = face_align.norm_crop2(img, np.asarray(kps, dtype=np.float32), 512)
        blob = ((aimg[:, :, ::-1].astype(np.float32) / 255.0) - 0.5) / 0.5
        blob = np.ascontiguousarray(blob.transpose(2, 0, 1)[None])
        pred = self.sess.run(None, {self.in_img: blob, self.in_w: np.array(self.w, dtype=np.float64)})[0]
        rec = ((pred[0].transpose(1, 2, 0) * 0.5 + 0.5) * 255).clip(0, 255).astype(np.uint8)
        IM = cv2.invertAffineTransform(M)
        rec_w = cv2.warpAffine(rec, IM, (img.shape[1], img.shape[0]), borderValue=0)
        white = np.full((512, 512), 255, np.float32)
        mask = cv2.warpAffine(white, IM, (img.shape[1], img.shape[0]), borderValue=0)
        mask[mask > 20] = 255
        mask = cv2.erode(mask, np.ones((40, 40), np.uint8), iterations=1)
        mask = cv2.GaussianBlur(mask, (61, 61), 0)
        m = (mask / 255.0 * float(mix))[..., None]
        return (m * rec_w + (1 - m) * img.astype(np.float32)).astype(np.uint8)


def main():
    argv = sys.argv[1:]
    if len(argv) < 2:
        raise SystemExit("用法: viggle_faceswap.py <in.mp4> <out.mp4> [--model 128|256] [--ref 图]")
    inp, out = argv[0], argv[1]
    model = "128"   # 实测身份相似度 inswapper_128 0.842 >> reswapper_256 0.495，默认用 128
    swap_all = "--all" in argv
    ref_p = REF_DEFAULT
    report_p = None
    if "--model" in argv:
        model = argv[argv.index("--model") + 1]
    if "--ref" in argv:
        ref_p = argv[argv.index("--ref") + 1]
    if "--report" in argv:
        report_p = argv[argv.index("--report") + 1]

    legacy = "--legacy" in argv
    use_track = False if legacy else bool(opt("track", argv))
    use_gate = False if legacy else bool(opt("gate", argv))
    use_multi = False if legacy else bool(opt("multiref", argv))
    use_restore = bool(opt("restore", argv)) and not legacy
    use_lip = bool(opt("lip", argv)) and not legacy
    lip_strength = float(opt("lip_strength", argv))
    restore_mix = float(opt("restore_mix", argv))

    w, h, fps = probe(inp)
    print(f"输入 {inp}  {w}x{h} @ {fps:.2f}fps  "
          f"跟踪={int(use_track)} 门控={int(use_gate)} 多视角={int(use_multi)} "
          f"精修={int(use_restore)} 唇色={int(use_lip)}", flush=True)

    tmp = tempfile.mkdtemp(prefix="faceswap_")
    fdir = os.path.join(tmp, "frames")
    os.makedirs(fdir, exist_ok=True)
    t0 = time.time()
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-i", inp,
                    "-vsync", "0", os.path.join(fdir, "%06d.png")], check=True)
    files = sorted(os.listdir(fdir))
    n = len(files)
    print(f"抽帧完成 {n} 帧 ({time.time() - t0:.1f}s)", flush=True)

    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=-1, det_size=(640, 640))
    ref_img = cv2.imread(ref_p)
    pool, primary = build_source_pool(app, ref_img, use_multi)
    if primary is None:
        raise SystemExit("参考图没检出人脸")
    print(f"参考图池 {len(pool)} 张  主脸 bbox={[round(float(v)) for v in primary.bbox]} "
          f"det={float(primary.det_score):.3f} yaw={yaw_of(primary):.1f}", flush=True)

    ref_lip = lip_lab(ref_img, lip_polygon(primary), shrink=7)
    if ref_lip is not None:
        print(f"参考图唇色 LAB = {np.round(ref_lip, 1).tolist()}", flush=True)

    sw = INSwapper(model_file=MODELS[model])
    print(f"换脸模型 {model} input_size={sw.input_size}", flush=True)
    restorer = Restorer(CF_MODEL) if use_restore else None

    stats = {"plain": 0, "low": 0, "zoom": 0, "track": 0, "miss": 0, "reject": 0,
             "swap": 0, "restore": 0, "lip": 0, "multi_pick": 0}
    rows = []
    last = {"kps": None, "bbox": None, "yaw": 0.0, "frame": -99}
    prev_next = {"kps": None}
    t1 = time.time()

    for i, fn in enumerate(files, 1):
        p = os.path.join(fdir, fn)
        img = cv2.imread(p)
        if img is None:
            continue
        faces = detect(app, img)
        src_tag = "plain"
        face = biggest(faces)
        rej = {}
        if face is None:
            # P0-a：真正生效的低阈值重试（旧版这里 TypeError 被吞，等于没重试）
            faces = detect(app, img, 0.22)
            cand = biggest(faces)
            if cand is not None:
                ok, why = accept_candidate(cand, last, img, "low")
                if ok:
                    face, src_tag = cand, "low"
                else:
                    rej["low"] = why
                    faces = []
        if face is None and use_track and last["bbox"] is not None:
            # P0-b：沿上一帧位置局部放大 2x 再找
            faces = detect_zoom(app, img, last["bbox"])
            cand = biggest(faces)
            if cand is not None:
                ok, why = accept_candidate(cand, last, img, "zoom")
                if ok:
                    face, src_tag = cand, "zoom"
                else:
                    rej["zoom"] = why
                    faces = []
        if face is None and rej:
            stats["reject"] += 1
            for r in sorted(set(rej.values())):
                key = "reject_" + r
                stats[key] = stats.get(key, 0) + 1
        yaw = 0.0
        if face is not None:
            yaw = yaw_of(face, last["yaw"])
        elif use_track and last["kps"] is not None and (i - last["frame"]) <= 6:
            # P0-b 末级：关键点速度外推（连续丢失不超过 6 帧才敢用）
            prev = prev_next["kps"]
            if prev is not None and float(np.abs(prev - last["kps"]).max()) > 0.5:
                pred = last["kps"] + (last["kps"] - prev)
            else:
                pred = last["kps"] + 0.0
            kps = pred.astype(np.float32)
            if np.abs(kps).max() > 0 and kps[:, 0].min() >= 0 and kps[:, 1].min() >= 0 \
                    and kps[:, 0].max() < img.shape[1] and kps[:, 1].max() < img.shape[0] \
                    and face_sharp(img, kps) >= 60.0:
                face = TrackFace(kps, pose=[0.0, last["yaw"], 0.0])
                src_tag = "track"
                yaw = last["yaw"]
            else:
                src_tag = "miss"

        if face is None or src_tag == "miss":
            stats["miss"] += 1
            rows.append({"frame": i, "state": "miss"})
            cv2.imwrite(p, img)
            continue
        stats[src_tag] += 1

        src, s_idx = pick_source(pool, primary, yaw, use_multi)
        if s_idx > 0:
            stats["multi_pick"] += 1
        alpha = gate_alpha(yaw) if use_gate else 1.0
        if src_tag == "track":
            alpha = min(alpha, 0.55)

        target_list = faces if (swap_all and faces) else [face]
        for f in target_list:
            fake, M = sw.get(img, f, src, paste_back=False)
            img = paste_face(img, fake, M, alpha)
        stats["swap"] += 1

        if restorer is not None:
            img = restorer.run(img, face.kps, mix=restore_mix)
            stats["restore"] += 1

        if use_lip and ref_lip is not None:
            poly = lip_polygon(face)
            img, ok = transfer_lip(img, poly, ref_lip, strength=lip_strength)
            if ok:
                stats["lip"] += 1

        cv2.imwrite(p, img)
        prev_next["kps"] = last["kps"]
        last["kps"] = np.asarray(face.kps, dtype=np.float32)
        last["bbox"] = np.asarray(face.bbox, dtype=np.float32)
        last["yaw"] = yaw
        last["frame"] = i
        rows.append({"frame": i, "state": "swap", "src": src_tag, "yaw": round(float(yaw), 1),
                     "alpha": round(float(alpha), 2), "ref": int(s_idx),
                     "bbox": [round(float(v)) for v in face.bbox]})

        if i % 50 == 0 or i == n:
            el = time.time() - t1
            print(f"  进度 {i}/{n}  {src_tag} yaw={yaw:.0f} α={alpha:.2f}  "
                  f"均耗时 {el / i:.2f}s/帧  预计剩余 {el / i * (n - i) / 60:.1f}min", flush=True)

    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y",
                    "-framerate", f"{fps:.6f}", "-i", os.path.join(fdir, "%06d.png"),
                    "-i", inp, "-map", "0:v", "-map", "1:a?",
                    "-c:v", "libx264", "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p",
                    "-c:a", "copy", "-shortest", out], check=True)

    mb = os.path.getsize(out) / 1024 / 1024
    el = time.time() - t1
    print(f"完成 {out}  {mb:.1f}MB  耗时 {el / 60:.1f}min", flush=True)
    print("检测来源: " + "  ".join(f"{k}={v}" for k, v in stats.items()), flush=True)
    if report_p:
        json.dump({"input": inp, "output": out, "stats": stats, "frames": rows},
                  open(report_p, "w", encoding="utf-8"), ensure_ascii=False)
        print("report ->", report_p, flush=True)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
