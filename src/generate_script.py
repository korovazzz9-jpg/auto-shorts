"""Генерирует тему и короткий сценарий факта через Claude API."""
import json
import os
import random

from anthropic import Anthropic

from config import CFG, CHANNEL
from recent_titles import add_title_to_cache, add_topic_to_cache, get_recent_titles, get_recent_topics
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
    # Re-test 2026-06-29: future technology возвращена. Старые EN-видео по ней удалены
    # (тег пропал из topic_stats) → тема получает НЕЙТРАЛЬНЫЙ вес и честно тестируется
    # под текущим сильным промптом. Прежний провал (avg 16) был под старым слабым промптом;
    # в ES та же тема сейчас 64% досмотра / 850-1380 просмотров. Если снова <300 — убрать.
    "future technology",
    # Удалены 2026-06: psychology (avg 136), bizarre records (непроверенная, размытая) —
    # в 5-8 раз хуже топа, мешали consistency канала.
]

MIN_TOPICS_WITH_DATA = 5  # не взвешивать, пока статистика не накопилась хотя бы по стольким темам


def _load_niche_signal() -> dict[str, int]:
    """Outlier-сигнал по нише (discover_niche_topics.py, раз в неделю, коммитится
    воркфлоу) — {topic: outlier_count}, сколько видео-выбросов у ЧУЖИХ каналов нашлось
    по этой теме. Нет файла/данных — пустой словарь, вес не меняется."""
    path = os.path.join(os.path.dirname(__file__), "..", f"niche_signal_{CHANNEL}.json")
    try:
        with open(path, encoding="utf-8") as f:
            stats = json.load(f)
        return stats.get("outlier_counts", {}) if isinstance(stats, dict) else {}
    except Exception:
        return {}


def _pick_topic() -> str:
    # Исключаем темы последних видео, чтобы не выходило два похожих ролика подряд.
    exclude = set(get_recent_topics(2))
    pool = [t for t in TOPICS_POOL if t not in exclude] or TOPICS_POOL

    try:
        avg_views = get_topic_avg_views()
    except Exception:
        avg_views = {}

    if len(avg_views) < MIN_TOPICS_WITH_DATA or len(pool) < 3:
        return random.choice(pool)

    overall_avg = sum(avg_views.values()) / len(avg_views)
    niche_counts = _load_niche_signal()
    # Темы без данных получают средний вес — попадают в середину рейтинга и продолжают
    # исследоваться, не застревая ни в топе, ни в хвосте. Мягкий бонус от outlier-анализа по
    # нише (2026-07-03): +15% веса за каждый найденный выброс, максимум ×1.45 (3+ выброса) —
    # чтобы один аномальный чужой ролик не рвал всю квоту 70/20/10, только подталкивал.
    weight = lambda t: max(avg_views.get(t, overall_avg), 1.0) * (1.0 + 0.15 * min(niche_counts.get(t, 0), 3))
    ranked = sorted(pool, key=lambda t: -weight(t))

    # Квоты 70/20/10 вместо чистого взвешивания по avg_views: взвешивание самоусиливает
    # победителей до усталости темы (локальный максимум — напр. серия почти одинаковых
    # shipwreck-роликов). Явные квоты гарантируют исследование: 70% — верхняя треть тем,
    # 20% — средняя, 10% — нижняя (wildcard). Внутри яруса — равномерно.
    third = max(1, len(ranked) // 3)
    roll = random.random()
    if roll < 0.7:
        tier, label = ranked[:third], "top"
    elif roll < 0.9:
        tier, label = ranked[third:2 * third] or ranked[:third], "mid"
    else:
        tier, label = ranked[2 * third:] or ranked[-third:], "wild"

    top5 = ", ".join(f"{t}({weight(t):.0f})" for t in ranked[:5])
    print(f"  Topic weights top-5: {top5} | tier={label}")
    return random.choice(tier)

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
1. Hook (the FIRST sentence, max ~12 words): the swipe-away decision is instant, so the single
   most shocking, hard-to-believe claim must come FIRST — no warm-up clause before it. Open an
   information gap the viewer is COMPELLED to close, WITHOUT naming the subject. The first 3-4
   words alone must stop the scroll. Break a belief or raise real stakes — don't merely tease.
   Proven templates:
   - "This [vague noun] can [shocking ability] — and [surprising consequence]."
   - "You've [common experience], and you never knew [hidden reason]."
   - "One [vague category] can [shocking thing] in [short timeframe]."
   - "[Authority] still can't explain why [phenomenon]."
   - "This sounds fake, but [claim without naming subject]."
   Never open with "Did you know" / "¿sabías que?" / "Today we'll talk about" / any warm-up —
   the shocking words come FIRST, framing second. Cut into the most interesting part mid-thought.
   Throughout the whole script (not just the hook): prefer strong, vivid verbs over "is"/"there
   is" constructions (e.g. "This cave BREATHES" not "There is a cave that breathes"). Keep
   sentences short and punchy — cut connector words and generic hedging phrases like
   "fascinating", "scientists discovered", "this phenomenon".
2. Reveal + fact: name the subject and deliver the core fact fast, no filler. The fact MUST
   contain at least one concrete anchor — a number, a date, a named place, or a named person
   (e.g. "100,000 years", "the 1888 Ritter Island eruption", "a goldsmith named Amenhotep").
   Vague facts feel like trivia; a specific anchor makes it feel true and memorable. Also make
   the stakes personal where you honestly can: tie it to the viewer's own body, safety, daily
   life, or something they've experienced — not just abstract "this is interesting."
3. Re-hook + twist: right before the payoff, re-open curiosity with a SHORT re-hook (3-5 words,
   e.g. "But here's the strange part" / "And it gets weirder") so viewers don't drop in the
   middle — then deliver one unexpected twist that makes the misconception's collapse explicit.
4. Comment bait (one sentence, standalone, MUST provoke a strong reaction): comments and shares
   are a top ranking signal, so the viewer should feel they CAN'T scroll without replying. Land
   on the single most debatable or personal point of the fact — never a generic recap or a soft
   "what do you think?". Pick the mechanism that creates the most disagreement or self-recognition:
   a) Correction trap: state it so confidently that people who "know better" rush to correct you.
      ("So technically, [common belief] was never actually true.")
   b) Personal-experience call: make a specific bet about the viewer's own body/life they'll want
      to confirm or deny. ("If your [body part] ever [sensation], you've felt this and didn't know it.")
   c) Camps: explicitly split the audience and predict one side won't accept it. ("Half of you will
      refuse to believe this even after watching twice.")
   d) Unfinished "actually": leave a deliberate, baitable gap that begs an "actually..." reply.
   e) Share trigger: phrase it so the viewer wants to SEND it to a specific person — name the
      type of person who needs to see it ("Send this to someone who still thinks [belief]").
      Shares and share-to-DM are a top distribution signal on both YouTube and TikTok.

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

# Top-performing fact/educational Shorts cluster at 25-35s (viral range 20-40s; retention/AVD is
# the whole game, >45s drops off hard). Facts aren't tutorials, but need room for anchor+twist+bait,
# so we target ~28-35s — the upper sweet spot. edge-tts at +5% ≈ 2.6 words/sec, so 70-88 words.
LENGTH_INSTRUCTION = (
    "HARD LENGTH LIMIT: the script (hook through CTA, the loop line is added later) MUST be "
    "70-88 words — top fact Shorts land at ~28-35s; longer than that and retention drops off. "
    "Silently count the words of your script before responding (do NOT show any draft, count, or "
    "reasoning in your reply — go straight to the JSON object, nothing before it). If your silent "
    "count is over 88, trim it before outputting. A script over 88 words is a failure even if "
    "great. Be ruthless: one tight sentence per beat, no throat-clearing, no second comment-bait, "
    "no padding adjectives. Build a full arc (setup, twist, payoff) tightly. Report your word "
    "count in the \"word_count\" field — it must match the actual word count of \"script\"."
)

SCRIPT_MIN_WORDS = 65
SCRIPT_MAX_WORDS = 93  # gate: above this we retry; loop line (~3 words) appended after

# A/B заголовков (2026-07-02): чисто нарративные заголовки (текущая практика) против
# keyword-насыщенных. Причина теста: индустриальные данные за 2026 говорят, что поисковая
# карусель для Shorts вернулась и заголовок-ключевые-слова снова участвуют в ранжировании —
# но наш промпт СОЗНАТЕЛЬНО их избегал ("read like a real headline, not a listicle"). Не
# меняем стратегию вслепую — тегируем title-seo/title-narrative (как hook_template) и
# сравниваем в weekly_report.py, прежде чем менять соотношение или отказываться от теста.
TITLE_INSTRUCTION_NARRATIVE = (
    "title: a punchy narrative hook, under 60 characters. Do NOT append a '| topic facts' "
    "style keyword suffix — it should read like a real headline, not a listicle."
)
TITLE_INSTRUCTION_SEO = (
    "title: under 60 characters. Name the specific subject plainly (the animal/place/era/"
    "phenomenon) and include the one concrete keyword a viewer would actually type into "
    "YouTube search for this fact — but it must still read like a real headline, not a "
    "listicle or a '| topic facts' keyword-stuffed suffix."
)
TITLE_INSTRUCTION = TITLE_INSTRUCTION_NARRATIVE  # обратная совместимость (generate_series.py)
TITLE_SEO_PROBABILITY = 0.3  # доля видео с keyword-насыщенным заголовком


def pick_title_variant() -> tuple[str, str]:
    """Возвращает (текст инструкции, тег 'seo'|'narrative') — вызывающий код передаёт текст в
    _build_user_content и должен сохранить тег в data["title_variant"] после парсинга."""
    if random.random() < TITLE_SEO_PROBABILITY:
        return TITLE_INSTRUCTION_SEO, "seo"
    return TITLE_INSTRUCTION_NARRATIVE, "narrative"

# Хук-шаблоны: модель сообщает, какой использовала; пайплайн тегирует видео hook-<id>,
# а analytics_retention меряет % досмотра по типу хука — чтобы взвешивать сильнейшие.
HOOK_TEMPLATES = [
    "vague-ability",           # "This [vague noun] can [shocking ability]..."
    "you-experience",          # "You've [common experience], you never knew [hidden reason]"
    "one-category",            # "One [vague category] can [shocking thing] in [timeframe]"
    "authority-cant-explain",  # "[Authority] still can't explain why..."
    "sounds-fake",             # "This sounds fake, but [claim]"
    "other",
]


def _hook_preference() -> str:
    """Замыкает петлю хук-аналитики: weekly_report.py раз в неделю пишет лучший по retention
    хук-шаблон в hook_stats_<channel>.json (коммитится воркфлоу), а мы мягко подсказываем его
    модели. Подсказка, не приказ — иначе шаблон станет формулой и данные для сравнения иссякнут.
    Нет файла/данных — пустая строка, промпт как раньше."""
    path = os.path.join(os.path.dirname(__file__), "..", f"hook_stats_{CHANNEL}.json")
    try:
        with open(path, encoding="utf-8") as f:
            stats = json.load(f)
        best = stats.get("best_template", "") if isinstance(stats, dict) else ""
    except Exception:  # подсказка опциональна — ЛЮБАЯ проблема с файлом не должна ломать генерацию
        return ""
    if best not in HOOK_TEMPLATES or best == "other":
        return ""
    return (f" Data note: on this channel the '{best}' opening currently retains viewers "
            "best — prefer it when it fits the fact naturally, but never force it.")


# Ротация заголовков (2026-07-03): проверено эмпирически — 84% заголовков EN-канала начинались
# с "The"/"Your"/"This" (64 заголовка: 61% + 22% + 2%). Заголовок генерится в том же вызове,
# что hook_template ("This X can...", "You've...") — модель эхует структуру спич-хука в title.
# Явный список открывашек + отчёт о выбранной (title_opener) — тот же паттерн, что HOOK_TEMPLATES.
TITLE_OPENERS = [
    "the-x",                   # "The [subject/mystery/creature] that..."
    "your-x",                  # "Your [body part/bones/skin] does/is..."
    "scientists-discovered",   # "Scientists just found/discovered..."
    "shouldnt-exist",          # "This shouldn't exist/be possible..."
    "nobody-expected",         # "Nobody expected/saw this coming..."
    "only-place",              # "The only place on Earth where..."
    "question",                # "Why does/do..."
    "other",
]

TITLE_OPENER_INSTRUCTION = (
    f"title_opener: which opening style the title uses — exactly one of "
    f"[{', '.join(TITLE_OPENERS)}]. VARY this across videos — don't default to 'the-x'/"
    "'your-x' every time; 'scientists-discovered', 'shouldnt-exist', 'nobody-expected', "
    "'only-place', and 'question' are equally valid and often punchier. Report the closest "
    "match (use 'other' if none fits)."
)


def _title_variety_note(past_titles: list[str]) -> str:
    """Считает, сколько из последних заголовков начинаются с The/Your/This (без доступа к
    тегам — эвристика по первому слову самого заголовка, работает даже для старых видео,
    опубликованных до введения title_opener). Если ≥60% — явно просим другой опенер, а не
    просто "варьируй" — иначе модель по инерции продолжает тот же паттерн."""
    if not past_titles:
        return ""
    sample = past_titles[:10]
    common_openers = {"the", "your", "this"}
    hits = sum(1 for t in sample if t.split()[:1] and t.split()[0].lower() in common_openers)
    if hits / len(sample) < 0.6:
        return ""
    return (" Data note: recent titles on this channel are heavily skewed toward 'The'/'Your'/"
            "'This' openings — for THIS title, deliberately use a different opener style "
            "('scientists-discovered', 'shouldnt-exist', 'nobody-expected', 'only-place', or "
            "'question') unless the fact genuinely reads better the old way.")


# Эмоциональный тон (2026-07-03): тема (space/ocean/history...) и эмоциональный регистр факта —
# разные оси. "Fear" и "Impossible" могут оба быть про космос, но восприниматься совершенно
# по-разному в ленте. Добавляем КАК ДОПОЛНИТЕЛЬНОЕ измерение поверх темы (не взамен) — тот же
# tag+track паттерн, что hook_template, БЕЗ переделки topic-системы (playlist/topic_stats/квоты
# 70/20/10 остаются как есть, они работают и завязаны на тему, не на эмоцию).
EMOTIONAL_TONES = [
    "fear",        # unsettling, threatening
    "awe",         # vast, mind-bending scale
    "creepy",      # unsettling, body-horror, parasitic
    "beautiful",   # aesthetic, rare, mesmerizing
    "huge",        # scale-shock (biggest/smallest/fastest)
    "impossible",  # defies intuition/physics as commonly understood
    "disgust",     # visceral, gross-out
    "humor",       # absurd, funny
    "other",
]

EMOTIONAL_TONE_INSTRUCTION = (
    f"emotional_tone: the emotional register the fact lands on for the viewer — exactly one "
    f"of [{', '.join(EMOTIONAL_TONES)}]. This is independent of the topic — e.g. a space fact "
    "can be 'fear', 'awe', or 'beautiful' depending on the angle. Report the closest match "
    "(use 'other' if none fits)."
)


def _build_user_content(topic: str, avoid_block: str, title_instruction: str = TITLE_INSTRUCTION_NARRATIVE) -> str:
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
        f"- {title_instruction}\n"
        f"- {TITLE_OPENER_INSTRUCTION}\n"
        f"- hook_text: a 3-6 word ON-SCREEN hook shown over the first seconds. It must be a "
        "DIFFERENT angle from the spoken first sentence (the eye and the ear deliver two "
        "separate hooks in the first 2 seconds) and NOT a copy of the title. Punchy, in "
        f"{CFG['script_language']}, no ending period.\n"
        f"- hook_template: which opening template the spoken hook uses — exactly one of "
        f"[{', '.join(HOOK_TEMPLATES)}]. Report the closest match (use 'other' if none fits)."
        f"{_hook_preference()}\n"
        f"- {EMOTIONAL_TONE_INSTRUCTION}\n"
        f"- tags: 6-9 specific YouTube search tags in {CFG['script_language']}, mixing "
        "broad ones (e.g. the channel's equivalent of 'facts'/'did you know') with specific "
        "long-tail ones tied to the exact fact (the specific phenomenon, place, or thing "
        "named in the script).\n"
        f"- hashtags: 3-5 hashtags in {CFG['script_language']} (lowercase, no spaces, with "
        "# prefix), mixing one broad discovery hashtag (#shorts and the language's "
        "equivalent of #facts) with 2-4 specific ones tied to the topic and fact.\n"
        "- search_summary: ONE plain, keyword-dense sentence (max 20 words) that states the "
        "fact directly for YouTube SEARCH — the OPPOSITE style from the spoken hook: no info "
        "gap, no vague noun, name the subject and the claim plainly (e.g. 'Turritopsis "
        "jellyfish can reverse their aging process and effectively avoid death'). This is NOT "
        f"spoken and NOT shown on screen — only used as the first line of the description, in "
        f"{CFG['script_language']}.\n\n"
        "Respond strictly in JSON, no markdown wrapper: "
        '{"title": "title text", '
        '"title_opener": "the-x", '
        '"hook_text": "short on-screen hook", '
        '"hook_template": "vague-ability", '
        '"emotional_tone": "awe", '
        '"script": "voiceover script ending with the comment-bait line (NO spoken CTA, NO loop line)", '
        '"word_count": 85, '
        '"search_summary": "plain keyword-dense sentence", '
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
    reported = data.get("word_count")
    if isinstance(reported, int) and abs(reported - word_count) > 5:
        print(f"    (self-reported word_count {reported} vs actual {word_count} — model miscounted)")
    if word_count > SCRIPT_MAX_WORDS:
        problems.append(
            f"The script is {word_count} words — too long (top fact Shorts land at ~28-35s). "
            f"Cut it to 70-88 words while keeping the hook, the core fact, the comment bait "
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
    title_instruction, title_variant = pick_title_variant()
    title_instruction += _title_variety_note(past_titles)
    user_content = _build_user_content(topic, avoid_block, title_instruction)

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1600,
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
            max_tokens=1600,
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
    data["title_variant"] = title_variant  # A/B заголовков: тег title-seo/title-narrative
    data["hashtag_position"] = "end"
    # #2 хук-шаблон: нормализуем к известному id (для тега hook-<id> и аналитики).
    ht = str(data.get("hook_template", "")).strip().lower()
    data["hook_template"] = ht if ht in HOOK_TEMPLATES else "other"
    # Ротация заголовков + эмоциональный тон (2026-07-03): нормализуем к известным id,
    # та же логика, что hook_template — неизвестное/пустое значение падает на "other".
    to = str(data.get("title_opener", "")).strip().lower()
    data["title_opener"] = to if to in TITLE_OPENERS else "other"
    et = str(data.get("emotional_tone", "")).strip().lower()
    data["emotional_tone"] = et if et in EMOTIONAL_TONES else "other"
    # #4 двойной хук: если on-screen hook пуст — падаем на заголовок (хук-плашка не исчезнет).
    if not str(data.get("hook_text", "")).strip():
        data["hook_text"] = data["title"]
    add_title_to_cache(data["title"])
    add_topic_to_cache(topic)
    return data


if __name__ == "__main__":
    print(json.dumps(generate_script(), ensure_ascii=False, indent=2))
