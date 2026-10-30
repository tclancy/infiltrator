"""Tell RomM the shelf changed: scan the platform, then forget games whose files left.

RomM's own watcher scans 5 minutes after a file appears, but a removed file
only becomes "missing" and stays listed, so a rotated-out game would linger on
the TV. Endpoints and payloads as in RomM 5.4.1 (backend/endpoints/tasks.py).
"""

import json
import time
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError

Request = Callable[[str, str, dict[str, str], bytes | None], Any]
DONE, BROKEN = "finished", ("failed", "stopped", "canceled")
IN_FLIGHT = 409  # RomM refuses a scan while another library scan is queued or running


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
    ) -> None:
        self.url, self.token = url.rstrip("/"), token
        self.request, self.sleep = request, sleep
        self.scan_timeout, self.poll_seconds = scan_timeout, poll_seconds

    def _call(self, method: str, path: str, payload: dict | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode()
        return self.request(method, f"{self.url}{path}", headers, body)

    def platform_id(self, fs_slug: str) -> int:
        for platform in self._call("GET", "/api/platforms"):
            if platform["fs_slug"] == fs_slug:
                return platform["id"]
        raise RommError(f"RomM has no {fs_slug} platform")

    def start_scan(self, platform_id: int) -> str:
        """Queue a quick scan, waiting out one already in flight; returns its task id."""
        waited = 0.0
        while True:
            try:
                payload = {"type": "quick", "platforms": [platform_id]}
                return self._call("POST", "/api/tasks/scan", payload)["task_id"]
            except HTTPError as err:
                if err.code != IN_FLIGHT or waited > self.scan_timeout:
                    raise
            self.sleep(self.poll_seconds)
            waited += self.poll_seconds

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

    def refresh_platform(self, fs_slug: str) -> None:
        """Quick-scan one platform, and only once that finished, purge its missing ROMs."""
        pid = self.platform_id(fs_slug)
        self.wait_for(self.start_scan(pid))
        self._call("POST", "/api/tasks/run/cleanup_missing_roms", {"platform_ids": [pid]})
