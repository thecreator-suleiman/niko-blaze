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

### What cannot be done for free (honest limits)

1. **"Professionally produced, human-quality" vocals are not guaranteed.** ACE-Step 1.5 is the best
   free option with singing (its own paper ranks it between Suno v4.5 and v5), but takes vary. The system
   generates 2 takes per song and **rejects** takes that fail objective checks (clipping, noise, dropouts,
   muffled audio, weak bass, phase problems, and *lyric intelligibility* measured by Whisper). It cannot judge
   taste — listen to early results and tune `config/settings.yaml`.
2. **Three brand-new hours of music every day** is beyond the free GPU quota. Each day adds new tracks
   (default: 2 Afrobeats singles + 3 reggae + 3 relaxation + 1 extra afrobeats) and each hour mix is a
   **new, never-repeated sequence** drawn from the growing library, favouring unused/newest tracks.
   Mixes are skipped (not padded) until a department has ≥ 50 minutes of approved music (≈ 1–2 weeks).
3. **24/7 livestreaming is not free.** GitHub's terms forbid using Actions as a streaming server.
   Mixes are uploaded as normal videos titled **"(Pre-recorded)"**. `nikoblaze/youtube/live.py` can run a
   scheduled broadcast from a machine you own (old PC/laptop) — disabled by default.
4. **GitHub Actions terms risk.** GitHub says Actions should be used for work related to the repository's
   software. Heavy daily media rendering for a YouTube channel is a grey area; GitHub could limit the
   account. Mitigation: the whole pipeline also runs from the included `Dockerfile` on any machine.
5. **Free tiers can change** within 2–3 years (Kaggle quota, GitHub Models limits). The system watches
   usage, pauses gracefully, and logs the reason — it never reports fake success.
6. **Monetization is not guaranteed.** YouTube's *inauthentic / mass-produced content* policy can
   demonetize channels that upload many near-identical AI videos. Keep volume modest, keep stories varied,
   and always keep the AI disclosure (`containsSyntheticMedia: true`, already set).

### Best open-source approach for natural male vocals
**ACE-Step 1.5** (XL-turbo checkpoint, fallback to SFT) via the official `diffusers` `AceStepPipeline`:
MIT licence (commercial use allowed), sings supplied lyrics in English, < 4 GB VRAM when offloaded, fits
Kaggle's free T4/P100. Alternatives were rejected for this use: MusicGen (no vocals, **non-commercial
weights**), YuE (needs 24 GB+), Stable Audio Open (no vocals, licence thresholds), Suno free tier
(**non-commercial**, excluded). Full matrix: `python -m nikoblaze providers` and docs/PROVIDERS.md.

---

## 2. How it works

```
06:10 Kigali  Produce  → unique briefs → lyrics (LLM + cliché/repetition/history checks) → Kaggle GPU batch
every 2 h     Collect  → download takes → QC score → reject/accept → master (-14 LUFS, -1 dBTP, 24-bit/48 kHz)
                         → store original + master → singles: lyric-synced vinyl video + thumbnail → YouTube
15:40 Kigali  Mixes    → per department: ~60 min crossfaded mix + chapters → looping vinyl video → YouTube
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
