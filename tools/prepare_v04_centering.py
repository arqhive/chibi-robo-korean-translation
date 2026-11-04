"""Correct the title-specific footer missed by v03; memory-only preparation.

Run the actual title getter -> sprintf -> positioning -> patched call chain,
not just a standalone wrapper. Keep v03 and its historical recipe reproducible.
"""
import struct
from PIL import Image
import numpy as np
from unicorn import UC_HOOK_CODE
import prepare_v03_corrections as v
import prepare_output_probe as p
from measure_message_windows import fpr_write, fpr_read

ROOT=p.ROOT
OUT=ROOT/'work/runtime-corrections/v04'
BASE=0x8069e000
TITLE_CALLS={0x80029ecc:BASE,0x80029f60:BASE,0x8002a478:BASE+0x200,0x8002aa3c:BASE+0x200}


def load():
    report=v.read('metadata/integrated_test_build_v03.json')
    with (ROOT/report['iso']['path']).open('rb') as f:
        f.seek(report['dol']['offset']);dol=f.read(report['dol']['bytes'])
    assert p.sha(dol)==report['dol']['sha256']
    return dol,report


def slot_stub():
    # Empty label has five fixed-step cells. Its real texture draw uses an
    # 0.8*size quad centered on each position, not the CFont advance width.
    # First bitmap starts at x=1, final bitmap ends at x=19 within 24px.
    # group center relative to first quad center:
    # 2*(size-5) + ((1+19)/2-12)*(0.8*size/24)
    # = 29*size/15 - 10. Derive the first center from the slot center f24.
    s=p.PPC(BASE+0x400);s.load(12,BASE+0x500)
    s.d(48,0,12,0);v.fmul(s,1,3,0);v.fop(s,21,1,24,1)
    s.d(48,0,12,4);v.fop(s,21,1,1,0);s.branch(0x800324ec)
    return s.finish()


def prepare():
    original,report=load();dol=bytearray(original);payload=bytearray(4096);patches=[]
    for at,data in [(0,v.center_stub(BASE,31)),(0x200,v.center_stub(BASE+0x200,6)),
                    (0x400,slot_stub()),(0x500,struct.pack('>ff',-29/15,10.))]:
        payload[at:at+len(data)]=data
    def patch(addr,data,expected,reason):
        off=v.offset(original,addr);assert dol[off:off+len(expected)]==expected
        patches.append({'offset':off,'address':hex(addr),'before':expected.hex(),'after':data.hex(),'reason':reason})
        dol[off:off+len(data)]=data
    for addr,target in TITLE_CALLS.items():patch(addr,v.branch(addr,target),v.branch(addr,v.PRINTF),'title footer actual-width centering')
    patch(0x80036c00,v.branch(0x80036c00,BASE+0x400),v.branch(0x80036c00,0x800324ec),'empty-slot visible bitmap center')
    ah=v.read('metadata/injection_memory_verification.json')['arena_hook']
    old=p.PPC(ah);old.load(11,BASE);new=p.PPC(ah);new.load(11,BASE+len(payload))
    patch(ah,new.finish(),old.finish(),'extend code reservation')
    size=int.from_bytes(original[0x98:0x9c],'big')
    assert int.from_bytes(original[0x50:0x54],'big')+size==BASE
    assert int.from_bytes(original[8:12],'big')+size==len(original)
    patches.append({'offset':0x98,'before':v.word(size).hex(),'after':v.word(size+len(payload)).hex(),'reason':'DOL section growth'})
    dol[0x98:0x9c]=v.word(size+len(payload));dol.extend(payload)
    assert report['dol']['offset']+len(dol)<=5177344
    restored=bytearray(dol[:len(original)])
    for row in patches:
        at=row['offset'];raw=bytes.fromhex(row['before']);restored[at:at+len(raw)]=raw
    assert restored==original
    mapping={r['character']:r for r in v.read('translation/full_font_plan.json')['mapping']}
    assert mapping['비']['bbox'][0]==1 and mapping['음']['bbox'][2]==19
    row=next(r for r in v.read('translation/text_catalog.json') if r['id']=='main.dol@00200ae0')
    assert row['translation']=='비어 있음'
    return bytes(dol),original,report,patches,bytes(payload)


def cstring(cpu,addr):
    out=bytearray()
    while b:=bytes(cpu.mem_read(addr+len(out),1))[0]:
        out.append(b);assert len(out)<1024
    return bytes(out)


def title_path(dol, xoffset=0.):
    u=v.cpu(dol,True);obj=0x81960000
    u.reg_write(p.regnum(1),p.STACK);u.reg_write(p.regnum(31),obj)
    u.mem_write(obj+0x37a4,struct.pack('>f',0.));u.mem_write(obj+0x37c4,struct.pack('>f',1.))
    fpr_write(u,29,0.);fpr_write(u,30,xoffset)
    captured=[]
    def hook(cpu,pc,size,_):
        if pc==v.PRINTF:
            captured.append({'raw':cstring(cpu,cpu.reg_read(p.regnum(5))).hex(),
                'x':fpr_read(cpu,1),'y':fpr_read(cpu,2),'size':fpr_read(cpu,4)})
            # Drawing excluded, but the real caller, getter, formatter, strlen,
            # wrapper and CFont width function all execute before this boundary.
            cpu.reg_write(p.reg.UC_PPC_REG_PC,cpu.reg_read(p.reg.UC_PPC_REG_LR))
    u.hook_add(UC_HOOK_CODE,hook)
    v.call(u,0x80029e18,0x80029f68)
    assert len(captured)==2
    return captured


def slot_path(dol,center,scale):
    u=v.cpu(dol,True);u.reg_write(p.regnum(1),p.STACK)
    for reg,val in {24:center,25:300.,26:1.,27:scale,28:1.}.items():fpr_write(u,reg,val)
    v.call(u,0x80036b68,0x800324ec)
    return fpr_read(u,1),fpr_read(u,3),cstring(u,u.reg_read(p.regnum(3)))


def verify(dol,original):
    old=title_path(original);new=title_path(dol)
    targets=['main.dol@00200818','main.dol@00200838'];catalog=v.read('translation/text_catalog.json')
    mapping={r['character']:r for r in v.read('translation/full_font_plan.json')['mapping']}
    metrics=v.read('metadata/glyph_metrics.json')['metrics'];result=[]
    for i,key in enumerate(targets):
        row=next(r for r in catalog if r['id']==key);text=row['translation']
        raw=b''.join(mapping[c]['code'].to_bytes(2,'big') if c in mapping else c.encode('cp932') for c in text)
        assert bytes.fromhex(old[i]['raw'])==bytes.fromhex(new[i]['raw'])==raw
        width=sum(mapping[c]['advance'] if c in mapping else metrics[c]['raw_advance_px'] for c in text)*21/24
        assert abs(new[i]['x']+width/2-21/2-320)<0.0001
        assert old[i]['y']==new[i]['y'] and old[i]['size']==new[i]['size']==21.
        result.append({'id':key,'translation':text,'old_x':old[i]['x'],'new_x':new[i]['x'],
            'real_advance':width,'new_advance_center':new[i]['x']+width/2-10.5})
    for shift in [-80.,80.]:
        moved=title_path(dol,shift)
        assert all(abs(moved[i]['x']-new[i]['x']-shift)<0.0001 for i in range(2))
    slot=[]
    for scale in [0.75,1.,1.25]:
        for center in [126.,320.,514.]:
            previous,size0,raw0=slot_path(original,center,scale)
            first,size,raw=slot_path(dol,center,scale)
            assert raw==raw0 and size==size0
            # Execute actual effect-loop position instruction for both endpoints.
            u=v.cpu(dol)
            positions=[]
            for index in [0,4]:
                fpr_write(u,0,float(index));fpr_write(u,26,size-5);fpr_write(u,27,first)
                u.emu_start(0x8003276c,0x80032770,count=2);positions.append(fpr_read(u,25))
            # Run the original effect renderer's spacing and quad-scale ops.
            fpr_write(u,29,size);fpr_write(u,25,first)
            u.emu_start(0x80032560,0x80032574,count=10)
            assert abs(fpr_read(u,26)-(size-5))<0.0001
            u.emu_start(0x80032644,0x80032658,count=10)
            quad=fpr_read(u,28)
            left=positions[0]+(1/24-0.5)*quad
            right=positions[1]+(19/24-0.5)*quad
            assert abs((left+right)/2-center)<0.0001
            slot.append({'center':center,'scale':scale,'old_first_center':previous,'new_first_center':first,
                'visible_left':left,'visible_right':right,'visible_center':(left+right)/2})
    # Extra title single-line paths use f6; verify saved args and original code guards.
    for addr in [0x8002a478,0x8002aa3c]:
        u=v.cpu(dol,True);raw=bytes.fromhex(new[1]['raw']);u.mem_write(p.STRING,raw+b'\0')
        for r,val in {1:p.STACK,3:p.OBJECT,4:0x141414ff,5:p.STRING}.items():u.reg_write(p.regnum(r),val)
        for r,val in {2:400.,3:0.,4:21.,5:21.,6:320.}.items():fpr_write(u,r,val)
        v.call(u,addr,v.PRINTF)
        assert abs(fpr_read(u,1)-new[1]['x'])<0.0001 and fpr_read(u,2)==400.
    u=v.cpu(dol);ah=v.read('metadata/injection_memory_verification.json')['arena_hook']
    for requested in [BASE-32,BASE,BASE+32,BASE+4096-32,BASE+4096,BASE+4096+32,0x81000000]:
        u.reg_write(p.regnum(3),requested);v.call(u,ah)
        assert int.from_bytes(u.mem_read(p.R13-0x72f0,4),'big')==max(requested,BASE+4096)
    return {'actual_title_caller':result,'title_offset_cases':3,'empty_slot_geometry_cases':slot,'arena_cases':7,
        'extra_title_callers':2,'title_getter_formatting_and_layout_executed':True,
        'final_gpu_verified':False,'mocked':'CFont printf drawing only; width fixture also skips post-glyph GX and paired stack spills'}


def main():
    dol,original,report,patches,payload=prepare();checks=verify(dol,original)
    OUT.mkdir(parents=True,exist_ok=True)
    with (ROOT/report['iso']['path']).open('rb') as f:
        f.seek(report['dol']['offset']+len(original));gap=f.read(len(payload))
    recipe={'base_build':'v03','base_dol_sha256':p.sha(original),'expected_dol_sha256':p.sha(dol),
        'base_dol_bytes':len(original),'new_dol_bytes':len(dol),'disc_offset':report['dol']['offset'],
        'patches':patches,'append_hex':payload.hex(),'disc_append_before_sha256':p.sha(gap)}
    p.save(OUT/'recipe.json',recipe)
    screen=ROOT/'work/runtime-feedback/v03/codex-clipboard-72195009-9e88-4414-9383-499234190423.png'
    a=np.array(Image.open(screen).convert('RGB'));roi=a[225:280]
    yy,xx=np.where((roi[:,:,0]>140)&(roi[:,:,1]>100)&(roi[:,:,2]<150))
    border=np.where(a[180].min(1)>210)[0]
    observed={'method':'gold fill threshold in y225..279; white frame threshold at y180',
        'text_fill_x_bounds':[int(xx.min()),int(xx.max())],
        'frame_x_bounds':[int(border.min()),int(border.max())],
        'text_center_minus_frame_center_pixels':float((xx.min()+xx.max()-border.min()-border.max())/2)}
    p.save(ROOT/'metadata/v04_centering_verification.json',{'source_build_sha256':report['iso']['sha256'],
        'candidate_dol_sha256':p.sha(dol),'recipe_sha256':p.sha((OUT/'recipe.json').read_bytes()),
        'cause':'Title-specific getter 0x8003a3ec adds 13 to UI indices. Its two footer calls at 0x80029ecc/0x80029f60 were not patched by v03.',
        'slot_cause':'v03 fixed byte counting but retained fixed 9px centering and omitted 24px bitmap transparent margins.',
        'checks':checks,'screenshot_measurement':observed,'new_iso_built':False,'runtime_fix_verified':False,
        'limits':['No live MEM1 found during read-only Dolphin process probe; loaded runtime revision not established.',
            'Geometry uses static glyph alpha bounds and the effect-loop position instruction, not a GPU screenshot.',
            'Advance centers are verified for footer; optical edge differences and animation need Dolphin confirmation.']})
    print('PASS:',checks['actual_title_caller'])
    print('PASS: 9 slot placement/scale cases; 2 additional title callers; no ISO written.')


if __name__=='__main__':main()
