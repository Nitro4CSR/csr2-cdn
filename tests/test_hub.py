import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from csr2cdn import DEFAULT_HUB_BASE_URL, HUB_CATEGORIES, HubCDN, HubError
from csr2cdn.cli import main


class Response:
    def __init__(self, body=b"", status=200, headers=None, failure=None):
        self.content = body
        self.status_code = status
        self.headers = headers or {}
        self.failure = failure
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code), response=self)

    def iter_content(self, chunk_size):
        yield self.content
        if self.failure:
            raise self.failure

    def close(self):
        self.closed = True


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        self.closed = True


# Examples taken from the v2 CDN content-tree.json. Folder layouts are not a
# single "brand/car.png" convention: flat files, branded snapshots, indexed
# snapshots, Icons groups and Localisation bundles each differ.
@pytest.mark.parametrize("category,name,kwargs,path", [
    ("AssetDatabases", "35391", {}, "AssetDatabases/35391"),
    ("Assets", "assets_client_metadata_217.ASTC", {}, "Assets/assets_client_metadata_217.ASTC"),
    ("CAD", "CarCalliperLibrary.ASTC", {}, "CAD/CarCalliperLibrary.ASTC"),
    ("CGD", "GlobalFlagTextures.ASTC", {}, "CGD/GlobalFlagTextures.ASTC"),
    ("CVD", "Abarth_500_2014", {}, "CVD/Abarth_500_2014"),
    ("Configs", "AppScript_Cars.json", {}, "Configs/AppScript_Cars.json"),
    ("NmgSvcs", "AIDriverNames.json", {}, "NmgSvcs/AIDriverNames.json"),
    ("App", "Addressables/1.5.5/catalog_1.5.5.bin", {}, "App/Addressables/1.5.5/catalog_1.5.5.bin"),
    ("Icons", "AMC_RingbrothersJavelinDefiant_1972_icon", {}, "Icons/Cars/AMC_RingbrothersJavelinDefiant_1972_icon"),
    ("Icons", "ABARTH_icon", {"group": "Manufacturers"}, "Icons/Manufacturers/ABARTH_icon"),
    ("Localisation", "EN", {}, "Localisation/Localisation_EN.ASTC"),
    ("Localisation", "Localisation_DE.ASTC", {}, "Localisation/Localisation_DE.ASTC"),
    ("Gacha", "Abarth_500_2014", {}, "Gacha/ABARTH/Abarth_500_2014.zip"),
    ("Snapshots", "AMC_RingbrothersJavelinDefiant_1972", {}, "Snapshots/AMC/AMC_RingbrothersJavelinDefiant_1972.png"),
    ("SnapshotsFull", "AMC_RingbrothersJavelinDefiant_1972", {}, "SnapshotsFull/AMC/AMC_RingbrothersJavelinDefiant_1972.png"),
    ("SnapshotsFullV2", "Apollo_ProjectEvo_2022", {}, "SnapshotsFullV2/Apollo/Apollo_ProjectEvo_2022.png"),
    ("SnapshotsGacha", "Abarth_500_2014", {"index": 0}, "SnapshotsGacha/ABARTH/Abarth_500_2014/0.png"),
    ("SnapshotsRC", "AstonMartin_DB5Classic_1964", {"index": "00"}, "SnapshotsRC/AstonMartin_DB5Classic_1964/00.png"),
    ("SnapshotsEC", "AstonMartin_DB5Classic_1964", {"index": "0"}, "SnapshotsEC/AstonMartin_DB5Classic_1964/0.png"),
])
def test_blueprint_layouts(category, name, kwargs, path):
    assert HubCDN().path_for(category, name, **kwargs) == path


@pytest.mark.parametrize("prefix,brand", [
    ("MercedesBenz", "Mercedes"), ("MercedesAMG", "Mercedes"),
    ("MercedesAMGF1", "MercedesPetronas"), ("Abarth", "ABARTH"),
    ("GTA", "GTAMotor"), ("Indy", "Indycar"), ("Audi", "Audi"),
])
def test_brand_mapping_and_url_encoding(prefix, brand):
    hub = HubCDN()
    path = hub.snapshot_path(prefix + "_Car")
    assert path == f"Snapshots/{brand}/{prefix}_Car.png"
    assert hub.url_for(path).split("/")[-2] == brand.replace(" ", "%20")
    assert hub.snapshot_path(prefix + "_Car", manufacturer="Custom Brand").startswith("Snapshots/Custom Brand/")


def test_icons_preserve_filename_and_group():
    hub = HubCDN()
    assert hub.icon_path("AMC_Car_2020_icon") == "Icons/Cars/AMC_Car_2020_icon"
    assert hub.icon_path("Mercedes_icon", "Manufacturers") == "Icons/Manufacturers/Mercedes_icon"
    assert hub.icon_path("IconicCars_V1_icon.png", "Collections") == "Icons/Collections/IconicCars_V1_icon.png"
    with pytest.raises(ValueError):
        hub.icon_path("x", "Bogus")


@pytest.mark.parametrize("path", ["", "/foo", "//evil/foo", "../foo", "a/../foo", "a/./foo", "a//b", "a/", "C:/foo", "a\\b", "https://evil/file", "a\x00b"])
def test_unsafe_paths_rejected_before_network_or_writes(path, tmp_path):
    session = Session()
    with pytest.raises(ValueError):
        HubCDN(session=session).download_to(path, tmp_path)
    assert not session.calls
    assert not list(tmp_path.iterdir())


def test_arbitrary_paths_are_quoted_without_query_injection():
    hub = HubCDN(base_url="https://example.test/cdn/")
    assert hub.url_for("Future Folder/a#b?c%20.png") == "https://example.test/cdn/Future%20Folder/a%23b%3Fc%2520.png"
    assert hub.url_for("aCRDB.txt").endswith("/aCRDB.txt")
    assert hub.url_for("UA.PP").endswith("/UA.PP")


@pytest.mark.parametrize("category,kwargs", [
    ("SnapshotsRC", {}), ("SnapshotsEC", {}),
    ("CVD", {"manufacturer": "A"}), ("Snapshots", {"index": "0"}),
    ("CVD", {"group": "Cars"}), ("Future", {}),
])
def test_invalid_layout_arguments(category, kwargs):
    with pytest.raises(ValueError):
        HubCDN().path_for(category, "Car_Name", **kwargs)


def test_config_and_database_use_hub_only():
    session = Session(
        Response(b'\xef\xbb\xbf{"unicode":"hello"}'), Response(b"32652\n"),
        Response(json.dumps([{"version": "32652"}, [{"code": "Car", "version": "3"}]]).encode()),
    )
    hub = HubCDN(session=session, timeout=4, headers={"X-Test": "yes"})
    assert hub.get_config("AppScript_Cars") == {"unicode": "hello"}
    assert hub.get_database().assets.Car.version == "3"
    assert [call[0] for call in session.calls] == [
        DEFAULT_HUB_BASE_URL + path for path in
        ["/Configs/AppScript_Cars.json", "/AssetDatabases/last.ver", "/AssetDatabases/32652"]
    ]
    assert session.calls[0][1]["timeout"] == 4
    assert session.calls[0][1]["headers"]["X-Test"] == "yes"


def test_content_tree_list_dir_and_find():
    tree = {"sha": "abc", "truncated": False, "tree": [
        {"path": "Snapshots", "type": "tree"},
        {"path": "Snapshots/AMC", "type": "tree"},
        {"path": "Snapshots/AMC/AMC_Car_1972.png", "type": "blob", "size": 111},
        {"path": "Snapshots/Audi/Audi_RS5_2014.png", "type": "blob", "size": 222},
        {"path": "AssetDatabases/35391", "type": "blob", "size": 4},
        {"path": "content-tree.json", "type": "blob", "size": 9},
    ]}
    body = json.dumps(tree).encode()
    hub = HubCDN(session=Session(Response(body), Response(body), Response(body)))
    root = {e["name"]: e["type"] for e in hub.list_dir()}
    assert root == {"Snapshots": "tree", "AssetDatabases": "tree", "content-tree.json": "blob"}
    brands = {e["name"]: e["type"] for e in hub.list_dir("Snapshots")}
    assert brands == {"AMC": "tree", "Audi": "tree"}
    assert hub.find("AMC_Car") == ["Snapshots/AMC/AMC_Car_1972.png"]


@pytest.mark.parametrize("version", ["../bad", "", "null", '{"version":12}'])
def test_malformed_database_pointer(version):
    with pytest.raises(HubError):
        HubCDN(session=Session(Response(version.encode()))).get_database()


def test_explicit_database_skips_pointer():
    session = Session(Response(b'[{"version":"29385"},[]]'))
    assert HubCDN(session=session).get_database(29385).version == "29385"
    assert len(session.calls) == 1


@pytest.mark.parametrize("status", [403, 404, 429, 500])
def test_http_errors_preserve_status_and_close(status):
    response = Response(status=status)
    with pytest.raises(HubError) as caught:
        HubCDN(session=Session(response)).download("CVD/Car")
    assert caught.value.status_code == status
    assert caught.value.path == "CVD/Car"
    assert response.closed


def test_network_and_decode_errors():
    with pytest.raises(HubError):
        HubCDN(session=Session(requests.Timeout("timeout"))).download("CVD/Car")
    with pytest.raises(HubError, match="valid JSON"):
        HubCDN(session=Session(Response(b"<html>failure</html>"))).get_json("TextData/CarData.json")
    with pytest.raises(HubError, match="text"):
        HubCDN(session=Session(Response(b"\xff"))).get_text("CVD/Car")


def test_atomic_download_survives_interrupt_and_closes(tmp_path):
    target = tmp_path / "CVD" / "Car"
    target.parent.mkdir()
    target.write_bytes(b"old complete data")
    response = Response(b"partial", failure=requests.ConnectionError("interrupted"))
    with pytest.raises(HubError):
        HubCDN(session=Session(response)).download_to("CVD/Car", tmp_path)
    assert target.read_bytes() == b"old complete data"
    assert not list(tmp_path.rglob("*.part"))
    assert response.closed


def test_download_preserves_directories_or_flattens(tmp_path):
    session = Session(Response(b"one"), Response(b"two"))
    hub = HubCDN(session=session)
    assert hub.download_to("CVD/Car", tmp_path) == tmp_path / "CVD" / "Car"
    assert hub.download_to("CVD/Other", tmp_path, preserve_paths=False) == tmp_path / "Other"


def test_batch_continues_after_failure_and_deduplicates(tmp_path):
    session = Session(Response(b"ok"), Response(status=404), Response(b"last"))
    results = HubCDN(session=session).download_files(["CVD/A", "CVD/A", "CVD/B", "CVD/C"], tmp_path, workers=1)
    assert results["CVD/A"].read_bytes() == b"ok"
    assert isinstance(results["CVD/B"], HubError)
    assert results["CVD/C"].read_bytes() == b"last"
    assert len(session.calls) == 3


def test_sync_conditional_changed_deleted_and_failed(tmp_path):
    session = Session(
        Response(b"first", headers={"ETag": '"one"', "Last-Modified": "yesterday"}),
        Response(status=304), Response(b"changed", headers={"ETag": '"two"'}),
        Response(b"repaired", headers={"ETag": '"three"'}), Response(status=503),
    )
    hub = HubCDN(session=session)
    path = "TextData/CarData.json"
    assert hub.sync_files([path], tmp_path).downloaded == [path]
    assert hub.sync_files([path], tmp_path).unchanged == [path]
    assert session.calls[1][1]["headers"]["If-None-Match"] == '"one"'
    assert session.calls[1][1]["headers"]["If-Modified-Since"] == "yesterday"
    assert hub.sync_files([path], tmp_path).changed
    (tmp_path / path).unlink()
    assert hub.sync_files([path], tmp_path).downloaded == [path]
    assert "If-None-Match" not in session.calls[3][1]["headers"]
    assert path in hub.sync_files([path], tmp_path).failed
    assert (tmp_path / path).read_bytes() == b"repaired"
    manifest = json.loads((tmp_path / ".csr2hub-sync.json").read_text())
    assert manifest["files"][path]["etag"] == '"three"'


def test_sync_no_validators_force_and_changed_base_url(tmp_path):
    session = Session(Response(b"a"), Response(b"b", headers={"ETag": '"b"'}),
                      Response(b"c", headers={"ETag": '"c"'}), Response(b"d"))
    hub = HubCDN(session=session)
    hub.sync_files(["file"], tmp_path)
    hub.sync_files(["file"], tmp_path)
    hub.sync_files(["file"], tmp_path, force=True)
    hub.base_url = "https://other.test"
    hub.sync_files(["file"], tmp_path)
    assert all("If-None-Match" not in kwargs["headers"] for _, kwargs in session.calls)


def test_sync_corrupt_manifest_and_unexpected_304(tmp_path):
    (tmp_path / ".csr2hub-sync.json").write_text("null")
    result = HubCDN(session=Session(Response(status=304))).sync_files(["file"], tmp_path)
    assert isinstance(result.failed["file"], HubError)
    assert not (tmp_path / "file").exists()


def test_sync_reserved_manifest_path(tmp_path):
    session = Session()
    result = HubCDN(session=session).sync_files([".csr2hub-sync.json"], tmp_path)
    assert isinstance(result.failed[".csr2hub-sync.json"], ValueError)
    assert not session.calls


def test_session_ownership(monkeypatch):
    session = Session()
    with HubCDN(session=session):
        pass
    assert not session.closed
    monkeypatch.setattr("csr2cdn.hub._http.build_session", lambda **kwargs: session)
    with HubCDN() as hub:
        assert hub.session is session
    assert session.closed


def test_export_bundle_images_uses_bytes_and_safe_names(tmp_path, monkeypatch):
    inputs = []
    class Image:
        def save(self, target):
            Path(target).write_bytes(b"PNG")
    objects = [SimpleNamespace(type=SimpleNamespace(name=kind), read=lambda: SimpleNamespace(image=Image()))
               for kind in ["TextAsset", "Texture2D", "Sprite"]]
    def load(payload):
        inputs.append(payload)
        return SimpleNamespace(objects=objects)
    monkeypatch.setitem(sys.modules, "UnityPy", SimpleNamespace(load=load))
    paths = HubCDN(session=Session(Response(b"UnityFS"))).export_images("Icons/BC/Mercedes_icon", tmp_path)
    assert inputs == [b"UnityFS"]
    assert [p.name for p in paths] == ["1.png", "2.png"]
    assert all(p.read_bytes() == b"PNG" for p in paths)


def test_export_direct_image_and_missing_extra(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "UnityPy", None)
    hub = HubCDN(session=Session(Response(b"PNG")))
    assert hub.export_images("Icons/BC/icon.png", tmp_path)[0].read_bytes() == b"PNG"
    with pytest.raises(HubError, match="csr2-cdn\\[images\\]"):
        hub.export_images("Icons/BC/Mercedes_icon", tmp_path)


def test_cli_url_categories_and_errors(capsys):
    assert main(["hub", "url", "Gacha/AM General/Car.zip"]) == 0
    assert "AM%20General" in capsys.readouterr().out
    assert main(["hub", "categories"]) == 0
    assert set(capsys.readouterr().out.splitlines()) == set(HUB_CATEGORIES)
    assert main(["hub", "url", "../bad"]) == 1
    assert "error:" in capsys.readouterr().err


def test_cli_get_download_sync_database_snapshot(tmp_path, monkeypatch, capsys):
    session = Session(Response(b'{"ok":true}'), Response(b"one"), Response(status=404),
                      Response(b"sync"), Response(b'[{"version":"12"},[]]'), Response(b"PNG"))
    monkeypatch.setattr("csr2cdn.hub._http.build_session", lambda **kwargs: session)
    assert main(["hub", "get", "version-control.json", "--json"]) == 0
    assert '"ok": true' in capsys.readouterr().out
    assert main(["hub", "download", "CVD/Car", "CVD/Missing", "-o", str(tmp_path), "--workers", "1"]) == 1
    assert main(["hub", "sync", "TextData/CarData.json", "-o", str(tmp_path)]) == 0
    assert main(["hub", "database", "--database-version", "12", "-o", str(tmp_path / "db.json")]) == 0
    assert main(["hub", "snapshot", "AstonMartin_DB5Classic_1964", "--kind", "SnapshotsRC", "--index", "00", "-o", str(tmp_path)]) == 0
    assert (tmp_path / "SnapshotsRC/AstonMartin_DB5Classic_1964/00.png").read_bytes() == b"PNG"
