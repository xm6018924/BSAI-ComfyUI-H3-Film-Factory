from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

# The official PTD Loader / Sampler / Sigmas come from the vendored copy of ComfyUI-PTD (ptd_inference/), so
# workflows using them run without the official pack. If that pack is installed too and ComfyUI imports it
# first, its nodes stay registered; if it loads after this pack, it replaces these. compact.ptd_modules()
# follows whichever copy is registered.
try:
    import nodes as _comfy_nodes
    if "PTDH3Sampler" not in _comfy_nodes.NODE_CLASS_MAPPINGS:
        from .ptd_inference.ptd_comfy import nodes as _official
        NODE_CLASS_MAPPINGS = {**_official.NODE_CLASS_MAPPINGS, **NODE_CLASS_MAPPINGS}
        NODE_DISPLAY_NAME_MAPPINGS = {**_official.NODE_DISPLAY_NAME_MAPPINGS, **NODE_DISPLAY_NAME_MAPPINGS}
except ImportError:  # outside ComfyUI
    pass

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
