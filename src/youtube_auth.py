"""Общая авторизация YouTube Data API для скриптов загрузки и чтения статистики."""
import os

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from config import CHANNEL

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",  # нужен для загрузки caption-треков
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def _default_refresh_token() -> str:
    """2026-07-08, найдено на живом прогоне: локальный `CHANNEL=es python weekly_report.py`
    молча брал EN-токен и считал EN-данные под ES-заголовком — в проде (GitHub Actions) это
    не баг, workflow сам мапит секрет `YT_REFRESH_TOKEN_ES` в стандартное имя для job'а
    ES-канала, а локально маппинга никто не делает. Теперь: если задан `YT_REFRESH_TOKEN_<CHANNEL>`
    (например `YT_REFRESH_TOKEN_ES`) — берём его; для EN такой переменной нет — поведение
    не меняется, как и для GH Actions (там в окружении только уже замапленный YT_REFRESH_TOKEN)."""
    suffixed = os.environ.get(f"YT_REFRESH_TOKEN_{CHANNEL.upper()}")
    return suffixed or os.environ["YT_REFRESH_TOKEN"]


def _client_pair(channel: str | None = None) -> tuple[str, str]:
    """(client_id, client_secret) для канала. 2026-07-17: у каждого канала СВОЙ OAuth-клиент.

    Причина: лимит Google — 50 живых refresh-токенов на пару (client_id + Google-аккаунт);
    при превышении САМЫЙ СТАРЫЙ токен молча инвалидируется. Все 3 канала висели на одном
    client_id и одном аккаунте, то есть делили один счётчик — каждый перевыпуск приближал
    вытеснение чужого рабочего токена. Отсюда серия `invalid_grant` без всякой периодичности
    (ES 10.07, EN 12.07, EN 17.07). Отдельный client_id = отдельный счётчик на канал.

    Фолбэк на общие YT_CLIENT_ID/SECRET оставлен намеренно: позволяет переводить каналы по
    одному и не ломает GH Actions, где ещё не заведены суффиксные секреты."""
    ch = (channel or CHANNEL).upper()
    cid = os.environ.get(f"YT_CLIENT_ID_{ch}") or os.environ["YT_CLIENT_ID"]
    sec = os.environ.get(f"YT_CLIENT_SECRET_{ch}") or os.environ["YT_CLIENT_SECRET"]
    return cid, sec


def _credentials(refresh_token: str | None = None, channel: str | None = None) -> Credentials:
    cid, sec = _client_pair(channel)
    return Credentials(
        token=None,
        refresh_token=refresh_token or _default_refresh_token(),
        client_id=cid,
        client_secret=sec,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )


def get_client(refresh_token: str | None = None, channel: str | None = None):
    """refresh_token: переопределить авто-выбор по CHANNEL — нужно comment_agent.py, который в
    ОДНОМ процессе работает сразу с обоими каналами (EN/ES), а не выбирает канал через CHANNEL
    env как остальной пайплайн.

    channel: ОБЯЗАТЕЛЕН вместе с чужим refresh_token (2026-07-17, отдельный client_id на канал) —
    токен канала X валиден только для client_id канала X. Без него взялся бы client_id текущего
    CHANNEL и Google отбил бы `invalid_grant`. Затрагивает comment_agent.py и recycle_winners.py,
    которые ходят в два канала из одного процесса."""
    return build("youtube", "v3", credentials=_credentials(refresh_token, channel))


def get_analytics_client():
    """YouTube Analytics API v2 — для retention-метрик (avg view duration / % досмотра)."""
    return build("youtubeAnalytics", "v2", credentials=_credentials())


def get_authenticated_channel_title() -> str:
    response = get_client().channels().list(part="snippet", mine=True).execute()
    return response["items"][0]["snippet"]["title"]
