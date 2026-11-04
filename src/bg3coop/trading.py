"""The `trade` tool: ask the human, open the game's own trade window for the agent's character (on the
human's screen, or hidden), buy and sell through it, close it. server.lua opens the window; client.lua
reads and works it."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from .chat import Chat
from .game import Game, GameError
from .handles import Handles, bare
from .views import gold, trade_lines

TRADE_MINUTES = 10  # one yes from the human covers trading with that merchant this long
ASK_S = 90  # how long each of the two questions waits for the human

TEXT = {
    "en": {
        "may": "I'd like to trade with {name}: {why}. OK?",
        "together": "Shall we trade together? Yes = the trade window opens on your screen, you can watch and "
                    "trade too. No = I trade on my own in the background.",
        "done": "Traded with {name}: {what}.",
        "bought": "bought {x}", "sold": "sold {x}",
    },
    "zh": {
        "may": "我想和{name}交易：{why}。可以吗？",
        "together": "一起交易吗？「是」＝交易窗口在你屏幕上打开，你可以看着我买卖，也可以自己动手；"
                    "「否」＝我在后台自己交易，你的屏幕照常。",
        "done": "和{name}交易完了：{what}。",
        "bought": "买了 {x}", "sold": "卖了 {x}",
    },
}


class Trader:
    def __init__(self, game: Game, ids: Handles, chat: Chat, run_job: Callable[[dict, float], dict]) -> None:
        self.game, self.ids, self.chat, self.run_job = game, ids, chat, run_job
        self.session: dict[str, Any] = {}  # npc, name, together, until

    def _text(self, key: str, **kw: Any) -> str:
        return TEXT[self.game.language()][key].format(**kw)

    def _pick(self, ref: str) -> tuple[str, int | None]:
        """'e12' -> one, 'e12:3' -> three, 'e12:all' -> the whole stack (None)."""
        ref, _, n = ref.strip().partition(":")
        n = n.strip().lower()
        if n in ("", "1"):
            return self.ids.resolve(ref), 1
        if n == "all":
            return self.ids.resolve(ref), None
        if not n.isdigit() or int(n) < 1:
            raise GameError(f"bad count in {ref}:{n}: use e12, e12:3 or e12:all")
        return self.ids.resolve(ref), int(n)

    def _view(self, me: str, yours: bool = False) -> dict:
        return self.game.call("trade_view", {"me": me, "yours": yours}, context="client")

    def _one(self, me: str, guid: str, count: int | None, side: str) -> str:
        """Buy or sell through the window and wait until the gold moves."""
        want = bare(guid).lower()
        row, before = None, {}
        deadline = time.monotonic() + 3  # a window that just opened fills in our side a moment later
        while row is None:
            before = self._view(me, yours=side == "sell")
            pool = before.get("yours" if side == "sell" else "goods") or []
            row = next((r for r in pool if want in str(r.get("id", "")).lower()), None)
            if row is not None or time.monotonic() > deadline:
                break
            time.sleep(0.3)
        if row is None:
            return f"{self.ids.handle(guid)}: " + ("not in your bag (worn items cannot be sold)" if side == "sell"
                                                   else "the merchant does not have it")
        stack = row.get("count") or 1
        n = stack if count is None else min(count, stack)
        if side == "buy" and row.get("price") is not None:
            cost = row["price"] * n / stack
            if cost > (before.get("party_gold") or 0):
                return f"{row.get('name')}: not enough gold (needs about {cost:.0f})"
        self.game.call("trade_item", {"me": me, "id": guid, "count": n, "side": side}, context="client")
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            time.sleep(0.3)
            after = self._view(me, yours=side == "sell")
            if not after.get("open"):
                return f"{row.get('name')}: the trade window closed"
            if after.get("party_gold") != before.get("party_gold"):
                paid = round((after.get("party_gold") or 0) - (before.get("party_gold") or 0))
                what = f"{row.get('name')}{f' x{n}' if n > 1 else ''}"
                return f"{'bought' if side == 'buy' else 'sold'} {what} ({'paid' if paid < 0 else 'got'} {abs(paid)} gold)"
        return f"{row.get('name')}: the game did not complete it (the merchant may be short of gold)"

    def _close(self, me: str) -> bool:
        for _ in range(3):
            if self.game.call("trade_close", context="client").get("closed"):
                return True
            for _ in range(10):
                time.sleep(0.2)
                if not self._view(me).get("open"):
                    self.game.call("trade_close", context="client")  # clears the hiding
                    return True
        return False

    def _agree(self, npc: str, name: str, why: str) -> dict | None:
        """Ask the human the two questions; None when they agreed (the session is set), else the
        result for the agent."""
        if not why.strip():
            return {"error": "say in `why` what you want to buy or sell: the human is asked first"}
        ans = self.chat.ask(self._text("may", name=name, why=why.strip()[:200]), ASK_S)
        if ans.get("answer") != "yes":
            return {"declined": True, **{k: ans[k] for k in ("reply", "timed_out") if k in ans},
                    "note": "the human did not agree to this trade: do not trade with them now"}
        ans = self.chat.ask(self._text("together"), ASK_S)
        if "answer" not in ans:
            return {"not_started": True, **{k: ans[k] for k in ("reply", "timed_out") if k in ans},
                    "note": "they did not say whether to trade together; ask again with trade, or answer their reply"}
        self.session.clear()
        self.session.update(npc=npc, name=name, together=ans["answer"] == "yes")
        return None

    def _report(self, name: str, did: list[str]) -> None:
        """Tell the human in the panel what was bought and sold in the background."""
        ok = [d for d in did if d.startswith(("bought ", "sold "))]
        if not ok:
            return
        words = {"bought": self._text("bought", x="").strip(), "sold": self._text("sold", x="").strip()}
        what = "; ".join(words[d.split(" ", 1)[0]] + " " + d.split(" ", 1)[1].split(" (")[0] for d in ok)
        self.game.chat_post(self._text("done", name=name, what=what))

    def trade(self, merchant: str, why: str = "", buy: list[str] | None = None, sell: list[str] | None = None,
              show_yours: bool = False, done: bool = False) -> Any:
        me = self.game.call("status").get("id") or ""
        npc = self.ids.resolve(merchant)
        if done:
            closed = self._close(me) if self._view(me).get("mine") else True
            self.session.clear()
            return {"closed": closed}
        buys = [self._pick(b) for b in buy or []]
        sells = [self._pick(s) for s in sell or []]
        if sells:  # an item from inventory may sit in a stack the window lists under another id
            heads = self.game.call("trade_ids", {"ids": [g for g, _ in sells]})
            sells = [(h or g, n) for (g, n), h in zip(sells, heads)]
        view = self._view(me)
        if view.get("open") and not view.get("mine"):
            return {"error": "the human is trading right now: wait until they close their trade window"}
        info = self.game.call("trade_check", {"id": npc})
        now = time.monotonic()
        if not (self.session.get("npc") == npc and self.session.get("until", 0) > now):
            refused = self._agree(npc, info["name"], why)
            if refused:
                return refused
        self.session["until"] = now + TRADE_MINUTES * 60
        together = self.session["together"]
        opened_here = False
        try:
            if not view.get("mine"):
                self.game.call("trade_hide", {"on": not together}, context="client")
                r = self.run_job(self.game.call("trade_open", {"id": npc}), 30)
                if r.get("status") != "done":
                    return {"error": r.get("error") or "could not get to the merchant", "job": r}
                opened_here = True
                deadline = time.monotonic() + 6
                while not view.get("mine"):
                    if time.monotonic() > deadline:
                        return {"error": "the trade window did not open"}
                    time.sleep(0.3)
                    view = self._view(me)
            did = ([self._one(me, g, n, "sell") for g, n in sells]
                   + [self._one(me, g, n, "buy") for g, n in buys])
            view = self._view(me, yours=show_yours)
            out: dict = {"merchant": info["name"], "together": together, "your_gold": gold(view.get("party_gold")),
                         "merchant_gold": gold(view.get("trader_gold")),
                         "goods": trade_lines(self.ids.shorten(view.get("goods") or []))}
            if did:
                out["done"] = did
            if show_yours:
                out["yours"] = trade_lines(self.ids.shorten(view.get("yours") or []))
            if together:
                out["note"] = "the window is open on the human's screen; call trade with done=true when you are both finished"
            else:
                self._report(info["name"], did)
            return out
        finally:
            if not together and (opened_here or self._view(me).get("mine")):
                self._close(me)
