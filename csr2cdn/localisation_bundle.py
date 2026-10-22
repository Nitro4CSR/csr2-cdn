"""Offline decoder for the observed CSR2 UnityFS English localisation asset.

Source evidence: Localisation_EN.ASTC.6312 (UnityFS v8, Unity 2022.3.62f2)
contains a TranslationDataAsset_Localisation_EN MonoBehaviour. Its string data
consists of an asset name, language code, project, project version, then two
parallel arrays of Unity-aligned UTF-8 strings (keys and translations).
This schema was derived from real game data, unlike the separate FlatBuffers
layout-dependent reader; it must not be generalized to other bundle shapes.
No network access. The package does not redistribute the game asset.
"""
from __future__ import annotations

import re
import struct
from pathlib import Path
from typing import Optional

from .game_labels import GameCarTranslations
from .service_prestige_unityfs import load_unityfs

_MAX_BUNDLE = 32 * 1024 * 1024
_MAX_NODE = 32 * 1024 * 1024
_MAX_STR = 4096
_MAX_ITEMS = 50000
_CAR = re.compile(r"TEXT_CAR_(.+)_(SHORT|MEDIUM|LONG)\Z")


class LocalisationSourceError(ValueError):
    """Missing, inconsistent, oversized or unsupported game translation data."""


def _u32(buf: bytes, pos: int) -> int:
    if pos < 0 or pos + 4 > len(buf):
        raise LocalisationSourceError("invalid Unity serialized field boundary")
    return struct.unpack_from("<I", buf, pos)[0]


def _unity_string(buf: bytes, pos: int) -> tuple[str, int]:
    size = _u32(buf, pos)
    start = pos + 4
    if size > _MAX_STR or start + size > len(buf):
        raise LocalisationSourceError("invalid Unity string length")
    try:
        value = buf[start:start + size].decode("utf-8")
    except UnicodeDecodeError:
        raise LocalisationSourceError("invalid Unity UTF-8") from None
    return value, (start + size + 3) & ~3


def _unity_strings(buf: bytes, pos: int) -> tuple[list[str], int]:
    count = _u32(buf, pos)
    if count < 1 or count > _MAX_ITEMS:
        raise LocalisationSourceError("invalid translation array size")
    pos += 4
    values = []
    for _ in range(count):
        value, pos = _unity_string(buf, pos)
        values.append(value)
    return values, pos


def _get_text_pairs(node: bytes, *, language: str) -> list[tuple[str, str]]:
    # Serialized Unity file header format 22: extended data offset at byte 32.
    if len(node) < 128 or len(node) > _MAX_NODE or struct.unpack_from(">I", node, 8)[0] != 22:
        raise LocalisationSourceError("unsupported Unity serialized-file format")
    data_offset = struct.unpack_from(">Q", node, 32)[0]
    if not 48 <= data_offset < len(node):
        raise LocalisationSourceError("invalid Unity serialized data offset")
    name = f"TranslationDataAsset_Localisation_{language}".encode("ascii")
    positions = []
    search = int(data_offset)
    while True:
        at = node.find(name, search)
        if at < 0:
            break
        search = at + len(name)
        if at >= data_offset + 4 and _u32(node, at - 4) == len(name):
            positions.append(at - 4)
    if len(positions) != 1:
        raise LocalisationSourceError("unique translation asset not found")
    start = positions[0]
    label, pos = _unity_string(node, start)
    locale, pos = _unity_string(node, pos)
    project, pos = _unity_string(node, pos)
    _project_version, pos = _unity_string(node, pos)
    if label != name.decode("ascii") or locale != language or project != "CSR2":
        raise LocalisationSourceError("translation asset identity mismatch")
    keys, pos = _unity_strings(node, pos)
    values, pos = _unity_strings(node, pos)
    if len(keys) != len(values) or len(keys) != len(set(keys)):
        raise LocalisationSourceError("translation arrays differ or duplicate keys")
    if not all(key and len(key) <= 512 for key in keys):
        raise LocalisationSourceError("invalid translation key")
    return list(zip(keys, values))


def decode_localisation_unityfs(raw: bytes, *, language: str = "EN",
                                expected_model_keys: tuple[str, ...] = ()) -> GameCarTranslations:
    """Extract display-ready SHORT/MEDIUM/LONG vehicle names from a real UnityFS.

    Surrounding whitespace is trimmed for display; interior characters, case,
    non-breaking spaces and punctuation are retained. Missing styles stay None.
    No fallback from a missing MEDIUM to another style is performed.
    """
    if type(raw) is not bytes or not 64 <= len(raw) <= _MAX_BUNDLE:
        raise LocalisationSourceError("unsupported or oversized localisation bundle")
    if language != "EN":
        raise LocalisationSourceError("only the observed EN source is supported")
    try:
        _engine, _generator, version, nodes = load_unityfs(raw)
    except (ValueError, IndexError, struct.error, KeyError, OSError) as exc:
        raise LocalisationSourceError("UnityFS decoding failed") from None
    if version != 8 or len(nodes) != 1:
        raise LocalisationSourceError("unsupported UnityFS version or node count")
    _node_name, payload = nodes[0]
    pairs = _get_text_pairs(payload, language=language)
    cars: dict[str, dict[str, str]] = {}
    for key, value in pairs:
        match = _CAR.fullmatch(key)
        if not match:
            continue
        model, style = match.groups()
        if not model:
            raise LocalisationSourceError("empty car identifier")
        display = value.strip()
        if not display:
            raise LocalisationSourceError("empty car translation variant")
        cars.setdefault(model, {})[style] = display
    if not cars or any(type(k) is not str or not k or k not in cars for k in expected_model_keys):
        raise LocalisationSourceError("car name keys absent or expected identifiers unavailable")
    try:
        return GameCarTranslations.from_manifest({"format": "csr2cdn.car-translations.v1",
                                                 "records": [{"model_key": model, **styles}
                                                             for model, styles in cars.items()]})
    except ValueError:
        raise LocalisationSourceError("decoded names exceed display-name contract") from None


def load_localisation_unityfs(path: str | Path, *, language: str = "EN",
                              expected_model_keys: tuple[str, ...] = ()) -> GameCarTranslations:
    """Read a bounded local game bundle without invoking CDN or game endpoints."""
    file = Path(path)
    if not file.is_file() or not 64 <= file.stat().st_size <= _MAX_BUNDLE:
        raise LocalisationSourceError("local translation bundle missing or oversized")
    return decode_localisation_unityfs(file.read_bytes(), language=language,
                                       expected_model_keys=expected_model_keys)
