# NIKO BLAZE — Zero-Budget Autonomous Music Production & YouTube Network

Original Reggae, Afrobeats/Amapiano and Relaxation music, generated with open-source AI on free GPUs,
quality-checked, mastered, turned into vinyl-turntable lyric videos, and published to YouTube — all
orchestrated by GitHub Actions at **zero cost**.

> Setup: **[docs/SETUP.md](docs/SETUP.md)** · Daily operation & fixes: **[docs/OPERATIONS.md](docs/OPERATIONS.md)** ·
> Model research: **[docs/PROVIDERS.md](docs/PROVIDERS.md)**

---

## 1. Feasibility report (November 2026)

### What genuinely runs for free

| Need | Free solution used | Limit that matters |
|---|---|---|
| Song generation with male vocals | **ACE-Step 1.5** (MIT licence) on a **Kaggle** GPU notebook, started from GitHub Actions through the Kaggle API | ~30 GPU-hours/week (Kaggle sets it; can change). Phone-verified Kaggle account needed. |
| Lyrics | **GitHub Models** free tier (uses the workflow's own token); **Gemini** free tier as backup | Daily request caps. If both are exhausted, vocal songs are **skipped** — no filler lyrics. |
| Orchestration, QC, mastering, video rendering | **GitHub Actions** (public repo = free standard runners) | 6 h per job; scheduled workflows are disabled after 60 idle days (a weekly heartbeat commit prevents this). |
| Storage of audio | **GitHub Releases** (2 GiB per file) | Keeps git small. Originals pruned after 60 days; masters kept. |
| Database | SQLite stored as a release asset | — |
| Dashboard | **GitHub Pages** (static; reads a JSON snapshot) | Cannot run anything itself. |
| Publishing | **YouTube Data API** | ~100 uploads/day bucket; thumbnails cost 50 units. **Unverified API projects can only upload *private* videos** until Google's free compliance audit passes. |

### How the hard limits are solved
1. **Vocal quality** — ACE-Step 1.5 (best free commercial option) + 2 takes per song + automatic rejection
   (clipping, noise, dropouts, muffled sound, weak bass, phase, lyric intelligibility via Whisper).
2. **Volume** — quality over quantity: 1 single, 3 Shorts and one brand-new 1-hour mix per week
   (genre rotates weekly). This uses ~2 of Kaggle's ~30 free GPU hours, leaving huge headroom.
3. **Public publishing on day one** — Upload-Post's free API (10 uploads/month) posts publicly and on
   schedule through its own approved YouTube app. Your own YouTube API project takes over (unlimited)
   once Google's free audit approves it (`youtube.audited: true`).
4. **No livestreaming** — not needed: the hour mix is a normal video labelled "(Pre-recorded)".
5. **GitHub terms** — the weekly volume keeps Actions usage light (≈ 2–3 h/week); the Dockerfile can
   move everything to any PC.
6. **Free tiers changing** — backup chains: lyrics GitHub Models → Gemini → Groq → OpenRouter →
   Cloudflare; publishing own API → Upload-Post; if all are unavailable the work waits, never faked.
7. **Monetization** — see [docs/STRATEGY.md](docs/STRATEGY.md).

### Best open-source approach for natural male vocals
**ACE-Step 1.5** (XL-turbo checkpoint, fallback to SFT) via the official `diffusers` `AceStepPipeline`:
MIT licence (commercial use allowed), sings supplied lyrics in English, < 4 GB VRAM when offloaded, fits
Kaggle's free T4/P100. Alternatives were rejected for this use: MusicGen (no vocals, **non-commercial
weights**), YuE (needs 24 GB+), Stable Audio Open (no vocals, licence thresholds), Suno free tier
(**non-commercial**, excluded). Full matrix: `python -m nikoblaze providers` and docs/PROVIDERS.md.

---

## 2. How it works

```
06:10 daily   Produce  → (Mon: single) + 3 tracks for this week's mix → unique briefs → lyrics (LLM + cliché/repetition/history checks) → Kaggle GPU batch
every 2 h     Collect  → download takes → QC score → reject/accept → master (-14 LUFS, -1 dBTP, 24-bit/48 kHz)
                         → store original + master → single video + 3 vertical Shorts → publish queue
Sunday 15:40  Mix      → this week's genre: ~60 min of new songs, chapters, looping vinyl video
Publishing    single Fri 18:00 · Shorts Tue/Thu/Sat 17:00 · mix Sun 20:00 (Kigali)
Sunday        Maintenance → prune old originals, DB backup, heartbeat commit
after each    Pages    → dashboard snapshot
```

Publishing is **blocked** unless every component (model, lyrics provider, portrait, fonts, visuals) is
`verified` in `config/licenses.yaml` — you confirm the lyric-provider terms and your photo rights once.

## 3. Repository layout

```
config/settings.yaml      all tunable behaviour (volumes, durations, loudness, schedule, privacy)
config/licenses.yaml      licensing registry + publishing gate
nikoblaze/
  departments.py          reggae / afrobeats+amapiano / relaxation identities (no other genres)
  lyrics/                 briefs (unique fingerprints), free LLM client, lyric QC, songwriting engine
  music/                  provider interface, Kaggle + local ACE-Step providers, GPU runner script
  audio/                  analysis, quality control & rejection, lyric alignment, mastering
  visual/                 procedural vinyl/turntable art, lyric-synced visualizer, mix loops, thumbnails
  youtube/                OAuth client, uploads, metadata/chapters, optional live broadcast
  mixes.py                hour-mix assembly        pipeline.py   orchestration
  storage.py              GitHub Releases storage  rights.py     licence gate   monitor.py  dashboard data
dashboard/                static GitHub Pages control room (Android + desktop)
.github/workflows/        produce, collect, mixes, control (manual), maintenance, pages, tests
tests/                    16 tests: QC, mastering, alignment, lyrics, visuals, mixes, end-to-end
scripts/youtube_auth.py   one-time OAuth helper
```

## 4. Status of this build

Implemented and tested here (CPU, synthetic test signals): lyric QC, briefs, QC/rejection, mastering,
alignment, visualizer, thumbnails, mix assembly/looping, rights gate, metadata, dashboard export,
end-to-end flow with a fake GPU. **Not yet run against real services** (needs your free accounts):
Kaggle GPU generation, GitHub Models/Gemini calls, YouTube upload. Follow docs/SETUP.md step 7 for the
first private test run.
