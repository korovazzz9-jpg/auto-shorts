# Auto Shorts — автоматический YouTube Shorts канал на фактах

Конвейер: тема → сценарий (Claude API) → озвучка (edge-tts, бесплатно) →
видео (фон + субтитры, MoviePy) → загрузка на YouTube (YouTube Data API) →
запуск по расписанию (GitHub Actions, бесплатно).

## Честно про "пассивность"

Это НЕ "настроил и забыл навсегда". Один раз руками нужно сделать:

1. Завести YouTube-канал.
2. Получить ключ Anthropic API (для генерации сценариев).
3. Настроить Google OAuth для YouTube Data API (один раз получить refresh token).
4. Залить секреты в GitHub Actions.

После этого скрипт сам, без вашего участия, раз в день:
- придумывает тему и пишет сценарий,
- озвучивает,
- собирает вертикальное видео с субтитрами,
- заливает на YouTube как Short с тегами и описанием.

Монетизация (YouTube Partner Program) включится не сразу — нужно набрать
1000 подписчиков и 10M просмотров Shorts за 90 дней (актуальные пороги
уточняйте на youtube.com/creators). Раз в 1-2 недели стоит заглядывать:
сменился алгоритм/формат — упадут просмотры, это нормально для такого
формата контента, и без присмотра доход будет затухать.

## Структура

```
src/
  generate_script.py   # тема + сценарий через Claude API
  tts.py                # текст -> аудио (edge-tts)
  build_video.py        # фон + субтитры + аудио -> mp4
  upload_youtube.py     # загрузка готового видео на YouTube
  pipeline.py            # склеивает всё вместе, точка входа
.github/workflows/
  daily.yml              # cron-job: раз в день гоняет pipeline.py
assets/
  backgrounds/            # фоновые вертикальные видео-петли (свои или royalty-free)
```

## Установка (один раз)

```bash
pip install -r requirements.txt
```

Создайте `.env` (локально для теста, в проде — GitHub Secrets):

```
ANTHROPIC_API_KEY=...
YT_CLIENT_ID=...
YT_CLIENT_SECRET=...
YT_REFRESH_TOKEN=...
```

Как получить YT_REFRESH_TOKEN — см. `src/get_youtube_token.py` (запускается
один раз локально, откроет браузер для логина в Google).

## Запуск вручную

```bash
python src/pipeline.py
```

## Автозапуск

`.github/workflows/daily.yml` гоняет `pipeline.py` каждый день в 12:00 UTC.
Секреты задаются в Settings → Secrets and variables → Actions репозитория.
