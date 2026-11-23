import json
import random

import pytest

from nikoblaze import db, rights
from nikoblaze.lyrics import briefs, engine, llm, quality
from nikoblaze.music.providers import CAPABILITY_MATRIX, KaggleProvider
from nikoblaze.music.base import Job
from nikoblaze.youtube import metadata

GOOD = """[Intro]
(yeah, yeah)
[Verse 1]
Mama sold tomatoes when the dawn was cold
Counting every coin like it was gold
Bus fare folded in a tissue bag
School shoes mended with a market rag
Uncle said the city eats the poor
Still she pushed me out the wooden door
I remember dust upon her feet
And the way she hummed above the street
[Chorus]
Tomatoes at dawn, tomatoes at dawn
She carried my future on the road she was on
Tomatoes at dawn, tomatoes at dawn
Now every good thing I have, I call her home
[Verse 2]
First pay cheque came on a Friday rain
I took the night bus back to Kibuye again
Found her by the stall with the same old chair
Grey now running gently through her hair
I said Mama, sit, the work is done
She just laughed and squinted at the sun
Told me money is a borrowed coat
Kindness is the only thing that floats
[Chorus]
Tomatoes at dawn, tomatoes at dawn
She carried my future on the road she was on
Tomatoes at dawn, tomatoes at dawn
Now every good thing I have, I call her home
[Outro]
Every good thing, I call her home"""


def test_lyrics_quality():
    assert quality.check(GOOD, "Tomatoes at Dawn", []) == []
    bad = GOOD.replace("Counting every coin", "Neon tapestry of coins")
    assert any("AI phrases" in i for i in quality.check(bad, "X", []))
    assert any("too similar" in i for i in quality.check(GOOD, "Other", [("Tomatoes", GOOD)]))
    assert any("already used" in i for i in quality.check(GOOD, "Tomatoes at Dawn", [("tomatoes at dawn", "")]))


def test_brief_uniqueness_and_caption():
    rng = random.Random(3)
    seen = set()
    for dept in ("reggae", "afrobeats", "relaxation"):
        for _ in range(5):
            b = briefs.make_brief(dept, rng)
            assert b["fingerprint"] not in seen
            seen.add(b["fingerprint"])
            cap = briefs.caption_for(b)
            assert len(cap) <= 512
            assert ("no vocals" in cap) == (dept == "relaxation")
            assert ("male" in cap) == (dept != "relaxation")


def test_lyrics_engine_with_mock_llm(monkeypatch):
    calls = []

    def fake_chat(messages, temperature=0.95, skip=()):
        calls.append(messages)
        if len(calls) == 1:
            return json.dumps({"title": "Neon", "lyrics": "[Verse]\nneon tapestry\n[Chorus]\nsoar"}), "github_models"
        return json.dumps({"title": "Tomatoes at Dawn", "concept": "c", "hook": "h", "lyrics": GOOD}), "github_models"
    monkeypatch.setattr(llm, "chat", fake_chat)
    b = briefs.make_brief("afrobeats", random.Random(1))
    out = engine.write(b)
    assert out["title"] == "Tomatoes at Dawn" and len(calls) == 3  # draft rejected, rewrite accepted, hook rated


def test_no_llm_means_no_fake_lyrics(monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: [])
    with pytest.raises(llm.NoLLMAvailable):
        engine.write(briefs.make_brief("reggae", random.Random(2)))


def test_kaggle_kernel_build(tmp, monkeypatch):
    monkeypatch.setenv("KAGGLE_USERNAME", "someone")
    monkeypatch.setenv("KAGGLE_KEY", "x")
    p = KaggleProvider()
    job = Job("afr-1", "afrobeats, male vocals", GOOD, 180, 104, "A minor", 42, False, 2)
    d = p.build_kernel([job], tmp / "k")
    src = (d / "runner.py").read_text()
    compile(src, "runner.py", "exec")
    assert "__JOBS__" not in src and "afr-1" in src
    meta = json.loads((d / "kernel-metadata.json").read_text())
    assert meta["enable_gpu"] and meta["is_private"] and meta["id"] == "someone/niko-blaze-gen"


def test_capability_matrix_honest():
    names = {c.name: c for c in CAPABILITY_MATRIX}
    assert "NO" in names["MusicGen (Meta AudioCraft)"].commercial_use
    assert "NO" in names["Suno free tier"].commercial_use


def test_rights_gate():
    comps = rights.components_for("song", "gemini")
    assert "lyrics:gemini" in rights.blocked(comps)  # owner must verify first
    assert rights.blocked(["model:ace-step-1.5", "visual:procedural"]) == []


def test_metadata_limits():
    song = {"title": "T" * 150, "subgenre": "amapiano", "lyrics": GOOD, "concept": "x"}
    m = metadata.single(song)
    assert len(m["title"]) <= 100 and len(m["description"]) <= 5000
    assert sum(len(t) + 1 for t in m["tags"]) <= 500
    mx = metadata.mix("reggae", 3, [(0, "A"), (200, "B"), (3700, "C")])
    assert "Pre-recorded" in mx["title"] and "0:00 A" in mx["description"] and "1:01:40 C" in mx["description"]


def test_pause_resume():
    db.kv_set("paused", True)
    assert db.is_paused()
    db.kv_set("paused", False)
    assert not db.is_paused()


def test_credential_reminders(monkeypatch):
    from datetime import date
    from nikoblaze import notify
    sent = []
    monkeypatch.setattr(notify, "text", lambda m: sent.append(m) or True)
    assert notify.credential_reminders(date(2027, 4, 30)) == []
    assert notify.credential_reminders(date(2027, 5, 1)) == ["OPENROUTER_API_KEY"]
    assert "15 day" in sent[0]
