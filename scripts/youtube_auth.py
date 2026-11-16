"""One-time helper to get a YouTube refresh token on a computer with a browser.
(No computer? Use the OAuth Playground method in docs/SETUP.md — works from a phone.)

  pip install google-auth-oauthlib
  python scripts/youtube_auth.py path/to/client_secret.json
"""
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube"]

flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
print("\nAdd these as GitHub repository secrets:\n")
print("YT_CLIENT_ID      =", creds.client_id)
print("YT_CLIENT_SECRET  =", creds.client_secret)
print("YT_REFRESH_TOKEN  =", creds.refresh_token)
