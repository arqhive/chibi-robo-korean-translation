"""Read-only stage4 extraction. PNGs retain native dimensions; no game edits.

HSD descriptors are relocation-backed structural candidates, not a scene graph
proof. Keep that distinction in the catalog, including missing palette links.
"""
from collections import Counter,defaultdict
import hashlib,json,math,struct
from pathlib import Path
from PIL import Image,ImageDraw
from inspect_discs import ROOT,save
from decode_gx import decode,size,BLOCKS,palette_rgba,self_test

def sha(b):return hashlib.sha256(b).hexdigest()
def u32(b,o):return struct.unpack_from('>I',b,o)[0]

def scalar_relocations(at,relocations):
    """ImageDesc has one pointer, then 20 bytes of scalar fields."""
    return [offset for offset in (4,8,12,16,20) if at+offset in relocations]

class Extractor:
    def __init__(self,edition):
        self.edition=edition;self.base=ROOT/f'work/roundtrip/{edition}/qp/files'
        self.out=ROOT/f'work/extraction/{edition}/graphics';self.out.mkdir(parents=True,exist_ok=True)
        self.rows=[];self.containers=[];self.errors=[]
    def image(self,path,key,b,off,w,h,fmt,palette=None,**extra):
        n=size(w,h,fmt);raw=b[off:off+n]
        row=dict(id=f'{path}#{key}',file=path,key=key,width=w,height=h,format=fmt,data_offset=off,data_size=n,raw_sha256=sha(raw),**extra)
        try:
            assert len(raw)==n
            im=decode(raw,w,h,fmt,palette)
            digest=sha(struct.pack('>II',w,h)+im.tobytes());png=self.out/(digest+'.png')
            if not png.exists():im.save(png)
            row.update(pixel_sha256=digest,png=str(png.relative_to(ROOT)).replace('\\','/'),decoded=True)
        except (ValueError,IndexError,AssertionError) as e:row.update(decoded=False,error=str(e))
        self.rows.append(row)
    def tpl(self,path,b):
        magic,n,table=struct.unpack_from('>III',b);assert magic==0x20af30
        for i in range(n):
            at,pal=struct.unpack_from('>II',b,table+8*i);h,w,fmt,off=struct.unpack_from('>HHII',b,at)
            palette=None;info={}
            if pal:
                count=struct.unpack_from('>H',b,pal)[0];pf,po=struct.unpack_from('>II',b,pal+4)
                palette=palette_rgba(b[po:po+count*2],pf);info=dict(palette_offset=po,palette_count=count,palette_format=pf)
            self.image(path,f'tpl-{i:03}',b,off,w,h,fmt,palette,kind='tpl',descriptor_offset=at,confidence='table_entry',**info)
    def hsd(self,path,b,archive_offset=0):
        total,rel,nrel,nroot,nref=struct.unpack_from('>5I',b)
        assert total==len(b) and 32+rel+4*nrel+8*(nroot+nref)<=len(b)
        assert b[20:24] in (bytes(4),b'001B')
        d=b[32:32+rel];rs=set(struct.unpack_from(f'>{nrel}I',b,32+rel))
        assert all(0<=r<=len(d)-4 for r in rs)
        refs=defaultdict(list)
        for r in rs:refs[u32(d,r)].append(r)
        found=0
        for at in sorted(refs):
            if at%4 or at not in rs or at+24>len(d):continue
            off,w,h,fmt,mip,lo,hi=struct.unpack_from('>IHHIIff',d,at)
            if fmt not in BLOCKS or not (1<=w<=1024 and 1<=h<=1024) or mip not in (0,1):continue
            if not (math.isfinite(lo) and math.isfinite(hi) and 0<=lo<=hi<=10):continue
            n=size(w,h,fmt)
            if off%32 or off+n>len(d):continue
            invalid=scalar_relocations(at,rs)
            # Referencing TObj image field is +0x4c, palette immediately after it.
            palette=None;info={};parents=[]
            for ref in refs[at]:
                parent=ref-0x4c
                if parent<0 or ref+8>len(d):continue
                if u32(d,parent+8)>7 or u32(d,parent+0x34)>2 or u32(d,parent+0x38)>2:continue
                parents.append(parent+32)
                if fmt in (8,9,10) and ref+4 in rs:
                    pal=u32(d,ref+4)
                    if pal in rs and pal+16<=len(d):
                        po,pf,_,count=struct.unpack_from('>IIIH',d,pal)
                        if pf<=2 and po+count*2<=len(d):
                            palette=palette_rgba(d[po:po+count*2],pf);info=dict(palette_offset=po+32,palette_format=pf,palette_count=count)
            self.image(path,f'hsd-{at+32:08x}',b,off+32,w,h,fmt,palette,kind='hsd',descriptor_offset=at+32,archive_offset=archive_offset,
                confidence='rejected_scalar_pointer_conflict' if invalid else 'relocation_descriptor_candidate',
                descriptor_valid=not invalid,nonpointer_field_relocations=invalid,
                parent_tobj_candidates=parents,mipmap=mip,min_lod=lo,max_lod=hi,**info)
            # Retain rejected diagnostic rows/IDs so existing visual reviews stay
            # reproducible. They are explicitly not translation texture assets.
            if invalid:continue
            # Mip levels are part of the same asset, not new translation pictures.
            if mip:
                cursor=off+n;mw,mh=w,h
                for level in range(1,int(hi)+1):
                    mw=max(1,mw//2);mh=max(1,mh//2);ln=size(mw,mh,fmt)
                    if cursor+ln>len(d):self.errors.append(dict(file=path,error='mipmap out of bounds',descriptor=at));break
                    self.image(path,f'hsd-{at+32:08x}-mip{level}',b,cursor+32,mw,mh,fmt,palette,kind='hsd_mip',parent=f'{path}#hsd-{at+32:08x}',confidence='descriptor_mip_chain')
                    cursor+=ln
            found+=1
        self.containers.append(dict(file=path,kind='hsd',size=len(b),sha256=sha(b),archive_offset=archive_offset,relocations=nrel,image_descriptor_candidates=found))
    def particle(self,path,b):
        n=u32(b,0);groups=struct.unpack_from(f'>{n}I',b,4)
        for g,at in enumerate(groups):
            count,fmt,unknown,w,h,unknown2=struct.unpack_from('>6I',b,at)
            assert fmt in BLOCKS and count<10000
            for i in range(count):
                off=u32(b,at+24+4*i)
                self.image(path,f'group{g}-frame{i:03}',b,off,w,h,fmt,kind='particle',group=g,frame=i,confidence='inferred_txg_table',unknown_fields=[unknown,unknown2])
        self.containers.append(dict(file=path,kind='particle_txg',groups=n,sha256=sha(b)))
    def run(self):
        for p in sorted(self.base.rglob('*')):
            if p.suffix not in ('.tpl','.dat','.txg'):continue
            path=p.relative_to(self.base).as_posix();b=p.read_bytes()
            try:
                if p.suffix=='.tpl':self.tpl(path,b)
                elif p.suffix=='.dat':self.hsd(path,b)
                else:self.particle(path,b)
            except (AssertionError,ValueError,struct.error) as e:self.errors.append(dict(file=path,error=repr(e)))
        # pc.idx offsets use a shared base. Verify every entry against pc.bin.
        b=(self.base/'pc.bin').read_bytes();idx=(self.base/'pc.idx').read_bytes()
        assert idx[-4:]==b'\xff'*4 and (len(idx)-4)%8==0
        entries=list(struct.iter_unpack('<II',idx[:-4]));base=min(o for o,n in entries)
        spans=sorted((o-base,n) for o,n in entries);cursor=0
        for i,(off,n) in enumerate(spans):
            assert off==cursor and off+n<=len(b)
            self.hsd(f'pc.bin/entry-{i:03}',b[off:off+n],off)
            cursor=(off+n+31)&~31
        assert cursor==len(b)
        self.containers.append(dict(file='pc.bin',kind='pc_index',entries=len(entries),index_base=base,complete_span_verified=True,sha256=sha(b)))
        parts=json.loads((ROOT/f'work/roundtrip/{self.edition}/parts.json').read_text())
        for part in parts:
            if part['name']=='opening.bnr':
                b=(ROOT/f'work/roundtrip/{self.edition}'/part['disk_file']).read_bytes()
                assert b[:4]==b'BNR1'
                self.image('opening.bnr','banner',b,32,96,32,5,kind='banner',confidence='bnr1_header')
        save(ROOT/f'metadata/graphics_catalog_{self.edition}.json',dict(edition=self.edition,images=self.rows,containers=self.containers,errors=self.errors,
            limits=['HSD relocation descriptors are candidates; complete scene/animation graph not traversed.','Particle tables inferred from bounded offsets, formats and exact frame sizes.','Pixel decode is not translated re-encoding or runtime validation.']))
        summary=dict(edition=self.edition,images=len(self.rows),decoded=sum(r['decoded'] for r in self.rows),unique_pixels=len({r.get('pixel_sha256') for r in self.rows if r['decoded']}),
            kinds=dict(Counter(r['kind'] for r in self.rows)),errors=self.errors,missing_palettes=[r['id'] for r in self.rows if not r['decoded']])
        print(json.dumps(summary,ensure_ascii=False))
        return summary

def sheets(edition):
    catalog=json.loads((ROOT/f'metadata/graphics_catalog_{edition}.json').read_text());groups=defaultdict(list)
    for r in catalog['images']:
        if r['decoded'] and r['kind']!='hsd_mip':groups[r['pixel_sha256']].append(r)
    rows=sorted(groups.values(),key=lambda g:(0 if g[0]['kind'] in ('tpl','banner','particle') else 1,g[0]['file'],g[0]['key']))
    out=ROOT/f'work/extraction/{edition}/sheets';out.mkdir(parents=True,exist_ok=True);index=[]
    for start in range(0,len(rows),48):
        page=Image.new('RGB',(1200,1120),(70,70,70));draw=ImageDraw.Draw(page)
        for j,g in enumerate(rows[start:start+48]):
            r=g[0];im=Image.open(ROOT/r['png']).convert('RGBA');im.thumbnail((192,105))
            x=(j%6)*200;y=(j//6)*140
            page.paste(im,(x+(196-im.width)//2,y),im)
            label=f'{start+j:04} {r["width"]}x{r["height"]} x{len(g)}'
            draw.text((x+3,y+106),label,fill='white');draw.text((x+3,y+121),r['file'][-27:],fill='white')
            index.append(dict(index=start+j,ids=[t['id'] for t in g],png=r['png'],page=f'{start//48:03}.jpg'))
        page.save(out/f'{start//48:03}.jpg',quality=90)
    save(out/'index.json',index)

if __name__=='__main__':
    self_test();results=[]
    for edition in ('jp','us'):
        results.append(Extractor(edition).run());sheets(edition)
    save(ROOT/'metadata/graphics_extraction_summary.json',dict(editions=results))
