import json
from urllib.parse import parse_qs

import pytest
import requests

from csr2cdn import (
    CDN, MetadataBlock, MetadataClient, MetadataError, MissingZidError,
    SnapshotCDN, SnapshotError, SnapshotNotFoundError, metadata_block_ids,
)
from csr2cdn.cli import main


CAR = "Apollo_S_2008"
UNSET = "-2147483648"
PNG = b"\x89PNG\r\n\x1a\n" + b"test-image-data"


def path(car=CAR, mode="DEFAULT", interior=UNSET, caliper=UNSET, extra="", prefix=None):
    if prefix is None:
        prefix = "Default/" if mode.startswith("DEFAULT") else ""
    return (f"{prefix}{car}_p0_i{interior}_c{caliper}_s512_n"
            f"_lz{UNSET}_l{UNSET}_m{mode}{extra}.png")


def manifest(paths=None):
    return {"CDNSnapshots": {
        "BaseUrlProd": "https://production.example/cdn-snapshots/",
        "BaseUrlStaging": "https://staging.example",
        "list": paths if paths is not None else [
            path(), path(interior="1840", caliper="0"),
            path(mode="DEFAULT_REVERSED", interior="1840", caliper="0"),
            path(mode="GACHA_CAR", extra="_fgc0"), path(mode="GACHA_CAR"),
            path(mode="PRIZE_CAR"), path("Abarth_500_2014", mode="GACHA_CAR"),
        ],
    }}


class Response:
    def __init__(self, body=PNG, status=200, document=None):
        self.content, self.status_code, self.document = body, status, document
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("HTTP error", response=self)

    def json(self):
        return self.document

    def close(self):
        self.closed = True


class Session:
    def __init__(self, response=None):
        self.response = response or Response()
        self.calls = []
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.response

    def close(self):
        self.closed = True


def test_car_dictionary_merges_directories_and_variants_without_inventing_modes():
    snapshots = SnapshotCDN(manifest())
    assert set(snapshots.cars) == {CAR, "Abarth_500_2014"}
    assert snapshots.cars[CAR] == dict(GACHA=True, PRIZE=True, DEFAULT=True, DEFAULT_REVERSED=True)
    assert snapshots.cars["Abarth_500_2014"] == dict(
        GACHA=True, PRIZE=False, DEFAULT=False, DEFAULT_REVERSED=False)
    cars = snapshots.cars
    cars[CAR]["DEFAULT"] = False
    assert snapshots.available(CAR)


def test_selection_preserves_listed_paths_and_is_independent_of_manifest_order():
    data = manifest()
    a = SnapshotCDN(data)
    data["CDNSnapshots"]["list"].reverse()
    b = SnapshotCDN(data)
    assert a.snapshot_path(CAR) == b.snapshot_path(CAR) == path()
    assert a.snapshot_path(CAR, "GACHA") == path(mode="GACHA_CAR")
    assert a.snapshot_path(CAR, reversed=True) == path(
        mode="DEFAULT_REVERSED", interior="1840", caliper="0")
    assert len(a.variants(CAR, "GACHA")) == 2


@pytest.mark.parametrize("suffix", ["_fgc0", "_et0000000", "_r_E0_W0_I0_B0",
                                   "_f-1_ns-1_rn-1_rc-1_rs-1_rz-1_wheel3a_pn0_cn0"])
def test_only_available_customized_variant_is_used_verbatim(suffix):
    exact = path(mode="GACHA_CAR", extra=suffix)
    snapshots = SnapshotCDN(manifest([exact]))
    assert snapshots.snapshot_path(CAR, "GACHA", strict=True) == exact


def test_unlisted_car_or_missing_mode_is_allowed_but_not_advertised():
    snapshots = SnapshotCDN(manifest())
    assert snapshots.variants("Future_Car_2030") == ()
    assert not snapshots.available("Future_Car_2030")
    assert snapshots.snapshot_path("Future_Car_2030", reversed=True) == path(
        "Future_Car_2030", mode="DEFAULT_REVERSED", interior="1840", caliper="0")
    assert snapshots.snapshot_path("Abarth_500_2014", "PRIZE") == path(
        "Abarth_500_2014", mode="PRIZE_CAR")
    assert "Future_Car_2030" not in snapshots.cars
    with pytest.raises(SnapshotNotFoundError):
        snapshots.snapshot_url("Future_Car_2030", strict=True)
    with pytest.raises(SnapshotNotFoundError):
        snapshots.snapshot_path("Abarth_500_2014", reversed=True, strict=True)


@pytest.mark.parametrize("kind,reverse", [("PRIZE", True), ("GACHA", True), ("MAP", False),
                                         ("DEFAULT", "false"), (None, False)])
def test_invalid_modes_rejected(kind, reverse):
    with pytest.raises(ValueError):
        SnapshotCDN(manifest()).snapshot_url(CAR, kind, reversed=reverse)


def test_urls_production_staging_and_case_sensitive_car_names():
    s = SnapshotCDN(manifest())
    assert s.snapshot_url(CAR, "prize") == "https://production.example/cdn-snapshots/" + path(mode="PRIZE_CAR")
    assert SnapshotCDN(manifest(), staging=True).snapshot_url(CAR) == "https://staging.example/" + path()
    assert not s.available(CAR.lower())
    assert s.url_for("Default/a #?.png").endswith("/Default/a%20%23%3F.png")


def test_unknown_future_files_and_placeholder_are_retained_without_false_modes():
    s = SnapshotCDN(manifest(["Mystery_Car_1234.png", "Default/Mystery_Car_1234.png", "future/file.png"]))
    assert s.unclassified_paths == ("Mystery_Car_1234.png", "future/file.png")
    assert s.cars["Mystery_Car_1234"] == dict(GACHA=False, PRIZE=False, DEFAULT=True, DEFAULT_REVERSED=False)
    assert s.snapshot_path("Mystery_Car_1234") == "Default/Mystery_Car_1234.png"
    assert s.url_for("future/file.png").endswith("/future/file.png")


@pytest.mark.parametrize("bad", ["../car", "/car", "car/name", "car\\name", "https:car", "", "a\n"])
def test_invalid_car_names_cannot_escape_the_endpoint(bad):
    with pytest.raises(ValueError):
        SnapshotCDN(manifest()).snapshot_url(bad)


@pytest.mark.parametrize("bad", ["../a.png", "/a.png", "//host/a.png", "a/../b", "a\\b", None, "a\n"])
def test_unsafe_manifest_paths_rejected(bad):
    with pytest.raises(ValueError):
        SnapshotCDN(manifest([bad]))


@pytest.mark.parametrize("bad", [None, {}, {"list": "file.png"}, {"list": [], "BaseUrlProd": "ftp://x"},
                                {"list": [], "BaseUrlProd": "https://user:pass@x"},
                                {"list": [], "BaseUrlProd": "https://x?a=b"}])
def test_malformed_manifest_rejected(bad):
    with pytest.raises(ValueError):
        SnapshotCDN(bad)


def test_file_and_metadata_block_accept_wrapped_and_unwrapped_content(tmp_path):
    file = tmp_path / "CDNSnapshots.meta"
    file.write_text(json.dumps(manifest()), encoding="utf-8-sig")
    assert SnapshotCDN.from_file(file).available(CAR)
    block = MetadataBlock("CDNSnapshots", "hash", "", manifest())
    assert SnapshotCDN(block).cars == SnapshotCDN(manifest()["CDNSnapshots"]).cars


def metadata_session():
    return Session(Response(document={"responseCode": 0, "responseData": {"blocks": [
        {"id": "CDNSnapshots", "hash": "hash", "data": json.dumps(manifest())},
    ]}}))


def test_fetches_manifest_through_existing_metadata_protocol():
    session = metadata_session()
    client = MetadataClient(session=session)
    s = SnapshotCDN.from_metadata("test-player", "6.8.0", client=client)
    assert s.available(CAR)
    method, url, args = session.calls[0]
    assert method == "POST" and url == client.url
    body = parse_qs(args["data"].decode())
    assert json.loads(body["blockTypes"][0]) == [{"id": "CDNSnapshots", "hash": "0" * 32}]
    assert b"zid=test-player" in args["data"] and b"productVersion=6.8.0" in args["data"]
    assert not session.closed


def test_cdn_integration_uses_attached_zid_and_version_without_asset_database():
    session = metadata_session()
    with CDN(zid="test-player", product_version="6.8.0", session=session) as cdn:
        with cdn.get_snapshots() as s:
            assert s.session is session
            assert s.available(CAR)
        assert len(session.calls) == 1 and not session.closed


def test_missing_zid_and_missing_metadata_fail_clearly():
    with pytest.raises(MissingZidError):
        SnapshotCDN.from_metadata("", "6.8.0")
    client = MetadataClient(session=Session(Response(document={"responseCode": 0})))
    with pytest.raises(MetadataError, match="did not return"):
        SnapshotCDN.from_metadata("test-player", "6.8.0", client=client)


def test_download_and_atomic_save(tmp_path):
    response = Response()
    session = Session(response)
    s = SnapshotCDN(manifest(), session=session, timeout=12)
    target = tmp_path / "nested" / "car.png"
    assert s.download_snapshot_to(CAR, target, "GACHA") == target
    assert target.read_bytes() == PNG and response.closed
    assert session.calls[0][2]["timeout"] == 12
    assert not list(target.parent.glob("*.part"))
    s.close()
    assert not session.closed


@pytest.mark.parametrize("status", [403, 404, 410, 500])
def test_failed_download_preserves_existing_file_and_http_status(tmp_path, status):
    response = Response(status=status)
    s = SnapshotCDN(manifest(), session=Session(response))
    target = tmp_path / "car.png"
    target.write_bytes(b"previous")
    with pytest.raises(SnapshotError) as exc:
        s.download_snapshot_to("Unlisted_Car_2030", target)
    assert exc.value.status_code == status and "Unlisted_Car_2030" in exc.value.path
    assert target.read_bytes() == b"previous" and response.closed


def test_network_failure_and_html_200_are_not_returned_as_images():
    with pytest.raises(SnapshotError) as exc:
        SnapshotCDN(manifest(), session=Session(requests.Timeout("timeout"))).download_snapshot(CAR)
    assert exc.value.status_code is None
    response = Response(body=b"<html>not found</html>")
    with pytest.raises(SnapshotError, match="not a PNG"):
        SnapshotCDN(manifest(), session=Session(response)).download_snapshot(CAR)
    assert response.closed


def test_owned_session_closed(monkeypatch):
    session = Session()
    monkeypatch.setattr("csr2cdn.snapshots._http.build_session", lambda: session)
    with SnapshotCDN(manifest()) as s:
        s.download_snapshot(CAR)
    assert session.closed


def test_cli_file_manifest_list_and_reversed_url(tmp_path, capsys):
    file = tmp_path / "CDNSnapshots.meta"
    file.write_text(json.dumps(manifest()))
    assert main(["snapshots", "--manifest", str(file), "--search", "apollo"]) == 0
    assert set(json.loads(capsys.readouterr().out)) == {CAR}
    assert main(["snapshot", CAR, "--manifest", str(file), "--reversed"]) == 0
    assert "_mDEFAULT_REVERSED.png" in capsys.readouterr().out
    assert main(["snapshot", CAR, "--manifest", str(file), "--kind", "PRIZE", "--reversed"]) == 1
    assert "DEFAULT" in capsys.readouterr().err


def test_bundled_block_ids_and_user_catalogue(tmp_path):
    ids = metadata_block_ids()
    assert len(ids) == len(set(ids)) == 277
    assert "CDNSnapshots" in ids and "FeatureKillswitches" in ids
    file = tmp_path / "block_ids.json"
    file.write_text('["NewBlock", "CDNSnapshots", "NewBlock"]')
    assert metadata_block_ids(file) == ["NewBlock", "CDNSnapshots"]
    file.write_text('{"not": "a list"}')
    with pytest.raises(ValueError):
        metadata_block_ids(file)


def test_arbitrary_new_car_and_new_directory_resolution_are_discovered():
    exact = path("NeverSeenManufacturer_NewModel_2042", mode="GACHA_CAR",
                 prefix="new-layout/v7/").replace("_s512_", "_s2048_")
    s = SnapshotCDN(manifest([exact, "Default/Another_NewPlaceholder_2042.png"]))
    assert s.available("NeverSeenManufacturer_NewModel_2042", "GACHA")
    assert s.snapshot_path("Unknown_Car_2043", "GACHA") == exact.replace(
        "NeverSeenManufacturer_NewModel_2042", "Unknown_Car_2043")
    assert s.available("Another_NewPlaceholder_2042")
    assert s.snapshot_path("NeverSeenManufacturer_NewModel_2042", "GACHA", strict=True) == exact


def test_refresh_replaces_cars_paths_flags_and_endpoint_without_stale_entries(tmp_path):
    file = tmp_path / "CDNSnapshots.meta"
    file.write_text(json.dumps(manifest()))
    s = SnapshotCDN.from_file(file)
    new = manifest([path("Future_Car_2042", mode="PRIZE_CAR", prefix="v2/")])
    new["CDNSnapshots"]["BaseUrlProd"] = "https://new.example/images"
    file.write_text(json.dumps(new))
    s.refresh()
    assert set(s.cars) == {"Future_Car_2042"}
    assert s.cars["Future_Car_2042"] == dict(GACHA=False, PRIZE=True, DEFAULT=False, DEFAULT_REVERSED=False)
    assert s.snapshot_url("Future_Car_2042", "PRIZE").startswith("https://new.example/images/v2/")
    assert s.snapshot_path("Unlisted_Car_2044", "PRIZE").startswith("v2/")
    file.write_text("invalid JSON")
    with pytest.raises(ValueError):
        s.refresh()
    assert set(s.cars) == {"Future_Car_2042"}
    assert s.base_url == "https://new.example/images"


def test_metadata_refresh_refetches_source_and_preserves_borrowed_session():
    session = metadata_session()
    client = MetadataClient(session=session)
    s = SnapshotCDN.from_metadata("test-player", "6.8.0", client=client, session=session)
    session.response.document["responseData"]["blocks"][0]["data"] = manifest([
        path("New_Car_2044", mode="GACHA_CAR")])
    s.refresh()
    assert set(s.cars) == {"New_Car_2044"}
    assert len(session.calls) == 2 and not session.closed
    s.close()
    assert not session.closed


def test_explicit_refresh_validates_before_replacing_state_and_empty_manifest_clears():
    s = SnapshotCDN(manifest())
    with pytest.raises(ValueError, match="supply a manifest"):
        s.refresh()
    with pytest.raises(ValueError):
        s.refresh({"list": ["../bad"], "BaseUrlProd": "https://new.example"})
    assert s.available(CAR)
    s.refresh(manifest([]))
    assert s.cars == {} and s.paths == ()
    assert s.snapshot_path("Unlisted_Car_2044") == path("Unlisted_Car_2044")


def test_metadata_accepts_future_block_not_in_bundled_seed():
    session = metadata_session()
    client = MetadataClient(session=session)
    client.get(["FutureBlock2045"], "test-player", "6.8.0")
    body = parse_qs(session.calls[0][2]["data"].decode())
    assert json.loads(body["blockTypes"][0])[0]["id"] == "FutureBlock2045"
