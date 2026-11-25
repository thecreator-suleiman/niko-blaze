"""Orchestration: plan -> generate (GPU) -> collect/QC/master -> render -> publish; plus hour mixes."""
import hashlib
import json
import random
import shutil
import os
import time
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import db, mixes, notify, rights, storage
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
    r = db.get().execute("SELECT COALESCE(SUM(gpu_seconds),0) s FROM batches WHERE provider NOT IN ('gha_cpu','local_acestep') AND submitted_at >= ?",
                         ((datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"),)).fetchone()
    return r["s"]


def gpu_budget_left() -> float:
    lim = (cfg("generation.kaggle_weekly_gpu_hours") - cfg("generation.kaggle_safety_margin_hours")) * 3600
    return lim - gpu_seconds_last_7_days()


# ------------------------------------------------------------------ plan
def _new_song(dept: str, rng: random.Random, is_single: bool, subgenre=None) -> str | None:
    lyr = None
    for attempt in range(3):  # a fresh brief each time; one bad draft or a busy provider must not cost a song
        b = briefs.make_brief(dept, rng, subgenre)
        sid = f"{dept[:3]}-{datetime.now(TZ):%Y%m%d}-{rng.randrange(16 ** 6):06x}"
        try:
            lyr = engine.write(b)
            break
        except (llm.NoLLMAvailable, ValueError) as e:
            db.log("warn", "lyrics", f"{sid}: attempt {attempt + 1}/3 failed: {str(e)[:400]}")
            time.sleep(20)
    if lyr is None:
        if is_single:  # the weekly single must not be lost: collect() retries every run until it works
            db.kv_set("pending_single", {"dept": dept, "subgenre": subgenre})
            notify.problem("lyrics for this week's single could not be written yet (free AI providers busy). "
                           "The system retries automatically every 2 hours — no action needed.")
        return None
    if is_single:
        db.kv_set("pending_single", None)
    b.update({"concept": lyr.get("concept"), "hook": lyr.get("hook"), "lyrics_provider": lyr["provider"],
              "hook_score": lyr.get("hook_score")})
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
    # weeks run Sunday -> Saturday (live on Saturday), so Sunday already counts toward the next mix
    return rot[((when or datetime.now(TZ)) + timedelta(days=1)).isocalendar().week % len(rot)]


def plan(extra: dict | None = None):
    """Create today's briefs + lyrics, then submit one GPU batch."""
    if db.is_paused():
        db.log("info", "plan", "automation paused — nothing planned")
        return
    if cfg("generation.provider") == "none":
        db.log("info", "plan", "setup not finished (generation.provider: none) — nothing planned")
        return
    rng = random.Random(f"{today()}-{datetime.now(timezone.utc).timestamp()}")
    sch = {k: cfg(f"schedule.{k}") for k in ("single_days", "single_department", "mix_tracks_per_day")}
    weekday = datetime.now(TZ).strftime("%a")
    wanted = []
    if weekday in sch["single_days"]:
        wanted.append((sch["single_department"], True))
    if weekday != "Sat":  # Sun-Fri build the library for this week's hour mix
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
        if not cfg("generation.backup_providers", ["gha_cpu"]):
            db.log("warn", "capacity", "free GPU quota for this week is used up — generation paused until it renews")
            return
        max_songs = int(cfg("generation.backup_max_songs", 6))
        db.log("warn", "capacity", f"Kaggle quota used up — using backup generator for up to {max_songs} songs")
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


def _caption(r) -> str:
    try:  # rebuild from the brief so caption fixes also reach older/re-queued songs
        return briefs.caption_for(json.loads(r["brief_json"]))
    except Exception:
        return r["caption"]


def _style_ref(r, what="url") -> str:
    try:
        sub = (json.loads(r["brief_json"] or "{}").get("subgenre") or "").lower()
    except Exception:
        return ""
    if what == "mode":
        return (cfg("generation.style_modes", {}) or {}).get(sub, "")
    path = (cfg("generation.style_refs", {}) or {}).get(sub)
    return f"https://raw.githubusercontent.com/thecreator-suleiman/niko-blaze/main/{path}" if path else ""


def provider_chain() -> list[str]:
    """Primary provider first, then backups. Kaggle is skipped while it is unhealthy (quota/auth/rule
    change/repeated errors) and comes back automatically once the cool-down has passed."""
    names = [cfg("generation.provider")] + list(cfg("generation.backup_providers", ["gha_cpu"]) or [])
    names = [n for i, n in enumerate(names) if n and n != "none" and n not in names[:i]]
    if "kaggle" in names and len(names) > 1:
        since = (datetime.now(timezone.utc) - timedelta(hours=cfg("generation.failover_cooldown_hours", 48))) \
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        last = db.get().execute("SELECT status FROM batches WHERE provider='kaggle' AND submitted_at >= ? "
                                "ORDER BY submitted_at DESC LIMIT 2", (since,)).fetchall()
        sick = len(last) == 2 and all(r["status"] == "error" for r in last)
        # Kaggle has one notebook slot: pushing again would cancel the running batch
        busy = db.get().execute("SELECT 1 FROM batches WHERE provider='kaggle' AND status='running'").fetchone()
        if busy:
            names.remove("kaggle")
            return names
        if sick or gpu_budget_left() - cfg("generation.batch_overhead_seconds") <= 0:
            names.remove("kaggle")
            names.append("kaggle")  # still the last resort
    return names


def submit(song_ids: list[str], providers: list[str] | None = None):
    names = providers or provider_chain()
    if not names:
        db.log("warn", "generate", "generation.provider is 'none' — songs stay planned")
        return
    rows = [db.get().execute("SELECT * FROM songs WHERE id=?", (i,)).fetchone() for i in song_ids]
    jobs = [Job(song_id=r["id"], caption=_caption(r), lyrics=_model_lyrics(r["lyrics"]), hq=bool(r["is_single"]) and cfg("generation.hq_singles", True) or bool(_style_ref(r, "mode")), duration=r["duration"], bpm=r["bpm"],
                keyscale=r["keyscale"], seed=r["seed"] + r["attempts"] * 104729,
                instrumental=r["department"] == "relaxation", candidates=cfg("generation.candidates_per_song"),
                reference_url=_style_ref(r), style_mode=_style_ref(r, "mode"),
                steps=int(cfg("generation.cover_steps", 16)) if _style_ref(r, "mode") else 0)
            for r in rows]
    bid, prov, errs = None, None, []
    for n in names:
        try:
            prov = get_provider(n)
            bid = prov.submit(jobs)
            break
        except Exception as e:
            errs.append(f"{n}: {str(e)[:300]}")
            bid = None
    if bid is None:
        db.log("error", "generate", "submit failed on every provider: " + " | ".join(errs))
        notify.text(f"⚠️ Niko Blaze: could not start music generation on any provider.\n" + "\n".join(errs))
        return
    if errs:
        db.log("warn", "generate", f"failover to {prov.name}: " + " | ".join(errs))
    with db.tx() as c:
        c.execute("INSERT INTO batches(id,provider,status,submitted_at,info) VALUES(?,?,?,?,?)",
                  (bid, prov.name, "running", db.now(), json.dumps(song_ids)))
        for r in rows:
            c.execute("UPDATE songs SET status='submitted', batch_id=?, attempts=attempts+1, updated_at=? WHERE id=?",
                      (bid, db.now(), r["id"]))
    db.log("info", "generate", f"batch {bid} submitted with {len(jobs)} songs")


# ------------------------------------------------------------------ collect
def collect():
    prov, retry_now = None, False
    for b in db.get().execute("SELECT * FROM batches WHERE status='running'").fetchall():
        try:
            prov = get_provider(b["provider"])
            st = prov.poll(b["id"])
        except Exception as e:  # provider broken (e.g. key revoked): fail the batch so songs move to a backup
            prov, st = None, "error"
            db.log("error", "collect", f"batch {b['id']}: cannot poll {b['provider']}: {e}")
        age_h = (datetime.now(timezone.utc) - datetime.strptime(b["submitted_at"], "%Y-%m-%dT%H:%M:%SZ")
                 .replace(tzinfo=timezone.utc)).total_seconds() / 3600
        if st == "running" and age_h < cfg("generation.batch_timeout_hours"):
            db.log("info", "collect", f"batch {b['id']} still running ({age_h:.1f} h)")
            continue
        if st != "complete":
            db.log("error", "collect", f"batch {b['id']} {st}; kaggle log tail:\n{getattr(prov, 'last_error', '')}")
            db.update("batches", "id", b["id"], status="error", finished_at=db.now())
            _requeue(json.loads(b["info"]), f"GPU batch {st}")
            retry_now = True
            continue
        try:
            man = prov.fetch(b["id"], work_dir("batches", b["id"]))
        except Exception as e:
            db.update("batches", "id", b["id"], status="error", finished_at=db.now())
            _requeue(json.loads(b["info"]), str(e))
            continue
        db.update("batches", "id", b["id"], status="complete", finished_at=db.now(),
                  gpu_seconds=man.get("runtime_seconds", 0))
        db.log("info", "generate", f"batch {b['id']}: gpu={man.get('gpu')} modes={man.get('modes_tried')} "
                                   f"takes={len(man.get('takes', []))} runtime={man.get('runtime_seconds')}s "
                                   f"ref={[d for d in man.get('diag', []) if 'lat_finite' not in d][:4]}")
        for err in man.get("errors", []):
            db.log("warn", "generate", f"{err}")
        for sid in json.loads(b["info"]):
            try:  # one bad song must never stop the others (or the publishing step)
                process_song(sid, [t for t in man["takes"] if t["song_id"] == sid], Path(man["dir"]))
            except Exception as e:
                db.log("error", "collect", f"{sid}: processing failed: {type(e).__name__}: {str(e)[:400]}")
                st = db.get().execute("SELECT status FROM songs WHERE id=?", (sid,)).fetchone()
                if st and st["status"] != "ready":
                    _requeue([sid], f"processing failed: {e}")
    repair_singles()
    announce_live()
    ps = db.kv_get("pending_single")
    if ps and not db.is_paused():
        sid = _new_song(ps["dept"], random.Random(), True, ps.get("subgenre"))
        if sid:
            submit([sid])
    # Self-healing: if a batch just failed, re-submit straight away (the provider chain skips a sick Kaggle)
    # instead of waiting for tomorrow's plan.
    if retry_now and not db.is_paused() and not db.get().execute(
            "SELECT 1 FROM batches WHERE status='running'").fetchone():
        rows = db.get().execute("SELECT id FROM songs WHERE status='retry'").fetchall()
        if rows:
            submit([r["id"] for r in rows][:int(cfg("generation.backup_max_songs", 6))])
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
        raw = src_dir / t["file"]
        try:  # corrective EQ first, then judge the corrected audio (what listeners will actually hear)
            path = raw.with_name(raw.stem + "_eq.wav")
            fix = mastering.tonal_fix(raw, path, dept, analysis.analyze(raw))
        except Exception as e:
            path, fix = raw, {"error": str(e)[:200]}
        m = analysis.analyze(path)
        words = t.get("words")
        if words is None:
            try:
                words = align.transcribe_cpu(path)
            except Exception:
                words = None
        al = None if instrumental else align.align(song["lyrics"], words or [], m["duration"])
        ratio = al["match_ratio"] if (al and words is not None) else None
        n_words = quality.sung_words(words) if instrumental else len(words or [])
        qc = quality.score_take(m, dept, instrumental, ratio, n_words, t.get("genres"),
                                json.loads(song["brief_json"] or "{}").get("subgenre"))
        if not instrumental and cfg("quality.hit_check", True):
            try:
                g = analysis.groove(path)
            except Exception:
                g = None
            hook = json.loads(song["brief_json"] or "{}").get("hook_score")
            hs = quality.hit_score(hook, g, ratio, words, qc["score"])
            qc["hit"] = hs
            bar = cfg("quality.min_hit_score", 70) if song["is_single"] else cfg("quality.min_hit_score_mix", 55)
            if hs["score"] < bar:
                qc["passed"] = False
                qc["hard"].append(f"hit potential {hs['score']}% < {bar}% {hs['parts']}")
        results.append((qc, m, al, path))
        db.log("info", "qc", f"{sid} take {t['take']}: score {qc['score']} passed={qc['passed']} "
                             f"{'; '.join(qc['hard'] + qc['warnings'])} hit={(qc.get('hit') or {}).get('score', '-')}% eq={fix} genre={(t.get('genres') or [['?']])[0][0]}")
    passing = sorted([r for r in results if r[0]["passed"]], key=lambda r: -r[0]["score"])
    if not passing:
        reasons = "; ".join(sorted({h for r in results for h in r[0]["hard"] + r[0]["warnings"]})) or "no takes produced"
        _requeue([sid], f"all takes rejected: {reasons}")
        # Routine: the system regenerates on its own, so no alert per song. Only a song that is given up on
        # after the last attempt is reported (by _requeue / the daily summary).
        st = db.get().execute("SELECT status FROM songs WHERE id=?", (sid,)).fetchone()
        if st and st["status"] == "abandoned":
            notify.problem(f"song '{song['title']}' failed quality control on every attempt and was dropped "
                           f"({reasons[:160]}). A new song will be planned instead — no action needed.")
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
    if song["is_single"] and cfg("publishing.require_approval", True) and not db.kv_get(f"approved:{sid}"):
        db.update("songs", "id", sid, status="awaiting_approval")
        send_for_approval(sid, master_wav)
        return
    if song["is_single"]:
        try:
            render_single(sid, master_wav)
        except Exception as e:  # audio is safe in storage; repair_singles() re-renders on the next run
            db.log("error", "render", f"{sid}: render failed, will retry: {type(e).__name__}: {str(e)[:300]}")


def send_for_approval(sid: str, master_wav: Path | None = None):
    """Nothing is posted until Kwizera listens and approves (control: approve <id> / withdraw <id>)."""
    import subprocess, tempfile
    song = db.get().execute("SELECT * FROM songs WHERE id=?", (sid,)).fetchone()
    if master_wav is None:
        master_wav = storage.download(song["master_asset"], Path(tempfile.mkdtemp()))
    mp3 = Path(tempfile.mkdtemp()) / f"{song['title']}.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(master_wav), "-b:a", "256k", str(mp3)], check=True)
    sub = json.loads(song["brief_json"] or "{}").get("subgenre", "")
    notify.audio(mp3, f"🎧 APPROVAL NEEDED: {song['title']} ({sub})\nID: {sid}\n"
                      f"Approve: Control → approve, target {sid}\nReject: Control → withdraw, target {sid}")
    db.log("info", "approval", f"{sid} sent for approval")


def approve(sid: str):
    db.kv_set(f"approved:{sid}", "1")
    db.update("songs", "id", sid, status="ready")
    render_single(sid)
    db.log("info", "approval", f"{sid} approved and queued for publishing")
    notify.text(f"✅ Approved: {sid} — rendering and scheduling now.")


def repair_singles():
    """Re-render ready singles whose video or Shorts never got queued (e.g. a crash mid-render)."""
    n_short = int(cfg("schedule.shorts_per_single", 3))
    for r in db.get().execute("SELECT id FROM songs WHERE is_single=1 AND status='ready' "
                              "AND master_asset IS NOT NULL").fetchall():
        sid = r["id"]
        have = db.get().execute("SELECT ref_id FROM uploads WHERE ref_id=? OR ref_id LIKE ?",
                                (sid, f"{sid}#s%")).fetchall()
        if any(u["ref_id"] == sid for u in have) and len(have) - 1 >= min(1, n_short):
            continue
        tries = int(db.kv_get(f"render_tries:{sid}") or 0)
        if tries >= 3:
            continue
        db.kv_set(f"render_tries:{sid}", tries + 1)
        try:
            render_single(sid)
            db.log("info", "render", f"{sid}: repaired (videos re-rendered and queued)")
        except Exception as e:
            db.log("error", "render", f"{sid}: repair failed: {type(e).__name__}: {str(e)[:300]}")


def render_single(sid: str, master_wav: Path | None = None):
    song = dict(db.get().execute("SELECT * FROM songs WHERE id=?", (sid,)).fetchone())
    from .lyrics import engine as lyr_engine, quality as lyr_quality
    if lyr_quality.title_issues(song["title"], song["lyrics"] or ""):
        new = lyr_engine.retitle(song["lyrics"] or "")
        db.log("info", "render", f"{sid}: retitled '{song['title']}' -> '{new}'")
        db.update("songs", "id", sid, title=new)
        song["title"] = new
    wd = work_dir("songs", sid)
    if master_wav is None or not Path(master_wav).exists():
        flac = storage.download(song["master_asset"], wd)
        master_wav = wd / f"{sid}_master.wav"
        analysis.ffmpeg("-i", str(flac), "-c:a", "pcm_s24le", str(master_wav))
    al = json.loads(song["align_json"]) if song["align_json"] else {"lines": []}
    set_variant(int(hashlib.sha1(sid.encode()).hexdigest(), 16))
    out = wd / f"{sid}.mp4"
    badge = (json.loads(song["brief_json"]).get("subgenre") or "").upper() or None  # the song's real genre
    render.render_song(song["department"], song["title"], Path(master_wav), al["lines"], song["master_duration"], out,
                       badge=badge)
    thumb = thumbnails.make(song["department"], song["title"], wd / f"{sid}_thumb.jpg", badge=badge)
    _queue_upload("single", sid, out, thumb)
    for k, st in enumerate(short_starts(song, al["lines"])):
        short = wd / f"{sid}_short{k}.mp4"
        render.render_short(song["department"], song["title"], Path(master_wav), al["lines"], st,
                            min(45.0, song["master_duration"] - st), short)
        _queue_upload("short", f"{sid}#s{k}", short, thumb)


def short_starts(song: dict, lines: list) -> list[float]:
    """Pick up to N distinct 45 s windows, preferring where the hook/chorus is sung."""
    n = int(cfg("schedule.shorts_per_single", 3))
    if n <= 0:
        return []
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


# ------------------------------------------------------------------ Saturday live stream
def stream_mix():
    """Stream the newest rendered mix live to YouTube with the channel's stream key (no API, no upload slot)."""
    import subprocess
    key = os.environ.get("YT_STREAM_KEY")
    u = db.get().execute("SELECT * FROM uploads WHERE kind='mix' AND status='live_pending' "
                         "ORDER BY created_at DESC LIMIT 1").fetchone()
    if not u:
        db.log("warn", "live", "no mix ready to stream")
        notify.problem("Saturday live: no 1-hour mix was ready to stream this week (not enough new tracks yet).")
        return
    if not key:
        db.update("uploads", "id", u["id"], status="pending")  # fall back to a normal upload
        publish_pending()
        return
    wd = work_dir("live", u["ref_id"])
    parts = json.loads(u["video_asset"])
    loop, audio = storage.download(parts["loop"], wd), storage.download(parts["audio"], wd)
    loop2 = wd / "loop_live.mp4"  # YouTube wants a keyframe every <= 4 s
    analysis.ffmpeg("-i", str(loop), "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-g", "60",
           "-keyint_min", "60", "-pix_fmt", "yuv420p", "-an", str(loop2))
    mx = db.get().execute("SELECT * FROM mixes WHERE id=?", (u["ref_id"],)).fetchone()
    meta = metadata.live(mx["department"], mx["volume"], json.loads(mx["chapters"] or "[]")) if mx else None
    title = meta["title"] if meta else "1 hour mix"
    db.update("uploads", "id", u["id"], status="streaming")
    db.get().commit()
    url = cfg("youtube.rtmp_url", "rtmp://a.rtmp.youtube.com/live2") + "/" + key
    proc = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-re", "-stream_loop", "-1", "-i",
                             str(loop2), "-re", "-i", str(audio), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                             "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-t", f"{float(parts['duration']):.1f}",
                             "-f", "flv", url], stderr=subprocess.PIPE, text=True)
    link = f"https://www.youtube.com/{cfg('youtube.channel_handle', '@nikoblazeofficial')}/live"
    vid = _find_live_video(proc)
    if vid:
        link = f"https://youtu.be/{vid}"
        try:  # own API is audited: set this week's hook title + thumbnail on the running broadcast
            thumb = storage.download(u["thumb_asset"], wd) if u["thumb_asset"] else None
            if meta:
                yt.update_video(vid, meta, thumb)
            db.update("uploads", "id", u["id"], youtube_id=vid)
        except Exception as e:
            db.log("warn", "live", f"could not set live title/thumbnail: {e}")
    notify.text(f"🔴 LIVE NOW on YouTube — {title}\n{link}")
    _, err = proc.communicate()
    r = type("R", (), {"returncode": proc.returncode, "stderr": err or ""})()
    if r.returncode == 0:
        db.update("uploads", "id", u["id"], status="uploaded")
        notify.text(f"✅ Live stream finished — {title}. The replay stays on the channel.")
    else:
        db.update("uploads", "id", u["id"], status="live_pending")
        notify.problem(f"Saturday live stream failed: {r.stderr[-300:]}")


def _find_live_video(proc, timeout=600) -> str | None:
    """The stream-key broadcast gets a video id once YouTube sees the stream; read it from the channel's /live page."""
    import time
    import requests
    cid = db.kv_get("yt_channel_id") or cfg("youtube.channel_id", None)
    end = time.time() + timeout
    time.sleep(60)
    while time.time() < end and proc.poll() is None:
        try:
            html = requests.get(f"https://www.youtube.com/channel/{cid}/live", timeout=30,
                                headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en"}).text
            m = re.search(r'<link rel="canonical" href="https://www\.youtube\.com/watch\?v=([\w-]{11})"', html) \
                or re.search(r'"isLive":true.*?"videoId":"([\w-]{11})"', html) \
                or re.search(r'"videoId":"([\w-]{11})"[^{}]*"isLive":true', html)
            if m:
                return m.group(1)
        except Exception:
            pass
        time.sleep(30)
    return None


# ------------------------------------------------------------------ live links
def _channel_feed() -> list[tuple[str, str]]:
    """(video_id, title) of the channel's latest uploads from YouTube's public RSS feed (no key, no quota)."""
    import html
    import requests
    cid = db.kv_get("yt_channel_id") or cfg("youtube.channel_id", None)
    if not cid:
        handle = cfg("youtube.channel_handle", "@nikoblazeofficial")
        page = requests.get(f"https://www.youtube.com/{handle}", timeout=30,
                            headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en"}).text
        m = re.search(r'"(?:channelId|externalId)":"(UC[\w-]{22})"', page) or \
            re.search(r"youtube\.com/channel/(UC[\w-]{22})", page)
        if not m:
            raise RuntimeError("could not find the channel id")
        cid = m.group(1)
        db.kv_set("yt_channel_id", cid)
    xml = requests.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}", timeout=30).text
    ids = re.findall(r"<yt:videoId>([\w-]{11})</yt:videoId>", xml)
    titles = [html.unescape(t) for t in re.findall(r"<entry>.*?<title>(.*?)</title>", xml, re.S)]
    return list(zip(ids, titles))


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def announce_live():
    """Send "✅ LIVE + link" once each scheduled upload is actually visible on the channel."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = [r for r in db.get().execute("SELECT * FROM uploads WHERE status='uploaded'").fetchall()
            if not db.kv_get(f"live:{r['ref_id']}") and (r["publish_at"] or "") <= now]
    if not rows:
        return
    try:
        feed = _channel_feed()
    except Exception as e:
        db.log("warn", "live", f"channel feed unavailable: {e}")
        return
    used = {u["youtube_id"] for u in db.get().execute("SELECT youtube_id FROM uploads WHERE youtube_id IS NOT NULL")}
    for r in sorted(rows, key=lambda r: r["publish_at"] or ""):  # Shorts share a title: oldest gets oldest video
        hit = next((vid for vid, title in reversed(feed) if _norm(title) == _norm(r["title"]) and vid not in used),
                   None)
        if hit:
            used.add(hit)
        if hit:
            db.update("uploads", "id", r["id"], youtube_id=hit)
            db.kv_set(f"live:{r['ref_id']}", hit)
            notify.live(r["kind"], r["title"], hit)
            db.log("info", "live", f"{r['ref_id']} is live: https://youtu.be/{hit}")
            continue
        due = datetime.fromisoformat((r["publish_at"] or r["updated_at"]).replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - due > timedelta(hours=12) and not db.kv_get(f"live_warned:{r['ref_id']}"):
            db.kv_set(f"live_warned:{r['ref_id']}", True)
            notify.problem(f"'{r['title']}' was due at {notify.local_time(r['publish_at'])} (Kigali) but is not on "
                           f"the channel yet. Check app.upload-post.com history.")


def reprocess(batch_id: str | None = None):
    """Re-judge the takes of a finished batch with the current QC (no new GPU time)."""
    b = db.get().execute("SELECT * FROM batches WHERE (? IS NULL OR id=?) AND status='complete' "
                         "ORDER BY submitted_at DESC LIMIT 1", (batch_id, batch_id)).fetchone()
    if not b:
        return
    prov = get_provider(b["provider"])
    man = prov.fetch(b["id"], work_dir("gpu", b["id"]))
    for sid in json.loads(b["info"]):
        st = db.get().execute("SELECT status FROM songs WHERE id=?", (sid,)).fetchone()
        if st and st["status"] in ("retry", "abandoned", "planned"):
            try:
                process_song(sid, [t for t in man["takes"] if t["song_id"] == sid], Path(man["dir"]))
            except Exception as e:
                db.log("error", "collect", f"{sid}: reprocess failed: {e}")
    publish_pending()


def reschedule(sid: str, at_kigali: str):
    """Move a song's full video to a new time (Kigali, 'YYYY-MM-DD HH:MM' or 'HH:MM' = today) and drop its Shorts."""
    import requests
    if len(at_kigali) <= 5:
        at_kigali = f"{datetime.now(TZ):%Y-%m-%d} {at_kigali}"
    at = (datetime.strptime(at_kigali, "%Y-%m-%d %H:%M") - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    key = os.environ.get("UPLOADPOST_API_KEY")
    ups = db.get().execute("SELECT * FROM uploads WHERE ref_id=? OR ref_id LIKE ?", (sid, f"{sid}#%")).fetchall()
    titles = {_norm(u["title"]) for u in ups if u["title"]}
    n = 0
    if key and titles:
        h = {"Authorization": f"Apikey {key}"}
        r = requests.get("https://api.upload-post.com/api/uploadposts/schedule", headers=h, timeout=60)
        for j in r.json().get("scheduled_posts", []):
            if _norm(j.get("title")) in titles:
                n += requests.delete(f"https://api.upload-post.com/api/uploadposts/schedule/{j['job_id']}",
                                     headers=h, timeout=60).ok
    if n:
        db.add_usage("upload_post", -n, publisher._month())
    try:  # the local copy is deleted once handed over; rebuild it from the stored master audio
        render_single(sid)
    except Exception as e:
        db.log("error", "publish", f"{sid}: re-render failed: {e}")
    with db.tx() as c:
        c.execute("UPDATE uploads SET status='cancelled' WHERE ref_id LIKE ?", (f"{sid}#%",))
        c.execute("UPDATE uploads SET status='pending', attempts=0, publish_at=?, youtube_id=NULL WHERE ref_id=?",
                  (at, sid))
    db.log("info", "publish", f"{sid}: {n} scheduled posts cancelled; full video re-queued for {at}")
    publish_pending()


def cancel_song(sid: str, reason: str):
    """Pull a song before it goes live: cancel its scheduled Upload-Post jobs (credits come back) and reject it."""
    import requests
    song = db.get().execute("SELECT * FROM songs WHERE id=?", (sid,)).fetchone()
    key = os.environ.get("UPLOADPOST_API_KEY")
    ups = db.get().execute("SELECT * FROM uploads WHERE ref_id=? OR ref_id LIKE ?", (sid, f"{sid}#%")).fetchall()
    titles = {_norm(u["title"]) for u in ups if u["title"]}
    cancelled = 0
    if key and titles:
        h = {"Authorization": f"Apikey {key}"}
        r = requests.get("https://api.upload-post.com/api/uploadposts/schedule", headers=h, timeout=60,
                         params={"limit": 100})
        for j in r.json().get("scheduled_posts", []):
            if _norm(j.get("title")) in titles:
                d = requests.delete(f"https://api.upload-post.com/api/uploadposts/schedule/{j['job_id']}",
                                    headers=h, timeout=60)
                cancelled += d.ok
    for u in ups:  # videos already scheduled through our own YouTube API
        if u["youtube_id"] and u["status"] != "cancelled":
            try:
                from .youtube import client as ytc
                ytc.service().videos().delete(id=u["youtube_id"]).execute()
                db.log("warn", "publish", f"deleted video {u['youtube_id']}")
            except Exception as e:
                db.log("warn", "publish", f"could not delete {u['youtube_id']}: {str(e)[:200]}")
    if cancelled:
        db.add_usage("upload_post", -cancelled, publisher._month())  # refunded slots
    with db.tx() as c:
        c.execute("UPDATE uploads SET status='cancelled' WHERE ref_id=? OR ref_id LIKE ?", (sid, f"{sid}#%"))
        c.execute("UPDATE songs SET status='rejected' WHERE id=?", (sid,))
    db.log("warn", "publish", f"{sid} withdrawn ({reason}); {cancelled} scheduled posts cancelled")
    notify.text(f"🛑 Withdrawn before going live: {song['title'] if song else sid}\nReason: {reason}\n"
                f"{cancelled} scheduled YouTube posts cancelled (upload credits refunded).")
    return cancelled


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
                            "ORDER BY CASE kind WHEN 'mix' THEN 0 WHEN 'single' THEN 1 ELSE 2 END, created_at").fetchall()
    for u in rows:  # mixes & singles first so the free monthly upload budget goes to the main videos
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
        when = u["publish_at"] if (u["publish_at"] or "") > db.now() else _publish_slot(u["kind"], done)
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
            vid, privacy = publisher.publish(video, meta, when, thumb, kind=u["kind"])
        except (yt.QuotaExhausted, publisher.NoPublisher) as e:
            db.log("warn", "publish", f"{u['ref_id']} waiting: {e}")
            break
        except Exception as e:
            db.update("uploads", "id", u["id"], status="failed", attempts=u["attempts"] + 1, error=str(e)[:500])
            db.log("error", "publish", f"{u['ref_id']} upload failed: {e}")
            notify.problem(f"upload failed for {u['ref_id']}: {str(e)[:300]}")
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
        notify.posted(u["kind"], vid, meta, video, thumb, privacy, when)
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
            if cfg("mixes.mode", "live") == "live" and os.environ.get("YT_STREAM_KEY"):
                # streamed live on Saturday evening instead of uploaded (the stream archive stays on the channel)
                db.get().execute("UPDATE uploads SET status='live_pending' WHERE ref_id=?", (mx["id"],))
                db.get().commit()
            db.update("mixes", "id", mx["id"], status="rendered")
            db.log("info", "mix", f"{mx['id']} rendered ({mx['duration'] / 60:.1f} min)")
            shutil.rmtree(mx["dir"], ignore_errors=True)
        except Exception as e:
            db.log("error", "mix", f"{dept}: {e}")
    publish_pending()


def test_mix(dept: str = "relaxation"):
    """Dry run of the weekly mix: build + render from the current library with a low minimum, then undo all
    database changes. Nothing is uploaded. Reports the result to Telegram."""
    import sqlite3
    snap = sqlite3.connect(":memory:")
    db.get().backup(snap)  # restore point
    os.environ["NB_SCHEDULE__MIX_MIN_MINUTES"] = "5"
    try:
        mx = mixes.build(dept)
        if not mx:
            notify.problem(f"mix test ({dept}): library too small even for a short test")
            return
        out = mx["dir"] / f"{mx['id']}.mp4"
        render.render_mix(dept, f"1 Hour {dept.title()} Mix · Vol. {mx['volume']}", mx["audio"], mx["duration"],
                          out, badge="1 HOUR · PRE-RECORDED")
        thumbnails.make(dept, f"1 Hour {dept.title()} Mix", mx["dir"] / f"{mx['id']}_thumb.jpg", badge="1 HOUR MIX")
        loop = out.parent / f"{out.stem}_layers" / "loop.mp4"
        ok = loop.exists() and Path(mx["audio"]).exists()
        notify.text(f"🧪 Mix test ({dept}): {'OK' if ok else 'FAILED'} — {len(mx['chapters'])} "
                    f"tracks, {mx['duration'] / 60:.1f} min rendered (test only, nothing uploaded).")
        db.log("info", "mix", f"test mix {dept} ok={ok} {mx['duration'] / 60:.1f} min")
        shutil.rmtree(mx["dir"], ignore_errors=True)
    except Exception as e:
        notify.problem(f"mix test ({dept}) FAILED: {type(e).__name__}: {str(e)[:300]}")
        raise
    finally:
        os.environ.pop("NB_SCHEDULE__MIX_MIN_MINUTES", None)
        snap.backup(db.get())  # undo: the test leaves no trace in the library or mix history
        db.log("info", "mix", f"test mix {dept} finished; database restored")


# ------------------------------------------------------------------ maintenance
def retry_production():
    """Manual retry (control action): also revives songs abandoned after repeated GPU failures."""
    with db.tx() as c:
        c.execute("UPDATE songs SET status='retry', attempts=0 WHERE status='abandoned'")
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
