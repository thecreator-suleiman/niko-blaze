import os
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
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
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", "diffusers==0.43.0", "transformers==5.23.0", "accelerate==1.16.0", "soundfile", "scipy",
                    "faster-whisper==1.2.1"], check=True)

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
import torch  # noqa: E402
from diffusers import AceStepPipeline  # noqa: E402

major, _ = torch.cuda.get_device_capability(0) if torch.cuda.is_available() else (0, 0)
DTYPE = torch.bfloat16  # fp16 always NaNs with ACE-Step XL (T4 too); bf16 is the official dtype
CUDA = torch.cuda.is_available()
DEV = "cuda" if CUDA else "cpu"
if not CUDA:
    torch.set_num_threads(os.cpu_count() or 4)
manifest["gpu"] = torch.cuda.get_device_name(0) if CUDA else "cpu"


manifest["mode"] = "gpu_split"  # denoise on GPU -> park big models in CPU RAM -> decode audio on GPU


def free():
    import gc
    gc.collect()
    if CUDA:
        torch.cuda.empty_cache()


BIG = ("transformer", "text_encoder", "condition_encoder")


def load(model_id, dtype):
    """Kaggle's free T4 has 15 GB. The XL model (~11 GB) fits for denoising, but not together with
    decoding minutes of audio. So we denoise to latents, move the big parts to CPU RAM, then decode."""
    p = AceStepPipeline.from_pretrained(model_id, torch_dtype=dtype, low_cpu_mem_usage=True)
    if not CUDA:  # CPU backup (one take per job): RAM is freed before decoding, see gen()
        p.vae.to(dtype=torch.float32)
        try:
            p.vae.enable_tiling()
        except Exception:
            pass
        return p
    p = p.to("cuda")
    p.vae.to(dtype=torch.float32)  # decode in fp32: avoids NaN on T4 fp16

    # Text + condition encoders (~2.4 GB) are only needed before denoising starts: as soon as the
    # condition encoder has run, move both to CPU RAM so the DiT has room for long songs.
    def _evict(mod, args, out):
        p.text_encoder.to("cpu")
        mod.to("cpu")
        free()
        return out
    p.condition_encoder.register_forward_hook(_evict)
    try:
        p.vae.enable_tiling()
    except Exception:
        pass
    return p


def park(pipe, where):
    if not CUDA:
        return
    for n in BIG:
        m = getattr(pipe, n, None)
        if m is not None:
            m.to(where)
    free()


class LatentNaN(RuntimeError):
    pass


class TooSlow(Exception):
    pass


def _speed_guard(limit_s):
    """Abort a take whose projected denoising time exceeds limit_s (protects the weekly GPU budget)."""
    t0 = time.time()

    def cb(pipe, step, timestep, kw):
        done = step + 1
        if done >= 3:
            proj = (time.time() - t0) / done * STEPS
            if proj > limit_s:
                raise TooSlow(f"projected {proj / 60:.0f} min > {limit_s / 60:.0f} min limit")
        return kw
    return cb


def gen(pipe, job, seed, duration):
    park(pipe, "cuda")  # make sure every part is back on the GPU (a failed take may have left some on CPU)
    g = torch.Generator(DEV).manual_seed(seed)
    if CUDA:
        torch.cuda.reset_peak_memory_stats()
    with torch.inference_mode():
        lat = pipe(prompt=job["caption"], lyrics=job["lyrics"], audio_duration=float(duration),
                   vocal_language=job.get("language", "en"), num_inference_steps=STEPS,
                   guidance_scale=float(CFG.get("hq_guidance", 7.0)),
                   callback_on_step_end=_speed_guard(float(CFG.get("max_take_seconds", 1200))),
                   bpm=job["bpm"], keyscale=job["keyscale"], timesignature="4", generator=g,
                   output_type="latent").audios
        diag = {"lat_finite": bool(torch.isfinite(lat).all()), "lat_absmax": float(lat.float().abs().max())}
        manifest.setdefault("diag", []).append(diag)
        if not diag["lat_finite"]:
            raise LatentNaN(f"latents not finite ({pipe.transformer.dtype})")
        park(pipe, "cpu")
        if not CUDA:  # 16 GB runner: drop the 11 GB of DiT/encoders so the VAE has room to decode
            for n in BIG:
                setattr(pipe, n, None)
            free()
        try:
            audio = pipe.vae.decode(lat.transpose(1, 2).float()).sample.float()
            peak = audio.abs().amax(dim=[1, 2], keepdim=True)
            audio = audio / peak.clamp(min=1.0)
            peak = audio.abs().amax(dim=[1, 2], keepdim=True).clamp(min=1e-6)
            audio = audio * (10.0 ** (-1.0 / 20.0) / peak)
            arr = audio[0].cpu().numpy().T  # (samples, channels)
            diag["audio_absmax"] = float(np.abs(arr).max()) if np.isfinite(arr).all() else "nan"
        finally:
            del lat
            park(pipe, "cuda")
    return arr


def bad(arr):
    if arr is None:
        return True
    return (not np.isfinite(arr).all()) or float(np.abs(arr).max()) < 1e-4


models = [CFG["model_id"], CFG["fallback_model_id"]]
HQ_MODEL = CFG.get("hq_model_id") or CFG["fallback_model_id"]
JOBS = sorted(JOBS, key=lambda j: bool(j.get("hq")))  # fast turbo songs first, then the high-quality singles
all_hq = bool(JOBS) and all(j.get("hq") for j in JOBS)
active = HQ_MODEL if all_hq else models[0]
STEPS = int(CFG.get("hq_steps", 40)) if all_hq else int(CFG["steps"])
pipe = load(active, DTYPE)
manifest["models_loaded"] = [active]
for job in JOBS:
    if job.get("hq") and active != HQ_MODEL:  # singles: SFT model, more steps + guidance = cleaner vocals/mix
        del pipe
        free()
        active, STEPS = HQ_MODEL, int(CFG.get("hq_steps", 40))
        pipe = load(active, DTYPE)
        manifest["models_loaded"].append(active)
    for c in range(job["candidates"]):
        seed = int(job["seed"]) + c * 7919
        name = f"{job['song_id']}_t{c}.wav"
        t = time.time()
        arr, err = None, None
        duration = float(job["duration"])
        for attempt in range(3):
            free()
            to_bf16 = False
            try:
                arr = gen(pipe, job, seed, duration)
                err = None if not bad(arr) else "model returned NaN or silence"
            except TooSlow as e:  # high-quality model too slow on this GPU: finish the batch with turbo
                err = str(e)
                arr = None
                if active != models[0]:
                    del pipe
                    free()
                    active, STEPS = models[0], int(CFG["steps"])
                    pipe = load(active, DTYPE)
                    manifest["models_loaded"].append(f"{active} (hq too slow)")
                    continue
            except LatentNaN as e:
                err = str(e)
                arr = None
                if DTYPE == torch.float16:  # fp16 overflows (NaN) on T4 -> convert in place to bf16 once
                    DTYPE = torch.bfloat16
                    to_bf16 = True
            except Exception as e:
                err = f"{type(e).__name__}: {str(e)[:400]}"
                arr = None
            if err is not None and DTYPE == torch.bfloat16 and to_bf16:
                for n in BIG:  # done outside the except block so no stale references pin GPU memory
                    getattr(pipe, n).to(dtype=torch.bfloat16)
                free()
                manifest["models_loaded"].append(f"{active} -> bf16")
                continue
            if err is None:
                break
            free()
            if "out of memory" in err.lower():
                duration = max(90.0, round(duration * 0.8))  # still too long for this GPU -> shorter song
        if err:
            manifest["errors"].append({"song_id": job["song_id"], "take": c, "error": err,
                                       "model": active, "peak_gb": (round(torch.cuda.max_memory_allocated() / 2**30, 2) if CUDA else 0)})
            save_manifest()
            continue
        sf.write(os.path.join(OUT, name), arr, pipe.sample_rate, subtype="PCM_24")
        manifest["takes"].append({"song_id": job["song_id"], "take": c, "file": name, "seed": seed,
                                  "model": active, "duration": duration, "gen_seconds": round(time.time() - t, 1),
                                  "peak_gb": (round(torch.cuda.max_memory_allocated() / 2**30, 2) if CUDA else 0)})
        save_manifest()

# Free the music model, then transcribe takes (word timestamps) on GPU.
del pipe
free()

# Genre check: an AudioSet music classifier (AST) listens to each take; we keep its genre labels only.
GENRES = {"Pop music", "Hip hop music", "Rock music", "Rhythm and blues", "Soul music", "Reggae", "Ska", "Country",
          "Funk", "Jazz", "Swing music", "Blues", "Disco", "Classical music", "Electronic music", "House music",
          "Techno", "Dubstep", "Drum and bass", "Ambient music", "New-age music", "Music of Africa", "Afrobeat",
          "Music of Latin America", "Salsa music", "Gospel music", "Christian music", "Folk music", "Dance music",
          "Electronic dance music", "Trance music", "Heavy metal", "Punk rock", "Lounge music", "Music of Asia",
          "Carnatic music", "Music of Bollywood", "Flamenco", "Opera", "Orchestra", "Piano", "Electric piano"}
try:
    from transformers import pipeline as hf_pipeline
    from scipy.signal import resample_poly
    from math import gcd
    clf = hf_pipeline("audio-classification", model=CFG.get("genre_model", "MIT/ast-finetuned-audioset-10-10-0.4593"),
                      device=0 if CUDA else -1)
    for take in manifest["takes"]:
        try:
            a, sr = sf.read(os.path.join(OUT, take["file"]), dtype="float32", always_2d=True)
            a = a.mean(axis=1)
            g = gcd(16000, sr)
            a = resample_poly(a, 16000 // g, sr // g).astype("float32")
            n, tot = len(a), {}
            for f in (0.2, 0.4, 0.6, 0.8):  # four 10 s windows across the song
                for r in clf({"raw": a[int(n * f):int(n * f) + 160000], "sampling_rate": 16000}, top_k=None):
                    if r["label"] in GENRES:
                        tot[r["label"]] = tot.get(r["label"], 0) + r["score"] / 4
            take["genres"] = [[k, round(v, 3)] for k, v in sorted(tot.items(), key=lambda x: -x[1])[:5]]
        except Exception as e:
            manifest["errors"].append({"stage": "genre", "song_id": take["song_id"], "error": str(e)[:300]})
    del clf
    free()
    save_manifest()
except Exception as e:
    manifest["errors"].append({"stage": "genre", "error": str(e)[:300]})

try:
    from faster_whisper import WhisperModel

    def _whisper():
        name = CFG.get("whisper_model", "large-v3-turbo")
        if CUDA:
            try:  # ctranslate2 needs CUDA-12 cuBLAS/cuDNN; Kaggle images may ship another CUDA version
                subprocess.run([sys.executable, "-m", "pip", "install", "-q", "nvidia-cublas-cu12",
                                "nvidia-cudnn-cu12==9.*"], check=False, timeout=600)
                import ctypes
                import glob
                import site
                for pat in ("nvidia/cublas/lib/libcublas*.so.12", "nvidia/cublas/lib/libcublasLt*.so.12",
                            "nvidia/cudnn/lib/libcudnn*.so.9"):
                    for sp in site.getsitepackages():
                        for lib in sorted(glob.glob(os.path.join(sp, pat))):
                            try:
                                ctypes.CDLL(lib, mode=ctypes.RTLD_GLOBAL)
                            except OSError:
                                pass
                m = WhisperModel(name, device="cuda", compute_type="float16")
                list(m.transcribe(np.zeros(16000, dtype="float32"))[0])  # fail now, not on the first take
                return m
            except Exception as e:
                manifest["errors"].append({"stage": "transcribe-gpu", "error": str(e)[:300], "fallback": "cpu"})
        return WhisperModel(name if not CUDA else "medium", device="cpu", compute_type="int8")

    wm = _whisper()
    for take in manifest["takes"]:
        job = next(j for j in JOBS if j["song_id"] == take["song_id"])
        a, sr = sf.read(os.path.join(OUT, take["file"]), dtype="float32", always_2d=True)
        a = a.mean(axis=1)
        if sr != 16000:  # decode ourselves: new PyAV broke faster-whisper's file loader (metadata_errors)
            from scipy.signal import resample_poly
            from math import gcd
            g = gcd(16000, sr)
            a = resample_poly(a, 16000 // g, sr // g).astype("float32")
        segs, _ = wm.transcribe(a, language="en", word_timestamps=True,
                                vad_filter=False, beam_size=5)
        take["words"] = [{"w": w.word.strip(), "s": round(w.start, 2), "e": round(w.end, 2),
                          "p": round(w.probability, 3)} for s in segs for w in (s.words or [])]
        save_manifest()
except Exception as e:
    manifest["errors"].append({"stage": "transcribe", "error": str(e)[:500]})
save_manifest()
print("done", json.dumps({k: v for k, v in manifest.items() if k != "takes"}))
