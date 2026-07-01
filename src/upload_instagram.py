"""Публикует видео в Instagram как Reel через Graph API."""
import os
import time

import requests

GRAPH_URL = "https://graph.facebook.com/v21.0"
POLL_INTERVAL_SECONDS = 5
POLL_TIMEOUT_SECONDS = 180


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


def upload_reel(video_url: str, caption: str, cover_url: str | None = None) -> str:
    ig_user_id = os.environ["IG_USER_ID"]

    kwargs: dict = dict(
        media_type="REELS",
        video_url=video_url,
        caption=caption[:2200],
    )
    if cover_url:
        kwargs["cover_url"] = cover_url

    container = _post(f"{ig_user_id}/media", **kwargs)
    container_id = container["id"]

    _wait_until_ready(container_id)

    publish = _post(f"{ig_user_id}/media_publish", creation_id=container_id)
    media_id = publish["id"]
    print(f"Posted to Instagram: media id {media_id}")
    return media_id
