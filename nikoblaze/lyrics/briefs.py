"""Unique creative briefs. A fingerprint of the musical/story choices is stored so they are not reused."""
import hashlib
import json
import random

from .. import db
from ..config import cfg
from ..departments import ARCS, DEPARTMENTS, KEYS, PERSPECTIVES, SETTINGS_PLACES

STRUCTURES = {
    "vocal": [
        ["Intro", "Verse 1", "Pre-Chorus", "Chorus", "Verse 2", "Pre-Chorus", "Chorus", "Bridge", "Chorus", "Outro"],
        ["Intro", "Chorus", "Verse 1", "Chorus", "Verse 2", "Bridge", "Chorus", "Outro"],
        ["Intro", "Verse 1", "Chorus", "Verse 2", "Chorus", "Bridge", "Chorus", "Outro"],
    ],
    "instrumental": [["Intro", "Theme A", "Theme B", "Theme A variation", "Outro"]],
}


def _fingerprint(b: dict) -> str:
    key = [b["department"], b["subgenre"], b["theme"], b.get("setting"), b["keyscale"], b["bpm"] // 4]
    return hashlib.sha1(json.dumps(key).encode()).hexdigest()[:16]


def _recent_fingerprints(days: int = 120) -> set:
    rows = db.get().execute(
        "SELECT fingerprint FROM songs WHERE created_at >= datetime('now', ?)", (f"-{days} days",)).fetchall()
    return {r["fingerprint"] for r in rows}


def _recent_themes(department: str, n: int = 12) -> list:
    rows = db.get().execute("SELECT brief_json FROM songs WHERE department=? ORDER BY created_at DESC LIMIT ?",
                            (department, n)).fetchall()
    return [json.loads(r["brief_json"]).get("theme") for r in rows if r["brief_json"]]


_SPEC_FOR = {"amapiano": "south_african_amapiano", "afrobeats": "nigerian_afrobeats", "roots reggae": "jamaican_reggae",
             "conscious reggae": "jamaican_reggae", "lovers rock": "jamaican_reggae", "reggae": "jamaican_reggae"}


def style_spec(subgenre: str | None) -> dict | None:
    """Producer style specs (config/style_specs.yaml): genre-true captions, tempo, keys, vocals, hook rules."""
    import yaml
    from pathlib import Path
    key = _SPEC_FOR.get((subgenre or "").lower())
    p = Path(__file__).resolve().parents[2] / "config" / "style_specs.yaml"
    if not key or not p.exists():
        return None
    return (yaml.safe_load(p.read_text()) or {}).get(key)


def _apply_spec(b: dict, rng: random.Random) -> dict:
    spec = style_spec(b["subgenre"])
    if not spec or b["instrumental"]:
        return b
    b["spec_caption"] = rng.choice(spec["captions"])
    b["bpm"] = rng.randint(*spec["bpm_range"])
    b["keyscale"] = rng.choice(spec["best_keys"])
    b["vocal_style"] = rng.choice(spec["vocal_style"])
    b["theme"] = rng.choice(spec["lyric_themes"])
    b["hook_rules"] = spec.get("hook_rules", "")
    return b


def make_brief(department: str, rng: random.Random, subgenre: str | None = None) -> dict:
    d = DEPARTMENTS[department]
    used = _recent_fingerprints()
    avoid_themes = set(_recent_themes(department))
    dur = cfg(f"durations.{department}")
    for _ in range(200):
        off = set(cfg("generation.disabled_subgenres", []) or [])
        sg = subgenre or rng.choice([k for k in d["subgenres"] if k not in off] or list(d["subgenres"]))
        prof = d["subgenres"][sg]
        themes = [t for t in d["themes"] if t not in avoid_themes] or d["themes"]
        instrumental = department == "relaxation"
        b = {
            "department": department,
            "subgenre": sg,
            "theme": rng.choice(themes),
            "setting": None if instrumental else rng.choice(SETTINGS_PLACES),
            "perspective": None if instrumental else rng.choice(PERSPECTIVES),
            "arc": None if instrumental else rng.choice(ARCS),
            "bpm": rng.randint(*prof["bpm"]),
            "keyscale": rng.choice(KEYS),
            "palette": rng.choice(prof["palette"]),
            "vocal_style": None if instrumental else rng.choice(d["vocal"]),
            "harmony": d["harmony"],
            "structure": rng.choice(STRUCTURES["instrumental" if instrumental else "vocal"]),
            "duration": rng.randint(dur["min"] + 10, dur["max"] - 5),
            "instrumental": instrumental,
        }
        b = _apply_spec(b, rng)
        b["fingerprint"] = _fingerprint(b)
        if b["fingerprint"] not in used:
            return b
    raise RuntimeError(f"Could not find an unused brief for {department}; widen themes in departments.py")


_DARK = {"light tape warmth": "clear and present", "subtle vinyl texture": "crisp detail",
         "long reverb": "airy reverb", "soft string pads": "shimmering string pads",
         "distant piano notes": "clear bell-like piano notes", "warm room": "natural room, clear highs"}


# Strong genre tags first: ACE-Step weighs the start of the prompt most. "not jazz" style negatives don't work,
# so the anchors name the defining rhythm instead.
GENRE_ANCHOR = {
    "afrobeats": "nigerian afrobeats, lagos afropop groove, syncopated west african percussion, talking drum, danceable",
    "amapiano": "amapiano, south african deep house, four-on-the-floor kick, log drum bass lead, 112 bpm, shakers, house piano chords, club dancefloor",
    "reggae": "reggae, one drop rhythm, offbeat skank guitar, jamaican",
    "roots reggae": "roots reggae, one drop rhythm, offbeat skank guitar, jamaican",
    "lovers rock": "lovers rock reggae, offbeat skank guitar, one drop rhythm",
    "conscious reggae": "conscious roots reggae, one drop rhythm, offbeat skank guitar, jamaican",
    "dancehall": "dancehall, jamaican riddim, digital drums",
}


def caption_for(b: dict) -> str:
    """ACE-Step style prompt (max 512 chars). Words that make the model sound muffled are swapped out."""
    b = dict(b)
    for k, v in _DARK.items():
        b["palette"] = (b.get("palette") or "").replace(k, v)
    if b["instrumental"]:
        parts = [b["subgenre"] + " music", b["palette"], f"evokes {b['theme']}", "no vocals",
                 "calm, spacious, crisp high fidelity studio recording, bright upper-register melody, sparkling clear treble, airy, not muddy, natural dynamics"]
    else:
        anchor = GENRE_ANCHOR.get(b["subgenre"], b["subgenre"])
        spec = style_spec(b["subgenre"])
        if spec:  # producer spec: anchor first (model weighs the start most), then one full genre caption
            cap = b.get("spec_caption") or spec["captions"][0]
            import re
            anchor = re.sub(r",?\s*\d+\s*BPM", "", spec["anchor"])  # real tempo goes in the bpm field
            out = ", ".join([anchor, cap, "clear English vocals"])
            return out if len(out) <= 512 else out[:512].rsplit(",", 1)[0]
        if b["subgenre"] == "amapiano":  # soul/afrobeat words pulled takes off-genre; keep it a club record
            return ", ".join([anchor, "afro amapiano club anthem, deep rolling log drums, heavy sub bass, punchy bouncy amapiano groove, hypnotic bounce, rhythmic chant-style male vocals, call-and-response chant hook, playful confident energetic, nightlife, clear English, punchy club mix, amapiano"])[:512]
        parts = [anchor, "driving danceable groove, punchy kick, tight crisp drums", b["palette"],
                 "natural expressive human vocals, warm breathy real singer, not robotic, no autotune",
                 b["vocal_style"], b["harmony"], f"mood: {b['arc']}",
                 "clear English pronunciation, catchy memorable chorus, professional mix, strong clean bass"]
    return ", ".join(p for p in parts if p)[:512]
