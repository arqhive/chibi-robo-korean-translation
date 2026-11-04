"""Read-only compatibility survey of extracted Wii DATA vs original GC JP.

Requires DolphinTool extract -g to work/wii-analysis/extracted. No translation
files, game containers, executable or ISO are modified by this analysis.
"""
import json
import struct
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np
from inspect_discs import ROOT, save
from analyze_stage1 import parse_msg
from verify_qp_repacking import sha
from decode_gx import decode, size, palette_rgba

WII=ROOT/'work/wii-analysis/extracted/DATA/files'
GC=ROOT/'work/roundtrip/jp/qp/files'


def scan(base):
    rows=[]
    for path in sorted((base/'bin').glob('*.bin')):
        original=path.read_bytes();raw=original;offset=0
        if path.name=='globals.bin':
            h=struct.unpack_from('<6I',raw);offset=h[4]+24;raw=raw[offset:offset+h[5]]
        for i,c in enumerate(raw[:-6]):
            if c not in (0x23,0x2b):continue
            end=struct.unpack_from('<I',raw,i+1)[0]
            if not i+6<=end<=min(len(raw),i+4096) or raw[end-1]!=0:continue
            try:text,tokens,tags=parse_msg(raw[i+5:end],'jp')
            except (ValueError,UnicodeError):continue
            content=raw[i+5:end]
            assert b''.join(bytes.fromhex(t['hex']) for t in tokens)==content
            rows.append(dict(file='bin/'+path.name,offset=offset+i,source=text,
                             payload_sha256=sha(content),tags=dict(tags)))
    return rows


def main():
    wf={p.relative_to(WII).as_posix():p for p in WII.rglob('*') if p.is_file()}
    gf={p.relative_to(GC).as_posix():p for p in GC.rglob('*') if p.is_file()}
    wh={name:sha(p.read_bytes()) for name,p in wf.items()}
    gh={name:sha(p.read_bytes()) for name,p in gf.items()}
    common=sorted(wf.keys()&gf.keys());same=[n for n in common if wh[n]==gh[n]]
    gr=scan(GC);wr=scan(WII)
    gtext=Counter((r['file'],r['source']) for r in gr)
    wtext=Counter((r['file'],r['source']) for r in wr)
    graw=Counter((r['file'],r['payload_sha256']) for r in gr)
    wraw=Counter((r['file'],r['payload_sha256']) for r in wr)
    textmatched=sum((gtext&wtext).values());rawmatched=sum((graw&wraw).values())
    novel=wtext-gtext
    examples=[dict(file=k[0],source=k[1],occurrences=n) for k,n in novel.items()]
    # Only source identity, not offsets or semantic context, is established.
    translations=json.loads((ROOT/'translation/text_catalog.json').read_text('utf-8'))
    translated_sources={(r['file'],r['source']) for r in translations if r.get('translation')}
    translated_matches=sum((r['file'],r['source']) in translated_sources for r in wr)
    # Decode Wii TPLs independently, then compare exact native RGBA to GC catalog.
    catalog=json.loads((ROOT/'metadata/graphics_catalog_jp.json').read_text('utf-8'))['images']
    gc_pixels=defaultdict(list)
    for r in catalog:
        if r.get('decoded'):gc_pixels[r['pixel_sha256']].append(r['id'])
    textures=[];errors=[]
    for name,p in sorted(wf.items()):
        if not name.endswith('.tpl'):continue
        b=p.read_bytes();magic,n,table=struct.unpack_from('>III',b)
        if magic!=0x20af30:errors.append(dict(file=name,error='not standard TPL'));continue
        for i in range(n):
            try:
                desc,pal=struct.unpack_from('>II',b,table+i*8)
                h,w,fmt,off=struct.unpack_from('>HHII',b,desc);palette=None
                if pal:
                    count=struct.unpack_from('>H',b,pal)[0];pf,po=struct.unpack_from('>II',b,pal+4)
                    palette=palette_rgba(b[po:po+count*2],pf)
                im=decode(b[off:off+size(w,h,fmt)],w,h,fmt,palette)
                key=sha(struct.pack('>II',w,h)+im.tobytes())
                textures.append(dict(id=f'{name}#tpl-{i:03}',width=w,height=h,format=fmt,
                    pixel_sha256=key,gc_matches=gc_pixels.get(key,[])))
            except (ValueError,KeyError,AssertionError,struct.error) as e:
                errors.append(dict(file=name,index=i,error=str(e)))
    selected=[]
    for report in ['metadata/graphics_encoding_verification.json','metadata/extra_graphics_drafts_v03.json']:
        selected+=json.loads((ROOT/report).read_text('utf-8'))['textures']
    byid={r['id']:r for r in catalog};matching=[]
    for row in selected:
        a=byid[row['texture']]
        matches=[t['id'] for t in textures if t['pixel_sha256']==a['pixel_sha256']]
        matching.append(dict(code=row['code'],gc_texture=row['texture'],wii_exact_tpl_matches=matches))
    wd=(WII.parent/'sys/main.dol').read_bytes();gd=(ROOT/'work/roundtrip/jp/main.dol').read_bytes()
    report=dict(source=read_original(),file_comparison=dict(wii_files=len(wf),gc_qp_files=len(gf),
        same_paths=len(common),byte_identical_same_paths=len(same),same_files=same,
        wii_extensions=dict(Counter(p.suffix for p in wf.values())),
        bin_files=dict(wii=sum(n.startswith('bin/') for n in wf),gc=sum(n.startswith('bin/') for n in gf),
            identical=sum(n.startswith('bin/') for n in same)),
        changed_common_files=[dict(path=n,gc_bytes=gf[n].stat().st_size,wii_bytes=wf[n].stat().st_size) for n in common if n not in same]),
        messages=dict(gc_structural_candidates=len(gr),wii_structural_candidates=len(wr),
            same_source_same_file_occurrences=textmatched,same_raw_message_same_file_occurrences=rawmatched,
            wii_candidates_with_existing_translation_source=translated_matches,
            unmatched_wii_source_occurrences=sum(novel.values()),
            limits='GC-style bounded opcode scan, not Wii control-flow verification. Source equality does not authorize copying event pointers, tags or entire files.'),
        graphics=dict(decoded_wii_tpl_textures=len(textures),gc_pixel_matches=sum(bool(r['gc_matches']) for r in textures),
            errors=errors,approved_gc_asset_matches=matching,
            limits='Exact pixel identity of TPL only. BRRES/BREFT, animations, UVs and runtime consumers not analyzed.'),
        executable=dict(gc_bytes=len(gd),wii_bytes=len(wd),gc_sha256=sha(gd),wii_sha256=sha(wd),byte_identical=gd==wd,
            limit='Font hooks/addresses/memory reservation not ported or tested.'),
        assessment='Existing translation and some graphics reusable; direct GC patched binary/container replacement unsupported. Wii-specific text/code/graphics packaging required.',
        new_patch_built=False,source_image_modified=False)
    save(ROOT/'metadata/wii_compatibility_survey.json',report)
    save(ROOT/'metadata/wii_file_inventory.json',[dict(path=n,bytes=wf[n].stat().st_size,sha256=wh[n]) for n in sorted(wf)])
    save(ROOT/'metadata/wii_tpl_comparison.json',textures)
    save(ROOT/'work/wii-analysis/message_candidates.json',wr)
    save(ROOT/'work/wii-analysis/unmatched_messages.json',examples)
    print(json.dumps(dict(files=report['file_comparison']['bin_files'],messages=report['messages'],
        graphics=dict(decoded=len(textures),matches=report['graphics']['gc_pixel_matches'],errors=errors),
        selected=matching,executable=report['executable']),ensure_ascii=False))


def read_original():return json.loads((ROOT/'metadata/wii_original.json').read_text('utf-8'))
if __name__=='__main__':main()
