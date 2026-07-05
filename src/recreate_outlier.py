"""Outlier-recreation (2026-07-05): раз в неделю самый мощный ЧУЖОЙ видео-выброс ниши
пересоздаётся СВОИМ скриптом (не копия — свой текст, структура и угол; факты не защищены
копирайтом, формулировки не заимствуются).

Зачем: аналог recycle_winners, но источник — вся ниша, а не сестринский канал. Выброс
с ratio 25-40× — это факт с ПОДТВЕРЖДЁННЫМ спросом, никакой лотереи дискавери.

Механика: берёт top_outliers из niche_signal_<channel>.json (пишет discover_niche_topics.py
тем же воркфлоу шагом раньше), пропускает уже пересозданные (recreated_niche_<channel>.json)
и дубли по сигнатуре имён/чисел (против очереди и опубликованных), генерирует свой скрипт
под якорь «вот заголовок перформящего видео конкурента — воспроизведи РЕАЛЬНЫЙ факт за ним
своими словами», кладёт В НАЧАЛО очереди с флагом niche_recreated (тег niche-recreation).

Запуск: шаг в discover-niche.yml (Пн, после discover), оба канала. 1 видео/канал/неделю.
"""
import json
import os

from anthropic import Anthropic
from dotenv import load_dotenv

from config import CFG, CHANNEL
from generate_script import (
    BASE_SYSTEM_PROMPT,
    EMOTIONAL_TONES,
    HOOK_TEMPLATES,
    LENGTH_INSTRUCTION,
    LOOP_INSTRUCTION,
    TITLE_OPENERS,
    _append_loop,
    _build_user_content,
    _niche_titles_for,
    _parse_response,
    _validate,
    pick_title_variant,
)
from prepare_batch import _is_duplicate, _signature, _signature_from_text
from recent_titles import add_title_to_cache, add_topic_to_cache, get_recent_titles, get_recent_video_texts
from script_queue import load_queue, save_queue

load_dotenv()

NICHE_SIGNAL_FILE = os.path.join(os.path.dirname(__file__), "..", f"niche_signal_{CHANNEL}.json")
RECREATED_FILE = os.path.join(os.path.dirname(__file__), "..", f"recreated_niche_{CHANNEL}.json")
MAX_RECREATED_MEMORY = 100  # сколько последних пересозданных video_id помним


def _load_recreated() -> list[str]:
    try:
        with open(RECREATED_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_recreated(ids: list[str]) -> None:
    with open(RECREATED_FILE, "w", encoding="utf-8") as f:
        json.dump(ids[-MAX_RECREATED_MEMORY:], f, ensure_ascii=False, indent=2)


def _pick_target() -> dict | None:
    """Самый мощный ещё не пересозданный выброс из niche_signal."""
    try:
        with open(NICHE_SIGNAL_FILE, encoding="utf-8") as f:
            outliers = json.load(f).get("top_outliers", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    done = set(_load_recreated())
    for o in outliers:
        if isinstance(o, dict) and o.get("video_id") and o["video_id"] not in done and o.get("title"):
            return o
    return None


def main() -> None:
    target = _pick_target()
    if not target:
        print("  Нет непересозданных выбросов — пропускаем.")
        return
    print(f"  Цель: «{target['title']}» ({target['ratio']}×, тема {target['topic']})")

    queue = load_queue()
    try:
        published_signatures = [_signature_from_text(t) for t in get_recent_video_texts(50)]
    except Exception:
        published_signatures = []

    # Дедуп ДО генерации — по заголовку цели (сигнатура слабее, чем по скрипту, но чужого
    # скрипта у нас нет; после генерации проверяем ещё раз полной сигнатурой).
    target_sig = _signature_from_text(target["title"])
    if any(len(target_sig & ps) >= 2 for ps in published_signatures):
        print("  Факт из цели уже выходил на канале — пропускаем, помечаем как пересозданный.")
        _save_recreated(_load_recreated() + [target["video_id"]])
        return

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

    title_instruction, title_variant = pick_title_variant()
    anchor = (
        "\n\nOVERRIDE — a competitor's Short with this exact title is massively overperforming "
        f"in our niche right now ({target['ratio']}x their subscriber base):\n"
        f"\"{target['title']}\"\n"
        "Recreate the REAL, verifiable fact behind that title natively for our channel — your "
        "own words, your own structure and angle, do NOT copy or paraphrase their title. If you "
        "are not confident you know the actual fact behind it, choose the closest strongly "
        "related verifiable fact on the same subject instead — never invent details."
    )
    user_content = _build_user_content(target["topic"], avoid_block, title_instruction) + anchor
    system_prompt = BASE_SYSTEM_PROMPT + "\n\n" + LOOP_INSTRUCTION + "\n\n" + LENGTH_INSTRUCTION

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=5)
    data, last_err = None, None
    for attempt in range(3):
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1600,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        try:
            data = _parse_response(message)
            break
        except json.JSONDecodeError as e:
            last_err = e
            print(f"  JSON parse failed (attempt {attempt + 1}/3): {e}; retrying...")
    if data is None:
        raise RuntimeError(f"Recreation JSON невалиден после 3 попыток: {last_err}")

    missing = [k for k in ("title", "script", "video_queries", "tags", "hashtags") if not data.get(k)]
    if missing:
        print(f"  В JSON нет полей {missing} — пропускаем прогон.")
        return

    problems = _validate(data)
    if problems:
        print(f"  Замечания валидации ({len(problems)}), беру как есть.")
    _append_loop(data)
    for key, known, default in (
        ("hook_template", HOOK_TEMPLATES, "other"),
        ("title_opener", TITLE_OPENERS, "other"),
        ("emotional_tone", EMOTIONAL_TONES, "other"),
    ):
        val = str(data.get(key, "")).strip().lower()
        data[key] = val if val in known else default
    if not str(data.get("hook_text", "")).strip():
        data["hook_text"] = data["title"]
    data["topic"] = target["topic"]
    data["title_variant"] = title_variant
    data["hashtag_position"] = "end"
    data["niche_styled"] = bool(_niche_titles_for(target["topic"]))  # промпт получал niche-титулы
    data["niche_recreated"] = True          # тег niche-recreation (pipeline.py)
    data["recreated_from_niche"] = target["video_id"]  # маркер происхождения в queue-файле

    # Дедуп ПОСЛЕ генерации — полной сигнатурой сгенерированного скрипта.
    sig = _signature(data)
    if any(_is_duplicate(data, q) for q in queue) or any(len(sig & ps) >= 2 for ps in published_signatures):
        print("  Сгенерированный факт — дубль очереди/опубликованного, пропускаем.")
        _save_recreated(_load_recreated() + [target["video_id"]])
        return

    add_title_to_cache(data["title"])
    add_topic_to_cache(target["topic"])
    queue.insert(0, data)  # в начало — выйдет в ближайший слот
    save_queue(queue)
    _save_recreated(_load_recreated() + [target["video_id"]])
    print(f"  + «{data['title']}» в начало очереди (из выброса {target['ratio']}×).")


if __name__ == "__main__":
    main()
