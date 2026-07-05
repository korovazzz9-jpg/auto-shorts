"""Телеграм-бот расписания. Слушает сообщение «расписание» (или /schedule) и отвечает
слотами выхода роликов в вьетнамском и московском времени + сколько до следующего ролика
по времени устройства (бот запускается локально → local time = время твоего ПК).

Запуск:  python schedule_bot.py   (держать окно открытым — отвечает, пока скрипт работает)
Использует тот же TELEGRAM_BOT_TOKEN, что и notify.py (бот alert_report_api_bot).

ВАЖНО: getUpdates работает, только если у бота НЕ установлен webhook (у нас не установлен —
notify.py шлёт через sendMessage). Если когда-нибудь поставим webhook, поллинг отвалится."""
import os
import time
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
API = f"https://api.telegram.org/bot{TOKEN}"

VN = timezone(timedelta(hours=7))    # Вьетнам UTC+7
MSK = timezone(timedelta(hours=3))   # Москва UTC+3

# Слоты публикаций в UTC (часы, минуты). EN — из check_recent_upload.SLOTS_UTC; ES — из cron-job.org.
# 2026-07-01: EN 5→4 (убран 13:07), ES 3→4 (добавлен 16:17) — перелив ресурса на ES.
# 2026-07-05: EN 22:13→23:07 (сдвиг в US-прайм 19:07 EDT, см. README).
EN_SLOTS = [(16, 13), (20, 7), (23, 7), (0, 7)]
ES_SLOTS = [(13, 17), (16, 17), (20, 17), (0, 17)]
ALL_SLOTS = sorted(set(EN_SLOTS + ES_SLOTS))

TRIGGERS = ("расписание", "/расписание", "schedule", "/schedule", "/start")


def _conv(h: int, m: int) -> tuple[str, str]:
    """(h,m) UTC → ('HH:MM' Вьетнам, 'HH:MM' Москва)."""
    dt = datetime(2000, 1, 1, h, m, tzinfo=timezone.utc)
    return dt.astimezone(VN).strftime("%H:%M"), dt.astimezone(MSK).strftime("%H:%M")


def _next_slot_utc(now: datetime) -> datetime:
    """Ближайший слот в будущем (UTC), ищем в сегодня/завтра по всем слотам."""
    cands = []
    for day in (0, 1):
        base = (now + timedelta(days=day)).date()
        for h, m in ALL_SLOTS:
            dt = datetime(base.year, base.month, base.day, h, m, tzinfo=timezone.utc)
            if dt > now:
                cands.append(dt)
    return min(cands)


def build_schedule() -> str:
    now = datetime.now(timezone.utc)
    lines = ["📅 Расписание выхода роликов", "(🇻🇳 Вьетнам · 🇷🇺 Москва)", "", "EN — 5/день:"]
    for h, m in EN_SLOTS:
        vn, msk = _conv(h, m)
        lines.append(f"• {vn} · {msk}")
    lines += ["", "ES — 3/день:"]
    for h, m in ES_SLOTS:
        vn, msk = _conv(h, m)
        lines.append(f"• {vn} · {msk}")

    nxt = _next_slot_utc(now)
    delta = nxt - now
    total = int(delta.total_seconds())
    h, m = total // 3600, (total % 3600) // 60
    local = nxt.astimezone()  # время устройства (локальная зона ПК, где запущен бот)
    lines += ["", f"⏭ Следующий: {local.strftime('%H:%M')} (твоё время) — через {h}ч {m:02d}м"]

    lines += ["", "ℹ️ Пн–Ср последний слот — это серии (Part 1/2/3).",
              "Вс ~06:00 ВН / 02:00 МСК — лонгформ."]
    return "\n".join(lines)


def main() -> None:
    print("Schedule bot запущен. Напиши боту «расписание». Ctrl+C для остановки.")
    offset = None
    while True:
        try:
            resp = requests.get(f"{API}/getUpdates",
                                params={"timeout": 30, "offset": offset}, timeout=40)
            for upd in resp.json().get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or upd.get("channel_post")
                if not msg:
                    continue
                text = (msg.get("text") or "").strip().lower()
                if any(text == t or text.startswith(t) for t in TRIGGERS):
                    chat_id = msg["chat"]["id"]
                    requests.post(f"{API}/sendMessage",
                                  data={"chat_id": chat_id, "text": build_schedule()}, timeout=15)
                    print(f"  Ответил расписанием в чат {chat_id}")
        except Exception as e:
            print(f"  Ошибка поллинга: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
