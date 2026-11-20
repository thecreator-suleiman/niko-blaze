"""Free media storage on GitHub Releases (assets up to 2 GiB each). Local folder fallback for development."""
import os
import re
import shutil
import subprocess
from pathlib import Path

from .config import WORK


def _gh_ok() -> bool:
    return bool(os.environ.get("GITHUB_REPOSITORY") and shutil.which("gh") and
                (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")))


def _local(tag: str) -> Path:
    p = WORK / "storage_local" / tag
    p.mkdir(parents=True, exist_ok=True)
    return p


def _gh(*args, check=True):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=3600)
    if check and r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])} failed: {r.stderr.strip()}")
    return r


def ensure_release(tag: str, title: str | None = None):
    if not _gh_ok():
        _local(tag)
        return
    if _gh("release", "view", tag, check=False).returncode != 0:
        _gh("release", "create", tag, "--title", title or tag, "--notes",
            "Automated Niko Blaze storage (not a software release).", "--latest=false", "--prerelease")


def upload(tag: str, path: Path, name: str | None = None) -> str:
    """Upload a file; returns 'tag/name'."""
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name or Path(path).name)  # gh treats 'file#label' specially
    ensure_release(tag)
    if _gh_ok():
        src = Path(path)
        if src.name != name:
            tmp = src.parent / name
            shutil.copy(src, tmp)
            src = tmp
        _gh("release", "upload", tag, str(src), "--clobber")
    else:
        shutil.copy(path, _local(tag) / name)
    return f"{tag}/{name}"


def download(ref: str, dest_dir: Path) -> Path:
    tag, name = ref.split("/", 1)
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / name
    if out.exists():
        return out
    if _gh_ok():
        _gh("release", "download", tag, "--pattern", name, "--dir", str(dest_dir), "--clobber")
    else:
        shutil.copy(_local(tag) / name, out)
    return out


def delete_asset(ref: str):
    tag, name = ref.split("/", 1)
    if _gh_ok():
        _gh("release", "delete-asset", tag, name, "--yes", check=False)
    else:
        (_local(tag) / name).unlink(missing_ok=True)


def asset_url(ref: str) -> str | None:
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo or not ref:
        return None
    tag, name = ref.split("/", 1)
    return f"https://github.com/{repo}/releases/download/{tag}/{name}"


# ---- state database persistence (keeps the git history small) ----
STATE_TAG = "state"


def pull_state(db_path: Path):
    if not _gh_ok():
        return
    if _gh("release", "view", STATE_TAG, check=False).returncode != 0:
        return
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _gh("release", "download", STATE_TAG, "--pattern", db_path.name, "--dir", str(db_path.parent), "--clobber",
        check=False)


def push_state(db_path: Path, backup_name: str | None = None):
    if not _gh_ok() or not db_path.exists():
        return
    ensure_release(STATE_TAG, "State database")
    _gh("release", "upload", STATE_TAG, str(db_path), "--clobber")
    if backup_name:
        b = db_path.parent / backup_name
        shutil.copy(db_path, b)
        _gh("release", "upload", STATE_TAG, str(b), "--clobber")
