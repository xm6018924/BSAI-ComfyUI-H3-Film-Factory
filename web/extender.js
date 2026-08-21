import { app } from "../../scripts/app.js";
// extender.js v2.1.1 — cache-bust marker (2026-08-21-preview-fix)
import { api } from "../../scripts/api.js";

const TARGET = "MiniMaxH3Extender";
const FINAL_TARGET = "MiniMaxH3MotionContextDiskFinalDecode";
const PROGRESS_EVENT = "h3_extender_progress";
const LATENT_PREVIEW_EVENT = "h3_extender_latent_preview";
const PROMPT_PACK_EVENT = "h3_extender_prompt_pack_import";
const CARD_WIDTH = 318;
const UI_MIN_HEIGHT = 600;
const NODES2_MIN_HEIGHT = 650;
// Keep a real visual gap between the native Nodes 2.0 widgets and the CLIP
// panel. This is internal padding only: we deliberately do NOT rewrite Vue
// grid tracks or absolutely position the DOM widget.
const NODES2_TOP_GAP = 28;
const NODE_MIN_WIDTH = 520;
const BOTTOM_PAD = 16;
// Leave an empty gutter under each card so an overlay horizontal scrollbar
// never covers the Validated/footer row.
const CARD_SCROLLBAR_SPACE = 24;
const CARD_MIN_HEIGHT = 355;
const NODES2_CARDS_MIN_HEIGHT = CARD_MIN_HEIGHT + CARD_SCROLLBAR_SPACE;
const REF_SLOT_WIDTH = 96;
const REF_THUMB_HEIGHT = 96;
// Reserve the scrollbar inside the existing reference section only.
// Do not grow the DOM widget or alter card sizing/layout for this.
const REF_SCROLLBAR_SPACE = 14;
const REF_SECTION_HEIGHT = 160;
const MAX_IMAGE_REFS = 9;
const MAX_RESOLUTION = 4096;
const DEFAULT_MEGAPIXELS = 0.40;
const TOOLBAR_HEIGHT = 50;
const GLOBAL_PROMPT_MIN_HEIGHT = 200;
const BOTTOM_BAR_HEIGHT = 35;
const NON_CARD_FIXED = TOOLBAR_HEIGHT + GLOBAL_PROMPT_MIN_HEIGHT + BOTTOM_BAR_HEIGHT;
const COLLAPSED_CLIP_HEIGHT = 38;
const BASE_PADDING = BOTTOM_PAD + 20;
const COLLAPSED_MIN_HEIGHT = 160;
const PREVIEW_PANEL_WIDTH = 130;
const MAX_AUTO_NODE_HEIGHT = 2000;
const MAX_CARDS_VISIBLE_HEIGHT = 3 * (CARD_MIN_HEIGHT + 9) + CARD_SCROLLBAR_SPACE;

function calculateMinHeight(runtime) {
    if (!runtime?.state?.clips?.length) {
        return COLLAPSED_MIN_HEIGHT;
    }
    let height = NON_CARD_FIXED;
    let cardsHeight = 0;
    for (const clip of runtime.state.clips) {
        if (clip.collapsed) {
            cardsHeight += COLLAPSED_CLIP_HEIGHT;
        } else {
            cardsHeight += clip.card_height > 0
                ? Math.max(CARD_MIN_HEIGHT, clip.card_height)
                : CARD_MIN_HEIGHT + CARD_SCROLLBAR_SPACE;
        }
    }
    height += cardsHeight;
    return Math.max(COLLAPSED_MIN_HEIGHT, Math.min(height + BASE_PADDING, MAX_AUTO_NODE_HEIGHT));
}

async function fetchClipPreview(node, clipIndex) {
    const params = new URLSearchParams();
    params.set("owner_id", String(node.id));
    params.set("clip_index", String(clipIndex));
    try {
        const response = await fetch(api.apiURL("/h3_extender/clip_preview?" + params.toString()));
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || !payload?.ok || !payload?.video) {
            return null;
        }
        return payload.video;
    } catch (e) {
        return null;
    }
}

function clipPreviewMediaUrl(info) {
    const params = new URLSearchParams();
    params.set("filename", info?.filename || "");
    params.set("type", info?.type || "temp");
    params.set("subfolder", info?.subfolder || "");
    return api.apiURL("/view?" + params.toString());
}

function renderPreviewPanel(panel, clip, index, node, runtime) {
    const expanded = Boolean(clip._previewExpanded);
    const cardBody = panel.parentElement;

    if (expanded) {
        panel.style.cssText = "position:absolute;inset:0;z-index:20;background:rgba(0,0,0,.96);padding:6px;display:flex;flex-direction:column;align-items:center;justify-content:center;overflow:hidden;";
    } else {
        panel.style.cssText = `width:${PREVIEW_PANEL_WIDTH}px;min-width:${PREVIEW_PANEL_WIDTH}px;flex-shrink:0;border-left:1px solid rgba(255,255,255,.08);background:rgba(0,0,0,.15);padding:6px;display:flex;flex-direction:column;align-items:center;justify-content:flex-start;overflow:hidden;`;
    }
    if (clip.collapsed) panel.style.display = "none";

    panel.replaceChildren();

    const headerRow = document.createElement("div");
    headerRow.style.cssText = "display:flex;align-items:center;justify-content:space-between;width:100%;flex:0 0 auto;margin-bottom:3px;";

    const expandBtn = document.createElement("button");
    expandBtn.type = "button";
    expandBtn.textContent = expanded ? "⤫" : "⤢";
    expandBtn.title = expanded ? "缩小预览" : "放大预览";
    expandBtn.style.cssText = "width:22px;height:22px;padding:0;border-radius:4px;border:1px solid rgba(255,255,255,.15);background:rgba(40,40,40,.8);color:rgba(255,255,255,.7);cursor:pointer;font-size:12px;line-height:1;flex:0 0 auto;";
    expandBtn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        clip._previewExpanded = !clip._previewExpanded;
        renderPreviewPanel(panel, clip, index, node, runtime);
        requestAnimationFrame(() => syncDomHeight(node, runtime, false));
    });
    headerRow.appendChild(expandBtn);

    if (expanded) {
        const closeBtn = document.createElement("button");
        closeBtn.type = "button";
        closeBtn.textContent = "✕";
        closeBtn.title = "关闭预览";
        closeBtn.style.cssText = "width:22px;height:22px;padding:0;border-radius:4px;border:1px solid rgba(255,255,255,.15);background:rgba(40,40,40,.8);color:rgba(255,255,255,.7);cursor:pointer;font-size:12px;line-height:1;flex:0 0 auto;";
        closeBtn.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            clip._previewExpanded = false;
            renderPreviewPanel(panel, clip, index, node, runtime);
            requestAnimationFrame(() => syncDomHeight(node, runtime, false));
        });
        headerRow.appendChild(closeBtn);
    }

    panel.appendChild(headerRow);

    const contentWrap = document.createElement("div");
    contentWrap.style.cssText = expanded
        ? "flex:1 1 auto;display:flex;align-items:center;justify-content:center;width:100%;min-height:0;overflow:hidden;"
        : "flex:1 1 auto;display:flex;flex-direction:column;align-items:center;justify-content:flex-start;width:100%;min-height:0;overflow:hidden;";

    const cached = index < Number(runtime.cachedCount || 0)
        || clip._previewLoaded;

    const videoStyle = expanded
        ? "max-width:100%;max-height:100%;height:auto;width:auto;object-fit:contain;background:#000;border-radius:4px;flex:0 0 auto;"
        : "width:100%;max-height:180px;object-fit:contain;background:#000;border-radius:4px;flex:0 0 auto;";

    // 1. Latent preview during sampling — show live decoded frame
    if (clip._latentPreviewUrl) {
        const img = document.createElement("img");
        img.src = clip._latentPreviewUrl;
        img.style.cssText = videoStyle;
        contentWrap.appendChild(img);

        const label = document.createElement("div");
        label.style.cssText = "color:#fa3;font-size:10px;text-align:center;margin-top:3px;flex:0 0 auto;";
        const stepInfo = clip._latentStep && clip._latentTotal
            ? ` (${clip._latentStep}/${clip._latentTotal})`
            : "";
        label.textContent = "渲染中" + stepInfo;
        contentWrap.appendChild(label);

        panel.appendChild(contentWrap);
        return;
    }

    // 2. Final video ready — show first frame as thumbnail, play on click
    if (clip._previewVideoUrl) {
        const video = document.createElement("video");
        video.controls = true;
        video.playsInline = true;
        video.preload = "metadata";
        video.style.cssText = videoStyle;
        video.src = clip._previewVideoUrl;
        contentWrap.appendChild(video);
        panel.appendChild(contentWrap);
        return;
    }

    // 3. Cached/ready but video not loaded yet — auto-fetch immediately
    if (cached) {
        const loading = document.createElement("div");
        loading.style.cssText = "display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:#555;font-size:11px;gap:6px;padding:8px;";
        loading.innerHTML = '<div style="font-size:18px;opacity:.6;animation:h3spin 1s linear infinite;">&#10227;</div><div>加载预览...</div>';
        contentWrap.appendChild(loading);
        panel.appendChild(contentWrap);

        fetchClipPreview(node, index).then(videoInfo => {
            if (!videoInfo) {
                contentWrap.replaceChildren();
                const err = document.createElement("div");
                err.style.cssText = "display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:#555;font-size:11px;text-align:center;gap:6px;padding:8px;";
                err.innerHTML = '<div style="font-size:22px;opacity:.5;">&#128249;</div><div>预览不可用</div>';
                contentWrap.appendChild(err);
                return;
            }
            const url = clipPreviewMediaUrl(videoInfo) + "&t=" + Date.now();
            clip._previewVideoUrl = url;
            clip._previewLoaded = true;
            contentWrap.replaceChildren();
            const video = document.createElement("video");
            video.controls = true;
            video.playsInline = true;
            video.preload = "metadata";
            video.style.cssText = videoStyle;
            video.src = url;
            contentWrap.appendChild(video);
        });
        return;
    }

    // 4. Not cached and not rendering — placeholder or error
    const ph = document.createElement("div");
    ph.style.cssText = "display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:#555;font-size:11px;text-align:center;gap:6px;padding:8px;";
    if (clip._previewError) {
        ph.innerHTML = '<div style="font-size:18px;opacity:.5;">&#9888;</div><div style="color:#a55;">预览解码失败</div><div style="color:#777;font-size:9px;word-break:break-all;">' + clip._previewError.substring(0, 80) + '</div>';
    } else {
        ph.innerHTML = '<div style="font-size:22px;opacity:.5;">&#128249;</div><div>等待渲染</div>';
    }
    contentWrap.appendChild(ph);
    panel.appendChild(contentWrap);
}

const PROJECT_WIDGETS = [
    "run_mode",
    "width",
    "height",
    "ref_image_size",
    "steps",
    "sampler_name",
    "scheduler",
    "denoise",
    "context_length",
    "audio_context_length",
    "clips_json",
    "resolution_mode",
    "megapixels",
    "refs_json",
    "output_mode",
    "filename_prefix",
];

const FINAL_PROJECT_WIDGETS = [
    "fps",
    "filename_prefix",
    "output_directory",
    "codec",
    "crf",
    "preset",
    "audio_bitrate",
    "export_clips",
];

// Validation and reference semantics are user-controlled. The Extender never
// associates Ref N with Clip N and never decides which clip a reference edit
// invalidates. Existing validation flags stay exactly as the user left them.
// The one unavoidable global exception is RESOLUTION: cached latents cannot be
// reused at another geometry, so an effective width/height change immediately
// clears validation for the whole chain.


function emptyRefsState() {
    return { version: 2, refs: Array(MAX_IMAGE_REFS).fill(null) };
}

function normalizeRefDescriptor(value) {
    if (!value || typeof value !== "object") return null;
    const id = String(value.id || value.ref_id || "").toLowerCase();
    if (!/^[0-9a-f]{64}$/.test(id)) return null;
    const sourceCandidate = String(value.source_id || value.original_id || id).toLowerCase();
    const source_id = /^[0-9a-f]{64}$/.test(sourceCandidate) ? sourceCandidate : id;
    const adjustment = (name) => {
        const n = Number(value[name] ?? 100);
        return Number.isFinite(n) ? Math.min(200, Math.max(0, n)) : 100;
    };
    return {
        id,
        source_id,
        original_name: String(value.original_name || value.name || "reference.png"),
        width: Math.max(0, Number(value.width || 0)),
        height: Math.max(0, Number(value.height || 0)),
        size_bytes: Math.max(0, Number(value.size_bytes || 0)),
        saturation: adjustment("saturation"),
        contrast: adjustment("contrast"),
        brightness: adjustment("brightness"),
    };
}

function normalizeRefsArray(values) {
    // Ref slots are stable logical identities. Never compact holes: moving Ref 3
    // into Ref 2 would silently break prompts that intentionally use <Picture 3>.
    const refs = Array(MAX_IMAGE_REFS).fill(null);
    const source = Array.isArray(values) ? values : [];
    for (let i = 0; i < Math.min(MAX_IMAGE_REFS, source.length); i++) {
        refs[i] = normalizeRefDescriptor(source[i]);
    }
    return refs;
}

function parseRefsState(raw) {
    try {
        const parsed = typeof raw === "string" ? JSON.parse(raw || "{}") : raw;
        const refs = Array.isArray(parsed) ? parsed : parsed?.refs;
        return { version: 2, refs: normalizeRefsArray(Array.isArray(refs) ? refs : []) };
    } catch (_) {
        return emptyRefsState();
    }
}

function serializeRefsState(state) {
    return JSON.stringify({ version: 2, refs: normalizeRefsArray(state?.refs || []) });
}

function refCount(runtime) {
    return (runtime?.refsState?.refs || []).filter(Boolean).length;
}

function refImageUrl(ref) {
    if (!ref?.id) return "";
    return api.apiURL("/h3_extender/ref/image?id=" + encodeURIComponent(String(ref.id)));
}

function sameRefContent(a, b) {
    return String(a?.id || "") === String(b?.id || "");
}

function removeLegacyImageRefInputs(node) {
    if (!node?.inputs) return false;
    let removed = false;
    for (let index = node.inputs.length - 1; index >= 0; index--) {
        const name = String(node.inputs[index]?.name || "");
        if (/^ref_[1-9]$/.test(name)) {
            try {
                node.removeInput(index);
                removed = true;
            } catch (_) {}
        }
    }
    if (removed) node.graph?.setDirtyCanvas(true, true);
    return removed;
}

function randomSeed() {
    try {
        const a = new Uint32Array(2);
        crypto.getRandomValues(a);
        // stay inside JS exact-integer range
        return Number((BigInt(a[0]) << 21n) ^ BigInt(a[1] & 0x1fffff));
    } catch (_) {
        return Math.floor(Math.random() * Number.MAX_SAFE_INTEGER);
    }
}

function normalizeColorAdjustment(value) {
    const c = value && typeof value === "object" ? value : {};
    const clamp = (v, lo, hi, fallback) => {
        const n = Number(v);
        return Math.max(lo, Math.min(hi, Number.isFinite(n) ? n : fallback));
    };
    return {
        saturation: clamp(c.saturation, 0, 200, 100),
        contrast: clamp(c.contrast, 50, 150, 100),
        brightness: clamp(c.brightness, 50, 150, 100),
    };
}

function colorAdjustmentIsNeutral(value) {
    const c = normalizeColorAdjustment(value);
    return [c.saturation, c.contrast, c.brightness].every((v) => Math.abs(v - 100) < 1e-6);
}

function cssColorFilter(value) {
    const c = normalizeColorAdjustment(value);
    return `saturate(${c.saturation}%) contrast(${c.contrast}%) brightness(${c.brightness}%)`;
}

function newClip(index) {
    return {
        id: `clip_${index + 1}_${Date.now().toString(36)}`,
        name: "",
        prompt: "",
        seed: randomSeed(),
        seed_mode: "randomize",
        duration: 15.0,
        validated: false,
        context_enabled: true,
        color_adjustment: normalizeColorAdjustment(),
        card_height: 0,
        collapsed: false,
        subtitle: "",
        subtitle_enabled: false,
        subtitle_mode: "manual",
        subtitle_auto_dialogue: true,
        subtitle_auto_narration: false,
        subtitle_auto_lyrics: false,
        subtitle_font: "msyh.ttc",
        subtitle_font_size: 24,
        subtitle_color: "#FFFFFF",
        subtitle_box: false,
        subtitle_box_color: "#000000",
        subtitle_box_width: 2,
        rfe_frame_count: 15,
        rfe_selection_mode: "last_n",
        rfe_start_frame: 0,
        rfe_end_frame: 0,
        rfe_max_output_frames: 9,
        rfe_sampling_method: "even",
        rfe_save_frames: false,
        rfe_output_subdir: "contextual_series",
        rfe_filename_prefix: "frame",
        render_enabled: true,
        replace_mode: false,
    };
}

function parseState(raw) {
    try {
        const p = JSON.parse(raw || "{}");
        const clips = Array.isArray(p) ? p : p?.clips;
        if (Array.isArray(clips) && clips.length) {
            return {
                version: 1,
                load_token: String(p?.project_load_token || ""),
                prompt_pack_signature: String(p?.prompt_pack_signature || ""),
                global_prompt: String(p?.global_prompt || ""),
                merge_output: Boolean(p?.merge_output) || false,
                clips: clips.map((c, i) => {
                    const clip = {
                        id: String(c?.id || `clip_${i + 1}`),
                        name: String(c?.name || ""),
                        prompt: String(c?.prompt || ""),
                        seed: Math.max(0, Math.min(Number.MAX_SAFE_INTEGER, Number(c?.seed || 0))),
                        seed_mode: ["randomize", "fixed", "increment", "decrement"].includes(String(c?.seed_mode))
                            ? String(c.seed_mode)
                            : "randomize",
                        duration: Math.max(0.25, Math.min(300, Number(c?.duration || 15))),
                        validated: Boolean(c?.validated),
                        context_enabled: c?.context_enabled !== undefined ? Boolean(c.context_enabled) : true,
                        color_adjustment: normalizeColorAdjustment(c?.color_adjustment),
                    };
                    clip.card_height = c?.card_height || 0;
                    clip.collapsed = c?.collapsed || false;
                    clip.subtitle = c?.subtitle || "";
                    clip.subtitle_enabled = c?.subtitle_enabled || false;
                    clip.subtitle_mode = c?.subtitle_mode || "manual";
                    clip.subtitle_auto_dialogue = c?.subtitle_auto_dialogue !== undefined ? c.subtitle_auto_dialogue : true;
                    clip.subtitle_auto_narration = c?.subtitle_auto_narration || false;
                    clip.subtitle_auto_lyrics = c?.subtitle_auto_lyrics || false;
                    clip.subtitle_font = c?.subtitle_font || "msyh.ttc";
                    clip.subtitle_font_size = c?.subtitle_font_size || 24;
                    clip.subtitle_color = c?.subtitle_color || "#FFFFFF";
                    clip.subtitle_box = c?.subtitle_box || false;
                    clip.subtitle_box_color = c?.subtitle_box_color || "#000000";
                    clip.subtitle_box_width = c?.subtitle_box_width || 2;
                    clip.rfe_frame_count = c?.rfe_frame_count !== undefined ? c.rfe_frame_count : 15;
                    clip.rfe_selection_mode = c?.rfe_selection_mode || "last_n";
                    clip.rfe_start_frame = c?.rfe_start_frame !== undefined ? c.rfe_start_frame : 0;
                    clip.rfe_end_frame = c?.rfe_end_frame !== undefined ? c.rfe_end_frame : 0;
                    clip.rfe_max_output_frames = c?.rfe_max_output_frames !== undefined ? c.rfe_max_output_frames : 9;
                    clip.rfe_sampling_method = c?.rfe_sampling_method || "even";
                    clip.rfe_save_frames = c?.rfe_save_frames || false;
                    clip.rfe_output_subdir = c?.rfe_output_subdir || "contextual_series";
                    clip.rfe_filename_prefix = c?.rfe_filename_prefix || "frame";
                    clip.render_enabled = c?.render_enabled !== undefined ? Boolean(c.render_enabled) : true;
                    clip.replace_mode = c?.replace_mode !== undefined ? Boolean(c.replace_mode) : false;
                    return clip;
                }),
            };
        }
    } catch (_) {}
    return { version: 1, load_token: "", prompt_pack_signature: "", merge_output: false, clips: [newClip(0)] };
}

function serializeState(state) {
    const clips = state.clips.map((c) => {
        const { _previewLoaded, _previewVideoUrl, _previewExpanded, _previewReady, _latentPreviewUrl, _latentStep, _latentTotal, _previewError, ...rest } = c;
        return rest;
    });
    const payload = { version: 1, clips };
    if (state?.load_token) payload.project_load_token = String(state.load_token);
    if (state?.merge_output) payload.merge_output = true;
    if (state?.prompt_pack_signature) {
        payload.prompt_pack_signature = String(state.prompt_pack_signature);
    }
    if (state?.global_prompt) {
        payload.global_prompt = String(state.global_prompt);
    }
    return JSON.stringify(payload);
}

function validatedPrefixFromState(state) {
    let count = 0;
    for (const clip of state?.clips || []) {
        if (!clip?.validated) break;
        count += 1;
    }
    return count;
}

async function restoreCacheState(node, runtime) {
    if (!node || !runtime || runtime.cacheStateRequestRunning) return;

    runtime.cacheStateRequestRunning = true;
    try {
        const params = new URLSearchParams();
        params.set("owner_id", String(node.id));
        const response = await fetch(
            api.apiURL("/h3_extender/cache_state?" + params.toString())
        );
        if (!response.ok) return;

        const payload = await response.json();
        if (!payload?.found) return;

        // Do not overwrite live execution information if generation started
        // while the startup request was in flight.
        if (["preparing", "sampling", "complete"].includes(String(runtime.activePhase || ""))) {
            return;
        }

        runtime.cachedCount = Number(payload.cached_count || 0);
        for (let i = 0; i < runtime.cachedCount && i < runtime.state.clips.length; i++) {
            const c = runtime.state.clips[i];
            if (c && !c._previewVideoUrl) {
                c._previewLoaded = true;
                delete c._latentPreviewUrl;
                delete c._latentStep;
                delete c._latentTotal;
            }
        }
        runtime.validatedCount = Number(payload.validated_count || 0);
        const restoredW = Number(payload.resolved_width || 0);
        const restoredH = Number(payload.resolved_height || 0);
        if (restoredW > 0 && restoredH > 0) {
            // Cache restore is informational only. Do not overwrite live
            // resolution controls: outside an explicit .ext Load the user is
            // free to change Auto/MP or Manual width/height at any time.
            runtime.expectedResolution = { width: restoredW, height: restoredH };
        }
        runtime.cacheStateRestored = true;
        const resolutionText = restoredW > 0 && restoredH > 0
            ? ` | project ${restoredW}x${restoredH}`
            : "";
        runtime.statusText =
            `Restored cache${resolutionText} | cached ${runtime.cachedCount}/${runtime.state.clips.length} | ` +
            `validated ${runtime.validatedCount}`;
        syncResolutionAndInvalidate(node, runtime);
        render(node, runtime);
        node.graph?.setDirtyCanvas(true, true);
    } catch (_) {
        // Cache-state restoration is visual convenience only. Never block UI load.
    } finally {
        runtime.cacheStateRequestRunning = false;
    }
}

function getWidget(node, name) {
    return node?.widgets?.find((w) => w?.name === name);
}

function effectiveManualResolution(width, height) {
    const step = 32;
    const w = Math.max(step, Math.min(MAX_RESOLUTION, Math.floor(Number(width || 0) / step) * step));
    const h = Math.max(step, Math.min(MAX_RESOLUTION, Math.floor(Number(height || 0) / step) * step));
    return { width: w, height: h };
}

function pythonRound(value) {
    // Python round() uses bankers rounding for exact .5 ties; match the
    // backend so the visible mirror can never disagree by a latent-grid step.
    const x = Number(value);
    if (!Number.isFinite(x)) return 0;
    const floor = Math.floor(x);
    const frac = x - floor;
    if (Math.abs(frac - 0.5) < 1e-12) return (floor % 2 === 0) ? floor : floor + 1;
    return Math.round(x);
}

function autoResolutionFromDimensions(srcWidth, srcHeight, megapixels) {
    const srcW = Number(srcWidth || 0);
    const srcH = Number(srcHeight || 0);
    if (!(srcW > 0) || !(srcH > 0)) return null;

    const mp = Math.max(0.01, Math.min(16.0, Number(megapixels ?? DEFAULT_MEGAPIXELS)));
    const total = mp * 1024.0 * 1024.0;
    const scale = Math.sqrt(total / (srcW * srcH));
    let scaledW = srcW * scale;
    let scaledH = srcH * scale;

    if (scaledW > MAX_RESOLUTION || scaledH > MAX_RESOLUTION) {
        const shrink = Math.min(MAX_RESOLUTION / scaledW, MAX_RESOLUTION / scaledH);
        scaledW *= shrink;
        scaledH *= shrink;
    }

    // H3 32-pixel canvas. Auto snaps downward so the resolved canvas never
    // exceeds the requested megapixel budget; Manual uses the same 32px grid.
    const step = 32;
    return {
        width: Math.max(step, Math.min(MAX_RESOLUTION, Math.floor(scaledW / step) * step)),
        height: Math.max(step, Math.min(MAX_RESOLUTION, Math.floor(scaledH / step) * step)),
    };
}

function currentGuideRefNumber(runtime) {
    const refs = runtime?.refsState?.refs || [];
    if (refs[0]) return 1;
    for (let i = 0; i < Math.min(MAX_IMAGE_REFS, refs.length); i++) {
        if (refs[i]) return i + 1;
    }
    return null;
}

function dimensionsFromInternalRef(runtime, refNumber) {
    const index = Number(refNumber) - 1;
    if (!runtime || !Number.isInteger(index) || index < 0 || index >= MAX_IMAGE_REFS) return null;
    const ref = runtime.refsState?.refs?.[index];
    const width = Number(ref?.width || 0);
    const height = Number(ref?.height || 0);
    return width > 0 && height > 0 ? { width, height } : null;
}

function setResolutionMirrorValues(node, runtime, width, height) {
    if (!runtime || !(width > 0) || !(height > 0)) return;
    runtime.applyingResolutionMirror = true;
    try {
        setWidgetValue(node, "width", Number(width));
        setWidgetValue(node, "height", Number(height));
    } finally {
        runtime.applyingResolutionMirror = false;
    }
}

function rememberManualResolution(node, runtime, width, height) {
    if (!runtime) return;
    if (Number(width) > 0) runtime.manualWidth = Number(width);
    if (Number(height) > 0) runtime.manualHeight = Number(height);
    if (node) {
        node.properties = node.properties || {};
        if (runtime.manualWidth > 0) node.properties.h3_manual_width = runtime.manualWidth;
        if (runtime.manualHeight > 0) node.properties.h3_manual_height = runtime.manualHeight;
    }
}

function syncResolutionMirror(node, runtime) {
    if (!node || !runtime) return;

    const mode = String(getWidget(node, "resolution_mode")?.value || "auto_from_ref");
    const widthWidget = getWidget(node, "width");
    const heightWidget = getWidget(node, "height");
    if (!widthWidget || !heightWidget) return;

    if (mode === "manual") {
        if (runtime.manualWidth > 0 && runtime.manualHeight > 0) {
            setResolutionMirrorValues(node, runtime, runtime.manualWidth, runtime.manualHeight);
        }
        runtime.resolutionMirrorActive = false;
        return;
    }

    const guideRef = currentGuideRefNumber(runtime);
    if (guideRef == null) {
        // Auto without a reference is deliberately the editable Manual fallback.
        if (runtime.manualWidth > 0 && runtime.manualHeight > 0) {
            setResolutionMirrorValues(node, runtime, runtime.manualWidth, runtime.manualHeight);
        }
        runtime.resolutionMirrorActive = false;
        return;
    }

    let source = dimensionsFromInternalRef(runtime, guideRef);
    const executedGuide = /^ref_(\d+)$/.exec(String(runtime.resolutionGuide || ""));
    if (!source && executedGuide && Number(executedGuide[1]) === Number(guideRef)) {
        if (runtime.guideSourceWidth > 0 && runtime.guideSourceHeight > 0) {
            source = { width: runtime.guideSourceWidth, height: runtime.guideSourceHeight };
        }
    }

    if (!source) {
        // Internal metadata normally carries the exact source dimensions. Keep
        // the last backend result as a defensive fallback for older saved state.
        if (
            executedGuide &&
            Number(executedGuide[1]) === Number(guideRef) &&
            runtime.resolvedWidth > 0 && runtime.resolvedHeight > 0
        ) {
            setResolutionMirrorValues(node, runtime, runtime.resolvedWidth, runtime.resolvedHeight);
            runtime.resolutionMirrorActive = true;
        }
        return;
    }

    const resolved = autoResolutionFromDimensions(
        source.width,
        source.height,
        Number(getWidget(node, "megapixels")?.value ?? DEFAULT_MEGAPIXELS),
    );
    if (!resolved) return;
    runtime.guideSourceWidth = Number(source.width);
    runtime.guideSourceHeight = Number(source.height);
    setResolutionMirrorValues(node, runtime, resolved.width, resolved.height);
    runtime.resolutionMirrorActive = true;
    node.graph?.setDirtyCanvas(true, true);
}

function wrapResolutionWidgetCallbacks(node, runtime) {
    if (!node || !runtime || runtime.resolutionCallbacksInstalled) return;
    runtime.resolutionCallbacksInstalled = true;

    const widthWidget = getWidget(node, "width");
    const heightWidget = getWidget(node, "height");
    const modeWidget = getWidget(node, "resolution_mode");
    const mpWidget = getWidget(node, "megapixels");

    const wrap = (widget, handler) => {
        if (!widget) return;
        const old = widget.callback;
        widget.callback = function (value) {
            const result = old ? old.apply(this, arguments) : undefined;
            handler(value);
            return result;
        };
    };

    wrap(widthWidget, (value) => {
        if (runtime.applyingResolutionMirror) return;
        const mode = String(modeWidget?.value || "auto_from_ref");
        if (mode === "manual" || currentGuideRefNumber(runtime) == null) {
            // A loaded .ext is forced to its exact archived geometry only at
            // load time. The first explicit resolution edit releases that
            // one-shot project state immediately.
            runtime.projectResolutionLoaded = false;
            rememberManualResolution(
                node,
                runtime,
                Number(value || widthWidget?.value || runtime.manualWidth || 896),
                runtime.manualHeight,
            );
            invalidateForResolutionChange(node, runtime);
        } else {
            requestAnimationFrame(() => syncResolutionAndInvalidate(node, runtime));
        }
    });
    wrap(heightWidget, (value) => {
        if (runtime.applyingResolutionMirror) return;
        const mode = String(modeWidget?.value || "auto_from_ref");
        if (mode === "manual" || currentGuideRefNumber(runtime) == null) {
            runtime.projectResolutionLoaded = false;
            rememberManualResolution(
                node,
                runtime,
                runtime.manualWidth,
                Number(value || heightWidget?.value || runtime.manualHeight || 576),
            );
            invalidateForResolutionChange(node, runtime);
        } else {
            requestAnimationFrame(() => syncResolutionAndInvalidate(node, runtime));
        }
    });
    wrap(modeWidget, (value) => {
        runtime.projectResolutionLoaded = false;
        const mode = String(value || modeWidget?.value || "auto_from_ref");
        if (mode === "auto_from_ref" && !runtime.resolutionMirrorActive) {
            rememberManualResolution(
                node,
                runtime,
                Number(widthWidget?.value || runtime.manualWidth || 896),
                Number(heightWidget?.value || runtime.manualHeight || 576),
            );
        }
        requestAnimationFrame(() => syncResolutionAndInvalidate(node, runtime));
    });
    wrap(mpWidget, () => {
        // Load Project deliberately enters Manual at the archived width/height
        // so simply pressing Queue cannot invalidate the imported cache. But
        // megapixels is an Auto-only control: if the user edits it after a
        // project load, that is an explicit request to choose a new resolution.
        // Re-enter Auto immediately instead of leaving the MP widget apparently
        // ineffective. The backend will then restart the incompatible cache on
        // the next generation, exactly like any other live resolution change.
        if (runtime.projectResolutionLoaded) {
            runtime.projectResolutionLoaded = false;
            setWidgetValue(node, "resolution_mode", "auto_from_ref");
        }
        requestAnimationFrame(() => syncResolutionAndInvalidate(node, runtime));
    });
}

// Nodes 2.0 (Vue) can render the native multiline STRING row before our
// onNodeCreated code gets a chance to touch the widget object. Hide that row
// pre-emptively with CSS, using the same proven strategy as ComfyUI_Stem_Mixer.
// MiniMaxH3Extender keeps clips_json + refs_json as native serialized textareas.
(function injectStateJsonHideRule() {
    if (document.getElementById("h3-extender-hide-state-json")) return;
    const style = document.createElement("style");
    style.id = "h3-extender-hide-state-json";
    style.textContent = `
        .lg-node-widget:has(> [node-type="${TARGET}"] > textarea) {
            display: none !important;
        }
    `;
    document.head.appendChild(style);
})();

function hideNativeWidget(node, widget) {
    if (!widget) return;

    // LiteGraph / Nodes 1.0: remove the logical footprint but keep the widget
    // itself intact so its normal workflow serialization continues to work.
    // Do NOT use canvasOnly/hidden here: Vue does not reliably honour those
    // flags for native widgets, while the pre-emptive CSS above does.
    widget.computeSize = () => [0, -4];
    widget.computeLayoutSize = () => ({
        minWidth: 0,
        minHeight: 0,
        maxWidth: 0,
        maxHeight: 0,
    });

    // LiteGraph may recreate the textarea when the node leaves/re-enters the
    // viewport, so re-hide the actual legacy DOM element on every foreground
    // draw, exactly as Stem Mixer does for its state widget.
    const oldDrawForeground = node?.onDrawForeground;
    if (node) {
        node.onDrawForeground = function (ctx) {
            if (oldDrawForeground) oldDrawForeground.apply(this, arguments);
            const inputEl = widget.inputEl;
            if (inputEl) {
                if (inputEl.style.display !== "none") inputEl.style.display = "none";
                const parent = inputEl.parentElement;
                if (parent && parent.style.display !== "none") {
                    parent.style.display = "none";
                }
            }
        };
    }
}

function domWidgetRenderMode(element) {
    // ComfyUI exposes the renderer state on LiteGraph.vueNodesMode. Use that
    // as the authority, but wait while the DOM widget is being re-parented so
    // we never apply Legacy sizing with a stale Vue last_y (or vice versa).
    const LG = globalThis.LiteGraph;
    const hasModeFlag = typeof LG?.vueNodesMode === "boolean";
    if (!element?.isConnected) return "pending";

    const insideVueRow = Boolean(element.closest?.(".lg-node-widget"));
    if (hasModeFlag) {
        if (LG.vueNodesMode && !insideVueRow) return "pending";
        if (!LG.vueNodesMode && insideVueRow) return "pending";
        return LG.vueNodesMode ? "nodes2" : "legacy";
    }

    // Older frontends may not expose vueNodesMode; fall back to the wrapper.
    return insideVueRow ? "nodes2" : "legacy";
}

function obviouslyPoisonedHeight(height, minimumHeight) {
    const h = Number(height);
    if (!Number.isFinite(h) || h <= 0) return false;
    return h > Math.max(1800, Number(minimumHeight || 0) * 3);
}

function invalidateFrom(state, index) {
    for (let i = Math.max(0, index); i < state.clips.length; i++) {
        state.clips[i].validated = false;
        state.clips[i]._previewLoaded = false;
        delete state.clips[i]._previewVideoUrl;
        delete state.clips[i]._latentPreviewUrl;
        delete state.clips[i]._latentStep;
        delete state.clips[i]._latentTotal;
    }
}

/**
 * Parse storyboard text into segments.
 * Looks for [分镜N] markers and splits text accordingly.
 * For each segment, extracts the full prompt text and the last time range
 * (e.g. "6-9秒" → 9) as the clip duration.
 *
 * 解析分镜文本：按 [分镜N] 标记拆分为多段，提取每段提示词和时长。
 */
function parseStoryboard(text) {
    if (!text || !String(text).trim()) return [];
    const raw = String(text);
    // Match [分镜1], [分镜2], etc. (also support [Shot1], [shot1])
    const markerRe = /\[(?:分镜|Shot|shot|SHOT)\s*(\d+)\]/g;
    const segments = [];
    let match;
    const indices = [];
    while ((match = markerRe.exec(raw)) !== null) {
        indices.push({ num: parseInt(match[1], 10), pos: match.index, markerLen: match[0].length });
    }
    if (indices.length === 0) return [];
    for (let i = 0; i < indices.length; i++) {
        const start = indices[i].pos + indices[i].markerLen;
        const end = i + 1 < indices.length ? indices[i + 1].pos : raw.length;
        let segmentText = raw.slice(start, end).trim();
        // Extract the last time range like "N-Ns" or "N-N秒" from the segment
        // e.g. "0-3秒...3-6秒...6-9秒" → 9
        let duration = 15; // default
        const timeRe = /(\d+(?:\.\d+)?)\s*[-–—~至到]\s*(\d+(?:\.\d+)?)\s*(?:秒|s|sec)/gi;
        let lastTimeMatch;
        let tm;
        while ((tm = timeRe.exec(segmentText)) !== null) {
            lastTimeMatch = tm;
        }
        if (lastTimeMatch) {
            duration = parseFloat(lastTimeMatch[2]);
        }
        // Clean up: remove the segment title line (e.g. "初始的觊觎\n")
        // but keep the rest as the prompt
        segments.push({
            num: indices[i].num,
            prompt: segmentText,
            duration: duration,
        });
    }
    return segments;
}

function currentResolutionFromWidgets(node) {
    const width = Number(getWidget(node, "width")?.value || 0);
    const height = Number(getWidget(node, "height")?.value || 0);
    if (!(width > 0) || !(height > 0)) return null;
    return effectiveManualResolution(width, height);
}

function invalidateForResolutionChange(node, runtime) {
    if (!node || !runtime?.state) return false;
    const expected = runtime.expectedResolution;
    const current = currentResolutionFromWidgets(node);
    if (!expected || !current) return false;

    const expectedW = Number(expected.width || 0);
    const expectedH = Number(expected.height || 0);
    if (!(expectedW > 0) || !(expectedH > 0)) return false;
    if (current.width === expectedW && current.height === expectedH) return false;

    const hadValidated = runtime.state.clips.some((clip) => Boolean(clip?.validated));
    const hadCached = Number(runtime.cachedCount || 0) > 0;

    // Once the requested geometry differs from the cache/project geometry,
    // every latent in that chain is incompatible. Reflect that immediately in
    // the cards instead of waiting for the backend to discover it at Queue.
    for (const clip of runtime.state.clips) {
        clip.validated = false;
        clip._previewLoaded = false;
        delete clip._previewVideoUrl;
        delete clip._latentPreviewUrl;
        delete clip._latentStep;
        delete clip._latentTotal;
    }
    runtime.validatedCount = 0;
    runtime.cachedCount = 0;
    runtime.resolutionInvalidated = true;
    runtime.statusText = "Ready";

    if (hadValidated || hadCached) updateHidden(node, runtime);
    render(node, runtime);
    node.graph?.setDirtyCanvas(true, true);
    return hadValidated || hadCached;
}

function syncResolutionAndInvalidate(node, runtime) {
    syncResolutionMirror(node, runtime);
    invalidateForResolutionChange(node, runtime);
}


function advanceSeedAfterGenerate(clip) {
    const mode = String(clip?.seed_mode || "randomize");
    const max = Number.MAX_SAFE_INTEGER;
    const current = Math.max(0, Math.min(max, Math.trunc(Number(clip?.seed || 0))));

    if (mode === "randomize") {
        let next = randomSeed();
        // Extremely unlikely, but never leave the node cache-identical.
        if (next === current) next = (current + 1) % (max + 1);
        clip.seed = next;
    } else if (mode === "increment") {
        clip.seed = current >= max ? 0 : current + 1;
    } else if (mode === "decrement") {
        clip.seed = current <= 0 ? max : current - 1;
    }
    // fixed deliberately does nothing.
}

function cardStatus(runtime, clip, index) {
    if (
        Number(runtime.activeClipIndex) === index &&
        ["preparing", "sampling", "complete"].includes(String(runtime.activePhase || ""))
    ) {
        return "rendering";
    }

    const cached = index < Number(runtime.cachedCount || 0);
    if (clip.validated && cached) return "validated";
    const firstOpen = runtime.state.clips.findIndex((c) => !c.validated);
    if (index === firstOpen) return cached ? "candidate" : "current";
    if (cached) return "cached";
    return "future";
}

function updateHidden(node, runtime) {
    const raw = serializeState(runtime.state);
    runtime.jsonWidget.value = raw;
    node.graph?.setDirtyCanvas(true, true);
}

function updateRefsHidden(node, runtime) {
    if (!runtime?.refsWidget) return;
    runtime.refsState.refs = normalizeRefsArray(runtime.refsState?.refs || []);
    runtime.refsWidget.value = serializeRefsState(runtime.refsState);
    node.graph?.setDirtyCanvas(true, true);
}

function handleReferenceChange(node, runtime, message = "Image references changed") {
    if (!node || !runtime?.state) return;

    // Reference edits are deliberately user-controlled. Do not infer any
    // Ref-to-Clip relationship and do not change validation automatically.
    updateRefsHidden(node, runtime);

    // Auto resolution still follows the active guide ref. If the ref edit changes
    // the effective geometry, the existing resolution safety rule necessarily
    // invalidates the whole latent chain; that is independent of ref semantics.
    syncResolutionAndInvalidate(node, runtime);

    if (!runtime.resolutionInvalidated) {
        runtime.statusText = `${message} | validations unchanged`;
        render(node, runtime);
    }
}

function openReferenceEditor(node, runtime, slotIndex, ref) {
    if (!ref?.id || !node || !runtime) return;
    if (projectBusy(runtime) || runtime.refBusy || runtime.projectOperationBusy) {
        alert("Wait for the current clip generation to finish before editing a reference image.");
        return;
    }

    const overlay = document.createElement("div");
    overlay.style.position = "fixed";
    overlay.style.inset = "0";
    overlay.style.zIndex = "100000";
    overlay.style.background = "rgba(0,0,0,.86)";
    overlay.style.display = "flex";
    overlay.style.alignItems = "center";
    overlay.style.justifyContent = "center";
    overlay.style.padding = "24px";
    overlay.style.boxSizing = "border-box";

    const panel = document.createElement("div");
    panel.style.width = "min(1180px, 94vw)";
    panel.style.height = "min(820px, 92vh)";
    panel.style.minWidth = "0";
    panel.style.minHeight = "0";
    panel.style.display = "flex";
    panel.style.flexDirection = "column";
    panel.style.background = "#191919";
    panel.style.border = "1px solid rgba(255,255,255,.18)";
    panel.style.borderRadius = "10px";
    panel.style.boxShadow = "0 18px 60px rgba(0,0,0,.65)";
    panel.style.overflow = "hidden";
    overlay.appendChild(panel);

    const header = document.createElement("div");
    header.style.display = "flex";
    header.style.alignItems = "center";
    header.style.justifyContent = "space-between";
    header.style.gap = "12px";
    header.style.padding = "10px 12px";
    header.style.borderBottom = "1px solid rgba(255,255,255,.12)";

    const title = document.createElement("div");
    title.textContent = `Reference Editor — Ref ${slotIndex + 1}`;
    title.style.fontWeight = "650";
    title.style.fontSize = "13px";
    title.style.overflow = "hidden";
    title.style.textOverflow = "ellipsis";
    title.style.whiteSpace = "nowrap";
    title.title = ref.original_name || `Ref ${slotIndex + 1}`;

    const closeButton = document.createElement("button");
    closeButton.textContent = "×";
    closeButton.title = "Close";
    closeButton.style.width = "28px";
    closeButton.style.minWidth = "28px";
    closeButton.style.height = "26px";
    closeButton.style.padding = "0";
    closeButton.style.fontSize = "18px";
    header.append(title, closeButton);
    panel.appendChild(header);

    const body = document.createElement("div");
    body.style.flex = "1 1 auto";
    body.style.minHeight = "0";
    body.style.minWidth = "0";
    body.style.display = "flex";
    body.style.gap = "0";
    panel.appendChild(body);

    const previewWrap = document.createElement("div");
    previewWrap.style.flex = "1 1 auto";
    previewWrap.style.minWidth = "0";
    previewWrap.style.minHeight = "0";
    previewWrap.style.display = "flex";
    previewWrap.style.alignItems = "center";
    previewWrap.style.justifyContent = "center";
    previewWrap.style.padding = "14px";
    previewWrap.style.boxSizing = "border-box";
    previewWrap.style.background = "#0f0f0f";

    const image = document.createElement("img");
    const sourceRef = { ...ref, id: ref.source_id || ref.id };
    image.src = refImageUrl(sourceRef);
    image.alt = ref.original_name || "Reference image";
    image.style.maxWidth = "100%";
    image.style.maxHeight = "100%";
    image.style.objectFit = "contain";
    image.style.borderRadius = "6px";
    image.style.boxShadow = "0 8px 30px rgba(0,0,0,.45)";
    image.draggable = false;
    previewWrap.appendChild(image);
    body.appendChild(previewWrap);

    const controls = document.createElement("div");
    controls.style.flex = "0 0 235px";
    controls.style.width = "235px";
    controls.style.boxSizing = "border-box";
    controls.style.padding = "14px";
    controls.style.borderLeft = "1px solid rgba(255,255,255,.12)";
    controls.style.display = "flex";
    controls.style.flexDirection = "column";
    controls.style.gap = "12px";
    controls.style.overflowY = "auto";
    body.appendChild(controls);

    const makeControl = (labelText) => {
        const wrap = document.createElement("div");
        wrap.style.display = "block";
        wrap.style.fontSize = "11px";
        wrap.style.fontWeight = "600";

        const headerRow = document.createElement("div");
        headerRow.style.display = "flex";
        headerRow.style.alignItems = "center";
        headerRow.style.justifyContent = "space-between";
        headerRow.style.gap = "8px";
        headerRow.style.marginBottom = "4px";

        const label = document.createElement("div");
        label.textContent = labelText;

        const number = document.createElement("input");
        number.type = "number";
        number.min = "0";
        number.max = "200";
        number.step = "1";
        number.value = "100";
        number.style.width = "58px";
        number.style.boxSizing = "border-box";
        number.style.padding = "3px 5px";
        number.style.borderRadius = "5px";
        number.style.border = "1px solid rgba(255,255,255,.18)";
        number.style.background = "rgba(0,0,0,.28)";
        number.style.color = "inherit";
        number.style.textAlign = "right";

        const slider = document.createElement("input");
        slider.type = "range";
        slider.min = "0";
        slider.max = "200";
        slider.step = "1";
        slider.value = "100";
        slider.style.width = "100%";
        slider.style.margin = "0";
        slider.style.padding = "0";
        slider.style.boxSizing = "border-box";
        slider.title = `${labelText}: 100`;

        headerRow.append(label, number);
        wrap.append(headerRow, slider);
        controls.appendChild(wrap);
        return { slider, number, labelText };
    };

    const saturation = makeControl("Saturation (%)");
    const contrast = makeControl("Contrast (%)");
    const brightness = makeControl("Brightness (%)");

    const help = document.createElement("div");
    help.textContent = "100 = original image. Edits are always calculated from the initially loaded reference, so Reset truly restores the original pixels.";
    help.style.fontSize = "10px";
    help.style.lineHeight = "1.35";
    help.style.opacity = ".66";
    controls.appendChild(help);

    const spacer = document.createElement("div");
    spacer.style.flex = "1 1 auto";
    controls.appendChild(spacer);

    const buttons = document.createElement("div");
    buttons.style.display = "grid";
    buttons.style.gridTemplateColumns = "1fr 1fr";
    buttons.style.gap = "7px";

    const reset = document.createElement("button");
    reset.textContent = "重置 / Reset";
    const cancel = document.createElement("button");
    cancel.textContent = "取消 / Cancel";
    const apply = document.createElement("button");
    apply.textContent = "应用 / Apply";
    apply.style.gridColumn = "1 / -1";
    apply.style.fontWeight = "650";
    buttons.append(reset, cancel, apply);
    controls.appendChild(buttons);

    const numericValue = (control) => {
        const value = Number(control.slider.value);
        if (!Number.isFinite(value)) return 100;
        return Math.min(200, Math.max(0, value));
    };

    const setControlValue = (control, value) => {
        const parsed = Number(value);
        const clamped = Number.isFinite(parsed) ? Math.min(200, Math.max(0, parsed)) : 100;
        const text = String(Math.round(clamped));
        control.slider.value = text;
        control.number.value = text;
        control.slider.title = `${control.labelText}: ${text}`;
    };

    setControlValue(saturation, ref.saturation ?? 100);
    setControlValue(contrast, ref.contrast ?? 100);
    setControlValue(brightness, ref.brightness ?? 100);

    const updatePreview = () => {
        const b = numericValue(brightness);
        const c = numericValue(contrast);
        const sat = numericValue(saturation);
        image.style.filter = `brightness(${b}%) contrast(${c}%) saturate(${sat}%)`;
    };
    for (const control of [saturation, contrast, brightness]) {
        control.slider.addEventListener("input", () => {
            control.number.value = control.slider.value;
            control.slider.title = `${control.labelText}: ${control.slider.value}`;
            updatePreview();
        });
        control.number.addEventListener("input", () => {
            const value = Number(control.number.value);
            if (Number.isFinite(value)) {
                setControlValue(control, value);
                updatePreview();
            }
        });
        control.number.addEventListener("change", () => {
            setControlValue(control, control.number.value);
            updatePreview();
        });
    }
    updatePreview();

    let closed = false;
    const close = () => {
        if (closed) return;
        closed = true;
        window.removeEventListener("keydown", onKey);
        overlay.remove();
    };
    const onKey = (event) => {
        if (event.key === "Escape") close();
    };
    closeButton.addEventListener("click", close);
    cancel.addEventListener("click", close);
    overlay.addEventListener("click", close);
    panel.addEventListener("click", (event) => event.stopPropagation());
    window.addEventListener("keydown", onKey);

    reset.addEventListener("click", () => {
        setControlValue(saturation, 100);
        setControlValue(contrast, 100);
        setControlValue(brightness, 100);
        updatePreview();
    });

    apply.addEventListener("click", async () => {
        if (projectBusy(runtime) || runtime.refBusy || runtime.projectOperationBusy) {
            alert("Wait for the current clip generation to finish before editing a reference image.");
            return;
        }
        apply.disabled = true;
        reset.disabled = true;
        cancel.disabled = true;
        runtime.refBusy = true;
        runtime.statusText = `Applying Ref ${slotIndex + 1} adjustments…`;
        render(node, runtime);
        try {
            const response = await fetch(api.apiURL("/h3_extender/ref/edit"), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    ref_id: ref.id,
                    source_id: ref.source_id || ref.id,
                    original_name: ref.original_name || `ref_${slotIndex + 1}.png`,
                    saturation: numericValue(saturation),
                    contrast: numericValue(contrast),
                    brightness: numericValue(brightness),
                }),
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok || !payload?.ok || !payload?.ref) {
                throw new Error(payload?.error || `Reference edit failed (${response.status}).`);
            }
            const newRef = normalizeRefDescriptor(payload.ref);
            if (!newRef) throw new Error("The backend returned invalid reference metadata.");

            const current = runtime.refsState.refs[slotIndex];
            if (!current || String(current.id) !== String(ref.id)) {
                throw new Error(`Ref ${slotIndex + 1} changed while the editor was open.`);
            }

            runtime.refsState.refs[slotIndex] = newRef;
            if (sameRefContent(ref, newRef)) {
                updateRefsHidden(node, runtime);
                runtime.statusText = `Ref ${slotIndex + 1} unchanged`;
                render(node, runtime);
            } else {
                handleReferenceChange(node, runtime, `Ref ${slotIndex + 1} adjusted`);
            }
            close();
        } catch (error) {
            runtime.statusText = "Reference edit failed";
            render(node, runtime);
            alert(String(error?.message || error));
            apply.disabled = false;
            reset.disabled = false;
            cancel.disabled = false;
        } finally {
            runtime.refBusy = false;
            render(node, runtime);
        }
    });

    document.body.appendChild(overlay);
}

async function uploadReference(node, runtime, slotIndex, file) {
    if (!node || !runtime || !file) return;
    if (projectBusy(runtime)) {
        alert("Wait for the current clip generation to finish before changing a reference image.");
        return;
    }

    runtime.refBusy = true;
    runtime.statusText = `Loading Ref ${slotIndex + 1}: ${file.name}…`;
    render(node, runtime);
    try {
        const form = new FormData();
        form.append("ref_file", file, file.name);
        const response = await fetch(api.apiURL("/h3_extender/ref/upload"), {
            method: "POST",
            body: form,
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || !payload?.ok || !payload?.ref) {
            throw new Error(payload?.error || `Reference upload failed (${response.status}).`);
        }

        const newRef = normalizeRefDescriptor(payload.ref);
        if (!newRef) throw new Error("The backend returned invalid reference metadata.");
        const previous = runtime.refsState.refs[slotIndex];
        if (sameRefContent(previous, newRef)) {
            runtime.refsState.refs[slotIndex] = newRef;
            updateRefsHidden(node, runtime);
            runtime.statusText = `Ref ${slotIndex + 1} unchanged`;
            render(node, runtime);
            return;
        }

        runtime.refsState.refs[slotIndex] = newRef;
        handleReferenceChange(node, runtime, `Ref ${slotIndex + 1} loaded`);
    } catch (error) {
        runtime.statusText = "Reference load failed";
        render(node, runtime);
        alert(String(error?.message || error));
    } finally {
        runtime.refBusy = false;
        render(node, runtime);
    }
}

function removeReference(node, runtime, slotIndex) {
    if (!runtime?.refsState?.refs?.[slotIndex]) return;
    if (projectBusy(runtime)) {
        alert("Wait for the current clip generation to finish before changing a reference image.");
        return;
    }
    const oldName = runtime.refsState.refs[slotIndex]?.original_name || `Ref ${slotIndex + 1}`;
    runtime.refsState.refs[slotIndex] = null;
    handleReferenceChange(node, runtime, `${oldName} removed`);
}

function nodeIs(node, className) {
    return node?.comfyClass === className || node?.type === className;
}

function connectedFinalDecode(node) {
    const graph = node?.graph || app.graph;
    if (!graph) return null;
    const output = (node.outputs || []).find((o) => o?.name === "cache") || node.outputs?.[0];
    for (const linkId of output?.links || []) {
        const link = graph.links?.[linkId];
        if (!link) continue;
        const target = graph.getNodeById?.(link.target_id)
            || (graph._nodes || []).find((n) => String(n?.id) === String(link.target_id));
        if (target && nodeIs(target, FINAL_TARGET)) return target;
    }
    return null;
}

function colorMediaUrl(info) {
    const params = new URLSearchParams();
    params.set("filename", info?.filename || "");
    params.set("type", info?.type || "temp");
    params.set("subfolder", info?.subfolder || "");
    return api.apiURL("/view?" + params.toString());
}

function colorAtTimelineTime(timeline, time, targetIndex, liveAdjustment) {
    const t = Number(time || 0);
    for (const item of timeline || []) {
        const start = Number(item?.start || 0);
        const end = Number(item?.end || start);
        if (t >= start && t < end) {
            if (Number(item?.index) === Number(targetIndex)) return liveAdjustment;
            return normalizeColorAdjustment(item?.adjustment);
        }
    }
    return normalizeColorAdjustment();
}

function closeColorEditor(overlay) {
    try {
        const video = overlay?.querySelector?.("video");
        if (video) {
            video.pause();
            video.removeAttribute("src");
            video.load();
        }
    } catch (_) {}
    overlay?.remove?.();
}

async function openClipColorEditor(node, runtime, clipIndex) {
    const finalNode = connectedFinalDecode(node);
    if (!finalNode) {
        alert("Connect the Extender cache output to Final Decode / Preview first.");
        return;
    }

    const params = new URLSearchParams();
    params.set("owner_id", String(node.id));
    params.set("final_id", String(finalNode.id));
    params.set("clip_index", String(clipIndex));

    let payload;
    try {
        const response = await fetch(
            api.apiURL("/h3_extender/color_editor_info?" + params.toString())
        );
        payload = await response.json().catch(() => ({}));
        if (!response.ok || !payload?.ok) {
            throw new Error(payload?.error || `Color editor failed (${response.status}).`);
        }
    } catch (error) {
        alert(`Color editor unavailable:\n${error?.message || error}`);
        return;
    }

    const timeline = Array.isArray(payload.timeline) ? payload.timeline : [];
    const target = timeline.find((item) => Number(item?.index) === Number(clipIndex));
    if (!target || !payload?.video?.filename) {
        alert("The decoded clip preview is not available yet.");
        return;
    }

    const clip = runtime.state.clips[clipIndex];
    let adjustment = normalizeColorAdjustment(
        clip?.color_adjustment || target?.adjustment
    );

    const overlay = document.createElement("div");
    overlay.style.position = "fixed";
    overlay.style.inset = "0";
    overlay.style.zIndex = "100000";
    overlay.style.background = "rgba(0,0,0,.78)";
    overlay.style.display = "flex";
    overlay.style.alignItems = "center";
    overlay.style.justifyContent = "center";
    overlay.style.padding = "24px";
    overlay.style.boxSizing = "border-box";

    const dialog = document.createElement("div");
    dialog.style.width = "min(1040px, 94vw)";
    dialog.style.maxHeight = "92vh";
    dialog.style.overflow = "auto";
    dialog.style.background = "#171717";
    dialog.style.color = "#f0f0f0";
    dialog.style.border = "1px solid rgba(255,255,255,.18)";
    dialog.style.borderRadius = "10px";
    dialog.style.boxShadow = "0 18px 60px rgba(0,0,0,.65)";
    dialog.style.padding = "14px";
    dialog.style.boxSizing = "border-box";

    const header = document.createElement("div");
    header.style.display = "flex";
    header.style.alignItems = "center";
    header.style.justifyContent = "space-between";
    header.style.gap = "12px";
    header.style.marginBottom = "10px";

    const title = document.createElement("strong");
    const clipName = String(clip?.name || "").trim();
    title.textContent = `Color Edit — Clip ${clipIndex + 1}${clipName ? ` — ${clipName}` : ""}`;
    title.style.fontSize = "15px";

    const close = document.createElement("button");
    close.textContent = "✕";
    close.title = "Close";
    close.style.width = "30px";
    close.style.height = "26px";
    close.style.cursor = "pointer";
    close.addEventListener("click", () => closeColorEditor(overlay));
    header.append(title, close);

    const video = document.createElement("video");
    video.controls = true;
    video.playsInline = true;
    video.preload = "auto";
    video.style.display = "block";
    video.style.width = "100%";
    video.style.maxHeight = "58vh";
    video.style.objectFit = "contain";
    video.style.background = "#000";
    video.style.borderRadius = "6px";

    const totalEnd = timeline.length ? Number(timeline[timeline.length - 1]?.end || 0) : Number(target.end || 0);
    const loopStart = Math.max(0, Number(target.start || 0) - 2.0);
    const loopEnd = Math.min(totalEnd, Number(target.end || 0) + 2.0);

    const loopInfo = document.createElement("div");
    loopInfo.textContent = `Loop: ${loopStart.toFixed(2)}s → ${loopEnd.toFixed(2)}s  •  target ${Number(target.start).toFixed(2)}s → ${Number(target.end).toFixed(2)}s`;
    loopInfo.style.fontSize = "11px";
    loopInfo.style.opacity = ".72";
    loopInfo.style.margin = "7px 0 10px";

    const controls = document.createElement("div");
    controls.style.display = "grid";
    controls.style.gridTemplateColumns = "1fr";
    controls.style.gap = "8px";

    const valueInputs = {};
    const sliderRows = [];
    const makeSlider = (key, label, min, max) => {
        const row = document.createElement("div");
        row.style.display = "grid";
        row.style.gridTemplateColumns = "100px 1fr 64px";
        row.style.gap = "10px";
        row.style.alignItems = "center";

        const text = document.createElement("span");
        text.textContent = label;
        text.style.fontSize = "12px";

        const slider = document.createElement("input");
        slider.type = "range";
        slider.min = String(min);
        slider.max = String(max);
        slider.step = "1";
        slider.value = String(Math.round(adjustment[key]));
        slider.style.width = "100%";

        const number = document.createElement("input");
        number.type = "number";
        number.min = String(min);
        number.max = String(max);
        number.step = "1";
        number.value = String(Math.round(adjustment[key]));
        number.style.width = "64px";
        number.style.boxSizing = "border-box";
        number.style.background = "rgba(0,0,0,.35)";
        number.style.color = "inherit";
        number.style.border = "1px solid rgba(255,255,255,.18)";
        number.style.borderRadius = "4px";
        number.style.padding = "3px 5px";

        const update = (raw) => {
            const n = Math.max(min, Math.min(max, Number(raw)));
            adjustment = { ...adjustment, [key]: Number.isFinite(n) ? n : 100 };
            slider.value = String(Math.round(adjustment[key]));
            number.value = String(Math.round(adjustment[key]));
            updateLiveFilter();
        };
        slider.addEventListener("input", () => update(slider.value));
        number.addEventListener("input", () => update(number.value));
        valueInputs[key] = { slider, number, update };
        row.append(text, slider, number);
        sliderRows.push(row);
        controls.appendChild(row);
    };

    const updateLiveFilter = () => {
        const c = colorAtTimelineTime(timeline, video.currentTime, clipIndex, adjustment);
        video.style.filter = cssColorFilter(c);
    };

    makeSlider("saturation", "Saturation", 0, 200);
    makeSlider("contrast", "Contrast", 50, 150);
    makeSlider("brightness", "Brightness", 50, 150);

    const buttons = document.createElement("div");
    buttons.style.display = "flex";
    buttons.style.justifyContent = "flex-end";
    buttons.style.gap = "8px";
    buttons.style.marginTop = "12px";

    const reset = document.createElement("button");
    reset.textContent = "重置 / Reset";
    reset.title = "Return this clip to neutral 100 / 100 / 100";
    reset.addEventListener("click", () => {
        adjustment = normalizeColorAdjustment();
        for (const [key, pair] of Object.entries(valueInputs)) {
            pair.slider.value = String(Math.round(adjustment[key]));
            pair.number.value = String(Math.round(adjustment[key]));
        }
        updateLiveFilter();
    });

    const cancel = document.createElement("button");
    cancel.textContent = "取消 / Cancel";
    cancel.addEventListener("click", () => closeColorEditor(overlay));

    const apply = document.createElement("button");
    apply.textContent = "应用 / Apply";
    apply.style.fontWeight = "700";
    apply.style.minWidth = "84px";
    apply.addEventListener("click", async () => {
        apply.disabled = true;
        apply.textContent = "应用中... / Applying...";
        try {
            const response = await fetch(api.apiURL("/h3_extender/color_adjust"), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    owner_id: String(node.id),
                    clip_index: Number(clipIndex),
                    adjustment: normalizeColorAdjustment(adjustment),
                }),
            });
            const result = await response.json().catch(() => ({}));
            if (!response.ok || !result?.ok) {
                throw new Error(result?.error || `Color adjustment failed (${response.status}).`);
            }
            clip.color_adjustment = normalizeColorAdjustment(result.adjustment);
            updateHidden(node, runtime);
            runtime.statusText = result.modified
                ? `Clip ${clipIndex + 1} color correction saved`
                : `Clip ${clipIndex + 1} color correction reset`;
            render(node, runtime);
            window.dispatchEvent(new CustomEvent("h3-extender-color-updated", {
                detail: {
                    owner_id: String(node.id),
                    color_timeline: Array.isArray(result.timeline) ? result.timeline : [],
                },
            }));
            node.graph?.setDirtyCanvas(true, true);
            closeColorEditor(overlay);
        } catch (error) {
            alert(`Color adjustment failed:\n${error?.message || error}`);
            apply.disabled = false;
            apply.textContent = "应用 / Apply";
        }
    });

    buttons.append(reset, cancel, apply);
    dialog.append(header, video, loopInfo, controls, buttons);
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);

    overlay.addEventListener("mousedown", (event) => {
        if (event.target === overlay) closeColorEditor(overlay);
    });
    const keyHandler = (event) => {
        if (event.key === "Escape" && overlay.isConnected) {
            closeColorEditor(overlay);
            document.removeEventListener("keydown", keyHandler);
        }
    };
    document.addEventListener("keydown", keyHandler);

    video.addEventListener("loadedmetadata", () => {
        video.currentTime = loopStart;
        updateLiveFilter();
        video.play().catch(() => {});
    });
    video.addEventListener("timeupdate", () => {
        if (video.currentTime >= loopEnd - 0.015 || video.currentTime < loopStart - 0.05) {
            video.currentTime = loopStart;
        }
        updateLiveFilter();
    });
    video.addEventListener("seeked", updateLiveFilter);
    if (typeof video.requestVideoFrameCallback === "function") {
        const colorFrameTick = () => {
            if (!overlay.isConnected) return;
            if (video.currentTime >= loopEnd - 0.015 || video.currentTime < loopStart - 0.05) {
                video.currentTime = loopStart;
            }
            updateLiveFilter();
            video.requestVideoFrameCallback(colorFrameTick);
        };
        video.requestVideoFrameCallback(colorFrameTick);
    }
    video.src = colorMediaUrl(payload.video) + "&t=" + Date.now();
    video.load();
}

function collectWidgetValues(node, names) {
    const out = {};
    for (const name of names) {
        const widget = getWidget(node, name);
        if (widget) out[name] = widget.value;
    }
    return out;
}

function collectConnectionSummary(node) {
    const out = {};
    for (const input of node?.inputs || []) {
        out[String(input?.name || "")] = input?.link != null;
    }
    return out;
}

function collectProjectPayload(node, runtime) {
    updateHidden(node, runtime);
    updateRefsHidden(node, runtime);
    const finalNode = connectedFinalDecode(node);
    const settings = collectWidgetValues(node, PROJECT_WIDGETS);
    // In Auto mode the visible width/height widgets are mirrors of the active
    // derived resolution. Preserve the user's Manual fallback separately so a
    // later Auto -> Manual switch restores what they actually entered.
    settings.width = Number(runtime.manualWidth || settings.width || 896);
    settings.height = Number(runtime.manualHeight || settings.height || 576);
    return {
        schema_version: 2,
        extender: {
            class_name: TARGET,
            node_title: String(node?.title || "BSAI-ComfyUI-H3 Film Factory"),
            settings,
            resolution: {
                mode: String(getWidget(node, "resolution_mode")?.value || "manual"),
                megapixels: Number(getWidget(node, "megapixels")?.value ?? 0.40),
                manual_width: Number(runtime.manualWidth || settings.width || 0),
                manual_height: Number(runtime.manualHeight || settings.height || 0),
                resolved_width: Number(runtime.resolvedWidth || runtime.expectedResolution?.width || 0),
                resolved_height: Number(runtime.resolvedHeight || runtime.expectedResolution?.height || 0),
                guide_ref: String(runtime.resolutionGuide || ""),
                fallback: Boolean(runtime.resolutionFallback),
            },
            clips_json: serializeState(runtime.state),
            clips: runtime.state.clips.map((clip) => ({ ...clip })),
            refs_json: serializeRefsState(runtime.refsState),
            references: runtime.refsState.refs.map((ref) => ref ? { ...ref } : null),
            connections: collectConnectionSummary(node),
        },
        final_decode: finalNode ? {
            class_name: FINAL_TARGET,
            settings: collectWidgetValues(finalNode, FINAL_PROJECT_WIDGETS),
        } : null,
    };
}

function setWidgetValue(node, name, value) {
    const widget = getWidget(node, name);
    if (!widget || value === undefined) return false;
    widget.value = value;
    return true;
}

function applyProjectPayload(node, runtime, projectPayload) {
    const extender = projectPayload?.extender || {};
    const settings = extender?.settings || {};
    if (typeof extender?.node_title === "string" && extender.node_title.trim()) {
        node.title = extender.node_title;
    }
    for (const name of PROJECT_WIDGETS) {
        if (name === "clips_json" || name === "refs_json") continue;
        if (Object.prototype.hasOwnProperty.call(settings, name)) {
            setWidgetValue(node, name, settings[name]);
        }
    }

    // v14.24 and older .ext projects did not know about automatic resolution.
    // Preserve their exact behavior instead of silently deriving a new size.
    if (!Object.prototype.hasOwnProperty.call(settings, "resolution_mode")) {
        setWidgetValue(node, "resolution_mode", "manual");
    }

    const savedResolution = extender?.resolution;
    const savedManualW = Number(savedResolution?.manual_width || settings?.width || 0);
    const savedManualH = Number(savedResolution?.manual_height || settings?.height || 0);
    rememberManualResolution(node, runtime, savedManualW, savedManualH);
    const savedW = Number(savedResolution?.resolved_width || 0);
    const savedH = Number(savedResolution?.resolved_height || 0);
    if (savedW > 0 && savedH > 0) {
        runtime.expectedResolution = { width: savedW, height: savedH };
        // Loading a portable project is the one place where the archived
        // geometry is authoritative. Put that exact size in Manual mode so the
        // imported latent cache can continue unchanged. The user can switch
        // back to Auto or edit width/height afterwards; doing so starts a new
        // cache at the newly requested resolution.
        setWidgetValue(node, "width", savedW);
        setWidgetValue(node, "height", savedH);
        setWidgetValue(node, "resolution_mode", "manual");
        rememberManualResolution(node, runtime, savedW, savedH);
        runtime.projectResolutionLoaded = true;
    }

    const rawRefs =
        extender?.refs_json
        || settings?.refs_json
        || JSON.stringify({ version: 2, refs: extender?.references || [] });
    runtime.refsState = parseRefsState(rawRefs);
    updateRefsHidden(node, runtime);

    const rawClips = String(
        extender?.clips_json
        || settings?.clips_json
        || JSON.stringify({ version: 1, clips: extender?.clips || [] })
    );
    runtime.state = parseState(rawClips);
    // Loading a project mutates the disk cache outside ComfyUI's executor. A
    // one-shot token forces the Extender input hash to change even if every
    // visible setting happens to match the workflow that was previously run.
    runtime.state.load_token = `${Date.now().toString(36)}_${randomSeed().toString(36)}`;
    updateHidden(node, runtime);

    const finalSettings = projectPayload?.final_decode?.settings;
    const finalNode = connectedFinalDecode(node);
    if (finalNode && finalSettings && typeof finalSettings === "object") {
        for (const name of FINAL_PROJECT_WIDGETS) {
            if (Object.prototype.hasOwnProperty.call(finalSettings, name)) {
                setWidgetValue(finalNode, name, finalSettings[name]);
            }
        }
        finalNode.graph?.setDirtyCanvas(true, true);
    }

    node.graph?.setDirtyCanvas(true, true);
}

function projectBusy(runtime) {
    return ["preparing", "sampling", "complete"].includes(String(runtime?.activePhase || ""));
}

function setProjectButtonsBusy(runtime, busy) {
    if (!runtime) return;
    runtime.projectOperationBusy = Boolean(busy);
    if (runtime.saveProjectButton) runtime.saveProjectButton.disabled = Boolean(busy);
    if (runtime.loadProjectButton) runtime.loadProjectButton.disabled = Boolean(busy);
}

async function saveProject(node, runtime) {
    if (!node || !runtime) return;
    if (projectBusy(runtime)) {
        alert("Wait for the current clip generation to finish before saving the project.");
        return;
    }
    if (runtime.resolutionInvalidated) {
        alert(
            "The resolution has changed and the previous cache is no longer compatible. " +
            "Queue the Extender once to start the new-resolution cache before saving the project."
        );
        return;
    }

    const suggested = runtime.projectName || "MiniMax_H3_Project";
    const requested = prompt("Project name (.ext)", suggested);
    if (requested == null) return;
    const projectName = String(requested || suggested).trim() || suggested;

    setProjectButtonsBusy(runtime, true);
    runtime.statusText = "Saving project…";
    render(node, runtime);
    try {
        const response = await fetch(api.apiURL("/h3_extender/project/prepare_save"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                owner_id: String(node.id),
                project_name: projectName,
                project: collectProjectPayload(node, runtime),
            }),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || !payload?.ok || !payload?.token) {
            throw new Error(payload?.error || `Save Project failed (${response.status}).`);
        }

        runtime.projectName = String(payload.filename || projectName).replace(/\.ext$/i, "");
        node.properties = node.properties || {};
        node.properties.h3_project_name = runtime.projectName;
        runtime.statusText = `Project ready: ${payload.filename || projectName} | refs ${Number(payload?.references?.count ?? refCount(runtime))} embedded`;
        render(node, runtime);

        // Do not fetch the archive into a JS Blob: .ext files may be many GB.
        // A normal browser download streams it directly from the backend.
        const a = document.createElement("a");
        a.href = api.apiURL(
            "/h3_extender/project/download?token=" + encodeURIComponent(String(payload.token))
        );
        a.download = String(payload.filename || `${runtime.projectName}.ext`);
        a.style.display = "none";
        document.body.appendChild(a);
        a.click();
        setTimeout(() => a.remove(), 0);
    } catch (error) {
        runtime.statusText = "Save Project failed";
        render(node, runtime);
        alert(String(error?.message || error));
    } finally {
        setProjectButtonsBusy(runtime, false);
        render(node, runtime);
    }
}

async function loadProjectFile(node, runtime, file) {
    if (!node || !runtime || !file) return;
    if (projectBusy(runtime)) {
        alert("Wait for the current clip generation to finish before loading a project.");
        return;
    }
    if (!confirm(
        "Load this .ext project?\n\nThe current Extender cache, image references and project settings will be replaced."
    )) return;

    setProjectButtonsBusy(runtime, true);
    runtime.statusText = `Loading ${file.name}…`;
    render(node, runtime);
    try {
        const form = new FormData();
        form.append("owner_id", String(node.id));
        form.append("project_file", file, file.name);
        const response = await fetch(api.apiURL("/h3_extender/project/load"), {
            method: "POST",
            body: form,
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || !payload?.ok) {
            throw new Error(payload?.error || `Load Project failed (${response.status}).`);
        }

        applyProjectPayload(node, runtime, payload.project || {});
        runtime.cachedCount = Number(payload?.cache?.cached_count || 0);
        for (let i = 0; i < runtime.cachedCount && i < runtime.state.clips.length; i++) {
            const c = runtime.state.clips[i];
            if (c) {
                c._previewLoaded = true;
                delete c._previewVideoUrl;
                delete c._latentPreviewUrl;
                delete c._latentStep;
                delete c._latentTotal;
            }
        }
        runtime.validatedCount = Number(payload?.cache?.validated_count || 0);
        const loadedW = Number(payload?.cache?.resolved_width || runtime.expectedResolution?.width || 0);
        const loadedH = Number(payload?.cache?.resolved_height || runtime.expectedResolution?.height || 0);
        if (loadedW > 0 && loadedH > 0) {
            runtime.expectedResolution = { width: loadedW, height: loadedH };
            setWidgetValue(node, "width", loadedW);
            setWidgetValue(node, "height", loadedH);
            setWidgetValue(node, "resolution_mode", "manual");
            rememberManualResolution(node, runtime, loadedW, loadedH);
            runtime.resolutionMirrorActive = false;
            runtime.projectResolutionLoaded = true;
            runtime.resolutionInvalidated = false;
        }
        runtime.cacheStateRestored = true;
        runtime.projectName = String(payload.project_name || file.name).replace(/\.ext$/i, "");
        node.properties = node.properties || {};
        node.properties.h3_project_name = runtime.projectName;
        const resolutionText = loadedW > 0 && loadedH > 0 ? ` | ${loadedW}x${loadedH}` : "";
        runtime.statusText =
            `Loaded ${runtime.projectName}${resolutionText} | refs ${refCount(runtime)} | cached ${runtime.cachedCount}/${runtime.state.clips.length} | ` +
            `validated ${runtime.validatedCount}`;
        render(node, runtime);
        syncDomHeight(node, runtime, false);

        // Final Decode / Preview can rebuild the full preview from decoded blobs
        // already inside the imported cache, with no sampler or VAE execution.
        window.dispatchEvent(new CustomEvent("h3-extender-project-loaded", {
            detail: { owner_id: String(node.id) },
        }));
    } catch (error) {
        runtime.statusText = "Load Project failed";
        render(node, runtime);
        alert(String(error?.message || error));
    } finally {
        setProjectButtonsBusy(runtime, false);
        render(node, runtime);
    }
}

function makeFieldLabel(text) {
    const label = document.createElement("div");
    label.textContent = text;
    label.style.fontSize = "11px";
    label.style.opacity = "0.72";
    label.style.margin = "5px 0 3px";
    return label;
}

function makeNumberInput(value, min, max, step) {
    const input = document.createElement("input");
    input.type = "number";
    input.value = String(value);
    input.min = String(min);
    input.max = String(max);
    input.step = String(step);
    input.style.width = "100%";
    input.style.boxSizing = "border-box";
    input.style.background = "rgba(0,0,0,.25)";
    input.style.border = "1px solid rgba(255,255,255,.15)";
    input.style.color = "inherit";
    input.style.borderRadius = "5px";
    input.style.padding = "5px 7px";
    return input;
}

function renderReferences(node, runtime) {
    const row = runtime?.refsRow;
    if (!row) return;
    row.replaceChildren();

    const refs = runtime.refsState?.refs || [];

    for (let index = 0; index < MAX_IMAGE_REFS; index++) {
        const ref = refs[index] || null;
        const slot = document.createElement("div");
        // Fill the whole available node width with nine equal reference slots.
        // REF_SLOT_WIDTH is a hard minimum for each slot, not for the node.
        // The node itself may shrink well below the combined strip width; once
        // that happens this row owns the horizontal overflow and exposes its scrollbar.
        slot.style.flex = "1 1 0px";
        slot.style.minWidth = `${REF_SLOT_WIDTH}px`;
        slot.style.boxSizing = "border-box";
        slot.style.position = "relative";

        const load = document.createElement("button");
        load.textContent = ref ? `Replace Ref ${index + 1}` : `Load Ref ${index + 1}`;
        load.title = ref
            ? `Replace Ref ${index + 1}: ${ref.original_name || "reference"}`
            : `Load image reference ${index + 1}`;
        load.style.width = "100%";
        load.style.height = "23px";
        load.style.padding = "2px 4px";
        load.style.fontSize = "10px";
        load.disabled = Boolean(
            runtime.refBusy || runtime.projectOperationBusy || projectBusy(runtime)
        );
        load.addEventListener("click", (event) => {
            event.preventDefault();
            if (load.disabled) return;
            runtime.pendingRefSlot = index;
            runtime.refFileInput?.click();
        });
        slot.appendChild(load);

        const thumb = document.createElement("div");
        thumb.style.marginTop = "2px";
        thumb.style.width = "100%";
        thumb.style.height = `${REF_THUMB_HEIGHT}px`;
        thumb.style.boxSizing = "border-box";
        thumb.style.border = "1px solid rgba(255,255,255,.15)";
        thumb.style.borderRadius = "6px";
        thumb.style.background = "rgba(0,0,0,.24)";
        thumb.style.display = "flex";
        thumb.style.alignItems = "center";
        thumb.style.justifyContent = "center";
        thumb.style.position = "relative";
        thumb.style.overflow = "hidden";

        if (ref) {
            const img = document.createElement("img");
            img.src = refImageUrl(ref);
            img.alt = ref.original_name || `Ref ${index + 1}`;
            img.title = `${ref.original_name || `Ref ${index + 1}`} — double-click to edit`;
            img.style.width = "100%";
            img.style.height = "100%";
            img.style.objectFit = "contain";
            img.style.cursor = "pointer";
            img.draggable = false;
            img.addEventListener("dblclick", (event) => {
                event.preventDefault();
                event.stopPropagation();
                openReferenceEditor(node, runtime, index, ref);
            });
            thumb.appendChild(img);

            const remove = document.createElement("button");
            remove.textContent = "×";
            remove.title = `Remove Ref ${index + 1}`;
            remove.style.position = "absolute";
            remove.style.top = "3px";
            remove.style.right = "3px";
            remove.style.width = "20px";
            remove.style.height = "20px";
            remove.style.minWidth = "20px";
            remove.style.padding = "0";
            remove.style.lineHeight = "16px";
            remove.style.borderRadius = "10px";
            remove.style.background = "rgba(0,0,0,.68)";
            remove.disabled = Boolean(runtime.refBusy || runtime.projectOperationBusy || projectBusy(runtime));
            remove.addEventListener("click", (event) => {
                event.preventDefault();
                event.stopPropagation();
                removeReference(node, runtime, index);
            });
            thumb.appendChild(remove);
        } else {
            const empty = document.createElement("span");
            empty.textContent = "+";
            empty.style.fontSize = "24px";
            empty.style.opacity = ".55";
            thumb.appendChild(empty);
        }
        slot.appendChild(thumb);

        const meta = document.createElement("div");
        meta.style.marginTop = "1px";
        meta.style.fontSize = "9px";
        meta.style.lineHeight = "9px";
        meta.style.opacity = ".6";
        meta.style.textAlign = "center";
        meta.style.whiteSpace = "nowrap";
        meta.style.overflow = "hidden";
        meta.style.textOverflow = "ellipsis";
        meta.textContent = ref && ref.width > 0 && ref.height > 0
            ? `${Math.trunc(ref.width)}×${Math.trunc(ref.height)}`
            : "empty";
        meta.title = ref?.original_name || "";
        slot.appendChild(meta);

        row.appendChild(slot);
    }
}

async function h3FetchAssets() {
    try {
        const resp = await fetch("/bsai/list_all_assets");
        const data = await resp.json();
        app.graph._nodes.forEach(function(n) {
            if (n.type === "MiniMaxH3Extender" && n.__h3Extender) {
                n.__h3Extender._h3_assetCache = data;
            }
        });
    } catch (e) {
        console.error("[H3] Failed to fetch assets:", e);
    }
}

function parseAssetRefs(prompt) {
    const refs = [];
    const re = /@(图|视频|音频)(\d+)/g;
    let match;
    while ((match = re.exec(prompt)) !== null) {
        const type = match[1] === "图" ? "images" : match[1] === "视频" ? "videos" : "audios";
        refs.push({ type: type, index: parseInt(match[2]), tag: match[0] });
    }
    return refs;
}

function renderAssetPanel(leftPanel, clip, node, runtime, textarea) {
    leftPanel.innerHTML = "";

    // Title row
    const hdr = document.createElement("div");
    hdr.style.cssText = "display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;font-size:11px;color:#888;";
    const title = document.createElement("span");
    title.textContent = "已引用资产";
    hdr.appendChild(title);

    const refreshBtn = document.createElement("button");
    refreshBtn.textContent = "↻";
    refreshBtn.style.cssText = "background:#333;color:#aaa;border:1px solid #444;border-radius:2px;cursor:pointer;font-size:12px;padding:0 4px;";
    refreshBtn.title = "刷新资产库";
    refreshBtn.addEventListener("click", () => { h3FetchAssets(); renderAssetPanel(leftPanel, clip, node, runtime, textarea); });
    hdr.appendChild(refreshBtn);
    leftPanel.appendChild(hdr);

    // Parse @图N/@视频N/@音频N from prompt
    const refs = parseAssetRefs(clip.prompt);

    if (refs.length === 0) {
        const empty = document.createElement("div");
        empty.style.cssText = "color:#555;font-size:11px;text-align:center;padding:8px;";
        empty.textContent = "暂无引用";
        leftPanel.appendChild(empty);
    } else {
        const assetList = runtime._h3_assetCache;
        refs.forEach(function(ref) {
            const assetItem = document.createElement("div");
            assetItem.style.cssText = "display:flex;align-items:center;gap:4px;margin-bottom:3px;font-size:11px;";

            const thumb = document.createElement("div");
            thumb.style.cssText = "width:40px;height:40px;border:1px solid #333;border-radius:3px;overflow:hidden;flex-shrink:0;background:#1a1a1a;";
            if (ref.type !== "audios") {
                const img = document.createElement("img");
                img.style.cssText = "width:100%;height:100%;object-fit:cover;";
                img.loading = "lazy";
                // Find the asset filename from the fetched asset list
                if (assetList) {
                    const items = assetList[ref.type] || [];
                    const item = items.find(i => i.index === ref.index);
                    if (item) {
                        if (ref.type === "videos") {
                            img.src = "/bsai/video_frame?filename=" + encodeURIComponent(item.name);
                        } else {
                            img.src = "/bsai/asset_file?type=" + ref.type + "&filename=" + encodeURIComponent(item.name);
                        }
                    }
                }
                img.onerror = function() {
                    img.style.display = "none";
                    thumb.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;width:100%;height:100%;color:#555;font-size:9px;">IMG</div>';
                };
                thumb.appendChild(img);
            } else {
                thumb.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;width:100%;height:100%;color:#666;">♪</div>';
            }
            assetItem.appendChild(thumb);

            const label = document.createElement("span");
            label.textContent = ref.tag;
            label.style.cssText = "color:#aaa;flex:1;";
            assetItem.appendChild(label);

            const removeBtn = document.createElement("button");
            removeBtn.textContent = "✕";
            removeBtn.style.cssText = "background:none;border:none;color:#a44;cursor:pointer;font-size:12px;padding:0 2px;";
            removeBtn.addEventListener("click", function(e) {
                e.stopPropagation();
                e.preventDefault();
                // Remove the @图N tag from prompt
                let p = clip.prompt;
                p = p.replace(ref.tag, "").replace(/\s+/g, " ").trim();
                clip.prompt = p;
                textarea.value = p;
                updateHidden(node, runtime);
                renderAssetPanel(leftPanel, clip, node, runtime, textarea);
            });
            assetItem.appendChild(removeBtn);

            leftPanel.appendChild(assetItem);
        });
    }

    // If asset cache not loaded yet, fetch and re-render
    if (!runtime._h3_assetCache) {
        h3FetchAssets().then(() => {
            renderAssetPanel(leftPanel, clip, node, runtime, textarea);
        });
    }
}

function showAssetPicker(parentEl, clip, node, runtime, textarea) {
    // Remove existing popup
    const existing = parentEl.querySelector(".bsai-asset-picker");
    if (existing) { existing.remove(); return; }

    const popup = document.createElement("div");
    popup.className = "bsai-asset-picker";
    popup.style.cssText = "position:absolute;z-index:1000;background:#1a1a1a;border:1px solid #444;border-radius:4px;padding:8px;max-height:300px;overflow-y:auto;width:220px;box-shadow:0 4px 12px rgba(0,0,0,0.5);";

    const assetList = runtime._h3_assetCache || { images: [], videos: [], audios: [] };
    const groups = [
        { label: "图片 / Images", items: assetList.images || [], type: "images", prefix: "图" },
        { label: "视频 / Videos", items: assetList.videos || [], type: "videos", prefix: "视频" },
        { label: "音频 / Audio", items: assetList.audios || [], type: "audios", prefix: "音频" },
    ];

    groups.forEach(function(g) {
        if (!g.items.length) return;
        const hdr = document.createElement("div");
        hdr.style.cssText = "font-size:11px;color:#888;margin-bottom:3px;margin-top:6px;";
        hdr.textContent = g.label;
        popup.appendChild(hdr);

        g.items.forEach(function(item) {
            const row = document.createElement("div");
            row.style.cssText = "display:flex;align-items:center;gap:4px;margin-bottom:2px;cursor:pointer;padding:2px;border-radius:2px;";
            row.addEventListener("mouseenter", function() { row.style.background = "#2a3a5a"; });
            row.addEventListener("mouseleave", function() { row.style.background = ""; });

            const tag = "@" + g.prefix + item.index;
            const alreadyRef = clip.prompt.indexOf(tag) >= 0;
            if (alreadyRef) row.style.opacity = "0.5";

            const thumb = document.createElement("div");
            thumb.style.cssText = "width:28px;height:28px;border:1px solid #333;border-radius:2px;overflow:hidden;flex-shrink:0;";
            if (g.type !== "audios") {
                const img = document.createElement("img");
                img.style.cssText = "width:100%;height:100%;object-fit:cover;";
                img.src = "/bsai/asset_file?type=" + g.type + "&filename=" + encodeURIComponent(item.name);
                thumb.appendChild(img);
            } else {
                thumb.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;width:100%;height:100%;color:#666;font-size:14px;">♪</div>';
            }
            row.appendChild(thumb);

            const lbl = document.createElement("span");
            lbl.textContent = tag;
            lbl.style.cssText = "font-size:11px;color:#ccc;";
            row.appendChild(lbl);

            if (alreadyRef) {
                const check = document.createElement("span");
                check.textContent = " ✓";
                check.style.cssText = "color:#4a4;font-size:11px;";
                row.appendChild(check);
            }

            row.addEventListener("mousedown", function(e) {
                e.preventDefault();
                e.stopPropagation();
                // Insert at cursor position
                const pos = textarea.selectionStart || textarea._savedCursorPos || 0;
                let val = textarea.value;
                if (val.indexOf(tag) >= 0) {
                    // Remove tag
                    val = val.replace(tag, "").replace(/\s+/g, " ").trim();
                } else {
                    const before = val.substring(0, pos);
                    const after = val.substring(pos);
                    const needSpaceBefore = before.length > 0 && !before.endsWith(" ") && !before.endsWith("\n");
                    const needSpaceAfter = after.length > 0 && !after.startsWith(" ") && !after.startsWith("\n");
                    val = before + (needSpaceBefore ? " " : "") + tag + (needSpaceAfter ? " " : "") + after;
                }
                textarea.value = val;
                clip.prompt = val;
                textarea.focus();
                const newPos = pos + tag.length + 1;
                textarea.setSelectionRange(newPos, newPos);
                updateHidden(node, runtime);
                renderAssetPanel(parentEl, clip, node, runtime, textarea);
                popup.remove();
            });

            popup.appendChild(row);
        });
    });

    if (!popup.children.length) {
        popup.innerHTML = '<div style="color:#555;font-size:11px;text-align:center;padding:12px;">资产库为空</div>';
    }

    // Close button
    const closeBtn = document.createElement("div");
    closeBtn.textContent = "✕ 关闭";
    closeBtn.style.cssText = "text-align:center;padding:4px;margin-top:4px;color:#a44;cursor:pointer;font-size:11px;border-top:1px solid #333;";
    closeBtn.addEventListener("click", function() { popup.remove(); });
    popup.appendChild(closeBtn);

    parentEl.style.position = "relative";
    parentEl.appendChild(popup);
}

function syncGlobalPromptFromInput(node, runtime) {
    try {
        const psInput = node.inputs?.find(inp => inp.name === "prompt_source");
        if (!psInput || psInput.link == null) return;
        const link = app.graph.links[psInput.link];
        if (!link || link.origin_id == null) return;
        const srcNode = app.graph.getNodeById(link.origin_id);
        if (!srcNode) return;
        let text = null;
        const srcWidget = srcNode.widgets?.find(w => w.name === "text" || w.type === "text_multiline" || w.type === "customtext");
        if (srcWidget && srcWidget.value != null) {
            text = srcWidget.value;
        } else {
            text = srcNode.widgets_values?.[0];
        }
        if (text != null && String(text).trim()) {
            const fullText = String(text);
            // Split at first [分镜N] marker: before → global prompt
            const sbMarkerRe = /\[(?:分镜|Shot|shot|SHOT)\s*\d+\]/;
            const sbMatch = fullText.match(sbMarkerRe);
            const globalText = sbMatch ? fullText.slice(0, sbMatch.index).trim() : fullText.trim();
            if (globalText && runtime.state.global_prompt !== globalText) {
                runtime.state.global_prompt = globalText;
                updateHidden(node, runtime);
            }
            if (runtime.globalPromptTextarea && runtime.globalPromptTextarea.value !== globalText) {
                runtime.globalPromptTextarea.value = globalText;
            }
            if (typeof runtime.renderGlobalAssetPanel === "function") {
                runtime.renderGlobalAssetPanel();
            }
        }
    } catch (e) { /* ignore */ }
}

function render(node, runtime) {
    const { state, cards, counter, status } = runtime;
    renderReferences(node, runtime);

    // Sync global_prompt from connected external input
    syncGlobalPromptFromInput(node, runtime);

    cards.replaceChildren();

    counter.textContent = `${state.clips.length} clip${state.clips.length > 1 ? "s" : ""} • ${refCount(runtime)} ref${refCount(runtime) === 1 ? "" : "s"}`;
    status.textContent = runtime.statusText || "Ready";

    // Update CLIPS total duration label at the bottom
    if (runtime.clipsTotalLabel) {
        const totalDur = state.clips.reduce((sum, c) => sum + (Number(c.duration) || 0), 0);
        const n = state.clips.length;
        runtime.clipsTotalLabel.textContent = `CLIPS | 总时长 ${totalDur}s (${n} clip${n > 1 ? "s" : ""})`;
    }

    // Highlight merge output button when a merge is pending
    if (runtime.mergeOutputBtn) {
        const pendingMerge = String(runtime.statusText || "").includes("pending merge");
        if (pendingMerge) {
            runtime.mergeOutputBtn.style.background = "#4a8a4a";
            runtime.mergeOutputBtn.style.borderColor = "#5a9a5a";
            runtime.mergeOutputBtn.style.boxShadow = "0 0 8px rgba(80,200,80,.4)";
            runtime.mergeOutputBtn.textContent = "⚡ 合并输出 / Merge Output";
        } else {
            runtime.mergeOutputBtn.style.background = "#2a6a3a";
            runtime.mergeOutputBtn.style.borderColor = "#3a7a4a";
            runtime.mergeOutputBtn.style.boxShadow = "none";
            runtime.mergeOutputBtn.textContent = "合并输出 / Merge Output";
        }
    }

    state.clips.forEach((clip, index) => {
        const card = document.createElement("div");
        card.className = "h3-extender-card";
        card.dataset.clipIndex = String(index);
        card.style.flex = "0 0 auto";
        card.style.width = "100%";
        card.style.boxSizing = "border-box";
        card.style.padding = "0";
        card.style.borderRadius = "8px";
        card.style.background = "rgba(20,20,20,.72)";
        card.style.border = "1px solid rgba(255,255,255,.13)";
        card.style.display = "flex";
        card.style.flexDirection = "column";
        card.style.minHeight = `${CARD_MIN_HEIGHT}px`;

        const st = cardStatus(runtime, clip, index);
        if (st === "rendering") {
            card.style.border = "3px solid rgba(70,210,255,1)";
            card.style.boxShadow = "0 0 0 1px rgba(70,210,255,.25), 0 0 16px rgba(70,210,255,.38)";
            card.style.background = "rgba(24,40,46,.88)";
        } else if (st === "validated") {
            card.style.borderColor = "rgba(80,210,120,.8)";
        } else if (st === "candidate" || st === "current") {
            card.style.borderColor = "rgba(255,180,60,.9)";
        } else if (st === "cached") {
            card.style.borderColor = "rgba(90,155,230,.65)";
        }

        const head = document.createElement("div");
        head.style.display = "flex";
        head.style.alignItems = "center";
        head.style.gap = "7px";
        head.style.marginBottom = "0";
        head.style.padding = "9px 9px 5px";

        const toggle = document.createElement("div");
        toggle.style.cssText = "cursor:pointer;font-size:12px;margin-right:4px;user-select:none;";
        toggle.textContent = clip.collapsed ? "▶" : "▼";
        toggle.addEventListener("click", (e) => {
            if (e.target.tagName === "INPUT") return;
            clip.collapsed = !clip.collapsed;
            updateHidden(node, runtime);
            render(node, runtime);
        });

        const title = document.createElement("strong");
        title.textContent = `CLIP ${index + 1}`;
        title.style.flex = "0 0 auto";
        title.style.whiteSpace = "nowrap";

        const name = document.createElement("input");
        name.type = "text";
        name.value = clip.name || "";
        name.placeholder = "name";
        name.title = "Optional clip/card name";
        name.style.flex = "1 1 0";
        name.style.minWidth = "0";
        name.style.height = "22px";
        name.style.boxSizing = "border-box";
        name.style.background = "rgba(0,0,0,.22)";
        name.style.border = "1px solid rgba(255,255,255,.12)";
        name.style.color = "inherit";
        name.style.borderRadius = "4px";
        name.style.padding = "2px 5px";
        name.style.fontSize = "11px";
        name.addEventListener("input", () => {
            if (name.value === clip.name) return;
            clip.name = name.value;
            updateHidden(node, runtime);
            // Keep focus while typing; no DOM rebuild here.
        });

        const colorWrap = document.createElement("div");
        colorWrap.style.display = "flex";
        colorWrap.style.alignItems = "center";
        colorWrap.style.gap = "2px";
        colorWrap.style.flex = "0 0 auto";

        const colorButton = document.createElement("button");
        colorButton.type = "button";
        colorButton.textContent = "🎨";
        const colorBusy = ["preparing", "sampling", "complete"].includes(String(runtime.activePhase || ""));
        const colorCached = index < Number(runtime.cachedCount || 0);
        colorButton.title = colorBusy
            ? "Color editing is disabled while the Extender is rendering"
            : colorCached
                ? "Edit color for this decoded clip"
                : "Color editor becomes available after this clip has been decoded";
        colorButton.disabled = colorBusy || !colorCached;
        colorButton.style.width = "27px";
        colorButton.style.height = "22px";
        colorButton.style.padding = "0";
        colorButton.style.borderRadius = "4px";
        colorButton.style.cursor = colorButton.disabled ? "default" : "pointer";
        colorButton.style.opacity = colorButton.disabled ? ".35" : ".9";
        colorButton.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            if (!colorButton.disabled) openClipColorEditor(node, runtime, index);
        });

        const colorCheck = document.createElement("span");
        colorCheck.textContent = colorAdjustmentIsNeutral(clip.color_adjustment) ? "" : "✓";
        colorCheck.title = colorCheck.textContent ? "Color correction applied" : "";
        colorCheck.style.width = "10px";
        colorCheck.style.fontSize = "11px";
        colorCheck.style.fontWeight = "700";
        colorCheck.style.color = "rgba(115,225,145,.95)";
        colorCheck.style.textAlign = "center";

        colorWrap.append(colorButton, colorCheck);

        const badge = document.createElement("span");
        badge.style.fontSize = "10px";
        badge.style.opacity = ".8";
        badge.textContent =
            st === "rendering"
                ? (
                    runtime.activePhase === "preparing"
                        ? "◆ PREPARING"
                        : runtime.activePhase === "complete"
                            ? "✓ COMPLETE"
                            : "▶ RENDERING"
                ) :
            st === "validated" ? "VALIDATED" :
            st === "candidate" ? "● CANDIDATE" :
            st === "current" ? "● NEXT" :
            st === "cached" ? "CACHE" : "○";

        // ── Per-clip render toggle & replace button ─────────────────
        const clipActions = document.createElement("div");
        clipActions.style.cssText = "display:flex;align-items:center;gap:3px;flex:0 0 auto;margin-left:4px;";

        const renderToggle = document.createElement("button");
        renderToggle.type = "button";
        renderToggle.title = clip.render_enabled
            ? "生成开关：已启用（点击关闭此CLIP生成）"
            : "生成开关：已关闭（点击启用此CLIP生成）";
        renderToggle.textContent = clip.render_enabled ? "⚡" : "⊘";
        renderToggle.style.cssText = "width:24px;height:22px;padding:0;font-size:12px;border-radius:4px;border:1px solid rgba(255,255,255,.15);cursor:pointer;";
        renderToggle.style.background = clip.render_enabled
            ? "rgba(60,140,220,.28)"
            : "rgba(100,100,100,.22)";
        renderToggle.style.opacity = clip.render_enabled ? ".95" : ".55";
        renderToggle.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            clip.render_enabled = !clip.render_enabled;
            updateHidden(node, runtime);
            render(node, runtime);
        });

        const replaceBtn = document.createElement("button");
        replaceBtn.type = "button";
        replaceBtn.title = clip.replace_mode
            ? "重新生成：已选中（运行时仅重新生成此CLIP，不影响其他CLIP）"
            : "点击选中此CLIP单独重新生成（不影响其他CLIP）";
        replaceBtn.textContent = "↻";
        replaceBtn.style.cssText = "width:24px;height:22px;padding:0;font-size:13px;border-radius:4px;border:1px solid rgba(255,255,255,.15);cursor:pointer;";
        const isCached = index < Number(runtime.cachedCount || 0);
        replaceBtn.style.background = clip.replace_mode
            ? "rgba(220,130,60,.32)"
            : isCached ? "rgba(80,80,80,.3)" : "rgba(50,50,50,.2)";
        replaceBtn.style.opacity = clip.replace_mode ? ".95" : (isCached ? ".7" : ".35");
        replaceBtn.disabled = !isCached && !clip.replace_mode;
        replaceBtn.style.cursor = replaceBtn.disabled ? "default" : "pointer";
        replaceBtn.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            // Single-select mode: clear replace_mode on all other clips
            runtime.state.clips.forEach((c, ci) => {
                if (ci !== index) c.replace_mode = false;
            });
            clip.replace_mode = !clip.replace_mode;
            if (clip.replace_mode) {
                clip.render_enabled = true;
                // Clear merge_output when selecting a clip for regeneration
                runtime.state.merge_output = false;
            }
            updateHidden(node, runtime);
            render(node, runtime);
        });

        clipActions.append(renderToggle, replaceBtn);

        // ── Independent Render button: render ONLY this CLIP ──
        const clipRenderBtn = document.createElement("button");
        clipRenderBtn.type = "button";
        clipRenderBtn.textContent = "▶";
        clipRenderBtn.title = "独立渲染此CLIP / Render this CLIP only (others unaffected)";
        clipRenderBtn.style.cssText = "width:26px;height:22px;padding:0;font-size:12px;border-radius:4px;border:1px solid rgba(80,200,80,.6);background:rgba(30,100,40,.6);color:#8f8;cursor:pointer;flex:0 0 auto;margin-left:4px;font-weight:bold;";
        clipRenderBtn.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            clip.replace_mode = true;
            updateHidden(node, runtime);
            runtime.statusText = `渲染 CLIP ${index + 1} / Rendering CLIP ${index + 1}`;
            if (runtime.counter) runtime.counter.textContent = `${runtime.state.clips.length} clips • ${refCount(runtime)} refs`;
            if (runtime.status) runtime.status.textContent = runtime.statusText;
            try {
                if (window.app?.queuePrompt) window.app.queuePrompt();
                else if (app?.queuePrompt) app.queuePrompt();
            } catch(qe) {
                console.warn("[H3] Could not auto-queue for single CLIP render", qe);
            }
            setTimeout(() => {
                clip.replace_mode = false;
                updateHidden(node, runtime);
            }, 1000);
        });

        // ── Red X delete button (rightmost) ─────────────────────────
        const delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.textContent = "✕";
        delBtn.title = "删除此CLIP / Delete this CLIP";
        delBtn.style.cssText = "width:26px;height:22px;padding:0;font-size:13px;font-weight:bold;border-radius:4px;border:1px solid rgba(255,80,80,.7);background:rgba(180,30,30,.55);color:rgba(255,210,210,.95);cursor:pointer;flex:0 0 auto;margin-left:4px;";

        head.append(toggle, title, name, colorWrap, clipActions, badge, clipRenderBtn, delBtn);

        delBtn.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (runtime.state.clips.length <= 1) return;
            runtime.state.clips.splice(index, 1);
            updateHidden(node, runtime);
            render(node, runtime);
        });

        card.appendChild(head);

        const cardBody = document.createElement("div");
        cardBody.dataset.cardBody = "true";
        cardBody.style.display = "flex";
        cardBody.style.flexDirection = "row";
        cardBody.style.flex = "1 1 auto";
        cardBody.style.minHeight = "0";
        cardBody.style.position = "relative";
        if (clip.collapsed) cardBody.style.display = "none";

        // Left panel: referenced assets
        const leftPanel = document.createElement("div");
        leftPanel.style.cssText = "width:140px;min-width:140px;flex-shrink:0;border-right:1px solid rgba(255,255,255,.08);background:rgba(0,0,0,.15);padding:6px;display:flex;flex-direction:column;overflow-y:auto;";

        // Right panel: existing content (prompt, subtitle, ref frame extract, seed, etc.)
        const rightPanel = document.createElement("div");
        rightPanel.style.cssText = "flex:1 1 auto;min-width:0;padding:9px;display:flex;flex-direction:column;position:relative;";

        rightPanel.appendChild(makeFieldLabel("Prompt"));
        const promptRow = document.createElement("div");
        promptRow.style.cssText = "display:flex;flex-direction:row;gap:3px;width:100%;";
        const prompt = document.createElement("textarea");
        prompt.value = clip.prompt;
        prompt.spellcheck = false;
        prompt.style.width = "100%";
        prompt.style.height = "120px";
        prompt.style.minHeight = "80px";
        prompt.style.maxHeight = "400px";
        prompt.style.flex = "1 1 auto";
        prompt.style.resize = "vertical";
        prompt.style.boxSizing = "border-box";
        prompt.style.background = "rgba(0,0,0,.27)";
        prompt.style.border = "1px solid rgba(255,255,255,.15)";
        prompt.style.color = "inherit";
        prompt.style.borderRadius = "5px";
        prompt.style.padding = "6px";

        const promptExpandBtn = document.createElement("button");
        promptExpandBtn.textContent = "⤢";
        promptExpandBtn.title = "放大提示词窗口";
        promptExpandBtn.style.cssText = "flex-shrink:0;width:22px;height:22px;font-size:12px;background:rgba(40,40,40,.8);border:1px solid rgba(255,255,255,.15);border-radius:4px;color:#aaa;cursor:pointer;align-self:flex-start;margin-top:0;";
        let promptExpanded = false;
        promptExpandBtn.addEventListener("click", (e) => {
            e.preventDefault();
            promptExpanded = !promptExpanded;
            if (promptExpanded) {
                // Expand prompt within rightPanel only — keeps width unchanged,
                // only grows height to cover the full rightPanel area.
                rightPanel.appendChild(prompt);
                rightPanel.appendChild(promptExpandBtn);
                prompt.style.position = "absolute";
                prompt.style.inset = "0";
                prompt.style.zIndex = "50";
                prompt.style.width = "100%";
                prompt.style.height = "100%";
                prompt.style.maxHeight = "100%";
                prompt.style.resize = "none";
                prompt.style.borderRadius = "5px";
                promptExpandBtn.textContent = "✕";
                promptExpandBtn.style.zIndex = "51";
                promptExpandBtn.style.position = "absolute";
                promptExpandBtn.style.top = "4px";
                promptExpandBtn.style.right = "4px";
            } else {
                // Move prompt+button back to promptRow
                promptRow.appendChild(prompt);
                promptRow.appendChild(promptExpandBtn);
                prompt.style.position = "";
                prompt.style.inset = "";
                prompt.style.zIndex = "";
                prompt.style.width = "100%";
                prompt.style.height = "120px";
                prompt.style.maxHeight = "400px";
                prompt.style.resize = "vertical";
                prompt.style.borderRadius = "5px";
                promptExpandBtn.textContent = "⤢";
                promptExpandBtn.style.zIndex = "";
                promptExpandBtn.style.position = "";
                promptExpandBtn.style.top = "";
                promptExpandBtn.style.right = "";
            }
            syncDomHeight(runtime);
        });
        promptRow.style.position = "relative";
        promptRow.style.minHeight = "120px";
        promptRow.appendChild(prompt);
        promptRow.appendChild(promptExpandBtn);
        rightPanel.appendChild(promptRow);

        // Overlay for CLIP prompt: inline @图N thumbnails
        // 分镜提示词覆盖层：@图N内联缩略图
        const clipOverlay = document.createElement("div");
        clipOverlay.style.cssText = "position:absolute;top:0;left:0;width:100%;height:100%;font-size:inherit;border:1px solid rgba(255,255,255,.15);color:inherit;border-radius:5px;padding:6px;box-sizing:border-box;overflow-y:auto;pointer-events:none;white-space:pre-wrap;word-wrap:break-word;z-index:1;background:rgba(0,0,0,.27);";
        prompt.style.color = "transparent";
        prompt.style.background = "transparent";
        prompt.style.caretColor = "white";
        prompt.style.position = "absolute";
        prompt.style.top = "0";
        prompt.style.left = "0";
        prompt.style.width = "100%";
        prompt.style.height = "100%";
        prompt.style.minHeight = "120px";
        prompt.style.maxHeight = "400px";
        prompt.style.zIndex = "2";
        prompt.style.resize = "none";
        prompt.style.outline = "none";
        promptRow.appendChild(clipOverlay);
        prompt.addEventListener("scroll", () => {
            clipOverlay.scrollTop = prompt.scrollTop;
            clipOverlay.scrollLeft = prompt.scrollLeft;
        });

        function renderClipOverlay() {
            const text = clip.prompt || "";
            const refs = parseAssetRefs(text);
            if (refs.length === 0) { clipOverlay.textContent = text; return; }
            let html = "";
            let lastIdx = 0;
            const assetList = runtime._h3_assetCache;
            const esc = window._h3_escHtml || (s => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"));
            refs.forEach(function(ref) {
                const idx = text.indexOf(ref.tag, lastIdx);
                if (idx < 0) return;
                html += esc(text.slice(lastIdx, idx + ref.tag.length));
                if (ref.type !== "audios" && assetList) {
                    const items = assetList[ref.type] || [];
                    const assetItem = items.find(i => i.index === ref.index);
                    if (assetItem) {
                        const src = ref.type === "videos"
                            ? "/bsai/video_frame?filename=" + encodeURIComponent(assetItem.name)
                            : "/bsai/asset_file?type=" + ref.type + "&filename=" + encodeURIComponent(assetItem.name);
                        html += '<img src="' + src + '" style="width:18px;height:18px;object-fit:cover;border:1px solid #555;border-radius:2px;vertical-align:middle;margin:0 1px;" alt="">';
                    }
                }
                lastIdx = idx + ref.tag.length;
            });
            html += esc(text.slice(lastIdx));
            clipOverlay.innerHTML = html;
        }
        renderClipOverlay();
        if (!runtime._h3_assetCache) {
            h3FetchAssets().then(() => renderClipOverlay());
        }

        prompt.addEventListener("input", () => {
            if (prompt.value === clip.prompt) return;
            clip.prompt = prompt.value;
            updateHidden(node, runtime);
            renderClipOverlay();
        });
        prompt.addEventListener("focus", () => {
            window._h3_activeTextarea = prompt;
            window._h3_activeClip = clip;
            window._h3_activeNode = node;
            window._h3_activeRuntime = runtime;
            window._h3_activeLeftPanel = leftPanel;
            window._h3_refreshAssetPanel = () => {
                updateHidden(node, runtime);
                renderAssetPanel(leftPanel, clip, node, runtime, prompt);
                renderClipOverlay();
            };
        });
        prompt.addEventListener("click", () => {
            prompt._savedCursorPos = prompt.selectionStart;
        });
        prompt.addEventListener("blur", () => {
            prompt._savedCursorPos = prompt.selectionStart;
            setTimeout(() => {
                if (document.activeElement !== prompt && window._h3_activeTextarea === prompt) {
                    window._h3_activeTextarea = null;
                    window._h3_activeClip = null;
                    window._h3_activeNode = null;
                    window._h3_activeRuntime = null;
                    window._h3_activeLeftPanel = null;
                    window._h3_refreshAssetPanel = null;
                }
            }, 300);
            setTimeout(() => {
                if (document.activeElement !== prompt) {
                    render(node, runtime);
                }
            }, 200);
        });

        // Subtitle section
        rightPanel.appendChild(makeFieldLabel("字幕 / Subtitle"));

        // Subtitle mode selector: Manual vs Auto Extract
        // 字幕模式选择：手动 vs 自动提取
        const subModeRow = document.createElement("div");
        subModeRow.style.cssText = "display:flex;gap:4px;margin-bottom:4px;";
        const subManualBtn = document.createElement("button");
        subManualBtn.textContent = "手动字幕 / Manual";
        subManualBtn.style.cssText = "flex:1;font-size:10px;padding:2px 4px;border-radius:3px;cursor:pointer;";
        const subAutoBtn = document.createElement("button");
        subAutoBtn.textContent = "自动提取 / Auto Extract";
        subAutoBtn.style.cssText = "flex:1;font-size:10px;padding:2px 4px;border-radius:3px;cursor:pointer;";
        subModeRow.append(subManualBtn, subAutoBtn);
        rightPanel.appendChild(subModeRow);

        // Auto extract type checkboxes
        const subAutoTypes = document.createElement("div");
        subAutoTypes.style.cssText = "display:none;flex-wrap:wrap;gap:8px;margin-bottom:4px;font-size:10px;align-items:center;";
        const dlgLabel = document.createElement("label");
        dlgLabel.style.cssText = "display:flex;align-items:center;gap:2px;color:#c8c8c8;";
        const dlgCheck = document.createElement("input");
        dlgCheck.type = "checkbox";
        dlgCheck.checked = clip.subtitle_auto_dialogue;
        dlgCheck.style.cssText = "width:12px;height:12px;";
        dlgLabel.append(dlgCheck, document.createTextNode("对白 / Dialogue"));
        const narLabel = document.createElement("label");
        narLabel.style.cssText = "display:flex;align-items:center;gap:2px;color:#c8c8c8;";
        const narCheck = document.createElement("input");
        narCheck.type = "checkbox";
        narCheck.checked = clip.subtitle_auto_narration;
        narCheck.style.cssText = "width:12px;height:12px;";
        narLabel.append(narCheck, document.createTextNode("旁白 / Narration"));
        const lyrLabel = document.createElement("label");
        lyrLabel.style.cssText = "display:flex;align-items:center;gap:2px;color:#c8c8c8;";
        const lyrCheck = document.createElement("input");
        lyrCheck.type = "checkbox";
        lyrCheck.checked = clip.subtitle_auto_lyrics;
        lyrCheck.style.cssText = "width:12px;height:12px;";
        lyrLabel.append(lyrCheck, document.createTextNode("歌词 / Lyrics"));
        subAutoTypes.append(dlgLabel, narLabel, lyrLabel);
        rightPanel.appendChild(subAutoTypes);

        // Auto-extract preview (read-only)
        const subAutoPreview = document.createElement("div");
        subAutoPreview.style.cssText = "display:none;width:100%;min-height:24px;max-height:60px;overflow-y:auto;background:#111;color:#8c8;border:1px solid #333;border-radius:3px;padding:4px 6px;font-size:11px;margin-bottom:4px;white-space:pre-wrap;";
        rightPanel.appendChild(subAutoPreview);

        // Manual subtitle input
        const subtitleInput = document.createElement("textarea");
        subtitleInput.value = clip.subtitle || "";
        subtitleInput.placeholder = "输入字幕文本 / Enter subtitle text";
        subtitleInput.style.cssText = "width:100%;height:36px;min-height:24px;resize:vertical;background:#1a1a1a;color:#c8c8c8;border:1px solid #333;border-radius:3px;padding:4px 6px;font-size:12px;margin-bottom:4px;";
        subtitleInput.addEventListener("input", () => {
            clip.subtitle = subtitleInput.value;
            updateHidden(node, runtime);
        });
        rightPanel.appendChild(subtitleInput);

        // Auto-extract function: parses clip.prompt for dialogue/narration/lyrics
        function autoExtractSubtitles() {
            const text = clip.prompt || "";
            const parts = [];
            // 对白: 角色N说："..." or 角色N说："..."
            if (dlgCheck.checked) {
                const dlgRe = /(?:角色\d|[^\s，。]+)说[：:]\s*["""「『]([^"""」』]+)["""」』]/g;
                let m;
                while ((m = dlgRe.exec(text)) !== null) {
                    parts.push(m[1]);
                }
            }
            // 旁白: description text (lines without 说：, 音效：, 声线：)
            if (narCheck.checked) {
                const lines = text.split(/[\n。]/);
                lines.forEach(line => {
                    const trimmed = line.trim();
                    if (!trimmed) return;
                    if (/说[：:]/.test(trimmed)) return;
                    if (/音效[：:]/.test(trimmed)) return;
                    if (/声线[：:]/.test(trimmed)) return;
                    if (/语速[：:]/.test(trimmed)) return;
                    if (/情绪[：:]/.test(trimmed)) return;
                    if (/^\d+-\d+秒[：:]/.test(trimmed)) return;
                    if (/^\[/.test(trimmed)) return;
                    if (trimmed.length > 10) parts.push(trimmed);
                });
            }
            // 歌词: text within ♪ symbols
            if (lyrCheck.checked) {
                const lyrRe = /♪([^♪]+)♪/g;
                let m;
                while ((m = lyrRe.exec(text)) !== null) {
                    parts.push(m[1].trim());
                }
            }
            return parts.join("\n");
        }

        function refreshAutoSubtitles() {
            const extracted = autoExtractSubtitles();
            clip.subtitle = extracted;
            subtitleInput.value = extracted;
            subAutoPreview.textContent = extracted || "(无匹配内容 / No match)";
            updateHidden(node, runtime);
        }

        function updateSubModeUI() {
            const isAuto = clip.subtitle_mode === "auto";
            subManualBtn.style.background = isAuto ? "#2a2a2a" : "#3a5a8a";
            subManualBtn.style.color = isAuto ? "#888" : "#cde";
            subManualBtn.style.border = isAuto ? "1px solid #333" : "1px solid #5a7aaa";
            subAutoBtn.style.background = isAuto ? "#5a8a3a" : "#2a2a2a";
            subAutoBtn.style.color = isAuto ? "#cde" : "#888";
            subAutoBtn.style.border = isAuto ? "1px solid #7aaa5a" : "1px solid #333";
            subAutoTypes.style.display = isAuto ? "flex" : "none";
            subAutoPreview.style.display = isAuto ? "block" : "none";
            subtitleInput.style.display = isAuto ? "none" : "block";
            if (isAuto) refreshAutoSubtitles();
        }

        subManualBtn.addEventListener("click", () => {
            clip.subtitle_mode = "manual";
            updateSubModeUI();
            updateHidden(node, runtime);
        });
        subAutoBtn.addEventListener("click", () => {
            clip.subtitle_mode = "auto";
            updateSubModeUI();
            updateHidden(node, runtime);
        });
        [dlgCheck, narCheck, lyrCheck].forEach(cb => {
            cb.addEventListener("change", () => {
                clip.subtitle_auto_dialogue = dlgCheck.checked;
                clip.subtitle_auto_narration = narCheck.checked;
                clip.subtitle_auto_lyrics = lyrCheck.checked;
                if (clip.subtitle_mode === "auto") refreshAutoSubtitles();
                updateHidden(node, runtime);
            });
        });

        // Auto-refresh when prompt changes (if in auto mode)
        const origRenderClipOverlay = renderClipOverlay;
        renderClipOverlay = function() {
            origRenderClipOverlay.call(this);
            if (clip.subtitle_mode === "auto") refreshAutoSubtitles();
        };

        updateSubModeUI();

        // Subtitle controls row
        const subCtrlRow = document.createElement("div");
        subCtrlRow.style.cssText = "display:flex;flex-wrap:wrap;gap:4px;align-items:center;margin-bottom:6px;font-size:11px;";

        // Font selector
        const fontLabel = document.createElement("span");
        fontLabel.textContent = "字体";
        fontLabel.style.cssText = "color:#888;margin-right:2px;";
        subCtrlRow.appendChild(fontLabel);
        const fontSelect = document.createElement("select");
        fontSelect.style.cssText = "background:#1a1a1a;color:#c8c8c8;border:1px solid #333;border-radius:3px;padding:1px 3px;font-size:11px;max-width:100px;";
        fontSelect.innerHTML = '<option value="msyh.ttc">微软雅黑</option><option value="simhei.ttf">黑体</option><option value="simsun.ttc">宋体</option><option value="arial.ttf">Arial</option>';
        fontSelect.value = clip.subtitle_font || "msyh.ttc";
        fontSelect.addEventListener("change", () => {
            clip.subtitle_font = fontSelect.value;
            updateHidden(node, runtime);
        });
        subCtrlRow.appendChild(fontSelect);

        // Font size
        const sizeLabel = document.createElement("span");
        sizeLabel.textContent = "字号";
        sizeLabel.style.cssText = "color:#888;margin-left:4px;margin-right:2px;";
        subCtrlRow.appendChild(sizeLabel);
        const sizeInput = document.createElement("input");
        sizeInput.type = "number";
        sizeInput.min = "8";
        sizeInput.max = "200";
        sizeInput.value = clip.subtitle_font_size || 24;
        sizeInput.style.cssText = "width:40px;background:#1a1a1a;color:#c8c8c8;border:1px solid #333;border-radius:3px;padding:1px 3px;font-size:11px;";
        sizeInput.addEventListener("input", () => {
            clip.subtitle_font_size = parseInt(sizeInput.value) || 24;
            updateHidden(node, runtime);
        });
        subCtrlRow.appendChild(sizeInput);

        // Color
        const colorLabel = document.createElement("span");
        colorLabel.textContent = "颜色";
        colorLabel.style.cssText = "color:#888;margin-left:4px;margin-right:2px;";
        subCtrlRow.appendChild(colorLabel);
        const colorInput = document.createElement("input");
        colorInput.type = "color";
        colorInput.value = clip.subtitle_color || "#FFFFFF";
        colorInput.style.cssText = "width:24px;height:20px;background:none;border:1px solid #333;border-radius:2px;padding:0;";
        colorInput.addEventListener("input", () => {
            clip.subtitle_color = colorInput.value;
            updateHidden(node, runtime);
        });
        subCtrlRow.appendChild(colorInput);

        // Box checkbox
        const boxLabel = document.createElement("label");
        boxLabel.style.cssText = "color:#888;margin-left:4px;display:flex;align-items:center;gap:2px;";
        const boxCheck = document.createElement("input");
        boxCheck.type = "checkbox";
        boxCheck.checked = clip.subtitle_box || false;
        boxCheck.style.cssText = "width:12px;height:12px;";
        const boxText = document.createElement("span");
        boxText.textContent = "加框";
        boxLabel.appendChild(boxCheck);
        boxLabel.appendChild(boxText);
        subCtrlRow.appendChild(boxLabel);

        // Box color
        const boxColorInput = document.createElement("input");
        boxColorInput.type = "color";
        boxColorInput.value = clip.subtitle_box_color || "#000000";
        boxColorInput.style.cssText = "width:24px;height:20px;background:none;border:1px solid #333;border-radius:2px;padding:0;display:none;";
        boxColorInput.addEventListener("input", () => {
            clip.subtitle_box_color = boxColorInput.value;
            updateHidden(node, runtime);
        });
        subCtrlRow.appendChild(boxColorInput);

        // Box width
        const boxWLabel = document.createElement("span");
        boxWLabel.textContent = "框粗";
        boxWLabel.style.cssText = "color:#888;margin-left:2px;margin-right:2px;display:none;";
        const boxWInput = document.createElement("input");
        boxWInput.type = "number";
        boxWInput.min = "0";
        boxWInput.max = "20";
        boxWInput.value = clip.subtitle_box_width || 2;
        boxWInput.style.cssText = "width:30px;background:#1a1a1a;color:#c8c8c8;border:1px solid #333;border-radius:3px;padding:1px 3px;font-size:11px;display:none;";
        boxWInput.addEventListener("input", () => {
            clip.subtitle_box_width = parseInt(boxWInput.value) || 0;
            updateHidden(node, runtime);
        });
        subCtrlRow.appendChild(boxWLabel);
        subCtrlRow.appendChild(boxWInput);

        boxCheck.addEventListener("change", () => {
            clip.subtitle_box = boxCheck.checked;
            boxColorInput.style.display = boxCheck.checked ? "" : "none";
            boxWLabel.style.display = boxCheck.checked ? "" : "none";
            boxWInput.style.display = boxCheck.checked ? "" : "none";
            updateHidden(node, runtime);
        });
        // Initial display
        if (boxCheck.checked) {
            boxColorInput.style.display = "";
            boxWLabel.style.display = "";
            boxWInput.style.display = "";
        }

        rightPanel.appendChild(subCtrlRow);

        // Context reference toggle
        const ctxRow = document.createElement("div");
        ctxRow.style.cssText = "display:flex;align-items:center;gap:6px;margin-top:6px;margin-bottom:3px;font-size:11px;";
        const ctxCheck = document.createElement("input");
        ctxCheck.type = "checkbox";
        ctxCheck.checked = clip.context_enabled !== false;
        ctxCheck.id = `ctx_${clip.id}`;
        ctxCheck.style.cssText = "cursor:pointer;accent-color:#4a8;";
        const ctxLabel = document.createElement("label");
        ctxLabel.htmlFor = ctxCheck.id;
        ctxLabel.textContent = "上下文参考 / Context Reference";
        ctxLabel.style.cssText = "color:#aaa;cursor:pointer;user-select:none;";
        ctxLabel.addEventListener("click", (e) => { e.preventDefault(); ctxCheck.click(); });
        ctxCheck.addEventListener("change", () => {
            clip.context_enabled = ctxCheck.checked;
            clip.validated = false;
            rfeContent.style.opacity = ctxCheck.checked ? "1" : "0.4";
            rfeToggle.style.opacity = ctxCheck.checked ? "1" : "0.5";
            rfeContent.style.pointerEvents = ctxCheck.checked ? "" : "none";
            updateHidden(node, runtime);
            invalidateFrom(runtime.state, runtime.state.clips.indexOf(clip));
        });
        ctxRow.appendChild(ctxCheck);
        ctxRow.appendChild(ctxLabel);
        rightPanel.appendChild(ctxRow);

        // Ref Frame Extract section (collapsible)
        const rfeToggle = document.createElement("div");
        rfeToggle.style.cssText = "cursor:pointer;font-size:11px;color:#888;margin-top:6px;margin-bottom:3px;user-select:none;";
        rfeToggle.textContent = "▶ 参考帧提取 / Ref Frame Extract";
        if (!ctxCheck.checked) rfeToggle.style.opacity = "0.5";
        let rfeExpanded = false;
        const rfeContent = document.createElement("div");
        rfeContent.style.cssText = "display:none;padding:4px 6px;border:1px solid #333;border-radius:3px;background:#0e0e0e;margin-bottom:6px;";
        if (!ctxCheck.checked) {
            rfeContent.style.opacity = "0.4";
            rfeContent.style.pointerEvents = "none";
        }

        rfeToggle.addEventListener("click", () => {
            if (!ctxCheck.checked) return;
            rfeExpanded = !rfeExpanded;
            rfeContent.style.display = rfeExpanded ? "" : "none";
            rfeToggle.textContent = (rfeExpanded ? "▼ " : "▶ ") + "参考帧提取 / Ref Frame Extract";
        });

        function makeRfeRow(labelText) {
            const rfeRow = document.createElement("div");
            rfeRow.style.cssText = "display:flex;gap:6px;align-items:center;margin-bottom:3px;font-size:11px;";
            const lbl = document.createElement("span");
            lbl.textContent = labelText;
            lbl.style.cssText = "color:#888;min-width:70px;";
            rfeRow.appendChild(lbl);
            return rfeRow;
        }

        // frame_count
        const rfeRow1 = makeRfeRow("frame_count");
        const rfeFc = document.createElement("input");
        rfeFc.type = "number"; rfeFc.min = "1"; rfeFc.max = "500"; rfeFc.value = clip.rfe_frame_count;
        rfeFc.style.cssText = "width:50px;background:#1a1a1a;color:#c8c8c8;border:1px solid #333;border-radius:2px;padding:1px 3px;font-size:11px;";
        rfeFc.addEventListener("input", () => { clip.rfe_frame_count = parseInt(rfeFc.value) || 15; updateHidden(node, runtime); });
        rfeRow1.appendChild(rfeFc);
        rfeContent.appendChild(rfeRow1);

        // selection_mode
        const rfeRow2 = makeRfeRow("selection_mode");
        const rfeSm = document.createElement("select");
        ["last_n","first_n","middle_n","custom_range"].forEach(v => { const o=document.createElement("option"); o.value=v; o.textContent=v; rfeSm.appendChild(o); });
        rfeSm.value = clip.rfe_selection_mode;
        rfeSm.style.cssText = "background:#1a1a1a;color:#c8c8c8;border:1px solid #333;border-radius:2px;padding:1px 3px;font-size:11px;";
        rfeSm.addEventListener("change", () => { clip.rfe_selection_mode = rfeSm.value; updateHidden(node, runtime); });
        rfeRow2.appendChild(rfeSm);
        rfeContent.appendChild(rfeRow2);

        // start_frame, end_frame
        const rfeRow3 = makeRfeRow("start_frame");
        const rfeSf = document.createElement("input");
        rfeSf.type = "number"; rfeSf.min = "0"; rfeSf.value = clip.rfe_start_frame;
        rfeSf.style.cssText = "width:50px;background:#1a1a1a;color:#c8c8c8;border:1px solid #333;border-radius:2px;padding:1px 3px;font-size:11px;";
        rfeSf.addEventListener("input", () => { clip.rfe_start_frame = parseInt(rfeSf.value) || 0; updateHidden(node, runtime); });
        rfeRow3.appendChild(rfeSf);
        const rfeSf2 = makeRfeRow("end_frame");
        const rfeEf = document.createElement("input");
        rfeEf.type = "number"; rfeEf.min = "0"; rfeEf.value = clip.rfe_end_frame;
        rfeEf.style.cssText = "width:50px;background:#1a1a1a;color:#c8c8c8;border:1px solid #333;border-radius:2px;padding:1px 3px;font-size:11px;";
        rfeEf.addEventListener("input", () => { clip.rfe_end_frame = parseInt(rfeEf.value) || 0; updateHidden(node, runtime); });
        rfeSf2.appendChild(rfeEf);
        rfeContent.appendChild(rfeRow3);
        rfeContent.appendChild(rfeSf2);

        // max_output_frames, sampling
        const rfeRow4 = makeRfeRow("max_output");
        const rfeMo = document.createElement("input");
        rfeMo.type = "number"; rfeMo.min = "1"; rfeMo.max = "50"; rfeMo.value = clip.rfe_max_output_frames;
        rfeMo.style.cssText = "width:50px;background:#1a1a1a;color:#c8c8c8;border:1px solid #333;border-radius:2px;padding:1px 3px;font-size:11px;";
        rfeMo.addEventListener("input", () => { clip.rfe_max_output_frames = parseInt(rfeMo.value) || 9; updateHidden(node, runtime); });
        rfeRow4.appendChild(rfeMo);
        const rfeRow4b = makeRfeRow("sampling");
        const rfeSamp = document.createElement("select");
        ["even","sequential"].forEach(v => { const o=document.createElement("option"); o.value=v; o.textContent=v; rfeSamp.appendChild(o); });
        rfeSamp.value = clip.rfe_sampling_method;
        rfeSamp.style.cssText = "background:#1a1a1a;color:#c8c8c8;border:1px solid #333;border-radius:2px;padding:1px 3px;font-size:11px;";
        rfeSamp.addEventListener("change", () => { clip.rfe_sampling_method = rfeSamp.value; updateHidden(node, runtime); });
        rfeRow4b.appendChild(rfeSamp);
        rfeContent.appendChild(rfeRow4);
        rfeContent.appendChild(rfeRow4b);

        // save_frames, subdir, prefix
        const rfeRow5 = makeRfeRow("save_frames");
        const rfeSave = document.createElement("input");
        rfeSave.type = "checkbox"; rfeSave.checked = clip.rfe_save_frames;
        rfeSave.style.cssText = "width:12px;height:12px;";
        rfeSave.addEventListener("change", () => { clip.rfe_save_frames = rfeSave.checked; updateHidden(node, runtime); });
        rfeRow5.appendChild(rfeSave);
        const rfeRow5b = makeRfeRow("subdir");
        const rfeSubdir = document.createElement("input");
        rfeSubdir.type = "text"; rfeSubdir.value = clip.rfe_output_subdir;
        rfeSubdir.style.cssText = "width:100px;background:#1a1a1a;color:#c8c8c8;border:1px solid #333;border-radius:2px;padding:1px 3px;font-size:11px;";
        rfeSubdir.addEventListener("input", () => { clip.rfe_output_subdir = rfeSubdir.value; updateHidden(node, runtime); });
        rfeRow5b.appendChild(rfeSubdir);
        const rfeRow5c = makeRfeRow("prefix");
        const rfePf = document.createElement("input");
        rfePf.type = "text"; rfePf.value = clip.rfe_filename_prefix;
        rfePf.style.cssText = "width:80px;background:#1a1a1a;color:#c8c8c8;border:1px solid #333;border-radius:2px;padding:1px 3px;font-size:11px;";
        rfePf.addEventListener("input", () => { clip.rfe_filename_prefix = rfePf.value; updateHidden(node, runtime); });
        rfeRow5c.appendChild(rfePf);
        rfeContent.appendChild(rfeRow5);
        rfeContent.appendChild(rfeRow5b);
        rfeContent.appendChild(rfeRow5c);

        rightPanel.appendChild(rfeToggle);
        rightPanel.appendChild(rfeContent);

        const row = document.createElement("div");
        row.style.display = "grid";
        row.style.gridTemplateColumns = "1fr 92px";
        row.style.gap = "7px";
        row.style.alignItems = "end";

        const seedBox = document.createElement("div");
        seedBox.appendChild(makeFieldLabel("Seed"));
        const seedRow = document.createElement("div");
        seedRow.style.display = "flex";
        seedRow.style.gap = "5px";
        const seed = makeNumberInput(clip.seed, 0, Number.MAX_SAFE_INTEGER, 1);
        seed.style.minWidth = "0";
        seed.addEventListener("change", () => {
            const v = Math.max(0, Math.min(Number.MAX_SAFE_INTEGER, Math.trunc(Number(seed.value || 0))));
            if (v !== clip.seed) {
                clip.seed = v;
                updateHidden(node, runtime);
                render(node, runtime);
            }
        });
        const dice = document.createElement("button");
        dice.textContent = "🎲";
        dice.title = "Randomize seed";
        dice.style.width = "32px";
        dice.addEventListener("click", (e) => {
            e.preventDefault();
            clip.seed = randomSeed();
            updateHidden(node, runtime);
            render(node, runtime);
        });
        seedRow.append(seed, dice);
        seedBox.appendChild(seedRow);

        const seedMode = document.createElement("select");
        seedMode.title = "Seed behavior after a generated candidate";
        seedMode.style.width = "100%";
        seedMode.style.marginTop = "4px";
        seedMode.style.boxSizing = "border-box";
        seedMode.style.background = "rgba(0,0,0,.25)";
        seedMode.style.border = "1px solid rgba(255,255,255,.15)";
        seedMode.style.color = "inherit";
        seedMode.style.borderRadius = "5px";
        seedMode.style.padding = "4px 5px";
        for (const [value, label] of [
            ["randomize", "after: randomize"],
            ["fixed", "after: fixed"],
            ["increment", "after: increment"],
            ["decrement", "after: decrement"],
        ]) {
            const option = document.createElement("option");
            option.value = value;
            option.textContent = label;
            seedMode.appendChild(option);
        }
        seedMode.value = clip.seed_mode || "randomize";
        seedMode.addEventListener("change", () => {
            clip.seed_mode = seedMode.value;
            updateHidden(node, runtime);
        });
        seedBox.appendChild(seedMode);

        const durBox = document.createElement("div");
        durBox.appendChild(makeFieldLabel("Duration s"));
        const duration = makeNumberInput(clip.duration, 0.25, 150, 0.1);
        duration.addEventListener("change", () => {
            const v = Math.max(0.25, Math.min(150, Number(duration.value || 10)));
            if (Math.abs(v - clip.duration) > 1e-9) {
                clip.duration = v;
                updateHidden(node, runtime);
                render(node, runtime);
            }
        });
        durBox.appendChild(duration);
        row.append(seedBox, durBox);
        rightPanel.appendChild(row);

        const foot = document.createElement("div");
        foot.style.display = "flex";
        foot.style.alignItems = "center";
        foot.style.justifyContent = "space-between";
        foot.style.marginTop = "9px";

        const validateLabel = document.createElement("label");
        validateLabel.style.display = "flex";
        validateLabel.style.alignItems = "center";
        validateLabel.style.gap = "6px";
        validateLabel.style.cursor = "pointer";
        const validated = document.createElement("input");
        validated.type = "checkbox";
        validated.checked = clip.validated;
        validated.addEventListener("change", () => {
            if (validated.checked) {
                clip.validated = true;
            } else {
                invalidateFrom(state, index);
            }
            // A valid chain is necessarily a continuous validated prefix.
            let open = false;
            for (const c of state.clips) {
                if (open) c.validated = false;
                else if (!c.validated) open = true;
            }
            updateHidden(node, runtime);
            render(node, runtime);
        });
        validateLabel.append(validated, document.createTextNode("Validated"));

        const info = document.createElement("span");
        const rawFrames = Math.max(5, Math.round(clip.duration * 24));
        let aligned = rawFrames;
        while (aligned % 17 !== 5) aligned++;
        info.textContent = `${aligned}f / ${(aligned / 24).toFixed(3)}s`;
        info.style.fontSize = "10px";
        info.style.opacity = ".65";

        foot.append(validateLabel, info);
        rightPanel.appendChild(foot);

        renderAssetPanel(leftPanel, clip, node, runtime, prompt);

        const previewPanel = document.createElement("div");
        previewPanel.style.cssText = `width:${PREVIEW_PANEL_WIDTH}px;min-width:${PREVIEW_PANEL_WIDTH}px;flex-shrink:0;border-left:1px solid rgba(255,255,255,.08);background:rgba(0,0,0,.15);padding:6px;display:flex;flex-direction:column;align-items:center;justify-content:flex-start;overflow:hidden;`;
        if (clip.collapsed) previewPanel.style.display = "none";
        renderPreviewPanel(previewPanel, clip, index, node, runtime);

        cardBody.append(leftPanel, rightPanel, previewPanel);
        card.appendChild(cardBody);

        if (!clip.collapsed) {
            const resizeHandle = document.createElement("div");
            resizeHandle.dataset.resizeHandle = "true";
            resizeHandle.style.cssText = "height:10px;cursor:ns-resize;background:rgba(255,255,255,0.05);border-top:1px solid rgba(255,255,255,0.08);display:flex;align-items:center;justify-content:center;";
            resizeHandle.textContent = "═";
            resizeHandle.style.color = "rgba(255,255,255,0.2)";
            resizeHandle.style.fontSize = "8px";

            resizeHandle.addEventListener("mousedown", (e) => {
                e.preventDefault();
                const startY = e.clientY;
                const startHeight = card.offsetHeight;
                const onMouseMove = (ev) => {
                    const newHeight = Math.max(200, startHeight + ev.clientY - startY);
                    card.style.height = newHeight + "px";
                };
                const onMouseUp = () => {
                    document.removeEventListener("mousemove", onMouseMove);
                    document.removeEventListener("mouseup", onMouseUp);
                    clip.card_height = card.offsetHeight;
                    updateHidden(node, runtime);
                };
                document.addEventListener("mousemove", onMouseMove);
                document.addEventListener("mouseup", onMouseUp);
            });
            card.appendChild(resizeHandle);
        }

        if (clip.collapsed) {
            card.style.height = "auto";
            card.style.minHeight = "0";
            card.style.flex = "none";
        } else {
            card.style.flex = "0 0 auto";
            card.style.minHeight = `${CARD_MIN_HEIGHT}px`;
            if (clip.card_height > 0) {
                card.style.height = clip.card_height + "px";
            } else {
                card.style.height = "";
            }
        }
        cards.appendChild(card);
    });

    requestAnimationFrame(() => syncDomHeight(node, runtime, false));
}

function syncDomHeight(node, runtime, forceMin = false, retry = 0) {
    if (!node || !runtime?.domWidget || runtime.syncingDomHeight) return;

    const mode = domWidgetRenderMode(runtime.root);
    if (mode === "pending") {
        if (retry < 12) {
            requestAnimationFrame(() => syncDomHeight(node, runtime, forceMin, retry + 1));
        }
        return;
    }

    // Nodes 2.0 owns the DOM-widget row height. Never derive a new getHeight
    // value from node.size here: node.size -> DOM getHeight -> node.size is the
    // feedback loop that created the infinite-height nodes.
    if (mode === "nodes2") {
        const dynMinH = calculateMinHeight(runtime);
        const currentH = Number(node.size?.[1] || 0);
        const y = Number(runtime.domWidget.last_y);
        const fallbackH = Number.isFinite(y) && y > 0
            ? y + dynMinH + BOTTOM_PAD
            : dynMinH + 180;

        // One-time recovery for workflows that were already saved with a
        // runaway height by an older build. This is not DOM-driven resizing;
        // it only removes a clearly corrupted value.
        if (
            runtime.lastRenderMode !== "nodes2" &&
            obviouslyPoisonedHeight(currentH, fallbackH)
        ) {
            runtime.syncingDomHeight = true;
            try {
                const rememberedLegacyH = Number(runtime.legacyNodeHeight);
                const targetH = (
                    Number.isFinite(rememberedLegacyH) &&
                    !obviouslyPoisonedHeight(rememberedLegacyH, fallbackH)
                )
                    ? Math.max(fallbackH, rememberedLegacyH)
                    : fallbackH;
                const targetW = Math.max(
                    NODE_MIN_WIDTH,
                    Number(node.size?.[0] || NODE_MIN_WIDTH)
                );
                node.setSize([targetW, targetH]);
            } finally {
                runtime.syncingDomHeight = false;
            }
        }

        runtime.lastRenderMode = "nodes2";

        // Nodes 2.0 mounts this element inside WidgetDOM.vue's flex wrapper
        // (`flex flex-col *:flex-1`) and NodeWidgets.vue owns the grid row.
        // Do NOT use percentage heights here. A `height: 100%` has no stable
        // intrinsic size while CSS Grid is resolving an `auto` row; after a
        // manual resize that row can collapse to 0 and WidgetDOM will not
        // remount the element until a page refresh. Keep a real intrinsic
        // minimum instead and let Vue stretch the row/child naturally.
        runtime.root.style.height = "auto";
        runtime.root.style.minHeight = `${dynMinH}px`;
        runtime.root.style.setProperty("--comfy-widget-min-height", `${dynMinH}px`);
        runtime.root.style.maxHeight = "none";
        runtime.root.style.flex = "1 1 auto";
        runtime.root.style.paddingTop = `${5 + NODES2_TOP_GAP}px`;
        // Avoid a second vertical clipping boundary at fractional canvas zooms.
        // Horizontal clipping/scrolling is still owned by `cards`.
        runtime.root.style.overflow = "visible";

        runtime.cards.style.height = "auto";
        runtime.cards.style.flex = "1 1 auto";
        runtime.cards.style.minHeight = `${Math.max(COLLAPSED_MIN_HEIGHT, dynMinH - NON_CARD_FIXED)}px`;
        runtime.cards.style.maxHeight = "none";
        return;
    }

    const y = Number(runtime.domWidget.last_y);
    if (!Number.isFinite(y) || y <= 0) {
        if (retry < 12) {
            requestAnimationFrame(() => syncDomHeight(node, runtime, forceMin, retry + 1));
        }
        return;
    }

    // Remove Nodes 2.0-only intrinsic sizing when returning to Legacy.
    runtime.root.style.paddingTop = "5px";
    runtime.root.style.minHeight = "0";
    const legacyMinH = calculateMinHeight(runtime);
    runtime.root.style.setProperty("--comfy-widget-min-height", `${legacyMinH}px`);
    runtime.root.style.maxHeight = "none";
    runtime.root.style.flex = "0 0 auto";
    runtime.root.style.overflow = "visible";

    runtime.syncingDomHeight = true;
    try {
        let w = Math.max(NODE_MIN_WIDTH, Number(node.size?.[0] || NODE_MIN_WIDTH));
        let h = Number(node.size?.[1] || 0);
        const minNodeH = y + legacyMinH + BOTTOM_PAD;
        const returningFromNodes2 = runtime.lastRenderMode === "nodes2";

        if (returningFromNodes2) {
            // Restore the last real Legacy height. If this node was first opened
            // in Nodes 2.0 (so there is no stored Legacy size), start from the
            // calculated Legacy minimum instead of inheriting a Vue runaway.
            const rememberedLegacyH = Number(runtime.legacyNodeHeight);
            h = (
                Number.isFinite(rememberedLegacyH) &&
                !obviouslyPoisonedHeight(rememberedLegacyH, minNodeH)
            )
                ? Math.max(minNodeH, rememberedLegacyH)
                : minNodeH;
        } else if (
            runtime.lastRenderMode == null &&
            obviouslyPoisonedHeight(h, minNodeH)
        ) {
            // Also heal workflows that are opened directly in Legacy after an
            // older version serialized an absurd height.
            h = minNodeH;
        } else if (forceMin && h < minNodeH) {
            h = minNodeH;
        }

        if (w !== Number(node.size?.[0]) || h !== Number(node.size?.[1])) {
            node.setSize([w, h]);
        }

        const actualH = Number(node.size?.[1] || h);
        const available = Math.max(legacyMinH, actualH - y - BOTTOM_PAD);
        runtime.root.style.height = `${available}px`;
        const cardsMin = Math.max(COLLAPSED_MIN_HEIGHT, legacyMinH - NON_CARD_FIXED);
        runtime.cards.style.height = `${Math.max(cardsMin, available - NON_CARD_FIXED)}px`;
        runtime.cards.style.flex = "1 1 auto";
        runtime.cards.style.minHeight = "";
        runtime.cards.style.maxHeight = "none";
        runtime.domHeight = available;
        if (!obviouslyPoisonedHeight(actualH, minNodeH)) {
            runtime.legacyNodeHeight = actualH;
        }
        runtime.lastRenderMode = "legacy";
        node.graph?.setDirtyCanvas(true, true);
    } finally {
        runtime.syncingDomHeight = false;
    }
}

function installInvalidationHooks(node, runtime) {
    // Image references are no longer graph sockets. Other input/parameter
    // changes deliberately preserve explicit clip validation as before.
}


function buildUi(node) {
    if (node.__h3Extender) return node.__h3Extender;

    if (!document.getElementById("h3-extender-spin-style")) {
        const styleEl = document.createElement("style");
        styleEl.id = "h3-extender-spin-style";
        styleEl.textContent = "@keyframes h3spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }";
        document.head.appendChild(styleEl);
    }

    const jsonWidget = getWidget(node, "clips_json");
    const refsWidget = getWidget(node, "refs_json");
    if (!jsonWidget || !refsWidget) return null;
    hideNativeWidget(node, jsonWidget);
    hideNativeWidget(node, refsWidget);

    const state = parseState(jsonWidget.value);
    const refsState = parseRefsState(refsWidget.value);

    const root = document.createElement("div");
    root.style.width = "100%";
    root.style.minWidth = "0";
    root.style.height = `${UI_MIN_HEIGHT}px`;
    root.style.minHeight = `${UI_MIN_HEIGHT}px`;
    // Official DOMWidgetImpl.computeLayoutSize() reads this CSS variable as a
    // fallback to getMinHeight. Keeping both makes the intrinsic contract clear
    // to current and slightly older Nodes 2.0 frontends.
    root.style.setProperty("--comfy-widget-min-height", `${NODES2_MIN_HEIGHT}px`);
    root.style.boxSizing = "border-box";
    root.style.display = "flex";
    root.style.flexDirection = "column";
    root.style.padding = "5px 0 4px";
    root.style.overflow = "visible";

    const toolbar = document.createElement("div");
    toolbar.style.display = "flex";
    toolbar.style.minWidth = "0";
    toolbar.style.gap = "7px";
    toolbar.style.alignItems = "center";
    toolbar.style.marginBottom = "7px";

    const saveProjectButton = document.createElement("button");
    saveProjectButton.textContent = "保存 / Save";
    saveProjectButton.title = "Save settings + disk cache as a portable .ext project";
    saveProjectButton.style.cssText = "font-size:10px;padding:1px 6px;background:#4a3a6a;border:1px solid #5a4a7a;border-radius:3px;color:#dcc;cursor:pointer;";
    saveProjectButton.addEventListener("click", (e) => {
        e.preventDefault();
        saveProject(node, runtime);
    });

    const loadProjectButton = document.createElement("button");
    loadProjectButton.textContent = "加载 / Load";
    loadProjectButton.title = "Load a .ext project into this Extender node";
    loadProjectButton.style.cssText = "font-size:10px;padding:1px 6px;background:#3a5a4a;border:1px solid #4a6a5a;border-radius:3px;color:#cdc;cursor:pointer;";

    const projectFileInput = document.createElement("input");
    projectFileInput.type = "file";
    projectFileInput.accept = ".ext,application/zip,application/octet-stream";
    projectFileInput.style.display = "none";
    projectFileInput.addEventListener("change", async () => {
        const file = projectFileInput.files?.[0];
        projectFileInput.value = "";
        if (file) await loadProjectFile(node, runtime, file);
    });
    loadProjectButton.addEventListener("click", (e) => {
        e.preventDefault();
        if (projectBusy(runtime)) {
            alert("Wait for the current clip generation to finish before loading a project.");
            return;
        }
        projectFileInput.click();
    });

    const batchDurLabel = document.createElement("span");
    batchDurLabel.textContent = "时长(s) / Dur:";
    batchDurLabel.style.cssText = "font-size:11px;color:#aaa;margin-left:6px;";

    const batchDurInput = document.createElement("input");
    batchDurInput.type = "number";
    batchDurInput.min = "1";
    batchDurInput.max = "300";
    batchDurInput.step = "0.5";
    batchDurInput.value = "15";
    batchDurInput.style.cssText = "width:48px;font-size:11px;padding:1px 4px;background:#1a1a1a;border:1px solid #444;border-radius:3px;color:#ddd;";

    const batchDurBtn = document.createElement("button");
    batchDurBtn.textContent = "应用全部 / Apply All";
    batchDurBtn.style.cssText = "font-size:10px;padding:1px 6px;background:#2a4a6a;border:1px solid #3a5a7a;border-radius:3px;color:#cde;cursor:pointer;";
    batchDurBtn.title = "批量设置所有CLIP的时长";
    batchDurBtn.addEventListener("click", (e) => {
        e.preventDefault();
        const val = parseFloat(batchDurInput.value);
        if (!Number.isFinite(val) || val <= 0) return;
        runtime.state.clips.forEach((clip) => {
            clip.duration = val;
            clip.validated = false;
        });
        invalidateFrom(runtime.state, 0);
        updateHidden(node, runtime);
        render(node, runtime);
    });

    const batchCtxLabel = document.createElement("span");
    batchCtxLabel.textContent = "上下文 / Context:";
    batchCtxLabel.style.cssText = "font-size:11px;color:#aaa;margin-left:6px;";

    const batchCtxBtn = document.createElement("button");
    batchCtxBtn.textContent = "全部开启 / Enable All";
    batchCtxBtn.style.cssText = "font-size:10px;padding:1px 6px;background:#2a6a4a;border:1px solid #3a7a5a;border-radius:3px;color:#cde;cursor:pointer;";
    batchCtxBtn.title = "批量开启/关闭所有CLIP的上下文参考";
    let batchCtxOn = true;
    batchCtxBtn.addEventListener("click", (e) => {
        e.preventDefault();
        batchCtxOn = !batchCtxOn;
        runtime.state.clips.forEach((clip) => {
            clip.context_enabled = batchCtxOn;
            clip.validated = false;
        });
        batchCtxBtn.textContent = batchCtxOn ? "全部关闭 / Disable All" : "全部开启 / Enable All";
        batchCtxBtn.style.background = batchCtxOn ? "#6a3a3a" : "#2a6a4a";
        batchCtxBtn.style.borderColor = batchCtxOn ? "#7a4a4a" : "#3a7a5a";
        invalidateFrom(runtime.state, 0);
        updateHidden(node, runtime);
        render(node, runtime);
    });
    batchCtxBtn.textContent = "全部关闭 / Disable All";
    batchCtxBtn.style.background = "#6a3a3a";
    batchCtxBtn.style.borderColor = "#7a4a4a";

    const counter = document.createElement("span");
counter.style.fontSize = "11px";
counter.style.opacity = ".8";
counter.style.marginLeft = "6px";

const mergeOutputBtn = document.createElement("button");
    mergeOutputBtn.textContent = "合并输出 / Merge Output";
    mergeOutputBtn.title = "将所有已生成好的CLIP合并为一个视频输出（不会重新生成任何CLIP）";
    mergeOutputBtn.style.cssText = "font-size:11px;padding:2px 10px;background:#2a6a3a;border:1px solid #3a7a4a;border-radius:4px;color:#cde;cursor:pointer;margin-left:6px;font-weight:bold;";

    // Unified sync button: re-sync ALL clips from external prompt_source
    // 统一刷新按钮：从外部输入源重新同步所有CLIP
    const syncAllClipsBtn = document.createElement("button");
    syncAllClipsBtn.textContent = "统一刷新 / Sync All";
    syncAllClipsBtn.title = "从外部输入源重新同步全局提示词和所有CLIP\nRe-sync global prompt and all CLIPs from external source";
    syncAllClipsBtn.style.cssText = "font-size:11px;padding:2px 10px;background:#8a4a2a;border:1px solid #aa5a3a;border-radius:4px;color:#fcd;cursor:pointer;margin-left:6px;font-weight:bold;";
    syncAllClipsBtn.addEventListener("click", (e) => {
        e.preventDefault();
        try {
            const psInput = node.inputs?.find(inp => inp.name === "prompt_source");
            if (!psInput || psInput.link == null) {
                runtime.statusText = "未连接外部输入源 / No external source";
                status.textContent = runtime.statusText;
                return;
            }
            const link = app.graph.links[psInput.link];
            if (!link || link.origin_id == null) return;
            const srcNode = app.graph.getNodeById(link.origin_id);
            if (!srcNode) return;
            let text = null;
            const srcWidget = srcNode.widgets?.find(w => w.name === "text" || w.type === "text_multiline" || w.type === "customtext");
            if (srcWidget && srcWidget.value != null) text = srcWidget.value;
            else text = srcNode.widgets_values?.[0];
            if (text == null) return;
            const newText = String(text);
            runtime._lastPromptSourceText = newText;
            const sbMarkerRe = /\[(?:分镜|Shot|shot|SHOT)\s*\d+\]/;
            const sbMatch = newText.match(sbMarkerRe);
            const globalText = sbMatch ? newText.slice(0, sbMatch.index).trim() : newText.trim();
            const storyboardText = sbMatch ? newText.slice(sbMatch.index).trim() : "";
            if (globalText !== undefined) {
                runtime.state.global_prompt = globalText;
                if (runtime.globalPromptTextarea) runtime.globalPromptTextarea.value = globalText;
            }
            if (storyboardText) {
                const segments = parseStoryboard(storyboardText);
                for (let i = 0; i < segments.length; i++) {
                    while (runtime.state.clips.length <= i) {
                        runtime.state.clips.push(newClip(runtime.state.clips.length));
                    }
                    runtime.state.clips[i].prompt = segments[i].prompt;
                    runtime.state.clips[i].duration = String(segments[i].duration);
                }
            }
            updateHidden(node, runtime);
            if (typeof runtime.renderGlobalAssetPanel === "function") runtime.renderGlobalAssetPanel();
            render(node, runtime);
            runtime.statusText = "已同步 / Synced";
            status.textContent = runtime.statusText;
        } catch(err) {
            runtime.statusText = "同步失败 / Sync failed";
            status.textContent = runtime.statusText;
        }
    });
mergeOutputBtn.addEventListener("click", (e) => {
    e.preventDefault();
    // Check if any clip is selected for replacement
    const hasReplace = runtime.state.clips.some((c) => c.replace_mode);
    if (hasReplace) {
        if (!confirm("当前有CLIP处于重新生成状态，点击合并输出将取消重新生成并直接合并已有结果。是否继续？")) {
            return;
        }
    }
    // Set merge_output flag, clear all replace_mode
    runtime.state.clips.forEach((c) => { c.replace_mode = false; });
    runtime.state.merge_output = true;
    updateHidden(node, runtime);
    // Trigger queue prompt
    try {
        const queueBtn = document.getElementById("queue-button");
        if (queueBtn) queueBtn.click();
        else if (window.app?.queuePrompt) window.app.queuePrompt();
    } catch (qe) {
        console.warn("[H3 Extender] Could not auto-queue prompt, please click Queue manually", qe);
    }
    // Reset merge_output after a short delay (will be consumed by backend)
    setTimeout(() => {
        runtime.state.merge_output = false;
        updateHidden(node, runtime);
    }, 500);
});

const status = document.createElement("span");
status.style.fontSize = "11px";
status.style.opacity = ".72";
status.style.marginLeft = "auto";
status.style.whiteSpace = "nowrap";
status.style.overflow = "hidden";
status.style.textOverflow = "ellipsis";
status.style.maxWidth = "45%";

toolbar.append(saveProjectButton, loadProjectButton, batchDurLabel, batchDurInput, batchDurBtn, batchCtxLabel, batchCtxBtn, counter, mergeOutputBtn, syncAllClipsBtn, status, projectFileInput);

    // Store merge output button reference for later updates


    const refFileInput = document.createElement("input");
    refFileInput.type = "file";
    refFileInput.accept = "image/*,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff";
    refFileInput.style.display = "none";

    const refsSection = document.createElement("div");
    refsSection.style.display = "none";
    refsSection.style.height = `${REF_SECTION_HEIGHT}px`;
    refsSection.style.minWidth = "0";
    refsSection.style.flex = `0 0 ${REF_SECTION_HEIGHT}px`;
    refsSection.style.boxSizing = "border-box";
    refsSection.style.marginBottom = "7px";

    const refsHeader = document.createElement("div");
    refsHeader.textContent = "参考图片 — 双击缩略图编辑 / REFERENCE IMAGES — double-click to edit";
    refsHeader.style.fontSize = "10px";
    refsHeader.style.fontWeight = "600";
    refsHeader.style.opacity = ".75";
    refsHeader.style.height = "13px";
    refsHeader.style.lineHeight = "13px";
    refsHeader.style.marginBottom = "1px";

    const refsRow = document.createElement("div");
    refsRow.style.display = "flex";
    refsRow.style.flexDirection = "row";
    refsRow.style.width = "100%";
    refsRow.style.maxWidth = "100%";
    refsRow.style.minWidth = "0";
    refsRow.style.gap = "7px";
    refsRow.style.overflowX = "auto";
    refsRow.style.overflowY = "hidden";
    refsRow.style.paddingBottom = `${REF_SCROLLBAR_SPACE}px`;
    refsRow.style.boxSizing = "border-box";
    refsRow.style.height = `${REF_SECTION_HEIGHT - 14}px`;
    refsRow.style.scrollbarGutter = "stable";
    refsSection.append(refsHeader, refsRow);

    // Global prompt section (between toolbar and clips)
    const globalPromptSection = document.createElement("div");
    globalPromptSection.style.cssText = "display:flex;flex-direction:row;gap:4px;margin-bottom:6px;align-items:stretch;position:relative;";

    // Left panel: global-prompt asset references (same as per-clip left panel)
    const gpLeftPanel = document.createElement("div");
    gpLeftPanel.style.cssText = "width:140px;min-width:140px;flex-shrink:0;border-right:1px solid rgba(255,255,255,.08);background:rgba(0,0,0,.15);padding:6px;display:flex;flex-direction:column;overflow-y:auto;max-height:400px;align-self:stretch;";

    const gpLabel = document.createElement("div");
    gpLabel.textContent = "全局提示词";
    gpLabel.style.cssText = "font-size:10px;color:#888;flex-shrink:0;width:60px;padding-top:5px;";
    const gpTextarea = document.createElement("textarea");
    gpTextarea.value = state.global_prompt || "";
    gpTextarea.spellcheck = false;
    gpTextarea.placeholder = "全局提示词 (Global Prompt) — 将添加到每个CLIP提示词前\n连接外部输入源后自动同步内容";
    gpTextarea.style.cssText = "flex:1 1 auto;min-height:180px;max-height:400px;resize:vertical;font-size:11px;background:rgba(0,0,0,.27);border:1px solid rgba(255,255,255,.15);color:inherit;border-radius:5px;padding:4px 6px;box-sizing:border-box;align-self:stretch;";
    gpTextarea.addEventListener("input", () => {
        state.global_prompt = gpTextarea.value;
        updateHidden(node, runtime);
        renderGlobalOverlay();
        renderAssetPanel(gpLeftPanel, gpPseudoClip, node, runtime, gpTextarea);
    });
    // Make global prompt textarea work with asset library @图N clicks
    gpTextarea.addEventListener("focus", () => {
        window._h3_activeTextarea = gpTextarea;
        window._h3_activeClip = null;
        window._h3_activeLeftPanel = gpLeftPanel;
        window._h3_refreshAssetPanel = function() {
            state.global_prompt = gpTextarea.value;
            updateHidden(node, runtime);
            renderGlobalAssetPanel();
        };
    });
    gpTextarea.addEventListener("blur", () => {
        gpTextarea._savedCursorPos = gpTextarea.selectionStart;
    });
    gpTextarea.addEventListener("keyup", () => {
        gpTextarea._savedCursorPos = gpTextarea.selectionStart;
    });
    gpTextarea.addEventListener("click", () => {
        gpTextarea._savedCursorPos = gpTextarea.selectionStart;
    });

    const gpExpandBtn = document.createElement("button");
    gpExpandBtn.textContent = "⤢";
    gpExpandBtn.title = "放大全局提示词窗口";
    gpExpandBtn.style.cssText = "flex-shrink:0;width:22px;height:22px;font-size:12px;background:rgba(40,40,40,.8);border:1px solid rgba(255,255,255,.15);border-radius:4px;color:#aaa;cursor:pointer;align-self:flex-start;";
    let gpExpanded = false;
    gpExpandBtn.addEventListener("click", (e) => {
        e.preventDefault();
        gpExpanded = !gpExpanded;
        if (gpExpanded) {
            gpTextarea.style.position = "absolute";
            gpTextarea.style.inset = "0";
            gpTextarea.style.zIndex = "30";
            gpTextarea.style.width = "100%";
            gpTextarea.style.height = "100%";
            gpTextarea.style.maxHeight = "100%";
            gpTextarea.style.resize = "none";
            gpExpandBtn.textContent = "✕";
            gpExpandBtn.style.zIndex = "31";
            gpExpandBtn.style.position = "absolute";
            gpExpandBtn.style.top = "4px";
            gpExpandBtn.style.right = "4px";
        } else {
            gpTextarea.style.position = "";
            gpTextarea.style.inset = "";
            gpTextarea.style.zIndex = "";
            gpTextarea.style.width = "";
            gpTextarea.style.height = "";
            gpTextarea.style.maxHeight = "400px";
            gpTextarea.style.resize = "vertical";
            gpExpandBtn.textContent = "⤢";
            gpExpandBtn.style.zIndex = "";
            gpExpandBtn.style.position = "";
            gpExpandBtn.style.top = "";
            gpExpandBtn.style.right = "";
        }
        syncDomHeight(runtime);
    });

    const gpRefreshBtn = document.createElement("button");
    gpRefreshBtn.textContent = "↻";
    gpRefreshBtn.title = "刷新：立即同步外部输入源内容";
    gpRefreshBtn.style.cssText = "flex-shrink:0;width:22px;height:22px;font-size:12px;background:rgba(40,40,40,.8);border:1px solid rgba(255,255,255,.15);border-radius:4px;color:#8cf;cursor:pointer;align-self:flex-start;";
    gpRefreshBtn.addEventListener("click", (e) => {
        e.preventDefault();
        syncGlobalPromptFromInput(node, runtime);
        renderGlobalAssetPanel();
        render(node, runtime);
    });

    // Pseudo-clip that proxies prompt get/set to the global prompt state
    const gpPseudoClip = {
        get prompt() { return gpTextarea.value || ""; },
        set prompt(v) { gpTextarea.value = v; state.global_prompt = v; },
    };

    function renderGlobalAssetPanel() {
        renderAssetPanel(gpLeftPanel, gpPseudoClip, node, runtime, gpTextarea);
        renderGlobalOverlay();
    }

    // Overlay technique: textarea (transparent text, visible caret) on top,
    // overlay div (visible text + inline thumbnails) behind.
    // 覆盖层技术：textarea文本透明+可见光标在上层，div显示文本+内联缩略图在下层
    const gpOverlay = document.createElement("div");
    gpOverlay.style.cssText = "position:absolute;top:0;left:0;width:100%;height:100%;font-size:11px;border:1px solid rgba(255,255,255,.15);color:inherit;border-radius:5px;padding:4px 6px;box-sizing:border-box;overflow-y:auto;pointer-events:none;white-space:pre-wrap;word-wrap:break-word;z-index:1;background:rgba(0,0,0,.27);";
    gpTextarea.style.color = "transparent";
    gpTextarea.style.background = "transparent";
    gpTextarea.style.caretColor = "white";
    gpTextarea.style.position = "absolute";
    gpTextarea.style.top = "0";
    gpTextarea.style.left = "0";
    gpTextarea.style.width = "100%";
    gpTextarea.style.height = "100%";
    gpTextarea.style.zIndex = "2";
    gpTextarea.style.resize = "none";
    gpTextarea.style.outline = "none";
    const gpEditorWrap = document.createElement("div");
    gpEditorWrap.style.cssText = "position:relative;flex:1 1 auto;min-height:180px;max-height:400px;align-self:stretch;";
    gpEditorWrap.append(gpOverlay, gpTextarea);
    gpTextarea.addEventListener("scroll", () => {
        gpOverlay.scrollTop = gpTextarea.scrollTop;
        gpOverlay.scrollLeft = gpTextarea.scrollLeft;
    });

    function escHtml(s) {
        return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }
    window._h3_escHtml = escHtml;

    function renderGlobalOverlay() {
        const text = gpTextarea.value || "";
        const refs = parseAssetRefs(text);
        if (refs.length === 0) { gpOverlay.textContent = text; return; }
        let html = "";
        let lastIdx = 0;
        const assetList = runtime._h3_assetCache;
        refs.forEach(function(ref) {
            const idx = text.indexOf(ref.tag, lastIdx);
            if (idx < 0) return;
            html += escHtml(text.slice(lastIdx, idx + ref.tag.length));
            if (ref.type !== "audios" && assetList) {
                const items = assetList[ref.type] || [];
                const assetItem = items.find(i => i.index === ref.index);
                if (assetItem) {
                    const src = ref.type === "videos"
                        ? "/bsai/video_frame?filename=" + encodeURIComponent(assetItem.name)
                        : "/bsai/asset_file?type=" + ref.type + "&filename=" + encodeURIComponent(assetItem.name);
                    html += '<img src="' + src + '" style="width:20px;height:20px;object-fit:cover;border:1px solid #555;border-radius:2px;vertical-align:middle;margin:0 1px;" alt="">';
                }
            }
            lastIdx = idx + ref.tag.length;
        });
        html += escHtml(text.slice(lastIdx));
        gpOverlay.innerHTML = html;
    }

    globalPromptSection.append(gpLeftPanel, gpLabel, gpEditorWrap, gpRefreshBtn, gpExpandBtn);

    // Sync external prompt_source input to the textarea (legacy widget callback)
    const gpWidget = node.widgets?.find(w => w.name === "global_prompt" || w.name === "prompt_source");
    if (gpWidget) {
        const origGpWidgetChanged = gpWidget.callback;
        gpWidget.callback = function(v) {
            if (v !== undefined && v !== null) {
                const fullText = String(v);
                const sbMarkerRe = /\[(?:分镜|Shot|shot|SHOT)\s*\d+\]/;
                const sbMatch = fullText.match(sbMarkerRe);
                const globalText = sbMatch ? fullText.slice(0, sbMatch.index).trim() : fullText.trim();
                gpTextarea.value = globalText;
                state.global_prompt = globalText;
                updateHidden(node, runtime);
                renderGlobalAssetPanel();
            }
            if (typeof origGpWidgetChanged === "function") origGpWidgetChanged.call(this, v);
        };
    }

    const cards = document.createElement("div");
    cards.style.display = "flex";
    cards.style.minWidth = "0";
    cards.style.flexDirection = "column";
    cards.style.gap = "9px";
    cards.style.overflowX = "hidden";
    cards.style.overflowY = "auto";
    cards.style.padding = `0 0 ${CARD_SCROLLBAR_SPACE}px 0`;
    cards.style.scrollbarGutter = "stable";
    cards.style.boxSizing = "border-box";
    cards.style.scrollBehavior = "smooth";
    cards.style.flex = "1";
    cards.style.minHeight = `${NODES2_CARDS_MIN_HEIGHT}px`;

    // ── Bottom section: CLIPS total duration (left) + Add/Del buttons (right) ──
    const bottomBar = document.createElement("div");
    bottomBar.style.cssText = "display:flex;align-items:center;justify-content:space-between;gap:8px;padding:6px 4px;border-top:2px solid rgba(255,255,255,.25);margin-top:auto;margin-bottom:2px;flex-shrink:0;background:#152030;";

    const clipsTotalLabel = document.createElement("span");
    clipsTotalLabel.style.cssText = "font-size:12px;font-weight:bold;color:#8ab4f8;white-space:nowrap;";

    const bottomBtnGroup = document.createElement("div");
    bottomBtnGroup.style.cssText = "display:flex;align-items:center;gap:6px;";

    const addClipBtn = document.createElement("button");
    addClipBtn.textContent = "添加CLIP / Add CLIP";
    addClipBtn.style.cssText = "font-size:11px;padding:2px 10px;background:#2a5a8a;border:1px solid #3a6a9a;border-radius:4px;color:#cde;cursor:pointer;font-weight:bold;";

    const delAllClipsBtn = document.createElement("button");
    delAllClipsBtn.textContent = "全部删除CLIP / DEL ALL CLIP";
    delAllClipsBtn.style.cssText = "font-size:11px;padding:2px 10px;background:#6a2a2a;border:1px solid #7a3a3a;border-radius:4px;color:#fcd;cursor:pointer;font-weight:bold;";

    bottomBtnGroup.append(addClipBtn, delAllClipsBtn);
    bottomBar.append(clipsTotalLabel, bottomBtnGroup);

    root.append(toolbar, refsSection, globalPromptSection, cards, bottomBar, refFileInput);

    const restoredValidatedPrefix = validatedPrefixFromState(state);
    const runtime = {
        state,
        jsonWidget,
        refsState,
        refsWidget,
        root,
        toolbar,
        refsSection,
        refsRow,
        globalPromptSection,
        globalPromptTextarea: gpTextarea,
        cards,
        counter,
        status,
        saveProjectButton,
        loadProjectButton,
        projectFileInput,
        refFileInput,
        mergeOutputBtn,
        bottomBar,
        clipsTotalLabel,
        addClipBtn,
        delAllClipsBtn,
        pendingRefSlot: -1,
        refBusy: false,
        projectOperationBusy: false,
        projectName: String(node?.properties?.h3_project_name || ""),
        domWidget: null,
        domHeight: UI_MIN_HEIGHT,
        syncingDomHeight: false,
        lastRenderMode: null,
        legacyNodeHeight: null,
        // clips_json already preserves the validated flags. Seed the visual state
        // immediately, then replace it with the authoritative disk manifest below.
        cachedCount: restoredValidatedPrefix,
        validatedCount: restoredValidatedPrefix,
        statusText: restoredValidatedPrefix
            ? `Restoring cache | validated ${restoredValidatedPrefix}`
            : "Ready",
        activeClipIndex: -1,
        activePhase: "idle",
        cacheStateRequestRunning: false,
        cacheStateRestored: false,
        expectedResolution: null,
        resolvedWidth: 0,
        resolvedHeight: 0,
        resolutionGuide: "",
        guideSourceWidth: 0,
        guideSourceHeight: 0,
        resolutionFallback: false,
        resolutionMismatch: false,
        manualWidth: Number(node?.properties?.h3_manual_width || getWidget(node, "width")?.value || 896),
        manualHeight: Number(node?.properties?.h3_manual_height || getWidget(node, "height")?.value || 576),
        applyingResolutionMirror: false,
        resolutionMirrorActive: false,
        resolutionCallbacksInstalled: false,
        // True only after an explicit .ext Load has imposed its archived
        // geometry. Any user resolution edit clears it; editing megapixels
        // also switches straight back to Auto because MP has no Manual meaning.
        projectResolutionLoaded: false,
        // True after a live resolution change has made the on-disk cache stale.
        // The backend clears/rebuilds that cache on the next Queue.
        resolutionInvalidated: false,
        ready: false,
        _gpPollTimer: null,
    };
    runtime.renderGlobalAssetPanel = renderGlobalAssetPanel;
    runtime._gpOverlay = gpOverlay;

    renderGlobalAssetPanel();

    // ── Bottom button handlers (added after runtime is fully defined) ──
    runtime.addClipBtn.addEventListener("click", (e) => {
        e.preventDefault();
        const newClipData = newClip(runtime.state.clips.length);
        runtime.state.clips.push(newClipData);
        updateHidden(node, runtime);
        render(node, runtime);
        requestAnimationFrame(() => {
            runtime.cards.scrollTop = runtime.cards.scrollHeight;
        });
    });

    runtime.delAllClipsBtn.addEventListener("click", (e) => {
        e.preventDefault();
        if (runtime.state.clips.length <= 1) return;
        if (!confirm("确定要删除所有CLIP并重置为一个默认CLIP吗？\nAre you sure you want to delete ALL clips and reset to one default clip?")) return;
        const freshClip = newClip(0);
        runtime.state.clips = [freshClip];
        updateHidden(node, runtime);
        render(node, runtime);
    });

    // Poll for unified prompt_source input changes every 800ms
    // 轮询统一外部提示词输入，自动拆分全局提示词和分镜内容
    runtime._lastPromptSourceText = "";
    runtime._psPollTimer = setInterval(() => {
        try {
            const psInput = node.inputs?.find(inp => inp.name === "prompt_source");
            if (!psInput || psInput.link == null) return;
            const link = app.graph.links[psInput.link];
            if (!link || link.origin_id == null) return;
            const srcNode = app.graph.getNodeById(link.origin_id);
            if (!srcNode) return;
            let text = null;
            const srcWidget = srcNode.widgets?.find(w => w.name === "text" || w.type === "text_multiline" || w.type === "customtext");
            if (srcWidget && srcWidget.value != null) {
                text = srcWidget.value;
            } else {
                text = srcNode.widgets_values?.[0];
            }
            if (text == null) return;
            const newText = String(text);
            if (newText === runtime._lastPromptSourceText) return;
            runtime._lastPromptSourceText = newText;

            // Split at first [分镜N] marker
            const sbMarkerRe = /\[(?:分镜|Shot|shot|SHOT)\s*\d+\]/;
            const sbMatch = newText.match(sbMarkerRe);
            const globalText = sbMatch ? newText.slice(0, sbMatch.index).trim() : newText.trim();
            const storyboardText = sbMatch ? newText.slice(sbMatch.index).trim() : "";

            let changed = false;

            // 1. Update global prompt (always sync, even if empty)
            if (runtime.state.global_prompt !== globalText) {
                runtime.state.global_prompt = globalText;
                if (runtime.globalPromptTextarea && runtime.globalPromptTextarea.value !== globalText) {
                    runtime.globalPromptTextarea.value = globalText;
                }
                changed = true;
            }

            // 1b. Always refresh global asset panel (overlay + thumbnails)
            if (typeof runtime.renderGlobalAssetPanel === "function") {
                runtime.renderGlobalAssetPanel();
            }

            // 2. Parse storyboard segments and auto-create/update CLIPs
            if (storyboardText) {
                const segments = parseStoryboard(storyboardText);
                if (segments.length > 0) {
                    // Add CLIPs to match segment count
                    while (runtime.state.clips.length < segments.length) {
                        runtime.state.clips.push(newClip(runtime.state.clips.length));
                        changed = true;
                    }
                    // Update each CLIP's prompt and duration from segments
                    for (let i = 0; i < segments.length && i < runtime.state.clips.length; i++) {
                        const seg = segments[i];
                        const clip = runtime.state.clips[i];
                        if (clip.prompt !== seg.prompt) {
                            clip.prompt = seg.prompt;
                            changed = true;
                        }
                        const newDur = String(seg.duration);
                        if (String(clip.duration) !== newDur) {
                            clip.duration = newDur;
                            changed = true;
                        }
                        clip.validated = false;
                    }
                }
            }

            if (changed) {
                updateHidden(node, runtime);
                render(node, runtime);
            }
        } catch (e) { /* ignore */ }
    }, 800);

    refFileInput.addEventListener("change", async () => {
        const file = refFileInput.files?.[0];
        const slot = Number(runtime.pendingRefSlot);
        refFileInput.value = "";
        runtime.pendingRefSlot = -1;
        if (file && Number.isInteger(slot) && slot >= 0 && slot < MAX_IMAGE_REFS) {
            await uploadReference(node, runtime, slot, file);
        }
    });

    const domWidget = node.addDOMWidget("h3_extender_timeline", "timeline", root, {
        serialize: false,
        hideOnZoom: false,
        // DOMWidgetImpl.computeLayoutSize() is the official size contract.
        // Give Nodes 2.0 a little more intrinsic room, while keeping the old
        // Legacy minimum unchanged.
        getMinHeight: () => calculateMinHeight(runtime),
        getHeight: () => runtime.domHeight,
        afterResize: (resizedNode) => {
            const mode = domWidgetRenderMode(root);
            if (mode === "nodes2") {
                // Re-assert only intrinsic CSS. Never derive anything from
                // node.size while Vue is resolving its grid.
                const dynH = calculateMinHeight(runtime);
                root.style.height = "auto";
                root.style.minHeight = `${dynH}px`;
                root.style.setProperty("--comfy-widget-min-height", `${dynH}px`);
                root.style.maxHeight = "none";
                root.style.flex = "1 1 auto";
                root.style.paddingTop = `${5 + NODES2_TOP_GAP}px`;
                root.style.overflow = "visible";
                cards.style.height = "auto";
                cards.style.flex = "1 1 auto";
                cards.style.minHeight = `${Math.max(COLLAPSED_MIN_HEIGHT, dynH - TOOLBAR_HEIGHT)}px`;
                runtime.lastRenderMode = "nodes2";
            } else if (mode === "legacy") {
                requestAnimationFrame(() => syncDomHeight(resizedNode, runtime, false));
            } else {
                requestAnimationFrame(() => syncDomHeight(resizedNode, runtime, false));
            }
        },
    });
    runtime.domWidget = domWidget;
    node.__h3Extender = runtime;

    installInvalidationHooks(node, runtime);
    wrapResolutionWidgetCallbacks(node, runtime);
    render(node, runtime);

    const oldConfigure = node.onConfigure;
    node.onConfigure = function (info) {
        if (oldConfigure) oldConfigure.apply(this, arguments);

        // Force-update the node title to the new display name
        this.title = "BSAI ComfyUI H3 Film Factory";

        // Workflow widget arrays are positional. The two v14.25 resolution
        // widgets were intentionally appended after clips_json so old values do
        // not shift. If this is an older workflow, force Manual to preserve its
        // historical width/height behavior. Newly-created nodes default to Auto.
        const savedWidgetValues = Array.isArray(info?.widgets_values) ? info.widgets_values : null;
        const hasSavedResolutionMode = Boolean(
            savedWidgetValues?.some((value) => value === "auto_from_ref" || value === "manual")
        );
        if (savedWidgetValues && !hasSavedResolutionMode) {
            setWidgetValue(this, "resolution_mode", "manual");
        }

        // Migrate old workflows that pre-date output_mode / filename_prefix
        // widgets: empty or missing combo values cause server-side validation
        // failures. Set sensible defaults so the prompt is accepted.
        const omWidget = getWidget(this, "output_mode");
        if (omWidget && (!omWidget.value || omWidget.value === "")) {
            setWidgetValue(this, "output_mode", "none");
        }
        const fpWidget = getWidget(this, "filename_prefix");
        if (fpWidget && (!fpWidget.value || fpWidget.value === "")) {
            setWidgetValue(this, "filename_prefix", "H3_Extender");
        }

        requestAnimationFrame(() => {
            const removedLegacyRefs = removeLegacyImageRefInputs(this);
            runtime.state = parseState(runtime.jsonWidget.value);
            runtime.refsState = parseRefsState(runtime.refsWidget.value);
            updateRefsHidden(this, runtime);
            const restoredValidatedPrefix = validatedPrefixFromState(runtime.state);
            runtime.cachedCount = restoredValidatedPrefix;
            for (let i = 0; i < restoredValidatedPrefix && i < runtime.state.clips.length; i++) {
                const c = runtime.state.clips[i];
                if (c && !c._previewVideoUrl) {
                    c._previewLoaded = true;
                    delete c._latentPreviewUrl;
                    delete c._latentStep;
                    delete c._latentTotal;
                }
            }
            runtime.validatedCount = restoredValidatedPrefix;
            if (removedLegacyRefs && refCount(runtime) === 0) {
                runtime.statusText = "Legacy image-ref sockets removed — load references in the Extender";
            }
            if (String(getWidget(this, "resolution_mode")?.value || "manual") === "manual") {
                rememberManualResolution(
                    this,
                    runtime,
                    Number(getWidget(this, "width")?.value || runtime.manualWidth || 896),
                    Number(getWidget(this, "height")?.value || runtime.manualHeight || 576),
                );
            }
            render(this, runtime);
            // Restore global prompt textarea value (render doesn't update it)
            // 恢复全局提示词textarea值（render不更新它）
            if (runtime.globalPromptTextarea) {
                runtime.globalPromptTextarea.value = runtime.state.global_prompt || "";
            }
            if (typeof runtime.renderGlobalAssetPanel === "function") {
                runtime.renderGlobalAssetPanel();
            }
            restoreCacheState(this, runtime);
            syncResolutionMirror(this, runtime);
            syncDomHeight(this, runtime, true);
            // Aggressive initial sync: try multiple times to catch source node loading
            // 激进的初始同步：多次尝试以捕获源节点加载完成
            [100, 500, 1200, 2500, 4000].forEach(delay => {
                setTimeout(() => {
                    try {
                        const psInput = this.inputs?.find(inp => inp.name === "prompt_source");
                        if (!psInput || psInput.link == null) return;
                        const link = app.graph.links[psInput.link];
                        if (!link || link.origin_id == null) return;
                        const srcNode = app.graph.getNodeById(link.origin_id);
                        if (!srcNode) return;
                        let text = null;
                        const srcWidget = srcNode.widgets?.find(w => w.name === "text" || w.type === "text_multiline" || w.type === "customtext");
                        if (srcWidget && srcWidget.value != null) {
                            text = srcWidget.value;
                        } else {
                            text = srcNode.widgets_values?.[0];
                        }
                        if (text == null) return;
                        const newText = String(text);
                        if (newText === runtime._lastPromptSourceText) return;
                        runtime._lastPromptSourceText = newText;
                        const sbMarkerRe = /\[(?:分镜|Shot|shot|SHOT)\s*\d+\]/;
                        const sbMatch = newText.match(sbMarkerRe);
                        const globalText = sbMatch ? newText.slice(0, sbMatch.index).trim() : newText.trim();
                        const storyboardText = sbMatch ? newText.slice(sbMatch.index).trim() : "";
                        if (globalText) {
                            runtime.state.global_prompt = globalText;
                            if (runtime.globalPromptTextarea) runtime.globalPromptTextarea.value = globalText;
                            if (typeof runtime.renderGlobalAssetPanel === "function") runtime.renderGlobalAssetPanel();
                        }
                        if (storyboardText) {
                            const segments = parseStoryboard(storyboardText);
                            for (let i = 0; i < segments.length; i++) {
                                while (runtime.state.clips.length <= i) {
                                    runtime.state.clips.push(newClip(runtime.state.clips.length));
                                }
                                runtime.state.clips[i].prompt = segments[i].prompt;
                                runtime.state.clips[i].duration = String(segments[i].duration);
                            }
                        }
                        updateHidden(this, runtime);
                        render(this, runtime);
                    } catch(e) { /* source not ready yet */ }
                }, delay);
            });
        });
    };

    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            removeLegacyImageRefInputs(node);
            runtime.ready = true;
            restoreCacheState(node, runtime);
            syncResolutionMirror(node, runtime);
            syncDomHeight(node, runtime, true);
        });
    });

    return runtime;
}


function findExtenderNodeByExecutionId(nodeId) {
    const graph = app.graph;
    if (!graph) return null;

    const wanted = String(nodeId);
    for (const node of graph._nodes || []) {
        if (
            String(node?.id) === wanted &&
            (node?.comfyClass === TARGET || node?.type === TARGET)
        ) {
            return node;
        }
    }
    return null;
}

function scrollActiveCard(runtime, index) {
    if (!runtime?.cards || index < 0) return;
    const card = runtime.cards.querySelector(
        `[data-clip-index="${index}"]`
    );
    if (!card) return;

    const left = Math.max(
        0,
        card.offsetLeft -
            Math.max(0, (runtime.cards.clientWidth - card.offsetWidth) / 2)
    );
    runtime.cards.scrollTo({
        left,
        behavior: "smooth",
    });
}

// A cancelled/failed ComfyUI execution does not call this node's onExecuted
// callback. Without an explicit terminal-event reset, the last custom progress
// event (usually "sampling") leaves the active card permanently blue until a
// page refresh. ComfyUI exposes official execution_interrupted/error/success
// websocket events, so clear only the transient rendering state when a prompt
// terminates. Cache/validation/card data are deliberately left untouched.
function clearTransientRenderingState(statusText = null) {
    const graph = app.graph;
    if (!graph) return;

    for (const node of graph._nodes || []) {
        if (!(node?.comfyClass === TARGET || node?.type === TARGET)) continue;

        const runtime = node.__h3Extender;
        if (!runtime) continue;

        const wasActive =
            Number(runtime.activeClipIndex) >= 0 ||
            ["preparing", "sampling", "complete"].includes(
                String(runtime.activePhase || "")
            );
        if (!wasActive) continue;

        runtime.activeClipIndex = -1;
        runtime.activePhase = "idle";
        if (statusText) runtime.statusText = statusText;

        render(node, runtime);
        node.graph?.setDirtyCanvas(true, true);
    }
}

app.registerExtension({
    name: "BSAIMiniMaxH3.Extender",

    setup() {
        // Official ComfyUI terminal execution events. In particular, pressing
        // Kill/Interrupt raises execution_interrupted and bypasses onExecuted.
        api.addEventListener("execution_interrupted", () => {
            clearTransientRenderingState("Rendering interrupted");
        });
        api.addEventListener("execution_error", () => {
            clearTransientRenderingState("Execution stopped by error");
        });
        // Defensive cleanup: a successful prompt should never leave a stale
        // rendering highlight even if another frontend/backend change prevents
        // the expected node UI callback from arriving.
        api.addEventListener("execution_success", () => {
            clearTransientRenderingState();
        });

        api.addEventListener(PROMPT_PACK_EVENT, ({ detail }) => {
            const node = findExtenderNodeByExecutionId(detail?.node);
            if (!node) return;

            const runtime = buildUi(node);
            if (!runtime || !detail?.clips_json) return;

            runtime.jsonWidget.value = String(detail.clips_json);
            runtime.state = parseState(detail.clips_json);
            const count = Number(detail?.prompt_count || runtime.state.clips.length || 0);
            const source = String(detail?.source || "External prompt pack");
            runtime.statusText = `${source}: imported ${count} prompt${count === 1 ? "" : "s"} → ${count} clip${count === 1 ? "" : "s"}`;
            updateHidden(node, runtime);
            render(node, runtime);
            syncDomHeight(node, runtime, false);
            node.graph?.setDirtyCanvas(true, true);
        });

        api.addEventListener(PROGRESS_EVENT, ({ detail }) => {
            const node = findExtenderNodeByExecutionId(detail?.node);
            if (!node) return;

            const runtime = buildUi(node);
            if (!runtime) return;

            const index = Number(detail?.clip_index ?? -1);
            runtime.activeClipIndex = Number.isFinite(index) ? index : -1;
            runtime.activePhase = String(detail?.phase || "idle");
            runtime.statusText = String(detail?.message || runtime.statusText || "Ready");

            if (runtime.activePhase === "complete" && index >= 0) {
                const clip = runtime.state.clips[index];
                if (clip) {
                    delete clip._latentPreviewUrl;
                    delete clip._latentStep;
                    delete clip._latentTotal;
                    const msg = String(detail?.message || "");
                    if (msg.includes("preview error")) {
                        // Preview decode failed — don't mark as loaded
                        clip._previewLoaded = false;
                        delete clip._previewVideoUrl;
                        clip._previewError = msg;
                    } else {
                        clip._previewLoaded = true;
                        delete clip._previewVideoUrl;
                        delete clip._previewError;
                    }
                }
            }

            render(node, runtime);

            if (runtime.activeClipIndex >= 0) {
                requestAnimationFrame(() => {
                    scrollActiveCard(runtime, runtime.activeClipIndex);
                });
            }

            node.graph?.setDirtyCanvas(true, true);
        });

        api.addEventListener(LATENT_PREVIEW_EVENT, ({ detail }) => {
            const node = findExtenderNodeByExecutionId(detail?.node);
            if (!node) {
                console.warn("[H3 Extender] latent preview: node not found for id", detail?.node);
                return;
            }

            const runtime = buildUi(node);
            if (!runtime) {
                console.warn("[H3 Extender] latent preview: runtime null for node", node?.id);
                return;
            }

            const index = Number(detail?.clip_index ?? -1);
            if (index < 0 || index >= runtime.state.clips.length) {
                console.warn("[H3 Extender] latent preview: clip_index out of range", index, runtime.state.clips.length);
                return;
            }

            const clip = runtime.state.clips[index];
            if (!clip) {
                console.warn("[H3 Extender] latent preview: clip null at index", index);
                return;
            }

            clip._latentPreviewUrl = String(detail?.image || "");
            clip._latentStep = Number(detail?.step ?? 0);
            clip._latentTotal = Number(detail?.total_steps ?? 0);

            render(node, runtime);
            node.graph?.setDirtyCanvas(true, true);
        });

        window.addEventListener("bsai-assets-changed", () => {
            app.graph._nodes.forEach(node => {
                if (node.type === "MiniMaxH3Extender" && node.__h3Extender) {
                    delete node.__h3Extender._assetCache;
                    delete node.__h3Extender._h3_assetCache;
                }
            });
            h3FetchAssets();
        });

        // Pre-load the asset list for the referenced-assets left panel.
        h3FetchAssets().then(() => {
            app.graph?._nodes.forEach(node => {
                if (node.type === "MiniMaxH3Extender" && node.__h3Extender?.renderGlobalAssetPanel) {
                    node.__h3Extender.renderGlobalAssetPanel();
                }
            });
        });
    },

    async beforeRegisterNodeDef(nodeType, nodeData) {
        // FinalDecode: migrate old workflows missing export_clips widget
        if (nodeData.name === FINAL_TARGET) {
            const oldFinalConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function (info) {
                if (oldFinalConfigure) oldFinalConfigure.apply(this, arguments);
                const ecWidget = this.widgets?.find(w => w.name === "export_clips");
                if (ecWidget && (!ecWidget.value || ecWidget.value === "")) {
                    ecWidget.value = "all";
                }
            };
            return;
        }

        if (nodeData.name !== TARGET) return;

        const oldConnChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function (side, slot, connected, link_info, ioSlot) {
            if (oldConnChange) oldConnChange.apply(this, arguments);
            // When global_prompt input connection changes, fetch the value
            const runtime = buildUi(this);
            if (!runtime) return;
            const gpInput = this.inputs?.find(inp => inp.name === "global_prompt");
            if (gpInput && gpInput.link != null) {
                // A link is connected — fetch the source node's widget value
                try {
                    const link = app.graph.links[gpInput.link];
                    if (link && link.origin_id != null) {
                        const srcNode = app.graph.getNodeById(link.origin_id);
                        if (srcNode && srcNode.widgets_values) {
                            // Text multiline nodes store text in widgets_values[0]
                            const text = srcNode.widgets_values[0];
                            if (text != null && String(text).trim()) {
                                runtime.state.global_prompt = String(text);
                                updateHidden(this, runtime);
                                render(this, runtime);
                            }
                        }
                    }
                } catch (e) { /* ignore */ }
            }
        };

        const oldCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = oldCreated ? oldCreated.apply(this, arguments) : undefined;

            // Force-update the node title to the new display name
            this.title = "BSAI ComfyUI H3 Film Factory";

            // New nodes must start in Auto resolution mode. Older workflows are
            // still migrated to Manual later in onConfigure when they do not
            // contain the v14.25+ resolution widgets.
            setWidgetValue(this, "resolution_mode", "auto_from_ref");

            const runtime = buildUi(this);
            removeLegacyImageRefInputs(this);
            if (runtime) {
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => syncDomHeight(this, runtime, true));
                });
                h3FetchAssets();
            }
            return r;
        };

        const oldExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            if (oldExecuted) oldExecuted.apply(this, arguments);
            const runtime = buildUi(this);
            if (!runtime) return;

            const info = message?.h3_extender_state?.[0];
            if (!info) return;

            if (info.clips_json) {
                runtime.jsonWidget.value = info.clips_json;
                runtime.state = parseState(info.clips_json);
            }
            // Safety: clear replace_mode and merge_output after execution
            runtime.state.merge_output = false;
            if (runtime.state.clips) {
                runtime.state.clips.forEach((c) => { c.replace_mode = false; });
            }
            if (info.refs_json) {
                runtime.refsWidget.value = info.refs_json;
                runtime.refsState = parseRefsState(info.refs_json);
            }
            if (info.global_prompt_connected && info.global_prompt_value) {
                runtime.state.global_prompt = String(info.global_prompt_value);
            }
    
            const generated = Array.isArray(info.generated) ? info.generated : [];
            for (const humanIndex of generated) {
                const i = Number(humanIndex) - 1;
                const clip = runtime.state.clips[i];
                // Only prepare a next seed for a candidate. A validated cached
                // clip is never touched by this automatic seed behavior.
                if (clip && !clip.validated) {
                    advanceSeedAfterGenerate(clip);
                }
            }

            // Critical: persist the next seed into clips_json. This changes the
            // node input hash, so pressing Queue again really re-executes it.
            if (generated.length) {
                updateHidden(this, runtime);
            }

            runtime.cachedCount = Number(info.cached_count || 0);
            for (let i = 0; i < runtime.cachedCount && i < runtime.state.clips.length; i++) {
                const c = runtime.state.clips[i];
                if (c && !c._previewVideoUrl) {
                    c._previewLoaded = true;
                    delete c._latentPreviewUrl;
                    delete c._latentStep;
                    delete c._latentTotal;
                }
            }
            runtime.validatedCount = Number(info.validated_count || 0);
            runtime.resolvedWidth = Number(info.resolved_width || 0);
            runtime.resolvedHeight = Number(info.resolved_height || 0);
            runtime.resolutionGuide = String(info.resolution_guide || "");
            runtime.guideSourceWidth = Number(info.resolution_guide_width || 0);
            runtime.guideSourceHeight = Number(info.resolution_guide_height || 0);
            runtime.resolutionFallback = Boolean(info.resolution_fallback);
            runtime.resolutionMismatch = Boolean(info.resolution_mismatch);
            if (runtime.resolvedWidth > 0 && runtime.resolvedHeight > 0) {
                // Backend execution is authoritative. After a resolution-change
                // run, this becomes the new baseline for future invalidation.
                runtime.expectedResolution = {
                    width: runtime.resolvedWidth,
                    height: runtime.resolvedHeight,
                };
                runtime.resolutionInvalidated = false;
            }
            runtime.activeClipIndex = -1;
            runtime.activePhase = "idle";
            runtime.statusText = String(info.status || "Ready");
            if (runtime.resolutionMismatch && Number(info.cache_width || 0) > 0) {
                runtime.statusText +=
                    ` | WARNING cache ${Number(info.cache_width)}x${Number(info.cache_height)} differs`;
            }
            syncResolutionMirror(this, runtime);
            render(this, runtime);
            syncDomHeight(this, runtime, false);
        };
    },
});
