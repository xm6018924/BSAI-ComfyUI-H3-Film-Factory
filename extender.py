"""
MiniMax H3 Extender
===================

One horizontal, JS-driven sequence node that replaces the repeated
Ref2VA -> Motion Context -> Sampler -> Disk Join graph while keeping the
validated disk cache and the separate Final Decode / Preview node.

The node intentionally accepts an already-patched H3 MODEL. Sigma-shift,
LoRA, Spectrum or other model patches therefore remain external and compose
normally before the Extender.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import datetime as _datetime
import hashlib
import io
import json
import math
import os
import re
from pathlib import Path
import contextlib
import secrets
import shutil
import subprocess
import tempfile
import time
import uuid
import zipfile
import numpy as np
import torch
import torchaudio
import types
import comfy.model_management
import comfy.nested_tensor
import comfy.ops
import comfy.quant_ops
import comfy.sample
import comfy.samplers
import comfy.utils
import latent_preview
import node_helpers
import folder_paths
import threading
from aiohttp import web
from PIL import Image, ImageEnhance, ImageOps
from server import PromptServer

# ==== BSAI 插件协同 SDK：加载即自动注册（失败不拖垮插件） ====
try:
    import sys as _bsai_sys, os as _bsai_os
    _BSAI_ORCH_DIR = _bsai_os.path.join(
        _bsai_os.path.dirname(_bsai_os.path.abspath(__file__)),
        "..", "BSAI-ComfyUI-Orchestrator")
    if _bsai_os.path.isdir(_BSAI_ORCH_DIR) and _BSAI_ORCH_DIR not in _bsai_sys.path:
        _bsai_sys.path.insert(0, _BSAI_ORCH_DIR)
    from bsai_orch_client import BSAIOrch  # noqa: E402
    BSAIOrch.register(
        name="BSAI-H3-Film-Factory",
        kind="sampling",
        hardware=["cuda"],
    )
except Exception as _bsai_e:  # 注册失败不得拖垮插件
    print(f"[BSAI SDK] BSAI-H3-Film-Factory 注册失败(忽略): {_bsai_e}")
# ==== BSAI SDK 块结束 ====

from .motion_context_ram import MiniMaxH3MotionContextRAM, MC_KEY
from .prompt_bridge import PROMPT_PACK_TYPE, _prompt_pack_signature
from .motion_context_disk import (
    CACHE_VERSION,
    CACHE_TYPE,
    _DATA_START,
    _chain_paths,
    _decoded_preview_cache_path,
    _decoded_preview_video_cache_path,
    _ensure_cache_root,
    _safe_name,
    _write_json_atomic,
    MiniMaxH3MotionContextDiskJoin,
    MiniMaxH3MotionContextDiskFinalDecode,
    _cache_size_mb,
    _load_manifest_from_paths,
    _manifest_for_first,
    _truncate_chain,
    _export_live_candidate_preview,
    _decode_single_clip_to_blob,
    _load_segment_video,
    _load_segment_audio,
    _backup_chain_before_truncate,
    _decode_single_audio,
    _find_ffmpeg,
    _copy_blob_to_file,
    _despeckle_frames,
    _next_output_path,
    _comfy_media_item,
    _save_tail_latents,
    _restore_tail_latents,
    _save_tail_latents_to_disk,
    _load_tail_latents_from_disk,
    _delete_tail_latents_from_disk,
    _has_tail_latents_on_disk,
    _snapshot_chain,
    _snapshot_latest,
    _restore_latest_backup,
)
# v14.81: payload row-order guard. Wraps whatever MiniMaxH3.extra_conds
# currently owns the site (whichever third-party pack won it) and rebuilds
# cond_*_latents into PackedLayout's own order. Installed at import by the
# module itself; re-asserted below at execution time as a safety net.
# See the module docstring.
from .patch_h3_audio_row_order import (
    apply_patch as _apply_row_order_patch,
    is_applied as _row_order_patch_applied,
)

BUILD = "minimax-h3-extender-v14.393-acc8step+pdmd-sigma+refine-full-redraw-content-lock+frontend-guard+redraw-temporal-chunk+refine-sigma0"

# v14.307 (里程碑): 全部渲染管道统一口径 —— 时间分块关闭、空间分块保留。
# 逐档核对后修正 TaoMate HD 档的 `tiled_refine = _CHUNKED_DENOISE_ON`
# (默认环境变量下等于关掉空间分块, 与 v14.306 口径相反)。直播带货(全自动)
# 与一镜到底·2K双采保持 global 全上下文: 这两档的 global 是为规避空间分块
# 每块独立重构造成的横带叠加/重影, 属于"不需要空间分块"的档位。
#
# v14.306: 时间分块二采全线关闭（B站 BV1kN4G6rE89），但空间分块(tile)恢复。
# v14.305 把空间分块也关了，546,720 tokens 整段直跑在 24GB 卡上 OOM：
# QKV 激活(546k×3072×2B≈3.4GB×4)叠 DiT 驻留 12.9GB 已超卡容。
# 结论：本机无 sol_attn 原生核(comfy_kitchen 无)，torch 回退路径扛不住整段；
# 空间分块带 128~256px overlap 混合，不产生时间维接缝，保留。
# 需要恢复时间分块时设 BSAI_H3_CHUNKED_DENOISE=1 后重启 ComfyUI。
_CHUNKED_DENOISE_ON = str(os.environ.get("BSAI_H3_CHUNKED_DENOISE", "0")).strip().lower() in ("1", "true", "on")

# v14.240: 二采 workspace reserve 记忆。
# 自适应让位(见 Refine 二采 workspace 探针)一次就够了: 链式渲染 clip>=2 时
# 直接把上次实测的 reserve 用上, 省掉一次"全卸 -> 重驻留"(24GB 卡上约
# 30-60s 的纯开销)。键 = refine 倍率, 值 = reserve(GB)。
_REFINE_WS_RESERVE_HINT = {}


# v14.385 (2026-11-12): 一镜到底段中换场 —— 改成「主体自己走过去」, 撤掉整幅遮挡机制。
# 用户口径(针对 h3_clip_250_1_1794456674 12.25s 首片): 「场景变化不对, 一镜到底模式应该
# 是从上一个场景自然走进下一个场景」。旧文本(_one_shot_transit_mid_rule v14.378)写的是
# 「柱身迎面涨满整幅画幅、整块盖住镜头、主体藏在实心石面后面」, 出片表现为约 9s 整幅石面
# 盖镜 -> 跳进另一个空间, 观感就是一次转场(主体被挡掉再出现), 与一镜到底的口径冲突。
# 现改法: 门洞在画幅正前方推近 -> 两条竖门框向画幅左右分开 -> 主体跨过门槛石那一拍
# 地面由 start 的石缝换成 end 的第一道石缝、两侧换成 end 的墙与灯 -> 之后的每一拍
# end 的墙/柱/灯把 start 的逐拍换掉。全程主体完整在画幅中央、脚步连续、四角始终看得见
# 地面与两侧建筑。接缝换场常量 _OS_SPACE_TRANSIT_RULE 里「画幅被门墙挡住那一瞬」同源,
# 一并改成门框掠过 + 门外景物逐拍退出/门里景物逐拍进入。

# v14.386 (2026-11-12): DMAD 渲染管线步数改成 1 采 8 步 + 2 采 2 步。
# 旧值 4+2(DMAD 4-step 蒸馏 LoRA 的标称步数); 用户口径要求 8+2。渲染管道档
# ("DMAD-4步") 与旧速度档遗留值(speed_preset == "DMAD-4步") 两处同时改, 保持一致;
# shift 12/2 与强制 lcm 采样器(官方配方)不动。二采自 v14.389 起默认开重绘
# (内容锁 denoise≤0.20 + 结构相似度闸门), 这 2 步会真跑; 要回到纯超分设
# BSAI_H3_REFINE_NO_REDRAW=1。
# 下拉名保持 "DMAD 4-step"/"DMAD-4步" 不改 —— 改标签会让旧工作流的保存值变成
# "Value not in list", 与 v14.x 那次 combo 改名的坑同源。

# v14.387 (2026-11-12): 新增渲染管道档「ACC 8-step SelfLift Dual-Pass (8+4)」。
# 用户口径: 检查所有渲染管线有没有 ACC 这一档 —— 没有就加上, ACC 一采 8 步二采 4 步。
# 权重: models\loras\H3\H3加速\ACC\ 下两个 8 步加速 LoRA
#   MiniMax-H3-Ref2VA-Acc-8Step_comfyui_pdd-T8.safetensors  参考图 -> 音视频
#   MiniMax-H3-FL2VA-Acc-8Step_comfy.safetensors            首尾帧 / 文生
# 配方: 8 步一采(euler + simple, shift 12/3, denoise 1.0) + 4 步二采(denoise 0.45,
# tile 16 / overlap 128, latent x2.0 -> 2K); LoRA strength 1.0, 禁叠第二个加速 LoRA。
# 二采自 v14.389 起默认开重绘(内容锁: 0.45~0.55=真实起点 σ, 采样后过结构闸门), 这 4 步会真跑。
# 三处必须同时改才真的"看得到 + 选得到 + 生效": 后端 combo/EN2ZH/dispatch 分支,
# 前端 web/extender.js 的 cycle/cycleLabels/tints(同序号) 与 cycleAliases/ALIAS_CANON,
# 以及遗留兼容层 OPTIONS 白名单。顺手补了 tints 表原来少一条(38 vs 37)的既存缺陷。

# v14.388 (2026-11-12): PDMD 4 步档出片全是噪点 —— 根因是调度器给错了网格。
# 实机(12:41-13:27 六段全噪)配方: PDMD 4步 LoRA strength 1.0 + euler + **simple**
# + shift 12/3 + 4 步。simple 生成的是等间距 base 位置 u=linspace(1,0,5)
# = [1.0,0.75,0.5,0.25,0.0], 经 shift 12 映射成 σ=[1.0,0.973,0.9231,0.8,0.0];
# 而 DMD 系 4-NFE 学生的训练边界是 base_schedule [1.0,0.7,0.4,0.15,0.0]
# (5 边界 / 4 NFE, 与 PDMD 模型卡「4 步 + 底模发布版调度配置 shift 12/3」一致),
# 映射后 σ=[1.0,0.96552,0.88889,0.67925,0.0]。学生只在后者的噪声位置上有效,
# 喂等间距网格后末步还是从 σ=0.8 一次跳到 0 —— 结果就是整段纯噪声。
# 修法: 新增 scheduler="pdmd_manual"(训练边界经 model_sampling 的 shift 映射),
# PDMD 4 步档改用它; 加步数时只在训练曲线的相邻边界间插值, 少步只取子集。
# 同机对照佐证: 同样的底模/稀疏注意力栈, 8 步 + beta 的 turbo_4step 档出过完整
# 正片(2026-11-03), FastH3 4 步 + beta 档也出过正常 clip —— 只有 PDMD 这一档
# 被钉在 simple 上。tools\check_pdmd_sigma_schedule.py 离线复算两条曲线并断言。

# v14.384 (2026-11-12): 二采(Refine / 双采)一律「只超分放大, 绝不重绘」。
# 用户口径: 不管哪条渲染管线的二采(8+2 / 8+4 / FastOmini / taomate ...), 都
# 完全按照一采结果做超分放大, 不允许任何程度的去噪重采样。
# 实现方式不是把 denoise 调小(那还是会重绘、还会因为分块+权重换页卡死),
# 而是: 潜空间放大(3D upscaler / bislerp)完成的那一刻就用内部信号跳出整个
# 二采重绘段 —— 加噪、去噪、分块、驻留、workspace 探针、时间分块全部不执行,
# 交付的 latent 就是放大后的一采结果。VAE 解码照旧, 音频保持一采原声。
#
# v14.389 (2026-11-12): 本条被用户新口径反转 —— 「打开所有渲染管线的二采重绘,
# 但保证二采重绘必须和一采内容一样, 不得重绘成别的画面」。默认改为开重绘, 并加
# 内容锁(起点 σ 0.45~0.55, v14.393 起 denoise=真实起点噪声比例) + 结构相似度闸门(低于 0.85 丢弃二采回退纯超分)。
# v14.384 的整段跳过仍保留, 但只在 BSAI_H3_REFINE_NO_REDRAW=1(或
# BSAI_H3_REFINE_REDRAW=0)时生效。
class _FFRefineSkip(Exception):
    """内部信号: 二采已完成超分放大, 跳过其余全部重绘阶段(正常控制流, 非错误)。"""


# v14.389 (2026-11-12): 用户口径改成「所有渲染管线的二采都开重绘, 但二采内容必须
# 和一采一样, 不得重绘成别的画面」。所以默认从「一律不重绘」翻成「一律重绘」,
# 并加两道内容锁:
#   ① 噪声上限: 二采 denoise 一律夹到 _FF_REFINE_LOCK_DENOISE(默认 0.20) —— 二采
#      的底图就是一采放大后的 latent, denoise 越小保留的构图/动作越多; 各管线表里
#      0.45/0.5/0.55/1.0 这类值不再原样生效。
#   ② 结构闸门: 二采采样完成后, 把结果和一采放大后的 latent 做低通余弦相似度,
#      低于 _FF_REFINE_CONTENT_MIN(默认 0.85) 就判定「重绘成别的画面」, 整块丢弃、
#      回退到一采放大结果并告警 —— 宁可少一点细节, 也不交付另一幅画。
# 仍需要「绝不重绘」的旧行为时设 BSAI_H3_REFINE_NO_REDRAW=1(或 BSAI_H3_REFINE_REDRAW=0)。
#
# v14.393 (2026-11-12): 用户口径修正 —— 0.20 这个上限配上旧 sigma 算法其实没用:
# `_sigmas()` 是"拉长 total_steps 再取末 N 步"的老 img2img 近似, 而 H3 在 shift12
# 下 σ(t) 高端极平(t=0.5 时 σ 已经 0.923), 实测 denoise=0.45/0.50 steps=2 的真实
# 起点 σ = **0.9234**, denoise 夹到 0.20 也只有 0.6294 —— 都是"几乎整帧重生",
# 所以二采必然画成另一幅。改成两件事:
#   ① 二采 sigma 改走 _sigmas_exact(denoise = 真实起点噪声比例), 0.45/0.50/0.55
#      对应 σ0 = 0.4381 / 0.4859 / 0.5427, 即用户要的 "σ≈0.45~0.55 起步";
#   ② 上限改成 0.55(env BSAI_H3_REFINE_DENOISE_MAX) —— 挡住表里 1.0 那种全量重生;
#      同时下限 0.45(env BSAI_H3_REFINE_DENOISE_MIN, 设 0 关闭), 把表里 0.20/0.35/0.40
#      这类"按旧算法其实在 σ≈0.9 全量重生、按新算法又太轻"的档统一抬到真重绘档,
#      全表二采起点 σ 收敛在 0.438~0.543(即用户要的 σ≈0.45~0.55)。
_FF_REFINE_NO_REDRAW = (
    str(os.environ.get("BSAI_H3_REFINE_NO_REDRAW", "0")).strip().lower() in ("1", "true", "on")
    or str(os.environ.get("BSAI_H3_REFINE_REDRAW", "1")).strip().lower() in ("0", "false", "off")
)
try:
    _FF_REFINE_LOCK_DENOISE = float(os.environ.get("BSAI_H3_REFINE_DENOISE_MAX", "0.55"))
except Exception:
    _FF_REFINE_LOCK_DENOISE = 0.55
_FF_REFINE_LOCK_DENOISE = max(0.05, min(1.0, _FF_REFINE_LOCK_DENOISE))
try:
    _FF_REFINE_FLOOR_DENOISE = float(os.environ.get("BSAI_H3_REFINE_DENOISE_MIN", "0.45"))
except Exception:
    _FF_REFINE_FLOOR_DENOISE = 0.45
_FF_REFINE_FLOOR_DENOISE = max(0.0, min(_FF_REFINE_LOCK_DENOISE, _FF_REFINE_FLOOR_DENOISE))
# v14.393: 二采是否走"denoise = 真实起点 σ"的精确 sigma 映射(默认开)。
# 关掉可回到 v14.389 及以前的"拉长 total_steps 取末 N 步"旧近似(实测会从 σ≈0.92 起跑)。
_FF_REFINE_SIGMA_EXACT = str(os.environ.get("BSAI_H3_REFINE_SIGMA_EXACT", "1")).strip().lower() not in (
    "0", "false", "off")
try:
    _FF_REFINE_CONTENT_MIN = float(os.environ.get("BSAI_H3_REFINE_CONTENT_MIN", "0.85"))
except Exception:
    _FF_REFINE_CONTENT_MIN = 0.85
_FF_REFINE_CONTENT_MIN = max(0.0, min(1.0, _FF_REFINE_CONTENT_MIN))

# ── v14.79: 删除 v14.78 的 _patch_h3_audio_row_pad 死代码 ──
# 那段 "补零/截断 cond_audio_rows" 的 monkey-patch 从定义起就没有任何调用点,
# 从未生效过——所以 v14.78 报"已修复"的 shape mismatch 其实一次都没被拦住。
# 而且它本身是错的: 它照抄了一份过时的打包实现, 用 layout.img_pos/audio_pos
# 直接铺行, 既不填 text 段(那一段会留在 torch.empty 的未初始化内存里),
# 也不走 token_refiner, 宽度还取 max(video, audio) 再喂给 Linear。
# 真被调用的话不是修 crash, 而是静默出花屏 + NaN。
#
# 真正的成因在 payload 侧, 已就地根治 (无需在此兜底):
#   comfyui-h3-multishot/h3_avbank_probe.py  与
#   BSAI-ComfyUI-H3-Film-Factory/patch_motion_payload.py
# 两个 extra_conds 包装都只用 refs 重建 cond_audio_latents, 丢掉了
# PackedLayout 已经为 keyframe 音频预留的 cond_audio 段, 于是预留行数
# (1128) > 实到行数 (1054), 差 74 行 = 一段 37 步 motion-context 引导音频 x2。
# 两个包装都已改成 keyframe 音频 + ref 音频, 与 PackedLayout 的分段顺序一致。
#
# 不要再在这里加"补零"兜底: 行数不一致是上游语义错误, 补零只会把崩溃换成
# 静默错帧。正确的防线是让 cond_*_latents 与 layout 的预留严格同序同量。
FPS = 24
AUDIO_LATENT_FPS = 40

# v14.205: 多视图参考图纪律。ref2va 的多参生视频普遍输入 3/4 视图角色设定拼版，
# 模型会把拼版里其它视角的身体/手臂当成场景内容复制进画面（实测：主画面左侧
# 悬浮一条白袖手臂）。不裁剪参考图（多视图是通用用法），改为在 @图N 解析后
# 统一注入一次只取单一实体的约束，对单视图参考无副作用。
#
# v14.291 (2026-11-03): 措辞改为**纯正向**。
#   原句含 "其他视角 / 其他身体 / **半截肢体** / **不复制进画面** / 只出现一次 /
#   只保留两条手臂" —— H3 在 CFG=1.0 下**没有负向分支**，否定句与"半截肢体"
#   这类负面素材词会被当画面内容渲染，等于把要防的东西递给了模型。
#   正向版只描述"画面里应该是什么样"，不点名任何不要出现的东西。
# v14.324: 纪律文本里不再写 <Picture N> 编号。编号在每段参考图重映射时会被
# 整段丢弃(未进前 MAX_IMAGE_REFS 的标签直接替换为空串), 纪律句因此退化成
# 一串空分隔符(实测 "【参考图纪律】、、、、、、…"), 同时这些编号还会抢占
# 每段的参考图槽位预算。改用角色描述, 具体是哪一张由正文里的标签自己说明。
_REF_SHEET_RULE = (
    "【参考图纪律】画面人物的参考图通常是同一角色的多角度/多视图设定拼版；"
    "画面里出现的是这一位角色本人的外形、发型与服装，这一位角色在整部片里始终是同一个人，"
    "身体完整地出现在画面中，两条手臂自然地随动作摆动；拼版里的各个视角与局部细节"
    "统一体现为这一位角色本人的完整身影。\n"
)

# v14.221 服装锁定纪律：H3 文本指令优先于参考图，分镜正文一旦出现与参考图相悖的
# 服装词（如写了"针织开衫"而 @图1 是运动套装），模型会照文本画而丢弃参考图。
# 在 @图N 解析后统一注入本纪律，声明画面主体人物的真实穿着以 <Picture N> 为准，
# 正文服装描述仅作补充、不得改款改色改材质。对场景/道具/无人物参考无害。
#
# v14.291 (2026-11-03): 措辞改为**纯正向**。
#   原句含 "穿着**不可改变** / **禁止**另起新款、**改换颜色**或**更换**开衫/外套/裙装
#   等与参考图**不符**的服装" —— 这是一条"负面清单"，而 CFG=1.0 的 H3 会把清单里的
#   词当画面内容渲染。实测 clip3 在 8.458s 处**外套由深色突变为浅灰蓝**
#   (一采 latent 相位离群 1.37x, 像素域 5.81x)，与"改换颜色/更换外套"同型。
#   正向版只反复陈述"穿的就是参考图里那几件、款式与颜色始终一致"。
_OUTFIT_LOCK_RULE = (
    "【服装锁定纪律】画面主体人物（主播/主角）的实际穿着与画面人物参考图中"
    "该人物的真实服装完全一致：款式、颜色、材质、上下装搭配逐项复刻参考图，"
    "人物与参考图同框时穿的是同一件衣服，整部片里这套服装的款式与颜色始终保持一致。"
    "人物转身、侧身、走动、做手势或表情变化时，身上的上衣、外套、衬衫、下装与"
    "鞋子的款式和颜色保持不变，动作只改变肢体姿态，不改变身上穿的衣服。"
    "分镜正文中出现的衣着描述作为这套参考图服装的补充说明，画面里的上衣、外套与"
    "下装从头到尾都是参考图里的那几件。\n"
)

# v14.313 (2026-11-04): 物品/道具锁定纪律。
#   实测故障: 分镜写"双手捧起一支小瓶香薰@图4 / 这款香薰蜡烛@图4"，资产库 @图4 是
#   香薰蜡烛罐的参考图，成片却画成一支黑盖香水瓶——品牌字样被抄了，物品类别被
#   文本先验"小瓶香薰"顶掉。根因是插件此前只注入"参考图=角色多视图设定板"与
#   "服装锁定"两条纪律，@图4 被当成角色/服装参考，没有任何"这件物品必须照参考图
#   复刻"的指令。本纪律按角色绑定物品参考，并用正向措辞（H3 CFG=1.0 无
#   负向分支）声明类别、轮廓、结构、标签逐项一致。
_PROP_LOCK_RULE = (
    "【物品锁定纪律】画面中将要出现的物品（道具/产品）的参考图，"
    "画面里这件物品与参考图完全一致：物品类别、外形轮廓、高宽比例、颜色、材质与"
    "表面质感、盖子与罐身结构、标签位置与上面的文字逐项复刻参考图；"
    "分镜正文里对这件物品的称法（例如“香薰”“小瓶”“蜡烛”“产品”）指的就是参考图里"
    "这件物品本身，画面里拿在手上、摆在前景的就是它，外观与参考图一致。\n"
)

# v14.313: 场景锁定纪律。场景参考（如"场景@图3"、"背景为场景@图3"）此前被并进
# "角色设定板"纪律，模型容易把场景图当人物参考而弱化环境一致性。正向声明环境以
# 参考图为准，只改机位不改地点。
_SCENE_LOCK_RULE = (
    "【场景锁定纪律】画面环境（场景）的参考图，画面环境以该参考图的建筑、"
    "地形、地面材质、光源方向与整体色调为准，整段片子都在这个地点里拍摄，"
    "镜头只改变机位与景别，场景本身保持前后连续。\n"
)

# 参考图角色判定词表。中文习惯把名词写在标签前（"场景@图3"、"小瓶香薰@图4"），
# 所以只看标签前的窗口，避免把后一个标签的定语误判给前一个标签。
_PROP_CUES = (
    "香薰", "蜡烛", "香水", "精油", "香氛", "瓶", "罐", "盒", "包装", "礼盒",
    "产品", "商品", "道具", "物品", "口红", "面霜", "精华", "眼影", "粉饼",
    "手机", "耳机", "手表", "手链", "项链", "戒指", "包", "鞋", "帽", "杯",
    "壶", "零食", "饮料", "酒", "咖啡", "相机", "玩具", "花束", "灯", "伞",
    "扇", "海报", "样机",
)
_SCENE_CUES = (
    # 通用空间词
    "场景", "背景", "环境", "路口", "街道", "街口", "广场", "巷", "长廊",
    "林荫道", "公园", "校园", "办公室", "厨房", "客厅", "卧室", "车厢",
    "车站", "机场", "大楼", "天台", "屋顶", "堤岸", "河岸", "海边", "海面",
    # v14.325: 建筑类场景词。建筑巡游脚本的段首标题形如
    # "S2 雅典帕特农神庙·卫城山门@图4"、"S11 伦敦塔桥·桥头塔楼@图13"，
    # 上面这批通用空间词一个都不命中，这些场景图会被判成人物参考图，
    # 场景锁定纪律因此不注入。下列词只在"标签前 14 字"窗口内匹配，
    # 按 场所/塔桥/门廊庭院/阶台栈道/城防水岸 分组。
    "神庙", "神殿", "教堂", "大教堂", "清真寺", "寺庙", "佛寺", "修道院",
    "宫殿", "王宫", "故宫", "城堡", "堡垒", "遗址", "遗迹", "古迹",
    "大殿", "中殿", "侧殿", "礼拜堂", "拱厅", "拱龛", "基座",
    "塔", "塔楼", "钟楼", "鼓楼", "斜塔", "铁塔", "石塔", "金字塔",
    "桥", "大桥", "桥面", "桥头", "桥腹",
    "拱门", "山门", "门廊", "门洞", "券门", "城门", "拱廊", "连廊", "回廊",
    "廊道", "侧廊", "内庭", "中庭", "庭院", "露台",
    "石阶", "台阶", "阶梯", "平台", "栈道",
    "城墙", "城台", "城楼", "护城河", "筒子河", "河畔", "石栏", "栏道",
    "许愿池", "喷泉", "水池",
)

# 名词短语边界(角色判定只看紧贴标签的那一段): 空格、间隔号、括号、箭头、标点。
_ROLE_BOUNDARY_RE = re.compile(r"[ \t\n·・（）()【】\[\]，,、；;：:→>]")


def _classify_picture_roles(prompt):
    """按 <Picture N> 出现处的前置词判定该参考图的角色。

    返回 {slot: "person"|"prop"|"scene"}，同一编号取首次出现的判定。
    没有任何线索时按人物处理，保持既有角色纪律的默认行为。
    """
    roles = {}
    for m in re.finditer(r"<Picture\s+(\d+)>", str(prompt), re.IGNORECASE):
        slot = int(m.group(1))
        before = str(prompt)[max(0, m.start() - 14):m.start()]
        # v14.325: 只看紧贴标签的那一名词短语。14 字窗口里常常还留着上一拍的
        # 动作描述("…沿平台前行 主播<Picture 1>"), 整窗匹配会把人物判成场景,
        # 人物/服装纪律因此不注入。名词短语以 空格/间隔号/括号/箭头/标点 为界;
        # 标签紧跟标点时片段为空, 退回整窗(词在中止的上一个分句里)。
        frag = _ROLE_BOUNDARY_RE.split(before)[-1].strip()
        probe = frag or before
        role = "person"
        if any(c in probe for c in _PROP_CUES):
            role = "prop"
        elif any(c in probe for c in _SCENE_CUES):
            role = "scene"
        roles.setdefault(slot, role)
    return roles


def _strip_ref_rules(text):
    """剥掉参考/服装/物品/场景四条锁定纪律（一镜到底场景名与景别判定只看正文）。"""
    return re.sub(
        r"【(?:参考图|服装锁定|物品锁定|场景锁定)纪律】[^\n]*\n?",
        "", str(text),
    )


def _comfyui_temp_dir():
    """插件安装的 ComfyUI 根目录/temp——不依赖 folder_paths.get_temp_directory(),
    避免被其它插件 set_temp_directory() 改到系统 Temp(如 latentsync_*), 保证每台
    机器上预览/CLIP 临时文件都落在各自的 .\\ComfyUI\\temp。"""
    try:
        _root = Path(__file__).resolve().parents[2]
        _d = _root / "temp"
        _d.mkdir(parents=True, exist_ok=True)
        return _d
    except Exception:
        try:
            import folder_paths as _fp
            return _comfyui_temp_dir()
        except Exception:
            import tempfile as _tf
            return Path(_tf.gettempdir())


def _clip_output_dir():
    """v1.94: 正式 clip 成片(h3_clip_*.mp4)的持久目录——ComfyUI/output/bsai_clips/.
    ComfyUI 启动会清空 temp, 重启后 Premiere Pro 时间线上的 clip 路径全部失效
    (Video track V1 produced no output) 且无法挑选 clipN 复用. output 目录重启
    保留, 与链缓存 bsai_h3_chain_cache 同级持久化. 预览 _clippv_* 仍走 temp
    (v1.85 已支持从 manifest blob 重建)."""
    try:
        _root = Path(__file__).resolve().parents[2]
        _d = _root / "output" / "bsai_clips"
        _d.mkdir(parents=True, exist_ok=True)
        return _d
    except Exception:
        return _comfyui_temp_dir()


@contextlib.contextmanager
def _aimdo_disabled():
    """v1.78: H3 分块采样与 aimdo 内存图(malloc_graph)不兼容。
    4090 ComfyUI 0.35 跑后期 clip 二采时显存不足, malloc_graph_push 报
    'aimdo memory compile error' 断链。采样期间临时禁用 malloc_graph_begin/end,
    采样后恢复, 不影响其它节点/工作流。"""
    _mp = None
    try:
        import comfy.model_prefetch as _mp
        _ob, _oe = _mp.malloc_graph_begin, _mp.malloc_graph_end
        _mp.malloc_graph_begin = lambda device: None
        _mp.malloc_graph_end = lambda: None
    except Exception:
        _mp = None
    try:
        yield
    finally:
        if _mp is not None:
            try:
                _mp.malloc_graph_begin, _mp.malloc_graph_end = _ob, _oe
            except Exception:
                pass


def _commit_gb():
    """v14.264: 系统提交内存(commit = 页文件已用量)统计, 返回 (已用GB, 上限GB)。

    v14.264 崩溃溯源: 事件日志 Resource-Exhaustion-Detector(2004) 显示本进程
    提交内存一度涨到 150GB, 触顶后 PyTorch 某次分配返回空指针, c10.dll 直接
    解引用 -> 0xc0000005(0xc0000005@c10.dll+0x8b645, 三次崩溃偏移完全相同)。
    Windows 上 CUDA 缓存分配器不会归还地址空间, 长链渲染会持续膨胀。把 commit
    打进各重阶段日志, 才能定位是谁把它顶上去的。
    """
    try:
        import ctypes

        class _MS(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        _m = _MS()
        _m.dwLength = ctypes.sizeof(_m)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(_m)):
            return ((_m.ullTotalPageFile - _m.ullAvailPageFile) / 1024.0 ** 3,
                    _m.ullTotalPageFile / 1024.0 ** 3)
    except Exception:
        pass
    return 0.0, 0.0


def _release_dynamic_vram(tag=""):
    """v1.81 (2026-09-15 fix #11): 4090 DynamicVRAM 二采前 staged 池残留致 CUDA abort。

    现象: 4090 (ComfyUI 0.35 + DynamicVRAM 流式) 一采完成后, 模型权重仍留在
    prefetch/vbar staged 池 (21833MB Staged), ComfyUI 标准 unload_all_models()
    对 dynamic 模型返回 "0 models unloaded" 无效; 二采前 device_free 只剩
    ~1GB, 分块采样触发 21.8GB 重载 + workspace 分配 -> CUDA 驱动级
    "Fatal Python error: Aborted" (线程 dump 在 bsai_h3_spatial_tiles.py)。
    修复: 调用 comfy.model_prefetch.cleanup_prefetch_queues() (vbar_unpin
    释放 staged 权重) + cleanup_malloc_graph() + unload_all_models() +
    empty_cache, 让二采前显存回到 20GB+。对非 DynamicVRAM (5090) 为 no-op。
    """
    import torch as _t81
    try:
        import comfy.model_prefetch as _mp81
        for _fn81 in ("cleanup_prefetch_queues", "cleanup_malloc_graph"):
            _f81 = getattr(_mp81, _fn81, None)
            if _f81 is not None:
                try:
                    _f81()
                except Exception:
                    pass
    except Exception:
        pass
    try:
        import comfy.model_management as _mm81
        try:
            # v2.120b: unload_all_models() 会对注册中的 dynamic 量化 DiT 走 model_unload->
            # detach->unpatch_model->self.model.to(cpu), 量化块 GPU→CPU 拷贝触发 comfy_kitchen
            # _handle_to 原生 access violation(round3 崩溃链)。free_memory(..., for_dynamic=True)
            # 对动态模型设 memory_to_free=0 跳过, 只卸载非量化模型, 动态模型交 DynamicVRAM 调度。
            _mm81.free_memory(1e30, _mm81.get_torch_device(), for_dynamic=True)
        except Exception:
            pass
    except Exception:
        pass
    try:
        _t81.cuda.empty_cache()
        _t81.cuda.synchronize()
    except Exception:
        pass
    try:
        _f81, _t81b = _t81.cuda.mem_get_info()
        print(f"[H3 Extender] v1.81 显存释放[{tag}]: "
              f"free={_f81/1024**3:.2f}GB/{_t81b/1024**3:.2f}GB")
    except Exception:
        pass


def _release_text_encoder(clip, tag=""):
    """v14.214 (2026-10-26): 采样前强制释放文本编码器(TE)在 GPU 上的权重。

    实测根因(本机 RTX 4090 24GB / 一镜到底 19 段, 2026-10-26 13:32 那次):
      · 第 1 段采样前 free=22.27GB → DiT 20.6GB 走 DynamicVRAM 流式, 8 步跑通;
      · 第 2 段采样前 free 只剩 15.57GB —— TE(qwen3vl_32b_minimax_h3_nvfp4_awq,
        量化权重 14.6GB) 仍以 "loaded partially; 8905.26 MB loaded" 常驻显存,
        可用余量 15.6-4.0=11.6GB 装不下 DiT, 第一次 int8_linear 的 torch.empty
        权重块分配失败 → "CUDA error: out of memory"。

    为什么现有两条释放逻辑都漏了 TE:
      · extender.py 的 TE 释放块对带 comfy_kitchen 量化权重的模型直接 continue
        (_mp_has_ck_quant_weights) —— 实测 TE 正是 comfy_kitchen 量化
        (patcher=ModelPatcher / MiniMaxH3TEModel_, is_dynamic()=False);
      · _release_dynamic_vram() 的 free_memory(..., for_dynamic=True) 只能扫到
        ComfyUI current_loaded_models 里的模型, 而 v1.53 块早已把 clip.patcher
        从该表摘除, 下一段重新加载后并不保证能被扫到。

    这里按"身份"(clip.patcher)释放而不是扫注册表, 不依赖 ComfyUI 的卸载分支。
    实测(复现"部分加载"状态: 占用 12GB 后 TE 载入 8522MB):
      te.partially_unload(offload_device, 1e32) → 释放 8522MB, loaded_size 归零, 进程存活
      te.detach(True)                               → 释放 8522MB, loaded_size 归零, 进程存活
    下一段需要 TE 时 ComfyUI 会自动重新加载(CLIP.load_model → load_models_gpu),
    不影响文本编码, 代价约 6s。
    """
    try:
        import torch as _t214
    except Exception:
        return
    te = getattr(clip, "patcher", None)
    if te is None:
        return
    try:
        before = int(te.loaded_size())
    except Exception:
        before = 0
    if before <= 0:
        return
    try:
        te.partially_unload(te.offload_device, 1e32)
    except Exception:
        try:
            te.detach(True)
        except Exception as _te_err:
            print(f"[H3 Extender] v14.214 文本编码器释放失败(忽略, 不影响采样): {_te_err}")
    try:
        after = int(te.loaded_size())
    except Exception:
        after = 0
    try:
        import comfy.model_management as _cmm214
        for _lm in list(_cmm214.current_loaded_models):
            try:
                if getattr(_lm, "model", None) is te:
                    _cmm214.current_loaded_models.remove(_lm)
            except Exception:
                pass
    except Exception:
        pass
    try:
        import gc as _gc214
        _gc214.collect()
        _t214.cuda.synchronize()
        _t214.cuda.empty_cache()
        _t214.cuda.ipc_collect()
    except Exception:
        pass
    try:
        _f214, _tt214 = _t214.cuda.mem_get_info()
        print(f"[H3 Extender] v14.214 文本编码器显存释放[{tag}]: "
              f"TE {before / 1024 ** 2:.0f}MB -> {after / 1024 ** 2:.0f}MB, "
              f"GPU free={_f214 / 1024 ** 3:.2f}GB/{_tt214 / 1024 ** 3:.2f}GB")
    except Exception:
        pass


def _ff_unregister_model(model, label=""):
    """v14.175 (2026-10-23): 从 current_loaded_models 摘除指定模型的 LoadedModel。

    ComfyUI 没有公开 API 做这件事:
      - unload_model()     : 不存在 (silent AttributeError, 全局多处误用)
      - unload_model_and_clones(): 会连带 clone_base 一起卸, dynamic 量化 DiT
                                  会触发 unpatch -> .to(cpu) -> access violation
      - free_memory(..., for_dynamic=True): 对 dynamic 模型 memory_to_free=0,
                                  跳过不卸载

    所以手工从 current_loaded_models 里 pop LoadedModel + GC + soft_empty_cache,
    让后续 load_models_gpu 按新 reserve 预算重新登记。DynamicVRAM 的 staged 权重
    在 RAM, 卸载后 forward 会按需自动搬运, 不会丢失。

    返回: 摘除的 LoadedModel 数量 (int)
    """
    import gc as _gc_ur
    _removed = 0
    try:
        import comfy.model_management as _mm_ur
        _clm = getattr(_mm_ur, "current_loaded_models", None)
        if _clm is not None:
            for _i in range(len(_clm) - 1, -1, -1):
                if getattr(_clm[_i], "model", None) is model:
                    _clm.pop(_i)
                    _removed += 1
        _gc_ur.collect()
        try:
            _mm_ur.soft_empty_cache(force=True)
        except Exception:
            pass
    except Exception:
        pass
    if _removed > 0 or label:
        print(f"[H3 Extender] v14.175 _unregister{label}: 摘除 {_removed} 个 LoadedModel")
    return _removed


def _decode_single_clip_preview(owner, clip_index, vae, audio_vae, fps, ffmpeg=None, async_encode=False, lip_audio_segment=None):
    """Decode a single cached clip to MP4 and store as blob for frontend preview.
    v1.70: async_encode=True 时 encode 段在后台线程执行, 返回
    {"async": True, "done_event": threading.Event}.
    lip_audio_segment: 对口型模式下该 CLIP 对应的歌曲片段，纯歌曲输出(模型音频丢弃)。"""
    return _decode_single_clip_to_blob(
        owner_id=owner,
        clip_index=clip_index,
        vae=vae,
        audio_vae=audio_vae,
        fps=fps,
        ffmpeg=ffmpeg,
        async_encode=async_encode,
        lip_audio_segment=lip_audio_segment,
    )


# ---------------------------------------------------------------------------
# IMAGE + AUDIO per-CLIP streaming outputs (BSAI H3 Film Factory v14.70)
#
# Every clip is decoded to an IMAGE tensor [T,H,W,C] (float32, 0..1) plus an
# AUDIO dict as soon as it finishes sampling, pushed to the frontend over
# WebSocket (h3_extender_clip_av) and accumulated into the final IMAGE/AUDIO
# output ports.  This lets downstream upscale nodes (e.g. BSAI-H3-upscale-4K)
# consume the film as soon as the run returns, without a second VAE decode.
# ---------------------------------------------------------------------------


def _read_frames_from_mp4(path, ffmpeg, total_frames, trim, width, height):
    """v1.67: 从已编码 MP4 blob 读帧(preview decode 产物), 返回 [T,H,W,C] float 0-1
    cpu tensor. 替代 _decode_clip_to_av 里重复的 VAE decode(2X 时每段省 ~30-60s).
    MP4 已按 trim 裁剪, 帧数以实际 raw 数据为准(编码器可能微调)."""
    import subprocess as _sp
    import numpy as _np
    n = max(0, int(total_frames) - int(trim))
    if n == 0:
        return None
    try:
        _p = _sp.run(
            [str(ffmpeg), "-y", "-i", str(path),
             "-f", "rawvideo", "-pix_fmt", "rgb24",
             "-s:v", f"{int(width)}x{int(height)}", "-"],
            stdout=_sp.PIPE, stderr=_sp.DEVNULL, timeout=600,
        )
    except Exception as _e:
        print(f"[H3 Extender] MP4 读帧失败: {_e}")
        return None
    raw = _p.stdout
    one = int(width) * int(height) * 3
    actual = len(raw) // one
    if actual == 0:
        return None
    arr = _np.frombuffer(raw[:actual * one], dtype=_np.uint8).reshape(
        actual, int(height), int(width), 3)
    return torch.from_numpy(arr.copy()).float().div_(255.0)


# ===========================================================================
# v14.335 (2026-11-08) 视频人物替换 —— Video Recast (H3 V2V character swap)
#
# 用法（与资产库对齐，用户口径）：
#   1) 资产库里放"被替换的源视频" → @视频N；放"替换成的人物参考图" → @图N（可多张，多人）；
#   2) 渲染管道选「视频替换 (V2V 人物替换)」，分镜脚本里写 @视频N + @图N 的替换指令；
#   3) 电影工厂把源视频按 H3 Recast 的「单镜头 ≤15s」硬约束自动切成 15s/段：
#      45s 源视频 = 3 段，每段独立执行人物替换，段间绝不做 motion context 续链，
#      保证每段画面都各自由源视频画面驱动，不出现"从上段生成画面漂移"；
#   4) 源原声整段锁进 AV latent 的音频行（noise_mask=0），采样器不会改写它 →
#      替换后人物口型/对白/环境声与原视频逐帧对齐（不需要另接 lip_audio）。
#
# 技术链路（与 ComfyUI-H3-Multishot 的 H3 Retake 同源，本机已核对）：
#   源片段 [start, start+dur) → ffmpeg 抽 24fps、等比放大+居中裁切到画布 W×H、
#   帧数对齐 H3 的 17k+5 网格 → video_vae.encode() → [1,24,T,h/16,w/16]
#   源原声 → 重采样到 audio_vae 采样率、裁/补到 round(dur*40) 行 →
#   audio_vae.encode() → [1,32,2,Ta]
#   latent = NestedTensor(video, audio)；noise_mask = (全 1 视频 / 全 0 音频)
#   → 一采 denoise≈0.65 半重绘：保留源片运动/构图/镜头，只把人物身份换成参考图。
#
# 只在本档生效（_rp_mode == "视频替换 (V2V 人物替换)"），其它档一律不受影响。
# ===========================================================================
_RECAST_VIDEO_TAG_RE = re.compile(r"<\s*Video\s*([0-9]+)\s*>", re.IGNORECASE)
_RECAST_SEG_SECONDS = 15.0          # H3 Recast 单镜头上限 15s（官方/社区一致）
_RECAST_MIN_SEG_SECONDS = 1.0
_RECAST_MAX_CLIPS = 120
# v14.337 人物区域掩码（只重绘人、背景锁死源像素）；可用环境变量关掉退回旧行为
_RECAST_MASK_ON = str(os.environ.get("BSAI_H3_RECAST_SUBJECT_MASK", "1")).strip().lower() \
    not in ("0", "false", "off", "no")
_RECAST_MASK_DILATE = max(0, int(os.environ.get("BSAI_H3_RECAST_MASK_DILATE", "13") or 13))
_RECAST_MASK_FEATHER = max(0, int(os.environ.get("BSAI_H3_RECAST_MASK_FEATHER", "10") or 10))
_RECAST_MASK_TIMEOUT = float(os.environ.get("BSAI_H3_RECAST_MASK_TIMEOUT", "120") or 120)
# 代表帧上限：H3 VAE 的 latent 行数远多于 17k+5 直觉（362 帧 → 107 行），逐行打 NPU 太慢；
# 15s 内 24 个采样点（≈0.6s/点）足够跟上人物位移，其余行取最近的采样帧。
_RECAST_MASK_SAMPLES = max(1, int(os.environ.get("BSAI_H3_RECAST_MASK_SAMPLES", "24") or 24))
_RECAST_DISCIPLINE = (
    "【视频人物替换纪律】本段执行“视频人物替换（Recast）”：输入视频是本段唯一的画面、场景与运动来源。"
    "把原视频中的人物换成参考图里的人物，除此之外画面的一切都不许动。"
    "① 场景纪律：人物之外的每一处像素——背景、室外街景/室内环境、建筑与墙面、天空、地面、家具、陈设、"
    "招牌与文字、光源位置与色温、明暗与噪点——必须与原视频完全一致，不得改换场地、不得从室外变成室内，"
    "也不得新增或删除任何背景物体。"
    "② 人物纪律：被替换人物的脸型、五官、神情、肤色、发型（发色/发长/刘海/发饰）、体型，"
    "以及整套服装、鞋、袜、帽、手套、项链等配饰，必须与参考图完全一致（颜色、款式、材质、长度都要一致）；"
    "原视频人物身上的服装与配饰一律不得保留、不得残留残片或改色沿用。"
    "③ 参考图为多视角角色设定图时，取其中最清晰的正视图/半身近景决定脸与服装，"
    "不得把多个视角、多个分身或设定图本身拼进画面。"
    "④ 动作纪律：位置、动作幅度、手势、视线、表情与口型必须逐帧跟随原视频，不得重新表演、"
    "不得改变动作轨迹、不得换机位或新增剪辑点。"
    "⑤ 未被指定替换的人物、背景与物体保持不变；画面内不得出现参考图本身、分屏、色卡、拼图、文字、水印或额外分身。"
)


def _recast_strip_video_tags(text: str) -> str:
    """Recast 档把 <Video N> 从提示词里摘掉。

    视频已作为 V2V latent 源（画面 + 原声）进入采样，保留 <Video N> 会让 H3 再把它
    当成 ref2v 参考视频二次注入，与 V2V 初始化互相打架（实测会重演一遍源片动作）。
    """
    if not text:
        return text
    cleaned = _RECAST_VIDEO_TAG_RE.sub("原视频", text)
    return cleaned


def _recast_prompt(text: str) -> str:
    """本段最终送入 TE 的 Recast 提示词 = 纪律块 + 用户指令（去掉 <Video N>）。"""
    body = _recast_strip_video_tags(str(text or "")).strip()
    return _RECAST_DISCIPLINE + "\n" + body if body else _RECAST_DISCIPLINE


def _recast_find_video_asset(asset_library, tag_num: int):
    """按 @视频N 取资产库视频条目（先按 index 匹配，再退回位置）。"""
    videos = []
    if isinstance(asset_library, dict):
        videos = list(asset_library.get("videos") or [])
    elif isinstance(asset_library, (list, tuple)):
        videos = list(asset_library)
    for item in videos:
        if isinstance(item, dict) and item.get("index") == tag_num:
            return item
    idx = int(tag_num) - 1
    if 0 <= idx < len(videos):
        return videos[idx]
    return None


_IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
_VID_EXTS = (".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv")
_AUD_EXTS = (".wav", ".mp3", ".flac", ".ogg", ".aac", ".m4a")


def _rebuild_asset_library_from_disk():
    """节点清单 widget 为空时的磁盘兜底：回读 input/bsai_assets/asset_order.json，
    清单缺项再扫目录，按 images/videos/audios 顺序重建资产库 dict。

    背景：BSAI_AssetLibraryInput 只把界面勾选的文件名写进三个 widget；工作流另存、
    跨机分发或清单被清空后，运行时资产库是 0 图 0 视频，@图N/@视频N 全部解析失败，
    参考图（脸/服装/鞋帽）与源视频都进不了 ref2va / V2V 链路，成片人物自然与参考图
    完全不同。这里在后端补一层，保证磁盘上已落盘的资产仍能被命中。
    """
    try:
        input_dir = folder_paths.get_input_directory()
        base = os.path.join(input_dir, "bsai_assets")
        manifest_path = os.path.join(base, "asset_order.json")
        manifest = {"images": [], "videos": [], "audios": []}
        if os.path.isfile(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest.update(json.load(f) or {})
            except Exception:
                manifest = {"images": [], "videos": [], "audios": []}

        def _entries(sec, exts):
            d = os.path.join(base, sec)
            if not os.path.isdir(d):
                return []
            on_disk = {x.lower(): x for x in os.listdir(d)
                       if os.path.isfile(os.path.join(d, x)) and x.lower().endswith(exts)}
            ordered = list(manifest.get(sec) or [])
            # 严格按清单重建：清单缺记录的类型留空，不把目录里的历史素材
            # （旧视频/旧音频）一并扫进本次替换任务。
            names = [on_disk[x.lower()] for x in ordered if x.lower() in on_disk]
            return [{"path": os.path.join(d, n), "name": n, "index": i + 1}
                    for i, n in enumerate(names)]

        return {
            "images": _entries("images", _IMG_EXTS),
            "videos": _entries("videos", _VID_EXTS),
            "audios": _entries("audios", _AUD_EXTS),
        }
    except Exception as exc:
        print(f"[BSAI AssetLibrary] 磁盘兜底重建失败: {exc}")
        return None


def _asset_library_is_empty(asset_library):
    if not isinstance(asset_library, dict):
        return True
    return not (asset_library.get("images") or asset_library.get("videos")
                or asset_library.get("audios"))


def _recast_probe_path(ffmpeg=None) -> str:
    """ffprobe 与 ffmpeg 同目录（整合包自带），找不到就退回 PATH 里的 ffprobe。"""
    try:
        if ffmpeg:
            cand = os.path.join(os.path.dirname(str(ffmpeg)), "ffprobe.exe")
            if os.path.isfile(cand):
                return cand
            cand = os.path.join(os.path.dirname(str(ffmpeg)), "ffprobe")
            if os.path.isfile(cand):
                return cand
    except Exception:
        pass
    return "ffprobe"


def _recast_probe_duration(path: str, ffmpeg=None):
    """源视频总时长（秒）。ffprobe 优先，ffmpeg -i 解析兜底；都失败返回 None。"""
    import subprocess as _sp
    try:
        p = _sp.run(
            [_recast_probe_path(ffmpeg), "-v", "error", "-show_entries",
             "format=duration", "-of", "default=nw=1:nk=1", str(path)],
            stdout=_sp.PIPE, stderr=_sp.PIPE, timeout=60,
        )
        if int(p.returncode) == 0:
            txt = (p.stdout or b"").decode("utf-8", "ignore").strip().splitlines()
            for line in txt:
                try:
                    d = float(line.strip())
                    if d > 0.05:
                        return d
                except Exception:
                    continue
    except Exception:
        pass
    if ffmpeg:
        try:
            p = _sp.run([str(ffmpeg), "-hide_banner", "-i", str(path)],
                        stdout=_sp.PIPE, stderr=_sp.PIPE, timeout=90)
            err = (p.stderr or b"").decode("utf-8", "ignore")
            m = re.search(r"Duration:\s*([0-9]+):([0-9]{2}):([0-9]{2}(?:\.[0-9]+)?)", err)
            if m:
                return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        except Exception:
            pass
    return None


def _recast_read_segment_frames(path, start_sec, dur_sec, width, height, frame_count,
                                ffmpeg=None, fps=None):
    """把源视频 [start, start+dur) 抽成恰好 frame_count 帧，等比放大后居中裁切到 W×H。

    返回 [T,H,W,C] float32 (0..1, CPU)；失败返回 None。
    精确 seek（-ss 放在 -i 之后）保证每段起点严格对齐源视频时间轴，
    段与段之间不会因为关键帧跳转而重叠/漏帧。
    """
    import subprocess as _sp
    import numpy as _np2
    if not ffmpeg:
        return None
    n = int(frame_count)
    if n <= 0:
        return None
    w, h = int(width), int(height)
    vf = (f"fps={int(fps or FPS)},"
          f"scale={w}:{h}:force_original_aspect_ratio=increase,"
          f"crop={w}:{h},setsar=1")
    cmd = [str(ffmpeg), "-v", "error", "-i", str(path),
           "-ss", f"{max(0.0, float(start_sec)):.3f}", "-t", f"{max(0.05, float(dur_sec)):.3f}",
           "-vf", vf, "-frames:v", str(n), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
    try:
        p = _sp.run(cmd, stdout=_sp.PIPE, stderr=_sp.PIPE, timeout=600)
    except Exception as exc:
        print(f"[H3 Recast] 源视频抽帧失败: {exc}")
        return None
    raw = p.stdout or b""
    one = w * h * 3
    got = len(raw) // one
    if got <= 0:
        print(f"[H3 Recast] 源视频抽帧为空 (start={start_sec:.2f}s dur={dur_sec:.2f}s): "
              f"{(p.stderr or b'')[:200]}")
        return None
    arr = _np2.frombuffer(raw[:got * one], dtype=_np2.uint8).reshape(got, h, w, 3)
    frames = torch.from_numpy(arr.copy()).float().div_(255.0)
    if got < n:
        # 该段比预期短（源视频尾部不足 / 抽帧取整）：冻结末帧补满，避免 latent 时间轴错位。
        pad = frames[-1:].repeat(n - got, 1, 1, 1)
        frames = torch.cat([frames, pad], dim=0)
        print(f"[H3 Recast] 源片段只抽到 {got}/{n} 帧，已用末帧冻结补满")
    elif got > n:
        frames = frames[:n]
    return frames.contiguous()


def _recast_read_segment_audio(path, start_sec, dur_sec, sample_rate, total_samples,
                               ffmpeg=None):
    """抽源片段原声 → [1, 2, total_samples] float32 (CPU)。无音轨/失败返回 None。"""
    import subprocess as _sp
    import numpy as _np3
    if not ffmpeg:
        return None
    sr = int(sample_rate or 32000)
    want = int(total_samples)
    if want <= 0:
        return None
    cmd = [str(ffmpeg), "-v", "error", "-i", str(path),
           "-ss", f"{max(0.0, float(start_sec)):.3f}", "-t", f"{max(0.05, float(dur_sec)):.3f}",
           "-vn", "-ac", "2", "-ar", str(sr), "-acodec", "pcm_f32le",
           "-f", "f32le", "pipe:1"]
    try:
        p = _sp.run(cmd, stdout=_sp.PIPE, stderr=_sp.PIPE, timeout=600)
    except Exception as exc:
        print(f"[H3 Recast] 源视频抽音失败(将改为让模型重生成音频): {exc}")
        return None
    raw = p.stdout or b""
    if len(raw) < 8:
        print("[H3 Recast] 源视频没有可用音轨(将改为让模型重生成音频)")
        return None
    smp = _np3.frombuffer(raw[: (len(raw) // 4) * 4], dtype=_np3.float32)
    ch = 2
    frames = smp.reshape(-1, ch).T  # [2, L]
    wav = torch.from_numpy(frames.copy()).unsqueeze(0)  # [1, 2, L]
    cur = int(wav.shape[-1])
    if cur < want:
        wav = torch.nn.functional.pad(wav, (0, want - cur))
    elif cur > want:
        wav = wav[..., :want]
    return wav.contiguous()


def _recast_npu_base_url() -> str:
    """本机 NPU 服务（挂在 ComfyUI 路由上）：优先读 PromptServer 端口，退回 8181。"""
    port = os.environ.get("BSAI_H3_RECAST_MASK_PORT") or ""
    if port:
        return "http://127.0.0.1:%s" % str(port).strip()
    try:
        import server as _srv_seg
        _ps_seg = getattr(_srv_seg.PromptServer, "instance", None)
        _p = int(getattr(_ps_seg, "port", 8181) or 8181)
    except Exception:
        _p = 8181
    return "http://127.0.0.1:%d" % _p


def _recast_npu_post(url: str, payload: dict, timeout=None):
    """POST JSON（NPU 服务只认 {"image": <base64>} 这种 JSON body）。"""
    import json as _json_seg
    import urllib.request as _ureq
    body = _json_seg.dumps(payload).encode("utf-8")
    req = _ureq.Request(url, data=body, headers={"Content-Type": "application/json"})
    with _ureq.urlopen(req, timeout=timeout or _RECAST_MASK_TIMEOUT) as _r:
        return _json_seg.loads(_r.read().decode("utf-8", "ignore"))


def _recast_decode_alpha_b64(s, height, width):
    """NPU 返回的 alpha 是 "data:image/png;base64,..." 的 8bit 灰度 PNG。"""
    import base64 as _b64_seg
    import io as _io_seg
    from PIL import Image as _PILSeg
    if not s:
        return None
    if s.startswith("data:"):
        s = s.split(",", 1)[1]
    s += "=" * (-len(s) % 4)
    _img = _PILSeg.open(_io_seg.BytesIO(_b64_seg.b64decode(s))).convert("L")
    _arr = np.asarray(_img, dtype=np.float32) / 255.0
    if _arr.shape[:2] != (height, width):
        import cv2 as _cv2s
        _arr = _cv2s.resize(_arr, (width, height), interpolation=_cv2s.INTER_LINEAR)
    return _arr


def _recast_frame_person_mask(rgb_u8, base_url):
    """单帧人像掩码 0..1（=1 允许重绘，=0 保持源像素）。

    RMBG-1.4 在夜景/虚化背景上会漏出大片背景亮斑，GrabCut 在特写（人物占满画面）时
    又会吃掉一部分人物；两者取并集并把结果限制在 YOLO 人体框内，既不会漏掉人物的
    衣服鞋帽（否则会出现"旧衣服残片"），也不会把整幅背景放开重绘。
    返回 None 表示这一帧分割失败。
    """
    import base64 as _b64f
    import io as _iof
    import cv2 as _cv2f
    from PIL import Image as _PILf

    h, w = int(rgb_u8.shape[0]), int(rgb_u8.shape[1])
    try:
        _pil = _PILf.fromarray(rgb_u8)
        _buf = _iof.BytesIO()
        _pil.save(_buf, format="JPEG", quality=95)
        _b64 = _b64f.b64encode(_buf.getvalue()).decode()
    except Exception:
        return None

    poses = []
    try:
        _pose = _recast_npu_post(base_url + "/detect_pose", {"image": _b64})
        poses = [p for p in (_pose.get("poses") or [])
                 if float(p.get("score", 0) or 0) > 0.3]
    except Exception:
        poses = []
    try:
        _seg = _recast_npu_post(base_url + "/segment_foreground", {"image": _b64})
        alpha = _recast_decode_alpha_b64(_seg.get("alpha", ""), h, w)
    except Exception:
        alpha = None
    if not poses and alpha is None:
        return None

    bgr = _cv2f.cvtColor(np.ascontiguousarray(rgb_u8), _cv2f.COLOR_RGB2BGR)
    mask = np.zeros((h, w), np.uint8)
    box = np.ones((h, w), np.uint8)
    gc_fg = np.zeros((h, w), np.uint8)
    bw = bh = 0
    if poses:
        x1, y1, x2, y2 = [int(round(float(v))) for v in poses[0]["bbox"][:4]]
        x1, y1 = max(0, min(w - 1, x1)), max(0, min(h - 1, y1))
        x2, y2 = max(x1 + 1, min(w, x2)), max(y1 + 1, min(h, y2))
        bw, bh = x2 - x1, y2 - y1
        sx, sy = int((x2 - x1) * 0.04), int((y2 - y1) * 0.04)
        rx1, ry1 = x1 + sx, y1 + sy
        rx2, ry2 = x2 - sx, y2 - sy
        if rx2 - rx1 > 8 and ry2 - ry1 > 8:
            try:
                gc = np.zeros((h, w), np.uint8)
                _bgd = np.zeros((1, 65), np.float64)
                _fgd = np.zeros((1, 65), np.float64)
                _cv2f.grabCut(bgr, gc, (rx1, ry1, rx2 - rx1, ry2 - ry1),
                              _bgd, _fgd, 5, _cv2f.GC_INIT_WITH_RECT)
                _mgc = np.where((gc == _cv2f.GC_FGD) | (gc == _cv2f.GC_PR_FGD), 1, 0)
                gc_fg = _mgc.astype(np.uint8)
                mask = np.maximum(mask, gc_fg)
            except Exception:
                gc_fg = np.zeros((h, w), np.uint8)
        box = np.zeros((h, w), np.uint8)
        ex, ey = int((x2 - x1) * 0.07), int((y2 - y1) * 0.06)
        box[max(0, y1 - ey):min(h, y2 + ey), max(0, x1 - ex):min(w, x2 + ex)] = 1
    if alpha is not None:
        a_bin = (alpha > 0.5).astype(np.uint8)
        # v14.338: RMBG 在夜景/虚化背景上会把大块亮区当"前景"（本机实测人区一度达 62%，
        # 等于人框内的街道也放开重绘）。所以把 alpha 限制在 GrabCut 人体区的邻域带内：
        # 衣服/鞋帽/手套紧贴人体，一定落在带内；离人很远的亮斑则被剔除。
        if poses and int(gc_fg.sum()) > (h * w) * 0.005:
            rad = int(round(0.10 * max(bw, bh)))
            rad = max(9, min(61, rad if rad % 2 == 1 else rad + 1))
            band = _cv2f.dilate(
                gc_fg, _cv2f.getStructuringElement(_cv2f.MORPH_ELLIPSE, (rad, rad)))
            a_bin = np.logical_and(a_bin, band).astype(np.uint8)
        mask = np.maximum(mask, a_bin)
    mask = mask * box

    # 去掉碎块（分镜里第二个人/误检），保留主要人像
    n_lab, lab, stats, _ = _cv2f.connectedComponentsWithStats(mask, 8)
    keep = np.zeros_like(mask)
    for k in range(1, n_lab):
        if int(stats[k][4]) > (h * w) * 0.015:
            keep = np.maximum(keep, (lab == k).astype(np.uint8))
    if int(keep.sum()) < (h * w) * 0.02:
        return None
    keep = _cv2f.morphologyEx(keep, _cv2f.MORPH_CLOSE,
                              np.ones((21, 21), np.uint8))
    keep = _cv2f.morphologyEx(keep, _cv2f.MORPH_OPEN,
                              np.ones((5, 5), np.uint8))
    if _RECAST_MASK_DILATE > 0:
        keep = _cv2f.dilate(
            keep, _cv2f.getStructuringElement(
                _cv2f.MORPH_ELLIPSE, (_RECAST_MASK_DILATE, _RECAST_MASK_DILATE)))
    soft = keep.astype(np.float32)
    if _RECAST_MASK_FEATHER > 0:
        soft = _cv2f.GaussianBlur(soft, (0, 0), float(_RECAST_MASK_FEATHER))
    return np.clip(soft, 0.0, 1.0)


def _recast_subject_mask(frames, t_lat, h_lat, w_lat, log=print):
    """把抽出来的源帧做成人像掩码，并采样到 latent 网格 [1,1,T,h,w]。

    frames 是 _recast_read_segment_frames 的返回值，即 **torch 张量** [T,H,W,C] 0..1（v14.338
    起显式转 numpy，v14.337 直接按 numpy 用会在 np.clip 后被 torch 的 __array_priority__
    接管、.astype() 不存在而整段退回全画幅）。
    代表帧数量被 _RECAST_MASK_SAMPLES 封顶（默认 24）：H3 VAE 的 latent 行数远多于 17k+5
    的直觉（362 帧 → 107 行），逐行打 NPU 会变成两百多次请求、每段多花好几分钟，
    而人物位置在 0.6s 内几乎不变，按"每行取最近的已采样帧"映射足够。
    结果里 1=允许重绘（人物），0=锁死源像素（背景）。全部分割失败返回 None（退回旧的全 1 行为）。
    """
    if not _RECAST_MASK_ON:
        return None
    try:
        if isinstance(frames, torch.Tensor):
            frames_np = frames.detach().to("cpu", torch.float32).numpy()
        else:
            frames_np = np.asarray(frames, dtype=np.float32)
        n = int(frames_np.shape[0])
        h, w = int(frames_np.shape[1]), int(frames_np.shape[2])
        if n < 1 or t_lat < 1 or h < 8 or w < 8:
            return None
        base_url = _recast_npu_base_url()
        want = max(1, min(int(t_lat), int(_RECAST_MASK_SAMPLES)))
        if want >= n:
            s_idx = list(range(n))
        else:
            s_idx = sorted({int(round(k * (n - 1) / float(want - 1)) if want > 1 else 0)
                            for k in range(want)})
        masks = {}
        ok = 0
        for fidx in s_idx:
            _rgb = np.clip(frames_np[fidx], 0.0, 1.0) * 255.0
            _m = _recast_frame_person_mask(_rgb.astype(np.uint8), base_url)
            masks[fidx] = _m
            if _m is not None:
                ok += 1
        if ok == 0:
            log("[H3 Recast] ⚠️ 人物掩码一帧都没成功（NPU 服务不可用？）——退回全画幅重绘")
            return None
        valid_idx = [i for i in s_idx if masks.get(i) is not None and masks[i].max() > 0.05]
        rows = []
        for j in range(int(t_lat)):
            fpos = (j * (n - 1) / float(int(t_lat) - 1)) if int(t_lat) > 1 else 0.0
            k = min(s_idx, key=lambda v: abs(v - fpos))
            if (masks.get(k) is None or masks[k].max() <= 0.05) and valid_idx:
                k = min(valid_idx, key=lambda v: abs(v - fpos))
            _mk = masks.get(k)
            rows.append(np.zeros((h, w), np.float32) if _mk is None else _mk)
        stack = np.stack(rows, 0)  # [T,H,W]
        # 没分割出来的行用相邻有效行补齐，避免"这一 latent 行整帧锁死 → 人物闪烁"
        valid = [i for i in range(int(t_lat)) if rows[i].max() > 0.05]
        for i in range(int(t_lat)):
            if rows[i].max() <= 0.05 and valid:
                stack[i] = stack[min(valid, key=lambda v: abs(v - i))]
        import cv2 as _cv2d
        small = np.stack([
            _cv2d.resize(stack[j], (int(w_lat), int(h_lat)),
                         interpolation=_cv2d.INTER_AREA)
            for j in range(stack.shape[0])
        ], 0)
        m_t = torch.from_numpy(small).float().unsqueeze(0).unsqueeze(0)
        log(f"[H3 Recast] 人物掩码已生成：{ok}/{len(s_idx)} 代表帧分割成功"
            f"（映射到 {int(t_lat)} 个 latent 行），"
            f"人区占画面 {float(small.mean()):.1%}（背景锁定源像素，只重绘人物）")
        return m_t
    except Exception as exc:
        log(f"[H3 Recast] ⚠️ 人物掩码生成失败（{exc}）——退回全画幅重绘")
        return None


def _recast_build_av_latent(vae, audio_vae, path, start_sec, dur_sec,
                           width, height, frame_count, ffmpeg=None,
                           subject_mask=True, with_audio=True):
    """源片段 → (video_latent, audio_latent_or_None, info, subject_mask)。

    v14.341/342: 第 35 档「视频角色替换+动作迁移」复用本函数，掩码由调用方按模式给：
      subject_mask=True （人物替换）→ 人物掩码，人区 1 重绘 / 背景 0 锁源像素；
      subject_mask=False（动作迁移）→ 返回 None，调用方落成全 1 掩码（背景可重绘）；
      with_audio=False → 不读源音轨，音频行交还模型重生成（教程"不送原声"模式）。
    失败抛异常由调用方处理。"""
    frames = _recast_read_segment_frames(
        path, start_sec, dur_sec, width, height, frame_count, ffmpeg=ffmpeg)
    if frames is None:
        raise RuntimeError("源视频抽帧失败")
    vz = vae.encode(frames)
    if vz.ndim == 5:
        video_z = vz
    elif vz.ndim == 4:
        video_z = vz.unsqueeze(2)
    else:
        raise RuntimeError(f"video_vae.encode 返回异常形状 {tuple(vz.shape)}")
    audio_z = None
    if with_audio and audio_vae is not None:
        sr = int(getattr(audio_vae, "audio_sample_rate", 32000))
        ta_want = int(round((frame_count / float(FPS)) * AUDIO_LATENT_FPS))
        # 音频 latent 每一行对应 1/40 s 的源原声
        need_samples = int(round(ta_want * (sr / float(AUDIO_LATENT_FPS))))
        wav = _recast_read_segment_audio(
            path, start_sec, dur_sec, sr, need_samples, ffmpeg=ffmpeg)
        if wav is not None:
            az = audio_vae.encode(wav.movedim(1, -1))
            if az.ndim == 4:
                audio_z = az
                if int(audio_z.shape[-1]) > ta_want:
                    audio_z = audio_z[..., :ta_want]
                elif int(audio_z.shape[-1]) < ta_want:
                    audio_z = torch.nn.functional.pad(
                        audio_z, (ta_want - int(audio_z.shape[-1]), 0))
    info = (f"src={os.path.basename(str(path))} [{start_sec:.2f}s, +{dur_sec:.2f}s) "
            f"{frames.shape[0]}f {width}x{height} "
            f"vz={tuple(video_z.shape)} az={tuple(audio_z.shape) if audio_z is not None else None}")
    # v14.337: 人物区域掩码（人区=1 重绘 / 背景=0 锁死源像素），失败返回 None
    # video_z 到这里恒为 5 维 [B,C,T,h,w]
    if subject_mask:
        subject_mask_t = _recast_subject_mask(
            frames, int(video_z.shape[2]), int(video_z.shape[3]), int(video_z.shape[4]))
    else:
        subject_mask_t = None
    return video_z, audio_z, info, subject_mask_t


def _recast_build_plan(clips, asset_library, ffmpeg=None, log=print):
    """在分镜里找 <Video N>，建立"源视频时间轴 → clipN"的替换计划。

    自动分段的硬规则（对齐 MiniMax H3 Recast 单镜头 ≤15s）：
      n = ceil(源视频时长 / 15s)；分镜里参与替换的分镜数 < n 时**补齐分镜**，
      每段时长 = 源视频时长 / n（帧数对齐 H3 的 17k+5 网格）。
      45s 源视频 → 3 段 × 15s，正好对应"每个 clip 15 秒自动分 3 个 clip"。
    已是足够多分镜时尊重用户自己的时长切分。

    返回值:
      {"path", "tag", "duration", "segments": {clip_idx: (start_sec, dur_sec)},
       "auto_added", "disabled", "audio": bool}  或 None（不是替换任务）
    """
    start_idx = None
    tag_num = None
    for idx, clip in enumerate(clips):
        m = _RECAST_VIDEO_TAG_RE.search(str(clip.get("prompt") or ""))
        if m:
            start_idx = idx
            tag_num = int(m.group(1))
            break
    if start_idx is None:
        log("[H3 Recast] 未在分镜提示词里找到 <Video N>（@视频N），本档未执行替换；"
            "请把源视频放进资产库并在分镜里引用 @视频N")
        return None

    entry = _recast_find_video_asset(asset_library, tag_num)
    if not isinstance(entry, dict):
        log(f"[H3 Recast] 资产库里找不到 @视频{tag_num}（视频资产数不足）")
        return None
    path = entry.get("path") or entry.get("filename") or ""
    if not path or not os.path.isfile(str(path)):
        log(f"[H3 Recast] @视频{tag_num} 指向的文件不存在: {path}")
        return None

    duration = _recast_probe_duration(path, ffmpeg)
    fallback_dur = 0.0
    for clip in clips[start_idx:]:
        try:
            fallback_dur += float(clip.get("duration", 0) or 0)
        except (TypeError, ValueError):
            pass
    if duration is None or duration <= 0.05:
        duration = fallback_dur if fallback_dur > 0 else None
        if duration is None:
            log(f"[H3 Recast] 无法探测 @视频{tag_num} 时长，替换中止")
            return None
        log(f"[H3 Recast] ⚠️ 探测不到源视频时长，按分镜总时长 {duration:.2f}s 处理")

    seg_cap = float(_RECAST_SEG_SECONDS)
    n_need = max(1, min(_RECAST_MAX_CLIPS, int(math.ceil((duration - 0.02) / seg_cap))))
    have = len(clips) - start_idx
    auto_added = 0
    template = clips[start_idx]
    if have < n_need:
        for _k in range(n_need - have):
            nc = copy.deepcopy(template)
            nc["id"] = f"{str(template.get('id', 'clip'))}_recast_{_k + 1}"
            nc["validated"] = False
            nc["replace_mode"] = False
            nc["render_enabled"] = True
            nc["context_enabled"] = False
            clips.append(nc)
            auto_added += 1
        log(f"[H3 Recast] 源视频 {duration:.2f}s → 按 15s/段上限切成 {n_need} 段，"
            f"自动补齐 {auto_added} 个 CLIP（原分镜 {have} 个）")
    elif have > n_need:
        log(f"[H3 Recast] 源视频 {duration:.2f}s 只需 {n_need} 段，分镜有 {have} 段："
            f"多出的 {have - n_need} 段没有源画面可替换，已跳过渲染")

    # 每段时长：源视频时长 / 段数，并对齐 H3 的 17k+5 帧网格（保证抽帧数与 latent 行数一致）
    seg_dur_raw = duration / float(n_need)
    seg_frames = _duration_to_frames(seg_dur_raw)
    seg_dur = float(seg_frames) / float(FPS)

    segments = {}
    cursor = 0.0
    disabled = 0
    for j in range(start_idx, len(clips)):
        rel = j - start_idx
        if rel >= n_need:
            clips[j]["render_enabled"] = False
            disabled += 1
            continue
        clips[j]["duration"] = seg_dur
        clips[j]["context_enabled"] = False
        clips[j]["validated"] = False
        clips[j]["render_enabled"] = True
        segments[j] = (cursor, seg_dur)
        cursor += seg_dur

    total_planned = cursor
    if seg_dur > seg_cap + 0.05:
        log(f"[H3 Recast] 注：17k+5 帧网格对齐后每段 {seg_dur:.2f}s，比 {seg_cap:g}s 上限多 "
            f"{seg_dur - seg_cap:.2f}s（{seg_frames} 帧）；这是网格硬约束的结果，"
            "源片尾部不足的部分用末帧冻结补齐")
    log(f"[H3 Recast] 替换计划: @视频{tag_num} 共 {duration:.2f}s → {n_need} 段 × "
        f"{seg_dur:.2f}s（{seg_frames} 帧/段，H3 17k+5 网格），覆盖 {total_planned:.2f}s；"
        f"源原声整段锁定，不做段间 motion context 续链")
    return {
        "path": str(path),
        "tag": tag_num,
        "duration": float(duration),
        "segments": segments,
        "auto_added": int(auto_added),
        "disabled": int(disabled),
        "audio": bool(isinstance(asset_library, dict)),
    }


# ===========================================================================
# v14.341 (2026-11-09) 视频角色替换 + 动作迁移 —— Video Remix (no-LoRA)
#
# 来源: Bilibili BV1HBWJ6HEkg《MiniMax H3 最强人物替换&动作迁移、一张图整段视频
#       换主角、不用lora、长视频自动分段续接、附提示词》（小肥猴）
#
# 与第 33 档「视频替换 (V2V 人物替换)」不是超集，而是另一条契约:
#   第 33 档 = 单段 ≤15s 硬切、段间绝不续链、只重绘人物区、8 步单采、要求 swap LoRA;
#   本档     = 226 帧/段 (5+17k, 24fps ≈9.42s, 教程默认档位)、段间 22 帧重叠锁定续接、
#              人物替换走人物掩码锁源背景 / 提示词写"新场景"才全画幅(动作迁移)、
#              一采 8 步(默认; 教程原口径 4 步, 实测 4 步欠噪) + 二采 5 步(二采先放大
#              1.5x 再补细节, 等价教程"高噪 4 步 + 低噪 5 步")、不要求任何
#              swap/角色替换 LoRA(教程实测会带出欧美脸、颜色融不进原片色调)。
#
# 教程口径落地要点:
#   ① 一张人物图 = 身份(脸/发型/体型/服装/鞋帽)，姿势构图动作一律以源视频为准;
#   ② 人物替换 vs 动作迁移**只由提示词决定**: 背景按源片写 = 换人保场景;
#      背景只写新场景 = 动作迁移到新场景;
#   ③ 只挂加速 LoRA(加速 LoRA 不参与身份语义)，不挂 swap/角色替换 LoRA;
#   ④ 源原声默认锁进 AV latent 音频行(noise_mask=0)，口型/对白/环境声与源片逐帧
#      对齐(教程"默认不送原声"只为省显存; 本机 5090 上锁音频收益远大于开销);
#      BSAI_H3_REMIX_LOCK_AUDIO=0 可退回"视频只做动作参考、音频由模型重生成";
#   ⑤ 长视频自动分段: 226 帧/段, 第 k 段(0 起)源时间轴起点 = 204*k/24s,
#      段头 22 帧 = 上一段段尾 22 帧(重叠锁定)，解码按 trim 裁掉 → 动作/光线连续;
#   ⑥ 断点续跑沿用既有 per-clip validated 机制(不改参数/素材重跑即续)。
# ===========================================================================
_REMIX_SEG_FRAMES = 226        # 5 + 17*13，教程默认每段帧数（24fps ≈ 9.42s）
_REMIX_OVERLAP_FRAMES = 22     # 段间重叠锁定帧数（教程固定 22）
_REMIX_MIN_TAIL_FRAMES = 73    # 5 + 17*4，尾段最短档（再短就没有可用动作了）
_REMIX_MAX_CLIPS = 120

_REMIX_DISCIPLINE = (
    "【视频角色替换+动作迁移纪律】本段以“原视频”为唯一的动作、机位、构图与节奏来源："
    "① 身份纪律：参考图只决定身份——脸型、五官、肤色、发型（发色/发长/刘海/发饰）、体型、"
    "整套服装、鞋、袜、帽、手套、项链等配饰必须与参考图完全一致（颜色、款式、材质、长度一致）；"
    "原视频人物身上的旧服装与配饰不得保留、不得残留残片，也不得改色沿用。"
    "② 动作纪律：站位、手势、步态、视线、表情、口型与动作节奏逐帧跟随原视频，"
    "不得重新表演、不得改变动作轨迹、不得换机位，也不得新增或删除剪辑点。"
    "③ 背景只写一种：提示词写原视频的背景（场地、陈设、光线、天气、光源色温与原片一致），"
    "人物以外的像素保持源片原样 = 人物替换；提示词只写一个全新场景 = 动作迁移（原片背景不得出现）。"
    "两种背景不得混写，也不得让原场景与新场景同时出现。"
    "④ 多人同框时用“位置+外观+动作”指明要替换的那一位（例：画面右侧穿红色上衣正在挥手的短发女人），"
    "未被指名的其他人物保持原样。"
    "⑤ 参考图为多视角设定图时，取其中最清晰的正视图/半身近景决定脸与服装，"
    "不得把多个视角、多个分身或设定图本身拼进画面。"
    "⑥ 画面内不得出现参考图本身、分屏、灰底、色卡、拼图、文字、水印或额外分身。"
)


def _remix_lock_audio() -> bool:
    """本档是否把源原声锁进音频行（默认锁；=0 退回教程的"不送原声"省显存模式）。"""
    try:
        v = str(os.environ.get("BSAI_H3_REMIX_LOCK_AUDIO", "1")).strip().lower()
    except Exception:
        return True
    return v not in ("0", "false", "off", "no", "none", "")


def _remix_prompt(text: str) -> str:
    """本段最终送入 TE 的 Remix 提示词 = 纪律块 + 用户指令（去掉 <Video N>）。"""
    body = _recast_strip_video_tags(str(text or "")).strip()
    return _REMIX_DISCIPLINE + "\n" + body if body else _REMIX_DISCIPLINE


# v14.342: 本档"背景保不保"必须由模式决定，不能一律全画幅。
# 实跑证据(2026-11-09 14:25, 源片 896x540 夜景街头): 全画幅 noise_mask + denoise 0.65
# 实际从 σ≈0.96 起跑(= 整帧重生), 出片背景被重画成室内、人物只换了半张脸,
# 因为源片背景像素没有任何锁定区可保。人物替换必须退回人物掩码(背景 mask=0 锁源像素);
# 只有"动作迁移"(提示词明确要一个新场景)才该全画幅重绘。
_REMIX_NEW_SCENE_WORDS = (
    "换场景", "换个场景", "换成场景", "换一个新的场景", "另一个场景",
    "背景换成", "背景改成", "背景改为", "背景重画", "重建背景", "生成新背景",
    "全新的场景", "全新的背景",
)


_REMIX_DISCIPLINE_MARKS = ("【视频角色替换+动作迁移纪律】", "【参考图纪律】")


def _remix_user_text(prompt_text: str) -> str:
    """只留用户自己写的分镜正文：去掉纪律块（含标题与其正文）与所有 【…】 块。

    实跑事故(2026-11-09 15:13): 背景判定拿到的 effective_prompt 里已经拼进了纪律块，
    而纪律块第 ③ 条自己写着"提示词只写一个全新场景 = 动作迁移" —— "全新场景"命中
    "新场景"关键词，于是每一段都被判成动作迁移，人物掩码从来没生效过。
    """
    t = str(prompt_text or "")
    for mark in _REMIX_DISCIPLINE_MARKS:
        while mark in t:
            a = t.index(mark)
            b = t.find("\n", a)
            t = (t[:a] + (t[b + 1:] if b >= 0 else "")).strip()
    return t


def _remix_keep_background(prompt_text: str) -> bool:
    """本段是否锁定源片背景（人物掩码，背景 0 不重绘）。

    优先级: 环境变量 BSAI_H3_REMIX_KEEP_BG (0/1) > 用户正文里的"新场景"关键词 > 默认保背景。
    prompt_text 必须传**用户自己的分镜提示词**（未拼纪律块），否则纪律块正文会误触发。
    """
    try:
        v = str(os.environ.get("BSAI_H3_REMIX_KEEP_BG", "")).strip().lower()
    except Exception:
        v = ""
    if v not in ("", "auto"):
        return v not in ("0", "false", "off", "no", "none")
    t = _remix_user_text(prompt_text)
    return not any(w in t for w in _REMIX_NEW_SCENE_WORDS)


def _remix_build_plan(clips, asset_library, ffmpeg=None, log=print,
                      seg_frames=None, overlap_frames=None, pipeline="remix"):
    """建立"源视频时间轴 → clipN"的角色替换+动作迁移计划（226 帧/段 + 22 帧重叠）。

    分段规则（教程实测口径）:
      seg_frames = 226 (5+17k 网格), overlap = 22;
      第 0 段覆盖源帧 [0, 226)，第 k 段覆盖 [204*k, 204*k+226)；
      即每段净推进 204 帧，段头 22 帧与上一段段尾重合 → 动作/光线在接缝处连续。
      n = 1 + ceil((源帧数 - 226) / 204)，分镜不足时自动补齐 CLIP。

    v14.345: seg_frames / overlap_frames / pipeline 参数化 —— 第 36 档
    「Viggle Remake 视频改写」复用同一套源视频切片计划，但每段 226 帧、
    **0 重叠**（源片本身作为 cond video 逐段进入条件，不需要段头重叠续接）。
    """
    seg_frames = int(seg_frames) if seg_frames else int(_REMIX_SEG_FRAMES)
    if seg_frames % 17 != 5:
        seg_frames = _align_frame_count(seg_frames)
    overlap = max(0, min(int(_REMIX_OVERLAP_FRAMES if overlap_frames is None
                             else overlap_frames), seg_frames - 5))
    net_frames = max(5, seg_frames - overlap)
    seg_sec = float(seg_frames) / float(FPS)
    net_sec = float(net_frames) / float(FPS)

    start_idx = None
    tag_num = None
    for idx, clip in enumerate(clips):
        m = _RECAST_VIDEO_TAG_RE.search(str(clip.get("prompt") or ""))
        if m:
            start_idx = idx
            tag_num = int(m.group(1))
            break
    if start_idx is None:
        # v14.348: 分镜里漏写 @视频N 时不再硬中止 —— 资产库里有视频就按 index 1
        # 兜底，并把 <Video 1> 前缀补到第一个分镜上重试（用户实测最常见的就是
        # 提示词全写在全局、分镜正文只剩场景描述）。
        _vg_fb_video = 0
        try:
            _vg_fb_list = (asset_library or {}).get("videos") or []
            _vg_fb_video = len(_vg_fb_list)
        except Exception:
            _vg_fb_video = 0
        if _vg_fb_video > 0:
            tag_num = 1
            start_idx = 0
            _fb_prompt = str(clips[0].get("prompt") or "")
            if "<Video" not in _fb_prompt:
                clips[0]["prompt"] = f"<Video 1>\n" + _fb_prompt
            log("[H3 Remix] v14.348 分镜里没有 <Video N>，已按资产库第 1 个视频兜底，"
                "并把 <Video 1> 前缀补到第一个分镜")
        else:
            log("[H3 Remix] 未在分镜提示词里找到 <Video N>（@视频N），资产库也没有视频，本档未执行替换；"
                "请把源视频放进资产库并在分镜里引用 @视频N")
            return None

    entry = _recast_find_video_asset(asset_library, tag_num)
    if not isinstance(entry, dict):
        log(f"[H3 Remix] 资产库里找不到 @视频{tag_num}（视频资产数不足）")
        return None
    path = entry.get("path") or entry.get("filename") or ""
    if not path or not os.path.isfile(str(path)):
        log(f"[H3 Remix] @视频{tag_num} 指向的文件不存在: {path}")
        return None

    duration = _recast_probe_duration(path, ffmpeg)
    fallback_dur = 0.0
    for clip in clips[start_idx:]:
        try:
            fallback_dur += float(clip.get("duration", 0) or 0)
        except (TypeError, ValueError):
            pass
    if duration is None or duration <= 0.05:
        duration = fallback_dur if fallback_dur > 0 else None
        if duration is None:
            log(f"[H3 Remix] 无法探测 @视频{tag_num} 时长，本档中止")
            return None
        log(f"[H3 Remix] ⚠️ 探测不到源视频时长，按分镜总时长 {duration:.2f}s 处理")

    dur_frames = int(round(float(duration) * FPS))
    if dur_frames <= seg_frames:
        n_need = 1
    else:
        n_need = 1 + int(math.ceil((dur_frames - seg_frames) / float(net_frames)))
    n_need = max(1, min(_REMIX_MAX_CLIPS, n_need))

    have = len(clips) - start_idx
    auto_added = 0
    template = clips[start_idx]
    if have < n_need:
        for _k in range(n_need - have):
            nc = copy.deepcopy(template)
            nc["id"] = f"{str(template.get('id', 'clip'))}_{pipeline}_{_k + 1}"
            nc["validated"] = False
            nc["replace_mode"] = False
            nc["render_enabled"] = True
            nc["context_enabled"] = True
            clips.append(nc)
            auto_added += 1
        log(f"[H3 Remix] 源视频 {duration:.2f}s → 按 {seg_sec:.2f}s/段切成 {n_need} 段"
            f"（段间重叠 {overlap} 帧续接），自动补齐 {auto_added} 个 CLIP"
            f"（原分镜 {have} 个）")
    elif have > n_need:
        log(f"[H3 Remix] 源视频 {duration:.2f}s 只需 {n_need} 段，分镜有 {have} 段："
            f"多出的 {have - n_need} 段没有源画面可用，已跳过渲染")

    segments = {}
    frames_by_clip = {}
    disabled = 0
    net_total = 0
    for j in range(start_idx, len(clips)):
        rel = j - start_idx
        if rel >= n_need:
            clips[j]["render_enabled"] = False
            disabled += 1
            continue
        # v14.341: 尾段按"源片实际剩余帧数"取 17k+5 网格档 —— 固定 226 帧会让
        # 源片末尾之后的部分靠末帧冻结补齐（20s 源视频会多出 6.4s 静帧）。
        start_frame = rel * net_frames
        avail = max(5, dur_frames - start_frame)
        if avail >= seg_frames:
            frames = seg_frames
        else:
            frames = _align_frame_count(max(_align_frame_count(avail),
                                            _REMIX_MIN_TAIL_FRAMES))
        net_out = frames if rel == 0 else frames - overlap
        frames_by_clip[j] = int(frames)
        # 时长按"净输出"填（第 2 段起扣掉段头重叠帧），UI 上的时间轴才与成片一致；
        # 实际渲染帧数走 frames_by_clip，不受这个字段影响。
        clips[j]["duration"] = float(net_out) / float(FPS)
        # 第 2 段起开段间续接：段头 22 帧 = 上一段段尾（教程的"重叠帧锁定"）
        # v14.345: overlap=0 的 Viggle 档不得开续接（否则段头会被当上下文裁掉）。
        clips[j]["context_enabled"] = bool(overlap > 0 and rel > 0)
        clips[j]["validated"] = False
        clips[j]["render_enabled"] = True
        segments[j] = (float(start_frame) / float(FPS), float(frames) / float(FPS))
        net_total += net_out

    log(f"[H3 Remix] 计划: @视频{tag_num} 共 {duration:.2f}s → {n_need} 段 × "
        f"{seg_frames} 帧（{seg_sec:.2f}s/段，段间重叠 {overlap} 帧锁定续接），"
        f"尾段按剩余帧数收窄，成片净 {net_total} 帧 ≈ {net_total / float(FPS):.2f}s；"
        f"源原声{'锁定' if _remix_lock_audio() else '不锁(模型重生成)'}，"
        "人物替换默认用人物掩码锁住源背景（提示词写新场景才全画幅做动作迁移）")
    return {
        "path": str(path),
        "tag": tag_num,
        "duration": float(duration),
        "segments": segments,
        "frames_by_clip": frames_by_clip,
        "auto_added": int(auto_added),
        "disabled": int(disabled),
        "audio": bool(isinstance(asset_library, dict)),
        "pipeline": str(pipeline),
        "seg_frames": int(seg_frames),
        "overlap_frames": int(overlap),
    }


# ---------------------------------------------------------------------------
# v14.345 (2026-11-09) 第 36 档「Viggle Remake 视频改写」—— 官方 MiniMax H3
# 编辑 LoRA 契约 (https://huggingface.co/Viggle/Viggle-Remake)。
#
# 与第 33/35 档（Recast/Remix）的本质区别:
#   33/35 = 源片编码成 AV latent 作**初始化**, denoise 0.62/0.65 半重绘;
#   36    = 源片整段作为 **cond video**（minimax_refs 的 video block）进入条件,
#           目标 latent 是**全噪**(video mask=1), 源原声仍锁 clean(mask=0),
#           6 步固定 sigma(swap/edit 两组官方 knots), cfg 1.0, 无二采。
#   LoRA 必须挂 viggle_remake_swap/edit（rank256 alpha256, 只认 FL2VA 基座）,
#   且只能走 LoraLoaderBypassModelOnly / bypass 槽，不能用普通 LoraLoaderModelOnly。
# ---------------------------------------------------------------------------
_VIGGLE_SEG_FRAMES = 226       # 5 + 17*13, 与教程 226 帧/段一致(24fps ≈ 9.42s)
_VIGGLE_MIN_FRAMES = 90        # 官方下限 90 帧(5+17*5)
_VIGGLE_MAX_FRAMES = 345       # 官方上限 345 帧

_VIGGLE_DISCIPLINE = (
    "【Viggle Remake 视频改写纪律】本段以“原视频”为唯一的时间轴、机位、构图、"
    "动作节奏与背景来源：原片的人物站位、手势、步态、视线、镜头运动、剪辑点、"
    "场景陈设、光线与色温逐帧保持，不得换机位、不得重新表演、不得改变动作轨迹。"
    "只在用户明确指定的范围内改写：身份替换时脸型/五官/肤色/发型/体型/服装/配饰"
    "必须与 @图N 参考图完全一致，原人物旧服装不得残留；元素增删改时只增删改被点名的"
    "道具/服装/场景元素，其余像素仍按原片生成。口型与发声严格跟随原片音轨，"
    "不得改台词、不得改语速。画面内不得出现参考图本身、分屏、灰底、色卡、拼图、"
    "文字或水印，也不得出现额外分身。"
)


def _viggle_task() -> str:
    """本档任务类型: swap(人物/主体替换, 默认) 或 edit(元素增删改)。"""
    try:
        v = str(os.environ.get("BSAI_H3_VIGGLE_TASK", "swap")).strip().lower()
    except Exception:
        return "swap"
    return "edit" if v in ("edit", "modify", "inpaint", "增删改", "编辑") else "swap"


def _viggle_prompt(text: str) -> str:
    """最终送入 TE 的提示词 = Viggle 纪律块 + 用户指令（去掉 <Video N>）。"""
    body = _recast_strip_video_tags(str(text or "")).strip()
    return _VIGGLE_DISCIPLINE + "\n" + body if body else _VIGGLE_DISCIPLINE


def _viggle_build_plan(clips, asset_library, ffmpeg=None, log=print):
    """源视频 → clipN 的 Viggle Remake 计划: 每段 226 帧、0 重叠、逐段独立改写。"""
    _log = (lambda m: log(str(m).replace("[H3 Remix]", "[H3 Viggle]")))
    plan = _remix_build_plan(
        clips, asset_library, ffmpeg=ffmpeg, log=_log,
        seg_frames=_VIGGLE_SEG_FRAMES, overlap_frames=0, pipeline="viggle",
    )
    if plan is not None:
        _log(f"[H3 Viggle] 任务类型={_viggle_task()}（swap=主体替换 / edit=元素增删改，"
             "用 BSAI_H3_VIGGLE_TASK 切换）；每段 226 帧、0 重叠，源片整段作 cond video，"
             "目标 latent 全噪 6 步重绘；LoRA 必须挂 viggle_remake_swap/edit")
    return plan


# ---------------------------------------------------------------------------
# v14.330 全片 IMAGE 预览累积预算（内存止血）
#
# 每段 decode 得到的 IMAGE 是 float32 [T,H,W,C] 0..1：
#   1920x1088 / 289 帧 ≈ 6.75 GB/段，19 段 ≈ 128 GB。
# 全部 append 到 out_images 会把系统提交内存顶到 130GB+，在 63.5GB 物理内存的机器上
# 必然触发 pagefile 抖动 —— 实测墙钟 52min / 72min / 95min 一段，而实际采样只有 8~10min。
#
# 全片 MP4 已按段落盘（output/bsai_clips），合并由 BSAI Premiere Pro 节点完成；
# IMAGE 端口只用于 UI 预览，_concat_clip_av 在 OOM 时本来就降级为单帧占位。
# 因此这里给累积设预算：超预算即停止累积、只留 1 帧占位，内存增长归零。
#   BSAI_H3_AV_BUDGET_GB  默认 6（uint8 字节上限）
# ---------------------------------------------------------------------------
def _av_acc_budget_bytes():
    try:
        return int(float(os.environ.get("BSAI_H3_AV_BUDGET_GB", "6")) * (1024 ** 3))
    except Exception:
        return 6 * 1024 ** 3


def _av_acc_push(out_images, img, state, budget):
    """把单段 IMAGE 以 uint8 追加进预览累积队列；超预算则清空并停止累积。

    返回 True=本段已累积（或无需累积），False=已因超预算跳过。
    调用方无论如何都要把该段标记为已解码，避免收尾时重复 decode。
    """
    if img is None or int(img.shape[0]) == 0:
        return True
    if state.get("skip"):
        return False
    try:
        n = int(img.numel())
    except Exception:
        return True
    if (state.get("used", 0) + n) > budget:
        keep = None
        try:
            if out_images:
                keep = out_images[0][:1]
        except Exception:
            keep = None
        out_images.clear()
        if keep is not None:
            out_images.append(keep)
        state["skip"] = True
        print(
            f"[H3 Extender] v14.330 IMAGE 预览累积超预算 {budget / 1024 ** 3:.1f}GB："
            f"已停止全片 IMAGE 累积（保留 1 帧占位）。全片以 per-clip MP4 / 合并 MP4 为准；"
            f"避免每段 {n / 1024 ** 3:.2f}GB 的 float32 常驻把系统内存撑爆"
        )
        return False
    try:
        u8 = img.detach()
        if u8.is_floating_point():
            u8 = u8.clamp_(0.0, 1.0).mul_(255.0).round_().to(torch.uint8)
        elif u8.dtype != torch.uint8:
            u8 = u8.to(torch.uint8)
        u8 = u8.contiguous()
        out_images.append(u8)
        state["used"] = state.get("used", 0) + int(u8.numel())
    except Exception as _av_e:
        print(f"[H3 Extender] v14.330 IMAGE 预览累积降级(保留 float32): {_av_e}")
        out_images.append(img)
        state["used"] = state.get("used", 0) + n
    return True


def _mp_has_ck_quant_weights(model):
    """检测 ModelPatcher 是否携带 comfy_kitchen 量化权重（QuantizedTensor 参数）。

    partially_unload(offload_device, 1e32) 会对 comfy_patched_weights 的模块执行
    m.to(cpu)，QuantizedTensor._handle_to 在该路径下原生 access violation 崩溃
    （Python try/except 无法捕获，直接杀进程）。此类模型必须跳过强制卸载循环，
    交由 DynamicVRAM 调度 / delegate 收尾 / unload_all_models()（detach 路径）卸载。
    """
    try:
        raw = getattr(model, "model", None)
        if raw is None:
            return False
        for _p in raw.parameters():
            if "comfy_kitchen" in (type(_p).__module__ or ""):
                return True
    except Exception:
        pass
    return False


def _mp_ck_offload_or_pop(_lm, _mm):
    """量化模型安全卸载(round3 同类路径封堵)。

    dynamic 量化模型(如 H3 量化 DiT): 走 ComfyUI 标准 partially_unload(1e32) 块级卸载,
    该路径对本模型多次实测安全(日志 'Unloaded partially: 14719.41 MB freed, 0.00 MB
    remains loaded'); 卸载后若仍有 GPU 驻留(loaded_size>1MB), 按身份从
    current_loaded_models 摘除, 避免后续任何 detach/unpatch_model 的
    self.model.to(cpu) 对量化块触发 comfy_kitchen _handle_to 原生崩溃。
    非 dynamic 量化模型(如二采 delegate 克隆, round1 崩溃对象): 不触碰
    partially_unload(其 m.to(cpu) 会原生崩溃), 直接摘除注册, 由 GC/empty_cache 回收。
    """
    try:
        _m = getattr(_lm, "model", None)
        if _m is None:
            return
        import torch as _t
        if _m.is_dynamic():
            try:
                _m.partially_unload(_m.offload_device, 1e32)
                try:
                    _t.cuda.synchronize()
                except Exception:
                    pass
            except Exception:
                pass
            try:
                if _m.loaded_size() > 1024 * 1024:
                    _mm.current_loaded_models.remove(_lm)
            except Exception:
                pass
        else:
            try:
                _mm.current_loaded_models.remove(_lm)
            except Exception:
                pass
    except Exception:
        pass


def _decode_clip_to_av(owner, clip_index, vae, audio_vae, fps):
    """Decode one cached clip to (IMAGE tensor, AUDIO dict), trimmed of the
    leading context overlap so downstream concatenation matches the Final
    Decode & Export output exactly."""
    data_path, manifest_path = _chain_paths(f"extender_{_safe_name(str(owner))}")
    manifest = _load_manifest_from_paths(data_path, manifest_path)
    if manifest is None:
        return None, None
    segments = [dict(x) for x in manifest.get("segments", [])]
    i = int(clip_index)
    if i < 0 or i >= len(segments):
        return None, None
    curr = segments[i]

    # v1.25 + v14.153: free VRAM before decode - 终极清理:
    # 二采(时间分块/delegate驻留)后模型注册残留会导致加载 VideoVAE 时竞态闪退,
    # 这里摘除全部注册模型 + 标准卸载 + 双重清缓存, 给 VAE decode 干净显存。
    try:
        import comfy.model_management as _mm
        import torch as _torch
        # 1) 摘除全部注册模型(含二采 delegate 驻留的量化 DiT)
        _popped = 0
        for _lm in list(_mm.current_loaded_models):
            try:
                _mm.current_loaded_models.remove(_lm)
                _popped += 1
            except Exception:
                pass
        # 2) 标准卸载(对已摘除的为 no-op, 兜底仍有注册的)
        try:
            _mm.unload_all_models()
        except Exception:
            pass
        # v1.96: 强制 GC 回收 delegate 量化权重(二采后 Python 引用残留导致 14.5GB 不释放)
        import gc as _gc_v196
        for _gc_round in range(3):
            _gc_v196.collect()
            _torch.cuda.empty_cache()
            _torch.cuda.synchronize()
        # 3) 双重清缓存 + 同步
        _mm.soft_empty_cache(force=True)
        _torch.cuda.synchronize()
        _torch.cuda.empty_cache()
        _torch.cuda.synchronize()
        _torch.cuda.empty_cache()
        _a = _torch.cuda.memory_allocated() / 1024 ** 3
        print(f"[H3 Extender]   decode VRAM prepared (popped={_popped}, gc3x): allocated={_a:.2f}GB free={_torch.cuda.mem_get_info()[0]/1024**3:.2f}GB")
        # v1.96: 如果清理后 allocated 仍 >8GB, 说明 delegate 权重泄漏, 打印警告
        if _a > 8.0:
            print(f"[H3 Extender]   ⚠️ decode VRAM: allocated={_a:.1f}GB 偏高(delegate 权重残留), "
                  f"VAE decode 可能 OOM; 若崩溃需重启 ComfyUI")
    except Exception as _e:
        print(f"[H3 Extender]   decode VRAM cleanup skipped: {_e}")

    # v1.67: 优先从 preview decode 已产出的 MP4 blob 读帧(预览画质), 省一次
    # 2X VAE decode(~30-60s/段). 音频仍走音频 VAE(秒级). blob 缺失/失败回退 VAE.
    _blob = curr.get("decoded_mp4_blob")
    if _blob is not None:
        try:
            _root = _ensure_cache_root()
            _tmp = _root / f"_avread_{uuid.uuid4().hex[:8]}.mp4"
            _copy_blob_to_file(data_path, _blob, _tmp)
            _imgs = _read_frames_from_mp4(
                str(_tmp), _find_ffmpeg(),
                int(curr.get("frames", 0)), int(curr.get("trim_frames", 0)) if i > 0 else 0,
                int(curr.get("width", 1920)), int(curr.get("height", 1080)),
            )
            try:
                _tmp.unlink()
            except Exception:
                pass
            if _imgs is not None and int(_imgs.shape[0]) > 0:
                images = _imgs
                audio = None
                try:
                    if audio_vae is not None:
                        audio = _decode_single_audio(data_path, curr, audio_vae, float(fps))
                        if audio is not None and int(curr.get("trim_frames", 0)) > 0:
                            sr = int(audio["sample_rate"])
                            trim_samples = int(round(float(int(curr.get("trim_frames", 0))) / float(fps) * sr))
                            wave = audio["waveform"]
                            if trim_samples > 0 and trim_samples < int(wave.shape[-1]):
                                audio = dict(audio)
                                audio["waveform"] = wave[..., trim_samples:]
                except Exception as _e:
                    print(f"[H3 Extender] _decode_clip_to_av audio decode failed clip={i}: {_e}")
                    audio = None
                print(f"[H3 Extender] _decode_clip_to_av: clip={i} 复用 MP4 blob ({images.shape[0]} 帧, 跳过 VAE decode)")
                return images, audio
        except Exception as _mp4err:
            print(f"[H3 Extender] _decode_clip_to_av MP4 读帧失败, 回退 VAE decode: {_mp4err}")

    # Video latent -> pixels [T,C,H,W] in [0,1]
    try:
        v = _load_segment_video(data_path, curr)
        video = vae.decode(v)
        if video.ndim == 5:
            video = video.reshape(-1, video.shape[-3], video.shape[-2], video.shape[-1])
    except Exception as _e:
        print(f"[H3 Extender] _decode_clip_to_av video decode failed clip={i}: {_e}")
        return None, None

    trim = int(curr.get("trim_frames", 0)) if i > 0 else 0
    if trim > 0:
        video = video[trim:]
    if video.shape[0] == 0:
        return None, None
    images = video.movedim(1, -1).float().cpu().contiguous()  # [T,H,W,C]
    # v14.190: 去彩点(色度去斑) —— VAE 解码在轮廓处逐通道截断产生的单像素饱和彩点
    try:
        _dp_parts = []
        for _s in range(0, int(images.shape[0]), 16):
            _dp_parts.append(_despeckle_frames(images[_s:_s + 16]))
        if _dp_parts:
            images = torch.cat(_dp_parts, dim=0).contiguous()
        del _dp_parts
    except Exception as _dp_err:
        print(f"[H3 Extender] 彩点修复跳过 clip={i}: {_dp_err}")

    # Audio latent -> {waveform [B,C,L], sample_rate}
    audio = None
    try:
        if audio_vae is not None:
            audio = _decode_single_audio(data_path, curr, audio_vae, float(fps))
            if audio is not None and trim > 0:
                sr = int(audio["sample_rate"])
                trim_samples = int(round(float(trim) / float(fps) * sr))
                wave = audio["waveform"]
                if trim_samples > 0 and trim_samples < int(wave.shape[-1]):
                    audio = dict(audio)
                    audio["waveform"] = wave[..., trim_samples:]
    except Exception as _e:
        print(f"[H3 Extender] _decode_clip_to_av audio decode failed clip={i}: {_e}")
        audio = None

    return images, audio


def _send_clip_av_output(node_id, clip_index, clip_count, images, audio, video_path=None, clip_name=None):
    """Lightweight per-clip readiness signal for the frontend. Includes
    video_path (temp MP4) so downstream nodes like BSAI Premiere Pro can
    auto-import the clip to their timeline without waiting for the full run."""
    try:
        server = PromptServer.instance
        if server is None:
            return
        payload = {
            "node": str(node_id),
            "clip_index": int(clip_index),
            "clip_count": int(clip_count),
            "frames": int(images.shape[0]) if images is not None else 0,
            "width": int(images.shape[2]) if images is not None else 0,
            "height": int(images.shape[1]) if images is not None else 0,
            "sample_rate": int(audio["sample_rate"]) if audio is not None else 0,
            "ready": True,
            "video_path": str(video_path) if video_path else None,
            "clip_name": str(clip_name) if clip_name else None,
        }
        server.send_sync(
            "h3_extender_clip_av",
            payload,
            getattr(server, "client_id", None),
        )
    except Exception as _e:
        print(f"[H3 Extender] _send_clip_av_output error: {_e}")


def _concat_clip_av(images_list, audios_list):
    """Concatenate per-clip IMAGE tensors and AUDIO dicts into one IMAGE batch
    + one AUDIO dict (same format as ComfyUI IMAGE/AUDIO)."""
    imgs = [im for im in images_list if im is not None and int(im.shape[0]) > 0]
    if imgs:
        try:
            # v2.119: 尺寸统一兜底 — 若各 clip 帧尺寸不一致(如 1080 vs 1088,
            # 来源: 参考图分辨率污染 / 损坏缓存 / ffmpeg 异步编码异常写出畸形容器),
            # torch.cat 会直接报尺寸不匹配。检测到不一致时统一 resize 到最大
            # WxH 再拼接(保留完整预览); 尺寸一致时零开销走原路径。
            _sp = {(int(im.shape[1]), int(im.shape[2])) for im in imgs}
            if len(_sp) > 1:
                _max_h = max(int(im.shape[1]) for im in imgs)
                _max_w = max(int(im.shape[2]) for im in imgs)
                _norm = []
                for _im in imgs:
                    if int(_im.shape[1]) == _max_h and int(_im.shape[2]) == _max_w:
                        _norm.append(_im)
                    else:
                        _imf = _im.float().permute(0, 3, 1, 2).contiguous()
                        _imf = torch.nn.functional.interpolate(
                            _imf, size=(_max_h, _max_w), mode="bilinear", align_corners=False
                        )
                        _norm.append(_imf.permute(0, 2, 3, 1).contiguous())
                print(f"[H3 Extender] _concat_clip_av 尺寸统一: {sorted(_sp)} -> ({_max_h}, {_max_w})")
                imgs = _norm
            images = torch.cat(imgs, dim=0).float().cpu().contiguous()
        except Exception as _cat_err:
            # v2.118: 22 段 1080p 全分辨率 concat 会要 ~157GB 内存(OOM 崩节点)。
            # per-clip MP4 与 merged.mp4 早已落盘, 节点输出 tensor 仅用于 UI 预览,
            # concat 失败时降级为单帧占位, 不让整次渲染收尾崩掉。
            print(f"[H3 Extender] _concat_clip_av 大内存拼接跳过(MP4 已落盘): {_cat_err}")
            images = imgs[0][:1].float().cpu().contiguous()
    else:
        images = torch.zeros((0, 64, 64, 3), dtype=torch.float32)

    audios = [a for a in audios_list if a is not None and int(a["waveform"].shape[-1]) > 1]
    if audios:
        sr = int(audios[0]["sample_rate"])
        waves = [a["waveform"].cpu().float() for a in audios]
        max_ch = max(int(w.shape[1]) for w in waves)
        padded = []
        for w in waves:
            if int(w.shape[1]) < max_ch:
                pad = torch.zeros((w.shape[0], max_ch, w.shape[2]), dtype=w.dtype)
                pad[:, :w.shape[1], :] = w
                w = pad
            padded.append(w)
        waveform = torch.cat(padded, dim=-1)
        audio = {"waveform": waveform, "sample_rate": sr}
    else:
        audio = {"waveform": torch.zeros(1, 1, 1), "sample_rate": 32000}
    return images, audio


def _ls_auto_clip_durations_by_audio(clips, lip_audio, fps=24.0):
    """v14.251 (2026-10-29): 直播带货·03 lip_voice 档 —— 音频总时长驱动 clip 时长分配。

    用户诉求: TTS 稿音频总时长决定 clip 切分, 不再人工预估每段时长。
    例如 24s 音频 + 模板上限 15s → clip1=15s, clip2=9s (余下全给最后一段);
    35s 音频 + 上限 15s → clip1=15s, clip2=15s, clip3=5s。
    12s 音频 + 上限 15s → clip1=12s (不补零, 不触发 _ff_fit_audio_duration max_ratio)。

    规则:
      - 每段时长 ≤ clips[i].duration(模板/用户设定的上限)
      - 剩余音频全给最后一段(若最后一段超出上限则截断到上限, 尾部音频丢弃)
      - 音频总时长 ≤ 第一段上限 → 只有一段有效, 其余 clip 置 render_enabled=False
      - 非 lip_voice 03 档 / lip_audio None → 原样返回, 不做任何修改

    返回: (clips 新列表, 是否被修改)
    """
    if lip_audio is None or not clips:
        return clips, False

    try:
        waveform = lip_audio["waveform"]
        sr = int(lip_audio["sample_rate"])
        total_samples = int(waveform.shape[-1])
        audio_total_sec = float(total_samples) / float(sr)
    except Exception:
        return clips, False

    if audio_total_sec <= 0:
        return clips, False

    remaining = audio_total_sec
    modified = False
    new_clips = []
    for i, cfg in enumerate(clips):
        cfg = dict(cfg)
        try:
            tpl_dur = float(cfg.get("duration", 15.0))
        except Exception:
            tpl_dur = 15.0
        tpl_dur = max(0.25, min(150.0, tpl_dur))

        if remaining <= 0:
            # 音频已分完 → 本段不需要渲染
            if cfg.get("render_enabled", True):
                cfg["render_enabled"] = False
                modified = True
            new_clips.append(cfg)
            continue

        new_dur = min(tpl_dur, remaining)
        if abs(new_dur - float(cfg.get("duration", tpl_dur))) > 0.01:
            cfg["duration"] = new_dur
            modified = True
        # 尾段强制启用渲染(若有音频剩余)
        if not cfg.get("render_enabled", True):
            cfg["render_enabled"] = True
            modified = True
        new_clips.append(cfg)
        remaining -= new_dur

    if remaining > 0.05:
        print(f"[H3 LipSync] v14.251 音频总时长 {audio_total_sec:.2f}s 超出全部 clip 上限总和, "
              f"尾部 {remaining:.2f}s 音频将被丢弃 (可加大 clip 时长上限或增加 clip 数)")

    if modified:
        _durs = [f"{c['duration']:.2f}s" for c in new_clips if c.get('render_enabled', True)]
        print(f"[H3 LipSync] v14.251 音频驱动 clip 时长: 音频总长={audio_total_sec:.2f}s, "
              f"分配 → {'/'.join(_durs)}")
    return new_clips, modified


def _split_lip_audio_by_clips(lip_audio, clips, fps=24.0, context_frames=0,
                              explicit_clip_durations=None):
    """Split a full lip-sync audio into per-clip segments based on clip durations.

    Args:
        lip_audio: AUDIO dict {"waveform": [B,C,L], "sample_rate": int}
        clips: list of clip dicts, each with "duration" (seconds)
        fps: video frame rate (used to align clip durations to frame grid)
        context_frames: motion context 帧数 (context_length, 默认39)。
            ctx_on 段的头部被上一段尾部的 motion context 占用, 模型净输出 =
            标称时长 - context_frames/fps 秒。切分推进必须按净时长, 否则每个
            段间边界原曲被跳过 1.625s(39帧@24fps) → 歌曲听感"断了一截"。

    Returns:
        list of AUDIO dicts, one per clip. Length = len(clips).
        If lip_audio is None, returns [None] * len(clips).
    """
    if lip_audio is None:
        return [None] * len(clips)

    waveform = lip_audio["waveform"]
    sr = int(lip_audio["sample_rate"])
    total_samples = int(waveform.shape[-1])
    total_duration = float(total_samples) / float(sr)

    # v14.253 (fix): 剔除对口型源音频里的"数字全零断点"。
    # TTS/拼接产物常在句间留下 0.1~0.2s 的精确全零(实测 26.264s TTS 在
    # 14.049~14.247 有 0.199s 全零), 成片听感就是"人在说话突然断了 0.2s"。
    # 自然换气的 RMS 在 0.001~0.005 量级, 不是全零, 所以只裁 |x|<=1e-4 的
    # 连续 >=80ms 全零段: 人声连续, 正常停顿完全不受影响。
    # 裁剪后按 6ms 交叉淡入淡出拼接, 避免硬切爆音。
    try:
        _wf = waveform
        if _wf.dim() >= 2 and int(_wf.shape[-1]) > 1:
            _mag = _wf.abs().amax(dim=tuple(range(_wf.dim() - 1)))
            _zarr = (_mag <= 1e-4).detach().cpu().numpy()
            _min_run = max(1, int(round(0.08 * sr)))
            _n = int(_zarr.shape[-1])
            _gaps, _pos = [], 0
            while _pos < _n:
                if bool(_zarr[_pos]):
                    _end = _pos
                    while _end < _n and bool(_zarr[_end]):
                        _end += 1
                    if (_end - _pos) >= _min_run:
                        _gaps.append((_pos, _end))
                    _pos = _end
                else:
                    _pos += 1
            if _gaps:
                _kept, _prev = [], 0
                for _gs, _ge in _gaps:
                    if _gs > _prev:
                        _kept.append(_wf[..., _prev:_gs])
                    _prev = _ge
                if _prev < _n:
                    _kept.append(_wf[..., _prev:])
                if _kept:
                    _fade = max(1, int(round(0.006 * sr)))
                    _out = _kept[0]
                    for _chunk in _kept[1:]:
                        if (_fade > 0 and _out.shape[-1] >= _fade
                                and _chunk.shape[-1] >= _fade):
                            _ramp = torch.linspace(0.0, 1.0, _fade,
                                                   device=_out.device, dtype=_out.dtype)
                            _mix = (_out[..., -_fade:] * (1.0 - _ramp)
                                    + _chunk[..., :_fade] * _ramp)
                            _out = torch.cat((_out[..., :-_fade], _mix,
                                              _chunk[..., _fade:]), dim=-1)
                        else:
                            _out = torch.cat((_out, _chunk), dim=-1)
                    _removed = float(total_duration - float(_out.shape[-1]) / float(sr))
                    waveform = _out
                    total_samples = int(waveform.shape[-1])
                    total_duration = float(total_samples) / float(sr)
                    print(f"[H3 LipSync] v14.253 剔除源音频数字全零断点 "
                          f"{len(_gaps)} 处, 共 {_removed:.2f}s (人声连续性修复)")
    except Exception as _zg_e:
        print(f"[H3 LipSync] v14.253 全零断点剔除跳过(可忽略): {_zg_e}")

    # v14.254 (fix): 每段推进必须与渲染端(v14.177)的实际净帧数同口径。
    # 渲染端: clip1 = _align_frame_count(round(dur*FPS))  → 12s 得 294 帧(12.25s);
    #         clip2+ (ctx_on) = _align_frame_count(round(dur*FPS)+ctx) - ctx → 289 帧(12.04s)。
    # 旧实现所有段都按 _duration_to_frames(dur)=294 推进, 于是 clip2+ 只播出
    # 289 帧原曲、歌曲指针却前进 294 帧 → 每个 clip2+ 边界被跳过 5~6 帧(0.21~0.25s)。
    # 用户实测: clip2 段尾原曲 00:24:06 → clip3 段头原曲从 00:24:12 起, 中间丢 6 帧;
    # clip1(294 帧)与推进量一致, 所以恰好在 clip1→clip2 边界无缝。
    _ctx_frames = 0
    try:
        _ctx_frames = max(0, int(context_frames))
    except (TypeError, ValueError):
        _ctx_frames = 0
    _ctx_ov_samples = int(round(_ctx_frames / float(fps) * sr)) if _ctx_frames else 0

    clip_durations = []
    if (explicit_clip_durations is not None
            and len(explicit_clip_durations) == len(clips)):
        # v14.302: 多人对话逐段 TTS 路径传入每段实测音频时长，直接用，不再按
        # cfg.duration 重算帧网格。原因：ctx_on 段的渲染净帧数 = align(raw+ctx)-ctx，
        # 恒比网格化音频多 1~16 帧(最多 0.67s)，重算后每段"多占"下一段 0.5s 台词，
        # 缺口累积到末段 → 末段台词被截断(实测 clip4 5.88s 音频只播 4.22s)。
        # 直传实测时长后，音频段与台词严格同长；多出来的视频尾帧落成静默尾，
        # 不侵占任何一段台词。
        for _d in explicit_clip_durations:
            clip_durations.append(max(1.0 / float(fps), float(_d)))
    else:
        for idx, cfg in enumerate(clips):
            dur = float(cfg.get("duration", 5.0))
            _raw = max(5, int(round(dur * float(fps))))
            _ctx_on = bool(cfg.get("context_enabled", True)) if idx < len(clips) else True
            if idx > 0 and _ctx_on and _ctx_frames > 0:
                _frames = max(5, _align_frame_count(_raw + _ctx_frames) - _ctx_frames)
            else:
                _frames = _align_frame_count(_raw)
            clip_durations.append(float(_frames) / float(fps))

    sum_clip_dur = sum(clip_durations)

    # If clip total > audio total, scale down proportionally.
    # v14.248: clips duration 来自用户分镜 cfg["duration"], 但实际渲染帧数可能与
    # 规划不符(例: clips[1].duration 规划 30s 但直播带货档实际只渲 15s)。当
    # sum_clip_dur/total_duration > 1.3 (差异>30%) 时, 按错误比例 scale 会导致
    # 每段注入 AV latent 的音频段比视频短, 尾部出现静音 gap(用户实测
    # h3_motion_preview_7_0.mp4: 每段尾部 ~3s 完全静音)。改为等分音频总长到
    # N 段, 保证每段音频段覆盖对应视频时长。
    if sum_clip_dur > total_duration + 0.01:
        _ratio = sum_clip_dur / total_duration
        if _ratio > 1.3:
            _per_seg = total_duration / len(clip_durations)
            clip_durations = [_per_seg] * len(clip_durations)
            print(f"[H3 LipSync] CLIP总时长({sum_clip_dur:.1f}s) > 音频总时长({total_duration:.1f}s)，"
                  f"差异 {_ratio:.2f}x > 1.3x, clips duration 口径可能不准, "
                  f"等分到 {len(clip_durations)} 段 (每段 {_per_seg:.2f}s)")
        else:
            # v14.253 (fix): 不再按比例缩放每一段。
            # 旧实现按 total/sum 等比缩小所有段(实测 26.264s 音频 / 26.625s 视频
            # -> x0.9865), 使每段音频都比自己的视频帧短(例 clip1 音频 14.879s
            # 而视频 362 帧 = 15.083s)。解码混音时段尾被 torch.zeros 补零
            # (motion_context_disk 的 _pad), 于是每个接缝都出现 ~0.2s 全零静音坑。
            # 现只把缺口压到末段: 前面各段严格等于各自视频时长 -> 段间零补零;
            # 缺口(本例 0.36s)落在片尾最后一段末尾, 片尾静音不可闻, 远好于段间断点。
            _deficit = max(0.0, float(sum_clip_dur - total_duration))
            if clip_durations and _deficit > 0:
                _floor = 1.0 / float(fps)
                clip_durations[-1] = max(_floor, float(clip_durations[-1]) - _deficit)
            print(f"[H3 LipSync] CLIP总时长({sum_clip_dur:.2f}s) > 音频总时长({total_duration:.2f}s)，"
                  f"缺口 {_deficit:.2f}s 全部由末段吸收(前面各段保持整帧, 段间零补零)")

    # Split audio into segments
    # v2: For clips after the first, extend the segment backward by ~1s to cover
    # the motion context's audio overlap (carry-over from previous clip).
    # The H3 model's motion context carries ~22 video frames (~0.9s) from the
    # previous clip, which adds ~74 audio latent rows. Without this overlap,
    # cond_audio_rows is shorter than all_audio_rows[~audio_update] → shape mismatch.
    # v2.111 (fix): 重叠只对"开启上下文参考"的 CLIP 生效。用户关闭 context_enabled
    # 时模型不带 motion context，若仍切重叠会(1)渲染条件多 1.2s 音频、(2)输出混音
    # 把上一段尾部音乐带进本段 → clip2+ 与 lip_audio 原始音频错位。现在：
    #   - context_enabled=True  → 段头部含 overlap_samples 重叠(模型 latent 行需要)，
    #     同时把 overlap_samples 记进段 dict，解码混音时精确跳过 → 输出仍与原始对齐。
    #   - context_enabled=False → 纯净切分(零重叠)，输入/输出双侧都与原始音频对齐。
    # v14.178 曾把重叠改成 0 (2s 重叠在长链上累积回声)。但实测 3 段成片:
    # clip2 覆盖原曲 [13.55, 24.18], clip3 从 25.8 开始 —— 每个 ctx_on 边界
    # 原曲被跳过 1.625s(39 帧@24fps), 听感"音频断了一截"。
    # 根因: motion context 占用段头部 context_frames 帧(视频=上一段尾部,
    # 音频也必须是上一段尾部对应的原曲), 模型净输出 = 标称 - context。零重叠
    # 时输入/输出都缺这 1.625s → 段间缺口 + 尾对齐后新帧音频整体前移(口型错位)。
    # 现按 context_frames/fps 精确切重叠:
    #   段 = [current - overlap, current + N)  (N = 标称净时长)
    #   推进 = N。解码混音时切掉段头 overlap → 输出恰好 N, 与视频净帧数等长,
    #   段间零缺口、零补零静音, 口型与音频严格同源。
    segments = []
    current_sample = 0
    for idx, dur in enumerate(clip_durations):
        nominal_samples = max(1, int(round(dur * sr)))

        _ctx_on = bool(clips[idx].get("context_enabled", True)) if idx < len(clips) else True
        _overlap = min(_ctx_ov_samples, max(0, nominal_samples - 1)) if (idx > 0 and _ctx_on) else 0
        # v14.252 (fix): 段长 = 净时长 nominal + 头部重叠 overlap, 推进 = nominal。
        # 旧实现把 overlap 算进 nominal 内(段长 nominal 含重叠), 解码混音时又按
        # overlap_samples 切掉段头 → 每段只剩 nominal-overlap 的原曲, 尾部补零 →
        # clip2+ 每段末尾静音(用户实测 h3_clip_250_1/2 对比: 仅 clip1 结尾无缝);
        # 且歌曲每段少推进 overlap, 20 段累积错位 ~4s。
        _content_samples = max(1, nominal_samples)
        _seg_samples = nominal_samples + _overlap

        seg_start = max(0, current_sample - _overlap)
        end_sample = min(current_sample + _content_samples, total_samples)
        actual_samples = end_sample - seg_start

        if actual_samples <= 0:
            silent = torch.zeros(waveform.shape[0], waveform.shape[1], _seg_samples,
                                 dtype=waveform.dtype, device=waveform.device)
            segments.append({"waveform": silent, "sample_rate": sr, "overlap_samples": 0})
        else:
            seg_wave = waveform[..., seg_start:end_sample].clone()
            if seg_wave.shape[-1] < _seg_samples:
                pad_len = _seg_samples - seg_wave.shape[-1]
                pad = torch.zeros(waveform.shape[0], waveform.shape[1], pad_len,
                                  dtype=waveform.dtype, device=waveform.device)
                seg_wave = torch.cat([seg_wave, pad], dim=-1)
            segments.append({"waveform": seg_wave, "sample_rate": sr, "overlap_samples": _overlap})

        current_sample = end_sample

    print(f"[H3 LipSync] 音频分割完成: {len(segments)} 段, 总时长 {total_duration:.2f}s / {total_samples} samples")
    for i, seg in enumerate(segments[:8]):
        if seg:
            d = int(seg["waveform"].shape[-1]) / float(sr)
            _ov_d = int(seg.get("overlap_samples", 0)) / float(sr)
            print(f"  clip[{i+1}]: {d:.2f}s ({int(seg['waveform'].shape[-1])} samples, 头部重叠 {_ov_d:.2f}s)")
    if len(segments) > 5:
        print(f"  ... 共 {len(segments)} 段")

    return segments


def _ff_fit_audio_duration(audio, target_sec, max_ratio=0.20):
    """v14.203: lip_voice 台词音频按视频总时长做 atempo 变速(不变调)。

    lip_voice(TTS 口播稿) 的时长由合成引擎决定, 与分镜总时长几乎不可能正好相等:
      - 比视频短 → _split_lip_audio_by_clips 按比例缩短每段, 每段尾部留静音,
        口型在线尾前就闭合;
      - 比视频长 → 单句台词被段边界截断, 或触发自动追加延续 CLIP。
    这里用 ffmpeg atempo 把整条语音压/拉到视频总时长, 再交给切分, 段边界永远
    落在整句台词之间。只对 lip_voice 生效(lip_audio 歌曲不做变速)。
    比例超出 ±max_ratio 时不做处理, 交给原有缩放/追加 CLIP 逻辑兜底。
    """
    try:
        wf = audio["waveform"]
        sr = int(audio["sample_rate"])
        dur = float(wf.shape[-1]) / float(sr)
        if dur <= 0 or target_sec <= 0:
            return None
        ratio = float(target_sec) / dur
        if abs(ratio - 1.0) <= 0.02:
            return None
        if abs(ratio - 1.0) > max_ratio:
            print(f"[H3 LipSync] lip_voice 时长 {dur:.2f}s 与视频 {target_sec:.2f}s 相差 "
                  f"{(ratio - 1.0) * 100:+.0f}%，超出 ±{max_ratio * 100:.0f}% 变速范围，按原速切分")
            return None
        ffmpeg = _find_ffmpeg()
        tempo = 1.0 / ratio
        with tempfile.TemporaryDirectory(prefix="bsai_lipvoice_fit_") as td:
            src = os.path.join(td, "in.wav")
            dst = os.path.join(td, "out.wav")
            torchaudio.save(src, wf[0].detach().cpu().float(), sr)
            subprocess.run(
                [ffmpeg, "-y", "-loglevel", "error", "-i", src,
                 "-filter:a", f"atempo={tempo:.5f}", dst],
                check=True, capture_output=True,
            )
            out, out_sr = torchaudio.load(dst)
        print(f"[H3 LipSync] ✅ lip_voice 时长自适应: {dur:.2f}s -> {target_sec:.2f}s "
              f"(atempo={tempo:.3f}, 变速不变调)")
        return {"waveform": out.unsqueeze(0), "sample_rate": int(out_sr)}
    except Exception as _fit_err:
        print(f"[H3 LipSync] lip_voice 时长自适应失败(按原速切分): {_fit_err}")
        return None


def _detect_speech_in_audio(audio, sr=32000, threshold_db=-35.0, min_duration=0.15):
    """Detect speech/singing segments in audio based on RMS energy.

    Returns list of (start_sec, end_sec) tuples where audio energy is above threshold.
    Used to determine which parts of a clip should have lip-sync and which shouldn't.
    """
    import numpy as np

    waveform = audio["waveform"]
    if waveform.dim() > 2:
        waveform = waveform[0]  # take first batch
    if waveform.shape[0] > 1:
        mono = waveform.mean(dim=0)
    else:
        mono = waveform[0]

    mono_np = mono.cpu().numpy().astype(np.float32)
    total_samples = len(mono_np)

    # Frame size for energy calculation (20ms windows)
    frame_len = max(1, int(sr * 0.02))
    hop_len = frame_len // 2

    # Compute RMS per frame
    num_frames = max(1, (total_samples - frame_len) // hop_len + 1)
    rms_values = np.zeros(num_frames, dtype=np.float32)
    for f in range(num_frames):
        start = f * hop_len
        end = min(start + frame_len, total_samples)
        frame = mono_np[start:end]
        rms_values[f] = np.sqrt(np.mean(frame ** 2) + 1e-10)

    # Convert to dB
    rms_db = 20.0 * np.log10(rms_values + 1e-10)

    threshold_linear = 10.0 ** (threshold_db / 20.0)
    mask = rms_values > threshold_linear

    # Find contiguous segments
    segments = []
    in_seg = False
    seg_start = 0
    min_frames = max(1, int(min_duration * sr / hop_len))

    for f in range(num_frames):
        if mask[f] and not in_seg:
            seg_start = f
            in_seg = True
        elif not mask[f] and in_seg:
            if f - seg_start >= min_frames:
                start_sec = seg_start * hop_len / float(sr)
                end_sec = f * hop_len / float(sr)
                segments.append((start_sec, end_sec))
            in_seg = False

    if in_seg:
        if num_frames - seg_start >= min_frames:
            start_sec = seg_start * hop_len / float(sr)
            end_sec = num_frames * hop_len / float(sr)
            segments.append((start_sec, end_sec))

    return segments


def _apply_h3_block_cache(model, residual_diff_threshold=0.12, cache_device="cpu"):
    """Best-effort integration of the F1B0 block-cache acceleration (from the
    T8 MiniMax H3 Block Cache plugin) straight into the Extender's own
    sequential clip sampling.  Reuses the proven residual cache so consecutive
    clips that stay temporally stable skip most DiT blocks.  If the T8 plugin
    is not installed, sampling silently continues without acceleration."""
    try:
        from comfy.ldm.minimax.model import MiniMaxH3Model
        diffusion_model = model.model.diffusion_model
        if not isinstance(diffusion_model, MiniMaxH3Model):
            print("[H3 Extender] block cache skipped: not a native MiniMax H3 model")
            return model

        import os as _os
        import sys as _sys
        t8_dir = None
        try:
            cnode_paths = folder_paths.get_folder_paths("custom_nodes")
        except Exception:
            cnode_paths = []
        for base in list(cnode_paths) + [os.path.join(folder_paths.base_path, "custom_nodes")]:
            cand = os.path.join(str(base), "comfyui-minimax-h3-blockcache-T8")
            if os.path.isdir(cand):
                t8_dir = cand
                break
        if t8_dir is None:
            raise RuntimeError("comfyui-minimax-h3-blockcache-T8 not installed")
        if t8_dir not in _sys.path:
            _sys.path.insert(0, t8_dir)

        import importlib.util as _ilu
        import types as _types
        cache_spec = _ilu.spec_from_file_location("_t8_h3_block_cache", os.path.join(t8_dir, "h3_block_cache.py"))
        cache_mod = _ilu.module_from_spec(cache_spec)
        cache_spec.loader.exec_module(cache_mod)
        CACHE_KEY = cache_mod.CACHE_KEY
        H3BlockCache = cache_mod.H3BlockCache
        H3BlockCacheConfig = cache_mod.H3BlockCacheConfig
        H3BlockPatch = cache_mod.H3BlockPatch
        _pkg = _types.ModuleType("_t8_plugin")
        _pkg.__path__ = [t8_dir]
        _sys.modules["_t8_plugin"] = _pkg
        _sys.modules["_t8_plugin.h3_block_cache"] = cache_mod
        nodes_spec = _ilu.spec_from_file_location("_t8_plugin.nodes", os.path.join(t8_dir, "nodes.py"))
        nodes_mod = _ilu.module_from_spec(nodes_spec)
        nodes_spec.loader.exec_module(nodes_mod)
        h3_block_cache_sample_wrapper = nodes_mod.h3_block_cache_sample_wrapper
        h3_block_cache_diffusion_wrapper = nodes_mod.h3_block_cache_diffusion_wrapper
        import comfy.patcher_extension as _pe

        total_blocks = len(diffusion_model.blocks)
        if total_blocks < 2:
            raise RuntimeError("H3 model has fewer than 2 DiT blocks")

        transformer_options = model.model_options["transformer_options"]
        if CACHE_KEY in transformer_options or "easycache" in transformer_options:
            print("[H3 Extender] block cache skipped: another cache already active")
            return model

        model = model.clone()
        config = H3BlockCacheConfig(
            residual_diff_threshold=float(residual_diff_threshold),
            start_percent=0.08,
            end_percent=0.95,
            max_consecutive_hits=2,
            cache_device=str(cache_device),
            metric_stride=8,
            verbose=False,
        )
        to = model.model_options["transformer_options"].copy()
        to[CACHE_KEY] = H3BlockCache(config, total_blocks)
        model.model_options["transformer_options"] = to

        model.set_model_patch_replace(H3BlockPatch(0), "dit", "double_block", 0)
        model.set_model_patch_replace(
            H3BlockPatch(total_blocks - 1), "dit", "double_block", total_blocks - 1
        )
        model.add_wrapper_with_key(
            _pe.WrappersMP.OUTER_SAMPLE, "minimax_h3_block_cache_t8", h3_block_cache_sample_wrapper
        )
        model.add_wrapper_with_key(
            _pe.WrappersMP.DIFFUSION_MODEL, "minimax_h3_block_cache_t8", h3_block_cache_diffusion_wrapper
        )
        print(f"[H3 Extender] block cache ACTIVE threshold={residual_diff_threshold} device={cache_device}")
        return model
    except Exception as _e:
        print(f"[H3 Extender] block cache unavailable, running without acceleration: {_e}")
        return model


# ============================================================
# v1.40 (2026-09-13): 自动注入 MiniMax H3 省显存 patches
# v1.39 失败原因: 我试图复制 KJNodes 的 forward 逻辑, 但 cast_to_input /
# self.kj_num_chunks / quant_ops.ck 几个 API 签名/属性对不上, 抄错了.
#
# v1.40 改用: 直接 import KJNodes 已经验证过的 3 个 plain function
# (minimax_mlp_chunked_forward / minimax_attn_lowmem_forward /
# minimax_block_lowmem_forward), 然后用 KJNodes 自己的 MiniMaxChunkFeedForward
# + MiniMaxLowVRAMAttention 节点里完全相同的 add_object_patch 流程. 不
# 再自己抄代码, 复用 KJNodes 已经能跑通的实现.
#
# 24GB 物理卡跑 1.5x/2.0x 二采的硬性要求:
#   - FFN SwiGLU token 切 2 块 → peak FFN 显存减半
#   - attention 头切 4 块 → sol_attn workspace 缩 1/4 (6.46GB → ~1.6GB)
# ============================================================

# Lazy import KJNodes pure functions (避免 ComfyUI 启动时硬依赖)
def _ff_get_kj_forward_fns():
    """返回 KJNodes 已经验证过的 3 个 plain function. 失败时返回 None.

    v1.41: 之前用 from custom_nodes.ComfyUI_KJNodes 失败 — 插件文件夹名是
    ComfyUI-KJNodes (带连字符), Python module 名不允许连字符, 必须用
    importlib.util.spec_from_file_location 走文件直加载. 此函数只取
    minimax_mlp_chunked_forward / minimax_attn_lowmem_forward /
    minimax_block_lowmem_forward 三个 plain function, 它们的源码在
    ComfyUI-KJNodes/nodes/minimax_nodes.py 顶部 def 段, 不依赖 KJNodes
    自己的 nodes.py 顶层 (那里会拉 comfy_aimdo.vram_buffer 等可选依赖).
    """
    import importlib.util as _ilu
    import os as _os
    # 找 ComfyUI-KJNodes 目录
    try:
        import folder_paths as _fp
        _bases = list(_fp.get_folder_paths("custom_nodes")) + [_fp.base_path]
    except Exception:
        _bases = []
    kj_root = None
    for _b in _bases:
        _cand = _os.path.join(str(_b), "ComfyUI-KJNodes")
        if _os.path.isdir(_cand):
            kj_root = _cand
            break
    if kj_root is None:
        print("[H3 Extender] v1.41 KJNodes 目录未找到 (在 custom_nodes 下找不到 ComfyUI-KJNodes)")
        return None
    # 直加载 minimax_nodes.py
    fpath = _os.path.join(kj_root, "nodes", "minimax_nodes.py")
    if not _os.path.isfile(fpath):
        print(f"[H3 Extender] v1.41 找不到 {fpath}")
        return None
    spec = _ilu.spec_from_file_location("_kj_minimax_v141", fpath)
    if spec is None or spec.loader is None:
        print(f"[H3 Extender] v1.41 spec_from_file_location 失败")
        return None
    mod = _ilu.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as _ex:
        # minimax_nodes.py 顶部会 import comfy.model_management / comfy.ops /
        # comfy.quant_ops, 其中任一个缺都会 raise. 但 你的 ComfyUI venv 已
        # 经能加载这些 (Sol-H3 也 import), 所以这个 _ex 几乎不会发生.
        print(f"[H3 Extender] v1.41 exec_module 失败: {_ex}")
        return None
    if not all(hasattr(mod, n) for n in ("minimax_mlp_chunked_forward",
                                          "minimax_attn_lowmem_forward",
                                          "minimax_block_lowmem_forward")):
        print("[H3 Extender] v1.41 mod 缺 3 个函数")
        return None
    return (mod.minimax_mlp_chunked_forward,
            mod.minimax_attn_lowmem_forward,
            mod.minimax_block_lowmem_forward)


def _ff_apply_h3_lowvram_patches(model, ff_chunks=2, ff_seq_threshold=4096,
                                 attn_head_chunks=4, verbose=True):
    """v1.40: 在 Extender 内部为 H3 model 注入 KJNodes 已验证的省显存 patches.

    完整复刻 ComfyUI-KJNodes 的 MiniMaxChunkFeedForward.execute + MiniMaxLowVRAMAttention.execute
    流程 (mm.cast_to(weight, device) 2 个位置参数 + add_object_patch + transformer_options 写
    minimax_head_chunks + sol_take_forward). 不再自己抄 forward 内部, 完全交给 KJNodes 实现.
    """
    try:
        if model is None:
            return model
        # 1) 拿 KJNodes 纯函数
        kj = _ff_get_kj_forward_fns()
        if kj is None:
            print("[H3 Extender] v1.40 KJNodes 不可用, 跳过省显存 patches (会按老路径 OOM)")
            return model
        kj_mlp, kj_attn, kj_block = kj

        # 2) 幂等性: 已在 model_options 里有 minimax_head_chunks, 不重复套
        to = model.model_options.get("transformer_options", {}) or {}
        already_lowvram = to.get("minimax_head_chunks") is not None
        m = model if already_lowvram else model.clone()
        diffusion_model = m.get_model_object("diffusion_model")
        blocks = getattr(diffusion_model, "blocks", None)
        if not blocks or not hasattr(blocks[0], "attn") or not hasattr(blocks[0].attn, "qkv_proj"):
            print("[H3 Extender] v1.40 model 不是 MiniMax H3 (无 attn.qkv_proj), 跳过")
            return model

        # 3) FFN chunking — 复用 KJNodes 的 MiniMaxFFNChunkPatch + minimax_mlp_chunked_forward
        if ff_chunks > 1 and not already_lowvram and hasattr(blocks[0], "mlp"):
            for idx, block in enumerate(blocks):
                # 先设属性, 然后调 KJNodes minimax_mlp_chunked_forward
                # 它的逻辑是 self.kj_seq_threshold / self.kj_num_chunks
                block.mlp.kj_num_chunks = ff_chunks
                block.mlp.kj_seq_threshold = ff_seq_threshold
                m.add_object_patch(
                    f"diffusion_model.blocks.{idx}.mlp.forward",
                    types.MethodType(kj_mlp, block.mlp),
                )

        # 4) attention low-mem — 完全照搬 KJNodes MiniMaxLowVRAMAttention.execute
        if attn_head_chunks > 1:
            m.model_options.setdefault("transformer_options", {})
            m.model_options["transformer_options"]["minimax_head_chunks"] = attn_head_chunks
        # sol_take_forward 每次都设 (幂等)
        m.model_options["transformer_options"]["sol_take_forward"] = kj_attn

        for idx, block in enumerate(blocks):
            m.add_object_patch(
                f"diffusion_model.blocks.{idx}.forward",
                types.MethodType(kj_block, block),
            )
            attn_key = f"diffusion_model.blocks.{idx}.attn.forward"
            if attn_key in m.object_patches:
                # 已有其他 patch (如 Sol-Attn 走 _uses_optimized_attention 路径),
                # 保留它, 它会从 transformer_options 读 head_chunks
                continue
            m.add_object_patch(attn_key, types.MethodType(kj_attn, block.attn))

        if verbose:
            print(f"[H3 Extender] v1.40 注入 H3 低显存 patches (复用 KJNodes): "
                  f"ff_chunks={ff_chunks} attn_head_chunks={attn_head_chunks} "
                  f"blocks={len(blocks)} already_patched={already_lowvram}")
        return m
    except Exception as _pv_err:
        print(f"[H3 Extender] v1.40 注入失败(回退原 model, 24GB 卡会 OOM): {_pv_err}")
        import traceback
        traceback.print_exc()
        return model


def _apply_cache_dit(model, model_type="Auto", warmup_steps=0, skip_interval=0, print_summary=True):
    """Best-effort integration of ComfyUI-CacheDiT (DiT inter-step residual
    caching; MiniMax-H3 supported, ~1.41-1.50x) into the Extender's own clip
    sampling. If the plugin is not installed, sampling silently continues
    without it."""
    try:
        import os as _os
        import sys as _sys
        import importlib.util as _ilu
        import types as _types

        cd_dir = None
        try:
            cnode_paths = folder_paths.get_folder_paths("custom_nodes")
        except Exception:
            cnode_paths = []
        for base in list(cnode_paths) + [os.path.join(folder_paths.base_path, "custom_nodes")]:
            cand = os.path.join(str(base), "ComfyUI-CacheDiT")
            if os.path.isdir(cand):
                cd_dir = cand
                break
        if cd_dir is None:
            raise RuntimeError("ComfyUI-CacheDiT not installed")

        if cd_dir not in _sys.path:
            _sys.path.insert(0, cd_dir)

        _pkg = _types.ModuleType("_cache_dit_pkg")
        _pkg.__path__ = [cd_dir]
        _sys.modules["_cache_dit_pkg"] = _pkg

        utils_spec = _ilu.spec_from_file_location("_cache_dit_pkg.utils", os.path.join(cd_dir, "utils.py"))
        utils_mod = _ilu.module_from_spec(utils_spec)
        utils_spec.loader.exec_module(utils_mod)
        _sys.modules["_cache_dit_pkg.utils"] = utils_mod

        nodes_spec = _ilu.spec_from_file_location("_cache_dit_pkg.nodes", os.path.join(cd_dir, "nodes.py"))
        nodes_mod = _ilu.module_from_spec(nodes_spec)
        nodes_spec.loader.exec_module(nodes_mod)

        optimizer_cls = nodes_mod.CacheDiT_Model_Optimizer
        opt = optimizer_cls()
        out = opt.optimize(
            model,
            enable=True,
            model_type=str(model_type),
            warmup_steps=int(warmup_steps),
            skip_interval=int(skip_interval),
            print_summary=bool(print_summary),
        )
        if isinstance(out, (tuple, list)):
            out = out[0]
        print(f"[H3 Extender] CacheDiT ACTIVE model_type={model_type}")
        return out
    except Exception as _e:
        print(f"[H3 Extender] CacheDiT unavailable, running without it: {_e}")
        return model


CANVAS_MULTIPLE = 32
# v1.25: 短边从 2048 降到 1024——2048 短边的大图单图产生 ~18000 visual tokens，
# 7 张 ref 总 token ~78000，TE 自注意力 causal_mask N×N 在 24GB 卡上直接 OOM。
# v1.29: 短边从 1024 降到 768——expandable_segments 生效后 TE 编码峰值从 23GB 降到 5.5GB，
# 但 TE 是 ModelPatcherDynamic（VBAR 虚拟地址空间），绕过 cudaMallocAsync 池，MLP down_proj
# 需要 1.19GB 连续块时 VBAR 无法提供导致 OOM（allocated 仅 5GB 但 free=0）。
# 768 短边 visual token 再减 ~45%（1024: ~46000 → 768: ~25000），MLP 激活内存同比下降，
# 角色参考图细节仍足够识别（ref 图仅用于特征提取，不影响输出分辨率 768×1344）。
REF_IMAGE_SHORT_EDGE = 768
MAX_CLIPS = 512
DEFAULT_DURATION = 10.0
DEFAULT_MEGAPIXELS = 0.40
MAX_RESOLUTION = 4096
DEFAULT_SEED_MAX = (1 << 53) - 1  # exact integer range in browser JS

PROJECT_FORMAT = "MiniMax H3 Extender Project"
PROJECT_FORMAT_VERSION = 2
PROJECT_SUPPORTED_VERSIONS = {1, 2}
PROJECT_JSON_MAX_BYTES = 16 * 1024 * 1024
PROJECT_DOWNLOAD_TTL_SECONDS = 2 * 60 * 60
PROJECT_COPY_CHUNK = 8 * 1024 * 1024
MAX_IMAGE_REFS = 9
REFS_JSON_VERSION = 2
MAX_REF_UPLOAD_BYTES = 256 * 1024 * 1024
MAX_REF_PIXELS = 120_000_000
_PROJECT_DOWNLOADS = {}


def _align_frame_count(n: int) -> int:
    n = max(5, int(n))
    while n % 17 != 5:
        n += 1
    return n


def _video_latent_t(frame_count: int) -> int:
    return 2 if frame_count <= 5 else ((frame_count - 5) // 17) * 5 + 2


def _duration_to_frames(seconds: float) -> int:
    raw = max(5, int(round(float(seconds) * FPS)))
    return _align_frame_count(raw)


def _empty_av_latent(width: int, height: int, frame_count: int):
    frame_count = _align_frame_count(frame_count)
    latent_t = _video_latent_t(frame_count)
    duration = frame_count / float(FPS)
    audio_t = round(duration * AUDIO_LATENT_FPS)
    device = comfy.model_management.intermediate_device()
    video = torch.zeros(
        [1, 24, latent_t, int(height) // 16, int(width) // 16],
        device=device,
    )
    audio = torch.zeros(
        [1, 32, 2, int(audio_t)],
        device=device,
    )
    return {"samples": comfy.nested_tensor.NestedTensor((video, audio))}


def _manual_effective_resolution(width: int, height: int):
    """Snap Manual/fallback resolution to MiniMax H3's 32-pixel canvas grid."""
    step = CANVAS_MULTIPLE
    w = max(step, min(MAX_RESOLUTION, (int(width) // step) * step))
    h = max(step, min(MAX_RESOLUTION, (int(height) // step) * step))
    return w, h


def _auto_resolution_from_dimensions(src_w: int, src_h: int, megapixels: float):
    """Auto resolution on H3's 32-pixel grid without exceeding the MP budget.

    H3's standard workflows use resolution_steps=32. For the Extender we snap
    DOWN to that grid rather than to the nearest value: this keeps every Auto
    canvas divisible by 32 while avoiding an upward size jump on borderline
    Dynamic-VRAM/AIMDO setups.

    Manual/fallback mode uses the same 32-pixel canvas grid, so every newly
    requested H3 resolution follows the same alignment rule.
    """
    src_w = int(src_w)
    src_h = int(src_h)
    if src_w <= 0 or src_h <= 0:
        raise ValueError("MiniMax H3 Extender: reference image has invalid dimensions.")

    mp = max(0.01, min(16.0, float(megapixels)))
    total = mp * 1024.0 * 1024.0
    scale_by = math.sqrt(total / float(src_w * src_h))
    scaled_w = float(src_w) * scale_by
    scaled_h = float(src_h) * scale_by

    if scaled_w > MAX_RESOLUTION or scaled_h > MAX_RESOLUTION:
        shrink = min(MAX_RESOLUTION / scaled_w, MAX_RESOLUTION / scaled_h)
        scaled_w *= shrink
        scaled_h *= shrink

    step = int(CANVAS_MULTIPLE)
    w = max(step, min(MAX_RESOLUTION, int(math.floor(scaled_w / step)) * step))
    h = max(step, min(MAX_RESOLUTION, int(math.floor(scaled_h / step)) * step))
    return w, h


def _auto_resolution_from_image(image, megapixels: float):
    if image is None or getattr(image, "ndim", 0) < 4:
        raise ValueError("MiniMax H3 Extender: invalid reference image for auto resolution.")
    return _auto_resolution_from_dimensions(
        int(image.shape[2]),
        int(image.shape[1]),
        megapixels,
    )


def _refs_root():
    root = _ensure_cache_root() / "_refs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _ref_id_is_safe(value):
    value = str(value or "").lower()
    return len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def _ref_path(ref_id):
    ref_id = str(ref_id or "").lower()
    if not _ref_id_is_safe(ref_id):
        raise ValueError("MiniMax H3 Extender: invalid internal reference id.")
    return _refs_root() / f"{ref_id}.png"


def _empty_refs():
    return [None for _ in range(MAX_IMAGE_REFS)]


def _normalize_ref_descriptor(value):
    if not isinstance(value, dict):
        return None
    ref_id = str(value.get("id") or value.get("ref_id") or "").lower().strip()
    if not _ref_id_is_safe(ref_id):
        return None
    try:
        width = int(value.get("width", 0) or 0)
        height = int(value.get("height", 0) or 0)
    except Exception:
        width = height = 0
    try:
        size_bytes = int(value.get("size_bytes", 0) or 0)
    except Exception:
        size_bytes = 0
    source_id = str(value.get("source_id") or value.get("original_id") or ref_id).lower().strip()
    if not _ref_id_is_safe(source_id):
        source_id = ref_id

    def _adjustment(name):
        try:
            number = float(value.get(name, 100) or 100)
        except Exception:
            number = 100.0
        if not math.isfinite(number):
            number = 100.0
        return max(0.0, min(200.0, number))

    return {
        "id": ref_id,
        "source_id": source_id,
        "original_name": str(value.get("original_name") or value.get("name") or "reference.png"),
        "width": max(0, width),
        "height": max(0, height),
        "size_bytes": max(0, size_bytes),
        "saturation": _adjustment("saturation"),
        "contrast": _adjustment("contrast"),
        "brightness": _adjustment("brightness"),
    }


def _normalize_ref_descriptors(refs):
    """Normalize nine stable logical ref slots without compacting holes."""
    source = list(refs or [])[:MAX_IMAGE_REFS]
    normalized = []
    for value in source:
        normalized.append(_normalize_ref_descriptor(value))
    normalized += [None] * (MAX_IMAGE_REFS - len(normalized))
    return normalized


# ---------------------------------------------------------------------------
# v14.220 直播带货配音模式 01/02/03 —— 一键切换。
# 直播带货（讲话类）渲染管道拆成三种配音模式，共用同一套采样配方
# （复用「直播带货（全自动）」的 12+4 / denoise0.55 / latentx2 / TST /
# 分块 / audio_context=0），仅在「用什么音频、模型要不要自己配音」上区分：
#   01 纯文本配音（三口不接）—— ref_audio/lip_audio/lip_voice 全部忽略，
#      模型只读分镜里的【口播】台词，用自身默认音色生成人声。
#   02 ref_audio 音色参考配音（只接参考）—— ref_audio 提供音色/风格参考，
#      模型读分镜台词生成人声但声线跟随 ref_audio；lip_audio/lip_voice 忽略。
#   03 lip_voice 对口型（只接现成主播音频）—— 模型不生成音频，声音完全由
#      lip_voice 提供并驱动 @图1 对口型；ref_audio 忽略。
# lip_audio 仅用于对口型 MV（歌曲），直播带货/讲话类一律不接。
# v14.270 例外（最高优先级）：无论哪个档/哪条渲染管道，只要 lip_audio 端口
# 接入有效音源，立即凌驾 01/02/03 接线强制，自动屏蔽 ref_audio/lip_voice。
# 返回模式键 "01"/"02"/"03"；非直播带货档返回 None。旧「直播带货（全自动）」
# 档等价于 02，历史工作流不受影响。
_LIVESTREAM_VOICE_PIPELINES = {
    "直播带货·01 纯文本配音（三口不接）": "01",
    "直播带货·02 ref_audio音色参考配音（只接参考）": "02",
    "直播带货·03 lip_voice对口型（只接现成主播音频）": "03",
    "直播带货（全自动）": "02",
}
_LIVESTREAM_VOICE_MODE_LABEL = {
    "01": "01 纯文本配音",
    "02": "02 ref_audio音色参考",
    "03": "03 lip_voice对口型",
}


def _livestream_voice_mode_of(render_pipeline_name):
    if not render_pipeline_name:
        return None
    return _LIVESTREAM_VOICE_PIPELINES.get(str(render_pipeline_name), None)


def _parse_refs_json(raw):
    if isinstance(raw, dict):
        payload = raw
    else:
        try:
            payload = json.loads(str(raw or "{}"))
        except Exception:
            payload = {}
    values = payload.get("refs") if isinstance(payload, dict) else None
    if not isinstance(values, list):
        values = []
    refs = [_normalize_ref_descriptor(value) for value in values[:MAX_IMAGE_REFS]]
    refs += [None] * (MAX_IMAGE_REFS - len(refs))
    return _normalize_ref_descriptors(refs)


def _refs_json(refs):
    return json.dumps(
        {"version": REFS_JSON_VERSION, "refs": _normalize_ref_descriptors(refs)},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _refs_signature(refs):
    ids = [ref.get("id") if isinstance(ref, dict) else None for ref in _normalize_ref_descriptors(refs)]
    raw = json.dumps(ids, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _asset_paths_signature(paths):
    """Content-ish signature of the @图N-resolved asset image paths.

    When asset-library images replace the internal refs, the refs are plain
    tensors: _normalize_ref_descriptor() drops them to None, so _refs_signature()
    is constant and the ref2va cache key never changes even after the user swaps
    the asset library for entirely different images. That made the cached VAE
    latents of the *old* assets keep being re-used. Path + mtime + size changes
    whenever the library is edited or same-named files are replaced, so the key
    invalidates and the new assets are encoded.
    """
    if not paths:
        return ""
    parts = []
    for p in paths[:MAX_IMAGE_REFS]:
        try:
            st = Path(p).stat()
            parts.append(f"{p}|{int(st.st_mtime)}|{int(st.st_size)}")
        except Exception:
            parts.append(str(p))
    raw = "|".join(parts).encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()[:16]


def _reference_count(refs):
    return sum(1 for ref in refs or [] if ref is not None)


def _validate_reference_file(path):
    path = Path(path)
    with Image.open(path) as image:
        width, height = map(int, image.size)
        if width <= 0 or height <= 0:
            raise ValueError("MiniMax H3 Extender: reference image has invalid dimensions.")
        if width * height > MAX_REF_PIXELS:
            raise ValueError(
                f"MiniMax H3 Extender: reference image is too large ({width}x{height})."
            )
        image.verify()
    return width, height


def _hash_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(PROJECT_COPY_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _store_uploaded_reference(source_path, original_name):
    """Normalize an uploaded reference to RGB PNG and store it content-addressed."""
    source_path = Path(source_path)
    temp_png = _refs_root() / f".upload_{uuid.uuid4().hex}.png"
    try:
        with Image.open(source_path) as source:
            source = ImageOps.exif_transpose(source)
            width, height = map(int, source.size)
            if width <= 0 or height <= 0:
                raise ValueError("MiniMax H3 Extender: reference image has invalid dimensions.")
            if width * height > MAX_REF_PIXELS:
                raise ValueError(
                    f"MiniMax H3 Extender: reference image is too large ({width}x{height})."
                )
            rgb = source.convert("RGB")
            rgb.save(temp_png, format="PNG", optimize=False, compress_level=4)

        ref_id = _hash_file(temp_png)
        target = _ref_path(ref_id)
        if target.exists():
            temp_png.unlink(missing_ok=True)
        else:
            os.replace(temp_png, target)
        return {
            "id": ref_id,
            "source_id": ref_id,
            "original_name": str(original_name or source_path.name or "reference.png"),
            "width": int(width),
            "height": int(height),
            "size_bytes": int(target.stat().st_size),
            "saturation": 100.0,
            "contrast": 100.0,
            "brightness": 100.0,
        }
    finally:
        try:
            temp_png.unlink(missing_ok=True)
        except Exception:
            pass


def _edit_internal_reference(source_id, original_name, brightness, contrast, saturation):
    """Render absolute photographic adjustments from the immutable source ref.

    Every edited descriptor keeps ``source_id`` pointing at the pixels that were
    originally loaded. Re-opening the editor therefore has an actual baseline:
    Reset = 100/100/100 against those original pixels, rather than 100% against
    the already edited derivative.
    """
    source_id = str(source_id or "").lower().strip()
    if not _ref_id_is_safe(source_id):
        raise ValueError("MiniMax H3 Extender: invalid source reference id.")

    source_path = _ref_path(source_id)
    if not source_path.exists():
        raise ValueError("MiniMax H3 Extender: original reference image not found.")

    def _factor(value, label):
        try:
            number = float(value)
        except Exception as exc:
            raise ValueError(f"MiniMax H3 Extender: invalid {label} value.") from exc
        if not math.isfinite(number) or number < 0.0 or number > 200.0:
            raise ValueError(f"MiniMax H3 Extender: {label} must be between 0 and 200 percent.")
        return number, number / 100.0

    brightness_value, brightness_factor = _factor(brightness, "brightness")
    contrast_value, contrast_factor = _factor(contrast, "contrast")
    saturation_value, saturation_factor = _factor(saturation, "saturation")

    temp_png = _refs_root() / f".edit_{uuid.uuid4().hex}.png"
    try:
        with Image.open(source_path) as source:
            image = source.convert("RGB")
            width, height = map(int, image.size)
            if width <= 0 or height <= 0:
                raise ValueError("MiniMax H3 Extender: reference image has invalid dimensions.")
            if width * height > MAX_REF_PIXELS:
                raise ValueError(
                    f"MiniMax H3 Extender: reference image is too large ({width}x{height})."
                )

            # Keep the order identical to the browser preview filter chain.
            if abs(brightness_factor - 1.0) > 1e-9:
                image = ImageEnhance.Brightness(image).enhance(brightness_factor)
            if abs(contrast_factor - 1.0) > 1e-9:
                image = ImageEnhance.Contrast(image).enhance(contrast_factor)
            if abs(saturation_factor - 1.0) > 1e-9:
                image = ImageEnhance.Color(image).enhance(saturation_factor)

            image.save(temp_png, format="PNG", optimize=False, compress_level=4)

        new_id = _hash_file(temp_png)
        target = _ref_path(new_id)
        if target.exists():
            temp_png.unlink(missing_ok=True)
        else:
            os.replace(temp_png, target)

        return {
            "id": new_id,
            "source_id": source_id,
            "original_name": str(original_name or "reference.png"),
            "width": int(width),
            "height": int(height),
            "size_bytes": int(target.stat().st_size),
            "saturation": float(saturation_value),
            "contrast": float(contrast_value),
            "brightness": float(brightness_value),
        }
    finally:
        try:
            temp_png.unlink(missing_ok=True)
        except Exception:
            pass

def _store_project_reference(source_path, original_name):
    """Validate an archived PNG and preserve its exact bytes/hash on import."""
    source_path = Path(source_path)
    width, height = _validate_reference_file(source_path)
    ref_id = _hash_file(source_path)
    target = _ref_path(ref_id)
    if not target.exists():
        temp = _refs_root() / f".import_{uuid.uuid4().hex}.png"
        shutil.copyfile(source_path, temp)
        try:
            os.replace(temp, target)
        finally:
            try:
                temp.unlink(missing_ok=True)
            except Exception:
                pass
    return {
        "id": ref_id,
        "source_id": ref_id,
        "original_name": str(original_name or "reference.png"),
        "width": int(width),
        "height": int(height),
        "size_bytes": int(target.stat().st_size),
        "saturation": 100.0,
        "contrast": 100.0,
        "brightness": 100.0,
    }


def _load_reference_tensor(ref):
    if not isinstance(ref, dict):
        raise ValueError("MiniMax H3 Extender: invalid internal reference metadata.")
    path = _ref_path(ref.get("id"))
    if not path.exists():
        raise FileNotFoundError(
            f"MiniMax H3 Extender: internal reference '{ref.get('original_name') or ref.get('id')}' is missing. "
            "Reload the reference image or load the portable .ext project that contains it."
        )
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        array = np.asarray(image, dtype=np.float32) / 255.0
    return torch.from_numpy(np.ascontiguousarray(array)).unsqueeze(0)


def _split_sheet_subjects(img):
    """把已判定为"多视图角色设定拼版"的 img 裁成单人参考张量列表。

    返回 list[Tensor]:
      - 无独立大胸像: [最左单人立绘];
      - 左胸像 + 多具全身立绘: [左侧大胸像(锁脸/发型/配饰), 正面全身立绘(锁服装/鞋帽)]。

    v14.340: 胸像与全身是同一角色的两个视角, 纪律块已声明为同一人的多视图,
    不会被当成第二个人; 胸像右缘以背景间隙为硬边界, 不卷入立绘残肢。
    """
    h, w = int(img.shape[1]), int(img.shape[2])
    ys = max(1, h // 320)
    xs = max(1, w // 480)
    small = img[0, ::ys, ::xs, :].detach().float().cpu().numpy()
    sh, sw = int(small.shape[0]), int(small.shape[1])
    if sh < 32 or sw < 64:
        return None
    border = np.concatenate([small[0], small[-1], small[:, 0], small[:, -1]], axis=0)
    bg = np.median(border, axis=0)
    fg = np.abs(small - bg).max(axis=2) > 0.12
    col = fg.mean(axis=0)
    gap = max(1, int(round(sw * 0.02)))
    bands = []
    start = None
    last_on = -1
    for x in range(sw):
        if col[x] > 0.22:
            if start is None:
                start = x
            last_on = x
        elif start is not None and x - last_on > gap:
            bands.append((start, last_on + 1))
            start = None
    if start is not None:
        bands.append((start, last_on + 1))

    ok = []
    for x0, x1 in bands:
        wf = (x1 - x0) / float(sw)
        if wf < 0.05 or wf > 0.35:
            continue
        rows = np.where(fg[:, x0:x1].any(axis=1))[0]
        if rows.size < 2:
            continue
        cov = (rows[-1] - rows[0] + 1) / float(sh)
        if cov < 0.5:
            continue
        ok.append((x0, x1, float(cov), float(wf)))
    if len(ok) < 3:
        return None
    figs = [b for b in ok if sum(
        1 for o in ok if max(o[3], b[3]) / min(o[3], b[3]) <= 1.8) >= 3]
    if not figs:
        return None
    fig_w = sorted(b[3] for b in figs)
    hero = max(ok, key=lambda b: b[3])
    dominant = (hero[3] >= 1.3 * fig_w[len(fig_w) // 2]
                and hero[0] <= min(b[0] for b in ok))
    sx, sy = w / float(sw), h / float(sh)
    clean = np.abs(small - bg).max(axis=2).max(axis=0) < 0.5

    def _box(b, bust=False, left_bound=None):
        x0, x1 = b[0], b[1]
        rows = np.where(fg[:, x0:x1].any(axis=1))[0]
        y0, y1 = int(rows[0]), int(rows[-1]) + 1
        mx = int(round((x1 - x0) * 0.12))
        my = int(round((y1 - y0) * 0.05))
        cl = max(0, x0 - mx)
        nxt = [bb[0] for bb in bands if bb[0] >= x1]
        cap_r = min(nxt) if nxt else sw
        if bust:
            while cl > 0 and not clean[cl]:
                cl -= 1
            cr = min(cap_r, x1 + mx)
            while cr < cap_r and not clean[cr - 1]:
                cr += 1
        else:
            # 全身立绘左边距: 取条带内前景第一列(立绘自身身体), 排除间隙/条带左缘
            # 斜跨过来的左邻胸像肩袖残肢; 再与左邻背景间隙硬边界取大值。
            seg_col = fg[:, x0:x1].mean(axis=0)
            fg_cols = np.where(seg_col > 0.06)[0]
            inner_x0 = x0 + int(fg_cols[0]) if fg_cols.size else x0
            # 底部行段(腿/鞋)前景起点更靠右: 残肢只露在底部角落, 用它进一步收紧左缘。
            seg_rows = fg[int(sh * 0.75):, x0:x1]
            bot_col = seg_rows.mean(axis=0)
            bot_cols = np.where(bot_col > 0.15)[0]
            if bot_cols.size:
                inner_x0 = max(inner_x0, x0 + int(bot_cols[0]))
            cl = max(cl, inner_x0)
            if left_bound is not None:
                cl = max(cl, left_bound)
            cr = min(sw, x1 + mx)
            while cr > x1 - (x1 - x0) // 4 and not clean[cr - 1]:
                cr -= 1
        cx0 = max(0, int(round(cl * sx)))
        cx1 = min(w, int(round(cr * sx)))
        cy0 = max(0, int(round((y0 - my) * sy)))
        cy1 = min(h, int(round((y1 + my) * sy)))
        if (cx1 - cx0) < 48 or (cy1 - cy0) < 96:
            return None
        return (cx0, cy0, cx1, cy1)

    def _crop_tensor(b, bust=False, left_bound=None):
        box = _box(b, bust=bust, left_bound=left_bound)
        if box is None:
            return None
        cx0, cy0, cx1, cy1 = box
        crop = img[:, cy0:cy1, cx0:cx1, :]
        # 全身立绘: 剔除被相邻胸像/立绘带进角落的零散残肢。
        if not bust:
            try:
                ca = crop[0].detach().float().cpu().numpy()
                ch, cw = int(ca.shape[0]), int(ca.shape[1])
                cbg = np.median(np.concatenate(
                    [ca[0], ca[-1], ca[:, 0], ca[:, -1]], axis=0), axis=0)
                cfg = np.abs(ca - cbg).max(axis=2) > 0.12

                # 主体列在 ≥2 个行段出现; 残肢列仅 1 段。
                bands = 4
                col_hits = np.zeros(cw, dtype=np.int32)
                for bi in range(bands):
                    r0, r1 = bi * ch // bands, (bi + 1) * ch // bands
                    seg = cfg[r0:r1]
                    scol = seg.mean(axis=0)
                    col_hits[scol > 0.06] += 1
                core = np.where(col_hits >= 2)[0]
                if core.size >= 2:
                    l0, l1 = int(core[0]), int(core[-1]) + 1
                    if (l1 - l0) >= 0.7 * cw:
                        crop = crop[:, :, l0:l1, :]

                ca = crop[0].detach().float().cpu().numpy()
                ch, cw = int(ca.shape[0]), int(ca.shape[1])
                cfg = np.abs(ca - cbg).max(axis=2) > 0.12
                rcol = cfg.mean(axis=1)
                rrows = np.where(rcol > 0.06)[0]
                if rrows.size >= 2:
                    ry0, ry1 = int(rrows[0]), int(rrows[-1]) + 1
                    if (ry1 - ry0) >= 0.7 * ch:
                        crop = crop[:, ry0:ry1, :, :]
            except Exception:
                pass
            # 角落残肢清理: 相邻胸像/立绘斜跨进裁切框的肩袖/手臂小块, 在前景掩码上
            # 与主体是断开的独立连通域。只剔除"贴侧边 + 顶部落在 70% 高度以下 +
            # 面积 < 30% 最大组件"的角落小块; 主体躯干/双腿/鞋都向上延伸到 70% 以上,
            # 不会被误删。填回背景色, 而不是按列裁掉(按列会把同列的腿/鞋一并切掉)。
            try:
                import cv2 as _cv2cc
                ca = crop[0].detach().float().cpu().numpy()
                ch, cw = int(ca.shape[0]), int(ca.shape[1])
                cbg2 = np.median(np.concatenate(
                    [ca[0], ca[-1], ca[:, 0], ca[:, -1]], axis=0), axis=0)
                cfg2 = (np.abs(ca - cbg2).max(axis=2) > 0.12).astype(np.uint8)
                _ncc, _lab, _st, _ = _cv2cc.connectedComponentsWithStats(cfg2, 8)
                if _ncc > 1:
                    _areas = _st[1:, _cv2cc.CC_STAT_AREA]
                    _maxa = int(_areas.max())
                    for _k in range(1, _ncc):
                        _x, _y, _cw2, _ch2, _ar = _st[_k]
                        _side = (_x == 0) or (_x + _cw2 == cw)
                        if _side and (_y / float(ch)) > 0.70 and _ar < 0.30 * _maxa:
                            ca[_lab == _k] = cbg2
                    crop = torch.from_numpy(np.ascontiguousarray(ca)).unsqueeze(0)
            except Exception:
                pass
        return crop

    if dominant:
        others = [b for b in ok if b is not hero]
        front = min(others, key=lambda b: b[0]) if others else None
        out = []
        # v14.340: 左侧大胸像作为"锁脸"参考单独裁出(脸部/发型/配饰近景);
        # 正面全身立绘作为"锁服装鞋帽"参考。两张同角色, 纪律块已声明为同一人的多视图,
        # 不会被当成第二个人。胸像右缘以背景间隙为硬边界, 不卷入立绘残肢。
        bust_t = _crop_tensor(hero, bust=True)
        if bust_t is not None:
            out.append(bust_t)
        if front is not None:
            # 找胸像条带右侧最近的背景间隙列: 胸像右缘常越出条带边界,
            # 以背景间隙为硬边界, 立绘裁切框不纳入胸像边缘/肩带残肢。
            hx1 = hero[1]
            lb = hx1
            for x in range(hx1, front[0]):
                if clean[x] and col[x] < 0.05:
                    lb = x
                    break
            full_t = _crop_tensor(front, bust=False, left_bound=lb)
            if full_t is not None:
                out.append(full_t)
        return out or None

    best = min(figs, key=lambda b: b[0])
    t = _crop_tensor(best, bust=False)
    return [t] if t is not None else None


def _single_subject_ref_crop(img):
    """v14.269: 把"多视图角色设定拼版"裁成单人参考张量列表，断掉第二个可复制的人形。

    实测 clip2 首帧并列两个一模一样的主播: @图1 是 5 视图设定板(左 1 张胸像 + 4 张
    全身立绘), 分镜正文写"身后陈列第二瓶同款产品@图3镜像对称排列", Ref2VA 就把设定板
    里现成的第二具立绘当成"第二个人"贴进画面 —— 文字纪律压不住图像里的现成人形。

    只在三个条件同时成立时才裁: 横幅(宽高比 ≥1.25)、浅色背景、≥3 条窄而立满高度的
    前景条带且其中至少 3 条宽度相近。双人/多人实拍参考图、场景图、产品图都会原样返回。

    v14.336: 取正面全身立绘作为参考, 脸部身份 + 服装/鞋帽全要素都在这一张里;
    避免胸像肩袖残肢被带进裁切框。
    v14.340: 在全身立绘之外, 额外把左侧大胸像作为锁脸参考一并返回(两张同角色)。

    返回 None 表示不是设定板、原样使用; 否则返回 (Tensor 或 list[Tensor], 立绘条数)。
    """
    try:
        if img is None or getattr(img, "ndim", 0) != 4:
            return None
        h, w = int(img.shape[1]), int(img.shape[2])
        if w / float(max(1, h)) < 1.25:
            return None
        split = _split_sheet_subjects(img)
        if not split:
            return None
        n_views = len(split)
        if len(split) == 1:
            return split[0], n_views
        return split, n_views
    except Exception:
        return None


def _bsai_sheet_crop_v378(img):
    """v14.378: 用确定性几何定位「角色设定拼版」的正面立绘（见 bsai_ref_sheet.py）。

    实测 @图1 是 5 联设定板（1 张胸像特写 + 正面 / 侧面 / 背面 / 背面 4 具全身立绘）。
    Ref2VA 会把板子里**所有**人形当成可复制素材：clip1 首帧同时贴出两个人，中段
    又把"背面立绘"当成朝镜头走来的那一个 —— 人物背对镜头却逐秒变大，用户看到的就是
    「从头到尾倒着走」。文字纪律压不住图像里的现成人形，只能在参考源头把侧/背立绘
    切掉，只把「胸像(锁脸) + 正面全身立绘」喂进去。

    v14.269 的启发式在这张板上失效：胸像与正面立绘挨在一起被并成一段，于是取到的是
    侧面立绘；同时它把场景图（故宫拱墙）误判成 2 具视图并裁掉一半。这里换成按
    "≥2 条等高窄段 + 1 条宽段 + 宽段右缘开窗"的确定性判别。

    返回 None 表示不是设定板（调用方继续走原逻辑）。
    """
    try:
        import bsai_ref_sheet as _rs378
    except Exception:
        # ComfyUI 不一定把本插件目录放进 sys.path -> 兜底按同目录文件加载
        try:
            import importlib.util as _ilu378
            _p378 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bsai_ref_sheet.py")
            _spec378 = _ilu378.spec_from_file_location("bsai_ref_sheet_local", _p378)
            _rs378 = _ilu378.module_from_spec(_spec378)
            _spec378.loader.exec_module(_rs378)
        except Exception:
            return None
    try:
        import numpy as _np378
        if hasattr(img, "detach"):
            _arr = img[0].detach().float().cpu().numpy()
        else:
            _arr = _np378.asarray(img)
        if _arr.ndim == 3 and _arr.shape[2] == 4:
            _arr = _arr[..., :3]
        _pan = _rs378.locate_sheet_panels(_arr)
        if not _pan:
            return None
        _parts = []
        if _pan.get("bust"):
            _bx0, _by0, _bx1, _by1 = _pan["bust"]
            _parts.append(img[:, int(_by0):int(_by1), int(_bx0):int(_bx1), :])
        _fx0, _fy0, _fx1, _fy1 = _pan["front"]
        _parts.append(img[:, int(_fy0):int(_fy1), int(_fx0):int(_fx1), :])
        print(f"[H3 Extender] v14.378 角色设定拼版: 认到 {_pan['views']} 具视图 -> "
              f"只取『正面立绘』x {_fx0}-{_fx1}({_fx1 - _fx0}x{_fy1 - _fy0})"
              f"{' + 胸像(锁脸)' if _pan.get('bust') else ''}; "
              f"侧面/背面立绘已丢弃(它们是倒着走的来源)")
        return _parts
    except Exception as _e378:
        print(f"[H3 Extender] v14.378 角色拼版切版跳过: {_e378}")
        return None


def _refs_from_project_payload(project_payload):
    extender = project_payload.get("extender", {}) if isinstance(project_payload, dict) else {}
    raw = extender.get("refs_json") if isinstance(extender, dict) else None
    if not raw:
        settings = extender.get("settings", {}) if isinstance(extender, dict) else {}
        raw = settings.get("refs_json") if isinstance(settings, dict) else None
    if not raw and isinstance(extender, dict) and isinstance(extender.get("references"), list):
        raw = {"version": REFS_JSON_VERSION, "refs": extender.get("references")}
    return _parse_refs_json(raw)


def _write_refs_to_project_payload(project_payload, refs):
    refs = _normalize_ref_descriptors(refs)
    extender = project_payload.setdefault("extender", {})
    raw = _refs_json(refs)
    extender["refs_json"] = raw
    extender["references"] = copy.deepcopy(refs)
    settings = extender.setdefault("settings", {})
    if isinstance(settings, dict):
        settings["refs_json"] = raw
    return refs


def _reference_dimensions(ref):
    if ref is None:
        return None
    if isinstance(ref, dict):
        try:
            width = int(ref.get("width", 0) or 0)
            height = int(ref.get("height", 0) or 0)
        except Exception:
            return None
        if width > 0 and height > 0:
            return width, height
        path = _ref_path(ref.get("id"))
        if path.exists():
            width, height = _validate_reference_file(path)
            ref["width"] = int(width)
            ref["height"] = int(height)
            return width, height
        return None
    if getattr(ref, "ndim", 0) >= 4:
        return int(ref.shape[2]), int(ref.shape[1])
    return None


def _select_resolution_guide(refs):
    """Ref 1 wins; otherwise the first available internal reference wins."""
    if refs and refs[0] is not None:
        return 1, refs[0]
    for index, image in enumerate(refs or [], start=1):
        if image is not None:
            return index, image
    return None, None


def _clip_asset_fp(paths):
    """v1.99: per-clip 资产指纹——依赖图路径 + 文件 mtime + size。
    路径或文件内容(替换同名图)变化 -> 指纹变 -> 仅该 clip 重渲。"""
    paths = list(paths or [])
    if not paths:
        return ""
    parts = []
    for _p in paths:
        try:
            _st = os.stat(_p)
            parts.append("{}|{}|{}".format(_p, int(_st.st_mtime), int(_st.st_size)))
        except Exception:
            parts.append(str(_p))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _resolve_generation_resolution(resolution_mode, megapixels, width, height, refs):
    manual_w, manual_h = _manual_effective_resolution(width, height)
    mode = str(resolution_mode or "auto_from_ref")
    if mode == "manual":
        return {
            "width": manual_w,
            "height": manual_h,
            "mode": "manual",
            "guide_ref": None,
            "guide_src_width": 0,
            "guide_src_height": 0,
            "fallback": False,
            "megapixels": float(megapixels),
        }

    guide_index, guide = _select_resolution_guide(refs)
    dims = _reference_dimensions(guide) if guide is not None else None
    if guide is None or dims is None:
        return {
            "width": manual_w,
            "height": manual_h,
            "mode": "manual_fallback",
            "guide_ref": None,
            "guide_src_width": 0,
            "guide_src_height": 0,
            "fallback": True,
            "megapixels": float(megapixels),
        }

    src_w, src_h = dims
    resolved_w, resolved_h = _auto_resolution_from_dimensions(src_w, src_h, megapixels)
    return {
        "width": resolved_w,
        "height": resolved_h,
        "mode": "auto_from_ref",
        "guide_ref": int(guide_index),
        "guide_src_width": int(src_w),
        "guide_src_height": int(src_h),
        "fallback": False,
        "megapixels": float(megapixels),
    }

def _resolution_from_manifest(manifest):
    if not isinstance(manifest, dict):
        return None
    geom = manifest.get("geometry")
    if not isinstance(geom, dict):
        return None
    try:
        w = int(geom.get("video_w", 0)) * 16
        h = int(geom.get("video_h", 0)) * 16
    except Exception:
        return None
    if w <= 0 or h <= 0:
        return None
    return {"width": w, "height": h}


def _resize(image, width: int, height: int):
    samples = image[..., :3].movedim(-1, 1)
    samples = comfy.utils.common_upscale(
        samples, int(width), int(height), "lanczos", "disabled"
    )
    return samples.movedim(1, -1)


def _encode_ref_audio(audio_vae, audio):
    """Encode one standalone Ref2VA audio reference exactly like ComfyUI native H3."""
    waveform = audio["waveform"]  # [B, C, L]
    sr = int(audio["sample_rate"])
    vae_sr = int(getattr(audio_vae, "audio_sample_rate", 32000))
    if sr != vae_sr:
        waveform = torchaudio.functional.resample(waveform, sr, vae_sr)
    latent = audio_vae.encode(waveform[:1].movedim(1, -1))  # [1, 32, 2, T]
    return latent, int(latent.shape[-1])


def _prepare_shared_refs(
    vae,
    audio_vae,
    width: int,
    height: int,
    ref_image_size: str,
    refs,
    ref_audio=None,
):
    """Encode shared Ref2VA image refs plus one optional standalone audio ref.

    Ref slots are stable logical identities. Native H3 numbers only the active
    images contiguously, so we also return the logical slot order and remap
    <Picture N> tags just before tokenization. This lets Ref 3 stay Ref 3 even
    when Ref 2 is empty, without feeding a fake placeholder image to the model.
    """
    active = [
        (slot, image)
        for slot, image in enumerate(refs, start=1)
        if image is not None
    ]

    ref_items = []
    ref_blocks = []
    active_picture_slots = []

    def _encode_one(img, slot):
        h, w = int(img.shape[1]), int(img.shape[2])
        if ref_image_size == "match":
            scale = min(1.0, math.sqrt((int(width) * int(height)) / float(w * h)))
        elif ref_image_size in ("half", "half (4合1加速)"):
            # v14.234: 4合1 加速 —— 参考输入在 max(短边 768) 基础上再降 50%
            # (面积 -75%): VAE 编码与生成参考数据处理大减, 保留动作/轮廓
            # (B站 BV1WWxT6cEdY 方案③ 参考输入降分)。
            scale = min(1.0, REF_IMAGE_SHORT_EDGE / float(min(w, h))) * 0.5
        else:
            scale = min(1.0, REF_IMAGE_SHORT_EDGE / float(min(w, h)))

        tw = max(
            CANVAS_MULTIPLE,
            round(w * scale / CANVAS_MULTIPLE) * CANVAS_MULTIPLE,
        )
        th = max(
            CANVAS_MULTIPLE,
            round(h * scale / CANVAS_MULTIPLE) * CANVAS_MULTIPLE,
        )

        resized = _resize(img[:1], tw, th)
        z = vae.encode(resized)
        ref_items.append({"type": "image", "data": resized})
        active_picture_slots.append(int(slot))
        ref_blocks.append(
            {
                "kind": "image",
                "latent_h": th // 16,
                "latent_w": tw // 16,
                "latent": z,
            }
        )

    for slot, ref in active:
        img = _load_reference_tensor(ref) if isinstance(ref, dict) else ref
        # v14.378: 先用确定性切版器把「角色设定拼版」切成 胸像(锁脸) + 正面立绘。
        # 这一步是「人物倒着走」的根治点：拼版里的侧面/背面立绘一旦进了 Ref2VA，
        # 模型就会把背面那具当成朝镜头走来的她，于是背对镜头逐秒变大。
        _parts_v378 = _bsai_sheet_crop_v378(img)
        if _parts_v378:
            for part in _parts_v378:
                _encode_one(part, slot)
            continue
        # v14.269: 多视图设定拼版只保留单人立绘(否则模型会把第二具立绘当第二个人)。
        # v14.336: 取正面全身立绘作为参考, 脸部身份 + 服装/鞋帽全要素都在这一张里;
        # 不再只裁左侧大胸像, 避免下装/袜子/鞋在参考源头缺失。
        # v14.378: 这条旧启发式只用于角色槽(第 1 张参考); 场景/产品参考图原样使用 ——
        # 实测它会把故宫拱墙误判成"2 具视图"并裁掉一半, 破坏场景参考。
        _allow_legacy_crop = False
        try:
            _allow_legacy_crop = (int(slot) == 1)
        except Exception:
            _allow_legacy_crop = False
        _crop = _single_subject_ref_crop(img) if _allow_legacy_crop else None
        if _crop is not None:
            cropped, _n_views = _crop
            if isinstance(cropped, list):
                parts = cropped
            else:
                parts = [cropped]
            print(f"[H3 Extender] v14.269 参考图 {slot} 是多视图设定拼版({_n_views} 具视图) "
                  f"-> 拆成 {len(parts)} 张单人参考编码")
            # v14.347: 丢掉"窄条"裁片 —— 拼版切分有时会切出一条 192x768 这类
            # 宽高比 <0.35 的碎片, 它给不出身份(脸/服装都不完整), 反而稀释参考
            # 权重。至少留一张, 全被丢掉时保持原样。
            if len(parts) > 1:
                _kept = [p for p in parts
                         if (float(p.shape[2]) / max(1.0, float(p.shape[1]))) >= 0.35]
                if _kept and len(_kept) != len(parts):
                    print(f"[H3 Extender] v14.347 丢弃 {len(parts) - len(_kept)} 张过窄裁片"
                          f"(宽高比 <0.35, 身份信息不足); 保留 {len(_kept)} 张")
                    parts = _kept
            for part in parts:
                _encode_one(part, slot)
        else:
            _encode_one(img, slot)

    # Official Ref2VA presentation order is images first, then standalone audio.
    # The tokenizer assigns the standalone input the prompt label <Audio 1>.
    if ref_audio is not None:
        if audio_vae is None:
            raise ValueError(
                "MiniMax H3 Extender: ref_audio is connected but audio_vae is not. "
                "Connect the MiniMax H3 Audio VAE to audio_vae."
            )
        if not active:
            raise ValueError(
                "MiniMax H3 Extender: MiniMax H3 Ref2VA requires an audio "
                "reference to be used together with at least one image reference."
            )
        audio_latent, ref_audio_t = _encode_ref_audio(audio_vae, ref_audio)
        ref_items.append({"type": "audio"})
        ref_blocks.append(
            {
                "kind": "audio",
                "ref_audio_t": int(ref_audio_t),
                "audio_latent": audio_latent,
            }
        )

    return ref_items, ref_blocks, active_picture_slots


# ---------------------------------------------------------------------------
# v1.8 Ref2VA conditioning disk cache (CLIPCached-style, 2026-09).
# Image-reference VAE latents are content-addressed by ref hash + output size
# + ref_image_size. Re-running identical refs (new prompt / new seed) skips
# the repeated multi-image 2K VAE encode. Audio refs are re-encoded fresh.
# ---------------------------------------------------------------------------
_REF2VA_CACHE_DIRNAME = "_ref2va_cache"


def _ref2va_cache_key(vae, width, height, ref_image_size, refs, cache_bias=""):
    sig = _refs_signature(refs)
    vae_tag = vae.__class__.__name__ if vae is not None else "novae"
    try:
        vae_tag += ":" + str(getattr(vae, "model_name", "") or "")
    except Exception:
        pass
    # v1.26: 缓存key必须包含REF_IMAGE_SHORT_EDGE——此前key不含该常量，
    # 改短边从2048降到1024后key不变，仍命中旧缓存(2048短边)跳过resize，
    # 导致1024短边修复完全不生效，clip[1] TE编码继续OOM。
    # v1.27: cache_bias 携带 @图N 资产图片路径签名——资产库更换后 key 变化，
    # 否则张量 refs 的 _refs_signature 恒定，ref2va 命中旧资产 VAE 编码。
    # v14.269: "|s1" = 多视图设定拼版裁单人立绘(见 _single_subject_ref_crop)。
    # v14.340: "|s2" = 胸像(锁脸)+全身(锁服装鞋帽)双参考; 旧 s1 缓存必须失效。
    # v14.378: "|s3" = 确定性切版器(v14.378)取正面立绘; 旧 s2 缓存是"未裁切/取到侧立绘"
    # 的版本, 不失效等于新裁切逻辑完全没生效 —— 必须换 key。
    # 旧 key 的缓存是未裁剪/单立绘版本, 必须失效, 否则裁图逻辑等于没生效。
    raw = f"r2v|s3|{sig}|{int(width)}x{int(height)}|{str(ref_image_size)}|se{REF_IMAGE_SHORT_EDGE}|{vae_tag}|b{cache_bias}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:40]


def _ref2va_cache_path(key):
    root = _ensure_cache_root() / _REF2VA_CACHE_DIRNAME
    root.mkdir(parents=True, exist_ok=True)
    return root / (key + ".pt")


def _ref2va_cache_load(key):
    path = _ref2va_cache_path(key)
    if not path.exists():
        return None
    try:
        data = torch.load(path, map_location=comfy.model_management.intermediate_device())
        if isinstance(data, dict) and "items" in data and "blocks" in data and "slots" in data:
            return data
    except Exception as _e:
        print(f"[H3 Extender] ref2va cache load failed, will re-encode: {_e}")
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
    return None


def _ref2va_cache_save(key, items, blocks, slots):
    path = _ref2va_cache_path(key)
    tmp = path.with_suffix(".tmp")
    try:
        torch.save({"items": items, "blocks": blocks, "slots": slots}, tmp)
        os.replace(tmp, path)
    except Exception as _e:
        print(f"[H3 Extender] ref2va cache save failed (will re-encode next time): {_e}")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _prepare_shared_refs_cached(
    vae,
    audio_vae,
    width,
    height,
    ref_image_size,
    refs,
    ref_audio=None,
    enable_cache=True,
    cache_bias="",
):
    """_prepare_shared_refs + disk cache for image-reference VAE latents."""
    if not enable_cache or not any(r is not None for r in refs or []):
        items, blocks, slots = _prepare_shared_refs(
            vae, audio_vae, width, height, ref_image_size, refs, ref_audio=ref_audio
        )
        return items, blocks, slots, False

    key = _ref2va_cache_key(vae, width, height, ref_image_size, refs, cache_bias=cache_bias)
    cached = _ref2va_cache_load(key)
    if cached is not None:
        items = list(cached["items"])
        blocks = list(cached["blocks"])
        slots = list(cached["slots"])
        if ref_audio is not None:
            if audio_vae is None:
                raise ValueError(
                    "MiniMax H3 Extender: ref_audio is connected but audio_vae is not. "
                    "Connect the MiniMax H3 Audio VAE to audio_vae."
                )
            if not items:
                raise ValueError(
                    "MiniMax H3 Extender: MiniMax H3 Ref2VA requires an audio "
                    "reference to be used together with at least one image reference."
                )
            audio_latent, ref_audio_t = _encode_ref_audio(audio_vae, ref_audio)
            items = items + [{"type": "audio"}]
            blocks = blocks + [
                {"kind": "audio", "ref_audio_t": int(ref_audio_t), "audio_latent": audio_latent}
            ]
        print(f"[H3 Extender] ref2va image cache HIT ({len(items)} ref_items) - skipped VAE encode")
        return items, blocks, slots, True

    items, blocks, slots = _prepare_shared_refs(
        vae, audio_vae, width, height, ref_image_size, refs, ref_audio=ref_audio
    )
    img_items = [it for it in items if it.get("type") == "image"]
    img_blocks = [b for b in blocks if b.get("kind") == "image"]
    _ref2va_cache_save(key, img_items, img_blocks, slots)
    print(f"[H3 Extender] ref2va cache MISS - encoded & saved ({len(img_items)} image refs)")
    return items, blocks, slots, False


_PICTURE_TAG_RE = re.compile(r"<Picture\s+(\d+)>", re.IGNORECASE)

_ARCHIVE_SECTION_RE = re.compile(r"^\s*\[[^\[\]\n]*档案[^\[\]\n]*\]", re.MULTILINE)


_MOUTH_CLOSED_RE = re.compile(r"(?:不开口|嘴唇闭合|双唇紧闭|闭嘴|不发声|闭口不言|口型不动)")


def _strip_singing_talk_descriptions(text):
    """lip_audio 模式下音频锁死口型, 分镜正文里的"闭嘴"类指令必须删除。

    v14.269: 实测 clip1 3-6s 分镜写的是"按照 lip_voice 对口型开口说话", 模型
    却闭嘴静止; 同一段分镜其它拍段写着"主播@图1不开口，嘴唇闭合"。音频
    (audio_denoise=0) 已经锁死口型, 任何"闭嘴/不开口"文字都是与 <Audio 1>
    直接冲突的指令, 模型会在拍段边界上选择出错的一边。所以: 口型状态只能由
    音频决定, 正文只保留画面描述, 不保留任何嘴部开合指令。

    按分句删除整条含闭嘴指令的分句(而不是替换词), 避免留下"此，"这类残字。
    """
    if not text:
        return ""
    out = []
    for seg in re.split(r"([，,；;。\n])", str(text)):
        if _MOUTH_CLOSED_RE.search(seg):
            continue
        out.append(seg)
    cleaned = "".join(out)
    cleaned = re.sub(r"[，,；;]{2,}", "，", cleaned)
    cleaned = re.sub(r"(?:。|；|;)\s*[，,]+\s*", r"。", cleaned)
    cleaned = re.sub(r"[，,；;]\s*(?=[。\n])", "", cleaned)
    return cleaned


def _strip_archive_sections(text):
    """Remove [角色档案]/[道具档案]/[场景档案] sections (heading plus their
    item lines) from a global prompt. Those character/prop/scene inventories
    must never leak into a CLIP's render prompt — otherwise the model draws
    every listed character and scene in every card. Other sections (e.g.
    [整体风格]) are kept as pure text style, without any picture refs."""
    if not text:
        return ""
    lines = str(text).splitlines()
    out = []
    skipping = False
    for ln in lines:
        if _ARCHIVE_SECTION_RE.match(ln):
            skipping = True
            continue
        if skipping:
            # A new bracket section ends the skipped archive block. Plain item
            # lines (e.g. "凌薇@图1，...") stay inside the skipped block.
            if re.match(r"^\s*\[", ln):
                skipping = False
            else:
                continue
        out.append(ln)
    return "\n".join(out).strip()


def _remap_picture_tags(prompt: str, active_picture_slots):
    """Map stable UI Ref slots to H3's contiguous active Picture ordinals."""
    slot_to_ordinal = {
        int(slot): ordinal
        for ordinal, slot in enumerate(active_picture_slots or [], start=1)
    }

    def replace(match):
        slot = int(match.group(1))
        if slot < 1 or slot > MAX_IMAGE_REFS:
            return match.group(0)
        ordinal = slot_to_ordinal.get(slot)
        # Do not police the user's prompt. An empty logical slot may be an
        # accidental reference or an intentional use of native H3 numbering.
        # In that case leave the tag exactly as written and let H3 interpret it.
        if ordinal is None:
            return match.group(0)
        return f"<Picture {ordinal}>"

    return _PICTURE_TAG_RE.sub(replace, str(prompt))


def _make_ref2va_conditioning(
    clip,
    vae,
    prompt: str,
    width: int,
    height: int,
    frame_count: int,
    ref_items,
    ref_blocks,
    active_picture_slots,
    semantic_bridge_pack=None,
):
    latent = _empty_av_latent(width, height, frame_count)
    resolved_prompt = _remap_picture_tags(prompt, active_picture_slots)
    print(f"[H3 Extender] _make_ref2va_conditioning: prompt='{resolved_prompt[:100]}'")
    print(f"[H3 Extender]   ref_items={len(ref_items) if ref_items else 0}, "
          f"ref_blocks={len(ref_blocks) if ref_blocks else 0}, "
          f"active_picture_slots={active_picture_slots}")
    if ref_items:
        for ri, item in enumerate(ref_items):
            if isinstance(item, dict):
                data = item.get("data")
                shape = tuple(data.shape) if data is not None and hasattr(data, 'shape') else None
                print(f"[H3 Extender]   ref_item[{ri}]: type={item.get('type')}, data_shape={shape}")
    tokens = clip.tokenize(resolved_prompt, minimax_ref_items=ref_items)
    # v1.23: TE 文本编码回到 GPU 且独占显存——编码前把其他已加载模型（尤其 H3 主模型）
    # 的权重强制移回 CPU（partially_unload(offload, 1e32) 才是真正释放显存的路径；
    # unload_all_models 走 detach 分支不释放 dynamic 显存，此前 OOM 根因）。编码完 TE 自动让位，采样时 H3 按需重载。
    try:
        import gc as _gc
        _gc.collect()
        import comfy.model_management as _cmm
        _cmm.cleanup_models_gc()
        # v2.121 (round4): TE 编码期间 ComfyUI 内部 free_memory 会扫描 current_loaded_models
        # 腾显存。若量化 DiT/delegate 仍在列表里(哪怕 loaded_size<1MB), 内部路径会走
        # detach->unpatch_model->to(cpu) 触发 comfy_kitchen _handle_to 原生 access violation。
        # 修复: 对所有带 ck 量化权重的模型, 一律直接从 current_loaded_models 摘除,
        # 不走 partially_unload(二采 delegate 与 DiT 共享权重, partially_unload 卸不干净),
        # 摘完 gc+empty_cache 让 GPU 权重物理回收。这样 ComfyUI 内部 free_memory 扫不到量化模型。
        for _lm in list(_cmm.current_loaded_models):
            try:
                if _lm.model is getattr(clip, "patcher", None):
                    continue
                if _mp_has_ck_quant_weights(_lm.model):
                    try:
                        _cmm.current_loaded_models.remove(_lm)
                    except Exception:
                        pass
                    continue
                _lm.model.partially_unload(_lm.model.offload_device, 1e32)
            except Exception:
                pass
        _gc.collect()
        _cmm.soft_empty_cache(force=True)
    except Exception:
        pass
    # v1.24: TE 计算临时切 bf16——ComfyUI sd1_clip forward 把 dtype hardcode 为 float32，
    # 导致 TE 编码峰值 ~22GB，在 24GB 卡（扣 reserve 后 ~22.3GB 可用）上贴边 OOM。
    # H3 主模型本身就是 bf16，TE 嵌入用 bf16 精度匹配且显存减半，编码后恢复原 forward。
    _te_bf16_patched = False
    _orig_tf_forward = None
    _tf_target = None
    try:
        _csm = getattr(clip, "cond_stage_model", None)
        _tf = getattr(_csm, "transformer", None) if _csm is not None else None
        if _tf is not None and hasattr(_tf, "forward"):
            _orig_tf_forward = _tf.forward
            _tf_target = _tf
            def _bf16_tf_forward(*args, **kwargs):
                kwargs["dtype"] = torch.bfloat16
                return _orig_tf_forward(*args, **kwargs)
            _tf.forward = _bf16_tf_forward
            _te_bf16_patched = True
    except Exception:
        _te_bf16_patched = False
    # v1.25: 编码前最后清一次 CUDA 缓存——clip[0] 渲染+解码后 cudaMallocAsync 池有碎片，
    # TE 编码需要大块连续内存（causal_mask N×N），碎片会导致 allocated 很低但 free=0 的伪 OOM。
    # v1.28: 加强为 reset_peak_memory_stats + 双轮 synchronize/empty_cache，配合启动脚本
    # PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True 根治 cudaMallocAsync 碎片。
    # v1.29: 加 ipc_collect() 清理 IPC 共享内存段；TE 是 ModelPatcherDynamic（VBAR），
    # 绕过 cudaMallocAsync 池，需尽可能清理所有可能占用虚拟地址空间的残留。
    try:
        import torch as _torch
        _torch.cuda.synchronize()
        _torch.cuda.empty_cache()
        _torch.cuda.ipc_collect()
        _torch.cuda.reset_peak_memory_stats()
        _torch.cuda.synchronize()
        _torch.cuda.empty_cache()
    except Exception:
        pass
    try:
        cond = clip.encode_from_tokens_scheduled(tokens)
    finally:
        if _te_bf16_patched and _tf_target is not None and _orig_tf_forward is not None:
            try:
                _tf_target.forward = _orig_tf_forward
            except Exception:
                pass
        # v1.27: TE编码完成后立即释放TE模型——参考MiniMaxH3 Director的vram_cleanup方案，
        # TE是普通ModelPatcher（非dynamic），unload_all_models+cleanup_models可真正释放TE权重显存，
        # 让H3主模型采样时独占GPU，避免TE驻留与H3加载竞争导致OOM。
        try:
            import gc as _gc2
            _gc2.collect()
            import comfy.model_management as _cmm2
            _cmm2.cleanup_models_gc()
            # v1.49: TE 是 ModelPatcherDynamic(VBAR), unload_all_models() 走 detach 分支
            # 不释放 VBAR 显存(同 :1386-1387 自证)。实测 TE 11.7GB 常驻不松, 导致 21.8GB
            # DiT 只能流式(89s/it)。改为对所有已加载模型(含 TE 自身, 不跳过 clip.patcher)
            # 走 partially_unload(offload_device, 1e32) VBAR 真释放路径, 再 unload_all + 空缓存。
            # 二采复用已编码 conditioning(不重 encode), 此处卸 TE 不影响二采/VAE/3D upscaler。
            for _lm2 in list(_cmm2.current_loaded_models):
                try:
                    if _mp_has_ck_quant_weights(_lm2.model):
                        continue
                    _lm2.model.partially_unload(_lm2.model.offload_device, 1e32)
                except Exception:
                    pass
            # v2.120b (round3): 崩溃链 extender.py:1938 -> unload_all_models()->
            # free_memory(1e30)->model_unload->detach->unpatch_model->self.model.to(cpu),
            # 对 GPU 驻留量化块触发 comfy_kitchen _handle_to 原生 access violation
            # (clip16→17 复现; 前 15 clip 未崩只因 DiT 恰好被 TE/VAE 加载挤成全 CPU)。
            # 改为 free_memory(..., for_dynamic=True): 动态模型(量化 DiT)memory_to_free=0
            # 跳过、不 detach, 非动态 TE/VAE 正常卸载, 量化权重不再走 GPU→CPU 拷贝。
            try:
                _cmm2.free_memory(1e30, _cmm2.get_torch_device(), for_dynamic=True)
            except Exception:
                pass
            _cmm2.cleanup_models()
            _cmm2.soft_empty_cache(force=True)
            import torch as _torch2
            _torch2.cuda.synchronize()
            _torch2.cuda.empty_cache()
            _torch2.cuda.ipc_collect()
        except Exception:
            pass
        # v1.53: ComfyUI 的 unload 只把权重移回 CPU RAM（current_loaded_models 保留引用，
        # 物理内存不释放）。TE 15GB + DiT 21.8GB + VAE 驻留会把系统物理内存顶满，
        # cudaHostRegister 锁页注册失败 → "Pin error." 刷屏 + offload 换页拖慢。
        # 配合 bat --cache-none（禁用节点结果缓存，消除 CLIPLoader 输出对 clip 的跨轮持有），
        # 此处把 TE 从 current_loaded_models 摘除，函数返回后 clip 引用归零，gc 真正释放 ~15GB RAM。
        try:
            import gc as _gc53
            import comfy.model_management as _cmm53
            _te_patcher53 = getattr(clip, "patcher", None)
            for _lm53 in list(_cmm53.current_loaded_models):
                try:
                    if _lm53.model is _te_patcher53:
                        _cmm53.current_loaded_models.remove(_lm53)
                except Exception:
                    pass
            _gc53.collect()
        except Exception:
            pass
        try:
            import torch as _torch
            _torch.cuda.synchronize()
        except Exception:
            pass
    if ref_blocks:
        cond = node_helpers.conditioning_set_values(
            cond, {"minimax_refs": ref_blocks}
        )
        print(f"[H3 Extender]   conditioning set with {len(ref_blocks)} minimax_refs blocks")
    else:
        print("[H3 Extender]   WARNING: no ref_blocks, conditioning has NO minimax_refs!")
    # v2.19 Semantic-Bridge: 可开可关(默认关). 对 cond[0][0] token 张量做小 MLP 残差混合.
    if isinstance(semantic_bridge_pack, dict) and semantic_bridge_pack.get("enabled"):
        try:
            import os as _os_sb, importlib.util as _ilu_sb
            _sb_path = _os_sb.path.join(_os_sb.path.dirname(_os_sb.path.abspath(__file__)),
                                        "bsai_h3_semantic_bridge.py")
            _sb_spec = _ilu_sb.spec_from_file_location("bsai_h3_semantic_bridge", _sb_path)
            _sb = _ilu_sb.module_from_spec(_sb_spec)
            _sb_spec.loader.exec_module(_sb)
            cond, _sb_note = _sb.apply(
                cond,
                semantic_bridge_pack.get("adapter", ""),
                float(semantic_bridge_pack.get("alpha", 0.15)),
                bool(semantic_bridge_pack.get("magnitude_match", True)),
            )
            if _sb_note:
                print(f"[H3 Extender]   {_sb_note}")
        except Exception as _sb_err:
            print(f"[H3 Extender]   Semantic Bridge 加载失败(忽略, 按无桥继续): {_sb_err}")
    return cond, latent


class _BasicGuider(comfy.samplers.CFGGuider):
    def set_conds(self, positive):
        self.inner_set_conds({"positive": positive})

    # v1.52: 不再覆写 outer_sample. force_full_load=True 把 21.8GB 全拉满会在
    # process_conds 阶段 OOM (23.86GB 物理上限). 改由 EXTRA_RESERVED_VRAM 抬到 ~5.5GB,
    # 让 ComfyUI 自动把权重驻留预算压到 ~16GB, 尾部 ~5.8GB offload, 留 ~6GB 给 conds/workspace.


# ============================================================
# P0 (2026-10-17): 官方双轨迹采样 —— MiniMaxH3SigmaShift 等效注入
#   video shift 驱动采样器 sigma 调度 (ModelSamplingAV + CONST),
#   audio schedule 由模型 forward 内部从共享 base grid 推导.
#   与 comfy_extras.nodes_minimax_h3.MiniMaxH3SigmaShift 实现一致, 幂等.
# ============================================================
def _apply_h3_dual_track_shift(model, shift_video, shift_audio):
    if model is None:
        return model
    try:
        # v14.152: shift_audio 可为 None（老工作流 0.0 的映射）→ 关闭音频 shift
        _sa = None if shift_audio is None else float(shift_audio)
        to = model.model_options.get("transformer_options", {}) or {}
        if (to.get("minimax_h3_sigma_shift_video") == float(shift_video)
                and to.get("minimax_h3_sigma_shift_audio") == _sa
                and model.model_options.get("_bsai_dual_track_applied")):
            return model  # 幂等: 已注入同值 shift
        import comfy.model_sampling as _cms
        m = model.clone()
        class _MSAV(_cms.ModelSamplingAV, _cms.CONST):
            pass
        original = m.get_model_object("model_sampling")
        ms = _MSAV(m.model.model_config)
        ms.set_parameters(shift=float(shift_video), audio_shift=_sa)
        if hasattr(original, "noise_scale"):
            try:
                ms.set_noise_scale(original.noise_scale)
            except Exception:
                pass
        m.add_object_patch("model_sampling", ms)
        to2 = m.model_options.get("transformer_options", {}).copy()
        to2["minimax_h3_sigma_shift_video"] = float(shift_video)
        to2["minimax_h3_sigma_shift_audio"] = _sa
        m.model_options["transformer_options"] = to2
        m.model_options["_bsai_dual_track_applied"] = True
        print(f"[H3 Extender] P0 双轨迹采样注入: shift_video={shift_video} shift_audio={_sa}", flush=True)
        return m
    except Exception as _e:
        print(f"[H3 Extender] P0 双轨迹注入失败(回退原模型): {_e}", flush=True)
        return model


# ============================================================
# P2 (2026-10-17): SelfLift H3 TST 时间状态传输 —— 少步数画质补偿
#   arXiv:2609.08505, 校正 H3 视频时间不平衡(闪烁/身份漂移/不合理运动).
#   依赖 comfyui-SelfLift (facok) 已安装; 未安装自动跳过.
# ============================================================
def _apply_h3_tst(model, enable, tau):
    if model is None or not enable:
        return model
    try:
        import sys as _sys_tst, os as _os_tst, importlib.util as _ilu_tst
        _tst_patch = None
        _src_tag = None
        # v14.163 (2026-10-22): TST 内置化 —— 优先从插件自带 vendor/selflift_tst/h3_tst.py
        # 加载 (importlib 按文件加载, 不污染 sys.path), 粉丝无需再单独安装 comfyui-SelfLift。
        _builtin_tst = _os_tst.path.join(
            _os_tst.path.dirname(_os_tst.path.abspath(__file__)),
            "vendor", "selflift_tst", "h3_tst.py",
        )
        if _os_tst.path.isfile(_builtin_tst):
            try:
                _spec_tst = _ilu_tst.spec_from_file_location("bsai_selflift_tst", _builtin_tst)
                _mod_tst = _ilu_tst.module_from_spec(_spec_tst)
                _spec_tst.loader.exec_module(_mod_tst)
                _tst_patch = getattr(_mod_tst, "patch_model", None)
                _src_tag = "内置 vendor/selflift_tst"
            except Exception as _be:
                print(f"[H3 Extender] 内置 TST 加载失败(回退外部): {_be}", flush=True)
        # 回退: 外部 comfyui-SelfLift（双保险保留，兼容老用户既有安装）
        if _tst_patch is None:
            _sl_dir = _os_tst.path.join(
                _os_tst.path.dirname(_os_tst.path.dirname(_os_tst.path.abspath(__file__))),
                "comfyui-SelfLift",
            )
            if not _os_tst.path.isfile(_os_tst.path.join(_sl_dir, "h3_tst.py")):
                try:
                    _cn_roots = folder_paths.get_folder_paths("custom_nodes")
                    _sl_dir = _os_tst.path.join(_cn_roots[0], "comfyui-SelfLift")
                except Exception:
                    pass
            if _os_tst.path.isfile(_os_tst.path.join(_sl_dir, "h3_tst.py")):
                if _sl_dir not in _sys_tst.path:
                    _sys_tst.path.insert(0, _sl_dir)
                from h3_tst import patch_model as _tst_patch_ext
                _tst_patch = _tst_patch_ext
                _src_tag = "外部 comfyui-SelfLift"
            else:
                print(f"[H3 Extender] P2 TST 注入跳过: 内置 vendor 与外部 comfyui-SelfLift "
                      f"均未找到 h3_tst.py (内置 {_builtin_tst} / 外部 {_sl_dir})", flush=True)
                return model
        m = model.clone()
        patched = _tst_patch(m, float(tau), False)
        print(f"[H3 Extender] P2 SelfLift H3 TST 注入({_src_tag}): tau={tau}", flush=True)
        return patched
    except Exception as _e:
        print(f"[H3 Extender] P2 TST 注入失败(继续无补偿): {_e}", flush=True)
        return model


# Pika H3 Flex 官方 ManualSigmas 契约 (docs.comfy.org Pika H3 Flex FAQ, SGLang 实现):
# 固定 6 步的 sigma 结 1000/750/500/250/100/40, 加终点 0 共 7 值 —— 蒸馏训练就是
# 这条调度, 少一个值即破坏 schedule, 加步数也不涨细节。shift 由 model_sampling
# 内置 (video 12 / audio 3 经双轨迹 time_snr_shift)。
_PIKA_H3_SIGMA_KNOTS = (1000.0, 750.0, 500.0, 250.0, 100.0, 40.0, 0.0)

# v14.339 (2026-11-08): HyperFlow H3 Flash 固定少步 sigma 曲线。
# 官方 ComfyUI-HyperFlow-Flash/loader_nodes.py 的 RAW_SIGMAS 经 flow shift 12
# 预乘后的结果 (integrations/README.md 同时给出这组数值, 二者逐位一致)。
# 注意: 这是"已乘 shift"的最终调度, 不能再经 model_sampling 的 shift 映射一次。
_HYPERFLOW_H3_SIGMAS = {
    4: (1.0, 0.962575793, 0.755781889, 0.312497854, 0.0),
    6: (1.0, 0.982655942, 0.914642572, 0.674755692, 0.385223746, 0.159055322, 0.0),
    8: (1.0, 0.993909776, 0.9842875, 0.966063738, 0.923076928, 0.8349424, 0.696852028, 0.468753308, 0.0),
}


# v14.345 (2026-11-09): 第 36 档「Viggle Remake 视频改写」官方 6 步固定 sigma。
# 来源: Viggle/Viggle-Remake README —— 两组 timesteps(knots) 归一为 σ=t/1000,
# 与 simple/linspace 完全无关，必须原样喂入，否则 6 步蒸馏契约不成立。
_VIGGLE_REMAKE_SIGMAS = {
    "swap": (1.0, 0.990476, 0.965243, 0.923077, 0.8, 0.631579, 0.0),
    "edit": (1.0, 0.983607, 0.96, 0.923077, 0.857143, 0.705882, 0.0),
}


# v14.388 (2026-11-12): PDMD(DMD 系 4-NFE 学生) 的训练噪声边界(base_schedule)。
# 来源: MiniMax H3 的 DMD2 蒸馏元数据契约 —— `_minimax_h3.sigma_shift_scales` =
# {video 12.0, audio 3.0}, `base_schedule = [1.0, 0.7, 0.4, 0.15, 0.0]`(5 个连续
# 边界 = 4 个 NFE), 与 PDMD 模型卡的「4 步 + 底模发布版调度配置(shift 12/3)」一致。
# 这里是**未乘 shift 的 base 位置**(0..1000 的 timestep 写法, 交给 model_sampling
# 的 time_snr_shift 映射), 不能直接当 σ 用, 也不能交给 simple 等间距网格。
# v14.387 之前 PDMD 4 步档强改 scheduler="simple" —— simple 生成 u=linspace(1,0,5)
# = [1.0, 0.75, 0.5, 0.25, 0.0], 经 shift 12 映射成 σ=[1.0, 0.973, 0.9231, 0.8, 0.0]:
# 学生从未在这些噪声位置训练过, 末步还要从 σ=0.8 一次跳到 0 —— 实机结果就是整段纯
# 噪声(2026-11-12 12:41-13:27 六段全噪)。改成训练边界后 σ=[1.0, 0.96552, 0.88889,
# 0.67925, 0.0], 每一步都落在学生见过的位置上。
_PDMD_H3_SIGMA_KNOTS = (1000.0, 700.0, 400.0, 150.0, 0.0)


# v14.352/v14.353: 运行时标记（采样函数与硬切拦截要用）
_VIGGLE_ACTIVE = False          # 当前这一段是不是 Viggle 档
_VIGGLE_RELEASE_POS = None      # 只含参考图的 positive（σ 早停释放源片 cond 用）
_VIGGLE_RELEASE_UNTIL = 0.9     # σ 低于该值就释放源片 cond video block


def _viggle_resample_sigmas(knots, want_steps):
    """v14.354: 把官方 6 步固定 knots 重采样成 want_steps 步。

    官方 σ 表长度决定采样步数，前端 steps 在 viggle 档原本完全失效（恒 6 步）。
    want == 6 原样返回；< 6 只取原始 knots 的子集（不引入模型没见过的 σ）；
    > 6 在相邻 knots 间对 σ 做分段线性插值、首尾钉死、强制严格单调递减。
    """
    import torch as _t
    k = [float(x) for x in knots]
    seg = len(k) - 1
    want = max(2, int(want_steps or seg))
    if want == seg:
        return _t.tensor([float(x) for x in knots], dtype=_t.float32).cpu()
    if want < seg:
        out = [k[round(i * seg / want)] for i in range(want + 1)]
    else:
        out = []
        for i in range(want + 1):
            t = i / float(want)
            pos = t * seg
            lo = int(min(seg - 1, max(0, int(pos))))
            w = pos - lo
            out.append(k[lo] * (1.0 - w) + k[lo + 1] * w)
    out[0] = k[0]
    out[-1] = 0.0
    for i in range(1, len(out)):
        if out[i] > out[i - 1]:
            out[i] = out[i - 1]
        elif out[i] == out[i - 1] and i < len(out) - 1:
            out[i] = max(0.0, out[i - 1] - 1e-6)
    return _t.tensor(out, dtype=_t.float32).cpu()


def _viggle_faceswap_clip(in_path, model="128", ref_path=None, tag=""):
    """v14.354/v14.355: 出片后逐帧换脸（子进程跑 tools/viggle_faceswap.py）。

    渲染进程与换脸进程隔离，换脸崩了不影响已经渲好的视频：失败一律回退原片。
    """
    import subprocess
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        script = os.path.join(here, "tools", "viggle_faceswap.py")
        if not os.path.isfile(script):
            print(f"[H3 Viggle] v14.355 换脸脚本缺失: {script}")
            return str(in_path)
        out_path = str(in_path)[:-4] + "_faceswap.mp4"
        cmd = [sys.executable, script, str(in_path), out_path, "--model", str(model)]
        if ref_path:
            cmd += ["--ref", str(ref_path)]
        print(f"[H3 Viggle] v14.355 换脸工序开始 {tag}: model={model} -> {os.path.basename(out_path)}", flush=True)
        _t0 = __import__("time").time()
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0 or not os.path.isfile(out_path):
            tail = (r.stderr or r.stdout or "")[-400:]
            print(f"[H3 Viggle] v14.355 换脸失败(保留原片): rc={r.returncode} {tail}", flush=True)
            return str(in_path)
        print(f"[H3 Viggle] v14.355 换脸工序完成 {tag}: {os.path.basename(out_path)} "
              f"{round(os.path.getsize(out_path) / 1048576, 2)}MB "
              f"{(__import__('time').time() - _t0) / 60:.1f}min", flush=True)
        return out_path
    except Exception as e:
        print(f"[H3 Viggle] v14.355 换脸异常(保留原片): {type(e).__name__}: {e}", flush=True)
        return str(in_path)


def knots_symbol(k):
    """σ 表首点（1.0），保留给 _viggle_resample_sigmas 做符号锚定。"""
    return k[0] if k else 1.0


# v14.347: 第 35 档专用 —— "名义 denoise = 真实起点 σ" 的 sigma 切片开关。
# 为什么必须分开: `_sigmas()` 用的是"拉长 total_steps 再取末 N 步"的老 img2img 近似,
# 只有在 sigma 随 t 近似线性时才对得上 denoise。H3 (shift 12) 的 σ(t) 高端极平,
# 实测 steps=4/denoise=0.65 → σ0=0.9601, 等于"几乎整帧重生": 名义 0.62 的半重绘
# 实际从 ~0.93 起跑, 8 步根本去不干净 → 出片糊、身份被源片像素按住换不掉。
# 这里改为: 在密集 sigma 表上找到 σ ≈ denoise·σmax 的那个下标, 再从那里到 0
# 均匀取 steps 个点。只影响显式打开的档位(第 35 档), 不动其它档既有手感。
_SIGMAS_EXACT = False


def _sigmas_exact(model, scheduler: str, steps: int, denoise: float, tag: str = ""):
    """从 σ = denoise·σmax 起步、按给定步数走到 0 的 sigma 表（denoise 为真实噪声比例）。"""
    steps = max(1, int(steps))
    denoise = float(denoise)
    ms = model.get_model_object("model_sampling")
    dense_n = max(256, steps * 32)
    _dense = comfy.samplers.calculate_sigmas(ms, str(scheduler), dense_n).cpu()
    # 方向保险: 正常 schedule 是 σmax → 0 降序; 若拿到升序(某些自定义 model_sampling
    # 的 sigma 表方向相反), 直接翻转, 否则"找到第一个 ≤ target"会落在错误的一端。
    if float(_dense[0]) < float(_dense[-1]):
        _dense = torch.flip(_dense, dims=[0])
    _smax = float(_dense[0])
    _target = _smax * denoise
    _idx = None
    for _i in range(int(_dense.shape[0])):
        if float(_dense[_i]) <= _target:
            _idx = _i
            break
    if _idx is None:
        _idx = 0
    _tail = _dense[_idx:]
    _n = steps + 1
    if int(_tail.shape[0]) >= _n:
        _pos = torch.linspace(0, int(_tail.shape[0]) - 1, _n)
        _lo = _pos.floor().long()
        _hi = torch.clamp(_lo + 1, max=int(_tail.shape[0]) - 1)
        _w = (_pos - _lo.float())
        _sig = _tail[_lo] * (1.0 - _w) + _tail[_hi] * _w
    else:
        _sig = torch.cat([_tail, torch.zeros(_n - int(_tail.shape[0]))])
    # 首尾钉死: σ0 必须是真实起点(denoise·σmax)附近, 末尾必须 0
    _sig[-1] = 0.0
    _sig[0] = float(_dense[_idx])
    # 单调不增(取整可能产生重复点, 重复点会让采样器空转)
    for _i in range(1, int(_sig.shape[0])):
        if float(_sig[_i]) > float(_sig[_i - 1]):
            _sig[_i] = float(_sig[_i - 1])
        elif float(_sig[_i]) == float(_sig[_i - 1]) and _i < int(_sig.shape[0]) - 1:
            _sig[_i] = max(0.0, float(_sig[_i - 1]) - 1e-6)
    print(f"[H3 SigmaExact]{(' ' + tag) if tag else ''} denoise={denoise:.2f} steps={steps} "
          f"→ σ0={float(_sig[0]):.4f} (旧算法会从 σ≈{float(_dense[-(steps + 1)]):.4f} 起跑) "
          f"σ表={[round(float(v), 4) for v in _sig.tolist()]}", flush=True)
    return _sig


def _sigmas(model, scheduler: str, steps: int, denoise: float):
    steps = max(1, int(steps))
    denoise = float(denoise)
    if denoise <= 0.0:
        return torch.FloatTensor([])
    ms = model.get_model_object("model_sampling")
    if str(scheduler) in ("viggle_remake_swap_manual", "viggle_remake_edit_manual"):
        _vg_task = "edit" if "edit" in str(scheduler) else "swap"
        # v14.354: 前端 steps 在 viggle 档原本失效（σ 表长度决定步数，恒 6）。
        # 这里按目标步数重采样 σ 表；BSAI_H3_VIGGLE_STEPS 优先于前端。
        try:
            _vg_want = int(os.environ.get("BSAI_H3_VIGGLE_STEPS", "") or steps)
        except (TypeError, ValueError):
            _vg_want = 6
        _vg_sig = _viggle_resample_sigmas(_VIGGLE_REMAKE_SIGMAS[_vg_task], _vg_want)
        print(f"[H3 Extender] v14.354 sigma 曲线重采样: {_vg_task} 步数={len(_vg_sig) - 1} "
              f"σ={[round(float(v), 4) for v in _vg_sig.tolist()]}", flush=True)
        return _vg_sig
    if str(scheduler) == "pika_manual":
        # v14.366: 原实现直接返回 6 结固定 σ 表 —— 长度决定步数，前端 steps
        # 在该调度上完全失效（与 v14.354 之前的 viggle 档同病）。这里按目标
        # 步数重采样：6 步原样返回（保持官方契约不变），>6 步对 6 步轨迹做
        # 分段线性插值细分（首尾钉死 + 强制严格单调递减），<6 步只取子集。
        # **不要**换成 simple 等间距：那是蒸馏适配器没训练过的调度。
        _pk_sig = ms.sigma(torch.tensor(_PIKA_H3_SIGMA_KNOTS, dtype=torch.float32)).cpu()
        _pk_want = max(2, int(steps))
        if _pk_want != int(_pk_sig.shape[0]) - 1:
            _pk_sig = _viggle_resample_sigmas(_pk_sig, _pk_want)
            print(f"[H3 Extender] v14.366 PIKA sigma 重采样: 步数={_pk_want} "
                  f"σ={[round(float(v), 4) for v in _pk_sig.tolist()]}", flush=True)
        return _pk_sig
    if str(scheduler) == "hyperflow_manual":
        _hf_steps = steps if steps in _HYPERFLOW_H3_SIGMAS else 6
        return torch.tensor(_HYPERFLOW_H3_SIGMAS[_hf_steps], dtype=torch.float32).cpu()
    if str(scheduler) == "pdmd_manual":
        # v14.388: PDMD 4-NFE 学生的训练噪声边界, 经 model_sampling 的 shift(12/3) 映射。
        # 不能用 simple/linspace 等间距(那是蒸馏学生没训练过的调度, 会直接出噪声);
        # 加步数时在训练曲线的相邻边界间线性插值, 少步时只取子集, 不引入新位置。
        _pd = ms.sigma(torch.tensor(_PDMD_H3_SIGMA_KNOTS, dtype=torch.float32)).cpu()
        _pd_want = max(2, int(steps))
        if _pd_want != int(_pd.shape[0]) - 1:
            _pd = _viggle_resample_sigmas([float(v) for v in _pd.tolist()], _pd_want)
        print(f"[H3 Extender] v14.388 PDMD sigma 曲线(训练边界): 步数={int(_pd.shape[0]) - 1} "
              f"σ={[round(float(v), 5) for v in _pd.tolist()]}", flush=True)
        return _pd
    # v14.347: 第 35 档打开 exact 模式 —— denoise 就是真实起点噪声比例
    if _SIGMAS_EXACT and denoise < 1.0:
        try:
            return _sigmas_exact(model, str(scheduler), steps, denoise, tag=f"scheduler={scheduler}")
        except Exception as _sxe:
            print(f"[H3 SigmaExact] ⚠️ exact 失败, 回退旧算法: {_sxe}")
    total_steps = steps
    if denoise < 1.0:
        total_steps = max(steps, int(steps / denoise))
    sigmas = comfy.samplers.calculate_sigmas(
        ms,
        str(scheduler),
        total_steps,
    ).cpu()
    return sigmas[-(steps + 1):]


# ============================================================
# v14.238: MiniMaxH3 Director「一采/二采极速渲染」全套移植辅助函数。
# 参考插件例程 minimax_h3_director_二采_加速.json 的已验证契约:
#   一采 8 步(res_multistep+simple, shift 12/3, guidance 1.0) @ 0.4MP 低清画布
#     (864x480 @16:9) —— 低清草稿快定构图/形状/运动;
#   二采 H3 latent 3D 放大到目标画布(默认 2MP = 1920x1088 @16:9)
#     + SIGMAS 极轻精修(beta 调度 3 步 denoise 0.2, euler, 1 pass)。
# 总 NFE = 8@0.4MP + 3@2MP —— 高分辨率只跑 3 步, 极速出 2K。
# ============================================================
def _ff_director_canvas(megapixels, ref_w, ref_h, snap=32):
    """按百万像素 + 参考宽高比计算 32px 对齐画布(对齐参考插件 864x480/1920x1088 契约)。

    参考宽高来自用户已解析的目标画布(保持其横竖构图), 参考值非法时回退 16:9。
    """
    try:
        mp = float(megapixels)
        rw = int(ref_w)
        rh = int(ref_h)
    except (TypeError, ValueError):
        mp, rw, rh = 0.4, 16, 9
    if mp <= 0 or rw <= 0 or rh <= 0:
        mp, rw, rh = 0.4, 16, 9
    snap = max(8, int(snap))
    area = mp * 1e6
    scale = math.sqrt(area / float(rw * rh))
    w = max(snap, int(round(rw * scale / snap)) * snap)
    h = max(snap, int(round(rh * scale / snap)) * snap)
    # 收紧到面积上限内(与 Omni 一采钳制同源策略, 防对齐取整后越过目标 MP)
    while w > snap and h > snap and w * h > area * 1.06:
        if w > h:
            w -= snap
        else:
            h -= snap
    return int(w), int(h)


def _ff_director_refine_factor(first_w, first_h, target_w, target_h, align_px):
    """计算二采 latent 放大因子: 在 W/H 两个候选因子中选放大后面积与目标画布
    误差更小的那个。因 32px 对齐取整(向下), 单一因子无法同时命中双轴,
    此函数保证输出画布始终 ≈ 目标 MP 且构图不被拉变形。

    返回 (面积误差, factor, 放大后 latent_w, 放大后 latent_h)。
    """
    try:
        lm = max(1, int(align_px) // 16)
        flw = max(1, int(first_w) // 16)
        flh = max(1, int(first_h) // 16)
        tlw = max(1, int(target_w) // 16)
        tlh = max(1, int(target_h) // 16)
        best = None
        for f in (tlw / float(flw), tlh / float(flh)):
            nw = _ff_snap_to_multiple(round(flw * f), lm)
            nh = _ff_snap_to_multiple(round(flh * f), lm)
            err = abs(nw * nh - tlw * tlh) / float(max(1, tlw * tlh))
            if best is None or err < best[0]:
                best = (err, f, nw, nh)
        return best
    except Exception:
        return (9e9, float(target_w) / max(1, float(first_w)), 0, 0)


def _ff_sigmas_override_tensor(sigmas_in):
    """Director Refine 外接 SIGMAS 输入 -> CPU float32 单调递减 tensor(与内部
    _sigmas() 返回同型)。支持 comfy.samplers.Sigmas 对象 / torch.Tensor /
    可迭代数值列表; 非法输入(空/非单调/解析失败)返回 None, 调用方回退内部 beta 调度。"""
    try:
        import torch as _t
        if sigmas_in is None:
            return None
        if isinstance(sigmas_in, _t.Tensor):
            t = sigmas_in
        elif hasattr(sigmas_in, "sigmas") and _t.is_tensor(getattr(sigmas_in, "sigmas", None)):
            t = sigmas_in.sigmas
        else:
            try:
                t = _t.tensor([float(v) for v in sigmas_in], dtype=_t.float32)
            except Exception:
                return None
        t = t.detach().reshape(-1).cpu().float()
        if t.numel() < 2:
            return None
        if not bool(_t.all(t[:-1] > t[1:])):
            return None
        return t
    except Exception:
        return None


# ============================================================
# v1.31: Sol-H3 Self-Lift 双采技术集成（一采 + 二采直出高清）
# 移植自 BSAI-ComfyUI-Sol-H3 的 LatentUpscaleAlign 核心语义:
#   latent 直接放大(不经过VAE) + 像素对齐(H3官方32px) + CONST 重加噪
#   + 音频锁定(默认) + DisableNoise 二采完整去噪
# ============================================================
_FF_UPSCALER_MOD = None
# v14.157: 3D 语义放大回退记录 —— 过去只打一行控制台日志就静默降为
# bilinear 插值, 用户完全看不到。这里记录状态, 由调用处推到前端状态栏。
_FF_UPSCALER_FELL_BACK = {"hit": False, "reason": "", "clip": -1}
try:
    import sys as _sys, os as _os
    _ff_up_dir = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                               "Comfyui_Minimax_h3_latent_Upscaler", "nodes")
    if _os.path.isdir(_ff_up_dir) and _ff_up_dir not in _sys.path:
        _sys.path.insert(0, _ff_up_dir)
    import minimax_h3_latent_upscaler_3d as _FF_UPSCALER_MOD
    try:
        _fp = folder_paths
        _ff_up_models = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                                      "Comfyui_Minimax_h3_latent_Upscaler", "models", "h3_latent_upscalers")
        if _os.path.isdir(_ff_up_models):
            _fp.add_model_folder_path("h3_latent_upscalers", _ff_up_models)
    except Exception:
        pass
except Exception:
    _FF_UPSCALER_MOD = None

# v14.250: 官方 ComfyUI-MiniMaxH3_LatentUpscaler 的 conditioning 放大函数
# (upscale_minimax_conditioning) —— 在二采 latent 放大到 2x 时, 必须同步
# 把 ref2va 的 minimax_refs[*].latent / minimax_keyframes[*].latent 也放大,
# 否则参考图 CLIP 嵌入停留在低分辨率坐标空间, 二采 2K 级别的参考控制力下降
# (参考工作流 H3-极速TR双采-文戏流 的官方 MiniMaxH3LatentUpscaleCombined 节点
# 内部正是同时做了 upscale_and_add_noise + upscale_minimax_conditioning)。
# 已安装即自动启用, 未安装时 refine 路径完全不影响。
_FF_COND_UPSCALE_FN = None
try:
    import importlib.util as _ilu_cond
    _cond_roots = [
        _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                      "ComfyUI-MiniMaxH3_LatentUpscaler"),
    ]
    for _r in _cond_roots:
        _cond_mod_path = _os.path.join(_r, "utils.py")
        if _os.path.isfile(_cond_mod_path):
            _cond_spec = _ilu_cond.spec_from_file_location("bsai_ff_cond_upscale", _cond_mod_path)
            _cond_mod = _ilu_cond.module_from_spec(_cond_spec)
            _cond_spec.loader.exec_module(_cond_mod)
            if hasattr(_cond_mod, "upscale_minimax_conditioning"):
                _FF_COND_UPSCALE_FN = _cond_mod.upscale_minimax_conditioning
                print("[H3 Extender] v14.250: 官方 MiniMaxH3LatentUpscaleCombined 的 "
                      "upscale_minimax_conditioning 已装载 —— 二采 latent 放大时 "
                      "ref2va minimax_refs/keyframes 同步放大")
            break
except Exception as _e_cond:
    _FF_COND_UPSCALE_FN = None


_RP_LEGACY_LABELS = {
    # pre-v14.340 label of the MV dual-pass pipeline
    "MV Dual-Pass (\u7535\u5f71\u5de5\u5382 v3.2 \u539f\u7248)": "MV Dual-Pass (Film Factory v3.2 original)",
}


# h3_clean_latent_upscaler_film_epoch200(base.low_blocks/refine_blocks/to_delta
# 因子化注意力架构) 会被直接塞进 pure-3D conv 加载器, strict load 必然失败,
# 静默退成 bislerp 插值 —— 画质明显变软却看不出原因。
# 这里自己读 safetensors 头做判定(只解析 header, 不加载任何张量, 毫秒级)。
_FF_UPSCALER_ARCH_CACHE = {}


def _ff_upscaler_weight_path(name):
    """权重文件名 -> 绝对路径; 找不到返回空串。"""
    if not name:
        return ""
    import os as _o
    try:
        _p = folder_paths.get_full_path("latent_upscale_models", name)
        if _p and _o.path.isfile(_p):
            return _p
    except Exception:
        pass
    try:
        _d = _FF_UPSCALER_MOD.get_models_dir()
        for _tail in (name, _o.path.basename(name)):
            _p = _o.path.join(_d, _tail)
            if _o.path.isfile(_p):
                return _p
    except Exception:
        pass
    return ""


def _ff_probe_upscaler_arch(name):
    """判定权重能否被本机 pure-3D conv 加载器 strict 加载。

    返回 (compatible, desc):
      True  -> 结构与 LatentResizer3D(conv_in/in_blocks/out_blocks, 24ch) 匹配
      False -> 已知不匹配(因子化注意力 clean 版 / LTX-2.5 版 / 未知布局)
      None  -> 无法判定(文件缺失/探针异常), 调用方按"照旧尝试加载"处理
    """
    import os as _o
    _path = _ff_upscaler_weight_path(name)
    if not _path:
        return None, "missing file"
    _key = None
    try:
        _key = (_path, _o.path.getmtime(_path), _o.path.getsize(_path))
        if _key in _FF_UPSCALER_ARCH_CACHE:
            return _FF_UPSCALER_ARCH_CACHE[_key]
    except Exception:
        _key = None

    _res = (None, "unknown")
    try:
        if _path.lower().endswith(".safetensors"):
            import json as _json
            import struct as _struct
            with open(_path, "rb") as _fh:
                _ln = _struct.unpack("<Q", _fh.read(8))[0]
                _hdr = _json.loads(_fh.read(_ln).decode("utf-8"))
            _keys = [k for k in _hdr.keys() if k != "__metadata__"]
            _conv = _hdr.get("conv_in.weight")
            _conv_shape = _conv.get("shape") if isinstance(_conv, dict) else None
            if (_conv_shape and len(_conv_shape) == 5 and _conv_shape[1] == 24
                    and any(k.startswith("in_blocks.") for k in _keys)
                    and any(k.startswith("out_blocks.") for k in _keys)):
                _res = (True, "pure-3D conv, channels=" + str(_conv_shape[0]) + ", 24ch in")
            elif any(k.startswith("base.") for k in _keys) or "to_delta.weight" in _hdr:
                _res = (False, "factorized-attention 'clean' upscaler "
                               "(base./refine_blocks/to_delta) needs h3_upscaler_dispatch, "
                               "pure-3D conv loader cannot strict-load it")
            elif "final_conv.weight" in _hdr:
                _res = (False, "LTX-2.5 latent upscaler (final_conv) - different architecture")
            else:
                _res = (False, "unknown safetensors layout: no conv_in.weight / no in_blocks")
    except Exception as _pe:
        _res = (None, "probe failed: " + str(_pe)[:80])
    if _key is not None:
        _FF_UPSCALER_ARCH_CACHE[_key] = _res
    return _res


def _ff_get_upscaler_models(compatible_only=False):
    """获取 3D latent upscaler 权重列表; 不可用时返回仅插值选项。

    compatible_only=True 时只返回本机加载器真能 strict-load 的权重(用于自动纠偏的
    备选列表)。节点下拉框仍用 False 保留全量文件名 —— 老工作流里存的
    h3_clean_... 若从列表里消失, 前端会报 "Value not in list" 并把整条 prompt 丢掉;
    架构不合的权重改为在 _ff_resolve_upscaler_model() 里运行时纠正。
    """
    opts = ["(bilinear interpolation, no model)"]
    if _FF_UPSCALER_MOD is not None:
        try:
            # v14.273: 只列真正能加载的权重 —— models/latent_upscale_models/
            # 同时放着 pure-3D 卷积、clean 因子化注意力、LTX-2.5 upsampler
            # 三种互不兼容的架构, 选错会在 load_state_dict 里炸掉。
            try:
                names = _FF_UPSCALER_MOD.scan_models(supported_only=True)
            except TypeError:
                names = _FF_UPSCALER_MOD.scan_models()
            # v14.345: 上游 2026-08-29 版把目录列全、不判架构, 这里按真实 header 过滤
            _keep = []
            for _n in names:
                if str(_n).startswith("("):
                    continue
                if compatible_only:
                    _ok, _ = _ff_probe_upscaler_arch(_n)
                    if _ok is False:
                        continue
                _keep.append(_n)
            opts.extend(sorted(_keep))
        except Exception:
            pass
    return opts


def _ff_resolve_upscaler_model(name):
    """校验 3D upscaler 权重与加载器架构是否匹配, 不匹配时自动换成可用权重。

    v14.273: 旧工作流里存的权重若不受加载器支持, 会在 load_state_dict 里
    抛错, 被 except 吞掉后静默退化成 bilinear 插值 —— 画质明显变软却看不出
    原因。这里提前发现, 自动纠正并把原因推到前端状态栏, 避免整条链白跑。
    v14.345: 加载器没有 is_supported_model 接口时(本机 2026-08-29 版), 改走
    safetensors header 探针, 保证这条校正在本机真的会执行。
    """
    if not name or str(name).startswith("("):
        return name, ""
    if _FF_UPSCALER_MOD is None:
        return name, ""

    _ok = None
    _desc = "unknown architecture"
    try:
        _ok = bool(_FF_UPSCALER_MOD.is_supported_model(name))
        _desc = "loader-reported supported"
    except Exception:
        _ok = None
    if _ok is None:
        _ok, _desc = _ff_probe_upscaler_arch(name)
    if _ok is not False:
        return name, ""

    _opts = [n for n in _ff_get_upscaler_models(compatible_only=True)
             if not str(n).startswith("(")]
    _fallback = ""
    for _pref in ("minimax_h3_latent_upscaler_3d_fp16", "minimax_h3_latent_upscaler_3d_fp32",
                  "latent_upscaler_3d", "upscaler_3d"):
        for _n in _opts:
            if _pref in str(_n).lower():
                _fallback = _n
                break
        if _fallback:
            break
    if not _fallback and _opts:
        _fallback = _opts[0]
    if not _fallback:
        return "(bilinear interpolation, no model)", (
            "3D upscaler weights '" + str(name) + "' do not match the loader architecture ("
            + str(_desc) + ") and no compatible weights are installed; "
            "fell back to bilinear interpolation")
    return _fallback, (
        "3D upscaler weights '" + str(name) + "' do not match the loader architecture ("
        + str(_desc) + "); switched to '" + str(_fallback) + "' automatically")


def _ff_is_nested(samples):
    return isinstance(samples, comfy.nested_tensor.NestedTensor)


def _ff_extract_members(samples):
    """NestedTensor -> members 列表; 普通 tensor 原样返回。"""
    if _ff_is_nested(samples):
        return list(samples.unbind()), True
    return [samples], False


def _ff_wrap_members(members, was_nested):
    if was_nested:
        return comfy.nested_tensor.NestedTensor(members)
    return members[0]


def _ff_video_hw(samples):
    """取 latent 视频成员的 (h, w); 失败返回 None。"""
    try:
        members, _ = _ff_extract_members(samples)
        v = members[0] if members else None
        if v is not None and v.dim() == 5:
            return (int(v.shape[-2]), int(v.shape[-1]))
    except Exception:
        pass
    return None


def _ff_detect_latent_hard_cut(samples, pixel_thr=1.6, lf_thr=1.8, trim_frames=0):
    """v14.317: 在一采 latent 序列里找"场景整体换掉"的硬切点。

    判据(用**真实一采 latent** 标定, 见 tools/audit_one_shot_latent.py 的相位口径):
      * 相邻行差分 > pixel_thr x **同相位(row mod 5)** 中位数
      * 且 低频(空间 8x8 块平均)相邻行差分 > lf_thr x 同相位中位数
    两项必须同时成立(AND): 低频项是**必要条件** —— 只看行差分会把
    "人物大幅运动/转身"误判成切镜, 低频项只看大面积明暗与结构, 对人物自身运动不敏感。

    标定值(阈值 1.6 / 1.8 在 v14.289 真实 4 段 latent 上: 3 处硬切全中, 零误报):
      段2 row53 (成片 f160) 相位1.89 低频3.76 | 段3 row11 (f13) 1.88/2.20
      段3 row68 (f210) 相位1.87 低频3.42 | 段1 最高 1.22/1.22 | 段4 最高 1.32/1.49
    (低频项用 mean_C(|Δ|) 无符号口径 —— 若先降通道再取绝对差, 正负会抵消,
     比值虚高 2~5 倍, 阈值必须按无符号口径标定)

    阈值平台区: 相位 ∈ [1.4, 1.8] x 低频 ∈ [1.3, 2.2] 结果完全一致;
    相位 >= 2.0 会漏掉全部硬切。

    返回 [{"row": latent 行号, "out_frame": ≈成片帧号, "dr":..., "lr":...}, ...]
    """
    try:
        members, _ = _ff_extract_members(samples)
        v = members[0] if members else None
        if v is None or v.dim() != 5:
            return []
        # (B, C, T, H, W) -> (C, T, H, W), 取 batch 0, 全通道
        x = v[0].detach().to("cpu", torch.float32)
        if x.dim() != 4:
            return []
        _c = int(x.shape[0])
        _t = int(x.shape[1])
        _h = int(x.shape[2])
        _w = int(x.shape[3])
        if _t < 12:
            return []
        # 时序行差分(全通道平均绝对差)
        d = (x[:, 1:] - x[:, :-1]).abs().mean(dim=(0, 2, 3))
        # 空间低频: 8x8 块平均(latent 网格上 8x8 块 = 像素域 32x32, 与像素域审计同口径)
        _k = 8
        _hh = (_h // _k) * _k
        _ww = (_w // _k) * _k
        if _hh < _k or _ww < _k:
            return []
        y = x[:, :, :_hh, :_ww].reshape(_c, _t, _hh // _k, _k, _ww // _k, _k).mean(dim=(3, 5))
        lfd = (y[:, 1:] - y[:, :-1]).abs().mean(dim=(0, 2, 3))
        # 同相位基线: H3 latent 每 5 行 = 17 帧, 行差分自带 5 行周期
        med = [0.0] * 5
        lmed = [0.0] * 5
        for _ph in range(5):
            _idx = [i for i in range(_t - 1) if ((i + 1) % 5) == _ph]
            if _idx:
                med[_ph] = float(d[_idx].median())
                lmed[_ph] = float(lfd[_idx].median())
        _trim = float(trim_frames or 0)
        out = []
        for _i in range(_t - 1):
            _row = _i + 1
            _b = med[_row % 5]
            _lb = lmed[_row % 5]
            if _b <= 0.0 or _lb <= 0.0:
                continue
            _dr = float(d[_i]) / _b
            _lr = float(lfd[_i]) / _lb
            if _dr > pixel_thr and _lr > lf_thr:
                _gf = _row * 17.0 / 5.0
                out.append({"row": _row, "gen_frame": _gf, "out_frame": _gf - _trim,
                            "dr": _dr, "lr": _lr})
        return out
    except Exception as _e:
        print(f"[H3 Extender] v14.317 硬切检测异常(忽略): {_e}")
        return []


def _ff_auto_refine_tile_count(samples, requested, overlap_px, max_tiles=8):
    """v14.179 (2026-10-23): 二采分块粒度自适应 —— 不再盲目扩块到 Sol-Attn 健康区。

    实测修正(实机 5090 24GB):
      - v14.149 固定 4 块(每块 ~334k 灰色区) = 399s/步;
      - v14.164 扩到 8 块(每块 <=270k 健康区) = 545s/步 —— 块间 overlap 重复计算
        翻倍, 且 tile 实际走 KJNodes head 分组(实测 0.26~0.55s/k tokens), 并非
        注释假设的 Sol-Attn 0.7s/块, 扩块反而更慢。
    → 结论: 每块 <=450k(病态边缘) 一律尊重请求值(分块越少 forward/搬运/重叠越少);
      每块 > 450k 才提升到每块 <=450k 的最少块数, 绕开 440k+ 病态 kernel。
    """
    try:
        _mm164, _ = _ff_extract_members(samples)
        if _mm164 is None or getattr(_mm164[0], "ndim", 0) < 5:
            return int(requested)
        _b164, _c164, _t164, _h164, _w164 = (int(x) for x in _mm164[0].shape)
        _axis = max(_h164, _w164)
        _minhw = min(_h164, _w164)
        if _axis <= 1 or _minhw <= 1 or _t164 <= 1:
            return int(requested)
        # v14.181: 恢复 overlap 128px 估算(回滚 v14.179 的 64px 钳制)。
        # 64px 接缝仅靠 motion-context keyframe 兜底(一镜到底模式), 分镜模式
        # 无兜底会画面崩坏; 128px 是分镜模式接缝融合的安全值。
        overlap_px = min(int(overlap_px), 128)
        # VAE_SPATIAL=16: overlap_px 转 latent 格(128px -> 8 latent)
        _ov = max(1, int(overlap_px) // 16)
        # 每块 token ≈ T * minHW * (axis/n + 2*ov)
        _target = 450000
        _req = max(1, int(requested))
        if _req > 1:
            _per_req = _t164 * _minhw * (_axis // _req + 2 * _ov)
        else:
            _per_req = _t164 * _minhw * _axis
        # 请求值每块未达病态边缘 -> 尊重请求(分块越少 forward/搬运/重叠越少)
        if _per_req <= _target:
            print(f"[H3 Extender] v14.179 分块粒度: 请求 n_tiles={requested} -> {_req} "
                  f"(每块约 {_per_req:,} tokens <= 450k 安全区, 尊重请求不扩块)")
            return _req
        # 请求值落在病态区 -> 提升到每块 <= 450k 的最少块数
        _den = _target / (_t164 * _minhw) - 2 * _ov
        if _den <= 0:
            return max_tiles
        _n = int(_axis / _den) + 1
        _n = max(_req + 1, min(max_tiles, _n))
        _per = _t164 * _minhw * (_axis // _n + 2 * _ov)
        print(f"[H3 Extender] v14.179 分块粒度: 请求 n_tiles={requested} -> {_n} "
              f"(每块约 {_per:,} tokens <= 450k 安全区, 绕开病态 kernel)")
        return _n
    except Exception:
        return int(requested)


def _ff_snap_to_multiple(n, m):
    m = max(1, int(m))
    return max(m, (int(n) // m) * m)


def _ff_refine_factor_for_budget(width, height, latent_t, budget, align_px=40):
    """v14.276: 让二采单次调用 tokens <= budget 的最大 latent 放大倍率。

    二采 tokens = T * H_lat * W_lat, 随倍率平方增长。超过预算时
    只能靠时间分块把整段切成多段各自加噪采样, 段间必然出现接缝闪烁与碎花纹理
    (实机 709,920 tokens 4 段采样满屏碎纹)。这里改为向下取倍率: 整段一次调用,
    宁可比目标分辨率小一点, 也不再把画面切段。
    """
    h_lat = max(1, int(height) // 16)
    w_lat = max(1, int(width) // 16)
    step = max(1, int(align_px) // 16)
    budget = max(1, int(budget))
    best = 1.0
    for _i in range(100, 201):
        _f = _i / 100.0
        _nh = _ff_snap_to_multiple(round(h_lat * _f), step)
        _nw = _ff_snap_to_multiple(round(w_lat * _f), step)
        if int(latent_t) * _nh * _nw <= budget:
            best = _f
    return best


def _ff_declared_output_px(width, height, latent_factor, hv2x=1.0, align_px=40):
    """v14.279: 由「一采像素 + 二采倍率」推导声明输出尺寸(与二采实际几何一致)。

    旧写法 round(960 × 1.02)=979 / round(544 × 1.02)=555 都是奇数, libx264
    yuv420p 直接拒绝 -> 每段 mp4 编码 BrokenPipe -> clip 预览/下载全空。
    这里在 latent 空间推导: round(像素//16 × 倍率) -> 按 align/16 向下取整
    回像素 -> HyperVAE 2x 再翻倍 -> 最后强制偶数。
    960x544 × 1.02 -> latent 34x60(1.02 被取整吸收) -> 960x544, 与实际解码一致。
    """
    try:
        w = max(1, int(width))
        h = max(1, int(height))
        f = max(1.0, float(latent_factor))
        step = max(1, int(align_px) // 16)
        nh = _ff_snap_to_multiple(round(int(h) // 16 * f), step)
        nw = _ff_snap_to_multiple(round(int(w) // 16 * f), step)
        x = max(1.0, float(hv2x))
        ow = int(round(nw * 16 * x))
        oh = int(round(nh * 16 * x))
    except Exception:
        ow, oh = int(width), int(height)
    ow -= ow % 2
    oh -= oh % 2
    return max(2, ow), max(2, oh)


def _ff_upscale_video_latent(video, scale, align_to_px, method, upscaler_model=""):
    """v1.31: 视频 latent [B,C,T,H,W] 空间放大 + 像素对齐(不经过 VAE, 无编解码损失)。

    H3 空间下采样率 16(1920->120 latent); 放大后先按 align_to_px(默认32px) 对齐
    再换算回 latent 尺寸, 避免官方节点不取整导致的分辨率偏移与边缘色条。
    音频 latent 保持不动(只放大视频成员)。

    upscaler_model: 选中 3D latent upscaler 文件名时用神经网络语义放大, 否则按 method 插值
    (调用处传 bislerp: 保 token 范数的平滑方法, bilinear 会让二采在边缘发明碎屑)。
    """
    import comfy.utils
    if video.ndim < 4:
        raise ValueError(f"视频latent至少需要4维 [B,C,H,W], 实际 {tuple(video.shape)}")

    h_lat, w_lat = video.shape[-2], video.shape[-1]
    latent_mult = max(1, int(align_to_px) // 16)  # 像素32 -> latent步进2(H3下采样16)
    new_h = _ff_snap_to_multiple(round(h_lat * scale), latent_mult)
    new_w = _ff_snap_to_multiple(round(w_lat * scale), latent_mult)
    if new_h == h_lat and new_w == w_lat:
        # v14.346/v14.374: 以前这里是「静默 return」, 日志只显示 upscale=x1.02 却不知道
        # 放大器一次都没跑(本次坏片就是这样被误判成"换权重导致糊")。改为显式播报。
        print(f"[H3 Extender] ⚠️ v14.346 latent 放大为空操作: 请求 x{float(scale):.2f} 但 "
              f"{h_lat}x{w_lat} -> {new_h}x{new_w} (align={int(align_to_px)}px 取整后几何未变), "
              f"3D 放大器未执行, 返回一采 latent")
        return video

    orig_dtype = video.dtype
    use_model = (upscaler_model and _FF_UPSCALER_MOD is not None
                 and not upscaler_model.startswith("("))
    if use_model:
        try:
            dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            model_dtype = torch.bfloat16
            s = video.to(device=dev, dtype=model_dtype, copy=True)
            if s.ndim == 4:
                s = s.unsqueeze(2)
            T = s.shape[2]
            model = _FF_UPSCALER_MOD.load_model(upscaler_model, dev, "bf16")
            norm_mean, norm_std = _FF_UPSCALER_MOD._make_norm_tensors(dev, model_dtype)
            with torch.inference_mode():
                s.sub_(norm_mean).div_(norm_std)
                out = model(s, scale=float(scale), target_size=(T, new_h, new_w))
                del s
                out.mul_(norm_std).add_(norm_mean)
            out = out.to(device="cpu", dtype=orig_dtype)
            if dev.type == "cuda":
                torch.cuda.empty_cache()
            print(f"[H3 Extender] Refine 3D upscaler: {tuple(video.shape)} -> {tuple(out.shape)} "
                  f"model={upscaler_model}")
            return out
        except Exception as e:
            print(f"[H3 Extender] Refine 3D upscaler 失败({e}), fallback {method}")
            # v14.157: 记录回退原因, 调用处会推送前端显式警告
            _FF_UPSCALER_FELL_BACK["hit"] = True
            _FF_UPSCALER_FELL_BACK["reason"] = str(e)[:180]

    # fp16/bf16 插值会量化新网格, 二采出现斑点; 统一 fp32 放大后转回原精度
    samples = video.float() if video.dtype in (torch.float16, torch.bfloat16) else video
    _method = "nearest-exact" if str(method) == "nearest" else str(method)
    out = comfy.utils.common_upscale(samples, new_w, new_h, _method, "disabled")
    return out.to(dtype=orig_dtype)


# v14.279: 条件几何对齐统计(ref/kf/实际缩放块数), 由调用处打印后清零。
_FF_COND_FIT_STATS = {"ref": 0, "kf": 0, "resized": 0}


def _ff_fit_cond_geometry(conditioning, target_h, target_w, method="bilinear"):
    """把 ref2va 的 minimax_refs / minimax_keyframes 视觉 latent 精确缩放到
    二采 latent 的**实际空间几何**。

    v14.250 直接按名义倍率 `_r_factor` 调官方 upscale_minimax_conditioning:
    本次 latent 34x60 经 align=40px 取整后尺寸未变, cond 却被插值到
    35x61(+patch pad 36x62)。PackedLayout 按 34x60 预留 9620 行, cond 实到
    10292 行 -> comfy/ldm/minimax/model.py:576 广播崩溃, 每个 clip 二采全废。
    改为「目标几何驱动」: 已与目标一致的块原样保留, 不一致的精确插值到
    (target_h, target_w) 并同步 latent_h/w(及 latent_t), 行数与布局恒等。
    """
    if not conditioning:
        return conditioning
    th, tw = int(target_h), int(target_w)
    if th <= 0 or tw <= 0:
        return conditioning

    def _fit(z):
        if not isinstance(z, torch.Tensor) or z.ndim not in (4, 5):
            return z
        if tuple(z.shape[-2:]) == (th, tw):
            return z
        src_dtype = z.dtype
        work = z.float()
        try:
            if z.ndim == 5:
                work = torch.nn.functional.interpolate(
                    work, size=(int(z.shape[2]), th, tw),
                    mode="trilinear", align_corners=False)
            else:
                work = torch.nn.functional.interpolate(
                    work, size=(th, tw), mode=str(method),
                    align_corners=False)
        except Exception:
            work = torch.nn.functional.interpolate(
                work,
                size=(int(z.shape[2]), th, tw) if z.ndim == 5 else (th, tw),
                mode="nearest")
        _FF_COND_FIT_STATS["resized"] += 1
        return work.to(dtype=src_dtype)

    out = []
    for entry in conditioning:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            out.append(entry)
            continue
        emb, meta = entry[0], entry[1]
        if not isinstance(meta, dict):
            out.append(entry)
            continue
        new_meta = dict(meta)
        refs = meta.get("minimax_refs")
        if isinstance(refs, list):
            new_refs = []
            for blk in refs:
                if (not isinstance(blk, dict)
                        or blk.get("kind") == "audio"
                        or blk.get("latent") is None):
                    new_refs.append(blk)
                    continue
                nb = dict(blk)
                nb["latent"] = _fit(nb["latent"])
                z = nb["latent"]
                if isinstance(z, torch.Tensor):
                    nb["latent_h"] = int(z.shape[-2])
                    nb["latent_w"] = int(z.shape[-1])
                    if "latent_t" in nb and z.ndim == 5:
                        nb["latent_t"] = int(z.shape[2])
                new_refs.append(nb)
                _FF_COND_FIT_STATS["ref"] += 1
            new_meta["minimax_refs"] = new_refs
        kfs = meta.get("minimax_keyframes")
        if isinstance(kfs, list):
            new_kfs = []
            for kf in kfs:
                if not isinstance(kf, dict) or kf.get("latent") is None:
                    new_kfs.append(kf)
                    continue
                nk = dict(kf)
                nk["latent"] = _fit(nk["latent"])
                new_kfs.append(nk)
                _FF_COND_FIT_STATS["kf"] += 1
            new_meta["minimax_keyframes"] = new_kfs
        out.append([emb, new_meta])
    return out


# ── v14.83/84/85: 像素域超分旁支（per-clip 逐段 + final 全片，默认关）────────
def _ff_clip_upscale_enabled(clip, master):
    """CLIP 级超分开关优先于总开关 upscale_per_clip：
    None=跟随总开关；True=强制本 CLIP 超分；False=强制本 CLIP 不超分。"""
    if clip is None:
        return bool(master)
    v = clip.get("upscale")
    if v is None:
        return bool(master)
    return bool(v)


def _ff_resolve_upscale_mode(mode, factor, engine):
    """v14.84 upscale mode preset -> (factor, engine). Default: Balanced (quality+speed)."""
    if mode in ("Quality first", "质量优先"):
        return 3.0, "realesr"
    if mode in ("Speed first", "速度优先"):
        return 1.5, "auto"
    if mode in ("Custom", "自定义"):
        return float(factor), str(engine)
    return 2.0, "auto"


def _ff_probe_video(path, ff):
    """返回 (width, height, fps_float, frame_count)。失败返回 None。"""
    try:
        r = subprocess.run(
            [ff, "-i", str(path), "-f", "null", "-"],
            capture_output=True, timeout=60,
        )
        stderr = (r.stderr or b"").decode("utf-8", "replace")
        import re as _re
        w = h = None
        m = _re.search(r"(\d{2,5})x(\d{2,5})", stderr)
        if m:
            w, h = int(m.group(1)), int(m.group(2))
        fps = None
        m2 = _re.search(r"(\d+(?:\.\d+)?)\s*fps", stderr)
        if m2:
            fps = float(m2.group(1))
        frames = None
        m3 = _re.search(r"(\d+)\s*frames\s*$", stderr, _re.MULTILINE)
        if m3:
            frames = int(m3.group(1))
        return (w, h, fps, frames)
    except Exception:
        return None


def _ff_get_duration(path, ff):
    """Return duration in seconds, or 0.0 on failure."""
    try:
        r = subprocess.run([ff, "-i", str(path), "-f", "null", "-"],
                           capture_output=True, timeout=30)
        import re as _re
        m = _re.search(r"time=(\d+):(\d+):(\d+\.\d+)", r.stderr.decode("utf-8", "replace"))
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    except Exception:
        pass
    return 0.0


def _ff_build_xfade_merge_cmd(ff, clip_paths, output_path, vfade=0.5, afade=0.05):
    """Build ffmpeg command that chains xfade (video) + acrossfade (audio) for N clips.
    Returns (cmd_list, duration_log). Falls back to re-encoded concat if any clip too short."""
    durations = [_ff_get_duration(cp, ff) for cp in clip_paths]
    n = len(clip_paths)
    if n < 2:
        return None, durations
    if any(d < vfade * 2 for d in durations):
        return None, durations  # too short for xfade, caller falls back

    # Build chained xfade video filter
    vparts = []
    aparts = []
    # v14.302: out_v/out_a 自带方括号，vlabel 必须存"裸标签"，
    # 否则下一轮 f"[{vlabel}]" 会拼成 "[[v01]]" → ffmpeg filter 语法错误(EINVAL)。
    vlabel = "0:v"
    alabel = "0:a"
    cum_dur = durations[0]
    for i in range(1, n):
        out_v = f"[v{i:02d}]"
        out_a = f"[a{i:02d}]"
        offset = max(0.1, cum_dur - vfade)
        vparts.append(f"[{vlabel}][{i}:v]xfade=transition=fade:duration={vfade}:offset={offset:.3f}{out_v}")
        aparts.append(f"[{alabel}][{i}:a]acrossfade=d={afade}:c1=tri:c2=tri{out_a}")
        vlabel = f"v{i:02d}"
        alabel = f"a{i:02d}"
        cum_dur = cum_dur + durations[i] - vfade  # cumulative after overlap

    filter_complex = ";".join(vparts + aparts)
    cmd = [ff, "-y"]
    for cp in clip_paths:
        cmd += ["-i", str(cp)]
    cmd += [
        "-filter_complex", filter_complex,
        "-map", f"[{vlabel}]",
        "-map", f"[{alabel}]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "17",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        str(output_path),
    ]
    return cmd, durations


def _ff_upscale_video_file(path, factor, engine, model, fp16, tile, batch, face_restore):
    """对已生成的视频文件做像素超分重编码（原子替换原文件）。

    引擎：
      bicubic —— ffmpeg scale 滤镜（最快、无模型依赖、内存安全）；
      realesr —— 逐帧读入 → ComfyUI UpscaleModelLoader → 重编码（质量优先）；
      dlss5  —— 预留（需 NVIDIA DLSS SDK 与驱动），暂回退 bicubic；
      auto   —— 按可用性自动选择。
    默认平衡档=auto → realesr 可用则 realesr，否则 bicubic。
    """
    import torch
    import torch.nn.functional as F
    try:
        factor = float(factor)
        if factor <= 1.0:
            return True
        ff = _find_ffmpeg()
        if not ff:
            print("[H3 Extender] 超分: 找不到 ffmpeg, 跳过")
            return False
        path = Path(path)
        if not path.exists():
            return False
        probe = _ff_probe_video(path, ff)
        if not probe or not probe[0] or not probe[1]:
            print("[H3 Extender] 超分: 无法探测视频尺寸, 跳过")
            return False
        w, h, fps, _frames = probe
        fw = max(2, int(round(w * factor)) // 2 * 2)
        fh = max(2, int(round(h * factor)) // 2 * 2)
        engine_eff = str(engine)
        if engine_eff == "auto":
            engine_eff = "realesr" if _ff_realesr_available(model) else "bicubic"
        tmp = path.with_name(path.stem + ".upscaled" + path.suffix)
        if engine_eff == "bicubic":
            cmd = [
                ff, "-y", "-i", str(path),
                "-vf", f"scale={fw}:{fh}:flags=bicubic",
                "-c:v", "libx264", "-crf", "18", "-preset", "slow",
                "-pix_fmt", "yuv420p",
                str(tmp),
            ]
            subprocess.run(cmd, check=True, capture_output=True, timeout=7200)
        elif engine_eff == "realesr":
            # v14.277: 先释放采样期 CUDA 缓存再测提交内存 —— H3 采样结束后 CUDA
            # 缓存常占 ~10GB+, 不释放就测余量会把它压到 20GB 阈值以下, 导致本可
            # realesr 的出片被误降级 bicubic。realesr 函数内仍会再释放一次。
            import gc as _gc_gate
            import torch as _torch_gate
            _gc_gate.collect()
            if _torch_gate.cuda.is_available():
                _torch_gate.cuda.empty_cache()
            # v14.265: 提交内存余量闸 —— 采样结束时 commit 基线常达 ~160GB/191GB,
            # realesr 流(GPU 缓冲 + x264@4K 的 ~110MB malloc + 管道)是压垮它的最后
            # 一根稻草(实测: x264 malloc 失败 -> 管道 EINVAL -> c10 空指针杀进程)。
            # 余量不足时降级 bicubic: ffmpeg 单进程、内存可忽略, 保证出片不炸。
            _cm_u265, _cm_t265 = _commit_gb()
            if _cm_t265 > 0 and (_cm_t265 - _cm_u265) < 20.0:
                print(f"[H3 Extender] 超分降级: 提交内存余量 {_cm_t265 - _cm_u265:.1f}GB "
                      f"< 20GB, realesr->bicubic 保出片", flush=True)
                cmd = [
                    ff, "-y", "-i", str(path),
                    "-vf", f"scale={fw}:{fh}:flags=bicubic",
                    "-map", "0:v:0", "-map", "0:a?",
                    "-c:v", "libx264", "-crf", "18", "-preset", "slow",
                    "-pix_fmt", "yuv420p", "-c:a", "copy",
                    str(tmp),
                ]
                subprocess.run(cmd, check=True, capture_output=True, timeout=7200)
            else:
                _ff_upscale_video_realesr(path, tmp, ff, fw, fh, fps, model, fp16, tile, batch)
        else:
            # dlss5 预留：无 SDK 时回退 bicubic
            print(f"[H3 Extender] 超分引擎 {engine_eff} 暂不可用, 回退 bicubic")
            cmd = [
                ff, "-y", "-i", str(path),
                "-vf", f"scale={fw}:{fh}:flags=bicubic",
                "-c:v", "libx264", "-crf", "18", "-preset", "slow",
                "-pix_fmt", "yuv420p",
                str(tmp),
            ]
            subprocess.run(cmd, check=True, capture_output=True, timeout=7200)
        os.replace(tmp, path)
        print(f"[H3 Extender] 像素超分完成: {path.name} {w}x{h} -> {fw}x{fh} engine={engine_eff}")
        if face_restore:
            _ff_face_restore_file(path, ff)
        return True
    except Exception as e:
        print(f"[H3 Extender] 像素超分失败: {e}")
        try:
            if tmp and Path(tmp).exists():
                Path(tmp).unlink()
        except Exception:
            pass
        return False


def _ff_realesr_available(model):
    """检查 ComfyUI 的 UpscaleModelLoader 链路是否可用（bicubic 无需模型）。"""
    try:
        import comfy_extras.nodes_upscale_model as _num
        # v14.211: ComfyUI 新版删掉了 comfy.ldm.modules.upscale,
        # UpscaleModelLoader / ImageUpscaleWithModel 已全在 comfy_extras.nodes_upscale_model.
        return bool(model and _num.UpscaleModelLoader and _num.ImageUpscaleWithModel)
    except Exception:
        return False


def _ff_load_upscale_model(model_path):
    """v14.211: 适配新版 UpscaleModelLoader API ——
    旧: UpscaleModelLoader().load_model(name).to(dev) -> nn.Module
    新: UpscaleModelLoader().execute(name) -> ImageModelDescriptor (spandrel),
        descriptor.model = nn.Module, descriptor.patcher = CoreModelPatcher.
    返回 (model_module, scale) 或抛出异常。"""
    import comfy_extras.nodes_upscale_model as _num
    import folder_paths as _fp
    import comfy.utils as _cu
    from spandrel import ModelLoader as _SpandrelLoader  # type: ignore
    # 新版 UpscaleModelLoader.execute 需要 node schema 上下文, 直接走底层更稳
    full = _fp.get_full_path_or_raise("upscale_models", model_path)
    sd = _cu.load_torch_file(full, safe_load=True)
    if "module.layers.0.residual_group.blocks.0.norm1.weight" in sd:
        sd = _cu.state_dict_prefix_replace(sd, {"module.": ""})
    descriptor = _SpandrelLoader().load_from_state_dict(sd).eval()
    model_mod = descriptor.model
    scale = getattr(descriptor, "scale", 1.0) or 1.0
    return model_mod, float(scale)


def _ff_upscale_video_realesr(path, tmp, ff, fw, fh, fps, model, fp16, tile, batch):
    """realesr 逐帧超分：ffmpeg 抽帧(rgb24) → torch → UpscaleModelLoader → 重编码。
    v14.211: 适配新版 ComfyUI —— comfy.ldm.modules.upscale 已不存在,
    UpscaleModelLoader 返回 spandrel ImageModelDescriptor, forward 直接调 descriptor.model."""
    import gc as _gc265
    import numpy as np
    import torch
    import torch.nn.functional as F
    import comfy.model_management as _mm211
    model_mod, _native_scale = _ff_load_upscale_model(model)
    dev = _mm211.get_torch_device()
    model_mod = model_mod.to(dev).eval()
    # fp16 提速: upscale 模型大多是 conv, fp16 安全
    if fp16 and dev.type == "cuda":
        model_mod = model_mod.half()
    # v14.265: 超分前释放采样期 CUDA 缓存 —— 采样结束时提交内存基线 ~160GB/191GB,
    # 不释放的话 x264@高分辨率 的 ~110MB malloc 会失败(实测: ffmpeg 死亡 -> 管道
    # EINVAL -> 超分失败, 随后 c10 分配空指针 0xc0000005 杀进程)。
    _gc265.collect()
    if dev.type == "cuda":
        torch.cuda.empty_cache()
    raw = str(tmp) + ".raw"
    subprocess.run(
        [ff, "-y", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", raw],
        check=True, capture_output=True, timeout=7200,
    )
    nbytes = os.path.getsize(raw)
    fw_in, fh_in = _ff_probe_video(path, ff)[0], _ff_probe_video(path, ff)[1]
    fw_in = fw_in or 1
    fh_in = fh_in or 1
    per_frame = fw_in * fh_in * 3
    n_frames = max(1, nbytes // per_frame)
    bs = max(1, min(int(batch), 8))
    # v14.265: 按请求输出尺寸收缩块 —— 单块输出 ≤ ~160MB, 防 8K 原生输出时
    # 802MB/块的巨型管道写 (x264 慢档消费速度远低于产出, 管道长时间承压)。
    bs = max(1, min(bs, int(160 * 1024 * 1024) // max(1, int(fw) * int(fh) * 3)))
    # v14.262: memmap 替代 read+copy —— 旧版整段 raw 双份进内存 + 攒全部超分帧
    # 再 torch.cat, 362 帧 2x 超分时单块 CPU 申请 36.3GB 直接 DefaultCPUAllocator OOM。
    arr = np.memmap(raw, dtype=np.uint8, mode="r")
    # tile_size: 新版 upscale 模型 forward 只接受 tile_size/tile_overlap,
    # 不接受 scale 走模型内部. scale 由模型本身决定.
    _tile_size = int(tile) if int(tile) > 0 else 512
    _tile_overlap = 16
    _need_resize = (int(fw_in) * _native_scale != float(fw)
                    or int(fh_in) * _native_scale != float(fh))
    if _need_resize:
        # v14.265: 输出尺寸以用户请求的 (fw, fh) 为准 —— realesr-general-x4v3 原生 x4,
        # v14.262 直接编码原生尺寸, 把 2x(2176x3840) 请求放大成 4x(4352x7680, 8K),
        # 单帧 raw 25MB->100MB, x264 缓冲区翻 4 倍压垮提交内存。
        print(f"[H3 Extender] 超分执行: 模型原生 x{_native_scale:g} "
              f"({int(fw_in * _native_scale)}x{int(fh_in * _native_scale)}) "
              f"-> 请求尺寸 {fw}x{fh}, area 缩放, 块={bs}", flush=True)
    enc = None
    _pipe_err = None
    try:
        with torch.inference_mode():
            for s in range(0, n_frames, bs):
                # memmap 切片只读, np.array 复制本块拿到独立可写内存
                chunk = np.array(arr[s * per_frame:(s + bs) * per_frame])
                # N, H, W, 3 uint8 -> N, 3, H, W float32
                t = torch.from_numpy(chunk).reshape(-1, fh_in, fw_in, 3).permute(0, 3, 1, 2).float().div_(255.0).to(dev)
                if fp16 and dev.type == "cuda":
                    t = t.half()
                # v14.277: 用 comfy.utils.tiled_scale 做真正的分块超分 —— 旧版
                # model_mod(t, tile_size=...) 对 spandrel 裸 nn.Module 无效
                # (SRVGGNetCompact 拒收 tile_size kwarg, 总是落到全帧 forward),
                # 1312x736 入 x4 原生 = 5248x2944 全帧, H3 常驻时极易 OOM。
                # tiled_scale 按 tile 切输入、逐块 forward、羽化拼接, 中间激活
                # 只占单块, 大幅降低峰值显存。
                import comfy.utils as _cu_us
                up = _cu_us.tiled_scale(
                    t,
                    lambda a: model_mod(a),
                    tile_x=_tile_size, tile_y=_tile_size,
                    overlap=_tile_overlap,
                    upscale_amount=_native_scale,
                    output_device=dev,
                )
                if fp16 and dev.type == "cuda":
                    up = up.float()
                if _need_resize and (int(up.shape[-1]) != int(fw) or int(up.shape[-2]) != int(fh)):
                    up = F.interpolate(up, size=(int(fh), int(fw)), mode="area")
                out = up.clamp_(0.0, 1.0).mul_(255.0).byte().permute(0, 2, 3, 1).cpu().numpy()
                del t, up, chunk
                if enc is None:
                    # 逐帧流式写 ffmpeg stdin; -map 1:a? -c:a copy 保留原音轨
                    # (旧版只编码视频流, 音轨丢失)
                    enc = subprocess.Popen(
                        [ff, "-y",
                         "-f", "rawvideo", "-pix_fmt", "rgb24",
                         "-s", f"{int(fw)}x{int(fh)}", "-r", str(fps or 30.0), "-i", "pipe:0",
                         "-i", str(path),
                         "-map", "0:v:0", "-map", "1:a?",
                         "-c:v", "libx264", "-crf", "18", "-preset", "slow",
                         "-pix_fmt", "yuv420p", "-c:a", "copy",
                         str(tmp)],
                        stdin=subprocess.PIPE)
                try:
                    for _fi in range(int(out.shape[0])):
                        enc.stdin.write(out[_fi].tobytes())
                except OSError as _we:
                    # 编码端已死(多为提交内存不足 x264 malloc 失败), 立即停止写入
                    _pipe_err = _we
                    del out
                    break
                del out
    finally:
        if enc is not None:
            try:
                enc.stdin.close()
            except Exception:
                pass
            if _pipe_err is not None:
                try:
                    enc.kill()
                except Exception:
                    pass
        # v14.267: memmap 必须显式关闭再删文件 —— Windows 上 np.memmap 持有文件
        # 句柄, 未释放时 os.unlink 报 [WinError 32] 另一个程序正在使用此文件,
        # 于是每次超分都"失败"并静默退回未超分原片(用户看到的就是超分不生效)。
        try:
            arr._mmap.close()
        except Exception:
            pass
        try:
            del arr
        except Exception:
            pass
        _gc265.collect()
        try:
            os.unlink(raw)
        except Exception:
            pass
    if _pipe_err is not None:
        raise RuntimeError(f"realesr: 编码管道写入失败(ffmpeg 提前退出): {_pipe_err}")
    if enc is None:
        raise RuntimeError("realesr: 无输出帧")
    if enc.wait() != 0:
        raise RuntimeError("realesr: ffmpeg 重编码失败")


def _ff_face_restore_file(path, ff):
    """人脸修复预留：检测到 codeformer/gfpgan 权重时启用，否则打印提示跳过。"""
    try:
        import folder_paths as _fp_fr
        has = _fp_fr.get_filename_list("facerestore_models")
        if not has:
            print("[H3 Extender] 人脸修复: 无 facerestore_models 权重, 跳过")
            return
        print(f"[H3 Extender] 人脸修复: 检测到 {len(has)} 个权重, 预留接入 FaceRestore (后续)")
    except Exception:
        pass


def _ff_const_add_noise(model, noise_tensor, sigmas, latent, audio_denoise):
    """v1.31: CONST 重加噪(对齐 Sol-H3 LatentUpscaleAlign 语义, 输入为噪声 tensor):
    process_latent_in/out 作用于整体 NestedTensor, 在 sigmas[0] 处混合,
    再 inverse_noise_scaling, 使二采以 σ·ε+(1-σ)·x 而非 (1-σ)²·x 重构。
    音频锁定: 音频成员噪声置零 + noise_mask 音频=0 (audio_denoise<0.5 时)。
    """
    if len(sigmas) == 0 or "samples" not in latent:
        return latent

    out = dict(latent)
    latent_image = latent["samples"]
    members, was_nested = _ff_extract_members(latent_image)
    n_members, n_was_nested = _ff_extract_members(noise_tensor)
    if len(n_members) != len(members):
        raise ValueError(f"噪声成员数 {len(n_members)} 与 latent 成员数 {len(members)} 不一致")

    lock_audio = len(members) >= 2 and float(audio_denoise) < 0.5
    if lock_audio:
        # 音频成员噪声置零(保持一采音频)
        n_members = [torch.zeros_like(t) if i == 1 else t for i, t in enumerate(n_members)]

    # noise_mask: 音频=0(保持), 视频=1(重噪); H3 joint DiT 仍需 mask 显式锁定
    if lock_audio and was_nested:
        mask_members = []
        for i, m in enumerate(members):
            if i == 0:
                mask_members.append(torch.ones(
                    (m.shape[0], 1, m.shape[2], m.shape[3], m.shape[4]),
                    device=m.device, dtype=torch.float32))
            elif i == 1:
                mask_members.append(torch.zeros(
                    (m.shape[0], 1, m.shape[2], m.shape[3]),
                    device=m.device, dtype=torch.float32))
            else:
                mask_members.append(torch.ones_like(m[:1, :1]))
        out["noise_mask"] = _ff_wrap_members(mask_members, was_nested=True)

    model_sampling = model.get_model_object("model_sampling")
    process_latent_out = model.get_model_object("process_latent_out")
    process_latent_in = model.get_model_object("process_latent_in")
    sigma_start = sigmas[0]

    latent_image = process_latent_in(latent_image)
    lat_members, _ = _ff_extract_members(latent_image)
    mixed = []
    for lat, noi in zip(lat_members, n_members):
        m = model_sampling.noise_scaling(sigma_start, noi, lat)
        if hasattr(model_sampling, "inverse_noise_scaling"):
            m = model_sampling.inverse_noise_scaling(sigma_start, m)
        mixed.append(m)
    mixed_nt = _ff_wrap_members(mixed, was_nested=was_nested or n_was_nested)
    mixed_nt = process_latent_out(mixed_nt)
    m_members, _ = _ff_extract_members(mixed_nt)
    out["samples"] = _ff_wrap_members(
        [torch.nan_to_num(t, nan=0.0, posinf=0.0, neginf=0.0) for t in m_members],
        was_nested=was_nested)
    return out


def _upscale_latent_spatial(samples, factor):
    """v1.30: H3 AV latent 空间维度放大。
    H3 latent 为 5D (B, C, T, H, W)，空间下采样率 16（输出 768×1344 → latent 48×84）。
    仅放大 H/W，保持 B/C/T 不变；放大后对齐到 2 的倍数（对应像素 32 网格）。
    4D latent 走 common_upscale 兜底。
    v1.21: 兼容 NestedTensor（H3 采样器可能返回 NestedTensor，无 .reshape 方法）。
    """
    factor = max(1.0, float(factor))
    if factor <= 1.0:
        return samples
    # NestedTensor 兼容：无 .reshape 方法时尝试转为 padded tensor
    if not hasattr(samples, "reshape"):
        try:
            if hasattr(samples, "to_padded_tensor"):
                samples = samples.to_padded_tensor(0.0)
                print(f"[H3 Extender] _upscale_latent_spatial: converted NestedTensor -> padded tensor shape={tuple(samples.shape)}")
            else:
                print(f"[H3 Extender] _upscale_latent_spatial: unsupported type {type(samples).__name__}, skip upscale")
                return samples
        except Exception as _conv_err:
            print(f"[H3 Extender] _upscale_latent_spatial: NestedTensor convert failed ({_conv_err}), skip upscale")
            return samples
    if samples.ndim == 4:
        _, _, H, W = samples.shape
        nH = max(2, (int(H * factor) // 2) * 2)
        nW = max(2, (int(W * factor) // 2) * 2)
        return comfy.utils.common_upscale(samples, nW, nH, "bilinear", "center")
    # 5D (B, C, T, H, W)
    B, C, T, H, W = samples.shape
    nH = max(2, (int(H * factor) // 2) * 2)
    nW = max(2, (int(W * factor) // 2) * 2)
    bt = B * T
    reshaped = samples.reshape(bt, C, H, W)
    # v2.0: bilinear 替代 bicubic，减少 latent 放大后的鬼影/重影
    up = torch.nn.functional.interpolate(reshaped, size=(nH, nW), mode="bilinear", align_corners=False)
    return up.reshape(B, C, T, nH, nW)


def _drop_mismatched_adaln_patches(model):
    """Shape-aware drop of lora adaln patches whose delta does not match the base adaln weight.

    pruned base adaln_proj.linear.weight=[96768,8], but full-width loras (e.g. cinematic lora)
    carry adaln delta=[96768,2688]. The rgthree stack applies AFTER SolH3 without SolH3's
    _shape_filter, so calculate_weight fails to reshape every block every step (spam+slow).
    We compare each patch expected shape against model_state_dict real shape and drop only the
    mismatched entries; attn/mlp detail enhancement stays. Full-width bases keep matching adaln.
    """
    try:
        model_sd = model.model_state_dict()
    except Exception:
        return 0
    dropped = 0
    for k in list(getattr(model, "patches", {}).keys()):
        if "adaln_proj.linear" not in k:
            continue
        if k not in model_sd:
            continue
        mw_shape = tuple(model_sd[k].shape)
        kept = []
        for entry in model.patches[k]:
            try:
                patch_obj = entry[1]
                mat1 = patch_obj.weights[0]
                mat2 = patch_obj.weights[1]
                exp = (tuple(mat1.shape)[0], tuple(mat2.shape)[1])
            except Exception:
                kept.append(entry)
                continue
            if tuple(exp) == tuple(mw_shape):
                kept.append(entry)
            else:
                dropped += 1
        if kept:
            model.patches[k] = kept
        else:
            del model.patches[k]
    return dropped


def _sample_h3(model, conditioning, latent, seed: int, sampler_name: str, scheduler: str, steps: int, denoise: float,
               owner_id=None, clip_index=-1,
               refine_enable=True, refine_denoise=0.45, refine_steps=2, refine_upscale_factor=2.0,
               refine_upscaler_model="", refine_align_to=40, refine_audio_denoise=0.0,
               tiled_refine=False, tile_count=4, tile_overlap=128,
               refine_mem_mode="spatial",
               temporal_chunk_tokens=0, temporal_overlap_tokens=8,
               dual_track_shift=True, shift_video=12.0, shift_audio=3.0,
               tst_enable=True, tst_tau=0.2, omni_8step_mode=False,
               honor_manual_steps=False,
               # v14.339 HyperFlow H3 Flash: 4/6/8-step 固定调度 + cfg 1.0,
               # 不适用 H3 底座"音频至少 12 步"的自动提步保护。
               hyperflow_mode=False,
               # v14.238 MiniMaxH3 Director 极速双采移植:
               #   refine_sampler: 二采采样器独立选择(参考插件一采 res_multistep、
               #     二采 euler); None/"inherit (跟随一采)" 时跟随一采采样器。
               #   refine_sigmas: 外接 SIGMAS 覆盖内部 beta 调度(Refine 节点
               #     原版行为, 参考插件用 BasicScheduler/ManualSigmas 直连)。
               refine_sampler=None, refine_sigmas=None,
               # v14.276: 一镜到底·2K双采的"干净优先"单次采样。倍率已按 token
               # 预算压到 Sol-Attn 健康区, 整段一次调用即可; 时间分块(每段独立
               # 加噪 + 独立 seed)会在接缝处闪烁、段内碎花, 该档一律禁用。
               refine_single_pass=False,
               # v14.281: MV 双采档忠实原版 —— 工作流里 temporal_chunk_tokens=0
               # 就是"整段一次二采", 不允许 v14.270 的自动时间分块把它重新切成
               # 4 段独立采样(段间换 seed 会在接缝闪烁/段内碎花)。
               refine_no_temp_chunk=False,
               # v14.317: 本段 motion context 裁掉的上下文帧数 —— 只用于把
               # latent 行号换算成成片帧号(日志用), 不参与采样。
               one_shot_trim_frames=0):
    if int(steps) < 1:
        raise ValueError("MiniMax H3 Extender: steps must be >= 1.")

    # v14.250 (2026-10-29): 二采 OOM/塌陷回退标记。回退后的 latent 只是「一采
    # latent 插值放大」, 不是采样产物 —— 在链几何上直接 VAE 解码会得到 16px 周期
    # 的马赛克玻璃条纹(实机一镜到底 clip2+ 复现, 条纹周期 = latent cell)。记下
    # 一采几何, 交给 Disk Cache 解码时先缩回一采再像素放大。
    _refine_fallback_hw = None

    # v14.195: 音频渲染质量保护（渲染环节治本, 非渲染后处理）——
    # 诊断(h3_clip_250 样本 + 5 个历史渲染): 所有电影工厂渲染输出均带恒定
    # 低频轰鸣(100-200Hz 占全频 ~60%、全程无静音、200-400Hz 人声带被盖住),
    # 而参考音频(lip_audio)本身干净(完美标准: 200-400Hz 占 73%)。根因:
    # ① lip_audio 对口型模式一采音频=参考原声 latent 锁定(干净), 二采
    #   refine_audio_denoise=0.7 把它 70% 重噪后仅 4 步重画(官方音频下限
    #   12 步) → 干净参考被重绘成低频轰鸣; ② 非 lip 模式(ref_audio 条件
    #   配音)一采 <12 步生成音频同样劣化。
    # 修复: 音频要么锁定保持原声(lip 模式默认), 要么 ≥12 步生成/重绘;
    # 环境变量 BSAI_H3_AUDIO_QUALITY=0 可一键关闭全部自动行为(回退旧参数)。
    _has_audio = False
    _lip_locked = False
    try:
        _m_probe = latent.get("samples")
        _mem_probe, _nt_probe = _ff_extract_members(_m_probe)
        if _nt_probe and len(_mem_probe) >= 2:
            _has_audio = True
            _nm_probe = latent.get("noise_mask")
            if _nm_probe is not None:
                _nmm_probe, _ = _ff_extract_members(_nm_probe)
                if len(_nmm_probe) >= 2 and int(torch.count_nonzero(_nmm_probe[1])) == 0:
                    _lip_locked = True
    except Exception as _probe_err:
        _has_audio, _lip_locked = False, False
    _audio_quality_on = os.environ.get("BSAI_H3_AUDIO_QUALITY", "1") != "0"
    if _has_audio:
        print(f"[H3 Extender] v14.195 音频渲染质量保护: 检测到 AV 双成员 latent, "
              f"lip_audio锁定={'是' if _lip_locked else '否'}, 自动保护={'开' if _audio_quality_on else '关(环境变量)'}")

    # v14.81: safety net for the payload row-order guard. The module installs
    # itself at import; re-asserting here puts it back on top in the rare case
    # something stacked over it after startup, and covers graphs that reached
    # the sampler before the import-time install could. Self-detecting, so the
    # per-clip calls after the first are a cheap no-op.
    if not _row_order_patch_applied():
        _apply_row_order_patch()

    _n_dropped = _drop_mismatched_adaln_patches(model)
    if _n_dropped:
        print(f"[H3 Extender] shape-aware dropped {_n_dropped} adaln lora patches mismatched with base (pruned/full auto, attn/mlp kept)", flush=True)

    # P0 (2026-10-17): 官方双轨迹采样注入 (MiniMaxH3SigmaShift 等效).
    # 在 guider 创建前对 model clone+patch: ModelSamplingAV 驱动采样器 sigma,
    # transformer_options 双 shift 让模型内部推导 audio schedule.
    if dual_track_shift:
        # v14.249 (S3): shift A/B env 门 —— BSAI_H3_SHIFT_VIDEO / BSAI_H3_SHIFT_AUDIO
        # 覆盖档位 shift 值, 供一镜到底漂移 A/B (官方: Balanced 漂移→shift 12;
        # 各档当前已统一 12.0/3.0, A/B 6/10/12 无需改代码)。不设 env 行为不变。
        try:
            _sv_env = os.environ.get("BSAI_H3_SHIFT_VIDEO", None)
            _sa_env = os.environ.get("BSAI_H3_SHIFT_AUDIO", None)
            if _sv_env or _sa_env:
                _sv_use = float(_sv_env) if _sv_env else float(shift_video)
                _sa_use = float(_sa_env) if _sa_env else shift_audio
                print(f"[H3 Extender] v14.249 shift env 覆盖: video {shift_video}->{_sv_use}, "
                      f"audio {shift_audio}->{_sa_use}", flush=True)
                shift_video, shift_audio = _sv_use, _sa_use
        except (TypeError, ValueError):
            pass
        # v14.152: shift_audio 可能已是 None（0.0 的映射），不再 float()
        model = _apply_h3_dual_track_shift(model, float(shift_video), shift_audio)
    # P2 (2026-10-17): SelfLift H3 TST 少步数画质补偿 (时间状态传输).
    if tst_enable:
        model = _apply_h3_tst(model, True, float(tst_tau))

    # v14.195: 一采音频步数保护 —— 音频由模型生成时(非 lip 锁定), 一采步数
    # <12(官方音频可用下限)会把配音生成出恒定低频轰鸣/含混吞音(实测 8 步
    # 档样本: 100-200Hz 占 59.5%, 全程无静音)。lip 锁定模式一采音频不采样
    # (mask=0), 步数不影响音频, 不提升(保持档位速度与画质)。
    if _has_audio and not _lip_locked and _audio_quality_on and int(steps) < 12 and not hyperflow_mode:
        if honor_manual_steps:
            print(f"[H3 Extender] v14.205 custom 手动步数优先: 一采 {int(steps)} 步 < 音频 12 步下限, "
                  f"按用户设置执行(配音质量可能下降; 要干净配音请接 lip_voice 或设 12 步)")
        else:
            print(f"[H3 Extender] v14.195 音频生成保护: 一采 {int(steps)} 步 < 官方音频 "
                  f"12 步下限, 自动提升到 12 步(根治低频轰鸣/含混配音; 如须回退 "
                  f"设 BSAI_H3_AUDIO_QUALITY=0)")
            steps = 12

    guider = _BasicGuider(model)
    # v14.169: FastH3 Omni 蒸馏契约 = guidance 1.0 单前向(无 CFG)。
    # CFGGuider 默认 cfg=8 双前向会过驱动蒸馏模型 → 过曝/伪影/糊
    # (cfg=8 是 FastH3 V2 老模型的用法; Omni 8步蒸馏必须 guidance 1.0)。
    if omni_8step_mode:
        guider.cfg_scale = 1.0
        print("[H3 Extender] v14.169 Omni 8步单采: 一采 guidance 1.0 (官方蒸馏契约, 单前向)")
    elif hyperflow_mode:
        # v14.339: HyperFlow H3 Flash 官方契约 = CFG 1.0 无分类器引导 (单前向)。
        # 4/6/8 步音视频是蒸馏目标, 不能套用 H3 底座"音频至少 12 步"的提步保护。
        guider.cfg = 1.0
        print(f"[H3 Extender] v14.339 HyperFlow H3 Flash: 一采 {int(steps)} 步 euler + "
              "HyperFlow 固定调度, CFG 1.0 单前向 (官方契约); 音频 12 步保护已跳过")
    guider.set_conds(conditioning)
    sampler = comfy.samplers.sampler_object(str(sampler_name))
    sigmas = _sigmas(model, scheduler, steps, denoise)

    latent_out = latent.copy()
    latent_image = latent["samples"]
    latent_image = comfy.sample.fix_empty_latent_channels(
        model,
        latent_image,
        latent.get("downscale_ratio_spacial", None),
        latent.get("downscale_ratio_temporal", None),
    )
    latent_out["samples"] = latent_image

    batch_inds = latent_out.get("batch_index", None)
    noise = comfy.sample.prepare_noise(latent_image, int(seed), batch_inds)
    noise_mask = latent_out.get("noise_mask", None)

    # v14.240 (2026-10-28): 二采段头锁 keep —— 提取一采 noise_mask 的段头锁行数
    # (video 成员头部连续 mask=0 的行 = motion context trim 区的 latent 行)。
    # 一采已把段头锁成上一段尾延续画面; 二采若从加噪底重绘段头, 接缝被二次
    # 重绘 → 段间跳帧/漂移(双采无缝档实测跳帧根因)。二采对同样行数锁 keep。
    _os_head_rows = 0
    try:
        _nm_os = latent.get("noise_mask")
        if _nm_os is not None:
            _nmm_os, _ = _ff_extract_members(_nm_os)
            _mvv_os = _nmm_os[0]
            if _mvv_os is not None and _mvv_os.dim() in (4, 5):
                _zr_os = 0
                for _r_os in range(int(_mvv_os.shape[2])):
                    if float(_mvv_os[:, :, _r_os].min()) <= 0.0:
                        _zr_os += 1
                    else:
                        break
                if _zr_os >= 1:
                    _os_head_rows = _zr_os
                    print(f"[H3 Extender] v14.240 二采段头锁: 检测到一采段头锁 {_os_head_rows} latent 行, 二采将保持该区(不二次重绘)")
    except Exception:
        _os_head_rows = 0

    x0_output = {}
    total_steps = sigmas.shape[0] - 1

    # Create a custom callback that sends latent preview frames to the
    # frontend CLIP preview panel (instead of ComfyUI's built-in node preview).
    previewer = None
    if owner_id is not None and clip_index >= 0:
        try:
            previewer = latent_preview.get_previewer(model.load_device, model.model.latent_format)
        except Exception as _e:
            print(f"[H3 Extender] latent previewer init failed: {_e}")
            previewer = None
        if previewer is None:
            # Fallback: create a simple latent2rgb previewer using first 3 channels
            try:
                preview_x0_test = latent_image[:1]
                if hasattr(preview_x0_test, "is_nested") and preview_x0_test.is_nested:
                    preview_x0_test = preview_x0_test.tensors[0]
                ch = int(preview_x0_test.shape[1])
                # Build simple identity-like factors: map first 3 channels to RGB
                factors = [[1.0 if i == c else 0.0 for i in range(ch)] for c in range(min(3, ch))]
                while len(factors) < 3:
                    factors.append([0.0] * ch)
                # v1.75 (2026-09-15 fix #11): 兼容不同 ComfyUI 版本的 Latent2RGBPreviewer。
                # 新版构造时 transpose(0,1) (linear 需要 (in,out)); 4090 pro_v36_lig 等旧版
                # 不转置 (linear 直接 x@W 需 (in,out) 语义不同), 传 (3,24) 会每步刷
                # "mat1 and mat2 shapes cannot be multiplied" 报错。
                # 解法: 构造后用 2x2 探针实测 decode, 失败自动用转置 factors 重试,
                # 再失败回退 None (走下方手动 RGB 预览, 不依赖 latent_preview 实现)。
                previewer = None
                _probe_ok = False
                for _factors_try in (factors, [list(r) for r in zip(*factors)]):
                    try:
                        _pv_try = latent_preview.Latent2RGBPreviewer(_factors_try)
                        _probe = _pv_try.decode_latent_to_preview(
                            preview_x0_test[:, :, :2, :2]
                            if preview_x0_test.ndim == 4 else preview_x0_test[:, :, 0, :2, :2])
                        previewer = _pv_try
                        _probe_ok = True
                        break
                    except Exception:
                        continue
                if _probe_ok:
                    print(f"[H3 Extender] using fallback Latent2RGB previewer (channels={ch})")
                else:
                    print(f"[H3 Extender] fallback previewer 两种 factors 均失败, 用手动 RGB 预览")
            except Exception as _e2:
                print(f"[H3 Extender] fallback previewer also failed: {_e2}")
                previewer = None

    pbar = comfy.utils.ProgressBar(total_steps)
    _last_sent_step = {"v": -1}

    _cb_t0 = {"t": None}
    def _latent_preview_callback(step, x0, x, total_steps_arg):
        # v1.55: 每步耗时诊断——定位第 4 步固定 ~430s 的瓶颈(计算/IO/卸载)
        try:
            import time as _t55
            _now55 = _t55.time()
            if _cb_t0["t"] is not None:
                print(f"[H3 Extender] step耗时诊断: step={step}/{total_steps_arg} 距上步 {_now55-_cb_t0['t']:.1f}s")
            _cb_t0["t"] = _now55
        except Exception:
            pass
        pbar.update_absolute(step + 1, total_steps_arg)
        if owner_id is not None:
            # Only send every 2nd step to reduce bandwidth
            if step == total_steps_arg - 1 or step % 2 == 0:
                try:
                    preview_x0 = x0
                    if hasattr(preview_x0, "is_nested") and preview_x0.is_nested:
                        preview_x0 = preview_x0.tensors[0]
                    if previewer is not None:
                        img = previewer.decode_latent_to_preview(preview_x0)
                        # v1.46: H3 latent 预览是 latent 格点直接映射(60x34 等),
                        # 不放大则前端看到的就是一张极小的缩略图, 视觉上"糊成一片"。
                        # 放大到实际视频分辨率(LANCZOS 平滑), 让一采预览真实可辨。
                        try:
                            _pv_w, _pv_h = img.size
                            _pv_scale = 16
                            if _pv_w < 320 or _pv_h < 320:
                                img = img.resize(
                                    (_pv_w * _pv_scale, _pv_h * _pv_scale),
                                    Image.LANCZOS,
                                )
                        except Exception:
                            pass
                    else:
                        # Manual fallback: take first 3 channels, normalize to 0-255
                        # Handle 5D video latents by taking the first time step
                        t = preview_x0
                        if t.ndim == 5:
                            t = t[:, :, 0]
                        t = t[:1, :3] if t.shape[1] >= 3 else t[:1, :1].expand(1, 3, -1, -1)
                        t = ((t - t.min()) / (t.max() - t.min() + 1e-8) * 255).clamp(0, 255)
                        t = t.to(device="cpu", dtype=torch.uint8)
                        img = Image.fromarray(t[0].movedim(0, 2).numpy())
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=60)
                    jpeg_bytes = buf.getvalue()
                    if step == 0 or step == total_steps_arg - 1:
                        print(f"[H3 Extender] latent preview: clip={clip_index} step={step+1}/{total_steps_arg} "
                              f"bytes={len(jpeg_bytes)} previewer={'yes' if previewer else 'manual'}")
                    _send_latent_preview_frame(owner_id, clip_index, step + 1, total_steps_arg, jpeg_bytes)
                except Exception as _e:
                    print(f"[H3 Extender] latent preview callback error: {_e}")
                    import traceback
                    traceback.print_exc()

    callback = _latent_preview_callback if owner_id is not None else None
    disable_pbar = not comfy.utils.PROGRESS_BAR_ENABLED
    # v1.52: force_full_load=True 把 21.8GB 全拉满 -> process_conds OOM (物理 23.86GB).
    # 改走 ComfyUI 自带预算: 把 EXTRA_RESERVED_VRAM 从 CLI 的 0 抬到 5.5GB, 让
    # minimum_inference_memory = 0.8+5.5 = 6.3GB; lowvram_model_memory = free - minimum_inference
    # ≈ 22 - 6.3 = 15.7GB 权重驻留, 尾部 ~6GB offload, 留 ~6GB 给 conds(cross_attn)+workspace.
    # 不再 force_full_load, 也不覆写 outer_sample. ComfyUI 自己按预算装, process_conds 有地放.
    try:
        import torch as _t1
        import comfy.model_management as _mm1
        # v1.84: 根治量化权重低显存流转的无声闪退。用户启动参数 --async-offload
        # 使 NUM_STREAMS>=1, int8量化权重(comfy_quant)在 CPU<->GPU 异步搬运时
        # 与 forward 复用存在竞态, 导致 step2/8 后进程无声消失(无traceback/驱动事件)。
        # 这里强制 NUM_STREAMS=0 (等价 --disable-async-offload), 搬运同步化。
        try:
            if getattr(_mm1, "NUM_STREAMS", 0) != 0:
                _mm1.NUM_STREAMS = 0
                print("[H3 Extender] 已禁用异步 offload (NUM_STREAMS=0, 同步搬运防量化权重竞态闪退)", flush=True)
        except Exception:
            pass
        # v1.81: 一采前也释放 DynamicVRAM staged, 保证一采起始显存充足 (4090 保险)。
        try:
            _release_dynamic_vram("pass1")
        except Exception:
            pass
        _t1.cuda.empty_cache()
        try: _t1.cuda.ipc_collect()
        except Exception: pass
        _free_os, _tot_os = _t1.cuda.mem_get_info()
        _free_os /= 1024 ** 3; _tot_os /= 1024 ** 3
        # v1.84: reserve 5.5->4.0GB（实测: 2.0全量驻留->free=0 process_conds OOM;
        # 3.0->free=0.22GB 仍OOM; 5.5->驻留16.2+offload3.7 流转崩; 4.0->驻留~17.5GB
        # +offload~2GB, free~2.5GB, 流转量减半）。量化权重低显存流转在
        # cudaMallocAsync+async-offload 下会无声硬崩(step2/8 后进程消失),
        # 配合启动参数去掉 --async-offload 根治。
        try: _mm1.EXTRA_RESERVED_VRAM = int(4.0 * 1024 ** 3)
        except Exception: pass
        _cm_u, _cm_t = _commit_gb()
        print(f"[H3 Extender] 一采前显存: OS free={_free_os:.2f}GB / {_tot_os:.1f}GB (allocated={_t1.cuda.memory_allocated()/1024**3:.2f}GB), commit={_cm_u:.1f}/{_cm_t:.1f}GB, reserve->4.0GB")
        # v1.91: 一采前同样解除 16GB fraction 限制(与二采一致), 避免
        # staged 15.25GB + workspace 临界超限. 全链路可用物理 23.86GB.
        try:
            _cur_frac91b = _t1.cuda.get_per_process_memory_fraction()
            if _cur_frac91b < 1.0:
                _t1.cuda.set_per_process_memory_fraction(1.0)
                print(f"[H3 Extender] v1.91 一采前解除 fraction 限制: {_cur_frac91b:.3f} -> 1.0")
        except Exception as _e91b:
            print(f"[H3 Extender] v1.91 一采前 fraction reset 失败: {_e91b}")
        # v14.186: 显存预算自检 —— 权重装不下时明确告警，避免用户白跑一整轮
        # (实测 19.5GB DiT 在 24GB 卡上不走驻留 → 每步 800s+，而驻留时 100-200s)。
        def _h3_warn_stream_fallback(_total_gb, _free_gb):
            _avail = max(0.0, float(_free_gb) - 4.0)
            print(f"[H3 Extender] ⚠️ v14.186 显存预算不足: DiT 权重 {float(_total_gb):.1f}GB > "
                  f"可用 {float(_free_gb):.1f}GB − reserve 4.0GB = {_avail:.1f}GB")
            print("[H3 Extender] ⚠️ 本段将走 DynamicVRAM 逐层流式搬运(同步, 无法与计算重叠): "
                  "实测每步可能 600-900s (权重整块驻留时 100-200s)")
            print("[H3 Extender] ⚠️ 建议: ①换剪枝/int8 小模型(如 fasth3_omniref_8step_pruned_int8_convrot, "
                  "配「FastH3 Omni 8步单采」档)让权重整块驻留; ②或换更大显存显卡; "
                  "③降低分辨率/上下文只能减 activation, 解决不了权重装不下")
        # v14.250: 流式 vbar watermark 的 activation headroom 改为可配置。
        # watermark = free − headroom, 决定有多少权重页能留在显存:
        #   headroom 越小 -> 驻留越多 -> 每步换页越少(越快);
        #   但 process_conds / Veda predictor / ctx 帧 activation 余量越小, 过小 OOM。
        # 原硬编码 5.0GB(流式) / 4.5GB(free<18GB 分支), 这里统一默认 3.5GB。
        # 24GB 卡装 20.6GB 权重时, 设 BSAI_H3_STREAM_HEADROOM_GB=2.0 可让几乎全部
        # 权重驻留(换页最少->最快), 代价是 activation 余量仅 2GB(风险自担)。
        try:
            _h3_stream_headroom = float(os.environ.get("BSAI_H3_STREAM_HEADROOM_GB", "3.5"))
        except Exception:
            _h3_stream_headroom = 3.5
        _h3_stream_headroom = max(1.0, min(8.0, _h3_stream_headroom))
        if _free_os >= 18.0:
            _mm1.load_models_gpu([model])   # reserve 4.0 预算: 驻留 ~17.5GB, 尾部 ~2GB offload
            _t1.cuda.synchronize()
            try:
                _res = model.loaded_size() / 1024 ** 3
                _tot = model.model_size() / 1024 ** 3
                print(f"[H3 Extender] 一采前 DiT 驻留: resident={_res:.1f}GB / total={_tot:.1f}GB (offload ~{_tot-_res:.1f}GB)")
                # v14.174 (2026-10-23): load_models_gpu 后 resident 无效回退.
                # int8 H3 total≈20.6GB, 24GB 卡 reserve 4GB 可用 ~20GB —— 装不下
                # 全量, load_models_gpu 静默返回 resident=0.0GB. 但它会往
                # current_loaded_models 里插 LoadedModel 占位, 污染 DynamicVRAM
                # staged 按需加载的调度状态, 导致采样时每次 forward 都走全流式
                # CPU↔GPU 搬运 + workspace 临界 → step 0/4 直接 OOM
                # (int8_linear 申请 int32 输出缓冲时爆掉).
                # 修复: resident < 4GB 说明连核心 transformer 层都没驻留,
                # 调用 _ff_unregister_model 摘除 LoadedModel + soft_empty_cache,
                # 让 DynamicVRAM 回到干净 staged 状态, forward 时按需搬运.
                # 注: ComfyUI 无公开 unload_model() API (全局 _mm.unload_model 都是
                # silent no-op, 已统一替换为 _ff_unregister_model).
                if _res < 4.0:
                    _ff_unregister_model(model, label="一采-resident无效")
                    print(f"[H3 Extender] v14.174 驻留无效(resident={_res:.1f}GB<4GB), "
                          f"回退 DynamicVRAM 按需流式 (total={_tot:.1f}GB > 可用{_free_os:.1f}GB-reserve)")
                    _h3_warn_stream_fallback(_tot, _free_os)
                    # v14.237 (2026-10-28): 流式模式下动态降 reserve 4.0->2.5GB。
                    # 根因(单采OM/双采 clip2+ 实测): resident=0 走 DynamicVRAM 逐层搬运时,
                    # reserve=4.0GB 让 ComfyUI 认为可用 = free-4.0, DiT 20.6GB 流式 peak
                    # ~17.6GB 卡在可用边缘(clip1 free=22.27 -> 可用18.27, peak 17.6+output
                    # 0.7 = 18.3 超 0.03GB) -> 第一个 forward int8_linear torch.empty OOM。
                    # resident 模式 reserve=4.0 是给 process_conds(causal_mask N×N)留的,
                    # 流式模式权重不在 GPU, conds 空间更宽裕, reserve 可降到 2.5GB,
                    # 多 1.5GB 给权重块搬运。clip0 首次 CUDA context 干净能挤过, clip1+ 碎片必崩。
                    try:
                        _mm1.EXTRA_RESERVED_VRAM = int(2.5 * 1024 ** 3)
                        _t1.cuda.empty_cache()
                        _t1.cuda.synchronize()
                        _free_after = _t1.cuda.mem_get_info()[0] / 1024 ** 3
                        print(f"[H3 Extender] v14.237 流式 reserve 4.0->2.5GB, "
                              f"empty_cache 后 free={_free_after:.2f}GB (多 1.5GB 给权重搬运)")
                    except Exception as _rsv_e:
                        print(f"[H3 Extender] v14.237 reserve 调整失败(忽略): {_rsv_e}")
                    # v14.238 (2026-10-28): 流式 vbar 驻留水位封顶。
                    # 实测(v14.237 已生效仍 OOM): DynamicVRAM 的 vbar watermark 默认
                    # = max_size(21GB), fault 调入的权重页"只进不出", 流式峰值爬到
                    # ~18-20GB 后 int8_linear 的 torch.empty(m,n) 无空间可分配 ->
                    # CUDA OOM (memory summary 里 torch reserved 仅 2GB 却 malloc
                    # 失败, 正是 native vbar 占用了 torch 看不到的显存)。
                    # 修复: 把 watermark 压到 free-4.0GB, 超过水位强制换出高位页,
                    # 给 activation(qkv_proj out / process_conds) 留足余量。
                    # 代价: 高位块反复 fault, 每步更慢; 但不再 OOM。
                    # v14.239 (2026-10-28): Veda Sparse Attention predictor (275MB fp8) +
                    # context帧 activation 额外吃 ~1GB, headroom 4.0->5.0GB。
                    # clip0 干净 CUDA context 能挤过 4.0GB, clip1+ 带 Veda predictor
                    # 驻留 torch 内存 + context 5帧 attention activation 顶爆。
                    try:
                        _vbar238 = None
                        if hasattr(model, "_vbar_get"):
                            _vbar238 = model._vbar_get(create=False)
                        if _vbar238 is not None:
                            _wm238 = int(max(2.0, _free_after - _h3_stream_headroom) * 1024 ** 3)
                            _vbar238.set_watermark(_wm238)
                            print(f"[H3 Extender] v14.250 流式 vbar watermark -> "
                                  f"{_wm238/1024**3:.1f}GB (free {_free_after:.1f}GB − "
                                  f"{_h3_stream_headroom:.1f}GB headroom)")
                        else:
                            print(f"[H3 Extender] v14.238 未找到 vbar(非动态模型?), 跳过水位封顶")
                    except Exception as _wm238e:
                        print(f"[H3 Extender] v14.238 watermark 设置失败(忽略): {_wm238e}")
            except Exception: pass
        else:
            print(f"[H3 Extender] 一采前 free={_free_os:.1f}GB < 18GB, 走 ComfyUI 按需流式")
            # v14.237: 同上, free<18GB 流式分支也降 reserve。
            try:
                _mm1.EXTRA_RESERVED_VRAM = int(2.5 * 1024 ** 3)
                _t1.cuda.empty_cache()
                _t1.cuda.synchronize()
            except Exception: pass
            # v14.238: free<18GB 更紧, 同样给 vbar 水位封顶(free-3.5GB), 防止
            # fault 调入爬满后 activation 无空间。
            try:
                _free_238 = _t1.cuda.mem_get_info()[0] / 1024 ** 3
                _vbar238b = None
                if hasattr(model, "_vbar_get"):
                    _vbar238b = model._vbar_get(create=False)
                if _vbar238b is not None:
                    _wm238b = int(max(1.5, _free_238 - _h3_stream_headroom) * 1024 ** 3)
                    _vbar238b.set_watermark(_wm238b)
                    print(f"[H3 Extender] v14.250 流式(free<18GB) vbar watermark -> "
                          f"{_wm238b/1024**3:.1f}GB (free {_free_238:.1f}GB − "
                          f"{_h3_stream_headroom:.1f}GB headroom)")
            except Exception as _wm238be:
                print(f"[H3 Extender] v14.238 watermark 设置失败(忽略): {_wm238be}")
            try:
                _h3_warn_stream_fallback(model.model_size() / 1024 ** 3, _free_os)
            except Exception:
                pass
    except Exception as _lp1:
        print(f"[H3 Extender] 一采前驻留预算设置失败(走按需流式): {_lp1}")
    # ---- BSAI 协同：GPU 主采样租约（失败不阻断采样，仅叠加租约管理） ----
    _bsai_alloc = None
    try:
        _bsai_alloc = BSAIOrch.allocate("sampling", requester="8191")
        if not _bsai_alloc.ok:
            print(f"[H3 Extender] SDK 未取得 gpu1_sampling 租约({_bsai_alloc.reason})，仍按原逻辑采样", flush=True)
    except Exception as _bsai_ae:
        print(f"[H3 Extender] SDK allocate 异常(忽略): {_bsai_ae}", flush=True)
        _bsai_alloc = None
    # v14.198 首步拆分诊断: 实测一采 step1=1217s, step2~12=45-48s。探针在首次
    # DIFFUSION_MODEL 前向入口打印"采样开始→前向"间隔(= process_conds/编码),
    # 前向返回后再打一次, 用来判定 1217s 花在 conds 还是首次前向(权重换页/op 编译).
    _ff_probe198 = {"t0": time.time(), "t1": None, "done": False}
    def _ff_first_forward_probe198(executor, x, timestep, context, transformer_options, **kwargs):
        if _ff_probe198["t1"] is None:
            _ff_probe198["t1"] = time.time()
            print(f"[H3 Extender] v14.198 首步拆分: 采样开始→首次前向 "
                  f"{_ff_probe198['t1'] - _ff_probe198['t0']:.1f}s (process_conds/编码)", flush=True)
        if not _ff_probe198["done"]:
            # v14.340: 模型侧掩码探针 —— 采样器收到的 mask 与模型收到的 denoise_mask
            # 是两条独立通路(前者在 KSamplerX0Inpaint 里做 x/out 混合, 后者经
            # extra_conds 进 _forward 做逐 token timestep 重标定 + out*mask)。
            # 这里打印模型这条通路实际看到的 mask, 以及 x 是否真是噪声。
            try:
                _dm = kwargs.get("denoise_mask")
                _pl = kwargs.get("minimax_payload") or {}
                _ts = float(timestep.flatten()[0]) if hasattr(timestep, "flatten") else float(timestep)
                _xv = x[0] if isinstance(x, (list, tuple)) else x
                print(f"[H3 Recast Probe-2] model-side: timestep={_ts:.1f} "
                      f"denoise_mask={'None' if _dm is None else tuple(_dm.shape)} "
                      f"x0={tuple(_xv.shape)} |x0|={float(_xv.float().abs().mean()):.3f} "
                      f"payload_keys={sorted(_pl.keys())}", flush=True)
                if _dm is not None:
                    _d = _dm.to(torch.float32)
                    if _d.dim() == 5:
                        _pool = _d[0, 0].reshape(_d.shape[2], _d.shape[3] // 2, 2,
                                                 _d.shape[4] // 2, 2).amax(dim=(2, 4))
                        _frac = float((_pool >= 0.5).float().mean())
                        print(f"[H3 Recast Probe-2] model-side token grid: "
                              f"mean={float(_d.mean()):.4f} min={float(_d.min()):.3f} "
                              f"max={float(_d.max()):.3f} 生成token占比={_frac * 100:.1f}%",
                              flush=True)
                    else:
                        print(f"[H3 Recast Probe-2] model-side mask(dim={_d.dim()}): "
                              f"mean={float(_d.mean()):.4f} max={float(_d.max()):.3f}", flush=True)
            except Exception as _p2e:
                print(f"[H3 Recast Probe-2] 探针失败(忽略): {_p2e}", flush=True)
        out = executor(x, timestep, context, transformer_options, **kwargs)
        if not _ff_probe198["done"]:
            _ff_probe198["done"] = True
            print(f"[H3 Extender] v14.198 首步拆分: 首次前向 "
                  f"{time.time() - _ff_probe198['t1']:.1f}s (含权重换页/op 编译), "
                  f"首步合计 {time.time() - _ff_probe198['t0']:.1f}s", flush=True)
        return out
    try:
        import comfy.patcher_extension as _pe198
        model.add_wrapper_with_key(_pe198.WrappersMP.DIFFUSION_MODEL,
                                   "bsai_first_step_probe", _ff_first_forward_probe198)
    except Exception as _e198:
        print(f"[H3 Extender] v14.198 首步探针安装失败(忽略): {_e198}")

    # v14.340 一次性诊断: 视频替换(半重绘)掩码探针。BSAI_H3_RECAST_PROBE=0 可关。
    # 目的: 确认送达采样器的 noise_mask 与 sigmas[0] 是否与代码预期一致
    # (1=重绘人物 / 0=锁源画面, σ0=1.0)。重绘画(keep)区起点 x 若与源 latent 高度相关,
    # 说明该区没进噪声、人物不会被替换。
    if str(os.environ.get("BSAI_H3_RECAST_PROBE", "1")).strip().lower() not in ("0", "false", "off"):
        try:
            _rpb_mem = _ff_extract_members(latent_image)[0]
            _rpb_nm = _ff_extract_members(noise_mask)[0] if noise_mask is not None else []
            _rpb_no = _ff_extract_members(noise)[0]
            _rpb_ms = model.get_model_object("model_sampling")
            print(f"[H3 Recast Probe] σ0={float(sigmas[0]):.4f} steps={len(sigmas) - 1} "
                  f"latent_members={[tuple(t.shape) for t in _rpb_mem]} "
                  f"mask_members={[tuple(t.shape) for t in _rpb_nm]}", flush=True)
            for _rpi, _rpl in enumerate(_rpb_mem):
                if _rpi >= len(_rpb_nm):
                    print(f"[H3 Recast Probe]  m{_rpi} 无 mask", flush=True)
                    continue
                _rpm = _rpb_nm[_rpi].to(dtype=torch.float32)
                _rpline = (f"[H3 Recast Probe]  m{_rpi} mean={float(_rpm.mean()):.4f} "
                           f"min={float(_rpm.min()):.3f} max={float(_rpm.max()):.3f} "
                           f"全1行={int((_rpm.flatten(2) >= 0.999).all(dim=2).sum())}")
                try:
                    _rpx = _rpb_ms.noise_scaling(sigmas[0], _rpb_no[_rpi], _rpl)
                    _rpv, _rpr = _rpx.flatten(), _rpl.flatten()
                    _rpw = _rpm.expand_as(_rpx).flatten()
                    for _tag, _sel in (("重绘画", _rpw > 0.5), ("锁keep", _rpw <= 0.5)):
                        if int(_sel.sum()) > 0:
                            _rpc = float(torch.nn.functional.cosine_similarity(
                                _rpv[_sel], _rpr[_sel], dim=0))
                            _rpline += (f" {_tag}: corr(x,源)={_rpc:+.3f} "
                                        f"|x|={float(_rpv[_sel].abs().mean()):.3f} "
                                        f"|源|={float(_rpr[_sel].abs().mean()):.3f}")
                except Exception as _rpe:
                    _rpline += f" 相关性计算失败: {type(_rpe).__name__}: {_rpe}"
                print(_rpline, flush=True)
        except Exception as _rperr:
            print(f"[H3 Recast Probe] 探针失败(忽略): {_rperr}", flush=True)

    # v14.352: 源片 cond 早停释放 —— σ 降到阈值以下后，把 minimax_refs 里的源片
    # video block 摘掉，只留参考图（后半程让身份主导，而不是被源片像素按住）。
    _vg_cb = callback
    try:
        _vrp = globals().get("_VIGGLE_RELEASE_POS", None)
        if _vrp is not None:
            _vru = float(globals().get("_VIGGLE_RELEASE_UNTIL", 0.9) or 0.9)
            _vrs = {"done": False}

            def _vg_release_cb(_step, _x0, _x, _total):
                try:
                    if not _vrs["done"]:
                        _s = float(sigmas[min(int(_step), len(sigmas) - 1)])
                        if _s < _vru:
                            # guider.conds 里存的是已编码的 dict，直接塞 conditioning
                            # 列表会在 calc_cond_batch 崩；必须走 inner_set_conds 重建。
                            _cond_rel = dict(conditioning)
                            _cond_rel["positive"] = _vrp
                            guider.inner_set_conds(_cond_rel)
                            _vrs["done"] = True
                            print(f"[H3 Extender] v14.352 源片 cond 早停释放: "
                                  f"step={_step} σ={_s:.4f} < {_vru} → cond 只留参考图",
                                  flush=True)
                except Exception as _vre:
                    print(f"[H3 Extender] v14.352 cond 释放失败(忽略): {_vre}", flush=True)
                    _vrs["done"] = True
                if callback is not None:
                    return callback(_step, _x0, _x, _total)
                return True

            _vg_cb = _vg_release_cb
    except Exception as _vge:
        print(f"[H3 Extender] v14.352 cond 释放挂载失败(忽略): {_vge}", flush=True)

    try:
        samples = guider.sample(
            noise,
            latent_image,
            sampler,
            sigmas,
            denoise_mask=noise_mask,
            callback=_vg_cb,
            disable_pbar=disable_pbar,
            seed=int(seed),
        )
    finally:
        try:
            model.model_options["wrappers"][_pe198.WrappersMP.DIFFUSION_MODEL].pop(
                "bsai_first_step_probe", None)
        except Exception:
            pass
        if _bsai_alloc is not None:
            try:
                _bsai_alloc.release()
            except Exception:
                pass
    samples = samples.to(comfy.model_management.intermediate_device())

    # ── v14.317: 段内硬切拦截(结果层) ─────────────────────────────────────
    # 动机(用户 2026-11-05 实测): clip2 f48 从"蓝调入夜胸像"一帧跳到"橙粉落日
    # 海边中景" —— 像素域帧间差 12.26x 中位、低频差 24.29x 中位, 像素层与场景层
    # 同时暴涨。v14.312 的 prompt 层规则在代码里却没拦住这一刀: 光线时间线
    # 倒流(入夜又回到落日)是**条件文本内部**的矛盾, 模型在某一帧突然"想起"
    # 脚本里的落日, 一帧硬切过去。文字规则能减少概率, 不能保证。
    #
    # 所以拦截做在**结果层**: 一采 latent 里检出这种硬切就换 seed 重采样。
    # 判据用**真实一采 latent** 标定过(阈值 1.6/1.8, 相位感知基线),
    # 详见函数 docstring 与 CHANGELOG。
    #
    # 重采样保持同一份 latent_image / noise_mask —— 段间 motion context 锚点
    # (上一段尾 latent)不动, 所以段间接缝不受影响; 只换噪声种子重掷这一段。
    _cut_guard_on = str(os.environ.get("BSAI_H3_CUT_GUARD", "1")).strip().lower() \
        not in ("0", "false", "off")
    try:
        _cut_retries = max(0, int(os.environ.get("BSAI_H3_CUT_RETRIES", "2")))
        _cut_pthr = float(os.environ.get("BSAI_H3_CUT_PIX_THR", "1.6"))
        _cut_lthr = float(os.environ.get("BSAI_H3_CUT_LF_THR", "1.8"))
    except Exception:
        _cut_retries, _cut_pthr, _cut_lthr = 2, 1.6, 1.8
    # v14.338: 视频替换档（带人物掩码的半重绘）里，latent 的"硬切"多半是**源片自身的镜头
    # 切换或循环接缝**——画面来源就是源视频，换 seed 也改不掉（实机实测：45s 源片由 12.59s
    # 循环拼成，row=82≈成片帧 279≈11.6s 正是循环缝，重采样 2 次仍是同样的 2 处），
    # 却每次都多花一整轮采样（≈11 分钟/段）。所以掩码型重绘不重采样，只如实记录。
    _cut_has_subject_mask = False
    try:
        _cm = noise_mask
        if isinstance(_cm, comfy.nested_tensor.NestedTensor):
            _cm = _cm.tensors[0]
        if _cm is not None:
            _cut_has_subject_mask = float(_cm.float().mean()) < 0.9
    except Exception:
        _cut_has_subject_mask = False
    if _cut_has_subject_mask:
        _cut_retries = 0
    # v14.353: Viggle 档同样跳过"换 seed 重采样" —— 硬切来自源片自身的剪辑点，
    # 换 seed 改不掉，每段只白跑一整轮采样（实测 62–73s/步 × 6 步）。
    if bool(globals().get("_VIGGLE_ACTIVE", False)):
        _cut_retries = 0
    if _cut_guard_on:
        _cut_hits = _ff_detect_latent_hard_cut(samples, _cut_pthr, _cut_lthr, one_shot_trim_frames)
        if _cut_hits:
            _cut_best = samples
            _cut_best_hits = _cut_hits
            for _cut_try in range(_cut_retries):
                _h = _cut_best_hits[0]
                print(f"[H3 Extender] v14.317 硬切拦截: 一采 latent 检出硬切 row={_h['row']} "
                      f"(≈成片帧 {_h['out_frame']:.0f}) 帧间差 {_h['dr']:.2f}x中位 "
                      f"低频差 {_h['lr']:.2f}x中位 共{len(_cut_best_hits)}处 "
                      f"-> 换 seed 重采样({_cut_try + 1}/{_cut_retries})", flush=True)
                _cut_seed = int(seed) + 7919 * (_cut_try + 1)
                _cut_alloc = None
                try:
                    _cut_alloc = BSAIOrch.allocate("sampling", requester="8191")
                except Exception:
                    _cut_alloc = None
                _cut_samples = None
                try:
                    _cut_noise = comfy.sample.prepare_noise(latent_image, _cut_seed, batch_inds)
                    _cut_samples = guider.sample(
                        _cut_noise,
                        latent_image,
                        sampler,
                        sigmas,
                        denoise_mask=noise_mask,
                        callback=callback,
                        disable_pbar=disable_pbar,
                        seed=_cut_seed,
                    )
                    _cut_samples = _cut_samples.to(comfy.model_management.intermediate_device())
                except Exception as _cut_err:
                    print(f"[H3 Extender] v14.317 硬切拦截重采样失败(保留原结果): {_cut_err}",
                          flush=True)
                    _cut_samples = None
                finally:
                    try:
                        if _cut_alloc is not None:
                            _cut_alloc.release()
                    except Exception:
                        pass
                if _cut_samples is None:
                    break
                _cut_new = _ff_detect_latent_hard_cut(
                    _cut_samples, _cut_pthr, _cut_lthr, one_shot_trim_frames)
                print(f"[H3 Extender] v14.317 硬切拦截: seed={_cut_seed} 重采样完成, "
                      f"剩余硬切 {len(_cut_new)} 处(原 {len(_cut_best_hits)} 处)", flush=True)
                if len(_cut_new) < len(_cut_best_hits):
                    _cut_best = _cut_samples
                    _cut_best_hits = _cut_new
                if not _cut_best_hits:
                    print("[H3 Extender] v14.317 硬切拦截: 重采样后无硬切, 采用该结果", flush=True)
                    break
            samples = _cut_best
            if _cut_best_hits:
                if _cut_retries <= 0:
                    print(f"[H3 Extender] v14.338 硬切拦截(人物掩码重绘): 检出 "
                          f"{len(_cut_best_hits)} 处硬切 row="
                          f"{[h['row'] for h in _cut_best_hits][:4]} —— 源片自身切镜/循环接缝, "
                          f"源画面即画面来源; 不做换 seed 重采样(省一整轮采样), 直接采用",
                          flush=True)
                else:
                    print(f"[H3 Extender] v14.317 硬切拦截: 重采样次数用尽, 仍剩 "
                          f"{len(_cut_best_hits)} 处硬切(保留最优的一次)", flush=True)

    # v1.31: 二采升级为 Sol-H3 Self-Lift 双采（一采 + 二采直出高清）
    # 技术流程（对齐 BSAI-ComfyUI-Sol-H3 LatentUpscaleAlign 极速版）：
    #   1) 一采潜空间结果直接放大（不经过 VAE，无编解码画质损失）：
    #      NestedTensor 感知——只放大视频成员，音频 latent 保持不动；
    #      放大后像素对齐 H3 官方 32px 网格（1920x1088 = 120x68 latent）；
    #      可选 3D latent upscaler 神经网络语义放大（细节更丰富）。
    #   2) CONST 重加噪：视频重噪到 sigma_start（σ·ε+(1-σ)·x 语义），
    #      音频默认锁定（零噪声 + noise_mask=0，保持一采音频不重绘）。
    #   3) DisableNoise 二采：从 CONST 加噪 latent 走完整去噪曲线
    #      （refine_denoise=1.0 时全量重绘，=0.55 时保留 45% 底图信息）。
    # v14.389: 内容闸门的一采快照在 refine 段内赋值, 这里先占位 —— 二采未启用时
    # 闸门必须看到 None 而不是 NameError。
    _refine_base_snapshot = None
    if refine_enable:
        try:
            _r_factor = float(refine_upscale_factor)
            _r_steps = max(1, int(refine_steps))
            _r_denoise = max(0.05, min(1.0, float(refine_denoise)))
            # v14.384: 二采不重绘(仅当用户显式要旧行为: BSAI_H3_REFINE_NO_REDRAW=1)
            # v14.389: 默认改为「全部重绘 + 内容锁」—— 二采底图是一采放大后的 latent,
            # denoise 夹到 _FF_REFINE_LOCK_DENOISE, 保留一采的构图/动作/场景。
            if _FF_REFINE_NO_REDRAW:
                if _r_denoise > 1e-6:
                    print(f"[H3 Extender] v14.384 二采不重绘: 请求 denoise={_r_denoise:.2f} "
                          f"steps={int(refine_steps)} -> denoise=0.00(只超分放大, 不做任何重采样)")
                _r_denoise = 0.0
            elif _r_denoise > _FF_REFINE_LOCK_DENOISE:
                print(f"[H3 Extender] v14.389 二采内容锁: 请求 denoise={_r_denoise:.2f} "
                      f"-> {_FF_REFINE_LOCK_DENOISE:.2f}(保留一采构图, 只补细节; "
                      f"v14.393 该值=真实起点 σ, 不再按旧 img2img 近似放大到 0.92)")
                _r_denoise = _FF_REFINE_LOCK_DENOISE
            elif _r_denoise > 1e-6 and _r_denoise < _FF_REFINE_FLOOR_DENOISE:
                # v14.393: 抬到"真重绘"下限 —— 旧算法下这些 0.20/0.35/0.40 的档实际从
                # σ≈0.92 全量重生(看起来是重绘但其实是换画面), 按精确 σ 又只轻扫一下。
                print(f"[H3 Extender] v14.393 二采重绘下限: 请求 denoise={_r_denoise:.2f} "
                      f"-> {_FF_REFINE_FLOOR_DENOISE:.2f}(真实起点 σ, 保证真重绘不脱形)")
                _r_denoise = _FF_REFINE_FLOOR_DENOISE
            # v14.390: 真重绘(denoise>0)时的分块策略开关。
            # 默认不动(沿用工作流/管线档的空间分块 + 时间分块到 64k/前向)。
            # 若分块前向仍慢, 设 BSAI_H3_REFINE_REDRAW_MEM=global 重启: 走 v14.275
            # 的全上下文时间分块(每段 ~236k tokens, 本机实测 Sol-Attn 稀疏下
            # 0.7-1.0s/步), 不再裁空间轴 —— 换来的是「不再暂停 TST/稀疏注意力」。
            if _r_denoise > 1e-6:
                _rmmd390 = str(os.environ.get("BSAI_H3_REFINE_REDRAW_MEM", "")).strip().lower()
                if _rmmd390 in ("global", "spatial") and not str(refine_mem_mode).startswith(_rmmd390):
                    print(f"[H3 Extender] v14.390 二采真重绘分块策略: {refine_mem_mode} -> "
                          f"{_rmmd390} (env BSAI_H3_REFINE_REDRAW_MEM)")
                    refine_mem_mode = ("global (全上下文省显存)" if _rmmd390 == "global"
                                       else "spatial (tiled, compatible)")
            _r_audio = float(refine_audio_denoise)
            _r_align = max(8, int(refine_align_to))
            # v14.195: 二采音频质量保护(渲染环节)——
            # ① lip_audio 对口型模式: 一采音频=参考原声 latent 已锁定(完美),
            #    二采音频重绘(0.7)会把干净参考 70% 重噪后低步数重画 → 低频
            #    轰鸣(实测根因)。默认保持锁定(输出=参考原声, 即"完美标准");
            #    环境变量 BSAI_H3_LIP_AUDIO_REDRAW=1 可恢复重绘(此时步数下限
            #    12 兜底)。② 音频重绘开启且二采步数 <12 → 自动提升到 12(官方
            #    音频下限), 根治"从噪声画 4 步音频"的轰鸣/崩坏。
            if _has_audio and float(_r_audio) >= 0.5:
                if not _FF_REFINE_NO_REDRAW and os.environ.get("BSAI_H3_REFINE_AUDIO_REDRAW", "0") != "1":
                    # v14.389 内容锁同样管音频: 二采画面要与一采一致, 声音也必须是同一份,
                    # 不然低步数重绘音频会换成另一段(且历史实测有低频轰鸣)。默认锁死。
                    _r_audio = 0.0
                    print(f"[H3 Extender] v14.389 二采内容锁: 音频重绘 "
                          f"{float(refine_audio_denoise):.1f} -> 锁定(沿用一采音频)"
                          f"；确需重绘音频设 BSAI_H3_REFINE_AUDIO_REDRAW=1")
                elif _lip_locked and os.environ.get("BSAI_H3_LIP_AUDIO_REDRAW", "0") != "1":
                    _r_audio = 0.0
                    print(f"[H3 Extender] v14.195 lip_audio 对口型: 参考原声已锁定, "
                          f"二采音频重绘 {float(refine_audio_denoise):.1f} 会把它重绘成 "
                          f"低频轰鸣(实测根因), 已保持锁定(输出=参考原声)。如确需重绘 "
                          f"设 BSAI_H3_LIP_AUDIO_REDRAW=1(此时步数自动 ≥12)")
                elif _audio_quality_on and int(_r_steps) < 12:
                    # v14.196: 不再把二采步数 4→12 (实测 4 步 324s/步 = 65 分钟/15秒片段,
                    # 用户无法接受)。一采音频已按 12 步生成(上面的音频生成保护保证),
                    # 二采只需锁住音频不再重绘即可保留同一份音频, 步数尊重用户设置。
                    # 效果等同: 音频质量不降, 二采少跑 8 步。
                    _r_audio = 0.0
                    print(f"[H3 Extender] v14.196 音频重绘保护: 二采 {int(refine_steps)} 步 < "
                          f"音频 12 步下限, 改为锁定音频(保留一采 12 步音频, 不重绘), "
                          f"二采步数按设置 {int(_r_steps)} 步执行(不做 4→12 提升, 省 8 步)。"
                          f"如须重绘并提升步数 设 BSAI_H3_AUDIO_QUALITY=0")
            # v1.44: 选了 3D upscaler 模型但 factor<=1.0 时自动提升到 1.5.
            # factor=1.0 会跳过 _ff_upscale_video_latent(), 3D upscaler
            # 白选了, 二采只是对同分辨率 latent 重加噪再去噪, 画质必糊.
            _has_upscaler = (refine_upscaler_model
                             and not str(refine_upscaler_model).startswith("(")
                             and _FF_UPSCALER_MOD is not None)
            if _has_upscaler and _r_factor <= 1.0 and not refine_single_pass:
                print(f"[H3 Extender] Refine: 选了 3D upscaler 但 factor={_r_factor}, "
                      f"自动提升到 1.5 以启用语义放大")
                _r_factor = 1.5
            print(f"[H3 Extender] Refine 双采(Sol-H3 Self-Lift): clip={clip_index} "
                  f"upscale=x{_r_factor} align={_r_align}px steps={_r_steps} denoise={_r_denoise:.2f} audio={_r_audio}")

            # v1.43 (2026-09-13 fix #4): 不再 unload_all_models()!
            # v1.32~v1.36 的 unload_all_models() 虽然释放了显存, 但把
            # diffusion 模型也卸了, 导致二采采样时 ComfyUI 以 full
            # lowvram 模式重载 (日志: "0.00 MB loaded, 19996.14 MB
            # offloaded"), 每个 layer 都要 CPU↔GPU 搬运, 造成显存碎片
            # 和峰值飙升, 必然 OOM.
            #
            # 参考 Sol-H3 双采极速版工作流: 一采和二采共用同一 model
            # 对象, 模型始终保持 loaded 状态, 二采只需额外 attention
            # workspace (~1-2GB), 总计 ~22GB 能装进 24GB 卡.
            #
            # 策略: 只做 GC + empty_cache 清理中间张量, 保留 diffusion
            # 在 VRAM. 3D upscaler 缓存在 _ff_upscale_video_latent()
            # 之后单独清理.
            try:
                import comfy.model_management as _mm
                import torch as _torch
                import gc as _gc
                _gc.collect()
                _mm.soft_empty_cache(force=True)
                _torch.cuda.synchronize()
                _torch.cuda.empty_cache()
                try:
                    _torch.cuda.ipc_collect()
                except Exception:
                    pass
                _a = _torch.cuda.memory_allocated() / 1024 ** 3
                _r = _torch.cuda.memory_reserved() / 1024 ** 3
                _f, _t = _torch.cuda.mem_get_info()
                _free_gb = _f / 1024 ** 3
                _total_gb = _t / 1024 ** 3
                print(f"[H3 Extender] Refine 二采前显存状态(v1.43 保留diffusion): "
                      f"allocated={_a:.2f}GB reserved={_r:.2f}GB "
                      f"device_free={_free_gb:.2f}GB/{_total_gb:.2f}GB")
            except Exception as _ve:
                print(f"[H3 Extender] Refine 二采前显存清理失败(可忽略): {_ve}")

            # v1.81: 二采前强制释放 DynamicVRAM staged 池 (4090 CUDA abort 修复),
            # 必须在显存预算检查之前, 让预算看到释放后的真实可用显存。
            try:
                _release_dynamic_vram("refine")
            except Exception as _rv81:
                print(f"[H3 Extender] v1.81 二采前显存释放异常(可忽略): {_rv81}")

            # v1.47 (2026-09-13 fix #6 二采卡死根治)
            # 问题(实锤, 与 BSAI-H3-MotionFix v2.9 记录的卡死同根因):
            #   DynamicVRAM 开启时 H3 int8 模型(21.8GB)以流式加载, 一采后
            #   完全释放显存(allocated≈0GB); 二采 _r_guider.sample() 触发
            #   21.8GB 全量重载 + 大 latent attention workspace(x2.0≈4.5GB),
            #   24GB 卡显存/内存耗尽 → Python 线程阻塞假死(日志停在
            #   "Model Initializing ... 0/4", 重启复现).
            #   对照: 11:05 成功运行(DynamicVRAM off)二采前模型驻留 9.19GB,
            #   二采无需全量重载, 4 步跑通; 17:40 卡死(DynamicVRAM on)
            #   二采前模型 0.02GB.
            # 修复: 1) 显存预算预检, 模型不在显存时按流式重载估算, 超限
            #   自动降级放大倍率(2.0→1.5→1.0)并醒目提示; 2) 二采采样前
            #   主动 load_model_gpu() 确保模型驻留(防 DynamicVRAM 重载
            #   假死); 3) 失败走已有 fallback, 绝不假死.
            try:
                import torch as _torch2
                _gpu_free_gb2, _gpu_total_gb2 = _torch2.cuda.mem_get_info()
                _gpu_free_gb2 /= 1024 ** 3
                _gpu_total_gb2 /= 1024 ** 3
                _alloc_gb2 = _torch2.cuda.memory_allocated() / 1024 ** 3
                _model_gb2 = 0.0
                try:
                    _dm2 = getattr(model, "model", None)
                    if _dm2 is not None:
                        _model_gb2 = sum(
                            p.numel() * p.element_size()
                            for p in _dm2.parameters()) / 1024 ** 3
                except Exception:
                    _model_gb2 = 0.0
                # int8 量化模型: 参数以 fp16 尺寸存于内存(41GB 量级), 实际
                # 显存占用≈参数量×0.53 (int8 每权重 1 字节 vs fp16 2 字节).
                # 实测: 参数 41.06GB → int8 显存 21.8GB (日志 21833MB Staged).
                if _model_gb2 > 0.0:
                    _model_gb2 *= 0.53
                if _model_gb2 <= 0.0:
                    _model_gb2 = 21.8  # int8 H3 经验值兜底
                # workspace 实测表: 60x34→1.5GB(一采) 90x50→2.6GB(11:05 二采)
                # 120x68→4.5GB(代码注释实测峰值)
                _ws_tbl = {1.0: 1.5, 1.5: 2.6, 2.0: 4.5}
                _orig_f = float(_r_factor)
                # 候选倍率从当前值开始逐级下降
                # v14.276: 单次采样档的倍率已按 token 预算取好(1.0~2.0 之间的小数),
                # 阶梯里只认 1.5/1.0, 会被误判成"显存不足"→ 反而启用 spatial 分块
                # 保住倍率(每块独立重构图 = 重影)。该档只按自身倍率判, 不分块。
                _cands = ([_orig_f] if refine_single_pass
                          else [f for f in (2.0, 1.5, 1.0) if _orig_f >= f - 1e-6])
                if not _cands:
                    _cands = [max(1.0, _orig_f)]
                # 需求估算:
                #  - 模型未驻留(alloc<4GB, DynamicVRAM 流式): 重载峰值≈35% 权重
                #  - 模型部分驻留(lowvram, 4GB<=alloc<全量): 二采需把 offloaded
                #    部分搬回 GPU, 搬运峰值≈(全量-已载)×0.6.
                #    实测校准: 11:05 x1.5 成功(起点 loaded 9.19GB, ws 2.6GB);
                #    19:13 x2.0 OOM(起点 loaded 10.34GB, ws 4.5GB, free 0).
                #    0.6 系数: x2.0 必拦, x1.5 放行(与 11:05 成功经验一致).
                # v1.65 (2026-09-14 fix #9 二采 x2.0 OOM 根治):
                # 实测 19:34 二采 x2.0: 旧预算(0.6 系数)算出需求 15.1GB<18.1GB
                # 放行, 但 load_models_gpu 全量驻留 21.72GB, Sol-Attn kernel
                # 连 603MB workspace 都分不出 → kernel failed×3 → fallback 到
                # 普通注意力 workspace 9.23GB 更大 → 二次 OOM → 回退一采.
                # 新预算: 驻留目标 = min(free,total) - workspace - 3GB 余量,
                # 驻留 <10GB 视为换页过重 → 逐级降 factor(在放大前拦截).
                _chosen2 = None
                for _f2 in _cands:
                    _ws2 = _ws_tbl.get(round(_f2, 1), 2.6)
                    _resident_target2 = min(_gpu_free_gb2, _gpu_total_gb2) - _ws2 - 3.0
                    if _resident_target2 >= 10.0:
                        _chosen2 = _f2
                        break
                # v14.157: 宁可分块, 不降倍率。
                # 旧逻辑在预算不足时直接把二采倍率 x2.0 降到 x1.5, 成片像素
                # 从声明的 1920x1088 悄悄缩水到 1440x800（线性 -25%, 人脸直接糊掉）。
                # 分块二采把 attention workspace 从 x2.0 的 4.5GB 压到 ~1.1GB,
                # 24GB 卡足以原地跑满原倍率; 只有分块也放不下时才真正降档。
                _auto_tiled = False
                if (not tiled_refine) and (_chosen2 is None or _chosen2 < _orig_f - 1e-6):
                    _ws_tiled_tbl = {1.0: 0.8, 1.5: 0.9, 2.0: 1.1}
                    _ws_tiled = _ws_tiled_tbl.get(round(_orig_f, 1), 1.1)
                    if min(_gpu_free_gb2, _gpu_total_gb2) - _ws_tiled - 3.0 >= 10.0:
                        tiled_refine = True
                        _auto_tiled = True
                        _chosen2 = _orig_f
                        print(f"[H3 Extender] v14.157 全帧二采 x{_orig_f} 显存不足, "
                              f"自动启用分块二采(tile_count={tile_count})保住原倍率, "
                              f"成片不再缩水到 x{_chosen2}")
                print(f"[H3 Extender] Refine 显存预算(v1.65): 模型~{_model_gb2:.1f}GB "
                      f"驻留alloc={_alloc_gb2:.1f}GB 可用显存={_gpu_free_gb2:.1f}GB/"
                      f"{_gpu_total_gb2:.0f}GB 驻留目标~{min(_gpu_free_gb2, _gpu_total_gb2) - _ws_tbl.get(round(_orig_f, 1), 2.6) - 3.0:.1f}GB")
                # v1.74 (2026-09-15 fix #10): 链几何一致性 —— 链上已有段时禁止 per-clip 降级。
                # 实测: 全量链渲染到 clip=7 时显存预算波动, 自动降级 2.0->1.5,
                # 二采 latent 从 120x68 变成 90x50, 与前段几何不一致,
                # Disk Join 报 "latent geometry changed" 中断整链 (4.5h 白跑).
                # 第一段(链空)允许降级(全局一致); 链上已有段时保持原 factor,
                # 若 OOM 由 v1.74b 把 fallback 输出 bilinear 对齐到链上几何。
                try:
                    _cp74, _cmp74 = _chain_paths(f"extender_{_safe_name(str(owner_id))}")
                    _cm74 = _load_manifest_from_paths(_cp74, _cmp74)
                    _cg74 = _cm74.get("geometry") if _cm74 is not None else None
                    if _cg74 is not None:
                        _chh74 = int(_cg74.get("video_h", 0))
                        _chw74 = int(_cg74.get("video_w", 0))
                        if _chh74 > 0 and _chw74 > 0 and _chosen2 is not None \
                                and _chosen2 < _orig_f - 1e-6:
                            _snap74 = max(1, _r_align // 16)
                            _m74a, _w74a = _ff_extract_members(samples)
                            _cur_h74, _cur_w74 = _m74a[0].shape[-2:]
                            _dg_h74 = _ff_snap_to_multiple(round(_cur_h74 * _chosen2), _snap74)
                            _dg_w74 = _ff_snap_to_multiple(round(_cur_w74 * _chosen2), _snap74)
                            if (_dg_h74, _dg_w74) != (_chh74, _chw74):
                                print(f"[H3 Extender] v1.74: 链上已有 {_chw74}x{_chh74} 段, "
                                      f"降级 x{_orig_f}->x{_chosen2} 会变几何 "
                                      f"({_dg_w74}x{_dg_h74}), 禁止 per-clip 降级(避免断链), "
                                      f"保持 x{_orig_f}")
                                _chosen2 = _orig_f
                except Exception as _ga74:
                    print(f"[H3 Extender] v1.74 链几何检查失败(可忽略): {_ga74}")
                if _chosen2 is not None and _chosen2 < _orig_f - 1e-6:
                    _r_factor = _chosen2
                    print(f"[H3 Extender] Refine 放大倍率已自动降级: x{_orig_f} -> x{_chosen2} "
                          f"(24GB 级显存 + int8 {_model_gb2:.1f}GB 模型下 x{_orig_f} 二采会假死, "
                          f"见 v1.47 显存预算)")
                    _send_extender_warning(
                        owner_id,
                        f"二采倍率被显存预算降级 x{_orig_f}→x{_chosen2}，"
                        f"本段成片像素低于声明值（细节会明显变软）",
                        clip_index=clip_index,
                    )
                elif _auto_tiled:
                    _send_extender_warning(
                        owner_id,
                        f"显存不足，已自动启用分块二采保住 x{_orig_f} 倍率"
                        f"（速度略降，画质不缩水）",
                        clip_index=clip_index,
                    )
                elif _chosen2 is None:
                    print(f"[H3 Extender] Refine 警告: 显存预算不足(需求>可用), "
                          f"二采将尝试流式采样, 若卡死请关闭 DynamicVRAM 启动 "
                          f"(--disable-dynamic-vram) 或换 w4a8 轻量模型")
            except Exception as _mp2:
                print(f"[H3 Extender] Refine 显存预算预检失败(可忽略): {_mp2}")

            # v1.38 (2026-09-13 fix): 在放大前 deep copy 一采原始 samples,
            # 留作 OOM fallback 用. 120x68 (2.0x) OOM 后, 重跑时直接用
            # 60x34 一采原始尺寸, attention workspace 从 4.47GB 降到
            # ~1.5GB, 24GB 卡稳过. 注意: 仅在 _r_factor > 1.0 时备份,
            # 省一份显存; 同时 audio latent 不备份 (audio 不放大不重画).
            # v14.206: 备份逻辑对 AV NestedTensor 修正。comfy.nested_tensor.NestedTensor
            # 没有 .clone(). 旧代码 hasattr(samples,"clone") 恒为 False, 于是二采这里
            # 从来就没备份成功过 —— OOM fallback 与塌陷回退都拿不到一采 latent。
            _samples_pre_upscale = None
            if _r_factor > 1.0:
                try:
                    if _ff_is_nested(samples):
                        _samples_pre_upscale = comfy.nested_tensor.NestedTensor(
                            [t.clone() for t in samples.unbind()])
                    elif hasattr(samples, "clone"):
                        _samples_pre_upscale = samples.clone()
                except Exception as _bp_err:
                    print(f"[H3 Extender] Refine 备份一采 samples 失败(可忽略): {_bp_err}")
                    _samples_pre_upscale = None

            # 1) NestedTensor 感知 latent 放大（仅视频，音频保持）+ 像素对齐 + 可选 3D upscaler
            if _r_factor > 1.0:
                _members, _was_nested = _ff_extract_members(samples)
                _old_hw = (tuple(_members[0].shape[-2:]) if _members else None)
                _FF_UPSCALER_FELL_BACK["hit"] = False
                _FF_UPSCALER_FELL_BACK["reason"] = ""
                # v14.273: 权重与加载器架构不匹配时提前纠正, 不再让它静默退化成 bilinear
                refine_upscaler_model, _up_note = _ff_resolve_upscaler_model(refine_upscaler_model)
                if _up_note:
                    print(f"[H3 Extender] v14.273 {_up_note}")
                    _send_extender_warning(
                        owner_id,
                        _up_note,
                        clip_index=clip_index,
                    )
                # v14.274: 插值回退用 bislerp 而不是 bilinear。latent token 是 24 维
                # 向量, 分量插值会在内容边缘把相邻 token 方向抵消、范数塌缩; 这些
                # "短 token" 严重 out-of-distribution, 二采会在此处凭空发明内容,
                # 表现为沿边缘的碎屑/丝状物(实测满屏白色碎纸片)。bislerp 对方向做
                # slerp、只插值模长, 是唯一保范数的平滑方法。
                _up_video = _ff_upscale_video_latent(
                    _members[0], _r_factor, _r_align, "bislerp", refine_upscaler_model)
                # v14.157: 3D 语义放大失败不再静默 —— 会退化成插值,
                # 画质明显变软, 必须让用户在状态栏看到。
                if _FF_UPSCALER_FELL_BACK["hit"]:
                    _send_extender_warning(
                        owner_id,
                        f"3D 语义放大失败，已回退 bislerp 插值"
                        f"（{_FF_UPSCALER_FELL_BACK['reason']}）",
                        clip_index=clip_index,
                    )
                if tuple(_up_video.shape[-2:]) != tuple(_members[0].shape[-2:]):
                    samples = _ff_wrap_members([_up_video] + list(_members[1:]), _was_nested)
                    print(f"[H3 Extender] Refine 潜空间放大: clip={clip_index} "
                          f"{_old_hw[1]}x{_old_hw[0]} -> {_up_video.shape[-1]}x{_up_video.shape[-2]} (x{_r_factor})")

            # v14.389: 这里 samples = 一采放大后的 latent, 就是二采重绘的底图。
            # 拍一份快照: 二采采样完成后拿它做内容闸门(结构相似度不足就回退到这一份),
            # 同时它也是「二采只该补细节、不该换画面」的参照基准。
            _refine_base_snapshot = None
            if not _FF_REFINE_NO_REDRAW and _r_denoise > 1e-6:
                try:
                    _bs_m, _bs_n = _ff_extract_members(samples)
                    if _bs_m:
                        # 存 CPU float32: 二采是最吃 VRAM 的阶段, 不让快照再占一份显存
                        _refine_base_snapshot = (
                            _bs_m[0].detach().to("cpu", dtype=torch.float32),
                            list(_bs_m[1:]), _bs_n,
                        )
                except Exception as _bs_err:
                    print(f"[H3 Extender] v14.389 一采快照失败(内容闸门将跳过): {_bs_err}")

            # v14.384: 放大已完成 = 二采的全部工作已做完。这里直接跳出去, 后面
            # 的 CONST 加噪 / DisableNoise 去噪 / 空间分块 / 时间分块 / 二采驻留 /
            # workspace 探针 / 塌陷检测全部不执行 —— 「绝不重绘」的落点就在这一行。
            if _FF_REFINE_NO_REDRAW:
                raise _FFRefineSkip()

            # v14.162 (2026-10-22 fix): 一镜到底连续性修复 —— 二采保留 motion-context keyframe。
            # 旧 v2.55b 在二采完全清空 minimax_keyframes，但二采是 denoise=0.55 的重新采样
            # （会改变画面内容），清空后二采失去"上一段尾帧"锚定 → 段间画面漂移/虚影，
            # 一镜到底的尾帧引导链在一采生效后又被二采冲掉（4090 实机 3 clip 验证）。
            # 修复：把一采 keyframe latent 空间 trilinear resize 到二采 latent 分辨率后
            # 保留注入，使"上一段尾帧引导"贯穿一采+二采，接缝处无缝衔接。
            if _r_factor > 1.0:
                try:
                    _cond_kc = conditioning[0][1] if isinstance(conditioning, list) else conditioning
                    if isinstance(_cond_kc, dict) and _cond_kc.get("minimax_keyframes"):
                        _kfs = _cond_kc["minimax_keyframes"]
                        _memb14, _nst14 = _ff_extract_members(samples)
                        _tgt_hw14 = tuple(_memb14[0].shape[-2:]) if _memb14 else None
                        if _tgt_hw14 is not None:
                            _nfs14 = []
                            _resized14 = 0
                            for _kf14 in _kfs:
                                _kl14 = _kf14.get("latent")
                                if _kl14 is not None and _kl14.ndim == 5 \
                                        and tuple(_kl14.shape[-2:]) != _tgt_hw14:
                                    try:
                                        _kl14 = torch.nn.functional.interpolate(
                                            _kl14,
                                            size=(
                                                int(_kl14.shape[2]),
                                                int(_tgt_hw14[0]),
                                                int(_tgt_hw14[1]),
                                            ),
                                            mode="trilinear",
                                            align_corners=False,
                                        )
                                        _resized14 += 1
                                    except Exception:
                                        pass
                                _nkf14 = dict(_kf14)
                                _nkf14["latent"] = _kl14
                                _nfs14.append(_nkf14)
                            _cond_kc["minimax_keyframes"] = _nfs14
                            print(f"[H3 Extender] v14.162 二采保留 {len(_nfs14)} 个 motion-context keyframe"
                                  f" (resize {_resized14} 块到 {_tgt_hw14[1]}x{_tgt_hw14[0]} 二采空间), "
                                  f"一镜到底尾帧引导贯穿一采+二采")
                except Exception as _ekc:
                    print(f"[H3 Extender] v14.162 keyframe 保留失败(可忽略): {_ekc}")

            # v1.43: 3D upscaler 用完后立即清缓存, 释放 VRAM 给二采 diffusion.
            # MODEL_CACHE 不受 ComfyUI model_management 管理 (不在
            # current_loaded_models 里), ComfyUI 无法自动让位, 必须手动清.
            if _r_factor > 1.0 and refine_upscaler_model and _FF_UPSCALER_MOD is not None:
                try:
                    _cache = getattr(_FF_UPSCALER_MOD, "MODEL_CACHE", None)
                    if isinstance(_cache, dict) and _cache:
                        for _k, _m in list(_cache.items()):
                            try:
                                _m.to("cpu")
                            except Exception:
                                pass
                            del _m
                            del _cache[_k]
                        import gc as _gc
                        import torch as _torch
                        _gc.collect()
                        _torch.cuda.synchronize()
                        _torch.cuda.empty_cache()
                        print(f"[H3 Extender] Refine 3D upscaler 缓存已清理, 释放 VRAM 给二采")
                except Exception as _uc_err:
                    print(f"[H3 Extender] Refine 清 3D upscaler cache 失败(可忽略): {_uc_err}")

            # 2) CONST 重加噪（视频重噪到 sigma_start，音频锁定/重绘）
            # v1.33: 二采调度器对齐官方示例工作流（Sol-H3 双采极速版）——beta + denoise 0.55 保留底图细化
            # v14.238 Director 移植: 外接 refine_sigmas 端口(BasicScheduler/
            # ManualSigmas 直连)优先, 二采完全按外部 sigma 曲线执行 —— 与参考
            # 插件 Refine 节点原版行为一致; 未接时回退内部 beta 调度。
            _r_sigmas_ext = _ff_sigmas_override_tensor(refine_sigmas)
            if _r_sigmas_ext is not None:
                _r_sigmas = _r_sigmas_ext
                print(f"[H3 Extender] v14.238 Director极速二采: 使用外接 SIGMAS "
                      f"({int(_r_sigmas_ext.shape[0])} 段), 覆盖内部 beta "
                      f"{_r_steps}步/{_r_denoise:.2f} 调度")
            else:
                # v14.393: 二采 denoise 一律按"真实起点噪声比例"解释。
                # 旧 `_sigmas()` 是"拉长 total_steps 再取末 N 步"的老 img2img 近似,
                # H3 在 shift12 下 σ(t) 高端极平(σ(t=0.5)=0.923), 实测 denoise=0.45/
                # 0.50 steps=2 → σ0=0.9234, 等于整帧重生 → 二采必画成另一幅。
                # 精确映射把 σ0 钉在 ≈denoise(实测 0.45→0.4381 / 0.50→0.4859 /
                # 0.55→0.5427), 这才是"从 σ≈0.45~0.55 起步的真重绘"。
                _r_sigmas = None
                if _FF_REFINE_SIGMA_EXACT and _r_denoise < 1.0:
                    try:
                        _r_sigmas = _sigmas_exact(model, "beta", _r_steps, _r_denoise,
                                                  tag=f"二采 steps={_r_steps}")
                    except Exception as _rse:
                        print(f"[H3 Extender] v14.393 二采 sigma 精确映射失败, 回退旧算法: "
                              f"{type(_rse).__name__}: {_rse}", flush=True)
                        _r_sigmas = None
                if _r_sigmas is None:
                    _r_sigmas = _sigmas(model, "beta", _r_steps, _r_denoise)
            # v1.45 (2026-09-13 fix #5 画面糊成一片根因): CONST 加噪的噪声必须用真实随机噪声
            # (σ·ε+(1-σ)·x 混合), 但喂给 KSAMPLER.sample 的 noise 参数必须用空噪声!
            # 原因: CFGGuider.sample -> KSAMPLER.sample 内部会对 noise 再执行一次
            #   noise = model_sampling.noise_scaling(sigmas[0], noise, latent_image)
            #   即 latent_image + noise*sigma. 若把 CONST 已加噪的 latent 与真实噪声同时传入,
            #   会二次加噪(双重噪声), 二采从过噪起点开始, 4步去噪不足, 输出残留噪声/细节丢失,
            #   画面"糊成一片+像素化故障风". 官方 Sol-H3 DualSample 工作流二采正是用
            #   DisableNoise(Noise_EmptyNoise -> prepare_empty_noise 全零噪声) 走同一入口,
            #   此处完全对齐.
            _use_temporal = (bool(temporal_chunk_tokens) and int(temporal_chunk_tokens) > 0
                             and not refine_single_pass)
            # v2.02b: chunk 过小(如当开关填 1)会切成大量单 token 段, 每段都要完整跑
            # 4 步空间分块采样, 总耗时爆炸(T=107 时 107 段≈100 分钟). 低于 16 一律按 16 执行.
            if _use_temporal and int(temporal_chunk_tokens) < 16:
                print(f"[H3 Extender] v2.02 temporal_chunk_tokens={int(temporal_chunk_tokens)} 过小, "
                      f"已按 16 执行 (T~107 建议 40~60, 0=关闭)", flush=True)
                temporal_chunk_tokens = 16
            # v14.228 (2026-10-27): 二采提速 —— temporal_chunk_tokens=0(未启用)时按
            # latent T 自动时间分块. 根因: 实机 218K tokens 整段二采 + spatial 分块 4
            # 后每块仍 ~113K(overlap 128px 膨胀), dense attention workspace ~51GB
            # 超 24GB 卡 -> 每块换页 ~87s -> 348s/步. 时间分块把每段降到 ~22 帧,
            # 与空间分块组合后每块 ~23K tokens, dense workspace ~2GB 可装, 总计算量
            # 守恒(tokens 均摊到段*块, 不膨胀), 预期 4 步总量 50-100s.
            # v14.276: 单次采样档不做自动时间分块 —— 倍率已按 token 预算压到
            # Sol-Attn 健康区, 整段一次调用最干净; 分块只会换来接缝闪烁与碎纹。
            # v14.281: MV 双采档同理 —— 原版 temporal_chunk_tokens=0 即整段一次,
            # 由 refine_no_temp_chunk 显式关闭自动分块(空间 4 块保留)。
            #
            # v14.390 (2026-11-12): 上面两条「整段一次」只在二采**不真采样**时成立。
            # v14.389 把二采重绘打开后, 实机(14:55 开工, FastH3/PIKA 双采档)在二采第
            # 1 块就死等: 272,136 tokens/块 × 6.4GB 权重 offload × tile forward 内
            # SelfLift TST 被 v14.380 显式暂停 —— GPU util 100% 但只有 98W、显存带宽
            # 利用率 1%(SM 空转等搬运), 主机单核 100%, py-spy 落在
            # _tiled_model_call -> cast_bias_weight, 20 分钟走不完 tile1 的第一步。
            # 根因是两道否决同时生效: ① v14.306 把 _CHUNKED_DENOISE_ON 默认关成
            # 「整段一次」; ② v14.281 的 refine_no_temp_chunk 再加一道。于是 v14.270
            # 那条「每前向 tokens 超预算就切时间」的保护在真重绘路径上从未生效。
            # 修法: denoise>0(真重绘)时这两道否决一律作废, 交回 token 预算自动分块;
            # 纯超分(denoise=0)与单采档的旧行为保持不变。
            _redraw390 = _r_denoise > 1e-6
            _tc_override390 = bool(refine_no_temp_chunk) and not _use_temporal and _redraw390
            if refine_no_temp_chunk and not _use_temporal:
                if _tc_override390:
                    print("[H3 Extender] v14.390 MV 双采: 二采真跑重绘(denoise="
                          f"{_r_denoise:.2f}) → 撤销 v14.281『整段一次』, "
                          "按 token 预算自动时间分块(272k tokens/块会让主机侧搬运变串行死等)",
                          flush=True)
                else:
                    print("[H3 Extender] v14.281 MV 双采: 按原版 temporal_chunk_tokens=0 "
                          "禁用自动时间分块 -> 整段一次二采(1 段 × 空间分块)", flush=True)
            if ((_CHUNKED_DENOISE_ON or _redraw390) and not _use_temporal
                    and not refine_single_pass
                    and (not refine_no_temp_chunk or _tc_override390)):
                try:
                    _t_cand226 = None
                    _h_cand226 = 0
                    _w_cand226 = 0
                    try:
                        _mem226, _ = _ff_extract_members(samples)
                        _t_cand226 = int(_mem226[0].shape[2])
                        _h_cand226 = int(_mem226[0].shape[-2])
                        _w_cand226 = int(_mem226[0].shape[-1])
                    except Exception:
                        try:
                            _t_cand226 = int(samples["samples"].tensors[0].shape[2])
                            _h_cand226 = int(samples["samples"].tensors[0].shape[-2])
                            _w_cand226 = int(samples["samples"].tensors[0].shape[-1])
                        except Exception:
                            pass
                    # v14.248: 自动时间分块阈值 T>=50 -> T>=200。根因: T=107 (二采
                    # tokens=218k 在 Sol-Attn 健康区 <=350k) 整帧采样只需 0.97s/步,
                    # v14.225 已确认不需要 global 包装。但 v14.228 仍自动切成
                    # chunk=21/overlap=8 -> 8 段独立 seed 采样, 段间接缝在 ~3s 处出现
                    # 模糊/马赛克/明暗闪烁/粗横条纹(用户实测 h3_motion_preview_7_0.mp4)。
                    # T>=200 (~500k+ tokens) 才真需要时间分块降 dense workspace;
                    # T=107 走 Sol-Attn 稀疏全帧最稳。
                    #
                    # v14.270 (2026-10-31 fix): 上面"拿 T 当阈值"是维度错误 —— 真正的
                    # 压力是 tokens = T*H*W, 不是 T。实机反例: T=87 看着远小于 200,
                    # 但 latent 已被 x2.0 放大到 120x68, tokens=87*120*68=709,920。
                    # 于是时间分块不触发, 只剩空间单轴(_plan_regions 仅沿 H 切)4 块,
                    # 每块仍吃满 87 帧 -> ~272k tokens/块(v14.179 实测)。后果链:
                    #   Sol-Attn workspace 要 4.5GB, 而自适应让位后 free 仅 6.8GB
                    #   且要留 2GB headroom -> 留给激活只剩 ~0.3GB, 同时仍有 3.9GB
                    #   权重在 CPU 侧 -> 每步全量换页活锁。实机二采 0/4 卡死 20min+,
                    #   GPU 99% util 但仅 82W / 55C = SM 空转等搬运, 不是在算。
                    # 现改为以「空间分块后的每块 tokens」为准: 超过 v14.250 探针用
                    # 的 130k 才启用时间分块, 并按超出倍数反推段数(不再固定 T/5)。
                    # 倍率 _r_factor 全程不动 —— 宁可分块, 不降倍率(v14.157 原则)。
                    if _t_cand226 is not None:
                        _tok226 = 0
                        if _h_cand226 > 0 and _w_cand226 > 0:
                            _tok226 = int(_t_cand226) * _h_cand226 * _w_cand226
                        _spatial_n226 = 1
                        _tile_infl226 = 1.55
                        _is_global_mem226 = str(refine_mem_mode) == "global"
                        if _is_global_mem226:
                            # v14.275: global 全上下文路径不裁空间轴, 没有 tile 重叠
                            # 膨胀, 按"单次调用 tokens"直接换算(见下方 240k 目标)。
                            _tile_infl226 = 1.0
                        else:
                            try:
                                _spatial_n226 = max(1, int(tile_count))
                            except Exception:
                                _spatial_n226 = 1
                        # 1.55x = overlap 128px 的 tile 膨胀系数, 与 v14.179 实测
                        # "每块 272,136 tokens" 吻合(709920/4*1.55≈275k)。
                        _per_tile226 = (_tok226 / float(_spatial_n226)) * _tile_infl226 if _tok226 > 0 else 0
                        # v14.270 回滚开关(不改文件即可退回旧行为, 需重启 ComfyUI 生效):
                        #   BSAI_H3_TEMPORAL_TRIGGER=tokens  默认, 新逻辑(按每块 tokens 触发)
                        #   BSAI_H3_TEMPORAL_TRIGGER=legacy 退回 v14.248 旧逻辑(仅 T>=200)
                        #   BSAI_H3_TEMPORAL_TRIGGER=off    完全关闭自动时间分块
                        #   BSAI_H3_TILE_TOKEN_TARGET=130000  每块 tokens 目标(仅 tokens 模式)
                        _trig270 = str(os.environ.get("BSAI_H3_TEMPORAL_TRIGGER", "tokens")).strip().lower()
                        _tok_tgt270 = 130000.0
                        try:
                            _tok_tgt270 = float(os.environ.get("BSAI_H3_TILE_TOKEN_TARGET", "130000"))
                        except Exception:
                            _tok_tgt270 = 130000.0
                        if _is_global_mem226:
                            # v14.275: global 全上下文没有 tile 重叠, 130k 会把 T=87
                            # 切成 6 段(每段~15帧, 段间接缝过密)。Sol-Attn 稀疏在
                            # 236k tokens 实测健康(0.7-1.0s/步), 抬到 240k 后
                            # T=87/709,920 tokens 只切 3 段(chunk=29) -> 4 段。
                            _tok_tgt270 = max(_tok_tgt270, 240000.0)
                        if _redraw390 and not _is_global_mem226:
                            # v14.390: 真重绘的分块路径没有稀疏注意力可用(v14.380 在
                            # tile forward 内暂停 TST), 每前向的激活量直接决定成败:
                            # 272k tokens 时单个激活张量就 ~1.1GB(272k*2048*bf16),
                            # 50 个 block 反复 malloc/free + 6.4GB 权重换页, 实测
                            # 20 分钟走不完第 1 块。压到 64k 档: T=87 切成 5 段
                            # (chunk=20 帧 × 46 × 68 ≈ 62.6k tokens/前向, 激活
                            # ~250MB), 与 v14.270 设计时"每段 ~22 帧"的实测健康区一致。
                            try:
                                _tok_tgt390 = float(os.environ.get(
                                    "BSAI_H3_REFINE_TILE_TOKEN_TARGET", "65536"))
                            except Exception:
                                _tok_tgt390 = 65536.0
                            if _tok_tgt390 > 0:
                                _tok_tgt270 = min(_tok_tgt270, max(16384.0, _tok_tgt390))
                        if _trig270 == "off":
                            _need_auto270 = False
                            # v14.390: 真重绘 + 每前向超预算时, "off" 不再作数 ——
                            # 这条开关是 v14.270 在不重绘的年代留的回滚口, 真采样时
                            # 关掉它就是回到 272k tokens/前向的串行死等。
                            if _redraw390 and _per_tile226 > _tok_tgt270:
                                _need_auto270 = True
                                print(f"[H3 Extender] v14.390 忽略 BSAI_H3_TEMPORAL_TRIGGER=off: "
                                      f"二采真重绘每前向 {int(_per_tile226):,} tokens > "
                                      f"{int(_tok_tgt270):,}, 必须时间分块", flush=True)
                        elif _trig270 == "legacy":
                            _need_auto270 = (_t_cand226 >= 200)
                        else:
                            _need_auto270 = (_t_cand226 >= 200) or (_per_tile226 > _tok_tgt270)
                        if _need_auto270:
                            if _per_tile226 > 0:
                                _seg_n226 = max(2, int(math.ceil(_per_tile226 / max(1.0, _tok_tgt270))))
                                temporal_chunk_tokens = max(20, int(round(_t_cand226 / _seg_n226)))
                            else:
                                temporal_chunk_tokens = max(20, int(round(_t_cand226 / 5)))
                            _use_temporal = True
                            print(f"[H3 Extender] v14.270 自动时间分块(trigger={_trig270}, 目标每块<={int(_tok_tgt270):,}): "
                                  f"T={_t_cand226} latent={_h_cand226}x{_w_cand226} "
                                  f"tokens={_tok226:,} / 空间{_spatial_n226}块 -> 每块~{int(_per_tile226):,} "
                                  f"切约 {max(1, int(round(_t_cand226 / max(1, int(temporal_chunk_tokens)))))} 段 "
                                  f"(chunk={int(temporal_chunk_tokens)}), 倍率保持 x{_r_factor}", flush=True)
                except Exception as _e226:
                    print(f"[H3 Extender] v14.228 自动时间分块失败(可忽略): {_e226}")
            # v14.200: 删除 v14.199 的"分块二采强制锁音频"。
            # 根因不再靠锁定规避: bsai_h3_spatial_tiles.py 现在直接取第 1 块
            # 的音频预测(音频 latent 无空间维度, 各块都给出完整音频估计),
            # 不再把 N 块相位不一致的预测求平均 → 没有低频轰鸣, 音频也能照常
            # 参与二采重绘。锁定会上游 v14.196 已按步数条件处理。
            if not _use_temporal:
                _r_noise = comfy.sample.prepare_noise(samples, int(seed) + 1, None)
                _r_latent = _ff_const_add_noise(model, _r_noise, _r_sigmas, {"samples": samples}, _r_audio)
                # v14.240 (fix): 非分块二采段头锁 keep —— 一采段头锁行数 >0 时,
                # 把二采 latent 段头重置为一采输出(samples)的干净延续画面, 并设
                # video mask=0 锁 keep, 杜绝二采从加噪底重画接缝 → 段间跳帧。
                if _os_head_rows >= 1:
                    try:
                        _rlm_os, _rln_os = _ff_extract_members(_r_latent["samples"])
                        _rv_os = _rlm_os[0]
                        _hrows_os = min(_os_head_rows, int(_rv_os.shape[2]))
                        if _hrows_os >= 1:
                            _smem_os, _ = _ff_extract_members(samples)
                            _s_v_os = _smem_os[0]
                            if tuple(_s_v_os.shape[-2:]) == tuple(_rv_os.shape[-2:]):
                                _rv_os = _rv_os.clone()
                                _rv_os[:, :, :_hrows_os] = _s_v_os[:, :, :_hrows_os]
                                _rlm_os[0] = _rv_os
                                _r_latent["samples"] = _ff_wrap_members(_rlm_os, _rln_os)
                                _vmask_os = torch.ones_like(_rv_os)
                                _vmask_os[:, :, :_hrows_os] = 0.0
                                _a_part_os = _rlm_os[1]
                                if float(_r_audio) >= 0.5:
                                    _amask_os = torch.ones((1, 1, 1, int(_a_part_os.shape[-1])),
                                                           dtype=_rv_os.dtype, device=_rv_os.device)
                                else:
                                    _amask_os = torch.zeros((1, 1, 1, int(_a_part_os.shape[-1])),
                                                           dtype=_rv_os.dtype, device=_rv_os.device)
                                _r_latent["noise_mask"] = comfy.nested_tensor.NestedTensor((_vmask_os, _amask_os))
                                print(f"[H3 Extender] v14.240 非分块二采段头锁 keep: 段头 {_hrows_os} 行锁定为一采延续画面(接缝零二次重绘)")
                    except Exception as _rlock_err:
                        print(f"[H3 Extender] v14.240 二采段头锁失败(可忽略): {_rlock_err}")
                # v14.347: 第 35 档人物替换 —— 把一采的人物掩码带进二采。
                # 二采默认 noise_mask 全 1(全帧重绘): 一采刚用掩码锁住的源背景, 会在
                # 1.5x 放大后被二采整体"洗"一遍 → 背景漂移 + 全画面糊(第三轮机位实测)。
                # 这里把一采 mask(人区 1 / 背景 0)最近邻重采样到二采 latent 尺寸继续沿用,
                # 段头锁行强制 0。任何一步出错就退回旧行为, 不允许因此打崩渲染。
                if _SIGMAS_EXACT and noise_mask is not None:
                    try:
                        _pcm, _ = _ff_extract_members(noise_mask)
                        _pcv = _pcm[0] if _pcm else None
                        if _pcv is not None and _pcv.dim() == 5 and float(_pcv.mean()) < 0.5:
                            _rlc, _rln = _ff_extract_members(_r_latent["samples"])
                            _rvc = _rlc[0]
                            _pcv = _pcv.float()
                            if (int(_pcv.shape[-2]), int(_pcv.shape[-1])) != (
                                    int(_rvc.shape[-2]), int(_rvc.shape[-1])):
                                _pcv = torch.nn.functional.interpolate(
                                    _pcv, size=(int(_rvc.shape[-2]), int(_rvc.shape[-1]),
                                                int(_rvc.shape[2])), mode="nearest")
                            else:
                                _t_h, _t_t = int(_pcv.shape[2]), int(_rvc.shape[2])
                                if _t_h > _t_t:
                                    _pcv = _pcv[:, :, :_t_t]
                                elif _t_h < _t_t:
                                    _pcv = torch.cat(
                                        [_pcv, _pcv[:, :, -1:].repeat(1, 1, _t_t - _t_h, 1, 1)], dim=2)
                            _pcv = _pcv.to(dtype=_rvc.dtype, device=_rvc.device).expand_as(_rvc).contiguous()
                            _hr_c = min(int(_os_head_rows), int(_pcv.shape[2]))
                            if _hr_c >= 1:
                                _pcv[:, :, :_hr_c] = 0.0
                            _rac = _rlc[1]
                            _amc = (torch.ones((1, 1, 1, int(_rac.shape[-1])),
                                               dtype=_rvc.dtype, device=_rvc.device)
                                    if float(_r_audio) >= 0.5 else
                                    torch.zeros((1, 1, 1, int(_rac.shape[-1])),
                                                dtype=_rvc.dtype, device=_rvc.device))
                            _r_latent["noise_mask"] = comfy.nested_tensor.NestedTensor((_pcv, _amc))
                            print(f"[H3 Remix] v14.347 二采沿用人物掩码: 重绘区 "
                                  f"{float(_pcv.mean()) * 100:.1f}% (背景继续锁一采源像素)")
                    except Exception as _rm2e:
                        print(f"[H3 Remix] v14.347 二采掩码沿用失败(退回全帧二采): {_rm2e}")
            else:
                _r_noise = None
                _r_latent = None

            # 3) DisableNoise 二采：从 CONST 加噪 latent 完整去噪（不再 prepare_noise 覆盖）
            # v1.47: 采样前主动确保 diffusion 模型驻留显存. DynamicVRAM
            # 模式下模型一采后会被完全释放(allocated≈0GB), 若依赖按需重载,
            # 21.8GB 全量加载在 24GB 卡上会假死(见 v1.47 预算注释).
            # load_model_gpu 同步加载, OOM 抛异常可走下方 fallback, 不静默卡死.
            _refine_model = model  # v14.142: 二采用模型（DynamicVRAM 时替换为 non-dynamic delegate）
            _ext_resv_orig = None  # v14.142: delegate 路径进入前的 EXTRA_RESERVED_VRAM 原值
            try:
                import torch as _torch3
                import comfy.model_management as _mm3
                # v1.54: 一采后 allocated≈3.7GB(显存碎片/cache) 不代表模型驻留——原判断
                # `allocated<1.0` 会漏判(3.75>1.0 跳过加载), 二采 0 驻留全流式,
                # 每步 21.8GB 换页 → 实测 209s/it. 改以 model.loaded_size() 判断
                # 实际权重驻留, <12GB 即主动重驻留(reserve 5.5GB 预算: 驻留 ~11-16GB,
                # 尾部 offload, 比全流式少换一半以上权重).
                _res_gb = 0.0
                try:
                    _res_gb = model.loaded_size() / 1024 ** 3
                except Exception:
                    pass
                if _res_gb < 12.0:
                    # v1.89: DynamicVRAM 模式检测——模型 is_dynamic() 时 load_models_gpu
                    # 只重新 staged(不真正驻留), 且 staged ~20GB 分配占满显存, 分块
                    # 初始化死等 staged 完成 -> 死锁(4090 实测: resident=0.0GB,
                    # 卡 0/6 Model Initializing)。dynamic 模式跳过手动重驻留,
                    # 交 DynamicVRAM 自身调度(一采同路径实测正常)。
                    # v1.89b: is_dynamic() 是 ModelPatcher 方法(model_patcher.py L403),
                    # 直接调 model.is_dynamic(), 不要取 model.model(v1.89 误写导致检测失效)。
                    try:
                        _is_dyn = bool(model.is_dynamic())
                    except Exception:
                        _is_dyn = False
                    if _is_dyn:
                        # v14.142 (2026-10-13): DynamicVRAM 二采 0 驻留全流式换页根治。
                        # 根因: DynamicVRAM 开启时一采后模型被完全卸载(allocated≈0GB),
                        # 二采交 staged 调度 = 每步 21.8GB CPU↔GPU 逐层换页 → 实测 637s/it
                        # (历史同根因: v1.54 209s、v1.87 313s、v1.90 分块 900s/步)。
                        # 修复: 用官方 get_non_dynamic_delegate()/clone(disable_dynamic=True)
                        # 生成非 dynamic delegate, 对 delegate 走标准 load_models_gpu 部分驻留
                        # (reserve 预算内驻留 + offload 尾部, 换页量减 2/3, 提速 2-3 倍)。
                        # delegate 与原 model 共享底层权重(模型缓存命中), 采样语义不变;
                        # 失败回退原路径(维持现状, 不会更糟)。
                        try:
                            _r_ws_dyn = _ws_tbl.get(round(_r_factor, 1), 2.6)
                            _r_resv_dyn = _model_gb2 - (_gpu_total_gb2 - _r_ws_dyn - 3.0 - 1.5)
                            _r_resv_dyn = max(3.0, min(8.0, _r_resv_dyn))
                            if tiled_refine:
                                _r_resv_dyn = max(_r_resv_dyn, 7.5)
                            _r_delegate_dyn = None
                            try:
                                if hasattr(model, "get_non_dynamic_delegate"):
                                    _r_delegate_dyn = model.get_non_dynamic_delegate()
                            except Exception:
                                _r_delegate_dyn = None
                            if _r_delegate_dyn is None:
                                _r_delegate_dyn = model.clone(disable_dynamic=True)
                            # v14.143 (2026-10-13): 曾以为 delegate 是 cached_patcher_init 重新
                            # 加载的全新模型对象, KJNodes 补丁(MethodType 绑定原模型 block 实例)
                            # 被 clone 复制后必然错位 -> 删掉补丁走原生 forward。实机证明这是
                            # 错误方向(v14.144 实测): 全幅 latent 中间激活暴涨到 6.35GB
                            # (allocated 18.05GB = 驻留 11.7 + 中间 6.35), Sol-Attn workspace
                            # 6.33GB 挤不下(24.38 > 23.86, 差 0.5GB), 连 sage 3.03GB 也失败,
                            # 依次降级到 pytorch attention, 二采失去稀疏加速。
                            # 参考插件(v14.82, 用户实测二采 240s/步 无雪花)恰恰是【保留
                            # KJNodes lowmem 分块 + Sol-Attn 的原 model 重驻留】: qkv GEMM 后
                            # 立即释放 h/qkv 缓冲 + minimax_head_chunks 按 head 分组, 中间
                            # 激活被压到 ~1GB 级, Sol-Attn workspace 才有空间。
                            # v14.145 正确修法: 不是删除补丁, 而是在 delegate 上【重新绑定】
                            # KJNodes 补丁到 delegate 自己的 block/attn 实例(MethodType 的
                            # self 指向 delegate 对象, 消除 clone 复制导致的错位), 并从原
                            # model 恢复 minimax_head_chunks / sol_take_forward。
                            try:
                                import sys as _sys_kn145
                                import types as _types_kn145
                                _kj_mod145 = None
                                for _m145 in list(_sys_kn145.modules.values()):
                                    _mf145 = getattr(_m145, "__file__", "") or ""
                                    if _mf145.replace("\\", "/").endswith("nodes/minimax_nodes.py"):
                                        _kj_mod145 = _m145
                                        break
                                if _kj_mod145 is None:
                                    import importlib.util as _ilu_kn145
                                    _kj_path145 = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                "..", "ComfyUI-KJNodes", "nodes", "minimax_nodes.py")
                                    if os.path.exists(_kj_path145):
                                        _kj_spec145 = _ilu_kn145.spec_from_file_location("bsai_kj_minimax145", _kj_path145)
                                        _kj_mod145 = _ilu_kn145.module_from_spec(_kj_spec145)
                                        _kj_spec145.loader.exec_module(_kj_mod145)
                                _r_deleg_diff145 = _r_delegate_dyn.get_model_object("diffusion_model")
                                _r_deleg_blocks145 = getattr(_r_deleg_diff145, "blocks", None)
                                if (_kj_mod145 is not None
                                        and getattr(_kj_mod145, "minimax_block_lowmem_forward", None)
                                        and _r_deleg_blocks145):
                                    for _bi145, _blk145 in enumerate(_r_deleg_blocks145):
                                        _r_delegate_dyn.object_patches[f"diffusion_model.blocks.{_bi145}.forward"] = \
                                            _types_kn145.MethodType(_kj_mod145.minimax_block_lowmem_forward, _blk145)
                                        _attn145 = getattr(_blk145, "attn", None)
                                        if _attn145 is not None and hasattr(_attn145, "qkv_proj"):
                                            _r_delegate_dyn.object_patches[f"diffusion_model.blocks.{_bi145}.attn.forward"] = \
                                                _types_kn145.MethodType(_kj_mod145.minimax_attn_lowmem_forward, _attn145)
                                    # 从原 model 恢复 KJNodes 写入的 transformer_options 键
                                    _r_to145 = _r_delegate_dyn.model_options.get("transformer_options", {})
                                    _r_to_orig145 = model.model_options.get("transformer_options", {})
                                    if isinstance(_r_to145, dict) and isinstance(_r_to_orig145, dict):
                                        if "minimax_head_chunks" in _r_to_orig145:
                                            _r_to145["minimax_head_chunks"] = _r_to_orig145["minimax_head_chunks"]
                                        if "sol_take_forward" in _r_to_orig145:
                                            _r_to145["sol_take_forward"] = _r_to_orig145["sol_take_forward"]
                                        # v14.179 (2026-10-23): 回退 v14.166 的 head_chunks 4->1。
                                        # 实测: v14.166 把 delegate head 分组 4->1 后, 每块走
                                        # KJNodes 分组稀疏的注意力退化成全 head dense 路径,
                                        # 8 块二采 545s/步 > v14.149(4块+head4) 399s/步。
                                        # 恢复 head 分组 4, 让 KJNodes 低显存分组生效。
                                        # (v14.166 注释称"单次并行 kernel 注意力减半"与实机不符)
                                        _r_hc166 = int(_r_to145.get("minimax_head_chunks", 4))
                                        _r_to145["minimax_head_chunks"] = 4
                                        if _r_hc166 != 4:
                                            print(f"[H3 Extender] v14.179 二采 delegate head_chunks "
                                                  f"{_r_hc166}->4 (回退 v14.166, 恢复 KJNodes 分组稀疏)")
                                    print(f"[H3 Extender] v14.145 KJNodes 低显存补丁已重建绑定到 delegate({len(_r_deleg_blocks145)} blocks)")
                                else:
                                    print(f"[H3 Extender] v14.145 KJNodes 补丁重建跳过(模块/blocks 不可用), 走原生 forward")
                            except Exception as _re145:
                                print(f"[H3 Extender] v14.145 KJNodes 补丁重建失败(回退原生 forward): {_re145}")
                            # v14.144 (2026-10-13): Sol-Attn workspace 让位——曾因原生 forward
                            # 中间激活 6.35GB 挤爆, 临时把 reserve 上调 2.5GB。v14.145 恢复
                            # KJNodes lowmem 分块(head 分组)后中间激活与 Sol-Attn workspace
                            # 同步缩小(minimax_head_chunks 使 kernel 内部暂存随 head 组缩水),
                            # 还原为参考插件标准 reserve 公式(与 v14.82 逐行一致, 实测 240s/步)。
                            # 检测 Sol-Attn 挂载键仅用于日志提示, 不再额外让位。
                            try:
                                _r_to3 = _r_delegate_dyn.model_options.get("transformer_options", {})
                                if isinstance(_r_to3, dict) and (
                                        _r_to3.get("optimized_attention_override") or _r_to3.get("sol_compose")):
                                    print(f"[H3 Extender] v14.145 Sol-Attn 已挂载, 走 KJNodes head 分组稀疏路径")
                            except Exception:
                                pass
                            try:
                                _ext_resv_orig = _mm3.EXTRA_RESERVED_VRAM
                            except Exception:
                                _ext_resv_orig = None
                            _mm3.EXTRA_RESERVED_VRAM = int(_r_resv_dyn * 1024 ** 3)
                            _mm3.load_models_gpu([_r_delegate_dyn])
                            _torch3.cuda.synchronize()
                            try:
                                _res2d = _r_delegate_dyn.loaded_size() / 1024 ** 3
                                print(f"[H3 Extender] v14.145 DynamicVRAM 二采改用 non-dynamic delegate 驻留(KJNodes补丁重建): "
                                      f"resident={_res2d:.1f}GB / total={_r_delegate_dyn.model_size()/1024**3:.1f}GB "
                                      f"reserve={_r_resv_dyn:.1f}GB")
                            except Exception:
                                pass
                            _refine_model = _r_delegate_dyn
                        except Exception as _de142:
                            _refine_model = model
                            print(f"[H3 Extender] v14.145 non-dynamic delegate 创建失败, 回退 DynamicVRAM 流式: {_de142}")
                        if _refine_model is model:
                            print(f"[H3 Extender] DynamicVRAM 模式: 跳过手动重驻留, 交 DynamicVRAM staged 调度")
                        else:
                            print(f"[H3 Extender] v14.145 delegate 已接管二采采样模型(非 DynamicVRAM 驻留路径)")
                    else:
                        # v1.87: 分块二采也走重驻留。v1.68 曾对 tile_count>1 跳过重载
                        # 导致二采 0 loaded + 20GB 全流式换页(实测 313s/it, 极速-VDN
                        # 二采 3步x4tile ≈ 60min)。实测 reserve 8.0 预算下 19.5GB 基座
                        # 可驻留 ~13.6GB + offload ~6GB, 换页量减少 2/3, 分块采样提速
                        # 2-3 倍。prepare(CONST加噪)在 load 之前已完成, 不会被卸。
                        # v1.65: 二采前驻留控制——先卸载再按 reserve 重载, 让加载器按
                        # reserve 预算重新平衡驻留量, 给 Sol-Attn workspace 让位.
                        # 实测 19:34 x2.0: 直接 load_models_gpu 全量驻留 21.72GB,
                        # Sol-Attn kernel 603MB workspace 分不出 → OOM.
                        # reserve = 模型 - (total - ws - 3GB 余量 - 1.5GB conds):
                        #   x2.0(ws4.5): ~6.8GB -> 驻留 ~15GB
                        #   x1.5(ws2.6): ~4.9GB -> 驻留 ~17GB
                        #   x1.0(ws1.5): ~4.2GB -> 驻留 ~17.5GB
                        try:
                            _ws_need2 = _ws_tbl.get(round(_r_factor, 1), 2.6)
                            _r_reserve_gb = _model_gb2 - (_gpu_total_gb2 - _ws_need2 - 3.0 - 1.5)
                            _r_reserve_gb = max(3.0, min(8.0, _r_reserve_gb))
                            # v1.88: 分块二采时 ComfyUI 按全幅估算 workspace(ws_need2)并判断
                            # free < ws+2GB 就卸载驻留模型(实测: reserve5.0->驻留16.3GB free5.2GB
                            # <6.5GB -> Unloaded到0 loaded -> 分块forward死锁0/3)。
                            # v14.341 分块下限 7.5 -> v14.377 5.0: 分块后每 tile 只跑
                            # ~1/n tokens, per-tile Sol-Attn workspace 远小于全幅
                            # ws_need2。7.5GB 下限让模型只驻留 13.5GB / offload 6.2GB,
                            # 每 tile 每层都要过 PCIe 搬权重(实机 py-spy: ~33% 主机
                            # 时间在 cast_bias_weight/cast_to, GPU 仅 ~100W/450W)。
                            # v14.224 empty_cache 已解决 cached 池误判; 本段下方的
                            # v14.250 探针(py-spy 版 v14.377: 分块时按 per-tile 判定)
                            # 会在 free 真不够时自适应让位抬 reserve, 不会 OOM。
                            # 下限 5.0GB: 模型驻留 ~17GB / offload ~2.5GB。
                            if tiled_refine:
                                _r_reserve_gb = max(_r_reserve_gb, 5.0)
                                # v14.382 (2026-11-12): 分块段按 per-tile workspace
                                # 定预算。v14.240 的「上次实测 reserve 提示」是**全帧**
                                # 二采测出来的(6.8GB), 复用到分块段会把 resident 压到
                                # 14.4GB / offload 6.3GB —— 实机 py-spy 常驻
                                # cast_bias_weight, 每块 >150s; 而一采 17.4GB /
                                # offload 3.2GB 时 710k tokens 只要 65s/步。分块段
                                # 单块只有 1/n tokens, 用不着全帧 workspace, 因此
                                # 这里把上限压到 5.5GB(驻留 ~17GB), 真不够时下方
                                # v14.381 per-tile 探针会自适应抬回。
                                _r_reserve_gb = min(_r_reserve_gb, 5.5)
                            # v14.240: 用上次实测的 reserve(见本文件下方 workspace 探针)。
                            # 链式渲染 clip>=2 直接命中, 省一次全卸重驻留。
                            # v14.382: 分块段不复用全帧测出来的提示(见上)。
                            _hint240 = None if tiled_refine else _REFINE_WS_RESERVE_HINT.get(round(_r_factor, 2))
                            if _hint240:
                                _r_reserve_gb = max(_r_reserve_gb, min(8.0, _hint240))
                                print(f"[H3 Extender] v14.240 复用上次实测 reserve "
                                      f"{_r_reserve_gb:.1f}GB (x{_r_factor}), 免重驻留")
                            _ff_unregister_model(model, label="二采-reserve-branch")
                            _mm3.EXTRA_RESERVED_VRAM = int(_r_reserve_gb * 1024 ** 3)
                        except Exception:
                            _r_reserve_gb = 5.5
                            _ff_unregister_model(model, label="二采-reserve-fallback")
                            _mm3.EXTRA_RESERVED_VRAM = int(_r_reserve_gb * 1024 ** 3)
                        print(f"[H3 Extender] Refine 二采前 DiT 驻留 {_res_gb:.1f}GB < 12GB, 重新驻留到 VRAM (reserve->{_r_reserve_gb:.1f}GB) ...")
                        _mm3.load_models_gpu([model])
                        _torch3.cuda.synchronize()
                        try:
                            _res2 = model.loaded_size() / 1024 ** 3
                            print(f"[H3 Extender] Refine 二采前 DiT 驻留: resident={_res2:.1f}GB / total={model.model_size()/1024**3:.1f}GB")
                        except Exception:
                            _res2 = 0.0
                            pass
                        # v14.383 (2026-11-12): 分块二采的 reserve 改成**按实测空闲
                        # 显存闭环定档**, 不再用任何经验常数。
                        # 实机两次对照(同一张卡 24GB, x2.0 264k/块):
                        #   reserve 8.9 -> resident 10.9GB / free ~3.5GB -> 每块 108.4s
                        #   reserve 6.8 -> resident 14.4GB / free 0.2GB  -> 单块 forward
                        #     内部反复腾挪权重, py-spy 全命中 cast_bias_weight, tile 1
                        #     >20min 未结束(GPU 99W)
                        # 结论: 决定速度的不是「驻留多少」, 而是**还剩多少空闲显存** ——
                        # free≈0 时每个 block 的中间张量都逼出一次权重换页, 比驻留少
                        # 3GB 还糟。目标带: free 3.0-6.2GB(定档 3.8GB), 迭代 3 次收敛。
                        _tiled383 = bool(tiled_refine)
                        _tok383 = 0
                        try:
                            _m383, _ = _ff_extract_members(samples)
                            if _m383 is not None and getattr(_m383[0], "ndim", 0) >= 4:
                                _tok383 = (int(_m383[0].shape[2]) * int(_m383[0].shape[-2])
                                           * int(_m383[0].shape[-1]))
                                if _tok383 > 130000:
                                    _tiled383 = True
                        except Exception:
                            _tok383 = 0
                        if _tiled383:
                            try:
                                _free383 = _torch3.cuda.mem_get_info()[0] / 1024 ** 3
                                _it383 = 0
                                while _it383 < 3 and (_free383 < 3.0 or _free383 > 6.2):
                                    _it383 += 1
                                    if _free383 < 3.0:
                                        _d383 = (3.8 - _free383)
                                    else:
                                        _d383 = -min(_free383 - 3.8, 2.5)
                                    _new383 = max(2.5, min(10.0, _r_reserve_gb + _d383))
                                    if abs(_new383 - _r_reserve_gb) < 0.2:
                                        break
                                    _ff_unregister_model(model, label="二采-free-vram-loop")
                                    _mm3.EXTRA_RESERVED_VRAM = int(_new383 * 1024 ** 3)
                                    _mm3.load_models_gpu([model])
                                    _torch3.cuda.synchronize()
                                    _r_reserve_gb = _new383
                                    _res383 = model.loaded_size() / 1024 ** 3
                                    _free383 = _torch3.cuda.mem_get_info()[0] / 1024 ** 3
                                    print(f"[H3 Extender] v14.383 二采自由显存闭环 {_it383}/3: "
                                          f"reserve={_r_reserve_gb:.1f}GB resident={_res383:.1f}GB "
                                          f"free={_free383:.1f}GB (目标 3.8GB, 带 3.0-6.2GB)")
                                print(f"[H3 Extender] v14.383 二采驻留定档: reserve={_r_reserve_gb:.1f}GB "
                                      f"resident={model.loaded_size()/1024**3:.1f}GB "
                                      f"free={_free383:.1f}GB (分块 {_tok383//1000}k tokens/块几何, "
                                      f"迭代 {_it383} 次)")
                            except Exception as _e383:
                                print(f"[H3 Extender] v14.383 二采自由显存闭环失败, 沿用 reserve="
                                      f"{_r_reserve_gb:.1f}GB: {_e383}")
                        # v1.65: 验证 Sol-Attn workspace 空间, 不足时醒目提示(采样走
                        # lowvram 换页兜底, 不会静默 OOM; 下次跑会在预算区提前降级).
                        # v14.224: free=0 多为 torch caching allocator 的 cached 池未释放
                        # (驻留 17.5GB + cached 4.5GB 后驱动 free≈0), 先主动 empty_cache
                        # 回收, 重查仍不足才提示——避免 Sol-Attn kernel workspace 分配
                        # 失败导致每步 1401s 的全量换页风暴.
                        try:
                            import torch as _torch65
                            _f65, _t65 = _torch65.cuda.mem_get_info()
                            _free65 = _f65 / 1024 ** 3
                            _ws65 = _ws_tbl.get(round(_r_factor, 1), 2.6)
                            _probe_ok240 = True
                            if _free65 < _ws65 + 2.0:
                                _fixed65 = False
                                try:
                                    import gc as _gc65b
                                    _gc65b.collect()
                                    _torch65.cuda.synchronize()
                                    _torch65.cuda.empty_cache()
                                    _f65b, _ = _torch65.cuda.mem_get_info()
                                    _free65 = _f65b / 1024 ** 3
                                    _fixed65 = _free65 >= _ws65 + 2.0
                                except Exception:
                                    pass
                                if _fixed65:
                                    print(f"[H3 Extender] v14.224 workspace 修复: "
                                          f"empty_cache 回收 cached 池后 free={_free65:.1f}GB "
                                          f">= ws {_ws65:.1f}GB+2GB, Sol-Attn workspace 可分配")
                                else:
                                    # v14.250 (2026-10-29): 探针改为「tokens > 130k 时
                                    # 强制让位, 不试分配」。v14.240 的试分配探针在
                                    # x1.0 218k 场景下"通过"了, 但实测 992~1339s/it —
                                    # 因为探针的 2GB 是在采样开始前试分配, 采样起来
                                    # latent/conds/VAE 中间缓冲挤占后, kernel 被迫走
                                    # 慢速备用路径。218k > 130k 已触发自动分块, 故
                                    # 探针直接判定为"不可信", 无条件走让位路径,
                                    # 保持满驻留不降倍率, 分块后每块 ~55k 在健康区。
                                    _probe_ok240 = False
                                    _r_tok_probe250 = 0
                                    try:
                                        _r_m_gate250, _ = _ff_extract_members(samples)
                                        if _r_m_gate250 is not None and getattr(_r_m_gate250[0], "ndim", 0) >= 4:
                                            _r_tok_probe250 = int(_r_m_gate250[0].shape[2]) * int(_r_m_gate250[0].shape[-2]) * int(_r_m_gate250[0].shape[-1])
                                    except Exception:
                                        pass
                                    # v14.377: 「>130k 无条件让位」这条门是对**全帧未分块**
                                    # 的病态规模(n>=440k 时 Sol-Attn 超线性恶化)判的。
                                    # 分块二采单块只有全帧的 1/5~1/8(实测 709,920 -> 每块
                                    # 136,068), 继续套这条门会把 per-tile 够用的 workspace
                                    # 误判成不够, 把刚降下来的 reserve 又弹回 7GB 档。
                                    # 分块时改走真实试分配: 分配得到就保持满驻留, 分配不到
                                    # 才让位 —— 不掺任何经验常数。
                                    # v14.381 (2026-11-12): 这段探针跑在 v14.181 自动分块
                                    # 决策之前，用的是本函数早先拿到的 tiled_refine 旗标；
                                    # 而 v14.181 的真判据是「tokens > 130k 就分块」。实测
                                    # 709,920 tokens 明明走自动分块(每块 272k)，这里却还是
                                    # False，于是落回「>130k 无条件让位」：reserve 6.8->8.9GB、
                                    # resident 14.4->10.9GB，每条 forward 多搬 3.4GB 权重，
                                    # v14.380 实机二采每块 108.4s。改为按**块几何**判 workspace:
                                    # 单块序列约为全帧的 1/n，workspace 随序列长度缩放。
                                    _will_tile381 = bool(tiled_refine) or _r_tok_probe250 > 130000
                                    _ws381 = _ws65
                                    _ntile381 = 1
                                    if _will_tile381 and _r_tok_probe250 > 0:
                                        try:
                                            _ntile381 = max(1, int(_ff_auto_refine_tile_count(
                                                samples, 4, tile_overlap)))
                                        except Exception:
                                            _ntile381 = 4
                                        _ws381 = max(2.0, _ws65 * (1.0 / float(_ntile381)) * 1.5)
                                    _tiled_probe377 = _will_tile381
                                    if (not _tiled_probe377) and _r_tok_probe250 > 130000:
                                        print(f"[H3 Extender] v14.250 workspace 探针: tokens={_r_tok_probe250:,} > 130k "
                                              f"(已触发自动分块), 不试分配直接判定让位 — "
                                              f"保持满驻留 x{_r_factor}(不降倍率), "
                                              f"分块后每块 ~{_r_tok_probe250 // 4 // 1000}k 在健康区")
                                        _probe_ok240 = False
                                    else:
                                        try:
                                            _pb240 = int((_ws381 + 0.5) * 1024 ** 3)
                                            _pt240 = _torch65.empty(_pb240 // 4, dtype=_torch65.float32,
                                                                    device="cuda")
                                            del _pt240
                                            _torch65.cuda.synchronize()
                                            _torch65.cuda.empty_cache()
                                            _probe_ok240 = True
                                        except Exception as _pe240:
                                            _probe_ok240 = False
                                            print(f"[H3 Extender] v14.381 分块 workspace 探针失败: "
                                                  f"ws_tile≈{_ws381:.1f}GB 试分配 "
                                                  f"{_ws381 + 0.5:.1f}GB 失败({_pe240})")
                                    if _probe_ok240:
                                        if _tiled_probe377:
                                            print(f"[H3 Extender] v14.381 分块 workspace 探针通过: "
                                                  f"ws_tile≈{_ws381:.1f}GB(全帧 {_ws65:.1f}GB, "
                                                  f"{_ntile381} 块), 试分配 {_ws381 + 0.5:.1f}GB 成功 "
                                                  f"→ 保持满驻留 reserve={_r_reserve_gb:.1f}GB"
                                                  f"(不为全帧 workspace 让位)")
                                        else:
                                            print(f"[H3 Extender] v14.250 workspace 探针通过: "
                                                  f"free={_free65:.1f}GB 低于阈值 ws {_ws65:.1f}GB+2GB, "
                                                  f"但真实试分配 {_ws65 + 0.5:.1f}GB 成功(池内空闲块可复用), "
                                                  f"Sol-Attn workspace 可用 → 保持满驻留 x{_r_factor}(不降倍率)")
                                    else:
                                        _resv_old240 = float(locals().get('_r_reserve_gb', 5.5))
                                        _deficit240 = (_ws65 + 2.0) - _free65
                                        _resv240 = min(14.0, _resv_old240 + _deficit240 + 0.5)
                                        try:
                                            import gc as _gc240
                                            _ff_unregister_model(model, label="二采-workspace-adaptive")
                                            _mm3.EXTRA_RESERVED_VRAM = int(_resv240 * 1024 ** 3)
                                            _mm3.load_models_gpu([model])
                                            _torch65.cuda.synchronize()
                                            _gc240.collect()
                                            _torch65.cuda.empty_cache()
                                            _f240b, _ = _torch65.cuda.mem_get_info()
                                            _res240 = model.loaded_size() / 1024 ** 3
                                            _r_reserve_gb = _resv240
                                            _REFINE_WS_RESERVE_HINT[round(_r_factor, 2)] = _resv240
                                            print(f"[H3 Extender] v14.250 workspace 自适应让位: "
                                                  f"reserve {_resv_old240:.1f}->{_resv240:.1f}GB, "
                                                  f"resident={_res240:.1f}GB, "
                                                  f"free={_f240b / 1024 ** 3:.1f}GB "
                                                  f"(目标 ws {_ws65:.1f}GB+2GB), 倍率保持 x{_r_factor}")
                                        except Exception as _er240:
                                            print(f"[H3 Extender] v14.250 workspace 让位失败, "
                                                  f"走 lowvram 换页兜底(可忽略): {_er240}")
                        except Exception:
                            pass
            except Exception as _lg2:
                print(f"[H3 Extender] Refine 主动加载模型失败, 走 DynamicVRAM 按需流式: {_lg2}")
            # v14.238 Director 移植: 二采采样器独立选择(参考插件 Refine 节点
            # 一采 res_multistep / 二采 euler 分离设计)。inherit 时跟随一采。
            _r_sam_name = str(refine_sampler or sampler_name)
            if _r_sam_name in ("inherit", "inherit (跟随一采)", "None", "none", ""):
                _r_sam_name = str(sampler_name)
            _r_sampler = comfy.samplers.sampler_object(_r_sam_name)
            if _r_sam_name != str(sampler_name):
                print(f"[H3 Extender] v14.238 Director极速二采: 二采采样器 "
                      f"{_r_sam_name} (独立于 一采 {sampler_name})")
            # v1.48 分块二采(默认关): 长空间轴分块, 激活/attention workspace 随 tile_count
            # 线性下降. 算法移植自 MiniMaxH3 Director spatial_tiled_sampling.py (Apache-2.0).
            # 包装器对非 packed latent / 小尺寸自动回退全帧, 不破坏既有流程.
            _r_restore_tiles = None
            if tiled_refine and refine_mem_mode != "global":
                try:
                    import os as _os_t, importlib.util as _ilu_t
                    _tiles_path = _os_t.path.join(_os_t.path.dirname(_os_t.path.abspath(__file__)), "bsai_h3_spatial_tiles.py")
                    _tiles_spec = _ilu_t.spec_from_file_location("bsai_h3_spatial_tiles", _tiles_path)
                    _tiles_mod = _ilu_t.module_from_spec(_tiles_spec)
                    _tiles_spec.loader.exec_module(_tiles_mod)
                    _r_tiles_n164 = _ff_auto_refine_tile_count(samples, tile_count, tile_overlap)
                    _r_restore_tiles = _tiles_mod.wrap_sampler_spatial_tiles(
                        _r_sampler, n_tiles=_r_tiles_n164, overlap_pixels=int(tile_overlap))
                    print(f"[H3 Extender] Refine 分块二采已启用: n_tiles={_r_tiles_n164} overlap={tile_overlap}px (v14.181 恢复 128px 接缝融合)")
                except Exception as _te_t:
                    print(f"[H3 Extender] Refine 分块包装失败(回退全帧): {_te_t}")
                    _r_restore_tiles = None
            # v1.56: 二采挂耗时诊断 callback——一采 callback 是外层函数局部变量,
            # 二采取不到, 且二采 callback=None 无法定位第 4 步固定 ~420s 的瓶颈.
            _r_cb_t0 = {"t": None}
            def _r_step_cb(step, x0, x, total):
                try:
                    import time as _t56
                    _now56 = _t56.time()
                    if _r_cb_t0["t"] is not None:
                        _cm_u56, _cm_t56 = _commit_gb()
                        print(f"[H3 Extender] refine耗时诊断: step={step+1}/{total} 距上步 {_now56-_r_cb_t0['t']:.1f}s "
                              f"commit={_cm_u56:.1f}/{_cm_t56:.1f}GB "
                              f"cuda_alloc={torch.cuda.memory_allocated()/1024**3:.2f}GB "
                              f"cuda_reserved={torch.cuda.memory_reserved()/1024**3:.2f}GB")
                    _r_cb_t0["t"] = _now56
                except Exception:
                    pass
                # v1.62: Sol-Attn sigma 门修复(工作流 end_percent 0.9->1.0)已验证:
                # step4 428s -> 134s. 原 sol_attn 计数诊断因模块以 spec 方式加载
                # 无法共享 _stats, 移除, 保留耗时诊断即可.
            # v14.148 (2026-10-13): 方案A —— Sol-Attn kernel 病态规模门。
            # 独立基准实测(comfy_kitchen ck.sol_attn, RTX 5090 24GB, 与实机同参):
            #   n=218,280 -> 0.97s / n=293,760 -> 0.70s (健康)
            #   n=440,640 -> >45s / n=873,120 topk -> >600s / n=873,120 dense -> >60s (病态)
            # 病态与 topk routing 无关, 是 kernel 在 n>=~440k 时超线性恶化.
            # v14.250 (2026-10-29): 阈值 350k -> 130k 校准。
            # 依据: 本机实测 n=218,280 未分块 + v14.240 探针误报 "保持满驻留" ->
            # 二采 992~1339s/it(用户报告); n=440k+ 病态线参考值维持 440k。
            # 130k 确保 x1.0 218k 自动分块(4 块 x ~55k/块, 每块稳在健康区
            # ~76s/步一采基准, 二采 4 块 x overlap 后仍 < 240s/步目标),
            # 同时 x2.0 873k 等更高倍率仍走原 dense 回退门。
            _REFINE_MAX_SOL_TOKENS = 130000
            try:
                _r_tok_gate = 0
                _r_m_gate, _ = _ff_extract_members(samples)
                if _r_m_gate is not None and getattr(_r_m_gate[0], "ndim", 0) >= 4:
                    _r_tok_gate = int(_r_m_gate[0].shape[2]) * int(_r_m_gate[0].shape[-2]) * int(_r_m_gate[0].shape[-1])
            except Exception:
                _r_tok_gate = 0
            # v14.275: 门控必须看「单次调用」的 tokens, 不是整段 tokens。
            # 时间分块二采每次只喂 temporal_chunk_tokens 帧(实机 T=87/chunk=29
            # → 29*68*120=236,640), 旧代码拿整段 709,920 去比 130k 阈值, 于是
            # 每个健康的分块调用都被 sol_max_tokens 强制降级成 dense attention。
            # 分块后的单段在 Sol-Attn 健康区(基准 218k=0.97s/步, 293k=0.70s/步),
            # 用 350k 作为该路径的上限(v14.225 验证过的健康区上界)。
            _r_call_tok = _r_tok_gate
            if _use_temporal:
                try:
                    _r_m_call, _ = _ff_extract_members(samples)
                    _r_call_tok = int(int(temporal_chunk_tokens)
                                      * int(_r_m_call[0].shape[-2]) * int(_r_m_call[0].shape[-1]))
                except Exception:
                    _r_call_tok = _r_tok_gate
            # v14.278: 单次采样档的 tokens 已由倍率预算压到 <=180,000(与一采同规模),
            # 门限按 180k 判 —— 仍用 130k 会把它误判成病态规模, 强制降级 dense
            # 并套 global 包装(全序列 dense attention, 每步上百秒)。
            _r_gate_limit = 180000 if (_use_temporal or refine_single_pass) else _REFINE_MAX_SOL_TOKENS
            # v14.164 (2026-10-22 fix #v14.173): 方案A — 先分块再决定 dense 降级。
            # 旧顺序(v14.148 先注入 sol_max_tokens -> v14.164 后分块)导致分块成功后
            # dense 门仍留在 transformer_options 里, 每个 262k token 的 tile 强制
            # 走 dense attention (KJNodes+SageAttention) 而非稀疏 Sol-Attn —— 实机
            # 4090 二采每步 411s, 远高于稀疏 0.7s/块 × 6 块 = ~4.2s 的理论值.
            # 修复: 先做 v14.164 分块决策, 再基于"是否已分块"决定要不要给整段注入
            # dense 门. 分块成功时每块 ~262k tokens 已在 Sol-Attn 健康区, 不需要
            # dense 回退. 同时显式清理 transformer_options 里可能从上个 clip 残留
            # 的 sol_max_tokens.
            if _r_call_tok > _r_gate_limit and _r_restore_tiles is None and refine_mem_mode != "global":
                try:
                    import os as _os_t3, importlib.util as _ilu_t3
                    _tiles_path3 = _os_t3.path.join(_os_t3.path.dirname(_os_t3.path.abspath(__file__)), "bsai_h3_spatial_tiles.py")
                    _tiles_spec3 = _ilu_t3.spec_from_file_location("bsai_h3_spatial_tiles", _tiles_path3)
                    _tiles_mod3 = _ilu_t3.module_from_spec(_tiles_spec3)
                    _tiles_spec3.loader.exec_module(_tiles_mod3)
                    _r_restore_tiles = _tiles_mod3.wrap_sampler_spatial_tiles(
                        _r_sampler, n_tiles=_ff_auto_refine_tile_count(samples, 4, tile_overlap), overlap_pixels=int(tile_overlap))
                    print(f"[H3 Extender] v14.181 方案A: latent tokens={_r_call_tok:,} > {_r_gate_limit:,}, "
                          f"自动启用分块二采 overlap={tile_overlap}px, n_tiles 按请求值(不扩块) "
                          f"(v14.149 固定 4 块 ~334k/块灰色区 399s/步 -> v14.164 扩 8 块 545s/步 反而更慢 -> v14.179 回退 -> v14.181 恢复 128px 接缝))")
                    # v14.173: 分块成功 —— 显式清理 transformer_options 里的 sol_max_tokens.
                    # 防止同一个 _refine_model 对象被二次调用时(链式 clip) 残留
                    # 上次注入的 dense 门, 把本该稀疏的 tile 强制降级.
                    try:
                        _r_to_clean = _refine_model.model_options.get("transformer_options", {})
                        if isinstance(_r_to_clean, dict) and "sol_max_tokens" in _r_to_clean:
                            _r_to_clean.pop("sol_max_tokens", None)
                            print(f"[H3 Extender] v14.173 清理残留 sol_max_tokens="
                                  f"已移除 (分块二启用, tile 稀疏保留)")
                    except Exception as _ec173:
                        print(f"[H3 Extender] v14.173 清理 sol_max_tokens 失败(可忽略): {_ec173}")
                except Exception as _te_t3:
                    print(f"[H3 Extender] v14.149 自动分块失败(走 v14.148 dense 回退门): {_te_t3}")
            # v14.148 (2026-10-13): 方案A — Sol-Attn kernel 病态规模门.
            # 独立基准实测(comfy_kitchen ck.sol_attn, RTX 5090 24GB, 与实机同参):
            #   n=218,280 -> 0.97s / n=293,760 -> 0.70s (健康)
            #   n=440,640 -> >45s / n=873,120 topk -> >600s / n=873,120 dense -> >60s (病态)
            # 病态与 topk routing 无关, 是 kernel 在 n>=~440k 时超线性恶化.
            # 只有在 v14.164 分块 **失败或被跳过** 时才触发 dense 降级 —— 此时整段
            # latent tokens 命中病态区, 才需要强制 dense 回退 (KJNodes 分组+
            # SageAttention). 分块成功时 tile 级 token 已在健康区, 稀疏 Sol-Attn
            # 直接跑通, 不注入 sol_max_tokens.
            if _r_call_tok > _r_gate_limit and _r_restore_tiles is None:
                try:
                    _r_to_gate = _refine_model.model_options.get("transformer_options", {})
                    if isinstance(_r_to_gate, dict):
                        _r_to_gate["sol_max_tokens"] = _REFINE_MAX_SOL_TOKENS
                        print(f"[H3 Extender] v14.148 方案A: 二采单次调用 tokens={_r_call_tok:,} > "
                              f"{_r_gate_limit:,} 且未启用分块, "
                              f"Sol-Attn 已降级 dense(KJNodes 分组+SageAttention), "
                              f"绕开病态 kernel(基准: 293k=0.7s 健康 / 440k>45s / 873k>600s)")
                except Exception as _eg:
                    print(f"[H3 Extender] v14.148 方案A 注入 sol_max_tokens 失败(可忽略): {_eg}")
            elif _r_restore_tiles is not None:
                print(f"[H3 Extender] v14.148 方案A: 二采单次调用 tokens={_r_call_tok:,} > "
                      f"{_r_gate_limit:,}, 分块二启用 — tile 级 token 在健康区, "
                      f"Sol-Attn 稀疏保留")
            else:
                print(f"[H3 Extender] v14.148 方案A: 二采单次调用 tokens={_r_call_tok:,} <= "
                      f"{_r_gate_limit:,}, Sol-Attn 稀疏保留(健康区)"
                      f" (整段 {_r_tok_gate:,}, 时间分块 {int(temporal_chunk_tokens) if _use_temporal else 0} 帧/段)")
            # v14.153 (2026-10-20): 二采省显存模式 global —— 移植 selflift-Avatar
            # (commit 5b93b6c) global-context 路径, 暂存源码 vendor/selflift_avatar/。
            # 与 spatial(v14.149 4 块分块)互斥: global 跳过空间分块, 对二采模型加
            # tiled_model() 全序列包装 —— attention 全序列一次跑(无接缝/背景膨胀,
            # query 永不见裁剪), norm/proj/MLP 按 token_chunk 分块压激活显存。
            # 与本插件现有机制协同(已验证源码级兼容):
            #   - KJNodes head 分组(object_patches ...attn.forward): vendor
            #     _native_attention_chunked_mlp 调 block.attn(...) 仍走 KJNodes 路径;
            #   - Sol-Attn override: vendor 判为 unknown override -> 自动回退 global
            #     纯 dense 分块路径(use_stream/use_ram 强制关, 上游语义), v14.148
            #     sol_max_tokens 门保持注入(全序列 873k 仍需 dense 回退防病态 kernel);
            #   - v14.145 delegate(KJNodes 补丁重建): wrapper 在 DIFFUSION_MODEL 层,
            #     object_patches 同为 block/attn 层, 叠加不冲突。
            # 包装失败时打印警告并回退 spatial 行为(此时 v14.149 自动分块已因
            # refine_mem_mode 被跳过, 需补一次分块包装保底)。
            _r_global_fallback_tiles = False
            # v14.225: tokens 在 Sol-Attn 健康区(<=350k)时跳过 global 包装——
            # global tiled_model 检测到 Sol-Attn override 会回退 dense full-sequence,
            # 进而触发 v14.208 切 spatial 8 块(overlap 重复计算, 实测 171s/步)。
            # 但 218k 稀疏 Sol-Attn 全帧直接跑只需 0.97s/步(基准), 根本不需要
            # global 包装压激活。global 只在 tokens 超健康区(>350k)时才需要。
            _skip_global_healthy = bool(refine_mem_mode == "global"
                                        and _r_call_tok <= _r_gate_limit)
            if _skip_global_healthy:
                print(f"[H3 Extender] v14.225 二采单次调用 tokens={_r_call_tok:,} 在 Sol-Attn 健康区, "
                      f"跳过 global 包装(避免 attention override 回退 dense + 切 8 块), "
                      f"稀疏 Sol-Attn 直接跑全帧(基准 0.97s/步, 不分块无 overlap 重复)")
            if refine_mem_mode == "global" and not _skip_global_healthy:
                try:
                    import os as _os_g, importlib as _ilg
                    import sys as _sys_g
                    _venv_dir = _os_g.path.join(_os_g.path.dirname(_os_g.path.abspath(__file__)), "vendor")
                    if _venv_dir not in _sys_g.path:
                        _sys_g.path.insert(0, _venv_dir)
                    _gt = _ilg.import_module("selflift_avatar.h3_global_tiling")
                    _r_original_refine_model = _refine_model
                    _refine_model = _gt.tiled_model(_refine_model, 4096)
                    _fb = getattr(_refine_model, "_selflift_global_fallback", None)
                    print(f"[H3 Extender] v14.153 二采省显存模式: global 全上下文路径已包装 "
                          f"(token_chunk=4096, 无空间分块)"
                          + (f", 上游回退: {_fb}(检测到自制注意力 override, 走全序列 attention+分块 MLP)" if _fb else ""))
                    if _fb:
                        # v14.253 (fix): 不再因 attention override 回退 spatial 分块。
                        # 旧(v14.208): 看到 _selflift_global_fallback 就切 spatial 4~8 块
                        # → 每块被独立重画成一整套构图 → 画面横带叠加(用户实测)。
                        # 现: selflift_avatar.h3_global_tiling.tiled_model 内部已用
                        # force_dense_on_unknown=True 处理了 attention override ——
                        # 检测到 unknown override 时走 _native_attention_chunked_mlp
                        # (完整 full-sequence attention + 仅 MLP 分块), 不切空间轴,
                        # 画面完整。代价: 1.3M tokens dense attention 在 24GB 卡上
                        # 可能吃满显存甚至 OOM, 但比"画面被切成 4 条横带"好得多。
                        # 真 OOM 时用户改回 spatial 即可, 不必自动回退到坏画质路径。
                        print(f"[H3 Extender] v14.253 global 保留 attention override({_fb}) "
                              f"继续走 full-sequence dense attention + chunked MLP, "
                              f"不切 spatial 分块(避免画面横带叠加); "
                              f"若后续 OOM 请改回 spatial")
                        del _r_original_refine_model
                except Exception as _eg15:
                    print(f"[H3 Extender] v14.153 global 包装失败, 回退 spatial 分块保底: {_eg15}")
                    refine_mem_mode = "spatial"
                    _r_global_fallback_tiles = True
            # v14.224: global 回退后无条件补分块——原条件还要求 _r_tok_gate > 350K,
            # 但回退已证明"全序列路径在此机不可用"(Sol-Attn override + 24GB), 无论
            # token 多少都该切 spatial 分块: 218K 整段虽在 Sol-Attn 健康区, 但全帧
            # workspace 1.5GB 在驻留 17.5GB + reserve 3.9GB 后 free≈0 无法分配
            # (实测 1401s/it 换页风暴). 分块后每块 ~54K tokens 更快, workspace 需求
            # 随 tile 数线性下降(x1.0: 1.5GB -> 0.8GB/块), Sol-Attn 稀疏照常生效.
            # v14.275: 时间分块已启用时不再补 spatial 分块保底 —— 每次调用只剩
            # chunk 帧(~236k tokens, 在 Sol-Attn 健康区), 不存在"全序列路径不可用"
            # 的问题; 硬补 8 块反而把画面切成 8 条独立重构图(重影/碎屑)。
            if _r_global_fallback_tiles and _r_restore_tiles is None and not _use_temporal:
                try:
                    import os as _os_t4, importlib.util as _ilu_t4
                    _tiles_path4 = _os_t4.path.join(_os_t4.path.dirname(_os_t4.path.abspath(__file__)), "bsai_h3_spatial_tiles.py")
                    _tiles_spec4 = _ilu_t4.spec_from_file_location("bsai_h3_spatial_tiles", _tiles_path4)
                    _tiles_mod4 = _ilu_t4.module_from_spec(_tiles_spec4)
                    _tiles_spec4.loader.exec_module(_tiles_mod4)
                    _r_restore_tiles = _tiles_mod4.wrap_sampler_spatial_tiles(
                        _r_sampler, n_tiles=8, overlap_pixels=int(tile_overlap))
                    print(f"[H3 Extender] v14.180 回退保底: 已补启用 spatial 分块 n_tiles=8 overlap={tile_overlap}px (v1.95: 4->8 降 tile activation)")
                    # v14.208: 与 v14.173 同逻辑——spatial fallback 装好后,
                    # 若 transformer_options 里有之前注入的 sol_max_tokens (来自 v14.148),
                    # 必须清掉, 否则每个 tile (~262k tokens) 被强制 dense attention,
                    # 比稀疏 Sol-Attn 慢 60x 且可能再次 OOM.
                    try:
                        _r_to_clean4 = _refine_model.model_options.get("transformer_options", {})
                        if isinstance(_r_to_clean4, dict) and "sol_max_tokens" in _r_to_clean4:
                            _r_to_clean4.pop("sol_max_tokens", None)
                            print(f"[H3 Extender] v14.208 spatial fallback: 清理残留 sol_max_tokens="
                                  f"已移除 (tile 级 token 在健康区, Sol-Attn 稀疏保留)")
                    except Exception as _ec208:
                        pass
                except Exception as _te_t4:
                    print(f"[H3 Extender] v14.153 回退补分块失败(仅 v14.148 dense 门兜底): {_te_t4}")
            # v14.224: global 回退 -> spatial 分块后, 重新平衡显存给 workspace 让位.
            # 背景: 回退路径的 reserve 在 v14.208 之前已按"非分块"定好(用户场景 3.9GB),
            # 此时模型驻留 17.5GB + reserve 3.9GB 已把 24GB 吃满, 分块 forward 的
            # Sol-Attn workspace 仍无空间 -> 每步 1401s 换页风暴. 分块场景按 v1.88
            # 实测把 reserve 下限提到 7.5GB(驻留 ~14.3GB + offload ~5.2GB +
            # free ~7.2GB > 全幅 ws+2GB), ComfyUI 不再卸载驻留, Sol-Attn 每块
            # workspace(0.8GB@x1.0)可分配. 摘除重载让加载器按新 reserve 平衡.
            if _r_global_fallback_tiles and _r_restore_tiles is not None:
                try:
                    import torch as _t215, gc as _gc215
                    import comfy.model_management as _mm215
                    _gc215.collect()
                    _t215.cuda.synchronize()
                    _t215.cuda.empty_cache()
                    _f215, _ = _t215.cuda.mem_get_info()
                    _free215 = _f215 / 1024 ** 3
                    _ws215 = _ws_tbl.get(round(_r_factor, 1), 2.6)
                    if _free215 < _ws215 + 2.0:
                        # v1.96: _r_reserve_gb 在 spatial fallback 路径可能未定义, 给默认值
                        _r_reserve_gb = float(locals().get('_r_reserve_gb', 5.5))
                        # v14.377: 分块场景下限 7.5->5.5(此路径仅在 free<ws+2 的
                        # 运行时真不够时触发, 5.5 已留足 per-tile workspace 余量)。
                        # 非分块是**全幅** workspace, v1.88 实测 reserve 5.0 -> 驻留
                        # 16.3GB -> free 5.2GB < 6.5GB -> Unloaded 到 0 loaded ->
                        # 分块 forward 死锁, 因此非分块保持 6.0, 不下探到 5.0。
                        _is_tiled_now215 = bool(tiled_refine) or _r_restore_tiles is not None
                        _resv215 = max(5.5, _r_reserve_gb) if _is_tiled_now215 else max(6.0, _r_reserve_gb)
                        if _resv215 > _r_reserve_gb + 1e-6:
                            try:
                                _ff_unregister_model(model, label="二采-workspace-branch")
                            except Exception:
                                pass
                            _mm215.EXTRA_RESERVED_VRAM = int(_resv215 * 1024 ** 3)
                            _mm215.load_models_gpu([model])
                            _t215.cuda.synchronize()
                            _gc215.collect()
                            _t215.cuda.empty_cache()
                            _f215b, _ = _t215.cuda.mem_get_info()
                            print(f"[H3 Extender] v14.224 workspace 让位: reserve "
                                  f"{_r_reserve_gb:.1f}->{_resv215:.1f}GB, 重驻留后 "
                                  f"free={_f215b/1024**3:.1f}GB (目标 ws {_ws215:.1f}GB+2GB), "
                                  f"Sol-Attn 分块 workspace 已可分配")
                        else:
                            print(f"[H3 Extender] v14.224 分块回退后 free={_free215:.1f}GB "
                                  f">= ws {_ws215:.1f}GB+2GB, 无需降驻留")
                except Exception as _e215:
                    print(f"[H3 Extender] v14.224 workspace 平衡失败(可忽略): {_e215}")
            # v14.279 (2026-11-02 fix): ref2va conditioning 跟随二采 latent 的
            # **实际几何**(而不是名义倍率), 根治 "每个 clip 二采都 shape mismatch":
            # 旧 v14.250 直接按 _r_factor(本次 x1.02) 放大 cond, 但 latent 经
            # align=40px 取整后仍是 34x60(尺寸未变), cond 却被插值到 36x62 ->
            # PackedLayout 预留 9620 行 / cond 实到 10292 行 ->
            # comfy/ldm/minimax/model.py:576 广播崩溃, 二采全部回退一采。
            if _FF_COND_UPSCALE_FN is not None and _r_factor > 1.0 and conditioning:
                try:
                    _cm279, _ = _ff_extract_members(samples)
                    _tg279_h = int(_cm279[0].shape[-2]) if _cm279 else 0
                    _tg279_w = int(_cm279[0].shape[-1]) if _cm279 else 0
                    _FF_COND_FIT_STATS.update({"ref": 0, "kf": 0, "resized": 0})
                    _cond279 = _ff_fit_cond_geometry(
                        conditioning, _tg279_h, _tg279_w)
                    _nfit279 = int(_FF_COND_FIT_STATS.get("resized", 0))
                    if _nfit279 > 0:
                        conditioning = _cond279
                        print(f"[H3 Extender] v14.279 二采条件几何对齐: "
                              f"{_nfit279} 块 ref/keyframe latent -> "
                              f"{_tg279_w}x{_tg279_h} "
                              f"(ref={_FF_COND_FIT_STATS['ref']} "
                              f"kf={_FF_COND_FIT_STATS['kf']}, 名义 x{_r_factor:.2f} "
                              f"被 align 取整吸收, 行数与 PackedLayout 恒等)")
                    else:
                        print(f"[H3 Extender] v14.279 二采条件几何一致 "
                              f"({_tg279_w}x{_tg279_h} 未变), 跳过 cond 放大 "
                              f"(名义 x{_r_factor:.2f} 已被 align 取整吸收)")
                except Exception as _e_cond_up:
                    print(f"[H3 Extender] v14.279 二采条件几何对齐跳过(可忽略): "
                          f"{_e_cond_up}")

            _r_guider = _BasicGuider(_refine_model)
            _r_guider.set_conds(conditioning)
            # v1.64: 恢复 v1.59 驻留补丁(v1.61 改诊断时误删)——二采采样前
            # 跳过 sampler_helpers._prepare_sampling 的 load_models_gpu/free_memory,
            # 防止 prepare 按全幅 latent 估算把刚驻留的模型全卸(0.00 MB remains,
            # 全流式换页 21.8GB/步). v1.63 已修分块+refs mismatch, 分块重新启用.
            # 驻留量由 reserve(分块 8GB/非分块 5.5GB) 决定, 换页只限 offload 尾部.
            import comfy.sampler_helpers as _sh59
            _bsai_orig_prepare = _sh59._prepare_sampling
            def _bsai_refine_prepare(model, noise_shape, conds, model_options=None, force_full_load=False, force_offload=False):
                try:
                    # 模型已驻留, 跳过 load_models_gpu 防 free_memory 全卸
                    return model.model, conds, []
                except Exception as _pe59:
                    print(f"[H3 Extender] v1.64 跳过prepare-load失败, 回退原路径: {_pe59}")
                    return _bsai_orig_prepare(model, noise_shape, conds, model_options=model_options,
                                              force_full_load=force_full_load, force_offload=force_offload)
            # v14.209: 总是安装驻留补丁, 包括分块/spatial fallback.
            # v1.65 曾因 DynamicVRAM 分块驻留 OOM 跳过分块路径——但 v14.142
            # 已用 clone(disable_dynamic=True) 生成 non-dynamic delegate,
            # 彻底消除 DynamicVRAM staged 全量加载根因.
            # 原 guard `if not (tile_count and int(tile_count) > 1)` 还有两个 bug:
            #   a) tile_count 默认就是 4(函数签名), 导致非分块场景补丁也装不上;
            #   b) 即使 tiled_refine=False 且 tile_count=4, 用户走 v14.208 spatial
            #      fallback 装了 _r_restore_tiles 但驻留仍被跳过, 每 step 从 0MB
            #      全流式换页 21GB -> 797s/it.
            # 修复后: 跳过原生 prepare 的 load_models_gpu/free_memory, 保持已驻留
            # 的 13.8GB 在 GPU, 仅 offload 尾部 6.8GB 换页 -> 预计 200-300s/it.
            _sh59._prepare_sampling = _bsai_refine_prepare
            print(f"[H3 Extender] v14.209 驻留补丁已安装 (tile_count={tile_count}, "
                  f"跳过原生 prepare 的全卸, 保持已驻留权重在 GPU)")
            # v1.91: 解除 torch allocator 人为 16GB fraction 限制——运行中
            # 某库调用过 set_per_process_memory_fraction, 使 torch 可用上限
            # 仅 16GB, 二采全帧 staged 15.25GB + 4K workspace 3.05GB = 18.3GB
            # 被判 OOM 回退一采. reset 1.0 后 torch 用满物理 23.86GB,
            # 全帧二采不再 OOM. LLM 全在 CPU, 无其他显存用户, reset 安全.
            # v1.93 (2026-09-16): 释放 aimdo VRAMBuffer(cast buffer, 一采加载期
            # 累积至 ~8.5GB 后常驻不释放). 主二采全程 _aimdo_disabled(), 该缓冲
            # 在二采阶段纯占显存——释放后 factor 2.0 全帧二采账本:
            # staged 15.4GB + workspace 3.08GB = 18.5GB < 23.86GB, 不再 OOM.
            try:
                import comfy.model_management as _mm93
                _released93 = 0
                for _k93 in list(_mm93.STREAM_AIMDO_CAST_BUFFERS):
                    try:
                        _buf93 = _mm93.STREAM_AIMDO_CAST_BUFFERS.pop(_k93)
                        del _buf93
                        _released93 += 1
                    except Exception:
                        pass
                if _released93:
                    import gc as _gc93
                    import torch as _torch93
                    _gc93.collect()
                    _torch93.cuda.synchronize()
                    _torch93.cuda.empty_cache()
                    print(f"[H3 Extender] v1.93 已释放 aimdo cast buffer x{_released93} (~8GB VRAM 回归可用)")
                else:
                    print(f"[H3 Extender] v1.93 无 aimdo cast buffer 需释放")
            except Exception as _e93:
                print(f"[H3 Extender] v1.93 释放 aimdo cast buffer 失败: {_e93}")
            try:
                import torch as _t91
                _cur_frac91 = _t91.cuda.get_per_process_memory_fraction()
                _t91.cuda.set_per_process_memory_fraction(1.0)
                if _cur_frac91 < 1.0:
                    print(f"[H3 Extender] v1.91 解除 fraction 限制: {_cur_frac91:.3f} -> 1.0 (二采可用 23.86GB)")
                else:
                    print(f"[H3 Extender] v1.91 fraction 已是 1.0, 无需解除")
            except Exception as _e91:
                print(f"[H3 Extender] v1.91 fraction reset 失败: {_e91}")
            # v14.251 (2026-10-29): 二采首步预热 —— 第 1 大步的"初始化税"
            # (Sol-Attn workspace 首次分配 4.5GB、KJNodes head 分组首触发、
            # tiled proxy 首次调度、keyframes/PackedLayout 首次构建) 全部移到
            # 真实进度条(0/4)之前: 用 1/8 空间小块 + 独立 seed 空跑最后一段
            # sigma 一步, 不污染真实采样状态, 失败则静默跳过。
            try:
                import comfy.utils as _cu_w, comfy.sample as _cs_w, comfy.nested_tensor as _cnt_w
                # v14.263: 分块二采/AV 双成员下 samples 可能是 NestedTensor, 也可能是
                # 裸 list/tuple/dict 的嵌套结构。旧实现只展平一层就取 [0] 当视频张量,
                # 只要真实结构再深一层就 `.shape` 报 "list object has no attribute
                # shape" 而整段预热被静默跳过。这里改成"深度优先展平 + 按维度挑成员",
                # 并且每个阶段单独打标, 万一仍失败能直接看出是卡在哪一步。
                _stage_w = "flatten"
                # v14.270 (2026-10-31 fix): 时间分块二采路径下 _r_latent 不会被创建
                # (它只在 `if not _use_temporal` 分支里构造), 旧实现直接取
                # _r_latent["samples"] 会 NameError -> 整段预热静默跳过 -> 第 1 大步
                # 独自扛下全部初始化税, 加剧 0/4 假死。这里加 fallback 到 samples。
                _w_lat_src = locals().get("_r_latent")
                if not (isinstance(_w_lat_src, dict) and "samples" in _w_lat_src):
                    _w_lat_src = {"samples": samples}
                _wflat_w, _wstack_w = [], list(_ff_extract_members(_w_lat_src["samples"])[0])
                while _wstack_w:
                    _mw = _wstack_w.pop(0)
                    if isinstance(_mw, torch.Tensor):
                        _wflat_w.append(_mw)
                    elif isinstance(_mw, dict):
                        _wstack_w[:0] = list(_mw.values())
                    elif isinstance(_mw, (list, tuple)):
                        _wstack_w[:0] = list(_mw)
                _wv_w = next((m for m in _wflat_w if m.dim() == 5), None)
                if _wv_w is None:
                    raise RuntimeError(
                        "samples 里没有 5 维视频成员: type=%s shapes=%s"
                        % (type(_w_lat_src.get("samples")).__name__,
                           [tuple(m.shape) for m in _wflat_w]))
                _wa_w = next((m for m in _wflat_w
                              if m is not _wv_w and m.dim() >= 3), None)

                _stage_w = "crop"
                # v14.282 (2026-11-04 fix): 预热 dummy 必须与 conditioning 保持
                # 相同空间几何 —— v14.279 已把 ref/keyframe latent 对齐到二采
                # 实际 120x68，旧 v14.251 又把 dummy 空间裁到 1/8(8x15)，sample
                # 时 PackedLayout 索引广播 shape mismatch([36720,96] vs
                # [8608,96])，预热失败后真实二采进入死循环(GPU 满载但 0/2 卡死、
                # 无 step 日志)。改为只裁剪时间轴帧数省开销，空间保持完整。
                _wh_w = int(_wv_w.shape[-2])
                _ww_w = int(_wv_w.shape[-1])
                _wt_w = max(2, int(_wv_w.shape[2]) // 16)
                _wv_s = _wv_w[:, :, :_wt_w, :, :].contiguous()
                _wa_s = _wa_w[..., :2048].contiguous() if _wa_w is not None else None
                _w_streams = [_wv_s] + ([_wa_s] if _wa_s is not None else [])

                _stage_w = "NestedTensor"
                _wbase = _cnt_w.NestedTensor(tuple(_w_streams))
                _stage_w = "set_conds"
                _w_guider_w = _BasicGuider(_refine_model)
                _w_guider_w.set_conds(conditioning)
                _stage_w = "prepare_noise"
                _w_noise_w = _cs_w.prepare_noise(_wbase, int(seed) + 999, None)
                # v14.279: NestedTensor.prepare_noise 在部分版本返回 list ->
                # 采样器对 noise 调 .shape 时抛 "'list' object has no attribute
                # 'shape'", 预热每次都被静默跳过(第 1 大步独自扛初始化税)。
                if isinstance(_w_noise_w, (list, tuple)):
                    _w_noise_w = _cnt_w.NestedTensor(tuple(_w_noise_w))
                # v14.279: sigmas 必须保持 tensor —— 旧实现 list(_r_sigmas)[-2:]
                # 把 tensor 变成 python list, sampler 对 sigmas 调 .shape 直接崩。
                _w_sig_w = _r_sigmas[-2:]
                _stage_w = "sample"
                with _aimdo_disabled():
                    _w_guider_w.sample(
                        _w_noise_w, _wbase, _r_sampler, _w_sig_w,
                        denoise_mask=None,
                        callback=None,
                        disable_pbar=True,
                        seed=int(seed) + 999,
                    )
                _stage_w = "sync"
                torch.cuda.synchronize()
                print(f"[H3 Extender] v14.251 二采首步预热完成 (dummy {_wh_w}x{_ww_w}, "
                      f"首次初始化已移出第 1 大步)", flush=True)
            except Exception as _we_w:
                print(f"[H3 Extender] v14.251 二采首步预热跳过[{locals().get('_stage_w', '?')}]: "
                      f"{type(_we_w).__name__}: {_we_w}", flush=True)
            try:
                if _use_temporal:
                    # v2.02 时间分块二采: 沿 T 切段, 逐段走已有(空间分块)采样器,
                    # 重叠区 denoise_mask 冻结 + smoothstep 接管. 见 bsai_h3_temporal_chunks.py
                    import os as _os_tc, importlib.util as _ilu_tc
                    _tc_path = _os_tc.path.join(_os_tc.path.dirname(_os_tc.path.abspath(__file__)), "bsai_h3_temporal_chunks.py")
                    _tc_spec = _ilu_tc.spec_from_file_location("bsai_h3_temporal_chunks", _tc_path)
                    _tc = _ilu_tc.module_from_spec(_tc_spec)
                    _tc_spec.loader.exec_module(_tc)
                    _mem_full, _was_nested_tc = _ff_extract_members(samples)
                    _vid_full = _mem_full[0]
                    _aud_full = _mem_full[1]
                    _T_full = int(_vid_full.shape[2])
                    _segs = _tc.plan_temporal_segments(_T_full, int(temporal_chunk_tokens), int(temporal_overlap_tokens))
                    if len(_segs) <= 1:
                        print(f"[H3 Extender] v2.02 时间分块: T={_T_full} <= chunk, 退化为整段二采")
                    else:
                        print(f"[H3 Extender] v2.02 时间分块二采: T={_T_full} chunk={temporal_chunk_tokens} "
                              f"overlap={temporal_overlap_tokens} -> {len(_segs)} 段 {_segs}", flush=True)
                    _acc_v = None
                    for _ki, (_st, _et) in enumerate(_segs):
                        _cv, _ca = _tc.slice_nested_temporal(_mem_full, _st, _et)
                        _ov_here = 0
                        _mask_ki = None
                        if _acc_v is not None:
                            _ov_here = max(0, int(_acc_v.shape[2]) - _st)
                            _ov_here = min(_ov_here, int(_cv.shape[2]))
                        if _ov_here > 0:
                            _cv = _cv.clone()
                            _cv[:, :, :_ov_here] = _acc_v[:, :, _st:_st + _ov_here]
                            _mask_ki, _lock_n, _ = _tc.build_temporal_mask(
                                int(_cv.shape[2]), _ov_here, dtype=_cv.dtype, device=_cv.device)
                        else:
                            _lock_n = 0
                        _chunk_base = comfy.nested_tensor.NestedTensor((_cv, _ca))
                        _chunk_noise = comfy.sample.prepare_noise(_chunk_base, int(seed) + 1 + _ki, None)
                        _chunk_latent = _ff_const_add_noise(_refine_model, _chunk_noise, _r_sigmas,
                                                            {"samples": _chunk_base}, _r_audio)
                        # 加噪后把整个重叠区重填为上一段干净结果:
                        # 锁区(mask=0)采样器原样保留; 过渡区(0<mask<1) KSamplerX0Inpaint
                        # 按 out*m + latent_image*(1-m) 混合, 若保留加噪底则高比例噪声
                        # 直接混进发布结果(VAE 解码后=马赛克横带), 必须同为干净内容。
                        if _lock_n > 0:
                            _cl_members, _ = _ff_extract_members(_chunk_latent["samples"])
                            _cl_members[0][:, :, :_ov_here] = _acc_v[:, :, _st:_st + _ov_here]
                            _chunk_latent["samples"] = _ff_wrap_members(_cl_members, _was_nested_tc)
                            _a_part = _chunk_latent["samples"].tensors[1]
                            # v14.179 (2026-10-23): 音频掩码跟随 refine_audio_denoise,
                            # 不再无条件锁定。旧代码此处永远 mask=0(保持一采音频), 会
                            # 把"直播配音高清"档(音频≥12步+音频重绘0.7)的二采音频精修
                            # 覆盖回锁定, 导致分块二采下配音仍乱/含混。audio_denoise>=0.5
                            # 时音频参与二采重绘(mask=1), <0.5 时锁定(mask=0)。
                            if float(_r_audio) >= 0.5:
                                _amask = torch.ones((1, 1, 1, int(_a_part.shape[-1])),
                                                    dtype=_mask_ki.dtype, device=_a_part.device)
                            else:
                                _amask = torch.zeros((1, 1, 1, int(_a_part.shape[-1])),
                                                    dtype=_mask_ki.dtype, device=_a_part.device)
                            _chunk_latent["noise_mask"] = comfy.nested_tensor.NestedTensor((_mask_ki, _amask))
                        # v14.240 (fix): 分块二采·首块段头锁 keep —— 首块无前块
                        # 重叠(_ov_here=0), 原逻辑全重绘会把 clip 段头(一采已锁的
                        # 延续区)二次重画 → 段间跳帧。这里把首块段头 _os_head_rows
                        # 行锁为一采输出(samples)的干净延续画面, mask=0 不二次重绘。
                        if _ki == 0 and _os_head_rows >= 1 and _lock_n == 0:
                            try:
                                _cl_m0, _cl_n0 = _ff_extract_members(_chunk_latent["samples"])
                                _cv_os = _cl_m0[0]
                                _hrows_os = min(_os_head_rows, int(_cv_os.shape[2]))
                                if _hrows_os >= 1:
                                    _s_v_os = _mem_full[0]
                                    if _st == 0 and tuple(_s_v_os.shape[-2:]) == tuple(_cv_os.shape[-2:]):
                                        _cv_os = _cv_os.clone()
                                        _cv_os[:, :, :_hrows_os] = _s_v_os[:, :, :_hrows_os]
                                        _cl_m0[0] = _cv_os
                                        _chunk_latent["samples"] = _ff_wrap_members(_cl_m0, _cl_n0)
                                        _mask_h0 = torch.ones_like(_cv_os)
                                        _mask_h0[:, :, :_hrows_os] = 0.0
                                        _a_h0 = _cl_m0[1]
                                        if float(_r_audio) >= 0.5:
                                            _amask_h0 = torch.ones((1, 1, 1, int(_a_h0.shape[-1])),
                                                                   dtype=_cv_os.dtype, device=_cv_os.device)
                                        else:
                                            _amask_h0 = torch.zeros((1, 1, 1, int(_a_h0.shape[-1])),
                                                                    dtype=_cv_os.dtype, device=_cv_os.device)
                                        _chunk_latent["noise_mask"] = comfy.nested_tensor.NestedTensor((_mask_h0, _amask_h0))
                                        print(f"[H3 Extender] v14.240 分块首块段头锁 keep: {_hrows_os} 行锁定为一采延续画面(接缝零二次重绘)")
                            except Exception as _h0_err:
                                print(f"[H3 Extender] v14.240 分块首块段头锁失败(可忽略): {_h0_err}")
                        with _aimdo_disabled():
                            _chunk_out = _r_guider.sample(
                                comfy.sample.prepare_empty_noise(_chunk_latent["samples"]),
                                _chunk_latent["samples"],
                                _r_sampler,
                                _r_sigmas,
                                denoise_mask=_chunk_latent.get("noise_mask"),
                                callback=_r_step_cb,
                                disable_pbar=not comfy.utils.PROGRESS_BAR_ENABLED,
                                seed=int(seed) + 1 + _ki,
                            )
                        _out_mem, _ = _ff_extract_members(_chunk_out)
                        _acc_v = _tc.merge_guarded(_acc_v, _out_mem[0], _st, _lock_n)
                        print(f"[H3 Extender] v2.02 时间分块: 段 {_ki+1}/{len(_segs)} "
                              f"[{_st},{_et}) 完成, 累计 T={_acc_v.shape[2]}", flush=True)
                    _r_samples = _ff_wrap_members([_acc_v, _aud_full], _was_nested_tc)
                else:
                    with _aimdo_disabled():
                        _r_samples = _r_guider.sample(
                        comfy.sample.prepare_empty_noise(samples),
                        _r_latent["samples"],
                        _r_sampler,
                        _r_sigmas,
                        denoise_mask=_r_latent.get("noise_mask"),
                        callback=_r_step_cb,
                        disable_pbar=not comfy.utils.PROGRESS_BAR_ENABLED,
                        seed=int(seed) + 1,
                    )
            finally:
                try:
                    _sh59._prepare_sampling = _bsai_orig_prepare
                except Exception:
                    pass
                if _r_restore_tiles is not None:
                    try:
                        _r_restore_tiles()
                    except Exception:
                        pass
                # v14.142: 二采完成后卸载 non-dynamic delegate, 恢复 EXTRA_RESERVED_VRAM
                # 到进入前原值, 避免 delegate 驻留残留挤压下一 CLIP 一采的 DynamicVRAM
                # staged 空间. 原 dynamic model 交给 DynamicVRAM 自身调度.
                # v2.55c: ComfyUI 无 unload_model() API (仅 unload_model_and_clones, 且会
                # 连带卸载同 clone_base_uuid 的原 dynamic DiT, 不可用), 旧调用静默 no-op,
                # delegate 的 GPU 驻留量化权重跨 clip 泄漏(二采前 device_free 逐 clip
                # 下滑), 最终 TE 加载时 ComfyUI 标准路径对 delegate 执行
                # partially_load->unpatch_model->self.model.to(cpu) 触发 QuantizedTensor
                # 原生 access violation。修复: 直接从 current_loaded_models 摘除 delegate
                # 的 LoadedModel, 释放本地引用 + GC, 让 GPU 量化权重真正回收, 不再触碰 .to()。
                try:
                    if _refine_model is not model:
                        # v14.248 (fix, 2026-10-29): 二采 delegate 真正卸载。
                        # 旧卸载只摘注册+置 _refine_model=None, 但实测 decode 前
                        # allocated 仍残留 14.47GB(每段都爆 VAE decode OOM)。根因:
                        # ① _r_guider(BasicGuider 内部持有 model) 与 _r_sampler 仍
                        #    强引用 delegate/tiled-wrapper, GC 无法回收 GPU 权重;
                        # ② tiled/spatial wrapper 替换 _refine_model 后, 注册表
                        #    匹配 `is _refine_model` 失败, delegate 的 LoadedModel
                        #    条目未被摘除。修复: 卸载前先断开采样器/guider 引用,
                        #    再摘除全部非 vae 且非原 dynamic model 的注册条目,
                        #    最后 GC 3 轮 + 清缓存 + synchronize。
                        try:
                            from comfy.model_management import current_loaded_models as _r_clm
                            # v14.248: 按 ModelPatcher 身份精确摘除 delegate/wrapper 条目,
                            # 不误摘原 dynamic model(_rm_p is model 的条目保留, 交
                            # DynamicVRAM 调度)。
                            _r_target_ids = set()
                            for _r_tgt in (_refine_model, _r_delegate_dyn):
                                if _r_tgt is not None:
                                    _r_target_ids.add(id(_r_tgt))
                            for _ri in range(len(_r_clm) - 1, -1, -1):
                                try:
                                    _rm_p = _r_clm[_ri].model
                                except Exception:
                                    _rm_p = None
                                if _rm_p is not None and id(_rm_p) in _r_target_ids:
                                    _r_clm.pop(_ri)
                        except Exception:
                            pass
                        # v14.248: 断开采样器/guider/latent 对 delegate 的强引用
                        _r_guider = None
                        _r_sampler = None
                        _r_latent = None
                        _r_sigmas = None
                        _r_step_cb = None
                        _refine_model = model
                        _r_delegate_dyn = None
                        # v14.243 (2026-10-28): 清除原 dynamic model 对 delegate 的
                        # 缓存引用 —— get_non_dynamic_delegate() 会把 delegate 的
                        # get_clone_model_override()(=delegate.model, 独立加载的
                        # ~19.5GB 权重实例) 存入 self.non_dynamic_delegate_model 属性,
                        # 原 model 全程存活导致 delegate 的 GPU 量化权重无法被 GC。
                        # 实机佐证: 二采后摘注册+GC 后 allocated 仍 18.47GB, clip2
                        # 一采全流式换页 195s/步(vs clip1 71s), v14.186 报 DiT
                        # 19.5GB > 可用 0GB。清空后 delegate 强引用归零, GC 回收
                        # 全部 GPU 权重; 下次二采 get_non_dynamic_delegate 重新创建,
                        # 无副作用, 全程不触碰 .to(cpu)/unpatch。
                        try:
                            if hasattr(model, "non_dynamic_delegate_model"):
                                model.non_dynamic_delegate_model = None
                                print("[H3 Extender] v14.243 清除 delegate 缓存引用 "
                                      "(non_dynamic_delegate_model), GPU 权重可回收")
                        except Exception:
                            pass
                        try:
                            import gc as _gc
                            for _g_round in range(3):
                                _gc.collect()
                                try:
                                    _mm3.soft_empty_cache(force=True)
                                except Exception:
                                    pass
                            _torch3.cuda.synchronize()
                            _al_gb = _torch3.cuda.memory_allocated() / 1024 ** 3
                            _fr_gb = _torch3.cuda.mem_get_info()[0] / 1024 ** 3
                            print(f"[H3 Extender] v14.248 delegate 已卸载: allocated={_al_gb:.2f}GB "
                                  f"free={_fr_gb:.2f}GB (vs 卸载前 ~14.5GB, 为 VAE decode 腾显存)")
                        except Exception:
                            pass
                    if _ext_resv_orig is not None:
                        try:
                            _mm3.EXTRA_RESERVED_VRAM = _ext_resv_orig
                        except Exception:
                            pass
                except Exception:
                    pass
                # v14.148: 清理二采注入的 sol_max_tokens 门, 防止残留影响后续 CLIP 一采
                # (一采 218k 本就不会触发, 但保持模型状态干净).
                try:
                    _r_to_clean = model.model_options.get("transformer_options", {})
                    if isinstance(_r_to_clean, dict) and "sol_max_tokens" in _r_to_clean:
                        _r_to_clean.pop("sol_max_tokens", None)
                except Exception:
                    pass
            samples = _r_samples.to(comfy.model_management.intermediate_device())
            print(f"[H3 Extender] Refine 双采完成: clip={clip_index}")
        except _FFRefineSkip:
            # v14.384: 正常控制流 —— 二采只做了超分放大, 已按需跳出重绘段。
            try:
                _hv384 = _ff_video_hw(samples)
            except Exception:
                _hv384 = (0, 0)
            try:
                _m384, _wn384 = _ff_extract_members(samples)
                _aw384 = int(_m384[1].shape[-1]) if len(_m384) > 1 else 0
            except Exception:
                _aw384 = 0
            print(f"[H3 Extender] v14.384 二采只超分放大(不重绘): clip={clip_index} "
                  f"视频 {_hv384[1]}x{_hv384[0]} latent 直出(源自一采 x{_r_factor} 放大), "
                  f"音频保持一采({_aw384} 帧 latent), 已跳过 加噪/去噪/分块/驻留/探针 全部阶段")
            # 3D upscaler 缓存不再需要(二采不采样), 及早还给下一段一采
            try:
                if _FF_UPSCALER_MOD is not None:
                    import gc as _gc384
                    import torch as _t384
                    _cache384 = getattr(_FF_UPSCALER_MOD, "MODEL_CACHE", None)
                    if isinstance(_cache384, dict) and _cache384:
                        for _k384 in list(_cache384.keys()):
                            _m384w = _cache384.pop(_k384)
                            try:
                                _m384w.to("cpu")
                            except Exception:
                                pass
                            del _m384w
                        print(f"[H3 Extender] v14.384 3D upscaler 缓存已清理(二采不采样), 释放 VRAM")
                    _gc384.collect()
                    _t384.cuda.synchronize()
                    _t384.cuda.empty_cache()
            except Exception:
                pass
        except torch.cuda.OutOfMemoryError as _oom:
            # v1.43 (2026-09-13 fix #4): OOM fallback 不再 unload_all_models()!
            # v1.37 的 fallback 每次 unload_all_models() 都把 diffusion
            # 推入 full lowvram 模式 (0 MB loaded, 20 GB offloaded),
            # 导致 fallback 本身也 OOM.
            #
            # v1.43 策略: diffusion 保持 loaded, 只清 3D upscaler 缓存
            # + GC + empty_cache, 然后用备份的一采原始 samples (60x34)
            # 重跑二采. 原始尺寸 attention workspace ~1.5GB, 加上
            # 已加载的 diffusion ~20GB, 总计 ~22GB 能装进 24GB 卡.
            print(f"[H3 Extender] Refine OOM: {_oom}")
            print(f"[H3 Extender] 自动 fallback (v1.43 保留diffusion)")
            import gc as _gc
            import comfy.model_management as _mm
            import torch as _torch
            _gc.collect()
            # 清 3D upscaler 缓存释放 VRAM
            if _FF_UPSCALER_MOD is not None:
                try:
                    _cache = getattr(_FF_UPSCALER_MOD, "MODEL_CACHE", None)
                    if isinstance(_cache, dict) and _cache:
                        for _k, _m in list(_cache.items()):
                            try:
                                _m.to("cpu")
                            except Exception:
                                pass
                            del _m
                            del _cache[_k]
                except Exception:
                    pass
            _gc.collect()
            _mm.soft_empty_cache(force=True)
            _torch.cuda.synchronize()
            _torch.cuda.empty_cache()
            try:
                _torch.cuda.ipc_collect()
            except Exception:
                pass
            _torch.cuda.synchronize()
            _torch.cuda.empty_cache()
            # v1.43: 如果有备份的一采原始 samples, 直接用它们重跑
            # (跳过放大, attention workspace 最小). 没有备份时,
            # 尝试用当前 (放大后) samples 重跑 (3D upscaler 已清,
            # 可能腾出足够 VRAM).
            _fb_samples = _samples_pre_upscale if _samples_pre_upscale is not None else samples
            # v1.92 (2026-09-16): 主二采全帧 OOM 时, 不再无条件卸载重载——
            # DynamicVRAM 下卸载重载实测把模型 staged 到 21.36GB, 再加
            # 2.24GB workspace 二次 OOM(5090 v1.91 实测: 15.40+3.08 后
            # fallback 21.36+2.24 仍 OOM). 策略改为:
            #   1. 保持当前 staged 状态(驻留>2GB 时绝不卸载);
            #   2. 若主二采是全帧(v1.90 极速-VDN 强制关分块), 降级安装
            #      分块包装器重跑放大版——x2.0 画质完整, 分块 workspace
            #      ~1.1GB + staged ~15.4GB < 24GB 可跑(4090 实测 374s/步);
            #   3. 仅当模型已被全卸(<2GB)或分块包装失败时, 才用原始尺寸
            #      (x1.0) 兜底, 绝不再回退到一采无增强结果.
            _fb_use_tiles = False
            try:
                # v1.93 fix: 总是包装 tiles 重跑放大版 samples(120x68)。
                # 旧逻辑 if not (tile_count>1) 导致 tile_count>1 时跳过包装 ->
                # 退回 _fb_samples(60x34) 重跑 -> 二采马赛克 + bicubic 拉伸。
                if True:  # v1.93: always tile-wrap the upscaled samples
                    import os as _os_t2, importlib.util as _ilu_t2
                    _tiles_path2 = _os_t2.path.join(_os_t2.path.dirname(_os_t2.path.abspath(__file__)), "bsai_h3_spatial_tiles.py")
                    _tiles_spec2 = _ilu_t2.spec_from_file_location("bsai_h3_spatial_tiles", _tiles_path2)
                    _tiles_mod2 = _ilu_t2.module_from_spec(_tiles_spec2)
                    _tiles_spec2.loader.exec_module(_tiles_mod2)
                    _r_tiles_n164b = _ff_auto_refine_tile_count(samples, tile_count if tile_count else 4, tile_overlap)
                    _r_restore_tiles = _tiles_mod2.wrap_sampler_spatial_tiles(
                        _r_sampler, n_tiles=_r_tiles_n164b, overlap_pixels=int(tile_overlap))
                    _fb_use_tiles = True
                    print(f"[H3 Extender] v1.92 fallback: 降级分块重跑放大版 n_tiles={_r_tiles_n164b} (v14.164 健康区自适应, v1.93 fix: 保留 120x68 不退回 60x34)")
            except Exception as _te2:
                _fb_use_tiles = False
                print(f"[H3 Extender] v1.92 fallback 分块包装失败, 用原始尺寸兜底: {_te2}")
            _fb_use = samples if _fb_use_tiles else _fb_samples
            # v14.207: fallback 用一采 34x60 重跑时, PackedLayout 会按输入 x 的空间网格
            # 给 keyframe cond 预留行数, 而 _cond_video_rows 按 keyframe latent 的实际
            # 尺寸 patchify —— v14.162 已把它们放大到二采 68x120, 两者差 4 倍, 首步前向
            # 直接 shape mismatch: [51648,96] vs [14928,96]。重跑前把 keyframe 缩回
            # 一采空间; 分块重跑(仍用放大版)时几何本来就一致, 不动。
            if not _fb_use_tiles:
                try:
                    _fbm, _fbst = _ff_extract_members(_fb_use)
                    _fb_hw = tuple(_fbm[0].shape[-2:]) if _fbm else None
                    _cond_fb = conditioning[0][1] if isinstance(conditioning, list) else conditioning
                    if _fb_hw and isinstance(_cond_fb, dict) and _cond_fb.get("minimax_keyframes"):
                        _kfs_fb = []
                        _kf_resized = 0
                        for _kf_fb in _cond_fb["minimax_keyframes"]:
                            _kl_fb = _kf_fb.get("latent")
                            if _kl_fb is not None and _kl_fb.ndim == 5 \
                                    and tuple(_kl_fb.shape[-2:]) != _fb_hw:
                                _kl_fb = torch.nn.functional.interpolate(
                                    _kl_fb,
                                    size=(int(_kl_fb.shape[2]), int(_fb_hw[0]), int(_fb_hw[1])),
                                    mode="trilinear", align_corners=False)
                                _kf_resized += 1
                            _nkf_fb = dict(_kf_fb)
                            _nkf_fb["latent"] = _kl_fb
                            _kfs_fb.append(_nkf_fb)
                        _cond_fb["minimax_keyframes"] = _kfs_fb
                        if _kf_resized:
                            print(f"[H3 Extender] v14.207 fallback: {_kf_resized} 个 keyframe "
                                  f"latent 已缩回一采 {int(_fb_hw[1])}x{int(_fb_hw[0])}"
                                  f"(原二采空间), 避免 cond 行数 4x 失配")
                except Exception as _fbk_e:
                    print(f"[H3 Extender] v14.207 fallback keyframe 几何对齐失败: {_fbk_e}")
            # v1.92: 仅当模型已被 ComfyUI 全卸(<2GB)时才卸载重载; 否则保持
            # 当前 staged 状态(DynamicVRAM 下卸载重载会 staged 21.36GB 二次 OOM).
            try:
                _fb_loaded_gb = model.loaded_size() / 1024 ** 3
            except Exception:
                _fb_loaded_gb = 0.0
            if _fb_loaded_gb < 2.0:
                try:
                    _ff_unregister_model(model, label="v1.92-fallback")
                    # v1.94: reserve 10->14GB, 强制更激进 offload 降 resident.
                    # 旧 10GB 时 resident 仍 14.5GB, tile forward 1.81GB 还是 OOM.
                    _mm.EXTRA_RESERVED_VRAM = int(14.0 * 1024 ** 3)
                    _mm.load_models_gpu([model])
                    print(f"[H3 Extender] v1.92 fallback: 模型已全卸({_fb_loaded_gb:.1f}GB), 重新驻留后重跑")
                except Exception:
                    pass
            _gc.collect()
            _torch.cuda.empty_cache()
            _r2_sigmas = _sigmas(_refine_model, "beta", _r_steps, _r_denoise)
            _r2_noise = comfy.sample.prepare_noise(_fb_use, int(seed) + 1, None)
            _r2_latent = _ff_const_add_noise(_refine_model, _r2_noise, _r2_sigmas, {"samples": _fb_use}, _r_audio)
            _r2_sampler = comfy.samplers.sampler_object(str(sampler_name))
            _r2_guider = _BasicGuider(_refine_model)
            _r2_guider.set_conds(conditioning)
            import comfy.sampler_helpers as _sh_fb
            _bsai_orig_prepare_fb = _sh_fb._prepare_sampling
            def _bsai_fb_prepare(model, noise_shape, conds, model_options=None, force_full_load=False, force_offload=False):
                try:
                    return model.model, conds, []
                except Exception:
                    return _bsai_orig_prepare_fb(model, noise_shape, conds, model_options=model_options,
                                                  force_full_load=force_full_load, force_offload=force_offload)
            _sh_fb._prepare_sampling = _bsai_fb_prepare
            try:
                with _aimdo_disabled():
                    _r2_samples = _r2_guider.sample(
                    _r2_noise,
                    _r2_latent["samples"],
                    _r2_sampler,
                    _r2_sigmas,
                    denoise_mask=_r2_latent.get("noise_mask"),
                    callback=_r_step_cb,
                    disable_pbar=not comfy.utils.PROGRESS_BAR_ENABLED,
                    seed=int(seed) + 1,
                )
                samples = _r2_samples.to(comfy.model_management.intermediate_device())
                _fb_label = "分块放大版" if _fb_use_tiles else ("原始备份" if _samples_pre_upscale is not None else "当前(放大后)")
                print(f"[H3 Extender] Refine fallback (v1.92 {_fb_label}) 完成: clip={clip_index}")
            except torch.cuda.OutOfMemoryError as _oom2:
                print(f"[H3 Extender] Refine fallback 仍 OOM: {_oom2}")
                # v14.206: 以前只打印"已回退到一采结果"却没有真的换回 samples,
                # 实际交付的是放大后未去噪的 latent(灰片)。这里补上真正的赋值。
                if _samples_pre_upscale is not None:
                    samples = _samples_pre_upscale
                    _refine_fallback_hw = _ff_video_hw(samples)
                    print(f"[H3 Extender] 已回退到一采 latent; 建议手动把 "
                          f"refine_upscale_factor 改成 1.0 重新跑")
            except Exception as _fb_err:
                # v14.207: fallback 自己抛非 OOM 异常(如 cond 行数/CUDA kernel 报错)时,
                # 旧代码会直接穿出 except-OOM 分支把整个 prompt 打死(实测 1.5 小时作业
                # 在 clip2 二采兜底里死于 shape mismatch)。兜底失败就不该再兜底,
                # 退回一采 latent 让成片先落地。用户取消(Interrupt)照常抛出。
                if type(_fb_err).__name__ == "InterruptProcessingException":
                    raise
                print(f"[H3 Extender] Refine fallback 失败(非 OOM): {_fb_err}")
                import traceback as _tb_fb
                _tb_fb.print_exc()
                if _samples_pre_upscale is not None:
                    samples = _samples_pre_upscale
                    _refine_fallback_hw = _ff_video_hw(samples)
                    print(f"[H3 Extender] 已回退到一采 latent (fallback 异常)")
            finally:
                # v1.65: 恢复 prepare_sampling, 防污染后续采样(下一 clip / 其它工作流)
                try:
                    _sh_fb._prepare_sampling = _bsai_orig_prepare_fb
                except Exception:
                    pass
                # v1.92: 恢复 fallback 安装的分块包装器
                if _fb_use_tiles and _r_restore_tiles is not None:
                    try:
                        _r_restore_tiles()
                    except Exception:
                        pass
        except Exception as _re:
            print(f"[H3 Extender] Refine 双采失败（回退主采样结果）: {_re}")
            import traceback
            traceback.print_exc()
            # v1.36 (2026-09-12 fix): 二采 OOM 兜底后, 用 unload_all_models()
            # 真把 diffusion/TE/VAE detach 掉, 避免 20GB VideoVAE 加载时
            # _decode_single_clip_to_blob 报 "loaded completely 20653MB"
            # 之后下一个 clip 又 OOM.
            try:
                import comfy.model_management as _mm
                import torch as _torch
                import gc as _gc
                _gc.collect()
                try:
                    # v2.120b (round3): 同 1942 崩溃链, unload_all_models() 对量化 DiT
                    # detach 时 .to(cpu) 原生崩溃; 改 for_dynamic=True 只卸非量化模型。
                    _mm.free_memory(1e30, _mm.get_torch_device(), for_dynamic=True)
                except Exception:
                    pass
                if _FF_UPSCALER_MOD is not None:
                    try:
                        _cache = getattr(_FF_UPSCALER_MOD, "MODEL_CACHE", None)
                        if isinstance(_cache, dict) and _cache:
                            for _k, _m in list(_cache.items()):
                                try:
                                    _m.to("cpu")
                                except Exception:
                                    pass
                                del _m
                                del _cache[_k]
                    except Exception:
                        pass
                _gc.collect()
                _mm.soft_empty_cache(force=True)
                _torch.cuda.synchronize()
                _torch.cuda.empty_cache()
                try:
                    _torch.cuda.ipc_collect()
                except Exception:
                    pass
                _torch.cuda.synchronize()
                _torch.cuda.empty_cache()
                _a = _torch.cuda.memory_allocated() / 1024 ** 3
                _f, _t = _torch.cuda.mem_get_info()
                print(f"[H3 Extender] Refine 失败后兜底释放(v1.36): allocated={_a:.2f}GB "
                      f"device_free={_f / 1024 ** 3:.2f}GB/{_t / 1024 ** 3:.2f}GB")
            except Exception as _ve2:
                print(f"[H3 Extender] Refine 失败后兜底释放失败(可忽略): {_ve2}")

    # v14.206 (2026-10-25): 二采 latent 塌陷兜底。
    # 实测(2026-10-25 灰片排查): 二采偶发把 latent 采样成近似常数场 —— 每通道空间
    # std 0.147、4x4 低通后 0.043, VAE 解码即灰雾/无画面; 健康 latent(一采 34x60)
    # 为 0.68~1.13。判据: 通道内空间离散度中位数 < 0.30 且 4x4 低通 < 0.15。
    # 命中且存在放大前一采备份时, 自动换回一采 latent(随后由 v1.74b 几何对齐到链上
    # 尺寸), 并推送告警, 避免再静默交付灰片。检测自身失败一律不打断渲染。
    try:
        _pre_up = _samples_pre_upscale
    except Exception:
        _pre_up = None
    if _pre_up is not None:
        try:
            _cm_v, _cm_nst = _ff_extract_members(samples)
            _cv = _cm_v[0] if _cm_v else None
            if _cv is not None and _cv.dim() == 5:
                _cv = _cv.detach().to("cpu", dtype=torch.float32)
                _ct = int(_cv.shape[2])
                if _ct > 8:
                    _cv = _cv[:, :, torch.linspace(0, _ct - 1, 8).long()]
                _cb, _cc, _ct, _ch, _cw = _cv.shape
                # 通道内空间离散度(每通道在 T/H/W 上的 std, 取中位数)
                _cdisp = float(_cv.reshape(_cb, _cc, -1).std(dim=2).median())
                # 4x4 低通后的离散度: 塌陷场只剩全局常量, 低通后几乎为 0
                _clp = torch.nn.functional.avg_pool2d(
                    _cv.permute(0, 2, 1, 3, 4).reshape(_cb * _ct, _cc, _ch, _cw),
                    4, ceil_mode=True)
                _clpdisp = float(
                    _clp.reshape(_clp.shape[0], _cc, -1).std(dim=2).median())
                # v14.260 (2026-10-30): 补「灰底 + 规则网格」漏网判据。
                # 分块二采(spatial 4 块)塌陷会产出均匀灰场 + 块状网格: 低频几乎全平
                # (低通 std 极低), 但网格把整体 std 抬到 0.30 以上, 上面那条 AND 判据
                # 因此漏网 → 灰片当"健康"直出。实测 clip[1]: 整体 0.472 / 低通 0.091;
                # 而命中回退的 clip[0] 是 0.293 / 0.115(低通反而更高)。
                # 独立触发: 低通极平 + 整体 std 低于注释记录的 0.68 健康下限 +
                # 能量几乎全在高频(整体 > 1.8×低通)。真·平滑场景三者不会同时成立。
                _grid_gray = (_clpdisp < 0.12 and _cdisp < 0.68
                              and _cdisp > 1.8 * _clpdisp)
                if (_cdisp < 0.30 and _clpdisp < 0.15) or _grid_gray:
                    _pre_v, _pre_nst = _ff_extract_members(_pre_up)
                    if _pre_v:
                        _pre_hw = tuple(_pre_v[0].shape[-2:])
                        samples = _ff_wrap_members(list(_pre_v), _pre_nst)
                        _refine_fallback_hw = (int(_pre_hw[0]), int(_pre_hw[1]))
                        print(f"[H3 Extender] ⚠ 二采 latent 塌陷"
                              f"({'网格灰场' if _grid_gray else '整体塌陷'}, clip={clip_index} "
                              f"通道内std={_cdisp:.3f}, 4x4低通std={_clpdisp:.3f}), "
                              f"已自动回退一采 latent {_pre_hw[1]}x{_pre_hw[0]}")
                        _send_extender_warning(
                            owner_id,
                            f"二采结果塌陷成灰片(通道内std={_cdisp:.3f})，"
                            f"已自动回退一采 latent；建议降低 refine_denoise / "
                            f"refine_steps，或关闭二采",
                            clip_index=clip_index,
                        )
                    else:
                        print(f"[H3 Extender] ⚠ 二采 latent 疑似塌陷(std={_cdisp:.3f}), "
                              f"但一采备份无效, 无法回退")
                else:
                    print(f"[H3 Extender] v14.206 二采 latent 健康: clip={clip_index} "
                          f"通道内std={_cdisp:.3f}, 4x4低通std={_clpdisp:.3f}")
        except Exception as _coll_err:
            print(f"[H3 Extender] 二采 latent 塌陷检测失败(可忽略): {_coll_err}")

    # v14.389 (2026-11-12): 二采内容闸门 —— 「重绘必须和一采内容一样」的落点。
    # 二采底图 = 一采放大后的 latent, 内容锁把起点 σ 压在 0.45~0.55(v14.393) —— 只补细节;
    # 但 denoise 再低也仍是重采样, 极端情况(换 seed 争用 / 分块相位不一致 / 模型对
    # 稀疏注意力栈过敏)仍可能整块滑到另一幅画面。这里做确定性判定:
    #   把二采结果与一采放大后的快照各做 4x4 低通(只比结构/构图, 不比细节纹理),
    #   逐通道算余弦相似度取均值; < _FF_REFINE_CONTENT_MIN(默认 0.85) 即判定
    #   「重绘成别的画面」, 整块丢弃回退到一采放大结果并告警。
    if _refine_base_snapshot is not None:
        try:
            _g_m, _g_n = _ff_extract_members(samples)
            _g_v = _g_m[0] if _g_m else None
            _g_base, _g_rest, _g_nst = _refine_base_snapshot
            if (_g_v is not None and _g_base is not None
                    and _g_v.dim() == 5 and _g_base.dim() == 5
                    and tuple(_g_v.shape) == tuple(_g_base.shape)):
                _g_a = _g_base  # 快照本来就是 CPU float32
                _g_b = _g_v.detach().to("cpu", dtype=torch.float32)
                _g_t = int(_g_a.shape[2])
                if _g_t > 8:
                    _g_idx = torch.linspace(0, _g_t - 1, 8).long()
                    _g_a = _g_a[:, :, _g_idx]
                    _g_b = _g_b[:, :, _g_idx]
                _g_ba, _g_ce, _g_ta, _g_ha, _g_wa = _g_a.shape
                _g_pa = torch.nn.functional.avg_pool2d(
                    _g_a.permute(0, 2, 1, 3, 4).reshape(_g_ba * _g_ta, _g_ce, _g_ha, _g_wa),
                    4, ceil_mode=True)
                _g_pb = torch.nn.functional.avg_pool2d(
                    _g_b.permute(0, 2, 1, 3, 4).reshape(_g_ba * _g_ta, _g_ce, _g_ha, _g_wa),
                    4, ceil_mode=True)
                _g_va = _g_pa.reshape(_g_pa.shape[0], _g_ce, -1)
                _g_vb = _g_pb.reshape(_g_pb.shape[0], _g_ce, -1)
                _g_cos = float(torch.nn.functional.cosine_similarity(
                    _g_va, _g_vb, dim=2).mean())
                if _g_cos < _FF_REFINE_CONTENT_MIN:
                    _g_back = _g_base.to(dtype=_g_v.dtype, device=_g_v.device)
                    samples = _ff_wrap_members([_g_back] + list(_g_rest), _g_nst)
                    _g_hw = tuple(_g_base.shape[-2:])
                    print(f"[H3 Extender] ⚠ v14.389 二采内容闸门: 结构相似度 "
                          f"{_g_cos:.3f} < {_FF_REFINE_CONTENT_MIN:.2f}, 判定重绘成别的画面, "
                          f"已丢弃二采结果回退一采放大 {_g_hw[1]}x{_g_hw[0]}(clip={clip_index})")
                    _send_extender_warning(
                        owner_id,
                        f"二采重绘偏离一采内容(结构相似度={_g_cos:.3f} < "
                        f"{_FF_REFINE_CONTENT_MIN:.2f})，已自动回退一采放大结果，"
                        f"本段按纯超分交付",
                        clip_index=clip_index,
                    )
                else:
                    print(f"[H3 Extender] v14.389 二采内容闸门: 结构相似度 {_g_cos:.3f} "
                          f">= {_FF_REFINE_CONTENT_MIN:.2f}, 二采与一采内容一致, 保留二采")
        except Exception as _g_err:
            print(f"[H3 Extender] v14.389 二采内容闸门失败(可忽略): {_g_err}")

    # v1.74b (2026-09-15 fix #10): 链几何对齐 —— 若链上已有段且本次 latent 几何不同
    # (per-clip 降级被拦截后仍可能 OOM fallback 到一采尺寸 / 异常路径),
    # bilinear 放大到链上几何, 保证 Disk Join 不断链。
    try:
        _cp74b, _cmp74b = _chain_paths(f"extender_{_safe_name(str(owner_id))}")
        _cm74b = _load_manifest_from_paths(_cp74b, _cmp74b)
        _cg74b = _cm74b.get("geometry") if _cm74b is not None else None
        if _cg74b is not None:
            _chh74b = int(_cg74b.get("video_h", 0))
            _chw74b = int(_cg74b.get("video_w", 0))
            if _chh74b > 0 and _chw74b > 0:
                _m74, _w74 = _ff_extract_members(samples)
                _v74 = _m74[0]
                _old_h74, _old_w74 = int(_v74.shape[-2]), int(_v74.shape[-1])
                if _old_h74 != _chh74b or _old_w74 != _chw74b:
                    import torch as _torch74
                    _v74 = _torch74.nn.functional.interpolate(
                        _v74, size=(int(_v74.shape[2]), _chh74b, _chw74b),
                        mode="trilinear", align_corners=False)
                    _m74[0] = _v74
                    samples = _ff_wrap_members(_m74, _w74)
                    print(f"[H3 Extender] v1.74b: latent 几何对齐到链上 "
                          f"{_chw74b}x{_chh74b} (原 {_old_w74}x{_old_h74})")
    except Exception as _ga74b:
        print(f"[H3 Extender] v1.74b 几何对齐失败(可忽略): {_ga74b}")

    out = latent_out.copy()
    out.pop("downscale_ratio_spacial", None)
    out.pop("downscale_ratio_temporal", None)
    out["samples"] = samples
    if _refine_fallback_hw:
        _fbh, _fbw = int(_refine_fallback_hw[0]), int(_refine_fallback_hw[1])
        if _fbh > 0 and _fbw > 0:
            # 解码时先缩回一采几何再像素放大(见 motion_context_disk._load_segment_video_native)
            out["decode_native_hw"] = [_fbh, _fbw]
            print(f"[H3 Extender] v14.250 二采已回退: 本段标记一采解码几何 "
                  f"{_fbw}x{_fbh} (避免插值 latent 直解码的马赛克条纹)")
    return out


def _normalize_color_adjustment(value=None):
    raw = value if isinstance(value, dict) else {}

    def _v(name, default=100.0, low=0.0, high=200.0):
        try:
            x = float(raw.get(name, default))
        except Exception:
            x = float(default)
        return max(float(low), min(float(high), x))

    return {
        "saturation": _v("saturation", 100.0, 0.0, 200.0),
        "contrast": _v("contrast", 100.0, 50.0, 150.0),
        "brightness": _v("brightness", 100.0, 50.0, 150.0),
    }


def _default_clip(index: int = 0):
    return {
        "id": f"clip_{index + 1}",
        "name": "",
        "prompt": "",
        "seed": int(secrets.randbelow(DEFAULT_SEED_MAX)),
        "seed_mode": "randomize",
        "duration": DEFAULT_DURATION,
        "validated": False,
        "context_enabled": True,
        "color_adjustment": _normalize_color_adjustment(),
    }


_DIALOGUE_AUDIO_LINE_RE = re.compile(
    r"^\s*(?:"
    r"【[^】]*(?:对白|台词|对话|旁白|音效|配音|配乐|voiceover|dialogue)[^】]*】"
    r"|\[[^\]\[]*(?:对白|台词|对话|旁白|音效|配音|配乐|voiceover|dialogue)[^\]\[]*\]"
    r"|[对白台词对话旁白音效配音配乐][：:]"
    r"|\([^)]*(?:对白|台词|对话|旁白|音效|配音|配乐)[^)]*\)"
    r"|（[^）]*(?:对白|台词|对话|旁白|音效|配音|配乐)[^）]*）"
    r")"
)
_ANCHOR_QUOTE_CHARS = '“”"「」『』‘’'


def _is_quote_dominated(seg):
    """句子中引号内对白内容占多数 → 纯对白句, 不参与视觉状态提取。"""
    try:
        _m = re.findall(
            r"[" + _ANCHOR_QUOTE_CHARS + r"]([^" + _ANCHOR_QUOTE_CHARS + r"]{0,80})[" + _ANCHOR_QUOTE_CHARS + r"]",
            seg,
        )
        _quoted = sum(len(x) for x in _m)
        return _quoted * 2 > len(seg)
    except Exception:
        return False


_VISUAL_ELEMENT_KEYWORDS = (
    # 角色形象/人物
    "人物", "角色", "主角", "男人", "女人", "男孩", "女孩", "少年", "少女", "老人",
    "男子", "女子", "女郎", "姑娘", "小伙", "演员", "歌手", "舞者", "士兵", "警察",
    "医生", "学生", "老师", "仆人", "士兵",
    # 外观/长相
    "面容", "脸庞", "脸色", "脸", "眼神", "眼睛", "眉毛", "鼻子", "嘴唇", "皮肤",
    "肤色", "皱纹", "胡须", "胡子", "雀斑", "妆容", "泪痕", "伤疤", "疤痕", "脸型",
    "面色", "苍白", "通红", "晒黑", "素颜", "浓妆", "淡妆",
    # 发型
    "头发", "发丝", "发髻", "刘海", "马尾", "辫子", "短发", "长发", "卷发", "直发",
    "发型", "白发", "黑发", "金发", "棕发", "盘发", "光头", "秃头",
    # 服装/服饰
    "服装", "衣着", "穿着", "衣服", "衣裳", "衣", "裙", "裤", "衫", "袍", "外套",
    "大衣", "夹克", "风衣", "毛衣", "衬衫", "T恤", "领带", "领结", "皮带", "腰带",
    "袖子", "袖口", "衣领", "领口", "制服", "校服", "礼服", "婚纱", "汉服", "旗袍",
    "背心", "睡衣", "披肩", "斗篷", "雨衣", "军装", "西装", "牛仔裤",
    # 鞋帽配饰
    "鞋", "靴", "袜", "帽", "头盔", "头巾", "围巾", "手套", "耳环", "项链", "戒指",
    "手镯", "眼镜", "口罩", "徽章", "胸针", "发卡", "发饰", "耳钉", "墨镜", "帽子",
    "腰带扣", "荷包", "香囊", "玉佩",
    # 伤势/状态变化（可见）
    "伤", "血", "绷带", "纱布", "疤", "淤青", "青紫", "肿", "破", "撕裂", "缝补",
    "补丁", "包扎", "擦伤", "伤口", "血迹", "流血", "渗血", "骨折", "断", "烧伤",
    "烫伤", "红肿",
    # 道具
    "道具", "刀", "剑", "枪", "伞", "油纸伞", "包", "袋", "杯", "瓶", "书", "手机",
    "相机", "乐器", "吉他", "琵琶", "小提琴", "钢琴", "麦克风", "话筒", "花", "灯笼",
    "蜡烛", "烛", "香烟", "酒瓶", "望远镜", "拐杖", "斧头", "绳索", "旗帜", "盾牌",
    "弓箭", "扇子", "折扇", "手帕", "钥匙", "信", "画卷",
    # 场景/布景
    "场景", "布景", "房间", "屋子", "客厅", "卧室", "厨房", "办公室", "教室", "街道",
    "马路", "巷", "广场", "公园", "森林", "树林", "山", "河", "海", "湖", "沙漠",
    "雪地", "草地", "田野", "桥", "阶梯", "台阶", "窗", "门", "墙", "桌", "椅",
    "床", "沙发", "柜", "窗帘", "地毯", "壁炉", "招牌", "路灯", "霓虹", "亭子",
    "楼", "塔", "寺庙", "教堂", "宫殿", "车站", "码头", "集市", "瀑布", "悬崖",
    "山洞", "稻田", "竹林", "花丛", "草地",
    # 天候/光影（可见）
    "光", "影", "暗", "明亮", "黄昏", "夜晚", "白天", "傍晚", "夕阳", "月光", "日光",
    "阳光", "雨", "雪", "雾", "烟", "云", "天空", "水面", "倒影", "反光", "剪影",
    "色调", "颜色", "色彩", "灰暗", "阴沉", "晨曦", "破晓", "彩虹",
)

# 可见视觉元素关键词的补充: 常用量词/方位 + 元素词组合过于发散, 这里仅做
# 优先级判定: 命中任一关键词的句子视为"含可见视觉元素", 预算紧张时优先保留,
# 保证角色形象/外观/服装/服饰/发型/鞋帽/场景/道具/布景等所有可见元素都被记录。


def _is_visual_element_sentence(seg):
    """句子是否包含可见视觉元素关键词（用于预算紧张时优先保留）。"""
    try:
        return any(_k in seg for _k in _VISUAL_ELEMENT_KEYWORDS)
    except Exception:
        return False


def _extract_visual_state(text, max_len=300):
    """v14.193 自动记录: 从分镜正文提取『全部可见视觉元素』状态。

    视觉锚点自动化的记录侧 —— 每个分镜的正文本身就是该分镜建立的视觉状态。
    按用户确认口径（v14.193），必须覆盖**所有可见视觉元素**：角色形象、外观、
    服装、服饰、发型、鞋帽、伤势、场景、道具、布景、天候光影等，全部记录为
    锚点，而不是只取末尾句子。

    策略：逐句保留所有非对白陈述句（对白/台词/旁白/音效是声音不是画面, 不参与
    锚点），保持原序；正文总长在预算（默认 300 字符）内时全量保留（分镜正文
    通常 <300 字符，即默认覆盖全部可见元素）；超预算时优先保留含可见视觉元素
    关键词的句子（_VISUAL_ELEMENT_KEYWORDS），再按原序补足其余句子，确保元素
    不因截断而丢失。

    返回清洗后的状态文本; 无可提取内容时返回 None。
    """
    try:
        if not text or not str(text).strip():
            return None
        raw = []
        for _ln in str(text).splitlines():
            _ln = _ln.strip()
            # 行级先做引号对白判定: 引号内的 。！？ 会把整行切成无配对引号的
            # 碎片, 若先切句再判引号会漏检纯对白行(如 『“快走！别管我！”』)。
            if not _ln or _DIALOGUE_AUDIO_LINE_RE.match(_ln) or _is_quote_dominated(_ln):
                continue
            for _seg in re.split(r"(?<=[。！？!?；;])", _ln):
                _seg = _seg.strip()
                if not _seg or _is_quote_dominated(_seg):
                    continue
                raw.append(_seg)
        if not raw:
            return None
        if sum(len(s) for s in raw) <= max_len:
            chosen = raw
        else:
            _vis = [s for s in raw if _is_visual_element_sentence(s)]
            _idx = {s: i for i, s in enumerate(raw)}
            chosen = []
            _used = 0
            for _s in _vis:  # 含可见元素的句子优先保底
                if _used + len(_s) <= max_len:
                    chosen.append(_s)
                    _used += len(_s)
            for _s in raw:  # 其余句子按原序补足剩余预算
                if _s in chosen:
                    continue
                if _used + len(_s) <= max_len:
                    chosen.append(_s)
                    _used += len(_s)
            chosen.sort(key=lambda _s: _idx[_s])  # 恢复原序
        state = re.sub(r"\s+", " ", "".join(chosen)).strip(" 　,，、;；:：")
        return state or None
    except Exception as _va_err:
        print(f"[H3 Extender] v14.193 视觉锚点自动记录解析失败(本次跳过): {_va_err}")
        return None


def _build_visual_anchor_snapshot(states, clip_index, max_total=1000):
    """v14.193 (2026-10-24): 视觉锚点自动注入 —— 为指定 CLIP 生成状态快照注入文本。

    参考 B站《MiniMax-H3 一键短剧导演台 V9》(BV1m2HK6DEPX) 的视觉锚点机制：
    多段连续剧情中，道具/场景/人物外观状态必须随剧情演进且持续延续，禁止漂移
    （如分镜3左臂受伤袖口破 → 后续各分镜必须保持受伤状态；分镜6医好/缝补 →
    后续保持新状态；绑纱布则延续纱布；缝补不同颜色布则延续该补丁布）。

    与 v14.186 的区别: 不再读取用户手写的『分镜N: 状态声明』文本（该手动输入
    widget 已移除，也不新增任何输入端口），改为自动记录 —— states 为与 clips
    对齐的列表（每项 = _extract_visual_state 从该分镜正文提取的全部可见视觉元素
    状态，或 None），本函数注入 clip_index 之前的**全部已建立状态**（自旧到新；
    总长超预算 max_total 时从最旧开始丢弃，最新状态最相关），确保每个分镜都
    携带此前全部可见视觉元素锚点。

    返回：为 clip_index（0-based）构造的注入文本；无有效状态时返回 None。
    """
    try:
        if not states:
            return None
        active = [(n, s) for n, s in enumerate(states[:clip_index], start=1) if s]
        if not active:
            return None
        keep = []
        _used = 0
        for _n, _s in reversed(active):  # 从最新往最旧装, 超预算丢最旧
            _cost = len(_s) + 14  # "自分镜N起: " 前缀开销
            if _used + _cost > max_total and keep:
                break
            keep.append((_n, _s))
            _used += _cost
        keep = keep[::-1]
        parts = [f"自分镜{n}起: {s}" for n, s in keep]
        snapshot = "；".join(parts)
        return (
            "\n[视觉锚点延续] 本段必须严格延续此前分镜已建立的视觉状态："
            + snapshot
            + "。禁止改变任何已建立的角色形象、外观、服装、服饰、发型、鞋帽、"
            "场景、道具、布景与伤势状态，除非本段正文明确声明了新的状态变化"
            "（如伤势治愈/包扎/缝补/换装等）；本段若声明新状态，则自本段起该"
            "新状态成为后续所有分镜的视觉锚点并强制延续，后续分镜不得回到旧状态。"
        )
    except Exception as _va_err:
        print(f"[H3 Extender] v14.193 视觉锚点注入失败(本次跳过注入): {_va_err}")
        return None


# ── v14.271 一镜到底: 分拍式剧本 → 单镜头连续散文 ─────────────────────────
# H3 的时序先验: 提示词按 "0-3秒：/3-6秒：/6-9秒：" 分拍写运镜时, 模型把每个分拍
# 当成一个独立镜头, 在拍点处自己硬切(实测 v004 clip2 第 78 帧 = 3.25s ≈ 3-6 秒拍点,
# ffmpeg scene>0.12 检出的硬切)。一镜到底模式在编码前必须把分拍标签改写成先后
# 连接词, 整段读成一气呵成的散文, 才能避开"拍点=镜头边界"的先验。
#
# 同时按社区 PROMPTING.md 的结论(CFG=1.0 无负向分支, 否定句会被当作画面内容渲染):
# 这里只做正向改写 —— 把"镜头切换到"改成"镜头继续移向", 并抹掉用户自撰的
# "不切镜/不转场"口号, 不注入任何 cut/dissolve/转场/叠化 词汇。
_OS_SEG_TIME_RE = re.compile(
    r"(?:【|\[|（|\()?\s*(?:第\s*)?\d{1,3}(?:\.\d+)?\s*(?:秒|s|S)?\s*"
    r"(?:至|到|~|～|—|–|-)\s*\d{1,3}(?:\.\d+)?\s*(?:秒|s|S|seconds?|sec)\s*"
    r"(?:】|\]|）|\))?(?:\s*[：:,，])?"
)
_OS_AT_TIME_RE = re.compile(r"(?:At|at)\s*\d{1,2}:\d{2}(?:[.,]\d{1,3})?\s*", re.IGNORECASE)
_OS_ATTR_TAG_RE = re.compile(
    r"(?:【|\[)\s*(?:镜头运动|运镜|景别(?:/构图)?|构图|光影(?:氛围)?|角色状态|道具交互|画面内容)\s*(?:】|\])"
)
# v14.297: 连接词原本是**时间顺序词**(随后/接着/继而)。时间标签虽然被 flatten
# 删掉了, 但 4 个分句还在 —— H3 把它们当成 4 个"节拍"均匀铺到 12 秒(每句约 3 秒),
# 在分句交界处换状态 → 密集硬切(实测 28 处切镜里 17 处(61%)落在拍边界±12帧内,
# 随机期望只有 8%)。改成**运动延续词**: 不再给"下一个节拍"的暗示, 直接说清
# "同一次连续运动"。
# v14.298: 段标题里的**人声状态标记**整块剔除。
# 段标题形如 "：霓虹小店长街@图6-无声穿行(【不唱】·全镜无人声)(【本段运镜：…】)"。
# v14.286 已为 【转场】 立过同样的规矩 —— H3 只认字面, 标签写什么就往画面里画什么;
# 而 "不唱" 里的"不"是否定词, H3 在 CFG=1.0 下没有负向分支 -> 会张嘴唱歌, 可这几段
# 根本没有音频(lip_audio 缺失, 脚本写的是"全镜无人声")。
# "人声0:00.2起 / 人声至1:32.1" 是**全片**时间码, 放进 12 秒的镜头提示词里只会给
# 模型一个错的时序锚点。插件不解析人声时间码(音频来自 lip_audio 输入), 整块删掉
# 不影响任何功能。
_OS_VOCAL_PAREN_RE = re.compile(
    r"[（(]\s*(?:[【\[]\s*)?(?:演唱中|不唱|转场|无人声|人声)[^）)]{0,40}[）)]"
)
_OS_VOCAL_TAG_RE = re.compile(r"[【\[]\s*(?:演唱中|不唱)\s*[】\]]")


def _one_shot_strip_vocal_tags(text):
    """v14.298: 剔除段标题里的人声状态标记(人声状态由 lip_audio 决定)。"""
    s = str(text or "")
    if not s:
        return s
    out = _OS_VOCAL_PAREN_RE.sub("", s)
    out = _OS_VOCAL_TAG_RE.sub("", out)
    return out


_OS_SEG_CONNECTIVE = ("沿着同一条轨迹连贯地推进，", "在同一次连续运动里，",
                      "顺着这条轨迹连贯地继续，", "在这次连续运动的收尾处，",
                      "到这次连续运动的末帧，")


# ── v14.300 (2026-11-03): 残留「切换」正向化 + 正文全片绝对时间码剥离 ──────
#
# 实测证据(v14.289 运行实例, 19 段逐段像素域审计 + 离线条件文本复核):
#   * 脚本里 5 处「切换」**全部**落在有段内硬切/叠化的段上:
#       段4  「胸前挂绳在明暗切换中忽隐忽现」              (段4 f118-f126 叠化)
#       段7  「出棚瞬间脚步声的质感切换」                  (段7 8 处硬切)
#       段10 「每经过一盏即在沈砚@图1身上形成一次明暗切换」 (段10 f12 叠化)
#       段11 「左耳银色耳钉在每次明暗切换中改变亮度」      (段11 f126 硬切)
#       段13 「脚步由石砖转为卵石的质感切换」              (段13 26 处硬切)
#     「切换」是切镜族词 —— H3 只认字面, "明暗切换"会被读成"画面切换"。
#     v14.271 只清了**否定式**切镜口号, 没清**正面陈述**里的"切换"。
#   * 正文里的全片绝对时间码(段11: "在2:04.6人声入唱处双唇开启")是**全片**时间,
#     而段11 自己只有 12 秒 —— 给模型一个错的时序锚点。v14.298 只清了段标题。
#
# 修法: 语义等价的正向改写, 不动用户脚本原文。
_OS_SWITCH_PAIRS = (
    ("明暗切换", "明暗交替"),
    ("暗亮切换", "暗亮交替"),
    ("光暗切换", "光暗交替"),
    ("明暗转换", "明暗交替"),
    ("镜头切换", "镜头继续移向"),
)
# 绝对时间码: 只在紧邻人声/声音类词时删(M:SS.s), 普通数字一律不动。
_OS_VOICE_TC_FWD = re.compile(
    r"\d{1,3}:\d{2}(?:\.\d+)?(?=\s*(?:人声|歌声|音频|音乐|演唱|唱))")
_OS_VOICE_TC_AFTER = re.compile(
    r"((?:人声|歌声|音频|音乐|演唱)\s*(?:至|起|到)?\s*)(\d{1,3}:\d{2}(?:\.\d+)?)")
_OS_VOICE_TC_TAIL = re.compile(
    r"(?:人声|歌声|音频|音乐|演唱)\s*(?:至|起|到)\s*(?=[，,；;。！？!?\n]|$)")


def _one_shot_sanitize_cut_words(text):
    """v14.300: 一镜到底条件下文本的最后一层清洗。

    1) **正面陈述**里的「切换」(明暗切换 / 质感切换) 改写成不含切镜词的同义表述;
    2) 正文里紧邻人声词的全片绝对时间码(M:SS.s) 剥掉。
    """
    s = str(text or "")
    if not s:
        return s
    for _a, _b in _OS_SWITCH_PAIRS:
        s = s.replace(_a, _b)
    if "切换" in s:
        s = s.replace("切换", "变化")
    s = _OS_VOICE_TC_FWD.sub("", s)
    s = _OS_VOICE_TC_AFTER.sub(r"\1", s)
    s = _OS_VOICE_TC_TAIL.sub("", s)
    s = re.sub(r"[，,；;]{2,}", "，", s)
    return s


# 切镜词汇。一镜到底的提示词里只要出现(不论是否定句), 都会被 H3 当成画面内容。
_OS_CUT_VOCAB = ("剪切", "切镜", "切场", "转场", "跳帧", "闪白", "画面切换", "切换机位",
                 "叠化", "淡入", "淡出", "硬切")
_OS_NEG_WORD_RE = re.compile(r"不|无|没有|禁止|绝不|严禁|不要|不得|避免")
_OS_FRAG_RE = re.compile(r"[^，,；;。！？!?\n]*[，,；;。！？!?\n]?")


def _strip_negated_cuts(text):
    """v14.271: 逐分句删除"否定词 + 切镜词汇"的指令。

    H3 在 CFG=1.0 下没有负向分支, "画面中不出现任何剪切点、转场、跳帧、闪白"
    这类否定句会被当成画面内容渲染(社区 PROMPTING.md 结论), 实测反而诱发段内
    切镜。一镜到底模式下这些分句一律不进入条件文本。
    """
    _out = []
    for _ln in str(text or "").splitlines():
        _keep = []
        for _f in _OS_FRAG_RE.findall(_ln):
            _core = _f.strip(" \t，,；;。！？!?\n")
            if _core and _OS_NEG_WORD_RE.search(_core):
                if any(_w in _core for _w in _OS_CUT_VOCAB):
                    continue
            _keep.append(_f)
        _out.append("".join(_keep).rstrip())
    return "\n".join(_out).strip()

# 景别词表 + 英文映射。顺序只用于构造, 选取时按字面首次出现位置(见下)。
_OS_SIZE_WORDS = (
    ("大特写", "EXTREME CLOSE-UP"),
    ("特写", "CLOSE-UP"),
    ("中近景", "MEDIUM CLOSE SHOT"),
    ("近景", "CLOSE SHOT"),
    ("中全景", "MEDIUM WIDE SHOT"),
    ("中景", "MEDIUM SHOT"),
    ("全景", "WIDE SHOT"),
    # v14.286: 补 "大远景" —— 词表原本缺这条, 脚本里的 "大远景" 会被最长匹配
    # 拆成 "远景", 景别链判定因此误报跨档跳变(段19 实测 中全景→远景 跨 3 档)。
    ("大远景", "EXTREME WIDE SHOT"),
    ("远景", "EXTREME WIDE SHOT"),
)


def _one_shot_flatten_prompt(text):
    """v14.271: 一镜到底模式下把分拍式提示词改写为单镜头连续散文。

    - 时间区间标签(0-3秒 / [0-3s] / At 00:03.000 / [Shot N]) → 先后连接词或直接删除
    - 属性方括号([镜头运动]/[景别/构图]/...) → 删除, 让各拍从句连成一段
    - 切镜动词(镜头切换至 / the camera cuts to) → 连续运镜动词
    - 用户自撰的"不切镜/不切场/不转场/无转场"口号 → 删除(否定句会被渲染)

    无任何可改写内容时原样返回。
    """
    s = str(text or "")
    if not s.strip():
        return s
    s = _OS_AT_TIME_RE.sub("", s)
    s = _OS_ATTR_TAG_RE.sub("", s)
    s = _strip_negated_cuts(s)
    for _w in ("不切镜", "不切场", "不转场", "无转场", "禁止切镜", "禁止转场"):
        s = s.replace(_w, "")
    s = (s.replace("镜头切换至", "镜头继续移向").replace("镜头切换到", "镜头继续移向")
          .replace("切换至", "继续移向").replace("切换到", "继续移向")
          .replace("硬切至", "连续移向").replace("硬切到", "连续移向"))
    s = re.sub(r"the\s+camera\s+cuts?\s+to\s+", "the camera continues to ", s, flags=re.IGNORECASE)
    s = re.sub(r"\bcut\s+to\s+", "move to ", s, flags=re.IGNORECASE)

    _parts = []
    _last = 0
    _n = 0
    for _m in _OS_SEG_TIME_RE.finditer(s):
        _between = s[_last:_m.start()]
        if "[分镜" in _between or "[Shot" in _between:
            _n = 0  # 新分镜重新计数, 否则全局提示词从第二个分镜起全是"最后"
        _parts.append(_between)
        if _n:
            _parts.append(_OS_SEG_CONNECTIVE[min(_n - 1, len(_OS_SEG_CONNECTIVE) - 1)])
        _n += 1
        _last = _m.end()
    _parts.append(s[_last:])
    s = re.sub(r"[ \t]{2,}", " ", "".join(_parts)).strip()
    # v14.300: 最后一层清洗(残留"切换"正向化 + 正文全片绝对时间码)
    s = _one_shot_sanitize_cut_words(s)
    return s


# v14.375 (2026-11-11): 一镜到底正文的「机位方向句」必须中和 —— 根因与 v14.347 同一对,
# 但这次落在**脚本正文**而不是规则里:
#   正文原句 =「镜头与主播@图1始终在同一条向前行进的连续弧线轨迹上, 同速同向、正对主播
#   @图1的正面, 沿其行进方向平稳前移并随拐点微摆」+「机身以连续无级的方式改变拍摄距离,
#   前段匀速推近至中景…」
#   ① 机位沿行进方向前移 ② 正对正面对镜头 ③ 又推近 —— 三条并置, 几何上互相矛盾;
#   模型只能在画幅里让主体「往后甩腿」同时满足「朝镜头 + 机位在前进」。
# v14.376 (2026-11-11): v14.375 把机位改成「与主播同距同速、随其位移同步移动」, 仍然是
#   **机位跟着人在走**, 配上规则里「画幅以他为锚 / 双脚踩在同一片地面」= 主体在画幅里钉死,
#   模型依旧只能让双腿原地倒腾(用户 11:29 那片重渲后判定"从头到尾全是倒着走")。
#   v14.376 统一口径: **机位与机身固定在同一处地面位置上不动, 只做连续变距**; 位移全部由
#   「主播朝镜头走近、画幅里逐秒由小到大」承担。这样"地面不动 + 人在画幅里变大"在物理上
#   只有在正走时才成立, 倒走会立刻自相矛盾。
# v14.378 (2026-11-11): 上面 v14.376 的「机位钉在一处地面位置」, 与本插件自己的
#   [取景连续]（extender.py 内「摄影机沿同一条轨迹与他同速同行、同距同高，主体在画幅中的
#   占画比例自始至终稳定」）硬自相矛盾。模型二选一, 实测新片 h3_clip_250_1_1794384070:
#   地面分区中位 dy 仅 +0.04~0.06px/帧(地面纹丝不动), 占画高 0.187→0.709 全靠"变大",
#   双腿原地不动 —— 就是用户说的"从头到尾倒着走/滑行"。
#   另外"运行时改写用户脚本正文"本身违背用户口径(脚本正文不可改)。本版整张改写表清空:
#   脚本原句(同一条轨迹、同速同向、正对正面)与 [取景连续] 一致, 前进凭据只在规则层
#   钉到地面上(石缝与柱列一道接一道后流过画幅下缘)。函数保留, 改写表为空 = 恒等返回。
_OS_CAM_DIR_REWRITES = ()


def _one_shot_neutralize_camera_dir(text):
    """v14.375: 中和正文里的机位方向句(纯文本改写, 不动用户工作流/脚本源文件)。"""
    if not text:
        return text
    out = text
    for _a, _b in _OS_CAM_DIR_REWRITES:
        out = out.replace(_a, _b)
    return out


def _one_shot_first_size(text):
    """v14.271: 返回提示词正文中最先出现的景别词 (词, 英文名); 无则 (None, "")。

    按字面首次出现位置选取, 而不是按景别尺度排序 —— 尺度顺序会把参考图纪律或
    全局提示词里的"特写"当成全段基准(v14.241 在实机上恒定输出"基准景别=特写")。
    """
    low = str(text or "").lower()
    _best = (None, "")
    _best_pos = None
    for _w, _en in _OS_SIZE_WORDS:
        _p = low.find(_w)
        if _p < 0:
            continue
        if _best_pos is None or _p < _best_pos:
            _best, _best_pos = (_w, _en), _p
    return _best


def _one_shot_size_chain(text):
    """v14.286: 返回 (起始景别, 结束景别, 命中列表, 是否可靠)。

    景别来源按优先级:
      1. 新格式拍段字段 "[景别/构图]中全景…"
      2. 老格式拍段行 "0-3秒：…运镜（…）、中全景。…" —— 景别在括号之后的顿号后
      3. 全文最长匹配扫描(兜底, **不可靠**: 分不清哪个景别词属于哪个拍段)

    为什么不能只看全文首个景别词: 段标题的【本段运镜: …缓缓上升至大远景】说的是
    **本段的目标**, 不是起幅景别。段19 实测: 标题写"至大远景", 但 0-3 秒拍段是
    "中全景低机位侧后方"(承接上一段末帧) —— 按全文首词取会凭空造出一次
    中全景→大远景 的跨档跳变。

    扫描一律**最长匹配优先**, 所以 "中全景" 不会被拆成 "全景"、"大远景" 不会被
    拆成 "远景"。命中列表元素为 (序号, 景别词, 英文名)。
    """
    s = str(text or "")

    def _scan(seg):
        out = []
        i = 0
        n = len(seg)
        while i < n:
            hit = None
            for _w, _en in _OS_SIZE_WORDS:
                if seg.startswith(_w, i):
                    hit = (_w, _en)
                    break
            if hit:
                out.append(hit)
                i += len(hit[0])
            else:
                i += 1
        return out

    def _pick(frag):
        _h = _scan(frag)
        return (_h[0][0], _h[0][1]) if _h else None

    # ── 1. 新格式: [景别/构图] ──
    hits = []
    for _idx, _seg in enumerate(re.findall(r"\[\s*景别\s*/\s*构图\s*\]\s*([^；;。\n]{0,60})", s)):
        _p = _pick(_seg)
        if _p:
            hits.append((_idx, _p[0], _p[1]))
    if hits:
        return hits[0][1], hits[-1][1], hits, True

    # ── 2. 老格式: 拍段行 "…）、<景别>。" ──
    hits = []
    for _idx, _ln in enumerate(s.splitlines()):
        if not re.match(r"^\s*[\d\u2013\u2014\-~]+\s*秒", _ln):
            continue
        _seg = re.sub(r"[（(][^）)]*[）)]", "", _ln)      # 去括号(运镜描述里的景别词不算)
        _m = re.search(r"[、]\s*([^\n。；;、，]{1,10})。", _seg)
        if not _m:
            continue
        _p = _pick(_m.group(1))
        if _p:
            hits.append((_idx, _p[0], _p[1]))
    if hits:
        return hits[0][1], hits[-1][1], hits, True

    # ── 3. 兜底: 全文扫描(不可靠) ──
    _all = _scan(s)
    hits = [(_i, _w, _en) for _i, (_w, _en) in enumerate(_all)]
    if not hits:
        return None, None, [], False
    return hits[0][1], hits[-1][1], hits, False


def _one_shot_force_size(text, target):
    """v14.286: 把 text 里所有景别词替换成 target(最长匹配优先)。

    只在用户**显式声明**全片景别时使用 —— 声明了就以声明为准, 正文里冲突的
    景别词必须同步改写, 否则"正文写中景 + 锁定指令写中全景"会让模型左右为难。
    """
    s = str(text or "")
    if not target or not s:
        return s
    out = []
    i = 0
    n = len(s)
    while i < n:
        hit = None
        for _w, _en in _OS_SIZE_WORDS:
            if s.startswith(_w, i):
                hit = _w
                break
        if hit:
            out.append(target)
            i += len(hit)
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


# ── v14.292 (2026-11-03): 取景锚定 + 光影与构图分离 ─────────────────────
#
# 实测证据(用户 19 段一镜到底 MV 的前 4 段, v14.289 运行实例, 1920x1088):
#   clip1 段内 0 处切镜;
#   clip2 f160 = 8.10x 中位数 —— 由"中近景(胸像)"**硬切**到"大远景剪影";
#   clip3 f13  = 4.66x —— 由"栈桥木栈道"硬切到"混凝土海堤"(环境整个换掉);
#          f210 = 6.70x —— 由"极端躯干特写(头都在画外)"硬切回"桥上中景"。
#   接缝全部通: c1->c2 = 1.37x, c2->c3 = 1.11x(v14.287 基线是 15.36x / 1.55x)。
#
# 三处切镜是**同一形态**: 模型先渐进漂离脚本给的景别/环境, 漂到脚本没写的状态,
# 然后用一帧硬切纠偏。原因有二:
#   ① 现有规则只说了"景别随摄影机连续变化"(没给边界), 于是段3 脚本写"下降回
#      平视并推近", 模型一路推过头到躯干特写, 9 秒后才硬切回来;
#   ② 段2 第3拍"背后靛蓝天幕渐透出第一颗星点, 发梢成为剪影边"被模型读成
#      "要一个剪影构图" —— 为容纳天空把取景从中近景拉到大远景 -> f160 硬切。
#      现有规则没有声明"光影描述只改光", 模型就有权借光线重排构图。
#
# 两条新规则(纯正向, 不含切镜词汇, 不含否定句; H3 在 CFG=1.0 下没有负向分支):
#   [光影与构图分离] 光影描述只改变明暗与色彩, 取景由摄影机运动决定。
#   [取景锚定]     取景范围以脚本自己给的景别为准, 推近/拉远不越出这个范围。
#
# 两条都可关(便于 A/B): BSAI_H3_LIGHT_COMPOSITION=0 / BSAI_H3_SIZE_ANCHOR=0
_OS_LIGHT_COMPOSITION_RULE = (
    "\n[光影与构图分离] 本段每一拍的光线与色调只推进一小步并逐拍连续过渡：主光方向、"
    "色温与亮度平滑偏移，新出现的发光元素在画面里由暗到亮逐渐显形，人物身上的受光"
    "随所在位置自然改变；这些光影变化只改变画面的明暗与色彩，主体在画幅中的位置与"
    "大小由摄影机的运动连续决定。"
)


# ── v14.294 (2026-11-03): 空间延续 / 空间过渡 ─────────────────────────
#
# 根因(用户 19 段一镜到底 MV, 2026-11-03 实测):
#   * clip3 f13 一帧硬切 —— 段2 末帧已是"靛蓝天幕+第一颗星点"的夜景, 而段3 拍1/拍2
#     的光影条款写的是"残晖"(橙金夕阳), 两段的光线时间线**自己往回跳**。模型为了
#     让条件文本成立, 在段内 0.5s 处一帧硬切到夕照石阶(实测 f6-f16 仍是上一段的
#     木栈桥夜景, f18 起变成夕照石阶)。
#   * clip4 f118-f126 叠化 —— 段3 的木栈桥与段4 的公路路口双曝光。
#   * 共同根因 = **条件文本与段首 motion context 关键帧冲突**: 关键帧钉住上一段
#     末帧的画面, 正文要求的却是另一处空间/另一种光, 模型只能二选一 —— 先拖着旧
#     画面再硬切, 或者把两处叠在一起。
#
# 修法(纯文本层, 不动用户脚本):
#   [同场景延续] 本段与上一段是同一处空间 -> 布局与光线都从上一段末帧延续, 逐拍
#                 只推进一小步(压住 clip3 的光线倒流与左右镜像)。
#   [空间过渡]   本段换到另一处空间 -> 明确"走过去"而不是叠化, 两处空间由同一条
#                 地面相连, 方位自始至终一致。
#
# 措辞纪律: 全文纯正向陈述; 不含任何 cut/转场/叠化/剪切/跳帧/闪白 等切镜词汇;
# 不含否定句(H3 在 CFG=1.0 下没有负向分支)。方位/距离/景别/动作仍全部交给用户脚本。
#
# v14.295 追加: 两条规则都加「展开之后就一直展开着, 本段后续的画面都处在这一处
# 已经展开的空间里」—— 实测段6/段7 的失败形态是模型在「上下文关键帧里的旧场景」
# 与「本段正文要求的新场景」之间**来回横跳**(乒乓), 单次换场规则压不住。
# 开关: BSAI_H3_SPACE_RULE=0 可关(便于 A/B)。
# ── v14.301 (2026-11-04): 换场段的空间锚定 ───────────────────────────────
#
# 实测证据(用户 2026-11-04 反馈 + 像素域审计 + 抽帧):
#   * 段4 是换场段(@图3 滨海堤岸 -> @图4 滨海公路路口)。
#   * 段4 正文**第 1 拍**就写"前方钠灯序列""湿润沥青路面", 但实际渲出来的前
#     5.7 秒全是**段3 的木栈桥 + 路灯**; f138 一帧硬切成沥青公路 + 警示牌 +
#     中全景 —— 场景与景别**同时**跳变。
#   * 接缝像素差只有 1.57x, 因为段4 开头**重复**了段3 的画面。
#   * 机制: [One Continuous Take] 写着"主体始终处在同一片连续空间里"(与换场冲突);
#     [段首承接] 把段4 第一帧钉死在段3 的构图上并给了"慢慢展开"的许可;
#     [空间过渡] 说"上一处空间的尽头还留在画面里"却**没给时间边界**。
# ── v14.320 (2026-11-05): 空间过渡段的「逐渐展开」→ 硬切式正向约束 ──────
#
# 实测证据(用户 2026-11-05 反馈 + CHANGELOG 历史审计):
#   * clip4 f118-f126 (4.9s) = 木栈桥与公路路口**双曝光**叠化 —— 两个空间同时出现。
#   * clip5 段头淡入淡出 —— 旧空间淡出、新空间淡入, 中间有 2-3 帧双重曝光。
#   * 共同根因: _OS_SPACE_TRANSIT_RULE 里写着「两侧的景物顺着前进的方向连续地换成
#     这一处的景物」+「这一处空间的景物从上一处空间的尽头逐渐展开在画面里」——
#     H3 把「连续地换成」「逐渐展开」理解成了叠化/淡入淡出的视觉效果, 渲染成双重
#     曝光。后面的「场景锚定」说「一旦出现就留住」, 但优先级不如前面的「逐渐展开」。
#
# 修法(纯文本层, 不动用户脚本, 同场景延续段不受影响):
#   删掉「连续地换成」「逐渐展开」, 插入正向硬约束:
#   「主体向前行走的同时就进入了新的空间, 画面里始终只有主体当下所处的那一处
#    空间的景物, 两处空间之间由主体的行走动作完成切换」
#   不用否定句(H3 CFG=1.0 不认), 用正向"始终只有"替代"不同时出现"。
# 同时改 HEAD_RULE 里的「脚下的路面与两侧景物在前进中连续地流过」为
#   「走过的景物留在画框后方, 前方的景物随步伐自然进入」—— 避免"流过"的渐变歧义。
# ── v14.332 (2026-11-07): 换场段把"换场"压进段首一瞬, 且由门墙遮挡完成 ────────
#
# 实测证据(用户 19 段一镜到底 MV, clip5 h3_clip_250_5_1794036207.mp4):
#   * 段内 scene 检测全片只有一处突变: pts 1.541667s, scene_score=0.2546;
#     抽帧(1.05/1.22/1.38s vs 1.55/1.72/1.88s)证实是**整幅背景替换**:
#     夜景街道(路灯/店铺/柏油路面) → 哥特尖拱石廊内景(拱门/石柱/地毯/吊灯),
#     人物胸像构图几乎不动 —— 即"门洞两侧"被模型做成了硬切, 而不是跨过。
#   * 旧文本自相矛盾: 第二句写"本段的第一拍起, 画面里的空间就已经是这一处空间",
#     第四句又写"上一处空间在开头的一瞬位于画幅边缘, 随主体向前走出画幅"。
#     H3 同时满足两句的办法只有一个: 段首先给 1.4s 旧空间, 再用一帧换掉整幅背景。
#   * 旧 HEAD_RULE 又要求"第一帧直接接着上一段末帧", 等于把第一帧钉死在**旧空间**
#     的画面上, 换场于是被推迟到段中 —— 段内硬切的位置就是这么来的。
#
# 修法(纯文本层, 不动用户脚本; 同场景延续段完全不受影响):
#   1) HEAD_RULE 改成"第一帧就是主体正跨过门洞的一刻", 换场落在段首(该处正是
#      22 帧重叠区, 合片时被裁掉), 段中不再有第二个空间;
#   2) SPACE_TRANSIT_RULE 删掉"上一处空间在开头的一瞬位于画幅边缘"这条许可,
#      改成"画幅被门墙挡住的那一瞬完成景物置换"——遮挡置换是连续的镜头语言,
#      机位/步频/画幅位置在遮挡前后一致, 画面本身没有跳变。
#   措辞纪律沿用: 纯正向陈述, 不含 cut/转场/叠化/闪白/跳帧 等词, 不含否定句。
_OS_SPACE_TRANSIT_HEAD_RULE = (
    "\n[段首承接] 本段的第一帧就是主体正跨过门前那道门洞的一刻：摄影机的高度、"
    "朝向与运动状态从上一段末尾连续延续，主体的步幅、身体姿态与视线方向也从上一段"
    "末尾的状态连续延续；门洞的石框从画幅一侧掠过，画面就在这一次跨过里落到门内"
    "这一处空间，之后整段镜头都跟着同一次行走在门内向前。"
)

_OS_SCENE_ANCHOR_RULE = (
    "\n[场景锚定] 本段画面里的地面材质、灯具与招牌样式、两侧的建筑与景物，"
    "都与本段脚本所写的这一处空间一致；这一处空间的景物一旦出现在画面里就留在"
    "画面里，本段后续的画面都由这一处空间的景物与灯光构成。"
)


_OS_SAME_SPACE_RULE = (
    "\n[同场景延续] 本段与上一段处在同一处空间里：左右方位、脚下地面、两侧景物"
    "与主体在画幅中的相对位置，本段全部延续上一段的布局；这一处空间里接着出现的"
    "新一段地形，是在主体前进的过程中逐渐展开在画面里的，展开之后就一直展开着，"
    "本段后续的画面都处在这一处已经展开的空间里；这一处空间里的光线与色调也从"
    "上一段末帧那一刻的状态起算，整段只逐拍向前推进一小步；主体身上的受光方向与"
    "地面上的光斑方向自始至终保持一致。"
)

_OS_SPACE_TRANSIT_RULE = (
    "\n[空间过渡] 本段只有一条连续行走：门外那一路的地面、灯具与建筑是上一处的，"
    "门里这一路的地面、灯具与建筑是这一处的，两处空间在画面里由那道真实的门洞与"
    "门墙分开。主体一步接一步跨过门洞：门框的两条竖边从画幅左右两侧掠过，门外的景物"
    "在画幅边缘逐拍退出，门里的景物在同一拍里逐拍进入，门槛石在画幅下方从他脚下掠过；"
    "跨过门洞前后是同一台摄影机、同一个步频、同一个画幅位置，主体一直完整地在画幅"
    "中央正对镜头向前行走，朝向与大小连续。跨过之后，本段画面里只有门里这一处空间的地面、墙面、灯具与建筑，"
    "它们在同一次行走里逐帧展开，越往前走越展开，展开之后就一直展开着；左右方位"
    "自始至终保持一致；本段的光线与色调从上一段末帧那一刻的明暗与色温状态起算，"
    # v14.374: 恢复 v14.373 之前的口径 —— 这里不许写死"夜色/壁灯/夜的深处"。换场段的
    # 明暗与色温只许"从上一段末帧那一刻的状态起算、逐拍朝脚本所写的状态推进"，
    # 写死具体色调会把白天/室内段强压成夜景(与实测的整段色温渐变切镜同源)。
    "整段只逐拍朝脚本所写的光线状态推进一小步，门里新出现的灯具在原有环境光上由暗到亮"
    "逐渐显形，天光的亮度与色温随行走沿同一条连续的方向演进，步幅与节奏自始至终一致。"
)

# v14.319 (2026-11-05): 光影因果化 —— 把"没有画面内原因的整体换色"改写成
# 与上一段末帧衔接的连续推进。
#
# 实测根因 (用户 19 段一镜到底, 段2 f47 切镜, 2026-11-05):
#   段1 尾帧 = 靛紫夜空 + 背面机位 —— 脚本里"橙粉残阳"那段在段1 内部已经演完;
#   段2 的 [光影氛围] 写的是"暮色压低主光, 天际由橘红转暗橙, 海面碎光变稀变冷",
#   这是一句**没有画面内原因**的整体换色 —— 此刻段2 既没穿过门洞也没别的过渡物
#   被触发。模型要同时满足"继承下来的靛紫夜空"和"天际是橘红", 只能把天空从靛紫
#   一路渐变回橘红。这条整体色温斜坡在 f47 附近被眼睛读成"切镜"。
#   对照: 段3 的光影全是灯具级描述(钠灯/站棚/树影), 同样继承靛紫夜空, 全段零换色。
#
# 判据 (只动光影小节, 且必须同时满足三条):
#   (a) 含整体色调名词(天际/天色/天空/天幕/暮色/晚霞/夜色/海平线/海面/河面);
#   (b) 含整体色温变化动词(转/变/接管/推开/让位/褪/跃出/压低/沉入/加深);
#   (c) **不含**画面内可见的过渡物(穿/登/拐/出/经/迈/踏/进入/落位/过/之后/行至)。
# 带 (c) 的句子(穿门后/出洞后/穿过缺口后...)有画面内原因, 一律不动 ——
# 段19 的"天色由靛蓝转浅橙"挂在"穿过缺口后"上, 因此不会被改写。
#
# 措辞纪律: 全文纯正向陈述; 不出现 cut/转场/叠化/剪切/跳帧 等切镜词汇;
# 不出现否定句 (H3 在 CFG=1.0 下没有负向分支); 不写死具体色温数值。
_OS_RELIGHT_SECTION_RE = re.compile(
    r"[\[\u3010]\s*(光影|光线|照明|氛围)[^\[\]\u3010\u3011\n]{0,8}\s*[\]\u3011]")
_OS_GLOBAL_TONE_NOUNS = ("天际", "天色", "天空", "天幕", "暮色", "晚霞", "夜色",
                          "海平线", "海面", "河面", "整片天")
_OS_TONE_CHANGE_VERBS = ("转", "变", "接管", "推开", "让位", "褪", "跃出",
                          "压低", "沉入", "加深")
_OS_TONE_CAUSAL_MARKERS = ("穿", "登", "拐", "出", "经", "迈", "踏", "进入",
                            "落位", "过", "之后", "行至", "抵达", "路过")
_OS_RELIGHT_CANON = (
    "画面里的整体明暗与色温接着上一段末帧那一刻的状态起算，整段画面只有这一次连续的"
    "整体色温变化，天光随着主体向前行走一路沉入更深的夜色"
)


def _one_shot_relight_sentence(sent):
    """v14.319: 判定并改写单句光影描述。返回改写后的句子(没命中则原样返回)。"""
    t = str(sent or "")
    if not t.strip():
        return t
    if "上一段末帧那一刻" in t:      # 已经改写过 —— 幂等
        return t
    if not any(n in t for n in _OS_GLOBAL_TONE_NOUNS):
        return t
    if not any(v in t for v in _OS_TONE_CHANGE_VERBS):
        return t
    if any(c in t for c in _OS_TONE_CAUSAL_MARKERS):
        return t
    # 逐小句: 丢掉带整体色调名词的小句, 保留纯局部描述
    subs = re.split(r"([，,])", t)
    keep = []
    dropped = False
    for sub in subs:
        if sub in ("，", ","):
            keep.append(sub)
            continue
        if any(n in sub for n in _OS_GLOBAL_TONE_NOUNS):
            dropped = True
            continue
        keep.append(sub)
    if not dropped:
        return t
    rest = "".join(keep).strip("，,；;。 ")
    if rest:
        return _OS_RELIGHT_CANON + "；" + rest
    return _OS_RELIGHT_CANON


def _one_shot_relight_global_tone(text):
    """v14.319: 光影小节里的"无因整体换色" -> 与上一段末帧衔接的连续推进。

    只改写光影小节; 其它小节(镜头运动/景别/角色状态/道具交互)逐字不动。
    """
    s = str(text or "")
    if not s.strip():
        return s
    m = _OS_RELIGHT_SECTION_RE.search(s)
    if not m:
        return s
    tail = s[m.end():]
    nxt = re.search(r"[\[\u3010][^\[\]\u3010\u3011\n]{0,30}[\]\u3011]", tail)
    body = tail[:nxt.start()] if nxt else tail
    if not body.strip():
        return s
    parts = re.split(r"([；;。])", body)
    out = []
    changed = False
    for seg in parts:
        if seg and seg not in ("；", ";", "。"):
            new = _one_shot_relight_sentence(seg)
            if new != seg:
                changed = True
                seg = new
        out.append(seg)
    if not changed:
        return s
    return s[:m.end()] + "".join(out) + tail[len(body):]

# 段首标题里的图片标签 —— 段标题形如 "[分镜3]：滨海堤岸@图3-登上海堤石阶(…)"
_OS_PICTURE_TAG_RE = re.compile(r"<Picture\s*\d+>|@图\s*\d+", re.IGNORECASE)


def _one_shot_scene_catalog(global_prompt):
    """v14.294: 从全局提示词的 [场景档案] 小节取出场景名清单。

    场景名清单是"这一处空间叫什么"的权威来源 —— 用它来判定本段与上一段是不是
    同一处空间, 比从标题里猜前缀可靠得多(标题里没有图片标签时直接放弃判定)。
    """
    names = []
    s = str(global_prompt or "")
    m = re.search(r"^\s*\[[^\[\]\n]*场景档案[^\[\]\n]*\]", s, re.MULTILINE)
    if not m:
        return names
    tail = s[m.end():]
    end = re.search(r"^\s*\[", tail, re.MULTILINE)
    block = tail[:end.start()] if end else tail
    for ln in block.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        mm = _OS_PICTURE_TAG_RE.search(ln)
        nm = (ln[:mm.start()] if mm else ln).strip(" \t：:，,、-—·【】()（）")
        if nm:
            names.append(nm)
    return names


def _one_shot_scene_name(text, catalog=None):
    """v14.294: 取段首标题里的场景名(不含图片标签)。

    段标题形如 "[分镜3]：滨海堤岸@图3-登上海堤石阶(…)" —— 场景名 = 第一个图片标签
    之前的那一小段文字。catalog 非空时优先用清单里的规范名做前缀匹配。
    取不到返回 None —— 调用方据此不注入空间规则(其它用户的脚本没有场景档案时安全跳过)。
    """
    s = str(text or "")
    head = ""
    for ln in s.splitlines():
        if ln.strip():
            head = ln.strip()
            break
    if not head:
        return None
    m = _OS_PICTURE_TAG_RE.search(head)
    if not m:
        return None
    pre = head[:m.start()]
    pre = re.sub(r"^\s*\[[^\[\]]*\]\s*", "", pre)   # 去掉 [分镜N] 前缀
    pre = re.split(r"[，,。；;：:\n]", pre)[-1]           # 取最后一段
    pre = pre.strip(" \t：:，,、-—·【】[]")
    if not pre:
        return None
    for nm in (catalog or []):
        if pre.startswith(nm) or nm.startswith(pre):
            return nm
    if len(pre) > 24:
        return None
    return pre


# ============================================================
# v14.362 增量合并: 自 v14.339(17:15 那份) 原样搬入的两套实现 ——
#   ① v14.341 正文时间码「平移归一」(与现役 v14.300「直接剥离」互斥, 二选一)
#   ② v14.341 一镜到底「本段自己的行程」解析 + 段中换场规则
# 当前均未接入主流程, 无任何调用点 -> 运行行为零变化。
# 用途: 离线对照 A/B 两套输出后再决定接入哪一套。
# ============================================================
# v14.341: 正文时间码(M:SS / M:SS.s), 不用 \b —— 中文与数字之间没有词边界。
_OS_TIMECODE_RE = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?:\.(\d{1,2}))?")


def _one_shot_normalize_timecodes(text, offset_sec=0.0, duration_sec=None):
    """v14.341: 把正文里的**全片绝对时间码**归一成本段相对时间码。

    实测(BSAI第077期 clip2): 段首小节写 "01-12秒:", 正文却写
    "0:12–0:13.5 闭口行进（段首1.5秒无唱）… 人声窗口0:13.5–0:24" —— 一个 12 秒的
    片段里出现了 0:24 这种**不可能满足**的时间锚点。H3 有时序感知, 会把它当成
    "段中某个时刻要发生一次新事件", 与"段首1.5秒"互相打架(实测 5.00s 一次机位跳变)。

    触发条件刻意从严:
      * 只有本文出现**超过本段时长**的时间码(即显然是按全片计的绝对时间) 才动手;
      * offset>0 才平移(段1 的绝对时间就是相对时间);
      * 平移后出现负值 -> 判定原文本来就是相对时间码, 原样返回。
    """
    s = str(text or "")
    if not s or float(offset_sec or 0) <= 0:
        return s
    _hits = []
    for _m in _OS_TIMECODE_RE.finditer(s):
        _sec = int(_m.group(1)) * 60 + int(_m.group(2))
        if _m.group(3):
            _sec += float("0." + _m.group(3))
        _hits.append((_m, _sec))
    if not _hits:
        return s
    _dur = float(duration_sec) if duration_sec else None
    if _dur is None:
        return s
    if max(_sec for _, _sec in _hits) <= _dur + 0.5:
        return s
    _off = float(offset_sec)
    if min(_sec for _, _sec in _hits) - _off < -0.05:
        return s
    _out, _last = [], 0
    for _m, _sec in _hits:
        _out.append(s[_last:_m.start()])
        _new = _sec - _off
        _mins = int(_new // 60)
        _rem = _new - _mins * 60
        if _m.group(3):
            _dec = len(_m.group(3))
            _body = f"{_rem:0{3 + _dec}.{_dec}f}"
            if _body.split(".")[0] == "60":
                _mins += 1
                _body = f"{0:0{2 + 1 + _dec}.{_dec}f}"
            _out.append(f"{_mins}:{_body}")
        else:
            _rsec = int(round(_rem))
            if _rsec >= 60:
                _mins += 1
                _rsec -= 60
            _out.append(f"{_mins}:{_rsec:02d}")
        _last = _m.end()
    _out.append(s[_last:])
    return "".join(_out)


_OS_EMPTY_PAREN_RE = re.compile(r"[（(]\s*[）)]")
_OS_ROUTE_TAG_RE = re.compile(r"([ST])\s?(\d{1,2})")
_OS_ROUTE_NAME_CUT_RE = re.compile(r"[@<（(\n【\[]")


def _one_shot_scene_route(text, catalog=None):
    """v14.341: 解析本段自己的行程。

    段首行是一镜到底 skill 的写法:
        "：S2 雅典帕特农神庙·卫城山门@图4-登阶上行 → T2 山门石阶阙口右柱脚（直行绕过·0°）
         → S3 圣家族大教堂·中殿侧廊@图5（【演唱中】…）【本段运镜…】"

    返回 dict:
        start    起行的那一处空间(第一个 S 段的名字)
        end      终止的那一处空间(最后一个 S 段的名字)
        transit  段中要跨过的过渡物(T 段的名字), 没有则 None
        cross    start != end —— 本段行程跨了两处空间
        route    行程原文(日志/审计用)
    解析失败或单段行程时 end == start、cross False。
    """
    _empty = {"start": None, "end": None, "transit": None, "cross": False, "route": ""}
    s = str(text or "")
    head = ""
    for ln in s.splitlines():
        if ln.strip():
            head = ln.strip()
            break
    if not head:
        return _empty
    # 行程只取到第一个方括号小节(【本段运镜… / [镜头运动]…) 之前 —— 那些小节里
    # 的 "中景起幅→中近景→近景" 也是箭头分隔, 不能被当成场景路线。
    _cut = len(head)
    for _mk in ("【", "["):
        _p = head.find(_mk)
        if _p > 0:
            _cut = min(_cut, _p)
    route = head[:_cut].strip(" \t：:，,、；;")
    route = re.sub(r"^\[[^\[\]]{0,12}\]\s*[：:]?\s*", "", route)
    if not route:
        return _empty
    segs = [x.strip(" \t：:，,、；;-—") for x in re.split(r"→|->", route)]
    scenes, transit = [], None
    for seg in segs:
        _m = _OS_ROUTE_TAG_RE.match(seg)
        if not _m:
            continue
        _kind = _m.group(1).upper()
        _label = f"{_kind}{int(_m.group(2))}"
        _body = _OS_ROUTE_NAME_CUT_RE.split(seg[_m.end():])[0]
        _body = _body.strip(" \t：:，,、；;-—·")
        _name = f"{_label} {_body}".strip() if _body else _label
        for _nm in (catalog or []):
            if (_nm == _name or _nm.startswith(_name) or _name.startswith(_nm)
                    or _nm.startswith(_label + " ")):
                _name = _nm
                break
        if _kind == "S":
            scenes.append(_name)
        elif _kind == "T" and transit is None:
            transit = _name
    start = scenes[0] if scenes else None
    end = scenes[-1] if scenes else None
    return {"start": start, "end": end, "transit": transit,
            "cross": bool(start and end and start != end), "route": route}


def _one_shot_transit_mid_rule(start, end, transit=None):
    """v14.344: 段中换场 —— 画幅以主体为锚、景物迎面流过、柱身整块遮镜(前三层继承 v14.343),
    另把「起幅归谁 / 换场在哪一段 / 换场后只剩谁」三处钉死。

    v14.343 实机首片(h3_clip_250_1_1794280356, 11:12, 1920x1088/294帧)的结果:
      * 用户报的两个缺陷都消失了 —— 无双曝、无中心淡入淡出、无倒走(她占画高 0.42→0.98
        逐拍单调变大, 一路朝镜头走来), 换场处也没留硬切;
      * 但暴露出一个新缺陷: **整段只在 S2 帕特农/卫城山门里走, S1 故宫一帧都没出现。**
        抽帧 0.04/0.30/2.00/3.00/4.12/4.50/5.80/6.20/6.60/8.00/9.21/9.50/11.80 全是希腊
        石廊, 两处空间被读成了同一处(行程塌缩)。
      * 对照 v14.342 同一 clip(16:38 那轮)注入的同类规则, 第一句是"起幅这一路的地面、灯具
        与两侧建筑是 S1 的" —— 那轮开幅确实是故宫红门。v14.343 把首句改成"主体站在{transit}
        的 S1 一侧", 模型于是把"起幅"理解成"已经站在券门旁边", 露头就迈出门去, 整段留在 S2。
      * 规则里"两处空间在同一条地面、同一片夜色里各自完整地铺开"这句是帮凶: 同一片地面/同一
        片夜色 → 两处空间被合成一处, 也就再也没有"换一次世界"的必要。

    v14.344 的修法(仍纯规则文本, 零新增采样):
      1) 首句改回"起幅到换场之前, 画幅里的地面、墙面、门洞、灯具与建筑全是{start}自己的
         东西", 并明写"颜色、材质与标志物按脚本写给{start}的原词出现, 与{end}明显不同"
         —— 开幅归属不再有歧义;
      2) 删掉"同一条地面、同一片夜色", 改成"两处空间各自的地面、墙面、颜色与标志物各不相同";
      3) 给换场一个时间窗("本段中段, 大约第三秒到第六秒之间的那两三拍") —— 没有时间锚时
         模型会把换场提前到 0 秒(等于整段只在 S2);
      4) 明写"换场之后到本段末帧, 画幅里只剩{end}自己的东西" —— 两处不再混同。

    v14.347 实机(15:44 轮 clip1 h3_clip_250_1_1794297087, 1920x1088/294 帧/12.25s):
      * v14.344 的三处修法都生效了 —— 起幅是 S1 故宫的城台拱墙(0.20s 抽帧), 约 6.5s 柱身整块
        盖住镜头, 7s 之后整段是 S2 帕特农/卫城山门, 两端接得上, 没有塌缩;
      * 但用户报"第一个分镜就倒着走"。抽样占画高 0.52(1.0s) → 0.55(5.0s) → 0.57(9.0s) 一路
        变大, 一路朝镜头走来 —— 距离上并不倒行, 倒行出在**步态**:
        ① "他每一步的鞋尖都朝面前那道镜头抬起来再落下去、脚跟随后抬起, 鞋底在画幅里由小
           变大" —— 鞋底朝镜头且变大, 只有往后甩腿时才看得见鞋底, 这是 moonwalk 的标准姿势;
        ② "地面石缝、石阶棱线、两侧柱列与灯具迎面朝镜头流动过来" —— 这一句等于机位在前进;
           机位前进 + 人朝镜头露鞋底 = 模型只能让她一边朝镜头一边往后甩腿, 两句并置就是
           moonwalk 的完整配方。v14.343 删掉"机位朝哪走"时漏了这一对。
        另: 6.50s 抽帧她整个人在石面上透出浅影(半透明双曝的残影), 属遮挡未完全做实。

    v14.347 的修法(仍纯规则文本, 零新增采样):
      1) 步态全改成正走: "抬起来的那只脚先在他身后离地, 膝盖朝镜头这一侧带出去, 整只脚从
         他身后甩到镜头这一侧, 鞋头先落到地上、脚跟随后落平", "画幅里看到的是鞋面、鞋头与
         鞋带" —— 删掉"鞋底在画幅里由小变大"与"脚跟随后抬起";
      2) 景物方向与本段正走绑成同一件事: "地面石缝与石阶棱线一拍比一拍更靠近画幅下缘",
         "落地的那一格地面随即从他脚下往后滑过画幅下缘" —— 不再用"迎面朝镜头流动"这种
         把机位速度交代给模型的写法;
      3) 遮挡做实: "那两三拍画幅的每一寸都是石头、画幅里只有石头这一层、主体整个人藏在
         这块实心石面后面、石面的棱边与砌缝都是实的"。

    v14.343 / v14.344 已验证有效的部分全部保留: 画幅以主体为锚、起幅归属句、换场时间窗、
    柱身整块遮镜、换场后只剩 end、每一拍只有一层实景。
    全文正向陈述, 不含 cut/转场/叠化 词汇, 不含否定词, 不含任何"后移"类写法。

    v14.375 实机(10:07 轮 clip1 h3_clip_250_1_1794362835, PIKA H3 Flex 8+2, 1920x1088/294帧):
      * v14.347 的步态句子在, 但**出片仍然 moonwalk**, 而且换场也没发生(整段留在 S1)。
      * 抽帧证据: 占画高 0.52→0.64 一路变大, 而地面砖缝、石阶棱线逐帧纹丝不动 ——
        主体在画幅里被放大、脚下却没有位移, 双腿只能在画幅下方原地倒腾; 这正是"倒着走"
        的观感来源, 比 v14.347 诊断的"鞋底朝镜头"更根本。
      * 真根因: v14.347 只改了**规则文本**, 脚本**正文**里的
        「镜头与主播@图1…沿其行进方向平稳前移」+「正对主播@图1的正面」+「推近」三条一直在;
        规则说"画幅以主体为锚、前进感由景物承担", 正文说"机位沿行进方向前移", 两句对撞,
        模型取交集 = 人在画幅里变大、地面不动、双腿倒腾。
      * 修法两条: ① 新增 _one_shot_neutralize_camera_dir, 在正文层把"沿其行进方向前移"
        改写成"与主播同距同速、只随其位移同步移动"(纯文本改写, 不动用户工作流/脚本源文件);
        ② 本规则补三件事 —— 机位几何一次说清(正前方同距同速、朝画幅纵深移动、地面朝镜头涌来)、
        落脚点与地面流动同向(脚从画幅下缘以下前摆进来、落地后随地面滑出画幅)、
        地面流动是唯一位移证据(一秒三到四条石缝、每迈一步滑走一道)。
    """
    _start = start or "脚本起行的那一处空间"
    _end = end or "脚本终止的那一处空间"
    _transit = transit or "脚本所写的那道门洞"
    return (
        f"\n[空间过渡] 本段是一条连续行走。起幅时主体站在{_transit}的{_start}这一侧、"
        f"正面朝镜头；起幅到跨过门槛之前，画幅里的地面、墙面、门洞、灯具与建筑全是{_start}自己"
        f"的东西 —— 它们的颜色、材质与标志物按脚本写给{_start}的原词出现，与{_end}明显"
        f"不同，一眼就看得出画幅里此刻是{_start}。"
        # v14.376: 真根因 —— v14.343 起这条规则一直写着「画幅以他为锚、位置自始至终固定在
        # 同一个地方」, v14.375 又补了「双脚始终踩在画幅下方同一片地面区域内」, 等于把主体
        # 在画幅里钉死。钉死之后他不可能真的往前走, 模型只能让双腿在画幅下方原地倒腾 ——
        # 用户看到的就是"从头到尾倒着走"。v14.375 那轮二采真跑了、换场也回来了, 唯独这一步
        # 没修, 而且钉得更死。
        # v14.378 真根因(新片 h3_clip_250_1_1794384070 取证): 这一句与后面 [取景连续] 的
        # 「摄影机沿同一条轨迹与他同速同行、同距同高，占画比例自始至终稳定」硬自相矛盾
        # (一个说机位钉在一处地面、人靠变大前进; 一个说机位与人同速同行、占画比例稳定)。
        # 模型二选一的结果是"滑行/平移": 实测地面分区中位 dy 只有 +0.04~0.06px/帧(地面
        # 根本不动), 而占画高 0.187→0.709 全靠变大 —— 位移全部来自缩放, 双腿原地不动。
        # 现统一到脚本正文自己的口径(用户脚本写的是"镜头与主播同一条轨迹、同速同向、正对
        # 正面"): 机位跟她同速同行, 前进凭据由「地面一道接一道后流过画幅下缘」承担。
        "本段机位与镜头机身沿同一条轨迹与他同速同行、同距同高，始终正对画幅里他的正面；"
        "取景范围只随本段景别路径连续变化，他因此按景别路径平缓变大或变小。"
        "他与镜头一同向前走，地面因此持续向后流过画幅："
        "他每一步都是一次干净的向前迈步：抬起的那只脚屈膝向前摆、膝盖领先于脚尖，"
        "越过支撑脚之后落在更靠近画幅下缘的一道新石缝上，脚跟先着地、鞋尖随后落平；"
        "落地那一拍画幅下方出现的是鞋面与鞋尖，鞋底与鞋跟朝向地面与画幅下缘。"
        "脚掌踩实之后与它踩住的那道石缝位置完全重合，随后随地面一起从画幅下缘滑出去；"
        f"{_start}的地面石缝与石阶棱线一道接一道向后流过画幅下缘，"
        "他一步跨过一道：一秒之内他跨过三到四道石缝，已经跨过的石缝留在画幅里他的身后。"
        f"两侧柱列与灯具同样一道接一道向后流过画幅两侧，他一步一步从它们之间走过。"
        f"{_transit}的门洞就立在{_start}与{_end}之间：门框这一侧是{_start}，"
        f"门框的另一侧是{_end}，两处空间各自的地面、墙面、颜色与标志物彼此明显不同。"
        # v14.385 (2026-11-12): 换场机制改回「主体自己走过去」。
        # 用户口径(针对 h3_clip_250_1_1794456674, 12.25s): 「场景变化不对, 一镜到底模式
        # 应该是从上一个场景自然走进下一个场景」。旧文本写的是「柱身迎面涨满整幅画幅、
        # 整块盖住镜头、主体整个人藏在实心石面后面」—— 那是**遮挡式切换**: 出片在约 9s
        # 出现整幅石面盖镜、之后跳到另一个空间, 观感就是一次转场, 当事人被挡掉再出现。
        # 现改成: 主体正对镜头一步接一步走过门洞, 空间在他身上逐拍替换 ——
        # 走近 → 门框向画幅两侧分开 → 跨过门槛石 → 身后的 start 逐拍换成 end。
        # 全程主体完整在画幅里、脚步连续, 画幅四角始终看得见地面与两侧建筑。
        "换场由他自己走过去完成 —— 换场落在本段中段，大约第三秒到第六秒之间的这几拍："
        f"{_transit}的门洞在画幅正前方由小及大迎面推近，"
        "两条竖直门框向画幅左右两侧分开、中间空出门洞的纵深；"
        f"他一步一步走近门洞，画幅下方的地面从{_start}的石缝逐拍过渡到门槛石；"
        f"跨过门槛的那一拍，画幅下方出现的是{_end}的第一道石缝、画幅两侧出现的是{_end}的墙与灯。"
        "跨过门槛之后他到本段末帧一直在这条通道里正对镜头向前行走，脚步连续、一步一步踩过地面；"
        f"画幅两侧与身后的{_start}的墙面、柱列与灯具逐拍换成{_end}的墙面、柱列与灯具。"
        "整个换场过程中主体完整地出现在画幅中央、正面朝镜头、一步一步向前，"
        "画幅的四角自始至终看得见地面与两侧建筑，"
        "门框的两条竖边与门槛石接住这一下前一后的两处空间。"
        f"本段画面始终是一层完整的实景：跨过门槛之前画幅是{_start}的实景，"
        f"跨过门槛之后画幅是{_end}的实景，"
        "两处由门框与门槛石接住，画幅里每一拍只有一处空间的实景。"
        f"脚本里写的登阶、绕过、走入、穿过、与她同速穿过某处，本段统一由画幅迎面进入"
        f"{_transit}这一下完成。步幅与节奏自始至终一致，光线与色调由起幅那一刻的明暗与"
        "色温起算，整段逐拍沿同一条轨迹推进一小步。"
    )



def _one_shot_scene_anchor_mid_rule(start, end, transit=None):
    """v14.343 (v14.385 改): 段中换场段的场景锚定 —— 置换点是**主体自己跨过门槛那一拍**。"""
    _start = start or "脚本起行的那一处空间"
    _end = end or "脚本终止的那一处空间"
    _transit = transit or "脚本所写的那道门洞"
    return (
        f"\n[场景锚定] 本段起幅到主体跨过{_transit}的门槛之前，主体身后的地面材质、灯具与"
        f"两侧建筑都与{_start}一致；跨过门槛的那一拍之后，主体身后的地面材质、灯具与"
        f"两侧建筑都与{_end}一致，并一直保持到本段末帧；门槛石与门框的两条竖边就是这两处"
        "空间的分界，画幅逐拍从一侧过渡到另一侧。本段画面里只有这两处空间，"
        "按这一次行走的先后顺序出现。"
    )


def _one_shot_space_decision(routes, i, names=None):
    """v14.341: 空间判定 —— 返回 (本段起行场景, 上段末场景, kind, site)。

    判定顺序(接缝优先):
      1) 上段末场景 != 本段起行场景 -> "空间过渡"/"head"  接缝本身换场, 换场压段首;
      2) 本段自己的行程 start != end   -> "空间过渡"/"mid"  换场落在段中跨过渡物处;
      3) 上段末场景 == 本段起行场景且已知 -> "同场景延续";
      4) 无任何可用场景信息 -> (None, None, None, None)。
    names(段首解析出的场景名)只在行程解析失败时兜底: 本段兜 start, 上一段兜 prev。
    """
    _rt = (routes[i] if 0 <= i < len(routes) else None) or {}
    _scene = _rt.get("start") or (names[i] if names and i < len(names) else None)
    _end = _rt.get("end") or _scene
    _prev = ((routes[i - 1] if i > 0 else None) or {}).get("end")
    if not _prev and names and 0 < i < len(names):
        _prev = names[i - 1]
    if not _scene:
        return None, _prev, None, None
    if _prev and _prev != _scene:
        return _scene, _prev, "空间过渡", "head"
    if _end and _end != _scene:
        return _scene, _prev, "空间过渡", "mid"
    if _prev:
        return _scene, _prev, "同场景延续", None
    return _scene, _prev, None, None


def _one_shot_size_anchor_rule(start=None, end=None):
    """v14.292: 取景锚定规则 —— 把脚本自己给的景别写成显式边界。

    只在景别链**可靠**解析时使用(拍段级命中), 否则返回空串。
    全文纯正向陈述, 与脚本给的景别不冲突 —— 它复述脚本的取值, 额外补一句
    "推近/拉远都在这个范围内完成", 防止模型一路推过头再硬切回来。
    """
    if not start:
        return ""
    if not end or end == start:
        return (
            "\n[取景锚定] 本段主体的取景范围是{0}：起幅与末帧保持同一取景范围，"
            "每一拍都从上一拍的取景范围平滑过渡过去；主体在画幅中的占画比例始终落在"
            "这个景别范围内平缓变化，推近与拉远都在这个范围内完成。".format(start)
        )
    return (
        "\n[取景锚定] 本段主体的取景范围由本段给定的景别决定：起幅是{0}，末帧是{1}。"
        "每一拍都从上一拍的取景范围平滑过渡过去，主体在画幅中的占画比例始终落在这两个"
        "景别之间平缓变化；推近与拉远都在这个景别范围内完成，到达给定的取景范围后保持稳定。"
        .format(start, end)
    )


def _one_shot_size_rule(locked_size=None, prev_end=None, cur_start=None,
                        full_sing=False):
    """v14.286: 生成景别相关的一镜到底规则文本(纯函数, 主循环与测试共用一份)。

    返回 (text, seam_mismatch):
      locked_size —— 用户显式声明的全片景别; 非空 → 锁死该景别
      prev_end    —— 上一段末帧景别
      cur_start   —— 本段首帧景别
      full_sing   —— v14.332: 本段整段都在唱/说(lip_audio 覆盖全段)

    全文只用正向陈述 —— H3 在 CFG=1.0 下没有负向分支, "没有/看不到/禁止" 这类
    否定词会被当成画面内容渲染。

    v14.332 实测(clip5): 锁死中全景 + "需要呈现唇形时推近、唇形段落结束后推回"
    在**整段演唱**的段里没有"段落结束"这个时刻, 模型只执行了推近那一半 ——
    12 秒全程停在胸像近景, 与 [全片统一景别] 的中全景互相矛盾。整段演唱时改成
    "取景范围全程固定", 口型改在中全景画幅里表达。
    """
    if locked_size:
        if full_sing:
            return (
                "\n[取景连续] 起幅、段中与末帧都保持{0}：摄影机沿同一条轨迹与他同速"
                "同行、同距同高，取景范围整段固定为{0}，主体在画幅中的占画比例自始至终"
                "稳定；他一路边走边唱，口型在中全景的画幅里直接可辨，嘴唇与下颌的开合"
                "随歌声逐字清晰可见。".format(locked_size),
                False,
            )
        return (
            "\n[取景连续] 起幅保持{0}：摄影机沿同一条轨迹连续推进，需要呈现唇形时"
            "沿原方向缓慢推近到人物面部，推近过程每一步都连续；唇形段落结束后再缓慢"
            "推回{0}。推近与推回的速度全程均匀，主体在画幅中的占画比例逐帧连续变化，"
            "景别之间只通过摄影机的连续推移完成过渡。".format(locked_size),
            False,
        )
    text = (
        "\n[景别连续] 景别自始至终只随摄影机连续的推移与升降而连续变化，"
        "本段末帧的取景范围与下一段首帧的取景范围完全一致，"
        "主体在画幅中的大小全程连续演进，画面里的景别始终平缓渐进。"
    )
    mismatch = bool(prev_end and cur_start and cur_start != prev_end)
    if mismatch:
        text += (
            "\n[景别衔接] 本段起幅时保持上一段末帧的{0}取景范围，"
            "摄影机以连续的后退或推近逐帧把取景范围过渡到本段的{1}，"
            "过渡过程平滑连续，画面里的景别始终平缓渐进。".format(prev_end, cur_start)
        )
    return text, mismatch


# ── v14.284 (2026-11-03): 一镜到底 —— 全局提示词「去多镜头结构化」 ────────
#
# 根因(19 段一镜到底×歌曲链实测, 2026-11-03):
#   用户的全局提示词带三张分镜表([场景连通表] / [场景串联核对表] / [人声分布总表],
#   合计 59 行表格) 与 S1→S20 场景路线串。_strip_archive_sections 只剥离标题含
#   "档案"的段落, 这三张表全部保留, 而全局提示词会被**前置到每一段**的条件里。
#   H3 的时序先验把 "镜 1 | S1堤道中段 | T1防汛石阶 | S2阶顶平台东侧 | 镜2首帧同站位"
#   这类行当成"本段要依次走完的镜头", 于是段内 2~4s 处自己切镜头并跳到表里的
#   其它场景: 实测 clip2 第 78 帧(3.25s)由滨海堤岸**叠化**到老城街口, 景别/机位/
#   主体朝向同时改变; 主体朝向翻转 180°(正面→背面)后, 同一段行走被反向重绘,
#   观感上就是"人物倒走"。
#
# 一镜到底的语义 = 每段只有一个镜头, 条件文本里不允许出现任何多镜头结构。
# 因此在编码前把全局/分段提示词里的多镜头结构整段清掉, 并用一句正向的
# "环境连续渐变"陈述替代被删掉的"场景串联"(保留跨段衔接意图, 不含任何分镜表)。

# 多镜头结构小节标题黑名单(标题命中即整节删除)
_OS_SHOTLIST_SECTION_KEYS = (
    "场景串联", "场景连通", "串联核对", "人声分布", "镜次", "分镜表",
    "镜头表", "镜头分配", "景别表", "运镜表", "连拍表", "时间码表", "时间轴",
    "场景清单", "场景表", "场次表", "镜头脚本", "转场表",
)
# 保护名单: 命中黑名单但属于"全片统一运镜/景别纪律"的小节必须保留
_OS_SHOTLIST_KEEP_KEYS = ("统一运镜", "统一景别", "运镜纪律", "景别纪律", "机位纪律")

# 方括号小节标题(半角 [] 与全角 【】 都要认)
_OS_BRACKET_TITLE_RE = re.compile(r"[\[【]\s*([^\[\]【】\n]{0,30}?)\s*[\]】]")
# 场景路线串: "S1xxx→T2yyy→S3zzz"(≥3 段由箭头连接)—— 一镜到底模式下这是分镜结构。
# 同时认 S 编号(场景) 和 T 编号(拍/中间态)。段与段之间以 → 分隔,
# 每段开头必须有 [ST]\d{1,2} 编号, 尾巴可选编号。
# v14.321: 之前只认 S 编号, 用户脚本里夹着 T4 路灯下的老城巷口 → 整条 S4→T4→S5
# 没被清掉, H3 读到 S5 街口牌坊/后面的 S11 石拱桥 → 在 f31-f32 硬切。
# v14.374: 恢复 v14.341 修好的字符排除条件 —— 段内行程串是模型唯一的起点/过渡物/
# 终止空间依据, 绝不能当成"分镜结构"删掉。带 @图 / <Picture> / 括号标注的行必须要
# 保住; 只有纯 S→T→S 的结构串(不含标签、不含括号注)才允许清。
# v14.373 把这两组排除条件放宽成 [^→\n]{0,36}, 于是 `S2 …@图4 → T2 …（直行绕过）→ S3`
# 整条被删, 模型既不知起点也不知过渡物 —— check_one_shot_route_rules 当场掉 3 条。
_OS_ROUTE_CHAIN_RE = re.compile(
    r"(?:[ST]\d{1,2}[^→@<（(\n]{0,24}→\s*){2,}(?:[ST]\d{1,2}[^；;。\n@<（(]{0,24})?"
)

# 否定式镜头口号 → 正向陈述。
# H3 在 CFG=1.0 下没有负向分支, "不放大也不收窄" 这类否定句会被当画面内容渲染
# (社区 PROMPTING.md 结论), 反而把镜头推向"该动一动"的相反方向。这里只做正向改写。
_OS_NEG_TO_POS = (
    ("不放大也不收窄", "保持同一景别与同一占画比例"),
    ("不放大", "保持同一景别"),
    ("不收窄", "保持同一景别"),
    ("不出现突然的姿态跳变", "姿态自始至终连续自然"),
    ("从不关机", "全程开机"),
    ("不关机", "持续开机"),
    ("不中断", "持续不断"),
    ("不静止", "持续运动"),
    ("不停留", "持续前行"),
)


def _one_shot_is_shotlist_title(title):
    """标题是否属于"多镜头结构"(分镜表/镜次表/场景串联表)。"""
    t = str(title or "").strip()
    if not t:
        return False
    for _k in _OS_SHOTLIST_KEEP_KEYS:
        if _k in t:
            return False
    for _k in _OS_SHOTLIST_SECTION_KEYS:
        if _k in t:
            return True
    return False


def _one_shot_drop_inline_shotlist_sections(line):
    """删掉一行里内嵌的"多镜头结构"小节(标题起 → 下一个标题/行尾)。"""
    _titles = list(_OS_BRACKET_TITLE_RE.finditer(line))
    if not _titles:
        return line
    _spans = []
    for _idx, _m in enumerate(_titles):
        if not _one_shot_is_shotlist_title(_m.group(1)):
            continue
        _end = _titles[_idx + 1].start() if _idx + 1 < len(_titles) else len(line)
        _spans.append((_m.start(), _end))
    if not _spans:
        return line
    _out = []
    _prev = 0
    for _s, _e in _spans:
        _out.append(line[_prev:_s])
        _prev = _e
    _out.append(line[_prev:])
    return "".join(_out)


def _one_shot_drop_shotlist_sections(text):
    """删掉整块"多镜头结构"小节: 标题行 + 其后的正文行, 直到下一个标题行。"""
    _out = []
    _skipping = False
    for _ln in str(text or "").splitlines():
        _m = re.match(r"^\s*[\[【]\s*([^\[\]【】\n]{0,30}?)\s*[\]】]", _ln)
        if _m:
            _skipping = _one_shot_is_shotlist_title(_m.group(1))
            if _skipping:
                continue
        elif _skipping:
            # 表格行/正文行属于被删小节, 继续跳过
            continue
        _out.append(_one_shot_drop_inline_shotlist_sections(_ln))
    return "\n".join(_out)


def _one_shot_demulti_shot(text, label=""):
    """v14.284: 一镜到底 —— 清除提示词里的多镜头结构(分镜表/场景路线/否定口号)。

    返回清洗后的文本。清洗内容:
      1. 多镜头结构小节(整节, 含表格正文行)
      2. 表格行(≥2 个 '|')—— 即便标题没被识别也清掉
      3. 场景路线串(S1→S2→S3)
      4. 否定式镜头口号 → 正向陈述
      5. 【转场】行内标签 —— 画面切镜高危词(见下)
    """
    s = str(text or "")
    if not s.strip():
        return s
    _orig = len(s)
    s = _one_shot_drop_shotlist_sections(s)
    s = "\n".join(_ln for _ln in s.splitlines() if _ln.count("|") < 2)
    s = _OS_ROUTE_CHAIN_RE.sub("", s)
    for _a, _b in _OS_NEG_TO_POS:
        s = s.replace(_a, _b)
    # v14.286: 删掉行内的【转场】标签。
    # 段标题里的 【转场】 是**人声状态**标记(转场·中途入唱), 不是画面指令, 但
    # H3 只认字面 —— "转场" 在段首出现会被读成画面转场, 直接诱发段内切镜。
    # 这里纯删除标签本身, 保留后面的人声时间码(口型由 lip_audio 驱动)。
    s = re.sub(r"[【\[]\s*转场\s*[】\]]\s*[·・:：]?", "", s)
    # v14.298: 段标题里其余的人声状态标记(【演唱中】/【不唱】 + 全片人声时间码)
    # 也整块剔除 —— "不唱" 是否定词(CFG=1.0 无负向分支 -> 会张嘴唱), 全片时间码
    # 会给模型错的时序锚点。口型/人声一律由 lip_audio 驱动。
    s = _one_shot_strip_vocal_tags(s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    if len(s) != _orig:
        print(f"[H3 Extender] v14.284 一镜到底去多镜头结构[{label or 'clip'}]: "
              f"{_orig} -> {len(s)} 字符 (已清分镜表/场景路线串/否定式切镜口号)")
    return s


def _one_shot_locked_size(text):
    """v14.284: 从全局提示词的"景别小节"里取全片锁定的景别词; 取不到返回 None。

    只看标题含"景别"的小节, 并取该小节正文里**最先出现**的景别词(与
    _one_shot_first_size 同口径: 按字面首次出现位置, 不按尺度排序)。
    """
    s = str(text or "")
    for _m in re.finditer(r"[\[【]\s*([^\[\]【】\n]{0,20}景别[^\[\]【】\n]{0,20})\s*[\]】]", s):
        _seg = s[_m.end():]
        _nxt = re.search(r"[\[【]", _seg)
        if _nxt:
            _seg = _seg[:_nxt.start()]
        _w, _en = _one_shot_first_size(_seg)
        if _w:
            return _w
    return None


def _parse_clips_json(value: str):
    try:
        payload = json.loads(value or "{}")
    except Exception as exc:
        raise ValueError(f"MiniMax H3 Extender: invalid clips JSON: {exc}") from exc

    if isinstance(payload, list):
        clips = payload
    elif isinstance(payload, dict):
        clips = payload.get("clips", [])
    else:
        clips = []

    if not clips:
        clips = [_default_clip(0)]
    if len(clips) > MAX_CLIPS:
        raise ValueError(
            f"MiniMax H3 Extender: {len(clips)} clips requested; max is {MAX_CLIPS}."
        )

    out = []
    for i, raw in enumerate(clips):
        raw = raw if isinstance(raw, dict) else {}
        try:
            seed = int(raw.get("seed", 0))
        except Exception:
            seed = 0
        seed = max(0, min(DEFAULT_SEED_MAX, seed))

        try:
            duration = float(raw.get("duration", DEFAULT_DURATION))
        except Exception:
            duration = DEFAULT_DURATION
        duration = max(0.25, min(150.0, duration))

        seed_mode = str(raw.get("seed_mode", "randomize"))
        if seed_mode not in {"randomize", "fixed", "increment", "decrement"}:
            seed_mode = "randomize"

        # v14.85 CLIP 级独立超分开关（三态）：None=跟随总开关 upscale_per_clip；
        # True=强制本 CLIP 超分；False=强制本 CLIP 不超分（优先于总开关）。
        _up_raw = raw.get("upscale")
        if _up_raw not in (None, True, False):
            _up_raw = None

        out.append(
            {
                "id": str(raw.get("id") or f"clip_{i + 1}"),
                "name": str(raw.get("name", "")),
                "prompt": str(raw.get("prompt", "")),
                "seed": seed,
                "seed_mode": seed_mode,
                "duration": duration,
                "validated": bool(raw.get("validated", False)),
                "context_enabled": bool(raw.get("context_enabled", True)),
                "color_adjustment": _normalize_color_adjustment(raw.get("color_adjustment")),
                "render_enabled": bool(raw.get("render_enabled", True)),
                "replace_mode": bool(raw.get("replace_mode", False)),
                "upscale": _up_raw,
            }
        )

    # Validation must always be a continuous prefix. Anything after the first
    # unvalidated clip depends on a clip that is not frozen yet.
    found_open = False
    for clip in out:
        if found_open:
            clip["validated"] = False
        elif not clip["validated"]:
            found_open = True

    return out


def _prompt_pack_signature_from_state(value):
    if isinstance(value, dict):
        payload = value
    else:
        try:
            payload = json.loads(str(value or "{}"))
        except Exception:
            payload = {}
    if not isinstance(payload, dict):
        return ""
    signature = str(payload.get("prompt_pack_signature") or "").lower().strip()
    if len(signature) != 64 or any(ch not in "0123456789abcdef" for ch in signature):
        return ""
    return signature


def _parse_clip_select(value, total_clips):
    """Parse clip_select string into a set of 0-indexed clip indices.

    Accepts: "all", "2", "2,3", "2-5", "1,3-5", "3,5,7", "7-10"
    Also tolerates Chinese full-width punctuation: "3，5，7", "2－5".
    Returns None for "all" (meaning: render every clip normally).
    Returns a set of 0-indexed ints for specific clips.
    """
    raw = str(value or "all").strip().lower()
    if not raw or raw == "all":
        return None
    # v2.62: 兼容中文标点（全角逗号/顿号/分号）与空格
    raw = raw.replace("，", ",").replace("、", ",").replace("；", ";").replace(";", ",")
    raw = raw.replace(" ", "")
    # 全角连字符/波浪号归一化为半角连字符（如 2－5 / 2～5）
    raw = raw.replace("－", "-").replace("—", "-").replace("～", "-").replace("~", "-")

    indices = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(\d+)\s*-\s*(\d+)$", part)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if lo > hi:
                lo, hi = hi, lo
            for n in range(lo, hi + 1):
                idx = n - 1
                if 0 <= idx < total_clips:
                    indices.add(idx)
        else:
            try:
                idx = int(part) - 1
            except ValueError:
                continue
            if 0 <= idx < total_clips:
                indices.add(idx)

    if not indices:
        return None
    return indices


def _state_json(clips, prompt_pack_signature="", merge_output=False):
    payload = {"version": 1, "clips": clips}
    signature = str(prompt_pack_signature or "").lower().strip()
    if len(signature) == 64 and all(ch in "0123456789abcdef" for ch in signature):
        payload["prompt_pack_signature"] = signature
    if merge_output:
        payload["merge_output"] = True
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _merge_output_from_state(value: str):
    """Extract merge_output flag from clips_json state."""
    try:
        payload = json.loads(value or "{}")
        if isinstance(payload, dict):
            return bool(payload.get("merge_output", False))
    except Exception:
        pass
    return False


def _normalize_external_prompt_pack(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("MiniMax H3 Extender: external prompt pack is invalid.")

    prompts_raw = value.get("prompts")
    if not isinstance(prompts_raw, (list, tuple)):
        raise ValueError("MiniMax H3 Extender: external prompt pack has no prompt list.")

    prompts = []
    found_empty = False
    for index, raw in enumerate(list(prompts_raw)[:10], start=1):
        text = "" if raw is None else str(raw)
        if not text.strip():
            found_empty = True
            continue
        if found_empty:
            raise ValueError(
                "MiniMax H3 Extender: external prompt pack contains a gap before "
                f"prompt {index}."
            )
        prompts.append(text)

    if not prompts:
        raise ValueError("MiniMax H3 Extender: external prompt pack contains no prompts.")

    signature = _prompt_pack_signature(prompts)
    return {
        "type": PROMPT_PACK_TYPE,
        "version": int(value.get("version", 1) or 1),
        "source": str(value.get("source") or "External prompt pack"),
        "count": len(prompts),
        "prompts": prompts,
        "signature": signature,
    }


def _sync_clips_from_prompt_pack(clips, pack, stored_signature=""):
    """Import a changed pack into normal clip prompts and sync card count.

    A pack is an import source, not a second runtime prompt path. Once imported,
    the textarea prompt remains authoritative and can be edited normally. The
    same connected pack is therefore not copied again unless its content changes
    or the user changes the number of Extender cards while it is connected.
    """
    if pack is None:
        return clips, str(stored_signature or ""), False, False

    prompts = list(pack.get("prompts") or [])
    desired_count = len(prompts)
    signature = str(pack.get("signature") or "")
    count_changed = len(clips) != desired_count
    content_changed = signature != str(stored_signature or "")
    should_import = bool(count_changed or content_changed)

    if not should_import:
        return clips, signature, False, False

    synced = [dict(c) for c in list(clips)[:desired_count]]
    while len(synced) < desired_count:
        synced.append(_default_clip(len(synced)))

    for index, prompt in enumerate(prompts):
        synced[index]["prompt"] = str(prompt)

    return synced, signature, True, count_changed


def _manifest_for_extender(owner_id, fps=24.0):
    return _manifest_for_first(f"extender_{owner_id}", fps)


EXTENDER_PROGRESS_EVENT = "h3_extender_progress"
EXTENDER_LATENT_PREVIEW_EVENT = "h3_extender_latent_preview"
EXTENDER_PROMPT_PACK_EVENT = "h3_extender_prompt_pack_import"


def _send_extender_prompt_pack_import(node_id, clips_json, prompt_count, source=""):
    try:
        server = PromptServer.instance
        if server is None:
            return
        server.send_sync(
            EXTENDER_PROMPT_PACK_EVENT,
            {
                "node": str(node_id),
                "clips_json": str(clips_json),
                "prompt_count": int(prompt_count),
                "source": str(source or "External prompt pack"),
            },
            getattr(server, "client_id", None),
        )
    except Exception:
        # Prompt import UI feedback must never be able to break generation.
        pass


def _send_extender_progress(
    node_id,
    clip_index,
    clip_count,
    phase,
    message="",
):
    """
    Send a tiny live UI event while the single Extender node is still running.

    clip_index is 0-based internally. Use -1 to clear the active card.
    """
    try:
        server = PromptServer.instance
        if server is None:
            return
        payload = {
            "node": str(node_id),
            "clip_index": int(clip_index),
            "clip_count": int(clip_count),
            "phase": str(phase),
            "message": str(message),
        }
        # Target the currently connected execution client when available.
        server.send_sync(
            EXTENDER_PROGRESS_EVENT,
            payload,
            getattr(server, "client_id", None),
        )
    except Exception:
        # Progress UI must never be able to break generation.
        pass


def _send_extender_warning(node_id, message, clip_index=-1, clip_count=0):
    """v14.157: 把"降级 / 回退"这类过去只写控制台的问题推到节点状态栏，
    避免用户拿到低画质成片却不知道原因。"""
    try:
        text = str(message or "").strip()
        if not text:
            return
        print(f"[H3 Extender] WARNING: {text}")
        _send_extender_progress(node_id, clip_index, clip_count, "warning", f"⚠ {text}")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 暂停渲染控制（CLIP 选择生成 + 每 CLIP 间暂停/继续/仅当前/中止）
# ---------------------------------------------------------------------------
_render_ctl_lock = threading.Lock()
_render_ctl = {}


@PromptServer.instance.routes.post("/h3_extender/render_control")
async def render_control(request):
    """前端暂停控制端点：pause / resume / stop_after / abort。"""
    try:
        data = await request.json()
    except Exception:
        data = {}
    node_id = str(data.get("node") or "")
    action = str(data.get("action") or "")
    with _render_ctl_lock:
        ctl = _render_ctl.get(node_id)
        if ctl is None:
            return web.json_response({"ok": True, "state": "idle", "message": "当前无渲染进行"})
        if action == "pause":
            ctl["state"] = "pause_requested"
        elif action == "resume":
            ctl["state"] = "resume"
            ctl["event"].set()
        elif action == "stop_after":
            ctl["state"] = "stop_after"
            ctl["event"].set()
        elif action == "abort":
            ctl["state"] = "abort"
            ctl["event"].set()
            # 立即中断当前采样：终止即时生效，不等当前CLIP跑完
            try:
                comfy.model_management.interrupt_current_processing()
            except Exception as _ie:
                print(f"[H3 Extender] interrupt_current_processing failed: {_ie}")
        else:
            return web.json_response({"ok": False, "error": f"unknown action {action}"})
        return web.json_response({"ok": True, "state": ctl["state"]})


@PromptServer.instance.routes.post("/h3_extender/restore_cache")
async def restore_cache(request):
    """v2.60/v2.62: 恢复最近一次渲染的所有缓存、CLIP成品和预览文件。

    v2.62 改动: 多源 fallback 搜索链快照 (修复 v2.61 硬编码 backup 目录导致
    99% 用户备份找不到的问题). 候选目录按优先级:
      1. <plugin_root>/backup/chain_cache_2026-09-21/  (v2.60 默认)
      2. <plugin_root>/../  (ComfyUI 根)
      3. <plugin_root>/../../  (ComfyUI-BSAI_pro_v36_lig 主项目根, 用户手动放的快照)
      4. 用户主目录下 BSAI_H3_* 快照
    找到 chain_extender_*.h3cache 或 *_chain_snapshot_backup.h3cache 后,
    重命名为符合 _chain_paths() 规范的 chain_{safe_name(node_id)}.h3cache,
    拷贝到 bsai_h3_chain_cache/. 后续 v1.17 前置 latent 链检查会通过,
    clip_select 单选可以从该 CLIP 连续渲染到末尾.
    """
    try:
        data = await request.json()
    except Exception:
        data = {}
    node_id = str(data.get("node") or "")

    plugin_root = Path(__file__).resolve().parents[1]
    comfyui_root = Path(__file__).resolve().parents[2]
    project_root = Path(__file__).resolve().parents[3]
    user_home = Path.home()

    # v2.62: 多源 fallback 搜索链快照备份
    # v1.98: 最高优先级 = 主链目录本身（渲染完成自动快照 *.snapshot.* / 截断前备份 *.preclear.*）
    candidate_dirs = [
        _ensure_cache_root(),                                   # v1.98 主链目录（自动快照/截断备份所在）
        plugin_root / "backup" / "chain_cache_2026-09-21",   # v2.60 默认
        comfyui_root,                                          # ComfyUI 根
        project_root,                                          # 主项目根 (用户放 BSAI_H3_chain_snapshot_backup.* 的地方)
        user_home,                                             # 用户主目录
    ]

    chain_cache_dir = comfyui_root / "bsai_h3_chain_cache"
    temp_dir = _comfyui_temp_dir()

    # v2.62: 重命名映射 — 把任意命名的快照重命名为符合 _chain_paths() 规范的 chain_{safe_name(node_id)}.*
    safe_node = re.sub(r"[^A-Za-z0-9._-]+", "_", node_id).strip("._") or "h3_chain"
    target_stem = f"chain_extender_{safe_node}"

    def _is_readable(path):
        """占用中的文件（如活跃主链被 mmap）不可读时返回 False，跳过该候选。"""
        try:
            with open(path, "rb") as _f:
                _f.read(1)
            return True
        except Exception:
            return False

    def _find_chain_snapshot():
        """在候选目录里找链快照 .h3cache (按候选优先级). 返回 (h3cache_path, json_path_or_None)."""
        for d in candidate_dirs:
            try:
                if not d.exists():
                    continue
                # v1.98 修复: 优先明确的自动备份文件（*.snapshot.* / *.preclear.*），
                # 排除活跃主链 chain_extender_<node>.h3cache（正被 mmap 占用，复制会 WinError 32）。
                for pat, pair in (("*.snapshot.h3cache", "snapshot"), ("*.preclear.h3cache", "preclear")):
                    hits = [p for p in d.glob(pat) if p.name != f"{target_stem}.h3cache" and _is_readable(p)]
                    if hits:
                        h3 = max(hits, key=lambda p: p.stat().st_mtime)
                        jp = Path(str(h3).replace(f".{pair}.h3cache", f".{pair}.json"))
                        return h3, (jp if jp.exists() else None), str(d)
                # 其次: 用户快照 BSAI_H3_chain_snapshot_backup.h3cache
                hits = [p for p in d.glob("*chain_snapshot_backup.h3cache") if p.name != f"{target_stem}.h3cache" and _is_readable(p)]
                if hits:
                    h3 = max(hits, key=lambda p: p.stat().st_mtime)
                    jp = h3.with_suffix(".json")
                    return h3, (jp if jp.exists() else None), str(d)
                # 最后: 任意 chain_*.h3cache（排除活跃主链自身）
                hits = [p for p in d.glob("chain_*.h3cache") if p.name != f"{target_stem}.h3cache" and _is_readable(p)]
                if hits:
                    h3 = max(hits, key=lambda p: p.stat().st_mtime)
                    jp = h3.with_suffix(".json")
                    return h3, (jp if jp.exists() else None), str(d)
            except Exception as _e:
                print(f"[H3 Extender] v2.62 扫描 {d} 出错: {_e}")
        return None, None, None

    # 恢复链缓存
    restored = 0
    snapshot_used = None
    try:
        h3_src, json_src, found_dir = _find_chain_snapshot()
        if h3_src is not None and h3_src.exists():
            chain_cache_dir.mkdir(parents=True, exist_ok=True)
            dst_h3 = chain_cache_dir / f"{target_stem}.h3cache"
            shutil.copy2(h3_src, dst_h3)
            restored += 1
            snapshot_used = str(h3_src)
            # 同步拷贝 .json (若有)
            if json_src is not None and json_src.exists():
                dst_json = chain_cache_dir / f"{target_stem}.json"
                shutil.copy2(json_src, dst_json)
            # v2.72: 写「续渲染标记」——恢复按钮只复制文件, 无法把 validated
            # 标记写进工作流 json。下次渲染主循环检测到该标记后, 以磁盘 manifest
            # 为准同步已渲染段 validated, 跳过已恢复的 CLIP、从下一个继续渲染,
            # 不再从 clip1 全量重渲。标记随本次渲染消费后自动清除。
            try:
                _mk = Path(dst_h3).with_suffix(".restored_marker")
                _mk.write_text(
                    f"restored={h3_src.name}\nnode={node_id}\ntime={time.time()}",
                    encoding="utf-8",
                )
                print(f"[H3 Extender] v2.72 续渲染标记已写入: {_mk.name}")
            except Exception as _me:
                print(f"[H3 Extender] v2.72 续渲染标记写入失败: {_me}")
            print(f"[H3 Extender] v2.62 恢复链缓存: {h3_src.name} ({h3_src.stat().st_size // (1024*1024)} MB) "
                  f"-> {dst_h3.name} (来自 {found_dir}, node={node_id})")
        else:
            tried = [str(d) for d in candidate_dirs if d.exists()]
            print(f"[H3 Extender] v2.62 恢复链缓存: 未找到任何 .h3cache 快照. "
                  f"已扫描: {tried}. 请把 chain_extender_*.h3cache 或 "
                  f"BSAI_H3_chain_snapshot_backup.h3cache 放到 ComfyUI 根目录后重试.")
    except Exception as e:
        print(f"[H3 Extender] v2.62 恢复链缓存失败: {e}")
        return web.json_response({"ok": False, "error": f"Restore chain cache failed: {e}"})

    # 恢复预览文件: 多源 fallback (同时找 _clippv_*.mp4)
    restored_previews = 0
    preview_used_dir = None
    try:
        for d in candidate_dirs:
            if not d.exists():
                continue
            # 优先查 <d>/temp/_clippv_*.mp4
            cand = d / "temp"
            search_roots = [cand] if cand.exists() else []
            # 也允许直接放在 d 下的 _clippv_*.mp4
            search_roots.append(d)
            for root in search_roots:
                hits = list(root.glob("_clippv_*.mp4"))
                if hits:
                    temp_dir.mkdir(parents=True, exist_ok=True)
                    for f in hits:
                        shutil.copy2(f, temp_dir / f.name)
                        restored_previews += 1
                    preview_used_dir = str(root)
                    break
            if restored_previews > 0:
                break
        if restored_previews > 0:
            print(f"[H3 Extender] v2.62 恢复预览文件完成: {restored_previews} 个 (来自 {preview_used_dir})")
    except Exception as e:
        print(f"[H3 Extender] v2.62 恢复预览文件失败: {e}")

    # 统计已渲染的 CLIP 数量
    clips_dir = _clip_output_dir()
    clip_count = len(list(clips_dir.glob(f"h3_clip_{node_id}_*.mp4"))) if clips_dir.exists() else 0

    return web.json_response({
        "ok": True,
        "clips_restored": clip_count,
        "previews_restored": restored_previews,
        "chain_cache_restored": restored,
        "chain_cache_source": snapshot_used,
        "node_id": node_id,
        "target_filename": f"{target_stem}.h3cache",
        "message": (f"恢复完成：{clip_count} 个 CLIP, {restored_previews} 个预览, "
                    f"{restored} 个链缓存文件" + (f" (来自 {snapshot_used})" if snapshot_used else " (未找到链快照)"))
    })


def _register_render_ctl(node_id):
    """开始渲染前注册控制条目（总是重置为运行态）。"""
    with _render_ctl_lock:
        _render_ctl[str(node_id)] = {"state": "running", "event": threading.Event()}


def _release_render_ctl(node_id):
    """渲染结束/中断后清理控制条目。"""
    with _render_ctl_lock:
        _render_ctl.pop(str(node_id), None)


def _maybe_pause_between(node_id, clip_index, loop_end, total, timeout):
    """每个CLIP生成完后、下一个开始前调用。

    仅当用户在前端点过「暂停」时才阻塞；否则立即返回 True。
    返回 True=继续渲染下一个；False=停止后续渲染（保留已生成的CLIP）。
    """
    with _render_ctl_lock:
        ctl = _render_ctl.get(str(node_id))
        if ctl is None or ctl.get("state") != "pause_requested":
            return True
        ctl["state"] = "paused"
        ctl["event"].clear()
    _send_extender_progress(
        node_id, clip_index, total, "paused",
        f"Clip {clip_index + 1} 已生成完成，渲染已暂停 — 可点「继续 / 仅当前 / 中止」，无干预 {int(timeout)}s 后自动继续",
    )
    decided = ctl["event"].wait(timeout)
    with _render_ctl_lock:
        state = ctl.get("state", "running")
        ctl["state"] = "running"
    if not decided:
        _send_extender_progress(
            node_id, clip_index, total, "resumed",
            f"暂停超时无干预 → 自动继续渲染 Clip {clip_index + 2}",
        )
        return True
    if state == "resume":
        _send_extender_progress(
            node_id, clip_index, total, "resumed",
            f"用户点击「继续」→ 渲染 Clip {clip_index + 2}",
        )
        return True
    if state == "stop_after":
        _send_extender_progress(
            node_id, clip_index, total, "stopped",
            "已停止后续渲染：仅保留已生成的 CLIP（可点「合并输出」合成视频）",
        )
        return False
    if state == "abort":
        _send_extender_progress(
            node_id, clip_index, total, "aborted",
            "渲染已中止",
        )
        return False
    return True


def _send_latent_preview_frame(node_id, clip_index, step, total_steps, jpeg_bytes):
    """Send a single latent preview frame (as base64 JPEG) to the frontend."""
    try:
        server = PromptServer.instance
        if server is None or not jpeg_bytes:
            return
        b64 = base64.b64encode(jpeg_bytes).decode("ascii")
        payload = {
            "node": str(node_id),
            "clip_index": int(clip_index),
            "step": int(step),
            "total_steps": int(total_steps),
            "image": "data:image/jpeg;base64," + b64,
        }
        server.send_sync(
            EXTENDER_LATENT_PREVIEW_EVENT,
            payload,
            getattr(server, "client_id", None),
        )
    except Exception as _e:
        print(f"[H3 Extender] _send_latent_preview_frame error: {_e}")


def _project_now_iso():
    return _datetime.datetime.now(_datetime.timezone.utc).isoformat()


def _project_filename(value):
    stem = _safe_name(Path(str(value or "MiniMax_H3_Project")).stem)
    return f"{stem}.ext"


def _project_temp_root():
    root = _ensure_cache_root() / "_projects"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_project_downloads():
    now = time.time()
    stale = []
    for token, info in list(_PROJECT_DOWNLOADS.items()):
        if now - float(info.get("created_at", 0.0)) > PROJECT_DOWNLOAD_TTL_SECONDS:
            stale.append((token, info))
    for token, info in stale:
        _PROJECT_DOWNLOADS.pop(token, None)
        try:
            Path(info.get("path", "")).unlink(missing_ok=True)
        except Exception:
            pass
    # Also clean abandoned downloads left by a previous ComfyUI process where
    # the in-memory token table no longer exists.
    try:
        for path in _project_temp_root().glob("download_*.ext"):
            if now - float(path.stat().st_mtime) > PROJECT_DOWNLOAD_TTL_SECONDS:
                path.unlink(missing_ok=True)
    except Exception:
        pass


def _prompt_pack_signature_from_project_payload(project_payload):
    extender = project_payload.get("extender", {}) if isinstance(project_payload, dict) else {}
    raw = extender.get("clips_json")
    if not isinstance(raw, str) or not raw.strip():
        settings = extender.get("settings", {}) if isinstance(extender, dict) else {}
        raw = settings.get("clips_json") if isinstance(settings, dict) else None
    return _prompt_pack_signature_from_state(raw)


def _clips_from_project_payload(project_payload):
    extender = project_payload.get("extender", {}) if isinstance(project_payload, dict) else {}
    raw = extender.get("clips_json")
    if not isinstance(raw, str) or not raw.strip():
        settings = extender.get("settings", {}) if isinstance(extender, dict) else {}
        raw = settings.get("clips_json") if isinstance(settings, dict) else None
    if not isinstance(raw, str) or not raw.strip():
        clips = extender.get("clips") if isinstance(extender, dict) else None
        if isinstance(clips, list):
            raw = json.dumps({"version": 1, "clips": clips}, ensure_ascii=False)
    if not isinstance(raw, str) or not raw.strip():
        raw = _state_json([_default_clip(0)])
    return _parse_clips_json(raw)


def _project_cache_snapshot(owner_id, project_payload):
    """Return a coherent, immutable manifest snapshot and byte limit.

    The .h3cache is append-only for a live tail. We snapshot the atomically-written
    manifest first, then copy only through the last referenced segment_end. If a
    generation starts concurrently, extra bytes appended after that boundary are
    intentionally excluded from the project.
    """
    data_path, manifest_path = _chain_paths(f"extender_{_safe_name(owner_id)}")
    if not data_path.exists() or not manifest_path.exists():
        return None

    manifest = _load_manifest_from_paths(data_path, manifest_path)
    if manifest is None:
        return None
    manifest = copy.deepcopy(manifest)
    segments = [dict(x) for x in manifest.get("segments", [])]

    # The UI state is the authority for explicit validation. Persist it into the
    # project snapshot without mutating the user's live cache manifest.
    try:
        clips = _clips_from_project_payload(project_payload)
    except Exception:
        clips = []
    for i, desc in enumerate(segments):
        desc["validated"] = bool(i < len(clips) and clips[i].get("validated", False))
    manifest["segments"] = segments

    if segments:
        data_limit = int(segments[-1].get("segment_end", 0))
    else:
        data_limit = int(_DATA_START)
    if data_limit < int(_DATA_START):
        raise ValueError("MiniMax H3 Extender Project: invalid cache byte boundary.")
    if int(data_path.stat().st_size) < data_limit:
        raise IOError("MiniMax H3 Extender Project: cache changed while snapshotting; retry Save Project.")

    return {
        "data_path": data_path,
        "manifest_path": manifest_path,
        "preview_path": _decoded_preview_cache_path(data_path),
        "manifest": manifest,
        "data_limit": data_limit,
    }


def _zip_write_prefix(zf, arcname, source_path, byte_limit):
    source_path = Path(source_path)
    remaining = int(byte_limit)
    info = zipfile.ZipInfo(str(arcname))
    info.compress_type = zipfile.ZIP_STORED
    info.date_time = time.localtime(source_path.stat().st_mtime)[:6]
    with open(source_path, "rb") as src, zf.open(info, "w", force_zip64=True) as dst:
        while remaining > 0:
            chunk = src.read(min(PROJECT_COPY_CHUNK, remaining))
            if not chunk:
                raise IOError(
                    f"MiniMax H3 Extender Project: source cache ended {remaining} byte(s) early."
                )
            dst.write(chunk)
            remaining -= len(chunk)


def _build_project_archive(owner_id, requested_name, project_payload, output_path):
    project_payload = copy.deepcopy(project_payload)
    refs = _refs_from_project_payload(project_payload)
    refs = _write_refs_to_project_payload(project_payload, refs)

    # A portable project is only useful when every referenced image is actually
    # embedded. Fail loudly instead of silently writing a project that depends on
    # a local cache entry which may not exist on the destination machine.
    ref_files = []
    source_ref_files = []
    for index, ref in enumerate(refs, start=1):
        if ref is None:
            continue
        path = _ref_path(ref.get("id"))
        if not path.exists():
            raise FileNotFoundError(
                f"MiniMax H3 Extender Project: reference {index} is missing from the internal store. "
                "Reload that reference image before saving the project."
            )
        width, height = _validate_reference_file(path)
        ref["width"] = int(width)
        ref["height"] = int(height)
        ref["size_bytes"] = int(path.stat().st_size)
        ref_files.append((index, ref, path))

        # If the visible ref is an edited derivative, also embed the immutable
        # source pixels. This keeps Reset meaningful after Save/Load and on
        # another machine.
        source_id = str(ref.get("source_id") or ref.get("id") or "").lower().strip()
        if source_id != str(ref.get("id") or "").lower().strip():
            source_path = _ref_path(source_id)
            if not source_path.exists():
                raise FileNotFoundError(
                    f"MiniMax H3 Extender Project: original source for reference {index} is missing. "
                    "Reload that reference image before saving the project."
                )
            _validate_reference_file(source_path)
            source_ref_files.append((index, source_id, source_path))
    _write_refs_to_project_payload(project_payload, refs)

    snapshot = _project_cache_snapshot(owner_id, project_payload)

    if snapshot is not None:
        cache_resolution = _resolution_from_manifest(snapshot.get("manifest"))
        if cache_resolution is not None:
            extender_payload = project_payload.setdefault("extender", {})
            resolution = extender_payload.setdefault("resolution", {})
            if isinstance(resolution, dict):
                resolution["resolved_width"] = int(cache_resolution["width"])
                resolution["resolved_height"] = int(cache_resolution["height"])
                resolution["source"] = "disk_cache"

    archive_meta = {
        "format": PROJECT_FORMAT,
        "format_version": PROJECT_FORMAT_VERSION,
        "created_at": _project_now_iso(),
        "extender_build": BUILD,
        "cache_version": CACHE_VERSION,
        "source_owner_id": str(owner_id),
        "project_name": Path(_project_filename(requested_name)).stem,
        "project": project_payload,
        "references": {
            "count": int(len(ref_files)),
            "embedded": True,
            "original_sources": int(len(source_ref_files)),
        },
        "cache": {
            "present": snapshot is not None,
            "clip_count": int(len(snapshot["manifest"].get("segments", []))) if snapshot else 0,
            "frame_count": int(snapshot["manifest"].get("final_frame_count", 0)) if snapshot else 0,
            "has_committed_preview": bool(snapshot and snapshot["preview_path"].exists()),
        },
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        project_bytes = json.dumps(
            archive_meta,
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")
        zf.writestr("project.json", project_bytes, compress_type=zipfile.ZIP_DEFLATED)

        for index, ref, path in ref_files:
            zf.write(
                path,
                arcname=f"refs/ref_{index}.png",
                compress_type=zipfile.ZIP_STORED,
            )
        for index, source_id, source_path in source_ref_files:
            zf.write(
                source_path,
                arcname=f"refs/original_ref_{index}.png",
                compress_type=zipfile.ZIP_STORED,
            )

        if snapshot is not None:
            manifest_bytes = json.dumps(
                snapshot["manifest"],
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            zf.writestr("cache/chain.json", manifest_bytes, compress_type=zipfile.ZIP_DEFLATED)
            _zip_write_prefix(
                zf,
                "cache/chain.h3cache",
                snapshot["data_path"],
                snapshot["data_limit"],
            )
            if snapshot["preview_path"].exists():
                zf.write(
                    snapshot["preview_path"],
                    arcname="cache/chain.preview.mp4",
                    compress_type=zipfile.ZIP_STORED,
                )
    return archive_meta

def _safe_zip_member(name):
    value = str(name or "").replace("\\", "/")
    if not value or value.startswith("/"):
        return False
    parts = [p for p in value.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return False
    return True


def _zip_copy_member(zf, member_name, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zf.open(member_name, "r") as src, open(destination, "wb") as dst:
        while True:
            chunk = src.read(PROJECT_COPY_CHUNK)
            if not chunk:
                break
            dst.write(chunk)
        dst.flush()
        os.fsync(dst.fileno())


def _replace_cache_transaction(owner_id, new_data=None, new_manifest=None, new_preview=None):
    target_data, target_manifest = _chain_paths(f"extender_{_safe_name(owner_id)}")
    target_preview = _decoded_preview_cache_path(target_data)
    target_preview_video = _decoded_preview_video_cache_path(target_data)
    # The video-only preview prefix is a derived v14.42 sidecar. It is not
    # required in .ext archives, but it MUST be cleared on project replacement
    # so a previous project's prefix can never be reused accidentally.
    # v1.100: 导入/替换前持久备份保护。v1.97 的 preclear 备份只覆盖 truncate 路径,
    # 项目导入路径(_replace_cache_transaction)在"导入空包"(new_data=None)或误导入时,
    # 旧链先被移到临时备份、随后随事务成功被删除——整链静默丢失。
    # 事务前对"旧链非空"做持久备份(preclear 风格, 留 3 份), 事务成败都不删。
    try:
        if target_data.exists() and target_data.stat().st_size > 0 and target_manifest.exists():
            _backup_chain_before_truncate(target_data, target_manifest, reason="project-import")
    except Exception as _be:
        print(f"[H3 Extender] v1.100 导入前备份失败(忽略, 继续导入): {_be}")

    targets = [target_data, target_manifest, target_preview, target_preview_video]
    backups = []
    token = uuid.uuid4().hex[:10]

    try:
        for target in targets:
            if target.exists():
                backup = target.with_name(target.name + f".project_backup_{token}")
                os.replace(target, backup)
                backups.append((target, backup))

        if new_data is not None and new_manifest is not None:
            os.replace(str(new_data), target_data)
            os.replace(str(new_manifest), target_manifest)
            if new_preview is not None and Path(new_preview).exists():
                os.replace(str(new_preview), target_preview)
        # No imported cache means an intentionally empty project. The old cache
        # remains only in backups until this transaction succeeds.
    except Exception:
        for target in targets:
            try:
                target.unlink(missing_ok=True)
            except Exception:
                pass
        for target, backup in reversed(backups):
            if backup.exists():
                os.replace(backup, target)
        raise
    else:
        for _, backup in backups:
            try:
                backup.unlink(missing_ok=True)
            except Exception:
                pass


def _import_project_archive(owner_id, archive_path):
    archive_path = Path(archive_path)
    work_root = _project_temp_root() / f"import_{uuid.uuid4().hex}"
    work_root.mkdir(parents=True, exist_ok=True)
    new_data = work_root / "chain.h3cache"
    new_manifest = work_root / "chain.json"
    new_preview = work_root / "chain.preview.mp4"

    try:
        with zipfile.ZipFile(archive_path, "r", allowZip64=True) as zf:
            for info in zf.infolist():
                if not _safe_zip_member(info.filename):
                    raise ValueError(
                        f"MiniMax H3 Extender Project: unsafe ZIP entry '{info.filename}'."
                    )

            names = set(zf.namelist())
            if "project.json" not in names:
                raise ValueError("MiniMax H3 Extender Project: project.json is missing.")
            pinfo = zf.getinfo("project.json")
            if int(pinfo.file_size) > PROJECT_JSON_MAX_BYTES:
                raise ValueError("MiniMax H3 Extender Project: project.json is unexpectedly large.")

            with zf.open("project.json", "r") as f:
                archive_meta = json.loads(f.read().decode("utf-8"))
            if archive_meta.get("format") != PROJECT_FORMAT:
                raise ValueError("MiniMax H3 Extender Project: unsupported project file.")
            format_version = int(archive_meta.get("format_version", -1))
            if format_version not in PROJECT_SUPPORTED_VERSIONS:
                supported = ", ".join(str(v) for v in sorted(PROJECT_SUPPORTED_VERSIONS))
                raise ValueError(
                    "MiniMax H3 Extender Project: incompatible project format "
                    f"{format_version} (supported: {supported})."
                )

            project_payload = archive_meta.get("project", {})
            if not isinstance(project_payload, dict):
                raise ValueError("MiniMax H3 Extender Project: invalid project metadata.")
            clips = _clips_from_project_payload(project_payload)
            project_prompt_pack_signature = _prompt_pack_signature_from_project_payload(project_payload)

            # v2 embeds the real reference pixels. Import each image into the
            # Extender's content-addressed store and rewrite the returned project
            # metadata to the local ids. v1 projects remain fully loadable; they
            # simply have no embedded internal references.
            saved_refs = _refs_from_project_payload(project_payload)
            imported_refs = _empty_refs()
            if format_version >= 2:
                for index in range(1, MAX_IMAGE_REFS + 1):
                    member = f"refs/ref_{index}.png"
                    saved = saved_refs[index - 1]
                    if member not in names:
                        if saved is not None:
                            raise ValueError(
                                f"MiniMax H3 Extender Project: embedded reference {index} is missing."
                            )
                        continue
                    ref_info = zf.getinfo(member)
                    if int(ref_info.file_size) > MAX_REF_UPLOAD_BYTES:
                        raise ValueError(
                            f"MiniMax H3 Extender Project: reference {index} exceeds the allowed image size."
                        )
                    extracted = work_root / f"ref_{index}.png"
                    _zip_copy_member(zf, member, extracted)
                    desc = _store_project_reference(
                        extracted,
                        (saved or {}).get("original_name") if isinstance(saved, dict) else f"ref_{index}.png",
                    )
                    if isinstance(saved, dict) and saved.get("id") and desc["id"] != saved.get("id"):
                        raise ValueError(
                            f"MiniMax H3 Extender Project: reference {index} failed its integrity check."
                        )

                    saved_source_id = (
                        str(saved.get("source_id") or saved.get("id") or desc["id"]).lower().strip()
                        if isinstance(saved, dict)
                        else desc["id"]
                    )
                    source_member = f"refs/original_ref_{index}.png"
                    if source_member in names:
                        source_info = zf.getinfo(source_member)
                        if int(source_info.file_size) > MAX_REF_UPLOAD_BYTES:
                            raise ValueError(
                                f"MiniMax H3 Extender Project: original reference {index} exceeds the allowed image size."
                            )
                        source_extracted = work_root / f"original_ref_{index}.png"
                        _zip_copy_member(zf, source_member, source_extracted)
                        source_desc = _store_project_reference(
                            source_extracted,
                            (saved or {}).get("original_name") if isinstance(saved, dict) else f"ref_{index}.png",
                        )
                        if _ref_id_is_safe(saved_source_id) and source_desc["id"] != saved_source_id:
                            raise ValueError(
                                f"MiniMax H3 Extender Project: original reference {index} failed its integrity check."
                            )
                        desc["source_id"] = source_desc["id"]
                    else:
                        # v2 projects created before v14.49 only embedded the
                        # currently used pixels. They remain loadable; that image
                        # becomes their reset baseline because the older archive
                        # contains no recoverable original.
                        desc["source_id"] = desc["id"]

                    if isinstance(saved, dict) and desc["source_id"] != desc["id"]:
                        for key in ("saturation", "contrast", "brightness"):
                            try:
                                desc[key] = max(0.0, min(200.0, float(saved.get(key, 100) or 100)))
                            except Exception:
                                desc[key] = 100.0
                    imported_refs[index - 1] = desc
                imported_refs = _normalize_ref_descriptors(imported_refs)
            _write_refs_to_project_payload(project_payload, imported_refs)

            has_data = "cache/chain.h3cache" in names
            has_manifest = "cache/chain.json" in names
            if has_data != has_manifest:
                raise ValueError("MiniMax H3 Extender Project: incomplete cache payload.")

            imported_manifest = None
            if has_data:
                _zip_copy_member(zf, "cache/chain.h3cache", new_data)
                _zip_copy_member(zf, "cache/chain.json", new_manifest)
                if "cache/chain.preview.mp4" in names:
                    _zip_copy_member(zf, "cache/chain.preview.mp4", new_preview)

                imported_manifest = _load_manifest_from_paths(new_data, new_manifest)
                if imported_manifest is None:
                    raise ValueError("MiniMax H3 Extender Project: cache manifest is empty.")

                # A hand-edited project may contain fewer cards than cached clips.
                # Keep only the portable prefix represented by the saved UI state.
                if len(imported_manifest.get("segments", [])) > len(clips):
                    imported_manifest = _truncate_chain(
                        new_data,
                        new_manifest,
                        imported_manifest,
                        len(clips),
                    )

                segments = [dict(x) for x in imported_manifest.get("segments", [])]
                for i, desc in enumerate(segments):
                    desc["validated"] = bool(i < len(clips) and clips[i].get("validated", False))
                imported_manifest = dict(imported_manifest)
                imported_manifest["segments"] = segments
                imported_manifest["owner_id"] = f"extender_{_safe_name(owner_id)}"
                imported_manifest["imported_at"] = time.time()
                imported_manifest["updated_at"] = time.time()
                _write_json_atomic(new_manifest, imported_manifest)

                imported_resolution = _resolution_from_manifest(imported_manifest)
                if imported_resolution is not None:
                    extender_payload = project_payload.setdefault("extender", {})
                    resolution = extender_payload.setdefault("resolution", {})
                    if isinstance(resolution, dict):
                        resolution["resolved_width"] = int(imported_resolution["width"])
                        resolution["resolved_height"] = int(imported_resolution["height"])
                        resolution["source"] = "disk_cache"

            cached_count = int(len(imported_manifest.get("segments", []))) if imported_manifest else 0
            # A clip can only remain validated when its physical cached segment is
            # present. Normalize the returned UI state accordingly.
            for i in range(cached_count, len(clips)):
                clips[i]["validated"] = False
            found_open = False
            for clip_cfg in clips:
                if found_open:
                    clip_cfg["validated"] = False
                elif not clip_cfg["validated"]:
                    found_open = True

            normalized_clips_json = _state_json(clips, project_prompt_pack_signature)
            extender_payload = project_payload.setdefault("extender", {})
            extender_payload["clips_json"] = normalized_clips_json
            extender_payload["clips"] = clips
            settings = extender_payload.setdefault("settings", {})
            if isinstance(settings, dict):
                settings["clips_json"] = normalized_clips_json

            _replace_cache_transaction(
                owner_id,
                new_data if imported_manifest is not None else None,
                new_manifest if imported_manifest is not None else None,
                new_preview if imported_manifest is not None and new_preview.exists() else None,
            )

            validated_count = 0
            if imported_manifest is not None:
                for desc in imported_manifest.get("segments", []):
                    if not bool(desc.get("validated", False)):
                        break
                    validated_count += 1

            loaded_resolution = _resolution_from_manifest(imported_manifest)
            return {
                "project_name": str(archive_meta.get("project_name") or archive_path.stem),
                "project": project_payload,
                "references": {
                    "count": int(_reference_count(imported_refs)),
                    "refs_json": _refs_json(imported_refs),
                },
                "cache": {
                    "present": imported_manifest is not None,
                    "cached_count": cached_count,
                    "validated_count": int(validated_count),
                    "frame_count": int(imported_manifest.get("final_frame_count", 0)) if imported_manifest else 0,
                    "resolved_width": int(loaded_resolution["width"]) if loaded_resolution else 0,
                    "resolved_height": int(loaded_resolution["height"]) if loaded_resolution else 0,
                },
            }
    finally:
        shutil.rmtree(work_root, ignore_errors=True)



def _bsai_list_semantic_bridge_adapters():
    """INPUT_TYPES 用: 列 models/semantic_bridge/ 下的语义桥权重, 至少返回占位项."""
    try:
        import os as _os_sb3, importlib.util as _ilu_sb3
        _sb_path = _os_sb3.path.join(_os_sb3.path.dirname(_os_sb3.path.abspath(__file__)),
                                     "bsai_h3_semantic_bridge.py")
        _sb_spec = _ilu_sb3.spec_from_file_location("bsai_h3_semantic_bridge", _sb_path)
        _sb = _ilu_sb3.module_from_spec(_sb_spec)
        _sb_spec.loader.exec_module(_sb)
        return _sb.list_adapters()
    except Exception:
        return ["(off: no weights)"]


def _bsai_list_upscale_models():
    """INPUT_TYPES 用: 列 models/upscale_models/ 下的超分模型, 至少返回占位项."""
    try:
        import folder_paths as _fp_u
        names = list(_fp_u.get_filename_list("upscale_models"))
        names = [n for n in names if n.lower().endswith((".pth", ".pt", ".safetensors", ".onnx", ".bin"))]
        if names and "realesr-general-x4v3.pth" not in names:
            names.insert(0, "realesr-general-x4v3.pth")
        return names or ["realesr-general-x4v3.pth"]
    except Exception:
        return ["realesr-general-x4v3.pth"]


# ---------------------------------------------------------------------------
# v14.221 保脸-小脸修复：复用本机 BSAI-ComfyUI-FaceRefine 引擎。
# 视频(BV133nh6fEMm)方案 = H3 FaceRefine 局部人脸重绘：检测裁剪人脸 -> H3 潜空间
# 重绘 -> 逐帧去噪 -> 羽化缝合回原帧。远景小脸崩坏时全帧 H3 会结构塌陷（脸太小，
# 放大后无足够像素重建五官）；局部裁剪到 ~768 画布并自动用视频里的近景大脸做
# ref2v 锚点后，H3 有清晰参考即可还原完整五官。这里把该引擎接到电影工厂出片前的
# 分镜段，作为「小脸修复」后处理。任何异常/无人脸都原样返回，绝不破坏画面。
# ---------------------------------------------------------------------------
_FR_ENGINE = None
_FR_ENGINE_ERR = None
_FR_DETECTOR = None


def _ff_face_detector():
    """从本机已装的 ultralytics bbox 模型里挑一个可用的人脸检测器。"""
    global _FR_DETECTOR
    if _FR_DETECTOR:
        return _FR_DETECTOR
    _FR_DETECTOR = "face_yolov8m.pt"
    try:
        import folder_paths as _fp
        _cands = ["face_yolov8m.pt", "face_yolov8s.pt", "face_yolov8n.pt", "face_yolov9c.pt"]
        for _key in ("ultralytics_bbox", "ultralytics"):
            try:
                _names = set(_fp.get_filename_list(_key))
            except Exception:
                _names = set()
            for _c in _cands:
                if _c in _names:
                    _FR_DETECTOR = _c
                    return _FR_DETECTOR
    except Exception:
        pass
    return _FR_DETECTOR


def _load_facerefine_engine():
    """延迟加载 BSAI-ComfyUI-FaceRefine 插件的 BSAIFaceRefine 节点类（复用其完整链路）。"""
    global _FR_ENGINE, _FR_ENGINE_ERR
    if _FR_ENGINE is not None:
        return _FR_ENGINE
    if _FR_ENGINE_ERR is not None:
        raise _FR_ENGINE_ERR
    import importlib.util as _ilu
    _base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _path = os.path.join(_base, "BSAI-ComfyUI-FaceRefine", "nodes.py")
    if not os.path.isfile(_path):
        _FR_ENGINE_ERR = FileNotFoundError("BSAI-ComfyUI-FaceRefine 插件未安装，小脸修复跳过。")
        raise _FR_ENGINE_ERR
    try:
        _spec = _ilu.spec_from_file_location("bsai_ff_facerefine", _path)
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        _FR_ENGINE = _mod.NODE_CLASS_MAPPINGS.get("BSAIFaceRefine")
        if _FR_ENGINE is None:
            _FR_ENGINE_ERR = RuntimeError("BSAI FaceRefine 节点未注册。")
            raise _FR_ENGINE_ERR
    except Exception as _e:
        _FR_ENGINE_ERR = _e
        raise _FR_ENGINE_ERR
    return _FR_ENGINE


def _ff_run_segment_face_refine(frames, model, clip, vae, audio_vae):
    """对单个分镜的解码帧 [T,H,W,C] 做 H3 局部人脸重绘并返回重绘后的帧。

    复用 BSAIFaceRefine 单节点完整链路（自动检测最大脸 + 小脸自动降倍 + 近景锚点
    ref2v + 逐帧去噪 + 羽化缝合）。任何异常或不适用都原样返回，保证不破坏出片。
    """
    if frames is None or int(getattr(frames, "shape", [0])[0]) == 0:
        return frames
    try:
        _cls = _load_facerefine_engine()
        _node = _cls()
        _refined, _report, _faces = _node.run(
            images=frames,
            model=model,
            clip=clip,
            vae=vae,
            audio_vae=audio_vae,
            detector=_ff_face_detector(),
            steps=8,
            denoise=0.35,
            canvas_size=768,
            small_face_denoise=1.0,
            confidence=0.35,
            crop_factor=2.5,
            smooth_window=21,
            scheduler="beta",
            sampler_name="euler",
            seed=0,
            prompt=("ultra high definition close-up of a human face, crystal clear facial details, "
                    "natural realistic skin texture, sharp detailed eyes, correct natural facial "
                    "features, photorealistic, professional portrait quality"),
            enable_audio_lock=False,
            paste_region="face_ellipse",
            mask_dilation=24,
            feather=24,
            colour_match=1.0,
            blend=1.0,
            stage2_enable=False,
            undetected_frames="fade_out",
            person_fallback=False,
            use_npu_face_detect=True,
        )
        if _faces and _refined is not None and getattr(_refined, "shape", None) == getattr(frames, "shape", None):
            print("[H3 Extender] 小脸修复：%d 张人脸已重绘 | %s" % (_faces, (str(_report) or "")[:160].replace("\n", " ")))
            return _refined
        return frames
    except Exception as _e:
        print("[H3 Extender] ⚠️ 小脸修复跳过（不影响出片）: %s" % _e)
        return frames


# ---------------------------------------------------------------------------
# v14.340 音频引导人脸/嘴型修复（TaoMate-FVSR 后处理档）
#
# 来源：淘宝直播团队 2026-11-02 开源的 TaoMate-FVSR（arXiv 2611.03393），
# 教程视频 BV1WrxS6UEDm。它和「超分/小脸修复」的关键差别是用音频引导嘴部重建：
#   · 原声模式：在保留画面结构的同时重建不可信的牙齿/嘴唇细节（LPIPS/DISTS 最低）
#   · 配音模式：给一段新语音，重建的嘴型直接对齐新语音（Sync-C 明显高于
#     "超分后再跑单独 dubbing 模型"的所有基线）
# 官方 ComfyUI 分支把链路拆成 5 个节点：Load Model → Prepare Video →
# GPEN Reference (CPU) → Restore Face Video → Save/Paste Back Video。整段视频
# 用 YOLO 裁脸、修复、直方图匹配 + 羽化贴回，场景/身体不动，输出保持原尺寸。
#
# 本档是「出片前逐分镜后处理」：直接串官方节点类，不重复实现模型代码。
# 所有参数走环境变量，避免往节点 widget 列表里加新控件（会错位老工作流布局）。
# ---------------------------------------------------------------------------
_FVRS_ENGINE = None
_FVRS_ENGINE_ERR = None


def _fvrs_env(name, default, cast=float):
    try:
        return cast(os.environ.get(name, default))
    except Exception:
        return default


def _fvrs_cfg():
    """从环境变量读修复参数；默认值即官方教程/README 的推荐值。"""
    return {
        "steps": _fvrs_env("BSAI_FVRS_STEPS", 10, int),
        "noise": _fvrs_env("BSAI_FVRS_NOISE", 0.8),
        "shift": _fvrs_env("BSAI_FVRS_SHIFT", 5.0),
        "audio_cfg": _fvrs_env("BSAI_FVRS_AUDIO_CFG", 4.0),
        "ref_cfg": _fvrs_env("BSAI_FVRS_REF_CFG", 1.7),
        "budget_gib": _fvrs_env("BSAI_FVRS_BUDGET", 15.0),
        "crop_scale": _fvrs_env("BSAI_FVRS_CROP_SCALE", 0.8),
        "seed": _fvrs_env("BSAI_FVRS_SEED", 42, int),
    }


def _load_fvrs_engine():
    """按文件路径加载官方 ComfyUI-TaoMate-FVSR 节点模块（延迟，未装不报错到启动阶段）。"""
    global _FVRS_ENGINE, _FVRS_ENGINE_ERR
    if _FVRS_ENGINE is not None:
        return _FVRS_ENGINE
    if _FVRS_ENGINE_ERR is not None:
        raise _FVRS_ENGINE_ERR
    import importlib.util as _ilu
    _base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _dir = os.path.join(_base, "ComfyUI-TaoMate-FVSR")
    _path = os.path.join(_dir, "nodes.py")
    if not os.path.isfile(_path):
        _FVRS_ENGINE_ERR = FileNotFoundError(
            "TaoMate-FVSR 插件未安装（custom_nodes/ComfyUI-TaoMate-FVSR），已跳过音频引导修复。"
        )
        raise _FVRS_ENGINE_ERR
    try:
        # 官方节点用的是相对导入（from .node_io import ...），且目录名带连字符不能直接
        # import，因此按「包规格 + 搜索路径」加载，并在 sys.modules 里先注册包名。
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location("bsai_fvrs_pkg", _path, submodule_search_locations=[_dir])
        if _spec is None or _spec.loader is None:
            raise ImportError(f"无法加载 TaoMate-FVSR 包规格: {_path}")
        _mod = _ilu.module_from_spec(_spec)
        import sys as _sys
        _sys.modules["bsai_fvrs_pkg"] = _mod
        _spec.loader.exec_module(_mod)
        _FVRS_ENGINE = _mod
    except Exception as _e:
        _FVRS_ENGINE_ERR = _e
        raise _FVRS_ENGINE_ERR
    return _FVRS_ENGINE


def _fvrs_gpen_repo():
    """GPEN 源码目录（不是权重目录）。缺失时退化为「首帧裁剪原图」当参考。"""
    cand = os.environ.get("BSAI_FVRS_GPEN_REPO", "").strip()
    if cand and os.path.isdir(cand):
        return cand
    try:
        import folder_paths as _fp
        _models = Path(_fp.models_dir)
    except Exception:
        _models = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))).parent / "models"
    for _c in (Path(_models) / "TaoMate-GPEN-source",
               Path(_models) / "TaoMate-FVSR" / "GPEN",
               Path(_models) / "GPEN"):
        if _c.is_dir():
            return str(_c)
    return ""


def _fvrs_detector_path():
    cand = os.environ.get("BSAI_FVRS_DETECTOR", "").strip()
    if cand and os.path.isfile(cand):
        return cand
    try:
        import folder_paths as _fp
        _models = Path(_fp.models_dir)
    except Exception:
        return ""
    for _c in (Path(_models) / "TaoMate-FVSR" / "face_yolov8n.pt",
               Path(_models) / "ultralytics" / "face_yolov8n.pt",
               Path(_models) / "ultralytics" / "face_yolov8m.pt"):
        if _c.is_file():
            return str(_c)
    return ""


def _ff_fvrs_retime(path, fps=24.0):
    """官方链路一律按 25fps 解码/编码；回到出片帧率，避免拼接/音画时长漂移。"""
    try:
        fps = float(fps)
    except Exception:
        fps = 24.0
    if abs(fps - 25.0) < 0.05:
        return path
    try:
        ff = _find_ffmpeg()
    except Exception:
        ff = None
    if not ff:
        return path
    out = str(path).replace(".mp4", f"_r{int(round(fps))}.mp4")
    cmd = [ff, "-y", "-i", str(path), "-vf", f"fps={fps:g}", "-c:v", "libx264",
           "-preset", "fast", "-crf", "17", "-pix_fmt", "yuv420p",
           "-c:a", "copy", "-movflags", "+faststart", out]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=900)
        return out
    except Exception as _e:
        print("[H3 Extender] ⚠️ FVSR 输出回转 %.0ffps 失败，沿用 25fps 结果: %s" % (fps, _e))
        return path


def _ff_fvrs_restore_clip(clip_path, fps=24.0, log=print):
    """对单个分镜 mp4 跑一次「音频引导人脸/嘴型修复」，返回修复后的 mp4 路径。

    官方约束：单人单镜、单帧人脸 512 推理、25fps 解码。这里对分镜逐个处理，
    正好落在「一镜一段」的边界上；任何异常都原样返回原片段，绝不阻断出片。
    """
    if not clip_path or not os.path.isfile(str(clip_path)):
        return clip_path
    try:
        nodes = _load_fvrs_engine()
        cfg = _fvrs_cfg()
        local_dir = os.environ.get("BSAI_FVRS_LOCAL_DIR", "").strip()
        model_dir = nodes.resolve_model_dir("(root)", local_dir)
        # 直接把解析出的目录作为 local_directory 传入，避免 selection 名再被拼一次子目录
        handle = nodes.TaoMateModelLoader().load("(root)", str(model_dir), cfg["budget_gib"])[0]
        video_path = str(clip_path)
        prep, first_crop = nodes.TaoMatePrepareVideo().prepare(
            video_path, "", "yolo_face", 0, 0, 512, 0,
            detector_path=_fvrs_detector_path(), crop_scale=cfg["crop_scale"],
        )
        gpen = _fvrs_gpen_repo()
        if gpen:
            reference = nodes.TaoMateGPENReference().enhance(first_crop, handle, gpen, cfg["seed"])[0]
        else:
            # 没有 GPEN 源码时用首帧裁剪原图当参考（官方 cropped-face 协议），
            # 细节增益弱于默认 GPEN 参考，但不会阻断出片。
            reference = first_crop
            log("[H3 Extender] TaoMate-FVSR: 未找到 GPEN 源码，改用首帧裁剪原图作参考（弱化模式）")
        result = nodes.TaoMateRestore().restore(
            handle, prep, reference, cfg["seed"], cfg["steps"], cfg["noise"],
            cfg["shift"], cfg["audio_cfg"], cfg["ref_cfg"],
        )[0]
        stem = os.path.splitext(os.path.basename(video_path))[0][:40]
        saved = nodes.TaoMateSaveVideo().save(result, "taomate_fvrs/" + stem)["result"][0]
        saved = _ff_fvrs_retime(saved, fps)
        log("[H3 Extender] 🎙️ TaoMate-FVSR 修复完成: %s (%d 帧, %d 步, audio_cfg=%.1f, ref_cfg=%.1f)"
            % (os.path.basename(str(saved)), len(prep.crops), cfg["steps"], cfg["audio_cfg"], cfg["ref_cfg"]))
        return saved
    except Exception as _e:
        print("[H3 Extender] ⚠️ TaoMate-FVSR 跳过（不影响出片）: %s" % _e)
        return clip_path


def _ff_fvrs_apply_clips(clip_paths, fps, cache=None, log=print):
    """逐段跑 FVSR；同一分镜只跑一次（per-clip 输出与 merged 输出复用结果）。"""
    if not clip_paths:
        return clip_paths
    cache = cache if cache is not None else {}
    out = []
    for _i, _cp in enumerate(clip_paths):
        _key = str(_cp)
        if _key not in cache:
            cache[_key] = _ff_fvrs_restore_clip(_cp, fps, log=log)
        out.append(cache[_key])
    return out


# v14.259: 下拉标签全面英文化(ComfyUI-Manager 上架复审要求: 列表只放英文)。
# 老工作流里序列化的中文值经 VALIDATE_INPUTS 放行后, 在 extend() 入口用下列
# 映射归一回旧中文内部值, 下游所有判断分支(渲染管道 elif 链/速度档/双采档)零改动;
# 新英文标签同样在此映射回中文内部值, 两套标签完全等价。
_RENDER_PIPELINE_EN2ZH = {
    "Sol-H3 Self-Lift Dual-Pass (default)": "Sol-H3 Self-Lift 双采 (默认)",
    "MV Dual-Pass (Film Factory v3.2 original)": "MV Dual-Pass (电影工厂 v3.2 原版)",
    "Live Dub HD (audio 12+ steps)": "直播配音高清（音频≥12步）",
    "FastH3 4-step VSA": "FastH3-4步VSA",
    "DMAD 4-step": "DMAD-4步",
    "Action Combo": "武戏组合拳",
    "4K Direct Secret Sauce": "4K直出 秘制酱料",
    "FastH3 Omni 8-step Single-Pass": "FastH3 Omni 8步单采",
    "Dual-Pass 2K (HyperVAE 2x decode)": "双采2K（HyperVAE 2x 解码）",
    "QAD-v2 8-step": "QAD-v2-8步",
    "Live Commerce 01 Text Dubbing (no audio inputs)": "直播带货·01 纯文本配音（三口不接）",
    "Live Commerce 02 ref_audio Voice Reference": "直播带货·02 ref_audio音色参考配音（只接参考）",
    "Live Commerce 03 lip_voice Lip-Sync": "直播带货·03 lip_voice对口型（只接现成主播音频）",
    "Live Commerce (fully automatic)": "直播带货（全自动）",
    "FastH3 Omni x SelfLift Upscale": "FastH3 Omni × SelfLift 超分",
    "H25 Hybrid 8-step Multi-Ref Single-Pass": "H25 Hybrid 8步 多参考单采",
    "4K Regenerate OpenH3Regenerate2K (768P draft to 2560)": "4K重生成 OpenH3Regenerate2K (768P草稿直出2560)",
    "PRISM 10-step Motion Single-Pass (Singularity v2 x 10Eros-Max)": "PRISM 10步 运动强化单采 (Singularity v2 × 10Eros-Max)",
    "Transparent Video Single-Pass Keying (H3 Transparent)": "透明视频 单采抠像 (H3 Transparent)",
    "4-in-1 Ultimate Speedup (DMAD 8-step + SelfLift 6+2 + half-res refs + SegAttention)": "4合1终极加速 (DMAD 8步 SelfLift 6+2 + 参考降分 + SegAttention)",
    "SolarRenderer Structure Control (control LoRA + 4-step LoRA)": "SolarRenderer 结构控制 (控制LoRA + 4步LoRA 逐帧驱动)",
    "Director Turbo Dual-Pass (MiniMaxH3 Director port)": "Director 极速双采 (MiniMaxH3 Director 移植)",
    "Dual-Pass 2K (official condition upscale)": "双采2K（官方条件放大）",
    "PDMD 4-step SelfLift Dual-Pass (4+2)": "PDMD 4步 SelfLift 双采 (4+2)",
    "PDMD 2-step Turbo Draft (single-pass)": "PDMD 2步 极速试稿 (单采)",
    "PTD 4-step Ref2VA Single-Pass (reference accel)": "PTD 4步 Ref2VA 单采 (参考图加速)",
    # v14.387 (2026-11-12): ACC 8 步加速档 —— 用户口径 1 采 8 步 + 2 采 4 步;
    # 权重在 models\loras\H3\H3加速\ACC\(Ref2VA 版 + FL2VA 版)。
    "ACC 8-step SelfLift Dual-Pass (8+4)": "ACC 8步 SelfLift 双采 (8+4)",
    "PIKA H3 Flex 6+2 SelfLift Dual-Pass (Ref2VA face-lock)": "PIKA H3 Flex 6+2 双采 (Ref2VA 锁脸)",
    # v14.366 (2026-11-10): PIKA 真双采档（一采 8 步 + 二采 4 步）。
    "PIKA H3 Flex 8+2 SelfLift Dual-Pass (Ref2VA face-lock)": "PIKA H3 Flex 8步+2步 双采 (Ref2VA 锁脸)",
    "TaoMate HD 3-Step Progressive Lift Dual-Pass (2+1, 1080p direct)": "TaoMate HD 3步 渐进放大双采 (2+1 1080p直出)",
    "TaoMate HD 8+4 Progressive Lift Dual-Pass (8+4, 1080p direct)": "TaoMate HD 8步+4步 渐进放大双采 (8+4 1080p直出)",
    "Singularity V2 + Pika H3 8-step High-Motion (Director/SelfLift/Context)": "SingularityV2+Pika H3 8步 高动态长视频 (导演台双采)",
    # v14.335 (2026-11-08): 视频人物替换档 —— 资产库 @视频N 作 V2V 源画面+原声，
    # @图N 作人物身份参考，按 H3 Recast 单镜 15s 上限自动分 clip 逐段替换。
    "Video Recast (H3 V2V character swap)": "视频替换 (V2V 人物替换)",
    # v14.341 (2026-11-09): 视频角色替换+动作迁移 —— 教程 BV1HBWJ6HEkg 口径,
    # 226 帧/段 + 段间 22 帧重叠锁定续接 + 一采 8 步/二采 5 步(1.5x),
    # 不要求任何 swap/角色替换 LoRA（只可挂加速 LoRA）。
    "Video Remix (no-LoRA character swap + motion transfer)": "视频角色替换+动作迁移",
    # v14.345 (2026-11-09): 第 36 档 Viggle Remake 视频改写 —— 官方两个编辑 LoRA
    # (swap=主体替换 / edit=元素增删改)，6 步固定 sigma，源片整段作 cond video。
    "Viggle Remake Video Edit (6-step swap/edit LoRA, FL2VA)": "Viggle Remake 视频改写 (6步 换人/增删改)",
    # v14.360 (2026-11-10): 换脸档 —— 与上一档共用全部 Viggle 采样配方，唯一差别是
    # 每段出片后追加 tools/viggle_faceswap.py 逐帧换脸(模型 128)。
    "Viggle Remake Video Edit + FaceSwap (6-step swap/edit LoRA + 128 face swap)": "Viggle Remake 视频改写+逐帧换脸 (6步 换人)",
    # v14.339 (2026-11-08): Video Rebirth HyperFlow H3 Flash 14B —— 官方 4/6/8 步
    # 固定调度 + CFG 1.0 单采; 权重为 GGUF, 必须用 HyperFlow GGUF Loader 加载,
    # 全量 H3 的加速 LoRA 与其低秩分解层不兼容, 不要叠。
    "HyperFlow H3 Flash 14B Single-Pass (4/6/8-step GGUF)": "HyperFlow H3 Flash 14B 单采 (4/6/8步 GGUF)",
}
_VIGGLE_RP_LABEL = "Viggle Remake 视频改写 (6步 换人/增删改)"
_VIGGLE_RP_FS_LABEL = "Viggle Remake 视频改写+逐帧换脸 (6步 换人)"
_VIGGLE_RP_LABELS = (_VIGGLE_RP_LABEL, _VIGGLE_RP_FS_LABEL)


_SPEED_PRESET_EN2ZH = {
    "Turbo": "极速",
    "Balanced": "均衡",
    "Fine": "精细",
    "Turbo-VDN": "极速-VDN",
    "Balanced-VDN": "均衡-VDN",
    "Fine-VDN": "精细-VDN",
}
_ONE_SHOT_SAMPLING_EN2ZH = {
    "Single-pass seamless (recommended)": "单采无缝 (推荐)",
    "Dual-pass HD (seam risk)": "双采高清 (接缝风险)",
    "Dual-pass seamless (8+4)": "双采无缝 (8+4)",
    "Dual-pass seamless 2K (8+4)": "双采无缝 2K (8+4)",
}


class BSAIH3FilmFactory:
    @classmethod
    def INPUT_TYPES(cls):
        sampler_names = list(comfy.samplers.SAMPLER_NAMES)
        scheduler_names = list(comfy.samplers.SCHEDULER_NAMES)
        default_sampler = "euler" if "euler" in sampler_names else sampler_names[0]
        default_scheduler = "simple" if "simple" in scheduler_names else scheduler_names[0]

        required = {
            "model": ("MODEL",),
            "clip": ("CLIP",),
            "vae": ("VAE",),
            "run_mode": (["clip_by_clip", "full_batch"], {"default": "clip_by_clip"}),
            "width": (
                "INT",
                {
                    "default": 1344, "min": 32, "max": 4096, "step": 32,
                    "tooltip": "Manual resolution width, also used as Auto fallback when no internal image reference is loaded.",
                },
            ),
            "height": (
                "INT",
                {
                    "default": 768, "min": 32, "max": 4096, "step": 32,
                    "tooltip": "Manual resolution height, also used as Auto fallback when no internal image reference is loaded.",
                },
            ),
            "ref_image_size": (["match", "max", "half"], {"default": "max"}),
            "steps": ("INT", {"default": 8, "min": 1, "max": 10000, "step": 1}),
            "sampler_name": (sampler_names, {"default": default_sampler}),
            "scheduler": (scheduler_names, {"default": default_scheduler}),
            "denoise": ("FLOAT", {"default": 1.0, "min": 0.01, "max": 1.0, "step": 0.01}),
            # v14.178 一镜到底全球方案落地 P0-1: context 默认 39→22(官方 AddGuide 尾部
            # 22 帧锚定), audio_context_length 默认 0→24(比视频多 2 帧对齐 40Hz 音频网格)。
            "context_length": (["22", "5", "39", "56"], {"default": "22"}),
            "audio_context_length": ("INT", {"default": 24, "min": 0, "max": 240, "step": 1}),
            "clips_json": (
                "STRING",
                {
                    "default": _state_json([_default_clip(0)]),
                    # v14.372: 超长 JSON 在 multiline textarea 里会撑成超高文本框,
                    # 把后面几行参数推出节点可视区。改单行渲染: 类型仍是 STRING,
                    # widget 位置/数量/序列化格式全部不变, 旧工作流不受影响。
                    "multiline": False,
                    "tooltip": "Internal state: CLIP script JSON (hidden from the UI, not rendered or edited). v14.103: changed from hidden back to STRING. The ComfyUI 1.55 frontend does not create widgets of type hidden, which made buildUi miss clips_json and caused the CLIP area/UI to disappear plus a widgets-array/save-array misalignment (NaN); as a STRING the widget is created normally and extender.js v2.105 hides it.",
                },
            ),
            # Keep these AFTER clips_json so pre-v14.25 workflow widget arrays
            # keep their original positional mapping. The frontend migrates old
            # workflows/projects to Manual mode on load.
            "resolution_mode": (
                ["auto_from_ref", "manual"],
                {
                    "default": "auto_from_ref",
                    "tooltip": "Auto uses internal Ref 1 as the aspect-ratio guide; with no internal image references it falls back to width/height.",
                },
            ),
            "megapixels": (
                "FLOAT",
                {
                    "default": DEFAULT_MEGAPIXELS, "min": 0.01, "max": 16.0, "step": 0.01,
                    "tooltip": "Target total pixels for Auto resolution. Auto and Manual canvases use the MiniMax H3 32-pixel grid; Auto snaps downward without exceeding the requested pixel budget.",
                },
            ),
            # Internal image-reference manager state. Appended after the v14.25
            # widgets so older positional workflow widget arrays keep mapping.
            "refs_json": (
                "STRING",
                {
                    "default": _refs_json(_empty_refs()),
                    "multiline": False,
                    "tooltip": "Internal state: reference image JSON (hidden from the UI, not rendered or edited). v14.103: changed from hidden back to STRING for the same reason as clips_json (the 1.55 frontend does not create hidden widgets).",
                },
            ),
            "output_mode": (
                ["none", "per_clip", "merged", "both"],
                {
                    "default": "none",
                    "tooltip": "none: cache only, use the Final Decode node for output. per_clip: save one MP4 per CLIP segment. merged: merge all CLIPs into a single MP4. both: save per-clip and merged outputs.",
                },
            ),
            "filename_prefix": (
                "STRING",
                {
                    "default": "H3_Extender",
                    "tooltip": "Output filename prefix. Per-segment output appends _clipN.mp4 automatically.",
                },
            ),
            "output_image_audio": (
                "BOOLEAN",
                {
                    "default": True,
                    "tooltip": "Decode each finished CLIP to IMAGE+AUDIO immediately and stream it through the image/audio output ports (e.g. into an upscale node). When off, only the cache is kept and Final Decode exports the result.",
                },
            ),
            "block_cache": (
                "BOOLEAN",
                {
                    "default": False,
                    "tooltip": "Enable MiniMax H3 Block Cache (F1B0 residual cache) acceleration: when consecutive CLIP frames are stable, most DiT blocks are skipped, significantly speeding up multi-CLIP generation. Requires the comfyui-minimax-h3-blockcache-T8 plugin.",
                },
            ),
            "block_cache_threshold": (
                "FLOAT",
                {
                    "default": 0.12, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "Block Cache hit threshold. Higher values hit more often and speed up more, but the result may change.",
                },
            ),
            "block_cache_device": (
                ["cpu", "gpu"],
                {
                    "default": "cpu",
                    "tooltip": "Block Cache device. cpu saves VRAM; gpu reduces transfers but uses VRAM.",
                },
            ),
            "ref_cache": (
                "BOOLEAN",
                {
                    "default": True,
                    "tooltip": "Ref2VA reference-image VAE encode disk cache (same as CLIPCached, 2026.09): when reference images are unchanged, the encoded image latent is reused and repeated encoding is skipped — prompt/seed changes re-run much faster; cache auto-invalidates when references change.",
                },
            ),
            "cache_dit": (
                "BOOLEAN",
                {
                    "default": False,
                    "tooltip": "CacheDiT inter-step cache acceleration (ComfyUI-CacheDiT, H3 ~1.4-1.5x, H3 support added 2026.08): auto-detected and applied; requires the ComfyUI-CacheDiT plugin (falls back automatically if not installed). Mutually exclusive with Block Cache; when both are on, CacheDiT takes priority.",
                },
            ),
            "clip_select_enable": (
                "BOOLEAN",
                {
                    "default": False,
                    "tooltip": "CLIP selection switch: when enabled, only the CLIPs listed in clip_select are rendered; unselected ones keep their cache and are not regenerated.",
                },
            ),
            "clip_select": (
                "STRING",
                {
                    "default": "all",
                    "multiline": False,
                    "tooltip": "CLIPs to render (1-based): all=everything; single e.g. 1; multiple e.g. 1,3 / 3,5,7; ranges e.g. 2-5 / 7-10; mixed e.g. 1,3-5. Only effective when clip_select_enable is on.",
                },
            ),
            "pause_enable": (
                "BOOLEAN",
                {
                    "default": False,
                    "tooltip": "Pause switch: when enabled, rendering pauses after each CLIP before starting the next one. The frontend offers pause/continue/current-only/abort; it auto-resumes after a timeout when the user does not intervene.",
                },
            ),
            "pause_timeout": (
                "FLOAT",
                {
                    "default": 5.0, "min": 5.0, "max": 3600.0, "step": 5.0,
                    "tooltip": "Seconds to wait before auto-resuming after a pause (default 5s = best output pacing; ignored when pause is off).",
                },
            ),
            # v1.31: 二采升级为 Sol-H3 Self-Lift 双采（一采 + 二采直出高清）
            "refine_enable": (
                "BOOLEAN",
                {
                    "default": True,
                    "tooltip": "Refine (Sol-H3 Self-Lift) dual-pass, best quality, on by default: the first-pass latent is upscaled directly (no VAE) + CONST re-noise + a second full-denoise pass, producing HD video directly (e.g. 1920x1088). When enabled, per-CLIP render time increases by about 50%-100%.",
                },
            ),
            "refine_denoise": (
                "FLOAT",
                {
                    "default": 0.55, "min": 0.05, "max": 1.0, "step": 0.01,
                    "tooltip": "Refine CONST re-noise strength (Sol-H3 dual-pass semantics; v14.157 default 0.55 keeps 45% of the first-pass image, so shadows and faces gain real detail; 0.45 and below mostly smooth low-light shots). 1.0 = full re-noise redraw (official fast dual-pass). Only effective when refine_enable is on.",
                },
            ),
            "refine_steps": (
                "INT",
                {
                    "default": 6, "min": 1, "max": 20, "step": 1,
                    "tooltip": "Refine steps (v14.157 default 6 = 4 steps cannot resolve texture in low light or close-ups, 6 steps is visibly more solid; each step costs far less than a first pass). 2 steps only suit turbo models. Only effective when refine_enable is on.",
                },
            ),
            "refine_upscale_factor": (
                "FLOAT",
                {
                    "default": 2.0, "min": 1.0, "max": 2.0, "step": 0.1,
                    "tooltip": "Refine latent upscale factor (default 2.0 = direct 1920x1088 from a 960x544 first pass). 1.3-1.5x outputs close to 1080P; >1.5x significantly increases VRAM demand. After upscaling, CONST re-noise + refine run automatically. Only effective when refine_enable is on.",
                },
            ),
            "refine_upscaler_model": (
                _ff_get_upscaler_models(),
                {
                    "default": "(bilinear interpolation, no model)",
                    "tooltip": "Refine latent upscale method: 3D latent upscaler neural semantic upscale (richer detail; requires the Comfyui_Minimax_h3_latent_Upscaler plugin + model) or bilinear interpolation (no model needed, small quality loss) — the default.",
                },
            ),
            "refine_align_to": (
                "INT",
                {
                    "default": 40, "min": 8, "max": 256, "step": 8,
                    "tooltip": "Pixel alignment step after refine upscale (default 40, the H3-official 40px grid validated as optimal; 1920x1088 is already a multiple of 40). Other resolutions are rounded to this grid automatically to avoid edge color fringes.",
                },
            ),
            "refine_audio_denoise": (
                "FLOAT",
                {
                    "default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "Refine audio redraw strength: 0 = keep the first-pass audio locked (recommended: no audio re-noise/redraw, keeps voice/effects consistent); 0.5-1.0 = audio is re-noised and redrawn together with the video (sound may change). Only effective when refine_enable is on.",
                },
            ),
            # v14.83 对口型×二采组合预设（一采注入 lip_audio → 二采音频锁定保口型 / 二采音频参与重绘）
            "refine_lipsync_mode": (
                # v2.120c: 兼容 a78fa62 之前保存的旧工作流中文标签（运行期 5429-5432 已双语映射；
                # 仅合法值列表需同时接受中英文，避免旧工作流校验失败输出被忽略）。
                ["Lock lip-sync (recommended)", "Audio redraw 0.7", "Full audio redraw 1.0"],
                {"default": "Lock lip-sync (recommended)", "tooltip": "Lip-sync × refine preset: Lock lip-sync = keep first-pass audio, no redraw (refine_audio_denoise=0); Audio redraw 0.7 = refine_audio_denoise=0.7; Full audio redraw 1.0 = refine_audio_denoise=1.0. Only effective when refine_enable is on."},
            ),
            # v14.83 像素超分旁支：per-clip 逐段超分 + final 全片超分（双开关，默认关）
            "upscale_per_clip": (
                "BOOLEAN",
                {"default": False, "tooltip": "Per-CLIP pixel upscale after decode, segment by segment (per-segment VRAM stays manageable; the CLIP card H button takes priority over this master switch). Default off."},
            ),
            "upscale_final": (
                "BOOLEAN",
                {"default": False, "tooltip": "One-shot pixel upscale of the full merged film (processed once before final output; faster and cheaper). Default off."},
            ),
            "upscale_mode": (
                # v2.120c: 兼容旧工作流中文标签（_ff_resolve_upscale_mode 2208-2216 已双语映射）。
                ["Balanced (quality+speed)", "Quality first", "Speed first", "Custom"],
                {"default": "Balanced (quality+speed)", "tooltip": "Upscale mode preset: Balanced = 2.0x auto (DLSS5 if available, else REALESR); Quality first = 3.0x REALESR; Speed first = 1.5x auto; Custom = explicit values from the widgets below."},
            ),
            "upscale_engine": (
                ["auto", "dlss5", "realesr", "bicubic"],
                {"default": "auto", "tooltip": "Upscale engine: auto = automatic; dlss5 = NVIDIA DLSS5 (requires an NVIDIA driver + library); realesr = RealESRGAN (upscale_models); bicubic = built-in interpolation (fastest, no model dependency)."},
            ),
            "upscale_factor": (
                "FLOAT",
                {"default": 2.0, "min": 1.0, "max": 4.0, "step": 0.5, "tooltip": "Pixel upscale factor (relative to the refine output resolution). Default 2.0x."},
            ),
            "upscale_model": (
                _bsai_list_upscale_models(),
                {"default": "realesr-general-x4v3.pth", "tooltip": "REALESR upscale model (models/upscale_models/). Only used when upscale_engine=realesr."},
            ),
            "upscale_tile": (
                "INT",
                {"default": 0, "min": 0, "max": 4096, "step": 1, "tooltip": "Upscale tile pixels (0 = full frame; set 512~1024 when VRAM is tight)."},
            ),
            "upscale_batch": (
                "INT",
                {"default": 4, "min": 1, "max": 32, "step": 1, "tooltip": "Upscale batch frame count (trades VRAM for speed; larger = faster but more VRAM)."},
            ),
            "upscale_fp16": (
                "BOOLEAN",
                {"default": True, "tooltip": "Upscale FP16 half-precision acceleration (auto when both NVIDIA and XPU support it)."},
            ),
            "upscale_face_restore": (
                "BOOLEAN",
                {"default": False, "tooltip": "Face restore after upscale (FaceRestore; requires GPFGAN/CodeFormer weights and adds time). Default off."},
            ),
            "tiled_refine": (
                "BOOLEAN",
                {"default": False, "tooltip": "v1.48 tiled refine (default off). When enabled, refine samples along the long spatial axis in tiles, so activation/attention workspace drops linearly with tile_count, fixing OOM/hang caused by a 21.8GB model + full-frame workspace when external processes squeeze VRAM. Ported from MiniMaxH3 Director spatial tiling (Apache-2.0). Keep off when VRAM is large. Only effective when refine_enable is on."},
            ),
            "tile_count": (
                "INT",
                {"default": 4, "min": 1, "max": 8, "step": 1, "tooltip": "Refine spatial tile count. Larger = less VRAM but slower (Director demo uses 4). Only effective when tiled_refine is on."},
            ),
            "tile_overlap": (
                "INT",
                {"default": 128, "min": 0, "max": 512, "step": 16, "tooltip": "Adjacent tile overlap pixels (raised-cosine blend). Director demo uses 128. Only effective when tiled_refine is on."},
            ),
            # v1.83: 速度预设 - 落地 B站 MiniMax急速工作流(comfyu-Selflift)技术:
            # 高分辨率二采只跑2步 + 一采4步, 视频验证 16G 跑 10s 200wpx 耗时 1000s 且质量保住.
            # 24G 跑 15s 208wpx(1920x1088) 极速模式预计 ~10-12 分钟/clip.
            # v14.172: 速度档仅保留基础速度/画质档(custom/极速/均衡/精细 + VDN 变体 7 项);
            # 模型配方档(FastH3-Trim/FastH3-4步VSA/Turbo-v4/DMAD-4步/武戏组合拳/Omni)
            # 已迁入「渲染管道 render_pipeline」下拉。旧工作流若遗留旧值, 下方
            # 兼容分支仍按值生效。
            "speed_preset": (
                ["custom", "Turbo", "Balanced", "Fine", "Turbo-VDN", "Balanced-VDN", "Fine-VDN"],
                {
                    "default": "custom",
                    "tooltip": "v1.86 speed preset (default custom = explicit values from the widgets below; best 8+2 dual-pass out of the box). Turbo = 4 first-pass steps + 3 refine steps + denoise 0.5 (~20min/clip); Balanced = 6 + 4 (~28min); Fine = 8 + 6 (~40min). VDN presets pair with the VDN workflows. Model recipes (FastH3-Trim / FastH3-4step VSA / Turbo-v4 / DMAD-4step / Action Combo / FastH3 Omni 8-step single-pass) have moved to the Render Pipeline dropdown. custom = explicit widget values below.",
                },
            ),
            # P0 (2026-10-17): 官方双轨迹采样 —— MiniMaxH3SigmaShift 等效注入.
            # video shift 驱动采样器 sigma 调度(ModelSamplingAV), audio schedule 由模型内部
            # 从共享 base grid 推导. 默认开(12/3, 官方推荐), 关掉则回到旧行为.
            "dual_track_shift": (
                "BOOLEAN",
                {"default": True, "tooltip": "P0: official dual-track sampling (MiniMaxH3SigmaShift equivalent). Separate video/audio flow shift improves A/V sync and few-step convergence. On by default."},
            ),
            "shift_video": (
                "FLOAT",
                {"default": 12.0, "min": 0.01, "max": 100.0, "step": 0.1, "tooltip": "Video flow shift, drives the sampler sigma schedule. Official default 12; DMAD recipe 12; Turbo v4 12."},
            ),
            "shift_audio": (
                "FLOAT",
                {"default": 3.0, "min": 0.0, "max": 100.0, "step": 0.1, "tooltip": "Audio flow shift. Official default 3; DMAD recipe 2. 0.0 = audio shift off (kept for old workflows)."},
            ),
            # P2 (2026-10-17): SelfLift H3 TST 时间状态传输 —— 少步数画质补偿.
            # 校正 H3 视频时间不平衡(闪烁/身份漂移/不合理运动), 运行时开销 1-2%.
            # 依赖 comfyui-SelfLift (facok) 已安装; 未安装时自动跳过并提示.
            "selflift_tst_enable": (
                "BOOLEAN",
                {"default": True, "tooltip": "P2: SelfLift H3 TST few-step quality compensation (corrects flicker, identity drift, implausible motion). Default tau 0.2. Requires comfyui-SelfLift to be installed."},
            ),
            "selflift_tst_tau": (
                "FLOAT",
                {"default": 0.2, "min": 0.0, "max": 1.0, "step": 0.05, "tooltip": "TST correction strength; the paper recommends 0.2, and 0.5 is too strong. 0 = diagnostics only."},
            ),
            "temporal_chunk_tokens": (
                "INT",
                {"default": 0, "min": 0, "max": 200, "step": 1, "tooltip": "v2.02 temporal chunking (along the T axis, unlike tile_count which is along H/W). 0 = off (default full-segment refine); >0 splits the refine latent along T into token segments of that length with overlap, each run through the existing (spatial-tiled) sampler, with the overlap zones frozen and taken over by smoothstep. Lowers attention/activation peaks to prevent OOM. For T~107, 40~60 is recommended."},
            ),
            "temporal_overlap_tokens": (
                "STRING",
                {"default": "8", "tooltip": "Overlap tokens between adjacent temporal chunks. Larger = more stable but slower; typically 8~12. Only effective when temporal_chunk_tokens>0. Old workflows: 'global_inherit', empty, or non-numeric values fall back to the default 8."},
            ),
            # v2.19 Semantic-Bridge 语义桥(可开可关, 默认关). 权重放 models/semantic_bridge/.
            "semantic_bridge_enable": (
                "BOOLEAN",
                {"default": False, "tooltip": "Semantic Bridge switch. When enabled, a small ~11MB MLP applies residual mixing to the text-encoder tokens so H3 follows instructions better (composition/spatial/counting, etc.). The original is distilled from FL2VA; this plugin forces Ref2VA compatibility. Default off; does not affect existing workflows."},
            ),
            "semantic_bridge_adapter": (
                _bsai_list_semantic_bridge_adapters(),
                {"tooltip": "Semantic Bridge weight file (~11MB), place in ComfyUI/models/semantic_bridge/. Downloads: speach1sdef178/MiniMax-H3-Semantic-Bridge or JOKER141/BUNNY_H3_Conditioning_Bridge (action/multi-person oriented). Choose (Off) to disable."},
            ),
            "semantic_bridge_alpha": (
                "STRING",
                {"default": "0.15", "tooltip": "Residual mix strength C=H+alpha*(S'-H). Original default 0.15; larger = tighter to the bridge, too large drifts. Old workflows: empty or non-numeric values fall back to the default 0.15."},
            ),
            "semantic_bridge_magnitude_match": (
                "BOOLEAN",
                {"default": True, "tooltip": "Align the small MLP output vector norm to the original hidden. Original default on."},
            ),
            # v2.24 模型环境音开关（对口型时是否混入H3自生成环境音；关=只留主唱/克隆语音）
            "env_audio_enable": (
                ["global_inherit", "on", "off"],
                {"default": "global_inherit", "tooltip": "Model ambient sound switch: global_inherit = follow the global default; on = mix in H3-generated ambient sound; off = keep only the main vocals/cloned voice."},
            ),
            "env_audio_gain": (
                "FLOAT",
                {"default": 0.15, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "Model ambient volume (0 = silent, 1 = full, default 0.15 as a floor)."},
            ),
            # v14.221: 保脸模式升级为三态枚举 ——
            #   off   = 关闭(默认，不额外处理)
            #   auto  = 常规保脸锁定(依靠 @img2.N 脸部特写参考注入 ref2v conditioning 维持五官一致)
            #   refine= 小脸修复(出片前对每个分镜做 H3 FaceRefine 局部人脸重绘，专治远景小脸崩坏)
            #   fvrs  = 音频引导修复(v14.340, TaoMate-FVSR 逐分镜重建嘴部/牙齿细节并对齐音轨)
            "face_lock_mode": (
                ["off", "auto (face-lock)", "refine (small-face inpaint)", "fvrs (audio-guided restore)"],
                {"default": "off", "tooltip": "Face-lock / small-face repair mode: off = disabled (default, no extra processing); auto = standard face-lock (injects the @img2.N close-up face reference into ref2v conditioning to keep facial features consistent); refine = small-face repair via H3 local inpaint (before output, detects faces in every shot, repaints the face region with H3 and blends it back; fixes small-face degradation in distant shots; requires the BSAI-ComfyUI-FaceRefine plugin, heavy; enable only when you actually see small-face artifacts); fvrs = audio-guided restoration via TaoMate-FVSR (per-shot: YOLO crop -> 512 face reconstruction guided by the clip's own audio -> paste back, fixes blurry faces AND lip/teeth detail drift; requires the official ComfyUI-TaoMate-FVSR plugin + ~15GB weights, ~745s for a 15s clip on H20; tune with BSAI_FVRS_* env vars)."},
            ),
            # v14.153 修正: refine_mem_mode 移出 required —— 它在 widget 序列中必须
            # 排在 optional 的 prompt_pack 之后（即所有 widget 的最末尾），否则会让
            # prompt_pack 从 index 62 挤到 63，与前端 KEYS/历史工作流布局错位，
            # 导致序列化丢 socket(model/clip/vae)。见下方 optional 末尾的真实定义。
        }

        # Standalone audio remains an external socket for now. Image refs are
        # deliberately no longer graph inputs: they are loaded/previewed/stored
        # by the Extender itself and embedded in portable .ext projects.
        optional = {
            "audio_vae": ("VAE", {"forceInput": True}),
            "ref_audio": ("AUDIO", {"forceInput": True, "tooltip": "Voice reference audio. When connected, it tells the H3 model that the character's voice/timbre/music style should follow this reference. Can be connected together with lip_audio — lip_audio drives the lip-sync while ref_audio provides the timbre reference."}),
            "lip_audio": ("AUDIO", {"forceInput": True, "tooltip": "Single song source: the complete song/dialogue audio — TOP PRIORITY audio port. Once connected: (1) the lip-sync of every CLIP and @imgN character is driven entirely by the matching segment of this song; (2) the ref_audio and lip_voice ports and @audN are all ignored automatically, no matter whether they are connected; (3) all model-generated audio is discarded; (4) the output sound is exactly this song. It is auto-sliced per CLIP duration and the final output matches the video length."}),
            # v14.101: 回退 18:35(v14.84) — lip_voice 位置与 v2.7.json 一致（lip_audio 之后）
            # v14.174: lip_voice 升级为对口型驱动音频（同 lip_audio 语义）。
            # v14.270: 优先级反转 — lip_audio 最高，lip_voice 仅在 lip_audio 未接时生效。
            "lip_voice": ("AUDIO", {"forceInput": True, "tooltip": "Lip-sync drive audio (v14.174+): the complete dialogue audio. Once connected, it behaves exactly like lip_audio — (1) drives lip-sync of every CLIP; (2) all model-generated audio is discarded; (3) output sound is exactly this audio, auto-sliced per CLIP; (4) applies only when lip_audio is NOT connected — lip_audio always takes top priority (v14.270+). Typical use: connect BSAI IndexTTS-2.5 synthesis output here to drive lip-sync with TTS voice lines."}),
            "prompt_source": ("STRING", {"forceInput": True, "tooltip": "Unified external prompt source. Auto-split at first [ShotN] marker: text before → global prompt, text from [ShotN] onwards → storyboard segments (auto-create N CLIPs with prompts and durations)."}),
            "prompt_pack": (
                PROMPT_PACK_TYPE,
                {
                    "tooltip": "Optional external prompt pack. New/changed packs are imported into the normal clip textareas and synchronize the clip count."
                },
            ),
            # v14.153: 二采省显存模式。必须排在 prompt_pack 之后 = 所有 widget 的最末尾
            # (index 62)，这样 0..61 的 widget 顺序与 v14.152 及更早完全一致，
            # 老工作流(58/59/63 键)零错位。若放 required 末尾会挤掉 prompt_pack → 丢 socket。
            "refine_mem_mode": (
                ["spatial (tiled, compatible)", "global (full-context, low VRAM)"],
                {"default": "spatial (tiled, compatible)", "tooltip": "Refine memory-saving mode. spatial (default) = current 4-tile spatial tiling (v14.149, may show background swelling/seams on some scenes). global = ported from selflift-Avatar global-context mode: full-sequence attention (no tiles, no seams) + token-chunked norm/MLP to bound VRAM; coexists with KJNodes head-grouping / Sol-Attn override (v14.148 dense gate stays active). Expect per-step time similar or better than 4-tile spatial."},
            ),
            # v14.158 (2026-10-21): BSAI 一镜到底旁支模式 —— 移植自 B站
            # 《MinimaxH3 长视频一镜到底工作流》(BV1rEto6eEvA) 的核心方法：
            # ① 段间用上一段尾部做 Add Guide 等效锚点引导（电影工厂已有
            #    motion context latent 级引导，一镜到底模式下强制开启）；
            # ② 每段提示词自动注入"不切场/不转场/镜头持续跟随主体"指令；
            # ③ 合并时改为无缝 concat（零转场），替代默认多镜头 xfade 渐变。
            # 作为旁支选择，off 时行为与历史版本完全一致，不影响任何旧工作流。
            "one_shot_mode": (
                ["off (storyboard)", "on (one-shot)"],
                {
                    "default": "off (storyboard)",
                    "tooltip": "BSAI one-shot branch (based on the Bilibili MinimaxH3 long-take workflow + Motion Context V2 BV1T9ho6HEKP): off = default shot-by-shot editing mode (each segment generated independently and joined with xfade transitions; behavior unchanged). on = one-shot mode: (1) every segment prompt gets a 'no cuts / no transitions / camera keeps following the subject' instruction injected automatically (skipped if you already wrote it); (2) inter-segment motion context is forced on, and the tail latent of the previous segment guides the current one as an Add Guide equivalent anchor; (3) joining switches to seamless concat with zero transitions. v14.185 adds the one_shot_sampling tier (the last parameter of this node): the default 'single-pass seamless' skips the refine pass, so chained latents are never redrawn and seams have zero drift (dual-pass chaining introduces pixel drift; only pick it when you need 2K upscaling). Prompt discipline: the seam trims 22 frames, about 0.92s, so to land a timestamp at T write T+0.92s; continuation segments should only state what carries over (same rhythm / same camera / same lighting) and must not introduce new scene nouns; keep seams inside motion, never on a threshold or event; keep dialogue lines to one short sentence per 2.5s. Continuous camera moves (push / pull / follow / orbit) across all CLIP prompts are recommended; together with this mode you get 30s+ seamless long takes.",
                },
            ),
            # v14.159 (2026-10-21): 一镜到底 × 歌曲自动分 CLIP。
            # 结合现有对口型模式的歌曲驱动逻辑(_split_lip_audio_by_clips 按 CLIP
            # 时长切音频): one_shot_mode=on 且连接 lip_audio 歌曲时, 按本值(每段
            # 目标秒数) 自动把歌曲时长均分为目标 CLIP 数量, 自动补齐/对齐 CLIP
            # 卡片与每段时长。0 = 关闭自动分(保持手动 CLIP 数)。
            "one_shot_clip_duration": (
                "INT",
                {
                    "default": 12, "min": 0, "max": 60, "step": 1,
                    "tooltip": "One-shot x song: target duration per segment (seconds). When lip_audio is connected and one_shot_mode=on, the CLIP count is auto-computed as song duration / this value (rounded up), and CLIP cards are added/aligned automatically; the last segment takes the song's remaining duration. Example: a 5-minute song / 12s = 25 CLIPs. 0 = auto-split off.",
                },
            ),
            "asset_library": ("ASSET_LIBRARY", {"forceInput": True, "tooltip": "Connect BSAI_AssetLibraryInput to resolve @imgN/@vidN/@audN references in clip prompts."}),
        }

        # v1.22: per-clip external prompt input ports (clip_prompt_1..clip_prompt_12).
        # v14.101: 回退到 18:35（v14.84）节点结构 — 依据 v2.7.json 权威文件：
        # 当时即有 clip_prompt_1-12 端口（1/2 常连、3-12 预留）。均为 forceInput
        # 输入端口，不序列化，不影响 widgets_values 数组对齐。
        for _ci in range(1, 13):
            optional[f"clip_prompt_{_ci}"] = (
                "STRING",
                {
                    "forceInput": True,
                    "multiline": True,
                    "tooltip": f"External prompt override for CLIP {_ci}. If connected and non-empty, replaces CLIP {_ci}'s prompt (duration/refs/timings still come from the clip card). Leave unconnected to use the built-in clip prompt.",
                },
            )
        # v14.101: 回退 18:35(v14.84) — tts_model_TTS模型 在 optional 末尾（v2.7.json 一致）
        optional["tts_model_TTS模型"] = (
            "INDEX_TTS_MODEL",
            {"forceInput": True, "tooltip": "IndexTTS-2.5 model (connect to the tts_model output of BSAI_IndexTTS2_5Loader). Required in speech mode."},
        )
        # v14.172 (2026-10-22): 渲染管道统一管理全部模型配方档 —— 双采默认 +
        # FastH3-Trim / FastH3-4步VSA / Turbo-v4 / DMAD-4步 / 武戏组合拳 / Omni 8步单采。
        # 速度档(v14.170 曾并入的配方档)已回退为 7 项基础档, 配方档统一在此选择。
        # 注意: 必须排在 optional 全部 widget 的最末尾 (index 65 = 老工作流空槽,
        # 现有 66 键工作流 w65=''), 追加在 tts_model 端口之后不挤占任何既有 index。
        optional["render_pipeline"] = (
            ["Sol-H3 Self-Lift Dual-Pass (default)", "MV Dual-Pass (Film Factory v3.2 original)", "Live Dub HD (audio 12+ steps)", "FastH3-Trim", "FastH3 4-step VSA", "Turbo-v4", "DMAD 4-step", "Action Combo", "4K Direct Secret Sauce", "FastH3 Omni 8-step Single-Pass", "Dual-Pass 2K (HyperVAE 2x decode)", "QAD-v2 8-step", "Live Commerce 01 Text Dubbing (no audio inputs)", "Live Commerce 02 ref_audio Voice Reference", "Live Commerce 03 lip_voice Lip-Sync", "Live Commerce (fully automatic)", "FastH3 Omni x SelfLift Upscale", "H25 Hybrid 8-step Multi-Ref Single-Pass", "4K Regenerate OpenH3Regenerate2K (768P draft to 2560)", "PRISM 10-step Motion Single-Pass (Singularity v2 x 10Eros-Max)", "Transparent Video Single-Pass Keying (H3 Transparent)", "4-in-1 Ultimate Speedup (DMAD 8-step + SelfLift 6+2 + half-res refs + SegAttention)", "SolarRenderer Structure Control (control LoRA + 4-step LoRA)", "Director Turbo Dual-Pass (MiniMaxH3 Director port)", "Dual-Pass 2K (official condition upscale)", "PDMD 4-step SelfLift Dual-Pass (4+2)", "PDMD 2-step Turbo Draft (single-pass)", "PTD 4-step Ref2VA Single-Pass (reference accel)", "ACC 8-step SelfLift Dual-Pass (8+4)", "PIKA H3 Flex 6+2 SelfLift Dual-Pass (Ref2VA face-lock)", "PIKA H3 Flex 8+2 SelfLift Dual-Pass (Ref2VA face-lock)", "TaoMate HD 3-Step Progressive Lift Dual-Pass (2+1, 1080p direct)", "TaoMate HD 8+4 Progressive Lift Dual-Pass (8+4, 1080p direct)", "Singularity V2 + Pika H3 8-step High-Motion (Director/SelfLift/Context)", "Video Recast (H3 V2V character swap)", "HyperFlow H3 Flash 14B Single-Pass (4/6/8-step GGUF)", "Video Remix (no-LoRA character swap + motion transfer)", "Viggle Remake Video Edit (6-step swap/edit LoRA, FL2VA)", "Viggle Remake Video Edit + FaceSwap (6-step swap/edit LoRA + 128 face swap)"],
            {
                "default": "Sol-H3 Self-Lift Dual-Pass (default)",
                "tooltip": "v14.184 render pipeline (all model recipes are selected here; Speed keeps only the 7 basic tiers): (1) Sol-H3 Self-Lift Dual-Pass (default, HD refine); (2) Live Dub HD = live-commerce ref_audio dubbing: 12 first-pass steps + 4 refine steps + audio redraw 0.7 (needs a non-8-step distilled model such as minimax_h3_ref2va_int8_convrot); (3) FastH3-Trim = nvfp4 pruned model, 8+4 dual-pass; (4) FastH3 4-step VSA = 4-step distillation + VSA LoRA, 4+2; (5) Turbo-v4 = Turbo LoRA v4 step600 EMA, 6+4 (shift 12/3); (6) DMAD 4-step = DMAD 4-step distillation LoRA, 8+2 (v14.386: was 4+2; forced lcm, shift 12/2); (7) Action Combo = 8+4 (euler; action/DMAD LoRAs injected by H3LoraStack); (8) 4K Direct Secret Sauce = self-lift progressive sampling (6-step low-res pass + boost x2 / 3-step detail pass + DLSS5 4K pixel upscale); (9) FastH3 Omni 8-step Single-Pass = skip refine, 8-step distilled first pass (guidance 1.0, shift 12/3; Loader must use fasth3_omniref_8step_pruned_int8_convrot + BlockSparseAttention VSA keep_percent=10); (10) Dual-Pass 2K (HyperVAE 2x decode) = 8+4, latent factor 1.0 (~4x faster refine) + HyperVAE 2x decoded pixels for direct 2K (weights auto-detected from models/vae as hyper*2x*.safetensors); (11) QAD-v2 8-step = quantization-aware distillation NVFP4 set (118GB -> 30GB), 8-step single pass (shift 10/3), refine skipped, Loader switches to the full QAD-v2 NVFP4 set; (12-14) Live Commerce voice modes (v14.220): 01 Text Dubbing = no audio ports connected, the model reads the storyboard lines in its default voice; 02 ref_audio Voice Reference = voice follows ref_audio; 03 lip_voice Lip-Sync = the model generates no audio, sound comes entirely from lip_voice driving @img1 lip-sync; all three share the 12+4 recipe and auto-ignore miswired audio ports; (15) Live Commerce (fully automatic) = one-click tier, every parameter is taken over (12+4, denoise 0.55, 3D latent upscaler x2.0, audio redraw 0.7, shift 12/3, TST 0.2, tiled 4x128, audio_context_length=0, motion context off from clip2); (16) FastH3 Omni x SelfLift Upscale = Omni 8-step distill + SelfLift progressive upscale (4-step ~0.4x skeleton -> 3D latent upscale -> 4-step hi-res refine, 8 NFE); (17) H25 Hybrid 8-step Multi-Ref Single-Pass = FL2VA base + Ref2VA overlay (Block Range Additive 25-49) + LightX2V 8-step FL2V accel LoRA, 8-step single-pass (euler+simple, shift 12/3); (18) 4K Regenerate OpenH3Regenerate2K = 768P draft -> 3-step regenerate -> 2560x1440 (merged LoRA: OpenH3 Refiner 0.7 + fl2v turbo 1.0 + lms sharp 1.0; license excludes EU/UK/KR/US); (19) PRISM 10-step Motion Single-Pass = Singularity v2 x 10Eros-Max merged model, euler+simple 10 steps, no LoRA; (20) Transparent Video Single-Pass Keying = generate on a flat solid backdrop (green/blue/pure black), 10-step single-pass, refine skipped so the backdrop stays uniform for clean keying; pair with BSAI_H3_TransparentKey + BSAI_H3_SaveTransparentVideo; (21) 4-in-1 Ultimate Speedup = DMAD 4-step LoRA + SegAttention 2.2.0 + half-res reference input + SelfLift dual-pass (6+2, latent x2.0); (22) SolarRenderer Structure Control = control LoRA reads a structure video frame-by-frame (3D greybox/normal/pose/depth, a video ControlNet) + 4-step LoRA, 4+4 = 8 NFE, ref_image_size forced max; (23) Director Turbo Dual-Pass = MiniMaxH3 Director port: 8-step low-res first pass + 4-step refine (latent x2.0, denoise 0.45), the second pass follows a Director control video instead of ref2va refs; (24) Dual-Pass 2K (official condition upscale) = latent 2x via the official MiniMaxH3LatentUpscaleCombined path with ref2va condition latents upscaled in sync, native VAE outputs 2K directly (8+4, denoise 0.45, euler, shift 12/3); (25) PDMD 4-step SelfLift Dual-Pass = PDMD 4-step distillation LoRA, 4+2 = 6 NFE (shift 12/3); (26) PDMD 2-step Turbo Draft = 2 NFE single-pass for rapid drafting only, not for final footage; (27) PTD 4-step Ref2VA Single-Pass = per-hop Ref2VA acceleration LoRA, requires a Ref2VA base model; (28) PIKA H3 Flex 6+2 SelfLift Dual-Pass (v14.310, Bilibili BV1Dy4u67EJo / Pika-Labs Pika-H3-Flex adapters, 6-step distilled, strength 1.0, no second accel LoRA stacked) = 6-step single pass with lcm + ManualSigmas fixed knots 1000/750/500/250/100/40 (official distilled schedule, NOT simple linspace), shift 12/3, cfg 1.0; refine SKIPPED because per-step SelfLift on a 587k-token 10s clip costs 287s/step = 6 NFE direct to 960x544 latent, H3 VAE decodes natively to 1920x1088; keep the hybrid b25-49 base (chained hops need the FL2VA last-frame handoff - a pure ref2va base makes hop-2+ render the reference sheet); Ref2VA @image refs lock the face; pair with SegAttention / Sol-Attn / Sol VAE for the full speed stack; (29) TaoMate HD 3-Step Progressive Lift Dual-Pass (v14.303, Bilibili BV1Ui4G6nEXs, slmonker/TaoMate-HD-preview-comfy 3-step distilled progressive-lift LoRA, strength 1.0, no second accel LoRA) = 2-step low-res first pass on a 0.625x canvas (1200x680 for 1080p) + bislerp coupled lift (latent x1.6, no upscaler model) + 1-step hi-res refine = 3 NFE direct to 1920x1088 1080p; cfg 1.0 distilled contract, euler+simple, shift 12/3; (30) TaoMate HD 8+4 Progressive Lift Dual-Pass (v14.323) = the same TaoMate HD recipe as (29) with 8 first-pass steps + 4 refine steps (denoise 0.45, latent x2.0, 3D latent upscaler, tiled 16x128) = 12 NFE; same LoRA contract (strength 1.0, never stack a second accel LoRA); (31) Singularity V2 + Pika H3 8-step High-Motion (v14.322, Bilibili BV1y8446DExi) = Singularity v2 base + 8-step turbo LoRA (pika_h3_flex_turbo_8step_hd_ref2va, official contract: 8 steps/CFG 1.0/euler-simple/shift 12/3, Flex style 0.6 baked; or LightX2V 8-step 768p) + 8-step first pass + SelfLift progressive 3-step refine (denoise 0.40, latent x2.0, 3D upscaler, tiled 4x128) = 11 NFE; two-stage LoRA discipline: stage-1 carries one high-motion LoRA (Motion_Repair_V2 / H3_Fight_Flow_V1 / H3_Combat_V2, pick ONE, never stack all), stage-2 keeps it at 0.3-0.4; audio stays locked in refine (8 first-pass steps clear the ~6-step H3 audio floor); pair with one_shot_mode=on + motion context for 27s/30s chained long takes, optional +6-step audio LoRA off by default. (32) Video Recast (H3 V2V character swap, v14.335) = video character replacement: the asset-library video @vidN becomes the V2V source (picture AND soundtrack) while @imgN reference pictures define the new identity; the backend auto-splits the source into <=15s segments (the MiniMax H3 Recast per-shot contract: a 45s video becomes 3 clips), encodes each segment into the H3 AV latent (video = source frames, audio = source soundtrack locked with noise_mask 0), and runs an 8-step euler/simple first pass at denoise 0.65 so the original camera/motion/composition survive and only the person is swapped; refine skipped, motion context chaining disabled between recast clips; mount minimax_h3_*character_swap_v1.5.safetensors in the LoRA stack at 0.6-0.8 for the strongest identity transfer. (34) Video Remix (no-LoRA character swap + motion transfer, v14.341, Bilibili BV1HBWJ6HEkg) = character replacement + motion transfer: the asset-library @vidN source video supplies the action, camera and soundtrack while @imgN reference pictures supply the identity; NO swap LoRA (community test: it pulls the face toward a western look and breaks colour match), only an acceleration LoRA may stay mounted. The backend splits the source into 226-frame (5+17k, ~9.42s) segments with a locked 22-frame overlap (segment k starts at 204*k/24 s, so its head IS the previous segment tail -> continuous action and light), runs a 4-step high-noise first pass plus a 5-step low-noise refine pass on a 1.5x latent (9 NFE total, euler/simple, shift 12/3, denoise 0.62); the whole frame stays redrawable so the prompt decides character replacement (background written from the source shot) versus motion transfer (one brand-new scene only), and the source soundtrack is locked into the audio rows (BSAI_H3_REMIX_LOCK_AUDIO=0 lets the model regenerate audio). (35) ACC 8-step SelfLift Dual-Pass (8+4, v14.387) = the BSAI H3 acceleration adapters under models/loras/H3/H3加速/ACC: MiniMax-H3-Ref2VA-Acc-8Step_comfyui_pdd-T8 (reference-image to AV) and MiniMax-H3-FL2VA-Acc-8Step_comfy (first/last-frame and text); LoRA strength 1.0, euler+simple, shift 12/3, CFG 1.0, and never stack a second acceleration LoRA (both adapters are already 8-step distilled and would fight over the same low-rank subspace); 8 first-pass steps + 4 refine steps, where the refine is pure super-resolution since v14.384 (the 4 steps only really run when BSAI_H3_REFINE_REDRAW=1); the Ref2VA adapter needs a Ref2VA or hybrid b25-49 base model (chained one-shot hops rely on the FL2VA last-frame handoff), so use the FL2VA adapter on a pure FL2VA base.",
            },
        )
        # v14.185 (2026-10-24): 一镜到底采样档 —— 追加在 render_pipeline 之后（optional
        # 最末尾），不挤占任何既有 widget index。
        # 参考 B站 Motion Context V2 (BV1T9ho6HEKP) 实测结论：双采 latent 续链在接缝
        # 产生像素漂移，单采接缝干净——一镜到底默认单采。
        # v14.215 (2026-10-26): 新增第三档「双采无缝 (8+4)」—— 一镜到底 + 二采
        # (1采8步 + 2采4步), 并修掉双采接缝漂移的根因(段头锁 keep 在双采分辨率下静默失效)。
        optional["one_shot_sampling"] = (
            ["Single-pass seamless (recommended)", "Dual-pass HD (seam risk)", "Dual-pass seamless (8+4)", "Dual-pass seamless 2K (8+4)"],
            {
                "default": "Single-pass seamless (recommended)",
                "tooltip": "One-shot sampling tier (only effective when one_shot_mode=on): Single-pass seamless = skip the refine pass, chained latents are never redrawn, seams have zero drift; recommended with the turbo 8-step LoRA + beta scheduler + 6-8 steps. Dual-pass HD = keep the refine upscale/refinement (can reach 2K), but the reference workflow shows dual-pass chaining introduces pixel drift at seams (blur/jitter between segments), so pick it only when you need HD upscaling. v14.215 adds 'Dual-pass seamless (8+4)': runs the refine pass (8 first-pass steps + 4 refine steps, denoise 0.45) AND repairs the inter-segment anchor so the join stays seamless - the head keep-lock used to die silently whenever the previous clip's tail was at the refined 2x resolution, which is exactly why dual-pass drifted. The 8+4 counts still come from the widget (speed_preset=custom); this tier never overrides them. v14.272 adds 'Dual-pass seamless 2K (8+4)': the same seamless dual-pass chain but as a self-contained 2K recipe - it forces 8 first-pass steps + 4 refine steps + denoise 0.45 + euler + shift 12/3, enables refine, and sets the refine scale so the output width lands on 2560 (2K) whatever the first-pass width is (1280 -> x2.00, 1920 -> x1.33, clamped to 1.0..2.0; a 3D latent upscaler model is used only at exactly x2.00, otherwise bilinear).",
            },
        )
        # v14.238 MiniMaxH3 Director 极速双采移植参数 —— 追加在 optional 最末尾,
        # 不挤占/不移位任何既有 widget index。
        optional["refine_sampler"] = (
            ["inherit", "euler", "res_multistep", "dpmpp_2m", "lcm", "ddim"],
            {
                "default": "inherit",
                "tooltip": "v14.238 Director port: independent refine-pass sampler. Mirrors the reference plugin's Refine node split (first pass res_multistep / refine pass euler); inherit = follow the first-pass sampler. The Director Turbo Dual-Pass tier defaults to euler.",
            },
        )
        optional["director_fast_first_mp"] = (
            "FLOAT",
            {
                "default": 0.4, "min": 0.1, "max": 1.0, "step": 0.05,
                "tooltip": "v14.238 Director Turbo Dual-Pass: first-pass low-res canvas (megapixels). Default 0.4 = 864x480 (16:9), matching the reference plugin's turbo workflow contract; only effective in the Director Turbo Dual-Pass tier.",
            },
        )
        optional["director_fast_target_mp"] = (
            "FLOAT",
            {
                "default": 2.0, "min": 0.5, "max": 4.0, "step": 0.1,
                "tooltip": "v14.238 Director Turbo Dual-Pass: target canvas after the refine pass (megapixels). Default 2.0 = 1920x1088 (16:9); only effective in the Director Turbo Dual-Pass tier.",
            },
        )
        optional["refine_sigmas"] = (
            "SIGMAS",
            {
                "forceInput": True,
                "tooltip": "v14.238 Director port: external SIGMAS input (mirrors the reference plugin's Refine node behavior). When connected to BasicScheduler/ManualSigmas, the refine pass follows the external sigma curve exactly; when unconnected, the internal beta schedule (refine_steps/refine_denoise) is used.",
            },
        )
        # v14.360: 换脸工序**不再追加 widget** —— 追加会改变电影工厂的既有参数位置，
        # 让旧版工作流(71 项)载入时尾部错位/NaN。改为"档位化"：
        #   下拉「Viggle Remake 视频改写 (6步 换人/增删改)」     = 纯 Viggle 出片，不换脸(默认)
        #   下拉「Viggle Remake 视频改写+逐帧换脸 (6步 换人)」 = 每段出片后跑 tools/viggle_faceswap.py
        # 前 71 项 widget 的位置/类型与 v14.339 及更早版本逐一对齐，旧工作流零影响。
        # v14.193: 视觉锚点改为全自动（自动记录 + 自动注入）—— 手动输入 widget
        # visual_anchor_notes（v14.186 曾置于 optional 最末尾 index 67）已移除：
        # 锚点状态自动从各分镜正文提取全部可见视觉元素（_extract_visual_state，
        # 角色形象/外观/服装/服饰/发型/鞋帽/场景/道具/布景等）并自动注入后续
        # 分镜，不再需要（也不新增）任何手动输入参数端口。移除的是最末尾
        # widget，不挤占/不移位任何既有 widget index（现役布局与旧 CUR68 一致）。


        # v1.21: INPUT_TYPES keys kept as pure English for workflow compatibility.
        # Bilingual labels are applied on the frontend via extender.js widget label override.
        return {
            "required": required,
            "optional": optional,
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = (CACHE_TYPE, "INT", "INT", "STRING", "FLOAT", "STRING", "STRING", "IMAGE", "AUDIO")
    RETURN_NAMES = (
        "cache",
        "clip_count",
        "validated_count",
        "status",
        "cache_size_mb",
        "build",
        "clip_videos",
        "images",
        "audios",
    )
    FUNCTION = "extend"
    CATEGORY = "BSAI/H3 Film Factory"
    OUTPUT_NODE = True

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        # v14.152: 带 **kwargs 的 VALIDATE_INPUTS 让 ComfyUI 跳过所有参数的
        # min/max 校验与 combo 选项校验（execution.py 1032/1060 行分支），
        # 使老版本导出的工作流（temporal_overlap_tokens='global_inherit'、
        # semantic_bridge_alpha=''、semantic_bridge_adapter=False、shift_audio=0.0
        # 等历史遗留值）能进入 extend()，由函数内容错逻辑统一归一到默认最低档。
        # 真正的类型/语义校验在 extend() 入口处完成。
        return True

    @staticmethod
    def _resolve_asset_library_refs(clips, asset_library):
        """Resolve @图N/@视频N/@音频N tags in clip prompts against the connected Asset Library.
        Replaces @图N with <Picture N>, @视频N with <Video N>, @音频N with <Audio 1>.
        Also loads referenced images as internal refs and audio as ref_audio path.

        Returns (clips_with_resolved_prompts, resolved_image_paths, resolved_audio_paths,
                 clip_asset_paths, speaker_audio_map, picture_asset_map).
        speaker_audio_map: dict {图_index (int): audio_path (str)} — @图N → @音频N 声音参考绑定。
        picture_asset_map: dict {<Picture N> ref_num (int): @图N tag_num (int)} —
        prompt 里 @图N 已被替换成 <Picture N>，对话台词解析需要反查回资产索引（v14.281）。
        """
        if not asset_library:
            print("[H3 Extender] asset_library is empty or None, skipping @图N resolution")
            return clips, [], [], [], {}, {}

        # asset_library can be a dict with 'images'/'videos'/'audios' lists
        if isinstance(asset_library, dict):
            images = asset_library.get("images", [])
            videos = asset_library.get("videos", [])
            audios = asset_library.get("audios", [])
        elif isinstance(asset_library, (list, tuple)):
            images = list(asset_library)
            videos = []
            audios = []
        else:
            print(f"[H3 Extender] asset_library is unexpected type: {type(asset_library)}")
            return clips, [], [], [], {}, {}

        print(f"[H3 Extender] asset_library received: {len(images)} images, {len(videos)} videos, {len(audios)} audios")
        for i, img in enumerate(images[:3]):
            if isinstance(img, dict):
                print(f"[H3 Extender]   image[{i}]: index={img.get('index')}, name={img.get('name')}, path={img.get('path', '')[:80]}")

        import re
        resolved_image_paths = []
        resolved_audio_paths = []
        # v1.99: 每个 clip 依赖的资产图路径（per-clip 失效用）
        clip_asset_paths = [[] for _ in clips]
        # v14.280: @图N ↔ @音频N 声音参考绑定 {图index: audio_path}
        speaker_audio_map = {}
        # v14.281: <Picture ref_num> → @图N tag_num 反查表（对话台词解析用）
        picture_asset_map = {}

        def _find_asset_by_index(items, tag_num):
            """Find an asset by its 'index' field, falling back to positional."""
            for item in items:
                if isinstance(item, dict) and item.get("index") == tag_num:
                    return item
            idx = tag_num - 1
            if 0 <= idx < len(items):
                return items[idx]
            return None

        for clip_idx, clip in enumerate(clips):
            prompt = clip.get("prompt", "")
            original_prompt = prompt

            # Resolve @图N -> load image path, replace tag with <Picture N>
            # Use re.sub to avoid str.replace bug with multi-digit tags (e.g. @图1 in @图10)
            def _replace_image_tag(m):
                tag_num = int(m.group(1))
                img_entry = _find_asset_by_index(images, tag_num)
                if img_entry is None:
                    print(f"[H3 Extender] @图{tag_num} not found in asset library (has {len(images)} images)")
                    return m.group(0)
                img_path = img_entry.get("path", img_entry.get("filename", "")) if isinstance(img_entry, dict) else str(img_entry)
                if not img_path:
                    print(f"[H3 Extender] @图{tag_num} found but path is empty")
                    return m.group(0)
                if img_path not in resolved_image_paths:
                    resolved_image_paths.append(img_path)
                if img_path not in clip_asset_paths[clip_idx]:
                    clip_asset_paths[clip_idx].append(img_path)
                # v14.280: @图N 自动查找 @音频N 作为声音参考
                aud_entry = _find_asset_by_index(audios, tag_num)
                if aud_entry is not None and tag_num not in speaker_audio_map:
                    aud_path = aud_entry.get("path", aud_entry.get("filename", "")) if isinstance(aud_entry, dict) else str(aud_entry)
                    if aud_path:
                        speaker_audio_map[tag_num] = aud_path
                        print(f"[H3 Extender] 🎤 @图{tag_num} ↔ @音频{tag_num} voice ref bound: {aud_path[-60:]}")
                ref_num = resolved_image_paths.index(img_path) + 1
                picture_asset_map[ref_num] = tag_num
                return f"<Picture {ref_num}>"
            prompt = re.sub(r'@(?:图|img)(\d+)', _replace_image_tag, prompt, flags=re.IGNORECASE)

            # Resolve @视频N -> <Video N>
            def _replace_video_tag(m):
                tag_num = int(m.group(1))
                vid_entry = _find_asset_by_index(videos, tag_num)
                if vid_entry is None:
                    return m.group(0)
                return f"<Video {tag_num}>"
            prompt = re.sub(r'@(?:视频|vid)(\d+)', _replace_video_tag, prompt, flags=re.IGNORECASE)

            # Resolve @音频N -> load audio path
            def _replace_audio_tag(m):
                tag_num = int(m.group(1))
                aud_entry = _find_asset_by_index(audios, tag_num)
                if aud_entry is None:
                    return m.group(0)
                aud_path = aud_entry.get("path", aud_entry.get("filename", "")) if isinstance(aud_entry, dict) else str(aud_entry)
                if aud_path and aud_path not in resolved_audio_paths:
                    resolved_audio_paths.append(aud_path)
                return "<Audio 1>"
            prompt = re.sub(r'@(?:音频|aud)(\d+)', _replace_audio_tag, prompt, flags=re.IGNORECASE)

            # v14.313: 参考图按角色分纪律注入。此前不区分参考图类型，所有 <Picture N>
            # 都被声明成"角色多视图设定板 + 服装参照"，产品/场景参考图因此没有绑定
            # 指令（实测 @图4 香薰蜡烛被画成香水瓶）。这里按标签前置词判定
            # 人物/物品/场景，分别注入对应纪律。
            # v14.324: 纪律文本不再携带 <Picture N> 编号 —— 编号在每段参考图重映射
            # 时会被整段丢弃, 纪律句会退化成空分隔符, 还会抢占每段 9 个参考图槽位。
            if "<Picture " in prompt and "【参考图纪律】" not in prompt:
                _roles = _classify_picture_roles(prompt)
                _person = sorted(s for s, r in _roles.items() if r == "person")
                _props = sorted(s for s, r in _roles.items() if r == "prop")
                _scenes = sorted(s for s, r in _roles.items() if r == "scene")
                _heads = []
                if _person:
                    _heads.append(_REF_SHEET_RULE)
                    _heads.append(_OUTFIT_LOCK_RULE)
                if _props:
                    _heads.append(_PROP_LOCK_RULE)
                if _scenes:
                    _heads.append(_SCENE_LOCK_RULE)
                if _heads:
                    prompt = "".join(_heads) + prompt
                    print(f"[H3 Extender] v14.324 clip[{clip_idx}] 参考图角色判定: "
                          f"人物={_person} 物品={_props} 场景={_scenes}（纪律按角色注入，不绑定编号）")

            if prompt != original_prompt:
                print(f"[H3 Extender] clip[{clip_idx}] prompt resolved: '{original_prompt[:60]}' -> '{prompt[:60]}'")
            clip["prompt"] = prompt

        print(f"[H3 Extender] resolved {len(resolved_image_paths)} image paths, {len(resolved_audio_paths)} audio paths")
        for i, p in enumerate(resolved_image_paths):
            print(f"[H3 Extender]   resolved_img[{i}]: {p}")
        if speaker_audio_map:
            print(f"[H3 Extender] 🎤 Speaker-audio bindings: {speaker_audio_map}")

        return clips, resolved_image_paths, resolved_audio_paths, clip_asset_paths, speaker_audio_map, picture_asset_map

    # ── v14.280: 自动多人对话声音克隆 ──────────────────────────────────────
    def _try_auto_dialogue_tts(self, clips, tts_model, speaker_audio_map, asset_library, picture_asset_map=None):
        """从分镜脚本自动提取对话台词 → 调用 IndexTTS 多人对话合成 → 返回完整 AUDIO。

        触发条件（全部满足才执行）:
          1) tts_model 已连接
          2) speaker_audio_map 非空（资产库 @图N ↔ @音频N 有绑定）
          3) clips 中能解析出 ≥1 行对话台词

        Returns:
            AUDIO dict 或 None（不满足条件时返回 None，让调用方跳过）
        """
        import os as _os
        import sys as _sys
        import re as _re
        import torchaudio

        try:
            import soundfile as sf  # 可选兜底：torchaudio 解不了 mp3 时才用
        except ImportError:
            sf = None

        # 条件 1: 有 tts_model
        if tts_model is None:
            return None

        # 条件 2: 资产库有音频参考（speaker_audio_map 来自 @图N ↔ @音频N 绑定，
        # 或直接有 audios 列表）
        asset_audios = []
        if isinstance(asset_library, dict):
            asset_audios = asset_library.get("audios", [])
        ref_audio_paths = list(speaker_audio_map.values()) if speaker_audio_map else [
            a.get("path") for a in asset_audios if isinstance(a, dict) and a.get("path")
        ]
        if not ref_audio_paths:
            print("[H3 AutoTTS] 资产库中没有 @音频N 参考 → 跳过自动对话合成")
            return None

        # 条件 3: 从 clips prompt 中提取对话台词（按 clip 分组，逐段合成本段音频，
        # 这样 clip 时长 = 本段台词音频时长，音画逐段严格对齐，不会出现
        # "clip1 画面是角色A、音频却已经开始播角色B" 的错位）。
        # 注意 clips 到这里时 @图N 已被 _resolve_asset_library_refs 替换成 <Picture N>，
        # 因此除 @图N 外还必须识别 <Picture N>（v14.281）。
        _pc_map = picture_asset_map or {}
        _DIALOGUE_LINE_RE = _re.compile(
            r"^\s*(?:"
            r"[【\[]([^】\]]{1,20})[】\]]\s*[:：]?\s*"            # 【角色名】台词
            r"|(\S{1,20})\s*[:：]\s+"                            # 角色名: 台词
            r"|@\s*(?:图|音频|img|aud)\s*(\d+)\s*[:：]\s*"        # @图N: 台词
            r"|<Picture\s+(\d+)>\s*[:：]\s*"                      # <Picture N>: 台词
            r"|<Audio\s+(\d+)>\s*[:：]\s*"                        # <Audio N>: 台词
            r")(.+?)\s*$"
        )

        _non_dialogue_skip = {"镜头", "景别", "构图", "画面", "音效", "音乐",
                              "BGM", "bgm", "环境音", "描述", "运动", "转场",
                              "时长", "秒", "灯光", "光影", "场景", "画面描述",
                              "参考图纪律", "服装锁定纪律"}
        # [分镜1]：xxx / 【镜头2】xxx 这类分段标题会被方括号分支误当成台词行
        _shot_header_re = _re.compile(r"^(?:分镜|镜头|Shot|shot|SHOT)\s*[\d一二三四五六七八九十]*$")
        _dialogue_by_clip = []
        for _c in clips or []:
            _lines = []
            prompt = _c.get("prompt", "") if isinstance(_c, dict) else str(_c)
            for _ln in prompt.splitlines():
                _ln = _ln.strip()
                if not _ln:
                    continue
                m = _DIALOGUE_LINE_RE.match(_ln)
                if not m:
                    continue
                if m.group(1):
                    speaker, text = m.group(1), m.group(6)
                    if speaker in _non_dialogue_skip or _shot_header_re.match(speaker):
                        continue
                    _lines.append((speaker, text))
                elif m.group(2):
                    speaker, text = m.group(2), m.group(6)
                    if speaker in _non_dialogue_skip or _shot_header_re.match(speaker):
                        continue
                    _lines.append((speaker, text))
                elif m.group(3):
                    _lines.append((f"asset_{int(m.group(3))}", m.group(6)))
                elif m.group(4):
                    _asset_idx = int(_pc_map.get(int(m.group(4)), int(m.group(4))))
                    _lines.append((f"asset_{_asset_idx}", m.group(6)))
                else:
                    _lines.append((f"asset_{int(m.group(5))}", m.group(6)))
            _dialogue_by_clip.append(_lines)

        _total_lines = sum(len(_l) for _l in _dialogue_by_clip)
        if not _total_lines:
            print("[H3 AutoTTS] 分镜脚本中没有识别到对话台词 → 跳过自动合成")
            return None

        print(f"[H3 AutoTTS] 解析到 {_total_lines} 行对话台词（{len(clips)} 个 clip），"
              f"使用 {len(ref_audio_paths)} 个参考音色")

        # 构造 speaker_map: asset_idx → ref_index（在 ref_audio_paths 列表中的位置）
        _spk_map_entries = []
        if speaker_audio_map:
            _path_to_ref_idx = {p: i + 1 for i, p in enumerate(ref_audio_paths)}
            for _img_idx, _aud_path in sorted(speaker_audio_map.items()):
                _ref_idx = _path_to_ref_idx.get(_aud_path)
                if _ref_idx is not None:
                    _spk_map_entries.append(f"asset_{_img_idx}={_ref_idx}")

        # 加载 voice_clone_node 模块
        _vc_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)))
        if _vc_dir not in _sys.path:
            _sys.path.insert(0, _vc_dir)
        from voice_clone_node import BSAIDialogueVoiceClone

        # 把参考音频文件加载成 AUDIO dict
        def _load_ref_wav(path):
            try:
                wf, sr = torchaudio.load(path)
            except Exception:
                if sf is None:
                    raise
                data, sr = sf.read(path)
                wf = torch.from_numpy(data).float()
                if wf.dim() == 1:
                    wf = wf.unsqueeze(0)
                else:
                    wf = wf.T
            if wf.shape[0] > 1:
                wf = wf.mean(dim=0, keepdim=True)
            return {"waveform": wf.unsqueeze(0), "sample_rate": sr}

        _ref_audio_objs = [_load_ref_wav(p) for p in ref_audio_paths]
        _clone = BSAIDialogueVoiceClone()
        _spk_map_str = ",".join(_spk_map_entries)

        # 逐 clip 合成 → 每段音频长度即该 clip 的时长
        _clip_waves = []
        _clip_durations = []
        _clip_sr = None
        for _ci, _lines in enumerate(_dialogue_by_clip):
            if not _lines:
                _clip_waves.append(None)
                _clip_durations.append(0.0)
                continue
            _script_lines = []
            for _s, _t in _lines:
                if _s.startswith("asset_"):
                    _script_lines.append(f"@图{_s.split('_')[-1]}: {_t}")
                else:
                    _script_lines.append(f"{_s}: {_t}")
            _kwargs_call = {
                "tts_model": tts_model,
                "dialogue_script": "\n".join(_script_lines),
                "speaker_map": _spk_map_str,
                "lang": "ZH",
                "duration_factor": 1.0,
                # v14.296: 抢话修复——clip 内换人留 250ms 节拍；crossfade 80→30ms
                # 避免两个说话人的声音在接缝处叠化(唇形模型会听到双人混音)。
                "crossfade_ms": 30,
                "pause_ms": 250,
            }
            for _i, _ref in enumerate(_ref_audio_objs[:6], 1):
                _kwargs_call[f"ref_audio_{_i}"] = _ref
            try:
                _seg_audio, _seg_log = _clone.synthesize_dialogue(**_kwargs_call)
            except Exception as _seg_e:
                print(f"[H3 AutoTTS] clip{_ci + 1} 台词合成失败（该段将关闭渲染）：{_seg_e}")
                _clip_waves.append(None)
                _clip_durations.append(0.0)
                continue
            print(f"[H3 AutoTTS] clip{_ci + 1} 合成完成：\n{_seg_log}")
            _w = _seg_audio["waveform"]
            _sr = int(_seg_audio["sample_rate"])
            if _clip_sr is None:
                _clip_sr = _sr
            elif _sr != _clip_sr:
                _rs = torchaudio.transforms.Resample(_sr, _clip_sr)
                _w = _rs(_w[0]).unsqueeze(0)
            # v14.296: 段尾追加 0.5s 换气静音（跨段抢话修复）。
            # context_enabled=True 时下一段的口型音频段 = [边界-1.625s, 边界+净时长)，
            # 重叠窗口会吃进本段末尾——若本段末尾仍是上一人台词，模型会把旧声音
            # 贴到新画面的嘴上（女声口型配男声="抢话"）。追加静音尾后：
            #   本段视频尾部 = 无人说话的换气节拍（口型闭合）；
            #   下一段 context 重叠窗口吃到的是静音，新说话人在新帧干净开场。
            _tail = int(round(0.5 * _clip_sr))
            _w = torch.cat(
                [_w, (torch.randn(_w.shape[0], _w.shape[1], _tail) * 3e-4).to(dtype=_w.dtype)],
                dim=-1)
            # 台词音频按 H3 帧网格补齐(帧数 %17==5)，让 clip 时长与音频段严格等长。
            # 补的是极低幅噪声(-70dB 级)而非精确 0：_split_lip_audio_by_clips 会剔除
            # >=80ms 的精确全零段，纯零填充会被删掉并让后续 clip 音频整体前移。
            _frames = _duration_to_frames(float(_w.shape[-1]) / float(_clip_sr))
            _pad = int(round(float(_frames) / float(FPS) * _clip_sr)) - int(_w.shape[-1])
            if _pad > 0:
                _noise = torch.randn(_w.shape[0], _w.shape[1], _pad) * 3e-4
                _w = torch.cat([_w, _noise.to(dtype=_w.dtype)], dim=-1)
            _clip_waves.append(_w)
            _clip_durations.append(float(_w.shape[-1]) / float(_clip_sr))

        if _clip_sr is None:
            print("[H3 AutoTTS] 全部 clip 台词合成失败 → 跳过自动合成")
            return None

        _parts = [_w for _w in _clip_waves if _w is not None]
        _full = _parts[0] if len(_parts) == 1 else torch.cat(_parts, dim=-1)
        print(f"[H3 AutoTTS] 多人对话音频拼接完成：总长 "
              f"{float(_full.shape[-1]) / float(_clip_sr):.2f}s, 逐段 "
              f"{'/'.join(f'{d:.2f}s' if d > 0 else 'off' for d in _clip_durations)}")
        return {"waveform": _full.cpu(), "sample_rate": _clip_sr}, _clip_durations

    def extend(self, model, clip, vae, **kwargs):
        # v14.347: exact sigma 开关只属于第 35 档, 每次进入 extend 先复位,
        # 免得上一轮跑了第 35 档之后, 别的档位偷偷继承"真实 denoise"手感。
        global _SIGMAS_EXACT
        _SIGMAS_EXACT = False
        # v1.21: keys are pure English now, direct kwargs.get()
        run_mode = kwargs.get("run_mode")
        width = kwargs.get("width")
        height = kwargs.get("height")
        ref_image_size = kwargs.get("ref_image_size")
        # v2.58b: 强制把 match 改成 max，避免参考图太大模型直接复制参考图内容
        # (match 模式参考图和输出一样大，模型会直接复制参考图，不听提示词)
        if ref_image_size == "match":
            ref_image_size = "max"
            print("[H3 Extender] v2.58b: 强制 ref_image_size 从 match 改成 max (避免参考图太大污染提示词)")
        steps = kwargs.get("steps")
        sampler_name = kwargs.get("sampler_name")
        scheduler = kwargs.get("scheduler")
        # P0/P2 (2026-10-17): 双轨迹采样 + TST 少步数补偿参数
        dual_track_shift = bool(kwargs.get("dual_track_shift", True))
        shift_video = float(kwargs.get("shift_video", 12.0))
        shift_audio = float(kwargs.get("shift_audio", 3.0))
        # v14.152: 老工作流可能存 0.0（旧版 min 允许 0），ModelSamplingAV.audio_scale
        # = shift/audio_shift 会除零。<=0 一律映射为 None（audio_scale=1.0，关闭音频
        # shift，即最低档），保证兼容且不崩。
        if shift_audio <= 0.0:
            shift_audio = None
            print(f"[H3 Extender] shift_audio<=0 已映射为 None（关闭音频 shift，最低档）", flush=True)
        selflift_tst_enable = bool(kwargs.get("selflift_tst_enable", True))
        selflift_tst_tau = float(kwargs.get("selflift_tst_tau", 0.2))
        denoise = kwargs.get("denoise")
        context_length = kwargs.get("context_length")
        audio_context_length = kwargs.get("audio_context_length")
        clips_json = kwargs.get("clips_json")
        resolution_mode = kwargs.get("resolution_mode", "auto_from_ref")
        megapixels = kwargs.get("megapixels", DEFAULT_MEGAPIXELS)
        refs_json = kwargs.get("refs_json", None)
        output_mode = kwargs.get("output_mode", "none")
        filename_prefix = kwargs.get("filename_prefix", "H3_Extender")
        prompt_pack = kwargs.get("prompt_pack", None)
        asset_library = kwargs.get("asset_library", None)
        # 清单 widget 被清空/另存丢失时, 回读磁盘资产库兜底, 避免 @图N/@视频N 静默断链。
        if _asset_library_is_empty(asset_library):
            _disk_lib = _rebuild_asset_library_from_disk()
            if _disk_lib and not _asset_library_is_empty(_disk_lib):
                print(f"[BSAI AssetLibrary] 节点清单为空, 已从磁盘兜底加载: "
                      f"{len(_disk_lib['images'])} 图 / {len(_disk_lib['videos'])} 视频 / "
                      f"{len(_disk_lib['audios'])} 音频")
                asset_library = _disk_lib
        prompt_source = kwargs.get("prompt_source", None)
        output_image_audio = kwargs.get("output_image_audio", True)
        block_cache = kwargs.get("block_cache", False)
        block_cache_threshold = kwargs.get("block_cache_threshold", 0.12)
        block_cache_device = kwargs.get("block_cache_device", "cpu")
        ref_cache = kwargs.get("ref_cache", True)
        cache_dit = kwargs.get("cache_dit", False)
        clip_select_enable = kwargs.get("clip_select_enable", False)
        clip_select = kwargs.get("clip_select", "all")
        restore_cache = kwargs.get("restore_cache", False)
        pause_enable = kwargs.get("pause_enable", False)
        pause_timeout = kwargs.get("pause_timeout", 5.0)
        refine_enable = kwargs.get("refine_enable", True)
        refine_denoise = kwargs.get("refine_denoise", 0.45)
        refine_steps = kwargs.get("refine_steps", 2)
        refine_upscale_factor = kwargs.get("refine_upscale_factor", 2.0)
        refine_upscaler_model = kwargs.get("refine_upscaler_model", "(bilinear interpolation, no model)")
        refine_align_to = int(kwargs.get("refine_align_to", 40))
        refine_audio_denoise = float(kwargs.get("refine_audio_denoise", 0.0))
        # v14.238 MiniMaxH3 Director 极速双采移植参数:
        #   refine_sampler    —— 二采采样器独立选择(默认跟随一采; Director 配方 = euler)
        #   refine_sigmas     —— 外接 SIGMAS 端口(未接时 None, 内部 beta 调度)
        #   director_fast_*_mp —— 极速档一采低清画布/目标画布(百万像素)
        refine_sampler = str(kwargs.get("refine_sampler", "inherit") or "inherit")
        refine_sigmas = kwargs.get("refine_sigmas", None)
        try:
            _dff_first_mp = float(kwargs.get("director_fast_first_mp", 0.4) or 0.4)
        except (TypeError, ValueError):
            _dff_first_mp = 0.4
        try:
            _dff_target_mp = float(kwargs.get("director_fast_target_mp", 2.0) or 2.0)
        except (TypeError, ValueError):
            _dff_target_mp = 2.0
        # v14.364 修复: _rp_mode 必须先解析再判定。v14.360 把「档位决定换脸」的判定
        # 写在本段参数解析区(此处), 而 _rp_mode 的赋值原本在 12087 行**之后**, 于是这一行
        # 读到的是函数内尚未赋值的局部变量, 每次调用必抛:
        #   UnboundLocalError: cannot access local variable '_rp_mode'
        # 离线函数级验证碰不到它, 只有真跑节点才会炸。这里补一次同源预解析(与
        # 12087-12089 完全一致的归一口径); 12087 处会再赋一次相同的值, 无副作用。
        _rp_mode = str(kwargs.get("render_pipeline", "") or "")
        _rp_mode = _RENDER_PIPELINE_EN2ZH.get(_rp_mode, _rp_mode)
        # v14.360: 换脸工序由**档位**决定，不占 widget、不改参数位置、不读环境变量。
        # 选「Viggle Remake + 逐帧换脸」档 → 每段出片后换脸；选普通 Viggle 档 → 绝不换脸。
        _viggle_faceswap_on = (_rp_mode == _VIGGLE_RP_FS_LABEL)
        _viggle_faceswap_model = "128"   # inswapper_128: clip1 全段相似度 0.792, 实测最优
        # v14.83 对口型×二采组合预设（优先于 refine_audio_denoise 原始值）
        refine_lipsync_mode = str(kwargs.get("refine_lipsync_mode", "Lock lip-sync (recommended)"))
        if refine_lipsync_mode in ("Audio redraw 0.7", "音频参与重绘0.7"):
            refine_audio_denoise = 0.7
        elif refine_lipsync_mode in ("Full audio redraw 1.0", "音频全重绘1.0"):
            refine_audio_denoise = 1.0
        else:
            refine_audio_denoise = 0.0
        # v14.194 音频重绘防护: 官方音频≥12步可用下限——一采步数<12 时二采音频重绘
        # (≥0.5) 会在低步数上重画音频 latent, 实测产出恒定低频轰鸣/底噪/失真
        # (h3_clip_250: ~95-200Hz 占~60%能量, 全程无静音帧)。不改行为,
        # 仅提示改走"直播配音高清"(一采12步+音频0.7) 或对口型×二采=锁定音频。
        if refine_enable and float(refine_audio_denoise) >= 0.5:
            try:
                _fp_steps = max(1, int(steps))
            except Exception:
                _fp_steps = 12
            if _fp_steps < 12:
                print(f"[H3 Extender] ⚠ v14.194: 一采 {_fp_steps} 步(<官方音频12步下限) + "
                      f"二采音频重绘 {float(refine_audio_denoise):.1f} —— 低步数重画音频 latent "
                      f"易产恒定低频轰鸣/底噪/失真; 建议改用\"直播配音高清\"管道 "
                      f"(一采12步+音频0.7) 或对口型×二采=锁定音频", flush=True)
        # v14.83 像素超分旁支（双开关，默认关）+ v14.84 模式预设
        upscale_per_clip = bool(kwargs.get("upscale_per_clip", False))
        upscale_final = bool(kwargs.get("upscale_final", False))
        upscale_mode = str(kwargs.get("upscale_mode", "Balanced (quality+speed)"))
        upscale_engine = str(kwargs.get("upscale_engine", "auto"))
        upscale_factor = float(kwargs.get("upscale_factor", 2.0))
        upscale_model = str(kwargs.get("upscale_model", "realesr-general-x4v3.pth"))
        upscale_tile = int(kwargs.get("upscale_tile", 0))
        upscale_batch = int(kwargs.get("upscale_batch", 4))
        upscale_fp16 = bool(kwargs.get("upscale_fp16", True))
        upscale_face_restore = bool(kwargs.get("upscale_face_restore", False))
        _up_factor, _up_engine = _ff_resolve_upscale_mode(
            upscale_mode, upscale_factor, upscale_engine
        )
        # v2.24 模型环境音开关 / face_lock_mode（v14.83 起参数化；读取并传入渲染配置）
        env_audio_enable = str(kwargs.get("env_audio_enable", "global_inherit"))
        env_audio_gain = float(kwargs.get("env_audio_gain", 0.15))
        # v14.221: 保脸模式三态枚举。兼容旧工作流布尔值：true->auto(常规保脸)，false->off。
        face_lock_mode = kwargs.get("face_lock_mode", "off")
        if isinstance(face_lock_mode, bool):
            face_lock_mode = "auto (face-lock)" if face_lock_mode else "off"
        face_lock_mode = str(face_lock_mode or "off")
        face_refine_enabled = face_lock_mode.startswith("refine")
        if face_refine_enabled:
            print("[H3 Extender] 🎭 保脸-小脸修复模式开启：出片前对每个分镜运行 H3 FaceRefine 局部重绘")
        # v14.340: 音频引导人脸/嘴型修复（TaoMate-FVSR）。后处理在分镜 mp4 上做，
        # 用片段自带音轨（lip_audio/lip_voice 驱动时就是那句台词）重建嘴部细节。
        face_fvrs_enabled = face_lock_mode.startswith("fvrs")
        if face_fvrs_enabled:
            _fvrs_c = _fvrs_cfg()
            print("[H3 Extender] 🎙️ TaoMate-FVSR 音频引导修复开启：逐分镜 512 人脸重建 "
                  "(steps=%d, audio_cfg=%.1f, ref_cfg=%.1f, %.0f GiB 预算)"
                  % (_fvrs_c["steps"], _fvrs_c["audio_cfg"], _fvrs_c["ref_cfg"], _fvrs_c["budget_gib"]))
        # v14.158 (2026-10-21): BSAI 一镜到底旁支模式。off 时零影响（默认）；
        # on 时：①强制段间 motion context（Add Guide 等效锚点引导）
        #       ②每段提示词自动注入一镜到底镜头指令
        #       ③合并改无缝 concat（零转场）
        one_shot_mode = str(kwargs.get("one_shot_mode", "off (storyboard)") or "off (storyboard)")
        one_shot_enabled = one_shot_mode.startswith("on")
        # v14.185: 一镜到底采样档 —— 单采无缝(默认)/双采高清(接缝风险)。
        # 参考 B站 Motion Context V2 (BV1T9ho6HEKP) 实测: 双采 latent 续链在接缝
        # 产生像素漂移(段间模糊/抖动), 单采接缝干净。
        one_shot_sampling = str(kwargs.get("one_shot_sampling", "Single-pass seamless (recommended)") or "Single-pass seamless (recommended)")
        # v14.259: 英文标签归一回旧中文内部值(老工作流中文原值不在表中, 原样透传)
        one_shot_sampling = _ONE_SHOT_SAMPLING_EN2ZH.get(one_shot_sampling, one_shot_sampling)
        one_shot_single_pass = one_shot_enabled and not one_shot_sampling.startswith("双采")
        # v14.215 (2026-10-26): 新增第三档「双采无缝 (8+4)」—— 一镜到底照跑二采,
        # 同时修掉双采接缝漂移的根因: 段头锁 keep 用的"上一段尾 latent"在双采下是
        # 二采放大后的 2x, 本段一采 latent 是 1x, 直接赋值 shape 不匹配 → 整块被
        # except 吞掉 → 噪声延续 + 段头锁 keep 全部失效 → 裁掉重叠区后接缝画面跳变。
        # one_shot_seamless_dual = 双采 + 接缝锚点修复(不跳过二采)
        one_shot_seamless_dual = one_shot_enabled and one_shot_sampling.startswith("双采无缝")
        # v14.272 (2026-11-01): 第四档「双采无缝 2K (8+4)」—— 一镜到底 + 双采,
        # 且是自带配方的档: 一采 8 步(蒸馏契约) + 二采 4 步(denoise 0.45)。
        # v14.276: 二采倍率改按「单次调用 token 预算 350k」向下取(960x544 → x1.39),
        # 整段一次采样; 2K 在该卡上只能靠时间分块, 分块会闪烁+碎花, 已放弃。
        one_shot_dual_2k = (one_shot_enabled and one_shot_sampling.startswith("双采无缝")
                            and "2K" in one_shot_sampling)
        # v14.159: 一镜到底×歌曲自动分 CLIP 的每段目标时长(秒); 0=关闭自动分
        try:
            one_shot_clip_duration = int(kwargs.get("one_shot_clip_duration", 12) or 12)
        except (TypeError, ValueError):
            one_shot_clip_duration = 12
        if one_shot_enabled:
            print("[H3 Extender] 🎬 一镜到底旁支模式已启用：无缝 concat 零转场 + 镜头跟随指令注入 + 强制 motion context")
            # v14.185: 提示词纪律引导(Motion Context V2 实测规则, 不改用户提示词)。
            print("[H3 Extender] 📝 一镜到底提示词纪律：①接缝裁切 22 帧(≈0.92s)，段内时间戳想落在 T 请写 T+0.92s；"
                  "②续写段开头只写承接(同节奏/同机位/同光照)，勿引入新景物名词；"
                  "③接缝落在运动中段(行走/奔跑中)，勿落在门槛/事件点，渐进式运镜勿跨接缝；"
                  "④台词约每 2.5s 一句短句，按句子切分段。")
        # v14.168 (2026-10-22): FastH3 Omni 8步蒸馏旁支模式。
        # 选择后 = 单采管道: 跳过二采(Self-Lift refine), 一采强制 8 步 + denoise 1.0
        # (官方 FastVideo FastH3 Omni 契约: 8步蒸馏 guidance 1.0 shift 12/3, 改步数掉画质)。
        # 模型/文本编码器/VAE 由工作流 Loader 提供(需换 fasth3_omniref_8step_pruned_int8_convrot),
        # VSA 稀疏由工作流 BlockSparseAttention 节点挂载 —— 本模式只改采样管道, 不碰模型图。
        _render_pipeline = str(kwargs.get("render_pipeline", "Sol-H3 Self-Lift Dual-Pass (default)") or "Sol-H3 Self-Lift Dual-Pass (default)")
        # v14.259: 英文标签归一回旧中文内部值(老工作流中文原值不在表中, 原样透传)
        _render_pipeline = _RENDER_PIPELINE_EN2ZH.get(_render_pipeline, _render_pipeline)
        # v14.211: 「FastH3 Omni × SelfLift 超分」是 Omni 的渐进双采版, 不走单采强制(保留二采)。
        omni_8step_mode = _render_pipeline.startswith("FastH3 Omni") and "SelfLift" not in _render_pipeline
        if omni_8step_mode:
            # ① 跳过二采 —— 一采 latent 直接解码, 单采直出
            refine_enable = False
            # ② 一采强制 8 步蒸馏契约 (官方固定 8, 4 步掉画质)
            try:
                _steps_raw = int(steps or 8)
            except (TypeError, ValueError):
                _steps_raw = 8
            if _steps_raw != 8:
                print(f"[H3 Extender] v14.168 Omni 8步单采: 一采 steps {_steps_raw} -> 强制 8 (官方蒸馏契约)")
                steps = 8
            # ③ 完整蒸馏 = denoise 1.0 (Omni 无 latent 继承, 从零去噪)
            try:
                _denoise_raw = float(denoise or 1.0)
            except (TypeError, ValueError):
                _denoise_raw = 1.0
            if _denoise_raw != 1.0:
                print(f"[H3 Extender] v14.168 Omni 8步单采: denoise {_denoise_raw} -> 强制 1.0 (完整蒸馏)")
                denoise = 1.0
            print("[H3 Extender] 🚀 FastH3 Omni 8步单采模式已启用：跳过二采(Self-Lift)，一采 8 步蒸馏直出。"
                  "确认 Loader 使用 fasth3_omniref_8step_pruned_int8_convrot.safetensors + BlockSparseAttention(VSA keep_percent=10)。")
        tiled_refine = bool(kwargs.get("tiled_refine", False))
        tile_count = int(kwargs.get("tile_count", 4))
        # v14.181 (2026-10-23): 回滚 v14.180 的 overlap 钳制 64px -> 恢复 128px。
        # 实测崩坏(分镜模式, 22:00 渲染): v14.179 声称 overlap 64 的接缝由
        # motion-context keyframe 对齐兜底, 但该兜底仅在一镜到底(one_shot=on)
        # 时注入; 分镜模式(one_shot=off) 无 keyframe 兜底, 64px 接缝完全裸露
        # -> 画面扭曲/变形/重影/分块严重。分镜模式必须保留 128px 接缝融合区。
        # 提速不能靠砍 overlap(接缝是画质底线), 正确路径=Sol-Attn 稀疏真生效。
        tile_overlap = min(int(kwargs.get("tile_overlap", 128)), 128)
        # v14.153: 二采省显存模式（spatial=v14.149 分块路径 / global=全上下文省显存）
        refine_mem_mode = str(kwargs.get("refine_mem_mode", "spatial (tiled, compatible)") or "spatial (tiled, compatible)")
        refine_mem_global = refine_mem_mode.startswith("global")
        # v2.02 (2026-09-19): 时间分块(沿 T 轴)二采, 区别于上面的空间分块(沿 H/W)。
        # chunk_tokens<=0 关闭(默认), 整段一次性二采; >0 时沿 T 切块逐段走已有(空间分块)采样器。
        # v2.56 (2026-09-21): 兼容旧工作流，新增参数空值容错
        def _safe_int(val, default=0):
            if val is None or val == "":
                return default
            try:
                return int(val)
            except (ValueError, TypeError):
                return default
        def _safe_float(val, default=0.0):
            if val is None or val == "":
                return default
            try:
                return float(val)
            except (ValueError, TypeError):
                return default
        # v14.153: 工作流传布尔 true(开但没给数字) 时自动用建议值 48 (T~107 只切 2~3 段),
        # 不再被 int(True)=1 -> 强制 16 -> 切成 13 段(每段重跑 4 步, 慢 4 倍)
        _tc_raw = kwargs.get("temporal_chunk_tokens")
        if _tc_raw is True or _tc_raw == "true" or _tc_raw == 1:
            temporal_chunk_tokens = 48
        else:
            temporal_chunk_tokens = _safe_int(_tc_raw, 0)
        if not _CHUNKED_DENOISE_ON and temporal_chunk_tokens > 0:
            print(f"[H3 Extender] v14.306 时间分块关闭 (工作流请求 {temporal_chunk_tokens} token/段 -> 整段一次; BSAI_H3_CHUNKED_DENOISE=1 可恢复)", flush=True)
            temporal_chunk_tokens = 0
        # v14.152: 兼容老工作流 'global_inherit' 等历史字符串 — 非数字一律取默认 8
        temporal_overlap_tokens = _safe_int(kwargs.get("temporal_overlap_tokens"), 8)
        # v2.19 Semantic-Bridge 语义桥(可开可关, 默认关). 小 MLP 残差混合 cond token.
        _sb_enable = bool(kwargs.get("semantic_bridge_enable", False))
        _sb_adapter_raw = kwargs.get("semantic_bridge_adapter", "")
        # v14.152: 老工作流可能存 False/None/空串 → 一律视为关闭（最低档）
        _sb_adapter = "" if _sb_adapter_raw in (False, None, "") else str(_sb_adapter_raw)
        # v14.152: 老工作流可能存空串 → 取默认 0.15（最低档）
        _sb_alpha = _safe_float(kwargs.get("semantic_bridge_alpha"), 0.15)
        _sb_mag = bool(kwargs.get("semantic_bridge_magnitude_match", True))
        sb_pack = {
            "enabled": _sb_enable and bool(_sb_adapter) and not _sb_adapter.startswith("("),
            "adapter": _sb_adapter,
            "alpha": _sb_alpha,
            "magnitude_match": _sb_mag,
        }
        # v1.83: 速度预设覆盖 (先于 REFINE-PARAMS 打印, 保证日志反映实际生效参数)
        speed_preset = str(kwargs.get("speed_preset", "Balanced"))
        # v14.259: 英文标签归一回旧中文内部值(老工作流中文原值不在表中, 原样透传)
        speed_preset = _SPEED_PRESET_EN2ZH.get(speed_preset, speed_preset)
        _sp_old = (steps, refine_steps, tile_count, refine_denoise)
        # v14.176: 武戏组合拳档启用 H3 17 帧块对齐 (YZ金鱼终极篇帧数公式 %17==5,
        # 防高动态武戏 latent 时间结构错位/果冻伪影)。档位分支命中后置 True,
        # lip 切段前统一把 clips duration 对齐到 17 帧块。
        _h3_align17 = False
        # v14.172: 渲染管道统一管理模型配方档 —— 非默认档时模式参数由渲染管道接管,
        # speed_preset 仅剩 7 项基础档。旧工作流遗留的配方档值(速度档里)仍由下方
        # speed_preset 兼容分支按值生效, 两源互斥不叠加。
        _rp_mode = str(kwargs.get("render_pipeline", "") or "")
        # v14.259: 英文标签归一回旧中文内部值(与上方 _render_pipeline 同源)
        _rp_mode = _RENDER_PIPELINE_EN2ZH.get(_rp_mode, _rp_mode)
        # v14.220 直播带货配音模式 01/02/03：识别模式键，并把三个新模式别名到
        # 「直播带货（全自动）」档以复用其已验证采样配方（12+4/latentx2/TST/
        # 分块/audio_context=0）。音频接线差异（三口用/不用）在下方音频接线段
        # 按 _ls_mode 强制处理。旧「直播带货（全自动）」档等价 02，历史不变。
        _ls_mode = _livestream_voice_mode_of(_rp_mode)
        if _ls_mode:
            _rp_mode = "直播带货（全自动）"
        # v14.182: HyperVAE 2x 像素翻倍因子 —— 仅「双采2K」档在分支内置 2.0,
        # 其余档保持 1.0 (声明输出尺寸 = 实际解码像素, 不放大)。
        _hv2x_decl = 1.0
        # v14.238 MiniMaxH3 Director 极速双采移植: 档位命中标志 —— 命中后
        # 分辨率接管(一采低清画布)与 refine factor 换算在解析完分辨率后执行。
        _director_fast_active = False
        # v14.281: 档位级"禁用自动时间分块"标志。MV 双采档按原版
        # temporal_chunk_tokens=0 整段一次二采, 由该标志传给 _sample_h3。
        _rp_no_temp_chunk = False
        # v14.339: HyperFlow H3 Flash 档位标志 —— 固定 4/6/8 步 + CFG 1.0 单前向,
        # 传给 _sample_h3 以跳过 H3 底座的音频 12 步自动提步。
        _rp_hyperflow = False
        # v14.210: 默认管道 "Sol-H3 Self-Lift 双采 (默认)" 名字里就是 "双采",
        # 理应自动 enable refine_enable——之前被行 6686 显式排除(作为"无管道"回退),
        # 导致用户选了默认管道但 UI toggle refine_enable=false 时二采被跳过。
        # 现在把默认管道也纳入 handler, 显式开 refine_enable 并保留用户其余参数。
        if _rp_mode:
            _rp_handled = True
            if _rp_mode == "Sol-H3 Self-Lift 双采 (默认)":
                # v14.210: 默认管道 = 双采, 强制 enable refine.
                # 不覆盖 steps/denoise 等数值——保留用户手动档设置, 只开关 enable.
                if not refine_enable:
                    refine_enable = True
                    print(f"[H3 Extender] v14.210 默认管道 Sol-H3 Self-Lift 双采: refine_enable=False -> True (双采管道理应开二采)")
                else:
                    print(f"[H3 Extender] v14.210 默认管道 Sol-H3 Self-Lift 双采: refine_enable 已 True")
            elif _rp_mode == "MV Dual-Pass (电影工厂 v3.2 原版)":
                # v14.280 (2026-11-02): MV 双采档 —— 参数完整照搬 BSAI_H3_Film_Factory
                # 电影工厂128分钟大电影版-示例工作流 v3.2-MV.json（v2.115 旧版插件
                # 保存的 45 键工作流, node 250 widgets_values 逐条反译确认）。
                # 一采 8 步(euler + simple) + 二采 4 步(denoise 0.45) + latent x2.0
                # 用 minimax_h3_latent_upscaler_3d_fp16.safetensors(SelfLift 同款 3D
                # latent 放大) + 40px 对齐改到 32px + 二采分块(4 块 256 overlap)
                # + audio_context_length=0(纯对口型档音频来自外部, 不进模型音频链)。
                # v14.281: 原版 temporal_chunk_tokens=0 = 整段一次二采, 禁止 v14.270
                # 自动时间分块接管(段间独立加噪 -> 接缝闪烁/碎花)。24GB 上每空间块
                # ~272k tokens 若确认活锁, 可临时设 BSAI_H3_MV_LEGACY_CHUNK=1 退回
                # 自动分块(不改代码, 需重启 ComfyUI)。
                _rp_no_temp_chunk = str(
                    os.environ.get("BSAI_H3_MV_LEGACY_CHUNK", "")).strip().lower() not in ("1", "true", "on")
                steps, refine_steps, tile_count, refine_denoise = 8, 4, 4, 0.45
                refine_enable = True
                refine_upscale_factor = 2.0
                refine_align_to = 32
                tiled_refine = True
                tile_overlap = 256
                audio_context_length = 0
                refine_audio_denoise = 0.0   # 对口型档音频由外部 lip_audio 提供, 锁定不重绘
                shift_video, shift_audio = 12.0, 3.0
                denoise = 1.0
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                    print(f"[H3 Extender] v14.280 MV双采(渲染管道): 采样器强制 euler (MV 档契约)")
                scheduler = "simple"
                # 自动选用 minimax_h3_latent_upscaler_3d_fp16.safetensors(同 MV 工作流)
                _mv_pick = None
                try:
                    for _nm in _ff_get_upscaler_models():
                        _nml = str(_nm).lower()
                        if "latent_upscaler_3d" in _nml and ("fp16" in _nml or "bf16" in _nml or "fp32" in _nml):
                            _mv_pick = _nm; break
                except Exception:
                    pass
                if _mv_pick is None:
                    try:
                        for _nm in _ff_get_upscaler_models():
                            if "latent_upscaler_3d" in str(_nm).lower():
                                _mv_pick = _nm; break
                    except Exception:
                        pass
                if _mv_pick:
                    refine_upscaler_model = _mv_pick
                    print(f"[H3 Extender] v14.280 MV双采(渲染管道): 二采放大模型 = '{_mv_pick}' (MV 工作流同款)")
                else:
                    refine_upscaler_model = "(bilinear interpolation, no model)"
                    print("[H3 Extender] ⚠️ v14.280 MV双采(渲染管道): 未探测到 H3 3D latent upscaler 模型,"
                          "二采放大走 bilinear 插值(画质略降), 请安装 Comfyui_Minimax_h3_latent_Upscaler")
                print("[H3 Extender] 🎵 v14.280 MV 双采 (电影工厂 v3.2 原版配方): "
                      f"一采 {int(steps)} 步 euler+simple + 二采 {int(refine_steps)} 步 "
                      f"(denoise {float(refine_denoise):.2f}, 3D latent upscaler x2.0, "
                      f"align {int(refine_align_to)}px, tiled {int(tile_count)}x{int(tile_overlap)}, "
                      f"audio_context_length=0) — 参数与 MV 示例工作流逐字一致")
                print("[H3 Extender] v14.281 MV 双采: 时间分块 "
                      + ("关闭(原版 temporal_chunk_tokens=0) — 二采整段一次 + 空间 4 块"
                         if _rp_no_temp_chunk else
                         "自动(BSAI_H3_MV_LEGACY_CHUNK 已置位) — v14.270 自动分块生效"))
            elif _rp_mode == "直播配音高清（音频≥12步）":
                # v14.179 (2026-10-23): 直播带货 ref_audio 配音模式专用配方。
                # 根因: H3 官方/社区实证 —— 音频 8 步最差, ≥12 步才可用;
                # 旧默认档 6~8 步一采 + 二采 audio_denoise=0.0 锁定音频 → 中文人声
                # 含混/吞音/切碎(VAD 10 段人声 ASR 仅转出 2 段 = 用户听到的"乱配音")。
                # 本档: 一采 12 步(音频达标) + 二采 4 步 + 音频参与重绘 0.7
                # (二采对音频重新加噪去噪, 精修人声清晰度, 同时保留 ref_audio 声线参考)。
                # 注意: 需配非 8 步蒸馏模型(如 minimax_h3_ref2va_int8_convrot),
                # 8 步蒸馏模型改 12 步会违背蒸馏契约掉画质。
                steps, refine_steps, tile_count, refine_denoise = 12, 4, 4, 0.45
                refine_audio_denoise = 0.7
                shift_video, shift_audio = 12.0, 3.0
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                    print(f"[H3 Extender] v14.179 直播配音高清(渲染管道): 采样器强制 euler + simple (配音精修配方)")
                print("[H3 Extender] 🎙️ 直播配音高清模式: 一采 12 步(音频≥12步官方可用下限) + 二采 4 步 + 音频重绘 0.7, 根治乱配音/含混吞音")
            elif _rp_mode == "FastH3-Trim":
                steps, refine_steps, tile_count, refine_denoise = 8, 4, 4, 0.45
            elif _rp_mode == "双采2K（HyperVAE 2x 解码）":
                # v14.182 (2026-10-23): T8 思路(B站 BV1aiaL61Eyu) 双采放大高分辨率。
                # 核心增量: ①二采 latent 不放大(factor=1.0) → 二采 token 少 ~4x,
                #    328s/步 -> ~80-90s/步 (同时根治 v14.180 64px overlap 接缝问题,
                #    因为压根不做 latent 放大, 无 tiles 接缝); ②解码用 HyperVAE 2x
                #    (encoder 16x 不变, decoder 32x pixel_shuffle 2x) → 二采 latent
                #    直接解成 2x 像素直出 2K, 全程只解码一次, 不增加采样显存。
                # v14.184 (2026-10-24): 回滚 v14.183 两处错误改动 ——
                #    v14.183 曾改: 一采 8->10 步 + 音频重绘 0.7->0.9 + denoise 0.45->0.5,
                #    实测 clip2(链 segment1) 音频彻底崩(VAD 0 段人声, ASR 置信度 0.43-0.70
                #    且前 8 秒无声) + 画质退化(10 步违背 FastH3 8 步蒸馏契约, 标签文字变糊)。
                #    根因: ①音频重绘 0.9 = 90% 重绘音频 latent + 二采仅 4 步 = 从噪声画
                #      4 步音频, 必崩(0.7 保留 30% 一采音频特征是安全线); ②一采 10 步
                #      破坏 8 步蒸馏契约掉画质。
                #    回滚: 一采 8 步(蒸馏契约) + denoise 0.45 + 音频重绘继承 w33(0.7)。
                #    吞音/噪点残余改用解码后处理(v14.184 双采2K 档解码端轻锐化降噪), 
                #    不动采样配方 —— 采样配方是已验证良好基线。
                steps, refine_steps, tile_count, refine_denoise = 8, 4, 4, 0.45
                shift_video, shift_audio = 12.0, 3.0
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                    print(f"[H3 Extender] v14.184 双采2K(渲染管道): 采样器强制 euler (T8 双采配方)")
                # 二采 latent 不放大 —— 由 HyperVAE 2x 解码负责像素翻倍
                try:
                    _rurf2k = float(refine_upscale_factor or 2.0)
                except (TypeError, ValueError):
                    _rurf2k = 2.0
                if _rurf2k != 1.0:
                    refine_upscale_factor = 1.0
                    print(f"[H3 Extender] v14.184 双采2K(渲染管道): refine_upscale_factor {_rurf2k} -> 1.0 (latent 不放大, 二采提速 + HyperVAE 2x 解码像素翻倍)")
                _hv2x_decl = 2.0  # v14.182: HyperVAE 2x 解码输出 = 像素 2x, 声明尺寸须翻倍
                # v14.182: 双采2K 二采 latent 不放大 —— 强制不使用 3D latent
                # upscaler (否则 L3109 会把 factor<=1.0 自动提到 1.5, 二采又放大
                # token, 双采2K 提速与 HyperVAE 2x 直出 2K 的收益全丢)。
                if refine_upscaler_model and not str(refine_upscaler_model).startswith("("):
                    _old_urm = str(refine_upscaler_model)
                    refine_upscaler_model = "(bilinear interpolation, no model)"
                    print(f"[H3 Extender] v14.184 双采2K(渲染管道): 3D upscaler '{_old_urm}' 已禁用 "
                          f"(factor=1.0 latent 不放大, 由 HyperVAE 2x 解码直出 2K)")
                # v14.184: 音频重绘继承 w33(0.7) —— v14.183 强制 0.9 致音频崩(VAD 0 段),
                # 0.7 = 保留 30% 一采音频 latent 特征(ref_audio 声线), 只精修 70%。
                print("[H3 Extender] 🎥 双采2K 模式: 一采 8 步(蒸馏契约) + 二采 4 步(factor=1.0 提速) + HyperVAE 2x 解码直出 2K, 音频重绘继承 w33(0.7)")
            elif _rp_mode == "双采2K（官方条件放大）":
                # v14.250 (2026-11-18): 参考 B站《惊-震-坐-瘫！我发现宝藏H3双采，
                # 让我违背单采祖训，感谢虚假的官方Regenerate-2K！》(BV1iNsZ6HEs9)
                # 的 H3-极速TR双采-文戏流工作流 —— MiniMaxH3LatentUpscaleCombined
                # 官方节点架构: 二采 latent 放大到 2x 时同步放大 ref2va 的
                # minimax_refs / minimax_keyframes latent 坐标。
                # 与旧档 "双采2K（HyperVAE 2x 解码）" 核心差异:
                #   旧档 = factor=1.0 + HyperVAE 2x VAE 解码, 省采样 token 但不做 latent 放大
                #   新档 = factor=2.0 + 原生 VAE 解码, latent 放大是条件放大的前置条件,
                #         二采同时有: latent 放大(精修细节) + 条件放大(ref2va 参考控制力
                #         随分辨率空间同步升级) + 原生 VAE 解码自动出 2K (latent 2x × 16x
                #         = 像素 2x, 不需额外 HyperVAE)
                steps, refine_steps, tile_count, refine_denoise = 8, 4, 4, 0.45
                shift_video, shift_audio = 12.0, 3.0
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                    print(f"[H3 Extender] v14.250 双采2K官方条件放大(渲染管道): 采样器强制 euler (TR 双采配方)")
                # 确保 refine_upscale_factor=2.0 (latent 放大是条件放大的前置,
                # 否则 ref2va refs/keyframes 停留在低分辨率坐标空间)
                try:
                    _rurf2k_cond = float(refine_upscale_factor or 0)
                except (TypeError, ValueError):
                    _rurf2k_cond = 0.0
                if _rurf2k_cond != 2.0:
                    refine_upscale_factor = 2.0
                    print(f"[H3 Extender] v14.250 双采2K官方条件放大(渲染管道): "
                          f"refine_upscale_factor {_rurf2k_cond} -> 2.0 "
                          f"(latent 放大是条件放大的前置)")
                # latent 2x 已覆盖 2K 像素 (latent 2x × 原生 VAE 16x = 像素 2x),
                # 不需要 HyperVAE 2x 解码 (否则会变成 4x 像素炸出 4K)
                _hv2x_decl = 1.0
                print(f"[H3 Extender] 🎥 双采2K 官方条件放大模式: 一采 8 步 + "
                      f"二采 4 步(latent x2.0 + ref2va 条件同步放大) + "
                      f"原生 VAE 解码直出 2K, 音频重绘继承 w33(0.7)")
            elif _rp_mode == "FastH3-4步VSA":
                steps, refine_steps, tile_count, refine_denoise = 4, 2, 4, 0.45
            elif _rp_mode == "Turbo-v4":
                # v14.173: 6+4/denoise0.55 -> 8+4/denoise0.45 (一采8步结构更稳, 二采少重绘防
                # clip2 复杂场景(点火/火焰/特写) 结构漂移变形; 速度仍快于精细(8+6)二采少2步)
                steps, refine_steps, tile_count, refine_denoise = 8, 4, 4, 0.45
                shift_video, shift_audio = 12.0, 3.0
            elif _rp_mode == "DMAD-4步":
                # v14.386: 用户口径 —— DMAD 渲染管线改成 1 采 8 步 + 2 采 2 步。
                # 旧值是 4+2(DMAD 4-step 蒸馏 LoRA 的标称步数); 实测 4 步一采在
                # H3 上结构/步态偏软, 8 步一采(同一套 DMAD LoRA 继续挂) 更稳,
                # 二采自 v14.389 起默认开重绘(内容锁: 起点 σ 0.45~0.55 + 结构相似度
                # 闸门), 这 2 步会真跑; 要回到 v14.384 的纯超分设
                # BSAI_H3_REFINE_NO_REDRAW=1。
                steps, refine_steps, tile_count, refine_denoise = 8, 2, 4, 0.5
                shift_video, shift_audio = 12.0, 2.0
                if str(sampler_name) != "lcm":
                    sampler_name = "lcm"
                    print(f"[H3 Extender] v14.172 DMAD-4步(渲染管道): 采样器强制 lcm (DMAD 官方配方)")
                print(f"[H3 Extender] v14.386 DMAD(渲染管道): 一采 8 步 + 二采 2 步 "
                      f"(v14.389 二采重绘开, 内容锁起点 σ 0.45~0.55)")
            elif _rp_mode == "武戏组合拳":
                # v14.176: 对齐 YZ金鱼「终极篇」武戏配方 (BV1LKJm6VELc):
                # 一采6步(simple) + 二采6步(总12步, 武戏拟合更清晰),
                # shift 12/3 (官方 v4), euler+simple 调度, 帧数对齐 H3 17 块.
                # 二采 denoise 0.45 (防高动态重绘漂移), 分块4 (24GB 显存防 OOM).
                steps, refine_steps, tile_count, refine_denoise = 6, 6, 4, 0.45
                shift_video, shift_audio = 12.0, 3.0
                _h3_align17 = True
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                    print(f"[H3 Extender] v14.176 武戏组合拳(渲染管道): 采样器强制 euler + simple 调度 (YZ终极篇武戏配方)")
            elif _rp_mode == "4K直出 秘制酱料":
                # v14.178 (2026-10-23): 对齐 B站《4K直出 MiniMax H3 秘制酱料工作流》
                # (BV18Vnb6UEPv, 大凯AI/CottonByte/Yusu) —— Self-Lift 自提升渐进采样:
                # 前期低分辨率阶段(一采 960x544 由 width/2 自动, 6 步)快定构图/轮廓/大幅运动;
                # 选定时间点 RESOLUTION BOOST (refine_upscale_factor 2.0 升潜空间分辨率);
                # 后期高分辨率阶段(二采 3 步)补纹理/精细细节。配 Turbo v4 step600 加速 LoRA +
                # MysticXXX V4 去油光 LoRA, 输出经 DLSS5 像素超分直出 4K (修 H3 高光过曝/发灰)。
                # 4090/24GB 若二采慢: refine_upscale_factor 降到 1.5 (1440x816) + DLSS 2.66x 仍 4K。
                steps, refine_steps, tile_count, refine_denoise = 6, 3, 4, 0.45
                shift_video, shift_audio = 12.0, 3.0
                try:
                    _rurf_raw = float(refine_upscale_factor or 2.0)
                except (TypeError, ValueError):
                    _rurf_raw = 2.0
                if _rurf_raw < 2.0:
                    print(f"[H3 Extender] v14.178 4K直出(渲染管道): refine_upscale_factor {_rurf_raw} 保持 (1.5 搭配 DLSS 2.66x 仍可达 4K)")
                else:
                    refine_upscale_factor = 2.0
                    print(f"[H3 Extender] v14.178 4K直出(渲染管道): refine_upscale_factor -> 2.0 (自提升 boost)")
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                    print(f"[H3 Extender] v14.178 4K直出(渲染管道): 采样器强制 euler + simple (秘制酱料配方)")
                print("[H3 Extender] 🎥 4K直出 秘制酱料模式: 一采 6 步低分辨率(自提升构图/形状/运动) → boost x2 → 二采 3 步细节。"
                      "LoRA 建议: minimax_h3_turbo_v4_step600 (0.5~0.8) + MysticXXX_MMH3-V4 (0.3~0.5, 去油光/高光自然); "
                      "输出走 DLSS5 像素超分(upscale_final + dlss5) 直出 4K。")
            elif _rp_mode == "FastH3 Omni 8步单采":
                steps, refine_steps, tile_count, refine_denoise = 8, 2, 4, 0.5
                if not omni_8step_mode:
                    omni_8step_mode = True
                    refine_enable = False
                    denoise = 1.0
                    shift_video, shift_audio = 12.0, 3.0
                    print(f"[H3 Extender] v14.172 FastH3 Omni 8步单采(渲染管道): 跳过二采, 一采 8 步蒸馏直出")
            elif _rp_mode == "QAD-v2-8步":
                # v14.201 (2026-10-25): FastH3-QAD-v2 —— 2026-10-20 海螺 AI Lab 发布,
                # 量化感知蒸馏整套 NVFP4(118GB→30GB, 质量不降反升)。8 步蒸馏直出
                # 单采(同 Omni 管道, 复用 7115 一采钳制健康区防 OOM); shift 10/3 为
                # 官方 V2 NVFP4 schedule(区别于 Omni 12/3, 不可混用); 需 Loader 换
                # QAD-v2 整套 NVFP4 模型 + BlockSparseAttention VSA keep_percent=10,
                # VAE 可选 36层(1.29GB 高质量)/8层(0.31GB 快15x) 新 NVFP4 解码器。
                steps, refine_steps, tile_count, refine_denoise = 8, 2, 4, 0.5
                if not omni_8step_mode:
                    omni_8step_mode = True
                    refine_enable = False
                    denoise = 1.0
                    shift_video, shift_audio = 10.0, 3.0
                    print(f"[H3 Extender] v14.201 QAD-v2-8步(渲染管道): 跳过二采, 一采 8 步蒸馏直出, "
                          f"shift 10/3 (官方 QAD-v2 NVFP4 schedule; Loader 需 QAD-v2 整套 NVFP4 模型)")
            elif _rp_mode == "直播带货（全自动）":
                # v14.202 (2026-10-25): 直播带货 ref_audio 一站式档。
                # 用户诉求"选中这一档后所有设置按固定配方, 手动设置全部无效"。
                # 配方 = v3 参考音频版工作流(v14.200 修复后)的已验证参数:
                #   一采 12 步(官方音频≥12步下限) + 二采 4 步 denoise 0.55
                #   + 3D latent upscaler x2.0(输出 2 倍像素) + 音频重绘 0.7
                #   (二采 4 步时由 v14.196 自动锁一采 12 步音频, 不重画)
                #   + shift 12/3 + TST tau 0.2 + 分块二采 4x128
                #   + audio_context_length=0(不把上一段语音当音频上下文)
                #   + clip2 起关闭 motion context(硬切段不再做 2s 渐变 → 首帧无拖影)
                # width/height 不锁: 分辨率决定一采像素, 锁死 1920 会让一采
                # 直接涨到 1920x1088(耗时 4x), 与用户"15秒必须 1 小时内"冲突。
                # v14.252 (2026-10-29) refine_denoise 回滚 0.45→0.55:
                # v14.251 把 denoise 降到 0.45 太保守, 一采 12 步本身低质量(480p/12 NFE),
                # 二采 0.45 没去掉一采高频噪点, 用户实测脸/手/衣服全部麻点污染
                # (头发高光区反而干净 —— 高频细节需要更高 denoise 才能"重画"干净)。
                # 保留 v14.251 的有效改动:
                #   ① audio_denoise=0.3 (色块已消)
                #   ② upscale_factor=1.5 (残影/拖影已减)
                #   ③ refine_steps=6 (更精细)
                # 只回滚 denoise 一项。
                steps, refine_steps, tile_count, refine_denoise = 12, 6, 4, 0.35
                refine_enable = True
                refine_audio_denoise = 0.3
                refine_upscale_factor = 1.5
                refine_upscaler_model = "minimax_h3_latent_upscaler_3d_fp32.pth"
                refine_align_to = 40
                shift_video, shift_audio = 12.0, 3.0
                dual_track_shift = True
                denoise = 1.0
                # v14.253 (fix): 直播带货档硬编码对齐用户工作流 + 修复接缝/横带问题.
                # context_length: 39 -> 22 (官方 AddGuide 22 帧尾部锚定, 过短锚不住, 过长占显存)
                # audio_context_length: 0 -> 24 (跨 CLIP 音频上下文, 修复 clip1→clip2 接缝断音)
                # refine_mem_mode: spatial -> global (避免 spatial 分块每块独立重画导致画面横带叠加;
                # global 路径 v14.253 已修复 attention override 回退)
                context_length = "22"
                audio_context_length = 24
                tiled_refine = False
                tile_overlap = 128
                refine_mem_mode = "global (全上下文省显存)"
                selflift_tst_enable = True
                selflift_tst_tau = 0.2
                upscale_per_clip = True
                upscale_final = True
                upscale_mode = "Quality first"
                upscale_engine = "dlss5"
                upscale_factor = 2.0
                _up_factor, _up_engine = _ff_resolve_upscale_mode(
                    upscale_mode, upscale_factor, upscale_engine
                )
                output_mode = "both"
                output_image_audio = True
                one_shot_mode = "off (分镜模式)"
                one_shot_enabled = False
                one_shot_single_pass = False
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                scheduler = "simple"
                print("[H3 Extender] 🛒 直播带货(全自动)档 v14.253: 12+4 / denoise 0.55 / latent x2.0 / "
                      "音频重绘 0.3 / shift 12-3 / TST 0.2 / global(不分块) / "
                      "context_length=22 / audio_context_length=24(跨CLIP接缝) / "
                      "clip2+ 关闭上下文 —— 除分辨率外手动参数全部由本档接管")
            elif _rp_mode == "FastH3 Omni × SelfLift 超分":
                # v14.211 (2026-10-26): B站《FastH3 Omni 全流程教学》(BV1rtnQ6qErJ) 配方落地。
                # FastH3 Omni 8 步蒸馏 + SelfLift 渐进式超分 (替代"单采 8 步 + 外部超分"):
                #   一采 4 步低分辨率(≈0.4x 搭骨架) -> 3D latent 放大 -> 二采 4 步高分辨率精修,
                #   总 8 NFE 仍满足 Omni 8 步蒸馏契约。
                # 注意力: 建议把工作流 BlockSparseAttention(VSA) 换成 sol-attn —— 默认 VSA 偏暗偏闷,
                #   换 sol-attn 画面瞬间清亮通透且速度不变。本档只改采样管道, 换节点需在工作流层做。
                # 模型: Loader 需换 fasth3_omniref_8step_pruned_int8_convrot.safetensors。
                steps, refine_steps, tile_count, refine_denoise = 4, 4, 4, 0.5
                refine_enable = True
                # v14.239: 倍率 2.5 -> 2.0 —— 实测 24GB 卡上 x2.5 会让二采 latent 达
                # 1.35M tokens(544x960 -> 1360x2400), Sol-Attn 降级 dense 后直接 OOM。
                # 2.0 时二采 ~864k tokens(≈v14.164 可跑通的 873k 量级), 24GB 可承受。
                refine_upscale_factor = 2.0
                shift_video, shift_audio = 12.0, 3.0
                denoise = 1.0
                selflift_tst_enable = True
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                print("[H3 Extender] 🚀 FastH3 Omni × SelfLift 超分: 一采 4 步(≈0.4x)搭骨架 -> 3D latent 放大 -> "
                      "二采 4 步高分辨精修 (总 8 NFE); 确认 Loader=fasth3_omniref_8step_pruned_int8_convrot "
                      "+ 注意力换 sol-attn(替代 VSA)。")
            elif _rp_mode == "H25 Hybrid 8步 多参考单采":
                # v14.223 (2026-10-27): B站《MiniMax H3 多参考终于测出最优解,
                # H25 Hybrid混合架构胜出》(BV1dygg6EE6W, AI-KSK) 配方落地。
                # H25 Hybrid = Base FL2VA + Overlay Ref2VA, Block Range Additive
                # 区间 25-49(社区共识, 非 50/50): 保留 FL2VA 清晰/细节/运动流畅,
                # 引入 Ref2VA 参考控制(参考强度 25→49 更强更像参考、动作更保守)。
                # 生产配方 = 8 步单采直出(视频实测 8 步=正式生产; 20 步仅质量
                # 基准; 4 步 Ref2V 加速 LoRA 音频劣化+动态被约束弃用) +
                # LightX2V 8 步 FL2V 加速 LoRA, euler+simple, shift 12/3,
                # denoise 1.0, 跳过二采。只改采样管道, 不碰模型图:
                # Loader 需换 minimax_h3_hybrid_fl2va_ref2va_b25-49-int8,
                # 加速 LoRA 槽挂 minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16。
                steps, refine_steps, tile_count, refine_denoise = 8, 2, 4, 0.5
                refine_enable = False
                denoise = 1.0
                shift_video, shift_audio = 12.0, 3.0
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                    print(f"[H3 Extender] v14.223 H25 Hybrid 8步(渲染管道): 采样器强制 euler + simple (LightX2V 8步配方)")
                scheduler = "simple"
                print("[H3 Extender] 🚀 H25 Hybrid 8步 多参考单采: 一采 8 步直出 (BV1dygg6EE6W 配方) — "
                      "确认 Loader=minimax_h3_hybrid_fl2va_ref2va_b25-49-int8.safetensors, "
                      "加速LoRA槽=minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors(强度 1.0)")
            elif _rp_mode == "4K重生成 OpenH3Regenerate2K (768P草稿直出2560)":
                # v14.229 (2026-10-27): B站《MinimaxH3 进入4K分辨率开源时代 768P草稿
                # 直接升2560 比官方还高清》(BV13uxT66EWq, AI绘画KK) 配方落地:
                # NVLabs Sana 仓库 OpenH3Regenerate2K 开放模型 —— 768P 草稿
                # (1344x768, 121帧) -> 三步精修重生成 -> 2560x1440 2K。
                # 官方采样: 3 步 sigmas [0.909375, 0.857143, 0.666667, 0], CFG=1.0,
                # 初始态 = (1-s0)*latent + s0*noise; 合并 LoRA(FP32, 三适配器沿
                # rank 轴拼接, 误差 2.2e-8): OpenH3 Refiner 5000步(0.7) +
                # LTXRV fl2v turbo 1.2(1.0) + lms sharp rank64(1.0)。
                # 落地为双采: 一采 4 步 768P 草稿搭骨架 -> 二采 3 步重生成
                # (官方 sigma 起点 0.909375) + latent x1.9 放大(1344->2560) 出 2K。
                steps, refine_steps, tile_count, refine_denoise = 4, 3, 4, 1.0
                refine_enable = True
                refine_upscale_factor = 1.9  # 1344 -> 2560 潜空间放大(官方 3D 卷积上采样器)
                refine_align_to = 32         # 2560x1440 目标网格 32px 对齐
                shift_video, shift_audio = 12.0, 3.0
                denoise = 1.0
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                # v14.334 (2026-11-08): 二采起点必须落在官方 sigma 0.909375 ——
                # 补录 B站《MiniMax H3又被玩出新花样了！潜空间重绘直冲2K！》
                # (BV1Yh4j6gEt3) 与 NVlabs/Sana Open-H3-Regenerate-2K 官方契约:
                #   sigmas = [0.909375, 0.857143, 0.666667, 0], 3 步 Euler, CFG off。
                # 旧实现 refine_denoise=1.0 走内部 beta 调度 = 从 sigma_max 纯噪声
                # 重建, 768P 草稿的构图/运动信息被整条丢弃(等于 3 步从零画 2560),
                # 与"重生成"语义相反。内部 _sigmas() 也取不到 0.909 起点: steps=3
                # 时 int(3/0.909)=3, total_steps 回落到 3, 返回整条 4 段调度, 起点
                # 仍是 1.0 —— 所以这里直接注入官方 SIGMAS(用户外接 supersede)。
                if refine_sigmas is None:
                    import torch as _torch_oh3
                    refine_sigmas = _torch_oh3.FloatTensor(
                        [0.909375, 0.857143, 0.666667, 0.0])
                print("[H3 Extender] 🚀 4K重生成 OpenH3Regenerate2K: 768P草稿(1344x768) -> "
                      "3步重生成 -> 2560x1440 2K (BV13uxT66EWq / BV1Yh4j6gEt3 配方) — "
                      "确认 Loader 挂合并LoRA(OpenH3 Refiner 0.7 + fl2v turbo 1.0 + lms sharp 1.0), "
                      "采样器 CFG 设为 1.0; 3D 卷积 latent 上采样器(BF16) 可挂 refine_upscaler_model; "
                      "二采 sigmas 已注入官方 [0.909375, 0.857143, 0.666667, 0]")
            elif _rp_mode == "PRISM 10步 运动强化单采 (Singularity v2 × 10Eros-Max)":
                # v14.231 (2026-10-27): B站《Singularity v2 × 10Eros-Max 合并模型,
                # 提升运动效果》(BV1Vino6qE2F, plphy-up) 配方落地。
                # PRISM = Ref2VA 系合并模型(HuggingFace OliviaRossi/
                # Minimax-h3_Singularity-x-10Eros-Max_PRISM, int8 20.3GB): 官方
                # workflow 直接替换 ref2va 模板的 UNETLoader 模型, 提升运动
                # 流畅度与连贯性(动画战斗场景实测)。官方采样 = euler + simple +
                # 10 步 + denoise 1.0, BasicGuider 默认 CFG 1.0, 无 LoRA,
                # 单采直出(不跑二采)。只改采样管道, 不碰模型图:
                # Loader 需换 Minimax-h3_Singularity_x_10Eros-Max_PRISM_int8.safetensors;
                # 建议 5 段式长提示词(subject_definitions / summary /
                # retention_analysis / detailed_description / overall_soundscape /
                # non_diegetic_music) 与参考图驱动(ref2va)。
                steps, refine_steps, tile_count, refine_denoise = 10, 2, 4, 0.5
                refine_enable = False
                denoise = 1.0
                shift_video, shift_audio = 12.0, 3.0
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                    print(f"[H3 Extender] v14.231 PRISM 10步(渲染管道): 采样器强制 euler + simple (PRISM 官方配方)")
                scheduler = "simple"
                print("[H3 Extender] 🚀 PRISM 10步 运动强化单采: 一采 10 步直出 (BV1Vino6qE2F 配方) — "
                      "确认 Loader=Minimax-h3_Singularity_x_10Eros-Max_PRISM_int8.safetensors, "
                      "euler+simple 10步 denoise 1.0 无 LoRA")
            elif _rp_mode == "透明视频 单采抠像 (H3 Transparent)":
                # v14.233 (2026-10-27): B站《在 ComfyUI 中使用 MiniMax-H3 轻松制作
                # 透明视频》(BV1arJX69E7L, 治部少辅哈库/SatoDive) 配方落地。
                # 核心思路: H3 在纯色背景(绿幕/蓝幕/纯黑)上生成 -> 节点内自动
                # 抠像(Matte + Edges 去溢色) -> 输出带真 Alpha 的 ProRes 4444/
                # WebM VP9/RGBA PNG 序列。采样 = 一采 10 步单采直出(教程默认
                # 10 步 + 4 步 turbo LoRA; 无 LoRA 用 ~20 步), euler+simple,
                # shift 12/3, denoise 1.0, 跳过二采 —— 二采重绘会扰动底色
                # 均匀性, 导致抠像破洞/边缘闪烁。只改采样管道, 不碰模型图:
                # 建议 Loader 挂 minimax_h3_fl2v_turbo_4step_*.safetensors
                # (强度约 0.8); 后续接 BSAI_H3_TransparentKey 抠像 +
                # BSAI_H3_SaveTransparentVideo 导出。
                steps, refine_steps, tile_count, refine_denoise = 10, 2, 4, 0.5
                refine_enable = False
                denoise = 1.0
                shift_video, shift_audio = 12.0, 3.0
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                    print(f"[H3 Extender] v14.233 透明视频(渲染管道): 采样器强制 euler + simple (单采抠像配方)")
                scheduler = "simple"
                print("[H3 Extender] 🎞️ 透明视频 单采抠像 (BV1arJX69E7L 配方): 一采 10 步单采直出, 跳过二采 — "
                      "提示词务必写明纯色背景(如 'green screen background, flat solid green backdrop, no floor, no horizon'); "
                      "建议 Loader 挂 minimax_h3_fl2v_turbo_4step_*.safetensors(强度 ~0.8); "
                      "出片后接 BSAI_H3_TransparentKey 抠像 + BSAI_H3_SaveTransparentVideo 导出")
            elif _rp_mode == "4合1终极加速 (DMAD 8步 SelfLift 6+2 + 参考降分 + SegAttention)":
                # v14.234 (2026-10-27): B站《MiniMax H3终极加速！4合1的加速方法，速度直接起飞！》
                # (BV1WWxT6cEdY, 小黄瓜) 4 大核心加速方案配方落地:
                # ① DMAD MiniMax H3 4step LoRA(官方20步 -> 8步, -57.5%) ② SegAttention 2.2.0
                # (KJNodes PatchSegAttentionKJ, 叠加 -81%) ③ 参考输入降分 half(叠加 -93.25%)
                # ④ SelfLift 二采(6 步半分辨率草稿 + 2 步全分辨率精修 = 8 NFE, latent upscale)。
                # 视频实测: 6 步 960x540 + 2 步 1920x1080 拆分生成比直接全分辨率 8 步更快。
                steps, refine_steps, tile_count, refine_denoise = 6, 2, 4, 0.5
                refine_enable = True
                refine_upscale_factor = 2.0   # 半分辨率 -> 全分辨率(latent upscale 等效)
                shift_video, shift_audio = 12.0, 3.0
                denoise = 1.0
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                    print(f"[H3 Extender] v14.234 4合1(渲染管道): 采样器强制 euler + simple (DMAD 8步配方)")
                scheduler = "simple"
                if ref_image_size not in ("half", "half (4合1加速)"):
                    ref_image_size = "half"   # 参考输入降分(保留动作/轮廓, 编码与生成数据大减)
                print("[H3 Extender] 🚀 4合1终极加速 (BV1WWxT6cEdY 配方): 6步半分辨率草稿 + 2步全分辨率精修 = 8 NFE; "
                      "参考输入已降分 half; Loader 建议挂 DMAD MiniMax H3 4step LoRA(官方20步->8步 -57.5%); "
                      "SegAttention 2.2.0 叠加可再 -81%(平缓文戏推荐, 高动态酌情)")
            elif _rp_mode == "SolarRenderer 结构控制 (控制LoRA + 4步LoRA 逐帧驱动)":
                # v14.235 (2026-10-27): B站《全新 FastH3-Omni + Singularity V2 动画管线！
                # SolarRenderer 逐帧控制，单卡直出〈刺客信条〉级电影短片！》(BV1Phxu6PE93) 配方:
                # SolarRenderer 跑在 Minimax H3 上, 两个 LoRA —— 控制LoRA(逐帧读取结构视频:
                # 3D灰盒/法线贴图/DW姿态骨架/OpenPose线框/深度图/边界框 = 视频版ControlNet) +
                # 4步LoRA(采样压到 4 步); 因果版逐块实时生成(每块只读前 5 块结构+渲染结果);
                # 基模 FastH3-Omni(加载运行更快) / Singularity V2(高动态动作更出色, INT8)。
                # 落地: 一采 4 步(SelfLift 低分辨率草稿) + 二采 4 步(latent x2.0 全分辨率精修)
                # = 8 NFE; ref_image_size 强制 max(结构细节不降分, 与 4合1 的 half 相反);
                # 提示词纪律: 详细描述镜头切换/落地/环境层次(否则模型只输出参考里的 3D 方块)。
                steps, refine_steps, tile_count, refine_denoise = 4, 4, 4, 0.45
                refine_enable = True
                refine_upscale_factor = 2.0   # SelfLift 低分辨率 0.5 -> 全分辨率(latent upscale 等效)
                shift_video, shift_audio = 12.0, 3.0
                denoise = 1.0
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                    print(f"[H3 Extender] v14.235 SolarRenderer(渲染管道): 采样器强制 euler + simple (4步LoRA 配方)")
                scheduler = "simple"
                if ref_image_size in ("half", "half (4合1加速)"):
                    ref_image_size = "max"   # 结构控制需保留完整结构细节
                    print(f"[H3 Extender] v14.235 SolarRenderer(渲染管道): ref_image_size half -> max (结构控制需保留完整结构细节)")
                print("[H3 Extender] 🎬 SolarRenderer 结构控制 (BV1Phxu6PE93 配方): 一采 4 步(低分辨率草稿) + 二采 4 步(latent x2.0 全分辨率精修) = 8 NFE; "
                      "Loader 建议挂 solarrenderer 控制LoRA + 4步LoRA(强度 ~0.8, 基模 FastH3-Omni/Singularity V2); "
                      "参考输入接结构视频抽帧序列(灰盒/法线贴图/骨架/深度图); 提示词务必详细描述镜头切换/落地细节; "
                      "出片后可接 NVIDIA RTX VFX(RTX Video Frame Generation 24->48FPS + Super Resolution 2K)")
            elif _rp_mode == "Director 极速双采 (MiniMaxH3 Director 移植)":
                # v14.238 (2026-10-28): MiniMaxH3 Director 插件「一采/二采极速渲染」
                # 全套移植。参考插件例程 minimax_h3_director_二采_加速.json 的
                # 已验证配方:
                #   一采: 8 步(res_multistep+simple) + shift 12/3 + guidance 1.0
                #         (BasicGuider 单前向) + 0.4MP 低清画布(864x480 @16:9)
                #         —— 低清草稿快定构图/形状/大幅运动;
                #   二采: H3 latent 3D 放大到目标画布(默认 2MP = 1920x1088 @16:9)
                #         + SIGMAS 极轻精修: beta 调度 3 步 denoise 0.2 + euler
                #         + 1 pass(参考插件 passes=1)。
                # 总 NFE = 8@0.4MP + 3@2MP —— 高分辨率只跑 3 步, 极速出 2K。
                # 电影工厂适配点:
                #   ① 二采采样器独立选择(默认 euler, 参考插件一采 res_multistep
                #      二采 euler 分离设计), 由新 widget refine_sampler 控制;
                #   ② 音频锁定(3 步 0.2 denoise 重绘音频必毁人声/低频轰鸣,
                #      遵循电影工厂 v14.195 音频质量原则; lip_voice 外部音频
                #      更应锁定);
                #   ③ 外接 SIGMAS: refine_sigmas 端口直连 BasicScheduler/
                #      ManualSigmas 时, 二采完全按外部 sigma 曲线执行(参考
                #      插件 Refine 节点原版行为), 未接时内部 beta 3步/0.2;
                #   ④ 分辨率: 用户 width/height/megapixels 仍定义目标画布
                #      (经 director_fast_target_mp 换算), 一采画布由
                #      director_fast_first_mp 接管 —— 见下方分辨率 override。
                steps, refine_steps, tile_count, refine_denoise = 8, 3, 4, 0.2
                refine_enable = True
                refine_audio_denoise = 0.0   # 极速二采锁定音频(低步数不重绘人声)
                shift_video, shift_audio = 12.0, 3.0
                denoise = 1.0
                if str(sampler_name) != "res_multistep":
                    sampler_name = "res_multistep"   # Director 一采采样器配方
                    print(f"[H3 Extender] v14.238 Director极速双采(渲染管道): 一采采样器强制 res_multistep")
                scheduler = "simple"
                if refine_sampler in ("inherit", "inherit (跟随一采)", "None", "none", ""):
                    refine_sampler = "euler"          # Director 二采采样器配方
                # 音频契约: lip_audio/lip_voice 提供外部音频时一采 8 步(蒸馏契约,
                # 省 4 步 x ~68s); 模型自生成音频时一采提 12 步满足官方音频可用
                # 下限(参考插件 8 步在电影工厂实测会出恒定低频轰鸣/含混配音)。
                if not kwargs.get("lip_audio") and not kwargs.get("lip_voice"):
                    steps = 12
                    print(f"[H3 Extender] v14.238 Director极速双采: 模型自生成音频 "
                          f"(未接 lip_audio/lip_voice), 一采 8->12 步满足官方音频"
                          f"下限; 接 lip_voice 外部音频可回到 8 步极速契约")
                # 自动选用 3D latent upscaler(参考插件用
                # minimax_h3_latent_upscaler_3d_bf16/fp32, 语义放大细节更丰富)
                if _FF_UPSCALER_MOD is not None:
                    try:
                        _d_ups_opts = _ff_get_upscaler_models()
                        _d_pick = None
                        for _nm in _d_ups_opts:
                            if "latent_upscaler_3d" in str(_nm).lower() or "upscaler_3d" in str(_nm).lower():
                                _d_pick = _nm
                                break
                        if _d_pick is None and len(_d_ups_opts) > 2:
                            _d_pick = _d_ups_opts[2]
                        if _d_pick:
                            refine_upscaler_model = _d_pick
                            print(f"[H3 Extender] v14.238 Director极速双采: 自动选用 "
                                  f"3D latent upscaler '{_d_pick}'")
                    except Exception as _du_err:
                        print(f"[H3 Extender] v14.238 Director极速双采: 3D upscaler "
                              f"自动选择失败(走 bilinear): {_du_err}")
                        refine_upscaler_model = "(bilinear interpolation, no model)"
                else:
                    refine_upscaler_model = "(bilinear interpolation, no model)"
                    print(f"[H3 Extender] ⚠️ v14.238 Director极速双采: 未探测到 3D "
                          f"latent upscaler 插件(Comfyui_Minimax_h3_latent_Upscaler), "
                          f"二采放大走 bilinear 插值(画质略降)")
                _director_fast_active = True
                print(f"[H3 Extender] 🚀 v14.238 Director 极速双采(MiniMaxH3 Director "
                      f"移植): 一采 {int(steps)} 步 {_dff_first_mp}MP 低清草稿 "
                      f"-> H3 latent 3D 放大 -> 二采 {int(refine_steps)} 步 "
                      f"(denoise {float(refine_denoise):.2f}, {refine_sampler}) 到 "
                      f"{_dff_target_mp}MP 目标画布; 音频锁定不重绘; "
                      f"总 NFE={int(steps)}@低清+{int(refine_steps)}@高清")
            elif _rp_mode == "PDMD 4步 SelfLift 双采 (4+2)":
                # v14.258 (2026-10-29): PDMD (UCSD×字节, arXiv 2609.35768, 2026-09-23/29
                # 发布) 4步蒸馏 LoRA 配方: 一采 4 步(论文 4 步契约, VideoGen-Eval 总分
                # 83.17, 超所有 4 步蒸馏基线) + 二采 2 步全分辨率精修(latent x2.0)
                # = 6 NFE。Loader 建议挂 Kijai 转换版 LoRA
                # minimax_h3_pdmd_4step_lora_avg_rank_57_bf16.safetensors
                # (Kijai/MiniMax-H3-experimental, 标准 H3 LoRA 路径加载, 无需自定义节点;
                # rank128 原版在 pdmd2026 HF); 模型卡要求 shift 12/3 + 基础模型调度器
                # 配置; 学生模型面向 1344×768。定位快速出片/试稿, 正片质量仍以
                # 双采2K/8步档为基准。
                steps, refine_steps, tile_count, refine_denoise = 4, 2, 4, 0.5
                refine_enable = True
                refine_upscale_factor = 2.0   # latent x2.0 全分辨率精修
                shift_video, shift_audio = 12.0, 3.0
                denoise = 1.0
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                    print(f"[H3 Extender] v14.258 PDMD 4步 SelfLift 双采(渲染管道): 采样器强制 euler (PDMD 4步蒸馏契约)")
                # v14.388: 原来是 scheduler="simple"(等间距 u=linspace(1,0,5)), 出片全噪 ——
                # 蒸馏学生只在固定噪声边界上训练过, 必须喂它自己的 base_schedule。
                scheduler = "pdmd_manual"
                print("[H3 Extender] v14.388 PDMD 4步(渲染管道): 调度器 = 训练边界 "
                      "[1.0,0.7,0.4,0.15,0.0] 经 shift 12/3 映射(不再用 ComfyUI simple 等间距)")
                print("[H3 Extender] 🧪 v14.258 PDMD 4步 SelfLift 双采 (4+2): "
                      "PDMD(UCSD×字节, arXiv 2609.35768, 2026-09-23/29 发布) 4步蒸馏 LoRA —— "
                      "一采 4 步(论文 4 步契约, VideoGen-Eval 总分 83.17, 超所有 4 步蒸馏基线) "
                      "+ 二采 2 步全分辨率精修(latent x2.0) = 6 NFE; "
                      "Loader 建议挂 Kijai 转换版 LoRA minimax_h3_pdmd_4step_lora_avg_rank_57_bf16.safetensors"
                      "(Kijai/MiniMax-H3-experimental, 标准 H3 LoRA 路径加载, 无需自定义节点; "
                      "rank128 原版在 pdmd2026 HF); 模型卡要求 shift 12/3 + 基础模型调度器配置; "
                      "学生模型面向 1344×768; 定位快速出片/试稿, 正片质量仍以双采2K/8步档为基准")
            elif _rp_mode == "PDMD 2步 极速试稿 (单采)":
                # v14.258: PDMD 2步蒸馏(pdmd_2NFE_lora, Kijai 转换
                # minimax_h3_pdmd_2step_lora_avg_rank_38_bf16.safetensors) = 2 NFE
                # 极速单采直出。定位快速试稿/筛镜头, 不用于正片(社区实测口径:
                # 低步数细节易崩, 正片建议 ≥6 步或走双采)。
                steps, refine_steps, tile_count, refine_denoise = 2, 0, 4, 0.5
                refine_enable = False
                shift_video, shift_audio = 12.0, 3.0
                denoise = 1.0
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                    print(f"[H3 Extender] v14.258 PDMD 2步极速试稿(渲染管道): 采样器强制 euler + simple (PDMD 2步蒸馏契约)")
                scheduler = "simple"
                print("[H3 Extender] ⚡ v14.258 PDMD 2步 极速试稿 (单采): "
                      "PDMD 2步蒸馏(pdmd_2NFE_lora, Kijai 转换 "
                      "minimax_h3_pdmd_2step_lora_avg_rank_38_bf16.safetensors) = 2 NFE 极速单采直出; "
                      "定位快速试稿/筛镜头, 不用于正片 —— 社区实测口径: 低步数细节易崩, "
                      "正片建议 ≥6 步或走双采")
            elif _rp_mode == "PTD 4步 Ref2VA 单采 (参考图加速)":
                # v14.258: PTD 逐跳 Ref2VA 加速 LoRA(淘宝内容AI, 2026-10-20/22 发布,
                # HF MiniMax-H3-Ref2VA-PTD-4Step rank128 bf16 5.58GB; 作者 H20 实测
                # 1344×768/243帧/4 NFE 端到端) = 参考图->音视频 4 步单采。
                # 需要 Ref2VA 底模(未剪枝 ~140GB, 或社区 ComfyUI-PTD-Compact int8 版),
                # 无对应底模时不要选此档; ref_image_size 保持用户值不强制。
                steps, refine_steps, tile_count, refine_denoise = 4, 0, 4, 0.5
                refine_enable = False
                shift_video, shift_audio = 12.0, 3.0
                denoise = 1.0
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                    print(f"[H3 Extender] v14.258 PTD 4步 Ref2VA(渲染管道): 采样器强制 euler + simple (PTD 4步契约)")
                scheduler = "simple"
                print("[H3 Extender] 🎯 v14.258 PTD 4步 Ref2VA 单采 (参考图加速): "
                      "PTD 逐跳 Ref2VA 加速 LoRA(淘宝内容AI, 2026-10-20/22 发布, "
                      "HF MiniMax-H3-Ref2VA-PTD-4Step rank128 bf16 5.58GB; "
                      "作者 H20 实测 1344×768/243帧/4 NFE 端到端) = 参考图->音视频 4 步单采; "
                      "需要 Ref2VA 底模(未剪枝 ~140GB, 或社区 ComfyUI-PTD-Compact int8 版), "
                      "无对应底模时不要选此档; ref_image_size 保持用户值不强制")
            elif _rp_mode == "ACC 8步 SelfLift 双采 (8+4)":
                # v14.387 (2026-11-12): ACC 8 步加速档 —— 用户口径 1 采 8 步 + 2 采 4 步。
                # 权重(models\loras\H3\H3加速\ACC\):
                #   MiniMax-H3-Ref2VA-Acc-8Step_comfyui_pdd-T8.safetensors  参考图->音视频
                #   MiniMax-H3-FL2VA-Acc-8Step_comfy.safetensors            首尾帧/文生
                # 8 步蒸馏契约: LoRA strength 1.0, euler + simple, shift 12/3, CFG 1.0;
                # 该加速 LoRA 本身已是 8 步蒸馏, 不要再叠第二个加速 LoRA(两个 LoRA 抢
                # 同一批低秩子空间, 与 Pika/TaoMate 的禁叠禁忌同源)。
                # Ref2VA 版要求 Ref2VA 底模(或 hybrid b25-49 混合底模, 分段链路靠
                # FL2VA 末帧接力); 纯 FL2VA 底模请改用 FL2VA 版权重。
                # 二采自 v14.389 起默认开重绘(内容锁 denoise 0.45 即起点 σ≈0.438,
                # 采样后还有结构相似度闸门), 这 4 步会真跑; 纯超分设
                # BSAI_H3_REFINE_NO_REDRAW=1。
                steps, refine_steps = 8, 4
                tile_count, refine_denoise = 16, 0.45
                refine_enable = True
                refine_upscale_factor = 2.0
                refine_align_to = 32
                tiled_refine = True
                tile_overlap = 128
                _rp_no_temp_chunk = True
                shift_video, shift_audio = 12.0, 3.0
                denoise = 1.0
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                    print(f"[H3 Extender] v14.387 ACC 8步(渲染管道): 一采强制 euler + simple (ACC 8步蒸馏契约)")
                scheduler = "simple"
                refine_sampler = "euler"
                print("[H3 Extender] ⚡ v14.387 ACC 8步 SelfLift 双采 (8+4): "
                      "挂 H3加速\\ACC\\ 下的 8 步加速 LoRA(strength 1.0) —— "
                      "Ref2VA 版 MiniMax-H3-Ref2VA-Acc-8Step_comfyui_pdd-T8 / "
                      "FL2VA 版 MiniMax-H3-FL2VA-Acc-8Step_comfy; "
                      "一采 8 步 + 二采 4 步(v14.389 二采重绘开, 内容锁起点 σ 0.45~0.55 + 结构闸门); "
                      "不要再叠加第二个加速 LoRA")
            elif _rp_mode == "PIKA H3 Flex 6+2 双采 (Ref2VA 锁脸)":
                # v14.310 (2026-11-04): Pika H3 Flex 配方 (B站教程 BV1Dy4u67EJo,
                # 官方模板 video_pika_h3_flex_ref2va / docs.comfy.org Pika H3 Flex)。
                # Pika 把 H3 蒸馏成 6 步生成器, 以两个 LoRA 适配器发布
                # (pika_h3_flex_ref2va_v1_bf16 / pika_h3_flex_fl2va_v1_bf16,
                # strength 必须 1.0, 禁止再叠第二个加速 LoRA —— 适配器本身已是
                # 6 步蒸馏, 叠加会破坏输出)。
                # v14.310 对齐官方 ManualSigmas: 蒸馏调度是固定 sigma 结
                # 1000/750/500/250/100/40 (+0), 不是 ComfyUI 的 simple 等间距
                # (1000/833/667/500/333/167/0) —— 用 simple 等于让蒸馏适配器跑
                # 没训练过的调度, 画质/稳定性都会掉。见 _PIKA_H3_SIGMA_KNOTS。
                # 实测修正 (h3_clip_250_2 耗时 >30min): 二采 SelfLift latent x2.0
                # 每步 287s, 10s clip tokens=587k 是教程 5s clip 的 4x; 关闭 refine,
                # 仅一采 6 步直出 960x544 latent → VAE decode 到 1920x1088
                # (H3 VAE 天然 x16 放大)。
                # 底模保留 hybrid b25-49 (分段链路 FL2VA 末帧接力, 勿切纯 ref2va);
                # 加速栈 SegAttention + Sol-Attn + Sol VAE。
                steps, refine_steps, tile_count, refine_denoise = 6, 0, 4, 0.5
                refine_enable = False
                shift_video, shift_audio = 12.0, 3.0
                denoise = 1.0
                if str(sampler_name) != "lcm":
                    sampler_name = "lcm"
                    print("[H3 Extender] v14.310 PIKA H3 Flex(渲染管道): 采样器强制 lcm (Pika 6步蒸馏官方契约)")
                scheduler = "pika_manual"
                print("[H3 Extender] 🎬 v14.310 PIKA H3 Flex 6 步单采 (Ref2VA 锁脸): "
                      "Pika H3 Flex 蒸馏适配器 (Pika-Labs/Pika-H3-Flex, 50步->6步) —— "
                      "lcm + ManualSigmas 固定结 1000/750/500/250/100/40 (官方契约, 非 simple 等间距), "
                      "shift 12/3, 跳过二采 SelfLift; "
                      "LoRA 槽挂 pika_h3_flex_ref2va_v1_bf16.safetensors (strength 1.0, 禁叠第二个加速 LoRA), "
                      "底模留 hybrid b25-49 (分段链路 FL2VA 接力, 勿切纯 ref2va)")
            elif _rp_mode == "PIKA H3 Flex 8步+2步 双采 (Ref2VA 锁脸)":
                # v14.366 (2026-11-10): 用户要求把 PIKA 做成**真实的**双采档。
                # v14.310 的 6+2 实际是 6 步单采 —— 二采 SelfLift x2.0 每步 287s，
                # 10s clip 587k tokens 是教程 5s clip 的 4x，太慢被关掉。
                # v14.367 (2026-11-10): 按用户要求定为 **8+2**（一采 8 步 + 二采 2 步）。
                # 原 8+4 的二采要 4 x 287s ≈ 19 分钟，单段近 30 分钟；2 步降到 ≈ 9.5 分钟，
                # 单段约 18 分钟。denoise 保持 0.45：2 步只做轻度收尾，不改写构图。
                # 一采 σ: Pika 官方只有 6 结 1000/750/500/250/100/40(+0)，8 步没有
                # 官方表，故对 6 步轨迹做分段线性插值细分（见 _sigmas 的 pika_manual
                # 分支）；**不换 simple 等间距** —— 那是蒸馏适配器没见过的调度。
                # 底模仍留 hybrid b25-49（分段链路 FL2VA 末帧接力，勿切纯 ref2va）；
                # LoRA 槽挂 pika_h3_flex_ref2va_v1_bf16 (strength 1.0, 禁叠第二个加速 LoRA)。
                steps, refine_steps = 8, 2
                tile_count, refine_denoise = 16, 0.45
                refine_enable = True
                refine_upscale_factor = 2.0
                refine_align_to = 32
                tiled_refine = True
                tile_overlap = 128
                _rp_no_temp_chunk = True
                shift_video, shift_audio = 12.0, 3.0
                denoise = 1.0
                if str(sampler_name) != "lcm":
                    sampler_name = "lcm"
                    print("[H3 Extender] v14.367 PIKA H3 Flex 8+2(渲染管道): 一采强制 lcm (Pika 蒸馏契约)")
                scheduler = "pika_manual"
                # 二采不跟随 lcm: beta + 4 步 + denoise 0.45 是通用精修配方，
                # lcm 在非 Pika 的 sigma 轨迹上收益不明，二采改 euler。
                refine_sampler = "euler"
                _pk8_pick = None
                try:
                    for _nm in _ff_get_upscaler_models():
                        if "minimax_h3_latent_upscaler_3d_fp16" in str(_nm).lower():
                            _pk8_pick = _nm
                            break
                    if _pk8_pick is None:
                        for _nm in _ff_get_upscaler_models():
                            if "latent_upscaler_3d" in str(_nm).lower():
                                _pk8_pick = _nm
                                break
                except Exception:
                    _pk8_pick = None
                refine_upscaler_model = _pk8_pick or ""
                print("[H3 Extender] 🎬 v14.367 PIKA H3 Flex 8步+2步 双采 (Ref2VA 锁脸): "
                      f"一采 {steps} 步 lcm + Pika 6 步轨迹细分 σ (非 simple 等间距), "
                      f"二采 {refine_steps} 步 euler + beta + denoise 0.45 + SelfLift x2.0 渐进放大 "
                      f"({tile_count} 块 / overlap {tile_overlap}); "
                      "LoRA 槽挂 pika_h3_flex_ref2va_v1_bf16.safetensors "
                      "(strength 1.0, 禁叠第二个加速 LoRA), 底模留 hybrid b25-49")
            elif _rp_mode in ("TaoMate HD 3步 渐进放大双采 (2+1 1080p直出)",
                              "TaoMate HD 8步+4步 渐进放大双采 (8+4 1080p直出)"):
                # v14.323 (2026-11-06): 同分支挂两档 —— 沿用 (2+1) 的全部配方
                # (半分辨率一采 / x2.0 3D latent 提升 / denoise 0.45 / 16 块 / euler+simple),
                # 只把步数拉成 8+4 = 12 NFE 的质量档。
                # v14.303 (2026-11-03): TaoMate HD 配方 (B站教程 BV1Ui4G6nEXs
                # 《卷！卷完加速卷放大！H3 Taomate HD光速出1080p视频》,
                # 节点包 github.com/slmonker/ComfyUI-TaoMateHD,
                # LoRA huggingface slmonker/TaoMate-HD-preview-comfy)。
                # v14.304 (2026-11-03 修复): 原 v14.303 照搬"3 NFE 契约"(2+1 步 +
                # denoise 0.5 单步二采 + x1.6 bislerp 提升)出片满屏竖直波纹、
                # 人脸被抹平 —— 实机 clip 复现。根因三条:
                # ① 3 NFE 只有 TaoMate 自家 teacher-state 渐进采样器才成立,
                #    用通用 euler 跑 2 步全 sigma + 1 步 denoise 0.5 = 严重欠采样,
                #    结构直接糊掉; ② x1.6 不是 3D latent upscaler 的训练倍率,
                #    只能走 bislerp 非整数重采样, 二采再欠采样就固化成一圈圈波纹;
                # ③ 二采被 v14.270 自动时间分块切成 3 段(每段独立 seed),
                #    接缝闪烁/段内碎花。
                # 现配方 = 半分辨率一采 + 训练倍率 x2.0 语义放大 + 足步数精修:
                # 一采 4 步(euler+simple, 低分画布) + 二采 3 步(denoise 0.45,
                # 3D latent upscaler x2.0) = 7 NFE, 二采禁用自动时间分块。
                # cfg 1.0 由 _BasicGuider 天然满足; shift 12/3。
                # LoRA 槽挂 TaoMate-HD-preview-comfy.safetensors (strength 1.0,
                # 禁止再叠第二个加速 LoRA —— 适配器本身已是 3 步蒸馏)。
                # v14.315: tile_count 4 -> 8。x2.0 放大后整段 709,920 tokens, 4 块
                # 每块 ~272k, 24GB 卡上 DiT 只驻留得住 ~13.8GB, 单块 forward 仍要 3.1GB
                # → 实机 OOM。8 块每块 ~136k, 激活减半; 接缝由 128px overlap 融合。
                # v14.316: x2.0 -> x1.5(24GB 卡上 8 块 x2.0 + 3D 权重仍爆,
                #   DiT 驻留 16GB + 单块激活 2.7GB, fallback 21.6GB+2.2GB 仍不够)。
                #   代价: latent 120x68 -> 90x51, **出片只有 1440x816**。
                # v14.318 (用户 2026-11-05 决定): **改回 x2.0 + 16 块**, 保 1920x1088。
                #   16 块每块 = T * minHW * (axis/n + 2*ov) = 87*68*(120//16+16)
                #   = 136,068 tokens —— 比 OOM 那次的 8 块(183,396)还小一半,
                #   显存更安全, 而出片分辨率回到 1920x1088。
                #   _ff_auto_refine_tile_count 的 max_tiles=8 只在"请求落在病态区、
                #   需要扩块"的分支生效; 136k <= 450k 健康区 -> **原样尊重 16**,
                #   不会被夹回 8 块(实测 n=16 覆盖 120/120 单元格, 无空洞)。
                #   3D latent upscaler 按 **x2.0 训练** -> x2.0 就该挂它
                #   (v14.316 退 bislerp 是因为当时是 x1.5); 与当前默认管线同路径。
                # v14.323: 步数按档位分叉, 其余参数(16 块分块 / denoise 0.45 / x2.0 提升)共用。
                if _rp_mode == "TaoMate HD 8步+4步 渐进放大双采 (8+4 1080p直出)":
                    steps, refine_steps = 8, 4
                else:
                    steps, refine_steps = 4, 3
                tile_count, refine_denoise = 16, 0.45
                refine_enable = True
                refine_upscale_factor = 2.0   # v14.318: 1.5->2.0 (出片回到 1920x1088)
                refine_align_to = 32           # latent_mult=2 -> 34*2=68 不被吸附, 高度 1088
                tiled_refine = True   # v14.307: 空间分块保留(x2.0 放大后 tokens 大, 防二采 OOM)
                tile_overlap = 128
                # v14.281 同款: 时间分块 = 每段独立加噪 + 独立 seed, 接缝闪烁/
                # 段内碎花, 该档一律禁用(空间分块保留)。
                _rp_no_temp_chunk = True
                # 优先挂 3D 语义 latent 放大权重(训练倍率 x2.0); 都没有则退 bislerp
                # (v14.274 保范数), 并在状态栏提示降级。
                _tm_pick = None
                try:
                    # v14.314: 只挂**本机加载器真能吃下**的 pure-3D 权重。
                    # 原优先选 "h3_clean_latent_upscaler"(clean 因子化注意力架构:
                    # base.*/stem/to_delta), 但本机缺 h3_upscaler_dispatch.py 分派模块,
                    # 3D 加载器 strict load 必失败 → 静默退成 bislerp 插值。改为优先
                    # minimax_h3_latent_upscaler_3d_fp16(与 MV 档同款、实机已验证),
                    # 没有才退任意 3D 权重; 都没有则退 bislerp。
                    for _nm in _ff_get_upscaler_models():
                        if "minimax_h3_latent_upscaler_3d_fp16" in str(_nm).lower():
                            _tm_pick = _nm
                            break
                    if _tm_pick is None:
                        for _nm in _ff_get_upscaler_models():
                            if "latent_upscaler_3d" in str(_nm).lower():
                                _tm_pick = _nm
                                break
                except Exception:
                    _tm_pick = None
                # v14.318: 倍率回到 x2.0 —— 正是 3D latent upscaler 的训练倍率,
                # 所以**挂回** 3D 权重(v14.316 退 bislerp 是因为当时是 x1.5)。
                # 挂错倍率的权重比不挂更糟: 结构分布与训练不一致, 二采欠采样会把它
                # 固化成横带/波纹(v14.304 实机记录过同一类故障)。
                if _tm_pick:
                    print("[H3 Extender] v14.318 TaoMate HD: 本档二采倍率 x2.0 (3D latent "
                          "upscaler 训练倍率) -> 挂 3D 权重; 分块 16 块降单块激活")
                refine_upscaler_model = _tm_pick or ""
                shift_video, shift_audio = 12.0, 3.0
                denoise = 1.0
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                    print(f"[H3 Extender] v14.304 TaoMate HD(渲染管道): 采样器强制 euler + simple")
                scheduler = "simple"
                print(f"[H3 Extender] 🚀 TaoMate HD {steps}+{refine_steps} 半分辨率提升双采: "
                      "TaoMate HD 3步蒸馏渐进放大 LoRA (slmonker/TaoMate-HD-preview-comfy) —— "
                      f"一采 {steps} 步低分画布 + 二采 {refine_steps} 步精修 (denoise 0.45, latent x2.0, "
                      f"upscaler={refine_upscaler_model or 'bislerp 插值'}) = {steps + refine_steps} NFE; "
                      f"自动时间分块已禁用(防接缝闪烁); 空间分块保留({tile_count} 块, 防二采 OOM); "
                      "画布请设半尺寸(1080p 出片 -> 960x544), LoRA 槽挂 TaoMate-HD-preview-comfy.safetensors "
                      "(strength 1.0, 禁止叠加第二个加速 LoRA); cfg 1.0, shift 12/3")
            elif _rp_mode == "SingularityV2+Pika H3 8步 高动态长视频 (导演台双采)":
                # v14.322 (2026-11-05): B站《逼近SeeDance！Singularity V2 + Pika H3 +
                # 高动态LoRA H3导演台长视频生成》(BV1y8446DExi, 大凯AI) 配方落地。
                # 教程实测结论:
                #   ① 基模 Singularity v2 (H3 社区微调版, 更多动作/复杂运动训练,
                #      提示词遵循与真实感提升, 修复旧版音频参考问题; 平镜镜头 v1.3 略优,
                #      动作场面 v2 明显更强);
                #   ② 8 步 turbo LoRA: Pika H3 Flex Turbo 8-step HD Ref2VA
                #      (官方契约: 8 步 / CFG 1.0 / euler|lcm|res_multistep + simple,
                #      shift video 12.0 / audio 3.0, Flex style 0.6 已烘焙,
                #      奖励 6-8 步; 8 步同时跨过 H3 音频 ~6 步劣化下限);
                #      等价替代 LightX2V v1.0 8步 768P
                #      (minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16);
                #   ③ 两阶段生成 = 一采定运动 + 二采补细节, LoRA 分组纪律:
                #      一采挂 1 个高动态动作 LoRA (Motion_Repair_V2 / H3_Fight_Flow_V1 /
                #      H3_Combat_V2, 三选一 —— 全开互相干扰且与参考图冲突),
                #      二采保留低强度 0.3~0.4 (教程原话: 不用开到 0.6);
                #   ④ SelfLift 渐进二采加速: 二采 3 步 denoise 0.40 + 3D latent x2.0;
                #   ⑤ 上下文长视频: 27s 一镜到底 / 30s 双人战斗(3x10s 链) =
                #      one_shot_mode=on + motion context, 时间线扩展拼接;
                #   ⑥ 音频优化 LoRA 默认关 (+6 步音质档可为选配)。
                # 只改采样管道, 不碰模型图: 模型/LoRA 由 Loader 与 H3LoraStack 挂载。
                steps, refine_steps, tile_count, refine_denoise = 8, 3, 4, 0.40
                refine_enable = True
                refine_upscale_factor = 2.0
                refine_align_to = 32
                tiled_refine = True
                tile_overlap = 128
                refine_audio_denoise = 0.0   # 音频锁定: 低步数二采重绘人声必毁
                shift_video, shift_audio = 12.0, 3.0
                denoise = 1.0
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                    print("[H3 Extender] v14.322 SingularityV2+Pika8步(渲染管道): "
                          "一采采样器强制 euler (官方契约 euler|lcm|res_multistep + simple)")
                scheduler = "simple"
                if refine_sampler in ("inherit", "inherit (跟随一采)", "None", "none", ""):
                    refine_sampler = "euler"
                # 自动挂 3D latent upscaler(训练倍率 x2.0), 没有则退 bilinear
                if _FF_UPSCALER_MOD is not None:
                    try:
                        _sg_ups_opts = _ff_get_upscaler_models()
                        _sg_pick = None
                        for _nm in _sg_ups_opts:
                            if "latent_upscaler_3d" in str(_nm).lower() or "upscaler_3d" in str(_nm).lower():
                                _sg_pick = _nm
                                break
                        if _sg_pick:
                            refine_upscaler_model = _sg_pick
                            print(f"[H3 Extender] v14.322 SingularityV2+Pika8步: 自动选用 "
                                  f"3D latent upscaler '{_sg_pick}'")
                    except Exception as _sg_err:
                        print(f"[H3 Extender] v14.322 SingularityV2+Pika8步: 3D upscaler "
                              f"自动选择失败(走 bilinear): {_sg_err}")
                        refine_upscaler_model = "(bilinear interpolation, no model)"
                else:
                    refine_upscaler_model = "(bilinear interpolation, no model)"
                    print("[H3 Extender] ⚠️ v14.322 SingularityV2+Pika8步: 未探测到 3D latent "
                          "upscaler 插件, 二采放大走 bilinear 插值(画质略降)")
                print("[H3 Extender] 🎬 v14.322 SingularityV2+Pika H3 8步 高动态双采 "
                      "(BV1y8446DExi 配方): 一采 8 步(euler+simple, shift 12/3, CFG 1.0) | "
                      "二采 SelfLift 渐进 3 步(起点 σ 0.45~0.55, v14.393 denoise=真实起点噪声比例, "
                      f"upscaler={refine_upscaler_model or 'bilinear'}, tiled {tile_count}x{tile_overlap}) "
                      "= 11 NFE; 音频二采锁定不重绘 — "
                      "Loader 建议 Minimax-h3_Singularity_ref2va_v2_int8 (链式一镜到底可留 hybrid b25-49); "
                      "LoRA 挂 pika_h3_flex_turbo_8step_hd_ref2va (strength 1.0, style 0.6 已烘焙) "
                      "或 LightX2V 8步 v1.0 768P; 高动态动作 LoRA 三选一"
                      "(Motion_Repair_V2 / H3_Fight_Flow_V1 / H3_Combat_V2), 二采强度降 0.3~0.4; "
                      "长视频开 one_shot_mode=on + motion context")
            elif _rp_mode == "视频替换 (V2V 人物替换)":
                # v14.335 (2026-11-08): 视频人物替换 (Video Recast / H3 V2V character swap)
                #
                # 与其它档最大的不同: 本档的"画面"不是文生视频生成的, 而是资产库 @视频N
                # 的源画面经 video_vae.encode() 直接灌进 AV latent(见
                # _recast_build_av_latent)，采样只做"半重绘":
                #   denoise≈0.65 → 源片运动/构图/机位/剪辑点保留, 人物身份换成 @图N;
                #   音频行 noise_mask=0 → 源原声整段锁定, 替换后口型/对白/环境声原样对齐。
                # 因此:
                #   ① 只跑一采, 二采关掉 —— 二采 latent 放大后会把源片细节(脸/衣纹)抹平,
                #      身份转移到二采就散了(社区 Recast 也是单采出片);
                #   ② 不做段间 motion context 续链 —— 每段独立由源视频对应片段驱动,
                #      续链会把上一段"生成出来的画面"当上下文, 越链越偏;
                #   ③ 采样器 euler + simple + shift 12/3, 8 步(单采蒸馏档的安全步数);
                #   ④ 提示词由 _recast_prompt() 统一加"人物替换纪律"(原地保留用户指令)。
                steps = 8
                refine_enable = False
                refine_steps = 2
                refine_denoise = 0.0
                refine_upscale_factor = 1.0
                tiled_refine = False
                refine_audio_denoise = 0.0
                shift_video, shift_audio = 12.0, 3.0
                # denoise: 用户显式改过(≠1.0)就用用户值并夹在 [0.35, 0.95];
                # 没改过则用 0.65 —— 既足以换掉五官/发型, 又不至于丢掉源片动作轨迹。
                try:
                    _rc_dn_user = float(kwargs.get("denoise", 1.0) or 1.0)
                except Exception:
                    _rc_dn_user = 1.0
                denoise = (min(0.95, max(0.35, _rc_dn_user))
                           if abs(_rc_dn_user - 1.0) > 1e-6 else 0.65)
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                    print("[H3 Recast] 采样器强制 euler（源片运动保留的半重绘契约）")
                scheduler = "simple"
                one_shot_enabled = False
                one_shot_single_pass = False
                print("[H3 Recast] 🎭 视频人物替换档 (Video Recast / H3 V2V character swap): "
                      f"单采 {steps} 步 euler+simple shift 12/3 denoise {denoise:.2f} + 源原声锁定; "
                      "资产库 @视频N = 被替换源视频, @图N = 替换成的人物参考图; "
                      "源视频按 15s/段上限自动分 clip 逐段替换(45s → 3 段); "
                      "LoRA 槽建议挂 minimax_h3_角色替换character_swap_v1.5.safetensors (0.6~0.8)")
            elif _rp_mode == "HyperFlow H3 Flash 14B 单采 (4/6/8步 GGUF)":
                # v14.339 (2026-11-08): Video Rebirth HyperFlow H3 Flash 14B (13.7B/13.9B)。
                # 官方契约(ComfyUI-HyperFlow-Flash v1.0.0):
                #   步数 4/6/8 (6 = 默认均衡, 4 = 速度, 8 = 质量);
                #   euler + HyperFlow Sigmas 固定曲线(已乘 flow shift 12);
                #   CFG 1.0 单前向, 无负面提示词; 音视频同出 32kHz 立体声。
                # 因此本档:
                #   ① 单采, 二采关闭 —— 官方四套模板(t2v/i2v/flf2v/ref2v)都是单采;
                #   ② 不注入 dual-track shift —— shift 12 已烘焙在 HyperFlow 固定曲线里,
                #      再经模型 shift 映射会二次缩放(官方模板也没有 SigmaShift 节点);
                #   ③ 关闭 TST —— 官方配方不含 Time State Transport, 保持蒸馏契约纯净;
                #   ④ 权重为 GGUF, 必须用 HyperFlow GGUF Loader; 全量 H3 的加速 LoRA 不兼容。
                try:
                    _hf_user_steps = int(kwargs.get("steps", 6) or 6)
                except (TypeError, ValueError):
                    _hf_user_steps = 6
                # 6 是官方推荐默认; 用户把 steps 设为 4/8 时切换到速度/质量档,
                # 其余值一律回落到 6(模型只发布了 4/6/8 三组 sigma)。
                steps = _hf_user_steps if _hf_user_steps in (4, 6, 8) else 6
                refine_enable = False
                refine_steps = 2
                refine_denoise = 0.0
                refine_upscale_factor = 1.0
                tiled_refine = False
                refine_audio_denoise = 0.0
                denoise = 1.0
                shift_video, shift_audio = 12.0, 3.0
                dual_track_shift = False
                selflift_tst_enable = False
                omni_8step_mode = False
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                scheduler = "hyperflow_manual"
                _rp_hyperflow = True
                print("[H3 Extender] v14.339 HyperFlow H3 Flash 14B 档: "
                      f"单采 {steps} 步 euler + HyperFlow 固定 sigma (flow shift 12 已烘焙), "
                      "CFG 1.0 单前向, 无负面提示词, 二采关闭; "
                      "权重须用 HyperFlow GGUF Loader 加载, 全量 H3 加速 LoRA 不兼容")
            elif _rp_mode == "视频角色替换+动作迁移":
                # v14.341 (2026-11-09): 视频角色替换 + 动作迁移 (Video Remix, 无 LoRA)
                # 教程 BV1HBWJ6HEkg 的采样参数在此落地:
                #   一采 8 步（默认；教程原口径 4 步，可把 widget steps 改回 4）—
                #     v14.344 实测: 4 步 + denoise 0.62 时 sigmas 起点 σ≈0.96（近乎整帧重生），
                #     4 步根本去不干净 → 脸糊、身份像"混合体"，故默认抬到 8 步；
                #   二采 5 步（先把 latent 放大 1.5x 再补细节）；
                #   euler + simple + shift 12/3（H3 默认双轨偏移）;
                #   不加 swap/角色替换 LoRA —— 身份完全由 @图N 参考图与提示词纪律承担,
                #   只允许用户自己挂加速 LoRA（加速 LoRA 不参与身份语义）。
                # 与第 33 档的区别: 段间 motion context 续接**必须开着**(22 帧重叠锁定),
                # 且掩码按模式: 人物替换=人物掩码锁背景 / 动作迁移=全画幅, 音频默认锁源原声。
                # 一采步数: 默认 8; widget 里显式填过(4~16)就尊重用户 —— 想回到教程原
                # 口径 4 步，把 steps 改成 4 即可（欠噪风险自负）。
                try:
                    _rm_steps_user = int(kwargs.get("steps", 8) or 8)
                except Exception:
                    _rm_steps_user = 8
                steps = max(4, min(16, _rm_steps_user))
                # v14.347: 打开 exact sigma —— "denoise 0.62" 从此就是真实起点 σ=0.62,
                # 不再是 H3 平顶曲线造成的 σ≈0.93 整帧重生(那是出片糊的根因)。
                _SIGMAS_EXACT = True
                refine_enable = True
                refine_steps = 5
                # v14.347: 二采 denoise 0.50 → 0.30(且现在也是真实 0.30)。
                # 旧值在伪 denoise 下实际≈0.9, 等于二采把一采画面整帧洗一遍 → 糊。
                refine_denoise = 0.30
                refine_upscale_factor = 1.5
                refine_upscaler_model = "(bilinear interpolation, no model)"
                refine_audio_denoise = 0.0   # 二采音频行锁定(不重绘), 口型/原声不变
                tiled_refine = False
                shift_video, shift_audio = 12.0, 3.0
                # 段间重叠 22 帧锁定续接（教程固定 22 帧；context 档里 22 即该档位）
                context_length = "22"
                one_shot_enabled = False
                one_shot_single_pass = False
                # denoise: 用户显式改过(≠1.0)就夹在 [0.35, 0.95]; 没改过用 0.62。
                # 低于 0.5 换不动身份, 高于 0.8 会漂掉源片动作轨迹。
                try:
                    _rm_dn_user = float(kwargs.get("denoise", 1.0) or 1.0)
                except Exception:
                    _rm_dn_user = 1.0
                denoise = (min(0.95, max(0.35, _rm_dn_user))
                           if abs(_rm_dn_user - 1.0) > 1e-6 else 0.62)
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                    print("[H3 Remix] 采样器强制 euler（源片动作保留的半重绘契约）")
                scheduler = "simple"
                print("[H3 Remix] 🎭 视频角色替换+动作迁移档 (Video Remix, no-LoRA): "
                      f"一采 {steps} 步 + 二采 {refine_steps} 步(放大 1.5x, denoise 0.30), "
                      f"euler+simple shift 12/3, 半重绘 denoise {denoise:.2f}(v14.347 起为真实 σ 起点); "
                      "段间 22 帧重叠锁定续接; 人物替换默认用人物掩码锁住源背景"
                      "（提示词写'新场景'才切全画幅做动作迁移, 或用 BSAI_H3_REMIX_KEEP_BG 强制）；"
                      "资产库 @视频N = 源视频(动作/机位/原声), @图N = 替换成的角色; "
                      "本档不挂 swap/角色替换 LoRA（只可挂加速 LoRA）")
            elif _rp_mode in _VIGGLE_RP_LABELS:
                # v14.345 (2026-11-09): 第 36 档 —— 官方 Viggle Remake 两个 LoRA
                # (swap / edit) 的 6 步蒸馏契约。教程口径 (BV19xWx69Eu6):
                #   6 步采样, 固定 timesteps 曲线(swap 与 edit 两组 knots, 不是 simple),
                #   cfg 1.0 / euler, 无二采, denoise 1.0(全噪重绘);
                #   源片整段作 cond video, 源原声锁 clean, 参考图 @图N 决定替换目标;
                #   LoRA 只认 FL2VA 基座, 且必须挂在 bypass 槽。
                steps = 6
                refine_enable = False
                refine_steps = 0
                refine_denoise = 0.0
                refine_upscale_factor = 1.0
                refine_audio_denoise = 0.0
                tiled_refine = False
                denoise = 1.0
                shift_video, shift_audio = 12.0, 3.0
                selflift_tst_enable = False
                omni_8step_mode = False
                context_length = "0"
                one_shot_enabled = False
                one_shot_single_pass = True
                _vg_task = _viggle_task()
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                # v14.345: 6 步是官方蒸馏契约（sigma knots 长度即步数），widget 里填别的值
                # 不参与采样；这里同步成 6 让日志/存盘与官方口径一致，避免误读。
                steps = 6
                scheduler = ("viggle_remake_edit_manual" if _vg_task == "edit"
                             else "viggle_remake_swap_manual")
                print("[H3 Viggle] 🎬 Viggle Remake 视频改写档: "
                      f"任务={_vg_task}, 6 步 euler + 官方固定 sigma 曲线, cfg 1.0 单采, "
                      "源片整段作 cond video + 源原声锁 clean + 目标 latent 全噪; "
                      "LoRA 必须挂 viggle_remake_swap/edit（只认 FL2VA 基座, 走 bypass 槽）")
            else:
                _rp_handled = False
            if _rp_handled:
                print(f"[H3 Extender] v14.172 渲染管道: {_rp_mode} -> 一采steps={steps} 二采steps={refine_steps} tile={tile_count} denoise={refine_denoise} (速度档不叠加)")
                speed_preset = "custom"  # 防下方 speed_preset 分支再覆盖配方档参数
                # v14.375 (2026-11-11): 采样档 vs 渲染管道，谁说了算 —— 一镜到底「单采无缝」
                # 不再静默吃掉管线二采。
                # 实测 10:07 那轮(h3_clip_250_1_1794362835): OneShotSmp=Single (seamless) +
                # 管线 PIKA H3 Flex 8步+2步 双采, 日志却打印「一镜到底·单采无缝：已跳过二采
                # (refine)」, 12s 只跑了一采 8 步 —— 用户选的双采档等于空转。
                # 现改为: 管线自己声明了二采(refine_enable 且 refine_steps >= 1)就以管线为准
                # 执行二采, 并把冲突与真正生效的配方一起播报出来(不静默)。
                if (bool(one_shot_enabled) and bool(one_shot_single_pass)
                        and bool(refine_enable) and int(refine_steps or 0) >= 1):
                    one_shot_single_pass = False
                    print(f"[H3 Extender] ⚠️ v14.375 采样档与管线冲突: OneShotSmp=单采无缝, "
                          f"而渲染管道「{_rp_mode}」声明二采 {refine_steps} 步 -> 按管线执行双采 "
                          f"(一采 {steps} 步 + 二采 {refine_steps} 步 denoise {refine_denoise})。"
                          f"确实只要单采时请把渲染管道换成单采档(如「FastH3 Omni 8步单采」)")
        # v14.237 (2026-10-28): SegAttention 协同检测修正 —— KJNodes 实际注册名是
        # "PathchSageAttentionKJ"(Sage Attention, 拼写带 h, 见 KJNodes __init__.py NODE_CONFIG),
        # 旧检测名 "PatchSegAttentionKJ" 从未被任何插件注册过 -> 环境已装 sageattention
        # 2.2.0+cu130 + KJNodes PathchSageAttentionKJ 节点也永远误报"未检测到"。
        # 现同时兼容两个名(防 KJNodes 改名), 命中任一即视为 SegAttention 就绪。
        try:
            _h3_seg_map = __import__("nodes").NODE_CLASS_MAPPINGS
            _has_segattn = bool(_h3_seg_map and
                                ("PathchSageAttentionKJ" in _h3_seg_map or
                                 "PatchSegAttentionKJ" in _h3_seg_map))
        except Exception:
            _has_segattn = False
        # v14.258: 扩展外部稀疏注意力节点探测 —— 大小写不敏感扫描 NODE_CLASS_MAPPINGS
        # key, 同时识别 Veda H3 predictor 与 Spark-H3 节点(纯打印诊断, 不改任何行为逻辑,
        # 不引入对未安装节点的硬依赖)。
        _ext_sparse_hits = {"veda": [], "spark": [], "sageattn": [], "segattn": []}
        try:
            for _k in (_h3_seg_map.keys() if _h3_seg_map else []):
                _kl = str(_k).lower()
                for _kw in _ext_sparse_hits:
                    if _kw in _kl:
                        _ext_sparse_hits[_kw].append(str(_k))
        except Exception:
            pass
        _ext_sparse_seen = {k: sorted(set(v)) for k, v in _ext_sparse_hits.items() if v}
        if _ext_sparse_seen:
            _ext_summary = " / ".join(
                f"{_kw}: {', '.join(_hits[:3])}{' ...' if len(_hits) > 3 else ''}"
                for _kw, _hits in _ext_sparse_seen.items())
            print(f"[H3 Extender] v14.258 已检测到外部稀疏注意力节点: {_ext_summary}")
            if "veda" in _ext_sparse_seen or "spark" in _ext_sparse_seen:
                print("[H3 Extender] ⚠️ v14.258 警告: 同时挂 Veda/Spark-H3 外部稀疏注意力与插件 "
                      "sol_attn(sol_max_tokens 门控)会互相抢占/踢掉对方, 请只保留一个 —— "
                      "用插件 Sol-Attn 就别接外部稀疏节点, 反之亦然")
        if _has_segattn:
            print("[H3 Extender] v14.234 ✅ 已检测到 KJNodes PathchSageAttentionKJ (SegAttention 2.2.0) — "
                  "插件注意力 override 让位协同, 稀疏注意力交 SegAttention 接管")
        else:
            print("[H3 Extender] v14.234 未检测到 SegAttention: 安装 KJNodes + SegAttention 2.2.0 环境包 "
                  "(匹配 Python/Torch/CUDA) 叠加可再降 81% 耗时 — 平缓文戏场景推荐, 高动态场景请酌情")
        # v14.220 直播带货配音模式音频参数精修（在采样配方之后、进采样之前生效）。
        # 01/02 走「全自动」配方的音频重绘 0.7（精修模型生成人声清晰度）；
        # 03 声音完全由外部 lip_voice 提供 → 锁定（0.0）不重绘，避免外部原声被二次处理。
        if _ls_mode == "03":
            refine_audio_denoise = 0.0
            # v14.225: lip_voice 外部音频已锁定(audio_denoise=0.0), 模型不生成音频,
            # 12 步是给"模型自生成音频≥12步"保质量的下限; 8 步蒸馏模型用 8 步是
            # 契约(v14.183 实测 10 步掉画质/标签变糊)。lip_voice 下省 4 步 x ~68s
            # ≈ 4.5 分钟/clip。01/02 模型自生成音频仍保持 12 步不动。
            if steps > 8:
                print(f"[H3 Extender] v14.225 03 lip_voice对口型: 音频已锁定不生成, "
                      f"一采 {steps}->8 步(8步蒸馏契约, 省 {steps-8} 步 x ~68s ≈ "
                      f"{(steps-8)*68//60} 分钟/clip)")
                steps = 8
            print(f"[H3 直播带货] 03 lip_voice对口型: 音频由外部音频(lip_voice/lip_audio)提供, 已锁 refine_audio_denoise=0.0（不重绘原声）")
        elif _ls_mode in ("01", "02"):
            refine_audio_denoise = 0.7
            print(f"[H3 直播带货] {_LIVESTREAM_VOICE_MODE_LABEL.get(_ls_mode, _ls_mode)}: 模型生成人声, 音频重绘 0.7 精修清晰度 + 一采12步达标")
        # v14.272 一镜到底·2K双采（1采8步 / 2采4步）—— 自带配方档。
        # 一镜到底的第三档「双采无缝 (8+4)」不覆盖任何数值, 全靠 widget (用户
        # 工作流是 12 步 + factor 2.0 → 一采 1920x1088 出来 3840x2176=4K)。
        # 本档把配方钉死为 1采8步 / 2采4步 / denoise 0.45 / euler / shift 12-3,
        # 并把二采倍数留给分辨率解析之后按"输出宽 2560(2K)"换算(见下方声明尺寸段),
        # 这样 1280 一采 → x2.00 = 2560, 1920 一采 → x1.33 = 2560, 都是 2K。
        # _hv2x_decl 保持 1.0: 本档走真实 latent 放大, 不依赖 HyperVAE 2x 解码
        # (用户 VAE 是 minimax_h3_sol_vae, 挂 HyperVAE 声明会把 2K 变成假放大)。
        if one_shot_dual_2k:
            # v14.279 (2026-11-02 fix): 渲染管道配方优先 —— 旧实现无条件写死
            # steps/refine_steps/denoise = 8/4/0.45, 把用户在「渲染管道」选的
            # 配方(日志 27 行声明 12/6/0.35)静默覆盖(日志 33 行 + 实跑),
            # 所有渲染管道模式都等于不生效。现本档只保留**结构约束**:
            # 开二采 / 单次采样 token 预算 / global 全上下文 / 不分块 /
            # HyperVAE 声明 1.0; 数值配方与采样器/shift 交给渲染管道。
            # 仅当未选中任何渲染管道时, 才回退到本档后备配方 8+4/0.45。
            _rp_is_recipe279 = bool(locals().get("_rp_handled", False)) and \
                str(_rp_mode or "").strip() not in ("", "(none)", "custom", "None")
            if _rp_is_recipe279:
                print(f"[H3 Extender] v14.279 一镜到底·2K双采: 渲染管道配方优先 "
                      f"({_rp_mode}) -> 一采 {steps} 步 / 二采 {refine_steps} 步 / "
                      f"denoise {float(refine_denoise):.2f} / sampler={sampler_name} "
                      f"/ shift {float(shift_video):g}-{float(shift_audio):g} "
                      f"(2K 档不再覆盖)")
            else:
                steps, refine_steps, tile_count, refine_denoise = 8, 4, 4, 0.45
                shift_video, shift_audio = 12.0, 3.0
                if str(sampler_name) != "euler":
                    sampler_name = "euler"
                print("[H3 Extender] v14.279 一镜到底·2K双采: 未选渲染管道, "
                      "使用本档后备配方 一采 8 步 + 二采 4 步 (denoise 0.45) + euler")
            refine_enable = True
            _hv2x_decl = 1.0
            # v14.275 (fix): 二采强制 global 全上下文, 禁用空间分块。
            # 本档 latent 已被 3D upscaler 放大到 709,920 tokens, 空间分块每块只有
            # 46/120 的宽度, 却仍带整套 ref2va 角色参考(PackedLayout 里 refs/keyframes
            # 一并裁到 tile 尺寸) → 模型在每块里独立重新构图: 实机 tile1(0~736px)凭空
            # 画出放大版人脸, tile4(1312~1920px)画出第二个沈砚, cosine 融合后就是
            # 半透明重影 + 满屏碎屑。global 包装不裁空间轴: 整帧一次前向, attention
            # 全序列稀疏(Sol-Attn), 仅 MLP 按 4096 token 分块压激活 → 无接缝、无重构图。
            # v14.253 的教训已写在直播带货档: 横带叠加正是 spatial 分块造成的。
            tiled_refine = False
            if not refine_mem_global:
                refine_mem_global = True
                refine_mem_mode = "global (全上下文省显存)"
                print("[H3 Extender] v14.275 一镜到底·2K双采: 二采强制 global 全上下文"
                      "(禁用 spatial 空间分块 —— 每块独立重构图会造成重影/碎屑)")
            print("[H3 Extender] 🎥 v14.279 一镜到底·2K双采: 只接管结构(二采/"
                  "global/不分块), 二采倍率按单次采样 token 预算取; 步数/denoise "
                  "以渲染管道为准")
        # v14.221 (自动提速护栏): 检测到 HyperVAE 2x 权重可用且当前二采会因
        # latent x2.0 放大导致 24GB 换页超时(实测 834s/步)时, 自动把二采
        # 降级到"双采2K"提速路径: factor=1.0 + HyperVAE 2x 解码直出 2K,
        # 二采 token 由 873k 回到 218k(Sol-Attn 健康区), 每步 ~80-90s。
        # 像素仍是 2K 不缩水(声明尺寸经 _hv2x_decl 翻倍)。仅对"默认双采"档
        # 且有 HyperVAE 权重时生效, 其余档位/无权重机器完全不受影响。
        # 用环境变量 BSAI_H3_AUTO_HV2X=0 可关闭该自动降级。
        _auto_hv2x = False
        try:
            if (os.environ.get("BSAI_H3_AUTO_HV2X", "1") != "0"
                    and not one_shot_dual_2k
                    and bool(refine_enable)
                    and float(refine_upscale_factor or 1.0) > 1.0
                    and (_rp_mode in ("", "Sol-H3 Self-Lift 双采 (默认)", "(none)")
                         or _rp_mode == "直播带货（全自动）")):
                # 覆盖默认双采档 + 直播带货(全自动)档。直播带货档原本强制
                # 3D latent upscaler x2.0(873k tokens -> 24GB 换页 -> 每块 ~400s),
                # 有 HyperVAE 2x 权重时自动降 factor=1.0(218k tokens, 等价一采规模,
                # 每步 ~80-90s) + HyperVAE 2x 解码直出 2K, 输出像素与像素契约一致
                # (一采像素 x2), 无 tiles 接缝。音频配方(12 步/重绘)保持不变。
                # 4K直出 / FastH3 Omni×SelfLift 等显式配方档保持原样, 不破坏其像素契约。
                _hv2x_probe = None
                for _hv2x_dir in folder_paths.get_folder_paths("vae"):
                    for _hv2x_file in os.listdir(_hv2x_dir):
                        _hv2x_l = _hv2x_file.lower()
                        if _hv2x_l.endswith(".safetensors") and ("hyper" in _hv2x_l or "2x" in _hv2x_l):
                            _hv2x_probe = os.path.join(_hv2x_dir, _hv2x_file)
                            break
                    if _hv2x_probe:
                        break
                if _hv2x_probe:
                    _hv2x_decl = 2.0
                    _auto_hv2x = True
                    _r_new_factor = 1.0
                    if refine_upscaler_model and not str(refine_upscaler_model).startswith("("):
                        refine_upscaler_model = "(bilinear interpolation, no model)"
                    print(f"[H3 Extender] v14.221 自动提速(含直播带货档): 检测到 HyperVAE 2x 权重 "
                          f"({os.path.basename(_hv2x_probe)}), 二采 factor "
                          f"{float(refine_upscale_factor or 1.0):.1f} -> 1.0 (latent 不放大, 由 "
                          f"HyperVAE 2x 解码直出 2K, 二采 token 873k->218k 回 Sol-Attn 健康区, "
                          f"每步 ~80-90s)。设 BSAI_H3_AUTO_HV2X=0 可关闭。")
                    refine_upscale_factor = _r_new_factor
        except Exception as _hv2x_auto_err:
            print(f"[H3 Extender] v14.221 自动提速探测失败(可忽略): {_hv2x_auto_err}")
            _auto_hv2x = False
        # v14.182: 双采2K 档 —— 解码用 HyperVAE 2x (encoder 16x 不变, decoder 32x
        # pixel_shuffle 2x)。整体替换 vae: encode 路径(参考图/conditioning)输出
        # 与原生 VAE 完全一致(权重含完整 encoder, encoder_unchanged=True), decode
        # 路径自动输出 2x 像素。权重自动探测 models/vae 中 hyper*2x* 文件;
        # 加载失败回退原生 vae 并降级提示(不崩)。
        if _rp_mode == "双采2K（HyperVAE 2x 解码）" or _auto_hv2x:
            _hv2x_path = None
            try:
                for _hv_dir in folder_paths.get_folder_paths("vae"):
                    for _hv_file in os.listdir(_hv_dir):
                        _hv_l = _hv_file.lower()
                        if _hv_l.endswith(".safetensors") and ("hyper" in _hv_l or "2x" in _hv_l):
                            _hv2x_path = os.path.join(_hv_dir, _hv_file)
                            break
                    if _hv2x_path:
                        break
            except Exception:
                _hv2x_path = None
            if _hv2x_path:
                try:
                    # v14.221c: 按相对 __file__ 的绝对文件路径加载, 修复 ComfyUI 动态
                    #   加载插件时 "No module named 'bsai_h3_hypervae_2x'" —— 插件目录
                    #   未必在 sys.path, 裸 import 会失败并回退原生 VAE(二采虽提速但
                    #   解码仍是 1x 像素, 2K 契约落空)。路径由 __file__ 相对推导,
                    #   绝不写死盘符, 整合包换盘符/升级版本号仍可移植。
                    import importlib.util as _ilu_hv
                    _hv2x_mod_path = os.path.join(
                        os.path.dirname(os.path.abspath(__file__)), "bsai_h3_hypervae_2x.py")
                    _hv2x_spec = _ilu_hv.spec_from_file_location("bsai_h3_hypervae_2x", _hv2x_mod_path)
                    if _hv2x_spec is None or _hv2x_spec.loader is None:
                        raise ImportError(f"spec_from_file_location 失败: {_hv2x_mod_path}")
                    _hv2x_mod = _ilu_hv.module_from_spec(_hv2x_spec)
                    _hv2x_spec.loader.exec_module(_hv2x_mod)
                    _load_hv2x = _hv2x_mod.load_hyper_vae_2x
                    _hv_vae, _hv_report = _load_hv2x(_hv2x_path)
                    _hv_vae.model_name = os.path.basename(_hv2x_path)  # ref2va cache key 区分
                    vae = _hv_vae
                    print(f"[H3 Extender] v14.182 双采2K: HyperVAE 2x 解码已装载 ({os.path.basename(_hv2x_path)}, "
                          f"decode_scale=2x, encode_scale=16x, 全程只解码一次)")
                except Exception as _hve:
                    print(f"[H3 Extender] ⚠️ v14.182 双采2K: HyperVAE 2x 加载失败, 回退原生 VAE: {_hve}")
                    vae = vae  # 保持原生
            else:
                print(f"[H3 Extender] ⚠️ v14.182 双采2K: models/vae 未探测到 HyperVAE 2x 权重 "
                      f"(hyperVAEKrea2Minimax_v20MinimaxX2Upscale.safetensors), 回退原生 VAE 解码(像素 1x, 档位不生效)")
        if speed_preset == "极速":
            # v1.85: 二采 2->3 步 + denoise 0.55->0.5. 写实动态(打斗)场景 2 步二采
            # 在 55% 重噪下收敛不足导致画面发糊, 3 步收敛更好保留高频细节.
            # 耗时 ~20min/clip(原~15min), 仍比均衡(6+4, ~28min)省 ~28%.
            steps, refine_steps, tile_count, refine_denoise = 4, 3, 4, 0.5
        elif speed_preset == "均衡":
            steps, refine_steps, tile_count, refine_denoise = 6, 4, 4, 0.55
        elif speed_preset == "精细":
            steps, refine_steps, tile_count, refine_denoise = 8, 6, 4, 0.55
        elif speed_preset == "极速-VDN":
            # v1.86: VDN 档 (搭配 VDN 版工作流). 一采固定 8 步(VDN DMD 蒸馏最优步数,
            # 质量≈dense 50 步, 且线性注意力长链更稳), 二采 3 步快速收敛.
            # 需用 VDN 工作流提供 model(UNETLoader+ApplyVDNH3, 跳过 FastH3 LoRA/Sol-Attn).
            # v1.90: 极速档强制关分块——实测 DynamicVRAM 下分块二采 900s/步
            # (0驻留全staged × 4 tile 序列 + overlap 重复计算), 全帧 1 次连续
            # staged 预计 ~400-500s/步. 画质档(均衡/精细/均衡-VDN/精细-VDN)
            # 保留分块防 4K 全幅 OOM. 24GB 卡全帧 DynamicVRAM staged 有兜底.
            steps, refine_steps, tile_count, refine_denoise = 8, 3, 4, 0.5
            if tiled_refine:
                tiled_refine = False
                print(f"[H3 Extender] v1.90 极速-VDN: 强制关分块(全帧二采), 原 tiled_refine=True 已覆盖")
        elif speed_preset == "均衡-VDN":
            # 一采 VDN 8 步 + 二采 4 步: 推荐档, 质量接近精细(FastH3 8+6), 时间省 ~25%.
            steps, refine_steps, tile_count, refine_denoise = 8, 4, 4, 0.55
        elif speed_preset == "精细-VDN":
            # 一采 VDN 8 步 + 二采 6 步: 与 FastH3 精细同画质, 一采更快更稳.
            steps, refine_steps, tile_count, refine_denoise = 8, 6, 4, 0.55
        elif speed_preset == "FastH3-Trim":
            # FastH3 Trim: 42层剪枝模型(nvfp4), 8步一采+4步二采双采.
            # 比V2模型一采快15%, 二采4步细节更丰富(2026-10-13 用户要求 8+4 档).
            steps, refine_steps, tile_count, refine_denoise = 8, 4, 4, 0.45
        elif speed_preset == "FastH3-4步VSA":
            # FastH3 4步VSA: 4步DMD2蒸馏+VSA稀疏注意力LoRA, 配2步二采.
            # 最快速度, 质量略低于8步但远快于50步base.
            steps, refine_steps, tile_count, refine_denoise = 4, 2, 4, 0.45
        elif speed_preset == "Turbo-v4":
            # P1 (2026-10-17): Turbo LoRA v4 step600 EMA. 6步一采(v4 画质舒适区) + 4步二采.
            # v14.173: 8+4/denoise0.45 与渲染管道档对齐 (复杂场景防结构漂移/变形)
            # 双轨迹 shift 12/3 (官方 v4 参数); 建议手动把采样器切到 res_multistep 以贴合官方配方.
            steps, refine_steps, tile_count, refine_denoise = 8, 4, 4, 0.45
            shift_video, shift_audio = 12.0, 3.0
        elif speed_preset == "DMAD-4步":
            # P1 (2026-10-17): DMAD 4-step 蒸馏 LoRA, shift 12/2,
            # 强制 lcm 采样器(DMAD 官方配方: LCM + simple grid, 无 CFG≈1).
            # v14.386: 步数与渲染管道档对齐 —— 1 采 8 步 + 2 采 2 步
            # (旧值 4+2; 二采在 v14.384 起默认只超分放大不重绘)。
            steps, refine_steps, tile_count, refine_denoise = 8, 2, 4, 0.5
            shift_video, shift_audio = 12.0, 2.0
            if str(sampler_name) != "lcm":
                sampler_name = "lcm"
                print(f"[H3 Extender] DMAD-4步: 采样器强制 lcm (DMAD 官方配方)")
            print(f"[H3 Extender] v14.386 DMAD(旧速度档遗留值): 一采 8 步 + 二采 2 步")
        elif speed_preset == "武戏组合拳":
            # v14.176: 与渲染管道档对齐 — YZ金鱼「终极篇」武戏配方 (BV1LKJm6VELc):
            # 一采6步 + 二采6步(总12步, 武戏拟合更清晰), shift 12/3, euler+simple,
            # 帧数对齐 H3 17 块。旧值 8+4 仍可用但拟合弱于 6+6。
            steps, refine_steps, tile_count, refine_denoise = 6, 6, 4, 0.45
            shift_video, shift_audio = 12.0, 3.0
            _h3_align17 = True
            if str(sampler_name) != "euler":
                sampler_name = "euler"
                print(f"[H3 Extender] v14.176 武戏组合拳: 采样器强制 euler + simple 调度 (YZ终极篇武戏配方)")
        elif speed_preset == "FastH3 Omni 8步单采":
            # v14.172 (2026-10-22): 速度档已移除 Omni 枚举(统一走渲染管道)。
            # 本分支仅兼容 v14.170 遗留旧工作流(速度档仍存有 Omni 值) —— 命中时
            # 同样联动渲染管道, 行为与 v14.170 完全一致; 新工作流请从「渲染管道」
            # 下拉选择 FastH3 Omni 8步单采。
            steps, refine_steps, tile_count, refine_denoise = 8, 2, 4, 0.5
            if not omni_8step_mode:
                omni_8step_mode = True
                _render_pipeline = "FastH3 Omni 8步单采"
                refine_enable = False
                denoise = 1.0
                shift_video, shift_audio = 12.0, 3.0
                print(f"[H3 Extender] v14.172 FastH3 Omni 8步单采(旧速度档遗留值兼容): 渲染管道已切 Omni, 跳过二采, 一采 8 步蒸馏直出")
        elif speed_preset == "QAD-v2-8步":
            # v14.196 (2026-10-25): QAD-v2-8步 也支持速度档遗留值兼容 —— 行为与
            # 渲染管道档完全一致(8 步蒸馏直出单采, shift 10/3 官方 QAD-v2 schedule)。
            # 新工作流请从「渲染管道」下拉选择 QAD-v2-8步。
            steps, refine_steps, tile_count, refine_denoise = 8, 2, 4, 0.5
            if not omni_8step_mode:
                omni_8step_mode = True
                _render_pipeline = "QAD-v2-8步"
                refine_enable = False
                denoise = 1.0
                shift_video, shift_audio = 10.0, 3.0
                print(f"[H3 Extender] v14.201 QAD-v2-8步(旧速度档遗留值兼容): 渲染管道已切 QAD-v2, 跳过二采, 一采 8 步蒸馏直出, shift 10/3 (官方 QAD-v2 NVFP4 schedule)")
        if speed_preset != "custom":
            print(f"[H3 Extender] v1.83 速度预设: {speed_preset} -> 一采steps={steps} 二采steps={refine_steps} tile={tile_count} denoise={refine_denoise} (原={_sp_old})")
        # v14.279: 唯一权威配方日志 —— 打印在所有管道/速度档覆盖之后, 保证
        # "日志声明 == 实际实跑", 不再出现渲染管道档声明 12/6 实跑 8/4 的分歧。
        print(f"[H3 Extender] v14.279 EFFECTIVE-RECIPE: pipeline={_rp_mode or '(none)'} "
              f"speed_preset={speed_preset} 一采 steps={steps} sampler={sampler_name} "
              f"scheduler={scheduler} denoise={denoise} shift={shift_video}/{shift_audio} "
              f"| 二采 enable={refine_enable} steps={refine_steps} "
              f"denoise={refine_denoise} factor={refine_upscale_factor} "
              f"tile={tile_count} mem={refine_mem_mode} "
              f"temp_chunk={'off(原版)' if _rp_no_temp_chunk else 'auto'}")
        print(f"[H3 Extender] REFINE-PARAMS: enable={refine_enable!r} denoise={refine_denoise!r} steps={refine_steps!r} factor={refine_upscale_factor!r} model={refine_upscaler_model!r} align={refine_align_to!r} audio={refine_audio_denoise!r}")
        unique_id = kwargs.get("unique_id", None)
        stored_prompt_pack_signature = _prompt_pack_signature_from_state(clips_json)
        clips = _parse_clips_json(clips_json)
        merge_output = _merge_output_from_state(clips_json)

        # v14.285 (多人对话修复): 前端 card UI 手动编辑 clip.prompt 时极易误删
        # @图N / @音频N 标签（尤其多角色分镜里 @图2/@图3/@图4），被删后资产参考
        # 与音色绑定全部失效且无法从 clips_json 恢复。
        # 补救：独立的 prompt_source 输入（PrimitiveStringMultiline 等）始终保留
        # 原始分镜脚本，用其中 [分镜N] 段重建 clip.prompt——前端 parseStoryboard
        # 本身不清洗资产标签，prompt_source 是标签的事实来源。
        # 仅当 prompt_source 有 [分镜N] 标记且段数 == clip 数、且 segment 比原
        # prompt 多出资产标签时触发（避免误伤手动构建的无标记 clips）。
        if prompt_source and clips:
            import re as _sb_re
            _marker_re = _sb_re.compile(r'\[(?:分镜|Shot|shot|SHOT)\s*(\d+)\]')
            _idxs = [(int(m.group(1)), m.end()) for m in _marker_re.finditer(str(prompt_source))]
            if _idxs and len(_idxs) == len(clips):
                for _i, _clip in enumerate(clips):
                    _s_start = _idxs[_i][1]
                    _s_end = _idxs[_i + 1][1] if _i + 1 < len(_idxs) else len(str(prompt_source))
                    _seg = str(prompt_source)[_s_start:_s_end].strip()
                    _old_tags = set(_sb_re.findall(r'@[图视频音频]\d+', str(_clip.get("prompt", ""))))
                    _new_tags = set(_sb_re.findall(r'@[图视频音频]\d+', _seg))
                    if _new_tags - _old_tags:
                        _clip["prompt"] = _seg
                        print(f"[H3 Extender] CLIP {_i + 1} prompt 已从 prompt_source 重建 "
                              f"(恢复 @图N 标签: {_new_tags - _old_tags})")

        # v1.22: per-clip external prompt overrides (clip_prompt_1..clip_prompt_12).
        # Applied before @图N resolution so asset tags in the override are resolved too.
        for _ci in range(1, 13):
            _pk = f"clip_prompt_{_ci}"
            _pv = kwargs.get(_pk)
            if _pv and _ci - 1 < len(clips) and str(_pv).strip():
                clips[_ci - 1]["prompt"] = str(_pv).strip()
                print(f"[H3 Extender] CLIP {_ci} prompt overridden by external port {_pk}")

        # Split unified prompt_source at first [分镜N] marker:
        # text before → global_prompt, text from [分镜N] onwards → storyboard
        # (storyboard segments are handled by frontend JS auto-CLIP creation)
        global_prompt = None
        if prompt_source:
            import re as _re
            sb_match = _re.search(r'\[(?:分镜|Shot|shot|SHOT)\s*\d+\]', str(prompt_source))
            if sb_match:
                global_prompt = str(prompt_source)[:sb_match.start()].strip()
            else:
                global_prompt = str(prompt_source).strip()
        else:
            # v2.57 (2026-09-21 fix): 全局提示词为空时强制清空，避免旧缓存污染新脚本。
            # 之前 v1.100 会从 clips_json 读旧全局提示词，导致换脚本后画面还是旧内容。
            global_prompt = None
            print("[H3 Extender] v2.57: 外部全局提示词为空，强制不使用旧全局提示词缓存")

        # Resolve @图N/@视频N/@音频N from connected Asset Library.
        # Include the global prompt as a pseudo-clip so its @图N tags are
        # resolved with the same image numbering as clip prompts.
        if global_prompt:
            print(f"[H3 Extender] global_prompt received (len={len(str(global_prompt))}): '{str(global_prompt)[:80]}'")
            gp_clip = {"prompt": str(global_prompt)}
            resolved_all, resolved_img_paths, resolved_aud_paths, _all_asset_paths, _speaker_audio_map, _picture_asset_map = self._resolve_asset_library_refs(
                [gp_clip] + clips, asset_library
            )
            global_prompt = resolved_all[0]["prompt"]
            clips = resolved_all[1:]
            global_asset_paths = _all_asset_paths[0] if _all_asset_paths else []
            clip_asset_paths = _all_asset_paths[1:] if len(_all_asset_paths) > 1 else []
            print(f"[H3 Extender] global_prompt after resolution: '{str(global_prompt)[:80]}'")
        else:
            print("[H3 Extender] no global_prompt connected")
            clips, resolved_img_paths, resolved_aud_paths, clip_asset_paths, _speaker_audio_map, _picture_asset_map = self._resolve_asset_library_refs(clips, asset_library)
            global_asset_paths = []
        external_prompt_pack = _normalize_external_prompt_pack(prompt_pack)
        clips, active_prompt_pack_signature, prompt_pack_imported, _prompt_pack_count_changed = (
            _sync_clips_from_prompt_pack(
                clips,
                external_prompt_pack,
                stored_prompt_pack_signature,
            )
        )
        # v14.202: 直播带货(全自动)档强制分镜上下文 —— 只保留 clip1 的上下文,
        # clip2/clip3/clip4... 一律关闭。放在资产解析与 Prompt Pack 同步之后,
        # 确保外部提示词包导入新增的 CLIP 也一并覆盖; 前端 UI 的勾选/分镜脚本
        # 里的 context_enabled 在本档下不生效(用户要求"手动设置全部无效"),
        # 避免硬切段被注入上一段尾部 39 帧后做 ≈2s 渐变, 渐变尾巴落在输出头
        # 12 帧 → 首帧重影/马赛克。
        if _ls_mode and clips:
            _forced = 0
            for _ci, _cc in enumerate(clips):
                _want = (_ci == 0)
                if bool(_cc.get("context_enabled", True)) != _want:
                    _cc["context_enabled"] = _want
                    _forced += 1
            print(f"[H3 Extender] 🛒 直播带货({_LIVESTREAM_VOICE_MODE_LABEL.get(_ls_mode, _ls_mode)})档: 上下文强制 clip1=开 / clip2+ 全关 "
                  f"(共 {len(clips)} 个 CLIP, 覆盖 {_forced} 个手动/导入的勾选)")
        owner = str(unique_id if unique_id is not None else "h3_extender")
        _register_render_ctl(owner)

        # ── v14.159 (2026-10-21): 一镜到底 × 歌曲自动分 CLIP ──────────────
        # 结合现有对口型模式的歌曲驱动逻辑(_split_lip_audio_by_clips 按 CLIP
        # 时长切音频): one_shot_mode=on 且连接 lip_audio 歌曲时, 按
        # one_shot_clip_duration(每段目标秒数) 自动把歌曲时长均分为目标 CLIP
        # 数量并自动补齐/对齐 CLIP 卡片与每段时长, 再交给现有 lip_audio 切分
        # 与一镜到底渲染链路。one_shot_clip_duration=0 时关闭自动分。
        if (one_shot_enabled
                and kwargs.get("lip_audio") is not None
                and int(one_shot_clip_duration) > 0):
            try:
                _os_audio = kwargs.get("lip_audio")
                _os_sr = int(_os_audio.get("sample_rate", 32000))
                _os_total = float(_os_audio["waveform"].shape[-1]) / float(_os_sr)
                _os_dur = float(one_shot_clip_duration)
                _os_target = max(1, int(math.ceil(_os_total / _os_dur)))
                _os_cur = len(clips)
                print(f"[H3 Extender] 🎵 一镜到底×歌曲: 歌曲 {_os_total:.1f}s ÷ 每段 {_os_dur:.0f}s "
                      f"→ 自动目标 CLIP 数 {_os_target} (原 {_os_cur})")
                if _os_cur != _os_target:
                    # 提示词模板: 第一个含提示词的 CLIP; 无则用内置一镜到底跟随模板
                    _os_tpl = None
                    for _c in clips:
                        if str(_c.get("prompt") or "").strip():
                            _os_tpl = dict(_c)
                            break
                    _os_tpl_prompt = ""
                    _os_tpl_name = ""
                    if _os_tpl is not None:
                        _os_tpl_prompt = str(_os_tpl.get("prompt") or "")
                        _os_tpl_name = str(_os_tpl.get("name") or "")
                    else:
                        _os_tpl_prompt = (
                            "镜头持续跟随主体运动，不切场、不转场、一镜到底，"
                            "主体在画面中连续完成动作，空间与时间连续，"
                            "音乐情绪与画面节奏同步。"
                        )
                    # 每段时长: 前 target-1 段 = 目标时长, 最后一段 = 歌曲剩余
                    _os_seg_dur = [_os_dur] * _os_target
                    _os_last = _os_total - _os_dur * (_os_target - 1)
                    if _os_last > 0.5:
                        _os_seg_dur[-1] = _os_last
                    _new_clips = []
                    for _i in range(_os_target):
                        if _i < _os_cur:
                            _nc = dict(clips[_i])
                        else:
                            _nc = dict(_default_clip(_i))
                            if _os_tpl is not None:
                                for _k in ("prompt", "name"):
                                    if _k in _os_tpl:
                                        _nc[_k] = _os_tpl[_k]
                            _nc["prompt"] = _os_tpl_prompt
                            _nc["name"] = (f"{_os_tpl_name}_{_i + 1}" if _os_tpl_name else f"CLIP{_i + 1}")
                        _nc["duration"] = float(_os_seg_dur[_i])
                        _nc["context_enabled"] = True
                        _new_clips.append(_nc)
                    clips = _new_clips
                    print(f"[H3 Extender] 一镜到底×歌曲: 已自动设置 {len(clips)} 个 CLIP, "
                          f"每段时长 {[round(float(c.get('duration', 0)), 1) for c in clips]}")
                else:
                    print(f"[H3 Extender] 一镜到底×歌曲: CLIP 数量已与歌曲匹配, 保持 {_os_cur} 个")
            except Exception as _os_err:
                print(f"[H3 Extender] 一镜到底×歌曲自动分CLIP失败(保持手动CLIP数): {_os_err}")
        # CLIP 自定义选择生成：None=全部；set=指定渲染范围。
        # 单选（如 2）语义：从该 CLIP 起连续渲染到结束（自动依次生成后续 CLIP），
        # 除非用户手动暂停或手动选择「合并输出」，才执行合并。多选/范围保留原「仅渲染指定段」语义。
        select_override = None
        if int(clip_select_enable):
            select_override = _parse_clip_select(clip_select, len(clips))
            # v2.62: 输入无法解析时明确告警（避免误以为已选择却静默渲染全部）
            if select_override is None and str(clip_select or "").strip().lower() not in ("", "all"):
                print(f"[H3 Extender] WARNING: clip_select='{clip_select}' 无法解析（支持 all / 1,3 / 2-5 / 3,5,7 / 7-10），已回退为渲染全部 CLIP")
            if select_override is not None and len(select_override) == 1:
                _sel_start = min(select_override)
                select_override = set(range(_sel_start, len(clips)))
            if select_override:
                _so_list = sorted(n + 1 for n in select_override)
                print(f"[H3 Extender] CLIP 选择生成: 从 {_so_list[0]} 起连续渲染 {len(select_override)} 个 CLIP {_so_list}")
        # v1.13: 仅「全量渲染且未干预」才自动合并；部分选择/重渲染/暂停均禁止自动合并
        render_partial = (
            select_override is not None
            and set(select_override) != set(range(len(clips)))
        )
        if external_prompt_pack is None:
            active_prompt_pack_signature = ""
        data_path, manifest_path, manifest = _manifest_for_extender(owner, FPS)

        # v2.72: 恢复缓存续渲染——前端「恢复缓存」按钮只复制快照文件, 无法把
        # validated 标记写进工作流 json。按钮已写 .restored_marker 标记文件,
        # 本次渲染以磁盘 manifest(快照内已渲染段 validated=True) 为准同步 clips,
        # 跳过已恢复的 CLIP 从下一个继续渲染; 消费后清除标记, 下次无标记则按
        # 正常全量流程(不改变既有语义)。
        _marker = Path(manifest_path).with_suffix(".restored_marker")
        if _marker.exists():
            try:
                _rm = _load_manifest_from_paths(data_path, manifest_path) or manifest
                _rm_segs = _rm.get("segments", []) if isinstance(_rm, dict) else []
                _synced = 0
                for _i in range(min(len(clips), len(_rm_segs))):
                    if bool(_rm_segs[_i].get("validated", False)) and not clips[_i].get("validated", False):
                        clips[_i]["validated"] = True
                        _synced += 1
                if _synced:
                    print(f"[H3 Extender] v2.72 恢复缓存续渲染: 同步 {_synced} 段 validated, "
                          f"跳过已渲染 CLIP, 从 CLIP {_synced + 1} 继续")
                else:
                    print(f"[H3 Extender] v2.72 恢复缓存续渲染: 磁盘 manifest 无已渲染段, "
                          f"本次按正常全量渲染")
                _marker.unlink(missing_ok=True)
            except Exception as _re:
                print(f"[H3 Extender] v2.72 恢复标记处理失败: {_re}")

        # v1.98: 一键恢复缓存——从最近一次自动快照恢复主链，
        # 已渲染的 CLIP 无需从 clip1 重新渲染补链；执行完成后前端自动复位开关。
        restore_cache_done = False
        if int(restore_cache):
            _rc_ok, _rc_count, _rc_kind, _rc_ts = _restore_latest_backup(data_path, manifest_path)
            if _rc_ok:
                _restored_manifest = _load_manifest_from_paths(data_path, manifest_path) or manifest
                # v1.98d: 恢复后立即分辨率预检——latent 链不能跨分辨率复用。
                # 备份分辨率 ≠ 当前渲染设置时回滚恢复并给出明确指引，
                # 避免"恢复成功 → 又被分辨率清链 → 从 clip1 补渲染"。
                _res_ok = True
                try:
                    _bk_res = _resolution_from_manifest(_restored_manifest)
                    if _bk_res is not None:
                        if str(resolution_mode or "") == "manual":
                            _tgt_w, _tgt_h = _manual_effective_resolution(width, height)
                            _tgt_res = {"width": _tgt_w, "height": _tgt_h}
                        else:
                            _tgt_res = _resolve_generation_resolution(
                                resolution_mode, megapixels, width, height, kwargs.get("refs") or []
                            )
                        # v2.71 fix: 链存的是「放大后 latent」（一采 960x544 latent 60x34
                        # 经 refine ×2.0 -> 120x68），备份"像素"不能用 geometry×16(=1920x1088)
                        # 与当前一采设置直接比（旧逻辑在 960x544 一采下永远不匹配，
                        # 恢复必被取消）。改为 latent 几何语义比较：
                        #   备份 latent(w/h) vs 当前一采 latent(÷16) × refine 倍率。
                        _bk_geom = _restored_manifest.get("geometry") if isinstance(_restored_manifest, dict) else None
                        _bk_lw = int(_bk_geom.get("video_w", 0)) if isinstance(_bk_geom, dict) else 0
                        _bk_lh = int(_bk_geom.get("video_h", 0)) if isinstance(_bk_geom, dict) else 0
                        _res_mismatch = False
                        if _bk_lw > 0 and _bk_lh > 0:
                            _rfu_rc = float(refine_upscale_factor) if bool(refine_enable) else 1.0
                            _tgt_lw = max(1, int(_tgt_res["width"] // 16))
                            _tgt_lh = max(1, int(_tgt_res["height"] // 16))
                            _res_mismatch = (
                                int(_bk_lw) != int(round(_tgt_lw * _rfu_rc))
                                or int(_bk_lh) != int(round(_tgt_lh * _rfu_rc))
                            )
                        else:
                            _res_mismatch = (
                                int(_bk_res["width"]) != int(_tgt_res["width"])
                                or int(_bk_res["height"]) != int(_tgt_res["height"])
                            )
                        if _res_mismatch:
                            _res_ok = False
                            _rb_ok, _rb_count, _rb_kind, _rb_ts = _restore_latest_backup(data_path, manifest_path)
                            print(f"[H3 Extender] v1.98d 恢复缓存已取消: 备份 latent {_bk_lw}x{_bk_lh} "
                                  f"≠ 当前设置 {_tgt_res['width']}x{_tgt_res['height']}（latent "
                                  f"{_tgt_lw}x{_tgt_lh} × refine {_rfu_rc:.1f} = "
                                  f"{int(round(_tgt_lw * _rfu_rc))}x{int(round(_tgt_lh * _rfu_rc))}），"
                                  f"几何不同无法复用 latent 链。"
                                  f"请把分辨率参数改回一采 {_bk_lw // 2 * 16}x{_bk_lh // 2 * 16}（latent 与备份一致）后重新运行；"
                                  f"或确认使用新分辨率后正常渲染（将重新生成全部缓存）。"
                                  f"{'已回滚恢复前状态' if _rb_ok else '回滚失败，请手动检查主链缓存'}")
                except Exception as _e:
                    print(f"[H3 Extender] v1.98d 恢复缓存分辨率预检跳过: {_e}")
                if _res_ok:
                    manifest = _restored_manifest
                    for _i, _cfg in enumerate(clips):
                        if _i < _rc_count:
                            _cfg["validated"] = True
                    restore_cache_done = True
                    print(f"[H3 Extender] v1.98 恢复缓存: {_rc_count} 段已恢复({_rc_kind} {_rc_ts})，"
                          f"已标记为已渲染，不再从 clip1 补链，仅渲染新增 CLIP")
            else:
                print("[H3 Extender] v1.98 恢复缓存: 无可用备份，本次按正常流程渲染")

        # If cards were removed, trim the physical cache immediately.
        if len(manifest.get("segments", [])) > len(clips):
            print(f"[H3 Extender] v1.97 卡片数减少({len(manifest.get('segments', []))} -> {len(clips)}), 修剪尾部缓存段")
            manifest = _truncate_chain(
                data_path, manifest_path, manifest, len(clips),
                reason=f"cards_removed {len(manifest.get('segments', []))}->{len(clips)}",
            )

        # Clear stale tail latents before a full render pass.
        # Tail latents are only valid between a "per-clip replace" operation
        # and the next "合并输出 / Merge Output" click.  Any other execution
        # path (full re-render, storyboard edit, prompt change, etc.) means
        # the tail latents on disk are stale and must be discarded — otherwise
        # the auto-merge_output guard can trigger and skip the entire render,
        # producing a merged video from the old cached content.
        if not merge_output and _has_tail_latents_on_disk(owner):
            any_replace = any(c.get("replace_mode", False) for c in clips)
            if not any_replace:
                _delete_tail_latents_from_disk(owner)
                print(f"[H3 Extender] Cleared stale tail latents before full re-render "
                      f"(clips={len(clips)})")
            else:
                # In per-clip replace mode, still clear tail if clip count
                # changed since the tail was saved.
                cached_seg_count = len(manifest.get("segments", []))
                if cached_seg_count != len(clips):
                    _delete_tail_latents_from_disk(owner)
                    print(f"[H3 Extender] Cleared stale tail latents "
                          f"(clips={len(clips)}, cache={cached_seg_count})")

        segments = manifest.get("segments", [])

        # A TRUE toggle can only validate a clip that actually exists on disk.
        # This also protects old workflow JSON with stale downstream TRUE values.
        if len(segments) < len(clips):
            for i in range(len(segments), len(clips)):
                if clips[i]["validated"]:
                    for j in range(i, len(clips)):
                        clips[j]["validated"] = False
                    break

        refs = _parse_refs_json(refs_json)

        # Load asset library images as reference tensors. When @图N tags are
        # used, the asset images replace the internal refs list entirely so
        # that <Picture N> tags in prompts match the ref slot numbers.
        clip_ref_plans = None
        if resolved_img_paths:
            print(f"[H3 Extender] Loading {len(resolved_img_paths)} asset images as ref tensors")
            asset_tensors = []
            for img_path in resolved_img_paths:
                try:
                    with Image.open(img_path) as image:
                        image = ImageOps.exif_transpose(image).convert("RGB")
                        array = np.asarray(image, dtype=np.float32) / 255.0
                    tensor = torch.from_numpy(np.ascontiguousarray(array)).unsqueeze(0)
                    asset_tensors.append(tensor)
                    print(f"[H3 Extender]   loaded asset image: {img_path} -> shape {tuple(tensor.shape)}")
                except Exception as _e:
                    print(f"[H3 Extender] FAILED to load asset image {img_path}: {_e}")

            if asset_tensors:
                refs = asset_tensors[:MAX_IMAGE_REFS]
                refs += [None] * (MAX_IMAGE_REFS - len(refs))
                print(f"[H3 Extender] refs replaced with {len(asset_tensors)} asset tensors (padded to {len(refs)} slots)")

                # Per-CLIP reference planning: each CLIP renders with ONLY the
                # assets its own prompt (plus the global prompt) references.
                # Other CLIPs' scene assets never leak into this shot, fixing
                # scene mixing when a CLIP references just one scene image.
                # <Picture N> tags are renumbered compactly 1..k
                # (k <= MAX_IMAGE_REFS) and both the CLIP prompt and the global
                # prompt are rewritten accordingly, so a <Picture 38> scene
                # reference still occupies a slot even when many global role
                # refs were resolved before it. Own-CLIP refs take priority
                # over global refs when the total exceeds the model's slot cap.
                _pic_re = re.compile(r'<Picture\s+(\d+)>', re.IGNORECASE)
                _gp_text = str(global_prompt or "")

                def _collect_pic_nums(text):
                    seen = []
                    for _m in _pic_re.finditer(str(text)):
                        _n = int(_m.group(1))
                        if _n not in seen and 1 <= _n <= len(asset_tensors):
                            seen.append(_n)
                    return seen

                def _remap_prompt_text(text, old_to_new):
                    def _sub(_m):
                        _n = int(_m.group(1))
                        if _n in old_to_new:
                            return f"<Picture {old_to_new[_n]}>"
                        # Refs beyond the slot cap are dropped entirely (tag
                        # removed, surrounding text kept). Leaving the original
                        # number would collide with a remapped tag and make the
                        # model reference the wrong asset.
                        return ""
                    return _pic_re.sub(_sub, str(text))

                _gp_nums = _collect_pic_nums(_gp_text)
                clip_ref_plans = []
                for _ci, _clip in enumerate(clips):
                    _clip_nums = _collect_pic_nums(_clip.get("prompt", ""))
                    # v14.351: Viggle 档最常踩的坑 —— 用户把 @图1 写在**全局提示词**里，
                    # strict per-clip 隔离把它排除，日志出现 "0 assets / no ref_blocks"，
                    # 参考图根本没进 conditioning（换脸不彻底的真凶之一）。
                    if (not _clip_nums) and _gp_nums and _rp_mode in _VIGGLE_RP_LABELS:
                        _clip_nums = list(_gp_nums)
                        print(f"[H3 Extender] clip[{_ci}] v14.351 分镜无 @图N，"
                              f"继承全局参考图 {_clip_nums}", flush=True)
                    _ordered = _clip_nums[:MAX_IMAGE_REFS]
                    _o2n = {_old: _idx + 1 for _idx, _old in enumerate(_ordered)}
                    _slot_refs = [None] * MAX_IMAGE_REFS
                    for _idx, _old in enumerate(_ordered):
                        _slot_refs[_idx] = asset_tensors[_old - 1]
                    clip_ref_plans.append(
                        {
                            "refs": _slot_refs,
                            "clip_prompt": _remap_prompt_text(_clip.get("prompt", ""), _o2n),
                            # Strict per-CLIP isolation: the global prompt NEVER
                            # injects picture refs into a CLIP. Only the CLIP's
                            # own @图N tags drive its reference images, so assets
                            # mentioned only in the global prompt (other scenes,
                            # other characters) never appear in this shot.
                            "global_prompt": _remap_prompt_text(_gp_text, {}),
                        }
                    )
                    print(
                        f"[H3 Extender] clip[{_ci}] ref plan: {len(_ordered)} assets "
                        f"(strict per-clip, global refs excluded), "
                        f"slots={[i + 1 for i, r in enumerate(_slot_refs) if r is not None]}"
                    )
            else:
                print("[H3 Extender] WARNING: resolved_img_paths was non-empty but no tensors were loaded!")
        else:
            print(f"[H3 Extender] no resolved_img_paths, using UI refs: {sum(1 for r in refs if r is not None)} active")

        # Set ref_audio from asset library if audio refs were resolved.
        # 若 lip_audio 已连接，则忽略 @音频N——对口型模式下 lip_audio 是唯一音频源。
        if resolved_aud_paths and not kwargs.get("ref_audio") and not kwargs.get("lip_audio"):
            kwargs["ref_audio"] = resolved_aud_paths[0]

        refs_signature = _refs_signature(refs)
        requested_resolution = _resolve_generation_resolution(
            resolution_mode,
            megapixels,
            width,
            height,
            refs,
        )

        # v14.238 MiniMaxH3 Director 极速双采移植 —— 分辨率接管。
        # 参考插件语义: Director 节点画布 = 一采低清(864x480 @0.4MP), Refine
        # 节点决定最终画布(1920x1088 @2MP), 两者互相独立。这里把用户目标画布
        # (width/height/megapixels 解析结果)仅用作构图参考: 一采画布由
        # director_fast_first_mp 接管(低清草稿), 二采 latent 放大因子按
        # director_fast_target_mp 自动换算(像素比 + 32px 对齐, 选面积误差
        # 最小的轴向因子), 最终输出 ≈ 目标 MP 且保持用户横竖构图。
        if _director_fast_active:
            try:
                _df_ref_w = int(requested_resolution.get("width") or 0)
                _df_ref_h = int(requested_resolution.get("height") or 0)
            except (TypeError, ValueError):
                _df_ref_w, _df_ref_h = 0, 0
            _df_fw, _df_fh = _ff_director_canvas(_dff_first_mp, _df_ref_w, _df_ref_h)
            _df_tw, _df_th = _ff_director_canvas(_dff_target_mp, _df_ref_w, _df_ref_h)
            _df_best = _ff_director_refine_factor(_df_fw, _df_fh, _df_tw, _df_th, int(refine_align_to))
            _df_factor = float(_df_best[1])
            requested_resolution = {
                "width": _df_fw,
                "height": _df_fh,
                "mode": "director_fast_lowres",
                "guide_ref": None,
                "guide_src_width": 0,
                "guide_src_height": 0,
                "fallback": False,
                "megapixels": float(_dff_first_mp),
            }
            refine_upscale_factor = _df_factor
            print(f"[H3 Extender] v14.238 Director极速双采分辨率: 用户目标画布 "
                  f"{_df_ref_w}x{_df_ref_h} -> 一采低清 {_df_fw}x{_df_fh} "
                  f"({_dff_first_mp}MP) + 二采 latent x{_df_factor:.3f} -> 目标 "
                  f"{_df_tw}x{_df_th} ({_dff_target_mp}MP, 对齐后实际 "
                  f"~{int(_df_best[2]) * 16}x{int(_df_best[3]) * 16}); "
                  f"外接 refine_sigmas 可覆盖 beta 3步/起点 σ 0.45~0.55 调度")

        cache_resolution = _resolution_from_manifest(manifest)
        cache_has_segments = bool(segments) and cache_resolution is not None

        # Resolution is a live generation setting again. Auto/MP or Manual
        # width/height may be changed at any time, exactly like the old external
        # Scale Image -> Get Image Size workflow. A latent chain cannot mix two
        # geometries, so when the requested size changes we restart only the
        # generated cache while preserving every card/prompt/seed/config.
        #
        # A .ext Load is handled in the frontend by putting the exact archived
        # cache width/height into Manual mode. Therefore the imported project
        # continues at its stored geometry until the user explicitly changes the
        # resolution controls afterwards.
        resolution = dict(requested_resolution)
        resolution["requested_width"] = int(requested_resolution["width"])
        resolution["requested_height"] = int(requested_resolution["height"])
        resolution["cache_reset"] = False

        resolved_width = int(resolution["width"])
        resolved_height = int(resolution["height"])

        # v14.171 (2026-10-22): Omni 单采一采钳制到 latent token 健康区。
        # 实测: 一采 1376x768 → latent(172,96,107) ≈ 177万 tokens, Sol-Attn 降级
        # dense 后 24GB 卡 attention 峰值 OOM (3/8 步崩溃, 叠加 lip_audio 音频注入
        # 峰值更高)。Omni 无二采, 直出高分辨率的代价是 attention 峰值爆炸;
        # 正确做法: 一采钳制 ≤ 960x544 (873,120 tokens, 与 v14.164 二采分块健康区
        # 同源), 最终高清由用户侧 upscale_final 超分链兜底 (保真放大, 无二采伪影)。
        if omni_8step_mode:
            _omni_max_px = 960 * 544  # Omni 一采健康像素上限
            _area = resolved_width * resolved_height
            if _area > _omni_max_px:
                _s = (_omni_max_px / float(_area)) ** 0.5
                _nw = max(32, int(round(resolved_width * _s / 32)) * 32)
                _nh = max(32, int(round(resolved_height * _s / 32)) * 32)
                # 等比取整后可能仍略超上限, 逐档 32px 收紧到像素上限内
                while _nw > 32 and _nh > 32 and _nw * _nh > _omni_max_px:
                    if _nw > _nh:
                        _nw -= 32
                    else:
                        _nh -= 32
                print(f"[H3 Extender] v14.171 Omni 一采钳制: {resolved_width}x{resolved_height} "
                      f"({_area/1e6:.2f}MP, latent {int(resolved_width/8)*int(resolved_height/8)*107:,} tokens)"
                      f" -> {_nw}x{_nh} (latent {int(_nw/8)*int(_nh/8)*107:,} tokens, 24GB 健康区; "
                      f"高清由 upscale_final 超分兜底)")
                resolved_width, resolved_height = _nw, _nh
                resolution["width"] = _nw
                resolution["height"] = _nh
                resolution["requested_width"] = _nw
                resolution["requested_height"] = _nh
            elif _area < _omni_max_px:
                # v14.212 (fix): 保底判据由"单边"改为"面积" —— 旧逻辑 (宽<960 或 高<544)
                # 会把竖版 544x960 (面积 522,240 本已 = 健康区上限 960x544) 误判为"太小",
                # 按宽度凑到 960 后高度等比跟到 1696 -> 960x1696 (1.63MP, ~2.7M tokens),
                # 一采每步 350s。改按面积等比放大: 面积达标即不动, 仅真正偏小的才提到健康区。
                _s = (_omni_max_px / float(_area or 1)) ** 0.5
                _nw = max(32, int(round(resolved_width * _s / 32)) * 32)
                _nh = max(32, int(round(resolved_height * _s / 32)) * 32)
                while _nw > 32 and _nh > 32 and _nw * _nh > _omni_max_px:
                    if _nw > _nh:
                        _nw -= 32
                    else:
                        _nh -= 32
                print(f"[H3 Extender] v14.212 Omni 一采保底: {resolved_width}x{resolved_height} "
                      f"({_area/1e6:.2f}MP) -> {_nw}x{_nh} (官方健康区 {_omni_max_px/1e6:.2f}MP, 直出更清晰)")
                resolved_width, resolved_height = _nw, _nh
                resolution["width"] = _nw
                resolution["height"] = _nh
                resolution["requested_width"] = _nw
                resolution["requested_height"] = _nh

        # v14.157: 声明的最终输出尺寸必须尽早落盘。
        # 逐段 MP4 解码靠 manifest 里的 output_width/height 才会把"二采被
        # 显存预算降级"的段重采样回声明像素；旧实现只在本函数收尾前写这两个
        # 键，续跑/恢复出来的链常常拿不到，于是成片停在 1440x800 而不是
        # 声明的 1920x1088（人脸直接糊掉）。这里在渲染开始前就写一次。
        # v14.276 (干净优先): 2K 不再可行 —— 二采放大到 2560 宽时 tokens 到 709,920,
        # Sol-Attn 稀疏在该规模病态, 单次调用装不进 24GB, 只能退化成时间分块(每段
        # 独立加噪/独立 seed, 切点也不落在 5-token 帧组相位上), 实机就是全程闪烁 +
        # 满屏碎花纹理。改为按「单次调用 token 预算」向下取倍率: 整段一次采样, 无
        # 接缝、无分块噪声, 960x544 一采约 x1.39 -> latent 46x82 = 1312x736。
        # 预算只与倍率平方相关(T·H_lat·W_lat), 这里按最长 clip 的 latent T 估算。
        _os2k_decl_px = None
        # v14.346/v14.374: 本次二采是否"没有任何几何放大"(倍率被预算压成 x1.0x 的假倍率)。
        # 为 True 时二采整段跳过 —— 详见下方预算分支里的说明。
        _os2k_skip_refine = False
        if one_shot_dual_2k:
            try:
                # v14.278: 350k 预算把二采推到 1312x736 / 328,164 tokens(健康上限 130k 的
                # 2.5 倍)。实机出片: 满屏细织纹网格、亮白晕斑、细节被抹平, 且单角色被
                # 复制成两个人 —— 都是采样规模外推的典型症状。分辨率改由像素域超分
                # (realesr, 见 upscale_final)承担, 二采回到一采同规模(960x544/177k)。
                _os2k_budget = 180000
                _os2k_t = 0
                for _c2k in clips or []:
                    try:
                        _d2k = float(_c2k.get("duration", 5.0))
                    except (TypeError, ValueError):
                        _d2k = 5.0
                    _os2k_t = max(_os2k_t, _video_latent_t(_duration_to_frames(_d2k)))
                _os2k_t = max(1, _os2k_t)
                refine_upscale_factor = _ff_refine_factor_for_budget(
                    resolved_width, resolved_height, _os2k_t, _os2k_budget, refine_align_to)
                _os2k_nh = _ff_snap_to_multiple(
                    round(int(resolved_height) // 16 * float(refine_upscale_factor)),
                    max(1, int(refine_align_to) // 16))
                _os2k_nw = _ff_snap_to_multiple(
                    round(int(resolved_width) // 16 * float(refine_upscale_factor)),
                    max(1, int(refine_align_to) // 16))
                print(f"[H3 Extender] v14.276 一镜到底·2K双采(干净优先): 一采 "
                      f"{resolved_width}x{resolved_height} -> 二采 latent x{float(refine_upscale_factor):.2f} = "
                      f"{_os2k_nw * 16}x{_os2k_nh * 16} "
                      f"({_os2k_t}x{_os2k_nh}x{_os2k_nw}={_os2k_t * _os2k_nh * _os2k_nw:,} tokens <= 预算 "
                      f"{_os2k_budget:,}), 整段一次采样(不分块, 无接缝/无碎纹)")
                _os2k_decl_px = (int(_os2k_nw * 16), int(_os2k_nh * 16))
                # v14.346 (2026-11-10 fix): 假倍率必须视为「没有二采」。
                # 预算 180,000 在 12s 一镜到底(87 latent 帧)下只允许 x1.02, 而
                # align=40px 取整后 latent 仍是 34x60 —— 与一采完全相同。这条"二采"
                # 于是不含任何放大, 只是把一采 latent 重新加噪到 0.35 再用 **4 步**
                # 去噪一遍。两个后果都是掉画质:
                #   ① 底模是 8 步蒸馏(turbo_8step), 4 步是离轨采样, 出来的是
                #      单元级(16px)花纹而不是细节;
                #   ② 本插件 tooltip 已写明 denoise<=0.45 的重绘"基本只是把画面抹平"
                #      —— 一采 8 步的锐度被这条 4 步重绘抹掉。
                # 实机产物 h3_clip_250_1_1794296265.mp4(960x544) 全片 16px 网格,
                # 3.79-5.46s Laplacian 方差 0.00057~0.00066(中位 0.00088, 掉 35-50%),
                # 就是这条无效二采留下的; 它还白烧 6.4 分钟/段(47.7->200.1s/步)。
                # 处理: 几何未变就不跑二采, 直接输出一采 8 步画面; 并把原因播报出去,
                # 不再让"2K双采"这个名字骗人(实际输出=一采尺寸)。
                _os2k_base_hw = (max(1, int(resolved_height) // 16),
                                 max(1, int(resolved_width) // 16))
                if (int(_os2k_nh), int(_os2k_nw)) == _os2k_base_hw:
                    _os2k_skip_refine = True
                    print(f"[H3 Extender] ⚠️ v14.346 一镜到底·2K双采: 预算把二采倍率压到 "
                          f"x{float(refine_upscale_factor):.2f}, 按 align={int(refine_align_to)}px 取整后几何与一采"
                          f"完全相同(latent {_os2k_base_hw[1]}x{_os2k_base_hw[0]} = "
                          f"{resolved_width}x{resolved_height}) —— 本次二采没有任何放大, 只会在同分辨率上"
                          f"用 {int(refine_steps)} 步 denoise {float(refine_denoise):.2f} 重绘一遍(抹平一采锐度), "
                          f"已整段跳过二采, 输出 = 一采 {int(steps)} 步画面")
                    print(f"[H3 Extender] ℹ️ v14.346 要真正的 2K: ①开 upscale_final(realesr 像素超分, "
                          f"当前工作流是关的); ②或把每段时长压到 8s 以内(87->57 latent 帧, tokens 177,480->"
                          f"116,340)后再开 latent 放大; ③12s 段 + latent x2.0 = 709,920 tokens, 24GB 卡必换页"
                          f"且满屏碎纹(CHANGELOG v14.276/v14.278 已实测)")
            except Exception as _os2k_err:
                print(f"[H3 Extender] v14.276 一镜到底·2K双采: 倍率换算失败, 回退 x1.5 ({_os2k_err})")
                refine_upscale_factor = 1.5
        try:
            _decl_out_f = max(1.0, float(refine_upscale_factor)) if bool(refine_enable) else 1.0
            # v14.182: 双采2K 档声明输出尺寸计入 HyperVAE 2x 像素翻倍 (latent
            # factor=1.0 不放大, 但解码输出 = 一采像素 × 2)。
            _decl_out_f = _decl_out_f * float(_hv2x_decl)
            manifest["first_pass_width"] = int(resolved_width)
            manifest["first_pass_height"] = int(resolved_height)
            manifest["declared_refine_factor"] = float(_decl_out_f)
            # v14.279: 声明尺寸必须在 latent 空间按 align 取整并取偶, 直接
            # round(像素×倍率) 会得到 979x555 这类奇数 -> yuv420p 编码失败。
            _decl_w279, _decl_h279 = _ff_declared_output_px(
                resolved_width, resolved_height,
                (float(refine_upscale_factor) if bool(refine_enable) else 1.0),
                _hv2x_decl, refine_align_to)
            manifest["output_width"] = int(_decl_w279)
            manifest["output_height"] = int(_decl_h279)
            # v14.276: 单次采样档的声明像素取二采实际几何(按 align 取整后的 latent),
            # 与倍率名义值差 1~2%, 直接用实际值避免成片再被重采样一次。
            if _os2k_decl_px is not None:
                manifest["output_width"], manifest["output_height"] = _os2k_decl_px
            _write_json_atomic(manifest_path, manifest)
            print(f"[H3 Extender] v14.157 声明输出尺寸: 一采 {resolved_width}x{resolved_height} "
                  f"× 二采 x{_decl_out_f:.1f} -> "
                  f"{manifest['output_width']}x{manifest['output_height']}")
        except Exception as _dow:
            print(f"[H3 Extender] v14.157 声明输出尺寸写入失败(可忽略): {_dow}")

        # v1.98: 渲染前分辨率诊断——断点被清时先看这里, 一眼定位清空原因
        _diag_geom = manifest.get("geometry")
        _diag_cache = cache_resolution or {}
        print(
            f"[H3 Extender] v1.98 分辨率诊断: mode={resolution_mode} mp={megapixels} "
            f"manual=({width}x{height}) guide_idx={requested_resolution.get('guide_ref')} "
            f"guide_dim=({requested_resolution.get('guide_src_width')}x{requested_resolution.get('guide_src_height')}) "
            f"guide_fallback={requested_resolution.get('fallback')} "
            f"requested={resolved_width}x{resolved_height} "
            f"cache_segments={len(segments)} cache_geom={_diag_geom} "
            f"cache_res={int(_diag_cache.get('width', 0) or 0)}x{int(_diag_cache.get('height', 0) or 0)} "
            f"cache_has_segments={cache_has_segments}"
        )

        # v2.70 fix: 双采工作流中链以「放大后 latent」为几何基准（一采 960x544
        # latent 34x60 经 refine ×2.0 -> 68x120 入链），而 requested 是「一采
        # 像素」。旧逻辑用 geometry×16(=1920x1088) 与 requested(960x544) 直接
        # 比较，链上一有段就误判"分辨率变化"而清链。这里改用 latent 几何
        # 对比：cache geometry(video_w/h) vs 一采 latent(÷16) × refine 倍率。
        _rfu = float(refine_upscale_factor) if bool(refine_enable) else 1.0
        # v14.331（2026-11-07）：一镜到底·单采无缝档实际不跑二采（refine 被跳过，
        # 见 v14.185），链几何就是一采 latent。旧逻辑仍按「声明 refine 倍率」比较
        # (34×2.0=68 vs 链上实测 60)，于是每次启动都误判“分辨率变化”并把整条链清空
        # ——日志里明明写着 960x544 -> 960x544，刚恢复的 238MB 快照照样作废，
        # 断点续渲被毁、19 段只得从 clip1 重来。此处把实际不生效的二采倍率折返为 1.0。
        if bool(refine_enable) and bool(one_shot_enabled) and bool(one_shot_single_pass):
            _rfu = 1.0
        _req_lw = max(1, int(resolved_width // 16))
        _req_lh = max(1, int(resolved_height // 16))
        _cg_geom = manifest.get("geometry") if isinstance(manifest, dict) else None
        _cg_lw = int(_cg_geom.get("video_w", 0)) if isinstance(_cg_geom, dict) else 0
        _cg_lh = int(_cg_geom.get("video_h", 0)) if isinstance(_cg_geom, dict) else 0
        # v14.156: 显存预算不足时二采倍率会被静默降级 x2.0 -> x1.5（见 v1.74
        # 预算预检），此时链几何固定为 1.5x。若仍按声明 2.0 比较，每次执行都会
        # 误判"分辨率变化"而清链，用户被迫从 clip1 重跑。这里对唯一一种预算
        # 降级组合（声明 2.0 / 实际 1.5）做精确放行；像素尺寸由解码时的
        # output_width/height 重采样兜底，因此成片尺寸不受影响。
        _cg_implied = (float(_cg_lw) / float(_req_lw)) if _req_lw else 0.0
        _budget_degraded = bool(
            abs(_rfu - 2.0) <= 0.01
            and abs(_cg_implied - 1.5) <= 0.02
            and _req_lh > 0
            and abs(float(_cg_lh) / float(_req_lh) - _cg_implied) <= 0.02
        )
        if _budget_degraded:
            print(f"[H3 Extender] v14.156 链几何匹配显存预算降级结果（声明 x{_rfu:.2f} / "
                  f"实际 x{_cg_implied:.2f}），保留缓存继续续跑；成片将重采样到声明尺寸")
        requested_mismatch = bool(
            cache_has_segments
            and _cg_lw > 0
            and _cg_lh > 0
            and not _budget_degraded
            and (
                int(_cg_lw) != int(round(_req_lw * _rfu))
                or int(_cg_lh) != int(round(_req_lh * _rfu))
            )
        )
        previous_cache_resolution = dict(cache_resolution) if requested_mismatch else None

        if requested_mismatch:
            # Resolution is the one unavoidable global invalidation: latent
            # geometry cannot be mixed inside one sequential disk chain.
            _old_r = cache_resolution or {}
            print(
                f"[H3 Extender] v1.97 分辨率变化, 链已清空(旧 {int(_old_r.get('width',0))}x{int(_old_r.get('height',0))} "
                f"-> 新 {resolved_width}x{resolved_height}); 若这是误操作请恢复参数后从备份恢复链"
            )
            manifest = _truncate_chain(
                data_path, manifest_path, manifest, 0,
                reason=f"resolution {int(_old_r.get('width',0))}x{int(_old_r.get('height',0))}->{resolved_width}x{resolved_height}",
            )
            segments = []
            cache_resolution = None
            cache_has_segments = False
            resolution["cache_reset"] = True
            for cfg in clips:
                cfg["validated"] = False
            try:
                preview_path = _decoded_preview_cache_path(data_path)
                if preview_path.exists():
                    preview_path.unlink()
            except Exception:
                pass

        if prompt_pack_imported and external_prompt_pack is not None:
            imported_json = _state_json(clips, active_prompt_pack_signature)
            _send_extender_prompt_pack_import(
                owner,
                imported_json,
                len(external_prompt_pack.get("prompts") or []),
                external_prompt_pack.get("source") or "External prompt pack",
            )

        # v1.99: per-clip 资产指纹失效——只重渲引用变化图的 clip。
        # asset_refs_key 是全库路径 hash(顺序敏感), 用户改一张图/加一张图就变;
        # 全库失效 = 改一个角色/场景就全重跑, 不可接受。改为: 每个 clip 记录其
        # 依赖图的(路径+mtime+size)指纹, 只有指纹变化的 clip 标未验证, 其余
        # 完全保留缓存; 全局参考图变化则全部 clip 标未验证(整体风格变了)。
        asset_refs_key = ""
        if resolved_img_paths:
            asset_refs_key = hashlib.sha256(
                "|".join(resolved_img_paths).encode("utf-8")
            ).hexdigest()

        manifest = _load_manifest_from_paths(data_path, manifest_path) or manifest
        manifest = dict(manifest)
        prev_clip_fps = manifest.get("clip_asset_fps") or []
        prev_global_fp = manifest.get("global_asset_fp", "")
        clip_asset_fps = [_clip_asset_fp(ps) for ps in clip_asset_paths]
        global_asset_fp = _clip_asset_fp(global_asset_paths)

        # prompt pack 导入/内容变化 -> 提示词已变, 指纹基准可能错位, 全部标未验证
        if prompt_pack_imported:
            print("[H3 Extender] v1.99 prompt pack 导入/内容变化 -> 全部 clip 标未验证(提示词已变)")
            for cfg in clips:
                cfg["validated"] = False

        # 旧版本链无指纹基准时不触发失效(升级不打扰); 基准在渲染完成后写入
        if prev_clip_fps and clip_asset_fps:
            _chg_global = bool(global_asset_fp) and bool(prev_global_fp) and global_asset_fp != prev_global_fp
            if _chg_global:
                print(f"[H3 Extender] v1.99 全局参考图变化 -> 全部 clip 标未验证(整体风格变了)")
                for cfg in clips:
                    cfg["validated"] = False
            else:
                _chg_clips = [
                    i for i, fp in enumerate(clip_asset_fps)
                    if fp and (i >= len(prev_clip_fps) or prev_clip_fps[i] != fp)
                ]
                if _chg_clips:
                    print(f"[H3 Extender] v1.99 资产变化: {len(_chg_clips)} 个 clip 引用的图变了 -> 仅重渲 clip {[i + 1 for i in _chg_clips]}")
                    for i in _chg_clips:
                        clips[i]["validated"] = False
                        print(f"   clip {i + 1} 当前依赖图: {clip_asset_paths[i]}")
                else:
                    print(f"[H3 Extender] v1.99 资产指纹稳定: {len(clips)} 个 clip 全部保留缓存")
        elif clip_asset_fps:
            print(f"[H3 Extender] v1.99 首次建立 per-clip 资产指纹基准({len(clip_asset_fps)} 个 clip)")

        manifest["asset_refs_key"] = asset_refs_key
        # v1.100: 持久化 per-clip/global 资产路径与全局提示词——刷新/另存后
        # 前端可从 cache_state 恢复资产链接显示, 无需重新输入全局提示词。
        try:
            manifest["clip_asset_paths"] = [list(ps) for ps in clip_asset_paths]
            manifest["global_asset_paths"] = list(global_asset_paths)
            manifest["global_prompt"] = str(global_prompt or "")
        except Exception:
            pass
        manifest["extender_refs_signature"] = refs_signature
        manifest["extender_ref_ids"] = [
            ref.get("id") if isinstance(ref, dict) else None for ref in refs
        ]
        # v14.156: 记录工作流声明的最终输出尺寸（一采像素 × 声明二采倍率）。
        # 二采倍率可能被显存预算静默降级（x2.0 -> x1.5），解码时按此尺寸精确
        # 重采样，保证 per-clip 与 merged 成片像素与工作流声明一致。
        try:
            _decl_f = max(1.0, float(refine_upscale_factor)) if bool(refine_enable) else 1.0
            # v14.182: 双采2K 档计入 HyperVAE 2x 像素翻倍
            _decl_f = _decl_f * float(_hv2x_decl)
            # v14.279: 与上方声明尺寸保持同一口径(latent 取整 + 偶数), 且单次
            # 采样档直接复用本轮算好的实际几何 —— 旧代码在这里用
            # round(960×1.02)=979x555 覆盖了上面的正确值, 导致 mp4 编码失败。
            _decl_w279, _decl_h279 = _ff_declared_output_px(
                resolved_width, resolved_height,
                (float(refine_upscale_factor) if bool(refine_enable) else 1.0),
                _hv2x_decl, refine_align_to)
            if _os2k_decl_px is not None:
                _decl_w279, _decl_h279 = _os2k_decl_px
            manifest["output_width"] = int(_decl_w279)
            manifest["output_height"] = int(_decl_h279)
            manifest["declared_refine_factor"] = float(_decl_f)
        except Exception:
            pass
        manifest["updated_at"] = time.time()
        _write_json_atomic(manifest_path, manifest)

        resolution_mismatch = False

        audio_vae = kwargs.get("audio_vae")
        ref_audio = kwargs.get("ref_audio")
        lip_audio = kwargs.get("lip_audio")
        # v14.174: lip_voice 升级为对口型驱动音频（与 lip_audio 同语义, 且优先）。
        # 用户把 IndexTTS 合成台词音频接入 lip_voice 时, 同样要求:
        #   1) 取消模型自己生成音频  2) 直接用 lip_voice 外部音频驱动对口型。
        # 实现: lip_voice 非 None 时重赋值 lip_audio → 下方切段/AV latent注入/
        # 提示词净化/音频锁定/输出混音替换全链路自动复用, 无需复制代码。
        _lip_voice = kwargs.get("lip_voice")
        # ── v14.336 视频替换档: 外部音频驱动口型（lip_audio / lip_voice）与本档
        #    "锁定源视频原声"互斥，必须在这里（两个变量都已绑定、下方 LipSync
        #    分镜按时长重排/音频预分割之前）一起剔除。
        # 实测教训：1 个 15s 分镜 + 225s lip_audio → LipSync 先把分镜扩成
        # 15.08s + 209.77s 两段，替换档再建计划（时间轴对不上，找不到源画面），
        # 209.77s 单段 = 5088 帧 → H3 一采 OOM。
        if ((_rp_mode == "视频替换 (V2V 人物替换)"
             or (_rp_mode == "视频角色替换+动作迁移" and _remix_lock_audio()))
                and (lip_audio is not None or _lip_voice is not None)):
            print(f"[{'H3 Remix' if _rp_mode != '视频替换 (V2V 人物替换)' else 'H3 Recast'}] "
                  "⚠️ 本档锁定源视频原声，已剔除 "
                  f"{'lip_audio' if lip_audio is not None else ''}"
                  f"{'、' if lip_audio is not None and _lip_voice is not None else ''}"
                  f"{'lip_voice' if _lip_voice is not None else ''} 对口型输入 —— "
                  "口型随源片逐帧对齐，不再另灌外部音频"
                  "（外部长音频会强行把分镜拉成 200s 级长段，单段超 15s 必爆显存）")
            lip_audio = None
            _lip_voice = None
        # v14.270: lip_audio 最高优先级（全渲染模型/全渲染管道通用，凌驾 01/02/03 档）。
        # 一旦 lip_audio 端口接入有效音源 → 自动屏蔽 ref_audio/lip_voice，
        # 不管这两个端口是否接入音源或处于连接状态，一律忽略。
        if lip_audio is not None:
            if ref_audio is not None or _lip_voice is not None:
                print(f"[H3 LipSync] lip_audio 已连接(最高优先级) → 自动忽略 "
                      f"{'ref_audio' if ref_audio is not None else ''}"
                      f"{'/' if ref_audio is not None and _lip_voice is not None else ''}"
                      f"{'lip_voice' if _lip_voice is not None else ''}, "
                      f"声音与口型完全由 lip_audio 提供")
            ref_audio = None
            _lip_voice = None
        # v14.220 直播带货配音模式音频接线强制（01/02/03 一键切换）。
        # 讲话类直播带货只允许模式对应的音频口生效，其余一律忽略并告警，
        # 保证用户选错/多接也不会串音。lip_audio 仅用于对口型 MV，直播带货不接。
        elif _ls_mode:
            _ls_lbl = _LIVESTREAM_VOICE_MODE_LABEL.get(_ls_mode, _ls_mode)
            if _ls_mode == "01":
                # 三口全不接：模型读分镜台词、用自身默认音色生成人声。
                if _lip_voice is not None or lip_audio is not None or ref_audio is not None:
                    print(f"[H3 直播带货] {_ls_lbl}: 已忽略用户误接的 "
                          f"{'ref_audio' if ref_audio is not None else ''}"
                          f"{'、' if ref_audio is not None and (_lip_voice is not None or lip_audio is not None) else ''}"
                          f"{'lip_audio' if lip_audio is not None else ''}"
                          f"{'、' if lip_audio is not None and _lip_voice is not None else ''}"
                          f"{'lip_voice' if _lip_voice is not None else ''} — 模型纯文本配音")
                _lip_voice = None
                lip_audio = None
                ref_audio = None
            elif _ls_mode == "02":
                # 只接 ref_audio 音色参考：模型读台词生成人声，声线跟随 ref_audio。
                if _lip_voice is not None or lip_audio is not None:
                    print(f"[H3 直播带货] {_ls_lbl}: 已忽略 lip_audio/lip_voice，仅用 ref_audio 音色参考配音")
                _lip_voice = None
                lip_audio = None
                if ref_audio is None:
                    print("[H3 直播带货] ⚠️ 02 ref_audio音色参考：未接参考音频端口 → 退化为纯文本配音（默认音色）。请把参考音频接入 ref_audio。")
                else:
                    print(f"[H3 直播带货] {_ls_lbl}: ref_audio 音色参考生效，模型读分镜台词生成人声并跟随参考音色")
            elif _ls_mode == "03":
                # 只接 lip_voice 对口型：模型不生成音频，声音完全由 lip_voice 驱动 @图1 对口型。
                if ref_audio is not None or lip_audio is not None:
                    print(f"[H3 直播带货] {_ls_lbl}: 已忽略 ref_audio/lip_audio，声音完全由 lip_voice 提供")
                ref_audio = None
                lip_audio = None
                if _lip_voice is None:
                    print("[H3 直播带货] ⚠️ 03 lip_voice对口型：未接 lip_voice 端口 → 无对口型驱动音频。请把主播现成音频接入 lip_voice。")
                else:
                    print(f"[H3 直播带货] {_ls_lbl}: lip_voice 对口型生效，模型不生成音频，完全由外部音频驱动 @图1 对口型")
        if _lip_voice is not None:
            # 走到这里 lip_audio 必为 None（v14.270: lip_audio 最高优先级已在上方拦截）。
            lip_audio = _lip_voice
            print(f"[H3 LipSync] ✅ lip_voice 已连接 → 升级为对口型驱动音频"
                  f"(取消模型自生成音频, 外部音频驱动口型; 仅在 lip_audio 未接时生效)")
            # v14.252 (2026-10-29): 不分渲染管道/模式, 只要 lip_audio(lip_voice) 有
            # 真正音频输入, 一律按音频实际时长切分 clip (不 atempo 拉长, 不缩短);
            # lip_audio=None (纯连端口/前端音频节点被 Bypass) → 不触发, 回退模型生成音频。
            # v14.251 原本限定 _ls_mode=="03", 用户在双采2K/其他管道连 lip_voice 时走不到,
            # 仍被 v14.203 atempo 拉到模板 clips 总时长 (25.51s 被拉成 30.17s) + v14.175
            # 追加延续 clip (2 clip 变 3 段)。现放宽为全管道通用。
            if lip_audio is not None and clips:
                clips, _audio_driven = _ls_auto_clip_durations_by_audio(clips, lip_audio, fps=float(FPS))
                if _audio_driven:
                    print(f"[H3 LipSync] v14.252 音频驱动 clip 切分已生效 (全管道通用, 按音频实际时长切分, 不拉长不缩短)")
        else:
            _lip_voice_dummy = None
        _tts_model = kwargs.get("tts_model_TTS模型")
        # v14.280: 自动多人对话声音克隆 —— 当 tts_model + 资产库音频参考都在，
        # 且没有外部 lip_audio/lip_voice 驱动时，从分镜脚本提取对话台词，
        # 自动调用 BSAIDialogueVoiceClone 合成完整多说话人对话音频，
        # 结果作为 lip_audio 驱动所有 @图N 角色的对口型。
        if _tts_model is not None and lip_audio is None and _lip_voice is not None:
            pass  # lip_voice 已接音频，不需要自动合成
        elif _tts_model is not None and lip_audio is None and _lip_voice is None:
            try:
                # _speaker_audio_map 在资产库解析时已赋值（6元组返回值）
                _am = locals().get("_speaker_audio_map", {})
                _auto_tts_triggered = self._try_auto_dialogue_tts(
                    clips=clips,
                    tts_model=_tts_model,
                    speaker_audio_map=_am,
                    asset_library=asset_library,
                    picture_asset_map=locals().get("_picture_asset_map", {}),
                )
                if _auto_tts_triggered is not None:
                    lip_audio, _auto_clip_durs = _auto_tts_triggered
                    # v14.281: 每段台词音频长度直接作为该 clip 的时长 →
                    # 后续 _split_lip_audio_by_clips 按这个时长切分，音画逐段严格对齐。
                    # 没有台词（时长 0）的 clip 关闭渲染，不参与成片。
                    if clips and len(_auto_clip_durs) == len(clips):
                        for _c, _d in zip(clips, _auto_clip_durs):
                            if _d <= 0.05:
                                _c["render_enabled"] = False
                            else:
                                _c["duration"] = max(0.25, float(_d))
                                _c["render_enabled"] = True
                                # v14.295: 保留工作流的 context_enabled 设置。
                                # 之前 v14.285/287 强制关闭 context 是为了口型对齐，
                                # 但 v14.254 已修复 _split_lip_audio_by_clips 的
                                # context 帧对齐（clip2+ 按净帧数推进音频），
                                # context_enabled=True 不再错位；强制关闭反而导致
                                # 段间无 motion context 衔接 → clip1→clip2 首帧跳变。
                        print("[H3 AutoTTS] clip 时长已按逐段台词音频设置: "
                              + "/".join((f"{_d:.2f}s" if _d > 0.05 else "off") for _d in _auto_clip_durs))
                    print(f"[H3 AutoTTS] ✅ 多人对话自动合成完成 → 已升级为 lip_audio 驱动口型")
            except Exception as _e:
                print(f"[H3 AutoTTS] 自动多人对话合成跳过（非致命）：{_e}")
                import traceback as _tb
                print(f"[H3 AutoTTS]  {_tb.format_exc()[-200:]}")
        elif _tts_model is not None:
            print(f"[H3 LipSync] 检测到 tts_model 输入连接，但 lip_audio/lip_voice 也已接入 → 外部音频优先，跳过自动多人对话合成")
        ref_items = None
        ref_blocks = None
        active_picture_slots = None

        # ── v14.176: 武戏组合拳档 → H3 17 帧块对齐 ──
        # YZ金鱼终极篇帧数公式 max(5, round(a*24)) + (5 - x%17)%17 (即帧数 %17==5),
        # 对齐 H3 video latent 时间结构, 防高动态武戏 latent 时间错位/果冻伪影。
        # 在 lip 切段/时长换算之前统一调整 clips duration, 保证帧数与音频段一致。
        if _h3_align17 and clips:
            for _c in clips:
                _cd = _c.get("duration", 5.0)
                try:
                    _cd_f = float(_cd)
                except (TypeError, ValueError):
                    _cd_f = float(str(_cd))
                _cf = _duration_to_frames(_cd_f)
                _cfa = _cf + (5 - _cf % 17) % 17
                if _cfa != _cf:
                    _c["duration"] = float(_cfa) / float(FPS)
            print(f"[H3 Extender] v14.176 武戏组合拳: clips 帧数已对齐 H3 17 块 "
                  f"({'/'.join(str(_duration_to_frames(float(_c.get('duration', 5)))) for _c in clips)} 帧)")

        # ── Lip Sync Audio 预分割 ──
        # 连接 lip_audio 时，按各 CLIP 时长把完整音频切成 N 段，
        # 每段驱动对应 CLIP 的对口型生成。
        lip_audio_segments = None
        if lip_audio is not None:
            # v14.157: 传入 context_length 帧数 — ctx_on 段按净时长(标称-context)
            # 推进切分, 否则每个段间边界原曲被跳过 context/fps 秒(39帧=1.625s)。
            try:
                _ctx_frames = int(str(context_length))
            except (TypeError, ValueError):
                _ctx_frames = 0
            # v14.252 (2026-10-29): 删除 v14.203 atempo 时长自适应 —— 用户要求 lip_voice
            # 音频不拉长不缩短, 按实际时长切分。v14.252 已在上方按音频实际时长重排 clips
            # (clip 总时长 = 音频时长), 此处再 atempo 拉到 clips 总时长会双重变速
            # (25.51s 被拉成 30.17s, 口型听感变慢), 彻底移除。
            # ── v14.175: 对口型驱动音频超长 → 自动追加延续分镜 CLIP ──
            # 外部音频总时长 > 分镜脚本 clips 总时长时(例: 音频35s / 脚本30s),
            # 自动追加一个延续上一个分镜画面的 CLIP 承载多余音频, 保证外部音频完整性,
            # 尾部台词不再被截断丢弃。
            try:
                _lip_total_dur = float(int(lip_audio["waveform"].shape[-1])) / float(lip_audio["sample_rate"])
            except Exception:
                _lip_total_dur = 0.0
            _sum_clip_dur = 0.0
            for _c in clips:
                _d = _c.get("duration", 5.0)
                try:
                    _sum_clip_dur += float(_d)
                except (TypeError, ValueError):
                    _sum_clip_dur += float(str(_d))
            if _lip_total_dur > _sum_clip_dur + 0.01 and clips:
                _extra_dur = _lip_total_dur - _sum_clip_dur
                _last = clips[-1]
                _new_clip = dict(_last)
                _new_clip["id"] = f"{str(_last.get('id', 'clip'))}_auto_ext"
                _new_clip["duration"] = float(_duration_to_frames(_extra_dur)) / float(FPS)
                # 画面延续上一个分镜: 保留原 prompt — lip 模式下提示词净化会抹掉
                # 唱歌/说话描述, 口型完全由音频驱动, 画面沿用上一分镜构图/场景。
                _new_clip["prompt"] = _last.get("prompt", "")
                _new_clip["validated"] = False
                _new_clip["seed_mode"] = "randomize"
                if _rp_mode == "直播带货（全自动）":
                    # v14.202: 本档 clip2+ 一律无 motion context, 自动追加的
                    # 延续段同样继承该规则(否则会从上一段尾部渐变出首帧拖影)。
                    _new_clip["context_enabled"] = False
                clips.append(_new_clip)
                # v14.189 (fix): 自动追加延续 CLIP 后必须同步扩展 clip_ref_plans ——
                # clip_ref_plans 在函数前部按原始 clips 构建(len=N), 此处 append 使
                # len(clips)=N+1, 渲染循环 loop_end=len(clips) 会访问 clip_ref_plans[N]
                # → IndexError: list index out of range。延续段画面沿用上一分镜构图,
                # 其 <Picture N> 引用与上一分镜相同, 直接继承最后一条 plan 即可。
                if clip_ref_plans is not None:
                    clip_ref_plans.append(dict(clip_ref_plans[-1]))
                    print(f"[H3 Extender] v14.189 clip_ref_plans 同步扩展: {len(clip_ref_plans)-1} 条 -> {len(clip_ref_plans)} 条 (继承最后一条)")
                print(f"[H3 LipSync] ✅ 对口型音频 {_lip_total_dur:.2f}s > 分镜总时长 "
                      f"{_sum_clip_dur:.2f}s → 自动追加延续分镜 CLIP +{_new_clip['duration']:.2f}s "
                      f"(id={_new_clip['id']}), 外部音频完整性已保证")
            lip_audio_segments = _split_lip_audio_by_clips(
                lip_audio, clips, fps=float(FPS), context_frames=_ctx_frames,
                explicit_clip_durations=locals().get("_auto_clip_durs"))
            print(f"[H3 LipSync] ✅ 已启用对口型模式，{len(lip_audio_segments)} 段音频已就绪 "
                  f"(context={_ctx_frames}帧, ctx_on 段按净时长推进)")
            # ── 声音参考共存模式（v2.121）──
            # lip_audio 注入 AV latent 锁定口型；ref_audio 保留为音色/风格参考（ref_block）。
            # 两者各司其职：lip_audio 驱动嘴型，ref_audio 告诉模型"这个人的声音应该什么样"。
            if ref_audio is not None:
                print("[H3 LipSync] 🎙️ ref_audio 保留为音色参考（与 lip_audio 共存）")
            # 已缓存(validated)的 CLIP 不会重渲：若它们是接歌之前生成的，口型对不上新歌。
            _cached_count = sum(1 for _c in clips if _c.get("validated"))
            if _cached_count:
                print(f"[H3 LipSync] ⚠️ 注意：{_cached_count} 个 CLIP 当前为缓存(validated)状态，"
                      f"本次不会重新渲染对口型。若它们是接入 lip_audio 之前生成的，"
                      f"请取消这些 CLIP 的 ✅ 校验标记后重渲，否则口型与歌曲不匹配。")

        # ── v14.335 视频人物替换 (Video Recast): 建立"源视频 → clipN"替换计划 ──
        # ── v14.341 视频角色替换+动作迁移 (Video Remix): 同一条链路，换 226/22 分段器 ──
        # 必须放在 loop_end = len(clips) 之前：替换档会自动补齐/裁剪 CLIP 数量
        # (45s 源视频 → 3 × 15s / remix → 每段净 204 帧)，loop_end 才能在后面的
        # 循环里覆盖到补齐的段。
        _recast_plan = None
        _remix_mode = (_rp_mode == "视频角色替换+动作迁移")
        _viggle_mode = (_rp_mode in _VIGGLE_RP_LABELS)
        _rp_tag = ("H3 Viggle" if _viggle_mode
                   else ("H3 Remix" if _remix_mode else "H3 Recast"))
        if _viggle_mode:
            # v14.355: 面板开关状态明确打一行 —— 关的时候出片后一律不跑换脸，
            # 免得误以为"关了还在跑 12 分钟 CPU"。
            print(f"[H3 Viggle] v14.355 换脸开关: "
                  f"{'开 (model=' + _viggle_faceswap_model + ')' if _viggle_faceswap_on else '关（面板未勾选，出片后不换脸）'}",
                  flush=True)
        if (_rp_mode == "视频替换 (V2V 人物替换)" or _remix_mode or _viggle_mode):
            try:
                if _viggle_mode:
                    # v14.349: 段间 motion context 在 Viggle 档必崩 —— 上一段 context
                    # 长度与这一段 17n+5 网格对不上时报 "previous latent/context length
                    # phase mismatch"，第 2 段直接死。这里强制所有 CLIP 关上下文，
                    # 与 _viggle_build_plan 的 overlap=0 双保险。
                    try:
                        _vg_ctx_reset = sum(1 for _c in clips if _c.get("context_enabled"))
                        for _c in clips:
                            _c["context_enabled"] = False
                        print(f"[H3 Extender] v14.349 Viggle 档硬跳 motion context: "
                              f"{_vg_ctx_reset} 个 CLIP 已关闭上下文续接", flush=True)
                    except Exception as _vg_ctx_err:
                        print(f"[H3 Extender] v14.349 关闭 context 失败(忽略): {_vg_ctx_err}")
                    _recast_plan = _viggle_build_plan(
                        clips, asset_library, ffmpeg=_find_ffmpeg())
                else:
                    _recast_plan = (
                        _remix_build_plan(clips, asset_library, ffmpeg=_find_ffmpeg())
                        if _remix_mode
                        else _recast_build_plan(clips, asset_library, ffmpeg=_find_ffmpeg())
                    )
            except Exception as _rc_plan_err:
                raise RuntimeError(
                    f"[{_rp_tag}] 替换计划构建异常，本档中止（不会退回普通渲染）："
                    f"{type(_rc_plan_err).__name__}: {_rc_plan_err}") from _rc_plan_err
            # v14.336: 计划为空 = 没有 @视频N / 资产库里没有该视频 → 本档直接中止。
            # 以前这里是"print 后回退普通渲染"，实测会带着 lip_audio 把分镜拉成
            # 200s 级长段再 OOM（渲染几十分钟才炸），静默降级比报错代价大得多。
            if _recast_plan is None:
                raise RuntimeError(
                    f"[{_rp_tag}] 本档（{_rp_mode}）无法建立替换计划：\n"
                    "  1) 分镜提示词里必须出现 @视频N（例：@图1 替换 @视频1 里的主持人）；\n"
                    "  2) 资产库 Videos 位要上传对应的源视频（文件在 input/bsai_assets/videos/）；\n"
                    "  3) 参考图放资产库 Images 位，用 @图N 指定「谁换成谁」。\n"
                    "修正后重新运行即可；本次已中止，不会退回普通渲染（那会把单段撑到 OOM）。")
            if _recast_plan is not None:
                # 替换档会自动追加 CLIP；clip_ref_plans 按原始 len(clips) 构建，
                # 不同步扩展会在渲染循环里越界（与 v14.189 对口型自动续段同源问题）。
                if clip_ref_plans is not None:
                    while len(clip_ref_plans) < len(clips):
                        clip_ref_plans.append(dict(clip_ref_plans[-1]))
                    print(f"[{_rp_tag}] clip_ref_plans 同步扩展: {len(clips)} 条")
                # 替换档的画面与口型都由源视频提供：lip_audio 会另灌一套音频行，
                # 与"锁定源原声"互相冲突，这里直接忽略并告知。
                if lip_audio_segments is not None:
                    print(f"[{_rp_tag}] ⚠️ 已忽略 lip_audio 对口型输入 —— 本档用源视频原声"
                          "直接锁进 AV latent，口型随源片逐帧对齐")
                    lip_audio_segments = None
                print(f"[{_rp_tag}] 替换计划就绪: {len(_recast_plan['segments'])} 个 CLIP 将"
                      f"逐段替换 (源 {_recast_plan['duration']:.2f}s)，"
                      f"自动补齐 {_recast_plan['auto_added']} 段，"
                      f"跳过 {_recast_plan['disabled']} 段无源画面的分镜")

        disk_join = MiniMaxH3MotionContextDiskJoin()
        motion = MiniMaxH3MotionContextRAM()

        previous_handle = None
        previous_proxy = None
        generated = []
        statuses = []

        # ── Merge Output mode: restore tail + produce merged video ────
        # When user clicks "合并输出" button, this flag is set. We skip all
        # rendering, restore any saved tail latents from disk, mark all clips
        # as validated, and produce the merged output.
        #
        # Also auto-trigger merge_output if there are saved tail latents on
        # disk and no replace_mode is active — this prevents accidental
        # re-rendering of tail clips when the user clicks Queue without
        # explicitly clicking "合并输出".
        if merge_output or (not any(c.get("replace_mode", False) for c in clips)
                             and _has_tail_latents_on_disk(owner)):
            print("[H3 Extender] merge_output mode: restoring tail + producing merged output")
            # Clear all replace_mode flags
            for cfg in clips:
                cfg["replace_mode"] = False

            # Load saved tail latents from disk (if any)
            disk_tail = _load_tail_latents_from_disk(owner)
            if disk_tail is not None:
                print(f"[H3 Extender] merge_output: restoring {len(disk_tail)} tail clip(s) from disk")
                restored_manifest = _restore_tail_latents(data_path, manifest_path, disk_tail)
                if restored_manifest is not None:
                    manifest = restored_manifest
                _delete_tail_latents_from_disk(owner)
            else:
                print("[H3 Extender] merge_output: no saved tail latents found, using existing chain as-is")

            # Mark all clips as validated
            final_manifest = _load_manifest_from_paths(data_path, manifest_path)
            if final_manifest is not None:
                segs = [dict(x) for x in final_manifest.get("segments", [])]
                changed = False
                for i in range(min(len(clips), len(segs))):
                    if not bool(segs[i].get("validated", False)):
                        segs[i]["validated"] = True
                        changed = True
                    clips[i]["validated"] = True
                    clips[i]["replace_mode"] = False
                if changed:
                    final_manifest = dict(final_manifest)
                    final_manifest["segments"] = segs
                    final_manifest["build"] = BUILD
                    final_manifest["updated_at"] = time.time()
                    _write_json_atomic(manifest_path, final_manifest)

            # Walk the chain to set previous_handle/proxy for Final Decode
            final_manifest = _load_manifest_from_paths(data_path, manifest_path)
            cached_count = len(final_manifest.get("segments", [])) if final_manifest else 0
            for i in range(cached_count):
                result = disk_join.join(
                    samples=None,
                    trim_frames=None,
                    validated=True,
                    run_mode=str(run_mode),
                    fps=float(FPS),
                    previous_cache=previous_handle,
                    unique_id=f"extender_{owner}",
                )
                previous_handle = result[0]
                previous_proxy = result[1]
                statuses.append(result[4])

            if previous_handle is None:
                raise RuntimeError("MiniMax H3 Extender: merge_output produced no cache handle.")

            validated_count = cached_count
            normalized_json = _state_json(clips, active_prompt_pack_signature)
            resolution_text = f"{resolved_width}x{resolved_height}"
            status = f"merge_output | {resolution_text} | cached {cached_count}/{len(clips)} | validated {validated_count} | merged"
            cache_mb = _cache_size_mb(data_path, manifest_path)

            _send_extender_progress(owner, -1, len(clips), "idle", status)

            # v1.18: 单独选择生成（render_partial）时跳过了 preview 解码，
            # decoded_mp4_blob 缺失——合并输出前对缺失段自动补解码，保证 merged 可产出。
            if final_manifest is not None:
                try:
                    _tgt_w = int(final_manifest.get("output_width", 0) or 0)
                    _tgt_h = int(final_manifest.get("output_height", 0) or 0)
                    _segs = [dict(x) for x in final_manifest.get("segments", [])]
                    for _si, _seg in enumerate(_segs):
                        if int(_seg.get("frames", 0)) <= 0:
                            continue
                        _need_dec = _seg.get("decoded_mp4_blob") is None
                        _why = "单独生成未产 blob"
                        if (not _need_dec and _tgt_w > 0 and _tgt_h > 0
                                and (int(_seg.get("decoded_mp4_width", 0) or 0) != _tgt_w
                                     or int(_seg.get("decoded_mp4_height", 0) or 0) != _tgt_h)):
                            # v14.156: 旧 blob 是二采降级后的像素（如 1440x800），
                            # 与新段的声明尺寸不一致会导致 concat 失败；解码入口
                            # 会用 ffmpeg 重采样到声明尺寸并保留原音轨。
                            _need_dec = True
                            _why = (f"尺寸 {_seg.get('decoded_mp4_width', '?')}x"
                                    f"{_seg.get('decoded_mp4_height', '?')} -> {_tgt_w}x{_tgt_h}")
                        if _need_dec:
                            print(f"[H3 Extender] merge_output: 校正 segment {_si}（{_why}）")
                            _decode_single_clip_preview(owner, _si, vae, audio_vae, float(FPS), _find_ffmpeg())
                    final_manifest = _load_manifest_from_paths(data_path, manifest_path) or final_manifest
                except Exception as _me:
                    print(f"[H3 Extender] merge_output: blob 补解码失败 {_me}")

            # Produce merged output directly — merge_output always produces
            # a merged video regardless of the output_mode widget setting.
            output_ui_videos = []
            if final_manifest is not None:
                try:
                    out_dir = Path(folder_paths.get_output_directory()).resolve()
                except Exception:
                    out_dir = (Path.cwd() / "output").resolve()
                out_dir.mkdir(parents=True, exist_ok=True)
                prefix = _safe_name(str(filename_prefix or "H3_Extender"))
                segments_out = [dict(x) for x in final_manifest.get("segments", [])]
                ff = None
                try:
                    ff = _find_ffmpeg()
                except Exception:
                    ff = None

                want_per_clip = str(output_mode) in ("per_clip", "both")
                want_merged = True  # merge_output always produces merged video
                # v14.340: FVSR 逐分镜修复结果复用表（si -> 修复后 mp4），避免 per-clip 与 merged 重复跑模型
                _fvrs_cache = {}

                if want_per_clip:
                    for si, seg in enumerate(segments_out):
                        blob = seg.get("decoded_mp4_blob")
                        if blob is None:
                            continue
                        clip_path = out_dir / f"{prefix}_clip{si + 1:02d}.mp4"
                        try:
                            _copy_blob_to_file(data_path, blob, clip_path)
                            # v14.83 per-clip 逐段超分（总开关 + CLIP 级三态优先，clips[si] 含 upscale 字段）
                            if _ff_clip_upscale_enabled(clips[si] if si < len(clips) else None, upscale_per_clip):
                                _ff_upscale_video_file(clip_path, _up_factor, _up_engine,
                                                       upscale_model, upscale_fp16,
                                                       upscale_tile, upscale_batch,
                                                       upscale_face_restore)
                            # v14.340: 音频引导人脸/嘴型修复（TaoMate-FVSR）
                            if face_fvrs_enabled:
                                _src_fv = _ff_fvrs_restore_clip(clip_path, float(FPS))
                                _fvrs_cache[si] = str(_src_fv)
                                if _src_fv and str(_src_fv) != str(clip_path) and os.path.isfile(str(_src_fv)):
                                    try:
                                        shutil.copy2(_src_fv, clip_path)
                                    except Exception as _e_fv:
                                        print(f"[H3 Extender] FVSR per-clip 回写失败: {_e_fv}")
                            item = _comfy_media_item(clip_path, float(FPS), "output")
                            output_ui_videos.append(item)
                            print(f"[H3 Extender] saved per-clip video: {clip_path}")
                        except Exception as _e:
                            print(f"[H3 Extender] failed to save clip {si+1}: {_e}")

                if want_merged and len(segments_out) > 0:
                    temp_root = _ensure_cache_root()
                    concat_list = temp_root / f"_concat_{owner}_{uuid.uuid4().hex[:8]}.txt"
                    clip_paths = []
                    for si, seg in enumerate(segments_out):
                        blob = seg.get("decoded_mp4_blob")
                        if blob is None:
                            continue
                        cp = temp_root / f"_mergeclip_{owner}_{si}_{uuid.uuid4().hex[:8]}.mp4"
                        try:
                            _copy_blob_to_file(data_path, blob, cp)
                            # v14.340: 复用 per-clip 已修复结果；否则对临时合并片段现场修复
                            if face_fvrs_enabled:
                                _src_fv = _fvrs_cache.get(si)
                                if not (_src_fv and os.path.isfile(str(_src_fv))):
                                    _src_fv = _ff_fvrs_restore_clip(cp, float(FPS))
                                if _src_fv and str(_src_fv) != str(cp) and os.path.isfile(str(_src_fv)):
                                    try:
                                        shutil.copy2(_src_fv, cp)
                                    except Exception as _e_fv:
                                        print(f"[H3 Extender] FVSR merge-clip 复用失败: {_e_fv}")
                            clip_paths.append(cp)
                        except Exception:
                            pass

                    if clip_paths:
                        with open(concat_list, "w", encoding="utf-8") as f:
                            for cp in clip_paths:
                                f.write(f"file '{cp.as_posix()}'\n")

                        merged_path = out_dir / f"{prefix}_merged.mp4"
                        if len(clip_paths) == 1:
                            shutil.copy2(clip_paths[0], merged_path)
                        elif ff:
                            # v14.158: 一镜到底旁支模式 —— 无缝 concat（零转场）。
                            # 段间连续性由 motion context（Add Guide 等效锚点）保证,
                            # 不再叠加 xfade 转场, 接缝处肉眼不可见。
                            if one_shot_enabled:
                                _xcmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
                                         "-c:v", "libx264", "-preset", "fast", "-crf", "17",
                                         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(merged_path)]
                                try:
                                    subprocess.run(_xcmd, check=True, capture_output=True, timeout=600)
                                    print(f"[H3 Extender] saved merged video (一镜到底无缝 concat, {len(clip_paths)} clips): {merged_path}")
                                except Exception as _e:
                                    print(f"[H3 Extender] 一镜到底 seamless concat failed: {_e}")
                            else:
                                # v2.0: 链式 xfade 视频渐变 + acrossfade 音频渐变, N段通用
                                _xcmd, _durs = _ff_build_xfade_merge_cmd(ff, clip_paths, merged_path)
                                if _xcmd is not None:
                                    try:
                                        subprocess.run(_xcmd, check=True, capture_output=True, timeout=600)
                                        print(f"[H3 Extender] saved merged video (xfade chain, {len(clip_paths)} clips): {merged_path}")
                                    except Exception as _e:
                                        print(f"[H3 Extender] xfade chain failed, fallback re-encode concat: {_e}")
                                        _xcmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
                                                 "-c:v", "libx264", "-preset", "fast", "-crf", "17",
                                                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(merged_path)]
                                        try:
                                            subprocess.run(_xcmd, check=True, capture_output=True, timeout=600)
                                        except Exception as _e2:
                                            print(f"[H3 Extender] re-encode concat also failed: {_e2}")
                                else:
                                    # clips too short for xfade → re-encode concat with audio
                                    _xcmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
                                             "-c:v", "libx264", "-preset", "fast", "-crf", "17",
                                             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(merged_path)]
                                    try:
                                        subprocess.run(_xcmd, check=True, capture_output=True, timeout=600)
                                        print(f"[H3 Extender] saved merged video (re-encode concat): {merged_path}")
                                    except Exception as _e:
                                        print(f"[H3 Extender] ffmpeg merge failed: {_e}")

                        # v14.83 全片合并后一次性超分（默认关）
                        if upscale_final:
                            _ff_upscale_video_file(merged_path, _up_factor, _up_engine,
                                                   upscale_model, upscale_fp16,
                                                   upscale_tile, upscale_batch,
                                                   upscale_face_restore)

                        try:
                            item = _comfy_media_item(merged_path, float(FPS), "output")
                            output_ui_videos.append(item)
                            print(f"[H3 Extender] saved merged video: {merged_path}")
                        except Exception as _e:
                            print(f"[H3 Extender] failed to create media item for merged: {_e}")

                        for cp in clip_paths:
                            try:
                                cp.unlink()
                            except Exception:
                                pass
                        try:
                            concat_list.unlink()
                        except Exception:
                            pass

            try:
                _snapshot_chain(data_path, manifest_path, reason="merge-output")
            except Exception:
                pass
            return {
                "ui": {
                    "videos": output_ui_videos,
                    "h3_extender_state": [{
                        "clips_json": normalized_json,
                        "clip_count": len(clips),
                        "cached_count": cached_count,
                        "validated_count": validated_count,
                        "generated": [],
                        "status": status,
                        "resolved_width": resolved_width,
                        "resolved_height": resolved_height,
                        "build": BUILD,
                        "restore_cache_done": bool(restore_cache_done),
                    }],
                },
                "result": (
                    previous_handle,
                    len(clips),
                    validated_count,
                    status,
                    cache_mb,
                    BUILD,
                ),
            }

        # ── Per-clip selective rendering ──────────────────────────────
        # Build selected_set from per-clip flags:
        #   - replace_mode=True  → re-render this clip (replaces previous output)
        #   - render_enabled=False → skip this clip (keep cached, don't generate)
        # When any clip has replace_mode, the chain is truncated to just
        # before the first such clip, and only the selected clip(s) are
        # re-rendered. Tail latents are saved to disk (not restored
        # automatically); the user must click "合并输出" to merge.
        saved_tail = None
        single_clip_replace = False
        loop_end = len(clips)
        first_sel = None
        last_sel = None
        selected_set = set()
        any_replace = False
        for i, cfg in enumerate(clips):
            if cfg.get("replace_mode", False):
                selected_set.add(i)
                any_replace = True
                if first_sel is None:
                    first_sel = i
                last_sel = i

        if any_replace:
            single_clip_replace = True
            manifest = _load_manifest_from_paths(data_path, manifest_path) or manifest
            segments = manifest.get("segments", [])

            # 2026-09-05 v1.21: 重渲染单个/多个 CLIP 后，不再保存/截断尾部 latent、
            # 不再自动合并 —— 仅渲染选中的 CLIP，渲染完即暂停静默等待。
            # 用户可手动选择合并输出、继续生成余下全部 CLIP、或选择其他单个 CLIP 重渲染。
            # 主循环依据 validated=False 仅重新采样选中段，其余段保留缓存。
            render_partial = True  # 重渲染 = 部分渲染，禁止自动合并
            if _has_tail_latents_on_disk(owner):
                _delete_tail_latents_from_disk(owner)
                print("[H3 Extender] per-clip replace: deleted stale tail latents from disk")
            saved_tail = None

            # Override validated flags: first_sel 之前的保留缓存（join），
            # 仅选中的 clip 置为未验证 → 重新渲染，其余保留缓存不重渲染。
            # v1.21: 单 clip 重渲染后立即停止，不连续渲染后续 clip，静默等待用户下一步操作。
            for i, cfg in enumerate(clips):
                if i in selected_set:
                    cfg["validated"] = False
                else:
                    cfg["validated"] = True
            # 限制循环只到最后一个选中 clip，选中 clip 渲染完即停止
            loop_end = max(selected_set) + 1
            _sel_list = ",".join(str(s + 1) for s in sorted(selected_set))
            print(f"[H3 Extender] single clip replace: selected_set={sorted(selected_set)} loop_end={loop_end} will re-render clip(s) {_sel_list}, then pause for user action")

        # v2.64: per-clip 独立渲染优先 —— 用户点击卡片「▶ 独立渲染」设置 replace_mode 时，
        # clip_select 范围选择不再生效。否则残留的 clip_select_enable=True 会让循环条件
        # `i not in select_override` 跳过用户指定渲染的 clip（如选 11-30 时点 clip9 ▶ 无效），
        # 且 v2.63 强制启用选择集内所有 clip，导致实际渲染的是选择集而不是用户点的 clip。
        if any_replace and select_override is not None:
            print("[H3 Extender] v2.64: 检测到 per-clip 独立渲染(replace_mode)，忽略 clip_select 范围选择，仅按卡片生成开关渲染。")
            select_override = None

        # v1.17: 前置 latent 链完整性检查 —— 部分选择 / 重渲染时，若磁盘 latent 链
        # 不足以支撑所选段的前置段，自动补渲染缺失段建立完整链（H3 必须依赖前置
        # latent 做 motion context），并明确打印提示，让用户知情而非报错/静默。
        _need_pre = None
        if select_override is not None:
            _need_pre = min(select_override)
        elif any_replace and first_sel > 0:
            _need_pre = first_sel
        if _need_pre is not None:
            try:
                _pre_m = _load_manifest_from_paths(data_path, manifest_path)
                _pre_n = len(_pre_m.get("segments", [])) if _pre_m else 0
            except Exception:
                _pre_m = None
                _pre_n = 0
            if _pre_n < _need_pre:
                try:
                    import os as _os
                    _jz = _os.path.getsize(manifest_path) if _os.path.exists(manifest_path) else None
                    _bz = _os.path.getsize(str(manifest_path) + ".bak") if _os.path.exists(str(manifest_path) + ".bak") else None
                    _dz = _os.path.getsize(data_path) if _os.path.exists(data_path) else None
                    print(f"[H3 Extender] v1.80 cache诊断: json={_jz}字节 bak={_bz}字节 h3cache={_dz}字节")
                except Exception:
                    pass
                _from = max(0, _pre_n)
                if select_override is not None:
                    # v2.62: 补渲染范围收窄到「选中段跨度内」，保持仅渲染指定段语义，
                    # 不再从缺口一路补到末尾（末尾未选中的 CLIP 保留缓存/不重新生成）。
                    _sel_max = max(select_override)
                    _old_sel = set(select_override)
                    select_override = set(range(_from, _sel_max + 1)) | _old_sel
                    _added = sorted(select_override - _old_sel)
                    print(
                        f"[H3 Extender] v2.62 前置 latent 链缺失（磁盘仅 {_pre_n} 段，"
                        f"不足所选 CLIP{_need_pre + 1} 所需的 {_need_pre} 段）：自动补渲染 "
                        f"CLIP {','.join(str(_p + 1) for _p in _added)} 建立完整链，随后仅渲染选中段。"
                    )
                else:
                    # v2.65: per-clip 独立渲染绝不自动补渲染其他 CLIP。
                    # 前置链不足时只警告，CLIP{N} 直接接续现有链末尾渲染（用户明确要求：
                    # 单点 CLIPN 只渲染 CLIPN，不渲染 CLIP1..N-1）。如需完整前置链请先「♻️ 恢复缓存」。
                    print(
                        f"[H3 Extender] v2.65 per-clip 独立渲染前置链不足（磁盘仅 {_pre_n} 段，"
                        f"CLIP{_need_pre + 1} 需 {_need_pre} 段）：按用户要求不补渲染其他 CLIP，"
                        f"CLIP{_need_pre + 1} 将接续现有链末尾渲染；如需完整前置链请先点「♻️ 恢复缓存」。"
                    )

        # v2.62: 中段缺口补齐 —— 选中段跨度内被跳过且磁盘无缓存的 CLIP 必须补渲染，
        # 否则 H3 链式运动上下文断链（后续段会拿错前置 latent）。
        # 典型场景：已有 CLIP1-2 缓存时输入 3,5,7，CLIP4/6 无缓存 → 自动补渲染 CLIP4/6。
        if select_override is not None:
            try:
                _gap_m = _load_manifest_from_paths(data_path, manifest_path)
                _gap_have = len(_gap_m.get("segments", [])) if _gap_m else 0
            except Exception:
                _gap_have = 0
            _sel_max = max(select_override)
            _gap_fill = set()
            for _p in range(_sel_max + 1):
                if _p not in select_override and _p >= _gap_have:
                    _gap_fill.add(_p)
            if _gap_fill:
                _gap_list = ",".join(str(_p + 1) for _p in sorted(_gap_fill))
                select_override = select_override | _gap_fill
                print(f"[H3 Extender] v2.62 中段缺口补渲染: CLIP {_gap_list} 被跳过但磁盘无缓存，为维持 H3 链式运动上下文自动补渲染。")

        # v1.21: 单 clip 重渲染时，如果前置 latent 链缺失（first_sel < 第一个选中 clip），
        # 强制渲染前置 clip（忽略前端 render_enabled=False），建立完整 latent 链。
        # 否则 disk_join 会把选中 clip 错放到索引0，导致预览解码和 Final Decode 失败。
        if any_replace and selected_set:
            _first_selected = min(selected_set)
            if first_sel < _first_selected:
                for _pre_i in range(first_sel, _first_selected):
                    if _pre_i < len(clips):
                        clips[_pre_i]["render_enabled"] = True
                        clips[_pre_i]["validated"] = False
                        print(f"[H3 Extender] v1.21: force render前置 clip {_pre_i + 1} (latent chain missing, first_sel={first_sel})")

        # v2.63: clip_select 权威选择修复 —— 选中集合（含 v2.62 自动补渲染的前置段/中段缺口）
        # 必须真正进入渲染循环。若残留 render_enabled=False（例如此前点「独立渲染▶」/「↻」
        # 留下的旧状态），循环的 `not render_enabled` 条件会静默跳过选中段：前置链补不出来、
        # 选中段不渲染、首个被渲染的 clip 被错放到链索引 0，导致 preview 越界与 Final Decode
        # 错位（典型症状：选了 11-30 却只渲染了 1 个 clip、轨道无输出）。
        # 与 v1.21「强制渲染前置 clip（忽略前端 render_enabled=False）」同一原则：
        # clip_select 显式选择时，选择集内的 render_enabled 一律强制为 True。
        if select_override is not None:
            _sel_force = [
                i for i in select_override
                if i < len(clips) and not clips[i].get("render_enabled", True)
            ]
            if _sel_force:
                for _fi in _sel_force:
                    clips[_fi]["render_enabled"] = True
                print(
                    f"[H3 Extender] v2.63 clip_select 权威选择: 选中集内 {len(_sel_force)} 个 clip 的"
                    f"生成开关处于关闭状态，已强制启用（CLIP {','.join(str(_f + 1) for _f in sorted(_sel_force))}）"
                )

        # Build the accelerated sampling model once for the whole pass.
        sampling_model = model
        # v14.342 诊断: 采样前打印当前 ModelPatcher 上已挂载的 LoRA/补丁数量,
        # 用于核对角色替换 LoRA 是否真的到达采样模型。只统计、不改动模型。
        if True:
            try:
                _pm = getattr(sampling_model, "patches", None)
                if _pm is None:
                    print("[H3 Extender][DEBUG-PATCHES] model 无 patches 属性 (非 ModelPatcher?)")
                else:
                    _mods = len(_pm)
                    _entries = 0
                    _lora = 0
                    _strengths = []
                    _samp = []
                    for _k, _v in _pm.items():
                        _entries += len(_v)
                        for _e in _v:
                            _ad = _e[1] if isinstance(_e, tuple) and len(_e) > 1 else None
                            _cls = type(_ad).__name__
                            if "lora" in _cls.lower():
                                _lora += 1
                            if len(_strengths) < 8 and isinstance(_e, tuple) and len(_e) > 2:
                                _strengths.append((round(float(_e[2]), 3), _cls))
                        if len(_samp) < 6:
                            _samp.append(str(_k))
                    print(f"[H3 Extender][DEBUG-PATCHES] patched_modules={_mods} "
                          f"adapter_entries={_entries} lora_adapters={_lora} "
                          f"sample_keys={_samp} sample_strengths={_strengths}")
            except Exception as _ex:
                print(f"[H3 Extender][DEBUG-PATCHES] 统计失败: {type(_ex).__name__}: {_ex}")
        # v1.44: 恢复 ff_chunks=2, attn_head_chunks=4 (对齐 Sol-H3 双采极速版).
        # v1.42 降到 chunks=1/head_chunks=2 是因为 unload_all_models() 导致
        # full lowvram 重载, CPU↔GPU 搬运越多 peak 越高. v1.43 已移除
        # unload_all_models(), diffusion 保持 loaded, 不存在 per-layer
        # 搬运开销, 可以安全使用更激进的 chunking 来降低临时张量显存,
        # 给 1.5x 二采 attention workspace 留更多余量.
        sampling_model = _ff_apply_h3_lowvram_patches(
            sampling_model,
            ff_chunks=2,
            ff_seq_threshold=4096,
            attn_head_chunks=4,
        )
        if int(cache_dit):
            sampling_model = _apply_cache_dit(
                model,
                model_type="Auto",
                warmup_steps=0,
                skip_interval=0,
                print_summary=True,
            )
        elif int(block_cache):
            sampling_model = _apply_h3_block_cache(
                model,
                residual_diff_threshold=float(block_cache_threshold),
                cache_device=str(block_cache_device),
            )

        # Per-CLIP IMAGE+AUDIO streaming outputs.
        out_images = []
        out_audios = []
        _av_decoded = set()
        # v14.330: IMAGE 预览累积预算（全片 float32 累积会撑爆系统内存 → pagefile 抖动）
        _av_acc_budget = _av_acc_budget_bytes()
        _av_acc_state = {"used": 0, "skip": False}
        paused_break = False  # v1.13: 用户暂停/停止后禁止自动合并
        _pending_enc = []  # v1.70: async encode 队列 [(done_event, 链内索引, 全局clip索引)]

        # v14.158: 一镜到底旁支模式 —— 强制开启每段 motion context。
        # 电影工厂的 motion context 把上一段 latent 尾部(默认2s)注入本段 conditioning,
        # 等效 B站工作流中官方 Add Guide 节点"把上一段最后一秒作为锚点引导生成"。
        # 一镜到底必须链式衔接，因此无视卡片级 context_enabled 手动关闭，强制为 True。
        if one_shot_enabled:
            _os_forced = [i + 1 for i, _c in enumerate(clips) if not _c.get("context_enabled", True)]
            for _c in clips:
                _c["context_enabled"] = True
            if _os_forced:
                print(f"[H3 Extender] 一镜到底: 强制开启 {len(_os_forced)} 个 CLIP 的段间 motion context (Add Guide 等效): CLIP {','.join(str(x) for x in _os_forced)}")

        # v14.283 (2026-11-03): 崩溃自动续渲 —— 启动时从 manifest 恢复 validated 状态。
        # 场景: 渲染到 clipN 时 ComfyUI 因 OOM/GPU 崩溃退出, 重跑同 workflow。
        # 此前 join 每段都 validated=False → manifest 全 False → 重跑从 clip1 全量重采样
        # (24min/段×9段=216min 白费)。现在 join 立即 commit validated=True, 重跑时这里
        # 扫描 manifest, 所有已 validated=True 且有 latent 的段 → cfg["validated"]=True
        # → 主循环 skip sampling, 直接从第一个未完成段续渲。replace_mode/select_override
        # 路径在此之前已处理完, 用户显式重渲的段已被强制 False, 不受此处影响。
        if not any_replace and select_override is None:
            try:
                _cr_m = _load_manifest_from_paths(data_path, manifest_path)
                if _cr_m is not None:
                    _cr_segs = _cr_m.get("segments", [])
                    _cr_synced = 0
                    for _i in range(min(len(clips), len(_cr_segs))):
                        if bool(_cr_segs[_i].get("validated", False)):
                            clips[_i]["validated"] = True
                            _cr_synced += 1
                    if _cr_synced > 0:
                        _cr_next = _cr_synced + 1
                        if _cr_synced < len(clips):
                            print(f"[H3 Extender] ✅ v14.283 崩溃自动续渲: manifest 识别到 {_cr_synced} 段已采样(validated=True), "
                                  f"将从 CLIP {_cr_next} 开始续渲, 跳过前置重采样。如需全量重渲请先点「♻️ 恢复缓存」再 Queue。")
                        else:
                            print(f"[H3 Extender] ✅ v14.283 崩溃自动续渲: manifest 识别到全部 {_cr_synced}/{len(clips)} 段已采样, "
                                  f"将进入 Final Decode 合并输出。")
            except Exception as _cr_err:
                print(f"[H3 Extender] v14.283 manifest 自动恢复跳过(可忽略): {_cr_err}")

        # v2.68 fix: 异步预览队列消费提前——encode 完成后立即推送预览/落盘，
        # 不再等下一个 CLIP 渲染完。原逻辑只在每个 CLIP 渲染完成的循环体末尾消费一次；
        # NVENC 编码(约2s)完成时主线程已进入下一 CLIP 渲染，消费被推迟整整一个
        # CLIP(~30min)，导致 per-clip 预览/MP4 延迟出现、用户以为"没生成"。
        def _flush_pending_enc(_paused_break):
            while _pending_enc and _pending_enc[0][0].is_set():
                _ev_done, _j, _gidx = _pending_enc.pop(0)
                if not (not _paused_break and int(output_image_audio)):
                    continue
                try:
                    _cimg, _caud = _decode_clip_to_av(owner, _j, vae, audio_vae, float(FPS))
                    if _cimg is not None and int(_cimg.shape[0]) > 0:
                        # v14.330: 走预算化 uint8 累积，超预算即停止（全片 MP4 已落盘）
                        _av_acc_push(out_images, _cimg, _av_acc_state, _av_acc_budget)
                        _av_decoded.add(_j)
                    if _caud is not None:
                        out_audios.append(_caud)

                    # 提取该 CLIP 的 MP4 blob 到持久目录(output/bsai_clips)，
                    # 供 BSAI Premiere Pro / 前端直接引用。
                    # v2.75: _j 是链索引(全局链=clip 索引; 局部链从 first_sel 起),
                    # _gidx 是全局 clip 索引(命名/前端定位用)。
                    _clip_video_path = None
                    _clip_name = clips[_gidx].get("name", f"CLIP{_gidx + 1}") if _gidx < len(clips) else f"CLIP{_gidx + 1}"
                    try:
                        _m = _load_manifest_from_paths(data_path, manifest_path)
                        if _m and _m.get("segments"):
                            _segs = [dict(x) for x in _m["segments"]]
                            if _j < len(_segs):
                                _blob = _segs[_j].get("decoded_mp4_blob")
                                if _blob is not None:
                                    _temp_dir = _clip_output_dir()
                                    _out_name = f"h3_clip_{owner}_{_gidx + 1}_{int(time.time())}.mp4"
                                    _out_path = _temp_dir / _out_name
                                    _copy_blob_to_file(data_path, _blob, _out_path)
                                    _clip_video_path = str(_out_path)
                                    print(f"[H3 Extender] per-clip video ready: clip {_gidx + 1} -> {_out_path}")
                    except Exception as _ve:
                        print(f"[H3 Extender] per-clip video extract failed clip={_j}: {_ve}")

                    _send_clip_av_output(owner, _gidx, len(clips), _cimg, _caud,
                                          video_path=_clip_video_path, clip_name=_clip_name)
                except Exception as _av_err:
                    print(f"[H3 Extender] per-clip AV output failed clip={_j}: {_av_err}")

        # Walk the card list in order. Cached TRUE clips are metadata-only;
        # active clips sample and are written immediately to disk.
        _os_pass_notice_done = False  # v14.185: 一镜到底采样档提示每次执行只打印一次
        # v14.241 (2026-10-28): 一镜到底 —— context 帧数下限自动提升到官方 22 帧。
        # 根因: 用户实测 context=5 帧(仅覆盖 0.2s)时, 段头延续参考只有 5 帧,
        # 段头锁 keep 区只有 2 latent 行(≈6.8帧), 之后 11.8s 模型完全自由发挥
        # → 段内自切景别(实测: 全身侧姿硬切到近景半身)。官方 continuation 语义
        # = 源尾部 22 帧(0.92s)续接, 上下文越长段头惯性越强, 模型越难在中途
        # 重启镜头。一镜到底时 context_length < 22 自动提升到 22(渲染帧数/锁区/
        # 音频重叠切分均按 context 动态计算, 自动联动, 净输出时长不变)。
        # 逃生门: 显式设环境变量 BSAI_H3_OS_CTX=0 关闭自动提升(保留用户原值)。
        if one_shot_enabled:
            try:
                _ctx_os_raw = str(context_length)
                _ctx_os_val = int(_ctx_os_raw) if str(_ctx_os_raw).isdigit() else 0
                _os_ctx_floor = "0" if os.environ.get("BSAI_H3_OS_CTX", "") == "0" else "22"
                if _ctx_os_val > 0 and _ctx_os_val < int(_os_ctx_floor):
                    print(f"[H3 Extender] v14.241 一镜到底: context_length={_ctx_os_val} 帧(仅 {_ctx_os_val/float(FPS):.2f}s)过短, "
                          f"段头延续不足→段内自切; 已自动提升到官方 {_os_ctx_floor} 帧 "
                          f"(渲染帧数/锁区/音频切分联动, 净输出时长不变; 设 BSAI_H3_OS_CTX=0 关闭)")
                    context_length = _os_ctx_floor
            except (TypeError, ValueError):
                pass
        # ── v14.284 (2026-11-03): 一镜到底 —— 全片统一景别锁定 ──────────
        # 需求: "所有clip段间和段内不切镜, 不换景别, 从头到尾所有运镜必须保持
        # 在一个摄影机运行轨迹上"。
        #
        # v14.286 (2026-11-03) 修正 v14.284 的过度约束:
        #   v14.284 把景别改成"全链锁死单一景别"(全局景别小节 → 否则回退到 clip1
        #   的首个景别词), 并向每段注入 "[景别锁定] 全段保持X构图"。实测用户的
        #   19 段脚本 **段间景别本来就 19/19 全部连续对接**(每段末帧景别 ==
        #   次段首帧景别, 脚本里甚至明写"起幅承接上一段末帧的…机位"), 而锁死
        #   会与 14/19 段的正文构图(中景/中近景/大远景)直接矛盾, 还会抹掉脚本
        #   精心设计的连续推进(中全景→中景→中近景→大远景)。
        #   现在: **只有用户显式声明全局景别小节时才锁死**(并同步改写正文景别词);
        #   否则按"段间景别连续"处理 —— 声明连续性 + 在跨档接缝处给出连续过渡。
        _os_locked_size = None
        _os_env_continuity = ""
        _os_prev_size_end = None      # v14.286: 上一段末帧景别(段间连续判定用)
        # v14.294: 预先算出每一段的场景名 —— 判定"本段与上一段是否同一处空间"。
        # 必须整链预扫: 缓存命中的段会 continue 掉, 在循环里算会让"上一段"的
        # 场景名错位(重渲 clip_select 时尤其明显)。
        _os_scene_catalog = _one_shot_scene_catalog(global_prompt) if one_shot_enabled else []
        _os_scene_names = []
        # v14.363: 同时预扫每一段自己的行程(起行空间 → 过渡物 → 终止空间)
        _os_scene_routes = []
        if one_shot_enabled:
            for _osc_c in clips:
                try:
                    # v14.309: 场景名必须从**正文**里取。
                    # 段首已被 prepend 了参考图纪律 / 服装锁定纪律(v14.295 起 prepend),
                    # 两条纪律各含一个 <Picture N> —— _one_shot_scene_name 只扫首行,
                    # 于是只看得到纪律那一行, 解析失败返回 None, 导致 v14.294 的
                    # [同场景延续]/[空间过渡] 整场一次都不注入(实测日志里
                    # "v14.294 空间规则 = " 从未出现)。后果正是段内硬切: 段3 正文写
                    # "残晖"夕阳, 而段2 末帧已是"靛蓝天幕+第一颗星点"的夜景, 条件文本
                    # 与段首 motion context 关键帧冲突, 模型只能先拖旧画面再一帧硬切。
                    _osc_body = _strip_ref_rules(_osc_c.get("prompt", ""))
                    _os_scene_names.append(
                        _one_shot_scene_name(_osc_body, _os_scene_catalog)
                    )
                    try:
                        _os_scene_routes.append(
                            _one_shot_scene_route(_osc_body, _os_scene_catalog)
                        )
                    except Exception:
                        _os_scene_routes.append(
                            {"start": None, "end": None, "transit": None,
                             "cross": False, "route": ""}
                        )
                except Exception:
                    _os_scene_names.append(None)
                    _os_scene_routes.append(
                        {"start": None, "end": None, "transit": None,
                         "cross": False, "route": ""}
                    )
        if one_shot_enabled and _os_scene_catalog:
            print(f"[H3 Extender] v14.294 一镜到底: 场景清单 = {_os_scene_catalog}")
        if one_shot_enabled:
            for _osr_i, _osr in enumerate(_os_scene_routes):
                if _osr.get("start") or _osr.get("end"):
                    print(f"[H3 Extender] v14.363 一镜到底 clip[{_osr_i + 1}]: 行程 = "
                          f"{_osr.get('start')} → ({_osr.get('transit') or '无过渡物'}) → "
                          f"{_osr.get('end')}"
                          + ("（段中换场）" if _osr.get("cross") else "（单处空间）"))
        if one_shot_enabled:
            _os_env_continuity = (
                "\n[环境连续] 环境沿一条连续的物理路线逐步变化，每一处新环境都由"
                "画面内可见的过渡物引入并逐渐展开，光线与色温随之平滑推移，"
                "画面始终保持在同一片连续空间里。"
            )
            try:
                _os_locked_size = _one_shot_locked_size(global_prompt or "")
            except Exception:
                _os_locked_size = None
            print(f"[H3 Extender] v14.286 一镜到底: 景别策略 = "
                  f"{('全片锁死 ' + str(_os_locked_size)) if _os_locked_size else '段间连续(不锁死)'}; "
                  f"摄影机轨迹/主体步态将按同一规则注入每一段")
        # v14.240 (2026-10-28): 一镜到底 —— 强制全链同 seed（摄像机轨迹连续）。
        # 根因: 默认 seed_mode=randomize 每段独立随机噪声场, 即使段头锁 keep +
        # keyframe 参考把画面锚住, 段内中段的噪声路径仍逐段重启 → 运镜轨迹
        # 每段重新随机, 观感=段间"切镜"。官方 continuation 语义(单次生成 +
        # 22帧延续)天然同源; 链式方案必须同 seed 才能让噪声场跨段连续,
        # 摄像机运动(推/拉/摇/移)沿同一条轨迹自然延伸。
        if one_shot_enabled:
            try:
                _os_seed_fixed = None
                for _osc in clips[:loop_end]:
                    try:
                        _s0 = max(0, min(DEFAULT_SEED_MAX, int(_osc.get("seed", 0) or 0)))
                        if _os_seed_fixed is None:
                            _os_seed_fixed = _s0
                        _sm = str(_osc.get("seed_mode", "randomize"))
                        if _osc.get("seed") != _os_seed_fixed or _sm != "fixed":
                            _osc["seed"] = _os_seed_fixed
                            _osc["seed_mode"] = "fixed"
                            print(f"[H3 Extender] v14.240 一镜到底: clip seed 强制统一 = {_os_seed_fixed} (原 {_sm}), 噪声场跨段连续")
                    except Exception:
                        pass
            except Exception:
                pass
        # v14.193: 视觉锚点自动记录 —— 渲染前按故事顺序预提取每个分镜的
        # 全部可见视觉元素状态（来源 = 分镜正文, 与渲染提示词同源: 外部 prompt
        # 覆盖优先）。覆盖角色形象/外观/服装/服饰/发型/鞋帽/场景/道具/布景等
        # 所有可见元素。不读取任何手动输入（visual_anchor_notes 已移除），
        # 也不新增输入端口。
        _va_auto_states = []
        for _va_ci, _va_cfg in enumerate(clips):
            _va_src = str(_va_cfg.get("prompt") or "")
            if clip_ref_plans is not None and _va_ci < len(clip_ref_plans):
                _va_ov = (clip_ref_plans[_va_ci] or {}).get("clip_prompt")
                if _va_ov:
                    _va_src = str(_va_ov)
            _va_auto_states.append(_extract_visual_state(_va_src))
        for i, cfg in enumerate(clips[:loop_end]):
            # v2.68 fix: 渲染本 CLIP 之前先消费已完成的 async encode（预览实时推送）。
            _flush_pending_enc(paused_break)
            # v14.185 一镜到底采样纪律校验(首段打印一次) —— 按采样档分流。
            # 单采无缝档对齐 Motion Context V2 实测标准: turbo 蒸馏 LoRA + beta 调度
            # + 6-8 步; 蒸馏链 steps≥20 过采样会烧穿上下文一致性(历史诊断: 接缝
            # PSNR 18.95dB)。双采高清档保留旧 ≥20 校验(非蒸馏底模思路)。
            # steps/scheduler 由本节点 INPUT_TYPES 传入, 此处校验+显式警告, 不强制改写。
            if one_shot_enabled and i == 0:
                try:
                    _os_steps = int(steps)
                    _os_sched = str(scheduler)
                    if one_shot_single_pass:
                        if _os_steps >= 20:
                            print(
                                f"[H3 Extender] ⚠️ v14.185 一镜到底·单采: 当前 steps={_os_steps} ≥ 20 —— "
                                f"turbo 蒸馏链过采样会烧穿上下文一致性(接缝劣化), "
                                f"参考工作流标准为 6-8 步 + beta 调度器, 请降低步数后重渲。"
                            )
                        elif 6 <= _os_steps <= 8 and _os_sched == "beta":
                            print(f"[H3 Extender] ✅ v14.185 一镜到底·单采: steps={_os_steps} + beta 调度 (对齐 Motion Context V2 标准)")
                        else:
                            print(f"[H3 Extender] ℹ️ v14.185 一镜到底·单采: steps={_os_steps} scheduler={_os_sched} "
                                  f"(参考标准: 6-8 步 + beta; 低动态内容可 6 步, 高动态 8 步)")
                        if _os_sched != "beta":
                            print(f"[H3 Extender] ℹ️ v14.185 一镜到底·单采: 当前调度器={_os_sched}, 参考工作流标准为 beta(仅提示, 不强制)")
                    elif one_shot_dual_2k:
                        # v14.272: 2K 档配方已钉死(8+4/denoise 0.45/euler/shift 12-3),
                        # 这里只做校验与回报, 不改用户参数。
                        if _os_steps != 8 or int(refine_steps) != 4:
                            print(f"[H3 Extender] ⚠️ v14.272 一镜到底·2K双采: 当前一采 {_os_steps} 步 / 二采 {int(refine_steps)} 步, "
                                  f"该档配方为 8+4 (脚本已按配方改写, 若日志仍如此请反馈)")
                        if _os2k_skip_refine:
                            print(f"[H3 Extender] ⚠️ v14.346 一镜到底·2K双采: 一采 {int(steps)} 步, "
                                  f"二采已跳过(倍率=假倍率 x{float(refine_upscale_factor):.2f}, 几何未变), "
                                  f"输出 {resolved_width}x{resolved_height}")
                        else:
                            print(f"[H3 Extender] ✅ v14.272 一镜到底·2K双采: 一采 {int(steps)} 步 + 二采 {int(refine_steps)} 步 "
                                  f"(denoise {float(refine_denoise):.2f}), 二采倍率按单次采样 token 预算(<=350k)取, "
                                  f"整段一次采样不分块(v14.276 干净优先)")
                        if _os_sched != "beta":
                            print(f"[H3 Extender] ℹ️ v14.272 一镜到底·2K双采: 当前调度器={_os_sched}, "
                                  f"参考工作流标准为 beta(仅提示, 不强制)")
                    elif one_shot_seamless_dual:
                        # v14.215: 双采无缝档 = 蒸馏底模 8 步一采 + 4 步二采(不是老链的 >=20 步)
                        if _os_steps >= 20:
                            print(
                                f"[H3 Extender] ⚠️ v14.215 一镜到底·双采无缝: 当前 steps={_os_steps} >= 20 —— "
                                f"蒸馏底模过采样会烧穿上下文一致性, 推荐 8 步一采 + 4 步二采。"
                            )
                        else:
                            print(f"[H3 Extender] ✅ v14.215 一镜到底·双采无缝: 一采 steps={_os_steps} "
                                  f"+ 二采 {int(refine_steps)} 步 (denoise {float(refine_denoise):.2f}), "
                                  f"接缝锚点已修复(双采段头锁 keep 真正生效)")
                        if _os_sched != "beta":
                            print(f"[H3 Extender] ℹ️ v14.215 一镜到底·双采无缝: 当前调度器={_os_sched}, "
                                  f"参考工作流标准为 beta(仅提示, 不强制)")
                        if not bool(refine_enable):
                            print("[H3 Extender] ⚠️ v14.215 一镜到底·双采无缝: refine 开关当前是关闭的, "
                                  "二采不会跑(该档不自动改写 refine 开关), 请手动打开 refine 再重渲")
                    elif _os_steps < 20:
                        print(
                            f"[H3 Extender] ⚠️ v14.178 一镜到底·双采: 当前一采 steps={_os_steps} < 20 "
                            f"(官方链上建议 20-25; 音频 8 步最差/≥12 可用)。"
                            f"steps 由工作流节点参数控制, 无法自动强制, 请手动将采样步数提到 ≥20 后重渲。"
                        )
                    else:
                        print(f"[H3 Extender] ✅ v14.178 一镜到底·双采: 一采 steps={_os_steps} (≥20 达标)")
                except Exception:
                    pass
            # Clips with render_enabled=False are skipped entirely: they keep
            # their cached latent (if any) and are not re-rendered.  This lets
            # the user turn off generation for specific clips without removing
            # them from the sequence. CLIP 选择生成时，未选中的同样跳过（保留缓存）；
            # 选中集已在循环前（v2.63）强制 render_enabled=True，不受此条件影响。
            if not cfg.get("render_enabled", True) or (
                select_override is not None and i not in select_override
            ):
                current_manifest = _load_manifest_from_paths(data_path, manifest_path)
                existing_count = len(current_manifest.get("segments", [])) if current_manifest else 0
                if i < existing_count:
                    result = disk_join.join(
                        samples=None,
                        trim_frames=None,
                        validated=True,
                        run_mode=str(run_mode),
                        fps=float(FPS),
                        previous_cache=previous_handle,
                        unique_id=f"extender_{owner}",
                    )
                    previous_handle = result[0]
                    previous_proxy = result[1]
                    statuses.append(result[4])
                continue

            # Refresh manifest state every iteration because Disk Join can
            # truncate or append the physical chain.
            current_manifest = _load_manifest_from_paths(data_path, manifest_path)
            existing_count = len(current_manifest.get("segments", [])) if current_manifest else 0
            existing = i < existing_count

            if cfg["validated"]:
                if existing:
                    result = disk_join.join(
                        samples=None,
                        trim_frames=None,
                        validated=True,
                        run_mode=str(run_mode),
                        fps=float(FPS),
                        previous_cache=previous_handle,
                        unique_id=f"extender_{owner}",
                    )
                    previous_handle = result[0]
                    previous_proxy = result[1]
                    statuses.append(result[4])
                    continue
                if single_clip_replace:
                    # v2.66: per-clip 独立渲染——前置段磁盘无缓存时不补渲、不 join，
                    # 直接跳过，让选中 clip 从当前链末尾接续渲染（绝不回 clip1）。
                    print(f"[H3 Extender] v2.66 独立渲染跳过前置段 clip{i+1}: validated=True 但磁盘无缓存，不补渲，选中 clip 将接续现有链末尾")
                    continue
                # validated 标记与磁盘缓存不一致（缓存被清理或路径变更）：
                # 不能静默跳过，否则 H3 链断裂且最终无 cache handle，落入下方采样路径重渲本段。
                print(f"[H3 Extender] clip{i+1} 标记为 validated 但磁盘缓存缺失，自动改为重新渲染")

            # Any active clip is unvalidated. Make sure everything after it is
            # false in the serialized state as well.
            _send_extender_progress(
                owner,
                i,
                len(clips),
                "preparing",
                f"Preparing clip {i + 1}/{len(clips)}",
            )
            cfg["validated"] = False
            for j in range(i + 1, loop_end):
                clips[j]["validated"] = False

            # Per-CLIP reference selection: this shot only conditions on the
            # assets its own prompt (plus the global prompt's) references.
            # Assets referenced by other CLIPs never leak into this scene.
            _refs_for_clip = refs
            _clip_prompt_for_cond = str(cfg["prompt"] or "")
            _gp_for_cond = global_prompt
            if clip_ref_plans is not None:
                _plan = clip_ref_plans[i]
                _refs_for_clip = _plan["refs"]
                _clip_prompt_for_cond = _plan["clip_prompt"]
                _gp_for_cond = _plan["global_prompt"]
            # v14.286: 景别链必须在 **flatten 之前** 算。
            # flatten 会把拍段标签([镜头运动]/[景别/构图] 等)整体改写成连续散文,
            # 之后既分不清哪个景别词属于哪个拍段, 标题里的"目标景别"也会混进来
            # (段19 实测: 标题写"上升至大远景", 但起幅拍段是"中全景" —— 按正文
            #  首个景别词取会凭空造出一次 中全景→大远景 的跨档跳变)。
            _os_size_start, _os_size_end, _os_size_hits = (None, None, [])
            _os_size_reliable = False
            if one_shot_enabled:
                try:
                    _os_size_start, _os_size_end, _os_size_hits, _os_size_reliable = (
                        _one_shot_size_chain(_clip_prompt_for_cond)
                    )
                except Exception:
                    _os_size_start, _os_size_end, _os_size_hits = (None, None, [])
                    _os_size_reliable = False
            # v14.271 一镜到底: 编码前把"0-3秒/3-6秒"分拍式剧本改写为单镜头连续散文。
            # 分拍标签会被 H3 当成镜头切分点(实测 clip2 在 3.25s ≈ 3-6秒拍点硬切)。
            if one_shot_enabled:
                _os_demulti = _one_shot_demulti_shot(_clip_prompt_for_cond, label=f"clip{i+1}")
                # v14.319: 光影因果化 —— 光影小节里"无因的整体换色"(段2 的
                # "天际由橘红转暗橙")会被模型当成段内一次独立事件, 在段中某个
                # 任意时刻整体换一次色, 实测在段2 f47 读成切镜。这里把它改写成
                # 与上一段末帧衔接的连续推进; 其余小节逐字不动。
                if str(os.environ.get("BSAI_H3_LIGHT_CONTINUITY", "1")).strip() != "0":
                    try:
                        _os_relight = _one_shot_relight_global_tone(_os_demulti)
                        if _os_relight != _os_demulti:
                            print(f"[H3 Extender] v14.319 一镜到底 clip[{i+1}]: "
                                  f"光影小节里的无因整体换色已改写为连续推进")
                            _os_demulti = _os_relight
                    except Exception:
                        pass
                _os_flat = _one_shot_flatten_prompt(_os_demulti)
                if _os_flat != _clip_prompt_for_cond:
                    print(f"[H3 Extender] v14.271 一镜到底 clip[{i}]: 提示词已单镜头化(分拍时间标签→连续运镜陈述)")
                    _clip_prompt_for_cond = _os_flat
                # v14.378: 正文机位方向句**不再改写**(改写表已清空) —— 脚本原句
                # 「同一条轨迹、同速同向、正对正面」与本版 [空间过渡]/[取景连续] 的
                # 「机位与他同速同行、同距同高、正对正面」一致; 改写成"机位固定"会与
                # [取景连续] 自相矛盾, 实测出"地面不动 + 全靠变大"的滑行(用户判定倒着走)。
                try:
                    _os_nocam = _one_shot_neutralize_camera_dir(_clip_prompt_for_cond)
                    if _os_nocam != _clip_prompt_for_cond:
                        print(f"[H3 Extender] v14.378 一镜到底 clip[{i+1}]: "
                              f"正文机位方向句已改写为同速同行口径")
                        _clip_prompt_for_cond = _os_nocam
                except Exception as _nocam_e:
                    print(f"[H3 Extender] v14.378 一镜到底 clip[{i+1}]: 机位方向句处理失败({_nocam_e})")
                # v14.286: 用户**显式声明**全片景别时, 正文里的景别词必须同步改写成
                # 声明值 —— 否则正文写"中景"、锁定指令写"中全景", 两个相反指令同时
                # 出现, 模型只能折中, 观感上就是主体忽大忽小(另一种景别跳变)。
                if one_shot_enabled and _os_locked_size:
                    try:
                        _os_forced = _one_shot_force_size(_clip_prompt_for_cond, _os_locked_size)
                        if _os_forced != _clip_prompt_for_cond:
                            _clip_prompt_for_cond = _os_forced
                            print(f"[H3 Extender] v14.286 一镜到底 clip[{i+1}]: "
                                  f"正文景别词已统一改写为全片声明值 '{_os_locked_size}'")
                    except Exception:
                        pass
            # Determine ref_audio for this clip.
            # lip_audio 模式：lip_audio_segment 已注入 AV latent 锁定口型，
            # 不需要再作为 ref_block。全局 ref_audio（音色参考）保留为 ref_block。
            if lip_audio_segments is not None:
                if i >= len(lip_audio_segments) or lip_audio_segments[i] is None:
                    raise RuntimeError(
                        f"[H3 LipSync] clip[{i+1}] 缺少对口型音频段（共 {len(lip_audio_segments)} 段，"
                        f"当前 clip 索引 {i}）。请检查 lip_audio 时长是否覆盖全部 CLIP。"
                    )
                _clip_ref_audio = ref_audio  # 音色参考（可能为 None）
                _seg_dur = int(lip_audio_segments[i]["waveform"].shape[-1]) / float(lip_audio_segments[i]["sample_rate"])
                print(f"[H3 LipSync] clip[{i+1}] 对口型驱动音频段: {_seg_dur:.2f}s"
                      + (f"，音色参考: 已连接" if ref_audio is not None else ""))
            else:
                _clip_ref_audio = ref_audio

            ref_items, ref_blocks, active_picture_slots, _ref_cache_hit = _prepare_shared_refs_cached(
                vae,
                audio_vae,
                resolved_width,
                resolved_height,
                str(ref_image_size),
                _refs_for_clip,
                ref_audio=_clip_ref_audio,
                enable_cache=bool(ref_cache),
                cache_bias=_asset_paths_signature(resolved_img_paths) + f"|clip{i}",
            )
            if not _ref_cache_hit:
                print(f"[H3 Extender] _prepare_shared_refs: {len(ref_items)} ref_items, "
                      f"{len(ref_blocks)} ref_blocks, active_picture_slots={active_picture_slots}")

            frame_count = _duration_to_frames(cfg["duration"])
            # v14.341 视频角色替换+动作迁移: 每段固定 226 帧（5+17k 网格，教程默认档位），
            # 段头 22 帧是上一段段尾（重叠锁定续接），解码按 trim_frames 裁掉 →
            # 净推进 204 帧/段。这里必须显式覆盖上面的时长推导与 v14.177 的
            # "目标+context" 推导：22 帧重叠不是 17 的倍数，两者相加后再对齐会落到
            # 243/260 帧，成片每段会比计划长出 4~40 帧，接缝错位。
            _remix_seg = (
                _recast_plan["segments"].get(i)
                if (_recast_plan is not None and _recast_plan.get("pipeline") == "remix")
                else None
            )
            # v14.345: Viggle Remake 档 —— 每段固定 226 帧、0 重叠，源片逐段作 cond video
            _viggle_seg = (
                _recast_plan["segments"].get(i)
                if (_recast_plan is not None and _recast_plan.get("pipeline") == "viggle")
                else None
            )
            if _viggle_seg is not None:
                _vg_frames = int(
                    (_recast_plan.get("frames_by_clip") or {}).get(i)
                    or _VIGGLE_SEG_FRAMES)
                print(f"[H3 Viggle] clip[{i+1}] 帧数锁定 {frame_count} -> {_vg_frames} 帧 "
                      f"(17n+5 网格，0 重叠，源片整段作 cond video)")
                frame_count = _vg_frames
            if _remix_seg is not None:
                _remix_frames = int(
                    (_recast_plan.get("frames_by_clip") or {}).get(i)
                    or _recast_plan.get("seg_frames") or _REMIX_SEG_FRAMES)
                _remix_overlap = int(_recast_plan.get("overlap_frames") or _REMIX_OVERLAP_FRAMES)
                print(f"[H3 Remix] clip[{i+1}] 帧数锁定 {frame_count} -> {_remix_frames} 帧 "
                      f"(含段头 {_remix_overlap} 帧重叠，净输出 "
                      f"{_remix_frames - (_remix_overlap if i > 0 else 0)} 帧)")
                frame_count = _remix_frames
            # v14.177 (fix): 段间衔接断裂根治 —— 渲染帧数必须包含 motion context 帧。
            # 机制: 本段将应用 motion context 时 (i>0 且 context_enabled 且前段有缓存),
            # 模型输出开头的 context 帧是上一段尾画面的延续 (join 解码时按 trim_frames
            # 裁掉, 只保留本段新内容)。旧代码 frame_count 只按目标时长构造 (12s -> 294),
            # motion.apply 返回 trim=39 后被裁 -> 每段净输出 255 帧 = 10.63s < 目标 12s,
            # 段间断帧断音、总时长 804 < 864, 成片每段短 1.37s。
            # 修复: 渲染帧数 = 目标帧 + context 帧 (经 H3 grid %17==5 对齐, 所有
            # context 档 5/22/39/56 裁后净输出均为 289 帧 ≈ 12.04s, 与目标 12s 一致)。
            if (
                i > 0
                and cfg.get("context_enabled", True)
                and previous_proxy is not None
            ):
                try:
                    _ctx_frames = int(str(context_length))
                except (TypeError, ValueError):
                    _ctx_frames = 0
                if _ctx_frames > 0:
                    _tgt_raw = int(round(float(cfg["duration"]) * FPS))
                    frame_count = _align_frame_count(_tgt_raw + _ctx_frames)
                    print(
                        f"[H3 Extender] v14.177 段间衔接: clip[{i+1}] 渲染帧数 = "
                        f"目标 {_tgt_raw} + context {_ctx_frames} -> {frame_count} "
                        f"(解码裁 {_ctx_frames} 后净输出 ≈ {frame_count - _ctx_frames} 帧)"
                    )
            # Prepend global prompt if connected from an external node.
            # The [角色档案]/[道具档案]/[场景档案] inventories are stripped so
            # the render prompt only ever describes THIS CLIP's own content.
            effective_prompt = _clip_prompt_for_cond
            # v14.84 lip-audio: 只净化本段CLIP提示词(全局提示词不受影响),
            # 抹掉"闭嘴/不开口"类与音频冲突的口型指令, 口型完全由音频驱动。
            if lip_audio_segments is not None:
                _before = effective_prompt[:80]
                effective_prompt = _strip_singing_talk_descriptions(effective_prompt)
                if _before != effective_prompt[:80]:
                    print(f"[H3 LipSync]   clip[{i+1}] 提示词净化(去闭嘴指令): '{_before}' -> '{effective_prompt[:80]}'")
            if _gp_for_cond:
                gp = _strip_archive_sections(str(_gp_for_cond)).strip()
                # v14.271 一镜到底: 全局提示词同样单镜头化。它会被前置到每一段,
                # 里面若带"0-3秒"分拍标签或"不出现画面切换/绝不切换机位"这类
                # 否定式切镜词, 会同时污染全部 clip(H3 会把否定句当画面渲染)。
                if gp and one_shot_enabled:
                    # v14.284: 一镜到底 —— 全局提示词必须"去多镜头结构化"。
                    # 全局文本会被前置到**每一段**, 所以里面的分镜表/场景路线串
                    # 等于"在每一段里都放一份 19 镜分镜表", H3 必然在段内自己
                    # 切镜头(实测 clip2 3.25s 由堤岸叠化到老城街口)。
                    # 清完后再单镜头化(去分拍时间标签 + 去否定式切镜口号)。
                    gp = _one_shot_demulti_shot(gp, label="global")
                    gp = _one_shot_flatten_prompt(gp)
                    # v14.284: 被删掉的"场景串联"用一句正向的连续性陈述替代 ——
                    # 保留"环境沿路线渐变"的跨段衔接意图, 但不含任何分镜结构。
                    if _os_env_continuity:
                        gp = gp + "\n" + _os_env_continuity
                if gp:
                    effective_prompt = gp + "\n" + effective_prompt
            # v14.193: 视觉锚点自动注入（参考 B站短剧导演台 V9 BV1m2HK6DEPX）。
            # 在 effective_prompt 组装早期注入状态快照（global prompt 之后、本段内容
            # 与 lip-audio/一镜到底指令之前），让"延续已建立状态"指令优先被模型读到。
            # 快照内容 = 本分镜前全部已自动记录的全部可见视觉元素状态（自旧到新, 有界）。
            # v14.271 一镜到底: 跳过视觉锚点快照。快照会把**上一段正文**的机位、
            # 景别、光照、时间(如 clip1 的"中全景仰视/橙粉残阳")原样搬到本段,
            # 与本段"中景/暮色转蓝调夜景"直接冲突 —— H3 会把矛盾渲染成并集,
            # 表现为段内某个时刻画面突然跳到上一段的空间与光线(实测 clip2 3.16s
            # 仍是暖色残阳, 3.25s 才跳到蓝调夜景)。一镜到底的延续由 motion context
            # keyframe(上一段尾 latent) 保证, 不再需要文本锚点, 且文本锚点有害。
            _va_snap = None if one_shot_enabled else _build_visual_anchor_snapshot(_va_auto_states, i)
            # v14.269: 视觉锚点来自前序分镜正文, 会把上段的"不开口，嘴唇闭合"原样
            # 带进本段 —— 与 <Audio 1> 冲突。对口型模式下同样按分句删除,
            # 口型只由音频决定。
            if _va_snap and lip_audio_segments is not None:
                _va_snap = _strip_singing_talk_descriptions(_va_snap) or None
            if _va_snap:
                effective_prompt = str(effective_prompt) + _va_snap
                print(f"[H3 Extender] v14.193 视觉锚点 clip[{i + 1}]: 已注入状态快照（自动记录·全部可见元素·延续约束）")
            # v2.120 lip-audio: 强化音频驱动提示词。
            # 参考B站最佳实践: 提示词必须明确告诉模型"人物在跟着音频唱",
            # 否则模型可能 lip-sync to nothing 或乱张嘴。
            if lip_audio_segments is not None:
                _audio_tag = (
                    "\n<Audio 1> 是本段中主播正在说/唱的音频。"
                    "主播的嘴唇、舌头和下颌必须跟随<Audio 1>的语速与音节自然开合，"
                    "口型与音频精确同步，说话时面部表情随内容起伏。"
                    "只要主播出现在画面内，嘴唇就必须持续跟随<Audio 1>开合，"
                    "本段不存在闭嘴静止或只做表情不含口型的画面。"
                )
                if "<Audio 1>" not in effective_prompt:
                    effective_prompt = effective_prompt + _audio_tag
            # v14.271 一镜到底 —— 正向单镜头指令（合并旧 v14.158/v14.191/v14.241 模板）。
            # 旧模板反复写 "no cut / 禁止切镜 / 禁止转场 / 禁止叠化 / no dissolve"。
            # H3 在 CFG=1.0 下没有负向分支, 否定句会被当作画面内容渲染(社区
            # PROMPTING.md 结论), 实测反而诱发段内切镜。这里只描述"摄影机如何连续
            # 运动", 全文不含任何 cut/dissolve/转场/叠化/淡入淡出 词汇。
            if one_shot_enabled:
                _os_shot_words = ["特写", "近景", "中景", "全景", "远景", "中全景", "中近景",
                                  "推近", "拉远", "推镜", "拉镜", "close-up", "close up",
                                  "closeup", "zoom in", "zoom out", "wide shot",
                                  "close shot", "full shot"]
                # 只扫本段正文(剥掉参考图纪律/服装锁定纪律), 否则模板词会污染基准景别
                # 判定(v14.241 实机恒定输出"基准景别=特写", 与正文"中景"冲突)。
                _os_body = _strip_ref_rules(_clip_prompt_for_cond)
                _os_hit_words = [w for w in _os_shot_words if w in _os_body.lower()]
                # v14.286: 景别链已在 flatten 之前算好(见上), 这里直接用。
                _os_body_size = _os_size_start
                if _os_locked_size and _os_body_size and _os_body_size != _os_locked_size:
                    print(f"[H3 Extender] ⚠️ v14.286 一镜到底 clip[{i+1}]: 本段正文出现"
                          f"景别词'{_os_body_size}', 与全片声明景别'{_os_locked_size}'不一致 —— "
                          f"正文景别词已统一改写为声明值")
                # v14.301: 场景判定提前 —— [段首承接] 与 [One Continuous Take] 都要
                # 按"同场/换场"分流, 所以先算出 _os_space_kind。
                # v14.363: 场景判定改用「本段自己的行程」+ 接缝对比上一段**终点**。
                # 旧代码对比 _os_scene_names[i-1](上一段起点) -> 链式路线(Sk→S{k+1})下
                # "本段起点 vs 上段起点"永远不等, 每段都被判成换场, 描述的却是**上一段**
                # 的换场, 整体错位一段: 段1 拿不到空间规则走不出自己的空间; 段2 收到段1
                # 的换场并在段首补做 —— 实测就是 2.083s 那一帧硬切。
                _os_route = (_os_scene_routes[i] if i < len(_os_scene_routes) else None) or {}
                _os_route_end = _os_route.get("end")
                _os_route_transit = _os_route.get("transit")
                (_os_scene_name, _os_prev_scene,
                 _os_space_kind, _os_transit_site) = _one_shot_space_decision(
                    _os_scene_routes, i, _os_scene_names)
                if str(os.environ.get("BSAI_H3_SPACE_RULE", "1")).strip() == "0":
                    _os_space_kind, _os_transit_site = None, None
                # 空间绑定句: 同场景段**逐字沿用**原文(段1-3 等已渲好的段因此依然有效);
                # 换场段改说"同一次连续行走", 不把主体钉在同一片空间里。
                _os_space_clause = (
                    "主体始终处在同一片连续空间里。" if _os_space_kind != "空间过渡"
                    else "主体始终处在同一次连续行走之中。")
                _os_rule = (
                    "\n[One Continuous Take] 本段从头帧到尾帧只有一个镜头：摄影机沿一条"
                    "连续轨迹运动，提示词中先后出现的时间与运镜描述都是这条轨迹上依次"
                    "经过的阶段，画面随运镜逐帧连续变化，" + _os_space_clause +
                    "这些阶段由同一次连续运动连起来，每一步的机位、光线与姿态都是从上一步"
                    "的状态平滑变化过来的。"
                    "机位高度与镜头光轴只通过连续的推移、升降与环绕平滑改变，速度连贯地延续。"
                    "提示词若要求绕到侧后方、横移到四十五度、环绕或旋转到某一角度，这些方位"
                    "变化都由摄影机连续环绕或横移逐帧完成，镜头里能看见空间在逐渐转过去。"
                    "段头呼吸渐稳、微小动作自然承接(脚步延续、视线微调、姿态汇入正在进行"
                    "的动作)；段尾姿态预先摆向下一动作，使下一段从动作中途接上。"
                )
                # v14.289 (2026-11-03): 段首**画面级**承接声明 —— 补 [One Continuous Take]
                # 只讲"微小动作承接"的缺口。
                #
                # 实测证据 (用户 4 段一镜到底 MV, 1920x1088, ctx=22, 一采 latent 相位审计):
                #   一采 latent 相位离群度 (同相位中位数比) 的两个热点 =
                #     ① 段中锚帧位  clip4 out≈138 = 2.65× (全段最高)
                #                      clip2 out≈172 = 2.44×  clip3 out≈141 = 1.91×
                #     ② 段首 row7/8  clip2 out≈2   = 2.57×  clip3 out≈5  = 1.87×
                #   ① 由 v14.288 关闭段中锚帧解决; ② 是段首重建构图, 需要提示词层补一条
                #   **画面/机位/构图**层面的正向承接声明 —— 现有规则只约束了"呼吸/视线/
                #   姿态"这类微小动作, 画面层(主体在画幅中的位置与大小、摄影机从上一段
                #   末尾的位置与运动状态继续)是空白, 模型在段首头几帧就自行重建构图
                #   (实测 clip3 前 6 帧接住 c2 尾帧后于 f7 跳到中近景; clip4 f5-f8 双曝光
                #   溶解后才真正进入新场景)。
                #
                # 措辞纪律: 全为正向陈述; 不出现任何 cut/转场/叠化 词汇; 不出现否定句
                # (H3 在 CFG=1.0 下没有负向分支); 不写死具体景别数值(景别由脚本决定);
                # 允许场景随主体行走自然变化(段4 堤道→公路路口), 因此不写"同一片空间"。
                if _os_space_kind == "空间过渡" and _os_transit_site == "head":
                    # v14.301: 只有**接缝本身**换场时才把换场压进段首重叠区。
                    _os_rule += _OS_SPACE_TRANSIT_HEAD_RULE
                elif i == 0:
                    # v14.341: 段1 没有"上一段末帧", 旧的"直接接着上一段末帧往下拍"
                    # 对它是无源指令。
                    _os_rule += (
                        "\n[段首起幅] 本段的第一帧就是脚本起幅这一处空间的第一个画面："
                        "摄影机从脚本给定的取景开始，主体在画幅中的位置与大小从这一帧起"
                        "连续延续，整段只有同一次行走。"
                    )
                else:
                    _os_rule += (
                        "\n[段首承接] 本段的第一帧直接接着上一段末帧那一帧往下拍："
                        "同一时刻、同一段连续行走，主体在画幅中的位置与大小接着上一段末尾"
                        "往下延续，摄影机从上一段末尾所处的位置与运动状态继续它正在做的"
                        "运动；主体一路向前行走，脚下的路面与两侧景物在前进中连续地流过，"
                        "空间随着他的前进自然展开。"
                    )
                # v14.294: 空间延续 / 空间过渡 —— 压住"段内硬切 / 段内叠化"的共同
                # 根因(条件文本与段首 motion context 关键帧冲突)。
                #
                # 这里只补脚本没写、但一镜到底语义必须成立的那部分:
                #   同一处空间 -> 布局与光线从上一段末帧延续, 逐拍只推进一小步;
                #   换到另一处空间 -> 由主体走过去, 两处空间由同一条地面相连。
                # 方位/距离/景别/动作仍旧全部交给用户脚本。
                if _os_space_kind == "同场景延续":
                    _os_rule += _OS_SAME_SPACE_RULE
                elif _os_space_kind == "空间过渡" and _os_transit_site == "mid":
                    # v14.344/347: 段中换场 —— 换场落在段中跨过渡物处(第三到第六秒),
                    # 由过渡物整块遮挡完成置换; 起幅归属与"换场后只剩 end"钉死。
                    _os_rule += _one_shot_transit_mid_rule(
                        _os_scene_name, _os_route_end, _os_route_transit)
                    _os_rule += _one_shot_scene_anchor_mid_rule(
                        _os_scene_name, _os_route_end, _os_route_transit)
                elif _os_space_kind == "空间过渡":
                    _os_rule += _OS_SPACE_TRANSIT_RULE
                    _os_rule += _OS_SCENE_ANCHOR_RULE
                if _os_space_kind:
                    if _os_transit_site == "mid":
                        print(f"[H3 Extender] v14.363 一镜到底 clip[{i+1}]: 空间规则 = "
                              f"空间过渡 ({_os_scene_name} → {_os_route_end}), "
                              f"换场落在段中({_os_route_transit or '过渡物'})"
                              f"第三到第六秒之间, 由柱面整块盖住镜头完成置换")
                    else:
                        print(f"[H3 Extender] v14.301 一镜到底 clip[{i+1}]: 空间规则 = "
                              f"{_os_space_kind}"
                              + (f" ({_os_prev_scene} → {_os_scene_name})"
                                 if _os_prev_scene else ""))
                    if _os_space_kind == "空间过渡" and _os_transit_site != "mid":
                        print("[H3 Extender] v14.332 换场段: 换场已压入段首一瞬"
                              "(门墙遮挡置换), 段中不再出现第二处空间")
                # v14.292 (2026-11-03): 光影与构图分离 —— 光影描述只改光, 不改构图。
                #
                # 实测: clip2 f160 由"中近景(胸像)"硬切到"大远景剪影", 切点正好落在脚本第3拍
                # "背后靛蓝天幕渐透出第一颗星点, 发梢成为剪影边"—— 模型把这句读成
                # "要一个剪影构图", 为容纳天空把取景拉开。现有规则没声明"光影描述只改光",
                # 模型就有权借光线重排构图。
                if str(os.environ.get("BSAI_H3_LIGHT_COMPOSITION", "1")).strip() != "0":
                    _os_rule += _OS_LIGHT_COMPOSITION_RULE

                # v14.288 (2026-11-03): 摄影机轨迹规则 —— **去掉与脚本冲突的硬约束**。
                #
                # v14.284 原文写的是"机位固定在主体侧前方, 与主体保持同距同高、朝向一致…
                # 主体在画幅中的位置与大小全程稳定保持同一状态, 画面里只有背景随摄影机
                # 移动而缓慢流转"。这与用户脚本里大量存在的**绕行/环绕/推近**直接矛盾:
                #   段2 "由平视中景起, 绕行至侧后方并缓缓上升"
                #   段7 "由正侧方绕至侧后方" / 段18 "由低位中近景起, 绕至侧后方并持续拉远"
                #   几乎每段正文都还有"缓慢推近""景别自然收窄""后退拉远"。
                # 两个相反指令同时出现, 模型只能在中途选一个 —— 实测正是这样:
                #   clip1(段1, 不绕行) scene 分数表为空 → **零切镜**
                #   clip2(段2, 绕行至侧后方) **5.083s 切镜**(中景→中近景, 主体朝向翻转)
                # 段内硬切的位置与脚本要求绕行的拍段精确对应。
                #
                # 现在只保留"相对关系连续演进 + 主体朝行进方向前进"两条不与脚本冲突的
                # 正向约束(防倒走); 方位/距离/景别的具体变化交给脚本, 由 [One Continuous
                # Take] 里已有的"绕到侧后方…由摄影机连续环绕或横移逐帧完成"承接。
                _os_rule += (
                    "\n[摄影机轨迹锁定] 摄影机与主体的相对关系自始至终连续演进："
                    "机位的高度、朝向与距离随同一条轨迹平滑改变，主体在画幅中的位置与"
                    "大小随运镜连续变化；主体始终朝着行进方向前进，画面里能看见空间"
                    "在摄影机移动中逐渐转过去。"
                )
                # v14.286: 景别规则(段间连续 / 全片锁死) —— 单一真相源的纯函数。
                # 锁死分支下正文景别词已在 demulti 之后统一改写成声明值, 两者不再打架。
                # 只有**可靠**解析出景别链时才做接缝判定 —— 兜底的全文扫描分不清
                # 哪个景别词属于哪个拍段, 据此判定跨档会凭空造出不存在的跳变。
                # v14.332: 整段演唱(lip_audio 覆盖全段)时不写"推近后再推回" ——
                # 演唱段没有"唇形段落结束"这个时刻, 模型只会执行推近那一半。
                # 判定必须扫**原始分段正文**(cfg["prompt"])：demulti/flatten 已经把
                # 场景路线串里的"（【演唱中】·人声0:48.0起）"标记一并剥掉,
                # 扫 effective_prompt 会恒为 False —— v14.333 实机验证发现。
                _os_sing_src = str(cfg.get("prompt") or "")
                _os_full_sing = bool(
                    lip_audio_segments is not None
                    and "演唱中" in _os_sing_src
                    and "不唱" not in _os_sing_src
                    and "中途入唱" not in _os_sing_src
                )
                _os_size_rule, _os_seam_mismatch = _one_shot_size_rule(
                    _os_locked_size,
                    _os_prev_size_end if _os_size_reliable else None,
                    _os_size_start if _os_size_reliable else None,
                    full_sing=_os_full_sing,
                )
                _os_rule += _os_size_rule
                # v14.333: 打印判定结果, 便于实机核对(上一轮扫 effective_prompt 恒 False)
                if _os_locked_size:
                    print(f"[H3 Extender] v14.333 景别规则 clip[{i+1}]: 锁死={_os_locked_size}, "
                          f"整段演唱={_os_full_sing} → "
                          f"{'取景范围全程固定(不推近)' if _os_full_sing else '允许唇形推近再推回'}")
                # v14.292: 取景锚定 —— 把脚本给的景别写成显式边界。
                #
                # 实测: clip3 脚本写"下降回平视并推近", 模型一路推过头到"极端躯干特写(头都在画外)",
                # 停了约 9 秒后在 f210 一帧硬切回"桥上中景"。原因是现有[景别连续]只说了
                # "景别随摄影机连续变化", 没给边界 —— 推近可以无限推。
                #
                # 注意: 只在景别链**可靠**解析时使用; 用户显式声明全片景别(锁死分支)时不添加,
                # 避免与[景别锁定]重复。
                if (str(os.environ.get("BSAI_H3_SIZE_ANCHOR", "1")).strip() != "0"
                        and _os_size_reliable and not _os_locked_size):
                    _os_rule += _one_shot_size_anchor_rule(_os_size_start, _os_size_end)
                if _os_seam_mismatch:
                    print(f"[H3 Extender] ⚠️ v14.286 一镜到底 clip[{i+1}]: 接缝景别"
                          f"{_os_prev_size_end} → {_os_size_start} 不一致 —— "
                          f"已注入连续过渡声明")
                # 更新"上一段末帧景别"给下一段用(锁死模式 / 解析不可靠时不更新)
                if not _os_locked_size and _os_size_reliable and _os_size_end:
                    _os_prev_size_end = _os_size_end
                # v14.284: 主体步态锁定 —— 正面走法与背面走法必须一致, 杜绝"倒走"。
                _os_rule += (
                    "\n[主体步态] 主体以稳定连续的步频持续向前行进，双腿交替迈出完整"
                    "步幅，步幅与节奏自始至终保持一致，身体朝向与行进方向始终一致。"
                    "身体姿态随每一步自然演进，手臂、肩背与头部的动作都从上一步的状态"
                    "平滑变化过来。"
                )
                effective_prompt = str(effective_prompt) + _os_rule
                print(f"[H3 Extender] v14.271 一镜到底 clip[{i}]: 命中景别/推拉词 "
                      f"{_os_hit_words}, 景别策略={_os_locked_size or '段间连续'}, "
                      f"本段景别 {_os_size_start or '无'} → {_os_size_end or '无'}, "
                      f"已注入正向连续运镜指令(+连续运镜/段首承接/轨迹锁定/景别规则/步态锁定)")
                # v14.289: 把**真正拼进条件文本的整段规则**打进日志 —— 之前只打印
                # effective_prompt 的前 120 字符, 一镜到底注入的规则全在后面, 无法核对。
                # 规则里若混入切镜词汇或否定句, 这一行会直接暴露。
                print(f"[H3 Extender] v14.289 一镜到底 clip[{i}] 注入规则全文 "
                      f"(len={len(_os_rule)}): {_os_rule}")
            print(f"[H3 Extender] clip[{i}] effective_prompt: '{effective_prompt[:120]}'")
            # v1.21: 多 CLIP 连续渲染时，上一 CLIP 的 H3 主模型（~20GB）仍驻留显存，
            # 会挤占本 CLIP 的 TE 文本编码空间导致 OOM——先卸载全部模型释放显存。
            # v1.23: unload_all_models 走 detach 分支不释放 dynamic 显存（OOM 根因），
            # 改为 partially_unload(offload, 1e32) 强制 weights 回 CPU 真释放。
            if i > 0:
                try:
                    import comfy.model_management as _mm
                    import torch as _torch
                    for _lm in list(_mm.current_loaded_models):
                        try:
                            if _mp_has_ck_quant_weights(_lm.model):
                                # v2.121 (round4): 同 _make_ref2va_conditioning 预编码清扫,
                                # 量化模型直接摘除, 不走 partially_unload(共享权重卸不干净)。
                                try:
                                    _mm.current_loaded_models.remove(_lm)
                                except Exception:
                                    pass
                                continue
                            _lm.model.partially_unload(_lm.model.offload_device, 1e32)
                        except Exception:
                            pass
                    # v14.243 兜底: 若二采完成处未走到 delegate 缓存引用清除
                    # (异常/回退路径), 在下一 clip 一采前强制清除原 model 持有的
                    # non_dynamic_delegate_model(=delegate.model 强引用), 使
                    # delegate 的 GPU 量化权重可被 GC, 避免 clip2+ 一采全流式换页。
                    try:
                        for _lm243 in list(_mm.current_loaded_models):
                            _m243 = getattr(_lm243, "model", None)
                            if _m243 is not None and hasattr(_m243, "non_dynamic_delegate_model"):
                                _m243.non_dynamic_delegate_model = None
                                print("[H3 Extender] v14.243 兜底清除 delegate 缓存引用")
                    except Exception:
                        pass
                    _mm.soft_empty_cache(force=True)
                    _torch.cuda.synchronize()
                    _torch.cuda.empty_cache()
                    _a = _torch.cuda.memory_allocated() / 1024 ** 3
                    _r = _torch.cuda.memory_reserved() / 1024 ** 3
                    print(f"[H3 Extender] clip[{i}] 显存已释放：allocated={_a:.2f}GB reserved={_r:.2f}GB")
                except Exception as _me:
                    print(f"[H3 Extender] 显存清理失败(可忽略): {_me}")

                # v14.223 (2026-10-26): 采样前把已解码、待最终拼接的 out_images/out_audios
                # 中的 GPU 张量迁到 CPU，恢复 DiT 整块驻留所需的显存。
                # 根因: clip0 解码产出的 IMAGE(约5.76GB) 被 out_images 活引用驻留显存, 空缓存
                # 清不掉, 使 clip1+ 采样前 free 只剩 ~16GB, 装不下 H3 DiT 20.6GB → 触发
                # DynamicVRAM 逐层流式换页(600-900s/步); 首段无上段积累所以快(~70s/步)。
                # 迁移后 GPU 归零, clip1+ 采样恢复整块驻留(~100-200s/步)。最终 _concat_clip_av
                # 内部本就末尾 .cpu(), 对 CPU 输入安全。
                if (i > 0) and (out_images or out_audios):
                    try:
                        import torch as _t223
                        _moved223 = 0
                        for _oi223, _im223 in enumerate(out_images):
                            try:
                                if _im223 is not None and getattr(_im223, "is_cuda", False):
                                    out_images[_oi223] = _im223.detach().to("cpu")
                                    _moved223 += 1
                            except Exception:
                                pass
                        for _oa223 in out_audios:
                            try:
                                _w223 = _oa223.get("waveform") if isinstance(_oa223, dict) else None
                                if _w223 is not None and getattr(_w223, "is_cuda", False):
                                    _oa223["waveform"] = _w223.detach().to("cpu")
                                    _moved223 += 1
                            except Exception:
                                pass
                        if _moved223:
                            _t223.cuda.synchronize()
                            _t223.cuda.empty_cache()
                            print(f"[H3 Extender] v14.223 采样前已把 {_moved223} 个上段解码 GPU 张量迁出显存, 恢复 DiT 整块驻留", flush=True)
                    except Exception:
                        pass

            # v14.162 (2026-10-22 fix): 4090 clip3 CUDA launch failure 修复 ——
            # 等待上一段异步编码线程完全结束再进入本段 TE 文本编码。
            # 实机根因: clip2 的异步编码(后台线程: VAE decode + NVENC)在 clip3 的
            # _make_ref2va_conditioning → TE encode(14.9GB 全量驻留 + comfy_kitchen
            # 量化权重 cast)期间仍在抢占 GPU → CUDA 上下文损坏, 崩在 llama o_proj
            # 的 weight.clone()。修复: 每段 conditioning 前同步等待 pending 编码
            # 全部完成并消费(解码+落盘), 杜绝主线程采样与后台编码并发抢 GPU。
            if _pending_enc:
                try:
                    for _pev_done, _pej, _peg in _pending_enc:
                        _pev_done.wait()
                    _flush_pending_enc(False)
                    print(f"[H3 Extender] v14.162 已等待 {_pej + 1} 段异步编码完成(防 TE 并发抢 GPU)")
                except Exception as _pe_err:
                    print(f"[H3 Extender] v14.162 等待异步编码完成失败(可忽略): {_pe_err}")

            # v14.335 视频人物替换: 本段对应的源视频片段（无则按普通分镜渲染）
            # v14.341: remix 档同一套注入，但走 _remix_prompt 的"角色替换+动作迁移"纪律，
            # 并且掩码交给调用方关掉（见下方 subject_mask=False）。
            _recast_seg = (_recast_plan["segments"].get(i)
                           if (_recast_plan is not None) else None)
            _remix_this = bool(_recast_seg is not None and _remix_seg is not None)
            _viggle_this = bool(_recast_seg is not None and _viggle_seg is not None)
            globals()["_VIGGLE_ACTIVE"] = bool(_viggle_this)
            if not _viggle_this:
                globals()["_VIGGLE_RELEASE_POS"] = None
            _rp_clip_tag = ("H3 Viggle" if _viggle_this
                            else ("H3 Remix" if _remix_this else "H3 Recast"))
            if _recast_seg is not None:
                # 纪律块统一注入（保留用户自己写的"谁换成谁"），并摘掉 <Video N>
                # —— 源视频已作为 V2V latent 进入采样，再当参考视频会双重注入。
                effective_prompt = (
                    (_viggle_prompt if _viggle_this
                     else (_remix_prompt if _remix_this else _recast_prompt))
                    (effective_prompt))

            positive, latent = _make_ref2va_conditioning(
                clip,
                vae,
                effective_prompt,
                resolved_width,
                resolved_height,
                frame_count,
                ref_items,
                ref_blocks,
                active_picture_slots,
                semantic_bridge_pack=sb_pack,
            )

            # v14.335 视频人物替换: 把本段源画面 + 源原声编码进 AV latent（半重绘初始化）
            if _recast_seg is not None:
                try:
                    _rc_vz, _rc_az, _rc_info, _rc_subject_mask = _recast_build_av_latent(
                        vae,
                        audio_vae,
                        _recast_plan["path"],
                        float(_recast_seg[0]),
                        float(_recast_seg[1]),
                        resolved_width,
                        resolved_height,
                        frame_count,
                        ffmpeg=_find_ffmpeg(),
                        # v14.342/345: 人物替换锁背景(人物掩码)，只有"动作迁移"（提示词写新场景）
                        # 才全画幅重绘；判定只看**用户自己的分镜正文**（纪律块正文里带
                        # "全新场景"字样，用 effective_prompt 判定会一律误判成全画幅）。
                        # v14.345: 用循环里的原始分镜提示词 `_clip_prompt_for_cond` ——
                        # 这里的 `clip` 是节点输入的 CLIP 文本编码器，不是分镜字典。
                        subject_mask=((_remix_keep_background(
                            _clip_prompt_for_cond) if _remix_this
                            else (False if _viggle_this else True))),
                        with_audio=(_remix_lock_audio() if _remix_this else True),
                    )
                    _rc_samples = latent.get("samples")
                    if isinstance(_rc_samples, comfy.nested_tensor.NestedTensor):
                        _rc_vt, _rc_at = _rc_samples.tensors[0], _rc_samples.tensors[1]
                    else:
                        _rc_vt, _rc_at = _rc_samples, None
                    _rc_v = _rc_vz.to(device=_rc_vt.device, dtype=_rc_vt.dtype)
                    _rc_t_tgt = int(_rc_vt.shape[2])
                    _rc_t_have = int(_rc_v.shape[2])
                    if _rc_t_have != _rc_t_tgt:
                        if _rc_t_have > _rc_t_tgt:
                            _rc_v = _rc_v[:, :, :_rc_t_tgt]
                        else:
                            _rc_v = torch.cat(
                                [_rc_v,
                                 _rc_v[:, :, -1:].repeat(1, 1, _rc_t_tgt - _rc_t_have, 1, 1)],
                                dim=2)
                        print(f"[{_rp_clip_tag}] clip[{i+1}] 源 latent 时间行 {_rc_t_have} -> "
                              f"{_rc_t_tgt}（与本次 frame_count 对齐）")
                    # 人物掩码的时间行跟着一起对齐，否则 noise_mask 形状对不上
                    if _rc_subject_mask is not None:
                        _rc_m_t = int(_rc_subject_mask.shape[2])
                        if _rc_m_t != _rc_t_tgt:
                            if _rc_m_t > _rc_t_tgt:
                                _rc_subject_mask = _rc_subject_mask[:, :, :_rc_t_tgt]
                            else:
                                _rc_subject_mask = torch.cat(
                                    [_rc_subject_mask,
                                     _rc_subject_mask[:, :, -1:].repeat(
                                         1, 1, _rc_t_tgt - _rc_m_t, 1, 1)], dim=2)
                    _rc_hw_tgt = (int(_rc_vt.shape[3]), int(_rc_vt.shape[4]))
                    if (int(_rc_v.shape[3]), int(_rc_v.shape[4])) != _rc_hw_tgt:
                        raise RuntimeError(
                            f"源 latent 画布 {_rc_v.shape[3]}x{_rc_v.shape[4]} 与本次 "
                            f"{_rc_hw_tgt[0]}x{_rc_hw_tgt[1]} 不一致（画布分辨率被其它档改写？）")
                    if _rc_at is not None:
                        if _rc_az is not None:
                            _rc_a = _rc_az.to(device=_rc_at.device, dtype=_rc_at.dtype)
                            _rc_a_tgt = int(_rc_at.shape[-1])
                            _rc_a = _rc_a[..., :_rc_a_tgt]
                            if int(_rc_a.shape[-1]) < _rc_a_tgt:
                                _rc_a = torch.nn.functional.pad(
                                    _rc_a, (0, _rc_a_tgt - int(_rc_a.shape[-1])))
                            latent["samples"] = comfy.nested_tensor.NestedTensor(
                                (_rc_v, _rc_a))
                            # 视频：有人像掩码 → 只放开人物区（1）重绘，背景锁 0 保持源像素；
                            #       掩码失败 → 旧行为全 1。音频全 0 = 锁定源原声。
                            if _rc_subject_mask is not None:
                                _rc_vmask = _rc_subject_mask.expand_as(_rc_v).to(
                                    device=_rc_v.device, dtype=_rc_v.dtype).contiguous()
                            else:
                                _rc_vmask = torch.ones_like(_rc_v)
                            _rc_amask = torch.zeros_like(_rc_a)
                        else:
                            # 源视频无音轨 / 未接 audio_vae：音频区交还模型重生成
                            latent["samples"] = comfy.nested_tensor.NestedTensor(
                                (_rc_v, _rc_at))
                            if _rc_subject_mask is not None:
                                _rc_vmask = _rc_subject_mask.expand_as(_rc_v).to(
                                    device=_rc_v.device, dtype=_rc_v.dtype).contiguous()
                            else:
                                _rc_vmask = torch.ones_like(_rc_v)
                            _rc_amask = torch.ones_like(_rc_at)
                            print(f"[{_rp_clip_tag}] clip[{i+1}] ⚠️ 源视频无可用音轨或未接 "
                                  "audio_vae —— 音频改由模型重新生成（口型不再跟随源片）")
                    else:
                        latent["samples"] = _rc_v
                        if _rc_subject_mask is not None:
                            _rc_vmask = _rc_subject_mask.expand_as(_rc_v).to(
                                device=_rc_v.device, dtype=_rc_v.dtype).contiguous()
                        else:
                            _rc_vmask = torch.ones_like(_rc_v)
                        _rc_amask = None
                    if _rc_amask is not None:
                        latent["noise_mask"] = comfy.nested_tensor.NestedTensor(
                            (_rc_vmask, _rc_amask))
                    else:
                        latent["noise_mask"] = _rc_vmask
                    _rc_area = (float(_rc_vmask.mean()) if _rc_subject_mask is not None else 1.0)
                    print(f"[{_rp_clip_tag}] clip[{i+1}] 源画面/原声已灌入 AV latent: {_rc_info}; "
                          f"半重绘 denoise={float(denoise):.2f}; "
                          f"重绘区={'人物掩码 %.1f%%(背景锁源像素)' % (_rc_area * 100) if _rc_subject_mask is not None else '全画幅(背景会被重画)'}; "
                          f"源原声{'已锁定' if _rc_az is not None else '未锁定'}")
                    if _remix_this and _rc_subject_mask is None:
                        print(f"[{_rp_clip_tag}] clip[{i+1}] ⚠️ 本段按'动作迁移'(全画幅)走：提示词里"
                              "必须把新场景写清楚，否则背景会被模型自行重画；只想换人请删掉"
                              "场景类描述，或设 BSAI_H3_REMIX_KEEP_BG=1")
                    if _viggle_this:
                        # v14.345: 官方 Viggle Remake 契约 —— 与 Recast/Remix 的"半重绘"
                        # 相反：目标 latent 必须是**全噪**(视频 mask=1)，源片整段改作
                        # cond video 进条件(minimax_refs 首个 video block)，源原声仍锁
                        # clean(mask=0) → 6 步固定 sigma 全重绘，口型/动作/机位跟源片。
                        _vg_samples = latent.get("samples")
                        if isinstance(_vg_samples, comfy.nested_tensor.NestedTensor):
                            _vg_vt, _vg_at = _vg_samples.tensors[0], _vg_samples.tensors[1]
                        else:
                            _vg_vt, _vg_at = _vg_samples, None
                        _vg_v = torch.zeros_like(_vg_vt)
                        if _vg_at is not None:
                            latent["samples"] = comfy.nested_tensor.NestedTensor(
                                (_vg_v, _vg_at))
                            latent["noise_mask"] = comfy.nested_tensor.NestedTensor(
                                (torch.ones_like(_vg_v), torch.zeros_like(_vg_at)))
                        else:
                            latent["samples"] = _vg_v
                            latent["noise_mask"] = torch.ones_like(_vg_v)
                        # 源片 latent → cond video block（放在 minimax_refs 最前，
                        # 与官方 Viggle Remake Conditioning 的 cond_video_latents 同构）
                        try:
                            _vg_blocks = list(ref_blocks or [])
                            _vg_video_block = {
                                "kind": "video",
                                "latent_t": int(_rc_v.shape[2]),
                                "latent_h": int(_rc_v.shape[3]),
                                "latent_w": int(_rc_v.shape[4]),
                                "ref_audio_t": 0,
                                "latent": _rc_v,
                                # 官方新版对 source audio 做了去重：音频由 latent 的
                                # clean 音频行承担，cond video 不再带 audio_latent。
                                "audio_latent": None,
                            }
                            positive = node_helpers.conditioning_set_values(
                                positive, {"minimax_refs": [_vg_video_block] + _vg_blocks})
                            # v14.352: 同一份 positive 的"只留参考图"版本，供
                            # 采样后半程释放源片 cond 时直接换上。
                            try:
                                globals()["_VIGGLE_RELEASE_POS"] = node_helpers.conditioning_set_values(
                                    positive, {"minimax_refs": list(_vg_blocks)})
                                globals()["_VIGGLE_RELEASE_UNTIL"] = float(
                                    os.environ.get("BSAI_H3_VIGGLE_RELEASE_UNTIL", "0.9") or 0.9)
                            except Exception:
                                pass
                            globals()["_VIGGLE_ACTIVE"] = True
                            print(f"[H3 Viggle] clip[{i+1}] 源片已作 cond video 注入 "
                                  f"(latent {_vg_video_block['latent_t']}×"
                                  f"{_vg_video_block['latent_h']}×"
                                  f"{_vg_video_block['latent_w']}), "
                                  f"参考图 {len(_vg_blocks)} 个, 目标 latent 全噪, "
                                  f"音频行{'锁源原声' if _vg_at is not None else '交还模型'}")
                        except Exception as _vg_cond_err:
                            raise RuntimeError(
                                f"Viggle cond video 注入失败: {type(_vg_cond_err).__name__}: "
                                f"{_vg_cond_err}") from _vg_cond_err
                except Exception as _rc_err:
                    # v14.336: 本段替换不了就别渲 —— 静默当普通分镜渲出来的是"没替换的片子"，
                    # 用户要等十几分钟到出片才发现，代价比直接报错大得多。
                    raise RuntimeError(
                        f"[{_rp_clip_tag}] clip[{i+1}] 源片段编码/注入失败，本档中止"
                        "（不退回普通渲染）："
                        f"{type(_rc_err).__name__}: {_rc_err}") from _rc_err

            # v2.119: lip_audio 注入 AV latent 音频区 + zero-denoise 锁定
            # 参考 VRGDG Audio Drive: 把歌曲编码后直接塞进 latent 音频区,
            # 采样器无法修改它, 模型必须让画面配合已锁定的音频 → 真正对口型.
            if lip_audio_segments is not None and audio_vae is not None:
                try:
                    _lip_seg = lip_audio_segments[i]
                    _lip_wave = _lip_seg["waveform"]
                    _lip_sr = int(_lip_seg["sample_rate"])
                    _vae_sr = int(getattr(audio_vae, "audio_sample_rate", 32000))
                    if _lip_sr != _vae_sr:
                        _lip_wave = torchaudio.functional.resample(_lip_wave, _lip_sr, _vae_sr)
                    _lip_latent = audio_vae.encode(_lip_wave[:1].movedim(1, -1))
                    # latent["samples"] 是 NestedTensor((video, audio))
                    _samples = latent["samples"]
                    if isinstance(_samples, comfy.nested_tensor.NestedTensor):
                        _video_t, _audio_t = _samples.tensors[0], _samples.tensors[1]
                        # 对齐时间轴长度
                        # v2.122: 改为尾对齐注入。ctx_on 时段头部含 overlap_samples
                        # 重叠(上一段的歌), 旧的头对齐会把这段歌灌进本段音频区 →
                        # 口型整体提前 ~1.2s 错位。尾对齐使注入的本段 audio 行精确
                        # 对应[段起点, 段终点], 多余重叠头自动丢弃, 与解码混音的
                        # overlap 跳过互补; ctx_off(零重叠)时尾对齐==头对齐, 行为不变。
                        _t_target = int(min(_audio_t.shape[-1], _lip_latent.shape[-1]))
                        _lip_rows = int(_lip_latent.shape[-1])
                        if _lip_rows >= _t_target:
                            _lip_cut = _lip_latent[..., -_t_target:]
                        else:
                            _lip_cut = torch.nn.functional.pad(_lip_latent, (_t_target - _lip_rows, 0))
                        _audio_locked = _audio_t.clone()
                        _audio_locked[..., :_t_target] = _lip_cut.to(_audio_t.device)
                        latent["samples"] = comfy.nested_tensor.NestedTensor((_video_t, _audio_locked))
                        # noise_mask: video=1(全去噪), audio=0(锁定不修改)
                        # v14.178 一镜到底全球方案落地 P0-5: 已核对官方网格对齐 ——
                        # 视频 mask 与 video latent 同形状(采样器内部按 2×2 latent patch
                        # 上采样), 音频 mask 整 latent 帧 0=keep/1=regen; 现实现 audio 区
                        # 全 0(锁原音)、video 区全 1, 与官方语义一致, 无需改形状。
                        _vmask = torch.ones_like(_video_t)
                        _amask = torch.zeros_like(_audio_locked)
                        latent["noise_mask"] = comfy.nested_tensor.NestedTensor((_vmask, _amask))
                        print(f"[H3 LipSync]   音频已注入AV latent并锁定: "
                              f"audio_latent={tuple(_lip_latent.shape)}, "
                              f"video_denoise=1.0, audio_denoise=0.0")
                except Exception as _inject_err:
                    print(f"[H3 LipSync]   音频注入AV latent失败(回退参考模式): {_inject_err}")

            trim_frames = None
            # v1.14: previous_proxy 为 None（前段无缓存）时不再 raise，防御性跳过
            # motion context（从当前段独立渲染，链拼接由 disk_join 的 previous_cache 保证）。
            # v2.122: 解除 v2.117b 强制 — 对口型模式下"上下文参考"恢复用户手动控制。
            # ctx_on 时上一段尾部通过 motion context keyframes 注入(视频块+音频尾部),
            # 音频上下文终点精确对齐本段起点; 音频同步由三件套保证:
            #   1) _split_lip_audio_by_clips: ctx_on 段头部切 1.2s 重叠并记录 overlap_samples
            #   2) AV latent 音频注入: 尾对齐(本段行对应[起点,终点], 重叠头丢弃)
            #   3) 解码混音: 按 overlap_samples 跳过段头重叠 → 输出与原始歌曲逐帧对齐
            _applied_ctx = False
            if i > 0 and cfg.get("context_enabled", True) and previous_proxy is not None:
                positive, trim_frames, _, _, _ = motion.apply(
                    positive,
                    latent,
                    previous_proxy,
                    str(context_length),
                    int(audio_context_length),
                )
                _applied_ctx = True
                # v14.249 (S1): 一镜到底段中锚帧 —— 官方 AddGuide 任意帧语义
                # (ComfyUI PR #15439, FL2VA 官方模板即用 1.5s/3.0s/5.0s 多点钉帧)。
                # 调研报告 P0-2: 12s 段 T=87-92 逼近 H3 训练时序窗口上限
                # (124-362 帧), 中后段"长度外推退化"→ 模型重新构图自切。把上一段
                # 尾锚块(=全段基准构图, 与 v14.248 文本层基准景别锚定同向)钉在
                # 本段输出区中点(≈7s), 图像层强制模型中段经过基准构图, 直接对冲
                # 中段漂移。
                #
                # ══ v14.288 (2026-11-03): 默认改回【关闭】—— 实测证明它有害 ══
                # v14.284 把它从"默认关闭(需 BSAI_H3_MID_ANCHOR=1 显式开启)"改成了
                # 默认开启, 理由是"用户实测段内自切持续存在, 继续默认关闭等于不生效"。
                # **该判断错误** —— 本机制的真实副作用是破坏段间衔接, 代价远大于收益。
                #
                # 实测证据(用户 19 段一镜到底 MV, 2026-11-03, 1920x1088):
                #   1) 段间断裂: clip1 尾帧=近景(头胸入画), clip2 首帧=中全景(腰部以下),
                #      跨 2 档跳变、主体位置也变。链路 manifest 显示 trim_frames=22
                #      → motion context **本身是生效的**, 所以断裂不是 context 丢失。
                #   2) 段中硬切: clip2 在 **7.167s** 出现 scene score 0.52 的硬切,
                #      天空由晚霞突变到星夜 —— 7.167s 正好落在本锚帧的中点位置。
                #   3) 根因: 本锚帧往 **同一个 minimax_keyframes 列表**追加了第二份
                #      "上一段尾 latent"。context 已经在段首放了一份同样的 latent,
                #      两份"上一段尾"并存 → ①中点处画面被强行拉回上一段尾(硬切),
                #      ②模型把中点当成另一个段落边界, 时序规划被打乱, 段首重新构图
                #      (段间接不上)。脚本本身写的是"起幅承接上一段末帧的机位",
                #      段间景别 19/19 连续对接, 不需要这个锚。
                #
                # 结论: 段中锚帧与"段内景别持续推进"的脚本**天然冲突** —— 中点钉死
                # 上一段尾 = 强制画面回跳。默认关闭; 需要 A/B 时显式设
                # BSAI_H3_MID_ANCHOR=1 (开启会打印已知副作用警告)。
                try:
                    if (one_shot_enabled
                            and str(os.environ.get("BSAI_H3_MID_ANCHOR", "")).strip() == "1"):
                        print("[H3 Extender] ⚠️ v14.288 段中锚帧已启用(BSAI_H3_MID_ANCHOR=1) —— "
                              "已知副作用: 会在本段中点(≈7s)钉一份'上一段尾 latent', 实测会造成"
                              "①中点硬切 ②段间接不上(同一 keyframes 列表里出现两份上一段尾)。"
                              "若看到段内/段间异常, 请设 BSAI_H3_MID_ANCHOR=0 或直接移除该环境变量。")
                        _row_a = positive[0] if isinstance(positive, list) and positive else None
                        _dict_a = None
                        if isinstance(_row_a, (list, tuple)):
                            for _cell in _row_a:
                                if isinstance(_cell, dict) and "minimax_keyframes" in _cell:
                                    _dict_a = _cell
                                    break
                        elif isinstance(_row_a, dict) and "minimax_keyframes" in _row_a:
                            _dict_a = _row_a
                        if _dict_a is not None:
                            _kfs_a = _dict_a["minimax_keyframes"]
                            _src_kf = None
                            for _kf in reversed(_kfs_a):
                                if isinstance(_kf, dict) and _kf.get("latent") is not None:
                                    _src_kf = _kf
                                    break
                            if _src_kf is not None:
                                _out_frames = max(1, frame_count - int(trim_frames))
                                _mid_pixel = int(trim_frames) + _out_frames // 2
                                _mid_kf = dict(_src_kf)
                                _mid_kf.pop("audio_latent", None)
                                _mid_kf["resolved_frame_index"] = _mid_pixel
                                if MC_KEY in _mid_kf:
                                    _mid_kf[MC_KEY] = _mid_pixel
                                _dict_a["minimax_keyframes"] = list(_kfs_a) + [_mid_kf]
                                print(f"[H3 Extender] v14.249 一镜到底段中锚帧: clip[{i}] "
                                      f"基准构图钉在像素帧 {_mid_pixel} "
                                      f"(输出区中点, {frame_count - int(trim_frames)} 输出帧)")
                except Exception as _mid_err:
                    print(f"[H3 Extender] v14.249 段中锚帧失败(可忽略): {_mid_err}")
                # v14.219 (对齐 B 站教程 BV1fahB6XEKY《SelfLift双采_MotionContext
                # 上下文参考无限循环_一镜到底1080P直出狂飙版》): 教程核心方法之一
                # "给潜空间图像注入噪声"——原文: 通过给上文潜空间参考注入噪声,
                # "可以很好的改善后面视频的画质, 避免严重劣化……因为噪声的加入
                # 会引发采样的真实发生, 对画质进行修复"。
                # 我们现状: overlap 延续区(采样起点)已加 10% 噪声(v14.178/188),
                # 但 conditioning 的 minimax_keyframes(前文参考段)是干净复用上一段尾
                # latent —— 无限长链多次复用时纯复用会累积过度平滑/劣化。
                # 这里按教程精神给 keyframes 参考注入微噪(σ 比例自适应)。
                # 环境变量 BSAI_H3_CTX_NOISE=0.05(默认), 设 0 关闭; 不加参数端口。
                # v14.240 (fix): 一镜到底默认关闭微噪 —— 该微噪给 keyframes 参考
                # latent 注入 5%σ 随机扰动, 会让模型把段头参考"重新想象"成新画面,
                # 抵消锁 keep + 尾帧引导的延续效果(用户实测段间跳帧)。仅当用户
                # 显式设 BSAI_H3_CTX_NOISE 才启用; 分镜模式保持原默认 0.05。
                try:
                    _ctx_noise_env = os.environ.get("BSAI_H3_CTX_NOISE", None)
                    if _ctx_noise_env is None:
                        _ctx_noise = 0.0 if one_shot_enabled else 0.05
                    else:
                        _ctx_noise = float(_ctx_noise_env or 0.0)
                except (TypeError, ValueError):
                    _ctx_noise = 0.0 if one_shot_enabled else 0.05
                if _ctx_noise > 0.0:
                    try:
                        # ComfyUI conditioning = list[[cond_dict, extra]]; 兼容两种槽位
                        _row = positive[0] if isinstance(positive, list) and positive else None
                        _pos_dict = None
                        if isinstance(_row, (list, tuple)):
                            for _cell in _row:
                                if isinstance(_cell, dict) and "minimax_keyframes" in _cell:
                                    _pos_dict = _cell
                                    break
                        elif isinstance(_row, dict) and "minimax_keyframes" in _row:
                            _pos_dict = _row
                        if _pos_dict is not None:
                            _kfs = _pos_dict["minimax_keyframes"]
                            _new_kfs, _noised = [], 0
                            for _kf in _kfs:
                                _kl = _kf.get("latent") if isinstance(_kf, dict) else None
                                if _kl is None or not torch.is_tensor(_kl) or _kl.numel() == 0:
                                    _new_kfs.append(_kf)
                                    continue
                                _sig = float(_ctx_noise) * float(_kl.std().item())
                                _nkf = dict(_kf)
                                _nkf["latent"] = _kl + torch.randn_like(_kl) * _sig
                                _new_kfs.append(_nkf)
                                _noised += 1
                            if _noised:
                                _pos_dict["minimax_keyframes"] = _new_kfs
                                print(f"[H3 Extender] v14.219 上下文潜空间微噪(对齐 BV1fahB6XEKY): "
                                      f"clip[{i}] {_noised} 个 keyframe 注入 {float(_ctx_noise):.2f}σ 噪声, "
                                      f"防无限长链参考复用过度平滑/劣化; 设 BSAI_H3_CTX_NOISE=0 关闭")
                    except Exception as _ctx_err:
                        print(f"[H3 Extender] v14.219 keyframe 微噪失败(可忽略, 不影响渲染): {_ctx_err}")
                # v14.178 一镜到底全球方案落地 P0-3: 重叠区噪声延续(HR Endless
                # video_continuation=22 语义)。官方 AddGuide 是 conditioning 语义(采样
                # 仍从空 latent 起), 接缝区模型仍会"重新想象"(诊断: 接缝 PSNR 仅 18.95dB)。
                # 这里在 latent/noise 构造路径把本段头部 overlap 帧直接取上一段尾 latent
                # +10% 扰动, 并在 noise_mask 把视频头部锁 keep(0=不去噪), 使采样器不再
                # 重画接缝区(该区最终被 join trim 裁掉)。与 P0-2 keyframes 注入双保险。
                # v14.187 (fix): 重叠区噪声延续从"一镜到底"扩展到所有上下文衔接段(分镜模式)。
                # 根因: 分镜模式 clip2+ 头部 motion context 走 conditioning(keyframes) 语义,
                # 采样 latent 仍从空噪声起, 模型在接缝区"重新想象" → clip2 前 3~4s 渐进模糊
                # (实测 Laplacian 153 vs clip1 1034, 量化确认 clip2 独有)。锁 keep 上一段尾
                # latent 后, 采样器不再重画接缝区, 前几帧从上一段尾状态延续 → 输出清晰;
                # 被锁区最终仍由 join trim 裁掉, 不进入成片。
                # v14.188 (fix): 分镜模式(场景可跳变)改"渐进锁 keep"——均匀锁 keep 会把上一段
                # 尾画面(如主播直播)强锁到新场景(如蜡烛特写)头部, 输出区前几帧被迫从旧场景
                # 演化 → 过渡帧重影/一帧崩坏(实测: clip2 首帧=主播场景重影马赛克, Laplacian
                # 突变 diff=107)。改为 noise_mask 头部 0.0→1.0 线性渐降: 首步完全 keep(无缝
                # 进入), 逐步放开重绘, 模型前几步从上一段尾状态平滑转向新场景, trim 后输出
                # 区起点已是转向完成的画面(清晰新场景, 无重影)。一镜到底(连续镜头)保持均匀
                # 锁 keep(v14.178 已验证无缝)。
                try:
                    if trim_frames:
                        # v14.240 (fix): 帧→latent 行精确换算(H3 网格: 每 17 帧
                        # 5 行, 基底 5 帧/2 行)。旧公式 (trim+16)//17: trim=22 -> 2行
                        # (≈6.8帧), trim=39 -> 3行(≈10帧) —— 锁 keep 区只覆盖段头
                        # 1/3~1/4, 其余 trim 区模型"重新想象" → 段头画面不延续
                        # 上一段尾 → 段间跳帧。精确公式 trim>=5 ->
                        # ((trim-5)//17)*5+2: 22->7行(≈23帧), 39->12行(≈41帧),
                        # 覆盖整个 motion context trim 区, 采样器在段头严格从
                        # 上一段尾状态延续演化, 输出区起点自然衔接。
                        _trim_n = int(trim_frames)
                        if _trim_n >= 5:
                            _n_head = max(1, ((_trim_n - 5) // 17) * 5 + 2)
                            # v14.241 (fix): 锁区比 trim 区少 1 latent 行 —— 行粒度
                            # (≈3.4帧/行)使 7 行(≈23.8帧) > 22帧 trim, 残留 1~2 帧
                            # 锁区(双采档下为 2x->1x 缩小的 clip1 尾)成为输出首帧,
                            # 实测 clip2 首帧 lap_var=34.0 vs clip1 尾 43.7(模糊, 用户
                            # 反馈"clip2 首帧模糊成鬼样")。少锁 1 行后锁区(≈20.4帧)
                            # < trim(22帧), 残留区由模型在 mask 边界按锁区锚点画面
                            # 自然重绘(延续语义保留), 输出首帧锐利且画面连续。
                            _n_head = max(1, _n_head - 1)
                        else:
                            _n_head = 1
                        _prev_samples = previous_proxy.get("samples") if isinstance(previous_proxy, dict) else previous_proxy
                        _tail_v = None
                        if isinstance(_prev_samples, comfy.nested_tensor.NestedTensor):
                            _tail_v = _prev_samples.tensors[0]
                        elif isinstance(_prev_samples, (list, tuple)) and _prev_samples:
                            _last = _prev_samples[-1]
                            if isinstance(_last, dict) and isinstance(_last.get("samples"), comfy.nested_tensor.NestedTensor):
                                _tail_v = _last["samples"].tensors[0]
                        if _tail_v is not None:
                            _smp = latent["samples"]
                            if isinstance(_smp, comfy.nested_tensor.NestedTensor):
                                _vv, _aa = _smp.tensors[0], _smp.tensors[1]
                                _n_head = min(_n_head, _tail_v.shape[2], _vv.shape[2])
                                if _n_head >= 1:
                                    _vv2 = _vv.clone()
                                    _src = _tail_v[:, :, -_n_head:].to(_vv2.device, dtype=_vv2.dtype)
                                    # v14.215: 双采时"上一段尾 latent"是二采放大后的 2x,
                                    # 本段一采 latent 是 1x —— 直接赋值 shape 不匹配会抛异常,
                                    # 整块被 except 吞掉 → 噪声延续 + 段头锁 keep 全部失效 →
                                    # 裁掉重叠区后接缝处画面跳变(双采"接缝风险"的真根因)。
                                    # 这里把锚点按本段 latent 的空间尺寸重采样后再锁 keep,
                                    # 与 motion.apply 对 keyframe 的重采样口径保持一致。
                                    if tuple(_src.shape[-2:]) != tuple(_vv2.shape[-2:]):
                                        try:
                                            _src_r = _src
                                            if _src_r.dim() == 4:
                                                _src_r = _src_r.unsqueeze(0)
                                            _src_r = torch.nn.functional.interpolate(
                                                _src_r,
                                                size=(int(_src_r.shape[2]),
                                                      int(_vv2.shape[-2]),
                                                      int(_vv2.shape[-1])),
                                                mode="trilinear",
                                                align_corners=False,
                                            )
                                            if _src_r.dim() == 5:
                                                _src_r = _src_r.squeeze(0)
                                            _src = _src_r.to(_vv2.device, dtype=_vv2.dtype)
                                            print(f"[H3 Extender] v14.215 接缝锚点重采样: 上一段尾 latent "
                                                  f"{int(_tail_v.shape[-2]) * 16}x{int(_tail_v.shape[-1]) * 16} "
                                                  f"-> 本段 {int(_vv2.shape[-2]) * 16}x{int(_vv2.shape[-1]) * 16} "
                                                  f"(双采二采倍率所致, 已修正段头锁 keep)")
                                        except Exception as _rs_err:
                                            print(f"[H3 Extender] v14.215 接缝锚点重采样失败(可忽略): {_rs_err}")
                                            raise
                                    if one_shot_enabled:
                                        # v14.282 (fix, 2026-11-03): 一镜到底段头锁 keep 解冻
                                        # —— 实测 clip6+ 首帧与 clip5 完全相同(diff<4)。
                                        # 根因: v14.249 的"2%→8% 扰动 + 前 1/3 行 0.0 完全锁
                                        # keep + mask 0.1→1.0 缓坡"三重保险太激进:
                                        # 前 2 latent 行 timestep=0(永不重建), 扰动仅 2%
                                        # 导致 latent 几乎完全保留上段尾画面, 再叠加 motion
                                        # context 的 keyframe 锚点 + clip 统一 seed, 模型
                                        # 被锁死在上一段状态, 场景图(@图4→@图5)切换时无
                                        # 力响应 → 每段首帧冻结成同一画面。
                                        # 修复: ①扰动 2%→8% 凸形 提升到 8%→20%, 让 latent
                                        # 更多样化; ②noise_mask 前 1/3 行从 0.0(完全锁)
                                        # 改为 0.15(轻度锁), timestep 非零使模型可去噪;
                                        # ③渐变初值 0.1 提到 0.3, 更快放开。锁 keep 仍覆盖
                                        # trim 区前几帧(解码被裁), 但输出区首帧能自由演化。
                                        _wv = torch.linspace(
                                            0.0, 1.0, int(_n_head),
                                            device=_src.device, dtype=_src.dtype,
                                        ) ** 2
                                        _nw = (0.08 + 0.12 * _wv).view(
                                            1, 1, int(_n_head), 1, 1
                                        )
                                        _vv2[:, :, :_n_head] = (
                                            _src * (1.0 - _nw)
                                            + torch.randn_like(_src) * _nw
                                        )
                                    else:
                                        _vv2[:, :, :_n_head] = _src * 0.9 + torch.randn_like(_src) * 0.1
                                    latent["samples"] = comfy.nested_tensor.NestedTensor((_vv2, _aa))
                                    _m_old = latent.get("noise_mask")
                                    if isinstance(_m_old, comfy.nested_tensor.NestedTensor):
                                        _mv, _ma = _m_old.tensors[0], _m_old.tensors[1]
                                    else:
                                        _mv, _ma = torch.ones_like(_vv2), torch.ones_like(_aa)
                                    _mv = _mv.clone()
                                    if one_shot_enabled:
                                        # v14.282 (fix, 2026-11-03): noise_mask 解冻 ——
                                        # 前 1/3 行从 0.0(完全锁, timestep=0 永不重建) 改为
                                        # 0.15(轻度锁, timestep≈正常 15%), 让模型在锁区就有
                                        # 一定去噪自由度; 渐变从 0.3→1.0(t²) 而非 0.1→1.0,
                                        # 更快放开。根因: 全锁 + 弱扰动 + 统一 seed 把模型
                                        # 锁死在上一段尾帧, 场景切换时无法响应新 prompt/@图N。
                                        # 锁 keep 区仍覆盖 trim 前几帧(解码被裁), 输出区首帧
                                        # 能自由演化、画面不冻结。
                                        _n_locked_os = max(1, _n_head // 3)
                                        for _k in range(_n_head):
                                            if _k < _n_locked_os:
                                                _mv[:, :, _k] = 0.15
                                            else:
                                                _t = (_k - _n_locked_os) / max(
                                                    1, _n_head - _n_locked_os - 1
                                                )
                                                _mv[:, :, _k] = 0.3 + 0.7 * (_t * _t)
                                        _lock_desc = f"凸形渐变锁keep(前{_n_locked_os}行轻锁0.15→0.3→1.0·t²)"
                                    else:
                                        # 分镜模式(场景可跳变): 头部渐进锁 keep, 0.0→1.0
                                        # 线性渐降, 首步完全保持(无缝进入), 逐步放开重绘,
                                        # 前几步从上一段尾平滑转向新场景, 无重影/崩坏帧
                                        for _k in range(_n_head):
                                            _mv[:, :, _k] = _k / max(1, _n_head - 1)
                                        _lock_desc = "渐进锁keep(0→1)"
                                    latent["noise_mask"] = comfy.nested_tensor.NestedTensor((_mv, _ma))
                                    _mode_tag = "一镜到底" if one_shot_enabled else "分镜衔接"
                                    print(f"[H3 Extender] v14.188 {_mode_tag}: clip[{i+1}] 头部{trim_frames}帧({_n_head}步)"
                                          f"噪声从上一段尾latent延续(+{8 if one_shot_enabled else 10}%扰动), noise_mask {_lock_desc}")
                except Exception as _seed_err:
                    print(f"[H3 Extender] v14.188 重叠区噪声延续失败(可忽略, 回退纯采样): {_seed_err}")
                if lip_audio is not None:
                    print(f"[H3 LipSync] clip[{i}] 对口型+上下文参考: 前段尾部已注入, 音频重叠区解码时自动跳过(与原始歌曲对齐)")
            elif i > 0 and cfg.get("context_enabled", True) and lip_audio is not None and previous_proxy is None:
                print(f"[H3 LipSync] clip[{i}] 对口型+上下文参考: 前段缓存缺失, 本段独立渲染(trim=0)")
            # v2.117d/v2.122: 本段未应用 motion context 时显式 trim=0 —
            # 绝不能让 disk_join.join 回退默认 22 帧 trim(那会把 clip2+ 自己的
            # 开头裁掉 → 段与段之间累积出空白帧)。ctx_on 且 motion.apply 已执行
            # 时保留其返回的 trim(上下文帧数), 由 join 裁掉上下文头, 与音频
            # overlap 跳过互补对齐。
            # v14.200: 不再限定 lip_audio —— ref_audio(参考音频版)下 clip 关闭
            # context_enabled 时同样必须 trim=0, 否则 join 回退 22 帧, 硬切段
            # 开头 0.9s 会被静默裁掉。
            if not _applied_ctx:
                trim_frames = 0
            # v14.284 (2026-11-03): 一镜到底接缝健康检查。
            # 段间不切镜依赖"上一段尾 latent 锚定 + 段头锁 keep"。一旦
            # motion context 没应用上(前段磁盘缓存缺失/前段未落盘), 段头就没有
            # 任何延续锚点, 段间必然硬切 —— 而这条链路此前只有一行 "本段独立
            # 渲染" 的提示, 很容易被忽略。这里显式告警, 避免误判成"提示词问题"。
            if one_shot_enabled and i > 0 and not _applied_ctx:
                print(f"[H3 Extender] ⚠️ v14.284 一镜到底接缝告警: clip[{i+1}] 未应用 "
                      f"motion context (上一段尾 latent 不可用), 本段与上一段之间会出现"
                      f"硬切 —— 请确认上一段已成功采样并落盘到链路缓存。")

            _send_extender_progress(
                owner,
                i,
                len(clips),
                "sampling",
                f"Rendering clip {i + 1}/{len(clips)}",
            )

            try:
                _eff_refine = bool(refine_enable)
                # v14.185: 一镜到底·单采无缝 —— 链式 latent 不做二采重绘。
                # Motion Context V2 (BV1T9ho6HEKP) 实测: 双采 latent 续链在接缝
                # 产生像素漂移(段间模糊/抖动), 单采接缝干净(45s+ 零拼接痕迹)。
                if one_shot_enabled and _eff_refine:
                    if one_shot_single_pass:
                        _eff_refine = False
                        if not _os_pass_notice_done:
                            _os_pass_notice_done = True
                            print("[H3 Extender] 一镜到底·单采无缝：已跳过二采（refine），链式 latent 不重绘，"
                                  "接缝零漂移（对齐 Motion Context V2 单遍采样方案）；"
                                  "如需 2K/高清放大请改用「双采高清」档或分镜模式")
                    elif one_shot_dual_2k:
                        # v14.276: 2K 档二采照跑, 倍数按单次采样 token 预算取。
                        # v14.346: 但倍率被预算压成假倍率(几何未变)时不许照跑 ——
                        # 那条二采不含放大, 只有 4 步同分辨率重绘, 纯掉画质(见预算分支)。
                        if _os2k_skip_refine:
                            _eff_refine = False
                            if not _os_pass_notice_done:
                                _os_pass_notice_done = True
                                print("[H3 Extender] ✅ v14.346 一镜到底·2K双采：本次预算下二采"
                                      "没有任何几何放大(倍率=假倍率)，已跳过二采 —— 不再做同分辨率 "
                                      f"{int(refine_steps)} 步 denoise {float(refine_denoise):.2f} 重绘，"
                                      f"输出 = 一采 {int(steps)} 步画面({resolved_width}x{resolved_height})")
                                _send_extender_warning(
                                    owner,
                                    "One-shot 2K dual-pass had no upscale this run (the token "
                                    "budget collapsed the refine factor to x1.0x, geometry "
                                    "unchanged), so the refine pass was skipped: it would only "
                                    "re-denoise the same-resolution latent in 4 steps and smear "
                                    "the first pass. Output equals the 8-step first pass; enable "
                                    "upscale_final (realesr) for a real 2K master, or shorten each "
                                    "clip to <=8s to keep single-call tokens in the healthy zone.",
                                    clip_index=i,
                                )
                        elif not _os_pass_notice_done:
                            _os_pass_notice_done = True
                            print("[H3 Extender] ✅ 一镜到底·2K双采：二采照跑"
                                  f"(一采 {int(steps)} 步 + 二采 {int(refine_steps)} 步, denoise {float(refine_denoise):.2f})，"
                                  f"二采 latent 放大 x{float(refine_upscale_factor):.2f}(按 token 预算取, 整段一次采样)；"
                                  "接缝沿用 v14.215 双采段头锚点修复")
                    elif one_shot_seamless_dual:
                        # v14.215: 双采无缝档 —— 二采照跑(1采8步+2采4步), 接缝靠
                        # v14.215 的锚点重采样修复(段头锁 keep 真正生效)。
                        if not _os_pass_notice_done:
                            _os_pass_notice_done = True
                            print("[H3 Extender] ✅ 一镜到底·双采无缝(8+4)：二采照跑"
                                  f"(一采 {int(steps)} 步 + 二采 {int(refine_steps)} 步, denoise {float(refine_denoise):.2f})，"
                                  "v14.215 已修复双采段头锚点(上一段尾 latent 按本段尺寸重采样后再锁 keep)，"
                                  "接缝不再因锁 keep 失效而跳变")
                    elif not _os_pass_notice_done:
                        _os_pass_notice_done = True
                        print("[H3 Extender] v14.389 一镜到底·双采高清：二采开重绘 + 内容锁"
                              f"(denoise 夹到 {_FF_REFINE_LOCK_DENOISE:.2f}, 采样后过结构相似度闸门"
                              f" ≥{_FF_REFINE_CONTENT_MIN:.2f} 才保留), 不会重绘成别的画面")
                # v14.214 (2026-10-26): 采样前强制释放文本编码器(TE)显存 ——
                # 长链从第 2 段起 TE 常驻 8~15GB, 采样前 free 从 22GB 掉到 15GB;
                # 而 H3 DiT 权重 20.6GB 在 24GB 卡上必须走 DynamicVRAM 流式,
                # 余量不足时第一次 int8_linear 权重块 torch.empty 分配失败 →
                # "CUDA error: out of memory"(实测 19 段长链崩在第 2 段第 1 步)。
                # 现有两条释放逻辑都漏了 TE: comfy_kitchen 量化被跳过,
                # free_memory 又只能扫 current_loaded_models(v1.53 块已把 TE 摘除)。
                try:
                    _release_text_encoder(clip, tag=f"clip{i + 1}/{len(clips)}")
                except Exception as _te_rel_err:
                    print(f"[H3 Extender] v14.214 文本编码器释放异常(忽略): {_te_rel_err}")
                sampled = _sample_h3(
                    sampling_model,
                    positive,
                    latent,
                    cfg["seed"],
                    str(sampler_name),
                    str(scheduler),
                    int(steps),
                    float(denoise),
                    owner_id=owner,
                    clip_index=i,
                    refine_enable=_eff_refine,
                    refine_denoise=float(refine_denoise),
                    refine_steps=int(refine_steps),
                    refine_upscale_factor=float(refine_upscale_factor),
                    refine_upscaler_model=str(refine_upscaler_model),
                    refine_align_to=int(refine_align_to),
                    refine_audio_denoise=float(refine_audio_denoise),
                    dual_track_shift=dual_track_shift,
                    shift_video=shift_video,
                    shift_audio=shift_audio,
                    tst_enable=selflift_tst_enable,
                    tst_tau=selflift_tst_tau,
                    tiled_refine=bool(tiled_refine),
                    tile_count=int(tile_count),
                    tile_overlap=int(tile_overlap),
                    refine_mem_mode=("global" if refine_mem_global else "spatial"),
                    temporal_chunk_tokens=int(temporal_chunk_tokens),
                    temporal_overlap_tokens=int(temporal_overlap_tokens),
                    refine_single_pass=bool(one_shot_dual_2k),
                    refine_no_temp_chunk=bool(_rp_no_temp_chunk),
                    one_shot_trim_frames=int(trim_frames or 0),
                    omni_8step_mode=omni_8step_mode,
                    hyperflow_mode=bool(_rp_hyperflow),
                    honor_manual_steps=(str(speed_preset) == "custom"),
                    # v14.238 MiniMaxH3 Director 极速双采移植参数
                    refine_sampler=refine_sampler,
                    refine_sigmas=refine_sigmas,
                )
            except comfy.model_management.InterruptProcessingException:
                _send_extender_progress(
                    owner, i, len(clips), "aborted",
                    "用户终止：渲染已中止（已保留已生成 CLIP）",
                )
                print("[H3 Extender] 用户终止渲染，停止后续 CLIP")
                break

            _decode_native_hw = None
            if isinstance(sampled, dict):
                _decode_native_hw = sampled.pop("decode_native_hw", None)
            # v14.283 (2026-11-03): 每段 join 后立即 validated=True ——
            # 崩溃重跑时 extender 才能识别哪些段已采样、直接跳过。此前全部段
            # validated=False, 崩溃后重跑会从 clip1 重新采样所有 N 段(24min/段
            # × 9 段 = 216min 白费)。现在 join 成功即 commit validated:True,
            # 重跑 manifest 里每个有 latent 的段都会被识别为已完成 → 自动续渲
            # 只采剩下的段。
            result = disk_join.join(
                samples=sampled,
                trim_frames=trim_frames,
                validated=True,  # v14.283: 每段采完立即 commit
                run_mode=str(run_mode),
                fps=float(FPS),
                previous_cache=previous_handle,
                unique_id=f"extender_{owner}",
                decode_native_hw=_decode_native_hw,
            )
            previous_handle = result[0]
            previous_proxy = result[1]
            statuses.append(result[4])
            generated.append(i)

            # v2.66: 每段 commit 后滚动快照——崩溃/误删后最多丢最后一段，
            # 用户点「♻️ 恢复缓存」即可从 latest.snapshot 恢复并续渲。
            try:
                _snapshot_latest(data_path, manifest_path, reason=f"clip-{i+1}-committed")
            except Exception as _sl:
                print(f"[H3 Extender] per-clip 快照异常(可忽略): {_sl}")

            # Drop full sampled/conditioning references before the next clip.
            del sampled, positive, latent

            # 暂停渲染：当前CLIP生成完、下一个开始前——
            #   pause_enable=False：手动暂停键始终可用（用户点过「暂停」才等待）
            #   pause_enable=True ：每个CLIP生成完自动暂停等待（继续/仅当前/中止，无干预超时自动继续）
            if i < loop_end - 1:
                if int(pause_enable):
                    with _render_ctl_lock:
                        _ctl_now = _render_ctl.get(str(owner))
                        if _ctl_now is not None:
                            _ctl_now["state"] = "pause_requested"
                if not _maybe_pause_between(
                    owner, i, loop_end, len(clips), float(pause_timeout)
                ):
                    print(f"[H3 Extender] 渲染已暂停停止：保留已生成的 CLIP（共 {i + 1} 段），不自动合并")
                    paused_break = True
                    break
            # Decode this clip to MP4 so the frontend preview panel can play it
            # immediately without waiting for the Final Decode node.
            # v1.19: 暂停停止（paused_break）或单独生成（render_partial）时静默——跳过 preview 解码，
            # 只保留 latent 缓存，等待用户下一步（合并输出 / 全量渲染）。
            _preview_error = None
            print(f"[H3 Extender] DEBUG clip={i} paused_break={paused_break} render_partial={render_partial} output_image_audio={output_image_audio} loop_end={loop_end}")
            if not paused_break:
                try:
                    _send_extender_progress(
                        owner, i, len(clips), "decoding_preview",
                        f"Decoding preview for clip {i + 1}/{len(clips)}",
                    )
                    _ff = _find_ffmpeg()
                    # v2.75: 链结构自适应 - 前置有缓存时链是全局索引
                    # (segments[i]=clip[i+1]); 前置无缓存时(v2.66 接续链末尾)
                    # 链是局部链(segments[0]=clip[first_sel])。按磁盘链实际
                    # 长度判断, 否则 preview/MP4 会解码到错误段
                    # (如单独渲染 clip29 却输出 clip1 内容).
                    _seg_idx = i
                    if single_clip_replace and first_sel is not None and first_sel > 0:
                        try:
                            _seg_m = _load_manifest_from_paths(data_path, manifest_path)
                            _nseg = len(_seg_m.get("segments", [])) if _seg_m else 0
                        except Exception:
                            _nseg = 0
                        if _nseg <= (i - first_sel + 1) and _nseg < i + 1:
                            _seg_idx = i - first_sel
                    print(f"[H3 Extender] preview decode: clip={i} ffmpeg={_ff} vae={type(vae).__name__} audio_vae={type(audio_vae).__name__ if audio_vae else 'None'} seg_idx={_seg_idx}")
                    _lip_seg = None
                    if lip_audio_segments is not None and i < len(lip_audio_segments):
                        _lip_seg = lip_audio_segments[i]
                    _dec_res = _decode_single_clip_preview(
                        owner=owner,
                        clip_index=_seg_idx,
                        vae=vae,
                        audio_vae=audio_vae,
                        fps=float(FPS),
                        ffmpeg=_ff,
                        async_encode=True,
                        lip_audio_segment=_lip_seg,
                    )
                    if isinstance(_dec_res, dict) and _dec_res.get("async"):
                        _pending_enc.append((_dec_res["done_event"], _seg_idx, i))
                except Exception as _pv_err:
                    # Preview decode failure should never abort the main render loop.
                    _preview_error = str(_pv_err)
                    print(f"[H3 Extender] clip preview decode failed: {_pv_err}")
                    import traceback
                    traceback.print_exc()

            _send_extender_progress(
                owner,
                i,
                len(clips),
                "complete",
                f"Clip {i + 1}/{len(clips)} complete"
                + (f" (preview error: {_preview_error})" if _preview_error else ""),
            )

            # Each CLIP is decoded to IMAGE+AUDIO as soon as it finishes and
            # emitted before the next clip starts (streaming output).
            # v1.21: 单 clip 重渲染也执行 per-clip AV 解码，推送 WebSocket 给 BSAI Premiere Pro。
            # v1.70: AV 输出延后处理——encode 在后台线程, blob 落盘后输出才可读.
            # encode ~55s << 一采+二采 ~29min, 队列首项已完成的先输出(FIFO 保持
            # clip 序); 本段刚启动未完成的留到下段处理. 暂停停止时跳过输出.
            print(f"[H3 Extender] DEBUG AV decode clip={i} cond={not paused_break and int(output_image_audio)} pending={len(_pending_enc)}")
            # v2.68 fix: 统一走 _flush_pending_enc（循环体末尾也消费一次，兜底）
            _flush_pending_enc(paused_break)


        # All clips rendered; the last handle is the active cached prefix
        # expected by Final Decode.
        if previous_handle is None:
            # 循环内没有任何 clip 产出 cache handle：磁盘缓存为空，且所有 CLIP
            # 均被跳过（生成开关关闭，或不在 clip_select 选择范围内）。
            raise RuntimeError(
                "MiniMax H3 Extender: sequence produced no cache handle — "
                "磁盘缓存为空且所有 CLIP 均被跳过。请开启至少一个 CLIP 的生成开关，"
                "或调整 clip_select 范围后重试。"
            )

        # Restore saved tail latents after selective re-rendering.
        # This block is for legacy in-memory tail restore. In single-clip
        # replace mode, saved_tail is None (tail is on disk instead).
        if saved_tail is not None:
            print(f"[H3 Extender] per-clip replace: restoring {len(saved_tail)} tail clip(s)")
            restored_manifest = _restore_tail_latents(data_path, manifest_path, saved_tail)
            if restored_manifest is not None:
                manifest = restored_manifest
            m = _load_manifest_from_paths(data_path, manifest_path)
            if m is not None:
                segs = [dict(x) for x in m.get("segments", [])]
                changed = False
                for i in range(first_sel, min(len(clips), len(segs))):
                    if not bool(segs[i].get("validated", False)):
                        segs[i]["validated"] = True
                        changed = True
                    clips[i]["validated"] = True
                    clips[i]["replace_mode"] = False
                if changed:
                    m = dict(m)
                    m["segments"] = segs
                    m["build"] = BUILD
                    m["updated_at"] = time.time()
                    _write_json_atomic(manifest_path, m)

        # In single-clip replace mode, clear replace_mode flags and mark
        # the re-rendered clip as validated. Tail latents are on disk and
        # will be restored when user clicks "合并输出" (merge_output).
        if single_clip_replace:
            m = _load_manifest_from_paths(data_path, manifest_path)
            if m is not None:
                segs = [dict(x) for x in m.get("segments", [])]
                changed = False
                for i in range(min(len(clips), len(segs))):
                    if i in selected_set and not bool(segs[i].get("validated", False)):
                        segs[i]["validated"] = True
                        changed = True
                    if i in selected_set:
                        clips[i]["validated"] = True
                        clips[i]["replace_mode"] = False
                if changed:
                    m = dict(m)
                    m["segments"] = segs
                    m["build"] = BUILD
                    m["updated_at"] = time.time()
                    _write_json_atomic(manifest_path, m)

        # ── v1.12: 重渲染单个/多个 CLIP 后不再自动恢复尾部 + 自动合并 ──
        # 链已由主循环从选中段连续渲染到结束，直接标记完成、正常输出。
        auto_merged = False
        _was_single_replace = bool(single_clip_replace)
        if single_clip_replace:
            single_clip_replace = False
            # v2.66: 只清 replace_mode 开关，不把未渲染的前置段误标 validated=True。
            # 选中段已在上方标记 validated=True；其余段保持原状态，下次独立渲染 clipM
            # 时由 v2.66 跳过逻辑正确接续现有链末尾。
            for cfg in clips:
                cfg["replace_mode"] = False
            print("[H3 Extender] per-clip replace complete → 仅渲染选中 clip，已出预览，等待用户新指令（无自动合并）")

        final_manifest = _load_manifest_from_paths(data_path, manifest_path)
        # v1.99: 更新实际渲染过的 clip 的资产指纹基准——仅渲染过的更新,
        # 未渲染的保留旧指纹, 下次该 clip 引用的图变化仍能正确触发重渲。
        if final_manifest is not None and clip_asset_fps:
            try:
                _new_fps = list(final_manifest.get("clip_asset_fps") or [])
                while len(_new_fps) < len(clip_asset_fps):
                    _new_fps.append("")
                _fp_changed = False
                for _gi in generated:
                    if _gi < len(clip_asset_fps) and clip_asset_fps[_gi] and _new_fps[_gi] != clip_asset_fps[_gi]:
                        _new_fps[_gi] = clip_asset_fps[_gi]
                        _fp_changed = True
                if _fp_changed:
                    final_manifest = dict(final_manifest)
                    final_manifest["clip_asset_fps"] = _new_fps
                    if global_asset_fp:
                        final_manifest["global_asset_fp"] = global_asset_fp
                    final_manifest["updated_at"] = time.time()
                    _write_json_atomic(manifest_path, final_manifest)
            except Exception as _fp_err:
                print(f"[H3 Extender] v1.99 指纹基准写入失败: {_fp_err}")
        # Color grading is montage metadata only. Keep it attached to each cached
        # decoded segment without invalidating latents or validation state.
        if final_manifest is not None:
            color_segments = [dict(x) for x in final_manifest.get("segments", [])]
            color_changed = False
            for color_i, desc in enumerate(color_segments):
                if color_i >= len(clips):
                    break
                wanted = _normalize_color_adjustment(clips[color_i].get("color_adjustment"))
                if desc.get("color_adjustment") != wanted:
                    desc["color_adjustment"] = wanted
                    color_segments[color_i] = desc
                    color_changed = True
            if color_changed:
                final_manifest = dict(final_manifest)
                final_manifest["segments"] = color_segments
                final_manifest["updated_at"] = time.time()
                _write_json_atomic(manifest_path, final_manifest)

        final_cache_resolution = _resolution_from_manifest(final_manifest)
        cached_count = len(final_manifest.get("segments", []))
        validated_count = 0
        for desc in final_manifest.get("segments", []):
            if bool(desc.get("validated", False)):
                validated_count += 1
            else:
                break

        normalized_json = _state_json(clips, active_prompt_pack_signature)
        if resolution.get("mode") == "auto_from_ref" and resolution.get("guide_ref") is not None:
            resolution_text = (
                f"{resolved_width}x{resolved_height} from ref_{int(resolution['guide_ref'])} "
                f"@ {float(resolution['megapixels']):.2f}MP"
            )
        elif resolution.get("fallback"):
            resolution_text = f"{resolved_width}x{resolved_height} manual fallback (no image ref)"
        else:
            resolution_text = f"{resolved_width}x{resolved_height} manual"

        if resolution.get("cache_reset") and previous_cache_resolution:
            resolution_text += (
                f" | resolution changed from "
                f"{int(previous_cache_resolution['width'])}x{int(previous_cache_resolution['height'])}: cache restarted"
            )
        prompt_pack_text = ""
        if external_prompt_pack is not None:
            prompt_pack_text = (
                f" | prompt pack {len(external_prompt_pack.get('prompts') or [])}"
                + (" imported" if prompt_pack_imported else " linked")
            )
        clip_select_text = ""
        if auto_merged:
            replaced = ",".join(str(i + 1) for i in sorted(selected_set))
            clip_select_text = f" | regenerated {replaced} | auto-merged"
        elif single_clip_replace:
            replaced = ",".join(str(i + 1) for i in sorted(selected_set))
            clip_select_text = f" | regenerated {replaced} | pending merge"
        elif any_replace:
            replaced = ",".join(str(i + 1) for i in sorted(selected_set))
            clip_select_text = f" | replace {replaced}"
        disabled = [i + 1 for i, c in enumerate(clips) if not c.get("render_enabled", True)]
        if disabled:
            clip_select_text += f" | skip {','.join(str(n) for n in disabled)}"
        if select_override is not None:
            _sel_min = min(select_override)
            if set(select_override) == set(range(_sel_min, len(clips))):
                sel_list = f"{_sel_min + 1}-{len(clips)}"
            else:
                sel_list = ",".join(str(n) for n in sorted(n + 1 for n in select_override))
            clip_select_text += f" | clip_select {{{sel_list}}}"
        status = (
            f"{str(run_mode)} | {resolution_text} | refs {_reference_count(refs)} | cached {cached_count}/{len(clips)} | "
            f"validated {validated_count}{prompt_pack_text}{clip_select_text} | "
            + (
                "generated " + ",".join(str(i + 1) for i in generated)
                if generated
                else "disk only"
            )
        )
        cache_mb = _cache_size_mb(data_path, manifest_path)

        _send_extender_progress(
            owner,
            -1,
            len(clips),
            "idle",
            status,
        )
        _release_render_ctl(owner)

        # ── Direct video output (per_clip / merged / both) ──────────────
        # Skip output only when single-clip replace is still pending (tail
        # latents not yet restored). After auto-restore, single_clip_replace
        # is set to False so output proceeds normally.
        output_ui_videos = []
        # v1.13: 单独选择生成 / 重渲染 / 暂停停止后禁止自动合并输出（merged）。
        # 仅「全量渲染且未干预」才自动合成 merged.mp4；否则只保留 per-clip 片段，
        # 由用户手动点「合并输出」按钮合成。
        # v2.76: 独立渲染(single_clip_replace)完成后也禁止自动合并与一切视频输出,
        # 仅保留 latent 缓存+预览, 静默等待用户下一步指令(合并输出/续跑).
        suppress_auto_merge = bool(render_partial or paused_break or _was_single_replace)
        if suppress_auto_merge:
            print("[H3 Extender] 单独生成/暂停：跳过合并与一切视频输出，仅保留 latent 缓存，静默等待新指令（v1.18）")
        if str(output_mode) != "none" and final_manifest is not None and not single_clip_replace and not _was_single_replace:
            try:
                out_dir = Path(folder_paths.get_output_directory()).resolve()
            except Exception:
                out_dir = (Path.cwd() / "output").resolve()
            out_dir.mkdir(parents=True, exist_ok=True)
            prefix = _safe_name(str(filename_prefix or "H3_Extender"))
            segments_out = [dict(x) for x in final_manifest.get("segments", [])]
            ff = None
            try:
                ff = _find_ffmpeg()
            except Exception:
                ff = None

            want_per_clip = str(output_mode) in ("per_clip", "both") and not suppress_auto_merge
            want_merged = str(output_mode) in ("merged", "both") and not suppress_auto_merge
            # v14.340: FVSR 逐分镜修复结果复用表（si -> 修复后 mp4）
            _fvrs_cache = {}

            if want_per_clip:
                for si, seg in enumerate(segments_out):
                    blob = seg.get("decoded_mp4_blob")
                    if blob is None:
                        continue
                    clip_path = out_dir / f"{prefix}_clip{si + 1:02d}.mp4"
                    try:
                        _copy_blob_to_file(data_path, blob, clip_path)
                        # v14.83 per-clip 逐段超分（总开关 + CLIP 级三态优先）
                        if _ff_clip_upscale_enabled(seg, upscale_per_clip):
                            _ff_upscale_video_file(clip_path, _up_factor, _up_engine,
                                                   upscale_model, upscale_fp16,
                                                   upscale_tile, upscale_batch,
                                                   upscale_face_restore)
                        # v14.340: 音频引导人脸/嘴型修复（TaoMate-FVSR）
                        if face_fvrs_enabled:
                            _src_fv = _ff_fvrs_restore_clip(clip_path, float(FPS))
                            _fvrs_cache[si] = str(_src_fv)
                            if _src_fv and str(_src_fv) != str(clip_path) and os.path.isfile(str(_src_fv)):
                                try:
                                    shutil.copy2(_src_fv, clip_path)
                                except Exception as _e_fv:
                                    print(f"[H3 Extender] FVSR per-clip 回写失败: {_e_fv}")
                        item = _comfy_media_item(clip_path, float(FPS), "output")
                        output_ui_videos.append(item)
                        print(f"[H3 Extender] saved per-clip video: {clip_path}")
                    except Exception as _e:
                        print(f"[H3 Extender] failed to save clip {si+1}: {_e}")

            if want_merged and len(segments_out) > 0:
                # Build a concat list and merge all clip MP4s into one file
                temp_root = _ensure_cache_root()
                concat_list = temp_root / f"_concat_{owner}_{uuid.uuid4().hex[:8]}.txt"
                clip_paths = []
                for si, seg in enumerate(segments_out):
                    blob = seg.get("decoded_mp4_blob")
                    if blob is None:
                        continue
                    cp = temp_root / f"_mergeclip_{owner}_{si}_{uuid.uuid4().hex[:8]}.mp4"
                    try:
                        _copy_blob_to_file(data_path, blob, cp)
                        # v14.340: 复用 per-clip 已修复结果；否则对临时合并片段现场修复
                        if face_fvrs_enabled:
                            _src_fv = _fvrs_cache.get(si)
                            if not (_src_fv and os.path.isfile(str(_src_fv))):
                                _src_fv = _ff_fvrs_restore_clip(cp, float(FPS))
                            if _src_fv and str(_src_fv) != str(cp) and os.path.isfile(str(_src_fv)):
                                try:
                                    shutil.copy2(_src_fv, cp)
                                except Exception as _e_fv:
                                    print(f"[H3 Extender] FVSR merge-clip 复用失败: {_e_fv}")
                        clip_paths.append(cp)
                    except Exception:
                        pass

                if clip_paths:
                    with open(concat_list, "w", encoding="utf-8") as f:
                        for cp in clip_paths:
                            f.write(f"file '{cp.as_posix()}'\n")

                    merged_path = out_dir / f"{prefix}_merged.mp4"
                    if len(clip_paths) == 1:
                        shutil.copy2(clip_paths[0], merged_path)
                    elif ff:
                        # v14.158: 一镜到底旁支模式 —— 无缝 concat（零转场）。
                        # 段间连续性由 motion context（Add Guide 等效锚点）保证,
                        # 不再叠加 xfade 转场。
                        merge_log = temp_root / f"_merge_{owner}_{uuid.uuid4().hex[:8]}.log"
                        if one_shot_enabled:
                            _xcmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
                                     "-c:v", "libx264", "-preset", "fast", "-crf", "17",
                                     "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(merged_path)]
                            try:
                                with open(merge_log, "wb") as lf:
                                    subprocess.run(_xcmd, stdout=subprocess.DEVNULL, stderr=lf, check=True)
                                print(f"[H3 Extender] saved merged video (一镜到底无缝 concat, {len(clip_paths)} clips): {merged_path}")
                            except Exception as _e:
                                print(f"[H3 Extender] 一镜到底 seamless concat failed: {_e}")
                        else:
                            # v2.0: 链式 xfade 视频渐变 + acrossfade 音频渐变, N段通用
                            _xcmd, _durs = _ff_build_xfade_merge_cmd(ff, clip_paths, merged_path)
                            merge_log = temp_root / f"_merge_{owner}_{uuid.uuid4().hex[:8]}.log"
                            if _xcmd is not None:
                                try:
                                    with open(merge_log, "wb") as lf:
                                        subprocess.run(_xcmd, stdout=subprocess.DEVNULL, stderr=lf, check=True)
                                    print(f"[H3 Extender] saved merged video (xfade chain, {len(clip_paths)} clips): {merged_path}")
                                except Exception as _e:
                                    print(f"[H3 Extender] xfade chain failed, fallback concat: {_e}")
                                    _xcmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
                                             "-c:v", "libx264", "-preset", "fast", "-crf", "17",
                                             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(merged_path)]
                                    try:
                                        with open(merge_log, "wb") as lf:
                                            subprocess.run(_xcmd, stdout=subprocess.DEVNULL, stderr=lf, check=True)
                                        print(f"[H3 Extender] saved merged video (re-encoded concat): {merged_path}")
                                    except Exception as _e2:
                                        print(f"[H3 Extender] merged re-encode also failed: {_e2}")
                            else:
                                # clips too short for xfade → re-encode concat
                                _xcmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
                                         "-c:v", "libx264", "-preset", "fast", "-crf", "17",
                                         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(merged_path)]
                                try:
                                    with open(merge_log, "wb") as lf:
                                        subprocess.run(_xcmd, stdout=subprocess.DEVNULL, stderr=lf, check=True)
                                    print(f"[H3 Extender] saved merged video (re-encoded concat): {merged_path}")
                                except Exception as _e:
                                    print(f"[H3 Extender] merged failed: {_e}")
                    else:
                        shutil.copy2(clip_paths[0], merged_path)

                    if merged_path.exists():
                        # v14.83 全片合并后一次性超分（默认关）
                        if upscale_final:
                            _ff_upscale_video_file(merged_path, _up_factor, _up_engine,
                                                   upscale_model, upscale_fp16,
                                                   upscale_tile, upscale_batch,
                                                   upscale_face_restore)
                        item = _comfy_media_item(merged_path, float(FPS), "output")
                        output_ui_videos.append(item)

                    # Clean up temp files
                    for cp in clip_paths:
                        try:
                            cp.unlink()
                        except Exception:
                            pass
                    try:
                        concat_list.unlink()
                    except Exception:
                        pass

            if output_ui_videos:
                status += f" | saved {len(output_ui_videos)} video(s) to output"

        ui_state = {
            "clips_json": normalized_json,
            "clip_count": len(clips),
            "cached_count": cached_count,
            "validated_count": validated_count,
            "generated": [i + 1 for i in generated],
            "status": status,
            "resolved_width": resolved_width,
            "resolved_height": resolved_height,
            "resolution_mode": str(resolution.get("mode") or "manual"),
            "resolution_guide": (
                f"ref_{int(resolution['guide_ref'])}"
                if resolution.get("guide_ref") is not None
                else ""
            ),
            "resolution_guide_width": int(resolution.get("guide_src_width", 0) or 0),
            "resolution_guide_height": int(resolution.get("guide_src_height", 0) or 0),
            "resolution_fallback": bool(resolution.get("fallback", False)),
            "megapixels": float(resolution.get("megapixels", megapixels)),
            "cache_width": int(final_cache_resolution["width"]) if final_cache_resolution else 0,
            "cache_height": int(final_cache_resolution["height"]) if final_cache_resolution else 0,
            "resolution_mismatch": False,
            "resolution_cache_locked": False,
            "resolution_cache_reset": bool(resolution.get("cache_reset", False)),
            "reference_cache_reset": False,
            "reference_count": int(_reference_count(refs)),
            "refs_json": _refs_json(refs),
            "requested_width": int(resolution.get("requested_width", resolved_width)),
            "requested_height": int(resolution.get("requested_height", resolved_height)),
            "prompt_pack_connected": external_prompt_pack is not None,
            "prompt_pack_imported": bool(prompt_pack_imported),
            "prompt_pack_count": int(len(external_prompt_pack.get("prompts") or [])) if external_prompt_pack is not None else 0,
            "prompt_pack_signature": str(active_prompt_pack_signature or ""),
            "global_prompt_connected": bool(prompt_source),
            "global_prompt_value": str(global_prompt or "")[:200],
            "prompt_source_connected": bool(prompt_source),
            "prompt_source_value": str(prompt_source or "")[:200],
            "asset_library_connected": bool(asset_library),
            "asset_image_count": len(resolved_img_paths) if 'resolved_img_paths' in locals() else 0,
            "build": BUILD,
            "restore_cache_done": bool(restore_cache_done),
        }

        ui_payload = {"h3_extender_state": [ui_state]}
        if output_ui_videos:
            ui_payload["h3_video"] = output_ui_videos

        if previous_handle and isinstance(previous_handle, dict):
            print(f"[H3 Extender] RETURNING cache handle: nonce={previous_handle.get('exec_nonce','N/A')} run_token={previous_handle.get('run_token','N/A')} next_index={previous_handle.get('next_index','N/A')}")

        # ── Extract per-clip preview MP4 files for BSAI Premiere Pro ──
        # Each clip's decoded MP4 blob is extracted from the .h3cache data
        # file to a standalone MP4 in ComfyUI's temp directory. The file
        # paths + metadata are returned as a JSON string so the Premiere
        # Pro node can add them to its timeline.
        # v14.302: clip_videos 提取(以及后续合并)之前必须先等待所有异步编码落盘。
        # 旧顺序里提取循环跑在 _pending_enc 等待之前：末段的 mp4 还在后台编码，
        # seg["decoded_mp4_blob"] 仍是 None → "segment N has no decoded blob, skipping"，
        # 结果最后一段既不进合成视频也不进 Premiere 时间线(实测 4 段只出 3 段)。
        _enc_waited = False
        for _enc_entry in _pending_enc:
            try:
                _enc_entry[0].wait(timeout=600)
            except Exception:
                pass
            _enc_waited = True
        _pending_enc = []
        if _enc_waited:
            print("[H3 Extender] v14.302 已等待全部异步编码落盘(clip_videos 提取前)")

        clip_videos_json = "[]"
        # v1.18: 单独生成/暂停后静默，不提取 clip_videos（等用户后续合并输出/全量渲染）。
        if not suppress_auto_merge:
            try:
                final_manifest = _load_manifest_from_paths(data_path, manifest_path)
                if final_manifest and final_manifest.get("segments"):
                    segments = [dict(x) for x in final_manifest["segments"]]
                    root = _ensure_cache_root()
                    import folder_paths as _fp
                    temp_dir = _clip_output_dir()
                    clips_info = []
                    for si, seg in enumerate(segments):
                        blob = seg.get("decoded_mp4_blob")
                        if blob is None:
                            print(f"[H3 Extender] clip_videos: segment {si} has no decoded blob, skipping")
                            continue
                        clip_name = clips[si].get("name", f"CLIP{si+1}") if si < len(clips) else f"CLIP{si+1}"
                        out_name = f"h3_clip_{owner}_{si+1}_{int(time.time())}.mp4"
                        out_path = temp_dir / out_name
                        _copy_blob_to_file(data_path, blob, out_path)
                        trim = int(seg.get("trim_frames", 0)) if si > 0 else 0
                        total_frames = int(seg.get("frames", 0))
                        out_frames = total_frames - trim
                        clip_fps = float(final_manifest.get("fps", FPS))
                        duration = float(out_frames) / clip_fps if clip_fps > 0 else 0.0
                        has_audio = bool(seg.get("decoded_mp4_has_audio", False))
                        w = int(seg.get("width", resolved_width))
                        h = int(seg.get("height", resolved_height))
                        clips_info.append({
                            "clip_index": si,
                            "clip_name": clip_name,
                            "file_path": str(out_path),
                            "file_name": out_name,
                            "duration": round(duration, 3),
                            "width": w,
                            "height": h,
                            "fps": clip_fps,
                            "has_audio": has_audio,
                            "frames": out_frames,
                        })
                        print(f"[H3 Extender] clip_videos: extracted clip {si+1} -> {out_path} ({out_frames} frames, {duration:.1f}s)")
                        # v14.355: 双保险第二道 —— 开了才跑，产物 <原名>_faceswap.mp4
                        if _viggle_faceswap_on:
                            try:
                                _fs_ref = str(os.environ.get("BSAI_H3_VIGGLE_FACESWAP_REF", "") or "")
                                if not _fs_ref:
                                    _fs_imgs = (asset_library or {}).get("images") or []
                                    if _fs_imgs:
                                        _fs_ref = str(_fs_imgs[0].get("path") or _fs_imgs[0].get("filename") or "")
                                _fs_out = _viggle_faceswap_clip(
                                    str(out_path), _viggle_faceswap_model, _fs_ref or None,
                                    tag=f"clip{si+1}")
                                if os.path.isfile(_fs_out) and str(_fs_out) != str(out_path):
                                    out_path = _fs_out
                                    clips_info[-1]["file_path"] = str(out_path)
                                    clips_info[-1]["file_name"] = os.path.basename(str(out_path))
                                    clips_info[-1]["faceswap"] = True
                            except Exception as _fs_err:
                                print(f"[H3 Viggle] v14.355 换脸工序异常(保留原片): {_fs_err}")

                    clip_videos_json = json.dumps(clips_info, ensure_ascii=False)
                    print(f"[H3 Extender] clip_videos: {len(clips_info)} clip(s) ready for Premiere Pro")
            except Exception as _cv_err:
                print(f"[H3 Extender] clip_videos extraction failed: {_cv_err}")
                import traceback
                traceback.print_exc()

        # Decode any validated (cached, not re-generated) clips so the
        # v1.70: 等待所有 async encode 完成(blob 落盘), final AV 输出才能读全.
        # v14.302: 该等待已上移到 clip_videos 提取之前(见 _enc_waited), 此处不再重复。
        _pending_enc = []

        # IMAGE/AUDIO outputs always carry the complete film.
        # v1.18: render_partial 静默，跳过 AV 汇总解码。
        if int(output_image_audio) and not suppress_auto_merge:
            try:
                final_m = _load_manifest_from_paths(data_path, manifest_path)
                if final_m is not None:
                    segs = [dict(x) for x in final_m.get("segments", [])]
                    for ci in range(len(segs)):
                        if ci in _av_decoded:
                            continue
                        cimg, caud = _decode_clip_to_av(owner, ci, vae, audio_vae, float(FPS))
                        if cimg is not None and int(cimg.shape[0]) > 0:
                            # v14.223b: 与主循环迁移一致——补录 decode 产出的 GPU 张量也统一
                            # 迁 CPU, 避免与先前已迁 CPU 的 out_images 混合设备, 使 concat 处
                            # torch.cat(imgs) 因跨设备抛错(concat 内部本就末尾 .cpu(), 迁后安全)。
                            try:
                                if getattr(cimg, "is_cuda", False):
                                    cimg = cimg.detach().to("cpu")
                            except Exception:
                                pass
                            # v14.330: 同样走预算化累积
                            _av_acc_push(out_images, cimg, _av_acc_state, _av_acc_budget)
                        if caud is not None:
                            try:
                                _cw = caud.get("waveform") if isinstance(caud, dict) else None
                                if _cw is not None and getattr(_cw, "is_cuda", False):
                                    caud = dict(caud)
                                    caud["waveform"] = _cw.detach().to("cpu")
                            except Exception:
                                pass
                            out_audios.append(caud)
            except Exception as _av2:
                print(f"[H3 Extender] cached-clip AV decode failed: {_av2}")

        # v14.223: 采样前曾把 out_images 迁到 CPU 释放显存给 DiT; 小脸修复在 GPU 上算,
        # 这里把需要处理的张量迁回 GPU。face_refine 是可选档(需 BSAI-ComfyUI-FaceRefine),
        # 用不上时 CPU 张量直接喂 _concat_clip_av(.cpu() 安全)。
        if face_refine_enabled and len(out_images) > 0:
            try:
                import torch as _t223b
                _dev223 = _t223b.cuda.current_device()
                out_images = [
                    (
                        (im.to(_dev223) if not getattr(im, "is_cuda", False) else im)
                        .float()
                        .div_(255.0) if getattr(im, "dtype", None) == _t223b.uint8
                        else (im.to(_dev223) if (im is not None and not getattr(im, "is_cuda", False)) else im)
                    )
                    for im in out_images
                ]
            except Exception:
                pass
            out_images = [
                _ff_run_segment_face_refine(im, model, clip, vae, audio_vae) if im is not None else im
                for im in out_images
            ]

        out_images_t, out_audios_t = _concat_clip_av(out_images, out_audios)

        # ── Lip Sync 模式：最终音频 = 纯 lip_audio 外部音源 ──
        # v14.270: 模型自生成音频(环境音/呼吸/自生成音乐)完全丢弃, 不再以 15% 垫底;
        # 模型音频仅在采样时作潜空间条件驱动口型, 不出现在最终输出中。
        if lip_audio is not None and lip_audio_segments is not None:
            try:
                import torchaudio as _ta_final
                total_video_frames = int(out_images_t.shape[0])
                video_duration = float(total_video_frames) / float(FPS)

                lip_wave = lip_audio["waveform"].float()
                lip_sr = int(lip_audio["sample_rate"])

                # 目标采样率/声道布局跟随模型音频输出格式
                model_sr = int(out_audios_t["sample_rate"])
                _out_ch = int(out_audios_t["waveform"].shape[-2]) if out_audios_t["waveform"].ndim >= 2 else 2

                # 歌曲重采样到模型音频采样率
                if lip_sr != model_sr:
                    lip_wave = _ta_final.functional.resample(lip_wave, lip_sr, model_sr)
                # 维度对齐 [B, C, L]
                if lip_wave.ndim == 2:
                    lip_wave = lip_wave.unsqueeze(0)
                # 声道对齐(歌曲单声道 → 输出立体声)
                if lip_wave.shape[1] == 1 and _out_ch == 2:
                    lip_wave = lip_wave.repeat(1, 2, 1)

                # 长度对齐到视频时长对应的模型采样数
                target_samples = max(1, int(video_duration * model_sr))
                # 歌曲段截/填到 target_samples
                if int(lip_wave.shape[-1]) >= target_samples:
                    lip_aligned = lip_wave[..., :target_samples]
                else:
                    _pad = target_samples - int(lip_wave.shape[-1])
                    lip_aligned = torch.cat([
                        lip_wave,
                        torch.zeros(lip_wave.shape[0], lip_wave.shape[1], _pad,
                                    dtype=lip_wave.dtype, device=lip_wave.device)
                    ], dim=-1)

                # v14.270: 纯 lip_audio 输出 — 模型自生成音频完全丢弃
                out_audios_t = {
                    "waveform": lip_aligned.cpu().float().contiguous(),
                    "sample_rate": model_sr,
                }
                print(f"[H3 LipSync] ✅ 最终出片音频: 纯 lip_audio 外部音源(模型自生成音频已完全丢弃) "
                      f"= {int(lip_aligned.shape[-1])} samples @ {model_sr}Hz "
                      f"({float(int(lip_aligned.shape[-1])) / model_sr:.2f}s)")
            except Exception as _lip_err:
                # 兜底：混音失败也要输出歌曲主体，不回退到纯模型音频。
                print(f"[H3 LipSync] ⚠️ 最终混音失败({_lip_err})，直接输出原始 lip_audio 波形兜底")
                try:
                    out_audios_t = {
                        "waveform": lip_audio["waveform"].cpu().float().contiguous(),
                        "sample_rate": int(lip_audio["sample_rate"]),
                    }
                except Exception:
                    pass

        if len(out_images) > 0:
            print(f"[H3 Extender] AV outputs: {int(out_images_t.shape[0])} frames, "
                  f"audio {int(out_audios_t['waveform'].shape[-1])} samples @ "
                  f"{int(out_audios_t['sample_rate'])}Hz")

        # v1.98: 渲染完成自动快照，保护本次渲染成果（可一键恢复）
        try:
            _snapshot_chain(data_path, manifest_path, reason="render-complete")
        except Exception:
            pass

        return {
            "ui": ui_payload,
            "result": (
                previous_handle,
                int(len(clips)),
                int(validated_count),
                status,
                float(cache_mb),
                BUILD,
                clip_videos_json,
                out_images_t,
                out_audios_t,
            ),
        }


NODE_CLASS_MAPPINGS = {
    "BSAIH3FilmFactory": BSAIH3FilmFactory,
    # Intermediate name kept for backward compat with workflows
    # created during the rename transition period.
    "BSAIMiniMaxH3Extender": BSAIH3FilmFactory,
    # Final Decode node — reads from our plugin's cache directory
    "BSAIH3FilmFactoryFinalDecode": MiniMaxH3MotionContextDiskFinalDecode,
}

# v14.144 启动标记：重启 ComfyUI 后控制台出现此行即确认加载的是最新后端
# v14.257: 隐藏启动横幅中的超长版本说明文字（原括号内整段历史配方摘要不再打印）
# v14.389: 横幅改为直接打印 BUILD —— 原来硬编码 v14.239, 与 BUILD 长期脱节,
# 控制台看到的"已加载版本"和 manifest 里的 build 对不上, 无法一眼判断是否重启生效。
print(f"[BSAI-H3-Film-Factory] {BUILD} backend loaded")

NODE_DISPLAY_NAME_MAPPINGS = {
    "BSAIH3FilmFactory": "BSAI ComfyUI H3 Film Factory",
    "BSAIMiniMaxH3Extender": "BSAI H3 Extender (Legacy Alias)",
    "BSAIH3FilmFactoryFinalDecode": "BSAI H3 Final Decode & Export",
}


if getattr(PromptServer, "instance", None) is not None:
    @PromptServer.instance.routes.post("/h3_extender/ref/upload")
    async def h3_extender_ref_upload(request):
        """Upload one image reference and store the actual pixels internally."""
        temp_path = _project_temp_root() / f"ref_upload_{uuid.uuid4().hex}.bin"
        original_name = "reference.png"
        got_file = False
        size = 0
        try:
            reader = await request.multipart()
            while True:
                part = await reader.next()
                if part is None:
                    break
                if part.name != "ref_file":
                    continue
                original_name = str(part.filename or "reference.png")
                with open(temp_path, "wb") as f:
                    while True:
                        chunk = await part.read_chunk(size=PROJECT_COPY_CHUNK)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > MAX_REF_UPLOAD_BYTES:
                            raise ValueError(
                                f"MiniMax H3 Extender: reference upload exceeds {MAX_REF_UPLOAD_BYTES // (1024 * 1024)} MB."
                            )
                        f.write(chunk)
                    f.flush()
                    os.fsync(f.fileno())
                got_file = True
                break

            if not got_file or not temp_path.exists() or temp_path.stat().st_size <= 0:
                return web.json_response(
                    {"ok": False, "error": "No reference image was uploaded."}, status=400
                )
            try:
                ref = await asyncio.to_thread(
                    _store_uploaded_reference,
                    temp_path,
                    original_name,
                )
            except Exception as exc:
                return web.json_response({"ok": False, "error": str(exc)}, status=400)
            return web.json_response({"ok": True, "ref": ref})
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass

    @PromptServer.instance.routes.post("/h3_extender/ref/edit")
    async def h3_extender_ref_edit(request):
        """Apply simple photographic adjustments to an internal reference."""
        try:
            body = await request.json()
            source_id = str(body.get("source_id") or body.get("ref_id") or "").lower().strip()
            if not _ref_id_is_safe(source_id):
                return web.json_response(
                    {"ok": False, "error": "Invalid source reference id."}, status=400
                )

            ref = await asyncio.to_thread(
                _edit_internal_reference,
                source_id,
                str(body.get("original_name") or "reference.png"),
                body.get("brightness", 100),
                body.get("contrast", 100),
                body.get("saturation", 100),
            )
            return web.json_response({"ok": True, "ref": ref})
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    @PromptServer.instance.routes.get("/h3_extender/ref/image")
    async def h3_extender_ref_image(request):
        """Serve an internally managed reference thumbnail/full preview."""
        ref_id = str(request.query.get("id", "")).lower().strip()
        if not _ref_id_is_safe(ref_id):
            return web.Response(status=400, text="Invalid reference id.")
        path = _ref_path(ref_id)
        if not path.exists():
            return web.Response(status=404, text="Reference image not found.")
        return web.FileResponse(
            path,
            headers={
                "Content-Type": "image/png",
                "Cache-Control": "public, max-age=31536000, immutable",
            },
        )

    @PromptServer.instance.routes.get("/h3_extender/cache/open")
    async def h3_extender_cache_open(request):
        """v1.16: 打开 latent 缓存目录 / CLIP 视频输出目录，并返回路径+文件列表。
        kind=latent -> cache/（chain_extender_*.h3cache 等）
        kind=clips  -> ComfyUI output/bsai_clips/（v1.94 持久化 h3_clip_*.mp4，
        重启不清空，Premiere Pro 时间线路径重启后仍有效）"""
        kind = str(request.query.get("kind", "latent")).strip().lower()
        try:
            if kind == "clips":
                d = _clip_output_dir()
            else:
                d = _ensure_cache_root()
            d = d.resolve()
            files = []
            if d.exists() and d.is_dir():
                for p in sorted(d.iterdir()):
                    if p.is_file():
                        try:
                            st = p.stat()
                            files.append({
                                "name": p.name,
                                "size": st.st_size,
                                "mtime": st.st_mtime,
                            })
                        except Exception:
                            pass
            # A one-click "open the folder" only for a caller on this machine;
            # any other client that can reach this route just gets the path,
            # so a remote request cannot pop a window on the host desktop.
            opened = False
            peer = str(getattr(request, "remote", "") or "")
            if peer in ("127.0.0.1", "::1"):
                try:
                    if os.name == "nt":
                        os.startfile(str(d))
                    else:
                        import subprocess
                        subprocess.Popen(
                            ["xdg-open", str(d)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        )
                    opened = True
                except Exception as open_err:
                    print(f"[BSAI H3 Film Factory] open cache dir failed: {open_err}")
            return web.json_response({
                "ok": True,
                "kind": kind,
                "path": str(d),
                "opened": opened,
                "files": files,
            })
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    @PromptServer.instance.routes.post("/h3_extender/ref2va_cache/clear")
    async def h3_extender_ref2va_cache_clear(request):
        """v1.27: 资产库删除/更换后清空 ref2va 参考图VAE编码磁盘缓存。

        旧资产图片被删除后，其 VAE 编码（Image Latent）若仍留在磁盘缓存，
        可能被同名/同key的新资产命中而错误复用。前端在 bsai-assets-changed
        事件中调用本接口，删除所有 _ref2va_cache/*.pt，下次生成重新编码。
        """
        try:
            root = _ensure_cache_root() / _REF2VA_CACHE_DIRNAME
            removed = 0
            if root.exists() and root.is_dir():
                for p in root.glob("*.pt"):
                    try:
                        p.unlink(missing_ok=True)
                        removed += 1
                    except Exception:
                        pass
            if removed > 0:
                print(f"[H3 Extender] ref2va cache cleared on asset change: removed={removed}")
            return web.json_response({"ok": True, "removed": removed, "path": str(root)})
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    @PromptServer.instance.routes.post("/h3_extender/clear_chain_cache")
    async def h3_extender_clear_chain_cache(request):
        """清空链缓存：删除上一版生成的缓存文件，重新渲染新缓存用。

        清理范围：
        - chain_*.h3cache / chain_*.json（主链缓存）
        - _ref2va_cache/*.pt（参考图VAE编码缓存）
        - _refs/*（参考图缓存）
        - _preview/*（预览缓存）
        - _color_*.log（颜色日志）
        - bsai_clips/h3_clip_*.mp4（已渲染CLIP成片，可选）
        - _clippv_*（临时预览，temp目录）
        """
        try:
            import shutil
            body = await request.json() if request.can_read_body else {}
            clear_clips = bool(body.get("clear_clips", True))

            cache_root = _ensure_cache_root()
            removed = 0
            freed_mb = 0.0
            details = {}

            # 1. 主链缓存 chain_*.h3cache / chain_*.json
            chain_files = list(cache_root.glob("chain_*.h3cache")) + list(cache_root.glob("chain_*.json"))
            for p in chain_files:
                try:
                    sz = p.stat().st_size if p.exists() else 0
                    p.unlink(missing_ok=True)
                    removed += 1
                    freed_mb += sz / (1024 * 1024)
                except Exception:
                    pass
            details["chain_cache"] = len(chain_files)

            # 2. ref2va 缓存
            ref2va_dir = cache_root / _REF2VA_CACHE_DIRNAME
            ref2va_count = 0
            if ref2va_dir.exists() and ref2va_dir.is_dir():
                for p in ref2va_dir.glob("*.pt"):
                    try:
                        sz = p.stat().st_size
                        p.unlink(missing_ok=True)
                        ref2va_count += 1
                        freed_mb += sz / (1024 * 1024)
                    except Exception:
                        pass
            details["ref2va"] = ref2va_count

            # 3. _refs 目录
            refs_dir = cache_root / "_refs"
            refs_count = 0
            if refs_dir.exists() and refs_dir.is_dir():
                for p in refs_dir.rglob("*"):
                    if p.is_file():
                        try:
                            sz = p.stat().st_size
                            p.unlink(missing_ok=True)
                            refs_count += 1
                            freed_mb += sz / (1024 * 1024)
                        except Exception:
                            pass
            details["refs"] = refs_count

            # 4. _preview 目录
            preview_dir = cache_root / "_preview"
            preview_count = 0
            if preview_dir.exists() and preview_dir.is_dir():
                for p in preview_dir.rglob("*"):
                    if p.is_file():
                        try:
                            sz = p.stat().st_size
                            p.unlink(missing_ok=True)
                            preview_count += 1
                            freed_mb += sz / (1024 * 1024)
                        except Exception:
                            pass
            details["preview"] = preview_count

            # 5. _color_*.log
            color_logs = list(cache_root.glob("_color_*.log"))
            for p in color_logs:
                try:
                    p.unlink(missing_ok=True)
                    removed += 1
                except Exception:
                    pass
            details["color_logs"] = len(color_logs)

            # 6. CLIP 成片（可选）
            clips_count = 0
            if clear_clips:
                clips_dir = _clip_output_dir()
                if clips_dir.exists() and clips_dir.is_dir():
                    for p in clips_dir.glob("h3_clip_*.mp4"):
                        try:
                            sz = p.stat().st_size
                            p.unlink(missing_ok=True)
                            clips_count += 1
                            freed_mb += sz / (1024 * 1024)
                        except Exception:
                            pass
            details["clips"] = clips_count

            # 7. 临时预览 _clippv_*
            temp_dir = _comfyui_temp_dir()
            temp_count = 0
            if temp_dir.exists() and temp_dir.is_dir():
                for p in temp_dir.glob("_clippv_*"):
                    try:
                        if p.is_file():
                            sz = p.stat().st_size
                            p.unlink(missing_ok=True)
                            temp_count += 1
                            freed_mb += sz / (1024 * 1024)
                        elif p.is_dir():
                            shutil.rmtree(p, ignore_errors=True)
                            temp_count += 1
                    except Exception:
                        pass
            details["temp_previews"] = temp_count

            print(f"[H3 Extender] 缓存已清空: removed={removed + ref2va_count + refs_count + preview_count + clips_count + temp_count}, freed={freed_mb:.1f}MB, details={details}")
            return web.json_response({
                "ok": True,
                "removed": removed + ref2va_count + refs_count + preview_count + clips_count + temp_count,
                "freed_mb": round(freed_mb, 1),
                "details": details,
                "cache_root": str(cache_root),
            })
        except Exception as exc:
            print(f"[H3 Extender] clear_chain_cache error: {exc}")
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    @PromptServer.instance.routes.post("/h3_extender/project/prepare_save")
    async def h3_extender_project_prepare_save(request):
        """Build a portable .ext archive without buffering the cache in RAM."""
        try:
            body = await request.json()
            owner_id = str(body.get("owner_id", "")).strip()
            if not owner_id:
                return web.json_response(
                    {"ok": False, "error": "Missing Extender node id."}, status=400
                )
            project_payload = body.get("project", {})
            if not isinstance(project_payload, dict):
                return web.json_response(
                    {"ok": False, "error": "Invalid project metadata."}, status=400
                )

            _cleanup_project_downloads()
            filename = _project_filename(body.get("project_name", "MiniMax_H3_Project"))
            token = uuid.uuid4().hex
            temp_path = _project_temp_root() / f"download_{token}.ext"

            try:
                archive_meta = await asyncio.to_thread(
                    _build_project_archive,
                    owner_id,
                    filename,
                    project_payload,
                    temp_path,
                )
            except Exception as exc:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass
                return web.json_response(
                    {"ok": False, "error": str(exc)}, status=500
                )

            _PROJECT_DOWNLOADS[token] = {
                "path": str(temp_path),
                "filename": filename,
                "created_at": time.time(),
            }
            return web.json_response({
                "ok": True,
                "token": token,
                "filename": filename,
                "size_bytes": int(temp_path.stat().st_size),
                "cache": archive_meta.get("cache", {}),
                "references": archive_meta.get("references", {}),
            })
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=500)

    @PromptServer.instance.routes.get("/h3_extender/project/download")
    async def h3_extender_project_download(request):
        """Stream a prepared .ext directly to the browser, then remove the temp file."""
        _cleanup_project_downloads()
        token = str(request.query.get("token", "")).strip()
        info = _PROJECT_DOWNLOADS.pop(token, None)
        if not info:
            return web.Response(status=404, text="Project download expired or was not found.")

        path = Path(info["path"])
        if not path.exists():
            return web.Response(status=404, text="Project file no longer exists.")

        filename = _project_filename(info.get("filename", "MiniMax_H3_Project.ext"))
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(path.stat().st_size),
                "Cache-Control": "no-store",
            },
        )
        try:
            await response.prepare(request)
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(PROJECT_COPY_CHUNK)
                    if not chunk:
                        break
                    await response.write(chunk)
            await response.write_eof()
            return response
        finally:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass

    @PromptServer.instance.routes.post("/h3_extender/project/load")
    async def h3_extender_project_load(request):
        """Import a .ext into the cache owned by the Extender node making the request."""
        upload_path = _project_temp_root() / f"upload_{uuid.uuid4().hex}.ext"
        owner_id = ""
        original_name = ""
        got_file = False
        try:
            reader = await request.multipart()
            while True:
                part = await reader.next()
                if part is None:
                    break
                if part.name == "owner_id":
                    owner_id = (await part.text()).strip()
                elif part.name == "project_file":
                    original_name = str(part.filename or "project.ext")
                    with open(upload_path, "wb") as f:
                        while True:
                            chunk = await part.read_chunk(size=PROJECT_COPY_CHUNK)
                            if not chunk:
                                break
                            f.write(chunk)
                        f.flush()
                        os.fsync(f.fileno())
                    got_file = True

            if not owner_id:
                return web.json_response(
                    {"ok": False, "error": "Missing Extender node id."}, status=400
                )
            if not got_file or not upload_path.exists():
                return web.json_response(
                    {"ok": False, "error": "No .ext project file was uploaded."}, status=400
                )

            try:
                imported = await asyncio.to_thread(
                    _import_project_archive,
                    owner_id,
                    upload_path,
                )
            except zipfile.BadZipFile:
                return web.json_response(
                    {"ok": False, "error": "The selected .ext file is not a valid project archive."},
                    status=400,
                )
            except Exception as exc:
                return web.json_response(
                    {"ok": False, "error": str(exc)}, status=400
                )

            imported["ok"] = True
            imported["source_filename"] = original_name
            return web.json_response(imported)
        finally:
            try:
                upload_path.unlink(missing_ok=True)
            except Exception:
                pass
