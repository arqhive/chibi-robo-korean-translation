"""Encode isolated texture candidates, preserving unedited pixels and headers.

No game container or ISO is written. CMPR endpoint trials reproduce every RGBA
pixel outside the supplied edit mask exactly; original endpoints are fallback.
Structural success does not imply acceptable CMPR glyph quality.
"""
import json,struct,hashlib
from collections import defaultdict
import numpy as np
from PIL import Image,ImageDraw
from inspect_discs import ROOT,save
from decode_gx import decode,palette_rgba,rgb565,BLOCKS,size,self_test

def sha(b):return hashlib.sha256(b).hexdigest()
def pack565(c):return ((int(c[0])*31+127)//255<<11)|((int(c[1])*63+127)//255<<5)|((int(c[2])*31+127)//255)
def colors(a,b):
    ca=rgb565(np.array(a)).astype(np.int32);cb=rgb565(np.array(b)).astype(np.int32)
    if a>b:return np.array([ca,cb,(5*ca+3*cb)//8,(3*ca+5*cb)//8])
    mid=(ca+cb)//2;tr=mid.copy();tr[3]=0
    return np.array([ca,cb,mid,tr])
def distance(p,c):
    # Compare premultiplied color, plus alpha; transparent hidden RGB is irrelevant
    # only for EDITED pixels. Unedited RGBA is constrained by exact equality.
    p=p.astype(np.int64);c=c.astype(np.int64)
    pr=p[:,:3]*p[:,3:4]//255;cr=c[:,:3]*c[:,3:4]//255
    return ((pr[:,None]-cr[None])**2).sum(2)+3*(p[:,None,3]-c[None,:,3])**2
def encode_cmpr_sub(raw,target,mask):
    if not mask.any():return raw
    a,b=struct.unpack_from('>HH',raw);original=colors(a,b)
    oldsel=np.array([(raw[4+y]>>(6-2*x))&3 for y in range(4) for x in range(4)])
    old=original[oldsel];pix=target.reshape(16,4);edited=mask.reshape(16)
    candidates={(a,b)}
    endpoints={a,b,0,65535}
    endpoints.update(pack565(c) for c in pix[edited] if c[3]>=128)
    # At most 20 distinct endpoints for a 4x4 block.
    candidates.update((x,y) for x in endpoints for y in endpoints)
    best=None
    for x,y in sorted(candidates):
        pal=colors(x,y);equal=(old[:,None]==pal[None]).all(2)
        if not equal[~edited].any(1).all():continue
        dist=distance(pix,pal);sel=dist.argmin(1)
        sel[~edited]=equal[~edited].argmax(1)
        # Stable ties prefer original encoding/endpoint order.
        score=(int(dist[np.arange(16)[edited],sel[edited]].sum()),(x,y)!=(a,b),x,y)
        if best is None or score<best[0]:best=(score,x,y,sel)
    assert best is not None
    _,a,b,sel=best
    return struct.pack('>HH',a,b)+bytes(sum(int(sel[y*4+x])<<(6-2*x) for x in range(4)) for y in range(4))

def encode(raw,image,fmt,palette=None,edit_mask=None,cmpr_encoder=encode_cmpr_sub):
    w,h=image.size;target=np.array(image.convert('RGBA'));source=np.array(decode(raw,w,h,fmt,palette))
    edited=(source!=target).any(2);out=bytearray(raw)
    allowed=edited if edit_mask is None else np.asarray(edit_mask,dtype=bool)
    assert allowed.shape==edited.shape and not (edited&~allowed).any()
    bw,bh,bs=BLOCKS[fmt];nx=(w+bw-1)//bw
    if fmt==14:
        padded=np.zeros((((h+7)//8)*8,((w+7)//8)*8,4),np.uint8);padded[:h,:w]=target
        mask=np.zeros(padded.shape[:2],bool);mask[:h,:w]=allowed
        for by in range(0,h,8):
            for bx in range(0,w,8):
                base=((by//8)*nx+bx//8)*32
                for i in range(4):
                    x=bx+(i%2)*4;y=by+(i//2)*4;at=base+i*8
                    # Padded texels outside the dimensions count as untouched.
                    old=colors(*struct.unpack_from('>HH',raw,at))
                    vals=np.array([old[(raw[at+4+yy]>>(6-2*xx))&3] for yy in range(4) for xx in range(4)]).reshape(4,4,4)
                    tt=padded[y:y+4,x:x+4].copy();mm=mask[y:y+4,x:x+4];tt[~mm]=vals[~mm]
                    out[at:at+8]=cmpr_encoder(raw[at:at+8],tt,mm)
    else:
        for y,x in zip(*np.nonzero(edited)):
            base=((y//bh)*nx+x//bw)*bs;pos=(y%bh)*bw+x%bw;c=target[y,x]
            if fmt in (0,8):
                if fmt==0:
                    pal=np.repeat((np.arange(16)*17)[:,None],4,axis=1)
                else:pal=palette[:16]
                value=int(distance(c[None],np.asarray(pal)).argmin())
                at=base+pos//2;shift=4 if pos%2==0 else 0
                out[at]=(out[at]&~(15<<shift))|(value<<shift)
            elif fmt==4:struct.pack_into('>H',out,base+pos*2,pack565(c))
            elif fmt==5:
                alpha=(int(c[3])*7+127)//255
                v=(alpha<<12)|sum(((int(c[k])*15+127)//255)<<(8-4*k) for k in range(3))
                if c[3]==255:
                    v=0x8000|sum(((int(c[k])*31+127)//255)<<(10-5*k) for k in range(3))
                struct.pack_into('>H',out,base+pos*2,v)
            else:raise ValueError(fmt)
    result=decode(bytes(out),w,h,fmt,palette);decoded=np.array(result)
    assert np.array_equal(source[~allowed],decoded[~allowed]),'Encoding altered pixels outside edit mask'
    return bytes(out),result,allowed

def main():
    self_test()
    # Non-square edge tiles, palette channel order, no-op and preservation checks.
    for fmt in [0,4,5,8,14]:
        raw=bytes(size(9,7,fmt));pal=palette_rgba(bytes.fromhex('0000ffff')*128,2) if fmt==8 else None
        image=decode(raw,9,7,fmt,pal);assert encode(raw,image,fmt,pal)[0]==raw
        image.putpixel((8,6),(255,255,255,255));got,im,mask=encode(raw,image,fmt,pal)
        assert im.getpixel((8,6))==(255,)*4 and mask.sum()==1
    project=json.loads((ROOT/'project.json').read_text('utf-8'))
    catalog=json.loads((ROOT/'metadata/graphics_catalog_jp.json').read_text('utf-8'))['images']
    observations={r['pixel_sha256']:r for r in json.loads((ROOT/'metadata/graphics_visual_observations.json').read_text('utf-8'))['groups']}
    out=ROOT/'work/graphics-encoding';out.mkdir(parents=True,exist_ok=True)
    parts=json.loads((ROOT/'work/roundtrip/jp/parts.json').read_text('utf-8'))
    source_hashes={r['path']:r['sha256'] for r in json.loads((ROOT/'metadata/qp_inventory_jp.json').read_text('utf-8'))['files']}
    source_hashes.update({r['path']:r['sha256'] for r in json.loads((ROOT/'metadata/disc_inventory_jp.json').read_text('utf-8'))['files'] if r['path']=='opening.bnr'})
    report=[];containers={};patches=defaultdict(list);previews=[]
    for asset in project['graphics_selection']:
        if asset['selection']!='translate_japanese':continue
        candidate=asset.get('composite_review') or asset.get('reuse')
        if not candidate:continue
        digest=asset['pixel_sha256'];code=f"G{observations[digest]['sheet_index']:04}"
        path=ROOT/candidate['path'];assert sha(path.read_bytes())==candidate['sha256']
        image=Image.open(path).convert('RGBA')
        for index,row in enumerate(r for r in catalog if r.get('pixel_sha256')==digest):
            assert not row.get('mipmap') and row['kind']!='hsd_mip'
            file=row['file'];assert not file.startswith('pc.bin/')
            if file not in containers:
                source=ROOT/'work/roundtrip/jp/qp/files'/file
                if file=='opening.bnr':source=ROOT/'work/roundtrip/jp'/next(p['disk_file'] for p in parts if p['name']==file)
                containers[file]=(source,source.read_bytes())
                assert sha(containers[file][1])==source_hashes[file]
            source,blob=containers[file];start=row['data_offset'];n=row['data_size'];raw=blob[start:start+n]
            assert sha(raw)==row['raw_sha256'] and image.size==(row['width'],row['height'])
            palette=None
            if 'palette_offset' in row:
                at=row['palette_offset'];palette=palette_rgba(blob[at:at+2*row['palette_count']],row['palette_format'])
            original=decode(raw,*image.size,row['format'],palette)
            assert encode(raw,original,row['format'],palette)[0]==raw
            effective=image
            interpretation='RGBA'
            if row['format']==0:
                # Reused button art is an opaque grayscale presentation of an I4
                # intensity mask. Its black pixels mean zero intensity/alpha,
                # not a request to change the format into opaque black RGBA.
                aa=np.array(image);assert np.all(aa[:,:,3]==255)
                assert np.array_equal(aa[:,:,0],aa[:,:,1]) and np.array_equal(aa[:,:,0],aa[:,:,2])
                effective=Image.fromarray(np.repeat(aa[:,:,:1],4,axis=2))
                interpretation='Opaque grayscale source interpreted as I4 intensity in all four decoded channels'
            edit_mask=np.array(Image.open(ROOT/candidate['mask']).convert('L'))>0 if candidate.get('mask') else None
            encoded,decoded,mask=encode(raw,effective,row['format'],palette,edit_mask);assert len(encoded)==n
            diff=np.abs(np.array(effective).astype(int)-np.array(decoded).astype(int))
            stem=f'{code}-{index}';(out/f'{stem}.gx').write_bytes(encoded);decoded.save(out/f'{stem}.png')
            patches[file].append((start,encoded,row['id']))
            report.append({'code':code,'texture':row['id'],'candidate_path':candidate['path'],'candidate_sha256':candidate['sha256'],
                'format':row['format'],'source_interpretation':interpretation,'source_bytes':n,'encoded_sha256':sha(encoded),'original_noop_byte_exact':True,
                'outside_edit_mask_changed_pixels':0,'mask_pixels':int(mask.sum()),'encoding_error_max_rgba':diff.reshape(-1,4).max(0).tolist(),
                'encoding_error_mean_rgba':diff.reshape(-1,4).mean(0).tolist(),
                'encoded':f'work/graphics-encoding/{stem}.gx','preview':f'work/graphics-encoding/{stem}.png',
                'user_approval':bool(candidate.get('approval')) or bool(asset.get('reuse')),'runtime_verified':False})
            if index==0:previews.append((code,effective,decoded))
    container_report=[]
    for file,(path,original) in containers.items():
        view=bytearray(original);allowed=np.zeros(len(view),bool)
        for at,raw,id in patches[file]:
            if allowed[at:at+len(raw)].any():raise AssertionError('Overlapping selected texture ranges: '+id)
            view[at:at+len(raw)]=raw;allowed[at:at+len(raw)]=True
        assert np.array_equal(np.frombuffer(original,np.uint8)[~allowed],np.frombuffer(view,np.uint8)[~allowed])
        assert sha(path.read_bytes())==sha(original)
        aliases=[r['id'] for r in catalog if r['file']==file and r['id'] not in {x[2] for x in patches[file]}
                 and any(r['data_offset']<a+len(raw) and a<r['data_offset']+r['data_size'] for a,raw,_ in patches[file])]
        assert not aliases,aliases
        container_report.append({'file':file,'original_sha256':sha(original),'same_size':True,'headers_palettes_and_other_bytes_unchanged':True,'unselected_overlap':aliases})
    sheet=Image.new('RGB',(1000,len(previews)*220),'#333333');d=ImageDraw.Draw(sheet)
    for i,(code,before,after) in enumerate(previews):
        d.text((8,i*220+4),code+'   approved/draft PNG | GX decoded',fill='white')
        for x,im in [(0,before),(500,after)]:
            display=im.copy();display.thumbnail((490,195));sheet.paste(display,(x+5,i*220+22),display)
    sheet.save(out/'comparison.png')
    small=[(c,a,b) for c,a,b in previews if c in ['G0146','G0200','G0225','G0226','G0235']]
    zoom=Image.new('RGB',(1250,len(small)*400),'#555555');zd=ImageDraw.Draw(zoom)
    for i,(code,before,after) in enumerate(small):
        zd.text((4,i*400+2),code+' PNG | GX decoded (nearest x6)',fill='white')
        for x,im in [(0,before),(625,after)]:
            im=im.resize((im.width*6,im.height*6),Image.Resampling.NEAREST);zoom.paste(im,(x+4,i*400+25),im)
    zoom.save(out/'small-zoom.png')
    save(ROOT/'metadata/graphics_encoding_verification.json',{'textures':report,'containers':container_report,
        'groups':len(previews),'texture_count':len(report),'new_iso_built':False,'container_files_written':False,
        'limits':['Format quantization remains; inspect native decoded previews',
                  'CMPR endpoint search preserves RGBA outside edit mask but is not an optimal compressor',
                  'Pending user approvals remain pending; conversion is not approval or runtime validation']})
    print('PASS:',len(previews),'groups,',len(report),'textures;',len(containers),'unchanged-size container simulations. No container/ISO written.')

if __name__=='__main__':main()
