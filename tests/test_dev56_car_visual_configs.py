"""Synthetic tests: no real repo asset or private roster is bundled."""
import json
import pytest

from csr2cdn._research.dev56_car_visual_configs import (
    _read_local_text, inspect_car_visual_config, parse_car_visual_config, main,
)


def fixture_text():
    vectors = {
        "CarPaintIDs": [11, 24],
        "CarInteriorIDs": [7],
        "CarCalliperIDs": [4],
        "CarLiveryIDs": [30],
        "CarLiveryZonesSetIDs": [0],
        "WheelBundleNames": ["Wheel1A_3D"],
    }
    s = ["MonoBehaviour Base"]
    for key, values in vectors.items():
        s += [f"\tvector {key}", "\t\tArray Array", f"\t\tint size = {len(values)}"]
        for i, value in enumerate(values):
            s += [f"\t\t\t[{i}]", f"\t\t\t{'int' if isinstance(value,int) else 'string'} data = {json.dumps(value)}"]
    s += ["\tCarVisualsGachaConfig GachaConfigs", "\t\tArray Array", "\t\tint size = 2"]
    for i, paint in enumerate([13, 11]):
        s += [f"\t\t\t[{i}]", "\t\t\tCarVisualsGachaConfig data", f"\t\t\t\tint PaintID = {paint}", "\t\t\t\tint InteriorID = 7", "\t\t\t\tint CalliperID = 4", "\t\t\t\tstring WheelBundleName = \"Wheel2A_3D\""]
    s += ["\tint lockPaintsToIndex = 0"]
    return "\n".join(s) + "\n"


def test_parser_preserves_explicit_order():
    parsed = parse_car_visual_config(fixture_text())
    assert parsed["arrays"]["CarPaintIDs"] == [11, 24]
    assert parsed["gacha_configs"][0]["PaintID"] == 13
    assert parsed["gacha_configs"][1]["PaintID"] == 11


def test_out_of_range_is_unresolved_even_if_gacha_has_options():
    r = inspect_car_visual_config(fixture_text().encode(), paint_index=15)
    assert r["paint_index_observation"]["archived_base_candidate_id"] is None
    assert r["distinct_base_plus_gacha_paint_id_count"] == 3
    assert r["crew_paint_index_to_paint_id_verified"] is False
    assert r["mapping_promoted"] is False


def test_in_range_base_candidate_still_not_verified():
    r = inspect_car_visual_config(fixture_text().encode(), paint_index=1)
    assert r["paint_index_observation"]["archived_base_candidate_id"] == 24
    assert not r["paint_index_observation"]["candidate_is_verified_runtime_selection"]


def test_independent_field_mappings_and_wheel_suffix():
    r = inspect_car_visual_config(fixture_text().encode(), interior_id=7, calliper_id=4, wheel_name="SomeCar_Wheel2A_3D", livery_id=654)
    f = r["observed_field_comparisons"]
    assert f["interior"]["present_in_archived_base_array"]
    assert f["calliper"]["gacha_config_occurrences"] == 2
    assert f["wheel"]["gacha_wheel_occurrences"] == 2
    assert not f["wheel"]["base_wheel_match"]
    assert not f["livery"]["present_in_archived_base_array"]
    assert not f["livery"]["roster_to_runtime_join_verified"]
    assert 'SomeCar' not in json.dumps(r)


def test_non_wheel_substring_is_not_match():
    r = inspect_car_visual_config(fixture_text().encode(), wheel_name="Wheelbase2A_3D")
    assert not r["observed_field_comparisons"]["wheel"]["recognized_wheel_bundle_suffix"]


def test_bad_array_size_rejected():
    with pytest.raises(ValueError, match="inconsistent"):
        parse_car_visual_config(fixture_text().replace("\t\tint size = 2", "\t\tint size = 3", 1))


def test_noncontiguous_indices_rejected():
    with pytest.raises(ValueError, match="noncontiguous"):
        parse_car_visual_config(fixture_text().replace("\t\t\t[1]", "\t\t\t[5]", 1))


def test_negative_paint_index_rejected():
    with pytest.raises(ValueError, match="nonnegative"):
        inspect_car_visual_config(fixture_text().encode(), paint_index=-1)


def test_symlinked_source_rejected(tmp_path):
    orig = tmp_path / 'real.txt'
    orig.write_text(fixture_text())
    link = tmp_path / 'linked.txt'
    try:
        link.symlink_to(orig)
    except OSError as e:
        pytest.skip(f'symlink creation unavailable: {e}')
    with pytest.raises(ValueError, match="non-symlinked"):
        _read_local_text(link)


def test_cli_writes_new_redacted_report_and_refuses_overwrite(tmp_path):
    config = tmp_path / 'config.txt'
    output = tmp_path / 'report.json'
    config.write_text(fixture_text())
    assert main(['--config-file',str(config),'--paint-index','15','--output',str(output)]) == 0
    report = json.loads(output.read_text())
    assert report['network_requests'] == 0
    assert report['paint_index_observation']['received_index'] == 15
    with pytest.raises(SystemExit):
        main(['--config-file',str(config),'--output',str(output)])


def test_source_catalogue_presence_does_not_promote_a_mapping():
    catalog = {
        'database_version': '34011',
        'individual_source_ids': [
            {'slot':'paint','numeric_id':11},
            {'slot':'paint','numeric_id':13},
            {'slot':'interior','numeric_id':7},
            {'slot':'calliper','numeric_id':4},
        ]
    }
    report = inspect_car_visual_config(fixture_text().encode(), paint_index=15, source_catalog=catalog)
    assert report['catalogue_source_presence']['paint']['distinct_config_ids'] == 3
    assert report['catalogue_source_presence']['paint']['present_in_source_catalogue'] == 2
    assert report['catalogue_source_presence']['paint']['absent_from_source_catalogue'] == 1
    assert report['catalogue_source_presence']['paint']['presence_is_not_roster_index_mapping']
    assert report['paint_index_observation']['archived_base_candidate_id'] is None
