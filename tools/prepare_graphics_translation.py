"""Show unedited originals beside proposed text; authoritative plans live in project.json."""
import hashlib
import html
import json
from pathlib import Path
from PIL import Image
from inspect_discs import ROOT


def main():
    p=json.loads((ROOT/'project.json').read_text(encoding='utf-8'))
    catalog=json.loads((ROOT/'metadata/graphics_catalog_jp.json').read_text(encoding='utf-8'))['images']
    observations=json.loads((ROOT/'metadata/graphics_visual_observations.json').read_text(encoding='utf-8'))['groups']
    byid={r['id']:r for r in catalog};obs={r['pixel_sha256']:r for r in observations}
    rules=p['graphics_work_rules'];cards=[];md=['# 그래픽 번역 작업안','','원본과 번역 문구를 비교하는 편집 전 작업안이다. 승인과 자산 상태의 기준은 `project.json`이다. 원본 PNG는 변경하지 않는다.','','## 공통 규칙','']
    md.extend('- '+s for s in rules['rules'])
    md+=['','## 개별 원문과 번역안','']
    esc=html.escape
    for s in p['graphics_selection']:
        if s['selection']!='translate_japanese':continue
        proposal=s['translation_proposal'];o=obs[s['pixel_sha256']];row=byid[o['ids'][0]]
        path=ROOT/row['png'];before=hashlib.sha256(path.read_bytes()).hexdigest()
        with Image.open(path) as im:assert im.size==(row['width'],row['height'])
        assert hashlib.sha256(path.read_bytes()).hexdigest()==before
        rel=Path('../../')/row['png']
        zoom=4 if row['width']<=96 else 1
        code=f'G{o["sheet_index"]:04}'
        cards.append(f'<article><h2>{code} · {esc(proposal["label"])}</h2><p>{row["width"]} × {row["height"]} px · 원본 형식 {row["format"]} · 연결 {len(o["ids"])}곳</p><div class="original"><img src="{rel.as_posix()}" width="{row["width"]}" height="{row["height"]}" alt="{esc(proposal["label"])} 원본"></div>'+ (f'<details><summary>4배 픽셀 확대</summary><div class="original"><img style="image-rendering:pixelated" src="{rel.as_posix()}" width="{row["width"]*zoom}" height="{row["height"]*zoom}"></div></details>' if zoom>1 else '') + '<div class="columns"><div><h3>일본어 원문</h3><pre>'+esc(proposal['source'])+'</pre></div><div><h3>한국어 제안</h3><pre>'+esc(proposal['translation'])+'</pre></div></div><p>'+esc(proposal['design'])+'</p><p class="note">'+esc(proposal['note'])+'</p><details><summary>원본 위치</summary><pre>'+esc('\n'.join(o['ids']))+'</pre></details></article>')
        md += [f'### {code} · {proposal["label"]}', '',f'- 원본: `{o["ids"][0]}` / {row["width"]}×{row["height"]}', '- 일본어: '+proposal['source'].replace('\n',' / '),'- 한국어: '+proposal['translation'].replace('\n',' / '),'- 작업: '+proposal['design'],'- 참고: '+proposal['note'],'']
        if reuse := s.get('reuse'):
            reused_path=ROOT/reuse['path']
            assert hashlib.sha256(reused_path.read_bytes()).hexdigest()==reuse['sha256']
            reused_rel=(Path('../../')/reuse['path']).as_posix()
            cards[-1]=cards[-1].removesuffix('</article>')+'<h3>이전 세션 결과 · 재사용</h3><div class="original"><img src="'+esc(reused_rel)+'" width="'+str(row['width'])+'" height="'+str(row['height'])+'" alt="기존 한글 작업본"></div><p>'+esc(reuse['font']+' · 원본 파일 그대로 복사·백업. '+reuse['encoding_note'])+'</p></article>'
            md += ['- 재사용 파일: `'+reuse['path']+'`','- 이전 작업 위치: `'+reuse['source_file']+'`','- SHA-256: `'+reuse['sha256']+'`','- 주입 전 확인: '+reuse['encoding_note'],'']
        if draft := s.get('imagegen_draft'):
            draft_path=ROOT/draft['path']
            assert hashlib.sha256(draft_path.read_bytes()).hexdigest()==draft['sha256']
            draft_rel=(Path('../../')/draft['path']).as_posix()
            cards[-1]=cards[-1].removesuffix('</article>')+'<h3>이미지젠 시안 · 글자 디자인 검토</h3><p>원본 크기로 표시한 미리보기입니다. 실제 파일은 '+esc(' × '.join(map(str,draft['dimensions'])))+' px이며 게임용 확정본이 아닙니다.</p><div class="original"><img src="'+esc(draft_rel)+'" width="'+str(row['width'])+'" height="'+str(row['height'])+'" alt="한글 로고 시안"></div><details><summary>생성 시안 확대</summary><img style="max-width:100%;height:auto" src="'+esc(draft_rel)+'"></details><ul>'+''.join('<li>'+esc(note)+'</li>' for note in draft['observations'])+'</ul></article>'
            md += ['- 이미지젠 시안: `'+draft['path']+'`','- 프롬프트: `'+draft['prompt']+'`','- 상태: '+draft['status'],'- 확인 사항: '+' / '.join(draft['observations']),'']
        if composite := s.get('composite_review'):
            assert hashlib.sha256((ROOT/composite['path']).read_bytes()).hexdigest()==composite['sha256']
            approved=bool(composite.get('approval'))
            status_text='사용자 확정·백업·동결 완료' if approved else '사용자 확정 대기'
            metrics=[('outside_edit_mask_changed_pixels','마스크 밖'),('robot_protection_changed_pixels','로봇 보호 영역'),('exclamation_tm_changed_pixels','느낌표·TM'),('protected_art_changed_pixels','원본 그림 보호 영역'),('alpha_changed_pixels','알파')]
            metric_text=' · '.join(label+' 변경 '+str(composite[key])+' px' for key,label in metrics if key in composite)
            if composite.get('alpha_note'):metric_text+=' · '+composite['alpha_note']
            description=composite.get('rendering_description','원본 글자 제거와 바탕 복원 → 이미지젠 한글 획 합성.')
            content='<h3>정밀 합성 '+('확정본' if approved else '검토본')+' · '+esc(' × '.join(map(str,composite['dimensions'])))+' px</h3><p>'+esc(description)+' 원본 크기로 표시합니다.</p>'
            for title,key in [('글자 제거·바탕 복원','cleaned'),('한글 합성','path')]:
                content+='<h4>'+title+'</h4><div class="original"><img src="'+esc((Path('../../')/composite[key]).as_posix())+'" width="'+str(row['width'])+'" height="'+str(row['height'])+'"></div>'
            content+='<p>'+metric_text+'</p><p>'+status_text+'. 게임 텍스처 인코딩·실행은 미검증입니다.</p><details><summary>'+str(composite.get('enlargement_scale',4))+'배 확대 보기</summary><div class="original"><img src="'+esc((Path('../../')/composite['enlarged']).as_posix())+'"></div></details>'
            cards[-1]=cards[-1].removesuffix('</article>')+content+'</article>'
            md += ['- 정밀 합성: `'+composite.get('approved_path',composite['path'])+'`','- 비교 시트: `'+composite['comparison']+'`','- 검증: '+metric_text+'. 게임용 인코딩·실행 미검증.','- 상태: '+status_text+'. 원본 크기·확대 검수 완료.','']
            if composite.get('generation_prompt'):md += ['- 내장 이미지젠 프롬프트: `'+composite['generation_prompt']+'`','']
    page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>치비로보 그래픽 번역 작업안</title><style>body{font:16px/1.65 system-ui;background:#f4f2ec;color:#222;margin:30px auto;padding:0 22px;max-width:1050px}h1{font-size:30px}h2{font-size:23px}h3{font-size:16px}article{background:white;border:1px solid #d8d7ce;border-radius:12px;padding:22px;margin:24px 0}.original{background:#454545;padding:12px;overflow:auto}.original img{display:block;max-width:none}.columns{display:grid;grid-template-columns:1fr 1fr;gap:22px}pre{font:inherit;white-space:pre-wrap;overflow-wrap:anywhere}.note{color:#5b625c}details{margin:12px 0}summary{cursor:pointer}li{margin:8px 0}a{color:#205d54}@media(max-width:650px){.columns{grid-template-columns:1fr}}</style><h1>치비로보 · 그래픽 번역 작업안</h1><p>원본 13묶음과 한국어 문구를 나란히 놓았습니다. 그림은 아직 편집하지 않았습니다. 작은 그림은 원본 크기와 4배 확대를 함께 확인할 수 있습니다.</p><details open><summary><b>작업 규칙</b></summary><ul>'''+''.join('<li>'+esc(x)+'</li>' for x in rules['rules'])+'</ul></details><p>판독되지 않는 작은 글씨 등 31묶음과 노래방 영상은 별도 조사 대상으로 유지합니다. 본문 문맥 32곳의 잠정 선택과 구분합니다.</p>'+''.join(cards)+'</html>'
    out=ROOT/'work/graphics-review';out.mkdir(parents=True,exist_ok=True)
    selected=[s for s in p['graphics_selection'] if s['selection']=='translate_japanese']
    reused=sum(bool(s.get('reuse')) for s in selected)
    approved=sum(bool(s.get('composite_review',{}).get('approval')) for s in selected)
    review=sum(bool(s.get('composite_review')) and not s['composite_review'].get('approval') for s in selected)
    held=sum(bool(s.get('source_reading_review')) for s in selected)
    remaining=len(selected)-reused-approved-review-held
    page=page.replace('그림은 아직 편집하지 않았습니다.',f'기존 결과 재사용 {reused}묶음 · PNG 확정 {approved}묶음 · 합성 검토 {review}묶음 · 원문 판독 보류 {held}묶음 · 나머지 미편집 {remaining}묶음입니다. 게임용 인코딩·실행은 별도 확인이 필요합니다.')
    (out/'plan.html').write_text(page,encoding='utf-8')
    (ROOT/'docs/graphics-translation-plan.md').write_text('\n'.join(md),encoding='utf-8')
    print('Prepared',len(cards),'original-image/text proposals; no image modified.')


if __name__=='__main__':main()
