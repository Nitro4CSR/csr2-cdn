"""Offline game-label adapters for CDN-sourced translations and visual libraries.

The game Metadata CDN and its hash-aware MetadataCache are authoritative for
*metadata block freshness* (as seen by the requesting client). Car translation
files / visual-code libraries must be decoded before importing here. Their
actual native wire structures have not been independently observed in this
build, so these strict normalized input formats do not guess game schemas.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional, Tuple

from .customization_evidence import CUSTOMIZATION_BLOCKS, SLOT_FIELDS

_STANDALONE_VISUAL_SLOTS = ("color", "wrap", "livery_set", "tuner_rim",
                            "tire", "boost_color", "livery_zone_mask")

_MAX_ROWS = 20000
_MAX_LABEL = 180


def _text(value: Any, limit: int = _MAX_LABEL) -> bool:
    return (type(value) is str and bool(value.strip()) and value == value.strip()
            and len(value) <= limit and not any(ord(c) < 32 or ord(c) == 127 for c in value))


class CarNameStyle(str, Enum):
    SHORT = "SHORT"
    MEDIUM = "MEDIUM"
    LONG = "LONG"

    @classmethod
    def coerce(cls, value: "CarNameStyle | str") -> "CarNameStyle":
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            raise ValueError("car name style must be SHORT, MEDIUM or LONG")
        try:
            return cls(value.upper())
        except ValueError:
            raise ValueError("car name style must be SHORT, MEDIUM or LONG") from None


class CarDisplayName(str):
    """String-compatible preferred name with exact translation attributes.

    The string value is MEDIUM by default; ``short``, ``medium`` and ``long``
    retain their separate source values. A missing preferred translation is
    represented by an empty string (never a fallback to a different style),
    while the corresponding attribute remains ``None``. Inspect ``medium``
    to distinguish an absent value from a real translation.
    """
    __slots__ = ("short", "medium", "long", "style")

    def __new__(cls, short: Optional[str], medium: Optional[str],
                long: Optional[str], style: CarNameStyle | str = CarNameStyle.MEDIUM):
        selected = CarNameStyle.coerce(style)
        forms = {"SHORT": short, "MEDIUM": medium, "LONG": long}
        result = str.__new__(cls, forms[selected.value] or "")
        result.short = short
        result.medium = medium
        result.long = long
        result.style = selected
        return result

    def for_style(self, style: CarNameStyle | str) -> "CarDisplayName":
        """Change the preferred string representation; retain all three forms."""
        return type(self)(self.short, self.medium, self.long, style)

    @property
    def names(self) -> list[Optional[str]]:
        """Return a new list in SHORT, MEDIUM, LONG order."""
        return [self.short, self.medium, self.long]


@dataclass(frozen=True)
class GameCarName:
    model_key: str = field(repr=False)
    short: Optional[str] = field(default=None, repr=False)
    medium: Optional[str] = field(default=None, repr=False)
    long: Optional[str] = field(default=None, repr=False)

    @property
    def name(self) -> CarDisplayName:
        """MEDIUM string with nested ``.short``, ``.medium``, ``.long``."""
        return CarDisplayName(self.short, self.medium, self.long)

    @property
    def names(self) -> list[Optional[str]]:
        """Three variants in the documented SHORT, MEDIUM, LONG order."""
        return [self.short, self.medium, self.long]

    def choose(self, style: CarNameStyle | str = CarNameStyle.MEDIUM) -> Optional[str]:
        """Legacy selection method; never falls back from an absent style."""
        return getattr(self, CarNameStyle.coerce(style).value.lower())


@dataclass(frozen=True)
class GameCarTranslations:
    """Exact DB-name matching against normalized decoded game translation rows.

    Contract ``csr2cdn.car-translations.v1`` must contain ``records`` of
    ``{model_key, SHORT?, MEDIUM?, LONG?}``. It is an exchange format, not a
    claim that the native translation file uses this structure. A missing
    selected variant is unresolved, not guessed from the DB key.
    """
    records: Tuple[GameCarName, ...] = field(default_factory=tuple, repr=False)
    source: str = "decoded_game_translation_file"

    @classmethod
    def from_manifest(cls, data: Any) -> "GameCarTranslations":
        if not isinstance(data, Mapping) or data.get("format") != "csr2cdn.car-translations.v1":
            raise ValueError("unrecognized game car translation manifest")
        rows = data.get("records")
        if not isinstance(rows, list) or len(rows) > _MAX_ROWS:
            raise ValueError("translation records must be a bounded list")
        seen = set()
        parsed = []
        for row in rows:
            if not isinstance(row, Mapping) or not _text(row.get("model_key")):
                raise ValueError("invalid car translation row")
            key = row["model_key"]
            if key in seen:
                raise ValueError("ambiguous duplicate car model translation")
            seen.add(key)
            fields = []
            for style in CarNameStyle:
                raw = row.get(style.value)
                if raw is not None and not _text(raw):
                    raise ValueError("invalid car name variant")
                fields.append(raw)
            if not any(field is not None for field in fields):
                raise ValueError("car translation requires at least one name variant")
            parsed.append(GameCarName(key, *fields))
        return cls(tuple(parsed))

    def match(self, model_key: Optional[str]) -> Optional[GameCarName]:
        return next((row for row in self.records if row.model_key == model_key), None)


@dataclass(frozen=True)
class VisualCodeName:
    model_key: str = field(repr=False)
    slot: str = ""
    code: int | str = 0
    name: str = field(default="", repr=False)
    source_library: str = ""
    source_hash: Optional[str] = field(default=None, repr=False)
    source_sha256: Optional[str] = field(default=None, repr=False)
    names: Tuple[str, ...] = field(default_factory=tuple, repr=False)


@dataclass(frozen=True)
class GameVisualLibrary:
    """Exact cosmetic visual-code labels extracted from named game libraries.

    Library files must be decoded into the normalized v1 exchange format.
    The record's library and optional metadata hash are provenance, not
    independent proof that a cosmetic name matches the in-game presentation.
    """
    records: Tuple[VisualCodeName, ...] = field(default_factory=tuple, repr=False)

    @classmethod
    def from_manifest(cls, data: Any) -> "GameVisualLibrary":
        if not isinstance(data, Mapping) or data.get("format") != "csr2cdn.visual-code-library.v1":
            raise ValueError("unrecognized visual-code library manifest")
        rows = data.get("records")
        if not isinstance(rows, list) or len(rows) > _MAX_ROWS:
            raise ValueError("visual records must be a bounded list")
        seen = set()
        parsed = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("invalid visual library record")
            model, slot, code, name, source, sha = (
                row.get("model_key"), row.get("slot"), row.get("code"),
                row.get("name"), row.get("source_library"), row.get("metadata_hash"))
            if not _text(model) or type(slot) is not str or slot not in (*SLOT_FIELDS, *_STANDALONE_VISUAL_SLOTS) or not _text(name) or not _text(source):
                raise ValueError("invalid model, visual-code slot, name or source")
            if slot == "wheel":
                if not _text(code):
                    raise ValueError("wheel name codes must be strings")
            elif type(code) is not int or not ((-2**31 <= code < 2**31) if slot == 'wrap' else (0 <= code < 2**31)):
                raise ValueError("visual codes must be nonnegative integer IDs")
            if sha is not None and (type(sha) is not str or len(sha) != 32 or
                                    any(c not in "0123456789abcdef" for c in sha)):
                raise ValueError("metadata hash must be 32 lowercase hex characters")
            k = (model, slot, code)
            if k in seen:
                raise ValueError("ambiguous visual-code mapping")
            seen.add(k)
            parsed.append(VisualCodeName(model, slot, code, name, source, sha))
        return cls(tuple(parsed))

    def match(self, model_key: Optional[str], slot: str, code: Any) -> Optional[VisualCodeName]:
        # Model-specific mappings override global library IDs; they must not
        # silently shadow each other within the same scope.
        for target in (model_key, '*'):
            found = next((r for r in self.records if r.model_key == target and r.slot == slot
                          and type(r.code) is type(code) and r.code == code), None)
            if found is not None:
                return found
        return None


def game_label_report(snapshot: Any, *, names: Optional[GameCarTranslations] = None,
                      visuals: Optional[GameVisualLibrary] = None,
                      style: CarNameStyle | str = CarNameStyle.MEDIUM,
                      show_members: bool = False) -> dict[str, Any]:
    """Privacy-safe coverage; names and visual values only with opt-in."""
    name_style = CarNameStyle.coerce(style)
    if names is not None and not isinstance(names, GameCarTranslations):
        raise TypeError("names must be GameCarTranslations")
    if visuals is not None and not isinstance(visuals, GameVisualLibrary):
        raise TypeError("visuals must be GameVisualLibrary")
    result: dict[str, Any] = {
        "status": "decoded_game_label_candidates",
        "car_name_style": name_style.value,
        "default_car_name_style": CarNameStyle.MEDIUM.value,
        "roster_rows": len(snapshot.members),
        "translation_records": len(names.records) if names is not None else 0,
        "visual_library_records": len(visuals.records) if visuals is not None else 0,
        "visual_label_bindings_present": sum(m.vehicle.visuals is not None for m in snapshot.members),
        "model_keys_present": sum(m.vehicle.model_key is not None for m in snapshot.members),
        "car_names_resolved": 0,
        "visual_codes_present": {slot: 0 for slot in SLOT_FIELDS},
        "visual_codes_resolved": {slot: 0 for slot in SLOT_FIELDS},
        "source_schema_observed_in_game": False,
        "network_requests": 0,
    }
    private = []
    for member in snapshot.members:
        model = member.vehicle.model_key
        # Reuse an explicitly bound name, or resolve a local catalog on demand.
        bound = member.vehicle.translated_names
        match = names.match(model) if names is not None else bound
        name = match.choose(name_style) if match is not None else None
        if name is not None:
            result["car_names_resolved"] += 1
        labels = {}
        appearance = member.vehicle.appearance
        for slot, attr in SLOT_FIELDS.items():
            code = getattr(appearance, attr) if appearance is not None else None
            if code is None:
                continue
            result["visual_codes_present"][slot] += 1
            matched = visuals.match(model, slot, code) if visuals is not None else None
            bound = (getattr(member.vehicle.visuals, slot)
                     if member.vehicle.visuals is not None else None)
            # A bound projection carries the exact code and source provenance.
            # Do not treat a bound label as matching a different raw ID.
            bound_ok = (bound is not None and type(bound.code) is type(code)
                        and bound.code == code and bound.name is not None)
            if matched is not None or bound_ok:
                result["visual_codes_resolved"][slot] += 1
                if show_members:
                    labels[slot] = {"name": matched.name if matched else bound.name,
                                    "source_library": (matched.source_library if matched
                                                       else bound.source_library)}
        if show_members:
            private.append({"car_name": name,
                            "car_names": match.names if match is not None else [],
                            "visual_names": labels})
    if show_members:
        result["member_labels"] = private
    return result


def metadata_library_inventory(cache: Any, names: Tuple[str, ...] = CUSTOMIZATION_BLOCKS) -> dict[str, Any]:
    """Inspect JSON blocks in an existing MetadataCache, never an APK.

    A hash is evidence of the CDN's response version when the file was synced;
    hashes and key names, not raw block data, go into this report.
    """
    from .metadata import MetadataCache
    if not isinstance(cache, MetadataCache):
        raise TypeError("cache must be MetadataCache")
    hashes = cache.hashes(names)
    result = {}
    for name in names:
        if name not in CUSTOMIZATION_BLOCKS:
            raise ValueError("unrecognized customization metadata block")
        value = cache.load(name)
        result[name] = {"cached": value is not None,
                        "metadata_hash_available": name in hashes,
                        "decoded_json_type": (type(value).__name__ if value is not None else None)}
    return {"status": "local_metadata_cdn_cache_inventory", "blocks": result,
            "network_requests": 0, "visual_record_schema_verified": False}
