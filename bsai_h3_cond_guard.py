# -*- coding: utf-8 -*-
"""BSAI_H3_CondGeometryGuard —— 二采前校正条件化的网格几何。

背景：MiniMax H3 是 token 级打包模型（comfy/ldm/minimax/model.py 的 PackedLayout）。
`minimax_keyframes`（上下文关键帧）会按**目标潜空间的网格**预留行：

    n = vt * frame_rows(target_h, target_w)

而实际填充的 `cond_video_rows` 来自关键帧自身的 latent：

    patchify(kf_latent) -> vt * frame_rows(src_h, src_w)

一采 34x60 → 二采 68x120 时，关键帧仍停在 34x60，预留行数按 68x120 算，就出现

    RuntimeError: shape mismatch ... all_video_rows[~img_update] = cond_video_rows

本节点把与当前潜空间网格不一致的关键帧剔除；`minimax_refs` 的 latent_t/h/w 声明
按真实张量重写、拿不出张量的引用块剔除（与 H3ContextContinuationPro 的
`_guard_cond_geometry` 同一套规则）。关键帧内容本来就已经烘进潜空间，二采阶段
丢掉它们只是去掉重复的条件，不影响画面。
"""

import torch


def _video_from_latent(latent):
    if isinstance(latent, dict):
        latent = latent.get("samples")
    if latent is None:
        raise ValueError("潜空间为空")
    samples = getattr(latent, "samples", latent)
    if isinstance(samples, torch.Tensor):
        return samples
    tensors = getattr(samples, "tensors", None)
    if tensors:
        return tensors[0]
    raise ValueError("无法从潜空间取出视频张量")


def _target_hw(latent):
    v = _video_from_latent(latent)
    if v.ndim == 5:
        return int(v.shape[3]), int(v.shape[4])
    if v.ndim == 4:
        return int(v.shape[2]), int(v.shape[3])
    raise ValueError("不认识的潜空间维度：%s" % (tuple(v.shape),))


def guard_conditioning(cond, latent, verbose=True):
    th, tw = _target_hw(latent)
    dropped_kf = dropped_ref = 0
    cleaned = []
    for item in cond or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            cleaned.append(item)
            continue
        c, md = item[0], item[1]
        d = dict(md) if isinstance(md, dict) else {}

        kfs = d.get("minimax_keyframes")
        if isinstance(kfs, (list, tuple)) and kfs:
            kept = []
            for kf in kfs:
                lat = kf.get("latent") if isinstance(kf, dict) else None
                if lat is None:
                    kept.append(kf)
                    continue
                q = lat if lat.ndim == 5 else lat.unsqueeze(0)
                if int(q.shape[3]) != th or int(q.shape[4]) != tw:
                    dropped_kf += 1
                    continue
                kept.append(kf)
            if kept:
                d["minimax_keyframes"] = kept
            else:
                d.pop("minimax_keyframes", None)

        refs = d.get("minimax_refs")
        if isinstance(refs, (list, tuple)) and refs:
            kept_refs = []
            for r in refs:
                if not isinstance(r, dict):
                    kept_refs.append(r)
                    continue
                kind = r.get("kind")
                lat = r.get("latent")
                if kind in ("video", "video_audio", "image"):
                    if lat is None:
                        dropped_ref += 1
                        continue
                    q = lat if lat.ndim == 5 else lat.unsqueeze(0)
                    r = dict(r)
                    r["latent_t"] = int(q.shape[2])
                    r["latent_h"] = int(q.shape[3])
                    r["latent_w"] = int(q.shape[4])
                    kept_refs.append(r)
                elif kind == "audio":
                    if r.get("audio_latent") is None and int(r.get("ref_audio_t", 0)) > 0:
                        dropped_ref += 1
                        continue
                    kept_refs.append(r)
                else:
                    kept_refs.append(r)
            if kept_refs:
                d["minimax_refs"] = kept_refs
            else:
                d.pop("minimax_refs", None)

        cleaned.append([c, d])

    if verbose and (dropped_kf or dropped_ref):
        print(
            "[H3 几何守卫] 目标网格 %dx%d：剔除 %d 个网格不符的关键帧、%d 个无张量的引用块"
            % (tw, th, dropped_kf, dropped_ref),
            flush=True,
        )
    return cleaned, dropped_kf, dropped_ref


class BSAI_H3_CondGeometryGuard:
    """二采前把条件化里的关键帧/引用块对齐到放大后的潜空间网格。"""

    CATEGORY = "A-BSAI/H3"
    FUNCTION = "run"
    RETURN_TYPES = ("CONDITIONING",)
    RETURN_NAMES = ("条件化",)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "条件化": ("CONDITIONING", {"tooltip": "二采要用的条件化（一采透传下来的那份）。"}),
                "潜空间": ("LATENT", {"tooltip": "二采实际要采样的潜空间，就地给目标网格。"}),
            },
            "optional": {
                "严格模式": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "label_on": "严格：网格不符就报错",
                        "label_off": "宽松：剔除不匹配的关键帧",
                        "tooltip": "打开后不做剔除，直接抛中文错误，方便排查到底哪里几何不一致。",
                    },
                ),
            },
        }

    def run(self, 条件化, 潜空间, 严格模式=False):
        cleaned, dropped_kf, dropped_ref = guard_conditioning(条件化, 潜空间, verbose=not 严格模式)
        if 严格模式 and (dropped_kf or dropped_ref):
            th, tw = _target_hw(潜空间)
            raise RuntimeError(
                "条件化与潜空间网格不一致：目标 %dx%d，其中 %d 个关键帧、%d 个引用块对不上。"
                "把本节点切回「宽松」会自动剔除这些关键帧。"
                % (tw, th, dropped_kf, dropped_ref)
            )
        return (cleaned,)


NODE_CLASS_MAPPINGS = {"BSAI_H3_CondGeometryGuard": BSAI_H3_CondGeometryGuard}
NODE_DISPLAY_NAME_MAPPINGS = {"BSAI_H3_CondGeometryGuard": "H3 条件化几何守卫（二采前校正关键帧网格）"}
