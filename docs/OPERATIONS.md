# Operations

## Weekly rhythm (Africa/Kigali)
| When | What |
|---|---|
| Daily 06:10 | Produce: Monday adds the week's single; Mon–Sat add 3 tracks for this week's mix |
| Every 2 h | Collect: QC → master → videos/Shorts → publish queue |
| Sunday 15:40 | Build this week's 1-hour mix (reggae → afrobeats → relaxation rotation) |
| Publishing | Single Fri 18:00 · Shorts Tue/Thu/Sat 17:00 · Mix Sun 20:00 |
| Sunday 04:00 | Maintenance + heartbeat |

## Manual controls
Dashboard buttons, or *Actions → Control (manual) → Run workflow* with an action:
`generate-song`, `generate-mix`, `retry-production`, `retry-upload`, `pause`, `resume`, `publish`, `status`.

## Tuning (config/settings.yaml)
- Volume per day: `daily.singles`, `daily.library_additions` (watch the GPU hours on the dashboard).
- Strictness: `quality.min_score`, `quality.vocal_min_lyric_match`.
- Loudness: `mastering` (default −14 LUFS / −1 dBTP; relaxation −16 LUFS).
- Publishing: `youtube.privacy`, `youtube.schedule_local_times`, `youtube.max_uploads_per_day`.

## Song statuses
`planned → submitted → ready → published`; `retry` = all takes rejected, will regenerate with a new seed;
`abandoned` = failed 3 times, never published.

## Troubleshooting
| Symptom on dashboard | Meaning / fix |
|---|---|
| "free GPU quota for this week is used up" | Normal. Generation resumes when Kaggle's weekly quota renews. |
| "no free lyrics capacity" | GitHub Models/Gemini daily limit hit. Vocal songs resume tomorrow. |
| `blocked_rights` uploads | A component in config/licenses.yaml is not `verified`. Fix, then *retry-upload*. |
| "KAGGLE_USERNAME / KAGGLE_KEY secrets are not set" | Add the secrets (SETUP step 2). |
| Kaggle batch `error` | Open kaggle.com → Code → `niko-blaze-gen` → log. Often: phone not verified, or the GPU type is unavailable (edit `machine_shape` in `nikoblaze/music/providers.py`). |
| YouTube `invalid_grant` | Refresh token expired/revoked: repeat SETUP step 4.4. Make sure the consent screen is *In production*. |
| "no publisher available" | Upload-Post monthly free limit used; videos wait for next month or the API audit. |
| Thumbnail warning | Verify the channel by phone (youtube.com/verify). |
| Scheduled runs stopped | GitHub disables schedules after 60 idle days; run Maintenance once manually. |

## Getting help from Claude later
Start a new Claude session, send the code **12003800**, then describe what to fix and share the
repository link or the error text from the dashboard log.

## Telegram reports
Secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` make the bot send a ✅ message with the posted video (Shorts/singles; thumbnail for hour mixes), the description and hashtags, plus ⚠️ alerts for failures.
