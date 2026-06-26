"""Пайплайн для недельной серии (Part 1/2/3).

Понедельник (SERIES_PART=1): генерирует все 3 скрипта, сохраняет в series_state.json, публикует Part 1.
Среда    (SERIES_PART=2): читает series_state.json, публикует Part 2.
Пятница  (SERIES_PART=3): читает series_state.json, публикует Part 3.
"""
import json
import os
import tempfile

from dotenv import load_dotenv

from build_video import build_video
from cloudinary_upload import delete_image, delete_video, upload_image, upload_video as upload_to_cloudinary
from config import CFG
from fetch_stock_video import fetch_clips
from generate_series import generate_series
from playlists import add_video_to_playlist
from post_comment import post_channel_comment
from tts import text_to_speech
from upload_captions import upload_captions
from upload_instagram import upload_reel
from upload_tiktok import upload_video as upload_to_tiktok, wait_for_publish
from upload_youtube import upload_video as upload_to_youtube
from youtube_auth import get_authenticated_channel_title

load_dotenv()

SERIES_STATE_FILE = os.path.join(os.path.dirname(__file__), "series_state.json")


def _load_state() -> dict:
    if os.path.exists(SERIES_STATE_FILE):
        with open(SERIES_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_state(state: dict) -> None:
    with open(SERIES_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def run() -> None:
    part = int(os.environ.get("SERIES_PART", "1"))

    # Проверяем канал
    actual = get_authenticated_channel_title()
    expected = CFG["channel_name"]
    if actual != expected:
        raise RuntimeError(f"Wrong channel: got '{actual}', expected '{expected}'")

    # Part 1 — генерируем все 3 части и сохраняем
    if part == 1:
        print(f"[{CFG['channel_name']}] Series Part 1 — generating all 3 scripts...")
        state = generate_series()
        _save_state(state)
        print(f"  Topic: {state['topic']}")
    else:
        state = _load_state()
        if not state:
            raise RuntimeError("series_state.json not found — run Part 1 first")
        print(f"[{CFG['channel_name']}] Series Part {part} — topic: {state['topic']}")

    part_key = f"part{part}"
    data = state[part_key]

    print(f"  Title: {data['title']}")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        audio_path = os.path.join(tmp, "audio.mp3")
        video_path = os.path.join(tmp, "video.mp4")

        print("Fetching stock clips...")
        clip_paths = fetch_clips(data["video_queries"], tmp)

        print("Synthesizing TTS...")
        words = text_to_speech(data["script"], audio_path)
        print(f"  Audio: {words[-1]['end']:.1f}s, {len(words)} words")

        print("Building video...")
        video_path, thumb_path = build_video(
            audio_path, clip_paths, words, video_path,
            topic=data.get("topic", state.get("topic")),
            part=part,
            total_parts=3,
            title=data["title"],
        )

        print("Uploading to YouTube...")
        video_id = upload_to_youtube(
            video_path,
            title=data["title"],
            description=data["script"],
            tags=data["tags"],
            hashtags=data["hashtags"],
            hashtag_position=data["hashtag_position"],
        )

        playlist_id = None
        try:
            playlist_id = add_video_to_playlist(video_id, data.get("topic", state.get("topic", "")))
        except Exception as e:
            print(f"  Playlist failed: {e}")

        try:
            channel_url = f"https://www.youtube.com/@{CFG.get('channel_handle', '')}"
            comment_template = CFG.get("first_comment", "")
            playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}" if playlist_id else ""
            comment = comment_template.format(channel_url=channel_url, playlist_url=playlist_url).strip()
            if comment:
                post_channel_comment(video_id, comment)
        except Exception as e:
            print(f"  Comment failed: {e}")

        try:
            upload_captions(video_id, words)
        except Exception as e:
            print(f"  Captions failed: {e}")

        need_cloudinary = CFG["post_to_instagram"] or CFG.get("post_to_tiktok")
        if need_cloudinary:
            print("Uploading to cloud (Cloudinary) and publishing...")
            hosted = None
            hosted_thumb = None
            try:
                hosted = upload_to_cloudinary(video_path)
                if CFG["post_to_instagram"]:
                    hosted_thumb = upload_image(thumb_path)
                    caption = f"{data['title']}\n\n{data['script']}\n\n{' '.join(data['hashtags'])}"
                    upload_reel(hosted["url"], caption, cover_url=hosted_thumb["url"])
                    print("  Instagram: published")

                if CFG.get("post_to_tiktok"):
                    try:
                        publish_id = upload_to_tiktok(hosted["url"], data["title"], data["hashtags"])
                        token = os.environ["TIKTOK_ACCESS_TOKEN"]
                        status = wait_for_publish(publish_id, token)
                        print(f"  TikTok: {status}")
                    except Exception as e:
                        print(f"  TikTok failed: {e}")
            except Exception as e:
                print(f"  Cloudinary/Instagram failed: {e}")
            finally:
                if hosted:
                    try:
                        delete_video(hosted["public_id"])
                    except Exception:
                        pass
                if hosted_thumb:
                    try:
                        delete_image(hosted_thumb["public_id"])
                    except Exception:
                        pass

    print(f"Done — Part {part}/3 published.")


if __name__ == "__main__":
    run()
