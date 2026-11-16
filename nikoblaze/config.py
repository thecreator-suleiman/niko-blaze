import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("NIKOBLAZE_ROOT", Path(__file__).resolve().parent.parent))
WORK = Path(os.environ.get("NIKOBLAZE_WORK", ROOT / "work"))
STATE_DB = Path(os.environ.get("NIKOBLAZE_DB", ROOT / "state" / "nikoblaze.db"))
ASSETS = ROOT / "assets"
DEPARTMENTS = ("reggae", "afrobeats", "relaxation")


@lru_cache(maxsize=1)
def settings() -> dict:
    with open(ROOT / "config" / "settings.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def licences() -> dict:
    with open(ROOT / "config" / "licenses.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["components"]


def cfg(path: str, default=None):
    """cfg('generation.provider') -> value. Env override: NB_GENERATION__PROVIDER."""
    env = "NB_" + path.upper().replace(".", "__")
    if env in os.environ:
        v = os.environ[env]
        return yaml.safe_load(v)
    node = settings()
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def mastering_target(department: str) -> dict:
    m = cfg("mastering")
    return {**m["default"], **m.get(department, {})}


def work_dir(*parts) -> Path:
    p = WORK.joinpath(*parts)
    p.mkdir(parents=True, exist_ok=True)
    return p
