"""Fit imagegen scream lettering to original transparent effects; retain !!!."""
import hashlib,json
from pathlib import Path
import cv2,numpy as np
from PIL import Image,ImageDraw,ImageFont,ImageFilter
ROOT=Path(__file__).resolve().parents[1]
ASSETS={
 'G0775':('24ffd2152e25360fa2b2eab46123ea583db5ec52c42ccd6ab62d5ee4541e12a3',208,(6,39,201,115)),
 'G0776':('cab648804b3574c5fd365b2fb590478edcac4021273a81d336f078525209c246',198,(3,4,190,113)),
}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main(revision='v02',outline_px=2):
    summary=Image.new('RGB',(620,240),'#454545');sd=ImageDraw.Draw(summary)
    font=ImageFont.truetype('C:/Windows/Fonts/malgun.ttf',17)
    for idx,(code,(pixel,cut,(tx,ty,tw,th))) in enumerate(ASSETS.items()):
        source=ROOT/f'work/extraction/jp/graphics/{pixel}.png'
        gen=ROOT/f'graphics/drafts/{code}/imagegen-v01.png'
        out=ROOT/f'graphics/drafts/{code}/composite-{revision}';out.mkdir(parents=True,exist_ok=True)
        orig=np.array(Image.open(source).convert('RGBA'));h,w=orig.shape[:2]
        a=np.array(Image.open(gen).convert('RGBA'))
        # Generated near-transparent (alpha 1) speckles are not part of the
        # letter silhouette. Keep major solid components, including Hangul jamo.
        raw=(a[:,:,3]>128).astype(np.uint8)
        n,labels,stats,_=cv2.connectedComponentsWithStats(raw,8)
        keep=np.flatnonzero(stats[:,cv2.CC_STAT_AREA]>60);keep=keep[keep!=0]
        mask=np.isin(labels,keep).astype(np.uint8)*255
        if code=='G0776':
            # Generation contains one extra 아. Its two connected components
            # are separate from all approved letters; remove those components
            # and move the final 악 along the same downward flow.
            assert stats[7].tolist()==[1026,556,168,154,18658]
            assert stats[8].tolist()==[1147,560,171,224,16878]
            mask[np.isin(labels,[7,8,9,10,11])]=0
            final=np.isin(labels,[9,10,11]).astype(np.uint8)*255
            shifted=cv2.warpAffine(final,np.float32([[1,0,-300],[0,1,-160]]),(mask.shape[1],mask.shape[0]),flags=cv2.INTER_NEAREST)
            mask=np.maximum(mask,shifted)
        ys,xs=np.where(mask>0)
        glyph=Image.fromarray(mask).crop((int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1)))
        scale=min(tw/glyph.width,th/glyph.height)
        size=(round(glyph.width*scale),round(glyph.height*scale))
        alpha=Image.new('L',(w,h));alpha.paste(glyph.resize(size,Image.Resampling.LANCZOS),(tx,ty+(th-size[1])//2))
        stroke=alpha.filter(ImageFilter.MaxFilter(outline_px*2+1))
        na=np.array(stroke)
        protect=np.zeros((h,w),bool);protect[:,cut:]=orig[:,cut:,3]>0
        # Preserve all original punctuation stroke and antialias pixels.
        # Expanded Korean outline may occupy transparent pixels beside them.
        assert not np.array(alpha)[protect].any()
        na[protect]=0;stroke=Image.fromarray(na)
        oldmask=(orig[:,:,3]>0)&~protect
        clean=orig.copy();clean[oldmask]=0
        dark=Image.new('RGBA',(w,h),(0,0,0,0));dark.putalpha(stroke)
        white=Image.new('RGBA',(w,h),'white');white.putalpha(alpha)
        layer=Image.alpha_composite(dark,white)
        result=np.array(Image.alpha_composite(Image.fromarray(clean),layer))
        edit=oldmask|(na>0)
        assert np.array_equal(orig[~edit],result[~edit])
        assert np.array_equal(orig[protect],result[protect])
        for name,data in [('korean',result),('cleaned',clean),('edit-mask',edit*255),('old-text-mask',oldmask*255),('protected-art',protect*255)]:
            Image.fromarray(np.asarray(data,dtype=np.uint8)).save(out/(name+'.png'))
        Image.fromarray(result).resize((w*3,h*3),Image.Resampling.NEAREST).save(out/'korean-3x.png')
        sheet=Image.new('RGB',(w*3+48,h+60),'#454545');d=ImageDraw.Draw(sheet)
        for j,(title,im) in enumerate([('원본',orig),('글자 제거',clean),('한글 합성',result)]):
            x=12+j*(w+12);d.text((x,8),title,font=font,fill='white');im=Image.fromarray(im);sheet.paste(im,(x,42),im)
        sheet.save(out/'comparison.png')
        sd.text((idx*310+12,8),code,font=font,fill='white');im=Image.fromarray(result);summary.paste(im,(idx*310+12,48),im)
        report={'asset':code,'original_sha256':sha(source),'lettering_source_sha256':sha(gen),'output_sha256':sha(out/'korean.png'),
            'dimensions':[w,h],'lettering_scale':scale,'outside_edit_mask_changed_pixels':0,'protected_art_changed_pixels':0,
            'outline_px':outline_px,'revision':revision,
            'alpha_changed_pixels':int((orig[:,:,3]!=result[:,:,3]).sum()),'alpha_outside_edit_mask_changed_pixels':0,
            'alpha_note':'Transparent texture: old text alpha removed and new letter alpha inserted; original punctuation alpha unchanged.',
            'encoding_verified':False,'runtime_verified':False,'visual_review':'pending'}
        (out/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))
    summary.save(ROOT/f'work/graphics-review/scream-effects-{revision}.png')
if __name__=='__main__':main()
