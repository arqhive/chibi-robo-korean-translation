"""Check source cache provenance, coverage, native PNG dimensions, and safe merge."""
import hashlib,json,tempfile
from collections import Counter
from pathlib import Path
from PIL import Image
from inspect_discs import ROOT,save
from extract_text_catalog import merge

def sha(b):return hashlib.sha256(b).hexdigest()
def main():
    results=[];aux=[]
    for edition in ('jp','us'):
        base=ROOT/f'work/roundtrip/{edition}';qp=json.loads((ROOT/f'metadata/qp_inventory_{edition}.json').read_text())
        for f in qp['files']:
            b=(base/'qp/files'/f['path']).read_bytes()
            assert len(b)==f['size'] and sha(b)==f['sha256'],f['path']
        parts=json.loads((base/'parts.json').read_text());disc=json.loads((ROOT/f'metadata/disc_inventory_{edition}.json').read_text());byname={r['name']:r for r in parts}
        assert sha((base/'main.dol').read_bytes())==disc['dol']['sha256']
        assert (base/byname['tmp/cbr.dol']['disk_file']).read_bytes()==(base/'main.dol').read_bytes()
        b=(base/byname['opening.bnr']['disk_file']).read_bytes();encoding='cp932' if edition=='jp' else 'cp1252'
        assert sha(b)==next(f['sha256'] for f in disc['files'] if f['path']=='opening.bnr')
        names=[];at=0x1820
        for label,n in [('short_title',32),('short_maker',32),('long_title',64),('long_maker',64),('comment',128)]:
            field=b[at:at+n];names.append(dict(field=label,offset=at,size=n,source=field.split(b'\0')[0].decode(encoding),raw_hex=field.hex()));at+=n
        aux.append(dict(edition=edition,banner_fields=names,banner_encoding=encoding,duplicate_dol='tmp/cbr.dol byte-identical to main.dol',
            disc_file_types=dict(Counter(Path(f['path']).suffix for f in disc['files'])),
            audio_files=[dict(file=f['path'],size=f['size'],sha256=f['sha256']) for f in disc['files'] if Path(f['path']).suffix in ('.ssm','.hps','.sem')],
            other=dict(file='tmp/cbr.ddf',description='Read as a development disc/configuration description; not a rendered message catalog.')))
        graphics=json.loads((ROOT/f'metadata/graphics_catalog_{edition}.json').read_text());unique={r['pixel_sha256']:r for r in graphics['images'] if r['decoded']}
        for digest,r in unique.items():
            im=Image.open(ROOT/r['png']).convert('RGBA');assert im.size==(r['width'],r['height'])
            import struct
            assert sha(struct.pack('>II',*im.size)+im.tobytes())==digest
        assert not graphics['errors']
        counts=Counter(c['kind'] for c in graphics['containers'])
        top_dat=sum(f['path'].endswith('.dat') for f in qp['files'])
        nested=next(c['entries'] for c in graphics['containers'] if c['kind']=='pc_index')
        assert counts['hsd']==top_dat+nested
        results.append(dict(edition=edition,qp_source_files_hash_verified=len(qp['files']),hsd_archives_surveyed=counts['hsd'],native_unique_pngs_hash_verified=len(unique),
            limits='Decoding candidates correctly does not certify that every HSD candidate is a real texture, or establish complete runtime usage.'))
    # The re-extractor must not reset translation/speaker/window/notes or silently
    # drop an existing record. Use isolated metadata fixtures, never real catalogs.
    with tempfile.TemporaryDirectory(prefix='chibi-catalog-check-') as d:
        p=Path(d)/'catalog.json';old=[dict(id='a',source='原文',translation='번역',translation_format='inline_source_token_refs_v1',speaker='화자',window='창',notes='수작업')]
        save(p,old);merge(p,[dict(id='a',source='原文',translation=None,speaker=None,window=None)])
        now=json.loads(p.read_text());assert all(now[0][k]==old[0][k] for k in ('translation','translation_format','speaker','window','notes'))
        for invalid in ([dict(id='a',source='다른 원문')],[]):
            try:merge(p,invalid)
            except (AssertionError,ValueError):pass
            else:raise AssertionError('Unsafe catalog replacement allowed')
    save(ROOT/'metadata/disc_auxiliary_inventory.json',dict(editions=aux))
    save(ROOT/'metadata/extraction_verification.json',dict(editions=results,catalog_preservation_fixture='passed',new_iso_built=False))
    print(json.dumps(results,ensure_ascii=False))

if __name__=='__main__':main()
