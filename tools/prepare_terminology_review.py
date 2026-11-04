"""Validate draft evidence and render a review, without translating/building."""
import hashlib,json,unicodedata
from collections import Counter
from inspect_discs import ROOT,save

def main():
    catalog_path=ROOT/'translation/text_catalog.json';raw=catalog_path.read_bytes();catalog=json.loads(raw);byid={r['id']:r for r in catalog}
    glossary=json.loads((ROOT/'translation/glossary.json').read_text());style=json.loads((ROOT/'translation/style.json').read_text())
    hints=json.loads((ROOT/'metadata/speaker_hints.json').read_text());assert hints['source_sha256']==hashlib.sha256(raw).hexdigest()
    entries=glossary['entries'];assert len({r['source'] for r in entries})==len(entries)
    project=json.loads((ROOT/'project.json').read_text())
    assert len({r['id'] for r in entries})==len(entries)
    norm=lambda s:unicodedata.normalize('NFKC',s)
    covered=[]
    for e in entries:
        assert e['source'] and e['ko'] and e['evidence_ids']
        for ident in e['evidence_ids']:assert ident in byid and e['source'] in norm(byid[ident]['source'])
        for ident in e['name_record_ids']:
            r=byid[ident];assert r['kind']=='metadata_string' and r['label'].endswith('.name') and norm(r['source'])==e['source'];covered.append(ident)
    expected={r['id'] for r in catalog if r['kind']=='metadata_string' and r['label'].endswith('.name') and r['source'].strip()}
    assert len(covered)==len(set(covered)) and set(covered)==expected
    for p in style['profiles']:
        for ident in p['evidence_ids']:assert ident in byid
    hint_byid={r['id']:r for r in hints['records']}
    def cell(s):return s.replace('|','\\|').replace('\n',' / ')
    lines=['# 치비로보 용어·말투 검토안','',
        '일본판 원문을 기준으로 작성한 용어 제안서다. 사용자 승인 상태는 `project.json`만 따른다. 이름 표 243개 필드를 포괄하지만 모든 대사의 용어를 빠짐없이 수집했다는 뜻은 아니다. 이 문서 생성 명령은 원문·본문 번역·시험 ISO를 변경하지 않는다.','',
        '생성 시점 승인 상태: '+('용어·말투 초안 승인됨. 문맥 미확인 명칭은 계속 보류.' if project['decisions'].get('glossary_approved') else '승인 대기.'),'',
        '## 우선 확인할 표기','',
        '핵심 제안은 톤피, 깃초맨, 호크, 삼푸, 슨미다, 베베, 피츠 공주, 조빈, 토이 렉스, 데카로보, 마네, 정크, 레치커즈다. 이 명칭들은 한국 공식명으로 확인된 표기가 아니라 일본판 원문에 근거한 제안이다.','',
        '병사 이름의 말장난은 원문대로 음역한다. 기능성 칩은 모아쏘기 칩·멀리쏘기 칩·우주 보청 칩을 제안한다. `色紙`의 사인지, `ミニファンキーブチ`의 얼룩 미니 펑키, `おしゃぶりボーン`의 쪽쪽이 뼈다귀는 실물/사용 문맥 확인이 필요한 잠정안이다.','',
        '일반 명사를 기계적으로 한 표현으로 치환하지 않는다. 마네는 고유 통화명이고 일반 お金는 문맥상 돈이다. 영문 그래픽은 원본 유지다.','',
        '## 원문 근거','',
        '- [닌텐도 GC 인물·로봇 소개](https://www.nintendo.co.jp/ngc/ggtj/chara/index.html)','- [닌텐도 GC 장난감 소개](https://www.nintendo.co.jp/ngc/ggtj/chara/page02.html)','- [닌텐도 GC 이야기·용어](https://www.nintendo.co.jp/ngc/ggtj/story/index.html)','',
        '일본어 이름·설정은 공식 페이지와 원본 데이터로 대조했다. 한국 닌텐도 검색에서 해당 인물들의 공식 한국어 표기를 확보하지 못했다는 것은 자료가 존재하지 않는다는 증명이 아니다. 후속작의 설정/북미판 개명은 가져오지 않았다.','',
        '## 용어 전체','', '| ID | 일본어/원문 | 한국어 제안 | 분류 | 주의점 |','| --- | --- | --- | --- | --- |']
    for e in entries:lines.append('| '+' | '.join(cell(s) for s in [e['id'],' / '.join(e['source_variants']),e['ko'],', '.join(e['categories']),e['note']])+' |')
    lines+=['','## 문체 규칙','']
    for rule in style['rules'].values():lines.append('- '+rule)
    lines+=['','## 말투 제안과 원문 표본','', '화자 연결은 조사 후보다. 음성·애니메이션 지정이 화자 확정을 대신하지 않는다. 아래 표본은 번역문이 아니라 원문 근거이며 `⟦format:…⟧`은 동적 변수 자리다.','']
    for p in style['profiles']:
        lines += ['### '+p['name'],'',p['proposal'],'']
        for ident in p['evidence_ids']:
            text=hint_byid.get(ident,{}).get('source_with_formats',byid[ident]['source'])
            lines += ['`'+ident+'`','', '> '+text.replace('\n','\n> '),'']
    lines += ['## 기술 조사와 한계','',
        f'스크립트 후보 {len(hints["records"]):,}항목의 음성/애니메이션 단서를 조사했다. 분류: `{hints["counts"]}`. 후보는 `metadata/speaker_hints.json`에 별도로 두었으며 원본 목록의 speaker를 자동 확정하지 않았다.','',
        '애니메이션의 20000+이름 ID 대응은 일본판 자기소개·음성·이름 표의 상관관계로 지지되는 가설이다. 실행 코드의 객체 탐색을 완전히 추적한 결과는 아니다. 음성 공유·음성 없음·태그 상속·듣는 인물의 동작·동적 이름 변수는 개별 검토가 필요하다.','',
        '남은 그래픽 31묶음은 계속 보류다. 창 연결·전체 한글 글리프·번역문 길이 변경 재배치 및 게임 실행 검증은 해결되지 않았다. 용어집 승인 전 본문 번역을 적용하거나 새 빌드를 만들지 않는다.','',
        '재현: `python -X utf8 tools/analyze_speaker_hints.py` → `python -X utf8 tools/prepare_terminology_review.py`. 두 명령은 원문/본문 번역/ISO를 바꾸지 않는다.','']
    (ROOT/'docs/terminology-review.md').write_text('\n'.join(lines),encoding='utf-8')
    assert catalog_path.read_bytes()==raw
    save(ROOT/'metadata/terminology_verification.json',dict(entries=len(entries),metadata_name_fields_covered=len(covered),style_profiles=len(style['profiles']),
        evidence_references_verified=True,catalog_sha256=hashlib.sha256(raw).hexdigest(),
        catalog_unchanged=True,new_iso_built=False,speaker_hints=hints['counts']))
    print('Verified glossary entries',len(entries),'name fields',len(covered),'style profiles',len(style['profiles']))

if __name__=='__main__':main()
