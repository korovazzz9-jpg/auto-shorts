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
        # Слоты публикации (UTC, час:мин) — должны совпадать с cron-job.org / daily.yml.
        # Читает check_recent_upload.py (watchdog: было ли видео в окне после слота).
        "daily_slots_utc": [(16, 13), (20, 7), (23, 7), (0, 7)],
        # Язык, на котором Claude пишет сценарий.
        "script_language": "English",
        # Голоса TTS, ротируются между видео ради вариативности.
        # 2026-07-08: британский (en-GB-RyanNeural) убран по просьбе пользователя.
        "voices": [
            "en-US-GuyNeural",
            "en-US-EricNeural",
            "en-US-ChristopherNeural",
            "en-AU-WilliamNeural",
        ],
        # Подпись призыва (вариативность) — на языке канала. Генерик-fallback,
        # когда тема не маппится (см. topic_cta_words ниже).
        # 2026-07-10: "FOLLOW" -> "SUBSCRIBE" — на YouTube нет действия Follow, только Subscribe
        # (кнопка под видео буквально так называется); FOLLOW — терминология IG/TikTok,
        # рассинхрон с реальной кнопкой мог резать конверсию просмотр->подписка.
        "cta_phrases": [
            "LIKE & SUBSCRIBE\nfor more",
            "SUBSCRIBE for more\nfacts like this",
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
        "cta_topic_template": "SUBSCRIBE for more\n{word} facts",
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
            "future technology": "TECHNOLOGY",
        },
        # Инструкция по CTA внутри сценария. Держим КОРОТКОЙ — иначе раздувает длину видео.
        "cta_instruction": (
            "ONE short CTA, 4-7 words MAX — either \"Subscribe for more.\" or "
            "\"Comment if you knew this.\" Pick one, no embellishment, no extra clauses"
        ),
        # Используется ли кросс-постинг в Instagram для этого канала.
        "post_to_instagram": True,
        "post_to_tiktok": False,  # ожидает одобрения TikTok Dev App + токена — вернуть True после
        "post_to_pinterest": False,  # ожидает одобрения Pinterest Dev App — вернуть True после
        "post_to_threads": False,  # ожидает Threads-токен (THREADS_ACCESS_TOKEN/USER_ID, см. upload_threads.py)
        # Хэндл канала без @ — реальный @handle из ссылки (проверено через channels.list().
        # customUrl), НЕ название канала: они разошлись при регистрации (60SecFacts — имя,
        # @60factspersecond — хендл). До 2026-07-05 тут стояло имя канала — ссылки в комментах/
        # описаниях/кросс-промо/IG-карточках месяц вели на потенциально чужой/несуществующий
        # хендл. Один параметр — правит все места сразу (все строят URL из CFG["channel_handle"]).
        "channel_handle": "60factspersecond",
        # CTA в подписи Instagram Reel (2026-07-02) — раньше подпись была без единого
        # призыва подписаться/перейти в био, хотя ссылка на YouTube лежит именно в био.
        # Пул — random.choice в publish.py, чтобы не выглядело ботом под каждым постом.
        "ig_caption_ctas": [
            "🔗 Follow for daily facts — link in bio",
            "📌 New fact every day — link in bio",
            "🔗 More facts like this — link in bio",
        ],
        # IG-карточка факта (2026-07-05): в первый слот дня (час UTC) в ленту постится ещё и
        # статичная карточка (build_pin_card) — 1/день, другой формат в той же ленте.
        "ig_card_slot_hour": 16,
        # Кросс-промо EN↔ES (2026-07-02): реальная билингвальная аудитория пересекается,
        # ссылка на сестринский канал в описании — почти нулевая цена, потенциальный переток
        # подписчиков. sister_channel_handle — БЕЗ @, sister_desc_cta — фраза на СВОЁМ языке
        # про сестринский канал НА ДРУГОМ языке. Пул для разнообразия (тот же паттерн, что CTA).
        "sister_channel_handle": "DatoEn30Segundo",
        "sister_desc_ctas": [
            "🌎 Also in Spanish:",
            "🌎 We also post in Spanish:",
            "🌎 En español too:",
        ],
        "sister_lang_tags": ["datos curiosos", "hechos curiosos", "sabías que"],
        "sister_lang_code": "es",  # язык локализации метаданных (localize_metadata.py)
        # «On this day» (2026-07-05): час UTC первого слота дня — по четвергам в этот слот
        # выходит топикал-факт с привязкой к дате (live-генерация мимо очереди).
        "topical_slot_hour": 16,
        # Community-пост после лонгформа (2026-07-05): API постов не имеет — pipeline_longform
        # шлёт готовый текст опроса в Telegram, копируется в Studio → Сообщество вручную.
        "community_poll_intro": "Have you seen the new deep-dive yet: {title}? 👀\n\nWhich topic should next week's video cover? Vote 👇",
        # Префикс источника факта в описании (source_note из генерации).
        "source_label": "Source:",
        "chapters_label": "Chapters:",  # заголовок блока глав в описании месячной компиляции
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
        # Video pairs (2026-07-08, см. paired_facts.py): B ссылается на A в своём закреп-
        # комменте (pair_callback_ctas), A дозаписывается ссылкой на B ПОСЛЕ публикации B
        # (pair_backlink_ctas, отдельный коммент через post_channel_comment). Пул, не одна
        # строка — тот же принцип анти-паттерна, что first_comment_subscribe_ctas.
        "pair_callback_ctas": [
            "↩️ Remember what we said before:",
            "↩️ This follows up on an earlier video:",
            "↩️ Callback to a fact we posted earlier:",
        ],
        "pair_backlink_ctas": [
            "🔄 Update — turns out there's more to this story:",
            "🔄 Plot twist follow-up just dropped:",
            "🔄 We found an exception to this one:",
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
        "novita_voice": "Deep_Voice_Man",   # глубокий мужской нарратор под факт/deep-dive
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
        "daily_slots_utc": [(16, 17), (20, 17), (0, 17), (3, 17)],
        "script_language": "Spanish (neutral Latin American / Mexican Spanish, NOT European Spanish)",
        "voices": [
            "es-MX-JorgeNeural",
            "es-MX-DaliaNeural",
            "es-US-AlonsoNeural",
            "es-CO-GonzaloNeural",
        ],
        # 2026-07-10: "SÍGUEME" (follow) -> "SUSCRÍBETE" (subscribe) — misma razón que EN,
        # YouTube no tiene "Follow", el botón real dice "Suscribirse".
        "cta_phrases": [
            "DALE LIKE Y SUSCRÍBETE\npara más",
            "SUSCRÍBETE para más\ndatos como este",
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
        "cta_topic_template": "SUSCRÍBETE para más\ndatos de {word}",
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
            "future technology": "TECNOLOGÍA",
        },
        "cta_instruction": (
            "ONE short CTA in Spanish, 4-7 words MAX — either \"Suscríbete para más.\" or "
            "\"Comenta si lo sabías.\" Pick one, no embellishment, no extra clauses"
        ),
        # Instagram ES (2026-07-01): @datosen30s, свой Business-аккаунт/токен (см. daily-es.yml).
        "post_to_instagram": True,
        "post_to_tiktok": False,
        "post_to_pinterest": False,
        "post_to_threads": False,  # ожидает Threads-токен (см. upload_threads.py)
        # Реальный @handle (channels.list().customUrl), не название канала — см. комментарий
        # в EN-конфиге, тот же баг тут: было "DatosEn30s", реальный хендл — @datoen30segundo.
        "channel_handle": "DatoEn30Segundo",
        "sister_channel_handle": "60factspersecond",
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
        "ig_card_slot_hour": 3,  # первый ES-слот дня (03:17 UTC = 21:17 Мехико, было 13:17)
        "topical_slot_hour": 3,   # первый ES-слот дня (03:17 UTC) — топикал по четвергам
        "community_poll_intro": "¿Ya viste el nuevo análisis: {title}? 👀\n\n¿Sobre qué tema quieres el video de la próxima semana? Vota 👇",
        "source_label": "Fuente:",
        "chapters_label": "Capítulos:",
        "longform_desc_cta": "Análisis completos en el canal:",
        "longform_comment_cta": "¿Quieres la historia completa? Mira el análisis 👉",
        "first_comment": "Un momento — ¿tú ya sabías esto? 👇\nSuscríbete para un dato nuevo cada día 👉 {channel_url}",
        "first_comment_subscribe_ctas": [
            "Suscríbete para un dato nuevo cada día 👉 {channel_url}",
            "Dato nuevo cada día — suscríbete 👉 {channel_url}",
            "Sígueme para más datos como este 👉 {channel_url}",
            "Un dato al día, para siempre — suscríbete 👉 {channel_url}",
        ],
        "pair_callback_ctas": [
            "↩️ Recuerda lo que dijimos antes:",
            "↩️ Esto continúa un video anterior:",
            "↩️ Volviendo a un dato que publicamos antes:",
        ],
        "pair_backlink_ctas": [
            "🔄 Actualización — resulta que hay más en esta historia:",
            "🔄 Acaba de salir la continuación con un giro:",
            "🔄 Encontramos una excepción a esto:",
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
        "novita_voice": "Deep_Voice_Man",
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
    # Португальский (Бразилия) — 3-й канал (2026-07-09). Клон ES (доказанно > EN 2×), т.к.
    # португальский рынок культурно смежен и менее насыщен английской конкуренцией. Старт
    # только daily Shorts (без серий/лонгформа — сначала проверить канал). loop_probability
    # НЕЙТРАЛЬНЫЙ 0.3 (у ES петля вредит, у EN помогает — PT свежая аудитория, само подстроится).
    # ⚠️ ПЕРЕД ЗАПУСКОМ пользователь ДОЛЖЕН: создать YouTube-канал, получить YT_REFRESH_TOKEN_PT
    #   (get_youtube_token.py pt → gh secret), заполнить channel_handle реальным @хендлом.
    "pt": {
        "channel_name": "Fatos em 30s",
        "lang_code": "pt",
        # Бразильские прайм-слоты (UTC-3): 14:23 день / 18:23-22:23 вечерний прайм (главное окно
        # BR — 7-11pm, смещено позже US/EU, см. ресёрч 2026-07-09). Минута :23 — не бьётся с
        # EN(:07/:13)/ES(:17). UTC: 17:23=14:23BRT, 21:23=18:23, 23:23=20:23, 01:23=22:23.
        "daily_slots_utc": [(17, 23), (21, 23), (23, 23), (1, 23)],
        "script_language": "Brazilian Portuguese (natural, conversational, NOT European Portuguese)",
        "voices": [
            "pt-BR-AntonioNeural",
            "pt-BR-FranciscaNeural",
            "pt-BR-ThalitaMultilingualNeural",
        ],
        # 2026-07-10: "SIGA" (follow) -> "INSCREVA-SE" (subscribe) — mesmo motivo do EN/ES,
        # no YouTube não existe "Follow", o botão real diz "Inscrever-se".
        "cta_phrases": [
            "CURTA E INSCREVA-SE\npara mais",
            "INSCREVA-SE para mais\nfatos como este",
            "CURTA\nse não sabia",
        ],
        "loop_phrases": {
            "why": ["E é por isso.", "E é exatamente por isso.", "É por isso mesmo.", "É por isso que acontece."],
            "how": ["E é assim.", "E é exatamente assim.", "É desse jeito."],
            "when": ["E foi justamente quando.", "E tudo começou quando."],
            "where": ["E foi bem ali que.", "E tudo aconteceu onde."],
            "because": ["E tudo por causa disso.", "E é porque."],
        },
        "loop_probability": 0.3,
        "cta_topic_template": "INSCREVA-SE para mais\nfatos sobre {word}",
        "topic_cta_words": {
            "the ocean": "OCEANO",
            "the animal kingdom": "ANIMAIS",
            "space": "ESPAÇO",
            "the human body": "CORPO",
            "ancient history": "HISTÓRIA",
            "archaeological discoveries": "ARQUEOLOGIA",
            "ancient civilizations": "CIVILIZAÇÕES",
            "volcanoes and earthquakes": "VULCÕES",
            "extreme weather": "CLIMA",
            "historical mysteries": "MISTÉRIOS",
            "evolution": "EVOLUÇÃO",
            "natural wonders": "NATUREZA",
            "shipwrecks and lost treasures": "NAUFRÁGIOS",
            "future technology": "TECNOLOGIA",
        },
        "cta_instruction": (
            "ONE short CTA in Brazilian Portuguese, 4-7 words MAX — either \"Inscreva-se para mais.\" or "
            "\"Comenta se você já sabia.\" Pick one, no embellishment, no extra clauses"
        ),
        "post_to_instagram": False,   # нет PT IG-аккаунта — включить после создания
        "post_to_tiktok": False,
        "post_to_pinterest": False,
        "post_to_threads": False,
        "channel_handle": "30SegDeFatos",   # @30SegDeFatos (2026-07-09)
        "sister_channel_handle": "",   # кросс-промо выключено на старте (свежая аудитория)
        "sister_desc_ctas": [],
        "sister_lang_tags": [],
        "sister_lang_code": "",
        "ig_caption_ctas": [
            "🔗 Siga para mais fatos — link na bio",
            "📌 Um fato novo todo dia — link na bio",
            "🔗 Mais fatos como este — link na bio",
        ],
        "ig_card_slot_hour": 17,   # первый PT-слот (не используется пока IG выключен)
        "topical_slot_hour": 17,   # первый PT-слот (17:23 UTC, поправлено 2026-07-09 под бразильский прайм) — топикал по четвергам
        "community_poll_intro": "Já viu a nova análise: {title}? 👀\n\nSobre qual tema você quer o vídeo da próxima semana? Vote 👇",
        "source_label": "Fonte:",
        "chapters_label": "Capítulos:",
        "longform_desc_cta": "Análises completas no canal:",
        "longform_comment_cta": "Quer a história completa? Veja a análise 👉",
        "first_comment": "Peraí — você já sabia disso? 👇\nInscreva-se para um fato novo todo dia 👉 {channel_url}",
        "first_comment_subscribe_ctas": [
            "Inscreva-se para um fato novo todo dia 👉 {channel_url}",
            "Fato novo todo dia — inscreva-se 👉 {channel_url}",
            "Siga para mais fatos como este 👉 {channel_url}",
            "Um fato por dia, pra sempre — inscreva-se 👉 {channel_url}",
        ],
        "pair_callback_ctas": [
            "↩️ Lembra do que a gente falou antes:",
            "↩️ Isso continua um vídeo anterior:",
            "↩️ Voltando a um fato que postamos antes:",
        ],
        "pair_backlink_ctas": [
            "🔄 Atualização — tem mais nessa história:",
            "🔄 Saiu a continuação com uma reviravolta:",
            "🔄 A gente achou uma exceção pra isso:",
        ],
        "first_comment_replies": [
            "Seja sincero — isso te surpreendeu ou você já sabia? 👀",
            "A maioria passa reto sem acreditar. Você acreditou?",
            "De 1 a 10, quão falso soou no começo? 👇",
            "Se você já sabia, tá no 1% — prova aí embaixo 👇",
        ],
        "series_playlist_cta": "📺 Veja todas as partes na ordem 👉",
        "longform_comment": "Qual parte te surpreendeu mais? 👇\nInscreva-se para uma análise nova toda semana 👉 {channel_url}",
        "longform_use_novita": True,
        "novita_language": "Portuguese",
        "novita_voice": "Deep_Voice_Man",
        "playlist_titles": {
            "space": "Fatos do Espaço",
            "the ocean": "Fatos do Oceano",
            "ancient history": "Fatos de História Antiga",
            "the human body": "Fatos do Corpo Humano",
            "the animal kingdom": "Fatos de Animais",
            "future technology": "Fatos de Tecnologia",
            "volcanoes and earthquakes": "Vulcões e Terremotos",
            "ancient civilizations": "Civilizações Antigas",
            "evolution": "Fatos de Evolução",
            "extreme weather": "Clima Extremo",
            "archaeological discoveries": "Descobertas Arqueológicas",
            "shipwrecks and lost treasures": "Naufrágios e Tesouros Perdidos",
            "historical mysteries": "Mistérios Históricos",
            "natural wonders": "Maravilhas Naturais",
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
