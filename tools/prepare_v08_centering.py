"""Actual-width centering for the remaining fixed-cell printf callers (v08).

26 callers (save/memory-card menus, shop yes/no and labels) compute
x = A - (N-1)*f4*0.5 with N = strlen(buffer)/2, i.e. they assume every
character is one full cell of width f4. Korean glyphs are 20/24 of a cell,
so the text drifts left by an amount that depends on N. A wrapper before
printf adds (N*f4 - actual_width)*0.5, which gives x = A + f4/2 - width/2:
the same anchor the original layout centred on, now by real glyph widths.
Same idea as the v03 footer wrapper. Memory-only preparation; no DOL/ISO.
"""
import struct
from capstone import Cs, CS_ARCH_PPC, CS_MODE_32, CS_MODE_BIG_ENDIAN
import prepare_output_probe as p
import prepare_v03_corrections as v
from prepare_v03_corrections import fop, fmul, PRINTF, WIDTH_FN

STRLEN = 0x8015ab20
HALF = -0x48a4            # r2 constant 0.5 (also used by the v03 wrapper)
MAGIC = -0x78b0           # r2 double 2^52 for unsigned int -> double
SITES = [0x8003392c, 0x800339ac, 0x80033a24, 0x80033acc, 0x80033b4c, 0x80033bc8,
         0x80033c80, 0x80033cf8, 0x80033d74, 0x80033e10, 0x80033ed0, 0x80033f7c,
         0x80034000, 0x80034088, 0x80034104, 0x8003dd04, 0x8003dd88, 0x8003de0c,
         0x8003de94, 0x8003df28, 0x8003ebdc, 0x8003ec60, 0x8003ece8, 0x80040fe0,
         0x80041064, 0x800410ec]


def check_sites(dol):
    """Each site: bl printf after strlen(rX=r1+K)/2, f4 = cell register, r5 = r1+K."""
    md = Cs(CS_ARCH_PPC, CS_MODE_32 | CS_MODE_BIG_ENDIAN); found = []
    for site in SITES:
        off = v.offset(dol, site); assert dol[off:off + 4] == v.branch(site, PRINTF), hex(site)
        ins = [(x.mnemonic, x.op_str) for x in md.disasm(dol[off - 0x90:off], site - 0x90)]
        j = max(i for i, (m, o) in enumerate(ins) if m == 'bl' and o == hex(STRLEN))
        arg = next(o for m, o in reversed(ins[:j]) if m == 'addi' and o.startswith('r3, r1,'))
        after = ins[j + 1:]
        assert after[0] == ('srwi', 'r3, r3, 1') and not any(m == 'bl' for m, _ in after)
        assert ('addi', 'r5, r1,' + arg.split('r1,')[1]) in after, (hex(site), arg)
        cell = [o.split(', ')[1] for m, o in after if m == 'fmr' and o.startswith('f4,')][-1]
        assert any(m == 'fmuls' and o.split(', ')[2] == cell for m, o in after) or \
               any(m == 'fmuls' and o.split(', ')[1] in ('f4',) and o.split(', ')[2] == cell for m, o in after), hex(site)
        assert any(m == 'lfs' and o.endswith('-0x78bc(r2)') for m, o in after)  # 0.5
        found.append({'site': hex(site), 'buffer': arg.split(', ')[2], 'cell_fpr': cell})
    return found


def stub(base):
    s = p.PPC(base)
    s.d(37, 1, 1, -0x100); s.emit(0x7c0802a6); s.d(36, 0, 1, 0x104)          # stwu, mflr, stw lr
    for r in range(3, 13): s.d(36, r, 1, 0x20 + (r - 3) * 4)
    s.emit(0x7c000026); s.d(36, 0, 1, 0x48)                                  # mfcr r0
    for f in range(14): s.d(54, f, 1, 0x50 + f * 8)                          # stfd f0..f13
    # N = strlen(r5) >> 1 (same count the caller used)
    s.d(14, 6, 5, 0); s.d(14, 7, 0, 0)
    s.label('loop'); s.d(34, 0, 6, 0); s.d(11, 0, 0, 0); s.bc(0x41820000, 'done')
    s.d(14, 6, 6, 1); s.d(14, 7, 7, 1); s.branch(base + s.labels['loop'])   # backward: absolute helper
    s.label('done'); s.emit(21 << 26 | 7 << 21 | 7 << 16 | 31 << 11 | 1 << 6 | 31 << 1)  # srwi r7,r7,1
    s.d(15, 0, 0, 0x4330); s.d(36, 0, 1, 0xc8); s.d(36, 7, 1, 0xcc)
    s.d(50, 2, 1, 0xc8); s.d(50, 3, 2, MAGIC)
    s.emit(63 << 26 | 2 << 21 | 2 << 16 | 3 << 11 | 20 << 1)                 # fsub f2,f2,f3 (= N)
    fmul(s, 2, 2, 4); s.d(54, 2, 1, 0xd0)                                    # N*f4
    s.d(14, 4, 5, 0); s.d(14, 5, 0, 1); v.fmr(s, 1, 4); s.branch(WIDTH_FN, True)
    s.d(50, 2, 1, 0xd0); fop(s, 20, 2, 2, 1)                                 # N*f4 - width
    s.d(48, 0, 2, HALF); fmul(s, 2, 2, 0)
    s.d(50, 3, 1, 0x58); fop(s, 21, 3, 3, 2); s.d(54, 3, 1, 0x58)            # saved f1 += delta
    for f in range(14): s.d(50, f, 1, 0x50 + f * 8)
    s.d(32, 0, 1, 0x48); s.emit(0x7c0ff120)                                  # mtcrf 0xff,r0
    for r in range(3, 13): s.d(32, r, 1, 0x20 + (r - 3) * 4)
    s.d(32, 0, 1, 0x104); s.emit(0x7c0803a6); s.d(14, 1, 1, 0x100); s.branch(PRINTF)
    return s.finish()


def apply(dol, base, size):
    """Append the wrapper at base (end of DOL text section 2) and repoint all sites."""
    dol = bytearray(dol); code = stub(base); assert len(code) <= size
    patches = []
    for site in SITES:
        off = v.offset(dol, site); before = bytes(dol[off:off + 4])
        assert before == v.branch(site, PRINTF)
        dol[off:off + 4] = v.branch(site, base)
        patches.append({'offset': off, 'before': before.hex(), 'after': dol[off:off + 4].hex(), 'reason': 'v08 centering ' + hex(site)})
    payload = code + bytes(size - len(code))
    return dol, payload, patches


def verify(dol, base, mapping, metrics):
    """Run the wrapper on real text: x changes by (N*cell - width)/2; all args preserved."""
    def encode(t): return b''.join(mapping[c].to_bytes(2, 'big') if c in mapping else c.encode('cp932') for c in t)
    cases = []
    for text in ['예', '아니요', 'はい', 'いいえ', '처음부터', '이어서', '불러오기', '저장할 수 없습니다.']:
        for cell in (16.0, 21.0, 24.0, 30.0):
            u = v.cpu(dol, True); raw = encode(text)
            u.mem_write(p.STRING, raw + b'\0')
            regs = {r: 0x11220000 + r for r in range(3, 13)}; regs.update({3: p.OBJECT, 4: 0xffaaffff, 5: p.STRING})
            for r, x in regs.items(): u.reg_write(p.regnum(r), x)
            u.reg_write(p.regnum(1), p.STACK)
            floats = {f: float(f) + 0.125 for f in range(14)}; floats[1] = 200.0; floats[4] = cell; floats[5] = cell
            for f, x in floats.items(): v.fpr_write(u, f, x)
            u.reg_write(p.reg.UC_PPC_REG_CR, 0x02000000)
            u.reg_write(p.reg.UC_PPC_REG_LR, p.STOP)
            u.emu_start(base, PRINTF, count=200000)
            assert u.reg_read(p.reg.UC_PPC_REG_PC) == PRINTF
            n = len(raw) // 2
            punct = {',': 7, '.': 7}   # v06 Gmarket comma/period
            width = sum((next(m['advance'] for m in MAP if m['character'] == c) if c in mapping
                         else punct[c] if c in punct else metrics[c]['raw_advance_px']) for c in text) * cell / 24
            want = 200.0 + (n * cell - width) / 2
            got = v.fpr_read(u, 1); assert abs(got - want) < 1e-4, (text, cell, got, want)
            for r, x in regs.items(): assert u.reg_read(p.regnum(r)) == x, (text, r)
            for f, x in floats.items():
                if f != 1: assert abs(v.fpr_read(u, f) - x) < 1e-9, (text, f)
            assert u.reg_read(p.regnum(1)) == p.STACK and u.reg_read(p.reg.UC_PPC_REG_LR) == p.STOP
            assert (u.reg_read(p.reg.UC_PPC_REG_CR) >> 24) & 0xf == 0x2      # CR1 kept
            cases.append({'text': text, 'cell': cell, 'x': got, 'shift': got - 200.0})
    return cases


MAP = []


def prepare_and_verify(dol, base, size):
    global MAP
    MAP = v.read('translation/full_font_plan.json')['mapping']
    mapping = {m['character']: m['code'] for m in MAP}
    metrics = v.read('metadata/glyph_metrics.json')['metrics']
    sites = check_sites(dol)
    new, payload, patches = apply(dol, base, size)
    return new, payload, patches, sites, mapping, metrics
