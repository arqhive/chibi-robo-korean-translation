"""Gmarket Sans comma and period for one-byte ASCII 0x2c/0x2e.

The space (0x20) stays on the ROM font: the reported "no space" was a
missing space in the translation, not the 5px ROM advance (2026-11-02).

Same two paths as the v03 tilde: the texel provider used by both the dynamic
cache miss (0x801a05e0) and the ASCII preload (0x801a0904), plus immutable
pointers in the v04 lookup. Memory-only preparation and PPC verification.
Never write a game DOL or ISO.
"""
import json
import struct
from PIL import Image, ImageDraw, ImageFont
import prepare_output_probe as p
import prepare_v03_corrections as v
import prepare_v04_font_lifetime as life4
import verify_subtitle_cache_lifetime as life

V04=p.ROOT/'metadata/v04_font_lifetime_verification.json'
V05=p.ROOT/'metadata/integrated_test_build_v05.json'
BASE=0x806a1000  # v04 arena end; the new payload directly follows it
SIZE=0x460
GLYPHS=BASE+0x100
QP_START=5177344
CHARS=[(',',0x2c),('.',0x2e)]
# Fullwidth ，． (used by the 2-byte-only ChibiCom ticker) share the same bitmaps.
FULLWIDTH={0x2c:0x8143,0x2e:0x8144}


# Blank 2-byte spacers with chosen advances (private-use characters in the
# translation). The save prompt 「はい　いいえ」 places its cursor box by six
# 21px cells; 「예아니요」 = 10+20+30+60 px keeps 예 centred in cells
# 0-1 and 아니요 in cells 3-5, exactly where はい/いいえ sat (2026-11-03).
BLANK=GLYPHS+2*288
# 11/03 v10 screenshots: 예 sat ~10px and 아니요 ~18px left of their boxes;
# widths widened from 10/30 to 22/(30+9).
# v15 screenshots: 예 ~8px right of its box, 아니요 ~0-4px right -> 12 / (30+16).
# : shop yes/no lead-in (half of the fullwidth space; v16 shop screenshots ~7-9px right).
SPACERS=[('',0xef40,12),('',0xef41,30),('',0xef42,16),('',0xef43,10)]


def specials(glyphs):
    out=[dict(m) for m in glyphs]+[dict(m,code=FULLWIDTH[m['code']]) for m in glyphs]
    out+=[{'character':c,'code':code,'advance':adv,'address':BLANK,'pixels':bytes(288)} for c,code,adv in SPACERS]
    return out
DYNAMIC,PRELOAD=0x801a05e0,0x801a0904


def load_v05():
    report=v.read('metadata/integrated_test_build_v05.json')
    iso=p.ROOT/report['iso']['path']
    if iso.exists():
        with iso.open('rb') as f:
            f.seek(0x420);disc_offset,=struct.unpack('>I',f.read(4))
            assert disc_offset==report['dol']['offset']
            f.seek(disc_offset);dol=f.read(report['dol']['bytes'])
    else:
        # Latest-build-only retention: v05 parts kept in work/base-v05 by build_v06.
        dol=(p.ROOT/'work/base-v05/main.dol').read_bytes()
    assert p.sha(dol)==report['dol']['sha256']==v.read('metadata/v04_font_lifetime_verification.json')['candidate_dol_sha256']
    return dol,report


def draw():
    font=ImageFont.truetype(str(p.FONT),p.FONT_SIZE);result=[]
    metrics=v.read('metadata/glyph_metrics.json')['metrics']
    for i,(c,code) in enumerate(CHARS):
        canvas=Image.new('L',(72,72));ImageDraw.Draw(canvas).text((24,24+p.BASELINE),c,font=font,fill=255,anchor='ls')
        im=canvas.crop((24,24,48,48));canvas.paste(0,(24,24,48,48));assert canvas.getbbox() is None
        # Gmarket natural advance + 1px, the same rule approved for the Wii port.
        advance=round(font.getlength(c))+1;assert 0<advance<32
        result.append({'character':c,'code':code,'advance':advance,'rom_advance':metrics[c]['raw_advance_px'],
                       'address':GLYPHS+i*288,'bbox':im.getbbox(),'pixels':p.pack_i4(im)})
    return result


def texel_stub(glyphs, fallback):
    # Same contract as the v03 stub: r3 string, r4 destination, r5/r6 call
    # mode, r7 width output. Returns the string pointer after the character.
    s=p.PPC(BASE)
    s.d(11,0,5,0);s.bc(0x40820000,'fallback')
    s.d(11,0,6,6);s.bc(0x40820000,'fallback')
    s.d(34,8,3,0)
    for i,m in enumerate(glyphs):
        s.d(10,0,8,m['code']);s.bc(0x41820000,f'g{i}')
    s.label('fallback');s.branch(fallback)
    for i,m in enumerate(glyphs):
        s.label(f'g{i}');s.load(9,m['address']);s.d(14,0,0,m['advance']);s.bc(0x48000000,'copy')
    s.label('copy');s.d(14,10,4,0);s.d(14,11,0,72);s.emit(0x7d6903a6)
    s.label('loop');s.d(32,12,9,0);s.d(36,12,10,0)
    s.d(14,9,9,4);s.d(14,10,10,4);s.bc(0x42000000,'loop')
    s.d(36,0,7,0);s.d(14,3,3,1);s.emit(0x4e800020) # one byte consumed; blr
    data=s.finish();assert len(data)<=GLYPHS-BASE
    return data


def prepare():
    original,report=load_v05();dol=bytearray(original)
    memory=v.read('metadata/injection_memory_verification.json');v03_texel=memory['payload_end']
    glyphs=draw();entries=life4.mapped(original)
    assert not {m['code'] for m in glyphs}&{m['code'] for m in entries}
    payload=bytearray(SIZE);code=texel_stub(glyphs,v03_texel);payload[:len(code)]=code
    for m in glyphs:
        rel=m['address']-BASE;assert rel+288<=SIZE and m['address']%32==0
        payload[rel:rel+288]=m['pixels']
    patches=[]
    def patch(off,data,expected,reason):
        assert bytes(dol[off:off+len(data)])==expected,(hex(off),reason)
        patches.append({'offset':off,'before':expected.hex(),'after':data.hex(),'reason':reason})
        dol[off:off+len(data)]=data
    def at(addr,data,expected,reason):patch(v.offset(original,addr),data,expected,reason)
    at(DYNAMIC,v.branch(DYNAMIC,BASE),v.branch(DYNAMIC,v03_texel),'dynamic glyph texel: punctuation first')
    at(PRELOAD,v.branch(PRELOAD,BASE),v.branch(PRELOAD,v03_texel),'ASCII preload texel: punctuation first')
    # Rebuild the v04 immutable lookup with three more one-byte special codes.
    old=life4.stub(entries);new=life4.stub(entries+specials(glyphs))
    off=v.offset(original,life4.BASE);assert original[off:off+len(old)]==old and len(new)<=0x400
    at(life4.BASE,new,original[off:off+len(new)],'immutable lookup specials')
    ah=memory['arena_hook'];o=p.PPC(ah);o.load(11,BASE);n=p.PPC(ah);n.load(11,BASE+SIZE)
    at(ah,n.finish(),o.finish(),'extend ArenaLo reservation')
    size=int.from_bytes(original[0x98:0x9c],'big')
    assert int.from_bytes(original[0x50:0x54],'big')+size==BASE
    assert int.from_bytes(original[8:12],'big')+size==len(original)
    patch(0x98,v.word(size+SIZE),v.word(size),'extend DOL text section 2')
    dol.extend(payload)
    assert report['dol']['offset']+len(dol)<=QP_START
    reverse=bytearray(dol[:len(original)])
    for x in patches:reverse[x['offset']:x['offset']+len(bytes.fromhex(x['before']))]=bytes.fromhex(x['before'])
    assert bytes(reverse)==original
    return bytes(dol),original,report,glyphs,entries,patches


def width(u,raw,size):
    u.mem_write(p.STRING,raw+b'\0')
    for r,x in {1:p.STACK,3:p.OBJECT,4:p.STRING,5:1}.items():u.reg_write(p.regnum(r),x)
    v.fpr_write(u,1,size);v.call(u,v.WIDTH_FN);return v.fpr_read(u,1)


def verify(data):
    dol,original,report,glyphs,entries,_=data
    memory=v.read('metadata/injection_memory_verification.json')
    # 1) Immutable lookup: new specials, and every previous glyph unchanged.
    u=v.cpu(dol);old=v.cpu(original)
    for m in glyphs:
        ptr,w=life.lookup(u,m['code'])
        assert ptr==m['address'] and w==m['advance'] and bytes(u.mem_read(ptr,288))==m['pixels']
    for m in entries:
        ptr,w=life.lookup(u,m['code']);assert ptr==m['address'] and w==m['advance']
        assert bytes(u.mem_read(ptr,288))==m['pixels']
    # 2) Other ASCII/Japanese fallbacks render exactly as v05.
    for m in specials(glyphs)[len(glyphs):]:
        ptr,w=life.lookup(u,m['code']);assert ptr==m['address'] and w==m['advance']
    samples=[ord(c) for c in ' A0!?-:;()"\'']+[0x82a0,0x8341,0x8140,0x8149,0x8148,0x8160,0x8142,0x8141]
    for code in samples:
        a,aw=life.lookup(u,code);b,bw=life.lookup(old,code)
        assert aw==bw and bytes(u.mem_read(a,288))==bytes(old.mem_read(b,288)),hex(code)
    # 3) Real texel callsites. Preload: ',A' consumes one byte and writes our
    # glyph; dynamic: same stub, falls through to v03 tilde/Korean otherwise.
    texel=[]
    for site in (PRELOAD,DYNAMIC):
        for m in glyphs:
            u=v.cpu(dol);u.mem_write(p.STRING,bytes([m['code']])+b'A\0');u.mem_write(p.DEST,bytes(320))
            for r,x in {1:p.STACK,3:p.STRING,4:p.DEST,5:0,6:6,7:p.WIDTH}.items():u.reg_write(p.regnum(r),x)
            v.call(u,site,site+4)
            assert u.reg_read(p.regnum(3))==p.STRING+1 and bytes(u.mem_read(p.DEST,288))==m['pixels']
            assert int.from_bytes(u.mem_read(p.WIDTH,4),'big')==m['advance']
            texel.append({'site':hex(site),'character':m['character']})
        for c in '~A':
            u=v.cpu(dol);w=v.cpu(original)
            for cpu in (u,w):
                cpu.mem_write(p.STRING,c.encode()+b'\0');cpu.mem_write(p.DEST,bytes(320))
                for r,x in {1:p.STACK,3:p.STRING,4:p.DEST,5:0,6:6,7:p.WIDTH}.items():cpu.reg_write(p.regnum(r),x)
                v.call(cpu,site,site+4)
            assert u.reg_read(p.regnum(3))==w.reg_read(p.regnum(3))
            assert bytes(u.mem_read(p.DEST,288))==bytes(w.mem_read(p.DEST,288))
            assert u.mem_read(p.WIDTH,4)==w.mem_read(p.WIDTH,4)
    # 4) Real width function on translated lines.
    mapping={m['character']:m for m in v.read('translation/full_font_plan.json')['mapping']}
    def encode(t):return b''.join(mapping[c]['code'].to_bytes(2,'big') if c in mapping else c.encode('cp932') for c in t)
    metrics=v.read('metadata/glyph_metrics.json')['metrics'];adv={m['character']:m['advance'] for m in glyphs}
    widths=[]
    u=v.cpu(dol,True)
    for text in ['저 톤피와, 안녕.','처음부터 시작하는 데이터를 만듭니다.','그런데, 마메랑 오야지 중에']:
        for size in (16.,24.):
            got=width(u,encode(text),size)
            exp=sum(adv[c] if c in adv else mapping[c]['advance'] if c in mapping else metrics[c]['raw_advance_px'] for c in text)*size/24
            assert abs(got-exp)<1e-4,(text,got,exp);widths.append({'text':text,'size':size,'width':got})
    # 5) ArenaLo guard moves to the new end.
    u=v.cpu(dol);ah=memory['arena_hook'];end=BASE+SIZE
    for requested in [life4.BASE,BASE-32,BASE,end-32,end,end+32,0x81000000]:
        u.reg_write(p.regnum(3),requested);v.call(u,ah)
        assert int.from_bytes(u.mem_read(p.R13-0x72f0,4),'big')==max(requested,end)
    return {'new_glyphs':[{k:m[k] for k in ('character','code','advance','rom_advance')}|{'address':hex(m['address']),'bbox':m['bbox']} for m in glyphs],
            'fullwidth_aliases':[hex(c) for c in FULLWIDTH.values()],'previous_immutable_glyphs_unchanged':len(entries),'fallback_cases_equal_v05':len(samples),
            'texel_callsites':texel,'width_cases':widths,'arena_cases':7}


def line_impact(glyphs):
    """Widen-only impact on applied lines, against the existing ROM-width model."""
    metrics=v.read('metadata/glyph_metrics.json')['metrics'];mapping={m['character']:m for m in v.read('translation/full_font_plan.json')['mapping']}
    extra={m['character']:m['advance']-m['rom_advance'] for m in glyphs}
    rows=[(e['id'],e['translation']) for e in v.read('translation/text_catalog.json')
          if e.get('translation') and e.get('selection') in (None,'hold_dol_reference_binding')]
    over={r['id']:r['translation'] for r in v.read('translation/text_additions_v06.json')['records']}
    rows=[(i,over.get(i,t)) for i,t in rows]+[(i,t) for i,t in over.items() if i not in dict(rows)]
    import re
    def lw(line):
        return sum(mapping[c]['advance'] if c in mapping else metrics[c]['raw_advance_px'] if c in metrics else 20 for c in line)
    before=[];after=[]
    for i,t in rows:
        for line in re.sub(r'<\d+>','',t).split('\n'):
            b=lw(line);before.append((b,i));after.append((b+sum(extra.get(c,0) for c in line),i,line))
    old_max=max(before)[0]
    widened=sum(1 for (b,_),(a,_,_) in zip(before,after) if a>b)
    beyond=sorted([x for x in after if x[0]>old_max],reverse=True)
    return {'lines':len(after),'widened_lines':widened,'previous_max_raw_px':old_max,
            'lines_beyond_previous_max':[{'id':i,'raw_px':a,'text':l} for a,i,l in beyond]}


def main():
    data=prepare();checks=verify(data);dol,original,report,glyphs,entries,patches=data
    impact=line_impact(glyphs)
    out=p.ROOT/'work/runtime-corrections/v06';out.mkdir(parents=True,exist_ok=True)
    recipe={'base_dol_sha256':p.sha(original),'expected_dol_sha256':p.sha(dol),'base_dol_bytes':len(original),
            'new_dol_bytes':len(dol),'disc_offset':report['dol']['offset'],'patches':patches,'append_hex':dol[len(original):].hex()}
    p.save(out/'punctuation-recipe.json',recipe)
    p.save(p.ROOT/'metadata/v06_punctuation_verification.json',{
        'authorization':'2026-11-02 사용자: 2번까지만 하자 일단 (쉼표·마침표 글자, 빌드 없음). 공백은 같은 날 오진으로 확인되어 ROM 글꼴 유지',
        'source_build_sha256':report['iso']['sha256'],'base_dol_sha256':p.sha(original),'candidate_dol_sha256':p.sha(dol),
        'recipe':'work/runtime-corrections/v06/punctuation-recipe.json','recipe_sha256':p.sha((out/'punctuation-recipe.json').read_bytes()),
        'new_arena_end':hex(BASE+SIZE),'additional_bytes_over_v05':len(dol)-len(original),
        'remaining_gap_before_qp_bytes':QP_START-report['dol']['offset']-len(dol),
        'checks':checks,'line_impact':impact,'new_iso_built':False,'runtime_fix_verified':False,
        'limits':['Real PPC lookup, texel callsites and width function; no GPU rendering.',
                  'Line widths use the existing common model; window links remain unresolved.',
                  'Dolphin/real-hardware screen confirmation remains required.']})
    print('PASS: glyphs',[(m['character'],m['advance']) for m in glyphs],'arena end',hex(BASE+SIZE),
          'gap left',QP_START-report['dol']['offset']-len(dol))
    print('PASS: previous glyphs unchanged',len(entries),'; widened lines',impact['widened_lines'],
          '; beyond previous max',len(impact['lines_beyond_previous_max']),'; no ISO written')


if __name__=='__main__':main()
