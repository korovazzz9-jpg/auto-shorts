"""Тестовый прогон: генерирует видео локально без загрузки на YouTube.
Сохраняет video.mp4, thumb.jpg, audio.mp3 и клипы на рабочий стол
чтобы можно было перерендерить через rerender.py без нового сюжета."""
import os, shutil, json

from dotenv import load_dotenv
load_dotenv()

from build_video import build_video
from config import CFG
from fetch_stock_video import fetch_clips, fetch_satisfying_clips
from generate_rapid_facts import FACTS_PER_VIDEO, generate_rapid_facts
from generate_script import generate_script
from tts import text_to_speech

import tempfile

OUT_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "auto-shorts-test")
os.makedirs(OUT_DIR, exist_ok=True)

# VN-канал в satisfying-режиме: random-facts сценарий + залипательный фон, без хук-плашки.
SATISFYING = CFG.get("satisfying_mode", False)

print("1/4 Генерация сценария...")
data = generate_rapid_facts() if SATISFYING else generate_script()
print(f"  Тема: {data['topic']}")
print(f"  Заголовок: {data['title']}")

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
    audio_path = os.path.join(tmp, "audio.mp3")
    video_path = os.path.join(tmp, "video.mp4")

    print("2/4 Стоковые клипы...")
    if SATISFYING:
        # Фон не тематический — берём залипательные клипы (на 1 больше фактов для ротации).
        clip_paths = fetch_satisfying_clips(FACTS_PER_VIDEO, tmp)
    else:
        clip_paths = fetch_clips(data["video_queries"], tmp)

    print("3/4 Озвучка...")
    words = text_to_speech(data["script"], audio_path)
    print(f"  Длина: {words[-1]['end']:.1f}s")

    print("4/4 Сборка видео...")
    video_path, thumb_path = build_video(
        audio_path, clip_paths, words, video_path,
        topic=None if SATISFYING else data["topic"],   # None → общий VN CTA-бейдж
        title=None if SATISFYING else data["title"],   # None → без EN-хук-плашки
    )

    # Определяем номер следующего видео
    existing = [f for f in os.listdir(OUT_DIR) if f.startswith("video_") and f.endswith(".mp4")]
    next_num = len(existing) + 1
    num = f"{next_num:02d}"

    shutil.copy2(video_path, os.path.join(OUT_DIR, "video.mp4"))
    shutil.copy2(video_path, os.path.join(OUT_DIR, f"video_{num}.mp4"))
    shutil.copy2(thumb_path, os.path.join(OUT_DIR, "thumb.jpg"))
    shutil.copy2(thumb_path, os.path.join(OUT_DIR, f"thumb_{num}.jpg"))
    shutil.copy2(audio_path, os.path.join(OUT_DIR, "audio.mp3"))
    clips_dir = os.path.join(OUT_DIR, "clips")
    os.makedirs(clips_dir, exist_ok=True)
    saved_clips = []
    for i, cp in enumerate(clip_paths):
        dst = os.path.join(clips_dir, f"clip_{i:02d}{os.path.splitext(cp)[1]}")
        shutil.copy2(cp, dst)
        saved_clips.append(dst)

    meta = {"data": data, "words": words, "clip_paths": saved_clips}
    with open(os.path.join(OUT_DIR, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT_DIR, f"meta_{num}.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

print(f"\nГотово!")
print(f"  Видео:     {os.path.join(OUT_DIR, f'video_{num}.mp4')}")
print(f"  Thumbnail: {os.path.join(OUT_DIR, f'thumb_{num}.jpg')}")
print(f"\nЗаголовок для TikTok: {data['title']}")
print(f"Хэштеги: {' '.join(data['hashtags'])}")
print(f"Caption: {data['title']}\n\n{' '.join(data['hashtags'])}")
