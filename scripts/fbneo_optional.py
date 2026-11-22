"""Extract optional ROM CRCs from FBNeo arcade driver sources.

Reads an FBNeo source checkout and writes a JSON file mapping set names to
lists of optional ROM CRCs (from entries flagged BRF_OPT in ROM tables).

Usage:
    uv run python scripts/fbneo_optional.py <path-to-fbneo-checkout> [-o OUTPUT]

Deterministic output: keys and CRC lists are sorted, two-space indentation,
trailing newline. Sets with no optional ROMs are omitted. ROMs flagged
BRF_NODUMP or with CRC 0 are omitted.

Tested against FBNeo commit 3f0de7fefbb7cc4b46e832647215cbe41eaf37b0.
"""

import argparse
import json
import re
import sys
from pathlib import Path

_STRING_OR_COMMENT = re.compile(r'"(?:\\.|[^"\\\n])*"|/\*.*?\*/|//[^\n]*', re.DOTALL)


def strip_comments(text: str) -> str:
    """Remove // and /* */ comments from C++ code, whichever opens first, leaving strings alone.

    One pass in source order: a `//` inside a block comment must not eat that comment's `*/`,
    and comment markers inside a string literal are not comments.
    """
    return _STRING_OR_COMMENT.sub(lambda m: m[0] if m[0].startswith('"') else " ", text)


def find_rom_tables(text: str) -> list[dict]:
    """Find all ROM table definitions in C++ code.

    Returns list of dicts with 'name' (e.g. 'Hbarrelua') and 'content'.
    """
    # Pattern: static struct BurnRomInfo NameRomDesc[] = { ... };
    pattern = r"static\s+struct\s+BurnRomInfo\s+(\w+?)RomDesc\s*\[\s*\]\s*=\s*\{(.*?)\n\};"
    tables = []
    for match in re.finditer(pattern, text, re.DOTALL):
        name = match.group(1)
        content = match.group(2)
        tables.append({"name": name, "content": content})
    return tables


def parse_rom_entries(table_content: str) -> list[dict]:
    """Parse ROM entries from a table content.

    Each entry is a dict with: name, size (hex), crc (hex), flags (str),
    is_optional (bool), is_nodump (bool).
    """
    # Strip comments first
    content = strip_comments(table_content)

    # Pattern for a ROM entry: { "name", 0xsize, 0xcrc, flags }
    # Flags can be combinations like BRF_ESS | BRF_PRG or just BRF_OPT
    pattern = (
        r'\{\s*"([^"]*)"\s*,\s*(0x[0-9a-fA-F]+|\d+)\s*,\s*(0x[0-9a-fA-F]+|\d+)\s*,\s*([^}]*)\}'
    )

    entries = []
    for match in re.finditer(pattern, content):
        name = match.group(1)
        size_str = match.group(2)
        crc_str = match.group(3)
        flags_str = match.group(4).strip()

        # Skip empty terminator entries
        if name == "" and crc_str in ("0", "0x0"):
            entries.append(
                {
                    "name": "",
                    "size": 0,
                    "crc": "00000000",
                    "flags": "",
                    "is_optional": False,
                    "is_nodump": False,
                }
            )
            continue

        # Parse CRC (convert to 8-digit lowercase hex)
        crc_int = int(crc_str, 0)
        crc = f"{crc_int:08x}"

        is_optional = "BRF_OPT" in flags_str
        is_nodump = "BRF_NODUMP" in flags_str

        entries.append(
            {
                "name": name,
                "size": int(size_str, 0),
                "crc": crc,
                "flags": flags_str,
                "is_optional": is_optional,
                "is_nodump": is_nodump,
            }
        )

    return entries


def find_burn_drivers(text: str) -> list[dict]:
    """Find all BurnDriver structs and extract set names and ROM table references.

    Returns list of dicts with: set_name, parent_name (or None), rom_table_name.
    """
    # Pattern: struct BurnDriver[D|X]? BurnDrv<ident> = { "setname", ... RomInfo, ... };
    pattern = r"struct\s+BurnDriver[DX]?\s+BurnDrv\w+\s*=\s*\{\s*\"([^\"]+)\"(.*?)\n\};"

    drivers = []
    for match in re.finditer(pattern, text, re.DOTALL):
        set_name = match.group(1)
        body = match.group(2)

        # Look for RomInfo reference in the struct body: SomeRomInfo
        rom_match = re.search(r"\b(\w+?)RomInfo\b", body)
        if rom_match:
            rom_table_name = rom_match.group(1)
            drivers.append({"set_name": set_name, "rom_table_name": rom_table_name})

    return drivers


def extract_optional_roms_from_text(text: str) -> dict[str, list[str]]:
    """Extract optional ROM CRCs from C++ source code.

    Returns dict mapping set names to sorted lists of lowercase 8-hex CRCs.
    Sets with no optional ROMs are omitted.
    """
    # Strip comments
    text = strip_comments(text)

    # Find all ROM tables
    tables = find_rom_tables(text)
    table_map = {}  # name -> list of optional CRCs
    for table in tables:
        entries = parse_rom_entries(table["content"])
        # Collect CRCs that are: optional, not NODUMP, not 0
        crcs = set()
        for entry in entries:
            if entry["is_optional"] and not entry["is_nodump"] and entry["crc"] != "00000000":
                crcs.add(entry["crc"])
        if crcs:
            table_map[table["name"]] = sorted(crcs)

    # Find all drivers and map them to ROM tables
    drivers = find_burn_drivers(text)
    result = {}
    for driver in drivers:
        rom_table_name = driver["rom_table_name"]
        set_name = driver["set_name"]
        if rom_table_name in table_map:
            result[set_name] = table_map[rom_table_name]

    return result


def extract_optional_roms_from_file(filepath: Path) -> dict[str, list[str]]:
    """Extract optional ROMs from a single C++ source file."""
    try:
        # Use latin-1 encoding to handle various FBNeo source files
        text = filepath.read_text(encoding="latin-1")
    except (UnicodeDecodeError, FileNotFoundError):
        return {}

    return extract_optional_roms_from_text(text)


def process_fbneo_checkout(fbneo_path: Path) -> tuple[dict[str, list[str]], int]:
    """Process all driver files in an FBNeo checkout.

    Returns (result_dict, driver_file_count).
    """
    drv_dir = fbneo_path / "src" / "burn" / "drv"

    if not drv_dir.is_dir():
        raise ValueError(f"No src/burn/drv directory found at {fbneo_path}")

    # Find all d_*.cpp files
    driver_files = sorted(drv_dir.rglob("d_*.cpp"))

    if not driver_files:
        raise ValueError(f"No driver files (d_*.cpp) found under {drv_dir}")

    result = {}
    file_count = 0

    for filepath in driver_files:
        file_count += 1
        roms_in_file = extract_optional_roms_from_file(filepath)
        result.update(roms_in_file)

    return result, file_count


def generate_json_output(data: dict[str, list[str]]) -> str:
    """Generate deterministic JSON output.

    Keys and CRC lists are sorted, two-space indentation, trailing newline.
    """
    # Sort keys and ensure CRC lists are sorted
    sorted_data = {k: sorted(v) for k, v in sorted(data.items())}
    output = json.dumps(sorted_data, indent=2, ensure_ascii=True)
    if not output.endswith("\n"):
        output += "\n"
    return output


def validate_fbneo_checkout(fbneo_path: Path) -> bool:
    """Check if the given path is a valid FBNeo checkout."""
    drv_dir = fbneo_path / "src" / "burn" / "drv"
    return drv_dir.is_dir()


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Extract optional ROM CRCs from FBNeo source.")
    parser.add_argument("fbneo_path", type=Path, help="Path to FBNeo checkout")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output file (default: stdout)",
    )
    args = parser.parse_args()

    fbneo_path = args.fbneo_path.expanduser()

    # Validate checkout
    if not validate_fbneo_checkout(fbneo_path):
        print(
            f"ERROR: No src/burn/drv directory found at {fbneo_path}",
            file=sys.stderr,
        )
        return 1

    try:
        result, file_count = process_fbneo_checkout(fbneo_path)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if not result:
        print(
            "ERROR: No ROM tables found in source; a valid FBNeo checkout "
            "must contain ROM definitions",
            file=sys.stderr,
        )
        return 1

    # Generate output
    output = generate_json_output(result)

    # Write output
    if args.output:
        args.output.write_text(output)
    else:
        print(output, end="")

    # Print summary to stderr
    total_opts = sum(len(v) for v in result.values())
    print(
        f"Read {file_count} driver files; found {len(result)} sets with "
        f"{total_opts} optional ROM entries",
        file=sys.stderr,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
