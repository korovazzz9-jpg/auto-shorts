"""Локальный OAuth для получения TikTok access token.
Запусти: python src/get_tiktok_token.py
Откроется браузер → авторизуй → вставь redirect URL сюда.
"""
import hashlib
import os
import secrets
import urllib.parse
import webbrowser

CLIENT_KEY = os.environ.get("TIKTOK_CLIENT_KEY", "awlqkv9gr65hjezw")
REDIRECT_URI = "https://korovazzz9-jpg.github.io/pages/callback.html"
SCOPES = "video.publish,video.upload"

code_verifier = secrets.token_urlsafe(64)
code_challenge = hashlib.sha256(code_verifier.encode()).digest()
import base64
code_challenge_b64 = base64.urlsafe_b64encode(code_challenge).rstrip(b"=").decode()

params = {
    "client_key": CLIENT_KEY,
    "redirect_uri": REDIRECT_URI,
    "response_type": "code",
    "scope": SCOPES,
    "code_challenge": code_challenge_b64,
    "code_challenge_method": "S256",
    "state": secrets.token_hex(8),
}
auth_url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode(params)

print("Открываю браузер для авторизации TikTok...")
print(f"\nURL: {auth_url}\n")
webbrowser.open(auth_url)

print("После авторизации тебя перенаправит на страницу callback.")
print("Скопируй ПОЛНЫЙ URL из адресной строки браузера и вставь сюда:")
redirect_url = input("URL: ").strip()

parsed = urllib.parse.urlparse(redirect_url)
code = urllib.parse.parse_qs(parsed.query).get("code", [None])[0]
if not code:
    print("Код не найден в URL. Проверь ссылку.")
    exit(1)

print(f"\nКод авторизации: {code}")
print(f"Code verifier: {code_verifier}")
print("\nТеперь запусти exchange_tiktok_token.py с этими значениями.")

with open("tiktok_auth.txt", "w") as f:
    f.write(f"code={code}\n")
    f.write(f"code_verifier={code_verifier}\n")
print("Сохранено в tiktok_auth.txt")
