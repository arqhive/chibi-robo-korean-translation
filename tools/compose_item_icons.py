"""Use imagegen lettering and precise original-pixel masks for four item icons.

Python editing explicitly authorized by user. No texture encoding or ISO build.
Chip restoration donor is the matching unlettered icon in user's US image.
"""
from pathlib import Path
import hashlib,json
import cv2
import numpy as np
from PIL import Image,ImageDraw,ImageFont,ImageFilter

ROOT=Path(__file__).resolve().parents[1]
SOURCES={
 'G0200':'23717beb3002cd0306becb6fc2a0079aa8852b92892953b9e4d530d8a9b8d1e2',
 'G0225':'d23ab35117c9ed04601ac4546790b51bdb4e1badc117d07b9f21cfb6e9f60eb8',
 'G0226':'4a9e04b48e124b879356641b25bc9c6ae6f8a8ca0fcb2d8f49c26e74aede34b1',
 'G0235':'80a021a55e5cd52188ec883dea9228e72d026768a50674a444b8c9d9335cf98e',
}
DONOR=ROOT/'work/extraction/us/graphics/7019b57b0ca678054cf30fa27f25694f0be14cbaf26a83f30f00d3433c9d13f4.png'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def lettering(code):
    path=ROOT/f'graphics/drafts/{code}/imagegen-v01.png'
    a=np.array(Image.open(path).convert('RGBA'));rgb=a[:,:,:3].astype(float);h,w=a.shape[:2]
    if code=='G0200':
        mask=np.clip((rgb.min(2)-20)/235,0,1)
    else:
        roi=np.zeros((h,w),bool)
        if code=='G0225':roi[int(h*.61):int(h*.90),int(w*.17):int(w*.81)]=True
        else:roi[int(h*.59):int(h*.88),int(w*.43):int(w*.88)]=True
        mask=np.clip((rgb.min(2)-180)/65,0,1)*roi
        mask*=((rgb.max(2)-rgb.min(2))<30)
    mask*=a[:,:,3]/255
    ys,xs=np.where(mask>.25);bbox=(int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1))
    return Image.fromarray((mask*255).round().astype(np.uint8)).crop(bbox),bbox


def main():
    reports=[];donor=np.array(Image.open(DONOR).convert('RGBA'))
    font=ImageFont.truetype('C:/Windows/Fonts/malgun.ttf',17)
    for code,pixel in SOURCES.items():
        source=ROOT/f'work/extraction/jp/graphics/{pixel}.png';orig=np.array(Image.open(source).convert('RGBA'));h,w=orig.shape[:2]
        out=ROOT/f'graphics/drafts/{code}/composite-v01';out.mkdir(parents=True,exist_ok=True)
        fill,box=lettering(code);fill.save(out/'lettering-mask-source.png')
        if code=='G0200':
            # Stroke/AA mask only. Flat-black background has no pictorial layer.
            ink=orig[:,:,:3].max(2)>12
            oldmask=cv2.dilate(ink.astype(np.uint8),np.ones((3,3),np.uint8))>0
            clean=orig.copy();clean[oldmask,:3]=0
            fill=fill.resize((16,15),Image.Resampling.LANCZOS)
            a=Image.new('L',(w,h));a.paste(fill,(1,2))
            newmask=np.array(a)>0
            overlay=Image.new('RGBA',(w,h),'white');overlay.putalpha(a)
            result=np.array(Image.alpha_composite(Image.fromarray(clean),overlay))
            protect=~(oldmask|newmask)
        else:
            # Native donor agrees on geometry and frame. Restrict restoring to
            # label-adjacent differences, not whole tiles or rectangular pastes.
            difference=np.abs(orig.astype(int)-donor.astype(int)).max(2)
            roi=np.zeros((h,w),bool);roi[29:44,7:44]=True
            seeds=(difference>18)&roi
            oldmask=(cv2.dilate(seeds.astype(np.uint8),np.ones((3,3),np.uint8))>0)&roi
            clean=orig.copy();clean[oldmask]=donor[oldmask]
            # New white glyphs with a common one-native-pixel dark outline.
            if code=='G0225':target=(25,11);position=(11,31)
            else:target=(22,12);position=(21,30)
            fill=fill.resize(target,Image.Resampling.LANCZOS)
            a=Image.new('L',(w,h));a.paste(fill,position)
            stroke=a.filter(ImageFilter.MaxFilter(3))
            shadow=Image.new('RGBA',(w,h),(24,24,24,0));shadow.putalpha(stroke)
            white=Image.new('RGBA',(w,h),'white');white.putalpha(a)
            overlay=Image.alpha_composite(shadow,white)
            newmask=np.array(overlay.getchannel('A'))>0
            result=np.array(Image.alpha_composite(Image.fromarray(clean),overlay))
            protect=np.ones((h,w),bool);protect[29:44,7:44]=False
            assert not newmask[protect].any()
            assert np.array_equal(orig[protect],result[protect])
            assert np.array_equal(orig[:,:,3],result[:,:,3])
        edit=oldmask|newmask
        assert np.array_equal(orig[~edit],result[~edit])
        assert np.array_equal(orig[:,:,3],result[:,:,3])
        for name,a in [('korean',result),('cleaned',clean),('edit-mask',edit.astype(np.uint8)*255),('old-text-mask',oldmask.astype(np.uint8)*255),('protected-art',protect.astype(np.uint8)*255)]:Image.fromarray(a).save(out/(name+'.png'))
        Image.fromarray(result).resize((w*8,h*8),Image.Resampling.NEAREST).save(out/'korean-8x.png')
        panelw=max(w*6,160);sheet=Image.new('RGB',(panelw*3+48,h*6+60),(230,230,230));d=ImageDraw.Draw(sheet)
        for i,(title,a) in enumerate([('원본',orig),('글자 제거·바탕 복원',clean),('한글 합성',result)]):
            x=12+i*(panelw+12);d.text((x,8),title,font=font,fill=(20,20,20));im=Image.fromarray(a).resize((w*6,h*6),Image.Resampling.NEAREST);sheet.paste(im,(x,40),im)
        sheet.save(out/'comparison.png')
        report={'asset':code,'original_sha256':sha(source),'lettering_source_sha256':sha(ROOT/f'graphics/drafts/{code}/imagegen-v01.png'),'donor':str(DONOR.relative_to(ROOT)) if code!='G0200' else None,'donor_sha256':sha(DONOR) if code!='G0200' else None,'lettering_crop':box,'dimensions':[w,h],'changed_pixels':int(np.any(orig!=result,2).sum()),'outside_edit_mask_changed_pixels':int(np.any(orig[~edit]!=result[~edit],1).sum()),'protected_art_changed_pixels':int(np.any(orig[protect]!=result[protect],1).sum()),'alpha_changed_pixels':int((orig[:,:,3]!=result[:,:,3]).sum()),'output_sha256':sha(out/'korean.png'),'visual_review':'pending','encoding_verified':False,'runtime_verified':False}
        (out/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');reports.append(report)
    print(json.dumps(reports,ensure_ascii=False))


if __name__=='__main__':main()
