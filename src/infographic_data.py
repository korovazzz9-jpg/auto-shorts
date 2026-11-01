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


def _overlap(a: list[str], b: list[str]) -> int:
    previous = [0] * (len(b) + 1)
    for word in a:
        current = [0]
        for j, other in enumerate(b, 1):
            current.append(previous[j - 1] + 1 if word == other
                           else max(current[-1], previous[j]))
        previous = current
    return previous[-1]


def _literal_span(phrase: str, script: str, limit: int, allow_short_anchor: bool = False) -> str | None:
    """Find a close verbatim script span, dropping paraphrased words, never adding facts."""
    if not isinstance(phrase, str) or not 3 <= len(phrase.strip()) <= 48:
        return None
    query = _plain(phrase).split()
    if not query:
        return None
    if len(phrase.strip()) <= limit and f" {_plain(phrase)} " in f" {_plain(script)} ":
        return phrase.strip()
    words = list(re.finditer(r"\b\w+\b", script, re.UNICODE))
    digits = re.findall(r"\d+", _plain(phrase))
    best = (0, 0.0, 0, "")
    for start in range(len(words)):
        for end in range(start + 1, min(start + 8, len(words) + 1)):
            candidate = script[words[start].start():words[end - 1].end()]
            if len(candidate) > limit:
                break
            tokens = _plain(candidate).split()
            if re.findall(r"\d+", _plain(candidate)) != digits:
                continue
            matches = _overlap(query, tokens)
            if matches < (1 if len(query) == 1 else 2):
                continue
            score = matches / max(len(query), len(tokens))
            if score >= 0.6 and (matches, score, -len(tokens), candidate) > best:
                best = (matches, score, -len(tokens), candidate)
    if best[3]:
        return best[3]
    # A two-word before/after label may paraphrase its adjective. Keep only
    # the spoken noun; never drop a quantity or unit to make a claim pass.
    quantitative = {"cero", "uno", "una", "dos", "tres", "cuatro", "cinco",
                    "seis", "siete", "ocho", "nueve", "diez", "cien",
                    "ciento", "mil", "millon", "metros", "kilometros", "anos"}
    if (allow_short_anchor and len(query) == 2 and not any(
            word.isdigit() or word in quantitative for word in query)
            and len(query[0]) >= 5):
        for word in words:
            if _plain(word.group()) == query[0]:
                return word.group()
    return None


def normalize_card(card, script: str, video_queries: list) -> dict | None:
    """Use only short literal phrases already present in the checked narration."""
    if not isinstance(card, dict) or card.get("type") not in KINDS or not isinstance(video_queries, list):
        return None
    subject, items, after = card.get("subject"), card.get("items"), card.get("after_query")
    if not isinstance(items, list) or len(items) != (3 if card["type"] in THREE_ITEM_KINDS else 2):
        return None
    if not isinstance(after, int) or isinstance(after, bool) or not 3 <= after <= len(video_queries):
        return None
    phrases = [_literal_span(subject, script, 36)] + [
        _literal_span(item, script, 32, card["type"] == "before_after") for item in items]
    if any(phrase is None for phrase in phrases):
        return None
    script_plain = _plain(script)
    for phrase in phrases:
        if any(ord(c) < 32 for c in phrase):
            return None
        if f" {_plain(phrase)} " not in f" {script_plain} ":
            return None
    if len({_plain(item) for item in phrases[1:]}) != len(items):
        return None
    return {"type": card["type"], "subject": phrases[0],
            "items": phrases[1:], "after_query": after}
