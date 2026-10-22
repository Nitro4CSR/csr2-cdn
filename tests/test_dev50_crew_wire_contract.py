"""Synthetic IL2CPP literal-table tests; no actual game assets distributed."""
import json
import struct
from zipfile import ZipFile

import pytest

from csr2cdn._research.dev50_crew_wire_contract import compiled_contract, aggregate_observations, main
from csr2cdn._research.dev48_native_paint_methods import _META_PATH, _SO_PATH
from test_dev48_native_paint_methods import native


def fake_metadata(literals=None, *, wrong_offset=False):
    if literals is None:
        literals = ['car_paint_id', 'car_interior_id', 'car_calliper_id', 'car_wheel_name']
    b = bytearray(4096)
    struct.pack_into('<II', b, 0, 0xFAB11BAF, 31)
    raw = b''.join(x.encode() for x in literals)
    b[1024:1024+len(raw)] = raw
    for hdr, off, length in ((0x08,256,len(literals)*8),
                             (0x10,1024,len(raw)), (0x18,1400,400),
                             (0x30,2000,0), (0xa0,2200,0x58)):
        struct.pack_into('<II', b, hdr, off, length)
    nextoff=0
    for i,v in enumerate(literals):
        struct.pack_into('<II', b, 256+i*8, len(v), (50000 if wrong_offset else nextoff))
        nextoff += len(v)
    b[1400:1400+len(b'CrewMemberCarInfo\0')] = b'CrewMemberCarInfo\0'
    return bytes(b)


def report(items=None):
    if items is None:
        items = [{'attribute':'paint','received_numeric_id':0,'occurrences':8},
                 {'attribute':'paint','received_numeric_id':15,'occurrences':1}]
    return {'status':'received_roster_numeric_ids_absent_from_source_libraries',
            'raw_roster_saved':False,'source_database_version':'34011',
            'coverage_by_attribute':{'paint':{'received_numeric_occurrences':29,
                                             'present_in_sources':20,'absent_from_sources':9}},
            'individual_absent_received_ids':items}


def test_exact_literal_matching_is_not_wire_verification():
    result=compiled_contract(fake_metadata())
    assert result['all_required_wire_spellings_present_once']
    assert result['literal_table_indices']=={'car_paint_id':[0], 'car_interior_id':[1],
                                            'car_calliper_id':[2], 'car_wheel_name':[3]}
    assert result['crew_member_class_present']
    assert result['literal_call_site_in_crew_serializer_verified'] is False


def test_missing_or_similar_names_are_not_exact():
    d=compiled_contract(fake_metadata(['car_paint', 'car_interior_id']))
    assert not d['all_required_wire_spellings_present_once']
    assert d['exact_literal_table_matches']['car_paint_id']==0


def test_duplicate_literal_never_confers_unique_witness():
    r=compiled_contract(fake_metadata(['car_paint_id','car_paint_id']))
    assert r['exact_literal_table_matches']['car_paint_id']==2
    assert not r['all_required_wire_spellings_present_once']


def test_bad_literal_table_offsets_fail_closed():
    with pytest.raises(ValueError, match='literal'):
        compiled_contract(fake_metadata(wrong_offset=True))


def test_corrupt_metadata_fails_closed():
    with pytest.raises(ValueError, match='unsupported'):
        compiled_contract(b'foo')


def test_reconciles_only_redacted_aggregates():
    r=aggregate_observations(report())
    assert r['unmatched_paint_values'][1]['paint_value']==15
    assert r['unmatched_paint_values'][0]['occurrences']==8
    assert r['original_roster_rows_exported'] is False


def test_mismatched_or_duplicated_roster_counts_fail():
    for items in ([{'attribute':'paint','received_numeric_id':0,'occurrences':4}],
                  [{'attribute':'paint','received_numeric_id':0,'occurrences':8},
                   {'attribute':'paint','received_numeric_id':0,'occurrences':1}]):
        with pytest.raises(ValueError):
            aggregate_observations(report(items))


def test_no_raw_roster_accepted():
    r=report();r['raw_roster_saved']=True
    with pytest.raises(ValueError):
        aggregate_observations(r)


def test_symlink_or_existing_output_not_overwritten(tmp_path):
    # The output guard fires even if the fake APK cannot be fully analyzed.
    apk=tmp_path/'mock.apk'
    with ZipFile(apk,'w') as z:
        z.writestr(_META_PATH,fake_metadata())
        z.writestr(_SO_PATH,native())
    out=tmp_path/'existing.json'
    out.write_text('original')
    with pytest.raises(SystemExit):
        main(['--apk',str(apk),'--output',str(out)])
    assert out.read_text()=='original'
