"""Quality control: score each generated take; hard failures are never published."""
from ..config import cfg


def score_take(m: dict, department: str, instrumental: bool, match_ratio: float | None,
               recognised_words: int = 0) -> dict:
    hard, warn, score = [], [], 100.0
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
