"""Free LLM access (OpenAI-compatible chat endpoints). No paid provider is ever called."""
import os
import time
from datetime import datetime, timezone

import requests

from .. import db
from ..config import cfg

PROVIDERS = {
    "github_models": {
        "url": "https://models.github.ai/inference/chat/completions",
        "env": "GITHUB_TOKEN",        # in Actions: permissions: models: read
        "model_cfg": "lyrics.github_model",
    },
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "env": "GEMINI_API_KEY",      # free key from aistudio.google.com (no card)
        "model_cfg": "lyrics.gemini_model",
    },
}


class NoLLMAvailable(RuntimeError):
    pass


def available() -> list:
    return [p for p in cfg("lyrics.providers", []) if p in PROVIDERS and os.environ.get(PROVIDERS[p]["env"])]


def chat(messages: list, temperature: float = 0.95) -> tuple[str, str]:
    """Returns (text, provider). Tries free providers in order; raises NoLLMAvailable if all fail."""
    errors = []
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for name in available():
        p = PROVIDERS[name]
        for attempt in range(2):
            try:
                r = requests.post(p["url"], timeout=120, headers={
                    "Authorization": f"Bearer {os.environ[p['env']]}", "Content-Type": "application/json"},
                    json={"model": cfg(p["model_cfg"]), "messages": messages, "temperature": temperature})
                if r.status_code == 429:
                    errors.append(f"{name}: rate limited (free tier exhausted for now)")
                    break
                r.raise_for_status()
                db.add_usage(f"llm:{name}", 1, day)
                return r.json()["choices"][0]["message"]["content"], name
            except Exception as e:  # network / 5xx
                errors.append(f"{name}: {e}")
                time.sleep(5)
    raise NoLLMAvailable("; ".join(errors) or "no free LLM credentials configured (GITHUB_TOKEN / GEMINI_API_KEY)")
