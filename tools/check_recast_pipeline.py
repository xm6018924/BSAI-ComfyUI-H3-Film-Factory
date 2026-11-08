# -*- coding: utf-8 -*-
r"""视频人物替换 (Video Recast / tier 33) 核心函数冒烟测试。

为什么要这个工具
----------------
v14.335 新增的第 33 档「视频替换 (V2V 人物替换)」不生成画面，而是把资产库
`@视频N` 的源画面与源原声编码进 H3 的 AV latent 做半重绘。整条链路里最容
易坏、又最难靠"看日志"发现的三件事都在这里：

  1) 时长探测 —— 探测失败就无法按 15s 切段（45s 源视频切 3 段全靠它）；
  2) 切段与帧网格 —— 每段帧数必须落在 H3 的 17k+5 网格上，否则 latent 时间
     轴与 AV latent 行数错位，出片会闪/卡/音画不同步；
  3) ffmpeg 抽帧/抽音 —— 帧数必须严格等于请求值（多段拼接时靠这个对齐），
     音频行数必须 = round(dur*40)，否则 noise_mask 锁定的音频区长度不对。

本工具不启动 ComfyUI、不加载 H3 权重，只 import 插件模块（stub
`server.PromptServer`，与 check_quickbar_enum_sync.py 同一套引导），然后用
ffmpeg 现合成带音轨的测试视频，逐项断言。合成视频跑完即删。

用法
----
    python tools\check_recast_pipeline.py
退出码: 0 = 全通过; 1 = 有用例失败（逐条打印实际值）。
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
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
    PKG = "bsai_h3_ff_recast_probe"
    pkg = types.ModuleType(PKG)
    pkg.__path__ = [PLUGIN]
    sys.modules[PKG] = pkg
    spec = importlib.util.spec_from_file_location(PKG + ".extender", EXT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def make_video(ff, path, seconds, size="640x360", audio=True):
    """ffmpeg 合成测试视频：testsrc2 画面 +（可选）440Hz 正弦音轨。"""
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
    work = tempfile.mkdtemp(prefix="h3recast_")
    ok = True
    fails = []

    def check(name, cond, detail=""):
        nonlocal ok
        print(f"[{ 'PASS' if cond else 'FAIL' }] {name}" + (f"  -> {detail}" if detail else ""))
        if not cond:
            ok = False
            fails.append(name)

    try:
        src20 = os.path.join(work, "src20.mp4")
        r = make_video(ff, src20, 20)
        check("合成 20s 测试视频", r.returncode == 0, (r.stderr or b"")[:200])
        if r.returncode != 0:
            return 1

        # 1) 时长探测
        d = m._recast_probe_duration(src20, ff)
        check("时长探测 20s", bool(d and 19.0 <= d <= 21.0), f"duration={d}")

        # 2) 提示词纪律：纪律块注入 + <Video N> 摘掉 + <Picture N> 保留
        p = m._recast_prompt("把 <Video 1> 里的主持人换成 <Picture 1> 的女孩")
        check("纪律块注入", "【视频人物替换纪律】" in p)
        check("<Video N> 已摘除", "<Video 1>" not in p and "原视频" in p)
        check("<Picture N> 保留", "<Picture 1>" in p)

        # 3) 20s → 2 段，自动补 1 个 CLIP，时间轴首尾相接
        clips = [{"id": "clip1", "prompt": "把 <Video 1> 里的主持人换成 <Picture 1> 的女孩",
                  "duration": 10.0, "context_enabled": True, "render_enabled": True,
                  "validated": True}]
        lib = {"videos": [{"index": 1, "path": src20, "name": "src"}],
               "images": [], "audios": []}
        plan = m._recast_build_plan(clips, lib, ffmpeg=ff)
        check("20s 切 2 段", plan is not None and len(plan["segments"]) == 2,
              str(plan["segments"] if plan else None))
        check("自动补齐 1 个 CLIP", plan is not None and plan["auto_added"] == 1
              and len(clips) == 2)
        check("段间 Context 全关",
              all(c["context_enabled"] is False for c in clips))
        check("补齐段待重渲染", clips[-1]["validated"] is False)
        if plan:
            seg0, seg1 = plan["segments"][0], plan["segments"][1]
            check("时间轴首尾相接",
                  abs(seg0[0]) < 1e-6 and abs(seg1[0] - seg0[1]) < 1e-6,
                  f"seg0={seg0} seg1={seg1}")
            # 抽帧：帧数严格等于请求值、画布 = 请求值、值域 [0,1]
            fc = m._duration_to_frames(seg0[1])
            framed = m._recast_read_segment_frames(
                src20, seg0[0], seg0[1], 512, 288, fc, ffmpeg=ff)
            check("抽帧帧数严格一致",
                  framed is not None and int(framed.shape[0]) == int(fc),
                  str(tuple(framed.shape) if framed is not None else None))
            check("抽帧画布 = 请求 W×H",
                  framed is not None and int(framed.shape[1]) == 288
                  and int(framed.shape[2]) == 512)
            check("抽帧值域 [0,1]",
                  framed is not None and float(framed.min()) >= 0.0
                  and float(framed.max()) <= 1.0)
            # 抽音：行数 = round(dur*40)
            sr = 32000
            ta = int(round(seg0[1] * m.AUDIO_LATENT_FPS))
            wav = m._recast_read_segment_audio(src20, seg0[0], seg0[1], sr, ta, ffmpeg=ff)
            check("抽音行数 = round(dur*40)",
                  wav is not None and int(wav.shape[-1]) == ta and int(wav.shape[1]) == 2,
                  str(tuple(wav.shape) if wav is not None else None))

        # 4) 45s（用户口径的例子）→ 3 段
        src45 = os.path.join(work, "src45.mp4")
        r2 = make_video(ff, src45, 45, size="320x180", audio=False)
        check("合成 45s 测试视频", r2.returncode == 0)
        d45 = m._recast_probe_duration(src45, ff)
        clips45 = [{"id": "c1", "prompt": "@图1 替换 <Video 1> 里的人", "duration": 10.0,
                    "context_enabled": False, "render_enabled": True, "validated": True}]
        plan45 = m._recast_build_plan(clips45,
                                      {"videos": [{"index": 1, "path": src45}],
                                       "images": [], "audios": []},
                                      ffmpeg=ff)
        check("45s 探测时长", bool(d45 and 44.0 <= d45 <= 46.0), f"duration={d45}")
        check("45s 切 3 段（用户口径 3×15s）",
              plan45 is not None and len(plan45["segments"]) == 3,
              str(plan45["segments"] if plan45 else None))
        check("45s 自动补 2 个 CLIP",
              plan45 is not None and plan45["auto_added"] == 2 and len(clips45) == 3)
        if plan45:
            _durs = [s[1] for s in plan45["segments"].values()]
            check("每段时长 ≈15s（17k+5 网格）",
                  all(14.0 <= x <= 15.5 for x in _durs), str(_durs))
            check("每段帧数落在 17k+5 网格",
                  all(int(round(x * 24)) % 17 == 5 or
                      (int(round(x * 24)) + 1) % 17 == 5 for x in _durs),
                  str([int(round(x * 24)) for x in _durs]))

        # 5) 无音轨 → 抽音返回 None（音频改由模型重生成）
        wav2 = m._recast_read_segment_audio(src45, 0.0, 2.0, 32000, 80, ffmpeg=ff)
        check("无音轨源 -> 抽音 None", wav2 is None, str(wav2))

        # 6) 提示词里没有 <Video N> -> 不是替换任务，返回 None
        check("无 @视频N 时不触发替换",
              m._recast_build_plan([{"id": "c", "prompt": "普通分镜", "duration": 5.0}],
                                   {"videos": [], "images": [], "audios": []},
                                   ffmpeg=ff) is None)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print("\n=== RECAST PIPELINE CHECK", "OK" if ok else "FAIL", "===")
    if fails:
        print("失败用例:", ", ".join(fails))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
