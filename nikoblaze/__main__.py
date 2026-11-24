"""CLI:  python -m nikoblaze <command>

  plan                  briefs + lyrics + submit today's GPU batch
  collect               fetch finished GPU output, QC, master, render singles, publish
  mixes [dept...]       build/render/publish the hour mixes
  publish               retry pending YouTube uploads
  generate-song DEPT    plan + submit one extra song (afrobeats|reggae|relaxation)
  retry-production      re-submit rejected/planned songs
  test-backup           send up to 2 waiting songs to the GitHub CPU backup generator
  retry-upload          reset failed uploads and try again
  pause | resume        stop/start all automation
  status                print a JSON status summary
  export-dashboard      write dashboard/data/status.json
  state-pull | state-push   sync the SQLite state with the 'state' GitHub release
  providers             print the music-provider capability matrix
  telegram-test         send a test message to the Telegram bot
  maintenance           prune old originals, weekly DB backup
  reminders             Telegram reminder for API keys close to expiry
"""
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone

from . import db, storage
from .config import DEPARTMENTS, STATE_DB


def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, args = argv[0], argv[1:]
    if cmd == "state-pull":
        storage.pull_state(STATE_DB)
        return 0
    if cmd == "state-push":
        week = datetime.now(timezone.utc).strftime("%G-W%V")
        storage.push_state(STATE_DB, backup_name=f"nikoblaze-{week}.db")
        return 0
    from . import monitor, pipeline
    if cmd == "plan":
        pipeline.plan()
    elif cmd == "collect":
        pipeline.collect()
    elif cmd == "mixes":
        pipeline.daily_mixes(args or None)
    elif cmd == "publish":
        pipeline.publish_pending()
    elif cmd == "generate-song":
        dept = args[0] if args else "afrobeats"
        assert dept in DEPARTMENTS, f"unknown department {dept}"
        if db.is_paused():
            db.log("info", "manual", "paused — resume first")
        else:
            import random
            sub = args[1] if len(args) > 1 else None  # e.g. generate-song afrobeats amapiano
            sid = pipeline._new_song(dept, random.Random(), dept == "afrobeats", sub)
            if sid:
                pipeline.submit([sid])
    elif cmd == "retry-production":
        pipeline.retry_production()
    elif cmd == "withdraw":  # withdraw <song_id> [reason...]: cancel scheduled posts, reject the song
        pipeline.cancel_song(args[0], " ".join(args[1:]) or "withdrawn manually")
    elif cmd == "reschedule":  # reschedule <song_id> <HH:MM | YYYY-MM-DD HH:MM> (Kigali time)
        pipeline.reschedule(args[0], " ".join(args[1:]))
    elif cmd == "api-test":  # does our own (audited) API project publish without the private lock?
        import time, subprocess, tempfile
        from .youtube import client as ytc
        from . import notify
        d = tempfile.mkdtemp()
        v = f"{d}/t.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=1280x720:d=8",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=8", "-shortest", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", v], check=True)
        meta = {"title": "API test (will be deleted)", "description": "test", "tags": [], "category": "10"}
        vid = ytc.upload(v, meta, "unlisted").split(":")[-1]
        time.sleep(90)
        yt = ytc.service()
        st = yt.videos().list(part="status", id=vid).execute()["items"][0]["status"]
        ok = st.get("privacyStatus") == "unlisted"
        print("API TEST", vid, st)
        try:
            yt.videos().delete(id=vid).execute()
            deleted = "deleted"
        except Exception as e:
            deleted = f"NOT deleted ({str(e)[:100]}) - delete it in YouTube Studio"
        notify.text(f"🧪 YouTube API test: {'PASSED — own API can publish publicly' if ok else 'still LOCKED private'} "
                    f"(status {st.get('privacyStatus')}); test video {deleted}.")
    elif cmd == "yt-delete":  # yt-delete <video_id>: remove one of our own videos (e.g. a stray Short)
        from .youtube import client as ytc
        ytc.service().videos().delete(id=args[0]).execute()
        with db.tx() as c:
            c.execute("UPDATE uploads SET status='cancelled' WHERE youtube_id=?", (args[0],))
        db.log("info", "publish", f"deleted video {args[0]}")
    elif cmd == "kaggle-restart":  # stuck Kaggle batch: drop it and push again (a new kernel version replaces it)
        rows = db.get().execute("SELECT * FROM batches WHERE provider='kaggle' AND status='running'").fetchall()
        sids = []
        for b in rows:
            db.update("batches", "id", b["id"], status="error")
            sids += json.loads(b["info"])
        if sids:
            pipeline.submit(sids, providers=["kaggle"])
    elif cmd == "test-mix":
        pipeline.test_mix(args[0] if args else "relaxation")
    elif cmd == "reprocess":
        pipeline.reprocess(args[0] if args else None)
    elif cmd == "stream":
        pipeline.stream_mix()
    elif cmd == "live-check":
        pipeline.announce_live()
    elif cmd == "test-backup":  # send waiting songs to the backup generator (checks the failover path)
        rows = db.get().execute("SELECT id FROM songs WHERE status IN ('retry','planned','abandoned')").fetchall()
        with db.tx() as c:
            c.execute("UPDATE songs SET status='retry', attempts=0 WHERE status='abandoned'")
        if rows:
            pipeline.submit([r["id"] for r in rows][:2], providers=["gha_cpu"])
    elif cmd == "retry-upload":
        pipeline.retry_uploads()
    elif cmd == "pause":
        db.kv_set("paused", True)
        db.log("info", "control", "automation paused")
    elif cmd == "resume":
        db.kv_set("paused", False)
        db.log("info", "control", "automation resumed")
    elif cmd == "status":
        s = monitor.snapshot()
        print(json.dumps({k: s[k] for k in ("paused", "config", "credits", "quality", "departments")}, indent=1,
                         default=str))
    elif cmd == "export-dashboard":
        print(monitor.export())
    elif cmd == "providers":
        from .music.providers import CAPABILITY_MATRIX
        print(json.dumps([asdict(c) for c in CAPABILITY_MATRIX], indent=1, ensure_ascii=False))
    elif cmd == "telegram-test":
        from . import notify
        if not notify.enabled():
            print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID secrets missing")
            return 1
        if not notify.text("✅ Niko Blaze bot connected. You will get a green tick, the video, its description "
                           "and hashtags every time something is posted to YouTube."):
            print("Telegram refused the message: press Start in your bot and check TELEGRAM_CHAT_ID")
            return 1
        print("telegram message sent")
    elif cmd == "gpu-log":
        from .music.providers import get_provider
        print(get_provider("kaggle").error_log())
    elif cmd == "reminders":
        from . import notify
        print("reminders sent:", notify.credential_reminders())
    elif cmd == "maintenance":
        pipeline.prune_originals()
        db.log("info", "maintenance", "weekly maintenance done")
    else:
        print(f"unknown command {cmd}\n{__doc__}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
