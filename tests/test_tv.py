from infiltrator.catalogue import connect
from infiltrator.catalogue.tv import set_tv_persona, tv_persona


def test_no_tv_persona_until_one_is_set(tmp_path):
    assert tv_persona(connect(tmp_path / "c.db")) is None


def test_setting_the_tv_persona_replaces_the_last(tmp_path):
    conn = connect(tmp_path / "c.db")
    set_tv_persona(conn, "solo")
    set_tv_persona(conn, "party")
    assert tv_persona(conn) == "party"
    assert conn.execute("SELECT COUNT(*) FROM tv").fetchone()[0] == 1
