"""Repair rejected lettering drafts. Isolated PNG/RGBA8 previews, no ISO.

G0204 uses user-requested ImageGen lettering, composited with continuous alpha.
Centi candidates keep their PNG pixels and avoid CMPR quantization entirely.
"""
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage
from inspect_discs import ROOT, save
from prepare_rgba8_comparison import encode_rgba8
from decode_gx import decode
from verify_graphics_encoding import sha

SOURCE = ROOT/'graphics/drafts/extra-source/gram-imagegen-v02.png'
OUT = ROOT/'work/graphics-extra'


def main():
    old_report=json.loads((ROOT/'metadata/extra_graphics_drafts.json').read_text('utf-8'))
    rows=[]
    for old in old_report['textures']:
        code=old['code']
        if code=='G2284':
            rows.append(dict(old,revision='unchanged_from_v01'))
            continue
        prev=ROOT/Path(old['candidate_path']).parent
        folder=prev.parent/'composite-v02';folder.mkdir(parents=True,exist_ok=True)
        source=Image.open(prev/'original.png').convert('RGBA');original=np.array(source)
        clean=Image.open(prev/'cleaned.png').convert('RGBA')
        if code=='G0204':
            generated=Image.open(SOURCE).convert('RGBA')
            alpha=generated.getchannel('A')
            assert alpha.getextrema()[0]==0, 'Expected transparent ImageGen lettering'
            # Remove generator speckles at source resolution before reducing.
            # No native-size binary threshold: preserve antialiasing when small.
            ink=ndimage.binary_opening(np.array(alpha)>180,iterations=3)
            components,count=ndimage.label(ink)
            areas=np.bincount(components.ravel());areas[0]=0
            ink=np.isin(components,np.flatnonzero(areas>=500))
            alpha=Image.fromarray(ink.astype('uint8')*255)
            box=alpha.point(lambda v:255 if v>12 else 0).getbbox()
            assert box
            # Keep the generated silhouette and slant; do not binary-threshold
            # the native glyph or substitute a system-font character.
            alpha=alpha.crop(box)
            alpha.thumbnail((17,17),Image.Resampling.LANCZOS)
            native=Image.new('L',(18,18))
            native.paste(alpha,((18-alpha.width)//2,(18-alpha.height)//2))
            overlay=Image.new('RGBA',(18,18),(255,255,255,0));overlay.putalpha(native)
            result=np.array(Image.alpha_composite(clean,overlay))
            old_mask=original[:,:,3]>0
            allowed=old_mask|(np.array(native)>0)
            result[~allowed]=original[~allowed]
            Image.fromarray(old_mask.astype('uint8')*255).save(folder/'old-text-mask.png')
            native.save(folder/'new-text-alpha.png')
        else:
            result=np.array(Image.open(prev/'korean.png').convert('RGBA'))
            allowed=np.array(Image.open(prev/'edit-mask.png').convert('L'))>0
            Image.open(prev/'old-text-mask.png').save(folder/'old-text-mask.png')
        assert np.array_equal(result[~allowed],original[~allowed])
        candidate=Image.fromarray(result)
        source.save(folder/'original.png');clean.save(folder/'cleaned.png')
        candidate.save(folder/'korean.png')
        Image.fromarray(allowed.astype('uint8')*255).save(folder/'edit-mask.png')
        encoded=encode_rgba8(candidate)
        (folder/'texture.gx').write_bytes(encoded)
        # Re-read the saved bytes, not just the in-memory encoder output.
        decoded=decode((folder/'texture.gx').read_bytes(),*candidate.size,6)
        assert np.array_equal(np.array(decoded),result)
        assert np.array_equal(np.array(decoded)[~allowed],original[~allowed])
        decoded.save(folder/'encoded-preview.png')
        previous_encoded=np.array(Image.open(prev/'encoded-preview.png').convert('RGBA'))
        record=dict(old)
        record.pop('rgba8_proposal',None)
        record.update(candidate_path=(folder/'korean.png').relative_to(ROOT).as_posix(),
            candidate_sha256=sha((folder/'korean.png').read_bytes()),
            encoded_path=(folder/'texture.gx').relative_to(ROOT).as_posix(),
            encoded_sha256=sha(encoded),format=6,source_format=14,
            encoded_max_error=[0,0,0,0],encoded_changed_pixels_from_png=0,
            old_cmpr_changed_pixels_from_old_png=int((previous_encoded!=np.array(Image.open(prev/'korean.png').convert('RGBA'))).any(2).sum()),
            imagegen_used=True,revision='v02',approval=None,
            format_proposal='Isolated RGBA8 draft; game container not modified; existing approved format-exception list unchanged.',
            layout_note='ImageGen white handwritten lettering with whole-word diagonal and continuous alpha' if code=='G0204' else 'Same ImageGen centi PNG, lossless roundtrip; numbers and border unchanged')
        if code=='G0204':
            record['imagegen_source']=SOURCE.relative_to(ROOT).as_posix()
            record['imagegen_source_sha256']=sha(SOURCE.read_bytes())
        else:
            assert np.array_equal(result,np.array(Image.open(prev/'korean.png').convert('RGBA')))
        save(folder/'verification.json',record);rows.append(record)
    save(ROOT/'metadata/extra_graphics_drafts_v02.json',dict(textures=rows,
        user_feedback='G0204 shape rejected; user requested ImageGen. Centi strokes missing in encoded preview.',
        revised_groups=['G0204','G2281','G2282','G2283'],
        new_iso_built=False,runtime_verified=False))
    render(rows)
    print('Four revised drafts reread: PNG vs RGBA8 differences=0; outside glyph masks differences=0. No ISO written.')


def render(rows, version='v02'):
    OUT.mkdir(parents=True,exist_ok=True)
    font=ImageFont.truetype('C:/Windows/Fonts/malgun.ttf',18)
    sheet=Image.new('RGB',(1120,1450),(58,62,66));d=ImageDraw.Draw(sheet)
    preview=Image.new('RGB',(1000,310),(58,62,66));pd=ImageDraw.Draw(preview)
    cards=[]
    for j,r in enumerate(rows):
        folder=(ROOT/r['candidate_path']).parent;code=r['code'];figs=[]
        for i,(label,name) in enumerate([('원본','original'),('글자 제거','cleaned'),('한글 PNG','korean'),('변환 후 · 픽셀 일치','encoded-preview')]):
            path=folder/(name+'.png');im=Image.open(path).convert('RGBA');uri=path.as_uri()
            figs.append(f'<figure><figcaption>{label}</figcaption><img src="{uri}" width="{im.width}" height="{im.height}"><br><img src="{uri}" width="{im.width*6}" height="{im.height*6}"></figure>')
            x=i*280;y=j*290;d.text((x+8,y+4),f'{code} {label}',font=font,fill='white')
            zoom=im.resize((192,192),Image.Resampling.NEAREST);sheet.paste(zoom,(x+8,y+36),zoom);sheet.paste(im,(x+8,y+238),im)
        im=Image.open(folder/'encoded-preview.png').convert('RGBA');zoom=im.resize((160,160),Image.Resampling.NEAREST)
        preview.paste(zoom,(j*200+20,50),zoom);preview.paste(im,(j*200+(200-im.width)//2,236),im)
        pd.text((j*200+12,12),code+' '+r['label'],font=font,fill='white')
        note='이미지젠으로 새로 만든 흰 손글씨. 원본처럼 글줄 전체를 기울였고, 작은 크기의 부드러운 가장자리를 보존했습니다. 원문 グラム 판독안의 실행 문맥은 아직 미확인입니다.' if code=='G0204' else '센티의 한글 PNG를 무손실 변환해 빠진 획을 복원했습니다. 세 상자의 글자 모양·크기는 같으며 숫자와 테두리는 원본입니다.'
        if code=='G0204' and version=='v03':
            note='글자는 회전하거나 기울이지 않았습니다. 똑바로 선 그를 왼쪽 위, 램을 오른쪽 아래에 위치만 옮겨 배치했습니다. 이미지젠 원본 글자와 연속 알파를 사용했습니다.'
        if code=='G2284':note='짐은 이전 시안을 유지했습니다. 원래 RGBA8 형식이며 픽셀 일치 검증은 기존과 같습니다.'
        cards.append(f'<article><h2>{code} · {r["label"]}</h2><p>{note}</p><div class="row">'+''.join(figs)+'</div></article>')
    sheet.save(OUT/f'comparison-{version}.png');preview.save(OUT/f'preview-{version}.png')
    page='''<!doctype html><html lang="ko"><meta charset="utf-8"><title>추가 그림 수정안 v02</title><style>body{background:#24282c;color:#eee;font:16px system-ui;line-height:1.6;margin:32px}article{background:#3b3e42;padding:24px;margin:24px 0;border-radius:12px}.row{display:flex;flex-wrap:wrap;gap:20px}figure{margin:8px;min-width:130px}img{image-rendering:pixelated;max-width:100%}figcaption{margin-bottom:12px}</style><h1>추가 그림 수정안 v02</h1><p>그램을 이미지젠으로 다시 만들고 센티3장의 압축 후 획 손상을 수정했습니다. 아래 마지막 열은 저장한 RGBA8 데이터를 다시 읽은 결과입니다. 한글 PNG와 다른 픽셀0, 편집 마스크 밖 변경0입니다.</p><p>G0204/G2281/G2282/G2283은 무손실 RGBA8 변환안이며 실제 게임 컨테이너에는 아직 적용하지 않았습니다. 짐은 기존안 그대로입니다. ISO를 새로 만들지 않았습니다.</p>'''+''.join(cards)+'</html>'
    if version=='v03':
        page=page.replace('v02','v03').replace('그램을 이미지젠으로 다시 만들고 센티3장의 압축 후 획 손상을 수정했습니다.','그램은 각 글자를 똑바로 세우고 위치만 사선으로 내리는 배치로 수정했습니다. 센티3장은 직전 무손실 수정안을 유지했습니다.')
    (OUT/'index.html').write_text(page,'utf-8')


if __name__=='__main__':main()
