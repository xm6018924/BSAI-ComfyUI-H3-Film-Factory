# 分镜拆段与顺序渲染节点 / Storyboard segmentation nodes

这两个插件原本独立放在 `custom_nodes/` 下，现已**并入宿主插件 `BSAI-ComfyUI-H3-Film-Factory`**：宿主 `__init__.py` 通过
`from .storyboard_nodes import ...` 把这里的节点一并注册，前端脚本上收到宿主 `web/js/storyboard_ref.js`。

## 安装：只装一个插件

**`custom_nodes/` 里只需要 `BSAI-ComfyUI-H3-Film-Factory` 这一个目录**，不要再单独放
`A_MiniMaxH3StoryboardDuration` / `A_MiniMaxH3StoryboardRefVideo`（放进去会和内置节点重复注册）。装好后重启 ComfyUI，
节点出现在 `BSAI/…` 分类下，`/extensions` 里会自动带上 `js/storyboard_ref.js`（宿主 `WEB_DIRECTORY = "./web"` 递归扫描）。

升级或改动 `node.py` 后：宿主插件目录里改文件 → 重启 ComfyUI 即可。宿主插件本身是个 git 仓库，`git status` 能看见改动，
`commit` 即发布，不会出现“运行副本与仓库副本各一份”的静默漂移。

| 目录 | 节点 | 作用 |
|---|---|---|
| `A_MiniMaxH3StoryboardDuration` | `[A] MiniMax H3 官方提示词时长解析` | 按分段标记切分官方提示词，取出第 N 段的时长与累计起始时间 |
| | `[A] MiniMax H3 分镜段数统计` | 统计提示词里实际有多少个 prompt 段，供序号回绕取上界 |
| | `[A] 全段自动续排（一次运行跑完全部分镜）` | 当前段跑完后自动把下一段（seed+1）排进队列，末段自动停 |
| `A_MiniMaxH3StoryboardRefVideo` | `[A] MiniMax H3 官方参考提示词逐段提取` | 单段抽取（含潜力/看板数据） |
| | `[A] MiniMax H3 官方参考生视频 (Full Ref2VA)` | 按段选提示词 + 参考图/参考视频，输出 CLIP 条件与首帧 latent |
| | `[A] MiniMax H3 官方参考提示词预览看板` | 前端看板：逐段预览、跳段 |

## 分段格式

官方提示词按分段标记切开，默认标记：

```
===== promptN =====
```

`N` 可以是数字，也可以是字面 `N`（按出现顺序编号）；标记编号重复时同样按出现顺序计数。

## 典型接线（一镜到底 N 段）

```
整段提示词 ──┬─→ 分镜段数统计 ──┐
             ├─→ 时长解析 (clip_index) ──→ clip_duration_sec / start_time_sec
             └─→ 参考生视频 (clip_index) ──→ 条件 / latent
SeedNode ──→ MathExpression (a - 1) % b + 1 ──→ 各处 clip_index     # b = 段数
SeedNode ──→ 全段自动续排 (seed, segment_count, after)              # 逐段排队，末段自停
```

`SeedNode` 既当噪声种子又当片段选择器：用 `(a - 1) % 段数 + 1` 回绕就能一直递增而不越界；
再让「全段自动续排」负责逐段排队，运行次数填 1、点一次即可跑完全部分镜。把该节点里的开关关掉即退回单段手动渲染。

`全段自动续排` 走服务端续排：复制当前 prompt、只改 SeedNode 的 `seed`，经
`execution.validate_prompt` 校验后写入 `PromptServer.prompt_queue`（本机 ComfyUI 0.4x 的六元组
`(number, prompt_id, prompt, extra_data, outputs, sensitive)`）。

## 依赖

`A_MiniMaxH3StoryboardRefVideo` 需要 torch / torchaudio / numpy / Pillow / opencv-python（见其 `requirements.txt`）。
`A_MiniMaxH3StoryboardDuration` 无额外依赖，只用标准库。

## 变更

- 2026-11-15：新增段数统计与全段自动续排两个节点；`clip_index` 越界（跑到第 13 段起必报
  `clip_index=… 超出范围`）改由工作流侧取模回绕解决。
