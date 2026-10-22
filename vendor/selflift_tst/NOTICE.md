# Third-party notice

The Temporal State Transport (TST) module in this folder is vendored from
[facok/comfyui-SelfLift](https://github.com/facok/comfyui-SelfLift):

- `h3_tst.py`

It is copied verbatim from the locally installed snapshot of comfyui-SelfLift
(hash matches the `published_python_sha256` recorded in the selflift-Avatar
provenance, `36b9d849...`), and is vendored here so that BSAI
ComfyUI-H3-Film-Factory users get the P2 few-step quality compensation
(`selflift_tst_enable` / `selflift_tst_tau`) **without having to install
comfyui-SelfLift separately**.

TST implements arXiv:2609.08505 (Temporal State Transport) as an inference-time
correction for MiniMax H3 joint attention. The upstream project is by facok;
this vendored copy is independent and is not an official release of that
project. Model weights, the H3 backbone, and ComfyUI remain subject to their
own licenses.

The upstream file is kept byte-for-byte unmodified; integration happens in
`extender.py::_apply_h3_tst`, which loads this vendored copy first and falls
back to an externally installed comfyui-SelfLift if present.

## Thanks

Special thanks to [facok](https://github.com/facok) for the original
comfyui-SelfLift project and to the TST paper authors.
