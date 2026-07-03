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
import re
import time
import unicodedata

from anthropic import Anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
from dotenv import load_dotenv

from generate_script import (
    BASE_SYSTEM_PROMPT,
    EMOTIONAL_TONES,
    HOOK_TEMPLATES,
    LENGTH_INSTRUCTION,
    LOOP_INSTRUCTION,
    TITLE_OPENERS,
    _append_loop,
    _build_user_content,
    _parse_response,
    _pick_topic,
    _title_variety_note,
    _validate,
    pick_title_variant,
)
from recent_titles import add_title_to_cache, add_topic_to_cache, get_recent_titles
from script_queue import load_queue, save_queue

load_dotenv()

QUEUE_TARGET = 10  # держим очередь на ~2.5 дня вперёд (4 EN / 4 ES слота/день с 2026-07-01)
POLL_INTERVAL = 20
POLL_TIMEOUT = 1800  # 30 минут ожидания в этом запуске; не успело — доберём в след. прогон

# Batch-запросы идут параллельно и НЕ видят друг друга (в отличие от live-генерации, где
# avoid_block обновляется между вызовами) — модель может независимо выбрать один и тот же
# канонический факт дважды под разными заголовками ("армия Камбиса пропала в пустыне" vs
# "исчезнувшая без следа армия" — заголовки разные, факт один). Заголовки в стиле "El X que Y"
# слишком шаблонны, чтобы сравнивать их слова напрямую (ловит ложные срабатывания на разных
# фактах с одинаковой синтаксической рамкой). Вместо этого сравниваем СОБСТВЕННЫЕ ИМЕНА и
# ЧИСЛА, упомянутые в самом script — это то, что реально идентифицирует конкретный факт.
_PROPER_NOUN_RE = re.compile(r"\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{3,}\b")
_NUMBER_RE = re.compile(r"\b\d{3,}\b")
_COMMON_CAPITALIZED = {
    "pero", "este", "esta", "ellos", "ellas", "cada", "solo", "sólo", "otro", "otra",
    "aqui", "aquí", "nadie", "todos", "todas", "casi", "porque", "cuando", "donde",
    "the", "this", "that", "they", "their", "your", "here", "when", "where", "because",
}


def _signature(data: dict) -> set[str]:
    text = f"{data.get('script', '')} {data.get('title', '')}"
    nouns = {
        unicodedata.normalize("NFKD", w.lower())
        for w in _PROPER_NOUN_RE.findall(text)
    }
    nouns = {"".join(c for c in w if not unicodedata.combining(c)) for w in nouns}
    nouns -= _COMMON_CAPITALIZED
    numbers = set(_NUMBER_RE.findall(text))
    return nouns | numbers


def _title_words(title: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", title.lower())
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    words = re.findall(r"[a-z0-9]+", normalized)
    return words and set(words) or set()


def _is_duplicate(a: dict, b: dict) -> bool:
    # Основной сигнал: >=2 совпадающих собственных имени/числа — это конкретный факт,
    # совпадение случайно не бывает (в отличие от шаблонных слов заголовка).
    if len(_signature(a) & _signature(b)) >= 2:
        return True
    # Резерв: почти дословно совпадающий заголовок (перефразировки без изменений сути).
    wa, wb = _title_words(a["title"]), _title_words(b["title"])
    if wa and wb and len(wa & wb) / len(wa | wb) >= 0.6:
        return True
    return False


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
    variety_note = _title_variety_note(past_titles)  # один расчёт на весь батч — past_titles не меняется внутри батча

    # Выбираем темы ПОСЛЕДОВАТЕЛЬНО, тегируя каждую в кеш сразу — иначе _pick_topic() внутри
    # этого же батча не увидит темы, выбранные парой строк выше, и может задвоить.
    # title_variant роллится ЗДЕСЬ (не внутри _build_user_content) — иначе после парсинга
    # ответа неоткуда было бы узнать, какой вариант ушёл в конкретный запрос батча.
    topics, title_variants = [], []
    for _ in range(need):
        t = _pick_topic()
        topics.append(t)
        add_topic_to_cache(t)
        title_variants.append(pick_title_variant())

    requests_ = [
        Request(
            custom_id=f"item-{i}",
            params=MessageCreateParamsNonStreaming(
                model="claude-sonnet-4-6",
                max_tokens=1600,
                system=system_prompt,
                messages=[{"role": "user", "content": _build_user_content(
                    topics[i], avoid_block, title_variants[i][0] + variety_note)}],
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

        # Обязательные поля для публикации (pipeline.py/publish.py читают их без .get) —
        # если модель что-то пропустила, кладём неполный элемент в очередь = daily.yml потом
        # упадёт при публикации (пропущенный слот). Лучше пропустить сейчас (очередь доберётся
        # следующим прогоном), чем отдать битый сценарий в прод.
        missing = [k for k in ("title", "script", "video_queries", "tags", "hashtags")
                   if not data.get(k)]
        if missing:
            print(f"  item-{i}: в JSON нет полей {missing}, пропускаем.")
            continue

        # Пост-обработка одного элемента изолирована: сбой на одном не должен обрушить весь
        # прогон и потерять уже добавленные в очередь элементы (save_queue — после цикла).
        try:
            problems = _validate(data)
            if problems:
                # Один невалидный скрипт из батча — не гоняем повторный батч ради одного,
                # берём как есть (лучше короткий/несовершенный скрипт, чем потерянный слот).
                print(f"  item-{i}: замечания валидации ({len(problems)}), беру как есть.")

            _append_loop(data)
            ht = str(data.get("hook_template", "")).strip().lower()
            data["hook_template"] = ht if ht in HOOK_TEMPLATES else "other"
            to = str(data.get("title_opener", "")).strip().lower()
            data["title_opener"] = to if to in TITLE_OPENERS else "other"
            et = str(data.get("emotional_tone", "")).strip().lower()
            data["emotional_tone"] = et if et in EMOTIONAL_TONES else "other"
            if not str(data.get("hook_text", "")).strip():
                data["hook_text"] = data["title"]
            data["topic"] = topic
            data["title_variant"] = title_variants[i][1]
            data["hashtag_position"] = "end"

            dupe_of = next((q for q in queue if _is_duplicate(data, q)), None)
            if dupe_of:
                print(f"  item-{i}: похож на уже добавленный «{dupe_of['title']}» — пропускаем "
                      f"(тот же факт, разная формулировка).")
                continue

            add_title_to_cache(data["title"])
            queue.append(data)
            added += 1
        except Exception as e:
            print(f"  item-{i}: пост-обработка упала ({e}), пропускаем.")
            continue

    save_queue(queue)
    print(f"  Добавлено {added} сценариев в очередь ({len(queue)}/{QUEUE_TARGET}).")


if __name__ == "__main__":
    main()
