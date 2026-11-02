"""BSAI 声音克隆节点 - 封装 IndexTTS-2.5 声音克隆（单人 + 多人对话）。

单人模式（BSAIVoiceClone）：参考音频 + 文本 → 克隆语音（向后兼容）
多人对话模式（BSAIDialogueVoiceClone）：对话脚本 + 多参考音频 → 完整对话音频

多人对话脚本格式（自动识别以下所有格式）：
  角色名: 台词内容
  角色名：台词内容
  【角色名】台词内容
  【角色名】：台词内容
  角色说："台词内容"
  @图1: 台词内容       ← 直接用 @图N 标签引用资产库中对应角色
  @音频1: 台词内容      ← 直接用 @音频N 标签引用参考音色

输出:
  - AUDIO: 克隆后的语音（单人）/ 拼接完整对话音频（多人）
  - STRING: 合成日志
"""

import re
import os
import sys
import tempfile
import traceback

import torch
import numpy as np
import folder_paths


# ===========================================================================
#  对话脚本解析器 —— 灵活识别多种格式的说话人+台词行
# ===========================================================================

# 标准格式：角色名[:：]台词    （角色名不含冒号，台词在冒号之后）
_DIALOGUE_COLON_RE = re.compile(
    r"^\s*([^\s:：\[【\]】\n]{1,20})\s*[:：]\s*(.+?)\s*$"
)
# 方括号/括号格式：【角色名】台词 或 [角色名]台词
_DIALOGUE_BRACKET_RE = re.compile(
    r"^\s*[【\[]([^\]】\s]{1,20})[】\]]\s*[:：]?\s*(.+?)\s*$"
)
# @图N / @音频N 引用格式：@图1: 台词 或 @音频1: 台词
_DIALOGUE_ASSET_RE = re.compile(
    r"^\s*@\s*(图|音频|img|aud)\s*(\d+)\s*[:：]\s*(.+?)\s*$",
    re.IGNORECASE,
)
# 角色说："台词" 格式（双引号包裹正则，内部用单引号/中文引号）
_QUOTE_OPEN = '\u201c\u300c\u300e"\''  # 「」『』""'"
_QUOTE_CLOSE = '\u201d\u300d\u300f"\''
_DIALOGUE_QUOTE_RE = re.compile(
    r"^\s*([^\s:：\[\]【】\n]{1,15})\s*说\s*[:：]\s*[" + _QUOTE_OPEN + r"](.+?)[" + _QUOTE_CLOSE + r"]\s*$"
)


def parse_dialogue_script(script, speaker_ref_map=None):
    """解析多人对话脚本，返回 [(speaker_key, text, asset_index_or_None), ...]

    Args:
        script: 多行对话脚本文本
        speaker_ref_map: 可选的 {角色名: 资产索引} 映射（如 {"小明": 1, "小红": 2}）
                         用于自动关联 @图N / @音频N 资产

    Returns:
        list of dict: [{"speaker": str, "text": str, "asset_index": int|None}, ...]
    """
    if not script or not script.strip():
        return []

    lines = script.strip().splitlines()
    results = []
    last_speaker = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        # 1) @图N / @音频N 格式
        m = _DIALOGUE_ASSET_RE.match(line)
        if m:
            asset_type = m.group(1).lower()
            asset_idx = int(m.group(2))
            text = m.group(3).strip()
            speaker = f"asset_{asset_type}_{asset_idx}"
            results.append({"speaker": speaker, "text": text, "asset_index": asset_idx})
            last_speaker = speaker
            continue

        # 2) 方括号格式：【角色名】台词
        m = _DIALOGUE_BRACKET_RE.match(line)
        if m:
            speaker = m.group(1).strip()
            text = m.group(2).strip()
            asset_idx = speaker_ref_map.get(speaker) if speaker_ref_map else None
            results.append({"speaker": speaker, "text": text, "asset_index": asset_idx})
            last_speaker = speaker
            continue

        # 3) 角色说："台词" 格式
        m = _DIALOGUE_QUOTE_RE.match(line)
        if m:
            speaker = m.group(1).strip()
            text = m.group(2).strip()
            asset_idx = speaker_ref_map.get(speaker) if speaker_ref_map else None
            results.append({"speaker": speaker, "text": text, "asset_index": asset_idx})
            last_speaker = speaker
            continue

        # 4) 标准冒号格式：角色名: 台词
        m = _DIALOGUE_COLON_RE.match(line)
        if m:
            speaker = m.group(1).strip()
            text = m.group(2).strip()
            # 过滤掉非对话行（如 "镜头运动："、"画面描述："、"音乐：" 等）
            _non_dialogue_tags = {"镜头", "景别", "构图", "画面", "音效", "音乐",
                                  "BGM", "bgm", "环境音", "描述", "运动", "转场",
                                  "时长", "秒", "灯光", "光影", "场景"}
            if speaker in _non_dialogue_tags:
                continue
            asset_idx = speaker_ref_map.get(speaker) if speaker_ref_map else None
            results.append({"speaker": speaker, "text": text, "asset_index": asset_idx})
            last_speaker = speaker
            continue

        # 5) 续行（没有冒号，归到上一个说话人）
        if last_speaker is not None and results:
            results[-1]["text"] += line
            continue

        # 6) 无法识别 → 跳过（可能是画面描述/分镜标题）
        continue

    # 清理空台词
    results = [r for r in results if r["text"].strip()]
    return results


def crossfade_concat(audio_segments, sample_rate, fade_ms=50):
    """将多段音频用交叉淡化拼接成一段。

    Args:
        audio_segments: list of torch.Tensor, each [1, 1, T] 或 [T]
        sample_rate: 采样率
        fade_ms: 交叉淡化毫秒数

    Returns:
        torch.Tensor [1, 1, total_samples]
    """
    if not audio_segments:
        raise ValueError("No audio segments to concatenate")
    if len(audio_segments) == 1:
        seg = audio_segments[0]
        if seg.dim() == 1:
            seg = seg.unsqueeze(0).unsqueeze(0)
        elif seg.dim() == 2:
            seg = seg.unsqueeze(0)
        return seg

    fade_samples = int(sample_rate * fade_ms / 1000)
    # 上限 200ms 的采样点数，避免短台词淡入淡出过长
    fade_samples = min(fade_samples, int(sample_rate * 0.2))

    def _prepare(seg):
        if seg.dim() == 1:
            seg = seg.unsqueeze(0).unsqueeze(0)
        elif seg.dim() == 2:
            seg = seg.unsqueeze(0)
        return seg.float()

    prepared = [_prepare(s) for s in audio_segments]

    # 如果某段太短 → 直接无交叉拼接（避免 fade_samples 超过段长）
    _min_len = fade_samples * 2 + 100
    all_long = all(s.shape[-1] >= _min_len for s in prepared)

    if not all_long:
        return torch.cat(prepared, dim=-1)

    # 线性交叉淡化（首尾各 fade_samples 毫秒淡入淡出）
    fade_in = torch.linspace(0, 1, fade_samples)
    fade_out = torch.linspace(1, 0, fade_samples)

    result = prepared[0]
    for next_seg in prepared[1:]:
        result_len = result.shape[-1]
        if result_len < fade_samples or next_seg.shape[-1] < fade_samples:
            result = torch.cat([result, next_seg], dim=-1)
            continue

        overlap_res = result[:, :, -fade_samples:] * fade_out
        overlap_next = next_seg[:, :, :fade_samples] * fade_in

        result_no_overlap = result[:, :, :-fade_samples]
        next_no_overlap = next_seg[:, :, fade_samples:]

        result = torch.cat([result_no_overlap, overlap_res + overlap_next, next_no_overlap], dim=-1)

    return result


# ===========================================================================
#  单人声音克隆节点（保留，向后兼容）
# ===========================================================================

class BSAIVoiceClone:
    """一键声音克隆：参考音频 + 文本 → 克隆语音。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "tts_model": ("INDEX_TTS_MODEL", {"tooltip": "IndexTTS-2.5 model"}),
                "text": ("STRING", {"multiline": True,
                                    "default": "Hello, this is a voice clone test.",
                                    "tooltip": "Text to synthesize"}),
                "reference_audio": ("AUDIO", {"tooltip": "Reference voice sample (3-10s clean dry voice)"}),
            },
            "optional": {
                "lang": (["ZH", "EN", "JA", "ES", "AR"], {"default": "ZH",
                         "tooltip": "Language"}),
                "duration_factor": ("FLOAT", {"default": 1.0, "min": 0.5, "max": 2.0,
                                    "step": 0.05, "tooltip": "Speech rate"}),
            }
        }

    RETURN_TYPES = ("AUDIO", "STRING")
    RETURN_NAMES = ("audio", "status")
    FUNCTION = "clone"
    CATEGORY = "BSAI/Voice"
    DESCRIPTION = "Single-speaker voice cloning: one reference audio + one text → cloned speech. Connect output directly to Film Factory lip_audio port for lip-sync."

    def clone(self, tts_model, text, reference_audio, lang="ZH", duration_factor=1.0):
        return _synthesize_one(tts_model, text, reference_audio, lang, duration_factor)


# ===========================================================================
#  多人对话声音克隆节点（核心新增）
# ===========================================================================

class BSAIDialogueVoiceClone:
    """多人对话声音克隆：对话脚本 + 多参考音频 → 拼接完整对话音频。

    自动解析对话脚本中的说话人，按说话人分配对应参考音频，
    逐个调用 IndexTTS 合成，最后自动交叉淡化拼接成一段完整音频。

    参考音频绑定优先级：
      1) 脚本中使用 @图N / @音频N → 直接匹配 asset_index=N 的参考音频
      2) speaker_map 中明确映射的角色名 → 参考音频索引
      3) 未映射的角色 → 按出现顺序依次分配 ref_audio_1, ref_audio_2, ...
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "tts_model": ("INDEX_TTS_MODEL", {"tooltip": "IndexTTS-2.5 model (from BSAI_IndexTTS2.5Loader)"}),
                "dialogue_script": ("STRING", {
                    "multiline": True,
                    "default": (
                        "小明: 大家好，欢迎来到我们的直播间！\n"
                        "小红: 是的，今天给大家带来了很多超值好物~\n"
                        "小明: 首先是这款面膜，补水效果超级棒！\n"
                        "小红: 没错，我自己也在用，价格也非常优惠。"
                    ),
                    "tooltip": (
                        "Multi-speaker dialogue script.\n"
                        "Supported formats:\n"
                        "  角色名: 台词内容\n"
                        "  【角色名】台词内容\n"
                        "  @图1: 台词内容  ← asset reference\n"
                        "  @音频2: 台词内容"
                    ),
                }),
            },
            "optional": {
                # --- 多参考音频输入（AutoGrow 风格：用可选端口覆盖最大 6 人） ---
                "ref_audio_1": ("AUDIO", {"tooltip": "Reference audio for speaker 1 (matches role @图1 / first unmapped role)"}),
                "ref_audio_2": ("AUDIO", {"tooltip": "Reference audio for speaker 2"}),
                "ref_audio_3": ("AUDIO", {"tooltip": "Reference audio for speaker 3"}),
                "ref_audio_4": ("AUDIO", {"tooltip": "Reference audio for speaker 4"}),
                "ref_audio_5": ("AUDIO", {"tooltip": "Reference audio for speaker 5"}),
                "ref_audio_6": ("AUDIO", {"tooltip": "Reference audio for speaker 6"}),
                # --- 角色映射（可选：显式指定角色名→ref_audio_N） ---
                "speaker_map": ("STRING", {
                    "multiline": False,
                    "default": "",
                    "tooltip": (
                        "Role-to-reference mapping (optional).\n"
                        "Format: 角色名=ref_index,角色名=ref_index\n"
                        "Example: 小明=1,小红=2,主播=1\n"
                        "If left empty, auto-mapping is used."
                    ),
                }),
                # --- 合成参数 ---
                "lang": (["ZH", "EN", "JA", "ES", "AR"], {"default": "ZH",
                         "tooltip": "Language (all speakers use the same)"}),
                "duration_factor": ("FLOAT", {"default": 1.0, "min": 0.5, "max": 2.0,
                                    "step": 0.05, "tooltip": "Overall speech rate multiplier"}),
                "crossfade_ms": ("INT", {"default": 80, "min": 0, "max": 300, "step": 10,
                               "tooltip": "Crossfade duration between lines (ms). 0 = hard splice."}),
                "pause_ms": ("INT", {"default": 0, "min": 0, "max": 1000, "step": 50,
                            "tooltip": "Extra silence between lines (ms). Added BEFORE crossfade."}),
            }
        }

    RETURN_TYPES = ("AUDIO", "STRING")
    RETURN_NAMES = ("audio", "log")
    FUNCTION = "synthesize_dialogue"
    CATEGORY = "BSAI/Voice"
    DESCRIPTION = (
        "Multi-speaker dialogue voice cloning: input a full conversation script "
        "+ reference voices for each speaker → outputs a single concatenated audio track. "
        "Supports @图N / @音频N asset reference tags and auto-role-to-voice mapping. "
        "Connect output to Film Factory lip_audio for multi-character lip-sync."
    )

    def synthesize_dialogue(
        self,
        tts_model,
        dialogue_script,
        ref_audio_1=None,
        ref_audio_2=None,
        ref_audio_3=None,
        ref_audio_4=None,
        ref_audio_5=None,
        ref_audio_6=None,
        speaker_map="",
        lang="ZH",
        duration_factor=1.0,
        crossfade_ms=80,
        pause_ms=0,
    ):
        log_lines = []

        # --- Step 1: 解析 speaker_map ---
        parsed_map = {}
        if speaker_map and speaker_map.strip():
            try:
                for pair in speaker_map.split(","):
                    pair = pair.strip()
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        k = k.strip()
                        v = v.strip()
                        try:
                            parsed_map[k] = int(v)
                        except ValueError:
                            log_lines.append(f"  [WARN] Invalid speaker_map entry: {pair}")
            except Exception as e:
                log_lines.append(f"  [WARN] speaker_map parse error: {e}")
        log_lines.append(f"[DialogueClone] Speaker map: {parsed_map or '(auto)'}")

        # --- Step 2: 解析对话脚本 ---
        dialogue_lines = parse_dialogue_script(dialogue_script, parsed_map)
        if not dialogue_lines:
            raise ValueError(
                "No dialogue lines parsed from script. "
                "Please use format: 角色名: 台词内容  or 【角色名】台词"
            )
        log_lines.append(f"[DialogueClone] Parsed {len(dialogue_lines)} dialogue lines")

        # --- Step 3: 收集可用参考音频 ---
        ref_pool = {}
        _all_refs = [
            (1, ref_audio_1), (2, ref_audio_2), (3, ref_audio_3),
            (4, ref_audio_4), (5, ref_audio_5), (6, ref_audio_6),
        ]
        for idx, ref in _all_refs:
            if ref is not None:
                ref_pool[idx] = ref
        if not ref_pool:
            raise ValueError("At least one ref_audio_N must be connected for voice cloning.")
        log_lines.append(f"[DialogueClone] {len(ref_pool)} reference voices connected: ref_audio_{sorted(ref_pool.keys())}")

        # --- Step 4: 为每个说话人分配参考音频 ---
        # 先收集所有出现的 speaker
        speaker_assignments = {}  # speaker_key -> ref_index
        auto_counter = 0

        for dlg in dialogue_lines:
            spk = dlg["speaker"]
            if spk in speaker_assignments:
                continue

            # 优先级1: asset_index 直接指定
            if dlg.get("asset_index") is not None:
                ai = dlg["asset_index"]
                if ai in ref_pool:
                    speaker_assignments[spk] = ai
                    log_lines.append(f"  [ASSIGN] '{spk}' → ref_audio_{ai} (asset reference)")
                    continue
                else:
                    log_lines.append(f"  [WARN] '{spk}' requests asset {ai} but ref_audio_{ai} not connected, using auto-assign")

            # 优先级2: speaker_map 已映射
            if spk in parsed_map:
                mi = parsed_map[spk]
                if mi in ref_pool:
                    speaker_assignments[spk] = mi
                    log_lines.append(f"  [ASSIGN] '{spk}' → ref_audio_{mi} (speaker_map)")
                    continue
                else:
                    log_lines.append(f"  [WARN] speaker_map assigns '{spk}'→ref_audio_{mi} but not connected")

            # 优先级3: 按出现顺序自动分配
            auto_counter += 1
            # 找下一个可用的 ref_pool key
            available_keys = sorted(ref_pool.keys())
            if auto_counter <= len(available_keys):
                chosen = available_keys[auto_counter - 1]
            else:
                # 循环复用（场景：说话人多于参考音频数）
                chosen = available_keys[(auto_counter - 1) % len(available_keys)]
            speaker_assignments[spk] = chosen
            log_lines.append(f"  [ASSIGN] '{spk}' → ref_audio_{chosen} (auto-assign #{auto_counter})")

        # --- Step 5: 逐行合成 ---
        log_lines.append(f"[DialogueClone] Synthesizing {len(dialogue_lines)} lines...")
        audio_segments = []
        any_sr = None

        for i, dlg in enumerate(dialogue_lines):
            spk = dlg["speaker"]
            text = dlg["text"]
            ref_idx = speaker_assignments[spk]
            ref_audio = ref_pool[ref_idx]

            log_lines.append(f"  [{i+1}/{len(dialogue_lines)}] {spk}: \"{text[:40]}{'...' if len(text) > 40 else ''}\" → ref_audio_{ref_idx}")

            try:
                seg_audio, seg_status = _synthesize_one(
                    tts_model=tts_model,
                    text=text,
                    reference_audio=ref_audio,
                    lang=lang,
                    duration_factor=duration_factor,
                )
                seg_wave = seg_audio["waveform"]
                seg_sr = seg_audio["sample_rate"]
                if any_sr is None:
                    any_sr = seg_sr
                elif seg_sr != any_sr:
                    # 重采样到统一采样率（极少见情况）
                    import torchaudio
                    resampler = torchaudio.transforms.Resample(seg_sr, any_sr)
                    if seg_wave.dim() == 3:
                        seg_wave = resampler(seg_wave[0]).unsqueeze(0)
                    else:
                        seg_wave = resampler(seg_wave)

                audio_segments.append(seg_wave)
                log_lines.append(f"       ✓ {seg_status}")
            except Exception as e:
                log_lines.append(f"       ✗ FAILED: {e}")
                # 跳过失败的行（不中断整体合成）
                continue

        if not audio_segments:
            raise RuntimeError("All dialogue lines failed to synthesize. Check TTS model and reference audios.")

        # --- Step 6: 拼接 ---
        if pause_ms > 0 and any_sr:
            pause_samples = int(any_sr * pause_ms / 1000)
            silence = torch.zeros(1, 1, pause_samples)
            new_segs = []
            for i, seg in enumerate(audio_segments):
                if i > 0:
                    new_segs.append(silence)
                new_segs.append(seg)
            audio_segments = new_segs

        if len(audio_segments) == 1:
            final_audio = audio_segments[0]
            final_sr = any_sr or 24000
        else:
            final_audio = crossfade_concat(audio_segments, any_sr or 24000, fade_ms=crossfade_ms)
            final_sr = any_sr or 24000

        total_seconds = final_audio.shape[-1] / final_sr
        log_lines.append(f"[DialogueClone] ✅ Done: {len(audio_segments)} segments → {total_seconds:.2f}s total, {final_sr}Hz")

        return ({"waveform": final_audio.cpu(), "sample_rate": final_sr}, "\n".join(log_lines))


# ===========================================================================
#  内部合成工具函数（复用 IndexTTS Synthesis 节点的完整逻辑）
# ===========================================================================

def _synthesize_one(tts_model, text, reference_audio, lang="ZH", duration_factor=1.0):
    """单次 IndexTTS 合成：文本 + 参考音频 → AUDIO dict + status string。

    完整复用 BSAI_IndexTTS2.5Synthesis 节点的退化检测 + 降级重试保护。
    """
    import torchaudio
    import tempfile
    import os
    import traceback

    ref_waveform = reference_audio["waveform"]
    ref_sr = reference_audio["sample_rate"]

    if ref_waveform.dim() == 3:
        ref_waveform = ref_waveform[0]
    elif ref_waveform.dim() == 1:
        ref_waveform = ref_waveform.unsqueeze(0)

    temp_dir = tempfile.mkdtemp(prefix="bsai_dialogue_tts_")
    ref_audio_path = os.path.join(temp_dir, "reference.wav")
    out_audio_path = os.path.join(temp_dir, "output.wav")

    # 保存参考音频
    _save_audio_file(ref_audio_path, ref_waveform, ref_sr)

    # 数值参数归一化
    generation_kwargs = {
        "temperature": 0.8, "top_p": 0.8, "top_k": 30,
        "length_penalty": 0.0, "num_beams": 3, "repetition_penalty": 10.0,
        "max_mel_tokens": 1500, "do_sample": True,
    }

    # 退化检测（与 IndexTTS 节点一致）
    def _is_degenerate(waveform):
        if waveform is None or waveform.numel() == 0:
            return True, "empty"
        w = waveform.float()
        if not bool(torch.isfinite(w).all()):
            return True, "NaN/Inf"
        x = w.abs()
        sat_frac = float((x > 0.999).float().mean().item())
        rms = float(torch.sqrt((w ** 2).mean()).item())
        if sat_frac > 0.3:
            return True, f"clipped ({sat_frac:.1%})"
        if rms > 0.25:
            return True, f"too loud (rms={rms:.3f})"
        return False, "ok"

    attempt = 0
    max_attempts = 2
    while True:
        tts_model.infer(
            spk_audio_prompt=ref_audio_path,
            text=text,
            output_path=out_audio_path,
            lang=lang,
            emo_audio_prompt=None,
            emo_alpha=1.0,
            emo_vector=None,
            use_emo_text=False,
            emo_text=None,
            use_random=False,
            duration_factor=duration_factor,
            verbose=False,
            max_text_tokens_per_segment=100,
            **generation_kwargs,
        )

        if not os.path.exists(out_audio_path):
            raise RuntimeError("TTS completed but output file missing")

        try:
            audio_waveform, audio_sr = torchaudio.load(out_audio_path)
        except (ImportError, RuntimeError):
            import soundfile as sf
            data, audio_sr = sf.read(out_audio_path)
            audio_waveform = torch.from_numpy(data).float()
            if audio_waveform.dim() == 1:
                audio_waveform = audio_waveform.unsqueeze(0)
            else:
                audio_waveform = audio_waveform.T

        if audio_waveform.shape[0] > 1:
            audio_waveform = audio_waveform.mean(dim=0, keepdim=True)

        is_deg, reason = _is_degenerate(audio_waveform)
        if not is_deg:
            break

        attempt += 1
        if attempt >= max_attempts:
            raise RuntimeError(f"Degenerate audio ({reason}) after {max_attempts} attempts")

        # 降级：如果是 BF16 → 卸载 fp32 重载重试
        if getattr(tts_model, "dtype", None) is not None:
            try:
                _bsai_idx_path = os.path.join(
                    folder_paths.base_path, "custom_nodes", "BSAI_ComfyUI_IndexTTS-2.5")
                if _bsai_idx_path not in sys.path:
                    sys.path.insert(0, _bsai_idx_path)
                from BSAI_IndexTTS import _unload_indextts, _get_indextts
                _unload_indextts()
                tts_model = _get_indextts(use_bf16=False)
            except Exception:
                pass

    # 转 ComfyUI AUDIO 格式
    if audio_waveform.dim() == 1:
        audio_waveform = audio_waveform.unsqueeze(0).unsqueeze(0)
    elif audio_waveform.dim() == 2:
        audio_waveform = audio_waveform.unsqueeze(0)

    duration = audio_waveform.shape[-1] / audio_sr
    status = f"Duration: {duration:.2f}s | SR: {audio_sr}Hz | Lang: {lang}"

    return ({"waveform": audio_waveform.cpu(), "sample_rate": audio_sr}, status)


def _save_audio_file(path, waveform, sample_rate):
    """保存音频文件（torchaudio + soundfile 双重降级）。"""
    import torchaudio
    import soundfile as sf

    wav_t = waveform.cpu()
    if wav_t.dim() == 3:
        wav_t = wav_t[0]
    elif wav_t.dim() == 1:
        wav_t = wav_t.unsqueeze(0)

    try:
        torchaudio.save(path, wav_t, sample_rate)
        return
    except Exception:
        pass

    wav_np = wav_t.numpy()
    if wav_np.ndim == 2:
        wav_np = wav_np.T
    elif wav_np.ndim == 1:
        wav_np = wav_np.reshape(-1, 1)
    sf.write(path, wav_np, sample_rate)


# ===========================================================================
#  节点注册
# ===========================================================================

NODE_CLASS_MAPPINGS = {
    "BSAIVoiceClone": BSAIVoiceClone,
    "BSAIDialogueVoiceClone": BSAIDialogueVoiceClone,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "BSAIVoiceClone": "BSAI Voice Clone (Single Speaker)",
    "BSAIDialogueVoiceClone": "BSAI Dialogue Voice Clone (Multi-Speaker)",
}
