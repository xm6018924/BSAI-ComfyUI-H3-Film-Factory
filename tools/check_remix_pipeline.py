# -*- coding: utf-8 -*-
r"""视频角色替换+动作迁移 (Video Remix / tier 35) 冒烟测试。

为什么要这个工具
----------------
v14.341 新增的第 35 档「视频角色替换+动作迁移」来自教程 BV1HBWJ6HEkg，和
第 33 档「视频替换 (V2V 人物替换)」共用同一条"源视频灌进 AV latent"的注入
链路，但分段契约完全不同 —— 这里最容易静默错、又最难靠看日志发现的是：

  1) 分段数学 —— 每段 226 帧（5+17k），段间重叠 22 帧，第 k 段源时间轴起点
     必须是 204*k/24s；算错就会在接缝处动作跳帧、成片时长偏离源片；
  2) 段间续接 —— remix 档第 2 段起必须开 motion context（22 帧重叠锁定），
     第 1 段必须关（它没有上一段），与第 33 档"全关"正好相反；
  3) 全画幅可重绘 —— 动作迁移要能换背景，所以注入时 subject_mask 必须关掉
     （退回全 1 掩码），否则背景被锁成源像素，动作迁移永远出不来；
  4) 无 LoRA 契约 —— 本档不得要求任何 swap/角色替换 LoRA；
  5) ffmpeg 抽帧/抽音 —— 226 帧请求必须严格返回 226 帧，音频行数 = round(dur*40)。

不启动 ComfyUI、不加载 H3 权重；import 插件模块（stub PromptServer），用 ffmpeg
现合成带音轨的测试视频，逐项断言，跑完即删。

用法
----
    python tools\check_remix_pipeline.py
退出码: 0 = 全通过; 1 = 有用例失败（逐条打印实际值）。
"""
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, ".."))
COMFY = os.path.abspath(os.path.join(PLUGIN, "..", ".."))
EXT = os.path.join(PLUGIN, "extender.py")
JS = os.path.join(PLUGIN, "web", "extender.js")
TIER_EN = "Video Remix (no-LoRA character swap + motion transfer)"
TIER_ZH = "视频角色替换+动作迁移"


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
    PKG = "bsai_h3_ff_remix_probe"
    pkg = types.ModuleType(PKG)
    pkg.__path__ = [PLUGIN]
    sys.modules[PKG] = pkg
    spec = importlib.util.spec_from_file_location(PKG + ".extender", EXT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def make_video(ff, path, seconds, size="640x360", audio=True):
    cmd = [str(ff), "-v", "error", "-y",
           "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=24:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i",
                f"sine=frequency=440:sample_rate=48000:duration={seconds}"]
        cmd += ["-c:a", "aac", "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", path]
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def main():
    m = load_mod()
    ff = m._find_ffmpeg()
    print("ffmpeg =", ff)
    work = tempfile.mkdtemp(prefix="h3remix_")
    ok = True
    fails = []

    def check(name, cond, detail=""):
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))
        if not cond:
            ok = False
            fails.append(name)

    try:
        # 0) 档位注册：后端枚举 / 中英映射 / 前端三表
        src = open(EXT, encoding="utf-8").read()
        js = open(JS, encoding="utf-8").read()
        check("后端枚举含第 35 档", f'"{TIER_EN}"' in src)
        check("中英映射有该档", f'"{TIER_EN}": "{TIER_ZH}"' in src)
        branch = src.split(f'_rp_mode == "{TIER_ZH}"')
        check("后端有该档分支", len(branch) >= 2)
        body = branch[1].split("else:")[0] if len(branch) >= 2 else ""
        check("一采默认 8 步(v14.344；教程原口径 4 步)",
              re.search(r'_rm_steps_user = int\(kwargs\.get\("steps", 8\)', body) is not None
              and re.search(r"steps = max\(4, min\(16, _rm_steps_user\)\)", body) is not None)
        check("二采 5 步", re.search(r"^\s+refine_steps = 5\s*$", body, re.M) is not None)
        check("二采 denoise 0.30（v14.347 真实 σ 起点）",
              re.search(r"^\s+refine_denoise = 0\.30\s*$", body, re.M) is not None)
        check("本档打开 exact sigma 映射", "_SIGMAS_EXACT = True" in body)
        check("exact sigma 函数存在", "def _sigmas_exact(" in src)
        check("二采沿用人物掩码（背景不被二采洗掉）",
              "二采沿用人物掩码" in src)
        check("二采禁止空间分块（v14.348 块状马赛克根因）",
              'refine_mem_mode = "global (全上下文省显存)"' in body)
        check("二采分块兜底开关存在", "BSAI_H3_REMIX_REFINE_MEM" in body)
        check("refine_mem_mode 传参不被旧 flag 打回 spatial",
              'str(refine_mem_mode).startswith("global")' in src)
        check("二采掩码缩放按帧 4D 做(不用 5D size 顺序)",
              "_pcv.reshape(_t_l, 1, _h_l, _w_l)" in src)
        check("二采放大 1.5x",
              re.search(r"^\s+refine_upscale_factor = 1\.5\s*$", body, re.M) is not None)
        check("段间续接 22 帧", 'context_length = "22"' in body)
        check("分支不提 swap LoRA", "character_swap" not in body)
        check("前端 cycle 含该档", f'"{TIER_EN}"' in js)
        check("前端别名含该档", f'"{TIER_ZH}": "{TIER_EN}"' in js)
        check("注入时按模式决定人物掩码",
              "_remix_keep_background(" in src
              and "_clip_prompt_for_cond) if _remix_this" in src)
        # v14.345 实跑事故: `clip` 在那个作用域是节点输入的 CLIP 编码器，
        # 当成分镜字典取 prompt 会 AttributeError 炸段（不退回普通渲染=整次任务终止）。
        _norm = re.sub(r"\s+", "", src)
        check("掩码判定不误用 CLIP 对象",
              "_remix_keep_background(_clip_prompt_for_cond)" in _norm
              and "_remix_keep_background(str(clip.get" not in _norm)
        check("帧数锁定 226", "frame_count = _remix_frames" in src)

        # 1) 提示词纪律
        p = m._remix_prompt("@图1 把 <Video 1> 里的主持人换成参考图的女孩")
        check("纪律块注入", "【视频角色替换+动作迁移纪律】" in p)
        check("<Video N> 已摘除", "<Video 1>" not in p and "原视频" in p)
        check("<Picture N> 保留", "@图1" in p)
        check("纪律块声明背景只写一种", "背景只写一种" in p)
        check("纪律块声明不出现参考图本身", "不得出现参考图本身" in p)

        # 2) 锁原声开关
        check("默认锁源原声", m._remix_lock_audio() is True)
        os.environ["BSAI_H3_REMIX_LOCK_AUDIO"] = "0"
        check("=0 时不锁(模型重生成)", m._remix_lock_audio() is False)
        os.environ.pop("BSAI_H3_REMIX_LOCK_AUDIO", None)

        # 2b) v14.342: 背景锁定（人物替换）vs 全画幅（动作迁移）
        #     实跑事故: 全画幅 + denoise 0.65 从 σ≈0.96 起跑，背景被整帧重画。
        check("默认保源背景(人物掩码)",
              m._remix_keep_background("把 @视频1 前景的女生替换成 @图1，背景/机位/光线不变") is True)
        check("写新场景 -> 全画幅(动作迁移)",
              m._remix_keep_background("把 @视频1 的人物换成 @图1，背景换成雨夜街头") is False)
        check("换新场景 -> 全画幅",
              m._remix_keep_background("人物不变，换到另一个场景：室内咖啡馆") is False)
        os.environ["BSAI_H3_REMIX_KEEP_BG"] = "1"
        check("环境变量=1 强制保背景",
              m._remix_keep_background("背景换成雨夜街头") is True)
        os.environ["BSAI_H3_REMIX_KEEP_BG"] = "0"
        check("环境变量=0 强制全画幅",
              m._remix_keep_background("背景不变") is False)
        os.environ.pop("BSAI_H3_REMIX_KEEP_BG", None)
        # v14.343: 纪律块正文带"全新场景"，绝不能让它把判定带偏（实跑事故）
        check("纪律块不能误触发全画幅",
              m._remix_keep_background(m._REMIX_DISCIPLINE + "\n把 @视频1 前景的女生替换成 @图1 里的角色") is True)
        check("纪律块+新场景正文 -> 全画幅",
              m._remix_keep_background(m._REMIX_DISCIPLINE + "\n把 @视频1 人物换成 @图1，背景换成雨夜街头") is False)
        check("正文抽取剥掉纪律块",
              "全新场景" not in m._remix_user_text(m._REMIX_DISCIPLINE + "\n只换人"))

        # 3) 20s 源视频 → 226/204/22 分段
        src20 = os.path.join(work, "src20.mp4")
        r = make_video(ff, src20, 20)
        check("合成 20s 测试视频", r.returncode == 0, (r.stderr or b"")[:200])
        if r.returncode != 0:
            return 1

        clips = [{"id": "clip1", "prompt": "@图1 把 <Video 1> 里的主持人换成参考图的女孩",
                  "duration": 9.42, "context_enabled": False, "render_enabled": True,
                  "validated": True}]
        lib = {"videos": [{"index": 1, "path": src20}], "images": [], "audios": []}
        plan = m._remix_build_plan(clips, lib, ffmpeg=ff)
        check("计划已建立", plan is not None and plan.get("pipeline") == "remix")
        if plan is None:
            return 1
        check("每段 226 帧", int(plan["seg_frames"]) == 226, str(plan["seg_frames"]))
        check("段间重叠 22 帧", int(plan["overlap_frames"]) == 22)
        check("226 落在 5+17k 网格", (226 - 5) % 17 == 0)
        net_frames = 226 - 22
        net_sec = net_frames / float(m.FPS)
        check("净推进 204 帧/段", net_frames == 204, str(net_frames))

        dur_frames = int(round(plan["duration"] * m.FPS))
        want_n = 1 + max(0, -(-(dur_frames - 226) // net_frames))
        check("段数 = 1 + ceil((源帧-226)/204)", len(plan["segments"]) == want_n,
              f"{len(plan['segments'])} 段（源 {dur_frames} 帧）")
        segs = [plan["segments"][k] for k in sorted(plan["segments"])]
        check("第 1 段从 0 起", abs(segs[0][0]) < 1e-6, str(segs[0]))
        check("第 k 段起点 = 204*k/24s",
              all(abs(segs[k][0] - k * net_sec) < 1e-6 for k in range(len(segs))),
              str([round(s[0], 3) for s in segs]))
        check("非尾段源窗口 = 226 帧",
              all(abs(s[1] * m.FPS - 226) < 0.02 for s in segs[:-1]),
              str([round(s[1] * m.FPS) for s in segs]))
        tail_frames = int(round(segs[-1][1] * m.FPS))
        check("尾段按剩余帧数收窄（不靠冻帧补满 226）", tail_frames <= 226,
              f"尾段 {tail_frames} 帧")
        check("尾段落在 5+17k 网格", (tail_frames - 5) % 17 == 0, str(tail_frames))
        check("尾段覆盖到源片末尾",
              (segs[-1][0] + segs[-1][1]) * m.FPS >= plan["duration"] * m.FPS - 1,
              f"窗口末 {(segs[-1][0] + segs[-1][1]) * m.FPS:.0f} / 源 "
              f"{plan['duration'] * m.FPS:.0f} 帧")
        check("相邻段重合 22 帧",
              all(abs((segs[k + 1][0] + 22.0 / m.FPS) - (segs[k][0] + segs[k][1])) < 1e-6
                  for k in range(len(segs) - 1)))
        check("第 1 段关续接 / 第 2 段起开续接",
              [c["context_enabled"] for c in clips] == [False] + [True] * (len(clips) - 1),
              str([c["context_enabled"] for c in clips]))
        net_out = [int(v) - (0 if k == 0 else 22)
                   for k, v in sorted(plan["frames_by_clip"].items())]
        check("净输出帧数 = 渲染帧 - 段头重叠",
              abs(sum(net_out) * 1.0 - plan["duration"] * m.FPS) <= 17.0,
              f"净 {sum(net_out)} 帧 / 源 {plan['duration'] * m.FPS:.0f} 帧")
        check("第 1 段时长 = 226 帧 / 后续 = 净输出帧",
              abs(clips[0]["duration"] * m.FPS - 226) < 0.02
              and all(abs(c["duration"] * m.FPS - n) < 0.02 for c, n in zip(clips[1:], net_out[1:])),
              str([round(c["duration"], 3) for c in clips]))
        check("自动补齐的段待重渲染",
              plan["auto_added"] > 0 and clips[-1]["validated"] is False,
              f"auto_added={plan['auto_added']}")

        # 4) ffmpeg 抽帧/抽音：帧数严格一致（首段 226 / 尾段取 frames_by_clip），
        #    音频行 = round(dur*40)
        fc = 226
        framed = m._recast_read_segment_frames(src20, segs[0][0], segs[0][1],
                                              512, 288, fc, ffmpeg=ff)
        check("首段抽帧帧数 = 226", framed is not None and int(framed.shape[0]) == fc,
              str(tuple(framed.shape) if framed is not None else None))
        last_fc = plan["frames_by_clip"][max(plan["frames_by_clip"])]
        framed2 = m._recast_read_segment_frames(src20, segs[-1][0], segs[-1][1],
                                               512, 288, last_fc, ffmpeg=ff)
        check("尾段抽帧帧数 = frames_by_clip（源片够用，不冻帧）",
              framed2 is not None and int(framed2.shape[0]) == last_fc,
              f"{tuple(framed2.shape) if framed2 is not None else None} 期望 {last_fc}")
        check("抽帧画布 = 请求 W×H",
              framed is not None and int(framed.shape[1]) == 288
              and int(framed.shape[2]) == 512)
        ta = int(round((fc / float(m.FPS)) * m.AUDIO_LATENT_FPS))
        wav = m._recast_read_segment_audio(src20, segs[0][0], segs[0][1], 32000, ta,
                                          ffmpeg=ff)
        check("抽音行数 = round(226/24*40)",
              wav is not None and int(wav.shape[-1]) == ta and int(wav.shape[1]) == 2,
              f"{tuple(wav.shape) if wav is not None else None} 期望 {ta}")

        # 5) 45s 长视频 → 自动续段且覆盖到源片末尾
        src45 = os.path.join(work, "src45.mp4")
        r2 = make_video(ff, src45, 45, size="320x180", audio=False)
        check("合成 45s 测试视频", r2.returncode == 0)
        clips45 = [{"id": "c1", "prompt": "@图1 替换 <Video 1> 里的人", "duration": 9.42,
                    "context_enabled": False, "render_enabled": True, "validated": True}]
        plan45 = m._remix_build_plan(
            clips45, {"videos": [{"index": 1, "path": src45}], "images": [], "audios": []},
            ffmpeg=ff)
        check("45s 生成多段", plan45 is not None and len(plan45["segments"]) >= 5,
              str(len(plan45["segments"]) if plan45 else None))
        if plan45:
            segs45 = [plan45["segments"][k] for k in sorted(plan45["segments"])]
            last = segs45[-1]
            cover = (last[0] + last[1]) * m.FPS
            check("覆盖到源片末尾(不留断尾)", cover >= plan45["duration"] * m.FPS - 1,
                  f"覆盖 {cover:.0f} 帧 / 源 {plan45['duration'] * m.FPS:.0f} 帧")
            check("段数受 _REMIX_MAX_CLIPS 约束",
                  len(segs45) <= m._REMIX_MAX_CLIPS)

        # 6) 没有 @视频N → 不触发
        check("无 @视频N 时不触发",
              m._remix_build_plan([{"id": "c", "prompt": "普通分镜", "duration": 5.0}],
                                  {"videos": [], "images": [], "audios": []},
                                  ffmpeg=ff) is None)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print("\n=== REMIX PIPELINE CHECK", "OK" if ok else "FAIL", "===")
    if fails:
        print("失败用例:", ", ".join(fails))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
