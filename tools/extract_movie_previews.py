"""Read THP frame chains and decode sampled PNG previews; never re-encode video."""
import json,struct,subprocess,hashlib
from pathlib import Path
from PIL import Image,ImageDraw
import imageio_ffmpeg
from inspect_discs import ROOT,save

def main():
    ffmpeg=imageio_ffmpeg.get_ffmpeg_exe();records=[]
    for edition in ('jp','us'):
        base=ROOT/f'work/roundtrip/{edition}';parts=json.loads((base/'parts.json').read_text())
        for p in parts:
            if not p['name'].endswith('.thp'):continue
            source=base/p['disk_file'];b=source.read_bytes();assert b[:4]==b'THP\x00'
            version,maxbuf,maxsamples,fps,frames,firstsize,datasize,components,offsets,first,last=struct.unpack_from('>IIIfIIIIIII',b,4)
            n=struct.unpack_from('>I',b,components)[0];types=b[components+4:components+4+n];desc=components+20
            assert types[0]==0;w,h,video_type=struct.unpack_from('>III',b,desc)
            at=first;sz=firstsize;chain=[]
            for i in range(frames):
                assert at+sz<=len(b)
                nxt,prev=struct.unpack_from('>II',b,at);sizes=struct.unpack_from(f'>{n}I',b,at+8)
                assert 8+4*n+sum(sizes)<=sz
                chain.append(dict(frame=i,offset=at,size=sz,component_sizes=sizes))
                at+=sz;sz=nxt
            assert chain[-1]['offset']==last and at==first+datasize
            out=ROOT/f'work/extraction/{edition}/movies'/Path(p['name']).stem;out.mkdir(parents=True,exist_ok=True)
            # Select original frames at 2-second intervals, no scale/fps blending.
            step=round(fps*2)
            command=[ffmpeg,'-hide_banner','-loglevel','error','-y','-i',str(source),'-vf',f'select=not(mod(n\\,{step}))','-fps_mode','vfr',str(out/'frame-%04d.png')]
            result=subprocess.run(command,capture_output=True,text=True)
            assert result.returncode==0,result.stderr
            images=sorted(out.glob('frame-*.png'))
            for start in range(0,len(images),20):
                page=Image.new('RGB',(1000,900),(50,50,50));draw=ImageDraw.Draw(page)
                for j,f in enumerate(images[start:start+20]):
                    im=Image.open(f);assert im.size==(w,h);im.thumbnail((246,154));x=j%4*250;y=j//4*180
                    page.paste(im,(x,y));draw.text((x+3,y+157),f'{(start+j)*step/fps:.2f}s',fill='white')
                page.save(out/f'sheet-{start//20:02}.jpg',quality=90)
            save(out/'frame_index.json',chain)
            records.append(dict(edition=edition,file=p['name'],sha256=hashlib.sha256(b).hexdigest(),version=hex(version),frames=frames,fps=fps,width=w,height=h,
                component_types=list(types),frame_chain_verified=True,sampled_previews=len(images),sample_step_frames=step,preview_directory=out.relative_to(ROOT).as_posix(),
                text_coverage='sampled_only_not_all_frames_reviewed'))
            print(edition,p['name'],frames,'frames;',len(images),'samples',flush=True)
    save(ROOT/'metadata/movie_extraction.json',dict(movies=records,decoder=ffmpeg,limits='All frame boundaries validated. PNGs are sampled original frames every approximately 2 seconds, not exhaustive video text identification.'))

if __name__=='__main__':main()
