# -*- coding: utf-8 -*-
"""v14.378 角色设定拼版切版器（numpy/cv2 纯实现，可离线单测）。

背景：BSSAI 一镜到底的 @图1 是"5 联角色设定板"（左 1 张胸像特写 + 4 张全身立绘：
正面 / 侧面 / 背面 / 背面）。Ref2VA 会把设定板里**所有**人形当成可复制素材：

  * 首帧同时出现两个人（正面立绘 + 背面立绘各贴一个）；
  * 中段把"背面立绘"当作朝镜头走来的那一个，于是人物背对镜头却逐秒变大 ——
    用户看到的就是"从头到尾倒着走"(moonwalk)。

v14.269 起的 `_split_sheet_subjects` 在这张板上失效（特写与正面立绘挨在一起被并成
一段），反而把**场景图**（故宫拱墙）误判成"2 具视图"并裁掉一半。本模块用确定性几何
判别替掉那套启发式：

  1. 背景色 = 边框像素中位数；前景 = 与背景差异 > 0.10 的像素。
  2. 按"近空列(gutter)"切段。
  3. 全身立绘 = 高度覆盖 ≥ 0.80H 且 宽度 ≤ 0.30W 的窄高段；要求 ≥ 2 段（设定板特征）。
  4. 宽段(宽度 > 0.30W) 里靠右的一段固定为**正面立绘**：以窄高段宽度中位数为窗宽，
     贴着宽段右缘开窗 —— 因为特写永远在最左边，正面立绘紧贴在特写右侧。
  5. 宽段剩下的左边部分 = 胸像(锁脸参考)。

场景图/产品图/双人实拍不会同时满足"≥2 条等高窄段 + 1 条宽段"，因此原样返回。
"""

import cv2
import numpy as np

FG_DELTA = 0.10          # 前景判定阈值(与背景的最大通道差)
GUTTER_MAX = 0.02        # 视为"空列"的列前景占比
MIN_SEG_PX = 8           # 最短有效段宽
TALL_MIN = 0.80          # 全身立绘: 高度覆盖下限
NARROW_MAX = 0.30        # 全身立绘: 宽度上限(占整幅比例)
WIDE_MIN = 0.30          # 特写/宽段: 宽度下限


def _to_rgb_float(img):
    """接受 uint8 / float(0..1 或 0..255)，统一成 float32 RGB 0..1。"""
    a = np.asarray(img)
    if a.ndim == 4:
        a = a[0]
    if a.shape[-1] == 4:
        a = a[..., :3]
    a = a.astype(np.float32)
    if a.max() > 1.5:
        a = a / 255.0
    return a


def _segments(mask):
    H, W = mask.shape
    col = mask.mean(axis=0)
    gut = col < GUTTER_MAX
    segs, s = [], None
    for x in range(W):
        if not gut[x] and s is None:
            s = x
        elif gut[x] and s is not None:
            if x - s >= MIN_SEG_PX:
                segs.append((s, x))
            s = None
    if s is not None and W - s >= MIN_SEG_PX:
        segs.append((s, W))
    out = []
    for (x0, x1) in segs:
        rows = np.where(mask[:, x0:x1].any(axis=1))[0]
        if rows.size == 0:
            continue
        out.append({"x0": x0, "x1": x1, "y0": int(rows[0]), "y1": int(rows[-1]) + 1})
    return out


def locate_sheet_panels(img):
    """返回 {"front": box, "bust": box|None, "views": n, "boxes": [...]} 或 None。

    box = (x0, y0, x1, y1)，像素坐标，右下开区间。
    """
    rgb = _to_rgb_float(img)
    if rgb.ndim != 3:
        return None
    H, W = rgb.shape[:2]
    if W / float(max(1, H)) < 1.25:            # 设定板一定是横幅
        return None
    bg = np.median(np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]], axis=0), axis=0)
    mask = np.abs(rgb - bg).max(axis=2) > FG_DELTA
    segs = _segments(mask)
    if len(segs) < 3:
        return None
    tall = [s for s in segs if (s["y1"] - s["y0"]) / H >= TALL_MIN
            and (s["x1"] - s["x0"]) / W <= NARROW_MAX]
    wide = [s for s in segs if (s["x1"] - s["x0"]) / W > WIDE_MIN]
    if len(tall) < 2 or not wide:
        return None
    med_w = int(np.median([s["x1"] - s["x0"] for s in tall]))
    if med_w < 24:
        return None

    front, bust = None, None
    for wseg in wide:
        x0, x1 = wseg["x0"], wseg["x1"]
        if x1 - x0 < med_w * 1.4:
            continue
        c1 = x1
        c0 = max(x0, c1 - med_w)
        # 窗内必须有足够前景, 否则不是人形
        if mask[:, c0:c1].mean() < 0.08:
            continue
        front = (c0, wseg["y0"], c1, wseg["y1"])
        if c0 - x0 >= med_w * 0.8:              # 左边还剩一大块 = 胸像
            bust = (x0, wseg["y0"], c0, wseg["y1"])
        break
    if front is None:                           # 兜底: 最左侧窄高段
        s = min(tall, key=lambda q: q["x0"])
        front = (s["x0"], s["y0"], s["x1"], s["y1"])
    n_views = len(tall) + (1 if bust is not None else 0)
    return {"front": front, "bust": bust, "views": n_views,
            "boxes": [(s["x0"], s["y0"], s["x1"], s["y1"]) for s in segs]}
