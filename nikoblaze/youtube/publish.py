"""Publisher chain: own YouTube API (once audited) -> Upload-Post free API (public immediately).
If every publisher is unavailable the video simply waits in the queue — it is never lost or faked."""
import os
from pathlib import Path
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


ZERNIO = "https://zernio.com/api/v1"


def _ai_label() -> bool:
    return bool(cfg("youtube.contains_synthetic_media", False))


def _zernio_put(path, content_type) -> str:
    h = {"Authorization": f"Bearer {os.environ['ZERNIO_API_KEY']}"}
    r = requests.post(f"{ZERNIO}/media/presign", headers=h, timeout=60,
                      json={"filename": Path(path).name, "contentType": content_type, "size": Path(path).stat().st_size})
    r.raise_for_status()
    js = r.json()
    with open(path, "rb") as f:
        requests.put(js["uploadUrl"], data=f, headers={"Content-Type": content_type}, timeout=3600).raise_for_status()
    return js["publicUrl"]


def _zernio_account() -> str:
    acc = os.environ.get("ZERNIO_ACCOUNT_ID")
    if acc:
        return acc
    h = {"Authorization": f"Bearer {os.environ['ZERNIO_API_KEY']}"}
    js = requests.get(f"{ZERNIO}/accounts", headers=h, timeout=60).json()
    for a in js.get("accounts", js if isinstance(js, list) else []):
        if a.get("platform") == "youtube":
            return a.get("_id") or a.get("id")
    raise RuntimeError("no YouTube channel connected in Zernio")


def zernio(video, meta, publish_at=None, thumb=None) -> str:
    """Zernio free plan: unlimited posts for up to 2 connected accounts, uses Zernio's audited Google app."""
    item = {"type": "video", "url": _zernio_put(video, "video/mp4")}
    if thumb:
        item["thumbnail"] = _zernio_put(thumb, "image/jpeg")
    psd = {"title": meta["title"][:100], "visibility": "public", "categoryId": "10", "madeForKids": False,
           "containsSyntheticMedia": _ai_label()}
    body = {"content": meta["description"][:5000], "mediaItems": [item], "tags": meta["tags"][:15],
            "platforms": [{"platform": "youtube", "accountId": _zernio_account(), "platformSpecificData": psd}]}
    if publish_at:
        body.update({"scheduledFor": publish_at.replace("Z", ""), "timezone": "UTC"})
    else:
        body["publishNow"] = True
    h = {"Authorization": f"Bearer {os.environ['ZERNIO_API_KEY']}", "Content-Type": "application/json"}
    r = requests.post(f"{ZERNIO}/posts", headers=h, json=body, timeout=600)
    if r.status_code == 400 and "containsSyntheticMedia" in r.text:
        psd.pop("containsSyntheticMedia")
        r = requests.post(f"{ZERNIO}/posts", headers=h, json=body, timeout=600)
    if r.status_code >= 300:
        raise RuntimeError(f"Zernio {r.status_code}: {r.text[:300]}")
    post = r.json().get("post", {})
    return "zernio:" + str(post.get("_id") or post.get("id") or "")


def upload_post(video, meta, publish_at=None, thumb=None) -> str:
    data = [("user", os.environ["UPLOADPOST_USER"]), ("platform[]", "youtube"), ("title", meta["title"]),
            ("description", meta["description"]), ("privacyStatus", "public"),
            ("categoryId", cfg("youtube.category_id", "10")), ("selfDeclaredMadeForKids", "false"),
            ("containsSyntheticMedia", "true" if _ai_label() else "false"), ("async_upload", "true")]
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


def _reserve(kind: str) -> int:
    """Free plan = 10 uploads/month. Shorts may only use a slot if enough are left for the weekly single + mix
    for the rest of the month (2 per remaining week)."""
    if kind != "short":
        return 0
    from datetime import datetime, timezone
    import calendar
    now = datetime.now(timezone.utc)
    days_left = calendar.monthrange(now.year, now.month)[1] - now.day
    return int(cfg("publishing.long_uploads_per_week", 2)) * (days_left // 7 + 1)


def publish(video, meta, publish_at=None, thumb=None, kind: str = "single") -> tuple[str, str]:
    """Returns (video_ref, privacy)."""
    have_api = all(os.environ.get(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))
    errors = []
    for name in cfg("publishing.order", []):
        try:  # one publisher failing (API down, key revoked, rule change) must not block the next one
            if name == "youtube_api_audited" and have_api and cfg("youtube.audited", False):
                privacy = "scheduled" if publish_at else "public"
                return yt.upload(video, meta, privacy, publish_at, thumb), privacy
            if name == "zernio" and os.environ.get("ZERNIO_API_KEY"):
                return zernio(video, meta, publish_at, thumb), "public"
            if name == "upload_post" and os.environ.get("UPLOADPOST_API_KEY") and upload_post_left() > _reserve(kind):
                return upload_post(video, meta, publish_at, thumb), "public"
            if name == "youtube_api_private" and have_api:
                return yt.upload(video, meta, "private", None, thumb), "private"
        except Exception as e:
            errors.append(f"{name}: {str(e)[:300]}")
    if errors:
        raise NoPublisher("all publishers failed — queued: " + " | ".join(errors))
    raise NoPublisher("no publisher available right now (monthly free limit used / not configured) — queued")
