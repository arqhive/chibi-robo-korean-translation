"""Resolve the %s name slots of script messages from the arguments the script pushes.

Before each script message the script pushes its format arguments and then
emits opcode 0x23 (5 bytes) right before the message bytes:
    10 6e 18 <u32 LE>   item number        -> item.NNN.name
    10 6d 18 <u32 LE>   20000 + actor no.  -> actor.NNN.name
Arguments are pushed in reverse order (last %s first).  Anything else
(registers, computed values) is reported as unresolved.
Writes work/name-slots/slots.json.
"""
import json, struct, collections
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JP = ROOT / 'work/roundtrip/jp/qp/files'


def main():
    cat = json.load(open(ROOT / 'translation/text_catalog.json', encoding='utf-8'))
    names = {r['label']: r for r in cat if r['file'] == 'bin/globals.bin' and (r.get('label') or '').endswith('.name')}
    data = {}
    out = []; stats = collections.Counter()
    for r in cat:
        toks = r.get('tokens') or []
        fmt = [i for i, t in enumerate(toks) if t['kind'] == 'format']
        if not fmt or r['kind'] != 'script_message_candidate' or r['file'] == 'main.dol':
            continue
        d = data.setdefault(r['file'], (JP / r['file']).read_bytes())
        o = r['offset']
        row = {'id': r['id'], 'slots': fmt, 'kinds': [toks[i]['hex'] for i in fmt], 'args': None}
        if d[o - 5] != 0x23:
            row['why'] = 'no 0x23 before message'; stats['no23'] += 1; out.append(row); continue
        p = o - 5; args = []
        while p >= 7 and d[p - 7] == 0x10 and d[p - 5] == 0x18:
            args.append((d[p - 6], struct.unpack_from('<I', d, p - 4)[0])); p -= 7
        # args collected backwards from the 0x23: nearest first == first pushed last == first %s? (pushed reversed)
        args = args[::-1]  # now in push order
        row['args'] = [[hex(k), v] for k, v in args]
        res = []
        for k, v in reversed(args):  # reversed push order == slot order
            if k == 0x6e: lab = 'item.%03d.name' % v
            elif k == 0x6d and v >= 20000: lab = 'actor.%03d.name' % (v - 20000)
            else: lab = None
            n = names.get(lab)
            res.append({'label': lab, 'source': n and n['source'], 'name': n and n.get('translation')})
        row['resolved'] = res
        stats['ok' if len(res) == len(fmt) and all(x['name'] for x in res) else 'partial'] += 1
        out.append(row)
    (ROOT / 'work/name-slots').mkdir(exist_ok=True)
    json.dump(out, open(ROOT / 'work/name-slots/slots.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(dict(stats), len(out))


if __name__ == '__main__':
    main()
