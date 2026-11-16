import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import STATE_DB

SCHEMA = """
CREATE TABLE IF NOT EXISTS songs(
  id TEXT PRIMARY KEY, department TEXT, subgenre TEXT, title TEXT, brief_json TEXT,
  lyrics TEXT, caption TEXT, bpm INT, keyscale TEXT, duration REAL, seed INT,
  fingerprint TEXT, is_single INT DEFAULT 0, status TEXT, attempts INT DEFAULT 0,
  batch_id TEXT, original_asset TEXT, master_asset TEXT, master_duration REAL,
  qc_score REAL, qc_json TEXT, align_json TEXT, used_in_mixes INT DEFAULT 0,
  last_used_in_mix TEXT, created_at TEXT, updated_at TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS batches(
  id TEXT PRIMARY KEY, provider TEXT, status TEXT, submitted_at TEXT,
  finished_at TEXT, gpu_seconds REAL DEFAULT 0, info TEXT);
CREATE TABLE IF NOT EXISTS mixes(
  id TEXT PRIMARY KEY, department TEXT, volume INT, title TEXT, track_ids TEXT,
  tracklist_hash TEXT UNIQUE, duration REAL, chapters TEXT, status TEXT,
  created_at TEXT, updated_at TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS uploads(
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, ref_id TEXT UNIQUE, file_sha256 TEXT,
  youtube_id TEXT, title TEXT, privacy TEXT, publish_at TEXT, status TEXT,
  attempts INT DEFAULT 0, video_asset TEXT, thumb_asset TEXT, error TEXT,
  created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS usage(day TEXT, service TEXT, units REAL, PRIMARY KEY(day, service));
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, level TEXT, stage TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS rights(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ref_kind TEXT, ref_id TEXT, component TEXT,
  status TEXT, note TEXT, UNIQUE(ref_kind, ref_id, component));
"""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path=None) -> sqlite3.Connection:
    path = path or STATE_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


_con = None


def get() -> sqlite3.Connection:
    global _con
    if _con is None:
        _con = connect()
    return _con


def reset(path=None):
    global _con
    if _con is not None:
        _con.close()
    _con = connect(path) if path else None


@contextmanager
def tx():
    con = get()
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise


def log(level: str, stage: str, message: str):
    print(f"[{level.upper()}] {stage}: {message}", flush=True)
    with tx() as c:
        c.execute("INSERT INTO events(ts,level,stage,message) VALUES(?,?,?,?)", (now(), level, stage, message[:2000]))


def kv_get(key, default=None):
    r = get().execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default


def kv_set(key, value):
    with tx() as c:
        c.execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, json.dumps(value)))


def add_usage(service: str, units: float, day: str):
    with tx() as c:
        c.execute("INSERT INTO usage(day,service,units) VALUES(?,?,?) "
                  "ON CONFLICT(day,service) DO UPDATE SET units=units+excluded.units", (day, service, units))


def usage(service: str, day: str) -> float:
    r = get().execute("SELECT units FROM usage WHERE day=? AND service=?", (day, service)).fetchone()
    return r["units"] if r else 0.0


def update(table: str, key: str, key_val, **fields):
    if table in ("songs", "mixes", "uploads"):
        fields.setdefault("updated_at", now())
    cols = ", ".join(f"{k}=?" for k in fields)
    with tx() as c:
        c.execute(f"UPDATE {table} SET {cols} WHERE {key}=?", (*fields.values(), key_val))


def is_paused() -> bool:
    return bool(kv_get("paused", False))
