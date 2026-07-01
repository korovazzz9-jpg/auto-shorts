"""Batch API preload для daily Shorts — генерирует сценарии ЗАРАНЕЕ через Anthropic
Message Batches (−50% Claude-стоимость на этом вызове) и складывает в `queue_<channel>.json`.
`pipeline.py` читает очередь первым делом; если она пуста — генерит сценарий вживую, как
раньше (fallback без риска для публикации).

СОЗНАТЕЛЬНО СУЖЕННЫЙ ОБЪЁМ: батчится только generate_script (Sonnet, самый дорогой
одиночный вызов). Vision-отбор клипов / TTS / сборка / загрузка остаются live в pipeline.py
на момент публикации — не трогаем самый чувствительный к времени и стабильности участок.
Экономия ~50% от стоимости script-gen (не всего Claude-расхода), но БЕЗ риска для
watchdog/расписания/публикации.

Запуск (не критично ко времени публикации — можно на native GitHub-cron):
  python prepare_batch.py            # EN, добивает очередь до QUEUE_TARGET
  CHANNEL=es python prepare_batch.py
"""
import os
import time

from anthropic import Anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
from dotenv import load_dotenv

from generate_script import (
    BASE_SYSTEM_PROMPT,
    HOOK_TEMPLATES,
    LENGTH_INSTRUCTION,
    LOOP_INSTRUCTION,
    _append_loop,
    _build_user_content,
    _parse_response,
    _pick_topic,
    _validate,
)
from recent_titles import add_title_to_cache, add_topic_to_cache, get_recent_titles
from script_queue import load_queue, save_queue

load_dotenv()

QUEUE_TARGET = 10  # держим очередь на ~2 дня вперёд (5 EN / 3 ES слотов/день)
POLL_INTERVAL = 20
POLL_TIMEOUT = 1800  # 30 минут ожидания в этом запуске; не успело — доберём в след. прогон


def main() -> None:
    queue = load_queue()
    need = QUEUE_TARGET - len(queue)
    if need <= 0:
        print(f"  Очередь уже полна ({len(queue)}/{QUEUE_TARGET}), ничего не готовим.")
        return

    print(f"  В очереди {len(queue)}/{QUEUE_TARGET}, готовим ещё {need} через Batch API...")
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=5)

    try:
        past_titles = get_recent_titles()
    except Exception:
        past_titles = []
    avoid_block = ""
    if past_titles:
        avoid_block = (
            "Already-published video titles on this channel — pick a DIFFERENT specific fact, "
            "not a variation of any of these:\n" + "\n".join(f"- {t}" for t in past_titles) + "\n\n"
        )

    system_prompt = BASE_SYSTEM_PROMPT + "\n\n" + LOOP_INSTRUCTION + "\n\n" + LENGTH_INSTRUCTION

    # Выбираем темы ПОСЛЕДОВАТЕЛЬНО, тегируя каждую в кеш сразу — иначе _pick_topic() внутри
    # этого же батча не увидит темы, выбранные парой строк выше, и может задвоить.
    topics = []
    for _ in range(need):
        t = _pick_topic()
        topics.append(t)
        add_topic_to_cache(t)

    requests_ = [
        Request(
            custom_id=f"item-{i}",
            params=MessageCreateParamsNonStreaming(
                model="claude-sonnet-4-6",
                max_tokens=1200,
                system=system_prompt,
                messages=[{"role": "user", "content": _build_user_content(topics[i], avoid_block)}],
            ),
        )
        for i in range(need)
    ]

    batch = client.messages.batches.create(requests=requests_)
    print(f"  Batch создан: {batch.id}, ждём завершения (до {POLL_TIMEOUT}s)...")

    waited = 0
    while waited < POLL_TIMEOUT:
        batch = client.messages.batches.retrieve(batch.id)
        if batch.processing_status == "ended":
            break
        time.sleep(POLL_INTERVAL)
        waited += POLL_INTERVAL
    else:
        print(f"  Batch не успел за {POLL_TIMEOUT}s — доберём результаты в следующий запуск "
              f"(batch_id={batch.id}, не потерян — Anthropic хранит результаты батча 29 дней).")
        return

    results_by_id = {r.custom_id: r for r in client.messages.batches.results(batch.id)}

    added = 0
    for i, topic in enumerate(topics):
        result = results_by_id.get(f"item-{i}")
        if not result or result.result.type != "succeeded":
            status = result.result.type if result else "missing"
            print(f"  item-{i}: batch-запрос не удался ({status}), пропускаем.")
            continue
        try:
            data = _parse_response(result.result.message)
        except Exception as e:
            print(f"  item-{i}: не распарсился JSON ({e}), пропускаем.")
            continue

        problems = _validate(data)
        if problems:
            # Один невалидный скрипт из батча — не гоняем повторный батч ради одного,
            # берём как есть (лучше короткий/несовершенный скрипт, чем потерянный слот).
            print(f"  item-{i}: замечания валидации ({len(problems)}), беру как есть.")

        _append_loop(data)
        ht = str(data.get("hook_template", "")).strip().lower()
        data["hook_template"] = ht if ht in HOOK_TEMPLATES else "other"
        if not str(data.get("hook_text", "")).strip():
            data["hook_text"] = data["title"]
        data["topic"] = topic
        data["hashtag_position"] = "end"
        add_title_to_cache(data["title"])
        queue.append(data)
        added += 1

    save_queue(queue)
    print(f"  Добавлено {added} сценариев в очередь ({len(queue)}/{QUEUE_TARGET}).")


if __name__ == "__main__":
    main()
