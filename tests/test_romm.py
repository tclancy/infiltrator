import json
from urllib.error import HTTPError
from urllib.parse import parse_qs, parse_qsl, urlsplit

import pytest

from infiltrator.romm import DONE, RommClient, RommError


class FakeRomm:
    """Answers RomM's API from a script and records what was asked.

    ROMs and collections behave as RomM 5.4.1's do: a scan of a platform whose folder is given
    lists that folder, giving each new file an id and flagging a vanished one missing (never
    deleting it); `GET /api/roms` pages; collections are found, created and changed by id.
    A path in `forbid` answers 403, as RomM does for a token without the scope.
    """

    def __init__(
        self,
        scan_states=("queued", "started", "finished"),
        platforms=None,
        found=(),
        roms=(),
        collections=(),
        folders=None,
        forbid=(),
    ):
        self.calls = []
        self.states = list(scan_states)
        self.platforms = platforms or [{"id": 7, "fs_slug": "arcade"}, {"id": 2, "fs_slug": "nes"}]
        self.found = list(found)  # platforms RomM only knows once a scan of every folder ran
        self.roms = [{"missing_from_fs": False, **rom} for rom in roms]
        self.collections = [{**c, "rom_ids": list(c["rom_ids"])} for c in collections]
        self.folders = dict(folders or {})  # platform id -> the folder a scan of it reads
        self.forbid = set(forbid)
        self.next_id = 100

    def __call__(self, method, url, headers, body):
        assert headers["Authorization"] == "Bearer rmm_t"
        parts = urlsplit(url)
        payload = self._body(headers, body)
        self.calls.append((method, url, payload))
        if any(parts.path.startswith(path) for path in self.forbid):
            raise HTTPError(url, 403, "Forbidden", {}, None)
        return self._answer(method, parts.path, parse_qs(parts.query), payload)

    @staticmethod
    def _body(headers, body):
        if not body:
            return None
        if headers.get("Content-Type") == "application/x-www-form-urlencoded":
            return dict(parse_qsl(body.decode()))
        return json.loads(body)

    def _answer(self, method, path, query, payload):
        if path == "/api/platforms":
            return self.platforms
        if path == "/api/tasks/scan":
            return self._scan(payload)
        if path == "/api/tasks/scan-1":
            return {"task_id": "scan-1", "status": self.states.pop(0) if self.states else DONE}
        if path == "/api/tasks/run/cleanup_missing_roms":
            return {"task_id": "clean-1", "status": "queued"}
        if path == "/api/roms":
            return self._roms_page(query)
        if path == "/api/collections":
            return self._create(query, payload) if method == "POST" else self.collections
        if path.startswith("/api/collections/") and path.endswith("/roms"):
            return self._members(method, int(path.split("/")[3]), payload["rom_ids"])
        raise AssertionError(path)

    def _scan(self, payload):
        if "platforms" not in payload:
            self.platforms = self.platforms + self.found
            self.states = ["finished", *self.states]
        for pid in payload.get("platforms") or self.folders:
            self._read_folder(pid)
        return {"task_id": "scan-1", "status": "queued"}

    def _read_folder(self, pid):
        if pid not in self.folders:
            return
        there = {p.name for p in self.folders[pid].iterdir()}
        mine = [rom for rom in self.roms if rom["platform_id"] == pid]
        for rom in mine:
            rom["missing_from_fs"] = rom["fs_name"] not in there
        for name in sorted(there - {rom["fs_name"] for rom in mine}):
            self.next_id += 1
            self.roms.append(
                {"id": self.next_id, "fs_name": name, "platform_id": pid, "missing_from_fs": False}
            )

    def _roms_page(self, query):
        platforms = {int(p) for p in query.get("platform_ids", [])}
        matching = [
            rom
            for rom in self.roms
            if (not platforms or rom["platform_id"] in platforms)
            and not (query.get("missing") == ["false"] and rom["missing_from_fs"])
        ]
        limit, offset = int(query.get("limit", ["50"])[0]), int(query.get("offset", ["0"])[0])
        items = matching[offset : offset + limit]
        return {"items": items, "total": len(matching), "limit": limit, "offset": offset}

    def _create(self, query, fields):
        self.next_id += 1
        made = {
            "id": self.next_id,
            "name": fields["name"],
            "description": fields.get("description", ""),
            "rom_ids": [],
            "is_public": query.get("is_public") == ["true"],
        }
        self.collections.append(made)
        return made

    def _members(self, method, collection_id, rom_ids):
        collection = next(c for c in self.collections if c["id"] == collection_id)
        held = set(collection["rom_ids"])
        held = held | set(rom_ids) if method == "POST" else held - set(rom_ids)
        collection["rom_ids"] = sorted(held)
        return collection

    def members(self, name):
        """The ROM ids in the named collection, as a set."""
        return {i for c in self.collections if c["name"] == name for i in c["rom_ids"]}

    def rom_id(self, platform_id, fs_name):
        return next(
            r["id"] for r in self.roms if (r["platform_id"], r["fs_name"]) == (platform_id, fs_name)
        )

    def cleanups(self):
        return [b for _m, u, b in self.calls if u.endswith("/api/tasks/run/cleanup_missing_roms")]


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


def paths(fake):
    return [(m, u.removeprefix("http://romm:8080"), b) for m, u, b in fake.calls]


def test_a_platform_romm_has_not_met_gets_one_scan_of_every_folder_first():
    fake = FakeRomm(found=[{"id": 9, "fs_slug": "fbneo"}])
    client(fake).refresh_platform("fbneo")
    assert paths(fake) == [
        ("GET", "/api/platforms", None),
        ("POST", "/api/tasks/scan", {"type": "quick"}),
        ("GET", "/api/tasks/scan-1", None),
        ("GET", "/api/platforms", None),
        ("POST", "/api/tasks/scan", {"type": "quick", "platforms": [9]}),
        ("GET", "/api/tasks/scan-1", None),
        ("GET", "/api/tasks/scan-1", None),
        ("GET", "/api/tasks/scan-1", None),
        ("POST", "/api/tasks/run/cleanup_missing_roms", {"platform_ids": [9]}),
    ]


def test_a_known_platform_gets_no_scan_of_every_folder():
    fake = FakeRomm(found=[{"id": 9, "fs_slug": "fbneo"}])
    client(fake).refresh_platform("arcade")
    assert {"type": "quick"} not in [b for _m, _u, b in fake.calls]


def test_a_platform_still_unknown_after_the_scan_raises_after_one_scan_and_purges_nothing():
    fake = FakeRomm(platforms=[{"id": 2, "fs_slug": "nes"}])
    with pytest.raises(RommError, match="fbneo"):
        client(fake).refresh_platform("fbneo")
    scans = [b for _m, u, b in fake.calls if u.endswith("/api/tasks/scan")]
    assert scans == [{"type": "quick"}]
    assert not any(u.endswith("cleanup_missing_roms") for _m, u, _b in fake.calls)


def test_the_scan_of_every_folder_waits_out_one_in_flight_too():
    fake = FakeRomm(found=[{"id": 9, "fs_slug": "fbneo"}])
    busy = iter([True, False, False])

    def request(method, url, headers, body):
        if url.endswith("/api/tasks/scan") and next(busy):
            fake.calls.append((method, url, None))
            raise HTTPError(url, 409, "scan in flight", {}, None)
        return fake(method, url, headers, body)

    client(request).refresh_platform("fbneo")
    assert fake.calls[-1][2] == {"platform_ids": [9]}


# Scanning without the cleanup, listing ROMs, and keeping a collection.


def test_scanning_a_platform_waits_for_the_scan_and_purges_nothing():
    fake = FakeRomm()
    assert client(fake).scan_platform("arcade") == 7
    assert [u for _m, u, _b in paths(fake)][-1] == "/api/tasks/scan-1"
    assert fake.cleanups() == []


def rom(rom_id, fs_name, platform_id=7, **extra):
    return {
        "id": rom_id,
        "fs_name": fs_name,
        "platform_id": platform_id,
        "missing_from_fs": False,
        **extra,
    }


def test_roms_lists_every_page_of_a_platform():
    fake = FakeRomm(roms=[rom(i, f"set{i}.zip") for i in range(1, 6)])
    assert client(fake, page_size=2).roms(7) == {f"set{i}.zip": i for i in range(1, 6)}
    offsets = [parse_qs(urlsplit(u).query)["offset"] for _m, u, _b in fake.calls]
    assert offsets == [["0"], ["2"], ["4"]]


def test_roms_stops_at_the_last_page_even_when_it_is_full():
    fake = FakeRomm(roms=[rom(i, f"set{i}.zip") for i in range(1, 5)])
    assert len(client(fake, page_size=2).roms(7)) == 4
    assert len(fake.calls) == 2


def test_roms_asks_for_one_platforms_present_files_without_the_extras():
    fake = FakeRomm(roms=[rom(1, "alpha.zip")])
    client(fake).roms(7)
    method, url, body = fake.calls[0]
    assert (method, urlsplit(url).path, body) == ("GET", "/api/roms", None)
    assert parse_qs(urlsplit(url).query) == {
        "platform_ids": ["7"],
        "missing": ["false"],
        "limit": ["500"],
        "offset": ["0"],
        "with_char_index": ["false"],
        "with_filter_values": ["false"],
        "with_rom_id_index": ["false"],
    }


def test_roms_leaves_out_other_platforms_and_files_that_are_gone():
    listed = [rom(1, "alpha.zip"), rom(2, "alpha.zip", platform_id=9)]
    listed.append(rom(3, "gone.zip", missing_from_fs=True))

    def ignores_every_filter(method, url, headers, body):  # whatever RomM sends, trust no more
        return {"items": listed, "total": 3}

    assert client(ignores_every_filter).roms(7) == {"alpha.zip": 1}


def test_a_collection_is_found_by_its_name():
    fake = FakeRomm(collections=[{"id": 4, "name": "Other", "rom_ids": []}])
    fake.collections.append({"id": 5, "name": "On the shelf", "rom_ids": [1]})
    assert client(fake).collection("On the shelf")["id"] == 5
    assert client(fake).collection("Nope") is None


def test_a_new_collection_is_a_public_form_post_with_a_description():
    fake = FakeRomm()
    seen = []

    def request(method, url, headers, body):
        seen.append(headers.get("Content-Type"))
        return fake(method, url, headers, body)

    made = client(request).create_collection("On the shelf")
    method, url, fields = fake.calls[0]
    assert (method, urlsplit(url).path) == ("POST", "/api/collections")
    assert parse_qs(urlsplit(url).query) == {"is_public": ["true"]}
    assert seen == ["application/x-www-form-urlencoded"]
    assert fields["name"] == "On the shelf" and "Infiltrator" in fields["description"]
    assert made["is_public"] and fake.collections == [made]


def members_calls(fake):
    return [(m, urlsplit(u).path, b) for m, u, b in fake.calls if u.endswith("/roms")]


def test_a_collection_that_already_matches_gets_no_call():
    fake = FakeRomm(collections=[{"id": 5, "name": "On the shelf", "rom_ids": [1, 2]}])
    client(fake).set_collection_roms(fake.collections[0], [2, 1])
    assert fake.calls == []


def test_a_collection_gets_one_add_and_one_remove():
    fake = FakeRomm(collections=[{"id": 5, "name": "On the shelf", "rom_ids": [1, 2, 3]}])
    client(fake).set_collection_roms(fake.collections[0], [2, 4, 5])
    assert members_calls(fake) == [
        ("POST", "/api/collections/5/roms", {"rom_ids": [4, 5]}),
        ("DELETE", "/api/collections/5/roms", {"rom_ids": [1, 3]}),
    ]
    assert fake.members("On the shelf") == {2, 4, 5}


@pytest.mark.parametrize(
    ("held", "wanted", "method"), [([1], [1, 2], "POST"), ([1, 2], [1], "DELETE")]
)
def test_a_collection_short_or_over_by_some_gets_only_that_one_call(held, wanted, method):
    fake = FakeRomm(collections=[{"id": 5, "name": "On the shelf", "rom_ids": held}])
    client(fake).set_collection_roms(fake.collections[0], wanted)
    assert [m for m, _p, _b in members_calls(fake)] == [method]
    assert fake.members("On the shelf") == set(wanted)


def test_a_token_without_the_rom_scope_is_an_error():
    with pytest.raises(HTTPError):
        client(FakeRomm(forbid={"/api/roms"})).roms(7)


def test_a_token_without_the_collection_scope_is_an_error():
    with pytest.raises(HTTPError):
        client(FakeRomm(forbid={"/api/collections"})).collection("On the shelf")
