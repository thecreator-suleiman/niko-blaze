"""Vinyl music visualizer (songs) and seamless-loop visual (hour mixes). FFmpeg + Pillow only."""
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw

from ..audio.analysis import ffmpeg
from . import assets
from .style import pal, variant_seed, ass_font_name, font

W, H, FPS = 1920, 1080, 30
RPM = 100 / 3  # 33 1/3
DECK_POS = (900, 150)
VINYL = 640


def _ass_time(t: float) -> str:
    t = max(0.0, t)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def _ass_color(rgb, alpha=0):
    r, g, b = rgb
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def lyrics_ass(lines: list[dict], dept: str, path: Path, duration: float):
    p = pal(dept)
    fn = ass_font_name()
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cur,{fn},50,&H00FFFFFF,{_ass_color((255, 255, 255))},&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,3,2,2,60,60,128,1
Style: Nxt,{fn},34,&H50FFFFFF,&H50FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,1,2,60,60,72,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    esc = lambda s: s.replace("{", "(").replace("}", ")").replace("\\", "/")
    ev = []
    for i, ln in enumerate(lines):
        start = ln["start"] - 0.2
        nxt = lines[i + 1]["start"] if i + 1 < len(lines) else duration
        end = min(max(ln["end"] + 1.2, start + 1.5), nxt - 0.25) if i + 1 < len(lines) else min(ln["end"] + 3, duration)
        if end <= start:
            end = start + 0.8
        k, cursor = [], start
        for w, s, e in ln["words"]:
            if s > cursor:
                k.append(f"{{\\k{int((s - cursor) * 100)}}}")
            k.append(f"{{\\kf{max(1, int((e - max(s, cursor)) * 100))}}}{esc(w)} ")
            cursor = max(cursor, e)
        ev.append(f"Dialogue: 1,{_ass_time(start)},{_ass_time(end)},Cur,,0,0,0,,{{\\fad(150,150)}}{''.join(k).strip()}")
        if i + 1 < len(lines):
            ev.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Nxt,,0,0,0,,{{\\fad(150,150)}}{esc(lines[i + 1]['text'])}")
    path.write_text(head + "\n".join(ev) + "\n", encoding="utf-8")


def _compose(dept: str, title: str, subtitle: str, out_dir: Path, badge: str | None = None):
    """Writes base.png (static), vinyl.png (rotating), top.png (sheen+tonearm). Returns vinyl position."""
    p = pal(dept)
    portrait, _ = assets.load_portrait()
    bg = assets.background(dept, portrait=portrait)
    card = assets.portrait_card(portrait, 440, p["accent"])
    bg.alpha_composite(card, (110, 150))
    base_deck, top_deck, (pcx, pcy) = assets.deck(dept, vinyl_size=VINYL)
    bg.alpha_composite(base_deck, DECK_POS)
    d = ImageDraw.Draw(bg)
    d.text((150, 62), "NIKO BLAZE", font=font(54), fill=(255, 255, 255), spacing=8)
    d.rectangle((152, 128, 330, 134), fill=p["accent"])
    chip = p["chip"] if not badge else badge
    cf = font(26)
    tw = d.textlength(chip, font=cf)
    d.rounded_rectangle((W - 150 - tw - 40, 66, W - 150, 116), radius=25, outline=p["accent"], width=3)
    d.text((W - 150 - tw - 20, 76), chip, font=cf, fill=p["accent"])
    # lyrics band (y >= 860) is kept clear of the title, portrait and deck; darken it for readability
    band = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    for yy in range(840, H):
        bd.line((0, yy, W, yy), fill=(0, 0, 0, int(150 * min(1, (yy - 840) / 60))))
    bg.alpha_composite(band)
    d = ImageDraw.Draw(bg)
    tf = font(46)
    y = 655
    for line in textwrap.wrap(title, 22)[:2]:
        d.text((150, y), line, font=tf, fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))
        y += 56
    d.text((152, y + 6), subtitle, font=font(30, bold=False), fill=(*p["accent2"],))
    out_dir.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(out_dir / "base.png")
    vx, vy = DECK_POS[0] + pcx - VINYL // 2, DECK_POS[1] + pcy - VINYL // 2
    assets.vinyl(dept, VINYL).save(out_dir / "vinyl.png")
    top = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    top.alpha_composite(assets.sheen(VINYL), (vx, vy))
    top.alpha_composite(top_deck, DECK_POS)
    top.save(out_dir / "top.png")
    return vx, vy


def _rotate_graph(vx, vy):
    return (f"[1:v]format=rgba,rotate=a='t*2*PI*{RPM / 60:.6f}':c=none:ow=iw:oh=ih[vin];"
            f"[0:v][vin]overlay=x={vx}:y={vy}[b1];[b1][2:v]overlay=0:0[b2]")


def render_song(dept: str, title: str, audio: Path, lines: list[dict], duration: float, out: Path,
                preset="medium", crf=20, badge: str | None = None) -> Path:
    tmp = out.parent / (out.stem + "_layers")
    vx, vy = _compose(dept, title, "Niko Blaze · Original Song", tmp, badge=badge)
    ass = tmp / "lyrics.ass"
    lyrics_ass(lines, dept, ass, duration)
    acc = "0x%02X%02X%02X" % pal(dept)["accent"]
    graph = (_rotate_graph(vx, vy) +
             f";[3:a]showwaves=s=960x44:mode=cline:draw=full:rate={FPS}:colors={acc}@0.85,format=rgba[wav];"
             f"[b2][wav]overlay=x=480:y=1032:format=rgb[b3];[b3]ass='{ass.as_posix()}'[v]")
    ffmpeg("-loop", "1", "-framerate", str(FPS), "-i", str(tmp / "base.png"),
           "-loop", "1", "-framerate", str(FPS), "-i", str(tmp / "vinyl.png"),
           "-loop", "1", "-framerate", str(FPS), "-i", str(tmp / "top.png"),
           "-i", str(audio), "-filter_complex", graph, "-map", "[v]", "-map", "3:a",
           "-t", f"{duration:.3f}", "-r", str(FPS), "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "384k", "-ar", "48000", "-movflags", "+faststart",
           str(out))
    return out


def render_mix(dept: str, title: str, audio_m4a: Path, duration: float, out: Path, badge: str) -> Path:
    """Animated 'live session' scene (no lyrics, no vinyl deck), looped seamlessly for the whole hour."""
    from . import live_scene
    tmp = out.parent / (out.stem + "_layers")
    loop = live_scene.render_loop(dept, tmp / "loop.mp4")
    ffmpeg("-stream_loop", "-1", "-i", str(loop), "-i", str(audio_m4a), "-map", "0:v", "-map", "1:a",
           "-c", "copy", "-t", f"{duration:.3f}", "-movflags", "+faststart", str(out))
    return out


def render_short(dept: str, title: str, audio: Path, lines: list[dict], start: float, length: float,
                 out: Path, preset="medium") -> Path:
    """Vertical 1080x1920 YouTube Short of the chorus (<= 50 s) with spinning vinyl and synced lyrics."""
    SW, SH = 1080, 1920
    p = pal(dept)
    tmp = out.parent / (out.stem + "_layers")
    tmp.mkdir(parents=True, exist_ok=True)
    portrait, _ = assets.load_portrait()
    bg = assets.background(dept, (SW, SH), portrait=portrait)
    bg.alpha_composite(assets.portrait_card(portrait, 300, p["accent"]), (SW // 2 - 190, 170))
    d = ImageDraw.Draw(bg)
    d.text((SW // 2, 90), "NIKO BLAZE", font=font(64), fill=(255, 255, 255), anchor="mm")
    y = 590
    for line in textwrap.wrap(title, 20)[:2]:
        d.text((SW // 2, y), line, font=font(58), fill=p["accent"], anchor="mm", stroke_width=3, stroke_fill=(0, 0, 0))
        y += 70
    bg.convert("RGB").save(tmp / "base.png")
    V = 820
    assets.vinyl(dept, V).save(tmp / "vinyl.png")
    top = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    vx, vy = (SW - V) // 2, 760
    top.alpha_composite(assets.sheen(V), (vx, vy))
    top.save(tmp / "top.png")
    seg = [{**l, "start": l["start"] - start, "end": l["end"] - start,
            "words": [(w, s - start, e - start) for w, s, e in l["words"]]}
           for l in lines if start <= l["start"] < start + length - 1]
    ass = tmp / "lyrics.ass"
    lyrics_ass(seg, dept, ass, length)
    txt = ass.read_text().replace(f"PlayResX: {W}", f"PlayResX: {SW}").replace(f"PlayResY: {H}", f"PlayResY: {SH}")
    txt = txt.replace(",80,80,118,1", ",60,60,180,1").replace(",80,80,66,1", ",60,60,110,1")
    ass.write_text(txt)
    graph = _rotate_graph(vx, vy) + f";[b2]ass='{ass.as_posix()}'[v];[3:a]afade=t=in:d=0.5,afade=t=out:st={length - 1.5}:d=1.5[a]"
    ffmpeg("-loop", "1", "-framerate", str(FPS), "-i", str(tmp / "base.png"),
           "-loop", "1", "-framerate", str(FPS), "-i", str(tmp / "vinyl.png"),
           "-loop", "1", "-framerate", str(FPS), "-i", str(tmp / "top.png"),
           "-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", str(audio), "-filter_complex", graph,
           "-map", "[v]", "-map", "[a]", "-t", f"{length:.2f}", "-r", str(FPS), "-c:v", "libx264", "-preset", preset,
           "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "320k", "-ar", "48000",
           "-movflags", "+faststart", str(out))
    return out
