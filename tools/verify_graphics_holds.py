"""Verify the rejection rule against actual archives and preserve reviewed IDs."""
import json
from collections import Counter
from inspect_discs import ROOT,save
from extract_graphics import Extractor,scalar_relocations
from investigate_graphics_holds import hsd_structure

def main():
    evidence=json.loads((ROOT/'metadata/graphics_hold_evidence.json').read_text())
    catalog=json.loads((ROOT/'metadata/graphics_catalog_jp.json').read_text())
    observed=set()
    for row in catalog['images']:
        if row['kind']!='hsd':continue
        _,rs=hsd_structure(row['file'],row.get('archive_offset',0))
        if scalar_relocations(row['descriptor_offset']-32,rs):observed.add(row['id'])
    expected={r['id'] for r in evidence['rejected_descriptors']}
    assert observed==expected and len(expected)==17
    files=sorted({r['file'] for r in evidence['rejected_descriptors']}|{'test/box_4.dat','test/box_8.dat','test/box_12.dat','test/box_lift.dat'})
    reader=Extractor('jp')
    for file in files:reader.hsd(file,hsd_structure(file)[0])
    prior={r['id']:r for r in catalog['images'] if r['file'] in files}
    current={r['id']:r for r in reader.rows}
    assert current.keys()==prior.keys(), 'Reviewed diagnostic IDs must remain stable'
    for ident,r in current.items():
        assert r['pixel_sha256']==prior[ident]['pixel_sha256']
        if r['kind']=='hsd':assert r['descriptor_valid']==(ident not in expected)
    states=json.loads((ROOT/'project.json').read_text())['graphics_selection']
    state={r['pixel_sha256']:r for r in states}
    assert len(state)==len(states)==2345
    for r in evidence['rejected_descriptors']:assert state[r['pixel_sha256']]['selection']=='exclude_not_texture'
    counts=Counter(r['selection'] for r in states)
    report=dict(full_jp_hsd_candidates_checked=14464,rejected=17,archives_redecoded=len(files),
        stable_id_and_pixel_entries_verified=len(current),selection_counts=dict(counts),
        new_iso_built=False,runtime_visibility_verified=False)
    save(ROOT/'metadata/graphics_hold_verification.json',report)
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
