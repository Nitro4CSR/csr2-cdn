"""Synthetic, offline-only TNR source regression fixtures. No proprietary assets."""
from __future__ import annotations

import hashlib
import io
import json
import lzma
import struct
from contextlib import redirect_stdout

import pytest

from csr2cdn import CrewMemberVehicle, GameVisualLibrary, VisualCodeName
from csr2cdn.visual_library_bundle import decode_visual_unityfs, VisualLibrarySourceError
from csr2cdn.tnr_visual_probe import is_tnr_model

SPECS = {
    "CarTunerStarsPaintLibrary": ("paint", "TNRCarPaint\0CarTNRPaints\0Category\0IncludeToCar\0"),
    "CarTunerStarsInteriorLibrary": ("interior", "TNRCarInterior\0CarTNRInteriors\0Category\0IncludeToCar\0"),
    "CarTunerStarsCalliperLibrary": ("calliper", "TNRCarCalliper\0CarTNRCallipers\0Category\0IncludeToCar\0"),
}


def _ustr(value):
    encoded = value.encode("utf-8")
    raw = struct.pack("<I",len(encoded)) + encoded
    return raw + b"\0" * (-len(raw)%4)


def synthetic_tnr_asset(library, *, duplicate=False, bad_category=False, tail=b""):
    slot, fields = SPECS[library]
    rows = bytearray()
    for i in range(24):
        ident = 1000001 + (0 if duplicate and i == 1 else i)
        name = f"Native name {i}"
        category = "Mazda_RX8TNR0_2008" if i == 23 else "All\r"
        if bad_category and i == 23:
            category = "Unknown car with spaces"
        if slot == 'paint':
            rows += _ustr(name) + struct.pack('<iii14f',-1,ident,1,*([0.2]*14))
        elif slot == 'interior':
            rows += struct.pack('<i',ident) + _ustr(name) + _ustr(f"Zone 2 {i}")
            rows += struct.pack('<8fiii',*([0.2]*8),0,1,0)
        else:
            rows += struct.pack('<i',ident) + _ustr(name) + struct.pack('<4fii',*([0.2]*4),1,0)
        rows += struct.pack('<i',0) + _ustr(category)
    data_offset = 512
    fixed = bytearray(64)
    struct.pack_into('>I',fixed,8,22)
    struct.pack_into('>Q',fixed,32,data_offset)
    metadata = fields.encode('ascii')
    node = (bytes(fixed) + metadata.ljust(data_offset-len(fixed), b'\0') +
            _ustr(library) + b'\0'*112 + struct.pack('<I',24) + rows + tail + b'\0'*16 + library.encode('ascii')+b'\0')
    packed = (b'\x5d' + struct.pack('<I',512*1024) +
        lzma.compress(node,format=lzma.FORMAT_RAW,filters=[{
          'id':lzma.FILTER_LZMA1,'dict_size':512*1024,'lc':3,'lp':0,'pb':2,
        }]))
    blocks = (b'\0'*16 + struct.pack('>I',1) + struct.pack('>IIH',len(node),len(packed),1)
           + struct.pack('>I',1) + struct.pack('>QQI',0,len(node),4) + b'CAB-synthetic\0')
    hdr = (b'UnityFS\0' + struct.pack('>I',8)+b'5.x.x\0'+b'2021.3.16f1\0'+
           struct.pack('>QIII',0,len(blocks),len(blocks),0x240))
    hdr += b'\0' * (-len(hdr)%16)
    bundle = hdr + blocks + b'\0' * (-(len(hdr)+len(blocks))%16) + packed
    result = bytearray(bundle)
    struct.pack_into('>Q',result,len(b'UnityFS\0')+4+len(b'5.x.x\0')+len(b'2021.3.16f1\0'),len(result))
    return bytes(result)


@pytest.mark.parametrize('library,kind',[(name,entry[0]) for name,entry in SPECS.items()])
def test_tnr_layout_id_name_category_and_hash(library,kind):
    raw=synthetic_tnr_asset(library)
    parsed=decode_visual_unityfs(raw,library=library)
    assert len(parsed.records)==24
    assert all(row.slot==kind for row in parsed.records)
    assert parsed.records[0].model_key=='*'
    assert parsed.records[-1].model_key=='Mazda_RX8TNR0_2008'
    assert parsed.records[0].source_sha256==hashlib.sha256(raw).hexdigest()
    assert parsed.match('Mazda_RX8TNR0_2008',kind,1000024).name=='Native name 23'
    assert parsed.match('Honda_CivicEGTNR2_1995',kind,1000024) is None
    if kind=='interior':
        assert parsed.records[0].names==('Native name 0','Zone 2 0')


@pytest.mark.parametrize('library',list(SPECS))
@pytest.mark.parametrize('corrupt',('duplicate','category'))
def test_tnr_bad_primary_array_fails_closed(library,corrupt):
    kw={'duplicate':True} if corrupt=='duplicate' else {'bad_category':True}
    with pytest.raises(VisualLibrarySourceError):
        decode_visual_unityfs(synthetic_tnr_asset(library,**kw),library=library)


def test_tnr_vs_standard_names_bind_only_with_tnr_model_syntax():
    raw=synthetic_tnr_asset('CarTunerStarsPaintLibrary')
    source=decode_visual_unityfs(raw,library='CarTunerStarsPaintLibrary')
    standard=VisualCodeName('*','paint',29,'Standard paint','CarPaintLibrary')
    library=GameVisualLibrary((standard,*source.records))
    tnr=CrewMemberVehicle.from_wire({'current_car':'Mazda_RX8TNR0_2008','car_paint_id':1000001}).with_visuals(library)
    assert tnr.visuals.paint.name=='Native name 0'
    assert tnr.visuals.paint.source_library=='CarTunerStarsPaintLibrary'
    specific=CrewMemberVehicle.from_wire({'current_car':'Mazda_RX8TNR0_2008','car_paint_id':1000024}).with_visuals(library)
    assert specific.visuals.paint.name=='Native name 23'
    unrelated_tnr=CrewMemberVehicle.from_wire({'current_car':'Honda_CivicEGTNR2_1995','car_paint_id':1000024}).with_visuals(library)
    assert unrelated_tnr.visuals.paint.name is None
    normal=CrewMemberVehicle.from_wire({'current_car':'Ferrari_TNR_branded','car_paint_id':1000001}).with_visuals(library)
    assert normal.visuals.paint.name is None
    regular=CrewMemberVehicle.from_wire({'current_car':'Ferrari_TNR_branded','car_paint_id':29}).with_visuals(library)
    assert regular.visuals.paint.name=='Standard paint'


def test_native_tnr_underscore_year_suffix_recognized_not_branding():
    assert is_tnr_model('Subaru_BRZTNR_2020')
    assert is_tnr_model('Mazda_RX8TNR0_2008')
    assert not is_tnr_model('Ferrari_TNR_branded')
    assert not is_tnr_model(None)


def test_tnr_asset_rejects_random_and_no_network():
    with pytest.raises(VisualLibrarySourceError):
        decode_visual_unityfs(b'\0'*1000,library='CarTunerStarsPaintLibrary')
    from csr2cdn.tnr_visual_probe import main
    stream=io.StringIO()
    with redirect_stdout(stream):
        assert main([])==0
    report=json.loads(stream.getvalue())
    assert report['network_requests']==0


def test_tnr_probe_separates_native_id_candidates_from_standard_hits_without_identity_leak():
    from csr2cdn import AssetDatabase
    from csr2cdn.crew_optional_data import CrewOptionalSnapshot
    from csr2cdn.service_models import OwnCrew, CrewMembers
    from csr2cdn.tnr_visual_probe import assess_tnr_snapshot
    crew = 'PRIVATE_CREW_REFERENCE'
    own = OwnCrew.from_response({'crew_uid': crew, 'members': 2})
    roster = CrewMembers.from_response(crew, {'crew_uid': crew, 'scores': [
        {'player_uid':'PRIVATE_PLAYER_A','name':'HIDDEN_FIRST',
         'current_car':'Mazda_RX8TNR0_2008','car_paint_id':1000001},
        {'player_uid':'PRIVATE_PLAYER_B','name':'HIDDEN_SECOND',
         'current_car':'Normal_Car_2024','car_paint_id':1000001},
    ]})
    snap = CrewOptionalSnapshot.from_reads(own, roster)
    db = AssetDatabase.from_json([{'version':'33695'}, []])
    lib = decode_visual_unityfs(synthetic_tnr_asset('CarTunerStarsPaintLibrary'),
                                library='CarTunerStarsPaintLibrary')
    report = assess_tnr_snapshot(snap, db, lib)
    assert report['cohorts']['tnr_model_syntax']['slot_coverage']['paint']['tnr_library_id_candidate'] == 1
    assert report['cohorts']['other_or_unknown_model']['slot_coverage']['paint']['unresolved'] == 1
    assert report['claims']['tnr_library_matches_prove_game_ui_equivalence'] is False
    assert 'PRIVATE_' not in json.dumps(report)
    assert 'Normal_Car_2024' not in json.dumps(report)
