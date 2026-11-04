"""Apply the explicitly approved fidelity review, validating every row first."""
import copy
import hashlib
import json
import re
import unicodedata
from inspect_discs import ROOT, save
from translation_tokens import template, translated_tokens


def main():
    path=ROOT/'translation/text_catalog.json'; raw=path.read_bytes()
    rp=ROOT/'translation/review_corrections.json'
    review=json.loads(rp.read_text(encoding='utf-8'))
    assert review.get('application_authorization')=='user_approved_proposals_and_delegated_context_choices'
    if review.get('applied'):
        assert hashlib.sha256(raw).hexdigest()==review['applied_catalog_sha256']
        print('Already applied; catalog unchanged.');return
    assert hashlib.sha256(raw).hexdigest()==review['review_basis_catalog_sha256']
    rows=json.loads(raw);index={r['id']:r for r in rows}
    numbers=lambda s:re.findall(r'\d+',unicodedata.normalize('NFKC',re.sub(r'<\d+>','',s)))
    seen=set();changed=0
    for c in review['changes']+review['context_reviews']:
        assert c['id'] not in seen;seen.add(c['id'])
        r=index[c['id']]
        assert r['translation']==c['before'] and template(r)==c['source']
        assert isinstance(c['after'],str) and c['after']
        candidate=copy.deepcopy(r);candidate['translation']=c['after'];translated_tokens(candidate)
        assert numbers(c['before'])==numbers(c['after'])
        if r['kind']=='dol_rodata_string_candidate':
            assert len(c['before'])-len(c['before'].rstrip('\u3000'))==len(c['after'])-len(c['after'].rstrip('\u3000'))
        changed+=c['before']!=c['after'];r['translation']=c['after']
        c['applied']=True
        c['approval']='delegated_provisional_choice' if c in review['context_reviews'] else 'user_approved'
    review['applied']=True;review['approval']='applied_with_provisional_context_choices'
    review['application_date']='2026-10-14'
    review['application_summary']={'reviewed_records':len(seen),'changed_records':changed,'retained_records':len(seen)-changed,'context_choices':len(review['context_reviews'])}
    # No source, tokens, row metadata, or unaffected translation is changed.
    assert path.read_bytes()==raw
    save(path,rows)
    review['applied_catalog_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    save(rp,review)
    print(json.dumps(review['application_summary'],ensure_ascii=False))


if __name__=='__main__':main()
