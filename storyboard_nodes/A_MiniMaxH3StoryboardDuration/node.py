# -*- coding: utf-8 -*-
"""Read one clip duration from an outer promptN block."""
import re

FPS = 24
MAX_CLIPS = 512
MAX_CLIP_DURATION_SECONDS = 15.0
DEFAULT_SEGMENT_MARKER = "===== promptN ====="

DURATION_RE = re.compile(
    r"(?<![\w.:])(\d+(?:\.\d+)?)\s*-?\s*"
    r"(hours?|hrs?|hr|h|minutes?|mins?|min|seconds?|secs?|sec|s|小时|分钟|秒)"
    r"(?![A-Za-z])",
    re.IGNORECASE,
)
DURATION_UNIT_SECONDS = {
    "h": 3600.0, "hr": 3600.0, "hrs": 3600.0, "hour": 3600.0, "hours": 3600.0,
    "min": 60.0, "mins": 60.0, "minute": 60.0, "minutes": 60.0,
    "s": 1.0, "sec": 1.0, "secs": 1.0, "second": 1.0, "seconds": 1.0,
    "秒": 1.0, "分钟": 60.0, "小时": 3600.0,
}
SECTION_BODY_RE = re.compile(r"(?ims)^([a-z_]+):[ \t]*(.*?)(?=^[a-z_]+:[ \t]*|\Z)")
OUTPUT_CONTEXT_RE = re.compile(
    r"\b(?:clip|video|segment|generation|output|duration|length|runtime|dance|performance)\b"
    r"|(?:视频|片段|时长|长度|舞蹈|表演)", re.IGNORECASE,
)
AUDIO_BEFORE_RE = re.compile(
    r"(?:<Audio\s+\d+>|\b(?:audio|song|track|soundtrack|music)\b)[^.!?\n]{0,24}$",
    re.IGNORECASE,
)
AUDIO_AFTER_RE = re.compile(
    r"^[ \t,;:-]*(?:(?:of|for|from)[ \t]+)?(?:audio|song|track|soundtrack|music)\b",
    re.IGNORECASE,
)


def _flexible_marker_literal(value):
    pieces = re.split(r"([ \t]+)", value)
    return "".join(r"[ \t]*" if piece and piece.isspace() else re.escape(piece) for piece in pieces)


def _marker_pattern(marker_template):
    template = str(marker_template or DEFAULT_SEGMENT_MARKER).strip() or DEFAULT_SEGMENT_MARKER
    placeholder = re.search(r"\{N\}|(prompt|clip)N|\bN\b", template, re.IGNORECASE)
    if placeholder:
        pattern = (
            _flexible_marker_literal(template[:placeholder.start()])
            + _flexible_marker_literal(placeholder.group(1) or "")
            + r"[ \t_\-]*"
            + r"(\d+)"
            + _flexible_marker_literal(template[placeholder.end():])
        )
        return re.compile(pattern, re.IGNORECASE), True
    return re.compile(_flexible_marker_literal(template), re.IGNORECASE), False


def _convert_legacy_storyboard_format(text):
    """Convert legacy [分镜N] format to ===== prompt_N ===== markers."""
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not re.search(r"\[分镜\s*\d+\]", raw, re.IGNORECASE):
        return raw

    sb_match = re.search(r"\[分镜\s*\d+\]", raw, re.IGNORECASE)
    opening = raw[:sb_match.start()]
    storyboard = raw[sb_match.start():]

    blocks = list(re.finditer(r"\[分镜\s*\d+\]", storyboard, re.IGNORECASE))
    segments = []
    for i, match in enumerate(blocks):
        start = match.start()
        end = blocks[i + 1].start() if i + 1 < len(blocks) else len(storyboard)
        block = storyboard[start:end].strip()
        seg = f"[Recommended duration]: 12 seconds\n{opening}\n\n{block}"
        segments.append(f"===== prompt_{i + 1} =====\n{seg}")

    return "\n\n".join(segments)


def _split_prompt_segments(text, segment_marker=DEFAULT_SEGMENT_MARKER):
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    raw = _convert_legacy_storyboard_format(raw)
    marker_re, has_number = _marker_pattern(segment_marker)
    headers = list(marker_re.finditer(raw))
    if not headers:
        prompt = raw.strip()
        if not prompt:
            raise ValueError("官方参考生提示词为空。")
        return [{"label": 1, "marker": "", "prompt": prompt}]
    if len(headers) > MAX_CLIPS:
        raise ValueError(f"prompt 段数超过上限 {MAX_CLIPS}。")
    segments = []
    for position, header in enumerate(headers):
        end = headers[position + 1].start() if position + 1 < len(headers) else len(raw)
        prompt = raw[header.end():end].strip()
        label = int(header.group(1)) if has_number else position + 1
        if label < 1:
            raise ValueError("分区标记中的序号必须从 1 开始。")
        if not prompt:
            raise ValueError(f"分区标记 {header.group(0)!r} 后没有提示词内容。")
        segments.append({"label": label, "marker": header.group(0), "prompt": prompt})
    return segments


def _duration_matches(text):
    raw = str(text or "")
    values = []
    for match in DURATION_RE.finditer(raw):
        start, end = match.span()
        before = raw[max(0, start - 40):start]
        after = raw[end:end + 32]
        output_before = bool(OUTPUT_CONTEXT_RE.search(before[-32:]))
        output_after = bool(re.match(
            r"^[ \t-]*(?:clip|video|segment|dance|performance)\b|^[ \t-]*(?:视频|片段|舞蹈|表演)",
            after,
            re.IGNORECASE,
        ))
        audio_context = bool(AUDIO_BEFORE_RE.search(before) or AUDIO_AFTER_RE.match(after))
        if (audio_context and not output_after) or not (output_before or output_after):
            continue
        value, unit = match.groups()
        values.append(float(value) * DURATION_UNIT_SECONDS[unit.casefold()])
    return values


def _max_duration_seconds(text):
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    summary = next(
        (match.group(2) for match in SECTION_BODY_RE.finditer(raw) if match.group(1).casefold() == "summary"),
        "",
    )
    durations = _duration_matches(summary)
    if not durations:
        durations = _duration_matches(raw)
    return max(durations) if durations else None


class A_MiniMaxH3StoryboardDuration:
    CATEGORY = "A-BSAI/H3"
    FUNCTION = "parse_duration"
    OUTPUT_NODE = False
    RETURN_TYPES = ("FLOAT", "FLOAT")
    RETURN_NAMES = ("clip_duration_sec", "start_time_sec")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt_source": (
                    "STRING",
                    {
                        "forceInput": True,
                        "multiline": True,
                        "tooltip": "按分段标记模板切分；默认 ===== promptN =====。",
                    },
                ),
                "length": (
                    "INT",
                    {
                        "default": 124,
                        "min": 5,
                        "max": 3600,
                        "step": 17,
                        "tooltip": "所选段未写明时长时使用的兜底帧数。",
                    },
                ),
                "clip_index": (
                    "INT",
                    {
                        "default": 1,
                        "min": 1,
                        "max": MAX_CLIPS,
                        "step": 1,
                        "tooltip": "按分段标记出现顺序选择；标记编号重复时也按顺序计数。",
                    },
                ),
                "video_duration_sec": (
                    "FLOAT",
                    {
                        "default": 0.0,
                        "min": 0.0,
                        "max": 86400.0,
                        "step": 0.1,
                        "tooltip": "仅在只有一个 prompt 段且段内没有显式时长时作为兜底。",
                    },
                ),
            },
            "optional": {
                "segment_marker": (
                    "STRING",
                    {
                        "forceInput": True,
                        "default": DEFAULT_SEGMENT_MARKER,
                        "tooltip": "可连接字符串节点自定义分段标记；模板中的 N 表示序号，不含 N 时按出现顺序编号。",
                    },
                ),
            },
        }

    def parse_duration(self, prompt_source, length, clip_index, video_duration_sec=0.0, segment_marker=DEFAULT_SEGMENT_MARKER):
        segments = _split_prompt_segments(prompt_source, segment_marker)
        index = int(clip_index)
        if index < 1 or index > len(segments):
            raise ValueError(
                f"clip_index={index} 超出范围：提示词共 {len(segments)} 个 prompt 段，请填 1~{len(segments)}。"
            )

        # 先解析每一段的时长，用于计算前面所有段的累计起始时间
        all_durations = []
        for seg in segments:
            d = _max_duration_seconds(seg["prompt"])
            if d is None:
                if len(segments) == 1 and float(video_duration_sec or 0.0) > 0:
                    d = float(video_duration_sec)
                else:
                    d = max(5.0 / FPS, int(length) / FPS)
            if d > MAX_CLIP_DURATION_SECONDS:
                raise ValueError(
                    f"识别到的 CLIP 时长 {d:.3f} 秒超过 MiniMax H3 单段 15 秒上限；请拆分提示词或缩短时长。"
                )
            all_durations.append(float(d))

        duration_sec = all_durations[index - 1]
        start_time_sec = float(sum(all_durations[:index - 1]))
        return (duration_sec, start_time_sec)

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")


class A_MiniMaxH3SegmentCount:
    """统计提示词里实际有几个 prompt 段，供片段序号做 1~N 自动回绕。

    与 A_MiniMaxH3StoryboardDuration / A_MiniMaxH3StoryboardRefVideo 使用同一套分段规则，
    保证回绕上界 = 真实段数，换 13 段、20 段提示词都不用改工作流。
    """

    CATEGORY = "A-BSAI/H3"
    FUNCTION = "count_segments"
    OUTPUT_NODE = False
    RETURN_TYPES = ("INT",)
    RETURN_NAMES = ("segment_count",)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt_source": (
                    "STRING",
                    {
                        "forceInput": True,
                        "multiline": True,
                        "tooltip": "整段官方提示词；段数即分段标记出现次数。",
                    },
                ),
            },
            "optional": {
                "segment_marker": (
                    "STRING",
                    {
                        "forceInput": True,
                        "default": DEFAULT_SEGMENT_MARKER,
                        "tooltip": "与时长解析节点保持一致，不接则用默认标记。",
                    },
                ),
            },
        }

    def count_segments(self, prompt_source, segment_marker=DEFAULT_SEGMENT_MARKER):
        segments = _split_prompt_segments(prompt_source, segment_marker or DEFAULT_SEGMENT_MARKER)
        return (len(segments),)

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")


class _AnyType(str):
    """通配类型：optional 输入可以接 IMAGE / LATENT / 任意东西。"""

    def __ne__(self, other):
        return False


ANY_TYPE = _AnyType("*")


class A_MiniMaxH3AutoChainAll:
    """一次运行、运行次数填 1，也能把全部分镜跑完。

    做法：本段执行完（或 at least 走到末端节点）后，把这个 prompt 原样复制一份，
    只把 SeedNode 的 seed 改成「上一段 + 1」，再通过 PromptServer 的队列塞回去。
    因为 seed 同时驱动片段序号，所以下一段就是下一镜；走到最后一段就停，不会无限循环。
    """

    CATEGORY = "A-BSAI/H3"
    FUNCTION = "chain_next"
    OUTPUT_NODE = True
    RETURN_TYPES = ("INT",)
    RETURN_NAMES = ("next_seed",)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "seed": (
                    "INT",
                    {
                        "forceInput": True,
                        "min": -9223372036854775807,
                        "max": 9223372036854775807,
                        "tooltip": "接 SeedNode 的 seed；它同时是片段序号的来源。",
                    },
                ),
                "segment_count": (
                    "INT",
                    {
                        "forceInput": True,
                        "min": 0,
                        "max": MAX_CLIPS,
                        "tooltip": "接「分镜段数统计」节点，决定排到第几段为止。",
                    },
                ),
                "enable": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "label_on": "自动续排 开",
                        "label_off": "自动续排 关",
                        "tooltip": "关掉后就是普通的单段渲染，不会再自动排下一段。",
                    },
                ),
            },
            "optional": {
                "after": (
                    ANY_TYPE,
                    {
                        "forceInput": True,
                        "tooltip": "接一个末端输出（比如 4K 索引切换），让本段真的跑完再排下一段；不接就是提交后立刻续排。",
                    },
                ),
            },
            "hidden": {"prompt": "PROMPT", "unique_id": "UNIQUE_ID"},
        }

    def chain_next(self, seed, segment_count, enable=True, after=None, prompt=None, unique_id=None):
        total = int(segment_count or 0)
        current = int(seed)
        if not enable or total <= 0:
            return (current,)

        index = (current - 1) % total + 1
        if index >= total:
            print(f"[A-AutoChain] 第 {index}/{total} 段是末段，本轮结束，不再续排。")
            return (current,)

        entry = (prompt or {}).get(str(unique_id)) or {}
        link = (entry.get("inputs") or {}).get("seed")
        if not (isinstance(link, (list, tuple)) and link):
            print("[A-AutoChain] seed 没有接线，无法自动续排。")
            return (current,)

        next_seed = current + 1
        src_id = str(link[0])
        try:
            import asyncio, copy, time, uuid
            from server import PromptServer
            import execution as execution_mod

            server = PromptServer.instance
            new_prompt = copy.deepcopy(dict(prompt))
            new_prompt[src_id]["inputs"]["seed"] = next_seed
            prompt_id = str(uuid.uuid4())

            async def _enqueue():
                valid = await execution_mod.validate_prompt(prompt_id, new_prompt, None)
                if not valid[0]:
                    raise RuntimeError(f"续排校验失败: {valid[1]} | {valid[3]}")
                number = server.number
                server.number = number + 1
                extra_data = {"create_time": int(time.time() * 1000)}
                client_id = getattr(server, "client_id", None)
                if client_id:
                    extra_data["client_id"] = client_id
                server.prompt_queue.put(
                    (number, prompt_id, new_prompt, extra_data, valid[2], {})
                )
                return prompt_id

            future = asyncio.run_coroutine_threadsafe(_enqueue(), server.loop)
            queued_id = future.result(timeout=60.0)
            print(
                f"[A-AutoChain] 第 {index}/{total} 段完成，第 {index + 1} 段已自动排队"
                f"（seed={next_seed}, prompt_id={queued_id}）"
            )
        except Exception as exc:  # 续排失败只打日志，不打断本段结果
            print(f"[A-AutoChain] 自动续排失败：{exc!r}")
        return (next_seed,)


NODE_CLASS_MAPPINGS = {
    "A_MiniMaxH3StoryboardDuration": A_MiniMaxH3StoryboardDuration,
    "A_MiniMaxH3SegmentCount": A_MiniMaxH3SegmentCount,
    "A_MiniMaxH3AutoChainAll": A_MiniMaxH3AutoChainAll,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "A_MiniMaxH3StoryboardDuration": "[A] MiniMax H3 官方提示词时长解析",
    "A_MiniMaxH3SegmentCount": "[A] MiniMax H3 分镜段数统计",
    "A_MiniMaxH3AutoChainAll": "[A] 全段自动续排（一次运行跑完全部分镜）",
}
