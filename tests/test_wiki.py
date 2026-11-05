"""bg3.wiki lookups with the network replaced by canned MediaWiki API answers."""

from __future__ import annotations

import io
import json
import urllib.parse

import pytest

from bg3coop import wiki

FIREBALL = ("Fireball  is a level 3 evocation spell.\n\n\n==  ==\nShoot a bright flame for 8d6⁠⁠Fire"
            " damage.\n\n\n===  ===\n Range: 18 m\n\t\tAoE: 4 m")


@pytest.fixture()
def api(monkeypatch):
    """pages: title (any case) -> extract; search: query -> titles. Records the requests."""
    data = {"pages": {"fireball": ("Fireball", FIREBALL)}, "search": {}, "calls": []}

    def urlopen(req, timeout=None):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(req.full_url).query))
        data["calls"].append(q)
        assert req.full_url.startswith(wiki.API) and q["format"] == "json" and timeout
        assert req.headers["User-agent"].startswith("bg3coop/")
        if q.get("list") == "search":
            body = {"query": {"search": [{"title": t} for t in data["search"].get(q["srsearch"], [])]}}
        else:
            hit = data["pages"].get(q["titles"].lower())
            page = {"title": hit[0], "extract": hit[1]} if hit else {"title": q["titles"], "missing": True}
            body = {"query": {"pages": [page]}}
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(wiki.urllib.request, "urlopen", urlopen)
    return data


def test_page_by_title(api):
    r = wiki.lookup("fireball")
    assert r["title"] == "Fireball" and r["url"] == "https://bg3.wiki/wiki/Fireball"
    assert r["text"] == ("Fireball is a level 3 evocation spell.\n\nShoot a bright flame for 8d6Fire damage."
                         "\n\nRange: 18 m\nAoE: 4 m")
    assert "more" not in r and "see_also" not in r
    assert len(api["calls"]) == 1  # no search needed


def test_falls_back_to_search(api):
    api["search"]["Projectile_Fireball"] = ["Fireball", "Flames of the Phoenix"]
    r = wiki.lookup("Projectile_Fireball")
    assert r["title"] == "Fireball" and r["see_also"] == ["Flames of the Phoenix"]


def test_long_pages_come_in_parts(api, monkeypatch):
    monkeypatch.setattr(wiki, "MAX_CHARS", 10)
    api["pages"]["long"] = ("Long", "abcdefghij" * 3)
    r = wiki.lookup("Long")
    assert r["text"] == "abcdefghij" and "offset=10" in r["more"]
    last = wiki.lookup("Long", offset=20)
    assert last["text"] == "abcdefghij" and "more" not in last


def test_nothing_found(api):
    with pytest.raises(wiki.WikiError, match="English"):
        wiki.lookup("火球术")
    with pytest.raises(wiki.WikiError, match="nothing"):
        wiki.lookup("zzz")
    with pytest.raises(wiki.WikiError):
        wiki.lookup("  ")


def test_offline(monkeypatch):
    def down(req, timeout=None):
        raise OSError("blocked")

    monkeypatch.setattr(wiki.urllib.request, "urlopen", down)
    with pytest.raises(wiki.WikiError, match="could not be reached"):
        wiki.lookup("Fireball")


def test_tool_returns_errors_as_text(monkeypatch):
    from bg3coop import server

    monkeypatch.setattr(server.chat, "listen", lambda status=None, activity=None: False)
    monkeypatch.setattr(server.chat, "begin", lambda tool, kw: {"done": tool})
    monkeypatch.setattr(server.bg3wiki, "lookup", lambda q, o: (_ for _ in ()).throw(wiki.WikiError("down")))
    assert server.wiki("Fireball") == {"error": "down"}
