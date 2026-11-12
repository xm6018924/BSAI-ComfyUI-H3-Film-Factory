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
# v14.342: H3 CFG=1.0 没有负向分支, 规则里的否定词会被当成画面内容渲染 —— 注入文本必须是
# 纯正向陈述。这里只查规则模板本身(不含用户正文)。
NEG_WORDS = ("不", "没有", "禁止", "勿", "无从", "无法", "别让", "别的", "别去")
# v14.344: "不" 只做否定词时才有害; "不同 / 景别 / 不只" 是正向比较或术语, 判红就是假阳。
# (v14.343 已经因为裸 "别" 误判过 "景别", 这里是同一类假阳的第二次出现。)
BENIGN_WORD_PARTS = ("不同", "景别", "不只")


def _neg_scan(text):
    """把假阳片段先摘掉, 再让 NEG_WORDS 扫描。"""
    for _benign in BENIGN_WORD_PARTS:
        text = text.replace(_benign, "")
    return text
# v14.343: 段中换场规则里出现任何"后移"类写法, 正面机位下都会被模型执行成拉开距离,
# 观感即"倒着走" —— 这类词必须从规则模板里彻底消失。
BACK_WORDS = ("后退", "退出", "后移", "拉远", "拉开", "退后")


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

    # ── 7) v14.343 段中换场: 机位零后退 + 柱面整块遮镜, 拆掉双曝与倒行两个来源 ────
    # v14.342 实测(16:39 clip1 / 18:07 clip2 两片): 规则里的"机位平稳后退"被模型执行成
    # 拉开距离 -> 正面朝镜头 + 距离变远 = 倒着走; 而"主体全程在位"与"过渡物占满整幅画面"
    # 互相矛盾 -> 模型用双曝(中心淡入淡出)同时满足两者。
    check("段中换场: 机位零后退(规则里没有后退/退出/拉远这类后移写法)",
          all(w not in mid for w in BACK_WORDS),
          [w for w in BACK_WORDS if w in mid])
    # v14.376 (11:29 轮 h3_clip_250_1_1794367784 复渲): 用户判定"从头到尾全是倒着走"。
    # 复核确认 v14.375 把「画幅以他为锚 / 位置固定在同一个地方 / 双脚踩在同一片地面区域内」
    # 三条钉得更死了 —— 主体一旦钉死在画幅里, 又要求他"行走", 模型只能让双腿原地倒腾。
    # 这版把锚拆掉: 机位与机身固定不动、只做变距, 位移全部由"朝镜头走近 -> 画幅里变大"承担。
    check("段中换场: 步态是正走(屈膝前摆→越过支撑脚→脚跟先着地→画幅里是鞋面与鞋尖)",
          "屈膝向前摆" in mid
          and "膝盖领先于脚尖" in mid
          and "脚跟先着地、鞋尖随后落平" in mid
          and "鞋面与鞋尖" in mid, mid[:60])
    # v14.346 实测(15:44 轮 clip1): 这两句并置 = moonwalk 配方 —— 鞋底朝镜头且变大(只有往后
    # 甩腿才看得见鞋底) + 景物"迎面朝镜头流动"(机位在前进)。机位前进时她只能往后甩腿。
    # v14.375 实测(10:07 轮 clip1 h3_clip_250_1_1794362835): 占画高一路变大、地面砖缝逐帧
    # 纹丝不动 -> 双脚在画幅下方原地倒腾, moonwalk 仍在。原因是规则改了、**正文**里的
    # 「机位沿其行进方向平稳前移」没改; 这版规则补了机位几何句 + 落脚点与地面流动同向。
    check("段中换场: 已删掉 moonwalk 三个来源(鞋底由小变大 / 脚跟随后抬起 / 脚从身后甩向镜头 / 景物迎面朝镜头)",
          "鞋底在画幅里由小变大" not in mid
          and "脚跟随后抬起" not in mid
          and "迎面朝镜头流动过来" not in mid
          and "甩到镜头" not in mid, mid[:200])
    # v14.378 (本版翻案): v14.376 的「机位钉在一处地面位置」与本插件自己的 [取景连续]
    # (摄影机与他同速同行、同距同高、占画比例自始至终稳定)硬自相矛盾。实测新片
    # h3_clip_250_1_1794384070: 地面中位 dy 仅 +0.04~0.06px/帧(地面不动), 占画高
    # 0.187→0.709 全靠"变大", 双腿原地不动 = 用户判定"倒着走"。口径统一到脚本原句。
    check("段中换场: 机位与他同速同行、同距同高(与[取景连续]同一口径)",
          "沿同一条轨迹与他同速同行、同距同高" in mid
          and "始终正对画幅里他的正面" in mid, mid[:60])
    check("段中换场: 前进凭据钉在地面(石缝与柱列一道接一道后流过画幅)",
          "一道接一道向后流过画幅下缘" in mid
          and "同样一道接一道向后流过画幅两侧" in mid, mid[:60])
    check("段中换场: 前进凭据不再靠'逐秒变大'(逐秒由小到大/全部来源 已删)",
          "逐秒由小到大" not in mid
          and "全部来源" not in mid
          and "头顶在画幅里逐秒上移" not in mid, mid[:60])
    check("矛盾守卫: 同一条规则里不得同时出现『机位固定』与『同速同行』",
          not ("机位与镜头机身固定在同一处地面位置上" in mid and "同速同行" in mid), mid[:60])
    check("段中换场: 一步跨过一道新石缝且可数(一秒三到四道, 跨过的留在身后)",
          "一秒之内他跨过三到四道石缝" in mid
          and "已经跨过的石缝留在画幅里他的身后" in mid, mid[:60])
    check("段中换场: 落脚点落在更靠近画幅下缘的新石缝上(倒走做不到)",
          "落在更靠近画幅下缘的一道新石缝上" in mid, mid[:60])
    check("段中换场: 脚掌与石缝零滑动(踩实后与那道石缝位置完全重合、随它一起后滑)",
          "脚掌踩实之后与它踩住的那道石缝位置完全重合" in mid
          and "随后随地面一起从画幅下缘滑出去" in mid, mid[:60])
    check("段中换场: 鞋底鞋跟朝向地面(画幅里只出现鞋面/鞋尖/鞋带)",
          "鞋底与鞋跟朝向地面与画幅下缘" in mid, mid[:60])
    check("段中换场: 景物不再是静止的(冻住世界+要求行走=原地倒腾, v14.378 已删)",
          "各自停在原处" not in mid
          and "各自固定在原处" not in mid, mid[:60])
    check("段中换场: 主体不再被钉死在画幅里(v14.343 的锚三条已拆)",
          "本段画幅以他为锚" not in mid
          and "位置自始至终固定在同一个地方" not in mid
          and "双脚始终踩在画幅下方同一片地面区域内" not in mid, mid[:60])
    # ── 7c) v14.385: 换场必须是「主体自己走过去」, 不得整幅遮挡 ────────────────
    # 用户口径(针对 h3_clip_250_1_1794456674): 场景变化不对, 一镜到底应该是从上一个
    # 场景自然走进下一个场景。旧文本的「柱身涨满画幅、整块盖住镜头、主体藏在石面后」
    # 出片就是约 9s 整幅石面盖镜 + 跳进另一个空间, 观感等于一次转场。
    check("段中换场: 换场由主体自己跨过门洞完成(门洞推近→门框向两侧分开→跨过门槛石)",
          "换场由他自己走过去完成" in mid
          and "两条竖直门框向画幅左右两侧分开" in mid
          and "跨过门槛的那一拍" in mid, mid[:60])
    check("段中换场: 全程主体完整在画幅里、脚步连续(不再被挡掉再出现)",
          "主体完整地出现在画幅中央" in mid
          and "脚步连续" in mid
          and "画幅的四角自始至终看得见地面与两侧建筑" in mid, mid[:60])
    check("段中换场: 不再有整幅遮挡机制(盖住镜头/每一寸都是石头/藏在实心石面 全部删除)",
          "盖住镜头" not in mid
          and "画幅的每一寸都是石头" not in mid
          and "藏在" not in mid
          and "涨满整幅画幅" not in mid
          and "占满画幅的四角" not in mid, mid[:60])
    check("段中换场: 空间在主体身上逐拍替换(start 的墙/柱/灯逐拍换成 end 的)",
          "逐拍换成" in mid and "第一道石缝" in mid, mid[:60])
    check("段中换场: 明写每拍只有一处空间的实景(双曝无动机)",
          "画幅里每一拍只有一处空间的实景" in mid, mid[:60])
    check("接缝换场(_OS_SPACE_TRANSIT_RULE) 也不再靠门墙遮挡那一瞬换景",
          "画幅被门墙与门框挡住" not in m._OS_SPACE_TRANSIT_RULE
          and "门框的两条竖边从画幅左右两侧掠过" in m._OS_SPACE_TRANSIT_RULE)
    check("段中换场: 过渡物立在两处空间之间(门框这一侧 / 另一侧)",
          "就立在" in mid and "门框这一侧是" in mid and "门框的另一侧是" in mid, mid[:60])
    check("段中换场: 正文的'同速穿过'已纳入本段覆盖清单",
          "与她同速穿过某处" in mid, mid[:60])
    # ── 7b) v14.344: 起幅归属 / 换场时间窗 / 换场后只剩 end ─────────────────────
    # v14.343 实机首片(11:12 clip1)结果: 双曝与倒行都消失, 但整段只在 S2 里走, S1 故宫一帧
    # 都没出现 —— v14.343 的首句把"起幅"写成了"站在过渡物的 S1 一侧", 模型读成"已经站在门
    # 口", 露头就迈出门, 整段留在 S2; 加上"同一条地面/同一片夜色"把两处空间合成一处。
    check("段中换场: 起幅归属钉在 start(跨过门槛前画幅里全是 start 自己的东西)",
          "起幅到跨过门槛之前" in mid and "全是" in mid
          and "按脚本写给" in mid, mid[:60])
    check("段中换场: 换场带时间窗(第三秒到第六秒), 避免被提前到 0 秒",
          "换场落在本段中段" in mid and "第三秒到第六秒" in mid, mid[:60])
    check("段中换场: 跨过门槛后到末帧只剩 end 自己的东西(两处不再混同)",
          "跨过门槛之后他到本段末帧" in mid
          and "画幅两侧与身后的" in mid
          and "逐拍换成" in mid, mid[:60])
    check("段中换场: 两处空间明确不同(已删掉'同一条地面/同一片夜色'这类同一化措辞)",
          "各自的地面、墙面、颜色与标志物彼此明显不同" in mid
          and "同一条地面" not in mid, mid[:60])
    check("段中换场规则不含否定词(CFG=1.0 会把否定词当画面内容)",
          all(w not in _neg_scan(mid) for w in NEG_WORDS),
          [w for w in NEG_WORDS if w in _neg_scan(mid)])
    check("场景锚定: 置换点挂在跨过门槛之前/那一拍之后(不再挂在柱面遮镜)",
          "跨过" in anchor and "门槛之前" in anchor
          and "门槛石与门框的两条竖边就是这两处空间的分界" in anchor, anchor[:60])

    # ── 8) v14.375: 正文机位方向句中和 + 采样档/管线优先级 ─────────────────────
    # 10:07 轮(h3_clip_250_1_1794362835)两处实测: ① moonwalk 仍在, 因为规则改了而**正文**里
    # 「镜头与主播@图1…沿其行进方向平稳前移」一字未动; ② OneShotSmp=单采无缝 把 PIKA 8+2
    # 管线的二采整段跳过, 12s 只跑一采 8 步。
    _body_probe = ("镜头与主播@图1始终在同一条向前行进的连续弧线轨迹上，同速同向、"
                   "正对主播@图1的正面，沿其行进方向平稳前移并随拐点微摆")
    try:
        _body_out = m._one_shot_neutralize_camera_dir(_body_probe)
    except Exception as _e:
        _body_out = f"<{_e}>"
    check("正文机位方向句不再被改写(用户脚本正文原样进提示词, v14.378 清空改写表)",
          _body_out == _body_probe, _body_out[:80])
    _body_probe2 = "在这条唯一轨迹上，机身以连续无级的方式改变拍摄距离"
    try:
        _body_out2 = m._one_shot_neutralize_camera_dir(_body_probe2)
    except Exception as _e:
        _body_out2 = f"<{_e}>"
    check("正文机身变距句不再被改写(取景变化只由脚本自己声明)",
          _body_out2 == _body_probe2, _body_out2[:80])
    try:
        _src = open(getattr(m, "__file__", ""), "r", encoding="utf-8").read()
    except Exception:
        _src = ""
    check("采样档与管线冲突已显式处理(管线声明二采时按管线执行, 并播报冲突)",
          "v14.375 采样档与管线冲突" in _src
          and "one_shot_single_pass = False" in _src, "extender.py 源码扫描")

    print()
    if ok:
        print("全部通过 (v14.344 一镜到底段内行程/换场位置/时间码/遮挡机制/起幅归属 规则自检)")
        return 0
    print(f"失败 {len(fails)} 项: {fails}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
