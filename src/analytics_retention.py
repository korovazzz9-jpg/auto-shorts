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
MAX_VIDEOS = 50  # сколько последних видео анализировать


def _iso8601_to_seconds(duration: str) -> int:
    """PT1M35S -> 95."""
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration or "")
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


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
            for tag in v["snippet"].get("tags", []):
                mt = TOPIC_TAG_RE.match(tag)
                if mt:
                    topic = mt.group(1).replace("_", " ")
                ml = LOOP_TAG_RE.match(tag)
                if ml:
                    loop = ml.group(1)
                mh = HOOK_TAG_RE.match(tag)
                if mh:
                    hook = mh.group(1)
            videos.append({
                "id": v["id"],
                "title": v["snippet"]["title"],
                "published": v["snippet"]["publishedAt"][:10],
                "published_full": v["snippet"]["publishedAt"],  # для слот-анализа (час UTC)
                "length": _iso8601_to_seconds(v["contentDetails"].get("duration", "")),
                "topic": topic or "—",
                "loop": loop or "?",
                "hook": hook or "—",
            })
    return videos


def _retention(analytics, video_ids: list[str], start: str, end: str) -> dict:
    """Возвращает {video_id: {pct, dur, views}}."""
    out = {}
    # Analytics API ограничивает длину фильтра — бьём по 200, у нас максимум 50.
    resp = analytics.reports().query(
        ids="channel==MINE",
        startDate=start,
        endDate=end,
        metrics="averageViewPercentage,averageViewDuration,views",
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


if __name__ == "__main__":
    main()
