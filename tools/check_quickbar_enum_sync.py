# -*- coding: utf-8 -*-
"""前端快捷按钮硬编码表(QUICK_DEFS) vs 后端 INPUT_TYPES 枚举 —— 一致性自检。

为什么要这个工具
----------------
电影工厂插件的快捷按钮里, 枚举型 widget 的可选项由 `web/extender.js` 的
`QUICK_DEFS` 表驱动, 每个枚举表项写死 **两份** 列表:

    cycle:       实际写回 widget 的值(必须与后端 INPUT_TYPES 的枚举字面量逐字一致)
    cycleLabels: 按钮上显示的英文

后端新增一个枚举项, 而前端这两份表没同步 -> 下拉里选不到新档。
(v14.213 "渲染管道下拉看不到第 13 档" 就是这么来的: .py 加了档, 前端 cycle/cycleLabels 没跟上。)

v14.218 起再加第三张表(可选):

    cycleAliases: 旧中文别名 -> 规范值的映射。后端 v2.120c 起枚举是中英双语的
                  (英文规范值 + 旧中文别名都合法), 前端 cycle 只放**规范值**,
                  旧别名通过 cycleAliases 换算, 这样:
                    * 后端枚举的每个值都能在快捷下拉里被表达(cycle 或 alias);
                    * 旧工作流存的旧中文值, 档位序号/进度条/高亮依然算得对;
                    * 快捷下拉写回的永远是后端规范值(逐字合法, 等于后端 default)。

本工具做四类检查:
  1) cycle 与 cycleLabels 长度是否一致(缺一份 = 选到了但没名字/名字错位);
  2) 后端枚举项是否都被前端表达(cycle 或 alias) —— 缺 = 下拉里选不到;
  3) 前端 cycle / alias 里是否有后端已不存在的值 —— 多 = 选到无效值, 后端静默回落;
  4) **遗留兼容层**(`H3LegacyCompat` 的 OPTIONS 白名单 + DEFAULTS)与后端是否一致:
     OPTIONS 缺后端值 -> 载入工作流时该值会被当成"选项外"静默改写成默认值;
     DEFAULTS 不是后端合法值 -> 载入时会写进一个后端不认的值。

用法
----
    python tools\check_quickbar_enum_sync.py
退出码: 0 = 全一致(只允许 WARN); 1 = 存在 ERROR(逐条打印)。

注: 不需要 ComfyUI 在跑(直接 import 插件模块取 INPUT_TYPES), 但需要能 import torch。
"""
import io
import json
import os
import re
import sys
import types
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, ".."))
COMFY = os.path.abspath(os.path.join(PLUGIN, "..", ".."))
JS = os.path.join(PLUGIN, "web", "extender.js")
EXT = os.path.join(PLUGIN, "extender.py")


def load_backend_enums():
    """import extender.py(造包别名 + stub server.PromptServer) 取 INPUT_TYPES 的枚举。"""
    os.chdir(COMFY)
    if COMFY not in sys.path:
        sys.path.insert(0, COMFY)

    fake_server = types.ModuleType("server")

    class _Routes:
        def get(self, *a, **k):
            def deco(fn):
                return fn
            return deco
        post = put = delete = get

    class _DummyPS:
        routes = _Routes()

        def send_sync(self, *a, **k):
            pass

        def send(self, *a, **k):
            pass

    class PromptServer:
        instance = _DummyPS()

    fake_server.PromptServer = PromptServer
    sys.modules["server"] = fake_server

    PKG = "bsai_h3_ff_enum_probe"
    pkg = types.ModuleType(PKG)
    pkg.__path__ = [PLUGIN]
    sys.modules[PKG] = pkg
    spec = importlib.util.spec_from_file_location(PKG + ".extender", EXT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)

    node_cls = None
    for name in dir(mod):
        obj = getattr(mod, name)
        if isinstance(obj, type) and hasattr(obj, "INPUT_TYPES"):
            try:
                it = obj.INPUT_TYPES()
            except Exception:
                continue
            if isinstance(it, dict) and "required" in it and any("clips_json" in k for k in it["required"]):
                node_cls = obj
                break
    if node_cls is None:
        raise RuntimeError("找不到 BSAIH3FilmFactory 节点类")

    it = node_cls.INPUT_TYPES()
    enums = {}
    for section in ("required", "optional"):
        for k, spec_ in (it.get(section) or {}).items():
            v = spec_[0] if isinstance(spec_, (list, tuple)) and spec_ else None
            if isinstance(v, list) and v and all(isinstance(x, str) for x in v):
                enums[k] = v
    return enums


# ---------------------------------------------------------------- JS 解析工具
def _match_brace(text, i):
    """text[i] 必须是 '{'; 返回匹配 '}' 之后的下标(跳过字符串内的花括号)。"""
    depth = 0
    n = len(text)
    in_str = False
    esc = False
    while i < n:
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return n


def _split_top(body):
    """按顶层逗号切分 JS 数组字面量(字符串里的逗号不算)。"""
    parts = []
    buf = []
    in_str = False
    esc = False
    depth = 0
    for c in body:
        if in_str:
            buf.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
            buf.append(c)
            continue
        if c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
            continue
        buf.append(c)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _js_array(text, name):
    """解析 const <name> = [...] -> list(元素已转成 python 值)。"""
    m = re.search(r"const\s+" + re.escape(name) + r"\s*=\s*\[", text)
    if not m:
        return None
    start = m.end() - 1
    end = _match_brace(text, start) if text[start] == "[" else len(text)
    # 数组用方括号, 单独处理
    depth = 0
    in_str = False
    esc = False
    i = start
    while i < len(text):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        i += 1
    body = text[start + 1:end - 1]
    out = []
    for el in _split_top(body):
        try:
            out.append(json.loads(el))
        except Exception:
            out.append(el)
    return out


def parse_quick_defs(js_text):
    """解析 QUICK_DEFS -> [(key, cycle, cycleLabels, cycleAliases)]。"""
    out = []
    for m in re.finditer(r'\{\s*key:\s*"([^"]+)"', js_text):
        start = m.start()
        blob = js_text[start:_match_brace(js_text, start)]
        if "cycle:" not in blob:
            continue
        cyc_m = re.search(r"cycle:\s*\[(.*?)\]", blob, re.S)
        lab_m = re.search(r"cycleLabels:\s*\[(.*?)\]", blob, re.S)
        if not cyc_m:
            continue
        vals = re.findall(r'"((?:[^"\\]|\\.)*)"', cyc_m.group(1))
        labels = re.findall(r'"((?:[^"\\]|\\.)*)"', lab_m.group(1)) if lab_m else []
        aliases = {}
        al_m = re.search(r"cycleAliases:\s*\{(.*?)\}", blob, re.S)
        if al_m:
            for a, b in re.findall(r'"((?:[^"\\]|\\.)*)"\s*:\s*"((?:[^"\\]|\\.)*)"', al_m.group(1)):
                aliases[a] = b
        out.append((m.group(1), vals, labels, aliases))
    return out


def parse_legacy_tables(js_text):
    """解析遗留兼容层的 OPTIONS 白名单 + KEYS/DEFAULTS 位置表。"""
    options = {}
    m = re.search(r"const\s+OPTIONS\s*=\s*\{", js_text)
    if m:
        start = m.start()
        blob = js_text[start:_match_brace(js_text, start)]
        for km in re.finditer(r"(\w+):\s*\[(.*?)\]", blob, re.S):
            key = km.group(1)
            vals = re.findall(r'"((?:[^"\\]|\\.)*)"', km.group(2))
            if vals:
                options[key] = vals
    keys = _js_array(js_text, "KEYS") or []
    defaults = _js_array(js_text, "DEFAULTS") or []
    return options, keys, defaults


# -------------------------------------------------------------------- 主检查
def main():
    js_text = io.open(JS, encoding="utf-8").read()
    backend = load_backend_enums()
    entries = parse_quick_defs(js_text)
    legacy_opts, legacy_keys, legacy_defaults = parse_legacy_tables(js_text)

    print(f"[前端] QUICK_DEFS 枚举项 {len(entries)} 个: {[e[0] for e in entries]}")
    print(f"[后端] 枚举型 widget {len(backend)} 个\n")
    print(f"{'key':<24}{'cycle':>6}{'labels':>7}{'alias':>6}{'后端':>6}  结论")
    print("-" * 84)

    errors = []
    warns = []
    for key, vals, labels, aliases in entries:
        b = backend.get(key)
        if b is None:
            print(f"{key:<24}{len(vals):>6}{len(labels):>7}{len(aliases):>6}{'-':>6}  ⚠ 后端不是枚举/已移除")
            warns.append((key, "后端没有该 widget 或不是枚举"))
            continue
        issues = []
        if len(vals) != len(labels):
            issues.append(f"cycle({len(vals)}) != cycleLabels({len(labels)})")
        missing = [x for x in b if x not in vals and x not in aliases]
        extra = [x for x in vals if x not in b]
        bad_alias_key = [k for k in aliases if k not in b]
        bad_alias_target = [t for t in aliases.values() if t not in vals or t not in b]
        if missing:
            issues.append("后端有前端没有(下拉里选不到): " + ", ".join(missing))
        if extra:
            issues.append("前端有后端没有(选到无效值): " + ", ".join(extra))
        if bad_alias_key:
            issues.append("alias 键不是后端枚举值: " + ", ".join(bad_alias_key))
        if bad_alias_target:
            issues.append("alias 目标不是合法 cycle 项: " + ", ".join(sorted(set(bad_alias_target))))
        verdict = "OK" if not issues else "MISMATCH: " + "; ".join(issues)
        print(f"{key:<24}{len(vals):>6}{len(labels):>7}{len(aliases):>6}{len(b):>6}  {verdict}")
        if issues:
            errors.append((key, "; ".join(issues)))

    # ---- 遗留兼容层(OPTIONS 白名单 / DEFAULTS) ----
    print("\n[遗留兼容层 H3LegacyCompat] OPTIONS 白名单 vs 后端枚举")
    if legacy_opts:
        for key in sorted(legacy_opts):
            b = backend.get(key)
            if b is None:
                continue
            ov = legacy_opts[key]
            miss = [x for x in b if x not in ov]
            extra = [x for x in ov if x not in b]
            if miss:
                msg = ("白名单缺后端值(载入工作流时会被静默改写成默认值): " + ", ".join(miss))
                print(f"  {key:<24} ERROR {msg}")
                errors.append((key, msg))
            if extra:
                msg = ("白名单留了后端已不接受的遗留值: " + ", ".join(extra))
                print(f"  {key:<24} WARN  {msg}")
                warns.append((key, msg))
            if not miss and not extra:
                print(f"  {key:<24} OK    ({len(ov)} 项)")
    else:
        print("  (未找到 OPTIONS 表)")

    print("\n[遗留兼容层 H3LegacyCompat] DEFAULTS 位置表 vs 后端枚举")
    dmap = {}
    for i, k in enumerate(legacy_keys):
        if i < len(legacy_defaults):
            dmap[k] = legacy_defaults[i]
    bad_default = []
    for key, d in dmap.items():
        b = backend.get(key)
        if b is None or not isinstance(d, str):
            continue
        if d not in b:
            bad_default.append((key, d))
    for key, d in bad_default:
        msg = "前端默认值不是后端合法值: %r" % (d,)
        print(f"  {key:<24} ERROR {msg}")
        errors.append((key, msg))
    if not bad_default:
        print("  全部合法")

    qkeys = {e[0] for e in entries}
    only_node_body = [k for k in sorted(backend) if k not in qkeys]
    if only_node_body:
        print("\n[提示] 后端枚举但不在快捷按钮里的(只能在节点体内选):")
        for k in only_node_body:
            print(f"   - {k}: {backend[k]}")

    print()
    if errors:
        print("=== DESYNC (%d ERROR) ===" % len(errors))
        for k, msg in errors:
            print(f"  {k}: {msg}")
        return 1
    if warns:
        print("=== SYNC OK (无 ERROR; %d WARN) ===" % len(warns))
    else:
        print("=== SYNC OK (前端两份硬编码表 + 遗留兼容层与后端枚举完全一致) ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
