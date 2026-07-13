"""Ежедневная проверка живости YouTube OAuth-токенов всех каналов (2026-07-13).

Зачем: refresh-токены Google периодически протухают/отзываются (реальные случаи:
ES 10.07, EN 12.07 — вероятная причина: лимит 50 живых токенов на пару client_id+аккаунт,
либо consent screen в статусе Testing с 7-дневным сроком жизни токенов). Раньше об этом
узнавали ПО ФАКТУ упавшей публикации — слот терялся, чинили в аврале. Теперь дешёвый
чек (1 юнит квоты на канал) каждое утро: протух — алерт в Telegram задолго до слотов,
переавторизация делается спокойно (python src/get_youtube_token.py <канал>).

Запуск: token-health.yml (GitHub-cron, тайминг некритичен). Красный прогон = есть
мёртвый токен (алерт уже отправлен изнутри)."""
import os

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from notify import notify

load_dotenv()

TOKENS = {
    "EN": "YT_REFRESH_TOKEN",
    "ES": "YT_REFRESH_TOKEN_ES",
    "PT": "YT_REFRESH_TOKEN_PT",
}


def _check(refresh_token: str) -> None:
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
    )
    build("youtube", "v3", credentials=creds).channels().list(part="id", mine=True).execute()


def main() -> None:
    dead = []
    for label, env_key in TOKENS.items():
        token = os.environ.get(env_key)
        if not token:
            print(f"  {label}: токен не задан в окружении — пропускаем.")
            continue
        try:
            _check(token)
            print(f"  {label}: OK")
        except Exception as e:
            print(f"  {label}: МЁРТВ — {e}")
            dead.append((label, str(e)[:200]))

    if dead:
        lines = "\n".join(f"• {label}: {err}" for label, err in dead)
        notify(
            "🔴 Токен-чек: протухли YouTube-токены (публикации начнут падать!):\n"
            f"{lines}\n\n"
            "Переавторизуй локально: python src/get_youtube_token.py <en|es|pt>\n"
            "(скрипт сам обновит .env и GitHub Secret)"
        )
        raise SystemExit(1)
    print("Все токены живы.")


if __name__ == "__main__":
    main()
