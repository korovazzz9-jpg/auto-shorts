"""Обменивает authorization code на access+refresh token."""
import os
import requests

CLIENT_KEY = os.environ.get("TIKTOK_CLIENT_KEY", "awlqkv9gr65hjezw")
CLIENT_SECRET = os.environ.get("TIKTOK_CLIENT_SECRET", "")
REDIRECT_URI = "https://60secfacts.netlify.app/callback.html"

with open("tiktok_auth.txt") as f:
    lines = dict(l.strip().split("=", 1) for l in f if "=" in l)

code = lines["code"]
code_verifier = lines["code_verifier"]

resp = requests.post("https://open.tiktokapis.com/v2/oauth/token/", data={
    "client_key": CLIENT_KEY,
    "client_secret": CLIENT_SECRET,
    "code": code,
    "grant_type": "authorization_code",
    "redirect_uri": REDIRECT_URI,
    "code_verifier": code_verifier,
})

data = resp.json()
print(resp.status_code, data)

if "access_token" in data:
    print(f"\naccess_token:  {data['access_token']}")
    print(f"refresh_token: {data.get('refresh_token', 'N/A')}")
    print(f"expires_in:    {data.get('expires_in')} sec")
    print("\nДобавь в GitHub Secrets:")
    print(f"  TIKTOK_ACCESS_TOKEN  = {data['access_token']}")
    print(f"  TIKTOK_REFRESH_TOKEN = {data.get('refresh_token', '')}")
