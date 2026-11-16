"""Concrete music providers + documented capability matrix."""
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..config import cfg, work_dir
from .base import Capabilities, Job, Provider

RUNNER = Path(__file__).parent / "kaggle_kernel" / "runner.py"

ACE_STEP = Capabilities(
    name="ACE-Step 1.5 (diffusers AceStepPipeline)",
    male_vocals="Yes — sings supplied lyrics; quality between Suno v4.5 and v5 per its paper. Not human-studio level; QC rejects weak takes.",
    instrumentals="Yes (lyrics '[Instrumental]')",
    african_genres="Prompt-driven; Afrobeats works reasonably, results vary per seed",
    amapiano="Partial — log-drum groove sometimes generic; multiple takes + QC needed",
    reggae="Good for one-drop/lovers rock style grooves",
    api="Python (diffusers), REST server, Gradio",
    hardware="NVIDIA GPU, <4 GB VRAM (offloaded) — runs on free Kaggle T4/P100",
    licence="MIT (code + weights)",
    commercial_use="Allowed by MIT licence",
    quality="Best open-source option for full songs with vocals (2026)",
)

CAPABILITY_MATRIX = [
    ACE_STEP,
    Capabilities("MusicGen (Meta AudioCraft)", "No vocals", "Yes, short clips (≤30 s native)", "Weak", "Weak", "Fair",
                 "Python", "GPU 16 GB for large", "Code MIT, weights CC-BY-NC 4.0", "NO — weights are non-commercial",
                 "Good instrumentals, but unusable for a monetized channel"),
    Capabilities("YuE", "Yes (full songs)", "Yes", "Fair", "Weak", "Fair", "Python", "24 GB+ GPU (too big for free tiers)",
                 "Apache-2.0", "Allowed", "Good vocals but too slow/heavy for free GPU quotas"),
    Capabilities("Stable Audio Open", "No vocals", "Yes (≤47 s)", "Weak", "Weak", "Weak", "Python",
                 "GPU", "Stability AI Community Licence", "Only under revenue threshold; owner must review", "Loops/SFX"),
    Capabilities("Suno free tier", "Yes", "Yes", "Good", "Good", "Good", "No official API", "n/a",
                 "Suno ToS", "NO — free tier is non-commercial; Suno owns free-tier songs", "Excluded from publishing"),
]


class KaggleProvider(Provider):
    """Runs runner.py as a private Kaggle GPU kernel. Needs KAGGLE_USERNAME + KAGGLE_KEY (free, phone-verified)."""
    name = "kaggle"
    capabilities = ACE_STEP

    def __init__(self):
        self.user = os.environ.get("KAGGLE_USERNAME")
        if not self.user or not os.environ.get("KAGGLE_KEY"):
            raise RuntimeError("KAGGLE_USERNAME / KAGGLE_KEY secrets are not set")
        self.slug = f"{self.user}/{cfg('generation.kaggle_kernel_slug')}"

    def _kaggle(self, *args, check=True):
        exe = shutil.which("kaggle") or sys.executable
        cmd = [exe, *args] if exe.endswith("kaggle") else [sys.executable, "-m", "kaggle", *args]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if check and r.returncode != 0:
            raise RuntimeError(f"kaggle {' '.join(args)} failed: {r.stderr or r.stdout}")
        return r.stdout + r.stderr

    def build_kernel(self, jobs: list[Job], dest: Path) -> Path:
        dest.mkdir(parents=True, exist_ok=True)
        conf = {"model_id": cfg("generation.model_id"), "fallback_model_id": cfg("generation.fallback_model_id"),
                "steps": int(cfg("generation.inference_steps", 8))}
        src = RUNNER.read_text().replace("__JOBS__", json.dumps([j.to_dict() for j in jobs])) \
            .replace("__CFG__", json.dumps(conf))
        (dest / "runner.py").write_text(src)
        meta = {"id": self.slug, "title": cfg("generation.kaggle_kernel_slug"), "code_file": "runner.py",
                "language": "python", "kernel_type": "script", "is_private": True, "enable_gpu": True,
                "enable_internet": True, "machine_shape": "NvidiaTeslaT4",
                "dataset_sources": [], "competition_sources": [], "kernel_sources": []}
        (dest / "kernel-metadata.json").write_text(json.dumps(meta, indent=1))
        return dest

    def submit(self, jobs):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        d = self.build_kernel(jobs, work_dir("kaggle", stamp))
        out = self._kaggle("kernels", "push", "-p", str(d))
        if "error" in out.lower() and "successfully" not in out.lower():
            raise RuntimeError(out)
        return f"kaggle-{stamp}"

    def poll(self, batch_id):
        out = self._kaggle("kernels", "status", self.slug, check=False).lower()
        if "complete" in out:
            return "complete"
        if "error" in out or "cancel" in out:
            return "error"
        return "running"

    def fetch(self, batch_id, dest):
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        self._kaggle("kernels", "output", self.slug, "-p", str(dest))
        found = list(dest.rglob("manifest.json"))
        if not found:
            raise RuntimeError("Kaggle output has no manifest.json (run failed before generating)")
        man = json.loads(found[0].read_text())
        man["dir"] = str(found[0].parent)
        return man


class LocalAceStepProvider(Provider):
    """Runs the same runner on a local CUDA machine (e.g. your own PC or a Colab session)."""
    name = "local_acestep"
    capabilities = ACE_STEP

    def submit(self, jobs):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        d = work_dir("local_gen", stamp)
        conf = {"model_id": cfg("generation.model_id"), "fallback_model_id": cfg("generation.fallback_model_id"),
                "steps": int(cfg("generation.inference_steps", 8)), "out_dir": str(d / "out"), "skip_install": True}
        src = RUNNER.read_text().replace("__JOBS__", json.dumps([j.to_dict() for j in jobs])) \
            .replace("__CFG__", json.dumps(conf))
        (d / "runner.py").write_text(src)
        subprocess.run([sys.executable, str(d / "runner.py")], check=True)
        return f"local-{stamp}"

    def poll(self, batch_id):
        return "complete"

    def fetch(self, batch_id, dest):
        d = work_dir("local_gen", batch_id.split("-", 1)[1], "out")
        man = json.loads((d / "manifest.json").read_text())
        man["dir"] = str(d)
        return man


def get_provider(name: str | None = None) -> Provider | None:
    name = name or cfg("generation.provider")
    if name == "kaggle":
        return KaggleProvider()
    if name == "local_acestep":
        return LocalAceStepProvider()
    return None
