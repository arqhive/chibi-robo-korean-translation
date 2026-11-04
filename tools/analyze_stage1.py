"""Bounded message-record survey. Candidates are not a control-flow extraction.

Control payload sizes referenced from Unplug's MIT-licensed event/msg.rs, v0.5.1.
"""
from collections import Counter
import json
from pathlib import Path
import struct
import xml.etree.ElementTree as ET
from inspect_discs import ROOT,save
from verify_roundtrip import digest

SIZES={1:1,2:1,3:7,5:1,6:5,10:0,11:0,13:1,14:1,15:4,16:1,17:1,18:3,19:1,20:2,21:4,22:3,23:2,24:0}
NAMES={1:'speed',2:'wait',3:'anim',4:'sfx',5:'voice',6:'default',10:'newline',11:'newline-vt',12:'format',13:'size',14:'color',15:'rgba',16:'layout',17:'icon',18:'shake',19:'center',20:'rotate',21:'scale',22:'number-input',23:'question',24:'stay'}
def decode(b,edition):
    try:return b.decode('cp932')
    except UnicodeDecodeError:
        if edition=='jp':raise
        return b.decode('cp1252')
def parse_msg(raw,edition):
    i=0;tokens=[];text=[];tags=Counter()
    while i<len(raw):
        start=i;c=raw[i];i+=1
        if c==0:
            if i!=len(raw):raise ValueError('early end')
            tokens.append({'kind':'end','hex':'00'});return ''.join(text),tokens,tags
        if c>=32:
            while i<len(raw) and raw[i]>=32:i+=1
            b=raw[start:i];s=decode(b,edition)
            if edition=='us':s=s.replace('$','"') # Verified Unplug/game message escape.
            # Prove the decoded field can reconstruct its bytes; store hex for CP932 aliases.
            tokens.append({'kind':'text','source':s,'hex':b.hex()});text.append(s);continue
        if c==12:
            end=raw.index(12,i);decode(raw[i:end],edition);i=end+1
        elif c==4:
            if i+5>len(raw):raise ValueError('sfx')
            ty=raw[i+4];i+=5
            if ty in (2,3):i+=2
            elif ty==4:i+=3
            elif ty not in (0,1,5,6,255):raise ValueError('sfx type')
        elif c in SIZES:i+=SIZES[c]
        else:raise ValueError('unknown control')
        if i>=len(raw):raise ValueError('missing terminator')
        tokens.append({'kind':NAMES[c],'hex':raw[start:i].hex()});tags[NAMES[c]]+=1
        if c in (10,11):text.append('\n')
    raise ValueError('unterminated')

def main():
    results=[]
    for edition,sub in [('jp','bin'),('us','bin/e')]:
        folder=ROOT/f'work/roundtrip/{edition}/qp/files'/sub;rows=[];totaltags=Counter();functions=None
        for p in sorted(folder.glob('*.bin')):
            original=p.read_bytes();base=0;raw=original
            if p.name=='globals.bin':
                h=struct.unpack_from('<6I',raw);base=h[4]+24;raw=raw[base:base+h[5]]
                # Table end inferred only when its smallest pointer equals table byte length.
                for n in range(1,1000):
                    if n*4>len(raw):break
                    values=struct.unpack_from(f'<{n}I',raw)
                    if min(values)==n*4 and all(n*4<=v<len(raw) for v in values):functions=n;break
            spans=[]
            for i,c in enumerate(raw[:-6]):
                if c not in (0x23,0x2b):continue
                end=struct.unpack_from('<I',raw,i+1)[0]
                if not i+6<=end<=min(len(raw),i+4096) or raw[end-1]!=0:continue
                try:text,tokens,tags=parse_msg(raw[i+5:end],edition)
                except (ValueError,UnicodeError):continue
                rebuilt=b''.join(bytes.fromhex(t['hex']) for t in tokens)
                assert rebuilt==raw[i+5:end]
                spans.append((i,end));totaltags.update(tags)
                rows.append({'file':sub+'/'+p.name,'offset':base+i,'partition_offset':i,'end_pointer':end,'opcode':c,'source':text,'tokens':tokens,'status':'structural_candidate_not_control_flow_verified'})
            for a,b in zip(spans,spans[1:]):assert a[1]<=b[0], 'Overlapping candidate records'
        work=ROOT/f'work/analysis/{edition}';save(work/'message_candidates.json',rows)
        chars=''.join(r['source'] for r in rows)
        report={'edition':edition,'script_files':len(list(folder.glob('*.bin'))),'inferred_library_count':functions,'candidate_messages':len(rows),
                'nonwhitespace_characters':sum(not c.isspace() for c in chars),'distinct_nonwhitespace_characters':len({c for c in chars if not c.isspace()}),
                'control_counts':dict(totaltags),'by_file':dict(Counter(r['file'] for r in rows)),
                'message_bytes_roundtrip':'Tokens -> original bytes exact for every candidate. Decoded source/hex retained; NOT a length-changing script rebuild.',
                'limitations':['Includes development/unreachable records; opcode/end-pointer scan is not a complete script traversal.','Not whole-game text count; metadata names/DOL/graphics/movie text excluded.']}
        if edition=='us':
            xml=ET.parse(work/'messages.xml').getroot();texts=[]
            for m in xml:
                # Ignore XML indentation and format argument placeholders in comparison.
                s=''
                for t in m.findall('text'):
                    s+=t.text or ''
                    for ch in t:
                        if ch.tag in ('br','br-vt'):s+='\n'
                        s+=ch.tail or ''
                texts.append(s)
            known=Counter(texts);found=Counter(r['source'] for r in rows)
            missing=known-found
            report['unplug_export']={'messages':len(xml),'nonwhitespace_characters':sum(not c.isspace() for t in texts for c in t),
              'all_xml_messages_covered_by_candidates':not missing,'missing_count':sum(missing.values()),'xml_sha256':digest((work/'messages.xml').read_bytes())}
        results.append(report);print(edition,report['candidate_messages'],'candidates,',report['nonwhitespace_characters'],'characters, libs',functions,report.get('unplug_export',{}))
    save(ROOT/'metadata/text_survey.json',{'editions':results})

if __name__=='__main__':main()
