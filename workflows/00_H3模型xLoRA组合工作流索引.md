# H3 模型 × 加速 LoRA 最佳搭档工作流索引

> 生成时间 2026-10-25 ｜ 模板：电影工厂「直播带货（手动档）8步模型+2步lora」
> 共 **30 组**，按 6 大类 + 顺序编号 ｜ 全部工作流在插件 workflows 目录，可直接拖入 ComfyUI

## 配对依据

每组都不是"随便配"，而是按本机 safetensors **实测兼容矩阵**选出：

1. 读底座 safetensors 头拿到真实 state_dict 键集与形状（归一化 `model.` / `diffusion_model.` 前缀）；
2. 按插件源码复刻两套装载逻辑 —— **BSAI Loader 槽**（`_fastvideo_lora_to_comfy_patches` + 形状过滤）与 **H3LoraStack 栈槽**（`comfy.sd.load_lora_for_models` → `convert_lora` + `comfy.lora.load_lora`）；
3. 只有 **目标键命中且形状一致** 的组合才进入本清单，命中率逐组写在配方卡里。


## A 类｜官方 Comfy-Org dense 底座 × 全格式加速 LoRA

| 编号 | 主模型 | 加速 LoRA | 强度 | 渲染管道 | 采样 | 二采 | 文件 |
|---|---|---|---|---|---|---|---|
| A01 | minimax_h3_ref2va_int8_convrot.safetensors | minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors | 1.0 | Sol-H3 Self-Lift 双采 (默认) | 4步 er_sde/simple | 2步 | `H3组合_A01_ref2va_int8_convrot x ref2v_turbo_4step_v0.1__4+2步_er_sde+simple.json` |
| A02 | minimax_h3_ref2va_int8_convrot.safetensors | minimax_h3_turbo_v4_step600_ema_pruned_comfyui.safetensors | 1.0 | Turbo-v4 | 8步 euler/beta | 4步 | `H3组合_A02_ref2va_int8_convrot x turbo_v4_pruned_8+4步_euler+beta.json` |
| A03 | minimax_h3_fl2va_zs05_int8_convrot.safetensors | minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors | 0.75 | Sol-H3 Self-Lift 双采 (默认) | 4步 er_sde/simple | 2步 | `H3组合_A03_fl2va_zs05_int8_convrot x fl2v_turbo_4step_v1.0__4+2步_er_sde+simple.json` |
| A04 | minimax_h3_fl2va_zs05_int8_convrot.safetensors | minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors | 1.0 | Sol-H3 Self-Lift 双采 (默认) | 8步 euler/simple | 4步 | `H3组合_A04_fl2va_zs05_int8_convrot x fl2v_turbo_8step_v1.0__8+4步_euler+simple.json` |
| A05 | minimax_h3_fl2va_zs05_int8_convrot.safetensors | minimax_h3_turbo_4step_comfy_v2.safetensors | 1.0 | Sol-H3 Self-Lift 双采 (默认) | 4步 euler/simple | 2步 | `H3组合_A05_fl2va_zs05_int8_convrot x turbo_4step_comfy_v2_4+2步_euler+simple.json` |
| A06 | minimax_h3_fl2va_zs05_int8_convrot.safetensors | FastH3-4step-VSA-LoRA.safetensors | 1.0 | FastH3-4步VSA | 4步 euler/simple | 2步 | `H3组合_A06_fl2va_zs05_int8_convrot x FastH3-4step-VSA-LoRA_4+2步_euler+simple.json` |
| A07 | minimax_h3_ref2va_int8_convrot.safetensors | minimax_h3_ELM_longlive_plug_4step_lora_bf16.safetensors | 1.0 | Sol-H3 Self-Lift 双采 (默认) | 4步 euler/simple | 2步 | `H3组合_A07_ref2va_int8_convrot x ELM_longlive_plug_4step_lora_bf16_4+2步_euler+simple.json` |

## B 类｜社区 dense 底座 × 全格式加速 LoRA

| 编号 | 主模型 | 加速 LoRA | 强度 | 渲染管道 | 采样 | 二采 | 文件 |
|---|---|---|---|---|---|---|---|
| B01 | minimax_h3_ref2va_XUELUO_int8_convrot.safetensors | minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors | 1.0 | Sol-H3 Self-Lift 双采 (默认) | 4步 er_sde/simple | 2步 | `H3组合_B01_ref2va_XUELUO_int8_convrot x ref2v_turbo_4step_v0.1__4+2步_er_sde+simple.json` |
| B02 | Minimax-h3_Singularity_ref2va_v1.3_int8.safetensors | minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors | 1.0 | Sol-H3 Self-Lift 双采 (默认) | 4步 er_sde/simple | 2步 | `H3组合_B02_Minimax-h3_Singularity_ref2va_v1.3_int8 x ref2v_turbo_4step_v0.1__4+2步_er_sde+simple.json` |
| B03 | Minimax-h3_Singularity_ref2va_v2_int8.safetensors | minimax_h3_turbo_v4_step600_ema_pruned_comfyui.safetensors | 1.0 | Turbo-v4 | 8步 euler/beta | 4步 | `H3组合_B03_Minimax-h3_Singularity_ref2va_v2_int8 x turbo_v4_pruned_8+4步_euler+beta.json` |
| B04 | PinkCherry_h3_fl2va_int8_convrot_v0.5-alpha-C.safetensors | minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors | 1.0 | Sol-H3 Self-Lift 双采 (默认) | 8步 euler/simple | 4步 | `H3组合_B04_PinkCherry_h3_fl2va_int8_convrot_v0.5-alpha-C x fl2v_turbo_8step_v1.0__8+4步_euler+simple.json` |

## C 类｜社区 pruned/curve 底座 × pruned/curve 格式加速 LoRA

| 编号 | 主模型 | 加速 LoRA | 强度 | 渲染管道 | 采样 | 二采 | 文件 |
|---|---|---|---|---|---|---|---|
| C01 | Minimax-h3_Singularity_ref2va_Pruned_v1.3_int8.safetensors | minimax_h3_turbo_v4_step600_ema_pruned_comfyui.safetensors | 1.0 | Turbo-v4 | 8步 euler/beta | 4步 | `H3组合_C01_Minimax-h3_Singularity_ref2va_Pruned_v1.3_int8 x turbo_v4_pruned_8+4步_euler+beta.json` |
| C02 | DasiwaMinimaxH3_V4_int8.safetensors | minimax_h3_turbo_v4_step600_ema_DasiwaREF2VAHybridV1_0_curveproj1025_compat_v001.safetensors | 1.0 | Turbo-v4 | 8步 euler/beta | 4步 | `H3组合_C02_DasiwaMinimaxH3_V4_int8 x turbo_v4_DasiwaREF2VAHybridV1_0_curveproj1025__8+4步_euler+beta.json` |
| C03 | minimax_h3_hybrid_fl2va_ref2va_b25-49-int8.safetensors | minimax_h3_turbo_v4_step600_ema_DasiwaREF2VAHybridV1_0_curveproj1025_compat_v001.safetensors | 1.0 | Turbo-v4 | 8步 euler/beta | 4步 | `H3组合_C03_hybrid_fl2va_ref2va_b25-49-int8 x turbo_v4_DasiwaREF2VAHybridV1_0_curveproj1025__8+4步_euler+beta.json` |
| C04 | Cobijada_H3_Hybrid_Uncensored_pruned_hybrid_int8_convrot_pruned.safetensors | minimax_h3_turbo_v4_step600_ema_DasiwaREF2VAHybridV1_0_curveproj1025_compat_v001.safetensors | 1.0 | Turbo-v4 | 8步 euler/beta | 4步 | `H3组合_C04_Cobijada_H3_Hybrid_Uncensored_pruned_hybrid_in x turbo_v4_DasiwaREF2VAHybridV1_0_curveproj1025__8+4步_euler+beta.json` |
| C05 | 10Eros_Max_h3_hybrid_beta5_int8.safetensors | minimax_h3_turbo_v4_step600_ema_pruned_comfyui.safetensors | 1.0 | Turbo-v4 | 8步 euler/beta | 4步 | `H3组合_C05_10Eros_Max_h3_hybrid_beta5_int8 x turbo_v4_pruned_8+4步_euler+beta.json` |
| C06 | PinkCherry_hybrid_v1.8_int8_minimax_h3_pruned.safetensors | minimax_h3_turbo_v4_step600_ema_pruned_comfyui.safetensors | 1.0 | Turbo-v4 | 8步 euler/beta | 4步 | `H3组合_C06_PinkCherry_hybrid_v1.8_int8_pruned x turbo_v4_pruned_8+4步_euler+beta.json` |
| C07 | PinkCherry_hybrid_v1.8_int8_minimax_h3_pruned.safetensors | minimax_h3_4step_lora_flashgen_v1.0_768p_fl2va_pruned_avg_rank_13_bf16.safetensors | 1.0 | Sol-H3 Self-Lift 双采 (默认) | 4步 euler/simple | 2步 | `H3组合_C07_PinkCherry_hybrid_v1.8_int8_pruned x 4step_lora_flashgen_v1.0_fl2va_pruned_avg_rank_4+2步_euler+simple.json` |

## D 类｜蒸馏整模型档（底座自带蒸馏）

| 编号 | 主模型 | 加速 LoRA | 强度 | 渲染管道 | 采样 | 二采 | 文件 |
|---|---|---|---|---|---|---|---|
| D01 | fastvideo_fasth3_8step_v2_pruned_int8_convrot.safetensors | （无） | 0.0 | 双采2K（HyperVAE 2x 解码） | 8步 euler/simple | 4步 | `H3组合_D01_fastvideo_fasth3_8step_v2_pruned_int8_convrot x 无LoRA_8+4步_euler+simple.json` |
| D02 | fasth3_omniref_8step_pruned_int8_convrot.safetensors | （无） | 0.0 | FastH3 Omni 8步单采 | 8步 euler/simple | 关 | `H3组合_D02_fasth3_omniref_8step_pruned_int8_convrot x 无LoRA_8+0步_euler+simple.json` |
| D03 | 10Eros_Max_h3_hybrid_beta5_int8.safetensors | minimax_h3_dmad_full_dareties_v4_step600_comfy_fro.safetensors | 0.8 | DMAD-4步 | 4步 lcm/simple | 2步 | `H3组合_D03_10Eros_Max_h3_hybrid_beta5_int8 x dmaddareties_v4_step600_comfy_fro_4+2步_lcm+simple.json` |
| D04 | minimax_h3_ref2va_int8_convrot.safetensors | minimax_h3_DMAD_4step_full_lora_avg_rank_39_bf16.safetensors | 0.8 | DMAD-4步 | 4步 lcm/simple | 2步 | `H3组合_D04_ref2va_int8_convrot x DMAD_4steplora_avg_rank_39_bf16_4+2步_lcm+simple.json` |

## E 类｜插件内建特殊管道档

| 编号 | 主模型 | 加速 LoRA | 强度 | 渲染管道 | 采样 | 二采 | 文件 |
|---|---|---|---|---|---|---|---|
| E01 | minimax_h3_ref2va_int8_convrot.safetensors | minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors | 1.0 | 直播配音高清（音频≥12步） | 12步 euler/simple | 4步 | `H3组合_E01_ref2va_int8_convrot x ref2v_turbo_4step_v0.1__12+4步_euler+simple.json` |
| E02 | minimax_h3_ref2va_int8_convrot.safetensors | minimax_h3_turbo_v4_step600_ema_pruned_comfyui.safetensors | 1.0 | 直播带货（全自动） | 12步 euler/simple | 4步 | `H3组合_E02_ref2va_int8_convrot x turbo_v4_pruned_12+4步_euler+simple.json` |
| E03 | minimax_h3_ref2va_int8_convrot.safetensors | minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors | 0.6 | 4K直出 秘制酱料 | 6步 euler/simple | 3步 | `H3组合_E03_ref2va_int8_convrot x ref2v_turbo_4step_v0.1__6+3步_euler+simple.json` |
| E04 | minimax_h3_ref2va_int8_convrot.safetensors | minimax_h3_turbo_v4_step600_ema_pruned_comfyui.safetensors | 1.0 | 双采2K（HyperVAE 2x 解码） | 8步 euler/simple | 4步 | `H3组合_E04_ref2va_int8_convrot x turbo_v4_pruned_8+4步_euler+simple.json` |

## F 类｜风格/功能 LoRA 叠加档

| 编号 | 主模型 | 加速 LoRA | 强度 | 渲染管道 | 采样 | 二采 | 文件 |
|---|---|---|---|---|---|---|---|
| F01 | minimax_h3_ref2va_int8_convrot.safetensors | minimax_h3_turbo_v4_step600_ema_pruned_comfyui.safetensors | 1.0 | Sol-H3 Self-Lift 双采 (默认) | 8步 euler/beta | 4步 | `H3组合_F01_ref2va_int8_convrot x turbo_v4_pruned_8+4步_euler+beta.json` |
| F02 | Minimax-h3_Singularity_ref2va_Pruned_v1.3_int8.safetensors | minimax_h3_turbo_v4_step600_ema_pruned_comfyui.safetensors | 1.0 | 武戏组合拳 | 6步 euler/simple | 6步 | `H3组合_F02_Minimax-h3_Singularity_ref2va_Pruned_v1.3_int8 x turbo_v4_pruned_6+6步_euler+simple.json` |
| F03 | Minimax-h3_Singularity_ref2va_Pruned_v1.3_int8.safetensors | minimax_h3_turbo_v4_step600_ema_pruned_comfyui.safetensors | 1.0 | Turbo-v4 | 8步 euler/beta | 4步 | `H3组合_F03_Minimax-h3_Singularity_ref2va_Pruned_v1.3_int8 x turbo_v4_pruned_8+4步_euler+beta.json` |
| F04 | minimax_h3_ref2va_int8_convrot.safetensors | minimax_h3_turbo_v4_step600_ema_pruned_comfyui.safetensors | 1.0 | Sol-H3 Self-Lift 双采 (默认) | 8步 euler/beta | 4步 | `H3组合_F04_ref2va_int8_convrot x turbo_v4_pruned_8+4步_euler+beta.json` |


## 插槽分工（插件原生用法）

| 插槽 | 节点 | 吃哪种 LoRA | 依据 |
|---|---|---|---|
| **加速 LoRA 槽** | 节点 329 `BSAI_SolH3_Loader.lora_name` | Comfy 布局(`lora_A/B`)、diffusers 布局(`transformer.*`)、delta(`diff`/`diff_b`) | 插件自研转换器 + 形状过滤，兼容面最广 |
| **风格 LoRA 栈 A** | 节点 1335 `H3LoraStack`（动作/武戏） | Comfy 布局 `lora_A/B` + `lora_up/down` | `comfy.sd.load_lora_for_models` 原生 7 种命名 |
| **风格 LoRA 栈 B** | 节点 1440 `H3LoraStack`（质感/写实/音频） | 同上 | 同上 |

## 实测兼容矩阵摘要（本机 14 个 H3 底座 × 18 个 H3 相关 LoRA）

| 加速 LoRA | 底座键集 | Loader 槽命中 | 栈槽命中 | 结论 |
|---|---|---|---|---|
| LightX2V Ref2V-Turbo 4步 v0.1 | 208 对 | **14/14 底座 208/208** | 208 | 全底座通用 |
| LightX2V FL2V-Turbo 4步 v1.0 / v1.2 | 208 对 | **14/14 底座 208/208** | 208 | 全底座通用 |
| LightX2V FL2V-Turbo 8步 v1.0 | 208 对 | **14/14 底座 208/208** | 208 | 全底座通用 |
| turbo v4 step600 EMA（pruned 版） | 208 对 | **14/14 底座 208/208** | 208 | 全底座通用（无 adaln） |
| turbo 4step comfy_v2 | 208 对 | **14/14 底座 208/208** | 208 | 全底座通用 |
| ELM longlive plug 4step | 208 对 | **14/14 底座 208/208** | 208 | 全底座通用 |
| DMAD dareties / DMAD full rank39 | 208 对 | **14/14 底座 208/208** | 208 | 全底座通用 |
| PDMD 4step rank57 / 2step rank38 | 208 对 | **14/14 底座 208/208** | 208 | 全底座通用 |
| solarwm stage05 adapter | 208 对 + 208 δ | **14/14 底座 208/208** | 208 | 全底座通用（来源未核实，未入正表） |
| DaSiWa curveproj1025 | 259 对 + 51 δ | dense 208/259 ｜ **pruned 系 259/259** | 310 | **只配 pruned 底座** |
| FlashGen 4step v1.0 768p | 259 对 + 51 δ | dense 208/259 ｜ **pruned 系 259/259** | 310 | **只配 pruned 底座** |
| FastH3 4步 VSA-LoRA | 258 对 + 82 δ | **dense 258/258** ｜ pruned 208/258 | 0 | **只配 dense 底座，且只能放 Loader 槽** |
| LMS 细节纹理增强 | 208 对（含 50 adaln 8 维） | pruned 258/258 ｜ **dense 形状不符会报错** | 208 | **只配 pruned 底座** |
| **HyperFlow 8步 v1.0** | `transformer.*` 前缀 | **0/212 全底座** | **0** | ⚠ **两个槽都装不上，见下方"已知不可用"** |
| **Wuli Turbo 4steps V1.0** | `lora.generator.*` 前缀 | **0/208 全底座** | **0** | ⚠ 不可用 |
| **TaoMate-H3-step3000** | `lora_down/lora_up` 命名 | **0 对** | **0** | ⚠ 不可用（见下方） |
| **FastH3-4step-LoRA** | — | 文件损坏 | — | ⚠ 不可用 |

## 已知不可用（实测，不臆测）

1. **HyperFlow 8步 v1.0**（`minimax_h3_hyperflow_8step_v1.0.safetensors`）—— 键名带 `transformer.` 前缀，而 BSAI Loader 的 `_fv_key_to_comfy` 只做 `transformer_blocks.→blocks.` 替换，**不剥 `transformer.`**；Comfy 原生栈侧 `unet_to_diffusers` 对 H3 返回空、`convert_lora` 也无通用前缀剥离。→ **两槽均 0 命中**，控制台会打印「LoRA加载失败(0个key匹配模型)」。本清单已全部替换为 turbo v4 等实测可装载件。
2. **Wuli Turbo 4steps V1.0** —— 键名带 `lora.generator.` 前缀，同样两槽 0 命中。
3. **TaoMate-H3-step3000-ComfyUI-FP32** —— 用 `lora_down/lora_up` 命名且**不带** `diffusion_model.` 前缀，两槽均匹配不到模型键。要用需先自行补前缀。
4. **FastH3-4step-LoRA.safetensors** —— 本机文件 safetensors 数据区截断（声明长度 > 实际大小），无法加载。

## 独立路线：PDD-Acc（阿里 PAI 官方 8 步加速）**不能进电影工厂**

本机已有 `H3加速lora\ref2va\pdd_acc\minimax_h3_ref2va_pdd_acc_8step_comfyui.safetensors` 与 `..._fl2va_pdd_acc_8step_comfyui.safetensors`（各 1.58 GB / 778 张量 / 258 对 + 258 alpha，上游 `alibaba-pai/MiniMax-H3-Acc-LoRAs`）。但它们**不是普通 LoRA**：除 rank-64 主干外还带 **PDD 头组**（32 份最终层视频/音频投影副本，每个采样步融合成一个平均块速度头），普通 LoRA 装载器读不了、丢掉头组会**静默丢失蒸馏效果**。

- 必须由 `BSAI-ComfyUI-MiniMax-H3-PDD-Acc` 插件的 **Apply 节点 + Scheduler 节点**接管采样；而电影工厂主节点（250）**内部自建采样器**（`comfy.samplers.sampler_object` + 自算 sigmas），**没有 SIGMAS 输入口**，所以无法把 PDD 的训练网格 sigmas 接进去 → 本批工作流不含 PDD 档。
- 另：插件按文档需把文件放到 `ComfyUI/models/pdd_acc/`（当前该目录**不存在**，文件还在 `models/loras/` 下）；即便放好，也要用插件自带的 `example_workflows/pdd_acc_t2v_basic.json` 等工作流。
- 官方配方（若单独用）：euler + CFG 1.0 + shift **12.0/3.0**，nfe=8（4/6 亦可，块大小只允许 4 或 8），lora_strength/head_strength = 1.0/1.0。

## 备选加速 LoRA 池（实测可装载，本批未占用编号）

| LoRA | 兼容范围 | 建议底座 | 说明 |
|---|---|---|---|
| `minimax_h3_fl2v_turbo_4step_v1.2_768p_comfyui_bf16` | 14/14 底座 208/208 | 官方 FL2VA | A03 的同族新版，文件名直接替换即可 |
| `minimax_h3_pdmd_4step_lora_avg_rank_57_bf16` | 14/14 底座 208/208 | 官方 Ref2VA/FL2VA | 字节+TaMU(DMAD) 的 PDMD 4 步件 |
| `minimax_h3_pdmd_2step_lora_avg_rank_38_bf16` | 14/14 底座 208/208 | 官方 Ref2VA/FL2VA | PDMD 2 步件，最快档 |
| `solarwm_h3_stage05_adapter_model_comfy_new` | 14/14 底座 208/208 + 208 δ | 官方 dense | 5 段式 stage05 adapter，来源未完全核实 |
| `电影工厂真实皮肤组合LORA\minimax_h3-realism-people-t2v-i2v-r2v` | 104/104（dense 底座） | 官方 Ref2VA | 与 F01 同一件，F01 栈槽已在用 |
| `H3_speed_slider_1.1` | 仅 1 个模块命中 | 任意 | 键名 `lora_down/up` + `diffusion_model.` 前缀，效果极弱 |

## 全局参数说明（与模板的差异，已逐条对齐）

| 项 | 值 | 原因 |
|---|---|---|
| Loader `min_tokens` | 12288 → **1024** | 插件 v2.9.1 起默认改为 1024；12288 门槛会让 Sol-Attn 内核全部 dense 回退，Spark/tau 稀疏全部失效（实测 off/full 输出逐像素一致），即白跑稀疏。 |
| Loader `cfg` | 4.0 → **1.0** | 工厂端用自带 `_BasicGuider`（继承 `CFGGuider`，默认 cfg=1.0 且不传 negative），Loader 的 cfg 不参与采样；置 1.0 避免与蒸馏契约（guidance 1.0）显示矛盾。 |
| Loader `sampler` | 统一 **euler** | 该 widget 合法值只有 euler/dpmpp_2m/euler_ancestral，且不参与采样；真正生效的采样器在电影工厂节点的 `sampler_name`。 |
| `refine_lipsync_mode` | 逐组显式写入 | 该下拉**会覆盖** `refine_audio_denoise`（锁定=0 / 0.7 / 1.0），模板里的「音频参与重绘0.7」会让所有组都强制 0.7。本清单按各组需要显式写死。 |
| `speed_preset` | 统一 **custom** | 渲染管道非默认档时由插件接管参数并把 speed_preset 置 custom；custom 同时让 v14.195 音频保护**不**把 4/8 步自动顶回 12 步。 |
| `render_pipeline` | 逐组写入并**与运行时接管值一致** | 非默认档的参数在运行期被管道分支覆盖，本清单已逐档对齐（12+4/0.55、8+4/0.45、6+3/0.45、4+2/0.45、6+6/0.45 等），UI 显示即真实配方。 |

## 两点必读

1. **音频与步数**：一采 < 12 步时官方音频不可用（恒定低频轰鸣）。本清单 4/6/8 步档均已 `speed_preset=custom` 保住步数，代价就是音频有底噪；**要干净配音请走 E01/E02（12 步）或接 lip_voice 对口型锁音频**。
2. **超分引擎**：`upscale_mode=质量优先` 会被 `_ff_resolve_upscale_mode` 解析成 **3.0x REALESR**，`upscale_engine=dlss5` 在预设档下会被覆盖（插件的 4K 档也是同样行为）。想真用 DLSS5 请把 `upscale_mode` 改成「自定义」。
