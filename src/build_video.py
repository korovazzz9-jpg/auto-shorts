"""Собирает вертикальное видео: стоковые клипы (быстрый монтаж) + аудио + karaoke-субтитры."""
import glob
import math
import os
import random
import shutil
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

# Шрифт субтитров и хука. По умолчанию — Anton (узкий жирный, выбран после теста
# Anton/LuckiestGuy/ArchivoBlack), лежит в репо → работает и на CI/Ubuntu без системных шрифтов.
# Можно переопределить env-переменной SUBTITLE_FONT (путь к .ttf или имя системного шрифта).
_ANTON = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts", "Anton.ttf")
SUBTITLE_FONT = os.environ.get("SUBTITLE_FONT", _ANTON)

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


def _pick_cta_phrase(topic: str | None = None) -> str:
    """Topic-aware CTA: если для темы есть слово — персональный призыв
    («FOLLOW for more OCEAN facts»), иначе генерик-фраза из cta_phrases."""
    words = CFG.get("topic_cta_words", {})
    template = CFG.get("cta_topic_template")
    if topic and template and topic in words:
        return template.format(word=words[topic])
    return random.choice(CFG["cta_phrases"])


def _fit_clip(clip: VideoFileClip, duration: float, zoom_factor: float, loop: bool = False) -> VideoFileClip:
    clip = clip.without_audio().resize(height=TARGET_SIZE[1])
    if clip.w < TARGET_SIZE[0]:
        clip = clip.resize(width=TARGET_SIZE[0])
    clip = clip.crop(x_center=clip.w / 2, y_center=clip.h / 2, width=TARGET_SIZE[0], height=TARGET_SIZE[1])
    if clip.duration < duration:
        if loop:
            loops = int(duration // clip.duration) + 1
            clip = clip.loop(n=loops)
        else:
            duration = clip.duration
    clip = clip.subclip(0, duration)
    clip = clip.resize(lambda t: 1 + (zoom_factor - 1) * (t / max(duration, 0.01)))
    return clip.set_position("center")


def _build_background(clip_paths: list[str], duration: float, visual_loop: bool = True) -> CompositeVideoClip:
    # Визуальный loop: первый клип повторяем в конце — кадр конца ≈ кадр начала,
    # петля (которую держит и текстовый loop в скрипте) ощущается бесшовной → больше пересмотров.
    # Только для daily (там есть текстовый loop и молчаливый follow-бейдж). У серий в конце
    # ОЗВУЧЕННЫЙ CTA («follow for Part 2/3») — зацикливать видео на начало после него бессмысленно
    # и режет ощущение (build_video.py вызывается и для daily, и для series — visual_loop=False
    # для серий передаётся из pipeline_series.py).
    # ВАЖНО: копируем в отдельный файл — нельзя открывать один и тот же файл двумя
    # VideoFileClip-ридерами (второй читает чёрные кадры → чёрный конец видео).
    clip_paths = list(clip_paths)
    # Понятная ошибка вместо ZeroDivisionError ниже: клипов нет, только если ВСЕ стоковые
    # запросы не нашли/не скачали видео (оба стока легли или пустая выдача). Явный текст
    # уходит в Telegram-алерт (🔴), а не «division by zero».
    if not clip_paths:
        raise RuntimeError("Нет стоковых клипов (все запросы к Pexels/Pixabay пусты или упали) — видео не собрать.")
    if visual_loop and len(clip_paths) >= 2:
        loop_tail = os.path.join(tempfile.mkdtemp(), "loop_tail" + os.path.splitext(clip_paths[0])[1])
        shutil.copy2(clip_paths[0], loop_tail)
        clip_paths.append(loop_tail)

    per_clip = duration / len(clip_paths)
    fitted = [
        _fit_clip(VideoFileClip(p), per_clip, _pick_zoom_factor(), loop=(i == len(clip_paths) - 1))
        for i, p in enumerate(clip_paths)
    ]
    sequence = concatenate_videoclips(fitted, method="compose")
    return CompositeVideoClip([sequence], size=TARGET_SIZE).set_duration(duration)


WORD_POP_DURATION = 0.12  # сек scale-анимации появления слова (word-pop, 2026-07-05)
WORD_POP_SCALE = 1.18     # стартовый масштаб «выпрыгивания»


def _karaoke_clips(words: list[dict], cutoff: float) -> list[TextClip]:
    color = _pick_caption_color()
    # Числа — главные анкоры фактов («100,000 years», «4.5mm») — выделяем контрастным
    # цветом. Только цифры (не имена): у имён нет надёжного сигнала в верхнем регистре.
    accent = "yellow" if color != "yellow" else "white"
    clips = []
    for w in words:
        if w["start"] >= cutoff:
            continue
        end = min(w["end"], cutoff)
        has_digit = any(ch.isdigit() for ch in w["text"])
        clip = (
            TextClip(
                w["text"].upper(),
                fontsize=100,
                color=accent if has_digit else color,
                font=SUBTITLE_FONT,
                stroke_color="black",
                stroke_width=5,
                size=(TARGET_SIZE[0] - 100, None),
                method="caption",
            )
            .set_position(("center", CAPTION_Y))
            .set_start(w["start"])
            .set_duration(max(end - w["start"], 0.05))
            # Word-pop (2026-07-05): слово «выпрыгивает» при появлении (1.18 → 1.0 за 0.12с) —
            # стандарт живых вирусных субтитров; после POP_DURATION масштаб стабильно 1.0.
            .resize(lambda t: max(1.0, WORD_POP_SCALE - (WORD_POP_SCALE - 1.0) * t / WORD_POP_DURATION))
        )
        clips.append(clip)
    return clips


def _cubic_bezier(p0, p1, p2, p3, n=40):
    """Возвращает n точек кубической кривой Безье."""
    pts = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        x = u**3*p0[0] + 3*u**2*t*p1[0] + 3*u*t**2*p2[0] + t**3*p3[0]
        y = u**3*p0[1] + 3*u**2*t*p1[1] + 3*u*t**2*p2[1] + t**3*p3[1]
        pts.append((x, y))
    return pts


def _draw_heart_png(path: str, size: int = 600) -> None:
    """Сердце через кубические безье (вариант 1) + тонкая тень.
    Рендерится в 440px чтобы при анимации масштаба не было пикселизации."""
    scale = 4
    big = size * scale
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # SVG path варианта 1: M0,-18 C2,-38 28,-46 38,-28 C48,-10 28,12 0,38
    #                       C-28,12 -48,-10 -38,-28 C-28,-46 -2,-38 0,-18 Z
    # Масштабируем под big, центр = (big/2, big/2 + small_offset)
    cx, cy = big * 0.5, big * 0.52
    sc = big * 0.011  # подбираем чтобы сердце занимало ~80% canvas

    def s(nx, ny):
        return (cx + nx * sc, cy + ny * sc)

    segments = [
        _cubic_bezier(s(0,-18), s(2,-38),  s(28,-46), s(38,-28)),
        _cubic_bezier(s(38,-28), s(48,-10), s(28,12),  s(0,38)),
        _cubic_bezier(s(0,38),  s(-28,12), s(-48,-10), s(-38,-28)),
        _cubic_bezier(s(-38,-28), s(-28,-46), s(-2,-38), s(0,-18)),
    ]
    pts = [pt for seg in segments for pt in seg]

    def shifted(dx, dy):
        return [(x + dx, y + dy) for x, y in pts]

    # тонкая тень
    draw.polygon(shifted(big*0.006, big*0.008), fill=(0, 0, 0, 70))
    # красное сердце
    draw.polygon(pts, fill=(255, 23, 68, 255))

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


def _cta_clips(duration: float, topic: str | None = None) -> list[ImageClip]:
    cta_duration = min(CTA_DURATION, duration)
    start = max(duration - cta_duration, 0)
    heart_y = int(TARGET_SIZE[1] * 0.24)

    tmp = tempfile.mkdtemp()
    heart_png = os.path.join(tmp, "heart.png")
    badge_png = os.path.join(tmp, "badge.png")

    _draw_heart_png(heart_png)  # рендерится в 600px — анимация всегда downscale, без пикселей
    _draw_cta_badge(badge_png, _pick_cta_phrase(topic), width=700)

    BASE = 220  # базовый размер сердца в видео (px)
    # pulse всегда downscale с 600px → 220-251px, пикселей нет
    pulse_raw = lambda t: 1 + 0.14 * max(0.0, math.sin(t * CTA_PULSES * math.pi / max(cta_duration, 0.01))) ** 2
    pulse = lambda t: BASE * pulse_raw(t) / 600
    heart = (
        ImageClip(heart_png)
        .resize(pulse)
        .set_position(lambda t: ("center", heart_y - int(30 * (pulse_raw(t) - 1))))
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


PART_LABEL_DURATION = 2.5  # секунд показа "PART N / 3" в начале видео
HOOK_DURATION = 2.8  # секунд показа крупного текста-хука (стоп-скролл в первой секунде)
LOOP_TAIL_PAD = 0.18  # запас после последнего слова при обрезке хвоста тишины (чтобы не резать слово)


HOOK_BOX_OPACITY = 0.4   # прозрачность тёмной плашки под хуком
HOOK_BOX_PAD_Y = 24      # вертикальный отступ плашки


def _hook_box_png(w: int, h: int, path: str) -> None:
    img = Image.new("RGBA", (w, h), (0, 0, 0, int(255 * HOOK_BOX_OPACITY)))
    img.save(path)


def _hook_clips(title: str) -> list:
    """Текст-хук на полупрозрачной тёмной плашке от края до края."""
    txt = TextClip(
        title.upper(),
        fontsize=120,
        color="white",
        font=SUBTITLE_FONT,
        size=(TARGET_SIZE[0] - 140, None),
        method="caption",
    )
    tw, th = txt.size
    box_png = os.path.join(tempfile.mkdtemp(), "hookbox.png")
    _hook_box_png(TARGET_SIZE[0], th + 2 * HOOK_BOX_PAD_Y, box_png)

    y = int(TARGET_SIZE[1] * 0.30)
    box = (ImageClip(box_png).set_position((0, y - HOOK_BOX_PAD_Y))
           .set_start(0).set_duration(HOOK_DURATION))
    txt = (txt.set_position(("center", y)).set_start(0).set_duration(HOOK_DURATION))
    return [box, txt]


def _part_label_clip(part: int, total: int) -> TextClip:
    """Оверлей 'PART 1/3' (Anton) в верхней части экрана на первые 2.5 сек."""
    label = TextClip(
        f"PART {part}/{total}",
        fontsize=72,
        color="white",
        font=SUBTITLE_FONT,  # Anton — единый шрифт с субтитрами/хуком/тумба-бейджем
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


def _draw_part_badge(thumb_path: str, part: int, total: int) -> None:
    """Дорисовывает крупный бейдж «PART N/T» сверху готовой тумбы серии через PIL.
    Делаем именно в PIL (а не полагаемся на in-video TextClip): на CI/Ubuntu системного
    Arial-Bold нет, поэтому MoviePy-лейбл мог не отрисоваться в кадре-тумбе. Бейдж нужен,
    чтобы зритель в ленте сразу видел, что это часть серии, и искал остальные части."""
    from PIL import ImageFont
    img = Image.open(thumb_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    W, H = img.size
    text = f"PART {part}/{total}"
    try:
        font = ImageFont.truetype(_ANTON, 120)
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 48, 28
    cx = W // 2
    by0 = int(H * 0.04)
    pill = [cx - tw // 2 - pad_x, by0, cx + tw // 2 + pad_x, by0 + th + 2 * pad_y]
    draw.rounded_rectangle(pill, radius=28, fill=(214, 40, 40))  # красная пилюля — заметна в ленте
    draw.text((cx - tw // 2 - bbox[0], by0 + pad_y - bbox[1]), text, font=font, fill="white")
    img.save(thumb_path, "JPEG", quality=90)


MUSIC_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "music")
MUSIC_LOOP_VOLUME = 0.12  # фоновый луп под голосом — тихо, но слышно


def _music_layer(duration: float):
    """Случайный фоновый луп из assets/music/ (ротация против шаблонности),
    нормализован, зациклен под длину видео, тихо под голосом."""
    try:
        tracks = glob.glob(os.path.join(MUSIC_DIR, "*.mp3"))
        if not tracks:
            return None
        m = AudioFileClip(random.choice(tracks))
        m = afx.audio_normalize(m)
        return afx.audio_loop(m, duration=duration).volumex(MUSIC_LOOP_VOLUME)
    except Exception as e:
        print(f"  Музыка пропущена: {e}")
        return None


def _build_audio(voice, words: list[dict], duration: float):
    """Финальная дорожка: голос + фоновый луп. Если музыки нет — только голос."""
    music = _music_layer(duration)
    return CompositeAudioClip([voice, music]) if music is not None else voice


def build_video(
    audio_path: str,
    clip_paths: list[str],
    words: list[dict],
    out_path: str,
    topic: str | None = None,
    part: int | None = None,
    total_parts: int = 3,
    title: str | None = None,
    hook_text: str | None = None,
    **kwargs,
) -> tuple[str, str]:
    """Returns (video_path, thumbnail_path).

    hook_text — текст ON-SCREEN хук-плашки. Если задан, отличается от произносимой первой
    фразы (двойной хук: глаз+ухо). Если None — используем title (обратная совместимость)."""
    audio = AudioFileClip(audio_path)
    duration = audio.duration

    if not clip_paths:
        raise ValueError("No video clips provided to build_video")

    # Обрезаем хвост тишины TTS после последнего слова — иначе перед зацикливанием
    # видна пауза. Оставляем небольшой запас, чтобы не отрезать само слово.
    if words:
        duration = min(duration, words[-1]["end"] + LOOP_TAIL_PAD)
        audio = audio.subclip(0, duration)

    cta_duration = min(CTA_DURATION, duration)
    cta_start = max(duration - cta_duration, 0)

    # Серия (part задан) заканчивается ОЗВУЧЕННЫМ CTA («follow for Part 2/3») — визуальный
    # loop-хвост (видео тела зацикливается на начало) после него не нужен, в отличие от daily.
    background = _build_background(clip_paths, duration, visual_loop=(part is None))
    caption_clips = _karaoke_clips(words, cutoff=duration)
    cta_clips = _cta_clips(duration, topic)
    part_clips = [_part_label_clip(part, total_parts)] if part else []
    hook_overlay = hook_text or title  # двойной хук: on-screen текст может отличаться от озвучки
    hook_clips = _hook_clips(hook_overlay) if hook_overlay else []
    final = CompositeVideoClip(
        [background, *caption_clips, *cta_clips, *part_clips, *hook_clips], size=TARGET_SIZE
    ).set_audio(_build_audio(audio, words, duration))
    final.write_videofile(out_path, fps=30, codec="libx264", audio_codec="aac", logger=None)

    # Тумба = самый первый кадр: виден только текст-хук, первое слово субтитров ещё
    # не появилось (стартует ~0.1с). Чище, чем кадр из середины хука, где вылезает субтитр.
    thumb_path = out_path.replace(".mp4", "_thumb.jpg")
    thumb_time = 0.05 if title else min(1.0, duration * 0.1)
    frame = final.get_frame(min(thumb_time, duration - 0.1))
    Image.fromarray(frame).convert("RGB").save(thumb_path, "JPEG")

    # Серия: дорисовываем «PART N/T» поверх тумбы (PIL), чтобы части были узнаваемы в ленте.
    if part:
        _draw_part_badge(thumb_path, part, total_parts)

    return out_path, thumb_path


def _save_thumbnail(img: Image.Image, path: str, title: str | None = None) -> None:
    """Сохраняет thumbnail. Если передан title — рисует текст поверх кадра."""
    if not title:
        img.save(path, "JPEG")
        return

    from PIL import ImageFont
    draw = ImageDraw.Draw(img)
    W, H = img.size

    # Полупрозрачная тёмная полоса в верхней части (видна в Instagram 1:1 кропе)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    ov_draw.rectangle([(0, 0), (W, 420)], fill=(0, 0, 0, 160))
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
    y = 48  # текст сверху — виден в Instagram 1:1 кропе и в полном 9:16

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        lw = bbox[2] - bbox[0]
        x = (W - lw) // 2
        # Тень
        draw.text((x + 4, y + 4), line, font=font, fill=(0, 0, 0, 200))
        draw.text((x, y), line, font=font, fill=(255, 255, 255))
        y += line_h

    img.save(path, "JPEG")
