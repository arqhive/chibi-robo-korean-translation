"""Validate saved manual-review coverage and render the source-fidelity comparison."""
import copy
import hashlib
import html
import json
import re
import unicodedata
from inspect_discs import ROOT
from translation_tokens import template, translated_tokens


def render():
    raw=(ROOT/'translation/text_catalog.json').read_bytes()
    rows=json.loads(raw); index={r['id']:r for r in rows}
    audit=json.loads((ROOT/'metadata/source_fidelity_review.json').read_text(encoding='utf-8'))
    review=json.loads((ROOT/'translation/review_corrections.json').read_text(encoding='utf-8'))
    sha=hashlib.sha256(raw).hexdigest()
    assert audit['summary']['catalog_sha256']==review['review_basis_catalog_sha256']
    applied=review.get('applied',False)
    assert sha==review.get('applied_catalog_sha256' if applied else 'review_basis_catalog_sha256'), 'Review snapshot is stale'
    changes={c['id']:c for c in review['changes']+review['context_reviews']}
    def original_pair(row):
        change=changes.get(row['id'])
        return [template(row),change['before'] if change and change.get('applied') else row['translation']]
    covered=[]; pairs=set()
    for g in audit['groups']:
        first=index[g['ids'][0]]; pair=original_pair(first)
        assert hashlib.sha256(json.dumps(pair,ensure_ascii=False).encode()).hexdigest()==g['pair_sha256']
        assert tuple(pair) not in pairs; pairs.add(tuple(pair))
        for id in g['ids']:
            assert original_pair(index[id])==pair
            covered.append(id)
    assert len(covered)==len(set(covered))
    assert set(covered)=={r['id'] for r in rows if r.get('translation') is not None}
    assert {i for a,b in audit['reviewed_ranges'] for i in range(a,b)}==set(range(len(pairs)))
    numbers=lambda s: re.findall(r'\d+',unicodedata.normalize('NFKC',re.sub(r'<\d+>','',s)))
    for change in review['changes']+review['context_reviews']:
        row=index[change['id']]
        assert row['translation']==change['after' if change.get('applied') else 'before'] and template(row)==change['source']
        if change['after'] is not None:
            candidate=copy.deepcopy(row);candidate['translation']=change['after']; translated_tokens(candidate)
            assert numbers(change['before'])==numbers(change['after'])
            if row['kind']=='dol_rodata_string_candidate':
                assert len(change['before'])-len(change['before'].rstrip('\u3000'))==len(change['after'])-len(change['after'].rstrip('\u3000'))
    for change in review['explicit_user_corrections']:
        assert index[change['id']]['translation']==change['after']
    assert all('외계인' not in (r.get('translation') or '') for r in rows if '宇宙人' in r['source'] or 'ウチュウジン' in r['source'])
    assert (ROOT/'translation/text_catalog.json').read_bytes()==raw
    s=audit['summary']; esc=lambda x:html.escape(str(x))
    cards=[]
    for f in sorted(audit['findings'],key=lambda x:x['group_index']):
        current=changes[f['ids'][0]]
        state='context' if f['after'] is None else 'proposal'
        title='문맥 확인' if state=='context' else ('의미 수정 제안' if f['review_kind']=='meaning_correction' else '원문 보존 제안')
        if applied:title='잠정 선택 · 실행 확인 예정' if state=='context' else '승인 반영 완료'
        ids='<br>'.join(esc(x) for x in f['ids'])
        after=current['after'] if applied else f['after']
        reason=f['reason']+('\n잠정 결정: '+current['resolution_reason'] if current.get('resolution_reason') else '')
        cards.append('<tr data-state="'+state+'"><td><b>'+esc(f['finding_id'])+'</b><p>'+title+'</p><small>'+ids+'</small></td>'+''.join('<td><pre>'+esc(v)+'</pre></td>' for v in (f['source'],f['before'],after if after is not None else '수정문 미확정 — 문맥/연출 확인 필요',reason))+'</tr>')
    for n,c in enumerate(review['explicit_user_corrections'],1):
        cards.append('<tr data-state="applied"><td><b>U'+str(n).zfill(2)+'</b><p>사용자 지시 반영</p><small>'+esc(c['id'])+'</small></td>'+''.join('<td><pre>'+esc(v)+'</pre></td>' for v in (template(index[c['id']]),c['before'],c['after'],c['reason']))+'</tr>')
    page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>치비로보 원문 보존 재검수</title>
<style>body{font:15px/1.65 system-ui,sans-serif;background:#f6f4ef;color:#272922;margin:28px}h1{font-size:28px;margin-bottom:8px}p{margin:8px 0}header{max-width:1100px}.stats{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}.stats span{background:white;border:1px solid #d7d7cc;padding:12px 18px;border-radius:8px}.stats b{font-size:24px;margin-right:8px}.controls{display:flex;gap:12px;margin:20px 0;flex-wrap:wrap}input,select{padding:10px;font:inherit;border:1px solid #bdbeb4;border-radius:6px}input{width:min(550px,80vw)}.tablewrap{overflow:auto;max-height:76vh;border:1px solid #ccc}table{border-collapse:collapse;width:100%;background:white}td,th{border:1px solid #ddd;padding:14px;vertical-align:top}th{position:sticky;top:0;background:#e9e8de;text-align:left;z-index:1}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;margin:0;min-width:190px}td:first-child{max-width:250px;overflow-wrap:anywhere}small{font-size:11px;color:#64685d}tr[data-state=context]{background:#fffaf0}tr[data-state=applied]{background:#f0f7f0}a{color:#215f59}footer{margin-top:20px;color:#5f6358}tr[hidden]{display:none}</style>
<header><h1>치비로보 · 원문 보존 재검수</h1><p>일본어에 없는 말의 추가, 정보 누락, 주체·수동·시제·감정 변화, 비유와 말장난을 다시 대조했습니다. 동일한 원문·번역 쌍은 묶고 모든 파일 위치를 연결했습니다.</p>'''
    page+=f'<div class="stats"><span><b>{s["draft_records"]:,}</b>대조한 초안</span><span><b>{s["proposed_records"]}</b>수정 제안</span><span><b>{s["context_records"]}</b>문맥 확인</span><span><b>{s["explicit_user_corrections_applied"]}</b>우주인 반영</span></div>'
    page+=f'<p>{s["unique_pairs"]:,}개의 서로 다른 원문·번역 쌍을 AI가 읽고 비교했습니다. 미번역/원문 유지 {s["unreviewed_null_records"]}항목, 실제 화자·장면·동적 치환·창 폭·실행은 이번 의미 대조의 통과 대상이 아닙니다.</p>'
    page+='<p><b>우주인 정정 외 수정안은 미적용입니다.</b> 원문 보존 제안에는 명백한 오류뿐 아니라 번역 선택의 여지가 있는 비유·호칭·강도 조정도 포함합니다. 문맥 확인 항목은 추측으로 고치지 않았습니다.</p><p>기존 우주인→외계인 제안 14곳은 철회했습니다. 나머지 이전 용어 통일 7곳은 이번 의미 오류로 집계하지 않았습니다. &lt;숫자&gt;는 원본 제어 코드 자리입니다.</p><p><a href="comparison.html">전체 번역 초안 대조표</a></p></header>'
    page+='<div class="controls"><input id="q" placeholder="원문, 번역, 사유, 파일 경로 검색" aria-label="검색"><select id="state" aria-label="표시 범위"><option value="">모두 보기</option value="proposal">수정 제안</option><option value="context">문맥 확인</option><option value="applied">우주인 반영</option></select><span id="count"></span></div><div class="tablewrap"><table><thead><tr><th>항목 / 위치</th><th>일본어 원문</th><th>수정 전</th><th>수정 후 제안 / 반영</th><th>대조 근거</th></tr></thead><tbody>'+''.join(cards)+'</tbody></table></div>'
    page+='<footer>문구를 읽은 검수이며 오류가 전혀 없다는 보증은 아닙니다. 숫자·태그·줄바꿈 보존은 별도 정적 검증으로 확인합니다. 새 ISO는 만들지 않았습니다.</footer><script>const q=document.querySelector("#q"),s=document.querySelector("#state"),rs=[...document.querySelectorAll("tbody tr")];function filter(){let n=0;for(const r of rs){r.hidden=Boolean((s.value&&r.dataset.state!==s.value)||!r.textContent.toLowerCase().includes(q.value.toLowerCase()));if(!r.hidden)n++}document.querySelector("#count").textContent=n+"개 검토 묶음 표시"}q.addEventListener("input",filter);s.addEventListener("change",filter);filter();</script></html>'
    if applied:
        page=page.replace('우주인 정정 외 수정안은 미적용입니다.','수정안은 승인 반영했고 문맥 확인 항목도 사용자 위임에 따라 잠정 설정했습니다.')
        page=page.replace('문맥 확인 항목은 추측으로 고치지 않았습니다.','문맥 선택의 근거와 미재현 말장난은 아래에 남겼으며 실제 실행 확인은 아직입니다.')
        page=page.replace('수정 제안</span>','수정안 승인 반영</span>').replace('문맥 확인</span>','문맥 잠정 선택</span>')
        page=page.replace('>수정 제안</option>','>승인 반영</option>').replace('>문맥 확인</option>','>잠정 선택</option>')
    dest=ROOT/'work/translation-review/corrections.html';dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(page,encoding='utf-8')
    return dict(reviewed_unique_pairs=len(pairs),draft_records=len(covered),proposals_validated=len(review['changes']),context_reviews=len(review['context_reviews']),explicit_corrections_verified=len(review['explicit_user_corrections']))


if __name__=='__main__':
    print(json.dumps(render(),ensure_ascii=False))
