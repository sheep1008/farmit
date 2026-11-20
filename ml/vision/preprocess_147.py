"""147 노지 작물 질병 전처리 (docs/vision/archive/vision.md 5장 규격 + docs/vision/archive/vision-147.md 4·5장의 결정). 원본 zip을 풀지 않고 바로 읽는다.

  .venv/Scripts/python.exe -I -X utf8 preprocess_147.py --raw "data/raw/147/노지 작물 질병 진단 이미지" --out data/processed/147 \
      [--crops 고추,토마토] [--review data/review/147] [--workers 12]

153(preprocess.py)과 다른 점
  - 폴더가 평평하고 라벨/원천 zip 이름이 `[라벨]작물_...zip`·`[원천]작물_...zip`이다. 이미지 이름으로 모든 원천 zip을 색인한다.
  - 코드: 작물 1~10, 질병 1~20(작물에 걸쳐 이어짐). 코드표 밖 (호박, 0)은 버린다. 질병 이름은 설명서가 없어 미확정.
  - **bbox는 EXIF 회전 뒤 좌표**이고 JSON width/height는 회전 전 크기(또는 0)다. 항상 EXIF 회전을 적용한 뒤 bbox를 그대로 쓴다.
  - 이상 라벨 제외: 정상인데 risk>0·region 있음, 질병인데 risk 0, 정상 파일명이 규칙 밖(날짜·번호 형식이 다름).
  - 너무 작은 crop(여백 25%를 줬을 때 긴 변이 128px 미만)은 제외한다.
  - 분할: 같은 작물의 병 클래스가 같은 식물(대상ID)을 공유하므로, 한 번 정한 대상ID의 분할을 작물 안의 다른 클래스에서도 그대로 쓴다.
선별(부위·정상 2배)·자르기(여백 25%, 긴 변 512, JPEG 90)·manifest 형식은 153과 같다.
"""
import argparse, collections, csv, io, json, os, random, re, sys, time, zipfile
from concurrent.futures import ProcessPoolExecutor

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

CROP_NAME = {1: '고추', 2: '무', 3: '배추', 4: '애호박', 5: '양배추', 6: '오이', 7: '토마토', 8: '콩', 9: '파', 10: '호박'}
DISEASE_OF_CROP = {1: (1, 2), 2: (3, 4), 3: (5, 6), 4: (7, 8), 5: (9, 10), 6: (11, 12), 7: (15,), 8: (13, 14), 9: (16, 17, 18), 10: (19, 20)}
DISEASE_NAME = {0: '정상', **{d: f'질병{d}(이름 미확정)' for ds in DISEASE_OF_CROP.values() for d in ds}}
VALID_KEYS = {(c, d) for c, ds in DISEASE_OF_CROP.items() for d in ds} | {(c, 0) for c in CROP_NAME}
AREA_NAME = {1: '열매', 2: '꽃', 3: '잎', 5: '줄기'}
MIN_AREA_SHARE = 0.05
NORMAL_RATIO = 2.0
MARGIN = 0.25
LONG_SIDE = 512
JPEG_Q = 90
MIN_CROP_PX = 128          # 여백 25%를 준 crop의 긴 변(원본 픽셀)이 이보다 작으면 제외
SPLIT_RATIO = (0.8, 0.1, 0.1)
ORIENT = {5, 6, 7, 8}      # 가로·세로가 바뀌는 EXIF 방향
TRANSPOSE_OPS = {2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180, 4: Image.Transpose.FLIP_TOP_BOTTOM,
                 5: Image.Transpose.TRANSPOSE, 6: Image.Transpose.ROTATE_270, 7: Image.Transpose.TRANSVERSE, 8: Image.Transpose.ROTATE_90}
SEQ_RE = re.compile(r'\d+_S\d+_\d+$')


def zname(i):
    return i.filename if i.flag_bits & 0x800 else i.filename.encode('cp437').decode('cp949')


# ---------------------------------------------------------------- 1. 라벨 읽기
def read_labels(raw, crops, stats):
    recs, seen = [], set()
    for split in ('Training', 'Validation'):
        for f in sorted(os.listdir(f'{raw}/{split}')):
            if not f.startswith('[라벨]'): continue
            if '증강' in f: continue
            z = zipfile.ZipFile(f'{raw}/{split}/{f}')
            for info in z.infolist():
                if info.is_dir() or not info.filename.lower().endswith('.json'): continue
                stats['label_files'] += 1
                d = json.loads(z.read(info).decode('utf-8-sig')); a, ds = d['annotations'], d['description']
                name = ds['image']; key = (a['crop'], a['disease']); is_dis = ds['type'] == 1
                stats['raw'][(split, key)] += 1
                if a['crop'] not in crops: continue
                if key not in VALID_KEYS or (is_dis and key[1] == 0) or (not is_dis and key[1] != 0): stats['bad_key'][key] += 1; continue
                if not a.get('points'): stats['no_box'] += 1; continue
                p = name.rsplit('.', 1)[0].split('_')
                risk = a.get('risk', 0)
                if not is_dis:
                    if ds.get('region') not in (None, ''): stats['anomaly_normal_region'] += 1; continue
                    if risk != 0: stats['anomaly_normal_risk'] += 1; continue
                    if not (len(p) == 13 and re.fullmatch(r'\d{8}', p[9]) and SEQ_RE.match('_'.join(p[10:]))): stats['irregular_name'] += 1; continue
                else:
                    if risk == 0: stats['anomaly_disease_risk0'] += 1; continue
                    if len(p) < 11: stats['irregular_name'] += 1; continue
                if name in seen: stats['dup'] += 1; continue
                seen.add(name)
                recs.append(dict(name=name, crop=a['crop'], disease=a['disease'], area=a['area'], risk=risk, region=ds.get('region') or '', date=ds.get('date') or '',
                                 box=a['points'][0], src_split=split, gid=(f'{a["crop"]}_{p[8]}' if is_dis else f'{a["crop"]}_{p[8]}_{p[9]}')))
    return recs


def index_images(raw):
    """모든 원천 zip의 파일 목록: 이미지 이름 → (zip 경로, zip 안 이름). Training 우선."""
    idx = {}
    for split in ('Validation', 'Training'):
        for f in sorted(os.listdir(f'{raw}/{split}')):
            if not f.startswith('[원천]') or '증강' in f: continue
            for info in zipfile.ZipFile(f'{raw}/{split}/{f}').infolist():
                if not info.is_dir(): idx[os.path.basename(zname(info))] = (f'{raw}/{split}/{f}', info.filename)
    return idx


# ---------------------------------------------------------------- 2~3. 부위·정상 선별 (153과 같다)
def spaced(items, n):
    if n >= len(items): return list(items)
    return [items[int(i)] for i in np.linspace(0, len(items) - 1, n).round()]


def fair_share(sizes, total):
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
        notes.append(f'- {CROP_NAME[crop]}: 쓰는 부위 {[AREA_NAME.get(a, a) for a in areas]} (질병 비율 ' + ', '.join(f'{AREA_NAME.get(a, a)} {area_cnt[a] / tot:.0%}' for a in sorted(area_cnt)) + f') · 질병 {len(dis)}장')
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


# ---------------------------------------------------------------- 4. 분할 (작물 안에서 같은 대상ID는 같은 분할)
def assign_split(chosen, seed, notes):
    rng = random.Random(seed); by_crop = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(list)))
    for r in chosen: by_crop[r['crop']][r['disease']][r['gid']].append(r)
    for crop in sorted(by_crop):
        fixed = {}       # gid → split (같은 작물의 다른 병 클래스에서 이미 정한 것)
        classes = sorted(by_crop[crop], key=lambda d: (d == 0, len(by_crop[crop][d])))   # 묶음이 적은 병 클래스부터, 정상은 마지막
        for d in classes:
            groups = by_crop[crop][d]; gs = sorted(groups); n = len(gs); size = {g: len(groups[g]) for g in gs}; tot = sum(size.values())
            n_te = max(1, round(SPLIT_RATIO[2] * n)); n_va = max(1 if n >= 3 else 0, round(SPLIT_RATIO[1] * n))
            if n_te + n_va >= n: n_va = max(0, n - n_te - 1)
            have_te = sum(1 for g in gs if fixed.get(g) == 'test'); have_va = sum(1 for g in gs if fixed.get(g) == 'val')
            free = [g for g in gs if g not in fixed]; need_te, need_va = max(0, n_te - have_te), max(0, n_va - have_va)
            need_te = min(need_te, len(free)); need_va = min(need_va, len(free) - need_te)
            best, best_cost = None, 1e9
            for _ in range(400):
                order = free[:]; rng.shuffle(order); te, va = set(order[:need_te]), set(order[need_te:need_te + need_va])
                cur = {**fixed, **{g: 'test' for g in te}, **{g: 'val' for g in va}}
                s_te = sum(size[g] for g in gs if cur.get(g) == 'test') / tot; s_va = sum(size[g] for g in gs if cur.get(g) == 'val') / tot
                cost = abs(s_te - SPLIT_RATIO[2]) + abs(s_va - SPLIT_RATIO[1])
                if cost < best_cost: best, best_cost = (te, va), cost
            te, va = best
            for g in free: fixed[g] = 'test' if g in te else 'val' if g in va else 'train'
            for g in gs:
                for r in groups[g]: r['split'] = fixed[g]
            if n < 3: notes.append(f'- 묶음 {n}개뿐: {CROP_NAME[crop]} {DISEASE_NAME[d]} (시험/검증 점수 불안정)')
            if not any(fixed[g] == 'test' for g in gs): notes.append(f'- 시험 묶음이 없음: {CROP_NAME[crop]} {DISEASE_NAME[d]}')


# ---------------------------------------------------------------- 5. 이미지 처리
_ZIPS = {}


def process(task):
    r, zp, member, out_path = task
    try:
        z = _ZIPS.get(zp) or _ZIPS.setdefault(zp, zipfile.ZipFile(zp))
        im = Image.open(io.BytesIO(z.read(member)))
        raw_w, raw_h = im.size; orient = im.getexif().get(274, 1)
        fw, fh = (raw_h, raw_w) if orient in ORIENT else (raw_w, raw_h)      # EXIF 회전 뒤 전체 크기. bbox는 이 좌표다
        b = r['box']; bw0, bh0 = b['xbr'] - b['xtl'], b['ybr'] - b['ytl']
        if bw0 < 8 or bh0 < 8: return ('bad_box', r['name'])
        if max(bw0, bh0) * (1 + 2 * MARGIN) < MIN_CROP_PX: return ('too_small', r['name'])
        for s in (8, 4, 2, 1):
            if max(bw0, bh0) * (1 + 2 * MARGIN) / s >= LONG_SIDE: break
        if s > 1: im.draft('RGB', (raw_w // s, raw_h // s))
        im = im.convert('RGB')
        if orient in TRANSPOSE_OPS: im = ImageOps.exif_transpose(im)
        cw, ch = im.size; sx, sy = cw / fw, ch / fh
        oob = b['xbr'] > fw * 1.01 or b['ybr'] > fh * 1.01       # 회전 뒤 좌표인데도 이미지를 벗어나면 기록
        x0, y0, x1, y1 = max(0, b['xtl'] * sx), max(0, b['ytl'] * sy), min(cw, b['xbr'] * sx), min(ch, b['ybr'] * sy)
        bw, bh = x1 - x0, y1 - y0
        if bw < 8 or bh < 8: return ('bad_box', r['name'])
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
        return ('ok', r['name'], box, crop.width, crop.height, fw, fh, orient in TRANSPOSE_OPS, oob)
    except Exception as e:  # noqa: BLE001
        return ('error', r['name'], repr(e))


# ---------------------------------------------------------------- 7. 결과물
def write_summary(rows, out, notes, stats, crops):
    L = ['# 147 전처리 요약', '', f'- 처리한 작물: {", ".join(CROP_NAME[c] for c in crops)}',
         f'- 읽은 라벨 {stats["label_files"]}개 · 코드표 밖 {sum(stats["bad_key"].values())}개({dict(stats["bad_key"])}) · bbox 없음 {stats["no_box"]}개 · 중복 {stats["dup"]}개',
         f'- 이상 라벨 제외: 정상인데 region 있음 {stats["anomaly_normal_region"]}, 정상인데 risk>0 {stats["anomaly_normal_risk"]}, 질병인데 risk 0 {stats["anomaly_disease_risk0"]}, 파일명 규칙 밖 {stats["irregular_name"]}',
         f'- 이미지를 못 찾음 {stats["missing"]}장 · 처리 실패 {stats["failed"]}장 · crop이 너무 작음(<{MIN_CROP_PX}px) {stats["too_small"]}장 · bbox 너무 작음 {stats["bad_box"]}장',
         f'- EXIF 회전이 적용된 이미지 {stats["exif"]}장, 그 중 회전 뒤에도 bbox가 이미지를 벗어난 것 {stats["oob"]}장', '', '## 선별 기록', *notes, '']
    cls = collections.OrderedDict(); sp_names = ('train', 'val', 'test')
    for r in sorted(rows, key=lambda r: (r['crop_code'], r['disease_code'])):
        c = cls.setdefault(r['label'], {'img': collections.Counter(), 'grp': {s: set() for s in sp_names}, 'row': r}); c['img'][r['split']] += 1; c['grp'][r['split']].add(r['group_id'])
    L += ['## 클래스 × 분할 (이미지 수 / 묶음 수)', '', '| 클래스 | train | val | test | 합계 | 묶음 train/val/test |', '|---|---:|---:|---:|---:|---|']
    tot = collections.Counter()
    for label, c in cls.items():
        n = [c['img'][s] for s in sp_names]; tot.update(c['img'])
        L.append(f'| {label} {c["row"]["disease_name"]} | {n[0]} | {n[1]} | {n[2]} | {sum(n)} | {"/".join(str(len(c["grp"][s])) for s in sp_names)} |')
    L.append(f'| **합계** | {tot["train"]} | {tot["val"]} | {tot["test"]} | {sum(tot.values())} | |')
    L += ['', '## 원본 수 (Training+Validation 라벨, 코드표 안, 선별 전)', '', '| 작물_질병 | Training | Validation |', '|---|---:|---:|']
    for k in sorted(k for (_, k) in stats['raw'] if k in VALID_KEYS): L.append(f'| {CROP_NAME[k[0]]}_{k[1]} | {stats["raw"][("Training", k)]} | {stats["raw"][("Validation", k)]} |')
    open(f'{out}/summary.md', 'w', encoding='utf-8').write('\n'.join(L) + '\n')


def review_sheets(rows, out, review, per_class=10, thumb=170):
    os.makedirs(review, exist_ok=True); rng = random.Random(7)
    font = ImageFont.truetype('C:/Windows/Fonts/malgun.ttf', 14)
    by = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in rows: by[r['crop_code']][r['label']].append(r)
    for crop, classes in by.items():
        labels = sorted(classes); H = 22 + thumb
        sheet = Image.new('RGB', (per_class * thumb, len(labels) * H), (255, 255, 255)); d = ImageDraw.Draw(sheet)
        for ri, label in enumerate(labels):
            rs = classes[label]; ex = rng.sample(rs, min(per_class, len(rs)))
            d.text((4, ri * H + 2), f'{label} {rs[0]["disease_name"]} ({len(rs)}장)', fill=(0, 0, 0), font=font)
            for ci, r in enumerate(ex):
                im = Image.open(f'{out}/{r["path"]}').convert('RGB'); k = thumb / max(im.size); im = im.resize((round(im.width * k), round(im.height * k))); dd = ImageDraw.Draw(im)
                dd.rectangle([r['bx0'] * k, r['by0'] * k, r['bx1'] * k - 1, r['by1'] * k - 1], outline=(255, 0, 0), width=2)
                sheet.paste(im, (ci * thumb, ri * H + 22))
        sheet.save(f'{review}/{CROP_NAME[crop]}.jpg', quality=85)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--raw', required=True); ap.add_argument('--out', required=True); ap.add_argument('--review', default=None)
    ap.add_argument('--crops', default='all'); ap.add_argument('--workers', type=int, default=12); ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()
    crops = sorted(CROP_NAME) if a.crops == 'all' else sorted(k for k, v in CROP_NAME.items() if v in a.crops.split(','))
    os.makedirs(a.out, exist_ok=True); t0 = time.time()
    stats = collections.Counter(); stats['raw'] = collections.Counter(); stats['bad_key'] = collections.Counter(); notes = []
    print('1. 라벨 읽기', flush=True); recs = read_labels(a.raw, crops, stats)
    print(f'   쓸 수 있는 라벨 {len(recs)}개 ({time.time() - t0:.0f}초). 원천 zip 목록 읽기', flush=True); idx = index_images(a.raw)
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
    tasks.sort(key=lambda t: (t[1], t[2]))
    print(f'5. 이미지 {len(tasks)}장 자르기', flush=True); res = {}
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        for n, out in enumerate(ex.map(process, tasks, chunksize=32), 1):
            res[out[1]] = out
            if n % 2000 == 0: print(f'   {n}/{len(tasks)} ({time.time() - t0:.0f}초)', flush=True)
    rows = []; seen_paths = set()
    for r in chosen:
        if r['rel'].lower() in seen_paths: notes.append(f'- 경로 중복 제외 {r["name"]}'); continue
        seen_paths.add(r['rel'].lower()); o = res[r['name']]
        if o[0] != 'ok':
            if o[0] in ('bad_box', 'too_small'): stats[o[0]] += 1
            else: stats['failed'] += 1; notes.append(f'- 실패 {r["name"]}: {o[2:]}')
            continue
        _, _, box, w, h, fw, fh, exif, oob = o; stats['exif'] += exif; stats['oob'] += oob
        rows.append(dict(path=r['rel'], dataset=147, crop_code=r['crop'], crop_name=CROP_NAME[r['crop']], disease_code=r['disease'], disease_name=DISEASE_NAME[r['disease']],
                         label=f'{CROP_NAME[r["crop"]]}_{r["disease"]}', group_id=r['gid'], split=r['split'], area=r['area'], risk=r['risk'], region=r['region'], date=r['date'],
                         orig_w=fw, orig_h=fh, img_w=w, img_h=h, bx0=box[0], by0=box[1], bx1=box[2], by1=box[3], exif=int(exif)))
    rows.sort(key=lambda r: r['path'])
    with open(f'{a.out}/manifest.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w_ = csv.DictWriter(f, fieldnames=list(rows[0])); w_.writeheader(); w_.writerows(rows)
    write_summary(rows, a.out, notes, stats, crops)
    if a.review: review_sheets(rows, a.out, a.review)
    print(f'끝: {len(rows)}장, {time.time() - t0:.0f}초 → {a.out}', flush=True)


if __name__ == '__main__':
    main()
