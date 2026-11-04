"""Immutable Korean glyph pointers, composed with pending v04 centering.

Memory-only preparation and PPC verification. Never write a game DOL or ISO.
"""
import struct
from unicorn import UC_HOOK_CODE
import prepare_output_probe as p
import prepare_v03_corrections as v
import prepare_v04_centering as center
import verify_subtitle_cache_lifetime as life

BASE=0x8069f000
SIZE=8192
TABLE=BASE+0x400
LOW,HIGH=0xf040,0xf597
HOOK=0x801a04cc


def mapped(dol):
    mem=v.read('metadata/injection_memory_verification.json')
    result=[]
    for i,m in enumerate(v.read('translation/full_font_plan.json')['mapping']):
        result.append(dict(m,address=mem['bitmaps']+i*288))
    for i,m in enumerate(v.read('metadata/v03_corrections_verification.json')['font_additions']):
        result.append(dict(m,address=0x8069d800+i*288))
    for m in result:
        assert m['address']%32==0 and 0<m['advance']<32
        off=v.offset(dol,m['address']);m['pixels']=dol[off:off+288]
        assert len(m['pixels'])==288 and any(m['pixels'])
    return result


def stub(entries):
    s=p.PPC(BASE)
    special=[m for m in entries if m['code']<LOW]
    for i,m in enumerate(special):
        s.d(10,0,30,m['code']);s.bc(0x41820000,f'special{i}')
    s.d(10,0,30,LOW);s.bc(0x41800000,'fallback')
    s.d(10,0,30,HIGH);s.bc(0x41810000,'fallback')
    s.load(4,LOW)
    s.emit(31<<26|4<<16|30<<11|40<<1) # subf r0,r4,r30
    s.emit(21<<26|2<<11|29<<1) # slwi r0,r0,2
    s.load(4,TABLE)
    s.emit(31<<26|10<<21|4<<16|23<<1) # lwzx r10,r4,r0
    s.d(11,0,10,0);s.bc(0x41820000,'fallback')
    s.bc(0x48000000,'found')
    for i,m in enumerate(special):
        s.label(f'special{i}');s.load(10,m['address']|m['advance'])
        s.bc(0x48000000,'found')
    s.label('found')
    s.emit(21<<26|10<<21|4<<16|26<<1) # clrrwi r4,r10,5
    s.d(28,10,0,31) # andi. r0,r10,31 (width packed in alignment bits)
    s.d(36,4,1,0x14);s.d(36,0,1,8)
    s.branch(0x801a064c)
    s.label('fallback');s.d(14,0,0,0) # displaced li r0,0
    s.branch(HOOK+4)
    data=s.finish();assert len(data)<=0x400
    return data


def prepare():
    centered,original,report,_,_=center.prepare()
    dol=bytearray(centered);entries=mapped(centered);payload=bytearray(SIZE)
    code=stub(entries);payload[:len(code)]=code
    for m in entries:
        if LOW<=m['code']<=HIGH:
            off=TABLE-BASE+(m['code']-LOW)*4
            assert off+4<=SIZE and not any(payload[off:off+4])
            payload[off:off+4]=v.word(m['address']|m['advance'])
    off=v.offset(dol,HOOK);assert dol[off:off+4]==v.word(0x38000000)
    dol[off:off+4]=v.branch(HOOK,BASE,False)
    ah=v.read('metadata/injection_memory_verification.json')['arena_hook']
    off=v.offset(dol,ah);old=p.PPC(ah);old.load(11,BASE)
    new=p.PPC(ah);new.load(11,BASE+SIZE)
    assert dol[off:off+8]==old.finish();dol[off:off+8]=new.finish()
    section_size=int.from_bytes(dol[0x98:0x9c],'big')
    assert int.from_bytes(dol[0x50:0x54],'big')+section_size==BASE
    assert int.from_bytes(dol[8:12],'big')+section_size==len(dol)
    dol[0x98:0x9c]=v.word(section_size+SIZE);dol.extend(payload)
    assert report['dol']['offset']+len(dol)<=5177344
    # Generate one guarded recipe against the retained v03, including centering.
    patches=[]
    for i in range(0,len(original),4):
        if original[i:i+4]!=dol[i:i+4]:
            patches.append({'offset':i,'before':original[i:i+4].hex(),
                            'after':dol[i:i+4].hex(),'reason':'v04 centering and immutable font lifetime'})
    restored=bytearray(dol[:len(original)])
    for r in patches:restored[r['offset']:r['offset']+4]=bytes.fromhex(r['before'])
    assert restored==original
    return bytes(dol),centered,original,report,entries,patches


def verify(data):
    dol,centered,original,report,entries,_=data
    old=life.reproduce(original);fixed=life.reproduce(dol)
    assert old['retained_bitmap_hangul']=='자음음은아빠차례구나'
    assert fixed['retained_bitmap_hangul']==fixed['expected_hangul']=='자다음은아빠차례구나'
    u=v.cpu(dol);refs=[]
    for m in entries:
        ptr,width=life.lookup(u,m['code'])
        assert ptr==m['address'] and width==m['advance']
        assert bytes(u.mem_read(ptr,288))==m['pixels']
        refs.append(ptr)
    assert len(set(refs))==len(entries)
    assert int.from_bytes(u.mem_read(p.R13-0x665c,4),'big')==0
    # Exercise fallback cache eviction, then reread ALL retained Korean pointers.
    # Original JP codes that are not remapped must still match v03 bitmaps/width.
    oldcpu=v.cpu(original);codes={m['code'] for m in entries};fallback=0
    samples=[ord(c) for c in ' A0!?']+[0x82a0,0x8341,0x8140]
    samples += [c for c in range(0x8940,0x89fd) if c&255!=0x7f][:110]
    samples += [LOW+0x3f,HIGH+1] # unmapped private-use holes/boundaries
    for code in samples:
        assert code not in codes
        ptr,w=life.lookup(u,code);optr,ow=life.lookup(oldcpu,code)
        assert w==ow and bytes(u.mem_read(ptr,288))==bytes(oldcpu.mem_read(optr,288))
        fallback+=1
    for m in entries:
        assert bytes(u.mem_read(m['address'],288))==m['pixels']
        ptr,w=life.lookup(u,m['code']);assert ptr==m['address'] and w==m['advance']
    # Verify the real descriptor constructor gets the immutable bitmap pointer.
    descriptor=[]
    for c in ['다','음']:
        m=next(m for m in entries if m['character']==c)
        u=v.cpu(dol)
        # Run real per-object initialization; the simpler width fixture's +24
        # sentinel is sufficient for cache lookup but is not a descriptor pointer.
        u.mem_write(p.OBJECT+0x24,bytes(4))
        life.lookup(u,m['code'])
        # Continue real getGlyph through its descriptor setup until GXInitTexObj.
        u.emu_start(0x801a0674,0x8018ae98,count=10000)
        assert u.reg_read(p.reg.UC_PPC_REG_PC)==0x8018ae98
        assert u.reg_read(p.regnum(4))==m['address']
        descriptor.append({'character':c,'texture_data':hex(m['address'])})
    # Composition regression: actual title caller and all 9 slot positions/scales.
    for shift in [-80.,0.,80.]:assert center.title_path(dol,shift)==center.title_path(centered,shift)
    for scale in [.75,1.,1.25]:
        for anchor in [126.,320.,514.]:assert center.slot_path(dol,anchor,scale)==center.slot_path(centered,anchor,scale)
    ah=v.read('metadata/injection_memory_verification.json')['arena_hook'];u=v.cpu(dol)
    for requested in [BASE-32,BASE,BASE+32,BASE+SIZE-32,BASE+SIZE,BASE+SIZE+32,0x81000000]:
        u.reg_write(p.regnum(3),requested);v.call(u,ah)
        assert int.from_bytes(u.mem_read(p.R13-0x72f0,4),'big')==max(requested,BASE+SIZE)
    return {'before':old,'after':fixed,'immutable_glyphs':len(entries),
            'unique_immutable_addresses':len(set(refs)),'original_fallback_cases':fallback,
            'retained_bitmaps_after_fallback_eviction':len(entries),'GXInitTexObj_arguments':descriptor,
            'centering_composition_cases':12,'arena_cases':7}


def main():
    data=prepare();checks=verify(data)
    dol,centered,original,report,entries,patches=data
    out=p.ROOT/'work/runtime-corrections/v04';out.mkdir(parents=True,exist_ok=True)
    with (p.ROOT/report['iso']['path']).open('rb') as f:
        f.seek(report['dol']['offset']+len(original));gap=f.read(len(dol)-len(original))
    recipe={'base_dol_sha256':p.sha(original),'expected_dol_sha256':p.sha(dol),
            'base_dol_bytes':len(original),'new_dol_bytes':len(dol),'disc_offset':report['dol']['offset'],
            'patches':patches,'append_hex':dol[len(original):].hex(),'disc_append_before_sha256':p.sha(gap)}
    p.save(out/'combined-recipe.json',recipe)
    p.save(p.ROOT/'metadata/v04_font_lifetime_verification.json',{
        'source_build_sha256':report['iso']['sha256'],'candidate_dol_sha256':p.sha(dol),
        'recipe':'work/runtime-corrections/v04/combined-recipe.json',
        'recipe_sha256':p.sha((out/'combined-recipe.json').read_bytes()),
        'bitmap_data_unchanged':True,'immutable_lookup_address':hex(BASE),
        'new_arena_end':hex(BASE+SIZE),'additional_bytes_over_v03':len(dol)-len(original),
        'remaining_gap_before_qp_bytes':5177344-report['dol']['offset']-len(dol),
        'checks':checks,'new_iso_built':False,'runtime_fix_verified':False,
        'limits':['Warm-cache state is constructed, not captured from the user.',
                  'Real PPC lookup and descriptor arguments verified; no GPU rendering or timing emulation.',
                  'Dolphin screen confirmation remains required.']})
    print('PASS:',checks['before']['retained_bitmap_hangul'],'->',checks['after']['retained_bitmap_hangul'])
    print('PASS: immutable glyphs',len(entries),'; no ISO written')


if __name__=='__main__':main()
