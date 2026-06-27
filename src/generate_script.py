"""Генерирует тему и короткий сценарий факта через Claude API."""
import json
import os
import random

from anthropic import Anthropic

from config import CFG
from recent_titles import add_title_to_cache, get_recent_titles
from topic_stats import get_topic_avg_views

# Темы, которые НЕЛЬЗЯ использовать — слишком абстрактны/технически сложны,
# аудитория не понимает сюрпризы без специальных знаний.
BANNED_TOPICS = {"physics", "quantum physics", "quantum mechanics"}

TOPICS_POOL = [
    # History/archaeology — исторически лучшие результаты на канале (avg views 740-1090)
    "ancient history", "archaeological discoveries", "ancient civilizations",
    "shipwrecks and lost treasures", "historical mysteries",
    # Science/nature — стабильно хорошая вовлечённость (avg views 580-1075)
    "the human body", "the animal kingdom", "the ocean", "evolution",
    "volcanoes and earthquakes", "extreme weather", "natural wonders",
    # Space — широкая аудитория
    "space",
    # Удалены 2026-06: psychology (avg 136), future technology (avg 16), bizarre records
    # (непроверенная, размытая) — в 5-8 раз хуже топа, мешали consistency канала.
]

MIN_TOPICS_WITH_DATA = 5  # не взвешивать, пока статистика не накопилась хотя бы по стольким темам


def _pick_topic() -> str:
    try:
        avg_views = get_topic_avg_views()
    except Exception:
        avg_views = {}

    if len(avg_views) < MIN_TOPICS_WITH_DATA:
        return random.choice(TOPICS_POOL)

    overall_avg = sum(avg_views.values()) / len(avg_views)
    # Темы без данных получают средний вес (чтобы не застревать на старых лидерах
    # и продолжать исследовать темы, которые ещё не пробовали).
    weights = [max(avg_views.get(t, overall_avg), 1.0) for t in TOPICS_POOL]

    # Логируем топ-5 тем для отладки в GitHub Actions
    ranked = sorted(zip(TOPICS_POOL, weights), key=lambda x: -x[1])
    top5 = ", ".join(f"{t}({w:.0f})" for t, w in ranked[:5])
    print(f"  Topic weights top-5: {top5}")

    return random.choices(TOPICS_POOL, weights=weights, k=1)[0]

BASE_SYSTEM_PROMPT = """You are a scriptwriter for short fact videos on YouTube Shorts (channel: {channel}).
Write the TITLE, SCRIPT and HASHTAGS in {language}, conversational, punchy, no filler. (Keep the
stock-footage search queries in English regardless — they are only used to search a stock video site.)

The fact MUST overturn a common intuitive assumption — something most people would confidently
believe is true (or would never think to question) until this fact breaks it. Not just "an
interesting detail about X," but "X is the opposite of what you'd assume." Body-related, historical,
or sensory facts with a clear before/after contrast in understanding work best. Avoid abstract or
purely technical facts that require specialist background to feel surprising (e.g. quantum
mechanics, relativity, advanced math) — the shock has to land for a general audience in one watch.
Physics and quantum physics are strictly off-limits as topics.

Structure, in order:
1. Hook (first 1-2 sentences): create intrigue WITHOUT naming the subject. The viewer must think
   "wait, what is this about?" for the first 2-3 seconds. Use mystery framing — describe the
   surprising property without revealing what thing has it. Proven templates:
   - "This [vague noun] can [shocking ability]." → reveal the subject next sentence
   - "Nobody knows why [mysterious phenomenon] happens."
   - "This sounds fake, but [claim without naming subject]."
   - "One [vague category] can [shocking thing] overnight."
   - "Scientists still can't explain why [phenomenon]."
   Never open with "Did you know" / "¿sabías que?" / "Today we'll talk about" — open
   mid-thought like cutting into the most interesting part of a conversation.
2. Reveal + fact: name the subject and deliver the core fact fast, no filler. The fact MUST
   contain at least one concrete anchor — a number, a date, a named place, or a named person
   (e.g. "100,000 years", "the 1888 Ritter Island eruption", "a goldsmith named Amenhotep").
   Vague facts feel like trivia; a specific anchor makes it feel true and memorable. Also make
   the stakes personal where you honestly can: tie it to the viewer's own body, safety, daily
   life, or something they've experienced — not just abstract "this is interesting."
3. One unexpected twist or payoff line that makes the misconception's collapse explicit.
4. Comment bait (one sentence, standalone): the viewer must feel an itch to reply. Pick ONE
   of these four mechanisms — whichever fits the fact best — never a generic "what do you think?":
   a) Correction trap: state something a chunk of viewers will believe is wrong, so they rush
      to correct you. ("Technically this means [common belief] was never true.")
   b) Personal-experience call: invite people who've felt/seen it to confirm. ("If you've ever
      [common experience tied to the fact], you already knew this on some level.")
   c) Camps: split the audience into two groups who'll argue. ("Half of you will refuse to
      believe this even now.")
   d) Unfinished "actually": an almost-complete claim that begs an "actually..." reply.

No "today I'll tell you about" style intros.""".format(
    channel=CFG["channel_name"],
    language=CFG["script_language"],
)

# Loop-специфичная концовка — добавляется ТОЛЬКО к ежедневным Shorts (generate_script).
# Series и longform используют BASE_SYSTEM_PROMPT без неё: у них своя концовка/CTA и нет петли.
LOOP_INSTRUCTION = """ENDING & LOOP (daily Shorts only):
The comment-bait IS the LAST spoken sentence of your script.
Do NOT add any spoken call-to-action ("follow", "comment", "like") — the follow prompt is shown
on-screen as a badge, not spoken. A voiced CTA here breaks the flow into the loop. Do NOT write
any loop line yourself either — a loop connector is appended automatically.

LOOP CONNECTORS (field "loop_connectors"): a short loop phrase is appended right after your last
sentence and the video loops back to sentence 1. The appended phrase ends in one of:
why / how / when / where / because — so on the loop it reads "<that word> <sentence 1>". Your job:
list ONLY the connector words for which "<word> <sentence 1>" is a COHERENT, grammatical sentence.
  Test each: read "why <sentence 1>", "how <sentence 1>", "when <sentence 1>", "where <sentence 1>",
  "because <sentence 1>" aloud — include a word ONLY if it forms a real sentence.
  Example: sentence 1 = "This creature ages backwards." → "why this creature ages backwards" ✓,
    "how this creature ages backwards" ✓, "when this creature ages backwards" ✓(weaker),
    "where..." ✗, "because..." ✗  → loop_connectors: ["why","how"].
  Always include at least one (usually "why" and/or "how" fit a fact-statement hook)."""

# 30-38s is the sweet spot for YouTube's 2026 Shorts algorithm (absolute watch time, not
# just retention %). edge-tts at +5% ≈ 2.6 words/sec, so 75-95 words ≈ 30-37s.
# 85-110 words drifted to 44-47s in practice — ceiling lowered to hit the target reliably.
LENGTH_INSTRUCTION = (
    "HARD LENGTH LIMIT: the script (hook through CTA, the loop line is added later) MUST be "
    "75-90 words. This is the single most important constraint — count the words before you "
    "answer and DO NOT exceed 90. A script over 90 words is a failure even if great. "
    "Be ruthless: one tight sentence per beat, no throat-clearing, no second comment-bait, "
    "no padding adjectives. Build a full arc (setup, twist, payoff) inside the budget."
)

SCRIPT_MIN_WORDS = 70
SCRIPT_MAX_WORDS = 92  # gate: above this we retry; loop line (~3 words) appended after
TITLE_INSTRUCTION = (
    "title: a punchy narrative hook, under 60 characters. Do NOT append a '| topic facts' "
    "style keyword suffix — it should read like a real headline, not a listicle."
)


def _build_user_content(topic: str, avoid_block: str) -> str:
    return (
        avoid_block +
        f"Topic: {topic}. Come up with one specific, lesser-known fact on this topic "
        "and write a script for it. Also break the script into visual beats (roughly one "
        "every 4-5 seconds of the script) and for each one write a short stock-footage "
        "search query (2-4 words, concrete, visual, in English, the kind you'd type into "
        "a stock video site search box, matching what's being said at that point). "
        "IMPORTANT for video queries: stock sites have generic footage, not specific "
        "artifacts or rare objects. Write queries for the MOOD and SETTING, not the "
        "exact object named in the script. Bad: 'sealed canopic jars egypt' (too specific). "
        "Good: 'ancient egypt excavation', 'archaeologist digging ruins', 'dark underground "
        "tunnel'. Always prefer wide scenes, landscapes, and human action over close-ups "
        "of specific objects.\n\n"
        "Requirements:\n"
        f"- {TITLE_INSTRUCTION}\n"
        f"- tags: 6-9 specific YouTube search tags in {CFG['script_language']}, mixing "
        "broad ones (e.g. the channel's equivalent of 'facts'/'did you know') with specific "
        "long-tail ones tied to the exact fact (the specific phenomenon, place, or thing "
        "named in the script).\n"
        f"- hashtags: 3-5 hashtags in {CFG['script_language']} (lowercase, no spaces, with "
        "# prefix), mixing one broad discovery hashtag (#shorts and the language's "
        "equivalent of #facts) with 2-4 specific ones tied to the topic and fact.\n\n"
        "Respond strictly in JSON, no markdown wrapper: "
        '{"title": "title text", '
        '"script": "voiceover script ending with the comment-bait line (NO spoken CTA, NO loop line)", '
        '"loop_connectors": ["why", "how"], '
        '"tags": ["tag1", "tag2", ...], '
        '"hashtags": ["#tag1", "#tag2", ...], '
        '"video_queries": ["query1", "query2", ...]}'
    )


def _parse_response(message) -> dict:
    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
    start, end = raw.find("{"), raw.rfind("}")
    return json.loads(raw[start:end + 1])


def _split_sentences(script: str) -> list[str]:
    import re
    parts = re.split(r"(?<=[.!?])\s+", script.strip())
    return [p.strip() for p in parts if p.strip()]


_LOOP_END_WORDS = {"why", "how", "when", "where", "because"}


def _validate(data: dict) -> list[str]:
    """Returns a list of human-readable problems; empty list means the script passed."""
    problems = []
    script = data.get("script", "")
    word_count = len(script.split())
    if word_count > SCRIPT_MAX_WORDS:
        problems.append(
            f"The script is {word_count} words — too long (runs over 37s). "
            f"Cut it to 75-95 words while keeping the hook, the core fact, the comment bait "
            f"and the CTA as the last sentence. Tighten the middle."
        )

    connectors = [c.lower() for c in data.get("loop_connectors", []) if isinstance(c, str)]
    if not any(c in _LOOP_END_WORDS for c in connectors):
        problems.append(
            "loop_connectors is missing or invalid. Provide a non-empty list of connector words "
            "from [why, how, when, where, because] — ONLY those for which '<word> <sentence 1>' is "
            "a coherent sentence. A fact-statement hook almost always supports 'why' and/or 'how'."
        )
    return problems


def _better(a: dict, b: dict) -> dict:
    """Лучший из двух кандидатов: меньше проблем валидации; при равенстве — короче скрипт."""
    pa, pb = len(_validate(a)), len(_validate(b))
    if pa != pb:
        return a if pa < pb else b
    wa = len(a.get("script", "").split())
    wb = len(b.get("script", "").split())
    return a if wa <= wb else b


def _append_loop(data: dict) -> None:
    """С вероятностью loop_probability дописывает loop-фразу в конец скрипта на языке канала
    (коннектор — из помеченных Claude). Иначе оставляет обычную концовку.
    Проставляет data["has_loop"] для пометки тегом и сравнения в аналитике."""
    if random.random() >= CFG.get("loop_probability", 0.5):
        data["has_loop"] = False
        return

    phrases = CFG.get("loop_phrases", {})
    valid = [c.lower() for c in data.get("loop_connectors", [])
             if isinstance(c, str) and c.lower() in phrases]
    connector = random.choice(valid) if valid else "why"
    pool = phrases.get(connector) or phrases.get("why") or ["This is why."]
    loop_line = random.choice(pool)
    data["script"] = f"{data['script'].rstrip()} {loop_line}"
    data["has_loop"] = True


def generate_script() -> dict:
    topic = _pick_topic()
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=5)

    try:
        past_titles = get_recent_titles()
    except Exception:
        past_titles = []

    avoid_block = ""
    if past_titles:
        avoid_block = (
            "Already-published video titles on this channel — pick a DIFFERENT specific fact, "
            "not a variation of any of these:\n" + "\n".join(f"- {t}" for t in past_titles) + "\n\n"
        )

    system_prompt = BASE_SYSTEM_PROMPT + "\n\n" + LOOP_INSTRUCTION + "\n\n" + LENGTH_INSTRUCTION
    user_content = _build_user_content(topic, avoid_block)

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1200,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    data = _parse_response(message)

    # Validation gate — only pay for a second call if the output is actually bad.
    problems = _validate(data)
    if problems:
        print("  Script failed validation, doing one targeted retry:")
        for p in problems:
            print(f"    - {p.split('.')[0]}.")
        feedback = (
            "Your previous script had these problems — fix ALL of them and return the FULL JSON "
            "again (title, script, tags, hashtags, video_queries), regenerating video_queries to "
            "match the revised script so the beats stay in sync:\n\n"
            + "\n".join(f"- {p}" for p in problems)
            + "\n\nPrevious script was:\n" + data.get("script", "")
        )
        retry = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1200,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": json.dumps(data, ensure_ascii=False)},
                {"role": "user", "content": feedback},
            ],
        )
        try:
            fixed = _parse_response(retry)
            # Выбираем лучший: меньше проблем, при равенстве — короче скрипт
            # (иначе при «обе длинные» оставался бы оригинал, который длиннее).
            data = _better(data, fixed)
        except Exception as e:
            print(f"  Retry parse failed ({e}), keeping original.")

    _append_loop(data)  # детерминированно дописываем loop-фразу под помеченный коннектор
    data["topic"] = topic
    data["hashtag_position"] = "end"
    add_title_to_cache(data["title"])
    return data


if __name__ == "__main__":
    print(json.dumps(generate_script(), ensure_ascii=False, indent=2))
