#!/usr/bin/env python3
"""Offline evidence probe for CSR2 6.8.0 binary Prestige race-group tail.

Works on a locally supplied UnityFS ASTC asset bundle. Never contacts servers,
uses authentication, or emits the asset's opaque race/player bytes.

Only decodes the *post-RaceEvents* section proven by native
RaceEventGroup_JsonData.FromBinary (RVA 0x32fd05c), and intentionally does not
claim to deserialize the full RaceEventGroup/RaceEvents hierarchy.
"""
from __future__ import annotations
import struct

from .service_prestige_unityfs import load_unityfs

MARKER = b'silver_prestige'

class DecodeError(ValueError): pass

class Reader:
    def __init__(self, blob: bytes, offset: int, limit: int):
        self.b, self.i, self.limit = blob, offset, limit
    def take(self, n: int) -> bytes:
        if n < 0 or self.i + n > self.limit:
            raise DecodeError('truncated field')
        out = self.b[self.i:self.i+n]; self.i += n
        return out
    def byte(self) -> int: return self.take(1)[0]
    def int32(self) -> int: return struct.unpack('<i', self.take(4))[0]
    def uint7(self) -> int:
        value = 0
        for j in range(5):
            c = self.byte()
            if j == 4 and c > 15: raise DecodeError('oversized 7-bit integer')
            value |= (c & 127) << (7*j)
            if c < 128: return value
        raise DecodeError('invalid 7-bit integer')
    def string(self) -> str:
        length = self.uint7()
        if length > 512: raise DecodeError('implausibly long string')
        try: return self.take(length).decode('utf-8')
        except UnicodeError as e: raise DecodeError('invalid UTF-8') from e
    def maybe_string(self) -> str | None:
        marker = self.byte()
        if marker == 0: return None
        if marker == 1: return self.string()
        raise DecodeError('invalid optional string marker')


def parse_group_tail(script: bytes, offset: int, marker_at: int) -> dict:
    """Decode native JsonData.FromBinary group tail after RaceEvents & reward.

    Fields: 4 optional strings, optional EventLeaderboard (string + array of
    two-string unlock conditions), five 32-bit group settings. Strictly
    validate the marker offset and telemetry field ownership.
    """
    r = Reader(script, offset, min(len(script), offset+4096))
    event_name = r.maybe_string()          # JsonData + 0x20
    other_1 = r.maybe_string()             # JsonData + 0xf8
    telemetry_position = r.i
    telemetry = r.maybe_string()          # JsonData + 0x38
    other_2 = r.maybe_string()             # JsonData + 0xa8
    if telemetry != MARKER.decode() or telemetry_position + 2 != marker_at:
        raise DecodeError('not the exact serialized telemetry field')
    if not event_name or len(event_name) > 160:
        raise DecodeError('missing event group name')
    present = r.byte()                    # optional leaderboard object
    if present not in (0,1): raise DecodeError('invalid leaderboard flag')
    template = None
    conditions = []
    if present:
        template = r.string()             # EventLeaderboard.FromBinary, +0x10
        n = r.int32()                     # unlock conditions count
        if n > 32 or n < 0: raise DecodeError('invalid condition count')
        for _ in range(n):
            conditions.append({'type':r.string(), 'value':r.string()})
    vals = [r.int32() for _ in range(5)]  # field offsets 148,14c,150,154,158
    season, car_lookup, index, repeat, trailing_int = vals
    if season not in range(0,10000) or car_lookup not in range(4) or index not in range(0,512):
        raise DecodeError('implausible season/car/index values')
    if repeat < 0 or repeat > 366*86400*10:
        raise DecodeError('implausible repeat interval')
    return {
        'event_group_name': event_name,
        'telemetry': telemetry,
        'has_leaderboard_object': bool(present),
        'leaderboard_template_id': template,
        'unlock_conditions': conditions,
        'based_on_season': season,
        'cup_car_lookup': car_lookup,
        'index_in_season': index,
        'time_repeat_duration_seconds': repeat,
        'additional_serialized_integer': trailing_int,
        'script_offset': offset,
        'decoded_end_offset': r.i,
        'confidence': 'native reader field order and accessors, not a full race-group decode',
    }


def probe_script(script: bytes) -> dict:
    result = []
    offset = 0
    while (offset := script.find(MARKER, offset)) != -1:
        found=[]
        # The telemetry third optional string must begin at offset-2.
        for start in range(max(4,offset-180), offset-3):
            try:
                record = parse_group_tail(script,start,offset)
            except (DecodeError, IndexError):
                continue
            found.append(record)
        # Reject ambiguous parses rather than silently choosing a match.
        if len(found)==1: result.append(found[0])
        offset += len(MARKER)
    return {'serialized_group_count':struct.unpack_from('<I',script,0)[0],
            'silver_prestige_marker_occurrences': script.count(MARKER),
            'native_group_tail_matches':result}


