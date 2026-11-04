"""Read-only ISO audit; reconstruct approved graphic containers in RAM only.

Writes an evidence report, never modifies assets or builds an ISO. Visual
observations are recorded separately; byte checks do not identify language.
"""
import json
import struct
from collections import Counter

from inspect_discs import ROOT, save
from verify_qp_repacking import parse, sha
from verify_roundtrip import model_table
from build_integrated_test import graphics


def read(path):
    return json.loads((ROOT / path).read_text('utf-8'))


def main():
    project = read('project.json')
    inv = read('metadata/disc_inventory_jp.json')
    build = read('metadata/integrated_test_build_v04.json')
    original = (ROOT / 'work/roundtrip/jp/qp/qp.rebuilt.bin').read_bytes()
    expected, banner, changes = graphics(project, original, parse(original), inv)
    expected['opening.bnr'] = banner
    catalog = read('metadata/graphics_catalog_jp.json')['images']
    byid = {r['id']: r for r in catalog}
    observations = read('metadata/graphics_visual_observations.json')['groups']
    codes = {r['code'] for r in changes}
    required = {item for o in observations if f"G{o['sheet_index']:04}" in codes for item in o['ids']}
    installed = {r['texture'] for r in changes}
    assert installed == required, (required - installed, installed - required)
    with (ROOT / build['iso']['path']).open('rb') as iso:
        assert (ROOT / build['iso']['path']).stat().st_size == build['iso']['bytes']
        iso.seek(0x424)
        fst_offset, fst_size = struct.unpack('>II', iso.read(8))
        iso.seek(fst_offset)
        table = model_table(iso.read(fst_size))
        nodes = {r['path']: table['entries'][r['index']] for r in inv['files']}
        qnode = nodes['qp.bin']
        iso.seek(qnode['a'])
        qp = iso.read(qnode['b'])
        qfiles = {r['path']: r for r in parse(qp)}
        checked = []
        for name, wanted in expected.items():
            if name == 'opening.bnr':
                node = nodes[name]
                iso.seek(node['a'])
                actual = iso.read(node['b'])
            else:
                node = qfiles[name]
                actual = qp[node['offset']:node['offset'] + node['size']]
            assert actual == wanted, name
            checked.append(dict(file=name, bytes=len(actual), sha256=sha(actual), exact=True))
        states = {r['pixel_sha256']: r for r in project['graphics_selection']}
        remaining = []
        for o in observations:
            state = states[o['pixel_sha256']]
            if not (state['selection'].startswith('hold_') or o['sheet_index'] in (199, 204)):
                continue
            for identity in o['ids']:
                asset = byid[identity]
                name = 'pc.bin' if asset['file'].startswith('pc.bin/entry-') else asset['file']
                node = qfiles[name]
                at = node['offset'] + asset['data_offset'] + asset.get('archive_offset', 0)
                raw = qp[at:at + asset['data_size']]
                assert sha(raw) == asset['raw_sha256'], identity
            remaining.append(dict(code=f"G{o['sheet_index']:04}", ids=o['ids'],
                                  source_pixels_unchanged=True))
    report = dict(date='2026-10-14', iso=build['iso']['path'],
        method='Read actual v04 FST/QP; reconstruct approved containers in memory and compare whole bytes, including descriptors and palettes; compare catalog duplicate IDs.',
        graphics_groups=len(codes), texture_occurrences=len(installed),
        missing_approved_occurrences=sorted(required - installed), containers=checked,
        remaining_source_groups=remaining,
        current_selection_counts=dict(Counter(r['selection'] for r in project['graphics_selection'])),
        limits=['ISO was not launched; no new gameplay test.',
                'All 49 original base contact sheets manually revisited; 17 rejected descriptors are not valid textures.',
                'Tiny lettering may remain unreadable. No complete movie-frame or dynamic runtime coverage.',
                'Remaining-source check compares texture payloads, not runtime visibility.'],
        visual_evidence='metadata/graphics_recheck_v04_observations.json')
    save(ROOT / 'metadata/graphics_recheck_v04.json', report)
    print(json.dumps(dict(groups=len(codes), textures=len(installed), containers=len(checked),
                          missing=sorted(required-installed), remaining=len(remaining)), ensure_ascii=False))


if __name__ == '__main__':
    main()
