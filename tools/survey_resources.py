"""Inspect TPL headers and collect reproducible font-code evidence; no image edits."""
from collections import Counter
import json
import struct
from inspect_discs import ROOT,save
from verify_roundtrip import digest

def main():
    reports=[]
    for edition in ['jp','us']:
        files=[]
        for p in sorted((ROOT/f'work/roundtrip/{edition}/qp/files/tpl').glob('*.tpl')):
            b=p.read_bytes();magic,n,table=struct.unpack_from('>3I',b);assert magic==0x0020af30 and table+n*8<=len(b)
            textures=[]
            for i in range(n):
                at,pal=struct.unpack_from('>II',b,table+i*8);assert at+12<=len(b)
                h,w,fmt,data=struct.unpack_from('>HHII',b,at);assert w and h and data<len(b)
                textures.append({'index':i,'width':w,'height':h,'format':fmt,'data_offset':data,'palette_header':pal})
            files.append({'path':'tpl/'+p.name,'texture_count':n,'textures':textures})
        reports.append({'edition':edition,'tpl_files':len(files),'textures':sum(r['texture_count'] for r in files),
          'formats':dict(Counter(t['format'] for r in files for t in r['textures'])),'files':files,
          'limits':'TPL headers only. Not pixel decoding, text-bearing selection, DAT models, particles or movie frames.'})
    save(ROOT/'metadata/tpl_survey.json',{'editions':reports})
    # Addresses discovered from the respective original DOL, not inherited from another game.
    from capstone import Cs,CS_ARCH_PPC,CS_MODE_32,CS_MODE_BIG_ENDIAN
    md=Cs(CS_ARCH_PPC,CS_MODE_32|CS_MODE_BIG_ENDIAN)
    reports=[]
    for edition,lo,hi in [('jp',0x801a0448,0x801a0b90),('us',0x8019ec40,0x8019f130)]:
        b=(ROOT/f'work/roundtrip/{edition}/main.dol').read_bytes();inv=json.loads((ROOT/f'metadata/disc_inventory_{edition}.json').read_text())
        s=next(s for s in inv['dol']['sections'] if s['ram_address']<=lo and hi<=s['ram_address']+s['size'])
        off=s['file_offset']+lo-s['ram_address'];code=b[off:off+hi-lo]
        lines=[f'{x.address:08x} {x.mnemonic} {x.op_str}' for x in md.disasm(code,lo)]
        (ROOT/f'work/analysis/{edition}/font-path.asm').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        reports.append({'edition':edition,'address_start':hex(lo),'address_end':hex(hi),'code_sha256':digest(code),
         'evidence':f'work/analysis/{edition}/font-path.asm','findings':{'rom_font_error_strings_present':all(s in b for s in [b'cfont.cpp',b'OSLoadFont()',b'OSInitFont()']),
         'sjis_i2_buffer_constant':hex(0x90ee4),'ansi_buffer_constant':hex(0x10120)},
         'limits':'Disassembly and error-string references. CPU mapper tested separately; game rendering and font pixel replacement untested.'})
    save(ROOT/'metadata/font_path_evidence.json',{'editions':reports,'jp_cache':{'record_size':320,'records':50,'glyph_key_offset':288,'width_offset':290,'evidence_addresses':['0x801a0554','0x801a056c','0x801a0578','0x801a0588','0x801a05e0']}})

if __name__=='__main__':main()
