#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""前端守卫：web/*.js 语法检查（module 模式）+ 快捷条枚举同步自检。

为什么必须用 module 模式
------------------------
对 `.js` 直接 `node --check` 会被文件头 `import` 语句干扰，语法错误仍然返回 0。
本插件已经因此漏过两次「一处结构破坏 -> 整个前端一行都不执行」：

  * v14.365   cycleLabels 里 `, ,` 空位 + 两个字符串相邻缺逗号
  * v14.387   render_pipeline 的 QUICK_DEFS 对象尾部多一个 `]`（`}]] },` 应为 `}] },`）

两次的外在症状都不是报错，而是「该隐藏的参数没隐藏 + CLIP 卡片/全局提示词消失」，
排查成本极高。所以本脚本把文件**原样复制成 .mjs** 再让 node 校验本体。

用法
----
    python tools\\check_frontend_guard.py                # 语法 + 枚举，全查
    python tools\\check_frontend_guard.py --syntax-only   # 只查语法（快，不 import torch）
    python tools\\check_frontend_guard.py --enum-only     # 只查枚举同步
    python tools\\check_frontend_guard.py --js a.js b.js  # 只查指定文件的语法

退出码：0 = 通过；1 = 有失败项（逐条打印原因）。
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WEB = os.path.join(ROOT, "web")
ENUM_CHECKER = os.path.join(HERE, "check_quickbar_enum_sync.py")


def find_node():
    exe = shutil.which("node") or shutil.which("node.exe")
    if exe:
        return exe
    for cand in (
        r"C:\Program Files\nodejs\node.exe",
        r"C:\Program Files (x86)\nodejs\node.exe",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(ROOT))), "nodejs", "node.exe"),
    ):
        if cand and os.path.isfile(cand):
            return cand
    return None


def collect_js():
    if not os.path.isdir(WEB):
        return []
    return sorted(
        os.path.join(WEB, n) for n in os.listdir(WEB)
        if n.lower().endswith(".js") and os.path.isfile(os.path.join(WEB, n))
    )


def check_syntax(files, node):
    """逐个把 js 复制成 .mjs 再 node --check；返回失败列表。"""
    failures = []
    for path in files:
        name = os.path.basename(path)
        with open(path, "rb") as fh:
            data = fh.read()
        fd, tmp = tempfile.mkstemp(suffix=".mjs", prefix="guard_")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            res = subprocess.run(
                [node, "--check", tmp], capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        if res.returncode != 0:
            # node 的报错里带临时文件名，换成真实文件名，便于定位
            msg = (res.stderr or res.stdout or "").replace(tmp, path)
            failures.append((path, msg.strip()))
            print(f"[语法] FAIL  web/{name}")
        else:
            print(f"[语法] OK    web/{name}  (module 模式 node --check)")
    return failures


def check_enum():
    if not os.path.isfile(ENUM_CHECKER):
        print("[枚举] SKIP  未找到 tools/check_quickbar_enum_sync.py")
        return None
    print("[枚举] 运行 tools/check_quickbar_enum_sync.py ...")
    res = subprocess.run(
        [sys.executable, ENUM_CHECKER], cwd=ROOT,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    out = (res.stdout or "") + (res.stderr or "")
    tail = [ln for ln in out.strip().splitlines() if ln.strip()]
    for ln in tail[-12:]:
        print("       " + ln)
    if res.returncode != 0:
        print("[枚举] FAIL  快捷条枚举 / 遗留兼容层与后端枚举不一致")
        return out.strip()
    print("[枚举] OK    前后端枚举一致")
    return None


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--syntax-only", action="store_true")
    ap.add_argument("--enum-only", action="store_true")
    ap.add_argument("--js", nargs="+", default=None, help="只检查指定 js 文件")
    args = ap.parse_args()
    if args.syntax_only and args.enum_only:
        print("--syntax-only 与 --enum-only 不能同时使用")
        return 2

    failed = []

    if not args.enum_only:
        files = [os.path.abspath(p) for p in args.js] if args.js else collect_js()
        if not files:
            print("[语法] SKIP  没有可检查的 web/*.js")
        else:
            node = find_node()
            if not node:
                print("[语法] SKIP  找不到 node，可装 Node.js 后重跑（此步会跳过）")
            else:
                failed.extend(check_syntax(files, node))

    if not args.syntax_only:
        if check_enum():
            failed.append(("enum", ""))

    print("")
    if failed:
        print(f"=== GUARD FAILED ({len(failed)} 项) ===")
        for path, msg in failed:
            if msg:
                print(f"--- {path} ---")
                print(msg)
        return 1
    print("=== GUARD OK ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
