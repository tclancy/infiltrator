"""A tiny DAT in the real DAT's shape, with real hashes over junk bytes.

No ROM content is involved: every chip is sha256(label) repeated to size, so
fixtures can be generated at test time and nothing is forged or committed.
"""

import hashlib
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


@pytest.fixture
def synthetic_dat(tmp_path) -> Path:
    path = tmp_path / "dat.xml"
    path.write_text(dat_xml())
    return path
