# Viggle Remake 视频改写（第 36 档）使用与安装说明

来源：B站教程《MiniMax H3 超强视频编辑工作流，Viggle Remake 两个 LoRA，6 步采样，极速搞定视频人物替换、场景替换、道具增减》
（BV19xWx69Eu6）+ 官方仓库 https://huggingface.co/Viggle/Viggle-Remake 。

本机落地时间：2026-11-09，当前 `BUILD = minimax-h3-extender-v14.346-viggle-remake-6step+video-remix-maskfix`（v14.345 加入第 36 档，v14.346 修 35 档掩码变量名冲突）。

---

## 1. 这次新增了什么

| 类型 | 位置 |
|---|---|
| 渲染管道档位 | 电影工厂 `render_pipeline` 第 36 项：`Viggle Remake Video Edit (6-step swap/edit LoRA, FL2VA)` / 中文 `Viggle Remake 视频改写 (6步 换人/增删改)` |
| 后端实现 | `extender.py`：`_VIGGLE_REMAKE_SIGMAS`、`_viggle_task()`、`_viggle_prompt()`、`_viggle_build_plan()`、`_sigmas()` 两条固定 knot 调度、档位分支、cond video 注入 |
| 官方节点包 | `ComfyUI/custom_nodes/ComfyUI-Viggle-Remake/`（`ViggleRemakeConditioning` / `ViggleRemakeKeyframeUntil` / `ViggleRemakeNoise`） |
| 示例工作流（原生节点） | `example_workflows/…电影工厂-ViggleRemake视频改写-swap-6步-原生节点-5090.json`<br>`example_workflows/…电影工厂-ViggleRemake视频改写-edit-6步-原生节点-5090.json` |
| LoRA 权重 | `G:\BSAI-ComfyUI-intel-XPU-GPU-NPU-aki\ComfyUI\models\loras\H3\H3视频编辑\viggle_remake_swap_comfyui.safetensors`<br>同目录 `viggle_remake_edit_comfyui.safetensors` |
| 说明文档 | `RENDER_PIPELINES_REFERENCE.md` 第八节、`CHANGELOG.md` v14.345 |

## 2. 官方契约（本档已内置，不要改）

- **6 步**，固定 sigma knots（不是 simple/linspace）：
  - swap（换人/换主体）：`1.0, 0.990476, 0.965243, 0.923077, 0.8, 0.631579, 0.0`
  - edit（元素增删改）：`1.0, 0.983607, 0.96, 0.923077, 0.857143, 0.705882, 0.0`
- cfg **1.0**（无负面提示词）、euler、24fps、无二采。
- 源片整段作为 **cond video**（`minimax_refs` 首个 `video` block），目标 latent **全噪**，源原声锁 **clean**（音频 mask=0）。
- 段长 90–345 帧，且必须是 `17n+5`（90/107/124/…/345）。本档默认 226 帧/段，0 重叠。
- 画面短边必须能被 32 整除。
- LoRA 只认 **FL2VA** 基座，必须走 **`LoraLoaderBypassModelOnly`**（bypass 槽）；普通 `LoraLoaderModelOnly` 不走这条 patch 路径。
- 两个 LoRA 不要同时挂：swap 与 edit 二选一。

## 3. 两种跑法

### A. 电影工厂档位（批量 / 分镜流程）

1. 基座：`H3/minimax_h3_fl2va_zs05_int8_convrot.safetensors`。
2. LoRA 槽：`LoraLoaderBypassModelOnly` → `H3\H3视频编辑\viggle_remake_swap_comfyui.safetensors`（strength 1.0）。
3. 电影工厂节点：`render_pipeline` 选第 36 档；或点快捷栏 **`Viggle / Remake`** 一键按钮（自动 6 步 / euler / denoise 1.0 / shift 12-3 / 关二采 / 0 重叠 context）。
4. 资产库：`@视频N` = 源视频；`@图N` = 要换成的角色（swap）或要增删改的元素参考（edit）。
5. 提示词照常写"谁换成谁 / 加什么删什么"，后端会自动拼 Viggle 改写纪律块。
6. `edit` 任务：设环境变量 `BSAI_H3_VIGGLE_TASK=edit`（默认 swap），或直接用下面的 edit 示例工作流。

采样参数被档位固定为 6 步 / cfg 1.0 / 单采；widget 里填别的步数不会生效。

### B. 原生示例工作流（要 pins 时用这个）

`example_workflows/…ViggleRemake视频改写-swap-6步-原生节点-5090.json`：

`UNETLoader(FL2VA int8) → LoraLoaderBypassModelOnly(swap) → RemakeKeyframeUntil(0.9) → RemakeConditioning → SamplerCustomAdvanced(ManualSigmas=官方 swap 曲线) → VAEDecode/VAEDecodeAudio → CreateVideo/SaveVideo`

- `pins`（参考帧锚定）由 `RemakeConditioning` 的 pin frames 参数决定：填两帧索引（逗号分隔、均 < frames）；`RemakeKeyframeUntil` 让 pinned 帧只在 sigma≥0.9 的前几步硬锁。
- 首次打开需把 `LoadVideo`/`LoadImage` 的占位文件名换成自己的素材。

## 4. 已知限制（务必看）

1. **第 36 档不做 pins 早停**。需要 pins 请用 B 方案原生工作流（自带 `RemakeKeyframeUntil` 0.9）。
2. 电影工厂档位默认只吃 `@视频N` 源片 + `@图N` 参考图，靠 6 步全噪重绘 + 纪律块改写。
3. int8 量化基座 + bf16 LoRA 是"能挂但需实跑验收"的组合；若报权重不匹配，改用官方合并版 `comfyui/viggle_remake_swap_int8_convrot.safetensors`（21GB，无需 LoRA 槽，`UNETLoader` 直接加载）。
4. 显存：官方称 int8 在 32GB / CUDA 13（5090）上可跑到 `1280x736 / 345 帧`；bf16 需要 ~37GB。
5. 不适用：长视频整段直出（>14.4s/段）——本档按 226 帧逐段改写，段与段之间是独立生成，接缝需后期处理。

## 5. 验证记录

- [x] `py_compile extender.py` 通过
- [x] `node --check web/extender.js` 通过
- [x] 三表逐字一致：后端 options 36 项 / JS 白名单 36 项 / JS 别名表 36 项
- [x] 示例工作流 JSON 可解析，引用的基座 / TE / 视频 VAE / 音频 VAE 本机均存在；两份示例的 `ManualSigmas` 与官方 swap/edit 曲线逐字一致（226 帧、`RemakeKeyframeUntil`=0.9、24fps、LoRA 走 `LoraLoaderBypassModelOnly`）
- [x] 后端模块离线可导入（stub 掉 `PromptServer.instance` 后 `importlib` 加载成功，BUILD、两组 sigma knots、`_viggle_task()` 全部正确）
- [x] **运行态实测**（ComfyUI 8181）：`/object_info/BSAIH3FilmFactory` 的 `render_pipeline` 返回 36 项、末项即第 36 档；`RemakeConditioning` / `RemakeKeyframeUntil` / `RemakeNoise` / `RemakePrefix` / `LoraLoaderBypassModelOnly` 全部已注册
- [x] **权重下载校验**：两个 LoRA 均 `3,773,044,920` 字节（= 3×1257681640 分段，3.51 GiB），`.part*` 已清理；safetensors header 可解析，各 606 个张量 / 202 个 `.alpha`，`lora_A/lora_B` 为 BF16，命名 `diffusion_model.blocks.N.*`
- [x] **维度对齐**：LoRA 目标模块（qkv_proj 21504×5376、out_proj 5376×7168、fc1 28672×5376、fc2 5376×14336）与 FL2VA int8 基座的 `weight` 形状逐一匹配
- [x] **ComfyUI 已识别**：`LoraLoaderBypassModelOnly.lora_name` 列表实查含 `H3\H3视频编辑\viggle_remake_swap_comfyui.safetensors` 与 `…edit_comfyui.safetensors`
- [ ] **实跑出片**：待验收（需在 ComfyUI 重启后跑一条短片确认显存与 LoRA 匹配）

## 6. 基座故障记录：FL2VA zs05 int8 的 `comfy_quant` 全零（2026-11-09）

**症状**

`BSAI_SolH3_Loader` 加载 `H3\minimax_h3_fl2va_zs05_int8_convrot.safetensors` 时报：

```
json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
  comfy/ops.py:1371 in _load_quantized_module
      layer_conf = json.loads(layer_conf.numpy().tobytes())
```

**根因**

`_load_quantized_module` 从 state dict 里取同名 `<layer>.comfy_quant` 张量（U8，存一段 JSON 描述量化格式）。
该文件 250 个 `comfy_quant` 张量**内容全为 0x00**（长度 71/72 字节，恰好是正常 JSON 的字节数），所以 `json.loads` 必然失败。
同目录能正常加载的 `minimax_h3_hybrid_fl2va_ref2va_b25-49-int8.safetensors`，同位置是：

```
{"format": "int8_tensorwise", "convrot": true, "convrot_groupsize": 256}
```

即：这是导出侧写坏了配置张量，不是工作流接错、也不是下载残缺。

**修复**

`comfy_quant` 张量长度与正确 JSON 完全相等，因此可原地重写数据区、不改 header、不动 31.7 GB 权重：

| 层类 | 数量 | 原长度 | 回写内容 | 依据 |
|---|---|---|---|---|
| attn（qkv_proj / out_proj）、mlp（fc1 / fc2） | 200 | 72 | `{"format":"int8_tensorwise","convrot":true,"convrot_groupsize":256}` | 与 hybrid 同位置逐字一致；in_features 5376/7168/14336 均整除 256 |
| adaln_proj.linear | 50 | 71 | 同上但 `convrot_groupsize: 64` | in_features=2688 不整除 256/512；原长度 71 说明 groupsize 是两位数（16/32/64），取最大可行的 64 |

回写脚本：`.sessions/38451884652146434/agents/m_0cw3jPoYAP6/fix_quant_conf.py`（250/250 处写后 JSON 校验通过，文件大小不变）。

**但这份 31.7 GB 文件在本机仍不可用**

它是**全量 int8**（50 层 attn/mlp + 50 层 adaln 全部 I8，共 1035 张量），权重规模 ~32 GB，而本机 5090 Laptop 只有 23.9 GB VRAM 且启动参数带 `--disable-dynamic-vram`：要么 OOM，要么整段 CPU offload 让 6 步慢到不可用。
可作为对照：hybrid 版 19.53 GB（adaln 走 BF16/F16，int8 只 200 层），是这台机器实际的可用档位。

**结论：本机跑 Viggle 用 hybrid 基座**

`H3\minimax_h3_hybrid_fl2va_ref2va_b25-49-int8.safetensors` 与两个 Viggle LoRA 的层名比对：**202 / 202 层全命中**（LoRA 目标层即 blocks.N.attn.qkv_proj / out_proj、blocks.N.mlp.fc1 / fc2、final_layer.video_out，不含 adaln、不含 ref2va 专属层），维度也一致。故 LoRA 可完整挂载，不会空打。
配套视频 VAE 用 `minimax_h3_sol_vae_fp16.safetensors`（与 hybrid 同档位原配）。

对应工作流：`BSAI第077期\…-ViggleRemake6步-hybrid基座-v14.346.json`。

## 7. 提示词硬约束：必须保留 `@视频N`

第 36 档（连同第 33 / 35 档）建立替换计划时，靠 `_RECAST_VIDEO_TAG_RE = <Video N>` 在**资产库解析之后**的分镜 prompt 里找源视频标签：

```
用户 prompt 里的 @视频1  →（_resolve_asset_library_refs）→  <Video 1>  →（_RECAST_VIDEO_TAG_RE）→ 命中
```

所以：

- 分镜 prompt 里**必须**出现 `@视频N`（资产库 Videos 位要有对应 index 的视频），否则 `_viggle_build_plan` 返回 None，本档直接抛 RuntimeError 中止（**不会**回退普通渲染，回退会带 lip_audio 把单段拉到 200s 级再 OOM）。
- 把用户指令改写成官方六段描述式时，**不能**把 `@视频1` 全部改写成“原视频”三个字——正文里要同时出现 `@视频N` 与 `@图N`。正确写法示例：

  ```
  summary：目标视频是 @视频1 改写后的成片：@视频1 里那位人物换成 @图1 里的同一个人，其余一切与 @视频1 逐帧一致。
  ```

- 送进 TE 之前 `_viggle_prompt()` 会再把 `<Video N>` 摘成「原视频」，所以模型正文里不会出现尖括号标签，用户能读到的仍是通顺描述。
- 最终的分段计划以源片时长现算：42.5s → 5 段 ×226 帧（不需前端改成 5 个 clip，后端会自动补齐缺少的 CLIP）；面板上仍显示 3 段 15s 属正常。

**v14.348 起有后端兜底**：`_viggle_build_plan` 若在分镜里找不到 `<Video N>`，会按资产库第 1 个视频补一个 `<Video N>` 前缀再重试一次，并打印

```
[H3 Viggle] ⚠️ 分镜提示词里没有 @视频N，已按资产库第 1 个视频（896x540.mp4）兜底重试；建议在分镜提示词里显式写 @视频1
```

即提示词漏标签不再硬中止，但这只是保底；显式写 `@视频N` 才是正解（兜底只认第 1 个视频，多视频场景会取错）。

## 8. 第 2 段崩 + 换脸不彻底（v14.349 / v14.350 修复）

### 8.1 第 2 段必崩：motion context 相位失配

**症状**

```
RuntimeError: MiniMax H3 Motion Context RAM: previous latent/context length phase mismatch (tail starts at cycle 2).
  extender.py extend → motion.apply(...)
  motion_context_ram.py apply → _video_tail_from_latent → raise
```

第 1 段正常出片，进入第 2 段即崩。

**根因**

本档是 **0 重叠、源片整段作 cond video**：段与段之间不是连续时间轴，上一段的尾巴对本段毫无意义。但派生出来的工作流里 `context_length = 39`（不是 0），且三个 clip 的 `context_enabled = True`，于是第 2 段命中 `i > 0 and context_enabled and previous_proxy is not None`，把上一段尾部 39 帧当 keyframe 注入；39 不在 `17n+5` 网格上，`motion_context_ram` 按 context_length 切尾与本段 226 帧相位对不上 → 抛错。

**修复（两处，双保险）**

| 位置 | 改动 |
|---|---|
| 工作流 `node 250` | `context_length` 39 → **0**（`widgets_values[8]` 与 `widgets_values_named["context_length"]` 双写） |
| 工作流 clips | 三个 clip `context_enabled` True → **False** |
| 代码 v14.349 `extend()` | `if i > 0 and context_enabled and previous_proxy is not None` 追加 `and not _viggle_this` —— Viggle 档**硬跳** motion context，无论前端怎么配 |

### 8.2 换脸不彻底（脸还是原片那张）

**根因 1（最关键）：纪律块里的身份约束是空指令。**

`_VIGGLE_DISCIPLINE` 原文写的是「…必须与 **@图N** 参考图完全一致…」。这段纪律是**后端拼在用户正文前面**直接送 TE 的，而 `@图N` 早在资产库解析阶段就已变成 `<Picture 1>`，纪律块里的 `@图N` 是**纯字面三个字符**。TE 看到「必须与 @图N 参考图完全一致」，根本不知道指哪张图 —— 约束等于没有。

**根因 2：纪律块把"保持原片"放在最前且篇幅最长。** 模型读到的第一优先级是"逐帧保持原片"，第二优先级才是"换人"，6 步全噪下它会选择照抄源视频那张脸。

**修复（v14.349 代码 + v14.350 工作流）**

1. `_viggle_prompt()` 新增 `{refs}` 实指替换：扫正文里的 `<Picture N>`，把纪律块中的占位换成 **`参考图 <Picture 1>`**；正文没有图片标签时退化为「参考图」。
2. `_VIGGLE_DISCIPLINE` 重写：人脸列为**最高优先级、不得妥协**，并逐部位点名 —— 脸型轮廓 / 额头 / 眉毛 / 眼睛形状与眼神 / 鼻梁鼻头 / 嘴唇 / 下巴 / 肤色质感 / 发型发色 / 体型 / 整套服装鞋履配饰；明确「**不得沿用原片人物的任何五官特征**，旧脸、旧发型、旧服装、旧配饰一律不得残留」，并覆盖「人脸很小、侧脸、被头发或手遮挡、背对镜头后又转回来」以及「不允许两张脸来回漂移」。
3. 工作流 v14.350：六段式正文补 `detailed_description` 的**文本外貌描述**（黑色高马尾＋几缕碎发、杏眼内双、细长眼型、淡粉薄唇、鹅蛋脸白肤、白色无袖拉链短上衣配黑红条纹饰边、白百褶短裙＋黑腰带、白及膝长袜＋白长手套＋黑高跟短靴、银色几何耳环），文本通道与图像通道双约束，并写明「整部片始终是同一个人、这一张脸，不允许中途换脸」。

**还能再提高相似度的开关**：`node 250` 的 `megapixels` 从 **1 提到 2**。1920x1088 在 `megapixels=1` 下被压成 960x544（日志 `声明输出尺寸: 一采 960x544` 即此），提到 2 后约 1360x768，脸部像素翻倍；代价是每段耗时约翻倍。

对应工作流：`BSAI第077期\…-@视频1换@图1-ViggleRemake6步-hybrid基座-v14.350.json`（context 已归零、提示词含外貌描述，v14.349 后端配套）。

## 9. 脸换不掉的真凶：参考图根本没进 conditioning（v14.351）

**症状**：出片一切正常（动作、背景、口型都对），唯独脸还是原片那位。日志里没有任何报错，只有两行容易被忽略的提示：

```
[H3 Extender] clip[0] ref plan: 0 assets (strict per-clip, global refs excluded), slots=[]
[H3 Extender]   ref_items=0, ref_blocks=0, active_picture_slots=[]
[H3 Extender]   WARNING: no ref_blocks, conditioning has NO minimax_refs!
```

**根因**：参考图的挂载是**按分镜各自解析**的 —— `clip_ref_plans` 只看**该 clip 自己的 prompt** 里的 `@图N`，全局提示词（`global_prompt`）里的 `@图1` 被"严格隔离"策略**故意排除**。

于是只要把提示词写在**全局提示词**里，分镜 prompt 为空，本 clip 的 refs 就是 0 —— 模型从头到尾**一张参考图都没看到**。这时候提示词写得再细也没用，脸必然照抄源视频。也解释了为什么"其他都对、只有脸不对"：结构/动作由 cond video 与文本纪律控制，身份只靠参考图。

**修复（v14.351，通用路径）**：分镜自己**一张图都没点名**、而全局提示词点名了时，继承全局的图片顺序给该 clip，并：

1. `_slot_refs` 填上对应 asset tensor → `minimax_refs` 块恢复；
2. 正文前置 `<Picture N>` 标签 → TE 的 `text_token_tags` 有东西可绑，`_viggle_prompt` 的纪律块也能实指到图；
3. 日志打 `clip[i] v14.351 分镜未点名参考图 -> 继承全局 N 张`，以及 `ref plan: … 已继承全局`。

只在"分镜完全没点名"时继承，多场景各点各图的既有行为不受影响。

**日志自检**：第 36 档正常跑起来，`ref plan` 必须是 `1 assets … slots=[1]`（或更多），且**不能**再出现 `WARNING: no ref_blocks`。若还是 0，说明资产库 Images 位没图或 `@图N` 编号超出资产库条目数。

## 10. 工作流该长什么样（V15 定型）

排查 v14.350 时发现的实际形态很典型，值得记下来：

- `clips_json` 里只有 **1 个 clip，而且 prompt 是空字符串**；
- 唯一有内容的是 **node 75（分镜脚本）**，它经 link 709 接到 `250.prompt_source`；
- 后端把 `prompt_source` **整段当作全局提示词**（没有 `[分镜N]` 标记时），而参考图只按 **per-clip** 的 `@图N` 分配 → `ref plan: 0 assets` → `no minimax_refs` → 脸换不掉。

所以第 36 档的工作流必须满足：

| 要点 | 做法 |
|---|---|
| 分镜提示词落在 clip 上 | `clips_json` 每个 clip 的 `prompt` 都要含 `@视频1` 与 `@图1`（V15 写了 3 段） |
| node 75 的写法 | 用 `[分镜1]` / `[分镜2]` / `[分镜3]` 分段，**第一个标记必须在最前面**，这样全局部分为空，后端不会把它当全局提示词；前端也会按 `[分镜N]` 重建 CLIP，与 clips_json 双保险 |
| 外部覆盖口 | `clip_prompt_1..12`（node 283 / 330 等）留空；非空会覆盖对应 clip 的 prompt |
| context | `context_length = 0`，clips 的 `context_enabled = False`（0 重叠不续接） |

V15 实测（离线全链路）：`node75 [分镜1] 在位置 0 → global_prompt = ''`；三个 clip 正文均含 `<Picture 1>` → 每段 ref plan 应为 1 assets；补齐段沿用首段模板（含 `@图1`）；计划 `42.50s → 5 段（226/226/226/226/124）`。

## 11. 参考图进去了、脸还是原片那张：源片 cond 全程没松手（v14.352）

**实测现象**（V15 第一次实跑，`ref plan: 1 assets`、`参考图 2 个`、`no ref_blocks` 已消失）：

- 第 8 帧的脸已经接近参考图（高马尾、淡妆、鹅蛋脸、白拉链上衣、白手套、银色耳环全对上）；
- 3 秒后脸变回**原片那个浓妆红唇的人**，中途来回漂。

即"服装/发型换掉了、脸换不掉"——参考图通道确实是通的，但身份没压住。

**根因**：第 36 档把源片整段作 `cond video`，全噪 6 步每一步都带着它。而官方 Viggle 有一个我们漏掉的机制：

```
RemakeKeyframeUntil: σ < keyframe_until(0.9) 时
   keyframes=None, layout=None,
   cond_video_latents=[参考图的 latent]      ← 源片在这一步彻底退出
```

也就是**最后两步必须让源片撒手**，只剩参考图 + 已生成的 x 继续去噪，脸才会被拉到参考图那位。全程带着源片时，模型每步都在复刻源片像素，脸必然回原样。

**实现（v14.352）**：`_ff_viggle_release_source_cond()` 给采样模型挂 `DIFFUSION_MODEL` wrapper，σ<until 时把 `cond_video_latents` 换成 `refs` 的 latent、`layout`/`keyframes` 置空。swap 曲线 `1.0 / 0.9905 / 0.9652 / 0.9231 / 0.8 / 0.6316 / 0.0`，`until=0.9` 即最后两步脱离源片，与官方默认一致。

- 开关：`BSAI_H3_VIGGLE_RELEASE_COND=0` 关掉；
- 阈值：`BSAI_H3_VIGGLE_RELEASE_UNTIL`（默认 0.9；想更彻底可试 0.93，即最后三步脱开源片）；
- 日志确认：`[H3 Viggle] v14.352 源片 cond 早停释放生效: σ=0.8000 < 0.9 → cond 只留 N 张参考图`。

**注意**：官方 pins（把参考图钉成输出帧的 keyframe）不适用于本档素材——官方要求参考图是"源片某帧在图像编辑器里涂改后的图"，而我们的 `@图1` 是白底多视图设定板，钉进画面会把白背景带进构图。所以只实现"早停释放"这一半。




## 12. 人脸还是不像：步数可调 + 出片后换脸工序（v14.354）

**先说结论**：Viggle 这条通道换的是"装"，换不了"骨相"。四轮实跑（v14.350 → V15 → v14.352 → v14.353）之后，服装/发型/白手套/耳环/白肤全部到位，唯独脸收敛到"一个好看的通用脸"，不是 `@图1` 那位。原因是 LoRA 的 6 步蒸馏：前四步受源片 cond 主导（复刻源片像素），身份窗口只有最后两步，信息量不够。提示词写到"人脸最高优先级"也补不上通道带宽。

所以补两件事：**步数可调**（多给几步去噪）+ **出片后逐帧换脸**（确定性到位）。

### 12.1 步数可调（v14.354）

**原状是个坑**：`_sigmas()` 在 viggle 档直接返回官方 7 点 knots（`1.0 / 0.990476 / 0.965243 / 0.923077 / 0.8 / 0.631579 / 0.0`），采样步数由 sigma 表长度决定，恒为 6 —— **前端 steps 填 8 完全无效**，日志仍显示 6 步。

**改法**：`_viggle_resample_sigmas(knots, want_steps)`

- `want == 6`：原样返回官方表（默认行为一分不变）；
- `want < 6`：只用原始 knots 的子集（保首尾、等间隔取），绝不引入模型没见过的 σ；
- `want > 6`：在相邻 knots 之间对 σ 做分段线性插值细分，首尾钉死，强制严格单调递减（重复 σ 会让采样器空转）。

实测输出（swap 曲线）：

| 步数 | σ 表 |
|---|---|
| 4 | 1.0 / 0.9652 / 0.9231 / 0.8 / 0.0 |
| 6（官方） | 1.0 / 0.9905 / 0.9652 / 0.9231 / 0.8 / 0.6316 / 0.0 |
| 8 | 1.0 / 0.9929 / 0.9779 / 0.9547 / 0.9231 / 0.8308 / 0.7158 / 0.4737 / 0.0 |
| 10 | 1.0 / 0.9943 / 0.9854 / 0.9703 / 0.9484 / 0.9231 / 0.8492 / 0.7663 / 0.6653 / 0.3789 / 0.0 |
| 16 | 逐段插值到 17 点，仍单调递减到 0 |

**怎么开**：UI 里 node 250 的 `steps` 直接填 8 / 10 / 16；或环境变量 `BSAI_H3_VIGGLE_STEPS=8`（优先级更高，可临时试某个步数而不用改工作流）。

**代价与风险（必须实测再定）**：耗时按 `步数×单步 ≈ 62s` 线性涨（8 步 ≈ 8 分钟/段，10 步 ≈ 10 分钟/段，5 段就是 40–50 分钟）。更重要的是官方 LoRA 只在这 6 个 σ 点上蒸馏过，细分出来的 0.8308 / 0.7158 这类中间 σ 模型没见过 —— **可能更细，也可能出塑料皮肤/五官发糊**。所以默认保持 6。建议先只用 8 步跑 1 段对比，别一把梭整片。

### 12.2 出片后换脸工序（默认关，开就全自动）

**为什么走这条**：本机已有完整换脸栈（`insightface` + `buffalo_l` + `inswapper_128.onnx` / `reswapper_256.onnx`），逐帧换脸只替换身份纹理，**动作、口型、背景、原声零损失**，比在 6 步采样里求身份稳得多。

**实现**：

- `tools/viggle_faceswap.py`：ffmpeg 抽帧 → insightface 检测最大脸 → inswapper 换脸（检测失败帧原样保留，含 0.25 低阈值重试）→ 重新编码 + 复制原音频。
- `extender.py` 里 `_ff_viggle_faceswap_clip()` 在 clip 落盘后调用子进程跑（与渲染进程隔离，换脸崩了不影响渲染），产物 `<原名>_faceswap.mp4` 回写进 `clip_videos`，下游拿到的是换脸版。

**开关与参数（v14.355 起有 UI 控件，不用再改环境变量）**：

node 250 参数面板**最下方**（`director_fast_target_mp` / `refine_sigmas` 之后）：

| widget | 类型 | 默认 | 作用 |
|---|---|---|---|
| `viggle_faceswap` | 布尔 | **false（关）** | 开 = 每段出片后逐帧换脸；关 = 纯 Viggle 出片 |
| `viggle_faceswap_model` | 128 / 256 | **128** | 128 约 3s/帧、大特写偏软；256 约 4.5s/帧、更锐 |

环境变量仍保留作强制/批量兜底，优先级**高于** UI：

| 环境变量 | 作用 | 默认 |
|---|---|---|
| `BSAI_H3_VIGGLE_FACESWAP` | `1` 强制打开（覆盖 UI 的关闭） | 关 |
| `BSAI_H3_VIGGLE_FACESWAP_MODEL` | 覆盖 UI 的模型选择 | 128 |
| `BSAI_H3_VIGGLE_FACESWAP_REF` | 参考图路径；不设则取资产库第 1 张图 | 自动 |

**前端兼容（加 widget 时必须同步改，否则静默改坏配置）**：`web/extender.js` 的 `H3LegacyCompat` 用 widgets_values **长度**判断布局版本（`KEYS` / `DEFAULTS` / `BOOLS` / `detect()` / `mapTo()`）。v14.355 已补进 73 键（`CUR73`）与 72 键（`CUR72`）。若只加后端 widget 而漏这几处，73 键会被当成"未知旧布局"，`mapTo` 走老纪元分支：只保留前 33 项、`out` 固定 71 位、其余全部回退 DEFAULTS —— 表现为加载工作流后 megapixels 变 0、render_pipeline 被打回默认档、Director 参数全丢。

**实测数据（2026-11-10 复测，同一参考图、同一组帧，960×544 / CPU）**：

| 模型 | 身份相似度 | 速度 | 单段耗时 |
|---|---|---|---|
| **inswapper_128（默认）** | **0.842**（clip1 全段 0.792，175/187 帧 ≥0.6） | ~3.2–3.3 s/帧 | 12–13 分钟 |
| reswapper_128 | 0.562 | ~3 s/帧 | — |
| reswapper_256 | 0.495（clip1 全段 0.449，**0/187 帧 ≥0.6**） | ~4.5 s/帧 | 17 分钟 |
| inswapper_128.fp16 | 0.122（模型本身无效） | — | — |
| hyperswap_1a/1b/1c_256 | 装载即 `AssertionError`，不可用 | — | — |

**结论：默认必须用 128。** 256 只在"锐度"上占优，身份相似度明显更差——这正是第一轮"脸还是原片那张"的主因。128 在大特写帧唇部会轻微偏暗（未到发黑），可接受。

**v2 脚本（2026-11-10）**：跨帧跟踪 / 误检闸门 / 多视角参考 / CodeFormer（默认关）/ 唇色迁移，五道工序全部落在 `tools/viggle_faceswap.py`，开关与数据见 `验收报告-第36档-换脸版-第二轮-20261110.md`。

**已知瑕疵（用之前要知道）**：

1. 真背身帧（如 clip4 开头 0–1s、clip1 甩头段）保留原脸，播放时会"闪回"。v2 会主动拒绝"后脑勺被误检成脸"的帧，这是正确行为。
2. 张嘴帧的唇形沿用源片（唇红已迁移到参考色），大张嘴时仍偏厚。
3. |yaw|>65° 的帧轮廓边缘有轻微接缝，用 α=0.75 混合压住。
4. 换脸工序是纯 CPU，每段多 12–17 分钟，默认关闭就是这个原因。
