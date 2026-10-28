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
                    ["Green screen", "Blue screen", "Pure black", "Pure white"],
                    {"default": "Green screen",
                     "tooltip": "Backdrop color used during generation: green/blue for characters/props; pure black for VFX fire/sparks/smoke (luma key); pure white for ink/silhouette/dark smoke (Dark-on-White). Legacy Chinese aliases (绿幕/蓝幕/纯黑/纯白) are accepted at runtime."},
                ),
                "matte_preset": (
                    ["Balanced (hair/smoke)", "Hard edges", "Fire on green", "Dark on white"],
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

    def _checkerboard(self, rgb, alpha, tile=8):
        """把 RGBA 合成到棋盘格透明底上做预览。"""
        b, c, h, w = rgb.shape
        yy = torch.arange(h, device=rgb.device).view(-1, 1)
        xx = torch.arange(w, device=rgb.device).view(1, -1)
        chk = ((yy // tile + xx // tile) % 2).float()  # (H,W)
        bg = chk.view(1, 1, h, w).repeat(b, 1, 1, 1) * 0.45 + 0.10
        comp = rgb * alpha + bg * (1.0 - alpha)
        return _clamp01(comp)

    def key(self, images, backdrop_color, matte_preset, key_strength,
            clip_white, shadow_retention, fill_holes, edge_softness,
            edge_choke, de_spill, keep_mask, mask=None):
        rgb = _to_hw_batch(images).to(images.device)
        b = rgb.shape[0]

        if keep_mask and mask is not None:
            if mask.dim() == 2:
                mask = mask.unsqueeze(0).unsqueeze(0)
            elif mask.dim() == 3:
                mask = mask.unsqueeze(1)
            m = mask.float()
            m = F.interpolate(m, size=(rgb.shape[2], rgb.shape[3]),
                              mode="bilinear", align_corners=False)
            alpha = _clamp01(m).repeat(b, 1, 1, 1)
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
        preview = self._checkerboard(rgb, alpha).permute(0, 2, 3, 1)

        frames = int(rgba.shape[0])
        print(f"[BSAI H3 TransparentKey] {backdrop_color} / {matte_preset}: "
              f"{frames} 帧 -> RGBA+Matte+预览 (alpha 均值 "
              f"{float(alpha.mean()) * 100:.1f}%)")
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
                     "RGBA PNG Sequence (.png)"],
                    {"default": "ProRes 4444 (.mov)",
                     "tooltip": "Export format: ProRes 4444 = 12-bit true-alpha QuickTime (editing software imports directly, preferred); WebM VP9 = alpha-bearing WebM (web/H5, requires FFmpeg libvpx-vp9, node will error clearly if unavailable); RGBA PNG Sequence = lossless per-frame transparent PNG (compositing preferred)."},
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
        """(B,H,W,4) float -> numpy uint8 (B,H,W,4)。"""
        im = images_rgba.detach().float().clamp(0.0, 1.0).cpu().numpy()
        return (im * 255.0 + 0.5).astype(np.uint8)

    def _audio_to_int16(self, audio):
        wf = audio["waveform"].float()          # (B, ch, samples)
        sr = int(audio["sample_rate"])
        if wf.dim() == 2:
            wf = wf.unsqueeze(0)
        data = wf.mean(dim=1) if wf.shape[1] > 1 else wf[:, 0]   # 混单声道
        mono = data[0].cpu().numpy()
        return (np.clip(mono, -1.0, 1.0) * 32767).astype(np.int16), sr

    def _write_mov_prores(self, path, frames_u8, fps, audio):
        import av
        container = av.open(path, "w")
        # v14.240: profile 经 encoder options 显式传给 avcodec_open2。
        # 旧写法 `vstream.codec_context.profile = "4444"` 对部分 PyAV/ffmpeg 组合
        # 赋值不生效（被 try/except 静默吞），于是填默认 profile(hq) + pix_fmt
        # yuva444p10le 的组合非法 -> avcodec_open2("prores", {}) 返回 22 (EINVAL)。
        # options 里的 profile 与下面的 pix_fmt 构成合法组合 (4444 <-> yuva444p10le)。
        vstream = container.add_stream("prores", rate=fps, options={"profile": "4444"})
        vstream.width = frames_u8.shape[2]
        vstream.height = frames_u8.shape[1]
        vstream.pix_fmt = "yuva444p10le"
        if audio is not None:
            adata, sr = self._audio_to_int16(audio)
            astream = container.add_stream("pcm_s16le", rate=sr)
            astream.layout = "mono"
        for i in range(frames_u8.shape[0]):
            fr = av.VideoFrame.from_ndarray(frames_u8[i], format="rgba")
            try:
                fr = fr.reformat(width=frames_u8.shape[2], height=frames_u8.shape[1],
                                 format="yuva444p10le")
            except Exception:
                fr = fr.reformat(width=frames_u8.shape[2], height=frames_u8.shape[1],
                                 format="yuva444p")
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

    def _write_webm_vp9(self, path, frames_u8, fps, audio):
        import av
        container = av.open(path, "w")
        vstream = container.add_stream("libvpx-vp9", rate=fps)
        vstream.width = frames_u8.shape[2]
        vstream.height = frames_u8.shape[1]
        vstream.pix_fmt = "yuva420p"     # WebM VP9 带 Alpha 的唯一格式
        if audio is not None:
            adata, sr = self._audio_to_int16(audio)
            astream = container.add_stream("libopus", rate=sr)
            astream.layout = "mono"
        for i in range(frames_u8.shape[0]):
            fr = av.VideoFrame.from_ndarray(frames_u8[i], format="rgba")
            fr = fr.reformat(width=frames_u8.shape[2], height=frames_u8.shape[1],
                             format="yuva420p")
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

    def _write_png_sequence(self, dir_path, frames_u8, prefix):
        from PIL import Image
        paths = []
        n = frames_u8.shape[0]
        width = len(str(n))
        for i in range(n):
            p = os.path.join(dir_path, f"{prefix}_{i:0{width}d}.png")
            Image.fromarray(frames_u8[i], "RGBA").save(p)
            paths.append(p)
        return paths

    def _write_preview_mp4(self, path, frames_u8, fps):
        """棋盘格合成预览（h264 无 Alpha，仅供快速检查）。"""
        import av
        b, h, w, _ = frames_u8.shape
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
        for i in range(b):
            rgb = frames_u8[i][..., :3].astype(np.float32) / 255.0
            a = frames_u8[i][..., 3:4].astype(np.float32) / 255.0
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
        frames_u8 = self._frames_to_uint8(images_rgba)
        fps = max(1, int(fps))

        safe = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", str(filename_prefix)) or "h3_transparent"
        if format.startswith("ProRes"):
            fpath = os.path.join(alpha_dir, f"{safe}.mov")
            self._write_mov_prores(fpath, frames_u8, fps, audio)
        elif format.startswith("WebM"):
            fpath = os.path.join(alpha_dir, f"{safe}.webm")
            self._write_webm_vp9(fpath, frames_u8, fps, audio)
        else:
            fpath = os.path.join(alpha_dir, f"{safe}_%04d.png")
            paths = self._write_png_sequence(alpha_dir, frames_u8, safe)
            fpath = paths[0] if paths else fpath

        preview_path = os.path.join(prev_dir, f"{safe}_preview.mp4")
        try:
            self._write_preview_mp4(preview_path, frames_u8, fps)
        except Exception as e:
            preview_path = ""
            print(f"[BSAI H3 SaveTransparentVideo] 预览生成失败（不影响 alpha 产物）: {e}")

        b = frames_u8.shape[0]
        dur = b / fps
        print(f"[BSAI H3 SaveTransparentVideo] {format} 已导出: {fpath} "
              f"({b} 帧, {dur:.1f}s @ {fps}fps, 音频={'合入' if audio is not None else '无'})")
        print(f"[BSAI H3 SaveTransparentVideo] 目录: {sub} (alpha/ + preview/)")

        # 预览图输出（棋盘格合成首帧->全帧）
        preview_imgs = []
        for i in range(b):
            rgb = frames_u8[i][..., :3].astype(np.float32) / 255.0
            a = frames_u8[i][..., 3:4].astype(np.float32) / 255.0
            yy = np.arange(frames_u8.shape[1]).reshape(-1, 1)
            xx = np.arange(frames_u8.shape[2]).reshape(1, -1)
            chk = ((yy // 8 + xx // 8) % 2).astype(np.float32) * 0.45 + 0.10
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
