# 60SecFacts / Datos en 30s — автоматический YouTube Shorts

Два параллельных канала на одном коде:
- **60SecFacts** (EN) — английский, 5 Shorts/день + 1 лонгформ/неделю, Instagram включён
- **Datos en 30s** (ES) — испанский, 3 Shorts/день, Instagram пока отключён

Конвейер: тема → сценарий (Claude `claude-sonnet-4-6`) → озвучка (edge-tts, бесплатно) → видео (стоковые клипы Pexels/Pixabay + караоке-субтитры, MoviePy) → YouTube → Instagram (только EN).

---

## Расписание публикаций

| Время UTC | Время Vietnam | EN (60SecFacts) | ES (Datos en 30s) |
|-----------|---------------|-----------------|-------------------|
| 13:07 | 20:07 | Shorts — **но в Пн/Вт/Ср вместо него Серия (Part 1/2/3)** | Shorts |
| 16:13 | 23:13 | Shorts | — |
| 20:07 | 03:07 (+1д) | Shorts | Shorts |
| 22:13 | 05:13 (+1д) | Shorts | — |
| 00:07 | 07:07 (+1д) | Shorts | Shorts |
| 15:07 Вс | 22:07 | Лонгформ | — |

**Серии замещают, а не добавляют:** в Пн/Вт/Ср слот 13:07 занимает серия (Part 1/2/3 по дням), а `daily.yml` в этот слот пропускает обычное видео (guard по дню недели + часу). Итого всегда **5 EN-роликов/день**, не 6.

**Чем триггерятся (важно):**
- **`daily.yml` / `daily-es.yml`** — ТОЛЬКО внешним **cron-job.org** (`workflow_dispatch`). Родной GitHub-`schedule` убран: он опаздывал на 10-40 мин и не совпадал по времени с cron-job.org, из-за чего concurrency-группа не ловила дубли → выходило ~10 видео/день вместо 5. cron-job.org бьёт точно вовремя.
- **`weekly-series.yml` / `weekly-longform.yml`** — на родном GitHub-`schedule` (у них нет дублёра в cron-job.org).
- **Подстраховка** — `watchdog.yml` запускается через 15 мин после каждого EN-слота (на GitHub-cron) и доретраит pipeline, если видео не появилось.

⚠️ **Зависимость:** daily теперь держится на cron-job.org. Если там слетит GitHub-PAT в заголовке заданий или задания отключатся — daily перестанет триггериться (watchdog частично подстрахует). При «тишине» в Actions — проверить задания на cron-job.org.

---

## Текущий статус

| Что | Состояние |
|-----|-----------|
| EN канал (60SecFacts) | ✅ работает, 5 видео/день |
| ES канал (Datos en 30s) | ✅ работает, 3 видео/день |
| Instagram EN (@a30secfacts) | ✅ включён, кросспостинг через Cloudinary |
| Instagram (ES) | ⏳ отключён — нет отдельного аккаунта |
| TikTok EN | ⏸️ `post_to_tiktok: False` в config — ждём одобрения app + токен |
| Pinterest EN | ⏸️ `post_to_pinterest: False` в config — ждём одобрения app |
| Telegram-алерты (`notify.py`) | ✅ 🔴 краш / ⚠️ частичный сбой / ✅ успех со ссылкой. Секреты `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` |
| Лонгформ (EN, еженедельно) | ✅ воскресенье 15:07 UTC; тумба + алерты выровнены |
| Серии (EN, 3 части **Пн/Вт/Ср**) | ✅ замещают daily-слот 13:07, не добавляются сверху |
| Watchdog (авторетрай) | ✅ проверяет через 15 мин после каждого слота |
| Субтитры на видео (caption tracks) | ⏸️ отключены ВЕЗДЕ (`enable_captions=False` в `publish.py` + лонгформ); экономия 1200 ед/видео; вернуть после увеличения квоты |
| Loop A/B (loop-yes/no тег) | ✅ 65% видео с петлёй; сравнение копится для `analytics_retention.py` |
| Фоновая музыка | ❌ убрана (была с голосами, мешала) |
| ES YouTube refresh token | ✅ переавторизован (был `invalid_scope`); `python src/get_youtube_token.py es` чинит автоматически |

---

## Как работает пайплайн (важные детали)

### Выбор темы (`generate_script.py`)
16 тем-пулов (space, ocean, psychology и т.д.). Пока данных меньше чем по 5 темам — выбирает случайно. Когда накопится статистика — взвешивает по средним просмотрам (`topic_stats.py`), т.е. популярные темы выбираются чаще. Скрытый тег `topic-<тема>` добавляется к каждому видео для трекинга.

**Стоп-темы (запрещено):** физика (`physics`) и квантовая физика (`quantum physics`) — слишком абстрактны, аудитория не чувствует сюрприза без специальных знаний. Запрет прописан в `BANNED_TOPICS` в коде и в системном промпте Claude.

### Дедупликация тем (`recent_titles.py`)
Перед генерацией сценария Claude получает список последних 100 заголовков канала и не должен повторять конкретные факты.

### Голоса TTS (`tts.py`)
Ротируются между видео (EN: 5 голосов, ES: 4 голоса) — YouTube следит за "inauthentic content", одинаковый голос каждый раз — красный флаг.

### Стоковое видео (`fetch_stock_video.py`)
Сначала Pexels, fallback на Pixabay. Claude генерирует поисковые запросы под каждый визуальный beat сценария (1 бит ≈ каждые 4-5 секунд), запросы пишутся под **настроение/обстановку**, а не под конкретный объект (стоки не имеют нишевых артефактов).

Три механизма качества клипов:
1. **Vision-отбор** — на каждый запрос берётся до 4 кандидатов, в Claude Haiku отправляются их **poster-кадры по URL** (Pexels отдаёт `image` в ответе — видео НЕ скачиваются), Haiku выбирает релевантный, полностью качается только победитель. ~$0.003/видео, трафик минимальный. Если у кандидатов нет preview (Pixabay-fallback) — берётся первый по релевантности стока. `VISION_CANDIDATES = 4`.
2. **Дедупликация** — `used_ids` в рамках одного видео: один и тот же сток-клип не попадёт дважды (раньше при похожих запросах клипы повторялись).
3. **Упрощение запроса** — если по полному запросу клипов нет, пробуем первые 2 слова (`mantis shrimp moving underwater` → `mantis shrimp`).

Фильтр: только вертикальные (`height >= width`), высота ≥ 960px. Pexels API запрашивается с `orientation=portrait`.

### Сборка видео (`build_video.py`)
- Формат: 1080×1920 (вертикаль)
- Zoom-эффект на фоне (1.05–1.15×), рандомится
- Караоке-субтитры: слово-по-слову, 3 цвета рандомно (белый/жёлтый/мятный), **идут до самого конца** (раньше обрывались за 2 сек до конца — теряли loop-фразу)
- CTA-пульс (сердечко + текст) в последние 2 сек, позиция ~24% сверху
- **Последний клип** зацикливается если короче своего слота; остальные клипы НЕ зацикливаются (показываются сколько есть) — чтобы не было повторов в середине
- **Thumbnail**: первый кадр + заголовок текстом **в верхней части** кадра (видно и в 9:16, и в Instagram 1:1 кропе который берёт центр); грузится на YouTube через `thumbnails.set` (нужны «расширенные функции» канала — у нас включены)

### Плейлисты (`playlists.py`)
Каждое видео автоматически добавляется в тематический плейлист по скрытому тегу. Плейлист создаётся если его ещё нет. Увеличивает watch session.

### Локальный тест и перерендер

```bash
# Полный прогон — генерирует сюжет, сохраняет видео + промежуточные файлы на рабочий стол
python src/test_local.py

# Перерендер с тем же сюжетом (после правки CTA/субтитров/сборки)
python src/rerender.py
```

#### ⚠️ Чем тестировать — `test_local.py` (платно) vs `rerender.py` (~$0)

**Правило: смотри КАКОЙ файл меняли.**

| Меняли файл | Что в нём | Тест | Цена |
|---|---|---|---|
| `build_video.py` | сборка: хук-текст, визуальный loop, субтитры, CTA-бейдж, тумба, зум, PART-оверлей | **`rerender.py`** | ~$0 (без Claude и без скачивания) |
| `config.py` (CTA-фразы, голоса) | оформление/озвучка | `rerender.py` (если только сборка) | ~$0 |
| `generate_script.py` | текст скрипта, loop-формулировка, длина, comment bait, валидатор | **`test_local.py`** | ~$0.03 (новый скрипт нужен) |
| `fetch_stock_video.py` | vision-отбор, запросы клипов | **`test_local.py`** | ~$0.03 (новые клипы нужны) |
| `tts.py` | озвучка/тайминги | `test_local.py` (новое аудио) | ~$0.03 |

Грубо: **меняешь как видео ВЫГЛЯДИТ из готовых данных → `rerender`. Меняешь как генерится ТЕКСТ/КЛИПЫ/ЗВУК → `test_local`.** `rerender.py` берёт последний `meta.json` + `clips/` и только пересобирает mp4 — Claude и стоки не дёргаются.

Файлы сохраняются в `~/Desktop/auto-shorts-test/`. Каждый прогон НЕ перезатирает прошлый: пишет и `video.mp4`/`thumb.jpg`/`meta.json` (последний), и нумерованные копии `video_NN.mp4`, `thumb_NN.jpg`, `meta_NN.json` (NN = следующий свободный номер). Плюс `audio.mp3` и `clips/`.

**Залить готовое видео с рабочего стола на YouTube+Instagram вручную** (без новой генерации) — `src/upload_from_desktop.py` (читает `video_02.mp4` + `meta.json`; поправь имя файла в скрипте под нужное видео).

### Watchdog (`watchdog.yml`)
Запускается через 15 мин после каждого слота Shorts. Если свежего видео нет — перезапускает pipeline. Окно проверки: 25 минут.

### Недельная серия (`pipeline_series.py` + `generate_series.py`)

3 тематически связанных видео 3 дня подряд (Пн/Вт/Ср в 20:07 Vietnam = 13:07 UTC), **замещают** слот 13:07 обычного daily, а не добавляются сверху:
- **Part 1 (Пн):** генерирует все 3 скрипта за один вызов Claude → сохраняет в `series_state.json` → публикует Part 1. CTA: *"Follow so you don't miss Part 2"*
- **Part 2 (Вт):** читает `series_state.json`, публикует. CTA: *"Follow for Part 3"*
- **Part 3 (Ср):** развязка + обычный follow CTA

Каждое видео начинается с оверлея **"PART N / 3"** в верхней части экрана (2.5 сек).

`series_state.json` — персистируется между ранами через `actions/cache` (ключ `series-state-en`).

**Чтобы отключить серии** — достаточно задизейблить `weekly-series.yml` в GitHub Actions. Ежедневные видео продолжат работать независимо.

**Чтобы запустить вручную:** Actions → Weekly Series (EN) → Run workflow → выбрать part (1/2/3). Если запускаешь Part 2 или 3 — убедись что `series_state.json` есть в кеше (т.е. Part 1 уже был запущен).

### Лонгформ (`pipeline_longform.py` + `generate_longform_script.py`)
Еженедельная компиляция: 5 фактов на одну тему, 3.5–4.5 мин, 550–700 слов. Второй путь к монетизации (1000 подписчиков + 4000 часов обычных просмотров, независимо от порога Shorts).

### CTA (call-to-action)

Последние 2 сек каждого видео: пульсирующее сердце + pill-бэйдж с текстом.

- **Сердце** — кубические безье (`_draw_heart_png`), рендерится в 600px → downscale до 220px при анимации (нет пикселизации). Цвет `#FF1744`, тонкая тёмная тень.
- **Бэйдж** — PIL pill с тёмной полупрозрачной подложкой (rgba 0,0,0,175), белый текст. Читается на любом фоне.
- **Текст бейджа** — topic-aware: если для темы есть слово в `topic_cta_words` → персональный призыв («FOLLOW for more OCEAN facts»), иначе генерик из `cta_phrases`. Конвертит лучше генерика. Правится в `config.py` (`cta_topic_template` + `topic_cta_words` + `cta_phrases`).

### Структура скрипта (`generate_script.py`, `BASE_SYSTEM_PROMPT`)
Жёсткий порядок предложений:
1. **Хук** — интрига БЕЗ раскрытия субъекта. Субъект называется только во 2-м предложении.
2. **Reveal + факт** — обязан содержать **конкретный якорь**: число/дату/место/имя (*"100,000 years"*, *"1888 Ritter Island"*). Где честно можно — привязка к телу/жизни/безопасности зрителя.
3. **Твист** — момент, где заблуждение явно рушится.
4. **Comment bait** — один из 4 механизмов (не generic "what do you think?"): (a) ловушка-коррекция; (b) призыв к личному опыту; (c) деление на лагеря; (d) незавершённое "actually".
5. **CTA** — последняя фраза скрипта от Claude. КОРОТКАЯ (4-7 слов): «Follow for more.» / «Comment if you knew this.». Loop-строку Claude НЕ пишет.

### Loop (петля пересмотра) — вариант A: Claude вет­тит, код собирает
**Это итог долгой итерации — НЕ менять без понимания.** Механизм:
1. Claude НЕ пишет loop-строку. Вместо этого отдаёт поле `loop_connectors` — список из {why/how/when/where/because}, для которых «<слово> <хук>» читается как **связное предложение** (вет­тит, зная свой хук).
2. Код (`_append_loop`) **детерминированно** дописывает фразу-петлю в конец скрипта: берёт коннектор из списка Claude, случайную формулировку под него из `CFG["loop_phrases"]` (на языке канала), приклеивает.
3. На стыке петли «<фраза> <хук>» = одно связное предложение. Пример: хук «Something in East Africa mummifies any creature…» + конец «Here's how.» → петля «Here's how something in East Africa mummifies…» ✓.

**Почему так:** форма гарантирована (эмитим только из списка Claude), смысл вет­тит модель на этапе генерации, мусор пройти не может. Прошлые подходы (кастомный фрагмент / общее слово / повтор слов хука) разваливались на стыке по смыслу.

**Петля НЕ на каждом видео:** `loop_probability` (0.65) — ~35% видео идут с обычной концовкой, чтобы приём не стал формулой. Каждое видео тегается `loop-yes`/`loop-no` → сравнение в `analytics_retention.py`. Решаем по данным через 2-3 недели, а не по теории.

### Валидация-гейт (`_validate` + `_better` в `generate_script.py`)
После генерации — **один** таргетный повтор, только если плохо (платный 2-й вызов в ~30% случаев):
- слов > 92 → длинно (повтор регенерирует и `video_queries`, десинхрона нет)
- `loop_connectors` пустой/невалидный

Выбор лучшего из двух (`_better`): меньше проблем; **при равенстве — короче скрипт** (иначе при «обе длинные» оставался бы длинный оригинал — это давало 48с).

### Длина Shorts-видео
30–37 сек (75–90 слов). Жёсткий потолок «over 90 = failure» в промпте, гейт на 92. CTA укорочен, чтобы не раздувал длину. edge-tts +5% ≈ 2.6 слова/сек.

### Что в контенте работает НЕ идеально (на будущее)
- **Vision-отбор клипов** — выбирает лучший из 4 по poster-кадрам, но если все 4 нерелевантны — берёт нерелевантный.
- **Предсказуемость структуры** — каждое видео = каркас "misconception reversal". **План:** на 5-10k подписчиков ввести ротацию 3-4 типов видео. Не срочно.
- **Звуковые акценты (SFX)** — пробовали, не зашло (синтетические звучали лишними), откатили. Можно вернуться с готовыми студийными SFX.
- **Edge-TTS** иногда нечётко произносит редкие слова — компенсируется субтитрами.

### Идеи / backlog (на будущее)
- **Instagram с карточками фактов** — отдельный контент-поток в IG: статичные посты-карточки (факт + брендинг, как генератор пинов в `upload_pinterest.py`), а не только Reels-кросспостинг. Переиспользовать логику генерации карточки. Растит охват в ленте/Explore помимо видео.

### Текст-хук в первом кадре (`build_video._hook_clip`)
Крупный статичный текст (заголовок) поверх первых ~2.8 сек — стоп-скролл для тех, кто смотрит без звука. Главный рычаг retention в первой секунде. Тумба берётся из кадра во время хука (текст уже в кадре, отдельный overlay убран).

---

## Структура

```
src/
  pipeline.py               # точка входа Shorts (ежедневные видео)
  pipeline_longform.py      # точка входа лонгформа
  pipeline_series.py        # точка входа недельных серий (Part 1/2/3)
  publish.py                # ОБЩАЯ публикация (YT→плейлист→коммент→IG/TikTok→Pinterest); зовут оба пайплайна
  notify.py                 # Telegram-алерты (🔴 краш / ⚠️ частичный сбой / ✅ успех со ссылкой)
  config.py                 # конфиг EN/ES — голоса, CTA, loop_phrases, loop_probability, плейлисты
  generate_script.py        # тема + сценарий + loop_connectors + валидация-гейт + сборка петли
  analytics_retention.py    # retention из YouTube Analytics API: % досмотра по теме/длине/loop-yes-no
  generate_series.py        # генерирует все 3 части серии за один вызов Claude
  generate_longform_script.py
  tts.py                    # текст → аудио (edge-tts, +5% скорость), retry если < 25s
  build_video.py            # стоковые клипы + субтитры + CTA [+ PART N оверлей] → mp4
  fetch_stock_video.py      # Pexels → Pixabay fallback; vision-отбор по poster-кадрам URL (Claude Haiku)
  upload_youtube.py         # загрузка на YouTube (категория: Education) + thumbnails.set
  upload_from_desktop.py    # залить готовое video_NN.mp4 с рабочего стола на YT+IG вручную
  upload_instagram.py       # Instagram Graph API v21.0 (Reels), cover_url поддержка
  cloudinary_upload.py      # временный хостинг видео/изображений для IG (Cloudinary)
  post_comment.py           # авто-комментарий от канала после загрузки
  upload_captions.py        # EN + VI + TL субтитры (авто-перевод через Claude Haiku) [временно отключены]
  upload_pinterest.py       # генерация карточки PIL + публикация пина Pinterest API v5
  playlists.py              # авто-плейлисты по теме
  recent_titles.py          # последние 100 заголовков + локальный кеш (дедупликация)
  topic_stats.py            # средние просмотры по темам для взвешенного выбора
  check_recent_upload.py    # проверка для watchdog (окно 25 мин)
  get_youtube_token.py      # OAuth: python get_youtube_token.py [es] — обновляет .env + GitHub Secret автоматически
  youtube_auth.py           # Google API клиент

.github/workflows/
  daily.yml           # EN Shorts: 13:07, 16:13, 20:07, 22:13, 00:07 UTC
  daily-es.yml        # ES Shorts: 13:17, 20:17, 00:17 UTC (смещены от EN)
  weekly-series.yml   # EN серии: Пн/Вт/Ср 13:07 UTC (Part 1/2/3), замещают daily-слот 13:07
  weekly-longform.yml # EN лонгформ: воскресенья 15:07 UTC
  watchdog.yml        # авторетрай через 15 мин после каждого EN-слота
```

---

## Секреты GitHub (Settings → Secrets → Actions)

| Секрет | Кому нужен |
|--------|-----------|
| `ANTHROPIC_API_KEY` | оба канала |
| `PEXELS_API_KEY` | оба канала |
| `PIXABAY_API_KEY` | оба канала (fallback) |
| `YT_CLIENT_ID` | оба канала |
| `YT_CLIENT_SECRET` | оба канала |
| `YT_REFRESH_TOKEN` | EN канал |
| `YT_REFRESH_TOKEN_ES` | ES канал |
| `CLOUDINARY_CLOUD_NAME` | только EN (Instagram) |
| `CLOUDINARY_API_KEY` | только EN (Instagram) |
| `CLOUDINARY_API_SECRET` | только EN (Instagram) |
| `IG_ACCESS_TOKEN` | только EN (Instagram) |
| `IG_USER_ID` | только EN (Instagram) |
| `TIKTOK_ACCESS_TOKEN` | только EN (TikTok, после одобрения app) |
| `PINTEREST_ACCESS_TOKEN` | только EN (Pinterest, после одобрения app) |
| `PINTEREST_BOARD_ID` | только EN (Pinterest, после одобрения app) |
| `TELEGRAM_BOT_TOKEN` | оба канала (алерты) — бот `alert_report_api_bot` |
| `TELEGRAM_CHAT_ID` | оба канала (алерты) — `326791462` |

---

## Telegram-алерты (`notify.py`)
Бот шлёт в чат при любом исходе пайплайна (закрывает дыру: GitHub-письма приходят только при ПОЛНОМ падении job, а частичные сбои шли в exit 0 — молча):
- 🔴 **краш** — видео не вышло (пайплайн упал, исключение проброшено → GitHub тоже красит)
- ⚠️ **частичный сбой** — видео вышло, но отвалился шаг (IG / TikTok / Pinterest / коммент / плейлист / тумба)
- ✅ **успех** — со ссылкой на видео

Без секретов `TELEGRAM_*` функция тихо no-op (локальные прогоны не падают). Включено во всех workflow.

---

## Запуск вручную

```bash
pip install -r requirements.txt

# EN канал
python src/pipeline.py

# ES канал
CHANNEL=es python src/pipeline.py

# Лонгформ (EN)
python src/pipeline_longform.py
```

### Триггер через GitHub Actions (без локальной среды)
Actions → нужный workflow → **Run workflow**

### Обновить YouTube refresh token

```bash
# EN канал — обновляет YT_REFRESH_TOKEN в .env и GitHub Secrets автоматически
python src/get_youtube_token.py

# ES канал — обновляет YT_REFRESH_TOKEN_ES в .env и GitHub Secrets автоматически
python src/get_youtube_token.py es
```

Скрипт откроет браузер → войди под нужным Google аккаунтом → токен запишется сам.

---

## Добавить Instagram для ES-канала

1. Создать Instagram Business-аккаунт для испанского канала
2. Привязать к Facebook Page, получить `IG_ACCESS_TOKEN` и `IG_USER_ID`
3. `gh secret set IG_ACCESS_TOKEN_ES -b"<токен>"` и `gh secret set IG_USER_ID_ES -b"<id>"`
4. В `daily-es.yml` добавить секреты в env
5. В `config.py` → `"es"` → `"post_to_instagram": True`

---

## Монетизация

**YouTube Partner Program — два пути:**

| Путь | Порог | Канал |
|------|-------|-------|
| Shorts | 1000 подписчиков + 10M просмотров Shorts за 90 дней | EN + ES |
| Лонгформ | 1000 подписчиков + 4000 часов обычных просмотров | EN |

Актуальные пороги: [youtube.com/creators](https://youtube.com/creators)

**Обслуживание раз в 1-2 недели:** заглядывай в аналитику YouTube Studio — если просмотры упали, алгоритм мог сменить предпочтения формата. Статистика по темам: `python src/topic_stats.py` (локально).

---

## Instagram — как работает (EN)

Instagram не принимает файл напрямую — нужна публичная HTTPS-ссылка. Схема:
1. Видео загружается во временное хранилище **Cloudinary** (бесплатный тариф)
2. Instagram скачивает по публичной ссылке и публикует как Reel
3. Временный файл в Cloudinary сразу удаляется

**Instagram-аккаунт:** `@a30secfacts` (Business-аккаунт, привязан к Facebook-странице `a30secfacts`)  
**Meta-приложение:** `30secreels`  
**Токен:** System User токен — **не истекает** (expires_at: 0), перевыпуск не нужен

**Если Instagram сломается** — проверить:
1. Токен `IG_ACCESS_TOKEN` в GitHub Secrets (System User токены не истекают, но могут быть отозваны при смене пароля Facebook)
2. Cloudinary не превысил лимит free-тира (25 GB трафика/месяц)
3. Instagram Business Account ID остался `17841424354177774` (не менялся)

---

## TikTok — как активировать (ожидает одобрения app)

Схема та же, что и для Instagram: видео уже на Cloudinary → TikTok скачивает по URL.

**Что сделано:**
- `src/upload_tiktok.py` — Content Posting API v2, метод `PULL_FROM_URL`, polling статуса
- `pipeline.py` / `pipeline_series.py` — один Cloudinary-аплоад на оба сервиса (не двойной)
- `config.py` → EN: `post_to_tiktok: True` (сработает автоматически после добавления токена)
- `daily.yml` / `weekly-series.yml` → `TIKTOK_ACCESS_TOKEN` уже прописан в env

**Активация после одобрения TikTok Dev App:**

```bash
# 1. Получить authorization code
python src/get_tiktok_token.py
# Откроет браузер → авторизуй → скопируй redirect URL → вставь в терминал

# 2. Обменять на access token
python src/exchange_tiktok_token.py
# Выведет access_token и refresh_token

# 3. Добавить секрет в GitHub
gh secret set TIKTOK_ACCESS_TOKEN -b"<access_token>"
```

После шага 3 следующий запуск `daily.yml` автоматически опубликует видео в TikTok.

**TikTok Developer App:**
- Название: `60SecFacts`
- Client Key: `awlqkv9gr65hjezw`
- ToS: `https://korovazzz9-jpg.github.io/pages/tos.html`
- Privacy: `https://korovazzz9-jpg.github.io/pages/privacy.html`

**Если TikTok сломается:** `"post_to_tiktok": False` в `config.py` → EN-конфиг. Instagram продолжит работать независимо.

---

## Pinterest — как активировать (ожидает одобрения app)

Каждое видео автоматически генерирует карточку с фактом (1000×1500px, PIL) и публикует её как пин со ссылкой на YouTube Short.

**Что сделано:**
- `src/upload_pinterest.py` — генерация карточки + Pinterest API v5
- `pipeline.py` — шаг после Instagram/TikTok, не зависит от Cloudinary
- `config.py` → EN: `post_to_pinterest: True`
- Все workflows → `PINTEREST_ACCESS_TOKEN` и `PINTEREST_BOARD_ID` прописаны в env

**Сайт приложения:** `https://60secfacts.netlify.app`

**Активация после одобрения Pinterest Dev App:**

```bash
# 1. Получить access token в developers.pinterest.com → My Apps → Authentication
# 2. Получить board ID
gh secret set PINTEREST_ACCESS_TOKEN -b"<токен>"
gh secret set PINTEREST_BOARD_ID -b"<board_id>"
```

**Если Pinterest сломается:** `"post_to_pinterest": False` в `config.py` → EN-конфиг.

---

## История ключевых решений

- **Ниша "факты"** — выбрана из-за низкого риска авторских прав и простоты генерации
- **Английский язык** — больше аудитория, выше CPM рекламодателей
- **Pollinations.ai → стоковые клипы** — первая версия использовала AI-генерацию картинок с эффектом Ken Burns, потом переключились на реальные видео Pexels/Pixabay (лучше смотрится)
- **MoviePy 1.x закреплён** в requirements — 2.x сломал совместимость API (`moviepy.editor` убрали)
- **Python 3.12** — установлен на машине взамен неполной установки Python 3.13
- **ImageMagick** нужен для субтитров; на Windows ищет `magick.exe` (не `convert.exe`) — путь прописан явно в `build_video.py`
- **Reddit-интеграция** — отменена: Reddit в 2025-2026 требует одобрения приложения и запрещает авто-постинг ссылок ("Responsible Builder Policy")
- **Расписание** подстроено под пики активности US Eastern: публикуем за 2-3 часа до пиков (12:00-15:00 и 18:00-21:00 ET). При переходе США на зимнее время (ноябрь) — сдвинуть расписание на час раньше
- **"inauthentic content"** — YouTube с 2025 усилил детекцию шаблонного контента. Поэтому сделана ротация: голоса TTS, зум фона, цвет субтитров, текст CTA

---

## Работа с ассистентом (Claude)

- После любого коммита сразу делать `git push origin master` — без запроса подтверждения.
- Деплой = пуш в master, GitHub Actions подхватывает автоматически.
- **Обновлять README после каждого изменения логики** — так, чтобы всегда можно было откатиться к предыдущему поведению.

### Как откатить фичу
Все новые фичи изолированы и отключаемы независимо:
| Фича | Как отключить |
|------|--------------|
| Серии (Part 1/2/3) | Задизейблить `weekly-series.yml` в Actions |
| VI/TL субтитры | Убрать `"vi"` / `"tl"` из `_EXTRA_CAPTION_LANGS` в `upload_captions.py` |
| Авто-комментарий | Убрать `"first_comment"` из конфига канала в `config.py` |
| Instagram thumbnail | Убрать `cover_url=hosted_thumb["url"]` из вызова `upload_reel` в `pipeline.py` |
| TikTok | `"post_to_tiktok": False` в `config.py` → EN-конфиг |
| Pinterest | `"post_to_pinterest": False` в `config.py` → EN-конфиг |
| PART N оверлей | Убрать `part=` аргумент из вызова `build_video` в `pipeline_series.py` |
| TTS retry | Убрать цикл в `text_to_speech`, оставить один вызов `_synthesize` |
| CTA (сердце + бэйдж) | `_draw_heart_png()` и `_draw_cta_badge()` в `build_video.py` |

## Аналитика

```bash
# Оба канала сразу
python src/analytics.py

# Только один канал
CHANNEL=es python src/analytics.py
```

Показывает для каждого канала:
- Подписчиков, всего просмотров, кол-во видео
- За последние 7 дней: просмотры, лайки, среднее на видео
- Таблицу последних 20 видео: заголовок, возраст, просмотры, лайки

Использует YouTube Data API v3 (не требует отдельного включения Analytics API).

---

## cron-job.org — внешний триггер

GitHub Actions cron ненадёжен (опаздывает на 10-40 мин, иногда пропускает). Поэтому daily.yml/daily-es.yml триггерятся **только** через [cron-job.org](https://cron-job.org) — это теперь ОСНОВНОЙ (единственный) триггер для них, а не дублёр. Родной GitHub-`schedule` у них убран (плодил дубли — см. раздел «Расписание»).

**Как работает:**
1. cron-job.org по расписанию отправляет POST-запрос на GitHub API
2. GitHub получает `workflow_dispatch` событие и запускает workflow
3. Слоты бьют точно вовремя (cron-job.org не опаздывает как GitHub-cron)

**Настроено 8 заданий** (Moscow time = UTC+3):

| Название | Workflow | Moscow | UTC |
|----------|----------|--------|-----|
| EN-1300 | daily.yml | 16:07 | 13:07 |
| EN-1600 | daily.yml | 19:13 | 16:13 |
| EN-2000 | daily.yml | 23:07 | 20:07 |
| EN-2200 | daily.yml | 01:13 | 22:13 |
| EN-0000 | daily.yml | 03:07 | 00:07 |
| ES-1300 | daily-es.yml | 16:17 | 13:17 |
| ES-2000 | daily-es.yml | 23:17 | 20:17 |
| ES-0000 | daily-es.yml | 03:17 | 00:17 |

**Если нужно обновить токен в cron-job.org:**
Зайди на cron-job.org → каждое задание → Edit → в заголовке `Authorization` замени токен.

---

## Мониторинг

- **GitHub Actions** — вкладка Actions: каждый запуск, ошибки, логи
- **Watchdog** — автоматически ретраит пропущенные слоты
- **YouTube Studio** — аналитика, статистика по видео
- Локальная статистика тем: `python src/topic_stats.py`

**Что проверять раз в 1-2 недели:**
- Баланс Anthropic API (console.anthropic.com)
- Нет ли предупреждений/страйков в YouTube Studio
- Просмотры не упали резко (если упали — алгоритм сменил предпочтения формата, норма для Shorts)
- GitHub Actions → последние запуски не красные
