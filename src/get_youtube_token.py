"""Разовый скрипт: логинится в Google в браузере и сохраняет refresh token в .env.
Запустить один раз локально:
  python src/get_youtube_token.py       — для EN канала (YT_REFRESH_TOKEN)
  python src/get_youtube_token.py es    — для ES канала (YT_REFRESH_TOKEN_ES)
  python src/get_youtube_token.py pt    — для PT канала (YT_REFRESH_TOKEN_PT)
Понадобится client_secret.json, скачанный из Google Cloud Console
(OAuth client ID, тип "Desktop app", API: YouTube Data API v3).
"""
import os
import subprocess
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

from youtube_auth import SCOPES

ROOT = os.path.join(os.path.dirname(__file__), "..")


ENV_PATH = os.path.join(ROOT, ".env")
REPO = "korovazzz9-jpg/auto-shorts"


def _save(key: str, value: str) -> None:
    """Пишет секрет в .env и в GitHub Secrets. Значение НИКОГДА не печатается и не уходит
    аргументом процесса (аргументы видны через tasklist/ps) — только через stdin."""
    lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, encoding="utf-8") as f:
            lines = [l for l in f.read().splitlines() if not l.startswith(f"{key}=")]
    lines.append(f"{key}={value}")
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  .env: {key} записан")

    proc = subprocess.run(["gh", "secret", "set", key, "--repo", REPO],
                          input=value, text=True)
    print(f"  gh secret: {key} " + ("обновлён" if proc.returncode == 0 else "НЕ обновлён — вручную"))


def _client_secret_path(channel: str) -> str:
    """2026-07-17: у каждого канала свой OAuth-клиент (лимит Google — 50 живых refresh-токенов
    на пару client_id+аккаунт; общий client_id на 3 канала приводил к молчаливому вытеснению
    самого старого токена → серия invalid_grant). Ищем client_secret_<channel>.json, при
    отсутствии — общий client_secret.json (обратная совместимость на время миграции)."""
    per_channel = os.path.join(ROOT, f"client_secret_{channel}.json")
    return per_channel if os.path.exists(per_channel) else os.path.join(ROOT, "client_secret.json")


def main() -> None:
    channel = sys.argv[1].lower() if len(sys.argv) > 1 else "en"
    # EN использует базовое имя, остальные каналы — суффикс _<CHANNEL> (маппится в
    # стандартное YT_REFRESH_TOKEN внутри workflow'а канала). 2026-07-09: обобщено с es-only
    # на любой код канала (нужно под pt/vi/будущие).
    env_key = "YT_REFRESH_TOKEN" if channel == "en" else f"YT_REFRESH_TOKEN_{channel.upper()}"

    secret_path = _client_secret_path(channel)
    per_channel = os.path.basename(secret_path) != "client_secret.json"
    print(f"Авторизация для канала: {channel.upper()} (сохранит в {env_key})")
    print(f"OAuth-клиент: {os.path.basename(secret_path)}"
          f"{'' if per_channel else '  ⚠️ ОБЩИЙ — заведи client_secret_%s.json, см. README' % channel}")
    print("Войдите в браузере под нужным Google аккаунтом.\n")

    flow = InstalledAppFlow.from_client_secrets_file(secret_path, SCOPES)
    creds = flow.run_local_server(port=0)

    # Свой client_id/secret канала тоже кладём в .env и в gh — youtube_auth._client_pair()
    # читает YT_CLIENT_ID_<CH>/YT_CLIENT_SECRET_<CH> с фолбэком на общие.
    if per_channel:
        import json
        conf = json.load(open(secret_path, encoding="utf-8"))["installed"]
        _save(f"YT_CLIENT_ID_{channel.upper()}", conf["client_id"])
        _save(f"YT_CLIENT_SECRET_{channel.upper()}", conf["client_secret"])

    # 2026-07-17: НЕ печатаем сам токен — он утекал в лог/историю терминала (реальный случай:
    # попал в файл фоновой задачи). Значение и так уходит в .env + gh secret через _save().
    print(f"\nТокен получен ({env_key}), длина {len(creds.refresh_token)} симв.")
    _save(env_key, creds.refresh_token)


if __name__ == "__main__":
    main()
