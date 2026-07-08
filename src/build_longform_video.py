"""Горизонтальный (16:9, 1920×1080) билдер для лонгформа.

Лонгформ смотрят с десктопа/ТВ, поэтому формат горизонтальный, а не вертикальный
как Shorts. Это упрощённый билдер: фон из стоковых клипов + лёгкий зум + караоке-субтитры
снизу. Без Shorts-фишек (хук-плашка, CTA-пульс, петля, PART-оверлей) — они тут не нужны.
Переиспользует шрифт/аудио/тумбу из build_video, но со своим размером кадра."""
import base64
import io
import os
import tempfile

from PIL import Image, ImageDraw, ImageFont

# build_video импортируем ПЕРВЫМ: он на Windows ставит IMAGEMAGICK_BINARY до импорта moviepy.
# Если moviepy импортнуть раньше — на Windows TextClip не находит ImageMagick (в CI/Linux ок).
import build_video as bv
from build_video import SUBTITLE_FONT, _build_audio, _pick_zoom_factor
from moviepy.editor import (
    AudioFileClip,
    CompositeVideoClip,
    TextClip,
    VideoFileClip,
    concatenate_videoclips,
)

TARGET_SIZE = (1920, 1080)
CAPTION_Y = int(TARGET_SIZE[1] * 0.80)  # субтитры в нижней трети, не перекрывают центр кадра

# Тумба лонгформа — vision-отбор кадра (2026-07-08): раньше кадр брался ВСЕГДА на t=0.5s
# (фактически случайный момент начала первого стокового клипа, без учёта того, хороший ли
# это кадр — статичный/смазанный/тёмный). Тот же паттерн, что уже используется для отбора
# стоковых клипов (fetch_stock_video.py, Haiku-vision) — сэмплируем несколько тайм-кодов,
# просим Haiku выбрать самый чёткий/выразительный с одним ясным фокусом (см. CTR-гайд:
# "one clear focal point", "viewer decides in under 1 second"). Дёшево (1 доп. Haiku-вызов
# на лонгформ, раз в неделю), безопасный фолбэк на старое поведение при любой ошибке.
_THUMB_CANDIDATE_FRACTIONS = (0.15, 0.35, 0.55, 0.75)


def _pick_thumb_frame(background, duration: float):
    """Возвращает numpy-кадр, выбранный Haiku из нескольких кандидатов по duration.
    Фолбэк на t=0.5s (старое поведение) при отсутствии ключа/сбое API/некорректном ответе."""
    fallback = background.get_frame(0.5)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return fallback
    try:
        from anthropic import Anthropic

        times = [duration * f for f in _THUMB_CANDIDATE_FRACTIONS if duration * f > 0.3]
        if len(times) < 2:
            return fallback
        frames = [background.get_frame(t) for t in times]

        content = [{"type": "text", "text": (
            f"Pick the best YouTube thumbnail frame from these {len(frames)} candidates "
            "(numbered 1 to N) for a fact/deep-dive video. Prefer: one clear focal point, "
            "sharp (not motion-blurred), good contrast, visually striking. Avoid: near-black "
            "or near-white frames, cluttered/busy compositions, mid-transition blur. "
            "Reply with ONLY the number."
        )}]
        for idx, frame in enumerate(frames, 1):
            buf = io.BytesIO()
            Image.fromarray(frame).convert("RGB").save(buf, format="JPEG", quality=80)
            b64 = base64.b64encode(buf.getvalue()).decode()
            content.append({"type": "text", "text": f"Frame {idx}:"})
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg", "data": b64}})

        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        response = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=10,
            messages=[{"role": "user", "content": content}],
        )
        pick = int(response.content[0].text.strip()[0]) - 1
        pick = max(0, min(pick, len(frames) - 1))
        print(f"  Vision picked thumb frame {pick + 1}/{len(frames)} (t={times[pick]:.1f}s)")
        return frames[pick]
    except Exception as e:
        print(f"  Vision thumb pick упал, фолбэк на t=0.5s: {e}")
        return fallback


def _save_longform_thumb(img: Image.Image, path: str, hook_text: str | None) -> None:
    """Тумба лонгформа (16:9): крупная короткая фраза-хук на затемнённой нижней трети.
    Рисуем именно короткий thumb_text (3-5 слов), а НЕ длинный заголовок — иначе кадр
    захламляется мелким текстом. Если фразы нет — отдаём чистый кадр."""
    img = img.convert("RGB")
    if not hook_text or not hook_text.strip():
        img.save(path, "JPEG", quality=90)
        return

    W, H = img.size
    text = hook_text.strip().upper()
    max_w = int(W * 0.88)
    draw = ImageDraw.Draw(img)

    # Подбираем размер шрифта так, чтобы фраза влезла максимум в 2 строки.
    font_size = 170
    while font_size > 60:
        try:
            font = ImageFont.truetype(bv._ANTON, font_size)
        except Exception:
            font = ImageFont.load_default()
        lines, cur = [], ""
        for w in text.split():
            t = (cur + " " + w).strip()
            if draw.textbbox((0, 0), t, font=font)[2] <= max_w:
                cur = t
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        if len(lines) <= 2 and all(
            draw.textbbox((0, 0), l, font=font)[2] <= max_w for l in lines
        ):
            break
        font_size -= 10

    line_h = font_size + 16
    block_h = len(lines) * line_h
    band_top = max(0, H - block_h - 130)

    # Затемняющая полоса снизу — текст читается на любом кадре.
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rectangle([(0, band_top), (W, H)], fill=(0, 0, 0, 150))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    y = band_top + 60
    for l in lines:
        bbox = draw.textbbox((0, 0), l, font=font)
        x = (W - (bbox[2] - bbox[0])) // 2 - bbox[0]
        for dx, dy in [(-3, 0), (3, 0), (0, -3), (0, 3)]:  # чёрная обводка
            draw.text((x + dx, y + dy), l, font=font, fill="black")
        draw.text((x, y), l, font=font, fill="white")
        y += line_h
    img.save(path, "JPEG", quality=90)


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
    # Понятная ошибка вместо ZeroDivisionError: клипов нет только если все стоковые запросы
    # пусты/упали (см. build_video.py). Явный текст в Telegram-алерт вместо «division by zero».
    if not clip_paths:
        raise RuntimeError("Нет стоковых клипов (все запросы к Pexels/Pixabay пусты или упали) — лонгформ не собрать.")
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
    thumb_text: str | None = None,
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

    # Тумба — кадр (vision-отбор, см. _pick_thumb_frame) + крупная короткая фраза-хук
    # (thumb_text), не весь заголовок.
    thumb_path = os.path.splitext(out_path)[0] + "_thumb.jpg"
    frame = _pick_thumb_frame(background, duration)
    _save_longform_thumb(Image.fromarray(frame), thumb_path, thumb_text or title)

    final.close()
    audio.close()
    return out_path, thumb_path
