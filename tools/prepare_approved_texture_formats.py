"""Apply explicitly approved RGBA8 exceptions to an isolated TPL candidate.

Original game data/PNGs are read-only. No archive or ISO is built. PNG approval
and the technical format exception are recorded separately.
"""
import json,struct
import numpy as np
from PIL import Image
from inspect_discs import ROOT,save
from prepare_rgba8_comparison import encode_rgba8
from decode_gx import decode,size
from verify_graphics_encoding import sha

def main():
    project=json.loads((ROOT/'project.json').read_text('utf-8'));decision=project['checks']['cmpr_format_review']
    assert decision['user_format_approval'] and decision['approved_groups']==['G0200','G0225','G0226','G0235']
    proposal=json.loads((ROOT/'metadata/rgba8_format_proposal.json').read_text('utf-8'))
    source=ROOT/'work/roundtrip/jp/qp/files/tpl/misc.tpl';original=source.read_bytes();assert sha(original)==proposal['source_sha256']
    catalog={r['id']:r for r in json.loads((ROOT/'metadata/graphics_catalog_jp.json').read_text('utf-8'))['images']}
    assets={s['pixel_sha256']:s for s in project['graphics_selection']}
    out=ROOT/'work/graphics-format-candidate';view=bytearray(original);allowed=np.zeros(len(original),bool);records=[]
    for row in proposal['textures']:
        code=row['code'];assert project['graphics_work_rules']['format_exceptions'][code]==6
        r=catalog[row['texture']];c=assets[r['pixel_sha256']]['composite_review']
        assert c['sha256']==row['candidate_sha256'] and sha((ROOT/c['path']).read_bytes())==c['sha256']
        image=Image.open(ROOT/c['path']).convert('RGBA');data=encode_rgba8(image)
        assert sha(data)==row['data_sha256'];start=(len(view)+31)&~31;view.extend(bytes(start-len(view)));view.extend(data)
        assert start==row['append_offset'];at=r['descriptor_offset'];struct.pack_into('>II',view,at+4,6,start);allowed[at+4:at+12]=True
        mask=np.array(Image.open(ROOT/c['mask']).convert('L'))>0;original_png=np.array(Image.open(ROOT/r['png']).convert('RGBA'))
        decoded=decode(data,*image.size,6);assert np.array_equal(np.array(decoded),np.array(image))
        assert np.array_equal(np.array(decoded)[~mask],original_png[~mask])
        out.mkdir(parents=True,exist_ok=True);decoded.save(out/f'{code}.png')
        records.append({'code':code,'texture':row['texture'],'candidate_path':c['path'],'candidate_sha256':c['sha256'],
            'old_format':14,'new_format':6,'data_offset':start,'data_size':len(data),'data_sha256':sha(data),'descriptor_offset':at,
            'png_exact':True,'outside_edit_mask_changed_pixels':0,'png_approval':c.get('approval'),'format_approval':decision['user_format_approval'],
            'preview':f'work/graphics-format-candidate/{code}.png','runtime_verified':False})
    assert np.array_equal(np.frombuffer(original,np.uint8)[~allowed],np.frombuffer(view[:len(original)],np.uint8)[~allowed])
    # Serialize only the review candidate; reopen it and every TPL texture entry.
    target=out/'tpl/misc.tpl';target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(view);reread=target.read_bytes();assert reread==view
    _,count,table=struct.unpack_from('>III',reread);modified={x['descriptor_offset']:x for x in records}
    for i in range(count):
        desc,pal=struct.unpack_from('>II',reread,table+i*8);h,w,fmt,offset=struct.unpack_from('>HHII',reread,desc)
        if desc in modified:
            r=modified[desc];assert fmt==6 and pal==0 and offset==r['data_offset']
            data=reread[offset:offset+size(w,h,fmt)];assert sha(data)==r['data_sha256']
            assert np.array_equal(np.array(decode(data,w,h,fmt)),np.array(Image.open(ROOT/r['candidate_path']).convert('RGBA')))
        else:
            assert reread[desc:desc+36]==original[desc:desc+36]
            assert reread[offset:offset+size(w,h,fmt)]==original[offset:offset+size(w,h,fmt)]
    save(ROOT/'metadata/approved_texture_formats.json',{'source_sha256':sha(original),'candidate_path':'work/graphics-format-candidate/tpl/misc.tpl',
        'candidate_sha256':sha(reread),'candidate_bytes':len(reread),'growth_bytes':len(reread)-len(original),'textures':records,
        'all_tpl_descriptors_reread':count,'original_data_and_unselected_fields_preserved':True,
        'format_approval':decision['user_format_approval'],'png_confirmation_pending':[r['code'] for r in records if not r['png_approval']],
        'applied_to_isolated_candidate':True,'original_game_data_changed':False,'new_iso_built':False,'runtime_verified':False})
    assert source.read_bytes()==original
    print('Applied 4 approved RGBA8 exceptions to isolated TPL candidate; 244 entries reread; PNG-exact; source unchanged.')

if __name__=='__main__':main()
