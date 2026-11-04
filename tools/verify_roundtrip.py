"""Extract disk parts/U8 entries, rebuild structured tables, compare complete streams.

Original offsets and opaque gaps are retained. Does not create a playable ISO.
"""
import hashlib
import json
import struct
from inspect_discs import ROOT,INPUTS,save

CHUNK=8*1024*1024
def digest(b):return hashlib.sha256(b).hexdigest()
def model_table(raw):
    count=struct.unpack_from('>I',raw,8)[0];names=raw[count*12:];entries=[]
    for i in range(count):
        w,a,b=struct.unpack_from('>III',raw,i*12);n=w&0xffffff;end=names.index(0,n)
        text=names[n:end].decode('cp932');assert text.encode('cp932')==names[n:end]
        entries.append({'kind':w>>24,'name_offset':n,'name':text,'a':a,'b':b})
    return {'entries':entries,'name_table_hex':names.hex()}
def encode_table(model):
    names=bytearray.fromhex(model['name_table_hex']);out=bytearray()
    for r in model['entries']:
        b=r['name'].encode('cp932')+b'\0';n=r['name_offset'];names[n:n+len(b)]=b
        out.extend(struct.pack('>III',r['kind']<<24|n,r['a'],r['b']))
    return out+names
def u8_roundtrip(edition,blob,folder):
    folder.mkdir(parents=True,exist_ok=True)
    magic,table,headersize,data=struct.unpack_from('>4I',blob)
    inv=json.loads((ROOT/f'metadata/qp_inventory_{edition}.json').read_text(encoding='utf-8'))
    model=model_table(blob[table:table+headersize]);model['header']=[magic,table,headersize,data]
    save(folder/'table.json',model)
    parts=[];pos=0
    for i,r in enumerate(sorted(inv['files'],key=lambda r:r['offset'])):
        assert r['offset']>=pos,'Overlapping/shared U8 ranges need explicit handling'
        if r['offset']>pos:parts.append({'start':pos,'size':r['offset']-pos,'file':f'gaps/{i:04}.bin','kind':'gap'})
        parts.append({'start':r['offset'],'size':r['size'],'file':'files/'+r['path'],'kind':'file'});pos=r['offset']+r['size']
    if pos<len(blob):parts.append({'start':pos,'size':len(blob)-pos,'file':'gaps/tail.bin','kind':'gap'})
    for p in parts:
        target=folder/p['file'];target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(blob[p['start']:p['start']+p['size']])
    save(folder/'parts.json',parts)
    out=bytearray()
    for p in json.loads((folder/'parts.json').read_text(encoding='utf-8')):
        assert len(out)==p['start'];b=(folder/p['file']).read_bytes();assert len(b)==p['size'];out.extend(b)
    m=json.loads((folder/'table.json').read_text(encoding='utf-8'))
    struct.pack_into('>4I',out,0,*m['header']);out[table:table+headersize]=encode_table(m)
    assert bytes(out)==blob
    rebuilt=folder/'qp.rebuilt.bin';rebuilt.write_bytes(out)
    return rebuilt,{'files':len(inv['files']),'size':len(out),'sha256':digest(out),'differing_bytes':0,'overlapping_file_ranges':0,'limits':'U8 table and payload extraction/repacking; nested payload formats remain opaque.'}

def main():
    reports=[]
    originals=json.loads((ROOT/'metadata/originals.json').read_text(encoding='utf-8'))['files']
    for region,filename in INPUTS:
        inv=json.loads((ROOT/f'metadata/disc_inventory_{region}.json').read_text(encoding='utf-8'))
        folder=ROOT/f'work/roundtrip/{region}';folder.mkdir(parents=True,exist_ok=True)
        parts=[{'start':inv['dol']['offset'],'size':inv['dol']['size'],'kind':'dol','name':'main.dol'},
               {'start':inv['fst_offset'],'size':inv['fst_size'],'kind':'fst','name':'fst.bin'}]
        parts += [{'start':r['offset'],'size':r['size'],'kind':'file','name':r['path']} for r in inv['files']]
        covered=[];pos=0
        for p in sorted(parts,key=lambda p:p['start']):
            assert p['start']>=pos,'Overlapping/shared disc ranges need explicit handling'
            if p['start']>pos:covered.append({'start':pos,'size':p['start']-pos,'kind':'opaque','name':'gap'})
            covered.append(p);pos=p['start']+p['size']
        size=(ROOT/filename).stat().st_size
        if pos<size:covered.append({'start':pos,'size':size-pos,'kind':'opaque','name':'tail'})
        with (ROOT/filename).open('rb') as source:
            for i,p in enumerate(covered):
                p['disk_file']=f'{i:03}.bin';source.seek(p['start']);left=p['size']
                with (folder/p['disk_file']).open('wb') as out:
                    while left:
                        b=source.read(min(left,CHUNK));assert b;out.write(b);left-=len(b)
        for p in covered:
            raw=folder/p['disk_file']
            if p['kind']=='fst':
                b=raw.read_bytes();save(folder/'fst.json',model_table(b))
                rebuilt=encode_table(json.loads((folder/'fst.json').read_text(encoding='utf-8')));assert rebuilt==b
                (folder/'fst.rebuilt.bin').write_bytes(rebuilt);p['disk_file']='fst.rebuilt.bin'
            elif p['kind']=='dol':
                b=bytearray(raw.read_bytes());save(folder/'dol_header.json',list(struct.unpack_from('>57I',b)))
                struct.pack_into('>57I',b,0,*json.loads((folder/'dol_header.json').read_text()))
                assert digest(b)==inv['dol']['sha256'];(folder/'main.dol').write_bytes(b);p['disk_file']='main.dol'
            elif p['name']=='qp.bin':
                rebuilt,qp=u8_roundtrip(region,raw.read_bytes(),folder/'qp');p['disk_file']=str(rebuilt.relative_to(folder))
        save(folder/'parts.json',covered)
        h=hashlib.sha256();compared=0
        with (ROOT/filename).open('rb') as source:
            for p in json.loads((folder/'parts.json').read_text(encoding='utf-8')):
                assert compared==p['start'] and (folder/p['disk_file']).stat().st_size==p['size']
                with (folder/p['disk_file']).open('rb') as part:
                    while b:=part.read(CHUNK):
                        assert b==source.read(len(b)),f'Mismatch near {compared:#x}'
                        h.update(b);compared+=len(b)
            assert not source.read(1)
        expected=next(r['sha256'] for r in originals if r['edition']==region)
        assert compared==size and h.hexdigest()==expected
        r={'edition':region,'bytes_compared':compared,'sha256':h.hexdigest(),'differing_bytes':0,'qp':qp,
           'method':'Extract disc parts and every U8 file/gap; reserialize U8/FST names and fields, DOL header; reread components into ordered comparison stream.',
           'limitations':['Original offsets/sizes only. Opaque scripts/models/compression and boot/gap bytes preserved.','Not translated reinsertion, relocation, gameplay or hardware verification. No output ISO.']}
        reports.append(r);print(region,'full disc and U8 exact roundtrip passed',flush=True)
    save(ROOT/'metadata/roundtrip.json',{'editions':reports})

if __name__=='__main__':main()
