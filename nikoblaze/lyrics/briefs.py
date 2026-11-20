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


def make_brief(department: str, rng: random.Random, subgenre: str | None = None) -> dict:
    d = DEPARTMENTS[department]
    used = _recent_fingerprints()
    avoid_themes = set(_recent_themes(department))
    dur = cfg(f"durations.{department}")
    for _ in range(200):
        sg = subgenre or rng.choice(list(d["subgenres"]))
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
        b["fingerprint"] = _fingerprint(b)
        if b["fingerprint"] not in used:
            return b
    raise RuntimeError(f"Could not find an unused brief for {department}; widen themes in departments.py")


_DARK = {"light tape warmth": "clear and present", "subtle vinyl texture": "crisp detail",
         "long reverb": "airy reverb", "soft string pads": "shimmering string pads",
         "distant piano notes": "clear bell-like piano notes", "warm room": "natural room, clear highs"}


def caption_for(b: dict) -> str:
    """ACE-Step style prompt (max 512 chars). Words that make the model sound muffled are swapped out."""
    b = dict(b)
    for k, v in _DARK.items():
        b["palette"] = (b.get("palette") or "").replace(k, v)
    if b["instrumental"]:
        parts = [b["subgenre"] + " music", b["palette"], f"evokes {b['theme']}", "no vocals",
                 "calm, spacious, crisp high fidelity studio recording, clear detailed highs, airy, natural dynamics"]
    else:
        parts = [b["subgenre"], b["palette"], b["vocal_style"], b["harmony"], f"mood: {b['arc']}",
                 "clear English pronunciation, catchy memorable chorus, professional mix, strong clean bass, warm"]
    return ", ".join(p for p in parts if p)[:512]
