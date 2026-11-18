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


MODES = ["model_offload", "gpu_tiled"]   # tried in order; the one that works is kept for the rest
manifest["modes_tried"] = []


def free():
    import gc
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def load(model_id, dtype, mode):
    """Kaggle T4 = 15 GB. ACE-Step XL needs >=12 GB with offload, so first try diffusers model
    offload; if that breaks (e.g. 'meta tensor') fall back to full-GPU with tiled VAE decode."""
    p = AceStepPipeline.from_pretrained(model_id, torch_dtype=dtype)
    if mode == "model_offload":
        p.enable_model_cpu_offload()
    else:
        p = p.to("cuda")
    for m in ("enable_vae_tiling", "enable_vae_slicing"):
        try:
            getattr(p, m)()
        except Exception:
            pass
    manifest["modes_tried"].append(mode)
    return p


def gen(pipe, job, seed):
    g = torch.Generator("cuda").manual_seed(seed)
    torch.cuda.reset_peak_memory_stats()
    with torch.inference_mode():
        audio = pipe(prompt=job["caption"], lyrics=job["lyrics"], audio_duration=float(job["duration"]),
                     vocal_language=job.get("language", "en"), num_inference_steps=CFG["steps"],
                     bpm=job["bpm"], keyscale=job["keyscale"], timesignature="4", generator=g).audios
    return audio[0].float().cpu().numpy().T  # (samples, channels)


def bad(arr):
    if arr is None:
        return True
    return (not np.isfinite(arr).all()) or float(np.abs(arr).max()) < 1e-4


import traceback  # noqa: E402

mode_i = 0
active = CFG["model_id"]
pipe = load(active, DTYPE, MODES[mode_i])
for job in JOBS:
    for c in range(job["candidates"]):
        seed = int(job["seed"]) + c * 7919
        name = f"{job['song_id']}_t{c}.wav"
        t = time.time()
        arr, last_err = None, None
        while True:
            free()
            try:
                arr = gen(pipe, job, seed)
                if bad(arr) and active != CFG["fallback_model_id"]:
                    raise RuntimeError("NaN/silence")
                break
            except Exception as e:  # out of memory, meta tensor, NaN ... -> next mode / fallback model
                last_err = f"[{MODES[mode_i]}|{active}] {type(e).__name__}: {str(e)[:300]} | " \
                           f"{traceback.format_exc()[-600:]}"
                manifest["errors"].append({"song_id": job["song_id"], "take": c, "error": last_err,
                                           "peak_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2)})
                del pipe
                free()
                if mode_i + 1 < len(MODES):
                    mode_i += 1
                elif active != CFG["fallback_model_id"]:
                    active, mode_i = CFG["fallback_model_id"], 0
                else:
                    pipe = load(active, torch.float16, MODES[mode_i])
                    arr = None
                    break
                pipe = load(active, DTYPE if active == CFG["model_id"] else torch.float16, MODES[mode_i])
        if bad(arr):
            save_manifest()
            continue
        sf.write(os.path.join(OUT, name), arr, pipe.sample_rate, subtype="PCM_24")
        manifest["takes"].append({"song_id": job["song_id"], "take": c, "file": name, "seed": seed,
                                  "model": active, "mode": MODES[mode_i], "gen_seconds": round(time.time() - t, 1),
                                  "peak_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2)})
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
