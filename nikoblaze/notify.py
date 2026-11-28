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


def audio(path, caption: str) -> bool:
    if not enabled():
        return False
    try:
        with open(path, "rb") as f:
            _call("sendAudio", {"caption": caption[:1000]}, files={"audio": f})
        return True
    except Exception as e:
        print(f"[WARN] telegram audio: {e}")
        return False


def text(msg: str) -> bool:
    if not enabled():
        return False
    ok = True
    for i in range(0, len(msg), 4000):
        try:
            _call("sendMessage", {"text": msg[i:i + 4000], "disable_web_page_preview": "true"})
        except Exception as e:
            ok = False
            print(f"[WARN] telegram: {e}")
    return ok


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
    tags = " ".join("#" + re.sub(r"\W", "", t) for t in meta["tags"])
    if when or ":" in ref:  # handed to a scheduler (uploadpost:, zernio:) — not visible yet
        # Handed over but not visible yet. A separate "✅ LIVE" message with the real link follows.
        head = (f"🕒 SCHEDULED — {kind.upper()}\n{meta['title']}\n"
                + (f"Goes live: {local_time(when)} (Kigali time)\n" if when else "Publishing now…\n")
                + "You'll get a ✅ LIVE message with the YouTube link once it is on the channel.")
    else:
        head = f"✅ LIVE on YouTube — {kind.upper()}\n{meta['title']}\nhttps://youtu.be/{vid}"
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


def local_time(iso: str | None) -> str:
    from datetime import datetime, timedelta
    if not iso:
        return ""
    t = datetime.fromisoformat(iso.replace("Z", "+00:00")) + timedelta(hours=2)  # Kigali = UTC+2, no DST
    return t.strftime("%a %d %b %Y, %H:%M")


def live(kind: str, title: str, video_id: str):
    text(f"✅ LIVE on YouTube — {kind.upper()}\n{title}\nhttps://youtu.be/{video_id}")


def problem(msg: str):
    text(f"⚠️ Niko Blaze: {msg}")


def credential_reminders(today=None) -> list:
    """Daily: Telegram reminder for keys close to expiry (config: expiring_credentials)."""
    from datetime import date
    from .config import cfg
    today = today or date.today()
    sent = []
    for c in cfg("expiring_credentials", []) or []:
        exp, start = c["expires"], c["remind_from"]
        exp = exp if isinstance(exp, date) else date.fromisoformat(str(exp))
        start = start if isinstance(start, date) else date.fromisoformat(str(start))
        if today < start:
            continue
        left = (exp - today).days
        state = f"expires in {left} day(s) ({exp})" if left >= 0 else f"EXPIRED on {exp}"
        msg = (f"⏰ Niko Blaze reminder: your {c['service']} key ({c['secret']}) {state}.\n"
               f"1) Make a new key: {c.get('renew_at', '')}\n"
               f"2) Paste it into GitHub secret {c['secret']}\n"
               f"3) Tell Claude (code 12003800) to update the expiry date so these reminders stop.")
        text(msg)
        sent.append(c["secret"])
    return sent


def photo(path, caption: str = "") -> bool:
    if not enabled():
        return False
    try:
        with open(path, "rb") as f:
            _call("sendPhoto", {"caption": caption[:1000]}, files={"photo": f})
        return True
    except Exception as e:
        print(f"[WARN] telegram photo: {e}")
        return False
