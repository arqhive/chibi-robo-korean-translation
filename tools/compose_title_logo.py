"""Composite approved imagegen lettering onto original G0340; no game injection.

User authorized Python precision masking/compositing on 2026-10-14.
Only stroke-shaped old-text masks are restored. Panel edges, robot, punctuation,
TM and all pixels outside the explicit edit mask retain their source values.
"""
import hashlib
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import distance_transform_edt
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
LETTERING = ROOT / 'graphics/drafts/G0340/imagegen-lettering-source-v01.png'


def polygon(shape, points):
    m = np.zeros(shape, np.uint8)
    cv2.fillPoly(m, [np.array(points, np.int32)], 255)
    return m > 0


def extract_letters(rgb):
    """Unmix grayscale ink from the colored supporting image; discard its panels."""
    h, w = rgb.shape[:2]
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    layer = np.zeros((h, w, 4), np.uint8)
    for index in range(4):
        span = np.zeros((h, w), bool)
        span[:, int(w*index/5):int(w*(index+1)/5)] = True
        bg = span & (hsv[:,:,1] > 180) & (hsv[:,:,2] > 190)
        points = np.column_stack(np.where(bg)[::-1]).astype(np.int32)
        hull = np.zeros((h,w), np.uint8)
        cv2.fillConvexPoly(hull, cv2.convexHull(points), 255)
        interior = cv2.erode(hull, np.ones((27,27),np.uint8)) > 0
        ink = interior & ((hsv[:,:,1] < 110) | (hsv[:,:,2] < 160))
        ink = (cv2.dilate(ink.astype(np.uint8),np.ones((7,7),np.uint8)) > 0) & interior
        good = bg & ~ink
        _, indices = distance_transform_edt(~good, return_indices=True)
        background = rgb[indices[0], indices[1]].astype(float)
        pixel = rgb.astype(float)
        chroma = pixel.max(2)-pixel.min(2)
        bg_chroma = np.maximum(background.max(2)-background.min(2),1)
        alpha = np.clip(1-chroma/bg_chroma,0,1) * ink
        gray = np.clip(((pixel-(1-alpha[:,:,None])*background).mean(2))/np.maximum(alpha,.001),0,255)
        part = np.dstack([gray,gray,gray,alpha*255]).round().astype(np.uint8)
        layer[ink] = part[ink]
    return Image.fromarray(layer)


def main(code='G0340'):
    originals={
        'G0340':'6235fee12d2e74a86817f048016291d9b94d32ef4e70305bcb0955c4c34bc8eb',
        'G0343':'f8c98c6dcf1dc0321c2db65a897e425f8f84fbbcf937741edf9933d38f0f4d59',
        'G0344':'fb8f3dc5bc2ad0c535b1e5d192edb07c91e5e016ebac7ceecf8ad1eec8ad2d3e',
    }
    ORIGINAL=ROOT/'work/extraction/jp/graphics'/f'{originals[code]}.png'
    OUT=ROOT/'graphics/drafts'/code/'composite-v01'
    OUT.mkdir(parents=True,exist_ok=True)
    original = np.array(Image.open(ORIGINAL).convert('RGBA'))
    rgb = original[:,:,:3];h,w = rgb.shape[:2]
    # Trace the robot body and cable independently; no large rectangular restore.
    body = polygon((h,w),[(218,64),(221,61),(225,61),(230,62),(234,65),(239,66),
        (245,69),(250,70),(253,73),(259,75),(261,79),(258,81),(254,79),
        (251,79),(250,87),(246,89),(242,93),(240,103),(237,115),(231,119),
        (225,120),(225,115),(229,111),(228,108),(229,101),(229,96),(230,89),
        (229,84),(229,79),(230,76),(226,75),(223,73),(220,72),(218,68)])
    cable=np.zeros((h,w),np.uint8)
    cv2.polylines(cable,[np.array([(254,77),(259,79),(263,83),(267,89),(271,96),
        (275,104),(278,111),(279,119),(277,125),(273,129),(269,131),
        (264,130),(260,127),(257,122),(253,115),(248,110),(244,108),(239,106)],np.int32)],False,255,5)
    # Native pixel inspection: the cord crosses Japanese strokes. Protect its
    # actual per-row silhouette rather than an overly wide idealized line.
    cable[:107,:]=0
    cord_edges=[(254,261),(254,262),(256,263),(257,263),(258,264),(259,264),
        (260,265),(260,265),(261,266),(262,267),(262,268),(263,269),(263,269),
        (264,270),(265,271),(266,272),(267,273),(268,274),(269,275),(270,276),
        (271,276),(272,277),(273,277),(273,278),(274,279),(275,279),(275,280),
        (276,280),(277,281),(277,281)]
    for y,(left,right) in enumerate(cord_edges,77):cable[y,left:right+1]=255
    protect = body | (cable>0)
    clean=original.copy();oldmask=np.zeros((h,w),bool);allowed=np.zeros((h,w),bool)
    colors=[(255,130,16),(181,223,41),(255,243,49),(181,223,41)]
    for index,color in enumerate(colors):
        hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
        span=np.zeros((h,w),bool);span[:,index*84:index*84+82]=True
        colored=span&(hsv[:,:,1]>170)&(hsv[:,:,2]>190)
        hull=np.zeros((h,w),np.uint8)
        cv2.fillConvexPoly(hull,cv2.convexHull(np.column_stack(np.where(colored)[::-1]).astype(np.int32)),255)
        roi=cv2.erode(hull,np.ones((3,3),np.uint8))>0
        # Chroma detects gray/black/white strokes, including tinted antialias edges.
        pix=rgb.astype(float);chroma=pix.max(2)-pix.min(2)
        c=np.array(color);bc=float(c.max()-c.min())
        ink=roi & ((chroma<bc*.91) | (pix[:,:,2]>85)) & ~protect
        ink=(cv2.dilate(ink.astype(np.uint8),np.ones((3,3),np.uint8))>0)&roi&~protect
        sample=roi & ~ink & ~protect & (chroma>bc*.92) & (pix[:,:,2]<80)
        ys,xs=np.where(sample); yi,xi=np.where(ink)
        tree=cKDTree(np.column_stack([ys,xs]));dist,idx=tree.query(np.column_stack([yi,xi]),k=12)
        weight=1/np.maximum(dist,.1)**2
        values=(rgb[ys[idx],xs[idx]].astype(float)*weight[:,:,None]).sum(1)/weight.sum(1)[:,None]
        clean[yi,xi,:3]=values.round().astype(np.uint8)
        oldmask|=ink;allowed|=roi
    letters=extract_letters(np.array(Image.open(LETTERING).convert('RGB')))
    letters.save(OUT/'lettering-extracted.png')
    letters=letters.resize((w,h),Image.Resampling.LANCZOS)
    l=np.array(letters);l[:,:,3][~allowed|protect]=0
    letters=Image.fromarray(l)
    composite=np.array(Image.alpha_composite(Image.fromarray(clean),letters))
    newmask=l[:,:,3]>0;edit=oldmask|newmask
    outside=np.any(composite!=original,axis=2)&~edit
    assert not outside.any()
    assert np.array_equal(composite[protect],original[protect])
    assert np.array_equal(composite[:,333:],original[:,333:])
    assert np.array_equal(composite[:,:,3],original[:,:,3])
    files={'cleaned.png':clean,'korean.png':composite,'edit-mask.png':edit.astype(np.uint8)*255,
           'old-text-mask.png':oldmask.astype(np.uint8)*255,'robot-protection.png':protect.astype(np.uint8)*255}
    for name,a in files.items():Image.fromarray(a).save(OUT/name)
    Image.fromarray(composite).resize((w*4,h*4),Image.Resampling.NEAREST).save(OUT/'korean-4x.png')
    fontpath=Path('C:/Windows/Fonts/malgun.ttf')
    font=ImageFont.truetype(str(fontpath),18)
    sheet=Image.new('RGB',(w*3+48,h+64),(235,235,235));draw=ImageDraw.Draw(sheet)
    for i,(title,a) in enumerate([('원본',original),('글자 제거·바탕 복원',clean),('한글 합성',composite)]):
        x=12+i*(w+12);draw.text((x,8),title,font=font,fill=(20,20,20));sheet.paste(Image.fromarray(a).convert('RGB'),(x,40))
    sheet.save(OUT/'comparison.png')
    report={'original_sha256':hashlib.sha256(ORIGINAL.read_bytes()).hexdigest(),
        'lettering_sha256':hashlib.sha256(LETTERING.read_bytes()).hexdigest(),
        'dimensions':[w,h],'changed_pixels':int(np.any(composite!=original,axis=2).sum()),
        'old_text_mask_pixels':int(oldmask.sum()),'new_text_mask_pixels':int(newmask.sum()),
        'outside_edit_mask_changed_pixels':int(outside.sum()),
        'robot_protection_changed_pixels':int(np.any(composite[protect]!=original[protect],axis=1).sum()),
        'exclamation_tm_changed_pixels':int(np.any(composite[:,333:]!=original[:,333:],axis=2).sum()),
        'alpha_changed_pixels':int((composite[:,:,3]!=original[:,:,3]).sum()),
        'output_sha256':hashlib.sha256((OUT/'korean.png').read_bytes()).hexdigest(),
        'visual_review':'pending','game_texture_encoding_verified':False,'runtime_verified':False}
    (OUT/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main(sys.argv[1] if len(sys.argv)>1 else 'G0340')
