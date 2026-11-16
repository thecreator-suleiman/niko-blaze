"""Transparent mastering with FFmpeg: clean-up, gentle glue compression, two-pass EBU R128 loudness.
Targets YouTube-friendly loudness (-14 LUFS) instead of maximum loudness, preserving dynamics."""
import json
import re
from pathlib import Path

from ..config import cfg, mastering_target
from .analysis import ffmpeg


def _pre_chain() -> str:
    c = cfg("mastering.compressor")
    return (f"highpass=f=24:poles=2,"
            f"acompressor=threshold={c['threshold_db']}dB:ratio={c['ratio']}:attack={c['attack_ms']}:"
            f"release={c['release_ms']}:knee=6:makeup=1")


def master(src, dst_wav, department: str) -> dict:
    t = mastering_target(department)
    sr = int(cfg("mastering.sample_rate", 48000))
    pre = _pre_chain()
    ln = f"loudnorm=I={t['lufs']}:TP={t['true_peak']}:LRA={t['lra']}"
    err = ffmpeg("-i", str(src), "-af", f"{pre},{ln}:print_format=json", "-f", "null", "-")
    meas = json.loads(re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", err, re.S)[-1])
    second = (f"{pre},{ln}:measured_I={meas['input_i']}:measured_TP={meas['input_tp']}:"
              f"measured_LRA={meas['input_lra']}:measured_thresh={meas['input_thresh']}:"
              f"offset={meas['target_offset']}:linear=true,"
              f"alimiter=limit={10 ** ((t['true_peak'] - 0.3) / 20):.4f}:attack=5:release=60:level=false,"
              f"aresample={sr}")
    Path(dst_wav).parent.mkdir(parents=True, exist_ok=True)
    ffmpeg("-i", str(src), "-af", second, "-ar", str(sr), "-ac", "2", "-c:a", "pcm_s24le", str(dst_wav))
    return {"target": t, "first_pass": meas}


def to_flac(src, dst):
    ffmpeg("-i", str(src), "-c:a", "flac", "-compression_level", "8", "-sample_fmt", "s32", str(dst))


def to_aac(src, dst):
    ffmpeg("-i", str(src), "-c:a", "aac", "-b:a", cfg("mastering.aac_bitrate", "384k"), "-ar", "48000", str(dst))
