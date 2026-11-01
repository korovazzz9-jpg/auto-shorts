"""Strict, dependency-free schema for one optional ES infographic scene."""

import re
import unicodedata


KINDS = {"route", "before_after", "timeline", "comparison",
         "cause_effect", "layers", "cycle", "part_whole"}
THREE_ITEM_KINDS = {"timeline", "layers", "cycle"}


def _plain(value: str) -> str:
    value = "".join(c for c in unicodedata.normalize("NFKD", value.casefold())
                    if not unicodedata.combining(c))
    return " ".join(re.findall(r"[\w]+", value))


def normalize_card(card, script: str, video_queries: list) -> dict | None:
    """Use only short literal phrases already present in the checked narration."""
    if not isinstance(card, dict) or card.get("type") not in KINDS or not isinstance(video_queries, list):
        return None
    subject, items, after = card.get("subject"), card.get("items"), card.get("after_query")
    if not isinstance(subject, str) or not 3 <= len(subject.strip()) <= 36:
        return None
    if not isinstance(items, list) or len(items) != (3 if card["type"] in THREE_ITEM_KINDS else 2):
        return None
    if not isinstance(after, int) or isinstance(after, bool) or not 3 <= after <= len(video_queries):
        return None
    script_plain = _plain(script)
    for phrase, limit in [(subject, 36)] + [(item, 24) for item in items]:
        if not isinstance(phrase, str) or not 3 <= len(phrase.strip()) <= limit:
            return None
        if any(ord(c) < 32 for c in phrase):
            return None
        exact = _plain(phrase)
        if not exact or f" {exact} " not in f" {script_plain} ":
            return None
    if len({_plain(item) for item in items}) != len(items):
        return None
    return {"type": card["type"], "subject": subject.strip(),
            "items": [item.strip() for item in items], "after_query": after}
