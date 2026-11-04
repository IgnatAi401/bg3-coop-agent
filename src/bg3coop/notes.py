"""The agent's own notes. Story notes (goals, what happened, places) live in the save through the
memory mod, so loading an older save takes them back to that point. Notes about the agent itself
(persona, the human's preferences) stay on this PC, one file per playthrough, whatever is loaded."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

SAVE_KINDS = ("goal", "story", "place")
LOCAL_KINDS = ("persona", "preference")
MAX_TEXT = 300
MAX_SAVE = 40
MAX_LOCAL = 20


class NotesError(Exception):
    pass


def data_dir() -> Path:
    if os.environ.get("BG3COOP_DATA_DIR"):
        return Path(os.environ["BG3COOP_DATA_DIR"])
    if os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "bg3coop"
    return Path.home() / ".local" / "share" / "bg3coop"


def _as_list(v: Any) -> list[dict]:
    # an empty Lua table comes back as {}
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


class Notes:
    def __init__(self, call: Callable[..., Any]) -> None:
        self._call = call  # Game.call

    # ---- storage ----

    def _save_side(self) -> dict:
        got = self._call("notes_get")
        got["notes"] = _as_list(got.get("notes"))
        return got

    def _local_path(self, campaign: str | None) -> Path:
        name = re.sub(r"[^0-9A-Za-z_-]", "_", campaign or "unknown")
        return data_dir() / "notes" / f"{name}.json"

    def _local(self, campaign: str | None) -> list[dict]:
        try:
            return _as_list(json.loads(self._local_path(campaign).read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return []

    def _write_local(self, campaign: str | None, items: list[dict]) -> None:
        path = self._local_path(campaign)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)

    # ---- the tool ----

    def read(self) -> dict:
        side = self._save_side()
        out: dict = {}
        for n in self._local(side.get("campaign")) + side["notes"]:
            out.setdefault(n["kind"], []).append(f"{n['id']}: {n['text']}")
        if not out:
            out["empty"] = "no notes yet"
        if side.get("store") != "save":
            out["warning"] = ("goal/story/place notes last only until the next save load: the memory mod "
                              "(v2) is not installed")
        return out

    def change(self, action: str, text: str = "", kind: str = "", note_id: str = "") -> dict:
        side = self._save_side()
        campaign = side.get("campaign")
        local = self._local(campaign)
        text = " ".join(text.split())
        if action == "add":
            kind = kind.strip().lower()
            if kind not in SAVE_KINDS + LOCAL_KINDS:
                raise NotesError(f"kind must be one of {', '.join(SAVE_KINDS + LOCAL_KINDS)}")
            if not text:
                raise NotesError("text required")
            in_save = kind in SAVE_KINDS
            items, cap, prefix = (side["notes"], MAX_SAVE, "s") if in_save else (local, MAX_LOCAL, "p")
            if len(items) >= cap:
                raise NotesError(f"{cap} {'story' if in_save else 'persona/preference'} notes already: "
                                 "edit or delete old ones first")
            nums = [int(n["id"][1:]) for n in items if str(n.get("id", ""))[1:].isdigit()]
            new = {"id": f"{prefix}{max(nums, default=0) + 1}", "kind": kind, "text": text[:MAX_TEXT]}
            items.append(new)
            self._store(in_save, campaign, side["notes"], local)
            return {"added": new["id"], **({"cut_to": MAX_TEXT} if len(text) > MAX_TEXT else {})}
        if action in ("edit", "delete"):
            note_id = note_id.strip()
            for in_save, items in ((True, side["notes"]), (False, local)):
                for i, n in enumerate(items):
                    if n.get("id") == note_id:
                        if action == "delete":
                            items.pop(i)
                        elif not text:
                            raise NotesError("text required")
                        else:
                            n["text"] = text[:MAX_TEXT]
                        self._store(in_save, campaign, side["notes"], local)
                        return {"deleted" if action == "delete" else "edited": note_id}
            raise NotesError(f"no note {note_id!r}: see notes()")
        raise NotesError("action must be read, add, edit or delete")

    def _store(self, in_save: bool, campaign: str | None, save_items: list, local: list) -> None:
        if in_save:
            self._call("notes_put", {"notes": save_items})
        else:
            self._write_local(campaign, local)
