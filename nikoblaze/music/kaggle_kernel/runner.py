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


def gen(pipe, job, seed, duration):
    park(pipe, "cuda")  # make sure every part is back on the GPU (a failed take may have left some on CPU)
    g = torch.Generator(DEV).manual_seed(seed)
    if CUDA:
        torch.cuda.reset_peak_memory_stats()
    with torch.inference_mode():
        lat = pipe(prompt=job["caption"], lyrics=job["lyrics"], audio_duration=float(duration),
                   vocal_language=job.get("language", "en"), num_inference_steps=CFG["steps"],
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
active = models[0]
pipe = load(active, DTYPE)
manifest["models_loaded"] = [active]
for job in JOBS:
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

# Genre check: a music-audio model (CLAP) listens to each take and scores how well it matches genre labels.
GENRES = ["afrobeats", "amapiano", "afropop", "reggae", "dancehall", "jazz", "smooth jazz", "blues", "soul",
          "r&b", "hip hop", "pop", "rock", "house music", "gospel", "classical piano", "ambient", "lo-fi",
          "country", "latin"]
try:
    from transformers import ClapModel, ClapProcessor
    cm_id = CFG.get("genre_model", "laion/larger_clap_music")
    cproc = ClapProcessor.from_pretrained(cm_id)
    cmod = ClapModel.from_pretrained(cm_id).to(DEV).eval()
    with torch.no_grad():
        ti = cproc(text=[f"{g} music" for g in GENRES], return_tensors="pt", padding=True).to(DEV)
        temb = torch.nn.functional.normalize(cmod.get_text_features(**ti), dim=-1)
    for take in manifest["takes"]:
        try:
            a, sr = sf.read(os.path.join(OUT, take["file"]), dtype="float32", always_2d=True)
            a = a.mean(axis=1)
            if sr != 48000:
                from scipy.signal import resample_poly
                from math import gcd
                g = gcd(48000, sr)
                a = resample_poly(a, 48000 // g, sr // g).astype("float32")
            n = len(a)
            clips = [a[int(n * f):int(n * f) + 48000 * 10] for f in (0.2, 0.4, 0.6, 0.8)]
            with torch.no_grad():
                ai = cproc(audios=clips, sampling_rate=48000, return_tensors="pt").to(DEV)
                aemb = torch.nn.functional.normalize(cmod.get_audio_features(**ai), dim=-1).mean(0, keepdim=True)
                sims = (aemb @ temb.T)[0].softmax(-1).tolist()
            take["genres"] = sorted(([g, round(s, 3)] for g, s in zip(GENRES, sims)), key=lambda x: -x[1])[:5]
        except Exception as e:
            manifest["errors"].append({"stage": "genre", "song_id": take["song_id"], "error": str(e)[:300]})
    del cmod
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
