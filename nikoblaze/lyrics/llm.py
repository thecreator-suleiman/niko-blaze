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


# Model lists change (models get retired -> 404). When the configured model is rejected, the provider's own
# model list is read and the best free chat model is picked automatically, then remembered.
MODELS_URL = {
    "github_models": "https://models.github.ai/catalog/models",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/models",
    "groq": "https://api.groq.com/openai/v1/models",
    "openrouter": "https://openrouter.ai/api/v1/models",
    "cloudflare": "https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/models/search?task=Text%20Generation&per_page=100",
    "mistral": "https://api.mistral.ai/v1/models",
    "cerebras": "https://api.cerebras.ai/v1/models",
    "sambanova": "https://api.sambanova.ai/v1/models",
    "nvidia": "https://integrate.api.nvidia.com/v1/models",
}
PREFER = [r"llama-4-maverick", r"gpt-oss-120b", r"llama-3\.3-70b", r"qwen3-?(235|32)b", r"deepseek-(v3|chat)",
          r"llama-4-scout", r"mistral-(large|medium)", r"gpt-4\.1-mini", r"gpt-4o-mini", r"gemini-2\.5-flash",
          r"mistral-small", r"gemma-3-27b", r"70b", r"instruct"]
AVOID = r"embed|vision|guard|whisper|tts|audio|image|coder|code|ocr|moderation|rerank|distil|tiny|\b[1-8](\.\d)?b\b"


def _url(s: str) -> str:
    return s.replace("{CF_ACCOUNT_ID}", os.environ.get("CF_ACCOUNT_ID", ""))


def model_for(name: str) -> str:
    return db.kv_get(f"llm_model:{name}") or cfg(PROVIDERS[name]["model_cfg"])


def discover(name: str) -> str | None:
    """Pick the best currently-available chat model from the provider's model list."""
    import re
    try:
        r = requests.get(_url(MODELS_URL[name]), timeout=60,
                         headers={"Authorization": f"Bearer {os.environ[PROVIDERS[name]['env']]}"})
        js = r.json()
    except Exception:
        return None
    items = js.get("data") if isinstance(js, dict) else js
    if isinstance(js, dict) and "result" in js:
        items = js["result"]
    ids = []
    for m in items or []:
        mid = m.get("id") or m.get("name") if isinstance(m, dict) else str(m)
        if not mid or re.search(AVOID, mid, re.I):
            continue
        if name == "openrouter" and not mid.endswith(":free"):
            continue  # never a paid model
        ids.append(mid)
    pick = next((mid for pat in PREFER for mid in ids if re.search(pat, mid, re.I)), None)
    if not pick:  # unknown future names: rank by size, prefer chat/instruct models
        def score(mid):
            m = re.findall(r"(\d+(?:\.\d+)?)b(?![a-z])", mid.lower())
            size = max((float(x) for x in m), default=20.0)
            size = size if size <= 700 else 0
            bonus = 15 if re.search(r"instruct|-it\b|chat", mid, re.I) else 0
            malus = 40 if re.search(r"\bvl\b|-vl|omni|nano|lite|preview|reason", mid, re.I) else 0
            return min(size, 120) + bonus - malus
        ranked = sorted(ids, key=score, reverse=True)
        pick = ranked[0] if ranked and score(ranked[0]) >= 15 else None
    if pick:
        db.kv_set(f"llm_model:{name}", pick)
        db.log("info", "lyrics", f"{name}: switched to available model {pick}")
    return pick


def available() -> list:
    return [p for p in cfg("lyrics.providers", []) if p in PROVIDERS and os.environ.get(PROVIDERS[p]["env"])]


def chat(messages: list, temperature: float = 0.95, skip=()) -> tuple[str, str]:
    """Returns (text, provider). Tries free providers in order (preferring those not in `skip`, but falling back
    to them before giving up); raises NoLLMAvailable only if every provider fails."""
    errors = []
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    names = [n for n in available() if n not in skip] + [n for n in available() if n in skip]
    for name in names:
        p = PROVIDERS[name]
        model, rediscovered = model_for(name), False
        for attempt in range(3):
            try:
                r = requests.post(_url(p["url"]), timeout=120, headers={
                    "Authorization": f"Bearer {os.environ[p['env']]}", "Content-Type": "application/json"},
                    json={"model": model, "messages": messages, "temperature": temperature})
                if r.status_code in (400, 404) and not rediscovered:
                    rediscovered = True
                    new = discover(name)
                    if new and new != model:
                        model = new
                        continue
                if r.status_code in (400, 401, 403, 404):
                    errors.append(f"{name}: key/model rejected ({r.status_code}: {r.text[:120]})")
                    break
                if r.status_code in (402, 429):
                    errors.append(f"{name}: rate limited (free tier exhausted for now)")
                    break
                r.raise_for_status()
                try:
                    js = r.json()
                except Exception:
                    errors.append(f"{name}: non-JSON reply ({r.status_code}: {r.text[:120]!r})")
                    break
                db.add_usage(f"llm:{name}", 1, day)
                content = (js["choices"][0]["message"].get("content") or "").strip()
                if not content:
                    errors.append(f"{name}: empty reply")
                    break
                return content, name
            except Exception as e:  # network / 5xx
                errors.append(f"{name}: {str(e)[:150]}")
                time.sleep(5)
    raise NoLLMAvailable("; ".join(errors) or "no free LLM credentials configured")
