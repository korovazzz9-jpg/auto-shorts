"""Генерирует сценарий для длинного (3-5 мин) видео — три чередующихся формата:
  deep_dive  — один факт, глубокий нарратив с хронологией и персонажами
  mystery    — открываем с результатом, разматываем загадку до развязки
  versus     — два явления/эпохи/места в контрасте, tension до конца
Формат чередуется каждую неделю через longform_state_<channel>.json в репо."""
import json
import os
import random

from anthropic import Anthropic

from config import CFG, CHANNEL
from generate_script import TOPICS_POOL as THEMES
from recent_titles import get_recent_titles

# Порядок ротации форматов
FORMAT_CYCLE = ["deep_dive", "mystery", "versus"]

STATE_FILE = os.path.join(
    os.path.dirname(__file__), "..", f"longform_state_{CHANNEL}.json"
)

SYSTEM_BASE = """You are a scriptwriter for {channel}, a YouTube channel about mind-blowing,
misconception-busting facts. Write the ENTIRE script in {language}.
Conversational, energetic, no filler. Do NOT open with "Today I'll tell you about" or any
warm-up. Cut straight into the most gripping moment."""

FORMAT_PROMPTS = {
    "deep_dive": """FORMAT: Deep Dive (one fact, full narrative, 3.5-5 min, 550-750 words).
Pick ONE lesser-known historical event, biological phenomenon, or discovery. Build it as a
mini-documentary: real names, real dates, a clear before/after in understanding. Structure:
  1. Hook — drop into the most dramatic moment first (in medias res), no warm-up
  2. Context — just enough background so the stakes are clear
  3. The core fact/discovery — the moment everything changed
  4. Twist — the implication most people never consider
  5. CTA — ask viewers to subscribe and comment what surprised them most
Use transitions that pull forward ("But nobody knew what was about to happen next.",
"Here's the part history books leave out."). Avoid lists — this is one continuous story.""",

    "mystery": """FORMAT: Mystery/Thriller (open with outcome, unravel the cause, 3.5-5 min, 550-750 words).
Pick a real historical mystery, unexplained event, or counterintuitive discovery. Structure:
  1. Hook — open with the shocking RESULT, not the setup. Make it sound unsolvable.
     ("In 1952, 12,000 people in one city died in five days. Nobody understood why for years.")
  2. Investigation — walk through what was known at the time, layer by layer
  3. The breakthrough — the moment the real cause was found (or wasn't — if still unsolved,
     the best current theory)
  4. Implication — what this reveals that most people still don't know
  5. CTA — ask viewers to subscribe and comment their theory or reaction
The viewer must feel they CAN'T leave before the answer. No lists — continuous narration.""",

    "versus": """FORMAT: Versus/Contrast (two things in direct comparison, 3.5-5 min, 550-750 words).
Pick two civilizations, eras, species, phenomena, or strategies that are commonly compared but
whose real difference most people misunderstand. Structure:
  1. Hook — open with a question or claim that sets up the contrast sharply
     ("Everyone knows Rome fell. Almost no one knows why China didn't — at the exact same time.")
  2. Side A — the story/facts for the first subject
  3. The turn — the moment where the contrast becomes surprising
  4. Side B — the story/facts for the second subject, in light of the turn
  5. Payoff — the single insight that explains the difference most people miss
  6. CTA — ask viewers to subscribe and comment which side surprised them more
Keep tension between the two sides alive throughout. No lists — continuous narration.""",
}

COMMON_SUFFIX = """
Each individual fact must overturn a common intuitive assumption — not just an interesting
detail, but something that breaks what people assume is true. Avoid abstract/technical facts
requiring specialist background (quantum mechanics, advanced math, physics)."""


def _load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_format_index": -1}


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _next_format(state: dict) -> str:
    idx = (state.get("last_format_index", -1) + 1) % len(FORMAT_CYCLE)
    state["last_format_index"] = idx
    return FORMAT_CYCLE[idx]


def generate_longform_script() -> dict:
    state = _load_state()
    fmt = _next_format(state)

    theme = random.choice(THEMES)
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=5)

    try:
        past_titles = get_recent_titles()
    except Exception:
        past_titles = []

    avoid_block = ""
    if past_titles:
        avoid_block = (
            "Already-published video titles on this channel — don't reuse these specific facts:\n"
            + "\n".join(f"- {t}" for t in past_titles) + "\n\n"
        )

    system_prompt = (
        SYSTEM_BASE.format(channel=CFG["channel_name"], language=CFG["script_language"])
        + "\n\n"
        + FORMAT_PROMPTS[fmt]
        + COMMON_SUFFIX
    )

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2500,
        system=system_prompt,
        messages=[{
            "role": "user",
            "content": (
                avoid_block +
                f"Theme: {theme}. Write the script. Break it into 15-20 visual beats "
                "(roughly one every 12-15 seconds) and for each one write a short "
                "stock-footage search query (2-4 words, concrete, visual, in English — "
                "prefer wide scenes, landscapes, human action over specific objects).\n\n"
                "Requirements:\n"
                f"- title: compelling narrative hook in {CFG['script_language']}, under 70 "
                "characters. Must read like a real headline, NOT a listicle "
                "(no '5 Facts...' / 'X Things...' patterns).\n"
                f"- tags: 10-15 specific YouTube search tags in {CFG['script_language']}.\n"
                f"- hashtags: 3-5 hashtags in {CFG['script_language']} (lowercase, with # prefix).\n\n"
                "Respond strictly in JSON, no markdown wrapper: "
                '{"title": "title text", '
                '"script": "full voiceover script", '
                '"tags": ["tag1", ...], '
                '"hashtags": ["#tag1", ...], '
                '"video_queries": ["query1", ...]}'
            ),
        }],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
    start, end = raw.find("{"), raw.rfind("}")
    data = json.loads(raw[start:end + 1])
    data["theme"] = theme
    data["longform_format"] = fmt

    _save_state(state)
    return data


if __name__ == "__main__":
    print(json.dumps(generate_longform_script(), ensure_ascii=False, indent=2))
