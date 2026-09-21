# -*- coding: utf-8 -*-
"""MiniMax H3 Semantic Bridge for BSAI H3 Film Factory (可开可关, 默认关).

Original student math from speach1sdef178/MiniMax-H3-Semantic-Bridge:

    x  = RMS_norm(H)
    S  = student(x)          # 5120 -> 512 SiLU -> 512 SiLU -> 5120
    S' = magnitude_match(S, H)
    C  = H + alpha * (S' - H)

Only CONDITIONING[0][0] (the [B, T, 5120] token tensor) is rewritten.
Keyframe / ref metadata is left untouched. Weights are user-provided under
ComfyUI/models/semantic_bridge/*.safetensors (~11MB). Unconnected / disabled
is a pure no-op. Distilled on FL2VA; Ref2VA (this plugin's r2v path) is
force-compat with a warning.
"""

from __future__ import annotations

import glob
import logging
import os

import torch
import torch.nn as nn
import torch.nn.functional as F

log = logging.getLogger("BSAI-H3-Film-Factory.semantic_bridge")

SEMANTIC_BRIDGE_FOLDER = "semantic_bridge"
MISSING_LABEL = "(关闭: 无权重)"
HIDDEN_DIM = 5120
STUDENT_DIM = 512
DEFAULT_ALPHA = 0.15
META_APPLIED_KEY = "bsai_semantic_bridge"

_MODEL_CACHE: dict = {}


class SemanticStudent(nn.Module):
    """5120->512 SiLU -> 512 SiLU -> 5120. Six tensors: fc1/2/3 weight+bias."""

    def __init__(self) -> None:
        super().__init__()
        self.fc1 = nn.Linear(HIDDEN_DIM, STUDENT_DIM)
        self.fc2 = nn.Linear(STUDENT_DIM, STUDENT_DIM)
        self.fc3 = nn.Linear(STUDENT_DIM, HIDDEN_DIM)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fc3(F.silu(self.fc2(F.silu(self.fc1(x)))))


def _folder() -> str | None:
    try:
        import folder_paths
        if SEMANTIC_BRIDGE_FOLDER not in folder_paths.folder_names_and_paths:
            folder_paths.add_model_folder_path(
                SEMANTIC_BRIDGE_FOLDER,
                os.path.join(folder_paths.models_dir, SEMANTIC_BRIDGE_FOLDER),
            )
        paths = folder_paths.get_folder_paths(SEMANTIC_BRIDGE_FOLDER)
        return paths[0] if paths else None
    except Exception:
        return None


def list_adapters() -> list:
    """Combo list for INPUT_TYPES. Always returns >=1 entry."""
    root = _folder()
    names: list = []
    if root:
        try:
            os.makedirs(root, exist_ok=True)
        except OSError:
            pass
        for ext in ("*.safetensors", "*.pt", "*.pth"):
            names.extend(os.path.basename(p) for p in glob.glob(os.path.join(root, ext)))
        try:
            import folder_paths
            names.extend(folder_paths.get_filename_list(SEMANTIC_BRIDGE_FOLDER) or [])
        except Exception:
            pass
    out = sorted({n for n in names if n and not n.startswith("(")})
    return [MISSING_LABEL] + out


def _resolve(name: str) -> str | None:
    n = str(name or "").strip()
    if not n or n.startswith("("):
        return None
    if os.path.isabs(n) and os.path.isfile(n):
        return n
    try:
        import folder_paths
        _folder()
        p = folder_paths.get_full_path(SEMANTIC_BRIDGE_FOLDER, n)
        if p and os.path.isfile(p):
            return p
    except Exception:
        pass
    root = _folder()
    if root:
        cand = os.path.join(root, n)
        if os.path.isfile(cand):
            return cand
    return None


def _load_sd(path: str) -> dict:
    if path.endswith(".safetensors"):
        from safetensors.torch import load_file
        return load_file(path)
    try:
        blob = torch.load(path, map_location="cpu", weights_only=True)
    except TypeError:
        blob = torch.load(path, map_location="cpu")
    if isinstance(blob, dict) and isinstance(blob.get("state_dict"), dict):
        return blob["state_dict"]
    if isinstance(blob, dict):
        return blob
    raise ValueError(f"Semantic Bridge adapter not a state dict: {path}")


def _load_student(path: str) -> SemanticStudent:
    cached = _MODEL_CACHE.get(path)
    if cached is not None:
        return cached
    m = SemanticStudent()
    m.load_state_dict(_load_sd(path), strict=True)
    m.eval()
    _MODEL_CACHE[path] = m
    return m


def _rms_norm(x, eps=1e-6):
    return x * torch.rsqrt(x.pow(2).mean(dim=-1, keepdim=True) + eps)


def _magnitude_match(s, t, eps=1e-8):
    return s * (t.norm(dim=-1, keepdim=True) / (s.norm(dim=-1, keepdim=True) + eps))


def apply(cond, adapter_name, alpha=DEFAULT_ALPHA, magnitude_match=True):
    """Rewrite cond[0][0] in place-copy. Returns (cond, note). No-op when off."""
    if not isinstance(cond, list) or not cond:
        return cond, None
    path = _resolve(adapter_name)
    if not path:
        return cond, f"Semantic Bridge 跳过: 未找到权重 {adapter_name or '(空)'}, 请放到 models/semantic_bridge/"

    item0 = cond[0]
    if not isinstance(item0, (list, tuple)) or not item0:
        return cond, "Semantic Bridge 跳过: 条件结构异常"
    hidden, meta = item0[0], (item0[1] if len(item0) > 1 else None)
    if not isinstance(hidden, torch.Tensor):
        return cond, "Semantic Bridge 跳过: cond[0][0] 不是张量"
    if hidden.ndim != 3 or hidden.shape[-1] != HIDDEN_DIM:
        return cond, (f"Semantic Bridge 跳过: 期望 [B,T,{HIDDEN_DIM}] 实际 {tuple(hidden.shape)}"
                      f" (该 H3 文本编码器维度不匹配)")

    try:
        student = _load_student(path)
        device, dtype = hidden.device, hidden.dtype
        student = student.to(device=device, dtype=torch.float32)
        x = hidden.float()
        with torch.no_grad():
            s = student(_rms_norm(x))
            if magnitude_match:
                s = _magnitude_match(s, x)
            out = x + float(alpha) * (s - x)
        rewritten = out.to(device=device, dtype=dtype)
    except Exception as exc:
        return cond, f"Semantic Bridge 跳过: {exc}"

    new_meta = dict(meta) if isinstance(meta, dict) else {}
    new_meta[META_APPLIED_KEY] = True
    new_item = [rewritten, new_meta]
    if len(item0) > 2:
        new_item.extend(item0[2:])
    out = list(cond)
    out[0] = new_item
    return out, (f"Semantic Bridge 生效 (adapter={os.path.basename(adapter_name)}, "
                 f"alpha={float(alpha):.3f}, tokens={int(rewritten.shape[1])})")
