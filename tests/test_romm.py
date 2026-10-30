import json
from urllib.error import HTTPError

import pytest

from infiltrator.romm import RommClient, RommError


class FakeRomm:
    """Answers RomM's API from a script and records what was asked."""

    def __init__(self, scan_states=("queued", "started", "finished"), platforms=None):
        self.calls = []
        self.states = list(scan_states)
        self.platforms = platforms or [{"id": 7, "fs_slug": "arcade"}, {"id": 2, "fs_slug": "nes"}]

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, json.loads(body) if body else None))
        assert headers["Authorization"] == "Bearer rmm_t"
        if url.endswith("/api/platforms"):
            return self.platforms
        if url.endswith("/api/tasks/scan"):
            return {"task_id": "scan-1", "status": "queued"}
        if url.endswith("/api/tasks/scan-1"):
            return {"task_id": "scan-1", "status": self.states.pop(0)}
        if url.endswith("/api/tasks/run/cleanup_missing_roms"):
            return {"task_id": "clean-1", "status": "queued"}
        raise AssertionError(url)


def client(fake, **kw):
    return RommClient("http://romm:8080", "rmm_t", request=fake, sleep=lambda s: None, **kw)


def test_scan_then_wait_then_purge_missing_for_arcade_only():
    fake = FakeRomm()
    client(fake).refresh_platform("arcade")
    assert [(m, u.removeprefix("http://romm:8080")) for m, u, _ in fake.calls] == [
        ("GET", "/api/platforms"),
        ("POST", "/api/tasks/scan"),
        ("GET", "/api/tasks/scan-1"),
        ("GET", "/api/tasks/scan-1"),
        ("GET", "/api/tasks/scan-1"),
        ("POST", "/api/tasks/run/cleanup_missing_roms"),
    ]
    assert fake.calls[1][2] == {"type": "quick", "platforms": [7]}
    assert fake.calls[-1][2] == {"platform_ids": [7]}


def test_failed_scan_raises_and_purges_nothing():
    fake = FakeRomm(scan_states=("started", "failed"))
    with pytest.raises(RommError, match="failed"):
        client(fake).refresh_platform("arcade")
    assert not any(u.endswith("cleanup_missing_roms") for _m, u, _b in fake.calls)


def test_scan_that_never_ends_times_out_and_purges_nothing():
    fake = FakeRomm(scan_states=["started"] * 100)
    with pytest.raises(RommError, match="still"):
        client(fake, scan_timeout=10, poll_seconds=2).refresh_platform("arcade")
    assert not any(u.endswith("cleanup_missing_roms") for _m, u, _b in fake.calls)


def test_unknown_platform_raises():
    fake = FakeRomm(platforms=[{"id": 2, "fs_slug": "nes"}])
    with pytest.raises(RommError, match="arcade"):
        client(fake).refresh_platform("arcade")


def test_scan_already_running_is_retried_until_romm_accepts():
    fake = FakeRomm()
    busy = iter([True, True, False])

    def request(method, url, headers, body):
        if url.endswith("/api/tasks/scan") and next(busy):
            fake.calls.append((method, url, None))
            raise HTTPError(url, 409, "scan in flight", {}, None)
        return fake(method, url, headers, body)

    client(request).refresh_platform("arcade")
    assert sum(u.endswith("/api/tasks/scan") for _m, u, _b in fake.calls) == 3
    assert fake.calls[-1][1].endswith("cleanup_missing_roms")


def test_other_http_errors_are_not_retried():
    def request(method, url, headers, body):
        if url.endswith("/api/tasks/scan"):
            raise HTTPError(url, 403, "forbidden", {}, None)
        return FakeRomm()(method, url, headers, body)

    with pytest.raises(HTTPError):
        client(request).refresh_platform("arcade")
