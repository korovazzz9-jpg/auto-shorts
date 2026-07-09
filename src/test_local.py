"""Тестовый прогон: генерирует видео локально без загрузки на YouTube.
Сохраняет video.mp4, thumb.jpg, audio.mp3 и клипы на рабочий стол
чтобы можно было перерендерить через rerender.py без нового сюжета."""
import os, shutil, json, sys

# Windows-консоль по умолчанию в cp1251 — падает на нелатинских заголовках (VN-канал,
# диакритика вида "ấ"/"đ"). Без этого print(data['title']) крашится с UnicodeEncodeError
# уже ПОСЛЕ платной генерации сценария (2026-07-08, поймано на реальном VN-прогоне).
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from build_video import build_video
from config import CFG, CHANNEL
from fetch_stock_video import fetch_clips, fetch_satisfying_clips
from generate_rapid_facts import FACTS_PER_VIDEO, generate_rapid_facts
from generate_script import generate_script
from notify import send_video
from tts import text_to_speech

import tempfile

OUT_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "auto-shorts-test")
os.makedirs(OUT_DIR, exist_ok=True)

# VN-канал в satisfying-режиме: random-facts сценарий + залипательный фон, без хук-плашки.
SATISFYING = CFG.get("satisfying_mode", False)

# Сценарий сохраняется СРАЗУ после генерации (2026-07-04): раньше упавший на клипах/TTS
# прогон (сетевой сбой) терял оплаченный вызов Sonnet. Если прошлый прогон упал —
# переиспользуем его сценарий вместо новой генерации. Удаляется при успешном завершении.
PENDING_PATH = os.path.join(OUT_DIR, "meta_pending.json")

print("1/4 Генерация сценария...")
data = None
if os.path.exists(PENDING_PATH):
    try:
        with open(PENDING_PATH, encoding="utf-8") as f:
            pending = json.load(f)
        if pending.get("channel") == CHANNEL:  # сценарий другого канала не переиспользуем
            data = pending["data"]
            print("  (сценарий из meta_pending.json — прошлый прогон упал после генерации)")
    except (json.JSONDecodeError, KeyError):
        pass
if data is None:
    data = generate_rapid_facts() if SATISFYING else generate_script()
    with open(PENDING_PATH, "w", encoding="utf-8") as f:
        json.dump({"channel": CHANNEL, "data": data}, f, ensure_ascii=False, indent=2)
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
        hook_text=None if SATISFYING else data.get("hook_text"),  # двойной хук (текст ≠ озвучка)
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
    # Прогон успешен — «страховочный» сценарий больше не нужен.
    if os.path.exists(PENDING_PATH):
        os.remove(PENDING_PATH)

print(f"\nГотово!")
print(f"  Видео:     {os.path.join(OUT_DIR, f'video_{num}.mp4')}")
print(f"  Thumbnail: {os.path.join(OUT_DIR, f'thumb_{num}.jpg')}")
# TikTok режет подпись после 5 хештегов (upload_tiktok.py делает то же для авто-загрузки) —
# VN постится вручную, печатаем ровно то, что реально влезет в TikTok, а не сырой список модели.
tiktok_hashtags = data["hashtags"][:5]
print(f"\nЗаголовок для TikTok: {data['title']}")
print(f"Хэштеги (макс 5 для TikTok): {' '.join(tiktok_hashtags)}")
caption = f"{data['title']}\n\n{' '.join(tiktok_hashtags)}"
print(f"Caption: {caption}")

# VN TikTok постится вручную с телефона (2026-07-09) — присылаем готовый файл сразу в
# Telegram, не нужно вручную идти на Desktop/забирать по кабелю на телефон. Только для
# satisfying-режима (VN) — EN/ES идут через полный pipeline.py на YouTube, тут не нужно.
if SATISFYING:
    print("\nОтправляю видео в Telegram...")
    send_video(os.path.join(OUT_DIR, f"video_{num}.mp4"), caption)
