"""Горизонтальный (16:9, 1920×1080) билдер для лонгформа.

Лонгформ смотрят с десктопа/ТВ, поэтому формат горизонтальный, а не вертикальный
как Shorts. Это упрощённый билдер: фон из стоковых клипов + лёгкий зум + караоке-субтитры
снизу. Без Shorts-фишек (хук-плашка, CTA-пульс, петля, PART-оверлей) — они тут не нужны.
Переиспользует шрифт/аудио/тумбу из build_video, но со своим размером кадра."""
import os
import tempfile

from PIL import Image
from moviepy.editor import (
    AudioFileClip,
    CompositeVideoClip,
    TextClip,
    VideoFileClip,
    concatenate_videoclips,
)

# Импорт build_video настраивает ImageMagick и даёт общие куски (шрифт, аудио, тумба).
import build_video as bv
from build_video import SUBTITLE_FONT, _build_audio, _pick_zoom_factor, _save_thumbnail

TARGET_SIZE = (1920, 1080)
CAPTION_Y = int(TARGET_SIZE[1] * 0.80)  # субтитры в нижней трети, не перекрывают центр кадра


def _fit_clip(clip: VideoFileClip, duration: float, zoom_factor: float) -> VideoFileClip:
    clip = clip.without_audio().resize(width=TARGET_SIZE[0])
    if clip.h < TARGET_SIZE[1]:
        clip = clip.resize(height=TARGET_SIZE[1])
    clip = clip.crop(x_center=clip.w / 2, y_center=clip.h / 2,
                     width=TARGET_SIZE[0], height=TARGET_SIZE[1])
    if clip.duration < duration:
        loops = int(duration // clip.duration) + 1
        clip = clip.loop(n=loops)
    clip = clip.subclip(0, duration)
    clip = clip.resize(lambda t: 1 + (zoom_factor - 1) * (t / max(duration, 0.01)))
    return clip.set_position("center")


def _build_background(clip_paths: list[str], duration: float) -> CompositeVideoClip:
    per_clip = duration / len(clip_paths)
    fitted = [_fit_clip(VideoFileClip(p), per_clip, _pick_zoom_factor()) for p in clip_paths]
    sequence = concatenate_videoclips(fitted, method="compose")
    return CompositeVideoClip([sequence], size=TARGET_SIZE).set_duration(duration)


def _karaoke_clips(words: list[dict], cutoff: float) -> list[TextClip]:
    clips = []
    for w in words:
        if w["start"] >= cutoff:
            continue
        end = min(w["end"], cutoff)
        clip = (
            TextClip(
                w["text"].upper(),
                fontsize=70,
                color="white",
                font=SUBTITLE_FONT,
                stroke_color="black",
                stroke_width=4,
                size=(TARGET_SIZE[0] - 300, None),
                method="caption",
            )
            .set_position(("center", CAPTION_Y))
            .set_start(w["start"])
            .set_duration(max(end - w["start"], 0.05))
        )
        clips.append(clip)
    return clips


def build_longform_video(
    audio_path: str,
    clip_paths: list[str],
    words: list[dict],
    out_path: str,
    topic: str | None = None,
    title: str | None = None,
    **kwargs,
) -> tuple[str, str]:
    """Returns (video_path, thumbnail_path). Сигнатура совместима с build_video."""
    audio = AudioFileClip(audio_path)
    duration = audio.duration

    if not clip_paths:
        raise ValueError("No video clips provided to build_longform_video")

    background = _build_background(clip_paths, duration)
    caption_clips = _karaoke_clips(words, cutoff=duration)
    final = CompositeVideoClip([background, *caption_clips], size=TARGET_SIZE)
    final = final.set_audio(_build_audio(audio, words, duration))

    final.write_videofile(
        out_path, fps=30, codec="libx264", audio_codec="aac",
        threads=4, preset="medium", logger=None,
    )

    # Тумба — первый кадр + заголовок (переиспользуем рендер из build_video).
    thumb_path = os.path.splitext(out_path)[0] + "_thumb.jpg"
    frame = background.get_frame(0.5)
    _save_thumbnail(Image.fromarray(frame), thumb_path, title=title)

    final.close()
    audio.close()
    return out_path, thumb_path
