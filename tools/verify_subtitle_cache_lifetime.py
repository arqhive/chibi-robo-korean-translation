"""Reproduce FIFO glyph aliasing with real PPC lookup code; no ISO writes.

The warm cache is an explicit fixture, not a capture of the user's runtime.
"""
import struct
import prepare_v04_centering as center
import prepare_v03_corrections as v
import prepare_output_probe as p


TEXT = '자, 다음은 아빠 차례구나!'


def glyphs():
    plan = v.read('translation/full_font_plan.json')['mapping']
    blob = (p.ROOT/'work/full-font/glyphs.i4').read_bytes()
    return {m['character']: dict(m, pixels=blob[i*288:(i+1)*288]) for i,m in enumerate(plan)}


def lookup(u, code):
    u.mem_write(p.STRING, code.to_bytes(1 if code<=255 else 2,'big')+b'\0')
    for r,x in {1:p.STACK,3:p.OBJECT,4:p.STRING,5:p.WIDTH}.items():
        u.reg_write(p.regnum(r),x)
    v.call(u,0x801a0448,0x801a0674)
    sp=u.reg_read(p.regnum(1))
    return int.from_bytes(u.mem_read(sp+20,4),'big'), int.from_bytes(u.mem_read(sp+8,4),'big')


def reproduce(dol):
    g=glyphs();u=v.cpu(dol)
    # Put 다 at the next eviction position. All other letters of the sentence
    # except 음 are cached, as can happen after earlier dialogue.
    warm=['다']+list(dict.fromkeys(c for c in TEXT if c in g and c not in '다음'))
    warm += [c for c in g if c not in warm and c!='음'][:50-len(warm)]
    for c in warm: lookup(u,g[c]['code'])
    refs=[]
    for c in TEXT:
        if c not in g: continue # original ASCII is normally preloaded separately
        ptr,width=lookup(u,g[c]['code'])
        assert bytes(u.mem_read(ptr,288))==g[c]['pixels'] and width==g[c]['advance']
        refs.append((c,ptr))
    inverse={m['pixels']:c for c,m in g.items()}
    retained=''.join(inverse.get(bytes(u.mem_read(ptr,288)),'?') for _,ptr in refs)
    expected=''.join(c for c in TEXT if c in g)
    return {'warm_characters':warm,'expected_hangul':expected,
            'retained_bitmap_hangul':retained,
            'references':[{'character':c,'address':hex(ptr)} for c,ptr in refs],
            'next_cache_index':int.from_bytes(u.mem_read(p.R13-0x665c,4),'big')}


if __name__=='__main__':
    dol,_=center.load();result=reproduce(dol)
    assert result['retained_bitmap_hangul']=='자음음은아빠차례구나'
    assert result['expected_hangul']=='자다음은아빠차례구나'
    p.save(p.ROOT/'metadata/subtitle_cache_lifetime_reproduction.json',result)
    print(result)
