"""Improve CMPR endpoints under exact outside-mask RGBA constraints.

For blocks containing protected pixels, enumerate all RGB565 endpoint pairs
consistent with those colors, including interpolated endpoints absent from the
PNG. Fully editable blocks retain the existing heuristic (no optimality claim).
"""
import itertools,json,struct,time
import numpy as np
from PIL import Image,ImageDraw
from inspect_discs import ROOT,save
from decode_gx import expand,decode
import verify_graphics_encoding as gx

CHANNELS={}
STATS={'constrained_blocks':0,'fully_editable_blocks':0,'endpoint_pairs_tested':0,'improved_blocks':0}
for bits in (5,6):
    a,b=np.indices((1<<bits,1<<bits)).reshape(2,-1);aa=expand(a,bits);bb=expand(b,bits)
    for mode in (3,4):
        pal=np.stack([aa,bb,(5*aa+3*bb)//8,(3*aa+5*bb)//8],1) if mode==4 else np.stack([aa,bb,(aa+bb)//2,(aa+bb)//2],1)
        CHANNELS[bits,mode]=(a,b,pal)

def palettes(a,b):
    ca=gx.rgb565(a).astype(np.int32);cb=gx.rgb565(b).astype(np.int32)
    middle=(ca+cb)//2;tr=middle.copy();tr[:,3]=0
    return np.stack([ca,cb,np.where((a>b)[:,None],(5*ca+3*cb)//8,middle),np.where((a>b)[:,None],(3*ca+5*cb)//8,tr)],1)

def solve(raw,target,mask):
    baseline=gx.encode_cmpr_sub(raw,target,mask)
    edited=mask.reshape(16)
    if not edited.any():return raw
    if edited.all():STATS['fully_editable_blocks']+=1;return baseline
    STATS['constrained_blocks']+=1
    oldpal=gx.colors(*struct.unpack_from('>HH',raw));oldsel=np.array([(raw[4+y]>>(6-2*x))&3 for y in range(4) for x in range(4)])
    old=oldpal[oldsel];protected=np.unique(old[~edited],axis=0);pix=target.reshape(16,4).astype(np.int64)
    a0,b0=struct.unpack_from('>HH',baseline);bp=gx.colors(a0,b0)
    base_dist=gx.distance(pix,bp);best_score=int(base_dist[edited].min(1).sum());best=(a0,b0)
    if best_score==0:return baseline
    original_pair=struct.unpack_from('>HH',raw)
    for mode in (3,4):
        for indices in itertools.permutations(range(4),len(protected)):
            if any(int(c[3])!=(0 if mode==3 and i==3 else 255) for c,i in zip(protected,indices)):continue
            options=[]
            for channel,bits in enumerate((5,6,5)):
                aa,bb,pal=CHANNELS[bits,mode];ok=np.ones(len(aa),bool)
                for color,index in zip(protected,indices):ok &= pal[:,index]==color[channel]
                options.append(np.flatnonzero(ok))
            if any(len(o)==0 for o in options):continue
            # With at least one fixed color, each channel restricts the pairs.
            grids=np.meshgrid(*options,indexing='ij');ap=np.zeros(grids[0].size,np.uint32);bpv=ap.copy()
            for channel,(bits,shift) in enumerate(((5,11),(6,5),(5,0))):
                aa,bb,_=CHANNELS[bits,mode];index=grids[channel].reshape(-1)
                ap |= aa[index].astype(np.uint32)<<shift;bpv |= bb[index].astype(np.uint32)<<shift
            valid=ap>bpv if mode==4 else ap<=bpv;ap=ap[valid];bpv=bpv[valid]
            STATS['endpoint_pairs_tested']+=len(ap)
            wanted=pix[edited];premul=wanted[:,:3]*wanted[:,3:4]//255
            for begin in range(0,len(ap),4096):
                av=ap[begin:begin+4096];bv=bpv[begin:begin+4096];pal=palettes(av,bv).astype(np.int64)
                rgb=pal[:,:,:3]*pal[:,:,3:4]//255
                dist=((premul[None,:,None,:]-rgb[:,None,:,:])**2).sum(3)+3*(wanted[None,:,None,3]-pal[:,None,:,3])**2
                scores=dist.min(2).sum(1);index=int(scores.argmin());score=int(scores[index])
                if score<best_score:
                    best_score=score;best=(int(av[index]),int(bv[index]))
    pal=gx.colors(*best);same=(old[:,None]==pal[None]).all(2)
    assert same[~edited].any(1).all()
    sel=gx.distance(pix,pal).argmin(1);sel[~edited]=same[~edited].argmax(1)
    result=struct.pack('>HH',*best)+bytes(sum(int(sel[y*4+x])<<(6-2*x) for x in range(4)) for y in range(4))
    old_score=int(base_dist[edited].min(1).sum())
    if best_score<old_score:STATS['improved_blocks']+=1
    return result if best_score<old_score else baseline

def main():
    project=json.loads((ROOT/'project.json').read_text('utf-8'))
    report=json.loads((ROOT/'metadata/graphics_encoding_verification.json').read_text('utf-8'))
    cat={r['id']:r for r in json.loads((ROOT/'metadata/graphics_catalog_jp.json').read_text('utf-8'))['images']}
    assets={s['pixel_sha256']:s for s in project['graphics_selection']}
    out=ROOT/'work/cmpr-refinement';out.mkdir(parents=True,exist_ok=True);rows=[]
    for old in report['textures']:
        if old['format']!=14:continue
        row=cat[old['texture']];asset=assets[row['pixel_sha256']]['composite_review'];path=ROOT/asset['path']
        assert gx.sha(path.read_bytes())==asset['sha256']
        blob=(ROOT/'work/roundtrip/jp/qp/files'/row['file']).read_bytes();raw=blob[row['data_offset']:row['data_offset']+row['data_size']]
        assert gx.sha(raw)==row['raw_sha256'];image=Image.open(path).convert('RGBA');mask=np.array(Image.open(ROOT/asset['mask']).convert('L'))>0
        before=dict(STATS);encoded,decoded,_=gx.encode(raw,image,14,edit_mask=mask,cmpr_encoder=solve)
        code=old['code'];decoded.save(out/f'{code}.png');(out/f'{code}.gx').write_bytes(encoded)
        target=np.array(image).astype(int);original=np.array(decode(raw,*image.size,14)).astype(int)
        baseline=np.array(Image.open(ROOT/old['preview']).convert('RGBA')).astype(int);current=np.array(decoded).astype(int)
        assert np.array_equal(original[~mask],current[~mask])
        def score(a):return int(((target[:,:,:3]-a[:,:,:3])**2).sum())
        assert score(current)<=score(baseline)
        r={'code':code,'candidate_sha256':asset['sha256'],'baseline_sse_rgb':score(baseline),'refined_sse_rgb':score(current),
           'outside_edit_mask_changed_pixels':0,'sha256':gx.sha(encoded),'statistics':{k:STATS[k]-before[k] for k in STATS},
           'png':f'work/cmpr-refinement/{code}.png','gx':f'work/cmpr-refinement/{code}.gx'}
        rows.append(r);print(json.dumps(r),flush=True)
    sheet=Image.new('RGB',(1120,len(rows)*350),'#555555');draw=ImageDraw.Draw(sheet)
    for i,r in enumerate(rows):
        old=next(x for x in report['textures'] if x['code']==r['code']);draw.text((5,i*350),r['code']+' PNG | previous | refined x6',fill='white')
        for x,path in [(0,old['candidate_path']),(370,old['preview']),(740,r['png'])]:
            im=Image.open(ROOT/path).convert('RGBA');im=im.resize((im.width*6,im.height*6),Image.Resampling.NEAREST);sheet.paste(im,(x+5,i*350+22),im)
    sheet.save(out/'comparison.png')
    save(ROOT/'metadata/cmpr_refinement.json',{'textures':rows,'statistics':STATS,'new_iso_built':False,
        'limits':['Exact endpoint enumeration for constrained blocks only; fully editable blocks retain heuristic',
                  'Numeric error reduction is not visual approval; no asset approval changed']})

if __name__=='__main__':main()
