"""IG-карточка факта (2026-07-05): статичный пост в Instagram-ленту, раз в день, отдельно
от Reels-кросспостинга (см. CFG["ig_card_slot_hour"] в publish.py).

Дизайн выбран пользователем из 2 вариантов — фиолетово-чёрный градиент с золотым акцентом
(перекликается с жёлтой лампочкой в логотипе 60SecFacts), настоящий YouTube-бейдж (красная
плашка + белый треугольник play) вместо юникод-символа. НЕ используется для Pinterest —
у того свой генератор с историческим тёмно-синим стилем (upload_pinterest.build_pin_card),
трогать его не стали, чтобы не сломать уже проверенный формат.
"""
import os
import tempfile
import textwrap

from PIL import Image, ImageDraw, ImageFont

CARD_W, CARD_H = 1000, 1500
BG_TOP = (35, 24, 46)      # тёмно-фиолетовый
BG_BOTTOM = (14, 10, 20)   # почти чёрный
ACCENT_GOLD = (255, 196, 60)


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


def _draw_youtube_badge(draw: ImageDraw.ImageDraw, x: int, y: int, w: int = 100, h: int = 70) -> None:
    """Настоящий YouTube-бейдж (красная скруглённая плашка + белый play), не юникод-символ."""
    draw.rounded_rectangle([x, y, x + w, y + h], radius=18, fill=(255, 0, 0))
    cx, cy = x + w / 2, y + h / 2
    s = h * 0.28
    draw.polygon([(cx - s * 0.6, cy - s), (cx - s * 0.6, cy + s), (cx + s * 1.1, cy)], fill="white")


def build_ig_card(title: str, fact: str, channel_handle: str) -> str:
    """Рисует IG-карточку факта и сохраняет во временный файл. Возвращает путь."""
    img = Image.new("RGB", (CARD_W, CARD_H), BG_TOP)
    draw = ImageDraw.Draw(img)

    for y in range(CARD_H):
        t = y / CARD_H
        r = int(BG_TOP[0] * (1 - t) + BG_BOTTOM[0] * t)
        g = int(BG_TOP[1] * (1 - t) + BG_BOTTOM[1] * t)
        b = int(BG_TOP[2] * (1 - t) + BG_BOTTOM[2] * t)
        draw.line([(0, y), (CARD_W, y)], fill=(r, g, b))

    draw.rectangle([60, 90, 220, 98], fill=ACCENT_GOLD)

    title_font = _get_font(40)
    title_lines = textwrap.wrap(title.upper(), width=30)
    y = 130
    for line in title_lines:
        bbox = draw.textbbox((0, 0), line, font=title_font)
        draw.text((60, y), line, font=title_font, fill=(220, 220, 230))
        y += (bbox[3] - bbox[1]) + 12

    fact_font = _get_font(66)
    fact_lines = textwrap.wrap(fact, width=23)
    total_h = sum(
        draw.textbbox((0, 0), l, font=fact_font)[3] - draw.textbbox((0, 0), l, font=fact_font)[1] + 20
        for l in fact_lines
    )
    y = (CARD_H - total_h) // 2 - 30
    for line in fact_lines:
        bbox = draw.textbbox((0, 0), line, font=fact_font)
        lw = bbox[2] - bbox[0]
        draw.text(((CARD_W - lw) // 2 + 3, y + 3), line, font=fact_font, fill=(0, 0, 0, 160))
        draw.text(((CARD_W - lw) // 2, y), line, font=fact_font, fill="white")
        y += (bbox[3] - bbox[1]) + 20

    brand_font = _get_font(36)
    brand_text = f"@{channel_handle}"
    bbox = draw.textbbox((0, 0), brand_text, font=brand_font)
    bw = bbox[2] - bbox[0]
    badge_w, gap = 100, 24
    start_x = (CARD_W - (bw + gap + badge_w)) // 2
    by = CARD_H - 110
    draw.text((start_x, by), brand_text, font=brand_font, fill=ACCENT_GOLD)
    _draw_youtube_badge(draw, start_x + bw + gap, by - 18, w=badge_w, h=70)

    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "ig_card.jpg")
    img.save(path, "JPEG", quality=95)
    return path
