"""The game's ``rewardType`` vocabulary, from ``RewardTypesInfo``.

Every reward ladder in the metadata — crew cups, collections cups, the Tuner
Cup, tournament milestones — states its payout as a bare integer
``rewardType``. ``RewardTypesInfo.Types`` maps those integers to names, so the
ladders become readable instead of being a wall of numbers.

Two things about that block are worth knowing before trusting it.

**The names are reliable; some of the title ids are not.** Each entry carries a
``RewardType`` name and a ``TitleStringId`` for localisation. For types 46
through 59 the title id is almost always
``TEXT_SP_REWARD_INFO_RACEPASS_PROFILE_BANNER_BACKGROUND_TITLE``, which
localises ``CarCredits``, ``CollectionPoints``, ``TournamentTrophies``,
``LootBox`` and the shields all as "ELITE BANNER". That is an upstream
copy-paste in the game's own data, not a decoding fault, so
:meth:`RewardTypeVocabulary.name` returns the ``RewardType`` name and
:meth:`title_id` is reported as ``suspect`` for that band rather than used.

**The vocabulary has gaps.** Observed ids run 1..63 with 28..37, 41, 42, 57 and
62 absent, and ``rewardType`` 35 is used live by the Tuner Cup ladder while
being undefined here. Those payouts carry a ``name`` of their own
(``EliteTuners_Credits``), so an unknown id with a name is reported as a
flexible currency rather than as an error.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

#: Ids whose ``TitleStringId`` is the mis-pasted profile-banner string. The
#: name is still correct; only the localisation pointer is wrong.
SUSPECT_TITLE_BAND = frozenset(range(46, 60))
#: The exact title id that band wrongly shares.
SUSPECT_TITLE_ID = "TEXT_SP_REWARD_INFO_RACEPASS_PROFILE_BANNER_BACKGROUND_TITLE"
#: Attribute keys seen alongside a reward type, in ladder payout rows.
PAYOUT_ATTRIBUTES = ("partGrade", "UpgradeStage", "matchCurrentCar",
                     "matchLockedInCar", "name", "flexibleCurrencyID")


@dataclass(frozen=True)
class RewardType:
    """One entry of ``RewardTypesInfo.Types``."""
    code: int
    name: str
    title_id: Optional[str] = None

    @property
    def title_is_suspect(self) -> bool:
        """True when this entry's localisation pointer is the known bad one."""
        return (self.code in SUSPECT_TITLE_BAND
                and self.title_id == SUSPECT_TITLE_ID)


@dataclass(frozen=True)
class RewardTypeVocabulary:
    """``rewardType`` integer to name, with the block's own gaps recorded."""
    types: Mapping[int, RewardType] = field(default_factory=dict, repr=False)
    source: str = "RewardTypesInfo.Types"

    def __len__(self) -> int:
        return len(self.types)

    @classmethod
    def from_block(cls, block: Any) -> "RewardTypeVocabulary":
        """Decode ``RewardTypesInfo``. Accepts the block or its ``Types`` map."""
        node = block
        if isinstance(block, Mapping) and "Types" in block:
            node = block["Types"]
        if not isinstance(node, Mapping):
            raise ValueError("RewardTypesInfo must contain a Types mapping")
        out: Dict[int, RewardType] = {}
        for key, row in node.items():
            if not (isinstance(key, str) and key.isdecimal()) and not isinstance(key, int):
                continue
            code = int(key)
            if not isinstance(row, Mapping):
                continue
            name = row.get("RewardType")
            if not isinstance(name, str) or not name.strip():
                continue
            title = row.get("TitleStringId")
            out[code] = RewardType(code, name.strip(),
                                   title if isinstance(title, str) and title else None)
        if not out:
            raise ValueError("RewardTypesInfo yielded no usable reward types")
        return cls(out)

    def get(self, code: Any) -> Optional[RewardType]:
        if isinstance(code, bool) or not isinstance(code, int):
            return None
        return self.types.get(code)

    def name(self, code: Any, attributes: Any = None) -> Optional[str]:
        """The reward's name, or a flexible currency's own name when unlisted.

        Returns None only when the id is neither defined here nor accompanied
        by a name of its own, so a caller can tell "unknown" from "named".
        """
        entry = self.get(code)
        if entry is not None:
            return entry.name
        if isinstance(attributes, Mapping):
            own = attributes.get("name") or attributes.get("flexibleCurrencyID")
            if isinstance(own, str) and own.strip():
                return own.strip()
        return None

    def title_id(self, code: Any) -> Optional[str]:
        """The localisation id, or None when it is the known mis-pasted one."""
        entry = self.get(code)
        if entry is None or entry.title_is_suspect:
            return None
        return entry.title_id

    @property
    def codes(self) -> Tuple[int, ...]:
        return tuple(sorted(self.types))

    @property
    def gaps(self) -> Tuple[int, ...]:
        """Ids absent between the lowest and highest defined id."""
        codes = self.codes
        if not codes:
            return ()
        return tuple(c for c in range(codes[0], codes[-1] + 1) if c not in self.types)

    @property
    def suspect_titles(self) -> Tuple[int, ...]:
        return tuple(c for c, t in sorted(self.types.items()) if t.title_is_suspect)

    def describe(self, code: Any, attributes: Any = None) -> str:
        """A short label for a ladder payout, e.g. ``AftermarketParts [grade 2]``."""
        name = self.name(code, attributes) or "rewardType=%s" % (code,)
        bits = []
        if isinstance(attributes, Mapping):
            grade = attributes.get("partGrade")
            if isinstance(grade, int) and not isinstance(grade, bool):
                bits.append("grade %d" % grade)
            stage = attributes.get("UpgradeStage")
            if isinstance(stage, int) and not isinstance(stage, bool):
                bits.append("stage %d" % stage)
            if attributes.get("matchCurrentCar") is True:
                bits.append("matches current car")
            if attributes.get("matchLockedInCar") is True:
                bits.append("matches locked-in car")
        return "%s [%s]" % (name, ", ".join(bits)) if bits else name
