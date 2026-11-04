"""Reuse exact display/voice duplicates inside an explicitly reviewed file range."""
import argparse,copy,json
from inspect_discs import ROOT
from translation_tokens import template,translated_tokens

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--file',required=True)
    p.add_argument('--start',type=lambda x:int(x,16),required=True)
    p.add_argument('--end',type=lambda x:int(x,16),required=True)
    p.add_argument('--context',required=True)
    p.add_argument('--reference-file',action='append',default=[],help='Additional source files; only use after reviewing the target context.')
    a=p.parse_args();path=ROOT/'translation/text_catalog.json';raw=path.read_bytes();rows=json.loads(raw)
    def eligible(r):return r['file']==a.file and r['kind']=='script_message_candidate' and a.start<=r['offset']<=a.end and not (r.get('selection') or '').startswith('hold_')
    def key(r):return (template(r),tuple(t['hex'] for t in r['tokens'] if t['kind']=='voice'))
    sources={}
    for r in rows:
        if (eligible(r) or (r['file'] in a.reference_file and r['kind']=='script_message_candidate' and not (r.get('selection') or '').startswith('hold_'))) and r.get('translation') is not None:sources.setdefault(key(r),[]).append(r)
    count=0
    for r in rows:
        if not eligible(r) or r.get('translation') is not None:continue
        try:k=key(r)
        except ValueError:continue
        matches=sources.get(k,[])
        if not matches or len({x['translation'] for x in matches})!=1:continue
        source=matches[0];r['translation']=source['translation'];r['translation_format']=source['translation_format']
        r['review']=copy.deepcopy(source['review']);r['review']['reuse_source_id']=source['id'];r['review']['reuse_evidence']='Exact display template and voice; '+a.context
        translated_tokens(r);count+=1
    assert path.read_bytes()==raw
    if count:
        tmp=path.with_suffix('.json.tmp');tmp.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(path)
    print('Reused exact reviewed-context drafts:',count)

if __name__=='__main__':main()
