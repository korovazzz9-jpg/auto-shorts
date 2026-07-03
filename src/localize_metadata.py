"""Локализация метаданных EN↔ES (2026-07-03): к видео прикрепляется перевод заголовка и
описания на язык сестринского канала (snippet.localizations). Испаноязычный зритель видит
EN-ролик с испанским заголовком прямо в своём интерфейсе YouTube (и наоборот) — видео
становится находимым на втором языке само по себе, глубже, чем кросс-промо-ссылка.

Перевод — Claude Haiku (копейки, тот же паттерн, что vi/tl-перевод в upload_captions.py).
Требование API: у видео должен быть snippet.defaultLanguage — ставится при загрузке
(upload_youtube.upload_video(default_language=...)), поэтому работает только для видео,
залитых после 2026-07-03. Квота: videos.update = 50 ед (общий пул, не критично).

Не для vi-канала: у него нет sister_lang_code в конфиге — publish.py просто пропускает шаг.
"""
import json
import os

from anthropic import Anthropic

from config import CFG
from youtube_auth import get_client

_LANG_NAMES = {"en": "English", "es": "Spanish (neutral Latin American)"}


def _translate(title: str, description: str, target_lang: str) -> tuple[str, str]:
    """Перевод заголовка+описания через Haiku. URL/хэндлы/хэштеги/эмодзи не переводятся."""
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    prompt = (
        f"Translate this YouTube video title and description into {_LANG_NAMES.get(target_lang, target_lang)}. "
        "Keep ALL URLs, @handles, hashtags, and emoji exactly as they are (do not translate or remove them). "
        "Preserve line breaks. The title must stay under 95 characters. "
        "Respond strictly in JSON, no markdown wrapper: "
        '{"title": "translated title", "description": "translated description"}\n\n'
        f"TITLE: {title}\n\nDESCRIPTION:\n{description}"
    )
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    start, end = raw.find("{"), raw.rfind("}")
    data = json.loads(raw[start:end + 1])
    return str(data["title"])[:100], str(data["description"])


def add_sister_localization(video_id: str, title: str, description: str) -> None:
    """Прикрепляет к видео локализацию на язык сестринского канала. Бросает исключение
    при сбое — вызывающий код (publish.py / pipeline_longform.py) ловит через alert:
    частичный сбой, видео уже опубликовано."""
    target_lang = CFG.get("sister_lang_code", "")
    if not target_lang:
        return  # канал без сестринской пары (vi) — шаг не применим

    loc_title, loc_description = _translate(title, description, target_lang)
    get_client().videos().update(
        part="localizations",
        body={
            "id": video_id,
            "localizations": {
                target_lang: {"title": loc_title, "description": loc_description},
            },
        },
    ).execute()
    print(f"  Локализация ({target_lang}) прикреплена: {loc_title[:60]}")
