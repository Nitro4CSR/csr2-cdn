import json

import pytest

from csr2cdn import (
    CDN,
    Asset,
    AssetDatabase,
    AssetNotFoundError,
    MetadataClient,
    MetadataError,
    alias_for,
    resolve_branch,
)

HEADER = {
    "version": "31951",
    "product_version": "6.7.81",
    "branch_name": "6_7_0_Release_OTA_1",
    "base_version": 31146,
    "gusanu_fy_nhin": "a" * 40,
    "cusanu_fy_ass_metel_gloyw": "b" * 40,
}
ASSETS = [
    {
        "code": "Lamborghini_AventadorLP7004_2011_loda",
        "type": "1",
        "version": "6",
        "dependencies": ["lamborghini_aventadorlp7004_2011_shared1"],
        "client_asset": 4,
        "sizes": {"High": 67825, "ASTC": 66120},
    },
    {
        "code": "Lamborghini_AventadorLP7004_2011_shared1",
        "type": "1",
        "version": "6",
        "client_asset": 4,
        "sizes": {"High": 10, "ASTC": 8},
    },
    {"code": "Localisation_PT-BR", "type": "14", "version": "6036", "client_asset": 1,
     "sizes": {"High": 1, "ASTC": 1}},
    {"code": "10A18Nb", "type": "43", "version": "191", "client_asset": 3,
     "sizes": {"High": 2, "ASTC": 2}},
    {"code": "Ford_GT40MkII_1966_Wheel_1_Calliper1_A_~_meshes", "type": "37", "version": "3",
     "client_asset": 4, "sizes": {"High": 3, "ASTC": 3}},
]


@pytest.fixture
def database():
    return AssetDatabase.from_json([HEADER, [dict(a) for a in ASSETS]])


# -- naming ---------------------------------------------------------------
@pytest.mark.parametrize(
    "code,alias",
    [
        ("Lamborghini_AventadorLP7004_2011_loda", "Lamborghini_AventadorLP7004_2011_loda"),
        ("Localisation_PT-BR", "Localisation_PT_BR"),
        ("10A18Nb", "_10A18Nb"),
        ("Ford_GT40MkII_1966_Wheel_1_Calliper1_A_~_meshes", "Ford_GT40MkII_1966_Wheel_1_Calliper1_A_meshes"),
        ("_TNRRims_shared1", "_TNRRims_shared1"),
    ],
)
def test_alias_for(code, alias):
    assert alias_for(code) == alias


# -- addressing -----------------------------------------------------------
def test_attribute_access(database):
    asset = database.assets.Lamborghini_AventadorLP7004_2011_loda
    assert isinstance(asset, Asset)
    assert asset.version == "6"
    assert database.assets.Localisation_PT_BR.code == "Localisation_PT-BR"
    assert database.assets._10A18Nb.code == "10A18Nb"


def test_item_access_and_case_insensitivity(database):
    assert database.assets["Localisation_PT-BR"].type == "14"
    assert database.assets["lamborghini_aventadorlp7004_2011_LODA"].version == "6"
    assert "10a18nb" in database.assets
    with pytest.raises(AssetNotFoundError):
        database.assets["nope"]
    with pytest.raises(AttributeError):
        database.assets.nope


def test_dir_lists_aliases(database):
    names = dir(database.assets)
    assert "Localisation_PT_BR" in names
    assert "_10A18Nb" in names


def test_dependencies_resolve(database):
    asset = database.assets.Lamborghini_AventadorLP7004_2011_loda
    assert [d.code for d in asset.dependencies] == ["Lamborghini_AventadorLP7004_2011_shared1"]
    assert asset.missing_dependencies == []
    assert len(asset.walk_dependencies(include_self=True)) == 2


def test_missing_dependencies(database):
    database.add_asset("Solo", dependencies=["does_not_exist"])
    assert database.assets.Solo.dependencies == []
    assert database.assets.Solo.missing_dependencies == ["does_not_exist"]


# -- header and defaults --------------------------------------------------
def test_header_fields(database):
    assert database.branch_name == "6_7_0_Release_OTA_1"
    assert database.version == "31951"
    assert database.base_version == 31146
    assert database.version_int == 31951


def test_header_fields_default_to_none():
    database = AssetDatabase.from_json([{}, []])
    for field in ("version", "product_version", "branch_name", "base_version",
                  "gusanu_fy_nhin", "cusanu_fy_ass_metel_gloyw"):
        assert getattr(database, field) is None


def test_header_keeps_unknown_keys():
    database = AssetDatabase.from_json([{"something_new": 1}, []])
    assert database.header["something_new"] == 1
    assert database.to_json()[0]["something_new"] == 1


def test_asset_defaults():
    database = AssetDatabase.from_json([{}, [{"code": "Bare"}]])
    asset = database.assets.Bare
    assert asset.version == "0"
    assert asset.type == "0"
    assert asset.client_asset == "0"
    assert asset.dependencies == []
    assert asset.sizes == {"High": "0", "ASTC": "0"}
    assert asset.size("ASTC") == 0


def test_null_and_empty_values_are_accepted():
    database = AssetDatabase.from_json(
        [{"version": None, "branch_name": ""}, [{"code": "X", "version": None, "sizes": {"High": None}}]]
    )
    assert database.version is None
    assert database.branch_name == ""
    assert database.assets.X.version == "0"
    assert database.assets.X.sizes["High"] == "0"


def test_defaults_are_not_written_back():
    document = [{}, [{"code": "Bare"}]]
    database = AssetDatabase.from_json(json.loads(json.dumps(document)))
    assert database.to_json()[1] == [{"code": "Bare"}]
    database.assets.Bare.fill_defaults()
    assert database.to_json()[1][0]["sizes"] == {"High": "0", "ASTC": "0"}


def test_add_asset_fills_defaults(database):
    asset = database.add_asset("NewThing", version="2")
    assert asset.raw == {
        "code": "NewThing",
        "version": "2",
        "type": "0",
        "client_asset": "0",
        "dependencies": [],
        "sizes": {"High": "0", "ASTC": "0"},
    }


# -- round trip and editing ----------------------------------------------
def test_round_trip_is_byte_identical():
    text = json.dumps([HEADER, ASSETS], separators=(",", ":"))
    assert AssetDatabase.loads(text).dumps() == text


def test_remove_and_rename(database):
    database.remove_asset("10A18Nb")
    assert "10A18Nb" not in database.assets
    database.rename_asset("Localisation_PT-BR", "Localisation_PT-PT")
    assert database.assets.Localisation_PT_PT.type == "14"
    assert "Localisation_PT-BR" not in database.assets


def test_duplicate_codes_rejected(database):
    with pytest.raises(ValueError):
        database.add_asset("10A18Nb")
    database.add_asset("10A18Nb", replace=True, version="9")
    assert database.assets._10A18Nb.version == "9"


def test_diff(database):
    older = AssetDatabase.from_json([HEADER, [dict(a) for a in ASSETS[:3]]])
    older.assets["Localisation_PT-BR"].raw["version"] = "1"
    diff = database.diff(older)
    assert diff.added == ["10A18Nb", "Ford_GT40MkII_1966_Wheel_1_Calliper1_A_~_meshes"]
    assert diff.removed == []
    assert diff.changed == ["Localisation_PT-BR"]
    assert bool(diff)


def test_bad_documents():
    from csr2cdn import DatabaseFormatError

    with pytest.raises(DatabaseFormatError):
        AssetDatabase.from_json({"not": "a list"})
    with pytest.raises(DatabaseFormatError):
        AssetDatabase.from_json([{}])
    with pytest.raises(DatabaseFormatError):
        AssetDatabase.from_json([{}, [{"no_code": 1}]])


# -- cdn ------------------------------------------------------------------
class FakeResponse:
    """Stands in for a requests.Response, including its error shape."""

    def __init__(self, payload=None, content=b"", status=200, text=""):
        self._payload = payload
        self.content = content
        self.status = status
        self.status_code = status
        self.text = text

    def json(self):
        return self._payload

    def iter_content(self, chunk_size=65536):
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start : start + chunk_size]

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        pass

    def raise_for_status(self):
        if self.status >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status}", response=self)


class FakeSession:
    def __init__(self, routes):
        self.routes = routes
        self.requested = []
        self.posted = []

    def get(self, url, **kwargs):
        self.requested.append(url)
        if url not in self.routes:
            return FakeResponse(status=404)
        return self.routes[url]

    def head(self, url, **kwargs):
        return self.get(url, **kwargs)

    def post(self, url, data=None, **kwargs):
        self.posted.append((url, data))
        return self.routes[url]

    def close(self):
        pass


def test_cdn_urls():
    cdn = CDN(session=FakeSession({}))
    assert cdn.version_url("B") == "https://csr2.cdn.zynga.com/asset_database_B.version"
    assert cdn.database_url("31951") == "https://csr2.cdn.zynga.com/asset_database.31951.json"
    assert (
        cdn.asset_url("CarPaintLibrary", "12")
        == "https://csr2.cdn.zynga.com/ANDROID/ASTC/CarPaintLibrary.ASTC.12"
    )
    assert cdn.asset_url("X", "1", platform="IOS", quality="High").endswith("/IOS/High/X.High.1")


def test_cdn_fetches_version_and_database(database, tmp_path):
    document = database.to_json()
    session = FakeSession(
        {
            "https://csr2.cdn.zynga.com/asset_database_6_7_0_Release_OTA_1.version": FakeResponse(
                {"version": "31951"}
            ),
            "https://csr2.cdn.zynga.com/asset_database.31951.json": FakeResponse(document),
        }
    )
    cdn = CDN(session=session)
    assert cdn.database_version("6_7_0_Release_OTA_1") == "31951"
    assert cdn.try_database_version("missing") is None
    fetched = cdn.get_database(branch="6_7_0_Release_OTA_1")
    assert fetched.branch_name == "6_7_0_Release_OTA_1"
    assert len(fetched.assets) == len(ASSETS)


def test_download_asset(tmp_path, database):
    asset = database.assets.Lamborghini_AventadorLP7004_2011_loda
    url = f"https://csr2.cdn.zynga.com/ANDROID/ASTC/{asset.code}.ASTC.6"
    cdn = CDN(session=FakeSession({url: FakeResponse(content=b"bundle")}))
    assert cdn.download_asset(asset) == b"bundle"
    path = cdn.download_asset_to(asset, tmp_path)
    assert path.endswith(f"{asset.code}.ASTC.6")
    assert open(path, "rb").read() == b"bundle"


def test_download_assets_reports_failures(tmp_path, database):
    good = database.assets.Lamborghini_AventadorLP7004_2011_loda
    bad = database.assets._10A18Nb
    url = f"https://csr2.cdn.zynga.com/ANDROID/ASTC/{good.code}.ASTC.6"
    cdn = CDN(session=FakeSession({url: FakeResponse(content=b"x")}))
    results = cdn.download_assets([good, bad], tmp_path, workers=2)
    assert isinstance(results[good.code], str)
    assert isinstance(results[bad.code], BaseException)


def test_download_by_code_and_version(tmp_path):
    url = "https://csr2.cdn.zynga.com/ANDROID/ASTC/Code.ASTC.4"
    cdn = CDN(session=FakeSession({url: FakeResponse(content=b"y")}))
    assert cdn.download_asset("Code", version="4") == b"y"
    assert cdn.download_asset("Code", version=4) == b"y"
    assert cdn.download_asset(("Code", "4")) == b"y"
    # A bare name with no version needs a database, which needs a branch or zid.
    from csr2cdn import MissingZidError

    with pytest.raises(MissingZidError):
        cdn.download_asset("Code")


# -- metadata -------------------------------------------------------------
def _metadata_response(blocks, code=0):
    return FakeResponse({"responseCode": code, "responseData": {"blocks": blocks}})


def test_metadata_body_field_order():
    client = MetadataClient(session=FakeSession({}))
    body = client.build_body(["A"], zid="123", product_version="6.7.81")
    keys = [part.split("=", 1)[0] for part in body.split("&")]
    assert keys[:5] == ["protocolVersion", "zid", "productName", "productVersion", "productPlatform"]
    assert "zid=123" in body
    assert "%7B%22id%22%3A%22A%22" in body  # blockTypes is percent encoded


def test_metadata_parses_blocks():
    payload = json.dumps({"CarFusionProfileData": {"a": 1}}, separators=(",", ":"))
    session = FakeSession(
        {
            MetadataClient().url: _metadata_response(
                [{"id": "CarFusionProfileData", "hash": "deadbeef", "data": payload},
                 {"id": "CollectionSlots", "data": None}],
                code=610,
            )
        }
    )
    client = MetadataClient(session=session)
    blocks = client.get(["CarFusionProfileData", "CollectionSlots"], zid="1", product_version="6.7.81")
    assert set(blocks) == {"CarFusionProfileData"}
    block = blocks["CarFusionProfileData"]
    assert block.hash == "deadbeef"
    assert block.text == payload
    assert block.content == {"a": 1}


def test_metadata_rejects_bad_response_code():
    session = FakeSession({MetadataClient().url: _metadata_response([], code=400)})
    client = MetadataClient(session=session)
    with pytest.raises(MetadataError):
        client.get(["A"], zid="1", product_version="6.7.81")


def test_killswitches_and_branch_resolution():
    killswitches = {
        "FeatureKillswitches": {
            "ExplicitDataBranchName": "6_7_0_Release_OTA_1",
            "PreemptiveDownloadDataBranchName": "",
        }
    }
    metadata_session = FakeSession(
        {MetadataClient().url: _metadata_response(
            [{"id": "FeatureKillswitches", "hash": "h", "data": killswitches}]
        )}
    )
    metadata = MetadataClient(session=metadata_session)
    cdn = CDN(
        session=FakeSession(
            {
                "https://csr2.cdn.zynga.com/asset_database_6_7_0_Release_OTA_1.version": FakeResponse(
                    {"version": "31951"}
                )
            }
        )
    )
    assert metadata.killswitches("1", "6.7.81")["ExplicitDataBranchName"] == "6_7_0_Release_OTA_1"
    assert resolve_branch("1", "6.7.81", cdn=cdn, metadata=metadata) == "6_7_0_Release_OTA_1"


def test_resolve_branch_prefers_the_newer_branch():
    killswitches = {
        "FeatureKillswitches": {
            "ExplicitDataBranchName": "6_7_0_Release_OTA_1",
            "PreemptiveDownloadDataBranchName": "6_8_0_Release",
        }
    }
    metadata = MetadataClient(
        session=FakeSession(
            {MetadataClient().url: _metadata_response(
                [{"id": "FeatureKillswitches", "hash": "h", "data": killswitches}]
            )}
        )
    )
    cdn = CDN(
        session=FakeSession(
            {
                "https://csr2.cdn.zynga.com/asset_database_6_7_0_Release_OTA_1.version": FakeResponse(
                    {"version": "31951"}
                ),
                "https://csr2.cdn.zynga.com/asset_database_6_8_0_Release.version": FakeResponse(
                    {"version": "32100"}
                ),
            }
        )
    )
    assert resolve_branch("1", "6.7.81", cdn=cdn, metadata=metadata) == "6_8_0_Release"


def test_resolve_branch_without_announcement_uses_fallback():
    metadata = MetadataClient(
        session=FakeSession(
            {MetadataClient().url: _metadata_response(
                [{"id": "FeatureKillswitches", "hash": "h",
                  "data": {"FeatureKillswitches": {"ExplicitDataBranchName": ""}}}]
            )}
        )
    )
    cdn = CDN(
        session=FakeSession(
            {
                "https://csr2.cdn.zynga.com/asset_database_6_7_0_Release_OTA_1.version": FakeResponse(
                    {"version": "31951"}
                )
            }
        )
    )
    assert (
        resolve_branch("1", "6.7.81", cdn=cdn, metadata=metadata, fallback=["6_7_0_Release_OTA_1"])
        == "6_7_0_Release_OTA_1"
    )

    from csr2cdn import BranchNotFoundError

    with pytest.raises(BranchNotFoundError):
        resolve_branch("1", "6.7.81", cdn=cdn, metadata=metadata)


# -- stubs ----------------------------------------------------------------
def test_stub_generation(tmp_path, database):
    from csr2cdn.stubs import generate

    module, stub = generate(database, tmp_path / "csr2_assets")
    stub_text = open(stub, encoding="utf-8").read()
    assert "Localisation_PT_BR: Asset" in stub_text
    assert "_10A18Nb: Asset" in stub_text
    assert "assets: _Assets" in stub_text

    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("csr2_assets", module)
    generated = importlib.util.module_from_spec(spec)
    sys.modules["csr2_assets"] = generated
    spec.loader.exec_module(generated)
    assert generated.assets.Localisation_PT_BR.code == "Localisation_PT-BR"
    assert generated.database.branch_name == database.branch_name


# -- cli ------------------------------------------------------------------
def test_cli_assets_and_stubs(tmp_path, database, capsys):
    from csr2cdn.cli import main

    path = tmp_path / "db.json"
    database.save(path)
    assert main(["assets", str(path), "--search", "Lamborghini"]) == 0
    out = capsys.readouterr().out
    assert "Lamborghini_AventadorLP7004_2011_loda" in out

    assert main(["stubs", str(path), "--output", str(tmp_path / "gen")]) == 0
    assert (tmp_path / "gen.pyi").exists()
