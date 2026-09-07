# BSAI ComfyUI H3 Film Factory

BSAI 出品的 MiniMax H3 电影工厂节点，支持多 clip 分镜逐帧生成、单 clip 重渲染、参考图资产库、二次采样画质修复、per-clip 实时预览解码。

## 节点参数说明（中英对照）

![参数中英对照](参数中英对照.png)

### 基础参数

| 参数名 | 中文说明 | 取值范围 / 选项 | 默认值 | 使用说明 |
|---|---|---|---|---|
| `run_mode` | 运行模式 | `clip_by_clip` / `full_batch` | `clip_by_clip` | `clip_by_clip` 逐 clip 生成，每 clip 完成后可预览；`full_batch` 全批一次性生成 |
| `width` | 宽度（手动分辨率宽） | 32 的倍数，最大 4096 | `896` | 手动模式下的渲染宽度；自动模式下会被回退覆盖 |
| `height` | 高度（手动分辨率高） | 32 的倍数，最大 4096 | `576` | 手动模式下的渲染高度；H3 原生最佳分辨率 896×576 |
| `ref_image_size` | 参考图尺寸 | `match` / `max` | `max` | `match` 匹配参考图尺寸；`max` 取最大参考图尺寸 |
| `steps` | 采样步数 | 正整数 | `4` | FastH3 蒸馏模型推荐 4 步；原生模型推荐 20-24 步 |
| `sampler_name` | 采样器 | `euler` / `euler_ancestral` 等 | `euler` | FastH3 蒸馏模型必须用 `euler` |
| `scheduler` | 调度器 | `simple` / `normal` 等 | `simple` | FastH3 蒸馏模型必须用 `simple` |
| `denoise` | 降噪强度 | 0.0 - 1.0 | `1.0` | 1.0 = 全量重绘；图生视频时可降低以保留参考图结构 |

### 上下文参数

| 参数名 | 中文说明 | 取值范围 / 选项 | 默认值 | 使用说明 |
|---|---|---|---|---|
| `context_length` | 上下文长度（H3时间上下文帧数） | 正整数 | `22` | 每个 clip 的 latent 上下文帧数，影响单 clip 生成时长 |
| `audio_context_length` | 音频上下文长度 | 0 = 自动，正整数 | `0` | 音频 latent 上下文长度，0 为自动匹配 |

### 分辨率参数

| 参数名 | 中文说明 | 取值范围 / 选项 | 默认值 | 使用说明 |
|---|---|---|---|---|
| `resolution_mode` | 分辨率模式 | `auto_from_ref` / `manual` | `auto_from_ref` | `auto_from_ref` 根据参考图和 megapixels 自动计算；`manual` 使用手动 width/height |
| `megapixels` | 百万像素（自动分辨率目标总像素） | 0.01 - 16.0 | `0.40` | 自动模式下的目标总像素数；如 0.40 ≈ 896×448；手动模式下不生效 |

### 输出参数

| 参数名 | 中文说明 | 取值范围 / 选项 | 默认值 | 使用说明 |
|---|---|---|---|---|
| `output_mode` | 输出模式 | `none` / `per_clip` / `merged` / `both` | `none` | `none` 仅缓存；`per_clip` 每 clip 分段输出；`merged` 合并输出；`both` 两者都输出 |
| `filename_prefix` | 文件名前缀 | 字符串 | `H3_Extender` | 输出文件的文件名前缀 |
| `output_image_audio` | 输出图像音频（每CLIP即时解码） | `true` / `false` | `true` | 每 clip 生成完后即时解码为图像+音频预览；关闭可加速但无预览 |

### 缓存加速参数

| 参数名 | 中文说明 | 取值范围 / 选项 | 默认值 | 使用说明 |
|---|---|---|---|---|
| `block_cache` | 块缓存加速（F1B0残差，需T8插件） | `true` / `false` | `false` | 启用 F1B0 残差块缓存加速；需安装 T8 插件；追求最佳画质建议关闭 |
| `block_cache_threshold` | 块缓存阈值（越高越易命中） | 0.0 - 1.0 | `0.12` | 块缓存命中阈值，越高越容易复用缓存块；可能影响画质 |
| `block_cache_device` | 块缓存设备 | `cpu` / `gpu` | `cpu` | 块缓存存储设备；`cpu` 省显存，`gpu` 占显存但更快 |
| `ref_cache` | 参考图缓存（Ref2VA编码，调参重跑提速） | `true` / `false` | `true` | 缓存参考图的 Ref2VA 编码结果，调参重跑时跳过重复编码；不影响画质 |
| `cache_dit` | DiT步间缓存（CacheDiT加速，需插件） | `true` / `false` | `false` | 启用 CacheDiT 步间缓存加速；需安装 CacheDiT 插件；追求最佳画质建议关闭 |

### CLIP 选择与暂停参数

| 参数名 | 中文说明 | 取值范围 / 选项 | 默认值 | 使用说明 |
|---|---|---|---|---|
| `clip_select_enable` | CLIP选择开关（仅渲染指定CLIP） | `true` / `false` | `false` | 启用后仅渲染 `clip_select` 指定的 clip，其余跳过 |
| `clip_select` | CLIP选择 | `all` / `1,3` / `2-5` | `all` | 指定要渲染的 clip 编号；`all` 全部；支持逗号分隔和范围 |
| `pause_enable` | 暂停开关（每CLIP生成完可暂停） | `true` / `false` | `false` | 每 clip 生成完后暂停，等待用户操作（继续/合并/重渲染） |
| `pause_timeout` | 暂停超时（秒，无干预自动继续） | 正整数（秒） | `120` | 暂停后无用户操作的超时时间，超时自动继续生成下一 clip |

### 二次采样参数（画质修复去模糊）

| 参数名 | 中文说明 | 取值范围 / 选项 | 默认值 | 使用说明 |
|---|---|---|---|---|
| `refine_enable` | 二次采样开关（画质修复去模糊） | `true` / `false` | `false` | 启用二次采样修复，在主采样后对 latent 进行放大+去噪，提升画质 |
| `refine_denoise` | 二次采样降噪（0.3-0.45黄金区间） | 0.0 - 1.0 | `0.35` | 二次采样的去噪强度；0.3-0.45 为推荐区间；过低修不动模糊，过高会改变内容 |
| `refine_steps` | 二次采样步数 | 正整数 | `4` | 二次采样的去噪步数；放大倍数大时建议 8-12 步 |
| `refine_upscale_factor` | 潜空间放大倍数（1.0=不放大） | 1.0 - 4.0 | `1.0` | 二次采样前对 latent 空间维度的放大倍数；1.0 = 不放大仅去噪；2.0 = 分辨率翻倍 |

## 最佳画质配置建议

### FastH3 蒸馏模型（4步）不开二采
```
steps=4, sampler=euler, scheduler=simple, denoise=1.0
width=896, height=576, resolution_mode=manual
block_cache=false, cache_dit=false, ref_cache=true
refine_enable=false
```

### FastH3 蒸馏模型（4步）开二采
```
steps=4, sampler=euler, scheduler=simple, denoise=1.0
width=896, height=576, resolution_mode=manual
block_cache=false, cache_dit=false, ref_cache=true
refine_enable=true, refine_denoise=0.45, refine_steps=8, refine_upscale_factor=1.5
```

### 原生 H3 模型（20-24步）
```
steps=20-24, sampler=euler, scheduler=simple
width=896, height=576, resolution_mode=manual
block_cache=false, cache_dit=false
```

## 注意事项

- **FastH3 蒸馏模型必须使用 `euler` 采样器 + `simple` 调度器 + 4 步**，其他配置会导致画质严重下降
- **H3 原生最佳分辨率为 896×576**，超出此范围可能导致画质下降或出现伪影
- **追求最佳画质时关闭 `block_cache` 和 `cache_dit`**，缓存复用可能导致细节丢失
- **单 clip 重渲染模式下**，选中 clip 渲染完后会暂停，等待用户手动选择合并、继续生成或重渲染其他 clip
- **前置 latent 链缺失时**，系统会自动从第一个 clip 补渲染建立完整链，确保 clip 索引正确

## CLIP 卡片多种生成模式总结

每张 CLIP 卡片顶部提供独立的生成控制按钮，卡片左侧边框颜色标识状态：
`rendering 生成中（蓝）/ validated 已生成（绿）/ current 当前待生成（橙）/ cached 已缓存（蓝灰）/ future 后续待生成`。

### 1. 全量渲染（默认）
所有 CLIP 依次连续生成到结束，全部完成后自动合并输出。这是未做任何选择时的默认行为；只要用户没有进行单 clip / 暂停等干预，渲染完成后自动出合并成片。

### 2. 单 CLIP 独立渲染（卡片绿色 ▶ 按钮）
点击某张卡片的 ▶ 只渲染这一个 CLIP（自动把其余 CLIP 的 `render_enabled` 关闭），其他 CLIP 完全不受影响。适合单独精修某个镜头。

### 3. 单 CLIP 重新生成（卡片 ↻ 按钮）
点击 ↻ 选中/取消选中该 CLIP 的「重新生成」模式（单选：同一时刻只有一张卡处于选中）。运行时**仅重新生成此 CLIP**，不碰其他 CLIP；选中时自动清除「合并输出」待定状态。该模式常用于「换一批资产后只想重出某一段」。

### 4. CLIP 选择渲染（`clip_select_enable` / `clip_select` 参数）
- `clip_select = all`：全部渲染；
- 单选（如 `2`）：从该 CLIP 起**连续渲染到结束**（自动依次生成后续 CLIP），除非手动暂停或手动选择合并输出；
- 多选 / 范围（如 `1,3` 或 `2-5`）：仅渲染指定段。

### 5. 暂停 / 继续 / 仅当前 / 中止（⏸ 暂停控制条）
- 手动点击 ⏸ **暂停**：当前 CLIP 生成完、下一个开始前暂停。暂停后可选择：
  - **▶ 继续**：继续渲染剩余 CLIP；
  - **⏹ 仅当前/停止**：停止后续渲染，仅保留已生成的 CLIP（可再点「合并输出」合成）；
  - **✖ 中止**：中止整个渲染。
- 无任何干预时停止后续渲染：不再自动继续、不再自动合并，仅保留已生成的 CLIP。
- 开启 `pause_enable`：每个 CLIP 生成完自动暂停等待；`pause_timeout` 为无干预超时（秒），超时后自动继续。

### 6. 合并输出（工具栏按钮）
将已生成的 CLIP 合成完整视频。若当前有 CLIP 处于「重新生成」状态，会先弹窗确认（取消重新生成、直接合并已有结果）。「单 clip 重渲染 / 暂停」路径不会自动合并，必须手动点此按钮出片。

### 7. render_enabled 渲染开关（卡片 ✓/✗ 按钮）
每张卡片的渲染参与开关，关闭后该 CLIP 不参与本轮生成。

---

## 最新升级功能（v1.27+）

### per-CLIP 外部提示词端口（clip_prompt_1 .. clip_prompt_12）
- 每个 CLIP 卡片都有独立的**可拖线**外部提示词输入端口（节点左侧 `clip_prompt_N`），可连接任意文本节点（如 Muye 提示词反推/扩写、PrimitiveStringMultiline 等）。
- 外部提示词内支持 `@图N` / `@视频N` / `@音频N` 资产引用语法，与资产库图片/视频/音频联动，引用编号按资产库当前顺序解析。
- 端口按实际 CLIP 数量动态显示。

### 外部提示词自动同步
- **连线即同步**：外部提示词接入端口后，其文本自动写入对应 CLIP 卡片提示词框。
- **修改/清空即时同步**：上游文本节点每次输入（打字、粘贴、清空）都会**事件驱动**实时同步进卡片，同时保留 500ms 轮询兜底；**无需手动点击「统一刷新 / Sync All」**。
- 删除连线后自动恢复该 CLIP 内置提示词。
- 执行型上游（反推等只在运行后出结果的节点）通过执行完成事件自动同步。

### ref2va 参考图缓存增强
- 缓存 key 现在绑定 `@图N` 解析出的**资产图片路径签名**（路径+修改时间+大小）：更换资产库后旧缓存自动失效，不会再复用旧图的 VAE 编码。
- **删除/更换资产库时自动清空 ref2va 磁盘缓存**（`bsai-assets-changed` 事件触发 `POST /h3_extender/ref2va_cache/clear`），下次生成重新编码当前资产，彻底杜绝「换了新资产画面还是旧图」。
- 控制参数：`ref_cache`（参考图 Ref2VA 编码缓存开关）。

### 其他修复与改进
- 二次采样 Refine 的 `NestedTensor.reshape` 崩溃修复（改用 `.to_padded_tensor`），开启二采不再回退主采样结果。
- 参数 UI 中英双语（后端英文键名 + 前端双语标签），保留旧工作流兼容。
- 前端版本号可验证：浏览器 Console 输入 `window.__h3ExtenderVersion` 返回当前版本标记。
- 资产库引用清理：资产被删除时，卡片中失效的 `@图N` 引用自动清理，防止悬空引用。
