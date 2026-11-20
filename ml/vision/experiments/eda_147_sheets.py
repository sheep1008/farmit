"""147 EDA 3단계: 작물별 확인 시트(질병 위 / 정상 아래, bbox를 빨간 상자로). 이미지는 zip에서 메모리로만 읽는다.
  .venv/Scripts/python.exe -I -X utf8 experiments/eda_147_sheets.py
출력: docs/vision/archive/vision-147-eda/sheet_<작물>.jpg, exif_check.txt
표본: 작물마다 질병 6장(클래스·대상ID를 번갈아) + 정상 6장(서로 다른 묶음), seed 고정.
"""
import csv, collections as C, io, os, random, zipfile
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = 'data/raw/147/노지 작물 질병 진단 이미지'
DOC = '../../docs/vision/archive/vision-147-eda'
T = 300; N = 6
random.seed(147)
R = list(csv.DictReader(open('data/review/147/labels.csv', encoding='utf-8')))
FONT = ImageFont.truetype('C:/Windows/Fonts/malgun.ttf', 13)
CROPS = ['고추', '무', '배추', '애호박', '양배추', '오이', '잎마름병(토마토)', '콩', '파', '호박']


def nm(i): return i.filename if i.flag_bits & 0x800 else i.filename.encode('cp437').decode('cp949')


def zips(split, crop, kind):
    pre = f'{ROOT}/{split}/'
    for f in sorted(os.listdir(pre)):
        if f.startswith('[원천]' + crop + '_') and (kind in f):
            yield pre + f


_idx = {}


def index(path):
    if path not in _idx:
        z = zipfile.ZipFile(path); _idx[path] = (z, {nm(i): i for i in z.infolist() if not i.is_dir()})
    return _idx[path]


def load(r):
    for p in zips(r['split'], r['zip_crop'], r['zip_kind']):
        z, m = index(p)
        for k in (r['image'],):
            # 원천 zip 안에는 하위 폴더가 있을 수 있어 파일명 끝으로 찾는다
            if k in m: return z.read(m[k])
        for name, info in m.items():
            if name.endswith('/' + r['image']) or name == r['image']: return z.read(info)
    return None


def pick(rows, n, key):
    by = C.defaultdict(list)
    for r in rows: by[key(r)].append(r)
    keys = sorted(by); random.shuffle(keys); out = []
    i = 0
    while len(out) < n and keys:
        k = keys[i % len(keys)]
        if by[k]: out.append(by[k].pop(random.randrange(len(by[k]))))
        i += 1
        if i > 10000: break
    return out


exif_log = []
for c in CROPS:
    sn = '토마토' if c.startswith('잎') else c
    dis = [r for r in R if r['zip_crop'] == c and r['zip_kind'] == '질병' and r['disease'] != '0']
    nor = [r for r in R if r['zip_crop'] == c and r['zip_kind'] == '정상']
    sel = [('질병', r) for r in pick(dis, N, lambda r: (r['disease'], r['gid']))] + [('정상', r) for r in pick(nor, N, lambda r: (r['gid'], r['fdate']))]
    sheet = Image.new('RGB', (N * T, 2 * (T + 34)), 'white'); d = ImageDraw.Draw(sheet)
    for j, (kd, r) in enumerate(sel):
        x, y = (j % N) * T, (j // N) * (T + 34)
        b = load(r)
        if b is None: d.text((x + 4, y + 4), '이미지 못 찾음', fill='red', font=FONT); continue
        im = Image.open(io.BytesIO(b)); raw = im.size
        exif_log.append((sn, r['image'], raw, (int(r['W']), int(r['H'])), im.getexif().get(0x0112)))
        im = ImageOps.exif_transpose(im).convert('RGB'); w, h = im.size
        # JSON 해상도가 0이거나 실제 크기와 다르면 실제 크기 기준으로 비율을 계산한다
        sx = sy = 1.0
        im.thumbnail((T, T)); s = im.size[0] / w
        dr = ImageDraw.Draw(im)
        dr.rectangle([int(r['xtl']) * s, int(r['ytl']) * s, int(r['xbr']) * s, int(r['ybr']) * s], outline='red', width=3)
        sheet.paste(im, (x, y + 34))
        d.text((x + 3, y + 1), f"{kd} {sn}-{r['disease']} 부위{r['area']} 위험{r['risk']}", fill='black', font=FONT)
        d.text((x + 3, y + 17), f"{r['date'] or '날짜없음'} {r['gid']} {'지역'+r['region'] if r['region'] else ''}", fill='black', font=FONT)
    sheet.save(f'{DOC}/sheet_{sn}.jpg', quality=82)
    print(sn, 'ok', flush=True)
with open(f'{DOC}/exif_check.txt', 'w', encoding='utf-8') as f:
    mism = [e for e in exif_log if e[2] != e[3] and e[2] != e[3][::-1]]
    swapped = [e for e in exif_log if e[2] != e[3] and e[2] == e[3][::-1]]
    f.write(f'표본 {len(exif_log)}장: raw 크기 == JSON W×H {sum(1 for e in exif_log if e[2]==e[3])}, 가로세로 뒤집힘 {len(swapped)}, 그 밖에 다름 {len(mism)}\n')
    f.write(f'EXIF orientation 값 분포: {dict(C.Counter(e[4] for e in exif_log))}\n')
    for e in mism + swapped: f.write(str(e) + '\n')
print(open(f'{DOC}/exif_check.txt', encoding='utf-8').read())
