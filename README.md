# 60SecFacts / Datos en 30s — автоматический YouTube Shorts

Два параллельных канала на одном коде:
- **60SecFacts** (EN) — английский, 5 Shorts/день + 1 лонгформ/неделю, Instagram включён
- **Datos en 30s** (ES) — испанский, 3 Shorts/день, Instagram пока отключён

Конвейер: тема → сценарий (Claude `claude-sonnet-4-6`) → озвучка (edge-tts, бесплатно) → видео (стоковые клипы Pexels/Pixabay + караоке-субтитры, MoviePy) → YouTube → Instagram (только EN).

---

## Текущий статус

| Что | Состояние |
|-----|-----------|
| EN канал (60SecFacts) | ✅ работает, 5 видео/день |
| ES канал (Datos en 30s) | ✅ работает, 3 видео/день |
| Instagram EN (@a30secfacts) | ✅ включён, кросспостинг через Cloudinary |
| Instagram (ES) | ⏳ отключён — нет отдельного аккаунта |
| Лонгформ (EN, еженедельно) | ✅ каждое воскресенье 15:07 UTC |
| Watchdog (авторетрай) | ✅ проверяет через 15 мин после каждого слота |
| Фоновая музыка | ❌ убрана (была с голосами, мешала) |

---

## Как работает пайплайн (важные детали)

### Выбор темы (`generate_script.py`)
14 тем-пулов (space, ocean, psychology и т.д.). Пока данных меньше чем по 5 темам — выбирает случайно. Когда накопится статистика — взвешивает по средним просмотрам (`topic_stats.py`), т.е. популярные темы выбираются чаще. Скрытый тег `topic-<тема>` добавляется к каждому видео для трекинга.

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

### Watchdog (`watchdog.yml`)
Запускается через 15 мин после каждого слота Shorts. Если свежего видео нет — перезапускает pipeline. Окно проверки: 25 минут.

### Лонгформ (`pipeline_longform.py` + `generate_longform_script.py`)
Еженедельная компиляция: 5 фактов на одну тему, 3.5–4.5 мин, 550–700 слов. Второй путь к монетизации (1000 подписчиков + 4000 часов обычных просмотров, независимо от порога Shorts).

### Длина Shorts-видео
30–40 сек (80–110 слов) — оптимум по алгоритму YouTube 2026: абсолютное время просмотра важнее процента досматривания, более короткие видео теряли охват даже при высоком completion rate.

---

## Структура

```
src/
  pipeline.py               # точка входа Shorts
  pipeline_longform.py      # точка входа лонгформа
  config.py                 # конфиг EN/ES — голоса, CTA, плейлисты, Instagram
  generate_script.py        # тема + сценарий (Claude API) + взвешенный выбор темы
  generate_longform_script.py
  tts.py                    # текст → аудио (edge-tts, +5% скорость)
  build_video.py            # стоковые клипы + субтитры + CTA → mp4
  fetch_stock_video.py      # Pexels → Pixabay fallback
  upload_youtube.py         # загрузка на YouTube (категория: Education)
  upload_instagram.py       # Instagram Graph API v21.0 (Reels)
  cloudinary_upload.py      # временный хостинг видео для IG (Cloudinary)
  playlists.py              # авто-плейлисты по теме
  recent_titles.py          # последние 100 заголовков для дедупликации
  topic_stats.py            # средние просмотры по темам для взвешенного выбора
  check_recent_upload.py    # проверка для watchdog (окно 25 мин)
  get_youtube_token.py      # разовый скрипт OAuth (локально)
  youtube_auth.py           # Google API клиент

.github/workflows/
  daily.yml         # EN Shorts: 13:07, 16:13, 20:07, 22:13, 00:07 UTC
  daily-es.yml      # ES Shorts: 13:17, 20:17, 00:17 UTC (смещены от EN)
  weekly-longform.yml  # EN лонгформ: воскресенья 15:07 UTC
  watchdog.yml      # авторетрай через 15 мин после каждого EN-слота
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
