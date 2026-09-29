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
    python publish_baby.py --plan 11-40 --start 2026-10-01 [--dry] [--yes]
        пачка: выпуски 11..40 по одному в день с 1 октября, будни 19:30 МСК, выходные 17:00 МСК

Уже выложенное повторно не уходит: выложенное пишется в stats/baby/published.csv, а перед загрузкой
проверяется и он, и список роликов канала (тег s-<name>, как в track_baby.py). Ролика нет — выпуск
пропускается с сообщением. Без --dry пачка печатает расписание и спрашивает y/N (--yes — не спрашивать).

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
PUBLISHED = ROOT / "stats" / "baby" / "published.csv"
PUBLISHED_FIELDS = ["name", "video_id", "publish_at_utc", "at"]
CHANNEL_TITLE = "Nora & Maple"
MSK = dt.timezone(dt.timedelta(hours=3))
WEEKDAY_TIME = dt.time(19, 30)
WEEKEND_TIME = dt.time(17, 0)
LEAD = dt.timedelta(minutes=15)  # раньше YouTube не даёт запланировать
BASE_TAGS = ["nora and maple", "baby and puppy", "golden retriever puppy", "toddler", "ai video"]
WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def _now() -> dt.datetime:
    return dt.datetime.now(MSK)


def _utc(when: dt.datetime) -> str:
    return when.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_shorts():
    return {s["name"]: s for s in json.loads((BABY / "shorts.json").read_text(encoding="utf-8"))}


def video_path(name: str) -> Path:
    return BABY / "batch" / f"{name}.mp4"


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
        status.update(privacyStatus="private", publishAt=_utc(publish_at))
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


# ---------- что уже выложено ----------

def read_published() -> list[dict]:
    if not PUBLISHED.exists():
        return []
    with PUBLISHED.open(encoding="utf-8", newline="") as f:
        return [r for r in csv.DictReader(f) if r.get("name")]


def record_published(name: str, video_id: str, publish_at: dt.datetime, at: dt.datetime) -> None:
    """Строка сразу после загрузки ролика: оборванная пачка не теряет уже выложенное."""
    PUBLISHED.parent.mkdir(parents=True, exist_ok=True)
    new = not PUBLISHED.exists() or PUBLISHED.stat().st_size == 0
    with PUBLISHED.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        if new:
            w.writerow(PUBLISHED_FIELDS)
        w.writerow([name, video_id, _utc(publish_at), _utc(at)])


def _published_at(row: dict) -> dt.datetime | None:
    try:
        return dt.datetime.strptime(row.get("publish_at_utc", ""), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def taken_days(published: list[dict]) -> set[dt.date]:
    """Дни (по Москве), на которые уже что-то выложено или запланировано, — пачка их пропускает."""
    return {when.astimezone(MSK).date() for when in map(_published_at, published) if when}


def last_type(published: list[dict], shorts: dict) -> str | None:
    """Тип последнего по времени выложенного выпуска: с ним сверяется первый выпуск пачки."""
    rows = [(when, r["name"]) for r in published if (when := _published_at(r)) and r["name"] in shorts]
    return shorts[max(rows)[1]]["type"] if rows else None


# ---------- расписание ----------

def slot_time(day: dt.date) -> dt.datetime:
    """Будни 19:30 МСК, суббота и воскресенье 17:00 МСК."""
    return dt.datetime.combine(day, WEEKEND_TIME if day.weekday() >= 5 else WEEKDAY_TIME, tzinfo=MSK)


def schedule(start: dt.date, count: int, taken: set[dt.date] = frozenset()) -> list[dt.datetime]:
    """count слотов по одному в день с даты start, минуя занятые дни."""
    slots, day = [], start
    while len(slots) < count:
        if day not in taken:
            slots.append(slot_time(day))
        day += dt.timedelta(days=1)
    return slots


def plan_order(items: list[dict], prev_type: str | None = None) -> list[dict]:
    """Порядок по order, но без двух выпусков одного type подряд: если следующий того же типа, что
    предыдущий, вперёд встаёт ближайший следующий другого типа. Нет такого — порядок как есть."""
    rest = sorted(items, key=lambda s: s["order"])
    out = []
    while rest:
        pick = next((s for s in rest if s["type"] != prev_type), rest[0])
        rest.remove(pick)
        out.append(pick)
        prev_type = pick["type"]
    return out


def parse_range(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", text)
    if not m or int(m.group(1)) > int(m.group(2)):
        raise SystemExit(f"--plan ждёт диапазон номеров «FROM-TO», например 11-40, а не «{text}»")
    return int(m.group(1)), int(m.group(2))


def print_schedule(rows: list[tuple]) -> None:
    print(f"Расписание ({len(rows)}):")
    for when, s, entry in rows:
        print(f"  {when:%Y-%m-%d} {WEEKDAYS[when.weekday()]} {when:%H:%M} МСК  #{s['order']:<3} "
              f"{s['name']:<24} {s['type']:<10} {entry['title']}")


# ---------- YouTube ----------

def check_channel(youtube) -> None:
    """Токен должен быть от канала Nora & Maple — иначе ничего не выкладываем."""
    items = youtube.channels().list(part="snippet", mine=True).execute().get("items", [])
    title = items[0]["snippet"]["title"] if items else ""
    if title != CHANNEL_TITLE:
        raise SystemExit(f"токен от другого канала: «{title}» — ничего не выложено")


def channel_names(youtube) -> set[str]:
    """Завязки, уже лежащие на канале (метка s-<name> в тегах или #s:<name> в описании), — как track_baby.py."""
    sys.path.insert(0, str(ROOT / "src"))
    from track_baby import fetch_videos, name_from_video
    return {n for v in fetch_videos(youtube) if (n := name_from_video(v))}


def connect():
    """Клиент YouTube канала baby с проверкой, что токен от Nora & Maple."""
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    token = os.environ.get("YT_TOKEN_BABY")
    if not token:
        raise SystemExit("нет YT_TOKEN_BABY в .env — py src/get_youtube_token.py baby")
    sys.path.insert(0, str(ROOT / "src"))
    from youtube_auth import get_client
    youtube = get_client(token, channel="baby")
    check_channel(youtube)
    return youtube


def upload(youtube, body: dict, video: Path) -> str:
    sys.path.insert(0, str(ROOT / "src"))
    from googleapiclient.http import MediaFileUpload
    from upload_youtube import resumable_upload
    req = youtube.videos().insert(part="snippet,status", body=body,
                                  media_body=MediaFileUpload(str(video), mimetype="video/mp4", resumable=True))
    return resumable_upload(req)["id"]


def confirm(count: int) -> bool:
    try:
        answer = input(f"Выложить {count} по этому расписанию? [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes", "д", "да")


# ---------- режимы ----------

def run_one(a) -> int:
    shorts = load_shorts()
    if a.name not in shorts:
        raise SystemExit(f"нет завязки {a.name} в shorts.json")
    video = video_path(a.name)
    if not video.exists():
        raise SystemExit(f"нет ролика {video}")
    if a.name in {r["name"] for r in read_published()}:
        raise SystemExit(f"{a.name} уже выложен (stats/baby/published.csv) — ничего не выложено")
    publish_at = None
    if a.at:
        publish_at = dt.datetime.strptime(a.at, "%Y-%m-%d %H:%M").replace(tzinfo=MSK)
        if publish_at < _now() + LEAD:
            raise SystemExit("время публикации должно быть хотя бы через 15 минут")
    body = build_body(a.name, pack_entry(shorts[a.name]["order"]), publish_at)
    print(json.dumps(body, ensure_ascii=False, indent=1))
    print("файл:", video)
    if a.dry:
        return 0

    youtube = connect()
    if a.name in channel_names(youtube):
        raise SystemExit(f"{a.name} уже на канале (тег s-{a.name}) — ничего не выложено")
    vid = upload(youtube, body, video)
    at = _now()
    record_published(a.name, vid, publish_at or at, at)
    when = publish_at.strftime("%d.%m %H:%M МСК") if publish_at else "сразу"
    print(f"Загружено: https://youtube.com/shorts/{vid} — публикация {when}; тег s-{a.name} трекер подхватит сам")
    return 0


def run_plan(a) -> int:
    lo, hi = parse_range(a.plan)
    try:
        start = dt.datetime.strptime(a.start, "%Y-%m-%d").date()
    except ValueError:
        raise SystemExit(f"--start ждёт дату «ГГГГ-ММ-ДД», а не «{a.start}»")
    shorts = load_shorts()
    chosen = sorted((s for s in shorts.values() if lo <= s["order"] <= hi), key=lambda s: s["order"])
    if not chosen:
        raise SystemExit(f"в shorts.json нет выпусков с номерами {lo}-{hi}")

    published = read_published()
    done = {r["name"] for r in published}
    todo, skipped = [], []
    for s in chosen:
        if s["name"] in done:
            skipped.append((s, "уже выложен (published.csv)"))
        elif not video_path(s["name"]).exists():
            skipped.append((s, f"нет ролика batch/{s['name']}.mp4"))
        else:
            todo.append(s)
    entries = {s["name"]: pack_entry(s["order"]) for s in todo}  # нет текста — стоп до всякой сети

    youtube = None
    if a.dry:
        print("--dry: список роликов канала не проверяется, только stats/baby/published.csv")
    else:
        youtube = connect()
        on_channel = channel_names(youtube)
        for s in [s for s in todo if s["name"] in on_channel]:
            todo.remove(s)
            skipped.append((s, f"уже на канале (тег s-{s['name']})"))
    for s, why in sorted(skipped, key=lambda x: x[0]["order"]):
        print(f"  пропуск #{s['order']} {s['name']}: {why}")
    if not todo:
        print("выкладывать нечего")
        return 0

    ordered = plan_order(todo, last_type(published, shorts))
    slots = schedule(start, len(ordered), taken_days(published))
    if slots[0] < _now() + LEAD:
        raise SystemExit(f"первый слот {slots[0]:%Y-%m-%d %H:%M} МСК уже прошёл или ближе 15 минут — "
                         f"возьмите --start позже")
    rows = [(when, s, entries[s["name"]]) for when, s in zip(slots, ordered)]
    print_schedule(rows)

    if a.dry:
        for when, s, entry in rows:
            print(f"\n--- #{s['order']} {s['name']} — {when:%Y-%m-%d %H:%M} МСК, файл {video_path(s['name'])}")
            print(json.dumps(build_body(s["name"], entry, when), ensure_ascii=False, indent=1))
        return 0
    if not a.yes and not confirm(len(rows)):
        print("отменено — ничего не выложено")
        return 0

    for i, (when, s, entry) in enumerate(rows):
        try:
            vid = upload(youtube, build_body(s["name"], entry, when), video_path(s["name"]))
        except Exception as exc:  # квота, сеть, отказ API: дальше не идём, выложенное уже записано
            print(f"  ОШИБКА на #{s['order']} {s['name']}: {type(exc).__name__}: {str(exc)[:300]}")
            print(f"остановлено: выложено {i} из {len(rows)}. Та же команда продолжит с оставшихся, "
                  f"занятые дни пропустит")
            return 1
        record_published(s["name"], vid, when, _now())
        print(f"  #{s['order']} {s['name']}: https://youtube.com/shorts/{vid} — {when:%d.%m %H:%M} МСК")
    print(f"готово: выложено {len(rows)}, записано в stats/baby/published.csv")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?", help="завязка из shorts.json (одиночная выкладка)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--at", help="время публикации по Москве, «ГГГГ-ММ-ДД ЧЧ:ММ»")
    g.add_argument("--now", action="store_true")
    g.add_argument("--plan", metavar="FROM-TO", help="пачка: выпуски с номерами FROM..TO по одному в день")
    ap.add_argument("--start", help="первый день пачки, «ГГГГ-ММ-ДД»")
    ap.add_argument("--dry", action="store_true", help="ничего не выкладывать и не писать, только показать")
    ap.add_argument("--yes", action="store_true", help="пачка без вопроса y/N")
    a = ap.parse_args(argv)
    if a.plan:
        if a.name:
            ap.error("--plan выкладывает диапазон номеров — имя завязки не нужно")
        if not a.start:
            ap.error("--plan требует --start ГГГГ-ММ-ДД")
        return run_plan(a)
    if not a.name:
        ap.error("укажите завязку или --plan FROM-TO")
    return run_one(a)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
