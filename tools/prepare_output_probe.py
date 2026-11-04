"""Memory-only Japanese Rev1 font-cache probe; NEVER writes a DOL or disc.

Synthetic CPU addresses below are test fixtures, NOT deployable patch addresses.
Requires the stage1 extracted DOL/scripts, Pillow and Unicorn.
"""
import hashlib
import json
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from unicorn import Uc, UC_ARCH_PPC, UC_MODE_32, UC_MODE_BIG_ENDIAN, UC_HOOK_CODE
from unicorn import ppc_const as reg
from inspect_discs import ROOT, save

FONT = ROOT / 'work/references/gmarket/GmarketSansBold.otf'
DOL = ROOT / 'work/roundtrip/jp/main.dol'
INV = ROOT / 'metadata/disc_inventory_jp.json'
ROMFONT = Path.home() / 'Desktop/Dolphin-x64/Sys/GC/font_japanese.bin'
OUT = ROOT / 'work/output-probe'
GET_TEXEL = 0x80168054
CALL_SITE = 0x801a05e0
# All of these addresses exist ONLY in this isolated Unicorn fixture.
R13, STACK, FONT_RAM = 0x80400000, 0x817f0000, 0x81000000
STUB, BITMAPS, STRING, DEST, WIDTH = 0x81800000, 0x81801000, 0x81900000, 0x81901000, 0x81902000
CACHE, OBJECT, STOP = 0x81910000, 0x81920000, 0x81fff000
FONT_SIZE, BASELINE, ADVANCE = 20, 18, 20


def sha(b):
    return hashlib.sha256(b).hexdigest()


def yay0(data):
    assert data[:4] == b'Yay0'
    size, links, chunks = struct.unpack_from('>3I', data, 4)
    out = bytearray(); masks = 16; mask = bits = 0
    while len(out) < size:
        if bits == 0:
            mask = struct.unpack_from('>I', data, masks)[0]; masks += 4; bits = 32
        if mask & 0x80000000:
            out.append(data[chunks]); chunks += 1
        else:
            word = struct.unpack_from('>H', data, links)[0]; links += 2
            count = word >> 12; distance = (word & 0xfff) + 1
            if count == 0:
                count = data[chunks] + 18; chunks += 1
            else:
                count += 2
            for _ in range(count): out.append(out[-distance])
        mask = (mask << 1) & 0xffffffff; bits -= 1
    assert len(out) == size
    return bytes(out)


def pack_i4(im):
    assert im.size == (24, 24)
    p = im.load(); out = bytearray()
    for by in range(0, 24, 8):
        for bx in range(0, 24, 8):
            for y in range(by, by + 8):
                for x in range(bx, bx + 8, 2):
                    out.append(((p[x, y] + 8) // 17) * 16 + (p[x + 1, y] + 8) // 17)
    return bytes(out)


def unpack_i4(data):
    assert len(data) == 288
    im = Image.new('L', (24, 24)); p = im.load(); i = 0
    for by in range(0, 24, 8):
        for bx in range(0, 24, 8):
            for y in range(by, by + 8):
                for x in range(bx, bx + 8, 2):
                    p[x, y] = (data[i] >> 4) * 17
                    p[x + 1, y] = (data[i] & 15) * 17; i += 1
    return im


class PPC:
    def __init__(self, base): self.base = base; self.words = []; self.labels = {}; self.fixes = []
    def emit(self, word): self.words.append(word)
    def d(self, op, rt, ra, imm): self.emit(op << 26 | rt << 21 | ra << 16 | imm & 0xffff)
    def load(self, rt, value): self.d(15, rt, 0, value >> 16); self.d(24, rt, rt, value & 0xffff)
    def label(self, name): self.labels[name] = len(self.words) * 4
    def bc(self, instruction, name): self.fixes.append((len(self.words), name)); self.emit(instruction)
    def branch(self, target, link=False):
        diff = target - (self.base + len(self.words) * 4)
        assert -(1 << 25) <= diff < 1 << 25 and diff % 4 == 0
        self.emit(0x48000000 | (diff & 0x03fffffc) | int(link))
    def finish(self):
        for i, name in self.fixes:
            diff = self.labels[name] - i * 4
            assert -32768 <= diff < 32768
            self.words[i] |= diff & 0xfffc
        return struct.pack('>' + 'I' * len(self.words), *self.words)


def make_stub(codes, base=STUB, bitmap_base=BITMAPS, advance=ADVANCE):
    p = PPC(base)
    p.d(11, 0, 5, 0); p.bc(0x40820000, 'fallback')  # cmpwi r5,0; bne
    p.d(11, 0, 6, 6); p.bc(0x40820000, 'fallback')
    # Byte loads allow unaligned multibyte strings.
    p.d(34, 8, 3, 0)
    p.d(28, 8, 9, 0x80); p.bc(0x41820000, 'fallback')  # andi. r9,r8: ASCII, no second-byte read
    p.emit(0x5508402e)  # slwi r8,r8,8
    p.d(34, 9, 3, 1); p.emit(0x7d084b78)  # or r8,r8,r9
    for i, code in enumerate(codes):
        p.d(10, 0, 8, code); p.bc(0x41820000, f'g{i}')
    p.label('fallback'); p.branch(GET_TEXEL)
    for i in range(len(codes)):
        p.label(f'g{i}'); p.load(9, bitmap_base + i * 288); p.bc(0x48000000, 'copy')
    p.label('copy')
    p.d(14, 10, 4, 0); p.d(14, 11, 0, 72)
    p.emit(0x7d6903a6)  # mtctr r11
    p.label('loop'); p.d(32, 12, 9, 0); p.d(36, 12, 10, 0)
    p.d(14, 9, 9, 4); p.d(14, 10, 10, 4); p.bc(0x42000000, 'loop')
    p.d(14, 8, 0, advance); p.d(36, 8, 7, 0)
    p.d(14, 3, 3, 2); p.emit(0x4e800020)  # next string; blr
    return p.finish()


def regnum(i): return getattr(reg, f'UC_PPC_REG_{i}')


def create_cpu(dol, inv, romfont):
    u = Uc(UC_ARCH_PPC, UC_MODE_32 | UC_MODE_BIG_ENDIAN)
    u.mem_map(0x80000000, 0x02000000)
    for s in inv['dol']['sections']:
        u.mem_write(s['ram_address'], dol[s['file_offset']:s['file_offset'] + s['size']])
    u.mem_write(FONT_RAM, romfont)
    u.reg_write(regnum(13), R13)
    def put(addr, value, size=4): u.mem_write(addr, value.to_bytes(size, 'big'))
    put(R13 - 0x72d0, 1, 2); put(R13 - 0x6668, 1, 2)
    put(R13 - 0x6a48, 0x80167f18); put(R13 - 0x6a4c, FONT_RAM)
    put(R13 - 0x6a50, FONT_RAM)
    return u


def texel(u, address, encoded, x=0, stride=6):
    u.mem_write(STRING, encoded + b'\0'); u.mem_write(DEST, b'\xa5' * 2048)
    u.mem_write(WIDTH, b'\0' * 4)
    for i, value in {1: STACK, 3: STRING, 4: DEST, 5: x, 6: stride, 7: WIDTH}.items():
        u.reg_write(regnum(i), value)
    u.reg_write(reg.UC_PPC_REG_LR, STOP)
    u.emu_start(address, STOP, count=100000)
    assert u.reg_read(reg.UC_PPC_REG_PC) == STOP
    return bytes(u.mem_read(DEST, 2048)), int.from_bytes(u.mem_read(WIDTH, 4), 'big'), u.reg_read(regnum(3)) - STRING


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    dol = DOL.read_bytes(); inv = json.loads(INV.read_text())
    assert sha(dol) == inv['dol']['sha256']
    romfont = yay0(ROMFONT.read_bytes())
    u = create_cpu(dol, inv, romfont)
    texts = [('はじめから', '처음부터', 0x200800, 0x80203800), ('つづきから', '이어서', 0x20080c, 0x8020380c)]
    chars = list(dict.fromkeys(''.join(t[1] for t in texts)))
    scripts = sorted((ROOT / 'work/roundtrip/jp/qp/files/bin').glob('*.bin'))
    assert len(scripts) == 40
    pool = dol + b''.join(p.read_bytes() for p in scripts)
    codes = []
    for code in range(0x889f, 0x9873):
        try: code.to_bytes(2, 'big').decode('cp932')
        except UnicodeDecodeError: continue
        if code.to_bytes(2, 'big') not in pool: codes.append(code)
        if len(codes) == len(chars): break
    assert len(codes) == 7
    # User-selected Gmarket Sans Bold, fitted to the original 20px advance.
    font = ImageFont.truetype(str(FONT), FONT_SIZE)
    glyphs = []
    for c in chars:
        im = Image.new('L', (24, 24)); draw = ImageDraw.Draw(im)
        draw.text((0, BASELINE), c, font=font, fill=255, anchor='ls')
        packed = pack_i4(im); assert pack_i4(unpack_i4(packed)) == packed
        glyphs.append(packed)
    stub = make_stub(codes)
    u.mem_write(STUB, stub); u.mem_write(BITMAPS, b''.join(glyphs))
    for i, code in enumerate(codes):
        preserved = {r: 0x10200000 + r for r in [2, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31]}
        for r, value in preserved.items(): u.reg_write(regnum(r), value)
        got, width, advance = texel(u, STUB, code.to_bytes(2, 'big'))
        assert got[:288] == glyphs[i] and got[288:] == b'\xa5' * (2048 - 288)
        assert width == ADVANCE and advance == 2
        assert all(u.reg_read(regnum(r)) == value for r, value in preserved.items())
        assert u.reg_read(regnum(13)) == R13 and u.reg_read(regnum(1)) == STACK
    # Compare fallback against the actual SDK code, including atypical layout arguments.
    fallback = []
    for text in ['A', '0', '!', '?', 'は', '亜']:
        for x, stride in [(0, 6), (2, 8)]:
            raw = text.encode('cp932')
            expected = texel(u, GET_TEXEL, raw, x, stride)
            actual = texel(u, STUB, raw, x, stride)
            assert actual == expected
            fallback.append({'text': text, 'x': x, 'stride': stride, 'width': actual[1], 'advance': actual[2]})
    for code in codes:
        raw = code.to_bytes(2, 'big')
        assert texel(u, STUB, raw, 2, 8) == texel(u, GET_TEXEL, raw, 2, 8)

    # Original CFont cache path; stop BEFORE graphics/GX operations. No game emulation.
    # Fresh CPU ensures trace hooks cover blocks not already translated by Unicorn.
    u = create_cpu(dol, inv, romfont)
    u.mem_write(STUB, stub); u.mem_write(BITMAPS, b''.join(glyphs))
    original_call = bytes(u.mem_read(CALL_SITE, 4)); assert original_call.hex() == '4bfc7a75'
    branch = PPC(CALL_SITE); branch.branch(STUB, True); u.mem_write(CALL_SITE, branch.finish())
    u.mem_write(CACHE, b'\0' * (50 * 320)); u.mem_write(OBJECT, b'\0' * 256)
    u.mem_write(OBJECT + 0x24, struct.pack('>I', 24))
    u.mem_write(R13 - 0x6660, struct.pack('>I', CACHE))
    counts = {'hook': 0, 'flush': 0}
    def trace(cpu, address, size, data):
        if address == STUB: counts['hook'] += 1
        if address == 0x80164b74: counts['flush'] += 1
        if address == 0x80164b9c:
            # The standalone fixture has no OS syscall handler/cache model.
            # Count entry above, execute the flush loop, skip ONLY its final sc.
            assert bytes(cpu.mem_read(address, 4)) == bytes.fromhex('44000002')
            cpu.reg_write(reg.UC_PPC_REG_PC, address + 4)
    u.hook_add(UC_HOOK_CODE, trace)
    def cache_call(code):
        u.mem_write(STRING, code.to_bytes(2, 'big') + b'\0')
        for r, val in {1: STACK, 3: OBJECT, 4: STRING, 5: WIDTH}.items(): u.reg_write(regnum(r), val)
        u.reg_write(reg.UC_PPC_REG_LR, STOP)
        u.emu_start(0x801a0448, 0x801a0674, count=100000)
        assert u.reg_read(reg.UC_PPC_REG_PC) == 0x801a0674
        sp = u.reg_read(regnum(1))
        ptr = int.from_bytes(u.mem_read(sp + 0x14, 4), 'big')
        return ptr, int.from_bytes(u.mem_read(sp + 8, 4), 'big')
    cache_results = []
    for i, code in enumerate(codes):
        ptr, width = cache_call(code)
        assert ptr == CACHE + i * 320 and width == ADVANCE
        assert bytes(u.mem_read(ptr, 288)) == glyphs[i]
        assert bytes(u.mem_read(ptr + 0x120, 4)) == struct.pack('>HH', code, ADVANCE)
        before = dict(counts); assert cache_call(code) == (ptr, width); assert counts == before
        cache_results.append({'code': hex(code), 'miss': 'exact_bitmap_key_width', 'hit': 'same_record_no_hook_no_flush'})
    assert counts == {'hook': 7, 'flush': 7}
    u.mem_write(CACHE, b'\0' * (50 * 320)); u.mem_write(R13 - 0x665c, struct.pack('>I', 49))
    ptr, width = cache_call(codes[0]); assert ptr == CACHE + 49 * 320
    assert bytes(u.mem_read(R13 - 0x665c, 4)) == b'\0' * 4

    def original_glyph(c):
        # SDK OR-writes pixels; clear destination for a clean reference.
        data, width, advance = texel(u, GET_TEXEL, c.encode('cp932'))
        # rerun with zero destination, as the game's memset does
        u.mem_write(DEST, b'\0' * 2048)
        for r, val in {1: STACK, 3: STRING, 4: DEST, 5: 0, 6: 6, 7: WIDTH}.items(): u.reg_write(regnum(r), val)
        u.reg_write(reg.UC_PPC_REG_LR, STOP); u.emu_start(GET_TEXEL, STOP, count=100000)
        return unpack_i4(bytes(u.mem_read(DEST, 288))), width
    sheet = Image.new('RGB', (820, 410), '#f4f0df'); d = ImageDraw.Draw(sheet)
    label = ImageFont.truetype('C:/Windows/Fonts/malgun.ttf', 17)
    d.text((18, 12), '치비로보 출력 시험 준비 — 실제 게임 화면이 아닌 글리프 비교', font=label, fill='#30291e')
    for row, (jp, ko, offset, address) in enumerate(texts):
        assert dol[offset:offset + len(jp.encode('cp932')) + 1] == jp.encode('cp932') + b'\0'
        for col, text in enumerate([jp, ko]):
            line = Image.new('L', (160, 24)); cursor = 0
            for c in text:
                im, width = original_glyph(c) if col == 0 else (unpack_i4(glyphs[chars.index(c)]), ADVANCE)
                line.paste(im, (cursor, 0)); cursor += width
            x = 20 + col * 400; y = 55 + row * 168
            d.text((x, y), '일본어 · Dolphin 기본 폰트' if col == 0 else '한국어 · G마켓 산스 Bold', font=label, fill='#30291e')
            for yy, scale in [(y + 30, 1), (y + 65, 3)]:
                mask = line.resize((480, 72), Image.Resampling.NEAREST) if scale == 3 else line
                # Clip only blank right margin, never glyphs.
                if scale == 3: mask = mask.crop((0, 0, 360, 72))
                sheet.paste('#272116', (x, yy), mask)
    sheet.save(OUT / 'font-preview.png')
    menu_rows = []
    for jp, ko, offset, address in texts:
        encoded = b''.join(codes[chars.index(c)].to_bytes(2, 'big') for c in ko)
        size = len(jp.encode('cp932')) + 1
        assert len(encoded) + 1 <= size
        menu_rows.append({'source': jp, 'translation': ko, 'dol_offset': hex(offset), 'ram_address': hex(address),
                          'original_hex': (jp.encode('cp932') + b'\0').hex(), 'replacement_hex': (encoded + bytes(size - len(encoded))).hex(),
                          'note': 'Fixed original field length; no pointer relocation. Menu visibility untested.'})
    save(ROOT / 'translation/output_probe.json', {'edition': 'GGTJ01 revision 1', 'scope': 'two DOL menu strings, seven glyphs only',
        'font_proposal': {'family': 'Gmarket Sans Bold', 'sha256': sha(FONT.read_bytes()), 'size_px': FONT_SIZE, 'baseline_px': BASELINE, 'advance_px': ADVANCE,
                          'reason': 'Explicitly selected by user for the authorized test ISO. Approval state lives in project.json.'},
        'mapping': [{'hangul': c, 'sjis_code': hex(code), 'original_japanese_cell': code.to_bytes(2, 'big').decode('cp932')} for c, code in zip(chars, codes)],
        'menus': menu_rows})
    save(ROOT / 'metadata/output_probe_preparation.json', {'mode': 'memory_only_no_localized_disc_or_DOL_written',
        'dol_sha256': sha(dol), 'reference_dolphin_font_sha256': sha(ROMFONT.read_bytes()), 'font_sha256': sha(FONT.read_bytes()),
        'unused_code_scan': {'scope': 'entire original DOL plus 40 Japanese bin/*.bin files, raw byte scan', 'script_count': len(scripts), 'selected_pairs_absent': True, 'not_claimed': 'all possible nested assets or dynamically composed strings'},
        'hook_call_site': hex(CALL_SITE), 'original_call': original_call.hex(), 'original_texel_function': hex(GET_TEXEL),
        'stub_bytes': len(stub), 'glyph_bytes': len(glyphs) * 288, 'synthetic_ram_only': True,
        'direct_glyph_checks': len(codes), 'fallback_checks': fallback, 'nondefault_layout_fallback_checks': len(codes),
        'cache_checks': cache_results, 'cache_slot49_wrap': True, 'callee_saved_registers_preserved': True,
        'cache_flush_syscall': 'Final sc at 0x80164b9c skipped in fixture without OS handler; hardware cache coherency NOT validated.',
        'preview': 'work/output-probe/font-preview.png',
        'limits': ['CPU checks stop before GX; no rendered game screen or Dolphin execution.', 'This test uses synthetic addresses. Separate candidate layout checks are in metadata/output_probe_layout.json; boot/cache coherency remains untested.', 'No full script insertion or full Hangul repertoire validation.', 'Dolphin replacement ROM font reference is not a hardware IPL font.']})
    print('PASS: 7 glyphs, 12 normal/guard fallbacks, 7 selected-code guards, cache miss/hit and slot49 wrap. No DOL/ISO emitted.')
    print(OUT / 'font-preview.png')


if __name__ == '__main__': main()
