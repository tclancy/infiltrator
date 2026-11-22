"""A tiny DAT in the real DAT's shape, with real hashes over junk bytes.

No ROM content is involved: every chip is sha256(label) repeated to size, so
fixtures can be generated at test time and nothing is forged or committed.
"""

import hashlib
import json
import zipfile
import zlib
from pathlib import Path
from xml.sax.saxutils import quoteattr

import pytest

# label -> size. A label is the one true identity of a chip; roms that share
# a chip (parent/clone merges, BIOS) point at the same label.
CHIPS = {
    "a1": 512,
    "a2": 256,
    "ab3": 128,
    "bx-std": 64,
    "bx-alt": 64,
    "bx-fix": 32,
    "b1": 96,
    "bb2": 48,
    "g1": 80,
    "d1": 40,
    # Chips only FBNeo's list names (see FBNEO_DISAGREEING). Their sizes are ones MAME's list
    # has no chip of, so a scan that hashed only MAME's sizes would never see them.
    "aw2": 200,
    "aprom": 16,
    "fb1": 72,
}

# (set, attrs, roms, extra xml). Each rom: (name, label|None, extra attrs).
GAMES = [
    (
        "alpha",
        {"description": "Alpha Blaster (World)"},
        [("a1.bin", "a1", {}), ("a2.bin", "a2", {}), ("a3.bin", None, {"status": "nodump"})],
        '<input players="2" control="joy4way" coins="2"/>',
    ),
    (
        "alphab",
        {"description": "Alpha Blaster (bootleg)", "cloneof": "alpha", "romof": "alpha"},
        [
            ("a1.bin", "a1", {"merge": "a1.bin"}),
            ("ab2.bin", "a2", {"merge": "a2.bin"}),  # renamed merge
            ("ab3.bin", "ab3", {}),
        ],
        '<input players="2" buttons="1" control="joy8way" coins="2"/>',
    ),
    (
        "biosx",
        {"description": "BIOS X", "runnable": "no"},
        [
            ("bx-std.bin", "bx-std", {"bios": "std"}),
            ("bx-alt.bin", "bx-alt", {"bios": "alt"}),
            ("bx-fix.bin", "bx-fix", {}),  # BIOS chip without a bios= attribute
        ],
        '<biosset name="std" description="Standard" default="yes"/>'
        '<biosset name="alt" description="Alternate"/>',
    ),
    (
        "beta",
        {"description": "Beta Force", "romof": "biosx"},
        [
            ("bx-std.bin", "bx-std", {"merge": "bx-std.bin", "bios": "std"}),
            ("bx-fix.bin", "bx-fix", {"merge": "bx-fix.bin"}),
            ("b1.bin", "b1", {}),
            ("b1.bin", "b1", {}),  # listed twice, as 71 real games do
        ],
        '<input players="1" buttons="2" control="joy8way" coins="1"/>',
    ),
    (
        "betab",
        {"description": "Beta Force (set 2)", "cloneof": "beta", "romof": "beta"},
        [
            ("bx-std.bin", "bx-std", {"merge": "bx-std.bin", "bios": "std"}),
            ("bx-fix.bin", "bx-fix", {"merge": "bx-fix.bin"}),
            ("b1.bin", "b1", {"merge": "b1.bin"}),
            ("bb2.bin", "bb2", {}),
        ],
        '<input players="1" buttons="2" control="joy8way" coins="1"/>',
    ),
    (
        "gamma",
        {"description": "Gamma Disc"},
        [("g1.bin", "g1", {})],
        '<disk name="gamma" sha1="0000000000000000000000000000000000000000"/>'
        '<input players="1" buttons="1" control="joy4way"/>',
    ),
    (
        "delta",
        {"description": "Delta (no sha1)"},
        [("d1.bin", "d1", {"nosha1": "1"})],
        '<input players="1" buttons="1" control="joy4way"/>',
    ),
]


def label_bytes(label: str) -> bytes:
    seed = hashlib.sha256(label.encode()).digest()
    size = CHIPS[label]
    return (seed * (size // len(seed) + 1))[:size]


def _rom_xml(name: str, label: str | None, extra: dict) -> str:
    attrs = {"name": name}
    extra = dict(extra)
    nosha1 = extra.pop("nosha1", None)
    if label is None:
        attrs["size"] = "1024"
    else:
        data = label_bytes(label)
        attrs["size"] = str(len(data))
        attrs["crc"] = f"{zlib.crc32(data):08x}"
        if not nosha1:
            attrs["sha1"] = hashlib.sha1(data).hexdigest()
    attrs.update(extra)
    body = " ".join(f"{k}={quoteattr(v)}" for k, v in attrs.items())
    return f"<rom {body}/>"


def dat_xml() -> str:
    parts = ['<?xml version="1.0"?>', "<mame>"]
    for name, attrs, roms, extra in GAMES:
        game_attrs = {"name": name}
        for key in ("cloneof", "romof", "runnable"):
            if key in attrs:
                game_attrs[key] = attrs[key]
        head = " ".join(f"{k}={quoteattr(v)}" for k, v in game_attrs.items())
        parts.append(f"<game {head}>")
        parts.append(f"<description>{attrs['description']}</description>")
        parts.append("<year>1982</year><manufacturer>Test</manufacturer>")
        parts.extend(_rom_xml(*r) for r in roms)
        parts.append(extra)
        parts.append("</game>")
    parts.append("</mame>")
    return "\n".join(parts)


def chips_for(set_name: str) -> dict[str, bytes]:
    """Every chip a set lists, keyed by its member name (duplicates collapse)."""
    for name, _attrs, roms, _extra in GAMES:
        if name == set_name:
            return {rom: label_bytes(label) for rom, label, _x in roms if label is not None}
    raise KeyError(set_name)


def make_zip(path: Path, members: dict[str, bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


def _rom_xml_fbneo(name: str, label: str | None, extra: dict) -> str:
    """Generate ROM XML for FBNeo DAT (no sha1 attribute)."""
    attrs = {"name": name}
    extra = dict(extra)
    extra.pop("nosha1", None)  # Ignore for FBNeo (never has sha1)
    extra.pop("bios", None)  # FBNeo doesn't use bios attribute on roms
    if label is None:
        attrs["size"] = "1024"
    else:
        data = label_bytes(label)
        attrs["size"] = str(len(data))
        attrs["crc"] = f"{zlib.crc32(data):08x}"
        # No sha1 for FBNeo
    attrs.update(extra)
    body = " ".join(f"{k}={quoteattr(v)}" for k, v in attrs.items())
    return f"<rom {body}/>"


def fbneo_dat_xml(games: list = GAMES) -> str:
    """Generate a FBNeo-format DAT with isbios attribute."""
    parts = [
        '<?xml version="1.0"?>',
        '<!DOCTYPE datafile PUBLIC "-//FinalBurn Neo//DTD ROM Management Datafile//EN"'
        ' "http://www.logiqx.com/Dats/datafile.dtd">',
        "<datafile>",
        "<header>",
        "<name>Test FBNeo</name>",
        "<description>Test FBNeo DAT</description>",
        "<version>1.0</version>",
        "</header>",
    ]
    for name, attrs, roms, _extra in games:
        game_attrs = {"name": name}
        # Map MAME attributes to FBNeo
        if "runnable" in attrs and attrs["runnable"] == "no":
            game_attrs["isbios"] = "yes"
        for key in ("cloneof", "romof"):
            if key in attrs:
                game_attrs[key] = attrs[key]
        head = " ".join(f"{k}={quoteattr(v)}" for k, v in game_attrs.items())
        parts.append(f"<game {head}>")
        parts.append(f"<description>{attrs['description']}</description>")
        parts.append("<year>1982</year><manufacturer>Test</manufacturer>")
        parts.extend(_rom_xml_fbneo(*r) for r in roms)
        # Add comment for BIOS sets (FBNeo-specific)
        if "runnable" in attrs and attrs["runnable"] == "no":
            parts.append("<comment>BIOS only</comment>")
        parts.append("</game>")
    parts.append("</datafile>")
    return "\n".join(parts)


@pytest.fixture
def synthetic_dat(tmp_path) -> Path:
    path = tmp_path / "dat.xml"
    path.write_text(dat_xml())
    return path


@pytest.fixture
def synthetic_fbneo_dat(tmp_path) -> Path:
    path = tmp_path / "fbneo.xml"
    path.write_text(fbneo_dat_xml())
    return path


# FBNeo's list where it disagrees with MAME 2003-Plus's, as it does over Heavy Barrel:
# - `alpha` is a name both lists use for different contents (here FBNeo's needs aw2, a chip
#   MAME's list has never heard of, where MAME's needs a2);
# - `alphaua` is MAME's `alpha` under another set name and other ROM names, plus a PROM FBNeo
#   can run without (FBNEO_OPTIONAL);
# - `biosx` is a BIOS here too, and `betafb` needs it; `fbonly` is a game only FBNeo has.
FBNEO_DISAGREEING = [
    (
        "alpha",
        {"description": "Alpha Blaster (World)"},
        [("a1.bin", "a1", {}), ("aw2.bin", "aw2", {})],
        "",
    ),
    (
        "alphaua",
        {"description": "Alpha Blaster (US)", "cloneof": "alpha", "romof": "alpha"},
        [
            ("ua-1.rom", "a1", {"merge": "a1.bin"}),
            ("ua-2.rom", "a2", {}),
            ("ua-prom.bin", "aprom", {}),
        ],
        "",
    ),
    (
        "biosx",
        {"description": "BIOS X", "runnable": "no"},
        [("bx-std.bin", "bx-std", {}), ("bx-fix.bin", "bx-fix", {})],
        "",
    ),
    (
        "betafb",
        {"description": "Beta Force (FBNeo)", "romof": "biosx"},
        [
            ("bx-std.bin", "bx-std", {"merge": "bx-std.bin"}),
            ("bx-fix.bin", "bx-fix", {"merge": "bx-fix.bin"}),
            ("fb-b1.bin", "b1", {}),
        ],
        "",
    ),
    ("fbonly", {"description": "Only In FBNeo"}, [("fbo.bin", "fb1", {})], ""),
]
FBNEO_OPTIONAL = {"alphaua": ["aprom"]}  # set -> labels of the ROMs it can run without


def fbneo_chips_for(set_name: str) -> dict[str, bytes]:
    """Every chip an FBNEO_DISAGREEING set lists, keyed by FBNeo's member names."""
    for name, _attrs, roms, _extra in FBNEO_DISAGREEING:
        if name == set_name:
            return {rom: label_bytes(label) for rom, label, _x in roms}
    raise KeyError(set_name)


@pytest.fixture
def disagreeing_fbneo_dat(tmp_path) -> Path:
    path = tmp_path / "fbneo-disagreeing.dat"
    path.write_text(fbneo_dat_xml(FBNEO_DISAGREEING))
    return path


@pytest.fixture
def fbneo_optional_json(tmp_path) -> Path:
    path = tmp_path / "fbneo-optional.json"
    crcs = {
        name: [f"{zlib.crc32(label_bytes(label)):08x}" for label in labels]
        for name, labels in FBNEO_OPTIONAL.items()
    }
    path.write_text(json.dumps(crcs))
    return path
