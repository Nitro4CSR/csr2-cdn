#!/usr/bin/env python3
"""Offline-only CSR2 6.8.0 Prestige template runtime-input probe.

Decodes structural fields from a user-supplied UnityFS bundle; reproduces the
native four-component *race EventID* construction when the resolved season is
provided explicitly. Neither this utility nor its fixtures call game servers.

All extraction requires independent structural checks. This is NOT a complete
native race-group deserializer and does NOT produce a leaderboard URL.
"""
from __future__ import annotations
import struct
from datetime import datetime, timedelta, timezone
from .service_prestige_binary_probe import (DecodeError, probe_script)
from .service_prestige_unityfs import load_unityfs

UTC=timezone.utc
PRESTIGE=b'silver_prestige'
REPEAT_SECONDS=14*86400

def iso(ts: int)->str:
    return datetime.fromtimestamp(ts,UTC).isoformat()

def _read_int(b:bytes,off:int)->int:
    if off<0 or off+4>len(b): raise DecodeError('invalid integer offset')
    return struct.unpack_from('<i',b,off)[0]

def parse_runtime_inputs(script:bytes)->dict:
    parsed=probe_script(script)
    matches=parsed['native_group_tail_matches']
    if len(matches)!=1: raise DecodeError('expected exactly one native decoded Prestige group tail')
    group=matches[0]
    if group['event_group_name']!='PRESTIGE_CHAMPIONSHIP_SILVER_LADDERS':
        raise DecodeError('unexpected Prestige template identity')
    if not group['has_leaderboard_object']:
        raise DecodeError('template lacks a leaderboard object')
    if group['time_repeat_duration_seconds']!=REPEAT_SECONDS:
        raise DecodeError('unexpected repeat interval')
    # The group tail's fifth int has native backing-field offset +0x158.
    # RaceEventGroup.get_EventFile (RVA 0x32fb2a8) reads that exact offset.
    event_file=group['additional_serialized_integer']
    if not 0<=event_file<=99: raise DecodeError('event file outside two-digit format')
    tail_start=group['decoded_end_offset']
    if tail_start+320>len(script):raise DecodeError('truncated group continuation')
    # Native FromBinary reads four consecutive Int32s for _TimeStart,
    # _TimeEnd, _TimeForeshadowDuration and TimeStayOnMapAfterCompletion.
    # The preceding optional objects/variable-length strings cannot safely be
    # skipped without their full type-tree, so require a unique candidate plus
    # calendar and duration consistency, not a silent first-match heuristic.
    windows=[]
    for pos in range(tail_start,tail_start+310):
        start,end,foreshadow,stay=struct.unpack_from('<iiii',script,pos)
        if (1500000000<=start<1800000000
                and 1500000000<end<1800000000
                and 0<end-start<REPEAT_SECONDS
                and (end-start)%3600==0
                and foreshadow in range(0,REPEAT_SECONDS+1)
                and stay in range(0,REPEAT_SECONDS+1)
                and foreshadow%3600==0 and stay%3600==0):
            windows.append((pos,start,end,foreshadow,stay))
    if len(windows)!=1:raise DecodeError('schedule fields not uniquely identified')
    pos,start,end,foreshadow,stay=windows[0]
    # Verify the pre-RaceEvents count attached to the earlier occurrence of
    # telemetry. The following record boundary contains the 30 repeating
    # descriptions; the first entry is the different cup-introduction race.
    marker_positions=[];p=0
    while (p:=script.find(PRESTIGE,p))!=-1:
        marker_positions.append(p);p+=len(PRESTIGE)
    if len(marker_positions)!=2:raise DecodeError('unexpected Prestige marker multiplicity')
    before,after=marker_positions
    if not before < group['script_offset'] < after < tail_start:
        raise DecodeError('Prestige group boundary inconsistent')
    # On this binary version the group header's 31-entry array count is the
    # unique nonzero reasonable candidate in the header gap immediately after
    # its telemetry field. Do not generalize an offset to other client builds.
    race_count_offsets=[o for o in range(before+len(PRESTIGE),before+110)
                        if _read_int(script,o)==31 and o<group['script_offset']]
    desc_count=script.count(b'TEXT_EVENT_DESCRIPTION_',before,group['script_offset'])
    intro_count=script.count(b'TEXT_CUPS_DESC_PRESTIGE',before,group['script_offset'])
    if len(race_count_offsets)!=1 or desc_count!=30 or intro_count!=1:
        raise DecodeError('race count / serialized race-marker validation failed')
    return {
        'template':group['event_group_name'],
        'telemetry':group['telemetry'],
        'event_file':event_file,
        'based_on_season':group['based_on_season'],
        'cup_car_lookup':group['cup_car_lookup'],
        'index_in_season':group['index_in_season'],
        'race_events_count':31,
        'introductory_race_count':1,
        'following_race_descriptions':desc_count,
        'base_start_utc':iso(start),
        'base_end_utc':iso(end),
        'active_duration_hours':(end-start)//3600,
        'foreshadow_seconds':foreshadow,
        'map_stay_seconds':stay,
        'repeat_seconds':group['time_repeat_duration_seconds'],
        'leaderboard_attached':group['has_leaderboard_object'],
        'serialized_leaderboard_template':group['leaderboard_template_id'],
        'native_field_provenance':{
            'event_file':'RaceEventGroup.get_EventFile (RVA 0x32fb2a8) / JsonData +0x158',
            'race_count':'RaceEventGroup_JsonData.FromBinary (RVA 0x32fd05c)',
            'base_timing':'RaceEventGroup_JsonData.FromBinary (RVA 0x32fd630 to 0x32fd68c)',
            'unique_id':'RaceEventGroup.GenerateUniqueEventID (RVA 0x32fe024)',
        },
        'status':'offline template fields only; actual live season/leaderboard identity not verified',
    }

def event_id(event_file:int, season:int, index_in_season:int, race_ordinal:int)->int:
    """Native GenerateUniqueEventID(int,int,int,int), as padded decimal int.

    Requires caller-verified season. Does not infer from local calendar or
    silently assign a leaderboard-template identifier.
    """
    vals=((event_file,99),(season,999),(index_in_season,99),(race_ordinal,999))
    for v,m in vals:
        if not isinstance(v,int) or isinstance(v,bool) or not 0<=v<=m:
            raise ValueError('race identifier component out of range')
    result=int(f'{event_file:02d}{season:03d}{index_in_season:02d}{race_ordinal:03d}')
    if result>2**31-1:raise ValueError('generated value does not fit signed int32')
    return result

def calendar_occurrence(inputs:dict,at:datetime)->dict:
    """Calendar projection only, NOT a substitute for game repeat-count logic.

    Native CalculateCurrentRepeatCount also uses map-stay behavior and may
    select a different count. The result must not be used as authoritative ID.
    """
    if at.tzinfo is None:raise ValueError('UTC aware datetime required')
    start=datetime.fromisoformat(inputs['base_start_utc'])
    end=datetime.fromisoformat(inputs['base_end_utc'])
    repeat=timedelta(seconds=inputs['repeat_seconds'])
    n=max(0,(at.astimezone(UTC)-start)//repeat)
    s=start+n*repeat;e=end+n*repeat
    return {'calendar_repeat_number':n,'start_utc':s.isoformat(),
            'end_utc':e.isoformat(),'active':s<=at.astimezone(UTC)<e,
            'authoritative_for_runtime_id':False}

def native_repeat_count_projection(inputs:dict,at:datetime)->dict:
    """Approximate compiled CalculateCurrentRepeatCount for ordinary timestamps.

    ARM64 at RVA 0x32fbd90: max(0, floor((now -
    (base_end + TimeStayOnMapAfterCompletion)) / TimeRepeatDuration)).
    The native implementation uses float32 in the floor path; boundary behavior
    should be validated against the client. Unlike `calendar_occurrence`, this
    is the map visibility/repeat counter, not a universal active-event resolver.
    """
    if at.tzinfo is None:raise ValueError('UTC aware datetime required')
    end=datetime.fromisoformat(inputs['base_end_utc'])
    repeat=inputs['repeat_seconds']
    stay=inputs['map_stay_seconds']
    diff=(at.astimezone(UTC)-end).total_seconds()-stay
    count=0 if diff<=0 else int(diff//repeat)
    return {'map_repeat_count':count,
            'source':'RaceEventGroup.CalculateCurrentRepeatCount (RVA 0x32fbd90)',
            'authoritative_for_leaderboard':False}



def extract_script(bundle: bytes) -> bytes:
    """Extract the exact native TextAsset script from the 6.8.0 type-46 bundle.

    Strict about node identity and byte ranges; never scans unrelated strings.
    """
    if not isinstance(bundle, bytes) or not 0 < len(bundle) <= 1_048_576:
        raise DecodeError("invalid Prestige template bundle size")
    _, _, _, nodes = load_unityfs(bundle)
    candidates = [node for name, node in nodes
                  if name == 'CAB-assets_client_metadata_special_ladder_events_database']
    if len(candidates) != 1:
        raise DecodeError("special-ladder node missing or ambiguous")
    node = candidates[0]
    if len(node) < 40:
        raise DecodeError("special-ladder node truncated")
    off = struct.unpack_from('>Q', node, 32)[0]
    if off > len(node) - 12:
        raise DecodeError("invalid TextAsset offset")
    namelen = struct.unpack_from('<I', node, off)[0]
    if namelen > 256 or off + 4 + namelen > len(node):
        raise DecodeError("invalid TextAsset name length")
    name = node[off+4:off+4+namelen].decode('utf-8')
    if name != 'SpecialLadderEvents':
        raise DecodeError("unexpected TextAsset name")
    pos = (off+4+namelen+3)&~3
    if pos+4 > len(node):
        raise DecodeError("missing TextAsset length")
    size = struct.unpack_from('<I', node, pos)[0]
    if size > 16_000_000 or pos+4+size > len(node):
        raise DecodeError("TextAsset content truncated")
    return node[pos+4:pos+4+size]


def decode_prestige_template(bundle: bytes) -> dict:
    """Decode the validated 6.8.0 Prestige binary group, not a guessed ID."""
    return parse_runtime_inputs(extract_script(bundle))
