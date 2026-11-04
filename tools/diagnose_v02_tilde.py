"""Read-only investigation of the overline in the user's subtitle screenshots."""
import json
import struct
import prepare_output_probe as p
from inspect_discs import ROOT, save
from build_output_probe import sections


def read(name):return json.loads((ROOT/name).read_text('utf-8'))


def main():
    build=read('metadata/integrated_test_build_v02.json')
    with (ROOT/build['iso']['path']).open('rb') as f:
        f.seek(0x420);offset=struct.unpack('>I',f.read(4))[0]
        f.seek(offset);dol=f.read(build['dol']['bytes'])
    assert p.sha(dol)==build['dol']['sha256']
    u=p.create_cpu(dol,{'dol':{'sections':sections(dol)}},p.yay0(p.ROMFONT.read_bytes()))
    glyphs=[]
    for char in ['~','～','￣',' ']:
        raw=char.encode('cp932')
        u.mem_write(p.STRING,raw+b'\0');u.mem_write(p.DEST,bytes(2048));u.mem_write(p.WIDTH,bytes(4))
        for r,v in {1:p.STACK,3:p.STRING,4:p.DEST,5:0,6:6,7:p.WIDTH}.items():u.reg_write(p.regnum(r),v)
        u.reg_write(p.reg.UC_PPC_REG_LR,p.STOP)
        # Execute the actual installed v02 hook, including its original-font fallback.
        u.emu_start(0x8064c5c0,p.STOP,count=100000)
        assert u.reg_read(p.reg.UC_PPC_REG_PC)==p.STOP
        consumed=u.reg_read(p.regnum(3))-p.STRING;assert consumed==len(raw)
        data=bytes(u.mem_read(p.DEST,288));im=p.unpack_i4(data)
        rows=[sum(im.getpixel((x,y))>0 for x in range(24)) for y in range(24)]
        glyphs.append({'character':char,'encoded':raw.hex(),'consumed':consumed,
            'advance':int.from_bytes(u.mem_read(p.WIDTH,4),'big'),'bbox':im.getbbox(),
            'nonzero_pixels_per_row':rows,'glyph_sha256':p.sha(data)})
    assert glyphs[0]['bbox']==(0,1,9,3),glyphs[0]
    assert glyphs[1]['bbox'][1]>=10 and glyphs[3]['bbox'] is None
    catalog=read('translation/text_catalog.json')
    ids=['bin/stage14.bin@000092bd','bin/stage14.bin@00009551']
    matched=[{k:r[k] for k in ['id','source','translation']} for r in catalog if r['id'] in ids]
    assert len(matched)==2 and all('~' in x['translation'] for x in matched)
    scope=read('metadata/build_scope_proposal.json')['record_ids_by_bucket']
    selected=set(scope['script_test_candidate']+scope['metadata_test_candidate']+scope['ui_test_candidate_runtime_unverified'])
    affected=[r for r in catalog if '~' in (r.get('translation') or '')]
    save(ROOT/'metadata/v02_tilde_diagnosis.json',{
        'build_sha256':build['iso']['sha256'],'font_reference_sha256':p.sha(p.ROMFONT.read_bytes()),
        'matched_subtitles':matched,'glyph_cpu_checks':glyphs,
        'all_draft_affected_records':len(affected),'v02_affected_records':sum(r['id'] in selected for r in affected),
        'v02_tilde_occurrences':sum(r['translation'].count('~') for r in affected if r['id'] in selected),
        'affected_ids':[r['id'] for r in affected if r['id'] in selected],
        'cause':'ASCII 0x7e goes through the original Japanese ROM-font fallback, yielding an overline at rows 1-2 (advance 8px) rather than a tilde. Space is blank.',
        'correction_proposal':'Provide an explicit tilde glyph for ASCII 0x7e in the font hook; preserve text/control bytes and one-byte consumption. Revalidate advance width and cache hit/miss.',
        'correction_applied':False,'new_iso_built':False,'runtime_fix_verified':False,
        'limits':['CPU used the installed Dolphin replacement ROM font, not hardware IPL data',
                  'Screenshot appearance matched to two unique translated subtitle strings; GPU correction remains untested']})
    print('PASS: ~ is an overline at rows 1-2 (advance 8px); space is blank; fullwidth wave is a distinct glyph.')


if __name__=='__main__':main()
