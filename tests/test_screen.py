"""Turn screenshots: one picture per combat turn of the agent, handed to the agent as an image."""

from __future__ import annotations

import asyncio
import base64
import json

import pytest

from bg3coop import screen
from test_offline import env  # noqa: F401  (fixture)

SH = "3ed74f06-3c60-42dc-83f6-f034cb47c679"
JPEG = b"\xff\xd8\xff\xe0fake"


@pytest.fixture()
def shots(env, monkeypatch):  # noqa: F811
    fake, s = env
    taken = []

    def grab():
        taken.append(1)
        return JPEG

    monkeypatch.setattr(s.shots, "available", lambda: True)
    monkeypatch.setattr(s.shots, "grab", grab)
    s.set_agent("Shadowheart")
    return fake, s, taken


def test_once_per_turn_from_wait_then_combat(shots):
    fake, s, taken = shots
    s.wait(1)  # the backlog
    fake.server.execute(f"MOCK.combat = true; MOCK.turn = '{SH}'; MOCK.fire('TurnStarted', '{SH}')")
    r = s.wait(1)
    text, image = r.content
    assert image.mime_type == "image/jpeg" and base64.b64decode(image.data) == JPEG
    out = r.structured_content["result"]
    assert json.loads(text.text) == out
    assert "your_turn" in [e["kind"] for e in out["events"]] and "screen" in out["screenshot"]
    assert "_screenshot" not in out
    assert isinstance(s.combat(), dict) and len(taken) == 1  # already seen this turn
    assert s.end_turn()["ended"]
    fake.server.execute("MOCK.turn = nil")
    # the next round, found through combat, not wait
    fake.server.execute(f"MOCK.turn = '{SH}'; MOCK.fire('TurnStarted', '{SH}')")
    r = s.combat()
    assert r.structured_content["result"]["my_turn"] and len(r.content) == 2 and len(taken) == 2


def test_not_on_others_turns_and_failures_are_noted_once(shots, monkeypatch):
    fake, s, taken = shots
    fake.server.execute("MOCK.combat = true; MOCK.turn = nil")
    assert isinstance(s.combat(), dict) and not taken

    def fail():
        raise screen.ShotError("game window is not in front")

    monkeypatch.setattr(s.shots, "grab", fail)
    fake.server.execute(f"MOCK.turn = '{SH}'")
    assert "not in front" in s.combat()["screenshot"]
    assert "screenshot" not in s.combat()


def test_off_switch_and_no_windows(monkeypatch):
    t = screen.TurnShots(None)
    monkeypatch.setattr(screen.sys, "platform", "darwin")
    assert not t.available()
    monkeypatch.setattr(screen.sys, "platform", "win32")
    assert t.available()
    monkeypatch.setenv("BG3COOP_SCREENSHOTS", "0")
    assert not t.available()


def test_capture_log_and_platform():
    screen._parse("OK 1280 720\n")
    with pytest.raises(screen.ShotError, match="minimized"):
        screen._parse("ERR game window is minimized\n")
    with pytest.raises(screen.ShotError, match="did not run"):
        screen._parse("Get-Command : python not found")
    if screen.sys.platform != "win32":
        with pytest.raises(screen.ShotError, match="Windows"):
            screen.grab_local()


def test_mcp_sends_text_and_image(shots):
    fake, s, _ = shots
    fake.server.execute(f"MOCK.combat = true; MOCK.turn = '{SH}'")
    res = asyncio.run(s.mcp.call_tool("combat", {}))
    blocks = res.content if hasattr(res, "content") else res
    kinds = [b.type for b in blocks]
    assert kinds == ["text", "image"] and blocks[1].mime_type == "image/jpeg"
    assert '"my_turn": true' in blocks[0].text


def test_the_picture_is_taken_while_the_turn_is_put_together(monkeypatch):
    import threading
    import time

    t = screen.TurnShots("somehost")
    started = threading.Event()

    def slow():
        started.set()
        time.sleep(0.3)
        return b"jpeg"

    monkeypatch.setattr(t, "grab", slow)
    t.start()
    assert started.wait(1)  # already being taken, before attach is called
    r = t.attach({}, "_shot")
    assert r["_shot"] == b"jpeg" and r["screenshot"] == screen.NOTE
    assert t.attach({}, "_shot") == {}  # once per turn
    t.turn_over()
    t.start()
    assert t.attach({}, "_shot")["_shot"] == b"jpeg"
