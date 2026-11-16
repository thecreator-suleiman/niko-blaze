# Applying for the free YouTube API audit (removes the private-only lock)

Form: search "YouTube API Services - Audit and Quota Extension Form" (Google). Answers to use:
- **Use case:** Uploading original music videos to my own channel (Niko Blaze) only. No other users.
- **API methods:** videos.insert, thumbnails.set. Daily usage: about 1 upload per day.
- **Data handling:** No user data is stored or shared; only my own channel is accessed via OAuth.
- **Compliance:** Every upload is marked as altered/synthetic content (containsSyntheticMedia) and labelled honestly.
- **Link/screenshots:** link to the public GitHub repo and the dashboard page.
Approval usually takes a few weeks. Then set `youtube.audited: true` in config/settings.yaml.
