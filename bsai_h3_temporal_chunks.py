"""
bsai_h3_temporal_chunks.py  (v1.00, 2026-09-19)
================================================
沿时间(T)轴切块的二采 refine 包装。

动机: BSAI 电影工厂原有 tile_count 是【空间分块】(沿 H/W 切, overlap_pixels),
二采 x2 时整段 T(~107 tokens)一次性过 DiT, attention/激活 workspace 随 T 线性增长,
24GB 卡在长 clip 或高 factor 时容易 OOM。本模块把【二采 refine】沿 T 切成带重叠的
小段, 每段单独走一遍已有的(空间分块)采样器, 已完成的重叠区用 denoise_mask 冻结,
相邻段用 smoothstep 斜坡接管 + 锁区原样保留, 避免接缝/重影。

算法移植自 T8 comfyui-minimax-h3-audio-T8
  chunked_two_pass_upscale_advanced.py (Apache-2.0):
  - FRAME_PER_TOKEN=(1,4,4,4,4) / FRAME_RESCALE=5/3 的 token<->frame 换算
  - previous_overlap_guarded_progressive_takeover ownership 策略
  - 锁区 read-only + smoothstep 过渡 + crossfade 合并

本文件只提供纯张量几何/mask/合并工具; 真正的 guider.sample 仍在 extender.py 主流程里
按段调用, 不重复实现采样调度。默认关闭, 由 extender 传 chunk_tokens>0 才启用。
"""

import torch

# H3 非均匀帧/token 映射 (与 comfy.ldm.minimax.model 一致)
FRAME_PER_TOKEN = (1, 4, 4, 4, 4)
FRAME_RESCALE = 5.0 / 3.0


def frames_for_tokens(count: int) -> int:
    """token 数 -> 对应视频帧数。"""
    count = int(count)
    if count <= 0:
        return 0
    return sum(FRAME_PER_TOKEN[i % 5] for i in range(count))


def plan_temporal_segments(total_tokens: int, chunk_tokens: int, overlap_tokens: int):
    """把 total_tokens 沿 T 切成 [start,end) token 段, 段间重叠 overlap。

    返回 [(start_tok, end_tok), ...]。chunk_tokens<=0 或整段装得下时返回单段(不切)。
    """
    total_tokens = int(total_tokens)
    chunk_tokens = int(chunk_tokens)
    overlap_tokens = int(overlap_tokens)
    if chunk_tokens <= 0 or total_tokens <= 0:
        return [(0, total_tokens)]
    if total_tokens <= chunk_tokens:
        return [(0, total_tokens)]
    overlap_tokens = max(0, min(overlap_tokens, chunk_tokens - 1))
    hop = chunk_tokens - overlap_tokens
    segs = []
    start = 0
    while start < total_tokens:
        end = min(start + chunk_tokens, total_tokens)
        segs.append((start, end))
        if end >= total_tokens:
            break
        start = end - overlap_tokens
    return segs


def _blend(values: torch.Tensor, style: str = "smoothstep") -> torch.Tensor:
    if style == "smoothstep":
        return values * values * (3.0 - 2.0 * values)
    return values


def build_temporal_mask(chunk_t: int, overlap_tokens: int, dtype, device):
    """构造二采 denoise_mask(只对视频成员)。

    返回 mask(1,1,chunk_t,1,1): 重叠区前半=0(冻结, 不重绘), 后半 smoothstep 0->1 接管,
    新区=1(正常重绘)。overlap_tokens=0 时全 1。
    """
    chunk_t = int(chunk_t)
    overlap_tokens = max(0, min(int(overlap_tokens), chunk_t))
    mask = torch.ones((1, 1, chunk_t, 1, 1), dtype=dtype, device=device)
    if overlap_tokens <= 0:
        return mask, 0, 0
    locked = max(1, overlap_tokens // 2)
    transition = overlap_tokens - locked
    mask[:, :, :locked] = 0
    if transition > 0:
        vals = torch.linspace(0.0, 1.0, transition + 1, dtype=dtype, device=device)[1:]
        mask[:, :, locked:overlap_tokens, 0, 0] = _blend(vals, "smoothstep")
    return mask, locked, transition


def slice_nested_temporal(members, start_t: int, end_t: int):
    """把 NestedTensor 的 [video, audio] 成员沿 T 切片。

    video:(1,24,T,H,W) 直接 [:, :, start:end]; audio:(1,32,2,At) 按 frame<->audio 换算切。
    返回 [chunk_video, chunk_audio]。
    """
    video, audio = members[0], members[1]
    chunk_video = video[:, :, start_t:end_t].contiguous()
    vf0 = frames_for_tokens(start_t)
    vf1 = frames_for_tokens(end_t)
    a_start = int(round(vf0 * FRAME_RESCALE))
    a_end = int(round(vf1 * FRAME_RESCALE))
    a_end = min(audio.shape[-1], a_end)
    a_start = min(a_start, a_end)
    chunk_audio = audio[..., a_start:a_end].contiguous()
    return chunk_video, chunk_audio


def merge_guarded(accumulated_video, chunk_video, start_t: int, locked_tokens: int):
    """ownership 合并: 锁区原样保留 accumulated, 过渡区发布 chunk 的桥接, 新区直接拼接。

    accumulated_video/chunk_video 形状 (1,24,T,H,W)。返回新的累计视频。
    """
    if accumulated_video is None:
        return chunk_video
    overlap = max(0, int(accumulated_video.shape[2]) - int(start_t))
    overlap = min(overlap, int(chunk_video.shape[2]))
    locked_tokens = max(0, min(int(locked_tokens), overlap))
    transition = overlap - locked_tokens
    published = accumulated_video.clone()
    if transition > 0:
        published[:, :, start_t + locked_tokens:start_t + overlap] = chunk_video[
            :, :, locked_tokens:overlap
        ]
    if overlap >= chunk_video.shape[2]:
        return published
    return torch.cat((published, chunk_video[:, :, overlap:]), dim=2)
