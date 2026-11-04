"""Nonbootable append/return relocation experiment on copied message candidates.

Opcode 3 semantics are the local Unplug reference model, NOT yet CPU-verified for
Japanese Rev1. No archive/ISO rebuilt. Held records are exercised, not approved.
"""
import copy,json,struct
from collections import defaultdict,Counter
from pathlib import Path
import numpy as np
from inspect_discs import ROOT
from prepare_output_probe import sha
from translation_tokens import translated_tokens
from analyze_stage1 import parse_msg

def encode_text(text,mapping):
    return b''.join(mapping[c].to_bytes(2,'big') if c in mapping else c.encode('cp932') for c in text)

def decode_text(data,inverse):
    out=[];i=0
    while i<len(data):
        b=data[i];n=2 if 0x81<=b<=0x9f or 0xe0<=b<=0xfc else 1
        raw=data[i:i+n];code=int.from_bytes(raw,'big')
        out.append(inverse[code] if n==2 and code in inverse else raw.decode('cp932'));i+=n
    return ''.join(out)

def verify_record(blob,r,base,mapping,inverse):
    at=r['opcode_offset'];assert blob[at]==3
    relocated=base+struct.unpack_from('<I',blob,at+1)[0]
    assert relocated==r['relocated_absolute'] and blob[relocated]==r['opcode']
    end=base+struct.unpack_from('<I',blob,relocated+1)[0]
    assert end==r['relocated_end_absolute']
    _,tokens,_=parse_msg(blob[relocated+5:end],'jp')
    expected=translated_tokens(r)
    assert len(tokens)==len(expected)
    for a,b in zip(tokens,expected):
        assert a['kind']==b['kind']
        if a['kind']=='text':assert decode_text(bytes.fromhex(a['hex']),inverse)==b['source']
        else:assert a['hex']==b['hex']
    assert blob[end]==3 and base+struct.unpack_from('<I',blob,end+1)[0]==r['end']
    return end+5

def main():
    cat=ROOT/'translation/text_catalog.json';initial=sha(cat.read_bytes());rows=json.loads(cat.read_text(encoding='utf-8'))
    plan=json.loads((ROOT/'translation/full_font_plan.json').read_text(encoding='utf-8'));assert plan['catalog_sha256']==initial
    mapping={m['character']:m['code'] for m in plan['mapping']};inverse={v:k for k,v in mapping.items()}
    groups=defaultdict(list)
    for r in rows:
        if r.get('translation') is not None and r['kind']=='script_message_candidate':groups[r['file']].append(copy.deepcopy(r))
    out=ROOT/'work/relocation-experiment';out.mkdir(parents=True,exist_ok=True)
    reports=[];details=[];fixtures=0;encoded_count=0
    for filename,records in sorted(groups.items()):
        source=ROOT/'work/roundtrip/jp/qp/files'/filename;orig=source.read_bytes();original_sha=sha(orig)
        base=struct.unpack_from('<I',orig,16)[0]+24 if filename=='bin/globals.bin' else 0
        blob=bytearray(orig);allowed=np.zeros(len(orig),bool);saved=[]
        previous_end=-1
        for r in sorted(records,key=lambda x:x['opcode_offset']):
            at=r['opcode_offset'];assert previous_end<=at;previous_end=r['end']
            assert orig[at]==r['opcode'] and r['offset']==at+5
            assert base+struct.unpack_from('<I',orig,at+1)[0]==r['end']
            assert orig[at+5:r['end']]==b''.join(bytes.fromhex(t['hex']) for t in r['tokens'])
            ts=translated_tokens(r);body=b''.join(encode_text(t['source'],mapping) if t['kind']=='text' else bytes.fromhex(t['hex']) for t in ts)
            relocated=len(blob);end=relocated+5+len(body)
            blob.extend(bytes([r['opcode']])+struct.pack('<I',end-base)+body+bytes([3])+struct.pack('<I',r['end']-base))
            saved.append((at,orig[at:at+5]));blob[at:at+5]=bytes([3])+struct.pack('<I',relocated-base);allowed[at:at+5]=True
            r.update(relocated_absolute=relocated,relocated_end_absolute=end)
            verify_record(blob,r,base,mapping,inverse)
            details.append({'id':r['id'],'file':filename,'original_entry':at,'original_resume':r['end'],'relocated_entry':relocated,'relocated_resume':end,'original_message_bytes':r['end']-r['offset'],'new_message_bytes':len(body),'selection':r.get('selection'),'deployable':False})
            encoded_count+=1
        if base:
            saved.append((20,orig[20:24]));struct.pack_into('<I',blob,20,len(blob)-base);allowed[20:24]=True
        assert np.array_equal(np.frombuffer(orig,np.uint8)[~allowed],np.frombuffer(blob[:len(orig)],np.uint8)[~allowed])
        for r in records:verify_record(blob,r,base,mapping,inverse)
        restored=bytearray(blob[:len(orig)])
        for at,old in saved:restored[at:at+len(old)]=old
        assert restored==orig
        # Real translated record corruption must be caught, not accepted by
        # merely serializing and reading the same implementation.
        sample=records[0]
        for at in [sample['opcode_offset']+1,sample['relocated_end_absolute']+1]:
            bad=bytearray(blob);bad[at]^=1
            try:verify_record(bad,sample,base,mapping,inverse)
            except (AssertionError,ValueError,IndexError,UnicodeError):fixtures+=1
            else:raise AssertionError('Corrupt branch accepted')
        dest=out/filename;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(blob)
        assert sha(source.read_bytes())==original_sha
        reports.append({'file':filename,'records':len(records),'original_bytes':len(orig),'experiment_bytes':len(blob),'growth_bytes':len(blob)-len(orig),'original_sha256':original_sha,'experiment_sha256':sha(blob),'unchanged_bytes_outside_entry_and_size_fields':True,'reverse_patch_byte_exact':True})
    assert sha(cat.read_bytes())==initial
    report={'catalog_sha256':initial,'files':reports,'records':encoded_count,'corrupt_branch_fixtures_rejected':fixtures,'held_translations_exercised_not_approved':sum((r['selection'] or '').startswith('hold_') for r in details),
        'algorithm':'Preserve original message entry addresses; opcode-3 jump to appended message with new end pointer; opcode-3 return to original resume address.',
        'reference':'Local Unplug event/opcodes/ggte.rs, command.rs, globals/header.rs; NTSC-U semantics only',
        'jp_dispatch_cpu_verified':False,'complete_control_flow_verified':False,'engine_file_size_limit_verified':False,'runtime_verified':False,'new_iso_built':False,'deployable':False,
        'excluded':['metadata strings and pointers','DOL UI strings and references','unknown source decoding','untranslated records'],
        'limits':['Structural message candidates only; this model does not prove Japanese runtime opcode semantics','Select and message wait/resume behavior still need CPU or runtime verification','File growth and archive loader memory constraints unverified','No unknown branch destinations scanned or rewritten; preserved old addresses do not prove absence of pointers into message bodies']}
    (ROOT/'metadata/relocation_experiment.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (out/'records.json').write_text(json.dumps(details,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='files'},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
