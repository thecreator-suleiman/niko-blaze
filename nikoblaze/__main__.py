"""CLI:  python -m nikoblaze <command>

  plan                  briefs + lyrics + submit today's GPU batch
  collect               fetch finished GPU output, QC, master, render singles, publish
  mixes [dept...]       build/render/publish the hour mixes
  publish               retry pending YouTube uploads
  generate-song DEPT    plan + submit one extra song (afrobeats|reggae|relaxation)
  retry-production      re-submit rejected/planned songs
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
            sid = pipeline._new_song(dept, random.Random(), dept == "afrobeats")
            if sid:
                pipeline.submit([sid])
    elif cmd == "retry-production":
        pipeline.retry_production()
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
