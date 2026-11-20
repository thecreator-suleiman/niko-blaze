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
    "groq": {"url": "https://api.groq.com/openai/v1/chat/completions", "env": "GROQ_API_KEY",
             "model_cfg": "lyrics.groq_model"},
    "openrouter": {"url": "https://openrouter.ai/api/v1/chat/completions", "env": "OPENROUTER_API_KEY",
                   "model_cfg": "lyrics.openrouter_model"},
    "cloudflare": {"url": "https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/v1/chat/completions",
                   "env": "CF_API_TOKEN", "model_cfg": "lyrics.cloudflare_model"},
    # extra free backups (no card). Each is used only if its secret exists; tried in lyrics.providers order.
    "mistral": {"url": "https://api.mistral.ai/v1/chat/completions", "env": "MISTRAL_API_KEY",
                "model_cfg": "lyrics.mistral_model"},
    "cerebras": {"url": "https://api.cerebras.ai/v1/chat/completions", "env": "CEREBRAS_API_KEY",
                 "model_cfg": "lyrics.cerebras_model"},
    "sambanova": {"url": "https://api.sambanova.ai/v1/chat/completions", "env": "SAMBANOVA_API_KEY",
                  "model_cfg": "lyrics.sambanova_model"},
    "nvidia": {"url": "https://integrate.api.nvidia.com/v1/chat/completions", "env": "NVIDIA_API_KEY",
               "model_cfg": "lyrics.nvidia_model"},
}


class NoLLMAvailable(RuntimeError):
    pass


def available() -> list:
    return [p for p in cfg("lyrics.providers", []) if p in PROVIDERS and os.environ.get(PROVIDERS[p]["env"])]


def chat(messages: list, temperature: float = 0.95, skip=()) -> tuple[str, str]:
    """Returns (text, provider). Tries free providers in order; raises NoLLMAvailable if all fail."""
    errors = []
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    names = [n for n in available() if n not in skip] or available()
    for name in names:
        p = PROVIDERS[name]
        for attempt in range(2):
            try:
                url = p["url"].replace("{CF_ACCOUNT_ID}", os.environ.get("CF_ACCOUNT_ID", ""))
                r = requests.post(url, timeout=120, headers={
                    "Authorization": f"Bearer {os.environ[p['env']]}", "Content-Type": "application/json"},
                    json={"model": cfg(p["model_cfg"]), "messages": messages, "temperature": temperature})
                if r.status_code in (401, 403, 404):
                    errors.append(f"{name}: key/model rejected ({r.status_code}) — skipped")
                    break
                if r.status_code in (402, 429):
                    errors.append(f"{name}: rate limited (free tier exhausted for now)")
                    break
                r.raise_for_status()
                db.add_usage(f"llm:{name}", 1, day)
                content = (r.json()["choices"][0]["message"].get("content") or "").strip()
                if not content:
                    errors.append(f"{name}: empty reply")
                    break
                return content, name
            except Exception as e:  # network / 5xx
                errors.append(f"{name}: {e}")
                time.sleep(5)
    raise NoLLMAvailable("; ".join(errors) or "no free LLM credentials configured (GITHUB_TOKEN / GEMINI_API_KEY)")
