"""Аналитика YouTube через Data API v3 (videos.list + channels.list).
Запуск: python analytics.py
"""
import os
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv()

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


def get_client(refresh_token):
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    return build("youtube", "v3", credentials=creds)


def fetch_channel_info(yt):
    r = yt.channels().list(part="snippet,statistics", mine=True).execute()
    ch = r["items"][0]
    return {
        "id": ch["id"],
        "name": ch["snippet"]["title"],
        "subs": int(ch["statistics"].get("subscriberCount", 0)),
        "total_views": int(ch["statistics"].get("viewCount", 0)),
        "videos": int(ch["statistics"].get("videoCount", 0)),
    }


def fetch_recent_videos(yt, channel_id, max_results=20):
    r = yt.search().list(
        part="id",
        channelId=channel_id,
        order="date",
        type="video",
        maxResults=max_results,
    ).execute()
    ids = [item["id"]["videoId"] for item in r.get("items", [])]
    if not ids:
        return []
    r2 = yt.videos().list(
        part="snippet,statistics,contentDetails",
        id=",".join(ids),
    ).execute()
    videos = []
    for item in r2.get("items", []):
        pub = item["snippet"]["publishedAt"]
        stats = item["statistics"]
        videos.append({
            "id": item["id"],
            "title": item["snippet"]["title"],
            "published": pub,
            "views": int(stats.get("viewCount", 0)),
            "likes": int(stats.get("likeCount", 0)),
            "comments": int(stats.get("commentCount", 0)),
        })
    return sorted(videos, key=lambda v: v["published"], reverse=True)


def fmt_time_ago(iso_str):
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    diff = datetime.now(timezone.utc) - dt
    h = int(diff.total_seconds() / 3600)
    if h < 24:
        return f"{h}h ago"
    return f"{h // 24}d ago"


def print_channel(label, refresh_token):
    print()
    print("=" * 58)
    yt = get_client(refresh_token)
    info = fetch_channel_info(yt)
    print(f"  {info['name']}  ({label})")
    print("=" * 58)
    print(f"  Subscribers : {info['subs']:,}")
    print(f"  Total views : {info['total_views']:,}")
    print(f"  Videos      : {info['videos']}")

    videos = fetch_recent_videos(yt, info["id"], max_results=20)
    if not videos:
        print("  No videos found.")
        return

    total_7d_views = 0
    total_7d_likes = 0
    count_7d = 0
    for v in videos:
        dt = datetime.fromisoformat(v["published"].replace("Z", "+00:00"))
        diff = datetime.now(timezone.utc) - dt
        if diff.total_seconds() < 7 * 86400:
            total_7d_views += v["views"]
            total_7d_likes += v["likes"]
            count_7d += 1

    print()
    print(f"  --- Last 7 days ({count_7d} videos) ---")
    print(f"  Views : {total_7d_views:,}")
    print(f"  Likes : {total_7d_likes:,}")
    avg_views = total_7d_views // count_7d if count_7d else 0
    print(f"  Avg views/video : {avg_views:,}")

    print()
    print(f"  --- Last {len(videos)} videos (newest first) ---")
    print(f"  {'Title':<42} {'Age':>7} {'Views':>7} {'Likes':>5}")
    print(f"  {'-'*42} {'-'*7} {'-'*7} {'-'*5}")
    for v in videos:
        title = v["title"][:42]
        age = fmt_time_ago(v["published"])
        print(f"  {title:<42} {age:>7} {v['views']:>7,} {v['likes']:>5,}")


channels = [
    ("EN", os.environ.get("YT_REFRESH_TOKEN", "")),
    ("ES", os.environ.get("YT_REFRESH_TOKEN_ES", "")),
]

for label, token in channels:
    if not token:
        print(f"\n[!] No token for {label}")
        continue
    try:
        print_channel(label, token)
    except Exception as e:
        print(f"\n[!] Error for {label}: {e}")

print()
