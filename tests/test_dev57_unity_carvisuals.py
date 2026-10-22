"""Synthetic, offline safety and source-fidelity regressions for Dev57."""
from __future__ import annotations

import json
import lzma
import os
import struct
from pathlib import Path

import pytest

from csr2cdn._research import dev57_unity_carvisuals as m


def _synthetic() -> bytes:
    payload = b"ok, unity"
    compact = lzma.compress(payload, format=lzma.FORMAT_RAW, filters=[{
        "id": lzma.FILTER_LZMA1, "dict_size": 1 << 19, "lc": 3, "lp": 0, "pb": 2}])
    properties = bytes([0x5D]) + struct.pack("<I", 1 << 19)
    return properties + compact


def test_lzma_unity_properties_raw_stream():
    assert m._decompress(_synthetic(), len(b"ok, unity"), 1) == b"ok, unity"


def test_size_mismatch_fails_closed():
    with pytest.raises(m.UnityReadError):
        m._decompress(_synthetic(), 999, 1)


def test_wrong_bundle_magic():
    with pytest.raises(m.UnityReadError):
        m.unpack_unityfs(b"BadData\0")


def test_bundle_size_limit():
    with pytest.raises(m.UnityReadError):
        m.unpack_unityfs(b"0" * (m.MAX_BUNDLE + 1))


def test_serialized_file_version_fails_closed():
    with pytest.raises(m.UnityReadError):
        m.parse_asset(b"0" * 56)


def test_archive_fixture_base_order_is_fixed():
    assert m.ARCHIVED_BASE["CarPaintIDs"] == [1156, 451, 1159, 1160]


def test_archive_fixture_has_eleven_presets():
    assert len(m.ARCHIVED_PRESETS) == 11
    assert m.ARCHIVED_PRESETS[0][0] == 1138


def test_index15_never_auto_resolved(monkeypatch):
    base = {**m.ARCHIVED_BASE, "lockPaintsToIndex": 0, "HasOwnLivery": 0}
    base["GachaConfigs"] = [
        {"PaintID": p, "InteriorID": i, "CalliperID": c, "WheelBundleName": w}
        for p, i, c, w in m.ARCHIVED_PRESETS]
    raw = [1160, 451, 1156, -1, 1164, 1163, 1162, -1,
           1157, 1158, 1161, -1, 1138, 1251, 1247, -1, 1246]
    unlocked = {"UnlockableMilestones": [], "AllUnlockables": {
        "carPaintIDs": raw, "carInteriorIDs": [66],
        "carCalliperIDs": [4], "wheelBundleNames": ["Wheel2A_3D"]}}
    monkeypatch.setattr(m, "unpack_unityfs", lambda _: b"test")
    monkeypatch.setattr(m, "parse_asset", lambda _: (base, unlocked))
    res = m.inspect_bundle(b"test")
    assert res["archive_comparison"]["all_base_arrays_equal"]
    assert res["archive_comparison"]["gacha_paint_interior_calliper_wheel_order_equal"]
    assert res["received_paint_index_15"]["raw_unlockables_array_at_15"] == -1
    assert not res["received_paint_index_15"]["crew_value_to_paint_id_verified"]
    assert not res["production_mapping_changed"]


def test_reader_le_primitives_and_alignment():
    reader = m._Reader(b"\x00\x01\x00\x00\x0a\x00\x00\x00")
    assert reader.read("B") == 0
    reader.align()
    assert reader.read("i") == 10


def test_unknown_compression_rejected():
    with pytest.raises(m.UnityReadError):
        m._decompress(b"payload", 7, 57)


def test_unexpected_string_offset_rejected():
    with pytest.raises(m.UnityReadError):
        m._string_name(b"abc\0", 5)


def test_cli_rejects_existing_output(tmp_path):
    bundle = tmp_path / "bundle"; bundle.write_bytes(b"invalid")
    out = tmp_path / "report.json"; out.write_text("pre-existing")
    with pytest.raises(SystemExit):
        m.main(["--bundle", str(bundle), "--output", str(out)])
    assert out.read_text() == "pre-existing"


@pytest.mark.skipif(not os.getenv("CSR2_DEV57_BUNDLE_TEST_PATH"), reason="operator-supplied Unity bundle optional")
def test_live_operator_bundle_offline():
    f = Path(os.environ["CSR2_DEV57_BUNDLE_TEST_PATH"])
    report = m.inspect_bundle(f.read_bytes())
    assert report["archive_comparison"]["all_base_arrays_equal"] is True
    assert report["archive_comparison"]["gacha_paint_interior_calliper_wheel_order_equal"] is True
    assert report["other_current_visual_configuration"]["all_unlockables_paint_distinct_count"] == 30
    assert report["received_paint_index_15"]["raw_unlockables_array_at_15"] == -1
