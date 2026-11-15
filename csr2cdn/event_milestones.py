"""Milestone and threshold reward ladders from ``EventMilestoneRewards``.

One block carries 77 reward containers and uses ``WinsRequired`` 3,183 times,
which is how the Tuner Cup, the collections cups and the crew cups all express
their rewards: a ladder of rungs, each needing a count to reach.

**``WinsRequired`` does not always count wins.** It is the wire key and is
kept verbatim, but the quantity appears to differ by family, and two of the
three families most likely do not count wins:

- the collections cup ladders top out at exactly each week's race count
  (44 and 68), which reads as "complete every race"; an inference from the
  numbers, not from client code
- the Tuner Cup's 900 is a combined race count across the crew
- the ``crewcups_*`` / ``cups_*`` families do appear to be genuine wins

So read a rung as "this many of whatever the family counts". ``LadderRung``
exposes ``keyed_value`` for callers that should not care, and the family-
specific meaning is documented per accessor rather than baked into a name.

Families confirmed live on 2026-11-06, with reward names resolved through
:mod:`csr2cdn.reward_types`:

``tuner_cup``
    32 rungs from 1 to **900** -- a combined *race* count across the crew, not
    wins -- paying Cash, Bronze keys, Aftermarket parts by
    grade, Fusion parts matching the current car, Gold, and a flexible
    ``EliteTuners_Credits`` currency whose ``rewardType`` 35 the vocabulary
    block does not define.

``COLLECTIONS_CUP_V2_W1`` / ``COLLECTIONS_CUP_V2_W2``
    Six rungs each, topping out at 44 and 68 *races*. Those are exactly the
    race counts of the two weekly cups, which the ladder and the ladder-event
    group agree on independently -- and which is what identified the quantity
    as races rather than wins. Payouts are Car Credits plus Fusion parts matching
    the *locked-in* car.

``crewcups_*`` / ``cups_*``
    Short crew-cup ladders at 5/10/15/25/30/50, the one family where the
    quantity does look like genuine wins, paying Crew RP, Wildcard tokens,
    Silver keys and upgrades.

``ThresholdBasedRewards.TournamentMilestoneRewards`` is a different shape in
the same spirit: 20 brackets keyed on a ``threshold`` from 50 to 300,000
rather than on a milestone count. Given the magnitudes and that it pays Crew RP, the metric
is an accumulating crew total rather than a race count -- which this module
records but does not claim to have identified.

**A container holds parallel levels, not one ladder.** ``RewardLevels`` is a
list of ladders sharing the same requirements but paying different
amounts: ``COLLECTIONS_CUP_V2_W1`` has two levels that both unlock at
3/8/14/22/32/44 races, the first paying 20 Car Credits at the first rung and
the second paying 60. Observed level counts are 1 (56 containers), 2 (2), 5
(1) and 6 (17), and the 6-level containers are the crew-cup families. Since
``crews/gccProgress`` reports a ``tier`` ("tier1") and a ``bucket``, a level
most likely selects by crew tier -- but nothing in the metadata says so, so
levels are exposed by index and that reading is left as a note. Merging them
would invent rungs that do not exist, so this module does not.

A ladder here is a *definition*. The current count is not in this metadata.
``events/crewEventProgress`` (``csr2cdn.crew_service_reads``) returns a crew
aggregate per event series, but no id pairing tried so far has returned a
non-zero figure, and it did not move for the collections cup ladder while the
crew raced. ``progress`` says what can be concluded once a count is supplied.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from csr2cdn.reward_types import RewardTypeVocabulary

#: The Tuner Cup, which the maintainer identifies as the in-game Elite Cup.
TUNER_CUP = "tuner_cup"
#: The two weekly collections cups, week 1 and week 2 of a season.
COLLECTIONS_CUP_CONTAINERS = ("COLLECTIONS_CUP_V2_W1", "COLLECTIONS_CUP_V2_W2")
#: Prefixes of the crew-cup reward families.
CREW_CUP_PREFIXES = ("crewcups_", "cups_")


def _int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


@dataclass(frozen=True)
class LadderRung:
    """One rung: the count it needs, and what it pays.

    ``wins_required`` is named for its ``WinsRequired`` wire key. What it
    counts most likely depends on the family -- races for the Tuner Cup and
    the collections cups, wins for the crew cups, as read from the rung
    values. Prefer ``keyed_value`` when the distinction does not matter.
    """
    #: The ``WinsRequired`` count. None for a threshold ladder.
    wins_required: Optional[int] = None
    #: Accumulated-metric threshold, for ``ThresholdBasedRewards``.
    threshold: Optional[int] = None
    quantity: Optional[int] = None
    reward_type: Optional[int] = None
    reward_name: Optional[str] = None
    #: ``partGrade``, ``matchLockedInCar`` and the like, as published.
    attributes: Mapping[str, Any] = field(default_factory=dict, repr=False)
    label: Optional[str] = None

    @property
    def requirement(self) -> Optional[int]:
        """Whichever of the milestone count or threshold this rung is keyed on."""
        return self.wins_required if self.wins_required is not None else self.threshold


@dataclass(frozen=True)
class RewardLadder:
    """One level of a container, its rungs in ascending requirement order."""
    container: str
    rungs: Tuple[LadderRung, ...] = ()
    #: ``"wins"`` or ``"threshold"``.
    keyed_on: str = "wins"
    #: Index into the container's ``RewardLevels``; None for a threshold ladder.
    level: Optional[int] = None

    def __len__(self) -> int:
        return len(self.rungs)

    @property
    def requirements(self) -> Tuple[int, ...]:
        return tuple(r.requirement for r in self.rungs if r.requirement is not None)

    @property
    def top(self) -> Optional[int]:
        reqs = self.requirements
        return reqs[-1] if reqs else None

    def progress(self, achieved: Any) -> dict:
        """What a supplied count earns, and what the next rung needs.

        ``achieved`` comes from outside this module: nothing in the metadata
        reports it, and no service read has yet been seen to supply it for the
        cup families. Returns ``None`` fields rather than guessing when the
        count is not a usable integer.
        """
        count = _int(achieved)
        if count is None or count < 0:
            return {"achieved": None, "earned": None, "next_rung": None,
                    "remaining": None, "complete": None}
        earned = [r for r in self.rungs
                  if r.requirement is not None and r.requirement <= count]
        pending = [r for r in self.rungs
                   if r.requirement is not None and r.requirement > count]
        nxt = pending[0] if pending else None
        return {
            "achieved": count,
            "earned": len(earned),
            "of": len(self.rungs),
            "next_rung": nxt.requirement if nxt is not None else None,
            "next_reward": nxt.label if nxt is not None else None,
            "remaining": (nxt.requirement - count) if nxt is not None else None,
            "complete": not pending,
        }

    def as_dict(self) -> dict:
        return {
            "container": self.container,
            "level": self.level,
            "keyed_on": self.keyed_on,
            "rungs": [{"requirement": r.requirement, "quantity": r.quantity,
                       "reward": r.label} for r in self.rungs],
            "top": self.top,
        }


@dataclass(frozen=True)
class MilestoneContainer:
    """A named reward container and its parallel levels."""
    container: str
    levels: Tuple[RewardLadder, ...] = ()

    def __len__(self) -> int:
        return len(self.levels)

    @property
    def level_count(self) -> int:
        return len(self.levels)

    def level(self, index: int = 0) -> Optional[RewardLadder]:
        return self.levels[index] if 0 <= index < len(self.levels) else None

    @property
    def requirements(self) -> Tuple[int, ...]:
        """The shared rung requirements, from the first level."""
        return self.levels[0].requirements if self.levels else ()

    @property
    def top(self) -> Optional[int]:
        return self.levels[0].top if self.levels else None

    @property
    def levels_share_requirements(self) -> bool:
        """True when every level unlocks at the same counts, as observed."""
        if len(self.levels) < 2:
            return True
        first = self.levels[0].requirements
        return all(l.requirements == first for l in self.levels[1:])

    @property
    def levels_are_identical(self) -> bool:
        """True when the levels also pay the same, as the crew cups do."""
        if len(self.levels) < 2:
            return True
        first = [(r.requirement, r.quantity, r.reward_type) for r in self.levels[0].rungs]
        return all([(r.requirement, r.quantity, r.reward_type) for r in l.rungs] == first
                   for l in self.levels[1:])

    def progress(self, achieved: Any, *, level: int = 0) -> dict:
        ladder = self.level(level)
        if ladder is None:
            return {"achieved": None, "earned": None, "next_rung": None,
                    "remaining": None, "complete": None}
        out = ladder.progress(achieved)
        out["level"] = level
        out["of_levels"] = self.level_count
        return out

    def as_dict(self) -> dict:
        return {"container": self.container, "level_count": self.level_count,
                "requirements": list(self.requirements), "top": self.top,
                "levels_share_requirements": self.levels_share_requirements,
                "levels_are_identical": self.levels_are_identical,
                "levels": [l.as_dict() for l in self.levels]}


def _rung(row: Any, vocabulary: Optional[RewardTypeVocabulary],
          *, keyed_on: str) -> Optional[LadderRung]:
    if not isinstance(row, Mapping):
        return None
    info = row.get("RewardInfo")
    if not isinstance(info, Mapping):
        info = row.get("reward")
    info = info if isinstance(info, Mapping) else {}
    code = _int(info.get("rewardType"))
    attributes = {k: v for k, v in info.items() if k != "rewardType"}
    quantity = _int(row.get("Quantity"))
    if quantity is None:
        quantity = _int(row.get("rewardAmount"))
    name = vocabulary.name(code, attributes) if vocabulary is not None else None
    label = vocabulary.describe(code, attributes) if vocabulary is not None else None
    return LadderRung(
        wins_required=_int(row.get("WinsRequired")) if keyed_on == "wins" else None,
        threshold=_int(row.get("threshold")) if keyed_on == "threshold" else None,
        quantity=quantity, reward_type=code, reward_name=name,
        attributes=attributes, label=label)


@dataclass(frozen=True)
class EventMilestoneCatalogue:
    """Every reward container in ``EventMilestoneRewards``."""
    containers_by_name: Mapping[str, MilestoneContainer] = field(default_factory=dict,
                                                                 repr=False)

    def __len__(self) -> int:
        return len(self.containers_by_name)

    @classmethod
    def from_block(cls, block: Any,
                   vocabulary: Optional[RewardTypeVocabulary] = None
                   ) -> "EventMilestoneCatalogue":
        if not isinstance(block, Mapping):
            raise ValueError("EventMilestoneRewards must be a mapping")
        out: Dict[str, MilestoneContainer] = {}
        for container, node in block.items():
            if not isinstance(container, str) or not isinstance(node, Mapping):
                continue
            levels = node.get("RewardLevels")
            if not isinstance(levels, list):
                continue
            ladders = []
            for index, level in enumerate(levels):
                rows = level.get("rewards") if isinstance(level, Mapping) else None
                if not isinstance(rows, list):
                    continue
                rungs = [r for r in (_rung(x, vocabulary, keyed_on="wins") for x in rows)
                         if r is not None and r.wins_required is not None]
                rungs.sort(key=lambda r: r.wins_required)
                ladders.append(RewardLadder(container, tuple(rungs), "wins", index))
            out[container] = MilestoneContainer(container, tuple(ladders))
        return cls(out)

    def get(self, container: str) -> Optional[MilestoneContainer]:
        return self.containers_by_name.get(container)

    @property
    def containers(self) -> Tuple[str, ...]:
        return tuple(sorted(self.containers_by_name))

    @property
    def tuner_cup(self) -> Optional[MilestoneContainer]:
        """The Elite Cup container, topping out at 900 combined crew races."""
        return self.get(TUNER_CUP)

    def collections_cups(self) -> Dict[int, MilestoneContainer]:
        """Week number to container, for the two weekly collections cups."""
        out = {}
        for index, container in enumerate(COLLECTIONS_CUP_CONTAINERS, start=1):
            found = self.get(container)
            if found is not None:
                out[index] = found
        return out

    def crew_cups(self) -> Dict[str, MilestoneContainer]:
        return {name: c for name, c in sorted(self.containers_by_name.items())
                if name.startswith(CREW_CUP_PREFIXES) and c.levels}


def threshold_ladder(block: Any, container: str = "TournamentMilestoneRewards",
                     vocabulary: Optional[RewardTypeVocabulary] = None
                     ) -> RewardLadder:
    """Decode ``ThresholdBasedRewards``, which keys on an accumulated total.

    The metric is not identified here: the magnitudes (50 to 300,000) and the
    Crew RP payouts point at a crew total rather than a race count, but
    nothing in the metadata states it.
    """
    if not isinstance(block, Mapping):
        raise ValueError("ThresholdBasedRewards must be a mapping")
    node = block.get(container)
    if not isinstance(node, Mapping):
        raise ValueError("container %r absent" % container)
    brackets = node.get("brackets")
    if not isinstance(brackets, list):
        raise ValueError("container %r holds no brackets" % container)
    rungs: list = []
    for bracket in brackets:
        if not isinstance(bracket, Mapping):
            continue
        threshold = _int(bracket.get("threshold"))
        for row in bracket.get("rewards") or []:
            rung = _rung(row, vocabulary, keyed_on="threshold")
            if rung is None:
                continue
            rungs.append(LadderRung(
                None, threshold, rung.quantity, rung.reward_type,
                rung.reward_name, rung.attributes, rung.label))
    rungs.sort(key=lambda r: (r.threshold is None, r.threshold or 0))
    return RewardLadder(container, tuple(rungs), "threshold")
