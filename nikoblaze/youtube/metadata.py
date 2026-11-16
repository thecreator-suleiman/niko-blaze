"""Titles, descriptions, tags and chapters within YouTube limits."""
from ..departments import DEPARTMENTS
from ..lyrics.quality import sung_lines

DISCLOSURE = ("Production note: this track was created by the Niko Blaze project using AI-assisted tools "
              "(ACE-Step 1.5 open-source music model; AI-assisted lyric drafting), then quality-checked "
              "and mastered. Marked as altered/synthetic content on YouTube.")

TAGS = {
    "afrobeats": ["Niko Blaze", "Afrobeats", "Amapiano", "African music", "afro love song", "new afrobeats"],
    "reggae": ["Niko Blaze", "Reggae", "Roots reggae", "Lovers rock", "Conscious reggae", "reggae storytelling"],
    "relaxation": ["Niko Blaze", "Relaxing music", "Study music", "Sleep music", "Meditation music", "Calm piano"],
}


def clean(s: str) -> str:
    return s.replace("<", "").replace(">", "").strip()


def _tags(dept, extra=()):
    out, total = [], 0
    for t in [*TAGS[dept], *extra]:
        t = clean(t)[:30]
        if t and t not in out and total + len(t) + 1 <= 450:
            out.append(t)
            total += len(t) + 1
    return out


def single(song: dict) -> dict:
    title = clean(f"Niko Blaze - {song['title']} ({song['subgenre'].title()})")[:100]
    lyric_text = "\n".join(sung_lines(song["lyrics"]))
    desc = (f"{song['title']} — an original {song['subgenre']} story by Niko Blaze.\n\n"
            f"Story: {song.get('concept') or ''}\n\nLYRICS\n{lyric_text}\n\n{DISCLOSURE}\n\n"
            f"#NikoBlaze #{song['subgenre'].replace(' ', '')} #AfricanMusic")
    return {"title": title, "description": clean(desc)[:4900], "tags": _tags("afrobeats", [song["subgenre"]])}


def _ts(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


def mix(dept: str, volume: int, chapters: list[tuple[float, str]]) -> dict:
    label = DEPARTMENTS[dept]["label"]
    title = clean(f"1 Hour {label} Mix (Pre-recorded) - Niko Blaze | Vol. {volume}")[:100]
    lines = "\n".join(f"{_ts(t)} {clean(name)}" for t, name in chapters)
    desc = (f"A pre-recorded one-hour {label.lower()} mix of original Niko Blaze music. "
            f"This is not a live broadcast.\n\nTRACKLIST\n{lines}\n\n{DISCLOSURE}\n\n#NikoBlaze")
    return {"title": title, "description": clean(desc)[:4900], "tags": _tags(dept, ["1 hour mix"])}
