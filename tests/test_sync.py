"""Caching, streaming downloads, asset syncing and the metadata cache."""

import json
import os

import pytest

from csr2cdn import CDN, MetadataCache, MetadataClient
from csr2cdn.cdn import SYNC_MANIFEST

from test_csr2cdn import FakeResponse, FakeSession

DATABASE = [
    {"branch_name": "6_7_0_Release_OTA_1", "version": "31951", "product_version": "6.7.81"},
    [
        {"code": "Alpha", "version": "1", "type": "1", "sizes": {"ASTC": 5, "High": 9}},
        {"code": "Beta", "version": "2", "type": "1", "dependencies": ["alpha"],
         "sizes": {"ASTC": 4, "High": 8}},
        {"code": "Gamma", "version": "3", "type": "2", "sizes": {"ASTC": 3, "High": 7}},
    ],
]
BASE = "https://csr2.cdn.zynga.com"


def _routes(**bodies):
    routes = {
        f"{BASE}/asset_database_6_7_0_Release_OTA_1.version": FakeResponse({"version": "31951"}),
        f"{BASE}/asset_database.31951.json": FakeResponse(DATABASE),
    }
    for code, body in bodies.items():
        asset = next(a for a in DATABASE[1] if a["code"] == code)
        routes[f"{BASE}/ANDROID/ASTC/{code}.ASTC.{asset['version']}"] = FakeResponse(content=body)
    return routes


def _cdn(routes, **kwargs):
    session = FakeSession(routes)
    client = CDN(session=session, branch="6_7_0_Release_OTA_1", **kwargs)
    client._metadata = MetadataClient(session=session)
    return client


# -- http behaviour -------------------------------------------------------
def test_a_missing_branch_is_none_but_a_broken_one_raises():
    routes = {f"{BASE}/asset_database_Present.version": FakeResponse({"version": "1"})}
    routes[f"{BASE}/asset_database_Broken.version"] = FakeResponse(status=500)
    cdn = _cdn(routes)
    assert cdn.try_database_version("Present") == "1"
    assert cdn.try_database_version("Absent") is None          # 404 means gone
    with pytest.raises(Exception):
        cdn.try_database_version("Broken")                      # 500 must not look gone
    assert cdn.try_database_version("Broken", strict=False) is None


# -- caching --------------------------------------------------------------
def test_databases_are_cached_on_disk(tmp_path):
    routes = _routes()
    cdn = _cdn(routes, cache_dir=tmp_path)
    first = cdn.get_database(version="31951")
    assert len(cdn.session.requested) == 1

    again = CDN(session=FakeSession({}), branch="6_7_0_Release_OTA_1", cache_dir=tmp_path)
    second = again.get_database(version="31951")   # no routes at all, served from disk
    assert second.to_json() == first.to_json()
    assert again.session.requested == []


def test_version_lookups_are_cached_for_a_while(tmp_path):
    cdn = _cdn(_routes(), cache_dir=tmp_path, version_ttl=3600)
    assert cdn.database_version() == "31951"
    assert cdn.database_version() == "31951"
    assert len(cdn.session.requested) == 1
    assert cdn.version_info(refresh=True)["version"] == "31951"
    assert len(cdn.session.requested) == 2


@pytest.mark.parametrize("ttl", [0, -1])
@pytest.mark.parametrize("age", [0, -1])
def test_expired_version_cache_is_refetched(tmp_path, monkeypatch, ttl, age):
    cdn = _cdn(_routes(), cache_dir=tmp_path, version_ttl=ttl)
    cdn.database_version()
    path = next(tmp_path.rglob("*.json"))
    monkeypatch.setattr("csr2cdn.cdn.time.time", lambda: path.stat().st_mtime + age)
    cdn.database_version()
    assert len(cdn.session.requested) == 2


def test_version_cache_expires_at_ttl_boundary(tmp_path, monkeypatch):
    cdn = _cdn(_routes(), cache_dir=tmp_path, version_ttl=60)
    cdn.database_version()
    path = next(tmp_path.rglob("*.json"))
    monkeypatch.setattr("csr2cdn.cdn.time.time", lambda: path.stat().st_mtime + 60)
    cdn.database_version()
    assert len(cdn.session.requested) == 2


def test_clear_cache(tmp_path):
    cdn = _cdn(_routes(), cache_dir=tmp_path)
    cdn.get_database(version="31951")
    assert os.listdir(tmp_path)
    cdn.clear_cache()
    assert not os.path.exists(tmp_path)


# -- downloads ------------------------------------------------------------
def test_downloads_are_atomic_and_leave_no_part_file(tmp_path):
    cdn = _cdn(_routes(Alpha=b"12345"))
    path = cdn.download_asset_to("Alpha", tmp_path)
    assert open(path, "rb").read() == b"12345"
    assert not any(name.endswith(".part") for name in os.listdir(tmp_path))


def test_skip_existing_respects_the_size_in_the_database(tmp_path):
    cdn = _cdn(_routes(Alpha=b"12345"))
    asset = cdn.database.assets.Alpha           # ASTC size is 5
    target = tmp_path / "Alpha.ASTC.1"
    target.write_bytes(b"12345")
    before = len(cdn.session.requested)
    cdn.download_asset_to(asset, tmp_path, skip_existing=True)
    assert len(cdn.session.requested) == before  # complete, so not refetched

    target.write_bytes(b"12")                    # truncated
    cdn.download_asset_to(asset, tmp_path, skip_existing=True)
    assert target.read_bytes() == b"12345"


# -- sync -----------------------------------------------------------------
def test_sync_downloads_everything_then_nothing(tmp_path):
    cdn = _cdn(_routes(Alpha=b"a", Beta=b"b", Gamma=b"g"))
    first = cdn.sync_assets(tmp_path)
    assert sorted(first.downloaded) == ["Alpha", "Beta", "Gamma"]
    assert first.unchanged == []
    assert first.changed

    second = cdn.sync_assets(tmp_path)
    assert second.downloaded == []
    assert sorted(second.unchanged) == ["Alpha", "Beta", "Gamma"]
    assert not second.changed


def test_sync_only_fetches_what_changed(tmp_path):
    cdn = _cdn(_routes(Alpha=b"a", Beta=b"b", Gamma=b"g"))
    cdn.sync_assets(tmp_path)

    # Beta moves to version 3 in a new database.
    bumped = json.loads(json.dumps(DATABASE))
    bumped[1][1]["version"] = "3"
    routes = _routes(Alpha=b"a", Gamma=b"g")
    routes[f"{BASE}/asset_database.31951.json"] = FakeResponse(bumped)
    routes[f"{BASE}/ANDROID/ASTC/Beta.ASTC.3"] = FakeResponse(content=b"bb")
    fresh = _cdn(routes)

    result = fresh.sync_assets(tmp_path)
    assert result.downloaded == ["Beta"]
    assert sorted(result.unchanged) == ["Alpha", "Gamma"]
    assert (tmp_path / "Beta.ASTC.3").read_bytes() == b"bb"
    assert not (tmp_path / "Beta.ASTC.2").exists()   # the old file is replaced


def test_sync_can_narrow_the_selection(tmp_path):
    cdn = _cdn(_routes(Alpha=b"a", Beta=b"b", Gamma=b"g"))
    result = cdn.sync_assets(tmp_path, search="Bet", with_dependencies=True)
    assert sorted(result.downloaded) == ["Alpha", "Beta"]   # Alpha is Beta's dependency

    typed = cdn.sync_assets(tmp_path, asset_type=2)
    assert typed.downloaded == ["Gamma"]


def test_sync_removes_stale_files_when_asked(tmp_path):
    cdn = _cdn(_routes(Alpha=b"a", Beta=b"b", Gamma=b"g"))
    cdn.sync_assets(tmp_path)
    assert (tmp_path / "Gamma.ASTC.3").exists()

    result = cdn.sync_assets(tmp_path, search="Alpha", remove_stale=True)
    assert sorted(result.removed) == ["Beta", "Gamma"]
    assert not (tmp_path / "Gamma.ASTC.3").exists()
    assert (tmp_path / "Alpha.ASTC.1").exists()


def test_sync_accepts_a_custom_naming_scheme(tmp_path):
    cdn = _cdn(_routes(Alpha=b"a", Beta=b"b", Gamma=b"g"))
    cdn.sync_assets(tmp_path, search="Alpha", name_for=lambda asset: asset.code.lower())
    assert (tmp_path / "alpha").read_bytes() == b"a"


def test_sync_manifest_records_the_database(tmp_path):
    cdn = _cdn(_routes(Alpha=b"a", Beta=b"b", Gamma=b"g"))
    cdn.sync_assets(tmp_path)
    manifest = json.loads((tmp_path / SYNC_MANIFEST).read_text())
    assert manifest["branch"] == "6_7_0_Release_OTA_1"
    assert manifest["database_version"] == "31951"
    assert manifest["assets"]["Alpha"] == {"version": "1", "file": "Alpha.ASTC.1"}


def test_sync_reports_failures_without_losing_the_batch(tmp_path):
    cdn = _cdn(_routes(Alpha=b"a", Gamma=b"g"))   # Beta has no route
    result = cdn.sync_assets(tmp_path)
    assert sorted(result.downloaded) == ["Alpha", "Gamma"]
    assert list(result.failed) == ["Beta"]

    # A failed asset is not recorded, so the next run retries it.
    manifest = json.loads((tmp_path / SYNC_MANIFEST).read_text())
    assert "Beta" not in manifest["assets"]


def test_deleting_a_file_makes_sync_fetch_it_again(tmp_path):
    cdn = _cdn(_routes(Alpha=b"a", Beta=b"b", Gamma=b"g"))
    cdn.sync_assets(tmp_path)
    (tmp_path / "Alpha.ASTC.1").unlink()
    result = cdn.sync_assets(tmp_path)
    assert result.downloaded == ["Alpha"]


# -- metadata cache -------------------------------------------------------
def _metadata_routes(*blocks):
    return {
        MetadataClient().url: FakeResponse(
            {"responseCode": 610, "responseData": {"blocks": list(blocks)}}
        )
    }


def test_metadata_cache_writes_files_and_hashes(tmp_path):
    payload = {"CollectionSlots": {"slots": 4}}
    session = FakeSession(_metadata_routes({"id": "CollectionSlots", "hash": "abc", "data": payload}))
    cache = MetadataCache(tmp_path, zid="1", product_version="6.7.81",
                          client=MetadataClient(session=session))

    assert cache.sync(["CollectionSlots"]) == ["CollectionSlots"]
    assert cache.load("CollectionSlots") == {"slots": 4}     # envelope unwrapped
    assert cache.hashes() == {"CollectionSlots": "abc"}
    assert cache.stored() == ["CollectionSlots"]

    body = session.posted[-1][1].decode()
    assert "0" * 32 in body                                   # first call claims no hash


def test_metadata_cache_sends_stored_hashes_and_skips_current_blocks(tmp_path):
    payload = {"CollectionSlots": {"slots": 4}}
    session = FakeSession(_metadata_routes({"id": "CollectionSlots", "hash": "abc", "data": payload}))
    client = MetadataClient(session=session)
    cache = MetadataCache(tmp_path, zid="1", product_version="6.7.81", client=client)
    cache.sync(["CollectionSlots"])

    # Now the service considers us current and returns null.
    session.routes = _metadata_routes({"id": "CollectionSlots", "data": None})
    assert cache.sync(["CollectionSlots"]) == []
    assert cache.load("CollectionSlots") == {"slots": 4}     # file left alone
    assert "hash%22%3A%22abc" in session.posted[-1][1].decode()


def test_metadata_cache_refetches_when_the_file_is_deleted(tmp_path):
    payload = {"CollectionSlots": {"slots": 4}}
    session = FakeSession(_metadata_routes({"id": "CollectionSlots", "hash": "abc", "data": payload}))
    cache = MetadataCache(tmp_path, zid="1", product_version="6.7.81",
                          client=MetadataClient(session=session))
    cache.sync(["CollectionSlots"])
    os.remove(cache.path("CollectionSlots"))
    assert cache.hashes() == {}                              # hash dropped with the file
    assert cache.sync(["CollectionSlots"]) == ["CollectionSlots"]


def test_metadata_cache_needs_a_zid(tmp_path):
    from csr2cdn import MetadataError

    cache = MetadataCache(tmp_path, product_version="6.7.81")
    with pytest.raises(MetadataError):
        cache.sync(["CollectionSlots"])


def test_cdn_hands_out_a_wired_cache(tmp_path):
    cdn = _cdn(_routes(), zid="948", product_version="6.7.81")
    cache = cdn.metadata_cache(tmp_path)
    assert cache.zid == "948"
    assert cache.product_version == "6.7.81"
