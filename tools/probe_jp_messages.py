"""Analysis-only miniature disc view exposing unchanged JP scripts as bin/e/*.

No boot code or game assets: this is NOT a playable ISO or a translated build.
Used to test an NTSC-U-oriented parser against the Japanese script bytes.
"""
import json
import struct
import subprocess
from inspect_discs import ROOT,save
from verify_roundtrip import digest

def make_archive(files):
    names=bytearray(b'\0bin\0e\0');entries=[[0x01000000,0,3+len(files)],[0x01000001,0,3+len(files)],[0x01000005,1,3+len(files)]]
    for name,b in files:
        off=len(names);names.extend(name.encode('ascii')+b'\0');entries.append([off,0,len(b)])
    hsize=len(entries)*12+len(names);start=(32+hsize+31)&~31;out=bytearray(start)
    for entry,(_,b) in zip(entries[3:],files):
        out.extend(b'\0'*((-len(out))%32));entry[1]=len(out);out.extend(b)
    struct.pack_into('>4I',out,0,0x55aa382d,32,hsize,start)
    for i,e in enumerate(entries):struct.pack_into('>3I',out,32+i*12,*e)
    out[32+len(entries)*12:32+hsize]=names
    return out

def main():
    folder=ROOT/'work/analysis/jp';folder.mkdir(parents=True,exist_ok=True)
    files=[(p.name,p.read_bytes()) for p in sorted((ROOT/'work/roundtrip/jp/qp/files/bin').glob('*.bin'))]
    inv=json.loads((ROOT/'metadata/qp_inventory_jp.json').read_text(encoding='utf-8'))
    for n,b in files:assert digest(b)==next(r['sha256'] for r in inv['files'] if r['path']=='bin/'+n)
    qp=make_archive(files);view=bytearray(0x3000)
    view[:6]=b'GGTJ01';struct.pack_into('>I',view,0x1c,0xc2339f3d)
    fst=struct.pack('>6I',0x01000000,0,2,1,0x3000,len(qp))+b'\0qp.bin\0'
    struct.pack_into('>4I',view,0x420,0,0x2800,len(fst),len(fst));view[0x2800:0x2800+len(fst)]=fst;view.extend(qp)
    path=folder/'parser-only-view.iso';path.write_bytes(view)
    exe=ROOT/'work/research/unplug-release/unplug.exe'
    cmd=[str(exe),'--no-config','--iso',str(path),'messages','export','-o',str(folder/'messages.xml')]
    r=subprocess.run(cmd,capture_output=True);(folder/'parser-view-export.log').write_bytes(r.stdout+r.stderr)
    save(ROOT/'metadata/jp_parser_probe.json',{'input_scripts':len(files),'all_script_bytes_match_original':True,'tool':'Unplug v0.5.1','returncode':r.returncode,'adaptation':'Synthetic nonbootable disc: only original JP bin/*.bin aliased as bin/e/*.bin; actual script bytes unchanged. Not original regional support.','output':'work/analysis/jp/messages.xml','log':'work/analysis/jp/parser-view-export.log'})
    print('JP alias parser exit:',r.returncode);print((r.stdout+r.stderr)[-1300:].decode('utf-8',errors='replace'))

if __name__=='__main__':main()
