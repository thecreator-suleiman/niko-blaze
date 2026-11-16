import subprocess
from functools import lru_cache

from PIL import ImageFont

from ..config import ASSETS

PALETTES = {
    "reggae": {"bg": [(8, 40, 22), (3, 12, 6)], "accent": (245, 197, 66), "accent2": (215, 38, 61),
               "label": [(26, 120, 60), (245, 197, 66), (215, 38, 61)], "chip": "REGGAE STORYTELLING"},
    "afrobeats": {"bg": [(58, 12, 74), (12, 4, 20)], "accent": (255, 122, 24), "accent2": (255, 209, 102),
                  "label": [(255, 122, 24), (120, 30, 140)], "chip": "AFROBEATS · AMAPIANO"},
    "relaxation": {"bg": [(10, 28, 58), (2, 8, 18)], "accent": (46, 196, 182), "accent2": (205, 180, 219),
                   "label": [(46, 196, 182), (20, 60, 90)], "chip": "RELAXATION"},
}


_VARIANT = {"seed": 0}


def set_variant(seed: int):
    """Every video gets its own colour shift + background layout (avoids identical-looking uploads)."""
    _VARIANT["seed"] = int(seed) % 10_000


def variant_seed() -> int:
    return _VARIANT["seed"]


def pal(dept: str) -> dict:
    import colorsys
    import random
    base = PALETTES[dept]
    seed = _VARIANT["seed"]
    if not seed:
        return base
    rng = random.Random(seed)
    shift = rng.uniform(-0.06, 0.06)

    def hue(c, amt):
        h, l, s_ = colorsys.rgb_to_hls(*[v / 255 for v in c])
        return tuple(int(v * 255) for v in colorsys.hls_to_rgb((h + amt) % 1, l, s_))
    return {**base, "bg": [hue(base["bg"][0], shift * 2), base["bg"][1]], "accent": hue(base["accent"], shift),
            "accent2": hue(base["accent2"], shift)}


@lru_cache(maxsize=None)
def font_path(bold: bool = True) -> str:
    for f in sorted((ASSETS / "fonts").glob("*.ttf")):
        if ("bold" in f.name.lower()) == bold:
            return str(f)
    q = "DejaVu Sans:bold" if bold else "DejaVu Sans"
    try:
        p = subprocess.run(["fc-match", "-f", "%{file}", q], capture_output=True, text=True).stdout.strip()
        if p:
            return p
    except FileNotFoundError:
        pass
    return "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"


def font(size: int, bold: bool = True):
    try:
        return ImageFont.truetype(font_path(bold), size)
    except OSError:
        return ImageFont.load_default(size)


def ass_font_name() -> str:
    try:
        return subprocess.run(["fc-scan", "--format", "%{family[0]}", font_path(True)],
                              capture_output=True, text=True).stdout.strip() or "DejaVu Sans"
    except FileNotFoundError:
        return "DejaVu Sans"
