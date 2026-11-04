"""Check particles after resolved %s name slots (needs work/name-slots/slots.json).

Writes work/name-slots/particle_review.json: one row per slot whose particle
does not match the final consonant of the name that the script puts there,
plus rows that could not be resolved and slots glued to a following word.
"""
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (pattern, (no-batchim form, batchim form)); longest first
PAIRS = [('이(가)', ('가', '이')), ('을(를)', ('를', '을')), ('은(는)', ('는', '은')), ('와(과)', ('와', '과')),
         ('과(와)', ('와', '과')), ('(으)로', ('로', '으로')), ('(이)랑', ('랑', '이랑')), ('(이)나', ('나', '이나')),
         ('이에요', ('예요', '이에요')), ('예요', ('예요', '이에요')), ('이었', ('였', '이었')), ('였', ('였', '이었')),
         ('이라고', ('라고', '이라고')), ('라고', ('라고', '이라고')), ('이라면', ('라면', '이라면')), ('라면', ('라면', '이라면')),
         ('이랑', ('랑', '이랑')), ('랑', ('랑', '이랑')), ('으로', ('로', '으로')), ('로', ('로', '으로')),
         ('이야', ('야', '이야')), ('이다', ('다', '이다')),
         ('을', ('를', '을')), ('를', ('를', '을')), ('은', ('는', '은')), ('는', ('는', '은')),
         ('와', ('와', '과')), ('과', ('와', '과')), ('이', ('가', '이')), ('가', ('가', '이'))]


def batchim(ch):
    o = ord(ch) - 0xAC00
    if not 0 <= o < 11172: return None
    return o % 28


def want(name, form):
    j = batchim(name[-1])
    if j is None: return None
    no, yes = form
    if no == '로':  # ㄹ batchim takes 로
        return '로' if j in (0, 8) else '으로'
    return yes if j else no


def main():
    cat = {r['id']: r for r in json.load(open(ROOT / 'translation/text_catalog.json', encoding='utf-8'))}
    add = json.load(open(ROOT / 'translation/text_additions_v06.json', encoding='utf-8'))['records']
    cur = {i: r.get('translation') for i, r in cat.items()}
    for r in add: cur[r['id']] = r['translation']
    namecur = {r['label']: cur[r['id']] for r in cat.values() if (r.get('label') or '').endswith('.name')}
    slots = json.load(open(ROOT / 'work/name-slots/slots.json', encoding='utf-8'))
    rows = []
    for s in slots:
        t = cur.get(s['id']) or ''
        res = s.get('resolved') or []
        for n, idx in enumerate(s['slots']):
            if s['kinds'][n] != '0c25730c': continue
            m = re.search(r'<%d>' % idx, t)
            if not m: continue
            after = t[m.end():]
            after = re.sub(r'^(<\d+>)+', '', after)
            info = res[n] if n < len(res) else None
            name = info and info['label'] and namecur.get(info['label'])
            base = {'id': s['id'], 'source': cat[s['id']]['source'], 'translation': t, 'slot': idx,
                    'label': info and info['label'], 'name': name}
            if not name:
                hit = next((p for p, _ in PAIRS if after.startswith(p)), None)
                if hit and '(' in hit:
                    rows.append(dict(base, kind='unresolved', particle=hit))
                continue
            hit = next(((p, f) for p, f in PAIRS if after.startswith(p)), None)
            if hit:
                p, f = hit
                w = want(name, f)
                if '(' in p or (w and not p.startswith(w) and not w.startswith(p)) or (w and p != w and p in ('이', '가', '을', '를', '은', '는', '와', '과', '로', '으로', '랑', '이랑')):
                    if w and p != w:
                        rows.append(dict(base, kind='particle', particle=p, want=w))
            elif after[:1] and batchim(after[0]) is not None and not after.startswith(('의', '도', '만', '에', '께', '한', '님', '씨', '야', '아', '처럼', '보다', '까지', '부터', '조차', '마저', '밖에', '하고', '군', '양', '짱', '네', '들', '에게', '이랑', '이나', '나', '라')):
                rows.append(dict(base, kind='glued', next=after[:6]))
    json.dump(rows, open(ROOT / 'work/name-slots/particle_review.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    import collections
    print(collections.Counter(r['kind'] for r in rows))


if __name__ == '__main__':
    main()
