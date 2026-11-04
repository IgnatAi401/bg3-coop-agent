"""Is there a newer bg3coop release on GitHub? Standard library only; any failure means "don't know"."""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.request

from . import __version__

REPO = "IgnatAi401/bg3-coop-agent"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES = f"https://github.com/{REPO}/releases/latest"
INSTALL_DOC = f"https://github.com/{REPO}/blob/main/docs/install-for-agents.md"
OPT_OUT = "BG3COOP_NO_UPDATE_CHECK"


def _parse(v: str) -> tuple[int, ...] | None:
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", v.strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def is_newer(latest: str, current: str) -> bool:
    a, b = _parse(latest), _parse(current)
    return bool(a and b and a > b)


def latest_version(timeout: float = 3) -> str | None:
    """The newest release's version ("0.2.0"), or None when offline, rate-limited or opted out."""
    if os.environ.get(OPT_OUT):
        return None
    req = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": f"bg3coop/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            tag = json.load(r).get("tag_name", "")
    except Exception:  # network, HTTP, JSON: never let an update check break anything
        return None
    return tag.lstrip("v") if _parse(tag) else None


def notice(latest: str | None, current: str | None = None) -> str | None:
    """A short message for the human when `latest` is newer than the running version."""
    current = current or __version__
    if not latest or current == "0.0.0" or not is_newer(latest, current):
        return None  # 0.0.0: a source tree that was never installed
    return (f"bg3coop {latest} is out (this is {current}). To update: install the new plugin, or reinstall "
            f"the new wheel the same way you installed this one ({RELEASES}, steps in {INSTALL_DOC}); "
            "then close the game and run `bg3coop setup` once.")


class Background:
    """Check once in a thread; `take()` hands the notice out a single time."""

    def __init__(self) -> None:
        self._msg: str | None = None
        self._given = False
        self._lock = threading.Lock()

    def start(self) -> None:
        threading.Thread(target=self._check, name="bg3coop-update-check", daemon=True).start()

    def _check(self) -> None:
        msg = notice(latest_version())
        with self._lock:
            self._msg = msg

    def set(self, msg: str | None) -> None:
        with self._lock:
            self._msg, self._given = msg, False

    def take(self) -> str | None:
        with self._lock:
            if self._msg and not self._given:
                self._given = True
                return self._msg
        return None
