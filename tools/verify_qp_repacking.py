"""In-memory U8 repacking experiments. No QP, DOL or ISO file is written.

Keep node/name order, physical file order and every original gap byte. Append
zero alignment bytes only where changed payload lengths require them.
"""
import copy,hashlib,json,struct
from collections import defaultdict
from pathlib import PurePosixPath
from inspect_discs import ROOT,save
from verify_roundtrip import model_table,encode_table

def sha(b):return hashlib.sha256(b).hexdigest()
def align(n):return (n+31)&~31

def parse(blob):
    magic,table,header,data=struct.unpack_from('>4I',blob)
    assert magic==0x55aa382d and table>=16 and table+header<=data<=len(blob)
    word,parent,count=struct.unpack_from('>III',blob,table)
    assert word>>24==1 and parent==0 and count>0 and count*12<=header
    names=blob[table+count*12:table+header];stack=[(count,'',0)];files=[]
    for i in range(1,count):
        while i>=stack[-1][0]:stack.pop()
        w,a,b=struct.unpack_from('>III',blob,table+12*i);kind=w>>24;n=w&0xffffff
        assert kind in (0,1) and n<len(names)
        name=names[n:names.index(0,n)].decode('cp932');assert name and name not in ('.','..') and '/' not in name and '\\' not in name
        path=stack[-1][1]+name
        if kind:
            assert a==stack[-1][2] and i<b<=stack[-1][0];stack.append((b,path+'/',i))
        else:
            assert a>=data and a%32==0 and a+b<=len(blob)
            files.append({'index':i,'path':path,'offset':a,'size':b,'sha256':sha(blob[a:a+b])})
    assert len({r['path'] for r in files})==len(files)
    end=data
    for r in sorted(files,key=lambda x:x['offset']):
        assert r['offset']>=end,'Overlapping/shared ranges require explicit support';end=r['offset']+r['size']
    return files

def repack(original,files,replacements):
    _,table,header,data=struct.unpack_from('>4I',original)
    model=model_table(original[table:table+header]);out=bytearray(original[:data]);cursor=data
    layout=[];padding_added=0
    for f in sorted(files,key=lambda x:x['offset']):
        # Opaque source gaps are retained, never assumed disposable zeroes.
        gap=original[cursor:f['offset']];out.extend(gap)
        n=align(len(out))-len(out);out.extend(bytes(n));padding_added+=n
        raw=replacements.get(f['path'],original[f['offset']:f['offset']+f['size']])
        at=len(out);out.extend(raw);node=model['entries'][f['index']]
        node['a']=at;node['b']=len(raw)
        layout.append({'path':f['path'],'old_offset':f['offset'],'new_offset':at,'old_size':f['size'],'new_size':len(raw),
                       'sha256':sha(raw),'changed_payload':raw!=original[f['offset']:f['offset']+f['size']]})
        cursor=f['offset']+f['size']
    out.extend(original[cursor:]);out[table:table+header]=encode_table(model)
    # Only file offset/size fields in header may change; names/directories stay.
    restored=bytearray(out[:data])
    for f in files:
        at=table+f['index']*12+4;restored[at:at+8]=original[at:at+8]
    assert restored==original[:data]
    return out,layout,padding_added

def verify(original,files,replacements,blob,layout):
    reread=parse(blob);assert [x['path'] for x in reread]==[x['path'] for x in files]
    expected={x['path']:x for x in layout}
    for r in reread:
        e=expected[r['path']];assert (r['offset'],r['size'],r['sha256'])==(e['new_offset'],e['new_size'],e['sha256'])
        raw=replacements.get(r['path'])
        if raw is not None:assert bytes(blob[r['offset']:r['offset']+r['size']])==raw
        else:
            old=next(f for f in files if f['path']==r['path'])
            assert r['sha256']==old['sha256']
    # Check opaque gaps independently from the serializer, including added zeros.
    _,_,_,data=struct.unpack_from('>4I',original);old_end=new_end=data
    for old in sorted(files,key=lambda r:r['offset']):
        now=expected[old['path']];gap=original[old_end:old['offset']]
        assert blob[new_end:new_end+len(gap)]==gap
        assert not any(blob[new_end+len(gap):now['new_offset']])
        old_end=old['offset']+old['size'];new_end=now['new_offset']+now['new_size']
    assert blob[new_end:]==original[old_end:]
    return reread

def main():
    disc=json.loads((ROOT/'metadata/disc_inventory_jp.json').read_text('utf-8'))
    entry=next(r for r in disc['files'] if r['path']=='qp.bin')
    source=ROOT/'work/roundtrip/jp/qp/qp.rebuilt.bin';original=source.read_bytes();assert sha(original)==entry['sha256']
    files=parse(original);known=json.loads((ROOT/'metadata/qp_inventory_jp.json').read_text('utf-8'))['files'];assert files==[{k:r[k] for k in files[0]} for r in known]
    scripts={}
    for r in json.loads((ROOT/'metadata/relocation_experiment.json').read_text('utf-8'))['files']:
        raw=(ROOT/'work/relocation-experiment'/r['file']).read_bytes();assert sha(raw)==r['experiment_sha256'];scripts[r['file']]=raw
    text=dict(scripts);meta=json.loads((ROOT/'metadata/metadata_relocation_verification.json').read_text('utf-8'))
    data=(ROOT/'work/metadata-relocation/globals.bin').read_bytes();assert sha(data)==meta['experiment_sha256'];text['bin/globals.bin']=data
    # Approved/reused, quality-checked PNG encodings only. Pending small logo and
    # all CMPR quality holds are intentionally excluded from this packing view.
    project=json.loads((ROOT/'project.json').read_text('utf-8'))
    obs={r['pixel_sha256']:f"G{r['sheet_index']:04}" for r in json.loads((ROOT/'metadata/graphics_visual_observations.json').read_text('utf-8'))['groups']}
    allowed={obs[s['pixel_sha256']] for s in project['graphics_selection'] if s['selection']=='translate_japanese'
             and ((s.get('composite_review',{}).get('approval') and s['composite_review'].get('encoding_verified'))
                  or s.get('reuse',{}).get('encoding_verified'))}
    allowed-=set(project['graphics_work_rules'].get('format_exceptions',{}))
    enc=json.loads((ROOT/'metadata/graphics_encoding_verification.json').read_text('utf-8'))
    cat={r['id']:r for r in json.loads((ROOT/'metadata/graphics_catalog_jp.json').read_text('utf-8'))['images']};gfx={};groups=set()
    for r in enc['textures']:
        if r['code'] not in allowed:continue
        asset=cat[r['texture']];name=asset['file'];assert name!='opening.bnr' and not name.startswith('pc.bin/')
        if name not in gfx:
            f=next(f for f in files if f['path']==name);gfx[name]=bytearray(original[f['offset']:f['offset']+f['size']])
        raw=(ROOT/r['encoded']).read_bytes();assert sha(raw)==r['encoded_sha256'] and len(raw)==asset['data_size']
        at=asset['data_offset'];gfx[name][at:at+len(raw)]=raw;groups.add(r['code'])
    gfx={k:bytes(v) for k,v in gfx.items()};assert not (text.keys()&gfx.keys())
    variants=[('unchanged',{}),('messages',scripts),('messages_metadata',text),('graphics',gfx),('combined',{**text,**gfx})]
    formats=None
    if (ROOT/'metadata/approved_texture_formats.json').exists():
        formats=json.loads((ROOT/'metadata/approved_texture_formats.json').read_text('utf-8'))
        assert project['checks']['cmpr_format_review']['user_format_approval']==formats['format_approval']
        raw=(ROOT/formats['candidate_path']).read_bytes();assert sha(raw)==formats['candidate_sha256']
        # The separate baseline gfx view must never reuse old CMPR bytes for the
        # newly approved format exceptions.
        assert 'tpl/misc.tpl' not in gfx
        rgba={**gfx,'tpl/misc.tpl':raw}
        variants.extend([('graphics_rgba8_four_experiment',rgba),('combined_rgba8_four_experiment',{**text,**rgba})])
    results=[];out=ROOT/'work/qp-repacking';out.mkdir(parents=True,exist_ok=True)
    for name,replacements in variants:
        blob,layout,padding=repack(original,files,replacements);read=verify(original,files,replacements,blob,layout)
        if not replacements:assert blob==original
        save(out/f'{name}-layout.json',layout)
        results.append({'variant':name,'files_reread':len(read),'bytes':len(blob),'growth':len(blob)-len(original),'sha256':sha(blob),
            'changed_payload_files':[x['path'] for x in layout if x['changed_payload']],
            'relocated_files':sum(x['old_offset']!=x['new_offset'] for x in layout),'extra_zero_alignment_bytes':padding,
            'node_name_and_physical_file_order_preserved':True,'all_source_gap_bytes_preserved':True,'all_unselected_payloads_byte_exact':True,
            'byte_exact_noop':blob==original if not replacements else None,'layout':f'work/qp-repacking/{name}-layout.json'})
        print(name,len(read),'files,',len(blob)-len(original),'growth bytes',flush=True)
    # Independent parser rejects corrupt output range, alignment and overlap.
    table=struct.unpack_from('>I',original,4)[0];negative=0
    for field,value in [(4,align(len(blob))+32),(4,files[0]['offset']+1),(8,len(blob)),(4,files[0]['offset'])]:
        bad=bytearray(blob);idx=files[1]['index'];struct.pack_into('>I',bad,table+idx*12+field,value)
        try:parse(bad)
        except (AssertionError,ValueError,IndexError,struct.error):negative+=1
        else:raise AssertionError('Malformed archive accepted')
    corrupt_payloads=0
    for changed in (True,False):
        f=next(x for x in layout if x['changed_payload']==changed and x['new_size']>0)
        bad=bytearray(blob);bad[f['new_offset']]^=1
        try:verify(original,files,replacements,bad,layout)
        except AssertionError:corrupt_payloads+=1
        else:raise AssertionError('Corrupt payload accepted')
    assert sha(source.read_bytes())==entry['sha256']
    save(ROOT/'metadata/qp_repacking_verification.json',{'source_sha256':entry['sha256'],'variants':results,'graphics_groups_included':sorted(groups),
        'rgba8_format_groups_in_added_variants':[r['code'] for r in formats['textures']] if formats else [],
        'rgba8_png_approval_pending':formats['png_confirmation_pending'] if formats else [],
        'malformed_archive_cases_rejected':negative,'corrupt_payload_cases_rejected':corrupt_payloads,'archives_written':False,'new_iso_built':False,'deployable':False,
        'limits':['Translated script/metadata holds remain experimental, not approved for release',
                  'Entire QP serialized and reread only in memory; game load/heap/streaming untested',
                  'Disc FST placement and whole-ISO changes are separate build work',
                  'Compression/internal formats are unchanged opaque bytes except verified replacement payloads']})

if __name__=='__main__':main()
