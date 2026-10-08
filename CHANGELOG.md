# CHANGELOG ｜ 更新日志

All notable changes, bilingual. 所有重要版本双语说明。

---

## 🚨 铁律 / IRON RULE

**未经用户验收合格,绝不动 git push(本地 commit 也先询问)。**
**Never push to git without explicit user acceptance. Ask before local commit too.**

这条规则在刘百声的所有项目中持续生效,直到被显式撤销。
This rule applies across all 刘百声 projects until explicitly revoked.

---


### v2.116 / v14.82 (2026-10-08) — lip_audio 独占歌曲源 + 模型环境音垫底混音 / lip_audio as Exclusive Song Source + Model Ambience Bed Mix

**核心：一旦把外部歌曲接到 lip_audio，所有 CLIP（含 @图N 角色）的口型完全由这首歌驱动；ref_audio 端口和 @音频N 资产库音频自动忽略，绝不串歌；逐段预览和最终出片音轨 = 歌曲主唱（满音量）+ 模型生成的环境音/音效（压低到 15%）作为 MV 辅助音；缺段直接报错而不是悄悄回退。**
**Core: once an external song is connected to lip_audio, every CLIP (including @图N characters) lip-syncs exclusively to that song; the ref_audio port and @音频N asset-library audio are auto-ignored so no other audio can leak in; per-clip previews and the final output track = lead song at full volume + model-generated ambience/SFX ducked to 15% as MV bed audio; a missing segment raises an error instead of silently falling back.**

---

#### 后端 / Backend

- **lip_audio 独占音频源 / lip_audio exclusive audio source**：连接 lip_audio 后立即把全局 `ref_audio` 置 None，`@音频N` 资产库注入同步跳过；每段 CLIP 的音频条件只能是 lip 切出的对应片段，段缺失直接 `RuntimeError`。 / Once lip_audio is connected, the global `ref_audio` is dropped and `@音频N` asset injection is skipped; every CLIP's audio conditioning is forced to its own lip segment, raising on a missing segment.
- **逐段预览 MP4 混音 / per-clip preview MP4 mix**：`_decode_single_clip_to_blob` 新增 `lip_audio_segment` 参数，模型解码出的环境音与对应歌曲片段自动混音（重采样/长度/声道对齐），歌曲满音量、模型音 ×0.15。 / `_decode_single_clip_to_blob` now accepts `lip_audio_segment`; the model-decoded ambience and the matching song segment are auto-mixed (resampled/length/channel aligned), lead full volume + model audio ×0.15.
- **最终输出混音 / final output mix**：最终 AUDIO 输出从"纯替换为歌曲"改为"歌曲 + 模型拼接音频 ×0.15"，模型的环境音不再丢弃。 / The final AUDIO output changed from "pure song replacement" to "song + concatenated model audio ×0.15"; model ambience is no longer discarded.
- **缓存提醒 / cache reminder**：连接 lip_audio 时若已有 validated 缓存 CLIP，日志明确提示需要取消校验重渲，否则口型与新歌不匹配。 / When lip_audio connects and some CLIPs are already validated/cached, the log warns to uncheck them and re-render so lips match the new song.
- **Bug 修复 / bug fix**：修复首次接入 lip_audio 时引用未赋值变量 `loop_end` 导致的 `UnboundLocalError`。 / Fixed an `UnboundLocalError` on `loop_end` when first connecting lip_audio.

---



### v2.72 → v2.115 / v14.85 (2026-09-30) — 崩溃修复 + 独立渲染正确性 + 前端底板全高 + 展开/收起CLIP按钮紧贴 + 全局提示词区独立折叠 + 高度实测 + 默认展开/宽度保证按钮完整可见 + 新建节点渲染 CLIP1 卡片 / Crash Fixes + Per-Clip Render Correctness + Full-Height Backdrop + Tight Collapse/Expand Toggle + Independent Global-Prompt Fold + Measured Heights + Expanded-by-Default & Toolbar-Fit Width + CLIP1 Card on New Nodes

**核心：崩溃后断点续跑不丢链；独立渲染"渲谁是谁"且渲染完静默等待；节点黑色底板跟随 CLIP 数量；展开/收起CLIP按钮点击后节点高度紧贴；全局提示词区不再随 CLIP 收起而消失，改为独立的「▲/▼」折叠按钮；收起态与展开态高度都实测，底部按钮栏不裁切、底板盖满节点；节点默认「展开CLIP」状态，默认宽度保证工具栏末尾的「📦 收起CLIP / 📂 展开CLIP」按钮完整可见。**
**Core: resume after crash without losing the chain; per-clip render outputs exactly the chosen clip and waits silently after finishing; the node's dark backdrop tracks the CLIP count; the "Collapse/Expand CLIP" buttons snap to the correct node height; the global prompt area no longer disappears when CLIPs are collapsed — it now has its own "▲/▼" fold button; both collapsed and expanded heights are measured so the bottom bar is never clipped and the backdrop covers the whole node; the node now opens **expanded**, and its default width guarantees the trailing "📦 收起CLIP / 📂 展开CLIP" button is fully visible.**

---

#### 🔧 后端 / Backend

- **hostbuf 崩溃修复（v2.72-v2.74）**：TE 权重重载路径 `hostbuf_file_reader_read failed` 崩溃修复，长链续跑不再闪退。/ Crash fix for the `hostbuf_file_reader_read failed` TE reload path — long-chain resume no longer crashes.
- **独渲"渲谁是谁"（v2.75）**：单独渲染 CLIP29 曾输出 CLIP1 内容（preview/MP4 按局部链索引取段）。现在 async encode 队列携带三元组（done_event、链内索引、全局 CLIP 索引），preview/MP4 提取/命名全部按全局索引——渲谁就是谁。/ Solo-rendering CLIP29 used to output CLIP1 (preview/MP4 indexed by local-chain index). The encode queue now carries (done_event, chain index, global CLIP index) and preview/MP4 extraction/naming use the global index — you get exactly the clip you chose.
- **独立渲染后不自动合并（v2.76）**：单独渲染某 CLIP 完成后不再自动合并/输出全部 clip，只保留 latent 缓存 + 卡片预览，静默等待用户下一步指令（合并输出 / 续跑 / 渲别的 clip）。/ After a solo render the node no longer auto-merges or outputs everything — it keeps the latent cache + card preview and silently waits for your next command (merge / continue / another clip).
- **收尾元组解包崩溃（v14.77）**：修复 `_pending_enc` 三元组在收尾遍历处的二元解包 `too many values to unpack`——渲染成果不受影响（缓存/预览先于崩溃已提交）。/ Fixed the binary unpack of the 3-tuple `_pending_enc` at the tail loop (`too many values to unpack`) — rendered results are unaffected (cache/preview commit before the crash point).

#### 🎨 前端 / Frontend

- **节点黑色底板跟随 CLIP 数量（v2.105）**：默认打开 = 1 卡视口 + 1 卡底板；点「展开CLIP」= 全部 CLIP 显示、底板撑到全高；收起态任何代码路径都无法把底板缩到 <1 卡（防止旧 nodeHeight/布局抖动闪回 0 卡）。/ The node backdrop tracks the CLIP count: default open = 1-card viewport with a 1-card backdrop; "Expand CLIP" shows every CLIP with a full-height backdrop; in collapsed mode no code path can shrink the backdrop below 1 card (no more 0-card flashback from stale nodeHeight/layout jitter).
- **拖拽画布不闪回（v2.105）**：移动画布/重布局瞬间节点不再闪回 1 卡再弹回。 / Dragging the canvas no longer flashes the node back to 1 card before recovering.
- **展开态内容不溢出底板（v2.105）**：展开时 root/cards 恢复 auto 高度，30 卡内容全高撑起节点，不再溢出到黑色底板之外。 / Expanded state: root/cards revert to auto height so the full card stack fills the backdrop instead of overflowing it.
- **「收起CLIP」按钮紧贴卡片底板（v2.107）**：之前点击「收起CLIP」后 `afterResize` 钩子把 `runtime._userResize` 标 true，让 `syncDomHeight` legacy 收起分支误判为"用户拖拽"，走错位公式 `cards = node.size[1] - NON_CARD_FIXED ≈ 215px`（实际应该是 1 卡视口 379px），节点底部空出 ~140px 黑边。修复后 click handler 显式置 `runtime._userResize = false` 再调 `syncDomHeight`，走 `collapsedViewportH=379` 这条确定性公式，节点高度紧贴 1 张卡 + 工具栏 + 底部按钮栏。/ The "Collapse CLIP" button now snaps the node to a 1-card-tight height. Previously `afterResize` flagged `_userResize=true` and made `syncDomHeight` use the wrong formula `cards = node.size[1] - NON_CARD_FIXED ≈ 215px` (should be 379px for 1 card), leaving ~140px of black gap below the cards. The click handler now forces `_userResize=false` before calling `syncDomHeight`, which takes the `collapsedViewportH=379` deterministic branch.
- **「展开CLIP」按钮底板撑到全高（v2.107）**：之前点击「展开CLIP」后 `node.size = [w, last_y + root.scrollHeight]`，但 `root.scrollHeight` 此时只有 ~90px（cards 还是收起态的 379px 固定高度），直接把节点撑回 690px，30 张卡片溢出到底板外、画布出现一大段黑空白。修复后 click handler 调 `autoGrowNodeToFitAllClips`（按 30 卡 × 380px + 285 固定 + 36 填充算 ≈12321px 设 node.size）再调 `syncDomHeight`，让 legacy 展开分支用真实 DOM `scrollHeight`（cards.style.height 已设 auto）撑高，黑色底板跟随全量卡片。/ The "Expand CLIP" button now grows the node to fit all 30 cards. Previously `node.size = [w, last_y + root.scrollHeight]` used a stale ~90px scrollHeight (cards still at collapsed 379px), shrinking the node to 690px while cards overflowed the backdrop. The click handler now calls `autoGrowNodeToFitAllClips` (which computes the full card-stack height) then `syncDomHeight`, which uses the real DOM scrollHeight (cards.style.height=auto) to grow the backdrop to match all cards.
- **「收起/展开CLIP」二次 setSize 抑制（v2.107 第二轮）**：第一轮修复后用户验收发现 bug 仍存在。根因是 click handler 调 `syncDomHeight` 设完 `node.size` 后触发 `afterResize` 钩子 → 钩子里 `_userResize = true`(line 6369 无条件) → 再调 `syncDomHeight(forceMin=false)` → 第二次进入 legacy 收起分支时 `_userResize=true` 走错位公式 `_vh2 = node.size[1] - NON_CARD_FIXED = 1075-285 = 790`,contentH=886,targetH3=1486,节点被二次撑高 +411px(收起 bug 仍在)/展开侧把 autoGrow 设的 12321 覆盖为 _fullNodeH=375,卡片全部溢出底板。修复加 `_h3BtnResizeInFlight` guard:click handler 设 `true`,afterResize 钩子看到 `true` 直接 return(只做"收起态不低于 1 卡最小高度"的兜底,不再二次调 syncDomHeight),setTimeout(0) 释放 guard。/ After the first round of v2.107 fixes the user re-tested and the bug persisted. Root cause: click handler calls `syncDomHeight` which writes `node.size`, triggering `afterResize` → which unconditionally sets `_userResize=true` (line 6369) → then calls `syncDomHeight(forceMin=false)` again → on this second call `_userResize=true` takes the wrong formula `_vh2 = node.size[1] - NON_CARD_FIXED`, inflating the node by ~411px in collapse mode and shrinking it to ~375px in expand mode. Fix: added `_h3BtnResizeInFlight` guard — the click handler sets it true, the afterResize hook checks it first and bails out (only doing the "minimum-height floor in collapse mode" sanity check), and the guard is released via setTimeout(0).
- **全局提示词区独立折叠（v2.108）**：用户反馈「收起状态全局提示词不见了」。根因是收起 CLIP 分支（nodes2 line 4982 / legacy line 5050 / onConfigure line 6583 / afterResize line 6417）无条件把 `globalPromptSection.style.display = "none"`，而展开分支负责恢复——CLIP 收起就把提示词区一起藏了。现在显隐完全解耦：新增 `applyGlobalPromptVisibility(runtime)` 统一裁决，只看用户折叠标志 `_h3GpUserCollapsed`（默认 `false` = 始终显示）；新增 `gpCollapseBtn`（`▲`/`▼`，在「全局提示词」标签右侧）让用户手动折叠/展开提示词区换取 CLIP 卡片可视高度；收起态高度公式加上 `globalPromptSectionH(runtime)` 实测高度，提示词区不再被底板裁掉；顺带把历史上从未赋值的 `runtime.gpResizer` 挂上（老代码的把手显隐一直是死代码）。折叠状态是会话内 UI 偏好，不写工作流 JSON（与 `gpDragHeight` 一致），刷新后回到默认展开。/ The user reported the global prompt area vanishing in collapsed mode. Root cause: every collapse branch hard-coded `display = "none"` on `globalPromptSection` while only the expand branch restored it. Now visibility is fully decoupled from the CLIP toggle: `applyGlobalPromptVisibility(runtime)` is the single decision point driven only by the new `_h3GpUserCollapsed` flag (default `false` = always visible), a new `▲`/`▼` button sits next to the "全局提示词" label for manual folding, the collapsed height formula now adds the measured `globalPromptSectionH(runtime)` so the prompt area is never clipped, and the historically-unassigned `runtime.gpResizer` is finally exposed. The fold state is a session-only UI preference (not written to the workflow JSON) and resets to expanded on reload.
- **收起态 bottomBar 被裁掉（v2.109）**：v2.108 上线后用户发现收起态底部「CLIPS | 总时长 …」+ 添加/删除按钮整条消失（截图红圈处一片空白）。根因是 v2.108 把手工高度公式漏算了几项：`globalPromptSection` 的 `margin-bottom:6px`、toolbar 的**真实**高度（按钮多时换行，超过 `TOOLBAR_HEIGHT=50` 这个常量）、bottomBar 的**真实**高度（`getBoundingClientRect()` 不含 margin，常量 35 也只是估值）。公式偏小 + `root.style.overflow:hidden` → 把最后一个子元素 bottomBar 整条裁掉。修复：新增 `applyCollapsedLayout(runtime, viewportH)` 统一处理收起态布局 —— cards 固定视口高 + `flex:0 0 auto`（不会被拉伸）、root 置 `height:auto`，强制一次 reflow（读 `offsetHeight`）后读 `root.scrollHeight` 作为真实内容全高，取 `max(实测, 兜底公式)`。收起态 cards 高度写死且不参与拉伸，所以不存在 v2.29 注释里的 `scrollHeight` 正反馈循环。三处调用点（onNodeCreated 同步收起 / onConfigure 恢复收起 / syncDomHeight legacy 收起分支）统一走这个函数，rAF 层的两处 targetH 兜底也补上了 `globalPromptSectionH()`，避免公式再次各自漂移。/ After v2.108 shipped, the user found the collapsed-state bottom bar ("CLIPS | 总时长 …" plus the add/delete buttons) entirely gone. Root cause: the v2.108 hand-written height formula missed `globalPromptSection`'s `margin-bottom:6px`, the toolbar's real height (buttons wrap past the `TOOLBAR_HEIGHT=50` constant), and the bottom bar's real height (`getBoundingClientRect()` excludes margins, and the 35px constant is only an estimate). The too-small height plus `overflow:hidden` clipped the last child. Fix: a new `applyCollapsedLayout(runtime, viewportH)` centralises the collapsed layout — cards get a fixed viewport height with `flex:0 0 auto` (never stretched), root goes `height:auto`, one forced reflow, then `root.scrollHeight` is read as the true content height and `max(measured, fallback)` is used. Because the collapsed cards height is fixed and non-stretching, the `scrollHeight` feedback loop described in the v2.29 comment does not apply. All three call sites now share this function, and the two rAF-layer targetH fallbacks also add `globalPromptSectionH()`.
- **展开态黑色底板盖不住节点底部（v2.110）**：收起态在 v2.109 修好后，展开态仍有问题 —— 节点外框在原生 widgets 之后就结束，toolbar / 全局提示词区 / CLIP 卡片 / 底部按钮栏全部溢出到框外。展开分支有四处缺陷：(1) `cards.style.flex = "1 1 auto"` 会让 cards 在 root 里被拉伸，实测 `scrollHeight` 不再等于真实内容高；(2) 高度换算 `domHeight = max(available, rootFullH - NON_CARD_FIXED)` 再 `+ NON_CARD_FIXED` 绕了一圈，而 `NON_CARD_FIXED=285` 是估值常量（toolbar 50 + 提示词区 200 + 底栏 35），与真实内容无关，换算结果可能偏小；(3) 读 `scrollHeight` 前没强制 reflow，拿到的是收起态残留布局的旧值；(4) 末尾有一行遗留的 `runtime.domHeight = available;`，把刚算好的值又覆盖回去。修复：把展开分支改成与收起态同构的实测写法 —— overflow 先设好、cards 改 `0 0 auto`、强制 reflow、读真实 `scrollHeight`，节点高 = `y + 内容全高 + BOTTOM_PAD`（并对当前高度取 `max`，绝不缩小用户已拉大的节点）；删掉旧的 `NON_CARD_FIXED` 换算和那行遗留覆盖；并在真正改动了 size 时安排一次下一帧校正（同一帧内 `last_y` 可能还是改 size 前的旧值）。/ With the collapsed state fixed in v2.109, the expanded state still broke — the node frame ended right after the native widgets and the toolbar / prompt area / CLIP card / bottom bar all overflowed outside it. The expanded branch had four defects: `cards.style.flex = "1 1 auto"` let cards stretch so the measured `scrollHeight` was no longer the real content height; the height math `max(available, rootFullH - NON_CARD_FIXED) + NON_CARD_FIXED` round-tripped through a 285px *estimated* constant unrelated to the real content and could come out too small; `scrollHeight` was read without a forced reflow so it reflected the leftover collapsed layout; and a leftover `runtime.domHeight = available;` overwrote the just-computed value. The expanded branch now mirrors the collapsed fix — set overflow first, `cards` to `0 0 auto`, force a reflow, read the real `scrollHeight`, and set the node height to `y + content + BOTTOM_PAD` (taking `max` with the current height so a user-enlarged node is never shrunk). The old `NON_CARD_FIXED` math and the leftover overwrite are gone, and a next-frame correction is scheduled only when the size actually changed (the same frame's `last_y` can still be the pre-resize value).
- **默认展开 + 宽度保证按钮完整可见（v2.111）**：两点改动。(1) **默认状态改为「展开CLIP」** —— 原先 runtime 初始化、onNodeCreated 同步块、onConfigure 的三处标记、以及按钮的初始文案和 `clipsCollapsed` 变量都写死为收起态。现在统一改为展开：按钮初始显示「📦 收起CLIP」（按钮显示的是"下一步可点的动作"），初始化不再套用收起态的 `applyCollapsedLayout` 固定视口，高度交给 `syncDomHeight` 展开分支实测。(2) **宽度下限** —— toolbar 是 `display:flex` + 默认 `nowrap`，而 flex 子项默认 `flex-shrink:1`，节点宽度不够时按钮不是换行而是被逐个压缩，排在 `pauseBar`/`status` 之前的「📂 展开CLIP / 📦 收起CLIP」首当其冲被压扁甚至裁掉。新增 `ensureToolbarWidth()` 实测工具栏自然宽度当宽度下限：直接读 `scrollWidth` 只会得到容器宽度（子项已被压缩），所以临时把 toolbar 设成 `width:max-content` 量完 `offsetWidth` 再还原，比拍魔数更稳（按钮文案增删、status 文本长短、DPI 差异都会自动跟随）。只加宽不缩窄，保留用户手动拉宽的宽度；在 onConfigure 布局稳定后再复测一次，因为首次调用时 DOM 可能还没排版。/ Two changes. (1) **The default state is now expanded** — the runtime init, the onNodeCreated sync block, the three onConfigure markers, the button's initial label, and the `clipsCollapsed` variable were all hard-coded to collapsed. They now all default to expanded: the button starts as "📦 收起CLIP" (a button shows the *next* action), and initialisation no longer applies the collapsed `applyCollapsedLayout` fixed viewport — height is measured by the `syncDomHeight` expanded branch. (2) **Width floor** — the toolbar is `display:flex` with default `nowrap`, and flex children default to `flex-shrink:1`, so when the node is too narrow buttons are compressed one by one rather than wrapping, and the trailing "📂 展开CLIP / 📦 收起CLIP" button (ordered before `pauseBar`/`status`) gets squashed or clipped first. A new `ensureToolbarWidth()` measures the toolbar's natural width as the floor: reading `scrollWidth` directly would only return the container width (children already shrunk), so it temporarily sets the toolbar to `width:max-content`, reads `offsetWidth`, and restores it — more robust than a magic number (button text changes, status length, DPI all follow automatically). It only widens, never narrows, and re-measures on the next frame in onConfigure because the first call may run before the DOM is laid out.
- **宽度修正改为多时间点重试（v2.112）**：v2.111 上线后用户实测发现宽度修正**完全没生效** —— 新节点仍然是窄的，工具栏按钮被压成两行叠字、还横向溢出到节点右框外（用户截图确认）。根因是 `ensureToolbarWidth()` 开头用 `tb.isConnected` 早退，而 DOM widget 是 ComfyUI **绘制时**才挂进 document 的，onNodeCreated / onConfigure 早期调用时 `isConnected` 为 false，函数直接 return，宽度永远没被修正。修复：去掉 `isConnected` 早退（连不上时 `offsetWidth` 自然为 0，由 `natural > 0` 自然跳过），并新增 `scheduleToolbarWidthFix(node, runtime)` 在 0 / 120 / 400 / 900 / 1800 / 3200ms 六个时间点各实测一次 —— 因为按钮文案、`counter`（"总时长 15s (1 clip)"）文本、`pauseBar` 按钮显示状态都会在渲染过程中陆续变化，靠后几个重试点覆盖。onNodeCreated 与 onConfigure 两处调用点都改用该调度。/ After v2.111 shipped the user tested and found the width fix **never took effect** — new nodes were still narrow, toolbar buttons compressed into two-line stacked text and overflowing horizontally past the node right frame (confirmed by the user screenshots). Root cause: `ensureToolbarWidth()` bailed out early on `tb.isConnected`, but the DOM widget is attached to the document by ComfyUI only at *draw* time, so `isConnected` was false during the early onNodeCreated / onConfigure calls and the function returned without ever correcting the width. Fix: drop the `isConnected` bail-out (when disconnected `offsetWidth` is naturally 0 and the `natural > 0` check skips it anyway) and add `scheduleToolbarWidthFix(node, runtime)`, which re-measures at 0 / 120 / 400 / 900 / 1800 / 3200 ms — button labels, the `counter` text and the pauseBar button visibility all settle during rendering, so the later retries cover them. Both the onNodeCreated and onConfigure call sites now use the scheduler.
- **逐子元素测量自然宽度（v2.113）**：v2.112 的 `measureToolbarNaturalWidth` 仍然量不准。原因是它把整个 toolbar 临时设成 `width:max-content` 再读 `offsetWidth`，但 toolbar 里的 `status` 是**弹性留白项**（`margin-left:auto` + `max-width:45%` + `text-overflow:ellipsis`），在 `max-content` 下依然参与压缩/反向影响结果，等于量了个循环依赖。改成逐个子元素处理：显式 `margin-left:auto` 或 `max-width` 是 <100% 百分比的判为弹性项**跳过**，其余子元素逐个临时设 `flex:0 0 auto` + `width:max-content` 让它按自身内容撑开，再连同 gap 求和；弹性项改用固定额度 `TOOLBAR_STATUS_ALLOWANCE=150` 计入（否则一段长状态文案会把节点撑到几千像素）。重试点延长到 0/120/400/900/1800/3200/6000/10000ms，并加 `ResizeObserver` 兜底（rAF 合并同帧触发，存 `runtime._toolbarWidthRO`）。/ v2.112's `measureToolbarNaturalWidth` still measured wrong. It set the whole toolbar to `width:max-content` and read `offsetWidth`, but `status` is a **flexible filler** (`margin-left:auto` + `max-width:45%` + `text-overflow:ellipsis`) that still participates under `max-content` — a circular measurement. Now each child is handled individually: anything with an explicit `margin-left:auto` or a `<100%` percentage `max-width` is treated as flexible and **skipped**; every other child is temporarily set to `flex:0 0 auto` + `width:max-content` so it expands to its own content, then summed with gaps. The flexible item is instead covered by a fixed `TOOLBAR_STATUS_ALLOWANCE=150` (otherwise one long status string would stretch the node to thousands of pixels). Retries extended to 0/120/400/900/1800/3200/6000/10000 ms, plus a `ResizeObserver` fallback (rAF-merged, stored in `runtime._toolbarWidthRO`).
- **默认宽度修复从未被调用（v2.114，本轮真正的根因）**：v2.113 之后用户第三次反馈「还是窄的」。这次在真实浏览器里复现并定位到根因：**`scheduleToolbarWidthFix` 只挂在 `onConfigure` 上，而 `onConfigure` 只在"从工作流 JSON 恢复节点"时才触发**。用户描述的场景是「从搜索框把节点拖到画布」，这条路径只走 `onNodeCreated` —— 宽度修正一次都没跑过，所以 v2.111/v2.112/v2.113 三轮全部无效。修复：`onNodeCreated` 在 `buildUi` 之后立刻调一次 `scheduleToolbarWidthFix`，双 rAF 回调里（卡片渲染完、counter/status 文案已填）再调一次。同时加**「量到即收手」闩锁**：`ensureToolbarWidth` 返回值改成"是否成功量到有效自然宽度"，一旦量到就停掉全部重试并 `disconnect()` 掉 `ResizeObserver` —— 否则长驻的 ResizeObserver 会在用户手动把节点拉窄时立刻把宽度顶回去，变成跟用户抢拖拽把手；默认宽度是落地态需求，量到一次就够，之后把控制权完全交回用户。顺带把节点标题从写死的 `v2.105` 升到 `v2.114`，方便一眼确认浏览器里加载的是哪一版（之前标题一直显示 v2.105，排查时极具误导性）。**浏览器实测**：从搜索框新建节点，等待全部重试点后，工具栏 11 个可见按钮的 y 坐标全部落在同一行（479/480，高度 5–6px@29% 缩放），全宽元素 `gpResizer` 右边界 x=778，工具栏从 x=338 起排到 x=661 之后还有 3 个按钮，合计正好落在节点右框以内；节点宽度从默认约 300 提升到约 1480（画布单位）。
- **新建节点不渲染 CLIP 卡片（v2.115，本轮第二个根因）**：宽度修好后用户发现新建节点里 **CLIP1 卡片整块消失** —— 全局提示词区下面直接就是底部按钮栏，后面留一大块黑。根因在 v2.76：当时为避免「onNodeCreated/onConfigure 两套分片链并发」把 `onNodeCreated` 的初始 `render()` 整段删掉，注释写的是「onConfigure 是唯一初始渲染」。但 `onConfigure` **只在 `graph.configure()` 恢复工作流时触发**，从搜索框拖到画布的新建节点一次都走不到它 —— 于是 `parseState` 兜出来的那个默认 CLIP（`clips: [newClip(0)]`，`buildUi` 里 `state = parseState(jsonWidget.value)` 已经解析出来了）从来没有被构建成卡片 DOM，状态里有、画布上没有。修复不能简单地在 `onNodeCreated` 里同步 `render`（那会重新引入 v2.76 要修的并发），改成「欠一次渲染」标志 `runtime._needsInitialRender`：`buildUi` 初始化为 `true`，`onConfigure` 渲染前置 `false`，`onNodeCreated` 里挂一个 500ms / 1800ms 的延时兜底，只在标志仍为 `true` 时才 `parseState` → `updateHidden` → `render` → `autoGrowNodeToFitAllClips` → `syncDomHeight` 并清标志。恢复路径下 `onConfigure` 是同步调用的，500ms 早已跑完，两套分片链不会并发；新建路径则由兜底补上唯一一次初始渲染。**浏览器实测**：从搜索框新建节点后 DOM 出现 `h3-extender-card[data-clip-index="0"]`（▼ CLIP 1、资产/模板、提示词 textarea、字幕/Subtitle、上下文参考、参考帧提取、Seed、Duration、Validated、预览），counter 变成 `1 clip • 0 refs`，底栏变成 `CLIPS | 总时长 10s (1 clip)`；底栏按钮 y=2076 紧贴卡片 Validated 行 y=2011（差 65px，即卡片预览区本身），**没有黑色空洞**；结构与顺序（toolbar → 已引用资产/全局提示词 → CLIP1 卡片 → 底部按钮栏）与目标截图一致。/ After the width fix, the user found the **CLIP1 card entirely missing** on a new node — the bottom bar sat right under the global prompt area with a large black void below it. Root cause dates to v2.76: to avoid "two concurrent chunked render chains from onNodeCreated/onConfigure", the initial `render()` was removed from `onNodeCreated` on the assumption that "onConfigure is the only initial render". But `onConfigure` **only fires during `graph.configure()` workflow restore** — a node dragged from the search box never reaches it, so the default clip that `parseState` already produced (`clips: [newClip(0)]`, parsed in `buildUi` via `state = parseState(jsonWidget.value)`) was never turned into card DOM: present in state, absent from the canvas. The fix cannot simply be a synchronous `render` in `onNodeCreated` (that would reintroduce exactly the concurrency v2.76 fixed). Instead it uses an "owes one render" flag `runtime._needsInitialRender`: initialised `true` in `buildUi`, set `false` by `onConfigure` just before it renders, and a deferred 500 ms / 1800 ms fallback in `onNodeCreated` that only acts while the flag is still `true` (`parseState` → `updateHidden` → `render` → `autoGrowNodeToFitAllClips` → `syncDomHeight`, then clears the flag). On the restore path `onConfigure` runs synchronously, long before 500 ms, so the two chunked chains never run together; on the create path the fallback supplies the single missing initial render. **Browser-verified**: a node created from the search box now produces `h3-extender-card[data-clip-index="0"]` (▼ CLIP 1, 资产/模板, prompt textarea, 字幕/Subtitle, 上下文参考, 参考帧提取, Seed, Duration, Validated, preview), the counter reads `1 clip • 0 refs`, and the bottom bar reads `CLIPS | 总时长 10s (1 clip)`. The bottom bar button sits at y=2076 right below the card's Validated row at y=2011 (65 px apart — the card's own preview area), so there is **no black void**. The structure and order (toolbar → 已引用资产/全局提示词 → CLIP1 card → bottom bar) matches the target screenshot./ v2.113 was followed by the user's third "still narrow" report. This time it was reproduced in a real browser and the real root cause found: **`scheduleToolbarWidthFix` was only wired to `onConfigure`, and `onConfigure` only fires when a node is restored from a workflow JSON.** The user's scenario is dragging the node from the search box onto the canvas, which goes through `onNodeCreated` only — the width fix never ran once, which is why v2.111/v2.112/v2.113 all did nothing. Fix: `onNodeCreated` now calls `scheduleToolbarWidthFix` right after `buildUi`, and again inside the double-rAF (after cards render and counter/status text is filled). A **"stop as soon as measured" latch** was added: `ensureToolbarWidth` now returns whether it successfully measured a valid natural width, and on the first success all retries stop and the `ResizeObserver` is disconnected — otherwise a long-lived ResizeObserver would immediately push the width back the moment the user narrows the node, fighting them for the resize handle. The default width is a one-shot layout requirement; after the first measurement control returns entirely to the user. The node title was also bumped from a hard-coded `v2.105` to `v2.114` so the loaded build is obvious at a glance (the stale title was actively misleading during debugging). **Verified in a real browser**: after creating the node from the search box and letting all retries run, the 11 visible toolbar buttons all sit on one line (y = 479/480, height 5–6 px at 29% zoom), the full-width `gpResizer` right edge is x=778, and the toolbar starting at x=338 runs past x=661 with 3 more buttons, landing just inside the node's right frame; the node grew from the ~300 default to ~1480 canvas units.

---

---

#### 🔧 后端 / Backend

- **hostbuf 崩溃修复（v2.72-v2.74）**：TE 权重重载路径 `hostbuf_file_reader_read failed` 崩溃修复，长链续跑不再闪退。/ Crash fix for the `hostbuf_file_reader_read failed` TE reload path — long-chain resume no longer crashes.
- **独渲"渲谁是谁"（v2.75）**：单独渲染 CLIP29 曾输出 CLIP1 内容（preview/MP4 按局部链索引取段）。现在 async encode 队列携带三元组（done_event、链内索引、全局 CLIP 索引），preview/MP4 提取/命名全部按全局索引——渲谁就是谁。/ Solo-rendering CLIP29 used to output CLIP1 (preview/MP4 indexed by local-chain index). The encode queue now carries (done_event, chain index, global CLIP index) and preview/MP4 extraction/naming use the global index — you get exactly the clip you chose.
- **独立渲染后不自动合并（v2.76）**：单独渲染某 CLIP 完成后不再自动合并/输出全部 clip，只保留 latent 缓存 + 卡片预览，静默等待用户下一步指令（合并输出 / 续跑 / 渲别的 clip）。/ After a solo render the node no longer auto-merges or outputs everything — it keeps the latent cache + card preview and silently waits for your next command (merge / continue / another clip).
- **收尾元组解包崩溃（v14.77）**：修复 `_pending_enc` 三元组在收尾遍历处的二元解包 `too many values to unpack`——渲染成果不受影响（缓存/预览先于崩溃已提交）。/ Fixed the binary unpack of the 3-tuple `_pending_enc` at the tail loop (`too many values to unpack`) — rendered results are unaffected (cache/preview commit before the crash point).

#### 🎨 前端 / Frontend

- **节点黑色底板跟随 CLIP 数量**：默认打开 = 4 卡视口 + 4 卡底板；点「展开CLIP」= 全部 CLIP 显示、底板撑到全高；收起态任何代码路径都无法把底板缩到 <4 卡（防止旧 nodeHeight/布局抖动闪回 1 卡）。/ The node backdrop tracks the CLIP count: default open = 4-card viewport with a 4-card backdrop; "Expand CLIP" shows every CLIP with a full-height backdrop; in collapsed mode no code path can shrink the backdrop below 4 cards (no more 1-card flashback from stale nodeHeight/layout jitter).
- **拖拽画布不闪回**：移动画布/重布局瞬间节点不再闪回 1 卡再弹回。 / Dragging the canvas no longer flashes the node back to 1 card before recovering.
- **展开态内容不溢出底板**：展开时 root/cards 恢复 auto 高度，31 卡内容全高撑起节点，不再溢出到黑色底板之外。 / Expanded state: root/cards revert to auto height so the full card stack fills the backdrop instead of overflowing it.

---

### v2.67 (2026-09-25) — 前端画布卡顿修复 / Frontend Canvas Lag Fix

**核心：打开工作流后画布逐渐卡死、一卡一卡的问题彻底修复。**
**Core: fixed the canvas gradually freezing / stuttering after opening a workflow.**

---

- **修复 1（每帧 console.log）**：`onDrawForeground` 每帧画布重绘都跑双语标签函数，且每帧都 `console.log`（同步阻塞），还重复设置已设过的 label。现已加守卫——节点只处理一次，后续每帧直接 return。
- Fix 1 (per-frame console.log): `onDrawForeground` ran the bilingual-label function on every frame and called `console.log` (synchronous blocking) every frame, re-setting labels already applied. Now guarded — each node processes labels once and returns immediately on later frames.
- **修复 2（定时器泄漏）**：`buildUi()` 被 `onConfigure`/`onExecuted` 反复调用，每次都新建一个 800ms 轮询定时器但旧的从不 `clearInterval`——打开工作流后定时器越积越多直到 CPU 跑满卡死。现已在新建前先 clear 旧定时器，永远只保留一个。
- Fix 2 (timer leak): `buildUi()` was called repeatedly by `onConfigure`/`onExecuted`, each time creating a new 800ms poll timer without clearing the old one — timers piled up after opening a workflow until the CPU maxed out. Now the old timer is cleared before creating a new one; exactly one timer is kept.

---

### v2.66 (2026-09-25) — latent 链保护三保险 + per-clip 独立渲染不补链 / Chain Protection Triple-Safety + Per-Clip Render Never Builds Prefix

**核心：渲过的 latent 链每段自动快照、恢复时空壳备份不再覆盖好链、点独立渲染绝不回 CLIP1。**
**Core: every committed segment is auto-snapshotted, empty backups can no longer overwrite a good chain, and per-clip render never falls back to CLIP1.**

---

#### 🛡️ 一、每段提交后自动滚动快照 / Per-Commit Rolling Snapshot

- 每渲完一段 CLIP（`disk_join` 成功后）立即把整条链快照到固定文件 `chain_extender_<id>.latest.snapshot.h3cache/.json`，每次覆盖。崩溃/误删后**最多丢最后一段**，点「♻️ 恢复缓存」即可回到最近完好状态。
- After every committed CLIP (right after `disk_join`), the whole chain is snapshotted to a fixed file `chain_extender_<id>.latest.snapshot.h3cache/.json` (overwritten each time). After a crash/accidental wipe you lose at most the last segment; click "♻️ Restore Cache" to return to the latest good state.
- 与旧的时间戳快照（仅在全部渲完/合并输出时触发）互补：中途崩溃也有备份。
- Complements the old timestamp snapshot (which only fired on full render-complete / merge-output): mid-run crashes are now covered too.

#### 🚫 二、恢复缓存防空壳保护 / Restore Guards Against Empty Backups

- 旧 bug：恢复时找不到快照会 fallback 到 preclear 备份，而 preclear 可能是 0 段空壳（仅 11 字节）——空壳被 copy 回主链，3.27GB 的 28 段链被空文件覆盖丢失。
- Old bug: when no snapshot existed, restore fell back to a preclear backup that could be a 0-segment empty shell (11 bytes) — copying it overwrote a 3.27GB / 28-segment chain.
- 现已：① 恢复时优先用 `latest.snapshot`；② 跳过段数=0 或数据 <1MB 的空壳备份；③ 当前主链非空且备份段数更少时**拒绝回退**，保护已渲染成果。
- Now: ① `latest.snapshot` is preferred; ② backups with 0 segments or <1MB data are skipped; ③ when the live chain is non-empty and a candidate backup has fewer segments, the restore refuses to roll back.

#### ▶️ 三、per-clip 独立渲染绝不回 CLIP1 / Per-Clip Render Never Falls Back to CLIP1

- 点卡片「▶ 独立渲染」CLIP29 时，若磁盘链只有 CLIP1，旧逻辑会把 CLIP2–28 当成待渲段从 CLIP1 一路补渲。现在前置段磁盘无缓存时**直接跳过、不补渲、不 join**，选中 CLIP 从当前链末尾接续渲染，渲完出预览、不自动合并、等待用户新指令。
- Clicking CLIP29 ▶ with only CLIP1 on disk used to treat CLIP2–28 as pending and re-render from CLIP1. Now missing prefix segments are **skipped — no re-render, no join**; the chosen CLIP renders right after the existing chain tail, emits its preview, and stops without auto-merging.

---


### v2.65 (2026-09-25) — 独立渲染绝不自动补渲染其他 CLIP / Single Clip Render Never Auto-Builds Prefix

**核心：点卡片「▶ 独立渲染」只渲染这一个 CLIP——前置 latent 链不足时不再自动从前面补渲染一大段。**
**Core: the per-clip ▶ button renders exactly one CLIP — missing prefix latents no longer trigger an automatic re-render of a long earlier segment.**

---

- **修复**：点 CLIP29 ▶ 时若磁盘链仅 2 段，旧 v1.17/v1.21 补链逻辑会从 CLIP3 一路补渲染到 CLIP29（用户实测点 clip29 却渲染了 clip3）。现在 per-clip 独立渲染前置链不足时只警告、不补渲染，直接接续现有链末尾渲染指定 CLIP；同时前端 ▶ 按钮会清除其他 CLIP 残留的 replace_mode，避免之前点过的 ↻ 被一起重渲染。clip_select 批量选择的补链逻辑保持不变。
- Fix: clicking CLIP29 ▶ with only 2 segments on disk used to auto re-render CLIP3–29 (the v1.17/v1.21 prefix build). Now a short prefix chain only logs a warning and the chosen CLIP renders right after the existing chain tail; the ▶ button also clears stale replace_mode on other clips. The clip_select batch path keeps its prefix-build behavior.

---

### v2.64 (2026-09-25) — 独立渲染优先 / Per-Clip Independent Render Priority

**核心：点卡片「▶ 独立渲染」只渲染指定 CLIP——即使节点上残留了「CLIP选择开关」的选择集，也不被选择集覆盖。**
**Core: the per-clip ▶ button now always renders exactly the chosen CLIP — a leftover "Clip Select" range can no longer override it.**

---

- **修复**：此前点「▶ 独立渲染」时若节点上残留 clip_select（如参数区「CLIP选择开关」开着、填 11-30），渲染循环的 `i not in select_override` 会跳过用户指定的 CLIP，同时 v2.63 强制启用选择集内全部 CLIP → 点 clip9 ▶ 实际渲染的是 11-30。现在后端检测到 per-clip 独立渲染（replace_mode）时优先忽略 clip_select 范围选择（参数区开关/值保持用户原样不动），▶ 按钮永远只渲染指定 CLIP（前置 latent 链缺失时仍自动补渲染前置段建立链，不渲染后续未选中段）；不点 ▶ 直接运行仍按参数区 clip_select 渲染。
- Fix: with a leftover clip_select range (e.g. the "Clip Select" switch on, 11-30), the loop's `i not in select_override` skipped the chosen clip and v2.63 force-enabled the whole range — clicking clip9 ▶ rendered 11-30 instead. The backend now gives per-clip replace_mode priority and ignores clip_select while the parameter-panel switch/value stay untouched. ▶ always renders exactly the chosen CLIP (missing prefix latents are auto-built, no trailing clips rendered); running without ▶ still follows the panel clip_select.

---

### v2.63 (2026-09-23) — clip_select 权威选择修复 / Clip Select Authority Fix

**核心：勾选「CLIP选择开关」后，clip_select 指定的选中集（含自动补渲染的前置/中段缺口）一律真正渲染，不再被残留的 render_enabled=✗ 静默跳过。**
**Core: with "Clip Select" enabled, the selected set (including auto-filled prefix/middle-gap clips) is always actually rendered — no longer silently skipped by stale per-clip ✗ toggles.**

---

- **修复**：`clip_select=11-30` 时若卡片上残留「独立渲染▶ / ↻」留下的 `render_enabled=✗`，选中段被循环的 `not render_enabled` 条件静默跳过：前置链补不出来、选中段不渲染，首个被渲染的 clip 错放到链索引 0，导致预览解码越界、轨道无输出。现在 clip_select 显式选择时，选择集内一律强制 `render_enabled=True`（与 v1.21 强制渲染前置 clip 同一原则），并在日志打印被强制启用的 CLIP 列表。
- Fix: with `clip_select=11-30`, stale `render_enabled=✗` flags (left by a previous ▶ single-render / ↻ replace action) made the loop's `not render_enabled` check silently skip selected clips — the prefix chain was never built, selected clips never rendered, and the first rendered clip landed at chain index 0 (preview decode out of range, no track output). Now an explicit clip_select forces `render_enabled=True` for the whole selected set before the loop (same principle as v1.21's forced prefix render), with the forced CLIP list printed to the log.

---

### v1.98 (2026-09-23) — 缓存永不自动删 + 渲染自动快照 + 一键恢复不补链 / Cache Protection + Auto-Snapshot + One-Click Restore Without Re-Rendering

**核心：只要渲染过，缓存就受保护、自动备份、可一键恢复，恢复后绝不从 CLIP1 重新渲染补链！**
**Once rendered, your cache is protected, auto-backed-up and one-click restorable — restored clips are never re-rendered from CLIP1!**

---

#### 🛡️ 一、缓存保护：渲染过永不自动删 / Cache Protection

- **任何截断（卡片减少、分辨率变化、工程导入等）前都无条件自动备份主链**，先备份再截断；缓存只可能被用户主动操作删除
  Before ANY chain truncation (card removal, resolution change, project import, etc.) the main chain is unconditionally backed up first; cache can only be removed by explicit user action
- 系统自动流程不再静默丢弃任何已渲染成果
  No automatic system path silently discards rendered work anymore

#### 📸 二、渲染完成自动快照 / Auto-Snapshot After Render

- 每次**渲染完成 / 合并输出**后自动快照整条链（数据 + 清单），保留最近 **5 份**，滚动清理
  After every **render completion / merge output**, the full chain (data + manifest) is auto-snapshotted; latest **5** kept with rolling cleanup
- 快照文件：`chain_extender_<id>.<时间戳>.snapshot.h3cache/.json`
  Snapshot files: `chain_extender_<id>.<timestamp>.snapshot.h3cache/.json`

#### ♻️ 三、一键恢复缓存（两个入口）/ One-Click Restore (Two Entries)

**入口 1 — 节点「恢复缓存」开关（参数列表末尾，执行后自动复位）**
**Entry 1 — Node "Restore Cache" toggle (at the END of the parameter list, auto-resets after execution)**
- 打开 → 运行 → 从最近自动快照恢复主链 → 恢复的 CLIP 标记为已渲染 → **只渲染新增 CLIP，不补链**
  Enable → Run → main chain restored from latest snapshot → restored clips marked as already-rendered → **only new clips render, no chain-fill**
- 执行完成前端自动把开关复位为关
  The toggle auto-resets to off after execution

**入口 2 — 前端工具栏「♻️ 恢复缓存」按钮**
**Entry 2 — Frontend toolbar "♻️ Restore Cache" button**
- 搜索源最高优先级 = 主链目录本身（自动快照/截断备份所在），可直接恢复自动快照
  Highest-priority search source = the main chain directory itself (where auto-snapshots / truncate backups live)

#### 🚫 四、恢复后不补链 / No Re-Rendering After Restore

- 恢复后主链 = 完整备份链 → 前置 latent 链检查直接通过 → **不会触发"从 clip1 自动补渲染"**
  After restore the main chain is complete → prefix latent-chain check passes directly → **no "auto-fill from clip1"**
- 恢复的 CLIP 全部标记 `validated=True` → 主循环跳过（秒级），只渲染真正新增的片段
  Restored clips are all marked `validated=True` → skipped by the main loop (seconds), only genuinely new clips render

#### 🐛 五、关键修复 / Key Fixes

- **WinError 32（文件占用）修复**：恢复源优先匹配 `*.snapshot.*` / `*.preclear.*` 明确备份，排除活跃主链（正被 mmap 占用），占用/损坏候选自动跳过
  WinError 32 (file-in-use) fixed: restore sources prefer explicit `*.snapshot.*` / `*.preclear.*` backups, exclude the live main chain (mmap-held), and skip busy/corrupt candidates
- **恢复分辨率校验**：备份链分辨率 ≠ 当前渲染设置时**回滚恢复并给出明确指引**，不再"恢复成功 → 又被分辨率清链 → 从 CLIP1 补渲染"（latent 链不能跨分辨率复用）
  Restore resolution guard: if backup chain resolution ≠ current render settings the restore is **rolled back with clear guidance**, no more "restore OK → cleared by resolution change → re-render from CLIP1" (latent chains cannot be reused across resolutions)
- **参数兼容**：`restore_cache` 追加在参数列表**末尾**，原有参数顺序完全不变，旧工作流不报错
  Workflow compatibility: `restore_cache` appended at the END of the parameter list; existing parameter order unchanged, old workflows unaffected

---

### v2.62 (2026-09-22) — CLIP 选择渲染增强 + 链完整性修复 / Clip Select Enhancements + Chain Integrity Fixes

**核心：CLIP 选择（clip_select）现在支持任意多选、范围与组合，未选中的 CLIP 保留缓存不重新生成！**
**Now `clip_select` supports arbitrary multi-select, ranges and combinations — unselected clips keep their cache and are not re-rendered!**

---

#### 🎯 一、CLIP 选择渲染 / Clip Select Rendering

**在节点上勾选「CLIP选择开关」后，在「CLIP选择」框输入：**
**Enable the "Clip Select" toggle on the node, then type in the "Clip Select" box:**

| 输入 / Input | 效果 / Effect |
|---|---|
| `all` | 渲染全部 CLIP / Render all clips |
| `1,3` | 仅渲染 CLIP 1 和 3 / Render only clips 1 and 3 |
| `2-5` | 渲染 CLIP 2 到 5 / Render clips 2 through 5 |
| `7-10` | 渲染 CLIP 7 到 10 / Render clips 7 through 10 |
| `3,5,7` | 仅渲染 CLIP 3、5、7 / Render only clips 3, 5, 7 |
| `3，5，7` | 兼容中文标点（全角逗号/顿号/分号、全角连字符）|
| | Chinese full-width punctuation supported (`，`、`、`、`；`, `－`) |
| `2`（单选）/ single | 从 CLIP 2 连续渲染到末尾（续渲染语义）/ From clip 2 continuously to the end (resume semantics) |

- **未选中的 CLIP 保留磁盘缓存、不重新生成**（适合改完个别分镜后局部重渲染）
  Unselected clips keep their disk cache and are **not re-rendered** (ideal for re-rendering only edited shots)
- **输入无法解析时输出 WARNING 提示**，不再静默渲染全部
  Invalid input prints a WARNING instead of silently rendering everything

#### 🔗 二、链完整性自动补齐 / Automatic Chain-Integrity Fill

**H3 链式运动上下文要求 latent 连续。选择跨度内被跳过且磁盘无缓存的 CLIP 会自动补渲染，并明确打印日志。**
**H3 chain motion-context requires contiguous latents. Skipped clips inside the selected span that have no disk cache are auto-filled with a clear log message.**

- 前置缺失段自动补渲染建立完整链 / Missing prefix segments auto-rendered to build the chain
- 中段缺口（如缓存有 1-2、选 3,5,7 时 CLIP4/6）自动补渲染 / Middle gaps (e.g. clips 4/6 when cache has 1-2 and you select 3,5,7) auto-filled
- 补渲染范围收窄到**选中段跨度内**，末尾未选中的 CLIP 保留缓存，不再一路补到片尾
  Fill scope narrowed to the selected span; unselected trailing clips keep cache and are not filled to the end

#### ♻️ 三、恢复缓存改进 / Restore Cache Improvements

- **多源 fallback 搜索链快照**：自动在插件目录、ComfyUI 根目录、主项目根、用户主目录逐级查找链快照，修复 v2.61 硬编码 backup 目录导致备份找不到的问题
  Multi-source fallback search for chain snapshots (plugin root → ComfyUI root → project root → user home), fixing v2.61's hardcoded backup dir
- **损坏链重建保护**：manifest 声称有段但磁盘只有 magic header（空文件）时，自动识别并触发重建，修复 `clip_select` 部分渲染时 `invalid chain index 0/0` 报错
  Corrupted-chain rebuild protection: detects manifest/disk mismatch (empty magic-header file) and triggers a clean rebuild, fixing `invalid chain index 0/0` on partial renders

#### 🖥️ 四、Windows 稳定性修复 / Windows Stability Fix

- 新增 `prestartup.py`：修复 Windows + Python 3.13 + aiohttp 下静态文件请求死锁（浏览器能开页面但 JS/CSS 永远加载不出来）。默认线程池升级到 256 worker + 静态路径同步解析
  New `prestartup.py` fixes the Windows aiohttp static-file deadlock (page loads but JS/CSS hang at "0 bytes received"): default executor upgraded to 256 workers + synchronous static path resolution

#### 📦 五、其他 / Other

- **新增示例工作流**：`example_workflows/百声电影工厂（H3全自动电影短片生成）v1.json`
  New example workflow: fully automatic film short generator
- **修复演示工作流** `BSAI_H3_ClipSelect_Pause.json`：控件顺序错位导致 `clip_select` 收到错误值（120.0）的问题已对齐
  Fixed demo workflow widget-order drift that made `clip_select` receive a wrong value (120.0)

---

### v2.61 (2026-09-22) — ♻️ 恢复缓存 体验修复 / Restore Cache UX Fixes

**恢复缓存按钮体验全面优化，关机续渲染更顺畅！**
**Restore Cache button UX polished — resume after reboot is now seamless!**

---

#### 1. 刷新弹窗修复 / Refresh-Prompt Fix

**「♻️ 恢复缓存」恢复成功后，默认改为"留在当前页面"，把已恢复 N 个 CLIP 的数量写到节点状态栏（紫色文字）。**
**After "♻️ Restore Cache" succeeds, the default is now "stay on current page" — the restored clip count is shown in the node status bar (purple text).**

- 不再强制刷新页面，避免 ComfyUI 的 `beforeunload` 拦截弹"是否离开网站"让用户误以为缓存丢失
  No more forced page reload, avoiding the misleading "leave site?" prompt caused by ComfyUI's own `beforeunload` listener
- 需要时手动 Ctrl+R 刷新即可 / Manually refresh (Ctrl+R) when needed

#### 2. 渲染循环自动读盘 / Auto-Read Fresh Chain Cache

**留在当前页面后，再次 Queue Prompt 时自动读取刚被恢复的 `.h3cache`，跳过已渲染完成的 CLIP，直接从断点继续。**
**When you queue another prompt, the renderer auto-loads the freshly restored `.h3cache` and continues from the break-point, skipping already-rendered clips.**

#### 3. 新增 mp4 预览路由 / New Clip Preview Routes

**后端新增 `/h3_extender/clip_preview` 与 `/h3_extender/clip_preview/file` 两个路由，修复"恢复缓存后右侧预览面板仍空白"问题。**
**Two new backend routes serve the newest per-clip mp4 from `output/bsai_clips/`, fixing the empty preview panel after cache restore.**

---

### v2.60b (2026-09-21) — 收起CLIP + 恢复缓存 + 关机续渲染 / Collapse CLIP + Restore Cache + Resume After Reboot

**两大实用功能：一键收起CLIP节省空间，一键恢复缓存关机续渲染！**
**Two handy features: collapse CLIPs to save space, restore cache to resume after reboot!**

---

#### 📦 一、收起CLIP按钮 / Collapse CLIP Button

**工具栏新增"📦 收起CLIP"按钮，点一下收起到只显示5个CLIP高度，其他CLIP用滚动条查看。**
**New "📦 Collapse CLIP" button in toolbar: click to collapse to show only 5 clips height, scroll for the rest.**

- **按钮位置 / Button Location**: 暂停按钮后面（绿色按钮）/ After pause button (green button)
- **收起后 / After Collapse**: 只显示5个CLIP高度，其他CLIP用滚动条上下滑动
  Only show 5 clips height, scroll up/down for other clips
- **再点一下 / Click Again**: 恢复全部展开
  Restore to fully expanded

---

#### ♻️ 二、恢复缓存按钮 / Restore Cache Button

**工具栏新增"♻️ 恢复缓存"按钮，点一下恢复最近一次渲染的所有缓存、CLIP成品、预览文件，不用从CLIP1重新渲染！**
**New "♻️ Restore Cache" button in toolbar: click to restore all cache, clips, and previews from last render — no need to restart from CLIP1!**

**恢复内容 / What Gets Restored**:
1. **链缓存（h3cache）**: 恢复到 `bsai_h3_chain_cache/` 目录
   Chain cache restored to `bsai_h3_chain_cache/`
2. **CLIP 成品（mp4）**: 恢复到 `output/bsai_clips/` 目录
   Final clips restored to `output/bsai_clips/`
3. **预览文件（_clippv_*.mp4）**: 恢复到 `temp/` 目录，每个CLIP预览窗口都能随时打开预览
   Preview files restored to `temp/`, every clip preview can be opened anytime

---

#### ⚡ 三、关机开机续渲染技巧 / How to Resume After Reboot

**渲染到一半要关机？不用怕，这样操作就能从上次结束的地方继续！**
**Need to reboot mid-render? No problem — follow these steps to resume where you left off!**

##### ✅ 正确操作步骤 / Correct Steps:

1. **等当前CLIP渲染完**（不要中途关机）
   Wait for current clip to finish rendering (don't reboot mid-clip)

2. **直接关机就行**（不用点暂停）
   Just shut down directly (no need to click pause)

3. **晚上开机后 / After Reboot**:
   - 打开工作流 / Open your workflow
   - 点一下 **"♻️ 恢复缓存"** 按钮 / Click the **"♻️ Restore Cache"** button
   - 直接点渲染 / Click render
   - 就会从上次结束的CLIP继续渲染 / It will resume from the last completed clip

##### ❌ 错误操作（不要这样做）/ Wrong Steps (Don't Do This):

- 点暂停 → 直接关机 → 开机后点继续
  Click pause → shut down directly → click resume after reboot
  - **为什么不行 / Why It Doesn't Work**: 暂停状态存在内存里，关机后就没了
  Pause state is in memory, it's gone after reboot

##### 📊 为什么这样行 / Why This Works:

| 状态 / State | 保存位置 / Saved In | 关机后还在吗 / Survives Reboot? |
|-------------|---------------------|-------------------------------|
| 暂停按钮状态 / Pause State | 内存 / Memory | ❌ 没了 / Gone |
| 链缓存（h3cache）/ Chain Cache | 硬盘 / Disk | ✅ 还在 / Survives |
| 已渲染的CLIP / Rendered Clips | 硬盘 / Disk | ✅ 还在 / Survives |
| 预览文件 / Preview Files | 硬盘备份 / Disk Backup | ✅ 恢复后还在 / Restored |

---

### v2.54 (2026-09-20) — 电影模板 + 性能优化 + Bug 修复 / Cinematic Templates + Performance + Bug Fixes

**全新电影提示词模板系统，一键统一全片运镜/调色/氛围，画布响应速度提升 10 倍！**
**Brand-new cinematic prompt template system, one-click unify camera/color/mood across all shots, 10x faster canvas interaction!**

---

#### 🎬 一、电影提示词模板系统 / Cinematic Prompt Templates

**38 个内置电影专业模板，覆盖运镜、调色、构图、氛围四大类，一键应用全片或单 CLIP。**
**38 built-in professional cinematic templates covering camera movement, color grading, composition, and mood — one-click apply to whole film or single clip.**

| 分类 / Category | 数量 / Count | 示例 / Examples |
|---------------|-------------|-----------------|
| 🎥 电影运镜 / Camera Movement | 12 | 缓推 Push In, 拉远 Pull Back, 跟拍 Tracking, 环绕 Orbit, 手持 Handheld, 斯坦尼康 Steadicam... |
| 🎨 电影调色 / Color Grading | 10 | 暖调 Warm, 冷调 Cool, 青橙 Teal & Orange, 黑白 Noir, 莫兰迪 Morandi, 霓虹赛博 Neon Cyber... |
| 🎬 画面分割 / Aspect & Composition | 6 | 宽屏 Widescreen, 上下黑边 Letterbox, 三分 Rule of Thirds, 框中框 Frame-in-Frame... |
| ✨ 电影感 / Cinematic Feel | 10 | 电影级画质 Cinematic Quality, 戏剧光影 Dramatic Light, 黄金时刻 Golden Hour, 雨夜 Rainy Night, 紧张悬疑 Tense Suspense, 史诗宏大 Epic... |

**两种应用模式 / Two Application Modes**:

1. **全局应用 / Global Apply**:
   - 节点顶部工具栏 `✨ 模板` 按钮，一键应用到**所有 CLIP + 全局提示词**
   - Top toolbar "✨ 模板" button, one-click apply to **ALL clips + global prompt**
   - 适合：全片统一调色、统一运镜风格、统一氛围
   - Best for: unifying color grading, camera style, or mood across the whole film

2. **单 CLIP 应用 / Per-Clip Apply**:
   - 每个 CLIP 左侧面板新增 `模板` tab，独立应用到当前 CLIP
   - Left panel "模板" tab on each clip, apply to current clip only
   - 其他 CLIP 完全不受影响
   - Other clips are completely unaffected

**合并选项 / Merge Options**:
- 【确定】= **合并 / Merge**: 保留全局模板，再加单 CLIP 模板
- 【取消】= **覆盖 / Overwrite**: 移除全局模板，只保留单 CLIP 模板

**模板标记 / Template Tags**:
- 全局模板：`[电影风格-全局]...[/电影风格-全局]`
- 单 CLIP 模板：`[电影风格-单CLIP]...[/电影风格-单CLIP]`
- 插入位置：每个 CLIP 提示词**最顶部**，清晰可随时删除

---

#### ⚡ 二、性能优化 / Performance Optimizations

**画布拖动卡、资产面板加载慢的问题彻底解决！**
**Fixed slow canvas dragging and slow asset panel loading!**

1. **资产面板缓存 / Asset Panel Cache**:
   - refs 没变不重新渲染，避免 150+ 个 img 重复加载
   - Skip re-render when refs unchanged, no more 150+ duplicate image loads
   - 加载速度提升 **10 倍以上**
   - Loading speed improved by **10x+**

2. **全局定时器降频 / Global Poll Rate Reduced**:
   - 从 500ms 降到 2000ms，减少 75% 的轮询开销
   - From 500ms to 2000ms, reducing polling overhead by 75%
   - 去掉重复的节点级定时器
   - Removed duplicate node-level timers

3. **CLIP 卡片智能显示 / Smart CLIP Card Display**:
   - 外部提示词输入几个分镜，自动显示几个 CLIP
   - Auto show N clips when N shots are entered in external prompt
   - 未输入时默认只显示 CLIP1，节省屏幕空间
   - Default to CLIP1 only when no prompt entered, saves screen space
   - 节点背景自动跟随 CLIP 数量伸缩
   - Node background auto-resizes with CLIP count

---

#### 🧠 三、时间分块 + 语义桥 / Temporal Chunking + Semantic Bridge

**两大核心技术升级：长片段防 OOM + 提示词更听话！**
**Two major technical upgrades: long clip OOM protection + better prompt adherence!**

##### ⏱️ 时间分块（v2.02）/ Temporal Chunking

**长片段二采防 OOM：沿时间轴（T 轴）切分二采 latent，逐段采样，峰值显存大幅降低。**
**Long clip OOM protection: split refine latent along the temporal axis (T), sample segment by segment, drastically reduces peak VRAM.**

- **区别于空间分块**: 空间分块沿 H/W（宽高）切，时间分块沿 T（时间）切
- **Different from spatial tiling**: spatial tiles along H/W (width/height), temporal chunks along T (time)
- **重叠区平滑接管**: 相邻段重叠区冻结 + smoothstep 接管，避免接缝
- **Smooth overlap**: frozen overlap region + smoothstep blending, no visible seams
- **参数说明 / Parameters**:
  - `temporal_chunk_tokens`: 时间分块长度（沿 T 轴切的 token 数）
  - `temporal_overlap_tokens`: 相邻段重叠 token 数（越大越稳越慢，一般 8~12）
- **使用建议 / Usage Tips**:
  - 0 = 关闭（默认整段二采）
  - T~107（约 4 秒）时建议 40~60
  - 长片段（15 秒+）二采必开，否则容易 OOM

##### 🌉 语义桥（v2.19）/ Semantic Bridge

**让 H3 更听话：用一个约 11MB 的小 MLP 对文本编码器 token 做残差混合，显著提升构图/空间/计数等提示词遵循度。**
**Better prompt adherence: a ~11MB small MLP does residual mixing on text encoder tokens, significantly improves adherence to composition / spatial / counting prompts.**

- **原理 / How it works**:
  - 原版蒸馏于 FL2VA 模型，本插件做了 Ref2VA 强制兼容
  - Original model distilled for FL2VA; this plugin adds Ref2VA compatibility
  - 公式：`C = H + α * (S - H)`，其中 H 是原始 token，S 是桥接 token，α 是强度
  - Formula: `C = H + α * (S - H)`, where H is original token, S is bridge token, α is strength
- **参数说明 / Parameters**:
  - `semantic_bridge_enable`: 开关（默认关，不影响旧工作流）
  - `semantic_bridge_adapter`: 权重文件选择（放 `ComfyUI/models/semantic_bridge/`）
  - `semantic_bridge_alpha`: 桥接强度（默认 0.15，越大越听话，太大会崩）
  - `semantic_bridge_magnitude_match`: 模长对齐（原版默认开，保持即可）
- **推荐权重 / Recommended Weights**:
  - `speach1sdef178/MiniMax-H3-Semantic-Bridge` — 原版通用
  - `JOKER141/BUNNY_H3_Conditioning_Bridge` — 偏动作/多人场景

---

#### 🐛 四、重要 Bug 修复 / Critical Bug Fixes

1. **刷新页面后缓存误清空 / Cache Cleared on Refresh**:
   - 修复：分辨率未稳定时校验，误判不匹配清空缓存
   - Fixed: cache was incorrectly cleared when resolution not yet stabilized on page load
   - 现在刷新页面后，之前生成的 CLIP 缓存完整保留
   - Now all previously generated clip caches are preserved on refresh

2. **外部提示词清空不同步 / External Prompt Clear Sync**:
   - 修复：清空外部全局提示词后，内部全局提示词不同步清空
   - Fixed: internal global prompt not cleared when external global prompt is cleared
   - 现在清空外部提示词，内部全局 + 所有 CLIP 全部同步清空
   - Now clearing external prompt syncs internal global + all clips immediately

3. **tab 切换后资产面板打不开 / Asset Panel Broken After Tab Switch**:
   - 修复：模板 tab 打开后，资产 tab 打不开
   - Fixed: asset tab stopped working after opening template tab
   - 现在 tab 切换完全正常
   - Now tab switching works perfectly

4. **CLIP 提示词框太小看不全 / CLIP Prompt Box Too Small**:
   - 新增：CLIP 提示词框右下角可拖拽拉高度
   - Added: resize handle at bottom-right of each clip prompt box
   - 初始高度 200px，可任意拉高
   - Initial 200px height, resizable to any height

5. **另存工作流报错 / Save Workflow Error**:
   - 修复：另存工作流时报 `structuredClone` 错误（`__h3Extender` 不可枚举属性导致）
   - Fixed: `structuredClone` error when saving workflow (non-enumerable `__h3Extender` property)
   - 现在另存工作流完全正常
   - Now saving workflows works perfectly

6. **二采开头 39 帧重影模糊 / Refine First 39 Frames Ghosting**:
   - 修复：二采 refine 时 motion-context keyframe 未清空，导致开头重影错位模糊
   - Fixed: motion-context keyframe not cleared in refine pass, causing ghosting/blurry first 39 frames
   - 现在二采开头画面干净清晰
   - Now refine start frames are clean and sharp

7. **导入空包误删旧链备份 / Empty Import Deletes Old Chain**:
   - 修复：导入空包时静默删除旧链备份，v1.97 防误清机制没覆盖导入路径
   - Fixed: empty import silently deleted old chain backup, v1.97 protection missed the import path
   - 现在导入前自动备份，不会误删整链
   - Now auto-backup before import, no more accidental chain loss

---

#### 🎛️ 五、其他重要优化 / Other Important Improvements

1. **全局资产引用折叠显示 / Global Asset Refs Folded Display**:
   - 之前：全局引用太多时，所有引用的资产全部展示，占满界面
   - Before: when too many global refs, all referenced assets displayed, taking too much space
   - 现在：每个 CLIP 只显示自己引用的资产，同一资产引用次数用数字角标表示
   - Now: each CLIP only shows its own referenced assets, reference count shown as number badge
   - 界面更清爽，占用更少
   - Cleaner UI, less space usage

2. **CLIP 节点高度自动扩展 / Node Height Auto-Expand**:
   - 之前：CLIP 超过 12 个时，节点高度被截断，只剩 4 个卡片能看到
   - Before: when more than 12 clips, node height was truncated, only 4 cards visible
   - 现在：节点高度自动扩展到 8000px，再多 CLIP 也能完整显示
   - Now: node height auto-expands to 8000px, even more clips fully visible
   - 底部黑色背景自动跟随 CLIP 数量伸缩
   - Bottom black background auto-resizes with CLIP count

3. **重启后资产链接自动恢复 / Asset Refs Auto-Restore on Restart**:
   - 之前：重启 ComfyUI 或刷新工作流后，所有 CLIP 的资产 @引用 全部丢失
   - Before: after restarting ComfyUI or refreshing workflow, all CLIP asset @refs were lost
   - 现在：已引用资产面板同时解析 CLIP prompt + 全局 prompt，重启后自动恢复
   - Now: asset panel parses both CLIP prompt + global prompt, auto-restores after restart
   - 不需要重新输入全局提示词来重新链接资产库
   - No need to re-enter global prompt to re-link asset library

4. **剧本输入自动建 CLIP / Auto-Create CLIP from Script**:
   - 输入外部全局提示词（剧本）后，自动按 `[分镜N]` 数量创建对应数量的 CLIP 卡片
   - After entering external global prompt (script), auto-create CLIP cards based on `[Shot N]` count
   - 节点自动撑高到对应 CLIP 数量，不需要手动拉
   - Node auto-expands to match CLIP count, no manual resizing needed
   - 实时解析，输入完立即生效
   - Real-time parsing, takes effect immediately after input

---

### v1.86 (2026-09-15) — VDN-H3 极速档 + Bullet Time Lora 集成 / VDN-H3 Presets + Bullet Time LoRA
- **VDN-H3 速度档 / VDN-H3 speed presets**: speed_preset 新增 **极速-VDN / Turbo-VDN**、**均衡-VDN / Balanced-VDN**、**精细-VDN / Fine-VDN** 三档。VDN 模式一采固定 8 步（Video DeltaNet DMD 蒸馏最优，质量≈dense 50 步、长链线性注意力更稳），二采 3/4/6 步。需搭配 **VDN 版工作流**（workflows/电影工厂工作流-VDN版-均衡VDN8+4（tile_overlap128）.json）——BSAIVDNH3Loader（基座+linear_branch+LoRA 一体化）替换 Sol-H3 链路，自动跳过 FastH3 LoRA/Sol-Attn。／Three new presets for the ComfyUI-VDN-H3 pipeline: pass-1 fixed at 8 VDN steps (≈dense-50 quality), refine at 3/4/6 steps. Use the VDN workflow (BSAIVDNH3Loader replaces the Sol-H3 chain).
- **Bullet Time LoRA 集成 / Bullet Time LoRA**: 两个工作流（FastH3 版 & VDN 版）均在 Lora Stack 挂载 **BulletTime-MMH3.safetensors @ 0.5**，配合 BSAI-MiniMAX-H3-Prompt 的子弹时间模板触发词（ullet time + time-slow 强化句）使用。／Both workflows mount **BulletTime-MMH3.safetensors @ 0.5** in the LoRA stack, paired with the bullet-time trigger words in the prompt templates.

| 预设 / Preset | 一采步数 / Pass1 steps | 二采步数 / Refine steps | 二采分块 / Tiles | 二采降噪 / denoise | 单 Clip 耗时 / per-Clip |
|---|---|---|---|---|---|
| 极速 Turbo (FastH3) | 4 | 3 | 4 | 0.5 | ~20 min |
| 均衡 Balanced (FastH3) | 6 | 4 | 4 | 0.55 | ~28 min |
| 精细 Fine (FastH3) | 8 | 6 | 4 | 0.55 | ~40 min |
| 极速-VDN Turbo-VDN | 8 (VDN) | 3 | 4 | 0.5 | ~20 min |
| 均衡-VDN Balanced-VDN | 8 (VDN) | 4 | 4 | 0.55 | ~28 min |
| 精细-VDN Fine-VDN | 8 (VDN) | 6 | 4 | 0.55 | ~40 min |

---

### v2.61 (2026-09-22) — ♻️ 恢复缓存 体验修复 + mp4 预览重新挂载 / Restore Cache UX Fix + mp4 Preview Remount

**主要解决"♻️ 恢复缓存"按钮按完后右侧 mp4 预览窗空白的问题，并把"是否刷新页面"的选择权交回用户。**

**Solves: "♻️ Restore Cache" leaves the right-side mp4 preview panel blank, and gives the user a clean way to choose between reloading the page or staying on it.**

#### 🪩 一、为什么之前"恢复缓存"按完右侧预览是空的 / Why the preview panel was blank after restore

**修复前**：
- 后端 `/h3_extender/clip_preview`（在 `motion_context_disk.py`）只从 `bsai_h3_chain_cache/chain_extender_<owner>.json` 的 `segments[*].decoded_mp4_blob` 取 mp4
- 当 `manifest.segments` 为空数组（典型场景：缓存损坏 / 备份丢失），接口固定返回 `400 This clip has not been rendered yet.`
- 前端拿到 null 就显示"预览不可用"占位符
- 即使 `output/bsai_clips/h3_clip_<owner>_<idx>_<ts>.mp4` 真实存在、30 MB 完整，前端也无路可拿

**Before the fix:**
- Backend `/h3_extender/clip_preview` (in `motion_context_disk.py`) only reads mp4 blobs from `manifest.segments[*].decoded_mp4_blob`
- When `manifest.segments` is empty (typical after cache corruption / lost backup), the endpoint always returns `400 This clip has not been rendered yet.`
- The frontend gets `null` and shows the "preview unavailable" placeholder
- Even though `output/bsai_clips/h3_clip_<owner>_<idx>_<ts>.mp4` is fully present, the frontend had no way to fetch it

**修复后**：
- 新加后端路由 `/h3_extender/rendered_clips?owner_id=<owner>`：扫描 `output/bsai_clips/` 返回 `latest_filename_by_idx`（每个 clip_index 对应最新时间戳的 mp4 文件名）
- 前端 `fetchClipPreview` 拿不到原接口数据时自动 fallback → 调 `rendered_clips` 拿文件名 → 直接走 `ComfyUI /view?type=output&subfolder=bsai_clips&filename=...` stream 30MB mp4
- 索引错位 bug 修复：前端 `state.clips[]` 是 0-based，后端 `h3_clip_*_<idx>_` 是 1-based；fetchClipPreview 入口统一 `+1` 转换
- "♻️ 恢复缓存"按完后 `render(node, runtime)` 重画所有 DOM 卡片，每个已渲染 CLIP 立即显示对应 mp4 缩略图

**After the fix:**
- New backend route `/h3_extender/rendered_clips?owner_id=<owner>` scans `output/bsai_clips/` and returns `latest_filename_by_idx`
- Frontend `fetchClipPreview` automatically falls back to `rendered_clips` → uses `/view?type=output&subfolder=bsai_clips&filename=...` to stream the 30 MB mp4
- Index off-by-one fixed: `state.clips[]` is 0-based; `h3_clip_*_<idx>_` is 1-based; the entry-point of `fetchClipPreview` now does a single `+1` conversion
- After pressing "♻️ Restore Cache", `render(node, runtime)` rebuilds every card; every rendered CLIP immediately shows its mp4 thumbnail

#### 📝 二、♻️ 恢复缓存按钮 — 详细使用说明 / Detailed Usage

**按钮位置 / Button Location**: 节点顶部工具栏 / Top toolbar of the node

**第一步 / Step 1**: 点击 **「♻️ 恢复缓存」** / Click the button
- 弹出第一个确认框 / First confirm dialog:*
- "确定要恢复最近一次渲染的所有缓存吗？会恢复：链缓存（h3cache）+ 已渲染完成的 CLIP 成品。恢复后可以直接继续渲染后面的 CLIP，不用从 CLIP1 重新开始。"

**第二步 / Step 2**: 后端响应 / Backend response
- 后端走 `/h3_extender/restore_cache` 接口
- 在 `backup/chain_cache_2026-09-21/` 备份目录存在时复制 `.h3cache` / `_clippv_*.mp4` 到运行目录
- 统计 `output/bsai_clips/h3_clip_<owner>_*.mp4` 总数 → 返回 `clips_restored`（如本机示例的 40）

**第三步 / Step 3**: 第二个确认框（v2.61 新增）/ Second confirm dialog (new in v2.61)
- "恢复成功！已恢复 N 个 CLIP。点击「确定」刷新页面以挂载新的缓存；点击「取消」留在当前页面继续渲染（缓存文件已就绪，状态栏会显示已恢复数量）。"
- **点「确定」**：浏览器原生 `location.reload()`，状态栏会显示已恢复数，右侧预览按需自动 mount
- **点「取消」（推荐）**：留在当前页面，前端调 `/h3_extender/rendered_clips` 拿文件名 → 重画所有卡片 → 右侧预览 1-2 秒内亮起 mp4 缩略图

**常见问题 / FAQ**:
- **Q: 弹出了"是否离开网站"原生框怎么办？/ "Leave site?" native dialog?**
  A: 这是 ComfyUI/LiteGraph 注册的 `beforeunload` 拦截。v2.61 已先调 `graph.setDirty(false)` 再 reload，多数情况下不会弹；万一弹了，按"离开"完成刷新即可（缓存已经在磁盘上了）。
- **Q: 右侧仍然空白？**
  A: 打开 DevTools → Network，搜 `rendered_clips` / `view` 请求，把 URL 和响应截图给我。
- **Q: 取消按钮按了之后想刷新怎么办？**
  A: 直接 Ctrl+R 或 Ctrl+F5，缓存文件已就绪。
- **Q: 恢复缓存会把所有 mp4 都重渲染一遍吗？**
  A: 不会。恢复缓存只搬运磁盘文件；下一次 Queue Prompt 会自动读 `.h3cache` 跳过已渲染段。

#### 🔖 三、如何回滚到此版本 / How to roll back to this version

```bash
cd /path/to/BSAI-ComfyUI-H3-Film-Factory
git checkout v2.61               # 切到这个里程碑
# 或 git checkout 7d2a91f 等具体提交哈希
```

回滚后**重启 ComfyUI** 让新代码生效。备份目录 `output/bsai_clips/` 不在版本控制内，不要手动删除。

```bash
git checkout v2.61
# Then restart ComfyUI for the new code to load. output/bsai_clips/ is not in version control — do not delete it manually.
```

---

## 🚀 VDN-H3 + Bullet Time 快速上手 / Quick Start (v1.86)

### 1️⃣ VDN 极速档（一采质量≈dense 50 步）/ VDN speed presets
1. **安装 VDN 插件（已随包内嵌，零安装）** / Install: BSAI-ComfyUI-vdn-minimax-h3 ships with an embedded vdn_h3 runtime — no separate install.
2. **权重就位** / Weights: put the VDN stage under ComfyUI/models/vdn/stage-dmd-step-250/ (linear_branch + adapters/turbo + adapters/default). Base model: any ComfyUI-compatible MiniMax H3 in models/diffusion_models (recommended minimax_h3_fl2va_int8_convrot.safetensors).
3. **加载 VDN 版工作流** / Load workflows/电影工厂工作流-VDN版-均衡VDN8+4（tile_overlap128）.json — the chain is already wired:
   > **多合一版（推荐）** / **All-in-one (recommended)**: workflows/BSAI_H3_Film_Factory电影工厂128分钟大电影版-多合一版（FastH3+VDN双链路·tile_overlap128).json — 单工作流双链路切换（**开关 OFF=FastH3 一采** / **ON=VDN 8步+turbo 一采**），含分镜AI生成/资产库/BulletTime LoRA/Premiere 导出全套。Dual-chain switch (OFF=FastH3, ON=VDN) with AI storyboard, asset library, BulletTime LoRA & Premiere export.
   BSAIVDNH3Loader (backbone + stage + quality_mode=⚡速度优先) → Lora Stack → BSAIH3FilmFactory (speed_preset=均衡-VDN).
4. **切换档位** / Switch presets on the Film Factory node: 极速-VDN(8+3) / 均衡-VDN(8+4, default) / 精细-VDN(8+6).
5. **想更高画质** / For max quality: set BSAIVDNH3Loader.quality_mode = 🎨 画质优先 (16步+双LoRA) and Film Factory speed_preset = custom, steps = 16.
6. **Run** — pass-1 fixed at 8 VDN steps, then latent upscale ×2 and tiled refine.

### 2️⃣ Bullet Time LoRA（子弹时间）/ Bullet Time LoRA
1. **权重** / Weight: put BulletTime-MMH3.safetensors into ComfyUI/models/loras/ (standard ComfyUI H3 LoRA, ~96 MB).
2. **两个工作流均已挂载 @ 0.5** / Both FastH3 & VDN workflows already mount it in the Lora Stack (slot 2, strength 0.5).
3. **触发词已进模板** / Trigger words are baked into all 6 bullet-time prompt templates (BSAI-MiniMAX-H3-Prompt v1.10+): ullet time at the freeze-chapter start + *"time slows almost to completely, while the camera continues moving dynamically around the action."*
4. **强度建议** / Strength: 0.5 (clean with FastH3 turbo); try 0.7 for stronger effect, watch for deformation on fast action.
5. **手动叠加（自建工作流）** / Manual: insert a LoraLoaderModelOnly (BulletTime-MMH3, 0.5) between your model loader and the sampler.

### 2️⃣.5️⃣ 多合一版工作流 / All-in-one Workflow Guide

**文件 / File**: workflows/BSAI_H3_Film_Factory电影工厂128分钟大电影版-多合一版（FastH3+VDN双链路·tile_overlap128).json

一个工作流同时内置 **FastH3（Sol-H3）** 与 **VDN-H3** 两条模型链路，用开关一键切换，免去开两个工作流。同时含分镜 AI 生成（Qwen）、资产库、BulletTime LoRA、字幕、Premiere 导出全套。
One workflow bundles both **FastH3 (Sol-H3)** and **VDN-H3** model chains, switched by a single toggle — no need for two separate workflows. It also includes AI storyboard (Qwen), asset library, BulletTime LoRA, subtitles and Premiere export.

**双链路切换 / Chain Switch**：

| 开关 Switch | 链路 Chain | 250 档位同步选 Preset |
|---|---|---|
| **OFF**（默认 / default） | FastH3（Sol-H3 Loader 一采） | 极速 4+3 / 均衡 6+4 / 精细 8+6 |
| **ON** | VDN（BSAIVDNH3Loader ⚡8步+turbo 一采） | 极速-VDN 8+3 / 均衡-VDN 8+4 / 精细-VDN 8+6 |

**使用步骤 / Steps**：
1. 加载多合一工作流（/ Load the workflow）。
2. 拨开关选链路（OFF=FastH3，ON=VDN）；**每次只加载一条链路，避免显存双载 OOM**。/ Toggle the switch; only one chain loads at a time (prevents VRAM OOM from double-loading).
3. 在 250 BSAIH3FilmFactory 上选对应档位（见上表）。/ Pick the matching preset on the Film Factory node (see table).
4. 填分镜脚本/资产库，点 Run。/ Fill in the storyboard & assets, hit Run.

**注意事项 / Notes**：
- VDN 链路需 models/vdn/stage-dmd-step-250/ 权重 + models/diffusion_models 有基座；FastH3 链路只需 FastH3 基座。VDN requires the stage weights; FastH3 only needs the FastH3 base.
- BulletTime LoRA 已挂 276 槽 2 @0.5；tile_overlap=128 已设（去毛刺）；latent upscale ×2 内置（960×544 → 1920×1088）。/ BulletTime LoRA mounted at slot 2 @0.5; tile_overlap=128 (de-glitch); built-in latent upscale ×2.
- 想真 4K：FinalDecode 输出后外接放大节点。/ For true 4K, add an upscaler after FinalDecode.

### 3️⃣ 双机同步 / Multi-machine sync
- 本机与 4090 均 git pull 两个仓库: BSAI-ComfyUI-H3-Film-Factory (v1.86) + BSAI-MiniMAX-H3-Prompt (bullet-time trigger words).
- VDN stage + BulletTime LoRA 权重放各机 models/vdn/ 与 models/loras/（VDN 版工作流在无 VDN 权重的机器上会报缺文件，属预期）。


---

---


## v2.61 (2026-09-22) — ♻️ 恢复缓存 体验修复 ｜ ♻️ Restore Cache UX Fix
- **刷新弹窗修复** ｜ **Refresh-prompt fix**: 「♻️ 恢复缓存」按钮恢复成功后, 默认改为"留在当前页面", 把已恢复 N 个 CLIP 的数量写到节点状态栏 (紫色文字). 用户想刷新可手动 Ctrl+R. 修复了因 ComfyUI 注册的 beforeunload 监听器弹出 "是否离开网站? 你所做的更改可能未保存" 让用户以为缓存丢失的问题.
  Default behavior of "♻️ Restore Cache" changed from forced page-reload to "stay on current page, show restored count in status bar". Manually refresh (Ctrl+R) when needed. Fixes the false impression that "restore failed because of beforeunload prompt" caused by ComfyUI's own beforeunload listener.
- **渲染循环自动读盘** ｜ **Auto-read fresh chain cache**: 留在当前页面后, 再次 Queue Prompt 时 `_load_tail_latents_from_disk` 会自动读取刚被恢复的 `.h3cache` 目录, 跳过已渲染完成的 CLIP, 直接从断点继续.
  When the user queues another prompt from the same page, the renderer auto-loads the freshly restored `.h3cache` from disk and continues from the break-point, skipping the already-rendered CLIPs.
- **新增 mp4 预览路由** ｜ **New clip_preview routes**: 后端补充 `/h3_extender/clip_preview` 和 `/h3_extender/clip_preview/file` 两个路由, 让前端能从 `output/bsai_clips/h3_clip_<owner>_<idx>_<ts>.mp4` 取最新 mp4 当 `<video>` 源. 修复"恢复缓存后右侧预览面板仍空白"问题.
  Added two backend routes `/h3_extender/clip_preview` and `/h3_extender/clip_preview/file` for the frontend to fetch the newest mp4 per clip from `output/bsai_clips/`; fixes the empty preview panel after cache restore.
---
## v2.50 (2026-09-20) — Built-in Cinematic Prompt Templates ｜ 内置电影提示词模板
- **38 built-in cinematic templates** ｜ **38 个内置电影模板**:
  - 🎥 Camera Movement (12): Push In / Pull Back / Tracking / Orbit / Handheld / Steadicam... ｜ 🎥 电影运镜（12 个）：缓推 / 拉远 / 跟拍 / 环绕 / 手持 / 斯坦尼康...
  - 🎨 Color Grading (10): Warm / Cool / Teal & Orange / Noir / Morandi / Neon... ｜ 🎨 电影调色（10 个）：暖调 / 冷调 / 青橙对比 / 黑白电影 / 莫兰迪 / 霓虹赛博...
  - 🎬 Aspect & Composition (6): Widescreen / Letterbox / Rule of Thirds / Frame-in-Frame... ｜ 🎬 画面分割（6 个）：宽屏电影感 / 上下黑边 / 三分构图 / 框中框...
  - ✨ Cinematic Feel (10): Cinematic Quality / Dramatic Light / Golden Hour / Rainy Night / Tense / Epic... ｜ ✨ 电影感（10 个）：电影级画质 / 戏剧化光影 / 黄金时刻 / 雨夜氛围 / 紧张悬疑 / 史诗宏大...
- **Global Apply mode** ｜ **全局应用模式**: Top toolbar "✨ 模板" button, one-click apply to ALL clips + global prompt. ｜ 节点顶部工具栏紫色 "✨ 模板" 按钮，一键应用到所有 CLIP + 全局提示词。
- **Per-Clip Apply mode** ｜ **单 CLIP 应用模式**: Left panel "模板" tab, apply to current clip only, other clips unaffected. ｜ 每个 CLIP 左侧面板新增 "模板" tab，独立应用到当前 CLIP，其他 CLIP 不受影响。
- **Two merge options** ｜ **两种合并方式**:
  - Confirm = Merge: Keep global template + add per-clip template ｜ 确定 = 合并：保留全局模板，再加单 CLIP 模板
  - Cancel = Overwrite: Remove global template, use only per-clip template ｜ 取消 = 覆盖：移除全局模板，只保留单 CLIP 模板
- **Template tags** ｜ **模板标记**: `[电影风格-全局]...[/电影风格-全局]` for global, `[电影风格-单CLIP]...[/电影风格-单CLIP]` for per-clip. ｜ 全局用 `[电影风格-全局]...[/电影风格-全局]`，单 CLIP 用 `[电影风格-单CLIP]...[/电影风格-单CLIP]`。
- **Performance optimizations** ｜ **性能优化**:
  - Asset panel cache: skip re-render when refs unchanged (no more 150+ img reloads) ｜ 资产面板缓存：refs 没变不重新渲染，避免 150+ 个 img 重复加载
  - Global poll rate reduced from 500ms to 2000ms ｜ 全局定时器从 500ms 降到 2000ms
  - Removed duplicate node-level timer ｜ 去掉重复的节点级定时器
- **UI improvements** ｜ **UI 优化**:
  - CLIP prompt box initial height 200px, bottom-right resize handle ｜ CLIP 提示词框初始 200px 高，右下角可拖拽拉高度
  - Left panel tabs: "资产" / "模板" ｜ 左侧面板新增 tab 切换："资产" / "模板"

---
## v1.86 (2026-09-15) — VDN-H3 Presets + Bullet Time LoRA ｜ VDN-H3 速度档 + 子弹时间 Lora
- **VDN-H3 speed presets** ｜ **VDN-H3 速度档**: speed_preset adds 极速-VDN / 均衡-VDN / 精细-VDN. Pass-1 fixed at 8 VDN steps (DMD-distilled optimum, quality ≈ dense-50, linear attention keeps long clips stable); refine 3/4/6 steps. Requires the VDN workflow (workflows/电影工厂工作流-VDN版-均衡VDN8+4（tile_overlap128）.json) whose BSAIVDNH3Loader replaces the Sol-H3 chain (FastH3 LoRA & Sol-Attn skipped). ｜ speed_preset 新增三档 VDN 预设：一采固定 VDN 8 步（蒸馏最优、质量≈dense 50 步、长链线性注意力更稳），二采 3/4/6 步；需搭配 VDN 版工作流（BSAIVDNH3Loader（基座+linear_branch 一体化）替换 Sol-H3 链路，跳过 FastH3 LoRA/Sol-Attn）。
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
