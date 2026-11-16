"""Objective audio measurements (numpy + FFmpeg EBU R128)."""
import re
import subprocess

import numpy as np
import soundfile as sf


def ffmpeg(*args, timeout=7200):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-y", *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr[-1500:]}")
    return r.stderr


def probe_duration(path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def ebur128(path) -> dict:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-filter_complex",
                        "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True)
    s = r.stderr[r.stderr.rfind("Summary:"):]
    def grab(pat):
        m = re.search(pat, s)
        return float(m.group(1)) if m else None
    return {"lufs": grab(r"I:\s+(-?[\d.]+|-inf) LUFS"), "lra": grab(r"LRA:\s+(-?[\d.]+) LU"),
            "true_peak": grab(r"True peak:\s+Peak:\s+(-?[\d.]+|-inf) dBFS")}


def analyze(path) -> dict:
    x, sr = sf.read(str(path), always_2d=True, dtype="float32")
    info = sf.info(str(path))
    m = {"sample_rate": sr, "channels": x.shape[1], "subtype": info.subtype, "duration": len(x) / sr}
    if not np.isfinite(x).all():
        m["nan"] = True
        return m
    a = np.abs(x)
    m["peak_dbfs"] = float(20 * np.log10(max(a.max(), 1e-9)))
    full = a >= 0.999
    m["clip_ratio"] = float(full.mean())
    # clipped runs: >=3 consecutive full-scale samples
    f = full.any(axis=1).astype(np.int8)
    runs = np.diff(np.concatenate([[0], f, [0]]))
    starts, ends = np.where(runs == 1)[0], np.where(runs == -1)[0]
    m["clip_runs"] = int(((ends - starts) >= 3).sum())
    m["dc_offset"] = float(np.abs(x.mean(axis=0)).max())
    mono = x.mean(axis=1)
    hop = int(sr * 0.05)
    n = len(mono) // hop
    rms = np.sqrt((mono[: n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    m["silence_ratio"] = float((db < -50).mean()) if n else 1.0
    # longest silent gap away from the edges (dropouts)
    inner = db[int(n * 0.05): int(n * 0.92)] < -55
    longest, cur = 0, 0
    for v in inner:
        cur = cur + 1 if v else 0
        longest = max(longest, cur)
    m["max_inner_silence_s"] = longest * 0.05
    m["stereo_corr"] = float(np.corrcoef(x[:, 0], x[:, 1])[0, 1]) if x.shape[1] > 1 and x[:, 0].std() > 0 and x[:, 1].std() > 0 else 1.0
    # spectrum (frames of 8192, every ~1 s)
    N = 8192
    step = max(N, sr)
    frames = [mono[i:i + N] for i in range(0, len(mono) - N, step)]
    if frames:
        win = np.hanning(N)
        P = np.array([np.abs(np.fft.rfft(fr * win)) ** 2 for fr in frames]) + 1e-12
        freqs = np.fft.rfftfreq(N, 1 / sr)
        loud = P.sum(axis=1) > np.percentile(P.sum(axis=1), 30)
        Pl = P[loud] if loud.any() else P
        spec = Pl.mean(axis=0)
        tot = spec[(freqs >= 20) & (freqs <= 20000)].sum()
        band = lambda lo, hi: float(spec[(freqs >= lo) & (freqs < hi)].sum() / tot)
        m["bands"] = {"sub": band(20, 60), "bass": band(60, 250), "mid": band(250, 4000),
                      "high": band(4000, 12000), "air": band(12000, 20000)}
        cum = np.cumsum(spec) / spec.sum()
        m["rolloff_99_hz"] = float(freqs[np.searchsorted(cum, 0.995)])
        sel = (freqs > 100) & (freqs < 10000)
        flat = np.exp(np.log(Pl[:, sel]).mean(axis=1)) / Pl[:, sel].mean(axis=1)
        m["spectral_flatness"] = float(np.median(flat))
    m.update(ebur128(path))
    return m
