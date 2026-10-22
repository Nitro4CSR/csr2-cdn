import json
import struct

import pytest
from csr2cdn._research import dev54_initial_paint_setup as d


def _methods():
    ctor=bytearray(0x46c)
    setup=bytearray(0xfc0)
    garage=bytearray(8)
    for body,base,pairs in [
      (ctor,0x3819978,{0x3819ac8:0x94495fe1,0x3819acc:0xf9003a74}),
      (setup,0x380275c,{
        0x38029d4:0xb9401d08,0x38029d8:0x12b00009,0x38029dc:0x6b09011f,
        0x38029f0:0xf9403a76,0x3802a60:0xf9403a60,0x3802a6c:0xb9401d01,
        0x3802aa8:0xb9002101,0x3803054:0xf9403a60,0x380309c:0xb9002121,
        0x3803680:0xb9406d08,0x3803684:0xb9411e69,0x380369c:0xb9011e68,
        0x38036f4:0xb9406d09,0x38036fc:0xf9403a69,0x3803704:0xb9401929,
        0x380370c:0xb9006d09}),
      (garage,0x3476b30,{0x3476b30:0xb9407000,0x3476b34:0xd65f03c0})]:
        for at,w in pairs.items():struct.pack_into('<I',body,at-base,w)
    return {('CarVisuals','.ctor'):{'rva':hex(0x3819978),'sha256':'x','body':bytes(ctor)},
            ('CarVisuals','Setup'):{'rva':hex(0x380275c),'sha256':'y','body':bytes(setup)},
            ('CarGarageInstance','get_OriginalPaintIndex'):{'rva':hex(0x3476b30),'sha256':'z','body':bytes(garage)}}


def test_native_constructor_and_setup_witness(monkeypatch):
    monkeypatch.setattr(d,'_resolve',lambda *_: _methods())
    result=d.analyze_native(b'm',b'n')
    assert result['paint_list_allocated_in_CarVisuals_constructor']
    assert result['initial_visual_paint_ids_may_be_appended_in_Setup']
    assert result['source_field_equal_to_2147483647_can_be_skipped']
    assert result['selected_paint_index_read_from_garage_car_offset']=='0x6c'
    assert result['garage_original_paint_index_is_separate_offset']=='0x70'
    assert result['paint_zero_current_label'] is None
    assert result['paint_15_current_label'] is None
    assert result['paint_zero_transparent_display_assumption']=='withdrawn_by_operator'
    assert result['complete_runtime_list_reconstructed'] is False
    assert result['production_resolver_changed'] is False


@pytest.mark.parametrize('alter',[(('CarVisuals','.ctor'),0x3819acc),
                                  (('CarVisuals','Setup'),0x38029dc),
                                  (('CarVisuals','Setup'),0x380369c),
                                  (('CarGarageInstance','get_OriginalPaintIndex'),0x3476b30)])
def test_native_fails_closed_when_any_witness_changes(monkeypatch,alter):
    methods=_methods();key,addr=alter
    m=methods[key]
    body=bytearray(m['body'])
    body[addr-int(m['rva'],16)]^=1
    m['body']=bytes(body)
    monkeypatch.setattr(d,'_resolve',lambda *_:methods)
    with pytest.raises(ValueError,match='witness differs'):
        d.analyze_native(b'm',b'n')


def test_unsupported_binary_hash_rejected():
    with pytest.raises(ValueError,match='only the verified'):
        d._resolve(b'not client',b'not client')


def test_direct_calls_and_instruction_bounds():
    ctor=_methods()[('CarVisuals','.ctor')]
    assert d._decode_bl(d._word_at(ctor,0x3819ac8),0x3819ac8)==0x4a71a4c
    assert d._decode_bl(0xd65f03c0,0x3819ac8) is None
    with pytest.raises(ValueError,match='outside'):
        d._word_at(ctor,0x3819977)


def test_no_overwrite(tmp_path):
    out=tmp_path/'out.json';out.write_text('existing')
    with pytest.raises(SystemExit):
        d.main(['--apk',str(tmp_path/'unused.apk'),'--output',str(out)])
    assert out.read_text()=='existing'


def test_native_report_json_redacted(monkeypatch):
    monkeypatch.setattr(d,'_resolve',lambda *_: _methods())
    report=d.analyze_native(b'm',b'n')
    serialized=json.dumps(report)
    assert 'player_uid' not in serialized
    assert 'car_model_key' not in serialized
    assert 'roster' not in report
    assert 'Transparent' not in [report['paint_zero_current_label'],report['paint_15_current_label']]
