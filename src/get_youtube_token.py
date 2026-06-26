"""Разовый скрипт: логинится в Google в браузере и печатает refresh token.
Запустить один раз локально: python src/get_youtube_token.py
Понадобится client_secret.json, скачанный из Google Cloud Console
(OAuth client ID, тип "Desktop app", API: YouTube Data API v3).
"""
import os

from google_auth_oauthlib.flow import InstalledAppFlow

from youtube_auth import SCOPES

CLIENT_SECRET_PATH = os.path.join(os.path.dirname(__file__), "..", "client_secret.json")


def main() -> None:
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_PATH, SCOPES)
    creds = flow.run_local_server(port=0)
    print("\nСохраните эти значения в .env / GitHub Secrets:\n")
    print(f"YT_CLIENT_ID={creds.client_id}")
    print(f"YT_CLIENT_SECRET={creds.client_secret}")
    print(f"YT_REFRESH_TOKEN={creds.refresh_token}")

    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            lines = f.readlines()
        with open(env_path, "w", encoding="utf-8") as f:
            for line in lines:
                if line.startswith("YT_REFRESH_TOKEN="):
                    f.write(f"YT_REFRESH_TOKEN={creds.refresh_token}\n")
                else:
                    f.write(line)
        print("\n.env обновлён автоматически.")


if __name__ == "__main__":
    main()
