"""Human-readable spatial tiling diagnostics (all memory values are estimates)."""


def format_plan(plan):
    if plan.get("kind") == "global":
        mode = plan.get("mode", "global")
        lines = [
            f"Mode / 模式: {mode}",
            "Full sequence / 全序列: 不切空间，保留完整 token/attention 上下文",
            f"Token chunk / token 分块: {plan.get('token_chunk', '?')}",
        ]
        if mode == "global_stream":
            cache = float(plan.get("weight_cache_gb", 0) or 0)
            lines.append(f"Weight cache / 权重缓存预算: {cache:.1f} GiB")
            lines.append("Native sparse / 原生稀疏: required (SLA/sol-attn on every block)")
        elif mode == "global_ram":
            lines.append("Host staging / 主机内存暂存: enabled; slower, lower GPU workspace")
        else:
            lines.append("Compatible fallback / 兼容路径: global context; may use more VRAM than global_stream")
        if plan.get("fallback") == "attention_backend":
            lines.append("Fallback / 回退: dense attention backend override removed; using default full-sequence attention")
        elif plan.get("fallback"):
            lines.append("Fallback / 回退: attention override detected; full-sequence dense attention with chunked MLP")
        lines.extend([
            "Masks / 遮罩: full-sequence video/audio masks, not cropped",
            "Estimate only / 非实测峰值；不保证不爆显存",
        ])
        return "\n".join(lines)

    axis = "W / 宽度" if plan["axis"] == 4 else "H / 高度"
    request = str(plan["requested_tiles"]) if plan["mode"] == "manual" else "auto"
    regions = plan["regions"]
    overlaps = [max(0, regions[i][1] - regions[i + 1][0]) for i in range(len(regions) - 1)]
    lines = [
        f"实际分块数量 / Actual tiles: {plan['tiles']}" + ("（整图，不拆分 / no split）" if plan['tiles'] == 1 else " 块"),
        f"Spatial / 空间分块 | mode={plan['mode']} | axis={axis}",
        f"Requested / 请求: {request} | Effective / 实际: {plan['tiles']}" + (" (整图 / no split)" if plan['tiles'] == 1 else ""),
        f"Largest latent tile / 最大块: {plan['largest_tile']}",
        "Regions / 范围 [start,end): " + ", ".join(f"[{a},{b})" for a, b in regions),
        "Overlap / 重叠 latent: " + (str(overlaps) if overlaps else "0"),
        f"Full audio / 完整音频: {plan['audio_shape']}",
        f"Est. workspace / 预计可用: {plan['available_mib']:.0f} MiB | minimum / 估计最低: {plan['minimum_mib']:.0f} MiB",
        "Estimate only / 非实测峰值，不保证不爆显存；非实时自适应",
    ]
    if not plan['estimate_fits']:
        lines.append("WARNING / 估计显存不足：不会自动重试，请增加块数或降低分辨率/时长")
    return "\n".join(lines)
