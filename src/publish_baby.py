"""Выкладка роликов канала Nora & Maple (серия «малышка и щенок») по команде.

Ролик, название, описание и хэштеги берутся из репозитория AI (рядом, ../AI):
  ролик   — video_gen/ui/_cp77_series/baby01/batch/<name>.mp4
  тексты  — video_gen/ui/_cp77_series/baby01/CHANNEL_PACK.md, раздел «Описания, теги, обложки» (по номеру выпуска)
  номер   — поле order в shorts.json
Что ставится всегда: «не для детей», «изменённый/синтетический контент» (containsSyntheticMedia), скрытый тег
s-<name> для трекера (он сам допишет пару в mapping.csv), язык en, категория «Животные».

    python publish_baby.py serious_lecture --at "2026-09-30 19:30"   запланировать (время МСК)
    python publish_baby.py serious_lecture --now                      опубликовать сразу
    python publish_baby.py serious_lecture --at ... --dry             показать, что уйдёт, ничего не выкладывая

Токен — YT_TOKEN_BABY из .env (py src/get_youtube_token.py baby). Запуск из каталога src.
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AI = Path(os.environ.get("AI_REPO", ROOT.parent / "AI"))
BABY = AI / "video_gen" / "ui" / "_cp77_series" / "baby01"
MAPPING = ROOT / "stats" / "baby" / "mapping.csv"
MSK = dt.timezone(dt.timedelta(hours=3))
BASE_TAGS = ["nora and maple", "baby and puppy", "golden retriever puppy", "toddler", "ai video"]


def load_shorts():
    return {s["name"]: s for s in json.loads((BABY / "shorts.json").read_text(encoding="utf-8"))}


def pack_entry(order: int) -> dict:
    """Название, описание, хэштеги выпуска N из CHANNEL_PACK.md («**N. Название**» + «- Описание:» + «- Теги:»)."""
    text = (BABY / "CHANNEL_PACK.md").read_text(encoding="utf-8")
    m = re.search(r"^\*\*%d\. (.+?)\*\*\s*$(.*?)(?=^\*\*\d+\. |\Z|^---)" % order, text, re.M | re.S)
    if not m:
        raise SystemExit(f"в CHANNEL_PACK.md нет выпуска {order} — допишите название и описание")
    body = m.group(2)
    desc = re.search(r"- Описание:(.*?)(?=^- |\Z)", body, re.M | re.S)
    tags = re.search(r"- Теги:(.*)", body)
    description = " ".join(desc.group(1).split()).replace(" / ", "\n\n") if desc else ""
    return {"title": m.group(1).strip(), "description": description,
            "hashtags": tags.group(1).split() if tags else []}


def build_body(name: str, entry: dict, publish_at: dt.datetime | None) -> dict:
    words = [h.lstrip("#") for h in entry["hashtags"] if h.lstrip("#") not in ("shorts",)]
    status = {"selfDeclaredMadeForKids": False, "containsSyntheticMedia": True}
    if publish_at:
        status.update(privacyStatus="private", publishAt=publish_at.astimezone(dt.timezone.utc)
                      .strftime("%Y-%m-%dT%H:%M:%SZ"))
    else:
        status["privacyStatus"] = "public"
    return {
        "snippet": {
            "title": entry["title"][:100],
            "description": (entry["description"] + "\n\n" + " ".join(entry["hashtags"])).strip()[:4990],
            "tags": list(dict.fromkeys(["s-" + name] + BASE_TAGS + words)),
            "categoryId": "15",  # Pets & Animals
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": status,
    }


def add_mapping(video_id: str, name: str) -> None:
    MAPPING.parent.mkdir(parents=True, exist_ok=True)
    new = not MAPPING.exists()
    with MAPPING.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        if new:
            w.writerow(["video_id", "name"])
        w.writerow([video_id, name])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--at", help="время публикации по Москве, «ГГГГ-ММ-ДД ЧЧ:ММ»")
    g.add_argument("--now", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)

    shorts = load_shorts()
    if a.name not in shorts:
        raise SystemExit(f"нет завязки {a.name} в shorts.json")
    video = BABY / "batch" / f"{a.name}.mp4"
    if not video.exists():
        raise SystemExit(f"нет ролика {video}")
    publish_at = None
    if a.at:
        publish_at = dt.datetime.strptime(a.at, "%Y-%m-%d %H:%M").replace(tzinfo=MSK)
        if publish_at < dt.datetime.now(MSK) + dt.timedelta(minutes=15):
            raise SystemExit("время публикации должно быть хотя бы через 15 минут")
    body = build_body(a.name, pack_entry(shorts[a.name]["order"]), publish_at)
    print(json.dumps(body, ensure_ascii=False, indent=1))
    print("файл:", video)
    if a.dry:
        return

    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    token = os.environ.get("YT_TOKEN_BABY")
    if not token:
        raise SystemExit("нет YT_TOKEN_BABY в .env — py src/get_youtube_token.py baby")
    sys.path.insert(0, str(ROOT / "src"))
    from googleapiclient.http import MediaFileUpload
    from upload_youtube import resumable_upload
    from youtube_auth import get_client
    youtube = get_client(token, channel="baby")
    title = youtube.channels().list(part="snippet", mine=True).execute()["items"][0]["snippet"]["title"]
    if title != "Nora & Maple":
        raise SystemExit(f"токен от другого канала: «{title}» — ничего не выложено")
    req = youtube.videos().insert(part="snippet,status", body=body,
                                  media_body=MediaFileUpload(str(video), mimetype="video/mp4", resumable=True))
    vid = resumable_upload(req)["id"]
    when = publish_at.strftime("%d.%m %H:%M МСК") if publish_at else "сразу"
    print(f"Загружено: https://youtube.com/shorts/{vid} — публикация {when}; тег s-"+a.name+" трекер подхватит сам")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
