"""IG-карточка факта (2026-07-05): статичный пост в Instagram-ленту, раз в день, отдельно
от Reels-кросспостинга (см. CFG["ig_card_slot_hour"] в publish.py).

Финальный дизайн (после нескольких итераций с пользователем): аватарка канала в золотом/
акцентном кольце сверху + номер факта + заголовок + разделитель-ромб, факт по центру с
кавычками-рамкой (резервируют своё место — не наезжают на текст ни при какой длине),
золотое свечение вокруг факта (размер от реальной высоты блока), декоративные точки ТОЛЬКО
в реально пустых зонах (плотность зависит от их размера — короткий факт не оставляет голых
пустот), зеркальный разделитель + бренд + настоящий YouTube-бейдж внизу.

Цвет и аватарка — под логотип канала (палитра выбрана пользователем по факту):
EN — фиолетово-чёрный + золото (жёлтая лампочка в лого 60SecFacts).
ES — тёмно-бирюзовый + оранжевый (teal/orange лого Datos en 30s).

НЕ используется для Pinterest — у того свой генератор (upload_pinterest.build_pin_card),
трогать его не стали, чтобы не сломать уже проверенный формат.
"""
import json
import math
import os
import random
import tempfile
import textwrap

from PIL import Image, ImageDraw, ImageFont, ImageFilter

CARD_W, CARD_H = 1000, 1500

_AVATAR_DIR = os.path.join(os.path.dirname(__file__), "..", "manual_thumbs")

# Палитра + аватарка на канал. accent — акцентный цвет (обводка, кавычки, номер, бренд-текст,
# точки, свечение); bg_top/bg_bottom — вертикальный градиент фона.
_THEMES = {
    "en": {
        "bg_top": (35, 24, 46), "bg_bottom": (14, 10, 20),
        "accent": (255, 196, 60),
        "avatar": os.path.join(_AVATAR_DIR, "yt_avatar_en.png"),
    },
    "es": {
        "bg_top": (10, 46, 44), "bg_bottom": (6, 18, 17),
        "accent": (251, 146, 60),
        "avatar": os.path.join(_AVATAR_DIR, "yt_avatar_es.png"),
    },
}

_COUNTER_DIR = os.path.dirname(__file__)


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in [
        r"C:\Windows\Fonts\arialbd.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]:
        if os.path.exists(candidate):
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _counter_path(channel: str) -> str:
    return os.path.join(_COUNTER_DIR, "..", f"ig_card_counter_{channel}.json")


def next_fact_number(channel: str) -> int:
    """Следующий номер факта (нумерация с 1 — карточки НОВЫЙ формат, не продолжение Shorts).
    НЕ записывает файл — только читает: сохранение через save_fact_number ПОСЛЕ успешной
    публикации, иначе сбой аплоада оставлял бы дыру в нумерации."""
    try:
        with open(_counter_path(channel), encoding="utf-8") as f:
            return json.load(f).get("last", 0) + 1
    except (FileNotFoundError, json.JSONDecodeError, AttributeError):
        return 1


def save_fact_number(channel: str, n: int) -> None:
    """Фиксирует номер после успешной публикации карточки. Файл коммитится persist-шагом
    daily.yml/daily-es.yml/watchdog.yml."""
    with open(_counter_path(channel), "w", encoding="utf-8") as f:
        json.dump({"last": n}, f)


def _draw_youtube_badge(draw: ImageDraw.ImageDraw, x: float, y: float, w: int = 90, h: int = 64) -> None:
    draw.rounded_rectangle([x, y, x + w, y + h], radius=18, fill=(255, 0, 0))
    cx, cy = x + w / 2, y + h / 2
    s = h * 0.28
    draw.polygon([(cx - s * 0.6, cy - s), (cx - s * 0.6, cy + s), (cx + s * 1.1, cy)], fill="white")


def _gradient(size: tuple[int, int], top: tuple, bottom: tuple) -> Image.Image:
    img = Image.new("RGB", size, top)
    draw = ImageDraw.Draw(img)
    for y in range(size[1]):
        t = y / size[1]
        r = int(top[0] * (1 - t) + bottom[0] * t)
        g = int(top[1] * (1 - t) + bottom[1] * t)
        b = int(top[2] * (1 - t) + bottom[2] * t)
        draw.line([(0, y), (size[0], y)], fill=(r, g, b))
    return img


def _circular_avatar(path: str, diameter: int) -> Image.Image:
    av = Image.open(path).convert("RGBA").resize((diameter, diameter), Image.LANCZOS)
    mask = Image.new("L", (diameter, diameter), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, diameter, diameter], fill=255)
    av.putalpha(mask)
    return av


def _wrap_to_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    """Перенос по РЕАЛЬНОЙ ширине в пикселях — не по числу символов (то обрезало текст)."""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textbbox((0, 0), test, font=font)[2] <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _block_height(draw: ImageDraw.ImageDraw, lines: list[str], font: ImageFont.FreeTypeFont, line_gap: int = 20) -> int:
    return sum(draw.textbbox((0, 0), l, font=font)[3] - draw.textbbox((0, 0), l, font=font)[1] + line_gap for l in lines)


def _fit_fact(draw, fact: str, max_w: int, max_h: int, start_size: int = 76, min_size: int = 40):
    """Максимальный размер шрифта факта, вмещающийся по ширине И высоте — короткий факт
    получает крупный шрифт (сам заполняет пространство), длинный влезает мельче."""
    size = start_size
    while size >= min_size:
        font = _get_font(size)
        lines = _wrap_to_width(draw, fact, font, max_w)
        if _block_height(draw, lines, font) <= max_h:
            return font, lines
        size -= 4
    font = _get_font(min_size)
    return font, _wrap_to_width(draw, fact, font, max_w)


def _divider(draw: ImageDraw.ImageDraw, y: float, cx: int, color: tuple) -> None:
    draw.line([(cx - CARD_W * 0.19, y), (cx - CARD_W * 0.06, y)], fill=color, width=2)
    draw.line([(cx + CARD_W * 0.06, y), (cx + CARD_W * 0.19, y)], fill=color, width=2)
    d = 10
    draw.polygon([(cx, y - d), (cx + d, y), (cx, y + d), (cx - d, y)], fill=color)


def _scattered_dots(img: Image.Image, zones: list[tuple[float, float]], color: tuple, seed: int) -> Image.Image:
    """Декор ТОЛЬКО в реально пустых зонах — плотность от их размера, не фиксирована."""
    random.seed(seed)
    dot_layer = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dot_layer)
    for y0, y1 in zones:
        zone_h = max(0, y1 - y0)
        count = int(zone_h / 22)
        for _ in range(count):
            px = random.choice([random.randint(55, 150), random.randint(CARD_W - 150, CARD_W - 55)])
            py = random.randint(int(y0), max(int(y0) + 1, int(y1)))
            r = random.choice([2, 2, 3, 4])
            alpha = random.randint(35, 100)
            dd.ellipse([px - r, py - r, px + r, py + r], fill=(*color, alpha))
    return Image.alpha_composite(img, dot_layer)


def build_ig_card(title: str, fact: str, channel_handle: str, channel: str, fact_no: int) -> str:
    """Рисует IG-карточку факта и сохраняет во временный файл. Возвращает путь.
    channel — "en"/"es" (выбирает палитру+аватарку), fact_no — порядковый номер
    (см. next_fact_number)."""
    theme = _THEMES.get(channel, _THEMES["en"])
    accent = theme["accent"]

    img = _gradient((CARD_W, CARD_H), theme["bg_top"], theme["bg_bottom"]).convert("RGBA")
    draw = ImageDraw.Draw(img)
    margin = 28
    draw.rounded_rectangle([margin, margin, CARD_W - margin, CARD_H - margin],
                            radius=36, outline=accent, width=4)

    # Аватарка в кольце + пунктирная орбита вокруг
    circle_r = 65
    cx, cy = CARD_W // 2, margin + 95
    orbit_r = circle_r + 22
    for angle in range(0, 360, 12):
        rad = math.radians(angle)
        x0, y0 = cx + orbit_r * math.cos(rad), cy + orbit_r * math.sin(rad)
        draw.ellipse([x0 - 2, y0 - 2, x0 + 2, y0 + 2], fill=(*accent, 140))
    ring_r = circle_r + 6
    draw.ellipse([cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r], fill=accent)
    if os.path.exists(theme["avatar"]):
        avatar = _circular_avatar(theme["avatar"], circle_r * 2)
        img.paste(avatar, (cx - circle_r, cy - circle_r), avatar)
    draw = ImageDraw.Draw(img)

    no_font = _get_font(28)
    no_text = f"FACT #{fact_no}"
    bbox = draw.textbbox((0, 0), no_text, font=no_font)
    draw.text(((CARD_W - (bbox[2] - bbox[0])) // 2, cy + circle_r + 30), no_text, font=no_font, fill=accent)

    title_font = _get_font(38)
    title_lines = textwrap.wrap(title.upper(), width=28)
    y = cy + circle_r + 85
    for line in title_lines:
        bbox = draw.textbbox((0, 0), line, font=title_font)
        draw.text(((CARD_W - (bbox[2] - bbox[0])) // 2, y), line, font=title_font, fill=(220, 220, 230))
        y += (bbox[3] - bbox[1]) + 12

    y += 30
    _divider(draw, y + 20, CARD_W // 2, accent)
    header_bottom = y + 60

    brand_top = CARD_H - 190
    max_w = CARD_W - 160
    QUOTE_RESERVE = 100
    quote_font = _get_font(90)
    available_h = brand_top - header_bottom - 2 * QUOTE_RESERVE
    fact_font, fact_lines = _fit_fact(draw, fact, max_w, available_h)
    fact_h = _block_height(draw, fact_lines, fact_font)
    fact_y = header_bottom + QUOTE_RESERVE + (available_h - fact_h) // 2

    glow = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    pad = max(60, int(fact_h * 0.4))
    gd.ellipse([CARD_W * 0.05, fact_y - pad, CARD_W * 0.95, fact_y + fact_h + pad], fill=(*accent, 55))
    glow = glow.filter(ImageFilter.GaussianBlur(60))
    img = Image.alpha_composite(img, glow)

    img = _scattered_dots(img, [
        (header_bottom + 10, fact_y - QUOTE_RESERVE + 20),
        (fact_y + fact_h + QUOTE_RESERVE - 20, brand_top - 20),
    ], accent, seed=fact_no)
    draw = ImageDraw.Draw(img)

    draw.text((CARD_W // 2 - 260, fact_y - QUOTE_RESERVE), '"', font=quote_font, fill=accent)

    yy = fact_y
    for line in fact_lines:
        bbox = draw.textbbox((0, 0), line, font=fact_font)
        lw = bbox[2] - bbox[0]
        draw.text(((CARD_W - lw) // 2 + 3, yy + 3), line, font=fact_font, fill=(0, 0, 0, 160))
        draw.text(((CARD_W - lw) // 2, yy), line, font=fact_font, fill="white")
        yy += (bbox[3] - bbox[1]) + 20

    draw.text((CARD_W // 2 + 200, fact_y + fact_h + 15), '"', font=quote_font, fill=accent)

    _divider(draw, CARD_H - 160, CARD_W // 2, accent)

    brand_font = _get_font(34)
    brand_text = f"@{channel_handle}"
    bbox = draw.textbbox((0, 0), brand_text, font=brand_font)
    bw = bbox[2] - bbox[0]
    badge_w, gap = 90, 20
    start_x = (CARD_W - (bw + gap + badge_w)) // 2
    by = CARD_H - 130
    draw.text((start_x, by), brand_text, font=brand_font, fill=accent)
    _draw_youtube_badge(draw, start_x + bw + gap, by - 16, w=badge_w, h=64)

    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "ig_card.jpg")
    img.convert("RGB").save(path, "JPEG", quality=95)
    return path
