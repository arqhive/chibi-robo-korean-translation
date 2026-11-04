"""Verify Unicode drafts against unchanged source, without encoding or building."""
import copy,hashlib,html,json,re,subprocess,unicodedata
from collections import Counter
from inspect_discs import ROOT,save
from translation_tokens import translated_tokens,template

def main():
    path=ROOT/'translation/text_catalog.json';raw=path.read_bytes();rows=json.loads(raw)
    # Stable source snapshot predates translation; refs are repository-local.
    original=json.loads(subprocess.check_output(['git','show','e98f0eb:translation/text_catalog.json'],cwd=ROOT))
    source_keys=('id','file','offset','end','label','kind','source','tokens','opcode_offset','opcode','pointer_offset')
    assert [{k:r.get(k) for k in source_keys} for r in rows]==[{k:r.get(k) for k in source_keys} for r in original]
    project=json.loads((ROOT/'project.json').read_text());assert project['decisions']['glossary_approved'] and project['decisions']['style_approved']
    for name in ('glossary','style'):
        assert hashlib.sha256((ROOT/f'translation/{name}.json').read_bytes()).hexdigest()==project['decisions'][name+'_approved_sha256']
    metrics=json.loads((ROOT/'metadata/glyph_metrics.json').read_text())['metrics']
    records=[];warnings=[];number_equivalences=[];allchars=set();counts=Counter();control_count=0
    reviewed_numbers={
        'bin/stage05.bin@000064b9':(['1'],[],'もう１回 → 한 번 더'),
        'bin/stage05.bin@00006874':(['1'],[],'もう１回 → 한 번 더'),
        'bin/stage05.bin@000068a5':(['1'],[],'もう１回 → 한 번 더'),
        'bin/stage05.bin@00007ef6':(['1'],[],'１日 → 하루'),
        'bin/stage05.bin@00008051':(['1'],[],'１日 → 하루'),
        'bin/globals.bin@000019f6':(['2'],[],'２等兵 → 이등병'),
        'bin/globals.bin@0000281d':([],['3'],'三段棚 → 3단 선반'),
        'bin/globals.bin@00002c62':([],['1'],'一回 → 1회'),
        'bin/globals.bin@00027749':(['1'],[],'１日 → 하루'),
        'bin/globals.bin@00027782':(['1'],[],'１日 → 하루'),
        'bin/globals.bin@00027989':(['1'],[],'１日 → 하루'),
    }
    for offset in ('18112','18163','18e50','1b662','1b6d5','1b800','1b893',
                   '1cad7','1cb90','1f2bd','1f31e','20ba2','20c5d','22627',
                   '22695','2b9d2','2baba'):
        reviewed_numbers['bin/stage02.bin@'+offset.zfill(8)]=(['2'],[],'２等兵 → 이등병')
    for offset in ('1836d','2fe0e','30de9'):
        reviewed_numbers['bin/stage02.bin@'+offset.zfill(8)]=(['2'],[],'２度と → 다시는 / 두 번 다시')
    number=lambda s:re.findall(r'\d+',unicodedata.normalize('NFKC',re.sub(r'<\d+>','',s)))
    for r in rows:
        if r.get('translation') is None:continue
        tokens=translated_tokens(r);controls=[t for t in tokens if t['kind']!='text'];control_count+=len(controls)
        display=''.join(t['source'] for t in tokens if t['kind']=='text');allchars.update(display)
        assert not re.search('[\u3040-\u30ff\u3400-\u9fff]',display),r['id']
        ns=number(r['source']);nt=number(display)
        if ns!=nt:
            # Approved equivalence of Japanese battery size names.
            if r['id'] in reviewed_numbers:
                a,b,reason=reviewed_numbers[r['id']];assert (ns,nt)==(a,b)
                number_equivalences.append(dict(id=r['id'],source=ns,target=nt,reason=reason))
            elif r.get('label') not in ('item.058.name','item.059.name','item.060.name'):
                warnings.append(dict(id=r['id'],issue='literal_number_difference',source=ns,target=nt))
        counts[r['review']['batch']]+=1
        unresolved=[]
        if any(t['kind']=='format' for t in tokens):unresolved.append('dynamic_variable_and_particle_review')
        if r.get('window') is None:unresolved.append('window_not_bound')
        if any(c not in metrics for c in display):unresolved.append('glyph_metrics_unverified')
        if (r.get('selection') or '').startswith('hold_'):unresolved.append(r['selection'])
        records.append(dict(id=r['id'],batch=r['review']['batch'],controls_preserved=len(controls),unresolved=unresolved,window_fit=None))
    assert not warnings,warnings
    # Real-message corruption fixtures prove missing/reordered markers fail.
    sample=next(r for r in rows if r.get('translation') and len(re.findall(r'<\d+>',r['translation']))>=2)
    markers=re.findall(r'<\d+>',sample['translation']);bad=copy.deepcopy(sample)
    for value in [sample['translation'].replace(markers[0],'',1),sample['translation'].replace(markers[0],'<9999>',1)]:
        bad['translation']=value
        try:translated_tokens(bad)
        except ValueError:pass
        else:raise AssertionError('Corrupted controls accepted')
    dol_fixtures=0
    for control in ('\n','\t'):
        sample=next(r for r in rows if r['kind']=='dol_rodata_string_candidate' and r.get('translation') and control in r['translation'])
        bad=copy.deepcopy(sample);bad['translation']=bad['translation'].replace(control,'',1)
        try:translated_tokens(bad)
        except ValueError:dol_fixtures+=1
        else:raise AssertionError('Missing DOL LF/tab accepted')
    for r in rows:
        if r['kind']=='dol_rodata_string_candidate' and r.get('translation') is not None:
            assert len(r['source'])-len(r['source'].rstrip('\u3000'))==len(r['translation'])-len(r['translation'].rstrip('\u3000')),r['id']
    assert path.read_bytes()==raw
    report=dict(translated_drafts=len(records),batches=dict(counts),original_records_unchanged=len(rows),
        original_control_tokens_preserved=control_count,corruption_fixtures='rejected',
        dol_literal_control_corruption_fixtures_rejected=dol_fixtures,
        source_numbers_checked=True,battery_size_equivalence_exceptions=3,reviewed_number_equivalences=number_equivalences,
        distinct_unmeasured_characters=''.join(sorted(allchars-set(metrics))),
        dynamic_variable_records=sum('dynamic_variable_and_particle_review' in r['unresolved'] for r in records),
        confirmed_window_fits=0,new_iso_built=False,records=records)
    save(ROOT/'metadata/translation_verification.json',report)
    out=ROOT/'work/translation-review';out.mkdir(parents=True,exist_ok=True)
    cards=[]
    for r in rows:
        if r.get('translation') is None:continue
        cards.append('<tr><td>'+html.escape(r.get('label') or r['id'])+'</td><td><pre>'+html.escape(template(r))+'</pre></td><td>未訳</td><td><pre>'+html.escape(r['translation'])+'</pre></td><td>'+html.escape(r.get('notes',''))+'</td></tr>')
    page='''<!doctype html><meta charset="utf-8"><title>치비로보 번역 초안 대조표</title><style>body{font:15px system-ui;margin:24px;background:#f7f5ef;color:#252525}table{border-collapse:collapse;width:100%}td,th{padding:12px;border:1px solid #ccc;vertical-align:top}pre{font:inherit;white-space:pre-wrap;margin:0;min-width:220px}th{position:sticky;top:0;background:#e6dfcf}input{font:inherit;padding:8px;width:60%}</style><h1>치비로보 · 번역 초안 대조표</h1><p>원문 / 수정 전(미번역) / 초안. &lt;숫자&gt;는 원본 제어 토큰 자리이며 게임에 출력하는 글자가 아닙니다. 실행·창 폭·동적 조사 검수 전입니다.</p><input id="q" placeholder="이름, 원문, 번역, 경로 검색"><table><thead><tr><th>항목</th><th>원문</th><th>수정 전</th><th>번역 초안</th><th>메모</th></tr></thead><tbody>'''+''.join(cards)+'''</tbody></table><script>document.getElementById('q').addEventListener('input',e=>{const s=e.target.value.toLowerCase();document.querySelectorAll('tbody tr').forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(s))});</script>'''
    (out/'comparison.html').write_text(page,encoding='utf-8')
    proposals_path=ROOT/'translation/review_corrections.json'
    if proposals_path.exists():
        proposals=json.loads(proposals_path.read_text(encoding='utf-8'))
        index={r['id']:r for r in rows};cards=[]
        for change in proposals['changes']:
            row=index[change['id']]
            assert row['translation']==change['after' if change.get('applied') else 'before'],change['id']
            candidate=copy.deepcopy(row);candidate['translation']=change['after'];translated_tokens(candidate)
            assert number(change['before'])==number(change['after']),change['id']
            cards.append('<tr>'+''.join('<td><pre>'+html.escape(change[key])+'</pre></td>' for key in ('id','source','before','after','reason'))+'</tr>')
        (out/'corrections.html').write_text('<!doctype html><meta charset="utf-8"><title>치비로보 용어 수정 승인 대조표</title><style>body{font:16px system-ui;margin:24px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #aaa;padding:12px;vertical-align:top}pre{white-space:pre-wrap;font:inherit;min-width:180px}th{position:sticky;top:0;background:#eee}</style><h1>용어 수정 승인 대조표</h1><p>승인 용어집에 맞추는 수정안입니다. 현재 번역에는 미적용이며 사용자 검토를 기다립니다.</p><table><tr><th>항목</th><th>원문</th><th>수정 전</th><th>수정 후 제안</th><th>사유</th></tr>'+''.join(cards)+'</table>',encoding='utf-8')
    if (ROOT/'metadata/source_fidelity_review.json').exists():
        from render_fidelity_review import render
        render()
    print(json.dumps({k:v for k,v in report.items() if k not in ('records','distinct_unmeasured_characters')},ensure_ascii=False))

if __name__=='__main__':main()
