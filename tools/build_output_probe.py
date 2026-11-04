"""Explicitly authorized two-menu Japanese Rev1 Gmarket Bold test ISO.

Original ISO is read-only. Writes a new, exclusively created build output only.
Run preparation tools first. Re-running refuses to replace an existing ISO.
This is an output probe, not a full-game translation or a byte-identical roundtrip.
"""
import hashlib
import json
import struct
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from unicorn import UC_HOOK_CODE
import prepare_output_probe as probe
import prepare_probe_layout as layout
from inspect_discs import ROOT, save

NAME = 'ChibiRobo_KO_OutputTest_v01_GmarketBold.iso'
OUTPUT = ROOT / 'build' / NAME
REPORT = ROOT / 'metadata/output_probe_build_v01.json'


def sections(dol):
    out = []
    for i in range(18):
        offset, address, size = [struct.unpack_from('>I', dol, x + i * 4)[0] for x in (0, 0x48, 0x90)]
        if not size: continue
        assert 0x100 <= offset < offset + size <= len(dol)
        assert 0x80000000 <= address < address + size <= 0x81800000
        out.append({'section': i, 'file_offset': offset, 'ram_address': address, 'size': size})
    for a, b in zip(sorted(out, key=lambda s: s['ram_address']), sorted(out, key=lambda s: s['ram_address'])[1:]):
        assert a['ram_address'] + a['size'] <= b['ram_address']
    return out


def ram_offset(inv, address):
    s = next(s for s in inv['dol']['sections'] if s['ram_address'] <= address < s['ram_address'] + s['size'])
    return s['file_offset'] + address - s['ram_address']


def make_dol(original, inv, plan):
    font = ImageFont.truetype(str(probe.FONT), probe.FONT_SIZE)
    assert probe.sha(probe.FONT.read_bytes()) == plan['font_proposal']['sha256']
    assert plan['font_proposal']['family'] == 'Gmarket Sans Bold'
    codes = [int(g['sjis_code'], 16) for g in plan['mapping']]
    assert len(codes) == len(set(codes)) == 7
    glyphs = []
    for entry in plan['mapping']:
        # Render on a larger canvas first and reject clipping before making the tile.
        large = Image.new('L', (64, 64)); d = ImageDraw.Draw(large)
        d.text((20, 20 + probe.BASELINE), entry['hangul'], font=font, fill=255, anchor='ls')
        box = large.getbbox(); assert box and 20 <= box[0] < box[2] <= 44 and 20 <= box[1] < box[3] <= 44
        glyphs.append(probe.pack_i4(large.crop((20, 20, 44, 44))))
    payload = bytearray(layout.RESERVED_END - layout.BASE)
    hook = probe.make_stub(codes, layout.BASE, layout.BITMAPS)
    arena = layout.arena_stub()
    assert len(hook) <= 0x100 and len(arena) <= 0x100
    payload[:len(hook)] = hook
    payload[0x100:0x100 + len(arena)] = arena
    payload[0x200:0x200 + sum(map(len, glyphs))] = b''.join(glyphs)
    changes = []
    out = bytearray(original)
    def replace(off, old, new, reason):
        assert len(old) == len(new) and out[off:off + len(old)] == old
        out[off:off + len(old)] = new
        changes.append({'offset': off, 'size': len(new), 'before': old.hex(), 'after': new.hex(), 'reason': reason})
    for address, target, link, old in [(probe.CALL_SITE, layout.BASE, True, '4bfc7a75'),
                                     (layout.SET_ARENA_LO, layout.ARENA_HOOK, False, '906d8d10')]:
        p = probe.PPC(address); p.branch(target, link)
        replace(ram_offset(inv, address), bytes.fromhex(old), p.finish(), 'glyph call' if link else 'reserve ArenaLo')
    for menu in plan['menus']:
        replace(int(menu['dol_offset'], 16), bytes.fromhex(menu['original_hex']), bytes.fromhex(menu['replacement_hex']), menu['source'] + ' -> ' + menu['translation'])
    payload_offset = (len(original) + 31) & ~31
    for off, value in [(8, payload_offset), (0x50, layout.BASE), (0x98, len(payload))]:
        replace(off, bytes(4), struct.pack('>I', value), 'unused DOL text section2')
    # Independently prove original DOL changes are confined to the declared fields.
    mask = np.zeros(len(original), dtype=bool)
    for c in changes: mask[c['offset']:c['offset'] + c['size']] = True
    diff = np.frombuffer(original, dtype=np.uint8) != np.frombuffer(out, dtype=np.uint8)
    assert not np.any(diff & ~mask)
    out.extend(bytes(payload_offset - len(out))); out.extend(payload)
    assert len(out) == payload_offset + len(payload)
    sections(out)
    return bytes(out), glyphs, changes


def verify_loaded_dol(dol, plan, glyphs):
    # Load serialized sections from the built header, not the preparation layout.
    u = probe.create_cpu(dol, {'dol': {'sections': sections(dol)}}, probe.yay0(probe.ROMFONT.read_bytes()))
    u.mem_write(probe.CACHE, bytes(50 * 320)); u.mem_write(probe.OBJECT, bytes(256))
    u.mem_write(probe.OBJECT + 0x24, struct.pack('>I', 24))
    u.mem_write(probe.R13 - 0x6660, struct.pack('>I', probe.CACHE))
    counts = {'hook': 0, 'flush': 0}
    def trace(cpu, pc, size, data):
        if pc == layout.BASE: counts['hook'] += 1
        if pc == 0x80164b74: counts['flush'] += 1
        if pc == 0x80164b9c: cpu.reg_write(probe.reg.UC_PPC_REG_PC, pc + 4)
    u.hook_add(UC_HOOK_CODE, trace)
    for value in (layout.BASE, layout.RESERVED_END + 0x100):
        u.reg_write(probe.regnum(3), value); u.reg_write(probe.reg.UC_PPC_REG_LR, probe.STOP)
        u.emu_start(layout.SET_ARENA_LO, probe.STOP, count=100)
        assert int.from_bytes(u.mem_read(probe.R13 - 0x72f0, 4), 'big') == max(value, layout.RESERVED_END)
    for menu in plan['menus']:
        expected = bytes.fromhex(menu['replacement_hex'])
        assert bytes(u.mem_read(int(menu['ram_address'], 16), len(expected))) == expected
    for i, entry in enumerate(plan['mapping']):
        code = int(entry['sjis_code'], 16)
        for repeat in range(2):
            u.mem_write(probe.STRING, code.to_bytes(2, 'big') + b'\0')
            for r, value in {1: probe.STACK, 3: probe.OBJECT, 4: probe.STRING, 5: probe.WIDTH}.items(): u.reg_write(probe.regnum(r), value)
            u.reg_write(probe.reg.UC_PPC_REG_LR, probe.STOP)
            u.emu_start(0x801a0448, 0x801a0674, count=100000)
            assert u.reg_read(probe.reg.UC_PPC_REG_PC) == 0x801a0674
            sp = u.reg_read(probe.regnum(1))
            ptr = int.from_bytes(u.mem_read(sp + 0x14, 4), 'big')
            assert ptr == probe.CACHE + 320 * i
            assert bytes(u.mem_read(ptr, 288)) == glyphs[i]
            assert bytes(u.mem_read(ptr + 288, 4)) == struct.pack('>HH', code, probe.ADVANCE)
        assert counts == {'hook': i + 1, 'flush': i + 1}
    return {'glyphs': 7, 'misses': counts['hook'], 'cache_hits': 7, 'flush_calls': counts['flush'],
            'arena_cases': 2, 'menu_bytes': 2, 'limitation': 'Isolated CPU stops before GX; flush sc skipped; not boot/runtime validation.'}


def apply_disc_changes(data, position, changes):
    result = bytearray(data)
    for offset, replacement in changes:
        start = max(position, offset); end = min(position + len(data), offset + len(replacement))
        if start < end: result[start - position:end - position] = replacement[start - offset:end - offset]
    return result


def main():
    state = json.loads((ROOT / 'project.json').read_text(encoding='utf-8'))
    assert state['decisions']['build_requested'] is True, 'Explicit build authorization must be recorded'
    assert state['decisions']['output_probe_font_approved'] == 'Gmarket Sans Bold'
    assert not OUTPUT.exists(), 'Refuse to overwrite an existing test ISO'
    partial = OUTPUT.with_suffix('.iso.partial'); assert not partial.exists(), 'Inspect prior partial build first'
    original_meta = next(x for x in json.loads((ROOT / 'metadata/originals.json').read_text())['files'] if x['edition'] == 'jp')
    source = ROOT / original_meta['path']; assert source.stat().st_size == original_meta['size_bytes']
    inv = json.loads(probe.INV.read_text()); original_dol = probe.DOL.read_bytes()
    assert probe.sha(original_dol) == inv['dol']['sha256']
    plan = json.loads((ROOT / 'translation/output_probe.json').read_text(encoding='utf-8'))
    dol, glyphs, dol_changes = make_dol(original_dol, inv, plan)
    cpu = verify_loaded_dol(dol, plan, glyphs)
    disc_offset = (inv['fst_offset'] + inv['fst_size'] + 31) & ~31
    assert disc_offset + len(dol) < min(f['offset'] for f in inv['files'])
    # Only two disc ranges change: DOL pointer and relocated extended executable.
    changes = [(0x420, struct.pack('>I', disc_offset)), (disc_offset, dol)]
    manifest = []
    with source.open('rb') as src:
        original_hash = hashlib.file_digest(src, 'sha256').hexdigest()
        assert original_hash == original_meta['sha256'], 'Original ISO hash mismatch'
        src.seek(inv['dol']['offset']); assert src.read(len(original_dol)) == original_dol
        src.seek(0x420); assert struct.unpack('>I', src.read(4))[0] == inv['dol']['offset']
        for offset, data in changes:
            src.seek(offset); before = src.read(len(data)); assert len(before) == len(data)
            manifest.append({'disc_offset': offset, 'size': len(data), 'before_sha256': probe.sha(before), 'after_sha256': probe.sha(data)})
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    print('Original SHA256 verified. Writing authorized test ISO...', flush=True)
    source_hash = hashlib.sha256(); output_hash = hashlib.sha256(); position = 0
    with source.open('rb') as src, partial.open('xb') as dst:
        while data := src.read(8 * 1024 * 1024):
            source_hash.update(data); new = apply_disc_changes(data, position, changes)
            dst.write(new); output_hash.update(new); position += len(data)
    assert position == original_meta['size_bytes'] and source_hash.hexdigest() == original_hash
    print('Re-reading entire output and proving all other bytes unchanged...', flush=True)
    checked_hash = hashlib.sha256(); rechecked_source = hashlib.sha256(); different = position = 0
    with source.open('rb') as src, partial.open('rb') as dst:
        while before := src.read(8 * 1024 * 1024):
            after = dst.read(len(before)); assert len(after) == len(before)
            assert after == apply_disc_changes(before, position, changes), 'Unexpected difference outside manifest or wrong injected byte'
            rechecked_source.update(before); checked_hash.update(after)
            different += int(np.count_nonzero(np.frombuffer(before, dtype=np.uint8) != np.frombuffer(after, dtype=np.uint8)))
            position += len(before)
        assert dst.read(1) == b''
        dst.seek(0x420); reread_offset = struct.unpack('>I', dst.read(4))[0]; assert reread_offset == disc_offset
        dst.seek(reread_offset); reread_dol = dst.read(len(dol)); assert reread_dol == dol
        # FST and every file are outside the changed intervals and proved above.
    assert rechecked_source.hexdigest() == original_hash
    assert checked_hash.hexdigest() == output_hash.hexdigest()
    verify_loaded_dol(reread_dol, plan, glyphs)
    partial.rename(OUTPUT)
    save(REPORT, {'build': NAME, 'edition': 'GGTJ01 revision 1', 'font': 'Gmarket Sans Bold',
        'font_sha256': probe.sha(probe.FONT.read_bytes()), 'size_bytes': OUTPUT.stat().st_size,
        'original_sha256_before_and_after': original_hash, 'output_sha256': checked_hash.hexdigest(),
        'dol_sha256': probe.sha(dol), 'dol_patches': dol_changes,
        'disc_change_ranges': manifest, 'different_bytes': different, 'unexpected_difference_bytes': 0,
        'all_original_fst_files_unchanged': len(inv['files']), 'original_fst_and_dol_bytes_preserved': True,
        'output_reread_full_bytes': position, 'loaded_dol_CPU_checks': cpu,
        'runtime': 'Not launched in Dolphin. User must confirm actual output.',
        'scope': 'Two menu strings, seven Hangul glyphs only; not a full translation.'})
    print(f'PASS: {different:,} changed bytes, no unexpected differences, {len(inv["files"])} original FST files unchanged.', flush=True)
    print(OUTPUT)
    print('SHA256', checked_hash.hexdigest())


if __name__ == '__main__': main()
