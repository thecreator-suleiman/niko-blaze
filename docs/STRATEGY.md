# Channel safety & monetization strategy

YouTube removes or demonetizes channels for: mass-produced/repetitive ("inauthentic") content,
misleading metadata, copyright claims, and undisclosed realistic AI. The system is built against each:

| Risk | Built-in protection |
|---|---|
| Mass-produced look | Max 1 single + 3 Shorts + 1 mix per week (`publishing.max_per_week`). Every video gets its own colour variant and background layout; every song has a unique story brief, title and lyrics (history checks). |
| Repetitive mixes | Each weekly mix is ~100% new songs made that week; tracks are not reused for 60 days. |
| Copyright strikes | Only original generations (ACE-Step, MIT); no samples, no covers, no artist imitation; licence gate blocks unverified parts. |
| AI disclosure | `containsSyntheticMedia: true` on every upload + description note. Never disable. |
| Misleading titles | Titles describe the real content; mixes say "Pre-recorded"; no clickbait words, no fake "live". |
| Spam signals | No tag stuffing (≤ 450 chars), no duplicate uploads (file hash), steady posting times. |

## Growth plan to reach the YouTube Partner Program
Requirements: 1,000 subscribers + 4,000 public watch hours in 12 months (or 10M Shorts views in 90 days).
1. **Shorts (3/week)** bring discovery; each points to the full song.
2. **1-hour mixes (1/week)** build watch hours fastest (study/sleep/relaxation listeners play them for hours).
3. **Singles (1/week)** build the artist identity: real artist photo, consistent name, storytelling lyrics.
4. Use playlists per genre (create once in YouTube Studio) and pin a channel trailer.
5. Human touch (strongly recommended for monetization review): your real artist photo, an "About"
   text in your own words, and replying to a few comments when you can.
6. After ~3 months, check the dashboard: keep the genre with the best watch time on more weeks of the rotation
   (`schedule.mix_rotation`).

Extra free income streams once eligible: YouTube Premium revenue, Shorts revenue share, channel memberships.
