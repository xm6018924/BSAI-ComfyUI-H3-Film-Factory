# -*- coding: utf-8 -*-
"""MiniMax H3 full-reference prompt extraction and reference-to-video nodes."""
import re

import numpy as np
import torch
from PIL import Image

import comfy.utils

try:
    import cv2
except ImportError:
    cv2 = None

from comfy_extras.nodes_minimax_h3 import MiniMaxH3ReferenceToVideo, align_frame_count

from .official_prompt import (
    DEFAULT_SEGMENT_MARKER,
    OfficialPromptError,
    parse_official_prompt,
    parse_official_prompt_segments,
    resolve_prompt_segment_duration,
)

FPS = 24
MAX_REF_IMAGES = 9
MAX_REF_VIDEOS = 3
MAX_REF_AUDIOS = 3
MAX_VIDEO_FRAMES = 360
DEFAULT_FALLBACK_FRAMES = 124
MAX_CLIPS = 512
SEGMENT_MARKER_INPUT = (
    "STRING",
    {
        "forceInput": True,
        "default": DEFAULT_SEGMENT_MARKER,
        "tooltip": "可连接字符串节点自定义标记；默认 ===== prompt_N =====，也兼容 promptN。prompt_N、clip_N 或 {N} 中的 N 表示序号；不含序号占位符时按出现顺序编号。",
    },
)

_LABELS = {
    "Picture": re.compile(r"<Picture\s+(\d+)>"),
    "Video": re.compile(r"<Video\s+(\d+)>"),
    "Audio": re.compile(r"<Audio\s+(\d+)>"),
}
_AUDIO_VIDEO_SOURCE_RE = re.compile(
    r"<Audio\s+(\d+)>[^\n]*?(?:synchronized\s+)?(?:audio|soundtrack)\s+track\s+of\s+<Video\s+(\d+)>",
    re.IGNORECASE,
)


def _load_image_tensor(path):
    image = Image.open(path).convert("RGB")
    array = np.array(image, dtype=np.float32) / 255.0
    return torch.from_numpy(array).unsqueeze(0)


def _load_video_frames(path):
    if cv2 is None:
        raise RuntimeError("opencv-python 未安装，无法加载素材库中的参考视频。")
    capture = cv2.VideoCapture(path)
    if not capture.isOpened():
        raise RuntimeError(f"无法打开参考视频：{path}")
    frames = []
    while len(frames) < MAX_VIDEO_FRAMES:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    capture.release()
    if not frames:
        raise RuntimeError(f"参考视频没有可读取的帧：{path}")
    return torch.from_numpy(np.stack(frames, dtype=np.float32) / 255.0)


def _load_audio(path):
    return comfy.utils.load_audio(path)


def _asset_path(entry):
    if isinstance(entry, dict):
        return entry.get("path", entry.get("filename", ""))
    return str(entry)


def _find_asset(items, index):
    for item in items:
        if isinstance(item, dict) and item.get("index") == index:
            return item
    if 0 < index <= len(items):
        return items[index - 1]
    return None


def _picture_library_for_source_ids(asset_library, source_image_refs):
    if not source_image_refs:
        return asset_library
    library = asset_library if isinstance(asset_library, dict) else {}
    images = library.get("images", [])
    mapped_images = []
    for source_index, picture_index in sorted(source_image_refs.items(), key=lambda item: item[1]):
        entry = _find_asset(images, int(source_index))
        if entry is None:
            raise ValueError(f"@图{source_index} 在 BSAI Asset Library 中没有对应图片。")
        if isinstance(entry, dict):
            mapped = dict(entry)
            path = _asset_path(entry)
        else:
            path = _asset_path(entry)
            mapped = {"path": path}
        if not path:
            raise ValueError(f"@图{source_index} 对应素材没有有效文件路径。")
        mapped["index"] = int(picture_index)
        mapped_images.append(mapped)
    return {
        **library,
        "images": mapped_images,
        "videos": library.get("videos", []),
        "audios": library.get("audios", []),
    }


def _numbers(text, kind):
    return sorted({int(value) for value in _LABELS[kind].findall(text or "")})


def _video_source(index, library_videos, external_videos, external_audio):
    if index <= len(library_videos):
        entry = _find_asset(library_videos, index)
        if entry is None:
            raise ValueError(f"<Video {index}> 在 BSAI Asset Library 中没有对应视频。")
        path = _asset_path(entry)
        return _load_video_frames(path), path, external_audio[index - 1]

    external_index = index - len(library_videos) - 1
    if external_index < 0 or external_index >= MAX_REF_VIDEOS:
        raise ValueError(f"<Video {index}> 超出当前参考视频输入范围。")
    frames = external_videos[external_index]
    if frames is None:
        raise ValueError(
            f"<Video {index}> 没有素材库文件或已连接的 ref_video_{external_index}。"
        )
    soundtrack = external_audio[external_index]
    return frames, None, soundtrack


def _audio_video_sources(subject_definitions, video_number_max):
    source_map = {}
    video_map = {}
    for audio_number, video_number in _AUDIO_VIDEO_SOURCE_RE.findall(subject_definitions):
        audio_number = int(audio_number)
        video_number = int(video_number)
        if video_number > video_number_max:
            raise ValueError(
                f"<Audio {audio_number}> 指向 <Video {video_number}>，"
                "但该视频没有在提示词中定义。"
            )
        previous = source_map.get(audio_number)
        if previous is not None and previous != video_number:
            raise ValueError(f"<Audio {audio_number}> 被绑定到多个参考视频。")
        previous_audio = video_map.get(video_number)
        if previous_audio is not None and previous_audio != audio_number:
            raise ValueError(f"<Video {video_number}> 被绑定到多个 <Audio N> 音轨。")
        source_map[audio_number] = video_number
        video_map[video_number] = audio_number
    return source_map


def build_official_clip_refs(prompt, asset_library, ext_videos, ext_video_audios, ext_audios):
    """Load reference assets by official label number without rewriting the prompt."""
    sections = parse_official_prompt(prompt)["sections"]
    library = asset_library if isinstance(asset_library, dict) else {}
    images_library = library.get("images", [])
    videos_library = library.get("videos", [])
    audios_library = library.get("audios", [])
    image_numbers = _numbers(prompt, "Picture")
    video_numbers = _numbers(prompt, "Video")
    audio_numbers = _numbers(prompt, "Audio")

    if image_numbers and image_numbers[-1] > MAX_REF_IMAGES:
        raise ValueError(f"MiniMax H3 支持最多 {MAX_REF_IMAGES} 个图片引用。")
    if video_numbers and video_numbers[-1] > MAX_REF_VIDEOS:
        raise ValueError(f"MiniMax H3 支持最多 {MAX_REF_VIDEOS} 个视频引用。")
    if audio_numbers and audio_numbers[-1] > MAX_REF_AUDIOS:
        raise ValueError(f"MiniMax H3 当前节点支持最多 {MAX_REF_AUDIOS} 个音频引用。")

    ref_images = {}
    for number in range(1, (image_numbers[-1] if image_numbers else 0) + 1):
        entry = _find_asset(images_library, number)
        if entry is None:
            raise ValueError(f"<Picture {number}> 在 BSAI Asset Library 中没有对应图片。")
        ref_images[f"ref_image_{number - 1}"] = _load_image_tensor(_asset_path(entry))

    videos = {}
    video_sources = {}
    for number in range(1, (video_numbers[-1] if video_numbers else 0) + 1):
        frames, path, soundtrack = _video_source(
            number, videos_library, ext_videos, ext_video_audios
        )
        videos[f"ref_video_{number - 1}"] = frames
        video_sources[number] = (path, soundtrack)

    audio_sources = _audio_video_sources(
        sections["subject_definitions"], video_numbers[-1] if video_numbers else 0
    )
    ref_audios = {}
    ref_video_audios = {}
    standalone_index = 0
    paired_audio_numbers = sorted(audio_sources)
    can_pair_soundtracks = paired_audio_numbers == list(
        range(1, len(paired_audio_numbers) + 1)
    )
    if can_pair_soundtracks:
        video_audio_order = sorted(audio_sources.items(), key=lambda item: item[1])
        can_pair_soundtracks = [number for number, _ in video_audio_order] == paired_audio_numbers
    for number in range(1, (audio_numbers[-1] if audio_numbers else 0) + 1):
        if number in audio_sources:
            video_number = audio_sources[number]
            path, external_audio = video_sources[video_number]
            if external_audio is not None:
                audio = external_audio
            elif path:
                audio = _load_audio(path)
            else:
                raise ValueError(
                    f"<Audio {number}> 定义为 <Video {video_number}> 的同步音轨，"
                    f"请连接 ref_video_audio_{video_number - len(videos_library) - 1}。"
                )
            if can_pair_soundtracks:
                ref_video_audios[f"ref_video_audio_{video_number - 1}"] = audio
            else:
                ref_audios[f"ref_audio_{number - 1}"] = audio
        else:
            entry = _find_asset(audios_library, standalone_index + 1)
            if entry is not None:
                audio = _load_audio(_asset_path(entry))
            else:
                external_index = standalone_index - len(audios_library)
                if 0 <= external_index < len(ext_audios) and ext_audios[external_index] is not None:
                    audio = ext_audios[external_index]
                else:
                    raise ValueError(
                        f"<Audio {number}> 没有对应音频。请检查 BSAI Asset Library "
                        "和 ref_audio 输入。"
                    )
            standalone_index += 1
            ref_audios[f"ref_audio_{number - 1}"] = audio

    return ref_images, videos, ref_video_audios, ref_audios


def seconds_to_frames(seconds):
    count = max(5, int(round(float(seconds) * FPS)))
    return align_frame_count(count)


def _select_prompt(prompt_source, clip_index, video_duration_sec, fallback_frames, segment_marker=DEFAULT_SEGMENT_MARKER):
    segments = parse_official_prompt_segments(prompt_source, segment_marker)
    index = int(clip_index)
    if index < 1 or index > len(segments):
        raise OfficialPromptError(
            f"clip_index={index} 超出范围；提示词共 {len(segments)} 个 prompt 段，请填写 1~{len(segments)}。"
        )
    segment = segments[index - 1]
    duration_sec, duration_source = resolve_prompt_segment_duration(
        segment, len(segments), fallback_frames, video_duration_sec
    )
    return (
        segment["parsed"],
        index,
        segment.get("converted_prompt", segment["prompt"]),
        duration_sec,
        len(segments),
        segment["marker"],
        duration_source,
        segment.get("source_image_refs", {}),
    )


class A_MiniMaxH3OfficialRefPromptSegment:
    """Extract one complete outer prompt block as an official full-reference prompt."""

    CATEGORY = "A-BSAI/H3"
    FUNCTION = "extract"
    OUTPUT_NODE = False
    RETURN_TYPES = ("STRING", "FLOAT", "FLOAT", "INT", "INT", "STRING")
    RETURN_NAMES = (
        "selected_prompt",
        "source_start_sec",
        "clip_duration_sec",
        "segment_frames",
        "segment_count",
        "status",
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "full_reference_prompt": (
                    "STRING",
                    {"forceInput": True, "multiline": True, "tooltip": "按 prompt_N 外层标记切分；也兼容 promptN。"},
                ),
                "clip_index": (
                    "INT",
                    {"default": 1, "min": 1, "max": MAX_CLIPS, "step": 1, "tooltip": "按分段标记出现顺序选择完整提示词段；标记编号重复时仍按出现顺序计数。"},
                ),
                "video_duration_sec": (
                    "FLOAT",
                    {"default": 0.0, "min": 0.0, "max": 86400.0, "step": 0.1, "tooltip": "仅在只有一个 prompt 段且提示词中没有显式时长时作为兜底；多段提示词的时长从各自文本中提取。"},
                ),
                "fallback_length_frames": (
                    "INT",
                    {"default": DEFAULT_FALLBACK_FRAMES, "min": 5, "max": 3600, "step": 17, "tooltip": "该 prompt 段没有显式时长时使用的兜底帧数。"},
                ),
            },
            "optional": {"segment_marker": SEGMENT_MARKER_INPUT},
        }

    def extract(self, full_reference_prompt, clip_index, video_duration_sec, fallback_length_frames, segment_marker=DEFAULT_SEGMENT_MARKER):
        segments = parse_official_prompt_segments(full_reference_prompt, segment_marker)
        index = int(clip_index)
        if index < 1 or index > len(segments):
            raise OfficialPromptError(
                f"clip_index={index} 超出范围；提示词共 {len(segments)} 个 prompt 段，请填写 1~{len(segments)}。"
            )
        segment = segments[index - 1]
        selected_prompt = segment["prompt"]
        duration_sec, duration_source = resolve_prompt_segment_duration(
            segment, len(segments), fallback_length_frames, video_duration_sec
        )
        frames = seconds_to_frames(duration_sec)
        total = len(segments)
        status = (
            f"已提取 {segment['marker'] or '单段完整提示词'}（{index}/{total}），完整六章节提示词原样输出；"
            f"时长 {duration_sec:.3f}s（{duration_source}），适配帧数 {frames}。"
        )
        return (selected_prompt, 0.0, float(duration_sec), int(frames), int(total), status)

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")


class A_MiniMaxH3StoryboardRefVideo:
    """MiniMax H3 full-reference prompt-block selector and Ref2VA packer."""

    CATEGORY = "A-BSAI/H3"
    FUNCTION = "generate"
    OUTPUT_NODE = False
    RETURN_TYPES = ("CONDITIONING", "LATENT", "FLOAT", "STRING", "STRING")
    RETURN_NAMES = (
        "clip1_positive",
        "clip1_latent",
        "clip_duration_sec",
        "selected_prompt",
        "status",
    )

    @classmethod
    def INPUT_TYPES(cls):
        optional = {}
        for index in range(MAX_REF_VIDEOS):
            optional[f"ref_video_{index}"] = (
                "IMAGE",
                {"tooltip": f"官方 <Video {index + 1}> 对应的视频帧；排在素材库视频之后。"},
            )
        for index in range(MAX_REF_VIDEOS):
            optional[f"ref_video_audio_{index}"] = (
                "AUDIO",
                {"tooltip": f"对应 ref_video_{index} 的音轨；只有 subject_definitions 显式将 <Audio N> 绑定到此视频时才使用。"},
            )
        for index in range(MAX_REF_AUDIOS):
            optional[f"ref_audio_{index}"] = (
                "AUDIO",
                {"tooltip": f"独立官方 <Audio N> 引用；素材库音频之后按顺序排列。"},
            )
        optional["segment_marker"] = SEGMENT_MARKER_INPUT
        return {
            "required": {
                "clip": ("CLIP", {"tooltip": "MiniMax H3 文本编码器（Qwen3VL MiniMax）。"}),
                "vae": ("VAE", {"tooltip": "MiniMax H3 视频 VAE。"}),
                "audio_vae": ("VAE", {"tooltip": "MiniMax H3 音频 VAE。"}),
                "prompt_source": (
                    "STRING",
                    {"forceInput": True, "multiline": True, "tooltip": "按 prompt_N 外层标记选择完整六章节提示词；支持 BSAI @图N 资产源编号并转换为本段连续 H3 引用标签。"},
                ),
                "asset_library": (
                    "ASSET_LIBRARY",
                    {"forceInput": True, "tooltip": "接入 BSAI Asset Library。@图N 按源编号查图，再按本段首次出现顺序映射为连续 <Picture N>；内部 H3 编号独立于源 @图N。"},
                ),
                "width": ("INT", {"default": 480, "min": 32, "max": 4096, "step": 32}),
                "height": ("INT", {"default": 832, "min": 32, "max": 4096, "step": 32}),
                "length": (
                    "INT",
                    {"default": DEFAULT_FALLBACK_FRAMES, "min": 5, "max": 3600, "step": 17, "tooltip": "所选 prompt 段未写明时长时使用的兜底帧数。"},
                ),
                "ref_image_size": (
                    ["match", "max"],
                    {"default": "max", "tooltip": "参考图缩放模式。"},
                ),
                "clip_index": (
                    "INT",
                    {"default": 1, "min": 1, "max": MAX_CLIPS, "step": 1, "tooltip": "按分段标记出现顺序选择完整 CLIP；每段保留完整提示词。"},
                ),
                "video_duration_sec": (
                    "FLOAT",
                    {"default": 0.0, "min": 0.0, "max": 86400.0, "step": 0.1, "tooltip": "优先读取各段 detailed_description 的 [Recommended duration]；该值仅供单段未写时长时兜底。"},
                ),
            },
            "optional": optional,
        }

    def generate(
        self,
        clip,
        vae,
        audio_vae,
        prompt_source,
        asset_library,
        width,
        height,
        length,
        ref_image_size,
        clip_index,
        video_duration_sec,
        **kwargs,
    ):
        external_videos = [kwargs.get(f"ref_video_{index}") for index in range(MAX_REF_VIDEOS)]
        external_video_audios = [
            kwargs.get(f"ref_video_audio_{index}") for index in range(MAX_REF_VIDEOS)
        ]
        external_audios = [kwargs.get(f"ref_audio_{index}") for index in range(MAX_REF_AUDIOS)]

        segment_marker = kwargs.get("segment_marker") or DEFAULT_SEGMENT_MARKER
        parsed, selected_index, selected_prompt, duration_sec, segment_count, segment_marker_text, duration_source, source_image_refs = _select_prompt(
            prompt_source, clip_index, video_duration_sec, length, segment_marker
        )
        prompt_asset_library = _picture_library_for_source_ids(asset_library, source_image_refs)
        ref_images, ref_videos, ref_video_audios, ref_audios = build_official_clip_refs(
            selected_prompt,
            prompt_asset_library,
            external_videos,
            external_video_audios,
            external_audios,
        )
        frame_count = seconds_to_frames(duration_sec)
        output = MiniMaxH3ReferenceToVideo.execute(
            clip=clip,
            prompt=selected_prompt,
            width=int(width),
            height=int(height),
            length=int(frame_count),
            ref_image_size=ref_image_size,
            vae=vae,
            audio_vae=audio_vae,
            ref_images=ref_images,
            ref_videos=ref_videos,
            ref_video_audios=ref_video_audios,
            ref_audios=ref_audios,
        )
        status = (
            f"已打包 {segment_marker_text or '单段完整提示词'}（{selected_index}/{segment_count}）；"
            f"该段视频时长 {duration_sec:.3f}s（{duration_source}）；"
            f"{len(ref_images)} 张图、{len(ref_videos)} 个视频、"
            f"{len(ref_audios) + len(ref_video_audios)} 个音频引用（含 {len(ref_video_audios)} 个视频配对音轨）。"
        )
        return (output[0], output[1], float(duration_sec), selected_prompt, status)

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")


class A_MiniMaxH3StoryboardViewer:
    """Preview official full-reference shots and their referenced assets."""

    CATEGORY = "A-BSAI/H3"
    FUNCTION = "view"
    OUTPUT_NODE = True
    RETURN_TYPES = ()

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt_source": (
                    "STRING",
                    {"forceInput": True, "multiline": True, "tooltip": "按 prompt_N 标记切分；支持 BSAI @图N 源索引与六章节官方提示词。"},
                ),
                "expand": ("BOOLEAN", {"default": False, "tooltip": "预览默认折叠；看板内支持逐段或全部展开。"}),
            },
            "optional": {
                "asset_library": (
                    "ASSET_LIBRARY",
                    {"forceInput": False, "tooltip": "按源 @图N 或官方 <Picture N>/<Video N> 索引显示素材缩略图。"},
                ),
                "segment_marker": SEGMENT_MARKER_INPUT,
            },
        }

    def view(self, prompt_source, expand=False, asset_library=None, segment_marker=DEFAULT_SEGMENT_MARKER):
        return {}

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")


NODE_CLASS_MAPPINGS = {
    "A_MiniMaxH3OfficialRefPromptSegment": A_MiniMaxH3OfficialRefPromptSegment,
    "A_MiniMaxH3StoryboardRefVideo": A_MiniMaxH3StoryboardRefVideo,
    "A_MiniMaxH3StoryboardViewer": A_MiniMaxH3StoryboardViewer,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "A_MiniMaxH3OfficialRefPromptSegment": "[A] MiniMax H3 官方参考提示词逐段提取",
    "A_MiniMaxH3StoryboardRefVideo": "[A] MiniMax H3 官方参考生视频 (Full Ref2VA)",
    "A_MiniMaxH3StoryboardViewer": "[A] MiniMax H3 官方参考提示词预览看板",
}
