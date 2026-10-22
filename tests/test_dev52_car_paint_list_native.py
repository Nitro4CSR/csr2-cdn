"""Dev52 strict native witness: no synthetic mappings or online requests."""
import hashlib
import struct
from types import SimpleNamespace
import pytest
from csr2cdn._research.dev52_car_paint_list_native import _verify_car_visual_path, _resolve_car_visual_methods, summarize_received_report


def fake_methods():
    get=struct.pack('<II',0xb9411c00,0xd65f03c0)
    set_ops=[0xb9411c08,0xb9011e61]+[0xd503201f]*11+[0xd65f03c0]
    add_ops=[0xf9403a60,0xb9801808,0x6b14001f,0xb9002114,0xb9011e75]+[0xd503201f]*76+[0xd65f03c0]
    return {
        'get_CurrentPaintIndex':{'body':get},
        'set_CurrentPaintIndex':{'body':struct.pack('<'+'I'*len(set_ops),*set_ops)},
        'SetPaintIDAddIfNecessary':{'body':struct.pack('<'+'I'*len(add_ops),*add_ops)},
    }


def test_car_local_paint_list_and_index_are_separate():
    report=_verify_car_visual_path(fake_methods())
    assert report['car_local_index_and_global_paint_id_are_distinct_concepts']
    assert report['add_if_needed_can_append_absent_paint_id']
    assert report['car_specific_paint_list_content_recovered'] is False
    assert report['paint_index_15_global_paint_id_resolved'] is False


@pytest.mark.parametrize('key,old,new',[ 
 ('get_CurrentPaintIndex',0xb9411c00,0xb9412000),
 ('set_CurrentPaintIndex',0xb9011e61,0xb9012261),
 ('SetPaintIDAddIfNecessary',0xf9403a60,0xf9403260),
 ('SetPaintIDAddIfNecessary',0x6b14001f,0x6b13001f),
 ('SetPaintIDAddIfNecessary',0xb9002114,0xb9002113),
 ('SetPaintIDAddIfNecessary',0xb9011e75,0xb9012275),
])
def test_witness_fails_closed_on_change(key,old,new):
    methods=fake_methods()
    buf=methods[key]['body']
    assert struct.pack('<I',old) in buf
    methods[key]['body']=buf.replace(struct.pack('<I',old),struct.pack('<I',new),1)
    with pytest.raises(ValueError):
        _verify_car_visual_path(methods)


def test_reordered_list_operations_rejected():
    methods=fake_methods()
    ops=list(struct.unpack('<'+'I'*(len(methods['SetPaintIDAddIfNecessary']['body'])//4),methods['SetPaintIDAddIfNecessary']['body']))
    ops[0],ops[3]=ops[3],ops[0]
    methods['SetPaintIDAddIfNecessary']['body']=struct.pack('<'+'I'*len(ops),*ops)
    with pytest.raises(ValueError):_verify_car_visual_path(methods)


def test_sources_contain_no_private_cache_or_gameplay_connector():
    import inspect
    from csr2cdn._research import dev52_car_paint_list_native as mod
    src=inspect.getsource(mod)
    assert 'requests.' not in src
    assert 'from ._service_auth import' not in src
    assert 'endpoint-cache.zip' not in src


def test_redacted_received_roster_overlap_not_verified_mapping():
    received={'status':'received_roster_numeric_ids_absent_from_source_libraries',
        'source_database_version':'34011',
        'coverage_by_attribute':{'paint':{'received_numeric_occurrences':29,'present_in_sources':20,'absent_from_sources':9}},
        'individual_absent_received_ids':[
            {'attribute':'paint','received_numeric_id':0,'occurrences':8},
            {'attribute':'paint','received_numeric_id':15,'occurrences':1}],
        'private_person_name':'should-not-export'}
    r=summarize_received_report(received)
    assert r['paint_numeric_library_overlaps']==20
    assert r['unmatched_paint_values']==[{'numeric_value':0,'occurrences':8},{'numeric_value':15,'occurrences':1}]
    assert r['numeric_library_overlap_proves_semantic_paint_label'] is False
    assert 'should-not-export' not in str(r)
    received['coverage_by_attribute']['paint']['absent_from_sources']=8
    with pytest.raises(ValueError):summarize_received_report(received)


def test_non_dev38_report_is_rejected():
    with pytest.raises(ValueError):summarize_received_report({'status':'source_library_only'})
