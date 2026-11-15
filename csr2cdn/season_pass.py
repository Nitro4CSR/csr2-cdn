"""The player's Season Pass state: ``season_pass/season_pass_info``.

The current season, the pass points earned, which level rewards are claimed
and which are still eligible, the premium-pass flags, and per-task progress.
Verified live on 2026-11-15 (``current_season: "Season57"``).

Reads only. ``season_pass/get_season_level_rewards`` returns the same
``rewards`` block and is covered by the same decoder.

Reward identifiers (``"50f"``, ``"900f"``, ``"50b_1"``) are opaque level tags,
kept as given. ``task_progress`` is a map of task name to
``{Progress, Status, DurationType, Index}``; ``Status`` is one of
``Locked``/``Unlocked``/``Complete`` and ``DurationType`` is the task's cadence
(1/2/3, meaning not established, so it is carried as an integer).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple

from .service_models import ServiceResponseError, _field, _int, _optional_str, _payload

#: The three task states the server sends.
TASK_STATES = ("Locked", "Unlocked", "Complete")
_MAX_I64 = 2**63 - 1


def _num(node: Mapping[str, Any], *names: str) -> Optional[int]:
    value = _int(node, *names)
    return value if value is not None and -_MAX_I64 <= value <= _MAX_I64 else None


def _flag(node: Mapping[str, Any], *names: str) -> Optional[bool]:
    value = _field(node, *names)
    return value if type(value) is bool else None


def _tags(node: Mapping[str, Any], *names: str) -> Tuple[str, ...]:
    value = _field(node, *names)
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value if isinstance(item, (str, int)))


@dataclass(frozen=True)
class SeasonPassTask:
    """One ``task_progress`` entry."""

    name: str
    progress: Optional[int] = None
    status: Optional[str] = None
    duration_type: Optional[int] = None
    index: Optional[int] = None

    @property
    def is_complete(self) -> bool:
        return self.status == "Complete"

    @property
    def is_known_state(self) -> bool:
        return self.status in TASK_STATES

    @classmethod
    def from_entry(cls, name: str, entry: Mapping[str, Any]) -> "SeasonPassTask":
        return cls(name, _num(entry, "Progress", "progress"),
                   _optional_str(entry, "Status", "status"),
                   _num(entry, "DurationType", "duration_type"),
                   _num(entry, "Index", "index"))


@dataclass(frozen=True)
class SeasonPass:
    """``season_pass/season_pass_info`` -> ``data``."""

    current_season: Optional[str] = None
    season_pass_points: Optional[int] = None
    is_premium_pass: Optional[bool] = None
    is_premium_pass_plus: Optional[bool] = None
    bonus_reward_unlocked: Optional[bool] = None
    rp_boost_percent: Optional[int] = None
    new_payer: Optional[bool] = None
    lapsed_payer: Optional[bool] = None
    delta_time_to_refetch: Optional[int] = None
    rewards_eligible: Tuple[str, ...] = ()
    rewards_claimed: Tuple[str, ...] = ()
    tasks: Tuple[SeasonPassTask, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def completed_tasks(self) -> Tuple[SeasonPassTask, ...]:
        return tuple(t for t in self.tasks if t.is_complete)

    def task(self, name: str) -> Optional[SeasonPassTask]:
        return next((t for t in self.tasks if t.name == name), None)

    @classmethod
    def from_response(cls, response: Any) -> "SeasonPass":
        node = _payload(response)
        data = _field(node, "data")
        if isinstance(data, Mapping):
            node = data
        markers = ("current_season", "season_pass_points", "rewards", "task_progress")
        if not any(key in node for key in markers):
            raise ServiceResponseError("season pass fields missing from response")
        rewards = _field(node, "rewards")
        rewards = rewards if isinstance(rewards, Mapping) else {}
        tp = _field(node, "task_progress")
        tasks = tuple(SeasonPassTask.from_entry(name, entry)
                      for name, entry in tp.items() if isinstance(entry, Mapping)) \
            if isinstance(tp, Mapping) else ()
        return cls(
            _optional_str(node, "current_season"),
            _num(node, "season_pass_points"),
            _flag(node, "is_premium_pass"),
            _flag(node, "is_premium_pass_plus"),
            _flag(node, "bonus_reward_unlocked"),
            _num(node, "rp_boost_percent"),
            _flag(node, "new_payer"),
            _flag(node, "lapsed_payer"),
            _num(node, "delta_time_to_refetch"),
            _tags(rewards, "eligible"),
            _tags(rewards, "claimed"),
            tasks,
            dict(node))


__all__ = ["SeasonPass", "SeasonPassTask", "TASK_STATES"]
