"""Karaoke movie (qp/movie/karaoke_teriyaki.thp): redraw every frame in Korean.

The movie is lyrics on black only; the game draws it over the stage. It opens
with the title (frames 8-214), then five pages of two lines that turn from
white to green as they are sung, and fades out. The original green edge per
frame is measured (measure.json) and mapped word group by word group onto the
Korean line, so the Korean lyric fills on the same beat. Fades copy the
original brightness curve.

Usage: python -X utf8 tools/karaoke_render.py [measure|render]
"""
import json, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageChops

ROOT = Path(__file__).resolve().parents[1]
K = ROOT / 'work/karaoke'
FRAMES, OUT = K / 'frames', K / 'ko_frames'
N, W, H, S = 2343, 480, 240, 4
WHITE, GREEN = (245, 245, 245), (92, 176, 66)
LYRIC_FONT, LYRIC_SIZE = ROOT / 'work/fonts/ChungjuKimSaeng.ttf', 34
TITLE_FONT, TITLE_SIZE, TITLE_STROKE = Path('C:/Windows/Fonts/batang.ttc'), 40, 1
TITLE, TITLE_FRAMES, TITLE_BOX = 'TERIYAKI 블루스', (8, 214), (55, 21, 425, 58)
# (first, last frame, line 1, line 2). '|' separates the groups that follow one
# original word each; spaces inside a group are ordinary word spaces.
PAGES = [(485, 753, '스키야키|후지야마', '게이샤|덴푸라'),
         (754, 951, '마루야키|아오야마', '닌자|노브라'),
         (952, 1293, '둘러대도|속여도', '듣고 싶지 않아'),
         (1294, 1512, '당신은|수줍고', '나는|샘나고'),
         (1513, 1942, '숨긴 사랑은|초밥 소스', '데리야키 블루스야')]
ROWS = {'L1': (110, 166), 'L2': (166, 216)}
LINE_Y = {'L1': 139, 'L2': 192}
GROUP_GAP = 22


def frame_rgb(i): return np.asarray(Image.open(FRAMES / f'f{i:04d}.png').convert('RGB')).astype(int)


def green_edge(a, rows):
    g = (a[:, :, 1] > a[:, :, 0] + 40) & (a[:, :, 1] > 60)
    xs = np.where(g[rows[0]:rows[1]].any(0))[0]
    return int(xs.max()) if len(xs) else None


def word_spans(a, rows, min_gap=12):
    cols = np.where((a[rows[0]:rows[1]].max(2) > 60).any(0))[0]
    spans, s, prev = [], cols[0], cols[0]
    for x in cols[1:]:
        if x - prev > min_gap: spans.append((int(s), int(prev))); s = x
        prev = x
    spans.append((int(s), int(prev))); return spans


def measure():
    """Per frame: brightness and green edge per line; per page: original word spans."""
    rec = {'frames': {}, 'pages': []}
    for i in range(1, N + 1):
        a = frame_rgb(i); rec['frames'][i] = {'max': int(a.max()), **{l: green_edge(a, r) for l, r in ROWS.items()}}
    for first, last, l1, l2 in PAGES:
        full = frame_rgb(min(last, 1900) - 2)
        rec['pages'].append({l: word_spans(full, r) for l, r in ROWS.items()})
    json.dump(rec, open(K / 'measure.json', 'w'))
    for p, (pg, sp) in enumerate(zip(PAGES, rec['pages'])):
        print(p, {l: len(s) for l, s in sp.items()}, [len(pg[2].split('|')), len(pg[3].split('|'))])


def layout(text, font, x_left=None, x_right=None):
    groups = text.split('|'); widths = [font.getlength(g) for g in groups]
    total = sum(widths) + GROUP_GAP * S * (len(groups) - 1)
    x = x_left * S if x_left is not None else x_right * S - total; out = []
    for g, w in zip(groups, widths): out.append((g, x, x + w)); x += w + GROUP_GAP * S
    return out


def map_edge(edge, jp, kr):
    """Original green edge x -> Korean edge x (supersampled), group by group."""
    if edge is None: return None
    if len(jp) != len(kr):          # one Korean span over the whole original line
        jp = [(jp[0][0], jp[-1][1])]; kr = [('', kr[0][1], kr[-1][2])]
    for (a, b), (_, ka, kb) in zip(jp, kr):
        if edge < a: return ka
        if edge <= b:
            if edge >= b - 1: return kb + 4 * S   # group finished: cover the last stroke's overhang
            return ka + (kb - ka) * (edge - a + 1) / (b - a + 1)
    return kr[-1][2] + S


# Brightness follows the original only inside its fade windows. Elsewhere the
# brightest pixel drops from white to green as a line fills, which is not a fade.
FADES = [(1, 56, 60), (166, 216, 160),            # title in / out
         (480, 513, 512), (1889, 1953, 1884)]       # lyrics in / out; (first, end, reference frame at full brightness)


def fade(i, m):
    for a, b, ref in FADES:
        if a <= i < b: return min(1.0, m['frames'][str(i)]['max'] / m['frames'][str(ref)]['max'])
    return 1.0


def render():
    m = json.load(open(K / 'measure.json')); OUT.mkdir(exist_ok=True)
    font = ImageFont.truetype(str(LYRIC_FONT), LYRIC_SIZE * S)
    tfont = ImageFont.truetype(str(TITLE_FONT), TITLE_SIZE * S, index=0)
    reached = {}   # green edge never goes back within a page (the fade dims it below the threshold)
    for i in range(1, N + 1):
        f = m['frames'][str(i)]; img = Image.new('RGB', (W * S, H * S), 0)
        if TITLE_FRAMES[0] <= i <= TITLE_FRAMES[1]:
            d = ImageDraw.Draw(img); cx = (TITLE_BOX[0] + TITLE_BOX[2]) / 2 * S; cy = (TITLE_BOX[1] + TITLE_BOX[3]) / 2 * S
            d.text((cx, cy), TITLE, font=tfont, fill=WHITE, anchor='mm', stroke_width=TITLE_STROKE * S, stroke_fill=WHITE)
            img = img.resize((W, H), Image.LANCZOS); alpha = fade(i, m)
        else:
            page = next((p for p, pg in enumerate(PAGES) if pg[0] <= i <= pg[1]), None)
            if page is None:
                Image.new('RGB', (W, H), 0).save(OUT / f'f{i:04d}.png'); continue
            first, last, l1, l2 = PAGES[page]
            mask = Image.new('L', img.size, 0); d = ImageDraw.Draw(mask)
            lay = {'L1': layout(l1, font, x_left=24), 'L2': layout(l2, font, x_right=455)}
            for l, groups in lay.items():
                for g, a, b in groups: d.text((a, LINE_Y[l] * S), g, font=font, fill=255, anchor='lm')
            gm = Image.new('L', img.size, 0); gd = ImageDraw.Draw(gm)
            for l, groups in sorted(lay.items(), reverse=True):
                e = f[l]; prev = reached.get((page, l))
                if prev is not None and (e is None or e < prev): e = prev
                reached[(page, l)] = e
                x = map_edge(e, m['pages'][page][l], groups)
                if l == 'L1' and reached.get((page, 'L2')) is not None: x = groups[-1][2] + 4 * S   # line 2 started: line 1 is done
                if x: gd.rectangle((0, ROWS[l][0] * S, x, ROWS[l][1] * S), fill=255)
            g = ImageChops.multiply(mask, gm); w = ImageChops.subtract(mask, g)
            img.paste(Image.new('RGB', img.size, WHITE), mask=w); img.paste(Image.new('RGB', img.size, GREEN), mask=g)
            img = img.resize((W, H), Image.LANCZOS); alpha = fade(i, m)
        if alpha < 0.999: img = Image.eval(img, lambda v, a=alpha: int(v * a + 0.5))
        img.save(OUT / f'f{i:04d}.png')
    print('rendered', N)


if __name__ == '__main__':
    {'measure': measure, 'render': render}[sys.argv[1]]()
