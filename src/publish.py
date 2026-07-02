"""Общая логика публикации одного готового видео на все площадки.

Используется и `pipeline.py` (обычные Shorts), и `pipeline_series.py` (серии) —
чтобы оркестрация загрузки (YouTube → плейлист → коммент → субтитры → Cloudinary/IG/TikTok
→ Pinterest) жила в ОДНОМ месте и не рассинхронизировалась между пайплайнами.
"""
import os
import random

from cloudinary_upload import delete_image, delete_video, upload_image, upload_video as upload_to_cloudinary
from config import CFG
from notify import notify
from post_comment import post_channel_comment, post_comment_reply
from upload_captions import upload_captions
from upload_instagram import upload_reel
from upload_pinterest import upload_pin
from upload_tiktok import upload_video as upload_to_tiktok, wait_for_publish
from upload_youtube import upload_video as upload_to_youtube


def publish(
    *,
    data: dict,
    video_path: str,
    thumb_path: str,
    words: list,
    topic: str,
    alert,
    extra_tags=(),
    extra_comment: str = "",
    enable_captions: bool = False,
    enable_pinterest: bool = False,
) -> str:
    """Заливает видео на YouTube и кросс-постит. Возвращает video_id.

    `alert(step, err)` — колбэк для частичных сбоев (видео уже вышло, шаг отвалился),
    каждый пайплайн передаёт свой с нужным префиксом (канал / "Part N").
    Субтитры и Pinterest по умолчанию выключены — включаются явно.
    """
    # Воронка Shorts→лонгформ: приоритет — лонгформ на ТУ ЖЕ тему (выше релевантность/CTR),
    # иначе последний лонгформ вообще («глубокий разбор» как формат). Пусто, если лонгформов
    # ещё не было.
    longform_url = ""
    try:
        from longform_link import get_last_longform_url
        longform_url = get_last_longform_url(topic)
    except Exception:
        longform_url = ""

    # SEO-строка первой: разговорный скрипт (хук специально скрывает субъект) почти не
    # содержит ключевых слов, по которым ищут в YouTube Search — search_summary называет
    # факт прямо, для находимости. Не озвучивается и не показывается на экране.
    description = data["script"]
    search_summary = str(data.get("search_summary", "")).strip()
    if search_summary:
        description = f"{search_summary}\n\n{description}"
    if longform_url:
        desc_cta = CFG.get("longform_desc_cta", "Full deep-dives on the channel:")
        description += f"\n\n▶ {desc_cta} {longform_url}"

    print("Загрузка на YouTube...")
    video_id = upload_to_youtube(
        video_path,
        title=data["title"],
        description=description,
        tags=list(data["tags"]) + list(extra_tags),
        hashtags=data["hashtags"],
        hashtag_position=data["hashtag_position"],
        thumbnail_path=thumb_path,
    )

    # Плейлисты для Shorts отключены: 0 открытий (Shorts смотрят в ленте, не через
    # плейлисты), а каждый ролик тратил ~50 ед. квоты YouTube. Лонгформ плейлисты сохраняет
    # (свой pipeline_longform).
    try:
        channel_url = f"https://www.youtube.com/@{CFG['channel_handle']}" if CFG.get("channel_handle") else ""
        comment_template = CFG.get("first_comment", "")
        # Выкидываем строки про плейлист — плейлистов у Shorts больше нет.
        lines = [ln for ln in comment_template.split("\n") if "{playlist_url}" not in ln]
        comment = "\n".join(lines).format(channel_url=channel_url).strip()
        if longform_url:  # та же воронка — ссылка на лонгформ в закреп-комменте
            comment_cta = CFG.get("longform_comment_cta", "Want the full story?")
            comment = (comment + f"\n\n▶ {comment_cta} {longform_url}").strip()
        if extra_comment:  # серии: ссылка на плейлист (+ прямые ссылки на части в Part 3)
            comment = (comment + "\n\n" + extra_comment).strip()
        if comment:
            comment_id = post_channel_comment(video_id, comment)
            # #3 Само-ответ → мини-тред (engagement density). Пул вариантов из CFG — один и
            # тот же текст под каждым видео выглядел ботово.
            replies = CFG.get("first_comment_replies", [])
            reply = random.choice(replies) if replies else ""
            if reply:
                try:
                    post_comment_reply(comment_id, reply)
                except Exception as e:
                    alert("comment reply", e)
    except Exception as e:
        alert("first comment", e)

    # Субтитры жгут ~1200 ед. квоты YouTube/видео — включать только когда квота позволяет.
    if enable_captions:
        try:
            upload_captions(video_id, words)
        except Exception as e:
            alert("captions", e)

    need_cloudinary = CFG["post_to_instagram"] or CFG.get("post_to_tiktok")
    if need_cloudinary:
        print("Загрузка в облако (Cloudinary) и публикация...")
        hosted = None
        hosted_thumb = None
        try:
            hosted = upload_to_cloudinary(video_path)
            if CFG["post_to_instagram"]:
                hosted_thumb = upload_image(thumb_path)
                # #shorts на IG бесполезен (это ютубовский тег) — меняем на Reels-нативные,
                # они реально влияют на попадание в Reels-ленту.
                ig_tags = []
                for t in data["hashtags"]:
                    if t.lower() == "#shorts":
                        ig_tags += ["#reels", "#reelsinstagram"]
                    else:
                        ig_tags.append(t)
                caption = f"{data['title']}\n\n{data['script']}\n\n{' '.join(ig_tags)}"
                upload_reel(hosted["url"], caption, cover_url=hosted_thumb["url"])
                print("  Instagram: опубликовано")

            if CFG.get("post_to_tiktok"):
                try:
                    publish_id = upload_to_tiktok(hosted["url"], data["title"], data["hashtags"])
                    token = os.environ["TIKTOK_ACCESS_TOKEN"]
                    status = wait_for_publish(publish_id, token)
                    print(f"  TikTok: {status}")
                except Exception as e:
                    alert("TikTok", e)
        except Exception as e:
            alert("Cloudinary/Instagram", e)
        finally:
            if hosted:
                try:
                    delete_video(hosted["public_id"])
                except Exception as e:
                    print(f"  Не удалось удалить временный файл из Cloudinary: {e}")
            if hosted_thumb:
                try:
                    delete_image(hosted_thumb["public_id"])
                except Exception as e:
                    print(f"  Не удалось удалить thumbnail из Cloudinary: {e}")

    if enable_pinterest and CFG.get("post_to_pinterest"):
        try:
            upload_pin(data["title"], data["script"], CFG["channel_handle"], video_id)
        except Exception as e:
            alert("Pinterest", e)

    url = f"https://youtube.com/shorts/{video_id}"
    notify(f"✅ [{CFG['channel_name']}] видео опубликовано:\n{data['title']}\n{url}")
    return video_id
