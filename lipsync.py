"""
BSAI H3 Film Factory — LipSync 对口型模块 (v1.0, 2026-10-06)
============================================================

技术路线（2026-10 全网研究结论）：
  H3 原生 Ref2VA 音频驱动 + IndexTTS-2.5 文本转语音。
  - H3 是 omni-modal 联合生成模型：参考图 + 参考音频 → 联合 latent 去噪，
    生成时口型/表情/动作与音频原生同步（社区 2026-08~09 已验证说话、唱歌、
    双人指定说话人场景；官方提示词 <d>...</d> 标签实现逐字朗读+口型同步）。
  - IndexTTS-2.5（本机已装 BSAI_ComfyUI_IndexTTS-2.5）：零样本语音克隆，
    输入一句话 + 角色声线参考音频 → 自然语音，直接输出 ComfyUI AUDIO。
  - 歌曲：外部音频文件/资产库 @音频N → 直接作为 Ref2VA 音频条件驱动唱歌口型。

两种模式：
  speech 说话：外部输入一句话（节点 lip_text 或 CLIP 卡片 lip_text）→ TTS
              → 该 CLIP 的 Ref2VA 音频条件 → 角色对口型说话。
  sing   唱歌：外部输入一首歌（节点 lip_audio AUDIO / CLIP 卡片 lip_audio
              @音频N / CLIP prompt 内 @音频N）→ 该 CLIP 的 Ref2VA 音频条件
              → 角色对口型唱歌。

与本插件既有链路的关系：
  extender.py 已有 ref_audio -> _encode_ref_audio(audio_vae) -> audio_latent
  -> cond_audio_latents（patch_motion_payload）完整通道。本模块只负责
  "每个 CLIP 的对口型音频从哪来"（TTS 合成 / 音频资产 / 节点输入），
  不触碰模型 patch 与采样链路，现有功能 100% 不变。
"""

from __future__ import annotations

import json
import os
import re
import zlib

import torch
import torchaudio

# 复用电影工厂自身的帧网格工具（避免重复定义）
try:
    from .nodes_clip import _duration_to_frames, FPS
except Exception:  # 兜底：独立定义，防止导入顺序问题
    FPS = 24
    # H3 官方帧数约束 17n+5，扩展到 15.08s（362 帧 = n=21）
    H3_FRAME_GRID = [17 * n + 5 for n in range(0, 22)]

    def _duration_to_frames(duration_seconds):
        target = int(duration_seconds * FPS)
        best = H3_FRAME_GRID[0]
        for v in H3_FRAME_GRID:
            if v <= target:
                best = v
        if target > H3_FRAME_GRID[-1] and abs(target - H3_FRAME_GRID[-1]) < abs(target - best):
            best = H3_FRAME_GRID[-1]
        return best


# ---------------------------------------------------------------------------
# 音频加载 / 工具
# ---------------------------------------------------------------------------

def load_audio_file(path: str):
    """音频文件路径 → ComfyUI AUDIO dict {waveform:[B=1,C,L], sample_rate}。

    与 _encode_ref_audio(audio_vae, audio) 兼容：waveform[:1].movedim(1,-1)。
    """
    waveform, sr = torchaudio.load(path)
    if waveform.dim() == 1:
        waveform = waveform.unsqueeze(0)
    # 多声道混为单声道（H3 AudioVAE 期望单声道输入）
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)
    if waveform.dim() == 2:
        waveform = waveform.unsqueeze(0)  # [1, C, L]
    return {"waveform": waveform.float(), "sample_rate": int(sr)}


def audio_seconds(audio) -> float:
    """AUDIO dict 的时长（秒）。"""
    try:
        return float(audio["waveform"].shape[-1]) / float(int(audio["sample_rate"]))
    except Exception:
        return 0.0


def trim_audio(audio, max_seconds: float):
    """把音频裁剪到不超过 max_seconds（尾部截断），返回新 AUDIO dict。"""
    waveform = audio["waveform"]
    sr = int(audio["sample_rate"])
    max_samples = int(max(0.0, float(max_seconds)) * sr)
    if waveform.shape[-1] > max_samples:
        waveform = waveform[..., :max_samples]
        audio = {"waveform": waveform, "sample_rate": sr}
    return audio


def slice_audio(audio, start_seconds: float, duration_seconds: float):
    """顺序切段：从全局音频切 [start, start+duration) 段。

    返回新 AUDIO dict；若起点已超出音频结尾（音频耗尽）返回 None。
    v1.2 (2026-10-07): 修复 end 样本计算括号优先级——
    旧版 int(start+dur)*sr 在小数秒游标(自适应切分)时会把 0.9s 的分数秒截掉。
    """
    waveform = audio["waveform"]
    sr = int(audio["sample_rate"])
    start = int(max(0.0, float(start_seconds)) * sr)
    end = int((float(start_seconds) + float(duration_seconds)) * sr)
    total = waveform.shape[-1]
    if start >= total:
        return None
    end = min(end, total)
    return {"waveform": waveform[..., start:end], "sample_rate": sr}


def _frames_nearest(duration_seconds):
    """对口型专用帧数：选 17n+5 网格中【最接近】target 的值（可略大于 target）。

    与 nodes_clip._duration_to_frames（只选 ≤target 的最大值，用于渲染帧数，
    保持既有 CLIP 渲染行为不变）不同——对口型必须保证音频不短于渲染帧数，
    取最接近值可让 15s 落到 362 帧(15.08s)而非 345 帧(14.38s)，不丢尾部歌词。
    """
    target = int(duration_seconds * FPS)
    grid = [17 * n + 5 for n in range(0, 22)]  # 最大 362 帧 = 15.08s
    return min(grid, key=lambda v: abs(v - target))


def _align_audio_to_fit(audio, clip_dur, lip_cfg, clip_index):
    """时长对齐：fit_duration=True 音频优先(对齐 17n+5 帧网格)；False 剧本优先(裁剪)。

    返回 (audio, eff_duration)。eff_duration 为 None 表示保持剧本时长。
    """
    fit_duration = bool(lip_cfg.get("fit_duration", True))
    audio_sec = audio_seconds(audio)
    if fit_duration:
        # 音频优先：CLIP 时长 = 音频时长（对口型专用最近网格，口型不短于音频）
        eff_duration = max(0.5, min(15.0, audio_sec))
        eff_frames = _frames_nearest(eff_duration)
        eff_sec = eff_frames / float(FPS)
        # 音频尾部对齐帧网格（略留 0.1s 余量，防止口型在最后一帧提前断掉）
        audio = trim_audio(audio, eff_sec + 0.1)
        print(f"[H3 LipSync] clip[{clip_index}] 时长对齐: 音频 {audio_sec:.2f}s -> "
              f"CLIP 时长 {eff_sec:.2f}s ({eff_frames}帧, 原剧本 {clip_dur:.2f}s)")
    else:
        # 剧本时长优先：音频裁剪到剧本时长
        audio = trim_audio(audio, clip_dur)
        print(f"[H3 LipSync] clip[{clip_index}] 时长对齐: 音频裁剪到剧本时长 {clip_dur:.2f}s "
              f"(原 {audio_sec:.2f}s)")
    return audio, eff_duration if fit_duration else None


def _find_asset_by_index(items, tag_num):
    """按 index 字段找资产，兼容资产库结构。"""
    for item in items:
        if isinstance(item, dict) and item.get("index") == tag_num:
            return item
    idx = tag_num - 1
    if 0 <= idx < len(items):
        return items[idx]
    return None


def _resolve_audio_ref_str(ref_str, audios):
    """把 '@音频N' 字符串解析为资产路径；找不到返回 None。"""
    if not ref_str or not str(ref_str).strip():
        return None
    s = str(ref_str).strip()
    m = re.search(r'@音频(\d+)', s)
    if not m:
        return None
    entry = _find_asset_by_index(audios or [], int(m.group(1)))
    if entry is None:
        return None
    return entry.get("path", entry.get("filename", "")) if isinstance(entry, dict) else str(entry)


# ---------------------------------------------------------------------------
# TTS：IndexTTS-2.5（延迟导入，避免插件加载顺序问题）
# ---------------------------------------------------------------------------

_TTS_SYNTH_NODE = None


def _get_tts_synthesis():
    """延迟获取 IndexTTS-2.5 的合成节点实例。"""
    global _TTS_SYNTH_NODE
    if _TTS_SYNTH_NODE is None:
        import importlib
        try:
            mod = importlib.import_module("BSAI_IndexTTS")
        except Exception as e:
            raise RuntimeError(
                "lip speech 模式需要 IndexTTS-2.5 插件，但导入 BSAI_IndexTTS 失败: %s" % e
            )
        _TTS_SYNTH_NODE = mod.BSAI_IndexTTS2_5Synthesis()
    return _TTS_SYNTH_NODE


def tts_speech(tts_model, text: str, voice_audio, lang: str = "ZH", duration_factor: float = 1.0):
    """一句话 + 角色声线参考音频 → IndexTTS-2.5 语音 → ComfyUI AUDIO dict。

    tts_model: BSAI_IndexTTS2_5Loader 输出的 INDEX_TTS_MODEL 句柄。
    voice_audio: ComfyUI AUDIO dict（角色声音样本，必须非空）。
    """
    if text is None or not str(text).strip():
        raise ValueError("lip speech 模式：lip_text 说话文本不能为空。")
    if tts_model is None:
        raise ValueError(
            "lip speech 模式需要连接 IndexTTS-2.5 Loader：把 BSAI_IndexTTS2_5Loader 的 "
            "tts_model 接到本节点的 tts_model_TTS模型 输入。"
        )
    if voice_audio is None or voice_audio.get("waveform") is None:
        raise ValueError(
            "lip speech 模式需要角色声线参考音频：连接本节点 lip_voice 输入，"
            "或在 CLIP 卡片 lip_voice 填 @音频N（声线样本）。"
        )
    node = _get_tts_synthesis()
    audio, status = node.synthesize(
        tts_model,
        str(text).strip(),
        voice_audio,
        lang_语言=lang,
        duration_factor_语速因子=float(duration_factor),
    )
    print(f"[H3 LipSync] IndexTTS-2.5: {status}")
    return audio


# ---------------------------------------------------------------------------
# 每 CLIP 对口型解析
# ---------------------------------------------------------------------------

LIP_NOTE_SPEECH = (
    "\n该角色正在对镜头说台词：<d>{text}</d>，口型、表情与发音逐字同步，语气自然。"
)
LIP_NOTE_SING = (
    "\n该角色正在演唱这段歌曲音频，嘴唇随歌声旋律开合，表情投入、自然，"
    "口型与歌曲节拍精确同步。"
)
# v1.81 (2026-10-07) 口播/说话音频模式：外部录音(口播/直播/相声/主持/对白)直接
# 驱动口型，不做歌声分段（不做 demucs/whisper），整段按「说话」演绎。
LIP_NOTE_TALK = (
    "\n该角色正在对镜头说话：嘴唇、下颌与舌部动作随这段说话音频的节奏自然开合，"
    "口型与语音逐字同步，表情随语气变化，语气自然，不唱歌、不做夸张演唱动作。"
)
LIP_NOTE_TALK_TEXT = (
    "\n该角色正在对镜头说台词：<d>{text}</d>，口型、表情与发音逐字同步，"
    "语气自然，不唱歌。"
)

# ---------------------------------------------------------------------------
# v1.81 模式归一化
#   speech       —— TTS 文本合成后对口型（需 tts_model + 声线参考）
#   sing         —— 外部歌曲音频对口型（demucs 歌声分段，纯音乐段不开口）
#   speech_audio —— 外部说话/口播/相声/主持/直播录音直接对口型（不做歌声分段）
# ---------------------------------------------------------------------------
MODE_SPEECH = "speech"
MODE_SING = "sing"
MODE_TALK = "speech_audio"
MODE_OFF = "off"
MODE_INVALID = "__invalid__"

_OFF_MODE_ALIASES = {"", "none", "off", "false", "0", "no", "关闭", "无", "关"}
_MODE_ALIASES = {
    "speech": MODE_SPEECH, "说话": MODE_SPEECH, "talk": MODE_SPEECH,
    "tts": MODE_SPEECH, "台词": MODE_SPEECH,
    "sing": MODE_SING, "唱歌": MODE_SING, "singing": MODE_SING,
    "song": MODE_SING, "演唱": MODE_SING, "歌曲": MODE_SING,
    "speech_audio": MODE_TALK, "talk_audio": MODE_TALK, "audio_speech": MODE_TALK,
    "audio_talk": MODE_TALK, "speechaudio": MODE_TALK, "口播": MODE_TALK,
    "说话音频": MODE_TALK, "录音": MODE_TALK, "对白音频": MODE_TALK,
    "主持": MODE_TALK, "相声": MODE_TALK, "直播": MODE_TALK,
    "narrate": MODE_TALK, "narration": MODE_TALK, "dub": MODE_TALK,
}


def normalize_lip_mode(value):
    """lip_mode 字符串 → off / speech / sing / speech_audio / __invalid__。"""
    s = str(value or "").strip().lower()
    if s in _OFF_MODE_ALIASES:
        return MODE_OFF
    return _MODE_ALIASES.get(s, MODE_INVALID)


# ---------------------------------------------------------------------------
# 歌声分段检测 (v1.3, 2026-10-07): 纯音乐段(前奏/间奏/尾奏)不开口
# ---------------------------------------------------------------------------
def detect_vocal_segments(audio, hop_s=0.1, win_s=0.06, sm_frames=15,
                          threshold=0.55, min_len_s=0.8, merge_gap_s=0.6):
    """轻量歌声分段：返回人声区间列表 [(start_s, end_s), ...]。

    特征(每 hop 帧):
      mid    = 300~3400Hz 能量占比      (人声主能量带, 纯钢琴/弦乐偏低)
      harm   = 1 - 谱平坦度            (人声=单基频谐波序列, 平坦度低)
      envj   = 包络抖动                (歌声音节起落, 纯伴奏平缓)
    评分 = mid*1.0 + harm*0.6 + envj*0.8, 平滑后阈值判定。
    保守取向(宁可多标人声, 避免误杀歌声段导致角色不开口)。
    """
    import numpy as np
    wav = audio["waveform"]
    if wav.ndim == 3:
        wav = wav[0]
    x = wav.float().mean(dim=0).numpy() if wav.ndim == 2 else wav.float().numpy()
    if x.ndim > 1:
        x = x.mean(axis=0)
    sr = int(audio["sample_rate"])
    n = len(x)
    if n < sr * 0.5:
        return [(0.0, float(n) / sr)] if n > 0 else []
    hop = max(int(hop_s * sr), 1)
    win = max(int(win_s * sr), 64)
    win = min(win, n)
    hann = np.hanning(win)
    n_frames = max(1, 1 + (n - win) // hop)
    scores = np.zeros(n_frames)
    f = np.fft.rfftfreq(win, 1.0 / sr)
    lo = int(np.searchsorted(f, 300.0))
    hi = int(np.searchsorted(f, 3400.0, side="right"))
    prev_e = 0.0
    for k in range(n_frames):
        i = k * hop
        seg = x[i:i + win]
        if len(seg) < win:
            seg = np.pad(seg, (0, win - len(seg)))
        seg = seg * hann
        S = np.abs(np.fft.rfft(seg)) + 1e-8
        tot = S.sum()
        mid = S[lo:hi].sum() / tot if tot > 0 else 0.0
        harm = 1.0 - np.exp(np.log(S).mean()) / np.exp(np.log(tot) - np.log(len(S))) \
            if tot > 0 else 0.0
        harm = min(max(harm, 0.0), 1.0)
        e = np.sqrt((seg ** 2).mean())
        envj = min(abs(e - prev_e) / (e + 1e-8), 0.5) if e > 0 else 0.0
        prev_e = e
        scores[k] = mid * 1.0 + harm * 0.6 + envj * 0.8
    if sm_frames > 1:
        pad = min(sm_frames, n_frames)
        kernel = np.ones(pad) / pad
        scores = np.convolve(scores, kernel, mode="same")
    vocal = scores >= threshold
    segs = []
    start = None
    for k, v in enumerate(vocal):
        if v and start is None:
            start = k
        elif not v and start is not None:
            if (k - start) * hop_s >= min_len_s:
                segs.append([start * hop_s, k * hop_s])
            start = None
    if start is not None and (n_frames - start) * hop_s >= min_len_s:
        segs.append([start * hop_s, n_frames * hop_s])
    # 合并小间隙
    if merge_gap_s > 0:
        merged = []
        for s, e in segs:
            if merged and s - merged[-1][1] <= merge_gap_s:
                merged[-1][1] = e
            else:
                merged.append([s, e])
        segs = merged
    return [(round(s, 2), round(min(e, float(n) / sr), 2)) for s, e in segs]


def make_sing_note(audio, sing_detect=True):
    """sing 模式提示词：有歌声段对口型；纯音乐段(前奏/间奏/尾奏)表演不开口。"""
    if not sing_detect or audio is None:
        return LIP_NOTE_SING
    try:
        vocals = detect_vocal_segments(audio)
    except Exception:
        return LIP_NOTE_SING
    total = audio_seconds(audio)
    if not vocals:
        return ("\n该角色正在欣赏这段纯音乐并深情表演：表情、动作随音乐情绪起伏，"
                "双唇闭合、不唱歌不开口。")
    if len(vocals) == 1 and vocals[0][0] <= 0.3 and abs(vocals[0][1] - total) <= 0.3:
        return LIP_NOTE_SING  # 几乎整段都有人声：保持原描述
    # 时间轴分段描述：人声段演唱对口型，间隙段闭口表演
    parts = []
    cursor = 0.0
    for s, e in vocals:
        s = max(s, 0.0)
        e = min(e, total)
        if s > cursor + 0.25:
            parts.append(f"{cursor:.1f}-{s:.1f}秒 纯音乐表演：角色聆听/随音乐演绎情绪，"
                         f"双唇闭合不开口；")
        parts.append(f"{s:.1f}-{e:.1f}秒 演唱：嘴唇随歌声旋律开合，口型与歌词节拍精确同步；")
        cursor = e
    if total - cursor > 0.25:
        parts.append(f"{cursor:.1f}-{total:.1f}秒 纯音乐尾奏：角色表演情绪，双唇闭合不开口。")
    return "\n该角色正在演唱这首歌曲，口型与歌声按时间轴精确同步：\n" + "".join(parts)


# ---------------------------------------------------------------------------
# whisper large-v3 歌声分段 (v1.4, 2026-10-07):
#   启发式 detect_vocal_segments 区分不了伴奏与歌声(45s/263s 整段误判人声)，
#   已实测否决。改用本机 transformers whisper-large-v3 转写时间戳：
#   有文本 token 的时间窗 = 人声段(唱歌/说话)，无文本 = 纯音乐段。
#   全局歌检测一次 + 磁盘缓存(.vocal.json) + 进程内单例，渲染只付一次成本。
# ---------------------------------------------------------------------------
_WHISPER_STATE = {"proc": None, "model": None}
_WHISPER_MODEL_PATH = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "models", "whisper", "whisper-large-v3"))
_DEMUCS_STATE = {"model": None}
_VOCAL_CACHE_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "bsai_h3_chain_cache"))


def _demucs_load():
    """htdemucs 人声分离模型 进程内单例（加载约 90s，仅一次）。"""
    if _DEMUCS_STATE["model"] is not None:
        return _DEMUCS_STATE["model"]
    from demucs import pretrained
    model = pretrained.get_model("htdemucs")
    model = model.cuda()
    _DEMUCS_STATE["model"] = model
    return model


def _demucs_vocal_segments(wav_t, sr):
    """htdemucs 分离 vocals → 滑窗能量检测 → [(全局秒 start, end), ...]。

    wav_t: torch.Tensor (1, C, T)，44.1kHz。
    纯音乐段(前奏/间奏/尾奏)人声轨近静音 -> 低能量 -> 判不开口。
    """
    import numpy as np
    model = _demucs_load()
    try:
        from demucs import apply
        with torch.no_grad():
            est = apply.apply_model(
                model, wav_t.cuda(), shifts=0, split=True,
                segment=7.8, overlap=0.25, device="cuda", progress=False)
    except Exception as e:
        print(f"[H3 LipSync] demucs 分离失败({e}), 回退 whisper")
        return None
    vocals = est[0, model.sources.index("vocals")].cpu()  # (C, T)
    v = vocals.mean(0).numpy()
    n = len(v)
    win = int(0.2 * sr)
    rms = np.sqrt(np.convolve(v ** 2, np.ones(win) / win, mode="valid"))
    floor = float(np.percentile(rms, 5))
    thr = max(floor * 3.0, 0.002)
    seg_flag = rms > thr
    out = []
    start = None
    for i, b in enumerate(seg_flag):
        t = (i + win // 2) / sr
        if b and start is None:
            start = t
        elif not b and start is not None:
            if t - start >= 0.5:
                out.append((round(start, 2), round(t, 2)))
            start = None
    if start is not None and (n / sr) - start >= 0.5:
        out.append((round(start, 2), round(n / sr, 2)))
    merged = []
    for s, e in out:
        if merged and s - merged[-1][1] <= 0.5:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(round(s, 2), round(e, 2)) for s, e in merged if e - s >= 0.5]


def _whisper_load():
    """whisper large-v3 进程内单例（加载约 230s，仅一次）。"""
    if _WHISPER_STATE["model"] is not None:
        return _WHISPER_STATE["proc"], _WHISPER_STATE["model"]
    from transformers import WhisperProcessor, WhisperForConditionalGeneration
    proc = WhisperProcessor.from_pretrained(_WHISPER_MODEL_PATH)
    model = WhisperForConditionalGeneration.from_pretrained(
        _WHISPER_MODEL_PATH, torch_dtype=torch.bfloat16).to("cuda")
    model.config.forced_decoder_ids = None
    try:
        model.generation_config.forced_decoder_ids = None
    except Exception:
        pass
    _WHISPER_STATE["proc"] = proc
    _WHISPER_STATE["model"] = model
    return proc, model


def _resample_16k(x, sr):
    """numpy 线性插值重采样 → 16kHz 单声道 float32（whisper 输入）。"""
    import numpy as np
    if sr == 16000:
        return x.astype(np.float32)
    n_old = len(x)
    n_new = int(round(n_old * 16000.0 / sr))
    xi = np.arange(n_new) * (n_old - 1) / max(n_new - 1, 1)
    x0 = np.floor(xi).astype(int)
    x1 = np.clip(x0 + 1, 0, n_old - 1)
    w = (xi - x0).astype(np.float32)
    return (x[x0] * (1.0 - w) + x[x1] * w).astype(np.float32)


def _whisper_window_segs(proc, model, wav16, win_start_s, win_end_s):
    """转写一个 ≤30s 窗口，返回 (start_s, end_s) 人声区间列表（窗内相对秒）。"""
    chunk = wav16[int(win_start_s * 16000): int(win_end_s * 16000)]
    if chunk.shape[0] < 16000:
        return []
    feats = proc(chunk, sampling_rate=16000, return_tensors="pt").input_features
    feats = feats.to(device="cuda", dtype=torch.bfloat16)
    ids = model.generate(
        feats, return_timestamps=True, language="zh", task="transcribe",
        max_new_tokens=400,
    )
    tokens = proc.tokenizer.convert_ids_to_tokens(ids[0])
    # 时间戳 token <|12.34|> 与非时间戳文本 token 交替；
    # 文本 token 落在上一个时间戳与下一个时间戳之间 → 人声段。
    # special tokens（<|startoftranscript|>/<|zh|>/<|transcribe|>/<|endoftext|>…）
    # 一律跳过，避免把"前奏-首个时间戳"误标为人声。
    items = []
    for tk in tokens:
        m = re.match(r"^<\|(\d+\.\d{2})\|>$", tk)
        if m:
            items.append((float(m.group(1)), True))
        elif tk.startswith("<|"):
            continue
        else:
            items.append((None, False))
    segs = []
    start_t = None
    prev_t = None
    for t, is_ts in items:
        if is_ts:
            if start_t is not None and prev_t is not None:
                segs.append((start_t, t))
            start_t = None
            prev_t = t
        else:
            if start_t is None:
                start_t = prev_t if prev_t is not None else 0.0
    if start_t is not None and prev_t is not None:
        segs.append((start_t, prev_t))
    # 合并 0.5s 内相邻间隙
    merged = []
    for s, e in segs:
        if merged and s - merged[-1][1] <= 0.5:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    return [(round(max(0.0, s), 2), round(min(e, win_end_s - win_start_s), 2))
            for s, e in merged]


def _vocal_cache_info(global_audio):
    """全局音频轻量指纹 → 缓存路径（波形下采样 crc32 + 时长，防撞）。"""
    wav = global_audio["waveform"][0].mean(0)
    sr = int(global_audio["sample_rate"])
    ds = wav[::8]
    try:
        h = zlib.crc32(ds.numpy().astype("<f4").tobytes()) ^ sr
    except Exception:
        h = zlib.crc32(str(sr).encode()) ^ int(audio_seconds(global_audio))
    dur10 = int(round(audio_seconds(global_audio) * 10))
    name = f"vocal_{h:08x}_{dur10}.json"
    return os.path.join(_VOCAL_CACHE_DIR, name)


def vocal_segments_global(global_audio, method="demucs", force=False):
    """全局歌人声区间（v1.5: demucs 人声分离为主，whisper 为回退）。

    - demucs: htdemucs 分离 vocals + 能量检测（快且对带伴奏歌声准，
      263s 全歌约 1-2 分钟；纯音乐段人声轨近静音 -> 不开口）。
    - whisper: 保留作 fallback（大模型转写，慢且漏报歌声）。
    磁盘缓存 .vocal.json（带 method 标记）避免重复分离；进程内模型单例。
    返回 [(start_s, end_s), ...] 或 None。
    """
    if global_audio is None or global_audio.get("waveform") is None:
        return None
    cache_path = _vocal_cache_info(global_audio)
    if not force and os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("segs") and data.get("method") == method:
                print(f"[H3 LipSync] 歌声分段缓存命中: {os.path.basename(cache_path)} "
                      f"({len(data['segs'])} 段人声, {method})")
                return [tuple(x) for x in data["segs"]]
        except Exception:
            pass
    try:
        wav = global_audio["waveform"][0].float()  # (C, T)
        sr = int(global_audio["sample_rate"])
        if method == "demucs":
            print("[H3 LipSync] 歌声分段: htdemucs 分离人声轨 (首次约 1-2 分钟)...")
            segs = _demucs_vocal_segments(wav.unsqueeze(0), sr)
            if segs is None:
                return whisper_vocal_segments_global(global_audio, force=True)
        else:
            print("[H3 LipSync] whisper 歌声分段: 加载模型 + 转写全局歌 (首次约数分钟)...")
            segs = _whisper_global_segs(wav, sr)
        if not segs:
            return None
        os.makedirs(_VOCAL_CACHE_DIR, exist_ok=True)
        print(f"[H3 LipSync] 歌声分段完成: {len(segs)} 段人声 -> "
              f"缓存 {os.path.basename(cache_path)} ({method})")
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"method": method, "segs": [list(x) for x in segs]}, f)
        return segs
    except Exception as e:
        print(f"[H3 LipSync] 歌声分段失败(回退全段演唱): {e}")
        return None


def _whisper_global_segs(wav, sr):
    """whisper large-v3 全局转写 → 人声区间（保留作回退）。wav: (C, T) tensor。"""
    proc, model = _whisper_load()
    wav16 = _resample_16k(wav.mean(0).numpy(), int(sr))
    total_s = len(wav16) / 16000.0
    segs = []
    win = 10.0
    off = 0.0
    while off < total_s:
        end = min(off + win, total_s)
        if end - off >= 1.0:
            segs += _whisper_window_segs(proc, model, wav16, off, end)
        off = end
    segs.sort()
    merged = []
    for s, e in segs:
        if merged and s - merged[-1][1] <= 1.5:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    return [(round(s, 2), round(e, 2)) for s, e in merged]


def whisper_vocal_segments_global(global_audio, force=False):
    """兼容入口：whisper 歌声分段（deprecated，v1.5 主判据为 demucs）。"""
    if global_audio is None or global_audio.get("waveform") is None:
        return None
    cache_path = _vocal_cache_info(global_audio)
    if not force and os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("segs"):
                print(f"[H3 LipSync] 歌声分段缓存命中: {os.path.basename(cache_path)} "
                      f"({len(data['segs'])} 段人声)")
                return [tuple(x) for x in data["segs"]]
        except Exception:
            pass
    try:
        print("[H3 LipSync] whisper 歌声分段: 加载模型 + 转写全局歌 (首次约数分钟)...")
        segs = _whisper_global_segs(global_audio["waveform"][0].float(),
                                    int(global_audio["sample_rate"]))
        if not segs:
            return None
        try:
            os.makedirs(_VOCAL_CACHE_DIR, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({"method": "whisper",
                           "segs": [[round(s, 2), round(e, 2)] for s, e in segs]},
                          f, ensure_ascii=False)
        except Exception:
            pass
        return segs
    except Exception as e:
        print(f"[H3 LipSync] whisper 歌声分段失败(回退全段演唱): {e}")
        return None


def make_sing_note_clip(audio, global_vocals, seg_start, seg_end):
    """auto_cut 分段的 sing 提示词：全局人声区间投影到本 CLIP 时间轴。

    人声段 -> 演唱对口型；纯音乐段(前奏/间奏/尾奏) -> 表演不开口。
    global_vocals 为 None 时回退 make_sing_note(启发式兜底)。
    """
    total = audio_seconds(audio)
    if not global_vocals:
        return make_sing_note(audio, True)
    local = []
    for s, e in global_vocals:
        a = max(0.0, s - seg_start)
        b = min(total, e - seg_start)
        if b - a >= 0.3:
            local.append((round(a, 2), round(b, 2)))
    if not local:
        return ("\n该角色正在欣赏这段纯音乐并深情表演：表情、动作随音乐情绪起伏，"
                "双唇闭合、不唱歌不开口。")
    if len(local) == 1 and local[0][0] <= 0.3 and abs(local[0][1] - total) <= 0.3:
        return LIP_NOTE_SING
    parts = []
    cursor = 0.0
    for s, e in local:
        s = max(s, 0.0)
        e = min(e, total)
        if s > cursor + 0.25:
            parts.append(f"{cursor:.1f}-{s:.1f}秒 纯音乐表演：角色聆听/随音乐演绎情绪，"
                         f"双唇闭合不开口；")
        parts.append(f"{s:.1f}-{e:.1f}秒 演唱：嘴唇随歌声旋律开合，口型与歌词节拍精确同步；")
        cursor = e
    if total - cursor > 0.25:
        parts.append(f"{cursor:.1f}-{total:.1f}秒 纯音乐尾奏：角色表演情绪，双唇闭合不开口。")
    return "\n该角色正在演唱这首歌曲，口型与歌声按时间轴精确同步：\n" + "".join(parts)


def make_talk_note(clip, lip_cfg):
    """v1.81 口播/说话音频模式提示词。

    外部录音(口播/直播/相声/主持/对白)直接驱动口型：不做歌声分段，
    整段按「说话」演绎。若提供了 lip_text 文本，用 H3 官方 <d>…</d>
    逐字朗读标签加强口型同步；没有文本则只用行为描述。
    """
    text = str((clip or {}).get("lip_text") or (lip_cfg or {}).get("text") or "").strip()
    if text:
        return LIP_NOTE_TALK_TEXT.format(text=text)
    return LIP_NOTE_TALK


# ---------------------------------------------------------------------------
# 剧本唱段先验 (v1.4, 2026-10-07):
#   whisper 对带伴奏歌声严重漏报(263s 只报出前 22.9s)，不能单独作判据。
#   工作流每个分镜秒段都写明是否"唱"(用户按歌词拆的，与人声位置强相关)，
#   解析 clip prompt 的 "N-M秒 …唱：" 段 -> clip 内唱段，投影到全局歌偏移
#   后与 whisper 区间取并集：剧本补全 whisper 漏报，whisper 补全剧本没写的。
# ---------------------------------------------------------------------------
def parse_clip_sing_segments(clip):
    """解析单个 CLIP prompt 中标记"唱"的秒段 -> [(clip内秒 start, end), ...]。
    秒段格式 "0-3秒：…" / "3-6秒：…"，段内出现"唱："（含"苏清@图1唱："指令）
    即人声段。仅"歌唱""唱腔"等名词/形容词不含冒号 -> 不误判。
    """
    prompt = str(clip.get("prompt") or "")
    segs = []
    for m in re.finditer(r"(\d+)-(\d+)秒", prompt):
        a, b = int(m.group(1)), int(m.group(2))
        head = m.end()
        nxt = re.search(r"\d+-\d+秒", prompt[head:])
        seg_text = prompt[head: head + (nxt.start() if nxt else len(prompt))]
        if re.search(r"唱[：:]", seg_text):
            segs.append((float(a), float(b)))
    return segs


def merge_vocal_segments(script_segs, whisper_segs, min_span_s=0.5):
    """剧本唱段 ∪ whisper 区间 -> 合并后的全局人声区间（排序+间隙合并）。"""
    raw = list(script_segs or []) + list(whisper_segs or [])
    if not raw:
        return []
    raw = sorted((max(0.0, s), e) for s, e in raw)
    merged = []
    for s, e in raw:
        if merged and s - merged[-1][1] <= 0.5:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(round(s, 2), round(e, 2)) for s, e in merged if e - s >= min_span_s]


def resolve_clip_lip(clip, lip_cfg, audios, clip_index=0):
    """解析单个 CLIP 的对口型配置。

    返回 (audio, note, eff_duration, warn, src, note_kind)：
      audio       : AUDIO dict 或 None（无口型 / 降级）
      note        : 要追加进该 CLIP prompt 的提示词片段（str）或 None
      eff_duration: 对口型音频对齐后的 CLIP 时长（秒，覆盖剧本时长）或 None
      warn        : 提示信息（str）或 None
      src         : 本 CLIP 对口型音频来源 "tts"/"card"/"global"/None
      note_kind   : "speech"/"sing"/"speech_audio"/None（供 build_clip_lips 分支用）
    """
    raw_mode = clip.get("lip_mode") or lip_cfg.get("mode") or "off"
    mode = normalize_lip_mode(raw_mode)
    warn = None

    if mode == MODE_OFF:
        return None, None, None, None, None, None
    if mode == MODE_INVALID:
        warn = (f"clip[{clip_index}] lip_mode='{raw_mode}' 无效，已按 off 处理"
                f"（可选: off / speech / sing / speech_audio）。")
        return None, None, None, warn, None, None

    is_speech = mode == MODE_SPEECH
    is_talk = mode == MODE_TALK

    audio = None
    note = None
    eff_duration = None
    src = None
    note_kind = mode

    if is_speech:
        text = str(clip.get("lip_text") or lip_cfg.get("text") or "").strip()
        if not text:
            warn = f"clip[{clip_index}] 为 speech 模式但无 lip_text 说话文本，已按 off 处理。"
            return None, None, None, warn, None, None
        # 声线参考：CLIP 卡片 lip_voice(@音频N) → 该 CLIP prompt 已引用的 @音频N → 节点 lip_voice
        voice = None
        voice_path = _resolve_audio_ref_str(clip.get("lip_voice", ""), audios)
        if voice_path and os.path.exists(voice_path):
            voice = load_audio_file(voice_path)
        if voice is None:
            clip_audio_paths = clip.get("ref_audio_paths") or []
            if clip_audio_paths and os.path.exists(str(clip_audio_paths[0])):
                voice = load_audio_file(str(clip_audio_paths[0]))
        if voice is None:
            voice = lip_cfg.get("voice")
        try:
            audio = tts_speech(
                lip_cfg.get("tts_model"),
                text,
                voice,
                lang=str(lip_cfg.get("lang") or "ZH"),
                duration_factor=float(lip_cfg.get("duration_factor") or 1.0),
            )
        except Exception as e:
            raise RuntimeError(f"[H3 LipSync] clip[{clip_index}] 语音合成失败: {e}") from e
        note = LIP_NOTE_SPEECH.format(text=text)
        src = "tts"
    else:  # sing / speech_audio（口播/相声/主持/直播录音）
        # 音频来源：CLIP 卡片 lip_audio(@音频N) → CLIP prompt 已引用的 @音频N → 节点 lip_audio
        sing_path = _resolve_audio_ref_str(clip.get("lip_audio", ""), audios)
        if sing_path and os.path.exists(sing_path):
            audio = load_audio_file(sing_path)
            src = "card"
        if audio is None:
            clip_audio_paths = clip.get("ref_audio_paths") or []
            if clip_audio_paths and os.path.exists(str(clip_audio_paths[0])):
                audio = load_audio_file(str(clip_audio_paths[0]))
                src = "card"
        # 全局音频 fallback：仅在自动切段关闭时直接把整段给本 CLIP（旧行为）。
        # auto_cut=True 时全局音频由 build_clip_lips 按顺序切段分发，这里不占用。
        if audio is None and not bool(lip_cfg.get("auto_cut", True)):
            audio = lip_cfg.get("audio")
            src = "global" if audio is not None else None
        if audio is None or audio.get("waveform") is None:
            _kind = "说话/口播音频" if is_talk else "歌曲音频"
            warn = (f"clip[{clip_index}] 为 {mode} 模式但未找到{_kind}：请在 CLIP 卡片 lip_audio 填 "
                    f"@音频N、或在 prompt 中引用 @音频N、或把 AUDIO 接到节点 lip_audio 输入。已按 off 处理。")
            return None, None, None, warn, None, None
        note = make_talk_note(clip, lip_cfg) if is_talk else LIP_NOTE_SING

    # 时长对齐（fit_duration=True 音频优先；False 剧本优先）
    clip_dur = float(clip.get("duration") or 5.0)
    audio, eff_duration = _align_audio_to_fit(audio, clip_dur, lip_cfg, clip_index)

    return audio, note, eff_duration, warn, src, note_kind


def build_clip_lips(clips, lip_cfg, asset_library):
    """为所有 CLIP 构建对口型配置。

    返回 (clip_lip_audios, lip_notes, lip_durations, warns, lip_plans)：
      前四项与 clips 等长；无口型的 CLIP 对应 None。
      lip_plans: 与 clips 等长的「成片音轨切片计划」，元素为 dict 或 None：
        {"use": True,  "start": 秒, "dur": 秒} —— 成片本段音轨 = 外部歌的该片段；
        {"use": False, "reason": ...}          —— 成片本段保留模型生成音频。
        extender 把它落盘到 <chain>.audiotrack.wav.json，解码阶段据此精确切片，
        与模型侧消费游标同源 → 消除两套 offset 不一致造成的逐段漂移。
    v1.1 (2026-10-06) 新增「自动切段」：
      某 CLIP 无独立音频（卡片 lip_audio / prompt @音频N / ref_audio_paths 均无），
      且节点全局 lip_audio 有音频 且 lip_auto_cut_自动切段=True 时，
      按 CLIP 顺序 + 各 CLIP 剧本 duration 自动顺序切段：
        CLIP0 -> [0, d0), CLIP1 -> [d0, d0+d1), CLIP2 -> [d0+d1, ...) ...
      全局音频耗尽后剩余 CLIP 按 off 处理并提示。
    v1.2 (2026-10-07) 自适应切段：完全跟随每个 CLIP 有效时长——
      目标 = CLIP 剧本 duration（≠15s 完全支持）；fit_duration=True 时对齐
      H3 17n+5 帧网格（单段上限 362帧/15.08s）；切片不短于渲染帧数；
      游标按实际消费（网格时长）前进，段与段无缝衔接。
    v1.81 (2026-10-07)：
      (1) 新增 speech_audio（口播/说话音频）模式，与 sing 共用切段逻辑；
      (2) 只有真的存在 sing CLIP 时才做人声分离（口播模式跳过 demucs）；
      (3) fit_duration=False 时切片长度改为「渲染实际时长（17n+5 向下取网格）」，
          不再用剧本 duration —— 旧版会让模型听到的音频长于渲染画面并逐段漂移；
      (4) 两种模式下切段游标都按实际渲染时长前进，并输出 lip_plans 供成片音轨精确切片。
    """
    audios = []
    if isinstance(asset_library, dict):
        audios = asset_library.get("audios", []) or []
    elif isinstance(asset_library, (list, tuple)):
        audios = list(asset_library)

    clip_lip_audios = []
    lip_notes = []
    lip_durations = []
    warns = []
    lip_plans = []
    auto_cut = bool(lip_cfg.get("auto_cut", True))
    cut_cursor = 0.0  # 自动切段游标（秒）
    global_audio = lip_cfg.get("audio")

    # v1.81: 预判各 CLIP 模式 —— 只有存在 sing CLIP 才做歌声分段
    # (htdemucs 人声分离为主判据，whisper 回退；缓存+单例)。
    # 口播/说话音频模式不做分离（省掉首次 1-2 分钟，也避免把语音误判成纯音乐）。
    clip_modes = [
        normalize_lip_mode((c or {}).get("lip_mode") or lip_cfg.get("mode") or "off")
        for c in clips
    ]
    global_vocals = None
    if auto_cut and bool(lip_cfg.get("sing_detect", True)) and MODE_SING in clip_modes:
        global_vocals = vocal_segments_global(global_audio)
    seg_start = seg_end = None
    for i, clip in enumerate(clips):
        (audio, note, eff_duration, warn,
         src, note_kind) = resolve_clip_lip(clip, lip_cfg, audios, clip_index=i)
        mode = clip_modes[i] if i < len(clip_modes) else MODE_OFF
        # 有独立音频源（卡片 @音频N / TTS）时，成片音轨无法从全局歌里切出对应片段
        plan = {"use": False, "reason": src or "off"} if audio is not None else None
        if src == "global" and audio is not None:
            # auto_cut=False：本 CLIP 用整段全局音频（旧行为），成片音轨取同一段
            render_sec = float(eff_duration) if eff_duration is not None else (
                _duration_to_frames(float(clip.get("duration") or 5.0)) / float(FPS)
            )
            # v1.81: 计划里的 start/dur 不做四舍五入 —— 段与段必须严格首尾相接,
            # 任何取整都会逐段累积微小偏移(4 位小数 = 0.1ms/段)。
            plan = {"use": True, "start": 0.0, "dur": float(render_sec)}

        # ── 自动切段：CLIP 无独立音频 + 全局有音频 + auto_cut + sing/口播 模式 ──
        if (audio is None and global_audio is not None
                and global_audio.get("waveform") is not None and auto_cut):
            if mode in (MODE_SING, MODE_TALK):
                clip_dur = float(clip.get("duration") or 5.0)
                fit_duration = bool(lip_cfg.get("fit_duration", True))
                # v1.2 自适应切段 (2026-10-07): 完全跟随本 CLIP 有效时长——
                #   目标时长 = CLIP 剧本 duration(≠15s 完全支持);
                #   fit_duration=True 时对齐到 H3 17n+5 帧网格(单段上限 362帧/15.08s,
                #   超过 15s 由模型约束截断, 切分按实际渲染消费前进, 歌不丢不重);
                #   切片长度 = max(剧本时长, 网格时长), 保证音频不短于渲染帧数;
                #   游标按实际消费(网格时长)前进, 段与段无缝衔接。
                # v1.81 (2026-10-07): fit_duration=False 时也改为按「渲染实际时长」
                #   (_duration_to_frames 向下取网格, 与渲染层 frame_count 完全一致),
                #   旧版按 clip_dur 切片会让模型听到的音频长于渲染画面, 且成片音轨
                #   按累计帧切片 → 每段错开 (clip_dur - 网格时长), 逐段累积漂移。
                if fit_duration:
                    eff_frames = _frames_nearest(max(0.5, min(15.0, clip_dur)))
                    eff_sec = eff_frames / float(FPS)
                    eff_duration = eff_sec  # 渲染/口型实际时长(帧网格对齐)
                else:
                    eff_frames = _duration_to_frames(clip_dur)  # 与渲染层一致(向下取网格)
                    eff_sec = eff_frames / float(FPS)
                    eff_duration = None  # 不覆盖剧本时长(渲染层算出的帧数与此一致)
                need_sec = max(float(clip_dur), float(eff_sec))
                seg = slice_audio(global_audio, cut_cursor, need_sec)
                if seg is None:
                    warn = (f"clip[{i}] 自动切段: 全局音频已耗尽(累计 {cut_cursor:.1f}s, "
                            f"总长 {audio_seconds(global_audio):.1f}s), 已按 off 处理。")
                    plan = {"use": False, "reason": "audio_exhausted"}
                else:
                    seg_sec = audio_seconds(seg)
                    if fit_duration:
                        # 尾部音频不足(网格时长超可用音频): CLIP 时长降级跟随
                        # 实际可用音频(音频优先, 口型不短于渲染帧数)。
                        _avail = max(0.5, min(eff_sec, seg_sec))
                        _frames = _frames_nearest(_avail)
                        if _frames / float(FPS) > seg_sec + 0.001:
                            _frames = int(seg_sec * FPS) // 17 * 17 + 5
                            if _frames < 5:
                                _frames = 5
                        eff_sec = _frames / float(FPS)
                        eff_duration = eff_sec
                    elif eff_sec > seg_sec + 0.05:
                        # fit_duration=False 且歌已接近尾声: 渲染帧数由剧本决定,
                        # 音频短于画面 → 成片该段尾部补零静音(切片仍按 eff_sec 计),
                        # 明示告警, 不做静默降级。
                        _tail_warn = (f"clip[{i}] 自动切段: 剩余音频 {seg_sec:.2f}s 短于渲染时长 "
                                      f"{eff_sec:.2f}s, 成片该段尾部将补静音(剧本时长优先)。")
                        warns.append(_tail_warn)
                        print(f"[H3 LipSync] {_tail_warn}")
                    # v1.81: 两种模式都裁到「实际渲染时长 + 0.1s 余量」——
                    # 保证模型听到的音频与渲染帧数一一对应, 成片切片口径一致。
                    audio = trim_audio(seg, eff_sec + 0.1)
                    seg_start = cut_cursor
                    cut_cursor += eff_sec  # 两种模式统一按实际渲染时长前进
                    seg_end = cut_cursor
                    note_kind = mode
                    note = make_talk_note(clip, lip_cfg) if mode == MODE_TALK else LIP_NOTE_SING
                    plan = {"use": True, "start": float(seg_start), "dur": float(eff_sec)}
                    warn = None  # 自动切段成功: 丢弃 resolve_clip_lip 的"未找到音频"提示
                    print(f"[H3 LipSync] clip[{i}] 自动切段: [{seg_start:.2f}s~{seg_end:.2f}s] "
                          f"段长{seg_sec:.2f}s -> CLIP {audio_seconds(audio):.2f}s "
                          f"({mode}, 自适应时长, fit_duration={fit_duration})")

        # v1.4: sing 提示词按歌声分段注入(纯音乐段不开口)
        # v1.81: 用 note_kind 判定分支(提示词文本可能带 <d> 台词, 不能用字符串比较)
        if audio is not None and note_kind == MODE_SING:
            if seg_start is not None:
                # 剧本唱段(CLIP prompt "N-M秒…唱：")投影到全局偏移
                script_global = [
                    (seg_start + s, seg_start + e)
                    for s, e in parse_clip_sing_segments(clip)
                ]
                # 剧本 ∪ whisper（whisper 漏报歌声，剧本补全；剧本没写的间奏/尾奏自然判纯音乐）
                vocal_global = merge_vocal_segments(script_global, global_vocals)
                note = make_sing_note_clip(audio, vocal_global, seg_start, seg_end)
            else:
                note = make_sing_note(audio, bool(lip_cfg.get("sing_detect", True)))
        elif audio is not None and note_kind == MODE_TALK:
            # v1.81 口播/说话音频：不做歌声分段, 整段按说话对口型
            note = make_talk_note(clip, lip_cfg)
        if seg_start is not None:
            seg_start = seg_end = None  # 每 CLIP 只消费一次游标区间

        # v1.81: 成片音轨切片计划缺失/不适用时明示原因(避免静默混源)
        if plan is None:
            plan = {"use": False, "reason": "no_lip"}
        elif not plan.get("use") and audio is not None:
            _why = str(plan.get("reason") or "")
            if _why in ("card", "tts"):
                _w = (f"clip[{i}] 对口型音频来自独立源({_why}), 成片该段音轨保留模型生成音频"
                      f"(外部全局音频只驱动口型, 不替换该段)")
                warns.append(_w)
                print(f"[H3 LipSync] {_w}")

        clip_lip_audios.append(audio)
        lip_notes.append(note)
        lip_durations.append(eff_duration)
        lip_plans.append(plan)
        if warn:
            warns.append(warn)
            print(f"[H3 LipSync] {warn}")
        if audio is not None:
            print(f"[H3 LipSync] clip[{i}] 对口型音频就绪: {audio_seconds(audio):.2f}s "
                  f"({mode_label_of(mode)}) 成片音轨={plan}")

    # v1.81: 外部音轨覆盖核对（歌曲/录音完整性）
    #   要点：上下文重叠帧(如 22 帧)只出现在"模型条件"里, 不占用成片时间轴 ——
    #   每段消费的音频 = 本段自身渲染时长(网格帧数/24), 段间严格首尾相接。
    #   这里把「音频总长 vs 所有 CLIP 覆盖到的时间」摊开打印, 缺口一眼可见。
    try:
        if global_audio is not None and global_audio.get("waveform") is not None:
            _song = audio_seconds(global_audio)
            _used = [p for p in lip_plans if isinstance(p, dict) and p.get("use")]
            _covered = max(
                (float(p.get("start", 0.0)) + float(p.get("dur", 0.0)) for p in _used),
                default=0.0,
            )
            _unused_clips = [
                i + 1 for i, p in enumerate(lip_plans)
                if isinstance(p, dict) and not p.get("use")
            ]
            print(f"[H3 LipSync] 外部音轨覆盖核对: 音频 {_song:.2f}s, "
                  f"{len(_used)}/{len(lip_plans)} 段使用外部音轨, 覆盖 [0, {_covered:.2f})s")
            if _song - _covered > 0.5:
                print(f"[H3 LipSync] ⚠️ 歌曲还有 {_song - _covered:.2f}s 没被用到 —— "
                      f"所有 CLIP 时长之和不足。要完整覆盖请增加 CLIP 或加长时长"
                      f"(单 CLIP 上限 15.083s / 362 帧, 17n+5 网格)。")
            elif _covered - _song > 0.5:
                print(f"[H3 LipSync] ⚠️ CLIP 总时长超出音频 {_covered - _song:.2f}s —— "
                      f"超出部分没有音频可用, 这些段会退回模型音频/补静音。")
            if _unused_clips:
                _show = _unused_clips[:12]
                _more = "" if len(_unused_clips) <= 12 else f" …共{len(_unused_clips)}段"
                print(f"[H3 LipSync] ⚠️ 以下 CLIP 成片音轨保留模型音频: {_show}{_more}"
                      f"（off/说话TTS/卡片独立音频/音频已耗尽, 详见上面的 plan 与告警）")
    except Exception as _cov_e:
        print(f"[H3 LipSync] 覆盖核对跳过(不影响渲染): {_cov_e}")

    return clip_lip_audios, lip_notes, lip_durations, warns, lip_plans


def mode_label_of(mode):
    if mode == MODE_SPEECH:
        return "speech 说话(TTS)"
    if mode == MODE_SING:
        return "sing 唱歌"
    if mode == MODE_TALK:
        return "speech_audio 口播/说话音频"
    return "off"


def mode_label(clip, lip_cfg):
    return mode_label_of(
        normalize_lip_mode(clip.get("lip_mode") or lip_cfg.get("mode") or "off")
    )
