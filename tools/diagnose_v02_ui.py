"""Investigate user-observed untranslated menu labels and centering, read-only.

Do not change approved catalog/ISO. Save proposed missing labels separately.
CPU checks exercise the real menu getter and the renderer's advance arithmetic;
they do not emulate GPU rendering or validate a complete centering fix.
"""
import json
import struct
import prepare_output_probe as p
from inspect_discs import ROOT, save
from build_output_probe import sections
from measure_message_windows import fpr_write, R2


def read(name): return json.loads((ROOT/name).read_text('utf-8'))


def main():
    original=p.DOL.read_bytes();inv=read('metadata/disc_inventory_jp.json')
    assert p.sha(original)==inv['dol']['sha256']
    report=read('metadata/integrated_test_build_v02.json')
    with (ROOT/report['iso']['path']).open('rb') as f:
        f.seek(0x420);offset=struct.unpack('>I',f.read(4))[0]
        f.seek(offset);dol=f.read(report['dol']['bytes'])
    assert p.sha(dol)==report['dol']['sha256']
    u=p.create_cpu(dol,{'dol':{'sections':sections(dol)}},p.yay0(p.ROMFONT.read_bytes()))
    u.reg_write(p.regnum(2),R2);u.reg_write(p.reg.UC_PPC_REG_MSR,0x2000)
    def ram(off):
        s=next(s for s in inv['dol']['sections'] if s['file_offset']<=off<s['file_offset']+s['size'])
        return s['ram_address']+off-s['file_offset']
    def raw_at(addr,n):
        s=next(s for s in inv['dol']['sections'] if s['ram_address']<=addr<s['ram_address']+s['size'])
        off=s['file_offset']+addr-s['ram_address'];return original[off:off+n]
    catalog=read('translation/text_catalog.json');known={r['id'] for r in catalog}
    suggestions={'そうび':'장비','きがえ':'갈아입기','はい':'예','いいえ':'아니요','セーブ':'저장',
        'ズーム':'줌','振動':'진동','する':'켬','しない':'끔','もどる':'돌아가기','マネ':'마네',
        'おわる':'끝내기','かう':'구입','えらぶ':'선택','つくる':'만들기','ロード':'불러오기','削除':'삭제'}
    offsets=[0x23952c,0x239534,0x23953c,0x239958,0x23995c,0x239960,0x239964,
             0x239b70,0x239b78,0x239b84,0x239b88,0x239b90,0x239b98,0x239ba0,
             0x239ba8,0x239bb0,0x239bb8,0x239bc0,0x239bc8,0x239bd4,0x239be4,0x239bec,0x239bf4,0x239bf8]
    candidates=[];getter_checks=0
    for off in offsets:
        end=original.index(0,off)+1;raw=original[off:end];text=raw[:-1].decode('cp932')
        id=f'main.dol@{off:08x}';assert id not in known
        address=ram(off);refs=[]
        for s in inv['dol']['sections']:
            if s['kind']!='data':continue
            for slot in range(s['file_offset'],s['file_offset']+s['size']-3,4):
                if struct.unpack_from('>I',original,slot)[0]!=address:continue
                entry={'file_offset':slot,'address':ram(slot)}
                # The observed menu strings share this existing UI table.
                if 0x21317c<=slot<0x213390:
                    index=(slot-0x21317c)//4
                    u.reg_write(p.regnum(3),index);u.reg_write(p.reg.UC_PPC_REG_LR,p.STOP)
                    u.emu_start(0x8006fff0,p.STOP,count=20)
                    assert u.reg_read(p.regnum(3))==address
                    assert bytes(u.mem_read(address,len(raw)))==raw
                    entry.update(menu_index=index,v02_getter_returns_original=True);getter_checks+=1
                refs.append(entry)
        candidates.append({'id':id,'file':'main.dol','offset':off,'end':end,'ram_address':address,
            'source':text,'translation_proposal':suggestions.get(text),'original_hex':raw.hex(),'references':refs,
            'state':'proposal_not_applied' if suggestions.get(text) else 'context_hold',
            'source_region':'DOL data section 14 (small-data strings)'})
    missing=[r for r in candidates if r['source'] in ['振動','する','しない','もどる']]
    assert len(missing)==4 and all(any(x.get('v02_getter_returns_original') for x in r['references']) for r in missing)
    # Prove the two actual layout paths count bytes, not characters or pixels.
    code_checks={
        'empty_label_strlen':(0x80036b88,'48123f99'),
        'empty_label_divide_two':(0x80036b8c,'5463f87e'),
        'footer_divide_two':(0x80032920,'5463f87e'),
        'single_help_divide_two':(0x800372fc,'547af87e'),
        'empty_slot_draw_index_spacing':(0x8003276c,'ef20deba'),
    }
    code=[]
    for name,(address,expected) in code_checks.items():
        raw=raw_at(address,4);assert raw.hex()==expected,(name,raw.hex())
        code.append({'name':name,'address':hex(address),'hex':raw.hex()})
    # Actual renderer 0x80196fdc..0x801970c4: variable advances, mode 1.
    # Fixed-position callers above instead assume one full cell per two bytes.
    widths=read('metadata/glyph_metrics.json')['metrics']
    mapping={x['character']:x for x in read('translation/full_font_plan.json')['mapping']}
    results=[]
    for id in ['main.dol@00200ae0','main.dol@00200818','main.dol@00200838']:
        row=next(r for r in catalog if r['id']==id);text=row['translation']
        data=b''.join(mapping[c]['code'].to_bytes(2,'big') if c in mapping else c.encode('cp932') for c in text)
        advances=[]
        for c in text:
            width=mapping[c]['advance'] if c in mapping else widths[c]['raw_advance_px']
            # Feed independently known font width to real renderer scalar block.
            u.reg_write(p.regnum(1),p.STACK);u.reg_write(p.regnum(25),1);fpr_write(u,19,21.)
            u.mem_write(p.STACK+0x10,struct.pack('>I',width));u.mem_write(p.STACK+0x14,bytes(4))
            u.emu_start(0x80196fdc,0x801970c4,count=100)
            actual=struct.unpack('>f',bytes(u.mem_read(p.STACK+0x14,4)))[0]
            assert abs(actual-width*21/24)<0.0001
            advances.append(actual)
        results.append({'id':id,'source':row['source'],'translation':text,'bytes':len(data),
            'legacy_byte_count_divided_by_two':len(data)//2,'unicode_characters':len(text),
            'at_size_21_renderer_advance_sum':sum(advances),'character_advances':advances,
            'legacy_full_cell_width_estimate':(len(data)//2)*21,
            'note':'21px is a comparison setting, not a measured screenshot scale. Empty-slot stylized renderer has separate per-character spacing.'})
    out={'build_sha256':report['iso']['sha256'],'catalog_sha256':p.sha((ROOT/'translation/text_catalog.json').read_bytes()),
        'observed_screenshots':['codex-clipboard-c8749288-77c8-4468-8393-8dbab9345d32.png',
                                'codex-clipboard-914aebbc-259d-404e-a6fb-8f8dcec6d66b.png'],
        'missing_labels':candidates,'menu_getter_cpu_checks':getter_checks,
        'extraction_cause':'extract_text_catalog.py only promotes main.dol offsets 0x1fbfa0..0x20d8c0; these section14 strings stayed extra candidates or were too short.',
        'centering_code_evidence':code,'renderer_advance_cpu':results,
        'status':'diagnosed_not_fixed_or_built',
        'limits':['No new semantic approvals or catalog edits','No ISO modification/new build',
                  'Numeric screenshot displacement and optical glyph centers not measured',
                  'Empty-slot per-character animation/spacing and other UI callers need separate fixes',
                  'GPU/runtime correction not verified']}
    save(ROOT/'metadata/v02_ui_diagnosis.json',out)
    print('PASS:',len(candidates),'missing small-data candidates;',getter_checks,'real menu getter checks; renderer advance arithmetic checked.')


if __name__=='__main__':main()
