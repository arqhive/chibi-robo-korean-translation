"""Rebuild karaoke_teriyaki.thp with the Korean frames (work/karaoke/ko_frames).

Every original frame carries the same baseline JPEG header: one DQT with both
tables, SOF0 4:2:0, one DHT with DC0, DC1, AC0, AC1, SOS; no APP0, and the scan
data is NOT byte-stuffed (FF stays FF). The original Huffman tables only hold
the symbols the original pictures needed, so each Korean frame gets standard
tables optimised per frame by Pillow (same quantisation tables as the original), regrouped into
the original segment layout and unstuffed. Audio chunks are copied as they are.
Frame layout: 16-byte header (next frame size, previous frame size, image size,
audio size), image padded to 4, frame padded to 32. The first frame's
"previous" is the last frame's size and the last frame's "next" the first's.

Usage: python -X utf8 tools/karaoke_thp.py
"""
import hashlib, io, struct
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
K = ROOT / 'work/karaoke'
SRC, DST = K / 'karaoke_teriyaki.thp', K / 'karaoke_teriyaki_ko.thp'


def segments(b, stop=0xda):
    i, out = 2, []
    while True:
        m = b[i + 1]; L = struct.unpack_from('>H', b, i + 2)[0]; out.append((m, b[i + 4:i + 2 + L])); i += 2 + L
        if m == stop: return out, i


def seg(marker, body): return bytes([0xff, marker]) + struct.pack('>H', len(body) + 2) + body


def original_frames(d):
    fo, size, out = 96, struct.unpack_from('>I', d, 0x18)[0], []
    for _ in range(struct.unpack_from('>I', d, 0x14)[0]):
        nxt, prev, isz, asz = struct.unpack_from('>IIII', d, fo)
        out.append((d[fo + 16:fo + 16 + isz], d[fo + 16 + isz:fo + 16 + isz + asz])); fo += size; size = nxt
    return out


def qtables(jpeg):
    segs, _ = segments(jpeg); body = next(b for m, b in segs if m == 0xdb); tabs = {}; j = 0
    while j < len(body): tabs[body[j] & 15] = list(body[j + 1:j + 65]); j += 65
    return tabs


def encode(img, q):
    buf = io.BytesIO(); img.save(buf, 'JPEG', qtables=[q[0], q[1]], subsampling='4:2:0', optimize=True)
    j = buf.getvalue(); segs, start = segments(j)
    dqt = b''.join(b for m, b in segs if m == 0xdb)
    dht = {b[0]: b for m, b in segs if m == 0xc4 for _ in [0]}
    # Pillow writes one table per DHT segment; regroup in the original order
    tables = []
    for m, b in segs:
        if m != 0xc4: continue
        k = 0
        while k < len(b):
            n = sum(b[k + 1:k + 17]); tables.append(b[k:k + 17 + n]); k += 17 + n
    order = {t[0]: t for t in tables}
    dht = b''.join(order[c] for c in (0x00, 0x01, 0x10, 0x11))
    sof = next(b for m, b in segs if m == 0xc0); sos = next(b for m, b in segs if m == 0xda)
    end = j.rindex(b'\xff\xd9'); scan = j[start:end].replace(b'\xff\x00', b'\xff')
    out = b'\xff\xd8' + seg(0xdb, dqt) + seg(0xc0, sof) + seg(0xc4, dht) + seg(0xda, sos) + scan + b'\xff\xd9'
    return out + bytes(-len(out) % 4)


def main():
    d = SRC.read_bytes(); frames = original_frames(d); q = qtables(frames[0][0])
    head = d[:0x30]; comp = d[0x30:96]
    # the original header must match what Pillow emits for these tables, apart from DHT contents
    osegs, _ = segments(frames[0][0])
    assert [m for m, _ in osegs] == [0xdb, 0xc0, 0xc4, 0xda]
    images = [encode(Image.open(K / 'ko_frames' / f'f{i + 1:04d}.png').convert('RGB'), q) for i in range(len(frames))]
    sizes = [(16 + len(im) + len(au) + 31) & ~31 for im, (_, au) in zip(images, frames)]
    body = bytearray()
    for k, (im, (_, au)) in enumerate(zip(images, frames)):
        nxt = sizes[(k + 1) % len(sizes)]; prev = sizes[k - 1]
        fr = struct.pack('>IIII', nxt, prev, len(im), len(au)) + im + au
        body += fr + bytes(sizes[k] - len(fr))
    hdr = bytearray(head)
    struct.pack_into('>I', hdr, 0x08, max(sizes))           # maxBufferSize
    struct.pack_into('>I', hdr, 0x18, sizes[0])             # firstFrameSize
    struct.pack_into('>I', hdr, 0x1c, len(body))            # dataSize
    struct.pack_into('>I', hdr, 0x2c, 96 + sum(sizes[:-1])) # lastFrameOffset
    out = bytes(hdr) + comp + bytes(body)
    DST.write_bytes(out)
    print(DST, len(out), 'max frame', max(sizes), 'orig max', struct.unpack_from('>I', d, 8)[0], 'md5', hashlib.md5(out).hexdigest())


if __name__ == '__main__':
    main()
