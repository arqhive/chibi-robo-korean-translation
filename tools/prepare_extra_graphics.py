"""Five user-selected graphic drafts; authorized precision compositing only.

Uses saved ImageGen 센티 lettering; source borders, numbers and background
outside glyph masks are immutable. Writes isolated PNG/GX drafts, no ISO.
"""
import json
from collections import Counter
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from inspect_discs import ROOT, save
from verify_graphics_encoding import encode, sha
from prepare_rgba8_comparison import encode_rgba8
from decode_gx import decode

FONT = ROOT / 'work/references/gmarket/GmarketSansBold.otf'
OUT = ROOT / 'work/graphics-extra'
GEN = ROOT / 'graphics/drafts/extra-source/centi-imagegen.png'
LABELS = {204: '그램', 2281: '12센티', 2282: '4센티', 2283: '8센티', 2284: '짐'}


def text_mask(text, height):
    font = ImageFont.truetype(str(FONT), height * 8)
    b = font.getbbox(text)
    a = Image.new('L', (b[2]-b[0]+16, b[3]-b[1]+16))
    ImageDraw.Draw(a).text((8-b[0], 8-b[1]), text, font=font, fill=255)
    return a.crop(a.getbbox())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    catalog = {r['id']: r for r in json.loads((ROOT/'metadata/graphics_catalog_jp.json').read_text('utf-8'))['images']}
    observations = json.loads((ROOT/'metadata/graphics_visual_observations.json').read_text('utf-8'))['groups']
    generated = np.array(Image.open(GEN).convert('L'))
    # Only dark source lettering; generated paper/background is never composited.
    alpha = np.clip((240-generated.astype(float))/210, 0, 1)
    alpha[generated > 220] = 0
    a = Image.fromarray((alpha*255).astype('uint8'))
    a = a.crop(a.getbbox()); a.thumbnail((48,22), Image.Resampling.LANCZOS)
    report = []
    for n, label in LABELS.items():
        code = f'G{n:04}'
        ob = next(o for o in observations if o['sheet_index']==n)
        asset = catalog[ob['ids'][0]]
        source = Image.open(ROOT/asset['png']).convert('RGBA')
        orig = np.array(source); clean = orig.copy(); h,w = orig.shape[:2]
        yy,xx = np.indices((h,w)); mask = Image.new('L',(w,h))
        protect = np.zeros((h,w),bool)
        if n in (2281,2282,2283):
            # Original letters start at y=36. Number4 ends at y=36 too;
            # preserve that stem separately, never erase the whole text box.
            roi = (yy>=36)&(yy<=61)&(xx>=2)&(xx<=61)
            if n==2282: roi &= ~((yy==36)&(xx>=19)&(xx<=23))
            old = roi & (orig[:,:,1]<220)
            # The decoded flat background varies slightly between CMPR blocks.
            # Reconstruct only ink pixels using same-block background if possible.
            for y,x in zip(*np.nonzero(old)):
                y0=y//4*4; x0=x//4*4
                block=orig[y0:y0+4,x0:x0+4]
                valid=(block[:,:,1]>=225)&(block[:,:,3]==255)
                if not valid.any():
                    y0=max(2,y-8);x0=max(2,x-8)
                    block=orig[y0:min(62,y+9),x0:min(62,x+9)]
                    valid=(block[:,:,1]>=225)&(block[:,:,3]==255)
                assert valid.any()
                clean[y,x] = Counter(map(tuple,block[valid])).most_common(1)[0][0]
            mask.paste(a,((w-a.width)//2,38))
            ink={2281:(209,168,121),2282:(207,123,209),2283:(189,131,148)}[n]
            protect=(yy<36)|(yy>=62)|(xx<2)|(xx>=62)
            if n==2282: protect |= ((yy==36)&(xx>=19)&(xx<=23))
        elif n==2284:
            old=(orig[:,:,:3]!=255).any(2)&(yy>2)&(yy<61)&(xx>1)&(xx<62)
            clean[old]=(255,255,255,255)
            a2=text_mask('짐',31)
            a2=a2.resize((round(a2.width/8),round(a2.height/8)),Image.Resampling.LANCZOS)
            mask.paste(a2,((w-a2.width)//2,17))
            ink=(103,0,122)
            protect=(yy<2)|(yy>=62)|(xx<1)|(xx>=63)
        else:
            old=orig[:,:,3]>0
            clean[old,3]=0
            # This tiny draft uses a horizontal line for readable Hangul.
            # Angle departure is explicitly presented for user review.
            a2=text_mask('그램',9).filter(ImageFilter.MinFilter(3))
            a2.thumbnail((16*8,16*8),Image.Resampling.LANCZOS)
            a2=a2.resize((round(a2.width/8),round(a2.height/8)),Image.Resampling.LANCZOS)
            # Original CMPR has binary transparency; preview the same alpha domain.
            a2=a2.point(lambda v:255 if v>=120 else 0)
            mask.paste(a2,((w-a2.width)//2,(h-a2.height)//2))
            ink=(255,255,255)
        new=np.array(mask)>0
        assert not new[protect].any()
        overlay=Image.new('RGBA',(w,h),(*ink,0));overlay.putalpha(mask)
        result=np.array(Image.alpha_composite(Image.fromarray(clean),overlay))
        # Keep hidden RGB exactly too; alpha_composite can rewrite invisible data.
        allowed=old|new;result[~allowed]=orig[~allowed]
        assert np.array_equal(orig[~allowed],result[~allowed])
        assert np.array_equal(orig[protect],result[protect])
        folder=ROOT/f'graphics/drafts/{code}/composite-v01';folder.mkdir(parents=True,exist_ok=True)
        for name, data in [('original',orig),('cleaned',clean),('korean',result),('edit-mask',allowed.astype('uint8')*255),('old-text-mask',old.astype('uint8')*255)]:
            Image.fromarray(data).save(folder/(name+'.png'))
        container=(ROOT/'work/roundtrip/jp/qp/files'/asset['file']).read_bytes()
        raw=container[asset['data_offset']:asset['data_offset']+asset['data_size']]
        assert sha(raw)==asset['raw_sha256']
        if asset['format']==6:
            encoded=encode_rgba8(Image.fromarray(result));decoded=decode(encoded,w,h,6)
        elif n==204:
            # 18x18 CMPR occupies24x24 storage. Padding is not displayed;
            # let its selectors adapt, while preserving every visible pixel
            # outside the glyph masks, including hidden RGB.
            padded=decode(raw,24,24,14)
            padded.paste(Image.fromarray(result),(0,0))
            am=np.ones((24,24),bool);am[:h,:w]=allowed
            encoded,full,_=encode(raw,padded,14,edit_mask=am)
            decoded=full.crop((0,0,w,h))
        else:
            encoded,decoded,_=encode(raw,Image.fromarray(result),asset['format'],edit_mask=allowed)
        assert len(encoded)==len(raw)
        decoded.save(folder/'encoded-preview.png');(folder/'texture.gx').write_bytes(encoded)
        dec=np.array(decoded);assert np.array_equal(dec[~allowed],orig[~allowed])
        assert np.array_equal(dec[protect],orig[protect])
        rgba8_proposal = None
        if n==204:
            lossless=encode_rgba8(Image.fromarray(result))
            lossless_image=decode(lossless,w,h,6)
            assert np.array_equal(np.array(lossless_image),result)
            (folder/'rgba8-proposal.gx').write_bytes(lossless)
            lossless_image.save(folder/'rgba8-proposal.png')
            rgba8_proposal=dict(format=6,bytes=len(lossless),sha256=sha(lossless),
                               approval=None,png_exact=True,reason='CMPR preserves outside-mask hidden RGB but forces dark Hangul pixels. RGBA8 draft avoids this without altering any unedited pixel.')
        record=dict(code=code,texture=asset['id'],label=label,source=asset['png'],
                    source_reading='グラム (拡大字形からの読み・実行文脈未確認)' if n==204 else {2281:'12センチ',2282:'4センチ',2283:'8センチ',2284:'荷物'}[n],
                    candidate_path=str((folder/'korean.png').relative_to(ROOT)).replace('\\','/'),
                    candidate_sha256=sha((folder/'korean.png').read_bytes()),
                    encoded_path=str((folder/'texture.gx').relative_to(ROOT)).replace('\\','/'),
                    encoded_sha256=sha(encoded),format=asset['format'],dimensions=[w,h],
                    outside_edit_mask_changed_pixels=0,protected_pixels_changed=0,
                    encoded_outside_edit_mask_changed_pixels=0,
                    encoded_max_error=np.abs(dec.astype(int)-result.astype(int)).max(axis=(0,1)).tolist(),
                    layout_note='18px readability draft: horizontal instead of source diagonal; approval pending' if n==204 else 'Original number, border and background retained; common centi glyphs across three boxes',
                    imagegen_used=n in (2281,2282,2283),approval=None,runtime_verified=False)
        if rgba8_proposal:record['rgba8_proposal']=rgba8_proposal
        save(folder/'verification.json',record);report.append(record)
    save(ROOT/'metadata/extra_graphics_drafts.json',dict(textures=report,new_iso_built=False,
         imagegen_source=str(GEN.relative_to(ROOT)).replace('\\','/'),imagegen_source_sha256=sha(GEN.read_bytes())))
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    main()
