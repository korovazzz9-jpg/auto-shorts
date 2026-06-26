"""TikTok Content Posting API — загрузка видео через pull_by_url."""
import os
import time
import requests


def get_client():
    return os.environ["TIKTOK_ACCESS_TOKEN"]


def upload_video(video_url: str, title: str, hashtags: list[str]) -> str:
    """Публикует видео на TikTok. Возвращает publish_id."""
    token = get_client()
    tag_text = " ".join(f"#{t.lstrip('#')}" for t in hashtags[:5])
    caption = f"{title}\n\n{tag_text}"[:2200]

    resp = requests.post(
        "https://open.tiktokapis.com/v2/post/publish/video/init/",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        json={
            "post_info": {
                "title": caption,
                "privacy_level": "PUBLIC_TO_EVERYONE",
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
                "video_cover_timestamp_ms": 1000,
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "video_url": video_url,
            },
        },
    )
    data = resp.json()
    if resp.status_code != 200 or data.get("error", {}).get("code", "ok") != "ok":
        raise RuntimeError(f"TikTok upload failed: {data}")

    publish_id = data["data"]["publish_id"]
    print(f"  TikTok publish_id: {publish_id}")
    return publish_id


def wait_for_publish(publish_id: str, token: str, timeout: int = 120) -> str:
    """Ждёт пока видео опубликуется. Возвращает статус."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = requests.post(
            "https://open.tiktokapis.com/v2/post/publish/status/fetch/",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json={"publish_id": publish_id},
        )
        status = resp.json().get("data", {}).get("status", "UNKNOWN")
        print(f"  TikTok status: {status}")
        if status in ("PUBLISH_COMPLETE", "FAILED"):
            return status
        time.sleep(5)
    return "TIMEOUT"
