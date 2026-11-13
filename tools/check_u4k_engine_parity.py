# -*- coding: utf-8 -*-
"""v14.392 引擎对齐自检：电影工厂的 4K 放大引擎映射 vs BSAI-H3-upscale-4K 插件本体。

检查项
------
1. `_FF_U4K_ENGINE_LABELS` 的每个标签都能在 4K 插件的 ENGINE_OPTIONS/TOPAZ_OPTIONS 里找到
   （标签拼错 = 该档永远路由不到引擎，而且不会报错）。
2. `_ff_u4k_call_engine` 里 `mod._xxx(...)` 调用的每个函数都真实存在于 4K 插件模块
   （4K 插件改名/重构后能立刻发现，而不是等到出片时 AttributeError）。
3. `_FF_U4K_PARAM_KEYS`（u4k_engine_params 允许的键）⊆ 4K 节点 INPUT_TYPES 的参数名，
   并列出「4K 有、我们没接」的键（长尾参数缺口一眼可见）。
4. 后端 `upscale_engine` 枚举 = 17 项，且前端 web/extender.js 的 OPTIONS 白名单与之一致
   （白名单缺值 -> 载入含该值的工作流会被静默改写）。
5. DLSS5 运行所需四件套是否就位（models/DLSS5/）。

全部用 AST 静态解析，不 import torch / comfy —— 秒级，可在提交钩子里跑。

用法
----
    python tools\\check_u4k_engine_parity.py
    python tools\\check_u4k_engine_parity.py --quiet
退出码：0 = 全对齐；1 = 有 ERROR。
"""
import argparse
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXT = os.path.join(ROOT, "extender.py")
JS = os.path.join(ROOT, "web", "extender.js")

U4K_CANDS = [
    os.environ.get("BSAI_U4K_PLUGIN_DIR", ""),
    os.path.join(os.path.dirname(ROOT), "BSAI-H3-upscale-4K"),
    os.path.join(ROOT, "_vendor", "BSAI-H3-upscale-4K"),
]

ERRORS = []
WARNS = []


def err(msg):
    ERRORS.append(msg)


def warn(msg):
    WARNS.append(msg)


def _find_u4k():
    for d in U4K_CANDS:
        if d and os.path.isfile(os.path.join(d, "bsai_h3_upscale_4k.py")):
            return os.path.join(d, "bsai_h3_upscale_4k.py")
    return None


def _module_defs(tree):
    return {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}


def _class_literal(tree, cls_name, attr):
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    for t in stmt.targets:
                        if isinstance(t, ast.Name) and t.id == attr:
                            try:
                                return ast.literal_eval(stmt.value)
                            except Exception:
                                return None
    return None


def _input_types_keys(tree, cls_name):
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            for fn in node.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == "INPUT_TYPES":
                    for r in ast.walk(fn):
                        if isinstance(r, ast.Return) and isinstance(r.value, ast.Dict):
                            for k, v in zip(r.value.keys, r.value.values):
                                if isinstance(k, ast.Constant) and k.value == "required" \
                                        and isinstance(v, ast.Dict):
                                    return [kk.value for kk in v.keys
                                            if isinstance(kk, ast.Constant)]
    return []


def _dict_assign(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    try:
                        return ast.literal_eval(node.value)
                    except Exception:
                        pass
    return None


def _frozenset_assign(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    call = node.value
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) \
                            and call.func.id == "frozenset" and call.args:
                        try:
                            return set(ast.literal_eval(call.args[0]))
                        except Exception:
                            pass
                    try:
                        return set(ast.literal_eval(call))
                    except Exception:
                        pass
    return None


def _param_keys(tree):
    """_FF_U4K_PARAM_KEYS 允许的键 = frozenset 字面量；再并上 EXTRA（引擎函数级旋钮）。"""
    keys = _frozenset_assign(tree, "_FF_U4K_PARAM_KEYS") or set()
    extra = _frozenset_assign(tree, "_FF_U4K_PARAM_KEYS_EXTRA") or set()
    return keys, extra


def _dict_entry_literal(tree, want_key):
    """在任意 dict 字面量里找 want_key 的值并 literal_eval（用于取枚举列表）。

    ComfyUI 的 widget 定义是元组 `(枚举列表, {default: ...})`，这里只取第一项。
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == want_key:
                    try:
                        if isinstance(v, ast.Tuple) and v.elts:
                            return ast.literal_eval(v.elts[0])
                        return ast.literal_eval(v)
                    except Exception:
                        continue
    return None


def _func_attr_calls(tree, func_name):
    """收集某函数体里 `mod._xxx(...)` 形式的被调函数名。"""
    calls = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                        and isinstance(sub.func.value, ast.Name) \
                        and sub.func.value.id == "mod":
                    calls.add(sub.func.attr)
    return calls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    ext_src = open(EXT, encoding="utf-8").read()
    ext_tree = ast.parse(ext_src)

    labels = _dict_assign(ext_tree, "_FF_U4K_ENGINE_LABELS")
    if not labels:
        err("extender.py 里找不到 _FF_U4K_ENGINE_LABELS 字典")
        labels = {}

    u4k_path = _find_u4k()
    if not u4k_path:
        err("找不到 BSAI-H3-upscale-4K/bsai_h3_upscale_4k.py（可设环境变量 BSAI_U4K_PLUGIN_DIR）")
    else:
        u4k_src = open(u4k_path, encoding="utf-8").read()
        u4k_tree = ast.parse(u4k_src)
        eng_opts = _class_literal(u4k_tree, "BSAI_H3_Upscale4K", "ENGINE_OPTIONS") or {}
        topaz_opts = _class_literal(u4k_tree, "BSAI_H3_Upscale4K", "TOPAZ_OPTIONS") or {}
        allowed = set(eng_opts.keys()) | set(topaz_opts.keys())
        for k, v in sorted(labels.items()):
            if v not in allowed:
                err("引擎标签对不上: %s -> %r 不在 4K 插件的 ENGINE_OPTIONS/TOPAZ_OPTIONS 里"
                    % (k, v))

        u4k_defs = _module_defs(u4k_tree)
        for fn in sorted(_func_attr_calls(ext_tree, "_ff_u4k_call_engine")):
            if fn not in u4k_defs:
                err("_ff_u4k_call_engine 调用了 4K 插件里不存在的函数: mod.%s()" % fn)

        it_keys = set(_input_types_keys(u4k_tree, "BSAI_H3_Upscale4K"))
        pk, pk_extra = _param_keys(ext_tree)
        missing = sorted(pk - it_keys)
        if missing:
            err("_FF_U4K_PARAM_KEYS 里有 4K 节点不存在的参数名: %s" % missing)
        unknown_extra = sorted(pk_extra - it_keys - set(pk))
        gap = sorted(it_keys - pk - {"images", "model_name"})
        if gap:
            warn("4K 节点有、u4k_engine_params 未透传的参数（长尾缺口）: %s" % gap)

    # 后端枚举 vs 前端白名单
    enum_vals = _dict_entry_literal(ext_tree, "upscale_engine")
    if not enum_vals:
        err("extender.py 里取不到 upscale_engine 的枚举字面量")
    else:
        legacy = ["auto", "dlss5", "realesr", "bicubic"]
        # dlss5 同时属于 legacy 与 4K 引擎集，按并集比，不重复计数
        expect = set(legacy) | set(labels)
        if set(enum_vals) != expect:
            err("后端 upscale_engine 枚举与 期望集合不一致: 多 %s 少 %s"
                % (sorted(set(enum_vals) - expect), sorted(expect - set(enum_vals))))
        if enum_vals[:4] != legacy:
            err("后端 upscale_engine 前 4 项必须仍是 legacy %s（否则旧工作流取值含义变了）: %s"
                % (legacy, enum_vals[:4]))

        js_src = open(JS, encoding="utf-8").read()
        js_line = ""
        for ln in js_src.splitlines():
            if "upscale_engine: [" in ln:
                js_line = ln
                break
        if not js_line:
            err("web/extender.js 里找不到 upscale_engine 的 OPTIONS 白名单")
        else:
            miss = [v for v in enum_vals if '"%s"' % v not in js_line]
            if miss:
                err("前端 OPTIONS 白名单缺值（载入会被静默改写）: %s" % miss)

    # DLSS5 四件套
    dlss_dir = os.path.join(os.path.dirname(os.path.dirname(ROOT)), "models", "DLSS5")
    need = ["video2dlssnr.exe", "nvngx_dlss.dll", "nvngx_dlssnr.dll", "nvngx.dll_dlssnr.dll"]
    if os.path.isdir(dlss_dir):
        lack = [n for n in need if not os.path.isfile(os.path.join(dlss_dir, n))]
        if lack:
            warn("DLSS5 缺文件（该档会回退 bicubic）: %s" % lack)
    else:
        warn("找不到 %s，DLSS5 档会回退 bicubic" % dlss_dir)

    if not args.quiet:
        print("=== u4k engine parity ===")
        print("引擎映射: %d 项" % len(labels))
        for k, v in sorted(labels.items()):
            print("  %-14s -> %s" % (k, v))
        if u4k_path:
            print("4K 插件: %s" % u4k_path)
        for w in WARNS:
            print("WARN  " + w)
    for e in ERRORS:
        print("ERROR " + e)
    if ERRORS:
        print("\n=== u4k parity FAILED (%d) ===" % len(ERRORS))
        return 1
    if not args.quiet:
        print("\n=== u4k parity OK ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
