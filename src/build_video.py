"""Собирает вертикальное видео: стоковые клипы (быстрый монтаж) + аудио + karaoke-субтитры."""
import glob
import math
import os

# Windows: moviepy 1.0.3 ищет legacy convert.exe, в ImageMagick 7+ бинарник называется magick.exe.
for _candidate in glob.glob(r"C:\Program Files\ImageMagick-*\magick.exe"):
    os.environ.setdefault("IMAGEMAGICK_BINARY", _candidate)
    break

from moviepy.editor import (
    AudioFileClip,
    CompositeVideoClip,
    TextClip,
    VideoFileClip,
    concatenate_videoclips,
)

TARGET_SIZE = (1080, 1920)
ZOOM_FACTOR = 1.08
CAPTION_Y = int(TARGET_SIZE[1] * 0.78)  # ближе к низу, но всё ещё выше названия канала/кнопок Shorts
CTA_DURATION = 2.0  # сколько секунд в конце висит призыв лайкнуть/подписаться
CTA_PULSES = 3  # сколько раз "тапает" сердечко за время показа CTA


def _fit_clip(clip: VideoFileClip, duration: float) -> VideoFileClip:
    clip = clip.without_audio().resize(height=TARGET_SIZE[1])
    if clip.w < TARGET_SIZE[0]:
        clip = clip.resize(width=TARGET_SIZE[0])
    clip = clip.crop(x_center=clip.w / 2, y_center=clip.h / 2, width=TARGET_SIZE[0], height=TARGET_SIZE[1])
    if clip.duration < duration:
        loops = int(duration // clip.duration) + 1
        clip = clip.loop(n=loops)
    clip = clip.subclip(0, duration)
    clip = clip.resize(lambda t: 1 + (ZOOM_FACTOR - 1) * (t / max(duration, 0.01)))
    return clip.set_position("center")


def _build_background(clip_paths: list[str], duration: float) -> CompositeVideoClip:
    per_clip = duration / len(clip_paths)
    fitted = [_fit_clip(VideoFileClip(p), per_clip) for p in clip_paths]
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
                fontsize=100,
                color="white",
                font="Arial-Bold",
                stroke_color="black",
                stroke_width=5,
                size=(TARGET_SIZE[0] - 100, None),
                method="caption",
            )
            .set_position(("center", CAPTION_Y))
            .set_start(w["start"])
            .set_duration(max(end - w["start"], 0.05))
        )
        clips.append(clip)
    return clips


def _cta_clips(duration: float) -> list[TextClip]:
    cta_duration = min(CTA_DURATION, duration)
    start = max(duration - cta_duration, 0)
    heart_y = int(TARGET_SIZE[1] * 0.40)
    label_y = heart_y + 270

    heart = TextClip(
        "♥",
        fontsize=200,
        color="red",
        font="Arial-Bold",
        stroke_color="black",
        stroke_width=3,
        method="label",
    )
    # Резкий "поп" при каждом тапе вместо плавной синусоиды — больше похоже на нажатие кнопки.
    pulse = lambda t: 1 + 0.35 * max(0.0, math.sin(t * CTA_PULSES * math.pi / max(cta_duration, 0.01))) ** 6
    heart = (
        heart.resize(pulse)
        .set_position(lambda t: ("center", heart_y - int(55 * (pulse(t) - 1))))
        .set_start(start)
        .set_duration(cta_duration)
    )

    label = (
        TextClip(
            "LIKE & FOLLOW for more",
            fontsize=60,
            color="white",
            font="Arial-Bold",
            stroke_color="black",
            stroke_width=4,
            size=(TARGET_SIZE[0] - 140, None),
            method="caption",
            align="center",
        )
        .set_position(("center", label_y))
        .set_start(start)
        .set_duration(cta_duration)
    )

    return [heart, label]


def build_video(
    audio_path: str,
    clip_paths: list[str],
    words: list[dict],
    out_path: str,
) -> str:
    audio = AudioFileClip(audio_path)
    duration = audio.duration

    if not clip_paths:
        raise ValueError("No video clips provided to build_video")

    cta_duration = min(CTA_DURATION, duration)
    cta_start = max(duration - cta_duration, 0)

    background = _build_background(clip_paths, duration)
    caption_clips = _karaoke_clips(words, cutoff=cta_start)
    cta_clips = _cta_clips(duration)

    final = CompositeVideoClip([background, *caption_clips, *cta_clips], size=TARGET_SIZE).set_audio(audio)
    final.write_videofile(out_path, fps=30, codec="libx264", audio_codec="aac", logger=None)
    return out_path
