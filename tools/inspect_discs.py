"""Read-only GameCube header/FST/DOL inventory and cross-region comparison.

Only metadata is written. This does not rebuild or extract a disc image.
"""
from pathlib import Path, PurePosixPath
import collections
import hashlib
import json
import struct
import zlib

ROOT=Path(__file__).resolve().parents[1]
INPUTS=[('jp','Chibi-Robo! (Japan) (Rev 1).iso'),('us','Chibi-Robo! (USA).iso')]


def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')


def hashes(f,offset,size):
    f.seek(offset);h=hashlib.sha256();s=hashlib.sha1();crc=0;left=size
    while left:
        b=f.read(min(left,8*1024*1024))
        if not b:raise ValueError('Unexpected EOF')
        h.update(b);s.update(b);crc=zlib.crc32(b,crc);left-=len(b)
    return dict(sha256=h.hexdigest(),sha1=s.hexdigest(),crc32=f'{crc:08X}')


def inspect(edition,filename):
    p=ROOT/filename;size=p.stat().st_size
    with p.open('rb') as f:
        h=f.read(0x440)
        assert struct.unpack_from('>I',h,0x1c)[0]==0xc2339f3d,'Not a raw GC image'
        doloff,fstoff,fstsize,fstmax=struct.unpack_from('>4I',h,0x420)
        assert 0<fstoff<fstoff+fstsize<=size and fstsize<=fstmax
        f.seek(fstoff);fst=f.read(fstsize)
        rootword,parent,count=struct.unpack_from('>3I',fst)
        assert rootword>>24==1 and parent==0 and 12*count<=len(fst)
        names=fst[12*count:];stack=[(count,'',0)];files=[];dirs=[]
        for i in range(1,count):
            while i>=stack[-1][0]:stack.pop()
            a,b,c=struct.unpack_from('>3I',fst,i*12)
            kind=a>>24;n=a&0xffffff
            assert kind in (0,1) and n<len(names)
            end=names.index(0,n);rawname=names[n:end]
            name=rawname.decode('shift_jis')
            assert name and '/' not in name and name not in ('.','..')
            path=stack[-1][1]+name
            if kind:
                assert b==stack[-1][2] and i<c<=stack[-1][0]
                dirs.append(dict(index=i,path=path,parent_index=b,end_index=c));stack.append((c,path+'/',i))
            else:
                assert b+c<=size
                f.seek(b);magic=f.read(min(c,16)).hex()
                files.append(dict(index=i,path=path,offset=b,size=c,magic_hex=magic,**hashes(f,b,c)))
        assert len({x['path'] for x in files})==len(files)
        f.seek(doloff);dh=f.read(0x100)
        offsets=struct.unpack_from('>18I',dh,0);addresses=struct.unpack_from('>18I',dh,0x48)
        sizes=struct.unpack_from('>18I',dh,0x90)
        sections=[]
        for i,(o,a,n) in enumerate(zip(offsets,addresses,sizes)):
            if not n:continue
            assert o>=0x100 and doloff+o+n<=size
            sections.append(dict(section=i,kind='text' if i<7 else 'data',file_offset=o,ram_address=a,size=n,**hashes(f,doloff+o,n)))
        dolsize=max(x['file_offset']+x['size'] for x in sections)
        report=dict(edition=edition,path=filename,size_bytes=size,game_id=h[:6].decode('ascii'),
                    disc_number=h[6],revision=h[7],title=h[0x20:0x400].split(b'\0')[0].decode('ascii'),
                    gc_magic='C2339F3D',**hashes(f,0,size))
        inventory=dict(edition=edition,fst_offset=fstoff,fst_size=fstsize,entry_count=count,directories=dirs,
                       files=files,dol=dict(offset=doloff,size=dolsize,sections=sections,**hashes(f,doloff,dolsize)),
                       extensions=dict(collections.Counter(PurePosixPath(x['path']).suffix.lower() or '(none)' for x in files)))
    print(edition,report['game_id'],'files',len(files),'directories',len(dirs),'extensions',inventory['extensions'],flush=True)
    return report,inventory


def main():
    oldpath=ROOT/'metadata/originals.json'
    old=json.loads(oldpath.read_text(encoding='utf8')) if oldpath.exists() else None
    results=[inspect(*args) for args in INPUTS]
    if old:
        for r,_ in results:
            assert next(x['sha256'] for x in old['files'] if x['path']==r['path'])==r['sha256'],'Original image changed'
    save(oldpath,dict(recorded_date='2026-10-14',files=[r for r,_ in results]))
    for r,inv in results:save(ROOT/f"metadata/disc_inventory_{r['edition']}.json",inv)
    a,b=({x['path']:x for x in inv['files']} for _,inv in results)
    common=sorted(a.keys()&b.keys());equal=[p for p in common if a[p]['sha256']==b[p]['sha256']]
    changed=[p for p in common if p not in equal]
    comparison=dict(common_paths=len(common),identical_files=len(equal),changed_files=len(changed),
                    only_jp=sorted(a.keys()-b.keys()),only_us=sorted(b.keys()-a.keys()),
                    changed=[dict(path=p,jp_size=a[p]['size'],us_size=b[p]['size']) for p in changed],
                    identical_paths=equal,dol_equal=results[0][1]['dol']['sha256']==results[1][1]['dol']['sha256'],
                    limitations=['FST/DOL inventory only; no internal format parsing or roundtrip','Different paths can still refer to equivalent assets; region choice not inferred from counts'])
    save(ROOT/'metadata/edition_comparison.json',comparison)
    print('Comparison:',{k:v for k,v in comparison.items() if k not in ('changed','identical_paths','limitations')},flush=True)


if __name__=='__main__':main()
