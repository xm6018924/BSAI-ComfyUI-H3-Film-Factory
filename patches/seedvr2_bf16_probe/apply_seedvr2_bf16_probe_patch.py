# -*- coding: utf-8 -*-
"""SeedVR2 bf16 探针补丁 —— 幂等应用器。

背景 (2026-10-26)
-----------------
`custom_nodes/seedvr2_videoupscaler/src/optimization/compatibility.py` 在 **import 期**
执行模块级语句:

    BFLOAT16_SUPPORTED = _probe_bfloat16_support()

而 `_probe_bfloat16_support()` 里会做一次

    a = torch.randn(8, 8, dtype=torch.bfloat16, device='cuda:0')

在 ComfyUI 全量环境里(同一进程内已加载 xformers / flash_attn / sageattention /
comfy_kitchen 等多个 CUDA 扩展), 这次 **首次 bf16 分配** 会触发
`Windows fatal exception: access violation`(原生崩溃, Python 的 try/except 接不住),
整个 ComfyUI 进程被直接杀掉 → 启动器 .bat 走到 `pause`, 端口 8181 不监听。

实测: 独立进程里 flash_attn→bf16 / sageattention→bf16 / triton→bf16 / 纯 bf16 matmul
全部正常; 只有 ComfyUI 全量环境必现(16:04 与 16:09 两次启动崩在同一行, faulthandler
精确指向 compatibility.py:688)。

修法
----
把探针改成 **只查设备计算能力, 不分配任何显存**:
sm_80(Ampere)及以后原生支持 bf16, 对 4090(sm_89)结论一致, 与原探针等价。

注意
----
`src/generation_utils.py` 用 `from ..optimization.compatibility import COMPUTE_DTYPE,
BFLOAT16_SUPPORTED` 取常量, 所以常量必须在 import 期就绪 —— 不能用模块级
`__getattr__` 懒加载, 只能在探针内部做替换。

用法
----
    python apply_seedvr2_bf16_probe_patch.py            # 自动定位并打补丁
    python apply_seedvr2_bf16_probe_patch.py <文件路径>   # 指定文件(测试用)

由本插件的 `prestartup.py` 在 ComfyUI 启动前自动调用, 因此 SeedVR2 节点更新
把补丁冲掉后, 下次启动会自动重打。
"""

import io
import os
import re
import shutil
import sys

MARKER = "local patch 2026-10-26: seedvr2 bf16 probe"

# 判定"是否已修补"：只在 _probe_bfloat16_support 函数体里找特征串。
# (不能全文件找 —— get_device_capability 在该文件别处也出现过, 会误判)
_FN_RE = re.compile(r"def _probe_bfloat16_support\(\).*?(?=\n\S|\Z)", re.S)


def _is_patched(text):
    m = _FN_RE.search(text)
    if not m:
        return False
    body = m.group(0)
    return ("get_device_capability(0)" in body and ">= (8, 0)" in body) or MARKER in body

ORIGINAL = '''def _probe_bfloat16_support() -> bool:
    if not torch.cuda.is_available():
        return True
    try:
        a = torch.randn(8, 8, dtype=torch.bfloat16, device='cuda:0')
        _ = torch.matmul(a, a)
        del a
        return True
    except RuntimeError as e:
        if "CUBLAS_STATUS_NOT_SUPPORTED" in str(e):
            return False
        raise
'''

PATCHED = '''def _probe_bfloat16_support() -> bool:
    if not torch.cuda.is_available():
        return True
    try:
        # ''' + MARKER + '''
        # 原实现在这里做 torch.randn(8, 8, dtype=torch.bfloat16, device='cuda:0')
        # + matmul 来探测 cuBLAS 是否支持 bf16。在 ComfyUI 启动期(进程内已加载
        # xformers / flash_attn / sageattention / comfy_kitchen 等多个 CUDA 扩展)
        # 做这次首次 bf16 分配会触发 native access violation, 直接杀掉整个进程
        # -> ComfyUI 起不来(faulthandler 精确指向本行)。
        # 改为只查设备计算能力: sm_80(Ampere)及以后原生支持 bf16, 不分配任何显存,
        # 因此不会在 import 期触发 CUDA 分配崩溃。对 40 系(4090 sm_89)结论一致。
        major, minor = torch.cuda.get_device_capability(0)
        return (major, minor) >= (8, 0)
    except Exception:
        return True
'''


def default_target():
    """从本文件位置推导 seedvr2 节点里的 compatibility.py 路径。

    本文件位于 <ComfyUI>/custom_nodes/BSAI-ComfyUI-H3-Film-Factory/patches/
              seedvr2_bf16_probe/apply_seedvr2_bf16_probe_patch.py
    """
    here = os.path.dirname(os.path.abspath(__file__))
    custom_nodes = os.path.abspath(os.path.join(here, "..", "..", ".."))
    return os.path.join(
        custom_nodes, "seedvr2_videoupscaler", "src", "optimization", "compatibility.py")


def apply(target=None):
    """幂等应用补丁。返回 True 表示本次真的改了文件。"""
    target = target or default_target()
    if not os.path.isfile(target):
        print(f"[H3 Extender] seedvr2 bf16 probe patch: 目标不存在, 跳过 ({target})")
        return False

    with io.open(target, "r", encoding="utf-8", newline="") as f:
        text = f.read()

    if _is_patched(text):
        print("[H3 Extender] seedvr2 bf16 probe patch: 已是修补态, 跳过")
        return False

    crlf = "\r\n" in text
    old = ORIGINAL.replace("\n", "\r\n") if crlf else ORIGINAL
    new = PATCHED.replace("\n", "\r\n") if crlf else PATCHED

    if text.count(old) != 1:
        print(f"[H3 Extender] seedvr2 bf16 probe patch: 原始代码块匹配数="
              f"{text.count(old)}(上游已改动), 不强行改写, 跳过")
        return False

    bak = target + ".bak-pre-bf16-probe-patch"
    if not os.path.exists(bak):
        shutil.copy2(target, bak)

    with io.open(target, "w", encoding="utf-8", newline="") as f:
        f.write(text.replace(old, new, 1))
    print(f"[H3 Extender] seedvr2 bf16 probe patch: 已应用 (备份 {os.path.basename(bak)})")
    return True


if __name__ == "__main__":
    if len(sys.argv) > 1:
        ok = apply(sys.argv[1])
    else:
        ok = apply()
    sys.exit(0 if ok is not None else 1)
