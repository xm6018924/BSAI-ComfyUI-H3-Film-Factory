"""MiniMax H3 external prompt bridge.

Packs numbered STRING prompt outputs from story/prompt generator nodes into one
H3_PROMPT_PACK socket that the MiniMax H3 Extender can import into its normal
per-clip prompt cards.

The frontend presents these sockets as an autogrowing list.  The backend keeps
a generous fixed declaration so the legacy V1 node API can still validate and
execute dynamically-created prompt_N sockets on both classic nodes and Nodes 2.0.
"""

from __future__ import annotations

import hashlib
import json

# V1 custom nodes do not have native backend autogrow inputs.  The frontend
# therefore shows only the sockets that are useful while this declaration keeps
# enough valid prompt_N names available for execution/validation.
MAX_PROMPTS = 128
PROMPT_PACK_TYPE = "H3_PROMPT_PACK"
PROMPT_PACK_VERSION = 1


def _pack_prompts(values):
    """Return prompts as one compact ordered list.

    Empty/unconnected inputs are ignored.  This makes the bridge behave like a
    normal ordered list: if a middle source is disconnected, every later prompt
    moves up one position in the pack instead of leaving a hole or raising an
    error.  The frontend mirrors the same behavior by compacting/renaming its
    visible prompt_N sockets while preserving the connected cables.
    """
    prompts = []
    for value in list(values)[:MAX_PROMPTS]:
        text = "" if value is None else str(value)
        if not text.strip():
            continue
        prompts.append(text)

    if not prompts:
        raise ValueError(
            "MiniMax H3 Prompt Pack Bridge: no non-empty prompts were received."
        )
    return prompts


def _prompt_pack_signature(prompts):
    payload = json.dumps(
        list(prompts),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class MiniMaxH3PromptPackBridge:
    """Pack a dynamic ordered series of STRING inputs into one Extender input."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt_1": (
                    "STRING",
                    {
                        "forceInput": True,
                        "tooltip": "Connect the first STRING prompt. More prompt inputs appear automatically.",
                    },
                ),
            },
            "optional": {
                **{
                    f"prompt_{i}": (
                        "STRING",
                        {
                            "forceInput": True,
                            "tooltip": f"Dynamic STRING prompt {i}.",
                        },
                    )
                    for i in range(2, MAX_PROMPTS + 1)
                },
            },
        }

    RETURN_TYPES = (PROMPT_PACK_TYPE, "INT")
    RETURN_NAMES = ("prompt_pack", "prompt_count")
    FUNCTION = "pack"
    CATEGORY = "BSAI/H3 Film Factory"
    OUTPUT_NODE = False

    def pack(self, prompt_1, **kwargs):
        values = [prompt_1]
        values.extend(kwargs.get(f"prompt_{i}") for i in range(2, MAX_PROMPTS + 1))
        prompts = _pack_prompts(values)
        signature = _prompt_pack_signature(prompts)
        pack = {
            "type": PROMPT_PACK_TYPE,
            "version": PROMPT_PACK_VERSION,
            "source": "MiniMax H3 Prompt Pack Bridge",
            "count": len(prompts),
            "prompts": prompts,
            "signature": signature,
        }
        return (pack, int(len(prompts)))


NODE_CLASS_MAPPINGS = {
    "MiniMaxH3PromptPackBridge": MiniMaxH3PromptPackBridge,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3PromptPackBridge": "BSAI H3 Film Factory | Prompt Pack Bridge",
}
