# -*- coding: utf-8 -*-
# vendor/selflift_avatar — selflift-Avatar 上游核心算法模块暂存区（仅暂存，不注册任何 ComfyUI 节点）
#
# 来源: https://github.com/slmonker/selflift-Avatar (commit 5b93b6c, 2026-10-20)
# 上游分支: main (global-context memory saving)
# 用途: 等待集成到 BSAI-ComfyUI-H3-Film-Factory 二采路径 (v14.148/v14.149 tiled refine)
#       作为可切换的 global_stream / global / global_ram 高分辨率省显存模式。
# 授权说明: 上游仓库暂无 LICENSE 文件, 来源与出处声明见同目录 NOTICE.md / PROVENANCE.json,
#       集成实现时须保留对上游及 Fish4AI (comfyui-SelfLift-Fish) 的致谢。
#
# 模块清单:
#   h3_global_tiling.py     — 全局上下文省显存核心: token 分块 DiT block 替换 / tiled_model()
#   h3_stream_attention.py  — global_stream: head 分组稀疏注意力 (依赖 comfy_kitchen)
#   h3_ram_attention.py     — global_ram: 主机 RAM 分级 (依赖 psutil)
#   h3_prepared_weights.py  — DynamicVRAM weight cache (highres_weight_cache_gb)
#   h3_tiling.py            — spatial 分块规划 (对照参考 + stale-reference 崩溃修复思路)
#   avatar_masks.py         — H3 音视频 latent 掩码约定
#   UPSTREAM_README_CN.md   — 上游中文说明 (模式选择/参数指南)
#
# 注意: 本目录文件保持上游原样, 集成时在 extender.py 侧做适配层, 不直接修改上游文件,
#       便于后续跟随上游更新 diff 对比。

__all__ = []
