"""Черновики ответов на комментарии зрителей + одобрение кнопкой в Telegram (2026-07-08).

2026-07-08: работает ЛОКАЛЬНО (Планировщик заданий Windows, run_comment_agent.bat), НЕ в
GitHub Actions — сознательно, чтобы не платить Actions-минутами за то, что можно бесплатно
гонять на своей машине только в будни днём. Планировщик: будни, 10:00-19:00 МСК, раз в час
(время системных часов — если ОС не в МСК, поправить расписание). Состояние
(comment_agent_state.json) — локальный файл, в git НЕ коммитится (см. .gitignore).

Каждый прогон делает ДВЕ вещи по очереди для обоих каналов (EN/ES) в ОДНОМ процессе:

1. Разбирает НАЖАТИЯ кнопок с прошлого запуска (Telegram getUpdates, offset из состояния).
   Это единственный способ ловить callback БЕЗ постоянно работающего сервера/веб-хука —
   ровно то, что нужно при схеме "раз в N часов, иначе процесс не живёт". ВАЖНО: только
   ОДИН процесс может звать getUpdates для одного бота — если бы EN и ES дёргали его
   независимо, один прогон "съедал" бы offset и второй канал никогда не увидел бы нажатие
   на СВОё сообщение. Поэтому это единый скрипт на оба канала, а не CHANNEL=en/es запуск
   дважды, как остальной пайплайн.

2. Ищет НОВЫЕ комментарии зрителей (commentThreads.list с allThreadsRelatedToChannelId —
   ОДИН вызов на весь канал = 1 квота-юнит, не по видео) и для каждого нового (без
   собственных комментариев канала, с капом за прогон — MAX_NEW_PER_RUN) генерит через
   Claude перевод на русский + 3 варианта ответа (тоже с переводом), шлёт в Telegram с
   inline-кнопками 1/2/3/Skip.

ВАЖНО про задержку: апрув учитывается только СЛЕДУЮЩИМ прогоном (нет постоянного сервера,
только периодический polling) — при интервале раз в час между нажатием кнопки и реальной
публикацией ответа может пройти до часа (и, вне окна 10-19 МСК/выходных — до следующего
рабочего окна). Если критично — сократить интервал в Планировщике, локальному запуску это
ничего не стоит (в отличие от прежней GH Actions-версии).

Квота YouTube (доминирующий бесплатный ресурс, 10 000 юнитов/день, общий пул) — НЕ узкое
место: commentThreads.list = 1 юнит/канал/прогон, comments.insert (реальная публикация,
только при апруве) = 50 юнитов — даже 20 ответов/день = 1000 из 10 000 (см. README, разбор
квоты 2026-07-03). Единственная реальная стоимость теперь — Claude Haiku за черновик
(перевод + варианты ответа), ~$0.0014/комментарий — см. README.

Не постит НИЧЕГО автоматически — только предлагает в Telegram, публикация СТРОГО по
кнопке. Тот же принцип, что и весь проект: автоматизируем обнаружение/черновик, решение
и подтверждение действия — за человеком.

Известное ограничение масштаба: commentThreads.list берёт последние MAX_FETCH=20
комментариев канала ЦЕЛИКОМ (не постранично) — если за один интервал прилетит больше 20
новых комментариев по всем видео сразу, самые старые из них выпадут из окна и не будут
замечены (на текущих объёмах — единицы комментариев на видео — маловероятно; при росте
канала можно поднять MAX_FETCH или добавить пагинацию)."""
import json
import os
import time

import requests
from anthropic import Anthropic
from dotenv import load_dotenv

from config import CONFIGS
from youtube_auth import get_client

load_dotenv()

STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "comment_agent_state.json")

MAX_NEW_PER_RUN = 5        # на канал за прогон — не заспамить Telegram/Claude при вирусном ролике
MAX_FETCH = 20              # сколько последних комментариев канала смотрим перед фильтрацией
PENDING_MAX_AGE_DAYS = 3    # висящие без апрува дольше — считаем неактуальными, чистим
SEEN_MAX_PER_CHANNEL = 3000  # скользящее окно "уже видели" — не даём файлу расти бесконечно

CHANNEL_TOKENS = {
    "en": os.environ.get("YT_REFRESH_TOKEN", ""),
    "es": os.environ.get("YT_REFRESH_TOKEN_ES", ""),
}


def _load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _channel_state(state: dict, channel: str) -> dict:
    return state.setdefault(channel, {"seen": [], "pending": {}, "next_id": 1})


def _tg(method: str, **params) -> dict:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    resp = requests.post(f"https://api.telegram.org/bot{token}/{method}", json=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


# --- Шаг 1: разбор апрувов с прошлого прогона -------------------------------------------

def _process_approvals(state: dict) -> None:
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        return
    offset = state.get("telegram_offset", 0) + 1
    try:
        updates = _tg("getUpdates", offset=offset, timeout=0).get("result", [])
    except Exception as e:
        print(f"  getUpdates упал: {e}")
        return

    for upd in updates:
        state["telegram_offset"] = upd["update_id"]
        cq = upd.get("callback_query")
        if not cq:
            continue
        data = cq.get("data", "")
        message_id = cq.get("message", {}).get("message_id")
        chat_id = cq.get("message", {}).get("chat", {}).get("id")
        try:
            _tg("answerCallbackQuery", callback_query_id=cq["id"])  # убрать "часики" на кнопке
        except Exception:
            pass

        parts = data.split(":")
        if len(parts) < 3 or parts[1] not in CONFIGS:
            continue
        action, channel, short_id = parts[0], parts[1], parts[2]
        ch_state = _channel_state(state, channel)
        item = ch_state["pending"].pop(short_id, None)
        if not item:
            continue  # уже обработано/истекло

        if action == "skip":
            _edit_reviewed_message(chat_id, message_id, item, "⏭ Пропущено")
            continue
        if action != "a" or len(parts) < 4:
            continue
        try:
            choice = int(parts[3])
            reply_text = item["replies"][choice]["text"]
        except (ValueError, IndexError):
            continue

        try:
            token = CHANNEL_TOKENS.get(channel)
            if not token:
                raise RuntimeError(f"нет YT-токена для канала {channel}")
            youtube = get_client(refresh_token=token)
            youtube.comments().insert(
                part="snippet",
                body={"snippet": {"parentId": item["comment_id"], "textOriginal": reply_text}},
            ).execute()
            _edit_reviewed_message(chat_id, message_id, item, f"✅ Опубликовано:\n{reply_text}")
            print(f"  [{channel}] ответ опубликован на comment_id={item['comment_id']}")
        except Exception as e:
            print(f"  [{channel}] публикация ответа упала: {e}")
            # reply_text — в самом алерте: item уже вынут из pending (retry-кнопки больше нет),
            # без текста пользователь не смог бы даже вручную запостить одобренный ответ.
            _tg_notify_fallback(
                chat_id,
                f"⚠️ Не удалось опубликовать ответ ({channel}): {e}\n\n"
                f"Текст ответа (запости вручную, если нужно):\n{reply_text}\n\n"
                f"На комментарий: {item['comment_id']}"
            )


def _edit_reviewed_message(chat_id, message_id, item: dict, result_line: str) -> None:
    if not chat_id or not message_id:
        return
    try:
        text = f"{item.get('review_text', '')}\n\n{result_line}"
        _tg("editMessageText", chat_id=chat_id, message_id=message_id, text=text[:4000])
    except Exception:
        pass  # не критично — состояние уже обновлено, апрув не потеряется


def _tg_notify_fallback(chat_id, text: str) -> None:
    try:
        _tg("sendMessage", chat_id=chat_id or os.environ.get("TELEGRAM_CHAT_ID"), text=text[:4000])
    except Exception:
        pass


# --- Шаг 2: поиск новых комментариев + черновики ----------------------------------------

def _fetch_recent_comments(youtube) -> tuple[list[dict], str]:
    """allThreadsRelatedToChannelId требует явный channel id (не принимает "mine") —
    получаем его отдельным дешёвым вызовом (channels().list, part=id, mine=True, 1 юнит)."""
    my_channel_id = youtube.channels().list(part="id", mine=True).execute()["items"][0]["id"]
    resp = youtube.commentThreads().list(
        part="snippet", allThreadsRelatedToChannelId=my_channel_id,
        order="time", maxResults=MAX_FETCH, textFormat="plainText",
    ).execute()
    out = []
    for item in resp.get("items", []):
        top = item["snippet"]["topLevelComment"]["snippet"]
        out.append({
            "comment_id": item["snippet"]["topLevelComment"]["id"],
            "video_id": item["snippet"]["videoId"],
            "text": top.get("textOriginal", ""),
            "author_channel_id": top.get("authorChannelId", {}).get("value", ""),
            "author": top.get("authorDisplayName", ""),
        })
    return out, my_channel_id


def _fetch_titles(youtube, video_ids: list[str]) -> dict[str, str]:
    """Заголовки видео батчем (1 юнит за вызов, до 50 id) — для контекста в промпте Claude
    и в тексте Telegram-сообщения. Отсутствующий/приватный video_id — просто не попадёт в словарь."""
    unique = list(dict.fromkeys(video_ids))
    titles = {}
    for i in range(0, len(unique), 50):
        batch = unique[i:i + 50]
        resp = youtube.videos().list(part="snippet", id=",".join(batch)).execute()
        for v in resp.get("items", []):
            titles[v["id"]] = v["snippet"].get("title", "")
    return titles


def _draft_replies(comment_text: str, video_title: str) -> dict | None:
    """Возвращает {"comment_ru": str, "replies": [{"text","ru"}, ...]} (0-3 варианта).
    Пусто — комментарий спам/враждебный/бессмысленный, честный отказ вместо натяжки
    (тот же принцип, что source_note/pair_resolved в остальном пайплайне)."""
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=3)
    prompt = (
        f"A viewer left this comment on our YouTube Shorts video (title: \"{video_title}\"):\n"
        f"\"{comment_text}\"\n\n"
        "1. Translate the comment to Russian (comment_ru).\n"
        "2. Write up to 3 DIFFERENT short reply variants in the SAME language as the comment — "
        "friendly, specific, no engagement bait, no generic filler like 'thanks so much!'. If the "
        "comment asks a factual question, answer honestly — if you don't actually know, say so, "
        "don't invent specifics. If the comment is spam, hostile, or nonsensical, return an EMPTY "
        "replies list instead of forcing a reply.\n"
        "3. Translate each reply variant to Russian too (ru field).\n\n"
        "Respond strictly in JSON, no markdown wrapper: "
        '{"comment_ru": "...", "replies": [{"text": "...", "ru": "..."}]} (0 to 3 items)'
    )
    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=700,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        start, end = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[start:end + 1])
        replies = [r for r in data.get("replies", [])
                   if isinstance(r, dict) and r.get("text") and r.get("ru")][:3]
        return {"comment_ru": str(data.get("comment_ru", "")).strip(), "replies": replies}
    except Exception as e:
        print(f"  черновик ответа упал: {e}")
        return None


def _check_channel(channel: str, state: dict) -> None:
    token = CHANNEL_TOKENS.get(channel)
    if not token:
        print(f"  [{channel}] нет YT-токена, пропускаем.")
        return
    cfg = CONFIGS[channel]
    ch_state = _channel_state(state, channel)
    seen = set(ch_state["seen"])

    # Чистим протухшие pending (без апрува дольше PENDING_MAX_AGE_DAYS) — не даём файлу
    # расти и не рискуем публиковать давно неактуальный черновик по случайному апруву.
    now = time.time()
    stale = [sid for sid, it in ch_state["pending"].items()
             if now - it.get("created_at", now) > PENDING_MAX_AGE_DAYS * 86400]
    for sid in stale:
        ch_state["pending"].pop(sid, None)

    youtube = get_client(refresh_token=token)
    try:
        comments, my_channel_id = _fetch_recent_comments(youtube)
    except Exception as e:
        print(f"  [{channel}] не удалось получить комментарии: {e}")
        return

    new_comments = [c for c in comments
                    if c["comment_id"] not in seen and c["author_channel_id"] != my_channel_id]
    # Все просмотренные (даже отфильтрованные/собственные) помечаем viewed — иначе будем
    # каждый прогон заново тратить вызов Claude на один и тот же спам/самокомментарий.
    for c in comments:
        seen.add(c["comment_id"])

    titles = _fetch_titles(youtube, [c["video_id"] for c in new_comments[:MAX_NEW_PER_RUN]])

    drafted = 0
    for c in new_comments:
        if drafted >= MAX_NEW_PER_RUN:
            break
        video_title = titles.get(c["video_id"], "")
        draft = _draft_replies(c["text"], video_title)
        if not draft or not draft["replies"]:
            continue
        drafted += 1

        short_id = str(ch_state["next_id"])
        ch_state["next_id"] += 1

        video_url = f"https://youtube.com/watch?v={c['video_id']}"
        lines = [
            f"💬 [{cfg['channel_name']}] Новый комментарий от {c['author']}",
            f"Видео: {video_title or c['video_id']}",
            video_url,
            "",
            f"«{c['text']}»",
            f"Перевод: «{draft['comment_ru']}»",
            "",
            "Варианты ответа:",
        ]
        buttons = []
        for i, r in enumerate(draft["replies"]):
            lines.append(f"{i + 1}) {r['text']}")
            lines.append(f"   RU: {r['ru']}")
            buttons.append({"text": str(i + 1), "callback_data": f"a:{channel}:{short_id}:{i}"})
        buttons.append({"text": "⏭ Skip", "callback_data": f"skip:{channel}:{short_id}"})

        review_text = "\n".join(lines)
        try:
            resp = _tg("sendMessage", chat_id=os.environ["TELEGRAM_CHAT_ID"],
                       text=review_text[:4000], reply_markup={"inline_keyboard": [buttons]})
            message_id = resp["result"]["message_id"]
            chat_id = resp["result"]["chat"]["id"]
        except Exception as e:
            print(f"  [{channel}] отправка в Telegram упала: {e}")
            continue

        ch_state["pending"][short_id] = {
            "comment_id": c["comment_id"], "video_id": c["video_id"],
            "replies": draft["replies"], "created_at": now,
            "review_text": review_text, "chat_id": chat_id, "message_id": message_id,
        }

    ch_state["seen"] = list(seen)[-SEEN_MAX_PER_CHANNEL:]
    print(f"  [{channel}] новых комментариев: {len(new_comments)}, черновиков отправлено: {drafted}.")


def main() -> None:
    state = _load_state()
    print("1/2 Разбор апрувов с прошлого прогона...")
    _process_approvals(state)
    print("2/2 Поиск новых комментариев...")
    for channel in CONFIGS:
        _check_channel(channel, state)
    _save_state(state)


if __name__ == "__main__":
    main()
