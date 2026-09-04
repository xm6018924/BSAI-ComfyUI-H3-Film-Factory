# BSAI ComfyUI H3 Film Factory

**BSAI 电影工厂 — MiniMax H3 全自动电影短片生成工具包**

A complete AI filmmaking toolkit for [MiniMax H3](https://www.minimax.io/blog/minimax-h3) workflows in ComfyUI. From script to screen — storyboard-driven clip generation, asset library, inline thumbnails, auto-subtitle extraction, face repair, and HD upscaling.

一个为 ComfyUI 中 [MiniMax H3](https://www.minimax.io/blog/minimax-h3) 工作流打造的全流程影视制作工具包。从剧本到成片——分镜驱动片段生成、资产库、内联缩略图、自动字幕提取、人脸修复、高清放大。

## 2026-09-04 修复：单独选择 CLIP 生成严格从所选 CLIP 开始（不静默补前置）
> **v1.15 新增**

### 问题
- 选中 CLIP3 单独生成，若磁盘 latent 链为空，v1.14 会**静默从 CLIP1 连续渲染**补全链 —— 用户预期从 CLIP3 开始，结果浪费大量时间从头渲染。

### v1.15 修复
- **撤销静默链扩展 / 强制补前置**逻辑。
- **缓存完整时**：单独选择 CLIPn 严格**从 CLIPn 开始**连续渲染到结束（clipn、clipn+1…），符合预期。
- **缓存缺失时**：明确报错提示 前置 latent 链缺失（磁盘仅 X 段，不足 N 段），请先「全量渲染」一次建立完整缓存，**不再静默从头渲染**。
- 全量渲染不受影响（缓存空时从 CLIP1 正常建立）。
- 保留 previous_proxy=None 防御性跳过 motion context（不崩）。

### 为什么必须这样
MiniMax H3 的链式生成依赖前置 CLIP 的 latent 做 motion context，磁盘缓存缺失时物理上无法单独从中间段开始。因此单独生成某 CLIP 前，请先全量渲染一次建立缓存；之后单独选择任意 CLIP 都能从该 CLIP 开始。

---
## 2026-09-04 修复：单独选择生成遇到空缓存链不再报错（previous cached latent unavailable）
> **v1.14 新增**

### 问题
- 磁盘 latent 链为空（或前置段缺失）时，单独选择生成某个 CLIP（如单选 clip3），主循环对未选中的前置段走缓存跳过，却因无缓存未建立前段 latent，采样时抛错 MiniMax H3 Extender: previous cached latent is unavailable。

### v1.14 修复
- **链完整性检查**：运行前读取磁盘 manifest，若部分选择但磁盘段数不足（前置段缺失），自动把选择范围扩展为**从最早缺失段起连续渲染到结束**，保证 latent 链完整、不报错。
- **need_fill 兜底**：主循环中若前段 latent 缺失（previous_proxy / previous_handle 为空），强制渲染该段（即使未被选中），保持链完整。
- **防御性容错**：previous_proxy 为 None 时不再 raise，跳过该段 motion context（从当前段独立渲染），链拼接由 disk_join 的 previous_cache 保证。
- 链完整性扩展后仍**不自动合并**（保持用户部分选择意图，输出 per-clip，由用户手动「合并输出」）。

---
## 2026-09-04 修复：暂停不再自动继续 + 单独生成/暂停后禁止自动合并
> **v1.13 新增**

### 问题
- 点「⏸ 暂停」后，暂停等待超时会**自动继续**渲染剩余 CLIP，最终仍自动合并输出 —— 用户感觉暂停无效。
- 单独选择生成（clip_select 单选 / ↻ 重渲染）后，即使只生成部分 CLIP，输出阶段仍会**自动合并**所有已解码 CLIP 生成 merged.mp4。

### v1.13 修复
- **暂停超时无干预 → 停止后续渲染**（不再自动继续），保留已生成的 CLIP，状态提示可点「合并输出」或重新运行。
- **单独选择生成 / ↻ 重渲染 / 暂停停止后 → 禁止自动合并输出**：只输出独立的 per-clip 片段（clip01.mp4、clip02.mp4…），**不再自动生成 merged.mp4**；由用户手动点「合并输出」按钮合成完整视频。
- 仅「全量渲染且未干预」才自动合成 merged.mp4。
- 暂停/继续/终止/仅当前 按钮任何时刻可用（常驻显示）。

### 行为矩阵
| 操作 | 渲染行为 | 自动合并 |
|---|---|---|
| 全量渲染 | 全部 CLIP | ✅ 合并 |
| 单选 clipN 生成 | 从 clipN 连续渲染到结束 | ❌ 不合并（手动合并输出） |
| ↻ 重渲染 clipN | 从 clipN 连续渲染到结束 | ❌ 不合并（手动合并输出） |
| 点暂停后超时/停止 | 停止后续渲染 | ❌ 不合并（保留已生成） |

---
## 2026-09-04 修复：重渲染单CLIP不再自动合并，改为连续渲染到结束
> **v1.12 新增**

### 问题
- 单独选择重渲染 clip2 生成后，代码自动恢复旧尾部 latent 并自动合并输出（saved tail → auto-restore → merge auto-triggered），而不是继续生成下一个 CLIP。

### v1.12 修复
- **重渲染单个/多个 CLIP 后，不再保存/截断尾部、不再自动合并**。
- 改为：**从最早选中段(first_sel)起自动连续渲染到结束**（依次生成 clip2、3、4…），与 v1.11 单选语义一致。
- 只有以下情况才执行合并：① 用户手动点击「⏸ 暂停 / ⏹ 停止」；② 用户手动点击「合并输出」按钮（merge_output 分支保留原样）。
- 示例：重渲染 clip2 → clip1 走缓存，clip2~6 依次连续重新采样生成，最后正常输出完整视频（不自动合并）。

---
## 2026-09-04 修复：clip_select 单选改为连续渲染（不自动合并）
> **v1.11 新增**

### 单选语义修正
- 之前：clip_select = 2 只渲染第 2 段，其余保留缓存，随后与已有 CLIP 合并输出（不符合预期）。
- **v1.11 起**：单选（如 2）= **从第 2 段起自动连续渲染到结束**（依次生成 2、3、4…），中途**不执行合并**。
- 只有以下情况才执行合并：① 用户手动点击「⏸ 暂停 / ⏹ 停止」；② 用户手动点击「合并输出」按钮。
- 多选/范围（2-5、1,3、1,3-5）仍保留「仅渲染指定段」语义；ll 为全部渲染。
- 状态栏显示连续范围（如 clip_select {2-6}）。

---
## 2026-09-04 按钮控制：暂停 / 继续 / 终止 任何时候可用
> **v1.10 新增**

### 三个按钮任何时候都有效
- **工具栏常驻**：⏸ 暂停 / ▶ 继续 / ⏹ 停止 / ✖ 中止 四个按钮现在**始终显示在工具栏**（不再依赖渲染状态隐藏）。
- **任意时刻点击都有效**：
  - **⏸ 暂停**：渲染中任意时刻点击 → 当前 CLIP 生成完、下一个开始前等待；pause_enable=True 时每个 CLIP 后自动暂停。
  - **▶ 继续**：暂停中点击立即继续渲染。
  - **⏹ 停止（仅当前/停止）**：渲染中点击 → 当前 CLIP 完、保留已生成，停止后续。
  - **✖ 中止**：**立即中断当前采样**（不等当前 CLIP 跑完），整个渲染中止，已生成的 CLIP 保留。
- 渲染空闲时点击任一按钮：后端返回「当前无渲染进行」友好提示（不再报错）。

---
---

## 2026-09-04 修复：暂停键始终可见可用
> **v1.9 新增**

### 暂停键在哪？现在渲染时始终显示在工具栏
- 之前 `pause_enable` 默认关闭会把暂停条隐藏，导致看不到「⏸ 暂停」键。
- v1.9 起：**只要开始渲染，工具栏即显示「⏸ 暂停」按钮**，无需先开任何开关。
- 点击暂停 → 当前 CLIP 生成完、下一个开始前等待，弹出「▶ 继续 / ⏹ 仅当前/停止 / ✖ 中止」；无干预则超时自动继续。

### `pause_enable` 语义更新（可选增强）
- `pause_enable=False`（默认）：手动点「暂停」才暂停（随时可用）。
- `pause_enable=True`：每个 CLIP 生成完**自动暂停等待**确认，更细粒度控制。
- `pause_timeout`：无干预自动继续的等待秒数（默认 120）。

### CLIP 选择生成说明
- `clip_select_enable` + `clip_select`（如 `2`）= 仅渲染选中的 CLIP，其他保留缓存。单选即只生成该段；要连续多段请用 `1,3` / `2-5` / `all`。
- 渲染过程中随时可用「⏸ 暂停」控制节奏。

---

## 2026-09-04 加速升级：SageAttention + Ref2VA 磁盘缓存 + CacheDiT 引擎
> **v1.8 新增（全球最新 H3 加速技术落地，三管齐下）**

### 1. 启动级：SageAttention（RTX 5090 Blackwell 原生加速）
- 启动参数从 `--use-pytorch-cross-attention` 切换为 **`--use-sage-attention`**（`BSAI-...-8185.bat` 已改，备份 `.bak` 可回退）。
- 本机已装 `sageattention` 库，ComfyUI 0.34 原生接入；H3 这类大 DiT 的 attention 是主要计算量，SageAttention 实测显著提速（参考 MiniMax H3 官方加速实验）。
- **需重启 ComfyUI 生效**。若个别模型兼容异常，日志会提示并回退 pytorch attention，不影响出片。

### 2. 节点级：Ref2VA 参考图编码磁盘缓存（CLIPCached 同款，2026.09 最新技术）
- 新增 **`ref_cache`** 开关（默认开）。参考图（6 张 1088×1920 级别）的 VAE 编码结果按"参考图内容哈希 + 输出尺寸 + ref_image_size"磁盘缓存。
- **调提示词 / 换种子 / 重跑同一分镜序列时，跳过每次重复的参考图 VAE 编码**，只重编音频引用；参考图变化自动失效重建。
- 缓存目录：`ComfyUI/user/.../_ref2va_cache/`，单键 `<hash>.pt`，无需手动清理。

### 3. 节点级：CacheDiT 步间缓存引擎（ComfyUI-CacheDiT，H3 约 1.41–1.50x）
- 新增 **`cache_dit`** 开关（默认关，需已安装 `ComfyUI-CacheDiT` 插件——本机已装并装好 `cache-dit` 库）。
- 开启后自动对采样模型应用 DiT 步间残差缓存（MiniMax-H3 预设 Auto 检测），与 Block Cache 互斥（优先 CacheDiT）。
- 未安装插件时自动静默回退，不影响出片。

### 4. 推荐加速组合（按需选择）
| 场景 | 配置 |
|---|---|
| 最快 | `cache_dit=开` + `steps=4` + euler/simple + `ref_cache=开` |
| 兼容稳妥 | `block_cache=开` + `cache_dit=关` + `ref_cache=开` |
| 质量优先 | 关 cache，`steps=8~20` + PDD-Acc 官方 8 步 LoRA |

---

## 2026-09-04 升级：CLIP 自定义选择生成 + 暂停渲染
> **v1.7 新增（对应工作流：`example_workflows/BSAI_H3_ClipSelect_Pause_示例工作流.json`）**

### 1. CLIP 自定义选择生成（单选 / 多选 / 全选）
`BSAIH3FilmFactory` 新增 **`clip_select_enable`**（开关，默认关）与 **`clip_select`**（选择串，默认 `all`）。
- `clip_select_enable` 开启后，仅渲染 `clip_select` 指定的 CLIP，**未选中的保留缓存、不重新生成**；
- `clip_select` 支持格式：`all`=全部；`1`=单个；`1,3`=多选；`2-5`=区间；`1,3-5`=混合（数字从 1 起）；
- 与卡片勾选（render_enabled）叠加：两者任一为「不渲染」即跳过该 CLIP；
- 渲染状态栏会显示 `clip_select {…}` 标明本次实际渲染范围。

### 2. 暂停渲染（CLIP 间暂停 / 继续 / 仅当前 / 中止，无干预自动继续）
新增 **`pause_enable`**（开关，默认关）与 **`pause_timeout`**（暂停后无干预自动继续秒数，默认 120）。
- 开启后，每个 CLIP 生成完成、**即将开始下一个之前**可暂停：前端工具栏出现「⏸ 暂停」按钮；
- 点击暂停后进入暂停态，显示三个操作：
  - **▶ 继续**：接着渲染剩余 CLIP；
  - **⏹ 仅当前/停止**：停止后续渲染，仅保留已生成的 CLIP（可直接点「合并输出」合成视频）；
  - **✖ 中止**：中止整个渲染；
- 暂停期间**用户无干预则超时自动继续**（`pause_timeout` 秒），无需守候；
- 后端新增路由 `POST /h3_extender/render_control`（action: pause / resume / stop_after / abort），前端 WebSocket
  事件 `h3_extender_progress` 增加 `paused / resumed / stopped / aborted` 相位驱动按钮状态。

---
## 2026-09 升级：Block-Cache 加速 + AV 即时输出 + 3D Latent 分块超清
> **v1.6 新增（对应工作流：`example_workflows/BSAI_H3_3DLatentUpscale_示例工作流.json`）**

### 1. Block-Cache 加速（主节点内置）
`BSAIH3FilmFactory` 新增 `block_cache` 开关（默认关），开启后复用已安装的
`comfyui-minimax-h3-blockcache-T8` 插件，以 F1B0 残差缓存跨 CLIP 复用——
画面稳定的顺序 CLIP 可跳过大部分 DiT 块，**显著提速**（参考 SageAttention 类加速思路，
本方案不依赖额外模型下载，本机已装即可用）。
- `block_cache_threshold`：命中阈值，越高越易命中、提速越多（默认 0.12）
- `block_cache_device`：缓存设备，cpu 省显存 / gpu 减传输
- 依赖未安装时自动静默回退，不影响原有生成

### 2. 逐 CLIP 即时输出 image / audio 端口
`BSAIH3FilmFactory` 新增 **`output_image_audio`**（默认开）与两个新输出端口
**`images`(IMAGE) / `audios`(AUDIO)**（共 9 个输出）。
每个 CLIP 采样完成后**立即**解码并推送到这两个端口（同时经 WebSocket
`h3_extender_clip_av` 事件实时流式），无需等全片生成——可直接把 IMAGE 接超分放大节点、
AUDIO 接音频后处理，实现流水线式并行消费。全片完成后端口输出全部帧/音频。

### 3. BSAI H3 3D Latent 分块超清（新节点）
新增 `BSAI_H3_3DLatentUpscale`：在**潜空间**内做 3D 分块高清放大，参考
[MMH3 Ultimate Upscale](https://github.com/bbaudio-2025/Comfyui-MMH3-UltimateUpscale) /
[MiniMax H3 Latent Split](https://github.com/bbaudio-2025/Comfyui-MiniMax-H3-LatentSplit) 方案。

- **时间分块**：长片段按 H3 keyframe 网格切成重叠时间块（`chunk_length`/`temporal_overlap`，17 倍数），
  每块独立处理，峰值显存与全片长度无关
- **3D Latent 放大**：`minimax_h3_latent_upscaler_3d_*.safetensors`（放
  `models/latent_upscale_models/`，可于 https://huggingface.co/LBH-123-AI/Minimax_h3_latent_Upscaler 下载，
  国内用 hf-mirror.com 镜像），或 `interpolate` 无模型插值
- **空间分块二采**：每时间块再切重叠 tile 逐块 re-sample（`tile_size`/`spatial_overlap`），
  显存峰值 = 单 tile；**低配显卡也能跑高清**（8G 卡 tile 320-384 / chunk 34-68，12G 卡 384-512，16G 卡 512-576）
- **锚定 + 交叉淡化缝合**：块间重叠区线性混合，时间/空间接缝平滑
- **音频原样携带**：音频 latent 只裁剪拼接、从不重采样
- 输出 `latent`（放大后 AV latent）+ `images` + `audios` + `status`

> ⚠️ 二采（`resample_second_pass`）需要 `model` + `conditioning`（接你生成时所用的 H3 提示词/参考图编码）；
> 不接则自动跳过二采、仅做 3D Latent 放大。



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
4. Load example workflow from `example_workflows/BSAI_H3_Film_Factory_v1.5.json`

1. 克隆或下载到 `ComfyUI/custom_nodes/BSAI-ComfyUI-H3-Film-Factory/`
2. 安装依赖：`pip install -r requirements.txt`
3. 重启 ComfyUI
4. 从 `example_workflows/BSAI_H3_Film_Factory_v1.5.json` 加载示例工作流

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
Drag `example_workflows/BSAI_H3_Film_Factory_v1.5.json` into ComfyUI.

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

### v1.6 — Cache Token & Single-CLIP Render Fix

**Bug Fixes | 问题修复:**

1. **Fixed: Final Decode outputs stale results on second run** — Added `run_token` field (based on manifest `updated_at`) to the cache handle. Previously, the cache handle dict was identical between runs (same `data_path`, `manifest_path`, `next_index`), causing ComfyUI's execution cache to skip the Final Decode node and reuse the first run's output. The `run_token` changes whenever the manifest is modified, forcing ComfyUI to re-execute the Final Decode node every time.

2. **Fixed: Single-CLIP render button triggers all CLIPs** — The green ▶ button now sets `render_enabled=false` on all other clips, ensuring only the selected CLIP is generated even if the queue runs multiple times. The `setTimeout` that reset `replace_mode` after 1 second has been removed (cleanup is handled by `onExecuted`). Backend logic updated to skip `render_enabled=false` clips regardless of `validated` state.

1. **修复：第二次运行时 Final Decode 输出第一次的合并结果** — 在缓存句柄中添加 `run_token` 字段（基于 manifest 的 `updated_at`）。此前两次运行的缓存句柄字典完全相同（`data_path`、`manifest_path`、`next_index` 一致），导致 ComfyUI 执行缓存认为 Final Decode 节点输入未变化而跳过执行，复用第一次的输出。`run_token` 在每次 manifest 修改时都会变化，强制 ComfyUI 每次都重新执行 Final Decode 节点。

2. **修复：单独渲染CLIP按钮会触发全部CLIP生成** — 绿色 ▶ 按钮现在会将其他所有CLIP的 `render_enabled` 设为 `false`，确保即使队列多次执行也只生成选中的CLIP。移除了1秒后重置 `replace_mode` 的 `setTimeout`（清理由 `onExecuted` 回调处理）。后端逻辑更新为无论 `validated` 状态如何，`render_enabled=false` 的CLIP都会被跳过。

### v1.5 — Updated Example Workflow & Cleaned Example Directory

**What's New | 更新内容:**

1. **Updated Example Workflow to v1.5** — Replaced all example workflows with the latest `BSAI_H3_Film_Factory_v1.5.json` in `example_workflows/` directory.
2. **Cleaned Example Directory** — Removed all legacy workflow files and utility scripts from `example_workflows/`, keeping only the latest v1.5 workflow.
3. **Updated Documentation** — All README references now point to `example_workflows/BSAI_H3_Film_Factory_v1.5.json`.

1. **更新示例工作流至 v1.5** — 将 `example_workflows/` 目录中所有旧工作流替换为最新的 `BSAI_H3_Film_Factory_v1.5.json`。
2. **清理示例目录** — 移除 `example_workflows/` 中所有旧版工作流文件和工具脚本，仅保留最新 v1.5 工作流。
3. **更新文档** — README 中所有引用已更新为 `example_workflows/BSAI_H3_Film_Factory_v1.5.json`。

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
