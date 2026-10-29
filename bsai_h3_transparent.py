# -*- coding: utf-8 -*-
"""
BSAI H3 透明视频管道 / H3 Transparent Video Pipeline (v14.233)
==============================================================
按 B站教程《在 ComfyUI 中使用 MiniMax-H3 轻松制作透明视频》(BV1arJX69E7L,
SatoDive/Minimax-H3-Transparent-Video 思路) 为电影工厂落地的两个节点：

  * BSAI_H3_TransparentKey    —— 透明视频抠像台（Matte 预设 + 边缘精修 + 去溢色）
  * BSAI_H3_SaveTransparentVideo —— 透明视频导出（ProRes 4444 真 Alpha /
                                   WebM VP9 / RGBA PNG 序列）

管线原理（与教程一致）：
  ① 电影工厂主节点在"纯色背景（绿幕/蓝幕/纯黑）"上生成 H3 视频片段；
  ② BSAI_H3_TransparentKey 把纯色背景一键抠成 Alpha（Matte），并做
     Edges 边缘柔化/choke/去溢色（de-spill）精修；
  ③ BSAI_H3_SaveTransparentVideo 输出带真实 Alpha 通道的专业格式
     （ProRes 4444 .mov / WebM VP9 / RGBA PNG 序列），
     保存到 output/H3_transparent_video/<生成子文件夹>/alpha/ + preview/，
     可直接拖入 PR / AE / DaVinci / Final Cut。

实现依赖：torch（已随 ComfyUI）、PyAV（av）、numpy、Pillow —— 全部为
ComfyUI 自带依赖，无需额外安装（与 SatoDive 原版节点同款依赖集）。
"""

import os
import re
import datetime
import numpy as np
import torch
import torch.nn.functional as F

try:
    import folder_paths
except Exception:  # 离线自检环境（enum probe）没有 ComfyUI 时兜底
    folder_paths = None


# ----------------------------------------------------------------------------
# 小工具 / shared helpers
# ----------------------------------------------------------------------------

def _clamp01(t):
    return torch.clamp(t, 0.0, 1.0)


def _smoothstep(edge0, edge1, x):
    """Hermite smoothstep; x/edge may be tensors. Out-of-range clamps to 0/1."""
    t = _clamp01((x - edge0) / (edge1 - edge0 + 1e-8))
    return t * t * (3.0 - 2.0 * t)


def _to_hw_batch(images):
    """IMAGE (B,H,W,C) float 0..1 -> tensor (B,C,H,W) float32, values clamped."""
    if images.dim() == 3:
        images = images.unsqueeze(0)
    im = images.permute(0, 3, 1, 2).float()
    if im.shape[1] == 1:  # 灰度图 -> RGB
        im = im.repeat(1, 3, 1, 1)
    return _clamp01(im)


def _morph_pool(x, radius, mode="dilate"):
    """按像素半径对 alpha 做膨胀/腐蚀（max_pool / min_pool）。"""
    if radius <= 0:
        return x
    k = radius * 2 + 1
    pad = radius
    if mode == "dilate":
        return F.max_pool2d(x, kernel_size=k, stride=1, padding=pad)
    # 腐蚀 = 对 -x 膨胀后取负
    return -F.max_pool2d(-x, kernel_size=k, stride=1, padding=pad)


def _blur_alpha(x, sigma):
    """alpha 高斯/均值模糊，sigma 为像素半径（整数）。"""
    if sigma <= 0:
        return x
    k = sigma * 2 + 1
    # 两级平均池化近似高斯（半径 sigma）
    out = x
    for _ in range(2):
        out = F.avg_pool2d(out, kernel_size=k, stride=1,
                           padding=sigma, count_include_pad=False)
    return out


def _rgb_to_ycbcr(rgb):
    """(B,3,H,W) -> (Y, Cb, Cr) 各 (B,1,H,W)，BT.601 全范围近似。"""
    r, g, b = rgb[:, 0:1], rgb[:, 1:2], rgb[:, 2:3]
    y = 0.299 * r + 0.587 * g + 0.114 * b
    cb = -0.169 * r - 0.331 * g + 0.500 * b
    cr = 0.500 * r - 0.419 * g - 0.081 * b
    return y, cb, cr


# ----------------------------------------------------------------------------
# 节点 A：透明视频抠像台 / Transparent Keying Studio
# ----------------------------------------------------------------------------

class BSAI_H3_TransparentKey:
    """把纯色背景（绿幕/蓝幕/纯黑/纯白）上的 H3 视频帧一键抠成透明视频。

    输出 straight alpha 的 RGBA IMAGE、Matte 灰度图、棋盘格预览图。
    可直接接 BSAI_H3_SaveTransparentVideo 导出 ProRes 4444/WebM/PNG。
    """

    CATEGORY = "BSAI/H3 Film Factory"
    RETURN_TYPES = ("IMAGE", "IMAGE", "IMAGE")
    RETURN_NAMES = ("images_rgba", "matte", "images_preview")
    FUNCTION = "key"
    DESCRIPTION = ("H3 透明视频抠像台：绿幕/蓝幕/纯黑/纯白背景一键抠像 -> straight "
                   "alpha RGBA + Matte + 棋盘格预览。Matte 预设 + 强度/白电平/阴影保留/"
                   "补洞 + 边缘柔化/收缩/去溢色精修。输出可直接接透明视频导出节点。")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "H3 生成的视频帧（电影工厂主节点 images 输出，B,H,W,3 float 0..1）"}),
                "backdrop_color": (
                    ["Green screen", "Blue screen", "Pure black", "Pure white",
                     "绿幕 Green", "蓝幕 Blue", "纯黑 Pure Black", "纯白 Pure White"],
                    {"default": "Green screen",
                     "tooltip": "Backdrop color used during generation: green/blue for characters/props; pure black for VFX fire/sparks/smoke (luma key); pure white for ink/silhouette/dark smoke (Dark-on-White). Legacy Chinese aliases (绿幕/蓝幕/纯黑/纯白) are accepted at runtime."},
                ),
                "matte_preset": (
                    ["Balanced (hair/smoke)", "Hard edges", "Fire on green", "Dark on white",
                     "平衡（毛发/烟雾）Balanced", "硬边 Hard edges", "火焰 Fire on green", "暗黑转白 Dark on white"],
                    {"default": "Balanced (hair/smoke)",
                     "tooltip": "One-click preset: Balanced=default tuning; Hard edges=tighten edges; Fire on green=green screen + stronger despill; Dark on white=white-screen dark-subject mode. Legacy Chinese aliases accepted at runtime."},
                ),
                "key_strength": (
                    "FLOAT", {"default": 0.5, "min": 0.05, "max": 1.0, "step": 0.05,
                              "tooltip": "抠像强度：越大保留主体越多（毛发/烟雾更完整），越小抠得越狠（背景更彻底透明）。"},
                ),
                "clip_white": (
                    "FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05,
                              "tooltip": "白电平钳制：把接近不透明的高 alpha 拉满（去除残留灰雾/半透明罩），0=关闭。"},
                ),
                "shadow_retention": (
                    "FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05,
                              "tooltip": "阴影保留：把绿幕/蓝幕上的深色投影区域按比例拉回不透明（保留脚底阴影），0=关闭。"},
                ),
                "fill_holes": (
                    "INT", {"default": 2, "min": 0, "max": 12, "step": 1,
                            "tooltip": "补洞半径（像素）：对主体内部被误抠的孔洞（如透出的背景色）做闭运算填充，0=关闭。"},
                ),
                "edge_softness": (
                    "INT", {"default": 1, "min": 0, "max": 8, "step": 1,
                            "tooltip": "边缘柔化半径（像素）：毛发/烟雾建议 1-3，硬边素材建议 0。"},
                ),
                "edge_choke": (
                    "FLOAT", {"default": 0.0, "min": -1.0, "max": 1.0, "step": 0.05,
                              "tooltip": "边缘收缩（负值收紧去残留绿边）/扩张（正值保住细节），0=不变。"},
                ),
                "de_spill": (
                    "FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05,
                              "tooltip": "去溢色强度：消除主体边缘残留的背景色光晕（绿边/蓝边），只作用于半透明边缘像素，不碰不透明主体。"},
                ),
                "keep_mask": (
                    "BOOLEAN", {"default": False,
                                "tooltip": "启用后忽略背景抠像，直接使用下方 mask 输入作为 Alpha（适用于自带蒙版/透明底的参考素材）。"},
                ),
            },
            "optional": {
                "mask": ("MASK", {"tooltip": "可选蒙版：keep_mask=True 时直接用该蒙版作为 Alpha（B,H,W 或 H,W float 0..1）。"}),
                "preview_side": ("INT", {"default": 512, "min": 128, "max": 2048, "step": 64,
                                        "tooltip": "棋盘格预览图短边上限（像素）。预览仅供检查，无需全分辨率；H3 全片 2K 视频（数百帧）时保持默认可大幅省内存。0=禁用预览降采样（不推荐）。"}),
                "matte_side": ("INT", {"default": 512, "min": 0, "max": 2048, "step": 64,
                                      "tooltip": "Matte 灰度图短边上限（像素）。0=全分辨率（需把 matte 当精确蒙版导出时使用，内存开销大）。默认降采样到 512，全分辨率 Alpha 仍由 images_rgba 的 A 通道提供，导出不受影响。"}),
            },
        }

    def _key_alpha(self, rgb, backdrop_color, strength, clip_white,
                   shadow_retention, preset):
        """返回 (alpha (B,1,H,W) 0..1, spill_map (B,1,H,W))。"""
        y, cb, cr = _rgb_to_ycbcr(rgb)
        b_ch = rgb.shape[1]

        if backdrop_color.startswith("绿幕") or backdrop_color.startswith("蓝幕"):
            if backdrop_color.startswith("绿幕"):
                key = rgb[:, 1:2] - torch.maximum(rgb[:, 0:1], rgb[:, 2:3])
            else:
                key = rgb[:, 2:3] - torch.maximum(rgb[:, 0:1], rgb[:, 1:2])
            # strength 越大 -> 阈值越低 -> 保留主体更多
            lo = 0.42 - 0.30 * strength
            hi = 0.42 + 0.28 * (1.0 - strength)
            alpha = 1.0 - _smoothstep(lo, hi, key)
            spill_ch = 1 if backdrop_color.startswith("绿幕") else 2
            spill = torch.maximum(rgb[:, spill_ch:spill_ch + 1]
                                  - torch.maximum(rgb[:, 0:1], rgb[:, 2:3] if spill_ch == 1 else rgb[:, 1:2]),
                                  torch.zeros_like(key))
        elif backdrop_color.startswith("纯黑"):
            # 亮度抠像：亮部（火焰/火花/高亮烟雾）不透明，纯黑背景透明
            lo = 0.10 + 0.22 * (1.0 - strength)
            hi = 0.10 + 0.22 * (1.0 - strength) + 0.30
            alpha = _smoothstep(lo, hi, y)
            spill = torch.zeros_like(y)
        else:  # 纯白
            # 亮度反抠：暗部（墨水/剪影/深色烟雾）不透明，纯白背景透明
            lo = 0.55 + 0.25 * (1.0 - strength)
            hi = lo + 0.30
            alpha = 1.0 - _smoothstep(lo, hi, y)
            spill = torch.zeros_like(y)

        # 白电平钳制：接近不透明的高 alpha 拉满
        if clip_white > 0.0:
            alpha = _smoothstep(1.0 - clip_white, 1.0, alpha)
        # 阴影保留：深色区域按强度拉回不透明
        if shadow_retention > 0.0:
            shadow_floor = shadow_retention * (1.0 - y)
            alpha = torch.maximum(alpha, _clamp01(shadow_floor))
        # 预设微调
        if "硬边" in preset:
            pass  # 硬边由 edge 参数控制，这里不额外改 alpha
        if "火焰" in preset:
            alpha = torch.maximum(alpha, _clamp01(y))  # 火焰主体强化
        return _clamp01(alpha), _clamp01(spill)

    def _apply_edges(self, alpha, fill_holes, softness, choke):
        if fill_holes > 0:
            # 闭运算：先膨胀后腐蚀 -> 填主体内部小孔
            alpha = _morph_pool(alpha, fill_holes, "dilate")
            alpha = _morph_pool(alpha, fill_holes, "erode")
        if choke != 0.0:
            r = int(round(abs(choke) * 6.0))
            if r > 0:
                alpha = _morph_pool(alpha, r, "erode" if choke < 0 else "dilate")
        if softness > 0:
            alpha = _blur_alpha(alpha, softness)
        return _clamp01(alpha)

    def _de_spill_rgb(self, rgb, alpha, spill, de_spill, backdrop_color):
        if de_spill <= 0.0:
            return rgb
        # 只在半透明边缘生效：权重 = (1 - alpha)^1.2
        edge_w = torch.pow(_clamp01(1.0 - alpha), 1.2).detach()
        if backdrop_color.startswith("绿幕"):
            g = rgb[:, 1:2] - de_spill * edge_w * spill
            rgb = torch.cat([rgb[:, 0:1], _clamp01(g), rgb[:, 2:3]], dim=1)
        elif backdrop_color.startswith("蓝幕"):
            b = rgb[:, 2:3] - de_spill * edge_w * spill
            rgb = torch.cat([rgb[:, 0:1], rgb[:, 1:2], _clamp01(b)], dim=1)
        return rgb

    def _checkerboard(self, rgb, alpha, tile=8, max_side=512):
        """把 RGBA 合成到棋盘格透明底上做预览（按 max_side 降采样省内存）。"""
        b, c, h, w = rgb.shape
        if max_side and max_side > 0 and max(h, w) > max_side:
            scale = max_side / float(max(h, w))
            nh, nw = max(1, int(round(h * scale))), max(1, int(round(w * scale)))
            rgb_s = F.interpolate(rgb, size=(nh, nw), mode="bilinear", align_corners=False)
            alpha_s = F.interpolate(alpha, size=(nh, nw), mode="bilinear", align_corners=False)
        else:
            rgb_s, alpha_s = rgb, alpha
        bh, bw = rgb_s.shape[2], rgb_s.shape[3]
        yy = torch.arange(bh, device=rgb_s.device).view(-1, 1)
        xx = torch.arange(bw, device=rgb_s.device).view(1, -1)
        chk = ((yy // tile + xx // tile) % 2).float()  # (H,W)
        bg = chk.view(1, 1, bh, bw).repeat(b, 1, 1, 1) * 0.45 + 0.10
        comp = rgb_s * alpha_s + bg * (1.0 - alpha_s)
        return _clamp01(comp)

    @staticmethod
    def _downsample_hw3(t_hwc, side):
        """t_hwc: (B,H,W,3) -> 短边 <= side 的 (B,H',W',3)；side<=0 原样。"""
        if not side or side <= 0:
            return t_hwc
        b, h, w, c = t_hwc.shape
        if max(h, w) <= side:
            return t_hwc
        scale = side / float(max(h, w))
        nh, nw = max(1, int(round(h * scale))), max(1, int(round(w * scale)))
        t_chw = t_hwc.permute(0, 3, 1, 2)
        t_s = F.interpolate(t_chw, size=(nh, nw), mode="bilinear", align_corners=False)
        return t_s.permute(0, 2, 3, 1).contiguous()

    def key(self, images, backdrop_color, matte_preset, key_strength,
            clip_white, shadow_retention, fill_holes, edge_softness,
            edge_choke, de_spill, keep_mask, mask=None,
            preview_side=512, matte_side=512):
        rgb_full = _to_hw_batch(images).to(images.device)
        b, c, h, w = rgb_full.shape

        # ---- 分块预算：控制峰值内存/显存 ----
        # 每块帧数上限：目标每块中间张量峰值不超过 ~1.5GB。
        # H,W 越大块越小；按输入所在设备分别给预算（CPU 保守 1GB，GPU 2GB）。
        px = max(1, h * w)
        is_cuda = rgb_full.device.type == "cuda"
        block_budget = (2 if is_cuda else 1) * (1024 ** 3)
        # 每帧主要副本：rgb(3ch)+alpha(1ch)+spill(1ch)+rgba(4ch)+matte(3ch)+preview(3ch) ≈ 15ch
        frame_bytes = px * 15 * 4
        chunk = max(1, min(b, block_budget // max(1, frame_bytes)))
        if chunk < 1:
            chunk = 1

        rgba_parts, matte_parts, prev_parts = [], [], []
        total_alpha_mean = 0.0
        for s in range(0, b, chunk):
            e = min(b, s + chunk)
            rgb = rgb_full[s:e]
            if keep_mask and mask is not None:
                if mask.dim() == 2:
                    m = mask.unsqueeze(0).unsqueeze(0).float()
                elif mask.dim() == 3:
                    m = mask.unsqueeze(1).float()
                else:
                    m = mask.float()
                m = F.interpolate(m, size=(h, w), mode="bilinear", align_corners=False)
                if m.shape[0] == 1 and (e - s) > 1:
                    m = m.expand(e - s, -1, -1, -1)
                alpha = _clamp01(m)
                spill = torch.zeros_like(rgb[:, 0:1])
            else:
                alpha, spill = self._key_alpha(
                    rgb, backdrop_color, float(key_strength),
                    float(clip_white), float(shadow_retention), matte_preset)
                if "硬边" in matte_preset:
                    edge_softness = min(int(edge_softness), 1)
                    edge_choke = float(edge_choke) + 0.15
                elif "火焰" in matte_preset:
                    de_spill = min(float(de_spill) + 0.25, 1.0)
                    edge_softness = int(edge_softness) + 1

            alpha = self._apply_edges(alpha, int(fill_holes),
                                      int(edge_softness), float(edge_choke))
            rgb = self._de_spill_rgb(rgb, alpha, spill, float(de_spill),
                                     backdrop_color)

            rgba = torch.cat([rgb, alpha], dim=1).permute(0, 2, 3, 1)
            matte = alpha.permute(0, 2, 3, 1).repeat(1, 1, 1, 3)
            preview = self._checkerboard(rgb, alpha, max_side=int(preview_side)).permute(0, 2, 3, 1)
            matte = self._downsample_hw3(matte, int(matte_side or 0))

            rgba_parts.append(rgba)
            matte_parts.append(matte)
            prev_parts.append(preview)
            total_alpha_mean += float(alpha.mean()) * (e - s)

        rgba = torch.cat(rgba_parts, dim=0)
        matte = torch.cat(matte_parts, dim=0)
        preview = torch.cat(prev_parts, dim=0)

        frames = int(rgba.shape[0])
        print(f"[BSAI H3 TransparentKey] {backdrop_color} / {matte_preset}: "
              f"{frames} 帧 (chunk={chunk}) -> RGBA+Matte+预览 (alpha 均值 "
              f"{total_alpha_mean / max(1, frames) * 100:.1f}%)")
        return (rgba, matte, preview)

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")


# ----------------------------------------------------------------------------
# 节点 B：透明视频导出 / Transparent Video Writer
# ----------------------------------------------------------------------------

class BSAI_H3_SaveTransparentVideo:
    """把 RGBA 视频帧导出为带真实 Alpha 通道的专业格式。

    输出目录（与教程一致）：output/H3_transparent_video/<子文件夹>/alpha/*.mov|webm|png
    + preview/*.mp4（棋盘格预览，方便快速检查）。
    """

    CATEGORY = "BSAI/H3 Film Factory"
    RETURN_TYPES = ("STRING", "STRING", "STRING", "IMAGE")
    RETURN_NAMES = ("folder", "alpha_file", "preview_file", "preview_images")
    FUNCTION = "export"
    OUTPUT_NODE = True
    DESCRIPTION = ("透明视频导出：ProRes 4444 (.mov 真 12bit Alpha，PR/AE/DaVinci/FCP "
                   "直接识别 straight alpha) / WebM VP9 (.webm 带 Alpha) / RGBA PNG 序列；"
                   "自动另存棋盘格预览 MP4。")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images_rgba": ("IMAGE", {"tooltip": "RGBA 视频帧（BSAI_H3_TransparentKey 的 images_rgba 输出，B,H,W,4）"}),
                "format": (
                    ["ProRes 4444 (.mov)", "WebM VP9 (.webm)",
                     "RGBA PNG Sequence (.png)",
                     "ProRes 4444 (.mov, 真Alpha)", "WebM VP9 (.webm, Alpha)",
                     "RGBA PNG 序列 (.png)"],
                    {"default": "ProRes 4444 (.mov)",
                     "tooltip": "Export format: ProRes 4444 = 12-bit true-alpha QuickTime (editing software imports directly, preferred); WebM VP9 = alpha-bearing WebM (web/H5, requires FFmpeg libvpx-vp9, node will error clearly if unavailable); RGBA PNG Sequence = lossless per-frame transparent PNG (compositing preferred). Legacy Chinese aliases (ProRes 4444 (.mov, 真Alpha) / RGBA PNG 序列 (.png)) accepted at runtime."},
                ),
                "fps": ("INT", {"default": 24, "min": 1, "max": 60, "step": 1}),
                "filename_prefix": ("STRING", {"default": "h3_transparent",
                                               "tooltip": "输出文件名前缀（自动追加时间戳子文件夹，不覆盖旧产物）。"}),
            },
            "optional": {
                "audio": ("AUDIO", {"tooltip": "可选音频（电影工厂主节点 audios 输出），合入 MOV/WebM。"}),
            },
        }

    def _output_root(self):
        base = folder_paths.get_output_directory() if folder_paths is not None else os.path.join("output")
        return os.path.join(base, "H3_transparent_video")

    def _new_subfolder(self, root, prefix):
        safe = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", str(prefix)) or "h3_transparent"
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        sub = os.path.join(root, f"{stamp}_{safe}")
        alpha_dir = os.path.join(sub, "alpha")
        prev_dir = os.path.join(sub, "preview")
        os.makedirs(alpha_dir, exist_ok=True)
        os.makedirs(prev_dir, exist_ok=True)
        return sub, alpha_dir, prev_dir

    # ---- PyAV 写入 ----
    @staticmethod
    def _av_available():
        try:
            import av  # noqa: F401
            return True
        except Exception:
            return False

    def _frames_to_uint8(self, images_rgba):
        """(B,H,W,4) float -> numpy uint8 (B,H,W,4)。

        v14.248: 分批 + torch 操作避免 numpy 中间临时数组。
        原实现: im(float32 22.4GiB) → im*255.0(临时 22.4GiB) → astype(5.6GiB) = 峰值 ~50GiB
        现实现: 分批 32 帧用 torch 做原地运算，峰值 ≈ 22.4 + 1 + 5.6 = 29GiB
        """
        im = images_rgba.detach().float().clamp(0.0, 1.0)
        if im.device.type != "cpu":
            im = im.cpu()
        B = im.shape[0]
        # 预先分配输出缓冲区，避免 concatenate 再分配
        out = np.empty((B, im.shape[1], im.shape[2], im.shape[3]), dtype=np.uint8)
        chunk = max(1, min(B, 32))
        for s in range(0, B, chunk):
            e = min(s + chunk, B)
            out[s:e] = (im[s:e] * 255.0 + 0.5).to(torch.uint8).numpy()
        del im
        return out

    def _iter_frames_uint8(self, images_rgba):
        """逐帧 yield uint8 numpy 数组，内存占用 ≈ 单帧（~8MB）。

        供 write 方法内部流式使用，避免一次性持有全部 frames_u8 数组。
        """
        im = images_rgba.detach().float().clamp(0.0, 1.0)
        if im.device.type != "cpu":
            im = im.cpu()
        for i in range(im.shape[0]):
            yield (im[i] * 255.0 + 0.5).to(torch.uint8).numpy()

    def _audio_to_int16(self, audio):
        wf = audio["waveform"].float()          # (B, ch, samples)
        sr = int(audio["sample_rate"])
        if wf.dim() == 2:
            wf = wf.unsqueeze(0)
        data = wf.mean(dim=1) if wf.shape[1] > 1 else wf[:, 0]   # 混单声道
        mono = data[0].cpu().numpy()
        return (np.clip(mono, -1.0, 1.0) * 32767).astype(np.int16), sr

    def _write_mov_prores(self, path, images_rgba, fps, audio):
        """v14.248: 接收原始 torch tensor (B,H,W,4)，流式逐帧转 uint8 写入。"""
        import av
        container = av.open(path, "w")
        try:
            vstream = container.add_stream("prores_ks", rate=fps, options={"profile": "4444"})
        except Exception:
            vstream = container.add_stream("prores", rate=fps)
            try:
                vstream.codec_context.profile = "4444"
            except Exception:
                pass
        vstream.width = images_rgba.shape[2]
        vstream.height = images_rgba.shape[1]
        vstream.pix_fmt = "yuva444p10le"
        w, h = vstream.width, vstream.height
        if audio is not None:
            adata, sr = self._audio_to_int16(audio)
            astream = container.add_stream("pcm_s16le", rate=sr)
            astream.layout = "mono"
        for frame_u8 in self._iter_frames_uint8(images_rgba):
            fr = av.VideoFrame.from_ndarray(frame_u8, format="rgba")
            try:
                fr = fr.reformat(width=w, height=h, format="yuva444p10le")
            except Exception:
                fr = fr.reformat(width=w, height=h, format="yuva444p")
            for pkt in vstream.encode(fr):
                container.mux(pkt)
        for pkt in vstream.encode():
            container.mux(pkt)
        if audio is not None:
            af = av.AudioFrame.from_ndarray(adata.reshape(1, -1), format="s16", layout="mono")
            af.sample_rate = sr
            for pkt in astream.encode(af):
                container.mux(pkt)
            for pkt in astream.encode():
                container.mux(pkt)
        container.close()

    def _write_webm_vp9(self, path, images_rgba, fps, audio):
        """v14.248: 接收原始 torch tensor (B,H,W,4)，流式逐帧转 uint8 写入。"""
        import av
        container = av.open(path, "w")
        vstream = container.add_stream("libvpx-vp9", rate=fps)
        vstream.width = images_rgba.shape[2]
        vstream.height = images_rgba.shape[1]
        vstream.pix_fmt = "yuva420p"     # WebM VP9 带 Alpha 的唯一格式
        w, h = vstream.width, vstream.height
        if audio is not None:
            adata, sr = self._audio_to_int16(audio)
            astream = container.add_stream("libopus", rate=sr)
            astream.layout = "mono"
        for frame_u8 in self._iter_frames_uint8(images_rgba):
            fr = av.VideoFrame.from_ndarray(frame_u8, format="rgba")
            fr = fr.reformat(width=w, height=h, format="yuva420p")
            for pkt in vstream.encode(fr):
                container.mux(pkt)
        for pkt in vstream.encode():
            container.mux(pkt)
        if audio is not None:
            af = av.AudioFrame.from_ndarray(adata.reshape(1, -1), format="s16", layout="mono")
            af.sample_rate = sr
            for pkt in astream.encode(af):
                container.mux(pkt)
            for pkt in astream.encode():
                container.mux(pkt)
        container.close()
        # 读回校验：部分 FFmpeg 构建的 libvpx-vp9 不支持 yuva420p，会静默降级为
        # 无 Alpha 的 yuv420p —— 禁止产出"假透明"文件，此时删除并明确报错。
        probe = av.open(path)
        got_fmt = probe.streams.video[0].codec_context.pix_fmt or ""
        probe.close()
        if "yuva" not in got_fmt:
            try:
                os.remove(path)
            except Exception:
                pass
            raise RuntimeError(
                "BSAI_H3_SaveTransparentVideo: 当前 FFmpeg 构建的 VP9 编码器不支持 "
                "Alpha 通道（libvpx-vp9 需 libvpx>=1.10，产出被静默降级为 yuv420p）。"
                "请改用 'ProRes 4444 (.mov, 真Alpha)' 或 'RGBA PNG 序列 (.png)'。")

    def _write_png_sequence(self, dir_path, images_rgba, prefix):
        """v14.248: 接收原始 torch tensor (B,H,W,4)，流式逐帧转 uint8 写 PNG。"""
        from PIL import Image
        B = images_rgba.shape[0]
        width = len(str(B))
        paths = []
        for i, frame_u8 in enumerate(self._iter_frames_uint8(images_rgba)):
            p = os.path.join(dir_path, f"{prefix}_{i:0{width}d}.png")
            Image.fromarray(frame_u8, "RGBA").save(p)
            paths.append(p)
        return paths

    def _write_preview_mp4(self, path, images_rgba, fps):
        """v14.248: 接收原始 torch tensor (B,H,W,4)，流式逐帧棋盘格合成预览。"""
        import av
        b, h, w, _ = images_rgba.shape
        tile = 8
        yy = np.arange(h).reshape(-1, 1)
        xx = np.arange(w).reshape(1, -1)
        chk = ((yy // tile + xx // tile) % 2).astype(np.float32) * 0.45 + 0.10
        container = av.open(path, "w")
        vstream = container.add_stream("libx264", rate=fps)
        vstream.width = w
        vstream.height = h
        vstream.pix_fmt = "yuv420p"
        vstream.options = {"crf": "18", "preset": "medium"}
        for frame_u8 in self._iter_frames_uint8(images_rgba):
            rgb = frame_u8[..., :3].astype(np.float32) / 255.0
            a = frame_u8[..., 3:4].astype(np.float32) / 255.0
            comp = np.clip(rgb * a + chk[..., None] * (1.0 - a), 0.0, 1.0)
            fr = av.VideoFrame.from_ndarray((comp * 255.0 + 0.5).astype(np.uint8), format="rgb24")
            fr = fr.reformat(width=w, height=h, format="yuv420p")
            for pkt in vstream.encode(fr):
                container.mux(pkt)
        for pkt in vstream.encode():
            container.mux(pkt)
        container.close()

    def export(self, images_rgba, format, fps, filename_prefix, audio=None):
        if images_rgba.shape[-1] < 4:
            raise ValueError("BSAI_H3_SaveTransparentVideo: 输入不是 RGBA（通道数 < 4），"
                             "请先接 BSAI_H3_TransparentKey 的 images_rgba 输出。")
        if not self._av_available():
            raise RuntimeError("PyAV(av) 不可用：请确认 ComfyUI 环境已安装 PyAV。")

        root = self._output_root()
        sub, alpha_dir, prev_dir = self._new_subfolder(root, filename_prefix)
        fps = max(1, int(fps))
        b = images_rgba.shape[0]

        # v14.248: 不再一次性转换全部 frames_u8（峰值内存 ~50GiB），
        # 改由各 write 方法内部通过 _iter_frames_uint8 流式逐帧处理。
        safe = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", str(filename_prefix)) or "h3_transparent"
        if format.startswith("ProRes"):
            fpath = os.path.join(alpha_dir, f"{safe}.mov")
            self._write_mov_prores(fpath, images_rgba, fps, audio)
        elif format.startswith("WebM"):
            fpath = os.path.join(alpha_dir, f"{safe}.webm")
            self._write_webm_vp9(fpath, images_rgba, fps, audio)
        else:
            fpath = os.path.join(alpha_dir, f"{safe}_%04d.png")
            paths = self._write_png_sequence(alpha_dir, images_rgba, safe)
            fpath = paths[0] if paths else fpath

        preview_path = os.path.join(prev_dir, f"{safe}_preview.mp4")
        try:
            self._write_preview_mp4(preview_path, images_rgba, fps)
        except Exception as e:
            preview_path = ""
            print(f"[BSAI H3 SaveTransparentVideo] 预览生成失败（不影响 alpha 产物）: {e}")

        dur = b / fps
        print(f"[BSAI H3 SaveTransparentVideo] {format} 已导出: {fpath} "
              f"({b} 帧, {dur:.1f}s @ {fps}fps, 音频={'合入' if audio is not None else '无'})")
        print(f"[BSAI H3 SaveTransparentVideo] 目录: {sub} (alpha/ + preview/)")

        # 预览图输出（棋盘格合成首帧->全帧）
        # v14.248: 同样从 tensor 逐帧取，避免 frames_u8 中间数组
        preview_imgs = []
        _, h, w, _ = images_rgba.shape
        yy = np.arange(h).reshape(-1, 1)
        xx = np.arange(w).reshape(1, -1)
        chk = ((yy // 8 + xx // 8) % 2).astype(np.float32) * 0.45 + 0.10
        for frame_u8 in self._iter_frames_uint8(images_rgba):
            rgb = frame_u8[..., :3].astype(np.float32) / 255.0
            a = frame_u8[..., 3:4].astype(np.float32) / 255.0
            comp = np.clip(rgb * a + chk[..., None] * (1.0 - a), 0.0, 1.0)
            preview_imgs.append(torch.from_numpy(comp).float())
        preview_out = torch.stack(preview_imgs, dim=0)

        return (sub, fpath, preview_path, preview_out)


NODE_CLASS_MAPPINGS = {
    "BSAI_H3_TransparentKey": BSAI_H3_TransparentKey,
    "BSAI_H3_SaveTransparentVideo": BSAI_H3_SaveTransparentVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "BSAI_H3_TransparentKey": "BSAI H3 透明视频抠像台 / Transparent Keying Studio",
    "BSAI_H3_SaveTransparentVideo": "BSAI H3 透明视频导出 / Transparent Video Writer",
}
