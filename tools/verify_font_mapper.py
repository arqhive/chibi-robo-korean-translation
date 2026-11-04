"""Execute each disc's actual PPC font-index routine in isolated synthetic RAM.

This verifies numeric mapping, not game rendering or a deployable patch address.
"""
import json
import struct
from unicorn import Uc,UC_ARCH_PPC,UC_MODE_32,UC_MODE_BIG_ENDIAN
from unicorn.ppc_const import UC_PPC_REG_3,UC_PPC_REG_4,UC_PPC_REG_LR
from inspect_discs import ROOT,save
from verify_roundtrip import digest

def main():
    jp=(ROOT/'work/roundtrip/jp/main.dol').read_bytes()
    ji=json.loads((ROOT/'metadata/disc_inventory_jp.json').read_text())
    address=0x80167768
    s=next(s for s in ji['dol']['sections'] if s['ram_address']<=address<s['ram_address']+s['size'])
    off=s['file_offset']+address-s['ram_address'];signature=jp[off:off+32]
    results=[]
    for edition in ['jp','us']:
        b=(ROOT/f'work/roundtrip/{edition}/main.dol').read_bytes();inv=json.loads((ROOT/f'metadata/disc_inventory_{edition}.json').read_text())
        hits=[];at=0
        while (at:=b.find(signature,at))>=0:hits.append(at);at+=1
        assert len(hits)==1
        at=hits[0];s=next(s for s in inv['dol']['sections'] if s['file_offset']<=at<s['file_offset']+s['size'])
        pc=s['ram_address']+at-s['file_offset']
        uc=Uc(UC_ARCH_PPC,UC_MODE_32|UC_MODE_BIG_ENDIAN);uc.mem_map(0x80000000,0x02000000)
        for seg in inv['dol']['sections']:uc.mem_write(seg['ram_address'],b[seg['file_offset']:seg['file_offset']+seg['size']])
        def call(enc,code):
            uc.reg_write(UC_PPC_REG_3,enc);uc.reg_write(UC_PPC_REG_4,code);uc.reg_write(UC_PPC_REG_LR,0x81fff000)
            uc.emu_start(pc,0x81fff000,count=150)
            return uc.reg_read(UC_PPC_REG_3)
        mapping={}
        for code in range(0x889f,0x9873):
            lo=code&255
            if not 0x40<=lo<=0xfc or lo==0x7f:continue
            result=call(1,code)
            expected=((code>>8)-0x88)*188+(lo-0x40-(lo>=0x80))+0x2be
            assert result==expected
            mapping[code]=result
        assert len(mapping)==len(set(mapping.values()))==2965
        assert call(0,0x41)==33 and call(0,0x889f)==0 and call(1,0x887f)==0
        results.append({'edition':edition,'mapper_ram_address':hex(pc),'mapper_file_offset':at,'routine_sha256':digest(b[at:at+0x174]),
          'sjis_kanji_distinct_cells':len(mapping),'index_min':min(mapping.values()),'index_max':max(mapping.values()),
          'fits_2350_by_slot_count':True,'ansi_A_index':33,'ansi_double_byte_code_returns_missing_cell':True,
          'limitations':['Synthetic RAM runs only mapper; no font pixels, cache rendering, hook, runtime memory or display validation.','2965 existing Japanese cells are replacement capacity, not spare unused cells. Preserve required Japanese/icon cells or expand separately.','USA has this mapper too, but runtime font encoding/default allocation may remain ANSI.']})
        print(edition,hex(pc),len(mapping),'distinct Kanji cells; ANSI cannot address two-byte codes')
    save(ROOT/'metadata/font_mapper.json',{'editions':results})

if __name__=='__main__':main()
