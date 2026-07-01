"""Очередь предгенерённых сценариев (`queue_<channel>.json`) — используется
`prepare_batch.py` (пишет) и `pipeline.py` (читает). Простой FIFO-список dict'ов,
той же формы, что возвращает `generate_script()`.

Если очередь пуста — `pipeline.py` генерит сценарий вживую, как раньше. Наличие/
отсутствие очереди НЕ меняет поведение пайплайна, кроме источника сценария."""
import json
import os

from config import CHANNEL

QUEUE_FILE = os.path.join(os.path.dirname(__file__), "..", f"queue_{CHANNEL}.json")


def load_queue() -> list[dict]:
    try:
        with open(QUEUE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_queue(queue: list[dict]) -> None:
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)


def pop_next() -> dict | None:
    """Достаёт и удаляет первый элемент очереди. None, если очередь пуста."""
    queue = load_queue()
    if not queue:
        return None
    item = queue.pop(0)
    save_queue(queue)
    return item
