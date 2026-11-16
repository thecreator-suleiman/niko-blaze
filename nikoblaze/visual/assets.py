"""Procedurally drawn, original visual assets: vinyl, turntable, backgrounds, portrait card."""
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from ..config import ASSETS
from .style import PALETTES, font

W, H = 1920, 1080


def gradient(size, c1, c2, diagonal=True):
    w, h = size
    base = Image.new("RGB", size, c1)
    top = Image.new("RGB", size, c2)
    mask = Image.linear_gradient("L").resize((w + h, w + h)).rotate(-45 if diagonal else 0).crop((0, 0, w, h)) \
        if diagonal else Image.linear_gradient("L").resize(size)
    return Image.composite(top, base, mask)


def background(dept: str, size=(W, H), seed=7, portrait: Image.Image | None = None) -> Image.Image:
    p = PALETTES[dept]
    img = gradient(size, *p["bg"]).convert("RGBA")
    rng = random.Random(seed)
    bokeh = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(bokeh)
    for _ in range(26):
        r = rng.randint(20, 120)
        x, y = rng.randint(0, size[0]), rng.randint(0, size[1])
        c = rng.choice([p["accent"], p["accent2"]])
        d.ellipse((x - r, y - r, x + r, y + r), fill=(*c, rng.randint(12, 38)))
    img = Image.alpha_composite(img, bokeh.filter(ImageFilter.GaussianBlur(18)))
    if portrait is not None:
        ghost = ImageOps.fit(portrait.convert("RGB"), size).filter(ImageFilter.GaussianBlur(28))
        ghost = Image.blend(ghost, Image.new("RGB", size, (0, 0, 0)), 0.55).convert("RGBA")
        ghost.putalpha(70)
        img = Image.alpha_composite(img, ghost)
    vig = Image.radial_gradient("L").resize(size)
    dark = Image.new("RGBA", size, (0, 0, 0, 255))
    dark.putalpha(vig.point(lambda v: int(v * 0.75)))
    return Image.alpha_composite(img, dark)


def load_portrait() -> tuple[Image.Image, bool]:
    """Return (image, is_authorized_file). Falls back to an original generated silhouette."""
    for ext in ("jpg", "jpeg", "png", "webp"):
        f = ASSETS / "artist" / f"portrait.{ext}"
        if f.exists():
            return Image.open(f).convert("RGB"), True
    s = 800
    img = gradient((s, s), (60, 60, 70), (15, 15, 20)).convert("RGBA")
    d = ImageDraw.Draw(img)
    d.ellipse((s * .33, s * .16, s * .67, s * .54), fill=(10, 10, 12))        # head
    d.rounded_rectangle((s * .16, s * .58, s * .84, s * 1.2), radius=int(s * .22), fill=(10, 10, 12))  # shoulders
    d.rectangle((s * .45, s * .5, s * .55, s * .62), fill=(10, 10, 12))         # neck
    return img.convert("RGB"), False


def portrait_card(portrait: Image.Image, size=560, accent=(255, 255, 255)) -> Image.Image:
    card = ImageOps.fit(portrait, (size, size))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size, size), radius=36, fill=255)
    pad = 40
    out = Image.new("RGBA", (size + pad * 2, size + pad * 2), (0, 0, 0, 0))
    sh = Image.new("RGBA", out.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((pad + 10, pad + 18, pad + size + 10, pad + size + 18), radius=36,
                                         fill=(0, 0, 0, 170))
    out = Image.alpha_composite(out, sh.filter(ImageFilter.GaussianBlur(16)))
    out.paste(card, (pad, pad), mask)
    ImageDraw.Draw(out).rounded_rectangle((pad, pad, pad + size, pad + size), radius=36,
                                          outline=(*accent, 200), width=4)
    return out


def vinyl(dept: str, size=640) -> Image.Image:
    """Rotating layer: disc, grooves and centre label (label text makes rotation visible)."""
    p = PALETTES[dept]
    ss = size * 2
    img = Image.new("RGBA", (ss, ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c, R = ss / 2, ss / 2 - 2
    d.ellipse((c - R, c - R, c + R, c + R), fill=(12, 12, 13, 255))
    label_r = R * 0.34
    for i, r in enumerate(range(int(label_r + 14), int(R - 8), 5)):
        shade = 22 + (i % 3) * 5 + (8 if i % 37 == 0 else 0)
        d.ellipse((c - r, c - r, c + r, c + r), outline=(shade, shade, shade + 2, 255), width=2)
    d.ellipse((c - R, c - R, c + R, c + R), outline=(40, 40, 42, 255), width=6)
    cols = p["label"]
    for k, col in enumerate(cols):
        r = label_r * (1 - k / (len(cols) + 0.6))
        d.ellipse((c - r, c - r, c + r, c + r), fill=(*col, 255))
    f1, f2 = font(int(label_r * 0.30)), font(int(label_r * 0.13), bold=False)
    for txt, f, dy in (("NIKO BLAZE", f1, -label_r * 0.42), (p["chip"], f2, label_r * 0.30)):
        tw = d.textlength(txt, font=f)
        d.text((c - tw / 2, c + dy), txt, font=f, fill=(255, 255, 255, 235), stroke_width=2,
               stroke_fill=(0, 0, 0, 120))
    d.ellipse((c - 14, c - 14, c + 14, c + 14), fill=(200, 200, 205, 255))
    d.ellipse((c - 6, c - 6, c + 6, c + 6), fill=(30, 30, 30, 255))
    return img.resize((size, size), Image.LANCZOS)


def sheen(size=640) -> Image.Image:
    """Static light reflection laid over the spinning record (reflections do not rotate in reality)."""
    ss = size
    img = Image.new("RGBA", (ss, ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c, R = ss / 2, ss / 2 - 4
    for a0 in (-60, 120):
        d.pieslice((c - R, c - R, c + R, c + R), a0, a0 + 28, fill=(255, 255, 255, 34))
    img = img.filter(ImageFilter.GaussianBlur(14))
    hole = Image.new("L", (ss, ss), 255)
    ImageDraw.Draw(hole).ellipse((c - R * .36, c - R * .36, c + R * .36, c + R * .36), fill=0)
    disc = Image.new("L", (ss, ss), 0)
    ImageDraw.Draw(disc).ellipse((c - R, c - R, c + R, c + R), fill=255)
    a = img.getchannel("A")
    from PIL import ImageChops
    img.putalpha(ImageChops.multiply(ImageChops.multiply(a, hole), disc))
    return img


def deck(dept: str, w=940, h=720, vinyl_size=640) -> tuple[Image.Image, Image.Image, tuple]:
    """Returns (plinth layer, top layer with tonearm, platter centre within deck)."""
    p = PALETTES[dept]
    wood = [(74, 46, 28), (38, 23, 13)] if dept != "relaxation" else [(48, 52, 60), (20, 22, 28)]
    base = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((18, 26, w - 6, h - 4), radius=34, fill=(0, 0, 0, 180))
    base = Image.alpha_composite(base, sh.filter(ImageFilter.GaussianBlur(14)))
    body = gradient((w - 30, h - 34), *wood, diagonal=False).convert("RGBA")
    m = Image.new("L", body.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, *body.size), radius=30, fill=255)
    base.paste(body, (6, 4), m)
    d = ImageDraw.Draw(base)
    d.rounded_rectangle((26, 22, w - 44, h - 50), radius=22, fill=(22, 22, 24, 255), outline=(90, 90, 95, 255), width=3)
    cx, cy = 26 + (vinyl_size // 2) + 40, h // 2 - 12
    pr = vinyl_size // 2 + 16
    d.ellipse((cx - pr, cy - pr, cx + pr, cy + pr), fill=(150, 150, 155, 255))
    d.ellipse((cx - pr + 6, cy - pr + 6, cx + pr - 6, cy + pr - 6), fill=(25, 25, 27, 255))
    for i, lab in enumerate(("33", "45")):  # speed buttons
        x = 52 + i * 70
        d.rounded_rectangle((x, h - 112, x + 56, h - 80), radius=8, fill=(60, 60, 64, 255),
                            outline=(*p["accent"], 255) if i == 0 else (110, 110, 115, 255), width=2)
        d.text((x + 14, h - 108), lab, font=font(20), fill=(230, 230, 230, 255))
    d.ellipse((w - 150, h - 150, w - 80, h - 80), fill=(70, 70, 75, 255), outline=(170, 170, 175, 255), width=3)
    d.rectangle((w - 110, 90, w - 98, 330), fill=(15, 15, 15, 255))                 # pitch slider
    d.rounded_rectangle((w - 122, 190, w - 86, 214), radius=4, fill=(200, 200, 205, 255))
    # tonearm on its own transparent top layer
    top = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    t = ImageDraw.Draw(top)
    px, py = w - 200, 110
    t.ellipse((px - 46, py - 46, px + 46, py + 46), fill=(120, 120, 126, 255), outline=(200, 200, 205, 255), width=4)
    t.ellipse((px - 18, py - 18, px + 18, py + 18), fill=(40, 40, 40, 255))
    ang = math.radians(118)
    L = vinyl_size * 0.62
    ex, ey = px + L * math.cos(ang), py + L * math.sin(ang)
    t.line((px + 3, py + 6, ex + 3, ey + 6), fill=(0, 0, 0, 120), width=14)
    t.line((px, py, ex, ey), fill=(205, 205, 212, 255), width=10)
    t.line((px, py, px + 60, py - 40), fill=(205, 205, 212, 255), width=10)
    t.ellipse((px + 50, py - 62, px + 92, py - 24), fill=(80, 80, 84, 255))         # counterweight
    hx, hy = ex - 20, ey + 6
    t.polygon([(ex - 8, ey - 14), (ex + 22, ey + 6), (hx + 6, hy + 34), (hx - 26, hy + 14)], fill=(30, 30, 32, 255))
    return base, top, (cx, cy)
