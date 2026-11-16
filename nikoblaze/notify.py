"""Telegram reports: green tick + the posted video, its description and hashtags. Free (Telegram Bot API)."""
import os
import re
from pathlib import Path

import requests

from .audio.analysis import ffmpeg

API = "https://api.telegram.org/bot{token}/{method}"
LIMIT = 48 * 1024 * 1024  # bots may upload up to 50 MB


def enabled() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def _call(method, data=None, files=None):
    r = requests.post(API.format(token=os.environ["TELEGRAM_BOT_TOKEN"], method=method),
                      data={"chat_id": os.environ["TELEGRAM_CHAT_ID"], **(data or {})}, files=files, timeout=600)
    r.raise_for_status()
    return r.json()


def text(msg: str):
    if not enabled():
        return
    for i in range(0, len(msg), 4000):
        try:
            _call("sendMessage", {"text": msg[i:i + 4000], "disable_web_page_preview": "true"})
        except Exception as e:
            print(f"[WARN] telegram: {e}")


def _preview(video: Path) -> Path | None:
    """Telegram-sized copy (<48 MB). Hour mixes are too long to send; their thumbnail is sent instead."""
    if video.stat().st_size <= LIMIT:
        return video
    out = video.with_name(video.stem + "_tg.mp4")
    try:
        ffmpeg("-i", str(video), "-vf", "scale=-2:720", "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
               "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out))
        return out if out.stat().st_size <= LIMIT else None
    except Exception:
        return None


def posted(kind: str, ref: str, meta: dict, video: Path, thumb: Path | None, privacy: str, when: str | None):
    if not enabled():
        return
    vid = ref.split(":")[-1]
    link = f"https://youtu.be/{vid}" if not ref.startswith("uploadpost") else "(link appears in YouTube Studio once processed)"
    tags = " ".join("#" + re.sub(r"\W", "", t) for t in meta["tags"])
    head = (f"✅ POSTED to YouTube — {kind.upper()}\n{meta['title']}\n"
            f"Privacy: {privacy}" + (f" · goes live {when} UTC" if when else "") + f"\n{link}")
    try:
        prev = _preview(Path(video)) if kind != "mix" else None
        if prev:
            with open(prev, "rb") as f:
                _call("sendVideo", {"caption": head[:1024], "supports_streaming": "true"}, {"video": f})
        elif thumb:
            with open(thumb, "rb") as f:
                _call("sendPhoto", {"caption": head[:1024]}, {"photo": f})
        else:
            text(head)
    except Exception as e:
        print(f"[WARN] telegram media: {e}")
        text(head)
    text(f"📝 DESCRIPTION\n{meta['description']}\n\n🏷 TAGS / HASHTAGS\n{tags}")


def problem(msg: str):
    text(f"⚠️ Niko Blaze: {msg}")
