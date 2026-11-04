"""The bridge's side of the in-game chat panel: what the human typed or clicked, Yes/No questions, and
the status line at the top of the panel (who the agent plays, HP, what it is doing)."""

from __future__ import annotations

import time
from typing import Any

from .game import Game, GameError
from .handles import Handles

# What the status line says the agent is doing, by the tool it called last.
DOING = {
    "move": "walking", "use": "using something", "talk": "talking", "dialogue": "talking",
    "choose": "talking", "cast": "in combat", "end_turn": "in combat", "wait": "waiting",
    "job_status": "busy", "look": "looking around", "status": "looking around",
    "spells": "checking spells", "container": "looting", "take": "looting",
    "stop": "stopped", "regroup": "following you", "inventory": "checking the bag",
    "use_item": "using an item", "throw": "throwing something", "equip": "changing gear",
    "give": "handing you something", "combat": "in combat",
    "examine": "looking around", "notes": "taking notes", "quests": "reading the journal",
    "wiki": "reading the wiki", "sneak": "sneaking", "sight": "looking around", "trade": "trading",
}
# What the human reads in the panel, when the game runs in Simplified Chinese.
ZH = {
    "walking": "走路", "using something": "使用物体", "talking": "对话中", "in combat": "战斗中",
    "waiting": "等待", "busy": "忙", "looking around": "观察四周", "checking spells": "查看法术",
    "looting": "搜刮", "stopped": "停下了", "following you": "跟着你", "checking the bag": "查看背包",
    "using an item": "使用物品", "throwing something": "投掷", "changing gear": "换装备",
    "handing you something": "给你东西", "taking notes": "记笔记", "reading the journal": "看任务日志",
    "reading the wiki": "查 wiki", "sneaking": "潜行", "trading": "交易", "my turn": "我的回合",
    "asking you": "在问你", "> Yes": "> 是", "> No": "> 否", "(no answer in time)": "（没有及时回答）",
}

POPUP_EVERY_S = 60  # `say urgent` pops up a message box at most this often


class Chat:
    def __init__(self, game: Game, ids: Handles) -> None:
        self.game, self.ids = game, ids
        self.heard: list[str] = []  # typed by the human, not yet handed to the agent
        self.answers: dict[int, str] = {}  # Yes/No clicks on ask questions, by question id
        self.hud: dict[str, Any] = {}  # doing, hp
        self._last_popup = 0.0

    def tr(self, text: str) -> str:
        return ZH.get(text, text) if self.game.language() == "zh" else text

    # ---- status line ----

    def note_tool(self, tool: str, result: Any) -> str | None:
        """Update the status line from a tool's name and result; returns the new line."""
        if tool in DOING:
            self.hud["doing"] = DOING[tool]
        st = result.get("status") if isinstance(result, dict) and isinstance(result.get("status"), dict) else result
        if isinstance(st, dict) and "hp" in st and "max_hp" in st:
            self.hud["hp"] = f"HP {st['hp']}/{st['max_hp']}"
            if st.get("my_turn"):
                self.hud["doing"] = "my turn"
        return self.status_line()

    def status_line(self) -> str | None:
        if not self.game.agent_name:
            return None
        doing = self.hud.get("doing")
        return " · ".join(x for x in (self.game.agent_name, self.hud.get("hp"), doing and self.tr(doing)) if x)

    # ---- what the human sends ----

    def _pointing(self, point: dict) -> str:
        """A middle-click mark from the human, as a line the agent can act on."""
        args = {"id": point["id"]} if point.get("id") else {"pos": point.get("pos")}
        try:
            p = self.game.call("pointed", args)
        except GameError:
            return "[pointing at] something you cannot place"
        where = f"{p['dist']} m {p['dir']} of you" if p.get("dist") is not None else "somewhere"
        if point.get("id"):
            return f"[pointing at] {p.get('name', '?')} ({self.ids.handle(point['id'])}, {p.get('rel')}, {where})"
        x, y, z = point["pos"]
        return f"[pointing at] the ground at x={x} y={y} z={z} ({where})"

    def listen(self, status: str | None = None) -> bool:
        """Collect what the human sent; True when there are lines for the agent. `status` refreshes
        the status line."""
        try:
            texts, answers = self.game.chat_take(status)
            self.heard.extend(t if isinstance(t, str) else self._pointing(t["point"]) for t in texts)
            self.answers.update(answers)
        except GameError:
            pass
        return bool(self.heard)

    def take_heard(self) -> list[str]:
        out, self.heard = self.heard, []
        return out

    # ---- questions ----

    def ask(self, question: str, seconds: float) -> dict:
        """Post a Yes/No question and wait up to `seconds` for a click or a typed reply."""
        ask_id = self.game.chat_ask(question)
        before = self.hud.get("doing")
        self.hud["doing"] = "asking you"
        try:
            return self._wait_answer(ask_id, time.monotonic() + seconds)
        finally:
            self.hud["doing"] = before

    def _wait_answer(self, ask_id: int, deadline: float) -> dict:
        while True:
            self.listen(self.status_line())
            if ask_id in self.answers:
                answer = self.answers.pop(ask_id)
                self.game.chat_ask_close(ask_id, self.tr("> " + answer.capitalize()))
                return {"answer": answer}
            if self.heard:
                reply = self.heard.pop(0)
                self.game.chat_ask_close(ask_id, "")
                return {"reply": reply}
            if time.monotonic() >= deadline:
                self.game.chat_ask_close(ask_id, self.tr("(no answer in time)"), kind="note")
                return {"timed_out": True, "hint": "they may be busy; carry on and ask again later if it matters"}
            time.sleep(0.5)

    def popup_allowed(self) -> bool:
        """Whether an urgent pop-up may be shown now; counts it when it may."""
        if time.monotonic() - self._last_popup < POPUP_EVERY_S:
            return False
        self._last_popup = time.monotonic()
        return True
