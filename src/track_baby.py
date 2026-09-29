"""Трекер статистики канала «малышка и щенок» (baby, англоязычные шортсы из репозитория AI,
video_gen/ui/_cp77_series/baby01/shorts.json). Раз в день снимает по всем роликам канала:
просмотры, лайки, комментарии (Data API), средний % и время досмотра, подписки с ролика
(Analytics API), показы и CTR обложки — если Analytics API их отдаёт.

Пишет:
  stats/baby/daily.csv   — снимок на каждый день (дописывается; повторный запуск в тот же день
                           заменяет строки этого дня, дублей нет);
  stats/baby/videos.csv  — последнее состояние каждого ролика;
  stats/baby/mapping.csv — video_id,name: какая завязка снята в ролике. Ручные строки главнее;
                           ролики с меткой в тегах (`s-<name>`) или описании (`#s:<name>`)
                           дописываются сюда сами (см. docs/SETUP_BABY.md).

Выключен, пока нет секрета: без YT_TOKEN_BABY пишет «канал не подключён» и выходит с кодом 0.

Запуск: python track_baby.py   (из каталога src; CHANNEL не выставлять — у канала нет конфига
в config.py, токен и OAuth-клиент берутся по имени канала baby, см. youtube_auth._client_pair).
"""
import csv
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATS_DIR = ROOT / "stats" / "baby"
CHANNEL_KEY = "baby"
TOKEN_ENV = "YT_TOKEN_BABY"
NOT_CONNECTED = "канал не подключён: секрета YT_TOKEN_BABY нет — трекер выключен."
MAX_VIDEOS = 500  # вся серия — 40 завязок; запас на пересъёмки и повторы

DAILY_FIELDS = ["date", "video_id", "name", "published_at", "age_hours", "views", "likes",
                "comments", "avg_view_pct", "avg_view_sec", "subs_gained", "impressions", "ctr"]
VIDEO_FIELDS = ["video_id", "name", "type", "risk", "title", "published_at", "duration_s",
                "views", "likes", "comments", "avg_view_pct", "avg_view_sec", "subs_gained",
                "impressions", "ctr", "updated_at"]
MAPPING_FIELDS = ["video_id", "name"]

RETENTION_METRICS = "averageViewPercentage,averageViewDuration,subscribersGained"
# Показы и CTR обложки. Имена метрик в Analytics API вживую НЕ проверены (канала ещё нет):
# если API их не знает, запрос падает 400 — тогда колонки остаются пустыми, остальное пишется.
IMPRESSION_METRICS = "videoThumbnailImpressions,videoThumbnailImpressionsClickRate"

TAG_RE = re.compile(r"^s[-:]([a-z0-9_]+)$")
DESCRIPTION_RE = re.compile(r"#s:([a-z0-9_]+)")


# ---------- CSV ----------

def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    """Атомарно: сначала .tmp, потом replace — оборванный раннер не оставит полфайла."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: "" if row.get(k) is None else row.get(k) for k in fields})
    tmp.replace(path)


def upsert_daily(path: Path, date: str, rows: list[dict]) -> list[dict]:
    """Дописывает снимок дня. Строки (date, video_id), уже записанные сегодня, заменяются новыми —
    повторный запуск за день обновляет цифры, а не плодит дубли. Прошлые дни не трогаются."""
    fresh = {r["video_id"] for r in rows}
    kept = [r for r in read_csv(path) if not (r["date"] == date and r["video_id"] in fresh)]
    merged = sorted(kept + [{**r, "date": date} for r in rows], key=lambda r: (r["date"], r["video_id"]))
    write_csv(path, DAILY_FIELDS, merged)
    return merged


def load_types(stats_dir: Path) -> dict:
    """name -> {type, risk} из shorts_types.csv (выгрузка shorts.json репозитория AI)."""
    return {r["name"]: {"type": r.get("type", ""), "risk": r.get("risk", "")}
            for r in read_csv(stats_dir / "shorts_types.csv") if r.get("name")}


# ---------- сопоставление ролика с завязкой ----------

def name_from_video(video: dict) -> str | None:
    """Метка завязки: тег `s-<name>` (зрителю не виден) или `#s:<name>` в описании."""
    for tag in video.get("tags") or []:
        m = TAG_RE.match(str(tag).strip().lower())
        if m:
            return m.group(1)
    m = DESCRIPTION_RE.search(video.get("description") or "")
    return m.group(1) if m else None


def resolve_names(videos: list[dict], mapping_rows: list[dict]) -> tuple[dict, list[dict]]:
    """{video_id: name} и новые строки mapping.csv. Ручная строка главнее метки в ролике."""
    names = {r["video_id"]: r["name"] for r in mapping_rows if r.get("video_id") and r.get("name")}
    added = []
    for v in videos:
        if v["id"] in names:
            continue
        name = name_from_video(v)
        if name:
            names[v["id"]] = name
            added.append({"video_id": v["id"], "name": name})
    return names, added


# ---------- YouTube ----------

def _num(value, cast=float):
    try:
        return cast(value)
    except (TypeError, ValueError):
        return None


def fetch_videos(youtube, limit: int = MAX_VIDEOS) -> list[dict]:
    """Все загрузки канала: заголовок, дата, длина, теги, описание и счётчики Data API."""
    from analytics_retention import _iso8601_to_seconds, upload_video_ids

    ids = upload_video_ids(youtube, limit)
    videos = []
    for i in range(0, len(ids), 50):
        resp = youtube.videos().list(part="snippet,statistics,contentDetails",
                                     id=",".join(ids[i:i + 50])).execute()
        for item in resp.get("items", []):
            snippet, stats = item.get("snippet", {}), item.get("statistics", {})
            videos.append({
                "id": item["id"],
                "title": snippet.get("title", ""),
                "published_at": snippet.get("publishedAt", ""),
                "tags": snippet.get("tags", []),
                "description": snippet.get("description", ""),
                "duration_s": _iso8601_to_seconds(item.get("contentDetails", {}).get("duration", "")),
                # likeCount/commentCount нет в ответе, если автор скрыл их или выключил комменты
                "views": _num(stats.get("viewCount"), int),
                "likes": _num(stats.get("likeCount"), int),
                "comments": _num(stats.get("commentCount"), int),
            })
    return videos


def fetch_analytics(analytics, ids: list[str], start: str, end: str) -> tuple[dict, bool]:
    """({video_id: {avg_view_pct, avg_view_sec, subs_gained, impressions, ctr}}, есть_ли_показы).
    Ошибка запроса показов не роняет трекер: без них CSV пишется с пустыми колонками."""
    from analytics_retention import video_report

    out = {vid: {} for vid in ids}
    if not ids:
        return out, False
    for vid, rec in video_report(analytics, ids, start, end, RETENTION_METRICS).items():
        out.setdefault(vid, {}).update(
            avg_view_pct=_num(rec.get("averageViewPercentage")),
            avg_view_sec=_num(rec.get("averageViewDuration")),
            subs_gained=_num(rec.get("subscribersGained"), int))
    try:
        impressions = video_report(analytics, ids, start, end, IMPRESSION_METRICS)
    except Exception as exc:  # HttpError 400 «Unknown identifier» — метрики нет в API
        print(f"  показы/CTR недоступны: {type(exc).__name__}: {str(exc)[:160]}")
        return out, False
    names = IMPRESSION_METRICS.split(",")
    for vid, rec in impressions.items():
        out.setdefault(vid, {}).update(impressions=_num(rec.get(names[0]), int), ctr=_num(rec.get(names[1])))
    return out, True


# ---------- прогон ----------

def _age_hours(published_at: str, now: datetime) -> float | None:
    try:
        published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return round((now - published).total_seconds() / 3600, 1)


def track(youtube, analytics, stats_dir: Path = STATS_DIR, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    today = now.date().isoformat()
    videos = fetch_videos(youtube)
    mapping_rows = read_csv(stats_dir / "mapping.csv")
    names, added = resolve_names(videos, mapping_rows)
    if added:
        write_csv(stats_dir / "mapping.csv", MAPPING_FIELDS, mapping_rows + added)
    types = load_types(stats_dir)
    unknown = sorted({n for n in names.values() if types and n not in types})
    for n in unknown:
        print(f"  [!] завязки «{n}» нет в shorts_types.csv — проверьте метку/mapping.csv")

    start = min((v["published_at"][:10] for v in videos if v["published_at"]), default=today)
    metrics, has_impressions = fetch_analytics(analytics, [v["id"] for v in videos], start, today)

    daily, latest = [], []
    for v in videos:
        m = metrics.get(v["id"], {})
        name = names.get(v["id"], "")
        row = {"video_id": v["id"], "name": name, "published_at": v["published_at"],
               "age_hours": _age_hours(v["published_at"], now), "views": v["views"],
               "likes": v["likes"], "comments": v["comments"], **m}
        daily.append(row)
        latest.append({**row, "title": v["title"], "duration_s": v["duration_s"],
                       "type": types.get(name, {}).get("type", ""),
                       "risk": types.get(name, {}).get("risk", ""),
                       "updated_at": now.isoformat(timespec="seconds")})
    upsert_daily(stats_dir / "daily.csv", today, daily)
    latest.sort(key=lambda r: r["published_at"], reverse=True)
    write_csv(stats_dir / "videos.csv", VIDEO_FIELDS, latest)
    summary = {"videos": len(videos), "mapped": sum(1 for v in videos if v["id"] in names),
               "new_mappings": len(added), "impressions": has_impressions, "unknown_names": unknown}
    print(f"  роликов {summary['videos']}, сопоставлено с завязками {summary['mapped']} "
          f"(новых меток {summary['new_mappings']}), показы/CTR: {'есть' if has_impressions else 'нет'}")
    return summary


def _load_env() -> None:
    """Локальный запуск: токен из .env (туда его кладёт get_youtube_token.py baby)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / ".env")


def main(argv=None) -> int:
    _load_env()
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        print(NOT_CONNECTED)
        return 0
    from analytics import fetch_channel_info
    from youtube_auth import get_analytics_client, get_client

    youtube = get_client(token, channel=CHANNEL_KEY)
    analytics = get_analytics_client(token, channel=CHANNEL_KEY)
    info = fetch_channel_info(youtube)
    print(f"Канал: {info['name']} — подписчиков {info['subs']}, роликов {info['videos']}")
    track(youtube, analytics)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
