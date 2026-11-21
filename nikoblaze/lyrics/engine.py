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
The title must be a real, memorable song title of 1-5 words (usually the hook's key phrase), never a cut-off
lyric line, no commas.
Return ONLY JSON: {"title": str, "concept": str (one sentence), "hook": str, "lyrics": str}
where lyrics uses section tags on their own lines like [Verse 1], [Pre-Chorus], [Chorus], [Bridge], [Outro]."""


def _history(department: str, n: int = 60):
    rows = db.get().execute(
        "SELECT title, lyrics FROM songs WHERE lyrics IS NOT NULL AND lyrics != '' ORDER BY created_at DESC LIMIT ?",
        (n,)).fetchall()
    return [(r["title"], r["lyrics"]) for r in rows]


def _extend(lyrics: str) -> str:
    """Add a final chorus (and outro repeat) when a song is a little short."""
    m = re.search(r"(?ims)^\s*\[chorus[^\]]*\]\s*\n(.*?)(?=^\s*\[|\Z)", lyrics)
    if not m:
        return lyrics
    chorus = m.group(1).strip()
    out = lyrics.rstrip() + "\n\n[Chorus]\n" + chorus
    if len([l for l in out.splitlines() if l.strip() and not l.strip().startswith("[")]) < 20:
        out += "\n\n[Outro]\n" + chorus
    return out


def retitle(lyrics: str) -> str:
    """Ask a free LLM for a proper short song title (used when the given one is missing or a lyric fragment)."""
    msgs = [{"role": "user", "content": "Give one original, memorable song title (1-5 words, no commas, not a "
             "cut-off lyric line) for these lyrics. Reply with the title only.\n\n" + lyrics[:3000]}]
    for _ in range(3):
        try:
            t, _p = llm.chat(msgs, temperature=0.7)
        except Exception:
            break
        t = re.sub(r'[<>"*#]', "", (t or "").strip().splitlines()[0] if t and t.strip() else "").strip(" .")
        if t and not quality.title_issues(t, lyrics):
            return t[:70]
    hook = re.search(r"(?im)^\s*\[chorus[^\]]*\]\s*\n\s*([^\n\[]+)", lyrics)
    words = (hook.group(1) if hook else "Untitled").replace(",", " ").split()
    return " ".join(w for w in words[:3]).strip(".!?") or "Untitled"


def _parse(text: str) -> dict:
    """Tolerant: handles code fences, <think> blocks, raw newlines inside strings, and plain-text lyrics."""
    text = (text or "").strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    text = re.sub(r"```(?:json)?", "", text, flags=re.I).strip()
    data = None
    a, b = text.find("{"), text.rfind("}")
    if a != -1 and b > a:
        blob = text[a:b + 1]
        for attempt in (blob, re.sub(r",\s*([}\]])", r"\1", blob)):
            try:
                data = json.loads(attempt, strict=False)
                break
            except Exception:
                continue
    if data is None and re.search(r"^\s*\[(verse|chorus|intro|hook)", text, re.I | re.M):
        t = re.search(r"(?im)^\s*\**\s*title\s*\**\s*[:\-]\s*\**\s*\"?([^\"\n*]+)", text)
        start = re.search(r"(?im)^\s*\[(verse|chorus|intro|hook)", text).start()
        data = {"title": t.group(1).strip() if t else "", "lyrics": text[start:].strip()}
        if not data["title"]:
            hook = re.search(r"(?im)^\s*\[chorus[^\]]*\]\s*\n\s*([^\n\[]+)", text)
            data["title"] = ""  # filled by retitle()
    if not isinstance(data, dict):
        raise ValueError("model did not return JSON")
    if isinstance(data.get("lyrics"), list):
        data["lyrics"] = "\n".join(map(str, data["lyrics"]))
    if not data.get("title"):
        data["title"] = retitle(data.get("lyrics") or "")
    for k in ("title", "lyrics"):
        if not data.get(k) or not isinstance(data[k], str):
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
    lines_target = max(24, int(brief["duration"] / 4.2))
    user = (f"Brief:\n{json.dumps({k: brief[k] for k in ('subgenre', 'theme', 'setting', 'perspective', 'arc', 'bpm', 'structure')}, indent=1)}\n"
            f"Write at least {lines_target} sung lines in total (section tags do not count) for a "
            f"{brief['duration']}s song. Each verse needs 8 lines, each chorus 4-6 lines. "
            f"Use exactly these sections in order: {', '.join(brief['structure'])}.\n"
            f"Do not reuse these titles: {recent_titles or 'none yet'}.")
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    last_issues, bad_providers = [], set()
    for attempt in range(int(cfg("lyrics.max_rewrites", 3)) + 3):
        text, provider = llm.chat(messages, skip=bad_providers)
        try:
            data = _parse(text)
        except Exception as e:
            last_issues = [f"invalid output from {provider}: {e}"]
            db.log("warn", "lyrics", f"{provider} returned unusable output: {(text or '')[:200]!r}")
            bad_providers.add(provider)  # next attempt goes to the next free provider
            continue
        issues = quality.check(data["lyrics"], data["title"], history, cfg("lyrics.history_similarity_max", 0.18))
        if issues == ["too few lines for a full song"]:  # repeat the chorus at the end, as real songs do
            data["lyrics"] = _extend(data["lyrics"])
            issues = quality.check(data["lyrics"], data["title"], history, cfg("lyrics.history_similarity_max", 0.18))
        if not issues:
            data["provider"] = provider
            return data
        last_issues = issues
        if attempt >= 1:
            bad_providers.add(provider)  # this model keeps missing; let the next free model try
        messages += [{"role": "assistant", "content": text[:6000]},
                     {"role": "user", "content": "Rewrite the whole song fixing: " + "; ".join(issues) +
                      ". Return ONLY the JSON object."}]
    raise ValueError("lyrics failed quality checks: " + "; ".join(last_issues))
