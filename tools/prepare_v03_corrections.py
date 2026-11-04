"""Prepare and CPU-check v02 UI fixes IN MEMORY. Never write a DOL or ISO.

Keep the approved v02 catalog, encoding and build recipe unchanged. The supplemental
translation file and this additive recipe form the next build's correction layer.
"""
import json
import struct
from PIL import Image, ImageDraw, ImageFont
from unicorn import UC_HOOK_CODE
import prepare_output_probe as p
from build_output_probe import sections
from measure_message_windows import R2, fpr_write, fpr_read
from check_text_layout import measure
from translation_tokens import translated_tokens

ROOT = p.ROOT
OUT = ROOT / 'work/runtime-corrections/v03'
PRINTF, WIDTH_FN = 0x80198270, 0x801984fc
FOOTERS = [0x80032970,0x800329e8,0x80032a68,0x80032ae8,0x80032b68,0x80032be8,
    0x80032c68,0x80032ce0,0x80032d5c,0x80032e14,0x80032e8c,0x80032f08,
    0x80032f88,0x80033000,0x80033080,0x800330f8,0x80033174,0x800331f4,
    0x80033274,0x800332ec,0x8003336c,0x800333e4,0x8003349c,0x80033514,
    0x800335c0,0x80033644,0x800336c0,0x80033748,0x800337c4]


def read(name): return json.loads((ROOT/name).read_text('utf-8'))
def word(v): return struct.pack('>I', v)
def branch(a, b, link=True):
    s=p.PPC(a);s.branch(b,link);return s.finish()
def offset(dol, address):
    sec=next(s for s in sections(dol) if s['ram_address']<=address<s['ram_address']+s['size'])
    return sec['file_offset']+address-sec['ram_address']


def font_stub(base, bitmap, mapping, fallback):
    s=p.PPC(base)
    s.d(11,0,5,0);s.bc(0x40820000,'fallback')
    s.d(11,0,6,6);s.bc(0x40820000,'fallback')
    s.d(34,8,3,0);s.d(10,0,8,0x7e);s.bc(0x41820000,'g0')
    s.d(28,8,9,0x80);s.bc(0x41820000,'fallback')
    s.emit(0x5508402e);s.d(34,9,3,1);s.emit(0x7d084b78)
    for i,m in enumerate(mapping[1:],1):
        s.d(10,0,8,m['code']);s.bc(0x41820000,f'g{i}')
    s.label('fallback');s.branch(fallback)
    for i,m in enumerate(mapping):
        s.label(f'g{i}');s.load(9,bitmap+288*i);s.d(14,0,0,m['advance'])
        s.d(14,8,0,1 if i==0 else 2);s.bc(0x48000000,'copy')
    s.label('copy');s.d(14,10,4,0);s.d(14,11,0,72);s.emit(0x7d6903a6)
    s.label('loop');s.d(32,12,9,0);s.d(36,12,10,0)
    s.d(14,9,9,4);s.d(14,10,10,4);s.bc(0x42000000,'loop')
    s.d(36,0,7,0);s.emit(0x7c634214);s.emit(0x4e800020) # add r3,r3,r8; blr
    return s.finish()


def count_stub(base):
    # Return twice the SJIS character count to the existing /2 caller.
    # Halfwidth kana are single-byte. Only valid SJIS lead ranges consume two.
    s=p.PPC(base);s.d(14,4,3,0);s.d(14,3,0,0)
    s.label('loop');s.d(34,5,4,0);s.d(11,0,5,0);s.bc(0x41820000,'done')
    s.d(14,3,3,2);s.d(14,4,4,1)
    s.d(10,0,5,0x81);s.bc(0x41800000,'loop')
    s.d(10,0,5,0x9f);s.bc(0x40810000,'lead')
    s.d(10,0,5,0xe0);s.bc(0x41800000,'loop')
    s.d(10,0,5,0xfc);s.bc(0x41810000,'loop')
    s.label('lead');s.d(34,5,4,0);s.d(11,0,5,0);s.bc(0x41820000,'done')
    s.d(14,4,4,1);s.branch(base+s.labels['loop'])
    s.label('done');s.emit(0x4e800020);return s.finish()


def fmr(s, d, b): s.emit(0xfc000090 | d<<21 | b<<11)
def fop(s, xo, d, a, b): s.emit(59<<26 | d<<21 | a<<16 | b<<11 | xo<<1)
def fmul(s,d,a,c): s.emit(59<<26 | d<<21 | a<<16 | c<<6 | 25<<1)


def center_stub(base, anchor):
    # These callers pass already formatted text. Preserve printf's varargs GPRs,
    # FPRs and CR1. Their old (n-1)*cell/2 formula anchors the first cell's center.
    s=p.PPC(base);s.d(37,1,1,-0x100);s.emit(0x7c0802a6);s.d(36,0,1,0x104)
    for r in range(3,13): s.d(36,r,1,0x20+(r-3)*4)
    s.emit(0x7c000026);s.d(36,0,1,0x48)
    for f in range(14): s.d(54,f,1,0x50+f*8)
    s.d(48,0,2,-0x48a4);fmul(s,0,4,0);fop(s,21,0,anchor,0);s.d(54,0,1,0xc0)
    s.d(14,4,5,0);s.d(14,5,0,1);fmr(s,1,4);s.branch(WIDTH_FN,True)
    s.d(48,0,2,-0x48a4);fmul(s,1,1,0);s.d(50,0,1,0xc0);fop(s,20,1,0,1)
    for f in [0,*range(2,14)]: s.d(50,f,1,0x50+f*8)
    s.d(32,0,1,0x48);s.emit(0x7c0ff120)
    for r in range(3,13): s.d(32,r,1,0x20+(r-3)*4)
    s.d(32,0,1,0x104);s.emit(0x7c0803a6);s.d(14,1,1,0x100);s.branch(PRINTF)
    return s.finish()


def load_base():
    report=read('metadata/integrated_test_build_v02.json')
    assert p.sha((ROOT/'translation/text_catalog.json').read_bytes())==report['catalog_sha256']
    assert p.sha((ROOT/'metadata/build_scope_proposal.json').read_bytes())==report['scope_sha256']
    source=ROOT/report['iso']['path']
    if source.exists():
        with source.open('rb') as f:
            f.seek(0x420);disc_offset,fst_offset,fst_size=struct.unpack('>3I',f.read(12))
            assert fst_offset+fst_size<=disc_offset
            f.seek(disc_offset);dol=f.read(report['dol']['bytes'])
    else:
        # Latest-build-only retention: reconstruct the base DOL in memory.
        from verify_integrated_layout import assemble_dol
        dol,_=assemble_dol(read('metadata/disc_inventory_jp.json'))
        disc_offset=report['iso']['placement']['dol_offset']
    assert p.sha(dol)==report['dol']['sha256']
    return dol,report,disc_offset


def prepare():
    original,build,disc_offset=load_base();dol=bytearray(original)
    memory=read('metadata/injection_memory_verification.json');base=memory['payload_end']
    oldmap=read('translation/full_font_plan.json')['mapping'];mapping={x['character']:x for x in oldmap}
    rows=read('translation/ui_corrections_v03.json')['records']
    newchars=sorted({c for r in rows for c in r['translation'] if '\uac00'<=c<='\ud7a3'}-mapping.keys())
    assert newchars==['삭','켬']
    sourcechars={c for r in read('translation/text_catalog.json') for t in r['tokens'] if t['kind']=='text' for c in t['source']}
    used={x['code'] for x in oldmap}
    codes=[h*256+l for h in range(0xf0,0xfa) for l in range(0x40,0xfd) if l!=0x7f
           and h*256+l not in used and bytes([h,l]).decode('cp932') not in sourcechars]
    font=ImageFont.truetype(str(p.FONT),p.FONT_SIZE)
    additions=[{'character':'~','code':0x7e,'advance':round(font.getlength('~'))}]
    additions += [{'character':c,'code':codes[i],'advance':p.ADVANCE} for i,c in enumerate(newchars)]
    glyphs=[]
    for m in additions:
        canvas=Image.new('L',(72,72));ImageDraw.Draw(canvas).text((24,24+p.BASELINE),m['character'],font=font,fill=255,anchor='ls')
        im=canvas.crop((24,24,48,48));canvas.paste(0,(24,24,48,48));assert canvas.getbbox() is None
        glyphs.append(p.pack_i4(im));m['bbox']=im.getbbox();mapping[m['character']]=m
    def encode(text):
        return b''.join(mapping[c]['code'].to_bytes(1 if c=='~' else 2,'big') if c in mapping else c.encode('cp932') for c in text)
    payload=bytearray(4096)
    def put(rel,data,limit):
        assert len(data)<=limit;payload[rel:rel+len(data)]=data
    put(0,font_stub(base,base+0x800,additions,memory['payload_start']),0x200)
    put(0x200,center_stub(base+0x200,29),0x200)
    put(0x400,center_stub(base+0x400,7),0x200)
    put(0x600,count_stub(base+0x600),0x200)
    put(0x800,b''.join(glyphs),0x400)
    patches=[]
    def patch(off,data,expected,reason):
        assert bytes(dol[off:off+len(data)])==expected,(hex(off),reason)
        patches.append({'offset':off,'before':expected.hex(),'after':data.hex(),'reason':reason})
        dol[off:off+len(data)]=data
    def at(addr,data,expected,reason): patch(offset(original,addr),data,expected,reason)
    original_sections=sections(p.DOL.read_bytes());cursor=0xc00
    for r in rows:
        oldraw=bytes.fromhex(r['original_hex'])
        assert original[r['offset']:r['offset']+len(oldraw)]==oldraw
        raw=encode(r['translation'])+b'\0';assert cursor+len(raw)<=len(payload)
        payload[cursor:cursor+len(raw)]=raw
        for ref in r['references']:
            oldsec=next(s for s in original_sections if s['file_offset']<=r['offset']<s['file_offset']+s['size'])
            oldaddr=oldsec['ram_address']+r['offset']-oldsec['file_offset']
            patch(ref['file_offset'],word(base+cursor),word(oldaddr),r['id']+' '+r['translation'])
        cursor+=len(raw)
    at(0x801a05e0,branch(0x801a05e0,base),branch(0x801a05e0,memory['payload_start']),'dynamic glyph hook')
    at(0x801a0904,branch(0x801a0904,base),branch(0x801a0904,p.GET_TEXEL),'ASCII/preload glyph hook')
    at(0x80036b88,branch(0x80036b88,base+0x600),branch(0x80036b88,0x8015ab20),'empty slot character count')
    for addr in FOOTERS+[0x8003737c]:
        at(addr,branch(addr,base+(0x400 if addr==0x8003737c else 0x200)),branch(addr,PRINTF),'footer actual-advance centering')
    ah=memory['arena_hook'];old=p.PPC(ah);old.load(11,base);new=p.PPC(ah);new.load(11,base+len(payload))
    at(ah,new.finish(),old.finish(),'extend ArenaLo reservation')
    size=int.from_bytes(original[0x98:0x9c],'big')
    assert int.from_bytes(original[0x50:0x54],'big')+size==base
    assert int.from_bytes(original[8:12],'big')+size==len(original)
    patch(0x98,word(size+len(payload)),word(size),'extend DOL text section 2')
    dol.extend(payload)
    # Exact reversal proves that no unlisted bytes in the base DOL changed.
    reverse=bytearray(dol[:len(original)])
    for x in patches:reverse[x['offset']:x['offset']+len(bytes.fromhex(x['before']))]=bytes.fromhex(x['before'])
    assert bytes(reverse)==original
    sections(dol) # Header parser checks are supplemented by RAM/disk bounds below.
    return bytes(dol),original,base,rows,additions,glyphs,mapping,encode,patches,bytes(payload),build,disc_offset


def cpu(dol, width_fixture=False):
    u=p.create_cpu(dol,{'dol':{'sections':sections(dol)}},p.yay0(p.ROMFONT.read_bytes()))
    u.reg_write(p.regnum(2),R2);u.reg_write(p.reg.UC_PPC_REG_MSR,0x2000)
    u.mem_write(p.CACHE,bytes(50*320));u.mem_write(p.R13-0x6660,word(p.CACHE))
    u.mem_write(p.R13-0x6664,word(p.FONT_RAM))
    u.mem_write(p.OBJECT+0x24,word(24))
    def trace(c,pc,size,_):
        ins=int.from_bytes(c.mem_read(pc,4),'big')
        # Unicorn does not implement Gekko paired-single spills; scalar stfd/lfd
        # alongside them preserve the FPR values used by these width routines.
        if ins>>26 in (56,60) and (ins>>16)&31==1:
            c.reg_write(p.reg.UC_PPC_REG_PC,pc+4)
        elif pc==0x80164b9c:
            assert ins==0x44000002;c.reg_write(p.reg.UC_PPC_REG_PC,pc+4)
        elif width_fixture and pc==0x801a0674:
            # Width/key/bitmap/cache paths are real. Bypass only subsequent GX
            # texture/matrix setup, then use the real getGlyph output/epilogue.
            c.reg_write(p.reg.UC_PPC_REG_PC,0x801a0700)
    u.hook_add(UC_HOOK_CODE,trace);return u


def call(u,address,stop=p.STOP,count=1000000):
    u.reg_write(p.reg.UC_PPC_REG_LR,p.STOP);u.emu_start(address,stop,count=count)
    assert u.reg_read(p.reg.UC_PPC_REG_PC)==stop,hex(u.reg_read(p.reg.UC_PPC_REG_PC))


def verify(data):
    dol,original,base,rows,additions,glyphs,mapping,encode,patches,payload,build,disc_offset=data
    u=cpu(dol);oldmap=read('translation/full_font_plan.json')['mapping'];oldglyphs=(ROOT/'work/full-font/glyphs.i4').read_bytes()
    for i,m in enumerate(oldmap):
        got,width,used=p.texel(u,base,m['code'].to_bytes(2,'big'))
        assert got[:288]==oldglyphs[i*288:(i+1)*288] and width==m['advance'] and used==2
    for m,g in zip(additions,glyphs):
        got,width,used=p.texel(u,base,encode(m['character']))
        assert got[:288]==g and width==m['advance'] and used==len(encode(m['character']))
        assert got[288:]==b'\xa5'*(2048-288)
    for c in ['A','0','!','?',' ','は','亜']:
        for x,stride in [(0,6),(2,8)]:
            assert p.texel(u,base,c.encode('cp932'),x,stride)==p.texel(u,p.GET_TEXEL,c.encode('cp932'),x,stride)
    # All relocated pointer values and the actual shared UI getter.
    refs=0;getters=0
    for r in rows:
        encoded=encode(r['translation'])+b'\0'
        for ref in r['references']:
            addr=int.from_bytes(dol[ref['file_offset']:ref['file_offset']+4],'big')
            assert bytes(u.mem_read(addr,len(encoded)))==encoded;refs+=1
            if 'menu_index' in ref:
                u.reg_write(p.regnum(3),ref['menu_index']);call(u,0x8006fff0)
                assert u.reg_read(p.regnum(3))==addr;getters+=1
    # Original strings for held candidates stay untouched, including references.
    for r in read('metadata/v02_ui_diagnosis.json')['missing_labels']:
        if r['translation_proposal'] is not None:continue
        assert dol[r['offset']:r['end']]==original[r['offset']:r['end']]
        for ref in r['references']:
            off=ref['file_offset'];assert dol[off:off+4]==original[off:off+4]
    count_cases=['','A','ABC','비어 있음','からっぽ','ｶﾅ','한 A 글','우호호~이.']
    for text in count_cases:
        raw=encode(text);u.mem_write(p.STRING+1,raw+b'\0');u.reg_write(p.regnum(3),p.STRING+1)
        call(u,base+0x600);assert u.reg_read(p.regnum(3))==len(text)*2
    u.mem_write(p.STRING,encode('비어 있음')+b'\0');u.reg_write(p.regnum(3),p.STRING)
    call(u,0x80036b88,0x80036b90)
    assert u.reg_read(p.regnum(3))==5 # actual patched call AND existing srwi
    # Real dynamic cache miss and hit, including one-byte tilde cache key.
    u=cpu(dol);hits={'hook':0}
    u.hook_add(UC_HOOK_CODE,lambda c,pc,size,d: hits.__setitem__('hook',hits['hook']+1) if pc==base else None)
    def cache_get(text):
        u.mem_write(p.STRING,encode(text)+b'\0')
        for r,v in {1:p.STACK,3:p.OBJECT,4:p.STRING,5:p.WIDTH}.items():u.reg_write(p.regnum(r),v)
        call(u,0x801a0448,0x801a0674)
        sp=u.reg_read(p.regnum(1));return int.from_bytes(u.mem_read(sp+0x14,4),'big'),int.from_bytes(u.mem_read(sp+8,4),'big')
    for m,g in zip(additions,glyphs):
        ptr,width=cache_get(m['character']);assert bytes(u.mem_read(ptr,288))==g and width==m['advance']
        before=hits['hook'];assert cache_get(m['character'])==(ptr,width) and hits['hook']==before
    # Execute the actual patched preload callsite with its real call arguments,
    # then install that entry at the proper index of an ASCII preloaded table.
    u.mem_write(p.STRING,b'~A\0');u.mem_write(p.DEST,bytes(320))
    for r,v in {1:p.STACK,3:p.STRING,4:p.DEST,5:0,6:6,7:p.WIDTH}.items():u.reg_write(p.regnum(r),v)
    call(u,0x801a0904,0x801a0908)
    assert u.reg_read(p.regnum(3))==p.STRING+1 and bytes(u.mem_read(p.DEST,288))==glyphs[0]
    preloaded=0x81930000;entry=preloaded+(0x7e-0x20)*320
    u.mem_write(0x802370a0,word(preloaded));u.mem_write(entry,glyphs[0]+struct.pack('>HH',0x7e,additions[0]['advance'])+bytes(28))
    before=hits['hook'];assert cache_get('~')==(entry,additions[0]['advance']) and hits['hook']==before
    # Real width computation, with only post-glyph GX setup skipped (above).
    u=cpu(dol,True);metrics=read('metadata/glyph_metrics.json')['metrics'];width_results=[]
    texts=['비어 있음','처음부터 시작하는 데이터를 만듭니다.','파일을 선택해 주세요.','우호호~이.','ABC 123','からっぽ']
    for size in (16.,21.,32.):
        for text in texts:
            raw=encode(text);u.mem_write(p.STRING,raw+b'\0')
            for r,v in {1:p.STACK,3:p.OBJECT,4:p.STRING,5:1}.items():u.reg_write(p.regnum(r),v)
            fpr_write(u,1,size);call(u,WIDTH_FN)
            expected=sum(mapping[c]['advance'] if c in mapping else metrics[c]['raw_advance_px'] for c in text)*size/24
            actual=fpr_read(u,1);assert abs(expected-actual)<0.0001,(text,expected,actual)
            width_results.append({'text':text,'size':size,'width':actual})
            # The wrapper must preserve all printf arguments and CR1, changing x only.
            for rel,anchor in [(0x200,29),(0x400,7)]:
                regs={r:0x11220000+r for r in range(3,13)};regs.update({3:p.OBJECT,4:0xffaaffff,5:p.STRING})
                for r,v in regs.items():u.reg_write(p.regnum(r),v)
                u.reg_write(p.regnum(1),p.STACK)
                floats={f:float(f)+0.125 for f in range(32)};floats[4]=size;floats[5]=size;floats[anchor]=320.
                for f,v in floats.items():fpr_write(u,f,v)
                u.reg_write(p.reg.UC_PPC_REG_CR,0x12345678)
                call(u,base+rel,PRINTF)
                assert abs(fpr_read(u,1)-(320+size/2-actual/2))<0.0001
                assert all(u.reg_read(p.regnum(r))==v for r,v in regs.items())
                assert all(fpr_read(u,f)==v for f,v in floats.items() if f!=1)
                assert u.reg_read(p.reg.UC_PPC_REG_CR)==0x12345678
                assert u.reg_read(p.regnum(1))==p.STACK and u.reg_read(p.reg.UC_PPC_REG_LR)==p.STOP
    mem=read('metadata/injection_memory_verification.json');end=base+len(payload)
    u=cpu(dol)
    for requested in [mem['payload_start']-32,base-32,base,end-32,end,end+32,0x81000000]:
        u.reg_write(p.regnum(3),requested);call(u,mem['arena_hook'])
        assert int.from_bytes(u.mem_read(p.R13-0x72f0,4),'big')==max(requested,end)
    sec=sections(dol)
    for i,s in enumerate(sec):
        for t in sec[i+1:]:assert max(s['ram_address'],t['ram_address'])>=min(s['ram_address']+s['size'],t['ram_address']+t['size'])
    qp_offset=build['iso']['placement']['qp_offset']
    assert disc_offset+len(dol)<=qp_offset # retain FST/file layout
    assert p.sha(load_base()[0])==p.sha(original)
    return {'old_glyphs_unchanged_cpu':len(oldmap),'new_glyphs_direct_and_cache':len(additions),
        'preloaded_ascii_tilde':True,'ui_records':len(rows),'pointer_readbacks':refs,'real_menu_getter_checks':getters,
        'sjis_count_cases':len(count_cases),'centering_wrapper_cases':len(width_results)*2,
        'width_cpu_results':width_results,'arena_cases':7,'base_dol_unchanged':True,
        'bytes_added':len(payload),'remaining_before_qp':qp_offset-disc_offset-len(dol)}


def layout_impact(additions):
    old=read('translation/full_font_plan.json')['metrics']
    new=dict(old)
    new['~']={**old['~'],'raw_advance_px':additions[0]['advance']}
    scope=read('metadata/build_scope_proposal.json')['record_ids_by_bucket']
    ids=set(scope['script_test_candidate']+scope['metadata_test_candidate']+scope['ui_test_candidate_runtime_unverified'])
    profiles={r['id']:r for r in read('translation/window_profiles.json')['profiles']}
    comparisons=[]
    for row in read('translation/text_catalog.json'):
        if row['id'] not in ids or '~' not in (row.get('translation') or ''):continue
        tokens=[dict(t,hex=t.get('hex','')) for t in translated_tokens(row)]
        profile=profiles.get(row.get('window') or row.get('window_id'))
        before=measure(tokens,old,profile);after=measure(tokens,new,profile)
        comparisons.append({'id':row['id'],'before_max_width':before['max_line_width_px'],
            'after_max_width':after['max_line_width_px'],
            'new_conditional_risks':sorted(set(after['conditional_risks'])-set(before['conditional_risks'])),
            'new_confirmed_overflow':before['passes_window_limits'] is not False and after['passes_window_limits'] is False,
            'window_fit':after['passes_window_limits']})
    assert len(comparisons)==960
    p.save(OUT/'tilde-layout-impact.json',comparisons)
    return {'affected_records':len(comparisons),'old_advance':old['~']['raw_advance_px'],
        'new_advance':new['~']['raw_advance_px'],
        'new_conditional_risks':[r for r in comparisons if r['new_conditional_risks']],
        'new_confirmed_overflows':[r['id'] for r in comparisons if r['new_confirmed_overflow']],
        'unconfirmed_window_fits':sum(r['window_fit'] is None for r in comparisons)}


def main():
    data=prepare();results=verify(data)
    dol,original,base,rows,additions,glyphs,mapping,encode,patches,payload,build,disc_offset=data
    OUT.mkdir(parents=True,exist_ok=True)
    results['tilde_layout_impact']=layout_impact(additions)
    # Recipe only: no executable/disc is emitted. Subsequent explicit build can
    # apply the guarded patches, append payload and verify this expected hash.
    recipe={'base_dol_sha256':p.sha(original),'expected_dol_sha256':p.sha(dol),'base_dol_bytes':len(original),
        'patches':patches,'append_hex':payload.hex(),'disc_offset':disc_offset,'new_dol_bytes':len(dol)}
    source=ROOT/build['iso']['path']
    if not source.exists():
        # v02 never modified the slack immediately after its DOL.
        source=ROOT/next(x['path'] for x in read('metadata/originals.json')['files'] if x['edition']=='jp')
    with source.open('rb') as f:
        f.seek(disc_offset+len(original));gap=f.read(len(payload))
    assert len(gap)==len(payload)
    recipe['disc_append_before_sha256']=p.sha(gap)
    p.save(OUT/'recipe.json',recipe)
    p.save(ROOT/'metadata/v03_corrections_verification.json',{
        'source_build_sha256':build['iso']['sha256'],'supplement_sha256':p.sha((ROOT/'translation/ui_corrections_v03.json').read_bytes()),
        'recipe_sha256':p.sha((OUT/'recipe.json').read_bytes()),'candidate_dol_sha256':p.sha(dol),
        'payload_address':hex(base),'font_additions':additions,'patch_count':len(patches),'checks':results,
        'new_iso_built':False,'runtime_fix_verified':False,
        'limits':['CPU fixture skips cache-flush syscall and Gekko paired-single stack spills.',
            'Width tests bypass post-glyph GX texture/matrix setup; no GPU rendering or hardware validation.',
            'Centering retains original half-cell anchor convention; optical appearance requires Dolphin confirmation.',
            'Private codes checked against extracted source, not all possible runtime data.',
            'Only identified save-slot and footer callers are corrected; other UI layouts remain subject to play testing.']})
    print(json.dumps(results,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
