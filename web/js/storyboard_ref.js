// A_MiniMaxH3StoryboardRefVideo / A_MiniMaxH3StoryboardViewer
// =================================================================
// 两个节点的前端：
//   1) A_MiniMaxH3StoryboardViewer（按 prompt_N 外层分段的官方提示词看板）
//      每个 prompt_N 标题整行可独立展开；顶部单按钮显示 / 隐藏看板。
//      标题行点击后，会把「连到同一脚本源」的打包节点 clip_index
//      自动设为该段（做法乙，不加连线）。卡片时长优先取 detailed_description 的 [Recommended duration]。
//      看板使用固定高度和内部滚动；展开 / 折叠卡片不会自动改变节点高度。
//   2) A_MiniMaxH3StoryboardRefVideo（打包节点，瘦身）
//      只保留一行小字状态：共 N 段 · 当前第 X 段。

import { app } from "../../../scripts/app.js";

const PACK_TYPE = "A_MiniMaxH3StoryboardRefVideo";
const VIEWER_TYPE = "A_MiniMaxH3StoryboardViewer";
const SEGMENT_TYPE = "A_MiniMaxH3OfficialRefPromptSegment";
const DURATION_TYPE = "A_MiniMaxH3StoryboardDuration";
const BOARD_WIDGET = "a_storyboard_board";
const STATUS_WIDGET = "a_pack_status";

const DEFAULT_SEGMENT_MARKER = "===== prompt_N =====";
const MAX_CLIP_DURATION_SECONDS = 15;
const MAX_BOARD_HEIGHT = 720;
const BOARD_VIEWPORT_HEIGHT = 520;
// 看板DOM高度跟随节点高度：节点上边缘到看板顶部的固定占用（标题栏 + 三个输入行）
const BOARD_TOP_RESERVE = 132;
const BOARD_MIN_HEIGHT = 150;
const REF_RE = /@(?:图|img)\s*(\d+)|@(?:视频|vid)\s*(\d+)|@(?:音频|aud)\s*(\d+)|<(Picture|Video|Audio)\s+(\d+)>/gi;
const MAX_CLIPS = 512;
// 旧版 BSAI 分镜格式（[分镜N]：...）与后端 official_prompt._convert_legacy_storyboard_format 对齐
const LEGACY_SHOT_RE = /^[ \t]*\[分镜[ \t]*(\d+)\][ \t]*[：:]?/gm;
const LEGACY_TAIL_RE = /^[ \t]*\[自检结果\]/m;
const GLOBAL_CARD_KEY = "__global__";

const C = {
    border: "#3a3a3a",
    borderSel: "#5b9cf6",
    text: "#d4d4d4",
    sub: "#9a9a9a",
    accent: "#8fb8ff",
};

function secondsToFrames(s) {
    let n = Math.max(5, Math.round(s * 24));
    while (n % 17 !== 5) n++;
    return n;
}

function maxExplicitDurationSeconds(text) {
    const re = /(?:^|[^0-9A-Za-z.:])(\d+(?:\.\d+)?)\s*-?\s*(hours?|hrs?|hr|h|minutes?|mins?|min|seconds?|secs?|sec|s|小时|分钟|秒)(?![A-Za-z])/gi;
    const factors = { h: 3600, hr: 3600, hrs: 3600, hour: 3600, hours: 3600,
        min: 60, mins: 60, minute: 60, minutes: 60,
        s: 1, sec: 1, secs: 1, second: 1, seconds: 1, 秒: 1, 分钟: 60, 小时: 3600 };
    const durationValues = (source) => {
        const raw = String(source || "");
        const values = [];
        for (const match of raw.matchAll(re)) {
            const start = match.index + match[0].indexOf(match[1]);
            const end = match.index + match[0].length;
            const before = raw.slice(Math.max(0, start - 40), start);
            const after = raw.slice(end, end + 32);
            const audioBefore = /(?:<Audio\s+\d+>|\b(?:audio|song|track|soundtrack|music)\b)[^.!?\n]{0,24}$/i.test(before);
            const audioAfter = /^[ \t,;:-]*(?:(?:of|for|from)[ \t]+)?(?:audio|song|track|soundtrack|music)\b/i.test(after);
            const outputBefore = /\b(?:clip|video|segment|generation|output|duration|length|runtime|dance|performance)\b|(?:视频|片段|时长|长度|舞蹈|表演)/i.test(before.slice(-32));
            const outputAfter = /^[ \t-]*(?:clip|video|segment|dance|performance)\b|^[ \t-]*(?:视频|片段|舞蹈|表演)/i.test(after);
            if ((audioBefore || audioAfter) && !outputAfter) continue;
            if (!outputBefore && !outputAfter) continue;
            const value = Number(match[1]) * factors[match[2].toLowerCase()];
            if (Number.isFinite(value)) values.push(value);
        }
        return values;
    };
    const raw = String(text || "").replace(/\r\n?/g, "\n");
    let summary = "";
    const sectionRe = /^([a-z_]+):[ \t]*(.*?)(?=^[a-z_]+:[ \t]*|$)/gims;
    for (const match of raw.matchAll(sectionRe)) {
        if (match[1].toLowerCase() === "summary") { summary = match[2]; break; }
    }
    const preferred = durationValues(summary);
    const values = preferred.length ? preferred : durationValues(raw);
    return values.length ? Math.max(...values) : null;
}

function sectionBody(text, sectionName) {
    const lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
    const body = [];
    let active = false;
    for (const line of lines) {
        const header = /^([a-z_]+):[ \t]*/i.exec(line);
        if (header) {
            if (active) return body.join("\n");
            active = header[1].toLowerCase() === sectionName;
        } else if (active) {
            body.push(line);
        }
    }
    return active ? body.join("\n") : "";
}

function recommendedDurationSeconds(text) {
    const detail = sectionBody(text, "detailed_description");
    const lines = detail.split("\n").map((line) => line.trim());
    const matches = [];
    for (let i = 0; i < lines.length; i++) {
        const match = /^\[Recommended duration\]:[ \t]*(\d+)[ \t]+seconds?$/i.exec(lines[i]);
        if (match) matches.push({ index: i, seconds: Number(match[1]) });
    }
    const metadataLines = lines.filter((line) => line.toLowerCase().includes("[recommended duration]"));
    if (metadataLines.length > 1) throw new Error("[Recommended duration] must appear exactly once.");
    if (!matches.length) {
        if (metadataLines.length) throw new Error("[Recommended duration] must be written as [Recommended duration]: N seconds.");
        return null;
    }
    if (matches.length !== 1) throw new Error("[Recommended duration] must appear exactly once.");
    const firstContent = lines.findIndex((line) => line.length > 0);
    if (matches[0].index !== firstContent) throw new Error("[Recommended duration] must be the first line after detailed_description:");
    return matches[0].seconds;
}

function referenceInfo(match) {
    const number = Number(match[1] || match[2] || match[3] || match[5]);
    let kind;
    if (match[1] || String(match[4]).toLowerCase() === "picture") kind = "images";
    else if (match[2] || String(match[4]).toLowerCase() === "video") kind = "videos";
    else kind = "audios";
    return { kind, number, tag: match[0] };
}

function collectReferences(text) {
    const refs = [];
    const byKey = new Map();
    REF_RE.lastIndex = 0;
    let match;
    while ((match = REF_RE.exec(String(text || ""))) !== null) {
        const ref = referenceInfo(match);
        const key = ref.kind + ":" + ref.number;
        const existing = byKey.get(key);
        if (existing) existing.count++;
        else {
            ref.count = 1;
            byKey.set(key, ref);
            refs.push(ref);
        }
    }
    return refs;
}

function escapeRegex(text) {
    return String(text).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function flexibleMarkerLiteral(text) {
    return String(text).split(/([ \t]+)/).map((part) => /^[ \t]+$/.test(part) ? "[ \\t]*" : escapeRegex(part)).join("");
}

function makeMarkerRegex(markerTemplate) {
    const template = String(markerTemplate || DEFAULT_SEGMENT_MARKER).trim() || DEFAULT_SEGMENT_MARKER;
    const placeholder = /\{N\}|(prompt|clip)(_?)N|\bN\b/i.exec(template);
    if (placeholder) {
        const start = placeholder.index;
        const end = start + placeholder[0].length;
        const word = placeholder[1] || "";
        const separator = word && placeholder[2] ? "_?" : "";
        const fixed = word || (placeholder[0] === "{N}" ? "" : placeholder[0].slice(0, -1));
        return { regex: new RegExp(flexibleMarkerLiteral(template.slice(0, start)) + flexibleMarkerLiteral(fixed) + separator + "(\\d+)" + flexibleMarkerLiteral(template.slice(end)), "gi"), hasNumber: true };
    }
    return { regex: new RegExp(flexibleMarkerLiteral(template), "gi"), hasNumber: false };
}

// --- 旧版 [分镜N] 格式支持：与后端 _convert_legacy_storyboard_format 对应 ---
// 第一个 [分镜N] 之前的内容 = 全局提示词（整体风格/统一运镜/角色档案/道具档案/人声分布总表），
// 每个 [分镜N] 之后到下一个标记之前 = 一条独立分镜，末尾 [自检结果] 归入全局块。
function splitLegacyStoryboard(raw) {
    const marks = [...String(raw || "").matchAll(LEGACY_SHOT_RE)];
    if (!marks.length) return null;
    const tailMatch = LEGACY_TAIL_RE.exec(raw);
    const tailIndex = tailMatch ? tailMatch.index : -1;
    const prefixText = raw.slice(0, marks[0].index);
    const blocks = marks.map((mark, i) => {
        const start = mark.index + mark[0].length;
        let end = marks[i + 1] ? marks[i + 1].index : raw.length;
        if (tailIndex >= 0 && tailIndex > start && tailIndex < end) end = tailIndex;
        return { num: Number(mark[1]), text: raw.slice(start, end).trim() };
    });
    const tailText = tailIndex >= 0 ? raw.slice(tailIndex).trim() : "";
    const globalText = [prefixText.trim(), tailText].filter((t) => t).join("\n\n");
    return { globalText, blocks };
}

function legacyBlockSeconds(text) {
    const m = /^[ \t]*0?1[ \t]*[-–—][ \t]*(\d+(?:\.\d+)?)[ \t]*秒/m.exec(String(text || ""));
    return m ? Number(m[1]) : null;
}

function legacySceneSnippet(text) {
    const first = String(text || "").split("\n").map((l) => l.trim()).find((l) => l.length > 0) || "";
    const head = first.split(" → ")[0].trim();
    const snippet = head || first;
    return snippet.length > 90 ? snippet.slice(0, 88) + "…" : snippet;
}

function parseStoryboard(text, videoDurationSec = 0, fallbackFrames = 124, markerTemplate = DEFAULT_SEGMENT_MARKER) {
    if (!text) return null;
    const raw = String(text).replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n");
    try {
        const { regex: headerRe, hasNumber } = makeMarkerRegex(markerTemplate);
        const headers = [...raw.matchAll(headerRe)];
        // 没有任何 ===== prompt_N ===== 标记、但存在 [分镜N] 旧版标记时，按旧版格式切分
        if (!headers.length) {
            const legacy = splitLegacyStoryboard(raw);
            if (legacy && legacy.blocks.length) {
                if (legacy.blocks.length > MAX_CLIPS) throw new Error(`More than the ${MAX_CLIPS} segment limit.`);
                const clips = legacy.blocks.map((block, i) => {
                    const scene = legacySceneSnippet(block.text);
                    let durationSec = legacyBlockSeconds(block.text);
                    if (durationSec == null) durationSec = recommendedDurationSeconds(block.text);
                    if (durationSec == null) durationSec = maxExplicitDurationSeconds(block.text);
                    if (durationSec == null) {
                        durationSec = legacy.blocks.length === 1 && Number(videoDurationSec) > 0
                            ? Number(videoDurationSec)
                            : Number(fallbackFrames) / 24;
                    }
                    return {
                        num: block.num || i + 1,
                        label: `[Shot ${block.num || i + 1}]${scene ? " " + scene : ""}`,
                        rawLabel: `[分镜${block.num || i + 1}]`,
                        text: block.text,
                        startSec: 0,
                        sec: durationSec,
                        overLimit: durationSec > MAX_CLIP_DURATION_SECONDS,
                        frames: secondsToFrames(durationSec),
                        assets: collectReferences(block.text),
                        legacy: true,
                    };
                });
                return { globalText: legacy.globalText, clips, legacy: true };
            }
        }
        const promptSegments = headers.length
            ? headers.map((header, i) => ({
                label: hasNumber ? Number(header[1]) : i + 1,
                marker: header[0],
                prompt: raw.slice(header.index + header[0].length, headers[i + 1]?.index ?? raw.length).trim(),
            }))
            : [{ label: 1, marker: "", prompt: raw.trim() }];
        if (promptSegments.length > MAX_CLIPS) throw new Error(`More than the ${MAX_CLIPS} segment limit.`);

        const clips = [];
        for (const segment of promptSegments) {
            const { label, marker, prompt } = segment;
            if (label < 1) throw new Error("prompt marker numbering must start at 1.");
            if (!prompt) throw new Error(`No prompt content after marker ${marker || `#${label}`}.`);

            let durationSec = recommendedDurationSeconds(prompt);
            if (durationSec == null) durationSec = maxExplicitDurationSeconds(prompt);
            if (durationSec == null) {
                durationSec = promptSegments.length === 1 && Number(videoDurationSec) > 0
                    ? Number(videoDurationSec)
                    : Number(fallbackFrames) / 24;
            }
            clips.push({
                num: label,
                label: marker ? (hasNumber ? marker : `${marker} ${promptSegments.indexOf(segment) + 1}`) : "Full prompt",
                text: prompt,
                startSec: 0,
                sec: durationSec,
                overLimit: durationSec > MAX_CLIP_DURATION_SECONDS,
                frames: secondsToFrames(durationSec),
                assets: collectReferences(prompt),
            });
        }
        return { globalText: "", clips };
    } catch (error) {
        return { error: error.message || String(error), clips: [] };
    }
}

function el(tag, style = {}) {
    const d = document.createElement(tag);
    Object.assign(d.style, style);
    return d;
}

function getInputOrigin(node, name) {
    try {
        const inp = node.inputs?.find((i) => i.name === name);
        if (!inp || inp.link == null) return null;
        const link = node.graph.links[inp.link];
        if (!link) return null;
        return { id: link.origin_id, slot: link.origin_slot, node: node.graph.getNodeById(link.origin_id) };
    } catch (e) {
        return null;
    }
}

function readConnectedString(node, inputName, fallback = null) {
    const o = getInputOrigin(node, inputName);
    if (!o || !o.node || !o.node.widgets) return fallback;
    try {
        const origin = o.node;
        const w = origin.widgets.find(
            (x) => typeof x.value === "string" &&
                (x.name === "value" || x.name === "prompt" || x.type === "customtext" || x.type === "STRING")
        );
        if (w) return w.value;
        const first = origin.widgets[0];
        if (first && typeof first.value === "string") return first.value;
    } catch (e) {}
    return fallback;
}

function readPromptSourceText(node) {
    const inputName = node.comfyClass === SEGMENT_TYPE ? "full_reference_prompt" : "prompt_source";
    return readConnectedString(node, inputName, null);
}

function readAssetLibrary(node) {
    const o = getInputOrigin(node, "asset_library");
    if (!o || !o.node || !o.node.widgets) return null;
    try {
        const origin = o.node;
        const get = (name) => {
            const w = origin.widgets.find((x) => x.name === name);
            if (!w) return [];
            try {
                const a = JSON.parse(w.value || "[]");
                return Array.isArray(a) ? a : [];
            } catch (e) { return []; }
        };
        const originType = origin.comfyClass || origin.type || "";
        const prefix = String(originType).startsWith("A_") ? "/absai" : "/bsai";
        return { images: get("image_files"), videos: get("video_files"), audios: get("audio_files"), originType, prefix };
    } catch (e) {
        return null;
    }
}

// 找连到同一提示词源的打包 / 提取节点，点击卡片时同步 clip_index。
function findPackNodes(viewer) {
    const src = getInputOrigin(viewer, "prompt_source");
    const graph = viewer.graph;
    const packs = [];
    if (src) {
        for (const n of (graph._nodes || [])) {
            if (n.comfyClass !== PACK_TYPE && n.comfyClass !== SEGMENT_TYPE && n.comfyClass !== DURATION_TYPE) continue;
            const inputName = n.comfyClass === SEGMENT_TYPE ? "full_reference_prompt" : "prompt_source";
            const ps = getInputOrigin(n, inputName);
            if (ps && ps.id === src.id) packs.push(n);
        }
    }
    if (packs.length) return packs;
    // 看板常读「原始提示词」，打包节点读「注入节拍后的提示词」，两条链路的直接上游不同，
    // 这里退回为图上所有打包/提取/时长节点，保证点击卡片仍能联动 clip_index 和时长读取。
    const fallback = [];
    for (const n of (graph._nodes || [])) {
        if (n.comfyClass === PACK_TYPE || n.comfyClass === SEGMENT_TYPE || n.comfyClass === DURATION_TYPE) fallback.push(n);
    }
    return fallback;
}

function getClipIndex(node) {
    const w = node.widgets?.find((x) => x.name === "clip_index");
    let v = w ? parseInt(w.value, 10) : NaN;
    if (!Number.isFinite(v)) {
        // clip_index 常被 SeedNode 之类的整数输入接管，widget 已转成输入
        const o = getInputOrigin(node, "clip_index");
        const ow = o?.node?.widgets?.find((x) => x.name === "value")
            || o?.node?.widgets?.find((x) => typeof x.value === "number");
        if (ow) v = parseInt(ow.value, 10);
    }
    return Number.isFinite(v) && v >= 1 ? v : 1;
}

function getSelected(viewer) {
    const packs = findPackNodes(viewer);
    if (packs.length) {
        const v = getClipIndex(packs[0]);
        if (Number.isFinite(v)) return v;
    }
    return viewer.__aLocalSel || 1;
}

function setSelected(viewer, n) {
    viewer.__aLocalSel = n;
    for (const p of findPackNodes(viewer)) {
        const w = p.widgets?.find((x) => x.name === "clip_index");
        if (w) {
            w.value = n;
            try { w.callback?.(n, null, p, null); } catch (e) {}
        }
        p.setDirtyCanvas?.(true, false);
    }
}

function getBoardOpen(viewer) {
    if (typeof viewer.__aBoardOpen === "boolean") return viewer.__aBoardOpen;
    const saved = viewer.properties?.aStoryboardBoardOpen;
    viewer.__aBoardOpen = saved === false ? false : true;
    return viewer.__aBoardOpen;
}

function setBoardOpen(viewer, open) {
    const wasOpen = getBoardOpen(viewer);
    viewer.__aBoardOpen = !!open;
    viewer.properties = viewer.properties || {};
    viewer.properties.aStoryboardBoardOpen = viewer.__aBoardOpen;
    // 打开/收起时同步节点高度，避免收起后留下大片空白
    try {
        const width = viewer.size?.[0] || 600;
        if (wasOpen && !viewer.__aBoardOpen) {
            viewer.__aSavedH = viewer.size?.[1] || 0;
            viewer.setSize?.([width, BOARD_TOP_RESERVE + 44]);
        } else if (!wasOpen && viewer.__aBoardOpen) {
            viewer.setSize?.([width, Math.max(BOARD_TOP_RESERVE + BOARD_MIN_HEIGHT, viewer.__aSavedH || BOARD_TOP_RESERVE + 400)]);
        }
    } catch (e) {}
    viewer.setDirtyCanvas?.(true, true);
}

// 看板顶端到节点顶端的实际占用：优先读该 DOM 组件真实的 last_y，读不到才用估算值
function boardTopReserve(viewer) {
    try {
        const w = viewer.widgets?.find((x) => x.name === BOARD_WIDGET);
        const ly = w && typeof w.last_y === "number" ? w.last_y : NaN;
        if (Number.isFinite(ly) && ly >= 60 && ly <= 240) return Math.round(ly);
    } catch (e) {}
    return BOARD_TOP_RESERVE;
}

function boardHeight(viewer) {
    const total = viewer.size?.[1] || 0;
    return Math.max(BOARD_MIN_HEIGHT, Math.round(total - boardTopReserve(viewer) - 4));
}

// 展开卡片正文高度：跟随看板可用高度，拖大拉高、拖小收紧
function cardBodyHeight(viewer) {
    const board = boardHeight(viewer);
    return Math.max(240, Math.min(900, board - 110));
}

function ensureViewerNodeSize(viewer) {
    try {
        const width = viewer.size?.[0] || 600;
        const minHeight = BOARD_TOP_RESERVE + BOARD_MIN_HEIGHT + 8;
        if ((viewer.size?.[1] || 0) < minHeight) {
            const size = [width, minHeight];
            if (typeof viewer.setSize === "function") viewer.setSize(size);
            else viewer.size = size;
            viewer.setDirtyCanvas?.(true, true);
        }
    } catch (e) {}
}

function hideWidget(w) {
    if (!w) return;
    w.computeSize = () => [0, 0];
    w.draw = () => {};
    if (w.inputEl) w.inputEl.style.display = "none";
    if (w.labelEl) w.labelEl.style.display = "none";
}

// 状态条节点高度适配
function syncHeight(node, root) {
    try {
        const content = Math.min(root.scrollHeight, MAX_BOARD_HEIGHT);
        if (content <= 0) return;
        const sz = node.computeSize?.();
        const height = sz && sz[1] > 0 ? Math.min(sz[1], MAX_BOARD_HEIGHT + 30) : content + 30;
        if (height > 0 && node.__aLastH !== height) {
            node.__aLastH = height;
            node.size = [node.size[0], height];
            node.setDirtyCanvas?.(true, true);
        }
    } catch (e) {}
}

function stopCanvasPointerEvents(element) {
    for (const type of ["pointerdown", "mousedown", "dblclick", "wheel"]) {
        element.addEventListener(type, (event) => event.stopPropagation());
    }
}

function assetUrl(prefix, kind, filename) {
    if (!filename) return null;
    if (kind === "images") return prefix + "/asset_file?type=images&filename=" + encodeURIComponent(filename);
    if (kind === "videos") return prefix + "/video_frame?filename=" + encodeURIComponent(filename);
    return null;
}

function buildAssetThumb(ref, library) {
    const arr = ref.kind === "images" ? library?.images : ref.kind === "videos" ? library?.videos : library?.audios;
    const filename = arr?.[ref.number - 1] || null;
    const row = el("div", {
        display: "flex", alignItems: "center", gap: "5px", minWidth: "0", margin: "3px 0",
        fontFamily: "sans-serif", fontSize: "11px", color: C.text,
    });
    const box = el("div", {
        width: "40px", height: "40px", flexShrink: "0", position: "relative", overflow: "hidden",
        border: "1px solid #45484f", borderRadius: "4px", background: "#141519", boxSizing: "border-box",
    });
    box.title = filename || (ref.tag + " (missing from library)");
    if (filename && (ref.kind === "images" || ref.kind === "videos")) {
        const image = document.createElement("img");
        image.loading = "lazy";
        image.style.cssText = "width:100%;height:100%;object-fit:cover;display:block;";
        image.src = assetUrl(library?.prefix || "/absai", ref.kind, filename);
        image.onerror = () => {
            image.remove();
            box.textContent = ref.kind === "videos" ? "▶" : "N/A";
            box.style.display = "grid";
            box.style.placeItems = "center";
            box.style.color = "#777";
        };
        box.appendChild(image);
    } else {
        box.textContent = ref.kind === "audios" ? "♫" : "N/A";
        box.style.display = "grid";
        box.style.placeItems = "center";
        box.style.color = "#777";
    }
    row.appendChild(box);
    const label = el("span", { minWidth: "0", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#aab" });
    label.textContent = ref.tag;
    label.title = filename || "No matching file in the library";
    row.appendChild(label);
    if (ref.count > 1) {
        const count = el("span", { marginLeft: "auto", padding: "1px 4px", borderRadius: "4px", background: "#b32626", color: "#fff", fontSize: "10px", flexShrink: "0" });
        count.textContent = "×" + ref.count;
        row.appendChild(count);
    }
    return row;
}

function renderReferencedAssets(panel, refs, library) {
    panel.replaceChildren();
    const title = el("div", { color: "#888", fontSize: "11px", paddingBottom: "5px", borderBottom: "1px solid #333", marginBottom: "4px" });
    title.textContent = "Referenced Assets";
    panel.appendChild(title);
    if (!refs.length) {
        const empty = el("div", { padding: "8px 2px", color: "#666", textAlign: "center", fontSize: "10px" });
        empty.textContent = "No references";
        panel.appendChild(empty);
        return;
    }
    refs.forEach((ref) => panel.appendChild(buildAssetThumb(ref, library)));
}

function buildInlineAsset(ref, filename, prefix) {
    const box = el("span", {
        display: "inline-flex", alignItems: "center", justifyContent: "center", verticalAlign: "middle",
        width: "22px", height: "22px", borderRadius: "3px", overflow: "hidden", margin: "0 2px 1px 1px",
        border: "1px solid #555", background: "#141519", position: "relative", boxSizing: "border-box",
    });
    box.title = filename || (ref.tag + " (missing from library)");
    if (filename && (ref.kind === "images" || ref.kind === "videos")) {
        const image = document.createElement("img");
        image.loading = "lazy";
        image.style.cssText = "width:100%;height:100%;object-fit:cover;display:block;";
        image.src = assetUrl(prefix || "/absai", ref.kind, filename);
        image.onerror = () => {
            image.remove();
            box.textContent = ref.kind === "videos" ? "▶" : "?";
            box.style.color = "#888";
        };
        box.appendChild(image);
    } else {
        box.textContent = ref.kind === "audios" ? "♫" : "?";
        box.style.color = "#888";
        box.style.fontSize = "10px";
    }
    return box;
}

function renderRichPrompt(container, text, library) {
    container.replaceChildren();
    const source = String(text || "");
    REF_RE.lastIndex = 0;
    let cursor = 0;
    let match;
    while ((match = REF_RE.exec(source)) !== null) {
        if (match.index > cursor) container.appendChild(document.createTextNode(source.slice(cursor, match.index)));
        const ref = referenceInfo(match);
        const arr = ref.kind === "images" ? library?.images : ref.kind === "videos" ? library?.videos : library?.audios;
        container.appendChild(buildInlineAsset(ref, arr?.[ref.number - 1] || null, library?.prefix));
        const label = el("span", { color: "#9ec1ff", whiteSpace: "nowrap", fontSize: "11px" });
        label.textContent = ref.tag;
        container.appendChild(label);
        cursor = REF_RE.lastIndex;
    }
    if (cursor < source.length) container.appendChild(document.createTextNode(source.slice(cursor)));
}

function buildClipCard(clip, orderIndex, selected, library, viewer) {
    const collapsed = Object.prototype.hasOwnProperty.call(viewer.__aCollapsed || {}, orderIndex)
        ? !!viewer.__aCollapsed[orderIndex]
        : true;
    const card = el("div", {
        boxSizing: "border-box", width: "calc(100% - 16px)", margin: "4px 8px",
        display: "flex", flex: "0 0 auto", flexDirection: "column", background: "#23252b",
        border: "1px solid " + (selected ? C.borderSel : C.border), borderRadius: "7px", overflow: "hidden",
        fontFamily: "sans-serif", boxShadow: selected ? "0 0 6px rgba(91,156,246,0.35)" : "none",
    });
    const head = el("div", {
        width: "100%", height: "36px", minHeight: "36px", flex: "0 0 36px", boxSizing: "border-box",
        border: "0", textAlign: "left", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px", padding: "5px 10px",
        background: "rgba(0,0,0,0.25)", color: selected ? "#fff" : C.text, fontSize: "13px", fontWeight: "600",
        fontFamily: "inherit", userSelect: "none",
    });
    head.setAttribute("role", "button");
    head.tabIndex = 0;
    head.setAttribute("aria-expanded", String(!collapsed));
    head.title = `${collapsed ? "Expand" : "Collapse"} ${clip.label || `prompt_${String(orderIndex).padStart(2, "0")}`}; select this shot too`;
    stopCanvasPointerEvents(head);
    const toggleClip = (event) => {
        event.stopPropagation();
        viewer.__aCollapsed = viewer.__aCollapsed || {};
        viewer.__aCollapsed[orderIndex] = !collapsed;
        setSelected(viewer, orderIndex);
        viewer.__aLastH = -1;
        viewer.__aRender?.();
    };
    head.addEventListener("click", toggleClip);
    head.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            toggleClip(event);
        }
        event.stopPropagation();
    });
    const arrow = el("span", { color: "#b9d5ff", width: "16px", flexShrink: "0", textAlign: "center" });
    arrow.textContent = collapsed ? "▸" : "▾";
    const title = el("span", { flex: "1", minWidth: "0", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" });
    title.textContent = clip.label || `===== prompt_${String(orderIndex).padStart(2, "0")} =====`;
    const duration = el("span", { color: clip.overLimit ? "#ff7070" : C.sub, fontWeight: "400", fontSize: "12px", whiteSpace: "nowrap", pointerEvents: "none" });
    duration.textContent = clip.sec.toFixed(3) + "s  ·  " + clip.frames + " frames" + (clip.overLimit ? "  ·  over 15s limit" : "");
    head.append(arrow, title, duration);
    card.appendChild(head);

    if (!collapsed) {
        const bodyH = cardBodyHeight(viewer);
        const body = el("div", {
            height: bodyH + "px", maxHeight: bodyH + "px", minHeight: "0", flex: "0 0 " + bodyH + "px", boxSizing: "border-box",
            display: "grid", gridTemplateColumns: "160px minmax(0, 1fr)", gap: "0", padding: "8px",
            background: "#191a1e", borderTop: "1px solid #333", overflow: "hidden",
        });
        const assets = el("div", {
            minWidth: "0", minHeight: "0", height: "100%", overflowY: "auto", overflowX: "hidden", overscrollBehavior: "contain",
            padding: "0 8px 0 0", borderRight: "1px solid #333", boxSizing: "border-box",
        });
        stopCanvasPointerEvents(assets);
        renderReferencedAssets(assets, clip.assets || [], library);
        const prompt = el("div", {
            minWidth: "0", minHeight: "0", height: "100%", overflowY: "auto", overflowX: "hidden", overscrollBehavior: "contain",
            padding: "0 8px 0 10px", color: C.text, fontSize: "12px", lineHeight: "1.65",
            whiteSpace: "pre-wrap", overflowWrap: "anywhere", boxSizing: "border-box",
        });
        stopCanvasPointerEvents(prompt);
        renderRichPrompt(prompt, clip.text, library);
        body.append(assets, prompt);
        card.appendChild(body);
    }
    return card;
}

function buildGlobalCard(globalText, library, viewer) {
    const collapsed = viewer.__aCollapsed && Object.prototype.hasOwnProperty.call(viewer.__aCollapsed, GLOBAL_CARD_KEY)
        ? !!viewer.__aCollapsed[GLOBAL_CARD_KEY]
        : false; // 全局提示词默认展开
    const card = el("div", {
        boxSizing: "border-box", width: "calc(100% - 16px)", margin: "4px 8px 8px",
        display: "flex", flex: "0 0 auto", flexDirection: "column", background: "#1e2420",
        border: "1px solid #4d6b4f", borderRadius: "7px", overflow: "hidden",
        fontFamily: "sans-serif", boxShadow: "0 0 6px rgba(96,180,110,0.22)",
    });
    const head = el("div", {
        width: "100%", height: "36px", minHeight: "36px", flex: "0 0 36px", boxSizing: "border-box",
        border: "0", textAlign: "left", cursor: "pointer", display: "flex", alignItems: "center", gap: "8px", padding: "5px 10px",
        background: "rgba(0,0,0,0.28)", color: "#e6f5e8", fontSize: "13px", fontWeight: "600",
        fontFamily: "inherit", userSelect: "none",
    });
    head.setAttribute("role", "button");
    head.tabIndex = 0;
    head.setAttribute("aria-expanded", String(!collapsed));
    head.title = `${collapsed ? "Expand" : "Collapse"} global prompt (film-wide rules, not part of shot selection)`;
    stopCanvasPointerEvents(head);
    const toggle = (event) => {
        event.stopPropagation();
        viewer.__aCollapsed = viewer.__aCollapsed || {};
        viewer.__aCollapsed[GLOBAL_CARD_KEY] = !collapsed;
        viewer.__aLastH = -1;
        viewer.__aRender?.();
    };
    head.addEventListener("click", toggle);
    head.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); toggle(event); }
        event.stopPropagation();
    });
    const arrow = el("span", { color: "#a8d9b0", width: "16px", flexShrink: "0", textAlign: "center" });
    arrow.textContent = collapsed ? "▸" : "▾";
    const title = el("span", { flex: "1", minWidth: "0", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" });
    title.textContent = "Global prompt · overall style / unified camera / shot-size strategy / character roster / props roster / vocal distribution";
    const tag = el("span", { color: "#8ecf98", fontWeight: "400", fontSize: "11px", whiteSpace: "nowrap", pointerEvents: "none" });
    tag.textContent = "Film-wide";
    head.append(arrow, title, tag);
    card.appendChild(head);

    if (!collapsed) {
        const bodyH = cardBodyHeight(viewer);
        const body = el("div", {
            height: bodyH + "px", maxHeight: bodyH + "px", minHeight: "0", flex: "0 0 " + bodyH + "px", boxSizing: "border-box",
            display: "grid", gridTemplateColumns: "160px minmax(0, 1fr)", gap: "0", padding: "8px",
            background: "#161a17", borderTop: "1px solid #3a4a3c", overflow: "hidden",
        });
        const assets = el("div", {
            minWidth: "0", minHeight: "0", height: "100%", overflowY: "auto", overflowX: "hidden", overscrollBehavior: "contain",
            padding: "0 8px 0 0", borderRight: "1px solid #3a4a3c", boxSizing: "border-box",
        });
        stopCanvasPointerEvents(assets);
        renderReferencedAssets(assets, collectReferences(globalText), library);
        const prompt = el("div", {
            minWidth: "0", minHeight: "0", height: "100%", overflowY: "auto", overflowX: "hidden", overscrollBehavior: "contain",
            padding: "0 8px 0 10px", color: C.text, fontSize: "12px", lineHeight: "1.65",
            whiteSpace: "pre-wrap", overflowWrap: "anywhere", boxSizing: "border-box",
        });
        stopCanvasPointerEvents(prompt);
        renderRichPrompt(prompt, globalText, library);
        body.append(assets, prompt);
        card.appendChild(body);
    }
    return card;
}

function renderBoard(viewer) {
    const root = viewer.__aRoot;
    if (!root) return;
    const previousScrollTop = root.scrollTop;
    root.replaceChildren();

    const text = readPromptSourceText(viewer);
    const library = readAssetLibrary(viewer);
    const packs = findPackNodes(viewer);
    const selectedNode = packs[0];
    const durationWidget = selectedNode?.widgets?.find((w) => w.name === "video_duration_sec");
    const lengthWidget = selectedNode?.widgets?.find((w) => w.name === "length" || w.name === "fallback_length_frames");
    const markerTemplate = readConnectedString(viewer, "segment_marker", DEFAULT_SEGMENT_MARKER);
    const parsed = parseStoryboard(text, Number(durationWidget?.value || 0), Number(lengthWidget?.value || 124), markerTemplate);
    const clips = parsed?.clips || [];
    const bar = el("div", {
        position: "sticky", top: "0", zIndex: "2", flex: "0 0 auto", boxSizing: "border-box", width: "calc(100% - 16px)",
        margin: "6px 8px 3px", padding: "5px 9px", display: "flex", justifyContent: "space-between",
        alignItems: "center", gap: "8px", borderRadius: "5px", background: "#24262c", color: C.text, fontSize: "11px",
    });

    if (!clips.length) {
        const tip = el("span", { color: "#e0a050" });
        tip.textContent = text ? "⚠ " + (parsed?.error || "Invalid prompt format.") : "⚠ Connect the full prompt; marker example: ===== prompt_01 =====";
        bar.appendChild(tip);
        root.appendChild(bar);
    } else {
        viewer.__aCollapsed = viewer.__aCollapsed || {};
        clips.forEach((_, index) => {
            const key = index + 1;
            if (!Object.prototype.hasOwnProperty.call(viewer.__aCollapsed, key)) viewer.__aCollapsed[key] = true;
        });

        const total = el("span", { whiteSpace: "nowrap", color: C.sub });
        const totalSeconds = clips.reduce((sum, clip) => sum + (Number.isFinite(clip.sec) ? clip.sec : 0), 0);
        const globalText = parsed?.globalText || "";
        total.textContent = `${clips.length} shot prompt(s) · ${totalSeconds.toFixed(2)}s total`
            + (globalText ? " · 1 global prompt segment" : "")
            + (parsed?.legacy ? " · [Shot N] legacy format" : "");
        const button = el("button", {
            padding: "5px 10px", border: "1px solid #45484f", borderRadius: "4px", cursor: "pointer",
            background: "#2a2c33", color: "#c9d7ea", fontSize: "11px", whiteSpace: "nowrap",
        });
        button.type = "button";
        const boardOpen = getBoardOpen(viewer);
        button.textContent = boardOpen ? "Hide board" : "Show board";
        button.title = boardOpen ? "Hide all shot cards" : "Show all shot cards";
        stopCanvasPointerEvents(button);
        button.addEventListener("click", (event) => {
            event.stopPropagation();
            setBoardOpen(viewer, !getBoardOpen(viewer));
            viewer.__aRender?.();
        });
        // 一键展开 / 折叠全部分镜
        const allOpen = clips.every((_, index) => !viewer.__aCollapsed[index + 1]);
        const btnAll = el("button", {
            padding: "5px 10px", border: "1px solid #45484f", borderRadius: "4px", cursor: "pointer",
            background: "#2a2c33", color: "#c9d7ea", fontSize: "11px", whiteSpace: "nowrap",
        });
        btnAll.type = "button";
        btnAll.textContent = allOpen ? "Collapse all" : "Expand all";
        btnAll.title = allOpen ? "Collapse all shot prompts" : "Expand all shot prompts";
        stopCanvasPointerEvents(btnAll);
        btnAll.addEventListener("click", (event) => {
            event.stopPropagation();
            clips.forEach((_, index) => { viewer.__aCollapsed[index + 1] = allOpen; });
            viewer.__aLastH = -1;
            viewer.__aRender?.();
        });
        const rightBox = el("div", { display: "flex", alignItems: "center", gap: "6px", flexShrink: "0" });
        rightBox.append(btnAll, button);
        bar.append(total, rightBox);
        root.appendChild(bar);
        if (boardOpen) {
            const selectedIndex = getSelected(viewer);
            if (globalText) root.appendChild(buildGlobalCard(globalText, library, viewer));
            clips.forEach((clip, index) => root.appendChild(buildClipCard(clip, index + 1, index + 1 === selectedIndex, library, viewer)));
        }
    }

    root.scrollTop = previousScrollTop;
}

function renderPackStatus(node) {
    const root = node.__aRoot;
    if (!root) return;
    root.innerHTML = "";
    const text = readPromptSourceText(node);
    const durationWidget = node.widgets?.find((w) => w.name === "video_duration_sec");
    const lengthWidget = node.widgets?.find((w) => w.name === "length" || w.name === "fallback_length_frames");
    const markerTemplate = readConnectedString(node, "segment_marker", DEFAULT_SEGMENT_MARKER);
    const parsed = parseStoryboard(text, Number(durationWidget?.value || 0), Number(lengthWidget?.value || 124), markerTemplate);
    const n = parsed?.clips.length || 0;
    const line = el("div", {
        boxSizing: "border-box", width: "calc(100% - 16px)", margin: "2px 8px",
        padding: "4px 9px", fontSize: "11px", borderRadius: "4px",
        background: "rgba(255,255,255,0.04)", color: C.text,
    });
    if (!n) {
        line.style.color = "#e0a050";
        line.textContent = text ? `⚠ ${parsed?.error || "Invalid prompt format."}` : "⚠ Full official prompt not connected";
    } else {
        const idx = getClipIndex(node);
        const outOfRange = idx > n;
        const currentLabel = parsed.clips[idx - 1]?.label || `===== prompt_${String(idx).padStart(2, "0")} =====`;
        line.textContent = `${n} shot prompt(s) · current ${currentLabel} (index ${idx})` + (outOfRange ? ` (out of range 1~${n})` : "");
        if (outOfRange) line.style.color = "#ff8080";
    }
    root.appendChild(line);
    requestAnimationFrame(() => syncHeight(node, root));
}

function bindViewer(viewer, isNew) {
    if (viewer.__aBound) return;
    viewer.__aBound = true;
    viewer.__aLastH = -1;

    // 新建节点给一个适合两列网格的初始宽度；加载已有工作流时保留保存宽度
    if (isNew) {
        try {
            const w = viewer.size?.[0] || 0;
            if (w < 600) viewer.size = [600, viewer.size?.[1] || 200];
        } catch (e) {}
    }

    const root = el("div", {
        width: "100%", height: "100%", minHeight: "0", boxSizing: "border-box", padding: "2px 0",
        display: "flex", flexDirection: "column", overflowY: "auto", overflowX: "hidden", colorScheme: "dark",
    });
    viewer.__aRoot = root;
    viewer.__aRender = () => renderBoard(viewer);

    // 隐藏原生 expand 勾选框，开关由看板顶部按钮控制
    setTimeout(() => hideWidget(viewer.widgets?.find((x) => x.name === "expand")), 0);

    // 看板高度跟随节点高度：拖大变大、拖小变小，不再固定 520px 留下一片黑底
    viewer.addDOMWidget(BOARD_WIDGET, "storyboard_board", root, {
        serialize: false,
        hideOnZoom: false,
        getMinHeight: () => BOARD_MIN_HEIGHT,
        getHeight: () => (getBoardOpen(viewer) ? boardHeight(viewer) : 30),
    });

    // 节点被拖动尺寸时，立刻按新高度重排列（重绘 + 防抖重建卡片，让正文高度跟着变）
    const origOnResize = viewer.onResize;
    viewer.onResize = function (...args) {
        const r = typeof origOnResize === "function" ? origOnResize.apply(this, args) : undefined;
        try { this.setDirtyCanvas?.(true, true); } catch (e) {}
        try {
            clearTimeout(this.__aResizeTimer);
            this.__aResizeTimer = setTimeout(() => renderBoard(this), 180);
        } catch (e) {}
        return r;
    };

    // Let ComfyUI finish restoring the saved node size, then grow to the fixed widget height once.
    setTimeout(() => {
        hideWidget(viewer.widgets?.find((x) => x.name === "expand"));
        ensureViewerNodeSize(viewer);
        renderBoard(viewer);
    }, 250);

    let lastHash = "";
    setInterval(() => {
        try {
            const text = readPromptSourceText(viewer) || "";
            const lib = readAssetLibrary(viewer);
            const selector = findPackNodes(viewer)[0];
            const duration = selector?.widgets?.find((w) => w.name === "video_duration_sec")?.value || 0;
            const fallback = selector?.widgets?.find((w) => w.name === "length" || w.name === "fallback_length_frames")?.value || 124;
            const markerTemplate = readConnectedString(viewer, "segment_marker", DEFAULT_SEGMENT_MARKER);
            const markerCount = [...text.matchAll(makeMarkerRegex(markerTemplate).regex)].length;
            const libHash = lib ? (lib.images.join("|") + "##" + lib.videos.join("|") + "##" + lib.audios.join("|")) : "";
            const hash = [
                text.length, text.slice(0, 200), markerTemplate, markerCount,
                libHash, duration, fallback, getBoardOpen(viewer), getSelected(viewer),
            ].join(":");
            if (hash !== lastHash) { lastHash = hash; viewer.__aLastH = -1; renderBoard(viewer); }
        } catch (e) {}
    }, 800);

    const origOnConfigure = viewer.onConfigure;
    viewer.onConfigure = function (...args) {
        const r = typeof origOnConfigure === "function" ? origOnConfigure.apply(this, args) : undefined;
        setTimeout(() => {
            hideWidget(viewer.widgets?.find((x) => x.name === "expand"));
            ensureViewerNodeSize(viewer);
            renderBoard(viewer);
        }, 350);
        return r;
    };
}

function bindPack(node) {
    if (node.__aBound) return;
    node.__aBound = true;
    node.__aLastH = -1;

    const root = el("div", {
        width: "100%", boxSizing: "border-box", padding: "2px 0",
        display: "flex", flexDirection: "column", colorScheme: "dark",
    });
    node.__aRoot = root;
    node.addDOMWidget(STATUS_WIDGET, "pack_status", root, {
        serialize: false,
        hideOnZoom: false,
        getMinHeight: () => {
            const h = root.scrollHeight;
            return h > 10 ? h : 26;
        },
        getHeight: () => {
            const h = root.scrollHeight;
            return h > 10 ? h + 4 : 26;
        },
    });

    setTimeout(() => renderPackStatus(node), 200);
    let lastHash = "";
    setInterval(() => {
        try {
            const text = readPromptSourceText(node) || "";
            const markerTemplate = readConnectedString(node, "segment_marker", DEFAULT_SEGMENT_MARKER);
            const markerCount = [...text.matchAll(makeMarkerRegex(markerTemplate).regex)].length;
            const hash = text.length + ":" + text.slice(0, 200) + ":" + markerTemplate + ":" + markerCount + ":" + getClipIndex(node);
            if (hash !== lastHash) { lastHash = hash; node.__aLastH = -1; renderPackStatus(node); }
        } catch (e) {}
    }, 800);

    const origOnConfigure = node.onConfigure;
    node.onConfigure = function (...args) {
        const r = typeof origOnConfigure === "function" ? origOnConfigure.apply(this, args) : undefined;
        setTimeout(() => renderPackStatus(node), 300);
        return r;
    };
}

app.registerExtension({
    name: "A.MiniMaxH3StoryboardRefVideo",
    nodeCreated(node) {
        if (node.comfyClass === VIEWER_TYPE) bindViewer(node, true);
        else if (node.comfyClass === PACK_TYPE || node.comfyClass === SEGMENT_TYPE) bindPack(node);
    },
    loadedGraphNode(node) {
        if (node.comfyClass === VIEWER_TYPE) bindViewer(node, false);
        else if (node.comfyClass === PACK_TYPE || node.comfyClass === SEGMENT_TYPE) bindPack(node);
    },
});

