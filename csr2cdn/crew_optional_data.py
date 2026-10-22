"""Optional CSR2 crew/member/vehicle projections from established read-only replies.

No additional network endpoints are needed. Fields and nested keys are based on
Dev30's live *schema* inventory; optional scalar meanings are provisional.
No private identifiers, names or raw response objects appear in ``repr`` or
normal aggregate diagnostic output. Never infer absent counts as zero.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import re
from typing import Any, Mapping, Optional, Tuple

from .service_models import CrewMembers, OwnCrew
from .game_labels import CarDisplayName, CarNameStyle, GameCarName, GameCarTranslations, GameVisualLibrary
from .customization_evidence import SLOT_FIELDS

_MAX_I64 = 2**63 - 1


def _counter(raw: Mapping[str, Any], key: str) -> Optional[int]:
    value = raw.get(key)
    return value if type(value) is int and 0 <= value <= _MAX_I64 else None


def _flag(raw: Mapping[str, Any], key: str) -> Optional[bool]:
    value = raw.get(key)
    return value if type(value) is bool else None


def _short_text(raw: Mapping[str, Any], key: str) -> Optional[str]:
    value = raw.get(key)
    return value if isinstance(value, str) and len(value) <= 180 else None


@dataclass(frozen=True)
class CrewOptionalStats:
    """Experimental crew-wide scalar fields, separate from GCC seasonal RP."""
    crew_level: Optional[int] = None
    crew_level_base: Optional[int] = None
    crew_level_threshold: Optional[int] = None
    crew_rp_unverified: Optional[int] = None
    crew_rr_point_unverified: Optional[int] = None
    crew_garage_value: Optional[int] = None
    crew_career_earning: Optional[int] = None
    members: Optional[int] = None
    max_members: Optional[int] = None
    total_invites: Optional[int] = None
    total_requests: Optional[int] = None
    # Appended in 0.7.1.dev83. Non-numeric, so read outside the counter loop.
    #: Roster join policy as the service words it, e.g. "OPEN".
    crew_status: Optional[str] = None
    #: Client version the service attributes to the session, e.g. "1.6.2".
    app_ver: Optional[str] = None
    debug_season: Optional[bool] = None

    @property
    def seats_free(self) -> Optional[int]:
        """Open roster seats, or None when either side is unknown."""
        if self.max_members is None or self.members is None:
            return None
        return max(0, self.max_members - self.members)

    @classmethod
    def from_own_crew(cls, own: OwnCrew) -> "CrewOptionalStats":
        raw = own.extras
        return cls(*(_counter(raw, key) for key in (
            "crew_level", "crew_level_base", "crew_level_threshold", "crew_rp",
            "crew_rr_point", "crew_garage_value", "crew_career_earning",
            "members", "max_members", "total_invites", "total_requests")),
            crew_status=_short_text(raw, "crew_status"),
            app_ver=_short_text(raw, "app_ver"),
            debug_season=_flag(raw, "debug_season"))


@dataclass(frozen=True)
class CrewEmblem:
    """Observed cosmetic emblem fields, not a decoded image or CDN asset."""
    emblem_id: Optional[int] = None
    colour: Optional[str] = field(default=None, repr=False)

    @classmethod
    def from_mapping(cls, raw: Any) -> Optional["CrewEmblem"]:
        if not isinstance(raw, Mapping):
            return None
        emblem = cls(_counter(raw, "id"), _short_text(raw, "colour"))
        return emblem if emblem.emblem_id is not None or emblem.colour is not None else None


@dataclass(frozen=True)
class CrewTournamentShape:
    """Presence and bounded structure of own-crew tournament metadata only.

    Never retain or decode event, extra or meta payload values. Their keys may
    include event-specific or private information.
    """
    present: bool = False
    events_present: bool = False
    extra_present: bool = False
    meta_present: bool = False
    events_keys: Optional[int] = None
    extra_keys: Optional[int] = None
    meta_keys: Optional[int] = None

    @classmethod
    def from_mapping(cls, raw: Any) -> "CrewTournamentShape":
        if not isinstance(raw, Mapping):
            return cls()
        nested = [raw.get(k) for k in ("events", "extra", "meta")]
        return cls(True, *(isinstance(n, Mapping) for n in nested),
                   *(min(len(n), 128) if isinstance(n, Mapping) else None for n in nested))


#: Observed spacing between consecutive crew-tournament events, in days.
#: Six consecutive live events were exactly 14 days apart, Thursdays 10:00 UTC.
TOURNAMENT_CADENCE_DAYS = 14


def _as_int(value: Any) -> Optional[int]:
    if type(value) is int:
        return value
    if isinstance(value, str) and value.lstrip("-").isdigit():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _split_vanity_reward(value: Any) -> Tuple[Optional[int], Optional[int]]:
    """Decode ``"<tier>_<unix seconds>"``, e.g. ``"1_1792663200"``.

    Confirmed on 7/7 live values (six events plus ``meta``): two underscore
    separated integers, the second a Unix timestamp at which the event's
    vanity reward is awarded. Returns ``(tier, reward_at)``.
    """
    if not isinstance(value, str):
        return (None, None)
    parts = value.split("_")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return (None, None)
    tier, at = int(parts[0]), int(parts[1])
    # A reward time, not an epoch offset: reject anything outside a sane range
    # rather than reporting a date in 1970 or 2200.
    return (tier, at if 1_000_000_000 < at < 4_000_000_000 else None)


@dataclass(frozen=True)
class CrewTournamentRival:
    """One crew in a tournament match-up.

    ``crew_id`` and ``name`` are in-game values any player can read off the
    tournament screen, so they are printed normally. Opaque or unrecognised
    keys on the wire row are never retained.
    """
    crew_id: Optional[str] = None
    name: Optional[str] = None
    logo_id: Optional[int] = None
    logo_colour: Optional[str] = None
    is_own_crew: Optional[bool] = None

    @classmethod
    def from_wire(cls, raw: Any, own_crew_uid: Any = None) -> "CrewTournamentRival":
        if not isinstance(raw, Mapping):
            return cls()
        logo = raw.get("logo") if isinstance(raw.get("logo"), Mapping) else {}
        crew_id = _short_text(raw, "id")
        own = (crew_id == str(own_crew_uid)) if crew_id and own_crew_uid else None
        return cls(crew_id, _short_text(raw, "name"),
                   _counter(logo, "id"), _short_text(logo, "colour"), own)


@dataclass(frozen=True)
class CrewTournamentEvent:
    """One crew-tournament event.

    ``members`` holds the participating players' in-game IDs. It is kept out of
    repr only because thirty strings make a repr unreadable, not for privacy;
    ``member_count`` and ``distinct_member_count`` stay as cheap summaries.
    Only the four known wire keys are read, so an auth or token field added to
    an event is never retained.
    """
    event_id: Optional[int] = None
    #: Unix seconds at which this event's vanity reward is awarded.
    reward_at: Optional[int] = None
    reward_tier: Optional[int] = None
    crew_count: Optional[int] = None
    member_count: Optional[int] = None
    distinct_member_count: Optional[int] = None
    own_crew_participated: Optional[bool] = None
    #: True when the wire ``hash`` is exactly the participating crew IDs joined
    #: by ``"_"``, which held on 6/6 live events. It is a match-up key, not a
    #: digest, and carries nothing the ``crews`` array does not already give.
    matchup_key_consistent: Optional[bool] = None
    rivals: Tuple[CrewTournamentRival, ...] = field(default_factory=tuple, repr=False)
    #: Participating players' in-game IDs, in wire order. Hidden from repr for
    #: readability only; see the class docstring.
    members: Tuple[str, ...] = field(default_factory=tuple, repr=False)

    @classmethod
    def from_wire(cls, event_id: Any, raw: Any,
                  own_crew_uid: Any = None) -> "CrewTournamentEvent":
        if not isinstance(raw, Mapping):
            return cls(_as_int(event_id))
        crews = [c for c in (raw.get("crews") or []) if isinstance(c, Mapping)]
        members = raw.get("members")
        members = members if isinstance(members, list) else []
        tier, reward_at = _split_vanity_reward(raw.get("vanity_reward"))
        crew_ids = {str(c.get("id")) for c in crews if c.get("id") is not None}
        wire_hash = raw.get("hash")
        consistent = (set(str(wire_hash).split("_")) == crew_ids
                      if isinstance(wire_hash, str) and crew_ids else None)
        return cls(
            _as_int(event_id), reward_at, tier, len(crews), len(members),
            len({str(m) for m in members}),
            (str(own_crew_uid) in crew_ids) if own_crew_uid and crew_ids else None,
            consistent,
            tuple(CrewTournamentRival.from_wire(c, own_crew_uid) for c in crews),
            tuple(str(m) for m in members
                  if isinstance(m, (str, int)) and not isinstance(m, bool)))


@dataclass(frozen=True)
class CrewTournament:
    """Decoded own-crew tournament tree.

    Complements, and does not replace, ``CrewTournamentShape``, which stays
    the presence-only view carried on ``CrewPresentation`` and printed in
    reports. Only the known wire keys are decoded, so opaque auth or token
    fields anywhere in the tree are never retained.
    """
    present: bool = False
    events: Tuple[CrewTournamentEvent, ...] = field(default_factory=tuple, repr=False)
    event_count: Optional[int] = None
    #: Highest event ID present. The IDs are consecutive and the spacing is a
    #: fixed fortnight, so the ID behaves as a global fortnight counter; the
    #: newest entry was still open at capture time.
    current_event_id: Optional[int] = None
    #: ``meta.scores``, when it is the single integer observed live. Its
    #: meaning is NOT established: one observation, equal to the reward tier.
    current_score: Optional[int] = None
    current_reward_tier: Optional[int] = None
    current_reward_at: Optional[int] = None
    #: Uniform day spacing between consecutive events, else None.
    cadence_days: Optional[int] = None
    prev_match_crew_count: Optional[int] = None
    #: ``meta.prev_match`` named the CURRENT match-up on every live capture,
    #: not the preceding one. The wire name is misleading, like ``car_paint_id``.
    prev_match_is_current_event: Optional[bool] = None
    #: ``extra`` was an empty object on every capture; this is True only when
    #: it actually carries something, so a future payload is noticed.
    extra_populated: bool = False

    @classmethod
    def from_mapping(cls, raw: Any, own_crew_uid: Any = None) -> "CrewTournament":
        if not isinstance(raw, Mapping):
            return cls()
        events_raw = raw.get("events") if isinstance(raw.get("events"), Mapping) else {}
        events = tuple(sorted(
            (CrewTournamentEvent.from_wire(k, v, own_crew_uid)
             for k, v in events_raw.items()),
            key=lambda e: (e.event_id is None, e.event_id or 0)))
        meta = raw.get("meta") if isinstance(raw.get("meta"), Mapping) else {}
        tier, reward_at = _split_vanity_reward(meta.get("vanity_reward"))
        scores = meta.get("scores")
        score = (scores[0] if isinstance(scores, list) and len(scores) == 1
                 and type(scores[0]) is int else None)
        prev = meta.get("prev_match")
        inner = (prev[0] if isinstance(prev, list) and prev
                 and isinstance(prev[0], list) else None)
        prev_matches_current = None
        if inner is not None and events:
            newest = {r.crew_id for r in events[-1].rivals if r.crew_id}
            if newest:
                prev_matches_current = {str(v) for v in inner} == newest
        cadence = None
        stamps = [e.reward_at for e in events if e.reward_at is not None]
        if len(stamps) >= 2:
            gaps = {b - a for a, b in zip(stamps, stamps[1:])}
            if len(gaps) == 1:
                gap = gaps.pop()
                cadence = gap // 86400 if gap > 0 and gap % 86400 == 0 else None
        extra = raw.get("extra")
        return cls(True, events, len(events),
                   events[-1].event_id if events else None,
                   score, tier, reward_at, cadence,
                   len(inner) if inner is not None else None,
                   prev_matches_current,
                   bool(isinstance(extra, Mapping) and extra))

    @property
    def own_crew_event_count(self) -> Optional[int]:
        """Events this crew took part in, or None when unknown."""
        known = [e.own_crew_participated for e in self.events
                 if e.own_crew_participated is not None]
        return sum(known) if known else None


@dataclass(frozen=True)
class CrewPresentation:
    """Opt-in own-crew cosmetics; motto, language and colour are hidden in repr."""
    logo: Optional[CrewEmblem] = None
    motto: Optional[str] = field(default=None, repr=False)
    language: Optional[str] = field(default=None, repr=False)
    tournament: CrewTournamentShape = field(default_factory=CrewTournamentShape)

    @classmethod
    def from_own_crew(cls, own: OwnCrew) -> "CrewPresentation":
        raw = own.extras
        return cls(CrewEmblem.from_mapping(raw.get("crew_logo")),
                   _short_text(raw, "crew_motto"),
                   _short_text(raw, "crew_language"),
                   CrewTournamentShape.from_mapping(raw.get("tournament")))


@dataclass(frozen=True)
class CrewVehicleAppearance:
    """Directly observed roster appearance IDs; zero is a valid ID.

    Values are identifiers, not decoded paint names, images or color labels.
    Plate text is intentionally excluded to avoid disclosing custom strings.
    """
    calliper_id: Optional[int] = None
    interior_id: Optional[int] = None
    livery_id: Optional[int] = None
    livery_zones_set_id: Optional[int] = None
    paint_id: Optional[int] = None
    wheel_name: Optional[str] = field(default=None, repr=False)
    decal_flag_id: Optional[int] = None
    decal_number_id: Optional[int] = None
    decal_number_color_id: Optional[int] = None
    decal_number_shape_color_id: Optional[int] = None
    decal_number_zone_id: Optional[int] = None
    decal_numberplate_style_id: Optional[int] = None
    decal_playername_state: Optional[int] = None
    decal_crewname_state: Optional[int] = None

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> Optional["CrewVehicleAppearance"]:
        result = cls(
            _counter(raw, "car_calliper_id"),
            _counter(raw, "car_interior_id"),
            _counter(raw, "car_livery_id"),
            _counter(raw, "car_liveryZonesSet_id"),
            _counter(raw, "car_paint_id"),
            _short_text(raw, "car_wheel_name"),
            _counter(raw, "car_decal_flag_id"),
            _counter(raw, "car_decal_number_id"),
            _counter(raw, "car_decal_number_color_id"),
            _counter(raw, "car_decal_number_shape_color_id"),
            _counter(raw, "car_decal_number_zone_id"),
            _counter(raw, "car_decal_numberplate_style_id"),
            _counter(raw, "car_decal_playername_state"),
            _counter(raw, "car_decal_crewname_state"),
        )
        return result if any(v is not None for v in vars(result).values()) else None


@dataclass(frozen=True)
class CrewVehicleGacha:
    """Observed 6.8.0 current-car customization IDs; units unverified."""
    caid: Optional[int] = None
    inid: Optional[int] = None
    livid: Optional[int] = None
    lzsid: Optional[int] = None
    paid: Optional[int] = None
    whbn: Optional[str] = field(default=None, repr=False)

    @classmethod
    def from_mapping(cls, raw: Any) -> Optional["CrewVehicleGacha"]:
        if not isinstance(raw, Mapping) or not raw:
            return None
        result = cls(*(_counter(raw, key) for key in ("caid", "inid", "livid", "lzsid", "paid")),
                     _short_text(raw, "whbn"))
        return result if any(value is not None for value in vars(result).values()) else None


class InteriorDisplayName(str):
    """String-compatible interior name with the game's two separate zones.

    The default string value is zone one, preserving previous ``.name``
    comparisons, printing and JSON serialization. ``zone2`` may be ``None``
    for older or incomplete user-supplied visual-library manifests; no
    substitute name is invented. This object contains no additional I/O.
    """
    __slots__ = ("zone1", "zone2")

    def __new__(cls, zone1: str, zone2: Optional[str] = None) -> "InteriorDisplayName":
        if not isinstance(zone1, str) or not zone1:
            raise ValueError("interior zone-one name must be nonempty")
        if zone2 is not None and not isinstance(zone2, str):
            raise ValueError("interior zone-two name must be a string or None")
        result = str.__new__(cls, zone1)
        result.zone1 = zone1
        result.zone2 = zone2
        return result


@dataclass(frozen=True)
class CrewVisualSelection:
    """One observed cosmetic code and its *optional*, explicitly bound label.

    ``name`` is ``None`` until a matching decoded game-library record is
    supplied; raw codes and library provenance are retained separately. No
    default names are invented. Labels and codes are hidden from ``repr``.
    """
    code: int | str = field(repr=False)
    name: Optional[str] = field(default=None, repr=False)
    source_library: Optional[str] = field(default=None, repr=False)
    source_hash: Optional[str] = field(default=None, repr=False)
    source_sha256: Optional[str] = field(default=None, repr=False)
    names: tuple[str, ...] = field(default_factory=tuple, repr=False)

    @property
    def resolved(self) -> bool:
        return self.name is not None


@dataclass(frozen=True)
class CrewVehicleVisuals:
    """Attribute-first view over the observed appearance slots.

    ``vehicle.visuals.paint.name`` exposes a verified-source candidate label,
    while ``vehicle.visuals.paint.code`` retains the game's original ID.
    Missing appearance slots are ``None``. No implicit CDN requests occur.
    """
    calliper: Optional[CrewVisualSelection] = field(default=None, repr=False)
    interior: Optional[CrewVisualSelection] = field(default=None, repr=False)
    livery: Optional[CrewVisualSelection] = field(default=None, repr=False)
    livery_zones_set: Optional[CrewVisualSelection] = field(default=None, repr=False)
    paint: Optional[CrewVisualSelection] = field(default=None, repr=False)
    wheel: Optional[CrewVisualSelection] = field(default=None, repr=False)
    decal_flag: Optional[CrewVisualSelection] = field(default=None, repr=False)
    decal_number: Optional[CrewVisualSelection] = field(default=None, repr=False)
    decal_number_color: Optional[CrewVisualSelection] = field(default=None, repr=False)
    decal_number_shape_color: Optional[CrewVisualSelection] = field(default=None, repr=False)
    decal_number_zone: Optional[CrewVisualSelection] = field(default=None, repr=False)
    decal_numberplate_style: Optional[CrewVisualSelection] = field(default=None, repr=False)

    @classmethod
    def from_appearance(cls, appearance: Optional[CrewVehicleAppearance], model_key: Optional[str],
                        library: GameVisualLibrary) -> "CrewVehicleVisuals":
        if not isinstance(library, GameVisualLibrary):
            raise TypeError("visual source must be GameVisualLibrary")
        found = {}
        for slot, wire_field in SLOT_FIELDS.items():
            code = getattr(appearance, wire_field) if appearance is not None else None
            if code is None:
                continue
            match = library.match(model_key, slot, code)
            # Tuner Stars IDs inhabit a separate high-numbered domain, but
            # their All category is not evidence of eligibility on non-TNR
            # vehicles. Keep such automatic joins conditional on model syntax.
            if (match is not None and match.source_library.startswith('CarTunerStars')
                    and (not isinstance(model_key, str) or
                         not re.search(r'TNR(?:[0-9]+)?_(?:19|20)[0-9]{2}(?:_|$)', model_key))):
                match = None
            label: Optional[str] = match.name if match is not None else None
            if slot == "interior" and match is not None:
                # The native CarInteriorLibrary has Zone1Name and Zone2Name.
                # Preserve .name as zone one while exposing both attributes.
                zones = match.names
                label = InteriorDisplayName(
                    zones[0] if zones else match.name,
                    zones[1] if len(zones) > 1 else None,
                )
            found[slot] = CrewVisualSelection(
                code=code,
                name=label,
                source_library=match.source_library if match is not None else None,
                source_hash=match.source_hash if match is not None else None,
                source_sha256=match.source_sha256 if match is not None else None,
                names=match.names if match is not None else (),
            )
        return cls(**found)

    @property
    def resolved_count(self) -> int:
        return sum(value is not None and value.resolved for value in vars(self).values())

    @property
    def present_count(self) -> int:
        return sum(value is not None for value in vars(self).values())


@dataclass(frozen=True)
class CrewMemberVehicle:
    """Vehicle details exposed by a roster row; no extra car lookup performed."""
    model_key: Optional[str] = field(default=None, repr=False)
    pp: Optional[int] = None
    ep: Optional[int] = None
    elite_level: Optional[int] = None
    am_milestone_level: Optional[int] = None
    restoration_status: Optional[int] = None
    source: Optional[str] = field(default=None, repr=False)
    gacha: Optional[CrewVehicleGacha] = None
    appearance: Optional[CrewVehicleAppearance] = None
    tuning_setup_present: bool = False
    tuning_setup_field_count: Optional[int] = None
    translated_names: Optional[GameCarName] = field(default=None, repr=False, compare=False)
    preferred_name_style: CarNameStyle = field(default=CarNameStyle.MEDIUM, repr=False, compare=False)
    visuals: Optional[CrewVehicleVisuals] = field(default=None, repr=False, compare=False)
    # Never copy tuning parameters or opaque tuning response objects into the typed model.

    @property
    def name(self) -> Optional[CarDisplayName]:
        """Translation-bound car name; absent until names are explicitly supplied."""
        return (self.translated_names.name.for_style(self.preferred_name_style)
                if self.translated_names is not None else None)

    @property
    def names(self) -> list[Optional[str]]:
        """SHORT, MEDIUM, LONG, or [] if no translation matches this model."""
        return self.translated_names.names if self.translated_names is not None else []

    def with_translations(self, translations: GameCarTranslations, *,
                          style: CarNameStyle | str = CarNameStyle.MEDIUM) -> "CrewMemberVehicle":
        """Return a copy with a selectable preferred name; no network requests."""
        if not isinstance(translations, GameCarTranslations):
            raise TypeError("translations must be GameCarTranslations")
        return replace(self, translated_names=translations.match(self.model_key),
                       preferred_name_style=CarNameStyle.coerce(style))

    def with_visuals(self, library: GameVisualLibrary) -> "CrewMemberVehicle":
        """Bind exact local visual-code labels; leave unmatched codes unresolved."""
        return replace(self, visuals=CrewVehicleVisuals.from_appearance(
            self.appearance, self.model_key, library))

    def with_game_labels(self, translations: GameCarTranslations,
                         visuals: GameVisualLibrary, *,
                         style: CarNameStyle | str = CarNameStyle.MEDIUM) -> "CrewMemberVehicle":
        """Bind car and visual names without mutating either source."""
        return self.with_translations(translations, style=style).with_visuals(visuals)

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> "CrewMemberVehicle":
        tuning = raw.get("car_tnr_setup")
        return cls(
            model_key=_short_text(raw, "current_car"),
            pp=_counter(raw, "car_pp"), ep=_counter(raw, "car_ep"),
            elite_level=_counter(raw, "car_elite_level"),
            am_milestone_level=_counter(raw, "car_am_milestone_level"),
            restoration_status=_counter(raw, "car_restoration_status"),
            source=_short_text(raw, "car_source"),
            gacha=CrewVehicleGacha.from_mapping(raw.get("car_gacha_config")),
            appearance=CrewVehicleAppearance.from_wire(raw),
            tuning_setup_present=isinstance(tuning, Mapping),
            tuning_setup_field_count=min(len(tuning), 128) if isinstance(tuning, Mapping) else None,
        )


@dataclass(frozen=True)
class CrewMemberOptionalStats:
    """Available numeric counters; value semantics remain native candidates."""
    garage_value: Optional[int] = None
    career_earning: Optional[int] = None
    cash_donated: Optional[int] = None
    collections_rank: Optional[int] = None
    season_pass_rp_boost: Optional[int] = None
    premium_plus_pass_holder: Optional[bool] = None
    # Still deliberately withheld: `facebook_id`. A Facebook ID is a
    # real-world social account rather than game data, and nothing in this
    # package needs it to describe a crew. It remains reachable through
    # `CrewMember.extras`. The maintainer has not asked for it, so do not add
    # it without being asked.
    #
    # In-game player IDs, crew IDs and license plate text were withheld until
    # 2026-10-21, when the maintainer confirmed printing them is fine. They are
    # in-game values a player can read off the roster screen. Opaque tokens
    # (auth fields, `hidden_token`, and anything unrecognised) remain withheld
    # unconditionally -- see test_dev071_dev3_cosmetics_isolation.
    #
    # --- appended in 0.7.1.dev83 ---------------------------------------
    #: Crew donation total in tokens. Lifetime, not seasonal; for seasonal
    #: crew contribution use `CrewMember.season_crew_rp`.
    token_donated: Optional[int] = None
    license_level: Optional[int] = None
    # Enumerations whose label tables have NOT been located, so these stay
    # raw wire values rather than resolved names. Live roster value sets are
    # recorded in VALIDATION_STATUS.md.
    tier: Optional[int] = None
    rarity: Optional[int] = None
    is_super_rare: Optional[bool] = None
    #: Index into an avatar library that has not been located either.
    avatar_index: Optional[int] = None
    preferred_avatar_type: Optional[int] = None
    #: Player-authored plate text, length-capped like every other
    #: player-supplied string here. Free-form user content: treat as untrusted.
    license_plate_text: Optional[str] = None
    #: Unix seconds, as sent; not converted, because the service's own zone is
    #: unverified. The game shows this on the roster screen, so it is printed.
    last_log_in_time: Optional[int] = None

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> "CrewMemberOptionalStats":
        return cls(*(_counter(raw, key) for key in (
            "garage_value", "career_earning", "cash_donated", "collections_rank",
            "season_pass_rp_boost")), _flag(raw, "season_pass_premium_plus_pass_holder"),
            *(_counter(raw, key) for key in (
                "token_donated", "license_level", "tier", "rarity")),
            is_super_rare=_flag(raw, "is_super_rare"),
            avatar_index=_counter(raw, "avatar_index"),
            preferred_avatar_type=_counter(raw, "preferred_avatar_type"),
            license_plate_text=_short_text(raw, "license_plate_text"),
            last_log_in_time=_counter(raw, "last_log_in_time"))


@dataclass(frozen=True)
class CrewMemberOptional:
    player_uid: Optional[str] = field(default=None, repr=False)
    name: Optional[str] = field(default=None, repr=False)
    stats: CrewMemberOptionalStats = field(default_factory=CrewMemberOptionalStats)
    vehicle: CrewMemberVehicle = field(default_factory=CrewMemberVehicle)


@dataclass(frozen=True)
class CrewOptionalSnapshot:
    crew_id: str = field(repr=False)
    crew: CrewOptionalStats = field(default_factory=CrewOptionalStats)
    presentation: CrewPresentation = field(default_factory=CrewPresentation, repr=False)
    members: Tuple[CrewMemberOptional, ...] = field(default_factory=tuple, repr=False)
    identity_complete: bool = False
    roster_count_matches_own_crew: Optional[bool] = None
    tournament: CrewTournament = field(default_factory=CrewTournament, repr=False)

    @classmethod
    def from_reads(cls, own: OwnCrew, roster: CrewMembers) -> "CrewOptionalSnapshot":
        if not own.crew_uid or own.crew_uid != roster.crew_uid:
            raise ValueError("own-crew and roster IDs must agree")
        decoded = tuple(CrewMemberOptional(
            player_uid=m.player_uid or m.zid, name=m.name,
            stats=CrewMemberOptionalStats.from_wire(m.extras),
            vehicle=CrewMemberVehicle.from_wire(m.extras)) for m in roster.members)
        ids = [m.player_uid for m in decoded]
        stats = CrewOptionalStats.from_own_crew(own)
        count_match = (len(decoded) == stats.members) if stats.members is not None else None
        return cls(own.crew_uid, stats, CrewPresentation.from_own_crew(own), decoded,
                   bool(ids) and all(ids) and len(set(ids)) == len(ids), count_match,
                   CrewTournament.from_mapping(own.extras.get("tournament"),
                                               own.crew_uid))

    def with_translations(self, translations: GameCarTranslations, *,
                          style: CarNameStyle | str = CarNameStyle.MEDIUM) -> "CrewOptionalSnapshot":
        """Bind preferred translated names to an immutable roster copy."""
        if not isinstance(translations, GameCarTranslations):
            raise TypeError("translations must be GameCarTranslations")
        return replace(self, members=tuple(replace(member,
            vehicle=member.vehicle.with_translations(translations, style=style))
            for member in self.members))

    def with_visuals(self, library: GameVisualLibrary) -> "CrewOptionalSnapshot":
        """Bind local visual labels to an immutable roster copy."""
        if not isinstance(library, GameVisualLibrary):
            raise TypeError("visual source must be GameVisualLibrary")
        return replace(self, members=tuple(replace(member,
            vehicle=member.vehicle.with_visuals(library)) for member in self.members))

    def with_game_labels(self, translations: GameCarTranslations,
                         visuals: GameVisualLibrary, *,
                         style: CarNameStyle | str = CarNameStyle.MEDIUM) -> "CrewOptionalSnapshot":
        """Bind names and visuals with one attribute-first offline operation."""
        return self.with_translations(translations, style=style).with_visuals(visuals)


def optional_report(snapshot: CrewOptionalSnapshot, *, show_values: bool = False,
                    show_members: bool = False, car_catalog=None, cosmetic_catalog=None) -> dict[str, Any]:
    """Structured preview: no member names or scalar values unless requested.

    ``show_members`` is explicit permission to print private per-member names,
    car descriptions and individual counters. Account identifiers are NEVER printed.
    """
    result: dict[str, Any] = {
        "status": "optional_fields_candidate_unverified",
        "member_rows": len(snapshot.members),
        "distinct_member_identities": snapshot.identity_complete,
        "roster_count_matches_own_crew": snapshot.roster_count_matches_own_crew,
        "crew_field_presence": {k: v is not None for k, v in vars(snapshot.crew).items()},
        "crew_presentation_presence": {
            "logo_id": snapshot.presentation.logo is not None and snapshot.presentation.logo.emblem_id is not None,
            "logo_colour": snapshot.presentation.logo is not None and snapshot.presentation.logo.colour is not None,
            "motto": snapshot.presentation.motto is not None,
            "language": snapshot.presentation.language is not None,
        },
        "tournament_shape": vars(snapshot.presentation.tournament).copy(),
        "member_stat_coverage": {},
        "vehicle_field_coverage": {},
        "vehicle_appearance_coverage": {},
        "raw_payloads_saved": False,
        "units_and_semantics_verified": False,
        "individual_values_printed": bool(show_members),
    }
    if car_catalog is not None:
        from .vehicle_catalog import VehicleCatalog, resolve_vehicle_report
        if not isinstance(car_catalog, VehicleCatalog):
            raise TypeError("car_catalog must be a VehicleCatalog")
        result["vehicle_catalogue"] = resolve_vehicle_report(
            snapshot, car_catalog, show_members=show_members)
    if cosmetic_catalog is not None:
        from .customization_evidence import cosmetic_coverage_report
        result["cosmetic_candidates"] = cosmetic_coverage_report(
            snapshot, cosmetic_catalog, show_members=show_members)
    if not snapshot.members:
        return result
    stat_keys = vars(snapshot.members[0].stats)
    car_keys = {key: value for key, value in vars(snapshot.members[0].vehicle).items()
                if key not in ("translated_names", "preferred_name_style", "visuals")}
    result["member_stat_coverage"] = {
        key: sum(getattr(member.stats, key) is not None for member in snapshot.members)
        for key in stat_keys}
    result["vehicle_field_coverage"] = {
        key: sum(getattr(member.vehicle, key) is not None for member in snapshot.members)
        for key in car_keys}
    result["gacha_records"] = sum(m.vehicle.gacha is not None for m in snapshot.members)
    result["vehicle_appearance_coverage"] = {
        key: sum(m.vehicle.appearance is not None and
                 getattr(m.vehicle.appearance, key) is not None for m in snapshot.members)
        for key in vars(CrewVehicleAppearance())
    }
    # Do not assert aggregate equality for an incomplete roster or missing
    # scalar. The dev30 sample verified exact garage aggregation for 29 rows;
    # cumulative career earnings are a separate unverified statistic.
    crew_garage = snapshot.crew.crew_garage_value
    garage_values = [m.stats.garage_value for m in snapshot.members]
    garage_complete = (snapshot.identity_complete and
                       snapshot.roster_count_matches_own_crew is True and
                       type(crew_garage) is int and
                       all(type(v) is int for v in garage_values))
    result["garage_aggregation"] = {
        "comparable": garage_complete,
        "equal": (sum(garage_values) == crew_garage) if garage_complete else None,
    }
    if show_values:
        result["garage_aggregation"]["delta"] = (
            sum(garage_values) - crew_garage if garage_complete else None)
        result["crew_stat_candidates"] = {k: v for k, v in vars(snapshot.crew).items() if v is not None}
        presentation = snapshot.presentation
        result["crew_presentation_candidates"] = {
            "logo_id": presentation.logo.emblem_id if presentation.logo else None,
            "logo_colour": presentation.logo.colour if presentation.logo else None,
            "motto": presentation.motto,
            "language": presentation.language,
        }
        result["member_aggregate_candidates"] = {}
        for key in stat_keys:
            values = [getattr(m.stats, key) for m in snapshot.members]
            nums = [v for v in values if type(v) is int]
            if nums:
                result["member_aggregate_candidates"][key] = {
                    "count": len(nums), "sum": sum(nums), "min": min(nums), "max": max(nums)}
    if show_members:
        result["member_candidates"] = [{
            "name": m.name,
            "stats": {k: v for k, v in vars(m.stats).items() if v is not None},
            "vehicle": {k: v for k, v in vars(m.vehicle).items()
                        if v is not None and k not in ("gacha", "appearance", "translated_names", "preferred_name_style", "visuals")},
            "gacha": vars(m.vehicle.gacha) if m.vehicle.gacha is not None else None,
            "appearance": vars(m.vehicle.appearance) if m.vehicle.appearance is not None else None,
        } for m in snapshot.members]
    return result
