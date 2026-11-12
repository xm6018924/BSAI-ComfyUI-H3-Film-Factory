#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""启用仓库内版本化的 git 钩子（tools/git-hooks）。

为什么不用 .git/hooks
---------------------
`.git/hooks/` 不进版本库，换台机器/重新克隆就没了，守卫会静默失效 ——
而它要防的正是「静默失效」。所以钩子放在 `tools/git-hooks/`，
每个克隆执行一次本脚本，把 `core.hooksPath` 指向它。

用法
----
    python tools\\install_git_hooks.py
    python tools\\install_git_hooks.py --uninstall
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HOOKS_DIR = os.path.join("tools", "git-hooks")


def git(*args, **kw):
    return subprocess.run(["git"] + list(args), cwd=ROOT, capture_output=True, text=True, **kw)


def main():
    if "--uninstall" in sys.argv:
        r = git("config", "--local", "--unset", "core.hooksPath")
        if r.returncode != 0:
            print("未启用（core.hooksPath 未设置）")
            return 0
        print("已取消 core.hooksPath")
        return 0

    if not os.path.isfile(os.path.join(ROOT, HOOKS_DIR, "pre-commit")):
        print("找不到 %s/pre-commit" % HOOKS_DIR)
        return 1

    r = git("config", "--local", "core.hooksPath", HOOKS_DIR)
    if r.returncode != 0:
        print("设置 core.hooksPath 失败：", r.stderr.strip())
        return 1

    # 让钩子在 Linux/macOS 侧克隆里也可执行（Windows 上 git 仍会按 sh 调用）
    git("update-index", "--chmod=+x", HOOKS_DIR.replace(os.sep, "/") + "/pre-commit")

    cur = git("config", "--get", "core.hooksPath").stdout.strip()
    print("core.hooksPath = %s" % cur)
    print("已启用：改动 web/*.js 或 extender.py 时，提交前会自动跑")
    print("  - web/*.js 语法检查（复制成 .mjs 再 node --check，避免 import 干扰漏报）")
    print("  - 快捷条枚举同步自检（tools/check_quickbar_enum_sync.py）")
    print("临时跳过：git commit --no-verify")
    return 0


if __name__ == "__main__":
    sys.exit(main())
