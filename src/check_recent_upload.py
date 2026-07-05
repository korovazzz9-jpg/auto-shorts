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
# слота+45 мин. При коротком lookback (было 25) watchdog, запустившись поздно, не видел
# уже опубликованное в слот видео (оно «старше 25 мин») → ложно решал «пропущено» → дубль.
# 50 мин покрывает retry-окно целиком и при этом меньше минимального разрыва между слотами
# (60 мин, между 23:07 и 00:07 — см. ниже), так что предыдущий слот случайно не зачтётся
# за текущий. 2026-07-05: разрыв сузился с ~114 до 60 мин (слот 22:13→23:07, US prime time),
# поэтому окна LOOKBACK/RETRY_WINDOW сужены пропорционально (были 70/(10,60)).
LOOKBACK_MINUTES = 50

# Слоты публикации (UTC, час:мин). Должны совпадать с cron-job.org / daily.yml.
# 2026-07-01: EN 5→4 слотов (перелив ресурса на ES, где отдача 2× — см. README).
# Убран 13:07 UTC (8am ET — худшее US-окно).
# 2026-07-05: 22:13→23:07 — попадание в US-прайм 19:07 EDT (7-9pm окно), было 18:13 EDT
# ("мёртвая зона" между дневным и вечерним пиком) — см. README, поиск прайм-таймов.
SLOTS_UTC = [(16, 13), (20, 7), (23, 7), (0, 7)]
# Сколько минут после слота watchdog имеет право доретраивать.
RETRY_WINDOW = (10, 45)


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
