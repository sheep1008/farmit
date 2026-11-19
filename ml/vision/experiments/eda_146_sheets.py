"""146 EDA 3단계: 표본 이미지 시트 + EXIF/bbox 좌표 조사. 이미지는 zip에서 메모리로만 읽는다 (풀지 않음).
  .venv/Scripts/python.exe -I -X utf8 experiments/eda_146_sheets.py
출력(이미지가 들어 있으므로 docs가 아니라 data/review/146/ 에만 쓴다):
  data/review/146/sheet_<작물>.jpg   클래스(질병)·부위(정상)별 8장, 빨간 상자 = JSON bbox (EXIF 회전 뒤)
  data/review/146/exif_check.jpg     bbox가 W,H를 바꿔야 들어가는 표본: 위 = 회전 전, 아래 = 회전 뒤
표(텍스트)는 docs/vision-146-eda/exif_survey.md 에 쓴다.
"""
import collections as C, csv, io, os, random, re, zipfile

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = 'data/raw/146/과수화상병 촬영 이미지'
REV = 'data/review/146'
DOC = '../../docs/vision-146-eda'
LAB = f'{REV}/labels.csv'
THUMB = 170


def zname(i):
    return i.filename if i.flag_bits & 0x800 else i.filename.encode('cp437').decode('cp949')


def index_images():
    idx = {}
    for split in ('Training', 'Validation'):
        for f in sorted(os.listdir(f'{ROOT}/{split}')):
            if not f.startswith('[원천]'): continue
            for info in zipfile.ZipFile(f'{ROOT}/{split}/{f}').infolist():
                if not info.is_dir(): idx[os.path.basename(zname(info))] = (f'{ROOT}/{split}/{f}', info.filename)
    return idx


_Z = {}


def read(idx, name):
    zp, m = idx[name]; z = _Z.get(zp) or _Z.setdefault(zp, zipfile.ZipFile(zp))
    return Image.open(io.BytesIO(z.read(m)))


def spread(rows, n, rng):
    """묶음(대상ID)을 돌아가며 n장."""
    g = C.defaultdict(list)
    for r in rows: g[r['gid']].append(r)
    for v in g.values(): rng.shuffle(v)
    keys = sorted(g); rng.shuffle(keys); out = []
    while len(out) < n and any(g.values()):
        for k in keys:
            if g[k] and len(out) < n: out.append(g[k].pop())
    return out


def main():
    rng = random.Random(3)
    R = list(csv.DictReader(open(LAB, encoding='utf-8')))
    for r in R:
        for k in ('W', 'H', 'xtl', 'ytl', 'xbr', 'ybr'): r[k] = int(r[k])
    idx = index_images()
    font = ImageFont.truetype('C:/Windows/Fonts/malgun.ttf', 13)
    ok = [r for r in R if str(r['disease']) == str(int(r['fdis'])) and r['image'] in idx]

    # ---- 1. EXIF 조사: 무작위 표본 + bbox가 swap인 행 전부
    surv = C.Counter(); detail = []
    pool = []
    for kind in ('정상', '질병'):
        for crop in ('배', '사과'):
            rs = [r for r in ok if r['zip_kind'] == kind and r['zip_crop'] == crop]; pool += rng.sample(rs, min(150, len(rs)))
    swap = [r for r in R if r['image'] in idx and not (r['xbr'] <= r['W'] * 1.01 and r['ybr'] <= r['H'] * 1.01) and r['xbr'] <= r['H'] * 1.01 and r['ybr'] <= r['W'] * 1.01]
    seen = set()
    for tag, rows in (('무작위', pool), ('bbox swap 후보', swap)):
        for r in rows:
            if (tag, r['image']) in seen: continue
            seen.add((tag, r['image']))
            try:
                im = read(idx, r['image']); w, h = im.size; o = im.getexif().get(274, 1)
            except Exception as e:  # noqa: BLE001
                surv[(tag, '읽기 실패')] += 1; continue
            fw, fh = (h, w) if o in (5, 6, 7, 8) else (w, h)
            raw_match = (w, h) == (r['W'], r['H']); rot_match = (fw, fh) == (r['W'], r['H'])
            fit_rot = r['xbr'] <= fw * 1.01 and r['ybr'] <= fh * 1.01
            fit_raw = r['xbr'] <= w * 1.01 and r['ybr'] <= h * 1.01
            surv[(tag, r['zip_kind'], f'EXIF {o}', 'JSON=원본크기' if raw_match else 'JSON=회전뒤크기' if rot_match else 'JSON≠이미지', 'bbox 회전뒤 안' if fit_rot else '회전뒤 밖', 'bbox 원본 안' if fit_raw else '원본 밖')] += 1
    L = ['# 146 EXIF·bbox 좌표 조사 (이미지 헤더 표본)', '', '표본: 구분×작물 150장 무작위(600) + bbox가 JSON 해상도에 안 들어가고 W,H를 바꾸면 들어가는 행 %d개 전부.' % len(swap), '',
         '| 표본 | 구분 | EXIF | JSON W,H가 가리키는 것 | bbox가 회전 뒤 크기 안 | bbox가 원본 크기 안 | 장수 |', '|---|---|---|---|---|---|---:|']
    for k, v in sorted(surv.items()): L.append('| ' + ' | '.join(str(x) for x in k) + f' | {v} |')
    open(f'{DOC}/exif_survey.md', 'w', encoding='utf-8').write('\n'.join(L) + '\n'); print('\n'.join(L))

    # ---- 2. EXIF 확인 시트
    os.makedirs(REV, exist_ok=True)
    pick = rng.sample(swap, min(6, len(swap)))
    sheet = Image.new('RGB', (len(pick) * 260, 2 * 270), 'white'); d = ImageDraw.Draw(sheet)
    for ci, r in enumerate(pick):
        im = read(idx, r['image']).convert('RGB'); o = read(idx, r['image']).getexif().get(274, 1)
        for ri, img in enumerate((im, ImageOps.exif_transpose(im))):
            t = img.copy(); t.thumbnail((250, 250)); k = t.width / img.width; dd = ImageDraw.Draw(t)
            dd.rectangle([r['xtl'] * k, r['ytl'] * k, r['xbr'] * k, r['ybr'] * k], outline=(255, 0, 0), width=3)
            sheet.paste(t, (ci * 260, ri * 270 + 14))
        d.text((ci * 260 + 2, 0), f'EXIF {o} {r["zip_crop"]} {r["zip_kind"]}', fill=(0, 0, 0), font=font)
    sheet.save(f'{REV}/exif_check.jpg', quality=85)

    # ---- 3. 작물별 시트
    for crop in ('배', '사과'):
        groups = []
        for d_ in sorted({r['disease'] for r in ok if r['zip_crop'] == crop and r['zip_kind'] == '질병'}, key=int):
            rs = [r for r in ok if r['zip_crop'] == crop and r['zip_kind'] == '질병' and r['disease'] == d_]
            if len(rs) > 300: groups.append((f'{crop} 질병 {d_} ({len(rs)}장)', spread(rs, 8, rng)))
        for a in ('01', '03', '04', '05'):
            rs = [r for r in ok if r['zip_crop'] == crop and r['zip_kind'] == '정상' and r['farea'] == a]
            if len(rs) > 300: groups.append((f'{crop} 정상 부위{a} ({len(rs)}장)', spread(rs, 8, rng)))
        H = 20 + THUMB; sheet = Image.new('RGB', (8 * THUMB, len(groups) * H), 'white'); d = ImageDraw.Draw(sheet)
        for ri, (title, rs) in enumerate(groups):
            d.text((4, ri * H + 2), title, fill=(0, 0, 0), font=font)
            for ci, r in enumerate(rs):
                im = ImageOps.exif_transpose(read(idx, r['image']).convert('RGB')); k = THUMB / max(im.size)
                t = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k)))); dd = ImageDraw.Draw(t)
                dd.rectangle([r['xtl'] * k, r['ytl'] * k, r['xbr'] * k, r['ybr'] * k], outline=(255, 0, 0), width=2)
                sheet.paste(t, (ci * THUMB, ri * H + 20))
        sheet.save(f'{REV}/sheet_{crop}.jpg', quality=85); print('시트', crop, len(groups), '줄')


if __name__ == '__main__':
    main()
