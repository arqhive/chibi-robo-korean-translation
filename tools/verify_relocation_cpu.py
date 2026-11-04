"""Exercise actual JP GOTO/MSG/SELECT handlers on experimental copied scripts.

Message drawing and selection audio calls are mocked; pointer arithmetic,
wait/retry/resume, selection result assignment and branch instructions are real.
No game/ISO build. Synthetic buffer addresses are NOT a deployment plan.
"""
import json,struct
from collections import defaultdict,Counter
from unicorn import UC_HOOK_CODE
import prepare_output_probe as p
ROOT=p.ROOT
STAGE=0x81000000
GLOBALS=0x81400000
MSGOBJ=0x81500000
THREAD=0x81920000
GOTO=0x8007e11c
MESSAGE=0x80076d78
TABLE=0x80224268

def verify_cpu(dol,inv,blobs,records):
    u=p.create_cpu(dol,inv,p.yay0(p.ROMFONT.read_bytes()))
    u.reg_write(p.regnum(1),p.STACK);u.reg_write(p.regnum(2),0x8063e160);u.reg_write(p.reg.UC_PPC_REG_LR,p.STOP)
    # Real table setup; stop before unrelated object/audio initialization.
    u.emu_start(0x800819c0,0x800820dc,count=100000)
    assert u.reg_read(p.reg.UC_PPC_REG_PC)==0x800820dc
    handlers={}
    for n in range(1,50):
        record=bytes(u.mem_read(TABLE+n*20,20));opcode=record[0]
        if opcode in (3,35,43):
            adjust,virtual,addr=struct.unpack_from('>3I',record,8)
            assert adjust==0 and virtual==0xffffffff
            handlers[opcode]=addr
    assert handlers=={3:GOTO,35:MESSAGE,43:MESSAGE},handlers
    put=lambda addr,val:u.mem_write(addr,struct.pack('>I',val))
    get=lambda addr:int.from_bytes(u.mem_read(addr,4),'big')
    globals_blob=blobs['bin/globals.bin']
    globals_base=struct.unpack_from('<I',globals_blob,16)[0]+24
    u.mem_write(GLOBALS,globals_blob)
    put(0x80345b78+0xec,GLOBALS);put(0x80345b78+0xf8,GLOBALS+globals_base)
    put(0x80345878+0x150,STAGE)
    calls=[];sound_calls=0
    def trace(cpu,pc,size,data):
        nonlocal sound_calls
        if pc==0x80083fc0:
            calls.append((cpu.reg_read(p.regnum(4)),cpu.reg_read(p.regnum(5))))
            cpu.reg_write(p.reg.UC_PPC_REG_PC,cpu.reg_read(p.reg.UC_PPC_REG_LR))
        if pc==0x8001e8e8:
            sound_calls+=1;cpu.reg_write(p.reg.UC_PPC_REG_PC,cpu.reg_read(p.reg.UC_PPC_REG_LR))
    u.hook_add(UC_HOOK_CODE,trace)
    def invoke(addr,opcode):
        for reg,val in {1:p.STACK,3:THREAD,4:opcode,5:0}.items():u.reg_write(p.regnum(reg),val)
        u.reg_write(p.reg.UC_PPC_REG_LR,p.STOP);u.emu_start(addr,p.STOP,count=10000)
        assert u.reg_read(p.reg.UC_PPC_REG_PC)==p.STOP
        return u.reg_read(p.regnum(3))
    groups=defaultdict(list)
    for r in records:groups[r['file']].append(r)
    counts=Counter()
    for filename,rows in sorted(groups.items()):
        blob=blobs[filename]
        ram=GLOBALS if filename=='bin/globals.bin' else STAGE
        if ram==STAGE:
            assert len(blob)<GLOBALS-STAGE
            u.mem_write(STAGE,blob)
        for r in rows:
            entry=ram+r['original_entry'];new=ram+r['relocated_entry'];end=ram+r['relocated_resume'];resume=ram+r['original_resume']
            op=blob[r['relocated_entry']]
            u.mem_write(THREAD,b'\0'*0x80);put(THREAD+0x54,MSGOBJ)
            # Actual GOTO decoder distinguishes stage vs globals pointer bases.
            put(THREAD+4,entry+1);assert invoke(GOTO,3)==0 and get(THREAD+4)==new
            # Start: payload pointer sent to drawing, current opcode retried.
            put(MSGOBJ+0x43fa8,0);put(MSGOBJ+0x43f70,1);put(MSGOBJ+0x804,0)
            before=len(calls);put(THREAD+4,new+1)
            assert invoke(MESSAGE,op)==1 and get(THREAD+4)==new
            assert len(calls)==before+1 and calls[-1]==(op,new+5)
            # Still active: keep same opcode, do not enter return trampoline.
            put(MSGOBJ+0x804,1);put(THREAD+4,new+1)
            assert invoke(MESSAGE,op)==1 and get(THREAD+4)==new
            # Finished: follow the new message end pointer; retain select result.
            put(MSGOBJ+0x804,0);put(MSGOBJ+0x43f84,2);put(THREAD+4,new+1)
            assert invoke(MESSAGE,op)==0 and get(THREAD+4)==end
            if op==43:assert get(THREAD+0x10)==2
            put(THREAD+4,end+1);assert invoke(GOTO,3)==0 and get(THREAD+4)==resume
            counts[str(op)]+=1
    report={'handlers':{str(k):hex(v) for k,v in handlers.items()},'handler_table_setup_range':['0x800819c0','0x800820dc'],
        'tested_records':sum(counts.values()),'message_records':counts['35'],'selection_records':counts['43'],'drawing_calls_mocked':len(calls),'selection_sound_calls_mocked':sound_calls,
        'goto_and_return':True,'message_payload_pointer':True,'wait_retry_resume':True,'selection_result':True,'stage_and_globals_pointer_bases':True,
        'script_files':len(groups),'loaded_dol_sha256':p.sha(dol),'game_rendering_verified':False,'game_loader_memory_verified':False,'full_script_control_flow_verified':False,'new_iso_built':False,
        'limits':['Draw call and select sound mocked; no actual dialogue window or GX','Synthetic addresses and sequential cases do not validate game allocation or asynchronous callers','Metadata/DOL pointers and held scope still require separate preparation']}
    return report

def main():
    dol=p.DOL.read_bytes();inv=json.loads(p.INV.read_text());assert p.sha(dol)==inv['dol']['sha256']
    records=json.loads((ROOT/'work/relocation-experiment/records.json').read_text(encoding='utf-8'))
    blobs={name:(ROOT/'work/relocation-experiment'/name).read_bytes() for name in {r['file'] for r in records}}
    report=verify_cpu(dol,inv,blobs,records)
    report['original_dol_sha256']=p.sha(dol)
    (ROOT/'metadata/relocation_cpu_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
