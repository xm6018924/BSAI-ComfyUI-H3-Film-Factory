# -*- coding: utf-8 -*-
r"""生成第 35 档「视频角色替换+动作迁移」示例工作流。

从 v14.335 的「视频替换V2V人物替换-角色替换LoRA-45s自动分3段」克隆，做三件事：

  1) 档位与采样参数改成 remix 契约：8 步一采(v14.344 默认) + 5 步二采(放大 1.5x)、
     一采 denoise 0.62 / 二采 denoise 0.30（v14.347 起 denoise = 真实 σ 起点）、
     段间续接 22 帧、输出原声、非一镜到底；
  2) 把 LoRA 槽从 swap/角色替换 LoRA 换成 8 步 Ref2VA 加速 LoRA
     —— 本档的契约是"不要求任何 swap LoRA"，只允许加速 LoRA；
  3) 分镜命名/提示词改为"角色替换"口径（背景按原片写 = 人物替换；
     只写新场景 = 动作迁移）。

用法
----
    python tools\build_remix_workflow.py            # 写出插件里的示例工作流
    python tools\build_remix_workflow.py --check    # 只校验示例产物
    python tools\build_remix_workflow.py --sync-user  # 把同一套参数打到用户实战工作流
                                                      # (OneDrive\...\BSAI第077期\...-v14.341.json)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, ".."))
EXDIR = os.path.join(PLUGIN, "example_workflows")

SRC = os.path.join(
    EXDIR, "BSAI_H3_Film_Factory电影工厂-视频替换V2V人物替换-角色替换LoRA-45s自动分3段-v14.335.json")
DST = os.path.join(
    EXDIR, "BSAI_H3_Film_Factory电影工厂-视频角色替换+动作迁移-无LoRA-长视频自动分段续接-v14.341.json")

TIER_EN = "Video Remix (no-LoRA character swap + motion transfer)"
ACCEL_LORA = "H3\\H3加速\\pdd_acc\\minimax_h3_ref2va_pdd_acc_8step_comfyui.safetensors"
NODE_TITLE = "BSAI ComfyUI H3 Film Factory v14.341·视频角色替换+动作迁移"

# 位置表（与 web/extender.js 的 KEYS 顺序一致）
IDX = {
    "steps": 4,
    "denoise": 7,
    "context_length": 8,
    "refine_enable": 26,
    "refine_denoise": 27,
    "refine_steps": 28,
    "refine_upscale_factor": 29,
    "refine_upscaler_model": 30,
    "refine_audio_denoise": 32,
    "one_shot_mode": 63,
    "render_pipeline": 65,
}

PATCH = {
    "steps": 8,
    "denoise": 0.62,
    "context_length": "22",
    "refine_enable": True,
    "refine_denoise": 0.30,
    "refine_steps": 5,
    "refine_upscale_factor": 1.5,
    "refine_upscaler_model": "(bilinear interpolation, no model)",
    "refine_audio_denoise": 0.0,
    "one_shot_mode": "off (storyboard)",
    "render_pipeline": TIER_EN,
}


USER_DST = (r"C:\Users\xm204\OneDrive\2025AI-完美工作流\Comfyui-BSAI\BSAI-系列节目工作流"
            r"\BSAI第077期\BSAI_H3_Film_Factory电影工厂-视频角色替换+动作迁移-无LoRA-"
            r"长视频自动分段续接-v14.341.json")

USER_NOTE = """【视频角色替换+动作迁移（Video Remix · 渲染管道第 35 档）· 使用说明】

① 资产库视频位 = 被替换的源视频，分镜里写 @视频1
   不必手工切段：后端按 226 帧(≈9.42s)/段自动分段，段间 22 帧锁定续接；42.5s 源片 → 5 段。
   （分镜卡片上的 15s 只是卡片时长，本档实际按 226 帧走，不按 15s 硬切。）
② 资产库图片位 = 替换成的人物参考图（@图1）
   建议单人正面全身、背景干净的单张图；多视图拼版会被裁切，宽高比 <0.35 的窄条碎片自动丢弃。
③ 人物替换 vs 动作迁移只由提示词决定：
   · 写「把 @视频1 里的人换成 @图1」且不写新场景 → 人物掩码锁背景，背景保留源视频（默认）
   · 写「换场景 / 另一个场景 / 背景换成…」 → 全画幅重绘（动作迁移，背景自由改）
   · 想强制：环境变量 BSAI_H3_REMIX_KEEP_BG=1（锁背景）/ =0（全画幅）
④ 本档参数（后端强制）：
   一采 8 步 euler+simple shift 12-3，denoise 0.62（v14.347 起 = 真实 σ 起点）+ 人物掩码
   二采 5 步 1.5x，denoise 0.30，且沿用一采人物掩码（背景不在二采二次洗）
   段间 context 22 帧；输出原声；一镜到底关闭
   ⚠ 本档禁止挂 swap/角色替换 LoRA（会把参考图身份压掉）；加速 LoRA 用 ref2va pdd_acc 8 步
⑤ denoise 是唯一主旋钮：
   换人不够彻底 → 调到 0.75~0.80（动作贴合会略松）
   动作走形 / 衣服纹理崩 → 下调到 0.55~0.60
"""


def _apply(d, note_text=None):
    """把 remix 契约打到 dict 上(原地修改), 返回 (节点, widgets_values, clips)。"""
    n = None
    for node in d["nodes"]:
        if node.get("type") == "BSAIH3FilmFactory":
            n = node
            break
    if n is None:
        raise SystemExit("工作流里找不到 BSAIH3FilmFactory 节点")

    wv = n["widgets_values"]
    for k, v in PATCH.items():
        wv[IDX[k]] = v
    named = n.get("widgets_values_named")
    if isinstance(named, dict):
        for k, v in PATCH.items():
            if k in named:
                named[k] = v

    # 分镜：改名 + 只保留 3 段（其余由后端按 226/22 自动补齐）
    cj = json.loads(wv[10]) if isinstance(wv[10], str) else wv[10]
    for i, c in enumerate(cj["clips"]):
        c["id"] = f"clip_{i + 1}_remix"
        c["name"] = f"角色替换段{i + 1}"
        c["render_enabled"] = True
        c["validated"] = False
        # 第 2 段起续接（段头 22 帧 = 上一段段尾）；后端建计划时会再强制一次
        c["context_enabled"] = bool(i > 0)
    wv[10] = json.dumps(cj, ensure_ascii=False, separators=(",", ":"))

    # LoRA 槽：2057 槽统一换成 8 步 Ref2VA 加速 LoRA；其余 swap/角色替换 LoRA 一律静音
    for node in d["nodes"]:
        if node.get("type") != "LoraLoaderModelOnly":
            continue
        lname = str((node.get("widgets_values") or [""])[0])
        if node.get("id") == 2057:
            node["widgets_values"] = [ACCEL_LORA, 1.0]
            node["title"] = "8步 Ref2VA 加速LoRA（本档不用 swap LoRA）"
            node["mode"] = 0
            name_map = node.get("widgets_values_named")
            if isinstance(name_map, dict):
                name_map["lora_name"] = ACCEL_LORA
                name_map["strength_model"] = 1.0
        elif "character_swap" in lname or "角色替换" in lname:
            node["mode"] = 4          # swap 槽静音（本档禁止）

    n["title"] = NODE_TITLE

    if note_text:
        for node in d["nodes"]:
            if node.get("type") == "Note":
                s = (node.get("widgets_values") or [""])[0]
                if "视频人物替换（V2V Recast" in s or "Video Remix" in s:
                    node["widgets_values"][0] = note_text
    return n, wv, cj


def build():
    with open(SRC, encoding="utf-8") as f:
        d = json.load(f)
    n, wv, cj = _apply(d)

    with open(DST, "w", encoding="utf-8", newline="\n") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print(f"[OK] 已写出: {os.path.basename(DST)}")
    print(f"     render_pipeline = {wv[IDX['render_pipeline']]}")
    print(f"     steps={wv[IDX['steps']]} denoise={wv[IDX['denoise']]} "
          f"refine={wv[IDX['refine_steps']]}x{wv[IDX['refine_upscale_factor']]} "
          f"ctx={wv[IDX['context_length']]}")
    print(f"     clips={len(cj['clips'])} (后端按 226/22 自动补齐)")
    print(f"     LoRA = {ACCEL_LORA}")


def sync_user():
    """把同样的 remix 契约打到用户那份实战工作流(BSAI第077期)上。"""
    if not os.path.exists(USER_DST):
        print(f"[SKIP] 用户工作流不存在: {USER_DST}")
        return 1
    raw = open(USER_DST, encoding="utf-8").read()
    d = json.loads(raw)
    n, wv, cj = _apply(d, note_text=USER_NOTE)
    bak = USER_DST + ".bak"
    if not os.path.exists(bak):
        with open(bak, "w", encoding="utf-8", newline="\n") as f:
            f.write(raw)
    with open(USER_DST, "w", encoding="utf-8", newline="\n") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print(f"[OK] 已同步用户工作流: {os.path.basename(USER_DST)}")
    print(f"     steps={wv[IDX['steps']]} denoise={wv[IDX['denoise']]} "
          f"refine={wv[IDX['refine_steps']]}x{wv[IDX['refine_upscale_factor']]}"
          f"@{wv[IDX['refine_denoise']]} ctx={wv[IDX['context_length']]}")
    return 0


def check():
    with open(DST, encoding="utf-8") as f:
        d = json.load(f)
    n = [x for x in d["nodes"] if x.get("type") == "BSAIH3FilmFactory"][0]
    wv = n["widgets_values"]
    ok = True
    for k, v in PATCH.items():
        if wv[IDX[k]] != v:
            ok = False
            print(f"[FAIL] {k}: {wv[IDX[k]]!r} != {v!r}")
    if len(wv) != 71:
        ok = False
        print(f"[FAIL] widgets_values 长度 {len(wv)} != 71")
    cj = json.loads(wv[10])
    if not all(c["id"].endswith("_remix") for c in cj["clips"]):
        ok = False
        print("[FAIL] 分镜 id 未改为 *_remix")
    lora = [x for x in d["nodes"] if x.get("id") == 2057]
    if not lora or "character_swap" in str(lora[0]["widgets_values"]):
        ok = False
        print("[FAIL] LoRA 槽仍挂着 swap LoRA")
    print("=== REMIX WORKFLOW", "OK" if ok else "FAIL", "===")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(check())
    if "--sync-user" in sys.argv:
        sys.exit(sync_user())
    build()
