"""Conservative JP DOL string address/reference audit; no patch writes.

Constant propagation is restricted to straight-line code. Reported references
are evidence, not a complete pointer-use/control-flow proof.
"""
import json,struct
from collections import Counter
from capstone import Cs,CS_ARCH_PPC,CS_MODE_32,CS_MODE_BIG_ENDIAN
from capstone.ppc import PPC_OP_REG
import prepare_output_probe as p
from inspect_discs import ROOT,save
from translation_tokens import translated_tokens
from verify_message_relocation import encode_text

def main():
    dol=p.DOL.read_bytes();inv=json.loads(p.INV.read_text());assert p.sha(dol)==inv['dol']['sha256']
    cat=ROOT/'translation/text_catalog.json';digest=p.sha(cat.read_bytes())
    rows=[r for r in json.loads(cat.read_text('utf-8')) if r['kind']=='dol_rodata_string_candidate']
    plan=json.loads((ROOT/'translation/full_font_plan.json').read_text('utf-8'));assert plan['catalog_sha256']==digest
    mapping={m['character']:m['code'] for m in plan['mapping']};targets={};records=[]
    for r in rows:
        s=next(s for s in inv['dol']['sections'] if s['file_offset']<=r['offset']<s['file_offset']+s['size'])
        address=s['ram_address']+r['offset']-s['file_offset']
        assert dol[r['offset']:r['end']]==b''.join(bytes.fromhex(t['hex']) for t in r['tokens'])
        raw=None if r.get('translation') is None else b''.join(encode_text(t['source'],mapping) if t['kind']=='text' else bytes.fromhex(t['hex']) for t in translated_tokens(r))
        item={'id':r['id'],'address':address,'original_bytes':r['end']-r['offset'],'translated_bytes':len(raw) if raw else None,
              'fits_original_span':len(raw)<=r['end']-r['offset'] if raw else None,'selection':r.get('selection'),'references':[]}
        records.append(item)
        for delta in range(r['end']-r['offset']):
            assert address+delta not in targets;targets[address+delta]=(item,delta)
    # Constant pointers in DOL data sections, including interior references.
    for s in inv['dol']['sections']:
        if s['kind']!='data':continue
        for o in range(s['file_offset'],s['file_offset']+s['size']-3,4):
            value=struct.unpack_from('>I',dol,o)[0]
            if value in targets:
                item,delta=targets[value];item['references'].append({'kind':'data_pointer','file_offset':o,'address':s['ram_address']+o-s['file_offset'],'interior_delta':delta})
    # lis/addi/ori and r2/r13 address calculations. Kill unknown destinations and
    # clear state at every branch, including calls; this deliberately undercounts.
    cs=Cs(CS_ARCH_PPC,CS_MODE_32|CS_MODE_BIG_ENDIAN);cs.detail=True;cs.skipdata=True
    cpu=p.create_cpu(dol,inv,p.yay0(p.ROMFONT.read_bytes()));verified=0
    constants={2:(0x8063e160,None),13:(0x8063c2e0,None)}
    for s in inv['dol']['sections']:
        if s['kind']!='text':continue
        known=dict(constants)
        for ins in cs.disasm(dol[s['file_offset']:s['file_offset']+s['size']],s['ram_address']):
            if ins.mnemonic=='.byte' or ins.mnemonic.startswith('b'):
                known=dict(constants);continue
            v=int.from_bytes(ins.bytes,'big');op=v>>26;rt=(v>>21)&31;ra=(v>>16)&31;imm=v&65535;signed=imm-65536 if imm&32768 else imm
            result=None;dest=None;input_reg=None;input_value=None;origin=None
            if op in (14,15) and (ra==0 or ra in known):
                input_reg=ra;input_value=known[ra][0] if ra else 0;origin=known[ra][1] if ra else ins.address
                result=(input_value+(signed<<16 if op==15 else signed))&0xffffffff;dest=rt
            elif op in (24,25) and rt in known:
                input_reg=rt;input_value,origin=known[rt];result=input_value|(imm<<16 if op==25 else imm);dest=ra
            if result is not None:
                known[dest]=(result,origin)
                if result in targets:
                    # Execute the actual effective-address instruction with its
                    # recorded input, independently checking our arithmetic.
                    if input_reg:cpu.reg_write(p.regnum(input_reg),input_value)
                    cpu.emu_start(ins.address,ins.address+4,count=1)
                    assert cpu.reg_read(p.regnum(dest))==result
                    item,delta=targets[result];item['references'].append({'kind':'code_address','instruction':ins.address,
                        'producer':origin,'input_register':input_reg,'input_value':input_value,'result_register':dest,
                        'assembly':ins.mnemonic+' '+ins.op_str,'interior_delta':delta,'cpu_address_verified':True});verified+=1
            else:
                # PPC arithmetic/load instructions generally write operand zero;
                # stores/comparisons don't, except update stores write base too.
                if ins.mnemonic.startswith(('cmp','cmpl','st','mt','dc','ic','sync')):
                    if ins.mnemonic.startswith('st') and ins.mnemonic.endswith(('u','ux')):known.pop(ra,None)
                    continue
                if ins.operands and ins.operands[0].type==PPC_OP_REG:
                    name=ins.reg_name(ins.operands[0].reg)
                    if name.startswith('r') and name[1:].isdigit():known.pop(int(name[1:]),None)
    translated=[r for r in records if r['translated_bytes'] is not None]
    summary={'catalog_sha256':digest,'dol_sha256':p.sha(dol),'catalog_ui_records':len(rows),'translated':len(translated),
        'fits_original_span':sum(r['fits_original_span'] is True for r in translated),
        'requires_growth':sum(r['fits_original_span'] is False for r in translated),
        'translated_with_references':sum(bool(r['references']) for r in translated),
        'translated_without_reference_evidence':[r['id'] for r in translated if not r['references']],
        'cpu_address_instructions_verified':verified,
        'interior_references':sum(x['interior_delta']!=0 for r in records for x in r['references']),
        'reference_kinds':dict(Counter(x['kind'] for r in records for x in r['references'])),
        'new_iso_built':False,'patch_written':False,'complete_reference_proof':False,
        'limits':['Direct constant/reference evidence only; no complete pointer-table consumer or REL analysis',
                  'In-place size fit does not prove safe string suffix handling or renderer binding',
                  'Code-address CPU checks compute addresses, not game rendering',
                  '20 growing strings need relocation or separately reviewed byte-budget changes; translations unchanged']}
    save(ROOT/'metadata/dol_ui_reference_audit.json',{'summary':summary,'records':records})
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
