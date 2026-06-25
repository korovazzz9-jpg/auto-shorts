# 60SecFacts / Datos en 30s — автоматический YouTube Shorts

Два параллельных канала на одном коде:
- **60SecFacts** (EN) — английский, 5 Shorts/день + 1 лонгформ/неделю, Instagram включён
- **Datos en 30s** (ES) — испанский, 3 Shorts/день, Instagram пока отключён

Конвейер: тема → сценарий (Claude `claude-sonnet-4-6`) → озвучка (edge-tts, бесплатно) → видео (стоковые клипы Pexels/Pixabay + караоке-субтитры, MoviePy) → YouTube → Instagram (только EN).

---

## Расписание публикаций

| Время UTC | Время Vietnam | EN (60SecFacts) | ES (Datos en 30s) |
|-----------|---------------|-----------------|-------------------|
| 13:07 | 20:07 | Shorts | Shorts |
| 13:07 Пн/Ср/Пт | 20:07 | Серия (Part 1/2/3) | — |
| 16:13 | 23:13 | Shorts | — |
| 20:07 | 03:07 (+1д) | Shorts | Shorts |
| 22:13 | 05:13 (+1д) | Shorts | — |
| 00:07 | 07:07 (+1д) | Shorts | Shorts |
| 15:07 Вс | 22:07 | Лонгформ | — |

Watchdog запускается через 15 мин после каждого EN-слота и перезапускает pipeline если видео не появилось.

---

## Текущий статус

| Что | Состояние |
|-----|-----------|
| EN канал (60SecFacts) | ✅ работает, 5 видео/день |
| ES канал (Datos en 30s) | ✅ работает, 3 видео/день |
| Instagram EN (@a30secfacts) | ✅ включён, кросспостинг через Cloudinary |
| Instagram (ES) | ⏳ отключён — нет отдельного аккаунта |
| TikTok EN | ⏳ ожидает одобрения TikTok Developer App (1–5 дней) |
| Лонгформ (EN, еженедельно) | ✅ каждое воскресенье 15:07 UTC |
| Серии (EN, 3 части Пн/Ср/Пт) | ✅ `weekly-series.yml`, Part 1 генерирует все 3 |
| Watchdog (авторетрай) | ✅ проверяет через 15 мин после каждого слота |
| Фоновая музыка | ❌ убрана (была с голосами, мешала) |

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
Сначала Pexels, fallback на Pixabay. Claude генерирует поисковые запросы под каждый визуальный beat сценария (1 бит ≈ каждые 4-5 секунд). Для Shorts берётся случайный клип из топ-10 результатов — чтобы фон не повторялся.

### Сборка видео (`build_video.py`)
- Формат: 1080×1920 (вертикаль)
- Zoom-эффект на фоне (1.05–1.15×), рандомится
- Караоке-субтитры: слово-по-слову, 3 цвета рандомно (белый/жёлтый/мятный)
- CTA-пульс (сердечко + текст) в последние 2 сек, позиция ~24% сверху

### Плейлисты (`playlists.py`)
Каждое видео автоматически добавляется в тематический плейлист по скрытому тегу. Плейлист создаётся если его ещё нет. Увеличивает watch session.

### Локальный тест и перерендер

```bash
# Полный прогон — генерирует сюжет, сохраняет видео + промежуточные файлы на рабочий стол
python src/test_local.py

# Перерендер с тем же сюжетом (после правки CTA/субтитров/сборки)
python src/rerender.py
```

Файлы сохраняются в `~/Desktop/auto-shorts-test/`: `video.mp4`, `thumb.jpg`, `audio.mp3`, `clips/`, `meta.json`.

### Watchdog (`watchdog.yml`)
Запускается через 15 мин после каждого слота Shorts. Если свежего видео нет — перезапускает pipeline. Окно проверки: 25 минут.

### Недельная серия (`pipeline_series.py` + `generate_series.py`)

3 тематически связанных видео в неделю (Пн/Ср/Пт в 20:07 Vietnam):
- **Part 1 (Пн):** генерирует все 3 скрипта за один вызов Claude → сохраняет в `series_state.json` → публикует Part 1. CTA: *"Follow so you don't miss Part 2"*
- **Part 2 (Ср):** читает `series_state.json`, публикует. CTA: *"Follow for Part 3"*
- **Part 3 (Пт):** развязка + обычный follow CTA

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
- **Текст** — ротируется из `cta_phrases` в конфиге (EN — английский, ES — испанский).

Чтобы изменить текст CTA — правь `"cta_phrases"` в `config.py` для нужного канала.

### Длина Shorts-видео
30–40 сек (80–110 слов) — оптимум по алгоритму YouTube 2026: абсолютное время просмотра важнее процента досматривания, более короткие видео теряли охват даже при высоком completion rate.

---

## Структура

```
src/
  pipeline.py               # точка входа Shorts (ежедневные видео)
  pipeline_longform.py      # точка входа лонгформа
  pipeline_series.py        # точка входа недельных серий (Part 1/2/3)
  config.py                 # конфиг EN/ES — голоса, CTA, плейлисты, Instagram
  generate_script.py        # тема + сценарий (Claude API) + взвешенный выбор темы
  generate_series.py        # генерирует все 3 части серии за один вызов Claude
  generate_longform_script.py
  tts.py                    # текст → аудио (edge-tts, +5% скорость), retry если < 25s
  build_video.py            # стоковые клипы + субтитры + CTA [+ PART N оверлей] → mp4
  fetch_stock_video.py      # Pexels → Pixabay fallback
  upload_youtube.py         # загрузка на YouTube (категория: Education)
  upload_instagram.py       # Instagram Graph API v21.0 (Reels), cover_url поддержка
  cloudinary_upload.py      # временный хостинг видео/изображений для IG (Cloudinary)
  post_comment.py           # авто-комментарий от канала после загрузки
  upload_captions.py        # EN + VI + TL субтитры (авто-перевод через Claude Haiku)
  playlists.py              # авто-плейлисты по теме
  recent_titles.py          # последние 100 заголовков + локальный кеш (дедупликация)
  topic_stats.py            # средние просмотры по темам для взвешенного выбора
  check_recent_upload.py    # проверка для watchdog (окно 25 мин)
  get_youtube_token.py      # разовый скрипт OAuth (локально)
  youtube_auth.py           # Google API клиент

.github/workflows/
  daily.yml           # EN Shorts: 13:07, 16:13, 20:07, 22:13, 00:07 UTC
  daily-es.yml        # ES Shorts: 13:17, 20:17, 00:17 UTC (смещены от EN)
  weekly-series.yml   # EN серии: Пн/Ср/Пт 13:07 UTC (Part 1/2/3)
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
python src/get_youtube_token.py
# откроет браузер → выбери нужный канал → скопируй токен
# gh secret set YT_REFRESH_TOKEN -b"<токен>"         # для EN
# gh secret set YT_REFRESH_TOKEN_ES -b"<токен>"      # для ES
```

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
| PART N оверлей | Убрать `part=` аргумент из вызова `build_video` в `pipeline_series.py` |
| TTS retry | Убрать цикл в `text_to_speech`, оставить один вызов `_synthesize` |
| CTA (сердце + бэйдж) | `_draw_heart_png()` и `_draw_cta_badge()` в `build_video.py` |

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
