"""Static video/audio masks for the selflift-Avatar experiment."""

import logging
import math

import torch
import torch.nn.functional as F


def _description(value):
    if getattr(value, "is_nested", False):
        return f"{type(value).__name__}({[tuple(s.shape) for s in value.unbind()]})"
    return f"{type(value).__name__}(shape={getattr(value, 'shape', None)})"


def resize_spatial(mask, size):
    if tuple(mask.shape[-2:]) == tuple(size):
        return mask
    lead = mask.shape[:-2]
    return F.interpolate(
        mask.reshape(-1, 1, *mask.shape[-2:]).float(),
        size=size, mode="bilinear", align_corners=False,
    ).reshape(*lead, *size)


def _normalize_video(mask, shape):
    video = len(shape) == 5
    if mask.ndim == 3:  # BHW
        mask = mask[:, None]
    if video and mask.ndim == 4:  # BCHW, constant over time
        mask = mask[:, :, None]
    if mask.ndim != len(shape):
        raise ValueError("video mask must be BHW, BCHW or BCTHW (C=1 or latent channels)")
    for axis in range(len(shape) - 2):
        if mask.shape[axis] not in (1, shape[axis]):
            raise ValueError(f"video mask axis {axis} has size {mask.shape[axis]}, expected 1 or {shape[axis]}")
    if mask.shape[-2] in (1, shape[-2]) and mask.shape[-1] in (1, shape[-1]):
        return mask.expand(shape[0], *mask.shape[1:-2], *shape[-2:])
    return resize_spatial(mask, shape[-2:]).expand(shape[0], *mask.shape[1:-2], *shape[-2:])


def _normalize_audio(mask, shape):
    if len(shape) != 4:
        raise ValueError(f"audio latent must be BCST, received {shape}")
    if mask.ndim == 1:  # T
        mask = mask[None, None, None]
    elif mask.ndim == 2:  # BT
        mask = mask[:, None, None]
    elif mask.ndim == 3:  # BST
        mask = mask[:, None]
    if mask.ndim != 4:
        raise ValueError("audio mask must be T, BT, BST or BCST")
    if (mask.shape[0] in (1, shape[0]) and mask.shape[1] in (1, shape[1])
            and mask.shape[2] not in (1, shape[2])):
        # SetLatentNoiseMask stores SolidMask at image resolution, even for audio.
        # A spatial constant can broadcast without inventing a time mapping.
        constant = mask[:, :, :1, :1]
        if not torch.equal(mask, constant.expand_as(mask)):
            raise ValueError("audio mask has a non-uniform image grid; use a constant SolidMask for whole-audio control or a BCST audio mask")
        original_shape = tuple(mask.shape)
        mask = constant.clone()
        logging.info("selflift-Avatar: constant audio mask %s -> %s (0=keep, 1=generate)",
                     original_shape, tuple(mask.shape))
    for axis, target in enumerate(shape):
        if mask.shape[axis] not in (1, target):
            raise ValueError(f"audio mask axis {axis} has size {mask.shape[axis]}, expected 1 or {target}; audio is not time-resampled")
    return mask.expand(shape[0], *mask.shape[1:])


def normalize_masks(mask, streams):
    if mask is None:
        return None
    description = _description(mask)
    shapes = [tuple(s.shape) for s in streams]
    if getattr(mask, "is_nested", False):
        masks = list(mask.unbind())
        if len(masks) != len(streams):
            raise ValueError(f"selflift-Avatar: mask stream count does not match {shapes}; received {description}")
    elif isinstance(mask, torch.Tensor):
        sizes = [math.prod(s[1:]) for s in shapes]
        if len(streams) > 1 and mask.ndim == 3 and mask.shape[1:] == (1, sum(sizes)):
            masks = [part.reshape(mask.shape[0], *shape[1:])
                     for part, shape in zip(mask.split(sizes, dim=-1), shapes)]
        else:
            masks = [mask] + [None] * (len(streams) - 1)
    else:
        raise ValueError(f"selflift-Avatar: unsupported noise_mask {description}")
    normalized = []
    for index, (m, stream) in enumerate(zip(masks, streams)):
        if m is None:
            normalized.append(stream.new_ones((1,) * stream.ndim, dtype=torch.float32))
            continue
        if not isinstance(m, torch.Tensor) or m.is_nested or m.numel() == 0:
            raise ValueError(f"selflift-Avatar: mask stream {index} must be a nonempty Tensor; received {description}")
        if not torch.isfinite(m).all():
            raise ValueError(f"selflift-Avatar: mask stream {index} contains NaN/Inf; received {description}")
        m = m.float().clamp(0.0, 1.0)
        normalizer = _normalize_video if index == 0 else _normalize_audio
        try:
            normalized.append(normalizer(m, tuple(stream.shape)))
        except ValueError as exc:
            raise ValueError(f"selflift-Avatar: {exc}; received {description}; latent shapes={shapes}") from exc
    return normalized


def restore_kept(outputs, anchors, masks):
    return [torch.where(mask.to(out.device) == 0, anchor.to(out), out)
            for out, anchor, mask in zip(outputs, anchors, masks)]


def validate_tiling_masks(masks):
    if masks is None:
        return
    if len(masks) != 2 or not bool((masks[0] == 1).all()) or not bool((masks[1] == 0).all()):
        raise ValueError(
            "selflift-Avatar: highres_tiling with noise_mask currently requires "
            "video mask = 1 everywhere and audio mask = 0 everywhere. "
            "Disable highres_tiling for video preservation, partial audio or soft masks."
        )
