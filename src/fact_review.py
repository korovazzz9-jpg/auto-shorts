"""Independent, bounded source check for an ES script before video production."""

import json
import os

from anthropic import Anthropic


def _json_from_text(text: str) -> dict:
    decoder = json.JSONDecoder()
    for i, char in enumerate(text):
        if char == "{":
            try:
                value, _ = decoder.raw_decode(text[i:])
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError:
                pass
    return {}


def verify_es_script(data: dict, client=None) -> tuple[bool, str]:
    """One web search and one small Haiku verdict. Uncertain claims fail review."""
    if client is None:
        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=2)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=900,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}],
        system=("You are an independent fact checker. Search the web for the core event, "
                "then check EVERY sentence of the title and script against the results. "
                "A real event with an invented date, "
                "number, cause, mechanism, person, or outcome is UNSUPPORTED. Do not infer "
                "support from a source that merely mentions the event. Prefer primary sources "
                "(government, museum, research institution). If the one search cannot verify "
                "all important concrete claims, including negative claims (no evidence, nobody knows) "
                "and descriptions of victims or motives, return supported=false. An estimate or 'up to N' "
                "does not support an exact count of N. Do not approve plausible embellishments "
                "about weight, physical impossibility, intent, or supernatural purpose without "
                "explicit source support. Do not rewrite the script. "
                "Return only JSON: {\"supported\": true/false, \"reason\": \"brief reason\"}."),
        messages=[{"role": "user", "content": json.dumps(
            {"title": data.get("title", ""), "script": data.get("script", "")},
            ensure_ascii=False)}],
    )
    searched = any(getattr(block, "type", None) == "server_tool_use" and
                   getattr(block, "name", None) == "web_search" for block in message.content)
    text = "\n".join(block.text for block in message.content
                     if getattr(block, "type", None) == "text")
    verdict = _json_from_text(text)
    reason = str(verdict.get("reason") or
                 f"no grounded verdict (stop={getattr(message, 'stop_reason', 'unknown')}, "
                 f"text_chars={len(text)}, searched={searched})")[:600]
    return searched and verdict.get("supported") is True, reason


def repair_es_script(data: dict, reason: str, client=None) -> dict:
    """Use the existing second Sonnet call to remove a reviewer's concrete error."""
    from config import CFG
    from script_facts import check_consistency

    if client is None:
        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=2)
    loop_tail = next((phrase for pool in CFG.get("loop_phrases", {}).values()
                      for phrase in pool if data["script"].endswith(phrase)), "")
    script = data["script"][:-len(loop_tail)].rstrip() if loop_tail else data["script"]
    message = client.messages.create(
        model="claude-sonnet-4-6", max_tokens=1800,
        system=("Repair a Spanish factual Shorts script after independent source review. "
                "Preserve the documented core event, vivid opening and narrative pace. "
                "Remove or correct every claim named in the review; do not invent a new "
                "date, number, mechanism, motive, or source. If the core event cannot be "
                "salvaged, return {}. Return JSON only with title, script, video_queries, "
                "hook_text, search_summary and comment_question. The script must be "
                "58-80 Spanish words, and video_queries must match the revised beats. "
                "Do not add a loop line; it will be restored separately."),
        messages=[{"role": "user", "content": json.dumps({
            "title": data.get("title"), "script": script,
            "video_queries": data.get("video_queries"),
            "source_url": data.get("source_url"), "review_error": reason,
        }, ensure_ascii=False)}],
    )
    answer = "\n".join(block.text for block in message.content
                       if getattr(block, "type", None) == "text")
    fixed = _json_from_text(answer)
    required = ("title", "script", "video_queries", "hook_text", "search_summary", "comment_question")
    if any(not fixed.get(key) for key in required):
        raise ValueError("repair did not return a complete script")
    if not isinstance(fixed["video_queries"], list) or not all(
        isinstance(query, str) and query.strip() for query in fixed["video_queries"]
    ):
        raise ValueError("repair returned invalid video queries")
    revised = dict(data)
    revised.update({key: fixed[key] for key in required})
    if loop_tail:
        revised["script"] = revised["script"].rstrip() + " " + loop_tail
    if not 58 <= len(revised["script"].split()) <= 90:
        raise ValueError("repaired script length outside Shorts range")
    problems = check_consistency(revised)
    if problems:
        raise ValueError("repaired title and script disagree: " + "; ".join(problems))
    return revised
