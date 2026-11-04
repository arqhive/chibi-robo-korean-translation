"""Read-only qp.bin node table inventory. No extraction or repacking."""
from collections import Counter
import hashlib
import json
from pathlib import PurePosixPath
import struct
from inspect_discs import ROOT,INPUTS,save


def inspect(edition,filename):
    inv=json.loads((ROOT/f'metadata/disc_inventory_{edition}.json').read_text(encoding='utf-8'))
    entry=next(r for r in inv['files'] if r['path']=='qp.bin')
    with (ROOT/filename).open('rb') as f:
        f.seek(entry['offset']);blob=f.read(entry['size'])
    assert hashlib.sha256(blob).hexdigest()==entry['sha256']
    magic,table,header_size,data_offset=struct.unpack_from('>4I',blob)
    assert magic==0x55aa382d and table+header_size<=data_offset<=len(blob)
    word,parent,count=struct.unpack_from('>3I',blob,table)
    assert word>>24==1 and parent==0 and count>0 and count*12<=header_size
    names=blob[table+count*12:table+header_size];stack=[(count,'',0)];files=[]
    for i in range(1,count):
        while i>=stack[-1][0]:stack.pop()
        a,b,c=struct.unpack_from('>3I',blob,table+i*12);kind=a>>24;n=a&0xffffff
        assert kind in (0,1) and n<len(names)
        end=names.index(0,n);name=names[n:end].decode('cp932')
        assert name and name not in ('.','..') and '/' not in name and '\\' not in name
        path=stack[-1][1]+name
        if kind:
            assert b==stack[-1][2] and i<c<=stack[-1][0];stack.append((c,path+'/',i))
        else:
            assert data_offset<=b and b+c<=len(blob)
            files.append({'index':i,'path':path,'offset':b,'size':c,'magic_hex':blob[b:b+min(c,16)].hex(),'sha256':hashlib.sha256(blob[b:b+c]).hexdigest()})
    assert len({r['path'] for r in files})==len(files)
    report={'edition':edition,'container':'qp.bin','magic':'55AA382D','node_table_offset':table,'header_size':header_size,'data_offset':data_offset,'entry_count':count,'files':files,'extensions':dict(Counter(PurePosixPath(r['path']).suffix.lower() or '(none)' for r in files)),'limitations':['Node boundaries and hashes only; payload formats, compression, fonts, text counts and byte-exact repacking not verified.']}
    save(ROOT/f'metadata/qp_inventory_{edition}.json',report)
    print(edition,'qp files:',len(files),'extensions:',report['extensions'])
    print('Named candidates:',[r['path'] for r in files if any(s in r['path'].lower() for s in ['font','message','msg','text'])][:60])


if __name__=='__main__':
    for args in INPUTS:inspect(*args)
