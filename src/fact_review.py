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
        max_tokens=500,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}],
        system=("You are an independent fact checker. Search the web for the MOST specific "
                "claim in the supplied title and script. A real event with an invented date, "
                "number, cause, mechanism, person, or outcome is UNSUPPORTED. Do not infer "
                "support from a source that merely mentions the event. Prefer primary sources "
                "(government, museum, research institution). If the one search cannot verify "
                "all important concrete claims, return supported=false. Do not rewrite the script. "
                "Return only JSON: {\"supported\": true/false, \"reason\": \"brief reason\"}."),
        messages=[{"role": "user", "content": json.dumps(
            {"title": data.get("title", ""), "script": data.get("script", ""),
             "source_hint": data.get("source_url") or data.get("source_note") or ""},
            ensure_ascii=False)}],
    )
    searched = any(getattr(block, "type", None) == "server_tool_use" and
                   getattr(block, "name", None) == "web_search" for block in message.content)
    text = "\n".join(block.text for block in message.content
                     if getattr(block, "type", None) == "text")
    verdict = _json_from_text(text)
    reason = str(verdict.get("reason") or "no grounded verdict")[:200]
    return searched and verdict.get("supported") is True, reason
