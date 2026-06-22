"""Собирает вертикальное видео: фоновый луп + аудио + субтитры по словам."""
import os
import random

from moviepy.editor import (
    AudioFileClip,
    CompositeVideoClip,
    TextClip,
    VideoFileClip,
)

BACKGROUNDS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "backgrounds")
TARGET_SIZE = (1080, 1920)


def _pick_background() -> str:
    files = [f for f in os.listdir(BACKGROUNDS_DIR) if f.lower().endswith((".mp4", ".mov"))]
    if not files:
        raise FileNotFoundError(
            f"Положите хотя бы один вертикальный фоновый ролик в {BACKGROUNDS_DIR} "
            "(royalty-free, например с Pexels/Pixabay)."
        )
    return os.path.join(BACKGROUNDS_DIR, random.choice(files))


def _fit_background(bg: VideoFileClip, duration: float) -> VideoFileClip:
    bg = bg.resize(height=TARGET_SIZE[1])
    if bg.w < TARGET_SIZE[0]:
        bg = bg.resize(width=TARGET_SIZE[0])
    bg = bg.crop(x_center=bg.w / 2, y_center=bg.h / 2, width=TARGET_SIZE[0], height=TARGET_SIZE[1])
    if bg.duration < duration:
        loops = int(duration // bg.duration) + 1
        bg = bg.loop(n=loops)
    return bg.subclip(0, duration)


def build_video(audio_path: str, title: str, script: str, out_path: str) -> str:
    audio = AudioFileClip(audio_path)
    duration = audio.duration

    bg_path = _pick_background()
    bg = _fit_background(VideoFileClip(bg_path), duration).without_audio()

    title_clip = (
        TextClip(
            title,
            fontsize=80,
            color="white",
            font="Arial-Bold",
            stroke_color="black",
            stroke_width=3,
            size=(TARGET_SIZE[0] - 120, None),
            method="caption",
        )
        .set_position(("center", 140))
        .set_duration(duration)
    )

    caption_clip = (
        TextClip(
            script,
            fontsize=58,
            color="white",
            font="Arial",
            stroke_color="black",
            stroke_width=2,
            size=(TARGET_SIZE[0] - 160, None),
            method="caption",
        )
        .set_position(("center", "center"))
        .set_duration(duration)
    )

    final = CompositeVideoClip([bg, title_clip, caption_clip], size=TARGET_SIZE).set_audio(audio)
    final.write_videofile(out_path, fps=30, codec="libx264", audio_codec="aac", logger=None)
    return out_path
