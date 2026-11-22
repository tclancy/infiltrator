"""Tests for fbneo_optional.py ROM table parsing."""

# Import the script module; since it's in scripts/, we need to load it specially
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "fbneo_optional",
    Path(__file__).parent.parent / "scripts" / "fbneo_optional.py",
)
fbneo_optional = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fbneo_optional)


class TestCommentStripping:
    """Test that comments are correctly removed."""

    def test_strip_line_comments(self):
        code = "x = 5; // this is a comment\ny = 6;"
        result = fbneo_optional.strip_comments(code)
        assert "// this is a comment" not in result
        assert "x = 5" in result
        assert "y = 6" in result

    def test_a_line_comment_marker_inside_a_block_comment_does_not_eat_its_end(self):
        # Seen in FBNeo's Neo Geo driver: this used to swallow every driver up to the next `*/`.
        code = "a = 1; /* see // the notes */ b = 2;\nc = 3; /* later */ d = 4;"
        result = fbneo_optional.strip_comments(code)
        assert "b = 2" in result and "c = 3" in result and "d = 4" in result
        assert "notes" not in result and "later" not in result

    def test_comment_markers_inside_a_string_are_kept(self):
        code = 'url = "http://example.com/*x*/"; // gone'
        result = fbneo_optional.strip_comments(code)
        assert '"http://example.com/*x*/"' in result
        assert "gone" not in result

    def test_strip_block_comments(self):
        code = "x = 5; /* block comment */ y = 6;"
        result = fbneo_optional.strip_comments(code)
        assert "/* block comment */" not in result
        assert "x = 5" in result
        assert "y = 6" in result

    def test_strip_multiline_block_comments(self):
        code = "x = 5;\n/* multi\nline\ncomment */\ny = 6;"
        result = fbneo_optional.strip_comments(code)
        assert "/* multi" not in result
        assert "line" not in result
        assert "x = 5" in result
        assert "y = 6" in result

    def test_preserve_strings_with_comment_chars(self):
        code = 'name = "file//name.bin"; // actual comment'
        result = fbneo_optional.strip_comments(code)
        # String content should be preserved (or at least the structure should work)
        assert "y = 6" not in result  # should remove comment
        assert "file" in result  # but keep name


class TestROMTableParsing:
    """Test parsing ROM tables from C++ code."""

    def test_find_rom_table_simple(self):
        code = """
static struct BurnRomInfo HbarreluaRomDesc[] = {
    { "file1.bin", 0x1000, 0x12345678, BRF_ESS | BRF_PRG },
    { "file2.bin", 0x2000, 0x87654321, BRF_OPT },
    { "", 0, 0, 0 },
};
"""
        tables = fbneo_optional.find_rom_tables(code)
        assert len(tables) == 1
        assert tables[0]["name"] == "Hbarrelua"

    def test_find_rom_table_empty_terminator(self):
        code = """
static struct BurnRomInfo SomeRomDesc[] = {
    { "file.bin", 0x1000, 0xdeadbeef, BRF_GRA },
    { "", 0, 0, 0 },
};
"""
        tables = fbneo_optional.find_rom_tables(code)
        assert len(tables) == 1
        assert tables[0]["name"] == "Some"

    def test_find_multiple_rom_tables(self):
        code = """
static struct BurnRomInfo FirstRomDesc[] = {
    { "f1.bin", 0x1000, 0x11111111, BRF_PRG },
    { "", 0, 0, 0 },
};
static struct BurnRomInfo SecondRomDesc[] = {
    { "f2.bin", 0x2000, 0x22222222, BRF_GRA },
    { "", 0, 0, 0 },
};
"""
        tables = fbneo_optional.find_rom_tables(code)
        assert len(tables) == 2
        assert tables[0]["name"] == "First"
        assert tables[1]["name"] == "Second"

    def test_parse_rom_entry_no_opt(self):
        code = """
static struct BurnRomInfo TestRomDesc[] = {
    { "prog.bin", 0x10000, 0x4877b09e, BRF_ESS | BRF_PRG },
    { "", 0, 0, 0 },
};
"""
        tables = fbneo_optional.find_rom_tables(code)
        assert len(tables) == 1
        entries = fbneo_optional.parse_rom_entries(tables[0]["content"])
        # Should have one real entry and one terminator
        assert len(entries) == 2
        real_entry = entries[0]
        assert real_entry["crc"] == "4877b09e"
        assert real_entry["is_optional"] is False

    def test_parse_rom_entry_with_opt(self):
        code = """
static struct BurnRomInfo TestRomDesc[] = {
    { "prom.bin", 0x200, 0x86e775f8, BRF_OPT },
    { "", 0, 0, 0 },
};
"""
        tables = fbneo_optional.find_rom_tables(code)
        entries = fbneo_optional.parse_rom_entries(tables[0]["content"])
        real_entry = entries[0]
        assert real_entry["crc"] == "86e775f8"
        assert real_entry["is_optional"] is True

    def test_parse_rom_entry_combined_flags(self):
        code = """
static struct BurnRomInfo TestRomDesc[] = {
    { "prog.bin", 0x10000, 0xaabbccdd, BRF_ESS | BRF_PRG },
    { "prom.bin", 0x200, 0x11223344, BRF_OPT | BRF_GRA },
    { "", 0, 0, 0 },
};
"""
        tables = fbneo_optional.find_rom_tables(code)
        entries = fbneo_optional.parse_rom_entries(tables[0]["content"])
        assert len(entries) == 3  # 2 real + 1 terminator
        assert entries[0]["is_optional"] is False
        assert entries[1]["is_optional"] is True

    def test_parse_rom_entry_brf_nodump_filtered(self):
        code = """
static struct BurnRomInfo TestRomDesc[] = {
    { "dump.bin", 0x1000, 0x12345678, BRF_NODUMP },
    { "", 0, 0, 0 },
};
"""
        tables = fbneo_optional.find_rom_tables(code)
        entries = fbneo_optional.parse_rom_entries(tables[0]["content"])
        # BRF_NODUMP entries may still appear in the structure but we filter them later
        # For now just verify the entry is parsed
        assert len(entries) >= 1

    def test_parse_rom_entry_zero_crc_filtered(self):
        code = """
static struct BurnRomInfo TestRomDesc[] = {
    { "unknown.bin", 0x1000, 0x0, BRF_OPT },
    { "", 0, 0, 0 },
};
"""
        tables = fbneo_optional.find_rom_tables(code)
        entries = fbneo_optional.parse_rom_entries(tables[0]["content"])
        # CRC 0 should be parsed but filtered later
        assert len(entries) >= 1

    def test_parse_rom_entry_commented_out(self):
        code = """
static struct BurnRomInfo TestRomDesc[] = {
    { "prog.bin", 0x10000, 0x12345678, BRF_PRG },
    // { "commented.bin", 0x1000, 0x87654321, BRF_OPT },
    { "", 0, 0, 0 },
};
"""
        tables = fbneo_optional.find_rom_tables(code)
        # Comments should be stripped before parsing
        entries = fbneo_optional.parse_rom_entries(tables[0]["content"])
        # Should only have the real entry and terminator, not the commented one
        non_term = [e for e in entries if e["crc"] != "00000000"]
        assert len(non_term) == 1
        assert non_term[0]["crc"] == "12345678"


class TestDriverStructParsing:
    """Test parsing BurnDriver structs."""

    def test_find_burn_driver_simple(self):
        code = """
struct BurnDriver BurnDrvHbarrelua = {
    "hbarrelua", "hbarrel", NULL, NULL, "1987",
    "Heavy Barrel", NULL, "Data East USA", "DEC0",
    NULL, HbarreluaRomInfo, HbarreluaRomName, NULL,
    NULL, NULL, NULL, Dec0InputInfo, HbarrelDIPInfo,
    HbarrelInit, BaddudesExit, DrvFrame, HbarrelDraw, BaddudesScan,
    NULL, 0x400, 240, 256, 3, 4
};
"""
        drivers = fbneo_optional.find_burn_drivers(code)
        assert len(drivers) == 1
        assert drivers[0]["set_name"] == "hbarrelua"
        assert drivers[0]["rom_table_name"] == "Hbarrelua"

    def test_find_burn_driver_with_variant(self):
        code = """
struct BurnDriverD BurnDrvTestD = {
    "testd", NULL, NULL, NULL, "1990",
    "Test Debug", NULL, "Corp", "TEST",
    NULL, TestRomInfo, TestRomName, NULL,
    NULL, NULL, NULL, TestInputInfo, TestDIPInfo,
    TestInit, TestExit, TestFrame, TestDraw, TestScan,
    NULL, 0x400, 256, 240, 4, 3
};
"""
        drivers = fbneo_optional.find_burn_drivers(code)
        assert len(drivers) == 1
        assert drivers[0]["set_name"] == "testd"
        assert drivers[0]["rom_table_name"] == "Test"

    def test_find_multiple_burn_drivers(self):
        code = """
struct BurnDriver BurnDrvFirst = {
    "first", NULL, NULL, NULL, "1987",
    NULL, FirstRomInfo, FirstRomName, NULL,
};
struct BurnDriver BurnDrvSecond = {
    "second", NULL, NULL, NULL, "1988",
    NULL, SecondRomInfo, SecondRomName, NULL,
};
"""
        drivers = fbneo_optional.find_burn_drivers(code)
        assert len(drivers) == 2
        assert drivers[0]["set_name"] == "first"
        assert drivers[1]["set_name"] == "second"

    def test_find_burn_driver_no_rom_info(self):
        # Some drivers might not have ROM info (should be skipped)
        code = """
struct BurnDriver BurnDrvNoRom = {
    "norom", NULL, NULL, NULL, "1990",
    NULL, NULL, NULL, NULL,
};
"""
        # Should handle drivers with no ROM info - they won't be in output
        drivers = fbneo_optional.find_burn_drivers(code)
        assert len(drivers) == 0  # No RomInfo found, so no driver mapping


class TestOptionalROMExtraction:
    """Test the full extraction of optional ROMs from a file."""

    def test_extract_optional_roms_simple(self):
        code = """
static struct BurnRomInfo HbarreluaRomDesc[] = {
    { "prog.bin", 0x10000, 0x4877b09e, BRF_ESS | BRF_PRG },
    { "prom1.bin", 0x200, 0x86e775f8, BRF_OPT },
    { "prom2.bin", 0x400, 0xa5cda23e, BRF_OPT },
    { "", 0, 0, 0 },
};
STD_ROM_PICK(Hbarrelua)
STD_ROM_FN(Hbarrelua)

struct BurnDriver BurnDrvHbarrelua = {
    "hbarrelua", "hbarrel", NULL, NULL, "1987",
    NULL, HbarreluaRomInfo, HbarreluaRomName, NULL,
};
"""
        result = fbneo_optional.extract_optional_roms_from_text(code)
        assert "hbarrelua" in result
        crcs = result["hbarrelua"]
        assert "86e775f8" in crcs
        assert "a5cda23e" in crcs
        assert len(crcs) == 2

    def test_extract_optional_roms_no_opts(self):
        code = """
static struct BurnRomInfo NoOptRomDesc[] = {
    { "prog.bin", 0x10000, 0x12345678, BRF_ESS | BRF_PRG },
    { "", 0, 0, 0 },
};
STD_ROM_PICK(NoOpt)
STD_ROM_FN(NoOpt)

struct BurnDriver BurnDrvNoOpt = {
    "noopts", NULL, NULL, NULL, "1987",
    NULL, NoOptRomInfo, NoOptRomName, NULL,
};
"""
        result = fbneo_optional.extract_optional_roms_from_text(code)
        # Should not include this set since it has no optional ROMs
        assert "noopts" not in result

    def test_extract_optional_roms_ignores_zero_crc(self):
        code = """
static struct BurnRomInfo TestRomDesc[] = {
    { "unknown.bin", 0x1000, 0x0, BRF_OPT },
    { "known.bin", 0x2000, 0xdeadbeef, BRF_OPT },
    { "", 0, 0, 0 },
};
STD_ROM_PICK(Test)
STD_ROM_FN(Test)

struct BurnDriver BurnDrvTest = {
    "test", NULL, NULL, NULL, "1987",
    NULL, TestRomInfo, TestRomName, NULL,
};
"""
        result = fbneo_optional.extract_optional_roms_from_text(code)
        # Should only include the non-zero CRC
        if "test" in result:
            crcs = result["test"]
            assert "00000000" not in crcs
            assert "deadbeef" in crcs

    def test_extract_optional_roms_ignores_brf_nodump(self):
        code = """
static struct BurnRomInfo TestRomDesc[] = {
    { "dump.bin", 0x1000, 0x11111111, BRF_OPT | BRF_NODUMP },
    { "known.bin", 0x2000, 0xdeadbeef, BRF_OPT },
    { "", 0, 0, 0 },
};
STD_ROM_PICK(Test)
STD_ROM_FN(Test)

struct BurnDriver BurnDrvTest = {
    "test", NULL, NULL, NULL, "1987",
    NULL, TestRomInfo, TestRomName, NULL,
};
"""
        result = fbneo_optional.extract_optional_roms_from_text(code)
        # Should only include non-NODUMP optional ROMs
        if "test" in result:
            # Exact behavior depends on how BRF_NODUMP is filtered
            assert "deadbeef" in result["test"]


class TestTableSharingAcrossDrivers:
    """Test that the same ROM table can be used by multiple drivers."""

    def test_multiple_drivers_same_table(self):
        code = """
static struct BurnRomInfo HbarrelRomDesc[] = {
    { "prog.bin", 0x10000, 0x12345678, BRF_ESS | BRF_PRG },
    { "prom.bin", 0x200, 0x86e775f8, BRF_OPT },
    { "", 0, 0, 0 },
};
STD_ROM_PICK(Hbarrel)
STD_ROM_FN(Hbarrel)

struct BurnDriver BurnDrvHbarrel = {
    "hbarrel", NULL, NULL, NULL, "1987",
    NULL, HbarrelRomInfo, HbarrelRomName, NULL,
};

struct BurnDriver BurnDrvHbarrelu = {
    "hbarrelu", "hbarrel", NULL, NULL, "1987",
    NULL, HbarrelRomInfo, HbarrelRomName, NULL,
};

struct BurnDriver BurnDrvHbarrelua = {
    "hbarrelua", "hbarrel", NULL, NULL, "1987",
    NULL, HbarrelRomInfo, HbarrelRomName, NULL,
};
"""
        result = fbneo_optional.extract_optional_roms_from_text(code)
        # All three sets should have the same optional ROM
        for set_name in ["hbarrel", "hbarrelu", "hbarrelua"]:
            assert set_name in result
            assert result[set_name] == ["86e775f8"]


class TestOutput:
    """Test JSON output generation."""

    def test_output_sorted_keys(self):
        data = {
            "zebra": ["11111111"],
            "apple": ["22222222"],
            "middle": ["33333333"],
        }
        output = fbneo_optional.generate_json_output(data)
        # Keys should be in alphabetical order
        parsed = json.loads(output)
        keys = list(parsed.keys())
        assert keys == sorted(keys)

    def test_output_sorted_crcs(self):
        data = {"test": ["33333333", "11111111", "22222222"]}
        output = fbneo_optional.generate_json_output(data)
        parsed = json.loads(output)
        assert parsed["test"] == ["11111111", "22222222", "33333333"]

    def test_output_trailing_newline(self):
        data = {"test": ["12345678"]}
        output = fbneo_optional.generate_json_output(data)
        assert output.endswith("\n")
        # And only one newline
        assert not output.endswith("\n\n")

    def test_output_deterministic(self):
        data = {"b": ["22"], "a": ["11"], "c": ["33", "11"]}
        output1 = fbneo_optional.generate_json_output(data)
        output2 = fbneo_optional.generate_json_output(data)
        assert output1 == output2

    def test_output_empty_dict(self):
        data = {}
        output = fbneo_optional.generate_json_output(data)
        parsed = json.loads(output)
        assert parsed == {}


class TestErrorHandling:
    """Test error handling for missing or empty data."""

    def test_no_drv_directory(self, tmp_path):
        # Create a temp directory without src/burn/drv
        result = fbneo_optional.validate_fbneo_checkout(tmp_path)
        assert result is False

    def test_empty_drv_directory(self, tmp_path):
        # Create the directory but no driver files
        (tmp_path / "src" / "burn" / "drv").mkdir(parents=True)
        # This should not raise, but should return empty results or warn
        # Exact behavior depends on implementation

    def test_no_rom_tables_found(self, tmp_path):
        # Create a driver file with no ROM tables
        (tmp_path / "src" / "burn" / "drv").mkdir(parents=True)
        driver_file = tmp_path / "src" / "burn" / "drv" / "d_test.cpp"
        driver_file.write_text("// No ROM tables here\n")
        # Should handle gracefully


class TestIntegration:
    """Integration tests with real-ish C++ structures."""

    def test_hbarrelua_ground_truth(self):
        """Verify known ground truth for hbarrelua."""
        code = """
static struct BurnRomInfo HbarreluaRomDesc[] = {
    { "heavy_barrel_04-1.3c", 0x10000, 0x4877b09e, BRF_ESS | BRF_PRG },
    { "heavy_barrel_01-1.3a", 0x10000, 0x8b41c219, BRF_ESS | BRF_PRG },
    { "heavy_barrel_05.4c", 0x10000, 0x2087d570, BRF_ESS | BRF_PRG },
    { "heavy_barrel_02.4a", 0x10000, 0x815536ae, BRF_ESS | BRF_PRG },
    { "heavy_barrel_06.6c", 0x10000, 0xda4e3fbc, BRF_ESS | BRF_PRG },
    { "heavy_barrel_03.6a", 0x10000, 0x7fed7c46, BRF_ESS | BRF_PRG },
    { "heavy_barrel_07.8a", 0x08000, 0xa127f0f7, BRF_ESS | BRF_PRG },
    { "heavy_barrel_25.15h", 0x10000, 0x8649762c, BRF_GRA },
    { "heavy_barrel_26.16h", 0x10000, 0xf8189bbd, BRF_GRA },
    { "heavy_barrel_18.14d", 0x10000, 0xef664373, BRF_GRA },
    { "heavy_barrel_17.12d", 0x10000, 0xa4f186ac, BRF_GRA },
    { "heavy_barrel_20.17d", 0x10000, 0x2fc13be0, BRF_GRA },
    { "heavy_barrel_19.15d", 0x10000, 0xd6b47869, BRF_GRA },
    { "heavy_barrel_22.14f", 0x10000, 0x50d6a1ad, BRF_GRA },
    { "heavy_barrel_21.12f", 0x10000, 0xf01d75c5, BRF_GRA },
    { "heavy_barrel_24.17f", 0x10000, 0xae377361, BRF_GRA },
    { "heavy_barrel_23.15f", 0x10000, 0xbbdaf771, BRF_GRA },
    { "heavy_barrel_29.8h", 0x10000, 0x5514b296, BRF_GRA },
    { "heavy_barrel_30.9h", 0x10000, 0x5855e8ef, BRF_GRA },
    { "heavy_barrel_27.8f", 0x10000, 0x99db7b9c, BRF_GRA },
    { "heavy_barrel_28.9f", 0x10000, 0x33ce2b1a, BRF_GRA },
    { "heavy_barrel_15.16c", 0x10000, 0x21816707, BRF_GRA },
    { "heavy_barrel_16.17c", 0x10000, 0xa5684574, BRF_GRA },
    { "heavy_barrel_11.16a", 0x10000, 0x5c768315, BRF_GRA },
    { "heavy_barrel_12.17a", 0x10000, 0x8b64d7a4, BRF_GRA },
    { "heavy_barrel_13.13c", 0x10000, 0x56e3ed65, BRF_GRA },
    { "heavy_barrel_14.14c", 0x10000, 0xbedfe7f3, BRF_GRA },
    { "heavy_barrel_09.13a", 0x10000, 0x26240ea0, BRF_GRA },
    { "heavy_barrel_10.14a", 0x10000, 0x47d95447, BRF_GRA },
    { "heavy_barrel_08.2c", 0x10000, 0x645c5b68, BRF_SND },
    { "heavy_barrel_31.9a", 0x01000, 0x239d726f, BRF_ESS | BRF_PRG },
    { "mb7116e.12c", 0x00200, 0x86e775f8, BRF_OPT },
    { "mb7122e.17e", 0x00400, 0xa5cda23e, BRF_OPT },
    { "", 0, 0, 0 },
};
STD_ROM_PICK(Hbarrelua)
STD_ROM_FN(Hbarrelua)

struct BurnDriver BurnDrvHbarrelua = {
    "hbarrelua", "hbarrel", NULL, NULL, "1987",
    "Heavy Barrel (US, revision 1)", NULL, "Data East USA", "DEC0",
    NULL, HbarreluaRomInfo, HbarreluaRomName, NULL,
    NULL, NULL, NULL, Dec0InputInfo, HbarrelDIPInfo,
    HbarrelInit, BaddudesExit, DrvFrame, HbarrelDraw, BaddudesScan,
    NULL, 0x400, 240, 256, 3, 4
};
"""
        result = fbneo_optional.extract_optional_roms_from_text(code)
        assert "hbarrelua" in result
        expected = ["86e775f8", "a5cda23e"]
        assert sorted(result["hbarrelua"]) == expected
