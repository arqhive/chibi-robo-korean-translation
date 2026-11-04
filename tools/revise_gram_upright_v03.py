"""Position upright ImageGen syllables diagonally. Never rotate or shear.

Only G0204 is revised. Other latest drafts are referenced without modification.
"""
import json
import numpy as np
from PIL import Image
from scipy import ndimage
from inspect_discs import ROOT, save
from prepare_rgba8_comparison import encode_rgba8
from decode_gx import decode
from verify_graphics_encoding import sha
from revise_extra_graphics_v02 import render

SOURCE=ROOT/'graphics/drafts/extra-source/gram-upright-imagegen-v03.png'


def main():
    report=json.loads((ROOT/'metadata/extra_graphics_drafts_v02.json').read_text('utf-8'))
    rows=report['textures'];r=next(r for r in rows if r['code']=='G0204')
    base=ROOT/'graphics/drafts/G0204/composite-v01'
    folder=base.parent/'composite-v03';folder.mkdir(parents=True,exist_ok=True)
    source=Image.open(base/'original.png').convert('RGBA');original=np.array(source)
    clean=Image.open(base/'cleaned.png').convert('RGBA')
    generated=Image.open(SOURCE).convert('RGBA');alpha=generated.getchannel('A')
    assert alpha.getextrema()[0]==0
    ink=ndimage.binary_opening(np.array(alpha)>180,iterations=2)
    labels,_=ndimage.label(ink);areas=np.bincount(labels.ravel());areas[0]=0
    ink=np.isin(labels,np.flatnonzero(areas>=500))
    alpha=Image.fromarray(ink.astype('uint8')*255)
    alpha=alpha.crop(alpha.getbbox())
    occupied=np.array(alpha).any(0)
    gaps=[];start=None
    for x in range(alpha.width):
        if not occupied[x] and start is None:start=x
        if occupied[x] and start is not None:
            if start>alpha.width*.15 and x<alpha.width*.85:gaps.append((x-start,start,x))
            start=None
    assert gaps, 'Two upright syllables must be separated in ImageGen source'
    _,left,right=max(gaps)
    cut=(left+right)//2
    glyphs=[alpha.crop((0,0,cut,alpha.height)),alpha.crop((cut,0,alpha.width,alpha.height))]
    glyphs=[g.crop(g.getbbox()) for g in glyphs]
    scale=min(9/max(g.width for g in glyphs),9/max(g.height for g in glyphs))
    native=Image.new('L',(18,18));placements=[]
    for text,g,(x,y) in zip(['그','램'],glyphs,[(1,0),(8,9)]):
        # Uniform scale, then translation only. No rotation, shear or skew.
        g=g.resize((max(1,round(g.width*scale)),max(1,round(g.height*scale))),Image.Resampling.LANCZOS)
        assert x+g.width<=18 and y+g.height<=18
        native.paste(g,(x,y));g.save(folder/f'syllable-{text}.png')
        placements.append(dict(text=text,x=x,y=y,width=g.width,height=g.height,rotation_degrees=0,shear=0))
    layer=Image.new('RGBA',(18,18),(255,255,255,0));layer.putalpha(native)
    result=np.array(Image.alpha_composite(clean,layer))
    allowed=(original[:,:,3]>0)|(np.array(native)>0)
    result[~allowed]=original[~allowed]
    assert np.array_equal(result[~allowed],original[~allowed])
    im=Image.fromarray(result);source.save(folder/'original.png');clean.save(folder/'cleaned.png');im.save(folder/'korean.png')
    native.save(folder/'new-text-alpha.png');Image.fromarray(allowed.astype('uint8')*255).save(folder/'edit-mask.png')
    encoded=encode_rgba8(im);(folder/'texture.gx').write_bytes(encoded)
    decoded=decode((folder/'texture.gx').read_bytes(),18,18,6)
    assert np.array_equal(np.array(decoded),result)
    decoded.save(folder/'encoded-preview.png')
    r.update(candidate_path=(folder/'korean.png').relative_to(ROOT).as_posix(),candidate_sha256=sha((folder/'korean.png').read_bytes()),
             encoded_path=(folder/'texture.gx').relative_to(ROOT).as_posix(),encoded_sha256=sha(encoded),
             revision='v03',imagegen_source=SOURCE.relative_to(ROOT).as_posix(),imagegen_source_sha256=sha(SOURCE.read_bytes()),
             layout_note='Upright syllables, translation only: 그 upper-left, 램 lower-right. Rotation0, shear0.',placements=placements,
             encoded_changed_pixels_from_png=0,outside_edit_mask_changed_pixels=0,approval=None)
    save(folder/'verification.json',r)
    save(ROOT/'metadata/extra_graphics_drafts_v03.json',dict(textures=rows,
        user_feedback='No rotation or slant of letters. Position upright syllables diagonally downward.',
        revised_groups=['G0204'],new_iso_built=False,runtime_verified=False))
    render(rows,version='v03')
    print(json.dumps(dict(placements=placements,png_roundtrip_changed_pixels=0,outside_mask_changed_pixels=0),ensure_ascii=False))


if __name__=='__main__':main()
