"""Extract editable catalogs without disc mutation. Preserve user-authored fields.

Dialogue remains explicitly a structural scan; no claim of full JP control flow.
Metadata tables are bounded by their first string and the next table address.
"""
import json,re,struct,hashlib
from collections import Counter,defaultdict
from inspect_discs import ROOT,save
from analyze_stage1 import parse_msg

def sha(b):return hashlib.sha256(b).hexdigest()
def ja(s):return bool(re.search('[\u3040-\u30ff\u3400-\u9fff]',s))
def merge(path,rows):
    old={r['id']:r for r in json.loads(path.read_text('utf-8'))} if path.exists() else {}
    for row in rows:
        previous=old.get(row['id'],{})
        if previous and previous['source']!=row['source']:raise ValueError('Source changed: '+row['id'])
        for key in ('translation','translation_format','speaker','window','notes','review','selection'):
            if key in previous:row[key]=previous[key]
    assert not (set(old)-{r['id'] for r in rows}), 'Existing rows would be dropped'
    save(path,rows)

def run(edition):
    base=ROOT/f'work/roundtrip/{edition}/qp/files';sub='bin' if edition=='jp' else 'bin/e'
    rows=[];extras=[];components={};spans=defaultdict(list)
    def component(file):
        if file not in components:
            p=ROOT/f'work/roundtrip/{edition}/main.dol' if file=='main.dol' else base/file
            components[file]=p.read_bytes()
        return components[file]
    def add(file,offset,end,source,tokens,kind,label=None,**kw):
        row=dict(id=f'{file}@{offset:08x}',file=file,offset=offset,end=end,label=label,kind=kind,source=source,translation=None,speaker=None,window=None,
            language='ja_or_mixed' if ja(source) else 'non_ja',tokens=tokens,**kw)
        rows.append(row);spans[file].append((offset,end,row));return row
    for r in json.loads((ROOT/f'work/analysis/{edition}/message_candidates.json').read_text()):
        off=r['offset']+5;length=sum(len(bytes.fromhex(t['hex'])) for t in r['tokens'])
        add(r['file'],off,off+length,r['source'],r['tokens'],'script_message_candidate',opcode_offset=r['offset'],opcode=r['opcode'],confidence=r['status'])
    file=f'{sub}/globals.bin';b=component(file);gh=struct.unpack_from('<6I',b);start=24+gh[0];m=b[start:start+gh[1]];head=struct.unpack_from('<21I',m)
    tables=[('item',10,159,20,2),('actor',11,64,4,1),('equipment',12,9,12,2),('suit',13,9,4,1),('stage',14,30,8,2),('leticker',18,20,12,2),('sticker',19,24,12,2),('stat',20,13,8,2)]
    for name,hi,count,stride,fields in tables:
        table=head[hi];first=struct.unpack_from('<I',m,table)[0]
        assert first==table+count*stride
        limit=min([v for v in head if v>table]+[len(m)])
        for i in range(count):
            for j in range(fields):
                pointer=table+i*stride+j*4;off=struct.unpack_from('<I',m,pointer)[0]
                assert first<=off<limit;end=m.index(0,off)+1;assert end<=limit
                raw=m[off:end];source,tokens,_=parse_msg(raw,edition)
                add(file,start+off,start+end,source,tokens,'metadata_string',label=f'{name}.{i:03}.{["name","description"][j]}',pointer_offset=start+pointer,confidence='bounded_table_pointer')
    # Scan DOL data sections and REL modules conservatively. Do not label arbitrary
    # binary CP932 runs as confirmed user-facing text. Require kana/CJK and a NUL.
    inv=json.loads((ROOT/f'metadata/disc_inventory_{edition}.json').read_text())
    files=[('main.dol',component('main.dol'))]+[(p.relative_to(base).as_posix(),p.read_bytes()) for p in sorted((base/'rel').glob('*.rel'))]
    for file,b in files:
        if file=='main.dol':
            regions=[(s['file_offset'],s['file_offset']+s['size']) for s in inv['dol']['sections'] if s['kind']=='data']
        else:regions=[(0,len(b))]
        count=0
        for lo,hi in regions:
            # Restrict byte alphabet first, then decode strictly. Data candidates
            # stay separate from the translation catalog until individually linked.
            for match in re.finditer(rb'[\x09\x0a\x0d\x20-\x7e\x80-\xfc]{4,}\x00',b[lo:hi]):
                raw=match.group()[:-1]
                try:s=raw.decode('cp932')
                except UnicodeError:continue
                if not ja(s) or len(s)<2:continue
                off=lo+match.start();count+=1
                extras.append(dict(id=f'{file}@{off:08x}',file=file,offset=off,source=s,raw_hex=raw.hex(),translation=None,speaker=None,window=None,
                    confidence='nul_terminated_cp932_candidate_not_display_verified'))
                # The JP main rodata string region includes the known menu fields.
                # 0x30 (ASCII zero) is alignment fill, not a Japanese prefix. Only
                # trim it up to the next 4-byte boundary, retaining explicit proof.
                # Keep all generic scans above as separate evidence, including rejects.
                if edition=='jp' and file=='main.dol' and 0x1fbfa0<=off<0x20d8c0:
                    aligned=(off+3)&~3
                    if b[off:aligned] not in (b'',b'0',b'00',b'000'):continue
                    clean=b[aligned:lo+match.end()-1]
                    try:source=clean.decode('cp932')
                    except UnicodeError:continue
                    japanese=sum('\u3040'<=c<='\u30ff' or '\u3400'<=c<='\u9fff' for c in source)
                    if japanese<2 or japanese/max(1,len(source))<.3 or re.search('[\ue000-\uf8ff\uff61-\uff9f\x80]',source):continue
                    tokens=[dict(kind='text',source=source,hex=clean.hex()),dict(kind='end',hex='00')]
                    row=add(file,aligned,aligned+len(clean)+1,source,tokens,'dol_rodata_string_candidate',
                        confidence='aligned_rodata_cp932_string_display_reference_pending',alignment_prefix_hex=b[off:aligned].hex())
                    extras[-1]['catalog_id']=row['id']
        print(edition,file,count,'extra candidates')
    # WRD lists are speech-recognition vocabulary, not dialogue labels.
    for p in sorted((base/'gssdk').glob('*.wrd')):
        b=p.read_bytes();n,count=struct.unpack_from('>II',b);assert n==len(b)
        words=b[8:].split(b'\x00');assert words[-1]==b'' and len(words)-1==count
        cursor=8
        for i,raw in enumerate(words[:-1]):
            extras.append(dict(id=f'{p.relative_to(base).as_posix()}@{cursor:08x}',file=p.relative_to(base).as_posix(),offset=cursor,source=raw.decode('cp932'),raw_hex=raw.hex(),
                translation=None,speaker=None,window=None,kind='speech_recognition_vocabulary',confidence='wrd_count_and_size_verified'))
            cursor+=len(raw)+1
    # Actual roundtrip: replace every extracted message/metadata span with newly
    # serialized tokens in memory; verify whole components. Opaque bytes retained.
    checks=[]
    for file,fields in spans.items():
        b=component(file);out=bytearray(b);encoded=0
        for off,end,row in fields:
            chunks=[]
            for t in row['tokens']:
                raw=bytes.fromhex(t['hex'])
                if t['kind']=='text':
                    text=t['source'].replace('"','$') if edition=='us' else t['source']
                    try:chunk=text.encode('cp932')
                    except UnicodeError:chunk=text.encode('cp1252')
                    # CP932 aliases can have several valid byte representations.
                    # Preserve the original spelling only when canonical encoding differs.
                    if chunk!=raw:chunk=raw
                else:chunk=raw
                chunks.append(chunk)
            raw=b''.join(chunks);assert len(raw)==end-off and raw==b[off:end]
            out[off:end]=raw;encoded+=len(raw)
        assert bytes(out)==b
        checks.append(dict(file=file,fields=len(fields),serialized_bytes=encoded,whole_component_sha256=sha(b),byte_exact=True))
    target=ROOT/'translation' if edition=='jp' else ROOT/'work/extraction/us'
    merge(target/'text_catalog.json',rows);merge(target/'text_extra_candidates.json',extras)
    report=dict(edition=edition,records=len(rows),kinds=dict(Counter(r['kind'] for r in rows)),nonempty_records=sum(bool(r['source']) for r in rows),
        nonwhitespace_characters=sum(not c.isspace() for r in rows for c in r['source']),extra_candidates=len(extras),
        roundtrip=checks,limitations=['Script candidates are not complete JP control-flow traversal.','Exact original-length field serialization only; length-changing relocation not implemented.','Extra binary strings may include false positives/debug data.','Speaker and window linkage unresolved unless manually recorded.'])
    save(ROOT/f'metadata/text_extraction_{edition}.json',report);print(edition,report['records'],report['kinds'],report['nonwhitespace_characters'])

if __name__=='__main__':
    for edition in ('jp','us'):run(edition)
