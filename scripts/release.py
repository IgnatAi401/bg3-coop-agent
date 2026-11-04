"""Keep the agent plugins in step with the package version, and pack them for a GitHub Release.

    uv run python scripts/release.py sync            # write version + wheel URL into integrations/
    uv run python scripts/release.py check [--tag vX.Y.Z]
    uv run python scripts/release.py pack dist       # Release assets, see pack()

The version comes from pyproject.toml, the repository from its [project.urls] Repository.
"""

from __future__ import annotations

import argparse
import json
import re
import io
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSIONED_JSON = (
    "integrations/claude-code/.claude-plugin/plugin.json",
    "integrations/codex/.codex-plugin/plugin.json",
    "integrations/dsh/package.json",
)
WHEEL_FILES = (
    "integrations/claude-code/.mcp.json",
    "integrations/codex/.mcp.json",
    "integrations/dsh/cordis.patch.yml",
    "docs/install-for-agents.md",
    "README.md",
    "README.en.md",
)
# Release asset URLs: the wheel, and the dsh plugin tarball (only in the docs).
WHEEL_RE = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/releases/download/[^/\s'\"]+/bg3coop-[^/\s'\"]+\.whl")
DSH_TGZ_RE = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/releases/download/[^/\s'\"]+/dsh-bg3coop-[^/\s'\"]+\.tgz")


def project() -> tuple[str, str]:
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    repo = meta["urls"]["Repository"].removeprefix("https://github.com/").strip("/")
    return meta["version"], repo


def wheel_url(version: str, repo: str) -> str:
    return f"https://github.com/{repo}/releases/download/v{version}/bg3coop-{version}-py3-none-any.whl"


def dsh_tgz_name(version: str) -> str:
    return f"dsh-bg3coop-{version}.tgz"


def dsh_tgz_url(version: str, repo: str) -> str:
    return f"https://github.com/{repo}/releases/download/v{version}/{dsh_tgz_name(version)}"


def expected() -> dict[str, str]:
    """Each managed file's content as it should be for the current version."""
    version, repo = project()
    url = wheel_url(version, repo)
    out = {}
    for rel in VERSIONED_JSON:
        text = (ROOT / rel).read_text(encoding="utf-8")
        out[rel] = re.sub(r'("version":\s*")[^"]*(")', rf"\g<1>{version}\g<2>", text, count=1)
    for rel in WHEEL_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        if not WHEEL_RE.search(text):
            raise SystemExit(f"{rel}: no wheel URL to update")
        out[rel] = DSH_TGZ_RE.sub(dsh_tgz_url(version, repo), WHEEL_RE.sub(url, text))
    return out


def sync() -> int:
    for rel, text in expected().items():
        path = ROOT / rel
        if path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
            print("updated", rel)
    return 0


def check(tag: str | None) -> int:
    version, _ = project()
    bad = [rel for rel, text in expected().items() if (ROOT / rel).read_text(encoding="utf-8") != text]
    for rel in VERSIONED_JSON:
        json.loads((ROOT / rel).read_text(encoding="utf-8"))
    if tag and tag != f"v{version}":
        print(f"tag {tag} does not match pyproject version {version}", file=sys.stderr)
        return 1
    if bad:
        print("out of date (run `uv run python scripts/release.py sync`): " + ", ".join(bad), file=sys.stderr)
        return 1
    print(f"plugins match v{version}")
    return 0


def pack(out_dir: str) -> int:
    """Plugin files for the Release, each in the form its agent installs:

    - bg3coop-claude-code-plugin-X.Y.Z.zip: the plugin folder, for people who do not add the
      marketplace (Claude Code accepts a plugin directory or a .zip of it).
    - dsh-bg3coop-X.Y.Z.tgz: an npm package tarball (`package/` prefix, the files `package.json`
      lists); `dsh plugin add <url>` hands it to pnpm, which does not take a .zip.

    Codex installs only from the marketplace (`codex plugin marketplace add`), so it gets none.
    """
    version, _ = project()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    src = ROOT / "integrations" / "claude-code"
    dest = out / f"bg3coop-claude-code-plugin-{version}.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(src.rglob("*")):
            if f.is_file():
                z.write(f, f"bg3coop/{f.relative_to(src).as_posix()}")
        z.write(ROOT / "LICENSE", "bg3coop/LICENSE")
    print("wrote", dest)

    src = ROOT / "integrations" / "dsh"
    manifest = json.loads((src / "package.json").read_text(encoding="utf-8"))
    files = [src / "package.json", ROOT / "LICENSE"]
    for entry in manifest["files"]:
        path = src / entry
        files += sorted(f for f in path.rglob("*") if f.is_file()) if path.is_dir() else [path]
    dest = out / dsh_tgz_name(version)
    with tarfile.open(dest, "w:gz", format=tarfile.USTAR_FORMAT) as t:
        for f in files:
            data = f.read_bytes()
            info = tarfile.TarInfo("package/" + (f.name if f.parent == ROOT else f.relative_to(src).as_posix()))
            info.size, info.mode, info.mtime = len(data), 0o644, 0
            t.addfile(info, io.BytesIO(data))
    print("wrote", dest)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync")
    c = sub.add_parser("check")
    c.add_argument("--tag")
    k = sub.add_parser("pack")
    k.add_argument("out_dir")
    a = p.parse_args(argv)
    if a.cmd == "sync":
        return sync()
    if a.cmd == "check":
        return check(a.tag)
    return pack(a.out_dir)


if __name__ == "__main__":
    sys.exit(main())
