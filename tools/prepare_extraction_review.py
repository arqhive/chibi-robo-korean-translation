"""Build scope-review artifacts from extraction facts and saved project decisions.

Does not assign human approval. Selection lives only in project.json; generated
review pages and tables are disposable views of that authoritative state.
"""
import json,html,hashlib
from collections import Counter
from pathlib import Path
from PIL import Image,ImageDraw
from inspect_discs import ROOT,save

def main():
    project=json.loads((ROOT/'project.json').read_text('utf-8'))
    observations=json.loads((ROOT/'metadata/graphics_visual_observations.json').read_text('utf-8'))
    catalog=json.loads((ROOT/'metadata/graphics_catalog_jp.json').read_text('utf-8'))
    us=json.loads((ROOT/'metadata/graphics_catalog_us.json').read_text('utf-8'))
    ushash={r['pixel_sha256'] for r in us['images'] if r['decoded']}
    byid={r['id']:r for r in catalog['images']}
    old={r['pixel_sha256']:r for r in project.get('graphics_selection',[])}
    selection=[]
    for o in observations['groups']:
        state=old.get(o['pixel_sha256'])
        if state is None:
            state=dict(pixel_sha256=o['pixel_sha256'],selection=o['suggested_selection'],reason=o['observation'],worker='main',approval=None)
        selection.append(state)
    project['graphics_selection']=selection
    followup=project['decisions'].get('stage4_investigate_holds_first',False)
    if not followup:
        project['stage']=4;project['status']='extraction_review_ready_scope_approval_pending'
    counts=Counter(r['selection'] for r in selection)
    rejected=counts['exclude_not_texture'];held=sum(n for k,n in counts.items() if k.startswith('hold_'))
    project['checks']['graphics_survey']=f'JP1083/US1086 top-level DAT plus780 pc.bin indexed DAT each surveyed. Both5TPL,57particle frames and BNR decoded. JP15048 diagnostic descriptor/level entries retained for reproducibility;2345 initial base groups, {rejected} rejected nontextures; {held} groups still held. See graphics_selection for current decisions.'
    text_report=json.loads((ROOT/'metadata/text_extraction_jp.json').read_text('utf-8'))
    project['checks']['text_extraction']=f"JP{text_report['records']} records:{text_report['kinds']};{text_report['nonwhitespace_characters']} nonwhitespace chars. {text_report['extra_candidates']} extra DOL/REL/WRD candidates (including linked duplicates) separate. {len(text_report['roundtrip'])} whole components byte-exact after field serialization; no length-changing relocation."
    project['checks']['movies']='4THP per edition:7594frame boundaries checked,128 native PNG samples per edition. Japanese karaoke text observed; no all-frame text coverage claim.'
    project['checks']['extraction_limits']=f'JP control flow/speaker/window links incomplete; DOL/REL string candidates not all proven UI; {held} graphic groups held; speech recognition language model opaque; movies sampled only. No localized build performed.'
    if not followup:project['next_work']='User stage4 scope decision, then stage5 glossary proposal. Resolve technical holds before affected translation/insertion; no new build authorized.'
    if not any(d.get('stage4_extraction') for d in project['decision_history']):
        project['decision_history'].append(dict(date='2026-10-14',stage4_extraction=True,decision='User requested next stage after common window measurement. Read-only stage4 extraction and visual triage prepared. Scope approval pending; translation/glossary/build not started.'))
    proposal={
        'text':'Japanese GC main-game script candidates, metadata names/descriptions and UI strings after source/use verification. Preserve original English.',
        'graphics':'Confirmed Japanese UI/logo/banner/effect groups; preserve English. Small illegible labels, currency monograms, seal-like glyphs and test assets held for contextual decisions.',
        'movie':'Japanese karaoke subtitles included as an identified separate asset; translation/re-encoding design remains to be established.',
        'audio':'Existing speech/audio unchanged; WRD/CTX/LNG speech-recognition data inventoried separately, not dialogue translation.',
        'system_banner_text':'BNR title/comment outside game font kept pending external-rendering policy; image is a logo duplicate.',
        'unfinished_technical_work':['Full Japanese script control flow and translated-length relocation','DOL/REL UI references and speaker/window binding','HSD candidate false-positive/type verification','Unreadable graphics and all-frame video coverage']}
    if not followup:project['extraction_scope_proposal']=proposal
    save(ROOT/'project.json',project)
    states={r['pixel_sha256']:r for r in selection};counts=Counter(r['selection'] for r in selection)
    review=[]
    for o in observations['groups']:
        s=states[o['pixel_sha256']]
        if s['selection'] in ('keep_original','exclude_not_texture'):continue
        representative=byid[o['ids'][0]]
        review.append(dict(**o,selection=s['selection'],reason=s['reason'],png=representative['png']))
    out=ROOT/'work/extraction/jp';cards=[]
    for r in review:
        path=Path(r['png']).relative_to('work/extraction/jp').as_posix()
        cards.append(f'<article><h3>{r["sheet_index"]:04} · {html.escape(r["selection"])}</h3><img src="{path}"><p>{html.escape(r["reason"])}</p><small>{html.escape(r["ids"][0])} · {len(r["ids"])} occurrences</small></article>')
    page='''<!doctype html><meta charset="utf-8"><title>치비로보 조사 범위 검토</title><style>body{background:#202327;color:#eee;font:16px system-ui;margin:32px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:20px}article{background:#34383d;padding:16px;border-radius:10px}img{max-width:100%;max-height:220px;object-fit:contain;image-rendering:pixelated}small{overflow-wrap:anywhere}p{line-height:1.5}</style><h1>치비로보 · 일본어 그림과 보류 항목</h1><p>번역·편집 전 조사 결과입니다. 영어·숫자·비문자 그림은 원본 유지로 분류했습니다. 작은 글씨와 구조 미확인 항목은 보류이며 제외 확정이 아닙니다.</p><main>'''+''.join(cards)+'</main>'
    (out/'graphics-review.html').write_text(page,encoding='utf-8')
    # Source-sized image excerpts, arranged for review only. No retouched assets.
    targets=[r for r in review if r['selection']=='translate_japanese']
    for start in range(0,len(targets),8):
        sheet=Image.new('RGB',(1200,1120),(55,55,55));draw=ImageDraw.Draw(sheet)
        for j,r in enumerate(targets[start:start+8]):
            im=Image.open(ROOT/r['png']).convert('RGBA');im.thumbnail((575,235));x=j%2*600;y=j//2*280
            sheet.paste(im,(x+8,y),im);draw.text((x+8,y+242),f'{r["sheet_index"]:04} {r["ids"][0]}',fill='white')
        sheet.save(out/f'japanese-targets-{start//8:02}.png')
    comparison=dict(shared_pixel_groups=len({r['pixel_sha256'] for r in catalog['images']} & ushash),jp_only_pixel_groups=len({r['pixel_sha256'] for r in catalog['images']}-ushash),
        warning='Presence/absence of regional pixel equality is a clue, not proof that a graphic is used or unused.')
    save(ROOT/'metadata/extraction_review_summary.json',dict(graphics_selection=dict(counts),comparison=comparison,
        review_html='work/extraction/jp/graphics-review.html',observation_evidence='metadata/graphics_visual_observations.json'))
    print(json.dumps(dict(counts),ensure_ascii=False))

if __name__=='__main__':main()
