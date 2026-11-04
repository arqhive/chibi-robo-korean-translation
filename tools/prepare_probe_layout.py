"""Derive and CPU-check a candidate JP Rev1 payload layout, without building.

All writes are to Unicorn RAM or JSON. No original, DOL or ISO is written.
"""
import json
import struct
from capstone import Cs, CS_ARCH_PPC, CS_MODE_32, CS_MODE_BIG_ENDIAN
import prepare_output_probe as probe
from inspect_discs import ROOT, save

BASE = 0x8064c5c0
RESERVED_END = BASE + 0x1000
ARENA_HOOK = BASE + 0x100
BITMAPS = BASE + 0x200
SET_ARENA_LO = 0x8016486c
REAL_R13 = 0x8063c2e0


def arena_stub():
    p = probe.PPC(ARENA_HOOK)
    p.load(11, RESERVED_END)
    p.emit(0x7c035840)  # cmplw r3,r11
    p.bc(0x40800000, 'original')  # bge
    p.d(36, 11, 13, -0x72f0); p.emit(0x4e800020)
    p.label('original'); p.d(36, 3, 13, -0x72f0); p.emit(0x4e800020)
    return p.finish()


def main():
    dol = probe.DOL.read_bytes(); inv = json.loads(probe.INV.read_text())
    assert probe.sha(dol) == inv['dol']['sha256']
    def at(address, length):
        s = next(s for s in inv['dol']['sections'] if s['ram_address'] <= address < s['ram_address'] + s['size'])
        off = address - s['ram_address'] + s['file_offset']
        return dol[off:off + length]
    # Derive register/startup constants from instructions, do not borrow addresses.
    def load_address(pc):
        a, b = struct.unpack('>II', at(pc, 8))
        assert a >> 26 == 15 and b >> 26 in (14, 24)
        high, low = (a & 0xffff) << 16, b & 0xffff
        return (high + (low - 0x10000 if b >> 26 == 14 and low & 0x8000 else low)) & 0xffffffff
    assert load_address(0x801631c0) == BASE
    assert load_address(0x80005420) == REAL_R13
    stack = load_address(0x80005410); assert stack == 0x8064a5b0
    bss, bss_size = struct.unpack_from('>II', dol, 0xd8)
    assert bss + bss_size == 0x8063a5b0 < stack < BASE
    for s in inv['dol']['sections']:
        assert s['ram_address'] + s['size'] <= BASE or s['ram_address'] >= RESERVED_END
    # Runtime __init_data has its own BSS zero table; check all entries too.
    bss_ranges = []
    for off in range(0, 128, 8):
        start, size = struct.unpack('>II', at(0x800055c8 + off, 8))
        if size == 0: break
        assert start + size <= BASE or start >= RESERVED_END
        bss_ranges.append({'start': hex(start), 'size': size})
    else: raise AssertionError('No startup BSS terminator')
    assert at(SET_ARENA_LO, 8).hex() == '906d8d104e800020'
    plan = json.loads((ROOT / 'translation/output_probe.json').read_text(encoding='utf-8'))
    codes = [int(x['sjis_code'], 16) for x in plan['mapping']]
    font_stub = probe.make_stub(codes, BASE, BITMAPS)
    assert len(font_stub) <= 0x100
    clamp = arena_stub(); assert len(clamp) <= 0x100
    assert BITMAPS + 288 * len(codes) <= RESERVED_END
    u = probe.create_cpu(dol, inv, probe.yay0(probe.ROMFONT.read_bytes()))
    u.mem_write(BASE, font_stub); u.mem_write(ARENA_HOOK, clamp)
    u.reg_write(probe.regnum(13), REAL_R13)
    patch = probe.PPC(SET_ARENA_LO); patch.branch(ARENA_HOOK)
    u.mem_write(SET_ARENA_LO, patch.finish())
    arena_cases = []
    for value in [0x8064a5c0, BASE, BASE + 32, RESERVED_END, RESERVED_END + 32, 0x81000000]:
        u.reg_write(probe.regnum(3), value); u.reg_write(probe.reg.UC_PPC_REG_LR, probe.STOP)
        u.emu_start(SET_ARENA_LO, probe.STOP, count=100)
        assert u.reg_read(probe.reg.UC_PPC_REG_PC) == probe.STOP
        result = int.from_bytes(u.mem_read(REAL_R13 - 0x72f0, 4), 'big')
        assert result == max(value, RESERVED_END) and u.reg_read(probe.regnum(3)) == value
        arena_cases.append({'requested': hex(value), 'reserved_result': hex(result)})
    # Rebased font hook at proposed real RAM layout (still isolated CPU only).
    u.reg_write(probe.regnum(13), probe.R13)
    for i, code in enumerate(codes):
        pattern = bytes([0x11 * (i + 1)]) * 288
        u.mem_write(BITMAPS + i * 288, pattern)
        result, width, consumed = probe.texel(u, BASE, code.to_bytes(2, 'big'))
        assert result[:288] == pattern and width == probe.ADVANCE and consumed == 2
    # Statically enumerate stores into ArenaLo; setters clamped, allocator advances it.
    stores = []
    cs = Cs(CS_ARCH_PPC, CS_MODE_32 | CS_MODE_BIG_ENDIAN); cs.skipdata = True
    for s in inv['dol']['sections']:
        if s['kind'] != 'text': continue
        for ins in cs.disasm(dol[s['file_offset']:s['file_offset'] + s['size']], s['ram_address']):
            if ins.mnemonic == 'stw' and ins.op_str.endswith('-0x72f0(r13)'): stores.append(ins.address)
    assert stores == [SET_ARENA_LO, 0x80164894]
    # There is no spare DOL data slot, but text slot2 is unused. Existing DOL ends
    # exactly at the FST, so extending it in-place would overwrite the FST.
    assert all(struct.unpack_from('>I', dol, off)[0] == 0 for off in (8, 0x50, 0x98))
    assert inv['dol']['offset'] + len(dol) == inv['fst_offset']
    disc_address = (inv['fst_offset'] + inv['fst_size'] + 31) & ~31
    extended_size = ((len(dol) + 31) & ~31) + (RESERVED_END - BASE)
    first_file = min(f['offset'] for f in inv['files'])
    assert disc_address + extended_size < first_file
    save(ROOT / 'metadata/output_probe_layout.json', {
        'status': 'candidate_layout_checked_in_isolated_CPU_not_booted_or_built',
        'payload_start': hex(BASE), 'payload_end_exclusive': hex(RESERVED_END), 'reserved_bytes': 4096,
        'font_hook': hex(BASE), 'arena_hook': hex(ARENA_HOOK), 'bitmaps': hex(BITMAPS),
        'font_hook_size': len(font_stub), 'arena_hook_size': len(clamp),
        'source_evidence': {'default_arena_load': '0x801631c0', 'initial_stack': hex(stack),
                            'startup_r13': hex(REAL_R13), 'dol_bss_end': hex(bss + bss_size),
                            'runtime_bss_clear_ranges': bss_ranges},
        'arena_setter': hex(SET_ARENA_LO), 'arena_cases': arena_cases,
        'arena_stores_found': [hex(a) for a in stores],
        'remaining_store': '0x80164894 is OSAllocFromArenaLo, aligns and advances the already-clamped value; not independently clamped.',
        'rebased_font_checks': 7,
        'disc_plan': {'unused_dol_text_slot': 2, 'new_disc_dol_offset': hex(disc_address),
                      'new_dol_size_with_reserved_payload': extended_size, 'first_original_fst_file': hex(first_file),
                      'method': 'Relocate extended DOL into non-file gap after FST; change disc header DOL pointer only. Keep original DOL, FST and every file at original offsets. Payload added via unused text section 2.',
                      'gap_caveat': 'Layout gap is not necessarily zero; new bytes need an explicit changed-range manifest when building.'},
        'limits': ['No disc serialized or booted; apploader acceptance and startup survival unverified.',
                   'Static ArenaLo store scan cannot prove absence of indirect writes.',
                   'OS debug/reboot paths and real cache synchronization untested.',
                   'Payload intentionally limited to this seven-glyph probe; do not scale unchanged to full translation.']})
    print('PASS: candidate 4KiB reservation, six ArenaLo boundary cases, seven rebased glyphs; no DOL/ISO written.')


if __name__ == '__main__': main()
