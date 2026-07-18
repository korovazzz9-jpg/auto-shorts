"""Генерирует карточку с фактом и публикует её как пин на Pinterest через API v5."""
import base64
import os
import textwrap
import tempfile

import requests
from PIL import Image, ImageDraw, ImageFont

PINTEREST_API = "https://api.pinterest.com/v5"

# Размер карточки — оптимум для Pinterest (соотношение 2:3)
CARD_W, CARD_H = 1000, 1500


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


def build_pin_card(title: str, fact: str, channel_handle: str) -> str:
    """Рисует карточку и сохраняет во временный файл. Возвращает путь."""
    img = Image.new("RGB", (CARD_W, CARD_H), (15, 15, 20))
    draw = ImageDraw.Draw(img)

    # Градиентный оверлей сверху и снизу
    for y in range(300):
        alpha = int(180 * (1 - y / 300))
        draw.line([(0, y), (CARD_W, y)], fill=(10, 10, 30, alpha))
    for y in range(300):
        alpha = int(160 * (y / 300))
        draw.line([(0, CARD_H - 300 + y), (CARD_W, CARD_H - 300 + y)], fill=(10, 10, 30, alpha))

    # Декоративная линия-акцент сверху
    draw.rectangle([60, 90, 200, 97], fill=(255, 60, 60))

    # Заголовок (title) — небольшой, над фактом
    title_font = _get_font(42)
    title_upper = title.upper()
    title_lines = textwrap.wrap(title_upper, width=28)
    y = 130
    for line in title_lines:
        bbox = draw.textbbox((0, 0), line, font=title_font)
        draw.text((60, y), line, font=title_font, fill=(200, 200, 200))
        y += (bbox[3] - bbox[1]) + 10

    # Основной текст факта — крупно по центру
    fact_font = _get_font(68)
    fact_lines = textwrap.wrap(fact, width=22)
    total_h = sum(
        draw.textbbox((0, 0), l, font=fact_font)[3] - draw.textbbox((0, 0), l, font=fact_font)[1] + 18
        for l in fact_lines
    )
    y = (CARD_H - total_h) // 2 - 40
    for line in fact_lines:
        bbox = draw.textbbox((0, 0), line, font=fact_font)
        lw = bbox[2] - bbox[0]
        lh = bbox[3] - bbox[1]
        # тень
        draw.text(((CARD_W - lw) // 2 + 3, y + 3), line, font=fact_font, fill=(0, 0, 0, 180))
        draw.text(((CARD_W - lw) // 2, y), line, font=fact_font, fill=(255, 255, 255))
        y += lh + 18

    # Брендинг внизу
    brand_font = _get_font(38)
    brand_text = channel_handle if channel_handle.startswith("@") else f"@{channel_handle}"
    bbox = draw.textbbox((0, 0), brand_text, font=brand_font)
    bw = bbox[2] - bbox[0]
    draw.text(((CARD_W - bw) // 2, CARD_H - 100), brand_text, font=brand_font, fill=(255, 60, 60))

    # YouTube иконка-плашка
    yt_font = _get_font(30)
    yt_text = "YouTube"  # был "▶ YouTube" — глиф ▶ отсутствует в шрифте, рисовался квадратом
    bbox = draw.textbbox((0, 0), yt_text, font=yt_font)
    yw = bbox[2] - bbox[0]
    draw.text(((CARD_W - yw) // 2, CARD_H - 55), yt_text, font=yt_font, fill=(160, 160, 160))

    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "pin_card.jpg")
    img.save(path, "JPEG", quality=95)
    return path


def publish_pin(title: str, description: str, image_path: str, video_url: str) -> str:
    """Публикует пин. Возвращает pin_id.

    2026-07-18: был 500 на КАЖДОЙ публикации (ни одного пина с включения 07-17) —
    эндпоинт /v5/media у Pinterest только для ВИДЕО; для картинок media_id не
    поддерживается, картинка передаётся прямо в POST /pins как image_base64."""
    token = os.environ["PINTEREST_ACCESS_TOKEN"]
    board_id = os.environ["PINTEREST_BOARD_ID"]

    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("ascii")

    body = {
        "board_id": board_id,
        "title": title[:100],
        "description": description[:500],
        "link": video_url,
        "media_source": {
            "source_type": "image_base64",
            "content_type": "image/jpeg",
            "data": image_b64,
        },
    }

    resp = requests.post(
        f"{PINTEREST_API}/pins",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    pin_id = resp.json()["id"]
    print(f"  Pinterest: опубликован пин {pin_id}")
    return pin_id


def upload_pin(title: str, script: str, channel_handle: str, video_id: str) -> str:
    """Точка входа: генерирует карточку и публикует пин."""
    # Первые 2 предложения скрипта как текст карточки. Сплит по границам предложений
    # С ПРОБЕЛОМ после знака — иначе «4.5mm» резался на «4. 5mm» (тот же баг был в publish).
    import re
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", script) if s.strip()]
    fact_text = " ".join(sentences[:2])

    card_path = build_pin_card(title, fact_text, channel_handle)
    video_url = f"https://www.youtube.com/shorts/{video_id}"
    description = f"{fact_text}\n\n▶ Watch the full short: {video_url}"

    return publish_pin(title, description, card_path, video_url)
