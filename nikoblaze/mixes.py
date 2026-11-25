"""Hour-long department mixes assembled from approved, mastered library tracks."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import db, storage
from .audio import mastering
from .audio.analysis import ffmpeg, probe_duration
from .config import cfg, work_dir


def select_tracks(dept: str) -> list:
    target = cfg("schedule.mix_target_minutes", 60) * 60
    cooldown = (datetime.now(timezone.utc) - timedelta(days=cfg("schedule.track_reuse_cooldown_days", 10))) \
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = db.get().execute(
        "SELECT * FROM songs WHERE department=? AND status IN ('ready','published') AND master_asset IS NOT NULL "
        "ORDER BY (last_used_in_mix IS NOT NULL), used_in_mixes ASC, created_at DESC", (dept,)).fetchall()
    fresh = [r for r in rows if not r["last_used_in_mix"] or r["last_used_in_mix"] < cooldown]
    fresh_ids = {r["id"] for r in fresh}
    pool = fresh + [r for r in rows if r["id"] not in fresh_ids]
    chosen, total = [], 0.0
    xf = 8 if dept == "relaxation" else 4
    for r in pool:
        if total >= target:
            break
        chosen.append(r)
        total += (r["master_duration"] or r["duration"]) - xf
    # Always a full hour: if the genre library is still small, play the tracks again in a new order
    # (never the same track back to back) instead of skipping the live.
    base = list(chosen)
    n = 0
    while total < target and len(base) >= 2 and n < 200:
        r = base[(n * 3 + 1) % len(base)]
        if r["id"] != chosen[-1]["id"]:
            chosen.append(r)
            total += (r["master_duration"] or r["duration"]) - xf
        n += 1
    return chosen


def build(dept: str) -> dict | None:
    tracks = select_tracks(dept)
    xf = 8 if dept == "relaxation" else 4
    est = sum((t["master_duration"] or t["duration"]) for t in tracks) - xf * max(0, len(tracks) - 1)
    if est < cfg("schedule.mix_min_minutes", 50) * 60 or len({t["id"] for t in tracks}) < 3:
        db.log("warn", "mix", f"{dept}: library too small for a mix ({est / 60:.0f} min available) — skipped")
        return None
    ids = [t["id"] for t in tracks]
    h = hashlib.sha1(json.dumps(ids).encode()).hexdigest()[:16]
    if db.get().execute("SELECT 1 FROM mixes WHERE tracklist_hash=?", (h,)).fetchone():
        tracks = tracks[1:] + tracks[:1]  # rotate order so the composition is new
        ids = [t["id"] for t in tracks]
        h = hashlib.sha1(json.dumps(ids).encode()).hexdigest()[:16]
    vol = (db.get().execute("SELECT COUNT(*) n FROM mixes WHERE department=?", (dept,)).fetchone()["n"] or 0) + 1
    mix_id = f"mix-{dept[:3]}-{datetime.now(timezone.utc):%Y%m%d}-{vol}"
    wd = work_dir("mixes", mix_id)
    files = [storage.download(t["master_asset"], work_dir("library")) for t in tracks]
    durs = [probe_duration(f) for f in files]
    inputs, graph, prev = [], [], "0:a"
    for f in files:
        inputs += ["-i", str(f)]
    for i in range(1, len(files)):
        out = f"a{i}"
        graph.append(f"[{prev}][{i}:a]acrossfade=d={xf}:c1=qsin:c2=qsin[{out}]")
        prev = out
    wav = wd / "mix.wav"
    if graph:
        ffmpeg(*inputs, "-filter_complex", ";".join(graph), "-map", f"[{prev}]", "-c:a", "pcm_s24le", str(wav))
    m4a = wd / "mix.m4a"
    mastering.to_aac(wav, m4a)
    chapters, t = [], 0.0
    for tr, d in zip(tracks, durs):
        chapters.append((t, tr["title"]))
        t += d - xf
    duration = probe_duration(m4a)
    with db.tx() as c:
        c.execute("INSERT INTO mixes(id,department,volume,title,track_ids,tracklist_hash,duration,chapters,status,"
                  "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                  (mix_id, dept, vol, "", json.dumps(ids), h, duration, json.dumps(chapters), "audio_ready",
                   db.now(), db.now()))
        for tid in ids:
            c.execute("UPDATE songs SET used_in_mixes=used_in_mixes+1, last_used_in_mix=? WHERE id=?", (db.now(), tid))
    return {"id": mix_id, "dept": dept, "volume": vol, "audio": m4a, "duration": duration, "chapters": chapters,
            "dir": wd}
