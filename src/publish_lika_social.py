"""Выкладка сценок Лики (те же ролики, что на YouTube @smeshno_shorts) в Instagram Reels и TikTok.

Порядок и тексты — как у publish_humor.py: CHANNEL_PACK.md («Порядок выкладки» и таблица).
Instagram и TikTok через API отложенную публикацию не дают, поэтому скрипт выкладывает СЛЕДУЮЩИЙ по очереди ролик
в момент запуска; два раза в день его запускает Планировщик заданий Windows (setup_lika_social.ps1), компьютер
должен быть включён. Выложенное пишется в stats/humor/social.csv — повторный запуск не дублирует.

    python src/publish_lika_social.py --platform ig --dry        что уйдёт следующим, ничего не выкладывая
    python src/publish_lika_social.py --platform ig --yes        выложить следующий Reel
    python src/publish_lika_social.py --platform tiktok --yes    отправить следующий ролик в TikTok

Instagram: Graph API (graph.facebook.com), видео через временную ссылку Cloudinary (как у фактов), ключи
IG_ACCESS_TOKEN_HUMOR и IG_USER_ID_HUMOR в .env. Перед выкладкой проверяется имя аккаунта (IG_USERNAME_HUMOR).
TikTok: пока приложение не прошло аудит, TikTok разрешает только загрузку в «черновики» (inbox): ролик приходит
уведомлением в приложение TikTok, подпись копируется из stats/humor/tiktok_captions.txt, «Опубликовать» — руками.
После аудита — TIKTOK_MODE_HUMOR=direct (сразу публично). Токен обновляется сам по TIKTOK_REFRESH_TOKEN_HUMOR.
"""
import argparse
import csv
import datetime as dt
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import publish_humor as ph  # noqa: E402

ROOT = ph.ROOT
SOCIAL = ROOT / "stats" / "humor" / "social.csv"
CAPTIONS = ROOT / "stats" / "humor" / "tiktok_captions.txt"
FIELDS = ["num", "file", "platform", "media_id", "at"]
GRAPH = "https://graph.facebook.com/v21.0"
TT = "https://open.tiktokapis.com/v2"
IG_TAGS = "#юмор #приколы #жиза #reels #смешно"
TT_TAGS = "#юмор #приколы #жиза #смешно #fyp"


def env(name):
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    v = os.environ.get(name)
    if not v:
        raise SystemExit(f"нет {name} в .env — см. docs/LIKA_INSTAGRAM_TIKTOK.md")
    return v


def done(platform):
    if not SOCIAL.exists():
        return set()
    with SOCIAL.open(encoding="utf-8", newline="") as f:
        return {int(r["num"]) for r in csv.DictReader(f) if r["platform"] == platform}


def record(row, platform, media_id):
    SOCIAL.parent.mkdir(parents=True, exist_ok=True)
    new = not SOCIAL.exists() or SOCIAL.stat().st_size == 0
    with SOCIAL.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        if new:
            w.writerow(FIELDS)
        w.writerow([row["num"], row["file"], platform, media_id, ph._utc(ph._now())])


def caption(row, platform):
    tags = row["tags"] + " " + (IG_TAGS if platform == "ig" else TT_TAGS)
    words = list(dict.fromkeys(t if t.startswith("#") else "#" + t for t in tags.split()))
    text = f"{row['title']}\n\n{row['desc']}\n\n" + " ".join(words[:12])
    return (text + "\n\nПерсонажи и видео созданы с помощью ИИ.")[:2200]


# ---------- Instagram ----------
def _ig(method, path, **params):
    params["access_token"] = env("IG_ACCESS_TOKEN_HUMOR")
    r = (requests.get if method == "get" else requests.post)(f"{GRAPH}/{path}", params=params if method == "get"
                                                            else None, data=None if method == "get" else params,
                                                            timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"Instagram {r.status_code}: {r.text[:400]}")
    return r.json()


def ig_check():
    user = env("IG_USER_ID_HUMOR")
    name = _ig("get", user, fields="username").get("username", "")
    want = env("IG_USERNAME_HUMOR").lstrip("@")
    if name.lower() != want.lower():
        raise SystemExit(f"токен от другого аккаунта: @{name}, ждали @{want} — ничего не выложено")
    return user


def ig_post(row, video):
    from cloudinary_upload import delete_video, upload_video
    user = ig_check()
    hosted = upload_video(str(video))
    try:
        for attempt in range(3):           # Meta иногда роняет контейнер без причины — пересоздаём (опыт фактов)
            box = _ig("post", f"{user}/media", media_type="REELS", video_url=hosted["url"],
                      caption=caption(row, "ig"), share_to_feed="true")["id"]
            for _ in range(60):
                st = _ig("get", box, fields="status_code")["status_code"]
                if st in ("FINISHED", "ERROR"):
                    break
                time.sleep(5)
            if st == "FINISHED":
                return _ig("post", f"{user}/media_publish", creation_id=box)["id"]
            print(f"  контейнер {box}: {st}, попытка {attempt + 1}/3")
            time.sleep(10)
        raise RuntimeError("Instagram не обработал ролик за 3 попытки")
    finally:
        try:
            delete_video(hosted["public_id"])
        except Exception as e:
            print(f"  не удалось удалить временный файл Cloudinary: {e}")


# ---------- TikTok ----------
TOKEN_FILE = ROOT / "stats" / "humor" / "tiktok_token.json"


def tt_token():
    """Токен доступа живёт сутки: каждый запуск обновляем его по refresh-токену (он живёт год и может смениться —
    свежий хранится в stats/humor/tiktok_token.json, первый берётся из .env TIKTOK_REFRESH_TOKEN_HUMOR)."""
    import json
    refresh = (json.loads(TOKEN_FILE.read_text(encoding="utf-8"))["refresh_token"] if TOKEN_FILE.exists()
               else env("TIKTOK_REFRESH_TOKEN_HUMOR"))
    r = requests.post(f"{TT}/oauth/token/", timeout=60, data={
        "client_key": os.environ.get("TIKTOK_CLIENT_KEY", "awlqkv9gr65hjezw"),
        "client_secret": env("TIKTOK_CLIENT_SECRET"), "grant_type": "refresh_token", "refresh_token": refresh}).json()
    if "access_token" not in r:
        raise RuntimeError(f"TikTok: токен не обновился — заново get_tiktok_token.py: {r}")
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps({"refresh_token": r.get("refresh_token", refresh)}), encoding="utf-8")
    return r["access_token"]


def tt_post(row, video):
    token = tt_token()
    mode = os.environ.get("TIKTOK_MODE_HUMOR", "inbox")
    size = video.stat().st_size
    head = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
    src = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1}
    if mode == "direct":
        body = {"post_info": {"title": caption(row, "tt"), "privacy_level": "PUBLIC_TO_EVERYONE",
                              "is_aigc": True, "video_cover_timestamp_ms": 1000}, "source_info": src}
        url = f"{TT}/post/publish/video/init/"
    else:
        body = {"source_info": src}
        url = f"{TT}/post/publish/inbox/video/init/"
    r = requests.post(url, headers=head, json=body, timeout=60).json()
    if r.get("error", {}).get("code", "ok") != "ok":
        raise RuntimeError(f"TikTok init: {r}")
    pid, up = r["data"]["publish_id"], r["data"]["upload_url"]
    put = requests.put(up, data=video.read_bytes(), timeout=600,
                       headers={"Content-Type": "video/mp4", "Content-Range": f"bytes 0-{size - 1}/{size}"})
    if put.status_code >= 400:
        raise RuntimeError(f"TikTok upload {put.status_code}: {put.text[:300]}")
    if mode != "direct":
        CAPTIONS.parent.mkdir(parents=True, exist_ok=True)
        with CAPTIONS.open("a", encoding="utf-8") as f:
            f.write(f"===== #{row['num']} {row['file']} ({ph._now():%d.%m %H:%M})\n{caption(row, 'tt')}\n\n")
    return pid


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", choices=["ig", "tiktok"], required=True)
    ap.add_argument("--count", type=int, default=1, help="сколько роликов за запуск (по умолчанию 1)")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args(argv)
    order, rows = ph.load_pack()
    left = [rows[n] for n in order if n not in done(a.platform)]
    if not left:
        print("выкладывать нечего — все ролики уже выложены")
        return 0
    batch = left[:a.count]
    for r in batch:
        video = ph.GIRL / "final" / r["file"]
        if not video.exists():
            raise SystemExit(f"нет ролика final/{r['file']}")
        print(f"{a.platform}: #{r['num']} {r['file']} — {r['title']} (осталось {len(left)})")
        if a.dry:
            print(caption(r, a.platform))
            continue
        if not a.yes:
            print("без --yes ничего не выкладывается")
            return 0
        try:
            mid = ig_post(r, video) if a.platform == "ig" else tt_post(r, video)
        except Exception as e:
            print(f"  ОШИБКА: {type(e).__name__}: {str(e)[:400]}")
            return 1
        record(r, a.platform, mid)
        print(f"  готово: {mid}", flush=True)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
