"""Lyrics & storytelling engine. Writes lyrics from a brief, then self-checks and rewrites."""
import json
import re

from .. import db
from ..config import cfg
from . import llm, quality

SYSTEM = """You are the songwriter for NIKO BLAZE, an independent African male artist.
You write original, human, emotionally specific lyrics. Rules:
- Tell a concrete story: names, places, objects, small details. No vague abstractions.
- Plain conversational English that is easy to sing. You may add a few widely known words from
  Nigerian Pidgin, Swahili, Kinyarwanda or isiZulu ONLY when you are certain of the meaning and it fits the setting.
- Never copy or quote existing songs. No famous lyric lines, no artist names.
- Avoid AI cliches (neon, tapestry, symphony, ignite, soar, echoes, whispers, journey, testament, realm, beacon).
- Each verse line is new. The chorus is short, singable, and has one memorable hook phrase.
- Lines are 4-12 words. Write the FULL chorus text every time it repeats (no "repeat chorus").
- Ad-libs go in parentheses on their own line, sparingly.
Return ONLY JSON: {"title": str, "concept": str (one sentence), "hook": str, "lyrics": str}
where lyrics uses section tags on their own lines like [Verse 1], [Pre-Chorus], [Chorus], [Bridge], [Outro]."""


def _history(department: str, n: int = 60):
    rows = db.get().execute(
        "SELECT title, lyrics FROM songs WHERE lyrics IS NOT NULL AND lyrics != '' ORDER BY created_at DESC LIMIT ?",
        (n,)).fetchall()
    return [(r["title"], r["lyrics"]) for r in rows]


def _parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("model did not return JSON")
    data = json.loads(m.group(0))
    for k in ("title", "lyrics"):
        if not data.get(k):
            raise ValueError(f"missing {k}")
    data["title"] = re.sub(r"[<>\"]", "", data["title"]).strip()[:70]
    return data


def write(brief: dict) -> dict:
    """Returns {title, concept, hook, lyrics, provider}. Raises llm.NoLLMAvailable if no free LLM works."""
    if brief["instrumental"]:
        title = brief["theme"].title()
        return {"title": title, "concept": f"Instrumental: {brief['theme']}", "hook": "",
                "lyrics": "[Instrumental]", "provider": "none"}
    history = _history(brief["department"])
    recent_titles = ", ".join(t for t, _ in history[:40])
    lines_target = int(brief["duration"] / 4.2)
    user = (f"Brief:\n{json.dumps({k: brief[k] for k in ('subgenre', 'theme', 'setting', 'perspective', 'arc', 'bpm', 'structure')}, indent=1)}\n"
            f"Target about {lines_target} sung lines in total for a {brief['duration']}s song. "
            f"Use exactly these sections in order: {', '.join(brief['structure'])}.\n"
            f"Do not reuse these titles: {recent_titles or 'none yet'}.")
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    last_issues = []
    for attempt in range(int(cfg("lyrics.max_rewrites", 3)) + 1):
        text, provider = llm.chat(messages)
        try:
            data = _parse(text)
        except Exception as e:
            last_issues = [f"invalid output: {e}"]
            messages += [{"role": "assistant", "content": text[:4000]},
                         {"role": "user", "content": "Return valid JSON only, as specified."}]
            continue
        issues = quality.check(data["lyrics"], data["title"], history, cfg("lyrics.history_similarity_max", 0.18))
        if not issues:
            data["provider"] = provider
            return data
        last_issues = issues
        messages += [{"role": "assistant", "content": text[:6000]},
                     {"role": "user", "content": "Rewrite the whole song fixing: " + "; ".join(issues)}]
    raise ValueError("lyrics failed quality checks: " + "; ".join(last_issues))
