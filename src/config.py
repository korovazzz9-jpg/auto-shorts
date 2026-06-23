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
        # Подпись призыва (вариативность) — на языке канала.
        "cta_phrases": [
            "LIKE & FOLLOW\nfor more",
            "FOLLOW for more\nfacts like this",
            "DOUBLE TAP\nif you knew this",
        ],
        # Инструкция по CTA внутри сценария.
        "cta_instruction": (
            "comment whether they knew this, or follow for more"
        ),
        # Используется ли кросс-постинг в Instagram для этого канала.
        "post_to_instagram": True,
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
        },
    },
    "es": {
        "channel_name": "Datos en 60s",
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
        "cta_instruction": (
            "ask viewers to comment if they knew this, or to follow for more (in Spanish)"
        ),
        # Испанский канал — отдельный Instagram появится позже; пока только YouTube.
        "post_to_instagram": False,
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
        },
    },
}

CFG = CONFIGS[CHANNEL]
