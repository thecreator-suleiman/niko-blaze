"""Animated, seamlessly looping 'live session' scene for the weekly 1-hour mix stream.
No lyrics. Slow sunset beach: swaying palms, shimmering sea, drifting glow particles, gentle equalizer,
'LIVE ... SESSION' title and a pulsing subscribe call. Every motion is periodic over LOOP seconds, so the
clip can be looped for the whole hour without a visible jump. Pillow + numpy + ffmpeg only (zero cost)."""
import math
import random
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from . import assets
from .style import font

W, H, FPS = 1920, 1080, 30
LOOP = 24  # seconds; all animation frequencies are whole cycles per LOOP
HORIZON = 700

SCENES = {
    "reggae": {"sky": [(38, 14, 52), (176, 52, 48), (247, 150, 52), (252, 208, 102)], "sea": (10, 42, 48),
               "sun": (255, 214, 110), "stripe": [(26, 140, 70), (245, 197, 66), (215, 38, 61)],
               "title": "LIVE REGGAE SESSION", "sub": "1 hour non-stop reggae · good vibes only",
               "cta": "IF YOU LOVE REGGAE MUSIC — SUBSCRIBE"},
    "afrobeats": {"sky": [(28, 8, 48), (120, 30, 120), (255, 110, 40), (255, 200, 110)], "sea": (20, 14, 40),
                  "sun": (255, 190, 90), "stripe": [(255, 122, 24), (255, 209, 102), (150, 40, 160)],
                  "title": "LIVE AFROBEATS SESSION", "sub": "1 hour non-stop afrobeats · feel the groove",
                  "cta": "IF YOU LOVE AFROBEATS — SUBSCRIBE"},
    "relaxation": {"sky": [(6, 14, 38), (30, 60, 110), (110, 150, 190), (220, 200, 180)], "sea": (8, 26, 46),
                   "sun": (245, 235, 210), "stripe": [(46, 196, 182), (205, 180, 219), (120, 170, 220)],
                   "title": "LIVE RELAXATION SESSION", "sub": "1 hour of calm · breathe, relax, unwind",
                   "cta": "IF YOU LOVE CALM MUSIC — SUBSCRIBE"},
}


def _sky(sc) -> Image.Image:
    stops = sc["sky"]
    ys = np.linspace(0, 1, HORIZON)[:, None]
    pos = np.linspace(0, 1, len(stops))
    col = np.stack([np.interp(ys[:, 0], pos, [c[i] for c in stops]) for i in range(3)], axis=1)
    sky = np.repeat(col[:, None, :], W, axis=1)
    sea = np.zeros((H - HORIZON, W, 3))
    t = np.linspace(0, 1, H - HORIZON)[:, None]
    top = np.array(stops[-1]) * 0.35 + np.array(sc["sea"]) * 0.65
    sea[:] = (top * (1 - t) + np.array(sc["sea"]) * 0.5 * t)[:, None, :]
    img = Image.fromarray(np.vstack([sky, sea]).clip(0, 255).astype(np.uint8)).convert("RGBA")
    # sun with retro bands, half set into the horizon
    sun = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(sun)
    cx, cy, r = W // 2, HORIZON - 40, 230
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((cx - r * 2, cy - r * 2, cx + r * 2, cy + r * 2), fill=(*sc["sun"], 90))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(120)))
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*sc["sun"], 255))
    for i, y in enumerate(range(cy + 30, cy + r, 26)):
        d.rectangle((cx - r, y, cx + r, y + 4 + i * 2), fill=(0, 0, 0, 0))
    sun = sun.crop((0, 0, W, HORIZON))
    img.alpha_composite(sun, (0, 0))
    # distant hills
    hills = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hills)
    rng = random.Random(3)
    for layer, (alpha, amp) in enumerate([(150, 70), (220, 45)]):
        pts = [(0, HORIZON)]
        for x in range(0, W + 40, 40):
            pts.append((x, HORIZON - amp * (0.5 + 0.5 * math.sin(x / (300 + layer * 140) + layer)) - rng.randint(0, 8)))
        pts.append((W, HORIZON))
        hd.polygon(pts, fill=(12, 10, 22, alpha))
    return Image.alpha_composite(img, hills)


def _palm(d: ImageDraw.ImageDraw, base, height, lean, sway, color):
    bx, by = base
    pts = []
    for i in range(21):
        k = i / 20
        x = bx + lean * k * k * height + sway * 18 * k ** 3
        y = by - height * k
        pts.append((x, y))
    for i in range(20):
        w = 26 * (1 - i / 22) + 8
        d.line([pts[i], pts[i + 1]], fill=color, width=int(w))
    tx, ty = pts[-1]
    for j in range(9):
        ang = -math.pi / 2 + (j - 4) * 0.42 + sway * 0.08 * math.sin(j * 1.7 + 1)
        length = 230 + 40 * math.cos(j * 2.1)
        frond = []
        for s in range(13):
            k = s / 12
            a = ang + (0.9 if math.cos(ang) >= 0 else -0.9) * k * k * 0.9
            frond.append((tx + math.cos(a) * length * k, ty + math.sin(a) * length * k + 60 * k * k))
        top = [(x, y - 14 * math.sin(math.pi * i / 12)) for i, (x, y) in enumerate(frond)]
        bot = [(x, y + 14 * math.sin(math.pi * i / 12)) for i, (x, y) in enumerate(frond)]
        d.polygon(top + bot[::-1], fill=color)
    d.ellipse((tx - 22, ty - 10, tx + 22, ty + 30), fill=color)


def _particles(seed=11, n=60):
    rng = random.Random(seed)
    return [dict(x=rng.uniform(0, W), y=rng.uniform(0, H), r=rng.uniform(2, 6), cyc=rng.choice([1, 1, 2]),
                 wob=rng.uniform(10, 40), ph=rng.uniform(0, 2 * math.pi), a=rng.randint(70, 180)) for _ in range(n)]


def _static_overlay(sc, portrait) -> Image.Image:
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    # flag stripe at the bottom
    sh = 10
    for i, c in enumerate(sc["stripe"]):
        d.rectangle((0, H - sh * (3 - i), W, H - sh * (2 - i)), fill=(*c, 255))
    # title block (top center), with soft shadow
    sh_l = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sh_l)
    tf, nf, sf = font(92), font(40), font(32, bold=False)
    sd.text((W // 2 + 4, 176), sc["title"], font=tf, fill=(0, 0, 0, 200), anchor="mm")
    ov.alpha_composite(sh_l.filter(ImageFilter.GaussianBlur(8)))
    d.text((W // 2, 100), "NIKO BLAZE", font=nf, fill=(255, 255, 255, 235), anchor="mm")
    d.text((W // 2, 172), sc["title"], font=tf, fill=(255, 255, 255, 255), anchor="mm",
           stroke_width=3, stroke_fill=(0, 0, 0, 180))
    tw = d.textlength(sc["title"], font=tf)
    seg = tw / 3
    for i, c in enumerate(sc["stripe"]):
        x0 = W // 2 - tw / 2 + seg * i
        d.rectangle((x0, 232, x0 + seg - 6, 238), fill=(*c, 255))
    d.text((W // 2, 272), sc["sub"], font=sf, fill=(255, 245, 220, 230), anchor="mm")
    # round portrait badge, top right
    if portrait is not None:
        s = 150
        p = ImageOps.fit(portrait.convert("RGB"), (s, s))
        m = Image.new("L", (s, s), 0)
        ImageDraw.Draw(m).ellipse((0, 0, s, s), fill=255)
        ov.paste(p, (W - 70 - s, 50), m)
        d.ellipse((W - 70 - s - 3, 47, W - 67, 53 + s), outline=(*sc["stripe"][1], 255), width=5)
    return ov


def frame(t: float, sc, sky, static, parts) -> Image.Image:
    ph = 2 * math.pi * t / LOOP
    img = sky.copy()
    d = ImageDraw.Draw(img)
    # sea shimmer + sun reflection
    for i in range(26):
        y = HORIZON + 12 + i * i * 0.55
        if y > H - 40:
            break
        w = 260 - i * 7 + 30 * math.sin(ph * 2 + i * 0.9)
        off = 25 * math.sin(ph + i * 1.3)
        a = int(170 - i * 5)
        d.line((W // 2 - w / 2 + off, y, W // 2 + w / 2 + off, y), fill=(*sc["sun"], max(a, 30)), width=3)
    for i in range(40):
        x = (i * 211 + 60 * math.sin(ph + i)) % W
        y = HORIZON + 30 + (i * 37) % (H - HORIZON - 70)
        d.line((x, y, x + 50 + 20 * math.sin(ph * 2 + i), y), fill=(255, 255, 255, 40), width=2)
    # palms (silhouettes), sway is periodic
    pal_l = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pd = ImageDraw.Draw(pal_l)
    col = (8, 6, 14, 255)
    _palm(pd, (170, H + 20), 820, 0.28, math.sin(ph), col)
    _palm(pd, (40, H + 20), 600, 0.42, math.sin(ph + 1.1), col)
    _palm(pd, (W - 150, H + 20), 780, -0.30, math.sin(ph + 2.2), col)
    img.alpha_composite(pal_l)
    # glowing particles drifting up (wrap = whole cycles per loop)
    gl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(gl)
    for p in parts:
        y = (p["y"] - (t / LOOP) * p["cyc"] * H) % H
        x = p["x"] + p["wob"] * math.sin(ph * p["cyc"] + p["ph"])
        a = int(p["a"] * (0.6 + 0.4 * math.sin(ph * 2 + p["ph"])))
        c = sc["stripe"][int(p["ph"] * 10) % 3]
        r = p["r"]
        gd.ellipse((x - r * 3, y - r * 3, x + r * 3, y + r * 3), fill=(*c, a // 4))
        gd.ellipse((x - r, y - r, x + r, y + r), fill=(255, 240, 200, a))
    img.alpha_composite(gl)
    img.alpha_composite(static)
    d = ImageDraw.Draw(img)
    # ● LIVE badge (blinks once per second -> 24 blinks per loop)
    on = math.sin(2 * math.pi * t) > -0.3
    d.rounded_rectangle((60, 60, 230, 120), radius=12, fill=(200, 20, 30, 235))
    if on:
        d.ellipse((80, 78, 104, 102), fill=(255, 255, 255, 255))
    d.text((165, 90), "LIVE", font=font(36), fill=(255, 255, 255), anchor="mm")
    # equalizer (looping), bottom center
    n, bw, gap = 48, 14, 6
    x0 = W // 2 - (n * (bw + gap)) // 2
    for i in range(n):
        h = 18 + 70 * abs(math.sin(ph * (2 + i % 5) + i * 0.7) * 0.6 + math.sin(ph * (3 + i % 3) + i) * 0.4)
        c = sc["stripe"][(i * 3) // n]
        d.rounded_rectangle((x0 + i * (bw + gap), H - 150 - h, x0 + i * (bw + gap) + bw, H - 150), radius=5,
                            fill=(*c, 220))
    # pulsing subscribe pill
    s = 1 + 0.05 * math.sin(ph * 6)
    cf = font(int(34 * s))
    txt = sc["cta"]
    tw = d.textlength(txt, font=cf)
    pw, phh = tw + 150, 70 * s
    cx, cy = W // 2, H - 85
    d.rounded_rectangle((cx - pw / 2, cy - phh / 2, cx + pw / 2, cy + phh / 2), radius=int(phh / 2),
                        fill=(0, 0, 0, 160), outline=(255, 255, 255, 200), width=2)
    bx = cx - pw / 2 + 50
    d.rounded_rectangle((bx - 26, cy - 18, bx + 26, cy + 18), radius=9, fill=(230, 20, 30, 255))
    d.polygon([(bx - 8, cy - 10), (bx - 8, cy + 10), (bx + 11, cy)], fill=(255, 255, 255, 255))
    d.text((bx + 45, cy), txt, font=cf, fill=(255, 255, 255), anchor="lm")
    return img


def render_loop(dept: str, out: Path, seconds: int = LOOP) -> Path:
    """Write an H.264 loop (keyframe every 2 s, as YouTube Live wants). ~2-4 min on a GitHub runner."""
    sc = SCENES.get(dept, SCENES["reggae"])
    try:
        portrait, _ = assets.load_portrait()
    except Exception:
        portrait = None
    sky, static, parts = _sky(sc), _static_overlay(sc, portrait), _particles()
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                             "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium",
                             "-crf", "20", "-g", str(FPS * 2), "-keyint_min", str(FPS * 2), "-sc_threshold", "0",
                             "-pix_fmt", "yuv420p", str(out)], stdin=subprocess.PIPE)
    for i in range(seconds * FPS):
        proc.stdin.write(frame(i / FPS, sc, sky, static, parts).convert("RGB").tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("live scene encode failed")
    return out


def still(dept: str, out: Path, t: float = 3.0) -> Path:
    sc = SCENES.get(dept, SCENES["reggae"])
    portrait, _ = assets.load_portrait()
    frame(t, sc, _sky(sc), _static_overlay(sc, portrait), _particles()).convert("RGB").save(out)
    return out
