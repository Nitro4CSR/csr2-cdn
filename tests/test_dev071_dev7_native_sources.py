"""Offline-only native-format adapters; fixtures are constructed, not observed game samples."""
import json
from pathlib import Path
import struct

import pytest

from csr2cdn.game_labels import GameCarTranslations, GameVisualLibrary
from csr2cdn.metadata import MetadataCache
from csr2cdn.native_game_sources import (
    SourceSchemaError, TranslationLayout, VisualJsonLayout,
    decode_translation_flatbuffer, decode_visual_metadata_cache,
    inspect_metadata_cache, main,
)


LAYOUT = {"format": "csr2cdn.translation-flatbuffer-layout.v1",
          "entries": 0, "model_key": 0, "short": 1, "medium": 2, "long": 3}
VISUAL = {"format": "csr2cdn.visual-json-layout.v1",
          "block": "CarAdditionalVisuals", "records_path": ["paintOptions"],
          "model_field": "model", "slot": "paint", "code_field": "id", "label_field": "label"}


def _align(raw):
    while len(raw) % 4:
        raw.append(0)


def make_translation_blob(rows):
    """Construct a standard FlatBuffers table/vector/string fixture by hand."""
    raw = bytearray(b"\x00" * 8)
    raw.extend(struct.pack("<HHH", 6, 8, 4))
    _align(raw)
    root = len(raw)
    raw.extend(b"\x00" * 8)
    struct.pack_into("<i", raw, root, root - 8)
    _align(raw)
    vector = len(raw)
    raw.extend(struct.pack("<I", len(rows)))
    slots = []
    for _ in rows:
        slots.append(len(raw)); raw.extend(b"\x00" * 4)
    struct.pack_into("<I", raw, root + 4, vector - (root + 4))
    for i, row in enumerate(rows):
        vt = len(raw)
        raw.extend(struct.pack("<HHHHHH", 12, 20, 4, 8, 12, 16))
        _align(raw)
        table = len(raw)
        raw.extend(b"\x00" * 20)
        struct.pack_into("<i", raw, table, table - vt)
        struct.pack_into("<I", raw, slots[i], table - slots[i])
        for index, string in enumerate(row):
            if string is None:
                # Delete corresponding vtable index so field is absent.
                struct.pack_into("<H", raw, vt + 4 + 2 * index, 0)
                continue
            _align(raw)
            ptr = len(raw)
            encoded = string.encode("utf-8")
            raw.extend(struct.pack("<I", len(encoded)))
            raw.extend(encoded + b"\x00")
            struct.pack_into("<I", raw, table + 4 + 4 * index, ptr - (table + 4 + 4 * index))
    struct.pack_into("<I", raw, 0, root)
    return bytes(raw)


def cache_with_visual(tmp_path, data=None):
    directory = tmp_path / "cache"
    directory.mkdir()
    payload = data if data is not None else {"CarAdditionalVisuals": {"paintOptions": [
        {"model": "Car_A", "id": 17, "label": "Pearl Blue"},
        {"model": "Car_B", "id": 9, "label": "Jet Black"},
    ]}}
    (directory / "CarAdditionalVisuals.meta").write_text(json.dumps(payload), encoding="utf-8")
    (directory / "hashes.json").write_text(json.dumps({"CarAdditionalVisuals": "a" * 32}), encoding="utf-8")
    return MetadataCache(directory)


def test_translation_flatbuffer_decodes_exact_variants():
    blob = make_translation_blob([("Car_A", "A", "Automobile A", "Automobile A Extended"),
                                  ("Car_B", "B", "Automobile B", None)])
    lib = decode_translation_flatbuffer(blob, TranslationLayout.from_manifest(LAYOUT), expected_keys=("Car_A",))
    assert isinstance(lib, GameCarTranslations)
    assert lib.match("Car_A").choose() == "Automobile A"
    assert lib.match("Car_A").choose("SHORT") == "A"
    assert lib.match("Car_A").choose("LONG") == "Automobile A Extended"
    assert lib.match("Car_B").choose("LONG") is None
    assert lib.match("car_a") is None


@pytest.mark.parametrize("change", [
    lambda x: x[:-3],
    lambda x: b"\xff\xff\xff\xff" + x[4:],
    lambda x: x[:20] + b"\x00" * 4 + x[24:],
])
def test_flatbuffer_invalid_offsets_and_truncation(change):
    blob = make_translation_blob([("Car_A", "A", "Medium", "Long")])
    with pytest.raises(SourceSchemaError):
        decode_translation_flatbuffer(change(blob), TranslationLayout.from_manifest(LAYOUT))


def test_translation_expected_key_enforced():
    blob = make_translation_blob([("Car_A", "A", "Medium", "Long")])
    with pytest.raises(SourceSchemaError):
        decode_translation_flatbuffer(blob, TranslationLayout.from_manifest(LAYOUT), expected_keys=("Car_C",))


def test_translation_duplicates_and_unknown_names_rejected():
    blob = make_translation_blob([("Car_A", "A", "Medium", "Long"), ("Car_A", "B", "Other", "Long")])
    with pytest.raises(SourceSchemaError):
        decode_translation_flatbuffer(blob, TranslationLayout.from_manifest(LAYOUT))
    with pytest.raises(SourceSchemaError):
        decode_translation_flatbuffer(make_translation_blob([("Car_A", None, None, None)]),
                                      TranslationLayout.from_manifest(LAYOUT))


@pytest.mark.parametrize("field,value", [("entries", -1), ("entries", 128), ("short", "1"), ("long", 1)])
def test_layout_rejects_unverified_indices(field, value):
    obj = dict(LAYOUT); obj[field] = value
    with pytest.raises(SourceSchemaError):
        TranslationLayout.from_manifest(obj)


def test_visual_cache_with_explicit_layout(tmp_path):
    cache = cache_with_visual(tmp_path)
    layout = VisualJsonLayout.from_manifest(VISUAL)
    lib = decode_visual_metadata_cache(cache, (layout,))
    assert isinstance(lib, GameVisualLibrary)
    found = lib.match("Car_A", "paint", 17)
    assert (found.name, found.source_library, found.source_hash) == ("Pearl Blue", "CarAdditionalVisuals", "a" * 32)
    assert lib.match("Car_A", "paint", "17") is None
    assert lib.match("Car_A", "wheel", 17) is None


def test_visual_unknown_json_schema_fails_closed(tmp_path):
    cache = cache_with_visual(tmp_path)
    layout = VisualJsonLayout.from_manifest({**VISUAL, "records_path": ["noSuchKey"]})
    with pytest.raises(SourceSchemaError):
        decode_visual_metadata_cache(cache, (layout,))


def test_visual_duplicate_mappings_fail(tmp_path):
    data = {"paintOptions": [{"model": "Car_A", "id": 17, "label": "Blue"},
                             {"model": "Car_A", "id": 17, "label": "Blue 2"}]}
    cache = cache_with_visual(tmp_path, data)
    with pytest.raises(SourceSchemaError):
        decode_visual_metadata_cache(cache, (VisualJsonLayout.from_manifest(VISUAL),))


def test_visual_cache_hash_required(tmp_path):
    cache = cache_with_visual(tmp_path)
    (Path(cache.directory) / "hashes.json").unlink()
    with pytest.raises(SourceSchemaError):
        decode_visual_metadata_cache(cache, (VisualJsonLayout.from_manifest(VISUAL),))


@pytest.mark.parametrize("key,value", [("slot", "roof"), ("block", "ImaginaryLibrary"),
                                       ("records_path", "paintOptions"), ("code_field", 17)])
def test_visual_layout_validation(key, value):
    obj = dict(VISUAL); obj[key] = value
    with pytest.raises(SourceSchemaError):
        VisualJsonLayout.from_manifest(obj)


def test_shape_inventory_does_not_print_sample_values_or_keys_by_default(tmp_path):
    cache = cache_with_visual(tmp_path)
    report = inspect_metadata_cache(cache, ("CarAdditionalVisuals", "CarPresets"))
    encoded = json.dumps(report)
    assert report["network_requests"] == 0
    assert report["blocks"]["CarPresets"]["cached"] is False
    assert "Car_A" not in encoded and "Pearl Blue" not in encoded
    assert "paintOptions" not in encoded
    shown = inspect_metadata_cache(cache, ("CarAdditionalVisuals",), show_field_names=True)
    assert "paintOptions" in json.dumps(shown)
    assert "Car_A" not in json.dumps(shown)


def test_native_cli_dry_run_and_fails_closed(capsys, tmp_path):
    assert main([]) == 0
    captured = json.loads(capsys.readouterr().out)
    assert captured["network_requests"] == 0
    file = tmp_path / "bad.bin"; file.write_bytes(b"not a flatbuffer")
    layout = tmp_path / "layout.json"; layout.write_text(json.dumps(LAYOUT))
    assert main(["--translation-file", str(file), "--translation-layout-json", str(layout)]) == 2
    captured = json.loads(capsys.readouterr().out)
    assert captured["details"] == "suppressed"
    assert str(file) not in json.dumps(captured)


def test_native_cli_exports_only_with_explicit_opt_in(tmp_path, capsys):
    cache = cache_with_visual(tmp_path)
    visuals = tmp_path / "visual_layouts.json"; visuals.write_text(json.dumps([VISUAL]))
    output = tmp_path / "visuals.json"
    assert main(["--metadata-cache-dir", str(cache.directory), "--visual-layout-json", str(visuals),
                 "--output-visual-json", str(output)]) == 0
    data = json.loads(output.read_text())
    assert data["format"] == "csr2cdn.visual-code-library.v1"
    assert data["records"][0]["name"] == "Pearl Blue"
    assert "Pearl Blue" not in capsys.readouterr().out
    assert main(["--metadata-cache-dir", str(cache.directory), "--visual-layout-json", str(visuals),
                 "--output-visual-json", str(output)]) == 2
    assert "Pearl Blue" not in capsys.readouterr().out


def test_native_cli_translations_output(tmp_path, capsys):
    blob = tmp_path / "translations.flat"; blob.write_bytes(make_translation_blob([("Car_A", "A", "Automobile A", "Automobile A Long")]))
    layout = tmp_path / "layout.json"; layout.write_text(json.dumps(LAYOUT))
    out = tmp_path / "names.json"
    assert main(["--translation-file", str(blob), "--translation-layout-json", str(layout),
                 "--expected-model-key", "Car_A", "--output-translations-json", str(out)]) == 0
    assert GameCarTranslations.from_manifest(json.loads(out.read_text())).match("Car_A").choose() == "Automobile A"
    assert "Automobile A" not in capsys.readouterr().out
