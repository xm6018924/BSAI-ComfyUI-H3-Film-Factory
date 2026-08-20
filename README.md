# BSAI-ComfyUI-H3 Film Factory

**H3 电影工厂 — MiniMax H3 全流程影视制作工具包**

A complete film production toolkit for [MiniMax H3](https://www.minimax.io/blog/minimax-h3) workflows in ComfyUI. Provides asset library management, storyboard-style clip sequencing, subtitle rendering, media combining, and contextual frame extraction for visual consistency across clips.

一个为 ComfyUI 中 [MiniMax H3](https://www.minimax.io/blog/minimax-h3) 工作流打造的完整影视制作工具包。提供资产管理、分镜式片段编排、字幕渲染、媒体拼接、以及跨片段视觉一致性参考帧提取功能。

---

## Features | 功能特性

- **Asset Library** — Upload images, videos, and audio via node UI; auto-indexed as `@图N` / `@视频N` / `@音频N`
- **Storyboard Sequencer** — Vertical CLIP card layout with prompt, subtitle, audio mode, duration, and seed per clip
- **Subtitle System** — Burn-in narration (旁白) and dialogue (对白) subtitles with Windows font support
- **Media Combiner** — Concatenate up to 16 video clips or audio streams into one continuous output
- **Contextual Frame Extraction** — Extract reference frames from generated video for cross-clip visual consistency

- **资产库** — 通过节点 UI 上传图片、视频、音频；自动编号为 `@图N` / `@视频N` / `@音频N`
- **分镜编排器** — 竖排 CLIP 卡片，每个片段独立设置提示词、字幕、音频模式、时长和种子
- **字幕系统** — 使用 Windows 系统字体烧录旁白和对白字幕
- **媒体拼接器** — 最多拼接 16 段视频或音频流为一条连续输出
- **上下文帧提取** — 从已生成视频中提取参考帧，保持跨片段视觉一致性

---

## Installation | 安装

1. Clone this repository into your ComfyUI `custom_nodes` directory:
   将此仓库克隆到 ComfyUI 的 `custom_nodes` 目录下：

   ```bash
   cd ComfyUI/custom_nodes
   git clone https://github.com/xm6018924/BSAI-ComfyUI-H3-Film-Factory.git
   ```

2. Install dependencies | 安装依赖：

   ```bash
   pip install -r BSAI-ComfyUI-H3-Film-Factory/requirements.txt
   ```

3. Restart ComfyUI | 重启 ComfyUI

---

## Nodes | 节点说明

All nodes are categorized under `BSAI/H3 Film Factory` in the ComfyUI node menu.

所有节点均位于 ComfyUI 节点菜单的 `BSAI/H3 Film Factory` 分类下。

### 1. BSAI Asset Library Input | 资产库输入

| | |
|---|---|
| **Type** | `BSAI_AssetLibraryInput` |
| **Category** | BSAI/H3 Film Factory |
| **Output** | `ASSET_LIBRARY` |

Upload images, videos, and audio files into a unified asset library. Files are uploaded via the node UI (batch or single) and stored in `input/bsai_assets/{images,videos,audio}/`. Each asset is auto-indexed: 图1, 图2, ... / 视频1, ... / 音频1, ...

上传图片、视频和音频文件到统一资产库。文件通过节点 UI 上传（批量或单个），存储在 `input/bsai_assets/{images,videos,audio}/` 目录。每个资产自动编号：图1, 图2, ... / 视频1, ... / 音频1, ...

**Inputs | 输入:**
- `image_files` (STRING): JSON array of uploaded image filenames | 已上传图片文件名的 JSON 数组
- `video_files` (STRING): JSON array of uploaded video filenames | 已上传视频文件名的 JSON 数组
- `audio_files` (STRING): JSON array of uploaded audio filenames | 已上传音频文件名的 JSON 数组

**Features | 特性:**
- Drag-and-drop reordering with auto-renumbering | 拖拽排序并自动重新编号
- Replace button (green ↻) preserves original numbering | 替换按钮（绿色 ↻）保持原始编号
- Delete button (red ✕) triggers renumbering to fill gaps | 删除按钮（红色 ✕）触发重新编号填补空缺
- Video thumbnails extracted via first frame | 视频缩略图通过首帧提取
- Asset order saved to `asset_order.json` | 资产顺序保存到 `asset_order.json`

---

### 2. BSAI Asset Reference Selector | 资产引用选择器

| | |
|---|---|
| **Type** | `BSAI_AssetRefSelector` |
| **Category** | BSAI/H3 Film Factory |
| **Outputs** | `IMAGE`, `IMAGE×3`, `AUDIO×3`, `AUDIO×3`, `STRING` |

Parse `@图N` / `@视频N` / `@音频N` notation in the prompt, load referenced assets, and output them for `MiniMaxH3ReferenceToVideo`. Replaces `@` tags with H3 `<Picture N>` / `<Video N>` / `<Audio N>` tags in the formatted prompt.

解析提示词中的 `@图N` / `@视频N` / `@音频N` 标记，加载引用的资产，输出给 `MiniMaxH3ReferenceToVideo`。将 `@` 标记替换为 H3 的 `<Picture N>` / `<Video N>` / `<Audio N>` 标签。

**Inputs | 输入:**
- `asset_library` (ASSET_LIBRARY): Connect from BSAI_AssetLibraryInput | 连接 BSAI_AssetLibraryInput
- `prompt` (STRING): Prompt text with `@图1 @视频1 @音频1` notation | 包含 `@图1 @视频1 @音频1` 标记的提示词

**Limits | 限制:**
- Up to 9 reference images (`@图1`–`@图9`) | 最多 9 张参考图
- Up to 3 reference videos (`@视频1`–`@视频3`) | 最多 3 段参考视频
- Up to 3 reference audios (`@音频1`–`@音频3`) | 最多 3 段参考音频

---

### 3. BSAI Image Batch Splitter | 图像批次拆分器

| | |
|---|---|
| **Type** | `BSAI_ImageBatchSplitter` |
| **Category** | BSAI/H3 Film Factory |
| **Outputs** | `IMAGE×9` |

Split an IMAGE batch into individual images (up to 9) for `MiniMaxH3ReferenceToVideo` `ref_image_0..8` inputs.

将 IMAGE 批次拆分为单独的图像（最多 9 张），用于 `MiniMaxH3ReferenceToVideo` 的 `ref_image_0..8` 输入。

---

### 4. BSAI Clip Composer | 片段编辑器

| | |
|---|---|
| **Type** | `BSAI_ClipComposer` |
| **Category** | BSAI/H3 Film Factory |
| **Output** | `CLIP_INFO` |

Compose a single clip with generation prompt, subtitle text, audio settings, and asset references. Supports `@图N` / `@视频N` / `@音频N` notation for referencing assets from BSAI_AssetLibraryInput.

编辑单个片段，包含生成提示词、字幕文本、音频设置和资产引用。支持 `@图N` / `@视频N` / `@音频N` 标记引用 BSAI_AssetLibraryInput 中的资产。

**Inputs | 输入:**
- `prompt` (STRING, multiline): Generation prompt. Use `【旁白】` / `【对白】` for subtitles | 生成提示词。使用 `【旁白】` / `【对白】` 标记字幕
- `asset_refs` (STRING): Asset references like `@图1 @图2 @视频1 @音频1` | 资产引用
- `narration` (STRING, multiline): Narration subtitle text (旁白字幕) | 旁白字幕文本
- `dialogue` (STRING, multiline): Dialogue subtitle text (对白字幕) | 对白字幕文本
- `subtitle_source`: `manual` or `extract_from_prompt` | 手动输入或从提示词提取
- `audio_mode`: `H3_auto` (use H3 generated audio) or `custom` | H3 自动或自定义
- `duration` (FLOAT): Clip duration in seconds, snapped to H3 17n+5 frame grid | 片段时长（秒），对齐到 H3 17n+5 帧网格
- `width` / `height` (INT): Video resolution (multiple of 32) | 视频分辨率（32 的倍数）
- `seed` (INT): Generation seed | 生成种子

---

### 5. BSAI Clip Sequencer | 分镜编排器

| | |
|---|---|
| **Type** | `BSAI_ClipSequencer` |
| **Category** | BSAI/H3 Film Factory |
| **Output** | `CLIP_SEQUENCE` |

Self-contained storyboard sequencer with vertical CLIP cards. Define clips directly in the node UI (top-to-bottom arrangement). Each card has a prompt textarea, duration, audio mode, subtitle source, and an expandable advanced section (narration, dialogue, width, height, seed).

自带竖排 CLIP 卡片的分镜编排器。直接在节点 UI 中定义片段（从上到下排列）。每张卡片包含提示词文本框、时长、音频模式、字幕来源，以及可展开的高级设置（旁白、对白、宽高、种子）。

**Inputs | 输入:**
- `clips_json` (STRING): JSON array of clip definitions (managed by UI) | 片段定义的 JSON 数组（由 UI 管理）
- `clip_1` – `clip_4` (CLIP_INFO, optional): External clips from BSAI_ClipComposer | 来自 BSAI_ClipComposer 的外部片段
- `asset_library` (ASSET_LIBRARY, optional): Connect for `@` notation resolution | 连接以支持 `@` 标记解析

**UI Features | UI 特性:**
- "+ 添加 CLIP / Add CLIP" button for manual clip addition | 手动添加片段按钮
- Per-clip delete button (✕) with auto-renumbering | 每段独立删除按钮，自动重新编号
- Bottom summary: clip count + total duration | 底部汇总：片段数 + 总时长
- "↻ 刷新资产库" button per clip to reload assets | 每段刷新资产库按钮
- Left panel: asset selection with thumbnails and @ labels | 左侧面板：资产选择带缩略图和 @ 标签
- Collapsible "字幕/高级设置" section per clip | 可折叠的字幕/高级设置

---

### 6. BSAI Subtitle Config | 字幕配置

| | |
|---|---|
| **Type** | `BSAI_SubtitleConfig` |
| **Category** | BSAI/H3 Film Factory |
| **Output** | `SUBTITLE_CONFIG` |

Configure subtitle font, color, size, and position. Font selection from `C:\Windows\Fonts`. Supports two subtitle types: narration (旁白) and dialogue (对白).

配置字幕字体、颜色、大小和位置。字体选自 `C:\Windows\Fonts`。支持两种字幕类型：旁白和对白。

**Inputs | 输入:**
- `font_name`: Font file from Windows Fonts directory | Windows 字体目录中的字体文件
- `font_size` (INT): Font size in pixels (8–200) | 字体大小（像素）
- `narration_color` (STRING): Narration subtitle color (hex, e.g. `#FFFFFF`) | 旁白字幕颜色
- `dialogue_color` (STRING): Dialogue subtitle color (hex, e.g. `#FFEE88`) | 对白字幕颜色
- `narration_position`: `top` / `center` / `bottom` | 旁白位置
- `dialogue_position`: `top` / `center` / `bottom` | 对白位置
- `background_box` (BOOLEAN): Draw semi-transparent background behind text | 绘制半透明背景
- `margin` (INT): Margin from screen edge in pixels | 距屏幕边缘的边距（像素）

---

### 7. BSAI Subtitle Renderer | 字幕渲染器

| | |
|---|---|
| **Type** | `BSAI_SubtitleRenderer` |
| **Category** | BSAI/H3 Film Factory |
| **Output** | `IMAGE` |

Render narration (旁白) and dialogue (对白) subtitles on video frames. Can extract subtitle text from `CLIP_INFO` or accept direct text input.

在视频帧上渲染旁白和对白字幕。可从 `CLIP_INFO` 提取字幕文本或接受直接文本输入。

**Inputs | 输入:**
- `images` (IMAGE): Video frames to render subtitles on | 要渲染字幕的视频帧
- `subtitle_config` (SUBTITLE_CONFIG): Subtitle styling configuration | 字幕样式配置
- `clip_info` (CLIP_INFO, optional): Clip info with narration/dialogue text | 包含旁白/对白文本的片段信息
- `narration` (STRING, optional): Manual narration text (used if clip_info not connected) | 手动旁白文本
- `dialogue` (STRING, optional): Manual dialogue text (used if clip_info not connected) | 手动对白文本

**Features | 特性:**
- CJK text wrapping (auto line-break for Chinese) | 中文自动换行
- Word-based wrapping for English | 英文按词换行
- Semi-transparent background box option | 半透明背景选项
- Supports multiple paragraphs | 支持多段落

---

### 8. BSAI Video Combiner | 视频拼接器

| | |
|---|---|
| **Type** | `BSAI_VideoCombiner` |
| **Category** | BSAI/H3 Film Factory |
| **Output** | `IMAGE` |

Combine multiple video clips (IMAGE batches) into a single continuous video. All clips are resized to match the first clip's resolution using bilinear interpolation. Connect clips top-to-bottom for storyboard-style sequencing.

将多段视频（IMAGE 批次）拼接为一条连续视频。所有片段使用双线性插值缩放到第一段的分辨率。从上到下连接片段实现分镜式排列。

**Inputs | 输入:**
- `clip_1` – `clip_16` (IMAGE, optional): Up to 16 video clips | 最多 16 段视频

---

### 9. BSAI Audio Combiner | 音频拼接器

| | |
|---|---|
| **Type** | `BSAI_AudioCombiner` |
| **Category** | BSAI/H3 Film Factory |
| **Output** | `AUDIO` |

Combine multiple audio streams into a single continuous audio track. All audio is resampled to match the first stream's sample rate.

将多段音频流拼接为一条连续音频轨道。所有音频重采样以匹配第一段的采样率。

**Inputs | 输入:**
- `audio_1` – `audio_16` (AUDIO, optional): Up to 16 audio streams | 最多 16 段音频

---

### 10. BSAI Contextual Series Extract | 上下文系列提取

| | |
|---|---|
| **Type** | `BSAI_ContextualSeriesExtract` |
| **Category** | BSAI/H3 Film Factory |
| **Outputs** | `IMAGE`, `INT` |

Extract reference frames from a previously generated video to maintain visual consistency (characters, scenes, props, lighting, colors) across sequential video generations. Designed for MiniMax H3 Omni Reference mode, which accepts up to 9 reference images.

从已生成的视频中提取参考帧，以保持跨片段的视觉一致性（角色、场景、道具、光照、色彩）。专为 MiniMax H3 Omni Reference 模式设计，支持最多 9 张参考图。

**Inputs | 输入:**
- `images` (IMAGE): Input video frames | 输入视频帧
- `selection_mode`: `last_n` / `first_n` / `middle_n` / `custom_range` | 选择模式
- `frame_count` (INT): Number of frames to extract | 提取帧数
- `start_frame` / `end_frame` (INT): For custom_range mode | 用于自定义范围模式
- `max_output_frames` (INT): Max frames after subsampling (default 9) | 子采样后最大帧数
- `sampling_method`: `even` / `sequential` | 采样方法
- `save_frames` (BOOLEAN, optional): Save extracted frames as PNG | 保存提取帧为 PNG
- `output_subdir` (STRING, optional): Output subdirectory | 输出子目录
- `filename_prefix` (STRING, optional): Saved frame filename prefix | 保存帧文件名前缀

---

### 11. BSAI Contextual Series Load | 上下文系列加载

| | |
|---|---|
| **Type** | `BSAI_ContextualSeriesLoad` |
| **Category** | BSAI/H3 Film Factory |
| **Outputs** | `IMAGE`, `INT` |

Load previously saved contextual reference frames from disk. Pairs with BSAI_ContextualSeriesExtract for cross-session workflows where run 1 and run 2 happen in separate ComfyUI sessions.

从磁盘加载之前保存的上下文参考帧。与 BSAI_ContextualSeriesExtract 配对使用，适用于跨会话工作流（第一次和第二次运行在不同的 ComfyUI 会话中）。

**Inputs | 输入:**
- `directory` (STRING): Directory containing saved frame PNG files | 包含已保存帧 PNG 文件的目录
- `filename_prefix` (STRING): Only load files starting with this prefix | 仅加载以此前缀开头的文件
- `max_frames` (INT): Maximum number of frames to load | 最大加载帧数
- `sampling_method`: `even` / `sequential` / `all` | 采样方法

---

## @ Notation Reference | @ 标记参考

| Notation | Type | Example | Replaced With |
|---|---|---|---|
| `@图N` | Image | `@图1` | `<Picture 1>` |
| `@视频N` | Video | `@视频1` | `<Video 1>` |
| `@音频N` | Audio | `@音频1` | `<Audio 1>` |

| 标记 | 类型 | 示例 | 替换为 |
|---|---|---|---|
| `@图N` | 图片 | `@图1` | `<Picture 1>` |
| `@视频N` | 视频 | `@视频1` | `<Video 1>` |
| `@音频N` | 音频 | `@音频1` | `<Audio 1>` |

---

## Subtitle Syntax | 字幕语法

Use `【旁白】` and `【对白】` markers in the prompt to automatically extract subtitle text:

在提示词中使用 `【旁白】` 和 `【对白】` 标记可自动提取字幕文本：

```
【旁白】午后的阳光穿过树叶，洒在庭院里。
【对白】我先看到它的了
```

When `subtitle_source = extract_from_prompt`, these lines are extracted into the narration and dialogue fields respectively.

当 `subtitle_source = extract_from_prompt` 时，这些行分别被提取到旁白和对白字段中。

---

## H3 Frame Grid | H3 帧网格

Clip durations are snapped to MiniMax H3's frame grid: `5, 22, 39, 56, 73, 90, 107, 124, 141, 158, 175, 192, 209, 226, 243` frames at 24fps.

片段时长会对齐到 MiniMax H3 的帧网格：24fps 下为 `5, 22, 39, 56, 73, 90, 107, 124, 141, 158, 175, 192, 209, 226, 243` 帧。

| Duration (s) | Frames | Duration (s) | Frames |
|---|---|---|---|
| 0.21 | 5 | 3.63 | 87→90 |
| 0.92 | 22 | 5.71 | 137→141 |
| 1.63 | 39 | 7.29 | 175 |
| 2.33 | 56 | 9.54 | 226 |
| 3.04 | 73 | 10.13 | 243 |

---

## Example Workflow | 工作流示例

A complete example workflow is included in `example_workflows/`. Load it in ComfyUI via the **Load** button to see a full film production pipeline:

完整示例工作流位于 `example_workflows/` 目录。在 ComfyUI 中通过 **Load** 按钮加载，查看完整的影视制作流程：

```
BSAI_AssetLibraryInput → BSAI_ClipSequencer → [H3 Generation] → BSAI_SubtitleRenderer → BSAI_VideoCombiner
                                ↑                                                        ↑
                    BSAI_ContextualSeriesExtract ──────────────────────────────────────┘
```

---

## Technical Details | 技术细节

- **Asset storage**: `ComfyUI/input/bsai_assets/{images,videos,audio}/` | 资产存储路径
- **Asset ordering**: `asset_order.json` manifest | 资产排序清单
- **Web extensions**: `web/js/asset_library.js`, `web/js/clip_sequencer.js` | 前端扩展
- **API endpoints**: `/bsai/upload_asset`, `/bsai/list_all_assets`, `/bsai/asset_file`, `/bsai/video_frame`, `/bsai/replace_asset`, `/bsai/save_asset_order`, `/bsai/list_fonts` | API 端点
- **Compatibility**: Designed for MiniMax H3 workflows with `MiniMaxH3Extender` and `MiniMaxH3MotionContextDiskFinalDecode` nodes | 兼容性

---

## License | 许可证

MIT License — See [LICENSE](LICENSE) file for details.

MIT 许可证 — 详情见 [LICENSE](LICENSE) 文件。

## Author | 作者

BSAI — [github.com/xm6018924](https://github.com/xm6018924)
