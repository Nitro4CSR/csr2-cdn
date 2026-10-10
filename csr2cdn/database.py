"""The asset database: ``[header, [assets]]``.

The CDN serves ``asset_database.{version}.json`` as a two element list. The
first element is a header describing the build, the second is the asset
catalogue::

    [
      {"version": "31951", "product_version": "6.7.81", "branch_name": "...",
       "base_version": 31146, "gusanu_fy_nhin": "...", "cusanu_fy_ass_metel_gloyw": "..."},
      [{"code": "Abarth_500_2014_loda", "type": "1", "version": "12",
        "dependencies": [...], "client_asset": 1,
        "sizes": {"High": 512662, "ASTC": 319147}}, ...]
    ]

Values are kept exactly as they were stored, so ``AssetDatabase.load(path).dumps()``
reproduces the original document byte for byte. Fields that are absent are
reported as their default (:data:`DEFAULT_ASSET_FIELDS`) without being written
into the document; call :meth:`Asset.fill_defaults` if you want them stored.
Header fields listed in :data:`HEADER_FIELDS` always exist and default to
``None``.
"""

from __future__ import annotations

import json
import os
from typing import (
    Any,
    Dict,
    Iterable,
    Iterator,
    List,
    Mapping,
    MutableMapping,
    NamedTuple,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from csr2cdn._naming import alias_for
from csr2cdn.errors import AssetNotFoundError, DatabaseFormatError

#: Header fields that always exist on a database, defaulting to ``None``.
HEADER_FIELDS: Tuple[str, ...] = (
    "version",
    "product_version",
    "branch_name",
    "base_version",
    "gusanu_fy_nhin",
    "cusanu_fy_ass_metel_gloyw",
)

#: Defaults applied to asset fields that are missing from the source JSON.
DEFAULT_ASSET_FIELDS: Dict[str, Any] = {
    "type": "0",
    "version": "0",
    "client_asset": "0",
    "dependencies": [],
    "sizes": {"High": "0", "ASTC": "0"},
}

#: Sizes reported by the database, and therefore the qualities served by the CDN.
DEFAULT_QUALITY = "ASTC"

PathLike = Union[str, "os.PathLike[str]"]


def _copy_default(default: Any) -> Any:
    if isinstance(default, list):
        return list(default)
    if isinstance(default, dict):
        return dict(default)
    return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class Asset:
    """A single entry of the asset catalogue.

    The underlying dictionary stays reachable through :attr:`raw` and edits to
    it are preserved when the database is written back out.
    """

    __slots__ = ("_raw", "_collection")

    def __init__(
        self,
        raw: MutableMapping[str, Any],
        collection: Optional["AssetCollection"] = None,
        fill_defaults: bool = False,
    ):
        if not isinstance(raw, MutableMapping):
            raise DatabaseFormatError(f"asset entry must be an object, got {type(raw).__name__}")
        if "code" not in raw:
            raise DatabaseFormatError("asset entry is missing the 'code' field")
        self._raw = raw
        self._collection = collection
        if fill_defaults:
            self.fill_defaults()

    def fill_defaults(self) -> "Asset":
        """Write the defaults for absent fields into :attr:`raw`.

        Loading a database does not do this, so that writing it back out
        reproduces the source document. Assets created with
        :meth:`AssetDatabase.add_asset` are filled in.
        """
        for field, default in DEFAULT_ASSET_FIELDS.items():
            if field not in self._raw or self._raw[field] is None:
                self._raw[field] = _copy_default(default)
        sizes = self._raw.get("sizes")
        if isinstance(sizes, MutableMapping):
            for quality, default in DEFAULT_ASSET_FIELDS["sizes"].items():
                if sizes.get(quality) is None:
                    sizes[quality] = default
        return self

    def _field(self, name: str) -> Any:
        value = self._raw.get(name)
        if value is None and name in DEFAULT_ASSET_FIELDS:
            return _copy_default(DEFAULT_ASSET_FIELDS[name])
        return value

    # -- stored fields ----------------------------------------------------
    @property
    def raw(self) -> MutableMapping[str, Any]:
        """The underlying JSON object. Mutating it mutates the database."""
        return self._raw

    @property
    def code(self) -> str:
        return self._raw["code"]

    @property
    def alias(self) -> str:
        """The attribute name this asset is reachable under."""
        return alias_for(self.code)

    @property
    def type(self) -> Any:
        return self._field("type")

    @property
    def version(self) -> Any:
        return self._field("version")

    @property
    def client_asset(self) -> Any:
        return self._field("client_asset")

    @property
    def sizes(self) -> Mapping[str, Any]:
        stored = self._raw.get("sizes")
        if not isinstance(stored, Mapping):
            return dict(DEFAULT_ASSET_FIELDS["sizes"])
        merged = dict(DEFAULT_ASSET_FIELDS["sizes"])
        merged.update({k: v for k, v in stored.items() if v is not None})
        return merged

    @property
    def dependency_codes(self) -> List[str]:
        """Dependency codes exactly as stored, which the CDN writes in lowercase."""
        return list(self._raw.get("dependencies") or [])

    # -- derived ----------------------------------------------------------
    @property
    def version_int(self) -> int:
        return _to_int(self.version)

    @property
    def type_int(self) -> int:
        return _to_int(self.type)

    def size(self, quality: str = DEFAULT_QUALITY) -> int:
        """Download size in bytes for *quality*, or 0 when it isn't listed."""
        return _to_int(self.sizes.get(quality))

    @property
    def dependencies(self) -> List["Asset"]:
        """Dependencies resolved against the database, skipping unknown codes."""
        if self._collection is None:
            return []
        resolved = []
        for code in self.dependency_codes:
            asset = self._collection.get(code)
            if asset is not None:
                resolved.append(asset)
        return resolved

    @property
    def missing_dependencies(self) -> List[str]:
        """Dependency codes with no matching asset in this database."""
        if self._collection is None:
            return self.dependency_codes
        return [c for c in self.dependency_codes if self._collection.get(c) is None]

    def walk_dependencies(self, include_self: bool = False) -> List["Asset"]:
        """Every dependency, transitively, in breadth first order."""
        seen = {self.code.lower()}
        out: List[Asset] = [self] if include_self else []
        queue: List[Asset] = list(self.dependencies)
        while queue:
            asset = queue.pop(0)
            key = asset.code.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(asset)
            queue.extend(asset.dependencies)
        return out

    def filename(self, quality: str = DEFAULT_QUALITY) -> str:
        """``{code}.{quality}.{version}``, the name the client downloads."""
        return f"{self.code}.{quality}.{self.version}"

    # -- dunder -----------------------------------------------------------
    def __getitem__(self, field: str) -> Any:
        return self._raw[field]

    def __setitem__(self, field: str, value: Any) -> None:
        if field == "code":
            raise KeyError("rename assets with AssetDatabase.rename_asset()")
        self._raw[field] = value

    def __contains__(self, field: object) -> bool:
        return field in self._raw

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Asset) and other._raw == self._raw

    def __hash__(self) -> int:
        return hash(self.code.lower())

    def __repr__(self) -> str:
        return f"<Asset {self.code!r} version={self.version!r} type={self.type!r}>"


class AssetCollection:
    """The asset catalogue, addressable by attribute, code or alias.

    ::

        database.assets.Lamborghini_AventadorLP7004_2011_loda.version
        database.assets["Localisation_PT-BR"]
        "abarth_500_2014_loda" in database.assets   # case-insensitive

    Lookups are case-insensitive, which matters because dependency lists store
    codes in lowercase while the catalogue does not.
    """

    def __init__(self, entries: Iterable[MutableMapping[str, Any]] = ()):
        self._assets: List[Asset] = []
        self._by_code: Dict[str, Asset] = {}
        self._by_alias: Dict[str, Asset] = {}
        self._alias_conflicts: Dict[str, List[str]] = {}
        for entry in entries:
            self.add(entry)

    # -- population -------------------------------------------------------
    def add(
        self,
        entry: Union[Asset, MutableMapping[str, Any]],
        replace: bool = False,
        fill_defaults: bool = False,
    ) -> Asset:
        """Add an asset from a raw dict or an existing :class:`Asset`."""
        raw = entry.raw if isinstance(entry, Asset) else entry
        asset = Asset(raw, self, fill_defaults=fill_defaults)
        key = asset.code.lower()
        existing = self._by_code.get(key)
        if existing is not None:
            if not replace:
                raise ValueError(f"duplicate asset code {asset.code!r}")
            self.remove(existing.code)
        self._assets.append(asset)
        self._by_code[key] = asset
        alias = asset.alias.lower()
        if alias in self._by_alias:
            self._alias_conflicts.setdefault(alias, [self._by_alias[alias].code]).append(asset.code)
        else:
            self._by_alias[alias] = asset
        return asset

    def remove(self, code: str) -> Asset:
        """Remove and return the asset with *code*."""
        asset = self[code]
        self._assets.remove(asset)
        self._by_code.pop(asset.code.lower(), None)
        alias = asset.alias.lower()
        if self._by_alias.get(alias) is asset:
            del self._by_alias[alias]
            leftovers = [c for c in self._alias_conflicts.pop(alias, []) if c.lower() != asset.code.lower()]
            for other in leftovers:
                other_asset = self._by_code.get(other.lower())
                if other_asset is not None:
                    self._by_alias.setdefault(alias, other_asset)
        return asset

    # -- lookup -----------------------------------------------------------
    def get(self, key: str, default: Optional[Asset] = None) -> Optional[Asset]:
        lowered = key.lower()
        asset = self._by_code.get(lowered)
        if asset is not None:
            return asset
        asset = self._by_alias.get(lowered)
        if asset is not None:
            return asset
        return self._by_alias.get(alias_for(key).lower(), default)

    def __getitem__(self, key: str) -> Asset:
        asset = self.get(key)
        if asset is None:
            raise AssetNotFoundError(f"no asset named {key!r}")
        return asset

    def __getattr__(self, name: str) -> Asset:
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        asset = self.get(name)
        if asset is None:
            raise AttributeError(f"no asset named {name!r}")
        return asset

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and self.get(key) is not None

    def __iter__(self) -> Iterator[Asset]:
        return iter(list(self._assets))

    def __len__(self) -> int:
        return len(self._assets)

    def __dir__(self) -> List[str]:
        return sorted(set(super().__dir__()) | {a.alias for a in self._assets})

    def __repr__(self) -> str:
        return f"<AssetCollection {len(self._assets)} assets>"

    # -- convenience ------------------------------------------------------
    @property
    def codes(self) -> List[str]:
        return [a.code for a in self._assets]

    @property
    def aliases(self) -> List[str]:
        return [a.alias for a in self._assets]

    @property
    def alias_conflicts(self) -> Dict[str, List[str]]:
        """Aliases claimed by more than one code, if a database ever produces any.

        Only the first code keeps the attribute; the others stay reachable
        through ``collection["exact code"]``.
        """
        return {k: list(v) for k, v in self._alias_conflicts.items()}

    def search(self, text: str) -> List[Asset]:
        """Every asset whose code contains *text*, case-insensitively."""
        needle = text.lower()
        return [a for a in self._assets if needle in a.code.lower()]

    def of_type(self, asset_type: Union[str, int]) -> List[Asset]:
        wanted = str(asset_type)
        return [a for a in self._assets if str(a.type) == wanted]

    def total_size(self, quality: str = DEFAULT_QUALITY) -> int:
        return sum(a.size(quality) for a in self._assets)


class DatabaseDiff(NamedTuple):
    """Result of :meth:`AssetDatabase.diff`."""

    added: List[str]
    removed: List[str]
    changed: List[str]

    def __bool__(self) -> bool:
        return bool(self.added or self.removed or self.changed)


class AssetDatabase:
    """An asset database, loaded from the CDN or built from your own JSON."""

    def __init__(
        self,
        header: Optional[Mapping[str, Any]] = None,
        assets: Iterable[MutableMapping[str, Any]] = (),
    ):
        self._header: Dict[str, Any] = dict(header or {})
        for field in HEADER_FIELDS:
            self._header.setdefault(field, None)
        self.assets = AssetCollection(assets)

    # -- construction -----------------------------------------------------
    @classmethod
    def from_json(cls, document: Sequence[Any]) -> "AssetDatabase":
        """Build a database from an already parsed ``[header, [assets]]`` list."""
        if isinstance(document, Mapping):
            raise DatabaseFormatError("expected a [header, [assets]] list, got an object")
        if not isinstance(document, Sequence) or len(document) < 2:
            raise DatabaseFormatError("expected a [header, [assets]] list")
        header, entries = document[0], document[1]
        if header is None:
            header = {}
        if not isinstance(header, Mapping):
            raise DatabaseFormatError(f"header must be an object, got {type(header).__name__}")
        if entries is None:
            entries = []
        if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
            raise DatabaseFormatError(f"asset list must be an array, got {type(entries).__name__}")
        return cls(header, entries)

    @classmethod
    def loads(cls, text: Union[str, bytes]) -> "AssetDatabase":
        """Parse a database from JSON text."""
        return cls.from_json(json.loads(text))

    @classmethod
    def load(cls, source: Union[PathLike, Any]) -> "AssetDatabase":
        """Load a database from a path or an open file object."""
        if hasattr(source, "read"):
            return cls.from_json(json.load(source))
        with open(source, "r", encoding="utf-8") as handle:
            return cls.from_json(json.load(handle))

    # -- header -----------------------------------------------------------
    @property
    def header(self) -> Dict[str, Any]:
        """The raw header object. Mutating it mutates the database."""
        return self._header

    @property
    def version(self) -> Any:
        return self._header.get("version")

    @property
    def product_version(self) -> Any:
        return self._header.get("product_version")

    @property
    def branch_name(self) -> Any:
        return self._header.get("branch_name")

    @property
    def base_version(self) -> Any:
        return self._header.get("base_version")

    @property
    def gusanu_fy_nhin(self) -> Any:
        return self._header.get("gusanu_fy_nhin")

    @property
    def cusanu_fy_ass_metel_gloyw(self) -> Any:
        return self._header.get("cusanu_fy_ass_metel_gloyw")

    @property
    def version_int(self) -> int:
        return _to_int(self.version)

    # -- editing ----------------------------------------------------------
    def add_asset(self, code: str, replace: bool = False, **fields: Any) -> Asset:
        """Add an asset. Missing fields fall back to :data:`DEFAULT_ASSET_FIELDS`."""
        raw: Dict[str, Any] = {"code": code}
        raw.update(fields)
        return self.assets.add(raw, replace=replace, fill_defaults=True)

    def remove_asset(self, code: str) -> Asset:
        return self.assets.remove(code)

    def rename_asset(self, code: str, new_code: str) -> Asset:
        asset = self.assets.remove(code)
        asset.raw["code"] = new_code
        return self.assets.add(asset.raw)

    # -- output -----------------------------------------------------------
    def to_json(self) -> List[Any]:
        """The database as a plain ``[header, [assets]]`` structure."""
        return [self._header, [asset.raw for asset in self.assets]]

    def dumps(self, indent: Optional[int] = None, ensure_ascii: bool = False) -> str:
        separators = (",", ":") if indent is None else None
        return json.dumps(
            self.to_json(), indent=indent, separators=separators, ensure_ascii=ensure_ascii
        )

    def save(self, path: PathLike, indent: Optional[int] = None) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self.dumps(indent=indent))

    # -- comparison -------------------------------------------------------
    def diff(self, other: "AssetDatabase") -> DatabaseDiff:
        """Compare against *other*, which is treated as the older database."""
        mine = {a.code.lower(): a for a in self.assets}
        theirs = {a.code.lower(): a for a in other.assets}
        added = sorted(mine[k].code for k in mine.keys() - theirs.keys())
        removed = sorted(theirs[k].code for k in theirs.keys() - mine.keys())
        changed = sorted(
            mine[k].code
            for k in mine.keys() & theirs.keys()
            if str(mine[k].version) != str(theirs[k].version)
        )
        return DatabaseDiff(added=added, removed=removed, changed=changed)

    def __len__(self) -> int:
        return len(self.assets)

    def __repr__(self) -> str:
        return (
            f"<AssetDatabase branch={self.branch_name!r} version={self.version!r} "
            f"assets={len(self.assets)}>"
        )
