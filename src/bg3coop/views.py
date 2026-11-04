"""How game replies are shown to the agent: one short line per character, item, spell or fighter, and
`look` results that leave out what has not changed. Pure formatting; no game calls."""

from __future__ import annotations

import re
import time
from typing import Any


def char_line(c: dict) -> str:
    parts = ["the human" if c.get("human") else "", c.get("rel", "")]
    if c.get("hp") is not None and c.get("max_hp"):
        parts.append(f"HP {c['hp']}/{c['max_hp']}")
    elif c.get("hp_pct") is not None:
        parts.append(f"{c['hp_pct']}% HP")
    parts += ["dead" if c.get("dead") else "", "in combat" if c.get("combat") else "",
              "can talk" if c.get("talk") else "", "trader" if c.get("trader") else "",
              f"{c['dist']} m {c['dir']}", "out of sight" if c.get("out_of_sight") else ""]
    return f"{c['id']} {c['name']} ({', '.join(p for p in parts if p)})"


def item_line(i: dict) -> str:
    """An object in the world (look)."""
    parts = [i.get("kind", ""), "locked" if i.get("locked") else "", "trap" if i.get("trap") else "",
             f"owned by {i['owner']}" if i.get("owner") else "", f"{i['dist']} m {i['dir']}",
             f"leads {i['leads']}" if i.get("leads") else "",
             "unexplored beyond" if i.get("new_beyond") else "",
             f"can't get there: {i['unreachable']}" if i.get("unreachable") else ""]
    return f"{i['id']} {i['name']} ({', '.join(p for p in parts if p)})"


def group_line(g: dict) -> str:
    """Several of the same small thing (look): the nearest one's id, how many, how far."""
    return f"{g['id']} {g['name']} x{g['count']} ({g['kind']}, {g['dist']}-{g['far']} m, nearest {g['dir']})"


def bag_line(i: dict) -> str:
    """An item in the agent's bag (inventory)."""
    count = f" x{i['count']}" if (i.get("count") or 1) > 1 else ""
    what = ", ".join(x for x in (i.get("kind"), "heals" if i.get("heals") else None, i.get("slot")) if x)
    return f"{i['id']} {i.get('name', '?')}{count} ({what})"


def fighter_line(f: dict) -> str:
    rel = "you" if f.get("rel") == "you" else ("the human" if f.get("human") else f.get("rel", "?"))
    parts = [rel]
    if f.get("hp") is not None and f.get("max_hp"):
        parts.append(f"HP {f['hp']}/{f['max_hp']}")
    elif f.get("hp_pct") is not None:
        parts.append(f"{f['hp_pct']}% HP")
    if f.get("downed"):
        parts.append("downed")
    if f.get("initiative") is not None:
        parts.append(f"init {f['initiative']}")
    if f.get("dist") is not None:
        parts.append(f"{f['dist']} m {f.get('dir', '')}".strip())
    if f.get("concentrating"):
        parts.append(f"concentrating on {f['concentrating']}")
    for key, label in (("statuses", ""), ("resist", "resists "), ("immune", "immune to "),
                       ("vulnerable", "vulnerable to "), ("immune_to", "cannot be ")):
        if f.get(key):
            parts.append(label + ", ".join(f[key]))
    return f"{'>> ' if f.get('current') else ''}{f.get('id', '?')} {f.get('name', '?')} ({'; '.join(parts)})"


def _levels(levels: list) -> str:
    if len(levels) > 2 and levels == list(range(levels[0], levels[-1] + 1)):
        return f"{levels[0]}-{levels[-1]}"
    return ",".join(map(str, levels))


def spell_line(r: dict) -> str:
    rng = r.get("range_m")
    parts = [r.get("kind") or "", r.get("cost") or "free", rng if rng == "self" else f"{rng} m"]
    if r.get("upcast"):
        parts.append("upcast " + _levels(r["upcast"]))
    if r.get("variants"):
        parts.append("variants " + ", ".join(r["variants"]))
    line = f"{r['spell']} {r.get('name', '')} ({'; '.join(p for p in parts if p)})"
    if not r.get("usable", True):
        line += f" NOT NOW: {r.get('why_not') or 'cannot be used now'}"
    return line


def watcher_line(w: dict) -> str:
    parts = [w.get("rel", ""), f"{w['dist']} m {w['dir']}",
             f"faces {w['faces']}" if w.get("faces") else "",
             f"sees {w['range_m']} m in a {w['fov']:g} deg cone",
             "SEES YOU" if w.get("sees") else "", "in their cone but behind cover" if w.get("cover") else ""]
    return f"{w['id']} {w['name']} ({', '.join(p for p in parts if p)})"


def spot_line(p: dict) -> str:
    x, y, z = p["pos"]
    return f"x={x} y={y} z={z} ({p['dist']} m {p['dir']})"


def gold(v: Any) -> Any:
    return round(v) if isinstance(v, (int, float)) else v


def trade_lines(rows: list[dict]) -> list[str]:
    out = []
    for r in rows:
        n, price = r.get("count") or 1, gold(r.get("price"))
        if price is None:
            cost = "price unknown"
        elif n > 1:
            cost = f"{price} gold for all, about {price / n:.4g} each"
        else:
            cost = f"{price} gold"
        out.append(f"{r['id']} {r.get('name', '?')}{f' x{n}' if n > 1 else ''} ({cost})")
    return out


_TAG = re.compile(r"<[^>]+>")


def journal_text(text: str | None, limit: int = 300) -> str | None:
    """Quest journal text without markup, at most `limit` characters."""
    if not text:
        return None
    text = " ".join(_TAG.sub(" ", text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# What `wait` repeats every time: enough to decide whether to act. `status` has the rest
# (position, resources, statuses, gold).
_BRIEF = ("hp", "max_hp", "sneaking", "combat", "turn_based", "my_turn", "turn_ended", "waiting_for_party",
          "dialog", "note", "human")


def brief(s: Any) -> Any:
    if not isinstance(s, dict) or "error" in s:
        return s
    return {k: s[k] for k in _BRIEF if k in s}


# ---------------------------------------------------------------- look, the rows that matter

LOOK_ROWS = 30  # about this many lines; the rest is summed up by direction
_TIER_M = 12.0  # metres: one step down in importance weighs like this much farther away
_GROUP_MIN = 3  # this many of the same small thing become one line
_EXITS = {"door", "ladder", "stairs", "portal", "hatch"}
_CLUTTER = ("candle", "torch", "hinge", "brazier", "candelabr", "sconce", "蜡烛", "火把", "铰链", "烛台", "火盆",
            "物体")


def _char_tier(c: dict) -> int:
    if c.get("human") or c.get("rel") in ("party", "enemy") or c.get("talk") or c.get("trader") or c.get("combat"):
        return 0
    return 1 if c.get("dead") else 2  # the dead can be searched; animals and passers-by last


def _item_tier(i: dict) -> int:
    name = str(i.get("name", "")).lower()
    if i.get("kind") == "object" or any(w in name for w in _CLUTTER):
        return 3
    if i.get("kind") in _EXITS or i.get("kind") in ("container", "item") or i.get("trap"):
        return 1
    return 2  # other things one can use


def _band(d: float) -> str:
    return next((f"{a}-{b} m" for a, b in ((0, 10), (10, 25), (25, 40)) if d < b), "40+ m")


def crowd(chars: list[dict], items: list[dict], limit: int = LOOK_ROWS) -> tuple[list, list, list, list[str]]:
    """Pick the rows worth a line: the ~`limit` most important by kind, nearest first; in a fight every
    enemy in it. Three or more of the same small thing become one group line. Returns
    (characters, items, groups, summary lines for the rest by direction)."""
    cands: list[tuple[float, str, dict]] = []
    for c in chars:
        cands.append((c["dist"] + _TIER_M * _char_tier(c), "c", c))
    same: dict[tuple, list[dict]] = {}
    for i in items:
        if _item_tier(i) >= 2:
            same.setdefault((i.get("name"), i.get("kind")), []).append(i)
    grouped = set()
    for (name, kind), rows in same.items():
        if len(rows) >= _GROUP_MIN:
            rows = sorted(rows, key=lambda r: r["dist"])
            near = rows[0]
            g = {"id": near["id"], "name": name, "kind": kind, "count": len(rows), "dist": near["dist"],
                 "far": rows[-1]["dist"], "dir": near["dir"], "members": rows}
            cands.append((near["dist"] + _TIER_M * _item_tier(near), "g", g))
            grouped.update(id(r) for r in rows)
    for i in items:
        if id(i) not in grouped:
            cands.append((i["dist"] + _TIER_M * _item_tier(i), "i", i))
    cands.sort(key=lambda t: t[0])
    picked: dict[str, list] = {"c": [], "i": [], "g": []}
    rest: list[tuple[str, dict]] = []
    for _, kind, row in cands:
        must = kind == "c" and (row.get("human") or (row.get("rel") == "enemy" and row.get("combat")))
        if must or len(picked["c"]) + len(picked["i"]) + len(picked["g"]) < limit:
            picked[kind].append(row)
        elif kind == "g":
            rest.extend(("i", m) for m in row["members"])
        else:
            rest.append((kind, row))
    for k in picked:
        picked[k].sort(key=lambda r: r["dist"])
    return picked["c"], picked["i"], [{k: v for k, v in g.items() if k != "members"} for g in picked["g"]], \
        _summary(rest)


def _summary(rest: list[tuple[str, dict]]) -> list[str]:
    by: dict[tuple[str, str], dict] = {}
    for kind, r in rest:
        b = by.setdefault((r["dir"], _band(r["dist"])), {"n": {}, "lo": r["dist"], "hi": r["dist"]})
        b["lo"], b["hi"] = min(b["lo"], r["dist"]), max(b["hi"], r["dist"])
        what = "people" if kind == "c" else (
            "exits" if r.get("kind") in _EXITS else "containers" if r.get("kind") == "container"
            else "items to pick up" if r.get("kind") == "item" else "other objects")
        b["n"][what] = b["n"].get(what, 0) + 1
    order = (("people", "person"), ("exits", "exit"), ("containers", "container"),
             ("items to pick up", "item to pick up"), ("other objects", "other object"))
    lines = []
    for (d, _), b in sorted(by.items(), key=lambda kv: kv[1]["lo"]):
        counts = ", ".join(f"{b['n'][w]} {w if b['n'][w] > 1 else one}" for w, one in order if w in b["n"])
        span = f"{b['lo']:g}" if b["lo"] == b["hi"] else f"{b['lo']:g}-{b['hi']:g}"
        lines.append(f"{d} {span} m: {counts}")
    return lines


# ---------------------------------------------------------------- look, only what changed


def _moved(old: dict, new: dict) -> bool:
    d = abs(new["dist"] - old["dist"])
    return d >= max(3.0, new["dist"] * 0.25) or (old["dir"] != new["dir"] and new["dist"] >= 6)


def _state(row: dict) -> tuple:
    return tuple(sorted((k, str(v)) for k, v in row.items() if k not in ("dist", "dir", "far")))


class LookMemory:
    """The previous look, so the next one can leave out what has not changed."""

    FRESH_S = 300  # after this long a look lists everything again

    def __init__(self) -> None:
        self.last: dict[str, Any] = {}

    def forget(self) -> None:
        self.last.clear()

    def show(self, r: dict, agent: str | None, radius: float, full: bool = False) -> dict:
        """`r` is the game's look reply with `explore` already summarised."""
        chars, items, groups, more = crowd(r.get("characters", []), r.get("items", []))
        rows = {"c:" + c["id"]: c for c in chars}
        rows.update({"i:" + i["id"]: i for i in items})
        rows.update({f"g:{g['name']}|{g['kind']}": g for g in groups})
        prev = self.last
        region = r["explore"].get("region")
        fresh = (not full and prev.get("agent") == agent and prev.get("radius") == radius
                 and time.monotonic() - prev.get("at", 0) < self.FRESH_S and prev.get("region") == region)
        old = prev.get("rows", {}) if fresh else {}
        self.last = dict(agent=agent, radius=radius, at=time.monotonic(), region=region, rows=rows,
                         explore=r["explore"], more=more)

        def keep(key: str, row: dict) -> bool:
            o = old.get(key)
            return o is None or row.get("human") or _state(o) != _state(row) or _moved(o, row)

        out: dict[str, Any] = {"me": r.get("me"), "sight_m": r.get("sight_m")}
        out["characters"] = [char_line(c) for c in chars if keep("c:" + c["id"], c)]
        out["items"] = [item_line(i) for i in items if keep("i:" + i["id"], i)]
        out["items"] += [group_line(g) for g in groups if keep(f"g:{g['name']}|{g['kind']}", g)]
        if more and not (fresh and prev.get("more") == more):
            out["farther"] = more
        if fresh:
            there = {"c:" + c["id"] for c in r.get("characters", [])} | {"i:" + i["id"] for i in r.get("items", [])}
            gone = [f"{o['id']} {o['name']}" for k, o in old.items()
                    if k not in rows and k not in there and not k.startswith("g:")]
            if gone:
                out["gone"] = gone[:10] + ([f"+{len(gone) - 10} more"] if len(gone) > 10 else [])
            same = len(rows) - len(out["characters"]) - len(out["items"])
            if same:
                out["unchanged"] = f"{same} more as in your last look (look full=true lists them)"
            if prev.get("explore") == r["explore"]:
                out["explore"] = "as in your last look"
                return out
        out["explore"] = r["explore"]
        return out
