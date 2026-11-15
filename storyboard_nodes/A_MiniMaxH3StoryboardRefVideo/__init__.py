# -*- coding: utf-8 -*-
"""MiniMax H3 official full-reference prompt extraction and video nodes.

已并入 BSAI-ComfyUI-H3-Film-Factory 插件（本目录作为其子包加载，不再单独作为插件安装）。
前端脚本已上收到插件根目录 web/js/storyboard_ref.js，随宿主插件的 WEB_DIRECTORY 一起加载。
"""
from .nodes_storyboard_ref import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]