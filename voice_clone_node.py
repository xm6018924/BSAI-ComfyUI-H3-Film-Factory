"""BSAI 声音克隆节点 - 封装 IndexTTS-2.5 一键声音克隆。

输入:
  - reference_audio: 参考人声（3-10秒清晰干声）
  - text: 要合成的文本
  - speaker_wav: 可选，额外参考音色

输出:
  - AUDIO: 克隆后的语音
"""

import torch
import numpy as np
import folder_paths
import os


class BSAIVoiceClone:
    """一键声音克隆：参考音频 + 文本 → 克隆语音。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "default": "Hello, this is a voice clone test.",
                                    "tooltip": "Text content to synthesize"}),
                "reference_audio": ("AUDIO", {"tooltip": "Reference voice sample (3-10s clean dry voice, no background music)"}),
                "speed": ("FLOAT", {"default": 1.0, "min": 0.5, "max": 2.0, "step": 0.1,
                                    "tooltip": "Speech rate, 1.0 is normal"}),
            },
            "optional": {
                "language": (["auto", "zh", "en", "ja", "ko"], {"default": "auto",
                                "tooltip": "Language, auto-detect"}),
                "effect_mode": (["nothing", "vocoder", "constant"], {"default": "nothing",
                                "tooltip": "Effect mode"}),
            }
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "clone"
    CATEGORY = "BSAI/Voice"
    DESCRIPTION = "One-click voice cloning: upload a reference voice, enter text, and generate speech in the same timbre. The output can be connected directly to the Film Factory lip_audio port for lip-sync."

    def clone(self, text, reference_audio, speed=1.0, language="auto", effect_mode="nothing"):
        # 延迟导入 IndexTTS
        try:
            from indextts.interface import IndexTTSInterface
        except ImportError:
            # 尝试从 BSAI IndexTTS 节点导入
            try:
                import sys
                idx_path = os.path.join(folder_paths.base_path, "custom_nodes", "BSAI_ComfyUI_IndexTTS-2.5")
                if idx_path not in sys.path:
                    sys.path.insert(0, idx_path)
                from BSAI_IndexTTS import IndexTTSNode
                # 复用现有节点
                node = IndexTTSNode()
                return node.generate(
                    text=text,
                    reference_audio=reference_audio,
                    speed=speed,
                    language=language,
                    effect_mode=effect_mode,
                )
            except Exception as e:
                raise RuntimeError(
                    f"声音克隆需要 IndexTTS-2.5 节点包。请确保 BSAI_ComfyUI_IndexTTS-2.5 已安装。\n"
                    f"错误: {e}"
                )

        # 如果直接导入成功
        wav = reference_audio["waveform"]
        sr = reference_audio["sample_rate"]

        # 保存参考音频到临时文件
        import tempfile
        import soundfile as sf
        tmpdir = tempfile.mkdtemp()
        ref_path = os.path.join(tmpdir, "reference.wav")
        sf.write(ref_path, wav[0].T.cpu().numpy(), sr)

        tts = IndexTTSInterface()
        output_wav = tts.synthesize(
            text=text,
            reference_wav=ref_path,
            language=language,
            speed=speed,
        )

        # 转成 AUDIO dict
        audio_tensor = torch.from_numpy(output_wav).float()
        if audio_tensor.ndim == 1:
            audio_tensor = audio_tensor.unsqueeze(0).unsqueeze(0)
        elif audio_tensor.ndim == 2:
            audio_tensor = audio_tensor.unsqueeze(0)

        return ({"waveform": audio_tensor, "sample_rate": sr},)


# 注册
NODE_CLASS_MAPPINGS = {"BSAIVoiceClone": BSAIVoiceClone}
NODE_DISPLAY_NAME_MAPPINGS = {"BSAIVoiceClone": "BSAI Voice Clone"}
