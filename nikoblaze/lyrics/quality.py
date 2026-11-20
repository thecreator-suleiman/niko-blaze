"""Lyric checks: AI clichés, repetition, structure, and similarity to the song history."""
import re

BANNED = [
    "neon", "tapestry", "symphony", "echoes of", "whispers of", "in the depths", "shattered dreams",
    "ignite", "soar", "embrace the", "journey of", "testament", "kaleidoscope", "unbreakable bond",
    "dance of life", "heart and soul", "set my soul on fire", "against all odds", "reach for the stars",
    "ethereal", "celestial", "enchanted", "realm", "boundless", "uncharted", "beacon", "labyrinth",
    "melody of my heart", "rhythm of my heart", "in this moment", "we rise", "light the way",
]
TAG = re.compile(r"^\s*\[([^\]]+)\]\s*$")


def parse_sections(lyrics: str) -> list[tuple[str, list[str]]]:
    sections, cur, lines = [], "Untitled", []
    for raw in lyrics.splitlines():
        m = TAG.match(raw)
        if m:
            if lines:
                sections.append((cur, lines))
            cur, lines = m.group(1).strip(), []
        elif raw.strip():
            lines.append(raw.strip())
    if lines:
        sections.append((cur, lines))
    return sections


def sung_lines(lyrics: str) -> list[str]:
    return [l for _, ls in parse_sections(lyrics) for l in ls if not (l.startswith("(") and l.endswith(")"))]


def words(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z']+", text.lower())


def ngrams(text: str, n=3) -> set:
    w = words(text)
    return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}


def similarity(a: str, b: str) -> float:
    A, B = ngrams(a), ngrams(b)
    return len(A & B) / max(1, len(A | B))


_DANGLING = {"to", "and", "but", "or", "the", "a", "an", "of", "in", "on", "for", "with", "my", "your", "is", "so",
             "when", "if", "at", "from", "by"}


def title_issues(title: str, lyrics: str = "") -> list[str]:
    """A real song title: 1-6 words, not a cut-off lyric line."""
    t = (title or "").strip()
    words = t.split()
    bad = []
    if not 1 <= len(words) <= 6:
        bad.append("title must be 1-6 words")
    if t[-1:] in ",;:-" or (words and words[-1].lower().strip(",.!?") in _DANGLING):
        bad.append("title looks like a cut-off lyric line; give a short real song title")
    if "," in t:
        bad.append("title must not contain commas")
    nt = re.sub(r"[^a-z0-9 ]", "", t.lower()).strip()
    for line in (lyrics or "").splitlines():
        nl = re.sub(r"[^a-z0-9 ]", "", line.lower()).strip()
        if len(nt) > 8 and nl.startswith(nt) and len(nl) > len(nt) + 2:
            bad.append("title is a cut-off lyric line")
            break
    if words and words[0].lower() in {"but", "and", "so", "or"}:
        bad.append("title must not start with a conjunction")
    return bad


def check(lyrics: str, title: str, history: list[tuple[str, str]], max_sim: float = 0.18) -> list[str]:
    """Return a list of problems (empty == acceptable). history = [(title, lyrics), ...]."""
    issues_t = title_issues(title, lyrics)
    if issues_t:
        return issues_t
    issues = []
    low = lyrics.lower()
    hits = [b for b in BANNED if b in low]
    if hits:
        issues.append(f"remove generic AI phrases: {', '.join(hits)}")
    secs = parse_sections(lyrics)
    names = " ".join(s.lower() for s, _ in secs)
    if "verse" not in names or "chorus" not in names:
        issues.append("needs at least one [Verse] and a [Chorus]")
    non_chorus = [l.lower() for s, ls in secs if "chorus" not in s.lower() for l in ls]
    if non_chorus and len(set(non_chorus)) / len(non_chorus) < 0.85:
        issues.append("verses repeat lines too much; every verse line must be new")
    lines = sung_lines(lyrics)
    long = [l for l in lines if len(words(l)) > 14]
    if long:
        issues.append(f"{len(long)} lines are too long to sing naturally (max 14 words)")
    if len(lines) < 20:
        issues.append("too few lines for a full song")
    for t, old in history:
        if t and title.strip().lower() == t.strip().lower():
            issues.append(f"title '{title}' already used")
        if old and similarity(lyrics, old) > max_sim:
            issues.append(f"too similar to earlier song '{t}'")
            break
    return issues
