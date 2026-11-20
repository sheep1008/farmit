"""153 시설 작물 질병 전처리 (docs/vision/archive/vision.md 5장 규격). 원본 zip을 풀지 않고 바로 읽는다.

  python -X utf8 preprocess.py --raw "data/raw/153/071.시설 작물 질병 진단/01.데이터" --out data/processed/153 \
      [--crops 고추,토마토] [--review data/review/153] [--workers 12]

단계
  1. 라벨 zip(Training+Validation)의 JSON을 모두 읽는다. 증강본(`_a000N`)·코드표에 없는 (작물, 질병) 조합·bbox 없는 것은 버린다.
     같은 이미지가 양쪽에 있으면 한 번만 센다 (AI Hub 분할은 쓰지 않는다).
  2. 부위: 작물마다 그 작물 질병 사진에서 5% 이상인 촬영 부위만 쓴다. 정상도 같은 부위만, 질병의 부위 비율에 맞춰 뽑는다.
  3. 정상: 작물마다 질병 합계의 2배까지. (장소, 날짜) 묶음마다 같은 몫으로, 묶음 안에서는 프레임 번호를 간격 두고 뽑는다.
  4. 분할: 질병은 대상ID, 정상은 (장소, 날짜) 묶음 단위로 8/1/1. 클래스마다 시험 묶음이 최소 1개. 3개 미만 클래스는 summary.md에 적는다.
  5. 자르기: EXIF 회전 적용 후 bbox를 사방 25% 넓혀(이미지 밖은 자름) 긴 변 512px, JPEG 90.
     배경 교체 증강용으로 **저장한 이미지 안의 bbox(잎) 위치**를 manifest의 bx0,by0,bx1,by1(픽셀)에 같이 적는다.
  6. 결과: <out>/<작물>_<질병코드>/<원본파일명>.jpg, manifest.csv, summary.md, 확인 시트(--review)
"""
import argparse, collections, csv, glob, io, json, os, random, re, sys, time, zipfile
from concurrent.futures import ProcessPoolExecutor

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

CROP_NAME = {1: '가지', 2: '고추', 3: '단호박', 4: '딸기', 5: '상추', 6: '수박', 7: '애호박', 8: '오이', 9: '쥬키니호박', 10: '참외', 11: '토마토', 12: '포도'}
CROP_DIR = {c: f'{c:02d}.{n}' for c, n in CROP_NAME.items()}
DISEASE_NAME = {0: '정상', 1: '가지잎곰팡이병', 2: '가지흰가루병', 3: '고추마일드모틀바이러스병', 4: '고추점무늬병', 5: '단호박점무늬병', 6: '단호박흰가루병',
                7: '딸기잿빛곰팡이병', 8: '딸기흰가루병', 9: '상추균핵병', 10: '상추노균병', 11: '수박탄저병', 12: '수박흰가루병', 13: '애호박점무늬병',
                14: '오이녹반모자이크바이러스(쥬키니호박)', 15: '오이바이러스병(CMV/CGMMV 미정)', 16: '참외노균병', 17: '참외흰가루병',
                18: '토마토잎곰팡이병', 19: '토마토황화잎말이바이러스병', 20: '포도노균병'}
# 쓸 (작물, 질병) 조합 21개 + 작물별 정상 12개
DISEASE_KEYS = {(1, 1), (1, 2), (2, 3), (2, 4), (3, 5), (3, 6), (4, 7), (4, 8), (5, 9), (5, 10), (6, 11), (6, 12), (7, 13), (8, 15), (9, 14),
                (10, 16), (10, 17), (11, 18), (11, 19), (12, 20)}
VALID_KEYS = DISEASE_KEYS | {(c, 0) for c in CROP_NAME}
AREA_NAME = {1: '열매', 2: '꽃', 3: '잎', 5: '줄기'}
MIN_AREA_SHARE = 0.05
NORMAL_RATIO = 2.0
MARGIN = 0.25
LONG_SIDE = 512
JPEG_Q = 90
SPLIT_RATIO = (0.8, 0.1, 0.1)
TRANSPOSE = {2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180, 4: Image.Transpose.FLIP_TOP_BOTTOM,
             5: Image.Transpose.TRANSPOSE, 6: Image.Transpose.ROTATE_270, 7: Image.Transpose.TRANSVERSE, 8: Image.Transpose.ROTATE_90}
AUG_RE = re.compile(r'_a\d{3,4}\.', re.I)


def group_id(crop, name, is_disease):
    """질병: 대상ID. 정상: (장소, 날짜) 묶음. 파일명 `V006_77_{type}_{disease}_{crop}_{area}_{grow}_{risk}_{대상ID|장소}_{날짜}_...`"""
    p = name.split('_')
    return f'{crop}_{p[8]}' if is_disease else f'{crop}_{p[8]}_{p[9]}'


# ---------------------------------------------------------------- 1. 라벨 읽기
def read_labels(raw, crops, stats):
    """라벨 zip 전부를 읽어 레코드 목록을 만든다. 같은 이미지 이름은 Training 것을 우선해 한 번만."""
    recs, seen = [], set()
    for split_dir in ('1.Training', '2.Validation'):
        for crop in crops:
            for zp in sorted(glob.glob(f'{raw}/{split_dir}/라벨링데이터/{CROP_DIR[crop]}/*.zip')):
                if '증강' in os.path.basename(zp): continue
                z = zipfile.ZipFile(zp)
                for info in z.infolist():
                    if info.is_dir() or not info.filename.lower().endswith('.json'): continue
                    stats['label_files'] += 1
                    name = os.path.basename(info.filename)[:-5]
                    if AUG_RE.search(name): stats['aug'] += 1; continue
                    d = json.loads(z.read(info).decode('utf-8')); a, ds = d['annotations'], d['description']
                    key = (a['crop'], a['disease'])
                    stats['raw'][(split_dir, key)] += 1
                    if key not in VALID_KEYS or key[0] != crop: stats['bad_key'][key] += 1; continue
                    if not a.get('points') or a.get('area') is None: stats['no_box'] += 1; continue
                    if name in seen: stats['dup'] += 1; continue
                    seen.add(name)
                    recs.append(dict(name=name, crop=a['crop'], disease=a['disease'], area=a['area'], risk=a.get('risk', ''), region=ds.get('region', ''),
                                     date=ds.get('date', ''), w=ds['width'], h=ds['height'], box=a['points'][0],
                                     gid=group_id(a['crop'], name, a['disease'] != 0)))
    return recs


def index_images(raw, crops):
    """원천 zip의 파일 목록 (이미지 이름 → (zip 경로, zip 안 이름)). 한 이름이 여러 곳이면 Training 우선."""
    idx = {}
    for split_dir in ('2.Validation', '1.Training'):      # 뒤에 오는 Training이 덮어쓴다
        for crop in crops:
            for zp in sorted(glob.glob(f'{raw}/{split_dir}/원천데이터/{CROP_DIR[crop]}/*.zip')):
                if '증강' in os.path.basename(zp): continue
                for info in zipfile.ZipFile(zp).infolist():
                    if not info.is_dir(): idx[os.path.basename(info.filename)] = (zp, info.filename)
    return idx


# ---------------------------------------------------------------- 2~3. 부위·정상 선별
def spaced(items, n):
    """정렬된 목록에서 n개를 같은 간격으로."""
    if n >= len(items): return list(items)
    return [items[int(i)] for i in np.linspace(0, len(items) - 1, n).round()]


def fair_share(sizes, total):
    """묶음마다 같은 몫(남으면 다른 묶음에 넘김). 반환: 묶음별 개수"""
    out = [0] * len(sizes); left = total; open_ = [i for i, s in enumerate(sizes) if s > 0]
    while left > 0 and open_:
        share = max(1, left // len(open_)); nxt = []
        for i in open_:
            t = min(share, sizes[i] - out[i], left); out[i] += t; left -= t
            if out[i] < sizes[i]: nxt.append(i)
            if left == 0: break
        open_ = nxt
    return out


def select(recs, notes):
    by_crop = collections.defaultdict(list)
    for r in recs: by_crop[r['crop']].append(r)
    chosen = []
    for crop, rs in sorted(by_crop.items()):
        dis = [r for r in rs if r['disease'] != 0]; nor = [r for r in rs if r['disease'] == 0]
        area_cnt = collections.Counter(r['area'] for r in dis); tot = sum(area_cnt.values())
        areas = sorted(a for a, n in area_cnt.items() if n / tot >= MIN_AREA_SHARE)
        dis = [r for r in dis if r['area'] in areas]
        chosen += dis
        notes.append(f'- {CROP_NAME[crop]}: 쓰는 부위 {[AREA_NAME.get(a, a) for a in areas]} (질병 비율 ' + ', '.join(f'{AREA_NAME.get(a, a)} {area_cnt[a] / tot:.0%}' for a in sorted(area_cnt)) + ')')
        if not nor or not dis: continue
        cap = int(NORMAL_RATIO * len(dis)); share = {a: sum(r['area'] == a for r in dis) / len(dis) for a in areas}
        nor = [r for r in nor if r['area'] in areas]
        quota = {a: int(round(cap * share[a])) for a in areas}
        pick = []
        for a in areas:
            groups = collections.defaultdict(list)
            for r in nor:
                if r['area'] == a: groups[r['gid']].append(r)
            gl = sorted(groups); take = fair_share([len(groups[g]) for g in gl], quota[a])
            for g, k in zip(gl, take): pick += spaced(sorted(groups[g], key=lambda r: r['name']), k)
        chosen += pick
        notes.append(f'  정상 후보 {len(nor)}장 → {len(pick)}장 (한도 {cap}, 묶음 {len({r["gid"] for r in nor})}개)')
    return chosen


# ---------------------------------------------------------------- 4. 분할
def assign_split(chosen, seed, notes):
    rng = random.Random(seed); by_cls = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in chosen: by_cls[(r['crop'], r['disease'])][r['gid']].append(r)
    for key in sorted(by_cls):
        gs = sorted(by_cls[key]); n = len(gs); size = {g: len(by_cls[key][g]) for g in gs}; tot = sum(size.values())
        n_te = max(1, round(SPLIT_RATIO[2] * n)); n_va = max(1 if n >= 3 else 0, round(SPLIT_RATIO[1] * n))
        if n_te + n_va >= n: n_va = max(0, n - n_te - 1)
        # 묶음 크기가 제각각이라 묶음 수만 맞추면 장수 비율이 크게 틀어진다 → 묶음 단위는 지키고, 장수 비율이 8/1/1에 가장 가까운 배정을 무작위 탐색으로 고른다
        best, best_cost = None, 1e9
        for _ in range(400):
            order = gs[:]; rng.shuffle(order)
            te, va = order[:n_te], order[n_te:n_te + n_va]
            s_te, s_va = sum(size[g] for g in te) / tot, sum(size[g] for g in va) / tot
            cost = abs(s_te - SPLIT_RATIO[2]) + abs(s_va - SPLIT_RATIO[1])
            if cost < best_cost: best, best_cost = (set(te), set(va)), cost
        te_set, va_set = best
        for g in gs:
            sp = 'test' if g in te_set else 'val' if g in va_set else 'train'
            for r in by_cls[key][g]: r['split'] = sp
        if n < 3: notes.append(f'- 묶음 {n}개뿐: {CROP_NAME[key[0]]} {DISEASE_NAME[key[1]]} (시험/검증 점수 불안정)')


# ---------------------------------------------------------------- 5. 이미지 처리
_ZIPS = {}


def process(task):
    r, zp, member, out_path = task
    try:
        z = _ZIPS.get(zp) or _ZIPS.setdefault(zp, zipfile.ZipFile(zp))
        im = Image.open(io.BytesIO(z.read(member)))
        raw_w, raw_h = im.size; orient = im.getexif().get(274, 1)
        # bbox가 원본 방향 기준인지 회전 적용 후 기준인지는 JSON 크기가 맞는 쪽으로 정한다
        raw_frame = (r['w'], r['h']) == (raw_w, raw_h) or orient not in TRANSPOSE
        if not raw_frame and (r['w'], r['h']) != (raw_h, raw_w): raw_frame = True
        b = r['box']; fw, fh = r['w'], r['h']
        bw0, bh0 = b['xbr'] - b['xtl'], b['ybr'] - b['ytl']
        # 속도: 잘라낸 크기가 512보다 충분히 크면 JPEG를 줄여서 읽는다
        for s in (8, 4, 2, 1):
            if max(bw0, bh0) * (1 + 2 * MARGIN) / s >= LONG_SIDE * 1.0: break
        if s > 1: im.draft('RGB', (raw_w // s, raw_h // s))
        im = im.convert('RGB')
        if not raw_frame: im = ImageOps.exif_transpose(im)
        cw, ch = im.size; sx, sy = cw / fw, ch / fh
        x0, y0, x1, y1 = b['xtl'] * sx, b['ytl'] * sy, b['xbr'] * sx, b['ybr'] * sy
        bw, bh = x1 - x0, y1 - y0
        if bw < 8 or bh < 8: return ('bad_box', r['name'])
        # raw_frame이면 먼저 EXIF 회전을 맞춘다 (bbox도 같이 변환한다)
        if raw_frame and orient in TRANSPOSE:
            im = im.transpose(TRANSPOSE[orient]); (x0, y0, x1, y1), (cw, ch) = _tb((x0, y0, x1, y1), (cw, ch), orient), im.size
            bw, bh = x1 - x0, y1 - y0
        c0, d0 = max(0, x0 - MARGIN * bw), max(0, y0 - MARGIN * bh)
        c1, d1 = min(cw, x1 + MARGIN * bw), min(ch, y1 + MARGIN * bh)
        crop = im.crop((int(c0), int(d0), int(c1), int(d1)))
        k = min(1.0, LONG_SIDE / max(crop.size))
        if k < 1: crop = crop.resize((max(1, round(crop.width * k)), max(1, round(crop.height * k))), Image.LANCZOS)
        fx, fy = crop.width / max(1e-6, c1 - c0), crop.height / max(1e-6, d1 - d0)
        box = [round((x0 - int(c0)) * fx), round((y0 - int(d0)) * fy), round((x1 - int(c0)) * fx), round((y1 - int(d0)) * fy)]
        box = [max(0, min(box[0], crop.width)), max(0, min(box[1], crop.height)), max(0, min(box[2], crop.width)), max(0, min(box[3], crop.height))]
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        crop.save(out_path, 'JPEG', quality=JPEG_Q)
        return ('ok', r['name'], box, crop.width, crop.height)
    except Exception as e:  # noqa: BLE001
        return ('error', r['name'], repr(e))


def _tb(box, size, orient):
    """상자 좌표에 EXIF transpose를 적용한다 (크기 size는 변환 전)."""
    x0, y0, x1, y1 = box; w, h = size
    pts = {2: (w - x1, y0, w - x0, y1), 3: (w - x1, h - y1, w - x0, h - y0), 4: (x0, h - y1, x1, h - y0),
           5: (y0, x0, y1, x1), 6: (h - y1, x0, h - y0, x1), 7: (h - y1, w - x1, h - y0, w - x0), 8: (y0, w - x1, y1, w - x0)}
    return pts[orient]


# ---------------------------------------------------------------- 7. 결과물
def write_summary(rows, out, notes, stats, crops):
    L = ['# 153 전처리 요약', '', f'- 처리한 작물: {", ".join(CROP_NAME[c] for c in crops)}',
         f'- 읽은 라벨 {stats["label_files"]}개 · 증강본 {stats["aug"]}개 제외 · 코드표 밖 조합 {sum(stats["bad_key"].values())}개 제외 · bbox 없음 {stats["no_box"]}개 · Training/Validation 중복 {stats["dup"]}개',
         f'- 이미지를 못 찾음 {stats["missing"]}장 · 처리 실패 {stats["failed"]}장', '', '## 선별 기록', *notes, '']
    cls = collections.OrderedDict(); sp_names = ('train', 'val', 'test')
    for r in sorted(rows, key=lambda r: (r['crop_code'], r['disease_code'])):
        c = cls.setdefault(r['label'], {'img': collections.Counter(), 'grp': {s: set() for s in sp_names}, 'row': r}); c['img'][r['split']] += 1; c['grp'][r['split']].add(r['group_id'])
    L += ['## 클래스 × 분할 (이미지 수 / 묶음 수)', '', '| 클래스 | train | val | test | 합계 | 묶음 train/val/test |', '|---|---:|---:|---:|---:|---|']
    tot = collections.Counter()
    for label, c in cls.items():
        n = [c['img'][s] for s in sp_names]; tot.update(c['img'])
        L.append(f'| {label} {DISEASE_NAME[c["row"]["disease_code"]]} | {n[0]} | {n[1]} | {n[2]} | {sum(n)} | {"/".join(str(len(c["grp"][s])) for s in sp_names)} |')
    L.append(f'| **합계** | {tot["train"]} | {tot["val"]} | {tot["test"]} | {sum(tot.values())} | |')
    L += ['', '## 원본 수 (Training+Validation 라벨, 증강 제외, 코드표 안, 선별 전)', '', '| 작물_질병 | Training | Validation |', '|---|---:|---:|']
    keys = sorted({k for (_, k) in stats['raw'] if k in VALID_KEYS})
    for k in keys: L.append(f'| {CROP_NAME[k[0]]}_{k[1]} {DISEASE_NAME[k[1]]} | {stats["raw"][("1.Training", k)]} | {stats["raw"][("2.Validation", k)]} |')
    if stats['bad_key']:
        L += ['', '## 버린 조합 (코드표 밖)', '', ', '.join(f'({CROP_NAME.get(k[0], k[0])},{k[1]}):{n}' for k, n in sorted(stats['bad_key'].items()))]
    open(f'{out}/summary.md', 'w', encoding='utf-8').write('\n'.join(L) + '\n')


def review_sheets(rows, out, review, per_class=10, thumb=170):
    os.makedirs(review, exist_ok=True); rng = random.Random(7)
    try: font = ImageFont.truetype('C:/Windows/Fonts/malgun.ttf', 14)
    except OSError: font = ImageFont.load_default()
    by = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in rows: by[r['crop_code']][r['label']].append(r)
    for crop, classes in by.items():
        labels = sorted(classes); H = 22 + thumb
        sheet = Image.new('RGB', (per_class * thumb, len(labels) * H), (255, 255, 255)); d = ImageDraw.Draw(sheet)
        for ri, label in enumerate(labels):
            rs = classes[label]; ex = rng.sample(rs, min(per_class, len(rs)))
            d.text((4, ri * H + 2), f'{label} {rs[0]["disease_name"]} ({len(rs)}장)', fill=(0, 0, 0), font=font)
            for ci, r in enumerate(ex):
                im = Image.open(f'{out}/{r["path"]}').convert('RGB'); k = thumb / max(im.size); s = (round(im.width * k), round(im.height * k))
                im = im.resize(s); dd = ImageDraw.Draw(im)
                dd.rectangle([r['bx0'] * k, r['by0'] * k, r['bx1'] * k - 1, r['by1'] * k - 1], outline=(255, 0, 0), width=2)   # 저장된 bbox 위치 확인용
                sheet.paste(im, (ci * thumb, ri * H + 22))
        sheet.save(f'{review}/{CROP_NAME[crop]}.jpg', quality=85)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--raw', required=True); ap.add_argument('--out', required=True); ap.add_argument('--review', default=None)
    ap.add_argument('--crops', default='all'); ap.add_argument('--workers', type=int, default=12); ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()
    crops = sorted(CROP_NAME) if a.crops == 'all' else sorted(k for k, v in CROP_NAME.items() if v in a.crops.split(','))
    os.makedirs(a.out, exist_ok=True); t0 = time.time()
    stats = dict(label_files=0, aug=0, no_box=0, dup=0, missing=0, failed=0, raw=collections.Counter(), bad_key=collections.Counter()); notes = []
    print('1. 라벨 읽기', flush=True); recs = read_labels(a.raw, crops, stats)
    print(f'   쓸 수 있는 라벨 {len(recs)}개 ({time.time() - t0:.0f}초). 원천 zip 목록 읽기', flush=True); idx = index_images(a.raw, crops)
    ok = []
    for r in recs:
        if r['name'] in idx: ok.append(r)
        else: stats['missing'] += 1
    print(f'   이미지 짝이 맞는 것 {len(ok)}개 (못 찾음 {stats["missing"]})', flush=True)
    print('2~3. 부위·정상 선별', flush=True); chosen = select(ok, notes)
    print('4. 분할', flush=True); assign_split(chosen, a.seed, notes)
    tasks = []
    for r in chosen:
        zp, member = idx[r['name']]; stem = os.path.splitext(r['name'])[0]
        r['rel'] = f'{CROP_NAME[r["crop"]]}_{r["disease"]}/{stem}.jpg'; tasks.append((r, zp, member, f'{a.out}/{r["rel"]}'))
    tasks.sort(key=lambda t: t[1])      # 같은 zip끼리 모아서 읽는다
    print(f'5. 이미지 {len(tasks)}장 자르기', flush=True); res = {}
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        for n, out in enumerate(ex.map(process, tasks, chunksize=32), 1):
            res[out[1]] = out
            if n % 2000 == 0: print(f'   {n}/{len(tasks)} ({time.time() - t0:.0f}초)', flush=True)
    rows = []; seen_paths = set()
    for r in chosen:
        if r['rel'].lower() in seen_paths: notes.append(f'- 경로 중복 제외 {r["name"]}'); continue    # 확장자만 다른 같은 stem은 같은 파일로 덮어써진다
        seen_paths.add(r['rel'].lower()); o = res[r['name']]
        if o[0] != 'ok': stats['failed'] += 1; notes.append(f'- 실패 {r["name"]}: {o[2:] if len(o) > 2 else o[0]}'); continue
        _, _, box, w, h = o
        rows.append(dict(path=r['rel'], dataset=153, crop_code=r['crop'], crop_name=CROP_NAME[r['crop']], disease_code=r['disease'], disease_name=DISEASE_NAME[r['disease']],
                         label=f'{CROP_NAME[r["crop"]]}_{r["disease"]}', group_id=r['gid'], split=r['split'], area=r['area'], risk=r['risk'], region=r['region'], date=r['date'],
                         orig_w=r['w'], orig_h=r['h'], img_w=w, img_h=h, bx0=box[0], by0=box[1], bx1=box[2], by1=box[3]))
    rows.sort(key=lambda r: r['path'])
    with open(f'{a.out}/manifest.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w_ = csv.DictWriter(f, fieldnames=list(rows[0])); w_.writeheader(); w_.writerows(rows)
    write_summary(rows, a.out, notes, stats, crops)
    if a.review: review_sheets(rows, a.out, a.review)
    print(f'끝: {len(rows)}장, {time.time() - t0:.0f}초 → {a.out}', flush=True)


if __name__ == '__main__':
    main()
