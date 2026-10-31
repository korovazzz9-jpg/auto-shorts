"""Cheap, conservative checks before a generated fact enters the ES batch queue.

These checks confirm that a cited passage exists; they cannot prove that the
passage entails every statement in the script. Ambiguous claims still need review.
"""

import html
import re
import unicodedata
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import Request, urlopen


_YEAR = re.compile(r"(?<!\d)(?:1[5-9]\d{2}|20\d{2})(?!\d)")
_SKIP = {"para", "hace", "años", "desde", "entre", "sobre", "cuando", "donde",
         "nunca", "nadie", "minutos", "horas", "siglo", "siglos", "mundo",
         "entero", "entera", "propios", "propias", "propio", "propia", "solo",
         "tormenta", "terremoto", "sonda", "niño", "ciudad", "mar", "río"}
_TRUSTED_HOSTS = (".gov", ".edu", "iceman.it", "britishmuseum.org", "nature.com",
                  "science.org", "heraklionmuseum.gr", "smithsonianmag.com",
                  "britannica.com", ".museum")


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", html.unescape(value).lower())
    value = "".join(c for c in value if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", value))


class _PageText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def check_consistency(data: dict) -> list[str]:
    """Check anchors that can be compared without another model call."""
    title = str(data.get("title") or "")
    script = str(data.get("script") or "")
    summary = str(data.get("search_summary") or "")
    problems = []
    missing_years = set(_YEAR.findall(title)) - set(_YEAR.findall(script))
    if missing_years:
        problems.append(f"title years absent from script: {', '.join(sorted(missing_years))}")
    title_words = {w for w in _norm(title).split() if len(w) >= 4 and w not in _SKIP}
    story_words = set(_norm(script + " " + summary).split())
    if title_words and not title_words & story_words:
        problems.append("title subject absent from script and summary")
    return problems


def check_source(data: dict, fetch=None) -> list[str]:
    """Require a real source page containing the model's claimed verbatim passage."""
    url = str(data.get("source_url") or "").strip()
    quote = str(data.get("source_quote") or "").strip()
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return ["invalid source URL"]
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or port not in (None, 443) or not any(
        host == suffix.lstrip(".") or host.endswith(suffix) for suffix in _TRUSTED_HOSTS
    ):
        return ["missing trusted HTTPS source URL"]
    if len(_norm(quote)) < 40:
        return ["missing substantive source quote"]
    title = str(data.get("title") or "")
    if set(_YEAR.findall(title)) - set(_YEAR.findall(quote)):
        return ["source quote omits title year"]
    subject = {w for w in _norm(title).split() if len(w) >= 4 and w not in _SKIP}
    if subject and not subject & set(_norm(quote).split()):
        return ["source quote omits title subject"]
    try:
        if fetch is None:
            request = Request(url, headers={"User-Agent": "Mozilla/5.0 auto-shorts-source-check"})
            with urlopen(request, timeout=10) as response:
                if response.status != 200:
                    return [f"source HTTP {response.status}"]
                page = response.read(750_000).decode("utf-8", errors="replace")
        else:
            page = fetch(url)
        reader = _PageText()
        reader.feed(page)
        if _norm(quote) not in _norm(" ".join(reader.parts)):
            return ["source quote not found on cited page"]
    except Exception as exc:
        return [f"source unavailable ({type(exc).__name__})"]
    return []
