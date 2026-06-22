"""Генерирует тему и короткий сценарий факта через Claude API."""
import json
import os
import random

from anthropic import Anthropic

TOPICS_POOL = [
    "космос", "океан", "история древнего мира", "человеческое тело",
    "животный мир", "психология", "технологии будущего", "необычные рекорды",
    "вулканы и землетрясения", "древние цивилизации", "квантовая физика",
    "криптография", "эволюция", "погодные явления", "археологические находки",
]

SYSTEM_PROMPT = """Ты сценарист коротких видео-фактов для YouTube Shorts.
Пиши на русском, разговорно, цепляюще, без воды. Длительность озвучки — 35-45 секунд
(примерно 90-120 слов). Структура: яркий крючок в первой фразе, сам факт, неожиданный
поворот или вывод в конце. Никаких вступлений вида "сегодня я расскажу"."""


def generate_script() -> dict:
    topic = random.choice(TOPICS_POOL)
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": (
                f"Тема: {topic}. Придумай один конкретный малоизвестный факт по этой теме "
                "и напиши по нему сценарий. Ответь строго в формате JSON без markdown-обёртки: "
                '{"title": "короткий цепляющий заголовок до 60 символов", '
                '"script": "текст сценария для озвучки", '
                '"tags": ["тег1", "тег2", ...]}'
            ),
        }],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
    data = json.loads(raw)
    data["topic"] = topic
    return data


if __name__ == "__main__":
    print(json.dumps(generate_script(), ensure_ascii=False, indent=2))
