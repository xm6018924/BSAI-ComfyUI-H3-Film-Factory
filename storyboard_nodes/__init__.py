# -*- coding: utf-8 -*-
"""Film Factory 内置分镜节点。

原 `A_MiniMaxH3StoryboardDuration` / `A_MiniMaxH3StoryboardRefVideo` 两个独立插件已并入
本插件（`BSAI-ComfyUI-H3-Film-Factory`），ComfyUI 里只需要装这一个插件。

前端脚本已上收到插件根目录的 `web/js/storyboard_ref.js`，随 `WEB_DIRECTORY = "./web"` 一起加载。
"""

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

# 时长解析 / 段数统计 / 全段自动续排
try:
    from .A_MiniMaxH3StoryboardDuration import (
        NODE_CLASS_MAPPINGS as DURATION_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as DURATION_DISPLAY,
    )
    NODE_CLASS_MAPPINGS.update(DURATION_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(DURATION_DISPLAY)
except Exception as e:
    print(f"[H3 Film Factory] storyboard A_MiniMaxH3StoryboardDuration import failed: {e}")

# 官方参考提示词逐段提取 / 打包生视频 / 看板
try:
    from .A_MiniMaxH3StoryboardRefVideo import (
        NODE_CLASS_MAPPINGS as REF_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as REF_DISPLAY,
    )
    NODE_CLASS_MAPPINGS.update(REF_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(REF_DISPLAY)
except Exception as e:
    print(f"[H3 Film Factory] storyboard A_MiniMaxH3StoryboardRefVideo import failed: {e}")

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
