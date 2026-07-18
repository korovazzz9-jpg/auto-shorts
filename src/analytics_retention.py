"""Retention-аналитика: тянет avg view duration и % досматривания на каждое видео
из YouTube Analytics API и сопоставляет с длиной видео, темой и (для Shorts) типом.

Зачем: до этого мы тюнили hook/loop/bait вслепую. Здесь — данные, по которым видно,
что реально держит зрителя: какие темы, какая длина, какой процент досмотра.

Запуск:
  python src/analytics_retention.py            # EN-канал
  CHANNEL=es python src/analytics_retention.py # ES-канал

Метрики (per-video):
  averageViewPercentage — % видео, который досматривают (ГЛАВНЫЙ сигнал retention для Shorts)
  averageViewDuration   — сколько секунд в среднем смотрят
  views                 — просмотры (для веса)
"""
import os
import re
from datetime import date, timedelta

from dotenv import load_dotenv

from config import CFG
from youtube_auth import get_analytics_client, get_client

load_dotenv()

TOPIC_TAG_RE = re.compile(r"^topic-(.+)$")
LOOP_TAG_RE = re.compile(r"^loop-(yes|no)$")
HOOK_TAG_RE = re.compile(r"^hook-(.+)$")
TITLE_VARIANT_TAG_RE = re.compile(r"^title-(seo|narrative)$")  # A/B заголовков, см. generate_script.py
OPENER_TAG_RE = re.compile(r"^opener-(.+)$")  # ротация заголовков, см. TITLE_OPENERS
TONE_TAG_RE = re.compile(r"^tone-(.+)$")      # эмоциональный тон, см. EMOTIONAL_TONES
COLOR_TAG_RE = re.compile(r"^color-(.+)$")    # цвет субтитров, см. CAPTION_COLORS в build_video.py
VOICE_TAG_RE = re.compile(r"^voice-(.+)$")    # TTS-голос, см. voices в config.py
FORMAT_TAG_RE = re.compile(r"^format-(.+)$")  # тип структуры скрипта, см. STRUCTURES в generate_script.py
TITLESTYLE_TAG_RE = re.compile(r"^titlestyle-(question|statement)$")  # вопрос vs утверждение, 2026-07-17
TITLEINTENSITY_TAG_RE = re.compile(r"^titleintensity-(mild|extreme)$")  # сила неожиданности, 2026-07-18
HOOKSTYLE_TAG_RE = re.compile(r"^hookstyle-(color|plain)$")  # раскраска хук-плашки, 2026-07-18
CTA_TAG_RE = re.compile(r"^cta-(schedule|topic|pair|generic)$")  # тип CTA-фразы, 2026-07-18
PAIR_A_TAG = "pair-a"  # часть A пары (несёт подписной тизер с 2026-07-10, см. paired_facts)
PAIR_B_TAG = "pair-b"  # часть B (резолюция пары)
NICHE_STYLED_TAG = "niche-styled"             # промпт получал заголовки чужих выбросов по теме
TOPICAL_TAG = "topical-onthisday"             # факт с привязкой к дате публикации
MAX_VIDEOS = 50  # сколько последних видео анализировать


def _iso8601_to_seconds(duration: str) -> int:
    """PT1M35S -> 95."""
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration or "")
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def retention_threshold(length_seconds: int) -> float:
    """Порог % досмотра, ниже которого YouTube резко сокращает раздачу Shorts (данные
    индустриальных бенчмарков 2026, не официальный YouTube-документ, но воспроизводимая
    цифра в нескольких независимых источниках): 65% для <30с, 50% для 30-60с. Абсолютное
    число менее важно, чем сам факт порога — это explore-and-exploit тест на малой
    аудитории, не постепенная шкала."""
    return 65.0 if length_seconds < 30 else 50.0


def _recent_videos(youtube) -> list[dict]:
    channels = youtube.channels().list(part="contentDetails", mine=True).execute()
    items = channels.get("items", [])
    if not items:
        return []
    uploads_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    video_ids, page_token = [], None
    while len(video_ids) < MAX_VIDEOS:
        resp = youtube.playlistItems().list(
            part="snippet", playlistId=uploads_id, maxResults=50, pageToken=page_token
        ).execute()
        video_ids += [i["snippet"]["resourceId"]["videoId"] for i in resp.get("items", [])]
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    video_ids = video_ids[:MAX_VIDEOS]

    videos = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        resp = youtube.videos().list(part="snippet,contentDetails", id=",".join(batch)).execute()
        for v in resp.get("items", []):
            topic = None
            loop = None
            hook = None
            title_variant = None
            opener = None
            tone = None
            color = None
            voice = None
            structure = None
            title_style = None
            title_intensity = None
            hook_style = None
            cta_kind = None
            niche = "plain"
            topical = "no"
            pair = "no"
            for tag in v["snippet"].get("tags", []):
                if tag == NICHE_STYLED_TAG:
                    niche = "styled"
                if tag == TOPICAL_TAG:
                    topical = "yes"
                if tag == PAIR_A_TAG:
                    pair = "a"
                if tag == PAIR_B_TAG:
                    pair = "b"
                mt = TOPIC_TAG_RE.match(tag)
                if mt:
                    topic = mt.group(1).replace("_", " ")
                ml = LOOP_TAG_RE.match(tag)
                if ml:
                    loop = ml.group(1)
                mh = HOOK_TAG_RE.match(tag)
                if mh:
                    hook = mh.group(1)
                mv = TITLE_VARIANT_TAG_RE.match(tag)
                if mv:
                    title_variant = mv.group(1)
                mo = OPENER_TAG_RE.match(tag)
                if mo:
                    opener = mo.group(1)
                mtone = TONE_TAG_RE.match(tag)
                if mtone:
                    tone = mtone.group(1)
                mcolor = COLOR_TAG_RE.match(tag)
                if mcolor:
                    color = mcolor.group(1)
                mvoice = VOICE_TAG_RE.match(tag)
                if mvoice:
                    voice = mvoice.group(1)
                mformat = FORMAT_TAG_RE.match(tag)
                if mformat:
                    structure = mformat.group(1)
                mts = TITLESTYLE_TAG_RE.match(tag)
                if mts:
                    title_style = mts.group(1)
                mti = TITLEINTENSITY_TAG_RE.match(tag)
                if mti:
                    title_intensity = mti.group(1)
                mhs = HOOKSTYLE_TAG_RE.match(tag)
                if mhs:
                    hook_style = mhs.group(1)
                mcta = CTA_TAG_RE.match(tag)
                if mcta:
                    cta_kind = mcta.group(1)
            videos.append({
                "id": v["id"],
                "title": v["snippet"]["title"],
                "published": v["snippet"]["publishedAt"][:10],
                "published_full": v["snippet"]["publishedAt"],  # для слот-анализа (час UTC)
                "length": _iso8601_to_seconds(v["contentDetails"].get("duration", "")),
                "topic": topic or "—",
                "loop": loop or "?",
                "hook": hook or "—",
                "title_variant": title_variant or "—",
                "title_opener": opener or "—",
                "emotional_tone": tone or "—",
                "caption_color": color or "—",
                "voice": voice or "—",
                "structure": structure or "—",
                "title_style": title_style or "—",
                "title_intensity": title_intensity or "—",
                "hook_style": hook_style or "—",
                "cta_kind": cta_kind or "—",
                "niche": niche,
                "topical": topical,
                "pair": pair,
            })
    return videos


def _retention_curve(analytics, video_id: str, start: str, end: str) -> list[tuple[float, float]]:
    """Посекундная (точнее — по 1%-долям длины видео) кривая retention для ОДНОГО видео.
    В отличие от averageViewPercentage (одно число на видео) показывает, В КАКОЙ МОМЕНТ
    зритель отваливается — на хуке, на reveal, на twist. elapsedVideoTimeRatio — эндпоинт
    Analytics API, который принимает фильтр только по одному video== за раз (не батчится),
    поэтому кривую тянем по видео отдельно, не для всех 50 разом.
    Возвращает [(elapsed_ratio 0..1, audience_watch_ratio), ...], отсортировано по времени."""
    resp = analytics.reports().query(
        ids="channel==MINE",
        startDate=start,
        endDate=end,
        metrics="audienceWatchRatio",
        dimensions="elapsedVideoTimeRatio",
        filters=f"video=={video_id}",
    ).execute()
    rows = resp.get("rows", []) or []
    return sorted((float(r[0]), float(r[1])) for r in rows)


def biggest_drop(curve: list[tuple[float, float]], video_length: int) -> dict | None:
    """Сегмент кривой с наибольшим падением audienceWatchRatio — где именно теряем зрителя.
    Возвращает {"second": ~секунда видео, "drop_pct": падение в п.п.} или None (мало точек)."""
    if len(curve) < 2 or video_length <= 0:
        return None
    best = None
    for (t0, r0), (t1, r1) in zip(curve, curve[1:]):
        drop = r0 - r1
        if drop > 0 and (best is None or drop > best[1]):
            best = (t1, drop)
    if not best:
        return None
    ratio, drop = best
    return {"second": round(ratio * video_length), "drop_pct": round(drop * 100, 1)}


def _retention(analytics, video_ids: list[str], start: str, end: str) -> dict:
    """Возвращает {video_id: {pct, dur, views, subs}}. subs = subscribersGained (2026-07-10):
    сколько зрителей подписалось С ЭТОГО видео — нужен для замера подписного тизера пар
    (pair_cta_phrases); тот же самый запрос, доп. квоты не стоит."""
    out = {}
    # Analytics API ограничивает длину фильтра — бьём по 200, у нас максимум 50.
    resp = analytics.reports().query(
        ids="channel==MINE",
        startDate=start,
        endDate=end,
        metrics="averageViewPercentage,averageViewDuration,views,subscribersGained",
        dimensions="video",
        filters="video==" + ",".join(video_ids),
        maxResults=len(video_ids),
    ).execute()
    headers = [h["name"] for h in resp.get("columnHeaders", [])]
    for row in resp.get("rows", []):
        rec = dict(zip(headers, row))
        out[rec["video"]] = {
            "pct": rec.get("averageViewPercentage", 0),
            "dur": rec.get("averageViewDuration", 0),
            "views": rec.get("views", 0),
            "subs": rec.get("subscribersGained", 0),
        }
    return out


def main() -> None:
    youtube = get_client()
    analytics = get_analytics_client()

    videos = _recent_videos(youtube)
    if not videos:
        print("Нет видео.")
        return

    start = min(v["published"] for v in videos)
    end = date.today().isoformat()
    ret = _retention(analytics, [v["id"] for v in videos], start, end)

    for v in videos:
        r = ret.get(v["id"], {})
        v["pct"] = float(r.get("pct", 0) or 0)
        v["dur"] = float(r.get("dur", 0) or 0)
        v["views"] = int(r.get("views", 0) or 0)

    print(f"\n=== {CFG['channel_name']}: retention по видео (сорт. по % досмотра) ===\n")
    print(f"{'%досм':>6} {'сек':>5} {'длина':>5} {'views':>7}  тема — заголовок")
    for v in sorted(videos, key=lambda x: -x["pct"]):
        print(f"{v['pct']:6.1f} {v['dur']:5.0f} {v['length']:5}s {v['views']:7}  "
              f"{v['topic']:<22} {v['title'][:45]}")

    # Агрегаты по теме
    by_topic: dict[str, list[float]] = {}
    for v in videos:
        by_topic.setdefault(v["topic"], []).append(v["pct"])
    print("\n=== Средний % досмотра по теме ===\n")
    for topic, pcts in sorted(by_topic.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])):
        print(f"{sum(pcts) / len(pcts):6.1f}%  ({len(pcts):2} видео)  {topic}")

    # Агрегаты по длине
    buckets = {"<30s": [], "30-40s": [], "40-50s": [], "50s+": []}
    for v in videos:
        L = v["length"]
        key = "<30s" if L < 30 else "30-40s" if L < 40 else "40-50s" if L < 50 else "50s+"
        buckets[key].append(v["pct"])
    print("\n=== Средний % досмотра по длине ===\n")
    for key, pcts in buckets.items():
        if pcts:
            print(f"{sum(pcts) / len(pcts):6.1f}%  ({len(pcts):2} видео)  {key}")

    # #2 Средний % досмотра по хук-шаблону — чтобы взвешивать сильнейшие хуки.
    by_hook: dict[str, list[float]] = {}
    for v in videos:
        if v["pct"] > 0:  # видео без данных (свежие) не занижают средние нулями
            by_hook.setdefault(v["hook"], []).append(v["pct"])
    print("\n=== Средний % досмотра по хук-шаблону ===\n")
    for hook, pcts in sorted(by_hook.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])):
        print(f"{sum(pcts) / len(pcts):6.1f}%  ({len(pcts):2} видео)  {hook}")

    # Главное сравнение: петля vs без петли (только видео с проставленным тегом)
    by_loop: dict[str, list[float]] = {"yes": [], "no": []}
    for v in videos:
        if v["loop"] in by_loop and v["pct"] > 0:
            by_loop[v["loop"]].append(v["pct"])
    print("\n=== Петля vs без петли (средний % досмотра) ===\n")
    for key, label in (("yes", "с петлёй "), ("no", "без петли")):
        pcts = by_loop[key]
        if pcts:
            print(f"{sum(pcts) / len(pcts):6.1f}%  ({len(pcts):2} видео)  {label}")
        else:
            print(f"   —    ( 0 видео)  {label} (ещё нет данных)")


def _print_curve(video_id: str) -> None:
    """Ручной разбор одного видео: python analytics_retention.py <video_id>."""
    youtube = get_client()
    analytics = get_analytics_client()
    info = youtube.videos().list(part="snippet,contentDetails", id=video_id).execute()["items"][0]
    length = _iso8601_to_seconds(info["contentDetails"]["duration"])
    published = info["snippet"]["publishedAt"][:10]
    curve = _retention_curve(analytics, video_id, published, date.today().isoformat())
    if not curve:
        print("Нет данных retention-кривой (видео слишком свежее или мало просмотров).")
        return
    print(f"\n=== Retention-кривая: {info['snippet']['title']} ({length}s) ===\n")
    for ratio, watch in curve:
        bar = "#" * int(watch * 40)
        print(f"{ratio*100:5.0f}% ({round(ratio*length):3}s)  {watch*100:5.1f}%  {bar}")
    drop = biggest_drop(curve, length)
    if drop:
        print(f"\nСамый большой обрыв: ~{drop['second']}s, падение {drop['drop_pct']} п.п.")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        _print_curve(sys.argv[1])
    else:
        main()
