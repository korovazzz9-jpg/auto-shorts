"""Перерендер того же сюжета/аудио с КАЖДЫМ AI-сгенерированным треком по очереди — без
нового API-запроса (бесплатно). Нужно для приватной проверки Content ID на YouTube
(assets/music/ai_generated/*.mp3 — кандидаты, ещё не введены в продакшен-ротацию).

Читает meta.json из папки auto-shorts-test на рабочем столе (см. rerender.py).
Результат: Desktop/auto-shorts-test/music_tests/<имя_трека>.mp4"""
import glob
import json
import os
import shutil
import sys
import tempfile

DESKTOP_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "auto-shorts-test")
MUSIC_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "music", "ai_generated")
OUT_DIR = os.path.join(DESKTOP_DIR, "music_tests")

meta_path = os.path.join(DESKTOP_DIR, "meta.json")
if not os.path.exists(meta_path):
    print("meta.json не найден — сначала запусти test_local.py")
    exit(1)

with open(meta_path, encoding="utf-8") as f:
    saved = json.load(f)

data = saved["data"]
words = saved["words"]
clip_paths = saved["clip_paths"]
audio_path = os.path.join(DESKTOP_DIR, "audio.mp3")

tracks = sorted(glob.glob(os.path.join(MUSIC_DIR, "*.mp3")))
if not tracks:
    print(f"Треков не найдено в {MUSIC_DIR}")
    exit(1)

# Необязательный фильтр по именам треков (без .mp3), напр. для перерендера только
# исправленных файлов: python rerender_music_tests.py custom_v4 custom_v5
if len(sys.argv) > 1:
    wanted = set(sys.argv[1:])
    tracks = [t for t in tracks if os.path.splitext(os.path.basename(t))[0] in wanted]
    if not tracks:
        print(f"Ни один трек не совпал с {wanted}")
        exit(1)

os.makedirs(OUT_DIR, exist_ok=True)
print(f"Тема: {data['topic']}")
print(f"Заголовок: {data['title']}")
print(f"Треков к рендеру: {len(tracks)}\n")

from build_video import build_video

for i, track_path in enumerate(tracks, 1):
    track_name = os.path.splitext(os.path.basename(track_path))[0]
    print(f"[{i}/{len(tracks)}] {track_name}...")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        video_path = os.path.join(tmp, "video.mp4")
        video_path, thumb_path, _color = build_video(
            audio_path, clip_paths, words, video_path,
            topic=data["topic"],
            title=data["title"],
            music_path=track_path,
        )
        out_video = os.path.join(OUT_DIR, f"{track_name}.mp4")
        shutil.copy2(video_path, out_video)
    print(f"  Готово: {out_video}")

print(f"\nВсе видео в {OUT_DIR}")
print("Загрузи каждое приватным видео на YouTube и проверь вкладку Content ID.")
