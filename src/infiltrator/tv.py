"""Put the TV persona's shelf in RomM's folders and tell RomM about it."""

import sqlite3

from infiltrator.catalogue.tv import tv_persona
from infiltrator.config import Settings
from infiltrator.dat import Dat
from infiltrator.publish import PublishResult, publish
from infiltrator.romm import RommClient
from infiltrator.shelf import current_shelf

PLATFORM = "arcade"


def bios_needed(dat: Dat, sets: list[str]) -> list[str]:
    found = {dat.bios_of(dat.games[name]) for name in sets if name in dat.games}
    return sorted(g.name for g in found if g is not None)


def publish_tv(settings: Settings, dat: Dat, conn: sqlite3.Connection) -> PublishResult | None:
    """Make RomM's folders hold the TV persona's shelf; None when there's nothing to publish to."""
    persona = tv_persona(conn)
    if persona is None or settings.shelf_dir is None or settings.bios_dir is None:
        return None
    sets = [row["set_name"] for row in current_shelf(conn, persona)]
    return publish(
        settings.library_dir, settings.shelf_dir, settings.bios_dir, sets, bios_needed(dat, sets)
    )


def romm_client(settings: Settings) -> RommClient | None:
    if not (settings.romm_url and settings.romm_token):
        return None
    return RommClient(settings.romm_url, settings.romm_token)


def show_on_tv(
    settings: Settings, dat: Dat, conn: sqlite3.Connection, client: RommClient | None = None
) -> PublishResult | None:
    """Publish, and when that changed anything, have RomM rescan and forget what left."""
    result = publish_tv(settings, dat, conn)
    client = client or romm_client(settings)
    if result is not None and result.changed and client is not None:
        client.refresh_platform(PLATFORM)
    return result
