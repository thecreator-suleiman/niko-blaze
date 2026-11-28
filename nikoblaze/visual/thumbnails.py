"""Click-worthy 16:9 YouTube thumbnails (1280x720, JPEG < 2 MB).

Formula used by successful music channels: one strong story image, the artist big and cut out with a glow,
2-4 huge hook words (not the full title, which YouTube already shows), one small genre badge, high contrast.

Scene image: free AI image (Cloudflare Workers AI FLUX -> Pollinations backup), prompt + hook words written by
the free LLM chain from the song's story. If every image service fails, a procedural scene is used, so a
thumbnail is always produced (zero cost)."""
import base64
import io
import json
import os
import random
import re
import textwrap
import urllib.parse
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from . import assets
from .style import pal, font

W, H = 1280, 720
SAFE = ("photorealistic, cinematic lighting, vibrant saturated colours, high contrast, sharp focus, "
        "adults only, fully clothed, tasteful, no text, no letters, no logos, no watermark")
GENRE_LOOK = {
    "reggae": "Caribbean sunset, warm golden light, palm trees, red gold and green accents",
    "afrobeats": "Lagos night life, neon purple and orange lights, glamorous party energy",
    "amapiano": "Johannesburg rooftop party at night, purple and gold neon, dancing crowd",
    "relaxation": "calm misty nature at dawn, soft blue and teal light, peaceful",
}
LIVE_HOOK = {"reggae": ("1 HOUR", "REGGAE"), "afrobeats": ("1 HOUR", "AFROBEATS"),
             "relaxation": ("1 HOUR", "RELAX")}
YELLOW, PINK, WHITE = (255, 214, 0), (255, 70, 150), (255, 255, 255)


# ------------------------------------------------------------------ image services (free)
def _cloudflare(prompt: str) -> Image.Image | None:
    acc, tok = os.environ.get("CF_ACCOUNT_ID"), os.environ.get("CF_API_TOKEN")
    if not (acc and tok):
        return None
    r = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/@cf/black-forest-labs/flux-1-schnell",
                      headers={"Authorization": f"Bearer {tok}"}, json={"prompt": prompt[:2000], "steps": 8},
                      timeout=120)
    r.raise_for_status()
    return Image.open(io.BytesIO(base64.b64decode(r.json()["result"]["image"])))


def _pollinations(prompt: str) -> Image.Image | None:
    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt[:900]) +
           f"?width=1280&height=720&nologo=true&seed={random.randint(1, 10**6)}")
    r = requests.get(url, timeout=180)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content))


def scene_image(prompt: str) -> Image.Image | None:
    for fn in (_cloudflare, _pollinations):
        try:
            img = fn(f"{prompt}. {SAFE}")
            if img is not None and min(img.size) >= 256:
                return img.convert("RGB")
        except Exception as e:
            print(f"[WARN] thumbnail image via {fn.__name__}: {e}")
    return None


# ------------------------------------------------------------------ hook words + scene prompt (free LLM)
def plan(title: str, genre: str, concept: str | None, lyrics: str | None) -> dict:
    """{'hook': ['WORDS', 'BIG'], 'scene': 'image prompt'}; never raises."""
    fallback = {"hook": _split_hook(title), "scene": f"{GENRE_LOOK.get(genre, GENRE_LOOK['afrobeats'])}, "
                                                    f"mood of a song called '{title}'"}
    try:
        from ..lyrics import llm
        msg = (f"You design viral YouTube music thumbnails. Song: \"{title}\" ({genre}). "
               f"Story: {concept or ''}\nLyrics excerpt: {(lyrics or '')[:600]}\n\n"
               "Return ONLY JSON: {\"hook\": \"2-4 punchy English words that create curiosity and are NOT just the "
               "title (e.g. 'SHE CHOSE MAMA?', 'NEVER AGAIN', 'CAUGHT IN LOVE')\", \"scene\": \"one vivid photo "
               "description (people, place, emotion, colours) that tells the song's story at a glance; leave the "
               "right third of the frame free for the singer; no text\"}")
        text, _ = llm.chat([{"role": "user", "content": msg}], temperature=0.8)
        data = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
        hook = re.sub(r"[^A-Za-z0-9 ?!'&]", "", str(data.get("hook", ""))).upper().split()
        scene = str(data.get("scene", "")).strip()
        if 1 <= len(hook) <= 5 and len(scene) > 20:
            return {"hook": _lines(hook), "scene": f"{scene}. Style: {GENRE_LOOK.get(genre, '')}"}
    except Exception as e:
        print(f"[WARN] thumbnail plan: {e}")
    return fallback


def _lines(words: list) -> list:
    if len(words) <= 2:
        return [" ".join(words)] if sum(map(len, words)) <= 9 else words
    half = (len(words) + 1) // 2
    return [" ".join(words[:half]), " ".join(words[half:])]


def _split_hook(title: str) -> list:
    return _lines(re.sub(r"\(.*?\)", "", title).upper().split()[:4])


# ------------------------------------------------------------------ composition
def _cover(img: Image.Image) -> Image.Image:
    return ImageOps.fit(img, (W, H), Image.LANCZOS, centering=(0.4, 0.4))


def _fallback_scene(dept: str) -> Image.Image:
    try:
        from .live_scene import SCENES, _sky, _static_overlay
        sc = dict(SCENES.get(dept, SCENES["reggae"]))
        return _sky(sc).convert("RGB")
    except Exception:
        portrait, _ = assets.load_portrait()
        return assets.background(dept, (W, H), portrait=portrait).convert("RGB")


def _cutout() -> Image.Image | None:
    f = assets.ASSETS / "artist" / "cutout.png"
    return Image.open(f).convert("RGBA") if f.exists() else None


def _artist(img: Image.Image, accent, side="right", height=700):
    cut = _cutout()
    if cut is None:
        portrait, _ = assets.load_portrait()
        card = assets.portrait_card(portrait, 420, accent)
        img.alpha_composite(card, (W - 470 if side == "right" else 40, 170))
        return
    cut = cut.resize((int(cut.width * height / cut.height), height), Image.LANCZOS)
    cut = cut.crop((0, 0, cut.width, min(cut.height, H - 0)))
    x = W - cut.width + 40 if side == "right" else (W - cut.width) // 2
    y = H - cut.height + 40
    # soften the photo's straight crop edges (left side and bottom) so the singer blends into the scene
    a = cut.split()[3]
    fade = Image.new("L", cut.size, 255)
    fd = ImageDraw.Draw(fade)
    for i in range(140):
        v = int(255 * i / 140)
        fd.line((i, cut.height // 2, i, cut.height), fill=v)
    for i in range(90):
        fd.line((0, cut.height - 1 - i, cut.width, cut.height - 1 - i), fill=int(255 * i / 90))
    from PIL import ImageChops
    a = ImageChops.multiply(a, fade)
    cut.putalpha(a)
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    g = Image.new("RGBA", cut.size, (*accent, 255))
    g.putalpha(a)
    glow.alpha_composite(g, (x, y))
    glow = glow.filter(ImageFilter.GaussianBlur(18))
    img.alpha_composite(glow)
    img.alpha_composite(glow)
    img.alpha_composite(cut, (x, y))


def _shade(img: Image.Image):
    """Dark gradient on the left so the hook words pop."""
    sh = Image.new("L", (W, H))
    d = ImageDraw.Draw(sh)
    for x in range(W):
        d.line((x, 0, x, H), fill=int(170 * max(0, 1 - x / (W * 0.62))))
    black = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    black.putalpha(sh)
    img.alpha_composite(black)


def _hook(d: ImageDraw.ImageDraw, lines: list, colors, x=46, y_mid=330, max_w=760):
    size = 150
    while size > 60:
        f = font(size)
        if all(d.textlength(l, font=f) <= max_w for l in lines) and size * 1.05 * len(lines) <= 420:
            break
        size -= 6
    f = font(size)
    y = y_mid - int(size * 1.02 * len(lines)) // 2
    for i, l in enumerate(lines):
        d.text((x, y), l, font=f, fill=colors[i % len(colors)], stroke_width=max(6, size // 14),
               stroke_fill=(0, 0, 0))
        y += int(size * 1.02)


def _chip(d, text, xy, fill, fg=(15, 15, 15), size=34):
    f = font(size)
    tw = d.textlength(text, font=f)
    x, y = xy
    d.rounded_rectangle((x, y, x + tw + 36, y + size + 24), radius=12, fill=fill)
    d.text((x + 18, y + 10), text, font=f, fill=fg)
    return x + tw + 36


def _save(img: Image.Image, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    img = ImageEnhance.Contrast(img.convert("RGB")).enhance(1.08)
    img = ImageEnhance.Color(img).enhance(1.12)
    img.save(out, "JPEG", quality=90, optimize=True)
    ImageOps.contain(Image.open(out), (480, 270)).save(out.with_name(out.stem + "_small.jpg"), "JPEG", quality=80)
    return out


def make(dept: str, title: str, out: Path, badge: str | None = None, concept: str | None = None,
         lyrics: str | None = None, kind: str = "single") -> Path:
    """kind: 'single' (story + hook words) or 'live' (weekly mix / Saturday live)."""
    if kind == "live":
        return make_live(dept, out)
    p = pal(dept)
    genre = (badge or dept).lower()
    pl = plan(title, genre, concept, lyrics)
    bg = scene_image(pl["scene"])
    img = _cover(bg if bg is not None else _fallback_scene(dept)).convert("RGBA")
    _shade(img)
    _artist(img, p["accent"], side="right", height=690)
    d = ImageDraw.Draw(img)
    _hook(d, pl["hook"], [YELLOW, WHITE])
    _chip(d, (badge or p["chip"]).upper(), (46, 60), p["accent"])
    _chip(d, "NEW", (46, H - 100), (230, 20, 30), fg=WHITE, size=32)
    d.text((W - 40, H - 40), "NIKO BLAZE", font=font(36), fill=WHITE, anchor="rs", stroke_width=4,
           stroke_fill=(0, 0, 0))
    return _save(img, out)


def make_live(dept: str, out: Path) -> Path:
    p = pal(dept)
    look = GENRE_LOOK.get(dept, GENRE_LOOK["reggae"])
    crowd = {"reggae": "happy crowd dancing at a beach reggae concert at golden hour, Jamaica, hands in the air",
             "afrobeats": "packed afrobeats concert crowd dancing under neon lights in Lagos",
             "relaxation": "peaceful lake at sunrise with soft mist and mountains"}.get(dept, "")
    bg = scene_image(f"{crowd}, {look}, wide shot")
    img = _cover(bg if bg is not None else _fallback_scene(dept)).convert("RGBA")
    _shade(img)
    _artist(img, p["accent"], side="right", height=690)
    d = ImageDraw.Draw(img)
    # red LIVE badge with dot
    d.rounded_rectangle((46, 50, 250, 124), radius=14, fill=(225, 20, 30))
    d.ellipse((70, 72, 100, 102), fill=WHITE)
    d.text((115, 87), "LIVE", font=font(52), fill=WHITE, anchor="lm")
    top, word = LIVE_HOOK.get(dept, ("1 HOUR", dept.upper()))
    _hook(d, [top, word], [WHITE, YELLOW], y_mid=360)
    _chip(d, "NON-STOP · EVERY SATURDAY", (46, H - 104), p["accent"], size=30)
    d.text((W - 40, H - 40), "NIKO BLAZE", font=font(36), fill=WHITE, anchor="rs", stroke_width=4,
           stroke_fill=(0, 0, 0))
    return _save(img, out)
