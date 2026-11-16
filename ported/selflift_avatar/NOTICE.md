# Third-party notice

The full-sequence H3 memory-saving modules in this folder are adapted from
[Fish4AI/comfyui-SelfLift-Fish](https://github.com/Fish4AI/comfyui-SelfLift-Fish):

- `h3_global_tiling.py`
- `h3_stream_attention.py`
- `h3_ram_attention.py`
- `h3_output_chunking.py`
- `h3_prepared_weights.py`

Local changes add selflift-Avatar mask propagation, lazy loading, node wiring,
status reporting, input-projection chunking, and CPU/UI tests. The original
SelfLift project is by facok; Fish's global-context work is by the Fish4AI
maintainers. This fork is independent and is not an official release of either
project. Model weights, the H3 backbone, and ComfyUI remain subject to their own
licenses.

## Thanks

Special thanks to [Fish4AI](https://github.com/Fish4AI), author of
[comfyui-SelfLift-Fish](https://github.com/Fish4AI/comfyui-SelfLift-Fish), for
publishing the global-context memory-saving work that this project adapts. The
full-sequence chunking, head-group streaming, host-RAM staging, output chunking,
and prepared-weight reuse modules in this folder originate from that work.

Thanks also to facok for the original comfyui-SelfLift project and to the
SelfLift paper authors.
