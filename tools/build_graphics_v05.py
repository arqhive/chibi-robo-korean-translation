"""Authorized v05: append four RGBA8 textures and replace one RGBA8 image.

Repack only the five affected QP members. Keep HSD data-relative relocation
targets and root/name tables; append image data before the relocation table.
Re-read the entire ISO and Desktop copy before allowing old build cleanup.
"""
import hashlib
import json
import shutil
import struct
from pathlib import Path
import numpy as np
from PIL import Image
from inspect_discs import ROOT, save
from verify_roundtrip import model_table
from verify_qp_repacking import parse, repack, verify, sha, align
from decode_gx import decode, size
from build_output_probe import apply_disc_changes
from build_runtime_v03 import digest

NAME='ChibiRobo_KO_Test_v05_GmarketBold.iso'
OUTPUT=ROOT/'build'/NAME
DESKTOP=Path.home()/'Desktop'/NAME


def read(name):return json.loads((ROOT/name).read_text('utf-8'))


def hsd_upgrade(raw, asset, data):
    total,rel,nrel,nroot,nref=struct.unpack_from('>5I',raw)
    assert total==len(raw)
    desc=asset['descriptor_offset'];old_end=32+rel
    relocations=struct.unpack_from(f'>{nrel}I',raw,old_end)
    assert desc-32 in relocations
    assert struct.unpack_from('>I',raw,desc)[0]==asset['data_offset']-32
    assert struct.unpack_from('>I',raw,desc+8)[0]==14
    start=align(rel);new_rel=start+len(data)
    out=bytearray(raw[:old_end]);out.extend(bytes(start-rel));out.extend(data);out.extend(raw[old_end:])
    struct.pack_into('>II',out,0,len(out),new_rel)
    struct.pack_into('>I',out,desc,start);struct.pack_into('>I',out,desc+8,6)
    assert out[32+new_rel:]==raw[old_end:]
    restored=bytearray(out[:old_end]);restored[:8]=raw[:8]
    restored[desc:desc+4]=raw[desc:desc+4];restored[desc+8:desc+12]=raw[desc+8:desc+12]
    assert restored==raw[:old_end]
    # All relocation locations remain stable within the unchanged data prefix.
    for offset in relocations:
        assert offset+4<=rel
        actual=struct.unpack_from('>I',out,32+offset)[0]
        expected=start if offset==desc-32 else struct.unpack_from('>I',raw,32+offset)[0]
        assert actual==expected and actual<new_rel
    roots=32+new_rel+4*nrel
    for i in range(nroot+nref):
        ptr,name=struct.unpack_from('>II',out,roots+8*i)
        assert ptr<new_rel and roots+8*(nroot+nref)+name<len(out)
    return bytes(out),32+start,dict(old_data_bytes=rel,new_data_bytes=new_rel,
        relocation_entries=nrel,root_entries=nroot+nref,unchanged_relocation_and_name_table=True)


def prepare(qp, project):
    cat={r['id']:r for r in read('metadata/graphics_catalog_jp.json')['images']}
    files=parse(qp);byname={r['path']:r for r in files};replacements={};records=[]
    states={r['pixel_sha256']:r for r in project['graphics_selection']}
    rows=read('metadata/extra_graphics_drafts_v03.json')['textures']
    assert {r['code'] for r in rows}=={'G0204','G2281','G2282','G2283','G2284'}
    for row in rows:
        a=cat[row['texture']];state=states[a['pixel_sha256']]['additional_draft_review']
        assert state['approval']==project['checks']['build_v05']['authorization']
        png=(ROOT/row['candidate_path']).read_bytes()
        assert sha(png)==row['candidate_sha256']==state['sha256']
        assert (ROOT/state['approved_path']).read_bytes()==png
        assert (ROOT/state['backup_path']).read_bytes()==png
        data=(ROOT/row['encoded_path']).read_bytes();assert sha(data)==row['encoded_sha256']
        assert row['format']==6 and len(data)==size(a['width'],a['height'],6)
        member=byname[a['file']];raw=qp[member['offset']:member['offset']+member['size']]
        assert sha(raw[a['data_offset']:a['data_offset']+a['data_size']])==a['raw_sha256']
        desc=a['descriptor_offset'];structure={}
        if a['kind']=='tpl':
            assert project['graphics_work_rules']['format_exceptions'][row['code']]==6
            start=align(len(raw));out=bytearray(raw);out.extend(bytes(start-len(raw)));out.extend(data)
            struct.pack_into('>II',out,desc+4,6,start)
            restored=bytearray(out[:len(raw)]);restored[desc+4:desc+12]=raw[desc+4:desc+12];assert restored==raw
            _,count,table=struct.unpack_from('>III',out)
            for i in range(count):
                at,pal=struct.unpack_from('>II',out,table+i*8)
                h,w,fmt,off=struct.unpack_from('>HHII',out,at)
                assert off+size(w,h,fmt)<=len(out)
                if at!=desc:assert out[at:at+36]==raw[at:at+36]
            structure={'tpl_descriptors_reread':count,'other_descriptors_unchanged':True}
            out=bytes(out)
        elif a['format']==14:
            assert project['graphics_work_rules']['format_exceptions'][row['code']]==6
            out,start,structure=hsd_upgrade(raw,a,data)
        else:
            assert a['format']==6 and len(data)==a['data_size']
            start=a['data_offset'];out=raw[:start]+data+raw[start+len(data):]
            assert len(out)==len(raw)
        # Independently read the new descriptor before decoding its image.
        if a['kind']=='tpl':
            h,w,fmt,offset=struct.unpack_from('>HHII',out,desc)
        else:
            offset,w,h,fmt=struct.unpack_from('>IHHI',out,desc);offset+=32
        assert (w,h,fmt,offset)==(a['width'],a['height'],6,start)
        decoded=decode(out[offset:offset+size(w,h,fmt)],w,h,fmt)
        assert np.array_equal(np.array(decoded),np.array(Image.open(ROOT/row['candidate_path']).convert('RGBA')))
        replacements[a['file']]=out
        records.append(dict(code=row['code'],file=a['file'],texture=row['texture'],
            old_bytes=len(raw),new_bytes=len(out),old_format=a['format'],new_format=6,
            descriptor_offset=desc,data_offset=start,data_sha256=sha(data),png_exact=True,
            container_sha256=sha(out),structure=structure))
    new,layout,padding=repack(qp,files,replacements)
    checked=verify(qp,files,replacements,new,layout)
    assert sum(r['changed_payload'] for r in layout)==5
    return bytes(new),records,layout,padding,len(checked)


def main():
    project=read('project.json');auth=project['checks']['build_v05']['authorization']
    assert '여기까지 빌드' in auth
    base=read('metadata/integrated_test_build_v04.json');source=ROOT/base['iso']['path']
    assert digest(source)==base['iso']['sha256']
    partial=OUTPUT.with_suffix('.iso.partial');dp=DESKTOP.with_suffix('.iso.partial')
    assert all(not x.exists() for x in [OUTPUT,partial,DESKTOP,dp])
    inv=read('metadata/disc_inventory_jp.json')
    with source.open('rb') as f:
        f.seek(0x420);dol_at,fst_at,fst_size=struct.unpack('>3I',f.read(12))
        f.seek(fst_at);fst=f.read(fst_size);model=model_table(fst)
        qentry=next(r for r in inv['files'] if r['path']=='qp.bin');qnode=model['entries'][qentry['index']]
        qoff,oldsize=qnode['a'],qnode['b'];f.seek(qoff);qp=f.read(oldsize)
        f.seek(dol_at);assert sha(f.read(base['dol']['bytes']))==base['dol']['sha256']
    new,graphics,layout,padding,member_count=prepare(qp,project)
    assert len(new)>oldsize
    for node in model['entries']:
        if node['kind']==0 and node is not qnode:
            assert node['a']+node['b']<=qoff or node['a']>=qoff+len(new)
    assert dol_at+base['dol']['bytes']<=qoff and qoff+len(new)<=base['iso']['bytes']
    changes=[(fst_at+qentry['index']*12+8,struct.pack('>I',len(new))),(qoff,new)]
    print('Writing v05: 5 graphics, verified TPL/HSD descriptors and QP repack...',flush=True)
    expected=hashlib.sha256();pos=0
    with source.open('rb') as src,partial.open('xb') as dst:
        while raw:=src.read(8*1024*1024):
            data=apply_disc_changes(raw,pos,changes);dst.write(data);expected.update(data);pos+=len(raw)
    assert pos==base['iso']['bytes']
    print('Rereading every byte, all FST files and all QP members...',flush=True)
    actual=hashlib.sha256();base_hash=hashlib.sha256();pos=0
    with source.open('rb') as src,partial.open('rb') as dst:
        while raw:=src.read(8*1024*1024):
            after=dst.read(len(raw));assert after==apply_disc_changes(raw,pos,changes)
            actual.update(after);base_hash.update(raw);pos+=len(raw)
        assert not dst.read(1) and actual.hexdigest()==expected.hexdigest()
        assert base_hash.hexdigest()==base['iso']['sha256']
        dst.seek(fst_at);afterfst=dst.read(fst_size);restored=bytearray(afterfst)
        at=qentry['index']*12+8;restored[at:at+4]=fst[at:at+4];assert restored==fst
        aftermodel=model_table(afterfst);count=0
        for entry in inv['files']:
            node=aftermodel['entries'][entry['index']]
            dst.seek(node['a']);raw=dst.read(node['b'])
            if entry['path']=='qp.bin':
                assert raw==new
                verify(qp,parse(qp),{r['path']:raw[r['new_offset']:r['new_offset']+r['new_size']] for r in layout if r['changed_payload']},raw,layout)
            else:
                before=model['entries'][entry['index']];assert node==before
                src.seek(before['a']);assert raw==src.read(before['b']);count+=1
        dst.seek(dol_at);assert sha(dst.read(base['dol']['bytes']))==base['dol']['sha256']
    partial.rename(OUTPUT)
    print('Copying to Desktop and checking SHA-256...',flush=True)
    shutil.copyfile(OUTPUT,dp);assert digest(dp)==expected.hexdigest();dp.rename(DESKTOP)
    save(ROOT/'metadata/integrated_test_build_v05.json',dict(authorization=auth,
        base_v04_sha256=base['iso']['sha256'],iso=dict(path=OUTPUT.relative_to(ROOT).as_posix(),bytes=pos,sha256=expected.hexdigest()),
        desktop_copy=dict(path=str(DESKTOP),sha256=expected.hexdigest()),dol=base['dol'],dol_unchanged=True,
        qp=dict(offset=qoff,old_bytes=oldsize,bytes=len(new),sha256=sha(new),member_count=member_count,padding_added=padding),
        text_records=base['text_records'],graphics_groups=base['graphics_groups']+5,graphics_occurrences=18,
        additional_graphics=graphics,qp_changed_files=5,qp_unchanged_files=member_count-5,
        fst_other_files_unchanged=count,all_bytes_reread=True,new_iso_built=True,
        dolphin_runtime_verified=False,hardware_verified=False,
        limits=['Static container/relocation/decode/readback verification; new textures not runtime tested.'],
        obsolete_build_cleanup='pending verified cleanup'))
    save(ROOT/'metadata/v05_qp_repack_layout.json',layout)
    print('PASS:',OUTPUT,expected.hexdigest(),flush=True)


if __name__=='__main__':main()
