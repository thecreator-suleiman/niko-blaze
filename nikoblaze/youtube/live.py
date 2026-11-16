"""Optional scheduled broadcast of a finished hour mix. Needs a PERSISTENT machine you control
(e.g. an old PC/laptop). Disabled by default; never run this on GitHub Actions (their terms forbid
using runners as a streaming server). The broadcast title always says 'Pre-recorded'."""
import subprocess
from datetime import datetime, timedelta, timezone

from ..config import cfg
from . import client


def schedule_and_stream(video_path: str, title: str, description: str, start_in_minutes: int = 10):
    if not cfg("livestream.enabled", False):
        raise RuntimeError("livestream.enabled is false in config/settings.yaml")
    if "pre-recorded" not in title.lower():
        title = f"{title} (Pre-recorded stream)"[:100]
    yt = client.service()
    start = (datetime.now(timezone.utc) + timedelta(minutes=start_in_minutes)).isoformat()
    b = yt.liveBroadcasts().insert(part="snippet,status,contentDetails", body={
        "snippet": {"title": title, "description": description, "scheduledStartTime": start},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
        "contentDetails": {"enableAutoStart": True, "enableAutoStop": True}}).execute()
    client.spend("liveBroadcasts.insert")
    s = yt.liveStreams().insert(part="snippet,cdn", body={
        "snippet": {"title": "niko-blaze-mix"},
        "cdn": {"ingestionType": "rtmp", "resolution": "1080p", "frameRate": "30fps"}}).execute()
    client.spend("liveStreams.insert")
    yt.liveBroadcasts().bind(part="id", id=b["id"], streamId=s["id"]).execute()
    client.spend("liveBroadcasts.bind")
    ing = s["cdn"]["ingestionInfo"]
    url = f"{ing['ingestionAddress']}/{ing['streamName']}"
    subprocess.run(["ffmpeg", "-re", "-i", video_path, "-c:v", "copy", "-c:a", "aac", "-b:a", "256k",
                    "-f", "flv", url], check=True)
    return b["id"]
