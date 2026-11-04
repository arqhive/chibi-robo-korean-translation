"""Explicitly authorized v02: selected 8,367 text records and 12 graphic groups.

Never overwrite originals or an existing output. Preserve held records and all
unselected data; reread the entire ISO before renaming its exclusive partial.
"""
import copy
import hashlib
import json
import struct
from collections import defaultdict

import prepare_output_probe as p
from inspect_discs import ROOT, save
from verify_integrated_layout import read, assemble_dol, verify_disc, validate_ranges
from build_output_probe import sections, apply_disc_changes
from verify_message_relocation import encode_text, verify_record
from translation_tokens import translated_tokens
from verify_relocation_cpu import verify_cpu
from verify_qp_repacking import parse, repack, verify
from verify_roundtrip import model_table

NAME = 'ChibiRobo_KO_Test_v02_GmarketBold.iso'
OUTPUT = ROOT / 'build' / NAME


def body(row, mapping):
    return b''.join(encode_text(t['source'], mapping) if t['kind'] == 'text' else bytes.fromhex(t['hex'])
                    for t in translated_tokens(row))


def messages(rows, selected, mapping):
    inverse = {v: k for k, v in mapping.items()}; groups = defaultdict(list)
    for row in rows:
        if row['id'] in selected: groups[row['file']].append(copy.deepcopy(row))
    blobs = {}; details = []; reports = []
    for name, records in sorted(groups.items()):
        original = (ROOT / 'work/roundtrip/jp/qp/files' / name).read_bytes()
        base = struct.unpack_from('<I', original, 16)[0] + 24 if name == 'bin/globals.bin' else 0
        blob = bytearray(original); patches = []
        previous_end = -1
        for r in sorted(records, key=lambda x: x['opcode_offset']):
            at = r['opcode_offset']; assert previous_end <= at; previous_end = r['end']
            assert original[at] == r['opcode'] and r['offset'] == at + 5
            assert base + struct.unpack_from('<I', original, at + 1)[0] == r['end']
            assert original[at + 5:r['end']] == b''.join(bytes.fromhex(t['hex']) for t in r['tokens'])
            raw = body(r, mapping); start = len(blob); end = start + 5 + len(raw)
            blob.extend(bytes([r['opcode']]) + struct.pack('<I', end - base) + raw + bytes([3]) + struct.pack('<I', r['end'] - base))
            patches.append((at, original[at:at + 5]))
            blob[at:at + 5] = bytes([3]) + struct.pack('<I', start - base)
            r.update(relocated_absolute=start, relocated_end_absolute=end)
            verify_record(blob, r, base, mapping, inverse)
            details.append({'id': r['id'], 'file': name, 'original_entry': at, 'original_resume': r['end'],
                            'relocated_entry': start, 'relocated_resume': end})
        if base:
            patches.append((20, original[20:24])); struct.pack_into('<I', blob, 20, len(blob) - base)
        restored = bytearray(blob[:len(original)])
        for at, old in patches: restored[at:at + len(old)] = old
        assert restored == original
        # Held and untranslated message headers/bodies must remain executable originals.
        held = [r for r in rows if r['file'] == name and r['kind'] == 'script_message_candidate' and r['id'] not in selected]
        for r in held: assert blob[r['opcode_offset']:r['end']] == original[r['opcode_offset']:r['end']]
        blobs[name] = bytes(blob)
        reports.append({'file': name, 'selected_messages': len(records), 'excluded_messages_verified': len(held),
                        'original_sha256': p.sha(original), 'sha256_before_metadata': p.sha(blob),
                        'original_bytes': len(original), 'bytes_before_metadata': len(blob), 'reverse_patch_byte_exact': True})
    assert len(details) == 7825 and {x['id'] for x in details} == selected
    return blobs, details, reports


def metadata(blobs, rows, selected, mapping, dol):
    name = 'bin/globals.bin'; original = (ROOT / 'work/roundtrip/jp/qp/files' / name).read_bytes()
    previous = blobs[name]; header = struct.unpack_from('<6I', original); base = 24 + header[0]
    meta = bytearray(original[base:base + header[1]]); expected = {}; pointers = []
    all_rows = [r for r in rows if r['kind'] == 'metadata_string']
    for r in all_rows:
        at = r['pointer_offset'] - base; old = struct.unpack_from('<I', meta, at)[0]
        assert base + old == r['offset']
        assert original[r['offset']:r['end']] == b''.join(bytes.fromhex(t['hex']) for t in r['tokens'])
        if r['id'] in selected:
            raw = body(r, mapping); new = len(meta); meta.extend(raw)
            struct.pack_into('<I', meta, at, new); pointers.append((at, old)); expected[r['id']] = (new, raw)
        else: expected[r['id']] = (old, original[r['offset']:r['end']])
    restored = bytearray(meta[:header[1]])
    for at, old in pointers: struct.pack_into('<I', restored, at, old)
    assert restored == original[base:base + header[1]] and len(pointers) == 409
    start = (len(previous) + 31) & ~31
    blob = bytearray(previous); blob.extend(bytes(start - len(blob))); blob.extend(meta)
    struct.pack_into('<II', blob, 0, start - 24, len(meta))
    assert blob[8:len(previous)] == previous[8:]
    for r in all_rows:
        at = struct.unpack_from('<I', meta, r['pointer_offset'] - base)[0]; want, raw = expected[r['id']]
        assert at == want and meta[at:at + len(raw)] == raw
    # Re-run real JP partition header and all known getters using filtered data.
    u = p.create_cpu(dol, {'dol': {'sections': sections(dol)}}, p.yay0(p.ROMFONT.read_bytes()))
    ram = 0x81000000; registry = 0x80345b78
    u.mem_write(ram, bytes(blob)); u.mem_write(registry + 0xcc, struct.pack('>I', ram))
    u.emu_start(0x80071080, 0x80071130, count=200)
    assert u.reg_read(p.reg.UC_PPC_REG_PC) == 0x80071130
    hdr = struct.unpack_from('<6I', blob)
    for field, index in [(0xf0, 0), (0xf4, 2), (0xf8, 4)]:
        assert int.from_bytes(u.mem_read(registry + field, 4), 'big') == ram + 24 + hdr[index]
    getters = read('metadata/metadata_relocation_verification.json')['getters']; tested = set()
    for r in all_rows:
        kind, index, field = r['label'].split('.'); pc = getters.get(kind + '.' + field)
        if not pc: continue
        u.reg_write(p.regnum(3), int(index)); u.reg_write(p.reg.UC_PPC_REG_LR, p.STOP)
        u.emu_start(int(pc, 16), p.STOP, count=300)
        want, raw = expected[r['id']]; ptr = u.reg_read(p.regnum(3))
        assert ptr == ram + start + want and bytes(u.mem_read(ptr, len(raw))) == raw
        tested.add(r['id'])
    assert selected <= tested
    blobs[name] = bytes(blob)
    return {'translated_fields': len(pointers), 'all_fields_readback': len(all_rows), 'cpu_fields': len(tested),
            'cpu_translated_fields': len(selected), 'held_fields_original': 3, 'sha256': p.sha(blob)}


def graphics(project, qp, files, inv):
    catalog = {r['id']: r for r in read('metadata/graphics_catalog_jp.json')['images']}
    assets = {r['pixel_sha256']: r for r in project['graphics_selection']}
    containers = {}; originals = {}; changed = []; groups = set()
    parts = read('work/roundtrip/jp/parts.json')
    formats = read('metadata/approved_texture_formats.json')
    assert not formats['png_confirmation_pending']
    candidate = (ROOT / formats['candidate_path']).read_bytes()
    assert p.sha(candidate) == formats['candidate_sha256']
    for row in read('metadata/graphics_encoding_verification.json')['textures']:
        asset = catalog[row['texture']]; state = assets[asset['pixel_sha256']]
        c = state.get('composite_review') or state.get('reuse')
        assert c and (c.get('approval') or state.get('reuse', {}).get('authorization'))
        assert p.sha((ROOT / c['path']).read_bytes()) == c['sha256'] == row['candidate_sha256']
        if c.get('approved_path'): assert p.sha((ROOT / c['approved_path']).read_bytes()) == c['sha256']
        name = asset['file']; groups.add(row['code'])
        if name not in containers:
            if name == 'opening.bnr':
                old = next(x for x in inv['files'] if x['path'] == name)
                raw = (ROOT / 'work/roundtrip/jp' / next(x['disk_file'] for x in parts if x['name'] == name)).read_bytes()
            else:
                old = next(x for x in files if x['path'] == name)
                raw = qp[old['offset']:old['offset'] + old['size']]
            assert p.sha(raw) == old['sha256']; originals[name] = raw
            containers[name] = bytearray(candidate if name == 'tpl/misc.tpl' else raw)
        if row['code'] in project['graphics_work_rules']['format_exceptions']:
            fmt = next(x for x in formats['textures'] if x['code'] == row['code'])
            assert fmt['candidate_sha256'] == c['sha256'] and fmt['png_exact']
            changed.append({'code': row['code'], 'file': name, 'format': 6, 'texture': row['texture'], 'offset': fmt['data_offset'], 'sha256': fmt['data_sha256']})
            continue
        raw = (ROOT / row['encoded']).read_bytes(); assert p.sha(raw) == row['encoded_sha256']
        at = asset['data_offset']; assert len(raw) == asset['data_size']
        assert p.sha(originals[name][at:at + len(raw)]) == asset['raw_sha256']
        containers[name][at:at + len(raw)] = raw
        changed.append({'code': row['code'], 'file': name, 'format': row['format'], 'texture': row['texture'], 'offset': at, 'sha256': p.sha(raw)})
    assert len(groups) == 12 and len(changed) == 13
    # Reverse every declared field/data edit to prove no extra changes.
    for name, data in containers.items():
        original = originals[name]; restored = bytearray(data[:len(original)])
        for row in changed:
            if row['file'] != name or row['code'] in project['graphics_work_rules']['format_exceptions']: continue
            a = catalog[row['texture']]; at = a['data_offset']; n = a['data_size']
            restored[at:at + n] = original[at:at + n]
        if name == 'tpl/misc.tpl':
            for r in formats['textures']:
                at = r['descriptor_offset'] + 4; restored[at:at + 8] = original[at:at + 8]
                assert p.sha(data[r['data_offset']:r['data_offset'] + r['data_size']]) == r['data_sha256']
        assert restored == original
    banner = bytes(containers.pop('opening.bnr'))
    # BNR1 text starts at 0x1820: text and all header bytes remain original.
    assert banner[:0x20] == originals['opening.bnr'][:0x20]
    assert banner[0x1820:] == originals['opening.bnr'][0x1820:]
    return {k: bytes(v) for k, v in containers.items()}, banner, changed


def write_iso(inv, dol, qp, banner):
    # Reuse verified placement, then add exactly the approved banner replacement.
    placement = verify_disc(inv, dol, qp)
    source_meta = next(x for x in read('metadata/originals.json')['files'] if x['edition'] == 'jp')
    source = ROOT / source_meta['path']; qentry = next(x for x in inv['files'] if x['path'] == 'qp.bin')
    bentry = next(x for x in inv['files'] if x['path'] == 'opening.bnr')
    assert len(banner) == bentry['size']
    changes = [(0x420, struct.pack('>I', placement['dol_offset'])),
        (inv['fst_offset'] + qentry['index'] * 12 + 4, struct.pack('>II', placement['qp_offset'], len(qp))),
        (placement['dol_offset'], dol), (placement['qp_offset'], qp), (bentry['offset'], banner)]
    validate_ranges(changes, source_meta['size_bytes'])
    manifest = []
    with source.open('rb') as src:
        for offset, data in changes:
            src.seek(offset); before = src.read(len(data)); assert len(before) == len(data)
            manifest.append({'offset': offset, 'bytes': len(data), 'before_sha256': p.sha(before), 'after_sha256': p.sha(data)})
    partial = OUTPUT.with_suffix('.iso.partial')
    assert not OUTPUT.exists() and not partial.exists(), 'Refuse to overwrite existing build or partial'
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    source_hash = hashlib.sha256(); output_hash = hashlib.sha256(); position = 0
    with source.open('rb') as src, partial.open('xb') as dst:
        while raw := src.read(8 * 1024 * 1024):
            source_hash.update(raw); new = apply_disc_changes(raw, position, changes)
            dst.write(new); output_hash.update(new); position += len(raw)
    assert position == source_meta['size_bytes'] and source_hash.hexdigest() == source_meta['sha256']
    print('ISO written to exclusive partial; rereading every byte...', flush=True)
    reread_hash = hashlib.sha256(); source_hash = hashlib.sha256(); position = 0
    with source.open('rb') as src, partial.open('rb') as dst:
        while raw := src.read(8 * 1024 * 1024):
            after = dst.read(len(raw)); assert after == apply_disc_changes(raw, position, changes)
            source_hash.update(raw); reread_hash.update(after); position += len(raw)
        assert dst.read(1) == b'' and source_hash.hexdigest() == source_meta['sha256']
        assert reread_hash.hexdigest() == output_hash.hexdigest()
        dst.seek(0x420); doff, fst_offset, fst_size, fst_max = struct.unpack('>4I', dst.read(16))
        assert doff == placement['dol_offset'] and fst_offset == inv['fst_offset'] and fst_size == inv['fst_size']
        dst.seek(doff); assert dst.read(len(dol)) == dol
        dst.seek(fst_offset); table = model_table(dst.read(fst_size))
        for f in inv['files']:
            node = table['entries'][f['index']]; dst.seek(node['a']); raw = dst.read(node['b'])
            if f['path'] == 'qp.bin':
                assert raw == qp and len(parse(raw)) == 1155
            elif f['path'] == 'opening.bnr': assert raw == banner
            else: assert (node['a'], node['b'], p.sha(raw)) == (f['offset'], f['size'], f['sha256'])
    partial.rename(OUTPUT)
    return {'path': OUTPUT.relative_to(ROOT).as_posix(), 'sha256': output_hash.hexdigest(),
            'bytes': position, 'changes': manifest, 'all_bytes_reread': True,
            'fst_files_reread': len(inv['files']), 'unchanged_logical_disc_files': len(inv['files']) - 2,
            'source_sha256_reverified': source_meta['sha256'], 'placement': placement}


def main():
    project = read('project.json'); auth = project['checks']['build_v02']
    assert auth['authorization'] == '2026-10-14 user: 두 그림 확정·제안 범위로 시험 ISO 빌드'
    assert p.sha((ROOT / auth['scope_proposal']).read_bytes()) == auth['scope_sha256']
    assert not OUTPUT.exists() and not OUTPUT.with_suffix('.iso.partial').exists()
    assert p.sha((ROOT / 'translation/text_catalog.json').read_bytes()) == auth['catalog_sha256']
    scope = read(auth['scope_proposal'])['record_ids_by_bucket']; rows = read('translation/text_catalog.json')
    mapping = {r['character']: r['code'] for r in read('translation/full_font_plan.json')['mapping']}
    inv = read('metadata/disc_inventory_jp.json'); dol, dol_report = assemble_dol(inv)
    ui = read('metadata/ui_relocation_verification.json')
    assert {x['id'] for x in ui['strings']} == set(scope['ui_test_candidate_runtime_unverified'])
    blobs, details, script_report = messages(rows, set(scope['script_test_candidate']), mapping)
    meta_report = metadata(blobs, rows, set(scope['metadata_test_candidate']), mapping, dol)
    cpu = verify_cpu(dol, {'dol': {'sections': sections(dol)}}, blobs, details)
    assert cpu['tested_records'] == 7825
    print('PASS: selected 7,825 scripts, 409 metadata fields, 133 UI strings; held records retained.', flush=True)
    original_qp = (ROOT / 'work/roundtrip/jp/qp/qp.rebuilt.bin').read_bytes()
    assert p.sha(original_qp) == next(x['sha256'] for x in inv['files'] if x['path'] == 'qp.bin')
    files = parse(original_qp); gfx, banner, graphic_report = graphics(project, original_qp, files, inv)
    assert not blobs.keys() & gfx.keys(); replacements = {**blobs, **gfx}
    qp, layout, padding = repack(original_qp, files, replacements)
    verify(original_qp, files, replacements, qp, layout)
    out = ROOT / 'work/build-v02'; out.mkdir(parents=True, exist_ok=True)
    save(out / 'qp-layout.json', layout); save(out / 'messages.json', details)
    print('PASS: 12 graphic groups / 13 textures and all 1,155 QP files. Building authorized ISO...', flush=True)
    iso = write_iso(inv, dol, bytes(qp), banner)
    report = {'authorization': auth['authorization'], 'catalog_sha256': auth['catalog_sha256'],
        'scope_sha256': auth['scope_sha256'], 'text_records': 8367, 'graphics_groups': 12,
        'script_files': script_report, 'scripts_cpu': cpu, 'metadata': meta_report, 'dol': dol_report,
        'graphics': graphic_report, 'qp': {'bytes': len(qp), 'growth': len(qp) - len(original_qp),
        'sha256': p.sha(qp), 'files_reread': len(files), 'alignment_bytes_added': padding,
        'changed_files': [x['path'] for x in layout if x['changed_payload']]}, 'iso': iso,
        'held_script_records_original': 97, 'held_metadata_records_original': 3,
        'new_iso_built': True, 'dolphin_runtime_verified': False, 'hardware_verified': False,
        'limits': ['CPU drawing/audio mocked; cache flush system call skipped',
                   'Actual boot, GPU, heap, window fit and level transitions require play testing',
                   'Unknown indirect references and hardcoded disc reads remain possible',
                   'Karaoke video, unread graphics and untranslated text remain original']}
    save(ROOT / 'metadata/integrated_test_build_v02.json', report)
    assert p.sha((ROOT / 'translation/text_catalog.json').read_bytes()) == auth['catalog_sha256']
    print('PASS:', str(OUTPUT), iso['sha256'], flush=True)


if __name__ == '__main__':
    main()
