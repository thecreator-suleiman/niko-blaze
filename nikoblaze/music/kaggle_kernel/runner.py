# Niko Blaze GPU runner — executed on a free Kaggle GPU notebook (or any CUDA machine).
# Generates takes with ACE-Step 1.5 (MIT) via diffusers, then transcribes each take with
# faster-whisper (MIT) for lyric timing and intelligibility checks.
# JOBS/CFG are injected by nikoblaze.music.kaggle_provider at push time.
import json
import os
import subprocess
import sys
import time

JOBS = json.loads(r'''__JOBS__''')
CFG = json.loads(r'''__CFG__''')
OUT = CFG.get("out_dir", "/kaggle/working/out")
os.makedirs(OUT, exist_ok=True)
T0 = time.time()
manifest = {"takes": [], "errors": [], "model": CFG["model_id"]}


def save_manifest():
    manifest["runtime_seconds"] = round(time.time() - T0, 1)
    with open(os.path.join(OUT, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)


if not CFG.get("skip_install"):
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", "diffusers>=0.39.0", "transformers",
                    "accelerate", "soundfile", "faster-whisper"], check=True)

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
import torch  # noqa: E402
from diffusers import AceStepPipeline  # noqa: E402

major, _ = torch.cuda.get_device_capability(0) if torch.cuda.is_available() else (0, 0)
DTYPE = torch.bfloat16 if major >= 8 else torch.float16
manifest["gpu"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"


def load(model_id, dtype):
    p = AceStepPipeline.from_pretrained(model_id, torch_dtype=dtype)
    total = torch.cuda.get_device_properties(0).total_memory / 2**30 if torch.cuda.is_available() else 0
    if total and total < 14:
        p.enable_model_cpu_offload()
    else:
        p = p.to("cuda")
    return p


def bad(arr):
    return (not np.isfinite(arr).all()) or float(np.abs(arr).max()) < 1e-4


pipe, active = load(CFG["model_id"], DTYPE), CFG["model_id"]
for job in JOBS:
    for c in range(job["candidates"]):
        seed = int(job["seed"]) + c * 7919
        name = f"{job['song_id']}_t{c}.wav"
        t = time.time()
        try:
            for attempt in range(2):
                g = torch.Generator("cuda").manual_seed(seed)
                audio = pipe(prompt=job["caption"], lyrics=job["lyrics"], audio_duration=float(job["duration"]),
                             vocal_language=job.get("language", "en"), num_inference_steps=CFG["steps"],
                             bpm=job["bpm"], keyscale=job["keyscale"], timesignature="4", generator=g).audios
                arr = audio[0].float().cpu().numpy().T  # (samples, channels)
                if not bad(arr):
                    break
                if active != CFG["fallback_model_id"]:  # NaN/silence -> switch to fallback model once
                    del pipe
                    torch.cuda.empty_cache()
                    pipe, active = load(CFG["fallback_model_id"], torch.float16), CFG["fallback_model_id"]
            if bad(arr):
                raise RuntimeError("model returned NaN or silence")
            sf.write(os.path.join(OUT, name), arr, pipe.sample_rate, subtype="PCM_24")
            manifest["takes"].append({"song_id": job["song_id"], "take": c, "file": name, "seed": seed,
                                      "model": active, "gen_seconds": round(time.time() - t, 1)})
        except Exception as e:
            manifest["errors"].append({"song_id": job["song_id"], "take": c, "error": str(e)[:500]})
        save_manifest()

# Free the music model, then transcribe takes (word timestamps) on GPU.
del pipe
torch.cuda.empty_cache()
try:
    from faster_whisper import WhisperModel
    wm = WhisperModel(CFG.get("whisper_model", "large-v3-turbo"), device="cuda", compute_type="float16")
    for take in manifest["takes"]:
        job = next(j for j in JOBS if j["song_id"] == take["song_id"])
        segs, _ = wm.transcribe(os.path.join(OUT, take["file"]), language="en", word_timestamps=True,
                                vad_filter=False, beam_size=5)
        take["words"] = [{"w": w.word.strip(), "s": round(w.start, 2), "e": round(w.end, 2),
                          "p": round(w.probability, 3)} for s in segs for w in (s.words or [])]
        save_manifest()
except Exception as e:
    manifest["errors"].append({"stage": "transcribe", "error": str(e)[:500]})
save_manifest()
print("done", json.dumps({k: v for k, v in manifest.items() if k != "takes"}))
