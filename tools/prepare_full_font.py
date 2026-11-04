"""Full translation font in synthetic PPC RAM only. No DOL/ISO writes.

Private-use SJIS slots are a candidate allocation, not a proof of absence in
unextracted strings. Font-cache tests use real JP instructions before GX drawing.
"""
import json,struct,hashlib
from collections import Counter
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from fontTools.ttLib import TTFont
from unicorn import UC_HOOK_CODE
import prepare_output_probe as p
from translation_tokens import translated_tokens
from check_text_layout import measure,oracle_check
ROOT=p.ROOT
OUT=ROOT/'work/full-font'
BASE=0x81800000
BITMAPS=0x81810000

def make_stub(mapping,base=BASE,bitmaps=BITMAPS):
    s=p.PPC(base)
    s.d(11,0,5,0);s.bc(0x40820000,'fallback')
    s.d(11,0,6,6);s.bc(0x40820000,'fallback')
    s.d(34,8,3,0);s.d(28,8,9,0x80);s.bc(0x41820000,'fallback')
    s.emit(0x5508402e);s.d(34,9,3,1);s.emit(0x7d084b78)
    for i,m in enumerate(mapping):s.d(10,0,8,m['code']);s.bc(0x41820000,f'g{i}')
    s.label('fallback');s.branch(p.GET_TEXEL)
    for i,m in enumerate(mapping):
        s.label(f'g{i}');s.load(9,bitmaps+i*288);s.d(14,0,0,m['advance']);s.bc(0x48000000,'copy')
    s.label('copy');s.d(14,10,4,0);s.d(14,11,0,72);s.emit(0x7d6903a6)
    s.label('loop');s.d(32,12,9,0);s.d(36,12,10,0);s.d(14,9,9,4);s.d(14,10,10,4);s.bc(0x42000000,'loop')
    s.d(36,0,7,0);s.d(14,3,3,2);s.emit(0x4e800020)
    code=s.finish();assert base+len(code)<bitmaps
    return code

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    catalog=ROOT/'translation/text_catalog.json';catalog_hash=p.sha(catalog.read_bytes());rows=json.loads(catalog.read_text(encoding='utf-8'))
    allchars=set(c for r in rows if r.get('translation') is not None for t in translated_tokens(r) if t['kind']=='text' for c in t['source'])
    originalchars=set(c for r in rows for t in r['tokens'] if t['kind']=='text' for c in t['source'])
    required=sorted(c for c in allchars if '\uac00'<=c<='\ud7a3' or c=='·')
    old=json.loads((ROOT/'translation/output_probe.json').read_text(encoding='utf-8'))['mapping']
    oldcodes={r['hangul']:int(r['sjis_code'],16) for r in old}
    udc=[h*256+l for h in range(0xf0,0xfa) for l in range(0x40,0xfd) if l!=0x7f and bytes([h,l]).decode('cp932') not in originalchars]
    assert not any(code.to_bytes(2,'big').decode('cp932') in originalchars for code in udc)
    cmap=TTFont(p.FONT).getBestCmap();font=ImageFont.truetype(str(p.FONT),p.FONT_SIZE)
    mapping=[];glyphs=[];clipped=[];ui=0
    sheet=Image.new('RGB',(32*32,((len(required)+31)//32)*40),'#e7e3d7');draw=ImageDraw.Draw(sheet)
    for i,c in enumerate(required):
        assert ord(c) in cmap,c
        if c in oldcodes:code=oldcodes[c]
        else:code=udc[ui];ui+=1
        canvas=Image.new('L',(72,72));d=ImageDraw.Draw(canvas);d.text((24,24+p.BASELINE),c,font=font,fill=255,anchor='ls')
        a=np.array(canvas);outside=a.copy();outside[24:48,24:48]=0
        if outside.any():clipped.append(c)
        im=canvas.crop((24,24,48,48));packed=p.pack_i4(im)
        assert p.pack_i4(p.unpack_i4(packed))==packed
        glyphs.append(packed);width=p.ADVANCE if c!='·' else round(font.getlength(c))
        mapping.append({'character':c,'code':code,'sjis_hex':f'{code:04x}','advance':width,'bitmap_index':i,'bbox':im.getbbox()})
        x=(i%32)*32;y=(i//32)*40;sheet.paste('#202020',(x+4,y+2),p.unpack_i4(packed));draw.text((x+2,y+27),str(i),fill='black')
    assert not clipped,clipped
    stub=make_stub(mapping);blob=b''.join(glyphs)
    (OUT/'glyphs.i4').write_bytes(blob);(OUT/'synthetic-hook.bin').write_bytes(stub);sheet.save(OUT/'glyph-atlas.png')
    dol=p.DOL.read_bytes();inv=json.loads(p.INV.read_text());assert p.sha(dol)==inv['dol']['sha256']
    romfont=p.yay0(p.ROMFONT.read_bytes());u=p.create_cpu(dol,inv,romfont)
    u.mem_write(BASE,stub);u.mem_write(BITMAPS,blob)
    preserved={r:0x10200000+r for r in [2,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31]}
    for r,value in preserved.items():u.reg_write(p.regnum(r),value)
    for m,g in zip(mapping,glyphs):
        got,width,consumed=p.texel(u,BASE,m['code'].to_bytes(2,'big'))
        assert got[:288]==g and got[288:]==b'\xa5'*(2048-288)
        assert width==m['advance'] and consumed==2
        assert all(u.reg_read(p.regnum(r))==value for r,value in preserved.items())
    fallbacks=0
    for c in ['A','0','!','?',' ','は','亜']:
        for x,stride in [(0,6),(2,8)]:
            raw=c.encode('cp932');assert p.texel(u,BASE,raw,x,stride)==p.texel(u,p.GET_TEXEL,raw,x,stride);fallbacks+=1
    for m in [mapping[0],mapping[-1]]:
        for x,stride in [(2,6),(0,8)]:
            raw=m['code'].to_bytes(2,'big');assert p.texel(u,BASE,raw,x,stride)==p.texel(u,p.GET_TEXEL,raw,x,stride);fallbacks+=1
    # Test actual cache keys, hit behavior and repeated 50-slot wrap for EVERY code.
    u=p.create_cpu(dol,inv,romfont);u.mem_write(BASE,stub);u.mem_write(BITMAPS,blob)
    branch=p.PPC(p.CALL_SITE);branch.branch(BASE,True);u.mem_write(p.CALL_SITE,branch.finish())
    u.mem_write(p.CACHE,b'\0'*(50*320));u.mem_write(p.OBJECT,b'\0'*256);u.mem_write(p.OBJECT+0x24,struct.pack('>I',24));u.mem_write(p.R13-0x6660,struct.pack('>I',p.CACHE))
    counts={'hook':0,'flush':0}
    def trace(cpu,pc,size,data):
        if pc==BASE:counts['hook']+=1
        if pc==0x80164b74:counts['flush']+=1
        if pc==0x80164b9c:
            assert bytes(cpu.mem_read(pc,4))==bytes.fromhex('44000002')
            cpu.reg_write(p.reg.UC_PPC_REG_PC,pc+4)
    u.hook_add(UC_HOOK_CODE,trace)
    def call(code):
        u.mem_write(p.STRING,code.to_bytes(2,'big')+b'\0')
        for r,v in {1:p.STACK,3:p.OBJECT,4:p.STRING,5:p.WIDTH}.items():u.reg_write(p.regnum(r),v)
        u.reg_write(p.reg.UC_PPC_REG_LR,p.STOP);u.emu_start(0x801a0448,0x801a0674,count=100000)
        assert u.reg_read(p.reg.UC_PPC_REG_PC)==0x801a0674
        sp=u.reg_read(p.regnum(1));return int.from_bytes(u.mem_read(sp+0x14,4),'big'),int.from_bytes(u.mem_read(sp+8,4),'big')
    for i,(m,g) in enumerate(zip(mapping,glyphs)):
        ptr,width=call(m['code']);assert ptr==p.CACHE+(i%50)*320 and width==m['advance']
        assert bytes(u.mem_read(ptr,288))==g
        assert bytes(u.mem_read(ptr+288,4))==struct.pack('>HH',m['code'],width)
        before=dict(counts);assert call(m['code'])==(ptr,width) and before==counts
    assert counts=={'hook':len(mapping),'flush':len(mapping)},counts
    metrics=json.loads((ROOT/'metadata/glyph_metrics.json').read_text(encoding='utf-8'))['metrics'];oracle_check(metrics)
    for m in mapping:metrics[m['character']]={'raw_advance_px':m['advance'],'bytes':m['sjis_hex'],'double_byte':True,'source':'full-font candidate synthetic CPU verified; not installed in game'}
    profiles={x['id']:x for x in json.loads((ROOT/'translation/window_profiles.json').read_text(encoding='utf-8'))['profiles']}
    layout=[];issues=Counter();risks=Counter()
    for r in rows:
        if r.get('translation') is None or r['kind']!='script_message_candidate':continue
        result=measure([dict(t,hex=t.get('hex','')) for t in translated_tokens(r)],metrics,profiles.get(r.get('window') or r.get('window_id')))
        layout.append({'id':r['id'],**result});issues.update(result['issues']);risks.update(result['conditional_risks'])
    plan={'catalog_sha256':catalog_hash,'font_sha256':p.sha(p.FONT.read_bytes()),'size_px':p.FONT_SIZE,'baseline':p.BASELINE,'mapping':mapping,'encoding_status':'candidate_private_use_codes; only extracted text absence verified','metrics':metrics}
    (ROOT/'translation/full_font_plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (OUT/'layout.json').write_text(json.dumps(layout,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    report={'glyph_count':len(mapping),'hangul_count':len(mapping)-1,'i4_bytes':len(blob),'hook_bytes':len(stub),'no_clipped_glyphs':True,'cpu_glyphs_verified':len(mapping),'cpu_cache_miss_hit_verified':len(mapping),'cache_wraps':len(mapping)//50,'fallback_cases':fallbacks,'private_use_codes':ui,'original_extracted_text_code_collisions':0,'remaining_unmeasured_characters':''.join(sorted(allchars-set(metrics))),
        'layout_records':len(layout),'layout_issues':dict(issues),'conditional_risks':dict(risks),'confirmed_window_fits':0,'game_installed':False,'runtime_verified':False,'flush_syscall_mocked':True,'new_iso_built':False,
        'limits':['UDC values absent from extracted original text, not proof against unextracted runtime strings','Synthetic fixture addresses are NOT patch placement','Cache flush system call skipped; no GPU rendering or hardware validation','Window links and dynamic widths remain unresolved']}
    (ROOT/'metadata/full_font_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    assert p.sha(catalog.read_bytes())==catalog_hash
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
