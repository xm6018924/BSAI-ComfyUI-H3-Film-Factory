"""BSAI 电影工厂 HyperVAE 2x —— 解码像素 2× 的视频 VAE 加载（v1.0, 2026-10-23）。

思路来源: T8 系工作流《H3低显存双采放大高分辨率轻松出2K》(BV1aiaL61Eyu)。
与 T8 原版 `comfyui-minimax-h3-audio-T8/h3_t8/hyper_vae_2x.py` 同源实现，
按 BSAI 电影工厂规范命名/注释。不 patch ComfyUI 核心。

核心原理:
  - 权重文件 = 标准 MiniMax H3 视频 VAE(encoder 16× 不变) + 2× 解码头
    (decoder.proj_out 12,288 通道 = 3RGB × 4 phase packed)。
  - 加载后返回标准 VAE 兼容对象: encode 仍 16× (encoder unchanged),
    decode 输出 pixel_shuffle 2× 像素 (latent 32× 几何)。
  - 用途: 渲染管道「双采2K」档 —— 二采 latent 不放大(factor=1.0, 提速),
    解码阶段用本 VAE 直出 2K 像素, 全程只解码一次。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import MethodType

import torch
import torch.nn.functional as F
from safetensors import safe_open

PROJECTION_WEIGHT_SHAPE = (12_288, 2_048)
PROJECTION_BIAS_SHAPE = (12_288,)
RGB_PHASES = 4


def inspect_hyper_vae_2x(path: str | Path) -> dict:
    """在加载 5 GB 前先用 safetensors 头校验, 拒绝不兼容文件。"""
    candidate = Path(path).expanduser().resolve(strict=True)
    if not candidate.is_file() or candidate.suffix.lower() != ".safetensors":
        raise ValueError("请选择 MiniMax H3 HyperVAE 2x 的 .safetensors 文件")
    with safe_open(str(candidate), framework="pt", device="cpu") as weights:
        keys = set(weights.keys())
        required = {
            "decoder.proj_out.weight": PROJECTION_WEIGHT_SHAPE,
            "decoder.proj_out.bias": PROJECTION_BIAS_SHAPE,
            "latents_mean": (24,),
            "latents_std": (24,),
        }
        for key, shape in required.items():
            if key not in keys or tuple(weights.get_slice(key).get_shape()) != shape:
                raise ValueError(f"不是支持的 H3 2x VAE：{key} 形状不匹配")
        if "encoder.down.5.block.0.conv1.weight" not in keys:
            raise ValueError("不是完整的 MiniMax H3 视频 VAE：缺少 encoder")
        metadata = weights.metadata() or {}
    try:
        adapter = json.loads(metadata["minimax_h3_x2_adapter"])
        video = json.loads(metadata["minimax_h3_video_vae"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("缺少 HyperVAE MiniMax 2x 元数据") from exc
    if (adapter.get("version") != 1 or adapter.get("packed_output_channels") != 12
            or adapter.get("pixel_shuffle_factor") != 2
            or adapter.get("encoder_unchanged") is not True
            or video.get("decoder_pixel_shuffle_factor") != 2
            or video.get("packed_decoder_output_channels") != 12):
        raise ValueError("HyperVAE 2x 元数据不符合当前解码合同")
    return {
        "path": str(candidate),
        "size_bytes": candidate.stat().st_size,
        "packed_channels": 12,
        "decode_scale": 2,
        "encode_scale": 16,
        "decode_scale_from_latent": 32,
    }


def pixel_shuffle_h3_images(images: torch.Tensor) -> torch.Tensor:
    """把 [B,T,H,W,12] phase-packed RGB 转成 [B,T,2H,2W,3]。"""
    if images.ndim != 5 or images.shape[-1] != 3 * RGB_PHASES:
        raise ValueError(f"HyperVAE 2x 解码预期 [B,T,H,W,12]，实际 {tuple(images.shape)}")
    batch, frames, height, width, _ = images.shape
    packed = images.permute(0, 1, 4, 2, 3).reshape(batch * frames, 12, height, width)
    rgb = F.pixel_shuffle(packed, upscale_factor=2)
    return rgb.reshape(batch, frames, 3, height * 2, width * 2).permute(0, 1, 3, 4, 2).contiguous()


def _finalize_hyper_pixels(inner, part: torch.Tensor) -> torch.Tensor:
    """保持原生 3 通道 encoder 统计, 解码 12 phase。"""
    if part.shape[1] != 12:
        raise ValueError(f"HyperVAE 解码头必须输出12通道，实际 {part.shape[1]}")
    std = inner.pixel_std.repeat_interleave(RGB_PHASES, dim=1).to(
        device=part.device, dtype=torch.float32
    )
    mean = inner.pixel_mean.repeat_interleave(RGB_PHASES, dim=1).to(
        device=part.device, dtype=torch.float32
    )
    return (part * std).add_(mean).clamp_(0.0, 1.0)


def load_hyper_vae_2x(path: str | Path):
    """返回标准 VAE 兼容对象: 原生 encode + 2x decode。"""
    report = inspect_hyper_vae_2x(path)
    import comfy.ops
    import comfy.sd
    import comfy.utils
    import comfy.model_management as model_management

    state, metadata = comfy.utils.load_torch_file(report["path"], return_metadata=True)
    original_weight = state["decoder.proj_out.weight"]
    original_bias = state["decoder.proj_out.bias"]
    # 用原生形状的 *view* 构建 H3 wrapper（只截取前 3072 通道做形状检查）,
    # 其余权重（含不变的 encoder）走 Comfy 正常 VAE/ModelPatcher 路径。
    # 首次执行前再替换为完整 12288 通道解码头。
    native_shape_state = dict(state)
    native_shape_state["decoder.proj_out.weight"] = original_weight[:3_072]
    native_shape_state["decoder.proj_out.bias"] = original_bias[:3_072]
    vae = HyperVAE2x(sd=native_shape_state, metadata=metadata)
    inner = vae.first_stage_model
    projection = comfy.ops.disable_weight_init.Linear(2_048, 12_288, bias=True)
    projection.load_state_dict(
        {"weight": original_weight, "bias": original_bias},
        strict=True,
        assign=vae.patcher.is_dynamic(),
    )
    projection.to(dtype=vae.vae_dtype).eval()
    inner.decoder.proj_out = projection
    inner.decoder.out_channels = 12
    # 权重存储 RGB phase 分组: RRRR GGGG BBBB. 统计只在 decode 阶段展开;
    # encoder 仍需要 RGB。
    inner._finalize_pixels = MethodType(_finalize_hyper_pixels, inner)
    model_management.archive_model_dtypes(inner)
    vae.size = None
    vae.patcher.size = 0
    vae.model_size()
    native_memory = vae.memory_used_decode
    vae.memory_used_decode = lambda shape, dtype: native_memory(shape, dtype) * 1.25
    report["status"] = "loaded_not_quality_qualified"
    report["video_vae_only"] = True
    report["audio_vae_unchanged"] = True
    return vae, report


# 仅在类定义处 import Comfy, 避免全局 monkey-patch VAE 工厂。
import comfy.sd  # noqa: E402


class HyperVAE2x(comfy.sd.VAE):
    def spacial_compression_decode(self):
        # 报告真实 IMAGE 几何, 不是内部 packed buffer。
        return 32

    def decode(self, samples_in, vae_options={}):
        _check_h3_video_latent(samples_in)
        return pixel_shuffle_h3_images(super().decode(samples_in, vae_options))

    def decode_tiled(self, samples, tile_x=None, tile_y=None, overlap=None,
                     tile_t=None, overlap_t=None):
        _check_h3_video_latent(samples)
        packed = super().decode_tiled(samples, tile_x=tile_x, tile_y=tile_y,
                                      overlap=overlap, tile_t=tile_t,
                                      overlap_t=overlap_t)
        return pixel_shuffle_h3_images(packed)


def _check_h3_video_latent(samples: torch.Tensor) -> None:
    if samples.ndim != 5 or samples.shape[1] != 24:
        raise ValueError(f"HyperVAE 2x 仅接受 H3 视频 latent [B,24,T,H,W]，实际 {tuple(samples.shape)}")
