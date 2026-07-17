"""Одноразовый OAuth-обмен для Pinterest API v5 (после одобрения Dev App).

Нужно в .env: PINTEREST_APP_ID (число из My Apps) и PINTEREST_KEY (App secret).
Redirect URI должен быть прописан в настройках приложения (у нас —
https://60secfacts.netlify.app/).

Шаг 1: python get_pinterest_token.py            -> печатает URL, открой в браузере, разреши
Шаг 2: python get_pinterest_token.py <code>     -> code из адресной строки после редиректа
        (браузер уйдёт на https://60secfacts.netlify.app/?code=XXXX — скопируй XXXX)

Результат: пишет PINTEREST_ACCESS_TOKEN в .env и показывает список досок для
PINTEREST_BOARD_ID. Refresh-токен тоже сохраняется (access живёт 30 дней,
refresh — год; см. PINTEREST_REFRESH_TOKEN)."""
import base64
import os
import sys

import requests
from dotenv import load_dotenv

ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(ENV_PATH)

APP_ID = os.environ["PINTEREST_APP_ID"]
APP_SECRET = os.environ["PINTEREST_KEY"]
REDIRECT = "https://60secfacts.netlify.app/"
SCOPES = "boards:read,boards:write,pins:read,pins:write,user_accounts:read"


def _set_env(key: str, value: str) -> None:
    with open(ENV_PATH, encoding="utf-8") as f:
        lines = f.read().splitlines()
    lines = [l for l in lines if not l.startswith(f"{key}=")]
    lines.append(f"{key}={value}")
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if len(sys.argv) < 2:
    print("Открой в браузере и разреши доступ:\n")
    print(f"https://www.pinterest.com/oauth/?client_id={APP_ID}"
          f"&redirect_uri={REDIRECT}&response_type=code&scope={SCOPES}")
    print(f"\nПосле редиректа скопируй code из адресной строки и запусти:\n"
          f"  python get_pinterest_token.py <code>")
    sys.exit(0)

code = sys.argv[1].strip()
basic = base64.b64encode(f"{APP_ID}:{APP_SECRET}".encode()).decode()
r = requests.post(
    "https://api.pinterest.com/v5/oauth/token",
    headers={"Authorization": f"Basic {basic}",
             "Content-Type": "application/x-www-form-urlencoded"},
    data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT},
    timeout=30,
)
if not r.ok:
    print("Ошибка обмена:", r.status_code, r.text[:300])
    sys.exit(1)

tok = r.json()
_set_env("PINTEREST_ACCESS_TOKEN", tok["access_token"])
if tok.get("refresh_token"):
    _set_env("PINTEREST_REFRESH_TOKEN", tok["refresh_token"])
print("Токен получен и записан в .env.")

h = {"Authorization": f"Bearer {tok['access_token']}"}
me = requests.get("https://api.pinterest.com/v5/user_account", headers=h, timeout=20).json()
print("Аккаунт:", me.get("username"))
boards = requests.get("https://api.pinterest.com/v5/boards", headers=h, timeout=20).json()
items = boards.get("items", [])
if items:
    print("Доски (id — для PINTEREST_BOARD_ID):")
    for b in items:
        print("  ", b["id"], "—", b["name"])
else:
    print("Досок нет — создай доску в Pinterest и перезапусти с тем же токеном,"
          " либо скажи ассистенту создать через API.")
