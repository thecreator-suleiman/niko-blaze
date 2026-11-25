"""End-to-end test with a fake GPU provider (synthetic test tones stand in for the model)."""
import json

from conftest import synth

from nikoblaze import db, monitor, pipeline
from nikoblaze.audio.analysis import probe_duration
from nikoblaze.music.base import Provider
from test_core import GOOD


class FakeProvider(Provider):
    name = "fake"

    def __init__(self, root):
        self.root = root

    def submit(self, jobs):
        self.jobs = jobs
        return "fake-1"

    def poll(self, b):
        return "complete"

    def fetch(self, b, dest):
        takes = []
        for j in self.jobs:
            for c in range(j.candidates):
                f = self.root / f"{j.song_id}_t{c}.wav"
                synth(f, seconds=j.duration, clip=(c == 0), seed=c)  # take 0 is clipped -> must be rejected
                words = [] if j.instrumental else [
                    {"w": w, "s": 5 + i * 0.4, "e": 5.3 + i * 0.4} for i, w in enumerate(j.lyrics.replace("[", " ").split())]
                takes.append({"song_id": j.song_id, "take": c, "file": f.name, "words": words})
        return {"takes": takes, "errors": [], "runtime_seconds": 600, "dir": str(self.root)}


def test_end_to_end(tmp, monkeypatch):
    fake = FakeProvider(tmp)
    monkeypatch.setattr(pipeline, "get_provider", lambda name=None: fake)
    monkeypatch.setattr(pipeline.engine, "write", lambda b: {
        "title": f"Song {b['fingerprint'][:4]}", "concept": "c", "hook": "h",
        "lyrics": "[Instrumental]" if b["instrumental"] else GOOD, "provider": "github_models"})
    monkeypatch.setattr(pipeline.render, "render_song",
                        lambda dept, title, audio, lines, dur, out, **k: (out.write_bytes(b"x"), out)[1])
    monkeypatch.setenv("NB_SCHEDULE__SINGLE_DAYS", "[Mon, Tue, Wed, Thu, Fri, Sat, Sun]")
    monkeypatch.setenv("NB_SCHEDULE__MIX_TRACKS_PER_DAY", "0")
    monkeypatch.setenv("NB_PUBLISHING__REQUIRE_APPROVAL", "false")
    monkeypatch.setattr(pipeline, "week_mix_department", lambda when=None: "relaxation")
    monkeypatch.setattr(pipeline, "render_single", lambda sid, w=None: pipeline._queue_upload(
        "single", sid, _dummy(tmp, "v.mp4"), _dummy(tmp, "t.jpg")))
    pipeline.plan(extra={"relaxation": 1})
    rows = db.get().execute("SELECT * FROM songs").fetchall()
    assert {r["status"] for r in rows} == {"submitted"}
    pipeline.collect()
    rows = {r["department"]: r for r in db.get().execute("SELECT * FROM songs").fetchall()}
    assert rows["afrobeats"]["status"] == "ready", rows["afrobeats"]["error"]
    qc = json.loads(rows["afrobeats"]["qc_json"])
    assert qc["qc"]["passed"] and qc["master"]["subtype"] == "PCM_24"
    up = db.get().execute("SELECT * FROM uploads").fetchone()
    assert up["kind"] == "single" and up["status"] == "pending"  # youtube disabled by default -> not published
    snap = monitor.snapshot()
    assert snap["departments"]["afrobeats"]["library_tracks"] == 1
    assert snap["credits"]["kaggle_gpu_hours_used_7d"] > 0


def test_mix_builder(tmp, monkeypatch):
    from nikoblaze import mixes, storage
    monkeypatch.setenv("NB_SCHEDULE__MIX_TARGET_MINUTES", "1")
    monkeypatch.setenv("NB_SCHEDULE__MIX_MIN_MINUTES", "0.5")
    for i in range(3):
        f = synth(tmp / f"r{i}.wav", 25, seed=i)
        ref = storage.upload("media-test", f)
        with db.tx() as c:
            c.execute("INSERT INTO songs(id,department,title,status,master_asset,master_duration,duration,created_at) "
                      "VALUES(?,?,?,?,?,?,?,?)", (f"reg-{i}", "reggae", f"Track {i}", "ready", ref, 25, 25, db.now()))
    mx = mixes.build("reggae")
    assert mx and len(mx["chapters"]) == 3
    assert abs(probe_duration(mx["audio"]) - (75 - 8)) < 1.0  # 3 x 25 s minus two 4 s crossfades


def _dummy(tmp, name):
    p = tmp / name
    p.write_bytes(b"x")
    return p


def test_short_and_publish_chain(tmp, monkeypatch):
    monkeypatch.setenv("NB_SCHEDULE__SHORTS_PER_SINGLE", "3")
    from nikoblaze.youtube import publish
    lines = [{"text": "hook line here", "start": 60.0, "end": 62.0, "words": [("hook", 60, 60.5)]}]
    song = {"master_duration": 200.0, "brief_json": '{"hook": "hook line here"}'}
    st = pipeline.short_starts(song, lines)
    assert st[0] == 59.0 and len(st) == 3 and all(s <= 154 for s in st)
    monkeypatch.setenv("UPLOADPOST_API_KEY", "k")
    monkeypatch.setenv("UPLOADPOST_USER", "u")
    sent = {}
    monkeypatch.setattr(publish, "upload_post", lambda v, m, w=None, t=None: sent.setdefault("ok", "uploadpost:1"))
    assert publish.publish(tmp, {"title": "t"}, None) == ("uploadpost:1", "public")
    monkeypatch.setenv("NB_PUBLISHING__UPLOAD_POST_MONTHLY_LIMIT", "0")
    import pytest
    with pytest.raises(publish.NoPublisher):
        publish.publish(tmp, {"title": "t"}, None)
