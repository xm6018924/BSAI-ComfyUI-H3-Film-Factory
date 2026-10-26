# CHANGELOG ｜ 更新日志

All notable changes, bilingual. 所有重要版本双语说明。

---

## 🚨 铁律 / IRON RULE

**未经用户验收合格,绝不动 git push(本地 commit 也先询问)。**
**Never push to git without explicit user acceptance. Ask before local commit too.**

这条规则在刘百声的所有项目中持续生效,直到被显式撤销。
This rule applies across all 刘百声 projects until explicitly revoked.

---

### 📦 示例工作流 / Example Workflow (2026-10-26) — 一镜到底 MV · accel-selector 组合 · 4090 · 自定义 8+4 档（修复「界面设 8+4 实跑 1 采 6 步」）/ Example workflow: one-shot MV + accel-selector combo on 4090 with a custom 8+4 tier (fixes "UI says 8+4, run does 6 steps")

**实测：界面把一采设 8 步 / 二采设 4 步，实际只跑一采 6 步、二采被完全跳过。** 根因是两层静默覆盖，与模型/显存无关：`render_pipeline` 非默认档会在 `extender.py` 末尾无条件改写 `steps / refine_steps / tile_count / refine_denoise`，而 `one_shot_sampling="单采无缝 (推荐)"` 会让一镜到底模式整段跳过二采。
**/ Measured: the UI was set to 8 first-pass + 4 refine steps, but only 6 first-pass steps ran and the refine pass was skipped entirely. Root cause is two layers of silent override, unrelated to model or VRAM.**

- **第 1 层覆盖（档位改写步数）：** `render_pipeline` 只有 `Sol-H3 Self-Lift 双采 (默认)` 不会进入 `extender.py` 的档位分支（`if _rp_mode and _rp_mode != "Sol-H3 Self-Lift 双采 (默认)"`）；选其它档，末尾一律硬改写采样参数，例如「4K直出 秘制酱料」→ `steps, refine_steps, tile_count, refine_denoise = 6, 3, 4, 0.45`，用户的 8+4 被无声改写为 6+3。** / Override layer 1: only the default tier skips the tier branch; every other tier hard-rewrites steps (e.g. "4K直出 秘制酱料" forces 6+3).**
- **第 2 层覆盖（一镜到底单采跳过二采）：** `one_shot_mode="on (一镜到底)"` + `one_shot_sampling="单采无缝 (推荐)"` → `one_shot_single_pass=True` → `_eff_refine=False`，二采整段不跑。** / Override layer 2: one-shot + "单采无缝 (推荐)" sets `_eff_refine=False` and skips the whole refine pass.**
- **本示例工作流的生效组合：** `render_pipeline="Sol-H3 Self-Lift 双采 (默认)"`（唯一不改写步数的档）+ `one_shot_sampling="双采高清 (接缝风险)"`（唯一让二采真跑的选项）+ `speed_preset="custom"` + `scheduler="beta"` + `sampler_name="euler"` + 一采 `steps=8` / 二采 `refine_steps=4` / `refine_denoise=0.45` / `refine_upscale_factor=2.0` / `tile_count=4` / shift 12/3。** / The combination that actually takes effect: default tier + dual-pass one-shot + custom speed preset.**
- **取舍说明（已知风险，非缺陷）：** 一镜到底 + 双采会有段间像素漂移（接缝风险），这正是 v14.185 单采档被设计出来规避的问题；本示例按用户明确要求选择「跑满二采」，接缝零漂移请改用「单采无缝 (推荐)」。** / Known trade-off: one-shot + dual-pass can drift at segment joins; that is exactly what the single-pass tier avoids.**
- **新增示例工作流：** `example_workflows/BSAI_H3_Film_Factory电影工厂-MV一镜到底版-accel-selector组合-4090-自定义8+4档.json`（103 节点 / 96 连线）。** / New example workflow added to `example_workflows/`.**
- **验证：** 按 `INPUT_TYPES` 实际 widget 顺序（90 项，`model/clip/vae` 为 forceInput 故数组偏移 3）逐项核对 `widgets_values` 数组与 `widgets_values_named` 字典 —— 两份副本一致率 **100%（68/68，0 处冲突）**，与已发布 5090 参照工作流同口径；按 `extender.py` 真实优先级逻辑仿真复算，一采 8 步 / 二采 4 步 / denoise 0.45 / `_eff_refine=True` / `honor_manual_steps=True` 全部命中。** / Verified: array and named widget maps agree 100% (68/68) against the plugin's real widget order; simulating the real override precedence yields 8 + 4 steps with refine enabled.**
- **缓存提示：** 旧的 6 步单采链缓存（`bsai_h3_chain_cache/chain_extender_250.json`，几何 60×34）与新配置期望的 120×68 不符，`requested_mismatch=True` 会自动清链重渲，不会复用旧 latent。** / Cache note: the stale 6-step single-pass chain cache does not match the new geometry and is auto-cleared.**

---

### v14.213 (2026-10-26) — 修「渲染管道下拉看不到第 13 档」：前端 `web/extender.js` 的 `cycle`/`cycleLabels` 漏了新档 / Fix the missing 13th render-pipeline tier in the frontend dropdown

**实测（用户 2026-10-26 报）：后端 `/object_info/BSAIH3FilmFactory` 的 `render_pipeline` 已返回 13 项（含第13档），但节点上的 Pipeline 下拉只画 12 项（英文名）。** **/ Measured: the backend already returns 13 tiers, but the node's Pipeline dropdown rendered only 12.**

- **根因：** 该节点的 Pipeline 下拉是插件**自定义下拉**（`web/extender.js` 中 `render_pipeline` 表项里的 `cycle`（值=中文）/ `cycleLabels`（显示=英文）两份**硬编码列表**），**并非** ComfyUI 原生 combo。v14.211 只往 `extender.py` 的 INPUT_TYPES 追加了第13档，**漏改这两份前端列表**，于是下拉仍旧 12 项。** / Root cause: the dropdown is a custom widget driven by two hardcoded lists (`cycle`/`cycleLabels`) in `web/extender.js`; v14.211 only appended the tier to the Python INPUT_TYPES and missed these.**
- **修复：** `cycle` 追加 `"FastH3 Omni × SelfLift 超分"`（与 Python 端值逐字一致），`cycleLabels` 追加 `"FastH3 Omni x SelfLift Upscale"`。** / Fix: append the tier to both lists.**
- **验证：** `node --check web/extender.js` PASS；两列表末项分别为 `FastH3 Omni × SelfLift 超分` / `FastH3 Omni x SelfLift Upscale`；后端 API 亦为 13 项。** / Verified: node --check PASS; both lists end with the new tier; backend returns 13.**
- **约定（写进规矩）：** 今后新增 `render_pipeline` 档位**必须同时改三处**：① `extender.py` INPUT_TYPES 选项；② `extender.py` 档位分支（`elif _rp_mode == ...`）；③ `web/extender.js` 的 `cycle` + `cycleLabels`。** / Convention: adding a tier requires all three edits.**

---

### v14.212 (2026-10-26) — 修 Omni 一采「保底」竖版误放大：判据由单边改面积，竖版 544×960 不再被拉成 960×1696（每步 350s → 恢复健康区） / Fix the Omni first-pass "floor" upscaling portrait clips: switch the test from one-sided to area-based

**实测（用户 2026-10-26 报）：竖版直播带货 clip，请求 544×960，一采却被"保底"到 960×1696（1.63MP、latent ≈2.7M tokens），每步 350s、8 步 46 分钟。** **/ Measured: a portrait clip requested 544×960 got "floored" to 960×1696 (~2.7M tokens), 350s/step.**

- **根因：** v14.171 的保底分支用单边判据 `resolved_width < 960 or resolved_height < 544`，再 `_s = max(960/宽, 544/高)`。竖版 544×960 的**面积 522,240 恰好等于健康区上限**（960×544 = 522,240），本应原样不动，却因 `宽 544 < 960` 命中 → 按宽度凑到 960、高度等比跟到 1696 → 面积暴涨 3.1×。** / Root cause: the floor test was one-sided; portrait 544×960 has area exactly equal to the health cap but hit the `width < 960` branch and got scaled to 960×1696.**
- **修复：** 判据改为 **面积**（`elif _area < _omni_max_px:`），等比缩放到健康区面积；面积达标即不动（竖版/横版都对），只有真正偏小的请求才被提到健康区。** / Fix: test by area; scale to the health-cap area; anything at/above the cap is left untouched.**
- **验证：** `extender.py` py_compile PASS；竖版 544×960 → 不触发保底（面积相等），横版 960×544 → 同样不动，480×480 → 提到约 0.52MP。** / Verified: py_compile PASS.**

---

### v14.211 (2026-10-26) — 渲染管道新增档「FastH3 Omni × SelfLift 超分」：落地 B站《FastH3 Omni 全流程教学》配方 / New render-pipeline tier "FastH3 Omni × SelfLift upscale": the Bilibili FastH3 Omni recipe

**来源：B站《FastH3 Omni 全流程教学:90秒直出10s高清视频、告别塑料假脸与全能参考实测》(BV1rtnQ6qErJ)。配方 = FastH3 Omni 8 步蒸馏 + SelfLift 渐进式超分 + sol-attn 替代 VSA。** **/ Source: Bilibili BV1rtnQ6qErJ (FastH3 Omni + SelfLift progressive upscale + sol-attn over VSA).**

- **新增档位：** render_pipeline 新增第 13 档「FastH3 Omni × SelfLift 超分」—— 一采 4 步低分辨率(≈0.4x, 由 `refine_upscale_factor=2.5` 表达)搭骨架 → 3D latent 放大 → 二采 4 步高分辨率精修; 总 8 NFE 仍满足 Omni 8 步蒸馏契约; shift 12/3、denoise 1.0、euler、TST 开。** / New tier: 4-step ~0.4x skeleton → 3D latent upscale → 4-step hi-res refine (8 NFE total), shift 12/3, denoise 1.0, euler, TST on.**
- **与现有档⑨ 的区别：** 档⑨ 是"单采 8 步 + 一采钳制 960×544 + 外部超分兜底"; 本档改为**插件内自持的渐进双采**(免外部超分, 无二采漂移)。因此 `omni_8step_mode` 判定已排除本档, 不再用单采强制覆盖二采。** / Unlike tier 9 (single pass + external upscale), this tier does in-plugin progressive dual-pass; `omni_8step_mode` excludes it so the single-pass force does not clobber refine.**
- **注意力建议：** 视频实测把 VSA 换成 **sol-attn** 后画面瞬间清亮通透、速度不变(默认 VSA 偏暗偏闷)。切换需在**工作流层**把 `BlockSparseAttention(VSA)` 换成 Sol-Attn 节点——本档只改采样管道 + 打印提示。** / Prefer sol-attn over VSA (a workflow-level node swap; this tier only prints a hint).**
- **模型要求：** Loader 需换 `fasth3_omniref_8step_pruned_int8_convrot.safetensors`。** / Loader must use the Omni checkpoint.**
- **验证：** `extender.py` py_compile PASS。** / Verified: py_compile PASS.**

---

### v14.207 (2026-10-25) — 修二采 OOM 兜底的 shape mismatch 崩溃：keyframe 几何随 fallback 收缩 + fallback 非 OOM 异常不再打死整个 prompt / Fix the OOM-fallback shape-mismatch crash: keyframe geometry follows the fallback, and a non-OOM fallback error no longer kills the whole prompt

**实测（用户 2026-10-25 16:12 报错，`clip2`）：`RuntimeError: shape mismatch: value tensor of shape [51648, 96] cannot be broadcast to indexing result of shape [14928, 96]`（`comfy/ldm/minimax/model.py:576 all_video_rows[~img_update] = cond_video_rows`），1 小时 34 分的作业在二采兜底里直接失败。** **/ Measured: clip 2's refine OOM fallback crashed with a cond-row shape mismatch, killing a 1h34m job.**

- **根因：** `PackedLayout` 按**输入 x 的空间网格**给 keyframe cond 预留行数（`frame_rows` 来自 `latent_shapes`），而 `_cond_video_rows` 按 **keyframe latent 的实际尺寸** patchify。v14.162 已把 keyframe 放大到二采 68×120；v14.206 修好一采备份后，OOM fallback 第一次真正走到「用一采 34×60 重跑」，两者空间差 4 倍 → 预留 14928 行 vs 实际 51648 行。** / Root cause: layout reserves keyframe rows from the input grid while cond rows are patchified from the actual keyframe size; the now-working backup path reruns at 34×60 against 68×120 keyframes.**
- **修复：** fallback 走「原始备份 / 非分块」时，先把 `conditioning` 里的 keyframe latent trilinear 缩回 `_fb_use` 的空间尺寸再采样；分块重跑（仍是放大版）几何本来一致，不动。** / Fix: when the fallback reruns at first-pass size, keyframe latents are trilinear-resized to that grid before sampling.**
- **兜底失败不再穿出：** 原来的 `except torch.cuda.OutOfMemoryError` 只兜 OOM；fallback 内部抛其它异常会直接穿出这个 except 分支（同级 `except Exception` 接不住），把整个 prompt 打死。现在追加 `except Exception`：打印栈并退回一采 latent 让成片先落地，`InterruptProcessingException` 照常抛出（取消不受影响）。** / A non-OOM error inside the fallback now degrades to the first-pass latent instead of aborting the run; user interrupt still propagates.**
- **验证：** `extender.py` py_compile PASS；启动横幅 `v14.207 backend loaded`。** / Verified: py_compile PASS, banner v14.207.**
- **附带观察（非本次改动）：** 该工作流 `tiled_refine=False` + 1920×1088 二采 → 995k tokens 走 v14.148 dense 降级，实测 **601s/步**（clip1 二采 4 步 40 分钟，clip2 直接 OOM）。想正常用双采请开分块二采（`tiled_refine=True`, 4×128）或把二采倍率降到 x1.5。** / Note: without tiled refine, 995k tokens fall back to dense attention at 601s/step; enable tiled refine or reduce the refine factor.**

---

### v14.206 (2026-10-25) — 二采 latent 塌陷检测：自动回退一采 latent + 告警，杜绝静默灰片 / Refine latent-collapse guard: auto-rollback to first-pass latent + warning, no more silent gray clips

**实测（2026-10-25 灰片排查）：二采偶发把 latent 采成近似常数场——每通道空间 std 0.147、4×4 低通后 0.043，VAE 解码即灰雾/无画面；同机一采健康 latent 为 0.68~1.13。** **/ Measured: the refine pass occasionally collapses into a near-constant latent (per-channel spatial std 0.147, 4×4 low-pass 0.043), which decodes as gray; healthy first-pass latents measure 0.68-1.13.**

- **塌陷检测（`_sample_h3` 二采出口，v1.74b 几何对齐之前）：** 取二采视频 latent 的 8 个时间切片，计算每通道在 T/H/W 上的空间 std 中位数与 4×4 avg_pool 后的 std 中位数；两者同时 `< 0.30 / < 0.15` 即判塌陷。命中且有一采备份时换回一采 latent（随后由 v1.74b trilinear 对齐到链上几何），并 `_send_extender_warning` 推到节点状态栏；检测本身异常只打印、不打断渲染。健康段会打印 `v14.206 二采 latent 健康: 通道内std=...`，可据此复核阈值。** / Collapse detection samples 8 temporal slices, computes per-channel spatial std median and its 4×4 low-passed value; both under threshold = collapse → restore the first-pass latent (v1.74b then resizes to chain geometry) and warn on the node. Detection failures never interrupt rendering.**
- **修「备份从来没成功过」：** `comfy.nested_tensor.NestedTensor` 没有 `.clone()`，旧 `samples.clone() if hasattr(...)` 对 AV 双成员 latent 恒为 False → `_samples_pre_upscale` 一直是 `None`，OOM fallback 与本次塌陷回退都拿不到一采 latent。改为对 NestedTensor 逐成员 clone 重建。** / Fixed the dead backup: NestedTensor has no clone(), so the old hasattr guard always yielded None for AV latents; now each member is cloned and re-wrapped.**
- **补「二次 OOM 只打印不回退」：** 二采 fallback 仍 OOM 时分支持续走放大后未去噪的 latent（灰片来源之一），现在真正赋值 `samples = _samples_pre_upscale`。** / The double-OOM path now actually restores the first-pass latent instead of just printing that it did.**
- **验证：** `extender.py` py_compile PASS；启动横幅 `v14.206 backend loaded`。** / Verified: py_compile PASS, banner shows v14.206.**

---

### v14.202 (2026-10-25) — render_pipeline 新增「直播带货（全自动）」第 12 档 + 快捷条一键按钮；档内除分辨率外全部参数强制接管 / New all-in-one Live-Sell pipeline tier + one-click quick button; every parameter except resolution is forced

**用户诉求：把直播带货专用模式做成一键档——选中后所有参数按固定配方，手动设置全部无效。** **/ User asked for a one-click live-commerce tier that ignores manual settings.**

- **`extender.py` render_pipeline：** 追加第 12 档 `直播带货（全自动）`。配方 = v3 参考音频版工作流（v14.200 修复后）已验证参数：一采 12 步 + 二采 4 步（denoise 0.55）+ 3D latent upscaler x2.0 + 音频重绘 0.7（4 步时由 v14.196 自动改为锁定一采 12 步音频）+ shift 12/3 + TST tau 0.2 + 分块二采 4x128 + `audio_context_length=0` + euler/simple + denoise 1.0 + 输出 both / 预览开 / 一镜到底关。命中该档时 `speed_preset` 置 custom，手动改这些参数不会生效。** / New tier forces the verified 12+4 recipe; manual values are overwritten.**
- **分镜上下文强制：** 该档下 `clip1` 上下文保持开启，`clip2` 起一律 `context_enabled=False`（覆盖分镜脚本与 UI 勾选）；外部音频超长自动追加的延续 CLIP 也继承关闭状态。这一条直接对应 clip2 首帧拖影/马赛克的根因。** / Clip 2+ motion context is forced off, including auto-appended continuation clips.**
- **分辨率不锁：** `width/height/resolution_mode` 沿用工作流。锁 1920x1088 会把一采从 960x544 抬到 1920x1088（耗时约 4x），与"15 秒一小时内"的验收冲突。** / Resolution is intentionally left to the workflow; locking it would quadruple first-pass cost.**
- **`web/extender.js`：** 快捷条最左侧新增绿色「直播带货 / LiveSell 全自动」按钮：一键写入整套配方值 + 同步关闭 clip2+ 的 Context Reference 复选框 + 清缓存重绘；参数区下拉切到该档时按钮同步点亮。`render_pipeline` 快捷下拉菜单补全此前缺失的「直播配音高清」「QAD-v2-8步」并加入新档（cycle 12 项）。** / Added the one-click button and completed the 12-item pipeline dropdown.**
- **验证：** `extender.py` py_compile PASS；`extender.js` `node --check` PASS。** / Verified: py_compile + node --check pass.**

---

### v14.201 (2026-10-25) — QAD-v2-8步 新档（render_pipeline 第 11 档 + speed_preset 兼容）；VAERouter 加 NVFP4 Decoder 推荐映射 / FastH3-QAD-v2 8-step preset added; VAERouter NVFP4 decoder mapping documented

**依据一手视频（BV16onF6dEWf，UP「AI绘画KK」2026-10-20）：海螺 AI Lab 发布 FastH3-QAD-v2——量化感知蒸馏整套 NVFP4（BF16 118GB→30GB，质量不降反升），RTX 5090 5s 480P 全流程 12.6~14.8s，配套两款新 NVFP4 VAE 解码器（36层 1.29GB/33.63dB 高质量、8层 0.31GB 快 15 倍极速）。官方 V2 NVFP4 schedule 已确认：8 forwards、video shift 10 / audio shift 3。** **/ Based on BV16onF6dEWf: FastH3-QAD-v2 QAT 4-bit stack (118→30GB), RTX 5090 5s 480P 12.6-14.8s, new NVFP4 decoders (36L 1.29GB/33.63dB, 8L 0.31GB 15x faster). Official V2 schedule: 8 steps, shift 10/3.**

- **H3-Film-Factory `extender.py`：** render_pipeline 选项列表追加 `QAD-v2-8步`（第 11 档），tooltip ⑪说明（shift 10/3 为 QAD-v2 专属，区别于 Omni 12/3）；分支逻辑 `elif _rp_mode == "QAD-v2-8步"` → 8 步单采、denoise 1.0、refine_enable=False、shift_video=10.0/shift_audio=3.0、复用 Omni 一采钳制（≤960x544 健康区）+ upscale_final 超分兜底；`speed_preset == "QAD-v2-8步"` 兼容分支联动同一管道；启动横幅升 v14.201。需 Loader 换 QAD-v2 整套 NVFP4 模型 + BlockSparseAttention（VSA keep_percent=10），VAE 可选 36/8 层新解码器。** / Added QAD-v2-8步 to render_pipeline and speed_preset compat; single-pass 8-step distillation, shift 10/3, reuses Omni clamp + upscale fallback. Requires QAD-v2 NVFP4 stack in Loader.**
- **BSAI-ComfyUI-VAERouter：** README 新增「NVFP4 Decoder 推荐映射」双语章节（36层 1.29GB 高质量档 / 8层 0.31GB 极速档 / LightVAE-Lite 旧档兜底，配 QAD-v2-8步 食用最佳）；nodes.py docstring 同步；未动 INPUT_TYPES/widget 结构（保护旧工作流对齐）。** / VAERouter README + docstring document the 36L/8L NVFP4 decoder mapping; node structure untouched.**
- **示例工作流：** `BSAI_H3_Film_Factory电影工厂-QAD-v2-8步-P0双轨迹-v14.201.json`（基于直播带货 12+4 最新底版生成：render_pipeline=QAD-v2-8步、一采 steps=8、shift 10/3、单采无缝；68 widgets 结构对齐），已复制到 `user\default\workflows` 与插件 `example_workflows\` 两处。** / Example workflow generated from the latest 12+4 template (render_pipeline=QAD-v2-8步, steps 8, shift 10/3), copied to both workflow dirs.**
- **验证：** extender.py / VAERouter nodes.py py_compile PASS；ComfyUI `--quick-test-for-ci`（8193/8194）exit 0，`v14.201 backend loaded` 正常打印；工作流 JSON 回读校验通过。**QAD-v2 模型文件下载链接公开通道暂不可得（硬阻塞），等官方放链接后按 large-file-download 拉取。** **/ Verified: py_compile PASS, quick-test exit 0, workflow JSON re-read OK. QAD-v2 weights link still unavailable publicly (hard blocker).**

---

### v14.200 (2026-10-25) — 分块二采改为「取第 1 块音频」不再求平均；硬切段 trim=0；clip2 首帧拖影与台词串段归因 / tiled refine keeps tile-1 audio instead of averaging; hard-cut clips trim 0; clip2 head ghost and cross-clip speech attributed

**实测 clip2（`_clippv_250_1_947c29a0.mp4`，1920×1088/24fps）：前 12 帧 Laplacian 方差 84~95，第 11 帧起骤降 17~20；blockiness 1.13→1.33；首帧视觉=主播全景与蜡烛特写双曝。同批 clip1（无上下文）全程 35~42，无异常。** **/ Measured clip2: first 12 frames Laplacian 84-95, then 17-20; blockiness 1.13→1.33; frame 0 is a double exposure of the host wide shot and the candle close-up. clip1 (no context) stays 35-42 with no anomaly.**

- **首帧拖影根因：** clip2 prompt 是硬切（0-3s 蜡烛特写），但 `context_enabled=True` 给它注入了上一段尾部 39 帧 motion context。模型被要求"续接上一段"，只能在段头把主播全景渐变成蜡烛特写；`trim_frames=39` 只裁掉 1.625s，而这次渐变约 2s，剩下的过渡尾巴正好落在输出头 12 帧 → 重影/马赛克。与 v14.188 的 noise_mask 头部锁定无关（该锁定区全部落在被裁掉的 39 帧内）。 **/ Root cause: clip2 is hard cut but context_enabled injects 39 context frames; the model morphs the host shot into the candle shot over ~2s, and trim 39 (1.625s) leaves the morph tail in the first 12 output frames.**
- **trim=0 修正（`_sample_h3` 采样循环）：** 原来只在 `lip_audio` 模式下把"未应用 motion context"的段强制 `trim_frames=0`；ref_audio（参考音频版）关闭 context 时 trim 保持 `None`，join 会回退默认 22 帧（0.9s）把新段开头静默裁掉。改为 `if not _applied_ctx: trim_frames = 0`。 **/ Fix: trim is forced to 0 for every segment without motion context, not only lip_audio ones; otherwise join silently trims 22 frames.**
- **配音串段根因：** `audio_context_length=24` 把上一段生成的语音尾部当音频上下文注入，clip2 prompt 又写着"台词0:15.0起"，模型顺理成章继续/混入上一段台词 → 用户听到的"乱配/自己加配音稿"。官方《配音修复》示例工作流该项就是 `0`。 **/ Root cause: audio_context_length 24 injects the previous clip's generated speech and the prompt says "台词0:15.0起", so the model continues or blends the previous lines; the official voice-fix example uses 0.**
- **分块二采音频（取代 v14.199 的锁定方案）：** 音频 latent 无空间维度，每个空间块都给出完整音频预测，但相位互不一致；求平均即互相抵消（低频轰鸣/发闷/削波）。现在直接取第 1 块预测（`bsai_h3_spatial_tiles.py`），v14.199 的"分块即锁音频"随之删除 —— 音频可以照常参与二采重绘，不再被平均毁掉。 **/ Audio latents have no spatial extent; averaging per-tile predictions cancels their phases. Keep tile-1 audio instead, and drop v14.199's forced audio lock.**
- **验证：** py_compile PASS；待用户重跑 clip2 验收（日志应出现 `v14.200`，且不再有 `v14.199 分块二采音频锁定`）。 **/ Verified by py_compile; awaiting a rerun of clip2.**

---

### v14.199 (2026-10-24) — 根因：分块二采把 4 块独立预测的音频 latent 求平均 → 低频轰鸣/发闷/削波（12 步也救不回）/ root cause: tiled refine averages 4 independently predicted audio latents → rumble, muffled mids, clipping (12 steps cannot fix it)

**实测成片（15.07s）vs 用户提供的参考音频（34.57s）：<200Hz 21.8% vs 5.4%；400-1000Hz 37.9% vs 16.9%；峰值 +2.2dBFS（削波 0.13%）vs -1.0dBFS；帧底噪 -78dB（无真实停顿）vs -200dB（有静音）。** **/ Measured on the delivered clip vs the user's reference: sub-200Hz 21.8% vs 5.4%, 400-1k 37.9% vs 16.9%, peak +2.2dBFS (clipped) vs -1.0, noise floor -78dB (no real pauses) vs -200dB.**

- **根因：** `bsai_h3_spatial_tiles._tiled_model_call`（L482）把每个空间块独立预测的音频 latent 直接求平均。4 块的空间上下文不同，音频预测相位互不一致，平均后在 latent 域就是抵消+糊化，解码后=低频轰鸣、中频发闷、完全没有静音；二采步数再高也只是把"平均后的错误音频"画得更干净。** / Root cause: tile merge averages per-tile audio predictions; differing spatial contexts give inconsistent phases, so the averaged latent decodes as rumble/mud with no silence.**
- **修复（`_sample_h3` 二采，L3503-3523）：** 只要二采走空间分块（`tiled_refine` 或 tokens>350k 自动分块），音频一律锁定（`audio_denoise→0.0`，`noise_mask` 音频=0），完整保留一采 12 步生成的音频；与用户的"音频参与重绘0.7"无关。全局模式（`refine_mem_mode=global`）不受影响；需要旧行为时设 `BSAI_H3_TILED_AUDIO_REDRAW=1`。**⚠️ 该锁定方案已被 v14.200 取代（改为保留第 1 块音频预测，不再求平均）。** **/ Fix, superseded by v14.200 (keep tile-1 audio instead of averaging).**
- **对照（参考音频里内嵌的原始工作流）：** 该"好音频"来自 `电影工厂真实皮肤组合\Minimax-h3_Singularity_ref2va_v2_int8.safetensors`、steps=4+FastH3 8步增强、`audio_context_length=0`、且**没有二采**。当前工作流用的是 `H3\minimax_h3_ref2va_int8_convrot.safetensors`、`audio_context_length=24`、二采音频重绘 0.7。若锁定后仍不达标，下一步按这两项 A/B。 **/ The reference's own embedded workflow used the Singularity v2 checkpoint, 4 steps + FastH3, audio_context_length=0, and no second pass; current uses a different checkpoint, audio_context 24, and a 0.7 audio redraw.**

---

### v14.198 (2026-10-24) — 首步耗时拆分诊断：定位一采 step1 的 1217s 花在 conds 还是首次前向 / first-step timing probe: split the 1217s first step into conds vs first forward

**实测一采 12 步 = 28:53：进度条 144.46s/it 是含首步的平均值，真实逐步为 step1=1217s、step2~12=45-48s。** **/ Pass 1 = 12 steps in 28:53; 144.46s/it is the average including step 1. Real per-step: step 1 = 1217s, steps 2-12 = 45-48s.**

- **探针（`_sample_h3`，仅一采挂一次 DIFFUSION_MODEL wrapper，采样结束即摘除）：** 首次前向入口打印"采样开始→前向"间隔（= process_conds/文本与参考编码），前向返回再打印前向耗时（含权重换页/op 编译）与首步合计。日志前缀 `v14.198 首步拆分`。 **/ Probe prints two timings around the first DIFFUSION_MODEL forward, then is removed from model_options after sampling.**
- 目的：区分"前置编码慢"与"首次前向慢"，再决定是缓存/预编码还是提高驻留/异步搬运。无行为变更，卸载失败不影响采样。 **/ Diagnostic only, no behavior change.**

---

### v14.197 (2026-10-24) — 段间接缝修复：音频按 motion-context 帧数精确重叠，原曲零缺口 + 口型同源 / seam fix: audio overlap now equals motion-context frames, so the song has no gap and lip-sync shares the same source

**用户实测 3 段成片：clip2 覆盖原曲 [13.55s, 24.18s]，clip3 从 25.8s 开始 —— 每个段间接缝原曲被跳过 ~1.6s，听感"音频断了一截"。** **/ Measured: clip2 covers song [13.55, 24.18], clip3 starts at 25.8 — every seam skips ~1.6s of the song.**

- **根因：** v14.178 把 `MOTION_CONTEXT_OVERLAP_SEC` 改成 0，但 motion context 仍占据段头部 `context_frames`(39 帧 = 1.625s) 的视频与音频行 —— 模型净输出 = 标称 − context。零重叠时输入缺上一段尾部 1.625s、输出又少 1.625s，且尾对齐注入使新帧音频整体前移 → 段间缺口 + 口型错位。 **/ Root cause: overlap was zeroed in v14.178, but motion context still occupies context_frames (39 = 1.625s) rows at the head; model net output = nominal − context. Zero overlap loses 1.625s on both input and output, and tail-aligned injection shifts new-frame audio.**
- **修复（`_split_lip_audio_by_clips`，新增 `context_frames` 入参）：** ctx_on 段的段头按 `context_frames/fps` 精确重叠，段长保持标称帧数 N，推进按净时长 N−overlap；解码混音跳过段头 overlap 后与原曲逐样本对齐。ctx_off 段保持零重叠全时长（行为不变）。 **/ Fix: ctx_on segments prepend exactly context_frames/fps of overlap, keep nominal length N, advance by N−overlap; mixer skips the overlap head so output stays sample-aligned with the song.**
- **验证：** ramp 信号仿真 4 组用例（3 段全 ctx_on / 3 段全 ctx_off / 混合开关 / 8 段压力）拼接后逐样本连续、0 跳变点；py_compile PASS。 **/ Verified by ramp-signal simulation: 4 cases, sample-continuous, zero discontinuities.**
- 说明：前段缓存缺失时 trim 会被强制为 0，该边界仍会多出 context 秒（既有异常，非本次引入）。 **/ Note: when the previous cache is missing, trim is 0 and that boundary duplicates the context span (pre-existing edge case).**

---

### v14.196 (2026-10-24) — 二采提速：音频保护不再把二采 4 步强制提升到 12 步（实测省 8 步 ≈ 43 分钟/片段）/ refine speed: audio guard no longer forces pass-2 steps 4→12 (saves 8 steps ≈ 43 min per clip)

**实测日志：** 一采 12 步 × ~45s/步（在可接受区间），二采被 v14.195 从 4 步提升到 12 步 × 324s/步 = 65 分钟，15 秒片段总耗时 >1 小时。 **/ Measured: pass 1 12×45s (acceptable), pass 2 was raised 4→12 by v14.195 → 12×324s = 65 min; >1h total for a 15s clip.**

- **改法：** v14.195 的"二采音频重绘步数下限 12"改为**锁定音频**——一采已按 12 步生成音频（v14.195 的音频生成保护保证），二采把 `refine_audio_denoise` 覆盖为 0.0 保留同一份音频，步数完全按用户设置执行。音频质量不变（不重绘就不会出现 4 步重画的低频轰鸣），二采少跑 8 步。 **/ The pass-2 audio step floor is replaced by locking the audio: pass 1 already generated it at 12 steps, so pass 2 keeps it (`refine_audio_denoise=0.0`) and runs the user's step count. Same audio quality, 8 fewer steps.**
- 保留：一采 <12 步自动提升（音频生成质量）、lip_audio 锁定模式二采不重绘、`BSAI_H3_AUDIO_QUALITY=0` 一键关闭全部自动行为（回退旧参数：二采重绘且 4→12）。 **/ Kept: pass-1 <12 auto-raise, lip-locked pass-2 no-redraw, env switch to restore old behavior.**

---

### v14.195 (2026-10-24) — 渲染环节音频质量修复（治本）：音频要么锁定保持原声，要么 ≥12 步生成/重绘；以参考音频（完美标准）为基准 / render-side audio quality fix (root cause): audio is either locked to the reference voice or generated/redrawn at ≥12 steps; user's reference audio is the acceptance standard

**用户否决 v14.194 后处理方案（"完全无效，要修的是电影工厂本身渲染声音的能力，不是渲染后再修复"），并给出完美声音基准 `ComfyUI\input\.ComfyUI_temp_gntqn_00001.mp3` 要求以其为标准。** **/ v14.194 post-processing was rejected (ineffective; must fix the render-side audio capability itself), with the provided perfect-audio reference as the acceptance standard.**

- **基准分析（完美音频 = 工作流参考音频/lip_audio 原声）：** 200-400Hz 占全频 **73.3%**（人声主体）、<200Hz 仅 3.6%、有真实停顿静音（min 200ms RMS=0.0000）—— **干净口播标准**。**/ The "perfect" audio IS the workflow reference audio (lip_audio original voice): 200-400Hz = 73.3% (voice), <200Hz = 3.6%, real pauses (min 200ms RMS=0).**
- **根因（对比 5 个历史渲染输出全部同症）：** 电影工厂渲染音频 100-200Hz 占 **45-60%**、全程无静音（min 200ms RMS 0.03-0.11）→ 恒定低频轰鸣。生成链：**① lip_audio 对口型模式** 一采音频=参考原声 latent 已锁定（干净）→ **二采 `refine_audio_denoise=0.7` 把干净参考 70% 重噪后仅 4 步重画**（官方音频下限 12 步，v14.183 已证 4 步重画崩音频）→ 低频轰鸣劣质品替换参考原声；**② 非 lip 模式**（ref_audio 条件配音）一采 <12 步生成音频同样劣化。 **/ Root cause (all 5 historical renders share it): ① lip-sync mode locks the clean reference into pass 1, then pass-2 audio redraw 0.7 re-noises 70% and redraws it in only 4 steps (official audio floor = 12) → rumble replaces the reference; ② non-lip voice mode generates audio in <12 pass-1 steps → same degradation.**
- **修复 A（extender.py `_sample_h3`，渲染环节，无参数端口变更）：** ① 检测到 AV 双成员 latent 的 **lip_audio 锁定**时，二采音频重绘自动保持锁定（`refine_audio_denoise` 覆盖为 0.0）→ **输出音轨=参考原声（即完美标准）**，日志说明；如确需重绘设 `BSAI_H3_LIP_AUDIO_REDRAW=1`（此时步数自动 ≥12）。② 音频重绘开启且二采步数 <12 → 自动提升到 12。③ 非 lip 音频生成模式一采 <12 → 自动提升到 12。④ `BSAI_H3_AUDIO_QUALITY=0` 一键关闭全部自动行为（回退旧参数）。 **/ Fix A (render side, no new ports): lip-locked mode keeps audio locked in pass 2 (output = reference voice = the perfect standard; env BSAI_H3_LIP_AUDIO_REDRAW=1 to force redraw with ≥12 steps); audio-redraw pass-2 steps <12 auto-raise to 12; non-lip voice generation pass-1 <12 auto-raise to 12; BSAI_H3_AUDIO_QUALITY=0 disables all auto behavior.**
- **修复 B（motion_context_disk.py 病态门控）：** v14.194 清洗函数加"病态门控"——仅在**恒定低频轰鸣**（100-250Hz 能量 >25% **且** 200ms 窗 min RMS>0.02 全程无静音）信号上生效；干净音频（参考原声/≥12 步配音，有停顿、低频正常）**原样通过，不改变音色与响度**（避免后处理破坏完美标准；重低音音乐/男低音有动态与停顿不会误判）。 **/ Fix B (dirty-audio gate): v14.194 cleanup now only runs on truly pathological constant-rumble signals; clean audio (reference voice / ≥12-step voice-over) passes through untouched so post-processing never alters the perfect standard.**
- **验证（本机无渲染条件，逻辑层全过）：** 渲染保护 13 项断言（lip 判定/一采提升/二采锁定/步数下限/环境变量开关）全过；门控 6 项断言（病态样本仍清洗、完美音频逐采样相等原样通过）全过；py_compile PASS。**渲染验收需用户用原工作流重渲染一版对比。** **/ Verified (logic-level, render needs user re-render): 13 render-guard assertions + 6 dirty-gate assertions + py_compile all pass.**
- 无参数/端口变更（延续用户既有约束）；未做任何 git 操作（铁律）。 / No param/port changes; no git ops (iron rule).

---

### v14.194 (2026-10-24) — 音频输出修复：去恒定低频轰鸣/底噪/失真，恢复正常音频输出 / audio output fix: remove constant low-frequency rumble / noise floor / distortion, restore normal audio output

**用户问题（h3_clip_250_1_1792842036.mp4，15s 单段）：** 电影工厂音频输出失真、噪音、低频杂音。**/ Reported issue (15s single-clip sample): distorted, noisy, low-frequency-rumble audio output.**

- **诊断（ffmpeg+手写 numpy 频谱，无 scipy）：** ① 100-200Hz 占全频能量 **59.5%**、<250Hz 占 90%+，50/100/150Hz 谐波串密集无规律（非单一工频）；② 低频噪声 **全程恒定**（200ms 窗 min RMS=0.042，0 静音帧），中段人声带(300-3000Hz)从 0.081 掉到 0.027 而低频带(100-250Hz)始终 0.11-0.14 → 噪声把人声盖在下面；③ 无削波（峰值 0.77）、无爆音（相邻跳变仅 1 处）、12-16kHz 仅 0.01% → **排除 AAC 编码/削波/段间拼接，源头在 H3 audio latent 解码输出，旧管线无任何滤波后处理**；④ 本次渲染参数：一采 **8 步**（<官方音频 12 步下限）+ 二采 4 步 + **音频参与重绘 0.7**（音频 latent 低步数重画）。 **/ Diagnosis: 100-200Hz = 59.5% of energy; constant LF noise floor (min 200ms RMS 0.042, zero silence frames); no clipping / clicks / high-freq noise → source is the audio-latent decode output, pipeline had zero audio post-processing; render used 8-step first pass + 0.7 audio redraw (below the official ≥12-step audio floor).**
- **修复（motion_context_disk.py）** `_clean_audio_waveform()` 接入音频解码漏斗 `_decode_audio_latent()`（单段/成对/逐CLIP/最终封装全部路径生效，纯 numpy CPU 秒级，环境变量 `BSAI_H3_AUDIO_CLEAN=0` 可关闭 A/B）：① 去 DC；② STFT 域低频轰鸣削减（≤50Hz -22dB → 150Hz -11.5dB → 200Hz -9dB → 350Hz 0dB，人声/音乐主体不动）；③ 语音带(300-3000Hz)噪声门（包络 p3 估底×2.2 阈值，停顿帧衰减 0.15，增益 ~0.13s 平滑防泵浦/爆音）；④ 目标 RMS 0.12 归一 + 峰值≤0.95 限幅。**实测该信号各频点无静音间隙（噪声估计≈中位数一半），逐 bin 谱减必吞人声 → 弃用谱减法。** **/ Fix: audio post-processing added at the decode funnel (all output paths), DC removal + LF-rumble cut + voice-band noise gate (restores pauses) + normalize/limiter; spectral subtraction was tested and rejected (dense speech, per-bin noise ≈ median/2 → eats voice).**
- **验证（h3_clip_250 样本 A/B）：** 静音 200ms min RMS **0.042→0.003**（停顿恢复静音）；低频(100-250)/人声(300-3000) RMS 比 **4.69→1.57**；100-200Hz 能量占比 **59.5%→28.9%**，400Hz+ 人声占比 **3.9%→23.8%**；峰值 0.62 无削波、无瞬态、立体声保留。**/ Verified on the reported sample: silence restored (0.042→0.003), LF/voice ratio 4.69→1.57, spectrum rebalanced to voice, no clipping, stereo preserved.**
- **缓存失效：** `decoded_mp4_version` 4 → **5**（2 处写入 + 1 处判定），旧 v4 blob（脏音频）自动重解码。 **/ Cache invalidation: decoded_mp4_version 4→5 so legacy dirty-audio blobs re-decode.**
- **二采音频重绘防护（extender.py，仅提示不改行为）：** 一采步数 <12 且 `refine_audio_denoise≥0.5` 时打印警告，提示改走『直播配音高清』（12+4+音频0.7）或锁定音频 —— v14.183 已验证 10 步+音频0.9 崩音频，勿重复低步数+重绘组合。 **/ Refine guard (warning only): prints when first-pass <12 steps with audio redraw ≥0.5, advising the 12+4+0.7 pipeline or locked audio.**
- **离线试听工具** `_bsai_fix\fix_mp4_audio.py`：对已渲染 mp4 应用同一清洗并重封装（仅 numpy，任意 python），无需重渲染即可试听修复效果（已对样本产出 `h3_clip_250_1_1792842036_audiofix.mp4`）。 **/ Offline tool fix_mp4_audio.py applies the same cleanup to any rendered mp4 (numpy-only), no re-render needed to preview the fix.**
- 无参数/端口变更（延续用户既有约束）；未做任何 git 操作（铁律）。 / No param/port changes; no git ops (iron rule).

---

---

### v14.193 (2026-10-24) — 视觉锚点覆盖升级：记录**全部可见视觉元素**（角色形象/外观/服装/服饰/发型/鞋帽/场景/道具/布景等），快照注入全部已建立状态 / visual anchor coverage upgrade: record ALL visible elements (character look/appearance/clothing/accessories/hairstyle/shoes & hats/scene/props/set dressing etc.), snapshot injects every established state

**用户确认口径（v14.193）：** 锚点记录必须包含所有可见视觉元素，而非只取分镜正文的收尾句子 —— v14.192 的"末尾 1~2 句"记录侧升级为**全量记录**。**/ Per user confirmation: anchors must cover every visible element, not just the tail sentences of the clip text — the v14.192 tail-only recording is upgraded to full coverage.**

- **自动记录** `_extract_visual_state()`：逐句保留分镜正文中所有非对白陈述句（对白/台词/旁白/音效行与引号对白句照旧剔除），保持原序；正文 ≤300 字符时**全量保留**（分镜正文通常在此范围内，即默认覆盖全部可见元素）；超预算时优先保留含可见视觉元素关键词（`_VISUAL_ELEMENT_KEYWORDS`，覆盖角色形象/外观/发型/服装/服饰/鞋帽/伤势/道具/场景/布景/天候光影等类别）的句子，再按原序补足，确保元素不因截断丢失。 **/ Auto-record: keeps every non-dialogue sentence of the clip text in order; within 300 chars the whole text is kept (covers all elements by default); over budget, sentences matching the visible-element lexicon are kept first, then the rest in order — elements are never dropped by truncation.**
- **自动注入** `_build_visual_anchor_snapshot()`：快照由"最近 3 段"升级为**全部已建立状态**（自旧到新；总长超 1000 字符预算时才从最旧开始丢弃），延续规则文本同步列出全部可见元素类别（角色形象/外观/服装/服饰/发型/鞋帽/场景/道具/布景/伤势）。 **/ Auto-inject: snapshot upgraded from 'last 3' to ALL established states (oldest first; only drops from the oldest when the 1000-char budget is exceeded); the continuity rule now enumerates all visible-element categories.**
- **无参数变更**：widget 布局与 v14.192 相同（visual_anchor_notes 已移除，无新增端口，现役 68 键布局与旧 CUR68 一致，旧 69 键工作流兼容）。 **/ No param changes: same layout as v14.192 (manual widget gone, no new ports, 68-key current layout = old CUR68, old 69-key workflows compatible).**
- 验证：py_compile PASS；功能断言覆盖"全量保留/元素句优先/对白剔除/全量快照/超预算丢最旧"等。 / Verified: py_compile PASS; functional assertions cover full-keep, element-sentence priority, dialogue filtering, full snapshot, oldest-drop on over-budget.

---

### v14.192 (2026-10-24) — 视觉锚点全自动：自动记录+自动注入，移除手动输入（不新增任何参数端口）/ visual anchors fully automatic: auto-record + auto-inject, manual widget removed (no new ports)

**设计变更：** v14.186 的手动『分镜N: 状态声明』widget（`visual_anchor_notes`，optional 最末尾 index 67）已移除 —— 锚点不再需要用户逐行手写，改为**自动记录 + 自动注入**：**/ Design change: the v14.186 manual 『分镜N: 状态声明』widget (`visual_anchor_notes`, last optional slot index 67) is removed — anchors are now auto-recorded and auto-injected with zero manual input and zero new ports.**

- **自动记录** `_extract_visual_state_tail()`：每个分镜的正文本身就是它建立的视觉状态（道具/场景/人物外观/伤势）。从分镜正文自动提取『收尾视觉状态』——跳过【对白】/台词/旁白/音效行与引号对白占多数的句子，取末尾 1~2 句非对白陈述句（≤90 字符），渲染前按故事顺序预提取（与渲染提示词同源，外部 prompt 覆盖优先）。 **/ Auto-record: each clip's own text IS its visual state; extracts the ending non-dialogue sentences (≤90 chars) as the tail visual state, precomputed in story order from the same source as the render prompt.**
- **自动注入** `_build_visual_anchor_snapshot()`：本分镜提示词组装早期自动注入『[视觉锚点延续]』快照 = 此前分镜已记录的收尾视觉状态（最近 3 段，快照有界不撑爆提示词），格式同 v14.186（自分镜N起: 状态），强制模型延续不漂移。 **/ Auto-inject: the '[视觉锚点延续]' snapshot (last 3 recorded tail states) is injected early into each clip's prompt, same format as v14.186, keeping the prompt bounded.**
- **无参数变更**：移除的是 optional 最末尾 widget，不挤占/不移位任何既有 index；现役布局 = 旧 CUR68（68 键），前端 `H3LegacyCompat` 的 KEYS/DEFAULTS/mapTo 同步收窄到 68 位，旧 69 键工作流映射时丢弃 w[67]（旧手写值不再使用）。 **/ No widget-index shifts (removed the last slot); current layout equals old CUR68; frontend KEYS/DEFAULTS/mapTo narrowed to 68; old 69-key workflows drop w[67].**
- 验证：py_compile PASS；node --check PASS；提取/快照逻辑 11 项断言 0 fail（对白行跳过、引号对白句跳过、全对白→None、句边界截断、最近3段、clip0 无前置→None 等）。 / Verified: py_compile PASS; node --check PASS; 11 functional assertions on extraction/snapshot logic, 0 fail.

---

### v14.191 (2026-10-24) — 一镜到底中段切镜（阶段一）：分拍时间标记反切镜指令 / one-shot mid-clip cut fix (phase 1): anti-cut directive for time-beat prompts

**实测定位：** clip1 预览（287 帧 / 11.96s）场景检测（scene>0.18）发现 **2 个硬切：t=2.67s（帧64）正面中景→侧后方、t=6.46s（帧155）侧后方→正面手持相机**。两个切点与提示词 "0-3秒 / 3-6秒" 分拍边界（3s/6s）对齐 → 模型把分拍脚本当成镜头清单，在拍点按 MV 蒙太奇先验自行分镜覆盖。 **/ Measured: two hard cuts in the 11.96s clip at 2.67s and 6.46s, aligned with the prompt's 0-3s/3-6s beat boundaries — the model read the beat list as a shot list and montage-covered the beats.**

- **根因（机制层面）**：既有链式机制（噪声延续 + 头部均匀锁 keep + 衔接模板）只锚定**段头 ~1s**；12s 单次生成窗口内其余 ~11s 是模型自由行驶区，没有任何机制约束段内不切镜。参考工作流的"一镜到底"全部使用 ~5s 短链，窗口短所以段内几乎不会切。 **/ Root cause: all chain mechanisms anchor only the ~1s head; the remaining ~11s of a 12s single-pass window is free-running. Reference workflows use ~5s links, where mid-link cuts are rare.**
- **本次修改（零风险，不动时序/缓存/参数）**：一镜到底模式下始终追加双语"[单镜头硬规则]"指令 —— 显式声明提示词中的时间段描述是**同一连续运镜的先后阶段而非多个镜头**，禁止拍点切镜/转场/机位景别跳变/时间跳跃。单采与双采档都生效。 **/ Change (zero-risk, no timing/cache/param impact): one-shot mode now always appends a bilingual "[Single Continuous Take — Hard Rule]" directive declaring the time beats are phases of ONE unbroken camera move, not separate shots.**
- **阶段二（待确认）**：12s 长段拆分为 ≤6.4s 链式短段（141+153 帧 / 136+153 帧，按 %17==5 网格精确求和 = 现有净帧数 294/289，**零音频漂移**）。需要先拿到一次实机渲染日志核对音频推进公式后再实施；启用后需全量重渲一次（旧缓存索引错位）。 / Phase 2 (pending): split 12s segments into ≤6.4s chained links with exact %17==5 grid math (sums match current net frames 294/289 — zero audio drift). Needs one runtime log to verify the audio-advance formula before implementation; enabling forces one full re-render.
- 验证：py_compile PASS。 / Verified: py_compile PASS.

---

### v14.190 (2026-10-24) — 淡彩/低步数彩点修复：解码后色度去斑（不动亮度、不加参数）/ chroma despeckle after decode: kill the colored dots without touching luma or adding widgets

**根因（实测定位）：** 成片 1920×1088 每帧约 420 个极端饱和像素（官方样本 0 个）；对官方干净样本用 libx264 crf17 yuv420p / yuv444p 重编码均为 0 → 排除编码器，彩点存在于编码前像素。真实彩点样例 `(33,181,134)` 青绿、自身 Cb/Cr=(0.006,−0.275)、邻域=(−0.10,+0.10)，偏离 0.37~0.40 且成 2×2 块（4:2:0 扩散特征）。链条：低步数单采 → VAE 解码在明暗交界/高光处逐通道过冲 → uint8 按通道硬截断成 2~6px 高饱和色块；淡彩画面本身低饱和，这些点成了画面唯一的高饱和像素，因此格外刺眼。 **/ Root cause (measured): ~420 extreme-saturation pixels per frame (0 in official samples); re-encoding a clean official sample with libx264 crf17 yuv420p/yuv444p yields 0 → encoder ruled out. Real sample (33,181,134): chroma (0.006,−0.275) vs neighborhood (−0.10,+0.10), deviation 0.37-0.40, in 2×2 blocks (4:2:0 spread). Chain: low-step single pass → VAE decode per-channel overshoot at luma/highlight boundaries → uint8 hard clipping into 2-6px saturated blotches, which stand out in a low-saturation pastel frame.**

- **新增 `motion_context_disk._despeckle_frames()`**：① 转 YCbCr；② 彩度参考取 13px 均值，像素彩度与参考差 d 超过 knee(0.07) 后按 span(0.12) 线性把 Cb/Cr 混向参考值，**Y 原样保留**（轮廓/纹理锐度不变）；③ 亮度只处理"孤立"亮点——`|Y−邻域均值|` 超阈且 `偏离/邻域起伏` 比值 >2.5（真实边缘比值约 1.5，单像素脉冲 6+），因此高对比边缘不被磨掉。 **/ New `_despeckle_frames()`: YCbCr split; chroma reference = 13px mean, blend Cb/Cr toward it with a soft knee (0.07 + 0.12 span), Y untouched; luma only for isolated impulses, gated by a deviation/neighborhood-variation ratio >2.5 so real high-contrast edges are never softened.**
- **接入四个出口**：`_write_image_frames()`（uint8 与 float 两个分支，即所有 VAE 解码→mp4 编码）、单 clip 预览解码 chunk 循环、`extender._decode_clip_to_av()`（按 16 帧分块）。 **/ Wired into four exits: `_write_image_frames()` (uint8 + float branches), the single-clip preview decode chunk loop, and `_decode_clip_to_av()`.**
- **缓存失效**：`decoded_mp4_version` 3 → **4**（3 处），旧 v3 blob 自动重编码，否则旧预览仍带彩点。 **/ Cache invalidation: `decoded_mp4_version` 3 → 4 so old v3 blobs re-encode.**
- **实测指标**：PSNR 44.85dB、改动像素 0.137%/帧、1080p CPU 约 102ms/帧；合成验证 4px 饱和块彩度保留 7%（按彩点处理）、12px 起 100% 保留、大色块内部改动 0.0、高对比边缘逐像素不变、1px 纯白亮点归零。 **/ Measured: PSNR 44.85dB, 0.137% pixels changed/frame, ~102ms per 1080p frame on CPU; synthetic: 4px saturated block retains 7% chroma (treated as speck), 12px+ fully kept, interior of large blocks unchanged, hard edges pixel-identical, 1px white dot removed.**
- **不改参数区、不动快捷条、不改旧工作流**：纯解码后处理，无新 widget；分镜模式/对口型链路同样受益。版本号 v14.190（远端 v14.187-189 已被 C/G 盘分镜修复与 lip_audio 修复占用）。 **/ No widget changes, no quick-bar changes, no workflow breakage — pure post-decode processing. Renumbered to v14.190 as remote took v14.187-189.**
- 验证：py_compile PASS；离线真实帧评估脚本通过。 / Verified: py_compile PASS; offline real-frame evaluation passed.

---

### v14.189 (2026-10-24) — 对口型音频超长自动追加延续 CLIP 时 clip_ref_plans 越界崩溃修复 / fix IndexError crash when auto-appended extension CLIP desyncs clip_ref_plans

**根因（G盘 8191 实机 IndexError 实锤）：** 分镜 clips 总时长 < lip_audio（对口型/歌曲）总时长时，插件在渲染函数前部按原始 clips 构建 clip_ref_plans（len=N），随后在 lip 处理段 `clips.append(_new_clip)` 自动追加延续分镜（len=N+1）——渲染循环 `loop_end=len(clips)=N+1` 访问 `clip_ref_plans[N]` → `IndexError: list index out of range`（extender.py:7766 `_plan = clip_ref_plans[i]`，clip 全部采样/解码完成后崩溃，成片无法输出）。** / Root cause (G-drive 8191 real IndexError): when total storyboard clip duration < lip_audio duration, clip_ref_plans is built for the original N clips, then `clips.append(_new_clip)` auto-extends to N+1 — the render loop (`loop_end = len(clips)`) hits `clip_ref_plans[N]` → IndexError at the end of the chain, discarding all rendered clips.**

- **修复（extender.py `clips.append` 处同步扩展）**：追加延续 CLIP 后，若 `clip_ref_plans` 非 None 则同步 `clip_ref_plans.append(dict(clip_ref_plans[-1]))`——延续段画面沿用上一分镜构图，其 `<Picture N>` 引用与上一分镜相同，直接继承最后一条 plan；plans 长度与 clips 重新对齐，循环不再越界。** / Fix (sync-extend at clips.append): after appending the extension clip, append a copy of the last clip_ref_plans entry so plans length tracks clips length; the extension clip inherits the previous shot's reference plan (same scene/pictures).**
- 验证：py_compile PASS。 / Verified: py_compile PASS.
- ⚠️ 待用户实机验收（超长歌曲自动延续段渲染不再崩溃、成片完整输出）后再 commit/push 与 C 盘同步（铁律）/ ⚠️ Awaiting user acceptance run before commit/push and C-drive sync (iron rule)

---

### v14.188 (2026-10-24, merge 整合) — 分镜模式过渡帧重影/一帧崩坏根治：渐进锁 keep（场景跳变平滑转向）/ storyboard-mode seam ghost-frame fix: progressive keep-lock (smooth turn toward the new scene)

**根因（实机抽帧量化实锤）：** 分镜模式场景跳变（clip1 尾=主播直播场景 → clip2 首=蜡烛特写）时，v14.187 的均匀锁 keep 把上一段尾画面强锁到新场景头部，输出区前几帧被迫从旧场景演化 → 过渡帧重影/一帧崩坏（实测 clip2 首帧=主播场景重影马赛克，相邻帧差突变 diff=107 且内容错位；用户截图 2094x1299 亦为主播+货架场景重影）。** / Root cause (frame-extract proven): in storyboard mode with scene jumps (clip1 tail = livestream host → clip2 head = candle close-up), v14.187's uniform keep-lock pins the previous clip's tail frame into the new scene's head; the post-trim output must evolve out of the old scene → ghost/damaged transition frames (measured: clip2 head = host scene ghosted/mosaiced, neighbor-frame diff=107 with content mismatch; user screenshot also shows host+shelf scene ghosting).**

- **修复（extender.py 段落头 noise_mask）**：一镜到底（连续镜头）保持均匀锁 keep（v14.178 已验证无缝）；**分镜模式改"渐进锁 keep"——noise_mask 头部 0.0→1.0 线性渐降（首步完全 keep 无缝进入，逐步放开重绘）**，模型前几步从上一段尾状态平滑转向新场景，trim 后输出区起点已是转向完成的画面（清晰新场景、无重影/崩坏帧）。** / Fix (extender.py head noise_mask): one-shot (continuous) keeps uniform keep-lock (v14.178 proven seamless); **storyboard mode switches to progressive keep-lock — head noise_mask ramps 0.0→1.0 linearly (first step fully kept for seamless entry, then denoise weight released step by step)** — the model smoothly turns from the previous tail state toward the new scene in the first steps, and the post-trim output starts from the turned result (sharp new scene, no ghost/corrupt frames).**

---

### v14.187 (2026-10-24) — 分镜模式 clip2+ 前段渐进模糊根治：重叠区噪声延续扩展到所有上下文衔接段 / storyboard-mode clip2+ head blur fix: seam noise-continuation extended to all motion-context segments

**根因（抽帧+Laplacian 量化实锤）：** 分镜模式 clip2+ 头部 motion context 走 conditioning（minimax_keyframes）语义，采样 latent 仍从空噪声起，模型在接缝区"重新想象"（v14.178 已诊断接缝 PSNR 仅 18.95dB）→ clip2 前 0.5~4s 渐进模糊。实测同机同工作流：clip1 前段清晰度 1034~1044，clip2 前段 153→236→320→452→650（0.5~4s）才恢复——clip2 独有、系统性前段模糊。** / Root cause (frame-extract + Laplacian proven): in storyboard mode the clip2+ head motion context is conditioning-only (minimax_keyframes); the sampling latent still starts from empty noise, so the model "re-imagines" the seam zone (v14.178 already diagnosed seam PSNR 18.95dB) → clip2's first 0.5~4s blur progressively. Measured on the same machine/workflow: clip1 head sharpness 1034~1044 vs clip2 head 153→236→320→452→650 — clip2-exclusive systematic head blur.**

- **修复（extender.py 段落头 latent 构造）**：v14.178 的"重叠区噪声延续"（头部 overlap 帧直接取上一段尾 latent +10% 扰动 + noise_mask 锁 keep 0=不去噪，采样器不再重画接缝区，被锁区最终由 join trim 裁掉）从 `one_shot_enabled` 扩展到**所有 `trim_frames` 生效的上下文衔接段（含分镜模式）**——clip2+ 从上一段尾 latent 状态延续而非空噪声重画，前几帧与接缝连续、清晰；日志区分"一镜到底/分镜衔接"。** / Fix (extender.py head-latent construction): v14.178's seam noise-continuation (head overlap rows = previous clip's tail latent +10% perturbation + noise_mask keep 0=no-denoise, sampler no longer repaints the seam zone, locked rows finally trimmed by join) extended from `one_shot_enabled` to **every motion-context segment where `trim_frames` applies (storyboard mode included)** — clip2+ continues from the previous tail latent instead of re-imagining from empty noise, so the first frames stay sharp and continuous; logs distinguish 一镜到底/分镜衔接.**

---

### v14.186 (2026-10-24) — 显存预算自检告警：权重装不下时明确提示将走流式 / VRAM budget self-check warning when weights cannot be resident

**背景：** 实机出现 831s/步（正常 100-200s/步），日志显示 19.5GB DiT 在 24GB 卡上 `resident=0.0GB` → 回退 DynamicVRAM 逐层流式搬运（NUM_STREAMS=0 同步搬运）。旧版仅打印"驻留无效"，看不出后果与解法。 **/ Background: real run showed 831s/step; the 19.5GB DiT could not be resident on a 24GB card and fell back to per-layer streaming.**

- **新增启动自检（extender.py 一采前显存预算段）**：当 `DiT 权重 > 可用 − reserve 4GB`（含 `free < 18GB` 分支）时，打印三条明确告警——①预算数值对照；②后果（每步 600-900s vs 驻留 100-200s）；③解法（换剪枝/int8 小模型如 `fasth3_omniref_8step_pruned_int8_convrot` 配「FastH3 Omni 8步单采」档 / 更大显存卡 / 降分辨率只减 activation 解决不了权重装不下）。不改变任何采样行为，纯诊断输出。 **/ Added a VRAM-budget self-check that prints budget, consequence, and remedies when weights cannot fit; diagnostic only, no behavior change.**
- 验证：py_compile PASS。 / Verified: py_compile PASS.

---

### v14.185 (2026-10-24) — 一镜到底接缝模糊/抖动根治：单采无缝档（对齐 Motion Context V2 单遍采样）/ one-shot seam blur & jitter fix: single-pass seamless tier (aligned with Motion Context V2)

**根因（参考工作流实锤）：** B站 Motion Context V2 (BV1T9ho6HEKP) 实测结论——"continuing a chain off dual-pass latents gives pixel shift at the joins. Single pass joins clean."。我们的一镜到底链每段走一采+二采（refine denoise 重采样），二采在接缝处引入像素漂移（段间模糊/抖动）；v14.162 keyframe resize 携带、v14.178 头部噪声延续都是对"双采链"的补丁，无法根治。另一参考《MiniMax H3 首帧上下文连续长镜头》(BV1eSgH6yE7z) 同为单遍采样链（res_multistep + beta 8 步 + turbo LoRA，22 pinned 帧接缝裁切）。** / Root cause (proven by reference workflows): continuing a chain off dual-pass latents gives pixel shift at the joins — our one-shot chain ran first-pass + refine per clip, and the refine re-denoise shifted pixels at every seam. v14.162/v14.178 were patches on a seam-hostile dual-pass chain.**

- **新增 `one_shot_sampling` widget（extender.py INPUT_TYPES optional 最末尾 / 前端 index 66）**：`单采无缝 (推荐)` / `双采高清 (接缝风险)`，默认单采。一镜到底开启且单采档时渲染循环 `_eff_refine` 强制 False（绕过 `_sample_h3` L3093 refine 分支，不动其内部），链式 latent 不重绘；双采档保留旧行为并打印接缝风险警告。** / New `one_shot_sampling` widget (appended last, frontend index 66): single-pass (default) forces `_eff_refine=False` in the render loop; dual-pass keeps legacy behavior with a seam-risk warning.**
- **步数校验翻转（原 v14.178 steps≥20 检查）**：单采档对齐参考标准 turbo 蒸馏 LoRA + beta 调度 + 6-8 步——steps≥20 警告蒸馏链过采样烧穿上下文一致性（历史诊断接缝 PSNR 18.95dB），scheduler≠beta 仅提示；双采档保留 ≥20 校验。** / Steps check flipped: single-pass recommends turbo LoRA + beta + 6-8 steps and warns on steps≥20; dual-pass keeps the ≥20 check.**
- **提示词纪律引导（启用时打印 + tooltip，不改用户提示词）**：接缝裁切 22 帧≈0.92s，段内时间戳想落在 T 写 T+0.92s；续写段开头只写承接勿加新景物名词；接缝落在运动中段勿落在门槛/事件点；台词每 2.5s 一句短句。** / Prompt-discipline guidance printed on enable + tooltip (user prompts untouched).**
- **前端同步（extender.js）**：KEYS/DEFAULTS/OPTIONS 68 键扩展、detect() 新增 CUR68、mapTo() 输出 68 位（CUR67 及更早布局自动补默认值）、widget 中文标签。** / Frontend: KEYS/DEFAULTS/OPTIONS extended to 68 keys, CUR68 detection, mapTo outputs 68 slots with defaults for older layouts, bilingual label.**
- 分镜模式（one_shot=off）零影响；lip_audio/lip_voice 对口型链路不受影响（音频注入 AV latent 与 refine 无关）；单采档下 refine 放大（含 HyperVAE 2K）不生效，需 2K 时改用双采档或分镜模式。** / Storyboard mode unaffected; lip-sync paths unaffected; refine upscaling (incl. HyperVAE 2K) is inactive in single-pass tier by design.**
- 验证：py_compile PASS；node --check PASS。 / Verified: py_compile PASS; node --check PASS.

---

### v14.179 (2026-10-23) — 二采分块提速：回退盲目扩块，overlap 减半，head 分组恢复 / refine-tile speed: no blind re-tiling, halved overlap, head-chunking restored

**根因（实机数据实锤）：** v14.164 把请求 4 块自动扩到 8 块（每块 <=270k 假设 Sol-Attn 稀疏 0.7s/块），但 tile 实际走 KJNodes head 分组路径（实测 0.26~0.55s/k tokens），8 块 overlap 重叠区重复计算翻倍 → 545s/步，反超 v14.149 固定 4 块（~334k/块灰色区）的 399s/步；v14.166 再把 head 分组 4->1，KJNodes 分组稀疏退化成全 head dense，雪上加霜。 **/ Root cause (proven by real runs): v14.164 auto-blew requested 4 tiles to 8 (<=270k/tile assumed Sol-Attn sparse at 0.7s/tile), but tiles actually run through the KJNodes head-chunk path (~0.26-0.55s/k tokens measured); 8 tiles double the overlap duplicate work → 545s/step, worse than v14.149's fixed 4 tiles (~334k grey-zone) at 399s/step. v14.166 then cut head chunks 4->1, degrading KJNodes grouped sparse into full-head dense.**

- **修复①（extender.py `_ff_auto_refine_tile_count`）**：健康区目标 270k -> 安全区 450k，每块 <=450k 一律尊重请求值不扩块（分块越少 forward/搬运/重叠越少）；overlap 钳制 128px -> 64px（重叠重复计算减半，接缝由 motion-context keyframe 对齐兜底）。 **/ Fix ①: healthy-zone target 270k -> safe-zone 450k; per-tile <=450k now respects the requested count (fewer tiles = less forward/move/overlap); overlap clamped 128px -> 64px.**
- **修复②（extender.py 二采 delegate）**：回退 v14.166 的 head_chunks 4->1，恢复 head 分组 4，让 KJNodes 低显存分组稀疏重新生效。 **/ Fix ②: revert v14.166's head_chunks 4->1 back to 4 so KJNodes low-mem grouped sparse re-engages.**
- **预期**：995k tokens 二采（clip1 8 块 545s/步）回到 ~4 块 340s/步量级；如需 200-240s/步，可后续攻 Sol-Attn 稀疏真生效（tile 0.7s）或二采 x1.8（成片 1728p）。 **/ Expected: 995k-token refine from 545s/step (8 tiles) back to ~340s/step (4 tiles); for 200-240s/step, either pursue true Sol-Attn sparse (0.7s/tile) or refine at x1.8 (1728p output).**

---

### v14.177 (2026-10-23) — 一镜到底段间衔接断裂根治：渲染帧数补上 motion context 帧 / one-shot inter-segment continuity fix: render frame count now includes motion context frames

**根因（5090 实测链缓存实锤）：** 渲染 latent 帧数只按目标时长构造（12s → 294 帧），而 motion context 会把上一段尾部 39 帧作为 keyframes 注入本段开头，join 解码时按 trim_frames=39 裁掉这段上下文 → 每段净输出只剩 255 帧 = 10.63s（目标 12s，每段短 1.375s），音频同步被裁（seg1/2=340000 samples=10.63s）→ 段间断帧断音、成片总时长 804 < 864，且段首过渡区被裁造成"切镜感"。** / Root cause (proven by 5090 chain-cache): render latent frame count was built from the target duration only (12s → 294 frames), but motion context injects the previous clip's tail 39 frames as keyframes into the start of this clip and join trims those 39 context frames at decode → each clip net-outputs only 255 frames = 10.63s (target 12s, short by 1.375s/clip), audio trimmed in sync (seg1/2 = 340000 samples = 10.63s) → inter-segment frame/audio gaps, total 804 < 864 frames, and the trimmed head-transition area reads as "camera cut".**

- **修复①（extender.py L7531）**：当 `i>0` 且 `context_enabled` 且前段有缓存（将应用 motion context）时，渲染帧数改为 `_align_frame_count(目标帧 + context帧)`——328 帧（12s 目标 288 + 39 ctx，经 H3 grid %17==5 对齐）。解码裁掉 39 帧 context 后净输出 **289 帧 = 12.04s ≈ 目标 12s**，段间画面无缝、音频同步不裁。** / Fix ① (extender.py L7531): when `i>0` and `context_enabled` and previous cache exists (motion context will apply), render frame count becomes `_align_frame_count(target_frames + context_frames)` → 328 (288 + 39 ctx, aligned to H3 grid %17==5). After trimming 39 context frames at decode, net output = **289 frames = 12.04s ≈ target 12s** — seamless inter-segment visuals, audio no longer truncated.**
- **修复②（_split_lip_audio_by_clips）**：ctx_on 段推进从 v14.157 的"净时长（标称−context）"改回**按标称全时长推进**——渲染侧净输出已恢复 = 标称，若 lip 切分仍扣 context 时长会导致音频段比视频短 context/fps 秒、下一边界错位。段头 overlap 跳过逻辑不变。** / Fix ② (_split_lip_audio_by_clips): ctx_on advancement reverted from v14.157's "net duration (nominal − context)" back to **full nominal duration** — the render side now outputs nominal length again, so lip segments must advance by nominal or they'd be short by context/fps seconds and misalign at the next boundary. Head-overlap skip logic unchanged.**
- 验证：py_compile PASS；算术自检 3×12s → old 804 帧(33.50s) / new 872 帧(36.33s) ≈ 目标 864(36s)；备份 `extender.py.bak_ctxfix_pre_v1420261023_134838` / Verified: py_compile PASS; arithmetic self-check 3×12s → old 804 frames (33.50s) / new 872 frames (36.33s) ≈ target 864 (36s); backup `extender.py.bak_ctxfix_pre_v1420261023_134838`
- ⚠️ 待用户 5090 重跑验收后再 commit/push 与 C 盘同步（铁律）/ ⚠️ Awaiting user re-render acceptance on 5090 before commit/push and C-drive sync (iron rule)

---


**核心：主节点新增 `render_pipeline` 下拉（widget index 65 = 老工作流空槽，前端 KEYS/mapTo 同步扩到 67 位对齐）。** 选择 **`FastH3 Omni 8步单采`** 后插件自动：①跳过二采（Self-Lift refine，L3018 短路，输出分辨率 factor=1.0 跟随一采）；②一采强制 8 步 + denoise 1.0（官方 FastVideo FastH3 Omni 契约：8 步蒸馏 + guidance 1.0 + shift 12/3，改步数掉画质）；③日志提示 Loader 需换 `fasth3_omniref_8step_pruned_int8_convrot.safetensors` + 模型分支挂 BlockSparseAttention（VSA keep_percent=10）。默认（双采）行为与历史版本完全一致，旧工作流（66 键）加载自动取双采默认，零影响。** / Core: new `render_pipeline` dropdown on the main node (widget index 65 = the legacy empty slot; frontend KEYS/mapTo extended to 67 positions). Selecting **`FastH3 Omni 8步单采`** auto: ①skips refine (Self-Lift dual-pass short-circuited at L3018, output factor=1.0 follows first-pass); ②forces 8 steps + denoise 1.0 on first pass (official FastVideo FastH3 Omni contract: 8-step distillation + guidance 1.0 + shift 12/3; changing steps hurts quality); ③logs that the Loader must use `fasth3_omniref_8step_pruned_int8_convrot.safetensors` with a BlockSparseAttention node (VSA keep_percent=10). Default (dual-pass) behaves exactly as before; legacy 66-key workflows load as dual-pass by default — zero impact.
- `extender.py`：INPUT_TYPES optional 末尾加 render_pipeline（index 65）；extend() 读取 + Omni 分支（refine_enable=False、steps=8、denoise=1.0 强制 + 日志）/ INPUT_TYPES optional tail adds render_pipeline (index 65); extend() reads it + Omni branch (refine_enable=False, steps=8, denoise=1.0 forced + logs)
- `web/extender.js`：KEYS/DEFAULTS/OPTIONS/detect/mapTo 扩到 67 位（render_pipeline=65，timeline=66）；中文标签 / KEYS/DEFAULTS/OPTIONS/detect/mapTo extended to 67 (render_pipeline=65, timeline=66); zh label added
- 前置（用户侧）：工作流 Loader 换 `fasth3_omniref_8step_pruned_int8_convrot.safetensors`（20.69G 已就位验证）+ 文本编码器 qwen3vl int8/nvfp4 + 模型分支挂 BlockSparseAttention(VSA) / Prereq (user side): workflow Loader → `fasth3_omniref_8step_pruned_int8_convrot.safetensors` (20.69G verified) + qwen3vl int8/nvfp4 TE + BlockSparseAttention(VSA) on the model branch
- 验证：py_compile PASS；node --check JS PASS；备份 `.bak_omni_pre_v14167`（全插件目录）/ Verified: py_compile PASS; node --check JS PASS; full-plugin backup `.bak_omni_pre_v14167`

---

### v14.169 (2026-10-22) — Omni 单采画质修复：官方 1344×768 分辨率直出 + guidance 1.0 单前向 / Omni single-pass quality fix: official 1344×768 direct output + guidance 1.0 single-forward

**根因（双杀）：** Omni 单采沿用双采架构的"一采档"分辨率（226 ResolutionSelector 0.5MP → 960×544），双采靠二采 x2 放大到 1080p，单采无二采 → 960×544 直出必然糊；且一采 guider 未覆写 cfg，CFGGuider 默认 cfg=8 双前向（FastH3 V2 老模型用法），对 Omni 8 步蒸馏模型过驱动 → 过曝/伪影/糊。** / Root cause (double hit): Omni single-pass inherited the dual-pass "first-pass tier" resolution (226 ResolutionSelector 0.5MP → 960×544) — dual-pass relies on refine x2 to reach 1080p, single-pass has no refine → 960×544 direct output is inevitably blurry; and the first-pass guider never overrode cfg, so CFGGuider's default cfg=8 dual-forward (FastH3 V2 legacy usage) over-drives the Omni 8-step distilled model → overexposure/artifacts/blur.**

- `extender.py`：
  - Omni 模式一采分辨率钳制 → 官方 FastVideo 模板 **1344×768**（L6507 后；resolved + resolution dict + manifest 声明同步，解码不再按旧声明缩放回低分辨率）/ Omni-mode first-pass resolution clamped to official FastVideo template **1344×768** (after L6507; resolved + resolution dict + manifest declaration synced so decode no longer re-scales to the old low declaration)
  - `_sample_h3` 加 `omni_8step_mode` 参数；Omni 时 `guider.cfg_scale = 1.0`（官方蒸馏契约 guidance 1.0 单前向，无 CFG 双前向；顺带每步耗时减半）/ `_sample_h3` gains `omni_8step_mode`; Omni sets `guider.cfg_scale = 1.0` (official distillation contract guidance 1.0 single-forward, no CFG dual-forward; step time roughly halves too)
  - 一采调用处传 `omni_8step_mode=omni_8step_mode`
- 工作流 `v3.2-Omni`：节点 226 ResolutionSelector **0.5 → 1.03MP**（16:9 精确输出 1344×768，与代码钳制目标一致；WAS resolve 算法核验：1353/761 → snap64 → 1344×768）/ Workflow `v3.2-Omni`: node 226 ResolutionSelector **0.5 → 1.03MP** (16:9 resolves to exactly 1344×768, matching the code clamp; WAS resolve verified: 1353/761 → snap64 → 1344×768)
- 验证：py_compile PASS；工作流 JSON 写回读回 OK（226=1.03MP、250 w65=FastH3 Omni 8步单采）；备份 `extender.py.bak_omni_quality_pre_v14169` / Verified: py_compile PASS; workflow JSON write+readback OK (226=1.03MP, 250 w65=FastH3 Omni 8步单采); backup `extender.py.bak_omni_quality_pre_v14169`

### v14.169b (2026-10-22) — Omni 画质二阶段：保底分辨率 + 全片 UltraSharp 超分到 1080p / Omni quality phase 2: floor resolution + full-clip UltraSharp upscale to 1080p

**首跑 1376×768 高清直出已确认（较 960×544 显著提升），但距 1080p 双采观感仍差一档。** 二阶段：①extender Omni 保底分辨率改为"≥官方模板(1344×768) 保留请求"（1376×768 与 latent 一致，manifest 不再偏差；<官方档才提升）；②工作流 v3.2-Omni 打开 `upscale_final`（全片合并后一次性超分）+ `upscale_model=4x-UltraSharpV2.safetensors`（133MB 锐化王，替代 5MB realesr-general）+ `upscale_factor=1.4` → 1376×768 ×1.4 = **1926×1075 近 1080p**。保真放大无二采伪影，单 CLIP ≈ 一采 8 步(~200s) + 超分(~90s) ≈ 5min，仍约 8x 于双采(40min)。** / First run confirms 1376×768 HD direct output (huge gain over 960×544) but still a tier below dual-pass 1080p. Phase 2: ①extender Omni floor resolution now "keep request if ≥ official template (1344×768)" (1376×768 matches latent, manifest no longer drifts; only below-floor requests get lifted); ②workflow v3.2-Omni enables `upscale_final` (post-merge single upscale) + `upscale_model=4x-UltraSharpV2.safetensors` (133MB sharpening king, replacing 5MB realesr-general) + `upscale_factor=1.4` → 1376×768 ×1.4 = **1926×1075 ~1080p**. Lossless enlargement, no refine artifacts; per-CLIP ≈ first-pass 8 steps (~200s) + upscale (~90s) ≈ 5min, still ~8x faster than dual-pass (40min).**
- `extender.py`：Omni 保底分辨率逻辑（L6518 附近）/ Omni floor-resolution logic (near L6518)
- 工作流 `v3.2-Omni`：250 节点 w35 upscale_final=True、w39 upscale_model=4x-UltraSharpV2.safetensors、w38 upscale_factor=1.4 / Workflow `v3.2-Omni`: node 250 w35 upscale_final=True, w39 upscale_model=4x-UltraSharpV2.safetensors, w38 upscale_factor=1.4
- 验证：py_compile PASS；工作流回读 OK（w34=False/w35=True/w38=1.4/w39=UltraSharpV2/w65=Omni）/ Verified: py_compile PASS; workflow readback OK (w34=False/w35=True/w38=1.4/w39=UltraSharpV2/w65=Omni)

### v14.170 (2026-10-22) — Omni 并入"速度"档：速度下拉直选 FastH3 Omni 8步单采（前后端联动）/ Omni merged into the "Speed" preset: pick FastH3 Omni 8-step single-pass right in the speed dropdown (frontend-backend linked)

**用户要求 Omni 档换到"速度"下拉直接选择。** speed_preset 由 12 档扩到 **13 档**（末尾新增 `FastH3 Omni 8步单采`，青蓝 tint #22d3ee）。选择该档 = 渲染管道联动切 Omni：跳过二采（refine_enable=False）、一采 8 步蒸馏 + denoise 1.0 + shift 12/3（官方契约），无需再单独点"渲染管道"按钮。**/ User asked to move the Omni option into the "Speed" dropdown. speed_preset expanded 12 → **13 entries** (tail adds `FastH3 Omni 8步单采`, cyan tint #22d3ee). Picking it links the pipeline to Omni: refine skipped (refine_enable=False), first-pass 8-step distillation + denoise 1.0 + shift 12/3 (official contract) — no need to touch the "渲染管道" button separately.**
- `extender.py`：speed_preset 枚举 + tooltip 加 Omni 档；映射分支（武戏组合拳后）`FastH3 Omni 8步单采` → 未切 Omni 时强制 omni_8step_mode=True / _render_pipeline 同步 / refine_enable=False / denoise=1.0 / shift 12/3 + 日志（omni_8step_mode 后续引用 L6520/L7600 生效）/ extender.py: speed_preset enum + tooltip gain the Omni entry; mapping branch (after 武戏组合拳) forces omni_8step_mode=True / _render_pipeline sync / refine_enable=False / denoise=1.0 / shift 12/3 + log (later omni_8step_mode consumers at L6520/L7600 take effect)
- `web/extender.js`：speed_preset cycle 13 档 + 青蓝 tint；syncOmniRefineRows 判定扩展为"render_pipeline 或 speed_preset 任一含 Omni"即隐藏二采行；**H3_REFINE_ROW_KEYS 移除 speed_preset**（防止速度档选 Omni 时把自己藏掉、无法切回）/ web/extender.js: speed_preset cycle 13 entries + cyan tint; syncOmniRefineRows now hides refine rows when either render_pipeline or speed_preset contains Omni; **speed_preset removed from H3_REFINE_ROW_KEYS** (so picking Omni in the speed dropdown can't hide the speed dropdown itself)
- 验证：py_compile PASS；node --check PASS；备份 `extender.py.bak_omni_speed_pre_v14170` + `web/extender.js.bak_omni_speed_pre_v14170` / Verified: py_compile PASS; node --check PASS; backups `extender.py.bak_omni_speed_pre_v14170` + `web/extender.js.bak_omni_speed_pre_v14170`
- 生效：重启 ComfyUI 后，速度下拉第 13 档即 Omni；也可 Ctrl+F5 强刷前端（仅 UI 按钮，后端逻辑随重载生效）/ To take effect: restart ComfyUI — the speed dropdown's 13th entry is Omni; Ctrl+F5 also refreshes the frontend (backend logic takes effect on reload)

### v14.171 (2026-10-22) — Omni 一采分辨率钳制到 24GB 显存健康区（修复 1376×768 直出 OOM 崩溃）/ Omni first-pass resolution clamped to the 24GB VRAM-healthy zone (fixes 1376×768 direct-output OOM crash)

**崩溃根因：** Omni 单采一采直出 1376×768 → latent(172,96,107) ≈ **177 万 tokens**，Sol-Attn 超 350k 阈值降级 dense 后 attention 峰值爆炸；叠加 lip_audio（TTS 音频 latent 注入）峰值更高 → 24GB 卡在第 3/8 步 CUDA OOM 崩溃（`[BSAI] ComfyUI exited.`，faulthandler 无 SIGSEGV 记录 = Python 层异常退出）。**修复：Omni 一采钳制 ≤ 960×544（873,120 tokens，与 v14.164 二采分块健康区同源），等比缩放保持纵横比；最终高清由 `upscale_final` 超分链兜底（全片合并后 4x-UltraSharp 1.4x → 1344×761，保真放大无二采伪影）。低请求（<960×544）仍等比提到健康区直出。** / Crash root cause: Omni single-pass first-pass at 1376×768 → latent (172,96,107) ≈ **1.77M tokens**; past Sol-Attn's 350k threshold it degrades to dense and the attention peak explodes; with lip_audio (TTS audio-latent injection) the peak is even higher → CUDA OOM crash at step 3/8 on the 24GB card (`[BSAI] ComfyUI exited.`, no SIGSEGV in faulthandler = Python-level abnormal exit). **Fix: Omni first-pass clamped to ≤ 960×544 (873,120 tokens, same healthy zone as v14.164 refine tiling), aspect-ratio-preserving; final HD carried by the `upscale_final` chain (post-merge 4x-UltraSharp 1.4x → 1344×761, lossless, no refine artifacts). Low requests (<960×544) still get lifted to the healthy zone.**
- `extender.py`：Omni 分辨率钳制逻辑重写（v14.169b 的"≥1344×768 保留请求" → v14.171 的"像素面积 ≤ 960×544"健康区上限；`_omni_max_px = 960*544`，等比缩放 + 32px 档收紧；日志含 latent token 数）/ extender.py: Omni resolution-clamp logic rewritten (v14.169b's "keep request if ≥1344×768" → v14.171's "pixel area ≤ 960×544" healthy-cap; `_omni_max_px = 960*544`, aspect-preserving + 32px step tightening; log shows latent token counts)
- 验证：py_compile PASS；备份 `extender.py.bak_omni_res_pre_v14171` / Verified: py_compile PASS; backup `extender.py.bak_omni_res_pre_v14171`
- 前置（用户侧）：工作流 250 节点 `upscale_final` 保持开启（w35=True）+ upscale_model=4x-UltraSharpV2 + factor 1.4（若想更近 1080p 可调 1.6-2.0）/ Prereq (user side): node 250 `upscale_final` stays on (w35=True) + upscale_model=4x-UltraSharpV2 + factor 1.4 (raise to 1.6-2.0 to get closer to 1080p)

### v14.172 (2026-10-22) — 模型配方档迁移：速度档回 7 项基础档，渲染管道统一 7 档管理模式配方 / Recipe modes migrated: speed dropdown back to 7 base presets, render pipeline now owns all 7 recipe modes

**用户要求：把速度档里的模型配方类档位（FastH3-Trim / FastH3-4步VSA / Turbo-v4 / DMAD-4步 / 武戏组合拳 / FastH3 Omni 8步单采）移入「渲染管道」下拉统一管理；速度档只保留基础档（custom/极速/均衡/精细 + VDN×3）。** / User asked: move the recipe-type presets (FastH3-Trim / FastH3-4步VSA / Turbo-v4 / DMAD-4步 / 武戏组合拳 / FastH3 Omni 8步单采) out of the speed dropdown into the render-pipeline dropdown; speed keeps only the base presets (custom/极速/均衡/精细 + VDN×3).**
- `extender.py`：
  - speed_preset 枚举 13→**7 项**（custom/极速/均衡/精细/极速-VDN/均衡-VDN/精细-VDN）/ speed_preset enum 13→**7 entries** (base + VDN trio)
  - render_pipeline 枚举 2→**7 项**（双采默认 + FastH3-Trim/FastH3-4步VSA/Turbo-v4/DMAD-4步/武戏组合拳/Omni）/ render_pipeline enum 2→**7 entries** (dual-pass default + 6 recipes)
  - extend() 新增渲染管道模式分支：非默认档时步骤/采样器/Omni 联动由渲染管道接管（speed_preset 置 custom 防叠加）；旧工作流遗留的配方档速度值仍走原兼容分支按值生效（两源互斥）/ extend() gains a render-pipeline recipe branch: non-default pipeline owns steps/sampler/Omni linkage (speed_preset forced to custom to avoid stacking); legacy recipe values left in the speed widget still hit the compat branches (mutually exclusive)
- `web/extender.js`：speed_preset cycle 13→7 档（desc 同步，提示配方档移至渲染管道）；render_pipeline cycle 2→7 档 + 7 色 tints；syncOmniRefineRows 双源判定保留（兼容旧值）/ web/extender.js: speed_preset cycle 13→7 (desc notes recipes moved); render_pipeline cycle 2→7 + 7 tints; syncOmniRefineRows dual-source check kept (legacy compat)
- 验证：py_compile PASS；node --check PASS；备份 `extender.py.bak_rp_move_pre_v14172` + `web/extender.js.bak_rp_move_pre_v14172` / Verified: py_compile PASS; node --check PASS; backups `extender.py.bak_rp_move_pre_v14172` + `web/extender.js.bak_rp_move_pre_v14172`
- 生效：重启 ComfyUI（或 Ctrl+F5 刷前端）；旧工作流速度档遗留配方值自动兼容，新工作流配方档统一从「渲染管道」选择 / To take effect: restart ComfyUI (or Ctrl+F5); legacy recipe values in the speed widget stay compatible; new workflows pick recipes from the render pipeline dropdown

### v14.173 (2026-10-23) — Turbo-v4 配方加固：8+4 步 + 二采 denoise 0.45（修复 clip2 复杂场景结构漂移变形）/ Turbo-v4 recipe hardened: 8+4 steps + refine denoise 0.45 (fixes structural drift/deformation in clip2 complex scenes)

**问题：Turbo-v4（6+4 / 二采 denoise 0.55）+ 一采 1376×768（177万 tokens）在 clip2（点火/火焰/大特写/产品标签）全面失真：人物面部模糊、手部拖影、蜡烛标签假英文乱码、购物车图标被模型误画。** / Issue: Turbo-v4 (6+4 / refine denoise 0.55) + 1376×768 first pass (1.77M tokens) fully degraded in clip2 (ignition/flame/close-up/product labels): blurred face, hand motion smear, fake-English label gibberish, shopping-cart icon hallucinated.**
- `extender.py`：渲染管道「Turbo-v4」分支 6+4/0.55 → **8+4/0.45**（一采 8 步结构更稳，二采少重绘防漂移；速度仍快于精细 8+6）；速度档兼容分支同步同值 / extender.py: render-pipeline "Turbo-v4" branch 6+4/0.55 → **8+4/0.45** (8-step first pass stabilizes structure, lower refine denoise avoids drift; still faster than 精细 8+6); speed-widget legacy branch synced
- 验证：py_compile PASS；备份 `extender.py.bak_rp_turbo_pre_v14173` / Verified: py_compile PASS; backup `extender.py.bak_rp_turbo_pre_v14173`
- 配套工作流建议（v3.4.8）：clip2 提示词移除「品牌logo」「虚拟购物车图标动画」等模型易画成假文字的诱导元素 / Companion workflow (v3.4.8): clip2 prompt removes hallucination-prone elements like "品牌logo" and "虚拟购物车图标动画"
- 生效：重启 ComfyUI 后生效 / To take effect: restart ComfyUI

### v14.174 (2026-10-23) — lip_voice 升级为对口型驱动音频（同 lip_audio 语义且优先）/ lip_voice upgraded to lip-sync drive audio (same semantics as lip_audio, takes priority)

**问题：lip_voice 端口接入 IndexTTS 合成台词音频后，模型仍自己生成音频、完全不对口型（lip_voice 此前仅打印提示日志，不驱动渲染）。** / Issue: connecting TTS dialogue audio to lip_voice left the model generating its own audio with no lip-sync (lip_voice previously only printed a hint log and changed nothing).**
- `extender.py`：lip_voice 非 None 时**重赋值 lip_audio 变量** → 切段(_split_lip_audio_by_clips)/AV latent 音频注入+zero-noise 锁定/提示词净化/音频驱动提示词/输出主轨替换（模型音频 15% 垫底）**全链路自动复用**，无需复制代码；lip_voice 优先于 lip_audio；日志更新为"✅ lip_voice 已连接 → 升级为对口型驱动音频" / extender.py: when lip_voice is connected it **overrides the lip_audio variable** so the whole lip-sync pipeline (per-CLIP slicing / AV-latent audio injection + zero-noise lock / prompt stripping / audio-drive prompt / output main-track swap with 15% model bed) is **reused automatically**; lip_voice takes priority over lip_audio; log updated
- 端口 tooltip 更新（中英双语）：lip_voice = 对口型驱动音频，接入后取消模型自生成音频，典型用途接 IndexTTS 合成台词 / lip_voice tooltip updated (bilingual): lip-sync drive audio; model-generated audio discarded; typical use: IndexTTS synthesis output
- 验证：py_compile PASS；备份 `extender.py.bak_lipvoice_pre_v14174` / Verified: py_compile PASS; backup `extender.py.bak_lipvoice_pre_v14174`
- 配套工作流（v3.4.9）：角色档案对齐@图1（高马尾红黑条纹）、道具档案去"品牌标识"、clips 去"品牌logo/购物车图标"诱导、1425 IndexTTS 换香薰口播稿（≤10字/句）/ Companion workflow (v3.4.9): character sheet aligned to @图1 (ponytail + red-black stripe top), prop sheet drops "brand logo", clips drop "logo/cart icon" hallucination bait, 1425 IndexTTS set to candle voice-over script (≤10 chars/sentence)
- 生效：重启 ComfyUI 后生效 / To take effect: restart ComfyUI

### v14.175 (2026-10-23) — 对口型音频超长自动补 CLIP / Auto-extend CLIPs when lip-sync audio is longer than storyboard

**需求：lip_voice/lip_audio 驱动模式下，外部音频超过分镜脚本设定的 clip 总时长时（例：音频 35s / 脚本 30s），自动新增一个延续上一个分镜画面的 CLIP 承载多余音频，保证外部音频完整性（尾部台词不再被截断丢弃）。** / Requirement: in lip_voice/lip_audio drive mode, when external audio exceeds the total storyboard duration (e.g. audio 35s / script 30s), auto-append a CLIP that continues the previous shot to carry the excess audio, so the external audio stays complete (no tail truncation).
- `extender.py`：切段前比对 `lip_audio` 总时长与 clips 总时长，超出时**自动追加 CLIP**（id=`<last>_auto_ext`，duration=差额帧对齐，prompt 复制上一个分镜——lip 模式提示词净化会抹掉口播描述，口型由音频驱动，画面自然延续；context_enabled/字幕等字段继承），随后 `_split_lip_audio_by_clips` 按扩展后 clips 切段、逐 CLIP 渲染，输出视频与外部音频逐帧对齐 / extender.py: before slicing, compare lip_audio total duration vs storyboard total; on exceed **auto-append a CLIP** (id=`<last>_auto_ext`, duration=frame-aligned remainder, prompt copied from previous shot — the lip-sync prompt-strip removes talking descriptions, mouth is audio-driven, visuals naturally continue; context/subtitle fields inherited), then slice by the extended clips and render each, final output frame-aligned with the external audio
- 兼容：原有"音频短于 clips 按比例缩放"逻辑不变；非 lip 模式不受影响 / Compatible: existing "audio shorter than clips scales down proportionally" untouched; non-lip modes unaffected
- 验证：py_compile PASS；备份 `extender.py.bak_autoext_pre_v14175` / Verified: py_compile PASS; backup `extender.py.bak_autoext_pre_v14175`
- 生效：重启 ComfyUI 后生效 / To take effect: restart ComfyUI

### v14.176 (2026-10-23) — 武戏组合拳档对齐 YZ金鱼终极篇配方（画质+速度双优化）/ 武戏组合拳 recipe aligned to YZ金鱼 ultimate edition (quality + speed)

**参考：B站「MiniMax H3终极篇、新二采、新加速、文武双全又快又好」(BV1LKJm6VELc) + YZ金鱼终极篇示例工作流。** / Reference: Bilibili "MiniMax H3 ultimate edition" (BV1LKJm6VELc) + YZ金鱼 example workflow.**
- **配方升级（渲染管道「武戏组合拳」+ 速度档兼容分支同步）**：一采 8 步+二采 4 步 → **一采 6 步 + 二采 6 步（总 12 步）**——YZ 明确武戏 6+6 拟合更好更清晰；shift 8/3 → **12/3**（官方 v4 参数）；euler+simple 调度保持；二采 denoise 0.45 / 分块 4 保持 / Recipe upgrade (render-pipeline "武戏组合拳" + speed-widget legacy branch synced): 8+4 → **6+6 (12 total, better action fitting per YZ)**; shift 8/3 → **12/3 (official v4)**; euler+simple kept; refine denoise 0.45 / tiles 4 kept
- **H3 17 帧块对齐（武戏档新增）**：命中武戏组合拳档时，clips 帧数统一对齐 `%17==5`（YZ 帧数公式），在 lip 切段/时长换算前调整 duration——防高动态武戏 latent 时间结构错位/果冻伪影 / **H3 17-frame-block alignment (new, combat preset only)**: frames aligned to `%17==5` (YZ frame formula) before lip-slicing/duration math — prevents latent time-structure jitter/ghosting in high-motion action scenes
- 配套（工作流层，需下载 YZ 包内文件）：主模型已具备 `minimax_h3_hybrid_fl2va_ref2va_b25-49-int8`；建议 H3LoraStack 增加 **DMAD融合LoRA（minimax_h3_dmad_full_dareties_v4_step600_comfy_fro @0.8）＋H3_Fight_Flow_V1（@0.35）＋速度滑块 H3_speed_slider_1.1（@3）＋可选去油腻 MysticXXX_MMH3-V1（@0.35）**；latent upscaler 换 **V2 LMS 锐利版（实测 YZ 包内文件名为 `h3_upscaler_lms_v0.1.safetensors`）**；下载：夸克网盘 s/6af352275c72（视频简介） / Companion (workflow layer, files from YZ pack): model already present; H3LoraStack + DMAD-merge LoRA (0.8) + H3_Fight_Flow_V1 (0.35) + speed slider (3) + optional de-oil MysticXXX (0.35); latent upscaler → V2 LMS (verified filename in YZ pack: `h3_upscaler_lms_v0.1.safetensors`); download: quark s/6af352275c72
- 验证：py_compile PASS；备份 `extender.py.bak_wxcombat_pre_v14176` / Verified: py_compile PASS; backup `extender.py.bak_wxcombat_pre_v14176`
- 生效：重启 ComfyUI 后生效 / To take effect: restart ComfyUI

### v14.178 (2026-10-23) — 新增「4K直出 秘制酱料」渲染管道档（自提升渐进采样 + DLSS5 4K 直出）/ New render-pipeline preset "4K直出 秘制酱料" (Self-Lift progressive sampling + DLSS5 4K output)

**参考：B站《4K直出 MiniMax H3 的视频生成秘制酱料工作流！H3 统一插件 + DLSS 5 超采样》(BV18Vnb6UEPv, 大凯AI / CottonByte / Yusu)。** / Reference: Bilibili "4K direct MiniMax H3 secret-sauce workflow" (BV18Vnb6UEPv, by 大凯AI / CottonByte / Yusu).**
- **新增渲染管道档「4K直出 秘制酱料」**：一采 **6 步低分辨率**（width/2 自动 960x544，快定构图/轮廓/大幅运动）→ **RESOLUTION BOOST**（refine_upscale_factor 强制 2.0 升潜空间分辨率）→ 二采 **3 步高分辨率细节**；shift **12/3**（官方 v4）；euler+simple 强制；二采 denoise **0.45**（防高光过曝/重绘漂移）/ **New preset "4K直出 秘制酱料"**: first pass **6 steps at low res** (auto 960x544 via width/2, fast composition/shapes/motion) → **RESOLUTION BOOST** (refine_upscale_factor forced 2.0) → refine **3 steps** for high-res texture; shift **12/3**; euler+simple forced; refine denoise **0.45**
- 若用户已手动把 refine_upscale_factor 降到 1.5（4090/24GB 提速）档位保留其值并提示搭配 DLSS 2.66x 仍达 4K / If user already set refine_upscale_factor 1.5 (4090/24GB speedup) the preset keeps it and hints DLSS 2.66x still reaches 4K
- 配套（工作流层）：H3LoraStack 建议 **Turbo v4 step600（`minimax_h3_turbo_v4_step600_ema_DasiwaREF2VAHybridV1_0_curveproj1025_compat_v001.safetensors` @0.5~0.8，加速）＋ MysticXXX_MMH3-V4（@0.3~0.5，去油光/高光自然）**；输出启用 **upscale_final + DLSS5 引擎**（RH-DLSS5）放大到 4K；4090 建议 refine_upscale_factor 1.5 + DLSS 2.66x / Companion (workflow layer): H3LoraStack with **Turbo v4 step600 (speed) + MysticXXX_MMH3-V4 (de-oil)**; enable **upscale_final + DLSS5 engine** for 4K; 4090 tip: 1.5x boost + DLSS 2.66x
- 验证：py_compile PASS；备份 `extender.py.bak_4kdirect_pre_v14178` / Verified: py_compile PASS; backup `extender.py.bak_4kdirect_pre_v14178`
- 生效：重启 ComfyUI 后生效（下拉选「4K直出 秘制酱料」）/ To take effect: restart ComfyUI and pick "4K直出 秘制酱料" in the render-pipeline dropdown

### v3.4.12 武戏搭档版工作流（2026-10-23）— 武戏组合拳 7 LoRA 双栈 + LMS upscaler / 武戏搭档 workflow: 7-LoRA dual-stack + LMS upscaler

**配套 `BSAI_H3_Film_Factory电影工厂-MV对口型一镜到底版-武戏搭档-5090.json`（example_workflows/）：** / Companion workflow shipped in example_workflows/:
- **upscaler 默认引用切 LMS 锐利版** `minimax_h3_latent_upscaler_3d_fp16.safetensors` → `h3_upscaler_lms_v0.1.safetensors`（YZ 终极篇推荐 V2/LMS；插件 upscaler 下拉为目录动态扫描，文件就位即可选）/ upscaler default switched to LMS sharp version (`h3_upscaler_lms_v0.1.safetensors`); plugin combo scans the folder dynamically so the file is instantly selectable
- **双 H3LoraStack 串联挂满 7 个 LoRA（YZ 武戏搭档配方）**：栈1(原 1335，已解除 bypass) = H3_Combat_V2@0.65 + H3_Fight_Flow_V1@0.35 + Motion_Repair_V2@0.35 + DMAD 融合 step600@0.8；栈2(新增 1440) = H3_speed_slider_1.1@3 + MysticXXX_MMH3-V1@0.35 + H3电影质感V0.4@0.6（保留质感）；链路 模型→栈1→栈2→渲染主节点 / Dual H3LoraStack chain with 7 LoRAs (YZ combat recipe): stack1 (1335, bypass lifted) = Combat 0.65 + Fight_Flow 0.35 + Motion_Repair 0.35 + DMAD-merge 0.8; stack2 (new 1440) = speed slider 3 + MysticXXX 0.35 + 电影质感 0.6; chain model→stack1→stack2→render node
- **refine_enable 修复**：原工作流二采总开关保存为 false（仅改了 2 步步数 → 一采直出、二采不跑）；武戏搭档版已置 **true**，2 采 2 步正常执行 / refine_enable fix: the saved workflow had the refine master switch false (steps were set to 2 but the switch was off → first-pass-only output); 武戏搭档 sets it **true** so the 2-step refine runs
- 运行要求：渲染管道快捷按钮选「武戏组合拳」（v14.176 内置 6+6/shift12/3/17 帧对齐）；速度档保持 custom / Run: set render-pipeline quick button to 武戏组合拳 (6+6/shift12/3/17-frame alignment built into v14.176); speed preset stays custom

---

### v14.167 (2026-10-22) — 二采 kernel 微基准定论：Sol-Attn 稀疏 pointer 262k=0.99s 即最优，6 块为效率最优点；建议二采 steps 6→4（-33%）/ Refine kernel micro-benchmark verdict: Sol-Attn sparse pointer 262k=0.99s is optimal, 6-block is the efficiency optimum; refine steps 6→4 recommended (-33%)

**核心：二采 338s/步已接近 kernel 理论上限，换 kernel/改块数无法再提速——实测定论（RTX 5090 Laptop, bf16, 14 heads, KJNodes BTHD 布局, randn）：** Sol-Attn 稀疏 pointer 262k=**0.99s** / 334k=**1.70s**（最优）；TMA 262k=1.03s / 334k=1.70s（无增益，pointer 即最优）；SageAttention 2.2 262k=2.20s / 334k=3.93s（慢 2.2×）；flash_attn / sdpa 在 BTHD 布局不适用（invalid argument）。**338s/步 = 6 块 × 50 层 × ~1.13s（含 12% 换页/launch 开销）已匹配理论 297s**；4 块 334k 单 kernel 1.70s 非线性恶化 → 总 4×50×1.70≈340s 并不更快（参考插件 238s 系真实数据稀疏度/autotune 差异，无法复刻）。**剩余提速仅两条：①二采 steps 6→4（工作流 w28，-33%：338→~225s/步，FastH3 4-step LoRA 原生设计）；②换 w4a8 轻量模型（~12GB 全驻留去换页，日志 v1.65 显存预算警告即流式采样代价）。** / Core: refine 338s/step is already near the kernel ceiling — no kernel/block-count change can help further. Measured (RTX 5090 Laptop, bf16, 14 heads, KJNodes BTHD layout, randn): Sol-Attn sparse pointer 262k=**0.99s** / 334k=**1.70s** (best); TMA 262k=1.03s / 334k=1.70s (no gain, pointer is already optimal); SageAttention 2.2 262k=2.20s / 334k=3.93s (2.2× slower); flash_attn / sdpa not applicable to the BTHD layout (invalid argument). 338s/step = 6 blocks × 50 layers × ~1.13s (incl. 12% paging/launch overhead) matches the theoretical 297s; 4×334k goes 4×50×1.70≈340s — not faster, due to superlinear 334k kernel time (reference's 238s comes from real-data sparsity/autotune, not reproducible here). Only two real speedups remain: ①refine steps 6→4 (workflow w28, -33%: 338→~225s/step, native to the FastH3 4-step LoRA); ②switch to a w4a8 light model (~12GB fully resident, no paging — the v1.65 VRAM-budget warning is the streaming-sampling cost).
- 工作流：`...v3.1-5090.json` 节点 250 w28 refine steps 6→4（备份 `.bak_w28_6`，回读验证 4）/ workflow node 250 w28 refine steps 6→4 (backup `.bak_w28_6`, read-back verified 4)
- 验证：kernel 实测表见上；w28 回读 PASS / Verified: kernel table above; w28 read-back PASS
- 生效：重载工作流文件后重跑；若 4 步画质有损可改回 6（一行）/ To take effect: reload the workflow file and re-run; revert w28 to 6 if 4 steps hurt quality

---

### v14.166 (2026-10-22) — 二采加速再突破：head 分组 4→1（每层 4 次串行 kernel → 1 次 14-head 并行 kernel）/ Refine speedup round 3: attention head-chunks 4→1 (per-layer 4 serial kernels → 1 parallel 14-head kernel)

**核心：二采 delegate 上把 KJNodes `minimax_head_chunks` 从 4 降到 1。** v14.164 健康区（每块 261,936 tokens ≤270k）后 Sol-Attn workspace 随 token 平方缩水（873k 全幅 6.33GB → 262k ≈0.6-1.9GB，reserve 6.9GB 内），v1.44 时期为 873k 病态大 token 让位的 head 分组不再必要：head_chunks=4 让每层注意力跑 **4 次 262k 长度串行 kernel**（每次仅 3.5 heads），实测每块 ~63s（50 层 × 4 × ~0.3s）；head_chunks=1 让每层跑 **1 次 14-head 并行 kernel**，kernel 调用次数 ×0.25、并行度 ×4，每块 kernel 时间预期减半（~30s），6 块 → ~200s/步（380s 再快 ~47%）。**仅改二采 delegate**（v14.145 重建段 L3454 后），一采 sampling_model 保持 head_chunks=4 不受影响；显存：中间激活 +~1GB、workspace 1.9GB，delegate 驻留 11.8GB + 换页后 24GB 内。** / Core: drop KJNodes `minimax_head_chunks` 4→1 on the refine delegate. With v14.164 healthy-zone tiling (261,936 tokens/block ≤270k) the Sol-Attn workspace shrinks with tokens (873k full-frame 6.33GB → 262k ≈0.6-1.9GB, inside the 6.9GB reserve); the v1.44-era head-grouping made for 873k pathological tokens is no longer needed: head_chunks=4 runs each layer as **4 serial 262k-long kernels** (3.5 heads each) ≈63s/block measured (50 layers × 4 × ~0.3s); head_chunks=1 runs **one parallel 14-head kernel** per layer — 0.25× kernel launches, 4× parallelism, expected ~half the per-block kernel time (~30s), 6 blocks → ~200s/step (another ~47% below 380s). Delegate-only change (after the v14.145 rebuild block L3454); the first-pass sampling model keeps head_chunks=4; VRAM: +~1GB intermediates, 1.9GB workspace, fits 24GB with 11.8GB delegate resident.
- `extender.py`：v14.145 二采 delegate 重建段 head_chunks 4→1 + 显存/回退安全（OOM 会走既有 fallback）/ v14.145 refine-delegate rebuild block head_chunks 4→1 + OOM-safe (existing fallbacks intact)
- 验证：py_compile PASS；预期日志 `v14.166 二采 delegate head_chunks 4->1`，二采每步应降到 ~200s（待用户重跑实测）/ Verified: py_compile PASS; expected log `v14.166 二采 delegate head_chunks 4->1`, refine step should drop toward ~200s (pending user re-run)
- 后续候选（未启用）：Sol-Attn int8_qk（routing 精度风险，画质优先不动）；block_cache/CacheDiT 本机未装插件不可用 / Next candidates (not enabled): Sol-Attn int8_qk (routing precision risk, quality-first); block_cache/CacheDiT unavailable — plugins not installed

---

### v14.158-159 (2026-10-21) — BSAI 一镜到底旁支模式 + 一镜到底×歌曲自动分CLIP（落地 B站 MinimaxH3 长视频一镜到底工作流方法）/ BSAI One-Shot (seamless long-take) side mode + song-driven auto CLIP splitting (ported from the Bilibili MinimaxH3 one-shot workflow)

**核心：新增 `one_shot_mode`（off 分镜剪辑 / on 一镜到底）：①每段提示词自动注入“不切场/不转场/镜头持续跟随主体”（用户已写同义则跳过）；②强制段间 motion context（上一段 latent 尾部作为 Add Guide 等效锚点引导本段）；③合并改无缝 concat 零转场。新增 `one_shot_clip_duration`：连接 lip_audio 歌曲且 one_shot_mode=on 时，自动 CLIP 数 = 歌曲时长 ÷ 本值（向上取整），末段自动取剩余时长并自动补齐/对齐 CLIP 卡片；0 = 关闭自动分。** / Core: new `one_shot_mode` (off=per-clip xfade edit / on=seamless long take): ①auto-injects "no cut / no transition / camera keeps following the subject" per clip (skipped when the user already wrote it); ②forces inter-clip motion context (previous clip's latent tail as an Add-Guide-equivalent anchor); ③merge switches to zero-transition concat. New `one_shot_clip_duration`: with lip_audio connected and one_shot_mode=on, target CLIP count = song length ÷ value (ceil), the tail clip takes the remainder, and CLIP cards are auto-aligned/back-filled; 0 = disabled.
- `extender.py` / `web/extender.js`：66 键布局（新增 2 个 widget）；对口型音频按每段时长切分逐段驱动口型 / 66-key layout (2 new widgets); lip audio split per-clip drives lips segment by segment
- 验证：晚风-伍佰 225.3s ÷ 12s = 19 CLIP，与 19 镜一镜到底分镜完全对齐（末镜 9.3s 实际尾长，零缩放）/ Verified: 晚风-伍佰 225.3s ÷ 12s = 19 CLIPs, exactly matching the 19-shot one-shot storyboard (tail clip 9.3s, no rescale)

---

### v14.165 (2026-10-22) — 二采画质修复：VAE 解码切换 fp16 + 健康区分块消除伪影（"2采慢+画质糊"配套根治）/ Refine quality fix: fp16 VAE decode + healthy-zone tiling to kill artifacts (pairs with the v14.164 speedup)

**核心①：工作流 VAE 解码从 int8 量化版切到 fp16 原版（节点 195 `minimax_h3_video_vae_int8_convrot.safetensors` → `minimax_h3_video_vae_fp16.safetensors`，原文件已备份 `.bak_vae_int8`）。** 二采 latent 120×68 直接经 VAE decode 到 1920×1088，int8_convrot 量化 VAE 在 2× 放大下会明显软化纹理/放大噪点——实测抽帧（面部特写噪点、背景糊、产品标签不可读）与量化解码特征吻合。fp16 原版是官方/支持库优先选择（director catalog fp16 第一优先），解码细节完整；解码期 diffusion/TE 已 detach，4.85GB 全量加载在 24GB 上无压力。** / Core ①: the workflow VAE decode switches from the int8-quantized build to the fp16 original (node 195 `minimax_h3_video_vae_int8_convrot.safetensors` → `minimax_h3_video_vae_fp16.safetensors`; the original file is backed up as `.bak_vae_int8`). The refine latent 120×68 is decoded straight to 1920×1088; the int8_convrot quantized VAE visibly softens texture and amplifies noise at 2× upscale — matching the frame evidence (facial noise, soft background, unreadable product label). fp16 is the official/support-library first choice (director catalog puts fp16 first), with complete decode detail; diffusion/TE are already detached during decode, so 4.85GB full load is fine on 24GB.
**核心②：v14.164 健康区分块（6×261,936 tokens ≤270k）同时是画质修复——** 插件 spatial 分块自认副作用 "may show background swelling/seams"，实测视频背景蓝色光斑/竖纹/整体软糊正是 334k 灰色区（Sol-Attn 稀疏在 293k~440k 未实测区间，routing 不稳定）+ 分块独立采样所致；健康区 262k 与参考插件"无雪花"区间一致，kernel 与 routing 均稳定。** / Core ②: the v14.164 healthy-zone tiling (6×261,936 tokens ≤270k) is also the quality fix — the plugin's own spatial-tiling tooltip admits "may show background swelling/seams"; the observed blue glows / vertical texture / overall softness match the 334k grey zone (Sol-Attn sparse routing unstable in the unmeasured 293k–440k band) plus per-tile independent sampling. The healthy 262k zone matches the reference plugin's "no-snow" range — kernel and routing both stable.
- 工作流：`BSAI_H3_Film_Factory...v3-5090.json` 节点 195 VAELoader int8→fp16（备份 `.bak_vae_int8`）/ workflow node 195 VAELoader int8→fp16 (backup `.bak_vae_int8`)
- 验证：JSON 回读确认 fp16 已写入；py_compile（v14.164 既有）通过 / Verified: JSON re-read confirms fp16; py_compile (v14.164) passes
- 生效：重启 ComfyUI（8191 端口）重跑带货 clip；预期 `Refine 分块二采已启用: n_tiles=6`（v14.164）+ VAE 加载日志 `minimax_h3_video_vae_fp16.safetensors` / To take effect: restart ComfyUI (port 8191) and re-run; expect `n_tiles=6` (v14.164) + VAE load log `minimax_h3_video_vae_fp16.safetensors`
- 可选项（画质进一步上探）：二采 steps 6→8（v14.164 提速后每步成本大幅下降，8 步纹理更实）；denoise 保持 0.55（v14.157 已验证低照度补细节） / Optional (further quality): refine steps 6→8 (much cheaper per-step after v14.164; 8 steps = firmer texture); keep denoise 0.55 (v14.157 validated for low-light detail)

---

### v14.164 (2026-10-22) — 二采加速：分块粒度自适应到 Sol-Attn 稀疏健康区（本机 399s/步 → 预期 1/4~1/8）/ Refine speedup: tile granularity auto-tuned into the Sol-Attn sparse healthy zone (this PC 399s/step → expected 4–8× faster)

**核心：二采空间分块的每块 token 压进 Sol-Attn kernel 健康区（≤270k），从"灰色区 dense/慢稀疏"切回"健康区稀疏"。** Sol-Attn kernel 病态基准（comfy_kitchen `ck.sol_attn`，RTX 5090 24GB 实机同参）：218k=0.97s / 293k=0.70s（健康），440k>45s / 873k>600s（病态）。v14.149 固定 n_tiles=4 时每块 latent 46×68×107=334,696 tokens，落在 293k 与 440k 之间未实测的灰色区——本机（5090 Laptop sm120）实测每块 ~90s+，二采 4 块合计 ~399s/步。v14.164 新增 `_ff_auto_refine_tile_count()`：按二采 latent 实际尺寸（T×minHW×(axis/n+2·overlap_latent)）自动求"每块 ≤270k 的最少块数"，主分块/v14.149 自动分块/v1.92 fallback 三处统一接入；120×68×107 → 6 块（每块 261,936 tokens，健康区 0.7s/块级稀疏），用户显式请求值每块已在健康区时保持请求（分块越少 forward/搬运越少）。** / Core: each refine spatial tile's token count is forced into the Sol-Attn kernel healthy zone (≤270k), switching from "grey-zone dense/slow-sparse" to "healthy-zone sparse". Sol-Attn pathological benchmarks (comfy_kitchen `ck.sol_attn`, RTX 5090 24GB, same params as this machine): 218k=0.97s / 293k=0.70s healthy; 440k>45s / 873k>600s pathological. v14.149's fixed n_tiles=4 yields 46×68×107=334,696 tokens/tile — the unmeasured grey zone between 293k and 440k — which measures ~90s+/tile here (5090 Laptop sm120), ~399s/step for 4 tiles. v14.164 adds `_ff_auto_refine_tile_count()`: it computes the minimal tile count whose per-tile tokens ≤270k from the actual refine latent (T×minHW×(axis/n+2·overlap_latent)), and wires it into all three tile entry points (main refine wrap / v14.149 auto-tile / v1.92 OOM fallback). 120×68×107 → 6 tiles (261,936 tokens each, healthy 0.7s/tile-class sparse); a requested value already in the healthy zone is kept (fewer tiles = fewer forwards / less weight paging).
- `extender.py`：新增 `_ff_auto_refine_tile_count(samples, requested, overlap_px, max_tiles=8)`；三处分块 wrap 接入 / new helper + wired into the three tile wrap sites
- 研究结论（社区检索通道 general_search/GitHub 站内被环境限制，改为本机实证）：本机已装 `sageattn3 1.0.0`（SageAttention 3，Blackwell FP4 注意力，专为 sm120 优化）与 `spas_sage_attn 0.1.0`（仅编译 sm80/89/90，无 sm120，不可用于 5090）。sageattn3 小规模（≤4096 头长）可用且与 sdpa 对齐，但长序列（≥64k）触发 `cudaErrorMisalignedAddress`（上游稳定性缺陷），故本次**未**接入生产，仅记录为后续 dense 兜底候选；本机当前 dense 路径为 KJNodes head 分组 + SageAttention 2.2（sm120 效率一般）。本次以"每块 token 健康化让 Sol-Attn 稀疏（int8）全程接管"为主升级路径。 / Research note (general_search & GitHub site search blocked by environment; validated locally instead): `sageattn3 1.0.0` (SageAttention 3, Blackwell FP4 attention for sm120) and `spas_sage_attn 0.1.0` (sm80/89/90 only, unusable on 5090) are installed. sageattn3 works and matches sdpa at small scale (≤4096), but long sequences (≥64k) hit `cudaErrorMisalignedAddress` (upstream stability bug) — NOT wired into production this round, recorded as a future dense-fallback candidate. The current dense path is KJNodes head-grouping + SageAttention 2.2 (mediocre on sm120). Primary upgrade: per-tile token health so Sol-Attn sparse (int8) runs the whole refine.
- 验证：py_compile 通过；后端 python 模拟 `_ff_auto_refine_tile_count`（120×68×107→6，每块 261,936 ≤270k；60×34 与 32×32 保持请求值；overlap=0 保持请求值）通过 / Verified: py_compile pass; backend-python simulation of `_ff_auto_refine_tile_count` (120×68×107→6 at 261,936/tile ≤270k; 60×34 & 32×32 keep requested; overlap=0 keeps requested) pass

---

### v14.163 (2026-10-22) — TST 内置化：粉丝无需再安装 comfyui-SelfLift / TST vendored: fans no longer need a separate comfyui-SelfLift install

**核心：把 comfyui-SelfLift 的 TST 关键文件 `h3_tst.py` 原样内置进插件 `vendor/selflift_tst/`（含 NOTICE.md / PROVENANCE.json 溯源声明），`_apply_h3_tst` 改为优先用 importlib 按文件加载内置副本（不污染 sys.path），外部 comfyui-SelfLift 仅作回退。P2 少步数画质补偿（selflift_tst_enable / selflift_tst_tau）开箱即用，分发给粉丝时少一个前置安装项。** / Core: the SelfLift TST key file `h3_tst.py` is vendored byte-for-byte into `vendor/selflift_tst/` (with NOTICE.md / PROVENANCE.json provenance), and `_apply_h3_tst` now loads the built-in copy first via importlib by file path (no sys.path pollution), falling back to an external comfyui-SelfLift only if present. The P2 few-step quality compensation (`selflift_tst_enable` / `selflift_tst_tau`) now works out of the box — one less prerequisite for fans.
- `vendor/selflift_tst/h3_tst.py`：上游原样副本（sha256 `36b9d849...`，与 selflift-Avatar published 版本一致）/ verbatim upstream copy (sha256 `36b9d849...`, matching the selflift-Avatar published build)
- `extender.py` `_apply_h3_tst`：内置 vendor 优先 → 外部 comfyui-SelfLift 回退，日志标注来源 / built-in vendor first → external fallback, source tagged in the log
- 验证：py_compile 通过；后端 python 模拟 importlib 加载 + patch_model 调用链（wrapper 挂载 `diffusion_model/selflift_h3_tst` + `optimized_attention_override` 注入）通过 / Verified: py_compile pass; backend-python simulation of importlib load + patch_model call chain (wrapper `diffusion_model/selflift_h3_tst` + `optimized_attention_override` injected) pass

---

### v14.162 (2026-10-22) — 一镜到底衔接修复（二采保留 motion-context keyframe）+ 4090 clip3 CUDA 崩溃修复（异步编码并发隔离）/ One-shot continuity fix (refine keeps motion-context keyframes) + 4090 clip3 CUDA crash fix (async-encode concurrency isolation)

**核心①：二采不再清空 motion-context keyframe。** 旧 v2.55b 在二采（denoise=0.55 的重新采样，会改变画面）完全清空 keyframe，导致"上一段尾帧"锚定只在一采生效、二采被冲掉 → 段间画面漂移/虚影，一镜到底尾帧引导链断裂（4090 实机 3 clip 视觉实证：clip1/clip2 首帧出现半透明虚影、闭眼/耳机等细节逐段漂移）。修复：把一采 keyframe latent 空间 trilinear resize（D 维不变，按 motion_context_ram v1.25 三元组写法）到二采 latent 分辨率后保留注入，使尾帧引导贯穿一采+二采，接缝无缝。** / Core ①: the refine pass no longer wipes motion-context keyframes. Old v2.55b fully cleared them during refine (a denoise=0.55 re-sampling that changes content), so the previous-clip tail anchor only held in the first pass and was washed out by the second — inter-segment drift/ghosting, the one-shot tail-anchor chain broke (proven on the 4090's 3 clips: ghosting on clip1/clip2 heads, eye-open/headphone details drifting). Fix: trilinear-resize (D kept, same triple-size form as motion_context_ram v1.25) each first-pass keyframe latent to the refine latent resolution and keep injecting, so the tail-frame guide runs through both passes for a seamless seam.
- `extender.py` L3188：v2.55b 清空逻辑 → v14.162 保留 + resize（缺尺寸/异常时安全降级为原行为）/ L3188: v2.55b wipe → v14.162 keep + resize (safe fallback to old behavior on missing shape / exception)

**核心②：每段 TE 文本编码前等待异步编码线程完成。** 4090 实机 clip3 崩在 `_make_ref2va_conditioning → TE encode`（llama o_proj 的 comfy_kitchen 量化权重 `clone()` → `CUDA error: unspecified launch failure`）。根因：clip2 的异步编码（后台线程 VAE decode + NVENC）与 clip3 的 TE 全量驻留（14.9GB）+ 量化 cast 并发抢 GPU → CUDA 上下文损坏。修复：clip 循环 conditioning 前同步等待 `_pending_enc` 全部完成并消费（解码+落盘），杜绝并发。** / Core ②: wait for the async-encode thread before each clip's TE text encoding. The 4090 crashed on clip3 inside `_make_ref2va_conditioning → TE encode` (comfy_kitchen quantized weight `clone()` in llama o_proj → `CUDA error: unspecified launch failure`). Root cause: clip2's async encoding thread (VAE decode + NVENC) was still grabbing the GPU while clip3's TE loaded fully (14.9GB) and cast quantized weights — corrupting the CUDA context. Fix: synchronously wait for and consume all `_pending_enc` before conditioning each clip.
- `extender.py` L7300：`for _pev_done, ... in _pending_enc: _pev_done.wait()` + `_flush_pending_enc(False)` / wait on all pending done-events, then flush (decode + persist)
- 验证：py_compile 通过；keyframe resize 全链模拟通过（[1,24,1,60,34]→[1,24,1,68,120]×3 块） / Verified: py_compile pass; full-chain keyframe resize simulation pass ([1,24,1,60,34]→[1,24,1,68,120] ×3)
- 生效：重启 ComfyUI（8191 端口）后重跑一镜到底；应看到 `v14.162 二采保留 N 个 motion-context keyframe` 与 `v14.162 已等待 N 段异步编码完成` / To take effect: restart ComfyUI (port 8191) and re-run one-shot; expect `v14.162 二采保留 N 个 motion-context keyframe` and `v14.162 已等待 N 段异步编码完成`

---

### v14.161 (2026-10-22) — P2 TST 注入修复：双保险定位 comfyui-SelfLift（兼容新版 ComfyUI 隔离加载）/ P2 TST injection fix: dual-path resolution of comfyui-SelfLift (compatible with new isolated custom-node loading)

**核心：新版 ComfyUI（core 0.3.384+）改用 `governance.pack_module_spec` 隔离加载自定义节点，不再把节点目录注入 `sys.path`，导致 `_apply_h3_tst` 里裸 `from h3_tst import patch_model` 报 `No module named 'h3_tst'`（P2 TST 时间状态传输补偿静默跳过，少步数画质补偿失效）。修复：定位 comfyui-SelfLift 目录改双保险——①基于 `__file__` 向上两级推导；②未命中时用 ComfyUI 官方 `folder_paths.get_folder_paths("custom_nodes")` 兜底；并先校验 `h3_tst.py` 存在性，缺失时打印期望路径而非笼统提示"需安装"。** / Core: new ComfyUI (core 0.3.384+) loads custom nodes via `governance.pack_module_spec` in isolation and no longer injects node dirs into `sys.path`, so the bare `from h3_tst import patch_model` in `_apply_h3_tst` raised `No module named 'h3_tst'` (P2 Temporal State Transport compensation silently skipped, few-step quality compensation lost). Fix: dual-path resolution of the comfyui-SelfLift dir — ① derive from `__file__` two levels up; ② fall back to ComfyUI's official `folder_paths.get_folder_paths("custom_nodes")` when missed; and pre-check `h3_tst.py` existence, printing the expected path instead of a generic "please install".
- `extender.py`：`_apply_h3_tst` 双路径解析 + 存在性校验 / dual-path resolution + existence check in `_apply_h3_tst`
- 验证：py_compile 通过；后端 python 模拟两条路径均命中 `custom_nodes\comfyui-SelfLift\h3_tst.py` 且 `from h3_tst import patch_model` 成功 / Verified: py_compile pass; both paths resolve to `custom_nodes\comfyui-SelfLift\h3_tst.py` in the backend python and `from h3_tst import patch_model` succeeds
- 生效：重启 ComfyUI（8191 端口）后重跑一镜到底，应恢复日志 `P2 SelfLift H3 TST 注入: tau=0.2` / To take effect: restart ComfyUI (port 8191) and re-run one-shot — the log should restore `P2 SelfLift H3 TST 注入: tau=0.2`

---

### v14.160 (2026-10-22) — one_shot_clip_duration 默认 12s：与对口型分镜 12s/镜 对齐 / default 12s: aligned with the 12s/CLIP lip-sync storyboard

**核心：默认每段 12s。225.3s 歌曲 ÷ 12 = 19 CLIP，与 19 镜分镜一一对应；旧 10s 默认会把 19 镜分镜自动切成 23 段，多出段复制首个分镜模板、且每段时间轴与分镜文案（0-3/3-6/6-9/9-12 秒拍段）错位。** / Core: 12s default per clip. A 225.3s song ÷ 12 = 19 CLIPs, one-to-one with a 19-shot storyboard; the old 10s default auto-split a 19-shot board into 23 segments whose extras copied the first shot's template and whose timeline no longer matched the board's 0-3/3-6/6-9/9-12s beats.
- `extender.py`：INPUT_TYPES default 10→12、运行时回退 10→12、tooltip 示例同步（5分钟 ÷ 12s = 25 CLIP）/ INPUT_TYPES default 10→12, runtime fallback 10→12, tooltip example updated (5-min ÷ 12s = 25 CLIPs)
- `web/extender.js`：前端 DEFAULTS 槽位 64 默认 10→12 / front-end DEFAULTS slot 64 default 10→12

---

### v14.156 (2026-10-21) — 输出尺寸强制对齐工作流声明：二采倍率被显存预算降级时，成片精确重采样到 1920×1088 / Output size enforced to the declared size: when the VRAM budget silently downgrades the refine factor, decode resamples to 1920×1088

**核心：根因 = 显存预算预检（v1.74，`extender.py` 约 2977 行）在 24GB 卡 + H3 int8（约 21.8GB 模型）上把声明的二采 x2.0 静默降级为 x1.5（`_ws_tbl = {1.0:1.5, 1.5:2.6, 2.0:4.5}`，x2.0 需 resident ≥10GB 不满足、x1.5 满足），且链首段降级后全局锁定。geometry 由 120×68 变成 90×51，经 `_ff_snap_to_multiple(…,40px//16=2)` 向下取整为 90×50 → 解码像素 1440×800，与工作流的 1920×1088 不符。工作流节点 250 的 width/height 被 link 覆盖，真实分辨率来自 ResolutionSelector（16:9 / 0.5MP / 32 → 960×544），二采 x2.0 才是 1920×1088。修复策略（保留 1.5x 二采的稳定与速度）：不解链、不重采样 latent，只在解码/导出时把成片精确重采样到声明尺寸。** / Core: root cause is the v1.74 VRAM-budget precheck (~line 2977) silently downgrading the declared refine x2.0 to x1.5 on a 24GB laptop GPU with the ~21.8GB H3 int8 model (x2.0 needs resident ≥10GB, x1.5 passes), and the downgrade is then locked for the whole chain. Geometry 120×68 becomes 90×51, snapped down to 90×50 by `_ff_snap_to_multiple(…, 40px//16=2)` → 1440×800 instead of the declared 1920×1088. Fix keeps the stable/fast 1.5x latent refine and only resamples the decoded/output pixels to the declared size.
- `extender.py`：manifest 新增 `output_width` / `output_height` / `declared_refine_factor`（一采分辨率 × 声明二采倍率） / manifest gains `output_width`, `output_height`, `declared_refine_factor` (first-pass resolution × declared refine factor)
- `motion_context_disk.py`：`_decode_single_clip_to_blob` 读取目标尺寸，逐批 `interpolate(mode="bicubic", antialias=True)`（失败回退 bilinear）后编码；跳过条件增加 `decoded_mp4_width/height` 校验，并回写实际编码尺寸 / reads the target size, per-batch bicubic (antialias) resample before encoding (bilinear fallback), skip condition now validates decoded pixel size, writes back the actual encoded size
- 新增 `_rescale_segment_blob`：已有 v3 blob 像素不符时用 ffmpeg `scale=W:H:flags=lanczos` 重编码视频轨 + `-c:a copy` 保留原音轨（不丢对口型歌曲混音、避免逐段 VAE 重解码）。数据文件为 append-only 布局（每段 latent → blob → decoded_audio），仅尾段 truncate 重写，非尾段追加到文件末尾并更新偏移，避免删除后续段 latent / new `_rescale_segment_blob`: ffmpeg lanczos rescale of an existing v3 blob with audio stream-copied (no VAE re-decode, no lip-sync mix loss). The data file is append-only (latent → blob → decoded_audio per segment); only the tail segment is truncated and rewritten, non-tail segments append at EOF with updated offsets so later latents are never deleted
- `extender.py` 合并路径：除"缺 blob"外，"尺寸与声明的 output_width/height 不符"也会触发校正（自动走 ffmpeg 重采样），避免 1440×800 与 1920×1088 混拼导致 concat 失败 / merge path now also corrects blobs whose decoded size differs from the declared output size (auto ffmpeg rescale), preventing concat failure when mixing 1440×800 and 1920×1088
- `extender.py` 链几何比较：识别"声明 x2.0 / 实际 x1.5"这一种显存预算降级组合并保留缓存（不再每次执行误判分辨率变化清链、被迫从 clip1 重跑）；像素由上述重采样兜底 / chain-geometry check recognizes the single budget-downgrade combination (declared x2.0 / actual x1.5) and keeps the cache instead of wiping it and restarting from clip1 every run
- 验证：py_compile 通过；实机验收 = 重启 ComfyUI → 重开 v2.1 → 续跑/合并，per-clip 与 merged 成片应为 1920×1088（旧 1440×800 段自动重采样，无需重渲 latent） / Verified: py_compile pass; acceptance = restart ComfyUI, reopen v2.1, continue/merge — per-clip and merged outputs should be 1920×1088 (old 1440×800 blobs are rescaled automatically, no latent re-render)

---

### v14.154 (2026-10-21) — 对口型纯歌曲输出：重叠切割先于重采样，根治 clip2+ 音频晚 0.75s（跳针+整段口型错位）/ Lip-sync pure-song output: overlap cut before resample — fixes clip2+ audio lagging 0.75s (skip + whole-clip lip offset)

**核心：`motion_context_disk.py` 纯歌曲输出混音段的采样率域顺序错误：`overlap_samples` 由 `_split_lip_audio_by_clips` 按段**原始采样率**计算（44.1kHz 歌曲 = 88200 样本/2.0s），但旧代码先把段音频重采样到模型 32kHz、再按 88200 样本切头——在 32kHz 域切 88200 = 2.756s（多切 0.756s），导致 clip2 起每段输出音频整体晚 ~0.75s。实机取证（互相关定位，score 0.993）：clip1 = 原曲 0.000s（无重叠切割故正常），clip2 = 原曲 12.986s（应为 12.250s）→ 衔接处歌曲凭空跳 0.75s（跳针），且口型按注入的正确歌曲段生成、听到的音频却晚 0.75s → 整段"口型完全没对上"。修复：先在段原始采样率域切重叠、再重采样对齐。clip1（overlap=0）本就走正确路径，不受影响。** / Core: the pure-song output mix in `motion_context_disk.py` applied the overlap cut in the wrong sample-rate domain. `overlap_samples` is computed by `_split_lip_audio_by_clips` in the segment's **native** sample rate (44.1kHz song → 88200 samples = 2.0s), but the old code resampled the segment to the model's 32kHz first, then cut 88200 samples — i.e. 2.756s instead of 2.0s, shifting every clip2+ output audio ~0.75s late. Forensics (cross-correlation, score 0.993): clip1 = song 0.000s (no overlap cut, correct), clip2 = song 12.986s (should be 12.250s) → a 0.75s hole in the song at the seam ("needle skip"), plus lips generated to the correct injected segment while the audible audio lags 0.75s → whole-clip "lip-sync completely off". Fix: cut the overlap in the native sample-rate domain first, then resample. clip1 (overlap=0) was already on the correct path.
- `motion_context_disk.py`：`_decode_single_clip_to_blob` 混音段——`_ov` 切割上移至 `_lip_sr` 原生域（重采样之前），删除原重采样后的重复切割块；维度/声道对齐与 `_target` 长度对齐逻辑不变 / mix block reordered: `_ov` cut moved into the native `_lip_sr` domain (before resample); old post-resample duplicate cut removed; dim/channel alignment and `_target` length logic unchanged
- 验证：py_compile 通过；实机验收 = 重启 ComfyUI 后重渲 clip2 + 合并输出，clip2 预览音频经互相关定位应 = 原曲 12.250s（±0.02s 编码器延迟内），衔接处无跳针、口型对齐 / Verified: py_compile pass; acceptance = restart ComfyUI, re-render clip2, merge — clip2 audio should cross-correlate at song 12.250s, no seam skip, lips aligned
- 遗留观察（非本次修复范围）：衔接处画面存在 ~5 帧量级的内容前跳（帧差 6.5 vs 段内 1.15，同场景无曝光跳变），为模型续走行为；音频修复后衔接观感应大幅改善，如仍明显再单独立项查 motion context 续走 / Residual note (out of scope): a ~5-frame content advance at the seam (frame diff 6.5 vs intra 1.15, same exposure) — model continuation behavior; the seam should feel far cleaner once audio is fixed

---

### v14.153 (2026-10-20) — 二采省显存模式：移植 selflift-Avatar global 全上下文路径（spatial 可切换）/ Refine memory-saving mode: ported selflift-Avatar global-context path (switchable with spatial)

**核心：二采新增 `refine_mem_mode` 下拉（序列化 widget 第 62 位 = 全部 widget 最末尾；置于 optional 的 prompt_pack 之后、asset_library 之前，required 列表零插入，所有历史工作流零错位）。`global` 模式移植 selflift-Avatar (commit 5b93b6c) global-context 省显存路径（源码暂存 `vendor/selflift_avatar/`）：全序列 attention 一次跑（无空间分块、无接缝/背景膨胀），norm/proj/MLP 按 token_chunk=4096 分块压激活显存。与 KJNodes head 分组（object_patches attn.forward 层）、Sol-Attn override（v14.148 dense 门保持注入）、v14.145 delegate 三机制源码级兼容；检测到自制 override 时按上游语义自动回退全序列 global 纯 dense 分块路径。包装失败自动回退 spatial 分块保底。** / Core: new `refine_mem_mode` dropdown (serialized widget index 62 = the very last widget; placed in optional after prompt_pack and before asset_library — zero insertion into required, so every legacy workflow loads without misalignment). The `global` mode ports the selflift-Avatar global-context memory-saving path (source staged in `vendor/selflift_avatar/`): full-sequence attention in one pass (no spatial tiles, no seams/background swelling) with norm/proj/MLP token-chunked at 4096 to bound activation VRAM. Source-level compatible with KJNodes head-grouping, the Sol-Attn override (v14.148 dense gate stays injected) and the v14.145 delegate; with a custom override detected it follows upstream semantics and falls back to the full-sequence global chunked path automatically. On wrapper failure it falls back to spatial tiling as a safety net.
- **前端 `H3LegacyCompat` 按全部真实工作流地面实况重写（向前兼容核心，本轮二次修正）**：全量扫描工作流目录 50 个真实文件确认——`prompt_pack` 是 H3_PROMPT_PACK 自定义类型 = 前端 socket，从不序列化进 widgets_values；`h3_extender_timeline` dom widget 虽标 serialize:false 仍被现役前端序列化为尾部空串；故真实序列 = 62 个后端 required widget（0..61）+ refine_mem_mode（62）+ timeline dom（63）。KEYS/DEFAULTS 对齐为 64 项（prompt_pack 移出、62=refine_mem_mode、63=timeline 占位），OPTIONS 新增 refine_mem_mode 选项归一。detect 新分支：`CUR64`（n=64 现役直抄——用户 v2.0 工作流即此布局，widget 序列与插件完全一致）、`N63`（n=63 无 rmm 仅尾部 timeline）、`O63`（n=63 被旧兼容层污染过的混合布局，判据 `w[48]` 为 number，57+ 垃圾位丢弃）、`N62`（n=62 v14.150 文件）、`L59`/`L58O` 及防御分支 `L59G`/`CURRENT`。mapTo 统一 64 位输出；所有老纪元分支（L43/L44/L45A/L45B/L45E/L47/L51/L52/L38/L40/L58O/L59/O63）统一走"老坐标系（0..47 同键、48..53 六联包、54..56 env/gain/face）→ 新坐标系 48..56 整体后移 5 位到 53..61"变换，一并修复 v14.150 插入 P0/P2 五参数后最老分支（L43 系/L45A 等）一直存在的 48+ 位 5 位错位 bit-rot（此前仅 L58O 单独修过）。回归 `_backups/h3_regress.js`：提取真实 IIFE + mock 64-widget node，覆盖工作流目录全部 6 个真实长度类（58/59/62/63/63O/64）+ 合成最老布局，**1364 项断言 0 fail**（无 NaN/undefined、NUMERIC/BOOLS 类型正确、锚点落值正确）。后端第二道保险：`refine_mem_mode` 空串在读取处归一为 `spatial (分块,兼容)`，永不传空值进二采。 / Frontend `H3LegacyCompat` rewritten per ground truth from all real workflows (second correction this round): a full scan of 50 real workflow files confirms `prompt_pack` (H3_PROMPT_PACK) is a frontend socket never serialized into widgets_values, while the `h3_extender_timeline` dom widget IS serialized as a trailing '' by the current frontend despite serialize:false — the true sequence is 62 backend required widgets (0..61) + refine_mem_mode (62) + timeline dom (63). KEYS/DEFAULTS realigned to 64 entries (prompt_pack removed; 62=refine_mem_mode, 63=timeline placeholder); OPTIONS gains refine_mem_mode normalization. New detect branches: `CUR64` (n=64 direct copy — the user's v2.0 workflow is exactly this layout), `N63` (n=63 timeline only), `O63` (n=63 polluted hybrid, w[48] numeric, slots 57+ discarded), `N62` (n=62 v14.150 files), `L59`/`L58O` plus defensive `L59G`/`CURRENT`. mapTo unifies to 64 slots; every legacy-era branch now goes through one old→new coordinate transform (old 48..56 → new 53..61, +5 for the P0/P2 five), also fixing the 5-slot misalignment bit-rot the L43-family/L45A branches had carried since v14.150 (previously only L58O was fixed inline). Regression `_backups/h3_regress.js`: real IIFE + mocked 64-widget node across all 6 real length classes in the workflow directory plus synthetic oldest layouts — 1364 assertions, 0 fail. Backend second guard: empty refine_mem_mode normalizes to `spatial (分块,兼容)` at read time.
- **上游版权说明**：selflift-Avatar 仓库暂无 LICENSE，vendor 暂存保留 NOTICE.md/PROVENANCE.json 出处声明，致谢上游及 Fish4AI (comfyui-SelfLift-Fish)。 / Upstream has no LICENSE; vendor staging keeps NOTICE.md/PROVENANCE.json attribution.

### v14.152 (2026-10-19) — 旧工作流 4 参数容错：VALIDATE_INPUTS 跳过校验 + STRING 类型 + None 映射 / Legacy workflow 4-param tolerance: VALIDATE_INPUTS skip + STRING type + None mapping

**核心：粉丝导入老版本分享的工作流时，4 个参数因历史遗留值（`'global_inherit'`、`''`、`False`、`0.0`）被 ComfyUI 前置校验拦截，节点根本无法执行。本轮加三层容错：VALIDATE_INPUTS 跳过 min/max/combo 校验、INT/FLOAT 改 STRING 类型绕开类型转换、函数内容错解析统一归一到默认最低档。** / Core: when importing a legacy workflow, 4 params were blocked by ComfyUI's pre-validation due to legacy values. This round adds three-layer tolerance: VALIDATE_INPUTS skips min/max/combo checks, INT/FLOAT→STRING bypasses type conversion, and in-function fallback normalizes everything to the default-lowest tier.
- **`VALIDATE_INPUTS(**kwargs)`**：新增类方法，带 `**kwargs` 使 ComfyUI 跳过所有参数的 min/max 校验与 combo 选项校验（execution.py 1032/1060 行分支），让 `semantic_bridge_adapter=False`、超范围 float 等历史值能进入 extend()。 / New classmethod with `**kwargs` makes ComfyUI skip all min/max and combo-option checks, letting legacy values through to `extend()`.
- **`temporal_overlap_tokens` INT→STRING**：`int('global_inherit')` 在类型转换阶段必炸，改 STRING 后 `str()` 永远不失败；函数内 `_safe_int` 对非数字取默认 8。 / `int('global_inherit')` always crashes at type-conversion; STRING's `str()` never fails, and `_safe_int` falls back to default 8 for non-numeric input.
- **`semantic_bridge_alpha` FLOAT→STRING**：同理，`float('')` 必炸；改 STRING 后函数内 `_safe_float` 对空串取默认 0.15。 / Same rationale; `_safe_float` falls back to 0.15 for empty strings.
- **`semantic_bridge_adapter` 容错**：`False`/`None`/空串一律视为关闭（最低档），`_sb_adapter.startswith("(")` 判断不受 `False` 影响（已提前转空串）。 / `False`/`None`/empty → treated as off (lowest tier); normalized to empty string before the `startswith` check.
- **`shift_audio` min 0.01→0.0 + None 映射**：老工作流存 `0.0` 合法但被 min 0.01 拦截；min 降为 0.0 允许通过，函数内 `shift_audio<=0` 映射为 `None`（`ModelSamplingAV.audio_scale = shift/None → 1.0`，关闭音频 shift 即最低档），避免除零。`_apply_h3_dual_track_shift` 同步支持 `None`。 / Legacy `0.0` was blocked by min 0.01; min lowered to 0.0, and `<=0` maps to `None` (audio_scale=1.0, audio shift off) to prevent division by zero.
- 验证：py_compile 通过；粉丝重跑老工作流时 4 个报错全部消失，参数自动取默认最低档（temporal_overlap=8, semantic_bridge=off/0.15, shift_audio=off） / Verified: py_compile pass; all 4 legacy errors resolved, params auto-fallback to default-lowest

---

### v14.151 (2026-10-19) — 对口型×上下文参考手动可控：解除强制关闭 + 音频尾对齐注入保同步 / Lip-sync×Context manual control: un-force the auto-disable + tail-aligned audio injection for sync

**核心：对口型（lip_audio 连接）模式下，"上下文参考"恢复用户手动控制（卡片级复选框 + 批量按钮），上下文带来的段间衔接由音频同步三件套保证，输出音频仍与 lip_audio 原始歌曲逐帧对齐。** / Core: in lip-sync mode (lip_audio connected), "Context Reference" returns to full manual control (per-card checkbox + batch button); inter-clip continuity is preserved while output audio stays frame-locked to the original song via the three-piece sync chain.
- **解除三处 v2.117 强制**：① 前端连线强制（v2.117b，`onConnectionsChange`）与轮询兜底（v2.117e）删除——lip_audio 连接不再自动关闭所有 CLIP 的 `context_enabled`；② 后端切分强制（`_split_lip_audio_by_clips` 里 `if lip_audio is not None: _ctx_on=False`）删除——恢复 v2.111 上下文感知切分；③ 后端渲染门禁（`lip_audio is None` 才执行 `motion.apply`）解除。 / Removed three v2.117 force-points: ① frontend connect-forcing (v2.117b) and poll-fallback (v2.117e); ② backend split forcing; ③ backend render gate (`motion.apply` now runs with lip_audio when ctx enabled).
- **音频同步三件套**（ctx_on 时）：① 切分段头部含 1.2s 重叠并记录 `overlap_samples`；② AV latent 音频注入由头对齐改为**尾对齐**（`[-t:]`）——重叠头（上一段的歌）自动丢弃，本段 audio 行精确对应[段起点,段终点]，修复 ctx_on 头对齐会把口型提前 ~1.2s 的隐患；③ 解码混音按 `overlap_samples` 精确跳过段头。ctx_off（零重叠）时尾对齐==头对齐，行为与旧版完全一致。 / Sync chain (ctx_on): ① split keeps 1.2s head overlap recorded as `overlap_samples`; ② AV-latent audio injection switches head-align → **tail-align** (surplus overlap head dropped; this clip's audio rows map exactly to [start,end], eliminating a latent ~1.2s lip-lead bug); ③ decode-mix skips exactly `overlap_samples`. With ctx_off, tail==head so legacy behavior is bit-identical.
- **trim 语义修正**：ctx_on 且 motion context 已注入时保留 `motion.apply` 返回的 trim（上下文帧数，由 join 裁掉上下文头，与音频 overlap 跳过互补）；未注入（ctx_off 或前段缓存缺失）时显式 `trim=0`，杜绝 join 回退默认 22 帧误裁本段开头（v2.117d 老问题在 ctx_on 无缓存分支的死灰复燃点）。 / Trim semantics: keep `motion.apply`'s trim when context was actually injected; force `trim=0` otherwise (ctx_off or missing previous cache) — prevents the join default-22-frame false trim from resurfacing on the ctx_on-no-cache branch.
- 备份：改前快照 `G:\BSAI-ComfyUI-intel-XPU-GPU-NPU-aki\_backups\BSAI-ComfyUI-H3-Film-Factory_LIPCTX_20261019_205047.zip`（回退：删除插件文件夹后解压到 `ComfyUI\custom_nodes\`）。 / Backup: pre-change snapshot at the path above (rollback: delete the plugin folder and unzip into `ComfyUI\custom_nodes\`).
- `extender.py` / `web/extender.js`：如上 5 处；版本横幅 → v14.151 / as above, 5 spots; banner → v14.151
- 验证：py_compile 通过；node --check 通过；实机验收判据 = lip_audio 连接时卡片复选框可自由勾选、日志出现 `对口型+上下文参考: 前段尾部已注入`、clip2+ 画面衔接连贯且歌声与口型/原曲零错位（对照：关闭上下文的行为与 v14.150 完全一致） / Verified: py_compile pass; node --check pass; live acceptance = checkboxes freely toggleable while lip_audio connected, log `对口型+上下文参考: 前段尾部已注入`, clip2+ continuous visuals with song/lips frame-locked (ctx_off behavior identical to v14.150)

---

### v14.150 (2026-10-17) — P0-P2 升级：官方双轨迹采样 + Turbo v4/DMAD 档位 + SelfLift TST 少步数补偿 / P0-P2 upgrade: official dual-track sampling + Turbo v4 / DMAD presets + SelfLift TST few-step compensation

**核心（周报技术落地，用户验收后推送）** / Core (weekly-report tech landing, push after user acceptance):
- **P0 双轨迹采样**：`_sample_h3` 采样前对 model 注入官方 `MiniMaxH3SigmaShift` 等效（`ModelSamplingAV+CONST` patch `model_sampling`，`transformer_options` 写入 `minimax_h3_sigma_shift_video/audio`）——video shift 驱动采样器 sigma 调度，audio schedule 由模型内部从共享 base grid 推导，幂等可关。新 UI 参数：`dual_track_shift`(默认开)、`shift_video`(默认12)、`shift_audio`(默认3)。一采注入后二采 `_refine_model` 自动继承（同 clone 链）。 / **P0 dual-track sampling**: before pass-1 sampling, `_sample_h3` injects the official `MiniMaxH3SigmaShift` equivalent (patch `model_sampling` with `ModelSamplingAV+CONST`, write `minimax_h3_sigma_shift_video/audio` into `transformer_options`) — video shift drives the sampler sigma schedule, audio schedule is derived inside the model from the shared base grid; idempotent and switchable. New UI params: `dual_track_shift` (default on), `shift_video` (default 12), `shift_audio` (default 3). Refine inherits the injection automatically (same clone chain).
- **P1 新档位**：`speed_preset` 新增 `Turbo-v4`（6+4 步、shift 12/3，Turbo LoRA v4 step600 EMA 舒适区）与 `DMAD-4步`（4+2 步、shift 12/2、采样器强制 `lcm`、DMAD 官方配方 LCM+simple、无 CFG≈1）。 / **P1 new presets**: `speed_preset` gains `Turbo-v4` (6+4 steps, shift 12/3, Turbo LoRA v4 step600 EMA comfort zone) and `DMAD-4步` (4+2 steps, shift 12/2, sampler forced to `lcm` per DMAD's official LCM+simple recipe, CFG≈1).
- **P2 SelfLift TST**：新增 `selflift_tst_enable`(默认开) + `selflift_tst_tau`(默认0.2)——采样前对 model 应用 `comfyui-SelfLift` 的 `h3_tst.patch_model`（arXiv:2609.08505 时间状态传输，校正闪烁/身份漂移/不合理运动，开销 1-2%）。依赖 `facok/comfyui-SelfLift` 已随本版安装；未安装自动跳过并提示。 / **P2 SelfLift TST**: new `selflift_tst_enable` (default on) + `selflift_tst_tau` (default 0.2) — applies `comfyui-SelfLift`'s `h3_tst.patch_model` before sampling (arXiv:2609.08505 Temporal State Transport, correcting flicker/identity drift/unphysical motion, 1-2% overhead). Requires `facok/comfyui-SelfLift`, installed with this release; auto-skip with a hint when missing.
- 备份：改前快照已存 `G:\BSAI-ComfyUI-intel-XPU-GPU-NPU-aki\BSAI插件升级备份_20261017\`（回退用）。 / Backup: pre-change snapshot at `G:\BSAI-ComfyUI-intel-XPU-GPU-NPU-aki\BSAI插件升级备份_20261017\`.
- `extender.py`：新增 `_apply_h3_dual_track_shift` / `_apply_h3_tst` 工具函数；`_sample_h3` 签名加 5 参数；INPUT_TYPES 加 5 参数；speed_preset 加 2 档；版本横幅 → v14.150 / `extender.py`: new `_apply_h3_dual_track_shift` / `_apply_h3_tst` helpers; `_sample_h3` gains 5 params; INPUT_TYPES gains 5 params; speed_preset gains 2 options; banner → v14.150
- 验证：py_compile 通过；`main.py --quick-test-for-ci` 加载通过（Film-Factory backend + SelfLift 均 loaded，exit=0）；实机验收判据 = 双轨迹日志 `[H3 Extender] P0 双轨迹采样注入: shift_video=.. shift_audio=..` + TST 日志 + Turbo-v4/DMAD 档位生效 / Verified: py_compile pass; `main.py --quick-test-for-ci` loads clean (Film-Factory backend + SelfLift loaded, exit=0); live acceptance = `[H3 Extender] P0 双轨迹采样注入: shift_video=.. shift_audio=..` + TST log + preset takeover

---

### v14.149 (2026-10-13) — 方案A 补全：token 超阈值自动启用分块二采（对齐参考插件 240s/步 无雪花实测路径）/ Plan A completion: auto-enable spatial-tile refine past token cap (mirrors reference plugin's verified 240s/step no-snow path)

**核心：参考插件实机日志确证其 240s/步 无雪花的机制 = spatial tiles 分块二采（`Refine 分块二采已启用: n_tiles=4 overlap=128px`，`spatial tiles: axis=W size=120 n=4 latent ranges=[(0,46),(22,68),(52,98),(82,120)]`）——每块 W≈46 latent → token ≈ 46×68×107 = 334,696 < 440k 病态线，Sol-Attn 稀疏/head 分组在健康区稳定跑完 2 步（step1 238s、step2 125s、总计 ~6 分钟），画质清晰无雪花。而我们工作流 tiled_refine=False → 二采整段 120x68x107=873,120 tokens 命中 sol_attn kernel 病态区（基准：293k=0.7s 健康 / 440k>45s / 873k>600s 病态）→ 第 1 步 75 分钟卡死。v14.148 只加了 dense 回退门（整段 873k 走 KJNodes 分组+SageAttention 仍偏慢）。本轮补全：二采 latent token 超 350k 阈值且未启用 tiled_refine 时，自动按参考插件参数启用分块（n_tiles=4、overlap=128px）——分块后每块 ~334k < 350k 门阈值 → Sol-Attn 稀疏保留（参考插件同款路径）；分块包装失败时维持 v14.148 dense 回退门，双保险。一采 218k 与用户手动开启 tiled_refine 的场景完全不受影响。** / Core: the reference plugin's live log confirms its 240s/step no-snow mechanism = spatial-tile refine (`Refine 分块二采已启用: n_tiles=4 overlap=128px`, `spatial tiles: axis=W size=120 n=4 latent ranges=[(0,46),(22,68),(52,98),(82,120)]`) — each tile W≈46 latent → token ≈ 46×68×107 = 334,696 < the 440k pathological line, Sol-Attn sparse/head-grouping runs stably in the healthy zone across both refine steps (step1 238s, step2 125s, ~6 min total), crisp no-snow output. Our workflow had tiled_refine=False → refine ran the full 120x68x107 = 873,120 tokens into the sol_attn kernel pathological zone (benchmarks: 293k=0.7s healthy / 440k>45s / 873k>600s pathological) → step-1 75-min hang. v14.148 only added a dense fallback gate (full-frame 873k via KJNodes head-grouping + SageAttention stays slow). This round completes it: when refine latent tokens exceed the 350k cap and tiled_refine is off, auto-enable tiling with the reference plugin's parameters (n_tiles=4, overlap=128px) — each tile ~334k sits under the 350k gate so Sol-Attn sparsity is kept (the reference plugin's exact path); if tiling fails to wrap, the v14.148 dense gate still applies as a second safety net. Pass-1 at 218k and user-enabled tiled_refine are fully unaffected.
- `extender.py`：v14.148 段后新增 v14.149 段——token 超阈值且 `_r_restore_tiles is None` 时动态加载 `bsai_h3_spatial_tiles.py` 并 `wrap_sampler_spatial_tiles(_r_sampler, n_tiles=4, overlap_pixels=128)`，打印启用/失败日志；版本横幅 → v14.149 / `extender.py`: new v14.149 block after the v14.148 gate — when tokens exceed the cap and `_r_restore_tiles is None`, dynamically load `bsai_h3_spatial_tiles.py` and `wrap_sampler_spatial_tiles(_r_sampler, n_tiles=4, overlap_pixels=128)` with enable/failure logs; banner → v14.149
- 验证：py_compile 通过；实机验收判据 = 二采每步 ~240s 量级 + 画质清晰无雪花（等待用户实机复测，预期日志见 v14.148 验收提示 + 新增 `[H3 Extender] v14.149 方案A: ... 自动启用分块二采 n_tiles=4 overlap=128px`） / Verified: py_compile pass; acceptance = refine ~240s/step + crisp no-snow (pending live re-test; expected logs = v14.148 gate note + new `[H3 Extender] v14.149 方案A: ... 自动启用分块二采 n_tiles=4 overlap=128px`)

---

### v14.148 (2026-10-13) — 方案A：二采 Sol-Attn token 规模上限门，根治二采第1步 75 分钟卡死 / Plan A: Refine Sol-Attn Token-Count Cap Gate — Fixes Refine Step-1 75-min Hang

**核心：二采（refine 双采）第 1 步此前满负荷约 75 分钟无产出——独立基准实测已确证根因：comfy_kitchen `sol_attn` kernel 在单段 token n≥~440k 时超线性病态恶化（与 topk routing 无关）：218k→0.97s、293k→0.70s 健康，440k→>45s、873k topk→>600s、873k dense→>60s 病态；二采整段 latent 120x68x107=873,120 tokens 必命中病态区。方案 A（用户已拍板"先 A 保稳"）：Sol-Attn kernel 层新增运行时 token 上限门——`make_override` 读取 `transformer_options["sol_max_tokens"]`（默认 None 完全向后兼容，不影响一采与未注入的其他工作流），单段 tokens 超过阈值即回退 dense（走 KJNodes head 分组 + SageAttention，对齐参考插件 v14.82 实测 240s/步 无雪花）；Film-Factory 二采路径在采样前按实际 latent 单段 token 数注入 `_REFINE_MAX_SOL_TOKENS=350000`（位于健康 293k 与病态 440k 之间），一采 218k 不受影响，二采 873k 必命中降级；时间分块 ≤36 帧（293k）场景仍保留 Sol-Attn 稀疏（方案 B 预留空间）。门在二采完成后自动清理，不残留污染后续 CLIP。** / Core: refine (double-pass) step 1 previously ran ~75 min with no output — root cause now confirmed by standalone benchmarks: the comfy_kitchen `sol_attn` kernel degrades super-linearly at per-call token count n≥~440k (independent of topk routing): 218k→0.97s / 293k→0.70s healthy, 440k→>45s / 873k topk→>600s / 873k dense→>60s pathological; the full refine latent 120x68x107 = 873,120 tokens inevitably hits the pathological zone. Plan A (user approved "A first for stability"): the Sol-Attn kernel layer gains a runtime token cap — `make_override` reads `transformer_options["sol_max_tokens"]` (default None, fully backward-compatible — no effect on pass-1 or uninjected workflows) and falls back to dense (KJNodes head-grouping + SageAttention, matching reference plugin v14.82's measured 240s/step, no snow) when per-call tokens exceed the cap; the Film-Factory refine path injects `_REFINE_MAX_SOL_TOKENS=350000` before sampling based on the actual per-segment latent token count (between healthy 293k and pathological 440k) — pass-1 at 218k is unaffected, refine at 873k always trips the gate; temporal-chunked ≤36-frame (293k) scenarios keep Sol-Attn sparsity (reserved for Plan B). The gate is auto-cleaned after refine, leaving no residue for later clips.
- `sol_attn_minimax_v2.py`（BSAI-ComfyUI-Sol-H3）：`_stats` 新增 `over_max_tokens` 计数；`make_override` 在 tokens 计算后、sink 之前插入上限门（读 `transformer_options["sol_max_tokens"]`，超过即 `return dense()` + 计数 + verbose 一次性日志） / `sol_attn_minimax_v2.py` (BSAI-ComfyUI-Sol-H3): `_stats` gains `over_max_tokens` counter; `make_override` inserts the cap gate right after token count and before sink (reads `transformer_options["sol_max_tokens"]`, returns `dense()` + counts + one-shot verbose log when exceeded)
- `extender.py`：`_r_guider = _BasicGuider(_refine_model)` 前新增 v14.148 段——`_REFINE_MAX_SOL_TOKENS = 350000`；`_ff_extract_members(samples)` 取视频 member 算 `T×H×W` tokens（ndim≥4 保护），超阈值向 `_refine_model.model_options["transformer_options"]["sol_max_tokens"]` 注入并打印降级日志，否则打印保留稀疏日志；二采 finally 清理该键防残留；版本横幅 → v14.148 / `extender.py`: new v14.148 block before `_r_guider = _BasicGuider(_refine_model)` — `_REFINE_MAX_SOL_TOKENS = 350000`; computes `T×H×W` tokens from the video member via `_ff_extract_members(samples)` (ndim≥4 guarded), injects `sol_max_tokens` into `_refine_model.model_options["transformer_options"]` with a downgrade log when over the cap, else logs sparsity kept; refine `finally` cleans the key to avoid residue; load banner → v14.148
- 验证：py_compile 两文件通过；实机验收判据 = 二采每步 ~240s 量级 + 画质清晰无雪花（等待用户实机复测） / Verified: py_compile passes on both files; acceptance criteria = refine ~240s/step + clean no-snow quality (pending user's live re-test)

---

### v14.147 (2026-10-13) — 快捷条枚举按钮改为下拉菜单直接选择 / Quickbar Enum Buttons: Cycle Click → Direct Dropdown Selection

**核心：快捷条上 4 个可循环点击的枚举档位按钮（输出 output_mode / 速度 speed_preset / 口型 refine_lipsync_mode / 超分模式 upscale_mode）不再逐档循环点击，改为点击弹出下拉菜单、直接点选任意档位。** 新增全局唯一下拉菜单状态 `_h3qkOpenMenu` 与 `_h3qkMakeMenu()`（按各档位深浅渐变着色、当前档高亮、点击项 stopPropagation + 回调 apply → w.callback → refresh → updateHidden → setDirtyCanvas）；按钮再次点击收起菜单（toggle），点击菜单外区域或滚动画布自动关闭（document click/wheel 监听）；菜单默认在按钮正下方、接近视口底部时自动翻转到上方；按钮样式/分色/进度条/当前档位名实时显示全部保留。布尔按钮（开/关）行为不变。纯前端 DOM 改动，widgets_values 序列化与后端参数顺序零变化 → 旧工作流零 NaN、零错位、零重连。** / Core: the 4 cycle-click enum preset buttons on the quickbar (输出 output_mode / 速度 speed_preset / 口型 refine_lipsync_mode / 超分模式 upscale_mode) no longer cycle one step per click — clicking now pops a dropdown menu to pick any preset directly. Adds a global singleton menu state `_h3qkOpenMenu` and `_h3qkMakeMenu()` (items tinted per-preset shade gradient, current preset highlighted, click stops propagation and applies via callback → w.callback → refresh → updateHidden → setDirtyCanvas); clicking the button again toggles the menu closed; clicking anywhere outside or scrolling the canvas auto-closes (document click/wheel listeners); the menu drops below the button and flips above when near the viewport bottom; button styling / per-preset coloring / progress bar / live current-preset label all kept. Boolean toggle buttons unchanged. Pure frontend DOM change — widgets_values serialization & backend param order untouched → zero NaN / zero misalignment / zero re-wiring on legacy workflows.
- `web/extender.js`：新增 `_h3qkOpenMenu/_h3qkCloseMenu/_h3qkMakeMenu`；click handler 循环分支改为下拉菜单（toggle + 定位翻转 + 全局关闭监听）；4 个枚举按钮 cycle 与 tints 全部保留（speed_preset 仍 8 档）；说明文案/悬停 title 同步更新；标题两处 → v2.129·v14.147 / `web/extender.js`: new `_h3qkOpenMenu/_h3qkCloseMenu/_h3qkMakeMenu`; cycle branch of click handler now opens a dropdown (toggle + flip positioning + global close listeners); all 4 enum buttons keep cycle & tints (speed_preset still 8 presets); tooltips/docs updated; both titles → v2.129·v14.147
- `extender.py`：后端加载横幅 → v14.147（标注 quickbar cycle→dropdown） / `extender.py`: backend load banner → v14.147 (notes quickbar cycle→dropdown)
- 验证：node --check + py_compile 通过；行为断言 18 项全过（菜单函数齐全 / 无循环取模残留 / 4 枚举按钮 cycle 保留 / speed_preset 8 档与 tints 不回归 / 菜单项 stopPropagation+回调链路 / 底部翻转 / click+wheel 全局关闭 / 无"循环下一档"文案残留 / 标题两处升级 / 后端横幅同步 / 布尔按钮开/关保留）/ Verified: node --check + py_compile pass; 18 behavioral assertions pass (menu helpers present / no cycle-mod residue / all 4 enum buttons keep cycle / speed_preset 8-preset & tints not regressed / menu-item stopPropagation + apply chain / bottom flip / click+wheel global close / no leftover "cycle next" copy / both titles bumped / backend banner synced / boolean toggle kept)

### v14.146 (2026-10-13) — 快捷条速度按钮补全 8 档 + 分链路配色 / Quickbar Speed Button: Full 8 Presets + Per-Link Coloring

**核心：快捷条「速度」按钮原来只在 极速→均衡→精细 三档循环，看不到 custom/VDN/Trim 档。本轮补齐为节点支持的全部 8 档：`custom → 极速 → 均衡 → 精细 → 极速-VDN → 均衡-VDN → 精细-VDN → FastH3-Trim`，并按链路分色——灰=custom 手动档 / 青绿=FastH3 标准档(极速/均衡/精细) / 紫=VDN 档 / 橙=FastH3-Trim 单采档；同链路内保留"档位越靠后越亮 + 底部档位进度条"的深浅渐变。新增 `h3QuickTintedShades()`（每档独立 color/border 的分档配色生成器 + 缓存），渲染循环优先使用 tints；`def.tints` 与 `def.cycle` 严格 1:1（8 组），纯前端 DOM 改动，widgets_values 序列化与后端参数顺序零变化 → 旧工作流零 NaN、零错位、零重连。** / Core: the quickbar "Speed" button only cycled 极速→均衡→精细 (3 presets), hiding custom/VDN/Trim. This round completes all 8 presets the node supports: `custom → 极速 → 均衡 → 精细 → 极速-VDN → 均衡-VDN → 精细-VDN → FastH3-Trim`, color-coded by link — gray=custom manual / teal-green=FastH3 standard (极速/均衡/精细) / purple=VDN / orange=FastH3-Trim single-pass; within each link the existing "later preset = brighter + bottom progress bar" gradient is kept. Adds `h3QuickTintedShades()` (per-preset color/border shade generator + cache); the render loop prefers tints when present; `def.tints` is strictly 1:1 with `def.cycle` (8 groups). Pure frontend DOM change — widgets_values serialization and backend param order untouched → zero NaN / zero misalignment / zero re-wiring on all legacy workflows.
- `web/extender.js`：QUICK_DEFS.speed_preset 增 `cycle` 8 档 + `tints` 8 组配色；新增 `h3QuickTintedShades(tints)`（含 `__h3TintCache` 缓存）；渲染循环 `shades` 优先 `def.tints`；快捷条顶部说明更新速度 8 档颜色含义；标题两处 → v2.128·v14.146 / `web/extender.js`: QUICK_DEFS.speed_preset gains 8-item `cycle` + 8-group `tints`; new `h3QuickTintedShades(tints)` (with `__h3TintCache`); render loop prefers `def.tints`; quickbar title tooltip documents the 8-preset color scheme; both titles → v2.128·v14.146
- `extender.py`：后端加载横幅 → v14.146（标注 KJNodes patch-rebuild + speed_preset 8 档全） / `extender.py`: backend load banner → v14.146 (notes KJNodes patch-rebuild + all-8 speed presets)
- 验证：node --check + py_compile 通过；行为断言 18 项全过（cycle=8 且与后端 INPUT_TYPES 逐字一致 / custom 首档 / tints=8 与 cycle 匹配 / 每档 color+border 齐全 / 分链路色相断言 / shades 优先 tints / 标题两处升级 / 后端横幅同步 / 循环取模逻辑保留）/ Verified: node --check + py_compile pass; 18 behavioral assertions pass (cycle=8 verbatim-matches backend INPUT_TYPES / custom first / tints=8 matches cycle / per-preset color+border present / per-link hue assertions / shades prefers tints / both titles bumped / backend banner synced / cycle-mod logic kept)

### v14.145 (2026-10-13) — 二采重驻留改走 KJNodes 补丁重建（根治 Sol-Attn workspace OOM 降级）/ Pass-2 Re-Residency via KJNodes Patch Rebuild (Root-Cure Sol-Attn Workspace OOM Downgrade)

**核心：v14.143"删 KJNodes 补丁走原生 forward"是错误方向，v14.144 实测证实并已废弃。** 实机日志：delegate 驻留 11.7GB 时采样瞬间 `allocated=18.05GB`（= 驻留 11.7 + **中间激活 6.35GB**），Sol-Attn 申请 6.33GB workspace → 24.38GB > 23.86GB 上限 OOM；降级 sage（3.03GB 也失败）→ pytorch attention，二采失去稀疏加速。根因：原生 block/attn forward 对 120x68 全幅 latent 的 qkv/normed-h 等中间张量全程驻留（~6.35GB），Sol-Attn 再无空间。参考插件（v14.82，用户实测二采 240s/步、画质清晰无雪花）的机制恰恰是**保留 KJNodes lowmem 分块 + Sol-Attn 的原 model 重驻留**：`minimax_attn_lowmem_forward` 在 qkv GEMM 后立即 `del x/qkv/q/k/v`，`minimax_head_chunks` 按 head 分组使 kernel 内部暂存随 head 组缩小——中间激活被压到 ~1GB 级，Sol-Attn workspace 才有空间。本轮在 delegate 上**重新绑定** KJNodes 补丁到 delegate 自己的 block/attn 实例（`types.MethodType(fn, delegate_block)`，消除 clone 复制导致 self 错位），并从原 model 恢复 `minimax_head_chunks`/`sol_take_forward`；同时**移除 v14.144 的 +2.5GB 让位**，还原为参考插件标准 reserve 公式（x2.0→ws4.5、clamp 3-8、tiled 下限 7.5），与 v14.82 逐行一致。** / Core: v14.143's "strip KJNodes patches and run native forward" was the wrong direction, and v14.144's real-machine log proved it: with 11.7GB delegate residency, sampling spiked to `allocated=18.05GB` (= 11.7 resident + **6.35GB intermediates**), Sol-Attn's 6.33GB workspace pushed it to 24.38GB > 23.86GB → OOM; sage (3.03GB) also failed → pytorch attention, pass-2 lost sparse acceleration. Root cause: native block/attn forwards keep qkv/normed-h intermediates of the full 120x68 latent resident (~6.35GB), leaving no room for Sol-Attn. The reference plugin (v14.82, user-measured pass-2 240s/step, clean & sharp) instead KEEPS the KJNodes lowmem chunking + Sol-Attn on the re-resident ORIGINAL model: `minimax_attn_lowmem_forward` frees x/qkv/q/k/v right after the qkv GEMM, and `minimax_head_chunks` splits heads so kernel-internal transients shrink per head group — intermediates drop to ~1GB, leaving room for Sol-Attn's workspace. This round REBINDS the KJNodes patches onto the delegate's own block/attn instances (`types.MethodType(fn, delegate_block)`, fixing the clone-copy self-misalignment), restores `minimax_head_chunks`/`sol_take_forward` from the original model, and REMOVES v14.144's +2.5GB headroom bump, reverting to the reference plugin's standard reserve formula (x2.0→ws4.5, clamp 3-8, tiled floor 7.5) — line-for-line aligned with v14.82.
- `extender.py`：delegate 创建后、`EXTRA_RESERVED_VRAM` 赋值前——（a）从 `sys.modules` 定位已加载的 KJNodes `nodes/minimax_nodes.py`（找不到则按插件同级 `..\ComfyUI-KJNodes\nodes\minimax_nodes.py` 路径 spec 加载）；遍历 delegate `diffusion_model.blocks`，用 delegate 自己的 block/attn 实例重新 `MethodType` 绑定 `minimax_block_lowmem_forward` 与 `minimax_attn_lowmem_forward` 写入 `object_patches`；（b）从原 `model.model_options["transformer_options"]` 恢复 `minimax_head_chunks` 与 `sol_take_forward` 到 delegate；（c）移除 v14.144 的 Sol-Attn 让位块（仅保留检测日志），reserve 回到标准公式 / After delegate creation, before `EXTRA_RESERVED_VRAM` assignment — (a) locate the loaded KJNodes `nodes/minimax_nodes.py` in `sys.modules` (fallback: spec-load `..\ComfyUI-KJNodes\nodes\minimax_nodes.py` relative to the plugin); iterate delegate `diffusion_model.blocks`, rebind `minimax_block_lowmem_forward` / `minimax_attn_lowmem_forward` via `types.MethodType` onto the delegate's own block/attn instances into `object_patches`; (b) restore `minimax_head_chunks` and `sol_take_forward` from the original `model.model_options["transformer_options"]` onto the delegate; (c) remove v14.144's Sol-Attn headroom bump (keep only the detection log), reserve back to the standard formula
- 版本升级：extender.js 两处标题 → v2.127·v14.145；后端二采日志注明 KJNodes 补丁重建 / Version bump: JS titles ×2 → v2.127·v14.145; backend refine log notes KJNodes patch rebuild
- 验证：py_compile + node --check 通过；mock 单测 16 断言全过（block/attn forward 绑定 delegate 自身实例、调用走 delegate、self 非原模型、head_chunks=4 与 sol_take_forward 恢复、补丁计数 6、`_uses_optimized_attention` 保留）；真实 KJNodes 模块加载验证 11 断言全过（模块可定位、函数可调用、签名含 transformer_options/attention、list 解包契约、head_chunks 读取、compose 键读取）；AST 结构校验 8 断言全过（v14.144 让位已移除、v14.143 删补丁已移除）/ Verified: py_compile + node --check pass; 16 mock assertions pass (block/attn forwards bound to delegate's own instances, calls route through delegate, self is not the original model, head_chunks=4 & sol_take_forward restored, 6 patches total, `_uses_optimized_attention` kept); real KJNodes module load: 11 assertions pass (module locatable, fns callable, signatures carry transformer_options/attention, list-unwrap contract, head_chunks read, compose-key read); AST structural check: 8 assertions pass (v14.144 bump removed, v14.143 strip removed)
- 注意：仍未实机跑（未启动 ComfyUI 完整渲染），浏览器/采样端最终效果需用户验收；若 head_chunks 分组后的 workspace 仍超预算，Sol-Attn 既有 fallback 链（sage→pytorch）保底不崩 / Note: not yet run on the real machine (ComfyUI full render not started); final effect on canvas/sampling needs user acceptance; if the chunked workspace still exceeds budget, Sol-Attn's existing fallback chain (sage→pytorch) keeps it functional

### v14.144 (2026-10-13) — 二采 Sol-Attn workspace 让位（修复 6.33GB workspace OOM 降级）/ Pass-2 Sol-Attn Workspace Headroom (Fix 6.33GB Workspace OOM Downgrade)

**核心：v14.143 后 KJNodes 崩溃已消除、delegate 原生 forward 生效，但二采采样启动即 OOM：Sol-Attn kernel 申请 6.33GB workspace 失败（已分配 18.05GB（delegate 驻留 14.4GB + 中间量 3.65GB）+ 请求 6.33GB = 24.38GB > 23.86GB 上限，仅差约 0.5GB），依次降级 sage attention（请求 3.03GB 也失败）再降级 pytorch attention——二采失去稀疏加速。根因：Sol-Attn 通过 `transformer_options["optimized_attention_override"]`（函数引用）挂载，clone 深拷贝后 delegate 仍持有；二采 latent 120x68 面积是一采 60x34 的 4 倍，workspace 从 ~1.6GB 涨到 6.33GB。本轮检测 delegate 的 transformer_options 中存在 `optimized_attention_override` 或 `sol_compose`（Sol-Attn 挂载键）时，把 reserve 预算上调 2.5GB（clamp 上限 8.0→10.0），驻留目标从 ~14.4GB 降到 ~12.4GB，给 workspace 让位。换页量 6.9→9.4GB（仍比全流式 21.8GB 减 57%），二采仅 2 步，稀疏加速收益远大于换页损失。** / Root cause: after v14.143 the KJNodes crash is gone and the delegate runs native forward, but pass-2 sampling now OOMs at startup: Sol-Attn kernel fails to allocate its 6.33GB workspace (18.05GB allocated (14.4GB delegate residency + 3.65GB intermediates) + 6.33GB requested = 24.38GB > 23.86GB limit, short ~0.5GB), downgrading to sage attention (3.03GB also fails) then pytorch attention — pass-2 loses sparse acceleration. Sol-Attn is mounted via `transformer_options["optimized_attention_override"]` (a function reference) that survives the deepcopy onto the delegate; pass-2 latent 120x68 is 4× the area of pass-1's 60x34, so the workspace grows from ~1.6GB to 6.33GB. This round detects `optimized_attention_override` or `sol_compose` (Sol-Attn mount keys) in the delegate's transformer_options and raises the reserve budget by 2.5GB (clamp ceiling 8.0→10.0), dropping residency from ~14.4GB to ~12.4GB to free room for the workspace. Page traffic rises 6.9→9.4GB (still 57% less than full streaming 21.8GB); pass-2 is only 2 steps, and the sparse-attention gain far outweighs the extra paging.
- `extender.py`：delegate 创建 + KJNodes 补丁清除之后、`EXTRA_RESERVED_VRAM` 赋值之前，检测 `transformer_options["optimized_attention_override"]`/`["sol_compose"]`，命中则 `_r_resv_dyn += 2.5` 并 `clamp(3.0, 10.0)`；无 Sol-Attn 时行为不变 / After delegate creation + KJNodes patch strip, before `EXTRA_RESERVED_VRAM` assignment, detect `transformer_options["optimized_attention_override"]`/`["sol_compose"]`; on hit `_r_resv_dyn += 2.5` and `clamp(3.0, 10.0)`; unchanged when Sol-Attn absent
- 版本升级：extender.js 两处标题 + 后端横幅 + 二采日志 → v2.126·v14.144 / Version bump: JS titles ×2 + backend banner + refine log → v2.126·v14.144
- 验证：py_compile + node --check 通过；mock 单测 5 断言全过（有 Sol-Attn→+2.5 / 仅 sol_compose 也触发 / 无 Sol-Attn 不变 / clamp 上限 10.0 / 下限 3.0 保留）；版本标记确认 / Verified: py_compile + node --check pass; 5 mock assertions pass (Sol-Attn present→+2.5 / sol_compose alone triggers / absent→unchanged / clamp ceiling 10.0 / floor 3.0 kept); version marker confirmed
- 注意：若 latent 继续变大（如全片合并超分更大的画幅），workspace 需求可能再超预算；届时 Sol-Attn 会按既有 fallback 链降级（sage→pytorch），功能不崩但会慢，可再调高 clamp 上限 / Note: if latent grows further (e.g. larger frames on final full-film upscale), workspace may again exceed budget; Sol-Attn's existing fallback chain (sage→pytorch) keeps it functional but slower — raise the clamp ceiling if needed

### v14.143 (2026-10-13) — 修复 delegate 与 KJNodes 低显存补丁冲突（二采首步崩溃）/ Fix Delegate vs KJNodes LowVRAM Patch Clash (Pass-2 First-Step Crash)

**核心：v14.142 的 delegate 方案在装有 KJNodes `MiniMaxLowVRAMAttention` 补丁的真实链路下二采首步崩溃：`AttributeError: 'list' object has no attribute 'shape'`（崩在 `minimax_block_lowmem_forward`）。根因：`clone(disable_dynamic=True)` 通过 `cached_patcher_init` **重新加载**了全新模型对象，但 KJNodes 的 block/attn 补丁是 `MethodType` 绑定**原模型 block 实例**的——复制到 delegate 后对象错位：block 走 lowmem 补丁把 h 包成 list，attn 却落回原生 forward（期望 tensor）。delegate 已按 reserve 预算部分驻留（~14GB），不再需要低显存补丁，本轮在 delegate 创建后清除 `diffusion_model.blocks.*` 级 object_patches 与 KJNodes 写入的 `minimax_head_chunks`/`sol_take_forward`，让 delegate 走原生 block/attn forward（权重补丁 `self.patches` 保留，采样语义不变）。** / Root cause: v14.142's delegate crashed on the first pass-2 sampling step under a real KJNodes `MiniMaxLowVRAMAttention` patch chain: `AttributeError: 'list' object has no attribute 'shape'` in `minimax_block_lowmem_forward`. `clone(disable_dynamic=True)` rebuilds a brand-new model object via `cached_patcher_init`, while KJNodes' block/attn patches are `MethodType` bound to the ORIGINAL model's block instances — copied over they point at the wrong objects: the block runs the lowmem patch which wraps h in a list, while attn falls back to the native forward (expects a tensor). Since the delegate is already partially-resident (~14GB), the low-VRAM patches are unnecessary; this round strips `diffusion_model.blocks.*` object_patches plus KJNodes' `minimax_head_chunks`/`sol_take_forward` after delegate creation, so the delegate runs native block/attn forwards (weight patches in `self.patches` are kept; sampling semantics unchanged).
- `extender.py`：delegate 创建成功后、`load_models_gpu` 前，过滤 `object_patches` 去掉所有 `diffusion_model.blocks.*` 键（KJNodes block/attn 补丁），并从 `model_options["transformer_options"]` 移除 `minimax_head_chunks` 与 `sol_take_forward`；保留 `manual_cast_dtype` 等非 blocks 补丁 / After delegate creation, before `load_models_gpu`, filter `object_patches` to drop every `diffusion_model.blocks.*` key (KJNodes block/attn patches) and pop `minimax_head_chunks` / `sol_take_forward` from `model_options["transformer_options"]`; non-blocks patches like `manual_cast_dtype` are preserved
- 版本升级：extender.js 两处标题 + 后端横幅 → v2.126·v14.143（横幅注明 native-forward）/ Version bump: JS titles ×2 + backend banner → v2.126·v14.143 (banner notes native-forward)
- 验证：py_compile + node --check 通过；mock 单测 6 断言全过（blocks.* 补丁全清除 / 非 blocks 补丁保留 / minimax_head_chunks 与 sol_take_forward 移除 / 其它 transformer_options 键保留 / 无 blocks 引用残留）/ Verified: py_compile + node --check pass; 6 mock assertions pass (all blocks.* patches stripped / non-blocks patches kept / minimax_head_chunks & sol_take_forward removed / other transformer_options keys kept / no blocks references left)
- 注意：若用户工作流另有其它绑定模型实例的注意力补丁（如 Sol-Attn 自挂），delegate 仍可能与其错位；届时优先建议二采关闭 DynamicVRAM（历史实测驻留 9.19GB 时二采分钟级正常）/ Note: if the workflow carries other model-instance-bound attention patches (e.g. Sol-Attn self-attached), the delegate may still clash; then the recommended path is disabling DynamicVRAM for pass-2 (historically measured pass-2 in minutes at 9.19GB resident)

### v14.142 (2026-10-13) — 修复 DynamicVRAM 二采 637s/步（non-dynamic delegate 驻留）/ Fix DynamicVRAM Refine 637s/step (Non-Dynamic Delegate Residency)

**核心：DynamicVRAM 开启时一采后模型被完全卸载（allocated≈0GB），二采交 staged 调度 = 每步 21.8GB CPU↔GPU 逐层换页 → 实测 637s/it。用官方 `get_non_dynamic_delegate()`/`clone(disable_dynamic=True)` 生成非 dynamic delegate，对 delegate 走标准 `load_models_gpu` 部分驻留（reserve 预算内驻留 + offload 尾部），换页量减约 2/3、二采提速 2-3 倍；失败自动回退原路径，不会比现状更糟。** / Root cause: with DynamicVRAM enabled the model is fully unloaded after pass-1 (allocated≈0GB), so pass-2 hands sampling to staged scheduling = per-step 21.8GB CPU↔GPU page swapping → measured 637s/it. Fix: build a non-dynamic delegate via official `get_non_dynamic_delegate()`/`clone(disable_dynamic=True)` and partially-reside it through standard `load_models_gpu` (reside within reserve budget, offload the tail), cutting page traffic ~2/3 and speeding pass-2 by 2-3×; falls back to the original path on failure (never worse than today).
- `extender.py`：二采块声明 `_refine_model = model`；`_is_dyn` 分支改为优先 `get_non_dynamic_delegate()`、回退 `clone(disable_dynamic=True)`、再回退原 model；按非 dynamic 分支同款 reserve 预算（`_model_gb2 - (_gpu_total_gb2 - ws - 3.0 - 1.5)` clamp 3.0~8.0，tiled 下限 7.5）设 `EXTRA_RESERVED_VRAM` 后 `load_models_gpu([delegate])` / `_refine_model = model` in refine block; `_is_dyn` branch now prefers `get_non_dynamic_delegate()`, falls back to `clone(disable_dynamic=True)`, then original model; sets `EXTRA_RESERVED_VRAM` with the same reserve budget as the non-dynamic branch then `load_models_gpu([delegate])`
- `extender.py`：二采采样 5 处调用点全部切换 `_refine_model`：`_r_guider = _BasicGuider(_refine_model)`、时间分块 `_ff_const_add_noise(_refine_model,…)`、OOM fallback `_r2_sigmas/_r2_latent/_r2_guider` / All 5 pass-2 sampling call sites switched to `_refine_model`: guider, temporal-chunk const-add-noise, and the OOM fallback trio
- `extender.py`：finally 追加 delegate 卸载（`unload_model`）+ `EXTRA_RESERVED_VRAM` 恢复进入前原值，防 delegate 驻留残留挤压下一 CLIP 一采 staged 空间 / finally now unloads the delegate and restores `EXTRA_RESERVED_VRAM` to its pre-entry value so leftover residency can't squeeze the next CLIP's pass-1 staging
- 版本升级：extender.js 两处标题 + 后端横幅 → v2.126·v14.142 / Version bump: JS titles ×2 + backend banner → v2.126·v14.142
- 验证：py_compile + node --check 通过；mock 单测 13 断言全过（delegate 生效 / reserve 预算 / 原值保存 / delegate 失败回退 / clone 兜底 / 非 dynamic 不触碰 / finally 卸载复位与恢复） / Verified: py_compile + node --check pass; 13 mock-test assertions pass (delegate active / reserve budget / orig-value saved / delegate-fail fallback / clone fallback / plain-path untouched / finally unload-reset-restore)
- 注意：delegate 创建依赖宿主 Sol-H3 加载器注册 `cached_patcher_init`，未注册时自动回退原路径，功能不回归 / Note: delegate creation needs `cached_patcher_init` registered by the Sol-H3 host loader; if absent it auto-falls-back with no regression

### v14.141 (2026-10-13) — 强制旧雪花 blob 失效重编（GOP 修复真正生效）/ Force Re-encode of Legacy Snow Blobs (GOP Fix Now Effective)

**核心：v14.140 的 GOP=48 只对新编码生效——`_decode_single_clip_to_blob` 的缓存（`decoded_mp4_version>=2`）让旧 GOP=250 雪花 blob 被直接复用，用户重渲染仍见尾部雪花。本轮把缓存版本升至 3，旧雪花 blob 全部失效并按 GOP=48 重编，per-CLIP 预览 / 渐进全片 / 最终成片全链路生效。** / Root cause: v14.140's GOP=48 only applied to NEW encodes — the blob cache (`decoded_mp4_version>=2`) re-served legacy GOP=250 snow blobs, so re-render still showed tail snow. This round bumps cache version to 3, invalidating all legacy snow blobs and re-encoding with GOP=48 across per-CLIP preview, progressive full preview and final export.
- `motion_context_disk.py`：缓存判定 `>=2 → >=3`，写入 `decoded_mp4_version = 3`；旧 v2 blob 全部重编 / Cache gate `>=2 → >=3`; writer sets version 3; all v2 blobs re-encoded
- 验证：渲染实际使用的 imageio_ffmpeg v7.1 实测 `-g 48`，362 帧 IDR 每 2s、尾部最后 IDR 14.0s / Verified on the actual runtime ffmpeg (imageio v7.1): IDR every 2s, last IDR at 14.0s
- 配套：v14.140 `_h264_enc_args`/`_hevc_enc_args` 全分支 `-g 48`（本版本号内已含）/ Bundled with v14.140's `-g 48` on all encode branches
- 注意：已渲染的旧 mp4 文件不受影响，需触发一次重渲染（blob 自动重编）后生效 / Already-rendered files unaffected; one re-render (auto re-encode) makes it effective

### v14.140 (2026-10-13) — 修复视频尾部雪花/花屏（关键帧 GOP 修复）/ Fix Tail Snow/Noise (Keyframe GOP Fix)

**核心：视频编码默认 GOP=250（10.4s）导致 15s 预览尾部 4.6s 无 IDR 关键帧（纯 P 帧链），播放器播放/拖拽到尾部时花屏雪花；统一改为显式 GOP=48（2s）关键帧间隔。** / Root cause: default GOP=250 (10.4s) left the last 4.6s of a 15s preview with zero IDR keyframes (pure P-frame chain), so players show snow/artifacts when playing or seeking the tail; now forced GOP=48 (2s) keyframe interval.
- `_h264_enc_args` / `_hevc_enc_args`：NVENC 与 libx264/x265 全部分支显式加 `-g 48`（每 2 秒一个 IDR，任意 seek 位置 ≤2s 内可寻址解码）/ Explicit `-g 48` on NVENC and libx264/x265 branches (IDR every 2s; any seek position decodes within ≤2s)
- 覆盖全部编码入口：per-CLIP 预览、progressive 全片预览、最终成片 export、色彩校正 / Covers all encode entry points: per-CLIP preview, full progressive preview, final export, color correction
- 验证：libx264 与 h264_nvenc 实测 362 帧 1920×1088，IDR 间隔精确 2s，尾部最后 IDR 位于 13.9–14.0s（距片尾仅 ~1s）/ Verified on both libx264 & h264_nvenc (362 frames): IDR every 2s, last IDR at 13.9–14.0s (~1s from end)
- 编码效率损失 <2%，画质与码率不变 / <2% encoding overhead; same quality & bitrate

### v14.138 (2026-10-12) — 最佳参数默认化（8+2 双采开箱即用）/ Best-Params as Defaults (8+2 Dual-sample Out-of-box)

**核心：全部采样/双采/暂停参数默认值改为 RTX 5090 24G 实测最佳配置，新拉节点开箱即用，无需手动调整。** / All sampling/refine/pause defaults switched to RTX 5090 24G verified best config; new nodes work out-of-box.
- `refine_enable`: `false → true`（双采默认开，直出高清）/ Dual-sample ON by default
- `refine_denoise`: `1.0 → 0.45`（CONST 重加噪最佳强度实测）/ Best re-noise strength
- `refine_steps`: `4 → 2`（8+2 双采实测最佳）/ 8+2 dual-sample verified best
- `refine_upscale_factor`: `1.5 → 2.0`（直出 1920×1088）/ Direct 1920×1088
- `refine_align_to`: `32 → 40`（H3 官方 40px 网格实测最佳）/ H3 40px grid verified
- `pause_timeout`: `120 → 5`（暂停超时默认 5s，最佳出片节奏）/ 5s auto-resume
- `speed_preset`: `均衡 → custom`（避免预设覆盖 8+2 显式值；按下方各 widget 显式值采样）/ custom so preset no longer overrides 8+2
- 同步更新 `_sample_h3()` 函数默认参数与运行时 `kwargs.get` 兜底默认（三处一致）/ Function defaults & runtime fallbacks synced (3 places)
- README 参数表 + 双采示例 + CHANGELOG 双语同步 / README tables & examples synced
- 兼容性：默认值变更只影响"新拉节点无保存值"场景；旧工作流 widgets_values 有保存值 → 加载行为完全不变，零 NaN 零重连 / Old workflows unaffected (saved values take precedence), zero NaN.
- 验证：py_compile ✓ / Verified: py_compile ✓
- 依据 / Basis：《MiniMax-H3双日志对比分析报告 V1.0》(2026-10-12)，环境 5090 24G / 8+2 dual-sample report.

---

### v14.104-121 (2026-10-12) — 一键化快捷开关条（全部布尔全覆盖）+ 参数区同步隐藏 / One-Click Quick Toggle Bar (all booleans) + Params Auto-Hidden

**核心：在 CLIP 卡片区底部按钮栏后面新增一行「快捷」开关条，20 个一键开关——10 个高频（二采、逐段超分、全片超分、块缓存、参考缓存、输出模式、速度预设、口型预设、超分模式、暂停）+ v14.106 扩展 10 个全部 true/false 布尔（预览 output_image_audio、DiT缓存 cache_dit、CLIP选择 clip_select_enable、超分FP16 upscale_fp16、人脸修复 upscale_face_restore、分块二采 tiled_refine、语义桥 semantic_bridge_enable、桥对齐 semantic_bridge_magnitude_match、保脸 face_lock_mode、恢复缓存 restore_cache）。布尔点一下开/关（绿=开），枚举点一下循环下一档；悬停显示中英双语完整名称+功能简介；按钮状态实时读 widget 真实值。v14.105-107：被快捷按钮覆盖的 20 个参数从参数区隐藏（一键开关替代原设置栏，其余参数保留）。隐藏复用 hideNativeWidget（clips_json/refs_json 同一成熟机制：computeSize 归零 + 重绘 re-hide inputEl），widget 仍保留在 widgets 数组 → widgets_values 对齐不变 → 任意版本旧工作流加载零 NaN、零重连、零错位。v14.107：restore_cache 是 1.55 新式 toggle widget（optional），部分浏览器环境 computeSize 归零后渲染可能残留——追加 DOM 级兜底（轮询找到 label 行容器 display:none，6s 超时自清，不影响 widget 数组）。v14.108：兜底升级为全元素+属性搜索（textContent / title / placeholder / aria-label 全覆盖，10s 轮询）。v14.109：**全局守卫**——实测真实 Chrome 无痕窗口 computeSize 归零与 buildUi 级轮询均失效（用户环境 restore_cache 仍显示），故在 extender.js 顶层安装页面级 MutationObserver（300ms 节流 + 500ms 首扫 + beforeunload 断开）：任何时刻 DOM 出现 restore_cache 文本/属性即自动隐藏 label 行，完全不依赖 buildUi 时机。v14.110：**组合式守卫**——用户环境实测 v14.109 仅把 toggle 控件置灰未隐藏整行（真实行容器 className 未知），升级为：①CSS 属性选择器注入 `[title*="restore_cache"]` 等 display:none !important（覆盖控件本体）；②守卫命中含 restore_cache 文本的叶子后依次隐藏 自身→直接父→祖先链类名匹配行/控件/开关的容器→附近 input/button/switch 控件；③持续扫描不停止。**该版全页面扫描+宽文本匹配+激进隐藏导致误伤核心 UI（用户强制刷新后白屏）**——立即回退重构。（前置 v14.111-113：守卫从安全化到全部移除——白屏终局修复，两害相权取"画布可用"；v14.114：restore_cache 单行黑色填充；v14.115：枚举档位按钮显示修复——输出/速度/口型/超分模式按钮下方实时显示当前档位、默认档灰/启用档绿，消除"恒绿点不动"观感，布尔按钮不变。）**v14.119-120（已回退）：** v14.119 尝试 widget.draw no-op + height=0 覆盖 canvas 绘制——实测在部分 1.55 环境导致**被覆盖参数行高塌陷、全部"叠罗汉"重叠**（行内容照常绘制但高度归零）；v14.120 撤销 marginTop 下移后问题仍在。**v14.121：叠罗汉根治 + remove 兜底**——①撤销 draw no-op 与 height=0（叠罗汉根源）；②保留 computeSize/computeLayoutSize 归零 + 涂色；③新增**残留行 remove 兜底**：paintCoveredRows 命中后若行仍可见（offsetParent 非空）直接 `row.remove()` 删除行节点——Vue 组件只在 widgets 数组变化时重渲染（数组未动 → 行不重建、彻底消失），widgets_values 由 widget 数组读取不受 DOM 删除影响 → **零 NaN、零重连**；多残留行（restore_cache/face_lock_mode）逐轮扫描全部处理。bu 实测：nan=0、被覆盖参数可见残留 0、画布正常。** / draw no-op + height=0 reverted (caused stacked/overlapping hidden param rows); v14.121 removes residual row DOM nodes directly after painting (widgets array untouched → Vue won't re-create the row, serialization unaffected).

---

### v2.117 / v14.86 (2026-10-09) — lip_audio 逐段音频错位彻底修复（上下文参考感知切分 + 混音跳过重叠）/ lip_audio Per-Clip Audio Drift Fully Fixed (Context-Aware Split + Mix Skips Overlap)

**核心：开启上下文参考时，lip_audio 切给 clip2+ 的段头部带 ~1.2s 上一段尾部重叠（用于模型音频 latent 行对齐），但输出混音时未跳过这段重叠，导致每个 clip 的预览 MP4 开头都混入上一段尾部的音乐，与 lip_audio 原始音频错位（用户需手动裁剪开头才能对上）。现在：切分感知「上下文参考」开关——关闭上下文参考的 CLIP 不再切重叠、纯净对齐；开启时把重叠量记录进段元数据，输出混音精确跳过重叠，clip2+ 与原始音频零错位。**
**Core: with context reference ON, the lip_audio segment handed to clip2+ carries ~1.2s of the previous segment's tail (needed to align the model's audio latent rows), but the output mix never skipped that overlap, so every clip preview MP4 started with the previous segment's music and drifted from the original lip_audio (users had to manually trim the head to realign). Now: split is context-aware — CLIPs with context reference OFF get pure zero-overlap segments; when ON, the overlap size is recorded in the segment metadata and the output mix skips it exactly, so clip2+ aligns with the original audio with zero drift.**

---

#### 后端 / Backend

- **上下文感知切分 / context-aware split**：`_split_lip_audio_by_clips` 逐段读取 `context_enabled`——关闭上下文参考的 CLIP（含 clip2+）切出纯净段（零重叠），开启的 CLIP 仍切重叠但把 `overlap_samples` 写进段 dict。 / `_split_lip_audio_by_clips` reads each CLIP's `context_enabled`: CLIPs with context reference OFF (incl. clip2+) get pure zero-overlap segments; ON CLIPs keep the overlap but record `overlap_samples` in the segment dict.
- **混音跳过重叠 / mix skips overlap**：`_decode_single_clip_to_blob` 混音前读取段元数据 `overlap_samples`，从歌曲段头部精确跳过重叠，再与模型音频对齐 → 输出 MP4 音频 = 本 CLIP 对应纯净歌曲段，与 lip_audio 原始音频逐帧对齐。 / Before mixing, `_decode_single_clip_to_blob` reads `overlap_samples` and skips exactly that many samples from the song segment head, then aligns to the model audio — the output MP4 audio is the clip's own pure song segment, frame-aligned with the original lip_audio.
- **日志增强 / log enhancement**：切分日志打印每段时长与头部重叠秒数，便于核对。 / Split log prints each segment's duration and head-overlap seconds for verification.
- **lip_audio 连接即自动关闭上下文 / auto-disable context on lip_audio connect**：一旦外部歌曲接入 lip_audio，后端强制所有 CLIP 零重叠切分且不做 motion context（即使前端开关仍开着也忽略）；前端 onConnectionsChange 检测到连线后自动把所有 CLIP 的「上下文参考」复选框关掉并刷新 UI。 / Once a song connects to lip_audio, the backend forces zero-overlap splitting and skips motion context for every CLIP (ignoring the front-end switch); the front-end onConnectionsChange handler auto-unchecks every CLIP's "Context Reference" box and refreshes the UI.

---

### v2.116 / v14.82 (2026-10-08) — lip_audio 独占歌曲源 + 模型环境音垫底混音 / lip_audio as Exclusive Song Source + Model Ambience Bed Mix

**核心：一旦把外部歌曲接到 lip_audio，所有 CLIP（含 @图N 角色）的口型完全由这首歌驱动；ref_audio 端口和 @音频N 资产库音频自动忽略，绝不串歌；逐段预览和最终出片音轨 = 歌曲主唱（满音量）+ 模型生成的环境音/音效（压低到 15%）作为 MV 辅助音；缺段直接报错而不是悄悄回退。**
**Core: once an external song is connected to lip_audio, every CLIP (including @图N characters) lip-syncs exclusively to that song; the ref_audio port and @音频N asset-library audio are auto-ignored so no other audio can leak in; per-clip previews and the final output track = lead song at full volume + model-generated ambience/SFX ducked to 15% as MV bed audio; a missing segment raises an error instead of silently falling back.**

---

#### 后端 / Backend

- **lip_audio 独占音频源 / lip_audio exclusive audio source**：连接 lip_audio 后立即把全局 `ref_audio` 置 None，`@音频N` 资产库注入同步跳过；每段 CLIP 的音频条件只能是 lip 切出的对应片段，段缺失直接 `RuntimeError`。 / Once lip_audio is connected, the global `ref_audio` is dropped and `@音频N` asset injection is skipped; every CLIP's audio conditioning is forced to its own lip segment, raising on a missing segment.
- **逐段预览 MP4 混音 / per-clip preview MP4 mix**：`_decode_single_clip_to_blob` 新增 `lip_audio_segment` 参数，模型解码出的环境音与对应歌曲片段自动混音（重采样/长度/声道对齐），歌曲满音量、模型音 ×0.15。 / `_decode_single_clip_to_blob` now accepts `lip_audio_segment`; the model-decoded ambience and the matching song segment are auto-mixed (resampled/length/channel aligned), lead full volume + model audio ×0.15.
- **最终输出混音 / final output mix**：最终 AUDIO 输出从"纯替换为歌曲"改为"歌曲 + 模型拼接音频 ×0.15"，模型的环境音不再丢弃。 / The final AUDIO output changed from "pure song replacement" to "song + concatenated model audio ×0.15"; model ambience is no longer discarded.
- **缓存提醒 / cache reminder**：连接 lip_audio 时若已有 validated 缓存 CLIP，日志明确提示需要取消校验重渲，否则口型与新歌不匹配。 / When lip_audio connects and some CLIPs are already validated/cached, the log warns to uncheck them and re-render so lips match the new song.
- **Bug 修复 / bug fix**：修复首次接入 lip_audio 时引用未赋值变量 `loop_end` 导致的 `UnboundLocalError`。 / Fixed an `UnboundLocalError` on `loop_end` when first connecting lip_audio.

---



### v2.72 → v2.115 / v14.85 (2026-09-30) — 崩溃修复 + 独立渲染正确性 + 前端底板全高 + 展开/收起CLIP按钮紧贴 + 全局提示词区独立折叠 + 高度实测 + 默认展开/宽度保证按钮完整可见 + 新建节点渲染 CLIP1 卡片 / Crash Fixes + Per-Clip Render Correctness + Full-Height Backdrop + Tight Collapse/Expand Toggle + Independent Global-Prompt Fold + Measured Heights + Expanded-by-Default & Toolbar-Fit Width + CLIP1 Card on New Nodes

**核心：崩溃后断点续跑不丢链；独立渲染"渲谁是谁"且渲染完静默等待；节点黑色底板跟随 CLIP 数量；展开/收起CLIP按钮点击后节点高度紧贴；全局提示词区不再随 CLIP 收起而消失，改为独立的「▲/▼」折叠按钮；收起态与展开态高度都实测，底部按钮栏不裁切、底板盖满节点；节点默认「展开CLIP」状态，默认宽度保证工具栏末尾的「📦 收起CLIP / 📂 展开CLIP」按钮完整可见。**
**Core: resume after crash without losing the chain; per-clip render outputs exactly the chosen clip and waits silently after finishing; the node's dark backdrop tracks the CLIP count; the "Collapse/Expand CLIP" buttons snap to the correct node height; the global prompt area no longer disappears when CLIPs are collapsed — it now has its own "▲/▼" fold button; both collapsed and expanded heights are measured so the bottom bar is never clipped and the backdrop covers the whole node; the node now opens **expanded**, and its default width guarantees the trailing "📦 收起CLIP / 📂 展开CLIP" button is fully visible.**

---

#### 🔧 后端 / Backend

- **hostbuf 崩溃修复（v2.72-v2.74）**：TE 权重重载路径 `hostbuf_file_reader_read failed` 崩溃修复，长链续跑不再闪退。/ Crash fix for the `hostbuf_file_reader_read failed` TE reload path — long-chain resume no longer crashes.
- **独渲"渲谁是谁"（v2.75）**：单独渲染 CLIP29 曾输出 CLIP1 内容（preview/MP4 按局部链索引取段）。现在 async encode 队列携带三元组（done_event、链内索引、全局 CLIP 索引），preview/MP4 提取/命名全部按全局索引——渲谁就是谁。/ Solo-rendering CLIP29 used to output CLIP1 (preview/MP4 indexed by local-chain index). The encode queue now carries (done_event, chain index, global CLIP index) and preview/MP4 extraction/naming use the global index — you get exactly the clip you chose.
- **独立渲染后不自动合并（v2.76）**：单独渲染某 CLIP 完成后不再自动合并/输出全部 clip，只保留 latent 缓存 + 卡片预览，静默等待用户下一步指令（合并输出 / 续跑 / 渲别的 clip）。/ After a solo render the node no longer auto-merges or outputs everything — it keeps the latent cache + card preview and silently waits for your next command (merge / continue / another clip).
- **收尾元组解包崩溃（v14.77）**：修复 `_pending_enc` 三元组在收尾遍历处的二元解包 `too many values to unpack`——渲染成果不受影响（缓存/预览先于崩溃已提交）。/ Fixed the binary unpack of the 3-tuple `_pending_enc` at the tail loop (`too many values to unpack`) — rendered results are unaffected (cache/preview commit before the crash point).

#### 🎨 前端 / Frontend

- **节点黑色底板跟随 CLIP 数量（v2.105）**：默认打开 = 1 卡视口 + 1 卡底板；点「展开CLIP」= 全部 CLIP 显示、底板撑到全高；收起态任何代码路径都无法把底板缩到 <1 卡（防止旧 nodeHeight/布局抖动闪回 0 卡）。/ The node backdrop tracks the CLIP count: default open = 1-card viewport with a 1-card backdrop; "Expand CLIP" shows every CLIP with a full-height backdrop; in collapsed mode no code path can shrink the backdrop below 1 card (no more 0-card flashback from stale nodeHeight/layout jitter).
- **拖拽画布不闪回（v2.105）**：移动画布/重布局瞬间节点不再闪回 1 卡再弹回。 / Dragging the canvas no longer flashes the node back to 1 card before recovering.
- **展开态内容不溢出底板（v2.105）**：展开时 root/cards 恢复 auto 高度，30 卡内容全高撑起节点，不再溢出到黑色底板之外。 / Expanded state: root/cards revert to auto height so the full card stack fills the backdrop instead of overflowing it.
- **「收起CLIP」按钮紧贴卡片底板（v2.107）**：之前点击「收起CLIP」后 `afterResize` 钩子把 `runtime._userResize` 标 true，让 `syncDomHeight` legacy 收起分支误判为"用户拖拽"，走错位公式 `cards = node.size[1] - NON_CARD_FIXED ≈ 215px`（实际应该是 1 卡视口 379px），节点底部空出 ~140px 黑边。修复后 click handler 显式置 `runtime._userResize = false` 再调 `syncDomHeight`，走 `collapsedViewportH=379` 这条确定性公式，节点高度紧贴 1 张卡 + 工具栏 + 底部按钮栏。/ The "Collapse CLIP" button now snaps the node to a 1-card-tight height. Previously `afterResize` flagged `_userResize=true` and made `syncDomHeight` use the wrong formula `cards = node.size[1] - NON_CARD_FIXED ≈ 215px` (should be 379px for 1 card), leaving ~140px of black gap below the cards. The click handler now forces `_userResize=false` before calling `syncDomHeight`, which takes the `collapsedViewportH=379` deterministic branch.
- **「展开CLIP」按钮底板撑到全高（v2.107）**：之前点击「展开CLIP」后 `node.size = [w, last_y + root.scrollHeight]`，但 `root.scrollHeight` 此时只有 ~90px（cards 还是收起态的 379px 固定高度），直接把节点撑回 690px，30 张卡片溢出到底板外、画布出现一大段黑空白。修复后 click handler 调 `autoGrowNodeToFitAllClips`（按 30 卡 × 380px + 285 固定 + 36 填充算 ≈12321px 设 node.size）再调 `syncDomHeight`，让 legacy 展开分支用真实 DOM `scrollHeight`（cards.style.height 已设 auto）撑高，黑色底板跟随全量卡片。/ The "Expand CLIP" button now grows the node to fit all 30 cards. Previously `node.size = [w, last_y + root.scrollHeight]` used a stale ~90px scrollHeight (cards still at collapsed 379px), shrinking the node to 690px while cards overflowed the backdrop. The click handler now calls `autoGrowNodeToFitAllClips` (which computes the full card-stack height) then `syncDomHeight`, which uses the real DOM scrollHeight (cards.style.height=auto) to grow the backdrop to match all cards.
- **「收起/展开CLIP」二次 setSize 抑制（v2.107 第二轮）**：第一轮修复后用户验收发现 bug 仍存在。根因是 click handler 调 `syncDomHeight` 设完 `node.size` 后触发 `afterResize` 钩子 → 钩子里 `_userResize = true`(line 6369 无条件) → 再调 `syncDomHeight(forceMin=false)` → 第二次进入 legacy 收起分支时 `_userResize=true` 走错位公式 `_vh2 = node.size[1] - NON_CARD_FIXED = 1075-285 = 790`,contentH=886,targetH3=1486,节点被二次撑高 +411px(收起 bug 仍在)/展开侧把 autoGrow 设的 12321 覆盖为 _fullNodeH=375,卡片全部溢出底板。修复加 `_h3BtnResizeInFlight` guard:click handler 设 `true`,afterResize 钩子看到 `true` 直接 return(只做"收起态不低于 1 卡最小高度"的兜底,不再二次调 syncDomHeight),setTimeout(0) 释放 guard。/ After the first round of v2.107 fixes the user re-tested and the bug persisted. Root cause: click handler calls `syncDomHeight` which writes `node.size`, triggering `afterResize` → which unconditionally sets `_userResize=true` (line 6369) → then calls `syncDomHeight(forceMin=false)` again → on this second call `_userResize=true` takes the wrong formula `_vh2 = node.size[1] - NON_CARD_FIXED`, inflating the node by ~411px in collapse mode and shrinking it to ~375px in expand mode. Fix: added `_h3BtnResizeInFlight` guard — the click handler sets it true, the afterResize hook checks it first and bails out (only doing the "minimum-height floor in collapse mode" sanity check), and the guard is released via setTimeout(0).
- **全局提示词区独立折叠（v2.108）**：用户反馈「收起状态全局提示词不见了」。根因是收起 CLIP 分支（nodes2 line 4982 / legacy line 5050 / onConfigure line 6583 / afterResize line 6417）无条件把 `globalPromptSection.style.display = "none"`，而展开分支负责恢复——CLIP 收起就把提示词区一起藏了。现在显隐完全解耦：新增 `applyGlobalPromptVisibility(runtime)` 统一裁决，只看用户折叠标志 `_h3GpUserCollapsed`（默认 `false` = 始终显示）；新增 `gpCollapseBtn`（`▲`/`▼`，在「全局提示词」标签右侧）让用户手动折叠/展开提示词区换取 CLIP 卡片可视高度；收起态高度公式加上 `globalPromptSectionH(runtime)` 实测高度，提示词区不再被底板裁掉；顺带把历史上从未赋值的 `runtime.gpResizer` 挂上（老代码的把手显隐一直是死代码）。折叠状态是会话内 UI 偏好，不写工作流 JSON（与 `gpDragHeight` 一致），刷新后回到默认展开。/ The user reported the global prompt area vanishing in collapsed mode. Root cause: every collapse branch hard-coded `display = "none"` on `globalPromptSection` while only the expand branch restored it. Now visibility is fully decoupled from the CLIP toggle: `applyGlobalPromptVisibility(runtime)` is the single decision point driven only by the new `_h3GpUserCollapsed` flag (default `false` = always visible), a new `▲`/`▼` button sits next to the "全局提示词" label for manual folding, the collapsed height formula now adds the measured `globalPromptSectionH(runtime)` so the prompt area is never clipped, and the historically-unassigned `runtime.gpResizer` is finally exposed. The fold state is a session-only UI preference (not written to the workflow JSON) and resets to expanded on reload.
- **收起态 bottomBar 被裁掉（v2.109）**：v2.108 上线后用户发现收起态底部「CLIPS | 总时长 …」+ 添加/删除按钮整条消失（截图红圈处一片空白）。根因是 v2.108 把手工高度公式漏算了几项：`globalPromptSection` 的 `margin-bottom:6px`、toolbar 的**真实**高度（按钮多时换行，超过 `TOOLBAR_HEIGHT=50` 这个常量）、bottomBar 的**真实**高度（`getBoundingClientRect()` 不含 margin，常量 35 也只是估值）。公式偏小 + `root.style.overflow:hidden` → 把最后一个子元素 bottomBar 整条裁掉。修复：新增 `applyCollapsedLayout(runtime, viewportH)` 统一处理收起态布局 —— cards 固定视口高 + `flex:0 0 auto`（不会被拉伸）、root 置 `height:auto`，强制一次 reflow（读 `offsetHeight`）后读 `root.scrollHeight` 作为真实内容全高，取 `max(实测, 兜底公式)`。收起态 cards 高度写死且不参与拉伸，所以不存在 v2.29 注释里的 `scrollHeight` 正反馈循环。三处调用点（onNodeCreated 同步收起 / onConfigure 恢复收起 / syncDomHeight legacy 收起分支）统一走这个函数，rAF 层的两处 targetH 兜底也补上了 `globalPromptSectionH()`，避免公式再次各自漂移。/ After v2.108 shipped, the user found the collapsed-state bottom bar ("CLIPS | 总时长 …" plus the add/delete buttons) entirely gone. Root cause: the v2.108 hand-written height formula missed `globalPromptSection`'s `margin-bottom:6px`, the toolbar's real height (buttons wrap past the `TOOLBAR_HEIGHT=50` constant), and the bottom bar's real height (`getBoundingClientRect()` excludes margins, and the 35px constant is only an estimate). The too-small height plus `overflow:hidden` clipped the last child. Fix: a new `applyCollapsedLayout(runtime, viewportH)` centralises the collapsed layout — cards get a fixed viewport height with `flex:0 0 auto` (never stretched), root goes `height:auto`, one forced reflow, then `root.scrollHeight` is read as the true content height and `max(measured, fallback)` is used. Because the collapsed cards height is fixed and non-stretching, the `scrollHeight` feedback loop described in the v2.29 comment does not apply. All three call sites now share this function, and the two rAF-layer targetH fallbacks also add `globalPromptSectionH()`.
- **展开态黑色底板盖不住节点底部（v2.110）**：收起态在 v2.109 修好后，展开态仍有问题 —— 节点外框在原生 widgets 之后就结束，toolbar / 全局提示词区 / CLIP 卡片 / 底部按钮栏全部溢出到框外。展开分支有四处缺陷：(1) `cards.style.flex = "1 1 auto"` 会让 cards 在 root 里被拉伸，实测 `scrollHeight` 不再等于真实内容高；(2) 高度换算 `domHeight = max(available, rootFullH - NON_CARD_FIXED)` 再 `+ NON_CARD_FIXED` 绕了一圈，而 `NON_CARD_FIXED=285` 是估值常量（toolbar 50 + 提示词区 200 + 底栏 35），与真实内容无关，换算结果可能偏小；(3) 读 `scrollHeight` 前没强制 reflow，拿到的是收起态残留布局的旧值；(4) 末尾有一行遗留的 `runtime.domHeight = available;`，把刚算好的值又覆盖回去。修复：把展开分支改成与收起态同构的实测写法 —— overflow 先设好、cards 改 `0 0 auto`、强制 reflow、读真实 `scrollHeight`，节点高 = `y + 内容全高 + BOTTOM_PAD`（并对当前高度取 `max`，绝不缩小用户已拉大的节点）；删掉旧的 `NON_CARD_FIXED` 换算和那行遗留覆盖；并在真正改动了 size 时安排一次下一帧校正（同一帧内 `last_y` 可能还是改 size 前的旧值）。/ With the collapsed state fixed in v2.109, the expanded state still broke — the node frame ended right after the native widgets and the toolbar / prompt area / CLIP card / bottom bar all overflowed outside it. The expanded branch had four defects: `cards.style.flex = "1 1 auto"` let cards stretch so the measured `scrollHeight` was no longer the real content height; the height math `max(available, rootFullH - NON_CARD_FIXED) + NON_CARD_FIXED` round-tripped through a 285px *estimated* constant unrelated to the real content and could come out too small; `scrollHeight` was read without a forced reflow so it reflected the leftover collapsed layout; and a leftover `runtime.domHeight = available;` overwrote the just-computed value. The expanded branch now mirrors the collapsed fix — set overflow first, `cards` to `0 0 auto`, force a reflow, read the real `scrollHeight`, and set the node height to `y + content + BOTTOM_PAD` (taking `max` with the current height so a user-enlarged node is never shrunk). The old `NON_CARD_FIXED` math and the leftover overwrite are gone, and a next-frame correction is scheduled only when the size actually changed (the same frame's `last_y` can still be the pre-resize value).
- **默认展开 + 宽度保证按钮完整可见（v2.111）**：两点改动。(1) **默认状态改为「展开CLIP」** —— 原先 runtime 初始化、onNodeCreated 同步块、onConfigure 的三处标记、以及按钮的初始文案和 `clipsCollapsed` 变量都写死为收起态。现在统一改为展开：按钮初始显示「📦 收起CLIP」（按钮显示的是"下一步可点的动作"），初始化不再套用收起态的 `applyCollapsedLayout` 固定视口，高度交给 `syncDomHeight` 展开分支实测。(2) **宽度下限** —— toolbar 是 `display:flex` + 默认 `nowrap`，而 flex 子项默认 `flex-shrink:1`，节点宽度不够时按钮不是换行而是被逐个压缩，排在 `pauseBar`/`status` 之前的「📂 展开CLIP / 📦 收起CLIP」首当其冲被压扁甚至裁掉。新增 `ensureToolbarWidth()` 实测工具栏自然宽度当宽度下限：直接读 `scrollWidth` 只会得到容器宽度（子项已被压缩），所以临时把 toolbar 设成 `width:max-content` 量完 `offsetWidth` 再还原，比拍魔数更稳（按钮文案增删、status 文本长短、DPI 差异都会自动跟随）。只加宽不缩窄，保留用户手动拉宽的宽度；在 onConfigure 布局稳定后再复测一次，因为首次调用时 DOM 可能还没排版。/ Two changes. (1) **The default state is now expanded** — the runtime init, the onNodeCreated sync block, the three onConfigure markers, the button's initial label, and the `clipsCollapsed` variable were all hard-coded to collapsed. They now all default to expanded: the button starts as "📦 收起CLIP" (a button shows the *next* action), and initialisation no longer applies the collapsed `applyCollapsedLayout` fixed viewport — height is measured by the `syncDomHeight` expanded branch. (2) **Width floor** — the toolbar is `display:flex` with default `nowrap`, and flex children default to `flex-shrink:1`, so when the node is too narrow buttons are compressed one by one rather than wrapping, and the trailing "📂 展开CLIP / 📦 收起CLIP" button (ordered before `pauseBar`/`status`) gets squashed or clipped first. A new `ensureToolbarWidth()` measures the toolbar's natural width as the floor: reading `scrollWidth` directly would only return the container width (children already shrunk), so it temporarily sets the toolbar to `width:max-content`, reads `offsetWidth`, and restores it — more robust than a magic number (button text changes, status length, DPI all follow automatically). It only widens, never narrows, and re-measures on the next frame in onConfigure because the first call may run before the DOM is laid out.
- **宽度修正改为多时间点重试（v2.112）**：v2.111 上线后用户实测发现宽度修正**完全没生效** —— 新节点仍然是窄的，工具栏按钮被压成两行叠字、还横向溢出到节点右框外（用户截图确认）。根因是 `ensureToolbarWidth()` 开头用 `tb.isConnected` 早退，而 DOM widget 是 ComfyUI **绘制时**才挂进 document 的，onNodeCreated / onConfigure 早期调用时 `isConnected` 为 false，函数直接 return，宽度永远没被修正。修复：去掉 `isConnected` 早退（连不上时 `offsetWidth` 自然为 0，由 `natural > 0` 自然跳过），并新增 `scheduleToolbarWidthFix(node, runtime)` 在 0 / 120 / 400 / 900 / 1800 / 3200ms 六个时间点各实测一次 —— 因为按钮文案、`counter`（"总时长 15s (1 clip)"）文本、`pauseBar` 按钮显示状态都会在渲染过程中陆续变化，靠后几个重试点覆盖。onNodeCreated 与 onConfigure 两处调用点都改用该调度。/ After v2.111 shipped the user tested and found the width fix **never took effect** — new nodes were still narrow, toolbar buttons compressed into two-line stacked text and overflowing horizontally past the node right frame (confirmed by the user screenshots). Root cause: `ensureToolbarWidth()` bailed out early on `tb.isConnected`, but the DOM widget is attached to the document by ComfyUI only at *draw* time, so `isConnected` was false during the early onNodeCreated / onConfigure calls and the function returned without ever correcting the width. Fix: drop the `isConnected` bail-out (when disconnected `offsetWidth` is naturally 0 and the `natural > 0` check skips it anyway) and add `scheduleToolbarWidthFix(node, runtime)`, which re-measures at 0 / 120 / 400 / 900 / 1800 / 3200 ms — button labels, the `counter` text and the pauseBar button visibility all settle during rendering, so the later retries cover them. Both the onNodeCreated and onConfigure call sites now use the scheduler.
- **逐子元素测量自然宽度（v2.113）**：v2.112 的 `measureToolbarNaturalWidth` 仍然量不准。原因是它把整个 toolbar 临时设成 `width:max-content` 再读 `offsetWidth`，但 toolbar 里的 `status` 是**弹性留白项**（`margin-left:auto` + `max-width:45%` + `text-overflow:ellipsis`），在 `max-content` 下依然参与压缩/反向影响结果，等于量了个循环依赖。改成逐个子元素处理：显式 `margin-left:auto` 或 `max-width` 是 <100% 百分比的判为弹性项**跳过**，其余子元素逐个临时设 `flex:0 0 auto` + `width:max-content` 让它按自身内容撑开，再连同 gap 求和；弹性项改用固定额度 `TOOLBAR_STATUS_ALLOWANCE=150` 计入（否则一段长状态文案会把节点撑到几千像素）。重试点延长到 0/120/400/900/1800/3200/6000/10000ms，并加 `ResizeObserver` 兜底（rAF 合并同帧触发，存 `runtime._toolbarWidthRO`）。/ v2.112's `measureToolbarNaturalWidth` still measured wrong. It set the whole toolbar to `width:max-content` and read `offsetWidth`, but `status` is a **flexible filler** (`margin-left:auto` + `max-width:45%` + `text-overflow:ellipsis`) that still participates under `max-content` — a circular measurement. Now each child is handled individually: anything with an explicit `margin-left:auto` or a `<100%` percentage `max-width` is treated as flexible and **skipped**; every other child is temporarily set to `flex:0 0 auto` + `width:max-content` so it expands to its own content, then summed with gaps. The flexible item is instead covered by a fixed `TOOLBAR_STATUS_ALLOWANCE=150` (otherwise one long status string would stretch the node to thousands of pixels). Retries extended to 0/120/400/900/1800/3200/6000/10000 ms, plus a `ResizeObserver` fallback (rAF-merged, stored in `runtime._toolbarWidthRO`).
- **默认宽度修复从未被调用（v2.114，本轮真正的根因）**：v2.113 之后用户第三次反馈「还是窄的」。这次在真实浏览器里复现并定位到根因：**`scheduleToolbarWidthFix` 只挂在 `onConfigure` 上，而 `onConfigure` 只在"从工作流 JSON 恢复节点"时才触发**。用户描述的场景是「从搜索框把节点拖到画布」，这条路径只走 `onNodeCreated` —— 宽度修正一次都没跑过，所以 v2.111/v2.112/v2.113 三轮全部无效。修复：`onNodeCreated` 在 `buildUi` 之后立刻调一次 `scheduleToolbarWidthFix`，双 rAF 回调里（卡片渲染完、counter/status 文案已填）再调一次。同时加**「量到即收手」闩锁**：`ensureToolbarWidth` 返回值改成"是否成功量到有效自然宽度"，一旦量到就停掉全部重试并 `disconnect()` 掉 `ResizeObserver` —— 否则长驻的 ResizeObserver 会在用户手动把节点拉窄时立刻把宽度顶回去，变成跟用户抢拖拽把手；默认宽度是落地态需求，量到一次就够，之后把控制权完全交回用户。顺带把节点标题从写死的 `v2.105` 升到 `v2.114`，方便一眼确认浏览器里加载的是哪一版（之前标题一直显示 v2.105，排查时极具误导性）。**浏览器实测**：从搜索框新建节点，等待全部重试点后，工具栏 11 个可见按钮的 y 坐标全部落在同一行（479/480，高度 5–6px@29% 缩放），全宽元素 `gpResizer` 右边界 x=778，工具栏从 x=338 起排到 x=661 之后还有 3 个按钮，合计正好落在节点右框以内；节点宽度从默认约 300 提升到约 1480（画布单位）。
- **新建节点不渲染 CLIP 卡片（v2.115，本轮第二个根因）**：宽度修好后用户发现新建节点里 **CLIP1 卡片整块消失** —— 全局提示词区下面直接就是底部按钮栏，后面留一大块黑。根因在 v2.76：当时为避免「onNodeCreated/onConfigure 两套分片链并发」把 `onNodeCreated` 的初始 `render()` 整段删掉，注释写的是「onConfigure 是唯一初始渲染」。但 `onConfigure` **只在 `graph.configure()` 恢复工作流时触发**，从搜索框拖到画布的新建节点一次都走不到它 —— 于是 `parseState` 兜出来的那个默认 CLIP（`clips: [newClip(0)]`，`buildUi` 里 `state = parseState(jsonWidget.value)` 已经解析出来了）从来没有被构建成卡片 DOM，状态里有、画布上没有。修复不能简单地在 `onNodeCreated` 里同步 `render`（那会重新引入 v2.76 要修的并发），改成「欠一次渲染」标志 `runtime._needsInitialRender`：`buildUi` 初始化为 `true`，`onConfigure` 渲染前置 `false`，`onNodeCreated` 里挂一个 500ms / 1800ms 的延时兜底，只在标志仍为 `true` 时才 `parseState` → `updateHidden` → `render` → `autoGrowNodeToFitAllClips` → `syncDomHeight` 并清标志。恢复路径下 `onConfigure` 是同步调用的，500ms 早已跑完，两套分片链不会并发；新建路径则由兜底补上唯一一次初始渲染。**浏览器实测**：从搜索框新建节点后 DOM 出现 `h3-extender-card[data-clip-index="0"]`（▼ CLIP 1、资产/模板、提示词 textarea、字幕/Subtitle、上下文参考、参考帧提取、Seed、Duration、Validated、预览），counter 变成 `1 clip • 0 refs`，底栏变成 `CLIPS | 总时长 10s (1 clip)`；底栏按钮 y=2076 紧贴卡片 Validated 行 y=2011（差 65px，即卡片预览区本身），**没有黑色空洞**；结构与顺序（toolbar → 已引用资产/全局提示词 → CLIP1 卡片 → 底部按钮栏）与目标截图一致。/ After the width fix, the user found the **CLIP1 card entirely missing** on a new node — the bottom bar sat right under the global prompt area with a large black void below it. Root cause dates to v2.76: to avoid "two concurrent chunked render chains from onNodeCreated/onConfigure", the initial `render()` was removed from `onNodeCreated` on the assumption that "onConfigure is the only initial render". But `onConfigure` **only fires during `graph.configure()` workflow restore** — a node dragged from the search box never reaches it, so the default clip that `parseState` already produced (`clips: [newClip(0)]`, parsed in `buildUi` via `state = parseState(jsonWidget.value)`) was never turned into card DOM: present in state, absent from the canvas. The fix cannot simply be a synchronous `render` in `onNodeCreated` (that would reintroduce exactly the concurrency v2.76 fixed). Instead it uses an "owes one render" flag `runtime._needsInitialRender`: initialised `true` in `buildUi`, set `false` by `onConfigure` just before it renders, and a deferred 500 ms / 1800 ms fallback in `onNodeCreated` that only acts while the flag is still `true` (`parseState` → `updateHidden` → `render` → `autoGrowNodeToFitAllClips` → `syncDomHeight`, then clears the flag). On the restore path `onConfigure` runs synchronously, long before 500 ms, so the two chunked chains never run together; on the create path the fallback supplies the single missing initial render. **Browser-verified**: a node created from the search box now produces `h3-extender-card[data-clip-index="0"]` (▼ CLIP 1, 资产/模板, prompt textarea, 字幕/Subtitle, 上下文参考, 参考帧提取, Seed, Duration, Validated, preview), the counter reads `1 clip • 0 refs`, and the bottom bar reads `CLIPS | 总时长 10s (1 clip)`. The bottom bar button sits at y=2076 right below the card's Validated row at y=2011 (65 px apart — the card's own preview area), so there is **no black void**. The structure and order (toolbar → 已引用资产/全局提示词 → CLIP1 card → bottom bar) matches the target screenshot./ v2.113 was followed by the user's third "still narrow" report. This time it was reproduced in a real browser and the real root cause found: **`scheduleToolbarWidthFix` was only wired to `onConfigure`, and `onConfigure` only fires when a node is restored from a workflow JSON.** The user's scenario is dragging the node from the search box onto the canvas, which goes through `onNodeCreated` only — the width fix never ran once, which is why v2.111/v2.112/v2.113 all did nothing. Fix: `onNodeCreated` now calls `scheduleToolbarWidthFix` right after `buildUi`, and again inside the double-rAF (after cards render and counter/status text is filled). A **"stop as soon as measured" latch** was added: `ensureToolbarWidth` now returns whether it successfully measured a valid natural width, and on the first success all retries stop and the `ResizeObserver` is disconnected — otherwise a long-lived ResizeObserver would immediately push the width back the moment the user narrows the node, fighting them for the resize handle. The default width is a one-shot layout requirement; after the first measurement control returns entirely to the user. The node title was also bumped from a hard-coded `v2.105` to `v2.114` so the loaded build is obvious at a glance (the stale title was actively misleading during debugging). **Verified in a real browser**: after creating the node from the search box and letting all retries run, the 11 visible toolbar buttons all sit on one line (y = 479/480, height 5–6 px at 29% zoom), the full-width `gpResizer` right edge is x=778, and the toolbar starting at x=338 runs past x=661 with 3 more buttons, landing just inside the node's right frame; the node grew from the ~300 default to ~1480 canvas units.

---

---

#### 🔧 后端 / Backend

- **hostbuf 崩溃修复（v2.72-v2.74）**：TE 权重重载路径 `hostbuf_file_reader_read failed` 崩溃修复，长链续跑不再闪退。/ Crash fix for the `hostbuf_file_reader_read failed` TE reload path — long-chain resume no longer crashes.
- **独渲"渲谁是谁"（v2.75）**：单独渲染 CLIP29 曾输出 CLIP1 内容（preview/MP4 按局部链索引取段）。现在 async encode 队列携带三元组（done_event、链内索引、全局 CLIP 索引），preview/MP4 提取/命名全部按全局索引——渲谁就是谁。/ Solo-rendering CLIP29 used to output CLIP1 (preview/MP4 indexed by local-chain index). The encode queue now carries (done_event, chain index, global CLIP index) and preview/MP4 extraction/naming use the global index — you get exactly the clip you chose.
- **独立渲染后不自动合并（v2.76）**：单独渲染某 CLIP 完成后不再自动合并/输出全部 clip，只保留 latent 缓存 + 卡片预览，静默等待用户下一步指令（合并输出 / 续跑 / 渲别的 clip）。/ After a solo render the node no longer auto-merges or outputs everything — it keeps the latent cache + card preview and silently waits for your next command (merge / continue / another clip).
- **收尾元组解包崩溃（v14.77）**：修复 `_pending_enc` 三元组在收尾遍历处的二元解包 `too many values to unpack`——渲染成果不受影响（缓存/预览先于崩溃已提交）。/ Fixed the binary unpack of the 3-tuple `_pending_enc` at the tail loop (`too many values to unpack`) — rendered results are unaffected (cache/preview commit before the crash point).

#### 🎨 前端 / Frontend

- **节点黑色底板跟随 CLIP 数量**：默认打开 = 4 卡视口 + 4 卡底板；点「展开CLIP」= 全部 CLIP 显示、底板撑到全高；收起态任何代码路径都无法把底板缩到 <4 卡（防止旧 nodeHeight/布局抖动闪回 1 卡）。/ The node backdrop tracks the CLIP count: default open = 4-card viewport with a 4-card backdrop; "Expand CLIP" shows every CLIP with a full-height backdrop; in collapsed mode no code path can shrink the backdrop below 4 cards (no more 1-card flashback from stale nodeHeight/layout jitter).
- **拖拽画布不闪回**：移动画布/重布局瞬间节点不再闪回 1 卡再弹回。 / Dragging the canvas no longer flashes the node back to 1 card before recovering.
- **展开态内容不溢出底板**：展开时 root/cards 恢复 auto 高度，31 卡内容全高撑起节点，不再溢出到黑色底板之外。 / Expanded state: root/cards revert to auto height so the full card stack fills the backdrop instead of overflowing it.

---

### v2.67 (2026-09-25) — 前端画布卡顿修复 / Frontend Canvas Lag Fix

**核心：打开工作流后画布逐渐卡死、一卡一卡的问题彻底修复。**
**Core: fixed the canvas gradually freezing / stuttering after opening a workflow.**

---

- **修复 1（每帧 console.log）**：`onDrawForeground` 每帧画布重绘都跑双语标签函数，且每帧都 `console.log`（同步阻塞），还重复设置已设过的 label。现已加守卫——节点只处理一次，后续每帧直接 return。
- Fix 1 (per-frame console.log): `onDrawForeground` ran the bilingual-label function on every frame and called `console.log` (synchronous blocking) every frame, re-setting labels already applied. Now guarded — each node processes labels once and returns immediately on later frames.
- **修复 2（定时器泄漏）**：`buildUi()` 被 `onConfigure`/`onExecuted` 反复调用，每次都新建一个 800ms 轮询定时器但旧的从不 `clearInterval`——打开工作流后定时器越积越多直到 CPU 跑满卡死。现已在新建前先 clear 旧定时器，永远只保留一个。
- Fix 2 (timer leak): `buildUi()` was called repeatedly by `onConfigure`/`onExecuted`, each time creating a new 800ms poll timer without clearing the old one — timers piled up after opening a workflow until the CPU maxed out. Now the old timer is cleared before creating a new one; exactly one timer is kept.

---

### v2.66 (2026-09-25) — latent 链保护三保险 + per-clip 独立渲染不补链 / Chain Protection Triple-Safety + Per-Clip Render Never Builds Prefix

**核心：渲过的 latent 链每段自动快照、恢复时空壳备份不再覆盖好链、点独立渲染绝不回 CLIP1。**
**Core: every committed segment is auto-snapshotted, empty backups can no longer overwrite a good chain, and per-clip render never falls back to CLIP1.**

---

#### 🛡️ 一、每段提交后自动滚动快照 / Per-Commit Rolling Snapshot

- 每渲完一段 CLIP（`disk_join` 成功后）立即把整条链快照到固定文件 `chain_extender_<id>.latest.snapshot.h3cache/.json`，每次覆盖。崩溃/误删后**最多丢最后一段**，点「♻️ 恢复缓存」即可回到最近完好状态。
- After every committed CLIP (right after `disk_join`), the whole chain is snapshotted to a fixed file `chain_extender_<id>.latest.snapshot.h3cache/.json` (overwritten each time). After a crash/accidental wipe you lose at most the last segment; click "♻️ Restore Cache" to return to the latest good state.
- 与旧的时间戳快照（仅在全部渲完/合并输出时触发）互补：中途崩溃也有备份。
- Complements the old timestamp snapshot (which only fired on full render-complete / merge-output): mid-run crashes are now covered too.

#### 🚫 二、恢复缓存防空壳保护 / Restore Guards Against Empty Backups

- 旧 bug：恢复时找不到快照会 fallback 到 preclear 备份，而 preclear 可能是 0 段空壳（仅 11 字节）——空壳被 copy 回主链，3.27GB 的 28 段链被空文件覆盖丢失。
- Old bug: when no snapshot existed, restore fell back to a preclear backup that could be a 0-segment empty shell (11 bytes) — copying it overwrote a 3.27GB / 28-segment chain.
- 现已：① 恢复时优先用 `latest.snapshot`；② 跳过段数=0 或数据 <1MB 的空壳备份；③ 当前主链非空且备份段数更少时**拒绝回退**，保护已渲染成果。
- Now: ① `latest.snapshot` is preferred; ② backups with 0 segments or <1MB data are skipped; ③ when the live chain is non-empty and a candidate backup has fewer segments, the restore refuses to roll back.

#### ▶️ 三、per-clip 独立渲染绝不回 CLIP1 / Per-Clip Render Never Falls Back to CLIP1

- 点卡片「▶ 独立渲染」CLIP29 时，若磁盘链只有 CLIP1，旧逻辑会把 CLIP2–28 当成待渲段从 CLIP1 一路补渲。现在前置段磁盘无缓存时**直接跳过、不补渲、不 join**，选中 CLIP 从当前链末尾接续渲染，渲完出预览、不自动合并、等待用户新指令。
- Clicking CLIP29 ▶ with only CLIP1 on disk used to treat CLIP2–28 as pending and re-render from CLIP1. Now missing prefix segments are **skipped — no re-render, no join**; the chosen CLIP renders right after the existing chain tail, emits its preview, and stops without auto-merging.

---


### v2.65 (2026-09-25) — 独立渲染绝不自动补渲染其他 CLIP / Single Clip Render Never Auto-Builds Prefix

**核心：点卡片「▶ 独立渲染」只渲染这一个 CLIP——前置 latent 链不足时不再自动从前面补渲染一大段。**
**Core: the per-clip ▶ button renders exactly one CLIP — missing prefix latents no longer trigger an automatic re-render of a long earlier segment.**

---

- **修复**：点 CLIP29 ▶ 时若磁盘链仅 2 段，旧 v1.17/v1.21 补链逻辑会从 CLIP3 一路补渲染到 CLIP29（用户实测点 clip29 却渲染了 clip3）。现在 per-clip 独立渲染前置链不足时只警告、不补渲染，直接接续现有链末尾渲染指定 CLIP；同时前端 ▶ 按钮会清除其他 CLIP 残留的 replace_mode，避免之前点过的 ↻ 被一起重渲染。clip_select 批量选择的补链逻辑保持不变。
- Fix: clicking CLIP29 ▶ with only 2 segments on disk used to auto re-render CLIP3–29 (the v1.17/v1.21 prefix build). Now a short prefix chain only logs a warning and the chosen CLIP renders right after the existing chain tail; the ▶ button also clears stale replace_mode on other clips. The clip_select batch path keeps its prefix-build behavior.

---

### v2.64 (2026-09-25) — 独立渲染优先 / Per-Clip Independent Render Priority

**核心：点卡片「▶ 独立渲染」只渲染指定 CLIP——即使节点上残留了「CLIP选择开关」的选择集，也不被选择集覆盖。**
**Core: the per-clip ▶ button now always renders exactly the chosen CLIP — a leftover "Clip Select" range can no longer override it.**

---

- **修复**：此前点「▶ 独立渲染」时若节点上残留 clip_select（如参数区「CLIP选择开关」开着、填 11-30），渲染循环的 `i not in select_override` 会跳过用户指定的 CLIP，同时 v2.63 强制启用选择集内全部 CLIP → 点 clip9 ▶ 实际渲染的是 11-30。现在后端检测到 per-clip 独立渲染（replace_mode）时优先忽略 clip_select 范围选择（参数区开关/值保持用户原样不动），▶ 按钮永远只渲染指定 CLIP（前置 latent 链缺失时仍自动补渲染前置段建立链，不渲染后续未选中段）；不点 ▶ 直接运行仍按参数区 clip_select 渲染。
- Fix: with a leftover clip_select range (e.g. the "Clip Select" switch on, 11-30), the loop's `i not in select_override` skipped the chosen clip and v2.63 force-enabled the whole range — clicking clip9 ▶ rendered 11-30 instead. The backend now gives per-clip replace_mode priority and ignores clip_select while the parameter-panel switch/value stay untouched. ▶ always renders exactly the chosen CLIP (missing prefix latents are auto-built, no trailing clips rendered); running without ▶ still follows the panel clip_select.

---

### v2.63 (2026-09-23) — clip_select 权威选择修复 / Clip Select Authority Fix

**核心：勾选「CLIP选择开关」后，clip_select 指定的选中集（含自动补渲染的前置/中段缺口）一律真正渲染，不再被残留的 render_enabled=✗ 静默跳过。**
**Core: with "Clip Select" enabled, the selected set (including auto-filled prefix/middle-gap clips) is always actually rendered — no longer silently skipped by stale per-clip ✗ toggles.**

---

- **修复**：`clip_select=11-30` 时若卡片上残留「独立渲染▶ / ↻」留下的 `render_enabled=✗`，选中段被循环的 `not render_enabled` 条件静默跳过：前置链补不出来、选中段不渲染，首个被渲染的 clip 错放到链索引 0，导致预览解码越界、轨道无输出。现在 clip_select 显式选择时，选择集内一律强制 `render_enabled=True`（与 v1.21 强制渲染前置 clip 同一原则），并在日志打印被强制启用的 CLIP 列表。
- Fix: with `clip_select=11-30`, stale `render_enabled=✗` flags (left by a previous ▶ single-render / ↻ replace action) made the loop's `not render_enabled` check silently skip selected clips — the prefix chain was never built, selected clips never rendered, and the first rendered clip landed at chain index 0 (preview decode out of range, no track output). Now an explicit clip_select forces `render_enabled=True` for the whole selected set before the loop (same principle as v1.21's forced prefix render), with the forced CLIP list printed to the log.

---

### v1.98 (2026-09-23) — 缓存永不自动删 + 渲染自动快照 + 一键恢复不补链 / Cache Protection + Auto-Snapshot + One-Click Restore Without Re-Rendering

**核心：只要渲染过，缓存就受保护、自动备份、可一键恢复，恢复后绝不从 CLIP1 重新渲染补链！**
**Once rendered, your cache is protected, auto-backed-up and one-click restorable — restored clips are never re-rendered from CLIP1!**

---

#### 🛡️ 一、缓存保护：渲染过永不自动删 / Cache Protection

- **任何截断（卡片减少、分辨率变化、工程导入等）前都无条件自动备份主链**，先备份再截断；缓存只可能被用户主动操作删除
  Before ANY chain truncation (card removal, resolution change, project import, etc.) the main chain is unconditionally backed up first; cache can only be removed by explicit user action
- 系统自动流程不再静默丢弃任何已渲染成果
  No automatic system path silently discards rendered work anymore

#### 📸 二、渲染完成自动快照 / Auto-Snapshot After Render

- 每次**渲染完成 / 合并输出**后自动快照整条链（数据 + 清单），保留最近 **5 份**，滚动清理
  After every **render completion / merge output**, the full chain (data + manifest) is auto-snapshotted; latest **5** kept with rolling cleanup
- 快照文件：`chain_extender_<id>.<时间戳>.snapshot.h3cache/.json`
  Snapshot files: `chain_extender_<id>.<timestamp>.snapshot.h3cache/.json`

#### ♻️ 三、一键恢复缓存（两个入口）/ One-Click Restore (Two Entries)

**入口 1 — 节点「恢复缓存」开关（参数列表末尾，执行后自动复位）**
**Entry 1 — Node "Restore Cache" toggle (at the END of the parameter list, auto-resets after execution)**
- 打开 → 运行 → 从最近自动快照恢复主链 → 恢复的 CLIP 标记为已渲染 → **只渲染新增 CLIP，不补链**
  Enable → Run → main chain restored from latest snapshot → restored clips marked as already-rendered → **only new clips render, no chain-fill**
- 执行完成前端自动把开关复位为关
  The toggle auto-resets to off after execution

**入口 2 — 前端工具栏「♻️ 恢复缓存」按钮**
**Entry 2 — Frontend toolbar "♻️ Restore Cache" button**
- 搜索源最高优先级 = 主链目录本身（自动快照/截断备份所在），可直接恢复自动快照
  Highest-priority search source = the main chain directory itself (where auto-snapshots / truncate backups live)

#### 🚫 四、恢复后不补链 / No Re-Rendering After Restore

- 恢复后主链 = 完整备份链 → 前置 latent 链检查直接通过 → **不会触发"从 clip1 自动补渲染"**
  After restore the main chain is complete → prefix latent-chain check passes directly → **no "auto-fill from clip1"**
- 恢复的 CLIP 全部标记 `validated=True` → 主循环跳过（秒级），只渲染真正新增的片段
  Restored clips are all marked `validated=True` → skipped by the main loop (seconds), only genuinely new clips render

#### 🐛 五、关键修复 / Key Fixes

- **WinError 32（文件占用）修复**：恢复源优先匹配 `*.snapshot.*` / `*.preclear.*` 明确备份，排除活跃主链（正被 mmap 占用），占用/损坏候选自动跳过
  WinError 32 (file-in-use) fixed: restore sources prefer explicit `*.snapshot.*` / `*.preclear.*` backups, exclude the live main chain (mmap-held), and skip busy/corrupt candidates
- **恢复分辨率校验**：备份链分辨率 ≠ 当前渲染设置时**回滚恢复并给出明确指引**，不再"恢复成功 → 又被分辨率清链 → 从 CLIP1 补渲染"（latent 链不能跨分辨率复用）
  Restore resolution guard: if backup chain resolution ≠ current render settings the restore is **rolled back with clear guidance**, no more "restore OK → cleared by resolution change → re-render from CLIP1" (latent chains cannot be reused across resolutions)
- **参数兼容**：`restore_cache` 追加在参数列表**末尾**，原有参数顺序完全不变，旧工作流不报错
  Workflow compatibility: `restore_cache` appended at the END of the parameter list; existing parameter order unchanged, old workflows unaffected

---

### v2.62 (2026-09-22) — CLIP 选择渲染增强 + 链完整性修复 / Clip Select Enhancements + Chain Integrity Fixes

**核心：CLIP 选择（clip_select）现在支持任意多选、范围与组合，未选中的 CLIP 保留缓存不重新生成！**
**Now `clip_select` supports arbitrary multi-select, ranges and combinations — unselected clips keep their cache and are not re-rendered!**

---

#### 🎯 一、CLIP 选择渲染 / Clip Select Rendering

**在节点上勾选「CLIP选择开关」后，在「CLIP选择」框输入：**
**Enable the "Clip Select" toggle on the node, then type in the "Clip Select" box:**

| 输入 / Input | 效果 / Effect |
|---|---|
| `all` | 渲染全部 CLIP / Render all clips |
| `1,3` | 仅渲染 CLIP 1 和 3 / Render only clips 1 and 3 |
| `2-5` | 渲染 CLIP 2 到 5 / Render clips 2 through 5 |
| `7-10` | 渲染 CLIP 7 到 10 / Render clips 7 through 10 |
| `3,5,7` | 仅渲染 CLIP 3、5、7 / Render only clips 3, 5, 7 |
| `3，5，7` | 兼容中文标点（全角逗号/顿号/分号、全角连字符）|
| | Chinese full-width punctuation supported (`，`、`、`、`；`, `－`) |
| `2`（单选）/ single | 从 CLIP 2 连续渲染到末尾（续渲染语义）/ From clip 2 continuously to the end (resume semantics) |

- **未选中的 CLIP 保留磁盘缓存、不重新生成**（适合改完个别分镜后局部重渲染）
  Unselected clips keep their disk cache and are **not re-rendered** (ideal for re-rendering only edited shots)
- **输入无法解析时输出 WARNING 提示**，不再静默渲染全部
  Invalid input prints a WARNING instead of silently rendering everything

#### 🔗 二、链完整性自动补齐 / Automatic Chain-Integrity Fill

**H3 链式运动上下文要求 latent 连续。选择跨度内被跳过且磁盘无缓存的 CLIP 会自动补渲染，并明确打印日志。**
**H3 chain motion-context requires contiguous latents. Skipped clips inside the selected span that have no disk cache are auto-filled with a clear log message.**

- 前置缺失段自动补渲染建立完整链 / Missing prefix segments auto-rendered to build the chain
- 中段缺口（如缓存有 1-2、选 3,5,7 时 CLIP4/6）自动补渲染 / Middle gaps (e.g. clips 4/6 when cache has 1-2 and you select 3,5,7) auto-filled
- 补渲染范围收窄到**选中段跨度内**，末尾未选中的 CLIP 保留缓存，不再一路补到片尾
  Fill scope narrowed to the selected span; unselected trailing clips keep cache and are not filled to the end

#### ♻️ 三、恢复缓存改进 / Restore Cache Improvements

- **多源 fallback 搜索链快照**：自动在插件目录、ComfyUI 根目录、主项目根、用户主目录逐级查找链快照，修复 v2.61 硬编码 backup 目录导致备份找不到的问题
  Multi-source fallback search for chain snapshots (plugin root → ComfyUI root → project root → user home), fixing v2.61's hardcoded backup dir
- **损坏链重建保护**：manifest 声称有段但磁盘只有 magic header（空文件）时，自动识别并触发重建，修复 `clip_select` 部分渲染时 `invalid chain index 0/0` 报错
  Corrupted-chain rebuild protection: detects manifest/disk mismatch (empty magic-header file) and triggers a clean rebuild, fixing `invalid chain index 0/0` on partial renders

#### 🖥️ 四、Windows 稳定性修复 / Windows Stability Fix

- 新增 `prestartup.py`：修复 Windows + Python 3.13 + aiohttp 下静态文件请求死锁（浏览器能开页面但 JS/CSS 永远加载不出来）。默认线程池升级到 256 worker + 静态路径同步解析
  New `prestartup.py` fixes the Windows aiohttp static-file deadlock (page loads but JS/CSS hang at "0 bytes received"): default executor upgraded to 256 workers + synchronous static path resolution

#### 📦 五、其他 / Other

- **新增示例工作流**：`example_workflows/百声电影工厂（H3全自动电影短片生成）v1.json`
  New example workflow: fully automatic film short generator
- **修复演示工作流** `BSAI_H3_ClipSelect_Pause.json`：控件顺序错位导致 `clip_select` 收到错误值（120.0）的问题已对齐
  Fixed demo workflow widget-order drift that made `clip_select` receive a wrong value (120.0)

---

### v2.61 (2026-09-22) — ♻️ 恢复缓存 体验修复 / Restore Cache UX Fixes

**恢复缓存按钮体验全面优化，关机续渲染更顺畅！**
**Restore Cache button UX polished — resume after reboot is now seamless!**

---

#### 1. 刷新弹窗修复 / Refresh-Prompt Fix

**「♻️ 恢复缓存」恢复成功后，默认改为"留在当前页面"，把已恢复 N 个 CLIP 的数量写到节点状态栏（紫色文字）。**
**After "♻️ Restore Cache" succeeds, the default is now "stay on current page" — the restored clip count is shown in the node status bar (purple text).**

- 不再强制刷新页面，避免 ComfyUI 的 `beforeunload` 拦截弹"是否离开网站"让用户误以为缓存丢失
  No more forced page reload, avoiding the misleading "leave site?" prompt caused by ComfyUI's own `beforeunload` listener
- 需要时手动 Ctrl+R 刷新即可 / Manually refresh (Ctrl+R) when needed

#### 2. 渲染循环自动读盘 / Auto-Read Fresh Chain Cache

**留在当前页面后，再次 Queue Prompt 时自动读取刚被恢复的 `.h3cache`，跳过已渲染完成的 CLIP，直接从断点继续。**
**When you queue another prompt, the renderer auto-loads the freshly restored `.h3cache` and continues from the break-point, skipping already-rendered clips.**

#### 3. 新增 mp4 预览路由 / New Clip Preview Routes

**后端新增 `/h3_extender/clip_preview` 与 `/h3_extender/clip_preview/file` 两个路由，修复"恢复缓存后右侧预览面板仍空白"问题。**
**Two new backend routes serve the newest per-clip mp4 from `output/bsai_clips/`, fixing the empty preview panel after cache restore.**

---

### v2.60b (2026-09-21) — 收起CLIP + 恢复缓存 + 关机续渲染 / Collapse CLIP + Restore Cache + Resume After Reboot

**两大实用功能：一键收起CLIP节省空间，一键恢复缓存关机续渲染！**
**Two handy features: collapse CLIPs to save space, restore cache to resume after reboot!**

---

#### 📦 一、收起CLIP按钮 / Collapse CLIP Button

**工具栏新增"📦 收起CLIP"按钮，点一下收起到只显示5个CLIP高度，其他CLIP用滚动条查看。**
**New "📦 Collapse CLIP" button in toolbar: click to collapse to show only 5 clips height, scroll for the rest.**

- **按钮位置 / Button Location**: 暂停按钮后面（绿色按钮）/ After pause button (green button)
- **收起后 / After Collapse**: 只显示5个CLIP高度，其他CLIP用滚动条上下滑动
  Only show 5 clips height, scroll up/down for other clips
- **再点一下 / Click Again**: 恢复全部展开
  Restore to fully expanded

---

#### ♻️ 二、恢复缓存按钮 / Restore Cache Button

**工具栏新增"♻️ 恢复缓存"按钮，点一下恢复最近一次渲染的所有缓存、CLIP成品、预览文件，不用从CLIP1重新渲染！**
**New "♻️ Restore Cache" button in toolbar: click to restore all cache, clips, and previews from last render — no need to restart from CLIP1!**

**恢复内容 / What Gets Restored**:
1. **链缓存（h3cache）**: 恢复到 `bsai_h3_chain_cache/` 目录
   Chain cache restored to `bsai_h3_chain_cache/`
2. **CLIP 成品（mp4）**: 恢复到 `output/bsai_clips/` 目录
   Final clips restored to `output/bsai_clips/`
3. **预览文件（_clippv_*.mp4）**: 恢复到 `temp/` 目录，每个CLIP预览窗口都能随时打开预览
   Preview files restored to `temp/`, every clip preview can be opened anytime

---

#### ⚡ 三、关机开机续渲染技巧 / How to Resume After Reboot

**渲染到一半要关机？不用怕，这样操作就能从上次结束的地方继续！**
**Need to reboot mid-render? No problem — follow these steps to resume where you left off!**

##### ✅ 正确操作步骤 / Correct Steps:

1. **等当前CLIP渲染完**（不要中途关机）
   Wait for current clip to finish rendering (don't reboot mid-clip)

2. **直接关机就行**（不用点暂停）
   Just shut down directly (no need to click pause)

3. **晚上开机后 / After Reboot**:
   - 打开工作流 / Open your workflow
   - 点一下 **"♻️ 恢复缓存"** 按钮 / Click the **"♻️ Restore Cache"** button
   - 直接点渲染 / Click render
   - 就会从上次结束的CLIP继续渲染 / It will resume from the last completed clip

##### ❌ 错误操作（不要这样做）/ Wrong Steps (Don't Do This):

- 点暂停 → 直接关机 → 开机后点继续
  Click pause → shut down directly → click resume after reboot
  - **为什么不行 / Why It Doesn't Work**: 暂停状态存在内存里，关机后就没了
  Pause state is in memory, it's gone after reboot

##### 📊 为什么这样行 / Why This Works:

| 状态 / State | 保存位置 / Saved In | 关机后还在吗 / Survives Reboot? |
|-------------|---------------------|-------------------------------|
| 暂停按钮状态 / Pause State | 内存 / Memory | ❌ 没了 / Gone |
| 链缓存（h3cache）/ Chain Cache | 硬盘 / Disk | ✅ 还在 / Survives |
| 已渲染的CLIP / Rendered Clips | 硬盘 / Disk | ✅ 还在 / Survives |
| 预览文件 / Preview Files | 硬盘备份 / Disk Backup | ✅ 恢复后还在 / Restored |

---

### v2.54 (2026-09-20) — 电影模板 + 性能优化 + Bug 修复 / Cinematic Templates + Performance + Bug Fixes

**全新电影提示词模板系统，一键统一全片运镜/调色/氛围，画布响应速度提升 10 倍！**
**Brand-new cinematic prompt template system, one-click unify camera/color/mood across all shots, 10x faster canvas interaction!**

---

#### 🎬 一、电影提示词模板系统 / Cinematic Prompt Templates

**38 个内置电影专业模板，覆盖运镜、调色、构图、氛围四大类，一键应用全片或单 CLIP。**
**38 built-in professional cinematic templates covering camera movement, color grading, composition, and mood — one-click apply to whole film or single clip.**

| 分类 / Category | 数量 / Count | 示例 / Examples |
|---------------|-------------|-----------------|
| 🎥 电影运镜 / Camera Movement | 12 | 缓推 Push In, 拉远 Pull Back, 跟拍 Tracking, 环绕 Orbit, 手持 Handheld, 斯坦尼康 Steadicam... |
| 🎨 电影调色 / Color Grading | 10 | 暖调 Warm, 冷调 Cool, 青橙 Teal & Orange, 黑白 Noir, 莫兰迪 Morandi, 霓虹赛博 Neon Cyber... |
| 🎬 画面分割 / Aspect & Composition | 6 | 宽屏 Widescreen, 上下黑边 Letterbox, 三分 Rule of Thirds, 框中框 Frame-in-Frame... |
| ✨ 电影感 / Cinematic Feel | 10 | 电影级画质 Cinematic Quality, 戏剧光影 Dramatic Light, 黄金时刻 Golden Hour, 雨夜 Rainy Night, 紧张悬疑 Tense Suspense, 史诗宏大 Epic... |

**两种应用模式 / Two Application Modes**:

1. **全局应用 / Global Apply**:
   - 节点顶部工具栏 `✨ 模板` 按钮，一键应用到**所有 CLIP + 全局提示词**
   - Top toolbar "✨ 模板" button, one-click apply to **ALL clips + global prompt**
   - 适合：全片统一调色、统一运镜风格、统一氛围
   - Best for: unifying color grading, camera style, or mood across the whole film

2. **单 CLIP 应用 / Per-Clip Apply**:
   - 每个 CLIP 左侧面板新增 `模板` tab，独立应用到当前 CLIP
   - Left panel "模板" tab on each clip, apply to current clip only
   - 其他 CLIP 完全不受影响
   - Other clips are completely unaffected

**合并选项 / Merge Options**:
- 【确定】= **合并 / Merge**: 保留全局模板，再加单 CLIP 模板
- 【取消】= **覆盖 / Overwrite**: 移除全局模板，只保留单 CLIP 模板

**模板标记 / Template Tags**:
- 全局模板：`[电影风格-全局]...[/电影风格-全局]`
- 单 CLIP 模板：`[电影风格-单CLIP]...[/电影风格-单CLIP]`
- 插入位置：每个 CLIP 提示词**最顶部**，清晰可随时删除

---

#### ⚡ 二、性能优化 / Performance Optimizations

**画布拖动卡、资产面板加载慢的问题彻底解决！**
**Fixed slow canvas dragging and slow asset panel loading!**

1. **资产面板缓存 / Asset Panel Cache**:
   - refs 没变不重新渲染，避免 150+ 个 img 重复加载
   - Skip re-render when refs unchanged, no more 150+ duplicate image loads
   - 加载速度提升 **10 倍以上**
   - Loading speed improved by **10x+**

2. **全局定时器降频 / Global Poll Rate Reduced**:
   - 从 500ms 降到 2000ms，减少 75% 的轮询开销
   - From 500ms to 2000ms, reducing polling overhead by 75%
   - 去掉重复的节点级定时器
   - Removed duplicate node-level timers

3. **CLIP 卡片智能显示 / Smart CLIP Card Display**:
   - 外部提示词输入几个分镜，自动显示几个 CLIP
   - Auto show N clips when N shots are entered in external prompt
   - 未输入时默认只显示 CLIP1，节省屏幕空间
   - Default to CLIP1 only when no prompt entered, saves screen space
   - 节点背景自动跟随 CLIP 数量伸缩
   - Node background auto-resizes with CLIP count

---

#### 🧠 三、时间分块 + 语义桥 / Temporal Chunking + Semantic Bridge

**两大核心技术升级：长片段防 OOM + 提示词更听话！**
**Two major technical upgrades: long clip OOM protection + better prompt adherence!**

##### ⏱️ 时间分块（v2.02）/ Temporal Chunking

**长片段二采防 OOM：沿时间轴（T 轴）切分二采 latent，逐段采样，峰值显存大幅降低。**
**Long clip OOM protection: split refine latent along the temporal axis (T), sample segment by segment, drastically reduces peak VRAM.**

- **区别于空间分块**: 空间分块沿 H/W（宽高）切，时间分块沿 T（时间）切
- **Different from spatial tiling**: spatial tiles along H/W (width/height), temporal chunks along T (time)
- **重叠区平滑接管**: 相邻段重叠区冻结 + smoothstep 接管，避免接缝
- **Smooth overlap**: frozen overlap region + smoothstep blending, no visible seams
- **参数说明 / Parameters**:
  - `temporal_chunk_tokens`: 时间分块长度（沿 T 轴切的 token 数）
  - `temporal_overlap_tokens`: 相邻段重叠 token 数（越大越稳越慢，一般 8~12）
- **使用建议 / Usage Tips**:
  - 0 = 关闭（默认整段二采）
  - T~107（约 4 秒）时建议 40~60
  - 长片段（15 秒+）二采必开，否则容易 OOM

##### 🌉 语义桥（v2.19）/ Semantic Bridge

**让 H3 更听话：用一个约 11MB 的小 MLP 对文本编码器 token 做残差混合，显著提升构图/空间/计数等提示词遵循度。**
**Better prompt adherence: a ~11MB small MLP does residual mixing on text encoder tokens, significantly improves adherence to composition / spatial / counting prompts.**

- **原理 / How it works**:
  - 原版蒸馏于 FL2VA 模型，本插件做了 Ref2VA 强制兼容
  - Original model distilled for FL2VA; this plugin adds Ref2VA compatibility
  - 公式：`C = H + α * (S - H)`，其中 H 是原始 token，S 是桥接 token，α 是强度
  - Formula: `C = H + α * (S - H)`, where H is original token, S is bridge token, α is strength
- **参数说明 / Parameters**:
  - `semantic_bridge_enable`: 开关（默认关，不影响旧工作流）
  - `semantic_bridge_adapter`: 权重文件选择（放 `ComfyUI/models/semantic_bridge/`）
  - `semantic_bridge_alpha`: 桥接强度（默认 0.15，越大越听话，太大会崩）
  - `semantic_bridge_magnitude_match`: 模长对齐（原版默认开，保持即可）
- **推荐权重 / Recommended Weights**:
  - `speach1sdef178/MiniMax-H3-Semantic-Bridge` — 原版通用
  - `JOKER141/BUNNY_H3_Conditioning_Bridge` — 偏动作/多人场景

---

#### 🐛 四、重要 Bug 修复 / Critical Bug Fixes

1. **刷新页面后缓存误清空 / Cache Cleared on Refresh**:
   - 修复：分辨率未稳定时校验，误判不匹配清空缓存
   - Fixed: cache was incorrectly cleared when resolution not yet stabilized on page load
   - 现在刷新页面后，之前生成的 CLIP 缓存完整保留
   - Now all previously generated clip caches are preserved on refresh

2. **外部提示词清空不同步 / External Prompt Clear Sync**:
   - 修复：清空外部全局提示词后，内部全局提示词不同步清空
   - Fixed: internal global prompt not cleared when external global prompt is cleared
   - 现在清空外部提示词，内部全局 + 所有 CLIP 全部同步清空
   - Now clearing external prompt syncs internal global + all clips immediately

3. **tab 切换后资产面板打不开 / Asset Panel Broken After Tab Switch**:
   - 修复：模板 tab 打开后，资产 tab 打不开
   - Fixed: asset tab stopped working after opening template tab
   - 现在 tab 切换完全正常
   - Now tab switching works perfectly

4. **CLIP 提示词框太小看不全 / CLIP Prompt Box Too Small**:
   - 新增：CLIP 提示词框右下角可拖拽拉高度
   - Added: resize handle at bottom-right of each clip prompt box
   - 初始高度 200px，可任意拉高
   - Initial 200px height, resizable to any height

5. **另存工作流报错 / Save Workflow Error**:
   - 修复：另存工作流时报 `structuredClone` 错误（`__h3Extender` 不可枚举属性导致）
   - Fixed: `structuredClone` error when saving workflow (non-enumerable `__h3Extender` property)
   - 现在另存工作流完全正常
   - Now saving workflows works perfectly

6. **二采开头 39 帧重影模糊 / Refine First 39 Frames Ghosting**:
   - 修复：二采 refine 时 motion-context keyframe 未清空，导致开头重影错位模糊
   - Fixed: motion-context keyframe not cleared in refine pass, causing ghosting/blurry first 39 frames
   - 现在二采开头画面干净清晰
   - Now refine start frames are clean and sharp

7. **导入空包误删旧链备份 / Empty Import Deletes Old Chain**:
   - 修复：导入空包时静默删除旧链备份，v1.97 防误清机制没覆盖导入路径
   - Fixed: empty import silently deleted old chain backup, v1.97 protection missed the import path
   - 现在导入前自动备份，不会误删整链
   - Now auto-backup before import, no more accidental chain loss

---

#### 🎛️ 五、其他重要优化 / Other Important Improvements

1. **全局资产引用折叠显示 / Global Asset Refs Folded Display**:
   - 之前：全局引用太多时，所有引用的资产全部展示，占满界面
   - Before: when too many global refs, all referenced assets displayed, taking too much space
   - 现在：每个 CLIP 只显示自己引用的资产，同一资产引用次数用数字角标表示
   - Now: each CLIP only shows its own referenced assets, reference count shown as number badge
   - 界面更清爽，占用更少
   - Cleaner UI, less space usage

2. **CLIP 节点高度自动扩展 / Node Height Auto-Expand**:
   - 之前：CLIP 超过 12 个时，节点高度被截断，只剩 4 个卡片能看到
   - Before: when more than 12 clips, node height was truncated, only 4 cards visible
   - 现在：节点高度自动扩展到 8000px，再多 CLIP 也能完整显示
   - Now: node height auto-expands to 8000px, even more clips fully visible
   - 底部黑色背景自动跟随 CLIP 数量伸缩
   - Bottom black background auto-resizes with CLIP count

3. **重启后资产链接自动恢复 / Asset Refs Auto-Restore on Restart**:
   - 之前：重启 ComfyUI 或刷新工作流后，所有 CLIP 的资产 @引用 全部丢失
   - Before: after restarting ComfyUI or refreshing workflow, all CLIP asset @refs were lost
   - 现在：已引用资产面板同时解析 CLIP prompt + 全局 prompt，重启后自动恢复
   - Now: asset panel parses both CLIP prompt + global prompt, auto-restores after restart
   - 不需要重新输入全局提示词来重新链接资产库
   - No need to re-enter global prompt to re-link asset library

4. **剧本输入自动建 CLIP / Auto-Create CLIP from Script**:
   - 输入外部全局提示词（剧本）后，自动按 `[分镜N]` 数量创建对应数量的 CLIP 卡片
   - After entering external global prompt (script), auto-create CLIP cards based on `[Shot N]` count
   - 节点自动撑高到对应 CLIP 数量，不需要手动拉
   - Node auto-expands to match CLIP count, no manual resizing needed
   - 实时解析，输入完立即生效
   - Real-time parsing, takes effect immediately after input

---

### v1.86 (2026-09-15) — VDN-H3 极速档 + Bullet Time Lora 集成 / VDN-H3 Presets + Bullet Time LoRA
- **VDN-H3 速度档 / VDN-H3 speed presets**: speed_preset 新增 **极速-VDN / Turbo-VDN**、**均衡-VDN / Balanced-VDN**、**精细-VDN / Fine-VDN** 三档。VDN 模式一采固定 8 步（Video DeltaNet DMD 蒸馏最优，质量≈dense 50 步、长链线性注意力更稳），二采 3/4/6 步。需搭配 **VDN 版工作流**（workflows/电影工厂工作流-VDN版-均衡VDN8+4（tile_overlap128）.json）——BSAIVDNH3Loader（基座+linear_branch+LoRA 一体化）替换 Sol-H3 链路，自动跳过 FastH3 LoRA/Sol-Attn。／Three new presets for the ComfyUI-VDN-H3 pipeline: pass-1 fixed at 8 VDN steps (≈dense-50 quality), refine at 3/4/6 steps. Use the VDN workflow (BSAIVDNH3Loader replaces the Sol-H3 chain).
- **Bullet Time LoRA 集成 / Bullet Time LoRA**: 两个工作流（FastH3 版 & VDN 版）均在 Lora Stack 挂载 **BulletTime-MMH3.safetensors @ 0.5**，配合 BSAI-MiniMAX-H3-Prompt 的子弹时间模板触发词（ullet time + time-slow 强化句）使用。／Both workflows mount **BulletTime-MMH3.safetensors @ 0.5** in the LoRA stack, paired with the bullet-time trigger words in the prompt templates.

| 预设 / Preset | 一采步数 / Pass1 steps | 二采步数 / Refine steps | 二采分块 / Tiles | 二采降噪 / denoise | 单 Clip 耗时 / per-Clip |
|---|---|---|---|---|---|
| 极速 Turbo (FastH3) | 4 | 3 | 4 | 0.5 | ~20 min |
| 均衡 Balanced (FastH3) | 6 | 4 | 4 | 0.55 | ~28 min |
| 精细 Fine (FastH3) | 8 | 6 | 4 | 0.55 | ~40 min |
| 极速-VDN Turbo-VDN | 8 (VDN) | 3 | 4 | 0.5 | ~20 min |
| 均衡-VDN Balanced-VDN | 8 (VDN) | 4 | 4 | 0.55 | ~28 min |
| 精细-VDN Fine-VDN | 8 (VDN) | 6 | 4 | 0.55 | ~40 min |

---

### v2.61 (2026-09-22) — ♻️ 恢复缓存 体验修复 + mp4 预览重新挂载 / Restore Cache UX Fix + mp4 Preview Remount

**主要解决"♻️ 恢复缓存"按钮按完后右侧 mp4 预览窗空白的问题，并把"是否刷新页面"的选择权交回用户。**

**Solves: "♻️ Restore Cache" leaves the right-side mp4 preview panel blank, and gives the user a clean way to choose between reloading the page or staying on it.**

#### 🪩 一、为什么之前"恢复缓存"按完右侧预览是空的 / Why the preview panel was blank after restore

**修复前**：
- 后端 `/h3_extender/clip_preview`（在 `motion_context_disk.py`）只从 `bsai_h3_chain_cache/chain_extender_<owner>.json` 的 `segments[*].decoded_mp4_blob` 取 mp4
- 当 `manifest.segments` 为空数组（典型场景：缓存损坏 / 备份丢失），接口固定返回 `400 This clip has not been rendered yet.`
- 前端拿到 null 就显示"预览不可用"占位符
- 即使 `output/bsai_clips/h3_clip_<owner>_<idx>_<ts>.mp4` 真实存在、30 MB 完整，前端也无路可拿

**Before the fix:**
- Backend `/h3_extender/clip_preview` (in `motion_context_disk.py`) only reads mp4 blobs from `manifest.segments[*].decoded_mp4_blob`
- When `manifest.segments` is empty (typical after cache corruption / lost backup), the endpoint always returns `400 This clip has not been rendered yet.`
- The frontend gets `null` and shows the "preview unavailable" placeholder
- Even though `output/bsai_clips/h3_clip_<owner>_<idx>_<ts>.mp4` is fully present, the frontend had no way to fetch it

**修复后**：
- 新加后端路由 `/h3_extender/rendered_clips?owner_id=<owner>`：扫描 `output/bsai_clips/` 返回 `latest_filename_by_idx`（每个 clip_index 对应最新时间戳的 mp4 文件名）
- 前端 `fetchClipPreview` 拿不到原接口数据时自动 fallback → 调 `rendered_clips` 拿文件名 → 直接走 `ComfyUI /view?type=output&subfolder=bsai_clips&filename=...` stream 30MB mp4
- 索引错位 bug 修复：前端 `state.clips[]` 是 0-based，后端 `h3_clip_*_<idx>_` 是 1-based；fetchClipPreview 入口统一 `+1` 转换
- "♻️ 恢复缓存"按完后 `render(node, runtime)` 重画所有 DOM 卡片，每个已渲染 CLIP 立即显示对应 mp4 缩略图

**After the fix:**
- New backend route `/h3_extender/rendered_clips?owner_id=<owner>` scans `output/bsai_clips/` and returns `latest_filename_by_idx`
- Frontend `fetchClipPreview` automatically falls back to `rendered_clips` → uses `/view?type=output&subfolder=bsai_clips&filename=...` to stream the 30 MB mp4
- Index off-by-one fixed: `state.clips[]` is 0-based; `h3_clip_*_<idx>_` is 1-based; the entry-point of `fetchClipPreview` now does a single `+1` conversion
- After pressing "♻️ Restore Cache", `render(node, runtime)` rebuilds every card; every rendered CLIP immediately shows its mp4 thumbnail

#### 📝 二、♻️ 恢复缓存按钮 — 详细使用说明 / Detailed Usage

**按钮位置 / Button Location**: 节点顶部工具栏 / Top toolbar of the node

**第一步 / Step 1**: 点击 **「♻️ 恢复缓存」** / Click the button
- 弹出第一个确认框 / First confirm dialog:*
- "确定要恢复最近一次渲染的所有缓存吗？会恢复：链缓存（h3cache）+ 已渲染完成的 CLIP 成品。恢复后可以直接继续渲染后面的 CLIP，不用从 CLIP1 重新开始。"

**第二步 / Step 2**: 后端响应 / Backend response
- 后端走 `/h3_extender/restore_cache` 接口
- 在 `backup/chain_cache_2026-09-21/` 备份目录存在时复制 `.h3cache` / `_clippv_*.mp4` 到运行目录
- 统计 `output/bsai_clips/h3_clip_<owner>_*.mp4` 总数 → 返回 `clips_restored`（如本机示例的 40）

**第三步 / Step 3**: 第二个确认框（v2.61 新增）/ Second confirm dialog (new in v2.61)
- "恢复成功！已恢复 N 个 CLIP。点击「确定」刷新页面以挂载新的缓存；点击「取消」留在当前页面继续渲染（缓存文件已就绪，状态栏会显示已恢复数量）。"
- **点「确定」**：浏览器原生 `location.reload()`，状态栏会显示已恢复数，右侧预览按需自动 mount
- **点「取消」（推荐）**：留在当前页面，前端调 `/h3_extender/rendered_clips` 拿文件名 → 重画所有卡片 → 右侧预览 1-2 秒内亮起 mp4 缩略图

**常见问题 / FAQ**:
- **Q: 弹出了"是否离开网站"原生框怎么办？/ "Leave site?" native dialog?**
  A: 这是 ComfyUI/LiteGraph 注册的 `beforeunload` 拦截。v2.61 已先调 `graph.setDirty(false)` 再 reload，多数情况下不会弹；万一弹了，按"离开"完成刷新即可（缓存已经在磁盘上了）。
- **Q: 右侧仍然空白？**
  A: 打开 DevTools → Network，搜 `rendered_clips` / `view` 请求，把 URL 和响应截图给我。
- **Q: 取消按钮按了之后想刷新怎么办？**
  A: 直接 Ctrl+R 或 Ctrl+F5，缓存文件已就绪。
- **Q: 恢复缓存会把所有 mp4 都重渲染一遍吗？**
  A: 不会。恢复缓存只搬运磁盘文件；下一次 Queue Prompt 会自动读 `.h3cache` 跳过已渲染段。

#### 🔖 三、如何回滚到此版本 / How to roll back to this version

```bash
cd /path/to/BSAI-ComfyUI-H3-Film-Factory
git checkout v2.61               # 切到这个里程碑
# 或 git checkout 7d2a91f 等具体提交哈希
```

回滚后**重启 ComfyUI** 让新代码生效。备份目录 `output/bsai_clips/` 不在版本控制内，不要手动删除。

```bash
git checkout v2.61
# Then restart ComfyUI for the new code to load. output/bsai_clips/ is not in version control — do not delete it manually.
```

---

## 🚀 VDN-H3 + Bullet Time 快速上手 / Quick Start (v1.86)

### 1️⃣ VDN 极速档（一采质量≈dense 50 步）/ VDN speed presets
1. **安装 VDN 插件（已随包内嵌，零安装）** / Install: BSAI-ComfyUI-vdn-minimax-h3 ships with an embedded vdn_h3 runtime — no separate install.
2. **权重就位** / Weights: put the VDN stage under ComfyUI/models/vdn/stage-dmd-step-250/ (linear_branch + adapters/turbo + adapters/default). Base model: any ComfyUI-compatible MiniMax H3 in models/diffusion_models (recommended minimax_h3_fl2va_int8_convrot.safetensors).
3. **加载 VDN 版工作流** / Load workflows/电影工厂工作流-VDN版-均衡VDN8+4（tile_overlap128）.json — the chain is already wired:
   > **多合一版（推荐）** / **All-in-one (recommended)**: workflows/BSAI_H3_Film_Factory电影工厂128分钟大电影版-多合一版（FastH3+VDN双链路·tile_overlap128).json — 单工作流双链路切换（**开关 OFF=FastH3 一采** / **ON=VDN 8步+turbo 一采**），含分镜AI生成/资产库/BulletTime LoRA/Premiere 导出全套。Dual-chain switch (OFF=FastH3, ON=VDN) with AI storyboard, asset library, BulletTime LoRA & Premiere export.
   BSAIVDNH3Loader (backbone + stage + quality_mode=⚡速度优先) → Lora Stack → BSAIH3FilmFactory (speed_preset=均衡-VDN).
4. **切换档位** / Switch presets on the Film Factory node: 极速-VDN(8+3) / 均衡-VDN(8+4, default) / 精细-VDN(8+6).
5. **想更高画质** / For max quality: set BSAIVDNH3Loader.quality_mode = 🎨 画质优先 (16步+双LoRA) and Film Factory speed_preset = custom, steps = 16.
6. **Run** — pass-1 fixed at 8 VDN steps, then latent upscale ×2 and tiled refine.

### 2️⃣ Bullet Time LoRA（子弹时间）/ Bullet Time LoRA
1. **权重** / Weight: put BulletTime-MMH3.safetensors into ComfyUI/models/loras/ (standard ComfyUI H3 LoRA, ~96 MB).
2. **两个工作流均已挂载 @ 0.5** / Both FastH3 & VDN workflows already mount it in the Lora Stack (slot 2, strength 0.5).
3. **触发词已进模板** / Trigger words are baked into all 6 bullet-time prompt templates (BSAI-MiniMAX-H3-Prompt v1.10+): ullet time at the freeze-chapter start + *"time slows almost to completely, while the camera continues moving dynamically around the action."*
4. **强度建议** / Strength: 0.5 (clean with FastH3 turbo); try 0.7 for stronger effect, watch for deformation on fast action.
5. **手动叠加（自建工作流）** / Manual: insert a LoraLoaderModelOnly (BulletTime-MMH3, 0.5) between your model loader and the sampler.

### 2️⃣.5️⃣ 多合一版工作流 / All-in-one Workflow Guide

**文件 / File**: workflows/BSAI_H3_Film_Factory电影工厂128分钟大电影版-多合一版（FastH3+VDN双链路·tile_overlap128).json

一个工作流同时内置 **FastH3（Sol-H3）** 与 **VDN-H3** 两条模型链路，用开关一键切换，免去开两个工作流。同时含分镜 AI 生成（Qwen）、资产库、BulletTime LoRA、字幕、Premiere 导出全套。
One workflow bundles both **FastH3 (Sol-H3)** and **VDN-H3** model chains, switched by a single toggle — no need for two separate workflows. It also includes AI storyboard (Qwen), asset library, BulletTime LoRA, subtitles and Premiere export.

**双链路切换 / Chain Switch**：

| 开关 Switch | 链路 Chain | 250 档位同步选 Preset |
|---|---|---|
| **OFF**（默认 / default） | FastH3（Sol-H3 Loader 一采） | 极速 4+3 / 均衡 6+4 / 精细 8+6 |
| **ON** | VDN（BSAIVDNH3Loader ⚡8步+turbo 一采） | 极速-VDN 8+3 / 均衡-VDN 8+4 / 精细-VDN 8+6 |

**使用步骤 / Steps**：
1. 加载多合一工作流（/ Load the workflow）。
2. 拨开关选链路（OFF=FastH3，ON=VDN）；**每次只加载一条链路，避免显存双载 OOM**。/ Toggle the switch; only one chain loads at a time (prevents VRAM OOM from double-loading).
3. 在 250 BSAIH3FilmFactory 上选对应档位（见上表）。/ Pick the matching preset on the Film Factory node (see table).
4. 填分镜脚本/资产库，点 Run。/ Fill in the storyboard & assets, hit Run.

**注意事项 / Notes**：
- VDN 链路需 models/vdn/stage-dmd-step-250/ 权重 + models/diffusion_models 有基座；FastH3 链路只需 FastH3 基座。VDN requires the stage weights; FastH3 only needs the FastH3 base.
- BulletTime LoRA 已挂 276 槽 2 @0.5；tile_overlap=128 已设（去毛刺）；latent upscale ×2 内置（960×544 → 1920×1088）。/ BulletTime LoRA mounted at slot 2 @0.5; tile_overlap=128 (de-glitch); built-in latent upscale ×2.
- 想真 4K：FinalDecode 输出后外接放大节点。/ For true 4K, add an upscaler after FinalDecode.

### 3️⃣ 双机同步 / Multi-machine sync
- 本机与 4090 均 git pull 两个仓库: BSAI-ComfyUI-H3-Film-Factory (v1.86) + BSAI-MiniMAX-H3-Prompt (bullet-time trigger words).
- VDN stage + BulletTime LoRA 权重放各机 models/vdn/ 与 models/loras/（VDN 版工作流在无 VDN 权重的机器上会报缺文件，属预期）。


---

---


## v2.61 (2026-09-22) — ♻️ 恢复缓存 体验修复 ｜ ♻️ Restore Cache UX Fix
- **刷新弹窗修复** ｜ **Refresh-prompt fix**: 「♻️ 恢复缓存」按钮恢复成功后, 默认改为"留在当前页面", 把已恢复 N 个 CLIP 的数量写到节点状态栏 (紫色文字). 用户想刷新可手动 Ctrl+R. 修复了因 ComfyUI 注册的 beforeunload 监听器弹出 "是否离开网站? 你所做的更改可能未保存" 让用户以为缓存丢失的问题.
  Default behavior of "♻️ Restore Cache" changed from forced page-reload to "stay on current page, show restored count in status bar". Manually refresh (Ctrl+R) when needed. Fixes the false impression that "restore failed because of beforeunload prompt" caused by ComfyUI's own beforeunload listener.
- **渲染循环自动读盘** ｜ **Auto-read fresh chain cache**: 留在当前页面后, 再次 Queue Prompt 时 `_load_tail_latents_from_disk` 会自动读取刚被恢复的 `.h3cache` 目录, 跳过已渲染完成的 CLIP, 直接从断点继续.
  When the user queues another prompt from the same page, the renderer auto-loads the freshly restored `.h3cache` from disk and continues from the break-point, skipping the already-rendered CLIPs.
- **新增 mp4 预览路由** ｜ **New clip_preview routes**: 后端补充 `/h3_extender/clip_preview` 和 `/h3_extender/clip_preview/file` 两个路由, 让前端能从 `output/bsai_clips/h3_clip_<owner>_<idx>_<ts>.mp4` 取最新 mp4 当 `<video>` 源. 修复"恢复缓存后右侧预览面板仍空白"问题.
  Added two backend routes `/h3_extender/clip_preview` and `/h3_extender/clip_preview/file` for the frontend to fetch the newest mp4 per clip from `output/bsai_clips/`; fixes the empty preview panel after cache restore.
---
## v2.50 (2026-09-20) — Built-in Cinematic Prompt Templates ｜ 内置电影提示词模板
- **38 built-in cinematic templates** ｜ **38 个内置电影模板**:
  - 🎥 Camera Movement (12): Push In / Pull Back / Tracking / Orbit / Handheld / Steadicam... ｜ 🎥 电影运镜（12 个）：缓推 / 拉远 / 跟拍 / 环绕 / 手持 / 斯坦尼康...
  - 🎨 Color Grading (10): Warm / Cool / Teal & Orange / Noir / Morandi / Neon... ｜ 🎨 电影调色（10 个）：暖调 / 冷调 / 青橙对比 / 黑白电影 / 莫兰迪 / 霓虹赛博...
  - 🎬 Aspect & Composition (6): Widescreen / Letterbox / Rule of Thirds / Frame-in-Frame... ｜ 🎬 画面分割（6 个）：宽屏电影感 / 上下黑边 / 三分构图 / 框中框...
  - ✨ Cinematic Feel (10): Cinematic Quality / Dramatic Light / Golden Hour / Rainy Night / Tense / Epic... ｜ ✨ 电影感（10 个）：电影级画质 / 戏剧化光影 / 黄金时刻 / 雨夜氛围 / 紧张悬疑 / 史诗宏大...
- **Global Apply mode** ｜ **全局应用模式**: Top toolbar "✨ 模板" button, one-click apply to ALL clips + global prompt. ｜ 节点顶部工具栏紫色 "✨ 模板" 按钮，一键应用到所有 CLIP + 全局提示词。
- **Per-Clip Apply mode** ｜ **单 CLIP 应用模式**: Left panel "模板" tab, apply to current clip only, other clips unaffected. ｜ 每个 CLIP 左侧面板新增 "模板" tab，独立应用到当前 CLIP，其他 CLIP 不受影响。
- **Two merge options** ｜ **两种合并方式**:
  - Confirm = Merge: Keep global template + add per-clip template ｜ 确定 = 合并：保留全局模板，再加单 CLIP 模板
  - Cancel = Overwrite: Remove global template, use only per-clip template ｜ 取消 = 覆盖：移除全局模板，只保留单 CLIP 模板
- **Template tags** ｜ **模板标记**: `[电影风格-全局]...[/电影风格-全局]` for global, `[电影风格-单CLIP]...[/电影风格-单CLIP]` for per-clip. ｜ 全局用 `[电影风格-全局]...[/电影风格-全局]`，单 CLIP 用 `[电影风格-单CLIP]...[/电影风格-单CLIP]`。
- **Performance optimizations** ｜ **性能优化**:
  - Asset panel cache: skip re-render when refs unchanged (no more 150+ img reloads) ｜ 资产面板缓存：refs 没变不重新渲染，避免 150+ 个 img 重复加载
  - Global poll rate reduced from 500ms to 2000ms ｜ 全局定时器从 500ms 降到 2000ms
  - Removed duplicate node-level timer ｜ 去掉重复的节点级定时器
- **UI improvements** ｜ **UI 优化**:
  - CLIP prompt box initial height 200px, bottom-right resize handle ｜ CLIP 提示词框初始 200px 高，右下角可拖拽拉高度
  - Left panel tabs: "资产" / "模板" ｜ 左侧面板新增 tab 切换："资产" / "模板"

---
## v1.86 (2026-09-15) — VDN-H3 Presets + Bullet Time LoRA ｜ VDN-H3 速度档 + 子弹时间 Lora
- **VDN-H3 speed presets** ｜ **VDN-H3 速度档**: speed_preset adds 极速-VDN / 均衡-VDN / 精细-VDN. Pass-1 fixed at 8 VDN steps (DMD-distilled optimum, quality ≈ dense-50, linear attention keeps long clips stable); refine 3/4/6 steps. Requires the VDN workflow (workflows/电影工厂工作流-VDN版-均衡VDN8+4（tile_overlap128）.json) whose BSAIVDNH3Loader replaces the Sol-H3 chain (FastH3 LoRA & Sol-Attn skipped). ｜ speed_preset 新增三档 VDN 预设：一采固定 VDN 8 步（蒸馏最优、质量≈dense 50 步、长链线性注意力更稳），二采 3/4/6 步；需搭配 VDN 版工作流（BSAIVDNH3Loader（基座+linear_branch 一体化）替换 Sol-H3 链路，跳过 FastH3 LoRA/Sol-Attn）。
- **Bullet Time LoRA in workflows** ｜ **工作流集成子弹时间 Lora**: both FastH3 and VDN workflows mount BulletTime-MMH3.safetensors @ 0.5 in the LoRA stack. Pair with the bullet-time trigger words added in BSAI-MiniMAX-H3-Prompt templates. ｜ FastH3 版与 VDN 版工作流均挂载 BulletTime-MMH3 @ 0.5，配合模板子弹时间触发词使用。

## v1.85 (2026-09-15) — Preview Blob Rebuild + Turbo Quality ｜ 预览重建 + 极速画质
- CLIP preview auto-rebuilds from chain manifest when temp files are cleared (regex fallback) ｜ 预览文件被清后按链清单自动重建。
- Turbo refine 2→3 steps, denoise 0.55→0.5 (fixes blurry dynamic shots) ｜ 极速二采 2→3 步、denoise 0.5，修动态糊。


## v1.84 (2026-09-15) — Preview Playback Fix + Migration Hardening ｜ 预览播放修复 + 迁移加固
- **Preview playback fixed (all machines)** ｜ **预览播放修复（所有机器一致）**:
  - New plugin self-served route GET /h3_extender/clip_preview/file?name=<file> streams CLIP previews straight from ComfyUI\temp, bypassing ComfyUI /view?type=temp which resolves older_paths.get_temp_directory(). On some machines other plugins call set_temp_directory() to the OS temp, so /view 404'd while files lived in ComfyUI\temp. Write & read are now same-source. ｜ 新增插件自服务路由，预览直接从 ComfyUI\temp 读取，绕开 /view 的 temp 目录解析不一致（部分机器被其它插件改到系统 Temp 后 404 无法播放），写读同源。
  - Frontend clipPreviewMediaUrl() uses the plugin route for 	ype=temp. ｜ 前端 temp 类型预览改走插件路由。
- **Chain-cache migration hardened** ｜ **链缓存迁移加固**: v1.82 migration no longer touches .migrated_v182 on partial failure (retries next startup) and verifies copied file size, preventing silent loss of large chains (e.g. 772MB h3cache). ｜ 迁移失败不再误标记、下次启动重试补齐 + 复制后大小校验，杜绝大文件链静默丢失。

## v1.83b (2026-09-15) — Bilingual UI Labels ｜ 双语界面标签
- speed_preset and related labels now show Chinese + English. ｜ 速度预设等参数标签中英双语显示。

## v1.83 (2026-09-15) — Speed Preset ｜ 速度预设 🚀
- New speed_preset widget on BSAIH3FilmFactory (after 	ile_overlap): **Turbo 极速 / Balanced 均衡 / Fine 精细**. ｜ 主节点新增速度预设下拉。
- Turbo = pass1 4 steps + refine 2 steps + 4 tiles + denoise 0.55 → ~15 min/clip on 24GB (15s, 2.08M px), ~46% faster than default. ｜ 极速：一采4步+二采2步，24G 跑 15s 200万像素 ~15 分钟/clip。
- Landed the MiniMax turbo workflow technique (comfyu-Selflift): low-res pass1 composition → 3D latent neural upscale → high-res refine only 2 steps. ｜ 落地 MiniMax 急速工作流技术：低分辨率构图 → latent 神经放大 → 高分辨率二采只跑 2 步。

## v1.82 (2026-09-15) — Chain Cache Relocation ｜ 链缓存目录迁移
- Chain cache moved from custom_nodes/BSAI-ComfyUI-H3-Film-Factory/cache to ComfyUI/bsai_h3_chain_cache (_CACHE_ROOT), auto-migrating legacy files on first use. Protects chains from external tools (e.g. backup software) clearing the custom_nodes cache directory. ｜ 链缓存迁出 custom_nodes 目录到 ComfyUI/bsai_h3_chain_cache，首次使用自动迁移，防止外部软件（如备份软件）清空 custom_nodes 缓存导致丢链。

## v1.81 (2026-09-15) — VRAM Release Timing ｜ 显存释放时机优化
- Explicit VRAM release before pass1 and refine (1.81 显存释放[pass1]/[refine]), reducing OOM risk in dynamic-VRAM environments. ｜ 一采/二采前显式释放显存，降低动态显存环境 OOM 风险。

## v1.80 (2026-09-15) — Cache Diagnostics ｜ 缓存诊断
- On insufficient segments, prints cache诊断: json=X字节 bak=X字节 h3cache=X字节 for quick root-cause. ｜ 段数不足时打印 json/bak/h3cache 字节数便于定位。

## v1.79 (2026-09-15) — Manifest Double-Backup ｜ 清单双保险
- .bak double backup + corruption fallback + segment-count tolerance. ｜ 清单 .bak 双保险 + 损坏回退 + 段数容错。

## v1.78 (2026-09-15) — aimdo Crash Fix ｜ aimdo 编译崩溃修复
- Wrap pass1/refine in _aimdo_disabled() context to avoid graph.push() compile crash on ComfyUI 0.35 with aimdo memory graph. ｜ 一采/二采包 aimdo 禁用上下文，修复 0.35 版本 aimdo 内存图编译崩溃。

## v1.77 (2026-09-15) — Encoder Quality ｜ 编码质量
- Preview/CLIP MP4 encode from ultrafast/17 → ast/14, reduces blocky artifacts. ｜ 预览/片段编码质量提升（fast/14），减少色块伪影。

## v1.76 (2026-09-15) — Unified Temp Path ｜ 临时文件路径统一
- All preview & CLIP temp files pinned to _comfyui_temp_dir() = <your ComfyUI>\temp (7 call sites). ｜ 所有预览/CLIP 临时文件统一固定到各自安装目录下的 ComfyUI\temp。

## v1.75 (2026-09-15) — 4090 Preview Probe Fix ｜ 4090 预览探针修复
- Fixed 2x2 probe transpose on machines without --enable-assets. ｜ 修复无 --enable-assets 机器的 2x2 探针转置问题。

## v1.74 (2026-09-15) — Chain Geometry Consistency ｜ 链几何一致性
- Block per-clip VRAM-budget downgrade once chain segments exist; align returned latent to chain geometry (trilinear) — fixes latent geometry changed Disk Join break on long chains (e.g. CLIP7). ｜ 链上有段后禁止 per-clip 降级 + 返回前 latent 对齐链上几何，修复长链（如 CLIP7）Disk Join 断链。

---

## Older / 更早版本
See README.md sections for v1.31+ feature history. ｜ v1.31 及更早功能历史见 README.md。
