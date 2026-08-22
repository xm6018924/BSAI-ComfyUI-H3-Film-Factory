# BSAI ComfyUI H3 Film Factory

**BSAI 电影工厂 — MiniMax H3 全自动电影短片生成工具包**

A complete AI filmmaking toolkit for [MiniMax H3](https://www.minimax.io/blog/minimax-h3) workflows in ComfyUI. From script to screen — storyboard-driven clip generation, asset library, inline thumbnails, auto-subtitle extraction, face repair, and HD upscaling.

一个为 ComfyUI 中 [MiniMax H3](https://www.minimax.io/blog/minimax-h3) 工作流打造的全流程影视制作工具包。从剧本到成片——分镜驱动片段生成、资产库、内联缩略图、自动字幕提取、人脸修复、高清放大。

---

## Features | 功能特性

### Core Engine | 核心引擎
- **Storyboard-Driven Generation** — Connect a Text Multiline node with `[整体风格]`, `[角色档案]`, `[分镜N]` markers; the system auto-splits global prompt vs. storyboard segments, auto-creates CLIPs, and syncs prompt + duration per clip
- **Per-CLIP Cards** — Vertical card layout with prompt, subtitle, duration, seed, audio mode, context reference, and color tag per clip
- **Per-CLIP Regeneration** — Regenerate any single CLIP without affecting others; manual merge via "合并输出 / Merge Output" button
- **Per-CLIP Refresh Button** — Blue ↻ button on each CLIP header to re-sync from external source
- **Live Latent Preview** — Real-time latent-space preview during rendering, showing progress per step
- **Per-CLIP Video Preview with Audio** — Each clip preview includes both video and audio; overlap frames are trimmed so clips merge seamlessly
- **Seamless Merge Output** — One-click merge of all clips into a single MP4 with no duplicate frames at boundaries

- **分镜驱动生成** — 连接 Text Multiline 节点，包含 `[整体风格]`、`[角色档案]`、`[分镜N]` 标记；系统自动拆分全局提示词与分镜段，自动创建CLIP，同步每个CLIP的提示词和时长
- **独立CLIP卡片** — 竖排卡片布局，每个片段独立设置提示词、字幕、时长、种子、音频模式、上下文参考、颜色标签
- **单CLIP重新生成** — 可单独重新生成某个CLIP而不影响其他片段；通过"合并输出"按钮手动合并
- **单CLIP刷新按钮** — 每个CLIP头部有蓝色↻按钮，可从外部输入源重新同步
- **潜空间实时预览** — 渲染过程中实时显示潜空间预览帧，展示每步进度
- **带音频的单CLIP视频预览** — 每个CLIP预览同时包含视频和音频；上下文重叠帧已自动去除，确保合并时无缝衔接
- **一键合并输出** — 一键将所有CLIP合并为单个MP4，连接处无重复画面

### Asset Library | 资产库
- **Upload & Index** — Upload images/videos/audio via node UI; auto-indexed as `@图N` / `@视频N` / `@音频N`
- **Inline Thumbnails** — `@图N` references in prompts show small thumbnail images directly after the text (overlay technique: transparent textarea + visible overlay div)
- **Referenced Assets Panel** — Left panel auto-shows all `@图N` thumbnails referenced in the prompt

- **上传与编号** — 通过节点UI上传图片/视频/音频；自动编号为 `@图N` / `@视频N` / `@音频N`
- **内联缩略图** — 提示词中的 `@图N` 引用直接在文字后面显示小缩略图（覆盖层技术：透明textarea + 可见overlay div）
- **已引用资产面板** — 左侧面板自动显示提示词中引用的所有 `@图N` 缩略图

### Subtitle System | 字幕系统
- **Manual Mode** — Direct text input for subtitles
- **Auto-Extract Mode** — Parses prompt text to auto-generate subtitles:
  - **对白 / Dialogue** — Extracts text from `角色N说："..."` patterns
  - **旁白 / Narration** — Extracts descriptive lines (>10 chars, excludes dialogue/sound/camera directions)
  - **歌词 / Lyrics** — Extracts text within `♪` symbols
- **Font Options** — Windows system fonts (微软雅黑, SimHei, etc.), size, color, bold, box outline

- **手动模式** — 直接输入字幕文本
- **自动提取模式** — 解析提示词文本自动生成字幕：
  - **对白 / Dialogue** — 从 `角色N说："..."` 模式提取文本
  - **旁白 / Narration** — 提取描述性文字（>10字，排除对白/音效/镜头指导）
  - **歌词 / Lyrics** — 提取 `♪` 符号内的文本
- **字体选项** — Windows系统字体（微软雅黑、SimHei等），大小、颜色、加粗、边框

### Unified Prompt Source | 统一提示词输入源
- **Single Input Port** — `prompt_source` port receives all text (global + storyboard) from one Text Multiline node
- **Auto-Split** — Text before `[分镜1]` → global prompt; text from `[分镜1]` onward → CLIP prompts
- **Auto-Duration** — Parses last time range in each segment (e.g., `6-9秒` → 9s) and sets CLIP Duration
- **Auto-CLIP Creation** — 4 storyboard segments → 4 CLIPs created automatically
- **Always Sync** — Page refresh / reload triggers aggressive retry sync (100ms, 500ms, 1200ms, 2500ms, 4000ms)
- **Refresh Buttons** — Global ↻ button + per-CLIP ↻ button for manual re-sync

- **单一输入端口** — `prompt_source` 端口从一个 Text Multiline 节点接收全部文本（全局+分镜）
- **自动拆分** — `[分镜1]` 之前的文本 → 全局提示词；`[分镜1]` 开始的文本 → CLIP提示词
- **自动时长** — 解析每个分镜段最后一个时间范围（如 `6-9秒` → 9秒）并设置CLIP Duration
- **自动创建CLIP** — 4个分镜段 → 自动创建4个CLIP
- **始终同步** — 页面刷新/重新加载触发多次重试同步（100ms、500ms、1200ms、2500ms、4000ms）
- **刷新按钮** — 全局↻按钮 + 每个CLIP的↻按钮可手动重新同步

### UI Design | 界面设计
- **Bilingual Labels** — All buttons and labels in Chinese/English
- **Node Title** — "BSAI ComfyUI H3 Film Factory" (no dashes)
- **Bottom Bar** — CLIPS total duration (left) + Add CLIP / Del All CLIP buttons (right), always visible
- **Per-CLIP Delete** — Red ✕ button on each CLIP header
- **Resizable** — Drag node bottom edge to resize; all CLIPs expand to fill height
- **Save/Load Project** — Purple Save / Green Load buttons for project file export/import

- **双语标签** — 所有按钮和标签均为中英双语
- **节点名称** — "BSAI ComfyUI H3 Film Factory"（无横杠）
- **底部栏** — CLIPS总时长（左）+ 添加CLIP / 全部删除CLIP按钮（右），始终可见
- **单CLIP删除** — 每个CLIP头部有红色✕按钮
- **可拉伸** — 拖动节点底部边缘调整大小；所有CLIP展开填满高度
- **保存/加载项目** — 紫色保存 / 绿色加载按钮，支持项目文件导出/导入

---

## Nodes | 节点列表

| Node | Description |
|------|-------------|
| **BSAI ComfyUI H3 Film Factory** (`BSAIH3FilmFactory`) | Core engine: storyboard-driven multi-CLIP generation with asset library, subtitles, and per-CLIP control |
| **BSAI H3 Final Decode & Export** (`BSAIH3FilmFactoryFinalDecode`) | Decode cached H3 motion latents to H.264 video (our plugin's cache, no conflict) |
| **H3 Latent Upscale 2x** (MiniMaxH3LatentUpscaleCombined) | 2x latent upscaling using H3 learned upscaler |
| **BSAI Asset Library** (BSAI_AssetLibraryInput) | Upload/manage images, videos, audio for @图N/@视频N/@音频N references |
| **H3 Face Track + Crop** (H3FaceTrackCrop) | Face detection and crop from video frames |
| **H3 Face Stitch** (H3FaceStitch) | Stitch refined face crops back to video |
| **H3 Inject Video Latent** (H3InjectVideoLatent) | Inject face crops as latent into H3 latent space |
| **H3 Per-Frame Denoise** (H3PerFrameDenoise) | Per-frame face denoising in latent space |
| **Empty H3 AV Latent** (EmptyMiniMaxH3LatentAV) | Create empty audio-visual latent for H3 |
| **Contextual Frame Extract** | Extract reference frames from generated video |
| **Media Combiner** | Concatenate up to 16 video/audio clips |
| **Subtitle Config** | Configure subtitle font, size, color, position |
| **Subtitle Render** | Render burn-in subtitles onto video |

---

## Installation | 安装

1. Clone or download to `ComfyUI/custom_nodes/BSAI-ComfyUI-H3-Film-Factory/`
2. Install dependencies: `pip install -r requirements.txt`
3. Restart ComfyUI
4. Load example workflow from `workflows/BSAI_H3_Film_Factory_v1.3.json`

1. 克隆或下载到 `ComfyUI/custom_nodes/BSAI-ComfyUI-H3-Film-Factory/`
2. 安装依赖：`pip install -r requirements.txt`
3. 重启 ComfyUI
4. 从 `workflows/BSAI_H3_Film_Factory_v1.3.json` 加载示例工作流

---

## Required Models | 所需模型

| Type | File |
|------|------|
| UNET | `minimax_h3_fl2va_int8_convrot.safetensors` |
| CLIP | `qwen3vl_32b_minimax_h3_ultra_uncensored_heretic_int8_convrot.safetensors` |
| VAE (video) | `minimax_h3_video_vae_int8_convrot.safetensors` |
| VAE (audio) | `minimax_h3_audio_vae_fp32.safetensors` |
| LoRA (optional) | `minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors` |
| Upscaler | `minimax_h3_latent_upscaler_3d_fp16.safetensors` |
| Face detector | `face_yolov8m.pt` (YOLOv8) |

---

## Quick Start | 快速开始

### 1. Load the Template Workflow | 加载模板工作流
Drag `workflows/BSAI_H3_Film_Factory_v1.3.json` into ComfyUI.

### 2. Connect Prompt Source | 连接提示词源
Connect a **Text Multiline** node to the `prompt_source` input port. Write your script:

将 **Text Multiline** 节点连接到 `prompt_source` 输入端口。编写剧本：

```
[整体风格]
电影级写实风格，自然光照

[角色档案]
角色1：浅棕色长发，翠绿宝石蝴蝶耳钉，淡蓝色亚麻连衣裙
角色2：黑色短发，灰白色粗麻衬衫，深棕色皮革腰带

[道具档案]
巨大的西瓜 @图3

[分镜1]：初始的觊觎
0-3秒：极缓推、中景。角色1位于画面左侧，视线锁定画面中央的西瓜切片。角色1说："我先看到它的了"
3-6秒：特写。焦点转移至西瓜切片。角色2说："不是说好了你今天想吃这个吗"
6-9秒：角色1眉头微蹙。

[分镜2]：边界的试探
0-4秒：过肩镜头。角色1说："我就是想尝尝看"
4-8秒：角色2说："我说过了，我先选"

[分镜3]：冲突的升级
0-4秒：角色1说："给我！"
4-6秒：角色2说："别碰！"
```

### 3. Auto-Sync Results | 自动同步结果
- **Global Prompt**: `[整体风格]...[道具档案]...` → fills global prompt area
- **CLIP 1**: Prompt from `[分镜1]`, Duration = 9s (last range `6-9秒`)
- **CLIP 2**: Prompt from `[分镜2]`, Duration = 8s (last range `4-8秒`)
- **CLIP 3**: Prompt from `[分镜3]`, Duration = 6s (last range `4-6秒`)
- **Bottom bar**: Shows `CLIPS | 总时长 23s (3 clips)`

- **全局提示词**：`[整体风格]...[道具档案]...` → 填入全局提示词区域
- **CLIP 1**：`[分镜1]` 内容，时长 = 9秒（最后时间范围 `6-9秒`）
- **CLIP 2**：`[分镜2]` 内容，时长 = 8秒（最后时间范围 `4-8秒`）
- **CLIP 3**：`[分镜3]` 内容，时长 = 6秒（最后时间范围 `4-6秒`）
- **底部栏**：显示 `CLIPS | 总时长 23s (3 clips)`

### 4. Upload Assets | 上传资产
Upload character/prop/scene images to the **BSAI Asset Library** node. Reference them as `@图1`, `@图2`, etc. in your prompt. Thumbnails appear inline.

上传角色/道具/场景图片到 **BSAI Asset Library** 节点。在提示词中用 `@图1`、`@图2` 等引用。缩略图会内联显示。

### 5. Subtitle Mode | 字幕模式
- **Manual**: Click "手动字幕 / Manual" and type subtitle text
- **Auto-Extract**: Click "自动提取 / Auto Extract", check 对白/旁白/歌词, subtitles auto-generate from prompt

- **手动**：点击"手动字幕 / Manual"并输入字幕文本
- **自动提取**：点击"自动提取 / Auto Extract"，勾选 对白/旁白/歌词，字幕从提示词自动生成

### 6. Lightning LoRA (Optional) | 闪电LoRA（可选）
Toggle the Boolean node: `true` = 4-step fast generation (with LoRA), `false` = 20-step full quality (without LoRA).

切换 Boolean 节点：`true` = 4步快速生成（启用LoRA），`false` = 20步完整质量（无LoRA）。

---

## Workflow Pipeline | 工作流流程

```
Text Multiline → prompt_source → [BSAI Film Factory]
                                    ↓
                              [Final Decode] → Video
                                    ↓
                         (Optional) [Face Repair] → Refined Video
                                    ↓
                         (Optional) [HD Upscale 2x] → HD Video
```

**Zone A — Main Generation**: Model loaders → H3 Film Factory → Final Decode → Video output
**Zone B — Face Repair (Optional)**: Load video → Face track/crop → Denoise → Stitch → Output
**Zone C — HD Upscale (Optional)**: Denoised latent → 2x upscale → CFG denoise → HD output

**A区 — 主生成**：模型加载 → H3 Film Factory → 最终解码 → 视频输出
**B区 — 人脸修复（可选）**：加载视频 → 人脸追踪裁剪 → 降噪 → 缝合 → 输出
**C区 — 高清放大（可选）**：降噪后潜空间 → 2倍放大 → CFG降噪 → 高清输出

---

## CLIP Card Anatomy | CLIP卡片结构

```
[▼] [CLIP 1] [name] [🎨] [▶/⏸] [替换] [状态] [↻刷新] [✕删除]
├── Left Panel: 已引用资产 (@图N thumbnails)
├── Right Panel:
│   ├── Prompt textarea (with inline @图N thumbnails overlay)
│   ├── Subtitle mode: 手动字幕 / 自动提取
│   ├── Subtitle font, size, color, bold, box
│   ├── Duration (s), Context reference, Ref frame extract
│   └── Seed + control_after_generate
└── Preview panel (expandable)
```

- **▼/▶**: Collapse/expand clip
- **CLIP N**: Clip number
- **name**: Optional clip name
- **🎨**: Color tag for visual grouping
- **▶/⏸**: Render toggle (generate on/off)
- **替换 / Replace**: Regenerate this clip only
- **状态 / Badge**: Render status (Ready/Rendering/Done)
- **↻**: Refresh — re-sync from external source
- **✕**: Delete this clip (minimum 1 remains)

- **▼/▶**：折叠/展开
- **CLIP N**：片段编号
- **name**：可选片段名称
- **🎨**：颜色标签
- **▶/⏸**：渲染开关
- **替换**：仅重新生成此CLIP
- **状态**：渲染状态
- **↻**：刷新——从外部源重新同步
- **✕**：删除此CLIP（至少保留1个）

---

## Output Mode | 输出模式

The `output_mode` dropdown controls what video files are saved to the output folder after each run.

`output_mode` 下拉菜单控制每次运行后保存哪些视频文件到输出目录。

| Mode | Description | 说明 |
|------|-------------|------|
| **none** | Cache only, no direct video output. Use downstream Final Decode node for output. | 仅缓存，不直接输出视频。通过下游 Final Decode 节点输出。 |
| **per_clip** | Save each clip as a separate MP4 file. | 每个CLIP单独保存为一个MP4文件。 |
| **merged** | Save all clips merged into a single MP4 file. | 所有CLIP合并为一个MP4文件输出。 |
| **both** | Save both per-clip MP4s and the merged MP4. | 同时输出单CLIP视频和合并视频。 |

File prefix is controlled by the `filename_prefix` widget.

文件前缀由 `filename_prefix` 控件设置。

---

## Technical Details | 技术细节

- **Extension Name**: `BSAIMiniMaxH3.Extender` (unique prefix avoids conflicts)
- **Category**: `BSAI/H3 Film Factory`
- **Node Class**: `BSAIH3FilmFactory`
- **Node Display**: `BSAI ComfyUI H3 Film Factory`
- **Note**: The node type `BSAIH3FilmFactory` is independent from the original `MiniMaxH3Extender` plugin — both can coexist without conflict
- **Overlay Technique**: Transparent textarea (caret visible) + visible overlay div (text + inline thumbnails), scroll-synced
- **Auto-Sync Timing**: 800ms polling + 5 retries at 100/500/1200/2500/4000ms on page load
- **Storyboard Parser**: Regex `/\[(?:分镜|Shot|shot|SHOT)\s*\d+\]/` for segment detection; `/\d+-\d+秒/` for duration extraction

- **扩展名**：`BSAIMiniMaxH3.Extender`（唯一前缀，避免冲突）
- **类别**：`BSAI/H3 Film Factory`
- **节点类**：`BSAIH3FilmFactory`
- **节点显示名**：`BSAI ComfyUI H3 Film Factory`
- **注意**：节点类型 `BSAIH3FilmFactory` 与原始 `MiniMaxH3Extender` 插件完全独立，两者可共存不冲突
- **覆盖层技术**：透明textarea（光标可见）+ 可见overlay div（文本+内联缩略图），滚动同步
- **自动同步时机**：800ms轮询 + 页面加载时5次重试（100/500/1200/2500/4000ms）
- **分镜解析器**：正则 `/\[(?:分镜|Shot|shot|SHOT)\s*\d+\]/` 检测分镜段；`/\d+-\d+秒/` 提取时长

---

## Changelog | 更新日志

### v1.3 — Independent Final Decode Node & Conflict Resolution

**What's New | 更新内容:**

1. **Independent Final Decode Node** — Added `BSAIH3FilmFactoryFinalDecode` (display name: "BSAI H3 Final Decode & Export"), a standalone final decode node that uses our plugin's own cache directory. This eliminates conflicts with the original `MiniMaxH3MotionContextDiskFinalDecode` node when both plugins are installed.

2. **Extension Name Unification** — Renamed all JS extension names to use the `BSAIMiniMaxH3.*` prefix for consistency:
   - `BSAIMiniMaxH3.Extender` — main extender extension
   - `BSAIMiniMaxH3.MotionContext.LivePreview` — live preview player
   - `BSAIMiniMaxH3.PromptPackBridge.DynamicInputs` — prompt bridge
   
   This prevents extension name conflicts with the original MiniMax H3 Extender plugin, which could cause custom widgets (video player, etc.) to fail loading.

3. **Dual Node Support** — The `live_preview.js` and `extender.js` now support both Final Decode node types via `ALL_FINAL_TARGETS`:
   - `MiniMaxH3MotionContextDiskFinalDecode` (original, backward compatible)
   - `BSAIH3FilmFactoryFinalDecode` (new, BSAI-specific)

4. **Updated Example Workflow** — `BSAI_H3_Film_Factory_v1.3.json` uses the new `BSAIH3FilmFactoryFinalDecode` node.

5. **Project Export/Import** — Project files now export using `BSAI_FINAL_TARGET` (`BSAIH3FilmFactoryFinalDecode`), ensuring projects use the BSAI version of the Final Decode node.

**Bug Fixes | 修复:**
- Fixed blank node issue caused by extension name conflicts when both BSAI Film Factory and the original MiniMax H3 Extender are installed
- Fixed `connectedFinalDecode` function to recognize both Final Decode node types

1. **独立的 Final Decode 节点** — 新增 `BSAIH3FilmFactoryFinalDecode`（显示名："BSAI H3 Final Decode & Export"），使用本插件独立的缓存目录。当两个插件同时安装时，彻底消除与原始 `MiniMaxH3MotionContextDiskFinalDecode` 节点的冲突。

2. **扩展名称统一** — 将所有 JS 扩展名称统一为 `BSAIMiniMaxH3.*` 前缀：
   - `BSAIMiniMaxH3.Extender` — 主扩展
   - `BSAIMiniMaxH3.MotionContext.LivePreview` — 实时预览播放器
   - `BSAIMiniMaxH3.PromptPackBridge.DynamicInputs` — 提示词桥接
   
   这避免了与原始 MiniMax H3 Extender 插件的扩展名称冲突，该冲突可能导致自定义组件（视频播放器等）无法加载。

3. **双节点支持** — `live_preview.js` 和 `extender.js` 现在通过 `ALL_FINAL_TARGETS` 同时支持两种 Final Decode 节点类型：
   - `MiniMaxH3MotionContextDiskFinalDecode`（原始，向后兼容）
   - `BSAIH3FilmFactoryFinalDecode`（新增，BSAI专用）

4. **更新示例工作流** — `BSAI_H3_Film_Factory_v1.3.json` 使用新的 `BSAIH3FilmFactoryFinalDecode` 节点。

5. **项目导出/导入** — 项目文件现在使用 `BSAI_FINAL_TARGET`（`BSAIH3FilmFactoryFinalDecode`）导出，确保项目使用 BSAI 版本的 Final Decode 节点。

**问题修复:**
- 修复了当同时安装 BSAI Film Factory 和原始 MiniMax H3 Extender 时，因扩展名称冲突导致节点空白的问题
- 修复 `connectedFinalDecode` 函数以识别两种 Final Decode 节点类型

---

## Dependencies | 依赖

```
torch
torchaudio
imageio-ffmpeg
numpy
Pillow
```

---

## Repository | 仓库

[github.com/xm6018924/BSAI-ComfyUI-H3-Film-Factory](https://github.com/xm6018924/BSAI-ComfyUI-H3-Film-Factory)

## License | 许可证

MIT
