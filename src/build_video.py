"""Собирает вертикальное видео: стоковые клипы (быстрый монтаж) + аудио + karaoke-субтитры."""
import glob
import math
import os
import random
import tempfile

from PIL import Image, ImageDraw

# Windows: moviepy 1.0.3 ищет legacy convert.exe, в ImageMagick 7+ бинарник называется magick.exe.
for _candidate in glob.glob(r"C:\Program Files\ImageMagick-*\magick.exe"):
    os.environ.setdefault("IMAGEMAGICK_BINARY", _candidate)
    break

from moviepy.editor import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
    VideoFileClip,
    afx,
    concatenate_videoclips,
)

from config import CFG
from fetch_music import fetch_random_track

MUSIC_VOLUME = 0.10  # тихо под голосом, не должна перетягивать внимание

TARGET_SIZE = (1080, 1920)
CAPTION_Y = int(TARGET_SIZE[1] * 0.78)  # ближе к низу, но всё ещё выше названия канала/кнопок Shorts
CTA_DURATION = 2.0  # сколько секунд в конце висит призыв лайкнуть/подписаться
CTA_PULSES = 3  # сколько раз "тапает" сердечко за время показа CTA

# Вариативность оформления между видео — чтобы не получался один и тот же шаблон
# каждый раз (YouTube следит за такой "inauthentic content" повторяемостью).
ZOOM_FACTORS = [1.05, 1.08, 1.12, 1.15]
CAPTION_COLORS = ["white", "yellow", "#7CFFCB"]


def _pick_zoom_factor() -> float:
    return random.choice(ZOOM_FACTORS)


def _pick_caption_color() -> str:
    return random.choice(CAPTION_COLORS)


def _pick_cta_phrase() -> str:
    return random.choice(CFG["cta_phrases"])


def _fit_clip(clip: VideoFileClip, duration: float, zoom_factor: float) -> VideoFileClip:
    clip = clip.without_audio().resize(height=TARGET_SIZE[1])
    if clip.w < TARGET_SIZE[0]:
        clip = clip.resize(width=TARGET_SIZE[0])
    clip = clip.crop(x_center=clip.w / 2, y_center=clip.h / 2, width=TARGET_SIZE[0], height=TARGET_SIZE[1])
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
    color = _pick_caption_color()
    clips = []
    for w in words:
        if w["start"] >= cutoff:
            continue
        end = min(w["end"], cutoff)
        clip = (
            TextClip(
                w["text"].upper(),
                fontsize=100,
                color=color,
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


def _draw_heart_png(path: str, size: int = 200) -> None:
    """Рисует классическую округлую форму сердца (параметрическая кривая), а не полагается
    на то, как конкретный шрифт рендерит символ ♥/❤ — те выходили угловатыми/нечитаемыми."""
    scale = 4  # суперсэмплинг для сглаживания краёв
    big = size * scale
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    points = []
    for deg in range(720):
        t = math.radians(deg / 2)
        x = 16 * math.sin(t) ** 3
        y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
        points.append((x, y))
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    pad = 0.08
    cx, cy = (min_x + max_x) / 2, (min_y + max_y) / 2

    def transform(p, expand=1.0):
        nx = (p[0] - cx) * expand + cx
        ny = (p[1] - cy) * expand + cy
        nx = (nx - min_x) / (max_x - min_x)
        ny = (ny - min_y) / (max_y - min_y)
        return (pad * big + nx * (1 - 2 * pad) * big, pad * big + ny * (1 - 2 * pad) * big)

    # Чёрная подложка чуть крупнее красного сердца поверх — даёт чистый контур без
    # артефактов "бахромы", которые получаются от ImageDraw.polygon(outline=..., width=...)
    # на многоточечном контуре.
    outline_polygon = [transform(p, expand=1.12) for p in points]
    draw.polygon(outline_polygon, fill=(0, 0, 0, 255))
    fill_polygon = [transform(p, expand=1.0) for p in points]
    draw.polygon(fill_polygon, fill=(225, 25, 25, 255))

    img = img.resize((size, size), Image.LANCZOS)
    img.save(path)


def _cta_clips(duration: float) -> list[ImageClip]:
    # Размер увеличен на ~27% и сдвинут в верхне-среднюю зону по данным о поведении
    # зрителей: CTA лучше работает выше центра, подальше от нижней зоны с реальными
    # кнопками платформы, и с мягкой, а не резкой пульсацией (тише, но всё ещё заметно).
    cta_duration = min(CTA_DURATION, duration)
    start = max(duration - cta_duration, 0)
    heart_y = int(TARGET_SIZE[1] * 0.24)
    label_y = heart_y + 230

    heart_png = os.path.join(tempfile.mkdtemp(), "heart.png")
    _draw_heart_png(heart_png, size=200)

    heart = ImageClip(heart_png)
    # Мягкая пульсация — плавная синусоида небольшой амплитуды вместо резкого "попа".
    pulse = lambda t: 1 + 0.12 * max(0.0, math.sin(t * CTA_PULSES * math.pi / max(cta_duration, 0.01))) ** 2
    heart = (
        heart.resize(pulse)
        .set_position(lambda t: ("center", heart_y - int(25 * (pulse(t) - 1))))
        .set_start(start)
        .set_duration(cta_duration)
    )

    label = (
        TextClip(
            _pick_cta_phrase(),
            fontsize=48,
            color="white",
            font="Arial-Bold",
            stroke_color="black",
            stroke_width=4,
            size=(TARGET_SIZE[0] - 160, None),
            method="caption",
            align="center",
        )
        .set_position(("center", label_y))
        .set_start(start)
        .set_duration(cta_duration)
    )

    return [heart, label]


def _mix_music(voice_audio: AudioFileClip, duration: float):
    music_path = os.path.join(tempfile.mkdtemp(), "music.mp3")
    try:
        found = fetch_random_track(music_path)
    except Exception:
        found = False
    if not found:
        return voice_audio

    try:
        music = AudioFileClip(music_path)
        music = afx.audio_loop(music, duration=duration).volumex(MUSIC_VOLUME)
        return CompositeAudioClip([music, voice_audio])
    except Exception:
        return voice_audio


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
    mixed_audio = _mix_music(audio, duration)

    final = CompositeVideoClip([background, *caption_clips, *cta_clips], size=TARGET_SIZE).set_audio(mixed_audio)
    final.write_videofile(out_path, fps=30, codec="libx264", audio_codec="aac", logger=None)
    return out_path
