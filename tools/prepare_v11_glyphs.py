"""v11: Gmarket Sans for ASCII digits/letters/symbols, their fullwidth forms and
a few symbols, the same set the Wii port uses (2026-11-03 사용자: 「기호 및 숫자 Wii
처럼 G마켓 산스로」). Replaces the v06 comma/period-only payload; keeps its API
(BASE, SIZE, SPACERS, prepare, verify) so tools/build_v06.py can switch modules.

Lookup is table-driven so ~200 codes do not bloat the compare chain:
  ASCII 0x20-0x7f -> 96-word table; 2-byte 0x81xx/0x82xx/0x87xx -> 189-word tables.
Each word is bitmap_address|advance (address 32-aligned, advance < 32), 0 = miss.
Misses fall through to the v04 immutable lookup (Korean, tilde, spacers) and the
v03 texel provider. Space (0x20/0x8140), '\\' and '~' are not remapped.
Memory-only preparation and PPC verification. Never writes a DOL or ISO.
"""
import struct
from PIL import Image, ImageDraw, ImageFont
import prepare_output_probe as p
import prepare_v03_corrections as v
import prepare_v04_font_lifetime as life4
import verify_subtitle_cache_lifetime as life
import prepare_v06_punctuation as v06

BASE = v06.BASE                 # 0x806a1000, right after the v04 arena end
TEXEL, LOOKUP = BASE, BASE + 0x100
ASCII_T = BASE + 0x200          # 96 words
TABLES = {0x81: BASE + 0x380, 0x82: BASE + 0x680, 0x87: BASE + 0x980}   # 189 words each
BITMAPS = BASE + 0xC80
HOOK = life4.HOOK
DYNAMIC, PRELOAD = v06.DYNAMIC, v06.PRELOAD
SPACERS = v06.SPACERS
DIGIT_ADVANCE = 15
SYMBOLS = '…「」★☆♪①②③④⑤⑥⑦⑧⑨⑩○△□→※∞×'
ASCII = [chr(c) for c in range(0x21, 0x7f) if chr(c) not in '\\~']


def char_set():
    """[(character drawn, [codes])] with ASCII and fullwidth sharing one bitmap."""
    out = []
    for c in ASCII:
        codes = [ord(c)]
        try:
            fw = chr(ord(c) + 0xfee0).encode('cp932')
            if len(fw) == 2 and fw[0] in TABLES and 0x40 <= fw[1] <= 0xfc: codes.append(int.from_bytes(fw, 'big'))
        except UnicodeEncodeError:
            pass
        out.append((c, codes))
    for c in SYMBOLS:
        b = c.encode('cp932'); assert b[0] in TABLES, c
        out.append((c, [int.from_bytes(b, 'big')]))
    return out


def draw():
    font = ImageFont.truetype(str(p.FONT), p.FONT_SIZE); glyphs = []
    metrics = v.read('metadata/glyph_metrics.json')['metrics']
    for i, (c, codes) in enumerate(char_set()):
        natural = font.getlength(c)
        if c.isdigit():
            advance = DIGIT_ADVANCE; x0 = (DIGIT_ADVANCE - natural) / 2
        else:
            advance = round(natural) + 1; x0 = 0
        assert 0 < advance < 32, c
        canvas = Image.new('L', (72, 72))
        ImageDraw.Draw(canvas).text((24 + x0, 24 + p.BASELINE), c, font=font, fill=255, anchor='ls')
        box = canvas.getbbox(); dy = 0; dx = 0
        if box and box[3] > 48: dy = box[3] - 48          # descenders (g j p q y) kept inside the cell
        if box and box[1] - dy < 24: dy = box[1] - 24      # never above the cell
        if box and box[0] < 24: dx = 24 - box[0]           # negative left bearing (j)
        if dy or dx:
            canvas = Image.new('L', (72, 72))
            ImageDraw.Draw(canvas).text((24 + x0 + dx, 24 + p.BASELINE - dy), c, font=font, fill=255, anchor='ls')
        im = canvas.crop((24, 24, 48, 48)); canvas.paste(0, (24, 24, 48, 48))
        assert canvas.getbbox() is None, ('ink outside 24x24', c)
        rom = metrics.get(c, {}).get('raw_advance_px')
        glyphs.append({'character': c, 'codes': codes, 'advance': advance, 'rom_advance': rom, 'lift': dy, 'shift_right': dx,
                       'address': BITMAPS + i * 288, 'bbox': im.getbbox(), 'pixels': p.pack_i4(im)})
    return glyphs


def blank_address(glyphs): return BITMAPS + len(glyphs) * 288


def size(glyphs): return ((blank_address(glyphs) + 288 - BASE) + 0x1f) & ~0x1f


def texel_stub(fallback):
    s = p.PPC(TEXEL)
    s.d(11, 0, 5, 0); s.bc(0x40820000, 'fallback')
    s.d(11, 0, 6, 6); s.bc(0x40820000, 'fallback')
    s.d(34, 8, 3, 0); s.d(10, 0, 8, 0x80); s.bc(0x40800000, 'fallback')      # lbz; cmplwi 0x80; bge
    s.d(14, 9, 8, -0x20); s.d(10, 0, 9, 95); s.bc(0x41810000, 'fallback')     # r9=c-0x20; bgt (unsigned)
    s.emit(21 << 26 | 9 << 21 | 9 << 16 | 2 << 11 | 0 << 6 | 29 << 1)        # slwi r9,r9,2
    s.load(10, ASCII_T); s.emit(31 << 26 | 9 << 21 | 10 << 16 | 9 << 11 | 23 << 1)  # lwzx r9,r10,r9
    s.d(11, 0, 9, 0); s.bc(0x41820000, 'fallback')
    s.d(28, 9, 0, 31)                                                         # andi. r0,r9,31 (advance)
    s.emit(21 << 26 | 9 << 21 | 9 << 16 | 0 << 11 | 0 << 6 | 26 << 1)        # clrrwi r9,r9,5
    s.d(14, 10, 4, 0); s.d(14, 11, 0, 72); s.emit(0x7d6903a6)                # mr r10,r4; li r11,72; mtctr
    s.label('loop'); s.d(32, 12, 9, 0); s.d(36, 12, 10, 0)
    s.d(14, 9, 9, 4); s.d(14, 10, 10, 4); s.bc(0x42000000, 'loop')
    s.d(36, 0, 7, 0); s.d(14, 3, 3, 1); s.emit(0x4e800020)
    s.label('fallback'); s.branch(fallback)
    data = s.finish(); assert len(data) <= 0x100
    return data


def lookup_stub():
    s = p.PPC(LOOKUP)
    s.d(10, 0, 30, 0x80); s.bc(0x40800000, 'two')                            # cmplwi r30,0x80; bge
    s.d(14, 11, 30, -0x20); s.d(10, 0, 11, 95); s.bc(0x41810000, 'miss')
    s.emit(21 << 26 | 11 << 21 | 11 << 16 | 2 << 11 | 0 << 6 | 29 << 1)      # slwi r11,r11,2
    s.load(12, ASCII_T); s.emit(31 << 26 | 10 << 21 | 12 << 16 | 11 << 11 | 23 << 1)  # lwzx r10,r12,r11
    s.bc(0x48000000, 'check')
    s.label('two')
    s.emit(21 << 26 | 30 << 21 | 11 << 16 | 24 << 11 | 8 << 6 | 31 << 1)     # srwi r11,r30,8
    s.emit(21 << 26 | 30 << 21 | 12 << 16 | 0 << 11 | 24 << 6 | 31 << 1)     # clrlwi r12,r30,24
    s.d(14, 12, 12, -0x40); s.d(10, 0, 12, 188); s.bc(0x41810000, 'miss')
    s.emit(21 << 26 | 12 << 21 | 12 << 16 | 2 << 11 | 0 << 6 | 29 << 1)      # slwi r12,r12,2
    for hi, table in TABLES.items():
        s.d(10, 0, 11, hi); s.bc(0x40820000, f'n{hi}')
        s.load(11, table); s.emit(31 << 26 | 10 << 21 | 11 << 16 | 12 << 11 | 23 << 1); s.bc(0x48000000, 'check')
        s.label(f'n{hi}')
    s.bc(0x48000000, 'miss')
    s.label('check'); s.d(11, 0, 10, 0); s.bc(0x41820000, 'miss')
    s.emit(21 << 26 | 10 << 21 | 4 << 16 | 26 << 1)                           # clrrwi r4,r10,5 (as v04)
    s.d(28, 10, 0, 31); s.d(36, 4, 1, 0x14); s.d(36, 0, 1, 8); s.branch(0x801a064c)
    s.label('miss'); s.branch(life4.BASE)                                     # v04: Korean, tilde, spacers
    data = s.finish(); assert len(data) <= 0x100
    return data


def tables(glyphs):
    ascii_t = bytearray(96 * 4); two = {hi: bytearray(189 * 4) for hi in TABLES}
    for g in glyphs:
        word = v.word(g['address'] | g['advance'])
        for code in g['codes']:
            if code < 0x80: ascii_t[(code - 0x20) * 4:(code - 0x20) * 4 + 4] = word
            else:
                hi, lo = code >> 8, code & 0xff; at = (lo - 0x40) * 4
                assert not any(two[hi][at:at + 4]); two[hi][at:at + 4] = word
    return ascii_t, two


def prepare():
    original, report = v06.load_v05(); dol = bytearray(original)
    memory = v.read('metadata/injection_memory_verification.json'); v03_texel = memory['payload_end']
    glyphs = draw(); entries = life4.mapped(original)
    codes = {c for g in glyphs for c in g['codes']}
    assert not codes & {m['code'] for m in entries}
    SIZE = size(glyphs); payload = bytearray(SIZE)
    def put(addr, data): payload[addr - BASE:addr - BASE + len(data)] = data
    put(TEXEL, texel_stub(v03_texel)); put(LOOKUP, lookup_stub())
    ascii_t, two = tables(glyphs); put(ASCII_T, ascii_t)
    for hi, t in two.items(): put(TABLES[hi], t)
    for g in glyphs: put(g['address'], g['pixels'])
    blank = blank_address(glyphs)
    spacers = [{'character': c, 'code': code, 'advance': adv, 'address': blank, 'pixels': bytes(288)} for c, code, adv in SPACERS]
    patches = []
    def at(addr, data, expected, reason):
        off = v.offset(original, addr); assert bytes(dol[off:off + len(data)]) == expected, (hex(addr), reason)
        patches.append({'offset': off, 'before': expected.hex(), 'after': data.hex(), 'reason': reason}); dol[off:off + len(data)] = data
    at(DYNAMIC, v.branch(DYNAMIC, TEXEL), v.branch(DYNAMIC, v03_texel), 'dynamic texel: Gmarket ASCII first')
    at(PRELOAD, v.branch(PRELOAD, TEXEL), v.branch(PRELOAD, v03_texel), 'ASCII preload texel: Gmarket ASCII first')
    at(HOOK, v.branch(HOOK, LOOKUP, False), v.branch(HOOK, life4.BASE, False), 'table lookup before v04 lookup')
    old = life4.stub(entries); new = life4.stub(entries + spacers)
    off = v.offset(original, life4.BASE); assert original[off:off + len(old)] == old and len(new) <= 0x400
    at(life4.BASE, new, bytes(original[off:off + len(new)]), 'v04 specials: blank spacers')
    ah = memory['arena_hook']; o = p.PPC(ah); o.load(11, BASE); n = p.PPC(ah); n.load(11, BASE + SIZE)
    at(ah, n.finish(), o.finish(), 'extend ArenaLo reservation')
    sec = int.from_bytes(original[0x98:0x9c], 'big')
    assert int.from_bytes(original[0x50:0x54], 'big') + sec == BASE and int.from_bytes(original[8:12], 'big') + sec == len(original)
    off = 0x98; patches.append({'offset': off, 'before': original[off:off + 4].hex(), 'after': v.word(sec + SIZE).hex(), 'reason': 'extend DOL text section 2'})
    dol[0x98:0x9c] = v.word(sec + SIZE); dol.extend(payload)
    reverse = bytearray(dol[:len(original)])
    for x in patches: reverse[x['offset']:x['offset'] + len(bytes.fromhex(x['before']))] = bytes.fromhex(x['before'])
    assert bytes(reverse) == original
    global SIZE_DONE; SIZE_DONE = SIZE
    return bytes(dol), original, report, glyphs, entries, patches, spacers


def verify(data):
    dol, original, report, glyphs, entries, _, spacers = data
    memory = v.read('metadata/injection_memory_verification.json')
    u = v.cpu(dol); old = v.cpu(original); n = 0
    for g in glyphs:
        for code in g['codes']:
            ptr, w = life.lookup(u, code)
            assert ptr == g['address'] and w == g['advance'] and bytes(u.mem_read(ptr, 288)) == g['pixels'], (g['character'], hex(code))
            n += 1
    for m in entries:
        ptr, w = life.lookup(u, m['code']); assert ptr == m['address'] and w == m['advance']
        assert bytes(u.mem_read(ptr, 288)) == m['pixels']
    for m in spacers:
        ptr, w = life.lookup(u, m['code']); assert ptr == m['address'] and w == m['advance'] and not any(u.mem_read(ptr, 288))
    samples = [0x20, 0x7e, 0x5c, 0x8140, 0x8141, 0x8142, 0x82a0, 0x8341, 0x889f, 0x8160, 0x815b]
    for code in samples:
        a, aw = life.lookup(u, code); b, bw = life.lookup(old, code)
        assert aw == bw and bytes(u.mem_read(a, 288)) == bytes(old.mem_read(b, 288)), hex(code)
    texel = 0
    for site in (PRELOAD, DYNAMIC):
        for c in 'A1!g?':
            g = next(x for x in glyphs if x['character'] == c)
            cpu = v.cpu(dol); cpu.mem_write(p.STRING, c.encode() + b'A\0'); cpu.mem_write(p.DEST, bytes(320))
            for r, x in {1: p.STACK, 3: p.STRING, 4: p.DEST, 5: 0, 6: 6, 7: p.WIDTH}.items(): cpu.reg_write(p.regnum(r), x)
            v.call(cpu, site, site + 4)
            assert cpu.reg_read(p.regnum(3)) == p.STRING + 1 and bytes(cpu.mem_read(p.DEST, 288)) == g['pixels']
            assert int.from_bytes(cpu.mem_read(p.WIDTH, 4), 'big') == g['advance']; texel += 1
        for c in ' ~':
            a, b = v.cpu(dol), v.cpu(original)
            for cpu in (a, b):
                cpu.mem_write(p.STRING, c.encode() + b'\0'); cpu.mem_write(p.DEST, bytes(320))
                for r, x in {1: p.STACK, 3: p.STRING, 4: p.DEST, 5: 0, 6: 6, 7: p.WIDTH}.items(): cpu.reg_write(p.regnum(r), x)
                v.call(cpu, site, site + 4)
            assert a.reg_read(p.regnum(3)) == b.reg_read(p.regnum(3)) and bytes(a.mem_read(p.DEST, 288)) == bytes(b.mem_read(p.DEST, 288))
    u = v.cpu(dol); ah = memory['arena_hook']; end = BASE + SIZE_DONE
    for requested in [life4.BASE, BASE - 32, BASE, end - 32, end, end + 32, 0x81000000]:
        u.reg_write(p.regnum(3), requested); v.call(u, ah)
        assert int.from_bytes(u.mem_read(p.R13 - 0x72f0, 4), 'big') == max(requested, end)
    return {'glyphs': len(glyphs), 'codes': n, 'previous_immutable_glyphs_unchanged': len(entries),
            'fallback_cases_equal_v05': len(samples), 'texel_cases': texel, 'arena_end': hex(end),
            'digits_fixed_advance': DIGIT_ADVANCE,
            'lifted': {g['character']: g['lift'] for g in glyphs if g['lift']}}


SIZE_DONE = None


def __getattr__(name):
    if name == 'SIZE':
        assert SIZE_DONE is not None, 'call prepare() first'
        return SIZE_DONE
    raise AttributeError(name)
