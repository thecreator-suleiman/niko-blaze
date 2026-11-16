# Setup (all free, phone-friendly)

Nothing here needs a credit card. Allow about one hour.

## 1. GitHub repository
1. Create a **public** repository (public repos get free, unlimited standard Actions minutes; your
   secrets stay private). Upload this project to it.
2. *Settings → Actions → General → Workflow permissions*: choose **Read and write permissions**.
3. *Settings → Pages → Build and deployment → Source*: **GitHub Actions**.

## 2. Kaggle (free GPU for music generation)
1. Create an account at kaggle.com and **verify your phone number** (*Settings → Phone verification*).
   Without this, notebooks get no GPU and no internet.
2. *Settings → API → Create New Token*. It downloads `kaggle.json` containing `username` and `key`.
3. In GitHub: *Settings → Secrets and variables → Actions → New repository secret*:
   `KAGGLE_USERNAME` and `KAGGLE_KEY`.

## 3. Lyrics (free LLM)
- **GitHub Models** works automatically inside Actions (the workflows request `models: read`).
- Optional backup: create a free key at aistudio.google.com → secret `GEMINI_API_KEY`.
- Read the terms linked in `config/licenses.yaml`, then change `lyrics:github_models` (and `lyrics:gemini`
  if used) from `pending_owner_review` to `verified`. Until then nothing is published.

## 4a. Upload-Post (public uploads from day one — free, 10/month)
1. Sign up at upload-post.com (free plan).
2. *Manage Users* → create a profile (e.g. `nikoblaze`) → connect your YouTube channel with Google.
3. *API Keys* → create a key.
4. GitHub secrets: `UPLOADPOST_API_KEY` (the key) and `UPLOADPOST_USER` (the profile name).

## 4b. Backup lyric AIs (free, optional — add any you can)
- Groq: console.groq.com → API key → secret `GROQ_API_KEY`
- OpenRouter: openrouter.ai → Keys → secret `OPENROUTER_API_KEY`
- Cloudflare: dash.cloudflare.com → Workers AI → API token → secrets `CF_ACCOUNT_ID`, `CF_API_TOKEN`
Then set their `lyrics:*` entries to `verified` in config/licenses.yaml after reading their terms.

## 4c. Your own YouTube API (unlimited later)
1. console.cloud.google.com → create project (no billing needed) → *APIs & Services → Library* →
   enable **YouTube Data API v3**.
2. *OAuth consent screen*: External; app name "Niko Blaze Publisher"; add your Google account as a test
   user; then press **Publish app** (status *In production*). Testing-mode tokens expire after 7 days.
   Google will show an "unverified app" warning — that is expected for your own private use.
3. *Credentials → Create credentials → OAuth client ID* → type **Web application** → authorised redirect
   URI: `https://developers.google.com/oauthplayground`. Copy the client ID and secret.
4. Open developers.google.com/oauthplayground → ⚙️ → tick **Use your own OAuth credentials** → paste
   them. In "Input your own scopes" enter
   `https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube` → *Authorize APIs*
   → sign in with the **channel's** Google account (Advanced → Continue) → *Exchange authorization code for
   tokens* → copy the **Refresh token**.
   (On a computer you can instead run `python scripts/youtube_auth.py client_secret.json`.)
5. Add secrets `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`.
6. Verify the channel by phone at youtube.com/verify (needed for custom thumbnails).
7. Apply for Google's free audit using docs/YOUTUBE_AUDIT.md. Until approved, Upload-Post publishes
   publicly; after approval set `youtube.audited: true`.

## 5. Artist photo (optional but recommended)
Upload an authorised photo as `assets/artist/portrait.jpg` (GitHub web → *Add file → Upload files*), then
set `visual:portrait` to `verified` in `config/licenses.yaml`.

## 6. Switch on publishing
In `config/settings.yaml` set `youtube.enabled: true`.

## 7. First test run (private)
1. *Actions → Produce (plan + GPU batch) → Run workflow*. It writes lyrics and starts the Kaggle job.
   The first Kaggle run downloads the model and can take 1–2 hours.
2. *Actions → Collect → Run workflow* (or wait — it runs every 2 hours).
3. Open your dashboard: `https://<your-user>.github.io/<repo>/`. Check scores, rejections and logs.
4. Watch the **private** video in YouTube Studio. Judge the vocals yourself before going public.
5. Mixes start automatically once each department has ≥ 50 minutes of approved songs.

Everything then runs daily without you. See OPERATIONS.md for controls and troubleshooting.
