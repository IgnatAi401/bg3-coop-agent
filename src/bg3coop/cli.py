"""bg3coop setup / doctor: one-time game setup and a health check, both meant for Windows players."""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import __version__, modpak, update
from .game import GAME_PORT, DebuggerBusy, Game, GameError, NotReady

BG3_APP_ID = "1086940"
SE_RELEASES = "https://github.com/Norbyte/bg3se/releases"
# What this version was last played with; other versions may work but are untested.
TESTED_SE_VERSION = 33
GAME_EXES = ("bg3.exe", "bg3_dx11.exe")


# ---------------------------------------------------------------- Steam library lookup


_VDF_TOKEN = re.compile(r'"((?:\\.|[^"\\])*)"|(\{)|(\})')


def parse_vdf(text: str) -> dict:
    """Steam's text KeyValues files (libraryfolders.vdf, appmanifest_*.acf) as nested dicts.

    Each entry is a quoted key followed by either a quoted value or a { ... } block of entries.
    Paths in values come with doubled backslashes; they are undoubled. Unbalanced braces are tolerated.
    """
    tokens = iter(_VDF_TOKEN.finditer(text))

    def block() -> dict:
        entries: dict = {}
        for m in tokens:
            if m.group(3):  # "}"
                break
            if m.group(2):  # a block with no key: keep it under ""
                entries[""] = block()
                continue
            key = m.group(1)
            nxt = next(tokens, None)
            if nxt is None:
                break
            if nxt.group(2):
                entries[key] = block()
            elif nxt.group(3):
                break
            else:
                entries[key] = nxt.group(1).replace("\\\\", "\\")
        return entries

    return block()


def steam_roots() -> list[Path]:
    roots: list[Path] = []
    if sys.platform == "win32":
        import winreg

        for hive, sub, name in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
        ):
            try:
                with winreg.OpenKey(hive, sub) as k:
                    roots.append(Path(winreg.QueryValueEx(k, name)[0]))
            except OSError:
                pass
        roots.append(Path(r"C:\Program Files (x86)\Steam"))
    else:
        roots += [Path.home() / ".steam/steam", Path.home() / ".local/share/Steam"]
    seen, out = set(), []
    for r in roots:
        key = str(r).lower().replace("/", "\\")
        if key not in seen and r.is_dir():
            seen.add(key)
            out.append(r)
    return out


def find_game_dir() -> Path | None:
    """The BG3 install folder, from Steam's libraryfolders.vdf and the game's appmanifest."""
    for root in steam_roots():
        vdf = root / "steamapps" / "libraryfolders.vdf"
        try:
            libs = parse_vdf(vdf.read_text(encoding="utf-8", errors="replace")).get("libraryfolders", {})
        except OSError:
            continue
        entries = [v for v in libs.values() if isinstance(v, dict) and "path" in v]
        # Libraries that list the app first, then the rest (the apps list can be stale).
        entries.sort(key=lambda v: BG3_APP_ID not in v.get("apps", {}))
        for lib in [*(Path(v["path"]) for v in entries), root]:
            manifest = lib / "steamapps" / f"appmanifest_{BG3_APP_ID}.acf"
            installdir = "Baldurs Gate 3"
            if manifest.is_file():
                state = parse_vdf(manifest.read_text(encoding="utf-8", errors="replace")).get("AppState", {})
                installdir = state.get("installdir", installdir)
            game = lib / "steamapps" / "common" / installdir
            if (game / "bin").is_dir():
                return game
    return None


# ---------------------------------------------------------------- setup


def settings_path(game_dir: Path) -> Path:
    return game_dir / "bin" / "ScriptExtenderSettings.json"


def read_settings(path: Path) -> dict:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8-sig")
    return json.loads(text) if text.strip() else {}


def merged_settings(current: dict, port: int) -> dict:
    """Turn the debugger on, keep every other setting the player has."""
    out = dict(current)
    out["EnableLuaDebugger"] = True
    out["LuaDebuggerPort"] = port
    out.setdefault("CreateConsole", False)
    return out


def cmd_setup(a: argparse.Namespace) -> int:
    game_dir = Path(a.game_dir) if a.game_dir else find_game_dir()
    if not game_dir or not (game_dir / "bin").is_dir():
        print("Could not find Baldur's Gate 3. Pass the install folder, e.g.\n"
              '  bg3coop setup --game-dir "D:\\SteamLibrary\\steamapps\\common\\Baldurs Gate 3"')
        return 1
    print(f"Game folder: {game_dir}")
    path = settings_path(game_dir)
    try:
        current = read_settings(path)
    except (ValueError, OSError) as e:
        print(f"Cannot read {path}: {e}\nFix or delete that file and run setup again.")
        return 1
    want = merged_settings(current, a.port)
    if want == current:
        print(f"OK    {path.name} already enables the Lua debugger on port {a.port}")
    elif a.dry_run:
        print(f"Would write {path}:\n{json.dumps(want, indent=2)}")
    else:
        path.write_text(json.dumps(want, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {path}")
        if _game_running():
            print("      Restart the game for this to take effect.")
    ok = True
    dll = game_dir / "bin" / "DWrite.dll"
    if dll.is_file():
        print(f"OK    Script Extender loader found: {dll}")
    else:
        ok = False
        print(f"TODO  Script Extender is not installed. Download it from {SE_RELEASES}\n"
              f"      and put DWrite.dll into {dll.parent}")
    if a.no_mod:
        print(f"SKIP  the {modpak.MOD_NAME} mod (--no-mod): every save load will wipe where the party has been "
              "and the agent's goal/story notes")
        base = modpak.larian_dir()
        if base and (base / "Mods" / modpak.PAK_NAME).is_file():
            print(f"      it is still installed from an earlier setup: {base / 'Mods' / modpak.PAK_NAME}")
    else:
        ok = install_mod(a.dry_run) and ok
    if ok:
        print("\nNext: start the game, load a save, then run `bg3coop doctor`.")
    return 0 if ok else 1


def install_mod(dry_run: bool, base: Path | None = None) -> bool:
    """Put the BG3 Co-op Memory mod into the game's Mods folder and turn it on in modsettings.lsx.
    The game rewrites modsettings.lsx when it quits, so this only runs while the game is closed."""
    base = base or modpak.larian_dir()
    if not base or not base.is_dir():
        print("TODO  could not find the game's user folder (%LOCALAPPDATA%\\Larian Studios\\Baldur's Gate 3);\n"
              "      start the game once, then run setup again")
        return False
    pak = base / "Mods" / modpak.PAK_NAME
    settings = base / "PlayerProfiles" / "Public" / "modsettings.lsx"
    want = modpak.build_pak(modpak.mod_files())
    try:
        text = settings.read_text(encoding="utf-8-sig")
        enabled = modpak.enable_in_modsettings(text)
    except (OSError, ValueError) as e:
        print(f"TODO  cannot read {settings}: {e}\n      start the game once, quit it, then run setup again")
        return False
    same_pak = pak.is_file() and pak.read_bytes() == want
    if same_pak and enabled is None:
        print(f"OK    the {modpak.MOD_NAME} mod is installed and turned on")
        return True
    if dry_run:
        if not same_pak:
            print(f"Would write {pak}")
        if enabled is not None:
            print(f"Would add {modpak.MOD_NAME} to {settings}")
        return True
    if _game_running():
        print(f"TODO  quit the game, then run setup again to install the {modpak.MOD_NAME} mod\n"
              "      (the game rewrites its mod list when it quits)")
        return False
    if not same_pak:
        pak.parent.mkdir(parents=True, exist_ok=True)
        pak.write_bytes(want)
        print(f"Wrote {pak}")
    if enabled is not None:
        backup = settings.with_name(settings.name + ".bg3coop-backup")
        if not backup.exists():
            backup.write_text(text, encoding="utf-8")
        settings.write_text(enabled, encoding="utf-8")
        print(f"Turned the mod on in {settings} (backup: {backup.name})")
    return True


# ---------------------------------------------------------------- doctor


@dataclass
class Report:
    failed: bool = False
    todo: str | None = None  # nothing failed, but what is left to do or check

    def add(self, level: str, text: str) -> None:
        if level == "FAIL":
            self.failed = True
        print(f"{level:<5} {text}", flush=True)


def _run(cmd: list[str], ssh_host: str | None) -> str | None:
    if ssh_host:
        cmd = ["ssh", ssh_host, " ".join(cmd)]
    elif sys.platform != "win32":
        return None
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20,
                              encoding="utf-8", errors="replace").stdout
    except (OSError, subprocess.TimeoutExpired):
        return None


def _game_running(ssh_host: str | None = None) -> bool | None:
    out = _run(["tasklist", "/fo", "csv", "/nh"], ssh_host)
    if out is None:
        return None
    names = {row[0].lower() for row in csv.reader(io.StringIO(out)) if row}
    return any(exe in names for exe in GAME_EXES)


def listen_addresses(netstat: str, port: int) -> list[str]:
    """Local addresses with a TCP listener on `port`, from `netstat -an` output."""
    out = []
    for line in netstat.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0].upper() == "TCP" and "LISTEN" in parts[3].upper():
            host, _, p = parts[1].rpartition(":")
            if p == str(port):
                out.append(host)
    return out


def connected_clients(netstat: str, port: int) -> int:
    """How many TCP connections a program holds open to the listener on `port`, from `netstat -an`."""
    n = 0
    for line in netstat.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0].upper() == "TCP" and parts[3].upper() == "ESTABLISHED":
            if parts[1].rpartition(":")[2] == str(port):
                n += 1
    return n


def cmd_doctor(a: argparse.Namespace) -> int:
    r = Report()
    game = Game()
    ssh = game.ssh_host
    remote_port = GAME_PORT if ssh else game.port
    print(f"bg3coop {__version__}, game at {game.address}\n")
    _check_update(r)

    running = _game_running(ssh)
    if running is None:
        r.add("SKIP", "game process check (only on the Windows PC that runs the game)")
    elif running:
        r.add("OK", "the game is running")
    else:
        r.add("FAIL", "the game is not running: start Baldur's Gate 3 and load a save")

    if not ssh and sys.platform == "win32":
        game_dir = find_game_dir()
        if not game_dir:
            r.add("WARN", "could not find the game folder in Steam (skipping the setup check)")
        else:
            try:
                s = read_settings(settings_path(game_dir))
            except (ValueError, OSError):
                s = {}
            if s.get("EnableLuaDebugger") is True:
                r.add("OK", f"ScriptExtenderSettings.json enables the debugger on port {s.get('LuaDebuggerPort', GAME_PORT)}")
            else:
                r.add("FAIL", "the Lua debugger is not enabled: run `bg3coop setup`, then restart the game")
            if not (game_dir / "bin" / "DWrite.dll").is_file():
                r.add("FAIL", f"Script Extender (DWrite.dll) is missing from {game_dir / 'bin'}: see {SE_RELEASES}")

    netstat = _run(["netstat", "-an", "-p", "TCP"], ssh)
    if netstat is not None:
        addrs = listen_addresses(netstat, remote_port)
        if not addrs:
            r.add("FAIL" if running else "WARN", f"nothing listens on port {remote_port} "
                  "(Script Extender not loaded, debugger off, or another port configured)")
        elif all(h in ("127.0.0.1", "[::1]") for h in addrs):
            r.add("OK", f"the debugger port {remote_port} only accepts connections from this PC")
        else:
            r.add("WARN", f"port {remote_port} listens on {', '.join(addrs)}: other machines on the network "
                  "could run code in your game. Block it in the firewall.")

    try:
        se = game.eval("return Ext.Utils.Version()", "client").strip()
        gv = game.eval("return Ext.Utils.GameVersion()", "client").strip()
        proto = game.client.server_version if game.client else "?"
        r.add("OK", f"connected: Script Extender v{se}, game {gv}, debugger protocol {proto}")
        if se.isdigit() and int(se) != TESTED_SE_VERSION:
            r.add("WARN", f"tested with Script Extender v{TESTED_SE_VERSION}; v{se} may behave differently")
    except DebuggerBusy as e:
        if netstat is not None and connected_clients(netstat, remote_port):
            r.add("WARN", f"another program is connected to the debugger port {remote_port}, usually the agent's "
                  "bg3 server (so it reached the game). The game serves one connection at a time, so doctor "
                  "cannot check the rest")
            r.todo = ("Not checked to the end: ask the agent to call `party`, or close the agent and run "
                      "`bg3coop doctor` again.")
        else:
            r.add("FAIL", str(e))
        game.close()
        return _done(r)
    except NotReady as e:
        r.add("WARN", str(e))
        r.todo = ("The game is still starting or loading: wait until it is at the main menu or in a save, "
                  "then run `bg3coop doctor` again.")
        game.close()
        return _done(r)
    except GameError as e:
        r.add("FAIL", str(e))
        game.close()
        return _done(r)

    try:
        game.eval("return 1", "server")
        loaded = True
        r.add("OK", "a save is loaded")
    except GameError as e:
        loaded = False
        r.add("WARN", f"{e}: the agent can only play once a save is loaded")
        r.todo = ("The setup is ready, but the agent cannot play yet: load a save with the companion it should "
                  "play in the party (keep the game in front if it pauses in the background), then run "
                  "`bg3coop doctor` again to check the rest.")

    if loaded:
        try:
            m = game.call("memory")
            want = modpak.mod_version()
            if not m.get("loaded"):
                r.add("WARN", f"the {modpak.MOD_NAME} mod is not loaded: the agent forgets where the party has "
                      "been on every save load. Run `bg3coop setup` with the game closed")
            elif m.get("version") != want:
                r.add("WARN", f"the {modpak.MOD_NAME} mod is v{m.get('version')}, this bg3coop ships v{want}: "
                      "run `bg3coop setup` with the game closed")
            else:
                r.add("OK", f"the {modpak.MOD_NAME} mod is loaded (v{want})")
        except GameError as e:
            r.add("WARN", f"cannot check the {modpak.MOD_NAME} mod: {e}")

    for ctx in ("client", "server") if loaded else ("client",):
        try:
            v = game.call("ping", context=ctx)["version"]
            want = game.versions[ctx]
            if v == want:
                r.add("OK", f"{ctx} script injected (v{v})")
            else:
                r.add("FAIL", f"{ctx} script reports v{v}, expected v{want}")
        except GameError as e:
            r.add("FAIL", f"cannot inject the {ctx} script: {e}")
    game.close()
    return _done(r)


def _check_update(r: Report) -> None:
    latest = update.latest_version()
    if latest is None:
        r.add("SKIP", "could not reach GitHub to check for a newer bg3coop")
    elif msg := update.notice(latest):
        r.add("WARN", msg)
    else:
        r.add("OK", f"bg3coop is up to date (latest release {latest})")


def _done(r: Report) -> int:
    if r.failed:
        print("\nSome checks failed; fix the FAIL lines above.")
    else:
        print("\n" + (r.todo or "All good."))
    return 1 if r.failed else 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="bg3coop", description="Play Baldur's Gate 3 with an AI agent.")
    p.add_argument("--version", action="version", version=f"bg3coop {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup", help="find the game, enable the Script Extender's Lua debugger and install "
                       "the memory mod")
    s.add_argument("--game-dir", help="the game's install folder, if it is not found automatically")
    s.add_argument("--port", type=int, default=GAME_PORT)
    s.add_argument("--dry-run", action="store_true", help="show what would change without writing")
    s.add_argument("--no-mod", action="store_true", help="do not install the memory mod (optional: without it every "
                   "save load wipes where the party has been and the agent's goal/story notes)")
    s.set_defaults(fn=cmd_setup)
    d = sub.add_parser("doctor", help="check that the game, Script Extender and debugger are ready")
    d.set_defaults(fn=cmd_doctor)
    m = sub.add_parser("mcp", help="run the MCP server (what agents start)")
    m.set_defaults(fn=None)
    a, rest = p.parse_known_args(argv)
    if a.cmd == "mcp":
        from .server import main as mcp_main

        sys.argv = ["bg3coop-mcp", *rest]
        mcp_main()
        return 0
    if rest:
        p.error(f"unrecognized arguments: {' '.join(rest)}")
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
