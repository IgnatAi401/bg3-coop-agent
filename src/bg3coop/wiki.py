"""Look things up on bg3.wiki (the community Baldur's Gate 3 wiki) through its MediaWiki API.

Standard library only. The wiki is English: search by English name or by a game id such as
Projectile_Fireball (what `spells` lists), not by a localised name.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any

from . import __version__

SITE = "https://bg3.wiki"
API = f"{SITE}/w/api.php"
MAX_CHARS = 4000
_TIMEOUT = 10


class WikiError(Exception):
    pass


def _get(params: dict[str, Any]) -> dict:
    query = urllib.parse.urlencode({"format": "json", "formatversion": 2, **params})
    req = urllib.request.Request(f"{API}?{query}", headers={"User-Agent": f"bg3coop/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return json.load(r)
    except Exception as e:  # network, HTTP, JSON
        raise WikiError(f"bg3.wiki could not be reached ({type(e).__name__}): the network may block it") from e


def page_url(title: str) -> str:
    return f"{SITE}/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"


def clean(text: str) -> str:
    """Tidy a plain-text extract: drop the empty heading lines and invisible characters it keeps."""
    text = text.replace("⁠", "").replace(" ", " ").replace("\t", " ")
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if not re.fullmatch(r"=*\s*=*", ln) or not ln]
    text = "\n".join(lines)
    text = re.sub(r"[ ]{2,}", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _extract(title: str) -> dict | None:
    pages = _get({"action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1,
                  "titles": title}).get("query", {}).get("pages", [])
    page = pages[0] if pages else None
    if not page or page.get("missing") or page.get("invalid") or not page.get("extract"):
        return None
    return page


def _search(query: str, limit: int = 6) -> list[str]:
    hits = _get({"action": "query", "list": "search", "srsearch": query, "srlimit": limit,
                 "srprop": ""}).get("query", {}).get("search", [])
    return [h["title"] for h in hits if h.get("title")]


def lookup(query: str, offset: int = 0) -> dict:
    """The page whose title matches `query` (else the best search hit) as plain text, cut to MAX_CHARS
    starting at `offset`; `see_also` lists other matching titles."""
    query = query.strip()
    if not query:
        raise WikiError("empty query")
    page = _extract(query)
    others: list[str] = []
    if page is None:
        others = _search(query)
        if not others:
            hint = " The wiki is in English: search by English name or by a game id." \
                if re.search(r"[^\x00-\x7f]", query) else ""
            raise WikiError(f"nothing on bg3.wiki matches {query!r}.{hint}")
        page = _extract(others[0])
        if page is None:
            return {"title": others[0], "url": page_url(others[0]), "text": "", "see_also": others[1:]}
    title = page["title"]
    text = clean(page["extract"])
    offset = max(0, offset)
    out: dict[str, Any] = {"title": title, "url": page_url(title), "text": text[offset:offset + MAX_CHARS]}
    if offset + MAX_CHARS < len(text):
        out["more"] = f"page goes on: pass offset={offset + MAX_CHARS} for the rest ({len(text)} chars)"
    see_also = [t for t in others if t != title]
    if see_also:
        out["see_also"] = see_also
    return out
