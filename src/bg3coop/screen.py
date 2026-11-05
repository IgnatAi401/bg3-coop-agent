"""Screenshots of the game for the agent: one small JPEG at the start of each of its combat turns.

The picture is the human's screen (the camera follows their character), taken in-process by wincap
(Windows API through ctypes: no extra process or window, so an exclusive-fullscreen game keeps the
focus). It only works in the player's desktop session, where the MCP server normally runs. With
BG3COOP_SSH_HOST (development) an ssh session has no desktop, so wincap.py runs under pythonw (no
window) as a one-off scheduled task in the logged-on user's session instead.
BG3COOP_SCREENSHOTS=0 turns it off (for an agent whose model cannot read images)."""

from __future__ import annotations

import base64
import concurrent.futures
import os
import subprocess
import sys
from importlib import resources

from . import wincap

MAX_WIDTH = 1280
QUALITY = 60
TIMEOUT_S = 40
NOTE = ("the game screen at the start of your turn: what the human sees (the camera follows their "
        "character); use it to read the battlefield, the numbers in `combat` stay authoritative")


class ShotError(Exception):
    """No picture this time; the message says why."""


def grab_local() -> bytes:
    try:
        return wincap.capture_bytes(MAX_WIDTH, QUALITY)
    except (wincap.CaptureError, OSError) as e:
        raise ShotError(str(e)) from e


def _parse(log: str) -> None:
    line = log.strip().splitlines()[0] if log.strip() else ""
    if line.startswith("ERR "):
        raise ShotError(line[4:].strip())
    if not line.startswith("OK"):
        raise ShotError("the screenshot did not run: " + (log.strip()[-200:] or "no output"))


# Development: run wincap.py in the desktop session through a scheduled task that is removed again.
_REMOTE = r"""
$ErrorActionPreference = 'Stop'
$d = Join-Path $env:TEMP 'bg3coop-shot'; New-Item -ItemType Directory -Force $d | Out-Null
Remove-Item "$d\shot.jpg", "$d\shot.log" -ErrorAction SilentlyContinue
[IO.File]::WriteAllBytes("$d\wincap.py", [Convert]::FromBase64String('__SCRIPT__'))
$py = Join-Path (Split-Path (Get-Command python).Source) 'pythonw.exe'
$a = New-ScheduledTaskAction -Execute $py -Argument "-I `"$d\wincap.py`" `"$d\shot.jpg`" `"$d\shot.log`" __W__ __Q__"
$pr = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive
Register-ScheduledTask -TaskName bg3coop_shot -Action $a -Principal $pr -Force | Out-Null
$t0 = Get-Date; Start-ScheduledTask -TaskName bg3coop_shot
while (-not (Test-Path "$d\shot.log") -and ((Get-Date) - $t0).TotalSeconds -lt 20) { Start-Sleep -Milliseconds 100 }
Start-Sleep -Milliseconds 100
Unregister-ScheduledTask -TaskName bg3coop_shot -Confirm:$false
Get-Content "$d\shot.log" -ErrorAction SilentlyContinue
if (Test-Path "$d\shot.jpg") { 'JPG ' + [Convert]::ToBase64String([IO.File]::ReadAllBytes("$d\shot.jpg")) }
Remove-Item $d -Recurse -Force -ErrorAction SilentlyContinue
"""


def grab_ssh(host: str) -> bytes:
    src = resources.files("bg3coop").joinpath("wincap.py").read_bytes()
    remote = (_REMOTE.replace("__SCRIPT__", base64.b64encode(src).decode())
              .replace("__W__", str(MAX_WIDTH)).replace("__Q__", str(QUALITY)))
    try:
        p = subprocess.run(["ssh", host, "pwsh -NoProfile -NonInteractive -Command -"], input=remote,
                           capture_output=True, text=True, timeout=TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ShotError(f"ssh screenshot failed: {e}") from e
    lines = (p.stdout + p.stderr).splitlines()
    _parse("\n".join(ln for ln in lines if not ln.startswith("JPG ")))
    data = next((ln[4:] for ln in lines if ln.startswith("JPG ")), "")
    if not data:
        raise ShotError("the screenshot wrote no picture")
    return base64.b64decode(data)


def enabled() -> bool:
    return os.environ.get("BG3COOP_SCREENSHOTS", "1").strip().lower() not in ("0", "off", "no", "false")


_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="bg3coop-shot")


class TurnShots:
    """At most one screenshot per combat turn of the agent."""

    def __init__(self, ssh_host: str | None) -> None:
        self.ssh_host = ssh_host
        self.taken = False  # for the current turn
        self._pending: concurrent.futures.Future | None = None  # a grab started early, by `start`

    def available(self) -> bool:
        return enabled() and (bool(self.ssh_host) or sys.platform == "win32")

    def grab(self) -> bytes:
        return grab_ssh(self.ssh_host) if self.ssh_host else grab_local()

    def turn_over(self) -> None:
        self.taken = False
        self._pending = None

    def start(self) -> None:
        """Begin this turn's picture now, on a thread, so it is taken while the rest of the turn's
        first result is put together (over ssh a picture takes seconds); `attach` waits for it."""
        if self.taken or self._pending or not self.available():
            return
        self._pending = _POOL.submit(self.grab)

    def attach(self, result: dict, key: str) -> dict:
        """Put this turn's picture under `key` (bytes; the tool wrapper turns it into an image),
        unless it was taken already. A failure is noted once and not retried this turn."""
        if self.taken or not self.available() or not isinstance(result, dict):
            return result
        self.taken = True
        pending, self._pending = self._pending, None
        try:
            result[key] = pending.result(timeout=TIMEOUT_S + 5) if pending else self.grab()
            result["screenshot"] = NOTE
        except (ShotError, concurrent.futures.TimeoutError) as e:
            result["screenshot"] = f"none this turn ({e or 'it took too long'})"
        return result
