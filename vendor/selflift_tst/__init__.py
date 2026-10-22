# -*- coding: utf-8 -*-
# vendor/selflift_tst — comfyui-SelfLift 上游 TST 核心模块暂存区（仅暂存，不注册任何 ComfyUI 节点）
#
# 来源: https://github.com/facok/comfyui-SelfLift (h3_tst.py)
# 用途: P2 少步数画质补偿 (Temporal State Transport, arXiv:2609.08505)。
#       内置于电影工厂插件, 粉丝无需再单独安装 comfyui-SelfLift;
#       若外部已装 comfyui-SelfLift, extender.py::_apply_h3_tst 仍优先用内置副本。
# 授权说明: 上游仓库暂无 LICENSE 文件, 来源与出处声明见同目录 NOTICE.md / PROVENANCE.json,
#       集成实现时须保留对 facok (comfyui-SelfLift) 与 TST 论文作者的致谢。
#
# 模块清单:
#   h3_tst.py  — TST patch_model: 基于谱张力的视频帧级注意力温度校正 (仅供电影工厂二采路径使用)
#
# 注意: 本目录文件保持上游原样, 不直接修改; 集成适配在 extender.py 侧, 便于跟随上游更新 diff。

__all__ = []
