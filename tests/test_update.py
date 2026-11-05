"""Update check: GitHub's latest release vs the running version. The network is always mocked."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from bg3coop import cli, update


@pytest.fixture
def github(monkeypatch):
    """Answer urlopen with `state["tag"]`, or raise when it is an exception."""
    state = {"tag": "v9.0.0", "calls": []}

    def urlopen(req, timeout):
        state["calls"].append((req.full_url, timeout))
        if isinstance(state["tag"], Exception):
            raise state["tag"]
        return io.BytesIO(json.dumps({"tag_name": state["tag"]}).encode())

    monkeypatch.delenv(update.OPT_OUT, raising=False)
    monkeypatch.setattr(update.urllib.request, "urlopen", urlopen)
    return state


def test_is_newer():
    assert update.is_newer("0.10.0", "0.9.1")
    assert update.is_newer("v1.0", "0.9")
    assert not update.is_newer("0.1.0", "0.1.0")
    assert not update.is_newer("0.1.0", "0.2.0")
    assert not update.is_newer("nightly", "0.1.0")


def test_latest_version(github):
    assert update.latest_version() == "9.0.0"
    url, timeout = github["calls"][0]
    assert url == update.API and timeout <= 5


@pytest.mark.parametrize("err", [urllib.error.URLError("offline"), TimeoutError(), ValueError("bad json")])
def test_failures_mean_unknown(github, err):
    github["tag"] = err
    assert update.latest_version() is None


def test_opt_out(github, monkeypatch):
    monkeypatch.setenv(update.OPT_OUT, "1")
    assert update.latest_version() is None
    assert github["calls"] == []


def test_notice():
    assert update.notice(None, "0.1.0") is None
    assert update.notice("0.1.0", "0.1.0") is None
    assert update.notice("0.2.0", "0.0.0") is None  # source tree
    msg = update.notice("0.2.0", "0.1.0")
    assert "0.2.0" in msg and "bg3coop setup" in msg and update.RELEASES in msg


def test_background_hands_out_once(github, monkeypatch):
    monkeypatch.setattr(update, "__version__", "0.1.0")
    bg = update.Background()
    bg._check()
    assert "9.0.0" in bg.take()
    assert bg.take() is None


def test_tool_result_carries_the_notice_once(monkeypatch):
    from bg3coop import server

    monkeypatch.setattr(server.chat, "listen", lambda status=None, activity=None: False)
    monkeypatch.setattr(server.chat, "begin", lambda tool, kw: {"done": tool})
    monkeypatch.setattr(server.chat, "header", lambda: None)
    monkeypatch.setattr(server, "_updates", update.Background())

    @server._safe
    def tool():
        return "fine"

    assert tool() == "fine"
    server._updates.set("bg3coop 9.0.0 is out.")
    first = tool()
    assert first["result"] == "fine" and first["update"].startswith("bg3coop 9.0.0 is out.")
    assert tool() == "fine"


@pytest.mark.parametrize("tag,level", [("v9.0.0", "WARN"), (None, "OK"), (urllib.error.URLError("x"), "SKIP")])
def test_doctor_line(github, monkeypatch, capsys, tag, level):
    monkeypatch.setattr(update, "__version__", "0.1.0")
    github["tag"] = "v0.1.0" if tag is None else tag
    r = cli.Report()
    cli._check_update(r)
    line = capsys.readouterr().out
    assert line.startswith(level) and not r.failed
