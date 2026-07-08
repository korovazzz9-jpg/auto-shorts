"""Обнаружение НОВЫХ категорий тем (2026-07-08) — раз в месяц.

Отличие от discover_niche_topics.py: тот ищет выбросы ВНУТРИ наших 14 тем (семена поиска —
TOPICS_POOL), поэтому в принципе не может заметить целую новую категорию, которой у нас
нет. Этот скрипт делает ОТКРЫТЫЙ поиск (generic-запросы про факт-контент, без привязки к
нашим темам), смотрит на выбросы среди РЕАЛЬНО топовых по просмотрам роликов ниши и просит
Claude сгруппировать их в кандидатов-категории — которых ЕЩЁ НЕТ в TOPICS_POOL.

НЕ добавляет темы автоматически — только предлагает в Telegram, финальное решение и правка
TOPICS_POOL (generate_script.py) — вручную. Тот же принцип, что и весь проект: автоматизируем
обнаружение, человек остаётся на решении (см. README, «Месячные инсайты», «PR вместо auto-push»).

Запуск: monthly-topic-discovery.yml, 15-е число месяца, оба канала.
"""
import json
import os

from anthropic import Anthropic
from dotenv import load_dotenv

from config import CFG
from generate_script import BANNED_TOPICS, TOPICS_POOL
from notify import notify
from youtube_auth import get_client

load_dotenv()

OUTLIER_RATIO = 15.0   # тот же порог, что discover_niche_topics.py
MIN_VIEWS = 20000
MAX_RESULTS_PER_QUERY = 15
CANDIDATES_TO_SEND = 5

# Generic-запросы про факт-контент БЕЗ привязки к нашим темам — открытый срез ниши.
_BROAD_QUERIES = {
    "en": [
        "mind blowing facts shorts", "amazing facts shorts", "did you know shorts",
        "facts you didn't know shorts", "crazy facts shorts",
    ],
    "es": [
        "datos curiosos shorts", "sabías que shorts", "datos increíbles shorts",
        "curiosidades shorts", "dato del día shorts",
    ],
}


def _search_broad(youtube, query: str) -> list[dict]:
    try:
        resp = youtube.search().list(
            q=query, part="snippet", type="video", order="viewCount",
            videoDuration="short", maxResults=MAX_RESULTS_PER_QUERY,
            relevanceLanguage=CFG["lang_code"],
        ).execute()
    except Exception as e:
        print(f"  search failed for '{query}': {e}")
        return []
    return [
        {"video_id": i["id"]["videoId"], "channel_id": i["snippet"]["channelId"],
         "title": i["snippet"].get("title", "")}
        for i in resp.get("items", []) if i.get("id", {}).get("videoId")
    ]


def _fetch_stats(youtube, video_ids: list[str], channel_ids: list[str]) -> tuple[dict, dict]:
    views: dict[str, int] = {}
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        resp = youtube.videos().list(part="statistics", id=",".join(batch)).execute()
        for v in resp.get("items", []):
            views[v["id"]] = int(v["statistics"].get("viewCount", 0) or 0)
    subs: dict[str, int] = {}
    unique = list(dict.fromkeys(channel_ids))
    for i in range(0, len(unique), 50):
        batch = unique[i:i + 50]
        resp = youtube.channels().list(part="statistics", id=",".join(batch)).execute()
        for c in resp.get("items", []):
            subs[c["id"]] = int(c["statistics"].get("subscriberCount", 0) or 0)
    return views, subs


def _collect_outliers() -> list[dict]:
    """Открытый срез ниши: видео-выбросы по generic-запросам (не по нашим темам), с реальными
    цифрами (views/subs/ratio) — 2026-07-08: раньше в Telegram уходил только текст-вывод
    модели без чисел, пользователь не мог сам оценить силу сигнала."""
    youtube = get_client()
    queries = _BROAD_QUERIES.get(CFG["lang_code"], _BROAD_QUERIES["en"])
    outliers = []
    for q in queries:
        results = _search_broad(youtube, q)
        if not results:
            continue
        video_ids = [r["video_id"] for r in results]
        channel_ids = [r["channel_id"] for r in results]
        views, subs = _fetch_stats(youtube, video_ids, channel_ids)
        for r in results:
            v = views.get(r["video_id"], 0)
            s = subs.get(r["channel_id"], 0)
            if v >= MIN_VIEWS and s > 0 and v / s >= OUTLIER_RATIO:
                outliers.append({"title": r["title"], "video_id": r["video_id"],
                                  "views": v, "subs": s, "ratio": round(v / s, 1)})
    outliers.sort(key=lambda o: -o["ratio"])
    return outliers


def _propose_candidates(outliers: list[dict]) -> list[dict]:
    """Просит Claude сгруппировать заголовки-выбросы в кандидатов-категории, которых нет
    в TOPICS_POOL. Возвращает [] при отсутствии заголовков или отказе модели предложить
    что-то новое (честно — лучше пусто, чем натянутая категория).

    2026-07-08: первый прод-прогон дал 2 ложных срабатывания — EN «food and eating» (пример
    оказался роликом-РЕАКЦИЕЙ фуд-блогера на еду, не фактом), ES «home science experiments»
    (формат демо/туториала — мы физически не снимаем эксперименты, наш пайплайн — закадровая
    озвучка факта поверх стоковых клипов). Обе причины: (1) generic-запросы находят ЛЮБОЙ
    контент с высоким ratio, не только факт-нарратив; (2) промпт не проверял, подходит ли
    НАЙДЕННЫЙ ФОРМАТ под то, что умеет наш пайплайн. Добавлены явный запрет по формату и
    подъём минимума доказательств 2→3 (2 ролика — слишком слабый сигнал на открытом поиске,
    где шума больше, чем в discover_niche_topics.py с семенами внутри наших тем)."""
    if not outliers:
        return []
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=5)
    outliers_json = json.dumps(
        [{"title": o["title"], "views": o["views"], "subs": o["subs"], "ratio": o["ratio"]} for o in outliers],
        ensure_ascii=False,
    )
    prompt = (
        f"These are videos found via broad search queries in the short-video niche "
        f"(language: {CFG['script_language']}) with real view/subscriber numbers — NOT "
        "pre-verified to be fact-narration content, some may be reaction/challenge/vlog/tutorial "
        f"videos that just matched the search terms:\n{outliers_json}\n\n"
        f"Our channel's format: a SINGLE off-screen narrator voiceover delivering ONE surprising, "
        "mind-blowing fact per video, over generic stock b-roll footage (no on-camera host, no "
        "physical demonstration, no live reaction, no step-by-step tutorial — we cannot produce "
        "footage that requires filming a real demo, experiment, reaction, or challenge).\n"
        f"Our channel already covers these topic categories: {', '.join(TOPICS_POOL)}.\n"
        f"Banned (never propose): {', '.join(BANNED_TOPICS)} — audience can't follow specialist "
        "topics requiring technical background.\n\n"
        "Look for a NEW topic CATEGORY (not already covered above) that fits our EXACT format "
        "(narrated fact + generic stock footage) and shows up in AT LEAST 3 of the videos above "
        "as a genuine recurring pattern. REJECT any category whose evidence videos are actually "
        "reaction/challenge/tutorial/demo/vlog/prank videos, even if topically adjacent — check "
        "each evidence title's actual format, not just its topic word. When in doubt, reject.\n\n"
        "Respond strictly in JSON, no markdown wrapper, a list of 0-3 candidates (0 if nothing "
        "genuinely new, recurring in 3+ videos, AND format-compatible — do NOT invent a category "
        "from fewer than 3 videos, and do NOT propose a topic whose only evidence is a "
        "reaction/demo/tutorial-style video). Copy the title/views/ratio EXACTLY from the input "
        "for each evidence item — do not paraphrase or invent numbers: "
        '[{"category": "short phrase like existing pool", '
        '"evidence": [{"title": "...", "views": 0, "ratio": 0.0}, ...] (3+ items), '
        '"why": "one sentence, in Russian, must also state why the FORMAT fits (narratable as a fact, not a demo)"}]'
    )
    message = client.messages.create(
        model="claude-sonnet-4-6", max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
    start, end = raw.find("["), raw.rfind("]")
    try:
        candidates = json.loads(raw[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return []
    return [c for c in candidates if isinstance(c, dict) and c.get("category")
            and len(c.get("evidence", [])) >= 3][:CANDIDATES_TO_SEND]


def run() -> None:
    outliers = _collect_outliers()
    print(f"  Собрано {len(outliers)} видео-выбросов (открытый поиск).")
    candidates = _propose_candidates(outliers)
    if not candidates:
        print("  Новых категорий не найдено — пропускаем.")
        return

    lines = [f"🆕 [{CFG['channel_name']}] Кандидаты на новую тему (проверь и одобри вручную):"]
    for c in candidates:
        lines.append(f"\n**{c['category']}**\n{c.get('why', '')}")
        for ev in c.get("evidence", [])[:3]:
            lines.append(f"  {ev.get('ratio', '?')}× — {ev.get('views', '?'):,} views — «{ev.get('title', '')}»"
                          if isinstance(ev.get("views"), int) else f"  «{ev.get('title', '')}»")
    lines.append("\n\nЕсли одобряешь — добавь строку в TOPICS_POOL (generate_script.py) вручную.")
    notify("\n".join(lines))
    print(f"  Отправлено {len(candidates)} кандидатов в Telegram.")


if __name__ == "__main__":
    run()
