"""Explicitly authorized v04: combined centering + immutable font recipe.

Verify every disc byte and both output copies before any obsolete-build cleanup.
"""
import hashlib
import shutil
import struct
from pathlib import Path
import prepare_output_probe as p
from prepare_v03_corrections import read
from build_runtime_v03 import digest
from build_output_probe import apply_disc_changes
from verify_roundtrip import model_table

ROOT=p.ROOT
NAME='ChibiRobo_KO_Test_v04_GmarketBold.iso'
OUTPUT=ROOT/'build'/NAME
DESKTOP=Path.home()/'Desktop'/NAME


def main():
    auth=read('project.json')['checks']['build_v04']['authorization']
    assert auth=='2026-10-14 user: ㄱㄱ (v04 시험 ISO 빌드 안내에 대한 지시)'
    partial=OUTPUT.with_suffix('.iso.partial');desktop_partial=DESKTOP.with_suffix('.iso.partial')
    assert all(not x.exists() for x in [OUTPUT,partial,DESKTOP,desktop_partial])
    base=read('metadata/integrated_test_build_v03.json');source=ROOT/base['iso']['path']
    assert source.is_file(),'Reconstruct v03 using its preserved recipe before this incremental build.'
    assert digest(source)==base['iso']['sha256']
    checks=read('metadata/v04_font_lifetime_verification.json')
    recipe_path=ROOT/checks['recipe'];assert p.sha(recipe_path.read_bytes())==checks['recipe_sha256']
    recipe=read(checks['recipe']);start=recipe['disc_offset']
    assert checks['source_build_sha256']==base['iso']['sha256']
    assert recipe['base_dol_sha256']==base['dol']['sha256']
    assert recipe['expected_dol_sha256']==checks['candidate_dol_sha256']
    with source.open('rb') as f:
        f.seek(start);old=f.read(recipe['base_dol_bytes'])
        gap=f.read(len(bytes.fromhex(recipe['append_hex'])))
    assert p.sha(old)==recipe['base_dol_sha256'] and p.sha(gap)==recipe['disc_append_before_sha256']
    dol=bytearray(old)
    for patch in recipe['patches']:
        at=patch['offset'];before=bytes.fromhex(patch['before']);after=bytes.fromhex(patch['after'])
        assert len(before)==len(after) and dol[at:at+len(before)]==before
        dol[at:at+len(after)]=after
    dol.extend(bytes.fromhex(recipe['append_hex']))
    assert len(dol)==recipe['new_dol_bytes'] and p.sha(dol)==recipe['expected_dol_sha256']
    assert start+len(dol)<=5177344
    changes=[(start,bytes(dol))];position=0;expected=hashlib.sha256()
    print('Writing v04 exclusive partial...',flush=True)
    with source.open('rb') as src,partial.open('xb') as dst:
        while raw:=src.read(8*1024*1024):
            data=apply_disc_changes(raw,position,changes);dst.write(data);expected.update(data);position+=len(raw)
    assert position==base['iso']['bytes']
    print('Rereading every ISO byte and all FST files...',flush=True)
    position=0;actual=hashlib.sha256();base_hash=hashlib.sha256()
    with source.open('rb') as src,partial.open('rb') as dst:
        while raw:=src.read(8*1024*1024):
            after=dst.read(len(raw));assert after==apply_disc_changes(raw,position,changes)
            actual.update(after);base_hash.update(raw);position+=len(raw)
        assert dst.read(1)==b'' and actual.hexdigest()==expected.hexdigest()
        assert base_hash.hexdigest()==base['iso']['sha256']
        dst.seek(start);assert dst.read(len(dol))==dol
        dst.seek(0x420);doff,fst_offset,fst_size=struct.unpack('>3I',dst.read(12));assert doff==start
        dst.seek(fst_offset);fst=dst.read(fst_size);src.seek(fst_offset);assert src.read(fst_size)==fst
        file_checks=0
        for node in model_table(fst)['entries']:
            if node['kind']!=0:continue
            assert node['a']+node['b']<=position
            assert node['a']+node['b']<=start or node['a']>=start+len(dol)
            src.seek(node['a']);dst.seek(node['a']);remaining=node['b']
            while remaining:
                amount=min(remaining,8*1024*1024);assert dst.read(amount)==src.read(amount);remaining-=amount
            file_checks+=1
    partial.rename(OUTPUT)
    print('Copying to Desktop and verifying SHA-256...',flush=True)
    shutil.copyfile(OUTPUT,desktop_partial)
    assert digest(desktop_partial)==expected.hexdigest()
    desktop_partial.rename(DESKTOP)
    report={'authorization':auth,'base_v03_sha256':base['iso']['sha256'],
        'iso':{'path':OUTPUT.relative_to(ROOT).as_posix(),'bytes':OUTPUT.stat().st_size,'sha256':expected.hexdigest()},
        'desktop_copy':{'path':str(DESKTOP),'sha256':expected.hexdigest()},
        'dol':{'bytes':len(dol),'sha256':p.sha(dol),'offset':start,'correction_patches':len(recipe['patches'])},
        'text_records':base['text_records'],'graphics_groups':base['graphics_groups'],
        'all_bytes_reread':True,'fst_unchanged':True,'fst_files_unchanged_from_v03':file_checks,
        'correction_cpu_report':'metadata/v04_font_lifetime_verification.json',
        'recipe_sha256':checks['recipe_sha256'],'new_iso_built':True,
        'dolphin_runtime_verified':False,'hardware_verified':False,'limits':checks['limits'],
        'obsolete_build_cleanup':'pending enumerated deletion after successful verification'}
    p.save(ROOT/'metadata/integrated_test_build_v04.json',report)
    print('PASS:',OUTPUT,expected.hexdigest(),flush=True)
    print('Desktop:',DESKTOP,flush=True)


if __name__=='__main__':main()
