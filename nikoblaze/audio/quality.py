"""Quality control: score each generated take; hard failures are never published."""
import re
from ..config import cfg


# AudioSet genre labels accepted per department (amapiano usually reads as House / Music of Africa).
GENRE_OK = {"afrobeats": {"Afrobeat", "Music of Africa", "House music", "Dance music", "Electronic dance music",
                          "Pop music", "Hip hop music", "Reggae", "Rhythm and blues", "Electronic music", "Disco"},
            "reggae": {"Reggae", "Ska", "Dubstep"},
            "relaxation": {"Ambient music", "New-age music", "Classical music", "Piano", "Lounge music",
                           "Electric piano"}}


_HALLU = re.compile(r"thank(s| you)|for watching|for listening|subscribe|like and|see you|bye|music|"
                    r"amara|subtitles|copyright|\d+", re.I)


def sung_words(words: list | None) -> int:
    """Count words that are really sung. Whisper hallucinates on quiet music ("Thank you. Thank you...",
    numbered lists); those are low-confidence, repetitive or stock phrases and are not vocals."""
    if not words:
        return 0
    keep = []
    for w in words:
        t = (w.get("w") if isinstance(w, dict) else str(w)) or ""
        p = w.get("p", 1.0) if isinstance(w, dict) else 1.0
        t = re.sub(r"[^a-z']", "", t.lower())
        if t and p >= 0.5 and not _HALLU.search(t):
            keep.append(t)
    if len(set(keep)) < 6:  # a loop of the same few words is a hallucination, not a vocal line
        return 0
    return len(keep)


def hit_score(hook: float | None, groove: float | None, match_ratio: float | None, words: list | None,
              production: float) -> dict:
    """Hit potential 0-100 (an estimate, not a real probability): hook strength (A&R rating of the lyrics),
    groove (beat strength), natural/clear vocals (how clearly the sung words are understood) and production."""
    def c(v):
        return max(0.0, min(1.0, v))
    hook_p = c(((hook or 6) - 4) / 5)                       # 9-10/10 -> full marks
    groove_p = c(((groove or 0.25) - 0.2) / 0.2)            # 0.40+ -> full marks
    probs = [w.get("p", 0.0) for w in (words or []) if isinstance(w, dict)]
    clarity = c(((match_ratio or 0) - 0.3) / 0.4) * 0.6 + c(((sum(probs) / len(probs)) if probs else 0.5) - 0.45) / 0.4 * 0.4
    parts = {"hook": round(35 * hook_p, 1), "groove": round(25 * groove_p, 1), "vocals": round(25 * c(clarity), 1),
             "production": round(15 * c(production / 100), 1)}
    return {"score": round(sum(parts.values())), "parts": parts}


def genre_issue(department: str, genres: list | None) -> str | None:
    """genres = top-5 [label, prob] from the CLAP listener. Fail only if none of the department's
    genres is in the top 3 — the song must actually sound like what its title and labels say."""
    ok = GENRE_OK.get(department)
    if not ok or not genres:
        return None
    if any(g in ok for g, _ in genres[:3]):
        return None
    return f"wrong genre: sounds like {genres[0][0]} (expected {', '.join(sorted(ok))})"


def score_take(m: dict, department: str, instrumental: bool, match_ratio: float | None,
               recognised_words: int = 0, genres: list | None = None) -> dict:
    hard, warn, score = [], [], 100.0
    gi = genre_issue(department, genres)
    if gi and cfg("quality.genre_check", True):
        hard.append(gi)
    q = cfg("quality")
    dur = cfg(f"durations.{department}")
    if m.get("nan"):
        return {"score": 0, "passed": False, "hard": ["audio contains NaN/inf"], "warnings": []}
    if not (dur["min"] - 15 <= m["duration"] <= dur["max"] + 5):
        hard.append(f"duration {m['duration']:.0f}s outside {dur['min']}-{dur['max']}s")
    if not instrumental and m["duration"] > cfg("durations.single_hard_max", 240) + 5:
        hard.append("song longer than 4:00")
    if m["silence_ratio"] > 0.2:
        hard.append(f"too much silence ({m['silence_ratio']:.0%})")
    if m["max_inner_silence_s"] > 2.5:
        hard.append(f"dropout of {m['max_inner_silence_s']:.1f}s mid-song")
    if m["clip_runs"] > 200 or m["clip_ratio"] > 1e-3:
        hard.append("heavy digital clipping (cannot be repaired by mastering)")
    elif m["clip_runs"] > 20:
        score -= 15; warn.append("some clipping")
    if m["dc_offset"] > 0.01:
        score -= 5; warn.append("DC offset (removed in mastering)")
    if m["channels"] > 1:
        if m["stereo_corr"] < -0.3:
            hard.append("stereo phase problem (mono incompatible)")
        elif m["stereo_corr"] < 0:
            score -= 15; warn.append("weak mono compatibility")
    # Muffled check, genre-aware: soft piano/ambient is naturally dark, pop/reggae is not.
    # hf_db = share of energy above 4 kHz in dB (pop mix ~ -12, soft piano ~ -22, broken/muffled < -40).
    relax = department == "relaxation"
    hard_db, warn_db = (q.get("hf_db_hard_relax", -42), q.get("hf_db_warn_relax", -32)) if relax else \
                       (q.get("hf_db_hard", -30), q.get("hf_db_warn", -22))
    hfdb = m.get("hf_db")
    if hfdb is None:  # old metrics without hf_db: fall back to rolloff
        hfdb = 0.0 if m.get("rolloff_99_hz", 20000) >= (3000 if relax else 8000) else hard_db - 1
    if hfdb < hard_db:
        hard.append(f"muffled/band-limited audio (energy above 4 kHz {hfdb:.0f} dB)")
    elif hfdb < warn_db:
        score -= 15; warn.append("dull top end")
    flat = m.get("spectral_flatness", 0)
    if flat > 0.5:
        hard.append("noise-like spectrum (hiss/static)")
    elif flat > 0.35:
        score -= 20; warn.append("noisy texture")
    bands = m.get("bands", {})
    low = bands.get("sub", 0) + bands.get("bass", 0)
    if department in ("reggae", "afrobeats") and low < 0.12:
        score -= 15; warn.append("weak bass for the genre")
    if low > 0.75:
        score -= 10; warn.append("boomy / unbalanced low end")
    if m.get("lra") is not None and m["lra"] < 2 and department != "relaxation":
        score -= 10; warn.append("over-compressed source (LRA < 2 LU)")
    if instrumental:
        if recognised_words > q["instrumental_max_words"]:
            score -= 25; warn.append(f"vocals detected in an instrumental ({recognised_words} words)")
    elif match_ratio is None:
        score -= 20; warn.append("lyric intelligibility not measured")
    elif match_ratio < q["vocal_min_lyric_match"]:
        hard.append(f"lyrics unintelligible / wrong words (match {match_ratio:.0%})")
    elif match_ratio < q["vocal_good_lyric_match"]:
        score -= 15; warn.append(f"pronunciation only partly clear (match {match_ratio:.0%})")
    score = max(0.0, score)
    return {"score": round(score, 1), "passed": not hard and score >= q["min_score"], "hard": hard, "warnings": warn}


def check_master(m: dict, target: dict) -> list[str]:
    """Post-mastering technical checks."""
    issues = []
    if m["sample_rate"] not in (44100, 48000):
        issues.append(f"sample rate {m['sample_rate']}")
    if m["subtype"] != "PCM_24":
        issues.append(f"bit depth {m['subtype']} (expected 24-bit)")
    if m["channels"] != 2:
        issues.append("not stereo")
    if m.get("true_peak") is not None and m["true_peak"] > target["true_peak"] + 0.3:
        issues.append(f"true peak {m['true_peak']} dBTP above {target['true_peak']}")
    if m.get("lufs") is not None and abs(m["lufs"] - target["lufs"]) > 1.5:
        issues.append(f"loudness {m['lufs']} LUFS off target {target['lufs']}")
    if m["clip_runs"] > 0:
        issues.append("clipping after mastering")
    return issues
