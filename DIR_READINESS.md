# P3 · DiR（数据空间迭代）就绪说明 / DiR Readiness Note

> 2026-10-17 · 《H3加速与画质提升技术周报_2026-10-17》第 2 项 / Weekly report item #2
> 项目页 / Project: https://scrya.com/dir_diffusion

## 技术要点 / What it is

Scrya 的 John D. Pope 将字节 Seed 团队的 **Data-space iteration (DiR, arXiv 2610.12102)** 移植到 MiniMax H3：
- DMD 双教师训练（real teacher = 冻结 H3，fake teacher = 学习 generator 习惯）
- Generator = H3 + **rank-16 LoRA** + 两个零初始化小模块（previous estimate projection + r embedding）
- 4 步精炼，DiT 时间快 5.4 倍，单卡 24GB / batch 2 / 1000 步可训练

## 当前状态（2026-10-17） / Status

- **无社区发布权重**：DiR 目前是论文方法 + 训练配方，尚未见可用 LoRA/checkpoint 下载
- **本地已具备接入条件**，无需任何代码改动：
  - `BSAI-Lora-Stack` 已支持任意 H3 LoRA 下拉加载（标准 LoraLoader 路径）
  - 本地基座 `diffusion_models\H3\minimax_h3_fl2va_pruned_int8_convrot.safetensors` 可挂 rank-16 LoRA（LoRA 无 adaln tensor 时 pruned 基座兼容）
  - `large-file-download` skill 可承接后续权重下载

## 落地预案 / Landing plan

1. **监控**：关注 scrya.com/dir_diffusion 与 Hugging Face 社区（HF 搜索 "dir h3 lora" / "dir_diffusion minimax"）
2. **权重发布后**：用 `large-file-download` skill 下载 → 放 `ComfyUI\models\loras\` → Lora-Stack 下拉选择
3. **训练侧（可选）**：按项目页配方单卡 24GB 微调；训练产物导出为 safetensors LoRA 后可同样接入

## 结论 / Conclusion

P3 = **就绪待权重**，无代码改动。一旦社区发布 DiR 权重，按上述预案 10 分钟内可跑通。
