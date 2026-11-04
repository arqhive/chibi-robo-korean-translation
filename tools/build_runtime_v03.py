"""Authorized v03 build: guarded v02 DOL corrections, full-disc readback.

The base ISO is disposable. If absent, regenerate it with the preserved v02
recipe before applying this layer. Remove obsolete builds after verification.
"""
import hashlib
import shutil
import struct
from pathlib import Path
import prepare_output_probe as p
import prepare_v03_corrections as fix
from build_output_probe import apply_disc_changes
from verify_roundtrip import model_table

ROOT=p.ROOT
NAME='ChibiRobo_KO_Test_v03_GmarketBold.iso'
OUTPUT=ROOT/'build'/NAME
DESKTOP=Path.home()/'Desktop'/NAME


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while chunk:=f.read(8*1024*1024):h.update(chunk)
    return h.hexdigest()


def main():
    project=fix.read('project.json');auth=project['checks']['build_v03']['authorization']
    assert auth=='2026-10-14 user: 빌드 ㄱㄱ 이전 빌드물은 남기지말고 새 빌드 나올때마다 다 지우세요'
    partial=OUTPUT.with_suffix('.iso.partial');desktop_partial=DESKTOP.with_suffix('.iso.partial')
    assert all(not x.exists() for x in [OUTPUT,partial,DESKTOP,desktop_partial])
    base_report=fix.read('metadata/integrated_test_build_v02.json');source=ROOT/base_report['iso']['path']
    if not source.exists():
        # v02 is a reproducible temporary input, not a retained old release.
        import build_integrated_test
        report_path=ROOT/'metadata/integrated_test_build_v02.json';saved=report_path.read_bytes()
        try:build_integrated_test.main()
        finally:report_path.write_bytes(saved)
    assert digest(source)==base_report['iso']['sha256']
    fix.main()
    recipe=fix.read('work/runtime-corrections/v03/recipe.json')
    checks=fix.read('metadata/v03_corrections_verification.json')
    assert p.sha((ROOT/'work/runtime-corrections/v03/recipe.json').read_bytes())==checks['recipe_sha256']
    start=recipe['disc_offset']
    with source.open('rb') as f:
        f.seek(start);old=f.read(recipe['base_dol_bytes']);gap=f.read(len(bytes.fromhex(recipe['append_hex'])))
    assert p.sha(old)==recipe['base_dol_sha256'] and p.sha(gap)==recipe['disc_append_before_sha256']
    dol=bytearray(old)
    for patch in recipe['patches']:
        at=patch['offset'];before=bytes.fromhex(patch['before']);after=bytes.fromhex(patch['after'])
        assert len(before)==len(after) and dol[at:at+len(before)]==before
        dol[at:at+len(after)]=after
    dol.extend(bytes.fromhex(recipe['append_hex']))
    assert len(dol)==recipe['new_dol_bytes'] and p.sha(dol)==recipe['expected_dol_sha256']
    changes=[(start,bytes(dol))];position=0;expected=hashlib.sha256()
    print('Writing v03 exclusive partial...',flush=True)
    with source.open('rb') as src,partial.open('xb') as dst:
        while raw:=src.read(8*1024*1024):
            data=apply_disc_changes(raw,position,changes);dst.write(data);expected.update(data);position+=len(raw)
    assert position==base_report['iso']['bytes']
    print('Rereading every ISO byte; verifying only declared DOL changes...',flush=True)
    position=0;actual=hashlib.sha256();base_hash=hashlib.sha256()
    with source.open('rb') as src,partial.open('rb') as dst:
        while raw:=src.read(8*1024*1024):
            after=dst.read(len(raw));assert after==apply_disc_changes(raw,position,changes)
            actual.update(after);base_hash.update(raw);position+=len(raw)
        assert dst.read(1)==b'' and actual.hexdigest()==expected.hexdigest()
        assert base_hash.hexdigest()==base_report['iso']['sha256']
        dst.seek(start);assert dst.read(len(dol))==dol
        dst.seek(0x420);doff,fst_offset,fst_size=struct.unpack('>3I',dst.read(12));assert doff==start
        dst.seek(fst_offset);fst=dst.read(fst_size);src.seek(fst_offset);assert src.read(fst_size)==fst
        table=model_table(fst);file_checks=0
        for node in table['entries']:
            if node['kind']!=0:continue
            src.seek(node['a']);dst.seek(node['a']);remaining=node['b']
            while remaining:
                amount=min(remaining,8*1024*1024);assert dst.read(amount)==src.read(amount);remaining-=amount
            file_checks+=1
    partial.rename(OUTPUT)
    shutil.copyfile(OUTPUT,desktop_partial)
    assert digest(desktop_partial)==expected.hexdigest()
    desktop_partial.rename(DESKTOP)
    report={'authorization':auth,'base_v02_sha256':base_report['iso']['sha256'],
        'iso':{'path':OUTPUT.relative_to(ROOT).as_posix(),'bytes':OUTPUT.stat().st_size,'sha256':expected.hexdigest()},
        'desktop_copy':{'path':str(DESKTOP),'sha256':expected.hexdigest()},
        'dol':{'bytes':len(dol),'sha256':p.sha(dol),'offset':start,'correction_patches':len(recipe['patches'])},
        'text_records':8385,'graphics_groups':12,'all_bytes_reread':True,'fst_unchanged':True,
        'fst_files_unchanged_from_v02':file_checks,'correction_cpu_report':'metadata/v03_corrections_verification.json',
        'new_iso_built':True,'dolphin_runtime_verified':False,'hardware_verified':False,
        'limits':checks['limits'],'obsolete_build_cleanup':'pending enumerated deletion after successful verification'}
    p.save(ROOT/'metadata/integrated_test_build_v03.json',report)
    print('PASS:',OUTPUT,expected.hexdigest(),flush=True)
    print('Desktop:',DESKTOP,flush=True)


if __name__=='__main__':main()
