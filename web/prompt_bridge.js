import { app } from "../../scripts/app.js";

const TARGET = "MiniMaxH3PromptPackBridge";
const MAX_PROMPTS = 128;
const PROMPT_RE = /^prompt_(\d+)$/;

function promptIndex(input) {
    const match = String(input?.name || "").match(PROMPT_RE);
    if (!match) return 0;
    const index = Number(match[1]);
    return Number.isInteger(index) && index >= 1 && index <= MAX_PROMPTS ? index : 0;
}

function isConnected(input) {
    return input?.link !== null && input?.link !== undefined;
}

function currentPromptInputs(node) {
    return (node?.inputs || [])
        .map((input, slot) => ({ input, slot, index: promptIndex(input) }))
        .filter((entry) => entry.index > 0)
        .sort((a, b) => a.slot - b.slot);
}

function addPromptInput(node, index) {
    if (!node || index < 1 || index > MAX_PROMPTS) return;
    if ((node.inputs || []).some((input) => promptIndex(input) === index)) return;
    node.addInput(`prompt_${index}`, "STRING");
}

function removePromptInput(node, slot) {
    if (!node || slot < 0 || slot >= (node.inputs || []).length) return;
    try {
        node.removeInput(slot);
    } catch (_) {
        // Keep the workflow usable even if a future frontend changes LiteGraph's
        // slot-removal internals. The next connection/configuration event retries.
    }
}

function renamePromptInput(input, index) {
    if (!input || index < 1 || index > MAX_PROMPTS) return false;
    const nextName = `prompt_${index}`;
    const oldName = String(input.name || "");
    if (oldName === nextName) return false;

    input.name = nextName;
    // Some ComfyUI/LiteGraph builds cache a separate visible label. Only rewrite
    // it when it was itself a generated prompt_N label; custom labels are kept.
    if (typeof input.label === "string" && PROMPT_RE.test(input.label)) {
        input.label = nextName;
    }
    return true;
}

function fitNodeHeight(node) {
    try {
        const computed = node?.computeSize?.();
        const height = Number(computed?.[1]);
        const width = Number(node?.size?.[0]);
        if (Number.isFinite(height) && height > 0 && Number.isFinite(width) && width > 0) {
            node.setSize?.([width, height]);
        }
    } catch (_) {}
}

function syncPromptInputs(node) {
    if (!node || node.__h3PromptBridgeSyncing) return;
    node.__h3PromptBridgeSyncing = true;

    let changed = false;
    try {
        let entries = currentPromptInputs(node);

        // The Bridge is an ordered LIST, not a fixed-ID reference bank. Remove
        // every empty prompt socket first (including a hole in the middle). Work
        // backwards so LiteGraph can safely shift target_slot values of later
        // connected cables as inputs are removed.
        const emptyEntries = entries
            .filter(({ input }) => !isConnected(input))
            .sort((a, b) => b.slot - a.slot);

        for (const { slot } of emptyEntries) {
            const before = (node.inputs || []).length;
            removePromptInput(node, slot);
            changed = changed || (node.inputs || []).length !== before;
        }

        // Any connected inputs that survived are now physically compacted. Rename
        // them in visual/cable order so prompt_3 automatically becomes prompt_2
        // when the former prompt_2 is disconnected. Renaming preserves the cable.
        entries = currentPromptInputs(node).filter(({ input }) => isConnected(input));
        for (let i = 0; i < entries.length; i++) {
            changed = renamePromptInput(entries[i].input, i + 1) || changed;
        }

        // Keep exactly one free socket after the connected list. With no links,
        // this recreates prompt_1. Connecting the free socket causes the next one
        // to appear on the following sync.
        const nextIndex = Math.min(MAX_PROMPTS, entries.length + 1);
        if (entries.length < MAX_PROMPTS) {
            const before = (node.inputs || []).length;
            addPromptInput(node, nextIndex);
            changed = changed || (node.inputs || []).length !== before;
        }

        if (changed) fitNodeHeight(node);
        node.graph?.setDirtyCanvas(true, true);
    } finally {
        node.__h3PromptBridgeSyncing = false;
    }
}

function deferSync(node) {
    if (!node || node.__h3PromptBridgeSyncQueued) return;
    node.__h3PromptBridgeSyncQueued = true;
    requestAnimationFrame(() => {
        node.__h3PromptBridgeSyncQueued = false;
        syncPromptInputs(node);
    });
}

app.registerExtension({
    name: "MiniMaxH3.PromptPackBridge.DynamicInputs",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== TARGET) return;

        const oldCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = oldCreated ? oldCreated.apply(this, arguments) : undefined;
            // Comfy creates all V1-declared optional sockets first. Collapse the
            // bridge immediately to its autogrowing presentation.
            deferSync(this);
            return result;
        };

        const oldConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = oldConfigure ? oldConfigure.apply(this, arguments) : undefined;
            // Saved workflows are normalized to the current compact list behavior.
            // Existing connected cables are preserved; only empty gaps disappear.
            deferSync(this);
            return result;
        };

        const oldConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            const result = oldConnectionsChange
                ? oldConnectionsChange.apply(this, arguments)
                : undefined;
            // Defer until LiteGraph has finished mutating the link itself.
            deferSync(this);
            return result;
        };
    },
});
