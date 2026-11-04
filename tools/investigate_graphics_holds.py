"""Read-only evidence for held graphics: relocation types, placements, JP/US pairs."""
from collections import defaultdict,Counter
import hashlib,json,struct
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from inspect_discs import ROOT,save
from functools import lru_cache
from extract_graphics import scalar_relocations

@lru_cache(maxsize=16)
def read_hsd(file,archive_offset=0,edition='jp'):
    base=ROOT/f'work/roundtrip/{edition}/qp/files'
    if file.startswith('pc.bin/'):
        b=(base/'pc.bin').read_bytes();off=archive_offset;n=struct.unpack_from('>I',b,off)[0];return b[off:off+n]
    return (base/file).read_bytes()

@lru_cache(maxsize=16)
def hsd_structure(file,archive_offset=0,edition='jp'):
    b=read_hsd(file,archive_offset,edition);_,off,n,*_=struct.unpack_from('>5I',b)
    return b,set(struct.unpack_from(f'>{n}I',b,off+32))

def test_models(stages):
    dol=(ROOT/'work/roundtrip/jp/main.dol').read_bytes()
    def address(a):
        for i in range(18):
            start=struct.unpack_from('>I',dol,0x48+4*i)[0];n=struct.unpack_from('>I',dol,0x90+4*i)[0]
            if start<=a<start+n:return struct.unpack_from('>I',dol,4*i)[0]+a-start
        raise ValueError(hex(a))
    result=[]
    for ident,name in [(18,'box_4'),(19,'box_8'),(20,'box_12'),(21,'box_lift')]:
        at=0x218f00+24*ident;model=address(struct.unpack_from('>I',dol,at)[0]);string=address(struct.unpack_from('>I',dol,model)[0])
        path=dol[string:dol.index(0,string)].decode('ascii');assert path=='test/'+name
        b,rs=hsd_structure(path+'.dat');_,rel,nr,nroot,nref=struct.unpack_from('>5I',b);rt=32+rel+4*nr;st=rt+8*(nroot+nref)
        def u(p):return struct.unpack_from('>I',b,32+p)[0]
        scene=None
        for k in range(nroot):
            p,s=struct.unpack_from('>II',b,rt+8*k)
            if b[st+s:b.index(0,st+s)]==b'scene_data':scene=p
        assert scene is not None
        arr=u(scene);joints=[];seen=set()
        def walk(p):
            if not p or p in seen:return
            seen.add(p);flags=u(p+4)
            joints.append(dict(offset=p+32,flags=flags,hidden=bool(flags&16),display_object_pointer=u(p+16)))
            walk(u(p+8));walk(u(p+12))
        while u(arr):walk(u(u(arr)));arr+=4
        placements=[dict(file=s['file'],**o) for s in stages for o in s['objects'] if o['id']==ident]
        result.append(dict(id=ident,path=path,definition_offset=at,model_pointer_offset=model,string_offset=string,
            dol_sha256=hashlib.sha256(dol).hexdigest(),source_sha256=hashlib.sha256(b).hexdigest(),joints=joints,placements=placements,
            limit='Placement/spawn flags and non-hidden joint do not prove final runtime visibility; script overrides and engine draw policy unverified.'))
    return result

def signature(r):
    im=Image.open(ROOT/r['png']).convert('RGBA');bg=Image.new('RGBA',im.size,(60,60,60,255));bg.alpha_composite(im)
    return np.asarray(bg.convert('RGB').resize((24,24)),dtype=np.float32)

def main():
    jp=json.loads((ROOT/'metadata/graphics_catalog_jp.json').read_text());us=json.loads((ROOT/'metadata/graphics_catalog_us.json').read_text())
    groups=json.loads((ROOT/'metadata/graphics_visual_observations.json').read_text())['groups'];byid={r['id']:r for r in jp['images']}
    errors=[]
    for r in jp['images']:
        if r['kind']!='hsd':continue
        b,rs=hsd_structure(r['file'],r.get('archive_offset',0));at=r['descriptor_offset']-32
        extra=scalar_relocations(at,rs)
        if extra:errors.append(dict(id=r['id'],pixel_sha256=r['pixel_sha256'],file=r['file'],descriptor_offset=r['descriptor_offset'],
            nonpointer_field_relocations=extra,descriptor_hex=b[at+32:at+56].hex(),source_sha256=hashlib.sha256(b).hexdigest(),
            conclusion='not_an_HSD_ImageDesc: width/height/format/mipmap/LOD scalar fields contain relocated pointers'))
    # Read every stage object table with the actual documented 56-byte stride.
    # Object IDs are collected without assuming USA name-table numbering applies to JP.
    stages=[]
    for p in sorted((ROOT/'work/roundtrip/jp/qp/files/bin').glob('*.bin')):
        if p.name=='globals.bin':continue
        b=p.read_bytes();h=struct.unpack_from('<13I',b);assert h[:2]==(52,72)
        off=h[1];objects=[]
        while True:
            ident=struct.unpack_from('>i',b,off)[0]
            if ident<0:break
            values=struct.unpack_from('>14i',b,off);flags=values[13]&0xffffffff
            objects.append(dict(index=len(objects),offset=off,id=ident,position=list(values[1:4]),variant=values[12],flags=flags,
                spawn=bool(flags&1),invisible=bool(flags&32),disabled=bool(flags&0x80000000)));off+=56
            assert off+4<=len(b)
        stages.append(dict(file='bin/'+p.name,object_count=len(objects),terminator_offset=off,objects=objects,sha256=hashlib.sha256(b).hexdigest()))
    out=ROOT/'work/extraction/jp/hold-investigation';out.mkdir(parents=True,exist_ok=True)
    uh=defaultdict(list);uf=defaultdict(list)
    for r in us['images']:
        if r['decoded'] and r['kind']!='hsd_mip':uh[r['pixel_sha256']].append(r);uf[r['file']].append(r)
    pairs=[];sig={}
    for g in groups:
        if g['suggested_selection'] not in ('hold_small_lettering','hold_symbol_or_kanji'):continue
        r=byid[g['ids'][0]];matches=uh.get(r['pixel_sha256'],[]);mode='pixel_identical'
        if matches:s=next((s for s in matches if s['file']==r['file']),matches[0]);score=0
        else:
            options=[s for s in uf[r['file']] if s['width']==r['width'] and s['height']==r['height']]
            if not options:s=None;score=None;mode='no_same_file_dimension_candidate'
            else:
                ref=signature(r)
                for s in options:
                    if s['pixel_sha256'] not in sig:sig[s['pixel_sha256']]=signature(s)
                s=min(options,key=lambda t:np.mean((sig[t['pixel_sha256']]-ref)**2));score=float(np.mean((sig[s['pixel_sha256']]-ref)**2));mode='nearest_same_file_size_unverified_correspondence'
        pairs.append(dict(index=g['sheet_index'],jp_id=r['id'],jp_png=r['png'],pixel_sha256=r['pixel_sha256'],us_id=s['id'] if s else None,us_png=s['png'] if s else None,mode=mode,mse=score))
    for start in range(0,len(pairs),6):
        page=Image.new('RGB',(1200,1020),(60,60,60));draw=ImageDraw.Draw(page)
        for j,r in enumerate(pairs[start:start+6]):
            x=j%2*600;y=j//2*340
            draw.text((x+5,y+4),f'{r["index"]:04} JP | US  {r["mode"][:20]}',fill='white')
            for col,key in enumerate(('jp_png','us_png')):
                if not r[key]:continue
                im=Image.open(ROOT/r[key]).convert('RGBA');scale=min(280/im.width,260/im.height,4)
                im=im.resize((round(im.width*scale),round(im.height*scale)),Image.Resampling.NEAREST);page.paste(im,(x+col*300+5,y+25),im)
            draw.text((x+5,y+295),r['jp_id'][:70],fill='white')
        page.save(out/f'pair-{start//6:02}.png')
    save(ROOT/'metadata/graphics_hold_evidence.json',dict(rejected_descriptors=errors,comparison_pairs=pairs,test_models=test_models(stages),
        limits='Exact pixel equality does not establish scene use; nearest-image correspondence must be visually checked. Stage placement does not include dynamic script spawns.'))
    save(ROOT/'metadata/stage_object_placements.json',dict(edition='jp',stages=stages))
    print('rejected descriptor entries',len(errors),'pixel groups',len({r['pixel_sha256'] for r in errors}),'pairs',len(pairs),'stages',len(stages))
    print('JP model IDs18..21 verified from original DOL pointers; placements and joint visibility recorded.')

if __name__=='__main__':main()
