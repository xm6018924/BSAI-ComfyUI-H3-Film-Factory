# SeedVR2 bf16 探针补丁 / SeedVR2 bf16 probe patch

修的是**第三方节点 SeedVR2 视频超分**在 ComfyUI **启动期**的原生崩溃，跟本插件无关，
但它会**直接把 ComfyUI 整个进程杀掉**，导致 H3 电影工厂也用不了，所以放在本仓库统一托管。

## 症状

ComfyUI 启动到一半进程消失，端口 8181 不监听，启动器 `.bat` 走到 `pause`：

```
[San4itos][San4itosInit] *** Custom Nodes from ComfyUI-san4itos Initialized ***
⚡ SeedVR2 optimizations check: SageAttention ✅ | Flash Attention ✅ | Triton ✅
🔧 Conv3d workaround active: PyTorch 2.11.0, cuDNN 91900 (fixing VAE 3x memory bug)
   ← 停在这里, 进程被 native 崩溃杀掉
```

服务端日志 `ComfyUI/user/comfyui_8181.log` 停在这两行之后；插件目录的
`_crash_faulthandler.log` 里搜 `Current thread` 能看到精确崩点：

```
Current thread 0x...:
  File ".../custom_nodes/seedvr2_videoupscaler/src/optimization/compatibility.py", line 688 in _probe_bfloat16_support
Windows fatal exception: access violation
```

## 根因

`compatibility.py` 在 **import 期**执行模块级语句 `BFLOAT16_SUPPORTED = _probe_bfloat16_support()`，
探针里做一次 `torch.randn(8, 8, dtype=torch.bfloat16, device='cuda:0')`。
在 ComfyUI 全量环境里（同一进程已加载 xformers / flash_attn / sageattention / comfy_kitchen
等多个 CUDA 扩展），这次**首次 bf16 分配**会触发原生 access violation。

排除项（都验证过）：独立进程里 flash_attn→bf16 / sageattention→bf16 / triton→bf16 /
纯 bf16 matmul **全部正常**；与模型、显存容量、驱动版本无关；本机必现（16:04 与 16:09
两次启动崩在同一行）。

## 修法

把探针换成**只查设备计算能力、不分配显存**：`sm_80`(Ampere) 及以后原生支持 bf16，
对 4090(sm_89) 结论一致，与原探针等价。

> 注意：`src/generation_utils.py` 用 `from ..optimization.compatibility import COMPUTE_DTYPE,
> BFLOAT16_SUPPORTED` 取常量，常量必须在 import 期就绪 → **不能**用模块级 `__getattr__`
> 懒加载，只能在探针内部替换。

## 自动重打

本插件的 `prestartup.py` 在 ComfyUI 启动前会调用
`apply_seedvr2_bf16_probe_patch.py`，所以**即使 SeedVR2 节点更新把补丁冲掉，下次启动会自动重打**。

手动执行：

```powershell
python patches\seedvr2_bf16_probe\apply_seedvr2_bf16_probe_patch.py
python patches\seedvr2_bf16_probe\apply_seedvr2_bf16_probe_patch.py <compatibility.py 路径>
```

应用器是幂等的：已修补则跳过；上游改了原始代码块（匹配数 ≠ 1）则**不强行改写**并打印提示。

## 兜底

万一补丁没生效又崩了，把节点目录临时禁用即可正常启动（ComfyUI 会跳过 `.disabled` 目录）：

```powershell
Rename-Item -LiteralPath "<ComfyUI>\custom_nodes\seedvr2_videoupscaler" -NewName "seedvr2_videoupscaler.disabled"
```

## 文件

| 文件 | 说明 |
|---|---|
| `apply_seedvr2_bf16_probe_patch.py` | 幂等应用器（prestartup 自动调用） |
| `compatibility.py.patch` | 同一改动的 unified diff，便于人工审阅/手工套用 |
| `README.md` | 本文件 |
