import { app } from "../../scripts/app.js";
// extender.js v2.4.0 — cache-bust marker (2026-08-22-clean-break-from-original)
import { api } from "../../scripts/api.js";

// v14.113: restore_cache 全局守卫已移除（安全回退）。
// 背景：restore_cache 是 1.55 新式 toggle widget（optional），computeSize 归零
// 在真实 Chrome 无痕窗口无效（行仍显示），v14.107-112 的 DOM 级兜底（轮询/
// MutationObserver/CSS 注入）在部分环境引发画布白屏（隐藏动作影响布局）。
// 两害相权：白屏（画布不可用）> restore_cache 参数行显示（可接受、可点击）。
// 本版彻底移除全部守卫与 CSS 注入，只保留 v14.105 的 computeSize 归零
// （无副作用的隐藏尝试）——restore_cache 行在支持的环境隐藏、在 1.55
// toggle 环境正常显示；快捷条「恢复缓存」按钮照常可用（功能不受影响）。
// 只操作 DOM，不动 widget 数组 → 零 NaN、零重连、旧版工作流加载正常。
// v14.113: restore_cache 全局守卫已移除（安全回退）。
// 背景：restore_cache 是 1.55 新式 toggle widget（optional），computeSize 归零
// 在真实 Chrome 无痕窗口无效（行仍显示），v14.107-112 的 DOM 级兜底（轮询/
// MutationObserver/CSS 注入）在部分环境引发画布白屏（隐藏动作影响布局）。
// 两害相权：白屏（画布不可用）> restore_cache 参数行显示（可接受、可点击）。
// 本版彻底移除全部守卫与 CSS 注入，只保留 v14.105 的 computeSize 归零
// （无副作用的隐藏尝试）——restore_cache 行在支持的环境隐藏、在 1.55
// toggle 环境正常显示；快捷条「恢复缓存」按钮照常可用（功能不受影响）。
// 只操作 DOM，不动 widget 数组 → 零 NaN、零重连、旧版工作流加载正常。

// v2.40: 电影提示词模板库 (内嵌)
window.H3_FILM_TEMPLATES = {
  version: "1.0.0",
  categories: [
    {
      id: "camera",
      name: "Cinematography",
      name_en: "Camera Movement",
      icon: "🎥",
      templates: [
        { id: "cam_push_in", name: "Slow Push-in", prompt: "【电影运镜·缓推】镜头缓慢向前推进，从全景逐渐聚焦到主体面部，营造紧张感与亲密感，焦点逐渐收紧，背景逐渐虚化。" },
        { id: "cam_pull_back", name: "Pull Back", prompt: "【电影运镜·拉远】镜头缓慢向后拉远，从主体特写逐渐展现全景环境，营造孤独感与宏大叙事感，画面信息逐渐丰富。" },
        { id: "cam_pan_left", name: "Pan Left", prompt: "【电影运镜·左摇】镜头从右向左水平摇动，流畅自然地扫过场景，引导观众视线跟随主体移动，营造探索感。" },
        { id: "cam_pan_right", name: "Pan Right", prompt: "【电影运镜·右摇】镜头从左向右水平摇动，流畅自然地扫过场景，引导观众视线跟随主体移动，营造追踪感。" },
        { id: "cam_tilt_up", name: "Tilt Up", prompt: "【电影运镜·上摇】镜头从下向上垂直摇动，从脚部/地面逐渐摇到面部/天空，营造崇高感与仰视的压迫感。" },
        { id: "cam_tilt_down", name: "Tilt Down", prompt: "【电影运镜·下摇】镜头从上向下垂直摇动，从面部/天空逐渐摇到脚部/地面，营造审视感与宿命感。" },
        { id: "cam_tracking", name: "Tracking Shot", prompt: "【电影运镜·跟拍】镜头平稳跟随主体移动，保持主体在画面中心，轻微手持晃动增加真实感与沉浸感，如同旁观者视角。" },
        { id: "cam_dolly", name: "Dolly Track", prompt: "【电影运镜·轨道推拉】镜头沿轨道平滑移动，背景呈现视差滚动效果，画面稳定流畅，如同专业电影级运镜。" },
        { id: "cam_crane", name: "Crane Shot", prompt: "【电影运镜·升降】镜头缓慢上升或下降，视角从平视逐渐变为俯视或仰视，营造史诗感与场面调度感。" },
        { id: "cam_orbit", name: "Orbit Shot", prompt: "【电影运镜·环绕】镜头围绕主体做360度或半圆弧线运动，多角度展现主体与环境关系，营造沉浸式展示感。" },
        { id: "cam_handheld", name: "Handheld", prompt: "【电影运镜·手持】镜头带有自然的手持晃动，节奏紧凑，营造纪实感与紧张感，如同现场实拍。" },
        { id: "cam_stedicam", name: "Steadicam", prompt: "【电影运镜·斯坦尼康】镜头平稳流畅，如同斯坦尼康拍摄，穿越复杂场景无卡顿，主体跟随自然，画面如丝般顺滑。" },
      ],
    },
    {
      id: "color",
      name: "Color Grading",
      name_en: "Color Grading",
      icon: "🎨",
      templates: [
        { id: "color_warm", name: "Warm Tone", prompt: "【电影调色·暖调】整体画面偏暖，金色与橙色为主色调，肤色温暖红润，阴影带棕褐色调，营造温馨怀旧的氛围。" },
        { id: "color_cool", name: "Cool Tone", prompt: "【电影调色·冷调】整体画面偏冷，蓝色与青色为主色调，肤色偏苍白，阴影带深蓝灰色调，营造清冷孤寂的氛围。" },
        { id: "color_teal_orange", name: "Teal & Orange", prompt: "【电影调色·青橙对比】经典好莱坞调色风格，阴影偏青蓝色，高光偏橙黄色，对比强烈，视觉冲击力强，商业大片质感。" },
        { id: "color_film_noir", name: "Black & White", prompt: "【电影调色·黑白电影】经典黑白电影质感，高对比度，深黑与纯白层次丰富，灰阶过渡自然，如同老胶片电影。" },
        { id: "color_pastel", name: "Pastel Macaron", prompt: "【电影调色·粉彩】低饱和度马卡龙色调，柔和粉嫩，色彩淡雅清新，营造梦幻甜美氛围，日系清新风格。" },
        { id: "color_high_contrast", name: "High Contrast", prompt: "【电影调色·高对比】高对比度调色，明暗反差强烈，暗部深邃，亮部通透，营造戏剧化与张力感。" },
        { id: "color_muted", name: "Muted Morandi", prompt: "【电影调色·莫兰迪】低饱和度莫兰迪色调，灰调柔和，色彩克制内敛，营造高级感与文艺片氛围。" },
        { id: "color_neon", name: "Neon Cyberpunk", prompt: "【电影调色·霓虹】赛博朋克风格，高饱和霓虹色，粉红与青蓝碰撞，夜间发光效果强烈，未来感十足。" },
        { id: "color_sepia", name: "Sepia Vintage", prompt: "【电影调色·棕褐】复古棕褐色调，如同老照片与老电影，泛黄怀旧，营造历史感与年代感。" },
        { id: "color_natural", name: "Natural Real", prompt: "【电影调色·自然】自然真实色彩，还原物体本色，肤色自然通透，光影写实，如同纪录片质感。" },
      ],
    },
    {
      id: "composition",
      name: "Composition",
      name_en: "Aspect / Composition",
      icon: "🎬",
      templates: [
        { id: "comp_widescreen", name: "Widescreen Cinematic", prompt: "【画面分割·宽屏】2.39:1 宽屏电影比例，上下黑色遮幅，经典电影画幅，营造史诗感与影院体验。" },
        { id: "comp_letterbox", name: "Letterbox", prompt: "【画面分割·黑边】上下适度黑色遮幅，营造电影感，同时保留足够垂直空间展示主体。" },
        { id: "comp_rule_thirds", name: "Rule of Thirds", prompt: "【画面分割·三分】经典三分法构图，主体位于画面三分之一线交点，视觉平衡稳定，电影感十足。" },
        { id: "comp_center", name: "Center Composition", prompt: "【画面分割·中心】主体居中对称构图，营造庄重感与仪式感，适合人物特写与正式场景。" },
        { id: "comp_leading", name: "Leading Lines", prompt: "【画面分割·引导线】利用环境元素形成引导线，视线自然汇聚到主体，画面有深度感与纵深感。" },
        { id: "comp_frame_in_frame", name: "Frame within Frame", prompt: "【画面分割·框中框】利用门窗、镜子等元素形成框中框构图，增加画面层次与视觉趣味性。" },
      ],
    },
    {
      id: "cinematic",
      name: "Cinematic Feel",
      name_en: "Cinematic Feel",
      icon: "✨",
      templates: [
        { id: "feel_cinematic", name: "Cinematic Quality", prompt: "【电影感·画质】电影级画质，8K超高清，细节丰富，光影层次细腻，景深自然，胶片颗粒感适中。" },
        { id: "feel_dramatic_light", name: "Dramatic Lighting", prompt: "【电影感·光影】戏剧化布光，伦勃朗光效，明暗对比强烈，光影层次丰富，营造戏剧张力与氛围。" },
        { id: "feel_soft_light", name: "Soft Light", prompt: "【电影感·柔光】柔和漫射光线，阴影边缘模糊，肤色细腻通透，营造温柔氛围与治愈感。" },
        { id: "feel_backlight", name: "Backlight Rim", prompt: "【电影感·逆光】逆光拍摄，主体边缘有金色轮廓光，背景过曝形成光晕，营造唯美感与梦幻感。" },
        { id: "feel_rainy", name: "Rainy Night", prompt: "【电影感·雨夜】雨夜场景，地面反射灯光，雨滴清晰可见，雾气弥漫，营造忧郁浪漫的氛围。" },
        { id: "feel_sunset", name: "Golden Hour", prompt: "【电影感·黄金时刻】日落黄金时刻光线，暖金色侧光，长投影，天空渐变色彩，营造温暖怀旧氛围。" },
        { id: "feel_night_neon", name: "Night Neon", prompt: "【电影感·夜景】夜晚都市场景，霓虹灯光闪烁，灯光散景效果，湿滑路面反射，赛博朋克氛围。" },
        { id: "feel_misty", name: "Misty Haze", prompt: "【电影感·雾气】雾气弥漫场景，远景朦胧模糊，空气透视明显，营造神秘氛围与诗意感。" },
        { id: "feel_tense", name: "Tense Suspense", prompt: "【电影感·紧张】低照度悬疑氛围，明暗对比强烈，阴影浓重，画面压抑，营造紧张与悬念感。" },
        { id: "feel_epic", name: "Epic Grand", prompt: "【电影感·史诗】史诗级宏大场面，广角镜头，开阔空间，人物渺小，营造历史感与命运感。" },
      ],
    },
  ],
};

// v2.07 (2026-09-19 fix): 全局 patch structuredClone,
// 如果克隆失败 (比如 properties 里有函数/DOM 节点),
// 自动降级到 JSON 深拷贝, 避免另存工作流时报错.
(function() {
    if (!window.structuredClone) return;
    const original = window.structuredClone;
    // v2.77 (2026-09-27): 失败告警节流 — 节点上挂着含 DOM 的 runtime,
    // ComfyUI 频繁克隆时每次都会失败, 原先每条都 console.warn 造成控制台
    // 999+ 条刷屏, 拖慢前端。现在每分钟最多告警 3 条, fallback 行为不变。
    let _cloneWarnCount = 0, _cloneWarnWindow = 0;
    window.structuredClone = function(value) {
        try {
            return original.call(window, value);
        } catch (e) {
            const now = Date.now();
            if (now - _cloneWarnWindow > 60000) { _cloneWarnWindow = now; _cloneWarnCount = 0; }
            if (_cloneWarnCount < 3) {
                _cloneWarnCount++;
                console.warn("[BSAI] structuredClone failed, fallback to JSON:", e.message);
            }
            try {
                // v2.79 (2026-09-27): fallback 序列化用 replacer 跳过 __h3* runtime
                // 字段和 DOM 节点, 大幅减少序列化体积与时间(原先会把含 DOM 的整个
                // runtime 序列化成大对象, 频繁克隆时拖慢主线程), 并避免循环引用失败。
                const _h3JsonReplacer = (k, v) => {
                    if (k.startsWith("__h3")) return undefined;
                    if (v && typeof v === "object" && typeof v.nodeType === "number") return undefined;
                    return v;
                };
                return JSON.parse(JSON.stringify(value, _h3JsonReplacer));
            } catch (e2) {
                console.error("[BSAI] JSON fallback also failed:", e2.message);
                return value;
            }
        }
    };
})();

const TARGET = "BSAIH3FilmFactory";
const ALL_TARGETS = new Set([TARGET, "BSAIMiniMaxH3Extender"]);
const FINAL_TARGET = "MiniMaxH3MotionContextDiskFinalDecode";
const BSAI_FINAL_TARGET = "BSAIH3FilmFactoryFinalDecode";
const ALL_FINAL_TARGETS = new Set([FINAL_TARGET, BSAI_FINAL_TARGET]);
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

// ── 工具栏按钮两行排版（中文上、英文下） ──
(function injectToolbarCSS() {
	if (window._bsaiToolbarCSSInjected) return;
	const style = document.createElement("style");
	style.id = "bsai-toolbar-btn-css";
	style.textContent = `
.bsai-tb-btn {
	font-size: 10px;
	line-height: 1.2;
	padding: 2px 6px;
	border-radius: 3px;
	cursor: pointer;
	font-weight: bold;
	display: inline-flex;
	flex-direction: column;
	align-items: center;
	gap: 0;
	white-space: nowrap;
}
.bsai-tb-btn .bsai-zh {
	font-size: 10px;
	line-height: 1.15;
}
.bsai-tb-btn .bsai-en {
	font-size: 8px;
	line-height: 1.1;
	opacity: 0.75;
	font-weight: normal;
}
`;
	document.head.appendChild(style);
	window._bsaiToolbarCSSInjected = true;
})();

function setBtnText(btn, zh, en, opts = {}) {
	if (!btn) return;
	const icon = opts.icon || "";
	const zhText = icon ? icon + " " + zh : zh;
	btn.innerHTML = "";
	const zhSpan = document.createElement("span");
	zhSpan.className = "bsai-zh";
	zhSpan.textContent = zhText;
	btn.appendChild(zhSpan);
	if (en) {
		const enSpan = document.createElement("span");
		enSpan.className = "bsai-en";
		enSpan.textContent = en;
		btn.appendChild(enSpan);
	}
	if (!btn.classList.contains("bsai-tb-btn")) {
		btn.classList.add("bsai-tb-btn");
	}
	// Merge existing inline styles with class styles
	const bg = opts.bg || btn.style.background || "";
	const border = opts.border || btn.style.borderColor || "";
	const color = opts.color || btn.style.color || "";
	btn.style.cssText = `font-size:10px;padding:2px 6px;background:${bg};border:1px solid ${border};border-radius:3px;color:${color};cursor:pointer;font-weight:bold;`;
}

const TOOLBAR_HEIGHT = 50;
const GLOBAL_PROMPT_MIN_HEIGHT = 200;
const BOTTOM_BAR_HEIGHT = 35;
const NON_CARD_FIXED = TOOLBAR_HEIGHT + GLOBAL_PROMPT_MIN_HEIGHT + BOTTOM_BAR_HEIGHT;
const COLLAPSED_CLIP_HEIGHT = 38;
const BASE_PADDING = BOTTOM_PAD + 20;
const COLLAPSED_MIN_HEIGHT = 160;
const PREVIEW_PANEL_WIDTH = 130;
const MAX_AUTO_NODE_HEIGHT = 8000;  // v2.03 (2026-09-19): 从 2000 提升到 8000, 解决 CLIP>12 个时节点高度被截断只剩 4 个卡片的问题. CLIP 列表容器已有 overflow-y:auto, 超出部分可内部滚动.
const MAX_CARDS_VISIBLE_HEIGHT = 3 * (CARD_MIN_HEIGHT + 9) + CARD_SCROLLBAR_SPACE;
// v2.105 (fix): 收起视口 = 1 张 CLIP 卡片(卡片最小高 355 + 滚动条预留 24 = 379)。
// 删除外部提示词后节点同步收回所有 CLIP、只留 CLIP1 时, 底部栏紧贴这张卡,
// 不再残留 3~4 卡的空白(原 5 卡基准 1820px 导致"距离只有 1 个 CLIP 还差 3 卡")。
const DEFAULT_COLLAPSED_VIEW_H = CARD_MIN_HEIGHT + CARD_SCROLLBAR_SPACE;
// v2.21 (2026-09-20 fix): 节点高度逻辑:
//   没输入外部提示词: 默认只显示 CLIP1 (最小值 = 1 个 CLIP)
//   输入外部提示词后: autoGrowNodeToFitAllClips 自动撑大到显示全部 CLIP
const DEFAULT_MAX_VISIBLE_CLIPS = 20;
const DEFAULT_MIN_VISIBLE_CLIPS = 1;

function calculateMinHeight(runtime) {
    if (!runtime?.state?.clips?.length) {
        return COLLAPSED_MIN_HEIGHT;
    }
    let height = NON_CARD_FIXED;
    let cardsHeight = 0;
    // v2.105 (fix): 最小高度 = 1 个 CLIP 的展开高度, 供 getMinHeight /
    // legacy minNodeH 兜底使用。展开态跟随全部 CLIP 由 autoGrowNodeToFitAllClips
    // 负责; 这里若返回全部 CLIP 高度, getMinHeight 会读到超大值把收起态底板
    // 重新撑开(刷新时"刚收回又自动脱离"), 并导致放大画布时节点超界消失。
    const clipsToCount = Math.min(runtime.state.clips.length, DEFAULT_MIN_VISIBLE_CLIPS);
    for (let i = 0; i < clipsToCount; i++) {
        const clip = runtime.state.clips[i];
        if (clip.collapsed) {
            cardsHeight += COLLAPSED_CLIP_HEIGHT;
        } else {
            cardsHeight += clip.card_height > 0
                ? Math.max(CARD_MIN_HEIGHT, clip.card_height)
                : CARD_MIN_HEIGHT + CARD_SCROLLBAR_SPACE;
        }
    }
    height += cardsHeight;
    return Math.max(COLLAPSED_MIN_HEIGHT, height + BASE_PADDING);
}

// v2.105 (fix): 收起态视口高度 = 第 1 张 CLIP 卡片的实际高度(不折叠时),
// 让"添加CLIP/删除CLIP"底部栏紧贴 CLIP1, 不再残留 3~4 卡空白。
// 卡片实际撑高(card_height)优先; 未知时用最小卡高 + 滚动条预留。
function collapsedViewportH(runtime) {
    const c0 = runtime && runtime.state && runtime.state.clips && runtime.state.clips[0];
    if (!c0) return COLLAPSED_MIN_HEIGHT;
    if (c0.collapsed) return COLLAPSED_CLIP_HEIGHT + CARD_SCROLLBAR_SPACE;
    const cardH = c0.card_height > 0 ? Math.max(CARD_MIN_HEIGHT, c0.card_height) : CARD_MIN_HEIGHT;
    return Math.max(COLLAPSED_MIN_HEIGHT, cardH + CARD_SCROLLBAR_SPACE);
}

// v2.108 (2026-09-29): 全局提示词区可见性统一裁决点。
// 历史问题: 收起 CLIP 分支(line 5050)无条件把 globalPromptSection 设 display:none,
// 用户反馈"收起状态全局提示词不见了"。现在改为: 全局提示词区的显隐只由
// 用户显式折叠标志 _h3GpUserCollapsed 决定, 与 CLIP 收起/展开完全解耦。
//   _h3GpUserCollapsed === false (默认) -> 始终显示 (CLIP 收起/展开都显示)
//   _h3GpUserCollapsed === true          -> 隐藏 (用户点了"▼ 展开全局提示词"折叠按钮)
function applyGlobalPromptVisibility(runtime) {
    if (!runtime) return;
    const hide = runtime._h3GpUserCollapsed === true;
    const disp = hide ? "none" : "flex";
    try {
        if (runtime.globalPromptSection) runtime.globalPromptSection.style.display = disp;
        // gpResizer 是拖动把手, 隐藏提示词区时也一起隐藏, 显示时恢复。
        if (runtime.gpResizer) runtime.gpResizer.style.display = hide ? "none" : "";
    } catch (e) {}
}

// v2.108: 全局提示词区的实际渲染高度。收起 CLIP 态下高度公式必须加上它,
// 否则提示词区内容被裁掉底板。拖拽高度优先, 其次 DOM 实测, 最后兜底 MIN。
function globalPromptSectionH(runtime) {
    const sec = runtime && runtime.globalPromptSection;
    if (!sec || sec.style.display === "none") return 0;
    let h = 0;
    try {
        if (typeof sec.getBoundingClientRect === "function") h = sec.getBoundingClientRect().height;
    } catch (e) {}
    if (!(h > 0)) h = Number(runtime?.state?.gpDragHeight) || 0;
    if (!(h > 0)) h = sec.offsetHeight || 0;
    // 拖动把手 7px + 上下各 1px margin
    return Math.round(Math.max(0, h) + 9);
}

// v2.109 (2026-09-29 fix): 收起态布局应用器 —— 三处调用点(onNodeCreated 同步收起、
// onConfigure 恢复收起、syncDomHeight legacy 收起分支)共用, 避免高度公式各自漂移。
//
// 回归背景: v2.108 改成"手工加总高度"后公式漏算了 globalPromptSection 的
// margin-bottom:6px、toolbar 的真实高度(按钮多时换行, 超过 TOOLBAR_HEIGHT=50 常量)
// 和 bottomBar 的真实高度。公式偏小 + root.style.overflow:hidden → 把最后一个子元素
// bottomBar 整条裁掉(用户看到收起态"CLIPS | 总时长"和添加/删除按钮消失)。
//
// 现在改成实测: cards 固定视口高 + flex:0 0 auto(不会被拉伸), root 置 height:auto,
// 强制一次 reflow 后读 scrollHeight —— 它等于真实内容全高, 不会漏项。
// v2.29 注释里的正反馈循环(节点高→cards 被拉高→测得更大→节点更高)在这里不成立,
// 因为收起态 cards 高度是写死的 px 且 flex 为 0 0 auto, 不参与拉伸。
// 取 max(实测, 兜底公式) 只可能偏大(toolbar 换行/提示词区变高), 不会偏小裁内容。
function applyCollapsedLayout(runtime, viewportH) {
    const _vh = Math.max(COLLAPSED_MIN_HEIGHT, Number(viewportH) || COLLAPSED_MIN_HEIGHT);
    if (!runtime) return _vh;
    applyGlobalPromptVisibility(runtime);
    if (!runtime.root) return _vh;
    runtime.root.style.height = "auto";
    runtime.root.style.overflow = "hidden";
    runtime.cards.style.height = `${_vh}px`;
    runtime.cards.style.overflowY = "auto";
    // 收起态 cards=0 0 auto(固定高度不拉伸)。之前 1 1 auto 在 flex-column root 里
    // 会拉伸填满 root, 把 bottomBar 推走。
    runtime.cards.style.flex = "0 0 auto";
    runtime.cards.style.minHeight = "";
    runtime.cards.style.maxHeight = "none";
    try { void runtime.root.offsetHeight; } catch (e) {}
    let measured = 0;
    try { measured = Math.round(runtime.root.scrollHeight) || 0; } catch (e) {}
    const padTop = parseInt(runtime.root.style.paddingTop || "5px") || 5;
    const fallback = padTop + TOOLBAR_HEIGHT + globalPromptSectionH(runtime) + _vh + BOTTOM_BAR_HEIGHT + 6;
    const contentH = Math.max(measured, fallback);
    runtime.root.style.height = `${contentH}px`;
    runtime.domHeight = contentH;
    return contentH;
}

// v2.111 (2026-09-30): 节点默认宽度下限 —— 保证工具栏里末尾的
// 「📂 展开CLIP / 📦 收起CLIP」按钮完整可见。
//
// 背景: toolbar 是 display:flex + 默认 flex-wrap:nowrap, 而 flex 子项默认
// flex-shrink:1。节点宽度不够时按钮不是"换行"而是被逐个压缩, 末尾的展开/收起
// 按钮(排在 pauseBar/status 之前)首当其冲被压扁甚至裁掉。
//
// 这里实测工具栏的"自然宽度"当宽度下限, 而不是拍一个魔数:
// 按钮文案增删、status 文本长短变化、字体/DPI 差异都会自动跟随。
// 量自然宽度必须先让子项不压缩 —— 直接读 scrollWidth 只会得到容器宽度
// (因为子项已被 shrink 压缩), 所以临时把 toolbar 设成 width:max-content
// 量完再还原。
const TOOLBAR_WIDTH_PADDING = 24; // root 左右内边距 + 一点余量
// v2.114: 工具栏末尾的 status 是"弹性留白"项(margin-left:auto + max-width:45% +
// text-overflow:ellipsis), 它按设计就是吸收剩余空间、放不下就省略号截断, 所以不
// 参与自然宽度求和 —— 否则一段长状态文案会把节点撑到几千像素。给它固定额度。
const TOOLBAR_STATUS_ALLOWANCE = 150;

// v2.114: 量工具栏"自然宽度" —— 逐个子元素临时解除 flex 压缩后求和。
//
// 为什么不能用 tb.offsetWidth / tb.scrollWidth:
//   flex 子项默认 flex-shrink:1, 容器窄的时候子项会被压缩(按钮文案折行成
//   两行), 此时量到的 offsetWidth/scrollWidth 都等于"被压缩后的容器宽度",
//   永远量不出真实需求, 于是 required 算出来偏小甚至等于当前宽度 → 不加宽 →
//   死循环。对整个容器取 max-content 也不可靠: status 这类弹性项在 max-content
//   下仍会参与压缩, 结果依赖容器当前宽度, 是个循环依赖。
//
// 可靠做法: 逐个把"固定尺寸"子元素设成 flex:0 0 auto + width:max-content,
// 让每个都按自身内容撑开, 连同 gap 求和; 弹性留白项(status)跳过, 改用固定额度。
// 判定弹性项: 显式 margin-left:auto, 或 max-width 是 <100% 的百分比。
function measureToolbarNaturalWidth(tb) {
    if (!tb) return 0;
    const children = Array.prototype.slice.call(tb.children || []);
    const saved = [];
    let sum = 0;
    let sawFlexible = false;
    try {
        for (let i = 0; i < children.length; i++) {
            const el = children[i];
            let flexible = !!(el.style && el.style.marginLeft === "auto");
            if (!flexible) {
                let mw = "";
                try { mw = getComputedStyle(el).maxWidth || ""; } catch (e2) { mw = ""; }
                if (/^\d+(\.\d+)?%$/.test(mw) && parseFloat(mw) < 100) flexible = true;
            }
            if (flexible) { sawFlexible = true; continue; }
            saved.push({
                el,
                flex: el.style.flex,
                width: el.style.width,
                minWidth: el.style.minWidth,
            });
            el.style.flex = "0 0 auto";
            el.style.width = "max-content";
            el.style.minWidth = "0";
        }
        // 强制一次 reflow, 让 max-content 生效后再量。
        void tb.offsetWidth;
        const gap = parseFloat(getComputedStyle(tb).gap) || 0;
        let counted = 0;
        for (let i = 0; i < saved.length; i++) {
            const w = saved[i].el.offsetWidth || 0;
            if (w > 0) { sum += w; counted++; }
        }
        // gap 只按"参与求和的子元素个数"折算, 免得被跳过的弹性项把间距算多/算少。
        if (counted > 1) sum += gap * (counted - 1);
        if (sawFlexible) sum += TOOLBAR_STATUS_ALLOWANCE;
    } catch (e) {
        sum = 0;
    } finally {
        for (let i = 0; i < saved.length; i++) {
            const s = saved[i];
            s.el.style.flex = s.flex;
            s.el.style.width = s.width;
            s.el.style.minWidth = s.minWidth;
        }
    }
    return Math.ceil(sum);
}

// 返回 true = 这次成功量到了有效自然宽度(不论是否需要加宽), 调用方可以收手。
function ensureToolbarWidth(node, runtime) {
    try {
        const tb = runtime && runtime.toolbar;
        // 注意: 不用 isConnected 早退。DOM widget 由 ComfyUI 在绘制时才挂进
        // document, onNodeCreated / onConfigure 早期调用时通常还没连接, 早退会让
        // 宽度修正永远不生效。未连接时 offsetWidth 为 0, 下面 `natural > 0` 自然跳过。
        if (!tb) return false;
        const natural = measureToolbarNaturalWidth(tb);
        if (!(natural > 0)) return false;
        const required = natural + TOOLBAR_WIDTH_PADDING;
        const cur = Number(node.size && node.size[0]) || 0;
        if (cur < required) {
            // 只加宽, 不缩窄 —— 用户手动拉宽的宽度要保留。
            node.size = [required, Number(node.size && node.size[1]) || 0];
            try { node.graph && node.graph.setDirtyCanvas(true, true); } catch (e) {}
        }
        return true;
    } catch (e) {}
    return false;
}

// v2.112: 宽度修正的重试调度。
// 单次调用常常量不到值(DOM 尚未挂载 / 按钮文案还没填 / counter 还没渲染),
// 所以在几个时间点各试一次 —— 每次都重新实测, 量到就加宽。
// 工具栏里的 counter("总时长 15s (1 clip)") 和 pauseBar 按钮的显示状态
// 都会在渲染过程中变化, 后面的重试点覆盖这些变化。
function scheduleToolbarWidthFix(node, runtime) {
    // v2.114: 加"量到即收手"闩锁。
    //
    // 为什么必须有: ResizeObserver 是长驻监听, 节点被用户手动拉窄时它会立刻
    // 再次触发并把宽度顶回去, 变成跟用户抢拖拽把手。而反复重试也只是在重复
    // 做同一件事。默认宽度是"落地态"需求, 量到一次就够, 之后把控制权完全交回用户。
    // 未挂载 / 量不到(返回 false)时不收手, 继续等下一个时间点。
    const st = { done: false };
    const stop = () => {
        if (st.done) return;
        st.done = true;
        try {
            if (runtime && runtime._toolbarWidthRO) {
                runtime._toolbarWidthRO.disconnect();
                runtime._toolbarWidthRO = null;
            }
        } catch (e) {}
    };
    const run = () => {
        if (st.done) return;
        try {
            // 每次重试前先把展开态布局摆好, 让 toolbar 拿到真实尺寸。
            if (runtime && runtime.root && runtime.root.style) {
                runtime.root.style.width = "";
            }
            if (ensureToolbarWidth(node, runtime)) stop();
        } catch (e) {}
    };
    const delays = [0, 120, 400, 900, 1800, 3200, 6000, 10000];
    for (let i = 0; i < delays.length; i++) {
        const d = delays[i];
        if (d === 0) requestAnimationFrame(run);
        else setTimeout(run, d);
    }
    // 挂载后兜底: ComfyUI 首次绘制 DOM widget 的时机不确定(画布缩放/节点在
    // 视口外/后台 tab 时可能更晚), 固定几个时间点可能全部落空; ResizeObserver
    // 在工具栏真正参与布局的那一刻必然触发一次, 那里再补一次测量。
    // 先建 RO 再排定时器, 免得 d=0 那轮先收手、RO 才建起来又一直挂着。
    try {
        const tb = runtime && runtime.toolbar;
        if (tb && typeof ResizeObserver === "function" && !runtime._toolbarWidthRO) {
            let pending = false;
            const ro = new ResizeObserver(() => {
                if (st.done || pending) return;
                pending = true;
                // 合并同一帧的多次触发, 避免连续改 size 造成抖动。
                requestAnimationFrame(() => {
                    pending = false;
                    run();
                });
            });
            ro.observe(tb);
            runtime._toolbarWidthRO = ro;
        }
    } catch (e) {}
}

// v2.12: 按剧本分镜自动建完 CLIP 后, 把节点自动撑高能显示全部 CLIP 卡片.
// 只撑大不缩小, 不破坏用户手动拉大; 用 _userResize 标记防止 poisoned 守卫弹回.
// v2.13: 双 rAF + 小延迟等展开卡片 textarea 真正排完再量; 不手动调 syncDomHeight(setSize 会触发 afterResize);
//        500ms 后再校验一次, 若高度被压回则重设, 防止时序竞争.
function autoGrowNodeToFitAllClips(node, runtime) {
    try {
        if (!runtime?.state?.clips) return;
        // v2.84: 收起状态下不自动撑大(只显示 CLIP1 视口, 滚动条查看全部)
        if (runtime._h3CollapsedAll) return;
        // v2.29 (2026-09-20 fix): 不测量 DOM (cards.scrollHeight 会形成循环:
        // 节点高度大 → cards 高度被强制撑大 → 测到很大值 → 节点撑得更大).
        // 直接根据 CLIP 数量计算高度:
        // - 输入外部提示词后 CLIP 变多 → 自动撑大到显示全部 CLIP
        // - 删除外部提示词后 CLIP 变少 → 自动缩小, 不留黑色空白
        if (runtime._growInFlight) return;
        runtime._growInFlight = true;
        const applyGrow = () => {
            try {
                const clips = runtime.state.clips;
                if (!clips || clips.length === 0) {
                    // 没有 CLIP: 用最小高度
                    const y = Number(runtime.domWidget && runtime.domWidget.last_y) || 0;
                    const target = y + COLLAPSED_MIN_HEIGHT + BOTTOM_PAD;
                    const w = Math.max(NODE_MIN_WIDTH, Number(node.size && node.size[0]) || NODE_MIN_WIDTH);
                    const cur = Number(node.size && node.size[1]) || 0;
                    runtime._userResize = true;
                    if (Math.abs(target - cur) > 4) {
                        node.setSize([w, target]);
                    }
                    runtime.state.nodeHeight = target;
                    return;
                }
                // 根据每个 CLIP 的实际 card_height 计算总高度
                let totalCardH = 0;
                // v2.83: 只按已渲染的 CLIP 数计算高度(收起=1, 展开=全部),
                // 避免收起状态下 autoGrow 又把节点撑到全部 CLIP 高度。
                const _growN = Math.min(clips.length, Number(runtime._renderedClips) || clips.length);
                for (let i = 0; i < _growN; i++) {
                    const clip = clips[i];
                    if (clip.collapsed) {
                        totalCardH += COLLAPSED_CLIP_HEIGHT;
                    } else if (clip.card_height > 0) {
                        totalCardH += Math.max(CARD_MIN_HEIGHT, clip.card_height);
                    } else {
                        totalCardH += CARD_MIN_HEIGHT + CARD_SCROLLBAR_SPACE;
                    }
                }
                const y = Number(runtime.domWidget && runtime.domWidget.last_y) || 0;
                // v2.98c: 展开时用 DOM 实测内容高(卡片 textbox 实际撑高 ~457px/张)
                // 放大估算值 - 只按 355px/张估算会把 node 撑得比实际内容矮,
                // 31 卡内容溢出到底板外(v2.29 注释的循环场景是卡片被 flex 拉伸;
                // 本实现卡片 flex 0 0 auto 高度独立于容器, scrollHeight 稳定不循环)。
                if (!runtime._h3CollapsedAll && runtime.cards && runtime.cards.scrollHeight > 0) {
                    totalCardH = Math.max(totalCardH, runtime.cards.scrollHeight);
                }
                const needed = y + NON_CARD_FIXED + totalCardH + BASE_PADDING;
                const target = Math.min(40000, needed);
                const w = Math.max(NODE_MIN_WIDTH, Number(node.size && node.size[0]) || NODE_MIN_WIDTH);
                const cur = Number(node.size && node.size[1]) || 0;
                runtime._userResize = true; // 防止 poisoned-height 守卫把新高度弹回
                if (Math.abs(target - cur) > 4) {
                    // v2.98: 直接改 size 数组(不走 setSize) - setSize 触发 getHeight
                    // 读 runtime.domHeight(旧收起值), 会把展开撑高覆盖回旧高度,
                    // 导致"底板只有 1 卡高、卡片内容溢出显示"。展开/收起统一用
                    // 直接写数组 + 同步 domHeight, 与 v2.97 收起固定同策略。
                    node.size = [w, target];
                    node.graph?.setDirtyCanvas(true, true);
                    runtime.domHeight = Math.max(COLLAPSED_MIN_HEIGHT, target - NON_CARD_FIXED);
                    // v2.98b: 直接写数组不会触发 afterResize/setSize, root/cards
                    // 不会跟随 node.size 更新(残留收起 700px 视口)。这里手动同步
                    // DOM 高度, 让展开后 root/cards 跟随撑高, 31 卡全部显示。
                    syncDomHeight(node, runtime, false);
                }
                runtime.state.nodeHeight = target;
                try { updateHidden(node, runtime); } catch (e) {}
            } catch (e) {}
        };
        // 等 CLIP 卡片 DOM 更新完后再计算; 跑完放开在途标记
        requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(() => {
            try { applyGrow(); } catch (e) {}
            runtime._growInFlight = false;
        }, 200)));
        // v2.98: 兜底 - 页面繁忙/节能时 rAF 链可能长时间不触发, _growInFlight
        // 卡死导致后续 autoGrow 全部 return, 展开撑高永远失败。800ms 后若
        // 仍未执行则强制同步执行一次并复位在途标记。
        setTimeout(() => {
            if (runtime._growInFlight) {
                try { applyGrow(); } catch (e) {}
                runtime._growInFlight = false;
            }
        }, 800);
        // v2.98d: 二次校验 - 分片渲染 31 卡需要时间, 首次 applyGrow 时
        // cards.scrollHeight 可能偏小(部分卡未渲染), 高度按估算算偏矮,
        // 内容仍溢出底板。600ms 后卡片全渲染, 若仍为展开态用实测内容高重跑。
        setTimeout(() => {
            if (runtime._h3CollapsedAll) return;
            runtime._growInFlight = true;
            try { applyGrow(); } catch (e) {}
            runtime._growInFlight = false;
        }, 600);
    } catch (e) {}
}

async function fetchClipPreview(node, clipIndex) {
    // v2.61: state.clips[] 数组下标是 0-based, 但后端 h3 文件命名 + manifest
    // segments 都是 1-based. 整个调用链统一 0->1 转换; 反向拿 0->1 时也再 -1.
    const idxOneBased = Math.max(0, Number(clipIndex) | 0) + 1;
    const params = new URLSearchParams();
    params.set("owner_id", String(node.id));
    params.set("clip_index", String(idxOneBased));
    try {
        const response = await fetch(api.apiURL("/h3_extender/clip_preview?" + params.toString()));
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || !payload?.ok || !payload?.video) {
            // v2.61: 后端说"未渲染"通常是因为 manifest.segments 是空数组(缓存
            // 文件损坏/恢复未完成). 直接查 /h3_extender/rendered_clips 拿到最新
            // 时间戳对应的 mp4 文件名, 走 /view 接口读 bsai_clips/ 里的成片.
            return await fetchClipPreviewFromDisk(node, idxOneBased);
        }
        return payload.video;
    } catch (e) {
        return null;
    }
}

async function fetchClipPreviewFromDisk(node, clipIndex) {
    // v2.61: 通过 /h3_extender/rendered_clips 拿到 bsai_clips/ 里最新 mp4 文件名,
    // 然后用 ComfyUI /view 接口直接 stream. 适用于"manifest 损坏但 mp4 还在"
    // 的恢复缓存场景.
    try {
        const r = await fetch(api.apiURL("/h3_extender/rendered_clips?owner_id=" + encodeURIComponent(String(node.id))));
        const info = await r.json().catch(() => null);
        if (!info || !info.ok) return null;
        // v2.61: 后端 latest_filename_by_idx 直接给出 mp4 文件名, 不必自己解析.
        const fname = info.latest_filename_by_idx && info.latest_filename_by_idx[String(clipIndex)];
        if (!fname) return null;
        return {
            type: "output",
            subfolder: "bsai_clips",
            filename: fname,
        };
    } catch (_) {
        return null;
    }
}

function clipPreviewMediaUrl(info) {
    const params = new URLSearchParams();
    params.set("filename", info?.filename || "");
    params.set("type", info?.type || "temp");
    params.set("subfolder", info?.subfolder || "");
    // v1.84: temp 类型预览改用插件自服务路由, 绕开 ComfyUI /view?type=temp
    // 的 folder_paths.get_temp_directory() 解析不一致(4090 被其它插件改到系统
    // Temp 后 /view 404 无法播放). 插件路由直接从 ComfyUI\temp 读, 写读同源.
    //
    // v2.61: 新增 "bsai_clip"/"output" 类型——/h3_extender/clip_preview 在恢复缓存
    // (从备份拷回 / 或历史上已渲染过成片) 后从 ComfyUI/output/bsai_clips/ 里挑最新
    // 的 mp4 返回. 同样走插件自服务路由, 不依赖 ComfyUI 的 /view 接口.
    if (info?.filename && (info?.type === "bsai_clip" || info?.type === "temp")) {
        const p2 = new URLSearchParams();
        p2.set("name", info.filename);
        return api.apiURL("/h3_extender/clip_preview/file?" + p2.toString());
    }
    // v2.61: output 类型——直接走 ComfyUI /view?type=output&subfolder=bsai_clips
    // 读 output/bsai_clips/ 里的成片. 这是 manifest segments 为空时的回退路径.
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
    expandBtn.title = expanded ? "Shrink preview" : "Enlarge preview";
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
        closeBtn.title = "Close preview";
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
        label.textContent = "Rendering" + stepInfo;
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
        // v1.85: 残留 URL 的文件可能已被清空(temp 清理/外部删除), 播放失败时
        // 清除残留并重新渲染面板 -> 重新 fetch(blob 重建或"未渲染"提示), 不再黑屏.
        video.onerror = () => {
            if (clip._previewRebuilding) return;
            clip._previewRebuilding = true;
            clip._previewVideoUrl = null;
            clip._previewLoaded = false;
            renderPreviewPanel(panel, clip, index, node, runtime);
            requestAnimationFrame(() => { clip._previewRebuilding = false; syncDomHeight(node, runtime, false); });
        };
        contentWrap.appendChild(video);
        panel.appendChild(contentWrap);
        return;
    }

    // 3. Cached/ready but video not loaded yet — auto-fetch immediately
    if (cached) {
        const loading = document.createElement("div");
        loading.style.cssText = "display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:#555;font-size:11px;gap:6px;padding:8px;";
        loading.innerHTML = '<div style="font-size:18px;opacity:.6;animation:h3spin 1s linear infinite;">&#10227;</div><div>Loading preview...</div>';
        contentWrap.appendChild(loading);
        panel.appendChild(contentWrap);

        fetchClipPreview(node, index).then(videoInfo => {
            if (!videoInfo) {
                contentWrap.replaceChildren();
                const err = document.createElement("div");
                err.style.cssText = "display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:#555;font-size:11px;text-align:center;gap:6px;padding:8px;";
                err.innerHTML = '<div style="font-size:22px;opacity:.5;">&#128249;</div><div>Preview unavailable</div>';
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
        ph.innerHTML = '<div style="font-size:18px;opacity:.5;">&#9888;</div><div style="color:#a55;">Preview decode failed</div><div style="color:#777;font-size:9px;word-break:break-all;">' + clip._previewError.substring(0, 80) + '</div>';
    } else {
        ph.innerHTML = '<div style="font-size:22px;opacity:.5;">&#128249;</div><div>Waiting to render</div>';
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

// v14.202: 直播带货（全自动）档下新建的 CLIP 默认不带上下文（clip1 除外），
// 让卡片 UI 与后端强制规则一致，避免"新增第 3 段又默认勾选"的误解。
let _liveSellCtxOff = false;
function newClip(index) {
    return {
        id: `clip_${index + 1}_${Date.now().toString(36)}`,
        name: "",
        prompt: "",
        seed: randomSeed(),
        seed_mode: "randomize",
        duration: 15.0,
        validated: false,
        context_enabled: (index === 0) ? true : !_liveSellCtxOff,
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
        // v14.85 CLIP 级独立超分开关（三态）：null=跟随总开关 upscale_per_clip；true=强制本 CLIP 超分；false=强制本 CLIP 不超分
        upscale: null,
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
                    // v14.85 CLIP 级超分三态：仅 true/false 保留，其余（含缺失）归一为 null=跟随总开关
                    clip.upscale = c?.upscale === true ? true : c?.upscale === false ? false : null;
                    // v2.72: 外部提示词(clip_prompt_N 端口驱动)与 builtin_prompt 备份
                    // 由 serializeState 写入 clips_json, 但 parseState 之前不恢复 →
                    // 刷新/另存后 external_prompt 丢失, 需要重新输入外部提示词。
                    // 此处补全恢复, 保持端口断开/清空时的回退语义。
                    if (c?.external_prompt !== undefined) clip.external_prompt = String(c.external_prompt);
                    if (c?.builtin_prompt !== undefined) clip.builtin_prompt = String(c.builtin_prompt);
                    return clip;
                }),
            };
        }
    } catch (_) {}
    return { version: 1, load_token: "", prompt_pack_signature: "", merge_output: false, clips: [newClip(0)] };
}

function serializeState(state) {
    const clips = state.clips.map((c) => {
        // v14.137: _h3ExtDriven 只是 syncExternalPrompts 的运行时标记, 不落盘
        const { _previewLoaded, _previewVideoUrl, _previewExpanded, _previewReady, _latentPreviewUrl, _latentStep, _latentTotal, _previewError, _h3ExtDriven, upscale, ...rest } = c;
        // v14.85: 跟随态(null)不落盘，仅开(true)/关(false)存进 clips_json
        if (upscale === true || upscale === false) rest.upscale = upscale;
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

        // v1.100: 刷新/另存后从缓存恢复全局提示词(若前端 state 丢失), 资产链接
        // (@图N)自动恢复, 无需重新输入全局提示词。
        // v2.72: 条件从「state.global_prompt 为空」放宽为「textarea 显示值与缓存
        // 不一致」——onConfigure 恢复 state 后 state 非空, 但 textarea 可能仍是
        // constructRuntime 阶段的空白, 必须在这里兜底同步, 否则用户看不到外部
        // 提示词、被迫重新输入。
        if (payload?.global_prompt && String(runtime.globalPromptTextarea?.value || "") !== String(payload.global_prompt)) {
            runtime.state.global_prompt = String(payload.global_prompt);
            if (runtime.globalPromptTextarea && runtime.globalPromptTextarea.value !== String(payload.global_prompt)) {
                runtime.globalPromptTextarea.value = String(payload.global_prompt);
                autoResizeTextarea(runtime.globalPromptTextarea);
            }
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
        // v2.54: 延迟执行分辨率校验, 避免初始化时 widget 分辨率还没稳定, 导致缓存被误清空
        setTimeout(() => {
            try { syncResolutionAndInvalidate(node, runtime); } catch(e) {}
        }, 2000);
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

// Bilingual widget labels: English name + Chinese usage description (global scope)
const BSAI_BILINGUAL_LABELS = {
    "run_mode": "Run mode (clip_by_clip = one clip at a time / full_batch = all clips in one batch)",
    "width": "Width (manual render width; falls back to automatic)",
    "height": "Height (manual render height; falls back to automatic)",
    "ref_image_size": "Reference image size (match = follow the reference / max = use the largest)",
    "steps": "Sampling steps",
    "sampler_name": "Sampler",
    "scheduler": "Scheduler",
    "denoise": "Denoise strength (1.0 = full re-render)",
    "context_length": "Context length (H3 temporal context frames)",
    "audio_context_length": "Audio context length (0 = auto)",
    "resolution_mode": "Resolution mode (auto_from_ref = automatic / manual = manual)",
    "megapixels": "Megapixels (target total pixels for the automatic resolution)",
    "output_mode": "Output mode (none=cached / per_clip=segmented / merged=combined / both=both)",
    "filename_prefix": "Filename Prefix",
    "output_image_audio": "Output image & audio (decoded per clip)",
    "block_cache": "Block cache acceleration (F1B0 residual; requires the T8 plugin)",
    "block_cache_threshold": "Block cache threshold (higher = easier to hit)",
    "block_cache_device": "Block cache device (cpu = saves VRAM / gpu = uses VRAM)",
    "ref_cache": "Reference image cache (Ref2VA encoding; skips re-encoding on re-runs)",
    "cache_dit": "DiT step cache (CacheDiT acceleration; requires the plugin)",
    "clip_select_enable": "Clip selection toggle (render only selected clips)",
    "clip_select": "Clip selection (all / 1,3 / 2-5 / 3,5,7 / 7-10)",
    "restore_cache": "Restore cache (rebuilds rendered CLIPs from the latest backup, no re-render)",
    "pause_enable": "Pause toggle (pause after each CLIP finishes)",
    "pause_timeout": "Pause timeout (seconds; auto-resume when there is no input)",
    "refine_enable": "Refine toggle (quality repair / deblur)",
    "refine_denoise": "Refine denoise (0.5-0.6 is the sweet spot; low-light shots below 0.5 only get smoothed)",
    "refine_steps": "Refine steps",
    "refine_upscale_factor": "Latent upscale factor (1.0 = no upscale)",
    "speed_preset": "Speed preset (custom / Fast 4+2 / Balanced 6+4 / Fine 8+6 / VDN x3; model recipes live in Render Pipeline)",
    "temporal_chunk_tokens": "Temporal chunk size (split along T axis to prevent OOM; 0=off, T~107 recommends 40~60)",
    "temporal_overlap_tokens": "Temporal chunk overlap (tokens shared by adjacent chunks; higher = steadier but slower; usually 8-12)",
    "refine_upscaler_model": "Refine upscale model (3D semantic upscale / default bilinear)",
    "refine_align_to": "Refine alignment stride (default 32; rounds the resolution to avoid edge color bands)",
    "refine_audio_denoise": "Refine audio denoise (0 = keep the audio unchanged, recommended; 0.5-1.0 alters the sound)",
    "tiled_refine": "Tiled refine toggle (enable when VRAM is low; splits along H/W; off by default)",
    "tile_count": "Spatial tile count (higher = less VRAM but slower; default 4)",
    "tile_overlap": "Tile overlap in pixels (adjacent tiles are blended; default 128)",
    "semantic_bridge_enable": "Semantic Bridge toggle (default off)",
    "semantic_bridge_adapter": "Semantic Bridge weights (place in models/semantic_bridge, about 11MB)",
    "semantic_bridge_alpha": "Semantic Bridge strength (C = H + alpha*(S-H); default 0.15)",
    "semantic_bridge_magnitude_match": "Semantic Bridge magnitude match (on by default, as upstream)",
    "dual_track_shift": "Official dual-track sampling (separate video/audio shift; on by default)",
    "shift_video": "Video flow shift (official default 12)",
    "shift_audio": "Audio flow shift (official default 3; 0 = off)",
    "selflift_tst_enable": "SelfLift TST temporal state transfer (compensates quality at low step counts)",
    "selflift_tst_tau": "TST correction strength (paper recommends 0.2)",
    "upscale_batch": "Upscale batch frames (higher = faster but more VRAM; default 4)",
    "upscale_tile": "Upscale tile pixels (0 = full frame; use 512-1024 when VRAM is tight)",
    "upscale_model": "Upscale model (Real-ESRGAN models in models/upscale_models)",
    "upscale_factor": "Upscale factor (relative to the refine output resolution)",
    "upscale_engine": "Upscale engine (auto/dlss5/realesr/bicubic)",
    "upscale_mode": "Upscale mode (balanced / quality first / speed first / custom)",
    "upscale_per_clip": "Per-clip upscale toggle (default off)",
    "upscale_final": "Full-film upscale toggle (default off)",
    "upscale_fp16": "Upscale FP16 half-precision acceleration",
    "upscale_face_restore": "Face restore after upscale (requires GPFGAN/CodeFormer)",
    "env_audio_enable": "Ambient audio toggle (global_inherit = follow global, on = mix in, off = voice only)",
    "env_audio_gain": "Ambient audio gain (default 0.15)",
    "face_lock_mode": "Face lock modes: off=disabled / auto=normal face lock (@img2.N face close-ups drive ref2v conditioning) / refine=small-face repair (H3 FaceRefine local face-crop redraw on every segment before output, fixes broken faces in wide shots; needs BSAI-ComfyUI-FaceRefine, slower)",
    "refine_mem_mode": "Refine VRAM-saving mode (spatial = tiling-compatible / global = full context)",
    "one_shot_mode": "One-shot mode (off = shot-by-shot editing / on = seamless long take: no-cut instruction + forced motion context + zero-transition concat)",
    "one_shot_clip_duration": "One-shot target seconds per segment (0 disables auto CLIP split; with a song, CLIP count = song duration / this value)",
    "one_shot_sampling": "One-shot sampling preset (single-pass seamless = skip refine, zero seam drift, recommended turbo 8-step LoRA + beta 6-8 steps / dual-pass HD = keep refine for 2K but seams may drift / v14.215 dual-pass seamless 8+4 = keep the refine pass and repair the inter-segment anchor so the join stays seamless)",
    "render_pipeline": "Render pipeline (all model recipes are selected here, v14.184): Sol-H3 Self-Lift dual-pass (default) -> FastH3-Trim (8+4) -> FastH3 4-step VSA (4+2) -> Turbo-v4 (6+4, shift 12/3) -> DMAD 4-step (4+2, lcm) -> action combo (8+4, euler) -> 4K direct secret sauce (self-lift 6+3, latent x2.0 -> DLSS5 pixel upscale to 4K) -> FastH3 Omni 8-step single-pass (skips refine; switch the loader to the Omni model + VSA) -> dual-pass 2K (8+4, latent not upscaled + HyperVAE 2x decode -> 2x pixels -> 2K, audio refine inherits w33 0.7) -> live commerce fully automatic (12+4 one-click tier: audio_context_length=0 + context off from clip2; manual parameters are ignored) -> H25 Hybrid 8-Step Multi-Ref (v14.223, BV1dygg6EE6W: H25 Hybrid = base FL2VA + overlay Ref2VA, Block Range Additive 25-49, + LightX2V 8-step FL2V accel LoRA; 8-step single-pass euler/simple shift 12/3 denoise 1.0, refine skipped; Loader=minimax_h3_hybrid_fl2va_ref2va_b25-49-int8, accel-LoRA=minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16).",
    "refine_sampler": "Refine sampler (v14.238 Director port: independent second-pass sampler; inherit = follow first-pass sampler; Director fast tier defaults to euler while the first pass runs res_multistep)",
    "director_fast_first_mp": "Director fast first-pass megapixels (v14.238 port: low-res draft canvas, default 0.4 = 864x480 16:9; only active in the Director fast dual-pass tier)",
    "director_fast_target_mp": "Director fast target megapixels (v14.238 port: final canvas after the H3 latent 3D upscale, default 2.0 = 1920x1088 16:9; only active in the Director fast dual-pass tier)",
};
function bsaiApplyBilingualLabels(node) {
    if (!node || !node.widgets) return;
    // v2.67 perf: onDrawForeground 每帧都调本函数。必须加守卫：
    // 已标过 _bsaiBilingual 的 widget 直接跳过，且不再每帧 console.log
    // （控制台日志是同步阻塞，是画布一卡一卡的主因）。
    if (node.__bsaiBilingualDone) return;
    let applied = 0;
    for (const w of node.widgets) {
        if (!w) continue;
        if (w._bsaiBilingual) continue;
        const label = BSAI_BILINGUAL_LABELS[w.name];
        if (label) {
            w.label = w.name + "  " + label;
            w._bsaiBilingual = true;
            applied++;
        }
    }
    if (applied > 0) {
        node.__bsaiBilingualDone = true;
        console.log("[BSAI] node", node.id, "applied", applied, "bilingual labels");
    }
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

// v14.133 —— 参数行隐藏机制重写：改用前端官方可见性 API。
//
// 旧实现为什么会出现"参数栏错位重叠 / 隐藏不干净"（用户 2026-10-12 实测）：
//   1) widget.computeSize = () => [0, 0] 只把行高压成 0，行仍然留在 widgets
//      布局里占位，画布照样给它画圆角边框 → 多个 0 高行的边框叠在同一 y 上
//      （截图放大后就是好几条嵌套的圆角线）。
//   2) 1.5s 常驻轮询对整页 querySelectorAll("*") 扫文本，命中后做
//      display:none / height:0 / textContent="" / element.remove()。
//      remove() 和清空文本直接改 Vue 拥有的 DOM，vnode 与真实 DOM 失配，
//      下一次 Vue 重渲染就把行插回错误位置 → 参数栏错位。
//   3) 全文档扫描 + 常驻定时器阻塞主线程，多 H3 节点时画布卡死。
//
// 官方路径（comfyui_frontend 1.55.14）：
//   src/types/widgetVisibility.ts
//     widget.hidden = true / widget.options.hidden = true
//       → visibility.suppression.byExtension = true
//   src/lib/litegraph/src/LGraphNode.ts
//     getLayoutWidgets() 过滤 suppression.byExtension 的 widget
//       → 画布不分配行、不绘制边框（行彻底消失，不是 0 高）
//     drawWidgets() 同样跳过 isWidgetRowVisible() 为 false 的行
//   src/renderer/extensions/vueNodes/composables/processedWidgetRenderModel.ts
//     isWidgetVisibleOnSurface(visibility, 'vueNode') = false
//   src/renderer/extensions/vueNodes/components/WidgetGrid.vue
//     renderedRows 不返回该行 → v-if 不渲染 → DOM 行根本不存在
//   serializeFromStoreState 只跳过 serialize === false
//     → widgets_values 顺序/长度不变 → 零 NaN、零重连、旧工作流正常
//
// 关键点：Vue 侧读的是 widgetValueStore 里的 visibility 副本，只改 live
// widget 不会更新 DOM。setNodeId() 会重新 registerWidget 把 live visibility
// 同步进 store；随后 BaseWidget.bindRegisteredState() 让 _visibility 直接
// 指向 store 里那份响应式对象，所以"写 hidden"必须在 setNodeId 之后再写一次。
function setWidgetRowHidden(node, widget, hidden) {
    if (!widget) return false;

    const write = () => {
        // options.hidden 走 BaseWidget 的 legacy shim → applyLegacyHiddenWrite，
        // 并且写进 _rawOptions：之后任何 options 重新赋值 /
        // syncVisibilityFromOptions 重新推导都不会把 hidden 冲掉。
        try { widget.options.hidden = hidden; } catch (e) {}
        try { widget.hidden = hidden; } catch (e) {}
    };

    write();

    // 同步到 widgetValueStore —— Vue DOM 行的可见性来源。
    try {
        if (typeof widget.setNodeId === "function") widget.setNodeId(node?.id);
    } catch (e) {}

    // _visibility 此时已指向 store 的响应式对象，再写一次保证 Vue 立刻收到变更。
    write();

    return true;
}

function hideNativeWidget(node, widget) {
    setWidgetRowHidden(node, widget, true);
}

// 只在本节点的参数区网格里做兜底（异常前端 / 渲染时序），绝不再扫描整个
// document：只 display:none，绝不 remove / 不清空 textContent —— Vue 拥有的
// 节点不能删，删了下一次重渲染就会插回错误位置。
//
// 参数名必须按"完整单词"匹配：block_cache 是 block_cache_threshold /
// block_cache_device 的前缀，用 indexOf 会把这两行一起误藏（违反 1:1）。
function rowBelongsToKey(text, key) {
    const i = text.indexOf(key);
    if (i < 0) return false;
    const before = i === 0 ? "" : text[i - 1];
    const after = text[i + key.length] || "";
    return !/[\w]/.test(before) && !/[\w]/.test(after);
}

function nukeVisibleHiddenRows(node, keys) {
    if (!node || !Array.isArray(keys) || !keys.length) return;
    const grid = node.element?.querySelector?.(".lg-node-widgets")
        || document.querySelector('[data-node-id="' + node.id + '"] .lg-node-widgets');
    if (!grid) return;
    for (const row of Array.from(grid.children)) {
        const t = row.textContent || "";
        if (!t || t.length > 200) continue;
        if (!keys.some((k) => rowBelongsToKey(t, k))) continue;
        if (row.style.display === "none") continue;
        row.style.setProperty("display", "none", "important");
    }
}

// Vue 首次渲染参数区有延迟，创建后按固定节奏补几次兜底即可，之后不再常驻轮询。
function scheduleHiddenRowFallback(node, keys) {
    if (!node || node.__h3HiddenRowFallback) return;
    node.__h3HiddenRowFallback = true;
    const delays = [0, 150, 400, 900, 1600];
    delays.forEach((d, i) => {
        setTimeout(() => {
            try { nukeVisibleHiddenRows(node, keys); } catch (e) {}
            if (i === delays.length - 1) node.__h3HiddenRowFallback = false;
        }, d);
    });
}

// v14.134 —— 参数区隐藏清单，改为**严格 1:1**：
//   有快捷按钮的参数 → 隐藏参数栏行；
//   没有快捷按钮的参数 → 一律留在参数区可见（用户明确要求，不得多藏）。
//
// H3_MANAGED_ROW_KEYS = 本插件管理过可见性的全部行。
//   前 21 项 = 快捷条 QUICK_DEFS 对应的参数 → hidden
//   后 9 项  = v14.133 误藏的"附属高级参数" → 强制放回参数区（自愈）
const H3_MANAGED_ROW_KEYS = [
    // ── 快捷条 21 项 ──
    "refine_enable", "upscale_per_clip", "upscale_final", "block_cache", "ref_cache",
    "output_mode", "speed_preset", "refine_lipsync_mode", "upscale_mode", "pause_enable",
    "output_image_audio", "cache_dit", "clip_select_enable", "upscale_fp16",
    "upscale_face_restore", "tiled_refine", "semantic_bridge_enable",
    "semantic_bridge_magnitude_match", "face_lock_mode", "one_shot_mode",
    "render_pipeline",
    // ── v14.133 误藏、v14.134 起必须显示 ──
    "upscale_engine", "upscale_factor", "upscale_model", "upscale_tile", "upscale_batch",
    "tile_count", "tile_overlap", "semantic_bridge_adapter", "semantic_bridge_alpha",
];

// 只有"真的接了连线"的参数才不隐藏。
// 注意：ComfyUI 1.55 里 node.inputs 为**每个 widget** 都建了一条输入槽
// （就是每行左侧那个 hover 才出现的 ◀ 圆点，LGraphNode.getSlotFromWidget
// 按 widget.name 反查），所以"存在同名的 input 槽"根本不能作为判断依据 ——
// v14.133 用它做守卫，结果 19 个快捷项一个都没藏成。
function widgetSlotIsConnected(node, key) {
    try {
        const slot = typeof node.getSlotFromWidget === "function"
            ? node.getSlotFromWidget(node.widgets?.find((w) => w && w.name === key))
            : (node.inputs || []).find((s) => s && s.widget && s.widget.name === key);
        if (!slot) return false;
        if (slot.isConnected === true) return true;
        return slot.link != null;
    } catch (e) {
        return false;
    }
}

// applyHiddenParamRows(node, hideKeys)
//   hideKeys 里的行 → 隐藏；H3_MANAGED_ROW_KEYS 里其余的行 → 强制显示。
function applyHiddenParamRows(node, hideKeys) {
    if (!node) return;
    const hide = new Set(Array.isArray(hideKeys) ? hideKeys : []);
    const managed = H3_MANAGED_ROW_KEYS.slice();
    for (const k of hide) if (!managed.includes(k)) managed.push(k);
    node.__h3HiddenRowKeys = Array.from(hide);
    let touched = 0;
    for (const key of managed) {
        const w = node.widgets?.find((x) => x && x.name === key);
        if (!w) continue;
        if (hide.has(key)) {
            if (widgetSlotIsConnected(node, key)) continue;
            if (setWidgetRowHidden(node, w, true)) touched++;
        } else {
            // 没快捷按钮 → 一定放回参数区
            if (setWidgetRowHidden(node, w, false)) touched++;
        }
    }
    if (!touched) return;
    // 让 _arrangeWidgets 重算行位置，画布节点高度随之收缩。
    try { node._widgetSlotsDirty = true; } catch (e) {}
    try { node.setDirtyCanvas?.(true, true); } catch (e) {}
    scheduleHiddenRowFallback(node, Array.from(hide));
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
    reset.textContent = "Reset";
    const cancel = document.createElement("button");
    cancel.textContent = "Cancel";
    const apply = document.createElement("button");
    apply.textContent = "Apply";
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
        if (target && (ALL_FINAL_TARGETS.has(target?.comfyClass) || ALL_FINAL_TARGETS.has(target?.type))) return target;
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
    reset.textContent = "Reset";
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
    cancel.textContent = "Cancel";
    cancel.addEventListener("click", () => closeColorEditor(overlay));

    const apply = document.createElement("button");
    apply.textContent = "Apply";
    apply.style.fontWeight = "700";
    apply.style.minWidth = "84px";
    apply.addEventListener("click", async () => {
        apply.disabled = true;
        apply.textContent = "Applying...";
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
            apply.textContent = "Apply";
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
            class_name: BSAI_FINAL_TARGET,
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

    // v2.68 perf: cache — refs 没变就不重建 9 个 slot 的 DOM.
    const refs = runtime.refsState?.refs || [];
    const refsKey = refs.map((r, i) => r ? i + ":" + (r.original_name || "") + ":" + (r.width||0) + "x" + (r.height||0) : i + ":").join("|");
    if (row._refsKey === refsKey && row.childNodes.length > 0) return;
    row._refsKey = refsKey;
    row.replaceChildren();

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
        const resp = await fetch("/bsai/list_all_assets?t=" + Date.now());
        const data = await resp.json();
        app.graph._nodes.forEach(function(n) {
            if (ALL_TARGETS.has(n.type) && n.__h3Extender) {
                n.__h3Extender._h3_assetCache = data;
                // Auto-append asset-library references to the global prompt
                // when it carries none, so connected assets are actually used.
                if (autoRefAssetsToGlobal(n.__h3Extender)) {
                    try { render(n, n.__h3Extender, { chunked: true }); } catch (e) {}
                }
            }
        });
    } catch (e) {
        console.error("[H3] Failed to fetch assets:", e);
    }
}

// Remove a previously auto-appended "[资产库自动引用]" block whose tag
// line is malformed (e.g. old "0 1 2..." residue from a buggy version).
// Valid blocks carrying real @图N tags are kept untouched.
// Auto-grow any textarea so its height always fits the full content
// (removes the need for internal scrollbars; the card/node can then be
// stretched tall enough to show every line). If the textarea lives inside
// a .bsai-gp-editor-wrap (global prompt overlay container), the wrapper
// height is kept in sync so the node reports the full content height.
function autoResizeTextarea(ta) {
    if (!ta) return;
    const wrap = ta.closest(".bsai-gp-editor-wrap");
    // When the user drag-fixed the global prompt section height, keep
    // wrapper/textarea at 100% (internal scrolling) instead of growing.
    if (wrap && wrap.dataset.gpDragFixed === "1") {
        // Even in drag-fixed mode, keep the gp left asset panel height
        // locked to the wrapper so a long asset list can never push the
        // node taller than the user-set global prompt height.
        if (typeof syncGpLeftPanelToWrap === "function") {
            syncGpLeftPanelToWrap(wrap);
        }
        return;
    }
    // Detect if the node is currently being clipped by canvas zoom-out:
    // if the wrap's own rendered height is already SMALLER than the
    // textarea's intrinsic content height, growing the wrap to fit would
    // break visual equality with the left panel. In that case, leave the
    // wrap at its current rendered height and let the textarea scroll
    // internally so its visible footprint matches the left panel exactly.
    let wrapClipped = false;
    if (wrap) {
        const currentWrapH = wrap.clientHeight;
        // Temporarily reset the textarea height so scrollHeight reports
        // its true intrinsic content height (not a stale clipped value).
        const savedH = ta.style.height;
        ta.style.height = "auto";
        const intrinsicH = ta.scrollHeight;
        ta.style.height = savedH || "";
        if (currentWrapH > 0 && intrinsicH > currentWrapH + 1) {
            wrapClipped = true;
        }
    }
    if (wrapClipped) {
        // Wrap is being squeezed by an outer constraint (canvas zoom).
        // Lock the textarea to the wrap and let it scroll internally.
        ta.style.height = "100%";
        ta.style.maxHeight = "100%";
        ta.style.overflowY = "auto";
        if (wrap) {
            wrap.style.overflow = "hidden";
        }
        if (typeof syncGpLeftPanelToWrap === "function") {
            syncGpLeftPanelToWrap(wrap);
        }
        return;
    }
    ta.style.height = "auto";
    ta.style.height = ta.scrollHeight + "px";
    if (wrap) wrap.style.height = ta.scrollHeight + "px";
    if (wrap) wrap.style.overflow = "";
    if (wrap && typeof syncGpLeftPanelToWrap === "function") {
        syncGpLeftPanelToWrap(wrap);
    }
}

// Lock the global-prompt left asset panel height to the editor wrapper so
// a long asset list (with overflow-y:auto + many rows) can never push the
// node taller than the prompt textarea itself. Implemented as a single
// function (no ResizeObserver per render) and called from every place
// that mutates the wrapper height: autoResizeTextarea, drag-resize, and
// the per-frame render() pass.
//
// IMPORTANT: read the wrap's *rendered* height (clientHeight) instead of
// getBoundingClientRect(). When the user zooms the canvas out, the whole
// node gets visually clipped and the bounding rect can be smaller than
// the wrap's actual layout height. clientHeight reflects the wrap's
// real internal height, so leftPanel never gets stuck at a stale value.
function syncGpLeftPanelToWrap(wrap) {
    if (!wrap) return;
    const section = wrap.parentElement;
    if (!section) return;
    const left = section.querySelector(".bsai-gp-left-panel");
    if (!left) return;
    // Prefer the wrap's own clientHeight — survives canvas zoom-out where
    // the node is visually clipped but its layout box is still large.
    let h = wrap.clientHeight;
    if (!(h > 0)) h = wrap.getBoundingClientRect().height;
    if (h > 0) {
        left.style.height = h + "px";
        left.style.maxHeight = h + "px";
    }
    // When the canvas zooms out so far that the node is shorter than the
    // textarea content, the absolute-positioned textarea would otherwise
    // overflow the wrap and visually grow taller than the left panel.
    // Force the textarea to fill 100% of the wrap (with internal scroll)
    // so its *visible* footprint matches the left panel exactly.
    const ta = wrap.querySelector("textarea");
    if (ta && h > 0) {
        ta.style.height = "100%";
        ta.style.maxHeight = "100%";
        ta.style.overflowY = "auto";
    }
}

// Run sync once after the next paint. Used to cover the very first render
// of the node, when the left panel was just created/inserted but the wrap
// has not yet been measured (clientHeight = 0) and ResizeObserver has not
// fired yet. Without this, a saved global prompt with many lines would
// briefly render the left panel at its full content height, then snap.
function syncGpLeftPanelToWrapNextFrame(wrap) {
    if (!wrap) return;
    requestAnimationFrame(() => {
        requestAnimationFrame(() => syncGpLeftPanelToWrap(wrap));
    });
}

function sanitizeGlobalPrompt(gp) {
    if (!gp) return gp;
    const lines = String(gp).split("\n");
    const out = [];
    for (let i = 0; i < lines.length; i++) {
        const lt = lines[i].trim();
        if (/^\[资产库自动引用\]/.test(lt)) {
            // drop header; also drop an immediately-following tag/junk line
            let j = i + 1;
            while (j < lines.length && !lines[j].trim()) j++;
            if (j < lines.length && (/^@(图|视频|音频)\d/.test(lines[j].trim()) || /^[\d\s]+$/.test(lines[j].trim()))) {
                i = j;
            }
        } else {
            out.push(lines[i]);
        }
    }
    const cleaned = out.join("\n").replace(/\n{3,}/g, "\n\n").trim();
    return cleaned === gp ? gp : cleaned;
}

// Reference rendering is driven by user-written @图N/@视频N/@音频N/<Picture N>
// tags only. Never inject an auto-reference block into the global prompt:
// per user request, an empty prompt must stay empty. This helper only strips
// legacy "[资产库自动引用]" blocks saved by older versions.
function autoRefAssetsToGlobal(runtime) {
    if (!runtime || !runtime.state) return false;
    const gp = sanitizeGlobalPrompt(runtime.state.global_prompt || "");
    if (gp === runtime.state.global_prompt) return false;
    runtime.state.global_prompt = gp;
    if (runtime.globalPromptTextarea && runtime.globalPromptTextarea.value !== gp) {
        runtime.globalPromptTextarea.value = gp;
        autoResizeTextarea(runtime.globalPromptTextarea);
    }
    // Persist into clips_json widget so the cleaned prompt is saved too.
    try {
        if (runtime.jsonWidget && typeof runtime.jsonWidget.value === "string") {
            const st = JSON.parse(runtime.jsonWidget.value);
            if (st && st.global_prompt !== gp) {
                st.global_prompt = gp;
                runtime.jsonWidget.value = JSON.stringify(st);
            }
        }
    } catch (e) { /* ignore */ }
    return true;
}

function parseAssetRefs(prompt) {
    const refs = [];
    const re = /@(图|视频|音频)(\d+)/g;
    let match;
    while ((match = re.exec(prompt)) !== null) {
        const type = match[1] === "图" ? "images" : match[1] === "视频" ? "videos" : "audios";
        refs.push({ type: type, index: parseInt(match[2]), tag: match[0] });
    }
    // Also parse <Picture N> tags (SKILL storyboard archive format) as image refs
    const reP = /<Picture\s+(\d+)>/gi;
    let m2;
    while ((m2 = reP.exec(prompt)) !== null) {
        const idx = parseInt(m2[1]);
        if (!refs.some(function(r) { return r.type === "images" && r.index === idx; })) {
            refs.push({ type: "images", index: idx, tag: m2[0] });
        }
    }
    return refs;
}

function cleanStaleAssetRefs(text, assetList) {
    const refs = parseAssetRefs(text);
    let result = text;
    refs.forEach(function(ref) {
        const items = assetList[ref.type] || [];
        const exists = items.some(function(i) { return i.index === ref.index; });
        if (!exists) {
            result = result.split(ref.tag).join("").replace(/\s+/g, " ").trim();
        }
    });
    return result;
}

function renderAssetPanel(leftPanel, clip, node, runtime, textarea) {
    // v2.31 (2026-09-20 perf fix): 加缓存 - refs 没变就不重新渲染 DOM,
    // 避免每次 render 都清空再重新创建所有缩略图 (30 个 CLIP × 5 个缩略图 = 150 个 img, 每次都重新加载非常慢).
    const refs = parseAssetRefs(clip.prompt || "");
    const refsKey = refs.map(r => r.type + ":" + r.index).join(",");
    if (clip._assetPanelRefsKey === refsKey && leftPanel.childNodes.length > 0) {
        // refs 没变, DOM 已经存在, 直接返回, 不重新渲染
        return;
    }
    clip._assetPanelRefsKey = refsKey;

    leftPanel.innerHTML = "";

    // Title row
    const hdr = document.createElement("div");
    hdr.style.cssText = "display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;font-size:11px;color:#888;";
    const title = document.createElement("span");
    title.textContent = "Referenced Assets";
    hdr.appendChild(title);

    const refreshBtn = document.createElement("button");
    refreshBtn.textContent = "↻";
    refreshBtn.style.cssText = "background:#333;color:#aaa;border:1px solid #444;border-radius:2px;cursor:pointer;font-size:12px;padding:0 4px;";
    refreshBtn.title = "Refresh asset library";
    refreshBtn.addEventListener("click", () => { h3FetchAssets(); clip._assetPanelRefsKey = null; renderAssetPanel(leftPanel, clip, node, runtime, textarea); });
    hdr.appendChild(refreshBtn);
    leftPanel.appendChild(hdr);

    // Parse @图N/@视频N/@音频N and <Picture N> from THIS CLIP's own prompt
    // only. Global-prompt refs are intentionally NOT shown here: each CLIP
    // card's left panel must list just the assets its own prompt references,
    // so cards without refs stay compact instead of mirroring every asset.

    if (refs.length === 0) {
        const empty = document.createElement("div");
        empty.style.cssText = "color:#555;font-size:11px;text-align:center;padding:8px;";
        empty.textContent = "No references";
        leftPanel.appendChild(empty);
    } else {
        const assetList = runtime._h3_assetCache;
        // Group identical assets: show ONE thumbnail per asset with a usage
        // count badge in its bottom-right corner. Duplicates no longer stack
        // rows, so the card height stays compact.
        const groups = new Map();
        for (const ref of refs) {
            const key = ref.type + ":" + ref.index;
            const g = groups.get(key) || { ref: ref, count: 0 };
            g.count += 1;
            groups.set(key, g);
        }
        Array.from(groups.values()).forEach(function(g) {
            const ref = g.ref;
            const count = g.count;
            const assetItem = document.createElement("div");
            assetItem.style.cssText = "display:flex;align-items:center;gap:4px;margin-bottom:3px;font-size:11px;";

            const thumb = document.createElement("div");
            thumb.style.cssText = "position:relative;width:40px;height:40px;border:1px solid #333;border-radius:3px;overflow:hidden;flex-shrink:0;background:#1a1a1a;";
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
            // Usage count badge (only when the same asset is referenced more
            // than once in this CLIP's prompt)
            if (count > 1) {
                const badge = document.createElement("div");
                badge.textContent = "×" + count;
                badge.style.cssText = "position:absolute;right:1px;bottom:1px;background:rgba(190,30,30,.92);color:#fff;font-size:9px;line-height:1.2;padding:1px 3px;border-radius:3px;pointer-events:none;";
                thumb.appendChild(badge);
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
        { label: "Images", items: assetList.images || [], type: "images", prefix: "img" },
        { label: "Videos", items: assetList.videos || [], type: "videos", prefix: "vid" },
        { label: "Audio", items: assetList.audios || [], type: "audios", prefix: "aud" },
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
        popup.innerHTML = '<div style="color:#555;font-size:11px;text-align:center;padding:12px;">Asset library is empty</div>';
    }

    // Close button
    const closeBtn = document.createElement("div");
    closeBtn.textContent = "✕ Close";
    closeBtn.style.cssText = "text-align:center;padding:4px;margin-top:4px;color:#a44;cursor:pointer;font-size:11px;border-top:1px solid #333;";
    closeBtn.addEventListener("click", function() { popup.remove(); });
    popup.appendChild(closeBtn);

    parentEl.style.position = "relative";
    parentEl.appendChild(popup);
}

/**
 * Show asset picker triggered by typing @ in a textarea.
 * Filters assets by the keyword typed after @, inserts selected tag at cursor.
 * Works with both CLIP prompts (clip.prompt) and global prompt (state.global_prompt).
 */
function showAssetPickerForTextarea(parentEl, clipOrState, node, runtime, textarea, keyword) {
    const existing = parentEl.querySelector(".bsai-asset-picker");
    if (existing) existing.remove();

    // Record the @ position at the time the picker was opened — much more
    // reliable than re-computing from selectionStart on mousedown (the
    // textarea may lose focus and selectionStart becomes unreliable).
    const pos = textarea.selectionStart;
    const val = textarea.value;
    const beforeText = val.substring(0, pos);
    const atMatch = beforeText.match(/@([^\s@]*)$/);
    if (!atMatch) return;
    const atPos = beforeText.length - atMatch[0].length;

    const assetList = runtime._h3_assetCache || { images: [], videos: [], audios: [] };
    const groups = [
        { label: "Images", items: assetList.images || [], type: "images", prefix: "img" },
        { label: "Videos", items: assetList.videos || [], type: "videos", prefix: "vid" },
        { label: "Audio", items: assetList.audios || [], type: "audios", prefix: "aud" },
    ];

    // Filter by keyword
    const kw = (keyword || "").toLowerCase();
    const filteredGroups = groups.map(g => ({
        ...g,
        items: g.items.filter(item =>
            !kw || String(item.index).includes(kw) || (item.name || "").toLowerCase().includes(kw)
        ),
    })).filter(g => g.items.length > 0);

    const popup = document.createElement("div");
    popup.className = "bsai-asset-picker";
    popup.style.cssText = "position:absolute;z-index:1000;background:#1a1a1a;border:1px solid #444;border-radius:4px;padding:8px;max-height:280px;overflow-y:auto;width:200px;box-shadow:0 4px 12px rgba(0,0,0,0.5);top:100%;left:0;";

    filteredGroups.forEach(function(g) {
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

            const thumb = document.createElement("div");
            thumb.style.cssText = "width:24px;height:24px;border:1px solid #333;border-radius:2px;overflow:hidden;flex-shrink:0;";
            if (g.type !== "audios") {
                const img = document.createElement("img");
                img.style.cssText = "width:100%;height:100%;object-fit:cover;";
                img.src = "/bsai/asset_file?type=" + g.type + "&filename=" + encodeURIComponent(item.name);
                thumb.appendChild(img);
            } else {
                thumb.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;width:100%;height:100%;color:#666;font-size:12px;">♪</div>';
            }
            row.appendChild(thumb);

            const lbl = document.createElement("span");
            lbl.textContent = tag;
            lbl.style.cssText = "font-size:11px;color:#ccc;";
            row.appendChild(lbl);

            row.addEventListener("mousedown", function(e) {
                e.preventDefault();
                e.stopPropagation();
                textarea.focus();
                // Use the pre-recorded @ position (atPos) and cursor position (pos)
                // from when the picker was opened — this is reliable because
                // selectionStart doesn't change when focus is retained.
                const fullVal = textarea.value;
                // Re-read current selection in case user typed more chars
                let curPos = textarea.selectionStart;
                // Validate: if cursor moved past pos, use the new position
                // but still find the @ that opened the picker
                let atPosition = atPos;
                // If the @ at atPos was deleted, scan backward from cursor
                if (atPosition >= fullVal.length || fullVal[atPosition] !== "@") {
                    atPosition = -1;
                    for (let i = curPos - 1; i >= 0; i--) {
                        if (fullVal[i] === "@") {
                            atPosition = i;
                            break;
                        }
                    }
                    if (atPosition < 0) { popup.remove(); return; }
                }
                // Find the end of the @keyword (first space or cursor, whichever is first)
                let kwEnd = atPosition + 1;
                while (kwEnd < fullVal.length && kwEnd < curPos && !/[\s@]/.test(fullVal[kwEnd])) {
                    kwEnd++;
                }
                // Build the new value: everything before @ + tag + everything after keyword
                const beforePart = fullVal.substring(0, atPosition);
                const afterPart = fullVal.substring(kwEnd);
                const needSpaceBefore = beforePart.length > 0 && !beforePart.endsWith(" ") && !beforePart.endsWith("\n");
                const needSpaceAfter = afterPart.length > 0 && !afterPart.startsWith(" ") && !afterPart.startsWith("\n");
                const insertText = (needSpaceBefore ? " " : "") + tag + (needSpaceAfter ? " " : "");
                const newVal = beforePart + insertText + afterPart;
                textarea.value = newVal;
                const newPos = beforePart.length + insertText.length;
                textarea.setSelectionRange(newPos, newPos);
                // Dispatch native input event — the listener will update
                // clip.prompt / state.global_prompt and render the overlay.
                // No _justInsertedAsset flag needed: after inserting "@图3 ",
                // the text before cursor ends with a space, so the @ picker
                // regex /@([^\s@]*)$/ won't match and won't re-trigger.
                textarea.dispatchEvent(new Event("input", { bubbles: true }));
                popup.remove();
            });

            popup.appendChild(row);
        });
    });

    if (!popup.children.length) {
        popup.innerHTML = '<div style="color:#555;font-size:11px;text-align:center;padding:12px;">No matching assets</div>';
    }

    // Close on click outside
    setTimeout(() => {
        const closeHandler = function(e) {
            if (!popup.contains(e.target) && e.target !== textarea) {
                popup.remove();
                document.removeEventListener("mousedown", closeHandler, true);
            }
        };
        document.addEventListener("mousedown", closeHandler, true);
    }, 0);

    parentEl.style.position = "relative";
    parentEl.appendChild(popup);
}

function _readPromptSourceText(node) {
    const psInput = node.inputs?.find(inp => inp.name === "prompt_source");
    if (!psInput || psInput.link == null) return null;
    return readUpstreamText(node, node.graph, psInput);
}

function syncGlobalPromptFromInput(node, runtime) {
    try {
        const text = _readPromptSourceText(node);
        // v2.53: 外部提示词清空时也要同步, 不能只判断非空
        if (text != null) {
            const fullText = String(text);
            // Split at first [分镜N] marker: before → global prompt
            const sbMarkerRe = /\[(?:分镜|Shot|shot|SHOT)\s*\d+\]/;
            const sbMatch = fullText.match(sbMarkerRe);
            const globalText = sbMatch ? fullText.slice(0, sbMatch.index).trim() : fullText.trim();
            const storyboardText = sbMatch ? fullText.slice(sbMatch.index).trim() : "";

            // v2.14: 源文本变化时实时解析 [分镜N], 自动建/改/删 CLIP (等同点"统一刷新"),
            // 由 poller 在外层做 render+autoGrow, 这里只改 state 并打脏标记, 避免 render 递归.
            if (fullText !== runtime._lastPromptSourceText) {
                runtime._lastPromptSourceText = fullText;
                if (storyboardText) {
                    const segments = parseStoryboard(storyboardText);
                    for (let i = 0; i < segments.length; i++) {
                        while (runtime.state.clips.length <= i) {
                            runtime.state.clips.push(newClip(runtime.state.clips.length));
                        }
                        runtime.state.clips[i].prompt = segments[i].prompt;
                        runtime.state.clips[i]._storyboardFilled = true;
                        delete runtime.state.clips[i].external_prompt;
                        runtime.state.clips[i].duration = String(segments[i].duration);
                    }
                    if (runtime.state.clips.length > segments.length) {
                        runtime.state.clips.splice(segments.length);
                    }
                    runtime._sourceClipsDirty = true;
                    // v2.72: storyboard 解析填充 CLIP prompt(含 @图N)后必须立即写回
                    // clips_json widget —— 否则保存工作流时 json 里 CLIP prompt 仍是
                    // 旧值, 刷新/另存后 @图N 引用丢失, 用户被迫"清空再重输外部提示词"
                    // 才能重新自动@资产库。updateHidden 只写 widget + 打脏, 不 render,
                    // 不会与 poller 的 render 递归。
                    updateHidden(node, runtime);
                } else if (!fullText || !fullText.trim()) {
                    // v2.53: 外部提示词完全清空时, 把所有 CLIP 也清空
                    if (runtime.state.clips.length > 0) {
                        runtime.state.clips.splice(0);
                        runtime._sourceClipsDirty = true;
                        updateHidden(node, runtime);
                    }
                }
            }

            // v2.53: 区分两种情况
            // - 外部源文本完全空了: 内部全局提示词也跟着清空
            // - 外部源文本非空, 但没有全局提示词部分: 保留内部的 (不覆盖手动输入)
            const sourceCompletelyEmpty = !fullText || !fullText.trim();
            
            if (sourceCompletelyEmpty || (globalText && runtime.state.global_prompt !== globalText)) {
                runtime.state.global_prompt = sourceCompletelyEmpty ? "" : globalText;
                updateHidden(node, runtime);
            }
            if (runtime.globalPromptTextarea) {
                const targetVal = sourceCompletelyEmpty ? "" : globalText;
                if (sourceCompletelyEmpty || (globalText && runtime.globalPromptTextarea.value !== targetVal)) {
                    runtime.globalPromptTextarea.value = targetVal;
                    autoResizeTextarea(runtime.globalPromptTextarea);
                }
            }
            // v2.68 perf: only refresh asset panel when the global prompt text actually
            // changed (every poll used to rebuild innerHTML with dozens of <img> thumbnails).
            if (typeof runtime.renderGlobalAssetPanel === "function" &&
                runtime._lastGpForAssetPanel !== (sourceCompletelyEmpty ? "" : globalText)) {
                runtime._lastGpForAssetPanel = sourceCompletelyEmpty ? "" : globalText;
                runtime.renderGlobalAssetPanel();
            }
        }
    } catch (e) { /* ignore */ }
}

// v2.82 (2026-09-27): 卡片构建提取为独立函数, 支持增量懒加载。
// 打开工作流只渲染前 6 张(renderMoreClips 增量追加), 彻底避免大工作流
// 一次性构建数千节点导致页面无响应; 内容完整可见(不再默认折叠)。
function buildClipCard(node, runtime, clip, index) {
    try {
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
            ? "Render: enabled (click to disable rendering of this clip)"
            : "Render: disabled (click to enable rendering of this clip)";
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
            ? "Regenerate: selected (only this clip is re-rendered at runtime, other clips are unaffected)"
            : "Click to select this clip for standalone regeneration (other clips are unaffected)";
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

        // ── v14.85 CLIP 级独立超分三态开关（H） ─────────────────────
        // 循环：跟随(H·灰) → 强制开(H↑绿) → 强制关(H↓红) → 跟随
        const upscaleBtn = document.createElement("button");
        upscaleBtn.type = "button";
        const _upState = clip.upscale; // null | true | false
        const _upLabel = _upState === true ? "H↑" : _upState === false ? "H↓" : "H·";
        const _upTip = _upState === true
            ? "Upscale: forced on (this clip is always upscaled per-segment, ignoring the global switch)"
            : _upState === false
                ? "Upscale: forced off (this clip is never upscaled per-segment, ignoring the global switch)"
                : "Upscale: follow (controlled by the node-level upscale_per_clip switch)";
        upscaleBtn.title = _upTip;
        upscaleBtn.textContent = _upLabel;
        upscaleBtn.style.cssText = "width:24px;height:22px;padding:0;font-size:11px;font-weight:bold;border-radius:4px;border:1px solid rgba(255,255,255,.15);cursor:pointer;";
        upscaleBtn.style.background = _upState === true
            ? "rgba(60,160,70,.32)"
            : _upState === false
                ? "rgba(180,60,60,.30)"
                : "rgba(100,100,100,.18)";
        upscaleBtn.style.color = _upState === true ? "#9fe" : _upState === false ? "#fbb" : "#aaa";
        upscaleBtn.style.opacity = _upState === null ? ".6" : ".95";
        upscaleBtn.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            // null → true → false → null
            if (clip.upscale === null) clip.upscale = true;
            else if (clip.upscale === true) clip.upscale = false;
            else clip.upscale = null;
            updateHidden(node, runtime);
            render(node, runtime);
        });

        clipActions.append(renderToggle, upscaleBtn, replaceBtn);

        // ── Independent Render button: render ONLY this CLIP ──
        const clipRenderBtn = document.createElement("button");
        clipRenderBtn.type = "button";
        clipRenderBtn.textContent = "▶";
        clipRenderBtn.title = "Render this CLIP only (others unaffected)";
        clipRenderBtn.style.cssText = "width:26px;height:22px;padding:0;font-size:12px;border-radius:4px;border:1px solid rgba(80,200,80,.6);background:rgba(30,100,40,.6);color:#8f8;cursor:pointer;flex:0 0 auto;margin-left:4px;font-weight:bold;";
        clipRenderBtn.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            // Set replace_mode on the selected clip and disable rendering
            // for all other clips. This ensures only this CLIP is generated
            // even if the queue runs multiple times.
            clip.replace_mode = true;
            clip.render_enabled = true;
            runtime.state.clips.forEach((c, ci) => {
                if (ci !== index) { c.render_enabled = false; c.replace_mode = false; }
            });

            updateHidden(node, runtime);
            runtime.statusText = `Rendering CLIP ${index + 1}`;
            if (runtime.counter) runtime.counter.textContent = `${runtime.state.clips.length} clips • ${refCount(runtime)} refs`;
            if (runtime.status) runtime.status.textContent = runtime.statusText;
            try {
                if (window.app?.queuePrompt) window.app.queuePrompt();
                else if (app?.queuePrompt) app.queuePrompt();
            } catch(qe) {
                console.warn("[H3] Could not auto-queue for single CLIP render", qe);
            }
        });

        // ── Red X delete button (rightmost) ─────────────────────────
        const delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.textContent = "✕";
        delBtn.title = "Delete this CLIP";
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

        // v2.52 perf: 折叠的 CLIP 不渲染内部内容 (资产面板/提示词/预览),
        // 大幅减少 DOM 节点数量, 拖动画布更流畅.
        if (clip.collapsed) {
            card.appendChild(cardBody);
            runtime.cards.appendChild(card);
            return card; // v2.82: 折叠分支直接返回(只渲染头部)
        }

        // Left panel: referenced assets (v2.40: 加 tab 切换: 资产 / 模板)
        const leftPanel = document.createElement("div");
        leftPanel.style.cssText = "width:160px;min-width:160px;flex-shrink:0;border-right:1px solid rgba(255,255,255,.08);background:rgba(0,0,0,.15);padding:6px;display:flex;flex-direction:column;overflow-y:auto;";
        
        // v2.40: 左侧面板 tab 头
        const leftTabs = document.createElement("div");
        leftTabs.style.cssText = "display:flex;gap:2px;margin-bottom:6px;border-bottom:1px solid rgba(255,255,255,.1);padding-bottom:4px;";
        const tabAsset = document.createElement("button");
        tabAsset.textContent = "Assets";
        tabAsset.style.cssText = "flex:1;padding:3px 0;border:1px solid #444;background:#3a3a4a;color:#ccc;border-radius:3px;cursor:pointer;font-size:10px;";
        const tabTemplate = document.createElement("button");
        tabTemplate.textContent = "Templates";
        tabTemplate.style.cssText = "flex:1;padding:3px 0;border:1px solid #444;background:#2a2a3a;color:#999;border-radius:3px;cursor:pointer;font-size:10px;";
        leftTabs.append(tabAsset, tabTemplate);
        leftPanel.appendChild(leftTabs);
        
        // v2.40: tab 内容区
        const tabContent = document.createElement("div");
        tabContent.style.cssText = "flex:1;display:flex;flex-direction:column;";
        leftPanel.appendChild(tabContent);
        
        // v2.40: 切换 tab
        let activeTab = "asset";
        function switchLeftTab(tab) {
            activeTab = tab;
            if (tab === "asset") {
                tabAsset.style.background = "#3a3a4a";
                tabAsset.style.color = "#ccc";
                tabTemplate.style.background = "#2a2a3a";
                tabTemplate.style.color = "#999";
                // v2.51: 清缓存, 强制重新渲染资产面板 (否则模板面板内容挡住了)
                clip._assetPanelRefsKey = null;
                renderAssetPanel(tabContent, clip, node, runtime, prompt);
            } else {
                tabTemplate.style.background = "#4a4a6a";
                tabTemplate.style.color = "#eef";
                tabAsset.style.background = "#2a2a3a";
                tabAsset.style.color = "#999";
                renderClipTemplatePanel(tabContent, clip, node, runtime, prompt, index);
            }
        }
        tabAsset.addEventListener("click", () => switchLeftTab("asset"));
        tabTemplate.addEventListener("click", () => switchLeftTab("template"));

        // Right panel: existing content (prompt, subtitle, ref frame extract, seed, etc.)
        const rightPanel = document.createElement("div");
        rightPanel.style.cssText = "flex:1 1 auto;min-width:0;padding:9px;display:flex;flex-direction:column;position:relative;";

        // ── Prompt header (external prompt is injected via the node's
        // clip_prompt_1..12 input ports, not via card-internal UI) ──
        const promptHeader = document.createElement("div");
        promptHeader.style.cssText = "display:flex;align-items:center;gap:6px;";
        const promptLabel = makeFieldLabel("Prompt");
        promptLabel.style.margin = "5px 0 3px";
        rightPanel.appendChild(promptHeader);




        const promptRow = document.createElement("div");
        promptRow.style.cssText = "display:flex;flex-direction:row;gap:3px;width:100%;flex:1 1 auto;min-height:200px;align-items:stretch;resize:vertical;overflow:hidden;";
        const prompt = document.createElement("textarea");
        prompt.value = clip.prompt;
        clip._promptEl = prompt;
        prompt.spellcheck = false;
        prompt.style.width = "100%";
        prompt.style.minHeight = "160px";
        prompt.style.height = "200px";
        prompt.style.maxHeight = "none";
        prompt.style.flex = "0 0 auto";
        prompt.style.resize = "vertical";
        prompt.style.overflowY = "auto";
        prompt.style.boxSizing = "border-box";
        prompt.style.background = "rgba(0,0,0,.27)";
        prompt.style.border = "1px solid rgba(255,255,255,.15)";
        prompt.style.color = "inherit";
        prompt.style.borderRadius = "5px";
        prompt.style.padding = "6px";

        const promptExpandBtn = document.createElement("button");
        promptExpandBtn.textContent = "⤢";
        promptExpandBtn.title = "Enlarge prompt window";
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
        // IMPORTANT: all font/text metrics must match the textarea exactly
        // so the overlay text aligns perfectly with the cursor position.
        const clipOverlay = document.createElement("div");
        clipOverlay.style.cssText = [
            "position:absolute", "top:0", "left:0", "width:100%", "height:100%",
            "min-height:120px",
            "font-size:11px", "line-height:1.4",
            "font-family: inherit", "font-weight: inherit",
            "letter-spacing: normal", "word-spacing: normal",
            "text-indent: 0", "text-transform: none",
            "border:1px solid rgba(255,255,255,.15)", "border-radius:5px",
            "padding:4px 6px", "box-sizing:border-box",
            "overflow-y:auto", "overflow-x:hidden",
            "pointer-events:none", "white-space:pre-wrap", "word-wrap:break-word",
            "word-break: normal",
            "z-index:1", "background:rgba(0,0,0,.27)",
            "color:inherit",
            "margin: 0",
        ].join(";") + ";";
        // Match textarea styles to the overlay EXACTLY — any difference in
        // font metrics causes the cursor to drift away from the text position
        // as the user types, especially in long CLIP prompts.
        prompt.style.cssText = [
            "position:absolute", "top:0", "left:0", "width:100%", "height:100%",
            "min-height:160px",
            "font-size:11px", "line-height:1.4",
            "font-family: inherit", "font-weight: inherit",
            "letter-spacing: normal", "word-spacing: normal",
            "text-indent: 0", "text-transform: none",
            "border:1px solid rgba(255,255,255,.15)", "border-radius:5px",
            "padding:4px 6px !important", "box-sizing:border-box",
            "overflow-y:auto", "overflow-x:hidden",
            "z-index:2", "background:transparent",
            "resize:none", "outline:none",
            "caret-color:white",
            "word-wrap:break-word",
            "word-break: normal",
            "white-space:pre-wrap",
            "margin: 0",
        ].join(";") + ";";
        prompt.style.setProperty("color", "transparent", "important");
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
            clip.prompt = prompt.value;
            updateHidden(node, runtime);
            renderClipOverlay();
            // Check if user just typed @ — show asset picker
            const pos = prompt.selectionStart;
            const before = prompt.value.substring(0, pos);
            const atMatch = before.match(/@([^\s@]*)$/);
            if (atMatch && atMatch[0].length <= 20) {
                showAssetPickerForTextarea(promptRow, clip, node, runtime, prompt, atMatch[1]);
            } else {
                const existing = promptRow.querySelector(".bsai-asset-picker");
                if (existing) existing.remove();
            }
        });
        prompt.addEventListener("focus", () => {
            window._h3_activeTextarea = prompt;
            window._h3_activeClip = clip;
            window._h3_activeNode = node;
            window._h3_activeRuntime = runtime;
            window._h3_activeLeftPanel = leftPanel;
            window._h3_refreshAssetPanel = () => {
                updateHidden(node, runtime);
                if (activeTab === "asset") {
                    renderAssetPanel(tabContent, clip, node, runtime, prompt);
                } else {
                    renderClipTemplatePanel(tabContent, clip, node, runtime, prompt, index);
                }
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
                // Don't re-render if the asset picker is open — the user is
                // clicking inside the picker, which causes textarea blur.
                // Re-rendering would destroy the picker mid-interaction and
                // can also wipe pending prompt changes (e.g. second @tag).
                const pickerOpen = promptRow.querySelector(".bsai-asset-picker");
                if (document.activeElement !== prompt && !pickerOpen) {
                    render(node, runtime);
                }
            }, 200);
        });

        // Subtitle section
        rightPanel.appendChild(makeFieldLabel("Subtitle"));

        // Subtitle mode selector: Manual vs Auto Extract
        // 字幕模式选择：手动 vs 自动提取
        const subModeRow = document.createElement("div");
        subModeRow.style.cssText = "display:flex;gap:4px;margin-bottom:4px;";
        const subManualBtn = document.createElement("button");
        subManualBtn.textContent = "Manual Subtitles";
        subManualBtn.style.cssText = "flex:1;font-size:10px;padding:2px 4px;border-radius:3px;cursor:pointer;";
        const subAutoBtn = document.createElement("button");
        subAutoBtn.textContent = "Auto Extract";
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
        dlgLabel.append(dlgCheck, document.createTextNode("Dialogue"));
        const narLabel = document.createElement("label");
        narLabel.style.cssText = "display:flex;align-items:center;gap:2px;color:#c8c8c8;";
        const narCheck = document.createElement("input");
        narCheck.type = "checkbox";
        narCheck.checked = clip.subtitle_auto_narration;
        narCheck.style.cssText = "width:12px;height:12px;";
        narLabel.append(narCheck, document.createTextNode("Narration"));
        const lyrLabel = document.createElement("label");
        lyrLabel.style.cssText = "display:flex;align-items:center;gap:2px;color:#c8c8c8;";
        const lyrCheck = document.createElement("input");
        lyrCheck.type = "checkbox";
        lyrCheck.checked = clip.subtitle_auto_lyrics;
        lyrCheck.style.cssText = "width:12px;height:12px;";
        lyrLabel.append(lyrCheck, document.createTextNode("Lyrics"));
        subAutoTypes.append(dlgLabel, narLabel, lyrLabel);
        rightPanel.appendChild(subAutoTypes);

        // Auto-extract preview (read-only)
        const subAutoPreview = document.createElement("div");
        subAutoPreview.style.cssText = "display:none;width:100%;min-height:24px;max-height:60px;overflow-y:auto;background:#111;color:#8c8;border:1px solid #333;border-radius:3px;padding:4px 6px;font-size:11px;margin-bottom:4px;white-space:pre-wrap;";
        rightPanel.appendChild(subAutoPreview);

        // Manual subtitle input
        const subtitleInput = document.createElement("textarea");
        subtitleInput.value = clip.subtitle || "";
        subtitleInput.placeholder = "Enter subtitle text";
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
            subAutoPreview.textContent = extracted || "(No match)";
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
        fontLabel.textContent = "Font";
        fontLabel.style.cssText = "color:#888;margin-right:2px;";
        subCtrlRow.appendChild(fontLabel);
        const fontSelect = document.createElement("select");
        fontSelect.style.cssText = "background:#1a1a1a;color:#c8c8c8;border:1px solid #333;border-radius:3px;padding:1px 3px;font-size:11px;max-width:100px;";
        fontSelect.innerHTML = '<option value="msyh.ttc">Microsoft YaHei</option><option value="simhei.ttf">SimHei</option><option value="simsun.ttc">SimSun</option><option value="arial.ttf">Arial</option>';
        fontSelect.value = clip.subtitle_font || "msyh.ttc";
        fontSelect.addEventListener("change", () => {
            clip.subtitle_font = fontSelect.value;
            updateHidden(node, runtime);
        });
        subCtrlRow.appendChild(fontSelect);

        // Font size
        const sizeLabel = document.createElement("span");
        sizeLabel.textContent = "Size";
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
        colorLabel.textContent = "Color";
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
        boxText.textContent = "Box";
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
        boxWLabel.textContent = "Thickness";
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
        ctxLabel.textContent = "Context Reference";
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
        rfeToggle.id = `rfe_toggle_${clip.id}`;
        rfeToggle.style.cssText = "cursor:pointer;font-size:11px;color:#888;margin-top:6px;margin-bottom:3px;user-select:none;";
        rfeToggle.textContent = "▶ Ref Frame Extract";
        if (!ctxCheck.checked) rfeToggle.style.opacity = "0.5";
        let rfeExpanded = false;
        const rfeContent = document.createElement("div");
        rfeContent.id = `rfe_content_${clip.id}`;
        rfeContent.style.cssText = "display:none;padding:4px 6px;border:1px solid #333;border-radius:3px;background:#0e0e0e;margin-bottom:6px;";
        if (!ctxCheck.checked) {
            rfeContent.style.opacity = "0.4";
            rfeContent.style.pointerEvents = "none";
        }

        rfeToggle.addEventListener("click", () => {
            if (!ctxCheck.checked) return;
            rfeExpanded = !rfeExpanded;
            rfeContent.style.display = rfeExpanded ? "" : "none";
            rfeToggle.textContent = (rfeExpanded ? "▼ " : "▶ ") + "Ref Frame Extract";
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
            for (const c of runtime.state.clips) {
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

        // v2.40: 默认渲染资产 tab
        renderAssetPanel(tabContent, clip, node, runtime, prompt);

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
        runtime.cards.appendChild(card);
        return card;
    } catch (e) {
        console.error("[H3] card render skipped (v2.82):", index, e);
        return null;
    }

// v2.82 (2026-09-27): 增量懒加载 - 只构建新卡片, 不重建已渲染的。
// 每次最多追加 count 张, 主线程每次只做少量 DOM 构建, 不会出现
// 一次性构建数千节点导致页面无响应的长任务。
function renderMoreClips(node, runtime, count) {
    const clips = runtime.state?.clips;
    if (!clips || !runtime.cards) return;
    const start = Number(runtime._renderedClips) || 0;
    if (start >= clips.length) return;
    const end = Math.min(clips.length, start + Math.max(1, Number(count) || 6));
    for (let i = start; i < end; i++) {
        try { buildClipCard(node, runtime, clips[i], i); } catch (e) {
            console.error("[H3] card render skipped (v2.82):", i, e);
        }
    }
    runtime._renderedClips = end;
    try {
        // v2.88: 收起状态下保持固定高度(滚动条查看全部), 不按已构建卡片数
        // setSize(否则每次追加都会把节点高度顶起来, 破坏收起视口)。
        if (runtime._h3CollapsedAll) {
            syncDomHeight(node, runtime, true);
            return;
        }
        const w = Math.max(NODE_MIN_WIDTH, Number(node.size?.[0] || NODE_MIN_WIDTH));
        let h = NON_CARD_FIXED;
        for (let i = 0; i < end; i++) {
            const c = clips[i];
            h += c.collapsed ? COLLAPSED_CLIP_HEIGHT
                : (c.card_height > 0 ? Math.max(CARD_MIN_HEIGHT, c.card_height) : CARD_MIN_HEIGHT + CARD_SCROLLBAR_SPACE);
        }
        h += BASE_PADDING;
        if (Math.abs(Number(node.size?.[1] || 0) - h) > 4) node.setSize([w, h]);
        runtime.state.nodeHeight = h;
        syncDomHeight(node, runtime, true);
    } catch (e) {}
}

}

// v2.90: 内容指纹 - 工作流加载/连接建立/轮询会产生大量"状态未变"的
// render 调用; 每次 replaceChildren 清空重建都会反复打断分片渲染链,
// 导致 DOM 永远停在 6 张。状态未变时跳过重建(只更新状态栏/高度)。
function buildRenderFingerprint(runtime, state) {
    let fp = (runtime._h3CollapsedAll ? "c" : "e") + "|" + (runtime.activePhase || "idle") + "|" + (runtime.activeClipIndex ?? -1);
    const c = state?.clips || [];
    fp += "|n" + c.length;
    for (let i = 0; i < c.length; i++) {
        const cl = c[i] || {};
        fp += "|" + i + ":" + (cl.collapsed ? 1 : 0) + ":" + (cl.prompt ? cl.prompt.length : 0)
            + ":" + (cl.card_height || 0) + ":" + (cl._previewVideoUrl ? 1 : 0)
            + ":" + (cl._latentStep || 0) + ":" + (cl._renderComplete ? 1 : 0);
    }
    return fp;
}

function render(node, runtime, opts) {
    const { state, cards, counter, status } = runtime;
    renderReferences(node, runtime);

    // Sync global_prompt from connected external input
    syncGlobalPromptFromInput(node, runtime);

    // v2.90: 指纹去重 - 状态未变的重复 render 直接跳过, 不打断分片链。
    const _fp = buildRenderFingerprint(runtime, state);
    if (runtime._renderFingerprint === _fp) {
        try {
            status.textContent = runtime.statusText || "Ready";
            if (runtime.clipsTotalLabel) {
                const _td = state.clips.reduce((s2, c2) => s2 + (Number(c2.duration) || 0), 0);
                runtime.clipsTotalLabel.textContent = `CLIPS | total ${_td}s (${state.clips.length} clip${state.clips.length > 1 ? "s" : ""})`;
            }
            syncDomHeight(node, runtime, true);
        } catch (e) {}
        return;
    }
    runtime._renderFingerprint = _fp;

    cards.replaceChildren();

    counter.textContent = `${state.clips.length} clip${state.clips.length > 1 ? "s" : ""} • ${refCount(runtime)} ref${refCount(runtime) === 1 ? "" : "s"}`;
    status.textContent = runtime.statusText || "Ready";

    // Update CLIPS total duration label at the bottom
    if (runtime.clipsTotalLabel) {
        const totalDur = state.clips.reduce((sum, c) => sum + (Number(c.duration) || 0), 0);
        const n = state.clips.length;
        runtime.clipsTotalLabel.textContent = `CLIPS | total ${totalDur}s (${n} clip${n > 1 ? "s" : ""})`;
    }

    // Highlight merge output button when a merge is pending
    if (runtime.mergeOutputBtn) {
        const pendingMerge = String(runtime.statusText || "").includes("pending merge");
        if (pendingMerge) {
            runtime.mergeOutputBtn.style.background = "#4a8a4a";
            runtime.mergeOutputBtn.style.borderColor = "#5a9a5a";
            runtime.mergeOutputBtn.style.boxShadow = "0 0 8px rgba(80,200,80,.4)";
            setBtnText(runtime.mergeOutputBtn, "Merge Output", "", { icon: "⚡", bg: "#4a8a4a", border: "#5a9a5a", color: "#cde" });
        } else {
            runtime.mergeOutputBtn.style.background = "#2a6a3a";
            runtime.mergeOutputBtn.style.borderColor = "#3a7a4a";
            runtime.mergeOutputBtn.style.boxShadow = "none";
            setBtnText(runtime.mergeOutputBtn, "Merge Output", "", { bg: "#2a6a3a", border: "#3a7a4a", color: "#cde" });
        }
    }

    // v2.76 (2026-09-27): 分片渲染加固。
    // 1) runtime._renderSeq 递增: 每次 render 使旧分片链自动停止, 杜绝
    //    onNodeCreated/onConfigure 两套链并发导致卡片缺失/重复。
    // 2) 单卡片 try/catch: 某张卡片构建抛错只跳过该卡片, 不中断整批。
    // 3) finally 保证下一批总是注册: 链不会因异常断掉, 最终必然补全全部卡片。
    runtime._renderSeq = (runtime._renderSeq || 0) + 1;
    const _renderSeq = runtime._renderSeq;
    const _renderChunkSize = 6;
    let _renderIdx = 0;
    // v2.88: limit 明确时按 limit; 无 limit 时全量。runtime._renderedClips
    // 始终表示"实际已构建卡片数"(每批构建后更新), 不再预设为目标数 -
    // 否则 DOM 只构建 6 张后 renderMoreClips/兜底会因 start>=len 永久失效。
    const _renderTotal = Math.min(state.clips.length, Number(opts?.limit) > 0 ? opts.limit : state.clips.length);
    runtime._renderedClips = 0;
    // v2.89: 防抖最终补全 - 每次 render 重置; 2 秒无新 render 后一次性补全
    // 剩余卡片。无论被多少异步 render 反复打断(预览/资产/事件), 最终 DOM
    // 都会完整 31 张, 滚动条可查看全部。
    if (runtime._renderFinalTimer) clearTimeout(runtime._renderFinalTimer);
    runtime._renderFinalTimer = setTimeout(() => {
        try {
            const _cur = runtime._renderedClips || 0;
            const _allF = state.clips.length;
            if (_cur < _allF) renderMoreClips(node, runtime, _allF - _cur);
        } catch (e) {}
    }, 2000);

        const _buildChunk = () => {
            if (runtime._renderSeq !== _renderSeq) return;
            const _end = Math.min(_renderIdx + _renderChunkSize, _renderTotal);
            try {
                for (; _renderIdx < _end; _renderIdx++) {
                    try {
                        buildClipCard(node, runtime, state.clips[_renderIdx], _renderIdx);
                    } catch (e) {
                        console.error("[H3] card render skipped (v2.82):", _renderIdx, e);
                    }
                }
                // v2.88: 每批构建后同步实际已构建数(renderMoreClips/兜底据此判断)
                runtime._renderedClips = _renderIdx;
        } finally {
            // v2.91: 统一分片推进 - 去掉 opts?.chunked 条件。此前无 opts 的
            // render(连接建立/轮询等占绝大多数)只构建第一批 6 张就停止,
            // 这是"DOM 永远停在 6 张"的直接原因。现在任何 render 都会
            // rAF+setTimeout 双保险分片推进, 最终必然补全全部卡片。
            if (_renderIdx < _renderTotal && runtime._renderSeq === _renderSeq) {
                // v2.78 (2026-09-27): rAF + setTimeout 双保险。
                // rAF 在页面节能/被判定无响应期间可能长时间不触发, 导致链条停在
                // 前 6 张卡片。setTimeout 400ms 兜底: 若 rAF 未推进则强制继续,
                // 保证全部卡片最终必然补全(每批最多延迟 400ms, 31 张约 2.4s)。
                requestAnimationFrame(_buildChunk);
                if (!runtime._renderTimeoutArmed) {
                    runtime._renderTimeoutArmed = true;
                    setTimeout(() => {
                        runtime._renderTimeoutArmed = false;
                        if (runtime._renderSeq === _renderSeq && _renderIdx < _renderTotal) {
                            try { _buildChunk(); } catch (e) {}
                        }
                    }, 400);
                }
            }
        }
    };
    _buildChunk();

    requestAnimationFrame(() => syncDomHeight(node, runtime, false));
    requestAnimationFrame(() => positionClipPorts(node, runtime));
    requestAnimationFrame(() => syncExternalPrompts(node, runtime));
    // v2.24 (2026-09-20 fix): 去掉了每次 render 后自动调用 autoGrowNodeToFitAllClips,
    // 因为会形成循环: render → 撑大 → 又触发 render → 又撑大...
    // 导致外部提示词没输入时黑色面板自己慢慢在撑大.
    // 只在输入/删除外部提示词后才调整高度 (见统一刷新按钮逻辑).
}

function positionClipPorts(node, runtime) {
    // Dynamic 12-port layout: only the ports matching the current number of
    // CLIP cards are visible in the default input slot list; the rest are
    // parked off-canvas so the node does not grow tall with 12 stacked rows
    // (user: "乱套了" - node got too tall). Ports reappear as soon as more
    // CLIP cards exist. Already-established links are untouched.
    if (!node || !node.inputs) return;
    const need = Math.max(0, Math.min(12, (runtime.state?.clips || []).length || 0));
    node.inputs.forEach((inp) => {
        const m = /^clip_prompt_(\d+)$/.exec(inp.name || "");
        if (!m) return;
        const idx = Number(m[1]);
        // Show port if it's within card range OR already connected
        const isConnected = inp.link != null;
        if (idx <= need || isConnected) {
            if (inp.pos) inp.pos = undefined;
            if (inp.label === " ") inp.label = "clip_prompt_" + idx;
            if (inp.localized_name === " ") inp.localized_name = undefined;
        } else {
            if (!inp.pos) inp.pos = [0, -9999];
        }
    });
}

// Read the text currently flowing into a connected clip_prompt_N input from
// its upstream node (PrimitiveNode text widget, or a node output cached after
// execution). Returns null when nothing usable is available yet.
window.__h3ExtenderVersion = "node-size-persist";

// --- diagnostic counters (removable) ---
function h3diag(sync) {
    if (sync) {
        window.__h3SyncCalls = (window.__h3SyncCalls || 0) + 1;
        window.__h3LastSyncAt = Date.now();
    }
}
function readUpstreamText(node, graph, input) {
    if (!input || !input.link) return null;
    const link = graph && graph.links ? graph.links[input.link] : null;
    if (!link) return null;
    const up = graph._nodes_by_id ? graph._nodes_by_id[link.origin_id] : null;
    if (!up) return null;
    // 1) Live widget values first: text-ish widgets (PrimitiveString,
    // PrimitiveStringMultiline, etc.) update as the user types, so reading
    // them keeps the CLIP card in lock-step with edits. Output caches would
    // hold the stale value from graph load.
    const ws = up.widgets || [];
    for (const wd of ws) {
        if (typeof wd.value === "string" && /text|prompt|string|value|output/i.test(wd.name || "")) {
            window.__h3LastRead = "w:" + String(wd.value).slice(0, 30);
            return wd.value; // may be "" -> upstream explicitly cleared
        }
    }
    // 2) Execution outputs (prompt-reversal / text-generator nodes) only when
    // the upstream has no text-ish widget to read live.
    const out = up.outputs && up.outputs[link.origin_slot];
    if (out) {
        const v = out._data != null ? out._data : (out.value != null ? out.value : null);
        if (v != null) {
            window.__h3LastRead = "o:" + String(v).slice(0, 30);
            return String(v); // may be "" -> upstream explicitly cleared
        }
    }
    window.__h3LastRead = "NULL";
    return null;
}

// Whether the upstream node feeding `input` ever held non-empty text (user
// typed/pasted something at least once). Distinguishes "user cleared the
// external prompt" from "an empty node was connected and never used".
function upstreamEverHadContent(node, graph, input) {
    if (!input || !input.link || !graph || !graph.links) return false;
    const link = graph.links[input.link];
    if (!link) return false;
    const up = graph._nodes_by_id ? graph._nodes_by_id[link.origin_id] : null;
    if (!up || !up.widgets) return false;
    for (const wd of up.widgets) {
        if (typeof wd.value === "string" || wd.type === "customtext" || wd.type === "text" || /text|prompt|string|value|output/i.test(wd.name || "")) {
            if (wd.__h3HadNonEmpty === true) return true;
        }
    }
    return false;
}

// Event-driven sync: wrap the upstream text widget's callback so every real
// edit (typing, paste, clear) pushes the new value into every connected CLIP
// card at once. ComfyUI calls widget.callback on each value change, so this
// path is independent of polling and of any cached output values.
function hookUpstreamWidgetCallback(node, runtime) {
    const graph = node && node.graph;
    if (!graph || !node.inputs || !runtime?.state) return;
    node.inputs.forEach((inp) => {
        const m = /^clip_prompt_(\d+)$/.exec(inp.name || "");
        if (!m || !inp.link) return;
        const link = graph.links && graph.links[inp.link];
        if (!link) return;
        const up = graph._nodes_by_id ? graph._nodes_by_id[link.origin_id] : null;
        if (!up || !up.widgets) return;
        for (const wd of up.widgets) {
            if (!(typeof wd.value === "string" || wd.type === "customtext" || wd.type === "text" || /text|prompt|string|value|output/i.test(wd.name || ""))) continue;
            if (wd.__h3Hooked) { wd.__h3HookedSync = wd.__h3HookedSync || []; if (!wd.__h3HookedSync.includes(node.id)) wd.__h3HookedSync.push(node.id); break; }
            wd.__h3Hooked = true;
            wd.__h3HookedSync = [node.id];
            const orig = wd.callback;
            wd.callback = function (value, canvas, nd, pos) {
                if (typeof orig === "function") { try { orig.apply(this, arguments); } catch (e) {} }
                try {
                    const appObj = window.comfyAPI && window.comfyAPI.app && window.comfyAPI.app.app;
                    const g = appObj && appObj.graph;
                    if (!g) return;
                    const newVal = value != null ? String(value) : (this && this.value != null ? String(this.value) : "");
                    // Remember whether the upstream ever held non-empty content.
                    // An always-empty upstream (user never typed anything) must
                    // NOT clear a CLIP card filled by global storyboard parsing;
                    // only a real "was non-empty -> now cleared" should clear it.
                    if (newVal && newVal.trim()) wd.__h3HadNonEmpty = true;
                    const srcId = nd ? nd.id : null;
                    const touched = [];
                    g._nodes.forEach((h3n) => {
                        if (!h3n || h3n.type !== "BSAIH3FilmFactory" || !h3n.__h3Extender) return;
                        let changed = false;
                        (h3n.inputs || []).forEach((i2) => {
                            const m2 = /^clip_prompt_(\d+)$/.exec(i2.name || "");
                            if (!m2 || !i2.link) return;
                            const l2 = g.links && g.links[i2.link];
                            if (!l2 || l2.origin_id !== srcId) return;
                            const cl = h3n.__h3Extender.state && h3n.__h3Extender.state.clips && h3n.__h3Extender.state.clips[Number(m2[1]) - 1];
                            if (cl && applyExternalClipValue(cl, newVal, wd.__h3HadNonEmpty === true)) changed = true;
                        });
                        if (changed) touched.push(h3n);
                    });
                    // Rebuild card DOM so the change is visible immediately.
                    touched.forEach((h3n) => {
                        try { render(h3n, h3n.__h3Extender); /* v2.25: 去掉 autoGrowNodeToFitAllClips, 防止每 500ms 自动撑大 */ } catch (e2) {}
                    });
                } catch (e) {}
            };
            break;
        }
    });
}

// Keep each CLIP card's prompt textarea in sync with its connected external
// clip_prompt_N input. Runs on a 500ms timer so edits on the upstream node
// (e.g. prompt-reversal output) propagate into the card automatically. On
// disconnect the builtin prompt is restored.
function syncExternalPrompts(node, runtime) {
    h3diag(true);
    if (!node || !node.inputs || !runtime?.state) return;
    const graph = node.graph;
    if (!graph) return;
    // v2.68 perf: fast-path — no connected clip_prompt_N ports, skip all work.
    let hasConnected = false;
    for (const inp of node.inputs) {
        if (/^clip_prompt_\d+$/.test(inp.name || "") && inp.link != null) { hasConnected = true; break; }
    }
    if (!hasConnected) {
        positionClipPorts(node, runtime);
        return;
    }
    hookUpstreamWidgetCallback(node, runtime);
    let changed = false;
    node.inputs.forEach((inp) => {
        const m = /^clip_prompt_(\d+)$/.exec(inp.name || "");
        if (!m) return;
        const idx = Number(m[1]) - 1;
        // Auto-create CLIP cards to match connected clip_prompt_N ports
        if (inp.link != null) {
            while (runtime.state.clips.length <= idx) {
                runtime.state.clips.push(newClip(runtime.state.clips.length));
                changed = true;
            }
        }
        const clip = runtime.state.clips && runtime.state.clips[idx];
        if (!clip) return;
        // v14.137: 标记"这张卡由已连接的 clip_prompt_N 端口驱动"。端口后续断开时
        // 不清除该标记, 让下面的空卡回收逻辑仍能收拾它; 反过来, 端口从未连接的卡
        // (用户点"添加CLIP"新建的空卡) 永远不带这个标记, 不会被当成垃圾清掉。
        if (inp.link != null) clip._h3ExtDriven = true;
        const val = readUpstreamText(node, graph, inp);
        if (val !== null) {
            if (val === "") {
                // Upstream text was cleared. Only clear the card when the
                // upstream really held non-empty content before (user cleared
                // it) OR this card already received external content. An
                // always-empty upstream must not wipe a card filled by global
                // storyboard parsing.
                const everHad = !clip._storyboardFilled && (upstreamEverHadContent(node, graph, inp) || clip.external_prompt != null);
                if (everHad && (clip.external_prompt != null || clip.prompt)) {
                    delete clip.external_prompt;
                    delete clip.builtin_prompt;
                    clip.prompt = "";
                    if (clip._promptEl && clip._promptEl.value !== "") clip._promptEl.value = "";
                    changed = true;
                }
            } else if (clip.external_prompt !== val) {
                // External non-empty value takes over; lift the storyboard lock.
                clip._storyboardFilled = false;
                if (!clip.builtin_prompt && clip.prompt && clip.prompt !== val) clip.builtin_prompt = clip.prompt;
                clip.external_prompt = val;
                clip.prompt = val;
                if (clip._promptEl && clip._promptEl.value !== val) clip._promptEl.value = val;
                changed = true;
            }
        } else if (!inp.link && clip.external_prompt) {
            // disconnected -> restore the builtin prompt
            if (clip.builtin_prompt) clip.prompt = clip.builtin_prompt;
            delete clip.external_prompt;
            delete clip.builtin_prompt;
            if (clip._promptEl && clip._promptEl.value !== clip.prompt) clip._promptEl.value = clip.prompt;
            changed = true;
        }
    });

    // v2.2 + v14.137: 空CLIP自动清理 — 从后往前删, 只删"由已连接的 clip_prompt_N
    // 端口驱动、且内容已清空"的卡片。CLIP1(idx=0) 永远保留, 永不删除。
    // v14.137 根因修复: 原来无条件删除任何空卡, 而 newClip() 生成的 prompt 就是
    // 空字符串 —— 于是"添加CLIP"新建的第 3 张卡在同一个 rAF 里就被这里 splice 掉,
    // 表现为"点多少次都加不出第 3 个 CLIP"(只保留有外部提示词的旧卡)。
    for (let idx = runtime.state.clips.length - 1; idx > 0; idx--) {
        const clip = runtime.state.clips[idx];
        if (clip._h3ExtDriven !== true) continue;
        const promptEmpty = !clip.prompt || !clip.prompt.trim();
        const externalEmpty = !clip.external_prompt || !clip.external_prompt.trim();
        if (promptEmpty && externalEmpty) {
            runtime.state.clips.splice(idx, 1);
            changed = true;
        }
    }

    // A real value change must be reflected in the card DOM. Direct .value
    // writes are not reliably visible on every render path; rebuilding the
    // card list is what makes the new text appear (same as the Sync All
    // button). Only happens when a value actually changed.
    if (changed) {
        try { updateHidden(node, runtime); } catch (e) {}
        try { render(node, runtime); } catch (e) {}
        // v2.26 (2026-09-20 fix): 外部提示词真正变化时才自动调整节点高度:
        // - 输入外部提示词 → CLIP 变多 → 自动撑大显示全部 CLIP
        // - 删除外部提示词 → CLIP 变少 → 自动缩小, 不留黑色空白
        // 只有 changed=true 才调用, 不会每 500ms 都撑大.
        try { autoGrowNodeToFitAllClips(node, runtime); } catch (e) {}
    }
}

// Apply an external prompt value onto a CLIP card (shared by all sync paths).
// allowClear guards the empty branch: a card filled by global storyboard
// parsing is only cleared when the upstream genuinely held content before
// (user cleared it), never by an always-empty upstream node.
function applyExternalClipValue(clip, val, allowClear) {
    if (!clip || val == null) return false;
    const text = String(val);
    if (clip.external_prompt === text) return false;
    if (text === "") {
        // A card filled by global storyboard parsing stays until an external
        // non-empty value takes over; an empty upstream must not wipe it.
        if (clip._storyboardFilled) return false;
        if (!(allowClear === true || clip.external_prompt != null)) return false;
        // upstream cleared -> clear the card to match
        delete clip.external_prompt;
        delete clip.builtin_prompt;
        clip.prompt = "";
        if (clip._promptEl && clip._promptEl.value !== "") clip._promptEl.value = "";
        return true;
    }
    // External non-empty value takes over the card.
    clip._storyboardFilled = false;
    if (!clip.builtin_prompt && clip.prompt && clip.prompt !== text) clip.builtin_prompt = clip.prompt;
    clip.external_prompt = text;
    clip.prompt = text;
    if (clip._promptEl && clip._promptEl.value !== text) clip._promptEl.value = text;
    return true;
}

// After a node executes, ComfyUI fires "executed" on the frontend API with the
// node's output. Prompt-reversal / text nodes (e.g. Muye 提示词反推及扩写) only
// produce their text at execution time, so this is the reliable path to sync
// their result into the connected CLIP card prompt.
function hookExecutedSync() {
    const apiObj = window.comfyAPI?.api?.api;
    if (!apiObj || window.__h3ExecSyncHooked) return;
    window.__h3ExecSyncHooked = true;
    apiObj.addEventListener("executed", (ev) => {
        try {
            const d = ev.detail;
            if (!d || d.node == null || d.output == null) return;
            const appObj = window.comfyAPI?.app?.app;
            const graph = appObj && appObj.graph;
            if (!graph) return;
            const nodeId = Number(d.node);
            const nodes = graph._nodes || [];
            for (const n of nodes) {
                if (!n || n.type !== "BSAIH3FilmFactory" || !n.__h3Extender) continue;
                const rt = n.__h3Extender;
                (n.inputs || []).forEach((inp) => {
                    const m = /^clip_prompt_(\d+)$/.exec(inp.name || "");
                    if (!m || !inp.link) return;
                    const link = graph.links && graph.links[inp.link];
                    if (!link || link.origin_id !== nodeId) return;
                    const clip = rt.state && rt.state.clips && rt.state.clips[Number(m[1]) - 1];
                    if (!clip) return;
                    const raw = d.output && d.output[0];
                    let val = null;
                    if (Array.isArray(raw)) { if (raw.length) val = raw[0]; }
                    else if (raw != null) val = raw;
                    if (val != null) applyExternalClipValue(clip, val);
                });
            }
        } catch (e) {}
    });
}

// Execution-type sources (prompt reversal, text generators, custom nodes)
// produce their text only server-side. After a run completes, pull the latest
// history (standard /history API) and write the upstream outputs into the
// connected CLIP cards. This is what makes "点刷新 / Sync All" and "每次反推
// 执行完自动同步" work.
async function syncFromHistory() {
    try {
        const res = await fetch("/history?max_items=2");
        if (!res.ok) return;
        const hist = await res.json();
        const appObj = window.comfyAPI?.app?.app;
        const graph = appObj && appObj.graph;
        if (!graph || !hist) return;
        const h3Nodes = (graph._nodes || []).filter((n) => n && n.type === "BSAIH3FilmFactory" && n.__h3Extender);
        if (!h3Nodes.length) return;
        // map origin node id+slot -> clip (node idx)
        const targets = [];
        for (const n of h3Nodes) {
            (n.inputs || []).forEach((inp) => {
                const m = /^clip_prompt_(\d+)$/.exec(inp.name || "");
                if (!m || !inp.link) return;
                const link = graph.links && graph.links[inp.link];
                if (!link) return;
                targets.push({ originId: Number(link.origin_id), slot: Number(link.origin_slot), node: n, clipIdx: Number(m[1]) - 1 });
            });
        }
        if (!targets.length) return;
        for (const entry of Object.values(hist)) {
            const outputs = entry && entry.outputs;
            if (!outputs) continue;
            let any = false;
            for (const t of targets) {
                const out = outputs[t.originId];
                if (!out || !out.outputs) continue;
                const raw = out.outputs[t.slot];
                let val = null;
                if (Array.isArray(raw)) { if (raw.length) val = raw[0]; }
                else if (raw != null) val = raw;
                if (val == null) continue;
                const clip = t.node.__h3Extender.state && t.node.__h3Extender.state.clips && t.node.__h3Extender.state.clips[t.clipIdx];
                if (clip && applyExternalClipValue(clip, val)) any = true;
            }
            if (any) break;
        }
    } catch (e) {}
}

// Module-level fallback poller: runs independent of any per-node closure
// timer. Every 500ms it walks the current graph and syncs every H3 node's
// per-CLIP external prompt ports, so upstream text edits / deletions reach
// the card prompt even if a node-local timer was never created or its closure
// captured a stale reference.
function ensureGlobalSyncPoll() {
    if (window.__h3GlobalSyncPoll) return;
    // v2.52 (2026-09-20 perf fix): 全局定时器从 2000ms 改成 4000ms,
    // 进一步减少遍历所有节点的频率, 拖动画布更流畅.
    window.__h3GlobalSyncPoll = setInterval(() => {
        try {
            const appObj = window.comfyAPI?.app?.app;
            const g = appObj && appObj.graph;
            if (!g || !g._nodes) return;
            for (const n of g._nodes) {
                if (!n || n.type !== "BSAIH3FilmFactory" || !n.__h3Extender) continue;
                try { positionClipPorts(n, n.__h3Extender); } catch (e) {}
                try { syncExternalPrompts(n, n.__h3Extender); } catch (e) {}
                try { syncGlobalPromptFromInput(n, n.__h3Extender); } catch (e) {}
                // v2.14: 源剧本实时变化导致 CLIP 重建后, render + 自动撑高
                try {
                    const rtD = n.__h3Extender;
                    if (rtD && rtD._sourceClipsDirty) {
                        rtD._sourceClipsDirty = false;
                        render(n, rtD);
                        /* v2.25: 去掉 autoGrowNodeToFitAllClips, 防止自动撑大 */
                    }
                } catch (e) {}
                // v2.122: 移除 v2.117e 轮询兜底强制 — 对口型模式下"上下文参考"
                // 恢复用户手动控制, 音频同步由后端三件套保证(切分重叠/尾对齐注入/
                // 解码跳过重叠), 不再强制关闭所有 CLIP 的 context_enabled。
                // Persist the user-adjusted node height so a page refresh or
                // ComfyUI restart restores the exact last layout, including
                // every CLIP card's share of the node body.
                // v2.105 (fix): 收起态跳过持久化 - 收起视口由 syncDomHeight
                // 统一按 1 卡计算; 若把旧的展开大高度写回 nodeHeight 并置
                // _userResize, syncDomHeight 收起分支会跟随 node.size 又撑开
                // (刷新后"刚收回 1 卡又自动脱离回 3 卡空白")。
                try {
                    const rt = n.__h3Extender;
                    if (rt && rt.state && !rt._h3CollapsedAll) {
                        const h = Number(n.size?.[1] || 0);
                        if (Number.isFinite(h) && h > 100 && h < 100000 && h !== rt._lastNodeHeight) {
                            rt._lastNodeHeight = h;
                            if (Number(rt.state.nodeHeight || 0) !== h) {
                                rt.state.nodeHeight = h;
                                updateHidden(n, rt);
                                rt._userResize = true;
                                try { syncDomHeight(n, rt); } catch (e) {}
                            }
                        }
                    }
                } catch (e) {}
            }
        } catch (e) {}
    }, 8000);
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
        // v2.28 (2026-09-20 fix): bodyMinH 直接用当前 CLIP 数量计算的高度,
        // 不用旧的 savedNodeH (Math.max 会导致 CLIP 变少后节点高度永远缩不回去).
        // 自动调整: 输入外部提示词后 CLIP 变多 → 自动撑大; 删除后 CLIP 变少 → 自动缩小.
        const bodyMinH = dynMinH;
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
        // v2.69: collapsed mode root.minHeight = actual collapsed content height,
        // not bodyMinH (which includes the hidden 200px global prompt area).
        if (runtime._h3CollapsedAll) {
            const _vhNow = collapsedViewportH(runtime);
            const _padTopNow = 5 + NODES2_TOP_GAP;
            runtime.root.style.minHeight = `${_padTopNow + TOOLBAR_HEIGHT + _vhNow + BOTTOM_BAR_HEIGHT + 6}px`;
            runtime.root.style.setProperty("--comfy-widget-min-height", `${_padTopNow + TOOLBAR_HEIGHT + _vhNow + BOTTOM_BAR_HEIGHT + 6}px`);
        } else {            runtime.root.style.minHeight = `${bodyMinH}px`;
            runtime.root.style.setProperty("--comfy-widget-min-height", `${bodyMinH}px`);
        }
        runtime.root.style.maxHeight = "none";
        runtime.root.style.flex = "1 1 auto";
        runtime.root.style.paddingTop = `${5 + NODES2_TOP_GAP}px`;
        // Avoid a second vertical clipping boundary at fractional canvas zooms.
        // Horizontal clipping/scrolling is still owned by `cards`.
        runtime.root.style.overflow = "visible";

        // v2.87: 收起状态(_h3CollapsedAll)下 root 固定高度 + overflow hidden,
        // cards 固定高度 + 纵向滚动条(用户可滚动查看全部; 手动拉长节点视口跟随);
        // 展开时恢复 auto 高度(全部显示)。仅设 cards 高度不够 - nodes2 下
        // root 若保持 height:auto, 31 张卡片会把节点撑到 13284px, 收起失效。
        if (runtime._h3CollapsedAll) {
            // v2.69 fix: 收起态 cards 高度永远 = collapsedViewportH(1卡视口),
            // 不跟随 node.size / _userResize。之前 _userResize=true 时读
            // node.size-285, 旧大高度(1280)让 cards=995px 空壳, root auto 高度
            // 跟着撑到 1080, 但 node.size 被设成 500, bottombar 被甩到节点外。
            const _vh = collapsedViewportH(runtime);
            // v2.108: 收起 CLIP 不再隐藏全局提示词区 — 显隐只由用户折叠标志决定。
            applyGlobalPromptVisibility(runtime);
            // v2.69: root 高度 auto — cards 已固定 _vh, root 自然高 = padding + toolbar + cards + bottombar.
            // 不能设死 root.height: root 高度 > node.size 会把 native widgets(分辨率/步长/CFG)压成 0.
            runtime.root.style.height = "auto";
            runtime.root.style.overflow = "hidden";
            runtime.cards.style.height = `${_vh}px`;
            runtime.cards.style.overflowY = "auto";
            runtime.cards.style.flex = "0 0 auto";  /* don't stretch in flex column */
            runtime.domHeight = _vh;
        } else {
            // v2.108: 展开态同样只由用户折叠标志决定显隐。
            applyGlobalPromptVisibility(runtime);
            runtime.root.style.height = "auto";
            runtime.root.style.overflow = "visible";
            runtime.cards.style.height = "auto";
            runtime.cards.style.overflowY = "visible";
        }
        runtime.cards.style.flex = "1 1 auto";
        runtime.cards.style.minHeight = `${Math.max(COLLAPSED_MIN_HEIGHT, bodyMinH - NON_CARD_FIXED)}px`;
        runtime.cards.style.maxHeight = "none";
        return;
    }

    const curLegacyH = Number(node.size?.[1] || 0);
    // v2.98e: legacyMinH 提前计算 - y<=0 兜底也要用收起目标值(而不是残留的
    // 旧 domHeight), 否则展开/收起切换瞬间 last_y 为 0 时, 兜底会用上次展开
    // 残留的大 domHeight(如 1829)恢复出 2114px 大底板, 卡片溢出到底板外。
    const legacyMinH = calculateMinHeight(runtime);
    const yRaw = Number(runtime.domWidget.last_y);
    // A last_y far beyond the current node height is a poisoned layout value
    // (runaway feedback). Treat it as absent so minNodeH is computed from the
    // real content minimum instead of amplifying the corruption.
    const y = (Number.isFinite(yRaw) && yRaw > 0 && yRaw < Math.max(1, curLegacyH) * 1.5)
        ? yRaw
        : 0;
    if (!Number.isFinite(y) || y <= 0) {
        // v2.105 (fix): 收起态下 last_y 为 0/未布局时不能直接 return ——
        // 否则收起固定(下方 root/cards 高度 + node.size)完全不执行, 节点
        // 保持工作流保存的巨大高度(如 12881px), DOM widget 被定位到画布
        // 可视区外: "节点存在但 CLIP 区域消失, 移动/缩小画布又出现"。
        // 收起态直接走下方收起分支(不依赖 last_y); 非收起态才重试等待布局。
        if (!runtime._h3CollapsedAll) {
            if (retry < 12) {
                requestAnimationFrame(() => syncDomHeight(node, runtime, forceMin, retry + 1));
            }
            return;
        }
    }

    // Remove Nodes 2.0-only intrinsic sizing when returning to Legacy.
    runtime.root.style.paddingTop = "5px";
    runtime.root.style.minHeight = "0";
    runtime.root.style.setProperty("--comfy-widget-min-height", `${legacyMinH}px`);
    runtime.root.style.maxHeight = "none";
    runtime.root.style.flex = "0 0 auto";
    runtime.root.style.overflow = "visible";

    runtime.syncingDomHeight = true;
    try {
        let w = Math.max(NODE_MIN_WIDTH, Number(node.size?.[0] || NODE_MIN_WIDTH));
        let h = Number(node.size?.[1] || 0);
        const minNodeH = y + legacyMinH + BOTTOM_PAD;

        // v2.92: 收起固定(legacy 分支) - 实测本环境 domWidgetRenderMode 判定为
        // legacy(nodes2 分支的收起逻辑不执行, root 高度跟随节点被撑到 9401)。
        // 收起时 root/cards 固定为 CLIP1 视口 + 纵向滚动条(滚动查看全部 31 张)。
        if (runtime._h3CollapsedAll) {
            // v2.94: 默认固定 CLIP1 视口(legacyMinH-285); 仅用户手动拖拽(_userResize,
            // afterResize 钩子置位)时跟随 node.size - 拉多少显示多少。
            // 初始 setSize 必须固定, 否则 setSize->getHeight 正反馈把节点撑回全高。
            // v2.105 (fix): 默认(非拖拽)视口 = 1 张 CLIP 卡片的实际高度,
            // 拖拽跟随 size(拉多少显示多少, 可小于 1 卡)
            const _vh2 = runtime._userResize
                ? Math.max(COLLAPSED_MIN_HEIGHT, Number(node.size?.[1] || 0) - NON_CARD_FIXED)
                : collapsedViewportH(runtime);
            // v2.108: 收起 CLIP 不再隐藏全局提示词区 — 显隐只由用户折叠标志决定。
            // v2.109: 高度改为实测 root.scrollHeight(不再手工加总漏项), 否则
            // overflow:hidden 会把 bottomBar 整条裁掉。详见 applyCollapsedLayout 注释。
            const _contentH = applyCollapsedLayout(runtime, _vh2);
            const _w3 = Math.max(NODE_MIN_WIDTH, Number(node.size?.[0] || NODE_MIN_WIDTH));
            // v2.69 fix: node.size[1] = native widgets高度(y) + root内容高度(_contentH)。
            // 之前只设 _contentH(root-only ~464px), 漏掉 native widgets(~600px),
            // 导致 root DOM 在 y=600 但节点背景只画到 y=464, root 全部溢出节点外。
            const _targetH3 = y + _contentH;
            if (Math.abs(Number(node.size?.[1] || 0) - _targetH3) > 4) {
                node.size = [_w3, _targetH3];
                node.graph?.setDirtyCanvas(true, true);
            }
            runtime.state.nodeHeight = _targetH3;
            runtime.lastRenderMode = "legacy";
            node.graph?.setDirtyCanvas(true, true);
            return;
        }

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
        } else if (obviouslyPoisonedHeight(h, legacyMinH) && !runtime._userResize) {
            // Heal workflows that were opened directly in Legacy after an older
            // version serialized an absurd height (baseline: real content
            // minimum, not the possibly-poisoned y-derived minNodeH).
            // v2.10: 用户手动拉大节点(afterResize)时不弹回, 保留拉大看更多 CLIP.
            // v2.18: calculateMinHeight 只算 DEFAULT_MIN_VISIBLE_CLIPS 个卡片,
            // 导致 30 个 CLIP 撑出来的合法高高度被误判中毒弹回 CLIP1.
            // legacyNodeHeight 是 syncDomHeight 自己在 _userResize 路径存下的
            // (autoGrow 或用户拖出), 存了就代表已接受; 当前高度和它接近就保留.
            const remembered = Number(runtime.legacyNodeHeight);
            if (Number.isFinite(remembered) && remembered > 0 &&
                Math.abs(h - remembered) < Math.max(200, remembered * 0.1)) {
                // keep h
            } else {
                h = minNodeH;
            }
        } else if (forceMin && h < minNodeH) {
            h = minNodeH;
        }
        // v2.22 (2026-09-20 fix): 去掉了之前加的"自动缩小"逻辑,
        // 因为它会把 autoGrowNodeToFitAllClips 刚撑大的节点又缩小回去,
        // 导致输入外部提示词后节点不自动撑大.
        // 删除外部提示词后节点不自动缩小的问题, 由 autoGrowNodeToFitAllClips
        // 在下次 render 时重新量 scrollHeight 来解决.

        if (w !== Number(node.size?.[0]) || h !== Number(node.size?.[1])) {
            node.setSize([w, h]);
        }

        const actualH = Number(node.size?.[1] || h);
        const available = Math.max(legacyMinH, actualH - y - BOTTOM_PAD);
        // v2.105: 展开态 root/cards 恢复 auto - 内容全高撑起节点, 黑色底板
        // 跟随全部 CLIP; 之前固定为 node.size-285 视口导致 31 卡内容溢出
        // 到底板外(用户看到"底板只显示一部分").
        // v2.108: 全局提示词区显隐只由用户折叠标志决定, 与 CLIP 收起/展开解耦。
        applyGlobalPromptVisibility(runtime);
        runtime.root.style.height = "auto";
        // v2.98: 展开(非收起)路径明确 overflow 可见 - 不清空会残留收起时的
        // auto/visible 状态, 展开后仍有滚动条; root 也明确 visible(内容跟随
        // node.size 全显示)。v2.110: 这两行必须在实测 scrollHeight 之前设好,
        // 让测量在最终样式下进行。
        runtime.root.style.overflow = "visible";
        runtime.cards.style.height = "auto";
        runtime.cards.style.overflowY = "visible";
        // v2.110 (2026-09-29 fix): cards 固定为 0 0 auto(自然高度, 不拉伸)。
        // 之前 1 1 auto 会让 cards 在 root 里被拉伸, 实测 scrollHeight 不再等于
        // 真实内容高, 换算出的 node.size 偏小 -> 黑色底板盖不住节点底部
        // (节点外框在原生 widgets 之后就结束, toolbar/提示词区/CLIP 卡片/
        //  底部按钮栏全部溢出到框外)。
        runtime.cards.style.flex = "0 0 auto";
        runtime.cards.style.minHeight = "";
        runtime.cards.style.maxHeight = "none";
        // v2.110: 高度改为实测(与收起态 applyCollapsedLayout 同构)。
        // 旧写法 `domHeight = max(available, rootFullH - NON_CARD_FIXED)` 再
        // `+ NON_CARD_FIXED` 绕了一圈: NON_CARD_FIXED=285 是估值常量
        // (toolbar 50 + 提示词区 200 + 底栏 35), 与真实内容无关, 换算结果
        // 既可能偏大也可能偏小; 而且读 scrollHeight 前没强制 reflow, 拿到的是
        // 收起态残留布局的旧值。这里改成: 强制 reflow -> 读真实 scrollHeight ->
        // 节点高 = 原生 widgets 高度(y) + 内容全高 + BOTTOM_PAD。
        try { void runtime.root.offsetHeight; } catch (eReflow) {}
        let _contentFullH = 0;
        try { _contentFullH = Math.round(runtime.root.scrollHeight) || 0; } catch (eScroll) {}
        if (!(Math.max(0, _contentFullH) > 0)) {
            // 未布局/实测异常: 退回旧估算, 保证不会把节点压到内容以下。
            _contentFullH = Math.max(available, legacyMinH);
        }
        // y<=0(last_y 未就绪)时不能算 y+content, 此时至少不缩小当前高度。
        const _targetFullH = y > 0
            ? Math.max(y + _contentFullH + BOTTOM_PAD, actualH)
            : Math.max(actualH, _contentFullH);
        if (Math.abs(Number(node.size?.[1] || 0) - _targetFullH) > 4) {
            node.size = [w, _targetFullH];
            node.graph?.setDirtyCanvas(true, true);
            // v2.110: 本帧内 runtime.domWidget.last_y 可能还是改 size 之前的旧值,
            // 下一帧布局稳定后再校正一次, 用真实 y 重算(否则会卡在 y 偏小的高度,
            // 底板盖不住内容)。只在真正改了 size 时安排, 保证收敛不会自激。
            requestAnimationFrame(() => {
                try {
                    if (!runtime._h3BtnResizeInFlight) syncDomHeight(node, runtime, false);
                } catch (eFollow) {}
            });
        }
        runtime.domHeight = _contentFullH;
        if (runtime._userResize || !obviouslyPoisonedHeight(actualH, minNodeH)) {
            runtime.legacyNodeHeight = actualH;
        }
        runtime.lastRenderMode = "legacy";
        node.graph?.setDirtyCanvas(true, true);
    } finally {
        runtime.syncingDomHeight = false;
        runtime._userResize = false;
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

    // v14.253 (2026-10-29): 兜底强制隐藏 clips_json / refs_json 文本框。
    // 背景：用户实测 H3 Film Factory 节点被两个巨型 JSON 文本框撑爆，
    //       CLIP 卡片/全局提示词/底部按钮全部被挤到看不见。
    //       hideNativeWidget 走前端 visibility API，但 ComfyUI 1.55+ 的
    //       customtext widget 在某些版本里 hidden=true 不生效，仍然显示。
    // 兜底方案：把 widget.type 从 "customtext" 改成 "hidden"（ComfyUI 官方
    //       认可的隐藏类型，不渲染 DOM 行），并强制 computeSize 归零。
    //       值仍然保留在 widgets_values 里，保存/加载工作流不受影响。
    for (const _w of [jsonWidget, refsWidget]) {
        if (!_w) continue;
        try { _w.type = "hidden"; } catch (e) {}
        try { _w.computeSize = () => [0, 0]; } catch (e) {}
        try { _w.computedHeight = 0; } catch (e) {}
    }

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
    setBtnText(saveProjectButton, "Save", "", { bg: "#4a3a6a", border: "#5a4a7a", color: "#dcc" });
    saveProjectButton.title = "Save settings + disk cache as a portable .ext project";
    saveProjectButton.classList.add("bsai-tb-btn");
    saveProjectButton.addEventListener("click", (e) => {
        e.preventDefault();
        saveProject(node, runtime);
    });

    const loadProjectButton = document.createElement("button");
    setBtnText(loadProjectButton, "Load", "", { bg: "#3a5a4a", border: "#4a6a5a", color: "#cdc" });
    loadProjectButton.title = "Load a .ext project into this Extender node";
    loadProjectButton.classList.add("bsai-tb-btn");

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
    batchDurLabel.textContent = "Duration(s):";
    batchDurLabel.style.cssText = "font-size:11px;color:#aaa;margin-left:6px;";

    const batchDurInput = document.createElement("input");
    batchDurInput.type = "number";
    batchDurInput.min = "1";
    batchDurInput.max = "300";
    batchDurInput.step = "0.5";
    batchDurInput.value = "15";
    batchDurInput.style.cssText = "width:48px;font-size:11px;padding:1px 4px;background:#1a1a1a;border:1px solid #444;border-radius:3px;color:#ddd;";

    const batchDurBtn = document.createElement("button");
    setBtnText(batchDurBtn, "Apply All", "", { bg: "#2a4a6a", border: "#3a5a7a", color: "#cde" });
    batchDurBtn.title = "Batch-set duration of all CLIPs";
    batchDurBtn.classList.add("bsai-tb-btn");
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
    batchCtxLabel.textContent = "Context:";
    batchCtxLabel.style.cssText = "font-size:11px;color:#aaa;margin-left:6px;";

    const batchCtxBtn = document.createElement("button");
    setBtnText(batchCtxBtn, "Enable All", "", { bg: "#2a6a4a", border: "#3a7a5a", color: "#cde" });
    batchCtxBtn.title = "Batch enable/disable context reference for all CLIPs";
    batchCtxBtn.classList.add("bsai-tb-btn");
    let batchCtxOn = true;
    batchCtxBtn.addEventListener("click", (e) => {
        e.preventDefault();
        batchCtxOn = !batchCtxOn;
        runtime.state.clips.forEach((clip) => {
            clip.context_enabled = batchCtxOn;
            clip.validated = false;
            // v2.117c: 卡片是增量构建、不重建, render() 不会刷新已有复选框 —
            // 这里直接改 DOM: 全开启=绿色打勾, 全关闭=空框; rfe 区域同步明暗。
            const cb = document.getElementById(`ctx_${clip.id}`);
            if (cb) cb.checked = batchCtxOn;
            const tg = document.getElementById(`rfe_toggle_${clip.id}`);
            if (tg) tg.style.opacity = batchCtxOn ? "1" : "0.5";
            const ct = document.getElementById(`rfe_content_${clip.id}`);
            if (ct) { ct.style.opacity = batchCtxOn ? "1" : "0.4"; ct.style.pointerEvents = batchCtxOn ? "" : "none"; }
        });
        if (batchCtxOn) {
            setBtnText(batchCtxBtn, "Disable All", "", { bg: "#6a3a3a", border: "#7a4a4a", color: "#cde" });
        } else {
            setBtnText(batchCtxBtn, "Enable All", "", { bg: "#2a6a4a", border: "#3a7a5a", color: "#cde" });
        }
        invalidateFrom(runtime.state, 0);
        updateHidden(node, runtime);
        render(node, runtime);
    });
    setBtnText(batchCtxBtn, "Disable All", "", { bg: "#6a3a3a", border: "#7a4a4a", color: "#cde" });

    const counter = document.createElement("span");
counter.style.fontSize = "11px";
counter.style.opacity = ".8";
counter.style.marginLeft = "6px";

const mergeOutputBtn = document.createElement("button");
    setBtnText(mergeOutputBtn, "Merge Output", "", { bg: "#2a6a3a", border: "#3a7a4a", color: "#cde" });
    mergeOutputBtn.title = "Merge all finished CLIPs into one video output (does not re-render any CLIP)";
    mergeOutputBtn.classList.add("bsai-tb-btn");

    // Unified sync button: re-sync ALL clips from external prompt_source
    // 统一刷新按钮：从外部输入源重新同步所有CLIP
    const syncAllClipsBtn = document.createElement("button");
    setBtnText(syncAllClipsBtn, "Sync All", "", { icon: "🔄", bg: "#8a4a2a", border: "#aa5a3a", color: "#fcd" });
    syncAllClipsBtn.title = "Re-sync global prompt and all CLIPs from external source";
    syncAllClipsBtn.classList.add("bsai-tb-btn");
    // v2.40: 电影模板按钮 (全局应用)
    const filmTemplateBtn = document.createElement("button");
    setBtnText(filmTemplateBtn, "Template", "", { icon: "✨", bg: "#6a4a8a", border: "#7a5a9a", color: "#eef" });
    filmTemplateBtn.title = "Open film prompt template library (applies globally to all CLIPs)";
    filmTemplateBtn.classList.add("bsai-tb-btn");
    filmTemplateBtn.addEventListener("click", (e) => {
        e.preventDefault();
        openFilmTemplatePicker(node, runtime, "global");
    });

    syncAllClipsBtn.addEventListener("click", (e) => {
        e.preventDefault();
        try {
            syncExternalPrompts(node, runtime);
            setTimeout(() => { try { syncFromHistory(); } catch (e) {} }, 0);
            const text = _readPromptSourceText(node);
            if (text == null) {
                runtime.statusText = "No external source";
                status.textContent = runtime.statusText;
                return;
            }
            const newText = String(text);
            runtime._lastPromptSourceText = newText;
            const sbMarkerRe = /\[(?:分镜|Shot|shot|SHOT)\s*\d+\]/;
            const sbMatch = newText.match(sbMarkerRe);
            const globalText = sbMatch ? newText.slice(0, sbMatch.index).trim() : newText.trim();
            const storyboardText = sbMatch ? newText.slice(sbMatch.index).trim() : "";
            const keepGlobal = !globalText && newText.trim().length > 0;
            if (globalText !== undefined && !keepGlobal) {
                runtime.state.global_prompt = globalText;
                if (runtime.globalPromptTextarea) {
                    runtime.globalPromptTextarea.value = globalText;
                    autoResizeTextarea(runtime.globalPromptTextarea);
                }
            }
            if (storyboardText) {
                const segments = parseStoryboard(storyboardText);
                for (let i = 0; i < segments.length; i++) {
                    while (runtime.state.clips.length <= i) {
                        runtime.state.clips.push(newClip(runtime.state.clips.length));
                    }
                    runtime.state.clips[i].prompt = segments[i].prompt;
                    runtime.state.clips[i]._storyboardFilled = true;
                    delete runtime.state.clips[i].external_prompt;
                    runtime.state.clips[i].duration = String(segments[i].duration);
                }
                // Remove excess CLIPs when storyboard has fewer segments
                if (runtime.state.clips.length > segments.length) {
                    runtime.state.clips.splice(segments.length);
                }
            }
            updateHidden(node, runtime);
            if (typeof runtime.renderGlobalAssetPanel === "function") runtime.renderGlobalAssetPanel();
            render(node, runtime);
            autoGrowNodeToFitAllClips(node, runtime);
            runtime.statusText = "Synced";
            status.textContent = runtime.statusText;
        } catch(err) {
            runtime.statusText = "Sync failed";
            status.textContent = runtime.statusText;
        }
    });
mergeOutputBtn.addEventListener("click", (e) => {
    e.preventDefault();
    // Check if any clip is selected for replacement
    const hasReplace = runtime.state.clips.some((c) => c.replace_mode);
    if (hasReplace) {
        if (!confirm("Some clips are currently marked for regeneration. Merging output will cancel regeneration and merge the existing results directly. Continue?")) {
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

// ── v1.16 打开缓存目录按钮（Latent缓存 / Clip输出） ──
const openCacheBtn = document.createElement("button");
setBtnText(openCacheBtn, "Latent Cache", "", { icon: "📂", bg: "#3a4a6a", border: "#4a5a8a", color: "#cde" });
openCacheBtn.title = "Open the latent cache directory (chain_extender_*.h3cache etc.) in the system file manager";
openCacheBtn.classList.add("bsai-tb-btn");
const openClipsBtn = document.createElement("button");
setBtnText(openClipsBtn, "Clip Output", "", { icon: "📂", bg: "#3a4a6a", border: "#4a5a8a", color: "#cde" });
openClipsBtn.title = "Open the CLIP video output directory (h3_clip_*.mp4, the folder BSAI Premiere Pro reads as its receive port)";
openClipsBtn.classList.add("bsai-tb-btn");
const openCacheDir = (kind, label) => {
    fetch(api.apiURL("/h3_extender/cache/open?kind=" + encodeURIComponent(kind)))
        .then((r) => r.json())
        .then((res) => {
            if (res && res.ok) {
                status.textContent = label + ": " + res.path + " (" + (res.files ? res.files.length : 0) + " files)";
                if (!res.opened) console.warn("[H3 Extender] directory returned but could not be opened automatically", res.path);
            } else {
                status.textContent = label + " open failed" + (res && res.error ? ": " + res.error : "");
            }
        })
        .catch(() => { status.textContent = label + " request failed"; });
};
openCacheBtn.addEventListener("click", (e) => { e.preventDefault(); openCacheDir("latent", "Latent cache"); });
openClipsBtn.addEventListener("click", (e) => { e.preventDefault(); openCacheDir("clips", "Clip output"); });

const status = document.createElement("span");
status.style.fontSize = "11px";
status.style.opacity = ".72";
status.style.marginLeft = "auto";
status.style.whiteSpace = "nowrap";
status.style.overflow = "hidden";
status.style.textOverflow = "ellipsis";
status.style.maxWidth = "45%";

// ── 暂停渲染控制条（每CLIP间暂停 / 继续 / 仅当前 / 中止） ──
const pauseBar = document.createElement("span");
pauseBar.style.cssText = "display:none;align-items:center;gap:4px;margin-left:6px;";
const pauseBtn = document.createElement("button");
setBtnText(pauseBtn, "Pause", "", { icon: "⏸", bg: "#6a5a2a", border: "#8a7a3a", color: "#fcd" });
pauseBtn.title = "Pause is always available: it pauses after the current CLIP finishes and before the next one starts. After pausing you can choose Resume / Current Only / Abort; without intervention, further rendering stops (no auto-resume, no auto-merge; finished CLIPs are kept and can be merged manually via Merge Output). When the node pause_enable is on, it pauses automatically after each CLIP.";
pauseBtn.classList.add("bsai-tb-btn");
const resumeBtn = document.createElement("button");
resumeBtn.textContent = "▶ Resume";
resumeBtn.title = "Resume rendering remaining CLIPs";
resumeBtn.style.cssText = "font-size:11px;padding:2px 10px;background:#2a6a4a;border:1px solid #3a7a5a;border-radius:4px;color:#cde;cursor:pointer;font-weight:bold;display:none;";
const stopAfterBtn = document.createElement("button");
stopAfterBtn.textContent = "⏹ Current Only/Stop";
stopAfterBtn.title = "Stop further rendering; keep only finished CLIPs (use Merge Output to combine)";
stopAfterBtn.style.cssText = "font-size:11px;padding:2px 10px;background:#7a3a3a;border:1px solid #9a5a5a;border-radius:4px;color:#fdd;cursor:pointer;font-weight:bold;display:none;";
const abortBtn = document.createElement("button");
abortBtn.textContent = "✖ Abort";
abortBtn.title = "Abort the whole render";
abortBtn.style.cssText = "font-size:11px;padding:2px 10px;background:#5a2a2a;border:1px solid #7a4a4a;border-radius:4px;color:#fbb;cursor:pointer;font-weight:bold;display:none;";
const sendRenderControl = (action) => {
	fetch(api.apiURL("/h3_extender/render_control"), {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ node: String(node.id), action }),
	})
		.then((r) => r.json().catch(() => ({})))
		.then((res) => {
			if (res && res.state === "idle") {
				console.warn("[H3 Extender] no render in progress", action);
			}
		})
		.catch((err) => console.warn("[H3 Extender] render_control failed", action, err));
};
pauseBtn.addEventListener("click", (e) => { e.preventDefault(); sendRenderControl("pause"); });
resumeBtn.addEventListener("click", (e) => { e.preventDefault(); sendRenderControl("resume"); });
stopAfterBtn.addEventListener("click", (e) => { e.preventDefault(); sendRenderControl("stop_after"); });
abortBtn.addEventListener("click", (e) => { e.preventDefault(); sendRenderControl("abort"); });
	// v2.83 (2026-09-27): 收起/展开CLIP按钮 - 收起时只渲染/显示 CLIP1,
	// 展开时渲染全部 CLIP(增量分片), 不再只是缩放高度。
	// 默认收起(打开工作流只展示 CLIP1), 与 onConfigure 的初始 limit:1 一致。
	const collapseAllBtn = document.createElement("button");
	// v2.111: 默认「展开CLIP」状态(与 runtime._h3CollapsedAll = false 一致)。
	// 按钮显示的是"下一步可点的动作", 所以展开态显示「📦 收起CLIP」。
	setBtnText(collapseAllBtn, "Collapse", "", { icon: "📦", bg: "#2a5a3a", border: "#3a7a4a", color: "#dfd" });
		collapseAllBtn.title = "Currently expanded (shows all CLIPs). Click to collapse to CLIP1 only; click again to expand.";
		collapseAllBtn.classList.add("bsai-tb-btn");
	let clipsCollapsed = false; // v2.111: 默认展开(与 runtime._h3CollapsedAll 一致)
	collapseAllBtn.addEventListener("click", (e) => {
		e.preventDefault();
		clipsCollapsed = !clipsCollapsed;
		const w = Math.max(NODE_MIN_WIDTH, Number(node.size && node.size[0]) || NODE_MIN_WIDTH);
		if (clipsCollapsed) {
			// 收起: 只显示 CLIP1 高度的视口, cards 纵向滚动条可滚动查看全部
			setBtnText(collapseAllBtn, "Expand", "", { icon: "📂", bg: "#2a5a3a", border: "#3a7a4a", color: "#dfd" });
			runtime._h3CollapsedAll = true;
			try {
				// v2.107 (fix): 收起按钮 click 必须用 _h3BtnResizeInFlight guard
				// 抑制 afterResize 钩子(line 6355)的"二次 syncDomHeight"。
				// 之前 click handler 调 syncDomHeight(node, runtime, true),
				// legacy 收起分支(line 5075)写 node.size=[w, _targetH3≈1075],
				// 触发 afterResize → 钩子里 _userResize=true(line 6356) → 再调
				// syncDomHeight(forceMin=false) → 此时 _userResize=true, 走
				// `_vh2 = node.size[1] - NON_CARD_FIXED = 1075-285 = 790` 这条
				// 错位公式 → contentH=886 → _targetH3=1486 → node.size=[w, 1486],
				// 节点被二次撑高 ~411px, 卡片底部出现 ~411px 黑边。
				// 修复: click handler 显式设 _h3BtnResizeInFlight=true,
				// afterResize 钩子看到这个标志直接 return 不调 syncDomHeight,
				// 保证 click handler 设的 _targetH3 是最终值。
				runtime._userResize = false;
				runtime.state.nodeHeight = 0;
				runtime._h3BtnResizeInFlight = true;
				try {
					syncDomHeight(node, runtime, true);
					node.graph?.setDirtyCanvas(true, true);
				} finally {
					// 下一帧再释放, 防 afterResize 同步执行(legacy 分支 line 6387
					// 同步调 syncDomHeight)在 finally 前再次进入。
					setTimeout(() => { try { runtime._h3BtnResizeInFlight = false; } catch (e3) {} }, 0);
				}
			} catch (e2) {}
		} else {
			// 展开: 一次性同步渲染全部 CLIP(保证点击必看到全部), 撑高到全量高度
			setBtnText(collapseAllBtn, "Collapse", "", { icon: "📦", bg: "#2a5a3a", border: "#3a7a4a", color: "#dfd" });
			runtime._h3CollapsedAll = false;
			// v2.108: 全局提示词区显隐只由用户折叠标志决定, 展开 CLIP 不再强制显示。
			applyGlobalPromptVisibility(runtime);
			try {
				const _all = Number(runtime.state?.clips?.length) || 0;
				if ((Number(runtime._renderedClips) || 0) < _all) {
					render(node, runtime, { chunked: false, limit: _all });
				}
				setTimeout(() => {
				try {
					// v2.107 (fix): 展开按钮用 _h3BtnResizeInFlight guard 防 autoGrow
					// 设的 node.size 被 afterResize 钩子的二次 syncDomHeight 覆盖。
					// autoGrowNodeToFitAllClips(line 272)写 node.size=[w, target≈12321],
					// 触发 afterResize → 钩子里 _userResize=true → 再调 syncDomHeight →
					// legacy 展开分支(line 5143)读 runtime.root.scrollHeight — 但此时
					// cards.style.height 还是收起态残留的 379px(scrollHeight 只有 ~90),
					// _fullNodeH=90+285=375 → node.size=[w, 375] 覆盖了 autoGrow 的 12321,
					// 节点被弹回到 375px, 30 张卡片全部溢出到底板外。
					// 修复: 用 guard 抑制 afterResize 钩子的二次调用, 让 autoGrow 设的高度保留。
					runtime._userResize = false;
					runtime._h3BtnResizeInFlight = true;
					try {
						autoGrowNodeToFitAllClips(node, runtime);
						syncDomHeight(node, runtime, false);
						node.graph?.setDirtyCanvas(true, true);
					} finally {
						setTimeout(() => { try { runtime._h3BtnResizeInFlight = false; } catch (e3) {} }, 0);
					}
				} catch (e2) {}
			}, 150);
			} catch (err) {}
		}
	});

	pauseBar.append(pauseBtn, resumeBtn, stopAfterBtn, abortBtn);

	// v2.60: 恢复缓存按钮
	const restoreCacheBtn = document.createElement("button");
	setBtnText(restoreCacheBtn, "Restore Cache", "", { icon: "♻️", bg: "#6a3a6a", border: "#8a5a8a", color: "#fdf" });
	restoreCacheBtn.title = "Restore all caches and finished CLIPs from the last render with one click, without re-rendering from CLIP1";
	restoreCacheBtn.classList.add("bsai-tb-btn");
	restoreCacheBtn.addEventListener("click", (e) => {
		e.preventDefault();
		if (!confirm("Restore all caches from the last render?\n\nThis restores:\n- The chain cache (.h3cache)\n- Finished CLIP outputs\n\nAfter restoring you can continue rendering the remaining CLIPs without restarting from CLIP1.\n\n(The page is not reloaded; the external prompt and @ asset references are unaffected. Save the workflow with Ctrl+S first; it is preserved across reloads.)")) return;
		fetch(api.apiURL("/h3_extender/restore_cache"), {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ node: String(node.id) }),
		})
			.then((r) => r.json())
			.then((res) => {
				if (res && res.ok) {
					const clipsRestored = res.clips_restored || 0;
					// 先把恢复结果落地到 localStorage, 这样即使浏览器拦截了刷新,
					// 用户在原页面也能看到"已恢复 N 个 CLIP"的状态, 并且下次进入页面
					// 状态栏会自动提示.
					try {
						localStorage.setItem("bsai_h3_last_restore", JSON.stringify({
							node_id: String(node.id),
							clips_restored: clipsRestored,
							previews_restored: res.previews_restored || 0,
							timestamp: Date.now(),
						}));
					} catch (_) {}

					// v2.72: 不再弹「刷新页面」——刷新会被浏览器 beforeunload 拦截
					// ("重新加载站点? 更改可能未保存"), 且丢失未保存的外部提示词/
					// @资产引用。缓存文件已由后端落盘, 后端靠 .restored_marker 在
					// 下次渲染时自动同步 validated 续渲染; 前端只需把已恢复 clip
					// 标记 validated 并重新挂载缩略图, 用户直接点 Run 即可续渲染。
					fetch(api.apiURL("/h3_extender/rendered_clips?owner_id=" + encodeURIComponent(String(node.id))))
						.then((r) => r.json())
						.then((info) => {
							if (info && info.ok) {
								const rendered = Array.isArray(info.rendered) ? info.rendered : [];
								const newCached = rendered.length > 0 ? Math.max(...rendered) : 0;
								runtime.cachedCount = Math.max(Number(runtime.cachedCount || 0), newCached);
							}
							// 把已恢复的 CLIP 标记 validated（与后端 restored_marker 同步一致）
							const stateClips = (runtime.state && runtime.state.clips) || [];
							for (let ci = 0; ci < Math.min(clipsRestored, stateClips.length); ci++) {
								stateClips[ci].validated = true;
							}
							stateClips.forEach((c) => {
								c._previewLoaded = false;
								c._previewVideoUrl = null;
								c._latentPreviewUrl = null;
							});
							// 同步写回 clips_json widget（用户随后 Ctrl+S 也会持久化 validated）
							try {
								if (runtime.jsonWidget && runtime.jsonWidget.value !== undefined) {
									runtime.jsonWidget.value = String(serializeState(runtime.state));
								}
							} catch (_) {}
							try {
								if (typeof render === "function") {
									render(node, runtime);
								}
							} catch (e) { console.warn("[H3] restore-render failed", e); }
							try { node.setDirtyCanvas(true, true); } catch (_) {}
							if (runtime.status) {
								runtime.status.textContent = "♻️ Restored " + clipsRestored + " CLIP(s); no refresh needed — click Run to continue from the next CLIP. Ctrl+S to save the workflow (external prompt and @ asset references are kept automatically)";
								runtime.status.style.color = "#fdf";
							}
						})
						.catch(() => {
							// rendered_clips 失败也至少完成 validated 标记
							const stateClips = (runtime.state && runtime.state.clips) || [];
							for (let ci = 0; ci < Math.min(clipsRestored, stateClips.length); ci++) {
								stateClips[ci].validated = true;
							}
							try {
								if (typeof render === "function") {
									render(node, runtime);
								}
							} catch (e) {}
							if (runtime.status) {
								runtime.status.textContent = "♻️ Restored " + clipsRestored + " CLIP(s); no refresh needed — click Run to continue rendering";
								runtime.status.style.color = "#fdf";
							}
						});
				} else {
					alert("Restore failed: " + (res && res.error ? res.error : "unknown error"));
				}
			})
			.catch((err) => alert("Restore failed: " + err.message));
	});

	// ── 清空缓存按钮（删除上一版缓存，重新渲染新缓存用） ──
	const clearCacheBtn = document.createElement("button");
	setBtnText(clearCacheBtn, "Clear Cache", "", { icon: "🗑", bg: "#5a3a1a", border: "#7a5a3a", color: "#fda" });
	clearCacheBtn.title = "Delete the chain cache, ref2va cache, preview cache, and finished CLIPs from the previous run so new caches can be rebuilt.\nA confirmation dialog will appear.";
	clearCacheBtn.classList.add("bsai-tb-btn");
	clearCacheBtn.addEventListener("click", (e) => {
		e.preventDefault();
		if (!confirm("Clear all caches?\n\nThis deletes:\n- Chain cache (chain_*.h3cache)\n- Reference VAE-encode cache (_ref2va_cache)\n- Reference image cache (_refs)\n- Preview cache (_preview)\n- Finished CLIPs (h3_clip_*.mp4)\n- Temporary previews (_clippv_*)\n\nAll CLIPs must be re-rendered afterwards.")) return;
		clearCacheBtn.textContent = "⏳ Clearing...";
		clearCacheBtn.disabled = true;
		fetch(api.apiURL("/h3_extender/clear_chain_cache"), {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ node: String(node.id), clear_clips: true }),
		})
			.then((r) => r.json().catch(() => ({})))
			.then((res) => {
				if (res && res.ok) {
					const removed = res.removed || 0;
					const freed = res.freed_mb || 0;
					const d = res.details || {};
					let detailStr = "";
					if (d.chain_cache) detailStr += `Chain cache: ${d.chain_cache}\n`;
					if (d.ref2va) detailStr += `ref2va: ${d.ref2va}\n`;
					if (d.refs) detailStr += `Reference images: ${d.refs}\n`;
					if (d.preview) detailStr += `Preview: ${d.preview}\n`;
					if (d.clips) detailStr += `CLIP outputs: ${d.clips}\n`;
					if (d.temp_previews) detailStr += `Temp previews: ${d.temp_previews}\n`;
					alert("Cache cleared!\n\nDeleted " + removed + " file(s)\nFreed " + freed + " MB of disk space\n\n" + detailStr + "\nPlease re-render.");
					// 重置节点渲染状态
					try {
						if (runtime) {
							runtime.cachedCount = 0;
							runtime._renderedClips = 0;
							const stateClips = (runtime.state && runtime.state.clips) || [];
							stateClips.forEach((c) => {
								c._previewLoaded = false;
								c._previewVideoUrl = null;
								c._latentPreviewUrl = null;
							});
							if (typeof render === "function") {
								render(node, runtime);
							}
						}
					} catch (e2) { console.warn("[H3] clear-cache render failed", e2); }
				} else {
					alert("Failed to clear cache: " + ((res && res.error) || "unknown error"));
				}
			})
			.catch((err) => {
				alert("Clear-cache request failed: " + err);
			})
			.finally(() => {
				setBtnText(clearCacheBtn, "Clear Cache", "", { icon: "🗑", bg: "#5a3a1a", border: "#7a5a3a", color: "#fda" });
				clearCacheBtn.disabled = false;
			});
	});

	toolbar.append(saveProjectButton, loadProjectButton, batchDurLabel, batchDurInput, batchDurBtn, batchCtxLabel, batchCtxBtn, counter, mergeOutputBtn, syncAllClipsBtn, filmTemplateBtn, openCacheBtn, openClipsBtn, restoreCacheBtn, collapseAllBtn, pauseBar, clearCacheBtn, status, projectFileInput);

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
    refsHeader.textContent = "REFERENCE IMAGES — double-click a thumbnail to edit";
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

    // Left panel: global-prompt asset references (same as per-clip left panel).
    // Height is locked to the editor wrapper (right side) via
    // syncGpLeftPanelToWrap — a long asset list scrolls inside this panel
    // instead of pushing the whole node taller than the prompt textarea.
    // Note: NO align-self: stretch — that would re-introduce the
    // section-height feedback loop where leftPanel content stretches the
    // section, which stretches the editor wrap, which is what we are
    // trying to clamp in the first place.
    const gpLeftPanel = document.createElement("div");
    gpLeftPanel.className = "bsai-gp-left-panel";
    gpLeftPanel.style.cssText = "width:140px;min-width:140px;flex-shrink:0;border-right:1px solid rgba(255,255,255,.08);background:rgba(0,0,0,.15);padding:6px;display:flex;flex-direction:column;overflow-y:auto;min-height:0;flex:0 0 auto;box-sizing:border-box;";

    const gpLabel = document.createElement("div");
    gpLabel.textContent = "Global Prompt";
    gpLabel.style.cssText = "font-size:10px;color:#888;flex-shrink:0;width:60px;padding-top:5px;";
    // v2.108: 手动折叠/展开全局提示词区。默认展开(收起 CLIP 态也可见),
    // 用户点这个按钮可以单独收起提示词区, 换取 CLIP 卡片更多可视高度。
    const gpCollapseBtn = document.createElement("button");
    gpCollapseBtn.textContent = "▲";
    gpCollapseBtn.title = "Collapse the global prompt area (more room for CLIP cards); click again to expand";
    gpCollapseBtn.style.cssText = "flex-shrink:0;width:22px;height:22px;font-size:10px;background:rgba(40,40,40,.8);border:1px solid rgba(255,255,255,.15);border-radius:4px;color:#aaa;cursor:pointer;align-self:flex-start;";
    const gpTextarea = document.createElement("textarea");
    gpTextarea.value = state.global_prompt || "";
    gpTextarea.spellcheck = false;
    gpTextarea.placeholder = "Global Prompt — prepended to every CLIP prompt\nContent syncs automatically when an external input source is connected";
    gpTextarea.style.cssText = "flex:1 1 auto;min-height:180px;max-height:none;height:auto;resize:vertical;overflow-y:hidden;font-size:11px;background:rgba(0,0,0,.27);border:1px solid rgba(255,255,255,.15);color:inherit;border-radius:5px;padding:4px 6px;box-sizing:border-box;align-self:stretch;";
    autoResizeTextarea(gpTextarea);
    gpTextarea.addEventListener("input", () => {
        state.global_prompt = gpTextarea.value;
        autoResizeTextarea(gpTextarea);
        updateHidden(node, runtime);
        renderGlobalOverlay();
        renderAssetPanel(gpLeftPanel, gpPseudoClip, node, runtime, gpTextarea);
        // Check if user typed @ — show asset picker
        const pos = gpTextarea.selectionStart;
        const before = gpTextarea.value.substring(0, pos);
        const atMatch = before.match(/@([^\s@]*)$/);
        if (atMatch && atMatch[0].length <= 20) {
            showAssetPickerForTextarea(globalPromptSection, null, node, runtime, gpTextarea, atMatch[1]);
        } else {
            const existing = globalPromptSection.querySelector(".bsai-asset-picker");
            if (existing) existing.remove();
        }
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
    gpExpandBtn.title = "Enlarge global prompt window";
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
            gpTextarea.style.maxHeight = "none";
            gpTextarea.style.resize = "vertical";
            autoResizeTextarea(gpTextarea);
            gpExpandBtn.textContent = "⤢";
            gpExpandBtn.style.zIndex = "";
            gpExpandBtn.style.position = "";
            gpExpandBtn.style.top = "";
            gpExpandBtn.style.right = "";
        }
        syncDomHeight(runtime);
    });

    // v2.108: 全局提示词区手动折叠/展开。默认展开(收起 CLIP 态也可见),
    // 用户点这个按钮单独收起提示词区, 给 CLIP 卡片更多可视高度。
    // 折叠状态是会话内 UI 偏好(不写工作流 JSON, 与 gpDragHeight 一致)。
    gpCollapseBtn.addEventListener("click", (e) => {
        e.preventDefault();
        runtime._h3GpUserCollapsed = !runtime._h3GpUserCollapsed;
        gpCollapseBtn.textContent = runtime._h3GpUserCollapsed ? "▼" : "▲";
        gpCollapseBtn.title = runtime._h3GpUserCollapsed
            ? "Expand the global prompt area"
            : "Collapse the global prompt area (gives CLIP cards more visible space); click again to expand";
        gpCollapseBtn.style.color = runtime._h3GpUserCollapsed ? "#6cf" : "#aaa";
        applyGlobalPromptVisibility(runtime);
        try { updateHidden(node, runtime); } catch (e2) {}
        // 显隐变了, 节点高度公式要重算 — 用与按钮相同的 guard 抑制
        // afterResize 钩子的二次 syncDomHeight。
        runtime._userResize = false;
        runtime._h3BtnResizeInFlight = true;
        try {
            syncDomHeight(node, runtime, true);
            node.graph?.setDirtyCanvas(true, true);
        } finally {
            setTimeout(() => { try { runtime._h3BtnResizeInFlight = false; } catch (e3) {} }, 0);
        }
    });

    const gpRefreshBtn = document.createElement("button");
    gpRefreshBtn.textContent = "↻";
    gpRefreshBtn.title = "Refresh: immediately sync content from the external input source";
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
        // Lock the left asset panel height to the editor wrap BEFORE the
        // asset list is re-rendered. Without this, a long asset list would
        // briefly push the section taller than the prompt textarea on the
        // next paint, then snap back when the ResizeObserver callback fires.
        // Use the next-frame variant so we read the wrap's real clientHeight
        // after the browser has finished its current layout pass.
        syncGpLeftPanelToWrapNextFrame(gpEditorWrap);
        renderAssetPanel(gpLeftPanel, gpPseudoClip, node, runtime, gpTextarea);
        renderGlobalOverlay();
        // Re-lock in case the asset list appended children whose intrinsic
        // height somehow exceeds the wrap (it shouldn't, but be safe).
        syncGpLeftPanelToWrapNextFrame(gpEditorWrap);
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
    gpTextarea.style.height = "auto";
    gpTextarea.style.zIndex = "2";
    gpTextarea.style.resize = "none";
    gpTextarea.style.outline = "none";
    const gpEditorWrap = document.createElement("div");
    gpEditorWrap.className = "bsai-gp-editor-wrap";
    gpEditorWrap.style.cssText = "position:relative;flex:1 1 auto;min-height:180px;max-height:none;height:auto;align-self:stretch;";
    gpEditorWrap.append(gpOverlay, gpTextarea);
    autoResizeTextarea(gpTextarea);

    // Keep the global-prompt left asset panel in lock-step with the editor
    // wrap height — covers font-size changes, drag-resize, and any other
    // path that mutates wrap height without going through autoResizeTextarea.
    // Also re-runs autoResizeTextarea so canvas zoom-out (which compresses
    // the wrap from outside) is detected and the textarea is switched to
    // internal scroll mode to stay in lock-step with the left panel.
    if (typeof ResizeObserver !== "undefined") {
        const gpRO = new ResizeObserver(() => {
            autoResizeTextarea(gpTextarea);
        });
        gpRO.observe(gpEditorWrap);
    }
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
        // v2.68 perf: skip innerHTML rebuild when text unchanged (was rebuilding dozens
        // of <img> thumbnails every poll / every render()).
        const refsKey = parseAssetRefs(text).map(r => r.type + ":" + r.index).join(",");
        if (gpOverlay._lastText === text && gpOverlay._lastRefsKey === refsKey) return;
        gpOverlay._lastText = text;
        gpOverlay._lastRefsKey = refsKey;
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

    // ── Global prompt font-size controls (A− / A+) ──
    let gpFontSize = Number(state.gpFontSize) || 11;
    function applyGpFontSize() {
        gpFontSize = Math.max(8, Math.min(26, Math.round(gpFontSize)));
        gpTextarea.style.fontSize = gpFontSize + "px";
        gpOverlay.style.fontSize = gpFontSize + "px";
        state.gpFontSize = gpFontSize;
        autoResizeTextarea(gpTextarea);
    }
    const gpFontMinusBtn = document.createElement("button");
    gpFontMinusBtn.textContent = "A−";
    gpFontMinusBtn.title = "Decrease global prompt font size";
    gpFontMinusBtn.style.cssText = "flex-shrink:0;width:22px;height:22px;font-size:10px;background:rgba(40,40,40,.8);border:1px solid rgba(255,255,255,.15);border-radius:4px;color:#aaa;cursor:pointer;align-self:flex-start;";
    gpFontMinusBtn.addEventListener("click", (e) => {
        e.preventDefault();
        gpFontSize -= 1;
        applyGpFontSize();
        updateHidden(node, runtime);
    });
    const gpFontPlusBtn = document.createElement("button");
    gpFontPlusBtn.textContent = "A+";
    gpFontPlusBtn.title = "Increase global prompt font size";
    gpFontPlusBtn.style.cssText = gpFontMinusBtn.style.cssText;
    gpFontPlusBtn.addEventListener("click", (e) => {
        e.preventDefault();
        gpFontSize += 1;
        applyGpFontSize();
        updateHidden(node, runtime);
    });
    applyGpFontSize();

    globalPromptSection.append(gpLeftPanel, gpLabel, gpCollapseBtn, gpEditorWrap, gpRefreshBtn, gpExpandBtn, gpFontMinusBtn, gpFontPlusBtn);

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
                // Preserve a manually-entered / auto-referenced global prompt when
                // the source carries no archive section but is not empty.
                const keepGlobal = !globalText && fullText.trim().length > 0;
                if (!keepGlobal) {
                    gpTextarea.value = globalText;
                    state.global_prompt = globalText;
                    updateHidden(node, runtime);
                    renderGlobalAssetPanel();
                }
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
    bottomBar.style.cssText = "display:flex;align-items:center;justify-content:space-between;gap:8px;padding:6px 4px;border-top:2px solid rgba(255,255,255,.25);margin-top:0;margin-bottom:2px;flex-shrink:0;background:#152030;";

    const clipsTotalLabel = document.createElement("span");
    clipsTotalLabel.style.cssText = "font-size:12px;font-weight:bold;color:#8ab4f8;white-space:nowrap;";

    const bottomBtnGroup = document.createElement("div");
    bottomBtnGroup.style.cssText = "display:flex;align-items:center;gap:6px;";

    const addClipBtn = document.createElement("button");
    addClipBtn.textContent = "Add CLIP";
    addClipBtn.style.cssText = "font-size:11px;padding:2px 10px;background:#2a5a8a;border:1px solid #3a6a9a;border-radius:4px;color:#cde;cursor:pointer;font-weight:bold;";

    const delAllClipsBtn = document.createElement("button");
    delAllClipsBtn.textContent = "Delete All CLIPs";
    delAllClipsBtn.style.cssText = "font-size:11px;padding:2px 10px;background:#6a2a2a;border:1px solid #7a3a3a;border-radius:4px;color:#fcd;cursor:pointer;font-weight:bold;";

    bottomBtnGroup.append(addClipBtn, delAllClipsBtn);
    bottomBar.append(clipsTotalLabel, bottomBtnGroup);

    // ── v14.104: 一键化快捷开关条（底部按钮栏后面；纯前端 DOM，不参与
    //    widgets_values 序列化、不改变后端参数顺序 → 旧工作流零 NaN 零错位）──
    //    布尔: 点一下开/关；枚举: 点一下弹出下拉菜单直接选档（v14.147 起不再循环点击）。
    //    按钮状态实时读 widget.value。
    const QUICK_DEFS = [
        { key: "refine_enable", en: "Refine", desc_en: "Sol-H3 dual-pass: latent upscale + CONST renoise + second-pass denoise for direct HD output (1920x1088)." },
        { key: "upscale_per_clip", en: "Upx/Clip", desc_en: "Pixel upscale per CLIP after decode (per-segment VRAM stays controllable)." },
        { key: "upscale_final", en: "Upx/Final", desc_en: "Single pixel upscale after all clips are merged (faster and cheaper, applied before delivery)." },
        { key: "block_cache", en: "BlkCache", desc_en: "H3 Block Cache (F1B0 residual) acceleration; requires the T8 plugin. Most effective on stable sequential shots." },
        { key: "ref_cache", en: "RefCache", desc_en: "Ref2VA reference-image encoding disk cache; skips repeated encoding when re-running with new settings." },
        { key: "output_mode", en: "Output", desc_en: "Output modes: none (cache only) -> per_clip (segmented) -> merged (combined) -> both.", cycle: ["none", "per_clip", "merged", "both"], cycleLabels: ["None", "Per clip", "Merged", "Both"] },
        { key: "speed_preset", en: "Speed", desc_en: "Speed preset (7 tiers): custom -> Fast -> Balanced -> Fine -> Fast-VDN -> Balanced-VDN -> Fine-VDN. Model recipes now live in Render Pipeline (v14.172).", cycle: ["custom", "极速", "均衡", "精细", "极速-VDN", "均衡-VDN", "精细-VDN"], cycleLabels: ["Custom", "Fast", "Balanced", "Fine", "Fast-VDN", "Balanced-VDN", "Fine-VDN"], tints: [{ color: "#94a3b8", border: "#475569" }, { color: "#5eead4", border: "#14b8a6" }, { color: "#2dd4bf", border: "#0d9488" }, { color: "#34d399", border: "#059669" }, { color: "#e879f9", border: "#c026d3" }, { color: "#d8b4fe", border: "#a21caf" }, { color: "#c084fc", border: "#7c3aed" }] },
        { key: "refine_lipsync_mode", en: "Lipsync", desc_en: "Lip-sync x refine presets: lock lip-sync -> audio redraw 0.7 -> full audio redraw 1.0.", cycle: ["Lock lip-sync (recommended)", "Audio redraw 0.7", "Full audio redraw 1.0"], cycleLabels: ["Lock lip-sync (recommended)", "Audio redraw 0.7", "Full audio redraw 1.0"], cycleAliases: { "锁定保口型(推荐)": "Lock lip-sync (recommended)", "音频参与重绘0.7": "Audio redraw 0.7", "音频全重绘1.0": "Full audio redraw 1.0" } },
        { key: "upscale_mode", en: "UpxMode", desc_en: "Upscale mode: Balanced (quality+speed) -> Quality first -> Speed first -> Custom.", cycle: ["Balanced (quality+speed)", "Quality first", "Speed first", "Custom"], cycleLabels: ["Balanced (quality+speed)", "Quality first", "Speed first", "Custom"], cycleAliases: { "平衡(质量+速度)": "Balanced (quality+speed)", "质量优先": "Quality first", "速度优先": "Speed first", "自定义": "Custom" } },
        { key: "pause_enable", en: "Pause", desc_en: "Pause automatically after each CLIP; resumes after the timeout when there is no input." },
        // v14.106: 全部 true/false 一键开关扩展（其余布尔参数全覆盖）
        { key: "output_image_audio", en: "Preview", desc_en: "Decode a preview for every CLIP (image + audio stream, can feed upscalers). Off = cache only; export with Final Decode." },
        { key: "cache_dit", en: "DiTCache", desc_en: "CacheDiT step cache acceleration (about 1.4-1.5x for H3, requires the plugin; falls back automatically). Mutually exclusive with block cache." },
        { key: "clip_select_enable", en: "ClipSel", desc_en: "Render only selected CLIPs (use the clip_select parameter, e.g. 1,3 / 2-5); unselected CLIPs keep their cache and are not re-rendered." },
        { key: "upscale_fp16", en: "UpxFP16", desc_en: "Half-precision pixel upscale acceleration (automatic when the GPU/XPU supports it)." },
        { key: "upscale_face_restore", en: "FaceFix", desc_en: "Face restore after upscale (FaceRestore; needs GPFGAN/CodeFormer weights, extra time)." },
        { key: "tiled_refine", en: "Tiled", desc_en: "Second pass samples in tiles along the long spatial axis (attention VRAM drops linearly, prevents OOM hangs). Keep off with plenty of VRAM." },
        { key: "semantic_bridge_enable", en: "SemBrg", desc_en: "Semantic Bridge (about 11MB small MLP residual mix; makes H3 follow composition/spatial/count cues better)." },
        { key: "semantic_bridge_magnitude_match", en: "MagMatch", desc_en: "Match the Semantic Bridge vector magnitude to the original hidden state (on by default upstream)." },
        // v14.221 (2026-10-26): 保脸由布尔升级为三态枚举。cycle 必须与后端 INPUT_TYPES
        // 枚举字面量逐字一致；cycleLabels 为按钮显示名。Old booleans normalized in H3LegacyCompat.norm.
        { key: "face_lock_mode", en: "FaceLock", desc_en: "Face lock modes (v14.221): Off = disabled; Auto = normal face lock (@img2.N face close-up refs drive ref2v conditioning for facial consistency); Small-face refine = run H3 FaceRefine local face-crop redraw on every segment before output, fixing broken/collapsed faces in wide shots (needs BSAI-ComfyUI-FaceRefine installed; slower).", cycle: ["off (关闭)", "auto (常规保脸锁定)", "refine (小脸修复·H3局部重绘)"], cycleLabels: ["Off", "Auto (lock)", "Small-face refine"], tints: [{ color: "#94a3b8", border: "#475569" }, { color: "#5eead4", border: "#14b8a6" }, { color: "#f472b6", border: "#be185d" }] },
        // v14.158 (2026-10-21): 一镜到底旁支模式（参考B站 MinimaxH3 长视频一镜到底工作流）。
        // off=默认分镜剪辑(xfade 转场拼接)；on=无缝长镜头(注入不切场/不转场指令 + 强制
        // motion context(Add Guide 等效锚点) + 合并零转场 concat)。
        { key: "one_shot_mode", en: "OneShot", desc_en: "One-shot branch: off = shot-by-shot editing (xfade transitions); on = seamless long take (no-cut instruction + forced motion context + zero-transition concat).", cycle: ["off (分镜模式)", "on (一镜到底)"], cycleLabels: ["Off (shot edit)", "On (one-shot)"], tints: [{ color: "#94a3b8", border: "#475569" }, { color: "#f472b6", border: "#be185d" }] },
        // v14.215 (2026-10-26): 一镜到底采样档快捷下拉(单采无缝/双采高清/双采无缝 8+4)。
        // cycle  = 实际写回 widget 的值, 必须与后端 INPUT_TYPES 的枚举字面量逐字一致;
        // cycleLabels = 按钮上显示的英文; 两份列表必须同时增删 —— 只改后端而漏掉这两份
        // 硬编码表, 下拉里就选不到新档(与 v14.213 "渲染管道下拉看不到第13档" 同源)。
        { key: "one_shot_sampling", en: "OneShotSmp", desc_en: "One-shot sampling tier (only effective when OneShot = On): Single-pass seamless = skip the refine pass, chained latents are never redrawn, zero seam drift / Dual-pass HD = keep the refine upscale (2K) but the reference workflow shows pixel drift at segment joins / Dual-pass seamless 8+4 (v14.215) = run the refine pass with 8 first-pass + 4 refine steps AND repair the inter-segment anchor, so the join stays seamless.", cycle: ["单采无缝 (推荐)", "双采高清 (接缝风险)", "双采无缝 (8+4)"], cycleLabels: ["Single (seamless)", "Dual-pass HD (seam risk)", "Dual-pass seamless (8+4)"], tints: [{ color: "#94a3b8", border: "#475569" }, { color: "#fca5a5", border: "#dc2626" }, { color: "#34d399", border: "#059669" }] },
        // v14.184 (2026-10-24): 回滚 v14.183 (10 步+音频0.9 致链 segment 音频崩
        // VAD 0 段 + 10 步违 8 步蒸馏契约画质退化) → 恢复 8+4 + 音频重绘继承 w33(0.7)
        // + denoise 0.45 已验证基线。
        // T8 思路 BV1aiaL61Eyu, 一采8步 + 二采4步 + latent不放大(factor=1.0, 二采提速~4x)
        // + HyperVAE 2x 解码像素2x直出 2K, 全程只解码一次, 不增采样显存。
        // 速度档仅留基础 7 档(custom/极速/均衡/精细/VDN×3); FastH3-Trim /
        // FastH3-4步VSA / Turbo-v4 / DMAD-4步 / 武戏组合拳 / 4K直出 秘制酱料 / Omni 8步单采 在此选择。
        // 选 Omni 时二采 15 行自动隐藏（syncOmniRefineRows），切回双采恢复。
        { key: "render_pipeline", en: "Pipeline", desc_en: "Render pipeline (all model recipes are selected here, v14.184): Sol-H3 Self-Lift dual-pass (default) -> FastH3-Trim (8+4) -> FastH3 4-step VSA (4+2) -> Turbo-v4 (6+4, shift 12/3) -> DMAD 4-step (4+2, lcm) -> action combo (8+4, euler) -> 4K direct secret sauce (self-lift 6+3, latent x2.0 -> DLSS5 pixel upscale to 4K) -> FastH3 Omni 8-step single-pass (skips refine; switch the loader to the Omni model + VSA) -> dual-pass 2K (8+4, latent not upscaled + HyperVAE 2x decode -> 2x pixels -> 2K, audio refine inherits w33 0.7) -> Live Commerce voice modes v14.220: 01 pure-text dubbing (all three audio ports ignored; model reads the storyboard lines with its default voice), 02 ref_audio timbre dubbing (model reads the lines but the voice follows ref_audio; lip_audio/lip_voice ignored), 03 lip_voice lip-sync (model does not generate audio; sound comes entirely from lip_voice driving the mouth; ref_audio/lip_audio ignored; lip_audio is MV-only and never used for talking) -> live commerce fully automatic (12+4 one-click tier: audio_context_length=0 + context off from clip2; manual parameters are ignored) -> H25 Hybrid 8-Step Multi-Ref (v14.223, Bilibili BV1dygg6EE6W: H25 Hybrid = base FL2VA + overlay Ref2VA, Block Range Additive 25-49, + LightX2V 8-step FL2V accel LoRA; 8-step single-pass euler/simple shift 12/3 denoise 1.0, refine skipped; switch the Loader to minimax_h3_hybrid_fl2va_ref2va_b25-49-int8 and the accel-LoRA slot to minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16) -> 4K Regenerate OpenH3Regenerate2K (v14.229, Bilibili BV13uxT66EWq: NVLabs open model regenerates a 768P draft (1344x768) to 2560x1440 in 3 refine steps; tier = 4-step draft + 3-step regenerate (denoise 1.0) + latent x1.9; CFG 1.0 set on the sampler; Loader must use the merged LoRA: OpenH3 Refiner 0.7 + fl2v turbo 1.0 + lms sharp 1.0; region license excludes EU/UK/KR/US) -> PRISM 10-Step Motion Boost (v14.231, Bilibili BV1Vino6qE2F: Singularity v2 x 10Eros-Max merged Ref2VA model, HuggingFace OliviaRossi/Minimax-h3_Singularity-x-10Eros-Max_PRISM int8 20.3GB; euler/simple 10 steps denoise 1.0, no LoRA, single-pass, refine skipped; switch the Loader to Minimax-h3_Singularity_x_10Eros-Max_PRISM_int8.safetensors; 5-part prompt recommended) -> Transparent Single-Pass (v14.233, Bilibili BV1arJX69E7L: generate H3 over a flat solid backdrop (green/blue/pure black), 10-step single-pass euler/simple shift 12/3 denoise 1.0, refine skipped so the backdrop stays uniform for clean keying; pair with the 4-step turbo LoRA (~0.8, or ~20 steps without); then key with BSAI_H3_TransparentKey + export with BSAI_H3_SaveTransparentVideo to ProRes 4444 / WebM VP9 / RGBA PNG; prompt must state the flat backdrop, no floor/horizon) -> 4-in-1 Ultimate Accel (v14.234, Bilibili BV1WWxT6cEdY): DMAD 4-step LoRA (official 20 steps -> 8, -57.5%) + SegAttention 2.2.0 (KJNodes PatchSegAttentionKJ, -81% stacked) + reference-input half downscale (-93.25% stacked) + SelfLift dual-pass (6 half-res draft steps + 2 full-res refine steps = 8 NFE, latent x2.0); tier = 6+2, ref half forced, SegAttention co-detected; calm dialogue scenes recommended, dial back for high-motion). -> SolarRenderer Structure Control (v14.235, Bilibili BV1Phxu6PE93: FastH3-Omni + Singularity V2 base; control LoRA reads a structure video frame-by-frame (3D greybox/normal map/DW pose/OpenPose/depth/bbox = video ControlNet) + 4-step LoRA (sampling down to 4 steps); causal version generates block-by-block in real time, each block reads only the previous 5 blocks; tier = 4-step low-res SelfLift draft + 4-step full-res refine (latent x2.0) = 8 NFE, ref_image_size forced max (structure detail kept); Loader suggested: solarrenderer control LoRA + 4-step LoRA (~0.8, FastH3-Omni/Singularity V2 base); feed structure-video frame strips as reference input; prompt must describe camera cuts/landing/environment in detail or the model only outputs the greybox cubes; output can be followed by NVIDIA RTX VFX (Frame Generation 24->48FPS + Super Resolution 2K)) -> Director Fast Dual-Pass (v14.238, MiniMaxH3 Director official workflow port: SelfLift low-res 4-step draft + 4-step full-res refine (latent x2.0) = 8 NFE; core diff: Director control signal (frame-by-frame structure video/greybox) replaces ref2va reference images; Loader suggested: MiniMaxH3 Director control LoRA + 4-step LoRA ~0.8, FastH3-Omni/Singularity V2 base) -> Dual-Pass 2K Official Cond Upscale (v14.250, Bilibili BV1iNsZ6HEs9 H3-TR Dual-Pass RefFlow: official MiniMaxH3LatentUpscaleCombined architecture — refine latent upscaled to x2.0 AND ref2va minimax_refs / minimax_keyframes latent coords upscaled in sync via ComfyUI-MiniMaxH3_LatentUpscaler.utils.upscale_minimax_conditioning (zero VRAM, zero compute); latent x2.0 x native VAE 16x = 2K pixels automatically, no HyperVAE needed; core diff vs old "Dual-Pass 2K HyperVAE 2x" (latent not upscaled, cond stays low-res): factor=2.0 + cond upscale together = reference control scales with refine resolution; recipe reuses proven 8+4/euler/shift 12/3/denoise 0.45).", cycle: ["Sol-H3 Self-Lift 双采 (默认)", "直播配音高清（音频≥12步）", "FastH3-Trim", "FastH3-4步VSA", "Turbo-v4", "DMAD-4步", "武戏组合拳", "4K直出 秘制酱料", "FastH3 Omni 8步单采", "双采2K（HyperVAE 2x 解码）", "QAD-v2-8步", "直播带货·01 纯文本配音（三口不接）", "直播带货·02 ref_audio音色参考配音（只接参考）", "直播带货·03 lip_voice对口型（只接现成主播音频）", "直播带货（全自动）", "FastH3 Omni × SelfLift 超分", "H25 Hybrid 8步 多参考单采", "4K重生成 OpenH3Regenerate2K (768P草稿直出2560)", "PRISM 10步 运动强化单采 (Singularity v2 × 10Eros-Max)", "透明视频 单采抠像 (H3 Transparent)", "4合1终极加速 (DMAD 8步 SelfLift 6+2 + 参考降分 + SegAttention)", "SolarRenderer 结构控制 (控制LoRA + 4步LoRA 逐帧驱动)", "Director 极速双采 (MiniMaxH3 Director 移植)", "双采2K（官方条件放大）"], cycleLabels: ["Sol-H3 Self-Lift Dual-Pass (Default)", "Live Voice HD (Audio >=12 steps)", "FastH3-Trim", "FastH3 4-Step VSA", "Turbo-v4", "DMAD 4-Step", "Action Combo", "4K Direct (Secret Sauce)", "FastH3 Omni 8-Step Single-Pass", "Dual-Pass 2K (HyperVAE 2x)", "QAD-v2 8-Step", "Live Com. 01 Text Dubbing", "Live Com. 02 ref_audio Timbre", "Live Com. 03 lip_voice Lip-sync", "Live Commerce (Auto)", "FastH3 Omni x SelfLift Upscale", "H25 Hybrid 8-Step Multi-Ref", "4K Regenerate (OpenH3Regenerate2K)", "PRISM 10-Step Motion Boost", "Transparent Single-Pass (H3 Keying)", "4-in-1 Ultimate Accel (DMAD 8-Step SelfLift 6+2)", "SolarRenderer Structure Control (4-Step LoRA + Control LoRA)", "Director Fast Dual-Pass (8+3, MiniMaxH3 Director Port)", "Dual-Pass 2K (Official Cond Upscale)"], tints: [{ color: "#94a3b8", border: "#475569" }, { color: "#86efac", border: "#16a34a" }, { color: "#fdba74", border: "#ea580c" }, { color: "#fca5a5", border: "#dc2626" }, { color: "#fde047", border: "#ca8a04" }, { color: "#fb923c", border: "#ea580c" }, { color: "#f87171", border: "#b91c1c" }, { color: "#facc15", border: "#a16207" }, { color: "#22d3ee", border: "#0891b2" }, { color: "#a78bfa", border: "#7c3aed" }, { color: "#5eead4", border: "#0d9488" }, { color: "#4ade80", border: "#15803d" }, { color: "#38bdf8", border: "#0369a1" }, { color: "#c084fc", border: "#7e22ce" }, { color: "#4ade80", border: "#15803d" }, { color: "#f0abfc", border: "#a21caf" }, { color: "#f9a8d4", border: "#be185d" }, { color: "#fda4af", border: "#e11d48" }, { color: "#a3e635", border: "#4d7c0f" }, { color: "#fbbf24", border: "#b45309" }, { color: "#f472b6", border: "#be185d" }, { color: "#7dd3fc", border: "#0284c7" }, { color: "#a5b4fc", border: "#6366f1" }, { color: "#c4b5fd", border: "#7c3aed" }] },
        // v14.193: 视觉锚点已改为全自动（自动记录+自动注入）——
        // 不再有手动输入 widget（visual_anchor_notes 已移除），也不新增端口。
        // 每个分镜渲染时自动把"此前分镜正文的全部可见视觉元素状态"
        // （角色形象/外观/服装/服饰/发型/鞋帽/场景/道具/布景等，全部已建立
        // 状态自旧到新，总长有界）注入为『[视觉锚点延续]』快照，
        // 强制模型延续不漂移；分镜正文声明的新状态自该分镜起成为后续锚点。
        // v14.127: restore_cache 已从 QUICK_DEFS 移除——后端 INPUT_TYPES 同步移除
        // 该参数（1.55 toggle 行无法前端隐藏，根治：参数不存在则行不存在）。
        // 恢复缓存功能由节点底部"恢复缓存"按钮（直调后端 /h3_extender/restore_cache
        // API）承担，功能保留；执行链 kwargs 默认 False（不自动恢复），与按钮手动
        // 恢复语义一致。
    ];
// ── 颜色工具（快捷条分色用）──────────────────────────────────────────
// 多档位按钮（输出 none/per_clip/merged/both、速度 custom/极速/均衡/精细/
// VDN×3/FastH3-Trim、口型 3 档、超分模式 4 档）原本所有非默认档都是同一个
// 亮色，看不出现在停在第几档。这里按档位序号生成一条"同色系深浅渐变"：
// 档位越靠后越浓、越亮、发光越强，第一档保持关闭态暗色 —— 同一个按钮
// 一眼能读出"属于哪一类 + 现在第几档 + 开没开"。v14.147 起点击按钮改为
// 弹出下拉菜单直接选择（不再循环点击），菜单项同样按档位渐变着色。
const __h3HexCache = new Map();
function h3HexToRgb(hex) {
    let h = String(hex || "").trim().replace("#", "");
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    const n = parseInt(h, 16);
    if (!Number.isFinite(n) || h.length !== 6) return { r: 120, g: 160, b: 200 };
    return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}
function h3MixHex(a, b, t) {
    const A = h3HexToRgb(a), B = h3HexToRgb(b);
    const k = Math.max(0, Math.min(1, Number(t) || 0));
    const r = Math.round(A.r + (B.r - A.r) * k);
    const g = Math.round(A.g + (B.g - A.g) * k);
    const bl = Math.round(A.b + (B.b - A.b) * k);
    return "#" + ((1 << 24) + (r << 16) + (g << 8) + bl).toString(16).slice(1);
}
function h3Rgba(hex, alpha) {
    const c = h3HexToRgb(hex);
    const a = Math.max(0, Math.min(1, Number(alpha) || 0));
    return "rgba(" + c.r + "," + c.g + "," + c.b + "," + a.toFixed(3) + ")";
}

// 为一个分类生成 levels 档的深浅渐变（index 0 = 默认档 = 关闭态）
const __h3ShadeCache = new Map();
function h3QuickShades(C, levels) {
    const n = Math.max(1, Math.min(8, levels | 0));
    const ck = C.border + "|" + n;
    if (__h3ShadeCache.has(ck)) return __h3ShadeCache.get(ck);
    const out = [];
    for (let i = 0; i < n; i++) {
        const t = n > 1 ? i / (n - 1) : 1;
        // 底色：淡 → 浓（同时往 border 色偏，保证同一色系内可分辨）
        const bg = h3MixHex(C.color, C.border, t * 0.9);
        out.push({
            t: t,
            bg: h3Rgba(bg, 0.13 + 0.58 * t),
            border: h3MixHex(C.border, C.color, t * 0.55),
            stripe: h3MixHex(C.color, "#ffffff", t * 0.35),
            glow: h3Rgba(h3MixHex(C.color, "#ffffff", t * 0.35), 0.18 + 0.62 * t),
            // 文字再叠一层区分：第 1 档用分类色（暗），中间档提亮，末档纯白
            text: t >= 0.66 ? "#ffffff" : (t >= 0.34 ? h3MixHex(C.color, "#ffffff", 0.55) : C.color),
            textAlpha: 0.62 + 0.38 * t,
            subText: C.color,
        });
    }
    __h3ShadeCache.set(ck, out);
    return out;
}

// v14.146: 分档独立配色（tints 每档一组 color/border）——同档位内仍按序号
// 深浅渐变（第0档=默认档=关闭态暗色），档与档之间用不同色相区分链路：
// 灰=custom / 青=FastH3标准 / 紫=VDN / 橙=Trim。
const __h3TintCache = new Map();
function h3QuickTintedShades(tints) {
    const n = Math.max(1, Math.min(8, tints.length | 0));
    const ck = "t|" + n + "|" + tints.map((t) => t.color + t.border).join(",");
    if (__h3TintCache.has(ck)) return __h3TintCache.get(ck);
    const out = [];
    for (let i = 0; i < n; i++) {
        const t = n > 1 ? i / (n - 1) : 1;
        const T = tints[Math.min(i, tints.length - 1)];
        const bg = h3MixHex(T.color, T.border, t * 0.9);
        out.push({
            t: t,
            bg: h3Rgba(bg, 0.13 + 0.58 * t),
            border: h3MixHex(T.border, T.color, t * 0.55),
            stripe: h3MixHex(T.color, "#ffffff", t * 0.35),
            glow: h3Rgba(h3MixHex(T.color, "#ffffff", t * 0.35), 0.18 + 0.62 * t),
            text: t >= 0.66 ? "#ffffff" : (t >= 0.34 ? h3MixHex(T.color, "#ffffff", 0.55) : T.color),
            textAlpha: 0.62 + 0.38 * t,
            subText: T.color,
        });
    }
    __h3TintCache.set(ck, out);
    return out;
}

// v14.147: 循环档位按钮改为下拉菜单直接选择（不再循环点击）。
// 全局仅允许一个打开的下拉菜单；点击外部/打开新菜单时自动关闭。
let _h3qkOpenMenu = null;
function _h3qkCloseMenu() {
    if (_h3qkOpenMenu) {
        try { _h3qkOpenMenu.remove(); } catch (e) {}
        _h3qkOpenMenu = null;
    }
}
// 在按钮正下方生成下拉面板：列出 cycle 全部档位，每项按该档位的深浅渐变着色，
// 当前档位高亮；点击任意项直接选中（立即回调 refresh/updateHidden）。
// v14.218 档位索引解析(别名感知):
//   cycle 里只放后端的**规范值**(英文), 但历史工作流可能存着旧的中文别名
//   (后端 v2.120c 起仍接受中文)。cycleAliases 把旧别名映射回规范值, 于是:
//     1) 档位序号 / 进度条 / 高亮 对"旧中文值"也算得对 —— 默认档不会被
//        误判成"非默认档"(此前 indexOf 命中不了, 整个档位指示会退化成 1/N);
//     2) 快捷下拉写回的永远是后端规范值(逐字合法, 且等于后端 default);
//     3) 每个别名都必须来自后端枚举、且指向一个真实 cycle 项(tools 自检)。
const _h3qkCanon = (def, v) => {
    if (!def || !def.cycle || typeof v !== "string") return null;
    if (def.cycle.indexOf(v) >= 0) return v;
    const al = def.cycleAliases;
    if (al && typeof al === "object") {
        const hit = al[v];
        if (hit && def.cycle.indexOf(hit) >= 0) return hit;
    }
    return null;
};
const _h3qkIndex = (def, v) => {
    const c = _h3qkCanon(def, v);
    return (c == null) ? -1 : def.cycle.indexOf(c);
};
function _h3qkMakeMenu(def, C, w, shades, onPick) {
    const menu = document.createElement("div");
    menu.style.cssText = "position:fixed;z-index:99999;min-width:130px;background:rgba(15,23,42,.97);border:1px solid " + C.border + ";border-radius:4px;box-shadow:0 6px 18px rgba(0,0,0,.55);padding:3px;";
    for (let i = 0; i < def.cycle.length; i++) {
        const opt = def.cycle[i];
        const S = shades ? shades[Math.min(i, shades.length - 1)] : null;
        const cur = (w && _h3qkCanon(def, w.value) === opt);
        const item = document.createElement("div");
        item.textContent = (def.cycleLabels && def.cycleLabels[i]) ? def.cycleLabels[i] : opt;
        item.style.cssText = "font-size:9px;line-height:1.5;padding:3px 9px;border-radius:3px;cursor:pointer;white-space:nowrap;";
        item.style.color = S ? (cur ? "#ffffff" : S.text) : "#dbeafe";
        item.style.background = cur ? (S ? S.bg : C.on) : "transparent";
        if (cur) item.style.fontWeight = "bold";
        item.addEventListener("mouseenter", () => { item.style.background = cur ? (S ? S.bg : C.on) : (S ? S.stripe : "rgba(255,255,255,.12)"); });
        item.addEventListener("mouseleave", () => { item.style.background = cur ? (S ? S.bg : C.on) : "transparent"; });
        item.addEventListener("click", (ev) => { ev.stopPropagation(); _h3qkCloseMenu(); onPick(opt); });
        menu.append(item);
    }
    return menu;
}

    // ── v14.135: 按功能分色（用户要求）─────────────────────────────────
    // 颜色 = 功能分类；亮度/底色 = 当前状态（关=暗、 开=亮+发光）。
    // 这样"属于哪一类"和"开没开"两个信息互不打架（旧版只用绿/灰表示状态，
    // 19 个按钮挤在一起完全看不出功能分组）。
    const QUICK_CATEGORIES = {
        quality: { zh: "画质", en: "Quality", color: "#c4b5fd", border: "#8b5cf6", off: "rgba(124,58,237,.14)", on: "rgba(139,92,246,.40)" },
        speed:   { zh: "加速", en: "Speed", color: "#5eead4", border: "#14b8a6", off: "rgba(20,184,166,.13)",  on: "rgba(20,184,166,.38)" },
        upscale: { zh: "超分", en: "Upscale", color: "#fcd34d", border: "#d97706", off: "rgba(217,119,6,.15)",  on: "rgba(217,119,6,.40)" },
        sema:    { zh: "语义", en: "Semantic", color: "#f9a8d4", border: "#db2777", off: "rgba(219,39,119,.15)", on: "rgba(219,39,119,.40)" },
        flow:    { zh: "流程", en: "Workflow", color: "#7dd3fc", border: "#0ea5e9", off: "rgba(14,165,233,.14)",  on: "rgba(14,165,233,.38)" },
    };
    // 参数名 → 分类。刻意做成独立映射表：改分类不用动 QUICK_DEFS 本体，
    // 也不会影响 H3_MANAGED_ROW_KEYS / 隐藏逻辑。
    const QUICK_CAT = {
        // 画质：二采 / 口型 / 人脸修复 / 分块二采 / 保脸
        refine_enable: "quality", refine_lipsync_mode: "quality",
        upscale_face_restore: "quality", tiled_refine: "quality", face_lock_mode: "quality",
        // 加速：速度预设 + 三种缓存
        speed_preset: "speed", block_cache: "speed", ref_cache: "speed", cache_dit: "speed",
        // 超分：逐段 / 全片 / 模式 / FP16
        upscale_per_clip: "upscale", upscale_final: "upscale",
        upscale_mode: "upscale", upscale_fp16: "upscale",
        // 语义：语义桥 / 桥对齐
        semantic_bridge_enable: "sema", semantic_bridge_magnitude_match: "sema",
        // 流程：输出 / 预览 / 暂停 / CLIP选择 / 一镜到底 / 渲染管道
        output_mode: "flow", output_image_audio: "flow",
        pause_enable: "flow", clip_select_enable: "flow", one_shot_mode: "flow",
        one_shot_sampling: "flow",
        render_pipeline: "flow",
    };
    const quickBar = document.createElement("div");
    quickBar.style.cssText = "display:flex;flex-wrap:wrap;align-items:center;gap:5px;padding:5px 4px;border-top:1px solid rgba(255,255,255,.18);margin-bottom:2px;flex-shrink:0;background:#182838;";
    const quickTitle = document.createElement("span");
    quickTitle.textContent = "Quick";
    quickTitle.title = "One-click quick toggles: click to toggle (boolean); enum buttons open a dropdown to pick a tier directly. Parameter order is unchanged — zero impact on old workflows.\n\nColor = function category (purple=quality / cyan=acceleration / orange=upscale / pink=semantic / blue=workflow).\nMulti-tier buttons (e.g. output none/per_clip/merged/both): same-hue gradient + tier progress bar at the bottom, brighter = further tier; first tier is dim/off. Click the button to open a dropdown and pick any tier.\nSpeed tiers (8): gray=custom manual / cyan=FastH3 standard (Turbo/Balanced/Fine) / purple=VDN / orange=FastH3-Trim (8 steps + 4 refine); within a chain, brighter = further tier.";
    quickTitle.style.cssText = "font-size:9px;color:#8ab4f8;white-space:nowrap;margin-right:2px;font-weight:bold;text-shadow:0 0 6px rgba(138,180,248,.45);";
    quickBar.append(quickTitle);
    // ── v14.202: 直播带货（全自动）一键档 ──────────────────────────────
    // 一次点击把整套已验证配方写进 widget（与后端同名渲染管道档严格一致），
    // 并把 clip2+ 的 Context Reference 关闭。后端同名档会再次强制覆盖全部
    // 参数，所以用户在参数区手改任何值都不影响实际渲染。
    const LIVE_SELL_VALUES = [
        ["render_pipeline", "直播带货（全自动）"],
        ["steps", 12], ["sampler_name", "euler"], ["scheduler", "simple"], ["denoise", 1],
        ["context_length", "39"], ["audio_context_length", 0],
        ["refine_enable", true], ["refine_steps", 4], ["refine_denoise", 0.55],
        ["refine_upscale_factor", 2], ["refine_upscaler_model", "minimax_h3_latent_upscaler_3d_fp32.pth"],
        ["refine_lipsync_mode", "Audio redraw 0.7"],
        ["shift_video", 12], ["shift_audio", 3], ["dual_track_shift", true],
        ["tiled_refine", false], ["tile_count", 4], ["tile_overlap", 128],
        ["selflift_tst_enable", true], ["selflift_tst_tau", 0.2],
        ["upscale_per_clip", true], ["upscale_final", true], ["upscale_mode", "Quality first"],
        ["upscale_engine", "dlss5"], ["upscale_factor", 2],
        ["output_mode", "both"], ["output_image_audio", true],
        ["one_shot_mode", "off (分镜模式)"],
    ];
    const liveSellBtn = document.createElement("button");
    liveSellBtn.style.cssText = "font-size:9px;line-height:1.15;padding:3px 9px;border-radius:4px;cursor:pointer;display:flex;flex-direction:column;align-items:center;font-family:inherit;background:rgba(21,128,61,.28);border:1px solid #16a34a;border-left:3px solid #4ade80;transition:background .12s,box-shadow .12s;";
    const lsLab = document.createElement("span");
    lsLab.textContent = "Live Commerce";
    lsLab.style.cssText = "font-weight:700;color:#86efac;white-space:nowrap;";
    const lsSub = document.createElement("span");
    lsSub.textContent = "LiveSell Auto";
    lsSub.style.cssText = "font-size:7px;color:#86efac;opacity:.65;";
    liveSellBtn.append(lsLab, lsSub);
    liveSellBtn.title = "One-click live-commerce (fully automatic) tier: 12+4 steps / denoise 0.55 / latent x2.0 / audio redraw 0.7 / shift 12-3 / TST 0.2 / tiles 4x128 / audio_context_length=0 / context off from clip2.\nThe backend render-pipeline tier forces all parameters again; manual changes are ignored.";
    const refreshLiveSell = () => {
        const rpw = node.widgets.find((x) => x && x.name === "render_pipeline");
        const _rpv = rpw && rpw.value || "";
        const on = !!(_rpv === "直播带货（全自动）" || _rpv.indexOf("直播带货·") === 0);
        _liveSellCtxOff = on;
        liveSellBtn.style.background = on ? "rgba(21,128,61,.62)" : "rgba(21,128,61,.28)";
        liveSellBtn.style.boxShadow = on ? "0 0 0 1px #16a34a, 0 0 9px rgba(74,222,128,.55)" : "none";
        lsSub.textContent = on ? (_rpv.indexOf("·01") >= 0 ? "01 Text" : (_rpv.indexOf("·02") >= 0 ? "02 Timbre" : (_rpv.indexOf("·03") >= 0 ? "03 Lip" : "Enabled"))) : "LiveSell Auto";
    };
    liveSellBtn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        for (const [k, v] of LIVE_SELL_VALUES) {
            const w = node.widgets.find((x) => x && x.name === k);
            if (!w) continue;
            w.value = v;
            if (typeof w.callback === "function") { try { w.callback(v); } catch (e) {} }
        }
        runtime.state.clips.forEach((clip, i) => {
            const want = (i === 0);
            clip.context_enabled = want;
            clip.validated = false;
            const cb = document.getElementById(`ctx_${clip.id}`);
            if (cb) cb.checked = want;
            const tg = document.getElementById(`rfe_toggle_${clip.id}`);
            if (tg) tg.style.opacity = want ? "1" : "0.5";
            const ct = document.getElementById(`rfe_content_${clip.id}`);
            if (ct) { ct.style.opacity = want ? "1" : "0.4"; ct.style.pointerEvents = want ? "" : "none"; }
        });
        refreshLiveSell();
        try { invalidateFrom(runtime.state, 0); } catch (e) {}
        try { updateHidden(node, runtime); } catch (e) {}
        try { render(node, runtime); } catch (e) {}
        try { node.setDirtyCanvas(true, true); } catch (e) {}
    });
    refreshLiveSell();
    quickBar.append(liveSellBtn);
    for (const def of QUICK_DEFS) {
        const w = node.widgets.find((x) => x.name === def.key);
        const C = QUICK_CATEGORIES[QUICK_CAT[def.key]] || QUICK_CATEGORIES.flow;
        const shades = def.cycle ? (def.tints ? h3QuickTintedShades(def.tints) : h3QuickShades(C, def.cycle.length)) : null;
        const btn = document.createElement("button");
        btn.style.cssText = "position:relative;overflow:hidden;font-size:9px;line-height:1.15;padding:2px 7px 3px 9px;border-radius:4px;cursor:pointer;display:flex;flex-direction:column;align-items:center;font-family:inherit;border:1px solid " + C.border + ";border-left:3px solid " + C.color + ";transition:background .12s,border-color .12s,box-shadow .12s;";
        const lab = document.createElement("span");
        const sub = document.createElement("span");
        lab.textContent = def.en;
        lab.style.cssText = "font-weight:700;color:" + C.color + ";white-space:nowrap;";
        sub.textContent = "";
        sub.style.cssText = "font-size:7px;color:" + C.color + ";opacity:.6;";
        btn.append(lab, sub);
        // v14.136: 档位进度条（仅循环档位按钮）——底部细条按档位序号填充，
        // 深浅渐变之外再加一条"位置"线索，双保险不怕看错。
        let posBar = null;
        if (def.cycle) {
            posBar = document.createElement("i");
            posBar.style.cssText = "position:absolute;left:0;bottom:0;height:3px;width:0;border-radius:0 3px 3px 0;pointer-events:none;";
            btn.append(posBar);
        }
        const baseTitle = "[" + C.en + "] " + def.en + "\n" + def.desc_en;
        btn.title = baseTitle + "\nClick to " + (def.cycle ? "open the dropdown and pick a tier" : "toggle on/off") + ".";
        const refresh = () => {
            let on = false;
            if (w) {
                if (def.cycle) {
                    // v14.115: 枚举档位按钮——第一档（默认）灰色、其他档绿色，
                    // 按钮下方实时显示当前档位名（不再恒绿"像点不动"）。
                    // v14.136: 不再"非默认档一律同色"——按档位序号取深浅渐变，
                    // 否则 none/per_clip/merged/both 看起来一模一样。
                    const cur = _h3qkIndex(def, w.value);
                    const idx = cur >= 0 ? cur : 0;
                    on = cur > 0;
                    const curName = cur >= 0 ? def.cycle[cur] : String((w.value === undefined || w.value === null) ? "" : w.value);
                    const curLabel = (def.cycleLabels && cur >= 0) ? def.cycleLabels[cur] : curName;
                    sub.textContent = curLabel;
                    sub.style.cssText = "font-size:7px;color:" + C.color + ";opacity:" + (on ? "1" : ".55") + ";max-width:96px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
                    btn.title = baseTitle + "\nCurrent tier: " + curLabel + " (" + (idx + 1) + "/" + def.cycle.length + ")\nClick to open the dropdown and pick a tier.";
                    if (posBar) {
                        const pct = Math.round(((idx + 1) / def.cycle.length) * 100);
                        posBar.style.width = pct + "%";
                        posBar.style.background = on ? shades[idx].stripe : C.border;
                        posBar.style.boxShadow = on ? "0 0 6px " + shades[idx].glow : "none";
                        posBar.style.opacity = on ? "1" : ".45";
                    }
                } else {
                    on = Boolean(w.value);
                    sub.textContent = on ? "ON" : "OFF";
                    sub.style.cssText = "font-size:7px;color:" + C.color + ";opacity:" + (on ? "1" : ".55") + ";max-width:96px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
                    if (posBar) { posBar.style.width = on ? "100%" : "0%"; }
                }
            }
            // 颜色=分类；循环按钮再按档位取深浅渐变；布尔按钮=开/关两态
            if (def.cycle && w) {
                const idx = Math.max(0, _h3qkIndex(def, w.value));
                const S = shades[Math.min(idx, shades.length - 1)];
                btn.style.background = S.bg;
                btn.style.border = "1px solid " + S.border;
                btn.style.borderLeft = "3px solid " + S.stripe;
                btn.style.boxShadow = on ? "0 0 0 1px " + S.border + ", 0 0 8px " + S.glow : "none";
                lab.style.color = S.text;
                lab.style.opacity = String(S.textAlpha);
                lab.style.textShadow = on ? "0 0 6px " + S.glow : "none";
            } else {
                btn.style.background = on ? C.on : C.off;
                btn.style.border = "1px solid " + C.border;
                btn.style.borderLeft = "3px solid " + C.color;
                btn.style.boxShadow = on ? "0 0 0 1px " + C.border + ", 0 0 7px " + C.color + "66" : "none";
                lab.style.color = on ? "#ffffff" : C.color;
                lab.style.opacity = "1";
                lab.style.textShadow = on ? "0 0 6px " + C.color + "cc" : "none";
            }
        };
        btn.addEventListener("click", (ev) => {
            if (!w) return;
            if (def.cycle) {
                // v14.147: 循环档位按钮 → 下拉菜单直接选择（不再循环点击）。
                // 点击按钮：若已打开本按钮的下拉菜单则关闭（toggle），否则关闭旧的、
                // 在按钮正下方打开本档位下拉菜单。
                ev.stopPropagation();
                if (_h3qkOpenMenu && _h3qkOpenMenu.__h3qkForBtn === btn) {
                    _h3qkCloseMenu();
                    return;
                }
                _h3qkCloseMenu();
                const apply = (val) => {
                    w.value = val;
                    if (typeof w.callback === "function") { try { w.callback(w.value); } catch (e) {} }
                    refresh();
                    try { updateHidden(node, runtime); } catch (e) {}
                    try { node.setDirtyCanvas(true, true); } catch (e) {}
                };
                const menu = _h3qkMakeMenu(def, C, w, shades, apply);
                menu.__h3qkForBtn = btn;
                const r = btn.getBoundingClientRect();
                // 下拉面板定位：默认在按钮下方；空间不足（接近视口底部）时翻转到上方
                const mh = 24 + def.cycle.length * 22;
                const top = (r.bottom + mh < (window.innerHeight || 800)) ? r.bottom + 2 : (r.top - mh);
                menu.style.left = Math.max(4, r.left) + "px";
                menu.style.top = Math.max(4, top) + "px";
                document.body.append(menu);
                _h3qkOpenMenu = menu;
            } else {
                w.value = !w.value;
                if (typeof w.callback === "function") { try { w.callback(w.value); } catch (e) {} }
                refresh();
                try { updateHidden(node, runtime); } catch (e) {}
                try { node.setDirtyCanvas(true, true); } catch (e) {}
            }
        });
        refresh();
        quickBar.append(btn);
    }

    // v14.135: 颜色图例（放在按钮行末尾，自动换行时不挡按钮）
    try {
        const legend = document.createElement("span");
        legend.title = "Color = function category; lit button = currently enabled.";
        legend.style.cssText = "display:inline-flex;align-items:center;gap:7px;margin-left:3px;padding-left:7px;border-left:1px solid rgba(255,255,255,.14);font-size:8px;white-space:nowrap;flex-shrink:0;";
        for (const _k of ["quality", "speed", "upscale", "sema", "flow"]) {
            const _c = QUICK_CATEGORIES[_k];
            if (!_c) continue;
            const _item = document.createElement("span");
            _item.style.cssText = "display:inline-flex;align-items:center;gap:3px;";
            const _dot = document.createElement("i");
            _dot.style.cssText = "width:7px;height:7px;border-radius:2px;display:inline-block;background:" + _c.color + ";box-shadow:0 0 5px " + _c.color + "aa;";
            const _tx = document.createElement("span");
            _tx.textContent = _c.en || _c.zh;
            _tx.style.cssText = "color:" + _c.color + ";opacity:.9;font-weight:bold;";
            _item.append(_dot, _tx);
            legend.append(_item);
        }
        quickBar.append(legend);
    } catch (e) {}

    // v14.147: 下拉菜单全局关闭——点击菜单以外的任何区域（含画布空白、其他节点、
    // 其他按钮）自动收起当前打开的下拉菜单；菜单项自身点击已 stopPropagation。
    try {
        document.addEventListener("click", () => { _h3qkCloseMenu(); });
        document.addEventListener("wheel", () => { _h3qkCloseMenu(); }, { passive: true });
    } catch (e) {}

    // v14.134: 被快捷按钮覆盖的参数在参数区隐藏（一键开关替代参数区设置栏）。
    // 走前端官方 visibility API（详见 hideNativeWidget 注释）：整行在画布
    // 布局里被剔除、Vue 侧 v-if 直接不渲染，而不是"压成 0 高 + 涂黑"——
    // 后者才是参数栏错位重叠（叠罗汉）的根因。
    //
    // 严格 1:1：快捷条上每一个按钮 → 藏它对应的那一行；**没有按钮的一律不藏**。
    //   19 项 = QUICK_DEFS，逐字对应底部快捷条的 19 个按钮：
    //   二采 refine_enable / 逐段超分 upscale_per_clip / 全片超分 upscale_final /
    //   块缓存 block_cache / 参考缓存 ref_cache / 输出 output_mode /
    //   速度 speed_preset / 口型 refine_lipsync_mode / 超分模式 upscale_mode /
    //   暂停 pause_enable / 预览 output_image_audio / DiT缓存 cache_dit /
    //   CLIP选择 clip_select_enable / 超分FP16 upscale_fp16 /
    //   人脸修复 upscale_face_restore / 分块二采 tiled_refine /
    //   语义桥 semantic_bridge_enable / 桥对齐 semantic_bridge_magnitude_match /
    //   保脸 face_lock_mode
    // 保持可见（无快捷按钮，v14.133 误藏、v14.134 起强制放回）：
    //   upscale_engine / upscale_factor / upscale_model / upscale_tile /
    //   upscale_batch / tile_count / tile_overlap /
    //   semantic_bridge_adapter / semantic_bridge_alpha
    //   以及 clip_select、pause_timeout、refine_denoise、refine_steps、
    //   refine_upscale_factor、refine_upscaler_model、refine_align_to、
    //   refine_audio_denoise、temporal_chunk_tokens、temporal_overlap_tokens、
    //   env_audio_enable、env_audio_gain 等从未被纳管的行。
    //
    // widget 仍留在 widgets 数组中，widgets_values 顺序/长度不变
    // → 零 NaN、零重连、旧版工作流加载正常。
    const HIDDEN_ROW_KEYS = QUICK_DEFS.map((d) => d.key);
    applyHiddenParamRows(node, HIDDEN_ROW_KEYS);

    // v14.168: FastH3 Omni 8步单采联动 —— render_pipeline 选 Omni 时隐藏全部
    // 二采(Refine)相关行，避免 UI 出现"二采开关还开着"的误导；切回双采自动恢复。
    // refine 行仍留在 widgets 数组（widgets_values 顺序/长度不变，零错位），仅行级隐藏。
    const H3_REFINE_ROW_KEYS = [
        "refine_enable", "refine_denoise", "refine_steps", "refine_upscale_factor",
        "refine_upscaler_model", "refine_align_to", "refine_audio_denoise",
        "refine_lipsync_mode", "tiled_refine", "tile_count", "tile_overlap",
        "temporal_chunk_tokens", "temporal_overlap_tokens", "refine_mem_mode",
    ];
    const syncOmniRefineRows = (nd) => {
        if (!nd) return;
        const rp = nd.widgets && nd.widgets.find((x) => x && x.name === "render_pipeline");
        const sp = nd.widgets && nd.widgets.find((x) => x && x.name === "speed_preset");
        // v14.170: speed_preset 也纳入 Omni 判定（速度档选 FastH3 Omni 8步单采时同样隐藏二采行）
        const omni = (rp && String(rp.value || "").indexOf("Omni") >= 0) ||
                     (sp && String(sp.value || "").indexOf("Omni") >= 0);
        const keys = omni ? HIDDEN_ROW_KEYS.concat(H3_REFINE_ROW_KEYS) : HIDDEN_ROW_KEYS.slice();
        applyHiddenParamRows(nd, keys);
    };
    try {
        const rpw = node.widgets && node.widgets.find((x) => x && x.name === "render_pipeline");
        if (rpw && !rpw.__h3OmniHook) {
            rpw.__h3OmniHook = true;
            const _oc = rpw.callback;
            rpw.callback = function () {
                try { syncOmniRefineRows(node); } catch (e) {}
                try { refreshLiveSell(); } catch (e) {}
                if (typeof _oc === "function") _oc.apply(this, arguments);
            };
        }
        // v14.170: 速度档选 FastH3 Omni 8步单采时同样实时联动隐藏二采行
        const spw = node.widgets && node.widgets.find((x) => x && x.name === "speed_preset");
        if (spw && !spw.__h3OmniHook) {
            spw.__h3OmniHook = true;
            const _sc = spw.callback;
            spw.callback = function () {
                try { syncOmniRefineRows(node); } catch (e) {}
                if (typeof _sc === "function") _sc.apply(this, arguments);
            };
        }
        syncOmniRefineRows(node);
    } catch (e) {}

    // ── Draggable divider between global prompt and CLIP cards ──
    // Drag to fix the global prompt section height (px); double-click to
    // restore auto (content-height) mode.
    let gpDragHeight = null; // null = auto; number = fixed px
    const gpResizer = document.createElement("div");
    gpResizer.title = "Drag to resize the global prompt area; double-click to restore auto height";
    gpResizer.style.cssText = "height:7px;flex:0 0 7px;cursor:row-resize;background:transparent;margin:1px 0;position:relative;z-index:5;";
    const gpResizerInner = document.createElement("div");
    gpResizerInner.style.cssText = "position:absolute;left:10px;right:10px;top:2px;height:3px;border-radius:2px;background:rgba(255,255,255,.12);transition:background .15s;";
    gpResizer.append(gpResizerInner);
    gpResizer.addEventListener("mouseenter", () => { gpResizerInner.style.background = "rgba(120,190,255,.6)"; });
    gpResizer.addEventListener("mouseleave", () => { gpResizerInner.style.background = "rgba(255,255,255,.12)"; });
    gpResizer.addEventListener("dblclick", (e) => {
        e.preventDefault();
        gpDragHeight = null;
        delete gpEditorWrap.dataset.gpDragFixed;
        delete state.gpDragHeight;
        updateHidden(node, runtime);
        globalPromptSection.style.height = "";
        globalPromptSection.style.flex = "";
        gpEditorWrap.style.height = "";
        gpTextarea.style.height = "";
        gpTextarea.style.overflowY = "hidden";
        autoResizeTextarea(gpTextarea);
        syncDomHeight(runtime);
    });
    gpResizer.addEventListener("mousedown", (e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        const startY = e.clientY;
        const startH = gpDragHeight != null
            ? gpDragHeight
            : (globalPromptSection.getBoundingClientRect().height || 200);
        const cardsMin = Number(cards.style.minHeight) || 200;
        const maxH = Math.max(80, (runtime.root ? runtime.root.getBoundingClientRect().height : 800) - cardsMin - 60);
        function onMove(ev) {
            const h = Math.max(60, Math.min(maxH, startH + (ev.clientY - startY)));
            gpDragHeight = h;
            gpEditorWrap.dataset.gpDragFixed = "1";
            globalPromptSection.style.height = h + "px";
            globalPromptSection.style.flex = "0 0 auto";
            gpEditorWrap.style.height = "100%";
            gpEditorWrap.style.minHeight = "0";
            gpTextarea.style.height = "100%";
            gpTextarea.style.overflowY = "auto";
            // Drag-fixed height changes the wrap height after the next layout
            // tick; keep the left asset panel locked to it in real time.
            syncGpLeftPanelToWrap(gpEditorWrap);
        }
        function onUp() {
            window.removeEventListener("mousemove", onMove);
            window.removeEventListener("mouseup", onUp);
            document.body.style.cursor = "";
            // Persist the user-dragged global prompt section height so it
            // survives page refresh / workflow save until adjusted again.
            if (gpDragHeight != null) {
                state.gpDragHeight = gpDragHeight;
                updateHidden(node, runtime);
            }
            syncGpLeftPanelToWrap(gpEditorWrap);
            syncDomHeight(runtime);
        }
        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
        document.body.style.cursor = "row-resize";
    });

    // Restore a previously drag-fixed global prompt height on node creation.
    if (state.gpDragHeight) {
        gpDragHeight = Number(state.gpDragHeight) || null;
        if (gpDragHeight != null) {
            gpEditorWrap.dataset.gpDragFixed = "1";
            globalPromptSection.style.height = gpDragHeight + "px";
            globalPromptSection.style.flex = "0 0 auto";
            gpEditorWrap.style.height = "100%";
            gpEditorWrap.style.minHeight = "0";
            gpTextarea.style.height = "100%";
            gpTextarea.style.overflowY = "auto";
            // Sync left asset panel to the restored fixed height on first paint
            // (ResizeObserver fires on the next tick, but the asset list is
            // already rendered by then and would briefly push the section
            // taller than the user-set height).
            syncGpLeftPanelToWrap(gpEditorWrap);
        }
    }

    root.append(toolbar, refsSection, globalPromptSection, gpResizer, cards, bottomBar, quickBar, refFileInput);

    const restoredValidatedPrefix = validatedPrefixFromState(state);
    const runtime = {
        _node: node,
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
        // v2.108: 暴露折叠按钮, 供 onConfigure 恢复用户折叠状态时同步图标。
        gpCollapseBtn,
        // v2.108: 暴露拖动把手(历史代码一直读 runtime.gpResizer 但从未赋值,
        // 导致 applyGlobalPromptVisibility 的把手显隐是死代码)。
        gpResizer,
        cards,
        counter,
        status,
        saveProjectButton,
        loadProjectButton,
        projectFileInput,
        refFileInput,
        mergeOutputBtn,
        pauseBar,
        pauseBtn,
        resumeBtn,
        stopAfterBtn,
        abortBtn,
        clearCacheBtn,
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
        // v2.111: 默认改为「展开CLIP」状态(之前默认收起)。用户点「收起CLIP」
        // 后按钮 toggle 会在运行时改这个标志, 不影响这里的默认值。
        _h3CollapsedAll: false,
        // v2.107 (fix): 「收起/展开CLIP」按钮 click handler 显式设的 guard —
        // true 时 afterResize 钩子不再二次调 syncDomHeight, 避免 _userResize=true
        // 让 legacy 收起/展开分支走错位公式把 click 设的高度覆盖掉。
        _h3BtnResizeInFlight: false,
        // v2.108: 全局提示词区是否被用户手动折叠。默认 false = 始终显示,
        // 与 CLIP 收起/展开完全解耦(用户不再丢失提示词区可见性)。
        _h3GpUserCollapsed: false,
        // v2.115: 是否还欠一次初始 render。v2.76 把 onNodeCreated 的初始 render
        // 删掉、改由 onConfigure 兜底, 但 onConfigure 只在"从工作流 JSON 恢复"时
        // 触发 —— 从搜索框新建的节点因此永远不构建卡片 DOM(state 里明明有 1 个
        // 默认 CLIP, 画布上却是一块黑)。onConfigure 渲染后置 false, onNodeCreated
        // 的兜底渲染只在它仍为 true 时执行, 两套分片链不会并发。
        _needsInitialRender: true,
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
        // v2.105 (fix): 手动添加 CLIP 后底板跟随新数量撑大(展开态)。
        // autoGrow 内部对收起态(_h3CollapsedAll)直接 return, 不影响收起视口。
        setTimeout(() => { try { autoGrowNodeToFitAllClips(node, runtime); } catch (e) {} }, 150);
        requestAnimationFrame(() => {
            runtime.cards.scrollTop = runtime.cards.scrollHeight;
        });
    });

    runtime.delAllClipsBtn.addEventListener("click", (e) => {
        e.preventDefault();
        if (runtime.state.clips.length <= 1) return;
        if (!confirm("Are you sure you want to delete ALL clips and reset to one default clip?")) return;
        const freshClip = newClip(0);
        runtime.state.clips = [freshClip];
        updateHidden(node, runtime);
        render(node, runtime);
        // v2.105 (fix): 删除全部 CLIP 后底板收回(展开态跟随新数量收缩)。
        setTimeout(() => { try { autoGrowNodeToFitAllClips(node, runtime); } catch (e) {} }, 150);
    });

    // Poll for unified prompt_source input changes every 800ms
    // 轮询统一外部提示词输入，自动拆分全局提示词和分镜内容
    // v2.67 perf: buildUi() 会被 onConfigure/onExecuted 反复调用，旧 timer 不清会叠加泄漏
    // —— 每调一次 buildUi 多一个 800ms 定时器，打开工作流后定时器越积越多直到卡死。
    if (runtime._psPollTimer) { try { clearInterval(runtime._psPollTimer); } catch (e) {} }
    runtime._lastPromptSourceText = null;
    runtime._psPollTimer = setInterval(() => {
        try {
            const text = _readPromptSourceText(node);
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
            // Preserve a manually-entered / auto-referenced global prompt when
            // the storyboard text has no archive section (empty globalText but
            // non-empty source). Only a fully deleted source resets it.
            const keepGlobal = !globalText && newText.trim().length > 0;
            if (!keepGlobal && runtime.state.global_prompt !== globalText) {
                runtime.state.global_prompt = globalText;
                if (runtime.globalPromptTextarea && runtime.globalPromptTextarea.value !== globalText) {
                    runtime.globalPromptTextarea.value = globalText;
                    autoResizeTextarea(runtime.globalPromptTextarea);
                }
                changed = true;
            }

            // 1b. Always refresh global asset panel (overlay + thumbnails)
            if (typeof runtime.renderGlobalAssetPanel === "function") {
                runtime.renderGlobalAssetPanel();
            }

            // 1c. If external prompt source is completely empty, reset all CLIPs to one empty CLIP
            if (!newText.trim()) {
                if (runtime.state.clips.length !== 1 || runtime.state.clips[0]?.prompt?.trim()) {
                    const freshClip = newClip(0);
                    runtime.state.clips = [freshClip];
                    changed = true;
                }
                // Also clear the Final Decode & Export node's video preview
                const finalNode = connectedFinalDecode(node);
                if (finalNode && finalNode.__h3LivePreview) {
                    const ps = finalNode.__h3LivePreview;
                    try {
                        ps.video.pause();
                        ps.video.removeAttribute("src");
                        ps.video.load();
                        ps.video.style.filter = "none";
                        ps.label.textContent = "";
                        ps.currentVideoInfo = null;
                        ps.colorTimeline = [];
                        ps.liveLoaded = false;
                        ps.restoreLoaded = false;
                        ps.restoreRequestRunning = false;
                        if (ps.saveButton) ps.saveButton.disabled = true;
                    } catch (_) {}
                }
                // Also clear any ComfyUI built-in image/video preview widgets
                if (finalNode) {
                    try {
                        const imgs = finalNode.dom?.querySelectorAll("img, video");
                        if (imgs) imgs.forEach(el => { el.removeAttribute("src"); el.load?.(); });
                    } catch (_) {}
                }
                // Notify backend to delete cached preview files so a page
                // refresh does not restore the stale preview
                if (finalNode) {
                    try {
                        fetch(api.apiURL("/h3_extender/clear_preview"), {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({
                                owner_id: String(node.id),
                                final_id: String(finalNode.id),
                            }),
                        }).catch(() => {});
                    } catch (_) {}
                }
            }

            // 2. Parse storyboard segments and auto-create/update CLIPs
            if (storyboardText) {
                const segments = parseStoryboard(storyboardText);
                if (segments.length > 0) {
                    // Add CLIPs to match segment count — new CLIPs get the segment prompt
                    while (runtime.state.clips.length < segments.length) {
                        const newIdx = runtime.state.clips.length;
                        const fresh = newClip(newIdx);
                        const seg = segments[newIdx];
                        if (seg) {
                            fresh.prompt = seg.prompt || "";
                            fresh.duration = String(seg.duration || fresh.duration);
                            fresh._storyboardFilled = true;
                            delete fresh.external_prompt;
                        }
                        runtime.state.clips.push(fresh);
                        changed = true;
                    }
                    // Update each existing CLIP's duration from segments,
                    // but PRESERVE the user's prompt (manually added @图N tags etc.)
                    for (let i = 0; i < segments.length && i < runtime.state.clips.length; i++) {
                        const seg = segments[i];
                        const clip = runtime.state.clips[i];
                        // If the existing CLIP's prompt is empty (e.g. after a
                        // reset triggered by clearing the prompt source), fill
                        // it from the segment. Otherwise keep user edits.
                        if ((!clip.prompt || !clip.prompt.trim()) && seg.prompt) {
                            clip.prompt = seg.prompt;
                            clip._storyboardFilled = true;
                            delete clip.external_prompt;
                            changed = true;
                        }
                        const newDur = String(seg.duration);
                        if (String(clip.duration) !== newDur) {
                            clip.duration = newDur;
                            changed = true;
                        }
                        clip.validated = false;
                    }
                    // Remove excess CLIPs when storyboard has fewer segments
                    if (runtime.state.clips.length > segments.length) {
                        runtime.state.clips.splice(segments.length);
                        changed = true;
                    }
                }
            }

            if (changed) {
                updateHidden(node, runtime);
                render(node, runtime);
            }
        } catch (e) { /* ignore */ }
    }, 1500);

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
        // v2.69: getHeight = root.scrollHeight (实际渲染高度)。
        // root=flex column: toolbar + cards + bottombar 顺序排列。
        // 收起态 cards 固定 _vh, scrollHeight = toolbar+_vh+bottombar;
        // 展开态 cards=auto, scrollHeight 跟随全部 CLIP 自然撑高。
        // bottombar 永远在 root 内容底部, 不溢出。
        getHeight: () => {
            try {
                const h = runtime.root ? runtime.root.scrollHeight : 0;
                if (h > 50) return h;
            } catch (e) {}
            return 400;
        },
        afterResize: (resizedNode) => {
            runtime._userResize = true; // 用户拖边框: 尊重新高度
            // v2.107 (fix): 「收起/展开CLIP」按钮 click handler 已经显式调过
            // syncDomHeight, 不能再让 afterResize 钩子二次调 — 第二次调用时
            // _userResize=true, 走 legacy 错位公式, 把 click 设的高度覆盖成
            // 错误值(收起+411px 黑边 / 展开→375px 把卡片全部挤出底板)。
            // _h3BtnResizeInFlight=true 时 click handler 自己负责最终高度,
            // 这里只做最小修复(收起态 node.size 不低于 1 卡最小高度)后 return。
            if (runtime._h3BtnResizeInFlight) {
                if (runtime._h3CollapsedAll) {
                    const _minH4b = NON_CARD_FIXED + collapsedViewportH(runtime) + BASE_PADDING - GLOBAL_PROMPT_MIN_HEIGHT
                        + globalPromptSectionH(runtime);
                    if (Number(resizedNode.size?.[1] || 0) < _minH4b - 4) {
                        resizedNode.size = [
                            Math.max(NODE_MIN_WIDTH, Number(resizedNode.size?.[0] || NODE_MIN_WIDTH)),
                            _minH4b,
                        ];
                        resizedNode.graph?.setDirtyCanvas(true, true);
                    }
                }
                return;
            }
            // v2.105 (fix): 收起态下节点高度不得小于 1 张 CLIP 卡片的实际高度 -
            // 程序 setSize 也会触发 afterResize, 防止任意路径(旧 nodeHeight/布局
            // 抖动)把底板缩小到不足 1 卡; 用户拖大不受影响, 展开态不受影响。
            if (runtime._h3CollapsedAll) {
                // v2.108: 收起 CLIP 不再隐藏全局提示词区 — 显隐只由用户折叠标志决定。
                applyGlobalPromptVisibility(runtime);
                const _minH4b = NON_CARD_FIXED + collapsedViewportH(runtime) + BASE_PADDING - GLOBAL_PROMPT_MIN_HEIGHT
                    + globalPromptSectionH(runtime);
                if (Number(resizedNode.size?.[1] || 0) < _minH4b - 4) {
                    resizedNode.size = [
                        Math.max(NODE_MIN_WIDTH, Number(resizedNode.size?.[0] || NODE_MIN_WIDTH)),
                        _minH4b,
                    ];
                    resizedNode.graph?.setDirtyCanvas(true, true);
                }
            }
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
                // v2.95: 同步执行 - rAF 延迟会被后续 getHeight 触发的固定逻辑覆盖,
                // 导致用户拖拽跟随(_userResize)失效、节点弹回收起高度。
                syncDomHeight(resizedNode, runtime, false);
            } else {
                syncDomHeight(resizedNode, runtime, false);
            }
        },
    });
    runtime.domWidget = domWidget;
    // v14.133: 内部状态 widget（clips_json / refs_json / h3_extender_timeline）
    // 与快捷条隐藏走同一套机制（前端官方 visibility API，见 hideNativeWidget）。
    // 旧代码额外覆写 computeSize / computeLayoutSize / computedHeight 把行压成
    // 0 高：行仍留在布局里、画布照样画边框 → 0 高行的圆角边框叠在一起
    // （"叠罗汉"）。这些覆写全部撤销 —— hidden=true 之后
    // LGraphNode.getLayoutWidgets() 会直接跳过该行，行是"消失"而不是"塌陷"。
    // 注意只藏内部状态：用户参数（width/height/steps/cfg/sampler 等）保持可见。
    try {
        const _hideNames = new Set(["clips_json", "refs_json", "h3_extender_timeline"]);
        for (const _w of (node.widgets || [])) {
            if (!_w || _w === domWidget) continue;
            if (!_hideNames.has(_w.name)) continue;  // 只藏内部状态, 用户参数保留可见
            setWidgetRowHidden(node, _w, true);
        }
    } catch (e) {}
    // v2.06 (2026-09-19 fix): 用 Object.defineProperty 定义为非可枚举属性,
    // 这样 ComfyUI 前端另存工作流时序列化会忽略 __h3Extender,
    // 避免 structuredClone 错误 (runtime 里包含 DOM 元素如 globalPromptTextarea).
    Object.defineProperty(node, '__h3Extender', {
        value: runtime,
        enumerable: false,
        writable: true,
        configurable: true
    });

    // Runaway-height recovery: workflows saved while the node was mid-growth
    // serialize an absurd size. Reset to the computed minimum so the DOM-widget
    // container (CLIP cards) sits at the top of the node again. Without this,
    // ComfyUI's widget layout reads the poisoned height and grows the node by
    // ~content-height every frame until it reaches hundreds of thousands of px.
    {
        const poisonedMinH = calculateMinHeight(runtime);
        const curH = Number(node.size?.[1] || 0);
        if (obviouslyPoisonedHeight(curH, poisonedMinH)) {
            const targetW = Math.max(NODE_MIN_WIDTH, Number(node.size?.[0] || NODE_MIN_WIDTH));
            try { node.setSize([targetW, poisonedMinH]); } catch (e) {}
            runtime.legacyNodeHeight = poisonedMinH;
        }
    }

    // v2.30 (2026-09-20 perf fix): 去掉节点级定时器 _portTimer.
    // 全局定时器 window.__h3GlobalSyncPoll 已经在每 500ms 遍历所有节点调用
    // positionClipPorts + syncExternalPrompts, 节点级定时器会导致每个节点
    // 每 500ms 被调用两次, 拖动画布卡顿. 现在只保留全局定时器.
    // if (!runtime._portTimer) {
    //     runtime._portTimer = setInterval(() => {
    //         try { positionClipPorts(node, runtime); } catch (err) {}
    //         try { syncExternalPrompts(node, runtime); } catch (err) {}
    //     }, 500);
    // }

    installInvalidationHooks(node, runtime);
    wrapResolutionWidgetCallbacks(node, runtime);
    // v2.76: onNodeCreated 不再初始 render — onConfigure 是唯一初始渲染。
    // 避免两套分片链并发(旧链被 replaceChildren 清空后仍在追加, 卡片缺失/重复)。

    // ================= H3LegacyCompat: 历史工作流多布局兼容（v14.139）=================
    // 替代 v14.99 按键名填充：该机制在 45A/45B(国庆版/永不失联) 布局会把
    // refine_lipsync_mode 字符串灌进 tiled_refine 布尔位 → 尾部 NaN 错位。
    // 新机制 = 布局检测(长度+锚点) → 位置映射 → 值归一化(选项外→默认/类型转换/
    // batch≥1/布尔字符串语义化)。全程 try 保护，不落盘、不改 JSON、幂等。
    // 设计依据: 对全部 115 个真实历史工作流(118 个 H3 节点, 14 种布局)全量模拟
    // 映射+校验 0 失败(Python 原型 h3_legacy_mapper.py)。
    const H3LegacyCompat = (() => {
        // v14.153 修正(实测全部真实历史工作流布局): prompt_pack 是 H3_PROMPT_PACK
        // 自定义类型 → 前端输入端口, 从不占 widgets_values; h3_extender_timeline
        // 是 dom widget(serialize:false, 但现役前端仍把它序列化为尾部空串)。
        // 现役 64 位: 0..61 = run_mode..face_lock_mode(62 个后端 widget),
        // 62 = refine_mem_mode, 63 = h3_extender_timeline(dom, applyToNode 跳过)。
        // v14.254 (2026-10-29): 补加 refine_sigmas —— Python 端 v14.238 在 optional
        // 末尾加了 refine_sigmas(SIGMAS, forceInput=True)，ComfyUI 前端把它也当
        // widget 序列化进 widgets_values，导致数组长度从 71 变 72，后续所有 widget
        // 映射错位，clips_json/refs_json 被挤到错误索引显示为巨大文本框。
        // 修复：KEYS 数组补加 "refine_sigmas"(index 70)，h3_extender_timeline 顺延到 71。
        const KEYS = ["run_mode","width","height","ref_image_size","steps","sampler_name","scheduler","denoise","context_length","audio_context_length","clips_json","resolution_mode","megapixels","refs_json","output_mode","filename_prefix","output_image_audio","block_cache","block_cache_threshold","block_cache_device","ref_cache","cache_dit","clip_select_enable","clip_select","pause_enable","pause_timeout","refine_enable","refine_denoise","refine_steps","refine_upscale_factor","refine_upscaler_model","refine_align_to","refine_audio_denoise","refine_lipsync_mode","upscale_per_clip","upscale_final","upscale_mode","upscale_engine","upscale_factor","upscale_model","upscale_tile","upscale_batch","upscale_fp16","upscale_face_restore","tiled_refine","tile_count","tile_overlap","speed_preset","dual_track_shift","shift_video","shift_audio","selflift_tst_enable","selflift_tst_tau","temporal_chunk_tokens","temporal_overlap_tokens","semantic_bridge_enable","semantic_bridge_adapter","semantic_bridge_alpha","semantic_bridge_magnitude_match","env_audio_enable","env_audio_gain","face_lock_mode","refine_mem_mode","one_shot_mode","one_shot_clip_duration","render_pipeline","one_shot_sampling","refine_sampler","director_fast_first_mp","director_fast_target_mp","refine_sigmas","h3_extender_timeline"];
        const DEFAULTS = ["clip_by_clip",1344,768,"max",8,"euler","simple",1.0,"39",0,"","auto_from_ref",0,"","none","H3_Extender",true,false,0.12,"cpu",true,false,false,"all",false,5.0,true,0.55,6,2.0,"(bilinear interpolation, no model)",40,0.0,"Lock lip-sync (recommended)",false,false,"Balanced (quality+speed)","auto",2.0,"realesr-general-x4v3.pth",0,4,true,false,false,4,128,"custom",true,12.0,3.0,true,0.2,0,"8",false,"(off: no weights)","0.15",true,"global_inherit",0.15,"off (关闭)","spatial (分块,兼容)","off (分镜模式)",12,"Sol-H3 Self-Lift 双采 (默认)","单采无缝 (推荐)","inherit (跟随一采)",0.4,2.0,""];
        const NUMERIC = new Set(["width","height","steps","audio_context_length","megapixels","block_cache_threshold","pause_timeout","refine_steps","refine_upscale_factor","refine_align_to","refine_audio_denoise","upscale_factor","upscale_tile","upscale_batch","tile_count","tile_overlap","temporal_chunk_tokens","temporal_overlap_tokens","semantic_bridge_alpha","env_audio_gain","one_shot_clip_duration","director_fast_first_mp","director_fast_target_mp"]);
        const BOOLS = new Set(["output_image_audio","block_cache","ref_cache","cache_dit","clip_select_enable","pause_enable","refine_enable","upscale_per_clip","upscale_final","upscale_fp16","upscale_face_restore","tiled_refine","semantic_bridge_enable","semantic_bridge_magnitude_match"]);
        const OPTIONS = {
            run_mode: ["clip_by_clip","full_batch"],
            ref_image_size: ["match","max","half (4合1加速)"],
            context_length: ["22","5","39","56"],
            resolution_mode: ["auto_from_ref","manual"],
            output_mode: ["none","per_clip","merged","both"],
            block_cache_device: ["cpu","gpu"],
            refine_lipsync_mode: ["Lock lip-sync (recommended)","锁定保口型(推荐)","Audio redraw 0.7","音频参与重绘0.7","Full audio redraw 1.0","音频全重绘1.0"],
            upscale_mode: ["Balanced (quality+speed)","平衡(质量+速度)","Quality first","质量优先","Speed first","速度优先","Custom","自定义"],
            upscale_engine: ["auto","dlss5","realesr","bicubic"],
            speed_preset: ["custom","极速","均衡","精细","极速-VDN","均衡-VDN","精细-VDN"],
            env_audio_enable: ["global_inherit","on","off"],
            face_lock_mode: ["off (关闭)","auto (常规保脸锁定)","refine (小脸修复·H3局部重绘)"],
            refine_mem_mode: ["spatial (分块,兼容)","global (全上下文省显存)"],
            one_shot_mode: ["off (分镜模式)","on (一镜到底)"],
            one_shot_sampling: ["单采无缝 (推荐)","双采高清 (接缝风险)","双采无缝 (8+4)"],
            refine_sampler: ["inherit (跟随一采)","euler","res_multistep","dpmpp_2m","lcm","ddim"],
            render_pipeline: ["Sol-H3 Self-Lift 双采 (默认)","直播配音高清（音频≥12步）","FastH3-Trim","FastH3-4步VSA","Turbo-v4","DMAD-4步","武戏组合拳","4K直出 秘制酱料","FastH3 Omni 8步单采","双采2K（HyperVAE 2x 解码）","QAD-v2-8步","直播带货·01 纯文本配音（三口不接）","直播带货·02 ref_audio音色参考配音（只接参考）","直播带货·03 lip_voice对口型（只接现成主播音频）","直播带货（全自动）","FastH3 Omni × SelfLift 超分","H25 Hybrid 8步 多参考单采","4K重生成 OpenH3Regenerate2K (768P草稿直出2560)","PRISM 10步 运动强化单采 (Singularity v2 × 10Eros-Max)","透明视频 单采抠像 (H3 Transparent)","4合1终极加速 (DMAD 8步 SelfLift 6+2 + 参考降分 + SegAttention)", "SolarRenderer 结构控制 (控制LoRA + 4步LoRA 逐帧驱动)", "Director 极速双采 (MiniMaxH3 Director 移植)"],
        };
        function detect(w) {
            const n = w.length;
            // v14.153 修正(实测工作流目录全部 H3 节点布局):
            //  - 64 键 = 现役: 0..61 后端 widget + refine_mem_mode(62) + timeline(63)。
            //  - 63 键分两代: w[48] boolean → v14.150~152(0..61 + timeline 62);
            //    w[48] number → 老键序被旧兼容层错位污染后再保存的混合版
            //    (六联包 temporal/sb 在 48..53, env/gain/face 在 54..56, 尾部为垃圾值)。
            //  - 62 键 = v14.150~152 无 timeline: 0..61。
            //  - 59/58 键 = v14.149 及更早(无 P0/P2 五参数): 六联包 48..53,
            //    env/gain/face 54..56; 59 键多 restore_cache(57)+timeline(58),
            //    58 键仅 timeline(57)。
            // v14.159: 66 键 = 现役 + one_shot_clip_duration(64) + timeline(65)。
            // v14.168: 67 键 = 现役 + render_pipeline(65) + timeline(66)。
            // v14.185: 68 键 = 现役 + render_pipeline(65) + one_shot_sampling(66) + timeline(67)。
            // v14.186: 69 键 = 现役 + render_pipeline(65) + one_shot_sampling(66) + visual_anchor_notes(67) + timeline(68)。
            // v14.192: 现役 68 键 = render_pipeline(65) + one_shot_sampling(66) + timeline(67)
            //          （visual_anchor_notes 手动输入已移除, 现役布局与旧 CUR68 相同,
            //          n===68 即 CUR68; n===69 仍为旧 CUR69 文件, 映射时丢弃 w[67]）。
            // v14.254: 72 键 = 现役 + refine_sampler(67) + director_fast_first_mp(68)
            //          + director_fast_target_mp(69) + refine_sigmas(70) + timeline(71)。
            if (n === 72) return "CUR72";
            if (n === 71) return "CUR71";
            if (n === 69) return "CUR69";
            if (n === 68) return "CUR68";
            if (n === 67) return "CUR67";
            if (n === 66) return "CUR66";
            if (n === 65) return "CUR65";
            if (n === 64) return "CUR64";
            if (n === 63) return (typeof w[48] === "number") ? "O63" : "N63";
            if (n === 62) return "N62";
            // L59G 防御分支(未见真实样本): 59 键且 w[58] 是 spatial/global 组合值。
            if (n === 59 && typeof w[58] === "string" &&
                (w[58].indexOf("spatial") === 0 || w[58].indexOf("global") === 0)) return "L59G";
            if (n === 59) return "L59";
            if (n === 58 && typeof w[48] === "number") return "L58O";
            if (n === 58) return "CURRENT"; // 防御(未见真实样本): 0..57 与现役同键
            const b33 = n > 33 ? w[33] : null;
            if (n === 45 && typeof b33 === "string") {
                const v39 = n > 39 ? w[39] : null;
                return (typeof v39 === "string" && (/\./.test(v39) || /\\/.test(v39))) ? "L45A" : "L45B";
            }
            if (typeof b33 === "boolean") {
                if (n === 43) return "L43";
                if (n === 44) return "L44";
                if (n === 45) return "L45E";
                if (n === 47) return "L47";
                if (n === 52) return "L52";
                if (n === 51) return "L51";
                if (n === 40) return "L40";
                if (n === 38) return "L38";
            }
            if (n === 31) return "L31";
            if (n === 27) return "L27";
            if (n === 17) return "L17";
            return "UNKNOWN";
        }
        // v14.218: 旧工作流中文别名 -> 后端规范值(与 QUICK_DEFS.cycleAliases 同源)。
        // 后端 v2.120c 起中英文都合法, 但规范值(英文)才是后端 default; 前端统一
        // 存规范值 —— 否则英文规范值会被下面的 OPTIONS 白名单当成"选项外", 静默
        // 改写成旧中文标签(这正是 v14.218 修的 desync 根因)。语义完全等价。
        const ALIAS_CANON = {
            refine_lipsync_mode: { "锁定保口型(推荐)": "Lock lip-sync (recommended)", "音频参与重绘0.7": "Audio redraw 0.7", "音频全重绘1.0": "Full audio redraw 1.0" },
            upscale_mode: { "平衡(质量+速度)": "Balanced (quality+speed)", "质量优先": "Quality first", "速度优先": "Speed first", "自定义": "Custom" },
        };
        function norm(k, v, d) {
            if (ALIAS_CANON[k] && typeof v === "string" && ALIAS_CANON[k][v]) return ALIAS_CANON[k][v];
            if (k === "upscale_mode" && typeof v === "string" && ["custom","手动","全手动"].includes(v.trim().toLowerCase())) return "Custom";
            // v14.221: 保脸由布尔升级为三态枚举；旧工作流的布尔值归一为字符串档位。
            if (k === "face_lock_mode" && typeof v === "boolean") return v ? "auto (常规保脸锁定)" : "off (关闭)";
            const o = OPTIONS[k];
            if (o) {
                if (typeof v !== "string") v = String(v);
                return o.includes(v) ? v : d;
            }
            if (NUMERIC.has(k)) {
                if (typeof v === "string") {
                    const s = v.trim();
                    if (s !== "" && !isNaN(Number(s))) return s.includes(".") ? Number(s) : parseInt(s, 10);
                    return d;
                }
                if (typeof v !== "number" || isNaN(v)) return d;
                if (k === "upscale_batch" && v < 1) return 4;
                return v;
            }
            if (BOOLS.has(k)) {
                if (typeof v === "string") {
                    const s = v.trim().toLowerCase();
                    if (["off","disabled","disable","关闭","0","no","false"].includes(s)) return false;
                    if (["on","enabled","enable","开启","1","yes","true"].includes(s)) return true;
                    return d;
                }
                return !!v;
            }
            return v;
        }
        function mapTo(w) {
            const L = detect(w);
            // v14.192 修正: 统一输出 68 位(对齐 KEYS, visual_anchor_notes 已移除):
            // 0..61 后端 widget, 62 = refine_mem_mode, 63 = one_shot_mode,
            // 64 = one_shot_clip_duration, 65 = render_pipeline, 66 = one_shot_sampling,
            // 67 = h3_extender_timeline(dom, applyToNode 跳过)。
            // v14.254: 统一输出 72 位 —— 67 = refine_sampler, 68 = director_fast_first_mp,
            // 69 = director_fast_target_mp, 70 = refine_sigmas, 71 = h3_extender_timeline(dom, 跳过)。
            const out = new Array(72).fill(null);
            if (L === "CUR72" || L === "CUR71" || L === "CUR69" || L === "CUR68" || L === "CUR67" || L === "CUR66" || L === "CUR65" || L === "CUR64" || L === "N63" || L === "N62" || L === "CURRENT" || L === "L59G") {
                // 新纪元(48..52 已有 P0/P2): 0..61 与 KEYS 完全同键, 直接照抄。
                for (let i = 0; i < 62 && i < w.length; i++) out[i] = w[i];
                // CUR72(现役 v14.254): w[62..70] 用户值保留(含 Director 极速三参数 + refine_sigmas);
                // timeline(71) 丢弃。
                if (L === "CUR72" && w.length > 70) { out[62] = w[62]; out[63] = w[63]; out[64] = w[64]; out[65] = w[65]; out[66] = w[66]; out[67] = w[67]; out[68] = w[68]; out[69] = w[69]; out[70] = w[70]; }
                // CUR71(v14.238): w[62..69] 用户值保留(含 Director 极速三参数);
                // timeline(70) 丢弃。
                else if (L === "CUR71" && w.length > 69) { out[62] = w[62]; out[63] = w[63]; out[64] = w[64]; out[65] = w[65]; out[66] = w[66]; out[67] = w[67]; out[68] = w[68]; out[69] = w[69]; }
                // CUR69(旧版含 visual_anchor_notes): w[62..66] 用户值保留;
                // visual_anchor_notes(67)+timeline(68) 丢弃(锚点已自动记录, 旧手写值不再使用)。
                // CUR68(现役, 与 v14.192 布局相同): w[62..66] 用户值; timeline(67) 丢弃。
                else if ((L === "CUR69" || L === "CUR68") && w.length > 66) { out[62] = w[62]; out[63] = w[63]; out[64] = w[64]; out[65] = w[65]; out[66] = w[66]; }
                // CUR67: w[62..65] = rmm/one_shot/clip_dur/render_pipeline 用户值; one_shot_sampling 缺 → DEFAULTS; timeline 丢弃。
                else if (L === "CUR67" && w.length > 65) { out[62] = w[62]; out[63] = w[63]; out[64] = w[64]; out[65] = w[65]; }
                // CUR66: w[62]=rmm 用户值, w[63]=one_shot 用户值, w[64]=clip_dur 用户值; timeline 丢弃。
                else if (L === "CUR66" && w.length > 64) { out[62] = w[62]; out[63] = w[63]; out[64] = w[64]; }
                // CUR65(v14.158): one_shot 值保留, clip_dur 缺 → DEFAULTS 10; timeline 丢弃。
                else if (L === "CUR65" && w.length > 63) { out[62] = w[62]; out[63] = w[63]; }
                // CUR64: w[62] = refine_mem_mode 用户值, 保留; 其余缺 → DEFAULTS; timeline 丢弃。
                else if (L === "CUR64" && w.length > 62) out[62] = w[62];
                // L59G 防御: rmm 值在 58。
                if (L === "L59G" && w.length > 58) out[62] = w[58];
                // N63/N62/CURRENT: 老文件无 rmm → 留 null → DEFAULTS 补 "spatial (分块,兼容)"。
            } else {
                // 老纪元(无 P0/P2): 先按老坐标系组装(58 位: 0..47 同键,
                // 48..53 = temporal/sb 六联包, 54..56 = env/gain/face_lock,
                // 57 = restore_cache/timeline 丢弃), 再统一变换到新坐标系:
                // 0..47 照抄, 48..52 留空补 P0/P2 默认, 老 48..56 → 新 53..61,
                // 62 = refine_mem_mode 默认。
                const old = new Array(58).fill(null);
                if (L === "L58O" || L === "L59" || L === "O63" || L === "CURRENT") {
                    // v14.255 (2026-10-29): CURRENT(58 键)也走这个分支 —— 旧版 KEYS 0..57
                    // 与新版 0..56 完全同键(仅 57 从 prompt_pack 变为 refine_mem_mode)。
                    // 此前 CURRENT 走 else 分支只复制 0..32, 33..57 全部丢失 →
                    // prompt_pack 默认值(复杂 JSON)被映射到新 71(h3_extender_timeline)
                    // 显示为巨大文本框, 把节点撑爆。
                    // 修复: CURRENT 复制 0..56, 57(prompt_pack)不映射(新版 62 由 DEFAULTS 补)。
                    for (let i = 0; i < 57 && i < w.length; i++) old[i] = w[i];
                } else {
                    for (let i = 0; i < 33 && i < w.length; i++) old[i] = w[i];
                    if (L === "L45A") {
                        old[33] = w[33]; old[39] = w[39];
                        old[45] = w[34]; old[46] = w[35]; old[47] = w[36]; old[48] = w[37]; old[49] = w[38];
                        old[51] = w[40]; old[52] = w[41]; old[53] = w[42];
                    } else if (L === "L45B") {
                        old[33] = w[33];
                        old[45] = w[34]; old[46] = w[35]; old[47] = w[36]; old[48] = w[37]; old[49] = w[38];
                        old[50] = w[39]; old[51] = w[40]; old[52] = w[41]; old[53] = w[42]; old[54] = w[43];
                    } else if (L === "L43" || L === "L44" || L === "L45E" || L === "L47" || L === "L51" || L === "L52") {
                        const base = {L43:43, L44:44, L45E:45, L47:47, L51:51, L52:52}[L];
                        for (let off = 0; off < 10; off++) if (33 + off < w.length) old[44 + off] = w[33 + off];
                        if (base >= 44 && w.length > 43) old[54] = w[43];
                        if (base >= 45 && w.length > 44) old[55] = w[44];
                        if (base >= 47 && w.length > 45) old[56] = w[45];
                    } else if (L === "L38") {
                        for (let off = 0; off < 4; off++) if (33 + off < w.length) old[44 + off] = w[33 + off];
                        if (w.length > 37) old[54] = w[37];
                    } else if (L === "L40") {
                        for (let off = 0; off < 6; off++) if (33 + off < w.length) old[44 + off] = w[33 + off];
                        if (w.length > 39) old[54] = w[39];
                    }
                    // L31/L27/L17/UNKNOWN: 仅前缀, 其余默认。
                }
                for (let i = 0; i < 48; i++) out[i] = old[i];
                for (let i = 48; i < 57; i++) out[i + 5] = old[i];
            }
            // 值归一化: 缺位补 DEFAULTS, 选项外回退默认, 数字/布尔类型纠正。
            for (let i = 0; i < out.length; i++) {
                let v = out[i];
                if (v === null || v === undefined) v = DEFAULTS[i];
                out[i] = norm(KEYS[i], v, DEFAULTS[i]);
            }
            return out;
        }
        return {
            applyToNode(node, hist) {
                if (!Array.isArray(hist) || !node.widgets) return;
                let out;
                try { out = mapTo(hist); } catch (e) { return; }
                for (let i = 0; i < out.length && i < node.widgets.length; i++) {
                    const w = node.widgets[i];
                    if (!w) continue;
                    const t = w.type || "";
                    if (t === "dom" || t === "separator") continue;
                    try { if (w.value !== out[i]) w.value = out[i]; } catch (e) {}
                }
            },
        };
    })();

    const oldConfigure = node.onConfigure;
    node.onConfigure = function (info) {
        // v14.99 历史工作流键序自适应（按键名填充）：
        // 工作流数组(59a)与后端 object_info 键序天然一致，按名填充即对齐；
        // 历史短数组(43/45/47 键)按键名模板补位。
        // 不再做值类型判别重排：idx33/idx56 判别在标准 59a 上误命中会导致
        // 尾部错位 + NaN。重排全程 try 保护，标题/渲染在任何异常下仍执行。
        const _hist = info && info.widgets_values;
        // v14.139: 多布局兼容层（替代 v14.99 按键名填充 —— 该机制在 45A/45B
        // 布局会把 refine_lipsync_mode 字符串灌进 tiled_refine 布尔位 → NaN 错位）。
        if (Array.isArray(_hist) && _hist.length) {
            try { H3LegacyCompat.applyToNode(this, _hist); } catch (e) { console.warn("[H3] legacy remap failed", e); }
        }
        // v14.99: 数组(59a)与后端 object_info 键序天然一致 —— 按键名填充即对齐。
        // 历史短数组(43/45/47)与 v14.91 尾部追加版(59)按键名模板补位。
        // 不再用 idx33/idx56 值类型判别模板：该判别在标准 59a 上误命中(face_lock 布尔)
        // 触发错误重排 → 尾部错位 + NaN。按名填充键名唯一, 缺失键跳过、多余值丢弃。
        if (false && Array.isArray(_hist) && _hist.length) {
            const _cur = this.widgets.map(w => w.name);
            const _T43 = ['run_mode','width','height','ref_image_size','steps','sampler_name','scheduler','denoise','context_length','audio_context_length','clips_json','resolution_mode','megapixels','refs_json','output_mode','filename_prefix','output_image_audio','block_cache','block_cache_threshold','block_cache_device','ref_cache','cache_dit','clip_select_enable','clip_select','pause_enable','pause_timeout','refine_enable','refine_denoise','refine_steps','refine_upscale_factor','refine_upscaler_model','refine_align_to','refine_audio_denoise','tiled_refine','tile_count','tile_overlap','speed_preset','temporal_chunk_tokens','temporal_overlap_tokens','semantic_bridge_enable','semantic_bridge_adapter','semantic_bridge_alpha','semantic_bridge_magnitude_match'];
            let _tpl = null;
            const _L = _hist.length;
            if (_L === 59) {
                // 59 键标准键序（v14.85 中间插入 = 后端 object_info）：
                // 无条件按键名填充（键名唯一），缺失键跳过、多余值丢弃。
                _tpl = _T43.slice(0, 33).concat(['refine_lipsync_mode','upscale_per_clip','upscale_final','upscale_mode','upscale_engine','upscale_factor','upscale_model','upscale_tile','upscale_batch','upscale_fp16','upscale_face_restore','tiled_refine','tile_count','tile_overlap','speed_preset','temporal_chunk_tokens','temporal_overlap_tokens','semantic_bridge_enable','semantic_bridge_adapter','semantic_bridge_alpha','semantic_bridge_magnitude_match','env_audio_enable','env_audio_gain','face_lock_mode','restore_cache','h3_extender_timeline']);
            }
            // v14.127: 58 键（restore_cache 已从后端移除后的新工作流键序）——
            // 59 模板去掉 restore_cache；按键名填充，缺失键跳过、多余值丢弃。
            else if (_L === 58) { _tpl = _T43.slice(0, 33).concat(['refine_lipsync_mode','upscale_per_clip','upscale_final','upscale_mode','upscale_engine','upscale_factor','upscale_model','upscale_tile','upscale_batch','upscale_fp16','upscale_face_restore','tiled_refine','tile_count','tile_overlap','speed_preset','temporal_chunk_tokens','temporal_overlap_tokens','semantic_bridge_enable','semantic_bridge_adapter','semantic_bridge_alpha','semantic_bridge_magnitude_match','env_audio_enable','env_audio_gain','face_lock_mode','h3_extender_timeline']); }
            else if (_L === 47) { _tpl = _T43.concat(['env_audio_enable','env_audio_gain','restore_cache','h3_extender_timeline']); }
            else if (_L === 45) { _tpl = _T43.concat(['restore_cache','h3_extender_timeline']); }
            else if (_L === 43) { _tpl = _T43; }
            else if (_L < 43) { _tpl = _T43.slice(0, _L); }
            if (_tpl) {
                try {
                    for (let i = 0; i < _L; i++) {
                        const _idx = _cur.indexOf(_tpl[i]);
                        if (_idx >= 0 && this.widgets[_idx] && this.widgets[_idx].type !== "dom") {
                            let _v = _hist[i];
                            // 防御：旧版以布尔保存 env 开关时归一为数值, 避免滑块 NaN。
                            if (typeof _v === "boolean" && this.widgets[_idx].type === "number") {
                                if (_tpl[i] === "env_audio_enable") _v = _v ? 0.15 : 0;
                                else if (_tpl[i] === "env_audio_gain") _v = _v ? 1 : 0;
                                else _v = _v ? 1 : 0;
                            }
                            this.widgets[_idx].value = _v;
                        }
                    }
                } catch (e) {}
            }
        }
        // v14.102: 代理模式下跳过 oldConfigure（核心包装器）避免递归 ——
        // 原型级代理已在外层调用原始 prototype.onConfigure。
        if (oldConfigure && !this.__h3InProxy) oldConfigure.apply(this, arguments);

        // Force-update the node title to the new display name（重排异常也不影响标题/渲染）
        try { this.title = "BSAI ComfyUI H3 Film Factory v2.131·v14.171"; } catch (e) {}

        // Poisoned-height recovery runs AFTER configure (workflow size has been
        // applied). Reset an absurd serialized height to the computed minimum;
        // widget layout then settles at the real content height.
        const cfgMinH = calculateMinHeight(runtime);
        const cfgCurH = Number(this.size?.[1] || 0);
        if (obviouslyPoisonedHeight(cfgCurH, cfgMinH)) {
            const cfgW = Math.max(NODE_MIN_WIDTH, Number(this.size?.[0] || NODE_MIN_WIDTH));
            try { this.setSize([cfgW, cfgMinH]); } catch (e) {}
            runtime.legacyNodeHeight = cfgMinH;
        }

        // Apply bilingual (EN/中文) labels to all widgets
        bsaiApplyBilingualLabels(this);

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

        // v14.134: 恢复工作流后再压一次被隐藏的参数行 —— configure 会重写
        // widget.options，必须在写入完成之后重新置位，否则快捷条覆盖的行
        // 会重新冒出来。applyHiddenParamRows 幂等（同时把不该藏的行放回），
        // 重复调用无副作用。
        try { applyHiddenParamRows(this, this.__h3HiddenRowKeys); } catch (e) {}

        // v2.111: 默认改为「展开CLIP」状态(之前默认收起)。这里只置标记 +
        // 保证宽度下限, 不再套用收起态的固定视口(v2.105 的默认行为);
        // 具体高度交给 syncDomHeight 的展开分支实测决定。
        try {
            runtime._h3CollapsedAll = false;
            // v2.111: 宽度下限, 保证「📂 展开CLIP / 📦 收起CLIP」按钮完整可见。
            scheduleToolbarWidthFix(this, runtime);
            // 展开态: root/cards 交回 auto, 由 syncDomHeight 实测撑高。
            runtime.root.style.height = "auto";
            runtime.root.style.overflow = "visible";
            runtime.cards.style.height = "auto";
            runtime.cards.style.overflowY = "visible";
            runtime.cards.style.flex = "0 0 auto";
            runtime.cards.style.minHeight = "";
            runtime.cards.style.maxHeight = "none";
            runtime.state.nodeHeight = 0;
        } catch (e) {}

        requestAnimationFrame(() => {
            // v2.102: 收起标记最先设置 - 原顺序在后面, 但
            // removeLegacyRefs/rememberManualResolution 等初始化抛异常会中断
            // 回调, 导致收起初始化不执行, 打开就是非收起态
            // (卡片溢出、底板 1 卡)。
            runtime._h3CollapsedAll = false;
            // v14.95: 初始化段逐项 try 兜底 —— 任何单项抛异常都不允许
            // 中断 rAF 渲染链（否则 CLIP 区/全局提示词区整体丢失）。
            let removedLegacyRefs = false;
            try { removedLegacyRefs = removeLegacyImageRefInputs(this); } catch (e) {}
            try { runtime.state = parseState(runtime.jsonWidget.value); } catch (e) {}
            try { runtime.refsState = parseRefsState(runtime.refsWidget.value); } catch (e) {}
            // v2.72: onConfigure 恢复 state 后必须把 global_prompt 同步回 textarea。
            // constructRuntime(onNodeCreated) 在 configure 应用 widgets_values 之前
            // 执行, textarea 初始化用的是默认空 state; 若这里不同步, 刷新/另存后
            // 全局提示词区显示空白, 用户以为外部提示词丢了被迫重新输入。
            // (state 里其实已恢复, 但用户看到的是 textarea 空白。)
            try {
                if (runtime.globalPromptTextarea && runtime.state?.global_prompt) {
                    runtime.globalPromptTextarea.value = String(runtime.state.global_prompt);
                    autoResizeTextarea(runtime.globalPromptTextarea);
                }
            } catch (e) {}
            try { updateRefsHidden(this, runtime); } catch (e) {}
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
            // v2.69 fix: 默认收起态必须在高度恢复之前就置位, 否则下面的
            // savedH 分支会把节点恢复成之前 30 CLIP 展开时的大高度, 然后
            // 行6581 才改 size —— ComfyUI 已按大高度布局, root 内容只占上面
            // 一截, bottomBar 被 margin-top:auto 推到底部, 中间空一大截。
            runtime._h3CollapsedAll = false;
            // Restore the exact node size the user last adjusted. This must run
            // AFTER widgets are applied: onNodeCreated sees pre-config defaults,
            // so the saved height is only available here in onConfigure. If the
            // widget value is missing (workflow saved by an older build) but the
            // serialized node size is taller than the content minimum, treat
            // that as the user's last height and persist it going forward.
            try {
                const savedH = Number(runtime.state?.nodeHeight || 0);
                const nodeH = Number(this.size?.[1] || 0);
                const minNodeH = calculateMinHeight(runtime) + NON_CARD_FIXED;
                let targetH = 0;
                // v2.105 (fix): 收起态下不恢复旧的 savedH/nodeH 高度 -
                // 那些是之前展开时保存的 4 卡高度, 恢复会把刚固定好的 1 卡
                // 视口又撑回去(刷新后"刚收回又自动脱离")。收起态统一用
                // collapsedViewportH 的 1 卡视口, 展开态才恢复用户保存的高度。
                if (runtime._h3CollapsedAll) {
                    // v2.109: 收起态提示词区默认可见, 公式补上它的实测高度
                    // (后面紧跟的 syncDomHeight 会再实测校正一次)。
                    targetH = NON_CARD_FIXED + collapsedViewportH(runtime) + BASE_PADDING - GLOBAL_PROMPT_MIN_HEIGHT
                        + globalPromptSectionH(runtime);
                } else if (Number.isFinite(savedH) && savedH > 0) {
                    targetH = Math.max(savedH, minNodeH);
                } else if (Number.isFinite(nodeH) && nodeH > minNodeH + 4) {
                    targetH = nodeH;
                    runtime.state.nodeHeight = nodeH;
                    try { updateHidden(this, runtime); } catch (e) {}
                }
                if (targetH > 0) {
                    const w = Math.max(NODE_MIN_WIDTH, Number(this.size?.[0] || NODE_MIN_WIDTH));
                    if (Math.abs(Number(this.size?.[1] || 0) - targetH) > 4) {
                        this.setSize([w, targetH]);
                    }
                    syncDomHeight(this, runtime, true);
                }
            } catch (e) {}
            try {
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
            } catch (e) {}
            // v2.111: 默认展开态 —— 不再套用收起态固定视口(applyCollapsedLayout),
            // 高度交给 syncDomHeight 展开分支实测。宽度下限保证工具栏末尾的
            // 「📂 展开CLIP / 📦 收起CLIP」按钮完整可见。
            runtime._h3CollapsedAll = false;
            try {
                scheduleToolbarWidthFix(this, runtime);
                runtime.root.style.height = "auto";
                runtime.root.style.overflow = "visible";
                runtime.cards.style.height = "auto";
                runtime.cards.style.overflowY = "visible";
                runtime.cards.style.flex = "0 0 auto";
                runtime.cards.style.minHeight = "";
                runtime.cards.style.maxHeight = "none";
                runtime.state.nodeHeight = 0;
            } catch (e) {}
            // v2.108: 全局提示词区默认展开(收起 CLIP 也可见), 显隐由用户
            // 的折叠按钮控制。折叠状态是会话内 UI 偏好, 不写入工作流 JSON
            // (与 gpDragHeight 一致), 刷新页面后回到默认展开。
            try {
                applyGlobalPromptVisibility(runtime);
            } catch (e) {}
            // v2.115: 恢复路径的首次渲染 —— 置位表明 onNodeCreated 的兜底渲染
            // 不必再跑(它检查的就是这个标志)。
            runtime._needsInitialRender = false;
            render(this, runtime, { chunked: true, limit: Number(runtime.state?.clips?.length) || 0 });
            // v2.88: 分片兜底 - 若 rAF/setTimeout 分片被页面占用而停在部分卡片,
            // 平滑循环补全(每 1.2s 补 6 张, 最多 30s), 保证滚动条可查看全部。
            const _h3FallbackTimer = setInterval(() => {
                try {
                    const _r = runtime._renderedClips || 0;
                    const _all2 = runtime.state?.clips?.length || 0;
                    if (_r >= _all2) { clearInterval(_h3FallbackTimer); return; }
                    renderMoreClips(this, runtime, 6);
                } catch (e) {}
            }, 1200);
            setTimeout(() => { try { clearInterval(_h3FallbackTimer); } catch (e) {} }, 30000);
            // Remove malformed auto-ref residue saved by an older version.
            const sanGp = sanitizeGlobalPrompt(runtime.state.global_prompt || "");
            if (sanGp !== runtime.state.global_prompt) {
                runtime.state.global_prompt = sanGp;
                try { updateHidden(this, runtime); } catch (e) {}
            }
            // Re-fetch assets AFTER state restore so autoRef appends references
            // on top of the restored prompt (onNodeCreated fetch may have raced).
            h3FetchAssets();
            // Restore global prompt textarea value (render doesn't update it)
            // 恢复全局提示词textarea值（render不更新它）
            if (runtime.globalPromptTextarea) {
                runtime.globalPromptTextarea.value = runtime.state.global_prompt || "";
                autoResizeTextarea(runtime.globalPromptTextarea);
            }
            if (typeof runtime.renderGlobalAssetPanel === "function") {
                runtime.renderGlobalAssetPanel();
            }
            restoreCacheState(this, runtime);
            syncResolutionMirror(this, runtime);
            // v2.112: 渲染完成后再跑一轮带重试的宽度修正 —— counter
            // (「总时长 15s (1 clip)」) 和 pauseBar 按钮的显示状态此时才稳定,
            // 早先那轮量到的可能偏小。
            scheduleToolbarWidthFix(this, runtime);
            syncDomHeight(this, runtime, true);
            // v2.68 perf: 初始同步从 5 次减到 2 次, 文本没只 autoGrow 不全量 render.
            [200, 1500].forEach(delay => {
                setTimeout(() => {
                    try {
                        const text = _readPromptSourceText(this);
                        if (text == null) return;
                        const newText = String(text);
                        if (newText === runtime._lastPromptSourceText) {
                            // v2.68: onConfigure rAF 已 render 过一次, 这里只 autoGrow 不重建 DOM.
                            try { autoGrowNodeToFitAllClips(this, runtime); } catch(e2) {}
                            return;
                        }
                        runtime._lastPromptSourceText = newText;
                        const sbMarkerRe = /\[(?:分镜|Shot|shot|SHOT)\s*\d+\]/;
                        const sbMatch = newText.match(sbMarkerRe);
                        const globalText = sbMatch ? newText.slice(0, sbMatch.index).trim() : newText.trim();
                        const storyboardText = sbMatch ? newText.slice(sbMatch.index).trim() : "";
                        if (globalText) {
                            runtime.state.global_prompt = globalText;
                            if (runtime.globalPromptTextarea) {
                                runtime.globalPromptTextarea.value = globalText;
                                autoResizeTextarea(runtime.globalPromptTextarea);
                            }
                            if (typeof runtime.renderGlobalAssetPanel === "function") runtime.renderGlobalAssetPanel();
                        }
                        if (storyboardText) {
                            const segments = parseStoryboard(storyboardText);
                            for (let i = 0; i < segments.length; i++) {
                                while (runtime.state.clips.length <= i) {
                                    runtime.state.clips.push(newClip(runtime.state.clips.length));
                                }
                                runtime.state.clips[i].prompt = segments[i].prompt;
                                runtime.state.clips[i]._storyboardFilled = true;
                                delete runtime.state.clips[i].external_prompt;
                                runtime.state.clips[i].duration = String(segments[i].duration);
                            }
                            // Remove excess CLIPs when storyboard has fewer segments
                            if (runtime.state.clips.length > segments.length) {
                                runtime.state.clips.splice(segments.length);
                            }
                        }
                        updateHidden(this, runtime);
                        render(this, runtime, { chunked: true }); // v2.75: 分批渲染
                        autoGrowNodeToFitAllClips(this, runtime);
                    } catch(e) { /* source not ready yet */ }
                }, delay);
            });
        });
    };
    // v14.102: 保存实例级 onConfigure 引用供原型级代理调用。核心 configure
    // 会把 node.onConfigure 覆盖为核心包装器，此引用不受影响（非枚举防序列化）。
    Object.defineProperty(node, '__h3OnConfigureFn', {
        value: node.onConfigure,
        enumerable: false,
        writable: true,
        configurable: true
    });

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
            (ALL_TARGETS.has(node?.comfyClass) || ALL_TARGETS.has(node?.type))
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

function updatePauseBar(runtime) {
	if (!runtime?.pauseBar) return;
	const node = runtime?._node;
	const phase = String(runtime.activePhase || "idle");
	// 暂停/继续/终止按钮任何时候都显示在工具栏；渲染空闲时点击由后端返回提示
	runtime.pauseBar.style.display = "flex";
	if (phase === "paused") {
		runtime.pauseBtn.style.display = "none";
		runtime.resumeBtn.style.display = "";
		runtime.stopAfterBtn.style.display = "";
		runtime.abortBtn.style.display = "";
	} else {
		runtime.pauseBtn.style.display = "";
		runtime.resumeBtn.style.display = "none";
		runtime.stopAfterBtn.style.display = "none";
		runtime.abortBtn.style.display = "none";
	}
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
        if (!(ALL_TARGETS.has(node?.comfyClass) || ALL_TARGETS.has(node?.type))) continue;

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
        if (runtime.pauseBar) runtime.pauseBar.style.display = "none";
        if (statusText) runtime.statusText = statusText;

        // Clear per-clip transient rendering state for all clips.
        // This ensures no clip is left stuck showing "渲染中" after
        // execution ends or is interrupted.
        runtime.state.clips.forEach((clip) => {
            delete clip._latentPreviewUrl;
            delete clip._latentStep;
            delete clip._latentTotal;
            delete clip._renderComplete;
        });

        render(node, runtime);
        node.graph?.setDirtyCanvas(true, true);
    }
}

app.registerExtension({
    name: "BSAIMiniMaxH3.Extender",

    setup() {
        console.log("[H3 Extender] v1.22.1-slotglue loaded");
        console.log("[H3 Extender] v2.105 loaded (sync-collapse + rAF fallback) (collapse-init-first + 4card) (default-4card-view + y0-keep) (y0-keep-layout) (y0 fallback collapse-target) (collapse direct-size + domHeight sync + resize-follow)");

        // v2.61: 页面刚刷新进入时, 如果 URL 上带着 bsai_h3_restored=1 或者 localStorage
        // 里记了"刚恢复的 CLIP 数", 就在控制台和后续节点挂载时明确告知用户.
        // 这样浏览器拦截了 beforeunload (用户点"取消") 时也能看到恢复成功的事实,
        // 而不会以为缓存"没正常恢复"。
        try {
            const urlParams = new URLSearchParams(location.search);
            const restored = urlParams.get("bsai_h3_restored");
            if (restored) {
                let payload = null;
                try {
                    payload = JSON.parse(localStorage.getItem("bsai_h3_last_restore") || "null");
                } catch (_) {}
                if (payload) {
                    console.log("[H3 Extender] restored " + payload.clips_restored + " cached CLIPs before this refresh (node " + payload.node_id + ")");
                }
                // 给用户一个明显提示, 避免"以为又回到空状态"
                setTimeout(() => {
                    try {
                        alert("♻️ Cache restored\n\nThe page has been reloaded." + (payload ? " Restored " + payload.clips_restored + " CLIP(s) this time." : "") + "\n\nIf the status still shows 0/rendered, reopen the workflow and try \"♻️ Restore Cache\" again.");
                    } catch (_) {}
                }, 600);
                // 清掉 URL 参数, 避免 F5 再次触发
                try {
                    const newUrl = location.href.split("#")[0].replace(/[?&]bsai_h3_restored=1/, "");
                    history.replaceState(null, "", newUrl);
                } catch (_) {}
            }
        } catch (_) {}

        // Official ComfyUI terminal execution events. In particular, pressing
        // Kill/Interrupt raises execution_interrupted and bypasses onExecuted.
        api.addEventListener("execution_interrupted", () => {
            clearTransientRenderingState("Rendering interrupted");
        });
        api.addEventListener("execution_error", () => {
            clearTransientRenderingState("Execution stopped by error");
        });
        hookExecutedSync();
        ensureGlobalSyncPoll();
        // Defensive cleanup: a successful prompt should never leave a stale
        // rendering highlight even if another frontend/backend change prevents
        // the expected node UI callback from arriving.
        api.addEventListener("execution_success", () => {
            clearTransientRenderingState();
            setTimeout(() => { try { syncFromHistory(); } catch (e) {} }, 400);
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
            const prevActiveIndex = runtime.activeClipIndex;
            runtime.activeClipIndex = Number.isFinite(index) ? index : -1;
            runtime.activePhase = String(detail?.phase || "idle");
            // v2.80: 渲染进行中自动展开当前卡片, 让用户能看到进度预览;
            // 其他卡片保持折叠, 避免全量重建拖慢前端。
            if ((runtime.activePhase === "preparing" || runtime.activePhase === "sampling") && index >= 0) {
                const _act = runtime.state.clips[index];
                if (_act && _act.collapsed) _act.collapsed = false;
            }
            // v2.82: 渲染推进时确保当前卡片已构建(增量懒加载场景下,
            // 未加载到的卡片按需追加, 保证状态徽章/进度能更新到该卡片)。
            if (index >= 0 && index >= (Number(runtime._renderedClips) || 0)) {
                try { renderMoreClips(node, runtime, index + 1); } catch (e) {}
            }
            runtime.statusText = String(detail?.message || runtime.statusText || "Ready");
            updatePauseBar(runtime);

            // When switching to a new active clip, clear latent preview state
            // on the previously active clip. This prevents a race condition
            // where the last latent preview frame arrives after the "complete"
            // event, leaving the finished clip stuck showing "渲染中".
            if (prevActiveIndex !== runtime.activeClipIndex && prevActiveIndex >= 0) {
                const prevClip = runtime.state.clips[prevActiveIndex];
                if (prevClip) {
                    delete prevClip._latentPreviewUrl;
                    delete prevClip._latentStep;
                    delete prevClip._latentTotal;
                }
            }

            if (runtime.activePhase === "complete" && index >= 0) {
                const clip = runtime.state.clips[index];
                if (clip) {
                    delete clip._latentPreviewUrl;
                    delete clip._latentStep;
                    delete clip._latentTotal;
                    clip._renderComplete = true;
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

            // Guard: ignore latent preview frames for clips that have already
            // completed. This handles the race condition where the last frame
            // arrives after the "complete" progress event.
            if (clip._renderComplete) {
                return;
            }

            clip._latentPreviewUrl = String(detail?.image || "");
            clip._latentStep = Number(detail?.step ?? 0);
            clip._latentTotal = Number(detail?.total_steps ?? 0);

            render(node, runtime);
            node.graph?.setDirtyCanvas(true, true);
        });

        window.addEventListener("bsai-assets-changed", () => {
            // Delete the old assets' ref2va VAE encodings immediately so a
            // swapped asset library can never reuse stale image latents.
            try { fetch(api.apiURL("/h3_extender/ref2va_cache/clear"), { method: "POST" }).catch(() => {}); } catch (e) {}
            app.graph._nodes.forEach(node => {
                if (ALL_TARGETS.has(node.type) && node.__h3Extender) {
                    delete node.__h3Extender._assetCache;
                    delete node.__h3Extender._h3_assetCache;
                }
            });
            h3FetchAssets().then(() => {
                // Clean up stale @图N/@视频N/@音频N references in prompts
                // after assets are removed from the library
                app.graph._nodes.forEach(node => {
                    if (!ALL_TARGETS.has(node.type) || !node.__h3Extender) return;
                    const runtime = node.__h3Extender;
                    const assetList = runtime._h3_assetCache || { images: [], videos: [], audios: [] };
                    let changed = false;

                    // Clean global prompt
                    if (runtime.state?.global_prompt) {
                        const cleaned = cleanStaleAssetRefs(runtime.state.global_prompt, assetList);
                        if (cleaned !== runtime.state.global_prompt) {
                            runtime.state.global_prompt = cleaned;
                            if (runtime.globalPromptTextarea) {
                                runtime.globalPromptTextarea.value = cleaned;
                                autoResizeTextarea(runtime.globalPromptTextarea);
                            }
                            changed = true;
                        }
                    }

                    // Clean all CLIP prompts
                    if (runtime.state?.clips) {
                        runtime.state.clips.forEach(clip => {
                            if (clip.prompt) {
                                const cleaned = cleanStaleAssetRefs(clip.prompt, assetList);
                                if (cleaned !== clip.prompt) {
                                    clip.prompt = cleaned;
                                    changed = true;
                                }
                            }
                        });
                    }

                    if (changed) {
                        updateHidden(node, runtime);
                        if (typeof runtime.renderGlobalAssetPanel === "function") runtime.renderGlobalAssetPanel();
                        render(node, runtime);
                    }
                });
            });
        });

        // Pre-load the asset list for the referenced-assets left panel.
        h3FetchAssets().then(() => {
            app.graph?._nodes.forEach(node => {
                if (ALL_TARGETS.has(node.type) && node.__h3Extender?.renderGlobalAssetPanel) {
                    node.__h3Extender.renderGlobalAssetPanel();
                }
            });
        });
    },

    async beforeRegisterNodeDef(nodeType, nodeData) {
        // FinalDecode: migrate old workflows missing export_clips widget
        if (ALL_FINAL_TARGETS.has(nodeData.name)) {
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

        if (!ALL_TARGETS.has(nodeData.name)) return;

        // v14.102: 1.55 核心 configure() 用包装器机制 —— bu 实测 configure 后
        // node.onConfigure 被核心重置为核心包装器，buildUi 里的实例级直接赋值
        // (node.onConfigure = fn) 从未被调用 → v14.99 重排/标题/CLIP 渲染全部
        // 不执行（历史工作流 NaN / 尾部错位 / CLIP 区丢失的根因）。在节点注册
        // 期挂原型级代理，使核心包装器经 prototype.onConfigure 链委托到
        // buildUi 注入的实例级 __h3OnConfigureFn。
        if (!nodeType.prototype.__h3MainCfgProxyInstalled) {
            nodeType.prototype.__h3MainCfgProxyInstalled = true;
            const oldMainConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function (info) {
                if (oldMainConfigure) oldMainConfigure.apply(this, arguments);
                const fn = this.__h3OnConfigureFn;
                if (fn) {
                    this.__h3InProxy = true;
                    try { fn.call(this, info); } catch (e) {}
                    finally { this.__h3InProxy = false; }
                }
            };
        }

        const oldConnChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function (side, slot, connected, link_info, ioSlot) {
            if (oldConnChange) oldConnChange.apply(this, arguments);
            // When prompt_source input connection changes, fetch the value
            const runtime = buildUi(this);
            if (!runtime) return;
            // NEW: per-CLIP external prompt — sync the card prompt immediately
            // on connect/disconnect (plus the 500ms poll for upstream edits).
            try {
                const io = this.inputs && this.inputs[slot];
                if (side === LiteGraph.INPUT && io && /^clip_prompt_\d+$/.test(io.name || "")) {
                    // Auto-create CLIP cards to match the connected port index
                    const idx = Number(/^clip_prompt_(\d+)$/.exec(io.name)[1]) - 1;
                    while (runtime.state.clips.length <= idx) {
                        runtime.state.clips.push(newClip(runtime.state.clips.length));
                    }
                    syncExternalPrompts(this, runtime);
                }
            } catch (e) {}
            // v2.122: 移除 v2.117b/c 连线强制 — lip_audio 连接时不再自动关闭
            // 所有 CLIP 的"上下文参考", 每张卡片的 Context Reference 复选框
            // 完全由用户控制(卡片级 + 批量按钮)。对口型+上下文的音频同步由后端
            // 三件套保证: ctx_on 段头部切重叠 → AV latent 尾对齐注入 → 解码混音
            // 按 overlap_samples 跳过段头, 输出与 lip_audio 原始歌曲逐帧对齐。
            // Sync from prompt_source (was incorrectly looking for "global_prompt")
            const psInput = this.inputs?.find(inp => inp.name === "prompt_source");
            if (psInput) {
                runtime._lastPromptSourceText = null; // Force re-sync on next poll
                syncGlobalPromptFromInput(this, runtime);
            }
        };

        const oldCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = oldCreated ? oldCreated.apply(this, arguments) : undefined;

            // Force-update the node title to the new display name
            this.title = "BSAI ComfyUI H3 Film Factory v2.131·v14.171";

            // New nodes must start in Auto resolution mode. Older workflows are
            // still migrated to Manual later in onConfigure when they do not
            // contain the v14.25+ resolution widgets.
            setWidgetValue(this, "resolution_mode", "auto_from_ref");

            const runtime = buildUi(this);
            ensureGlobalSyncPoll();
            removeLegacyImageRefInputs(this);
            // Apply bilingual (EN/中文) labels to all widgets
            bsaiApplyBilingualLabels(this);
            if (runtime) {
                // v2.114 (fix): 从搜索框拖到画布的新建节点只走 onNodeCreated,
                // onConfigure 只在"从工作流 JSON 恢复"时才触发 —— 之前宽度修正只
                // 挂在 onConfigure 上, 所以新建节点的默认宽度永远没被加宽, 工具栏
                // 末尾的「📂 展开CLIP / 📦 收起CLIP」按钮溢出到节点外。这里补上。
                scheduleToolbarWidthFix(this, runtime);
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        // 卡片渲染完(counter/status 文案已填)再量一次, 比 rAF=0 那轮准。
                        scheduleToolbarWidthFix(this, runtime);
                        syncDomHeight(this, runtime, true);
                        // Restore the exact node size the user last adjusted,
                        // so refresh / restart keeps the same CLIP card layout.
                        // Never shrink below the content minimum.
                        const savedH = Number(runtime.state?.nodeHeight || 0);
                        if (Number.isFinite(savedH) && savedH > 0) {
                            const minNodeH = calculateMinHeight(runtime) + NON_CARD_FIXED;
                            let targetH;
                            // v2.105 (fix): 收起态固定 1 卡视口, 绝不恢复旧的
                            // 4 卡高度(savedH 是之前展开时存的 nodeHeight, 直接
                            // Math.max 会把刚收回的 1 卡底板又撑回 3 卡空白)。
                            if (runtime._h3CollapsedAll) {
                                // v2.109: 同上, 补上提示词区实测高度(随后 syncDomHeight 会校正)。
                                targetH = NON_CARD_FIXED + collapsedViewportH(runtime) + BASE_PADDING - GLOBAL_PROMPT_MIN_HEIGHT
                                    + globalPromptSectionH(runtime);
                            } else {
                                targetH = Math.max(savedH, minNodeH);
                            }
                            const w = Math.max(NODE_MIN_WIDTH, Number(this.size?.[0] || NODE_MIN_WIDTH));
                            if (Math.abs(Number(this.size?.[1] || 0) - targetH) > 4) {
                                this.setSize([w, targetH]);
                                syncDomHeight(this, runtime, true);
                            }
                        }
                    });
                });
                // v2.115 (fix): 兜底的初始 render —— 见 _needsInitialRender 注释。
                //
                // 背景: v2.76 为了避免"onNodeCreated/onConfigure 两套分片链并发"
                // 把 onNodeCreated 的初始 render 整段删掉, 认定 onConfigure 是唯一
                // 初始渲染入口。但 onConfigure 只在 graph.configure() 恢复工作流时
                // 触发, 从搜索框拖到画布的新建节点一次都不会走到它 —— 于是
                // runtime.state.clips 里明明有 parseState 兜出来的 1 个默认 CLIP,
                // 画布上却连一张卡片都没有, 底部按钮栏直接顶在提示词区下面,
                // 后面留一大块黑。
                //
                // 这里不能简单地在 onNodeCreated 里同步 render: 那会重新引入
                // v2.76 要修的并发。改成一个"欠一次渲染"的标志 —— onConfigure
                // 渲染时置 false, 下面这个延时兜底只在它仍为 true 时才动手。
                // 恢复路径下 onConfigure 是同步调用的, 500ms 早就跑完, 所以两套
                // 分片链不会同时在跑; 新建路径则由这里补上唯一一次初始渲染。
                const _h3InitialRender = () => {
                    try {
                        if (!runtime || !runtime._needsInitialRender) return;
                        runtime._needsInitialRender = false;
                        runtime.state = parseState(runtime.jsonWidget.value);
                        updateHidden(this, runtime);
                        render(this, runtime, { chunked: true, limit: Number(runtime.state?.clips?.length) || 0 });
                        autoGrowNodeToFitAllClips(this, runtime);
                        syncDomHeight(this, runtime, true);
                    } catch (e) {}
                };
                setTimeout(_h3InitialRender, 500);
                setTimeout(_h3InitialRender, 1800);
                h3FetchAssets();
            }
            return r;
        };

        // Ultimate fallback: apply bilingual labels on every draw (idempotent)
        const oldDrawFG = nodeType.prototype.onDrawForeground;
        nodeType.prototype.onDrawForeground = function (ctx) {
            if (oldDrawFG) oldDrawFG.apply(this, arguments);
            bsaiApplyBilingualLabels(this);
        };

        const oldExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            if (oldExecuted) oldExecuted.apply(this, arguments);
            const runtime = buildUi(this);
            if (!runtime) return;
            // Ensure bilingual labels are applied (fallback)
            bsaiApplyBilingualLabels(this);

            const info = message?.h3_extender_state?.[0];
            if (!info) return;

            if (info.clips_json) {
                runtime.jsonWidget.value = info.clips_json;
                runtime.state = parseState(info.clips_json);
            }
            // Safety: clear replace_mode, merge_output, and restore render_enabled after execution
            runtime.state.merge_output = false;
            // v1.98: 恢复缓存完成后自动复位开关（一次性动作）
            if (info.restore_cache_done) {
                const rcWidget = node.widgets && node.widgets.find((w) => w.name === "restore_cache");
                if (rcWidget) {
                    rcWidget.value = false;
                    if (typeof rcWidget.callback === "function") { try { rcWidget.callback(); } catch (_e) {} }
                }
            }
            if (runtime.state.clips) {
                runtime.state.clips.forEach((c) => {
                    c.replace_mode = false;
                    c.render_enabled = true;
                });
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

// ============================================================
// v2.40: 电影提示词模板功能
// ============================================================

// 打开模板选择器弹窗
function openFilmTemplatePicker(node, runtime, mode, clipIdx) {
    const templates = window.H3_FILM_TEMPLATES;
    if (!templates) {
        alert("Template library not loaded");
        return;
    }

    // 创建遮罩
    const overlay = document.createElement("div");
    overlay.style.cssText = "position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.7);z-index:9999;display:flex;align-items:center;justify-content:center;";

    // 创建弹窗
    const modal = document.createElement("div");
    modal.style.cssText = "width:700px;max-width:90%;max-height:80vh;background:#1e1e2e;border:1px solid #444;border-radius:10px;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 10px 40px rgba(0,0,0,.5);";

    // 标题栏
    const header = document.createElement("div");
    header.style.cssText = "padding:12px 16px;border-bottom:1px solid #333;display:flex;justify-content:space-between;align-items:center;";
    const title = document.createElement("h3");
    title.textContent = mode === "global" ? "✨ Film Prompt Templates (apply to all clips)" : "✨ Film Prompt Templates (apply to this clip)";
    title.style.cssText = "margin:0;font-size:14px;color:#eef;";
    const closeBtn = document.createElement("button");
    closeBtn.textContent = "✕";
    closeBtn.style.cssText = "background:none;border:none;color:#aaa;font-size:18px;cursor:pointer;padding:0 4px;";
    closeBtn.addEventListener("click", () => overlay.remove());
    header.append(title, closeBtn);

    // 分类标签
    const catTabs = document.createElement("div");
    catTabs.style.cssText = "display:flex;gap:4px;padding:8px 16px;border-bottom:1px solid #333;flex-wrap:wrap;";
    
    // 模板列表区
    const listArea = document.createElement("div");
    listArea.style.cssText = "flex:1;overflow-y:auto;padding:12px 16px;display:grid;grid-template-columns:repeat(2,1fr);gap:8px;";

    // 渲染分类标签
    templates.categories.forEach((cat, idx) => {
        const tab = document.createElement("button");
        tab.textContent = cat.icon + " " + cat.name;
        tab.style.cssText = "padding:6px 12px;border:1px solid #444;background:#2a2a3a;color:#ccc;border-radius:6px;cursor:pointer;font-size:12px;";
        tab.addEventListener("click", () => {
            // 切换激活状态
            catTabs.querySelectorAll("button").forEach(b => b.style.background = "#2a2a3a");
            tab.style.background = "#4a4a6a";
            // 渲染模板列表
            renderTemplateList(cat, listArea, node, runtime, mode, clipIdx, overlay);
        });
        catTabs.appendChild(tab);
        // 默认选中第一个
        if (idx === 0) {
            tab.style.background = "#4a4a6a";
            renderTemplateList(cat, listArea, node, runtime, mode, clipIdx, overlay);
        }
    });

    modal.append(header, catTabs, listArea);
    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    // 点遮罩关闭
    overlay.addEventListener("click", (e) => {
        if (e.target === overlay) overlay.remove();
    });
}

// 渲染模板列表
function renderTemplateList(cat, listArea, node, runtime, mode, clipIdx, overlay) {
    listArea.innerHTML = "";
    cat.templates.forEach(tpl => {
        const card = document.createElement("div");
        card.style.cssText = "padding:10px;border:1px solid #3a3a4a;border-radius:6px;background:#252535;cursor:pointer;transition:all .15s;";
        card.innerHTML = '<div style="font-size:12px;color:#eef;font-weight:bold;margin-bottom:4px;">' + tpl.name + '</div>' +
                        '<div style="font-size:10px;color:#999;line-height:1.4;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;">' + tpl.prompt + '</div>';
        card.addEventListener("mouseenter", () => card.style.borderColor = "#6a6a9a");
        card.addEventListener("mouseleave", () => card.style.borderColor = "#3a3a4a");
        card.addEventListener("click", () => {
            applyFilmTemplate(node, runtime, mode, clipIdx, tpl);
            overlay.remove();
        });
        listArea.appendChild(card);
    });
}

// 应用模板到提示词
function applyFilmTemplate(node, runtime, mode, clipIdx, tpl) {
    if (mode === "global") {
        // 全局应用: 用 [电影风格-全局] 包裹
        const wrapped = "[电影风格-全局] " + tpl.prompt + " [/电影风格-全局]";
        runtime.state.clips.forEach((clip, i) => {
            // 移除旧的全局模板
            clip.prompt = removeFilmTemplateByTag(clip.prompt, "电影风格-全局");
            // 加新全局模板
            clip.prompt = wrapped + "\n" + clip.prompt.trim();
        });
        // 全局提示词也加上
        if (runtime.globalPromptTextarea) {
            let gp = runtime.globalPromptTextarea.value;
            gp = removeFilmTemplateByTag(gp, "电影风格-全局");
            runtime.globalPromptTextarea.value = wrapped + "\n" + gp.trim();
            autoResizeTextarea(runtime.globalPromptTextarea);
            runtime.state.global_prompt = runtime.globalPromptTextarea.value;
        }
        runtime.statusText = "Applied global template to all clips: " + tpl.name;
    } else {
        // 单 CLIP 应用: 先弹窗选择
        const choice = confirm(
            'How to apply the template to CLIP ' + (clipIdx + 1) + '?\n\n' +
            'OK = merge with the global template (keep the global template, add this clip template)\n' +
            'Cancel = replace the global template (remove it, keep only this clip template)'
        );
        
        const wrapped = "[电影风格-单CLIP] " + tpl.prompt + " [/电影风格-单CLIP]";
        const clip = runtime.state.clips[clipIdx];
        if (!clip) return;
        
        if (choice) {
            // 合并: 保留全局模板, 加单CLIP模板
            clip.prompt = removeFilmTemplateByTag(clip.prompt, "电影风格-单CLIP");
            clip.prompt = wrapped + "\n" + clip.prompt.trim();
            runtime.statusText = "Merged template into CLIP " + (clipIdx + 1) + ": " + tpl.name;
        } else {
            // 覆盖: 移除全局模板, 加单CLIP模板
            clip.prompt = removeFilmTemplateByTag(clip.prompt, "电影风格-全局");
            clip.prompt = removeFilmTemplateByTag(clip.prompt, "电影风格-单CLIP");
            clip.prompt = wrapped + "\n" + clip.prompt.trim();
            runtime.statusText = "Replaced template in CLIP " + (clipIdx + 1) + ": " + tpl.name;
        }
    }

    updateHidden(node, runtime);
    render(node, runtime);
    autoGrowNodeToFitAllClips(node, runtime);
    if (runtime.statusEl) runtime.statusEl.textContent = runtime.statusText;
}

// 按标签名移除电影风格模板区块
function removeFilmTemplateByTag(prompt, tagName) {
    if (!prompt) return prompt || "";
    const re = new RegExp("\\[" + tagName + "\\][\\s\\S]*?\\[\\/" + tagName + "\\]", "g");
    return prompt.replace(re, "").trim();
}

// v2.40: 单 CLIP 模板面板 (左侧"模板"tab)
function renderClipTemplatePanel(container, clip, node, runtime, textarea, clipIdx) {
    container.innerHTML = "";
    const templates = window.H3_FILM_TEMPLATES;
    if (!templates) {
        container.innerHTML = '<div style="color:#666;font-size:11px;text-align:center;padding:8px;">Template library not loaded</div>';
        return;
    }

    // 标题
    const hdr = document.createElement("div");
    hdr.style.cssText = "font-size:11px;color:#888;margin-bottom:6px;";
    hdr.textContent = "Film Templates (click to apply to this CLIP)";
    container.appendChild(hdr);

    // 分类 + 模板
    templates.categories.forEach(cat => {
        const catHdr = document.createElement("div");
        catHdr.style.cssText = "font-size:10px;color:#777;margin:6px 0 3px;font-weight:bold;";
        catHdr.textContent = cat.icon + " " + cat.name;
        container.appendChild(catHdr);

        cat.templates.forEach(tpl => {
            const btn = document.createElement("button");
            btn.textContent = tpl.name;
            btn.style.cssText = "display:block;width:100%;text-align:left;padding:3px 6px;margin-bottom:2px;font-size:10px;color:#ccc;background:#2a2a3a;border:1px solid #3a3a4a;border-radius:3px;cursor:pointer;";
            btn.addEventListener("mouseenter", () => btn.style.background = "#3a3a5a");
            btn.addEventListener("mouseleave", () => btn.style.background = "#2a2a3a");
            btn.addEventListener("click", () => {
                applyFilmTemplate(node, runtime, "clip", clipIdx, tpl);
            });
            container.appendChild(btn);
        });
    });
}
