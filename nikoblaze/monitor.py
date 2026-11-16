"""Exports a status.json snapshot for the static GitHub Pages dashboard."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from . import db, rights, storage
from .config import DEPARTMENTS, ROOT, cfg
from .lyrics import llm
from .pipeline import gpu_budget_left, gpu_seconds_last_7_days, today
from .visual.assets import load_portrait
from .youtube.client import pacific_day


def _rows(sql, *a):
    return [dict(r) for r in db.get().execute(sql, a).fetchall()]


def snapshot() -> dict:
    songs = _rows("SELECT id,department,subgenre,title,status,qc_score,is_single,attempts,error,created_at,"
                  "master_duration FROM songs ORDER BY created_at DESC LIMIT 120")
    uploads = _rows("SELECT kind,ref_id,youtube_id,title,privacy,publish_at,status,error,updated_at "
                    "FROM uploads ORDER BY updated_at DESC LIMIT 80")
    for u in uploads:
        u["thumb"] = storage.asset_url(f"thumbs/{u['ref_id']}.jpg")
    depts = {}
    for d in DEPARTMENTS:
        lib = db.get().execute("SELECT COUNT(*) n, COALESCE(SUM(master_duration),0) s FROM songs WHERE department=? "
                               "AND status IN ('ready','published')", (d,)).fetchone()
        last_mix = _rows("SELECT id,title,status,duration,created_at,error FROM mixes WHERE department=? "
                         "ORDER BY created_at DESC LIMIT 1", d)
        depts[d] = {"library_tracks": lib["n"], "library_minutes": round(lib["s"] / 60, 1),
                    "last_mix": last_mix[0] if last_mix else None,
                    "today_new": db.get().execute("SELECT COUNT(*) n FROM songs WHERE department=? AND status IN "
                                                  "('ready','published') AND created_at >= date('now')", (d,)).fetchone()["n"]}
    qc = _rows("SELECT AVG(qc_score) avg, SUM(status IN ('ready','published')) ok, "
               "SUM(status IN ('retry','abandoned')) rejected FROM songs")[0]
    _, portrait_ok = load_portrait()
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": os.environ.get("GITHUB_REPOSITORY", ""),
        "artist": cfg("artist"),
        "paused": db.is_paused(),
        "today": today(),
        "config": {"provider": cfg("generation.provider"), "youtube_enabled": cfg("youtube.enabled"),
                   "privacy": cfg("youtube.privacy"), "llm_available": llm.available()},
        "credits": {
            "kaggle_gpu_hours_used_7d": round(gpu_seconds_last_7_days() / 3600, 2),
            "kaggle_gpu_hours_left": round(max(0, gpu_budget_left()) / 3600, 2),
            "kaggle_weekly_limit": cfg("generation.kaggle_weekly_gpu_hours"),
            "youtube_uploads_today": db.usage("youtube_uploads", pacific_day()),
            "youtube_units_today": db.usage("youtube_units", pacific_day()),
            "llm_calls_today": {p: db.usage(f"llm:{p}", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
                                for p in ("github_models", "gemini")},
        },
        "quality": {"average_score": round(qc["avg"] or 0, 1), "accepted": qc["ok"] or 0, "rejected": qc["rejected"] or 0},
        "departments": depts,
        "songs": songs,
        "uploads": uploads,
        "batches": _rows("SELECT id,status,submitted_at,finished_at,gpu_seconds FROM batches ORDER BY submitted_at DESC LIMIT 20"),
        "licensing": {"components": rights.summary(), "portrait_file_present": portrait_ok},
        "events": _rows("SELECT ts,level,stage,message FROM events ORDER BY id DESC LIMIT 150"),
    }


def export(path: Path | None = None) -> Path:
    path = path or ROOT / "dashboard" / "data" / "status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot(), indent=1, default=str))
    return path
