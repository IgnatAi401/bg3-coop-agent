"""Short handles: the agent sees e12 instead of 80-character GUIDs like S_Player_ShadowHeart_3ed74f06-..."""

from __future__ import annotations

import re
from typing import Any

from .game import GameError

GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def bare(ref: str) -> str:
    """The GUID at the end of an id, lower case ("S_Player_X_3ed7..." and "3ed7..." name the same
    thing); an id without one is returned as it is."""
    m = GUID.search(ref or "")
    return m.group(0).lower() if m else ref


class Handles:
    """e1, e2, ... for every id the game has shown the agent, for as long as the bridge runs."""

    def __init__(self) -> None:
        self._ids: dict[str, str] = {}  # handle -> id as the game gave it
        self._handles: dict[str, str] = {}  # bare GUID -> handle

    def handle(self, guid: str) -> str:
        key = bare(guid)
        h = self._handles.get(key)
        if h is None:
            h = f"e{len(self._handles) + 1}"
            self._handles[key], self._ids[h] = h, guid
        return h

    def resolve(self, ref: str) -> str:
        """The game id for a handle from a tool result (a full id passes through)."""
        ref = ref.strip()
        if ref in self._ids:
            return self._ids[ref]
        if GUID.search(ref):
            return ref
        raise GameError(f"unknown id {ref!r}: use an id from look, like e12")

    def shorten(self, obj: Any) -> Any:
        """A game reply with every `id` turned into a handle and empty values left out."""
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if v is None or v == [] or v == {}:
                    continue
                out[k] = self.handle(v) if k == "id" and isinstance(v, str) else self.shorten(v)
            return out
        if isinstance(obj, list):
            return [self.shorten(x) for x in obj]
        return obj
