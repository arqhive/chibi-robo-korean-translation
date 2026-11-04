"""Relocated globals metadata in an isolated copy; actual JP getters in CPU RAM."""
import json,struct
from collections import defaultdict
from capstone import Cs,CS_ARCH_PPC,CS_MODE_32,CS_MODE_BIG_ENDIAN
import prepare_output_probe as p
from inspect_discs import ROOT,save
from translation_tokens import translated_tokens
from verify_message_relocation import encode_text,decode_text

RAM=0x81000000
REGISTRY=0x80345b78
def main():
    cat=ROOT/'translation/text_catalog.json';cat_hash=p.sha(cat.read_bytes())
    rows=[r for r in json.loads(cat.read_text('utf-8')) if r['kind']=='metadata_string']
    plan=json.loads((ROOT/'translation/full_font_plan.json').read_text('utf-8'));assert plan['catalog_sha256']==cat_hash
    mapping={r['character']:r['code'] for r in plan['mapping']};inverse={v:k for k,v in mapping.items()}
    source=ROOT/'work/roundtrip/jp/qp/files/bin/globals.bin';original=source.read_bytes()
    previous=(ROOT/'work/relocation-experiment/bin/globals.bin').read_bytes()
    old_header=struct.unpack_from('<6I',original);base=24+old_header[0]
    meta=bytearray(original[base:base+old_header[1]]);expected={};changes=[]
    for r in rows:
        at=r['pointer_offset']-base;old=struct.unpack_from('<I',meta,at)[0]
        assert base+old==r['offset']
        assert original[r['offset']:r['end']]==b''.join(bytes.fromhex(t['hex']) for t in r['tokens'])
        if r.get('translation') is None:expected[r['id']]=old;continue
        body=b''.join(encode_text(t['source'],mapping) if t['kind']=='text' else bytes.fromhex(t['hex']) for t in translated_tokens(r))
        new=len(meta);meta.extend(body);struct.pack_into('<I',meta,at,new);expected[r['id']]=new
        changes.append({'id':r['id'],'pointer_offset_in_metadata':at,'old':old,'new':new,'bytes':len(body),'selection':r.get('selection')})
    # Keep all old partitions and message relocation offsets intact. Only the
    # metadata offset/size header points to a copied, enlarged partition at EOF.
    relocated=(len(previous)+31)&~31;blob=bytearray(previous);blob.extend(bytes(relocated-len(blob)));blob.extend(meta)
    struct.pack_into('<II',blob,0,relocated-24,len(meta))
    assert blob[8:len(previous)]==previous[8:]
    assert struct.unpack_from('<4I',blob,8)==struct.unpack_from('<4I',previous,8)
    for r in rows:
        pos=struct.unpack_from('<I',meta,r['pointer_offset']-base)[0];assert pos==expected[r['id']]
        raw=bytes(meta[pos:meta.index(0,pos)+1])
        if r.get('translation') is None:assert raw==original[r['offset']:r['end']]
        else:
            wanted=b''.join(encode_text(t['source'],mapping) if t['kind']=='text' else bytes.fromhex(t['hex']) for t in translated_tokens(r))
            # Some fields have binary controls including zeros, so use token size.
            assert bytes(meta[pos:pos+len(wanted)])==wanted
    dol=p.DOL.read_bytes();inv=json.loads(p.INV.read_text());assert p.sha(dol)==inv['dol']['sha256']
    def at(pc,n):
        s=next(s for s in inv['dol']['sections'] if s['ram_address']<=pc and pc+n<=s['ram_address']+s['size'])
        off=s['file_offset']+pc-s['ram_address'];return dol[off:off+n]
    u=p.create_cpu(dol,inv,p.yay0(p.ROMFONT.read_bytes()))
    def load(data):
        u.mem_write(RAM,bytes(data));u.mem_write(REGISTRY+0xcc,struct.pack('>I',RAM))
        u.emu_start(0x80071080,0x80071130,count=200)
        assert u.reg_read(p.reg.UC_PPC_REG_PC)==0x80071130
        hdr=struct.unpack_from('<6I',data)
        for field,offset in [(0xf0,0),(0xf4,2),(0xf8,4)]:
            assert int.from_bytes(u.mem_read(REGISTRY+field,4),'big')==RAM+24+hdr[offset]
    # Discover branch-free metadata getter functions by their JP instructions.
    cs=Cs(CS_ARCH_PPC,CS_MODE_32|CS_MODE_BIG_ENDIAN);cs.skipdata=True
    ins=list(cs.disasm(at(0x8006f000,0x2000),0x8006f000));functions=[]
    for k,i in enumerate(ins):
        if i.mnemonic!='lis' or i.op_str!='r4, -0x7fcc':continue
        chunk=[]
        for q in ins[k:k+100]:
            chunk.append(q)
            if q.mnemonic=='blr':break
        if chunk[-1].mnemonic!='blr' or any(q.mnemonic.startswith('b') for q in chunk[:-1]):continue
        if any(q.mnemonic=='lwz' and '0xf0(' in q.op_str for q in chunk):functions.append(i.address)
    def getter(pc,index):
        u.reg_write(p.regnum(3),index);u.reg_write(p.reg.UC_PPC_REG_LR,p.STOP)
        u.emu_start(pc,p.STOP,count=300);assert u.reg_read(p.reg.UC_PPC_REG_PC)==p.STOP
        return u.reg_read(p.regnum(3))
    grouped=defaultdict(list)
    for r in rows:
        kind,index,field=r['label'].split('.');grouped[(kind,field)].append((int(index),r))
    load(original);bindings={}
    for key,records in grouped.items():
        samples=sorted(records)[:3]
        candidates=[pc for pc in functions if all(getter(pc,index)==RAM+r['offset'] for index,r in samples)]
        if len(candidates)==1:bindings[key]=candidates[0]
    # Check original and translated full tables through the discovered functions.
    tested=[];unbound=[]
    for data,is_new in [(original,False),(blob,True)]:
        load(data)
        for key,records in grouped.items():
            if key not in bindings:
                if is_new:unbound.extend(r['id'] for _,r in records)
                continue
            for index,r in records:
                ptr=getter(bindings[key],index)
                want=RAM+relocated+expected[r['id']] if is_new else RAM+r['offset']
                assert ptr==want,(r['id'],hex(ptr),hex(want))
                if is_new:tested.append(r['id'])
    out=ROOT/'work/metadata-relocation';out.mkdir(parents=True,exist_ok=True);(out/'globals.bin').write_bytes(blob)
    assert p.sha(cat.read_bytes())==cat_hash and source.read_bytes()==original
    save(ROOT/'metadata/metadata_relocation_verification.json',{'catalog_sha256':cat_hash,'original_sha256':p.sha(original),
        'translated_fields':len(changes),'metadata_fields':len(rows),'cpu_verified_fields':len(tested),
        'unbound_fields':unbound,'translated_cpu_verified':sum(r['id'] in tested for r in changes),
        'translated_unbound':[r['id'] for r in changes if r['id'] in unbound],
        'partition_header_cpu_verified':True,'cpu_header_range':['0x80071080','0x80071130'],
        'getters':{'.'.join(k):hex(v) for k,v in bindings.items()},'original_metadata_bytes':old_header[1],
        'new_metadata_bytes':len(meta),'metadata_absolute_offset':relocated,'experiment_file_bytes':len(blob),
        'growth_beyond_message_experiment':len(blob)-len(previous),'experiment_sha256':p.sha(blob),'changes':changes,
        'other_partitions_and_message_addresses_unchanged':True,'new_iso_built':False,'deployable':False,
        'limits':['CPU loads bytes directly; actual resource allocation and loading remain untested',
                  'Unplug rejects nonzero metadata offset; this experiment uses JP CPU evidence instead',
                  'Held translations are exercised, not approved; rendering/window fit not verified']})
    print('PASS:',len(changes),'translated metadata fields;',len(tested),'JP getter checks;',len(unbound),'unbound. No ISO written.')

if __name__=='__main__':main()
