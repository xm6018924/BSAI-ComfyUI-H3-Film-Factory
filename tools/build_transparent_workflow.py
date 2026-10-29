# -*- coding: utf-8 -*-
"""BSAI H3 Film Factory 透明视频渲染管道 · 极简示例工作流生成器 (v14.233).

B站《在 ComfyUI 中使用 MiniMax-H3 轻松制作透明视频》(BV1arJX69E7L) 配方:
H3 在纯色背景(绿幕/蓝幕/纯黑)上生成 -> BSAI_H3_TransparentKey 抠像 ->
BSAI_H3_SaveTransparentVideo 导出(ProRes 4444 真 Alpha / WebM VP9 / RGBA PNG 序列)。

链: UNETLoader -> LoraLoaderModelOnly(4步turbo LoRA 0.8) -> BSAIH3FilmFactory
     (render_pipeline=「透明视频 单采抠像 (H3 Transparent)」)
     -> BSAI_H3_TransparentKey -> BSAI_H3_SaveTransparentVideo (+ audios 合流)
"""
import json
import io
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(
    OUT_DIR, "..", "example_workflows",
    "BSAI_H3_Film_Factory电影工厂-透明视频-单采抠像直出.json")

# ---- 主节点 68 键模板（v14.233，H3LegacyCompat 布局）----
# 极简版仅接线 model/clip/vae/audio_vae；宽度/高度走 widget 手填值。
CLIP_PROMPT = (
    "【透明视频纪律】提示词必须以纯色背景收尾：flat solid green screen background, "
    "no floor, no horizon, no shadows, no props。\n"
    "：开场-主体亮相（绿幕单采·透明素材） 0-5秒：镜头中近景，一位年轻女性动漫角色"
    "位于画面正中央正对镜头，面带微笑挥手，动作缓慢自然。背景为纯色绿幕，平坦均匀"
    "无纹理。清透 2D 动漫风格，边缘干净利落便于抠像。音效：轻柔卡通环境音，轻微风声。"
)
GLOBAL_PROMPT = (
    "[画面硬约束·全片必须遵守]：画面只能出现纯色背景（绿幕/蓝幕/纯黑）与主体角色，"
    "不得出现地板、地平线、阴影、杂物、道具、桌面；背景必须平坦、均匀、无纹理、"
    "无光照渐变，便于后期一键抠像生成透明视频。\n\n"
    "[角色纪律]：主体角色全片保持一致外形与服装，同一角色只出现一次、只保留两条手臂。\n\n"
    "[整体风格]：clean 2D anime style, clean line art, bright rim light, high quality。\n\n"
    "[音频]：轻柔卡通风格环境音，轻微空气流动声，不生成台词。"
)
CLIPS = {
    "version": 1,
    "clips": [{
        "id": "clip_1_h3transparent",
        "name": "",
        "prompt": CLIP_PROMPT,
        "seed": 889464827739203,
        "seed_mode": "randomize",
        "duration": 5,
        "validated": False,
        "context_enabled": True,
        "color_adjustment": {"saturation": 100, "contrast": 100, "brightness": 100},
        "card_height": 0,
        "collapsed": False,
        "subtitle": "",
        "subtitle_enabled": False,
        "subtitle_mode": "manual",
        "subtitle_auto_dialogue": True,
        "subtitle_auto_narration": False,
        "subtitle_auto_lyrics": False,
        "subtitle_font": "msyh.ttc",
        "subtitle_font_size": 24,
        "subtitle_color": "#FFFFFF",
        "subtitle_box": False,
        "subtitle_box_color": "#000000",
        "subtitle_box_width": 2,
        "rfe_frame_count": 15,
        "rfe_selection_mode": "last_n",
        "rfe_start_frame": 0,
        "rfe_end_frame": 0,
        "rfe_max_output_frames": 9,
        "rfe_sampling_method": "even",
        "rfe_save_frames": False,
        "rfe_output_subdir": "contextual_series",
        "rfe_filename_prefix": "frame",
        "render_enabled": True,
        "replace_mode": False,
    }],
    "global_prompt": GLOBAL_PROMPT,
}

MAIN = {
    "id": 6, "type": "BSAIH3FilmFactory",
    "pos": [700.0, 120.0], "size": [1842.25, 2574.0],
    "flags": {}, "order": 6, "mode": 0,
    "title": "BSAI ComfyUI H3 Film Factory v2.131·v14.233 透明视频·单采抠像 (极简版)",
    "properties": {
        "aux_id": "xm6018924/BSAI-ComfyUI-H3-Film-Factory",
        "ver": "98641a946b1b0a010da9d8977a38e3b44258b356",
        "Node name for S&R": "BSAIH3FilmFactory",
        "enableTabs": False,
        "tabWidth": 65,
        "tabXOffset": 10,
        "hasSecondTab": False,
        "secondTabText": "Send Back",
        "secondTabOffset": 80,
        "secondTabWidth": 65,
        "h3_manual_width": 1920,
        "h3_manual_height": 1088,
        "ue_properties": {
            "widget_ue_connectable": {"width": True, "height": True},
            "version": "7.8",
            "input_ue_unconnectable": {},
        },
        "h3_project_name": "H3透明视频-",
    },
    "inputs": [
        {"name": "model", "type": "MODEL", "link": 2},
        {"name": "clip", "type": "CLIP", "link": 3},
        {"name": "vae", "type": "VAE", "link": 4},
        {"name": "audio_vae", "type": "VAE", "link": 5, "shape": 7},
        {"name": "ref_audio", "type": "AUDIO", "link": None, "shape": 7},
        {"name": "lip_audio", "type": "AUDIO", "link": None, "shape": 7},
        {"name": "lip_voice", "type": "AUDIO", "link": None, "shape": 7},
        {"name": "prompt_source", "type": "STRING", "link": None, "shape": 7},
        {"name": "prompt_pack", "type": "H3_PROMPT_PACK", "link": None, "shape": 7},
        {"name": "asset_library", "type": "ASSET_LIBRARY", "link": None, "shape": 7},
        {"name": "clip_prompt_1", "type": "STRING", "link": None, "shape": 7},
        {"name": "clip_prompt_2", "type": "STRING", "link": None, "shape": 7},
        {"name": "clip_prompt_3", "type": "STRING", "link": None, "shape": 7},
        {"name": "clip_prompt_4", "type": "STRING", "link": None, "shape": 7},
        {"name": "clip_prompt_5", "type": "STRING", "link": None, "shape": 7},
        {"name": "clip_prompt_6", "type": "STRING", "link": None, "shape": 7},
        {"name": "clip_prompt_7", "type": "STRING", "link": None, "shape": 7},
        {"name": "clip_prompt_8", "type": "STRING", "link": None, "shape": 7},
        {"name": "clip_prompt_9", "type": "STRING", "link": None, "shape": 7},
        {"name": "clip_prompt_10", "type": "STRING", "link": None, "shape": 7},
        {"name": "clip_prompt_11", "type": "STRING", "link": None, "shape": 7},
        {"name": "clip_prompt_12", "type": "STRING", "link": None, "shape": 7},
        {"name": "tts_model_TTS模型", "type": "INDEX_TTS_MODEL", "link": None, "shape": 7},
        {"name": "width", "type": "INT", "link": None},
        {"name": "height", "type": "INT", "link": None},
    ],
    "outputs": [
        {"name": "cache", "type": "H3_MOTION_DISK_CACHE", "links": [], "slot_index": 0},
        {"name": "clip_count", "type": "INT", "links": [], "slot_index": 1},
        {"name": "validated_count", "type": "INT", "links": [], "slot_index": 2},
        {"name": "status", "type": "STRING", "links": [], "slot_index": 3},
        {"name": "cache_size_mb", "type": "FLOAT", "links": [], "slot_index": 4},
        {"name": "build", "type": "STRING", "links": [], "slot_index": 5},
        {"name": "clip_videos", "type": "STRING", "links": [], "slot_index": 6},
        {"name": "images", "type": "IMAGE", "links": [6], "slot_index": 7},
        {"name": "audios", "type": "AUDIO", "links": [8], "slot_index": 8},
    ],
    "widgets_values": [
        "clip_by_clip",   # 0 播放模式
        1920,             # 1 宽度（手填）
        1088,             # 2 高度（手填）
        "max",            # 3 参考图尺寸
        8,                # 4 参考图数量
        "euler",          # 5 采样器（透明档强制 euler）
        "simple",         # 6 调度器
        1,                # 7 
        5,                # 8
        0,                # 9
        json.dumps(CLIPS, ensure_ascii=False),  # 10 clips_json
        "manual",         # 11 分镜控制
        1,                # 12
        '{"version":2,"refs":[null,null,null,null,null,null,null,null,null]}',  # 13 素材引用
        "both",           # 14
        "H3_Extender",    # 15 速度档（渲染管道接管）
        False,            # 16 二采 refine_enable（透明档关闭）
        False,            # 17
        0.12,             # 18
        "cpu",            # 19
        True,             # 20
        False,            # 21
        False,            # 22
        "all",            # 23
        False,            # 24
        120,              # 25
        True,             # 26
        0.45,             # 27
        4,                # 28
        2,                # 29
        "minimax_h3_latent_upscaler_3d_fp32.pth",  # 30
        40,               # 31
        0,                # 32
        "Audio redraw 0.7",  # 33
        True,             # 34
        True,             # 35
        "Quality first",  # 36
        "dlss5",          # 37
        2,                # 38
        "4x-UltraSharpV2.safetensors",  # 39
        0,                # 40
        4,                # 41
        True,             # 42
        False,            # 43
        False,            # 44
        4,                # 45
        128,              # 46
        "custom",         # 47
        True,             # 48
        12,               # 49 shift_video
        3,                # 50 shift_audio
        True,             # 51
        0.2,              # 52
        0,                # 53
        8,                # 54
        False,            # 55
        "MiniMaxH3_SemanticBridge_v1.safetensors",  # 56
        0.15,             # 57
        True,             # 58
        "global_inherit", # 59
        0.15,             # 60
        "off",            # 61 面部锁定
        "global (full-context, low VRAM)",  # 62
        "off (storyboard)",  # 63 单采模式
        0,                # 64
        "Transparent Video Single-Pass Keying (H3 Transparent)",  # 65 render_pipeline (第20档)
        "Single-pass seamless (recommended)",  # 66
        "",               # 67
    ],
}

# ---- 抠像台 + 导出节点（与 PRISM 改造版同构）----
KEY = {
    "id": 7, "type": "BSAI_H3_TransparentKey",
    "pos": [2680.0, 260.0], "size": [340, 420], "flags": {},
    "order": 7, "mode": 0,
    "inputs": [{"name": "images", "type": "IMAGE", "link": 6}],
    "outputs": [
        {"name": "images_rgba", "type": "IMAGE", "links": [7], "slot_index": 0},
        {"name": "matte", "type": "IMAGE", "links": [], "slot_index": 1},
        {"name": "images_preview", "type": "IMAGE", "links": [], "slot_index": 2},
    ],
    "title": "BSAI H3 透明视频抠像台 / Transparent Keying Studio",
    "properties": {"Node name for S&R": "BSAI_H3_TransparentKey"},
    "widgets_values": ["绿幕 Green", "平衡（毛发/烟雾）Balanced", 0.5, 0.0, 0.0, 2, 1, 0.0, 0.5, False],
}
SAVE = {
    "id": 8, "type": "BSAI_H3_SaveTransparentVideo",
    "pos": [3060.0, 260.0], "size": [340, 300], "flags": {},
    "order": 8, "mode": 0,
    "inputs": [
        {"name": "images_rgba", "type": "IMAGE", "link": 7},
        {"name": "audio", "shape": 7, "type": "AUDIO", "link": 8},
    ],
    "outputs": [
        {"name": "folder", "type": "STRING", "links": [], "slot_index": 0},
        {"name": "alpha_file", "type": "STRING", "links": [], "slot_index": 1},
        {"name": "preview_file", "type": "STRING", "links": [], "slot_index": 2},
        {"name": "preview_images", "type": "IMAGE", "links": [], "slot_index": 3},
    ],
    "title": "BSAI H3 透明视频导出 / Transparent Video Writer",
    "properties": {"Node name for S&R": "BSAI_H3_SaveTransparentVideo"},
    "widgets_values": ["ProRes 4444 (.mov, 真Alpha)", 24, "h3_transparent"],
}

# ---- 加载链路（教程配方：底模 + 4步 turbo LoRA）----
LOADERS = [
    {"id": 1, "type": "UNETLoader",
     "pos": [120.0, 120.0], "size": [320, 102], "flags": {}, "order": 1, "mode": 0,
     "inputs": [], "outputs": [{"name": "MODEL", "type": "MODEL", "links": [1], "slot_index": 0}],
     "title": "Load H3 Base Model (FL2VA int8)",
     "properties": {"Node name for S&R": "UNETLoader"},
     "widgets_values": ["minimax_h3_fl2va_zs05_int8_convrot.safetensors", "default", True, "default"]},
    {"id": 2, "type": "CLIPLoader",
     "pos": [120.0, 280.0], "size": [320, 102], "flags": {}, "order": 2, "mode": 0,
     "inputs": [], "outputs": [{"name": "CLIP", "type": "CLIP", "links": [3], "slot_index": 0}],
     "title": "Load H3 Text Encoder (qwen3vl 32B)",
     "properties": {"Node name for S&R": "CLIPLoader"},
     "widgets_values": ["qwen3vl_32b_minimax_h3_int8_convrot.safetensors", "minimax", "default"]},
    {"id": 3, "type": "VAELoader",
     "pos": [120.0, 440.0], "size": [320, 102], "flags": {}, "order": 3, "mode": 0,
     "inputs": [], "outputs": [{"name": "VAE", "type": "VAE", "links": [4], "slot_index": 0}],
     "title": "Load Video VAE",
     "properties": {"Node name for S&R": "VAELoader"},
     "widgets_values": ["minimax_h3_video_vae_int8_convrot.safetensors"]},
    {"id": 4, "type": "VAELoader",
     "pos": [120.0, 600.0], "size": [320, 102], "flags": {}, "order": 4, "mode": 0,
     "inputs": [], "outputs": [{"name": "VAE", "type": "VAE", "links": [5], "slot_index": 0}],
     "title": "Load Audio VAE",
     "properties": {"Node name for S&R": "VAELoader"},
     "widgets_values": ["minimax_h3_audio_vae_fp32.safetensors"]},
    {"id": 5, "type": "LoraLoaderModelOnly",
     "pos": [120.0, 760.0], "size": [320, 166], "flags": {}, "order": 5, "mode": 0,
     "inputs": [{"name": "model", "type": "MODEL", "link": 1}],
     "outputs": [{"name": "MODEL", "type": "MODEL", "links": [2], "slot_index": 0}],
     "title": "Load 4-step Turbo LoRA (教程配方, 强度 0.8)",
     "properties": {"Node name for S&R": "LoraLoaderModelOnly"},
     "widgets_values": ["minimax_h3_fl2v_turbo_4step_v1.2_768p_comfyui_bf16.safetensors", 0.8, 0.8]},
]

LINKS = [
    [1, 1, 0, 5, 0, "MODEL"],
    [2, 5, 0, 6, 0, "MODEL"],
    [3, 2, 0, 6, 1, "CLIP"],
    [4, 3, 0, 6, 2, "VAE"],
    [5, 4, 0, 6, 3, "VAE"],
    [6, 6, 7, 7, 0, "IMAGE"],
    [7, 7, 0, 8, 0, "IMAGE"],
    [8, 6, 8, 8, 1, "AUDIO"],
]

WF = {
    "last_node_id": 8, "last_link_id": 8,
    "nodes": LOADERS + [MAIN, KEY, SAVE],
    "links": LINKS,
    "groups": [], "config": {}, "extra": {}, "version": 0.4,
}

OUT = os.path.abspath(OUT)
with io.open(OUT, "w", encoding="utf-8") as fh:
    fh.write(json.dumps(WF, ensure_ascii=False, indent=2))
print("written:", OUT)
print("nodes:", len(WF["nodes"]), "links:", len(WF["links"]))
