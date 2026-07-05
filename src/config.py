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
            # Было "DOUBLE TAP if you knew this" — это Instagram-жест, на YouTube (основная
            # площадка) двойного тапа нет. Коммент-CTA работает на обеих платформах и
            # усиливает главный сигнал ранжирования (comment density).
            "COMMENT\nif you knew this",
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
        "loop_probability": 0.5,
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
        # CTA в подписи Instagram Reel (2026-07-02) — раньше подпись была без единого
        # призыва подписаться/перейти в био, хотя ссылка на YouTube лежит именно в био.
        # Пул — random.choice в publish.py, чтобы не выглядело ботом под каждым постом.
        "ig_caption_ctas": [
            "🔗 Follow for daily facts — link in bio",
            "📌 New fact every day — link in bio",
            "🔗 More facts like this — link in bio",
        ],
        # Кросс-промо EN↔ES (2026-07-02): реальная билингвальная аудитория пересекается,
        # ссылка на сестринский канал в описании — почти нулевая цена, потенциальный переток
        # подписчиков. sister_channel_handle — БЕЗ @, sister_desc_cta — фраза на СВОЁМ языке
        # про сестринский канал НА ДРУГОМ языке. Пул для разнообразия (тот же паттерн, что CTA).
        "sister_channel_handle": "DatosEn30s",
        "sister_desc_ctas": [
            "🌎 Also in Spanish:",
            "🌎 We also post in Spanish:",
            "🌎 En español too:",
        ],
        "sister_lang_tags": ["datos curiosos", "hechos curiosos", "sabías que"],
        "sister_lang_code": "es",  # язык локализации метаданных (localize_metadata.py)
        # Воронка Shorts→лонгформ: фразы перед ссылкой на последний длинный ролик
        # (в описании и закреп-комменте). Тема не важна — продаём формат «глубокий разбор».
        "longform_desc_cta": "Full deep-dives on the channel:",
        "longform_comment_cta": "Want the full story? Watch the deep-dive 👉",
        # Первый комментарий от имени канала после каждой публикации. Вопрос-провокация
        # СВЕРХУ — комменты/ответы это топ-сигнал алгоритма (engagement density), generic
        # "follow" так не работает. {channel_url} подставляется автоматически.
        "first_comment": "Wait — did you actually already know this one? 👇\nSubscribe for a new fact every day 👉 {channel_url}",
        # Пул для строки подписки в закреп-комменте (2026-07-05): раньше это была ЕДИНСТВЕННАЯ
        # фиксированная строка, дословно одинаковая на 100% видео канала — классический
        # "bot-like pattern" сигнал спам-детекции YouTube. Тот же паттерн, что first_comment_replies.
        "first_comment_subscribe_ctas": [
            "Subscribe for a new fact every day 👉 {channel_url}",
            "New fact drops daily — subscribe 👉 {channel_url}",
            "Follow along for more like this 👉 {channel_url}",
            "One fact a day, forever — subscribe 👉 {channel_url}",
        ],
        # #3 Само-ответ на закреп-коммент → мини-тред (engagement density). Генерик, без доп.
        # токенов. ПУЛ вариантов (random.choice в publish/pipeline_longform): один и тот же
        # текст под каждым видео выглядел ботово.
        "first_comment_replies": [
            "Be honest — did this actually surprise you, or did you already know? 👀",
            "Most people scroll past without believing it. Did you?",
            "On a scale of 1-10, how fake did this sound at first? 👇",
            "If you already knew this one, you're officially in the top 1% 👇",
        ],
        # Навигация по серии: ссылка на плейлист в закреп-комменте каждой части.
        "series_playlist_cta": "📺 Watch all parts in order 👉",
        # Закреп-коммент лонгформа: провокация + подписка (досмотревший = горячий подписчик).
        "longform_comment": "Which part surprised you the most? 👇\nSubscribe for a new deep-dive every week 👉 {channel_url}",
        # Лонгформ-TTS через novita (MiniMax speech-02-turbo) — качество голоса важнее, чем у
        # 30-сек Shorts. Daily остаётся на edge-tts. Фолбэк на edge-tts, если novita упала.
        "longform_use_novita": True,
        "novita_language": "English",   # language_boost для MiniMax
        "novita_voice": "Wise_Woman",   # voice_id; сменить после прослушивания сэмплов
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
        "loop_probability": 0.5,
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
        # Instagram ES (2026-07-01): @datosen30s, свой Business-аккаунт/токен (см. daily-es.yml).
        "post_to_instagram": True,
        "post_to_tiktok": False,
        "post_to_pinterest": False,
        "channel_handle": "DatosEn30s",
        "sister_channel_handle": "60SecFacts",
        "sister_desc_ctas": [
            "🌎 También en inglés:",
            "🌎 También publicamos en inglés:",
            "🌎 In English too:",
        ],
        "sister_lang_tags": ["facts", "did you know", "fun facts"],
        "sister_lang_code": "en",
        "ig_caption_ctas": [
            "🔗 Sígueme para más datos — link en bio",
            "📌 Un dato nuevo cada día — link en bio",
            "🔗 Más datos como este — link en bio",
        ],
        "longform_desc_cta": "Análisis completos en el canal:",
        "longform_comment_cta": "¿Quieres la historia completa? Mira el análisis 👉",
        "first_comment": "Un momento — ¿tú ya sabías esto? 👇\nSuscríbete para un dato nuevo cada día 👉 {channel_url}",
        "first_comment_subscribe_ctas": [
            "Suscríbete para un dato nuevo cada día 👉 {channel_url}",
            "Dato nuevo cada día — suscríbete 👉 {channel_url}",
            "Sígueme para más datos como este 👉 {channel_url}",
            "Un dato al día, para siempre — suscríbete 👉 {channel_url}",
        ],
        "first_comment_replies": [
            "Sé sincero — ¿esto te sorprendió o ya lo sabías? 👀",
            "La mayoría pasa de largo sin creerlo. ¿Tú lo creíste?",
            "Del 1 al 10, ¿qué tan falso te sonó al principio? 👇",
            "Si ya lo sabías, estás en el 1% — demuéstralo abajo 👇",
        ],
        "series_playlist_cta": "📺 Mira todas las partes en orden 👉",
        "longform_comment": "¿Qué parte te sorprendió más? 👇\nSuscríbete para un análisis nuevo cada semana 👉 {channel_url}",
        "longform_use_novita": True,
        "novita_language": "Spanish",
        "novita_voice": "Wise_Woman",
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
    # Вьетнамский TikTok-профиль. Аккаунт TikTok зарегистрирован во Вьетнаме → раздаётся
    # вьетнамской аудитории, поэтому контент на вьетнамском. Публикация ручная (генерим
    # локально через `CHANNEL=vi python test_local.py`), автопостинг выключен.
    "vi": {
        "channel_name": "Sự Thật 60 Giây",
        "lang_code": "vi",
        "script_language": "Vietnamese (natural, conversational Vietnamese)",
        "voices": [
            "vi-VN-NamMinhNeural",
        ],
        "cta_phrases": [
            "THEO DÕI\nđể xem thêm",
            "THEO DÕI để xem\nnhững sự thật như này",
            "NHẤN ĐÔI\nnếu bạn chưa biết",
        ],
        # Петля на вьетнамском грамматически не складывается так же, как в EN/ES
        # («<слово> <хук>» не читается единым предложением), поэтому петлю отключаем.
        "loop_phrases": {},
        "loop_probability": 0.0,
        "cta_topic_template": "THEO DÕI để xem thêm\nsự thật về {word}",
        "topic_cta_words": {
            "the ocean": "ĐẠI DƯƠNG",
            "the animal kingdom": "ĐỘNG VẬT",
            "space": "VŨ TRỤ",
            "the human body": "CƠ THỂ",
            "ancient history": "LỊCH SỬ",
            "archaeological discoveries": "KHẢO CỔ",
            "ancient civilizations": "CỔ ĐẠI",
            "volcanoes and earthquakes": "NÚI LỬA",
            "extreme weather": "THỜI TIẾT",
            "historical mysteries": "BÍ ẨN",
            "evolution": "TIẾN HÓA",
            "natural wonders": "THIÊN NHIÊN",
            "shipwrecks and lost treasures": "KHO BÁU",
        },
        "cta_instruction": (
            "ONE short CTA in Vietnamese, 4-7 words MAX — either \"Theo dõi để xem thêm.\" or "
            "\"Bình luận nếu bạn đã biết.\" Pick one, no embellishment, no extra clauses"
        ),
        "post_to_instagram": False,
        "post_to_tiktok": False,
        "post_to_pinterest": False,
        # VN TikTok-формат: random-facts (3-4 коротких факта) поверх залипательного фона,
        # без EN-хук-плашки. test_local.py при этом флаге берёт generate_rapid_facts +
        # fetch_satisfying_clips вместо обычной generate_script/тематических клипов.
        "satisfying_mode": True,
        "channel_handle": "",
        "first_comment": "",
        "playlist_titles": {},
    },
}

CFG = CONFIGS[CHANNEL]
