"""MCP server: tools for an agent that plays ONE party member next to a human player.

Each tool is a thin layer over a game call. The parts with more to them live in their own modules:
handles (short ids), views (how results read), chat (the panel), trading, dialogue, notes, explore."""

from __future__ import annotations

import functools
import json
import time
from typing import Any

from mcp.server.mcpserver import Image, MCPServer
from mcp.types import CallToolResult, TextContent

from . import dialogue as dialogues, explore, update, views, wiki as bg3wiki
from .chat import Chat
from .game import Game, GameError
from .handles import Handles
from .notes import Notes, NotesError
from .persona import role_play
from .screen import TurnShots
from .trading import Trader

INSTRUCTIONS = """\
# You are playing Baldur's Gate 3 together with a human

You control one party member; the human controls their own main character in the same game. Your
character is unchained from the human's group and can explore on its own. Act through these tools
and talk to the human in the language they use with you.

## Starting
1. `party` to see the party. If the human said whom you play, `set_agent` that character; otherwise
   pick a companion who is not the main character and tell the human whom you picked. If the human
   says which character is theirs, pass it as `human`.
2. `say` a short hello: it brings up the chat panel in their game (F10 toggles it) and tells them you
   are connected. The panel lives only until the game restarts or a save loads; any tool call brings
   it back, so when the human says it is gone, call `status` and `say` hello again.
3. `notes` to recall who you are playing as, your goals and what happened (set_agent shows them
   too), and `quests` for the open quests in the journal. Then `status`, `look`, and start exploring.

## Keep playing
- `wait` is how you stay in the game. It is the only call that brings you events (your turn, combat
  starting, someone downed or dead, `human_says`, `noticed`, being controlled) while you are not
  acting, so call it again and again whenever you are not doing something else: between actions,
  while others take their turns, after `end_turn`, and while the human is busy. Never stop calling
  it to sit in the chat: if you do not `wait`, you miss your turn and the human's messages.
- Loop: `look` -> decide where to go and what to do -> act -> `wait` when needed. When there is
  nothing to do, `wait` too; do not end your turn in the chat just to wait for the human.
  A `look` shortly after the previous one lists only what changed; if you have lost track of what
  is around (for example after your context was summarised), call `look` with `full=true`.
- Explore on your own: interactable objects, people to talk to, and the places `look` lists under
  `explore.unexplored` (where ground nobody in the party has been to begins: `move` to the
  coordinates; the memory is kept in the save, so it follows save loads). Exits marked
  `unexplored beyond` lead somewhere new. `explore.quest_marker` and `quests` show where the
  journal's quest targets are: head that way when you have nothing closer to do. When you get far
  from the human (more than about 60 m), drift back towards them.
- Role-play: choose and speak the way your character would. For an origin companion `set_agent`
  gives a `role_play` sketch to start from; your persona notes take precedence over it.
- Remember with `notes`: when you set yourself a long-term goal, make a promise or a key decision, or
  find a place worth coming back to, add a goal/story/place note; when you settle how you role-play
  this character or learn what the human likes, add a persona/preference note. Keep them short and
  up to date (edit or delete stale ones): your context gets cut and restarted, the notes stay.

## Rules
- Use only what you can see. Do not guess at hidden things.
- Combat: act only when `status` shows `my_turn`. Start each turn with `combat` (turn order, enemy
  HP and concentration, your movement left, what happened since your last turn), then check
  `spells` (`usable: false` cannot be used now; pick one of the `variants` for spells with forms;
  `upcast` lists the slot levels you can cast at), then `cast` and `move`, and always finish with
  `end_turn`. When it is not your turn or `turn_ended` shows, `wait`. The first `wait` or `combat`
  of your turn also carries a screenshot of the human's screen: look at it for the lay of the
  battlefield (cover, high ground, hazards, who stands where). Spell slots are scarce: do not
  spend high-level slots on weak enemies. Pick damage and spells the enemy does not resist; `examine`
  a dangerous enemy for its traits. `wait` reports `downed` when a party member drops and
  `controlled` / `control_ended` when something takes over your character (asleep, held, charmed...).
- When `status` shows `turn_based` outside combat, the human has switched on turn-based mode: you
  move as far as your movement allows per turn, and `end_turn` starts a new one once everyone has
  ended theirs.
- Sneaking: `sneak` hides your character; `sight` shows who is around, which way they look, their
  view cones and spots nobody watches. While sneaking, check `sight`, walk with `move(..., sneak=true)`
  from one unwatched spot to the next, and wait for people to turn away when the way is watched. When
  `wait` reports `stealth_lost`, stop and decide (talk your way out, walk away, or tell the human). Sneak
  to scout, to get the jump on enemies, when the human asks, or to steal once the human has agreed
  to it; sneaking into places where you may not be needs the human's OK too.
- `wait` reports `noticed` when your character spots something hidden (a buried chest, a trap, a
  secret switch): go and `look` at it, and warn the human about traps.
- Items: `inventory` shows your potions and scrolls (other kinds on request). Drink a healing potion
  with `use_item` when your HP is low, read scrolls with `use_item` like a spell, `throw` grenades,
  oil and other throwables (it can hit, so not near the human), and `give` the human what they ask
  for. Ask before giving away or using rare items.
- Good to know: a party member at 0 HP is downed, not dead, and can be helped up with `cast`
  Target_Help next to them; a revive scroll read with `use_item` brings back the downed or dead; in
  camp, Withers ("守墓人" in the Chinese version) revives the dead for 200 gold through `talk`.
  Whether and when to use any of this is your call.
- Out of combat you can change your prepared spells with `prepare` (as the spellbook does), e.g.
  before a known fight or after a long rest; tell the human what you swapped and why.
- Trading: `trade` with a merchant (`trader` in look) to buy what you need (potions, scrolls,
  ammunition) or sell your own loot. The gold is the whole party's. `trade` itself asks the human
  whether you may trade and whether to trade together or leave it to you; pass a short `why`. If they
  say no, drop it. Browse first (`trade` without buy/sell), then buy or sell. Sell only junk or things
  the human agreed to; never sell quest items or anything rare without asking. Tell them what you got.
- Some things only the human can do from their screen: levelling up (when `wait` reports
  `level_up`, ask them to level your character), short and long rests.
  Ask with `say` when you need one; for a rest, say why (low HP, no spell slots).
- `wiki` looks things up on bg3.wiki. Use it freely for mechanics: what a spell, item, condition or
  enemy does, its resistances, how a rule works. Do not read it for quest solutions, puzzle answers,
  hidden places or what happens next in the story: that spoils the game for the human. Look those up
  only when the human asks you to or agrees (`ask`). When it cannot reach the wiki, play on without.
- Reactions are handled automatically. Change them with `reactions` only when needed.
- Dialogue: after `talk`, read it with `dialogue`; some NPCs say one line and stop (`open: false`).
  `said` in `dialogue` holds the lines spoken since your last read, also once the conversation is
  over: read them, they are what you missed. When `dialogue` says `yours: false` it is the human's
  conversation: never answer it. Answer your own with `choose`, and always pass `why`: a short reason
  in the human's language. The chat panel shows your answer and reason so the human can follow. Answers tagged like [PERSUASION] or [调查] are skill checks: after choosing
  one, `dialogue` shows a `roll`; throw the dice with `roll`. Before a key story choice (one that could make a companion leave, strongly
  affects the human's character, steals, or attacks a neutral) ask the human with `ask`.
- Never steal on your own initiative: taking items `look` or `container` mark `owned by` someone is
  stealing. Only when the human has agreed to it (ask with `ask`, or they told you to) may you steal,
  and then always `sneak` first, out of everyone's view (`sight`), and `take` with `steal=true`.
  You cannot pickpocket people (the game runs it only from the human's screen): leave that to the
  human. Do not attack non-hostile characters unless the human agrees. Getting caught starts a
  conversation: answer it with `choose`.
- The human writes to you in a chat panel in the game; their messages arrive as `human_says` in any
  tool result. Read them first and answer with `say` when they ask or tell you something. Keep `say`
  short: report finds, ask for help, discuss key choices. Use `urgent` only when it cannot wait.
  When they middle-click something, a `[pointing at] ...` line arrives with its id (or a
  ground x/y/z for `move`): "this" and "there" in their next words mean that.
  The panel also has quick buttons, which arrive as `[button] ...` messages: Follow me (`regroup`
  or walk `to_human` and stay close), Stop (`stop` and stay), Wait for me (stay where you are until
  they come), Free roam (go back to exploring on your own).
- For a yes/no decision use `ask`: it waits for the human to click Yes/No or type a reply.
- Do not start a conversation while the human is in a dialogue or cutscene.
- When a tool returns `error`, read why and try something else instead of repeating the same call.
- Entity names in results carry short ids like e12; pass those ids to the action tools.
"""

mcp = MCPServer("bg3-coop", instructions=INSTRUCTIONS)
game = Game()
ids = Handles()
chat = Chat(game, ids)
memo = Notes(game.call)
seen = views.LookMemory()
shots = TurnShots(game.ssh_host)
SHOT = "_screenshot"  # result key for a JPEG that _safe hands over as an image
_updates = update.Background()  # started by main(), so tests never touch the network


def _call(op: str, args: dict | None = None, context: str = "server") -> Any:
    return ids.shorten(game.call(op, args, context))


def _run_job(start: dict, wait_s: float) -> dict:
    """Poll a game job until it ends or wait_s passes."""
    job_id = start["job"]
    deadline = time.monotonic() + max(0.5, min(wait_s, 45))
    while True:
        view = game.call("job", {"id": job_id})
        if view["status"] != "running":
            return ids.shorten(view)
        if time.monotonic() >= deadline:
            return {"id": job_id, "status": "running", "hint": "still going: call wait or job_status"}
        time.sleep(0.25)


trader = Trader(game, ids, chat, _run_job)


def _with(result: Any, key: str, value: Any) -> dict:
    if not isinstance(result, dict):
        result = {"result": result}
    result[key] = value
    return result


def _safe(fn):
    """Turn game refusals into plain text results instead of tool errors with stack traces, and hand
    over whatever the human typed in the chat panel meanwhile."""

    @functools.wraps(fn)
    def inner(*a, **kw):
        try:
            result = fn(*a, **kw)
        except GameError as e:
            result = {"error": str(e)}
        picture = result.pop(SHOT, None) if isinstance(result, dict) else None
        if chat.listen(chat.note_tool(fn.__name__, result)):
            result = _with(result, "human_says", chat.take_heard())
        news = _updates.take()
        if news:
            result = _with(result, "update", news + " Tell the human once, in their language.")
        return _with_picture(result, picture) if picture else result
    return inner


def _with_picture(result: Any, jpeg: bytes) -> CallToolResult:
    """The result as text plus an image. Built whole here: on some Pythons the tools get an output
    schema ({"result": ...}) that the plain conversion cannot fill with an image."""
    text = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    return CallToolResult(content=[TextContent(type="text", text=text),
                                   Image(data=jpeg, format="jpeg").to_image_content()],
                          structured_content={"result": result})


def _target(args: dict, target: str, x: float | None, y: float | None, z: float | None) -> dict:
    """Aim an action at `target` (an id) or else at x/y/z, if either is given."""
    if target:
        args["id"] = ids.resolve(target)
    elif x is not None and y is not None and z is not None:
        args["pos"] = [x, y, z]
    return args


# Event cursor. The epoch changes whenever the game's Lua state is fresh (save load),
# which restarts event numbering.
_events = {"epoch": None, "seq": 0}


def _mark_events_seen() -> None:
    got = game.call("events", {"since": 1 << 30, "epoch": _events["epoch"]})
    _events["epoch"], _events["seq"] = got.get("epoch"), got.get("latest", 0)


# ---------------------------------------------------------------- setup


@mcp.tool()
def rules() -> str:
    """How to play alongside the human. Read this first if your client did not already show you
    the bg3-coop server instructions ("You are playing Baldur's Gate 3 together with a human")."""
    return INSTRUCTIONS


@mcp.tool()
@_safe
def party() -> Any:
    """List party members; shows which one is the human's and which is yours. If you have not seen
    the play rules yet, call `rules` first."""
    return _call("party")


@mcp.tool()
@_safe
def set_agent(name: str, human: str = "") -> Any:
    """Take control of the party member whose name contains `name` (e.g. "Shadowheart") and unchain it.
    `human` names the human's own character; by default it is their custom main character."""
    args = {"name": name}
    if human:
        args["human"] = human
    r = game.call("set_agent", args)
    r.pop("human_id", None)
    seen.forget()
    hint = role_play(r.get("id", ""))
    if hint:
        r["role_play"] = hint
    _mark_events_seen()
    try:
        r["notes"] = memo.read()
    except GameError:
        pass
    return ids.shorten(r)


@mcp.tool()
@_safe
def regroup() -> Any:
    """Chain your character back to the human's group (they will follow each other again)."""
    return _call("regroup")


# ---------------------------------------------------------------- observe


@mcp.tool()
@_safe
def status() -> Any:
    """Your character: HP, position, statuses, resources, combat/dialogue state, where the human is."""
    return _call("status")


def _combat_rows() -> Any:
    return _call("combat")


@mcp.tool()
@_safe
def combat() -> Any:
    """In combat: the turn order (highest initiative first, `current` = whose turn it is) with each
    fighter's HP, statuses, concentration and distance, plus enemies' damage resistances, immunities,
    vulnerabilities and status immunities (`immune_to`); your movement (metres), actions, bonus actions
    and reactions left; and `since_your_last_turn`, what everyone did since your previous turn
    (`no_damage` = an attack that missed, a save that was passed, or an immunity). One line per
    fighter; `>>` marks whose turn it is. Once per turn of yours it comes with a screenshot of the game."""
    r = _combat_rows()
    if isinstance(r, dict) and r.get("order"):
        r["order"] = [views.fighter_line(f) for f in r["order"]]
    if isinstance(r, dict) and r.get("my_turn") and not r.get("turn_ended"):
        shots.attach(r, SHOT)
    elif isinstance(r, dict):
        shots.turn_over()
    return r


@mcp.tool()
@_safe
def examine(target: str) -> Any:
    """What the game's examine window shows about a character you can see: level, AC, ability scores,
    damage resistances / immunities / vulnerabilities, status immunities, statuses, concentration and
    passive traits with a short description."""
    return _call("examine", {"target": ids.resolve(target)})


def _look_rows(radius: float = 40) -> dict:
    r = _call("look", {"radius": radius})
    r["explore"] = explore.summary(r.pop("area", None), r.pop("frontiers", None))
    marker = explore.nearest_marker(_quest_markers(), r.get("me"))
    if marker:
        r["explore"]["quest_marker"] = explore.quest_marker_line(marker, r.get("me"))
    return r


def _quest_markers() -> list[dict]:
    """The quest targets the game marks on the map (read from the client's map), [] when unreadable."""
    try:
        got = game.call("quest_markers", context="client") or {}
    except GameError:
        return []
    return got.get("markers") or [] if isinstance(got, dict) else []


@mcp.tool()
@_safe
def look(radius: float = 40, full: bool = False) -> Any:
    """What your character can see within `radius` metres (max 40): characters and interactable objects
    as one line each (id, name, relation, HP, distance and compass direction; N = +Z). About 30 lines,
    the most important nearest first (people, then exits, containers and loot, then other things to
    use, clutter last; in a fight every enemy in it); three or more of the same small thing share one
    line (the nearest one's id), and `farther` sums up the rest by direction (look with a smaller
    `radius` to list those near you). Doors, ladders,
    stairs, portals and hatches also say when you cannot get to them (and why), where they lead (up or
    down) and when what lies beyond is unexplored. `explore` gives the map, the nearest waypoint, the
    nearest quest target on the map, and `unexplored`: up to 3 places you can walk to where ground no
    one in the party has been to begins, as coordinates to `move` to, with the walk and any door or
    climb on the way. To save
    tokens, a look soon after the previous one lists only what is new or changed (moved, hurt,
    died...) plus `gone`, and counts the rest as `unchanged`; the human is always listed. `full` lists everything again (use it when you no longer remember the last look)."""
    return seen.show(_look_rows(radius), game.agent_name, radius, full)


def _spell_rows(kind: str = "") -> Any:
    return _call("spells", {"kind": kind} if kind else {})


@mcp.tool()
@_safe
def spells(kind: str = "") -> Any:
    """Actions you can use today: attacks, cantrips, prepared spells, Dash, Jump..., one line each:
    the id to pass to `cast`, the name, then kind, cost, range in metres, the slot levels you can
    upcast to and, for spells that make you pick a form, the `variants` to cast instead. A line
    marked NOT NOW says why it cannot be used at the moment. `kind` filters: attack, heal, buff,
    control, summon, utility."""
    rows = _spell_rows(kind)
    if isinstance(rows, dict):
        return rows
    return [views.spell_line(r) for r in rows]


@mcp.tool()
@_safe
def prepare(add: list[str] | None = None, remove: list[str] | None = None) -> Any:
    """Change which spells you have prepared, as in the game's spellbook. With no arguments, lists per
    class how many are prepared and the game's limit, then the prepared and not prepared spells (ids
    and names). `add` and `remove` take spell ids from that list; a class cannot go over its limit, so
    remove as many as you add. Not in combat. Cantrips and always-prepared spells are not listed."""
    add, remove = list(add or []), list(remove or [])
    if not add and not remove:
        return _call("prepare")
    r = _call("prepare", {"add": add, "remove": remove})
    if not isinstance(r, dict) or "error" in r:
        return r
    # the game applies the request on its next frame
    state: Any = None
    for _ in range(10):
        time.sleep(0.2)
        state = _call("prepare")
        if not isinstance(state, dict) or "error" in state:
            return state
        prepared = {line.split(" ", 1)[0] for c in state["classes"] for line in c["prepared"]}
        if set(add) <= prepared and not (set(remove) & prepared):
            out: dict = {"done": True}
            if add:
                out["prepared"] = add
            if remove:
                out["unprepared"] = remove
            out["classes"] = [f"{c['class']} {c['prepared_count']}/{c['max']}" for c in state["classes"]]
            return out
    return {"error": "the game did not apply the change (see prepare)", "state": state}


@mcp.tool()
@_safe
def reactions(mode: str = "", reaction: str = "") -> Any:
    """Your reactions (Warding Flare, Attack of Opportunity...) and how each is handled: auto (always used,
    no prompt), never, or ask (the human gets the prompt). set_agent makes free reactions auto and ones that
    cost a spell slot never. To change: `mode` plus a `reaction` id or name part (empty = all)."""
    args: dict = {}
    if mode:
        args["mode"] = mode
        if reaction:
            args["reaction"] = reaction
    return _call("reactions", args)


@mcp.tool()
@_safe
def wait(seconds: float = 10) -> Any:
    """Let game time pass (up to 30 s) and report what happened: new events, messages from the human
    and a short status (`status` has position, resources and statuses). Returns early when something happens (your turn, combat, a dialogue, the human
    writes)."""
    deadline = time.monotonic() + max(1, min(seconds, 30))
    events: list = []
    while True:
        args = {"since": _events["seq"], "epoch": _events["epoch"]}
        if _events["epoch"] is None:  # first look in this bridge: skip the old backlog
            args["max_age_ms"] = 30_000
        got = game.call("events", args)
        _events["epoch"], _events["seq"] = got.get("epoch"), got.get("latest", _events["seq"])
        events += got.get("events", [])
        if events or chat.listen() or time.monotonic() >= deadline:
            break
        time.sleep(1.0)
    s = _call("status")
    events = ids.shorten([{"kind": e["kind"], **(e.get("data") or {})} for e in events])
    out = {"events": events, "status": views.brief(s)}
    kinds = {e["kind"] for e in events}
    if kinds & {"your_turn", "combat_ended"}:
        shots.turn_over()
    if "your_turn" in kinds and isinstance(s, dict) and s.get("my_turn"):
        shots.attach(out, SHOT)
    return out


@mcp.tool()
@_safe
def job_status(job: int, wait_s: float = 20) -> Any:
    """Keep waiting on a long action that came back as still running."""
    return _run_job({"job": job}, wait_s)


@mcp.tool()
@_safe
def notes(action: str = "read", text: str = "", kind: str = "", id: str = "") -> Any:
    """Your own notes, which outlast context resets, restarts and save loads. `read` (the default)
    lists them; `add` takes a `kind` and `text`; `edit` replaces the `text` of note `id`; `delete`
    removes note `id`. Kinds kept in the save, so loading an older save takes them back to that point
    (they reach the save file the next time the game saves): goal (long-term aims), story (promises,
    decisions, what happened), place (where things are). Kinds kept on this PC for this playthrough,
    whatever is loaded: persona (who you are and how you role-play), preference (what the human
    likes). One note is at most 300 characters."""
    try:
        if action in ("", "read"):
            return memo.read()
        return memo.change(action, text, kind, id)
    except NotesError as e:
        return {"error": str(e)}


@mcp.tool()
@_safe
def quests() -> Any:
    """The quest journal: the party's open quests with their title, the main quest a sub-quest belongs
    to (`part_of`) and the latest step the party reached, worded as the journal does (in the game's
    language). Steps the game marks in unusual ways may be missing, so `latest` can be behind.
    `markers` are the quest targets the game marks on this map, with distance and direction from you
    and coordinates to `move` to (they can be far, inside buildings or on another floor)."""
    r = game.call("quests")
    out = []
    for q in r.get("quests", []):
        row = {"title": views.journal_text(q["title"])}
        if q.get("parent"):
            row["part_of"] = views.journal_text(q["parent"])
        latest = views.journal_text(q.get("latest"))
        if latest:
            row["latest"] = latest
        out.append(row)
    res: dict[str, Any] = {"open": out} if out else {"open": [], "note": "no open quests in the journal"}
    markers = explore.marker_lines(_quest_markers(), r.get("me"))
    if markers:
        res["markers"] = markers
    return res


@mcp.tool()
@_safe
def wiki(query: str, offset: int = 0) -> Any:
    """Look something up on bg3.wiki, the community Baldur's Gate 3 wiki (English only): the page
    titled `query`, else the best search hit, as plain text cut into parts (`more` gives the next
    `offset`); `see_also` lists other matching pages. Search by English name ("Fireball", "Goblin
    Booyahg", "Owlbear") or by a game id such as a spell id from `spells` (Projectile_Fireball).
    Needs internet access on the game PC."""
    try:
        return bg3wiki.lookup(query, offset)
    except bg3wiki.WikiError as e:
        return {"error": str(e)}


# ---------------------------------------------------------------- act


@mcp.tool()
@_safe
def move(target: str = "", direction: str = "", meters: float = 8, to_human: bool = False,
         x: float | None = None, y: float | None = None, z: float | None = None,
         sneak: bool = False, even_if_seen: bool = False) -> Any:
    """Walk. Give exactly one of: `target` (an id from look), `direction` (N NE E SE S SW W NW) with
    `meters` (max 30: you go as far that way as you can walk, not round through a door), `to_human`
    (go to the human's character), or x/y/z. Waits up to ~30 s. The way is planned first: when there
    is none it fails at once saying why (a locked door: `blocked_by`; a jump or a climb) and gives
    `nearest`, the closest spot you can walk to (`use` and `talk` do the same).
    `sneak` (while sneaking): the way is checked first and refused if it crosses someone's view
    (`seen_at`, `would_see_you`; `even_if_seen` walks anyway), and the walk stops just short of a view
    it is about to enter (people turn and walk about)."""
    args: dict = {"meters": meters}
    if sneak:
        args["sneak"] = True
    if even_if_seen:
        args["even_if_seen"] = True
    if target:
        args["id"] = ids.resolve(target)
    elif direction:
        args["dir"] = direction
    elif to_human:
        args["to_human"] = True
    elif x is not None and y is not None and z is not None:
        args["pos"] = [x, y, z]
    else:
        return {"error": "give target, direction, to_human or x/y/z"}
    return _run_job(game.call("move", args), 30)


@mcp.tool()
@_safe
def use(target: str) -> Any:
    """Walk to an object and use it: open a door or chest, pull a lever, climb a ladder, read a book.
    The result's `effect` says what visibly happened (opened, picked up, no visible change...), also
    when it took you somewhere else (`moved_m`), started a conversation (`dialogue`: it is yours, read
    it) or a fight (`combat`), or made something new to use appear nearby (`appeared`)."""
    return _run_job(game.call("use", {"id": ids.resolve(target)}), 30)


@mcp.tool()
@_safe
def container(target: str) -> Any:
    """List what is inside a container or corpse you are standing next to."""
    r = _call("container", {"id": ids.resolve(target)})
    if isinstance(r, dict) and "error" not in r:
        r.setdefault("items", [])
    return r


@mcp.tool()
@_safe
def take(items: list[str], steal: bool = False) -> Any:
    """Pick up items (ids from container or look) you are standing next to, as a click does. Taking an
    item marked `owned by` someone (or from a container that is) is theft and is refused unless you pass
    `steal`, which you may do only after the human agreed to this theft, and only while sneaking. If
    someone sees it the game treats it as a crime (the owner or a guard may confront you in a
    conversation)."""
    args: dict = {"ids": [ids.resolve(i) for i in items]}
    if steal:
        args["steal"] = True
    return _run_job(game.call("take", args), 8)


def _inventory_rows(kind: str = "") -> Any:
    r = _call("inventory", {"kind": kind} if kind else {})
    if isinstance(r, dict) and "error" not in r:
        r.setdefault("items", [])
    return r


@mcp.tool()
@_safe
def inventory(kind: str = "") -> Any:
    """Your bag and what you wear. By default lists only potions, scrolls and throwables, with a count of
    the rest under `not_shown`; `kind` picks one group (weapon, gear, potion, scroll, throwable, other) or
    all. One line per item: id, name, `xN` for a stack, kind (`heals` marks healing potions) and
    the slot it is worn in; `equipped` lists what you wear by slot."""
    r = _inventory_rows(kind)
    if isinstance(r, dict) and "error" not in r:
        r["items"] = [views.bag_line(i) for i in r["items"]]
        if r.get("equipped"):
            r["equipped"] = [f"{e.get('slot', '?')}: {e['id']} {e.get('name', '?')}" for e in r["equipped"]]
    return r


@mcp.tool()
@_safe
def use_item(item: str, target: str = "", x: float | None = None, y: float | None = None,
             z: float | None = None, even_if_allies: bool = False) -> Any:
    """Drink a potion or read a scroll from your bag (ids from inventory). A potion is always drunk by you.
    A scroll casts its spell on `target`, at x/y/z, or on yourself, and is used up. A revive scroll
    (Revivify and the like) takes the dead or downed party member as `target`; x/y/z, if given, is where
    they get up (within 9 m of you). Costs the action or bonus action it needs; in combat only on your
    turn. A harmful area scroll is refused while party members stand in the area, as for cast."""
    args: dict = {"item": ids.resolve(item)}
    if even_if_allies:
        args["even_if_allies"] = True
    if target:
        args["id"] = ids.resolve(target)
    if x is not None and y is not None and z is not None:
        args["pos"] = [x, y, z]  # with a target only a revive scroll uses it
    return _run_job(game.call("use_item", args), 25)


@mcp.tool()
@_safe
def throw(item: str, target: str = "", x: float | None = None, y: float | None = None,
          z: float | None = None, even_if_allies: bool = False) -> Any:
    """Throw something at `target` or at x/y/z, like the game's Throw action: an item from your bag
    (grenades, oil, a weapon), an object or body you can see, or a character. The game decides whether
    you can lift it, rolls to hit and applies its effects; thrown items land where they hit. Costs an
    action; in combat only on your turn. A grenade whose blast would reach party members is refused
    unless `even_if_allies`."""
    args: dict = {"item": ids.resolve(item)}
    if even_if_allies:
        args["even_if_allies"] = True
    return _run_job(game.call("throw", _target(args, target, x, y, z)), 25)


@mcp.tool()
@_safe
def equip(item: str, remove: bool = False) -> Any:
    """Wear or wield an item from your bag (it replaces what is in that slot), or take it off with
    `remove`. Not in combat."""
    args: dict = {"item": ids.resolve(item)}
    if remove:
        args["remove"] = True
    return _run_job(game.call("equip", args), 5)


@mcp.tool()
@_safe
def give(items: list[str], to: str = "", count: int = 0) -> Any:
    """Hand items from your bag to another party member: the human's character by default, or the one
    whose name contains `to`. `count` gives only part of a stack. Works at any distance, not in combat.
    Take off worn items with equip first."""
    args: dict = {"items": [ids.resolve(i) for i in items]}
    if to:
        args["to"] = to
    if count > 0:
        args["count"] = count
    return _call("give", args)


@mcp.tool()
@_safe
def talk(target: str) -> Any:
    """Walk up to a character and start a conversation. Then use dialogue/choose."""
    return _run_job(game.call("talk", {"id": ids.resolve(target)}), 30)


@mcp.tool()
@_safe
def trade(merchant: str, why: str = "", buy: list[str] | None = None, sell: list[str] | None = None,
          show_yours: bool = False, done: bool = False) -> Any:
    """Trade with a merchant (`trader` in look) through the game's own trade window, at the game's
    prices; the gold is the party's. The first call for a merchant asks the human two things in the chat
    panel: may you trade (say `why`: what you want to buy or sell), and do they want to trade together
    (the window opens on their screen and stays open, they can join in) or leave it to you (you trade
    in the background, the window opens and closes hidden). Their answer covers this merchant for 10
    minutes. You walk up to the merchant first.
    Returns the merchant's goods (`goods`: id, name, count, price for the whole stack) and gold; with
    `show_yours`, what you can sell from your own bag (worn items not). `buy` and `sell` take ids from
    those lists or from inventory: `e12` for one, `e12:3` for three, `e12:all` for the whole stack.
    Selling happens first. In a trade together the window stays open: finish with `done=true` (closes it)
    when you are both done, or when the human closes it."""
    return trader.trade(merchant, why, buy, sell, show_yours, done)


@mcp.tool()
@_safe
def travel(to: str = "camp", waypoint: str = "") -> Any:
    """Teleport as the game's buttons do; only your character goes, the human travels on their own.
    `camp` goes to camp, or leaves it if you are there. `waypoint` without a name lists the waypoints
    you unlocked on this map (nearest first); with one of those names it fast-travels there.
    Not in combat or a conversation. `flee` is the combat flee button: on your turn, when no enemy is
    close (the game says how far to get), you leave the fight and land in camp (or at a waypoint);
    the rest of the party fights on."""
    args: dict = {"to": to}
    if waypoint:
        args["waypoint"] = waypoint
    r = game.call("travel", args)
    return _run_job(r, 10) if "job" in r else r


@mcp.tool()
@_safe
def cast(spell: str, target: str = "", x: float | None = None, y: float | None = None,
         z: float | None = None, level: int = 0, even_if_allies: bool = False) -> Any:
    """Use an action by its `spell` id from spells (e.g. Target_MainHandAttack): on `target`, at x/y/z,
    or on yourself when neither is given. `level` upcasts a spell with a higher slot. Spends the action,
    bonus action and spell slot it costs; in combat only on your turn. The game rolls attacks and saving
    throws as usual, so it can miss. Out of range, you walk up to the target first. A harmful area spell
    (fireball, cone, shout) is refused while party members stand in the area, naming them; aim elsewhere,
    or pass `even_if_allies` to cast it anyway."""
    args: dict = {"spell": spell}
    if even_if_allies:
        args["even_if_allies"] = True
    if level:
        args["level"] = level
    return _run_job(game.call("cast", _target(args, target, x, y, z)), 25)


@mcp.tool()
@_safe
def end_turn() -> Any:
    """End your combat turn. Party members next to you in initiative share the turn, so status keeps
    showing the turn as theirs (turn_ended, waiting_for_party) until they finish too."""
    r = _call("end_turn")
    if isinstance(r, dict) and r.get("ended"):
        shots.turn_over()
    return r


@mcp.tool()
@_safe
def sight(x: float | None = None, y: float | None = None, z: float | None = None) -> Any:
    """Who could spot you: each character you can see within 30 m, which way they face and their view
    (a cone `fov` degrees wide and `range` m long; walls block it). `seen_by` names who has you in view
    now, `safe_spots` are nearby places nobody watches (x/y/z for `move`). With x/y/z, whether anyone has
    that spot in view (`seen_there`; SEES YOU then means sees that spot). People turn and walk, so check
    again before you go."""
    r = _call("sight", _target({}, "", x, y, z))
    r["watchers"] = [views.watcher_line(w) for w in r.get("watchers", [])]
    if "safe_spots" in r:
        r["safe_spots"] = [views.spot_line(p) for p in r["safe_spots"]]
    return r


@mcp.tool()
@_safe
def sneak(on: bool = True, anyway: bool = False) -> Any:
    """Start sneaking (the Hide action) or stop (`on=false`). Refused while someone has you in view,
    as they would spot you at once (`anyway` tries regardless). In combat it costs an action (a bonus
    action with the bonus Hide). While sneaking, walk with `move(..., sneak=true)`; `wait` reports
    `stealth_lost` when you are spotted."""
    if not on:
        return _call("sneak", {"off": True})
    r = game.call("sneak", {"anyway": True} if anyway else {})
    return _run_job(r, 5) if "job" in r else r


@mcp.tool()
@_safe
def stop() -> Any:
    """Stop whatever your character is doing."""
    return _call("stop")


# ---------------------------------------------------------------- dialogue and chat


@mcp.tool()
@_safe
def dialogue() -> Any:
    """The conversation on screen: who speaks, the line, numbered answers, and whether it is yours.
    `said` lists the lines spoken since your last read (also after the conversation has ended)."""
    return ids.shorten(dialogues.view(game))


@mcp.tool()
@_safe
def roll(reroll_if_failed: bool = False, use_boosts: bool = False) -> Any:
    """Throw the dice for a skill check in YOUR conversation, when `dialogue` shows a `roll`. The
    human sees the dice on screen. `use_boosts` first adds the bonuses `dialogue` lists under
    `your_boosts` (Guidance: a cantrip, but it takes your concentration). With `reroll_if_failed` a
    failed roll is thrown once more for one of the party's inspiration points (few and shared: keep
    them for checks that matter). Returns the roll and whether it passed; then read `dialogue`."""
    return dialogues.roll(game, reroll_if_failed, use_boosts)


@mcp.tool()
@_safe
def choose(n: int, why: str = "", expect: str = "") -> Any:
    """Pick answer number `n` in YOUR character's conversation. `why`: one short sentence, in the
    human's language, on why you pick it; the chat panel shows the answer and the reason, so the
    human can follow. `expect` (a few words of its text) guards against the options having changed."""
    st = game.call("status")
    mine = st.get("dialog")
    if not mine:
        return {"error": "your character is not in a conversation; leave the human's dialogues to them"}
    if not mine.get("yours"):
        return {"error": "this conversation belongs to the human; leave it to them"}
    r = game.call("choose", {"n": n, "expect": expect, "instance": mine["instance"], "as": st.get("name")},
                  context="client")
    game.chat_post(dialogues.choice_line(game, r["chose"], why))
    return r


@mcp.tool()
@_safe
def say(text: str, urgent: bool = False) -> Any:
    """Write to the human in the chat panel in their game. Keep it short. `urgent` also pops up a message
    box that interrupts them: only for danger or a choice that cannot wait, at most once a minute."""
    text = text.strip()[:300]
    if not text:
        return {"error": "text required"}
    if urgent:
        if not chat.popup_allowed():
            return {"error": "the last pop-up was less than a minute ago; say it without urgent"}
        _call("say", {"text": text[:200]})
    game.chat_post(text)
    return {"shown": "panel and pop-up" if urgent else "panel"}


@mcp.tool()
@_safe
def ask(question: str, timeout: float = 60) -> Any:
    """Ask the human a yes/no question in the chat panel and wait for the answer (up to `timeout`
    seconds, max 120). They click Yes or No, or type a reply. Returns `answer` ("yes"/"no"), or
    `reply` with what they typed, or `timed_out`."""
    question = question.strip()[:300]
    if not question:
        return {"error": "question required"}
    return chat.ask(question, max(5, min(timeout, 120)))


def main() -> None:
    import argparse
    import signal
    import sys

    p = argparse.ArgumentParser(description="BG3 co-op MCP server")
    p.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    p.add_argument("--port", type=int, default=8771)
    a = p.parse_args()
    kwargs = {"host": "127.0.0.1", "port": a.port} if a.transport == "streamable-http" else {}
    # agents stop the server with SIGTERM: exit normally so the cleanup below runs
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    _updates.start()
    try:
        mcp.run(transport=a.transport, **kwargs)
    finally:
        game.close()


if __name__ == "__main__":
    main()
