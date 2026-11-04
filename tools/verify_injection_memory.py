"""Candidate placement and loader arithmetic in CPU RAM; no DOL/ISO output."""
import json,struct
from capstone import Cs,CS_ARCH_PPC,CS_MODE_32,CS_MODE_BIG_ENDIAN
import prepare_output_probe as p
from prepare_full_font import make_stub
from inspect_discs import ROOT,save
from translation_tokens import translated_tokens
from verify_message_relocation import encode_text

BASE=0x8064c5c0
REAL_R13=0x8063c2e0
SET_ARENA_LO=0x8016486c
def align(n,a=32):return (n+a-1)&~(a-1)

def main():
    dol=p.DOL.read_bytes();inv=json.loads(p.INV.read_text())
    assert p.sha(dol)==inv['dol']['sha256']
    def at(pc,n=4):
        s=next(s for s in inv['dol']['sections'] if s['ram_address']<=pc and pc+n<=s['ram_address']+s['size'])
        o=s['file_offset']+pc-s['ram_address'];return dol[o:o+n]
    plan=json.loads((ROOT/'translation/full_font_plan.json').read_text('utf-8'))
    assert plan['catalog_sha256']==p.sha((ROOT/'translation/text_catalog.json').read_bytes())
    mapping=plan['mapping'];blob=(ROOT/'work/full-font/glyphs.i4').read_bytes()
    assert len(blob)==288*len(mapping)
    # Size first, then reassemble for the actual candidate RAM addresses.
    size=len(make_stub(mapping));arena=align(BASE+size);bitmaps=align(arena+64)
    ui_start=align(bitmaps+len(blob))
    codes={m['character']:m['code'] for m in mapping}
    ui_rows=[r for r in json.loads((ROOT/'translation/text_catalog.json').read_text('utf-8'))
             if r['kind']=='dol_rodata_string_candidate' and r.get('translation') is not None]
    ui_data=bytearray()
    for r in ui_rows:
        ui_data.extend(bytes(align(len(ui_data),4)-len(ui_data)))
        ui_data.extend(b''.join(encode_text(t['source'],codes) if t['kind']=='text' else bytes.fromhex(t['hex']) for t in translated_tokens(r)))
    end=align(ui_start+len(ui_data),4096);stub=make_stub(mapping,BASE,bitmaps)
    clamp=p.PPC(arena);clamp.load(11,end);clamp.emit(0x7c035840)
    clamp.bc(0x40800000,'original');clamp.d(36,11,13,-0x72f0);clamp.emit(0x4e800020)
    clamp.label('original');clamp.d(36,3,13,-0x72f0);clamp.emit(0x4e800020)
    clamp=clamp.finish();assert arena+len(clamp)<=bitmaps
    # Guard the previously derived startup constants, not just free-looking RAM.
    assert at(0x801631c0,8).hex()=='3c6080653863c5c0'
    assert at(SET_ARENA_LO,8).hex()=='906d8d104e800020'
    bss,n=struct.unpack_from('>II',dol,0xd8);assert bss+n==0x8063a5b0<0x8064a5b0<BASE
    assert all(s['ram_address']+s['size']<=BASE or s['ram_address']>=end for s in inv['dol']['sections'])
    cleared=[]
    for o in range(0,128,8):
        start,n=struct.unpack('>II',at(0x800055c8+o,8))
        if not n:break
        assert start+n<=BASE or start>=end;cleared.append([start,n])
    else:raise AssertionError('Missing startup clear terminator')
    cs=Cs(CS_ARCH_PPC,CS_MODE_32|CS_MODE_BIG_ENDIAN);cs.skipdata=True
    stores=[i.address for s in inv['dol']['sections'] if s['kind']=='text'
            for i in cs.disasm(dol[s['file_offset']:s['file_offset']+s['size']],s['ram_address'])
            if i.mnemonic=='stw' and i.op_str.endswith('-0x72f0(r13)')]
    assert stores==[SET_ARENA_LO,0x80164894]
    u=p.create_cpu(dol,inv,p.yay0(p.ROMFONT.read_bytes()))
    u.mem_write(BASE,stub);u.mem_write(arena,clamp);u.mem_write(bitmaps,blob);u.mem_write(ui_start,bytes(ui_data))
    branch=p.PPC(SET_ARENA_LO);branch.branch(arena);u.mem_write(SET_ARENA_LO,branch.finish())
    u.reg_write(p.regnum(13),REAL_R13)
    cases=[]
    for requested in [BASE-32,BASE,BASE+32,end-32,end,end+32,0x81000000]:
        u.reg_write(p.regnum(3),requested);u.reg_write(p.reg.UC_PPC_REG_LR,p.STOP)
        u.emu_start(SET_ARENA_LO,p.STOP,count=100)
        got=int.from_bytes(u.mem_read(REAL_R13-0x72f0,4),'big')
        assert got==max(end,requested) and u.reg_read(p.regnum(3))==requested
        cases.append({'requested':requested,'result':got})
    u.reg_write(p.regnum(13),p.R13)
    for m in mapping:
        got,width,n=p.texel(u,BASE,m['code'].to_bytes(2,'big'))
        i=m['bitmap_index'];assert got[:288]==blob[i*288:(i+1)*288]
        assert width==m['advance'] and n==2
    # Verify what the actual generic CFile loader requests from its allocator.
    # Stop at bctrl; allocator, I/O and heap availability are NOT mocked as passing.
    assert at(0x8018efc0,8).hex()=='806300084e800020'
    obj=0x81930000;vtable=obj+512;u.mem_write(obj+0xe8,struct.pack('>I',vtable))
    sizes={r['experiment_bytes'] for r in json.loads((ROOT/'metadata/relocation_experiment.json').read_text('utf-8'))['files']}
    if (ROOT/'metadata/metadata_relocation_verification.json').exists():
        sizes.add(json.loads((ROOT/'metadata/metadata_relocation_verification.json').read_text('utf-8'))['experiment_file_bytes'])
    sizes.update([1,31,32,33,0x80000]);loads=[]
    for length in sorted(sizes):
        u.mem_write(obj+0xc8,struct.pack('>I',length));u.reg_write(p.regnum(29),obj);u.reg_write(p.regnum(27),0)
        u.emu_start(0x801a14d8,0x801a1500,count=100)
        assert u.reg_read(p.reg.UC_PPC_REG_PC)==0x801a1500
        assert u.reg_read(p.regnum(4))==align(length)
        loads.append({'file_length':length,'allocation_request':align(length)})
    assert all(struct.unpack_from('>I',dol,o)[0]==0 for o in (8,0x50,0x98))
    disc_offset=align(inv['fst_offset']+inv['fst_size']);extended=align(len(dol))+end-BASE
    assert disc_offset+extended<min(f['offset'] for f in inv['files'])
    save(ROOT/'metadata/injection_memory_verification.json',{
        'catalog_sha256':plan['catalog_sha256'],'dol_sha256':p.sha(dol),
        'payload_start':BASE,'font_hook_bytes':len(stub),'arena_hook':arena,'bitmaps':bitmaps,
        'ui_start':ui_start,'ui_bytes':len(ui_data),'ui_sha256':p.sha(ui_data),'ui_records':len(ui_rows),
        'payload_end':end,'reserved_bytes':end-BASE,'glyphs_rebased_cpu_verified':len(mapping),
        'arena_cases':cases,'startup_clear_ranges':cleared,'arena_stores':stores,
        'disc_candidate':{'text_slot':2,'dol_offset':disc_offset,'extended_dol_bytes':extended},
        'loader_allocation_cases':loads,'loader_size_field': 'CFile+0xc8; archive entry size at +8 via 0x8018efc0',
        'loader_allocation_entry':'0x801a14d8; stopped before allocator at 0x801a1500',
        'heap_availability_verified':False,'startup_boot_verified':False,'new_iso_built':False,
        'limits':['ArenaLo direct-store scan does not exclude indirect writes',
                  'Full payload has not booted; GPU/cache synchronization unverified',
                  'Generic loader allocation arithmetic only; game callers may override sizes',
                  'Heap fragmentation, concurrent resources and level transitions require runtime testing']})
    print('PASS:',len(mapping),'rebased glyphs;',end-BASE,'reserved bytes;',len(loads),'loader arithmetic cases. No DOL/ISO written.')

if __name__=='__main__':main()
