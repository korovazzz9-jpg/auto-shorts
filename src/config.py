"""Конфигурация канала. Выбирается переменной окружения CHANNEL (по умолчанию 'en').
Английский канал работает ровно как раньше; испанский — параллельный конфиг.
Учётные данные (YT-токен и т.д.) читаются из стандартных env-имён — за их маршрутизацию
под нужный канал отвечает workflow (разные секреты -> одни и те же env-имена)."""
import os

CHANNEL = os.environ.get("CHANNEL", "en")

CONFIGS = {
    "en": {
        "channel_name": "60SecFacts",
        "lang_code": "en",
        # Язык, на котором Claude пишет сценарий.
        "script_language": "English",
        # Голоса TTS, ротируются между видео ради вариативности.
        "voices": [
            "en-US-GuyNeural",
            "en-US-EricNeural",
            "en-US-ChristopherNeural",
            "en-GB-RyanNeural",
            "en-AU-WilliamNeural",
        ],
        # Подпись призыва (вариативность) — на языке канала. Генерик-fallback,
        # когда тема не маппится (см. topic_cta_words ниже).
        "cta_phrases": [
            "LIKE & FOLLOW\nfor more",
            "FOLLOW for more\nfacts like this",
            "DOUBLE TAP\nif you knew this",
        ],
        # Фразы-петли (loop): дописываются в конец скрипта детерминированно. Ключ = коннектор,
        # который Claude пометил как подходящий по смыслу к хуку. На стыке петли
        # "<фраза> <хук>" читается как одно связное предложение ("This is why <хук>").
        "loop_phrases": {
            "why": ["This is why.", "And that's exactly why.", "And that's why.", "Which is why."],
            "how": ["And that's how.", "And that's exactly how.", "And this is how."],
            "when": ["And that's exactly when.", "And it all started when."],
            "where": ["And that's exactly where.", "And it all happened where."],
            "because": ["And it's all because.", "And that's because."],
        },
        # Доля видео с петлёй (остальные — обычная концовка). Не 100%, чтобы приём не стал
        # формулой и чтобы было с чем сравнить в analytics_retention.py (тег loop-yes/loop-no).
        "loop_probability": 0.65,
        # Topic-aware CTA: персональный призыв под тему видео конвертит лучше генерика.
        "cta_topic_template": "FOLLOW for more\n{word} facts",
        "topic_cta_words": {
            "the ocean": "OCEAN",
            "the animal kingdom": "ANIMAL",
            "space": "SPACE",
            "the human body": "BODY",
            "ancient history": "HISTORY",
            "archaeological discoveries": "ARCHAEOLOGY",
            "ancient civilizations": "ANCIENT",
            "volcanoes and earthquakes": "VOLCANO",
            "extreme weather": "WEATHER",
            "historical mysteries": "MYSTERY",
            "evolution": "EVOLUTION",
            "natural wonders": "NATURE",
            "shipwrecks and lost treasures": "SHIPWRECK",
        },
        # Инструкция по CTA внутри сценария. Держим КОРОТКОЙ — иначе раздувает длину видео.
        "cta_instruction": (
            "ONE short CTA, 4-7 words MAX — either \"Follow for more.\" or "
            "\"Comment if you knew this.\" Pick one, no embellishment, no extra clauses"
        ),
        # Используется ли кросс-постинг в Instagram для этого канала.
        "post_to_instagram": True,
        "post_to_tiktok": False,  # ожидает одобрения TikTok Dev App + токена — вернуть True после
        "post_to_pinterest": False,  # ожидает одобрения Pinterest Dev App — вернуть True после
        # Хэндл канала без @, нужен для ссылки в первом комментарии.
        "channel_handle": "60SecFacts",
        # Первый комментарий от имени канала после каждой публикации.
        # {channel_url} — подставляется автоматически.
        "first_comment": "More videos on this topic 👉 {playlist_url}\nFollow for daily facts 👉 {channel_url}",
        "playlist_titles": {
            "space": "Space Facts",
            "the ocean": "Ocean Facts",
            "ancient history": "Ancient History Facts",
            "the human body": "Human Body Facts",
            "the animal kingdom": "Animal Facts",
            "psychology": "Psychology Facts",
            "future technology": "Technology Facts",
            "bizarre records": "Bizarre Records",
            "volcanoes and earthquakes": "Volcano & Earthquake Facts",
            "ancient civilizations": "Ancient Civilizations",
            "cryptography": "Cryptography Facts",
            "evolution": "Evolution Facts",
            "extreme weather": "Extreme Weather Facts",
            "archaeological discoveries": "Archaeology Facts",
            "shipwrecks and lost treasures": "Shipwrecks & Lost Treasures",
            "historical mysteries": "Historical Mysteries",
            "natural wonders": "Natural Wonders",
        },
    },
    "es": {
        "channel_name": "Datos en 30s",
        "lang_code": "es",
        "script_language": "Spanish (neutral Latin American / Mexican Spanish, NOT European Spanish)",
        "voices": [
            "es-MX-JorgeNeural",
            "es-MX-DaliaNeural",
            "es-US-AlonsoNeural",
            "es-CO-GonzaloNeural",
        ],
        "cta_phrases": [
            "DALE LIKE Y SÍGUEME\npara más",
            "SÍGUEME para más\ndatos como este",
            "DALE LIKE\nsi no lo sabías",
        ],
        "loop_phrases": {
            "why": ["Y por eso.", "Y por eso exactamente.", "Y por eso pasa.", "Por eso mismo."],
            "how": ["Y así es como.", "Y exactamente así.", "Y de esta forma."],
            "when": ["Y justo cuando.", "Y todo empezó cuando."],
            "where": ["Y justo ahí donde.", "Y todo pasó donde."],
            "because": ["Y todo porque.", "Y es porque."],
        },
        "loop_probability": 0.65,
        "cta_topic_template": "SÍGUEME para más\ndatos de {word}",
        "topic_cta_words": {
            "the ocean": "OCÉANO",
            "the animal kingdom": "ANIMALES",
            "space": "ESPACIO",
            "the human body": "CUERPO",
            "ancient history": "HISTORIA",
            "archaeological discoveries": "ARQUEOLOGÍA",
            "ancient civilizations": "CIVILIZACIONES",
            "volcanoes and earthquakes": "VOLCANES",
            "extreme weather": "CLIMA",
            "historical mysteries": "MISTERIOS",
            "evolution": "EVOLUCIÓN",
            "natural wonders": "NATURALEZA",
            "shipwrecks and lost treasures": "NAUFRAGIOS",
        },
        "cta_instruction": (
            "ONE short CTA in Spanish, 4-7 words MAX — either \"Sígueme para más.\" or "
            "\"Comenta si lo sabías.\" Pick one, no embellishment, no extra clauses"
        ),
        # Испанский канал — отдельный Instagram появится позже; пока только YouTube.
        "post_to_instagram": False,
        "post_to_tiktok": False,
        "post_to_pinterest": False,
        "channel_handle": "DatosEn30s",
        "first_comment": "Más videos sobre este tema 👉 {playlist_url}\nSíguenos para más datos 👉 {channel_url}",
        "playlist_titles": {
            "space": "Datos del Espacio",
            "the ocean": "Datos del Océano",
            "ancient history": "Datos de Historia Antigua",
            "the human body": "Datos del Cuerpo Humano",
            "the animal kingdom": "Datos de Animales",
            "psychology": "Datos de Psicología",
            "future technology": "Datos de Tecnología",
            "bizarre records": "Récords Increíbles",
            "volcanoes and earthquakes": "Volcanes y Terremotos",
            "ancient civilizations": "Civilizaciones Antiguas",
            "cryptography": "Datos de Criptografía",
            "evolution": "Datos de Evolución",
            "extreme weather": "Clima Extremo",
            "archaeological discoveries": "Descubrimientos Arqueológicos",
            "shipwrecks and lost treasures": "Naufragios y Tesoros Perdidos",
            "historical mysteries": "Misterios Históricos",
            "natural wonders": "Maravillas Naturales",
        },
    },
}

CFG = CONFIGS[CHANNEL]
