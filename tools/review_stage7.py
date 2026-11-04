"""Read-only stage7 QA of current translation and PNG candidates. Never build."""
import copy,hashlib,html,json,re
from collections import Counter
from pathlib import Path
import numpy as np
from PIL import Image
from inspect_discs import ROOT
from translation_tokens import translated_tokens
from check_text_layout import measure,oracle_check

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    catalog=ROOT/'translation/text_catalog.json';before=sha(catalog)
    rows=json.loads(catalog.read_text(encoding='utf-8'));index={r['id']:r for r in rows}
    p=json.loads((ROOT/'project.json').read_text(encoding='utf-8'))
    metrics=json.loads((ROOT/'metadata/glyph_metrics.json').read_text(encoding='utf-8'))['metrics']
    oracle_check(metrics)
    profiles={x['id']:x for x in json.loads((ROOT/'translation/window_profiles.json').read_text(encoding='utf-8'))['profiles']}
    glossary=json.loads((ROOT/'translation/glossary.json').read_text(encoding='utf-8'))['entries']
    layouts=[];punct=[];terms=[];checked_names=0
    for r in rows:
        if r.get('translation') is None:continue
        tokens=translated_tokens(r)
        display=''.join(t['source'] for t in tokens if t['kind']=='text')
        if re.search(r'[…~～]\.',display):punct.append({'id':r['id'],'source':r['source'],'translation':r['translation'],'reason':'말줄임표·물결표 뒤 마침표 후보. 의도 확인 필요.'})
        if r['kind']=='script_message_candidate':
            normalized=[dict(t,hex=t.get('hex','')) for t in tokens]
            profile=profiles.get(r.get('window') or r.get('window_id'))
            result=measure(normalized,metrics,profile)
            layouts.append({'id':r['id'],'line_count':result['line_count'],'passes_window_limits':result['passes_window_limits'],'issues':result['issues'],'conditional_risks':result['conditional_risks']})
    for term in glossary:
        for id in term.get('name_record_ids',[]):
            r=index[id]
            if r.get('translation') is None:continue
            checked_names+=1
            if r['translation'].strip()!=term['ko'].strip():terms.append({'id':id,'source':r['source'],'translation':r['translation'],'glossary':term['ko'],'reason':'용어집에 직접 연결된 이름 필드의 표기 차이. 기존 승인/문맥 선택과 대조 필요.'})
    obs={o['pixel_sha256']:o for o in json.loads((ROOT/'metadata/graphics_visual_observations.json').read_text(encoding='utf-8'))['groups']}
    graphics=[]
    for s in p['graphics_selection']:
        if s['selection']!='translate_japanese':continue
        o=obs[s['pixel_sha256']];code=f"G{o['sheet_index']:04}"
        entry={'code':code,'label':s['translation_proposal']['label']}
        if c:=s.get('composite_review'):
            for key in ['path','backup']+(['approved_path'] if c.get('approved_path') else []):assert sha(ROOT/c[key])==c['sha256'],c[key]
            source=ROOT/f"work/extraction/jp/graphics/{s['pixel_sha256']}.png"
            orig=np.array(Image.open(source).convert('RGBA'));new=np.array(Image.open(ROOT/c['path']).convert('RGBA'))
            assert orig.shape==new.shape
            mask=np.array(Image.open(ROOT/c['mask']).convert('L'))>0
            assert np.array_equal(orig[~mask],new[~mask])
            key='protected_art' if 'protected_art' in c else 'robot_protection'
            if c.get(key):
                protect=np.array(Image.open(ROOT/c[key]).convert('L'))>0
                assert np.array_equal(orig[protect],new[protect])
            entry.update(status='approved_png' if c.get('approval') else 'confirmation_pending',dimensions=c['dimensions'],outside_edit_mask_changed_pixels=0,encoding_verified=c['encoding_verified'],runtime_verified=c['runtime_verified'])
        elif c:=s.get('reuse'):
            assert sha(ROOT/c['path'])==c['sha256'];assert sha(ROOT/c['backup'])==c['sha256']
            with Image.open(ROOT/c['path']) as im:assert list(im.size)==c['dimensions']
            entry.update(status='authorized_reuse_png',dimensions=c['dimensions'],encoding_verified=c.get('encoding_verified',False),runtime_verified=False)
        else:entry.update(status='source_reading_hold',encoding_verified=False,runtime_verified=False)
        graphics.append(entry)
    v=json.loads((ROOT/'metadata/translation_verification.json').read_text(encoding='utf-8'))
    audit=json.loads((ROOT/'metadata/source_fidelity_review.json').read_text(encoding='utf-8'))
    summary={'catalog_sha256':before,'catalog_records':len(rows),'translated_drafts':v['translated_drafts'],'source_control_tokens_preserved':v['original_control_tokens_preserved'],
        'previous_manual_review_unique_pairs':audit['summary'].get('unique_pairs',len(audit['groups'])),'manual_review_note':'Existing source-fidelity review hashes revalidated by verify_translation.py; not a new semantic review.',
        'untranslated_selections':dict(Counter(r.get('selection','unclassified') for r in rows if r.get('translation') is None)),
        'translated_script_layouts_checked':len(layouts),'confirmed_window_fit':sum(r['passes_window_limits'] is True for r in layouts),'unresolved_window_fit':sum(r['passes_window_limits'] is None for r in layouts),
        'unmeasured_characters':v['distinct_unmeasured_characters'],'dynamic_variable_records':v['dynamic_variable_records'],'direct_name_fields_checked':checked_names,
        'glossary_candidates':len(terms),'punctuation_candidates':len(punct),'graphics_status_counts':dict(Counter(g['status'] for g in graphics)),
        'limits':['전체 번역 글리프 매핑·폭 미검증','창별 한도·화자·동적 조사 미확인','번역 길이 변경에 따른 스크립트 재배치 미검증','전체 그래픽 게임 형식 재인코딩 미검증','노래방 영상 번역·재인코딩 미완료','Dolphin 전체 실행·실기 미확인'],
        'new_iso_built':False}
    candidate=None;relocation=None
    if (ROOT/'metadata/full_font_verification.json').exists():
        plan=json.loads((ROOT/'translation/full_font_plan.json').read_text(encoding='utf-8'))
        assert plan['catalog_sha256']==before
        candidate=json.loads((ROOT/'metadata/full_font_verification.json').read_text(encoding='utf-8'))
        summary['full_font_candidate']={k:candidate[k] for k in ['glyph_count','cpu_glyphs_verified','cpu_cache_miss_hit_verified','layout_records','game_installed','runtime_verified']}
        summary['limits'][0]='전체 글꼴 후보 CPU 검증 완료, 실제 게임 배치·렌더링 미검증'
    if (ROOT/'metadata/relocation_cpu_verification.json').exists():
        experiment=json.loads((ROOT/'metadata/relocation_experiment.json').read_text(encoding='utf-8'))
        assert experiment['catalog_sha256']==before
        relocation=json.loads((ROOT/'metadata/relocation_cpu_verification.json').read_text(encoding='utf-8'))
        summary['relocation_cpu']={k:relocation[k] for k in ['tested_records','goto_and_return','wait_retry_resume','selection_result','game_rendering_verified','game_loader_memory_verified']}
        summary['limits'][2]='대사 이동·복귀 CPU 검증 완료, 로더 메모리·전체 제어 흐름·메타데이터/DOL 참조 미검증'
    injection=p['checks'].get('injection_preparation')
    if injection:
        summary['injection_preparation']=injection
        summary['limits'][0]='전체 글꼴·UI 메모리 예약 후보 CPU 검증 완료, 부팅·힙 여유·렌더링 미검증'
        summary['limits'][2]='대사/이름 읽기 CPU 검증 및 DOL UI 참조표 실험 완료; 전체 제어 흐름·QP 패킹·일부 필드 연결 미확인'
        summary['limits'][3]='그래픽 12묶음 형식/영역 검사 완료. CMPR 4묶음 획 손실로 품질 보류; PNG 승인과 별개'
    packing=p['checks'].get('qp_repacking')
    proposal=p['checks'].get('cmpr_format_review')
    if packing:
        summary['qp_repacking']=packing
        summary['limits'][2]='대사/이름 CPU·UI 참조표 및 QP 7조합 재패킹 검증 완료. 실제 로딩·전체 제어 흐름·일부 필드는 미확인'
    if proposal:summary['cmpr_format_review']=proposal
    if proposal and proposal.get('applied'):
        summary['limits'][3]='작은 그림 4장의 승인된 RGBA8 예외 적용·PNG 일치 확인. 원본 미변경, 실제 화면과 일부 PNG 확정은 별도'
    integrated=p['checks'].get('integrated_layout')
    if integrated:summary['integrated_layout']=integrated
    current_build=p['checks'].get('build_v02',{})
    if current_build.get('new_iso_built'):summary['current_test_build']=current_build
    assert sha(catalog)==before
    report={'summary':summary,'graphics':graphics,'glossary_candidates':terms,'punctuation_candidates':punct,'layout_records':layouts}
    (ROOT/'metadata/stage7_review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    esc=lambda x:html.escape(str(x))
    content='<h1>치비로보 · 7단계 정적 검수</h1><p>번역문 변경·ISO 빌드 없음. 기존 의미 대조 기록은 해시를 재검증했으며, 이번에 전 문장을 새로 읽었다는 뜻은 아닙니다.</p>'
    content+=f'<p>번역 초안 {v["translated_drafts"]:,}항목 · 제어 코드 {v["original_control_tokens_preserved"]:,}개 보존. 확정 창 맞춤 {summary["confirmed_window_fit"]}항목.</p>'
    if candidate:
        content+='<h2>추가 기술 검증 · 게임 미적용</h2><p>Gmarket Sans Bold 한글 1,030자와 가운데점, 총 1,031글리프의 복사·폭·캐시 적중·순환을 일본판 실제 CPU 명령으로 확인했습니다. 기존 시험 ISO에는 아직 7글자만 적용되어 있습니다. 전체 후보 폭으로 7,922항목을 다시 계산했으나 창별 한도와 동적 변수가 남아 창 맞춤 통과는 아닙니다.</p><p><a href="../full-font/glyph-atlas.png">전체 글리프 미리보기</a></p>'
    if relocation:
        content+='<p>재배치 실험 7,922항목: 일본판 실제 분기·메시지·선택지 처리 명령으로 새 대사 진입, 표시 대기, 원래 주소 복귀, 선택지 결과 전달을 확인했습니다. 화면 그리기와 선택지 음성은 모의 처리했으며 게임 로더 메모리·전체 제어 흐름·DOL/이름 필드는 별도입니다.</p>'
    if injection:
        content+='<h2>주입 준비 검증 · 새 ISO 없음</h2><p>폰트·UI 후보에 330,304바이트를 예약하고 글리프 1,031자와 ArenaLo 경계를 CPU에서 검사했습니다. 이름·설명 412항목 중 409항목은 일본판 실제 읽기 함수로 확인했습니다. 나머지 3개는 stage 보조 설명 필드로 표시 경로가 미확인입니다. UI 133항목은 원문을 줄이지 않고 별도 공간에 넣어 참조표 141칸을 RAM에서 대조했습니다.</p><p>12묶음·13텍스처의 크기·헤더·편집 영역 밖 보존 검사는 통과했습니다. 초기 CMPR 변환에서는 마네와 칩 3장의 획 손실이 발견됐습니다. 아래의 사용자 승인 RGBA8 예외로 변환 손실을 해소했으며 확정 PNG는 변경하지 않았습니다.</p><p><a href="../graphics-encoding/comparison.png">PNG와 게임 형식 변환 비교</a> · <a href="../graphics-encoding/small-zoom.png">작은 그림 6배 비교</a> · <a href="../../docs/injection-preparation.md">검증 기록과 한계</a></p>'
    if packing:
        content+='<h2>QP 재패킹</h2><p>원본 왕복·대사·설명·그림·RGBA8 포함 통합의 7조합에서 각각 1,155파일을 다시 읽어 확인했습니다. 무변경 결과는 바이트 일치, RGBA8 4장을 포함한 텍스트·그림 통합 실험은 470,208바이트 증가합니다. 보류 번역과 미확정 PNG를 포함한 실험을 배포 승인으로 처리하지 않습니다. 원본 간격·파일 순서·비교체 파일 내용은 보존했습니다. 메모리 검증만 수행했으며 QP/ISO 파일은 만들지 않았습니다.</p>'
    if proposal:
        content+='<h2>작은 글자 RGBA8 예외 · 사용자 승인 반영</h2><p>CMPR 색 조합을 추가 탐색해도 마네·칩 3장의 획 손실이 남습니다. 아래 오른쪽 RGBA8 후보는 PNG와 픽셀이 정확히 같고 4장 합계 29,248바이트 늘어납니다. 크기·배경·알파는 보존합니다. 사용자가 4장의 형식 변경을 승인하여 별도 TPL 후보에 적용하고 244항목을 다시 확인했습니다. G0200 PNG 자체의 확정 상태는 형식 승인과 별도로 남아 있습니다. 일본판 텍스처 초기화 CPU 검사는 통과했으나 TPL 로더·실제 화면은 미확인입니다.</p><p><a href="../rgba8-comparison/comparison.png">PNG / 기존 CMPR / 개선 CMPR / RGBA8 비교</a> · <a href="../../docs/qp-and-cmpr.md">상세 근거</a></p><img style="max-width:100%;height:auto" src="../rgba8-comparison/comparison.png" alt="작은 글자 압축 비교">'
    content+='<h2>미확인·남은 작업</h2><ul>'+''.join('<li>'+esc(x)+'</li>' for x in summary['limits'])+'</ul>'
    if integrated:
        content+='<h2>통합 시험 준비</h2><p>메모리에서 합친 DOL의 헤더로 CPU를 로딩해 전체 글꼴·UI 참조·메모리 경계를 확인했습니다. QP를 디스크 앞쪽으로 옮기는 가상 배치도 검증했고 원래 디스크 파일 143개의 내용·위치는 보존했습니다. 실제 ISO는 아직 없습니다. 이 최대 범위 실험과 실제 시험본 적용 제안은 구분합니다.</p><p><a href="../build-plan/index.html">적용·보류 목록과 확정 대기 그림 2장 보기</a></p>'
    content+='<h2>그래픽</h2><table><tr><th>그룹</th><th>내용</th><th>상태</th><th>규격</th></tr>'+''.join('<tr>'+''.join('<td>'+esc(g.get(k,''))+'</td>' for k in ['code','label','status','dimensions'])+'</tr>' for g in graphics)+'</table>'
    for title,items in [('용어집 직접 이름 필드 비교',terms),('문장부호 후보',punct)]:
        content+='<h2>'+title+'</h2><p>자동 수정하지 않은 검토 후보입니다.</p><table>'+''.join('<tr>'+''.join('<td><pre>'+esc(c.get(k,''))+'</pre></td>' for k in ['id','source','translation','glossary','reason'])+'</tr>' for c in items)+'</table>'
    content+='<p><a href="../translation-review/corrections.html">기존 원문 보존 수정 대조표</a> · <a href="../graphics-review/plan.html">그래픽 비교</a></p>'
    if current_build.get('new_iso_built'):
        content='<h1>v02 시험 ISO 제작 완료</h1><p>텍스트 8,367항목·그림 12묶음을 적용했습니다. 보류 대사 97개·설명 3개는 원문 유지. ISO 전체 재읽기 검증 완료, 실제 Dolphin 실행은 미확인입니다. 아래는 이전 7단계 기술 검수 기록입니다.</p><p><a href="../build-v02/index.html">최신 시험본과 검증 결과</a></p><hr>'+content
        content=content.replace('기존 시험 ISO에는 아직 7글자만 적용되어 있습니다.','v01은 7글자 출력 시험이며, v02에는 전체 글꼴 후보를 적용했습니다. 실제 출력 확인은 별도입니다.')
        content=content.replace('G0200 PNG 자체의 확정 상태는 형식 승인과 별도로 남아 있습니다.','G0200 PNG와 G0146 v02도 후속 사용자 승인으로 확정했습니다.')
    out=ROOT/'work/stage7-review';out.mkdir(parents=True,exist_ok=True)
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>7단계 정적 검수</title><style>body{max-width:1200px;margin:30px auto;padding:20px;font:16px/1.7 system-ui;background:#f4f2ec}table{border-collapse:collapse;width:100%}td,th{padding:10px;border:1px solid #bbb;vertical-align:top}pre{white-space:pre-wrap;font:inherit}h2{margin-top:30px}</style>'+content,encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k!='unmeasured_characters'},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
