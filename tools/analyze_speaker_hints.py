"""Read-only voice/animation clues; never assign confirmed catalog speakers.

Unplug msg.rs documents tag payloads. JP self-introductions and actor-name
metadata corroborate their use, but animation targets can be listeners.
"""
import hashlib,json,struct
from collections import Counter,defaultdict
from inspect_discs import ROOT,save

# Manual semantic hypotheses from JP text plus the local reference enum.
# Shared voices deliberately have multiple candidates, not one guessed name.
VOICE_ACTORS={0:[5],1:[57,58,59],2:[3],3:[1],4:[2],7:[8],8:[9],
    9:list(range(17,45)),10:[11],11:[12,53],13:[17],14:[3],16:[6],
    17:[45,46,47,48,60],18:[13],19:[14],20:[16,51],21:[15,50],
    22:[10],23:[10],24:[14],27:[4]}

def main():
    path=ROOT/'translation/text_catalog.json';before=path.read_bytes();catalog=json.loads(before)
    actors={int(r['label'].split('.')[1]):r['source'] for r in catalog if (r.get('label') or '').startswith('actor.')}
    rows=[];cross=defaultdict(Counter);counts=Counter()
    for r in catalog:
        if r['kind']!='script_message_candidate':continue
        voices=[];animations=[];display=[]
        for i,t in enumerate(r['tokens']):
            raw=bytes.fromhex(t['hex'])
            if t['kind']=='voice':assert len(raw)==2;voices.append(raw[1])
            elif t['kind']=='anim':
                assert len(raw)==8
                flags,obj,anim=struct.unpack_from('<Bhi',raw,1)
                animations.append(dict(token=i,flags=flags,object=obj,animation=anim,
                    candidate_actor_id=obj-20000 if obj-20000 in actors else None))
            if t['kind']=='text':display.append(t['source'])
            elif t['kind'] in ('newline','newline-vt'):display.append('\n')
            elif t['kind']=='format':display.append('⟦format:'+raw[1:-1].decode('cp932')+'⟧')
        vs=sorted(set(voices)-{255});aa=sorted({a['candidate_actor_id'] for a in animations if a['candidate_actor_id'] is not None})
        for a in aa:
            for v in vs:cross[a][v]+=1
        candidates=set().union(*(set(VOICE_ACTORS.get(v,[])) for v in vs)) if vs else set()
        if len(vs)>1:status='multiple_voice_settings_review_required';suggested=[]
        elif len(aa)==1 and aa[0] in candidates:status='single_animation_and_voice_corroborated_candidate';suggested=aa
        elif aa and candidates and not set(aa)&candidates:status='animation_voice_disagreement';suggested=[]
        elif len(candidates)==1:status='voice_only_candidate';suggested=sorted(candidates)
        elif candidates:status='shared_voice_ambiguous';suggested=sorted(candidates)
        else:status='insufficient_evidence';suggested=[]
        counts[status]+=1
        rows.append(dict(id=r['id'],voice_ids=vs,animations=animations,candidate_actor_ids=suggested,
            candidate_names=[actors[a] for a in suggested],evidence_class=status,
            source_with_formats=''.join(display)))
    assert path.read_bytes()==before
    save(ROOT/'metadata/speaker_hints.json',dict(schema_version=1,source_sha256=hashlib.sha256(before).hexdigest(),
        limits=['Animation targets can be listeners. No confirmed speaker assignments.',
            'Voice inheritance/default resets and complete control flow are not modeled.',
            'Source preview retains format placeholders but does not resolve their argument expressions.',
            'Actor base 20000 is a JP-data-correlated hypothesis; runtime object lookup is not independently traced.'],
        counts=dict(counts),actor_voice_cooccurrence={str(a):dict(v) for a,v in cross.items()},records=rows))
    print(json.dumps(dict(counts),ensure_ascii=False))

if __name__=='__main__':main()
