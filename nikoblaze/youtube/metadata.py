"""Titles, descriptions, tags and chapters within YouTube limits."""
from ..departments import DEPARTMENTS
from ..lyrics.quality import sung_lines

DISCLOSURE = ("Production note: this track was created by the Niko Blaze project using AI-assisted tools "
              "(ACE-Step 1.5 open-source music model; AI-assisted lyric drafting), then quality-checked "
              "and mastered. Marked as altered/synthetic content on YouTube.")

TAGS = {  # YouTube allows ~500 chars of tags: use them (artist, genre, search phrases, moods, year)
    "afrobeats": ["Niko Blaze", "Niko Blaze new song", "Afrobeats", "Afrobeats 2026", "new afrobeats 2026",
                  "afrobeats songs", "afrobeats mix", "naija music", "nigerian music", "afropop", "afro pop",
                  "afro love song", "african music", "african love songs", "afro dance", "afrobeats dance",
                  "east african music", "kampala music", "lagos vibes", "afro vibes", "new music 2026",
                  "latest afrobeats", "afrobeats playlist", "chill afrobeats", "afro fusion", "official audio"],
    "amapiano": ["Niko Blaze", "Amapiano", "Amapiano 2026", "new amapiano 2026", "amapiano mix", "amapiano songs",
                 "south african music", "log drum", "private school piano", "amapiano dance", "afro house",
                 "amapiano vibes", "amapiano playlist", "african music", "new music 2026", "official audio"],
    "reggae": ["Niko Blaze", "Reggae", "Reggae 2026", "new reggae 2026", "reggae music", "reggae songs",
               "reggae mix", "roots reggae", "lovers rock", "conscious reggae", "one drop reggae", "reggae love songs",
               "reggae playlist", "chill reggae", "reggae vibes", "jamaican music", "african reggae",
               "reggae live", "new music 2026", "official audio"],
    "relaxation": ["Niko Blaze", "Relaxing music", "Study music", "Sleep music", "Meditation music", "Calm piano",
                   "relaxing piano", "focus music", "deep sleep music", "lofi", "stress relief music",
                   "ambient music", "peaceful music", "1 hour relaxing music", "music for studying"],
}

HASHTAGS = {"afrobeats": "#Afrobeats #Afrobeats2026 #NaijaMusic #AfroPop #NewMusic",
            "amapiano": "#Amapiano #Amapiano2026 #LogDrum #AfroHouse #NewMusic",
            "reggae": "#Reggae #Reggae2026 #RootsReggae #LoversRock #NewMusic",
            "relaxation": "#RelaxingMusic #StudyMusic #SleepMusic #Calm"}


def clean(s: str) -> str:
    return s.replace("<", "").replace(">", "").strip()


def _tags(dept, extra=()):
    out, total = [], 0
    for t in [*TAGS[dept], *extra]:
        t = clean(t)[:30]
        if t and t.lower() not in [o.lower() for o in out] and total + len(t) + 3 <= 490:
            out.append(t)
            total += len(t) + 3  # YouTube counts quotes around multi-word tags
    return out


def single(song: dict) -> dict:
    title = clean(f"Niko Blaze - {song['title']} ({song['subgenre'].title()})")[:100]
    lyric_text = "\n".join(sung_lines(song["lyrics"]))
    sg = song["subgenre"].lower()
    key = sg if sg in TAGS else ("reggae" if "reggae" in sg or "lovers" in sg else "afrobeats")
    desc = (f"🎧 Niko Blaze – \"{song['title']}\" | New {song['subgenre'].title()} 2026 (Official Audio)\n\n"
            f"{song['title']} is a brand-new {song['subgenre']} song by Niko Blaze. "
            f"{song.get('concept') or ''}\n\n"
            f"🔔 Subscribe for a new song every week and a 1-hour live mix every Saturday 20:00 (Kigali).\n"
            f"👍 Like, comment your favourite line and share it with someone who needs this vibe.\n\n"
            f"LYRICS\n{lyric_text}\n\n"
            f"{HASHTAGS[key]} #NikoBlaze")
    return {"title": title, "description": clean(desc)[:4900],
            "tags": _tags(key, [song["title"], f"{song['title']} Niko Blaze", song["subgenre"]])}


def _ts(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


def mix(dept: str, volume: int, chapters: list[tuple[float, str]]) -> dict:
    label = DEPARTMENTS[dept]["label"]
    title = clean(f"1 Hour {label} Mix (Pre-recorded) - Niko Blaze | Vol. {volume}")[:100]
    lines = "\n".join(f"{_ts(t)} {clean(name)}" for t, name in chapters)
    desc = (f"A pre-recorded one-hour {label.lower()} mix of original Niko Blaze music. "
            f"This is not a live broadcast.\n\nTRACKLIST\n{lines}\n\n{HASHTAGS.get(dept, '')} #NikoBlaze")
    return {"title": title, "description": clean(desc)[:4900], "tags": _tags(dept, ["1 hour mix"])}


def short(song: dict) -> dict:
    title = clean(f"{song['title']} - Niko Blaze #Shorts")[:100]
    desc = (f"From the new Niko Blaze {song['subgenre']} song \"{song['title']}\". Full song on the channel.\n\n"
            f"#Shorts #NikoBlaze #{song['subgenre'].replace(' ', '')}")
    return {"title": title, "description": clean(desc)[:4900], "tags": _tags("afrobeats", ["shorts"])}


LIVE_TITLES = {
    "reggae": "🔴 Reggae Saturday LIVE – 1 Hour of Feel-Good Roots Vibes | Niko Blaze",
    "afrobeats": "🔴 Afrobeats & Amapiano LIVE – 1 Hour Non-Stop Party Mix 🔥 | Niko Blaze",
    "relaxation": "🔴 1 Hour Calm Piano LIVE – Relax, Study & Sleep | Niko Blaze",
}


LIVE_ABOUT = {
    "reggae": ("feel-good roots reggae, lovers rock and conscious one drop vibes", "If you love reggae music",
               "#Reggae #ReggaeMusic #ReggaeLive #RootsReggae #ReggaeMix #LoversRock #ReggaeVibes #Reggae2026"),
    "afrobeats": ("afrobeats, afropop and afro-fusion grooves", "If you love afrobeats",
                  "#Afrobeats #AfrobeatsLive #AfrobeatsMix #Afropop #NaijaMusic #AfricanMusic #Afrobeats2026"),
    "relaxation": ("calm, peaceful relaxing music", "If you love calm music",
                   "#RelaxingMusic #StudyMusic #SleepMusic #CalmMusic #RelaxingLive #ChillMusic"),
}


def live(dept: str, volume: int, chapters: list) -> dict:
    """Title/description/tags for the Saturday live stream of the weekly mix (SEO: many relevant tags/hashtags)."""
    label = DEPARTMENTS[dept]["label"]
    title = LIVE_TITLES.get(dept, f"🔴 {label} LIVE – 1 Hour Mix | Niko Blaze")[:100]
    about, love, tags_line = LIVE_ABOUT.get(dept, (label.lower(), "If you love this music", HASHTAGS.get(dept, "")))
    lines = "\n".join(clean(name) for _, name in chapters)
    g = {"reggae": "reggae", "afrobeats": "afrobeats", "relaxation": "relaxing"}.get(dept, dept)
    desc = (f"🔴 LIVE NOW: 1 hour of non-stop {about} by Niko Blaze (Vol. {volume}).\n"
            f"{love}, SUBSCRIBE 🔔 and turn on notifications — a new live mix every Saturday 20:00 (Kigali) "
            f"and a new single every Friday.\n\n"
            f"Perfect for relaxing, working, studying, driving, cooking or chilling with friends. "
            f"Say hi in the chat and tell us where you're listening from! 🌍\n\n"
            f"TRACKLIST\n{lines}\n\n"
            f"👍 Like and share this live with someone who loves {g} music.\n\n"
            f"{tags_line} #NikoBlaze #LiveMusic #1HourMix")
    extra = [f"{g} live", f"{g} live stream", f"1 hour {g} mix", f"{g} mix 2026", f"non stop {g}",
             "live music", "1 hour mix", "live"]
    return {"title": title, "description": clean(desc)[:4900], "tags": _tags(dept, extra)}
