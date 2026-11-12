# TaoMate-FVSR 音频引导修复 · 电影工厂接入说明（v14.340）

> 论文：TaoMate-FVSR: Audio-Guided Facial Video Restoration（arXiv 2611.03393，淘宝直播团队，2026-11-02）
> 教程：B 站 BV1WrxS6UEDm（"MiniMaxH3 视频人脸糊嘴型飘？淘宝刚开源这个音频修复神器直接救场"）
> 官方仓库：`https://github.com/TaoLiveAIGC/TaoMate-FVSR`（`comfyui` 分支为 ComfyUI 节点版）

## 1. 它解决的是哪一类问题

| 现象 | 普通超分（FlashVSR / SeedVR2 / RealESRGAN） | H3 FaceRefine（本厂 refine 档） | TaoMate-FVSR（本厂 fvrs 档） |
|---|---|---|---|
| 远景小脸糊 | 只提锐度，结构仍崩 | 裁脸局部 H3 重绘，五官能补回来 | 能补，同时给嘴部更强的先验 |
| 牙齿/嘴唇细节假 | 会把错的牙形一起放大 | 依赖 H3 自身重绘 | 音频引导重建，论文里 LPIPS/DISTS 最低 |
| 嘴型与音轨不同步 | 完全不处理 | 不处理（没有音频条件） | 原声模式下按音频对齐嘴型 |
| 换了新配音 | 需再接一个 dubbing 模型，两步误差叠加 | 不适用 | 同一模型内直接按新音频重建嘴型 |

论文口径（talking-head 基准）：原声修复 Sync-C 7.41，高于 GPEN 6.31 / FlashVSR 6.47；换音配音 Sync-C 8.18，明显高于"FlashVSR → X-Dub/KeySync/LipForcing"等两步管线。

## 2. 电影工厂里怎么用

1. 装好官方节点插件与权重（见第 4 节）。
2. 在电影工厂节点里把 **`face_lock_mode`** 选成 **`fvrs (audio-guided restore)`**。
3. 出片方式建议：
   - 多分镜成片：`output_mode = merged` 或 `both`。每段独立修复后再 xfade/无缝拼接，切镜边界正好是"单人单镜"的合法边界。
   - 直播带货 / 对口型：`lip_audio` / `lip_voice` 驱动时，分镜 mp4 自带的就是那句台词，fvrs 直接以该音轨做条件——这正是"嘴型飘"最有效的修法。
4. 参数用环境变量调，不动节点 widget（避免老工作流 widget 索引错位）：

| 环境变量 | 默认 | 含义 |
|---|---|---|
| `BSAI_FVRS_STEPS` | 10 | Euler 去噪步数（官方默认；不建议低于 8） |
| `BSAI_FVRS_NOISE` | 0.8 | 源噪声混合比例（越低越贴近原画面） |
| `BSAI_FVRS_SHIFT` | 5.0 | sigma shift |
| `BSAI_FVRS_AUDIO_CFG` | 4.0 | 音频引导强度（嘴型跟音频的力度） |
| `BSAI_FVRS_REF_CFG` | 1.7 | 参考/历史引导强度（保脸力度） |
| `BSAI_FVRS_BUDGET` | 15.0 | 显存分配预算 GiB（10–15，配合 `--disable-cuda-malloc`） |
| `BSAI_FVRS_CROP_SCALE` | 0.8 | YOLO 裁脸框放大倍率（脸太小/裁太紧时调） |
| `BSAI_FVRS_LOCAL_DIR` | 空 | 权重目录；空则查 `models/TaoMate-FVSR` 或 extra_model_paths 的 `taomate` 键 |
| `BSAI_FVRS_GPEN_REPO` | 空 | GPEN **源码**目录；缺省自动找 `models/TaoMate-GPEN-source`，仍缺则降级用首帧裁剪原图做参考 |
| `BSAI_FVRS_DETECTOR` | 空 | 人脸检测权重；缺省用 `models/ultralytics/face_yolov8n.pt` |
| `BSAI_FVRS_SEED` | 42 | 随机种子 |

5. 帧率：官方链路固定 25fps 解码/编码；本厂在后处理后自动 `fps=<出片帧率>` 回转（默认 24），避免拼接后音画总时长漂移。

## 3. 失败兜底与硬边界

- **任何异常都原样返回原片段**：插件缺失、权重缺失、检测不到脸、疑似切镜、OOM、超时，都不会让出片失败，只在日志里打一行 `⚠️ TaoMate-FVSR 跳过`。
- 官方当前版本只支持 **单人单镜、512 人脸推理**（2× 档在官方 CLI 有，ComfyUI 节点未暴露）。
- 分镜内部若有切镜，`Prepare Video` 会直接报 `Possible shot cuts at 25fps frame indices ...`；此时应把该段拆成更短的 CLIP 再出。
- 人脸过小 / 大幅侧转 / 两人交叉时检测会漂；先看 `Prepare Video` 的 first crop 预览，再定 `CROP_SCALE` 或改固定 ROI。
- 修复会调用 `unload_all_models()` 释放 ComfyUI 侧模型再跑；出片后继续排队时 H3 会重新加载，属预期行为。

## 4. Windows 安装（官方标注"Windows 未验收"，按下列顺序做）

> 风险点：`requirements.txt` 会装 `livevsr`（git 源）与 `ultralytics==8.4.14`。**不要**让 pip 顺手改 PyTorch；先 dry-run 看它想动什么。

```powershell
# 1) 代码（已克隆到 custom_nodes/ComfyUI-TaoMate-FVSR，comfyui 分支）
# 2) 先只看安装计划，不改环境
C:\BSAI\ComfyUI-BSAI_pro_v43\python\python.exe -m pip install --dry-run `
  -r C:\BSAI\ComfyUI-BSAI_pro_v43\ComfyUI\custom_nodes\ComfyUI-TaoMate-FVSR\requirements.txt

# 3) 确认不会升降 torch/torchvision 后再真正安装
C:\BSAI\ComfyUI-BSAI_pro_v43\python\python.exe -m pip install `
  -r C:\BSAI\ComfyUI-BSAI_pro_v43\ComfyUI\custom_nodes\ComfyUI-TaoMate-FVSR\requirements.txt

# 4) 权重（约 14.89GB，可用 hf 镜像）
cd C:\BSAI\ComfyUI-BSAI_pro_v43\ComfyUI\custom_nodes\ComfyUI-TaoMate-FVSR
C:\BSAI\ComfyUI-BSAI_pro_v43\python\python.exe scripts\download_models.py `
  --dest ..\..\models\TaoMate-FVSR --gpen-source-dir ..\..\models\TaoMate-GPEN-source --endpoint https://hf-mirror.com

# 5) 校验
C:\BSAI\ComfyUI-BSAI_pro_v43\python\python.exe scripts\download_models.py `
  --dest ..\..\models\TaoMate-FVSR --check --gpen-source-dir ..\..\models\TaoMate-GPEN-source
```

- 启动 ComfyUI 时加 `--disable-cuda-malloc`（官方 15GiB 预算依赖 PyTorch 原生分配器）。
- 预期目录：`ComfyUI/models/TaoMate-FVSR/{TaoMate-FVSR.safetensors, config.json, Wan2.2_VAE.pth, hubert/, GPEN-BFR-512.pth, RetinaFace-R50.pth, ParseNet-latest.pth, face_yolov8n.pt}` 与 `ComfyUI/models/TaoMate-GPEN-source/`。
- 本机已有 `models/vae/wan2.2_vae.safetensors`，但官方脚本按文件名/SHA256 校验，**不要**手工改名顶替，直接用脚本下载的那份。

## 5. 验收清单（装完后按顺序跑）

1. 重启 ComfyUI，日志无 import 报错，节点面板出现 `TaoMate FVSR` 分类下 5 个节点。
2. 拖 `custom_nodes/ComfyUI-TaoMate-FVSR/examples/yolo-gpen-workflow.json`，把 `max_frames` 设 77，先只跑裁剪/参考预览，确认 first crop 框住整张脸。
3. 放行 `Save / Paste Back Video`，跑一个 **5 秒、单人、无切镜** 的 H3 片段，确认输出**尺寸不变**、时长不变、音轨仍在。
4. 回电影工厂，`face_lock_mode = fvrs`，`output_mode = merged`，跑两段 8 秒分镜；检查 `output/` 下 `*_merged.mp4` 与 `output/taomate_fvrs/` 临时产物，日志应出现 `🎙️ TaoMate-FVSR 修复完成`。
5. 对比目检：牙齿边界、唇形闭合、说话停顿处的嘴型是否跟着音频；若过度重绘，降 `BSAI_FVRS_NOISE` 到 0.6–0.7 或 `AUDIO_CFG` 到 3.0。

## 6. 已知未验证项（官方与本地一致）

- Windows 下 `livevsr` 与 GPEN 自定义算子未做官方验收；若 GPEN 编译失败，可先把 `BSAI_FVRS_GPEN_REPO` 留空走降级参考。
- 消费级 16GB 卡、8/12GB 卡未验证；本机 5090 24GB 建议先 10 步、单段 8 秒起测。
- 长片段（>15s）会显著吃磁盘与内存（官方 14.88s 用例进程内存约 17.75GiB）。
