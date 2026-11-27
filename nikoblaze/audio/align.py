"""Align known lyrics to recognised words -> per-line and per-word timing + intelligibility ratio."""
import difflib
import re

from ..lyrics.quality import parse_sections

norm = lambda w: re.sub(r"[^a-z0-9']", "", w.lower())


def lyric_lines(lyrics: str) -> list[str]:
    return [l for _, ls in parse_sections(lyrics) for l in ls]


def align(lyrics: str, recognised: list[dict], duration: float) -> dict:
    """recognised: [{'w','s','e'}]. Returns {'match_ratio', 'lines': [{'text','start','end','words':[(w,s,e)]}]}"""
    lines = lyric_lines(lyrics)
    toks = [(li, w) for li, l in enumerate(lines) for w in l.split() if norm(w)]
    if not toks:
        return {"match_ratio": 0.0, "lines": []}
    rec = [r for r in recognised if norm(r["w"])]
    sm = difflib.SequenceMatcher(a=[norm(w) for _, w in toks], b=[norm(r["w"]) for r in rec], autojunk=False)
    times = [None] * len(toks)
    matched = 0
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            times[a + k] = (rec[b + k]["s"], rec[b + k]["e"])
            matched += 1
    ratio = matched / len(toks)
    # interpolate gaps between known anchors
    known = [i for i, t in enumerate(times) if t]
    if not known:  # nothing recognised: spread lines evenly over the vocal part of the song
        start, end = duration * 0.06, duration * 0.94
        step = (end - start) / len(toks)
        times = [(start + i * step, start + (i + 1) * step) for i in range(len(toks))]
    else:
        for i in range(len(toks)):
            if times[i]:
                continue
            prev = max([k for k in known if k < i], default=None)
            nxt = min([k for k in known if k > i], default=None)
            if prev is None:
                t0 = max(0.0, times[nxt][0] - 0.35 * (nxt - i))
                times[i] = (t0, t0 + 0.3)
            elif nxt is None:
                t0 = min(duration - 0.3, times[prev][1] + 0.35 * (i - prev))
                times[i] = (t0, t0 + 0.3)
            else:
                a0, b0 = times[prev][1], times[nxt][0]
                frac = (i - prev) / (nxt - prev)
                t0 = a0 + (b0 - a0) * frac
                times[i] = (t0, t0 + max(0.12, (b0 - a0) / (nxt - prev)))
    out = []
    for li, text in enumerate(lines):
        ws = [(w, *times[k]) for k, (l, w) in enumerate(toks) if l == li]
        if ws:
            out.append({"text": text, "start": round(ws[0][1], 2), "end": round(ws[-1][2], 2),
                        "words": [(w, round(s, 2), round(e, 2)) for w, s, e in ws]})
    # enforce monotonic line starts
    for i in range(1, len(out)):
        if out[i]["start"] < out[i - 1]["start"]:
            out[i]["start"] = out[i - 1]["start"] + 0.05
    return {"match_ratio": round(ratio, 3), "lines": out}


def transcribe_cpu(path, model="small") -> list[dict]:
    """Fallback when the GPU runner did not provide word timings (needs `pip install faster-whisper`)."""
    from faster_whisper import WhisperModel
    wm = WhisperModel(model, device="cpu", compute_type="int8")
    segs, _ = wm.transcribe(_pcm16k(path), language="en", word_timestamps=True)
    return [{"w": w.word.strip(), "s": w.start, "e": w.end, "p": w.probability} for s in segs for w in (s.words or [])]


def _pcm16k(path):
    """Decode with ffmpeg (avoids PyAV version clashes like 'unexpected keyword metadata_errors')."""
    import subprocess
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(path), "-f", "s16le", "-ac", "1",
                          "-ar", "16000", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
