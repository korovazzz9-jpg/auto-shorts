"""Разовый скрипт: логинится в Google в браузере и сохраняет refresh token в .env.
Запустить один раз локально:
  python src/get_youtube_token.py       — для EN канала (YT_REFRESH_TOKEN)
  python src/get_youtube_token.py es    — для ES канала (YT_REFRESH_TOKEN_ES)
  python src/get_youtube_token.py pt    — для PT канала (YT_REFRESH_TOKEN_PT)
Понадобится client_secret.json, скачанный из Google Cloud Console
(OAuth client ID, тип "Desktop app", API: YouTube Data API v3).
"""
import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

from youtube_auth import SCOPES

CLIENT_SECRET_PATH = os.path.join(os.path.dirname(__file__), "..", "client_secret.json")


def main() -> None:
    channel = sys.argv[1].lower() if len(sys.argv) > 1 else "en"
    # EN использует базовое имя, остальные каналы — суффикс _<CHANNEL> (маппится в
    # стандартное YT_REFRESH_TOKEN внутри workflow'а канала). 2026-07-09: обобщено с es-only
    # на любой код канала (нужно под pt/vi/будущие).
    env_key = "YT_REFRESH_TOKEN" if channel == "en" else f"YT_REFRESH_TOKEN_{channel.upper()}"

    print(f"Авторизация для канала: {channel.upper()} (сохранит в {env_key})")
    print("Войдите в браузере под нужным Google аккаунтом.\n")

    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_PATH, SCOPES)
    creds = flow.run_local_server(port=0)

    print(f"\n{env_key}={creds.refresh_token}")

    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            lines = f.readlines()

        updated = False
        new_lines = []
        for line in lines:
            if line.startswith(f"{env_key}="):
                new_lines.append(f"{env_key}={creds.refresh_token}\n")
                updated = True
            else:
                new_lines.append(line)

        if not updated:
            new_lines.append(f"{env_key}={creds.refresh_token}\n")

        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        print(f"\n.env обновлён: {env_key} записан автоматически.")

    # Обновляем GitHub Secret
    print(f"\nОбновляем GitHub Secret {env_key}...")
    ret = os.system(f'gh secret set {env_key} --body "{creds.refresh_token}" --repo korovazzz9-jpg/auto-shorts')
    if ret == 0:
        print(f"GitHub Secret {env_key} обновлён.")
    else:
        print(f"GitHub Secret не обновлён автоматически — обновите вручную.")


if __name__ == "__main__":
    main()
