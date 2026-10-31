"""One age-labelled reach snapshot per ES Short, first sampled after 72 hours.

YouTube Data API supplies public play counts. Analytics supplies engaged views
for the first three UTC calendar dates when available. Shorts feed impressions
and stayed-to-watch are Studio-only and are never inferred from these numbers.
"""
import csv
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from youtube_auth import get_analytics_client, get_client

ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / "video_history_es.json"
OUTPUT = ROOT / "stats" / "es" / "reach_after_72h.csv"
FIELDS = ("video_id", "published_at", "sampled_at", "sample_age_hours", "topic",
          "hook_template", "opening_vetted", "views_at_sample",
          "analytics_period_end", "analytics_views_3d", "engaged_views_3d")


def due(history, recorded_ids, now):
    """Include missed daily runs up to day seven; sample each video only once."""
    result = []
    for entry in history:
        if entry.get("video_id") in recorded_ids:
            continue
        try:
            published = datetime.fromisoformat(entry["published_at"].replace("Z", "+00:00"))
            age = now - published.astimezone(timezone.utc)
        except (KeyError, ValueError, TypeError):
            continue
        if timedelta(hours=72) <= age <= timedelta(days=7):
            result.append((entry, published.astimezone(timezone.utc), age))
    return sorted(result, key=lambda item: item[1])


def load_rows(path=OUTPUT):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_rows(rows, path=OUTPUT):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".csv.tmp")
    with temp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(path)


def collect(now=None, history_path=HISTORY, output_path=OUTPUT):
    now = now or datetime.now(timezone.utc)
    rows = load_rows(output_path)
    history = json.loads(history_path.read_text(encoding="utf-8"))
    pending = due(history, {row["video_id"] for row in rows}, now)
    if not pending:
        print("ES reach: no videos aged 72h–7d await a snapshot")
        return 0

    youtube = get_client(channel="es")
    ids = [entry["video_id"] for entry, _, _ in pending]
    videos = {}
    for start in range(0, len(ids), 50):
        response = youtube.videos().list(
            part="statistics,status", id=",".join(ids[start:start + 50])
        ).execute()
        videos.update({item["id"]: item for item in response.get("items", [])})
    pending = [(entry, published, age) for entry, published, age in pending
               if videos.get(entry["video_id"], {}).get("status", {}).get("privacyStatus") == "public"
               and videos[entry["video_id"]].get("statistics", {}).get("viewCount") is not None]
    if not pending:
        print("ES reach: no eligible public videos to snapshot")
        return 0

    # Batch videos by publication date: same fixed three-calendar-date period,
    # fewer Analytics requests than querying each video separately.
    analytics_rows = {}
    try:
        from analytics_retention import video_report
        analytics = get_analytics_client(channel="es")
        groups = defaultdict(list)
        for entry, published, _ in pending:
            groups[published.date()].append(entry["video_id"])
        for day, group_ids in groups.items():
            end = day + timedelta(days=2)
            try:
                stats = video_report(analytics, group_ids, day.isoformat(), end.isoformat(),
                                     "views,engagedViews")
                analytics_rows.update(stats)
            except Exception as exc:
                print(f"::warning::ES Analytics unavailable for {day}: {type(exc).__name__}")
    except Exception as exc:
        print(f"::warning::ES Analytics unavailable: {type(exc).__name__}")

    added = 0
    for entry, published, age in pending:
        count = videos[entry["video_id"]]["statistics"]["viewCount"]
        stats = analytics_rows.get(entry["video_id"], {})
        rows.append({
            "video_id": entry["video_id"],
            "published_at": published.isoformat(),
            "sampled_at": now.isoformat(),
            "sample_age_hours": round(age.total_seconds() / 3600, 1),
            "topic": entry.get("topic", ""),
            "hook_template": entry.get("hook_template", ""),
            "opening_vetted": (entry.get("clip_selection") or {}).get("opening_vetted", ""),
            "views_at_sample": int(count),
            "analytics_period_end": (published.date() + timedelta(days=2)).isoformat(),
            "analytics_views_3d": stats.get("views", ""),
            "engaged_views_3d": stats.get("engagedViews", ""),
        })
        added += 1
    if added:
        write_rows(rows, output_path)
    print(f"ES reach: saved {added} snapshots; Analytics values available for "
          f"{sum(row['engaged_views_3d'] != '' for row in rows[-added:]) if added else 0}")
    return added


if __name__ == "__main__":
    collect()
