"""Weekly Telegram summary for Lika's YouTube, Instagram and Facebook accounts.

Only public videos released in the last seven days are ranked. View counts are
their cumulative counts at report time. Follower changes use saved snapshots;
the first run establishes a baseline and never invents a historical count.
"""
import csv
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ.get("LIKA_DATA_ROOT", ROOT))
HISTORY = DATA_ROOT / "stats" / "humor" / "followers.json"
GRAPH = "https://graph.facebook.com/v21.0"
PAGE_ID = "1438073186047107"
PAGE_NAME = "Юмор шортс Humor Shorts"
IG_USERNAME = "smeshno_shorts"
YOUTUBE_NAME = PAGE_NAME
MAX_ITEMS = 200


class DataUnavailable(Exception):
    """An API did not return a trustworthy count."""


def _load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv(DATA_ROOT / ".env")
    except ImportError:
        pass


def _graph(path, token, **params):
    response = requests.get(f"{GRAPH}/{path}", headers={"Authorization": f"Bearer {token}"},
                            params=params, timeout=25)
    try:
        body = response.json()
    except ValueError as exc:
        raise DataUnavailable(f"Meta: HTTP {response.status_code}") from exc
    if response.status_code >= 400 or body.get("error"):
        error = body.get("error", {})
        raise DataUnavailable(f"Meta: код {error.get('code', response.status_code)} — "
                              f"{error.get('message', 'ошибка чтения')}")
    return body


def _since(now):
    return now - timedelta(days=7)


def _published(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _recent(items, now):
    return [item for item in items if _since(now) <= _published(item["published_at"]) <= now]


def _page_items(path, token, fields, now):
    """Read a bounded number of media pages; never assume the API sorts them."""
    items, after = [], None
    while len(items) < MAX_ITEMS:
        params = {"fields": fields, "limit": min(100, MAX_ITEMS - len(items))}
        if after:
            params["after"] = after
        body = _graph(path, token, **params)
        batch = body.get("data", [])
        items.extend(batch)
        cursor = body.get("paging", {}).get("cursors", {}).get("after")
        if not batch or not cursor or cursor == after:
            break
        after = cursor
    return items[:MAX_ITEMS]


def fetch_youtube(now):
    token = os.environ.get("YT_REFRESH_TOKEN_HUMOR")
    if not token:
        raise DataUnavailable("нет YT_REFRESH_TOKEN_HUMOR")
    from analytics_retention import upload_video_ids
    from youtube_auth import get_client

    yt = get_client(token, channel="humor")
    channels = yt.channels().list(part="snippet,statistics", mine=True).execute().get("items", [])
    if len(channels) != 1 or channels[0]["snippet"]["title"] != YOUTUBE_NAME:
        raise DataUnavailable("YouTube-токен не принадлежит каналу Лики")
    followers = channels[0].get("statistics", {}).get("subscriberCount")
    ids = upload_video_ids(yt, 100)
    schedule = {}
    published_csv = DATA_ROOT / "stats" / "humor" / "published.csv"
    if published_csv.exists():
        with published_csv.open(encoding="utf-8", newline="") as file:
            schedule = {row["video_id"]: row["publish_at_utc"] for row in csv.DictReader(file)}
    videos = []
    for start in range(0, len(ids), 50):
        response = yt.videos().list(part="snippet,statistics,status", id=",".join(ids[start:start + 50])).execute()
        for item in response.get("items", []):
            if item.get("status", {}).get("privacyStatus") != "public":
                continue
            snippet = item["snippet"]
            videos.append({"id": item["id"], "title": snippet.get("title", ""),
                           "published_at": schedule.get(item["id"], snippet["publishedAt"]),
                           "views": (int(item["statistics"]["viewCount"])
                                     if "viewCount" in item.get("statistics", {}) else None),
                           "url": f"https://youtube.com/shorts/{item['id']}"})
    return {"followers": int(followers) if followers is not None else None,
            "videos": _recent(videos, now), "views_status": None}


def fetch_instagram(now):
    token = os.environ.get("IG_ACCESS_TOKEN_HUMOR")
    account_id = os.environ.get("IG_USER_ID_HUMOR")
    if not token or not account_id:
        raise DataUnavailable("не подключён Instagram-токен Лики")
    profile = _graph(account_id, token, fields="username,followers_count")
    if profile.get("username", "").lower() != IG_USERNAME:
        raise DataUnavailable("Instagram-токен не принадлежит аккаунту Лики")
    media = _page_items(f"{account_id}/media", token,
                        "id,caption,media_type,media_product_type,timestamp,permalink", now)
    videos = [{"id": m["id"], "title": (m.get("caption") or "Reel").splitlines()[0],
               "published_at": m["timestamp"], "url": m.get("permalink", "")}
              for m in media if m.get("media_product_type") == "REELS" and m.get("timestamp")]
    videos = _recent(videos, now)
    views_status = None
    for video in videos:
        try:
            insight = _graph(f"{video['id']}/insights", token, metric="views")
            values = insight.get("data", [{}])[0].get("values", [])
            if values and values[0].get("value") is not None:
                video["views"] = int(values[0]["value"])
        except DataUnavailable:
            views_status = "нет доступа к просмотрам Reels (нужно instagram_manage_insights)"
            break
    if videos and not any("views" in v for v in videos) and not views_status:
        views_status = "Meta не вернула просмотры Reels"
    return {"followers": profile.get("followers_count"), "videos": videos,
            "views_status": views_status}


def fetch_facebook(now):
    token = os.environ.get("IG_ACCESS_TOKEN_HUMOR")
    if not token:
        raise DataUnavailable("не подключён Meta-токен Лики")
    accounts = _page_items("me/accounts", token, "id,name,access_token", now)
    page = next((p for p in accounts if p.get("id") == PAGE_ID and p.get("name") == PAGE_NAME), None)
    if not page or not page.get("access_token"):
        raise DataUnavailable("страница Facebook Лики недоступна токену")
    page_token = page["access_token"]
    profile = _graph(PAGE_ID, page_token, fields="name,followers_count")
    media = _page_items(f"{PAGE_ID}/videos", page_token,
                        "id,description,created_time,views,permalink_url", now)
    videos = [{"id": m["id"], "title": (m.get("description") or "Reel").splitlines()[0],
               "published_at": m["created_time"], "url": m.get("permalink_url", ""),
               "views": int(m.get("views") or 0)}
              for m in media if m.get("created_time")]
    videos = _recent(videos, now)
    views_status = None
    if videos and not any(v["views"] > 0 for v in videos):
        try:
            result = _graph(f"{videos[0]['id']}/video_insights", page_token,
                            metric="total_video_views")
            if result.get("data"):
                # Page video.views is zero for some Reels. Prefer insights if authorized.
                for video in videos:
                    data = _graph(f"{video['id']}/video_insights", page_token,
                                  metric="total_video_views").get("data", [])
                    values = data[0].get("values", []) if data else []
                    if values:
                        video["views"] = int(values[0].get("value") or 0)
        except DataUnavailable:
            views_status = "нет доступа к просмотрам Reels (нужно read_insights)"
    if videos and not any(v["views"] > 0 for v in videos) and not views_status:
        views_status = "Meta вернула нулевые просмотры для всех новых Reels"
    # Graph often reports zero on Page Reels that have public views. These values
    # cannot establish the least-viewed Reel until insights access is granted.
    if videos and any(v["views"] == 0 for v in videos):
        views_status = (views_status or "Meta не вернула просмотры части новых Reels")
        for video in videos:
            if video["views"] == 0:
                video["views"] = None
    return {"followers": profile.get("followers_count"), "videos": videos,
            "views_status": views_status}


def load_history(path=HISTORY):
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("snapshots", [])


def baseline(history, platform, now):
    """Only an older weekly snapshot qualifies; same-day reruns keep the same base."""
    eligible = [row for row in history if row["at"][:10] <= (now - timedelta(days=5)).date().isoformat()
                and row.get("followers", {}).get(platform) is not None]
    return max(eligible, key=lambda row: row["at"]) if eligible else None


def save_snapshot(results, now, path=HISTORY):
    history = load_history(path)
    counts = {key: result["followers"] for key, result in results.items()
              if isinstance(result, dict) and result.get("followers") is not None}
    if not counts:
        return
    today = now.date().isoformat()
    history = [row for row in history if row["at"][:10] != today]
    history.append({"at": now.isoformat(), "followers": counts})
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps({"snapshots": history}, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    temp.replace(path)


def render(results, history, now):
    lines = [f"📊 Лика · {now:%d.%m.%Y} · новые ролики за 7 дней",
             "Просмотры роликов — с публикации, на момент отчёта."]
    for key, name in (("youtube", "YouTube"), ("instagram", "Instagram"), ("facebook", "Facebook")):
        lines.append(f"\n{name}")
        result = results[key]
        if isinstance(result, str):
            lines.append(f"Данные недоступны: {result}")
            continue
        count = result["followers"]
        old = baseline(history, key, now)
        if count is None:
            lines.append("Подписчики: данных нет")
        elif old:
            before = old["followers"][key]
            delta = count - before
            lines.append(f"Подписчики: {delta:+,} с {old['at'][:10]} ({before:,} → {count:,})")
        else:
            lines.append(f"Подписчики: {count:,} (первый замер; прирост со следующей недели)")
        videos = result["videos"]
        lines.append(f"Новых роликов: {len(videos)}")
        measured = [v for v in videos if v.get("views") is not None]
        if videos and len(measured) == len(videos):
            best = max(measured, key=lambda v: v["views"])
            worst = min(measured, key=lambda v: v["views"])
            lines.append(f"Самый просматриваемый: {best['views']:,} — {best['title'][:50]}\n{best['url']}")
            lines.append(f"Наименее просматриваемый: {worst['views']:,} — {worst['title'][:50]}\n{worst['url']}")
        elif videos:
            lines.append(f"Лидер и аутсайдер не определены: просмотры доступны для {len(measured)}/{len(videos)} роликов")
            if result.get("views_status"):
                lines.append(result["views_status"])
        else:
            lines.append("За неделю новых роликов нет")
    return "\n".join(lines)


def send_telegram(text):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat = os.environ["TELEGRAM_CHAT_ID"]
    if len(text) > 4000:
        raise ValueError("Отчёт длиннее лимита Telegram")
    response = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                             json={"chat_id": chat, "text": text, "disable_web_page_preview": True},
                             timeout=25)
    if response.status_code >= 400:
        raise RuntimeError(f"Telegram HTTP {response.status_code}")
    if not response.json().get("ok"):
        raise RuntimeError("Telegram не подтвердил доставку отчёта")


def main():
    _load_env()
    now = datetime.now(timezone.utc)
    history = load_history()
    results = {}
    for key, fetch in (("youtube", fetch_youtube), ("instagram", fetch_instagram),
                       ("facebook", fetch_facebook)):
        try:
            results[key] = fetch(now)
        except DataUnavailable as exc:
            results[key] = str(exc)[:180]
        except Exception as exc:
            results[key] = f"ошибка {type(exc).__name__}"
    report = render(results, history, now)
    send_telegram(report)
    save_snapshot(results, now)
    print(f"Отчёт отправлен и подтверждён Telegram; площадки: "
          f"{', '.join(k for k, v in results.items() if isinstance(v, dict))}")


if __name__ == "__main__":
    main()
