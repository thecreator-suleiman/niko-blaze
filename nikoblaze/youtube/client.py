"""YouTube Data API: OAuth via refresh token (stored as GitHub secrets), uploads, thumbnails, quota tracking."""
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .. import db
from ..config import cfg

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube"]
COST = {"videos.insert": 1, "thumbnails.set": 50, "liveBroadcasts.insert": 50, "liveStreams.insert": 50,
        "liveBroadcasts.bind": 50, "channels.list": 1}


class QuotaExhausted(RuntimeError):
    pass


def pacific_day() -> str:
    return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")


def spend(method: str):
    db.add_usage("youtube_units" if method != "videos.insert" else "youtube_uploads", COST[method], pacific_day())


def uploads_today() -> int:
    return int(db.usage("youtube_uploads", pacific_day()))


def service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    need = ["YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"]
    missing = [k for k in need if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"YouTube secrets missing: {', '.join(missing)}")
    creds = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"], client_id=os.environ["YT_CLIENT_ID"],
                        client_secret=os.environ["YT_CLIENT_SECRET"], token_uri="https://oauth2.googleapis.com/token",
                        scopes=SCOPES)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def update_video(vid: str, meta: dict, thumb=None, category: str = "10"):
    """Set title/description/tags (+ thumbnail) of one of our own videos, e.g. the running live stream."""
    from googleapiclient.http import MediaFileUpload
    yt = service()
    yt.videos().update(part="snippet", body={"id": vid, "snippet": {
        "title": meta["title"], "description": meta["description"], "tags": meta["tags"][:30],
        "categoryId": category}}).execute()
    if thumb:
        yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb), mimetype="image/jpeg")).execute()


def upload(path, meta: dict, privacy: str, publish_at: str | None = None, thumb=None) -> str:
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
    if uploads_today() >= int(cfg("youtube.max_uploads_per_day", 6)):
        raise QuotaExhausted("daily upload limit (config) reached")
    yt = service()
    status = {"privacyStatus": "private" if privacy == "scheduled" else privacy,
              "selfDeclaredMadeForKids": False,
              "containsSyntheticMedia": bool(cfg("youtube.contains_synthetic_media", False))}
    if privacy == "scheduled" and publish_at:
        status["publishAt"] = publish_at
    body = {"snippet": {"title": meta["title"], "description": meta["description"], "tags": meta["tags"],
                        "categoryId": cfg("youtube.category_id", "10"), "defaultLanguage": "en",
                        "defaultAudioLanguage": "en"}, "status": status}
    media = MediaFileUpload(str(path), chunksize=16 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp, retries = None, 0
    while resp is None:
        try:
            _, resp = req.next_chunk()
        except HttpError as e:
            reason = str(e)
            if "quotaExceeded" in reason or "uploadLimitExceeded" in reason:
                raise QuotaExhausted(reason[:300])
            if e.resp.status in (500, 502, 503, 504) and retries < 6:
                retries += 1
                time.sleep(2 ** retries)
                continue
            raise
    spend("videos.insert")
    vid = resp["id"]
    if thumb and cfg("youtube.set_thumbnails", True):
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb), mimetype="image/jpeg")).execute()
            spend("thumbnails.set")
        except HttpError as e:
            db.log("warn", "youtube", f"thumbnail not set for {vid} (channel may need phone verification): {e}")
    return vid
