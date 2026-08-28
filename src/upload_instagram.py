"""Публикует видео в Instagram как Reel через Graph API."""
import os
import time

import requests

GRAPH_URL = "https://graph.facebook.com/v21.0"
POLL_INTERVAL_SECONDS = 5
POLL_TIMEOUT_SECONDS = 180
CONTAINER_RETRIES = 2       # доп. попытки, помимо первой
CONTAINER_RETRY_DELAY = 10  # секунд — Meta иногда роняет обработку контейнера (status_code=
# ERROR) без видимой причины на самом файле (2026-08-28, реальный случай); пересоздание
# контейнера (не повторный опрос уже упавшего) обычно проходит.


def _raise_with_body(response: requests.Response) -> None:
    """response.raise_for_status() сам по себе теряет тело ответа — а именно там Graph API
    кладёт error.message с реальной причиной (401/400 без этого не продиагностировать)."""
    if response.status_code >= 400:
        try:
            detail = response.json().get("error", {})
        except ValueError:
            detail = response.text[:500]
        raise RuntimeError(f"Instagram Graph API {response.status_code}: {detail}")


def _get(path: str, **params) -> dict:
    params["access_token"] = os.environ["IG_ACCESS_TOKEN"]
    response = requests.get(f"{GRAPH_URL}/{path}", params=params, timeout=30)
    _raise_with_body(response)
    return response.json()


def _post(path: str, **params) -> dict:
    params["access_token"] = os.environ["IG_ACCESS_TOKEN"]
    response = requests.post(f"{GRAPH_URL}/{path}", data=params, timeout=30)
    _raise_with_body(response)
    return response.json()


def _wait_until_ready(container_id: str) -> None:
    deadline = time.time() + POLL_TIMEOUT_SECONDS
    while time.time() < deadline:
        status = _get(container_id, fields="status_code")["status_code"]
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"Instagram failed to process container {container_id}")
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"Instagram container {container_id} did not finish processing in time")


def _create_container_with_retry(ig_user_id: str, **kwargs) -> str:
    """Создаёт контейнер и ждёт готовности; при status_code=ERROR пересоздаёт контейнер
    заново (повторный опрос уже упавшего контейнера бессмыслен — ошибка финальна для него)."""
    last_err = None
    for attempt in range(CONTAINER_RETRIES + 1):
        container = _post(f"{ig_user_id}/media", **kwargs)
        try:
            _wait_until_ready(container["id"])
            return container["id"]
        except RuntimeError as e:
            last_err = e
            if attempt < CONTAINER_RETRIES:
                print(f"  Instagram container failed (attempt {attempt + 1}/{CONTAINER_RETRIES + 1}), "
                      f"retrying in {CONTAINER_RETRY_DELAY}s: {e}")
                time.sleep(CONTAINER_RETRY_DELAY)
    raise last_err


def upload_photo(image_url: str, caption: str) -> str:
    """Публикует статичную фото-карточку в ленту (не Reel) — для IG-карточек фактов."""
    ig_user_id = os.environ["IG_USER_ID"]
    container_id = _create_container_with_retry(ig_user_id, image_url=image_url, caption=caption[:2200])
    publish = _post(f"{ig_user_id}/media_publish", creation_id=container_id)
    print(f"Posted photo to Instagram: media id {publish['id']}")
    return publish["id"]


def upload_story(image_url: str) -> str:
    """Публикует изображение в Stories (2026-07-05): карточка факта дублируется в сторис —
    ленту видят новые люди, сторис — подписчики; двойное касание с той же картинки."""
    ig_user_id = os.environ["IG_USER_ID"]
    container_id = _create_container_with_retry(ig_user_id, media_type="STORIES", image_url=image_url)
    publish = _post(f"{ig_user_id}/media_publish", creation_id=container_id)
    print(f"Posted story to Instagram: media id {publish['id']}")
    return publish["id"]


def upload_reel(video_url: str, caption: str, cover_url: str | None = None) -> str:
    ig_user_id = os.environ["IG_USER_ID"]

    kwargs: dict = dict(
        media_type="REELS",
        video_url=video_url,
        caption=caption[:2200],
    )
    if cover_url:
        kwargs["cover_url"] = cover_url

    container_id = _create_container_with_retry(ig_user_id, **kwargs)

    publish = _post(f"{ig_user_id}/media_publish", creation_id=container_id)
    media_id = publish["id"]
    print(f"Posted to Instagram: media id {media_id}")
    return media_id
