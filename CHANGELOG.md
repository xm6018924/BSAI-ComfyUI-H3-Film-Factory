# CHANGELOG ｜ 更新日志

All notable changes, bilingual. 所有重要版本双语说明。

---
## v1.86 (2026-09-15) — VDN-H3 Presets + Bullet Time LoRA ｜ VDN-H3 速度档 + 子弹时间 Lora
- **VDN-H3 speed presets** ｜ **VDN-H3 速度档**: speed_preset adds 极速-VDN / 均衡-VDN / 精细-VDN. Pass-1 fixed at 8 VDN steps (DMD-distilled optimum, quality ≈ dense-50, linear attention keeps long clips stable); refine 3/4/6 steps. Requires the VDN workflow (workflows/电影工厂工作流-VDN版-均衡VDN8+4（tile_overlap128）.json) whose UNETLoader+ApplyVDNH3 replaces the Sol-H3 chain (FastH3 LoRA & Sol-Attn skipped). ｜ speed_preset 新增三档 VDN 预设：一采固定 VDN 8 步（蒸馏最优、质量≈dense 50 步、长链线性注意力更稳），二采 3/4/6 步；需搭配 VDN 版工作流（UNETLoader+ApplyVDNH3 替换 Sol-H3 链路，跳过 FastH3 LoRA/Sol-Attn）。
- **Bullet Time LoRA in workflows** ｜ **工作流集成子弹时间 Lora**: both FastH3 and VDN workflows mount BulletTime-MMH3.safetensors @ 0.5 in the LoRA stack. Pair with the bullet-time trigger words added in BSAI-MiniMAX-H3-Prompt templates. ｜ FastH3 版与 VDN 版工作流均挂载 BulletTime-MMH3 @ 0.5，配合模板子弹时间触发词使用。

## v1.85 (2026-09-15) — Preview Blob Rebuild + Turbo Quality ｜ 预览重建 + 极速画质
- CLIP preview auto-rebuilds from chain manifest when temp files are cleared (regex fallback) ｜ 预览文件被清后按链清单自动重建。
- Turbo refine 2→3 steps, denoise 0.55→0.5 (fixes blurry dynamic shots) ｜ 极速二采 2→3 步、denoise 0.5，修动态糊。


## v1.84 (2026-09-15) — Preview Playback Fix + Migration Hardening ｜ 预览播放修复 + 迁移加固
- **Preview playback fixed (all machines)** ｜ **预览播放修复（所有机器一致）**:
  - New plugin self-served route GET /h3_extender/clip_preview/file?name=<file> streams CLIP previews straight from ComfyUI\temp, bypassing ComfyUI /view?type=temp which resolves older_paths.get_temp_directory(). On some machines other plugins call set_temp_directory() to the OS temp, so /view 404'd while files lived in ComfyUI\temp. Write & read are now same-source. ｜ 新增插件自服务路由，预览直接从 ComfyUI\temp 读取，绕开 /view 的 temp 目录解析不一致（部分机器被其它插件改到系统 Temp 后 404 无法播放），写读同源。
  - Frontend clipPreviewMediaUrl() uses the plugin route for 	ype=temp. ｜ 前端 temp 类型预览改走插件路由。
- **Chain-cache migration hardened** ｜ **链缓存迁移加固**: v1.82 migration no longer touches .migrated_v182 on partial failure (retries next startup) and verifies copied file size, preventing silent loss of large chains (e.g. 772MB h3cache). ｜ 迁移失败不再误标记、下次启动重试补齐 + 复制后大小校验，杜绝大文件链静默丢失。

## v1.83b (2026-09-15) — Bilingual UI Labels ｜ 双语界面标签
- speed_preset and related labels now show Chinese + English. ｜ 速度预设等参数标签中英双语显示。

## v1.83 (2026-09-15) — Speed Preset ｜ 速度预设 🚀
- New speed_preset widget on BSAIH3FilmFactory (after 	ile_overlap): **Turbo 极速 / Balanced 均衡 / Fine 精细**. ｜ 主节点新增速度预设下拉。
- Turbo = pass1 4 steps + refine 2 steps + 4 tiles + denoise 0.55 → ~15 min/clip on 24GB (15s, 2.08M px), ~46% faster than default. ｜ 极速：一采4步+二采2步，24G 跑 15s 200万像素 ~15 分钟/clip。
- Landed the MiniMax turbo workflow technique (comfyu-Selflift): low-res pass1 composition → 3D latent neural upscale → high-res refine only 2 steps. ｜ 落地 MiniMax 急速工作流技术：低分辨率构图 → latent 神经放大 → 高分辨率二采只跑 2 步。

## v1.82 (2026-09-15) — Chain Cache Relocation ｜ 链缓存目录迁移
- Chain cache moved from custom_nodes/BSAI-ComfyUI-H3-Film-Factory/cache to ComfyUI/bsai_h3_chain_cache (_CACHE_ROOT), auto-migrating legacy files on first use. Protects chains from external tools (e.g. backup software) clearing the custom_nodes cache directory. ｜ 链缓存迁出 custom_nodes 目录到 ComfyUI/bsai_h3_chain_cache，首次使用自动迁移，防止外部软件（如备份软件）清空 custom_nodes 缓存导致丢链。

## v1.81 (2026-09-15) — VRAM Release Timing ｜ 显存释放时机优化
- Explicit VRAM release before pass1 and refine (1.81 显存释放[pass1]/[refine]), reducing OOM risk in dynamic-VRAM environments. ｜ 一采/二采前显式释放显存，降低动态显存环境 OOM 风险。

## v1.80 (2026-09-15) — Cache Diagnostics ｜ 缓存诊断
- On insufficient segments, prints cache诊断: json=X字节 bak=X字节 h3cache=X字节 for quick root-cause. ｜ 段数不足时打印 json/bak/h3cache 字节数便于定位。

## v1.79 (2026-09-15) — Manifest Double-Backup ｜ 清单双保险
- .bak double backup + corruption fallback + segment-count tolerance. ｜ 清单 .bak 双保险 + 损坏回退 + 段数容错。

## v1.78 (2026-09-15) — aimdo Crash Fix ｜ aimdo 编译崩溃修复
- Wrap pass1/refine in _aimdo_disabled() context to avoid graph.push() compile crash on ComfyUI 0.35 with aimdo memory graph. ｜ 一采/二采包 aimdo 禁用上下文，修复 0.35 版本 aimdo 内存图编译崩溃。

## v1.77 (2026-09-15) — Encoder Quality ｜ 编码质量
- Preview/CLIP MP4 encode from ultrafast/17 → ast/14, reduces blocky artifacts. ｜ 预览/片段编码质量提升（fast/14），减少色块伪影。

## v1.76 (2026-09-15) — Unified Temp Path ｜ 临时文件路径统一
- All preview & CLIP temp files pinned to _comfyui_temp_dir() = <your ComfyUI>\temp (7 call sites). ｜ 所有预览/CLIP 临时文件统一固定到各自安装目录下的 ComfyUI\temp。

## v1.75 (2026-09-15) — 4090 Preview Probe Fix ｜ 4090 预览探针修复
- Fixed 2x2 probe transpose on machines without --enable-assets. ｜ 修复无 --enable-assets 机器的 2x2 探针转置问题。

## v1.74 (2026-09-15) — Chain Geometry Consistency ｜ 链几何一致性
- Block per-clip VRAM-budget downgrade once chain segments exist; align returned latent to chain geometry (trilinear) — fixes latent geometry changed Disk Join break on long chains (e.g. CLIP7). ｜ 链上有段后禁止 per-clip 降级 + 返回前 latent 对齐链上几何，修复长链（如 CLIP7）Disk Join 断链。

---

## Older / 更早版本
See README.md sections for v1.31+ feature history. ｜ v1.31 及更早功能历史见 README.md。
