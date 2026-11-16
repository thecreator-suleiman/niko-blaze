"""Publisher chain: own YouTube API (once audited) -> Upload-Post free API (public immediately).
If every publisher is unavailable the video simply waits in the queue — it is never lost or faked."""
import os
from datetime import datetime, timezone

import requests

from .. import db
from ..config import cfg
from . import client as yt


class NoPublisher(RuntimeError):
    pass


def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def upload_post_left() -> int:
    if not (os.environ.get("UPLOADPOST_API_KEY") and os.environ.get("UPLOADPOST_USER")):
        return 0
    return int(cfg("publishing.upload_post_monthly_limit", 10) - db.usage("upload_post", _month()))


def upload_post(video, meta, publish_at=None, thumb=None) -> str:
    data = [("user", os.environ["UPLOADPOST_USER"]), ("platform[]", "youtube"), ("title", meta["title"]),
            ("description", meta["description"]), ("privacyStatus", "public"),
            ("categoryId", cfg("youtube.category_id", "10")), ("selfDeclaredMadeForKids", "false"),
            ("containsSyntheticMedia", "true"), ("async_upload", "true")]
    data += [("tags[]", t) for t in meta["tags"]]
    if publish_at:
        data += [("scheduled_date", publish_at), ("timezone", "UTC")]
    files = {"video": open(video, "rb")}
    if thumb:
        files["thumbnail"] = open(thumb, "rb")
    try:
        r = requests.post("https://api.upload-post.com/api/upload", data=data, files=files, timeout=3600,
                          headers={"Authorization": f"Apikey {os.environ['UPLOADPOST_API_KEY']}"})
    finally:
        for f in files.values():
            f.close()
    if r.status_code in (402, 429):
        raise yt.QuotaExhausted(f"Upload-Post limit: {r.text[:200]}")
    r.raise_for_status()
    j = r.json()
    db.add_usage("upload_post", 1, _month())
    return "uploadpost:" + str(j.get("request_id") or j.get("job_id") or "ok")


def publish(video, meta, publish_at=None, thumb=None) -> tuple[str, str]:
    """Returns (video_ref, privacy)."""
    have_api = all(os.environ.get(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))
    for name in cfg("publishing.order", []):
        if name == "youtube_api_audited" and have_api and cfg("youtube.audited", False):
            privacy = "scheduled" if publish_at else "public"
            return yt.upload(video, meta, privacy, publish_at, thumb), privacy
        if name == "upload_post" and upload_post_left() > 0:
            return upload_post(video, meta, publish_at, thumb), "public"
        if name == "youtube_api_private" and have_api:
            return yt.upload(video, meta, "private", None, thumb), "private"
    raise NoPublisher("no publisher available right now (monthly free limit used / not configured) — queued")
