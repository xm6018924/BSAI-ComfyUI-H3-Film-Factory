"""
BSAI-ComfyUI-H3 Film Factory
A complete film production toolkit for MiniMax H3 workflows.

Core H3 nodes (from original MiniMax H3 Extender):
  - MiniMaxH3Extender: Full H3 video generation pipeline with CLIP sequencing
  - MiniMaxH3MotionContextRAM: In-RAM motion context chaining
  - MiniMaxH3MotionContextDiskJoin: Disk-based motion context join
  - MiniMaxH3MotionContextDiskFinalDecode: Final decode/export with codec settings
  - MiniMaxH3TailFromLatent: Tail frame/audio extraction from latent
  - MiniMaxH3PromptPackBridge: Dynamic prompt input packer

Film Factory nodes (new):
  - BSAI_ContextualSeriesExtract/Load: Contextual frame extraction
  - BSAI_AssetLibraryInput/RefSelector/ImageBatchSplitter: Asset management
  - BSAI_ClipComposer/ClipSequencer: Clip editing and sequencing
  - BSAI_SubtitleConfig/SubtitleRenderer: Subtitle rendering
  - BSAI_VideoCombiner/AudioCombiner: Media combining
"""

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

# === Core H3 nodes (from original MiniMax H3 Extender) ===
try:
    from .node import (
        NODE_CLASS_MAPPINGS as UTILITY_NODE_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as UTILITY_NODE_DISPLAY_NAME_MAPPINGS,
    )
    NODE_CLASS_MAPPINGS.update(UTILITY_NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(UTILITY_NODE_DISPLAY_NAME_MAPPINGS)
except Exception as e:
    print(f"[H3 Film Factory] node.py import failed: {e}")

try:
    from .motion_context_ram import (
        NODE_CLASS_MAPPINGS as MOTION_CONTEXT_NODE_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as MOTION_CONTEXT_NODE_DISPLAY_NAME_MAPPINGS,
    )
    NODE_CLASS_MAPPINGS.update(MOTION_CONTEXT_NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(MOTION_CONTEXT_NODE_DISPLAY_NAME_MAPPINGS)
except Exception as e:
    print(f"[H3 Film Factory] motion_context_ram.py import failed: {e}")

try:
    from .extender import (
        NODE_CLASS_MAPPINGS as EXTENDER_NODE_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as EXTENDER_NODE_DISPLAY_NAME_MAPPINGS,
    )
    NODE_CLASS_MAPPINGS.update(EXTENDER_NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(EXTENDER_NODE_DISPLAY_NAME_MAPPINGS)
except Exception as e:
    print(f"[H3 Film Factory] extender.py import failed: {e}")

try:
    from .motion_context_disk import (
        NODE_CLASS_MAPPINGS as MOTION_CONTEXT_DISK_NODE_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as MOTION_CONTEXT_DISK_NODE_DISPLAY_NAME_MAPPINGS,
    )
    NODE_CLASS_MAPPINGS.update(MOTION_CONTEXT_DISK_NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(MOTION_CONTEXT_DISK_NODE_DISPLAY_NAME_MAPPINGS)
except Exception as e:
    print(f"[H3 Film Factory] motion_context_disk.py import failed: {e}")

try:
    from .prompt_bridge import (
        NODE_CLASS_MAPPINGS as PROMPT_BRIDGE_NODE_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as PROMPT_BRIDGE_NODE_DISPLAY_NAME_MAPPINGS,
    )
    NODE_CLASS_MAPPINGS.update(PROMPT_BRIDGE_NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(PROMPT_BRIDGE_NODE_DISPLAY_NAME_MAPPINGS)
except Exception as e:
    print(f"[H3 Film Factory] prompt_bridge.py import failed: {e}")

# === Film Factory nodes (new) ===
try:
    from .nodes import NODE_CLASS_MAPPINGS as CONTEXTUAL_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS as CONTEXTUAL_DISPLAY
    NODE_CLASS_MAPPINGS.update(CONTEXTUAL_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(CONTEXTUAL_DISPLAY)
except Exception as e:
    print(f"[H3 Film Factory] nodes.py import failed: {e}")

try:
    from .nodes_asset import NODE_CLASS_MAPPINGS as ASSET_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS as ASSET_DISPLAY
    NODE_CLASS_MAPPINGS.update(ASSET_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(ASSET_DISPLAY)
except Exception as e:
    print(f"[H3 Film Factory] nodes_asset.py import failed: {e}")

try:
    from .nodes_clip import NODE_CLASS_MAPPINGS as CLIP_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS as CLIP_DISPLAY
    NODE_CLASS_MAPPINGS.update(CLIP_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(CLIP_DISPLAY)
except Exception as e:
    print(f"[H3 Film Factory] nodes_clip.py import failed: {e}")

try:
    from .nodes_subtitle import NODE_CLASS_MAPPINGS as SUBTITLE_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS as SUBTITLE_DISPLAY
    NODE_CLASS_MAPPINGS.update(SUBTITLE_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(SUBTITLE_DISPLAY)
except Exception as e:
    print(f"[H3 Film Factory] nodes_subtitle.py import failed: {e}")

try:
    from .nodes_media import NODE_CLASS_MAPPINGS as MEDIA_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS as MEDIA_DISPLAY
    NODE_CLASS_MAPPINGS.update(MEDIA_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(MEDIA_DISPLAY)
except Exception as e:
    print(f"[H3 Film Factory] nodes_media.py import failed: {e}")

try:
    from .bsai_h3_3dlatent_upscale import (
        NODE_CLASS_MAPPINGS as H3_3D_UPSCALE_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as H3_3D_UPSCALE_DISPLAY,
    )
    NODE_CLASS_MAPPINGS.update(H3_3D_UPSCALE_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(H3_3D_UPSCALE_DISPLAY)
except Exception as e:
    print(f"[H3 Film Factory] bsai_h3_3dlatent_upscale.py import failed: {e}")

# === Server-side API endpoints ===
try:
    from . import server
except Exception as e:
    print(f"[H3 Film Factory] server module load failed: {e}")

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]

WEB_DIRECTORY = "./web"
