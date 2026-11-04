"""Isolated DOL UI pointer/data experiment; no executable or ISO serialization."""
import json,struct
from inspect_discs import ROOT,save
import prepare_output_probe as p
from translation_tokens import translated_tokens
from verify_message_relocation import encode_text

def main():
    cat=ROOT/'translation/text_catalog.json';digest=p.sha(cat.read_bytes())
    rows=[r for r in json.loads(cat.read_text('utf-8')) if r['kind']=='dol_rodata_string_candidate' and r.get('translation') is not None]
    plan=json.loads((ROOT/'translation/full_font_plan.json').read_text('utf-8'));assert plan['catalog_sha256']==digest
    memory=json.loads((ROOT/'metadata/injection_memory_verification.json').read_text('utf-8'));assert memory['catalog_sha256']==digest
    audit=json.loads((ROOT/'metadata/dol_ui_reference_audit.json').read_text('utf-8'));assert audit['summary']['catalog_sha256']==digest
    refs={r['id']:r for r in audit['records']};mapping={m['character']:m['code'] for m in plan['mapping']}
    dol=p.DOL.read_bytes();inv=json.loads(p.INV.read_text());assert p.sha(dol)==inv['dol']['sha256']
    u=p.create_cpu(dol,inv,p.yay0(p.ROMFONT.read_bytes()));start=memory['ui_start'];payload=bytearray();patches=[];details=[]
    for row in rows:
        payload.extend(bytes((-len(payload))%4));address=start+len(payload)
        body=b''.join(encode_text(t['source'],mapping) if t['kind']=='text' else bytes.fromhex(t['hex']) for t in translated_tokens(row))
        payload.extend(body);evidence=refs[row['id']];assert evidence['references']
        for ref in evidence['references']:
            assert ref['kind']=='data_pointer' and ref['interior_delta']==0
            assert struct.unpack_from('>I',dol,ref['file_offset'])[0]==evidence['address']
            patches.append({'file_offset':ref['file_offset'],'address':ref['address'],'old':evidence['address'],'new':address,'id':row['id']})
        details.append({'id':row['id'],'address':address,'bytes':len(body),'body_sha256':p.sha(body)})
    assert len(payload)==memory['ui_bytes'] and p.sha(payload)==memory['ui_sha256']
    assert start+len(payload)<=memory['payload_end']
    assert len({x['address'] for x in patches})==len(patches)
    u.mem_write(start,bytes(payload))
    for x in patches:u.mem_write(x['address'],struct.pack('>I',x['new']))
    # Every referenced table slot now resolves to the exact translated token
    # bytes, including LF/tab and NUL. This is a RAM readback, not a UI draw call.
    byid={r['id']:r for r in details}
    for x in patches:
        value=int.from_bytes(u.mem_read(x['address'],4),'big');r=byid[x['id']]
        assert value==r['address'] and p.sha(bytes(u.mem_read(value,r['bytes'])))==r['body_sha256']
    # Reconstruct allowed byte changes in memory, preserving source strings and
    # all data/code outside the identified 4-byte reference slots.
    view=bytearray(dol)
    for x in patches:struct.pack_into('>I',view,x['file_offset'],x['new'])
    restored=bytearray(view)
    for x in patches:struct.pack_into('>I',restored,x['file_offset'],x['old'])
    assert restored==dol
    for r in rows:assert view[r['offset']:r['end']]==dol[r['offset']:r['end']]
    out=ROOT/'work/ui-relocation';out.mkdir(parents=True,exist_ok=True);(out/'strings.bin').write_bytes(payload)
    save(ROOT/'metadata/ui_relocation_verification.json',{'catalog_sha256':digest,'records':len(rows),'pointer_slots':len(patches),
        'payload_start':start,'payload_bytes':len(payload),'payload_sha256':p.sha(payload),'patches':patches,'strings':details,
        'original_strings_preserved':True,'pointer_reverse_patch_byte_exact':True,'ram_pointer_readback_verified':True,
        'runtime_verified':False,'new_iso_built':False,'dol_written':False,'deployable':False,
        'limits':['References come from a conservative DOL audit; unknown computed or REL references may remain',
                  'Table pointer readback is not actual renderer/window execution','Held DOL UI drafts remain held until binding/runtime review']})
    assert p.sha(cat.read_bytes())==digest and p.DOL.read_bytes()==dol
    print('PASS:',len(rows),'UI strings;',len(patches),'pointer slots;',len(payload),'payload bytes. No DOL/ISO written.')

if __name__=='__main__':main()
