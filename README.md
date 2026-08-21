# BSAI ComfyUI H3 Film Factory

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
- **Per-CLIP Regeneration** — Regenerate individual clips without affecting others; manual merge via button
- **Bilingual UI** — All buttons and labels in Chinese/English dual language

- **资产库** — 通过节点 UI 上传图片、视频、音频；自动编号为 `@图N` / `@视频N` / `@音频N`
- **分镜编排器** — 竖排 CLIP 卡片，每个片段独立设置提示词、字幕、音频模式、时长和种子
- **字幕系统** — 使用 Windows 系统字体烧录旁白和对白字幕
- **媒体拼接器** — 最多拼接 16 段视频或音频流为一条连续输出
- **上下文帧提取** — 从已生成视频中提取参考帧，保持跨片段视觉一致性
- **单CLIP重新生成** — 可单独重新生成某个CLIP而不影响其他片段；通过按钮手动合并
- **双语界面** — 所有按钮和标签均为中英双语对照

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

### 0. BSAI ComfyUI H3 Film Factory (Main Node) | 主节点

| | |
|---|---|
| **Type** | `MiniMaxH3Extender` |
| **Display Name** | BSAI ComfyUI H3 Film Factory |
| **Category** | BSAI/H3 Film Factory |
| **Web Extension** | `BSAIMiniMaxH3.Extender` |

The core node for MiniMax H3 video generation with a full-featured custom UI. Supports multi-CLIP storyboard sequencing, per-CLIP rendering, preview, and merging.

MiniMax H3 视频生成的核心节点，配备全功能自定义界面。支持多CLIP分镜编排、逐CLIP渲染、预览和合并。

**UI Layout | 界面布局:**

```
┌─────────────────────────────────────────────────┐
│ Toolbar: 保存/加载 | 时长 | 应用全部 | 上下文 | 合并 │
├─────────────────────────────────────────────────┤
│ Global Prompt Section                            │
│ ┌──────────┬──────────────────────────────────┐ │
│ │ 已引用资产 │ 全局提示词 (与左侧同高)            │ │
│ │ @图1      │                                    │ │
│ │ @图2      │                                    │ │
│ └──────────┴──────────────────────────────────┘ │
├─────────────────────────────────────────────────┤
│ CLIP Cards (scrollable)                           │
│ ┌─ CLIP 1 ────────────────────── ✕ ─────────────┐│
│ │ Prompt | Subtitle | Context | Seed | Duration ││
│ └─────────────────────────────────────────────────┘│
│ ┌─ CLIP 2 ────────────────────── ✕ ─────────────┐│
│ │ ...                                              ││
│ └─────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────┤
│ CLIPS | 总时长 45s (3 clips)   [添加CLIP] [全部删除] │
└─────────────────────────────────────────────────┘
```

**Toolbar Buttons | 工具栏按钮:**

| Button | Description | 说明 |
|--------|-------------|------|
| 保存 / Save | Save project as portable .ext file | 保存项目为 .ext 文件 |
| 加载 / Load | Load .ext project file | 加载 .ext 项目文件 |
| 时长(s) / Dur | Batch set duration for all clips | 批量设置所有片段时长 |
| 应用全部 / Apply All | Apply batch duration to all clips | 应用批量时长到所有片段 |
| 上下文 / Context | Toggle context reference for all clips | 切换所有片段的上下文参考 |
| 合并输出 / Merge Output | Merge all generated clips into one video | 合并所有已生成片段 |

**Bottom Bar | 底部栏:**

- **Left side**: `CLIPS | 总时长 Ns (N clips)` — total duration across all clips | 所有片段时长统计
- **Right side**: `[添加CLIP / Add CLIP]` + `[全部删除CLIP / DEL ALL CLIP]` — add/delete buttons grouped together | 添加/删除按钮紧靠一起

**Per-CLIP Features | 单CLIP功能:**

- Red ✕ button on each CLIP header to delete that clip | 每个CLIP头部的红色✕按钮可删除该片段
- Per-CLIP render toggle (Generate) | 单CLIP渲染开关
- Per-CLIP replace button (Regenerate) — only regenerates the selected clip | 单CLIP重新生成按钮，仅重新生成选中的片段
- Per-CLIP collapsed/expanded toggle | 单CLIP折叠/展开切换
- Per-CLIP subtitle settings (font, size, color, bold) | 单CLIP字幕设置
- Per-CLIP seed and duration | 单CLIP种子和时长
- Per-CLIP context reference checkbox and frame extraction | 单CLIP上下文参考和帧提取
- Per-CLIP asset panel with @ notation support | 单CLIP资产面板支持@标记

**Global Prompt | 全局提示词:**

- Textarea auto-stretches to match the left asset panel height | 文本框自动拉伸至与左侧资产面板同高
- Expand button (⤢) for full-screen editing | 展开按钮用于全屏编辑
- Auto-syncs with external `global_prompt` input | 自动与外部输入同步

---

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

---

### 6. BSAI Subtitle Config | 字幕配置

| | |
|---|---|
| **Type** | `BSAI_SubtitleConfig` |
| **Category** | BSAI/H3 Film Factory |
| **Output** | `SUBTITLE_CONFIG` |

Configure subtitle font, color, size, and position. Font selection from `C:\Windows\Fonts`. Supports two subtitle types: narration (旁白) and dialogue (对白).

配置字幕字体、颜色、大小和位置。字体选自 `C:\Windows\Fonts`。支持两种字幕类型：旁白和对白。

---

### 7. BSAI Subtitle Renderer | 字幕渲染器

| | |
|---|---|
| **Type** | `BSAI_SubtitleRenderer` |
| **Category** | BSAI/H3 Film Factory |
| **Output** | `IMAGE` |

Render narration (旁白) and dialogue (对白) subtitles on video frames. Can extract subtitle text from `CLIP_INFO` or accept direct text input.

在视频帧上渲染旁白和对白字幕。可从 `CLIP_INFO` 提取字幕文本或接受直接文本输入。

---

### 8. BSAI Video Combiner | 视频拼接器

| | |
|---|---|
| **Type** | `BSAI_VideoCombiner` |
| **Category** | BSAI/H3 Film Factory |
| **Output** | `IMAGE` |

Combine multiple video clips (IMAGE batches) into a single continuous video. All clips are resized to match the first clip's resolution using bilinear interpolation.

将多段视频（IMAGE 批次）拼接为一条连续视频。所有片段使用双线性插值缩放到第一段的分辨率。

---

### 9. BSAI Audio Combiner | 音频拼接器

| | |
|---|---|
| **Type** | `BSAI_AudioCombiner` |
| **Category** | BSAI/H3 Film Factory |
| **Output** | `AUDIO` |

Combine multiple audio streams into a single continuous audio track. All audio is resampled to match the first stream's sample rate.

将多段音频流拼接为一条连续音频轨道。所有音频重采样以匹配第一段的采样率。

---

### 10. BSAI Contextual Series Extract | 上下文系列提取

| | |
|---|---|
| **Type** | `BSAI_ContextualSeriesExtract` |
| **Category** | BSAI/H3 Film Factory |
| **Outputs** | `IMAGE`, `INT` |

Extract reference frames from a previously generated video to maintain visual consistency (characters, scenes, props, lighting, colors) across sequential video generations. Designed for MiniMax H3 Omni Reference mode, which accepts up to 9 reference images.

从已生成的视频中提取参考帧，以保持跨片段的视觉一致性（角色、场景、道具、光照、色彩）。专为 MiniMax H3 Omni Reference 模式设计，支持最多 9 张参考图。

---

### 11. BSAI Contextual Series Load | 上下文系列加载

| | |
|---|---|
| **Type** | `BSAI_ContextualSeriesLoad` |
| **Category** | BSAI/H3 Film Factory |
| **Outputs** | `IMAGE`, `INT` |

Load previously saved contextual reference frames from disk. Pairs with BSAI_ContextualSeriesExtract for cross-session workflows.

从磁盘加载之前保存的上下文参考帧。与 BSAI_ContextualSeriesExtract 配对使用，适用于跨会话工作流。

---

## @ Notation Reference | @ 标记参考

| Notation | Type | Example | Replaced With |
|---|---|---|---|
| `@图N` | Image | `@图1` | `<Picture 1>` |
| `@视频N` | Video | `@视频1` | `<Video 1>` |
| `@音频N` | Audio | `@音频1` | `<Audio 1>` |

---

## Subtitle Syntax | 字幕语法

Use `【旁白】` and `【对白】` markers in the prompt to automatically extract subtitle text:

在提示词中使用 `【旁白】` 和 `【对白】` 标记可自动提取字幕文本：

```
【旁白】午后的阳光穿过树叶，洒在庭院里。
【对白】我先看到它的了
```

---

## H3 Frame Grid | H3 帧网格

Clip durations are snapped to MiniMax H3's frame grid: `5, 22, 39, 56, 73, 90, 107, 124, 141, 158, 175, 192, 209, 226, 243` frames at 24fps.

片段时长会对齐到 MiniMax H3 的帧网格：24fps 下为 `5, 22, 39, 56, 73, 90, 107, 124, 141, 158, 175, 192, 209, 226, 243` 帧。

---

## Example Workflow | 工作流示例

A complete example workflow is included in `example_workflows/`. Load it in ComfyUI via the **Load** button to see a full film production pipeline:

完整示例工作流位于 `example_workflows/` 目录。在 ComfyUI 中通过 **Load** 按钮加载，查看完整的影视制作流程：

```
BSAI_AssetLibraryInput → BSAI ComfyUI H3 Film Factory → [H3 Generation] → BSAI_SubtitleRenderer → BSAI_VideoCombiner
                                     ↑                                                        ↑
                           BSAI_ContextualSeriesExtract ──────────────────────────────────────┘
```

---

## Technical Details | 技术细节

- **Asset storage**: `ComfyUI/input/bsai_assets/{images,videos,audio}/` | 资产存储路径
- **Asset ordering**: `asset_order.json` manifest | 资产排序清单
- **Web extensions**: `web/extender.js` (main node UI), `web/js/asset_library.js`, `web/js/clip_sequencer.js`, `web/live_preview.js` | 前端扩展
- **Extension name**: `BSAIMiniMaxH3.Extender` (unique to avoid conflicts) | 扩展名称（唯一避免冲突）
- **API endpoints**: `/bsai/upload_asset`, `/bsai/list_all_assets`, `/bsai/asset_file`, `/bsai/video_frame`, `/bsai/replace_asset`, `/bsai/save_asset_order`, `/bsai/list_fonts` | API 端点
- **Compatibility**: Designed for MiniMax H3 workflows | 兼容性：专为 MiniMax H3 工作流设计

---

## License | 许可证

MIT License — See [LICENSE](LICENSE) file for details.

MIT 许可证 — 详情见 [LICENSE](LICENSE) 文件。

## Author | 作者

BSAI — [github.com/xm6018924](https://github.com/xm6018924)
