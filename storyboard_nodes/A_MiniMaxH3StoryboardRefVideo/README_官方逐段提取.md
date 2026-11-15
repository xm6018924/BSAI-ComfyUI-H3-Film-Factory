# MiniMax H3 官方 Full Ref2VA 分镜看板

## 提示词分段

把完整分镜提示词接到 `[A] MiniMax H3 官方参考提示词预览看板` 或 `[A] MiniMax H3 官方参考生视频 (Full Ref2VA)` 的 `prompt_source`。默认按 `===== prompt_N =====` 分段，例如 `===== prompt_01 =====`；也兼容旧格式 `===== prompt1 =====`。节点按标记出现顺序编号，所以 `clip_index=1` 选择第一个标记后的正文，依次类推，不按标记文本中的数字跳转。每段应包含六个 H3 字段和 Shot 描述。

看板每段显示为全宽 CLIP 卡片，左栏按首次出现顺序列出本段所引用的素材和重复次数，右栏显示完整六字段提示词，并在 `@图N` 处内嵌显示缩略图。CLIP 标题右侧持续显示时长和帧数。每张卡可单独折叠或展开，工具栏也可全部折叠或展开；点击 CLIP 标题会同步设置连接的提取/打包节点 `clip_index`。

## 素材索引映射

对于 BSAI 格式中的 `@图N`，节点先用 N 查找 Asset Library 对应的源素材索引，再按该 prompt 中素材首次出现顺序生成本段连续的 H3 `<Picture 1>`、`<Picture 2>` 等编号。例如首段出现 `@图36`、`@图1`、`@图20` 时，H3 图片槽依次使用 Asset Library 的第 36、1、20 张图片，并映射为 `<Picture 1>`、`<Picture 2>`、`<Picture 3>`。不会把源 `@图N` 直接当成 H3 图片编号。

`subject_definitions` 按原有行顺序分配本段连续的 `<Subject N>`；提示词其他字段中的相同源图引用会映射回对应 Subject 标签。Picture 与 Subject 是两个独立编号体系。每段最多支持 MiniMax H3 的 9 张图片；引用的 `@图N` 在资源库中缺失时，打包节点会明确报错。

原生 H3 `<Picture N>` 提示词继续按原有编号读取。单段不能混合 `@图N` 源编号与 `<Picture N>` 内部编号，避免发生索引歧义。

## 时长与帧数

每段优先读取 `detailed_description:` 后第一行且唯一一行 `[Recommended duration]: N seconds`。看板显示该原始时长（例如 `12.000秒`），帧数按 H3 的 24 fps 和 `17n+5` 帧对齐规则计算（12 秒对应 294 帧）。打包节点也使用同一时长计算帧数；不会以 summary 中的时长或 Shot 时间戳覆盖该字段。没有推荐时长时，才沿用原有单段时长或帧数兜底逻辑。

H3 单段视频的 15 秒上限仍有效。输入时长超过上限时，打包节点报错，看板标红提示。

## 节点

- `[A] MiniMax H3 官方参考提示词预览看板`：连接 `prompt_source` 和可选 `asset_library`，可查看全部 prompt 的引用、缩略图、时长、帧数。
- `[A] MiniMax H3 官方参考生视频 (Full Ref2VA)`：连接 CLIP、Video VAE、Audio VAE、`prompt_source`、`asset_library`，并用 `clip_index` 选择一段生成。
- `[A] MiniMax H3 官方参考提示词逐段提取`：按同一分段和时长规则输出选中段落。

格式参考：[MiniMax H3 Full-Reference Mode Rewrite Output Format Guide](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md)。修改 Python 节点后重启 ComfyUI；浏览器脚本没有刷新时，强制刷新页面。
