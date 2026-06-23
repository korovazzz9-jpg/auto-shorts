"""Загружает видео во временный публичный хостинг (Cloudinary), нужный для Instagram Graph API
(он не принимает файлы напрямую — только публичную ссылку, которую сам скачивает)."""
import os

import cloudinary
import cloudinary.uploader


def _configure() -> None:
    cloudinary.config(
        cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
        api_key=os.environ["CLOUDINARY_API_KEY"],
        api_secret=os.environ["CLOUDINARY_API_SECRET"],
    )


def upload_video(video_path: str) -> dict:
    """Returns {"url": public https url, "public_id": id for later deletion}."""
    _configure()
    result = cloudinary.uploader.upload(
        video_path,
        resource_type="video",
        folder="auto-shorts",
    )
    return {"url": result["secure_url"], "public_id": result["public_id"]}


def delete_video(public_id: str) -> None:
    _configure()
    cloudinary.uploader.destroy(public_id, resource_type="video")
