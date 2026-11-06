# BSAI-H3-Film-Factory 渲染管道 / 模式 / LoRA 搭配速查表

> 基于 `extender.py` v14.322 源码整理（2026-11-05）。
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

## 三、渲染管道（render_pipeline）全 32 档

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
| 19 | **4K Regenerate OpenH3Regenerate2K** | 2560x1440 | 768P草稿(1344x768)→3步重生成 | 合并LoRA: OpenH3 Refiner 5000步(0.7)+fl2v turbo(1.0)+lms sharp(1.0)；**许可不含EU/UK/KR/US** | 4K重生成 |
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
| 11 | 跑自检 | `node --check web/extender.js`、`py_compile extender.py`、三表逐字比对、重启后 `/object_info/BSAIH3FilmFactory` 计 31 项 | 全通过才算改完 |

两条硬约束：任何新 widget 只能追加在 `optional` 最末尾（现役最后一项是 `refine_sigmas`），不得挤占既有 widget index；只改后端不改前端的效果是"UI 里选不到新档 + 含新档的旧工作流加载被打回默认档"。

---

*本表由 extender.py 源码自动提取整理，如管道参数在后续版本变更请以源码为准。*
