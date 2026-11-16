from pathlib import Path

from conftest import synth

from nikoblaze.audio.analysis import ffmpeg, probe_duration
from nikoblaze.visual import render, thumbnails


def test_song_video_and_thumbnail(tmp):
    a = synth(tmp / "a.wav", 5)
    lines = [{"text": "Mama sold tomatoes", "start": 0.5, "end": 2.0,
              "words": [("Mama", 0.5, 0.9), ("sold", 0.9, 1.3), ("tomatoes", 1.3, 2.0)]}]
    out = render.render_song("reggae", "Tomatoes {at} Dawn", a, lines, 5.0, tmp / "v.mp4", preset="ultrafast")
    assert abs(probe_duration(out) - 5.0) < 0.2
    t = thumbnails.make("afrobeats", "When The Money Comes Home", tmp / "t.jpg")
    from PIL import Image
    assert Image.open(t).size == (1280, 720) and t.stat().st_size < 2_000_000


def test_mix_video_loops(tmp):
    synth(tmp / "m.wav", 40)
    ffmpeg("-i", str(tmp / "m.wav"), "-c:a", "aac", "-b:a", "192k", str(tmp / "m.m4a"))
    out = render.render_mix("relaxation", "1 Hour Relaxation Mix", tmp / "m.m4a", 40.0, tmp / "mix.mp4", "1 HOUR")
    assert abs(probe_duration(out) - 40.0) < 1.0
