# ComfyUI-Manager 注册信息 - BSAI 插件包

## 提交方式
1. Fork https://github.com/Comfy-Org/ComfyUI-Manager
2. 在 `custom-node-list.json` 的 `custom_nodes` 数组末尾添加以下条目
3. 提交 Pull Request

---

## 插件列表

```json
{
  "author": "xm6018924",
  "title": "BSAI-ComfyUI-H3-Film-Factory",
  "id": "bsai-comfyui-h3-film-factory",
  "reference": "https://github.com/xm6018924/BSAI-ComfyUI-H3-Film-Factory",
  "files": [
    "https://github.com/xm6018924/BSAI-ComfyUI-H3-Film-Factory"
  ],
  "install_type": "git-clone",
  "description": "BSAI H3 电影工厂 - 多CLIP分镜逐帧生成 + 单CLIP重渲染 + 资产库 + 二次采样 + 内置电影模板",
  "category": "video",
  "tags": ["video", "minimax", "h3", "film", "storyboard"]
},
{
  "author": "xm6018924",
  "title": "BSAI-ComfyUI-FastH3",
  "id": "bsai-comfyui-fasth3",
  "reference": "https://github.com/xm6018924/BSAI-ComfyUI-FastH3",
  "files": [
    "https://github.com/xm6018924/BSAI-ComfyUI-FastH3"
  ],
  "install_type": "git-clone",
  "description": "BSAI FastH3 加速节点 - MiniMax H3 推理加速优化",
  "category": "video",
  "tags": ["video", "minimax", "h3", "fast", "performance"]
},
{
  "author": "xm6018924",
  "title": "BSAI-ComfyUI-Sol-H3",
  "id": "bsai-comfyui-sol-h3",
  "reference": "https://github.com/xm6018924/BSAI-ComfyUI-Sol-H3",
  "files": [
    "https://github.com/xm6018924/BSAI-ComfyUI-Sol-H3"
  ],
  "install_type": "git-clone",
  "description": "BSAI Sol-H3 - MiniMax H3 Sol-Attention 注意力优化",
  "category": "video",
  "tags": ["video", "minimax", "h3", "attention", "optimization"]
},
{
  "author": "xm6018924",
  "title": "BSAI-ComfyUI-vdn-minimax-h3",
  "id": "bsai-comfyui-vdn-minimax-h3",
  "reference": "https://github.com/xm6018924/BSAI-ComfyUI-vdn-minimax-h3",
  "files": [
    "https://github.com/xm6018924/BSAI-ComfyUI-vdn-minimax-h3"
  ],
  "install_type": "git-clone",
  "description": "BSAI VDN-H3 - MiniMax H3 Video DeltaNet 蒸馏加速 (8步≈50步质量)",
  "category": "video",
  "tags": ["video", "minimax", "h3", "vdn", "distillation", "turbo"]
},
{
  "author": "xm6018924",
  "title": "BSAI-Asset-Library-Auto-List",
  "id": "bsai-asset-library-auto-list",
  "reference": "https://github.com/xm6018924/BSAI-Asset-Library-Auto-List",
  "files": [
    "https://github.com/xm6018924/BSAI-Asset-Library-Auto-List"
  ],
  "install_type": "git-clone",
  "description": "BSAI 资产库自动列表 - 自动扫描 input 目录生成资产列表",
  "category": "asset",
  "tags": ["asset", "library", "browser"]
},
{
  "author": "xm6018924",
  "title": "BSAI-ComfyUI-MiniMax-H3-PDD-Acc",
  "id": "bsai-comfyui-minimax-h3-pdd-acc",
  "reference": "https://github.com/xm6018924/BSAI-ComfyUI-MiniMax-H3-PDD-Acc",
  "files": [
    "https://github.com/xm6018924/BSAI-ComfyUI-MiniMax-H3-PDD-Acc"
  ],
  "install_type": "git-clone",
  "description": "BSAI MiniMax H3 PDD 精度加速优化",
  "category": "video",
  "tags": ["video", "minimax", "h3", "performance", "accuracy"]
},
{
  "author": "xm6018924",
  "title": "BSAI-ComfyUI-TaoMate",
  "id": "bsai-comfyui-taomate",
  "reference": "https://github.com/xm6018924/BSAI-ComfyUI-TaoMate",
  "files": [
    "https://github.com/xm6018924/BSAI-ComfyUI-TaoMate"
  ],
  "install_type": "git-clone",
  "description": "BSAI TaoMate 工具集 - ComfyUI 辅助工具节点",
  "category": "utilities",
  "tags": ["utility", "tool"]
},
{
  "author": "xm6018924",
  "title": "BSAI-ComfyUI_Contextual-Series",
  "id": "bsai-comfyui-contextual-series",
  "reference": "https://github.com/xm6018924/BSAI-ComfyUI_Contextual-Series",
  "files": [
    "https://github.com/xm6018924/BSAI-ComfyUI_Contextual-Series"
  ],
  "install_type": "git-clone",
  "description": "BSAI Contextual Series - 上下文连续生成系列节点",
  "category": "video",
  "tags": ["video", "context", "continuity"]
},
{
  "author": "xm6018924",
  "title": "BSAI-H3-MotionFix",
  "id": "bsai-h3-motionfix",
  "reference": "https://github.com/xm6018924/BSAI-H3-MotionFix",
  "files": [
    "https://github.com/xm6018924/BSAI-H3-MotionFix"
  ],
  "install_type": "git-clone",
  "description": "BSAI H3 MotionFix - MiniMax H3 运动一致性修复",
  "category": "video",
  "tags": ["video", "minimax", "h3", "motion", "fix"]
},
{
  "author": "xm6018924",
  "title": "BSAI-H3-upscale-4K",
  "id": "bsai-h3-upscale-4k",
  "reference": "https://github.com/xm6018924/BSAI-H3-upscale-4K",
  "files": [
    "https://github.com/xm6018924/BSAI-H3-upscale-4K"
  ],
  "install_type": "git-clone",
  "description": "BSAI H3 Upscale 4K - MiniMax H3 视频 4K 超分",
  "category": "video",
  "tags": ["video", "minimax", "h3", "upscale", "4k"]
},
{
  "author": "xm6018924",
  "title": "BSAI-MiniMAX-H3-Prompt",
  "id": "bsai-minimax-h3-prompt",
  "reference": "https://github.com/xm6018924/BSAI-MiniMAX-H3-Prompt",
  "files": [
    "https://github.com/xm6018924/BSAI-MiniMAX-H3-Prompt"
  ],
  "install_type": "git-clone",
  "description": "BSAI MiniMax H3 提示词模板库 - 电影运镜/调色/分镜模板",
  "category": "prompt",
  "tags": ["prompt", "template", "film", "minimax", "h3"]
},
{
  "author": "xm6018924",
  "title": "BSAI-ComfyUI-FaceRefine",
  "id": "bsai-comfyui-face-refine",
  "reference": "https://github.com/xm6018924/BSAI-ComfyUI-FaceRefine",
  "files": [
    "https://github.com/xm6018924/BSAI-ComfyUI-FaceRefine"
  ],
  "install_type": "git-clone",
  "description": "BSAI FaceRefine - 面部细节修复优化",
  "category": "image",
  "tags": ["face", "refine", "detail"]
},
{
  "author": "xm6018924",
  "title": "BSAI_ComfyUI_IndexTTS-2.5",
  "id": "bsai-comfyui-indextts-25",
  "reference": "https://github.com/xm6018924/BSAI_ComfyUI_IndexTTS-2.5",
  "files": [
    "https://github.com/xm6018924/BSAI_ComfyUI_IndexTTS-2.5"
  ],
  "install_type": "git-clone",
  "description": "BSAI IndexTTS 2.5 - 高质量语音合成 TTS",
  "category": "audio",
  "tags": ["audio", "tts", "speech", "voice"]
},
{
  "author": "xm6018924",
  "title": "BSAI_ComfyUI_Nodes",
  "id": "bsai-comfyui-nodes",
  "reference": "https://github.com/xm6018924/BSAI_ComfyUI_Nodes",
  "files": [
    "https://github.com/xm6018924/BSAI_ComfyUI_Nodes"
  ],
  "install_type": "git-clone",
  "description": "BSAI ComfyUI 通用工具节点集",
  "category": "utilities",
  "tags": ["utility", "tool", "nodes"]
},
{
  "author": "xm6018924",
  "title": "BSAI_ComfyUI_SolarWM_H3",
  "id": "bsai-comfyui-solarwm-h3",
  "reference": "https://github.com/xm6018924/BSAI_ComfyUI_SolarWM_H3",
  "files": [
    "https://github.com/xm6018924/BSAI_ComfyUI_SolarWM_H3"
  ],
  "install_type": "git-clone",
  "description": "BSAI SolarWM H3 - MiniMax H3 水印去除",
  "category": "video",
  "tags": ["video", "minimax", "h3", "watermark", "remove"]
},
{
  "author": "xm6018924",
  "title": "BSAI_Premiere_Pro",
  "id": "bsai-premiere-pro",
  "reference": "https://github.com/xm6018924/BSAI_Premiere_Pro",
  "files": [
    "https://github.com/xm6018924/BSAI_Premiere_Pro"
  ],
  "install_type": "git-clone",
  "description": "BSAI Premiere Pro 导出 - ComfyUI 时间线导出到 Premiere",
  "category": "video",
  "tags": ["video", "premiere", "export", "timeline"]
}
```

---

## 注意事项

1. **每个插件都需要单独的 README.md 和 LICENSE**
2. **每个插件根目录需要有 `__init__.py`** 并且正确导出 `NODE_CLASS_MAPPINGS`
3. **提交 PR 前测试**：在 ComfyUI-Manager 里勾选"使用本地数据库"，确认能正常加载
4. **分类建议**：
   - video: 视频生成/编辑相关
   - image: 图片处理相关
   - audio: 音频相关
   - prompt: 提示词模板相关
   - utilities: 工具类
   - asset: 资产库相关
