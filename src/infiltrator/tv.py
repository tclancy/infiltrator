"""Put the TV persona's shelf in RomM's folders and tell RomM about it."""

import sqlite3
from collections.abc import Mapping
from pathlib import Path

from infiltrator.catalogue.tv import romm_pending, set_romm_pending, tv_persona
from infiltrator.config import Settings
from infiltrator.dat import DEFAULT_EMULATOR, FBNEO, Dat
from infiltrator.library import emulator_dir
from infiltrator.publish import PublishResult, Target, check_folders, locked, publish_all
from infiltrator.romm import RommClient
from infiltrator.shelf import current_shelf


def bios_needed(dat: Dat, sets: list[str]) -> list[str]:
    found = {dat.bios_of(dat.games[name]) for name in sets if name in dat.games}
    return sorted(g.name for g in found if g is not None)


Folders = tuple[Path, Path]  # (games, BIOS sets)


def publish_folders(settings: Settings) -> dict[str, Folders]:
    """Each emulator that has RomM folders configured, and those folders."""
    pairs = {
        DEFAULT_EMULATOR: (settings.shelf_dir, settings.bios_dir),
        FBNEO: (settings.fbneo_shelf_dir, settings.fbneo_bios_dir),
    }
    return {e: (shelf, bios) for e, (shelf, bios) in pairs.items() if shelf and bios}


def shown_emulators(settings: Settings) -> frozenset[str]:
    """The emulators whose sets may be shelved: MAME 2003-Plus, and any with folders of its own.

    A game chosen for FBNeo stays on MAME 2003-Plus until FBNeo's folders are configured, so a
    half-configured install shows a game the TV can launch rather than none.
    """
    return frozenset({DEFAULT_EMULATOR, *publish_folders(settings)})


def preflight(settings: Settings) -> None:
    """Raise now, before the shelf changes, if publishing to any folder would refuse later."""
    for emulator, folders in publish_folders(settings).items():
        check_folders(emulator_dir(settings.library_dir, emulator), *folders)


def _target(settings: Settings, dat: Dat, folders: Folders, shelf: list[sqlite3.Row]) -> Target:
    """One emulator's shelf entries, from its own library folder, with the BIOS its DAT names."""
    sets = [row["set_name"] for row in shelf if row["emulator"] == dat.emulator]
    library = emulator_dir(settings.library_dir, dat.emulator)
    return Target(library, *folders, sets, bios_needed(dat, sets))


def publish_tv(
    settings: Settings, dats: Mapping[str, Dat], conn: sqlite3.Connection
) -> PublishResult | None:
    """Make RomM's folders hold the TV persona's shelf; None when there's nothing to publish to.

    Each emulator's entries go to that emulator's folders. Every folder is checked before any
    changes, under one lock.
    """
    persona, folders = tv_persona(conn), publish_folders(settings)
    if persona is None or not folders:
        return None
    shelf = current_shelf(conn, persona)
    targets = [_target(settings, dats[e], pair, shelf) for e, pair in folders.items()]
    with locked(settings.db_path.parent / "publish.lock"):
        result = publish_all(targets)
    if result.changed:
        set_romm_pending(conn, True)
    return result


def romm_client(settings: Settings) -> RommClient | None:
    if not (settings.romm_url and settings.romm_token):
        return None
    return RommClient(settings.romm_url, settings.romm_token)


def romm_platforms(settings: Settings) -> list[str]:
    """One RomM platform per emulator with folders: named after its games folder (`mame`)."""
    return [shelf.name for shelf, _bios in publish_folders(settings).values()]


def tell_romm(
    settings: Settings, conn: sqlite3.Connection, client: RommClient | None = None
) -> None:
    """If RomM hasn't heard about the last change, rescan each platform and forget what left.

    Every platform is tried; the flag clears only if every one succeeded, so a failure here is
    retried by the next run. The first failure is raised once all have been tried.
    """
    client = client or romm_client(settings)
    if client is None or not romm_pending(conn):
        return
    failures = []
    for platform in romm_platforms(settings):
        try:
            client.refresh_platform(platform)
        except Exception as err:
            failures.append(err)
    if failures:
        raise failures[0]
    set_romm_pending(conn, False)
