"""Client for the NMG metadata service used by CSR2.

There is no per-file URL. You POST the block ids you want together with the
hash you already hold for each, and the service decides which of them you are
behind on. A block you are current on comes back as ``null`` and is skipped.

``responseCode`` 0 means every block you asked about was served, 610 means
"Partial Success", which is the normal answer once you hold hashes. Anything
else raises :class:`~csr2cdn.errors.MetadataError`.

Every call needs a ``zid``. That is a player id, so you have to supply your
own; this package ships no default.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time
import urllib.parse
from typing import Any, Dict, Iterable, Iterator, List, Mapping, NamedTuple, Optional, Sequence

from csr2cdn import _http

from csr2cdn.errors import MetadataError

DEFAULT_METADATA_URL = "https://csr2-production2-metadata.core.nmgx.co.uk/brewster/v5.php"
DEFAULT_USER_AGENT = "Dalvik/2.1.0 (Linux; U; Android 13; SM-G991B Build/TP1A.220624.014)"

#: The block holding ``ExplicitDataBranchName`` and ``PreemptiveDownloadDataBranchName``.
KILLSWITCHES_BLOCK = "FeatureKillswitches"


def metadata_block_ids(path=None) -> List[str]:
    """Read block IDs from a JSON list, or the bundled 2026-10-14 catalogue.

    This is a discovery seed, not a guarantee that every block is available
    for every player/version. New IDs can still be passed directly to get().
    """
    source = Path(path) if path is not None else Path(__file__).with_name("block_ids.json")
    with source.open(encoding="utf-8-sig") as handle:
        names = json.load(handle)
    if not isinstance(names, list) or any(not isinstance(n, str) or not n.strip() for n in names):
        raise ValueError("block IDs must be a JSON list of nonempty strings")
    return list(dict.fromkeys(names))

PROTOCOL_VERSION = "5"
PRODUCT_NAME = "csr2"
PRODUCT_PLATFORM = "googleplay"
EMPTY_HASH = "0" * 32
_SK = "0" * 40
_PARAM_ORDER = (
    "protocolVersion",
    "zid",
    "productName",
    "productVersion",
    "productPlatform",
    "clientUtc",
    "utcOffset",
    "sk",
    "lastUniqueId",
    "eosEnv",
    "segmentsParams",
    "blockTypes",
    "ducs",
    "a",
)
_PERCENT_ENCODED = {"productName", "productVersion", "lastUniqueId", "blockTypes"}
ACCEPTED_RESPONSE_CODES = frozenset({0, 610})


class MetadataBlock(NamedTuple):
    """One metadata block as served by the metadata service."""

    name: str
    hash: str
    text: str
    data: Any

    @property
    def content(self) -> Any:
        """The inner object, unwrapping the ``{"BlockName": {...}}`` envelope."""
        if isinstance(self.data, Mapping) and self.name in self.data:
            return self.data[self.name]
        return self.data

    def save(self, path) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self.text)


def _utc_offset() -> str:
    offset_hours = -time.timezone / 3600.0
    if time.daylight and time.localtime().tm_isdst:
        offset_hours = -time.altzone / 3600.0
    return "%+.2f" % offset_hours


def _serialize(data: Any) -> str:
    if isinstance(data, str):
        return data
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def _iter_blocks(node: Any) -> Iterator[Mapping[str, Any]]:
    if isinstance(node, Mapping) and "data" in node:
        yield node
    elif isinstance(node, list):
        for item in node:
            yield from _iter_blocks(item)
    elif isinstance(node, Mapping):
        for value in node.values():
            if isinstance(value, (list, Mapping)):
                yield from _iter_blocks(value)


class MetadataClient:
    """Fetches metadata blocks.

    ::

        client = MetadataClient()
        blocks = client.get(["CarFusionProfileData"], zid="948...", product_version="6.7.81")
        blocks["CarFusionProfileData"].content
    """

    def __init__(
        self,
        url: str = DEFAULT_METADATA_URL,
        session: Optional[Any] = None,
        timeout: float = 30.0,
        user_agent: str = DEFAULT_USER_AGENT,
        product_platform: str = PRODUCT_PLATFORM,
        product_name: str = PRODUCT_NAME,
    ):
        self.url = url
        self.timeout = timeout
        self.user_agent = user_agent
        self.product_platform = product_platform
        self.product_name = product_name
        self._session = session
        self._owns_session = session is None

    @property
    def session(self):
        if self._session is None:
            self._session = _http.build_session()
        return self._session

    def close(self) -> None:
        if self._session is not None and self._owns_session:
            self._session.close()
            self._session = None

    def __enter__(self) -> "MetadataClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # -- request building -------------------------------------------------
    def build_body(
        self,
        names: Sequence[str],
        zid: str,
        product_version: str,
        hashes: Optional[Mapping[str, str]] = None,
    ) -> str:
        """The urlencoded POST body, in the field order the service expects."""
        hashes = hashes or {}
        block_types = json.dumps(
            [{"id": name, "hash": hashes.get(name) or EMPTY_HASH} for name in names],
            separators=(",", ":"),
        )
        params = {
            "protocolVersion": PROTOCOL_VERSION,
            "zid": str(zid),
            "productName": self.product_name,
            "productVersion": product_version,
            "productPlatform": self.product_platform,
            "clientUtc": str(int(time.time())),
            "utcOffset": _utc_offset(),
            "sk": _SK,
            "lastUniqueId": "",
            "eosEnv": "",
            "segmentsParams": "{}",
            "blockTypes": block_types,
            "ducs": json.dumps({"hash": "", "cohort": ""}, separators=(",", ":")),
            "a": "1",
        }
        parts = []
        for key in _PARAM_ORDER:
            value = params[key]
            if key in _PERCENT_ENCODED:
                value = urllib.parse.quote(value, safe="")
            parts.append(f"{key}={value}")
        return "&".join(parts)

    # -- requests ---------------------------------------------------------
    def request(
        self,
        names: Sequence[str],
        zid: str,
        product_version: str,
        hashes: Optional[Mapping[str, str]] = None,
    ) -> Dict[str, Any]:
        """POST to the service and return the parsed response document."""
        body = self.build_body(names, zid, product_version, hashes)
        response = self.session.post(
            self.url,
            data=body.encode("utf-8"),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": self.user_agent,
                "Accept-Encoding": "gzip, deflate",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        document = response.json()
        code = document.get("responseCode")
        if code not in ACCEPTED_RESPONSE_CODES:
            raise MetadataError(
                f"metadata service returned responseCode {code}: {document.get('responseMessage')!r}",
                response_code=code,
                response_message=document.get("responseMessage"),
            )
        return document

    def get(
        self,
        names: Iterable[str],
        zid: str,
        product_version: str,
        hashes: Optional[Mapping[str, str]] = None,
    ) -> Dict[str, MetadataBlock]:
        """Fetch *names* and return the blocks that were served.

        Blocks you already hold the current hash for are not returned, since the
        service sends ``null`` for them. Pass ``hashes=None`` to always get
        everything.
        """
        wanted = list(names)
        document = self.request(wanted, zid, product_version, hashes)
        return self.parse(document, wanted)

    def get_one(
        self,
        name: str,
        zid: str,
        product_version: str,
        hashes: Optional[Mapping[str, str]] = None,
    ) -> Optional[MetadataBlock]:
        """Fetch a single block, or ``None`` if the service considered it current."""
        return self.get([name], zid, product_version, hashes).get(name)

    @staticmethod
    def parse(document: Mapping[str, Any], names: Optional[Sequence[str]] = None) -> Dict[str, MetadataBlock]:
        """Pull the served blocks out of a response document."""
        wanted = set(names) if names is not None else None
        blocks: Dict[str, MetadataBlock] = {}
        response_data = document.get("responseData") or {}
        for entry in _iter_blocks(response_data.get("blocks")):
            name = entry.get("id")
            if wanted is not None and name not in wanted:
                continue
            data = entry.get("data")
            if data is None or data == "null":
                continue
            text = _serialize(data)
            parsed = json.loads(text) if isinstance(data, str) else data
            block_hash = entry.get("hash") or hashlib.md5(text.encode("utf-8")).hexdigest()
            blocks[name] = MetadataBlock(name=name, hash=block_hash, text=text, data=parsed)
        return blocks

    # -- convenience ------------------------------------------------------
    def killswitches(self, zid: str, product_version: str) -> Dict[str, Any]:
        """The ``FeatureKillswitches`` block, unwrapped. Empty if unchanged."""
        block = self.get_one(KILLSWITCHES_BLOCK, zid, product_version)
        if block is None:
            return {}
        content = block.content
        return dict(content) if isinstance(content, Mapping) else {}

    def block_names(self, zid: str, product_version: str, names: Iterable[str]) -> List[str]:
        """Which of *names* the service currently has data for."""
        return sorted(self.get(names, zid, product_version))


#: Name of the hash file :class:`MetadataCache` keeps beside the blocks.
HASH_FILE = "hashes.json"


class MetadataCache:
    """Metadata blocks on disk, with the hash bookkeeping done for you.

    The service decides what to send from the hashes you claim to hold, so using
    it well means storing a hash per block and sending it back next time. This
    keeps ``<name>.meta`` files and a ``hashes.json`` in one directory and does
    that for you::

        cache = MetadataCache("./metadata", zid="948...", product_version="6.7.81")
        updated = cache.sync(["CarFusionProfileData", "CollectionSlots"])
        # -> ['CarFusionProfileData']  (the other one was already current)

        data = cache.load("CollectionSlots")

    A hash is only recorded once its file is written, and a hash whose file has
    gone missing is dropped, so deleting a ``.meta`` file is all it takes to
    force a refetch.
    """

    def __init__(
        self,
        directory,
        zid: Optional[str] = None,
        product_version: Optional[str] = None,
        client: Optional[MetadataClient] = None,
        suffix: str = ".meta",
    ):
        self.directory = os.fspath(directory)
        self.zid = str(zid) if zid is not None else None
        self.product_version = product_version
        self.client = client or MetadataClient()
        self.suffix = suffix

    # -- paths ------------------------------------------------------------
    def path(self, name: str) -> str:
        """Where the block named *name* is stored."""
        return os.path.join(self.directory, f"{name}{self.suffix}")

    @property
    def hash_path(self) -> str:
        return os.path.join(self.directory, HASH_FILE)

    # -- state ------------------------------------------------------------
    def hashes(self, names: Optional[Iterable[str]] = None) -> Dict[str, str]:
        """The stored hashes, minus any whose file has gone missing."""
        try:
            with open(self.hash_path, "r", encoding="utf-8") as handle:
                stored = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(stored, Mapping):
            return {}
        wanted = list(names) if names is not None else list(stored)
        out = {}
        for name in wanted:
            value = stored.get(name)
            path = self.path(name)
            if value and os.path.exists(path) and os.path.getsize(path) > 0:
                out[name] = value
        return out

    def save_hashes(self, hashes: Mapping[str, str]) -> None:
        os.makedirs(self.directory, exist_ok=True)
        merged = dict(self.hashes())
        merged.update(hashes)
        temporary = f"{self.hash_path}.part"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(merged, handle, indent=2, sort_keys=True)
        os.replace(temporary, self.hash_path)

    def load(self, name: str) -> Any:
        """The stored block, parsed and unwrapped, or ``None`` if not held."""
        try:
            with open(self.path(name), "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None
        if isinstance(data, Mapping) and name in data:
            return data[name]
        return data

    def stored(self) -> List[str]:
        """Block names currently on disk."""
        if not os.path.isdir(self.directory):
            return []
        return sorted(
            entry[: -len(self.suffix)]
            for entry in os.listdir(self.directory)
            if entry.endswith(self.suffix)
        )

    # -- syncing ----------------------------------------------------------
    def sync(
        self,
        names: Iterable[str],
        zid: Optional[str] = None,
        product_version: Optional[str] = None,
        force: bool = False,
    ) -> List[str]:
        """Fetch *names* and write the ones that changed. Returns their names.

        An empty list means every block you asked about was already current.
        With *force* the stored hashes are ignored and everything comes back.
        """
        wanted = list(names)
        resolved_zid = str(zid) if zid is not None else self.zid
        if not resolved_zid:
            raise MetadataError("a zid is required; pass zid= or MetadataCache(zid=...)")
        version = product_version or self.product_version
        if not version:
            raise MetadataError("a product_version is required")

        blocks = self.client.get(
            wanted,
            zid=resolved_zid,
            product_version=version,
            hashes=None if force else self.hashes(wanted),
        )
        os.makedirs(self.directory, exist_ok=True)
        written = []
        fresh = {}
        for name, block in blocks.items():
            temporary = f"{self.path(name)}.part"
            with open(temporary, "w", encoding="utf-8") as handle:
                handle.write(block.text)
            os.replace(temporary, self.path(name))
            fresh[name] = block.hash
            written.append(name)
        if fresh:
            self.save_hashes(fresh)
        return written

    def __repr__(self) -> str:
        return f"<MetadataCache {self.directory} blocks={len(self.stored())}>"
