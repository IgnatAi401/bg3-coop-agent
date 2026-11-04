"""The BG3 Co-op Memory mod: builds its .pak and turns it on in modsettings.lsx. Standard library only,
like the rest of `bg3coop setup`."""

from __future__ import annotations

import re
import struct
from importlib import resources
from pathlib import Path

MOD_UUID = "addfead0-7a1a-46c3-942a-77c0348aeee3"
MOD_FOLDER = "BG3CoopMemory"
MOD_NAME = "BG3 Co-op Memory"
PAK_NAME = "BG3CoopMemory.pak"


def _script() -> bytes:
    return resources.files("bg3coop").joinpath("mod", "BootstrapServer.lua").read_bytes()


def mod_version(lua: bytes | None = None) -> int:
    """VERSION in the mod's script: what doctor compares with the one running in the game."""
    m = re.search(rb"^VERSION = (\d+)", _script() if lua is None else lua, re.M)
    return int(m.group(1)) if m else 0


# 1.<VERSION>.0.0, as major << 55 | minor << 47 | revision << 31 | build
VERSION64 = 1 << 55 | mod_version() << 47


META = f"""<?xml version="1.0" encoding="UTF-8"?>
<save>
    <version major="4" minor="0" revision="9" build="331"/>
    <region id="Config">
        <node id="root">
            <children>
                <node id="Dependencies"/>
                <node id="ModuleInfo">
                    <attribute id="Author" type="LSString" value="bg3-coop-agent"/>
                    <attribute id="CharacterCreationLevelName" type="FixedString" value=""/>
                    <attribute id="Description" type="LSString" value="Remembers where the party has been, inside the save. Part of bg3-coop-agent."/>
                    <attribute id="Folder" type="LSString" value="{MOD_FOLDER}"/>
                    <attribute id="LobbyLevelName" type="FixedString" value=""/>
                    <attribute id="MD5" type="LSString" value=""/>
                    <attribute id="MainMenuBackgroundVideo" type="FixedString" value=""/>
                    <attribute id="MenuLevelName" type="FixedString" value=""/>
                    <attribute id="Name" type="LSString" value="{MOD_NAME}"/>
                    <attribute id="NumPlayers" type="uint8" value="4"/>
                    <attribute id="PhotoBooth" type="FixedString" value=""/>
                    <attribute id="StartupLevelName" type="FixedString" value=""/>
                    <attribute id="Tags" type="LSWString" value=""/>
                    <attribute id="Type" type="FixedString" value="Add-on"/>
                    <attribute id="UUID" type="FixedString" value="{MOD_UUID}"/>
                    <attribute id="Version64" type="int64" value="{VERSION64}"/>
                    <children>
                        <node id="PublishVersion">
                            <attribute id="Version64" type="int64" value="{VERSION64}"/>
                        </node>
                        <node id="TargetModes">
                            <children>
                                <node id="Target">
                                    <attribute id="Object" type="FixedString" value="Story"/>
                                </node>
                            </children>
                        </node>
                    </children>
                </node>
            </children>
        </node>
    </region>
</save>
"""

SE_CONFIG = f'{{\n  "RequiredVersion": 20,\n  "ModTable": "{MOD_FOLDER}",\n  "FeatureFlags": ["Lua"]\n}}\n'


def mod_files() -> dict[str, bytes]:
    lua = _script()
    base = f"Mods/{MOD_FOLDER}"
    return {
        f"{base}/meta.lsx": META.encode(),
        f"{base}/ScriptExtender/Config.json": SE_CONFIG.encode(),
        f"{base}/ScriptExtender/Lua/BootstrapServer.lua": lua,
    }


# ---------------------------------------------------------------- .pak (LSPK v18, what BG3 reads)


def lz4_block(data: bytes) -> bytes:
    """An LZ4 block made of literals only: valid for any LZ4 decoder, no compression needed."""
    n = len(data)
    if n < 15:
        return bytes([n << 4]) + data
    out = bytearray([0xF0])
    rest = n - 15
    while rest >= 255:
        out.append(255)
        rest -= 255
    out.append(rest)
    return bytes(out) + data


def lz4_unblock(block: bytes) -> bytes:
    """Decode an LZ4 block (for tests and for reading back an installed pak)."""
    out, i = bytearray(), 0
    while i < len(block):
        token = block[i]
        i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = block[i]
                i += 1
                lit += b
                if b != 255:
                    break
        out += block[i:i + lit]
        i += lit
        if i >= len(block):
            break
        offset = block[i] | block[i + 1] << 8
        i += 2
        ml = token & 15
        if ml == 15:
            while True:
                b = block[i]
                i += 1
                ml += b
                if b != 255:
                    break
        for _ in range(ml + 4):
            out.append(out[-offset])
    return bytes(out)


_HEADER = struct.Struct("<4sIQIBB16sH")  # signature, version, file list offset/size, flags, priority, md5, parts
_ENTRY = struct.Struct("<256sIHBBII")  # name, offset (low 32, high 16), part, flags, size on disk, uncompressed
LZ4 = 0x02 | 0x20  # LZ4, default level


def build_pak(files: dict[str, bytes]) -> bytes:
    body, entries = bytearray(), []
    pos = _HEADER.size
    for name, data in files.items():
        packed = lz4_block(data)
        entries.append(_ENTRY.pack(name.encode().ljust(256, b"\0"), pos & 0xFFFFFFFF, pos >> 32, 0, LZ4,
                                   len(packed), len(data)))
        body += packed
        pos += len(packed)
    table = lz4_block(b"".join(entries))
    file_list = struct.pack("<II", len(entries), len(table)) + table
    header = _HEADER.pack(b"LSPK", 18, pos, len(file_list), 0, 0, b"\0" * 16, 1)
    return header + bytes(body) + file_list


def read_pak(pak: bytes) -> dict[str, bytes]:
    sig, version, offset, _, _, _, _, _ = _HEADER.unpack_from(pak)
    if sig != b"LSPK" or version != 18:
        raise ValueError("not a BG3 pak")
    count, size = struct.unpack_from("<II", pak, offset)
    table = lz4_unblock(pak[offset + 8:offset + 8 + size])
    out = {}
    for k in range(count):
        name, lo, hi, _, flags, on_disk, _ = _ENTRY.unpack_from(table, k * _ENTRY.size)
        start = lo | hi << 32
        raw = pak[start:start + on_disk]
        out[name.rstrip(b"\0").decode()] = lz4_unblock(raw) if flags & 0x0F == 2 else raw
    return out


# ---------------------------------------------------------------- install


def larian_dir() -> Path | None:
    import os

    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / "Larian Studios" / "Baldur's Gate 3" if base else None


_SHORT_DESC = f"""<node id="ModuleShortDesc">
                            <attribute id="Folder" type="LSString" value="{MOD_FOLDER}"/>
                            <attribute id="MD5" type="LSString" value=""/>
                            <attribute id="Name" type="LSString" value="{MOD_NAME}"/>
                            <attribute id="PublishHandle" type="uint64" value="0"/>
                            <attribute id="UUID" type="guid" value="{MOD_UUID}"/>
                            <attribute id="Version64" type="int64" value="{VERSION64}"/>
                        </node>"""


def enable_in_modsettings(text: str) -> str | None:
    """modsettings.lsx with the mod added to the end of the Mods list (or its version brought up to
    date), or None if it is already there as this version."""
    if MOD_UUID in text:
        m = re.search(r'<node id="ModuleShortDesc">(?:(?!</node>).)*?' + MOD_UUID + r'(?:(?!</node>).)*?</node>', text, re.S)
        if not m:
            return None
        block = re.sub(r'(<attribute id="Version64" type="int64" value=")\d+', rf"\g<1>{VERSION64}", m.group(0))
        return None if block == m.group(0) else text[:m.start()] + block + text[m.end():]
    text = re.sub(r'<node id="Mods"\s*/>', '<node id="Mods">\n<children>\n</children>\n</node>', text, count=1)
    m = re.search(r'(<node id="Mods">\s*<children>)(.*?)(\n?(\s*)</children>)', text, re.S)
    if not m:
        raise ValueError("no Mods list in modsettings.lsx")
    indent = m.group(4) + "    "
    return text[:m.end(2)] + "\n" + indent + _SHORT_DESC + text[m.end(2):]
