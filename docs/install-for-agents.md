# Installing BG3 Co-op (instructions for an AI agent)

You are setting up BG3 Co-op for the person you are working with. When it is done, you (or
another agent session) can play one party member next to them in Baldur's Gate 3. Work through
the steps in order and tell them what you are doing in their language. Ask before downloading
anything or changing files outside the places named here.

## What is needed

- Windows 10/11, Baldur's Gate 3 on Steam, and the game and the agent on the same PC.
  Tested with game 4.1.1.7631656 (DirectX 11) and Script Extender v33.
- **Python 3.10 or newer**, in any form: uv, pipx, a python.org / Microsoft Store Python, or a
  conda environment.
- **The package**: one wheel from the GitHub release. Its only dependency is `mcp`, which pip or
  uv download.

```
WHEEL = https://github.com/IgnatAi401/bg3-coop-agent/releases/download/v0.1.1/bg3coop-0.1.1-py3-none-any.whl
```

## What "installed" means

However you install it, you end up with two commands that work from a new terminal:

| | runs | used for |
| --- | --- | --- |
| `BG3COOP` | `bg3coop`, or `<python> -m bg3coop.cli` | `BG3COOP setup`, `BG3COOP doctor` |
| `BG3COOP_MCP` | `bg3coop-mcp`, or `<python> -m bg3coop.server` | the MCP server (stdio) the agent starts |

**Done** means `BG3COOP doctor` prints only `OK` lines (a `SKIP`/`WARN` about the update check is
fine) with the game running and a save loaded, and after a restart the agent has the `bg3` tools
(`party` answers).

## 1. Script Extender

The game needs Norbyte's Script Extender: `DWrite.dll` in the game's `bin` folder (for example
`D:\SteamLibrary\steamapps\common\Baldurs Gate 3\bin`). If it is not there, ask the person to
download the latest release from https://github.com/Norbyte/bg3se/releases and put `DWrite.dll`
into `bin`, or do it yourself with their permission. The release asset is a zip named
`BG3SE-Updater-<date>.zip`; `DWrite.dll` is the file inside it. It is not code-signed, which is
normal for it.

## 2. Install bg3coop

First look at what the PC already has: `uv --version`, `pipx --version`, `py -0p` (Python
launcher: lists installed Pythons), `python --version`, `conda env list`. With uv, use it. Without
uv, ask the person first whether to install it (next section), and only then pick the first way
that fits:

| the PC has | install | `BG3COOP` / `BG3COOP_MCP` |
| --- | --- | --- |
| uv | nothing to install; or `uv tool install <WHEEL>` for permanent commands | `uvx --from <WHEEL> bg3coop` / `uvx --from <WHEEL> bg3coop-mcp` (or `bg3coop` / `bg3coop-mcp` after `uv tool install`) |
| pipx | `pipx install <WHEEL>` | `bg3coop` / `bg3coop-mcp` |
| Python ≥ 3.10 | its own venv, below | `<venv>\Scripts\bg3coop.exe` / `<venv>\Scripts\bg3coop-mcp.exe` |
| conda | its own env, below | `<env>\python.exe -m bg3coop.cli` / `<env>\python.exe -m bg3coop.server` |

A venv (replace `py -3.12` with the Python you found; `python` works too if it is ≥ 3.10):

```powershell
py -3.12 -m venv "$env:LOCALAPPDATA\bg3coop\venv"
& "$env:LOCALAPPDATA\bg3coop\venv\Scripts\python.exe" -m pip install <WHEEL>
```

A conda env: `conda create -n bg3coop python=3.12`, then `<env>\python.exe -m pip install <WHEEL>`
(`<env>` is the path `conda env list` shows for it).

Rules:

- Do not install into the system Python or conda's `base` environment, do not use admin rights,
  and do not change the person's PATH or other environments (the uv installer is the one exception,
  when they chose it).
- If none of the above is there, stop and ask the person: uv (next section), or Python from
  https://www.python.org/downloads/ .
- Prefer full paths (`C:\Users\…\Scripts\bg3coop-mcp.exe`) when registering the MCP server: some
  agents start it with a reduced PATH.
- Run `BG3COOP --version` to confirm it works.

### Without uv: ask whether to install it

The official plugins (step 4) start bg3coop with `uvx`, so they need uv. Without uv you install
bg3coop yourself and register it with the agent by hand. Tell the person, in their language, what
each choice brings and costs, and let them choose:

**Install uv, then use the plugin**

- What they get: bg3coop shows on the agent's plugin page, where it can be switched off or removed
  like any plugin. Updating the plugin updates bg3coop as well, in one step. There is no venv to
  look after, and the timeouts are already set (the `ask` tool waits up to two minutes for them).
- What it costs: one more program on the PC. The installer is a script downloaded and run from
  astral.sh: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
  (or `winget install --id astral-sh.uv -e`). It needs no admin rights. The script puts `uv.exe`,
  `uvx.exe` and `uvw.exe` in `%USERPROFILE%\.local\bin` and adds that folder to their user PATH
  (winget uses a folder of its own, also on PATH): the one change to PATH these instructions
  allow, and only with their consent. uv keeps
  downloaded packages in `%LOCALAPPDATA%\uv\cache`, and if it finds no Python 3.10+ it downloads one
  of its own. The agent app has to be restarted after the install so it sees the new PATH.

**Keep what the PC has**

- What they get: nothing new beyond bg3coop's own venv or conda env, and PATH stays as it is.
- What it costs: the agent's plugin page does not list bg3coop (it is a hand-registered MCP
  server; step 4 says where it shows instead). Updates are by hand: install the new wheel into the
  same venv or env, and the registration stays as it is. Removing it is also by hand.

Both ways download the wheel and its dependencies (`mcp` and what it needs, from PyPI) once, and
again for each update. They play the same; the difference is only in installing, updating and
removing.

## 3. Configure the game

The game must be closed (it rewrites its mod list when it exits). First ask the person whether they
want the Memory mod (below: what it keeps, and what they give up without it). Then ask them to quit
the game, and run:

```powershell
BG3COOP setup
```

`setup` finds the game through Steam, turns on the Script Extender's Lua debugger (port 9998,
local connections only) in `bin\ScriptExtenderSettings.json`, checks `DWrite.dll`, and installs
the small "BG3 Co-op Memory" mod (`%LOCALAPPDATA%\Larian Studios\Baldur's Gate 3\Mods`, enabled
in `PlayerProfiles\Public\modsettings.lsx` next to it, the original backed up as
`modsettings.lsx.bg3coop-backup`). `setup --dry-run` shows what it would change. The mod is
optional, but recommended: it keeps the agent's memory in the save, namely where the party has
been and the agent's goal/story/place notes (its promises, plans, what happened). Loading a save
then takes that memory back to the same point. Saves made with the mod list it as required.

If the person does not want it, run `BG3COOP setup --no-mod`, which leaves the Mods folder and
`modsettings.lsx` alone and works with the game open; `doctor` then shows a WARN about the
missing mod, which is expected. Before they choose, tell them what they give up: without the mod
that memory lasts only until the next save load. Every load, quickload or reload after a death
wipes the explored areas and those notes. Meanwhile the agent's conversation still remembers what
happened before the load, so after going back to an older save it may act on promises, plans and
events that no longer exist in that save, and it walks back over ground it has already explored.
Persona and preference notes are kept on the PC and are not affected.

If `setup` cannot find the game, pass `--game-dir "<install folder>"`. Every line should say what it did; fix any
problem it reports and run it again.

## 4. Connect the agent

Register `BG3COOP_MCP` with the agent the person uses, under the name `bg3`, using the exact
command that worked in step 2. Each agent has an official plugin that does this in one step,
but the plugins start the server with `uvx`, so they need uv; otherwise register the command by
hand.

**Claude Code**

- with uv: in Claude Code, `/plugin marketplace add IgnatAi401/bg3-coop-agent`, then
  `/plugin install bg3coop@bg3-coop-agent` (in a terminal: `claude plugin marketplace add …` and
  `claude plugin install …`)
- otherwise, in a terminal: `claude mcp add --scope user bg3 -- BG3COOP_MCP`

**Codex**

- with uv, in a terminal:

  ```powershell
  codex plugin marketplace add IgnatAi401/bg3-coop-agent
  codex plugin add bg3coop@bg3-coop-agent
  ```

  The plugin already sets the timeouts below.
- otherwise: `codex mcp add bg3 -- BG3COOP_MCP`, then open `%USERPROFILE%\.codex\config.toml` and
  add `tool_timeout_sec = 180` and `startup_timeout_sec = 120` under `[mcp_servers.bg3]`: the `ask`
  tool waits up to two minutes for the human (Codex's default is 60 s).

**DeepSeek Harness (dsh)**

- with uv: install the dsh plugin package from the release, either on dsh's Plugins page ("Add
  plugin", paste the address, install, enable) or in a terminal with
  `dsh plugin add <address>` (`--profile <name>` for a profile other than the default):

  ```
  https://github.com/IgnatAi401/bg3-coop-agent/releases/download/v0.1.1/dsh-bg3coop-0.1.1.tgz
  ```

- otherwise (or if installing fails), add the entry to the profile's patch file by hand
  (`%USERPROFILE%\.dsh\profiles\<profile>\cordis.patch.yml`, a YAML list; append, keep what is
  there). `command` is the program and `args` the rest of `BG3COOP_MCP`, for example
  `command: 'C:\Users\…\bg3coop\venv\Scripts\bg3coop-mcp.exe'` and `args: []`:

```yaml
- insert:
    - id: mcp-bg3coop
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: bg3
        transport: stdio
        command: uvx
        args: ['--from', '<WHEEL>', 'bg3coop-mcp']
        toolCallTimeoutMs: 180000
```

The entry above is complete; there is no need to look up the `dsh-mcp-client` schema. In the dsh
desktop app, `dsh` is not on PATH: the command is
`%LOCALAPPDATA%\Programs\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd`, the profile is
usually `desktop`, and that profile refuses `--dump-config`. The app picks up an edited patch file
without a restart.

Restart the agent (or start a new session) so it loads the server. Its tools appear as
`party`, `set_agent`, `look`, … (prefixed with the server name, e.g. `mcp__bg3__party`). If the
agent did not get the server instructions (older dsh versions), it reads them with the `rules` tool.

Registered by hand, bg3 is an MCP server, not a plugin, so the agent's plugin list does not show
it. Tell the person where it is instead: dsh lists it under Settings → Built-in plugins → Plugin
list (global, entry `mcp-bg3coop`), Claude Code under `/mcp` (`claude mcp list`), Codex in
`codex mcp list`.

## 5. Check

Ask the person to start the game and load a save with the companion they want you to play in
the party (the Script Extender downloads its runtime on the first start). In that same message,
before they start the game, tell them that on startup the game may report corrupted game files or
a similar error: with the Script Extender and mods installed this is common and can usually be
ignored, so they can dismiss it and carry on. Then:

```powershell
BG3COOP doctor
```

Every line should be `OK`; each `FAIL` says what to change. `doctor` also asks GitHub whether a
newer release exists (skipped when offline). The last line says `All good.` only when nothing is
left; otherwise it says what is (for example, loading a save). Then call `party`: when it lists the
party, the install is done.

The game accepts one debugger connection at a time. Once the agent's `bg3` server has connected
(after its first game tool call), `doctor` cannot get in and says so instead of checking the rest;
that is expected, not a fault.

Delete what you downloaded for the install (the wheel, the Script Extender zip, temporary folders).

## 6. Start playing

Tell the person how to start: in a new agent session, say "start playing, you control
Shadowheart" (or another companion). In-game, F10 toggles the chat panel; middle-click points at
things. Playing stays smooth when the agent keeps looping: Claude Code's `/loop`, dsh's goal or
ralph mode.

## Updating and removing

`doctor` and the MCP server say when a newer release is out (the server once, in a tool result:
pass it on to the person). Plugin and wheel always share one version number.

- Update the same way it was installed. A plugin always starts the wheel of its own version, so
  updating the plugin updates both: Claude Code `/plugin marketplace update bg3-coop-agent` (or
  `claude plugin update bg3coop@bg3-coop-agent` in a terminal; auto-update is off for third-party
  marketplaces until the person turns it on under Marketplaces in `/plugin`); Codex
  `codex plugin marketplace upgrade bg3-coop-agent`; dsh: install the new release's `.tgz` address
  the same way (Plugins page or `dsh plugin add <address>`), which replaces the old one. Restart the
  agent afterwards. Otherwise use the new release's wheel URL: the new URL in the `uvx` commands and the MCP registration; `uv tool install --force <WHEEL>`;
  `pipx install --force <WHEEL>`; or `<python> -m pip install --upgrade <WHEEL>` in the venv /
  conda env. Then close the game and run `BG3COOP setup` again so the Memory mod is updated too
  (`BG3COOP setup --no-mod` if the person skipped the mod; the game can stay open).
- Remove: uninstall the plugin (`/plugin uninstall bg3coop@bg3-coop-agent`,
  `codex plugin remove bg3coop@bg3-coop-agent`, `dsh plugin remove dsh-bg3coop`), or
  `claude mcp remove bg3` / `codex mcp remove bg3` / delete the dsh patch entry; remove the package (`uv tool uninstall bg3coop`, `pipx uninstall bg3coop`, or
  delete the venv folder / `conda env remove -n bg3coop`). With the game closed, delete
  `BG3CoopMemory.pak` from the Mods folder and restore `modsettings.lsx.bg3coop-backup` (saves made
  with the mod list it as required); set `EnableLuaDebugger` to `false` in
  `bin\ScriptExtenderSettings.json`.
