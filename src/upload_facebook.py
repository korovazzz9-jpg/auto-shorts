"""Публикует видео в Facebook как Reel через Graph API (тот же Meta Graph, что и Instagram).

Отдельный от upload_instagram модуль, потому что у FB Reels СВОЙ трёхшаговый upload
(start → upload → finish), а не одношаговый media/media_publish как у IG, и свой токен
(Page access token со скоупом pages_manage_posts — НЕ IG-токен).

Требует секретов FB_PAGE_ID и FB_PAGE_ACCESS_TOKEN. Видео скармливаем ссылкой (file_url) —
тот же публичный Cloudinary-URL, что уже залит для IG-рила, повторная заливка не нужна.
"""
import os
import time

import requests

GRAPH_URL = "https://graph.facebook.com/v21.0"
RUPLOAD_URL = "https://rupload.facebook.com/video-upload/v21.0"
POLL_INTERVAL_SECONDS = 5
POLL_TIMEOUT_SECONDS = 180


def _raise_with_body(response: requests.Response) -> None:
    """raise_for_status теряет тело — а Graph API кладёт реальную причину в error.message."""
    if response.status_code >= 400:
        try:
            detail = response.json().get("error", {})
        except ValueError:
            detail = response.text[:500]
        raise RuntimeError(f"Facebook Graph API {response.status_code}: {detail}")


def _token() -> str:
    return os.environ["FB_PAGE_ACCESS_TOKEN"]


def _wait_until_ready(video_id: str) -> None:
    """Reels обрабатывается асинхронно: публикация принята, но видео появляется не сразу.
    Опрашиваем publishing_phase, пока не complete (или не упало)."""
    deadline = time.time() + POLL_TIMEOUT_SECONDS
    while time.time() < deadline:
        resp = requests.get(
            f"{GRAPH_URL}/{video_id}",
            params={"fields": "status", "access_token": _token()},
            timeout=30,
        )
        _raise_with_body(resp)
        status = resp.json().get("status", {})
        publishing = status.get("publishing_phase", {}).get("status")
        if publishing == "complete":
            return
        if publishing == "error":
            raise RuntimeError(f"Facebook failed to publish reel {video_id}: {status}")
        time.sleep(POLL_INTERVAL_SECONDS)
    # Таймаут не фатален: публикация обычно уже принята, просто ещё крутится обработка —
    # не роняем весь кросс-постинг из-за медленной стороны Facebook.
    raise TimeoutError(f"Facebook reel {video_id} did not finish publishing in time")


def upload_reel(video_url: str, caption: str) -> str:
    """Публикует Reel на страницу из публичной ссылки video_url. Возвращает video_id."""
    page_id = os.environ["FB_PAGE_ID"]

    # Шаг 1 — start: получаем video_id и upload_url.
    start = requests.post(
        f"{GRAPH_URL}/{page_id}/video_reels",
        data={"upload_phase": "start", "access_token": _token()},
        timeout=30,
    )
    _raise_with_body(start)
    video_id = start.json()["video_id"]

    # Шаг 2 — upload: отдаём ссылку на файл заголовком file_url (hosted upload), тело пустое.
    up = requests.post(
        f"{RUPLOAD_URL}/{video_id}",
        headers={"Authorization": f"OAuth {_token()}", "file_url": video_url},
        timeout=60,
    )
    _raise_with_body(up)

    # Шаг 3 — finish: публикуем с описанием.
    finish = requests.post(
        f"{GRAPH_URL}/{page_id}/video_reels",
        data={
            "upload_phase": "finish",
            "video_id": video_id,
            "video_state": "PUBLISHED",
            "description": caption[:2200],
            "access_token": _token(),
        },
        timeout=30,
    )
    _raise_with_body(finish)

    _wait_until_ready(video_id)
    print(f"Posted to Facebook: reel id {video_id}")
    return video_id
