"""Put the TV persona's shelf in RomM's folders and tell RomM about it.

Without `romm_collection`, RomM's folders hold the shelf and nothing else. With it, they hold
the whole verified library (each game as its chosen emulator's sets) and the shelf is that RomM
collection.
"""

import json
import sqlite3
from collections.abc import Collection, Mapping
from pathlib import Path

from infiltrator.catalogue.games import library_sets
from infiltrator.catalogue.tv import (
    romm_pending,
    romm_shelf,
    set_romm_pending,
    set_romm_shelf,
    tv_persona,
)
from infiltrator.config import Settings
from infiltrator.dat import DEFAULT_EMULATOR, FBNEO, Dat
from infiltrator.library import emulator_dir
from infiltrator.publish import PublishResult, Target, check_folders, locked, publish_all
from infiltrator.romm import RommClient, RommError
from infiltrator.shelf import current_shelf, stand_ins


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


def _shelf_targets(
    settings: Settings, dats: Mapping[str, Dat], conn: sqlite3.Connection, persona: str
) -> list[Target]:
    """Each emulator with folders: the persona's shelf entries for it, and the BIOS they need."""
    shelf = current_shelf(conn, persona)
    folders = publish_folders(settings)
    return [_target(settings, dats[e], pair, shelf) for e, pair in folders.items()]


def _shown_games(emulator: str, games: list[sqlite3.Row], stood_in: Collection[str]) -> list[str]:
    """An emulator's sets RomM should list: a MAME 2003-Plus set is left out once its game is
    shown as another emulator's set, so RomM has one emulator's copy of a game, not both."""
    if emulator != DEFAULT_EMULATOR:
        return [g["set_name"] for g in games]
    return [g["set_name"] for g in games if g["family"] not in stood_in]


def _library_targets(settings: Settings, conn: sqlite3.Connection) -> list[Target]:
    """Each emulator with folders: its verified sets, one emulator per game, and its BIOS sets
    in the BIOS folder."""
    stood_in = stand_ins(conn, shown_emulators(settings))
    targets = []
    for emulator, folders in publish_folders(settings).items():
        games, bios = library_sets(conn, emulator)
        shown = _shown_games(emulator, games, stood_in)
        targets.append(Target(emulator_dir(settings.library_dir, emulator), *folders, shown, bios))
    return targets


def publish_tv(
    settings: Settings, dats: Mapping[str, Dat], conn: sqlite3.Connection
) -> PublishResult | None:
    """Make RomM's folders hold what the TV shows; None when there's nothing to publish to.

    That is the TV persona's shelf, or with `romm_collection` the whole library. Each emulator's
    sets go to that emulator's folders. Every folder is checked before any changes, under one
    lock.
    """
    persona = tv_persona(conn)
    if persona is None or not publish_folders(settings):
        return None
    if settings.romm_collection:
        targets = _library_targets(settings, conn)
    else:
        targets = _shelf_targets(settings, dats, conn, persona)
    with locked(settings.db_path.parent / "publish.lock"):
        result = publish_all(targets)
    if result.changed or _collection_behind(settings, conn):
        set_romm_pending(conn, True)
    return result


def shelf_on_tv(settings: Settings, conn: sqlite3.Connection) -> dict[str, list[str]]:
    """The TV persona's shelf by RomM platform: each emulator with folders, its shelved sets."""
    persona = tv_persona(conn)
    shelf = current_shelf(conn, persona) if persona else []
    return {
        games.name: sorted(row["set_name"] for row in shelf if row["emulator"] == emulator)
        for emulator, (games, _bios) in publish_folders(settings).items()
    }


def _shelf_key(shelf: dict[str, list[str]]) -> str:
    return json.dumps(shelf, sort_keys=True)


def _collection_behind(settings: Settings, conn: sqlite3.Connection) -> bool:
    """With the shelf as a collection: has the shelf changed since the collection matched it?"""
    if not settings.romm_collection:
        return False
    return romm_shelf(conn) != _shelf_key(shelf_on_tv(settings, conn))


def romm_client(settings: Settings) -> RommClient | None:
    if not (settings.romm_url and settings.romm_token):
        return None
    return RommClient(settings.romm_url, settings.romm_token)


def romm_platforms(settings: Settings) -> list[str]:
    """One RomM platform per emulator with folders: named after its games folder (`mame`)."""
    return [shelf.name for shelf, _bios in publish_folders(settings).values()]


def shelf_rom_ids(client: RommClient, shelf: dict[str, list[str]]) -> set[int]:
    """The RomM id of every shelved set, from its own platform; raises naming any RomM lacks."""
    ids, unlisted = set(), []
    for platform, sets in shelf.items():
        if not sets:
            continue
        listed = client.roms(client.platform_id(platform))
        ids |= {listed[f"{name}.zip"] for name in sets if f"{name}.zip" in listed}
        unlisted += [f"{platform}/{name}" for name in sets if f"{name}.zip" not in listed]
    if unlisted:
        raise RommError(f"RomM does not list {', '.join(unlisted)}")
    return ids


def sync_collection(settings: Settings, conn: sqlite3.Connection, client: RommClient) -> None:
    """Make the `romm_collection` collection hold exactly the TV's shelf, made if need be.

    Every shelved set is found in RomM before the collection is touched, so a set RomM has not
    listed yet changes nothing.
    """
    name = settings.romm_collection
    assert name is not None
    shelf = shelf_on_tv(settings, conn)
    rom_ids = shelf_rom_ids(client, shelf)
    collection = client.collection(name) or client.create_collection(name)
    client.set_collection_roms(collection, rom_ids)
    set_romm_shelf(conn, _shelf_key(shelf))


def _scan_platforms(settings: Settings, client: RommClient) -> list[Exception]:
    """Scan each platform, trying every one; returns what failed.

    Missing ROMs are purged only when the folders hold just the shelf. With the shelf as a
    collection, a game that left keeps its RomM record, its cover and its id.
    """
    scan = client.scan_platform if settings.romm_collection else client.refresh_platform
    failures = []
    for platform in romm_platforms(settings):
        try:
            scan(platform)
        except Exception as err:
            failures.append(err)
    return failures


def tell_romm(
    settings: Settings, conn: sqlite3.Connection, client: RommClient | None = None
) -> None:
    """If RomM hasn't heard about the last change, rescan each platform, then show the shelf.

    RomM shows the shelf once it forgets what left the folders or, with `romm_collection`, once
    that collection's members are set. The flag clears only if all of it succeeded, so a
    failure here is retried by the next run. The first failure is raised after every platform
    was tried, and the collection is left alone unless every scan succeeded.
    """
    client = client or romm_client(settings)
    if client is None or not romm_pending(conn):
        return
    failures = _scan_platforms(settings, client)
    if failures:
        raise failures[0]
    if settings.romm_collection:
        sync_collection(settings, conn, client)
    set_romm_pending(conn, False)
