# ported ｜ 并入的节点移植说明

本目录是「电影工厂」（`BSAI-ComfyUI-H3-Film-Factory`）吸收的**原独立插件节点**副本。
节点类名（`NODE_CLASS_MAPPINGS` 的键）与显示名保持与源插件完全一致，所以旧工作流
（如 `BSAI+AI造梦湿【卡点舞蹈MV工作流 v2.0】.json`）不需要改节点即可直接运行。

## 映射表

| 本目录文件 | 源插件目录（已移出 custom_nodes） | 注册的节点类名 |
|---|---|---|
| `librosa_beat_cue.py` | `A_LibrosaBeatCue` | `A_LibrosaBeatCue`、`A_TextInjectCue` |
| `h3_context_pro/` | `H3ContextContinuationPro` | `H3ContextInjectPro`、`H3ContextTrimPro` |
| `vhs_custom_path.py` | `ComfyUI-VideoCombineCustomPath` | `VHS_VideoCombineCustomPath`、`VHS_LoadVideoCustomLatest` |
| `selflift_avatar/` | `selflift-Avatar` | `SelfLiftAvatarH3Sampler`、`SelfLiftAvatarH3SpatialAnchoredSampler`、`SelfLiftAvatarH3TST`、`SelfLiftAvatarImageSampler` |
| `vrgdg_video_compare.py` | `VRGDG_VideoCompare` | `VRGDG_VideoCompareSlider` |
| `h3_sigma_refiner.py` | `ComfyUI-YCNodes-MiniMax-H3`（`py/h3_sigma_refiner.py`） | `H3SigmaRefiner` |
| `h3_dynamic_cfg_scheduler.py` | `ComfyUI-YCNodes-MiniMax-H3`（`py/h3_dynamic_cfg_scheduler.py`） | `H3DynamicCFGScheduler` |

`ComfyUI-YCNodes-MiniMax-H3` 的 `__init__.py` 是「扫 py 目录、逐个 import 并合并映射」的装载器，
移植时按同样语义把两个模块直接平铺进本目录，由 `ported/__init__.py` 分别 try/except 注册；
该插件声明的 `WEB_DIRECTORY = "./js"` 实际没有 js 目录，故本次没有前端文件要搬。

前端 JS 扩展同步放到了插件根 `web/` 下（ComfyUI 按 `/extensions/<插件目录>/<文件名>` 提供，
只有放在 web 根目录、保持一层目录深度，原 `import ... from "../../scripts/app.js"` /
`"../../../scripts/app.js"` 的相对路径才继续有效）：

| web 下文件 | 源文件 | 作用 |
|---|---|---|
| `ported_vrgdg_video_compare.js` | `VRGDG_VideoCompare/web/VRGDG_VideoCompare.js` | 一二采对比滑块面板 |
| `ported_selflift_model_input_order.js` | `selflift-Avatar/web/model_input_order.js` | low/high_res_model 输入槽顺序修正 |
| `ported_selflift_tiling_controls.js` | `selflift-Avatar/web/tiling_controls.js` | 高分辨率分块控件联动 |

## 移植时改动的仅有 3 处

1. `vhs_custom_path.py` 中 `_VHS_DIR`：源插件用「上溯两层」定位 custom_nodes，移植后位于
   `Film-Factory/ported/`，改为上溯三层并改用 `_CUSTOM_NODES_DIR` 变量；
   `sys.path` 注入 `ComfyUI-VideoHelperSuite` 的机制不变（VHS 插件仍是外部依赖，必须安装）。
2. `h3_context_pro/context_pro.py`：`from .Yuan_common import handle_chunk_upload`
   → `from .yuan_common import handle_chunk_upload`（同目录文件重命名为小写）。
3. `H3ContextContinuationPro/__init__.py` 的转发逻辑移到 `h3_context_pro/__init__.py`。

除此之外节点代码、参数默认值、目录写入（`output/H3-Mubu` 等）、HTTP 路由
（`/yuan_h3_motion_upload_latent`、`/vrgdg/video_compare/upload`、
`/vrgdg/video_compare/save_recording`）全部原样保留。

## 依赖（删除源插件后仍需存在）

- `ComfyUI-VideoHelperSuite`：`VHS_VideoCombineCustomPath` 继承其 `VideoCombine`。
- `videohelpersuite` 之外的外部依赖保持原样：`librosa`（A_LibrosaBeatCue 首次分析时才 import）、
  `av`、`psutil`、`comfy_kitchen`（selflift global_stream）。
- `VRGDG` 前端 JS 还会调用 `/vrgdg/video_editor/video`，该路由由
  `comfyui-vrgamedevgirl` 插件提供，与本次移植无关，请勿一并删除。

## 回滚

源插件目录整体移到了 ComfyUI 根目录下的
`ported_backup_20261116\`（不在 `custom_nodes` 内，ComfyUI 不会加载）。
需要回滚时把它移回 `custom_nodes`，并删除本目录与 `web/ported_*` 三个 JS。

## G 盘（intel XPU 环境）说明

本机 ComfyUI\custom_nodes 原本就没有这 6 个源插件目录，本次是首次直接并入，
不存在「删除原插件」环节，也不需要 ported_backup_20261116 备份。
本目录内容与 C:\BSAI\ComfyUI-BSAI_pro_v43 那套电影工厂的 ported/ 完全一致。
