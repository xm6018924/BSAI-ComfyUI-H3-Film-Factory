#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""v14.270 rollback tool for BSAI-ComfyUI-H3-Film-Factory / extender.py.

Purpose
-------
v14.270 changed how the refine pass decides to enable temporal chunking:
the trigger moved from "T >= 200" to "tokens per spatial tile > 130000".
If that change misbehaves on a machine, this tool restores the exact
pre-change file, and can also re-apply the v14.270 file afterwards.

Usage (run from anywhere):
    python tools/rollback_v14_270.py check      # inspect only, change nothing
    python tools/rollback_v14_270.py rollback   # restore the pre-v14.270 file
    python tools/rollback_v14_270.py restore    # re-apply the v14.270 file

Files used
----------
  extender.py                                  live file
  extender.py.bak_v14270_pre_20261031          snapshot BEFORE v14.270
  extender.py.bak_v14270_applied_<timestamp>   snapshot of the v14.270 file,
                                               created automatically by
                                               `rollback` so you can `restore`

Every write is verified by sha256 + py_compile before it is accepted.
"""

import hashlib
import io
import os
import py_compile
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
LIVE = os.path.join(PKG, "extender.py")
PRE = os.path.join(PKG, "extender.py.bak_v14270_pre_20261031")

# fingerprints recorded at the time the change was made
PRE_SHA = "f777a4a560c7bbbad1db8d59fe67346d8212aec099f382883f2520cbd0ccdb4b"
V14270_MARKER = "v14.270 自动时间分块"


def _out(*a):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(*a)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_text(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def compile_ok(path):
    """py_compile without leaving a .pyc next to the source."""
    try:
        tmpdir = tempfile.mkdtemp(prefix="h3_rollback_")
        py_compile.compile(path, cfile=os.path.join(tmpdir, "x.pyc"), doraise=True)
        shutil.rmtree(tmpdir, ignore_errors=True)
        return True, ""
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, e)


def describe(path):
    if not os.path.isfile(path):
        return None
    txt = read_text(path)
    return {
        "sha": sha256(path),
        "size": os.path.getsize(path),
        "has_v14270": V14270_MARKER in txt,
    }


def find_latest_applied():
    """Newest snapshot that actually CONTAINS the v14.270 logic.

    `restore` also snapshots the file it replaces (which may be the
    pre-change file). Those must never be picked as a re-apply source,
    otherwise `restore` would silently reinstall the pre-change file.
    """
    cands = [
        os.path.join(PKG, n)
        for n in os.listdir(PKG)
        if n.startswith("extender.py.bak_v14270_applied_")
    ]
    if not cands:
        return None
    good = []
    for c in cands:
        try:
            if V14270_MARKER in read_text(c):
                good.append(c)
        except Exception:
            pass
    pool = good if good else cands
    return max(pool, key=os.path.getmtime)


def install(src, dst, label, snap_prefix="applied"):
    """Copy src -> dst with snapshot + sha + compile verification."""
    src_info = describe(src)
    if src_info is None:
        _out("[FAIL] source missing: %s" % src)
        return False

    dst_info = describe(dst)
    if dst_info is not None:
        keep = os.path.join(
            PKG,
            "extender.py.bak_v14270_%s_%s.py"
            % (snap_prefix, __import__("time").strftime("%Y%m%d_%H%M%S")),
        )
        shutil.copy2(dst, keep)
        # copy2 preserves the source mtime, which would make "newest snapshot"
        # resolution unreliable (an old file copied later still looks old).
        # Force the snapshot's mtime to now so ordering reflects creation time.
        os.utime(keep, None)
        _out("  [snapshot] current file saved -> %s" % os.path.basename(keep))

    shutil.copy2(src, dst)

    after = describe(dst)
    if after is None or after["sha"] != src_info["sha"]:
        _out("[FAIL] sha mismatch after copy — file NOT trusted")
        return False
    ok, err = compile_ok(dst)
    if not ok:
        _out("[FAIL] syntax check failed: %s" % err)
        return False

    _out("  [ok] %s installed" % label)
    _out("       sha256=%s" % after["sha"])
    _out("       size=%d bytes, v14.270 present=%s" % (after["size"], after["has_v14270"]))
    return True


def cmd_check():
    _out("=== v14.270 rollback: CHECK (no changes) ===")
    pre = describe(PRE)
    if pre is None:
        _out("[FAIL] pre-change backup NOT found: %s" % PRE)
        _out("       Without it, file-level rollback is impossible.")
        return 1
    ok_pre = pre["sha"] == PRE_SHA
    _out("pre-change backup : %s" % os.path.basename(PRE))
    _out("  sha256=%s" % pre["sha"])
    _out("  matches expected (%s): %s" % (PRE_SHA[:12] + "...", ok_pre))
    _out("  has v14.270 logic: %s  (must be False)" % pre["has_v14270"])

    live = describe(LIVE)
    _out("live extender.py :")
    _out("  sha256=%s" % live["sha"])
    _out("  has v14.270 logic: %s" % live["has_v14270"])
    if live["has_v14270"]:
        _out("  status: v14.270 IS applied")
    else:
        _out("  status: v14.270 is NOT applied (already rolled back?)")

    applied = find_latest_applied()
    _out("re-apply snapshot : %s" % (os.path.basename(applied) if applied else "(none)"))

    if not ok_pre:
        _out("[WARN] pre-change backup sha differs from the recorded value.")
        _out("       It may have been modified; inspect before trusting it.")
        return 1
    _out("RESULT: rollback is available.")
    return 0


def cmd_rollback():
    _out("=== v14.270 rollback: restore pre-change extender.py ===")
    pre = describe(PRE)
    if pre is None:
        _out("[FAIL] pre-change backup missing: %s" % PRE)
        return 1
    if pre["sha"] != PRE_SHA:
        _out("[WARN] backup sha differs from recorded value; continuing anyway.")
    if pre["has_v14270"]:
        _out("[FAIL] the backup already contains v14.270 — refusing to overwrite.")
        return 1
    ok = install(PRE, LIVE, "pre-v14.270 extender.py", snap_prefix="applied")
    _out("RESULT: %s" % ("rolled back OK — restart ComfyUI" if ok else "FAILED"))
    return 0 if ok else 1


def cmd_restore():
    _out("=== v14.270 rollback: re-apply the v14.270 extender.py ===")
    applied = find_latest_applied()
    if applied is None:
        _out("[FAIL] no applied snapshot found (run `rollback` first).")
        return 1
    info = describe(applied)
    if not info["has_v14270"]:
        _out("[WARN] %s does not look like the v14.270 file." % os.path.basename(applied))
    ok = install(applied, LIVE, os.path.basename(applied), snap_prefix="rolledback")
    _out("RESULT: %s" % ("v14.270 re-applied — restart ComfyUI" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "check").strip().lower()
    table = {"check": cmd_check, "rollback": cmd_rollback, "restore": cmd_restore}
    if cmd not in table:
        _out(__doc__)
        return 2
    return table[cmd]()


if __name__ == "__main__":
    sys.exit(main())
