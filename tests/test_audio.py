import json

from conftest import synth

from nikoblaze.audio import align, analysis, mastering, quality
from nikoblaze.config import mastering_target


def test_good_signal_passes_and_masters(tmp):
    src = synth(tmp / "a.wav", seconds=180)
    m = analysis.analyze(src)
    qc = quality.score_take(m, "afrobeats", instrumental=False, match_ratio=0.8)
    assert qc["passed"], qc
    mastering.master(src, tmp / "m.wav", "afrobeats")
    mm = analysis.analyze(tmp / "m.wav")
    assert quality.check_master(mm, mastering_target("afrobeats")) == []
    assert abs(mm["lufs"] + 14) < 1.0 and mm["true_peak"] <= -0.9
    mastering.to_flac(tmp / "m.wav", tmp / "m.flac")
    assert analysis.analyze(tmp / "m.flac")["subtype"] == "PCM_24"


def test_rejections(tmp):
    clip = analysis.analyze(synth(tmp / "c.wav", 180, clip=True))
    assert not quality.score_take(clip, "reggae", False, 0.8)["passed"]
    noise = analysis.analyze(synth(tmp / "n.wav", 180, noise=True))
    assert not quality.score_take(noise, "reggae", False, 0.8)["passed"]
    silent = analysis.analyze(synth(tmp / "s.wav", 180, silent=True))
    assert not quality.score_take(silent, "reggae", False, 0.8)["passed"]
    phase = analysis.analyze(synth(tmp / "p.wav", 180, mono_phase=True))
    assert any("phase" in h for h in quality.score_take(phase, "reggae", False, 0.8)["hard"])
    short = analysis.analyze(synth(tmp / "short.wav", 30))
    assert not quality.score_take(short, "afrobeats", False, 0.8)["passed"]
    good = analysis.analyze(synth(tmp / "g.wav", 180))
    assert not quality.score_take(good, "afrobeats", False, 0.1)["passed"]  # unintelligible lyrics


def test_alignment():
    lyrics = "[Verse 1]\nMama sold tomatoes at the dawn\nEvery coin a prayer\n[Chorus]\nWe go rise again"
    rec = [{"w": w, "s": i * 0.5, "e": i * 0.5 + 0.4} for i, w in
           enumerate("mama sold tomatoes at dawn every coin prayer we go rise".split())]
    out = align.align(lyrics, rec, 30)
    assert out["match_ratio"] > 0.75
    assert [l["text"] for l in out["lines"]][0].startswith("Mama")
    starts = [l["start"] for l in out["lines"]]
    assert starts == sorted(starts)
    assert align.align(lyrics, [], 30)["lines"]  # even spread fallback


def test_hit_score_gate():
    from nikoblaze.audio.quality import hit_score
    strong = hit_score(8, 0.37, 0.6, [{"p": 0.8}] * 40, 100)
    weak = hit_score(6, 0.22, 0.3, [{"p": 0.4}] * 40, 80)
    assert strong["score"] >= 70 > weak["score"]
