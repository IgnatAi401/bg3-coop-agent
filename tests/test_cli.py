"""Setup and doctor helpers that do not need the game."""

from __future__ import annotations

import json
from xml.etree import ElementTree

import pytest

from bg3coop import cli, modpak

LIBRARIES = r'''"libraryfolders"
{
	"0"
	{
		"path"		"C:\\Program Files (x86)\\Steam"
		"apps"
		{
			"228980"		"1089391563"
		}
	}
	"1"
	{
		"path"		"D:\\SteamLibrary"
		"apps"
		{
			"1086940"		"155499474767"
		}
	}
}
'''


def test_parse_vdf():
    libs = cli.parse_vdf(LIBRARIES)["libraryfolders"]
    assert libs["1"]["path"] == "D:\\SteamLibrary"
    assert "1086940" in libs["1"]["apps"]


def test_find_game_dir(tmp_path, monkeypatch):
    root, lib = tmp_path / "Steam", tmp_path / "Lib"
    (root / "steamapps").mkdir(parents=True)
    (root / "steamapps" / "libraryfolders.vdf").write_text(
        f'"libraryfolders" {{ "0" {{ "path" "{root.as_posix()}" }} '
        f'"1" {{ "path" "{lib.as_posix()}" "apps" {{ "1086940" "1" }} }} }}')
    (lib / "steamapps").mkdir(parents=True)
    (lib / "steamapps" / "appmanifest_1086940.acf").write_text('"AppState" { "installdir" "BG3 Custom" }')
    (lib / "steamapps" / "common" / "BG3 Custom" / "bin").mkdir(parents=True)
    monkeypatch.setattr(cli, "steam_roots", lambda: [root])
    assert cli.find_game_dir() == lib / "steamapps" / "common" / "BG3 Custom"


def test_settings_keep_player_options(tmp_path):
    path = tmp_path / "ScriptExtenderSettings.json"
    path.write_text("\ufeff" + json.dumps({"EnableAchievements": True, "EnableLuaDebugger": False}), encoding="utf-8")
    merged = cli.merged_settings(cli.read_settings(path), 9998)
    assert merged == {"EnableAchievements": True, "EnableLuaDebugger": True, "LuaDebuggerPort": 9998,
                      "CreateConsole": False}
    assert cli.merged_settings(merged, 9998) == merged


MODSETTINGS = """<?xml version="1.0" encoding="UTF-8"?>
<save>
    <version major="4" minor="8" revision="0" build="700"/>
    <region id="ModuleSettings">
        <node id="root">
            <children>
                <node id="Mods">
                    <children>
                        <node id="ModuleShortDesc">
                            <attribute id="Folder" type="LSString" value="GustavX"/>
                            <attribute id="UUID" type="guid" value="cb555efe-2d9e-131f-8195-a89329d218ea"/>
                        </node>
                    </children>
                </node>
            </children>
        </node>
    </region>
</save>
"""


@pytest.fixture(autouse=True)
def larian(tmp_path, monkeypatch):
    """The game's user folder, as a closed game leaves it."""
    base = tmp_path / "appdata" / "Larian Studios" / "Baldur's Gate 3"
    (base / "PlayerProfiles" / "Public").mkdir(parents=True)
    (base / "PlayerProfiles" / "Public" / "modsettings.lsx").write_text(MODSETTINGS, encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr(cli, "_game_running", lambda ssh_host=None: False)
    return base


def test_setup_installs_the_memory_mod(tmp_path, larian, capsys, monkeypatch):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "DWrite.dll").write_bytes(b"x")
    settings = larian / "PlayerProfiles" / "Public" / "modsettings.lsx"
    assert cli.main(["setup", "--game-dir", str(tmp_path), "--dry-run"]) == 0
    assert not (larian / "Mods").exists() and settings.read_text() == MODSETTINGS
    assert cli.main(["setup", "--game-dir", str(tmp_path)]) == 0
    pak = (larian / "Mods" / "BG3CoopMemory.pak").read_bytes()
    assert modpak.read_pak(pak) == modpak.mod_files()
    text = settings.read_text()
    assert text.index("GustavX") < text.index(modpak.MOD_UUID)  # after the base game
    mods = ElementTree.fromstring(text).find(".//node[@id='Mods']/children")
    assert [n.find("attribute[@id='Folder']").get("value") for n in mods] == ["GustavX", "BG3CoopMemory"]
    assert settings.with_name("modsettings.lsx.bg3coop-backup").read_text() == MODSETTINGS
    capsys.readouterr()
    assert cli.main(["setup", "--game-dir", str(tmp_path)]) == 0
    assert "mod is installed and turned on" in capsys.readouterr().out
    assert settings.read_text() == text  # nothing added twice
    # the game rewrites the mod list when it quits, so setup waits for it to close
    settings.write_text(MODSETTINGS, encoding="utf-8")
    monkeypatch.setattr(cli, "_game_running", lambda ssh_host=None: True)
    assert cli.main(["setup", "--game-dir", str(tmp_path)]) == 1
    assert "quit the game" in capsys.readouterr().out


def test_setup_without_the_memory_mod(tmp_path, larian, capsys, monkeypatch):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "DWrite.dll").write_bytes(b"x")
    settings = larian / "PlayerProfiles" / "Public" / "modsettings.lsx"
    # the mod is optional: skipping it works even while the game is running
    monkeypatch.setattr(cli, "_game_running", lambda ssh_host=None: True)
    assert cli.main(["setup", "--game-dir", str(tmp_path), "--no-mod"]) == 0
    out = capsys.readouterr().out
    assert "SKIP" in out and "Next:" in out and "still installed" not in out
    assert not (larian / "Mods").exists() and settings.read_text() == MODSETTINGS
    (larian / "Mods").mkdir()
    (larian / "Mods" / "BG3CoopMemory.pak").write_bytes(b"x")
    assert cli.main(["setup", "--game-dir", str(tmp_path), "--no-mod"]) == 0
    assert "still installed" in capsys.readouterr().out


def test_enable_in_an_empty_mod_list():
    out = modpak.enable_in_modsettings('<save><node id="Mods"/></save>')
    assert modpak.MOD_UUID in out and out.count('<node id="Mods">') == 1


def test_setup_writes_settings(tmp_path, capsys):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "DWrite.dll").write_bytes(b"x")
    code = cli.main(["setup", "--game-dir", str(tmp_path)])
    s = json.loads((tmp_path / "bin" / "ScriptExtenderSettings.json").read_text())
    assert code == 0 and s["EnableLuaDebugger"] is True and s["LuaDebuggerPort"] == 9998
    assert cli.main(["setup", "--game-dir", str(tmp_path)]) == 0
    assert "already enables" in capsys.readouterr().out


def test_setup_without_script_extender(tmp_path, capsys):
    (tmp_path / "bin").mkdir()
    assert cli.main(["setup", "--game-dir", str(tmp_path)]) == 1
    assert "DWrite.dll" in capsys.readouterr().out


NETSTAT = """
活动连接

  协议  本地地址          外部地址        状态
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING
  TCP    127.0.0.1:9998         0.0.0.0:0              LISTENING
  TCP    127.0.0.1:9998         127.0.0.1:50211        ESTABLISHED
  TCP    [::]:9998              [::]:0                 LISTENING
"""


def test_listen_addresses():
    assert cli.listen_addresses(NETSTAT, 9998) == ["127.0.0.1", "[::]"]
    assert cli.listen_addresses(NETSTAT, 1234) == []


def test_chunks_keep_text_and_limit():
    from bg3coop.game import _chunks
    text = "".join(f"line {i} 中文\n" for i in range(5000)) + "\n\nlast"
    pieces = _chunks(text, 1000)
    assert "".join(pieces) == text
    assert all(len(p.encode()) <= 1000 for p in pieces) and len(pieces) > 10


def test_modsettings_gets_the_new_mod_version():
    old = modpak.enable_in_modsettings(MODSETTINGS).replace(str(modpak.VERSION64), str(1 << 55))
    new = modpak.enable_in_modsettings(old)
    assert new.count(modpak.MOD_UUID) == 1 and str(modpak.VERSION64) in new
    assert new.count('value="36028797018963968"') == 0  # GustavX in the fixture has no Version64
    assert modpak.enable_in_modsettings(new) is None


def test_connected_clients():
    netstat = NETSTAT + "  TCP    127.0.0.1:9998         127.0.0.1:50300        CLOSE_WAIT\n" \
        "  TCP    127.0.0.1:50211        127.0.0.1:9998         ESTABLISHED\n"
    assert cli.connected_clients(netstat, 9998) == 1  # the game's side only; a dead client does not count
    assert cli.connected_clients(netstat, 1234) == 0


@pytest.fixture
def silent_debugger(monkeypatch):
    """A debugger port that takes connections and never answers, as the game does while another client is on it."""
    import functools
    import socket

    from bg3coop import game

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    port = srv.getsockname()[1]
    monkeypatch.setenv("BG3COOP_PORT", str(port))
    monkeypatch.delenv("BG3COOP_SSH_HOST", raising=False)
    monkeypatch.setattr(game, "RemoteLua", functools.partial(game.RemoteLua, connect_timeout=0.3))
    monkeypatch.setattr(cli, "_check_update", lambda r: None)
    monkeypatch.setattr(cli, "_game_running", lambda ssh_host=None: True)
    yield port
    srv.close()


@pytest.mark.parametrize("busy", [True, False])
def test_doctor_when_another_program_holds_the_debugger(silent_debugger, monkeypatch, capsys, busy):
    port = silent_debugger
    netstat = f"  TCP    127.0.0.1:{port}         0.0.0.0:0              LISTENING\n"
    if busy:
        netstat += f"  TCP    127.0.0.1:{port}         127.0.0.1:60899        ESTABLISHED\n"
    monkeypatch.setattr(cli, "_run", lambda cmd, ssh_host: netstat if cmd[0] == "netstat" else None)
    code = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert "Is BG3 running" not in out
    if busy:
        assert code == 0 and "another program is connected" in out and "All good" not in out
        assert "call `party`" in out
    else:
        assert code == 1 and "did not answer" in out
