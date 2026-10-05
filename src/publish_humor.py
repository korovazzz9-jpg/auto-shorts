"""Выкладка роликов канала «Юмор шортс Humor Shorts» (@smeshno_shorts, сценки с Ликой) с расписанием.

Ролики и тексты — из репозитория AI (рядом, ../AI):
  ролики  — video_gen/ui/_cp77_series/girl01/final/<NN>_<slug>.mp4
  тексты  — video_gen/ui/_cp77_series/girl01/CHANNEL_PACK.md: таблица «Заголовки, описания, теги»
  порядок — там же, раздел «Порядок выкладки»
Расписание: 2 ролика в день, 12:00 и вечер — через день 18:00 или 19:00 МСК (опыт со временем). Ставится «не для детей» и «синтетический контент».

    python publish_humor.py --start 2026-10-05 --dry     показать расписание и что уйдёт, ничего не выкладывая
    python publish_humor.py --start 2026-10-05 [--yes]   выложить всё оставшееся по расписанию

Квота API — около 6 загрузок в сутки на проект: при отказе скрипт останавливается, та же команда на
следующий день продолжит с оставшихся (выложенное пишется в stats/humor/published.csv, занятые слоты
пропускаются). Токен — YT_REFRESH_TOKEN_HUMOR из .env (py src/get_youtube_token.py humor).
"""
import argparse
import csv
import datetime as dt
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AI = Path(os.environ.get("AI_REPO", ROOT.parent / "AI"))
GIRL = AI / "video_gen" / "ui" / "_cp77_series" / "girl01"
PACK = GIRL / "CHANNEL_PACK.md"
PUBLISHED = ROOT / "stats" / "humor" / "published.csv"
FIELDS = ["num", "file", "video_id", "publish_at_utc", "at"]
CHANNEL_TITLE = "Юмор шортс Humor Shorts"
MSK = dt.timezone(dt.timedelta(hours=3))
SLOTS = [dt.time(12, 0), dt.time(19, 0)]
LEAD = dt.timedelta(minutes=15)
COMMON = "#юмор #приколы #жиза #shorts"
BASE_TAGS = ["юмор", "приколы", "жиза", "смешные видео", "шортс", "сценки", "женский юмор", "humor shorts"]


def _now():
    return dt.datetime.now(MSK)


def _utc(when):
    return when.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_pack():
    """(порядок номеров, {номер: строка таблицы})."""
    text = PACK.read_text(encoding="utf-8")
    rows = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 5 and cells[0].isdigit():
            rows[int(cells[0])] = {"num": int(cells[0]), "file": cells[1], "title": cells[2],
                                   "desc": cells[3], "tags": cells[4]}
    sec = text.split("## Порядок выкладки", 1)[1].split("\n\n", 2)[2].split("\n\n", 1)[0]
    order = [int(n) for n in re.findall(r"\d+", sec)]
    missing = [n for n in order if n not in rows]
    if missing or len(set(order)) != len(order) or set(order) != set(rows):
        raise SystemExit(f"порядок и таблица не сходятся: нет строк {missing}, "
                         f"вне порядка {sorted(set(rows) - set(order))}")
    return order, rows


def build_body(row, publish_at):
    tags = row["tags"] + " " + COMMON
    words = [t.lstrip("#") for t in tags.split() if t.lstrip("#") != "shorts"]
    return {
        "snippet": {
            "title": row["title"][:100],
            "description": f"{row['desc']}\n\n{tags}\n\nПерсонажи и видео созданы с помощью ИИ.",
            "tags": list(dict.fromkeys(BASE_TAGS + words)),
            "categoryId": "23",  # Comedy
            "defaultLanguage": "ru",
            "defaultAudioLanguage": "ru",
        },
        "status": {"privacyStatus": "private", "publishAt": _utc(publish_at),
                   "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True},
    }


def read_published():
    if not PUBLISHED.exists():
        return []
    with PUBLISHED.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def record(row, vid, when):
    PUBLISHED.parent.mkdir(parents=True, exist_ok=True)
    new = not PUBLISHED.exists() or PUBLISHED.stat().st_size == 0
    with PUBLISHED.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        if new:
            w.writerow(FIELDS)
        w.writerow([row["num"], row["file"], vid, _utc(when), _utc(_now())])


def slots(start, count, taken):
    busy = {dt.datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).astimezone(MSK).date()
            for t in taken}
    out, day = [], start
    while len(out) < count:
        if day in busy:
            day += dt.timedelta(days=1)
            continue
        for t in SLOTS:
            if t.hour == 19 and day.toordinal() % 2 == 0:
                t = dt.time(18, 0)  # 5 окт: вечер через день в 18:00 — сравнить с 19:00 (решение пользователя)
            when = dt.datetime.combine(day, t, tzinfo=MSK)
            if when >= _now() + LEAD and _utc(when) not in taken and len(out) < count:
                out.append(when)
        day += dt.timedelta(days=1)
    return out


def connect():
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    token = os.environ.get("YT_REFRESH_TOKEN_HUMOR")
    if not token:
        raise SystemExit("нет YT_REFRESH_TOKEN_HUMOR в .env — py src/get_youtube_token.py humor")
    sys.path.insert(0, str(ROOT / "src"))
    from youtube_auth import get_client
    yt = get_client(token, channel="humor")
    items = yt.channels().list(part="snippet", mine=True).execute().get("items", [])
    title = items[0]["snippet"]["title"] if items else ""
    if title != CHANNEL_TITLE:
        raise SystemExit(f"токен от другого канала: «{title}» — ничего не выложено")
    return yt


def upload(yt, body, video):
    from googleapiclient.http import MediaFileUpload
    from upload_youtube import resumable_upload
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(video), mimetype="video/mp4", resumable=True))
    return resumable_upload(req)["id"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="первый день, ГГГГ-ММ-ДД")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args(argv)
    start = dt.datetime.strptime(a.start, "%Y-%m-%d").date()
    order, rows = load_pack()
    pub = read_published()
    done = {int(r["num"]) for r in pub}
    todo = [rows[n] for n in order if n not in done]
    for r in todo:
        if not (GIRL / "final" / r["file"]).exists():
            raise SystemExit(f"нет ролика final/{r['file']}")
    if not todo:
        print("выкладывать нечего")
        return 0
    when_list = slots(start, len(todo), {r["publish_at_utc"] for r in pub})
    plan = list(zip(when_list, todo))
    print(f"Расписание ({len(plan)}), уже выложено {len(done)}:")
    for when, r in plan:
        print(f"  {when:%Y-%m-%d %H:%M} МСК  #{r['num']:<4} {r['file']:<26} {r['title']}")
    if a.dry:
        print("\nпример тела запроса:", build_body(plan[0][1], plan[0][0]))
        return 0
    if not a.yes and input(f"Выложить {len(plan)}? [y/N] ").strip().lower() not in ("y", "yes", "д", "да"):
        print("отменено")
        return 0
    yt = connect()
    for i, (when, r) in enumerate(plan):
        try:
            vid = upload(yt, build_body(r, when), GIRL / "final" / r["file"])
        except Exception as exc:
            print(f"  ОШИБКА на #{r['num']}: {type(exc).__name__}: {str(exc)[:300]}")
            print(f"остановлено: выложено {i} из {len(plan)}; та же команда завтра продолжит")
            return 1
        record(r, vid, when)
        print(f"  #{r['num']} https://youtube.com/shorts/{vid} — {when:%d.%m %H:%M} МСК", flush=True)
    print(f"готово: {len(plan)}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
