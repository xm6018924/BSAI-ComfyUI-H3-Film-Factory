"""Copy the runtime part of the official ComfyUI-PTD code into ptd_inference/.

    git clone --branch release/comfyui-inference https://github.com/vita-epfl/PTD-inference
    python tools/vendor_ptd.py PTD-inference

The files are copied unchanged except that their absolute ``ptd.`` imports become relative, so the copy
needs no pip install and cannot clash with an installed ``ptd`` package.
"""
import os
import re
import shutil
import subprocess
import sys

FILES = ["LICENSE", "NOTICE", "ptd/__init__.py", "ptd/recipes.py", "ptd/schedule.py",
         "ptd_comfy/__init__.py", "ptd_comfy/checkpoint.py", "ptd_comfy/nodes.py", "ptd_comfy/patcher.py",
         "ptd_comfy/sampling.py"]

src = sys.argv[1]
dst = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ptd_inference")
commit = subprocess.run(["git", "-C", src, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
for name in FILES:
    os.makedirs(os.path.join(dst, os.path.dirname(name)), exist_ok=True)
    if not name.endswith(".py"):
        shutil.copyfile(os.path.join(src, name), os.path.join(dst, name))
        continue
    with open(os.path.join(src, name)) as f:
        text = f.read()
    if name.startswith("ptd_comfy/"):
        text = re.sub(r"^(\s*)from ptd\.", r"\1from ..ptd.", text, flags=re.M)
    if re.search(r"^\s*(from|import) ptd(_comfy)?\b", text, flags=re.M):
        sys.exit(f"{name}: absolute ptd import left after rewriting; update tools/vendor_ptd.py")
    with open(os.path.join(dst, name), "w") as f:
        f.write(text)
with open(os.path.join(dst, "__init__.py"), "w") as f:
    f.write(f'"""Runtime part of ComfyUI-PTD (https://github.com/vita-epfl/PTD-inference), vendored by\n'
            f'tools/vendor_ptd.py from commit {commit}. Do not edit; re-run the tool instead."""\n\n'
            f'COMMIT = "{commit}"\n')
print(f"vendored {len(FILES)} files from {commit}")
