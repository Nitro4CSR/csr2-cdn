"""The version -> branch discovery chain: patterns, store sources, probing."""


import pytest

from csr2cdn import CDN, MetadataClient, patterns, resolve_branch, store
from csr2cdn.errors import BranchNotFoundError, MissingZidError, StoreVersionError

from test_csr2cdn import FakeResponse, FakeSession

# Every branch name seen in the historical databases, with what it parses to.
HISTORICAL = [
    ("4_0_0_Release_OTA_2", patterns.OTA, 2, "4.0.0"),
    ("4_0_0_Release_Preemptive_OTA", patterns.PREEMPTIVE, None, "4.0.0"),
    ("4_0_1_Release_Preemptive_OTA", patterns.PREEMPTIVE, None, "4.0.1"),
    ("4_1_0_Release", patterns.RELEASE, None, "4.1.0"),
    ("4_1_0_Release_OTA_1", patterns.OTA, 1, "4.1.0"),
    ("4_2_0_Release", patterns.RELEASE, None, "4.2.0"),
    ("4_2_0_Release_OTA_1", patterns.OTA, 1, "4.2.0"),
    ("4_3_0_Release", patterns.RELEASE, None, "4.3.0"),
    ("4_3_0_Release_OTA_1", patterns.OTA, 1, "4.3.0"),
    ("4_3_2_Release_1", patterns.NUMBERED, 1, "4.3.2"),
    ("4_4_0_Release_Preemptive_OTA", patterns.PREEMPTIVE, None, "4.4.0"),
    ("4_5_0_Release", patterns.RELEASE, None, "4.5.0"),
    ("4_5_1_Release_OTA_1", patterns.OTA, 1, "4.5.1"),
    ("6_3_0_Release_OTA_2", patterns.OTA, 2, "6.3.0"),
    ("6_4_0_Release", patterns.RELEASE, None, "6.4.0"),
    ("6_4_1_Release", patterns.RELEASE, None, "6.4.1"),
    ("6_4_1_Release_OTA_1", patterns.OTA, 1, "6.4.1"),
    ("6_5_0_Release", patterns.RELEASE, None, "6.5.0"),
    ("6_7_0_Release_OTA_1", patterns.OTA, 1, "6.7.0"),
]


# -- patterns -------------------------------------------------------------
@pytest.mark.parametrize("name,kind,ordinal,release", HISTORICAL)
def test_parse_every_historical_branch(name, kind, ordinal, release):
    parsed = patterns.parse_branch(name)
    assert parsed is not None
    assert (parsed.kind, parsed.ordinal, parsed.release) == (kind, ordinal, release)
    assert patterns.build_branch(parsed.version, parsed.kind, parsed.ordinal) == name


def test_non_branch_names_parse_to_none():
    assert patterns.parse_branch("Default_Android") is None
    assert patterns.parse_branch("6_7_0") is None
    assert patterns.parse_branch("") is None


def test_patch_component_is_not_assumed_zero():
    # 4_5_1, 4_3_2 and 6_4_1 all shipped, so a branch name cannot be derived by zeroing.
    assert patterns.release_candidates("4.5.1") == [(4, 5, 1), (4, 5, 0)]
    assert patterns.release_candidates("6.4.1") == [(6, 4, 1), (6, 4, 0)]
    assert patterns.release_candidates("6.7.1", patch_zero_first=True) == [(6, 7, 0), (6, 7, 1)]


def test_successors_of_an_ota_branch():
    names = patterns.successors("6_7_0_Release_OTA_1")
    assert "6_7_0_Release_OTA_1" in names           # itself
    assert "6_7_0_Release_OTA_2" in names           # next OTA
    assert "6_7_0_Release_1" in names               # numbered variant
    assert "6_7_0_Release_Preemptive_OTA" in names  # staged
    assert "6_7_1_Release" in names                 # next patch
    assert "6_8_0_Release" in names                 # next minor
    assert len(names) < 25                          # bounded, not a search


def test_successors_continue_the_ordinal():
    names = patterns.successors("4_0_0_Release_OTA_2", include_self=False)
    assert names[0] == "4_0_0_Release_OTA_3"
    assert "4_0_0_Release_OTA_1" not in names
    assert "4_3_2_Release_2" in patterns.successors("4_3_2_Release_1")


def test_successors_can_skip_preemptive():
    names = patterns.successors("6_7_0_Release", include_preemptive=False)
    assert not any("Preemptive" in name for name in names)


def test_successors_rejects_junk():
    with pytest.raises(ValueError):
        patterns.successors("Default_Android")


# -- store sources --------------------------------------------------------
def test_normalize_release():
    assert store.normalize_release("6.7.1") == "6.7.0"
    assert store.normalize_release("6.7") == "6.7.0"
    with pytest.raises(StoreVersionError):
        store.normalize_release("varies with device")


def test_previous_releases():
    assert store.previous_releases("6.7.0", 2) == ["6.6.0", "6.5.0"]
    assert store.previous_releases("7.0.0", 1) == ["6.9.0"]


def test_latest_store_version_falls_through_dead_sources():
    def broken(app, session=None, timeout=15.0, countries=None):
        raise RuntimeError("503")

    def silent(app, session=None, timeout=15.0, countries=None):
        return None  # Play saying "Varies with device"

    def working(app, session=None, timeout=15.0, countries=None):
        return "6.7.1"

    assert store.latest_store_version(sources=[broken, silent, working]) == "6.7.1"
    with pytest.raises(StoreVersionError):
        store.latest_store_version(sources=[broken, silent])


def test_first_wins_by_default_and_max_looks_further():
    calls = []

    def play(app, **kwargs):
        calls.append("play")
        return "6.7.0"

    def appstore(app, **kwargs):
        calls.append("appstore")
        return "6.7.1"   # the iOS rollout landed first

    # Default: one source, one request.
    assert store.latest_store_version(sources=[play, appstore]) == "6.7.0"
    assert calls == ["play"]

    calls.clear()
    assert store.latest_store_version(sources=[play, appstore], strategy="max") == "6.7.1"
    assert calls == ["play", "appstore"]


def test_custom_sources_may_take_just_the_app():
    def tiny(app):
        return "6.7.1"

    assert store.latest_store_version(sources=[tiny]) == "6.7.1"
    assert store.store_versions(sources=[tiny]) == {"tiny": "6.7.1"}


def test_versions_compare_numerically_not_lexically():
    assert store.newest(["6.9.0", "6.10.0"]) == "6.10.0"
    assert store.newest(["Varies with device", "6.7.1", None]) == "6.7.1"
    assert store.newest(["nonsense"]) is None


def test_app_store_source_reads_the_itunes_lookup_api():
    url = "https://itunes.apple.com/lookup?id=887947640&country=us"
    session = FakeSession({url: FakeResponse({"resultCount": 1, "results": [{"version": "6.7.1"}]})})
    assert store.app_store_version(session=session, countries=["us"]) == "6.7.1"
    assert store.app_store_version(session=FakeSession({}), countries=["us"]) is None


def test_play_asks_one_country_and_the_app_store_asks_several():
    assert store.PLAY_COUNTRIES == ("gb",)
    assert len(store.APP_STORE_DEFAULT_COUNTRIES) > 1


def test_app_store_storefronts_are_fetched_concurrently():
    countries = ["gb", "us", "de", "au", "nz"]
    routes = {
        f"https://itunes.apple.com/lookup?id=887947640&country={c}": FakeResponse(
            {"results": [{"version": "6.7.0" if c != "nz" else "6.7.1"}]}
        )
        for c in countries
    }
    session = FakeSession(routes)
    assert store.app_store_version(session=session, countries=countries) == "6.7.1"
    assert sorted(session.requested) == sorted(routes)


def test_app_store_source_takes_the_newest_storefront():
    session = FakeSession(
        {
            "https://itunes.apple.com/lookup?id=887947640&country=us": FakeResponse(
                {"results": [{"version": "6.7.0"}]}
            ),
            "https://itunes.apple.com/lookup?id=887947640&country=nz": FakeResponse(
                {"results": [{"version": "6.7.1"}]}   # staged rollout reached NZ first
            ),
        }
    )
    assert store.app_store_version(session=session, countries=["us", "nz"]) == "6.7.1"


def test_google_play_uses_one_request_by_default(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_scraper(name, *args, **kwargs):
        if name == "google_play_scraper":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_scraper)
    url = (
        "https://play.google.com/store/apps/details"
        "?id=com.naturalmotion.customstreetracer2&hl=en&gl=gb"
    )
    html = '<script type="application/ld+json">{"softwareVersion": "6.7.1"}</script>'
    session = FakeSession({url: FakeResponse(text=html)})
    assert store.google_play_version(session=session) == "6.7.1"
    assert len(session.requested) == 1


def test_google_play_falls_back_to_parsing_the_listing(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_scraper(name, *args, **kwargs):
        if name == "google_play_scraper":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_scraper)
    url = (
        "https://play.google.com/store/apps/details"
        "?id=com.naturalmotion.customstreetracer2&hl=en&gl=us"
    )
    html = '<script type="application/ld+json">{"softwareVersion": "6.7.1"}</script>'
    session = FakeSession({url: FakeResponse(text=html)})
    assert store.google_play_version(session=session, countries=["us"]) == "6.7.1"


def test_app_ids_default_to_csr2():
    assert store.CSR2.package_id == "com.naturalmotion.customstreetracer2"
    assert store.CSR2.app_store_id == "887947640"
    assert len(store.GOOGLE_PLAY_COUNTRIES) > 100
    assert len(store.APP_STORE_COUNTRIES) > 100


def test_version_parsing_helpers():
    html = '<script type="application/ld+json">{"softwareVersion": "6.7.1"}</script>'
    assert store._ld_json_version(html) == "6.7.1"
    assert store._ld_json_version('<script type="application/ld+json">{"a":1}</script>') is None
    assert store._clean("Varies with device") is None
    assert store._clean("6.7.1") == "6.7.1"


# -- the chain ------------------------------------------------------------
def _killswitch_response(explicit="", preemptive=""):
    return FakeResponse(
        {
            "responseCode": 0,
            "responseData": {
                "blocks": [
                    {
                        "id": "FeatureKillswitches",
                        "hash": "h",
                        "data": {
                            "FeatureKillswitches": {
                                "ExplicitDataBranchName": explicit,
                                "PreemptiveDownloadDataBranchName": preemptive,
                            }
                        },
                    }
                ]
            },
        }
    )


def _cdn(routes, **kwargs):
    session = FakeSession(routes)
    client = CDN(session=session, **kwargs)
    client._metadata = MetadataClient(session=session)
    return client


def _version_route(branch, version):
    return (f"https://csr2.cdn.zynga.com/asset_database_{branch}.version", FakeResponse({"version": version}))


def test_bootstrap_reads_product_version_from_the_base_branch():
    database = [{"product_version": "6.7.81", "branch_name": "6_7_0_Release"}, []]
    routes = dict(
        [
            _version_route("6_7_0_Release", "31146"),
            ("https://csr2.cdn.zynga.com/asset_database.31146.json", FakeResponse(database)),
            (MetadataClient().url, _killswitch_response("6_7_0_Release_OTA_1")),
            _version_route("6_7_0_Release_OTA_1", "31951"),
        ]
    )
    cdn = _cdn(routes, zid="1", release_version="6.7.1")
    assert cdn.base_branch == "6_7_0_Release"     # 6_7_1_Release does not exist
    assert cdn.product_version == "6.7.81"
    assert cdn.branch == "6_7_0_Release_OTA_1"


def test_bootstrap_uses_product_version_from_the_version_file_when_present():
    routes = dict(
        [
            _version_route("6_7_0_Release", "31146"),
            (
                "https://csr2.cdn.zynga.com/asset_database_6_7_0_Release.version",
                FakeResponse({"version": "31146", "product_version": "6.7.81"}),
            ),
        ]
    )
    cdn = _cdn(routes, release_version="6.7.0")
    assert cdn.product_version == "6.7.81"  # no database download needed


def test_patch_branch_is_tried_before_the_zeroed_one():
    routes = dict([_version_route("4_5_1_Release", "10701")])
    cdn = _cdn(routes, release_version="4.5.1")
    assert cdn.base_branch == "4_5_1_Release"


def test_older_release_is_used_when_the_store_runs_ahead():
    routes = dict([_version_route("6_6_0_Release", "30000")])
    cdn = _cdn(routes, release_version="6.7.1")
    assert cdn.base_branch == "6_6_0_Release"


def test_no_reachable_base_branch():
    cdn = _cdn({}, release_version="6.7.1")
    with pytest.raises(BranchNotFoundError):
        cdn.base_branch


# -- probing --------------------------------------------------------------
def test_probe_finds_the_newest_branch():
    routes = dict(
        [
            _version_route("6_7_0_Release", "31146"),
            _version_route("6_7_0_Release_OTA_1", "31951"),
            _version_route("6_7_0_Release_OTA_2", "32010"),
        ]
    )
    cdn = _cdn(routes, release_version="6.7.0")
    found = cdn.probe_branches("6_7_0_Release")
    assert found == {
        "6_7_0_Release": 31146,
        "6_7_0_Release_OTA_1": 31951,
        "6_7_0_Release_OTA_2": 32010,
    }
    assert max(found, key=found.get) == "6_7_0_Release_OTA_2"


def test_probing_works_without_a_zid():
    routes = dict(
        [
            _version_route("6_7_0_Release", "31146"),
            _version_route("6_7_0_Release_OTA_1", "31951"),
        ]
    )
    cdn = _cdn(routes, release_version="6.7.0", probe=True)
    assert cdn.branch == "6_7_0_Release_OTA_1"


def test_without_zid_or_probe_it_says_so():
    cdn = _cdn(dict([_version_route("6_7_0_Release", "31146")]), release_version="6.7.0")
    with pytest.raises(MissingZidError):
        cdn.resolve_branch()


def test_probe_finds_an_unannounced_branch():
    # The service still announces OTA_1, but OTA_2 is already uploaded.
    routes = dict(
        [
            _version_route("6_7_0_Release", "31146"),
            _version_route("6_7_0_Release_OTA_1", "31951"),
            _version_route("6_7_0_Release_OTA_2", "32010"),
            (MetadataClient().url, _killswitch_response("6_7_0_Release_OTA_1")),
        ]
    )
    cdn = _cdn(routes, zid="1", release_version="6.7.0", product_version="6.7.81")
    assert cdn.resolve_branch() == "6_7_0_Release_OTA_1"
    assert cdn.resolve_branch(probe=True, refresh=True) == "6_7_0_Release_OTA_2"


def test_preemptive_toggle():
    routes = dict(
        [
            _version_route("6_7_0_Release", "31146"),
            _version_route("6_7_0_Release_OTA_1", "31951"),
            _version_route("6_8_0_Release_Preemptive_OTA", "32500"),
            (
                MetadataClient().url,
                _killswitch_response("6_7_0_Release_OTA_1", "6_8_0_Release_Preemptive_OTA"),
            ),
        ]
    )
    cdn = _cdn(routes, zid="1", release_version="6.7.0", product_version="6.7.81")
    assert cdn.resolve_branch() == "6_8_0_Release_Preemptive_OTA"

    cdn = _cdn(routes, zid="1", release_version="6.7.0", product_version="6.7.81",
               allow_preemptive=False)
    assert cdn.resolve_branch() == "6_7_0_Release_OTA_1"


def test_preemptive_toggle_applies_to_probing_too():
    routes = dict(
        [
            _version_route("6_7_0_Release", "31146"),
            _version_route("6_7_0_Release_Preemptive_OTA", "32500"),
        ]
    )
    cdn = _cdn(routes, release_version="6.7.0", probe=True, allow_preemptive=False)
    assert cdn.resolve_branch() == "6_7_0_Release"


def test_resolve_branch_needs_something_to_go_on():
    with pytest.raises(BranchNotFoundError):
        resolve_branch(cdn=_cdn({}))


# -- convenience on the client -------------------------------------------
def test_get_database_by_version_or_branch_but_not_both():
    document = [{"branch_name": "B", "version": "5"}, [{"code": "X", "version": "2"}]]
    routes = dict(
        [
            _version_route("B", "5"),
            ("https://csr2.cdn.zynga.com/asset_database.5.json", FakeResponse(document)),
        ]
    )
    cdn = _cdn(routes, branch="B")
    assert cdn.get_database(version="5").branch_name == "B"
    assert cdn.get_database(branch="B").branch_name == "B"
    assert cdn.get_database().branch_name == "B"
    with pytest.raises(ValueError):
        cdn.get_database(version="5", branch="B")


def test_download_asset_by_name_looks_up_the_version():
    document = [{"branch_name": "B", "version": "5"}, [{"code": "CarPaintLibrary", "version": "12"}]]
    routes = dict(
        [
            _version_route("B", "5"),
            ("https://csr2.cdn.zynga.com/asset_database.5.json", FakeResponse(document)),
            (
                "https://csr2.cdn.zynga.com/ANDROID/ASTC/CarPaintLibrary.ASTC.12",
                FakeResponse(content=b"bundle"),
            ),
        ]
    )
    cdn = _cdn(routes, branch="B")
    assert cdn.download_asset("CarPaintLibrary") == b"bundle"
    assert cdn.download_asset("carpaintlibrary") == b"bundle"   # case-insensitive
    assert cdn.download_asset("CarPaintLibrary", version=12) == b"bundle"   # int
    assert cdn.download_asset("CarPaintLibrary", version="12") == b"bundle"  # str


def test_download_asset_with_an_explicit_version_skips_the_database():
    routes = {
        "https://csr2.cdn.zynga.com/ANDROID/ASTC/Anything.ASTC.9": FakeResponse(content=b"x")
    }
    cdn = _cdn(routes)  # no branch, no zid, no database
    assert cdn.download_asset("Anything", version=9) == b"x"


def test_metadata_by_name_with_an_attached_zid():
    routes = {MetadataClient().url: _killswitch_response("6_7_0_Release_OTA_1")}
    cdn = _cdn(routes, zid="948", product_version="6.7.81")
    blocks = cdn.get_metadata("FeatureKillswitches")
    assert blocks["FeatureKillswitches"].content["ExplicitDataBranchName"] == "6_7_0_Release_OTA_1"
    assert cdn.killswitches()["ExplicitDataBranchName"] == "6_7_0_Release_OTA_1"
    body = cdn.session.posted[-1][1].decode()
    assert "zid=948" in body and "productVersion=6.7.81" in body


def test_metadata_without_a_zid_says_so():
    cdn = _cdn({}, product_version="6.7.81")
    with pytest.raises(MissingZidError):
        cdn.get_metadata("CollectionSlots")


def test_database_header_branch_wins_over_the_requested_branch():
    # asset_database_6_4_1_Release.version served a database whose header says
    # 6_4_1_Release_OTA_1, so the header is what identifies the data.
    from csr2cdn import AssetDatabase

    document = [{"branch_name": "6_4_1_Release_OTA_1", "version": "26675"}, []]
    routes = dict(
        [
            _version_route("6_4_1_Release", "26675"),
            ("https://csr2.cdn.zynga.com/asset_database.26675.json", FakeResponse(document)),
        ]
    )
    cdn = _cdn(routes)
    database = cdn.get_database(branch="6_4_1_Release")
    assert isinstance(database, AssetDatabase)
    assert database.branch_name == "6_4_1_Release_OTA_1"


def test_use_database_skips_the_download():
    from csr2cdn import AssetDatabase

    database = AssetDatabase.from_json(
        [{"branch_name": "6_7_0_Release_OTA_1"}, [{"code": "X", "version": "3"}]]
    )
    routes = {"https://csr2.cdn.zynga.com/ANDROID/ASTC/X.ASTC.3": FakeResponse(content=b"y")}
    cdn = _cdn(routes)
    cdn.use_database(database)
    assert cdn.branch == "6_7_0_Release_OTA_1"
    assert cdn.download_asset("X") == b"y"
