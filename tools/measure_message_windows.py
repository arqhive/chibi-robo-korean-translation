"""Read-only JP message layout evidence and Dolphin-reference glyph metrics.

No build/injection. Values are logical game coordinates, not screenshot pixels.
"""
import json
import struct
from collections import Counter
from pathlib import Path
from unicorn import UC_HOOK_CODE
import prepare_output_probe as p
from inspect_discs import ROOT, save

R2 = 0x8063e160
MSG = 0x81880000


def f32(value): return struct.unpack('>f', struct.pack('>f', value))[0]
def fpr_write(u, number, value): u.reg_write(getattr(p.reg, f'UC_PPC_REG_FPR{number}'), int.from_bytes(struct.pack('>d', value), 'big'))
def fpr_read(u, number): return struct.unpack('>d', u.reg_read(getattr(p.reg, f'UC_PPC_REG_FPR{number}')).to_bytes(8, 'big'))[0]


def advance(width, size, layout, double_byte):
    if size <= 0: return float(width)
    if layout == 0: return size if double_byte else size * 0.5
    return f32(f32(width * size) / 24.0)


def main():
    dol = p.DOL.read_bytes(); inv = json.loads(p.INV.read_text())
    assert p.sha(dol) == inv['dol']['sha256']
    romfont = p.yay0(p.ROMFONT.read_bytes())
    rows = json.loads((ROOT / 'work/analysis/jp/message_candidates.json').read_text(encoding='utf-8'))
    def read(address, size):
        s = next(s for s in inv['dol']['sections'] if s['ram_address'] <= address < s['ram_address'] + s['size'])
        off = address - s['ram_address'] + s['file_offset']; return dol[off:off + size]
    def constant(offset): return struct.unpack('>f', read(R2 + offset, 4))[0]
    constants = {'default_size': constant(-0x6e2c), 'glyph_cell': constant(-0x4870),
                 'box_x_min': constant(-0x6e04), 'box_x_max': constant(-0x6e00),
                 'box_y_min': constant(-0x6dfc), 'box_y_max': constant(-0x6df8)}
    assert constants == {'default_size': 22., 'glyph_cell': 24., 'box_x_min': 16., 'box_x_max': 624., 'box_y_min': 34., 'box_y_max': 414.}
    # Obtain widths from the original SDK parser/glyph path, not Unicode character count.
    u = p.create_cpu(dol, inv, romfont)
    chars = sorted(set(''.join(t['source'] for row in rows for t in row['tokens'] if t['kind'] == 'text')) | set(chr(i) for i in range(32, 127)))
    widths = {}; failed = {}
    for char in chars:
        try:
            encoded = char.encode('cp932'); _, width, consumed = p.texel(u, p.GET_TEXEL, encoded)
            assert consumed == len(encoded)
            widths[char] = {'raw_advance_px': width, 'bytes': encoded.hex(), 'double_byte': len(encoded) == 2}
        except (UnicodeError, AssertionError) as error:
            failed[char] = type(error).__name__
    probe_plan = json.loads((ROOT / 'translation/output_probe.json').read_text(encoding='utf-8'))
    for entry in probe_plan['mapping']:
        widths[entry['hangul']] = {'raw_advance_px': p.ADVANCE, 'bytes': entry['sjis_code'][2:], 'double_byte': True, 'source': 'built v01 seven-glyph mapping only'}
    save(ROOT / 'metadata/glyph_metrics.json', {'environment': 'installed Dolphin replacement ROM font + v01 seven Hangul glyphs',
        'reference_rom_font_sha256': p.sha(p.ROMFONT.read_bytes()), 'metrics': widths, 'unmeasured': failed,
        'limits': 'Does not approve all Hangul or hardware IPL metrics; font changes require remeasurement.'})
    # Execute the actual scalar advance block, with real SDA constants.
    u.reg_write(p.reg.UC_PPC_REG_MSR, 0x2000); u.reg_write(p.regnum(2), R2)
    cases = []
    for size in (0., 16., 22., 32.):
        for mode in (0, 1):
            for char in ('A', ' ', 'は', '처'):
                item = widths[char]; raw = bytes.fromhex(item['bytes'])
                u.reg_write(p.regnum(1), p.STACK); u.reg_write(p.regnum(31), mode); fpr_write(u, 31, size)
                u.mem_write(p.STACK + 8, struct.pack('>I', item['raw_advance_px']))
                u.mem_write(p.STACK + 12, struct.pack('>f', 0)); u.mem_write(p.STACK + 20, raw + b'\0')
                u.emu_start(0x8019858c, 0x80198674, count=150)
                assert u.reg_read(p.reg.UC_PPC_REG_PC) == 0x80198674
                actual = struct.unpack('>f', bytes(u.mem_read(p.STACK + 12, 4)))[0]
                expected = advance(item['raw_advance_px'], size, mode, item['double_byte'])
                assert abs(actual - expected) < 0.00002
                cases.append({'char': char, 'size': size, 'layout': mode, 'advance_px': actual})
    # Run the original line prepass; only rendering-width helper and Gekko paired
    # register spills are substituted. Width arithmetic was verified above.
    u = p.create_cpu(dol, inv, romfont)
    u.reg_write(p.reg.UC_PPC_REG_MSR, 0x2000); u.reg_write(p.regnum(2), R2)
    width_calls = []
    def trace(cpu, pc, size, data):
        if pc in (0x80088434, 0x80088958):
            cpu.reg_write(p.reg.UC_PPC_REG_PC, pc + 4)
        if pc == 0x801984fc:
            ptr = cpu.reg_read(p.regnum(4)); raw = bytes(cpu.mem_read(ptr, 3)); lead = raw[0]
            n = 2 if 0x81 <= lead <= 0x9f or 0xe0 <= lead <= 0xfc else 1
            char = raw[:n].decode('cp932'); item = widths[char]
            value = advance(item['raw_advance_px'], fpr_read(cpu, 1), cpu.reg_read(p.regnum(5)), n == 2)
            width_calls.append(value); fpr_write(cpu, 1, value)
            cpu.reg_write(p.reg.UC_PPC_REG_PC, cpu.reg_read(p.reg.UC_PPC_REG_LR))
    u.hook_add(UC_HOOK_CODE, trace)
    samples = [
        ('default_two_glyphs', 'はじ'.encode('cp932'), [40 * 22 / 24], [22.]),
        ('two_lines', 'は\nじ'.encode('cp932'), [20 * 22 / 24] * 2, [22.] * 2),
        ('vertical_tab', 'は\vじ'.encode('cp932'), [20 * 22 / 24] * 2, [22.] * 2),
        ('monospace', b'\x10\x00' + 'はA'.encode('cp932'), [33.], [22.]),
        ('size_reset', b'\x0d\x20' + 'は'.encode('cp932') + b'\x0a\x0d\xff' + 'じ'.encode('cp932'), [20 * 32 / 24, 20 * 22 / 24], [32., 32.]),
        ('ten_lines', ('は\n' * 9 + 'じ').encode('cp932'), [20 * 22 / 24] * 10, [22.] * 10),
    ]
    prepass = []
    for name, raw, expected_widths, expected_heights in samples:
        u.mem_write(MSG, bytes(4096)); u.mem_write(MSG, raw + b'\0')
        u.reg_write(p.regnum(1), p.STACK); u.reg_write(p.regnum(3), MSG); u.reg_write(p.reg.UC_PPC_REG_LR, p.STOP)
        u.emu_start(0x80088424, p.STOP, count=100000)
        assert u.reg_read(p.reg.UC_PPC_REG_PC) == p.STOP
        n = int.from_bytes(u.mem_read(MSG + 0x804, 4), 'big'); assert n == len(expected_widths)
        ws = list(struct.unpack('>' + 'f' * n, bytes(u.mem_read(MSG + 0x830, 4 * n))))
        hs = list(struct.unpack('>' + 'f' * n, bytes(u.mem_read(MSG + 0x858, 4 * n))))
        assert all(abs(a - b) < 0.0001 for a, b in zip(ws, expected_widths)), (name, ws)
        assert hs == expected_heights, (name, hs)
        prepass.append({'case': name, 'line_widths': ws, 'line_heights': hs,
                        'max_width_max_height_total_height': list(struct.unpack('>3f', bytes(u.mem_read(MSG + 0x880, 12))))})
    save(ROOT / 'metadata/message_layout_evidence.json', {'edition': 'GGTJ01 revision1', 'dol_sha256': p.sha(dol),
        'constants': constants, 'advance_CPU_cases': cases, 'line_prepass_CPU_cases': prepass,
        'code_hashes': [{'start': hex(a), 'size': n, 'sha256': p.sha(read(a, n))} for a, n in [(0x801984fc, 0x290), (0x80088424, 0x550), (0x80087ae0, 0x944), (0x80084cb8, 0x88)]],
        'line_table': {'count_offset': '0x804', 'char_counts': '0x808', 'widths': '0x830', 'heights': '0x858', 'slots': 10, 'note': 'Structural capacity, NOT an on-screen ten-line allowance.'},
        'dynamic_box': {'width_loaded_from': 'CMsgData+0x880 at0x80087e10', 'height_loaded_from': 'CMsgData+0x888 at0x80087e14', 'position_clamp': '0x80084cb8..0x80084d40', 'note': 'Position shifts to limits; this block does not wrap, clamp width, or shrink text.'},
        'limits': ['CMsgFont/window instances have not all been linked to script records.', 'CPU prepass skips two paired-single register spills and substitutes glyph-width helper; not actual GX/gameplay.', 'Scale/rotation/shake visual extents, icons, format substitutions and special UI remain unresolved.']})
    print(f'PASS: {len(widths)} glyph metrics, {len(cases)} advance cases, {len(prepass)} line prepass cases. No ROM build.')


if __name__ == '__main__': main()
