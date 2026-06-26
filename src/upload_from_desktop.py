"""Загружает готовое видео с рабочего стола на YouTube + Instagram.
Берёт video.mp4, thumb.jpg и meta.json из ~/Desktop/auto-shorts-test/.
"""
import json
import os

from dotenv import load_dotenv
load_dotenv()

from cloudinary_upload import delete_image, delete_video, upload_image, upload_video as upload_to_cloudinary
from config import CFG
from playlists import add_video_to_playlist
from post_comment import post_channel_comment
from upload_instagram import upload_reel
from upload_youtube import upload_video as upload_to_youtube
from youtube_auth import get_authenticated_channel_title

OUT_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "auto-shorts-test")
video_path = os.path.join(OUT_DIR, "video_02.mp4")
thumb_path = os.path.join(OUT_DIR, "thumb.jpg")
meta_path = os.path.join(OUT_DIR, "meta.json")

with open(meta_path, encoding="utf-8") as f:
    meta = json.load(f)
data = meta["data"]
words = meta["words"]

# Проверка канала
actual = get_authenticated_channel_title()
expected = CFG["channel_name"]
if actual != expected:
    raise RuntimeError(f"Неверный канал: '{actual}', ожидался '{expected}'")

print(f"Канал: {actual}")
print(f"Тема: {data['topic']} | Заголовок: {data['title']}")

print("Загрузка на YouTube...")
video_id = upload_to_youtube(
    video_path,
    title=data["title"],
    description=data["script"],
    tags=data["tags"] + [f"topic-{data['topic'].replace(' ', '_')}"],
    hashtags=data["hashtags"],
    hashtag_position=data["hashtag_position"],
    thumbnail_path=thumb_path,
)

try:
    playlist_id = add_video_to_playlist(video_id, data["topic"])
except Exception as e:
    print(f"  Плейлист: {e}")
    playlist_id = None

try:
    channel_url = f"https://www.youtube.com/@{CFG['channel_handle']}" if CFG.get("channel_handle") else ""
    comment_template = CFG.get("first_comment", "")
    playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}" if playlist_id else ""
    comment = comment_template.format(channel_url=channel_url, playlist_url=playlist_url).strip()
    if comment:
        post_channel_comment(video_id, comment)
except Exception as e:
    print(f"  Комментарий: {e}")

if CFG["post_to_instagram"]:
    print("Загрузка в Instagram...")
    hosted = None
    hosted_thumb = None
    try:
        hosted = upload_to_cloudinary(video_path)
        hosted_thumb = upload_image(thumb_path)
        caption = f"{data['title']}\n\n{data['script']}\n\n{' '.join(data['hashtags'])}"
        upload_reel(hosted["url"], caption, cover_url=hosted_thumb["url"])
        print("  Instagram: опубликовано")
    except Exception as e:
        print(f"  Instagram: {e}")
    finally:
        if hosted:
            try: delete_video(hosted["public_id"])
            except Exception: pass
        if hosted_thumb:
            try: delete_image(hosted_thumb["public_id"])
            except Exception: pass

print(f"\nГотово! https://youtube.com/shorts/{video_id}")
