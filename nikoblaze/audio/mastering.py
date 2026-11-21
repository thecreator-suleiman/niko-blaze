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


def tonal_fix(src, dst, department: str, m: dict) -> dict:
    """Corrective EQ like a mastering engineer would apply, adapted to each take's measured balance:
    lift a dull top end, tame boomy/muddy lows, narrow a phasey stereo image. Returns what was applied."""
    relax = department == "relaxation"
    target_hf = cfg("mastering.target_hf_db_relax", -26) if relax else cfg("mastering.target_hf_db", -17)
    hf = m.get("hf_db", target_hf)
    bands = m.get("bands", {})
    low = bands.get("sub", 0) + bands.get("bass", 0)
    chain, applied = ["highpass=f=30:poles=2"], {}
    boost = max(0.0, min(14.0, target_hf - hf))
    if boost >= 1:
        # two gentle shelves sound more natural than one big one
        chain += [f"treble=g={boost * 0.6:.1f}:f=2500:t=s:w=0.5", f"treble=g={boost * 0.4:.1f}:f=7000:t=s:w=0.5"]
        applied["treble_db"] = round(boost, 1)
    mid = bands.get("mid", 0)
    if low > 0.55 or (relax and mid > 0 and low > mid):
        cut = min(6.0, max(2.0, (low - 0.45) * 15))
        chain += [f"equalizer=f=180:t=o:w=1.4:g=-{cut:.1f}", f"bass=g=-{cut / 2:.1f}:f=80"]
        applied["low_cut_db"] = round(cut, 1)
    if m.get("channels", 2) > 1 and m.get("stereo_corr", 1) < 0.1:
        chain.append("extrastereo=m=0.6")  # pull the sides in for mono compatibility
        applied["stereo_narrowed"] = True
    chain.append("alimiter=limit=0.89:level=false")  # boosts must never clip
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    ffmpeg("-i", str(src), "-af", ",".join(chain), "-c:a", "pcm_s24le", str(dst))
    return applied


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
