"""16:9 YouTube thumbnails (1280x720, JPEG < 2 MB)."""
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from . import assets
from .style import pal, variant_seed, font


def make(dept: str, title: str, out: Path, badge: str | None = None) -> Path:
    W, H = 1280, 720
    p = pal(dept)
    portrait, _ = assets.load_portrait()
    img = assets.background(dept, (W, H), portrait=portrait)
    rec = assets.vinyl(dept, 560)
    img.alpha_composite(rec, (W - 400, H // 2 - 280))
    img.alpha_composite(assets.sheen(560), (W - 400, H // 2 - 280))
    pc = assets.portrait_card(portrait, 380, p["accent"])
    img.alpha_composite(pc, (W - 700, H // 2 - 230))
    d = ImageDraw.Draw(img)
    d.text((48, 40), "NIKO BLAZE", font=font(46), fill=(255, 255, 255))
    d.rectangle((50, 98, 200, 104), fill=p["accent"])
    y = 200
    tf = font(66)
    for line in textwrap.wrap(title.upper(), 12)[:3]:
        d.text((48, y), line, font=tf, fill=(255, 255, 255), stroke_width=5, stroke_fill=(0, 0, 0))
        y += 78
    tag = badge or p["chip"]
    bf = font(34)
    tw = d.textlength(tag, font=bf)
    d.rounded_rectangle((48, H - 110, 48 + tw + 40, H - 50), radius=14, fill=p["accent"])
    d.text((68, H - 104), tag, font=bf, fill=(15, 15, 15))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out, "JPEG", quality=90, optimize=True)
    small = ImageOps.contain(Image.open(out), (480, 270))
    small.save(out.with_name(out.stem + "_small.jpg"), "JPEG", quality=80)
    return out
