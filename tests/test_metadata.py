from infiltrator.dat import load_dat
from infiltrator.metadata import load_metadata, parse_renames
from infiltrator.names import title

HEADER = "[FOLDER_SETTINGS]\nRootFolderIcon mame\n\n;; comment ;;\n\n[ROOT_FOLDER]\n\n"


def write(meta, name, body):
    meta.mkdir(exist_ok=True)
    (meta / name).write_text(HEADER + body)


def test_mature_flag_and_genre(tmp_path, synthetic_dat):
    meta = tmp_path / "meta"
    write(meta, "catver.ini", "[Category]\nalpha=Shooter / Flying * Mature *\ndelta=Maze\n")
    m = load_metadata(meta, load_dat(synthetic_dat))
    assert (m["alpha"].genre, m["alpha"].mature) == ("Shooter / Flying", True)
    assert m["delta"].mature is False


def test_language_section(tmp_path, synthetic_dat):
    meta = tmp_path / "meta"
    write(meta, "languages.ini", "[English]\nalpha\n\n[Japanese]\nalphab\n")
    m = load_metadata(meta, load_dat(synthetic_dat))
    assert m["alpha"].language == "English"
    assert m["alphab"].language == "Japanese"


def test_bestgames_tier(tmp_path, synthetic_dat):
    meta = tmp_path / "meta"
    write(meta, "bestgames.ini", "[90 to 100 (Best Games)]\nalpha\n\n[0 to 10 (Worst)]\ndelta\n")
    m = load_metadata(meta, load_dat(synthetic_dat))
    assert (m["alpha"].quality_tier, m["delta"].quality_tier) == (9, 0)


def test_nplayers_values(tmp_path, synthetic_dat):
    meta = tmp_path / "meta"
    write(meta, "nplayers.ini", "[NPlayers]\nalpha=2P alt\ndelta=???\n")
    m = load_metadata(meta, load_dat(synthetic_dat))
    assert m["alpha"].players == "2P alt"
    assert m["delta"].players is None


def test_clone_inherits_tier_genre_players_not_language(tmp_path, synthetic_dat):
    meta = tmp_path / "meta"
    write(meta, "catver.ini", "[Category]\nalpha=Shooter\n")
    write(meta, "bestgames.ini", "[80 to 90 (Very Good)]\nalpha\n")
    write(meta, "nplayers.ini", "[NPlayers]\nalpha=2P alt\n")
    write(meta, "languages.ini", "[English]\nalpha\n")
    clone = load_metadata(meta, load_dat(synthetic_dat))["alphab"]
    assert (clone.genre, clone.quality_tier, clone.players) == ("Shooter", 8, "2P alt")
    assert clone.language is None


def test_rename_chain_resolves_in_version_order(tmp_path):
    ini = tmp_path / "renameSET.ini"
    ini.write_text("[0.200]\nRen_001=b   > c\n\n[0.100]\nRen_001=a > b\n")
    assert parse_renames(ini, {"a"}) == {"a": "c"}


def test_swap_within_a_version_is_simultaneous(tmp_path):
    ini = tmp_path / "renameSET.ini"
    ini.write_text("[0.100]\nRen_001=x > y\nRen_002=y > x\n")
    assert parse_renames(ini, {"x", "y"}) == {"x": "y", "y": "x"}


def test_renames_before_the_dat_version_are_ignored(tmp_path):
    ini = tmp_path / "renameSET.ini"
    ini.write_text("[0.37b1]\nRen_001=pacman > puckman\n\n[0.78]\nRen_001=a > b\n")
    assert parse_renames(ini, {"pacman", "a"}) == {}


def test_renamed_set_uses_modern_entry(tmp_path, synthetic_dat):
    meta = tmp_path / "meta"
    write(meta, "renameSET.ini", "[0.150]\nRen_001=delta > deltanew\n")
    write(meta, "catver.ini", "[Category]\ndeltanew=Puzzle\ndelta=Wrong / Reused name\n")
    assert load_metadata(meta, load_dat(synthetic_dat))["delta"].genre == "Puzzle"


def test_missing_files_give_none(tmp_path, synthetic_dat):
    m = load_metadata(tmp_path / "nothing", load_dat(synthetic_dat))
    assert m["alpha"].language is None
    assert m["alpha"].quality_tier is None


def test_title_strips_parentheticals():
    assert title("Pac-Man (Midway)") == "Pac-Man"
    assert title("1942 (set 2)") == "1942"
    assert title("Heavy Barrel (World) (bootleg)") == "Heavy Barrel"
    assert title("Q*bert") == "Q*bert"


def test_renamed_set_without_modern_entry_falls_back_to_old_name(tmp_path, synthetic_dat):
    meta = tmp_path / "meta"
    write(meta, "renameSET.ini", "[0.150]\nRen_001=alpha > alphaold\n")
    write(meta, "bestgames.ini", "[70 to 80 (Good)]\nalpha\n")
    assert load_metadata(meta, load_dat(synthetic_dat))["alpha"].quality_tier == 7
