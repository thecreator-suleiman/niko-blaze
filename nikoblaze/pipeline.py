"""Orchestration: plan -> generate (GPU) -> collect/QC/master -> render -> publish; plus hour mixes."""
import hashlib
import json
import random
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import db, mixes, rights, storage
from .audio import align, analysis, mastering, quality
from .config import DEPARTMENTS, cfg, mastering_target, work_dir
from .lyrics import briefs, engine, llm
from .music.base import Job
from .music.providers import get_provider
from .visual import render, thumbnails
from .youtube import client as yt
from .youtube import metadata
from .youtube import publish as publisher
from .visual.style import set_variant

TZ = ZoneInfo(cfg("timezone", "Africa/Kigali"))


def today() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")


# ------------------------------------------------------------------ capacity
def gpu_seconds_last_7_days() -> float:
    r = db.get().execute("SELECT COALESCE(SUM(gpu_seconds),0) s FROM batches WHERE submitted_at >= ?",
                         ((datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"),)).fetchone()
    return r["s"]


def gpu_budget_left() -> float:
    lim = (cfg("generation.kaggle_weekly_gpu_hours") - cfg("generation.kaggle_safety_margin_hours")) * 3600
    return lim - gpu_seconds_last_7_days()


# ------------------------------------------------------------------ plan
def _new_song(dept: str, rng: random.Random, is_single: bool, subgenre=None) -> str | None:
    b = briefs.make_brief(dept, rng, subgenre)
    sid = f"{dept[:3]}-{datetime.now(TZ):%Y%m%d}-{rng.randrange(16 ** 6):06x}"
    try:
        lyr = engine.write(b)
    except llm.NoLLMAvailable as e:
        db.log("warn", "lyrics", f"{sid}: no free lyrics capacity, vocal song skipped ({e})")
        return None
    except ValueError as e:
        db.log("warn", "lyrics", f"{sid}: {e}")
        return None
    b.update({"concept": lyr.get("concept"), "hook": lyr.get("hook"), "lyrics_provider": lyr["provider"]})
    with db.tx() as c:
        c.execute("INSERT INTO songs(id,department,subgenre,title,brief_json,lyrics,caption,bpm,keyscale,duration,seed,"
                  "fingerprint,is_single,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (sid, dept, b["subgenre"], lyr["title"], json.dumps(b), lyr["lyrics"], briefs.caption_for(b),
                   b["bpm"], b["keyscale"], b["duration"], rng.randrange(2 ** 31), b["fingerprint"],
                   int(is_single), "planned", db.now(), db.now()))
    db.log("info", "plan", f"{sid} '{lyr['title']}' ({b['subgenre']}) planned")
    return sid


def week_mix_department(when=None) -> str:
    rot = cfg("schedule.mix_rotation")
    return rot[(when or datetime.now(TZ)).isocalendar().week % len(rot)]


def plan(extra: dict | None = None):
    """Create today's briefs + lyrics, then submit one GPU batch."""
    if db.is_paused():
        db.log("info", "plan", "automation paused — nothing planned")
        return
    rng = random.Random(f"{today()}-{datetime.now(timezone.utc).timestamp()}")
    sch = cfg("schedule")
    weekday = datetime.now(TZ).strftime("%a")
    wanted = []
    if weekday in sch["single_days"]:
        wanted.append((sch["single_department"], True))
    if weekday != "Sun":  # Mon-Sat build the library for this week's hour mix
        wanted += [(week_mix_department(), False)] * int(sch["mix_tracks_per_day"])
    for dept, n in (extra or {}).items():
        wanted += [(dept, dept == sch["single_department"])] * n
    # capacity: songs waiting for a retry count first
    retry = db.get().execute("SELECT id FROM songs WHERE status='retry'").fetchall()
    per_take = cfg("generation.est_gpu_seconds_per_take")
    cands = cfg("generation.candidates_per_song")
    budget = gpu_budget_left() - cfg("generation.batch_overhead_seconds")
    max_songs = int(max(0, budget) // (per_take * cands))
    if max_songs <= 0:
        db.log("warn", "capacity", "free GPU quota for this week is used up — generation paused until it renews")
        return
    ids = [r["id"] for r in retry][:max_songs]
    for dept, single in wanted:
        if len(ids) >= max_songs:
            db.log("warn", "capacity", f"GPU budget allows only {max_songs} songs today; rest deferred")
            break
        sid = _new_song(dept, rng, single)
        if sid:
            ids.append(sid)
    if ids:
        submit(ids)


def _model_lyrics(lyrics: str) -> str:
    """ACE-Step expects simple lowercase section tags: [verse], [chorus], [bridge] ..."""
    import re
    return re.sub(r"^\s*\[([A-Za-z\- ]+?)\s*\d*\]\s*$", lambda m: f"[{m.group(1).strip().lower()}]", lyrics, flags=re.M)


def submit(song_ids: list[str]):
    prov = get_provider()
    if prov is None:
        db.log("warn", "generate", "generation.provider is 'none' — songs stay planned")
        return
    rows = [db.get().execute("SELECT * FROM songs WHERE id=?", (i,)).fetchone() for i in song_ids]
    jobs = [Job(song_id=r["id"], caption=r["caption"], lyrics=_model_lyrics(r["lyrics"]), duration=r["duration"], bpm=r["bpm"],
                keyscale=r["keyscale"], seed=r["seed"] + r["attempts"] * 104729,
                instrumental=r["department"] == "relaxation", candidates=cfg("generation.candidates_per_song"))
            for r in rows]
    try:
        bid = prov.submit(jobs)
    except Exception as e:
        db.log("error", "generate", f"submit failed: {e}")
        return
    with db.tx() as c:
        c.execute("INSERT INTO batches(id,provider,status,submitted_at,info) VALUES(?,?,?,?,?)",
                  (bid, prov.name, "running", db.now(), json.dumps(song_ids)))
        for r in rows:
            c.execute("UPDATE songs SET status='submitted', batch_id=?, attempts=attempts+1, updated_at=? WHERE id=?",
                      (bid, db.now(), r["id"]))
    db.log("info", "generate", f"batch {bid} submitted with {len(jobs)} songs")


# ------------------------------------------------------------------ collect
def collect():
    prov = None
    for b in db.get().execute("SELECT * FROM batches WHERE status='running'").fetchall():
        prov = prov or get_provider(b["provider"])
        st = prov.poll(b["id"])
        age_h = (datetime.now(timezone.utc) - datetime.strptime(b["submitted_at"], "%Y-%m-%dT%H:%M:%SZ")
                 .replace(tzinfo=timezone.utc)).total_seconds() / 3600
        if st == "running" and age_h < cfg("generation.batch_timeout_hours"):
            db.log("info", "collect", f"batch {b['id']} still running ({age_h:.1f} h)")
            continue
        if st != "complete":
            db.update("batches", "id", b["id"], status="error", finished_at=db.now())
            _requeue(json.loads(b["info"]), f"GPU batch {st}")
            continue
        try:
            man = prov.fetch(b["id"], work_dir("batches", b["id"]))
        except Exception as e:
            db.update("batches", "id", b["id"], status="error", finished_at=db.now())
            _requeue(json.loads(b["info"]), str(e))
            continue
        db.update("batches", "id", b["id"], status="complete", finished_at=db.now(),
                  gpu_seconds=man.get("runtime_seconds", 0))
        for err in man.get("errors", []):
            db.log("warn", "generate", f"{err}")
        for sid in json.loads(b["info"]):
            process_song(sid, [t for t in man["takes"] if t["song_id"] == sid], Path(man["dir"]))
    publish_pending()


def _requeue(song_ids, reason):
    for sid in song_ids:
        r = db.get().execute("SELECT attempts FROM songs WHERE id=?", (sid,)).fetchone()
        st = "retry" if r and r["attempts"] < cfg("generation.max_attempts_per_song") else "abandoned"
        db.update("songs", "id", sid, status=st, error=reason[:500])
    db.log("error", "generate", f"{len(song_ids)} songs re-queued: {reason[:200]}")


def process_song(sid: str, takes: list, src_dir: Path):
    song = db.get().execute("SELECT * FROM songs WHERE id=?", (sid,)).fetchone()
    dept, instrumental = song["department"], song["department"] == "relaxation"
    results = []
    for t in takes:
        path = src_dir / t["file"]
        m = analysis.analyze(path)
        words = t.get("words")
        if words is None:
            try:
                words = align.transcribe_cpu(path)
            except Exception:
                words = None
        al = None if instrumental else align.align(song["lyrics"], words or [], m["duration"])
        ratio = al["match_ratio"] if (al and words is not None) else None
        qc = quality.score_take(m, dept, instrumental, ratio, len(words or []))
        results.append((qc, m, al, path))
        db.log("info", "qc", f"{sid} take {t['take']}: score {qc['score']} passed={qc['passed']} "
                             f"{'; '.join(qc['hard'] + qc['warnings'])}")
    passing = sorted([r for r in results if r[0]["passed"]], key=lambda r: -r[0]["score"])
    if not passing:
        reasons = "; ".join(sorted({h for r in results for h in r[0]["hard"] + r[0]["warnings"]})) or "no takes produced"
        _requeue([sid], f"all takes rejected: {reasons}")
        return
    qc, m, al, path = passing[0]
    day = datetime.now(TZ).strftime("%Y%m%d")
    tag = f"{cfg('storage.release_prefix', 'media')}-{day}"
    wd = work_dir("songs", sid)
    orig_flac, master_wav, master_flac = wd / f"{sid}_original.flac", wd / f"{sid}_master.wav", wd / f"{sid}_master.flac"
    mastering.to_flac(path, orig_flac)
    mastering.master(path, master_wav, dept)
    mm = analysis.analyze(master_wav)
    issues = quality.check_master(mm, mastering_target(dept))
    if issues:
        _requeue([sid], "mastering check failed: " + "; ".join(issues))
        return
    mastering.to_flac(master_wav, master_flac)
    o_ref, m_ref = storage.upload(tag, orig_flac), storage.upload(tag, master_flac)
    brief = json.loads(song["brief_json"])
    comps = rights.components_for("song", brief.get("lyrics_provider"))
    rights.record("song", sid, comps)
    db.update("songs", "id", sid, status="ready", original_asset=o_ref, master_asset=m_ref,
              master_duration=mm["duration"], qc_score=qc["score"],
              qc_json=json.dumps({"qc": qc, "metrics": m, "master": mm}), align_json=json.dumps(al) if al else None)
    db.log("info", "master", f"{sid} mastered ({mm['lufs']} LUFS, {mm['true_peak']} dBTP) and stored")
    if song["is_single"]:
        render_single(sid, master_wav)


def render_single(sid: str, master_wav: Path | None = None):
    song = dict(db.get().execute("SELECT * FROM songs WHERE id=?", (sid,)).fetchone())
    wd = work_dir("songs", sid)
    if master_wav is None or not Path(master_wav).exists():
        flac = storage.download(song["master_asset"], wd)
        master_wav = wd / f"{sid}_master.wav"
        analysis.ffmpeg("-i", str(flac), "-c:a", "pcm_s24le", str(master_wav))
    al = json.loads(song["align_json"]) if song["align_json"] else {"lines": []}
    set_variant(int(hashlib.sha1(sid.encode()).hexdigest(), 16))
    out = wd / f"{sid}.mp4"
    render.render_song(song["department"], song["title"], Path(master_wav), al["lines"], song["master_duration"], out)
    thumb = thumbnails.make(song["department"], song["title"], wd / f"{sid}_thumb.jpg")
    _queue_upload("single", sid, out, thumb)
    for k, st in enumerate(short_starts(song, al["lines"])):
        short = wd / f"{sid}_short{k}.mp4"
        render.render_short(song["department"], song["title"], Path(master_wav), al["lines"], st,
                            min(45.0, song["master_duration"] - st), short)
        _queue_upload("short", f"{sid}#s{k}", short, thumb)


def short_starts(song: dict, lines: list) -> list[float]:
    """Pick up to N distinct 45 s windows, preferring where the hook/chorus is sung."""
    n = int(cfg("schedule.shorts_per_single", 3))
    dur = song["master_duration"]
    hook = (json.loads(song["brief_json"]).get("hook") or "").lower()[:25]
    cands = [l["start"] - 1.0 for l in lines if hook and hook[:12] in l["text"].lower()]
    cands += [dur * f for f in (0.3, 0.55, 0.75)]
    out = []
    for c in cands:
        c = max(0.0, min(c, dur - 46))
        if all(abs(c - o) > 30 for o in out):
            out.append(round(c, 2))
        if len(out) >= n:
            break
    return out


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _queue_upload(kind: str, ref_id: str, video: Path, thumb: Path, parts: dict | None = None):
    """Stage a finished video for (re)upload. Hour mixes stage their small parts (loop + audio) instead of the
    multi-GB video, and are re-muxed losslessly when uploaded."""
    sha = _sha(video)
    small = thumb.with_name(thumb.stem + "_small.jpg")
    if small.exists():
        storage.upload("thumbs", small, f"{ref_id}.jpg")
    tag = f"video-{datetime.now(TZ):%Y%m%d}"
    if parts:
        v_ref = json.dumps({"loop": storage.upload(tag, parts["loop"], f"{ref_id}_loop.mp4"),
                            "audio": storage.upload(tag, parts["audio"], f"{ref_id}.m4a"),
                            "duration": parts["duration"]})
    else:
        v_ref = storage.upload(tag, video)  # held until uploaded, then deleted to save space
    t_ref = storage.upload(tag, thumb)
    with db.tx() as c:
        c.execute("INSERT INTO uploads(kind,ref_id,file_sha256,status,video_asset,thumb_asset,created_at,updated_at) "
                  "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(ref_id) DO UPDATE SET file_sha256=excluded.file_sha256, "
                  "video_asset=excluded.video_asset, thumb_asset=excluded.thumb_asset, "
                  "status=CASE WHEN uploads.status='uploaded' THEN 'uploaded' ELSE 'pending' END",
                  (kind, ref_id, sha, "pending", v_ref, t_ref, db.now(), db.now()))


# ------------------------------------------------------------------ publish
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _week_start() -> str:
    now = datetime.now(TZ)
    start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _publish_slot(kind: str, used: int) -> str:
    """Next configured day/time for this kind (e.g. singles Friday 18:00 Kigali)."""
    days = cfg(f"publishing.publish_days.{kind}")
    days = days if isinstance(days, list) else [days]
    hhmm = cfg(f"youtube.schedule_local_times.{kind}", "18:00")
    hhmm = hhmm[0] if isinstance(hhmm, list) else hhmm
    h, m = map(int, hhmm.split(":"))
    now = datetime.now(TZ)
    slots = []
    for i in range(0, 15):
        d = (now + timedelta(days=i)).replace(hour=h, minute=m, second=0, microsecond=0)
        if d.strftime("%a") in days and d > now + timedelta(minutes=30):
            slots.append(d)
    t = slots[min(used, len(slots) - 1)]
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _meta_for(u) -> tuple[dict, list]:
    if u["kind"] in ("single", "short"):
        sid = u["ref_id"].split("#")[0]
        song = dict(db.get().execute("SELECT * FROM songs WHERE id=?", (sid,)).fetchone())
        song["concept"] = json.loads(song["brief_json"]).get("concept")
        meta = metadata.single(song) if u["kind"] == "single" else metadata.short(song)
        comps = [r["component"] for r in db.get().execute(
            "SELECT component FROM rights WHERE ref_kind='song' AND ref_id=?", (sid,))]
    else:
        mx = db.get().execute("SELECT * FROM mixes WHERE id=?", (u["ref_id"],)).fetchone()
        meta = metadata.mix(mx["department"], mx["volume"], json.loads(mx["chapters"]))
        comps = sorted({r["component"] for tid in json.loads(mx["track_ids"]) for r in db.get().execute(
            "SELECT component FROM rights WHERE ref_kind='song' AND ref_id=?", (tid,))})
    return meta, comps


def publish_pending():
    if db.is_paused() or not cfg("youtube.enabled", False):
        return
    rows = db.get().execute("SELECT * FROM uploads WHERE status IN ('pending','failed') AND attempts < 5 "
                            "ORDER BY created_at").fetchall()
    for u in rows:
        cap = int(cfg(f"publishing.max_per_week.{u['kind']}", 1))
        done = db.get().execute("SELECT COUNT(*) n FROM uploads WHERE kind=? AND status='uploaded' AND updated_at>=?",
                                (u["kind"], _week_start())).fetchone()["n"]
        if done >= cap:
            continue  # channel-safety pacing: wait for next week
        meta, comps = _meta_for(u)
        blocked = rights.blocked(comps)
        if blocked:
            db.update("uploads", "id", u["id"], status="blocked_rights", error="unverified: " + ", ".join(blocked))
            db.log("warn", "rights", f"{u['ref_id']} not published — verify in config/licenses.yaml: {', '.join(blocked)}")
            continue
        dup = db.get().execute("SELECT youtube_id FROM uploads WHERE file_sha256=? AND status='uploaded'",
                               (u["file_sha256"],)).fetchone()
        if dup:
            db.update("uploads", "id", u["id"], status="uploaded", youtube_id=dup["youtube_id"])
            continue
        when = _publish_slot(u["kind"], done)
        wd = work_dir("upload", u["ref_id"].replace("#", "_"))
        try:
            if u["video_asset"].startswith("{"):
                p = json.loads(u["video_asset"])
                video = wd / f"{u['ref_id']}.mp4"
                if not video.exists():
                    loop, aud = storage.download(p["loop"], wd), storage.download(p["audio"], wd)
                    analysis.ffmpeg("-stream_loop", "-1", "-i", str(loop), "-i", str(aud), "-map", "0:v", "-map",
                                    "1:a", "-c", "copy", "-t", f"{p['duration']:.3f}", "-movflags", "+faststart",
                                    str(video))
            else:
                video = storage.download(u["video_asset"], wd)
            thumb = storage.download(u["thumb_asset"], wd) if u["kind"] != "short" else None
            vid, privacy = publisher.publish(video, meta, when, thumb)
        except (yt.QuotaExhausted, publisher.NoPublisher) as e:
            db.log("warn", "publish", f"{u['ref_id']} waiting: {e}")
            break
        except Exception as e:
            db.update("uploads", "id", u["id"], status="failed", attempts=u["attempts"] + 1, error=str(e)[:500])
            db.log("error", "publish", f"{u['ref_id']} upload failed: {e}")
            continue
        db.update("uploads", "id", u["id"], status="uploaded", youtube_id=vid, title=meta["title"], privacy=privacy,
                  publish_at=when, attempts=u["attempts"] + 1, error=None)
        for ref in (json.loads(u["video_asset"]) if u["video_asset"].startswith("{") else {"v": u["video_asset"]}).values():
            if isinstance(ref, str):
                storage.delete_asset(ref)  # video now lives on YouTube; free the space
        if u["kind"] == "single":
            db.update("songs", "id", u["ref_id"], status="published")
        elif u["kind"] == "mix":
            db.update("mixes", "id", u["ref_id"], status="published")
        db.log("info", "publish", f"{u['ref_id']} -> {vid} ({privacy}, goes live {when})")
        shutil.rmtree(wd, ignore_errors=True)


# ------------------------------------------------------------------ mixes
def daily_mixes(depts=None):
    if db.is_paused():
        db.log("info", "mix", "automation paused")
        return
    for dept in depts or [week_mix_department()]:
        try:
            mx = mixes.build(dept)
            if not mx:
                continue
            meta = metadata.mix(dept, mx["volume"], mx["chapters"])
            db.update("mixes", "id", mx["id"], title=meta["title"])
            set_variant(int(hashlib.sha1(mx["id"].encode()).hexdigest(), 16))
            out = mx["dir"] / f"{mx['id']}.mp4"
            render.render_mix(dept, f"1 Hour {dept.title()} Mix · Vol. {mx['volume']}", mx["audio"], mx["duration"],
                              out, badge="1 HOUR · PRE-RECORDED")
            thumb = thumbnails.make(dept, f"1 Hour {dept.title()} Mix", mx["dir"] / f"{mx['id']}_thumb.jpg",
                                    badge="1 HOUR MIX")
            _queue_upload("mix", mx["id"], out, thumb, parts={
                "loop": out.parent / f"{out.stem}_layers" / "loop.mp4", "audio": mx["audio"], "duration": mx["duration"]})
            db.update("mixes", "id", mx["id"], status="rendered")
            db.log("info", "mix", f"{mx['id']} rendered ({mx['duration'] / 60:.1f} min)")
            shutil.rmtree(mx["dir"], ignore_errors=True)
        except Exception as e:
            db.log("error", "mix", f"{dept}: {e}")
    publish_pending()


# ------------------------------------------------------------------ maintenance
def retry_production():
    rows = db.get().execute("SELECT id FROM songs WHERE status IN ('retry','planned')").fetchall()
    if rows:
        submit([r["id"] for r in rows][:20])


def retry_uploads():
    with db.tx() as c:
        c.execute("UPDATE uploads SET attempts=0, status='pending' WHERE status IN ('failed','blocked_rights')")
    publish_pending()


def prune_originals():
    days = cfg("storage.keep_originals_days", 60)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for r in db.get().execute("SELECT id, original_asset FROM songs WHERE original_asset IS NOT NULL AND created_at < ?",
                              (cutoff,)).fetchall():
        storage.delete_asset(r["original_asset"])
        db.update("songs", "id", r["id"], original_asset=None)
