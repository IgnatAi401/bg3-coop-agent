"""The agent plugins point at the wheel of the current version, and pack cleanly."""

from __future__ import annotations

import importlib.util
import json
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# scripts/release.py is a dev/CI tool and uses tomllib (3.11+); the package itself runs on 3.10.
if sys.version_info >= (3, 11):
    spec = importlib.util.spec_from_file_location("release", ROOT / "scripts" / "release.py")
    release = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release)
needs_tomllib = pytest.mark.skipif(sys.version_info < (3, 11), reason="scripts/release.py needs tomllib")


@needs_tomllib
def test_plugins_match_the_version():
    assert release.check(None) == 0


@needs_tomllib
def test_tag_must_match():
    version, _ = release.project()
    assert release.check(f"v{version}") == 0
    assert release.check("v0.0.0-not-this") == 1


@needs_tomllib
def test_every_plugin_starts_the_same_server():
    version, repo = release.project()
    url = release.wheel_url(version, repo)
    for rel in release.WHEEL_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert url in text, rel
        if rel.startswith("integrations/"):
            assert "bg3coop-mcp" in text, rel
    launch = {"command": "uvx", "args": ["--from", url, "bg3coop-mcp"]}
    cc = json.loads((ROOT / "integrations/claude-code/.mcp.json").read_text(encoding="utf-8"))["mcpServers"]["bg3"]
    assert cc == {"type": "stdio", **launch}
    # Codex: `ask` waits up to 120 s (default tool timeout 60 s); the first uvx download is slow.
    cx = json.loads((ROOT / "integrations/codex/.mcp.json").read_text(encoding="utf-8"))["mcpServers"]["bg3"]
    assert cx == {**launch, "startup_timeout_sec": 120, "tool_timeout_sec": 180}


@needs_tomllib
def test_docs_point_at_the_dsh_tarball():
    version, repo = release.project()
    url = release.dsh_tgz_url(version, repo)
    for rel in ("README.md", "README.en.md", "docs/install-for-agents.md"):
        assert url in (ROOT / rel).read_text(encoding="utf-8"), rel


def test_plugin_files_exist():
    """Every path a manifest names is inside its plugin folder."""
    cc = ROOT / "integrations/claude-code"
    assert (cc / json.loads((cc / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))["icon"]).is_file()
    cx = ROOT / "integrations/codex"
    manifest = json.loads((cx / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    assert (cx / manifest["mcpServers"]).is_file()
    for key in ("composerIcon", "logo"):
        assert (cx / manifest["interface"][key]).is_file()
    dsh = ROOT / "integrations/dsh"
    pkg = json.loads((dsh / "package.json").read_text(encoding="utf-8"))
    assert pkg["dsh"]["manifestVersion"] == 1
    assert (dsh / pkg["dsh"]["bundle"]["patch"]).is_file() and (dsh / pkg["icon"]).is_file()
    for entry in pkg["files"]:
        assert (dsh / entry).exists(), entry
    for lang in ("en", "zh"):
        assert json.loads((dsh / f"locale/{lang}.json").read_text(encoding="utf-8"))["meta"]["title"]


def test_marketplaces_point_at_plugins():
    cc = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
    assert (ROOT / cc["plugins"][0]["source"] / ".claude-plugin/plugin.json").is_file()
    cx = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text(encoding="utf-8"))
    assert (ROOT / cx["plugins"][0]["source"]["path"] / ".codex-plugin/plugin.json").is_file()


@needs_tomllib
def test_pack(tmp_path):
    assert release.pack(str(tmp_path)) == 0
    version, _ = release.project()
    names = zipfile.ZipFile(tmp_path / f"bg3coop-claude-code-plugin-{version}.zip").namelist()
    assert {"bg3coop/.claude-plugin/plugin.json", "bg3coop/.mcp.json", "bg3coop/LICENSE"} <= set(names)
    assert all(n.startswith("bg3coop/") for n in names)
    with tarfile.open(tmp_path / release.dsh_tgz_name(version)) as t:
        names = t.getnames()
        pkg = json.load(t.extractfile("package/package.json"))
    assert {"package/package.json", "package/cordis.patch.yml", "package/LICENSE", "package/locale/zh.json"} <= set(names)
    assert all(n.startswith("package/") for n in names)
    assert pkg["version"] == version


@needs_tomllib
def test_update_check_uses_the_repository():
    from bg3coop import update

    assert update.REPO == release.project()[1]


def test_rules_tool_returns_the_instructions():
    from bg3coop import server

    assert server.rules() == server.INSTRUCTIONS
