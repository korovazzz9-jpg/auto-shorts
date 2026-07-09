"""Генерирует тему и короткий сценарий факта через Claude API."""
import json
import os
import random

import requests
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


def _load_niche_stats() -> dict:
    """Весь niche_signal_<channel>.json (discover_niche_topics.py, раз в неделю, коммитится
    воркфлоу): outlier_counts {topic: count} для весов + outlier_titles {topic: [titles]}
    для стилевой калибровки промпта. Нет файла/данных — пустой словарь."""
    path = os.path.join(os.path.dirname(__file__), "..", f"niche_signal_{CHANNEL}.json")
    try:
        with open(path, encoding="utf-8") as f:
            stats = json.load(f)
        return stats if isinstance(stats, dict) else {}
    except Exception:
        return {}


def _load_niche_signal() -> dict[str, int]:
    """{topic: outlier_count} — сколько видео-выбросов у ЧУЖИХ каналов нашлось по теме."""
    return _load_niche_stats().get("outlier_counts", {})


def _load_saturation() -> dict[str, int]:
    """{topic: total_results} — насыщенность темы (2026-07-08): сколько всего видео вообще
    конкурирует за тему на YouTube (сигнал ПРЕДЛОЖЕНИЯ, из pageInfo.totalResults в
    discover_niche_topics.py — тот же вызов, что уже ищет выбросы, доп. квота не нужна)."""
    sat = _load_niche_stats().get("saturation", {})
    return sat if isinstance(sat, dict) else {}


def _saturation_multiplier(topic: str, saturation: dict[str, int]) -> float:
    """Мягкий противовес чистому спросу: тема с тем же avg_views/outlier-сигналом, но МЕНЬШЕЙ
    конкуренцией (меньше totalResults) — более «свободная» ниша, получает небольшой бонус;
    сильно перенасыщенная — небольшой штраф. Специально мягче outlier-бонуса (макс ×1.45) —
    сигнал шумнее (один снэпшот поиска, произвольный порог), не должен доминировать над
    реальной статистикой просмотров. Нет данных по теме/вообще — множитель 1.0."""
    if not saturation or topic not in saturation:
        return 1.0
    values = [v for v in saturation.values() if v > 0]
    if not values:
        return 1.0
    median = sorted(values)[len(values) // 2]
    s = max(saturation.get(topic, median), 1)
    ratio = median / s  # >1 — тема менее насыщена медианы (бонус), <1 — более (штраф)
    return min(max(ratio ** 0.3, 0.85), 1.15)


def _niche_titles_for(topic: str) -> list[str]:
    """Заголовки чужих видео-выбросов по теме (2026-07-05) — стилевые примеры для промпта
    («какие углы сейчас кликаются в нише»). НЕ для копирования фактов — только angle/energy.
    Добавляются органично: лишь когда _pick_topic() выбрал тему с выбросами (weight-бонус
    уже подталкивает такие темы, отдельная квота не нужна). Пусто — промпт как раньше."""
    titles = _load_niche_stats().get("outlier_titles", {})
    if not isinstance(titles, dict):
        return []
    return [t for t in titles.get(topic, []) if isinstance(t, str) and t.strip()][:3]


def _dropoff_note() -> str:
    """Замыкает петлю drop-off-аналитики (2026-07-05): weekly_report.py пишет медианную зону
    обрыва зрителя по худшим видео недели в dropoff_stats_<channel>.json — здесь она
    превращается в зонную подсказку модели. Обрывы в концовке (ending) — норма (CTA),
    подсказка не нужна. Нет файла/мало данных — пустая строка, промпт как раньше."""
    path = os.path.join(os.path.dirname(__file__), "..", f"dropoff_stats_{CHANNEL}.json")
    try:
        with open(path, encoding="utf-8") as f:
            stats = json.load(f)
        zone = str(stats.get("zone", ""))
        n = int(stats.get("videos", 0))
    except Exception:
        return ""
    if n < 3:
        return ""
    notes = {
        "hook": (" Analytics note: on this channel viewers currently drop within the FIRST "
                 "seconds — the hook is not landing. Make the opening claim even more shocking "
                 "and concrete; cut anything that delays it."),
        "reveal": (" Analytics note: on this channel viewers currently drop between the hook "
                   "and the reveal — name the subject and deliver the core fact FASTER (by the "
                   "second sentence), no scenic buildup."),
        "middle": (" Analytics note: on this channel viewers currently drop mid-video — tighten "
                   "the middle: shorter sentences, place the re-hook earlier, cut one detail "
                   "instead of trailing."),
    }
    return notes.get(zone, "")


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
    saturation = _load_saturation()
    # Темы без данных получают средний вес — попадают в середину рейтинга и продолжают
    # исследоваться, не застревая ни в топе, ни в хвосте. Мягкий бонус от outlier-анализа по
    # нише (2026-07-03): +15% веса за каждый найденный выброс, максимум ×1.45 (3+ выброса) —
    # чтобы один аномальный чужой ролик не рвал всю квоту 70/20/10, только подталкивал.
    # Насыщенность темы (2026-07-08, см. _saturation_multiplier) — противовес спросу: та же
    # тема с меньшей конкуренцией ценнее, множитель мягче (0.85-1.15).
    weight = lambda t: (max(avg_views.get(t, overall_avg), 1.0)
                         * (1.0 + 0.15 * min(niche_counts.get(t, 0), 3))
                         * _saturation_multiplier(t, saturation))
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
   CRITICAL — do NOT resolve the fact inside the hook: if the first sentence already delivers the
   COMPLETE payoff (e.g. "Your liver grows back like a lizard's tail"), viewers who feel they
   "got it" drop right before the reveal — measured as our single biggest drop-off point
   (hook->reveal). The hook states the impossible-sounding SETUP and withholds the specific
   resolution (the number, the mechanism, the twist) for point 2. Open the gap; never close it.
   Throughout the whole script (not just the hook): prefer strong, vivid verbs over "is"/"there
   is" constructions (e.g. "This cave BREATHES" not "There is a cave that breathes"). Keep
   sentences short and punchy — cut connector words and generic hedging phrases like
   "fascinating", "scientists discovered", "this phenomenon".
2. Reveal + fact: name the subject and deliver the core fact fast, no filler — and it MUST
   ADD the specific resolution the hook deliberately withheld (the number, the mechanism, the
   twist), never just restate the hook in more words. If the reveal only repeats what the hook
   already said, there is no reason to watch past the hook. The fact MUST
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


# Video pairs (2026-07-08, см. paired_facts.py): видео A формулирует опровержимый/дополняемый
# claim, видео B (через 1-10 дней) находит РЕАЛЬНОЕ противоречие/дополнение к нему. Некликбейт:
# явный запрет выдумывать натяжку, честный отказ (пустая строка / False) лучше подделки —
# тот же принцип, что source_note.
PAIR_START_INSTRUCTION = (
    "\n- pairable_claim: this fact may have a strong, well-known potential CONTRADICTION or "
    "surprising EXTENSION that could anchor a follow-up video later. If so, report it as a "
    "SHORT (under 12 words), precisely falsifiable/extendable statement drawn from this fact "
    "(e.g. 'Bananas are technically classified as berries'). Only fill this if a genuine "
    "well-known follow-up angle exists — otherwise return \"\"."
)


def _pair_resolve_note(claim: str) -> str:
    return (
        f"\n\nFOLLOW-UP OVERRIDE: A previous video on this channel claimed: \"{claim}\". Try to "
        "find a REAL, verifiable contradiction, exception, or surprising extension to this "
        "SPECIFIC claim as THIS video's fact — not invented, not a stretch, not just rephrasing "
        "it. If you find one, set \"pair_resolved\": true and build the whole script around it "
        "(the fact must still stand on its own for someone who never saw the previous video). "
        "If you can't find a genuine one, set \"pair_resolved\": false and pick a normal fact on "
        "the topic instead — a forced/weak contradiction is worse than skipping the follow-up."
    )


def _build_user_content(topic: str, avoid_block: str, title_instruction: str = TITLE_INSTRUCTION_NARRATIVE,
                         pair_start: bool = False, pair_resolve_claim: str | None = None) -> str:
    # Стилевая калибровка по нише (2026-07-05): заголовки чужих выбросов на ЭТУ тему.
    niche_titles = _niche_titles_for(topic)
    niche_block = ""
    if niche_titles:
        niche_block = (
            "Style calibration — these titles are currently overperforming across the niche on "
            "this topic (other channels' videos; do NOT copy their facts or wording, only note "
            "the angle/energy that makes them click):\n"
            + "\n".join(f"- {t}" for t in niche_titles) + "\n\n"
        )
    return (
        avoid_block + niche_block +
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
        f"{CFG['script_language']}.\n"
        f"- comment_question: ONE provocative question about THIS specific fact, in "
        f"{CFG['script_language']}, for the channel's pinned comment. It must reference the "
        "concrete subject of the fact and make viewers want to argue, correct you, or confess "
        "— NOT a generic 'did you know this?'. Max 15 words, may end with an emoji.\n"
        f"- source_note: where this fact comes from — institution/journal/publication + year "
        f"(e.g. 'University of Washington study, 2008'), max 8 words, in {CFG['script_language']}, "
        "no URL. ONLY name a source you genuinely know; if not 100% sure, return \"\" — an "
        "invented source is worse than none.\n"
        f"{_dropoff_note()}"
        f"{PAIR_START_INSTRUCTION if pair_start else ''}"
        f"{_pair_resolve_note(pair_resolve_claim) if pair_resolve_claim else ''}\n\n"
        "Respond strictly in JSON, no markdown wrapper: "
        '{"title": "title text", '
        '"title_opener": "the-x", '
        '"hook_text": "short on-screen hook", '
        '"hook_template": "vague-ability", '
        '"emotional_tone": "awe", '
        '"script": "voiceover script ending with the comment-bait line (NO spoken CTA, NO loop line)", '
        '"word_count": 85, '
        '"search_summary": "plain keyword-dense sentence", '
        '"comment_question": "provocative question about the fact", '
        '"source_note": "origin of the fact or empty string", '
        + ('"pairable_claim": "short falsifiable/extendable claim or empty string", ' if pair_start else '')
        + ('"pair_resolved": true, ' if pair_resolve_claim else '')
        + '"loop_connectors": ["why", "how"], '
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


def _drop_corrupted(items: list) -> list:
    """Фильтрует строки с U+FFFD (2026-07-09: реальный прод-случай на VN-канале — модель
    отдала битую multi-byte UTF-8 последовательность для вьетнамского слова, "#factbat"
    превратилось в "#factbat<0xEF><0xBF><0xBD>x3" — редкий, но известный артефакт на границе
    токенов для языков со сложной диакритикой (VN, потенциально и ES). Не ошибка парсинга —
    сами байты ответа модели уже битые, json.loads успешно проглатывает как валидный символ.
    Такой тег/хэштег всё равно бесполезен/может быть отклонён платформой — молча
    выбрасываем, не роняем генерацию из-за одного плохого элемента среди нескольких."""
    return [s for s in items if isinstance(s, str) and "�" not in s]


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


def _enrich_tags_with_suggestions(tags: list[str]) -> list[str]:
    """SEO-обогащение тегов (2026-07-09): проверяет первые 3 тега через бесплатный YouTube
    autocomplete-эндпоинт (suggestqueries.google.com — без ключа, без квоты Data API) и
    добавляет РЕАЛЬНЫЕ популярные формулировки, которых ещё нет в списке (максимум +3,
    по одной лучшей на проверяемый тег).

    НЕ трогает хук/заголовок/скрипт — проверено эмпирически: полные заголовки-хуки дают
    0 совпадений в автокомплите, и это ожидаемо (хук намеренно уникален, скрывает субъект
    ради интриги — curiosity gap несовместим с keyword-matching по дизайну). Короткие
    tags-фразы (2-3 слова) — ровно то, для чего этот сигнал полезен.

    Недокументированный эндпоинт Google (не официальный API) — теоретически может
    измениться без предупреждения. Обвязано в try/except на каждый запрос — сбой/пустой
    ответ просто пропускается, никогда не роняет генерацию.

    Фильтр релевантности (2026-07-09, после реального теста): автокомплит договаривает по
    созвучию/популярности, не по смыслу — "octopus dna" дало "octopus oggy" (мультик,
    вообще не по теме). Принимаем формулировку, только если она содержит ВСЕ значимые
    слова исходного запроса (не только первое) — иначе автокомплит просто увёл в сторону."""
    added: list[str] = []
    existing_lower = {t.lower() for t in tags}
    # Однословные теги — это generic-якоря промпта ("facts"/"did you know" и т.п.), не
    # конкретика факта. Проверено эмпирически: автокомплит на них даёт шум ("facts" →
    # "facts up"), а на 2+ словных long-tail — реальные полезные формулировки.
    candidates = [t for t in tags if len(t.lstrip("#").split()) >= 2][:3]
    for tag in candidates:
        query = tag.lstrip("#").strip()
        if not query:
            continue
        query_words = [w for w in query.lower().split() if len(w) > 2]  # без коротких стоп-слов
        try:
            resp = requests.get(
                "http://suggestqueries.google.com/complete/search",
                params={"client": "firefox", "ds": "yt", "q": query},
                timeout=5,
            )
            suggestions = resp.json()[1]
        except Exception:
            continue
        for s in suggestions:
            best = str(s).strip()
            best_lower = best.lower()
            if not best or best_lower in existing_lower:
                continue
            if query_words and not all(w in best_lower for w in query_words):
                continue  # автокомплит увёл в сторону — не все слова запроса сохранились
            added.append(best)
            existing_lower.add(best_lower)
            break  # одна лучшая формулировка на тег, не больше
    return tags + added


def generate_script(on_this_day: bool = False, pair_start: bool = False,
                     pair_resolve_claim: str | None = None) -> dict:
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
    user_content = _build_user_content(topic, avoid_block, title_instruction,
                                        pair_start=pair_start, pair_resolve_claim=pair_resolve_claim)

    # «On this day» (2026-07-05): раз в неделю факт привязывается к сегодняшней дате —
    # timely-контент алгоритм тестирует охотнее, дата в скрипте добавляет конкретики.
    # Только live-генерация (pipeline.py, мимо очереди): batch-заготовки не знают дату выхода.
    #
    # ⚠️ Баг найден 2026-07-09 (реальный прод-инцидент, ES 03:17/03:49): "The date claim must
    # be REAL" невольно приглашала модель ПРОВЕРЯТЬ СЕБЯ ВСЛУХ — response.stop_reason был
    # "max_tokens", а content[0].text был заполнен видимым перебором дат ("July 9, 455 AD: the
    # Vandals sacked Rome (that was June 2)... July 9, 48 BC: Caesar crossed into Greece...")
    # БЕЗ единого символа "{" — весь бюджет 1600 токенов ушёл на рассуждение, JSON не
    # начинался вообще. Точно та же болезнь, что уже чинили в word_count (см. «Самопроверка
    # длины 2026-07-01» в README) — там тоже "count it, trim, recount" в тексте ответа
    # приводило к видимым рассуждениям и упору в max_tokens. Тот же фикс: явно "молча".
    if on_this_day:
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%B %d")
        user_content += (
            f"\n\nTOPICAL OVERRIDE — today is {today}. Instead of a generic fact, find a real, "
            "verifiable historical event or discovery tied to THIS calendar date (any year), "
            "ideally within the topic above — if nothing natural fits the topic, any strong "
            "date-tied fact works. Weave the anniversary into the script naturally (e.g. "
            "'Exactly 143 years ago today...'). Recall and verify the date SILENTLY — do NOT "
            "show any candidate dates, reasoning, or draft text before the JSON; go straight "
            "to the final JSON answer. The date claim must be REAL — if you cannot silently "
            "recall a solid dated fact with real confidence, write the usual fact WITHOUT "
            "inventing a date, still going straight to JSON with no visible deliberation."
        )

    # Ретрай битого JSON (2026-07-05): в отличие от generate_series.py/generate_longform_script.py
    # (там добавлено раньше после прод-падений), здесь парсинг падал без права на восстановление —
    # один сломанный ответ модели ронял весь слот публикации (реальный случай: 2026-07-05 00:07 UTC).
    #
    # on_this_day fallback (2026-07-09): реальный прод-случай — ES 03:17 упал 3/3 попытки с
    # ПУСТЫМ ответом модели (message.content[0].text == "", не битый JSON, а вообще ничего) на
    # topical-промпте "On this day". У ES нет watchdog — упавший слот терялся безвозвратно. Если
    # ВСЕ 3 topical-попытки не распарсились, делаем ЕЩЁ ОДНУ попытку БЕЗ topical override —
    # честный обычный факт лучше потерянного слота, тот же принцип, что и явная инструкция
    # модели "if you cannot recall a solid dated fact, write the usual fact" — только на уровне
    # кода, на случай если сама проблема была в topical-формулировке промпта, а не в факте.
    def _try_generate(content: str, attempts: int) -> tuple[dict | None, Exception | None]:
        last_err = None
        for attempt in range(attempts):
            message = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1600,
                system=system_prompt,
                messages=[{"role": "user", "content": content}],
            )
            try:
                return _parse_response(message), None
            except json.JSONDecodeError as e:
                last_err = e
                print(f"  Script JSON parse failed (attempt {attempt + 1}/{attempts}): {e}; retrying...")
        return None, last_err

    data, last_err = _try_generate(user_content, 3)
    if data is None and on_this_day:
        print("  Topical-режим не распарсился 3/3 — пробуем обычную генерацию без даты (fallback).")
        fallback_content = _build_user_content(topic, avoid_block, title_instruction,
                                                pair_start=pair_start, pair_resolve_claim=pair_resolve_claim)
        data, last_err = _try_generate(fallback_content, 2)
        if data is not None:
            on_this_day = False  # data["topical"] ниже должен честно отражать, что дата не вошла
    if data is None:
        raise RuntimeError(f"Script JSON невалиден после всех попыток: {last_err}")

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
    data["topical"] = bool(on_this_day)          # тег topical-onthisday (pipeline.py)
    data["niche_styled"] = bool(_niche_titles_for(topic))  # тег niche-styled (pipeline.py)
    # Video pairs (2026-07-08, см. paired_facts.py): нормализуем — модель может вернуть не-строку/
    # не-bool, пустое значение или молчание (не относится к этому вызову) не должно всплывать.
    data["pairable_claim"] = str(data.get("pairable_claim", "")).strip() if pair_start else ""
    data["pair_resolved"] = bool(data.get("pair_resolved")) if pair_resolve_claim else False
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
    if isinstance(data.get("tags"), list):
        data["tags"] = _drop_corrupted(data["tags"])
        data["tags"] = _enrich_tags_with_suggestions(data["tags"])
    if isinstance(data.get("hashtags"), list):
        data["hashtags"] = _drop_corrupted(data["hashtags"])
    return data


if __name__ == "__main__":
    print(json.dumps(generate_script(), ensure_ascii=False, indent=2))
