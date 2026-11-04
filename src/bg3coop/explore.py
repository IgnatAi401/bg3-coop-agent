"""The `explore` part of look, from what the game side measured. Where the party has been is kept by
the BG3 Co-op Memory mod inside the save (see mod/), or by the injected script until the next load."""

from __future__ import annotations

import math

# The game's map codes (Osi.GetRegion), for the agent to read.
REGIONS = {
    "TUT_Avernus_C": "the nautiloid (prologue)",
    "WLD_Main_A": "the wilderness (act 1)",
    "CRE_Main_A": "Rosymorn Monastery and the Mountain Pass (act 1)",
    "SCL_Main_A": "the Shadow-Cursed Lands (act 2)",
    "BGO_Main_A": "Rivington and Wyrm's Crossing (act 3)",
    "CTY_Main_A": "the Lower City of Baldur's Gate (act 3)",
    "IRN_Main_A": "the Iron Throne (act 3)",
}


DIRS = ("E", "NE", "N", "NW", "W", "SW", "S", "SE")  # as the game side names them: N = +Z, E = +X


def direction(frm: list, to: list) -> str:
    a = math.atan2(to[2] - frm[2], to[0] - frm[0])
    return DIRS[round(a / (math.pi / 4)) % 8]


def frontier_line(f: dict) -> str:
    """A place to walk to where unexplored ground begins: `move` takes the coordinates as they are."""
    x, y, z = f["pos"]
    parts = [f"{f['dist']:g} m {f['dir']}", f"{f['walk_m']} m on foot"]
    if f.get("via"):
        parts.append("through " + ", ".join(d["name"] for d in f["via"]))
    if f.get("dy"):
        parts.append(f"{'up' if f['dy'] > 0 else 'down'} {abs(f['dy'])} m")
    return f"x={x} y={y} z={z} ({'; '.join(parts)})"


def summary(area: dict | None, frontiers: dict | None) -> dict:
    """The map, the nearest waypoint and the nearest places the agent can walk to where ground nobody
    in the party has been to begins."""
    area = area or {}
    out: dict = {}
    if area.get("region"):
        out["region"] = REGIONS.get(area["region"], area["region"])
    wp = area.get("waypoint")
    if wp:
        where = f"{wp['dist']} m {wp['dir']}" if wp.get("dist") is not None else "on this map"
        out["nearest_waypoint"] = f"{wp['name']} ({where}{', not unlocked' if wp.get('locked') else ''})"
    frontiers = frontiers or {}
    rows = frontiers.get("spots") or []  # an empty Lua table comes as {}
    more = frontiers.get("more")
    out["unexplored"] = [frontier_line(f) for f in rows]
    if not rows:
        out["hint"] = ("still checking the ways around here: look again" if more else
                       "the party has been everywhere you can walk to around here: take an exit, go farther, or travel")
    elif more:
        out["more"] = "not every way around here checked yet: the next look may add closer ones"
    if area.get("memory") == "session":
        out["memory"] = "only since the last save load (the memory mod is not installed)"
    return out


def quest_marker_line(m: dict, me: list | None) -> str:
    """A quest target on the map, with where it is from the agent."""
    x, y, z = (round(v, 1) for v in m["pos"])
    where = f"x={x} y={y} z={z}"
    if me:
        d = math.hypot(m["pos"][0] - me[0], m["pos"][2] - me[2])
        where = f"{round(d)} m {direction(me, m['pos'])}, {where}"
    quests = "; ".join(q["title"] + (f" (part of {q['part_of']})" if q.get("part_of") else "")
                       for q in m.get("quests", []))
    return f"{m.get('name', '?')} ({where})" + (f" for {quests}" if quests else "")


def nearest_marker(markers: list[dict], me: list | None) -> dict | None:
    if not markers or not me:
        return None
    return min(markers, key=lambda m: math.hypot(m["pos"][0] - me[0], m["pos"][2] - me[2]))


def marker_lines(markers: list[dict], me: list | None) -> list[str]:
    """All quest targets on the map, nearest first."""
    if me:
        markers = sorted(markers, key=lambda m: math.hypot(m["pos"][0] - me[0], m["pos"][2] - me[2]))
    return [quest_marker_line(m, me) for m in markers]
