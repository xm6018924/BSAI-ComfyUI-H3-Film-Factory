# -*- coding: utf-8 -*-
r"""一镜到底「段内行程 / 换场位置」规则冒烟测试 (v14.341)。

为什么要这个工具
----------------
BSAI第077期 21 段一镜到底 MV（走遍世界，1920x1088，TaoMate 8+4）clip2 出现两处
切镜：scdet 在 2.083s 给出 score=14.439（同片中位 0.30），5.042s 给出 0.861。
抽帧确认 0-2.04s 仍是 clip1 的故宫券门、2.08s 一帧硬切成帕特农石阶背面、5.00s
又跳成正面近景对口型。根因有三层，全部落在插件代码里：

  1) 换场判定错位一段 —— 旧代码拿 `_os_scene_names[i-1]`（上一段的**起点**）与本段
     起点对比。脚本按链式路线写（段1 S1→S2、段2 S2→S3…），于是"本段起点 vs 上段
     起点"永远不相等，每段都被判成换场，而且描述的是**上一段**的换场；段1 一条空间
     规则都没拿到，段2 收到段1 的 S1→S2 并被压进段首 -> 先拖旧画面 2 秒再一帧换背景。
  2) 段内行程串被误删 —— `_OS_ROUTE_CHAIN_RE` 把带 `@图` 标签的本段行程
     （`S2 …@图4-登阶上行 → T2 … → S3 …@图5`）当成"分镜结构"整条清掉，模型既不知
     起点也不知过渡物。
  3) 正文写的是**全片绝对时间码**（`0:12–0:13.5`、`0:24`），一个 12 秒片段里出现
     0:24 这种不可能满足的锚点，与"段首1.5秒"互相打架。

本工具锁死修好之后的这三件事，防止以后再被改回去。不启动 ComfyUI、不加载权重，
只 import 插件模块（stub `server.PromptServer`，与 check_recast_pipeline.py 同一套引导）。

用法
----
    python tools\check_one_shot_route_rules.py
退出码: 0 = 全通过; 1 = 有用例失败。
"""
import importlib.util
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, ".."))
COMFY = os.path.abspath(os.path.join(PLUGIN, "..", ".."))
EXT = os.path.join(PLUGIN, "extender.py")


def load_mod():
    os.chdir(COMFY)
    if COMFY not in sys.path:
        sys.path.insert(0, COMFY)
    fake = types.ModuleType("server")

    class _Routes:
        def get(self, *a, **k):
            def deco(fn):
                return fn
            return deco
        post = put = delete = get

    class _PS:
        routes = _Routes()

        def send_sync(self, *a, **k):
            pass

        def send(self, *a, **k):
            pass

    class PromptServer:
        instance = _PS()

    fake.PromptServer = PromptServer
    sys.modules["server"] = fake
    PKG = "bsai_h3_ff_route_probe"
    pkg = types.ModuleType(PKG)
    pkg.__path__ = [PLUGIN]
    sys.modules[PKG] = pkg
    spec = importlib.util.spec_from_file_location(PKG + ".extender", EXT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# 与 BSAI第077期 同构的链式行程(段1 S1→S2, 段2 S2→S3)，含 @图 标签、T 过渡物、
# 段首人声标签、以及**全片绝对**时间码。
CLIP1 = (
    "S1 故宫·午门城台拱墙@图3-沿城台缓行 → T1 西南侧券门拱脚（直行绕过·0°） → "
    "S2 雅典帕特农神庙·卫城山门@图4（【演唱中】·段首入唱·人声0:00起）"
    "【本段运镜：单条连续轨迹·连续变距（中景起幅→近景收幅），不新增机位、不切镜】\n"
    "01-12秒：正面跟拍缓行，走到券门拱脚。"
)
CLIP2 = (
    "S2 雅典帕特农神庙·卫城山门@图4-登阶上行 → T2 山门石阶阙口右柱脚（直行绕过·0°） → "
    "S3 圣家族大教堂·中殿侧廊@图5（【演唱中】·段首入唱·人声0:12起）"
    "【本段运镜：单条连续轨迹·连续变距（中景起幅→中近景→近景→中近景收幅），不新增机位、不切镜】\n"
    "01-12秒：沿石阶上行。"
    "0:12–0:13.5 闭口行进（段首1.5秒无唱），0:13.5 双唇开启进入人声窗口0:13.5–0:24。"
)
CLIP3 = (
    "S3 圣家族大教堂·中殿侧廊@图5-沿侧廊前行 → T3 尖拱门左侧门框（侧身通过·15°） → "
    "S4 蓝色清真寺·内庭连廊@图6（【演唱中】·段中入唱）\n"
    "01-12秒：沿侧廊直行。"
)
CUT_WORDS = ("切镜", "转场", "叠化", "硬切", "切换", "淡入", "淡出")


def main():
    m = load_mod()
    ok = True
    fails = []

    def check(name, cond, detail=""):
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))
        if not cond:
            ok = False
            fails.append(name)

    # ── 1) 每段自己的行程 ────────────────────────────────────────────────
    r1 = m._one_shot_scene_route(CLIP1, [])
    r2 = m._one_shot_scene_route(CLIP2, [])
    r3 = m._one_shot_scene_route(CLIP3, [])
    check("段1 起行空间", r1["start"] == "S1 故宫·午门城台拱墙", r1["start"])
    check("段1 过渡物", r1["transit"] == "T1 西南侧券门拱脚", r1["transit"])
    check("段1 终止空间", r1["end"] == "S2 雅典帕特农神庙·卫城山门", r1["end"])
    check("段2 起行空间", r2["start"] == "S2 雅典帕特农神庙·卫城山门", r2["start"])
    check("段2 过渡物", r2["transit"] == "T2 山门石阶阙口右柱脚", r2["transit"])
    check("段2 终止空间", r2["end"] == "S3 圣家族大教堂·中殿侧廊", r2["end"])
    check("段3 起行空间", r3["start"] == "S3 圣家族大教堂·中殿侧廊", r3["start"])
    check("行程跨两处空间(cross=True)",
          all(x["cross"] for x in (r1, r2, r3)),
          f"{r1['cross']}/{r2['cross']}/{r3['cross']}")
    check("行程不吞吃【本段运镜】小节",
          "本段运镜" not in (r1["route"] + r2["route"]), (r1["route"] + r2["route"])[:60])
    check("行程里保留 @图 标签",
          "@图4" in r1["route"] and "@图3" in r1["route"], r1["route"][:70])

    # ── 2) 接缝判定: 用**上一段的 end** 对比 ──────────────────────────────
    routes = [r1, r2, r3]
    d1 = m._one_shot_space_decision(routes, 0)
    d2 = m._one_shot_space_decision(routes, 1)
    d3 = m._one_shot_space_decision(routes, 2)
    check("段1 无上一段 -> 换场落在段中(mid)", d1[2:] == ("空间过渡", "mid"), str(d1[2:]))
    check("段2 接缝连续(上段末=S2=本段起行) -> mid", d2[2:] == ("空间过渡", "mid"), str(d2[2:]))
    check("段2 上段末场景 = 段1 终止空间", d2[1] == r1["end"], d2[1])
    check("段3 接缝连续 -> mid", d3[2:] == ("空间过渡", "mid"), str(d3[2:]))
    check("段2 不再被判成 head(旧 bug 的核心症状)",
          d2[3] != "head", str(d2))

    # ── 3) 向后兼容: 无箭头旧格式(接缝真换场) 仍走 v14.332 的段首换场 ──
    old = [
        {"start": "滨海堤岸", "end": "滨海堤岸", "transit": None, "cross": False},
        {"start": "滨海公路路口", "end": "滨海公路路口", "transit": None, "cross": False},
        {"start": "滨海公路路口", "end": "滨海公路路口", "transit": None, "cross": False},
    ]
    check("旧格式: 接缝真换场 -> head",
          m._one_shot_space_decision(old, 1)[2:] == ("空间过渡", "head"),
          str(m._one_shot_space_decision(old, 1)[2:]))
    check("旧格式: 同一处空间 -> 同场景延续",
          m._one_shot_space_decision(old, 2)[2] == "同场景延续",
          str(m._one_shot_space_decision(old, 2)[2]))
    check("旧格式: 首段无空间规则(kind=None)",
          m._one_shot_space_decision(old, 0)[2] is None,
          str(m._one_shot_space_decision(old, 0)[2]))

    # ── 4) 清洗链: 段首行程串不被删、空括号与段首垃圾清掉 ───────────────
    clean2 = m._one_shot_demulti_shot(CLIP2, label="clip2")
    check("清洗后仍以段首行程开头(不是标点垃圾)",
          clean2.startswith("S2 雅典帕特农神庙·卫城山门@图4"), clean2[:40])
    check("清洗后保留终止空间与参考图",
          "S3 圣家族大教堂·中殿侧廊@图5" in clean2, clean2[:120])
    check("清洗后保留过渡物 T2", "T2 山门石阶阙口右柱脚" in clean2, "T2" in clean2)
    check("清洗后无空括号残留",
          m._OS_EMPTY_PAREN_RE.search(clean2) is None, clean2[:60])
    check("清洗后段首无孤立标点", clean2[0] not in "：:，,、；;）)）", clean2[:10])

    # ── 5) 正文时间码归一(全片绝对 -> 段内相对) ─────────────────────────
    tc = m._one_shot_normalize_timecodes(CLIP2, 12.0, 12.0)
    check("0:12 -> 0:00", "0:00–0:01.5" in tc, tc[-80:])
    check("0:13.5 -> 0:01.5", "0:01.5 双唇开启" in tc, tc[-80:])
    check("0:24 -> 0:12(不再是 0:24)", "0:01.5–0:12" in tc and "0:24" not in tc, tc[-80:])
    rel = "0:00–0:01.5 闭口行进，0:01.5–0:12 演唱"
    check("已是相对时间码的段不被平移",
          m._one_shot_normalize_timecodes(rel, 12.0, 12.0) == rel,
          m._one_shot_normalize_timecodes(rel, 12.0, 12.0))
    check("段1(offset=0) 一律不动",
          m._one_shot_normalize_timecodes(rel, 0.0, 12.0) == rel,
          m._one_shot_normalize_timecodes(rel, 0.0, 12.0))

    # ── 6) 段中换场规则措辞纪律 ─────────────────────────────────────────
    mid = m._one_shot_transit_mid_rule(r2["start"], r2["end"], r2["transit"])
    anchor = m._one_shot_scene_anchor_mid_rule(r2["start"], r2["end"], r2["transit"])
    check("段中换场规则含两侧空间与过渡物",
          r2["start"] in mid and r2["end"] in mid and r2["transit"] in mid, mid[:60])
    check("段中换场规则不含切镜词",
          all(w not in mid for w in CUT_WORDS),
          [w for w in CUT_WORDS if w in mid])
    check("场景锚定不含切镜词",
          all(w not in anchor for w in CUT_WORDS),
          [w for w in CUT_WORDS if w in anchor])
    check("接缝换场规则已去掉写死的夜色/壁灯",
          ("夜色" not in m._OS_SPACE_TRANSIT_RULE
           and "壁灯" not in m._OS_SPACE_TRANSIT_RULE
           and "夜的深处" not in m._OS_SPACE_TRANSIT_RULE),
          "夜色" in m._OS_SPACE_TRANSIT_RULE)

    print()
    if ok:
        print("全部通过 (v14.341 一镜到底段内行程/换场位置/时间码 规则自检)")
        return 0
    print(f"失败 {len(fails)} 项: {fails}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
