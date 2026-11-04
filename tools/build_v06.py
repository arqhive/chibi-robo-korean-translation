"""v06+: v05 plus the v06 supplement (text_additions_v06.json) and comma/period glyphs.

Scripts and metadata are rebuilt from the original JP files exactly as v02
did, after first proving that the v02 selection reproduces the v05 files
byte for byte. Graphics, banner and every other QP member come from v05.
Never overwrite originals or an existing output.

Usage: python -X utf8 tools/build_v06.py [VERSION]   (default 6)
"""
import copy
import json
import shutil
import struct
import sys
from collections import defaultdict
from pathlib import Path

import prepare_output_probe as p
import prepare_v03_corrections as v
import prepare_v06_punctuation as punct
import build_integrated_test as b
from inspect_discs import ROOT, save
from verify_integrated_layout import read
from build_output_probe import sections
from verify_message_relocation import encode_text, verify_record
from translation_tokens import translated_tokens
from verify_relocation_cpu import verify_cpu
from verify_qp_repacking import parse, repack, verify
from verify_roundtrip import model_table

VERSION = int(sys.argv[1]) if len(sys.argv) > 1 else 6
if VERSION >= 12:
    import prepare_v11_glyphs as punct          # digits/letters/symbols in Gmarket (Wii set)
NAME = f'ChibiRobo_KO_Test_v{VERSION:02d}_GmarketBold.iso'
REPORT = f'metadata/integrated_test_build_v{VERSION:02d}.json'
POST_V05_GRAPHICS = [('G0199', 'tpl/misc.tpl#tpl-141')]
OUTPUT = ROOT / 'build' / NAME
V05 = read('metadata/integrated_test_build_v05.json')
STR_ALIGN = 0x20
DESKTOP = Path.home() / 'Desktop' / NAME
SD = Path('D:/games/Chibi-Robo [GGTJ01]/game.iso')
MOVIE = 'qp/movie/karaoke_teriyaki.thp'   # v30+: Korean karaoke lyrics (tools/karaoke_render.py, karaoke_thp.py)


def messages(rows, selected, mapping):
    """build_integrated_test.messages without the fixed v02 record count."""
    inverse = {v: k for k, v in mapping.items()}; groups = defaultdict(list)
    for row in rows:
        if row['id'] in selected: groups[row['file']].append(copy.deepcopy(row))
    blobs = {}; details = []
    for name, records in sorted(groups.items()):
        original = (ROOT / 'work/roundtrip/jp/qp/files' / name).read_bytes()
        base = struct.unpack_from('<I', original, 16)[0] + 24 if name == 'bin/globals.bin' else 0
        blob = bytearray(original); patches = []; previous_end = -1
        for r in sorted(records, key=lambda x: x['opcode_offset']):
            at = r['opcode_offset']; assert previous_end <= at; previous_end = r['end']
            assert original[at] == r['opcode'] and r['offset'] == at + 5
            assert base + struct.unpack_from('<I', original, at + 1)[0] == r['end']
            assert original[at + 5:r['end']] == b''.join(bytes.fromhex(t['hex']) for t in r['tokens'])
            raw = b.body(r, mapping); start = len(blob); end = start + 5 + len(raw)
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
        held = [r for r in rows if r['file'] == name and r['kind'] == 'script_message_candidate' and r['id'] not in selected]
        for r in held: assert blob[r['opcode_offset']:r['end']] == original[r['opcode_offset']:r['end']]
        blobs[name] = bytes(blob)
    assert {x['id'] for x in details} == selected
    return blobs, details


def metadata(blobs, rows, selected, mapping):
    """build_integrated_test.metadata layout, generalized count, no CPU getters."""
    name = 'bin/globals.bin'; original = (ROOT / 'work/roundtrip/jp/qp/files' / name).read_bytes()
    previous = blobs[name]; header = struct.unpack_from('<6I', original); base = 24 + header[0]
    meta = bytearray(original[base:base + header[1]]); expected = {}; pointers = []
    all_rows = [r for r in rows if r['kind'] == 'metadata_string']
    for r in all_rows:
        at = r['pointer_offset'] - base; old = struct.unpack_from('<I', meta, at)[0]
        assert base + old == r['offset']
        assert original[r['offset']:r['end']] == b''.join(bytes.fromhex(t['hex']) for t in r['tokens'])
        if r['id'] in selected:
            raw = b.body(r, mapping); new = len(meta); meta.extend(raw)
            struct.pack_into('<I', meta, at, new); pointers.append((at, old)); expected[r['id']] = (new, raw)
        else: expected[r['id']] = (old, original[r['offset']:r['end']])
    restored = bytearray(meta[:header[1]])
    for at, old in pointers: struct.pack_into('<I', restored, at, old)
    assert restored == original[base:base + header[1]] and len(pointers) == len(selected)
    start = (len(previous) + 31) & ~31
    blob = bytearray(previous); blob.extend(bytes(start - len(blob))); blob.extend(meta)
    struct.pack_into('<II', blob, 0, start - 24, len(meta))
    for r in all_rows:
        at = struct.unpack_from('<I', meta, r['pointer_offset'] - base)[0]; want, raw = expected[r['id']]
        assert at == want and meta[at:at + len(raw)] == raw
    blobs[name] = bytes(blob)
    return expected, start


def metadata_cpu(dol, blob, start, expected, rows):
    # Real JP partition header and known getters, as v02 did.
    u = p.create_cpu(dol, {'dol': {'sections': sections(dol)}}, p.yay0(p.ROMFONT.read_bytes()))
    ram = 0x81000000; registry = 0x80345b78
    u.mem_write(ram, bytes(blob)); u.mem_write(registry + 0xcc, struct.pack('>I', ram))
    u.emu_start(0x80071080, 0x80071130, count=200)
    assert u.reg_read(p.reg.UC_PPC_REG_PC) == 0x80071130
    getters = read('metadata/metadata_relocation_verification.json')['getters']; tested = 0
    for r in rows:
        if r['kind'] != 'metadata_string': continue
        kind, index, field = r['label'].split('.'); pc = getters.get(kind + '.' + field)
        if not pc: continue
        u.reg_write(p.regnum(3), int(index)); u.reg_write(p.reg.UC_PPC_REG_LR, p.STOP)
        u.emu_start(int(pc, 16), p.STOP, count=300)
        want, raw = expected[r['id']]; ptr = u.reg_read(p.regnum(3))
        assert ptr == ram + start + want and bytes(u.mem_read(ptr, len(raw))) == raw; tested += 1
    return tested


def dol_strings(dol, records, mapping):
    """Append overridden/new DOL UI strings after the v06 glyph payload; repoint slots."""
    dol = bytearray(dol); base = punct.BASE + punct.SIZE
    uiv = read('metadata/ui_relocation_verification.json')
    ui = {s['id']: s for s in uiv['strings']}; uipatches = uiv['patches']
    catalog = {r['id']: r for r in read('translation/text_catalog.json')}
    payload = bytearray(); patches = []; strings = []
    for r in records:
        if r['file'] != 'main.dol': continue
        payload.extend(bytes((-len(payload)) % 4)); address = base + len(payload)
        tokens = [{'kind': 'text', 'source': r['source']}, {'kind': 'end', 'hex': '00'}]
        row = {'id': r['id'], 'kind': 'dol_rodata_string_candidate', 'tokens': tokens, 'translation': r['translation']}
        raw = b''.join(encode_text(t['source'], mapping) if t['kind'] == 'text' else bytes.fromhex(t['hex'])
                       for t in translated_tokens(row))
        payload.extend(raw)
        if r.get('slots'):
            # New string for selected pointer slots only (other slots keep the old string).
            oldraw = encode_text(r['translation_before'], mapping) + b'\0'
            slots = list(r['slots'])
            old = int.from_bytes(dol[slots[0]:slots[0] + 4], 'big')
            off = v.offset(dol, old); assert bytes(dol[off:off + len(oldraw)]) == oldraw, r['id']
        elif r['id'] in ui:
            # Override of a v02 UI string: every slot that points at the old Korean string.
            old = ui[r['id']]['address']; oldrow = catalog[r['id']]
            oldraw = b''.join(encode_text(t['source'], mapping) if t['kind'] == 'text' else bytes.fromhex(t['hex'])
                              for t in translated_tokens(oldrow))
            off = v.offset(dol, old); assert bytes(dol[off:off + len(oldraw)]) == oldraw
            slots = [x['file_offset'] for x in uipatches if x['id'] == r['id']]
            assert slots and all(x['new'] == old for x in uipatches if x['id'] == r['id']), r['id']
        else:
            old = int.from_bytes(dol[r['references'][0]['file_offset']:r['references'][0]['file_offset'] + 4], 'big')
            sec = next(s for s in sections(dol) if s['file_offset'] <= r['offset'] < s['file_offset'] + s['size'])
            assert old == sec['ram_address'] + r['offset'] - sec['file_offset']
            assert dol[r['offset']:r['offset'] + len(bytes.fromhex(r['original_hex']))] == bytes.fromhex(r['original_hex'])
            slots = [x['file_offset'] for x in r['references']]
        for s in slots:
            assert int.from_bytes(dol[s:s + 4], 'big') == old
            patches.append({'offset': s, 'before': dol[s:s + 4].hex(), 'after': v.word(address).hex(), 'reason': r['id']})
            dol[s:s + 4] = v.word(address)
        strings.append({'id': r['id'], 'address': hex(address), 'slots': [hex(s) for s in slots], 'bytes': len(raw), 'raw': raw})
    size = (len(payload) + STR_ALIGN - 1) & ~(STR_ALIGN - 1); payload.extend(bytes(size - len(payload)))
    memory = read('metadata/injection_memory_verification.json'); ah = memory['arena_hook']
    o = p.PPC(ah); o.load(11, base); n = p.PPC(ah); n.load(11, base + size)
    off = v.offset(dol, ah); assert bytes(dol[off:off + 8]) == o.finish(); dol[off:off + 8] = n.finish()
    sec = int.from_bytes(dol[0x98:0x9c], 'big'); assert int.from_bytes(dol[0x50:0x54], 'big') + sec == base
    assert int.from_bytes(dol[8:12], 'big') + sec == len(dol)
    dol[0x98:0x9c] = v.word(sec + size); dol.extend(payload)
    # RAM readback through the real section table, plus ArenaLo clamp cases.
    u = v.cpu(bytes(dol))
    for s in strings:
        for slot in s['slots']:
            ptr = None
            for sec_ in sections(bytes(dol)):
                if sec_['file_offset'] <= int(slot, 16) < sec_['file_offset'] + sec_['size']:
                    ptr = int.from_bytes(u.mem_read(sec_['ram_address'] + int(slot, 16) - sec_['file_offset'], 4), 'big')
            assert ptr == int(s['address'], 16) and bytes(u.mem_read(ptr, s['bytes'])) == s['raw']
    end = base + size
    for requested in [base - 32, base, end - 32, end, end + 32, 0x81000000]:
        u.reg_write(p.regnum(3), requested); v.call(u, ah)
        assert int.from_bytes(u.mem_read(p.R13 - 0x72f0, 4), 'big') == max(requested, end)
    for s in strings: s.pop('raw')
    return bytes(dol), strings, patches, end


AUTH = {6: '2026-11-03 사용자: 커밋하고 바탕화면 빌드해줘',
        7: '2026-11-03 사용자: 고치고 빌드 (치비컴 전광판 19줄 전각, 치비컴 4줄)',
        8: '2026-11-03 사용자: 빌드해 (조사 줄별 판단·치비컴 로고·예아니요 가운데 정렬)',
        9: '2026-11-03 사용자: 빌드해 (Wii 플레이 검수 대사 26줄)',
        10: '2026-11-03 사용자: 넣고 빌드 (저장·구입 창 예아니요 배치, 아이템 설명 마침표 58줄)',
        11: '2026-11-03 사용자: 1번으로 하자 (지역 이름 띄어쓰기 뺌, 저장 창 빈 글자 폭 조정)',
        12: '2026-11-03 사용자: 빌드해 (숫자·기호 G마켓, 지역 이름 위치 함수·띄어쓰기 복원)',
        13: '2026-11-03 사용자: 고쳐지지 않았어 엄한곳을 수정했나벼 (지역 이름 위치를 그리기 루틴에서)',
        14: '2026-11-03 사용자: 안 고쳐짐 + 전체 스크린샷(이어서 화면 세이브 카드 지역 이름)',
        15: '2026-11-03 사용자: 빼고 빌드 (v13 로딩 화면 0x8000b0b0 수정 제거)',
        16: '2026-11-03 사용자: 빌드해 (저장 창 예·아니요 빈 칸 12·30+16)',
        17: '2026-11-03 사용자: 빌드해 (생일파티, 구매 화면 예·아니요 앞 빈 칸 10)',
        18: '2026-11-03 사용자: 커빌 (실기 대사 수정 14줄)'}


def ticker_pairing(dol):
    """Walk every ChibiCom ticker string like 0x800466a0..0x80046970.

    Tab (0x09, rank number) and 0x07 (0x80046754) consume one byte; everything else is read as a
    halfword and advances two. The walk must land exactly on the terminator.
    """
    u = v.cpu(dol); table = 0x802163c4; results = []
    for i in range(0x18):
        ptr = int.from_bytes(u.mem_read(table + i * 4, 4), 'big')
        if not ptr: continue
        raw = bytes(u.mem_read(ptr, 1024)); pos = 0; cells = 0
        while raw[pos] != 0:
            if raw[pos] in (7, 9): pos += 1; continue
            hi = raw[pos]; assert hi >= 0x81 and raw[pos + 1] != 0, (hex(ptr), pos, raw[pos:pos + 2])
            pos += 2; cells += 1
        results.append({'index': i, 'address': hex(ptr), 'bytes': pos, 'cells': cells})
    return results


CENTER_SIZE = 0x200


def centering(dol, base):
    """v08: actual-width centering wrapper for 26 fixed-cell printf callers."""
    import prepare_v08_centering as c8
    dol = bytearray(dol)
    sec = int.from_bytes(dol[0x98:0x9c], 'big'); assert int.from_bytes(dol[0x50:0x54], 'big') + sec == base
    assert int.from_bytes(dol[8:12], 'big') + sec == len(dol)
    new, payload, patches, sites, mapping, metrics = c8.prepare_and_verify(bytes(dol), base, CENTER_SIZE)
    new = bytearray(new)
    memory = read('metadata/injection_memory_verification.json'); ah = memory['arena_hook']
    o = p.PPC(ah); o.load(11, base); n = p.PPC(ah); n.load(11, base + CENTER_SIZE)
    off = v.offset(new, ah); assert bytes(new[off:off + 8]) == o.finish(); new[off:off + 8] = n.finish()
    new[0x98:0x9c] = v.word(sec + CENTER_SIZE); new.extend(payload); new = bytes(new)
    cases = c8.verify(new, base, mapping, metrics)
    u = v.cpu(new); end = base + CENTER_SIZE
    for requested in [base - 32, base, end - 32, end, end + 32, 0x81000000]:
        u.reg_write(p.regnum(3), requested); v.call(u, ah)
        assert int.from_bytes(u.mem_read(p.R13 - 0x72f0, 4), 'big') == max(requested, end)
    return new, {'sites': sites, 'patches': patches, 'cpu_cases': len(cases), 'wrapper': hex(base),
                 'examples': [c for c in cases if c['cell'] == 24.0]}, end


def stagename(dol, base):
    """Area-name centre x by real widths (v13: drawing routine 0x8000b0b0)."""
    import prepare_v11_stagename as sn
    dol = bytearray(dol)
    sec = int.from_bytes(dol[0x98:0x9c], 'big'); assert int.from_bytes(dol[0x50:0x54], 'big') + sec == base
    assert int.from_bytes(dol[8:12], 'big') + sec == len(dol)
    if VERSION >= 15:   # only the save-file card; the v13 loading-title change was a misread target
        new, payload, patches = sn.apply_card(bytes(dol), base)
    else:
        new, payload, patches = sn.apply(bytes(dol), base)
        if VERSION >= 14:   # save-file card (「이어서」 screen), confirmed by the user's full screenshot
            new, card, cpatches = sn.apply_card(bytes(new), base + sn.SIZE)
            payload = payload + card; patches = patches + cpatches
    memory = read('metadata/injection_memory_verification.json'); ah = memory['arena_hook']
    size = len(payload)
    o = p.PPC(ah); o.load(11, base); n = p.PPC(ah); n.load(11, base + size)
    off = v.offset(new, ah); assert bytes(new[off:off + 8]) == o.finish(); new[off:off + 8] = n.finish()
    new[0x98:0x9c] = v.word(sec + size); new.extend(payload); new = bytes(new)
    mapping = {m['character']: m['code'] for m in read('translation/full_font_plan.json')['mapping']}
    if VERSION >= 15:
        cases = {'save_card': sn.verify_card(new, base, mapping)}
    else:
        cases = sn.verify(new, base, mapping)
        if VERSION >= 14: cases = {'loading_title': cases, 'save_card': sn.verify_card(new, base + sn.SIZE, mapping)}
    u = v.cpu(new); end = base + size
    for requested in [base - 32, base, end - 32, end, end + 32, 0x81000000]:
        u.reg_write(p.regnum(3), requested); v.call(u, ah)
        assert int.from_bytes(u.mem_read(p.R13 - 0x72f0, 4), 'big') == max(requested, end)
    return new, {'patches': patches, 'wrapper': hex(base), 'cases': cases}, end


def v05_parts():
    base = ROOT / 'work/base-v05'
    if not (ROOT / V05['iso']['path']).exists():
        # Latest-build-only retention deleted the v05 ISO; its parts were kept.
        qp = (base / 'qp.bin').read_bytes(); banner = (base / 'opening.bnr').read_bytes()
        meta = json.loads((base / 'base.json').read_text('utf-8'))
        assert p.sha(qp) == V05['qp']['sha256'] and p.sha(banner) == meta['opening.bnr']['sha256']
        return qp, banner
    with (ROOT / V05['iso']['path']).open('rb') as f:
        f.seek(0x420); doff, fst_offset, fst_size = struct.unpack('>3I', f.read(12))
        f.seek(fst_offset); table = model_table(f.read(fst_size))
        inv = read('metadata/disc_inventory_jp.json')
        q = next(x for x in inv['files'] if x['path'] == 'qp.bin'); bn = next(x for x in inv['files'] if x['path'] == 'opening.bnr')
        node = table['entries'][q['index']]; f.seek(node['a']); qp = f.read(node['b'])
        node = table['entries'][bn['index']]; f.seek(node['a']); banner = f.read(node['b'])
    assert p.sha(qp) == V05['qp']['sha256']
    return qp, banner


def copy_verified(src, dst, expected):
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + '.partial'); assert not tmp.exists()
    shutil.copyfile(src, tmp); assert p.sha(tmp.read_bytes()) == expected
    if dst.exists(): dst.unlink()
    tmp.rename(dst); return {'path': str(dst), 'sha256': expected}


def write_iso_boot_order(inv, dol, qp, banner, movie=None):
    """v28+: keep the original boot order header -> apploader -> DOL -> FST (UWUVCI showed a black
    screen when the DOL sat after the FST). The grown DOL starts at the original DOL offset, the
    FST follows it, qp.bin moves into the gap before the first file and opening.bnr stays in place.
    v30+: movie = Korean karaoke THP, written over the original one (it is smaller; only its FST size changes)."""
    import hashlib
    from verify_integrated_layout import validate_ranges
    from verify_roundtrip import encode_table
    origin = next(x for x in read('metadata/originals.json')['files'] if x['edition'] == 'jp')
    source = ROOT / origin['path']; size = origin['size_bytes']
    qentry = next(x for x in inv['files'] if x['path'] == 'qp.bin')
    bentry = next(x for x in inv['files'] if x['path'] == 'opening.bnr')
    first_file = min(x['offset'] for x in inv['files'] if x['path'] != 'qp.bin')
    dol_offset = inv['dol']['offset']
    fst_offset = (dol_offset + len(dol) + 0x1f) & ~0x1f
    qp_offset = (fst_offset + inv['fst_size'] + 0x7fff) & ~0x7fff
    assert qp_offset + len(qp) <= first_file and len(banner) == bentry['size']
    with source.open('rb') as src:
        src.seek(0x420); header = bytearray(src.read(16))
        assert struct.unpack('>3I', header[:12]) == (dol_offset, inv['fst_offset'], inv['fst_size'])
        src.seek(inv['fst_offset']); old_fst = src.read(inv['fst_size'])
    table = model_table(old_fst); node = table['entries'][qentry['index']]
    assert (node['a'], node['b']) == (qentry['offset'], qentry['size'])
    node['a'], node['b'] = qp_offset, len(qp)
    mentry = next(x for x in inv['files'] if x['path'] == MOVIE) if movie else None
    if movie:
        assert len(movie) <= mentry['size']; table['entries'][mentry['index']]['b'] = len(movie)
    fst = encode_table(table); assert len(fst) == len(old_fst)
    at = qentry['index'] * 12 + 4; restored = bytearray(fst); restored[at:at + 8] = old_fst[at:at + 8]
    if movie: mt = mentry['index'] * 12 + 8; restored[mt:mt + 4] = old_fst[mt:mt + 4]
    assert restored == old_fst
    struct.pack_into('>2I', header, 0, dol_offset, fst_offset)
    changes = [(0x420, bytes(header)), (dol_offset, dol), (fst_offset, fst), (qp_offset, qp), (bentry['offset'], banner)]
    if movie: changes.append((mentry['offset'], movie))
    validate_ranges(changes, size)
    for offset, raw in changes[1:4]:   # only boot data and the free gap before the first file
        assert offset + len(raw) <= first_file
    manifest = []
    with source.open('rb') as src:
        for offset, data in changes:
            src.seek(offset); before = src.read(len(data))
            manifest.append({'offset': offset, 'bytes': len(data), 'before_sha256': p.sha(before), 'after_sha256': p.sha(data)})
    partial = OUTPUT.with_suffix('.iso.partial')
    assert not OUTPUT.exists() and not partial.exists(), 'Refuse to overwrite existing build or partial'
    out_hash = hashlib.sha256(); position = 0
    with source.open('rb') as src, partial.open('xb') as dst:
        while raw := src.read(8 * 1024 * 1024):
            new = b.apply_disc_changes(raw, position, changes); dst.write(new); out_hash.update(new); position += len(raw)
    assert position == size
    print('ISO written to exclusive partial; rereading every byte...', flush=True)
    reread = hashlib.sha256()
    with partial.open('rb') as dst:
        while raw := dst.read(8 * 1024 * 1024): reread.update(raw)
        assert reread.hexdigest() == out_hash.hexdigest()
        dst.seek(0x420); doff, foff, fsize = struct.unpack('>3I', dst.read(12))
        assert (doff, foff, fsize) == (dol_offset, fst_offset, inv['fst_size'])
        assert doff + len(dol) <= foff   # DOL before FST, as on the original disc
        dst.seek(doff); assert dst.read(len(dol)) == dol
        dst.seek(foff); t = model_table(dst.read(fsize))
        for f in inv['files']:
            n = t['entries'][f['index']]; dst.seek(n['a']); raw = dst.read(n['b'])
            if f['path'] == 'qp.bin': assert raw == qp and len(parse(raw)) == 1155
            elif f['path'] == 'opening.bnr': assert raw == banner
            elif movie and f['path'] == MOVIE: assert n['a'] == f['offset'] and raw == movie
            else: assert (n['a'], n['b'], p.sha(raw)) == (f['offset'], f['size'], f['sha256'])
    partial.rename(OUTPUT)
    return {'path': OUTPUT.relative_to(ROOT).as_posix(), 'sha256': out_hash.hexdigest(), 'bytes': position,
            'changes': manifest, 'all_bytes_reread': True, 'fst_files_reread': len(inv['files']),
            'boot_order': 'header, apploader, DOL, FST (original order)',
            'placement': {'dol_offset': dol_offset, 'fst_offset': fst_offset, 'qp_offset': qp_offset}}


def main():
    assert not OUTPUT.exists() and not OUTPUT.with_suffix('.iso.partial').exists()
    project = read('project.json'); add = read('translation/text_additions_v06.json')
    assert p.sha((ROOT / 'translation/text_additions_v06.json').read_bytes()) == project['text_additions_v06']['sha256']
    scope = read(project['checks']['build_v02']['scope_proposal'])['record_ids_by_bucket']
    rows = read('translation/text_catalog.json')
    mapping = {r['character']: r['code'] for r in read('translation/full_font_plan.json')['mapping']}
    mapping.update({c: code for c, code, _ in punct.SPACERS})  # blank 2-byte spacers (v09+)
    v05qp, banner = v05_parts(); v05files = {f['path']: f for f in parse(v05qp)}
    member = lambda path: v05qp[v05files[path]['offset']:v05files[path]['offset'] + v05files[path]['size']]

    # 1) The v02 selection must reproduce the v05 script/metadata files exactly.
    base_scripts = set(scope['script_test_candidate']); base_meta = set(scope['metadata_test_candidate'])
    old_blobs, _ = messages(rows, base_scripts, mapping); metadata(old_blobs, rows, base_meta, mapping)
    for name, raw in old_blobs.items(): assert raw == member(name), name
    print('PASS: v02 selection reproduces all', len(old_blobs), 'v05 script files byte for byte.', flush=True)

    # 2) Apply the supplement.
    over = {r['id']: r for r in add['records']}
    rows = [dict(r, translation=over[r['id']]['translation']) if r['id'] in over else r for r in rows]
    kinds = {r['id']: r['kind'] for r in rows}
    scripts = base_scripts | {i for i in over if kinds.get(i) == 'script_message_candidate'}
    metas = base_meta | {i for i in over if kinds.get(i) == 'metadata_string'}
    dol_records = [r for r in add['records'] if r['file'] == 'main.dol']
    assert len(scripts - base_scripts) + len(metas - base_meta) + len(dol_records) + \
        sum(1 for i in over if i in base_scripts or i in base_meta) == len(over)
    blobs, details = messages(rows, scripts, mapping); expected, start = metadata(blobs, rows, metas, mapping)

    # 3) DOL: v05 + comma/period glyphs (re-verified) + DOL strings.
    pdata = punct.prepare(); pchecks = punct.verify(pdata); pdol = pdata[0]
    dol, strings, string_patches, arena_end = dol_strings(pdol, dol_records, mapping)
    center = None
    if VERSION >= 8: dol, center, arena_end = centering(dol, arena_end)
    stage = None
    if VERSION >= 12: dol, stage, arena_end = stagename(dol, arena_end)
    ticker = ticker_pairing(dol)
    cpu = verify_cpu(dol, {'dol': {'sections': sections(dol)}}, blobs, details)
    meta_cpu = metadata_cpu(dol, blobs['bin/globals.bin'], start, expected, rows)
    print('PASS: scripts', len(details), 'CPU', cpu['tested_records'], '; metadata getters', meta_cpu,
          '; DOL strings', len(strings), flush=True)

    # 4) QP: only script files that differ from v05 are replaced.
    replacements = {k: v_ for k, v_ in blobs.items() if v_ != member(k)}
    graphics = []
    if VERSION >= 8:
        # Post-v05 approved textures, applied to the v05 container bytes.
        catalog = {i['id']: i for i in read('metadata/graphics_catalog_jp.json')['images']}
        sel = {r['pixel_sha256']: r for r in project['graphics_selection']}
        import verify_graphics_encoding as gx, refine_cmpr as rc
        from PIL import Image
        for code, texture in POST_V05_GRAPHICS:
            img = catalog[texture]; c = sel[img['pixel_sha256']]['composite_review']
            assert c['code'] == code and c['texture'] == texture and c['approval']
            png = (ROOT / c['approved_path']).read_bytes(); assert p.sha(png) == c['sha256']
            name = img['file']; data = bytearray(replacements.get(name, member(name)))
            at = img['data_offset']; raw = bytes(data[at:at + img['data_size']])
            assert p.sha(raw) == img['raw_sha256'], texture
            enc, _, _ = gx.encode(raw, Image.open(ROOT / c['approved_path']), img['format'], cmpr_encoder=rc.solve)
            assert p.sha(enc) == c['encoded_sha256']
            data[at:at + len(enc)] = enc; replacements[name] = bytes(data)
            restored = bytearray(data); restored[at:at + len(raw)] = raw; assert bytes(restored) == member(name)
            graphics.append({'code': code, 'texture': texture, 'png_sha256': c['sha256'], 'encoded_sha256': p.sha(enc)})
    files = parse(v05qp); qp, layout, padding = repack(v05qp, files, replacements)
    verify(v05qp, files, replacements, qp, layout)
    inv = read('metadata/disc_inventory_jp.json')
    b.OUTPUT = OUTPUT
    movie = (ROOT / 'work/karaoke/karaoke_teriyaki_ko.thp').read_bytes() if VERSION >= 30 else None
    iso = write_iso_boot_order(inv, dol, bytes(qp), banner, movie) if VERSION >= 28 else b.write_iso(inv, dol, bytes(qp), banner)
    print('PASS: ISO', iso['sha256'], flush=True)

    desk = copy_verified(OUTPUT, DESKTOP, iso['sha256'])
    sd = copy_verified(OUTPUT, SD, iso['sha256']) if SD.parent.parent.exists() else None
    report = {'authorization': AUTH.get(VERSION, ''), 'version': VERSION, 'ticker_pairing': ticker,
        'base_v05_sha256': V05['iso']['sha256'], 'supplement_sha256': project['text_additions_v06']['sha256'],
        'iso': iso, 'desktop_copy': desk, 'sd_copy': sd,
        'dol': {'bytes': len(dol), 'sha256': p.sha(dol), 'offset': iso['placement']['dol_offset'],
                'punctuation_checks': pchecks, 'strings': strings, 'string_patches': string_patches,
                'arena_end': hex(arena_end), 'centering_v08': center, 'stagename_v11': stage},
        'v05_script_reproduction': 'byte_exact', 'text_records_added_or_overridden': len(over),
        'script_records': len(details), 'scripts_cpu': cpu, 'metadata_fields': len(metas), 'metadata_cpu_getters': meta_cpu,
        'qp': {'bytes': len(qp), 'sha256': p.sha(qp), 'changed_files': sorted(replacements), 'alignment_bytes_added': padding},
        'post_v05_graphics': graphics,
        'banner_from_v05': True, 'all_bytes_reread': iso['all_bytes_reread'],
        'new_iso_built': True, 'dolphin_runtime_verified': False, 'hardware_verified': False,
        'limits': ['CPU-only checks; GPU, heap and window fit need play testing',
                   'Graphics and banner are v05 bytes; karaoke video and held text remain original']}
    save(ROOT / REPORT, report)
    print('PASS: desktop', DESKTOP, '; SD', sd and sd['path'], flush=True)


if __name__ == '__main__':
    main()
