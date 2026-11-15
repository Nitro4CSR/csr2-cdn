"""Dev89: the Grand Tour season read (`grand_tour/get_season_details`).

Verified live 2026-11-15 (Season 4). The request nests its id under an `extra`
object; the reply gives the shard wallet, the universal-card count, and
per-segment state. Fixture shaped like the live reply, with invented ids.
"""
from __future__ import annotations

import pathlib
import re
from collections import OrderedDict

import pytest

from csr2cdn._service_reads import (
    ReadContract, ReadContractError, grand_tour_contract, prepare_read_contract,
)
from csr2cdn.grand_tour import GrandTourSeason, SCHEDULE_ID
from csr2cdn.service_models import ServiceResponseError


LIVE_GRAND_TOUR = {
    "data": {
        "Shards": 20570, "UniversalCards": 0,
        "GrandTour": {
            "GRAND_TOUR_SEASON_4_SEG_2": {
                "Status": "Started", "StartTime": 1792663200, "Duration": 4838400,
                "ClaimedCardsData": ["S4_Card34", "S4_Card43", "S4_Card10"],
                "StudioPacks": {
                    "GreenPackShards": {"NextPurchasedTime": 1794769829},
                    "BluePackShards": {"NextPurchasedTime": 1794851678},
                    "RedPackShards": {"NextPurchasedTime": 1794776594},
                },
            },
            "GRAND_TOUR_SEASON_3_SEG_2": {
                "Status": "NotCompleted", "StartTime": 1787824800, "Duration": 4838400,
                "ClaimedCardsData": [], "StudioPacks": {},
            },
        },
    },
}


def test_grand_tour_decodes():
    gt = GrandTourSeason.from_response(LIVE_GRAND_TOUR)
    assert gt.shards == 20570
    assert gt.universal_cards == 0
    assert len(gt.segments) == 2


def test_active_segment_is_the_started_one():
    gt = GrandTourSeason.from_response(LIVE_GRAND_TOUR)
    active = gt.active_segment
    assert active.schedule_id == "GRAND_TOUR_SEASON_4_SEG_2"
    assert active.is_started is True
    assert active.claimed_card_count == 3
    assert active.claimed_cards[0] == "S4_Card34"
    assert active.end_time == 1792663200 + 4838400
    assert {p.name for p in active.studio_packs} == {
        "GreenPackShards", "BluePackShards", "RedPackShards"}


def test_studio_pack_next_purchase_time():
    gt = GrandTourSeason.from_response(LIVE_GRAND_TOUR)
    packs = {p.name: p.next_purchased_time for p in gt.active_segment.studio_packs}
    assert packs["GreenPackShards"] == 1794769829


def test_other_segment_is_not_started():
    gt = GrandTourSeason.from_response(LIVE_GRAND_TOUR)
    seg = gt.segment("GRAND_TOUR_SEASON_3_SEG_2")
    assert seg.is_started is False
    assert seg.claimed_card_count == 0
    assert seg.studio_packs == ()


def test_grand_tour_missing_raises():
    with pytest.raises(ServiceResponseError):
        GrandTourSeason.from_response({"data": {"Shards": 1}})  # no GrandTour block


def test_grand_tour_error_envelope_raises():
    with pytest.raises(ServiceResponseError):
        GrandTourSeason.from_response({"error": "invalid params"})


# --------------------------------------------------------------------------
# contract: the nested `extra` body


def test_contract_nests_id_under_extra():
    c = grand_tour_contract("GRAND_TOUR_SEASON_4_SEG_0")
    assert c.route == "grand_tour/get_season_details"
    assert c.request_type == 1
    assert tuple(c.params) == ("app_ver", "extra")
    assert c.params["extra"] == {"activeScheduleId": "GRAND_TOUR_SEASON_4_SEG_0"}


@pytest.mark.parametrize("bad", [
    "", "GRAND_TOUR_SEASON_4", "SEG_0", "grand_tour_season_4_seg_0",
    "GRAND_TOUR_SEASON_4_SEG", 4,
])
def test_contract_rejects_bad_schedule_id(bad):
    with pytest.raises(ReadContractError):
        grand_tour_contract(bad)


def test_schedule_id_pattern_matches_live_ids():
    assert SCHEDULE_ID.fullmatch("GRAND_TOUR_SEASON_4_SEG_2")
    assert not SCHEDULE_ID.fullmatch("GRAND_TOUR_SEASON_4")


def test_allowlist_rejects_tampered_extra():
    bad = ReadContract("grand_tour/get_season_details",
                       OrderedDict([("app_ver", "6.8.0"),
                                    ("extra", {"activeScheduleId": "GRAND_TOUR_SEASON_4_SEG_0",
                                               "injected": 1})]), 1, "x")
    with pytest.raises(ReadContractError):
        prepare_read_contract(None, bad)


def test_allowlist_rejects_non_mapping_extra():
    bad = ReadContract("grand_tour/get_season_details",
                       OrderedDict([("app_ver", "6.8.0"), ("extra", True)]), 1, "x")
    with pytest.raises(ReadContractError):
        prepare_read_contract(None, bad)


def test_service_helper_stays_offline():
    from csr2cdn.services import CSR2Services
    services = CSR2Services("11111111111", allow_network=False)
    c = services.prepare_grand_tour("GRAND_TOUR_SEASON_4_SEG_0")
    assert c.route == "grand_tour/get_season_details"
    assert c.params["extra"]["activeScheduleId"] == "GRAND_TOUR_SEASON_4_SEG_0"


def test_no_real_player_id_in_module():
    import csr2cdn.grand_tour as grand_tour
    text = pathlib.Path(grand_tour.__file__).read_text(encoding="utf-8")
    assert not re.search(r"(?<!\d)\d{11}(?!\d)", text)
