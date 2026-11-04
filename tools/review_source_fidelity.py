"""Record manual source/translation comparison coverage; never edit translations."""
import argparse, copy, hashlib, json
from pathlib import Path
from inspect_discs import ROOT
from translation_tokens import translated_tokens

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['show','record'])
    parser.add_argument('start',type=int)
    parser.add_argument('end',type=int)
    parser.add_argument('--findings',type=Path)
    args=parser.parse_args()
    path=ROOT/'work/fidelity-audit/coverage.json'
    audit=json.loads(path.read_text(encoding='utf-8'))
    catalog=ROOT/'translation/text_catalog.json'
    assert hashlib.sha256(catalog.read_bytes()).hexdigest()==audit['catalog_sha256']
    assert 0<=args.start<args.end<=len(audit['groups'])
    if args.action=='show':
        for row in audit['groups'][args.start:args.end]:
            print(str(row['index'])+'|'+row['source'].replace('\n',' / ')+'|'+row['translation'].replace('\n',' / '))
        return
    rows={r['id']:r for r in json.loads(catalog.read_text(encoding='utf-8'))}
    if args.findings:
        for line in args.findings.read_text(encoding='utf-8-sig').splitlines():
            if not line.strip():continue
            i,category,after,reason=line.split('|',3);i=int(i)
            assert args.start<=i<args.end
            group=audit['groups'][i]
            suggestion=after.replace('\\n','\n') if after else None
            if suggestion:
                for id in group['ids']:
                    candidate=copy.deepcopy(rows[id]);candidate['translation']=suggestion
                    translated_tokens(candidate)
            audit['findings'].append(dict(group_index=i,ids=group['ids'],source=group['source'],before=group['translation'],after=suggestion,category=category,reason=reason,approval='pending',applied=False))
    audit['reviewed_ranges'].append([args.start,args.end])
    covered={i for a,b in audit['reviewed_ranges'] for i in range(a,b)}
    audit['reviewed_unique_pairs']=len(covered)
    audit['complete']=len(covered)==len(audit['groups'])
    path.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Recorded manual comparison',args.start,args.end,'findings',len(audit['findings']))

if __name__=='__main__':main()
