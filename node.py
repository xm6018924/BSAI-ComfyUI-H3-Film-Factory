"""
Small utility node kept alongside the Motion Context pipeline.

MiniMax H3 Tail From Latent:
decode a sampled H3 joint AV latent and expose a tail / last frame that can
still be useful as an image/video reference in external H3 workflows.

All obsolete bridge / seam / concatenate experiments were removed in v13.
"""

import torch

FPS = 24.0
MIN_H3_FRAMES = 5
BUILD = "tail-from-latent-v13-clean"


def _align_h3_frame_count(n: int) -> int:
    n = max(MIN_H3_FRAMES, int(n))
    while n % 17 != 5:
        n += 1
    return n


def _decode_video(vae, samples):
    latent = samples["samples"]
    if getattr(latent, "is_nested", False):
        latent = latent.unbind()[0]
    images = vae.decode(latent)
    if images.ndim == 5:
        images = images.reshape(
            -1,
            images.shape[-3],
            images.shape[-2],
            images.shape[-1],
        )
    return images


def _decode_audio(audio_vae, samples):
    latent = samples["samples"]
    if getattr(latent, "is_nested", False):
        latent = latent.unbind()[-1]

    audio = audio_vae.decode(latent).movedim(-1, 1)
    std = torch.std(audio, dim=[1, 2], keepdim=True) * 5.0
    std[std < 1.0] = 1.0
    audio = audio / std

    sr = getattr(
        audio_vae,
        "audio_sample_rate_output",
        getattr(audio_vae, "audio_sample_rate", 32000),
    )
    if "sample_rate" in samples:
        sr = samples["sample_rate"]

    return {
        "waveform": audio,
        "sample_rate": int(sr),
    }


def _slice_audio_tail(audio, seconds):
    sr = int(audio["sample_rate"])
    waveform = audio["waveform"]
    wanted = max(1, int(round(float(seconds) * sr)))
    start = max(0, int(waveform.shape[-1]) - wanted)
    return {
        "waveform": waveform[..., start:],
        "sample_rate": sr,
    }


class MiniMaxH3TailFromLatent:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "samples": ("LATENT",),
                "vae": ("VAE",),
                "audio_vae": ("VAE",),
                "tail_seconds": (
                    "FLOAT",
                    {
                        "default": 0.5,
                        "min": 0.1,
                        "max": 15.0,
                        "step": 0.05,
                    },
                ),
                "align_to_h3_grid": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("IMAGE", "AUDIO", "IMAGE", "INT", "FLOAT")
    RETURN_NAMES = (
        "ref_video",
        "ref_video_audio",
        "last_frame",
        "frame_count",
        "duration_seconds",
    )
    FUNCTION = "extract"
    CATEGORY = "BSAI/H3 Film Factory"

    def extract(
        self,
        samples,
        vae,
        audio_vae,
        tail_seconds,
        align_to_h3_grid,
    ):
        frames = _decode_video(vae, samples)
        audio = _decode_audio(audio_vae, samples)

        total = int(frames.shape[0])
        wanted = max(
            1,
            min(total, int(round(float(tail_seconds) * FPS))),
        )

        if align_to_h3_grid:
            count = min(
                total,
                _align_h3_frame_count(max(MIN_H3_FRAMES, wanted)),
            )
        else:
            count = wanted

        duration = count / FPS

        return (
            frames[-count:],
            _slice_audio_tail(audio, duration),
            frames[-1:].clone(),
            count,
            float(duration),
        )


NODE_CLASS_MAPPINGS = {
    "MiniMaxH3TailFromLatent": MiniMaxH3TailFromLatent,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3TailFromLatent": "BSAI H3 Film Factory | Tail From Latent",
}
