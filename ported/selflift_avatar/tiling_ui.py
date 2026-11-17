"""Human-readable spatial tiling diagnostics (all memory values are estimates)."""


def format_plan(plan):
    if plan.get("kind") == "global":
        mode = plan.get("mode", "global")
        lines = [
            f"Mode: {mode}",
            "Full sequence: no spatial split, full token/attention context retained",
            f"Token chunk: {plan.get('token_chunk', '?')}",
        ]
        if mode == "global_stream":
            cache = float(plan.get("weight_cache_gb", 0) or 0)
            lines.append(f"Weight cache budget: {cache:.1f} GiB")
            lines.append("Native sparse: required (SLA/sol-attn on every block)")
        elif mode == "global_ram":
            lines.append("Host staging: enabled; slower, lower GPU workspace")
        else:
            lines.append("Compatible fallback: global context; may use more VRAM than global_stream")
        if plan.get("fallback") == "attention_backend":
            lines.append("Fallback: dense attention backend override removed; using default full-sequence attention")
        elif plan.get("fallback"):
            lines.append("Fallback: attention override detected; full-sequence dense attention with chunked MLP")
        lines.extend([
            "Masks: full-sequence video/audio masks, not cropped",
            "Estimate only: not a measured peak; OOM is not guaranteed to be avoided",
        ])
        return "\n".join(lines)

    axis = "W / width" if plan["axis"] == 4 else "H / height"
    request = str(plan["requested_tiles"]) if plan["mode"] == "manual" else "auto"
    regions = plan["regions"]
    overlaps = [max(0, regions[i][1] - regions[i + 1][0]) for i in range(len(regions) - 1)]
    lines = [
        f"Actual tiles: {plan['tiles']}" + (" (single frame, no split)" if plan['tiles'] == 1 else ""),
        f"Spatial | mode={plan['mode']} | axis={axis}",
        f"Requested: {request} | Effective: {plan['tiles']}" + (" (single frame, no split)" if plan['tiles'] == 1 else ""),
        f"Largest latent tile: {plan['largest_tile']}",
        "Regions [start,end): " + ", ".join(f"[{a},{b})" for a, b in regions),
        "Overlap latent: " + (str(overlaps) if overlaps else "0"),
        f"Full audio: {plan['audio_shape']}",
        f"Est. workspace: {plan['available_mib']:.0f} MiB | minimum: {plan['minimum_mib']:.0f} MiB",
        "Estimate only: not a measured peak, OOM not guaranteed; not adaptive at runtime",
    ]
    if not plan['estimate_fits']:
        lines.append("WARNING: estimated VRAM insufficient; it will not retry automatically, increase tile count or reduce resolution/duration")
    return "\n".join(lines)
