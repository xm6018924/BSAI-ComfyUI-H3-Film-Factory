# -*- coding: utf-8 -*-
"""v14.378 角色设定拼版切版器自检（跑真实资产，不靠眼判）。

正例：@图1 必须被认成设定板，取到**正面立绘**（不被侧面/背面视图抢走）。
反例：场景图(@图3/@图4)、其它资产必须原样返回 None（此前故宫图被误裁成 2 具视图）。
"""
import io
import os
import sys

import cv2
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from bsai_ref_sheet import locate_sheet_panels  # noqa: E402

ASSET = r"C:\BSAI\ComfyUI-BSAI_pro_v36_lig\ComfyUI\input\bsai_assets\images"
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("[PASS] " if ok else "[FAIL] ") + name + (("  -> " + str(detail)) if detail else ""))


def load(name):
    p = os.path.join(ASSET, name)
    try:  # cv2.imread 打不开非 ASCII 路径, 用 fromfile + imdecode
        buf = np.fromfile(p, dtype=np.uint8)
        bgr = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except Exception:
        bgr = None
    if bgr is None:
        return None
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def sheet_name():
    """按 asset_order.json 的 images[0] 解析 @图1 —— 资产会换人, 不能写死文件名。"""
    import json
    p = os.path.join(os.path.dirname(ASSET), "asset_order.json")
    try:
        with io.open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        imgs = data.get("images") or []
        if imgs:
            return str(imgs[0])
    except Exception:
        pass
    return "Qwen_Image_2509_00001.png"


def main():
    # 1) @图1：若当前资产是多视图设定板, 必须切到正面立绘; 若是单人立绘, 必须原样放行
    name0 = sheet_name()
    img = load(name0)
    if img is None:
        check(f"@图1({name0}) 存在且可读", False, "缺失")
        return 1
    H, W = img.shape[:2]
    res = locate_sheet_panels(img)
    if res is None:
        check(f"@图1({name0}) 不是多视图拼版 -> 原样进 Ref2VA(不裁切/不丢视图)", True,
              f"{W}x{H} single-view")
    else:
        check(f"@图1({name0}) 被判为多视图设定板", True, f"views={res['views']}")
        fx0, fy0, fx1, fy1 = res["front"]
        aspect = (fx1 - fx0) / float(fy1 - fy0)
        check("正面立绘是窄高全身像(宽高比 0.15-0.40)",
              0.15 <= aspect <= 0.40, f"{aspect:.3f} box={res['front']}")
        check("正面立绘窗口贴住宽段右缘(即紧邻特写的那一具)",
              bool(res["boxes"]) and fx1 == max(b[2] for b in res["boxes"] if (b[2] - b[0]) / W > 0.30),
              f"front.x1={fx1} wide_edges={[b[2] for b in res['boxes'] if (b[2]-b[0])/W>0.30]}")
        check("胸像参考存在(锁脸用)", res["bust"] is not None, res["bust"])
        if res["bust"]:
            check("胸像在正面立绘左侧(不被裁片重叠)",
                  res["bust"][2] <= fx0 + 2, f"bust.x1={res['bust'][2]} front.x0={fx0}")
        # 关键：裁给 Ref2VA 的窗口里不能含任何侧/背立绘 —— 这正是"倒着走"的来源
        tails = [b for b in res["boxes"]
                 if b[0] >= fx1 - 4 and (b[3] - b[1]) / H >= 0.80 and b != res["front"]]
        check("裁出的窗口不含侧/背立绘(它们不在 front 窗内)",
              all(b[0] >= fx1 for b in tails), f"tail_boxes={tails} front.x1={fx1}")
        check("返回给 Ref2VA 的参考只有 2 张(胸像+正面立绘)",
              res["bust"] is not None and res["views"] == 4, f"views={res['views']}")

    # 2) 反例：场景图不得被当成设定板
    for name in ("@图3_1.png", "@图4_1.png", "@图10_1.png", "@图22_1.png"):
        im = load(name)
        if im is None:
            check(f"{name} 可读", False, "缺失")
            continue
        check(f"{name} 不被误判成设定板(保持原样)", locate_sheet_panels(im) is None,
              locate_sheet_panels(im))

    print()
    if FAIL:
        print("FAILED %d / %d" % (len(FAIL), len(FAIL) + len(PASS)))
        for f in FAIL:
            print("  - " + f)
        return 1
    print("全部通过 (%d 条 v14.378 参考拼版切版自检)" % len(PASS))
    return 0


if __name__ == "__main__":
    sys.exit(main())

