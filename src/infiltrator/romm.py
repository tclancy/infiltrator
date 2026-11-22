"""Tell RomM what changed: scan a platform, forget games whose files left, keep a collection.

RomM's own watcher scans 5 minutes after a file appears, but a removed file
only becomes "missing" and stays listed, so a rotated-out game would linger on
the TV unless the cleanup task deletes its record (and its cover with it).
With the shelf as a collection nothing leaves the folders, so the collection's
members change instead and no record is deleted.

Endpoints, parameters and payloads as in RomM 5.4.1: backend/endpoints/tasks.py (scans, the
cleanup task), backend/endpoints/roms/__init__.py (`GET /api/roms`) and
backend/endpoints/collections.py.
"""

import json
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from typing import Any
from urllib.error import HTTPError

Request = Callable[[str, str, dict[str, str], bytes | None], Any]
DONE, BROKEN = "finished", ("failed", "stopped", "canceled")
IN_FLIGHT = 409  # RomM refuses a scan while another library scan is queued or running
ROMS_PAGE = 500  # RomM pages ROMs 50 at a time unless asked, and allows up to 10,000
FORM = "application/x-www-form-urlencoded"  # how RomM's form fields arrive when no file is sent
COLLECTION_DESCRIPTION = "Infiltrator keeps this matching the shelf on the TV; edits are undone."


class RommError(Exception):
    """RomM didn't do what was asked."""


def http_json(method: str, url: str, headers: dict[str, str], body: bytes | None) -> Any:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (the configured RomM URL)
        return json.load(resp)


class RommClient:
    def __init__(
        self,
        url: str,
        token: str,
        *,
        request: Request = http_json,
        sleep: Callable[[float], None] = time.sleep,
        scan_timeout: float = 900,
        poll_seconds: float = 5,
        page_size: int = ROMS_PAGE,
    ) -> None:
        self.url, self.token = url.rstrip("/"), token
        self.request, self.sleep = request, sleep
        self.scan_timeout, self.poll_seconds = scan_timeout, poll_seconds
        self.page_size = page_size

    def _send(self, method: str, path: str, body: bytes | None, content_type: str | None) -> Any:
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if content_type is not None:
            headers["Content-Type"] = content_type
        return self.request(method, f"{self.url}{path}", headers, body)

    def _call(self, method: str, path: str, payload: dict | None = None) -> Any:
        if payload is None:
            return self._send(method, path, None, None)
        return self._send(method, path, json.dumps(payload).encode(), "application/json")

    def _post_form(self, path: str, fields: dict[str, str]) -> Any:
        return self._send("POST", path, urllib.parse.urlencode(fields).encode(), FORM)

    def _find_platform(self, fs_slug: str) -> int | None:
        for platform in self._call("GET", "/api/platforms"):
            if platform["fs_slug"] == fs_slug:
                return platform["id"]
        return None

    def platform_id(self, fs_slug: str) -> int:
        pid = self._find_platform(fs_slug)
        if pid is None:
            raise RommError(f"RomM has no {fs_slug} platform")
        return pid

    def _start(self, payload: dict) -> str:
        """Queue a scan, waiting out one already in flight; returns its task id."""
        waited = 0.0
        while True:
            try:
                return self._call("POST", "/api/tasks/scan", payload)["task_id"]
            except HTTPError as err:
                if err.code != IN_FLIGHT or waited > self.scan_timeout:
                    raise
            self.sleep(self.poll_seconds)
            waited += self.poll_seconds

    def start_scan(self, platform_id: int) -> str:
        """Queue a quick scan of one platform; returns its task id."""
        return self._start({"type": "quick", "platforms": [platform_id]})

    def start_full_scan(self) -> str:
        """Queue a quick scan of every folder, which is how RomM meets a new one."""
        return self._start({"type": "quick"})

    def _known_platform(self, fs_slug: str) -> int:
        """The platform's id; a folder RomM has never scanned gets one full quick scan first."""
        pid = self._find_platform(fs_slug)
        if pid is not None:
            return pid
        self.wait_for(self.start_full_scan())
        return self.platform_id(fs_slug)

    def wait_for(self, task_id: str) -> None:
        waited = 0.0
        while waited <= self.scan_timeout:
            status = self._call("GET", f"/api/tasks/{task_id}")["status"]
            if status == DONE:
                return
            if status in BROKEN:
                raise RommError(f"RomM task {task_id} {status}")
            self.sleep(self.poll_seconds)
            waited += self.poll_seconds
        raise RommError(f"RomM task {task_id} still running after {self.scan_timeout}s")

    def scan_platform(self, fs_slug: str) -> int:
        """Quick-scan one platform and wait for it; returns its id. Nothing is deleted."""
        pid = self._known_platform(fs_slug)
        self.wait_for(self.start_scan(pid))
        return pid

    def refresh_platform(self, fs_slug: str) -> None:
        """Quick-scan one platform, and only once that finished, purge its missing ROMs."""
        pid = self.scan_platform(fs_slug)
        self._call("POST", "/api/tasks/run/cleanup_missing_roms", {"platform_ids": [pid]})

    def _roms_page(self, platform_id: int, offset: int) -> dict:
        """One page of a platform's ROMs whose files are there, without the UI's extras."""
        query = urllib.parse.urlencode(
            {
                "platform_ids": platform_id,
                "missing": "false",
                "limit": self.page_size,
                "offset": offset,
                "with_char_index": "false",
                "with_filter_values": "false",
                "with_rom_id_index": "false",
            }
        )
        return self._call("GET", f"/api/roms?{query}")

    def _all_roms(self, platform_id: int) -> list[dict]:
        """Every page of a platform's ROMs: until RomM's total, or a page comes up short."""
        roms: list[dict] = []
        while True:
            page = self._roms_page(platform_id, len(roms))
            roms.extend(page["items"])
            if len(page["items"]) < self.page_size or len(roms) >= page["total"]:
                return roms

    def roms(self, platform_id: int) -> dict[str, int]:
        """File name → RomM id, for the platform's ROMs whose files are there."""
        return {
            rom["fs_name"]: rom["id"]
            for rom in self._all_roms(platform_id)
            if rom["platform_id"] == platform_id and not rom["missing_from_fs"]
        }

    def collection(self, name: str) -> dict | None:
        """The collection of this name, with its `id` and `rom_ids`; None if there is none."""
        for found in self._call("GET", "/api/collections"):
            if found["name"] == name:
                return found
        return None

    def create_collection(self, name: str) -> dict:
        """A new, empty, public collection: everyone in the house sees the same shelf."""
        fields = {"name": name, "description": COLLECTION_DESCRIPTION}
        return self._post_form("/api/collections?is_public=true", fields)

    def set_collection_roms(self, collection: dict, rom_ids: Iterable[int]) -> None:
        """Make the collection hold exactly these ROMs: add the missing, then drop the rest."""
        wanted, held = set(rom_ids), set(collection["rom_ids"])
        path = f"/api/collections/{collection['id']}/roms"
        if wanted - held:
            self._call("POST", path, {"rom_ids": sorted(wanted - held)})
        if held - wanted:
            self._call("DELETE", path, {"rom_ids": sorted(held - wanted)})
