# -*- coding: utf-8 -*-
"""Parsing helpers for MiniMax H3 full-reference prompts."""
import re


SECTION_ORDER = (
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
)

_SECTION_RE = re.compile(r"^([a-z_]+):[ \t]*(.*)$")
_SHOT_RE = re.compile(
    r"^\[Shot\s+(\d+)\](?:\s+At\s+(\d+):(\d{2})\.(\d{3}),)?\s*(.*)$"
)
_TIME_PREFIX_RE = re.compile(r"^At\s+\d+:\d{2}\.\d{3}")
_LEGACY_MARKER_RE = re.compile(r"\[分镜\s*\d+\]|@(?:图|视频|音频|img|vid|aud)\s*\d+", re.IGNORECASE)
_BROKEN_LABEL_RE = re.compile(r"<(?:Subject|Picture|Video|Audio)\d+>")
_SHOT_REF_RE = re.compile(r"\[Shot\s+(\d+)\]")
_LABEL_RE = re.compile(r"<(Subject|Picture|Video|Audio)\s+(\d+)>")
_SUMMARY_PREFIX_RE = re.compile(
    r"^\[((?:keyframe completion|reference generation|video editing|video continuation|"
    r"audio reuse|audio reference)(?:\s*\+\s*(?:keyframe completion|reference generation|"
    r"video editing|video continuation|audio reuse|audio reference))*)\]",
    re.IGNORECASE,
)
DEFAULT_SEGMENT_MARKER = "===== prompt_N ====="
MAX_CLIP_DURATION_SECONDS = 15.0
_DURATION_RE = re.compile(
    r"(?<![\w.:])(\d+(?:\.\d+)?)\s*-?\s*"
    r"(hours?|hrs?|hr|h|minutes?|mins?|min|seconds?|secs?|sec|s|小时|分钟|秒)"
    r"(?![A-Za-z])",
    re.IGNORECASE,
)
_DURATION_OUTPUT_CONTEXT_RE = re.compile(
    r"\b(?:clip|video|segment|generation|output|duration|length|runtime|dance|performance)\b"
    r"|(?:视频|片段|时长|长度|舞蹈|表演)",
    re.IGNORECASE,
)
_DURATION_AUDIO_BEFORE_RE = re.compile(
    r"(?:<Audio\s+\d+>|\b(?:audio|song|track|soundtrack|music)\b)[^.!?\n]{0,24}$",
    re.IGNORECASE,
)
_DURATION_AUDIO_AFTER_RE = re.compile(
    r"^[ \t,;:-]*(?:(?:of|for|from)[ \t]+)?(?:audio|song|track|soundtrack|music)\b",
    re.IGNORECASE,
)
_SECTION_BODY_RE = re.compile(
    r"(?ims)^([a-z_]+):[ \t]*(.*?)(?=^[a-z_]+:[ \t]*|\Z)"
)
_DURATION_UNIT_SECONDS = {
    "h": 3600.0, "hr": 3600.0, "hrs": 3600.0, "hour": 3600.0, "hours": 3600.0,
    "min": 60.0, "mins": 60.0, "minute": 60.0, "minutes": 60.0,
    "s": 1.0, "sec": 1.0, "secs": 1.0, "second": 1.0, "seconds": 1.0,
    "秒": 1.0, "分钟": 60.0, "小时": 3600.0,
}
_SOURCE_IMAGE_RE = re.compile(r"@(?:图|img)\s*(\d+)", re.IGNORECASE)
_NAMED_SOURCE_IMAGE_RE = re.compile(
    r"[\w\u3400-\u9fff·.-]+@(?:图|img)\s*(\d+)", re.IGNORECASE
)
_RECOMMENDED_DURATION_RE = re.compile(
    r"^\[Recommended duration\]:[ \t]*(\d+)[ \t]+seconds?[ \t]*$",
    re.IGNORECASE,
)


class OfficialPromptError(ValueError):
    pass


def _duration_matches(text):
    raw = str(text or "")
    values = []
    for match in _DURATION_RE.finditer(raw):
        start, end = match.span()
        before = raw[max(0, start - 40):start]
        after = raw[end:end + 32]
        output_before = bool(_DURATION_OUTPUT_CONTEXT_RE.search(before[-32:]))
        output_after = bool(re.match(
            r"^[ \t-]*(?:clip|video|segment|dance|performance)\b|^[ \t-]*(?:视频|片段|舞蹈|表演)",
            after,
            re.IGNORECASE,
        ))
        audio_context = bool(_DURATION_AUDIO_BEFORE_RE.search(before) or _DURATION_AUDIO_AFTER_RE.match(after))
        if (audio_context and not output_after) or not (output_before or output_after):
            continue
        value, unit = match.groups()
        values.append(float(value) * _DURATION_UNIT_SECONDS[unit.casefold()])
    return values


def extract_max_duration_seconds(text):
    """Return the largest clip/output duration, ignoring timecodes and source-audio lengths."""
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    summary = next(
        (match.group(2) for match in _SECTION_BODY_RE.finditer(raw) if match.group(1).casefold() == "summary"),
        "",
    )
    durations = _duration_matches(summary)
    if not durations:
        durations = _duration_matches(raw)
    return max(durations) if durations else None


def _flexible_marker_literal(value):
    pieces = re.split(r"([ \t]+)", value)
    return "".join(r"[ \t]*" if piece and piece.isspace() else re.escape(piece) for piece in pieces)


def _prompt_marker_pattern(marker_template):
    template = str(marker_template or DEFAULT_SEGMENT_MARKER).strip() or DEFAULT_SEGMENT_MARKER
    placeholder = re.search(
        r"\{N\}|(?P<word>prompt|clip)(?P<underscore>_?)N|\bN\b",
        template,
        re.IGNORECASE,
    )
    if placeholder:
        word = placeholder.group("word")
        fixed = word or ("" if placeholder.group(0) == "{N}" else placeholder.group(0)[:-1])
        separator = r"_?" if word and placeholder.group("underscore") else ""
        pattern = (
            _flexible_marker_literal(template[:placeholder.start()])
            + _flexible_marker_literal(fixed)
            + separator
            + r"(\d+)"
            + _flexible_marker_literal(template[placeholder.end():])
        )
        return re.compile(pattern, re.IGNORECASE), True
    return re.compile(_flexible_marker_literal(template), re.IGNORECASE), False


_LEGACY_STORYBOARD_SPLIT_RE = re.compile(
    r"\[(?:分镜|Shot|shot|SHOT)\s*\d+\]"
)

# 旧格式分段块的权威标记：只有 [分镜N] 才算旧格式，[Shot N] 属于官方六段格式内部标记。
_LEGACY_STORYBOARD_BLOCK_RE = re.compile(r"\[分镜\s*\d+\]")

# 已经是官方分段格式的行标记（===== prompt_1 ===== / ===== clip 02 ===== 等）。
_PROMPT_MARKER_LINE_RE = re.compile(
    r"^[ \t]*=+\s*(?:prompt|clip)[_\s]*0*\d+\s*=+[ \t]*$",
    re.MULTILINE | re.IGNORECASE,
)


def _parse_legacy_subject_definitions(opening):
    """Extract @图N -> definition line mapping from legacy opening section."""
    defs = {}
    for section_match in re.finditer(
        r"\[(?:角色档案|道具档案)\]：\s*\n(.*?)(?=\n\n|\[|S\d)",
        opening, re.DOTALL,
    ):
        for line in section_match.group(1).split("\n"):
            line = line.strip()
            if not line:
                continue
            m = re.match(r"(.+?)@(?:图|img)\s*(\d+)\s*[，,]\s*(.+)", line, re.IGNORECASE)
            if m:
                defs[m.group(2)] = f"@图{m.group(2)} identifies {m.group(1).strip()}: {m.group(3).strip()}"
    for m in re.finditer(
        r"S\d+\s+(.+?)@(?:图|img)\s*(\d+)\s*\([^)]*\)\s*[，,]\s*(.+)",
        opening, re.IGNORECASE,
    ):
        desc = m.group(3).strip()
        if len(desc) > 150:
            desc = desc[:150] + "..."
        defs[m.group(2)] = f"@图{m.group(2)} identifies {m.group(1).strip()}: {desc}"
    return defs


def _convert_legacy_storyboard_format(text):
    """Convert legacy [分镜N] BSAI H3 Film Factory format to official six-section prompt."""
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    # 已经是官方分段格式（含 ===== prompt_N ===== 行）时原样返回，绝不走旧格式转换。
    if _PROMPT_MARKER_LINE_RE.search(raw):
        return raw
    # 旧格式只由 [分镜N] 触发；[Shot N] 是官方六段格式内部的镜头标记，
    # 不能当作旧格式分隔符，否则按 [分镜N] 切块会切出 0 段、返回空串
    # （上游表现为 OfficialPromptError: 官方参考生提示词为空）。
    if not _LEGACY_STORYBOARD_BLOCK_RE.search(raw):
        return raw

    sb_match = _LEGACY_STORYBOARD_BLOCK_RE.search(raw)
    opening = raw[:sb_match.start()]
    storyboard = raw[sb_match.start():]

    subject_defs = _parse_legacy_subject_definitions(opening)

    blocks = list(re.finditer(r"\[分镜\s*\d+\]", storyboard, re.IGNORECASE))
    style_match = re.search(r"\[整体风格\]：\s*(.+)", opening, re.DOTALL)
    style_text = style_match.group(1).strip() if style_match else ""
    if len(style_text) > 150:
        style_text = style_text[:150] + "..."

    segments = []
    for i, match in enumerate(blocks):
        start = match.start()
        end = blocks[i + 1].start() if i + 1 < len(blocks) else len(storyboard)
        block = storyboard[start:end].strip()
        body = re.sub(r"^\s*\[分镜\s*\d+\]\s*[：:]\s*", "", block, count=1)

        used_ids = sorted(set(
            m.group(1) for m in _SOURCE_IMAGE_RE.finditer(body)
        ), key=int)
        seg_defs = [subject_defs[nid] for nid in used_ids if nid in subject_defs]

        lines = []
        lines.append("subject_definitions:")
        lines.extend(seg_defs)
        lines.append("")
        lines.append("summary:")
        lines.append(f"[reference generation + audio reference] {style_text}")
        lines.append("")
        lines.append("retention_analysis:")
        lines.append("N/A")
        lines.append("")
        lines.append("detailed_description:")
        lines.append("[Recommended duration]: 12 seconds")
        lines.append(style_text)
        lines.append("")
        lines.append(f"[Shot 1] {body}")
        lines.append("")
        lines.append("overall_soundscape:")
        lines.append("N/A")
        lines.append("")
        lines.append("non_diegetic_music:")
        lines.append("N/A")
        segments.append("\n".join(lines))

    return "\n\n".join(
        f"===== prompt_{idx + 1} =====\n{seg}" for idx, seg in enumerate(segments)
    )


def convert_source_image_refs(text):
    """Convert BSAI @图 source ids into stable H3 Subject and Picture labels."""
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    source_ids = list(dict.fromkeys(int(value) for value in _SOURCE_IMAGE_RE.findall(raw)))
    if not source_ids:
        return raw, {}
    if re.search(r"<Picture\s+\d+>", raw, re.IGNORECASE):
        raise OfficialPromptError("同一 prompt 不能混用 @图N 源索引和 <Picture N> 内部编号。")

    sections = {
        match.group(1).casefold(): match.group(2)
        for match in _SECTION_BODY_RE.finditer(raw)
    }
    subject_text = sections.get("subject_definitions", "")
    subject_ids = list(dict.fromkeys(
        int(value) for value in _SOURCE_IMAGE_RE.findall(subject_text)
    ))
    subject_labels = {source_id: index for index, source_id in enumerate(subject_ids, 1)}
    picture_labels = {source_id: index for index, source_id in enumerate(source_ids, 1)}

    # BSAI source ids identify the library entries. Picture labels are local to
    # this prompt, while Subject labels follow subject_definitions order.
    lines = raw.split("\n")
    in_subject_definitions = False
    definition_re = re.compile(
        r"^\s*[^\n]*?@(?:图|img)\s*(\d+)\s+identifies\s+(.+?)\s*$",
        re.IGNORECASE,
    )
    for index, line in enumerate(lines):
        heading = re.match(r"^([a-z_]+):", line)
        if heading:
            in_subject_definitions = heading.group(1).casefold() == "subject_definitions"
            continue
        if not in_subject_definitions:
            continue
        match = definition_re.match(line)
        if not match:
            continue
        source_id = int(match.group(1))
        subject_id = subject_labels.get(source_id)
        picture_id = picture_labels.get(source_id)
        if subject_id is None or picture_id is None:
            continue
        description = match.group(2).strip()
        lines[index] = (
            f"<Subject {subject_id}> is {description} "
            f"Its visual reference is <Picture {picture_id}>."
        )

    prepared = "\n".join(lines)

    def replace_reference(match):
        source_id = int(match.group(1))
        subject_id = subject_labels.get(source_id)
        if subject_id is not None:
            return f"<Subject {subject_id}>"
        return f"<Picture {picture_labels[source_id]}>"

    converted = _NAMED_SOURCE_IMAGE_RE.sub(replace_reference, prepared)
    converted = _SOURCE_IMAGE_RE.sub(
        lambda match: (
            f"<Subject {subject_labels[int(match.group(1))]}>"
            if int(match.group(1)) in subject_labels
            else f"<Picture {picture_labels[int(match.group(1))]}>"
        ),
        converted,
    )
    return converted, picture_labels


def extract_recommended_duration_seconds(detailed_description):
    """Read the unique duration metadata line at the start of detailed_description."""
    lines = [line.strip() for line in str(detailed_description or "").splitlines()]
    matches = [
        (index, match)
        for index, line in enumerate(lines)
        if (match := _RECOMMENDED_DURATION_RE.fullmatch(line))
    ]
    metadata_lines = [
        line for line in lines if "[recommended duration]" in line.casefold()
    ]
    if len(metadata_lines) > 1:
        raise OfficialPromptError("detailed_description: [Recommended duration] 必须且只能出现一次。")
    if not matches:
        if metadata_lines:
            raise OfficialPromptError(
                "[Recommended duration] 必须写成 [Recommended duration]: N seconds。"
            )
        return None
    if len(matches) != 1:
        raise OfficialPromptError("detailed_description: [Recommended duration] 必须且只能出现一次。")
    first_content = next((index for index, line in enumerate(lines) if line), None)
    if matches[0][0] != first_content:
        raise OfficialPromptError(
            "[Recommended duration] 必须是 detailed_description: 后的第一行。"
        )
    return float(matches[0][1].group(1))


def parse_official_prompt_segments(text, segment_marker=DEFAULT_SEGMENT_MARKER):
    """Split and validate full prompts using a configurable outer marker template."""
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    raw = _convert_legacy_storyboard_format(raw)
    marker_re, has_number = _prompt_marker_pattern(segment_marker)
    matches = list(marker_re.finditer(raw))
    if not matches:
        prompt = raw.strip()
        converted, picture_labels = convert_source_image_refs(prompt)
        parsed = parse_official_prompt(converted)
        duration_sec = extract_recommended_duration_seconds(
            parsed["sections"]["detailed_description"]
        )
        return [{
            "label": 1,
            "marker": "",
            "prompt": prompt,
            "converted_prompt": converted,
            "source_image_refs": picture_labels,
            "parsed": parsed,
            "duration_sec": duration_sec if duration_sec is not None else extract_max_duration_seconds(converted),
        }]
    if len(matches) > 512:
        raise OfficialPromptError("prompt 段数超过上限 512。")
    segments = []
    for position, match in enumerate(matches):
        end = matches[position + 1].start() if position + 1 < len(matches) else len(raw)
        prompt = raw[match.end():end].strip()
        label = int(match.group(1)) if has_number else position + 1
        if label < 1:
            raise OfficialPromptError("分区标记中的序号必须从 1 开始。")
        if not prompt:
            raise OfficialPromptError(f"分区标记 {match.group(0)!r} 后没有提示词内容。")
        converted, picture_labels = convert_source_image_refs(prompt)
        parsed = parse_official_prompt(converted)
        duration_sec = extract_recommended_duration_seconds(
            parsed["sections"]["detailed_description"]
        )
        segments.append({
            "label": label,
            "marker": match.group(0),
            "prompt": prompt,
            "converted_prompt": converted,
            "source_image_refs": picture_labels,
            "parsed": parsed,
            "duration_sec": duration_sec if duration_sec is not None else extract_max_duration_seconds(converted),
        })
    return segments


def resolve_prompt_segment_duration(segment, segment_count, fallback_frames=124, video_duration_sec=0.0):
    """Use the largest clip duration in this prompt block, then safe fallbacks."""
    duration_sec = segment.get("duration_sec")
    if duration_sec is not None:
        duration_sec = float(duration_sec)
        source = "detailed_description" if "[Recommended duration]" in segment.get("prompt", "") else "prompt summary"
    # A whole-video duration is meaningful only when there is a single prompt block.
    elif int(segment_count) == 1 and float(video_duration_sec or 0.0) > 0:
        duration_sec = float(video_duration_sec)
        source = "video_duration_sec"
    else:
        duration_sec = max(5.0 / 24.0, int(fallback_frames) / 24.0)
        source = "fallback_length_frames"
    if duration_sec > MAX_CLIP_DURATION_SECONDS:
        raise OfficialPromptError(
            f"识别到的 CLIP 时长 {duration_sec:.3f} 秒超过 MiniMax H3 单段 15 秒上限；请拆分提示词或缩短时长。"
        )
    return duration_sec, source


def parse_official_prompt(text):
    """Parse the six official full-reference sections and their Shot blocks."""
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        raise OfficialPromptError("官方参考生提示词为空。")
    if _LEGACY_MARKER_RE.search(raw):
        raise OfficialPromptError("检测到旧分镜或 @素材标记；请改用 [Shot N] 和 <Picture N>/<Video N>/<Audio N>。")
    if _BROKEN_LABEL_RE.search(raw):
        raise OfficialPromptError("参考标签的类别与编号之间必须留空格，例如 <Picture 1>。")

    sections = {}
    current = None
    for line in raw.split("\n"):
        match = _SECTION_RE.match(line)
        name = match.group(1) if match else None
        if name in SECTION_ORDER:
            if name in sections:
                raise OfficialPromptError(f"章节 {name}: 重复出现。")
            current = name
            sections[name] = [match.group(2)] if match.group(2) else []
        elif name and current is not None:
            raise OfficialPromptError(
                f"发现非官方章节 {name}:；只接受官方六章节，且必须按规定顺序填写。"
            )
        elif current is not None:
            sections[current].append(line)
        elif line.strip():
            raise OfficialPromptError(
                "提示词必须从 subject_definitions: 开始，并按官方六章节顺序填写。"
            )

    missing = [name for name in SECTION_ORDER if name not in sections]
    if missing:
        raise OfficialPromptError("缺少官方章节：" + ", ".join(missing))
    header_order = [
        match.group(1)
        for line in raw.split("\n")
        if (match := _SECTION_RE.match(line)) and match.group(1) in SECTION_ORDER
    ]
    if tuple(header_order) != SECTION_ORDER:
        raise OfficialPromptError(
            "官方章节顺序必须是：" + " → ".join(SECTION_ORDER)
        )

    values = {name: "\n".join(lines).strip() for name, lines in sections.items()}
    empty = [name for name, value in values.items() if not value]
    if empty:
        raise OfficialPromptError("以下官方章节内容为空：" + ", ".join(empty))
    summary_prefix = _SUMMARY_PREFIX_RE.match(values["summary"])
    if not summary_prefix:
        raise OfficialPromptError(
            "summary: 必须以官方任务类型开头，例如 [reference generation + audio reference]。"
        )
    tasks = [task.strip().casefold() for task in summary_prefix.group(1).split("+")]
    if len(tasks) != len(set(tasks)):
        raise OfficialPromptError("summary: 任务类型不能重复。")

    detail_lines = values["detailed_description"].split("\n")
    markers = []
    for line_index, line in enumerate(detail_lines):
        match = _SHOT_RE.match(line)
        if match:
            minute, second, millis = match.group(2), match.group(3), match.group(4)
            start = None
            if minute is not None:
                if int(second) > 59:
                    raise OfficialPromptError(f"[Shot {match.group(1)}] 时间戳的秒数必须在 00~59。")
                start = int(minute) * 60 + int(second) + int(millis) / 1000.0
            markers.append({
                "num": int(match.group(1)),
                "line_index": line_index,
                "timestamp": start,
                "first_line": match.group(5),
            })

    if not markers:
        raise OfficialPromptError("detailed_description: 中没有找到独立成行的 [Shot N]。")
    if [item["num"] for item in markers] != list(range(1, len(markers) + 1)):
        raise OfficialPromptError("镜头编号必须从 [Shot 1] 开始并连续递增。")
    if markers[0]["timestamp"] is not None or _TIME_PREFIX_RE.match(markers[0]["first_line"]):
        raise OfficialPromptError("官方格式要求 [Shot 1] 不带时间戳。")
    for marker in markers[1:]:
        if marker["timestamp"] is None:
            raise OfficialPromptError(
                f"[Shot {marker['num']}] 缺少 At MM:SS.mmm 时间戳。"
            )
    starts = [0.0] + [item["timestamp"] for item in markers[1:]]
    if any(current <= previous for previous, current in zip(starts, starts[1:])):
        raise OfficialPromptError("Shot 时间戳必须严格递增。")

    shots = []
    for index, marker in enumerate(markers):
        end_line = markers[index + 1]["line_index"] if index + 1 < len(markers) else len(detail_lines)
        body_lines = [marker["first_line"]] + detail_lines[marker["line_index"] + 1:end_line]
        body = "\n".join(body_lines).strip()
        if not body:
            raise OfficialPromptError(f"[Shot {marker['num']}] 没有镜头描述。")
        shots.append({"num": marker["num"], "start_sec": starts[index], "body": body})

    opening = "\n".join(detail_lines[:markers[0]["line_index"]]).strip()
    if not opening:
        raise OfficialPromptError(
            "detailed_description: 请在 [Shot 1] 前写一到两句全片风格开场。"
        )
    return {"sections": values, "opening": opening, "shots": shots}


def _labels(text):
    return {(kind, int(number)) for kind, number in _LABEL_RE.findall(text or "")}


def _segment_retention_analysis(text, shot_index, active_labels):
    kept = []
    for line in (text or "").split("\n"):
        labels = _labels(line)
        if not labels:
            if line.strip() and line.strip().casefold() != "n/a":
                kept.append(line)
            continue
        if not labels.intersection(active_labels):
            continue
        shot_refs = [int(number) for number in _SHOT_REF_RE.findall(line)]
        if shot_refs and shot_index not in shot_refs:
            continue
        kept.append(_SHOT_REF_RE.sub("[Shot 1]", line))
    return "\n".join(kept).strip() or "N/A"


def extract_official_shot(parsed, shot_index, video_duration_sec=0.0, fallback_frames=124):
    shots = parsed["shots"]
    index = int(shot_index)
    if index < 1 or index > len(shots):
        raise OfficialPromptError(
            f"clip_index={index} 超出范围；提示词共 {len(shots)} 段，请填写 1~{len(shots)}。"
        )

    shot = shots[index - 1]
    start_sec = shot["start_sec"]
    if index < len(shots):
        end_sec = shots[index]["start_sec"]
        duration_sec = end_sec - start_sec
    elif float(video_duration_sec or 0.0) > start_sec:
        end_sec = float(video_duration_sec)
        duration_sec = end_sec - start_sec
    else:
        duration_sec = max(5.0 / 24.0, int(fallback_frames) / 24.0)

    sections = dict(parsed["sections"])
    active_labels = _labels(shot["body"])
    active_labels.update(_labels(sections["overall_soundscape"]))
    active_labels.update(_labels(sections["non_diegetic_music"]))
    definitions = sections["subject_definitions"].split("\n")
    changed = True
    while changed:
        changed = False
        for line in definitions:
            labels = _labels(line)
            if labels.intersection(active_labels) and not labels.issubset(active_labels):
                active_labels.update(labels)
                changed = True

    sections["retention_analysis"] = _segment_retention_analysis(
        sections["retention_analysis"], index, active_labels
    )
    sections["detailed_description"] = (
        parsed["opening"] + "\n\n[Shot 1] " + shot["body"]
    )
    selected_prompt = "\n\n".join(
        f"{name}:\n{sections[name]}" for name in SECTION_ORDER
    )
    return selected_prompt, start_sec, duration_sec
