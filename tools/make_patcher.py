"""Build the GameCube file-unit patcher zip (patcher/ + data/ + bin/).

The Korean build overwrites five places of the original image (see
build_integrated_test.write_iso): header 0x420, the qp.bin FST entry, the
moved DOL, the moved qp.bin and opening.bnr in place.  So the patcher copies
the original image and writes xdelta-patched DOL, qp.bin, opening.bnr and FST.

Usage: python -X utf8 tools/make_patcher.py BUILD.iso VERSION
"""
import hashlib, shutil, struct, subprocess, sys, tempfile, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORIG = ROOT / 'Chibi-Robo! (Japan) (Rev 1).iso'
BIN = ROOT / 'tools/bin'
XDELTA = (BIN / 'xdelta3.exe').resolve()
CODE, TITLE, RESULT = 'GGTJ', '치비로보!', 'Chibi-Robo (Korean) [GGTJ01]'


def md5(b): return hashlib.md5(b).hexdigest()


def at(f, off, n): f.seek(off); b = f.read(n); assert len(b) == n; return b


def dol_size(dol): # end of the furthest text/data section
    offs = struct.unpack('>18I', dol[:72]); sizes = struct.unpack('>18I', dol[0x90:0xd8])
    return max(o + s for o, s in zip(offs, sizes) if s)


def fst_files(fst):
    n = struct.unpack_from('>I', fst, 8)[0]; strs = n * 12; out = {}
    def name(o): return fst[strs + o:fst.index(b'\0', strs + o)].decode('cp932')
    def walk(i, stop, pre):
        while i < stop:
            flag = fst[i * 12]; no = int.from_bytes(fst[i * 12 + 1:i * 12 + 4], 'big')
            a, b = struct.unpack_from('>II', fst, i * 12 + 4)
            if flag: walk(i + 1, b, pre + name(no) + '/'); i = b
            else: out[pre + name(no)] = (a, b); i += 1
    walk(1, n, ''); return out


def image(path):
    with open(path, 'rb') as f:
        head = at(f, 0, 0x440); doff, fo, fsz = struct.unpack_from('>3I', head, 0x420)
        fst = at(f, fo, fsz); files = fst_files(fst)
        dol = at(f, doff, 0x100); dol = at(f, doff, dol_size(dol))
        blobs = {name: at(f, *files[name]) for name in ('qp.bin', 'opening.bnr')}
    return head, fo, fst, files, doff, dol, blobs


def main():
    build, version = Path(sys.argv[1]), sys.argv[2]
    oh, ofo, ofst, ofiles, odoff, odol, oblobs = image(ORIG)
    nh, nfo, nfst, nfiles, ndoff, ndol, nblobs = image(build)
    assert oh[:0x420] == nh[:0x420] and ofo == nfo and len(ofst) == len(nfst)
    assert set(ofiles) == set(nfiles)
    # only qp.bin moved; every other file keeps its place
    assert all(ofiles[k] == nfiles[k] for k in ofiles if k != 'qp.bin')
    name = f'{CODE}_KPatch_v{version}'
    out = ROOT / 'release' / name
    if out.exists(): shutil.rmtree(out)
    (out / 'data').mkdir(parents=True); (out / 'bin').mkdir()
    rows = [('dol', 'main.dol', odol, ndol, ndoff), ('raw', 'qp.bin', oblobs['qp.bin'], nblobs['qp.bin'], nfiles['qp.bin'][0]),
            ('raw', 'opening.bnr', oblobs['opening.bnr'], nblobs['opening.bnr'], nfiles['opening.bnr'][0]),
            ('fst', 'fst.bin', ofst, nfst, nfo)]
    manifest = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, (mode, rel, a, b, pos) in enumerate(rows):
            src, dst, patch = Path(tmp, 'a'), Path(tmp, 'b'), out / 'data' / f'{i:03d}.xdelta'
            src.write_bytes(a); dst.write_bytes(b)
            subprocess.run([str(XDELTA), '-e', '-9', '-S', 'djw', '-A=', '-B', '268435456', '-f', '-s', str(src), str(dst), str(patch)], check=True)
            manifest.append('\t'.join([mode, patch.name, rel, md5(a), md5(b), str(pos)]))
    h = hashlib.md5()
    with open(build, 'rb') as f:
        while chunk := f.read(1 << 24): h.update(chunk)
    config = {'id': 'GGTJ01', 'rev': str(oh[7]), 'title': TITLE, 'version': version, 'result': RESULT,
              'disc_size': str(ORIG.stat().st_size), 'fst_md5': md5(ofst), 'dol_size': str(len(odol)),
              'hdr420': nh[0x420:0x430].hex(), 'result_md5': h.hexdigest()}
    (out / 'data/config.txt').write_text(''.join(f'{k}={v}\n' for k, v in config.items()), encoding='utf-8')
    (out / 'data/manifest.txt').write_text('\n'.join(manifest) + '\n', encoding='utf-8')
    ps1 = (ROOT / 'patcher/patch.ps1').read_text(encoding='utf-8').replace('\r\n', '\n').replace('\n', '\r\n')
    (out / 'patch.ps1').write_bytes(b'\xef\xbb\xbf' + ps1.encode('utf-8'))
    shutil.copy(ROOT / 'patcher/패치하기.bat', out / '패치하기.bat')
    shutil.copy(ROOT / 'patcher/README.txt', out / 'README.txt')
    for f in BIN.iterdir(): shutil.copy(f, out / 'bin' / f.name)
    zpath = out.parent / (out.name + '.zip')
    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.rglob('*')):
            if f.is_file(): z.write(f, f.relative_to(out.parent).as_posix())
    print(zpath, zpath.stat().st_size, config['result_md5'])
    for m in manifest: print(m)


if __name__ == '__main__':
    main()
