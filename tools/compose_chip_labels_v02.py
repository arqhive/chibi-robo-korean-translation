"""Uniform chip typography, using authorized Python precision compositing.

The gold chip, frame and NEW mark remain source pixels. No ISO build.
"""
import hashlib,json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont,ImageFilter
from compose_item_icons import SOURCES,ROOT

LABELS={'G0225':'보청','G0226':'모아','G0235':'멀리'}
FONT=ROOT/'work/references/gmarket/GmarketSansBold.otf'
SCALE=8

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    font=ImageFont.truetype(str(FONT),10*SCALE)
    boxes=[font.getbbox(t) for t in LABELS.values()]
    bounds=(min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes))
    preview=Image.new('RGB',(3*320,460),'#dddddd')
    pd=ImageDraw.Draw(preview);pf=ImageFont.truetype('C:/Windows/Fonts/malgun.ttf',20)
    reports=[]
    for i,(code,label) in enumerate(LABELS.items()):
        out=ROOT/f'graphics/drafts/{code}/composite-v02';out.mkdir(parents=True,exist_ok=True)
        previous=ROOT/f'graphics/drafts/{code}/composite-v01'
        source=ROOT/f'work/extraction/jp/graphics/{SOURCES[code]}.png'
        orig=np.array(Image.open(source).convert('RGBA'))
        clean=Image.open(previous/'cleaned.png').convert('RGBA')
        oldmask=np.array(Image.open(previous/'old-text-mask.png'))>0
        protect=np.array(Image.open(previous/'protected-art.png'))>0
        # Common font size, metrics, baseline and angle. No per-label stretch.
        a=Image.new('L',(bounds[2]-bounds[0]+4*SCALE,bounds[3]-bounds[1]+4*SCALE))
        ImageDraw.Draw(a).text((2*SCALE-bounds[0],2*SCALE-bounds[1]),label,font=font,fill=255)
        a=a.rotate(8,Image.Resampling.BICUBIC,expand=True)
        mask=Image.new('L',(48*SCALE,48*SCALE))
        mask.paste(a,(round(31*SCALE-a.width/2),round(36*SCALE-a.height/2)))
        stroke=mask.filter(ImageFilter.MaxFilter(2*SCALE+1))
        dark=Image.new('RGBA',mask.size,(24,24,24,0));dark.putalpha(stroke)
        white=Image.new('RGBA',mask.size,'white');white.putalpha(mask)
        overlay=Image.alpha_composite(dark,white).resize((48,48),Image.Resampling.LANCZOS)
        layer=np.array(overlay)
        # LANCZOS can create negligible outer lobes; cut them outside label ROI.
        assert layer[:,:,3][protect].max(initial=0)<=4
        layer[protect]=0
        result=np.array(Image.alpha_composite(clean,Image.fromarray(layer)))
        newmask=layer[:,:,3]>0;edit=oldmask|newmask
        assert np.array_equal(orig[~edit],result[~edit])
        assert np.array_equal(orig[protect],result[protect])
        assert np.array_equal(orig[:,:,3],result[:,:,3])
        for name,data in [('korean',result),('cleaned',np.array(clean)),('edit-mask',edit*255),('old-text-mask',oldmask*255),('protected-art',protect*255)]:
            Image.fromarray(np.asarray(data,dtype=np.uint8)).save(out/(name+'.png'))
        Image.fromarray(result).resize((384,384),Image.Resampling.NEAREST).save(out/'korean-8x.png')
        sheet=Image.new('RGB',(936,350),'#dddddd');d=ImageDraw.Draw(sheet)
        for j,(title,im) in enumerate([('원본',Image.fromarray(orig)),('바탕 복원',clean),('통일한 글자',Image.fromarray(result))]):
            d.text((12+j*308,6),title,font=pf,fill='black')
            im=im.resize((288,288),Image.Resampling.NEAREST);sheet.paste(im,(12+j*308,44),im)
        sheet.save(out/'comparison.png')
        pd.text((i*320+12,8),code+' · '+label,font=pf,fill='black')
        im=Image.fromarray(result).resize((288,288),Image.Resampling.NEAREST)
        preview.paste(im,(i*320+12,44),im)
        native=Image.fromarray(result);preview.paste(native,(i*320+132,365),native)
        report={'asset':code,'dimensions':[48,48],'original_sha256':sha(source),'output_sha256':sha(out/'korean.png'),
            'font':'Gmarket Sans Bold','font_sha256':sha(FONT),'font_size_px':10,'angle_degrees':8,
            'outline_px':1,'fill_rgb':[255,255,255],'outline_rgb':[24,24,24],'label_center':[31,36],
            'shared_metrics_bounds':bounds,'outside_edit_mask_changed_pixels':0,'protected_art_changed_pixels':0,'alpha_changed_pixels':0,
            'encoding_verified':False,'runtime_verified':False,'visual_review':'pending'}
        (out/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        reports.append(report)
    preview.save(ROOT/'work/graphics-review/chip-labels-v02.png')
    print(json.dumps(reports,ensure_ascii=False))

if __name__=='__main__':main()
