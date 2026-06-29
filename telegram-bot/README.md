# Schedule bot — Cloudflare Worker (24/7, без включённого ПК)

Телеграм-бот, который на «расписание» отвечает слотами выхода роликов (Вьетнам/Москва) и
временем до следующего ролика. Работает всегда — не требует включённого компа.

## Деплой (через дашборд Cloudflare, ~5 минут)

1. **Аккаунт Cloudflare** — зарегистрируйся на https://dash.cloudflare.com (бесплатно).
2. **Создать Worker:** Workers & Pages → Create → Create Worker → дай имя (напр. `schedule-bot`) → Deploy.
3. **Вставить код:** открой Worker → Edit code → удали шаблон, вставь содержимое
   `schedule_worker.js` → Deploy. Запомни URL вида `https://schedule-bot.<твой>.workers.dev`.
4. **Добавить секрет с токеном:** Worker → Settings → Variables and Secrets → Add →
   тип **Secret**, имя `BOT_TOKEN`, значение = твой `TELEGRAM_BOT_TOKEN` (из `.env`) → Save and deploy.
5. **Привязать webhook** (один раз) — открой в браузере, подставив токен и URL Worker:
   ```
   https://api.telegram.org/bot<ТОКЕН>/setWebhook?url=https://schedule-bot.<твой>.workers.dev
   ```
   Ответ `{"ok":true,...}` = готово. Теперь пиши боту «расписание».

## Важно

- **Webhook отключает getUpdates** → локальный `src/schedule_bot.py` после этого работать не будет
  (он больше не нужен — Worker заменяет его).
- `notify.py` (алерты о выходе роликов) **продолжает работать** — sendMessage с webhook совместим.
- Слоты захардкожены в `schedule_worker.js` (`EN_SLOTS`/`ES_SLOTS`). Поменял слоты — обнови код
  Worker и нажми Deploy.

## Откатиться на поллинг (убрать webhook)

```
https://api.telegram.org/bot<ТОКЕН>/deleteWebhook
```
После этого снова заработает `python src/schedule_bot.py`.
