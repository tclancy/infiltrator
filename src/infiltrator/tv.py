"""Put the TV persona's shelf in RomM's folders and tell RomM about it."""

import sqlite3

from infiltrator.catalogue.tv import romm_pending, set_romm_pending, tv_persona
from infiltrator.config import Settings
from infiltrator.dat import Dat
from infiltrator.publish import PublishResult, check_folders, locked, publish
from infiltrator.romm import RommClient
from infiltrator.shelf import current_shelf

PLATFORM = "arcade"


def bios_needed(dat: Dat, sets: list[str]) -> list[str]:
    found = {dat.bios_of(dat.games[name]) for name in sets if name in dat.games}
    return sorted(g.name for g in found if g is not None)


def _publishing(settings: Settings) -> bool:
    return settings.shelf_dir is not None and settings.bios_dir is not None


def preflight(settings: Settings) -> None:
    """Raise now, before the shelf changes, if publishing would refuse later."""
    if _publishing(settings):
        check_folders(settings.library_dir, settings.shelf_dir, settings.bios_dir)


def publish_tv(settings: Settings, dat: Dat, conn: sqlite3.Connection) -> PublishResult | None:
    """Make RomM's folders hold the TV persona's shelf; None when there's nothing to publish to."""
    persona = tv_persona(conn)
    if persona is None or not _publishing(settings):
        return None
    sets = [row["set_name"] for row in current_shelf(conn, persona)]
    with locked(settings.db_path.parent / "publish.lock"):
        result = publish(
            settings.library_dir,
            settings.shelf_dir,
            settings.bios_dir,
            sets,
            bios_needed(dat, sets),
        )
    if result.changed:
        set_romm_pending(conn, True)
    return result


def romm_client(settings: Settings) -> RommClient | None:
    if not (settings.romm_url and settings.romm_token):
        return None
    return RommClient(settings.romm_url, settings.romm_token)


def tell_romm(
    settings: Settings, conn: sqlite3.Connection, client: RommClient | None = None
) -> None:
    """If RomM hasn't heard about the last change, rescan and forget what left.

    The flag clears only on success, so a failure here is retried by the next run.
    """
    client = client or romm_client(settings)
    if client is not None and romm_pending(conn):
        client.refresh_platform(PLATFORM)
        set_romm_pending(conn, False)
