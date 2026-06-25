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

MUSIC_VOLUME = 0.18  # тихо под голосом, но должна реально быть слышна

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


def _draw_heart_png(path: str, size: int = 220) -> None:
    """Плоское emoji-стиль сердце: два круга + ромб снизу, белый ободок.
    Такой формат (идентичный кнопке лайка YouTube) лучше ассоциируется с действием."""
    scale = 4
    big = size * scale
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Сердце = два круга сверху + повёрнутый квадрат снизу.
    # Параметры подобраны чтобы форма выглядела как ❤️ emoji.
    r = big * 0.27
    # левый круг
    lx, ly = big * 0.29, big * 0.30
    # правый круг
    rx, ry = big * 0.71, big * 0.30
    # нижняя точка
    bx, by = big * 0.50, big * 0.88

    WHITE = (255, 255, 255, 255)
    RED   = (255, 23, 68, 255)   # #FF1744 — YouTube-red

    # белый ободок (чуть крупнее)
    expand = 1.13
    draw.ellipse([lx - r*expand, ly - r*expand, lx + r*expand, ly + r*expand], fill=WHITE)
    draw.ellipse([rx - r*expand, ry - r*expand, rx + r*expand, ry + r*expand], fill=WHITE)
    # белый треугольник снизу
    draw.polygon([
        (lx - r*expand*0.6, ly + r*0.5),
        (rx + r*expand*0.6, ry + r*0.5),
        (bx, by + big*0.04),
    ], fill=WHITE)

    # красное сердце поверх
    draw.ellipse([lx - r, ly - r, lx + r, ly + r], fill=RED)
    draw.ellipse([rx - r, ry - r, rx + r, ry + r], fill=RED)
    draw.polygon([
        (lx - r*0.6, ly + r*0.5),
        (rx + r*0.6, ry + r*0.5),
        (bx, by),
    ], fill=RED)

    img = img.resize((size, size), Image.LANCZOS)
    img.save(path)


def _draw_cta_badge(path: str, text: str, width: int = 760) -> None:
    """Рисует pill-бэйдж с белым текстом на полупрозрачном тёмном фоне через PIL.
    Это надёжнее чем TextClip+stroke — текст читается на любом фоне кадра."""
    from PIL import ImageFont

    font_path = None
    for candidate in [
        r"C:\Windows\Fonts\arialbd.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]:
        if os.path.exists(candidate):
            font_path = candidate
            break

    font_size = 62
    try:
        font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    # Измеряем текст
    dummy = Image.new("RGBA", (1, 1))
    d = ImageDraw.Draw(dummy)
    lines = text.split("\n")
    line_h = font_size + 16
    total_h = len(lines) * line_h
    pad_x, pad_y = 48, 28

    h = total_h + pad_y * 2
    img = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Тёмная полупрозрачная pill-подложка
    r = h // 2
    draw.rounded_rectangle([0, 0, width - 1, h - 1], radius=r, fill=(0, 0, 0, 175))

    # Белый текст по центру
    y = pad_y
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        lw = bbox[2] - bbox[0]
        x = (width - lw) // 2
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_h

    img.save(path)


def _cta_clips(duration: float) -> list[ImageClip]:
    cta_duration = min(CTA_DURATION, duration)
    start = max(duration - cta_duration, 0)
    heart_y = int(TARGET_SIZE[1] * 0.24)

    tmp = tempfile.mkdtemp()
    heart_png = os.path.join(tmp, "heart.png")
    badge_png = os.path.join(tmp, "badge.png")

    _draw_heart_png(heart_png, size=220)
    _draw_cta_badge(badge_png, _pick_cta_phrase(), width=700)

    heart = ImageClip(heart_png)
    pulse = lambda t: 1 + 0.14 * max(0.0, math.sin(t * CTA_PULSES * math.pi / max(cta_duration, 0.01))) ** 2
    heart = (
        heart.resize(pulse)
        .set_position(lambda t: ("center", heart_y - int(30 * (pulse(t) - 1))))
        .set_start(start)
        .set_duration(cta_duration)
    )

    badge_h = ImageClip(badge_png).size[1]
    badge_y = heart_y + 250
    badge = (
        ImageClip(badge_png)
        .set_position(("center", badge_y))
        .set_start(start)
        .set_duration(cta_duration)
    )

    return [heart, badge]


def _mix_music(voice_audio: AudioFileClip, duration: float, topic: str | None):
    music_path = os.path.join(tempfile.mkdtemp(), "music.mp3")
    try:
        found = fetch_random_track(music_path, topic=topic)
    except Exception:
        found = False
    if not found:
        return voice_audio

    try:
        music = AudioFileClip(music_path)
        # Нормализуем громкость исходника перед множителем -- иначе если сам трек
        # записан тихо, MUSIC_VOLUME от него получается почти неслышным.
        music = afx.audio_normalize(music)
        music = afx.audio_loop(music, duration=duration).volumex(MUSIC_VOLUME)
        return CompositeAudioClip([music, voice_audio])
    except Exception:
        return voice_audio


PART_LABEL_DURATION = 2.5  # секунд показа "PART N / 3" в начале видео


def _part_label_clip(part: int, total: int) -> TextClip:
    """Полупрозрачный оверлей 'PART 1 / 3' в верхней части экрана на первые 2.5 сек."""
    label = TextClip(
        f"PART {part} / {total}",
        fontsize=72,
        color="white",
        font="Arial-Bold",
        stroke_color="black",
        stroke_width=5,
    )
    label = (
        label
        .set_position(("center", int(TARGET_SIZE[1] * 0.08)))
        .set_start(0)
        .set_duration(PART_LABEL_DURATION)
    )
    return label


def build_video(
    audio_path: str,
    clip_paths: list[str],
    words: list[dict],
    out_path: str,
    topic: str | None = None,
    part: int | None = None,
    total_parts: int = 3,
    title: str | None = None,
    **kwargs,
) -> tuple[str, str]:
    """Returns (video_path, thumbnail_path)."""
    audio = AudioFileClip(audio_path)
    duration = audio.duration

    if not clip_paths:
        raise ValueError("No video clips provided to build_video")

    cta_duration = min(CTA_DURATION, duration)
    cta_start = max(duration - cta_duration, 0)

    background = _build_background(clip_paths, duration)
    caption_clips = _karaoke_clips(words, cutoff=cta_start)
    cta_clips = _cta_clips(duration)
    part_clips = [_part_label_clip(part, total_parts)] if part else []
    final = CompositeVideoClip(
        [background, *caption_clips, *cta_clips, *part_clips], size=TARGET_SIZE
    ).set_audio(audio)
    final.write_videofile(out_path, fps=30, codec="libx264", audio_codec="aac", logger=None)

    thumb_path = out_path.replace(".mp4", "_thumb.jpg")
    frame = final.get_frame(min(1.0, duration * 0.1))
    _save_thumbnail(Image.fromarray(frame).convert("RGB"), thumb_path, title=title)

    return out_path, thumb_path


def _save_thumbnail(img: Image.Image, path: str, title: str | None = None) -> None:
    """Сохраняет thumbnail. Если передан title — рисует текст поверх кадра."""
    if not title:
        img.save(path, "JPEG")
        return

    from PIL import ImageFont
    draw = ImageDraw.Draw(img)
    W, H = img.size

    # Полупрозрачная тёмная полоса снизу под текстом
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    ov_draw.rectangle([(0, H - 420), (W, H)], fill=(0, 0, 0, 160))
    img = img.convert("RGBA")
    img = Image.alpha_composite(img, overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    # Подбираем размер шрифта чтобы текст влез в ширину
    font_path = None
    for candidate in [
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\Arial Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]:
        if os.path.exists(candidate):
            font_path = candidate
            break

    max_w = W - 80
    font_size = 96
    while font_size > 40:
        try:
            font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
        except Exception:
            font = ImageFont.load_default()
        # Перенос слов вручную
        words_list = title.upper().split()
        lines, current = [], ""
        for word in words_list:
            test = (current + " " + word).strip()
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] - bbox[0] <= max_w:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)

        # Проверяем что все строки влезают
        too_wide = any(
            draw.textbbox((0, 0), l, font=font)[2] - draw.textbbox((0, 0), l, font=font)[0] > max_w
            for l in lines
        )
        if not too_wide and len(lines) <= 3:
            break
        font_size -= 8

    try:
        font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    line_h = font_size + 12
    total_h = len(lines) * line_h
    y = H - total_h - 48

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        lw = bbox[2] - bbox[0]
        x = (W - lw) // 2
        # Тень
        draw.text((x + 4, y + 4), line, font=font, fill=(0, 0, 0, 200))
        draw.text((x, y), line, font=font, fill=(255, 255, 255))
        y += line_h

    img.save(path, "JPEG")
