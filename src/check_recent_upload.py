"""Проверяет, было ли на канал залито видео за последние N минут. Используется
watchdog-воркфлоу: если нет — значит запланированный запуск pipeline.py не сработал
(например, GitHub Actions пропустил scheduled trigger), и его нужно повторить.

Exit code 0 — ретрай НЕ нужен (свежее видео есть ЛИБО сейчас не окно слота).
Exit code 1 — свежего видео нет и мы в окне после слота → нужен повторный запуск.

ВАЖНО: guard по времени. GitHub-cron палит watchdog с опозданием в часы (видели
запуски в 07:40/08:17/09:34 UTC вместо 00:22) — без этого guard watchdog публиковал
лишние ролики в случайное время (почти 0 просмотров, YouTube душит частые загрузки).
Ретраим ТОЛЬКО если сейчас в окне RETRY_WINDOW после реального слота.
"""
import datetime
import sys

from youtube_auth import get_client

# Окно проверки «было ли видео» должно покрывать слот + всё опоздание watchdog.
# Watchdog бежит на GitHub-cron (опаздывает на 10-40 мин), и его retry-окно тянется до
# слота+60 мин. При коротком lookback (было 25) watchdog, запустившись поздно, не видел
# уже опубликованное в слот видео (оно «старше 25 мин») → ложно решал «пропущено» → дубль.
# 70 мин покрывает retry-окно целиком и при этом меньше минимального разрыва между слотами
# (~114 мин), так что предыдущий слот случайно не зачтётся за текущий.
LOOKBACK_MINUTES = 70

# Слоты публикации (UTC, час:мин). Должны совпадать с cron-job.org / daily.yml.
SLOTS_UTC = [(13, 7), (16, 13), (20, 7), (22, 13), (0, 7)]
# Сколько минут после слота watchdog имеет право доретраивать.
RETRY_WINDOW = (10, 60)


def in_retry_window() -> bool:
    now = datetime.datetime.now(datetime.timezone.utc)
    now_m = now.hour * 60 + now.minute
    lo, hi = RETRY_WINDOW
    for h, m in SLOTS_UTC:
        delta = (now_m - (h * 60 + m)) % 1440  # минут прошло с этого слота
        if lo <= delta <= hi:
            return True
    return False


def has_recent_upload() -> bool:
    youtube = get_client()
    channels = youtube.channels().list(part="contentDetails", mine=True).execute()
    uploads_id = channels["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    response = youtube.playlistItems().list(
        part="snippet", playlistId=uploads_id, maxResults=1
    ).execute()

    items = response.get("items", [])
    if not items:
        return False

    published_at = datetime.datetime.fromisoformat(
        items[0]["snippet"]["publishedAt"].replace("Z", "+00:00")
    )
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=LOOKBACK_MINUTES)
    return published_at >= cutoff


if __name__ == "__main__":
    if not in_retry_window():
        print("SKIP: not within retry window after a slot — no retry.")
        sys.exit(0)
    if has_recent_upload():
        print("OK: recent upload found.")
        sys.exit(0)
    else:
        print("MISSING: no upload in the lookback window.")
        sys.exit(1)
