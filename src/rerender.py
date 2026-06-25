"""Перерендер видео с тем же сюжетом/аудио — без нового API-запроса.
Читает meta.json из папки auto-shorts-test на рабочем столе."""
import os, shutil, json

OUT_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "auto-shorts-test")
meta_path = os.path.join(OUT_DIR, "meta.json")

if not os.path.exists(meta_path):
    print("meta.json не найден — сначала запусти test_local.py")
    exit(1)

with open(meta_path, encoding="utf-8") as f:
    saved = json.load(f)

data = saved["data"]
words = saved["words"]
clip_paths = saved["clip_paths"]
audio_path = os.path.join(OUT_DIR, "audio.mp3")

print(f"Тема: {data['topic']}")
print(f"Заголовок: {data['title']}")
print("Перерендериваю видео...")

import tempfile
from build_video import build_video

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
    video_path = os.path.join(tmp, "video.mp4")
    video_path, thumb_path = build_video(
        audio_path, clip_paths, words, video_path,
        topic=data["topic"],
        title=data["title"],
    )
    shutil.copy2(video_path, os.path.join(OUT_DIR, "video.mp4"))
    shutil.copy2(thumb_path, os.path.join(OUT_DIR, "thumb.jpg"))

print(f"\nГотово!")
print(f"  Видео:     {os.path.join(OUT_DIR, 'video.mp4')}")
print(f"  Thumbnail: {os.path.join(OUT_DIR, 'thumb.jpg')}")
