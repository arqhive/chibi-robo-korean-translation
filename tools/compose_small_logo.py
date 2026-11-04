"""Reuse approved title lettering in the native 96x32 logo/banner.

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
OUT=ROOT/'graphics/drafts/G0146/composite-v01'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    orig=np.array(Image.open(SOURCE).convert('RGBA'));rgb=orig[:,:,:3];h,w=rgb.shape[:2]
    assert (w,h)==(96,32)
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    robot=np.array(Image.open(BASE/'robot-protection.png').resize((w,h),Image.Resampling.BOX))>48
    reference_strokes=np.array(Image.open(BASE/'old-text-mask.png').resize((w,h),Image.Resampling.BOX))>0
    clean=orig.copy();oldmask=np.zeros((h,w),bool);allowed=np.zeros((h,w),bool)
    for x0,x1 in [(0,20),(20,39),(39,58),(58,77)]:
        span=np.zeros((h,w),bool);span[:,x0:x1]=True
        colored=span&(hsv[:,:,1]>140)&(hsv[:,:,2]>175)
        hull=np.zeros((h,w),np.uint8)
        cv2.fillConvexPoly(hull,cv2.convexHull(np.column_stack(np.where(colored)[::-1]).astype(np.int32)),255)
        interior=cv2.erode(hull,np.ones((3,3),np.uint8))>0
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
    layer=np.array(Image.open(BASE/'lettering-extracted.png').resize((w,h),Image.Resampling.LANCZOS))
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
    (OUT/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(report))


if __name__=='__main__':main()
