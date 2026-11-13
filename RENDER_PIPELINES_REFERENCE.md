# BSAI-H3-Film-Factory 渲染管道 / 模式 / LoRA 搭配速查表

> 基于 `extender.py` v14.339 源码整理（2026-11-08；v14.322 起整理，新增第 33 档「视频替换」，v14.337 起该档改为人物区域掩码重绘；v14.339 新增第 34 档 HyperFlow H3 Flash 14B）。
> LoRA 一律挂在 H3 Loader 的标准 LoRA 槽，强度按各档推荐。

---

## 一、一镜到底模式（one_shot_mode）

| 选项 | 作用 | 适用 |
|---|---|---|
| **off (storyboard)** | 分镜剪辑模式，每段独立生成，段间 xfade 转场拼接 | 多镜头 MV、广告、有明确切镜的片子 |
| **on (one-shot)** | ①每段自动注入"连续单镜头"指令；②段间强制 motion context 锚定（上段尾 latent 引导下段）；③段间改无缝 concat（零转场） | 一镜到底长镜头、30s+ 连续跟拍 |

### on 时的采样档（one_shot_sampling）

| 档 | 一采+二采 | 接缝漂移 | 配套 |
|---|---|---|---|
| **Single-pass seamless（推荐）** | 一采N步，跳过二采 | 零漂移（链 latent 不被重绘） | turbo 8步 LoRA + beta scheduler + 6~8步 |
| **Dual-pass HD (seam risk)** | 保留二采放大，可达2K | 有像素漂移（模糊/抖动） | 只在需要 HD 放大时用 |
| **Dual-pass seamless (8+4)** | 8一采 + 4二采，denoise 0.45 | 已修双采接缝锚点 | 常规一镜到底 |
| **Dual-pass seamless 2K (8+4)** | 同上 + 强制输出宽2560（1280→x2.0 / 1920→x1.33） | 已修 | 直出2K成片 |

---

## 二、速度档（speed_preset）

| 档 | 一采+二采 | denoise | 单段耗时 | 说明 |
|---|---|---|---|---|
| **custom** | 手填 | 手填 | — | 默认，用下方滑块值 |
| **Turbo** | 4+3 | 0.5 | ~20min | 快速预览 |
| **Balanced** | 6+4 | 0.5 | ~28min | 日常出片 |
| **Fine** | 8+6 | 0.5 | ~40min | 高质量 |
| Turbo-VDN / Balanced-VDN / Fine-VDN | 同左 | — | — | 配 VDN 工作流专用 |

> **注意**：选了 render_pipeline 配方档后 speed_preset 自动变 custom，两源互斥不叠加。

---

## 三、渲染管道（render_pipeline）全 40 档

### A. 默认/通用

| # | 管道 | 一采+二采 | sampler / shift | 推荐 LoRA 与基模 | 适用 |
|---|---|---|---|---|---|
| 1 | **Sol-H3 Self-Lift Dual-Pass（默认）** | 自定义 | 默认 shift 12/3 | 不强制 LoRA；SelfLift TST 默认开(tau 0.2) | 日常通用、HD refine |
| 2 | **MV Dual-Pass（电影工厂v3.2原版）** | 自定义 | 默认 | 无 | 老工作流兼容 |

### B. 直播带货 / 对口型

| # | 管道 | 一采+二采 | 关键参数 | 配套 | 适用 |
|---|---|---|---|---|---|
| 3 | **Live Dub HD** | 12+4 | audio redraw 0.7 | 需非8步蒸馏模型 `minimax_h3_ref2va_int8_convrot` | ref_audio 配音 |
| 13 | **Live Commerce 01 Text Dubbing** | 12+4 | 同上 | 不接任何音频口，模型默认声读台词 | 纯文本配音 |
| 14 | **Live Commerce 02 ref_audio** | 12+4 | 同上 | 声音跟随 ref_audio | 音色参考 |
| 15 | **Live Commerce 03 lip_voice** | 12+4 | 同上 | 模型不生成音频，lip_voice 驱动对口型 | TTS 对口型 |
| 16 | **Live Commerce（全自动）** | 12+4 | denoise 0.55，3D latent x2.0，audio redraw 0.7，shift 12/3，TST 0.2，tiled 4x128，clip2起关 motion context | 一键档 | 直播带货成片 |

### C. 加速蒸馏（LoRA 配方）

| # | 管道 | NFE | sampler / shift | 推荐 LoRA（文件名） | 适用 |
|---|---|---|---|---|---|
| 5 | **FastH3 4-step VSA** | 4+2=6 | 默认 | 4步蒸馏 + VSA LoRA | 快速预览 |
| 6 | **Turbo-v4** | 6+4 | shift 12/3 | `minimax_h3_turbo_v4_step600`(0.5~0.8) + `MysticXXX_MMH3-V4`(0.3~0.5 去油光) | 日常加速 |
| 7 | **DMAD 4-step** | 4+2=6 | 强制 lcm，shift 12/2 | DMAD 4步蒸馏 LoRA | 动作镜头 |
| 8 | **Action Combo** | 8+4 | euler | action/DMAD LoRA 由 H3LoraStack 注入 | 动作片 |
| 18 | **H25 Hybrid 8-step Multi-Ref** | 8单采 | euler+simple，shift 12/3 | `minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16`(1.0)；基模 FL2VA + Ref2VA 叠加(b25-49) | 多参考图 |
| 26 | **PDMD 4-step SelfLift Dual-Pass** | 4+2=6 | shift 12/3 | `minimax_h3_pdmd_4step_lora_avg_rank_57_bf16`（Kijai/MiniMax-H3-experimental） | 少步高质量 |
| 27 | **PDMD 2-step Turbo Draft** | 2单采 | 默认 | `minimax_h3_pdmd_2step_lora_avg_rank_38_bf16` | **仅草稿，不出成片** |
| 28 | **PTD 4-step Ref2VA** | 4单采 | 默认 | per-hop Ref2VA 加速 LoRA；需 Ref2VA 基模 | 参考图加速 |
| 29 | **PIKA H3 Flex 6+2** | 6单采（refine跳过） | 强制 lcm，ManualSigmas knots 1000/750/500/250/100/40，shift 12/3，cfg 1.0 | `pika_h3_flex_ref2va_v1_bf16`(1.0，**禁叠第二个加速LoRA**)；基模 hybrid b25-49 | 直出1080p(960x544 latent→VAE原生1920x1088) |
| 30 | **TaoMate HD 3-Step Progressive** | 2+1=3 | euler+simple，cfg 1.0，shift 12/3 | `TaoMate-HD-preview-comfy.safetensors`(1.0，**禁叠第二个加速LoRA**)；节点 slmonker/ComfyUI-TaoMateHD | 1080p直出，0.625x低采→bislerp x1.6→1步精修 |
| 31 | **TaoMate HD 8+4 Progressive** | 8+4=12 | euler+simple，cfg 1.0，shift 12/3；二采 denoise 0.45，latent x2.0，3D latent upscaler，tiled 16x128 | `TaoMate-HD-preview-comfy.safetensors`(1.0，**禁叠第二个加速LoRA**)；节点 slmonker/ComfyUI-TaoMateHD | 1080p直出画质版，半分辨率一采8步→3D latent x2.0→4步精修 |
| 32 | **SingularityV2+Pika H3 8步 高动态长视频** | 8+3=11 | euler+simple，cfg 1.0，shift 12/3；二采 denoise 0.40，latent x2.0，3D upscaler，tiled 4x128，音频锁定 | 基模 `Minimax-h3_Singularity_ref2va_v2_int8`（链式一镜到底可留 hybrid b25-49）；加速 LoRA `pika_h3_flex_turbo_8step_hd_ref2va`(1.0，style 0.6 已烘焙) 或 `minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16`；动作 LoRA **三选一** `Motion_Repair_V2` / `H3_Fight_Flow_V1` / `H3_Combat_V2` | 高动态动作 + 27s/30s 导演台长视频（BV1y8446DExi） |

### D. 分辨率/画质档

| # | 管道 | 目标分辨率 | 关键参数 | 配套 | 适用 |
|---|---|---|---|---|---|
| 9 | **4K Direct Secret Sauce** | 4K | 6步低采+x2 boost + 3步细节+DLSS5像素超分 | `minimax_h3_turbo_v4_step600`(0.5~0.8)+`MysticXXX_MMH3-V4`(0.3~0.5) | 4K成片，修高光过曝 |
| 11 | **Dual-Pass 2K (HyperVAE 2x)** | 2K | 8+4，latent factor 1.0（refine快4x） | VAE: `models/vae/hyper*2x*.safetensors` | 2K快速出片 |
| 19 | **4K Regenerate OpenH3Regenerate2K** | 2560x1440 | 768P草稿(1344x768, 4步)→latent x1.9(aligned 32)→3步重生成，**二采 sigmas 固定注入官方 [0.909375, 0.857143, 0.666667, 0]**，euler，CFG off | 合并LoRA: OpenH3 Refiner 5000步(0.7)+fl2v turbo(1.0)+lms sharp(1.0)；**许可不含EU/UK/KR/US** | 768P 草稿直出 2K |
| 24 | **Director Turbo Dual-Pass** | 1920x1088 | 8步低采(0.4MP=864x480)+4步refine(latent x2.0, denoise 0.45) | refine_sampler=euler；二采跟随 Director 控制视频而非 ref2va | 导演分镜控制 |
| 25 | **Dual-Pass 2K (official condition upscale)** | 2K | 8+4，denoise 0.45，euler，shift 12/3 | 官方 MiniMaxH3LatentUpscaleCombined，ref2va condition 同步放大 | 官方路径2K |

### E. 模型/架构专用

| # | 管道 | 关键参数 | 基模/配套 | 适用 |
|---|---|---|---|---|
| 4 | **FastH3-Trim** | 8+4 | nvfp4 剪枝模型 | 省显存 |
| 10 | **FastH3 Omni 8-step Single-Pass** | 8步单采，guidance 1.0，shift 12/3 | `fasth3_omniref_8step_pruned_int8_convrot` + BlockSparseAttention VSA keep_percent=10 | 极速单采 |
| 12 | **QAD-v2 8-step** | 8步单采，shift 10/3，refine跳过 | QAD-v2 NVFP4 全套（118GB→30GB） | 量化省显存 |
| 17 | **FastH3 Omni x SelfLift Upscale** | 4步(0.4x骨架)+3D latent放大+4步refine=8NFE | Omni 8步蒸馏 + SelfLift 渐进放大 | 蒸馏+放大组合 |
| 20 | **PRISM 10-step Motion** | euler+simple 10步，无LoRA | Singularity v2 x 10Eros-Max 合并模型 | 运动表现 |
| 21 | **Transparent Video Single-Pass Keying** | 10步单采，refine跳过 | 纯色背景(绿/蓝/黑)；配 BSAI_H3_TransparentKey + BSAI_H3_SaveTransparentVideo | 抠像/透明视频 |
| 22 | **4-in-1 Ultimate Speedup** | 6+2，latent x2.0 | DMAD 4步LoRA + SegAttention 2.2.0 + 半分辨率参考输入 + SelfLift 双采 | 极限加速 |
| 23 | **SolarRenderer Structure Control** | 4+4=8NFE，ref_image_size强制max | 控制LoRA(逐帧读3D灰盒/法线/姿态/深度) + 4步LoRA(强度~0.8)；基模 FastH3-Omni/Singularity V2 | 结构控制 |

### F. 视频人物替换 / Video Recast (V2V character swap · v14.335，v14.337 改为人物区域掩码）

| # | 管道 | 一采+二采 | 关键参数 | 配套 | 适用 |
|---|---|---|---|---|---|
| 33 | **视频替换 (V2V 人物替换)**<br>`Video Recast (H3 V2V character swap)` | 8 步单采（**refine 强制关**） | euler + simple，shift 12/3；denoise 0.72（用户显式改过 widget 则用用户值并夹到 0.35~0.95）；`noise_mask` = 视频**人物区域掩码**（人区 1 重绘 / 背景 0 锁死源像素，v14.337）/ 音频全 0 | 源视频放资产库 → `@视频N`；替换的人物参考图放资产库 → `@图N`；LoRA 槽建议 `minimax_h3_角色替换character_swap_v1.5.safetensors`(0.6~0.8，**该权重名尚未在本机目录核实，不可当既有事实引用**) | V2V 人物替换：保留源片机位/运动/构图/剪辑点/口型，只换人物身份 |

**链路**：源片段 → ffmpeg 精确 seek（`-ss` 在 `-i` 之后）抽 24fps、等比放大 + 居中裁切到画布、帧数对齐 17k+5 网格 → `vae.encode()` 得 `[1,24,T,h/16,w/16]`；源原声 → 重采样到 audio_vae 采样率、裁/补到 `round(dur*40)` 行 → `audio_vae.encode()` 得 `[1,32,2,Ta]`。两者装进 `NestedTensor` 作为一采初始化 latent：视频行按**人物掩码**放行重绘，音频行锁死（mask=0），所以替换后对白/环境声/口型与原视频逐帧对齐，**不需要另接 lip_audio**。

**人物掩码（v14.337，为什么必须有）**：早期版本视频 mask 全 1，等于整幅画面都允许重绘，denoise 0.65 下夜景街景被换成室内、衣服也沿用了源片 —— 实测出片正是这么坏的。现在逐帧向本机 NPU 服务取：`POST /detect_pose`（YOLO11-pose 人体框）+ `POST /segment_foreground`（RMBG-1.4 alpha，**JSON `{"image": <base64>}`，返回 `data:image/png;base64` 前缀需剥掉**），**GrabCut（框内初值）∪ RMBG alpha 后限制在人体框内**，去碎块 → 闭运算补洞 → 外扩 13px → 羽化 10px，按 17 帧步长取代表帧 `INTER_AREA` 下采样到 latent 网格（v14.338 起代表帧改由 `_RECAST_MASK_SAMPLES` 封顶默认 24 个，因实测 `vae.encode` 对 362 帧给出 **107** 个 latent 行，逐行打 NPU 太慢；每行取最近的已采样帧）。掩码语义见 `comfy/model_base.py::process_timestep` —— `denoise_mask * timestep → patchify`，0 表示该 token 不做去噪（保持源 latent）。掩码失败（NPU 掉线）才退回全 1 并告警。相关环境变量：`BSAI_H3_RECAST_SUBJECT_MASK=0` 关闭、`BSAI_H3_RECAST_MASK_DILATE`、`BSAI_H3_RECAST_MASK_FEATHER`、`BSAI_H3_RECAST_MASK_SAMPLES`、`BSAI_H3_RECAST_MASK_PORT`。

**分段（15s 契约）**：`n = ceil(源时长 / 15s)`（对齐 MiniMax H3 Recast 单镜头 ≤15s），每段时长 = 源时长 / n 并对齐帧网格。45s 源视频 → 3 段 × ≈15s，分镜不足自动补 CLIP（`id` 后缀 `_recast_k`，`context_enabled=False`），分镜多于所需则把多余段 `render_enabled=False` 跳过并打印说明。

**刻意不做的事（都是踩过的坑）**：
- 不跑二采：latent 放大会抹平源片细节，身份转移在二采会散掉；
- 不做段间 motion context 续链：每段必须各自被源视频对应片段驱动，否则会把"上段生成出来的画面"当上下文，越链越偏；
- 提示词里的 `<Video N>` 会被替换成"原视频"字样：源视频已经作为 V2V latent 进入采样，保留标签会让 H3 把它再当 ref2v 参考视频二次注入，动作被重演一遍；
- 忽略 `lip_audio_segments`：另灌一套音频行会与"锁定源原声"冲突。

### G. HyperFlow H3 Flash 14B（v14.339，Bilibili BV13oWJ6uEQZ）

| # | 管道 | 一采+二采 | 关键参数 | 配套 | 适用 |
|---|---|---|---|---|---|
| 34 | **HyperFlow H3 Flash 14B 单采 (4/6/8步 GGUF)**<br>`HyperFlow H3 Flash 14B Single-Pass (4/6/8-step GGUF)` | 4/6/8 步单采（**refine 强制关**） | euler + `hyperflow_manual` 固定 sigma（官方 4/6/8 曲线，flow shift 12 已烘焙，**不再注入 dual-track shift**）；CFG 1.0 单前向；denoise 1.0；无负面提示词；TST 关闭；跳过 H3 底座音频 12 步提步保护 | 权重 `minimax_h3_fl2va_hyperflow_flash_14b-Q4_K_M.gguf`(9.1GB) / `minimax_h3_ref2va_hyperflow_flash_14b-Q4_K_M.gguf`(9.2GB) → `models/diffusion_models/`；必须用 **HyperFlow GGUF Loader**（节点包 ComfyUI-GGUF + ComfyUI-HyperFlow-Flash）；全量 H3 的加速 LoRA **不兼容** | 低显存 24GB 级快速出片；官方默认 1344x768 / 124帧(5.2s) / 24fps / 32kHz 立体声；16GB 未实测 |

**官方固定 sigma（已乘 flow shift 12，取自 ComfyUI-HyperFlow-Flash/integrations/README.md，与 loader_nodes.py 的 RAW_SIGMAS 一致）**：
- 4 步：`1.0, 0.962575793, 0.755781889, 0.312497854, 0.0`
- 6 步：`1.0, 0.982655942, 0.914642572, 0.674755692, 0.385223746, 0.159055322, 0.0`
- 8 步：`1.0, 0.993909776, 0.9842875, 0.966063738, 0.923076928, 0.8349424, 0.696852028, 0.468753308, 0.0`

**权重选择**：纯文生/首帧/首尾帧 → `fl2va_gguf/`；参考图 Ref2VA（电影工厂 `@图N` 链路）→ `ref2va_gguf/`。二采在官方四套模板中均不存在，本档保持单采。

### H. 高低噪切分采样（v14.401，SplitSigmas 6+2）

| # | 管道 | 一采+二采 | 关键参数 | 配套 | 适用 |
|---|---|---|---|---|---|
| 40 | **BSAI6+2高低噪采样**<br>`BSAI 6+2 High/Low-Noise Split Sampling (beta 8-step split at 6, 3D latent upscale)` | 6+2=8（放大不计步） | **同一条** 8 步 beta 曲线（denoise 1）在 step=6 处 SplitSigmas 切开；两段都 euler + BasicGuider(CFG 1.0)；shift 12/3；二采起点 σ = 切点直送（不做 0.45~0.55 夹取）；二采前 3D latent x2.0 / align 32 / tiled 16x128 | 模型侧照参考工作流：hybrid b25-49 int8 基模 + `DMAD full_dareties_v4_step600` 类加速 LoRA(0.8) + Sol-Attn；权重名以本机目录为准 | 一采只跑到切点、二采续算低噪段的高/低噪分档路线 |

**参数出处**：用户参考工作流 `卡点舞蹈MV工作流_纯音乐版.json` 的采样段，逐节点核对过（节点号见 `extender.py` 该分支注释）：

| 工作流节点 | 值 | 在电影工厂里的等价物 |
|---|---|---|
| Int「一采步数」(600) | 6 | `steps`，同时 = SplitSigmas 切点 |
| Int「二采步数」(601) | 2 | `refine_steps` |
| MathExpression `a+b`(602) | 8 | 总步数（`_BSAI6P2_TOTAL_STEPS`） |
| BasicScheduler(507) | beta / steps=8 / denoise 1 | 一次算出的 8 步 beta 曲线 |
| SplitSigmas(604) | step=6 | `_bsai_6plus2_split()`：高噪 7 点(6 步) / 低噪 3 点(2 步) |
| SamplerCustomAdvanced(502/610) + KSamplerSelect(506/609) | euler ×2 | `sampler_name = euler` / `refine_sampler = euler` |
| BasicGuider(503/608) | CFG 1.0 单前向 | `_BasicGuider` |
| MinimaxH3LatentUpscaler3D(606) | `minimax_h3_latent_upscaler_3d_fp16` / target dimensions / align 32 | `refine_upscaler_model` + `refine_upscale_factor=2.0` + `refine_align_to=32` |

**实测切点 σ（`comfy.samplers.calculate_sigmas` + `ModelSamplingDiscreteFlow(shift=12)`，8 步 beta）**：

```
1.0  0.99499  0.98251  0.96074  0.92336  0.85529 | 0.72073  0.42491  0.0
└──────────── 高噪 6 步（一采）────────────┘   └── 低噪 2 步（二采）──┘
```

三点必须一起看，否则很容易"看着像、其实不是这条路"：

1. **一采不能按 steps=6 单独算 beta**。独立 6 步 beta 的 σ 是 `1.0 0.99173 0.96936 0.92336 0.82061 0.54871 0`，切点落在 0.5487 而不是 0.7207 —— 二采起点整体偏掉，等于换了一条调度曲线。本档因此用哨兵调度 `bsai6plus2_high` / `bsai6plus2_low`，两段都从**同一次** 8 步 beta 计算结果里切。
2. **二采不重加噪**。一采在 σ≈0.72 收工，输出 latent 本身就是 `σ·ε+(1-σ)·x0` 的半噪底；再按 CONST 口径加一次噪会叠到等效 σ≈0.92（`σ·ε+(1-σ)·x` 二次混合），2 步二采就成了从零重画。本档直接沿用一采噪声状态，只补一步 `inverse_noise_scaling`（`x -> x/(1-σ)`）抵掉采样器内部的 `(1-σ)` 缩放，净结果是原样喂入。
3. **内容锁 / 结构闸门对该档让位**。v14.389 的 0.45~0.55 denoise 夹取与 0.85 结构相似度闸门都是为"一采已跑完整条曲线到 σ=0"的常规双采设计的。本档一采的合法产物就是半噪 latent，拿它当闸门基准会把正确二采判成"换了画面"并回退到半噪底（比不跑二采更糟）。该档连续性由"同一曲线 + 切点 σ 直送"保证。

**已知偏差**：空间放大是对半噪 latent 做的（与参考工作流一致），放大会在噪声上引入轻微插值痕迹，由二采 2 步低噪段吸收；`refine_upscale_factor` 与 `refine_align_to` 可按目标分辨率调整，工作流里的 1280x704 + align 32 即 `x2.0 + align 32` 的实测组合。

---

## 四、全局关键开关

| 参数 | 默认 | 说明 |
|---|---|---|
| dual_track_shift | **on** | 官方双轨迹采样，视频/音频独立 shift，默认开 |
| shift_video | **12.0** | 视频流 shift（官方12，DMAD用12，QAD用10） |
| shift_audio | **3.0** | 音频流 shift（官方3，DMAD用2） |
| selflift_tst_enable | **on** | SelfLift TST 少步画质补偿（闪屏/身份漂移/运动异常） |
| selflift_tst_tau | **0.2** | 论文推荐0.2，0.5太强，0=诊断 |
| temporal_chunk_tokens | **0（关）** | v14.307里程碑已全线关闭时间分块；空间分块(tile_count=4)保留 |
| semantic_bridge_enable | off | 语义桥 MLP（~11MB），增强指令遵循；默认关 |
| face_lock_mode | off | off / auto(参考图锁脸) / refine(小脸inpaint，需BSAI-FaceRefine插件) |
| refine_mem_mode | spatial (tiled) | spatial=4块空间分块；global=全序列注意力无接缝 |

---

## 五、常用搭配推荐

| 场景 | render_pipeline | one_shot_mode | one_shot_sampling | LoRA |
|---|---|---|---|---|
| **日常一镜到底 MV** | Sol-H3 Self-Lift Dual-Pass | on | Dual-pass seamless (8+4) | 无（默认）或 Turbo-v4 |
| **一镜到底 2K 成片** | 同上 | on | Dual-pass seamless 2K (8+4) | 同上 |
| **极速预览/草稿** | PDMD 2-step Turbo Draft | off | — | pdmd_2step_lora |
| **少步高质量一镜到底** | PDMD 4-step SelfLift Dual-Pass | on | Single-pass seamless | pdmd_4step_lora |
| **直出1080p** | PIKA H3 Flex 6+2 | on | Single-pass seamless | pika_h3_flex_ref2va_v1 |
| **高动态动作/长视频** | SingularityV2+Pika H3 8步 高动态长视频 | on | Dual-pass seamless (8+4) 或 Single-pass seamless | pika_h3_flex_turbo_8step_hd_ref2va + 动作LoRA三选一（一采 0.5~0.6 / 二采 0.3~0.4） |
| **结构控制分镜** | SolarRenderer Structure Control | off 或 on | 按需 | solarrenderer 控制LoRA + 4步LoRA |
| **直播带货一键出片** | Live Commerce (fully automatic) | off | — | 无（12+4 配方） |
| **4K 电影感** | 4K Direct Secret Sauce | off | — | turbo_v4_step600 + MysticXXX_V4 |

---

## 六、新增 / 改名 / 调序档位的维护规程（必读）

`render_pipeline` 下拉**不是** ComfyUI 原生 combo，而是插件在 `web/extender.js` 里用自定义 DOM 下拉渲染的，取值来自**后端枚举 + 三份硬编码数据**。任何新增/改名/调序（含改快捷按钮）必须一次改全，顺序如下：

| 序 | 位置 | 文件 | 改什么 |
|---|---|---|---|
| 1 | 后端枚举 | `extender.py` `render_pipeline` options | 追加/改英文档名（必须与前端取值逐字一致） |
| 2 | 英文→中文映射 | `extender.py` `_RENDER_PIPELINE_EN2ZH` | 新英文档名 → 中文分支 label |
| 3 | 分支实现 | `extender.py` `elif _rp_mode == "<中文label>":` | 写该档配方，末尾由 `_rp_handled` 收口 |
| 4 | cycle | `extender.js` `QUICK_DEFS.render_pipeline` | 与后端 options 逐字一致、顺序一致 |
| 5 | cycleLabels | 同上一条 def | 按钮显示名，长度必须 = cycle |
| 6 | tints | 同上一条 def | 颜色梯度，长度必须 = cycle |
| 7 | cycleAliases | 同上一条 def | 旧中文 label → 新英文值（既有档位改名时必须补） |
| 8 | 旧值兼容表-白名单 | `extender.js` `H3LegacyCompat.OPTIONS.render_pipeline` | 值不在白名单会被 `norm()` 静默回落默认档 |
| 9 | 旧值兼容表-别名 | `extender.js` `H3LegacyCompat.ALIAS_CANON.render_pipeline` | 中文旧标签 → 英文规范值 |
| 10 | DEFAULTS | `extender.js` `H3LegacyCompat.DEFAULTS` 第 65 位 | 仅在改默认档时才动 |
| 11 | 跑自检 | `node --check web/extender.js`、`py_compile extender.py`、三表逐字比对、重启后 `/object_info/BSAIH3FilmFactory` 计 40 项（档数随版本递增，以 combo 长度为准） | 全通过才算改完 |

两条硬约束：任何新 widget 只能追加在 `optional` 最末尾（现役最后一项是 `refine_sigmas`），不得挤占既有 widget index；只改后端不改前端的效果是"UI 里选不到新档 + 含新档的旧工作流加载被打回默认档"。

---

## 七、Regenerate 2K 二采的适用面（BV1Yh4j6gEt3）

教程（《MiniMax H3又被玩出新花样了！潜空间重绘直冲2K！》）与 NVlabs/Sana `Open-H3-Regenerate-2K` 的做法只有四件事：

1. 低清草稿（384P~768P）只负责构图/运动；
2. 3D 卷积 latent 上采样器**直接放大到目标网格**（不解码再编码）；
3. 放大后的 latent **重噪到 sigma 0.909375**，3 步 Euler（`[0.909375, 0.857143, 0.666667, 0]`），CFG off；
4. 合并 LoRA（Refiner rank384 + LightX2V FL2VA Turbo v1.2 rank128 + LMS Sharp rank64）承担"少步 + 重新画细节"。

**结论：这不是一次"全管道升级"，而是一种只在特定档位成立的二采模式。** 是否可挂，按下表判断（`refine_sigmas` 端口本身就接受外部 SIGMAS，无需改代码即可试）：

| 档位 | 可否挂 regenerate 二采 | 原因 |
|---|---|---|
| 19 OpenH3Regenerate2K | **已内置** | 本档就是该方案，二采 sigmas 已固定注入 |
| 9 4K直出秘制酱料 / 11 双采2K HyperVAE / 25 双采2K官方条件放大 / 31 TaoMate 8+4 / 32 Singularity 8+3 / 24 Director / 17 Omni SelfLift / 22 4合1 / 1 默认 Sol-H3 / 4 FastH3-Trim / 5 6 7 8 26 | 可试，需单独验收 | 都有"latent 放大 + 少步二采"结构，起点改成 0.9 会从"抛光"变"重画"，细节更强但人物/道具会出现局部重绘 |
| 3 / 13 / 14 / 15 / 16 直播带货·对口型 / 29 PIKA 锁脸 | **不要挂** | 高 sigma 重绘会改嘴型、改产品 logo/文字，直接毁掉对口型与货品一致性 |
| 10 Omni 单采 / 12 QAD-v2 / 18 H25 / 21 透明视频 / 27 PDMD 2步 / 28 PTD | **无二采环节** | 单采档没有第二遍，挂不上 |
| 一镜到底链式（one_shot_mode=on） | **不要全片挂** | 段间靠 motion context 锚上一段尾 latent，0.9 重绘会让每段各自重画 → 人物漂移、接缝跳变 |

前提条件（缺一不可）：`models/loras` 里要有 Kijai 转换的 `minimax_h3_open_regenerate_2k_refiner_rank_384_bf16.safetensors`（或 father558/DrakenZA 的全量合并版），配 LightX2V FL2VA Turbo v1.2 + LMS Sharp 一起挂；latent 上采样器用 `minimax_h3_latent_upscaler_3d_conv_v1_bf16.safetensors`。**自制转换必须做 SwiGLU 变换，单纯改 key 名会得到发灰/噪点画面。**

---

*本表由 extender.py 源码自动提取整理，如管道参数在后续版本变更请以源码为准。*
