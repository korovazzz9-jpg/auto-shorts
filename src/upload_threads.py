"""Threads-автопост (2026-07-05): факт + карточка в Threads через официальный Meta API.

ВАЖНО: Threads использует ОТДЕЛЬНЫЙ токен, не IG_ACCESS_TOKEN — нужно приложение с
Threads API (use case «Access the Threads API»), scopes threads_basic +
threads_content_publish, long-lived token. Env: THREADS_ACCESS_TOKEN + THREADS_USER_ID.
Пока токена нет — CFG["post_to_threads"]=False, шаг просто пропускается (тот же паттерн
ожидания, что TikTok/Pinterest).
"""
import os
import time

import requests

GRAPH_URL = "https://graph.threads.net/v1.0"
PROCESSING_WAIT_SECONDS = 8  # Meta рекомендует дать контейнеру с изображением обработаться


def _raise_with_body(response: requests.Response) -> None:
    if response.status_code >= 400:
        try:
            detail = response.json().get("error", {})
        except ValueError:
            detail = response.text[:500]
        raise RuntimeError(f"Threads API {response.status_code}: {detail}")


def post_thread(text: str, image_url: str | None = None) -> str:
    """Публикует пост в Threads (текст, опционально с изображением). Возвращает id поста."""
    token = os.environ["THREADS_ACCESS_TOKEN"]
    user_id = os.environ["THREADS_USER_ID"]

    params: dict = {"access_token": token, "text": text[:500]}
    if image_url:
        params["media_type"] = "IMAGE"
        params["image_url"] = image_url
    else:
        params["media_type"] = "TEXT"

    resp = requests.post(f"{GRAPH_URL}/{user_id}/threads", data=params, timeout=30)
    _raise_with_body(resp)
    creation_id = resp.json()["id"]

    if image_url:
        time.sleep(PROCESSING_WAIT_SECONDS)

    pub = requests.post(
        f"{GRAPH_URL}/{user_id}/threads_publish",
        data={"access_token": token, "creation_id": creation_id},
        timeout=30,
    )
    _raise_with_body(pub)
    thread_id = pub.json()["id"]
    print(f"Posted to Threads: {thread_id}")
    return thread_id
