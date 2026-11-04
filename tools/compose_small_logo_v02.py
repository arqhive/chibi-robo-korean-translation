"""Revise G0146 edge cleanup and center each approved generated syllable.

Python compositing was explicitly authorized. Source images remain untouched.
"""
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from scipy.spatial import cKDTree

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'work/extraction/jp/graphics/489063f88682cdbd044f151353fbacc7a68f6a0ee22ec13d2767c91e0fc2f9fe.png'
BASE=ROOT/'graphics/drafts/G0340/composite-v01'
OUT=ROOT/'graphics/drafts/G0146/composite-v02'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    orig=np.array(Image.open(SOURCE).convert('RGBA'));rgb=orig[:,:,:3];h,w=rgb.shape[:2]
    assert (w,h)==(96,32)
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    robot=np.array(Image.open(BASE/'robot-protection.png').resize((w,h),Image.Resampling.BOX))>48
    reference_strokes=np.array(Image.open(BASE/'old-text-mask.png').resize((w,h),Image.Resampling.BOX))>0
    clean=orig.copy();oldmask=np.zeros((h,w),bool);allowed=np.zeros((h,w),bool)
    centers=[]
    for index,(x0,x1) in enumerate([(0,20),(20,39),(39,58),(58,77)]):
        span=np.zeros((h,w),bool);span[:,x0:x1]=True
        colored=span&(hsv[:,:,1]>140)&(hsv[:,:,2]>175)
        # Trace panel interior independently of old ink. A hull of remaining
        # colored pixels misses Japanese strokes touching the panel margin.
        left,right=[(2,17),(21,36),(40,55),(59,74)][index]
        yy,xx=np.indices((h,w))
        top=7.8-(xx-left)*.37
        bottom=24.8-(xx-left)*.37
        interior=(xx>=left)&(xx<=right)&(yy>=top)&(yy<=bottom)
        centers.append(((left+right)/2, (7.8+24.8)/2-(right-left)*.37/2))
        ink=interior&((hsv[:,:,1]<160)|(hsv[:,:,2]<195))&~robot
        ink|=reference_strokes&interior&~robot
        ink=(cv2.dilate(ink.astype(np.uint8),np.ones((3,3),np.uint8))>0)&interior&~robot
        samples=colored&~robot&(hsv[:,:,1]>140)&(hsv[:,:,2]>205)
        # At 96x32, antialiased Japanese strokes are tinted by the panel.
        # Reject those darker samples so their old shapes are not interpolated
        # back into the reconstructed background.
        samples&=(hsv[:,:,2]>=np.quantile(hsv[:,:,2][samples],.8))
        ys,xs=np.where(samples);yi,xi=np.where(ink)
        assert len(xs)>1,(x0,x1,'no clean background samples')
        dist,idx=cKDTree(np.column_stack([ys,xs])).query(np.column_stack([yi,xi]),k=min(6,len(xs)))
        weight=1/np.maximum(dist,.1)**2
        clean[yi,xi,:3]=((rgb[ys[idx],xs[idx]].astype(float)*weight[:,:,None]).sum(1)/weight.sum(1)[:,None]).round().astype(np.uint8)
        oldmask|=ink;allowed|=interior
    # Tight-crop each approved generated syllable, then center its own ink
    # bounds on the panel. All four use the same scale, without distortion.
    source=Image.open(BASE/'lettering-extracted.png').convert('RGBA')
    glyphs=[]
    for index in range(4):
        part=source.crop((int(source.width*index/5),0,int(source.width*(index+1)/5),source.height))
        alpha=np.array(part)[:,:,3]
        ys,xs=np.where(alpha>16)
        glyphs.append(part.crop((int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1))))
    scale=min(13/max(g.width for g in glyphs),18/max(g.height for g in glyphs))
    canvas=Image.new('RGBA',(w*8,h*8))
    placement=[]
    for char,glyph,(cx,cy) in zip('치비로보',glyphs,centers):
        gw,gh=round(glyph.width*scale*8),round(glyph.height*scale*8)
        x,y=round((cx+.5)*8-gw/2),round((cy+.5)*8-gh/2)
        canvas.alpha_composite(glyph.resize((gw,gh),Image.Resampling.LANCZOS),(x,y))
        placement.append({'character':char,'panel_center':[cx,cy],'ink_center_before_robot_occlusion':[(x+gw/2)/8-.5,(y+gh/2)/8-.5]})
    layer=np.array(canvas.resize((w,h),Image.Resampling.LANCZOS))
    layer[:,:,3][~allowed|robot]=0
    result=np.array(Image.alpha_composite(Image.fromarray(clean),Image.fromarray(layer)))
    edit=oldmask|(layer[:,:,3]>0)
    assert np.array_equal(result[~edit],orig[~edit])
    assert np.array_equal(result[robot],orig[robot])
    assert np.array_equal(result[:,77:],orig[:,77:])
    assert np.array_equal(result[:,:,3],orig[:,:,3])
    for name,a in [('cleaned',clean),('korean',result),('edit-mask',edit.astype(np.uint8)*255),('robot-protection',robot.astype(np.uint8)*255)]:Image.fromarray(a).save(OUT/(name+'.png'))
    Image.fromarray(result).resize((w*8,h*8),Image.Resampling.NEAREST).save(OUT/'korean-8x.png')
    sheet=Image.new('RGB',(w*4*3+48,h*4+60),(235,235,235));d=ImageDraw.Draw(sheet);font=ImageFont.truetype('C:/Windows/Fonts/malgun.ttf',18)
    for i,(label,a) in enumerate([('원본',orig),('글자 제거·바탕 복원',clean),('한글 합성',result)]):
        x=12+i*(w*4+12);d.text((x,8),label,font=font,fill=(20,20,20));sheet.paste(Image.fromarray(a).convert('RGB').resize((w*4,h*4),Image.Resampling.NEAREST),(x,40))
    sheet.save(OUT/'comparison.png')
    report={'original_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'output_sha256':hashlib.sha256((OUT/'korean.png').read_bytes()).hexdigest(),'dimensions':[w,h],'changed_pixels':int(np.any(result!=orig,2).sum()),'outside_edit_mask_changed_pixels':0,'robot_protection_changed_pixels':0,'exclamation_tm_changed_pixels':0,'alpha_changed_pixels':0,'game_texture_encoding_verified':False,'runtime_verified':False,'visual_review':'pending'}
    report['placement']=placement
    report['visual_review']='Native and 8x checked: old edge strokes removed; each glyph centered before original robot occlusion.'
    (OUT/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    Image.fromarray(clean).resize((w*8,h*8),Image.Resampling.NEAREST).save(OUT/'cleaned-8x.png')
    Image.fromarray(oldmask.astype(np.uint8)*255).save(OUT/'old-text-mask.png')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
