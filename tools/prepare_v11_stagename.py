"""Proportional spacing for the loading-screen area name (v13).

The label is drawn per character by the routine at 0x8000af1c. For character i
of N it computes the centre x as
    29 + 320 - 0.5*(58*N) + 58*i          (0x8000b090..0x8000b0bc)
so every character, including a space, takes a 58px cell and the line is
centred on 320. At 0x8000b0b0 (`fsubs f4,f4,f5`, f4 = i) a call replaces i by
    acc_i + w_i/2 - 0.5     and f3 (= 58*N) by 58*W,
where w is 0.35 for a space (0x20 / 0x8140), 0.9 for other 2-byte glyphs and
1.0 for 1-byte glyphs, acc_i the sum of w before i and W the total. The same
centring formula then centres on real widths.

v12 patched 0x8000bbdc instead (2026-11-03); that value is the per-character
animation delay, not the position, so nothing moved on screen. v13 drops it.
Memory-only preparation and PPC verification.
"""
import struct
import prepare_output_probe as p
import prepare_v03_corrections as v

SITE = 0x8000b0b0
ORIGINAL = 0xec842828          # fsubs f4,f4,f5
SPACE = 0.35
HANGUL = 0.9
SIZE = 0xe0
DATA = 0xc0
REC = -0x1bec                  # record field: character pointer (stride 0x14)
COUNT = -0x1bf4                # number of records


def fop(xo, d, a, b): return 59 << 26 | d << 21 | a << 16 | b << 11 | xo << 1
def fmuls(d, a, c): return 59 << 26 | d << 21 | a << 16 | c << 6 | 25 << 1
def fmr(d, b): return 63 << 26 | d << 21 | b << 11 | 72 << 1
def cmpw(a, b): return 31 << 26 | a << 16 | b << 11


def stub(base):
    s = p.PPC(base)
    s.load(8, base + DATA)
    s.d(15, 12, 23, 0x10); s.d(14, 12, 12, REC & 0xffff)        # r12 = &record[0].char
    s.d(32, 11, 12, (COUNT - REC) & 0xffff)                      # r11 = count
    s.d(48, 9, 8, 0); s.emit(fmr(10, 9)); s.emit(fmr(11, 9))     # acc = W = w_i = 0
    s.d(14, 10, 0, 0)                                            # j = 0
    s.label('loop'); s.emit(cmpw(10, 11)); s.bc(0x40800000, 'done')
    s.d(32, 9, 12, 0)                                            # r9 = character pointer
    s.d(34, 0, 9, 0); s.d(11, 0, 0, 0x20); s.bc(0x41820000, 'space')
    s.d(10, 0, 0, 0x81); s.bc(0x41800000, 'one')                # 1-byte
    s.d(11, 0, 0, 0x81); s.bc(0x40820000, 'two')
    s.d(34, 0, 9, 1); s.d(11, 0, 0, 0x40); s.bc(0x41820000, 'space')
    s.label('two'); s.d(48, 12, 8, 12); s.bc(0x48000000, 'have')
    s.label('one'); s.d(48, 12, 8, 4); s.bc(0x48000000, 'have')
    s.label('space'); s.d(48, 12, 8, 8)
    s.label('have'); s.emit(fop(21, 10, 10, 12))                 # W += w
    s.emit(cmpw(10, 24)); s.bc(0x40800000, 'notbefore')
    s.emit(fop(21, 9, 9, 12))                                    # j < i: acc += w
    s.label('notbefore'); s.bc(0x40820000, 'next'); s.emit(fmr(11, 12))       # j == i: w_i
    s.label('next'); s.d(14, 10, 10, 1); s.d(14, 12, 12, 0x14); s.branch(base + s.labels['loop'])
    s.label('done')
    s.d(48, 13, 8, 16)                                           # 0.5
    s.emit(fmuls(4, 11, 13)); s.emit(fop(21, 4, 9, 4)); s.emit(fop(20, 4, 4, 13))   # f4 = acc + w/2 - 0.5
    s.emit(fmuls(3, 6, 10))                                      # f3 = 58*W
    s.emit(0x4e800020)
    code = s.finish(); assert len(code) <= DATA, len(code)
    payload = bytearray(SIZE); payload[:len(code)] = code
    payload[DATA:DATA + 20] = struct.pack('>fffff', 0.0, 1.0, SPACE, HANGUL, 0.5)
    return bytes(payload)


def apply(dol, base):
    dol = bytearray(dol); off = v.offset(dol, SITE)
    assert int.from_bytes(dol[off:off + 4], 'big') == ORIGINAL, hex(int.from_bytes(dol[off:off + 4], 'big'))
    before = bytes(dol[off:off + 4]); dol[off:off + 4] = v.branch(SITE, base)
    return dol, stub(base), [{'offset': off, 'before': before.hex(), 'after': dol[off:off + 4].hex(), 'reason': 'area name centre x by real widths'}]


def verify(dol, base, mapping):
    """Build records like 0x8000bb7c does, run the call, then the game's centring formula."""
    def encode(t): return b''.join(mapping[c].to_bytes(2, 'big') if c in mapping else c.encode('cp932') for c in t)
    obj = 0x80f00000; rec = obj + 0x100000 + REC; cases = []
    for text in ['치비로보 하우스', '아빠 엄마의 방', '지하 창고', '거실', 'ちびロボハウス', 'キッチン　テスト']:
        raw = encode(text); chars = []; pos = 0
        while pos < len(raw):
            two = 0x81 <= raw[pos] <= 0x9f or 0xe0 <= raw[pos] <= 0xfc
            chars.append(raw[pos:pos + (2 if two else 1)]); pos += 2 if two else 1
        w = [SPACE if c in (b' ', b'\x81\x40') else HANGUL if c[0] >= 0x81 else 1.0 for c in chars]; W = sum(w)
        xs = []
        for i in range(len(chars)):
            u = v.cpu(dol)
            for j, ch in enumerate(chars):
                u.mem_write(p.STRING + 8 * j, ch + b'\0'); u.mem_write(rec + 0x14 * j, struct.pack('>I', p.STRING + 8 * j))
            u.mem_write(obj + 0x100000 + COUNT, struct.pack('>I', len(chars)))
            u.reg_write(p.regnum(23), obj); u.reg_write(p.regnum(24), i)
            v.fpr_write(u, 6, 58.0); v.fpr_write(u, 4, float(i)); v.fpr_write(u, 3, 58.0 * len(chars))
            u.reg_write(p.reg.UC_PPC_REG_LR, p.STOP); u.emu_start(base, p.STOP, count=2000)
            f4, f3 = v.fpr_read(u, 4), v.fpr_read(u, 3)
            x = 29 + (320 - 0.5 * f3) + 58 * f4                     # the game's own formula
            want = 320 + 58 * (sum(w[:i]) + w[i] / 2 - W / 2)
            assert abs(x - want) < 1e-3, (text, i, x, want); xs.append(round(x, 2))
        cases.append({'text': text, 'centres': xs, 'width_cells': round(W, 2),
                      'left': round(320 - 29 * W, 1), 'right': round(320 + 29 * W, 1),
                      'original_left': 320 - 29 * len(chars)})
    return cases


# ---------------------------------------------------------------------------
# Save-file card (「이어서」 screen). 2026-11-03 사용자 전체 스크린샷으로 위치 확정.
# 0x80036994 gets the area name, right-aligns it with N = strlen/2 cells
# (x0 = 88*s - 18*s*N) and calls 0x800324ec, which draws character i at
# x0 + i*pitch (0x8003276c `fmadds f25,f0,f26,f27`, f0 = i). A halfwidth space
# counts as half a cell in N but takes a whole cell when drawn, so
# 「치비로보 하우스」 (15 bytes -> N 7, 8 glyphs) ran one cell past the card.
# The call keeps every string without spaces exactly as before; with spaces,
# a space takes CARD_SPACE cells and the line is shifted so its right edge is
# x0 + N*pitch, where the caller meant it to be.

CARD_SITE = 0x8003276c
CARD_ORIGINAL = 0xef20deba           # fmadds f25,f0,f26,f27
CARD_SPACE = 0.35
CARD_SIZE = 0xe0
CARD_DATA = 0xd0
RECORDS = 0x24c                      # r1 + 0x24c: per-character records, stride 0x14, [0] = char pointer


def card_stub(base):
    s = p.PPC(base)
    s.load(8, base + CARD_DATA)
    s.d(14, 12, 1, RECORDS); s.d(14, 10, 0, 0); s.d(14, 9, 0, 0)        # r12 records, j=0, spaces=0
    s.d(48, 9, 8, 0); s.emit(fmr(10, 9))                                 # acc = W = 0
    s.label('loop'); s.emit(cmpw(10, 19)); s.bc(0x40800000, 'done')
    s.d(32, 7, 12, 0); s.d(34, 0, 7, 0)
    s.d(11, 0, 0, 0x20); s.bc(0x41820000, 'space')
    s.d(11, 0, 0, 0x81); s.bc(0x40820000, 'full')
    s.d(34, 0, 7, 1); s.d(11, 0, 0, 0x40); s.bc(0x41820000, 'space')
    s.label('full'); s.d(48, 12 - 12 + 12, 8, 4); s.bc(0x48000000, 'have')
    s.label('space'); s.d(48, 12, 8, 8); s.d(14, 9, 9, 1)
    s.label('have'); s.emit(fop(21, 10, 10, 12))                         # W += w
    s.emit(cmpw(10, 18)); s.bc(0x40800000, 'skip'); s.emit(fop(21, 9, 9, 12))   # j < i: acc += w
    s.label('skip'); s.d(14, 10, 10, 1); s.d(14, 12, 12, 0x14); s.branch(base + s.labels['loop'])
    s.label('done'); s.d(11, 0, 9, 0); s.bc(0x41820000, 'out')          # no spaces: original layout
    s.d(32, 7, 1, RECORDS); s.d(14, 6, 0, 0)                             # strlen(record[0])
    s.label('len'); s.emit(31 << 26 | 0 << 21 | 7 << 16 | 6 << 11 | 87 << 1)     # lbzx r0,r7,r6
    s.d(11, 0, 0, 0); s.bc(0x41820000, 'lend'); s.d(14, 6, 6, 1); s.branch(base + s.labels['len'])
    s.label('lend'); s.emit(21 << 26 | 6 << 21 | 6 << 16 | 31 << 11 | 1 << 6 | 31 << 1)   # srwi r6,r6,1 (N)
    s.d(27, 6, 6, 0x8000); s.d(36, 6, 1, 0x3e4); s.d(50, 11, 1, 0x3e0)  # xoris; stw; lfd (hi word 0x4330 already there)
    s.emit(fop(20, 11, 11, 29))                                          # N as float
    s.emit(fop(20, 11, 11, 10)); s.emit(fop(21, 9, 9, 11))              # acc += N - W
    s.label('out'); s.emit(59 << 26 | 25 << 21 | 9 << 16 | 27 << 11 | 26 << 6 | 29 << 1)   # fmadds f25,f9,f26,f27
    s.emit(0x4e800020)
    code = s.finish(); assert len(code) <= CARD_DATA, len(code)
    payload = bytearray(CARD_SIZE); payload[:len(code)] = code
    payload[CARD_DATA:CARD_DATA + 12] = struct.pack('>fff', 0.0, 1.0, CARD_SPACE)
    return bytes(payload)


def apply_card(dol, base):
    dol = bytearray(dol); off = v.offset(dol, CARD_SITE)
    got = int.from_bytes(dol[off:off + 4], 'big'); assert got == CARD_ORIGINAL, hex(got)
    before = bytes(dol[off:off + 4]); dol[off:off + 4] = v.branch(CARD_SITE, base)
    return dol, card_stub(base), [{'offset': off, 'before': before.hex(), 'after': dol[off:off + 4].hex(), 'reason': 'save card area name x by real widths'}]


def verify_card(dol, base, mapping):
    def encode(t): return b''.join(mapping[c].to_bytes(2, 'big') if c in mapping else c.encode('cp932') for c in t)
    magic = struct.unpack('>d', bytes.fromhex('4330000080000000'))[0]; cases = []
    for text in ['치비로보 하우스', '아빠 엄마의 방', '지하 창고', '거실', '0:08', 'ちびロボハウス', 'キッチン　テスト']:
        raw = encode(text); chars = []; pos = 0
        while pos < len(raw):
            two = 0x81 <= raw[pos] <= 0x9f or 0xe0 <= raw[pos] <= 0xfc
            chars.append(pos); pos += 2 if two else 1
        spaces = [raw[c:c + 1] == b' ' or raw[c:c + 2] == b'\x81\x40' for c in chars]
        w = [CARD_SPACE if sp else 1.0 for sp in spaces]; W = sum(w); N = len(raw) // 2
        pitch, x0 = 18.0, 100.0; xs = []
        for i in range(len(chars)):
            u = v.cpu(dol); sp = p.STACK
            u.mem_write(p.STRING, raw + b'\0')
            for j, c in enumerate(chars): u.mem_write(sp + RECORDS + 0x14 * j, struct.pack('>I', p.STRING + c))
            u.mem_write(sp + 0x3e0, struct.pack('>I', 0x43300000))
            u.reg_write(p.regnum(1), sp); u.reg_write(p.regnum(18), i); u.reg_write(p.regnum(19), len(chars))
            v.fpr_write(u, 26, pitch); v.fpr_write(u, 27, x0); v.fpr_write(u, 29, magic); v.fpr_write(u, 0, float(i))
            u.reg_write(p.reg.UC_PPC_REG_LR, p.STOP); u.emu_start(base, p.STOP, count=5000)
            got = v.fpr_read(u, 25)
            want = x0 + pitch * i if not any(spaces) else x0 + pitch * (sum(w[:i]) + N - W)
            assert abs(got - want) < 1e-3, (text, i, got, want); xs.append(round(got, 2))
            for f, val in ((26, pitch), (27, x0), (29, magic)): assert v.fpr_read(u, f) == val
        right = xs[-1] + pitch
        cases.append({'text': text, 'x': xs, 'right_edge': round(right, 2), 'caller_right_edge': x0 + pitch * N,
                      'unchanged': not any(spaces)})
    return cases
