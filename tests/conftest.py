import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="nbtest-"))
os.environ["NIKOBLAZE_DB"] = str(_tmp / "test.db")
os.environ["NIKOBLAZE_WORK"] = str(_tmp / "work")
for k in ("GITHUB_REPOSITORY", "GITHUB_TOKEN", "GH_TOKEN", "GEMINI_API_KEY"):
    os.environ.pop(k, None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pytest  # noqa: E402
import soundfile as sf  # noqa: E402


@pytest.fixture
def tmp(tmp_path):
    return tmp_path


def synth(path, seconds=30.0, sr=48000, clip=False, noise=False, mono_phase=False, silent=False, seed=1):
    """Synthetic TEST SIGNAL only (never published): bass + melody + hats."""
    t = np.arange(int(sr * seconds)) / sr
    rng = np.random.default_rng(seed)
    if silent:
        x = np.zeros((len(t), 2))
    elif noise:
        x = 0.3 * rng.standard_normal((len(t), 2))
    else:
        bass = 0.45 * np.sin(2 * np.pi * 55 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.5 * t))
        mel = 0.15 * np.sin(2 * np.pi * 440 * t + 3 * np.sin(2 * np.pi * 2 * t))
        air = 0.02 * np.sin(2 * np.pi * 15000 * t)
        hats = 0.04 * rng.standard_normal(len(t)) * (np.sin(2 * np.pi * 4 * t) > 0.8)
        L, R = bass + mel + hats + air, bass + 0.9 * mel + hats + air
        if mono_phase:
            R = -L
        x = np.stack([L, R], 1) * 0.7
    if clip:
        x = np.clip(x * 4, -1, 1)
    sf.write(path, x, sr, subtype="PCM_24")
    return path
