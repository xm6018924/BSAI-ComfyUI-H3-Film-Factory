# -*- coding: utf-8 -*-
"""Librosa beat analysis and H3-safe beat-cue injection nodes."""
import re

import numpy as np

CUE_GUARD = "Rhythm guide"
_ANALYSIS_CACHE = {}


def _analyze_audio(audio):
    """Run librosa once per audio; return (tempo, beat_times). Cached."""
    import librosa
    import torch

    waveform = audio["waveform"]
    sr = int(audio["sample_rate"])
    key = (sr, tuple(waveform.shape), float(waveform.float().sum()), float(waveform.float().abs().max()))
    if key in _ANALYSIS_CACHE:
        return _ANALYSIS_CACHE[key]

    # collapse to mono [samples], ComfyUI AUDIO is [batch, channels, samples]
    mono = waveform.mean(dim=1).squeeze(0).detach().cpu().numpy().astype("float32")
    tempo, beat_frames = librosa.beat.beat_track(y=mono, sr=sr)
    tempo = float(np.atleast_1d(tempo)[0])
    beat_times = librosa.frames_to_time(beat_frames, sr=sr).astype("float64")
    result = (tempo, beat_times)
    _ANALYSIS_CACHE[key] = result
    return result


def _fmt(values):
    return ", ".join(f"{v:.2f}" for v in values)


_REC_DUR_RE = re.compile(
    r"^\[Recommended duration\]:\s*(\d+(?:\.\d+)?)\s*seconds?\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def _durations_from_prompt(raw):
    """Read every clip's [Recommended duration]; supports unequal clip lengths."""
    text = str(raw or "").replace("\r\n", "\n").replace("\r", "\n")
    markers = list(_MARKER_RE.finditer(text))
    if not markers:
        m = _REC_DUR_RE.search(text)
        if not m:
            raise ValueError("no [Recommended duration] found in the storyboard text; cannot follow the prompt duration.")
        return [float(m.group(1))]
    durs = []
    for i, mk in enumerate(markers):
        seg_end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        seg = text[mk.end():seg_end]
        m = _REC_DUR_RE.search(seg)
        if not m:
            raise ValueError(f"segment {i + 1} has no [Recommended duration]; cannot follow the prompt duration.")
        durs.append(float(m.group(1)))
    return durs


def _out_of_range(clip_index, n_clips, tempo):
    msg = f"clip_index={clip_index} exceeds the current {n_clips} segment(s); skipped beat analysis."
    cue = f"{CUE_GUARD}, tempo {tempo:.2f} BPM; clip index out of range, no beat cue added."
    return (float(tempo), cue, "", "", 0, msg)


class A_LibrosaBeatCue:
    """Analyze the song and build an H3-safe rhythm cue for the current clip."""

    CATEGORY = "A-BSAI/H3"
    FUNCTION = "build_cue"
    OUTPUT_NODE = False
    RETURN_TYPES = ("FLOAT", "STRING", "STRING", "STRING", "INT", "STRING")
    RETURN_NAMES = (
        "tempo_bpm",
        "beat_cue_text",
        "global_beat_times",
        "global_downbeat_times",
        "beats_in_clip",
        "status",
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio": ("AUDIO", {"forceInput": True, "tooltip": "The full song; analyzed once per audio and cached."}),
                "clip_index": ("INT", {"forceInput": True, "min": 1, "tooltip": "Current clip index, fed from the SeedNode."}),
                "performer_name": ("STRING", {"default": "Chi Heng", "tooltip": "Performer name used in the prompt; change per project."}),
                "beats_per_bar": ("INT", {"default": 4, "min": 1, "max": 16, "tooltip": "Beats per bar; set 4 for 4/4 time."}),
                "cue_mode": (["downbeats_only", "all_beats"], {"tooltip": "Cue mode: mark downbeats only, or every beat."}),
                "grid_duration": ("FLOAT", {"default": 8.0, "min": 0.1, "max": 15.0, "step": 0.1, "tooltip": "Fallback: fixed segment length used only when neither the prompt text nor external start/duration is wired."}),
                "motion_cycle_sec": ("FLOAT", {"default": 6.0, "min": 2.0, "max": 12.0, "step": 0.5, "tooltip": "Speed: seconds for one full left-right sweep; shared by pan and roll. Larger is slower, smaller is faster."}),
                "sway_percent": ("FLOAT", {"default": 2.5, "min": 0.0, "max": 10.0, "step": 0.5, "tooltip": "Small horizontal camera pan as a percentage of frame width; 0 disables pan."}),
                "roll_degrees": ("FLOAT", {"default": 5.0, "min": 0.0, "max": 20.0, "step": 0.5, "tooltip": "Camera roll in degrees; 0 disables roll."}),
                "time_offset": ("FLOAT", {"default": 0.0, "min": -1.0, "max": 1.0, "step": 0.01, "tooltip": "Shift all beat points earlier or later (seconds)."}),
                "camera_breathing": ("BOOLEAN", {"default": True, "tooltip": "Add a handheld breathing camera (drift + roll)."}),
            },
            "optional": {
                "prompt_source": ("STRING", {"forceInput": True, "tooltip": "Storyboard text; when connected each segment duration follows the prompt and segments may differ in length. Recommended."}),
                "start_time_sec": ("FLOAT", {"forceInput": True, "tooltip": "Advanced: feed the current segment start (seconds) directly from an external node; leave empty for normal use."}),
                "clip_duration_sec": ("FLOAT", {"forceInput": True, "tooltip": "Advanced: feed the current segment duration (seconds) directly from an external node; leave empty for normal use."}),
            },
        }

    def build_cue(self, audio, clip_index, performer_name, beats_per_bar, cue_mode,
                  grid_duration, motion_cycle_sec, sway_percent, roll_degrees,
                  time_offset, camera_breathing,
                  prompt_source=None, start_time_sec=None, clip_duration_sec=None):
        tempo, beat_times = _analyze_audio(audio)
        total_audio = audio["waveform"].shape[-1] / float(audio["sample_rate"])
        clip_index = int(clip_index)
        if start_time_sec is not None and clip_duration_sec is not None:
            # priority 1: explicit external start/duration
            start = float(start_time_sec)
            duration = float(clip_duration_sec)
        elif prompt_source is not None:
            # priority 2: follow each clip's [Recommended duration] in the prompt
            durs = _durations_from_prompt(prompt_source)
            if clip_index > len(durs):
                return _out_of_range(clip_index, len(durs), tempo)
            duration = durs[clip_index - 1]
            start = float(sum(durs[:clip_index - 1]))
        else:
            # priority 3: fixed-grid fallback
            grid = float(grid_duration)
            start = (clip_index - 1) * grid
            duration = min(grid, max(0.0, total_audio - start))
        end = start + duration

        # global downbeat positions (every beats_per_bar beat, starting at first beat)
        downbeat_times = beat_times[:: max(1, int(beats_per_bar))]

        # beats inside this clip window (small tolerance at the edges)
        inside = (beat_times >= start - 0.02) & (beat_times < end + 0.02)
        local_idx = np.where(inside)[0]
        local_rel = (beat_times[local_idx] - start + float(time_offset))
        local_rel = np.maximum(local_rel, 0.0)
        is_down = (local_idx % max(1, int(beats_per_bar)) == 0)
        local_down = local_rel[is_down]
        local_all = local_rel

        name = str(performer_name).strip() or "the performer"
        parts = [f"{CUE_GUARD}, tempo {tempo:.2f} BPM."]
        if len(local_down):
            parts.append(
                "Downbeat accents within this clip land at " + _fmt(local_down) +
                f"; on each downbeat {name} snaps into a sharp hit pose and freezes for a beat, "
                "then flows through the off-beats so every accent lands exactly on the beat."
            )
        else:
            parts.append(
                f"No downbeat falls inside this clip; {name} keeps a continuous flowing motion "
                "and carries the rhythm across the clip boundary."
            )
        if cue_mode == "all_beats" and len(local_all):
            parts.append("Beat positions within this clip are " + _fmt(local_all) + ".")
        if camera_breathing:
            cycle = float(motion_cycle_sec); sway = float(sway_percent); roll = float(roll_degrees)
            motion_bits = []
            if sway > 0.0:
                motion_bits.append(
                    f"the handheld camera gently sways and drifts left and right by about {sway:.1f} percent of frame width"
                )
            if roll > 0.0:
                motion_bits.append(
                    f"a handheld roll that tilts the horizon left and right by about {roll:.1f} degrees"
                )
            if motion_bits:
                camera_sent = (
                    "The camera is handheld; " + ", combined with ".join(motion_bits) +
                    f"; the drift and tilt share one smooth cycle of about {cycle:.1f} seconds per full left-right-left sweep, "
                    "and move together around the subject while the subject stays centered; "
                    "the camera movement is a continuous breathing drift and never snaps on the beat."
                )
            else:
                camera_sent = (
                    "The camera stays nearly static with only a faint handheld breathing; "
                    "the subject stays centered and the camera never moves on the beat."
                )
            parts.append(camera_sent)
        cue = " ".join(parts)

        global_beats = ", ".join(f"{v:.3f}" for v in beat_times)
        global_downs = ", ".join(f"{v:.3f}" for v in downbeat_times)
        status = (
            f"clip {int(clip_index)} window {start:.3f}-{end:.3f}; "
            f"{len(local_all)} beats ({len(local_down)} downbeats); tempo {tempo:.2f} BPM."
        )
        return (float(tempo), cue, global_beats, global_downs, int(len(local_all)), status)

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")


_MARKER_RE = re.compile(
    r"^[ \t]*=+\s*prompt[_\s]*0*(\d+)\s*=+[ \t]*$",
    re.MULTILINE | re.IGNORECASE,
)
_SHOT1_RE = re.compile(r"^[ \t]*\[Shot\s+1\]", re.MULTILINE)


class A_TextInjectCue:
    """Inject the cue into the current clip's opening line (before [Shot 1])."""

    CATEGORY = "A-BSAI/H3"
    FUNCTION = "inject"
    OUTPUT_NODE = False
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("prompt_source_enhanced", "status")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt_source": ("STRING", {"forceInput": True, "multiline": True, "tooltip": "Original storyboard text, fed from a PrimitiveString."}),
                "beat_cue_text": ("STRING", {"forceInput": True, "tooltip": "Beat-cue instruction output by the beat node."}),
                "clip_index": ("INT", {"forceInput": True, "min": 1, "tooltip": "Current clip index, fed from the SeedNode."}),
                "enable": ("BOOLEAN", {"default": True, "tooltip": "Master switch; when off the original text is output unchanged."}),
            }
        }

    def inject(self, prompt_source, beat_cue_text, clip_index, enable):
        raw = str(prompt_source or "").replace("\r\n", "\n").replace("\r", "\n")
        index = int(clip_index) - 1
        if not enable:
            return (prompt_source, "injection disabled; prompt unchanged.")

        markers = list(_MARKER_RE.finditer(raw))
        if not markers:
            # graceful: prompt not wired / empty, do not crash the run
            return (prompt_source, "no storyboard segment marker detected (prompt may not be connected); skipped injection.")
        if index < 0 or index >= len(markers):
            # graceful: do not crash the run when the loop runs past the available clips
            return (prompt_source, f"clip_index={clip_index} exceeds the current {len(markers)} segment(s); skipped injection.")

        seg_start = markers[index].end()
        seg_end = markers[index + 1].start() if index + 1 < len(markers) else len(raw)
        seg = raw[seg_start:seg_end]

        m = _SHOT1_RE.search(seg)
        if not m:
            raise ValueError(f"clip {clip_index}: no [Shot 1] line found; cannot find opening to inject.")
        before, after = seg[:m.start()], seg[m.start():]
        trimmed = before.rstrip()

        # idempotent: do not stack a second cue
        if CUE_GUARD in trimmed:
            return (prompt_source, f"clip {clip_index} already contains a rhythm cue; not duplicated.")

        gap = before[len(trimmed):]
        new_seg = trimmed + " " + str(beat_cue_text).strip() + gap + after
        enhanced = raw[:seg_start] + new_seg + raw[seg_end:]
        return (enhanced, f"Rhythm cue injected into clip {clip_index} opening; other clips unchanged.")

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")


NODE_CLASS_MAPPINGS = {
    "A_LibrosaBeatCue": A_LibrosaBeatCue,
    "A_TextInjectCue": A_TextInjectCue,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "A_LibrosaBeatCue": "[A] Librosa Beat Cue",
    "A_TextInjectCue": "[A] H3 Beat Cue Inject",
}
