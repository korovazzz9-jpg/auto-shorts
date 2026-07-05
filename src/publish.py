"""Общая логика публикации одного готового видео на все площадки.

Используется и `pipeline.py` (обычные Shorts), и `pipeline_series.py` (серии) —
чтобы оркестрация загрузки (YouTube → плейлист → коммент → субтитры → Cloudinary/IG/TikTok
→ Pinterest) жила в ОДНОМ месте и не рассинхронизировалась между пайплайнами.
"""
import os
import random

from datetime import datetime, timezone

from cloudinary_upload import delete_image, delete_video, upload_image, upload_video as upload_to_cloudinary
from config import CFG
from notify import notify
from post_comment import post_channel_comment, post_comment_reply
from upload_captions import upload_captions
from upload_instagram import upload_photo, upload_reel
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
    # Источник факта (2026-07-05): повышает доверие, снижает «это фейк» в комментах, даёт
    # поисковые ключи. Модель возвращает пусто, если не уверена в происхождении —
    # выдуманный источник хуже отсутствия (инструкция в generate_script).
    source_note = str(data.get("source_note", "")).strip()
    if source_note:
        description += f"\n\n{CFG.get('source_label', 'Source:')} {source_note}"
    if longform_url:
        desc_cta = CFG.get("longform_desc_cta", "Full deep-dives on the channel:")
        description += f"\n\n▶ {desc_cta} {longform_url}"

    # Кросс-промо EN↔ES (2026-07-02): реальная билингвальная аудитория пересекается —
    # ссылка на сестринский канал почти ничего не стоит и может перетянуть подписчиков
    # в обе стороны. Пул фраз (random.choice), не один статичный текст.
    sister_handle = CFG.get("sister_channel_handle", "")
    sister_ctas = CFG.get("sister_desc_ctas", [])
    if sister_handle and sister_ctas:
        sister_cta = random.choice(sister_ctas)
        description += f"\n\n{sister_cta} https://www.youtube.com/@{sister_handle}"

    # Билингвальные теги (2026-07-02): пара generic discovery-тегов НА ДРУГОМ языке —
    # шанс попасть в рекомендации зрителю, который смотрит на двух языках. Не топик-
    # специфичные (те и так на языке канала), а самые общие ("facts"/"datos curiosos").
    tags = list(data["tags"]) + list(extra_tags) + list(CFG.get("sister_lang_tags", []))

    print("Загрузка на YouTube...")
    video_id = upload_to_youtube(
        video_path,
        title=data["title"],
        description=description,
        tags=tags,
        hashtags=data["hashtags"],
        hashtag_position=data["hashtag_position"],
        thumbnail_path=thumb_path,
        default_language=CFG["lang_code"],
    )
    # Локализация метаданных (2026-07-03) — СОЗНАТЕЛЬНО только для лонгформа
    # (pipeline_longform.py), не здесь: риск для Shorts/серий — зритель кликает по знакомому
    # переведённому заголовку, слышит озвучку на другом языке, отваливается за секунды →
    # бьёт по retention-порогу (65%/50%, см. analytics_retention.retention_threshold) и
    # алгоритм обрывает раздачу. На лонгформе зритель терпимее к смене языка ради разбора.

    # Плейлисты для Shorts отключены: 0 открытий (Shorts смотрят в ленте, не через
    # плейлисты), а каждый ролик тратил ~50 ед. квоты YouTube. Лонгформ плейлисты сохраняет
    # (свой pipeline_longform).
    try:
        channel_url = f"https://www.youtube.com/@{CFG['channel_handle']}" if CFG.get("channel_handle") else ""
        comment_template = CFG.get("first_comment", "")
        # Выкидываем строки про плейлист — плейлистов у Shorts больше нет.
        lines = [ln for ln in comment_template.split("\n") if "{playlist_url}" not in ln]
        comment = "\n".join(lines).format(channel_url=channel_url).strip()
        # Фактоспецифичный вопрос (2026-07-04): модель отдаёт comment_question в том же
        # вызове генерации — вопрос про КОНКРЕТНЫЙ факт собирает больше ответов, чем
        # генерик «ты это знал?» (comment density — топ-сигнал ранжирования). Заменяет
        # первую (генерик-провокация) строку шаблона, строка подписки остаётся. Замена
        # ПОСЛЕ .format() — чтобы случайные фигурные скобки в тексте модели не уронили его.
        fact_q = str(data.get("comment_question", "")).strip()
        if fact_q and comment:
            comment_lines = comment.split("\n")
            comment_lines[0] = fact_q
            comment = "\n".join(comment_lines)
        # Строка подписки из пула (2026-07-05): раньше это была ЕДИНСТВЕННАЯ дословно
        # одинаковая строка на 100% видео канала — "bot-like pattern" сигнал спам-детекции.
        # Заменяет ВТОРУЮ строку (первая уже заменена fact_q выше). Тот же паттерн, что
        # first_comment_replies. Пусто в конфиге → строка остаётся как в шаблоне.
        subscribe_ctas = CFG.get("first_comment_subscribe_ctas", [])
        if subscribe_ctas and comment:
            comment_lines = comment.split("\n")
            if len(comment_lines) >= 2:
                comment_lines[1] = random.choice(subscribe_ctas).format(channel_url=channel_url)
                comment = "\n".join(comment_lines)
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
                # CTA (2026-07-02): подпись раньше не звала ни подписаться, ни перейти в
                # био — единственное место со ссылкой на YouTube. Пул фраз, не один текст.
                ig_ctas = CFG.get("ig_caption_ctas", [])
                ig_cta = random.choice(ig_ctas) if ig_ctas else ""
                caption = f"{data['title']}\n\n{data['script']}"
                if ig_cta:
                    caption += f"\n\n{ig_cta}"
                caption += f"\n\n{' '.join(ig_tags)}"
                upload_reel(hosted["url"], caption, cover_url=hosted_thumb["url"])
                print("  Instagram: опубликовано")

                # IG-карточка факта (2026-07-05): раз в день (первый слот, ig_card_slot_hour)
                # в ленту постится ещё и СТАТИЧНАЯ карточка — другой формат в той же ленте,
                # больше касаний без нового контента. Генератор переиспользован из Pinterest
                # (build_pin_card — чистый PIL, Pinterest API не нужен). Сбой карточки не
                # роняет остальной кросс-постинг (alert + continue).
                if datetime.now(timezone.utc).hour == CFG.get("ig_card_slot_hour", -1):
                    hosted_card = None
                    try:
                        from upload_pinterest import build_pin_card
                        sentences = [s.strip() for s in data["script"].replace("!", ".").replace("?", ".").split(".") if s.strip()]
                        fact_text = ". ".join(sentences[:2]) + "."
                        card_path = build_pin_card(data["title"], fact_text, CFG["channel_handle"])
                        hosted_card = upload_image(card_path)
                        card_caption = data["title"]
                        if ig_cta:
                            card_caption += f"\n\n{ig_cta}"
                        card_caption += f"\n\n{' '.join(ig_tags)}"
                        upload_photo(hosted_card["url"], card_caption)
                        print("  Instagram: карточка опубликована")
                    except Exception as e:
                        alert("IG card", e)
                    finally:
                        if hosted_card:
                            try:
                                delete_image(hosted_card["public_id"])
                            except Exception as e:
                                print(f"  Не удалось удалить карточку из Cloudinary: {e}")

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
