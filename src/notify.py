"""Алерты в Telegram при сбоях пайплайна.

Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.
Если не заданы — функция тихо ничего не делает (локальные прогоны и каналы без
настроенного бота не падают из-за отсутствия алертов).
"""
import os

import requests


def notify(text: str) -> None:
    """Шлёт сообщение в Telegram. Никогда не бросает исключение наружу —
    сбой алерта не должен ронять пайплайн."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True},
            timeout=15,
        )
    except Exception as e:
        print(f"  (Telegram notify failed: {e})")


if __name__ == "__main__":
    notify("✅ Тест уведомления auto-shorts — бот настроен правильно.")
    print("Отправлено (если TELEGRAM_BOT_TOKEN/CHAT_ID заданы).")
