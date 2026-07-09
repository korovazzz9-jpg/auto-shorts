"""Месячная компиляция-лонгформ: топ-Shorts канала за последний месяц пересобираются в одно
горизонтальное видео 5-7 минут («Best facts of <месяц>»).

Зачем: факты УЖЕ проверены просмотрами (никакой лотереи дискавери), скрипты уже написаны
(лежат в description опубликованных видео — см. publish.py), Claude пишет только
интро/переходы/аутро — почти бесплатные часы просмотра для порога монетизации (4000 ч).

Механика: НЕ склейка видеофайлов (исходников нет — рендер живёт в tempdir воркфлоу), а
пересборка: скрипты фактов из description → связки от Claude → TTS → свежие горизонтальные
стоки → build_longform_video. Главы описания строятся по РЕАЛЬНЫМ таймингам TTS (границы
фактов известны по числу слов — надёжнее, чем sentence_index от модели).

Запуск: 1-го числа месяца (monthly-compilation.yml), оба канала.
"""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

from anthropic import Anthropic
from dotenv import load_dotenv

from build_longform_video import build_longform_video
from config import CFG
from fetch_stock_video import fetch_clips
from notify import notify
from pipeline_longform import _alert, _longform_tts, _verify_channel
from post_comment import post_channel_comment, post_comment_reply
from recycle_winners import _extract_script, _fetch_videos
from upload_captions import upload_captions
from upload_youtube import upload_video as upload_to_youtube
from youtube_auth import get_client

load_dotenv()

TOP_N = 8             # сколько лучших фактов месяца входит в компиляцию
LOOKBACK_VIDEOS = 150  # сколько последних видео просмотреть (покрывает месяц с запасом)
MIN_FACTS = 5         # меньше — компиляция слишком короткая, прогон отменяется
MAX_SHORT_SECONDS = 65  # отсекаем лонгформы/компиляции прошлых месяцев


def _top_shorts() -> list[dict]:
    """Топ-TOP_N Shorts за последний месяц по просмотрам, с извлечённым из description
    скриптом. Серии исключены (части вырваны из общего сюжета плохо стоят в компиляции)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    vids = _fetch_videos(get_client(), LOOKBACK_VIDEOS, with_stats=True)
    pool = [
        v for v in vids
        if v["seconds"] <= MAX_SHORT_SECONDS
        and v["published"] >= cutoff
        and not any(t.startswith("series-part-") for t in v["tags"])
    ]
    pool.sort(key=lambda v: -v["views"])

    top = []
    for v in pool:
        script = _extract_script(v["description"])
        if len(script.split()) >= 40:  # описание без полноценного скрипта — пропускаем
            v["script"] = script
            top.append(v)
        if len(top) >= TOP_N:
            break
    return top


def _month_label() -> str:
    """Название прошлого месяца (компиляция выходит 1-го числа ЗА предыдущий месяц)."""
    first_of_current = datetime.now(timezone.utc).replace(day=1)
    return (first_of_current - timedelta(days=1)).strftime("%B %Y")


def _generate_glue(facts: list[dict]) -> dict:
    """Интро/переходы/аутро + метаданные от Claude. Скрипты фактов НЕ переписываются —
    они уже проверены просмотрами, модель пишет только связки."""
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=5)
    facts_block = "\n\n".join(
        f"FACT {i + 1} (original title: {f['title']}):\n{f['script']}"
        for i, f in enumerate(facts)
    )
    n = len(facts)
    prompt = (
        f"These are the {n} top-performing short fact scripts from our channel "
        f"({CFG['channel_name']}) for {_month_label()}. We are compiling them VERBATIM into "
        "one longer video. Write ONLY the connective tissue in "
        f"{CFG['script_language']}:\n\n{facts_block}\n\n"
        "Requirements:\n"
        "- intro: 2 punchy sentences opening the compilation (hook first — why these facts "
        "broke people's brains this month; no 'welcome to the channel' filler).\n"
        f"- transitions: EXACTLY {n - 1} short bridge sentences (5-10 words each), transition i "
        "leads from fact i into fact i+1. Vary them — no repeated template.\n"
        "- outro: 1-2 sentences: payoff + ask to subscribe and comment which fact won.\n"
        f"- title: compilation title in {CFG['script_language']}, under 70 chars, must read as "
        "a best-of for the month (mention the month naturally).\n"
        "- thumb_text: 3-5 word thumbnail phrase, instantly readable.\n"
        f"- tags: 10-15 YouTube search tags in {CFG['script_language']}.\n"
        f"- hashtags: 3-5 hashtags in {CFG['script_language']} (lowercase, # prefix).\n"
        "- search_summary: ONE keyword-dense sentence (max 25 words) describing the compilation "
        f"for YouTube search, in {CFG['script_language']}.\n"
        f"- video_queries: {n * 2} stock-footage search queries (2-4 words, English, wide "
        "scenes/landscapes/human action) — 2 per fact, in fact order.\n\n"
        "Respond strictly in JSON, no markdown wrapper: "
        '{"intro": "...", "transitions": ["...", ...], "outro": "...", "title": "...", '
        '"thumb_text": "...", "tags": [...], "hashtags": [...], "search_summary": "...", '
        '"video_queries": [...]}'
    )

    data, last_err = None, None
    for attempt in range(3):
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        start, end = raw.find("{"), raw.rfind("}")
        try:
            candidate = json.loads(raw[start:end + 1])
            missing = [k for k in ("intro", "transitions", "outro", "title", "video_queries")
                       if not candidate.get(k)]
            if missing:
                raise ValueError(f"в JSON нет полей {missing}")
            if len(candidate["transitions"]) < n - 1:
                raise ValueError(f"переходов {len(candidate['transitions'])}, нужно {n - 1}")
            data = candidate
            break
        except (json.JSONDecodeError, ValueError) as e:
            last_err = e
            print(f"  Compilation JSON parse failed (attempt {attempt + 1}/3): {e}; retrying...")
    if data is None:
        raise RuntimeError(f"Compilation JSON невалиден после 3 попыток: {last_err}")
    return data


def _assemble_script(facts: list[dict], glue: dict) -> tuple[str, list[int]]:
    """Собирает полный скрипт и возвращает (script, границы фактов в СЛОВАХ) — по границам
    после TTS строятся главы с реальными таймингами."""
    parts = [glue["intro"].strip()]
    boundaries = []  # индекс слова, с которого начинается каждый факт
    word_count = len(parts[0].split())
    transitions = [str(t).strip() for t in glue["transitions"]]
    for i, f in enumerate(facts):
        if i > 0:
            t = transitions[i - 1] if i - 1 < len(transitions) else ""
            if t:
                parts.append(t)
                word_count += len(t.split())
        boundaries.append(word_count)
        parts.append(f["script"].strip())
        word_count += len(f["script"].split())
    parts.append(glue["outro"].strip())
    return " ".join(parts), boundaries


def _chapters_block(words: list[dict], boundaries: list[int], titles: list[str]) -> str:
    """Главы по реальным таймингам TTS. Требования YouTube: 0:00 первая, ≥3 глав, ≥10с между."""
    if not words:
        return ""
    # 2026-07-09: было бинарным en/else — для PT совпало случайно (по-португальски тоже
    # "Capítulos"), но конструкция не переживёт следующий язык. per-channel label, как
    # source_label/остальные локализованные строки.
    label = CFG.get("chapters_label", "Chapters:")
    entries = [(0.0, "Intro")]
    for wi, title in zip(boundaries, titles):
        t = words[min(wi, len(words) - 1)]["start"]
        entries.append((t, title[:60]))

    # Интро короче 10с (2 предложения ≈ 9-10с) — иначе фильтр ниже выкинул бы главу
    # ПЕРВОГО факта. Глава первого факта поглощает Intro и стартует с 0:00.
    if len(entries) >= 2 and entries[1][0] < 10.0:
        entries[0] = (0.0, entries[1][1])
        entries.pop(1)

    filtered = [entries[0]]
    for t, title in entries[1:]:
        if t - filtered[-1][0] >= 10.0:
            filtered.append((t, title))
    if len(filtered) < 3:
        return ""
    lines = [label]
    for t, title in filtered:
        m, s = int(t) // 60, int(t) % 60
        lines.append(f"{m}:{s:02d} {title}")
    return "\n".join(lines)


def run() -> None:
    _verify_channel()
    print(f"1/5 Топ-Shorts за месяц ({CFG['channel_name']})...")
    facts = _top_shorts()
    if len(facts) < MIN_FACTS:
        print(f"  Найдено только {len(facts)} фактов со скриптами (<{MIN_FACTS}) — компиляцию пропускаем.")
        notify(f"⚠️ [{CFG['channel_name']}] компиляция месяца пропущена: мало фактов ({len(facts)}).")
        return
    for f in facts:
        print(f"  {f['views']:6} views — {f['title'][:60]}")

    print("2/5 Генерация связок (интро/переходы/аутро)...")
    glue = _generate_glue(facts)
    print(f"  Заголовок: {glue['title']}")
    script, boundaries = _assemble_script(facts, glue)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        audio_path = os.path.join(tmp, "audio.mp3")
        video_path = os.path.join(tmp, "video.mp4")

        print("3/5 Стоковые клипы (горизонтальные)...")
        clip_paths = fetch_clips(glue["video_queries"], tmp, landscape=True)

        print("4/5 Озвучка и сборка...")
        words = _longform_tts(script, audio_path)
        video_path, thumb_path = build_longform_video(
            audio_path, clip_paths, words, video_path,
            title=glue["title"], thumb_text=glue.get("thumb_text"),
        )

        print("5/5 Загрузка на YouTube...")
        description = script
        search_summary = str(glue.get("search_summary", "")).strip()
        if search_summary:
            description = f"{search_summary}\n\n{description}"
        chapters = _chapters_block(words, boundaries, [f["title"] for f in facts])
        if chapters:
            description += f"\n\n{chapters}"
        sister_handle = CFG.get("sister_channel_handle", "")
        sister_ctas = CFG.get("sister_desc_ctas", [])
        if sister_handle and sister_ctas:
            import random
            description += f"\n\n{random.choice(sister_ctas)} https://www.youtube.com/@{sister_handle}"

        video_id = upload_to_youtube(
            video_path,
            title=glue["title"],
            description=description,
            tags=list(glue.get("tags", [])) + list(CFG.get("sister_lang_tags", [])),
            hashtags=glue.get("hashtags", []),
            hashtag_position="end",
            thumbnail_path=thumb_path,
            default_language=CFG["lang_code"],
        )

    try:
        from localize_metadata import add_sister_localization
        add_sister_localization(video_id, glue["title"], description)
    except Exception as e:
        _alert("localization", e)

    try:
        upload_captions(video_id, words)
    except Exception as e:
        _alert("captions", e)

    try:
        channel_url = f"https://www.youtube.com/@{CFG['channel_handle']}" if CFG.get("channel_handle") else ""
        comment = CFG.get("longform_comment", "").format(channel_url=channel_url).strip()
        if comment:
            comment_id = post_channel_comment(video_id, comment)
            import random
            replies = CFG.get("first_comment_replies", [])
            if replies:
                try:
                    post_comment_reply(comment_id, random.choice(replies))
                except Exception as e:
                    _alert("comment reply", e)
    except Exception as e:
        _alert("comment", e)

    # Воронка Shorts→лонгформ: компиляция становится последним лонгформом (без темы —
    # by_topic не трогаем, тематические ссылки остаются на настоящие deep-dive).
    try:
        from longform_link import set_last_longform
        set_last_longform(video_id)
    except Exception as e:
        _alert("last-longform-link", e)

    url = f"https://youtube.com/watch?v={video_id}"
    notify(
        f"✅ [{CFG['channel_name']}] компиляция месяца опубликована:\n{glue['title']}\n{url}\n\n"
        f"📌 Не забудь добавить End Screen вручную в YouTube Studio."
    )
    print(f"Готово: {url}")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        notify(f"🔴 [{CFG['channel_name']}] компиляция месяца УПАЛА:\n{e}")
        raise
