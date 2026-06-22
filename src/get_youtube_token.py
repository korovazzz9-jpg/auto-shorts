"""Разовый скрипт: логинится в Google в браузере и печатает refresh token.
Запустить один раз локально: python src/get_youtube_token.py
Понадобится client_secret.json, скачанный из Google Cloud Console
(OAuth client ID, тип "Desktop app", API: YouTube Data API v3).
"""
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main() -> None:
    flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
    creds = flow.run_local_server(port=0)
    print("\nСохраните эти значения в .env / GitHub Secrets:\n")
    print(f"YT_CLIENT_ID={creds.client_id}")
    print(f"YT_CLIENT_SECRET={creds.client_secret}")
    print(f"YT_REFRESH_TOKEN={creds.refresh_token}")


if __name__ == "__main__":
    main()
