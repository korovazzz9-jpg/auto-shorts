"""Кросс-канальное переиспользование победителей: топ-факты канала-ИСТОЧНИКА пересоздаются
на языке канала-ЦЕЛИ (CHANNEL) через Batch API (−50%) и кладутся В НАЧАЛО его очереди.

Зачем: EN и ES генерят факты независимо, хотя проверенный на одном канале факт — это
готовый победитель без риска «не зашло» (дискавери нового факта — главная лотерея).
У ES вдвое меньше выпущенных видео — ему есть куда впитывать EN-победителей, и наоборот.

Механика:
  1. Берём Shorts канала-источника за последние SOURCE_LOOKBACK видео (не моложе 3 дней —
     просмотрам надо накопиться; сериальные части и лонгформ исключаются).
  2. Победители = выше 75-го перцентиля по просмотрам, топ-MAX_RECYCLED по убыванию.
  3. Дедуп против цели: очередь + последние опубликованные видео (по сигнатуре
     собственных имён/чисел из prepare_batch._is_duplicate — «тот же факт, другая
     формулировка» ловится, перевод на другой язык — нет, поэтому сигнатура работает
     по именам собственным и числам, они переживают перевод).
  4. Пересоздаём (НЕ дословный перевод) через Batch API с якорем на проверенный факт.
  5. Готовые кладём в НАЧАЛО очереди цели (публикуются раньше свежесгенерённых).

Запуск (еженедельный, recycle-winners.yml):
  CHANNEL=es SOURCE_YT_REFRESH_TOKEN=<EN token> python recycle_winners.py   # EN -> ES
  CHANNEL=en SOURCE_YT_REFRESH_TOKEN=<ES token> python recycle_winners.py   # ES -> EN
"""
import datetime
import os
import time

from anthropic import Anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from config import CFG
from generate_script import (
    BASE_SYSTEM_PROMPT,
    EMOTIONAL_TONES,
    HOOK_TEMPLATES,
    LENGTH_INSTRUCTION,
    LOOP_INSTRUCTION,
    TITLE_OPENERS,
    _append_loop,
    _build_user_content,
    _drop_corrupted,
    _enrich_tags_with_suggestions,
    _parse_response,
    _validate,
    pick_title_variant,
)
from prepare_batch import _is_duplicate
from recent_titles import add_title_to_cache
from script_queue import load_queue, save_queue
from youtube_auth import SCOPES, get_client

load_dotenv()

SOURCE_LOOKBACK = 40      # сколько последних видео источника смотрим
MIN_AGE_DAYS = 3          # моложе — просмотры ещё не накопились, рейтинг врёт
MAX_RECYCLED = 5          # 3→5 (2026-07-04): отдача ES от EN-победителей 2×, Batch API тянет
MAX_SHORT_SECONDS = 65    # отсекаем лонгформ по длительности
POLL_INTERVAL = 20
POLL_TIMEOUT = 1800


def _source_client():
    """YouTube-клиент канала-ИСТОЧНИКА (отдельный refresh token, те же client id/secret)."""
    creds = Credentials(
        token=None,
        refresh_token=os.environ["SOURCE_YT_REFRESH_TOKEN"],
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    return build("youtube", "v3", credentials=creds)


def _iso_duration_seconds(duration: str) -> int:
    import re
    # Часы обязательны в паттерне: без (\d+)H строка "PT1H..." не матчила ни одну группу
    # и возвращала 0 сек — часовое видео прошло бы фильтр "только Shorts <= 65с".
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration or "")
    if not m:
        return 10 ** 6
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def _fetch_videos(youtube, max_results: int, with_stats: bool) -> list[dict]:
    """Последние видео канала: title/description/tags (+views/duration/published для источника)."""
    ch = youtube.channels().list(part="contentDetails", mine=True).execute()
    items = ch.get("items", [])
    if not items:
        return []
    uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    ids, token = [], None
    while len(ids) < max_results:
        resp = youtube.playlistItems().list(
            part="snippet", playlistId=uploads, maxResults=50, pageToken=token
        ).execute()
        ids += [i["snippet"]["resourceId"]["videoId"] for i in resp.get("items", [])]
        token = resp.get("nextPageToken")
        if not token:
            break
    ids = ids[:max_results]

    part = "snippet,statistics,contentDetails" if with_stats else "snippet"
    out = []
    for i in range(0, len(ids), 50):
        resp = youtube.videos().list(part=part, id=",".join(ids[i:i + 50])).execute()
        for v in resp.get("items", []):
            item = {
                "id": v["id"],
                "title": v["snippet"]["title"],
                "description": v["snippet"].get("description", ""),
                "tags": v["snippet"].get("tags", []),
            }
            if with_stats:
                item["views"] = int(v["statistics"].get("viewCount", 0))
                item["seconds"] = _iso_duration_seconds(v["contentDetails"].get("duration", ""))
                item["published"] = v["snippet"]["publishedAt"]
            out.append(item)
    return out


def _extract_script(description: str) -> str:
    """Достаёт озвученный скрипт из описания: самый длинный блок без ссылок/CTA/хэштегов
    (описание = search_summary \\n\\n script \\n\\n ▶ воронка \\n\\n #хэштеги)."""
    blocks = [b.strip() for b in description.split("\n\n") if b.strip()]
    blocks = [b for b in blocks
              if not b.startswith(("▶", "#")) and "http" not in b]
    return max(blocks, key=len) if blocks else ""


def _pick_winners(source_videos: list[dict]) -> list[dict]:
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(days=MIN_AGE_DAYS)).isoformat()
    pool = [
        v for v in source_videos
        if v["views"] > 0
        and v["seconds"] <= MAX_SHORT_SECONDS
        and v["published"] < cutoff
        and not any(t.startswith("series-part-") for t in v["tags"])
    ]
    if len(pool) < 8:  # мало данных — перцентиль не о чем
        print(f"  Мало видео с данными у источника ({len(pool)}), пропускаем прогон.")
        return []
    views = sorted(v["views"] for v in pool)
    p75 = views[int(len(views) * 0.75)]
    winners = sorted((v for v in pool if v["views"] >= p75), key=lambda v: -v["views"])
    return winners[:MAX_RECYCLED]


def _source_topic(video: dict) -> str:
    for t in video["tags"]:
        if t.startswith("topic-"):
            return t[len("topic-"):].replace("_", " ")
    return "general knowledge"


def main() -> None:
    if not os.environ.get("SOURCE_YT_REFRESH_TOKEN"):
        raise RuntimeError("SOURCE_YT_REFRESH_TOKEN не задан — неоткуда брать победителей.")

    print(f"  Цель: {CFG['channel_name']}. Собираем победителей источника...")
    winners = _pick_winners(_fetch_videos(_source_client(), SOURCE_LOOKBACK, with_stats=True))
    if not winners:
        return

    # Дедуп против цели: очередь + последние опубликованные (title+script источника против
    # title+description цели — сигнатура по именам собственным/числам переживает перевод).
    queue = load_queue()
    try:
        target_published = [
            {"title": v["title"], "script": v["description"]}
            for v in _fetch_videos(get_client(), SOURCE_LOOKBACK, with_stats=False)
        ]
    except Exception as e:
        print(f"  Не удалось получить опубликованное цели ({e}) — дедуп только по очереди.")
        target_published = []

    candidates = []
    for w in winners:
        src_item = {"title": w["title"], "script": _extract_script(w["description"])}
        against = queue + target_published
        dupe = next((x for x in against if _is_duplicate(src_item, x)), None)
        if dupe:
            print(f"  «{w['title']}» уже есть у цели ({dupe['title'][:50]}...) — пропускаем.")
            continue
        candidates.append((w, src_item))

    if not candidates:
        print("  Все победители уже есть у цели — нечего пересоздавать.")
        return
    print(f"  Пересоздаём {len(candidates)} победителей через Batch API...")

    system_prompt = BASE_SYSTEM_PROMPT + "\n\n" + LOOP_INSTRUCTION + "\n\n" + LENGTH_INSTRUCTION
    requests_, title_variants = [], []
    for i, (w, src_item) in enumerate(candidates):
        anchor = (
            "\n\nOVERRIDE — DO NOT invent a new fact. Recreate THIS exact proven fact (a top "
            "performer on our sister channel) natively for this channel's audience — same core "
            "fact, same structure of surprise, NOT a literal word-for-word translation:\n"
            f"Source title: {w['title']}\n"
            f"Source script: {src_item['script']}"
        )
        title_instruction, title_variant = pick_title_variant()
        title_variants.append(title_variant)
        requests_.append(Request(
            custom_id=f"recycle-{i}",
            params=MessageCreateParamsNonStreaming(
                model="claude-sonnet-4-6",
                max_tokens=1600,
                system=system_prompt,
                messages=[{"role": "user",
                           "content": _build_user_content(_source_topic(w), "", title_instruction) + anchor}],
            ),
        ))

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=5)
    batch = client.messages.batches.create(requests=requests_)
    print(f"  Batch создан: {batch.id}, ждём (до {POLL_TIMEOUT}s)...")
    waited = 0
    while waited < POLL_TIMEOUT:
        batch = client.messages.batches.retrieve(batch.id)
        if batch.processing_status == "ended":
            break
        time.sleep(POLL_INTERVAL)
        waited += POLL_INTERVAL
    else:
        print(f"  Batch не успел ({batch.id} хранится 29 дней) — доберём в следующий прогон.")
        return

    results = {r.custom_id: r for r in client.messages.batches.results(batch.id)}
    added = 0
    for i, (w, _) in enumerate(candidates):
        r = results.get(f"recycle-{i}")
        if not r or r.result.type != "succeeded":
            print(f"  recycle-{i}: batch-запрос не удался, пропускаем.")
            continue
        try:
            data = _parse_response(r.result.message)
            missing = [k for k in ("title", "script", "video_queries", "tags", "hashtags")
                       if not data.get(k)]
            if missing:
                print(f"  recycle-{i}: нет полей {missing}, пропускаем.")
                continue
            problems = _validate(data)
            if problems:
                print(f"  recycle-{i}: замечания валидации ({len(problems)}), беру как есть.")
            _append_loop(data)
            ht = str(data.get("hook_template", "")).strip().lower()
            data["hook_template"] = ht if ht in HOOK_TEMPLATES else "other"
            to = str(data.get("title_opener", "")).strip().lower()
            data["title_opener"] = to if to in TITLE_OPENERS else "other"
            et = str(data.get("emotional_tone", "")).strip().lower()
            data["emotional_tone"] = et if et in EMOTIONAL_TONES else "other"
            if not str(data.get("hook_text", "")).strip():
                data["hook_text"] = data["title"]
            data["topic"] = _source_topic(w)
            data["title_variant"] = title_variants[i]
            data["hashtag_position"] = "end"
            data["recycled_from"] = w["id"]  # маркер происхождения (виден в queue-файле)
            # Пост-обработка тегов как в live-пути (2026-07-10): U+FFFD-фильтр + автокомплит.
            if isinstance(data.get("tags"), list):
                data["tags"] = _enrich_tags_with_suggestions(_drop_corrupted(data["tags"]))
            if isinstance(data.get("hashtags"), list):
                data["hashtags"] = _drop_corrupted(data["hashtags"])

            if any(_is_duplicate(data, q) for q in queue):
                print(f"  recycle-{i}: дубль с очередью после генерации — пропускаем.")
                continue

            add_title_to_cache(data["title"])
            queue.insert(added, data)  # победители — в начало очереди, публикуются раньше
            added += 1
            print(f"  + «{data['title']}» (из «{w['title']}», {w['views']} views)")
        except Exception as e:
            print(f"  recycle-{i}: пост-обработка упала ({e}), пропускаем.")

    save_queue(queue)
    print(f"  Добавлено {added} пересозданных победителей в начало очереди ({len(queue)} всего).")


if __name__ == "__main__":
    from notify import guard_main
    guard_main(f"recycle-winners {os.environ.get('CHANNEL', 'en')}", main)
