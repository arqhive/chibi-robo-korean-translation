"""Review-only RGBA8 alternative to CMPR. Does not apply a format change."""
import json,struct
import numpy as np
from PIL import Image,ImageDraw
from inspect_discs import ROOT,save
from decode_gx import decode,size
from verify_graphics_encoding import sha
import prepare_output_probe as p

def encode_rgba8(image):
    a=np.array(image.convert('RGBA'));h,w=a.shape[:2];out=bytearray()
    for y in range(0,h,4):
        for x in range(0,w,4):
            tile=np.zeros((4,4,4),np.uint8);sample=a[y:y+4,x:x+4];tile[:sample.shape[0],:sample.shape[1]]=sample
            tile=tile.reshape(16,4);out.extend(tile[:,[3,0]].tobytes());out.extend(tile[:,[1,2]].tobytes())
    assert len(out)==size(w,h,6) and np.array_equal(np.array(decode(out,w,h,6)),a)
    return bytes(out)

def main():
    project=json.loads((ROOT/'project.json').read_text('utf-8'));encoding=json.loads((ROOT/'metadata/graphics_encoding_verification.json').read_text('utf-8'))
    cat=json.loads((ROOT/'metadata/graphics_catalog_jp.json').read_text('utf-8'))['images'];byid={r['id']:r for r in cat}
    selected=[r for r in encoding['textures'] if r['format']==14]
    path=ROOT/'work/roundtrip/jp/qp/files/tpl/misc.tpl';original=path.read_bytes();view=bytearray(original);allowed=np.zeros(len(original),bool)
    known=next(r for r in json.loads((ROOT/'metadata/qp_inventory_jp.json').read_text('utf-8'))['files'] if r['path']=='tpl/misc.tpl')
    assert sha(original)==known['sha256'];out=ROOT/'work/rgba8-comparison';out.mkdir(parents=True,exist_ok=True);rows=[]
    for old in selected:
        source=byid[old['texture']];assert source['file']=='tpl/misc.tpl' and source['kind']=='tpl'
        a=next(s for s in project['graphics_selection'] if s['pixel_sha256']==source['pixel_sha256'])['composite_review']
        assert a['sha256']==old['candidate_sha256'] and sha((ROOT/a['path']).read_bytes())==a['sha256']
        image=Image.open(ROOT/a['path']).convert('RGBA');data=encode_rgba8(image);decoded=decode(data,*image.size,6)
        mask=np.array(Image.open(ROOT/a['mask']).convert('L'))>0;source_png=np.array(Image.open(ROOT/source['png']).convert('RGBA'))
        assert np.array_equal(source_png[~mask],np.array(decoded)[~mask])
        offset=(len(view)+31)&~31;view.extend(bytes(offset-len(view)));view.extend(data)
        descriptor=source['descriptor_offset'];struct.pack_into('>II',view,descriptor+4,6,offset);allowed[descriptor+4:descriptor+12]=True
        code=old['code'];decoded.save(out/f'{code}.png');(out/f'{code}.rgba8').write_bytes(data)
        rows.append({'code':code,'texture':source['id'],'candidate_sha256':a['sha256'],'width':image.width,'height':image.height,
            'old_format':14,'proposed_format':6,'old_texture_bytes':source['data_size'],'proposed_texture_bytes':len(data),
            'png_exact':True,'outside_edit_mask_changed_pixels':0,'alpha_changed_from_candidate':0,
            'append_offset':offset,'descriptor_offset':descriptor,'data_sha256':sha(data),
            'preview':f'work/rgba8-comparison/{code}.png','data':f'work/rgba8-comparison/{code}.rgba8'})
    assert np.array_equal(np.frombuffer(original,np.uint8)[~allowed],np.frombuffer(view[:len(original)],np.uint8)[~allowed])
    # Re-read every TPL descriptor, not just proposed entries.
    magic,count,table=struct.unpack_from('>III',view);assert magic==0x20af30
    modified={r['descriptor_offset']:r for r in rows}
    for i in range(count):
        desc,pal=struct.unpack_from('>II',view,table+8*i)
        h,w,fmt,off=struct.unpack_from('>HHII',view,desc)
        if desc in modified:
            assert pal==0 and fmt==6
            r=modified[desc];assert (w,h,off)==(r['width'],r['height'],r['append_offset'])
            assert np.array_equal(np.array(decode(view[off:off+size(w,h,fmt)],w,h,fmt)),np.array(Image.open(ROOT/r['preview']).convert('RGBA')))
        else:
            assert view[desc:desc+36]==original[desc:desc+36]
            assert view[off:off+size(w,h,fmt)]==original[off:off+size(w,h,fmt)]
    sheet=Image.new('RGB',(1500,len(rows)*350),'#555555');draw=ImageDraw.Draw(sheet)
    for i,r in enumerate(rows):
        old=next(x for x in selected if x['code']==r['code']);draw.text((5,i*350),r['code']+' PNG | CMPR previous | CMPR refined | RGBA8 proposal (x6)',fill='white')
        for x,preview_path in [(0,old['candidate_path']),(375,old['preview']),(750,f"work/cmpr-refinement/{r['code']}.png"),(1125,r['preview'])]:
            im=Image.open(ROOT/preview_path).convert('RGBA');im=im.resize((im.width*6,im.height*6),Image.Resampling.NEAREST);sheet.paste(im,(x+5,i*350+24),im)
    sheet.save(out/'comparison.png')
    # Actual JP GXInitTexObj handles both formats. Exercise its normal memset
    # and switch table; this does not exercise the game's TPL loader or GPU.
    dol=p.DOL.read_bytes();inv=json.loads(p.INV.read_text('utf-8'));assert sha(dol)==inv['dol']['sha256']
    cpu=p.create_cpu(dol,inv,p.yay0(p.ROMFONT.read_bytes()));obj=0x81930000;pixels=0x81000000;cpu_cases=[]
    for r in rows:
        for fmt in [14,6]:
            for reg,value in {1:p.STACK,2:0x8063e160,3:obj,4:pixels,5:r['width'],6:r['height'],7:fmt,8:0,9:0,10:0}.items():cpu.reg_write(p.regnum(reg),value)
            cpu.mem_write(obj,b'\xa5'*32);cpu.reg_write(p.reg.UC_PPC_REG_LR,p.STOP)
            cpu.emu_start(0x8018ae98,p.STOP,count=10000);assert cpu.reg_read(p.reg.UC_PPC_REG_PC)==p.STOP
            got=bytes(cpu.mem_read(obj,32));image0=struct.unpack_from('>I',got,8)[0]
            assert image0&1023==r['width']-1 and (image0>>10)&1023==r['height']-1 and (image0>>20)&15==fmt
            assert struct.unpack_from('>I',got,20)[0]==fmt
            assert struct.unpack_from('>I',got,12)[0]&0x1fffff==(pixels>>5)&0x1fffff
            block=8 if fmt==14 else 4;assert struct.unpack_from('>H',got,28)[0]==((r['width']+block-1)//block)*((r['height']+block-1)//block)
            cpu_cases.append({'code':r['code'],'format':fmt,'texobj_hex':got.hex()})
    save(ROOT/'metadata/rgba8_format_proposal.json',{'source_sha256':sha(original),'textures':rows,'original_tpl_bytes':len(original),
        'proposed_tpl_bytes':len(view),'append_growth_bytes':len(view)-len(original),'tpl_descriptors_reread':count,
        'changed_original_fields':'Only format and data pointer of four descriptors in memory; all original image bytes retained',
        'gx_init_texobj_cpu_cases':cpu_cases,'gx_init_texobj_address':'0x8018ae98',
        'approval_source':'project.json graphics_work_rules.format_exceptions','container_written':False,'new_iso_built':False,'runtime_verified':False,
        'limits':['This report is a comparison; current approval/application state is in project.json',
                  'RGBA8 encode/decode and TPL structure only; this game renderer/loading not executed',
                  'G0200 draft PNG itself still awaits user confirmation']})
    assert sha(path.read_bytes())==known['sha256']
    print('RGBA8 proposal: four PNG-exact textures,',len(view)-len(original),'bytes TPL growth;',count,'descriptors checked. Comparison only; application state is in project.json.')

if __name__=='__main__':main()
