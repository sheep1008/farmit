"""146 과수화상병(사과·배) 전처리 (docs/vision.md 5장 규격 + docs/vision-146.md 4~6장의 결정). 원본 zip을 풀지 않고 바로 읽는다.

  .venv/Scripts/python.exe -I -X utf8 preprocess_146.py --raw "data/raw/146/과수화상병 촬영 이미지" --out data/processed/146 \
      [--crops 배] [--review data/review/146] [--workers 12] [--dis-cap 1000] [--normal-cap 3000]

153(preprocess.py)·147(preprocess_147.py)과 다른 점
  - 작물 코드가 배 1·사과 2, 질병 코드는 배 1~2·사과 3~7(데이터셋 안에서 이어짐). 질병 이름은 설명서가 없어 미확정.
  - 질병 JSON의 `type`은 null이다 (zip 종류로 정상/질병을 가른다). 질병 JSON의 `area`는 파일명과 어긋나는 것이 많아 **파일명 부위**를 쓴다.
  - 부위: 01 열매, 03 잎, 04 가지, 05 줄기(주간). 질병 대상ID는 클래스 사이에 공유되지 않는다.
  - 이미지 확장자가 .jpg·.JPG·.png(사과 질병 867장)이다. 라벨 JSON 이름은 `<이미지 이름>.json`.
  - **bbox는 EXIF 회전 뒤 좌표**다 (EXIF 6 정상 176장에서 확인). 항상 EXIF 회전을 먼저 적용한다.
  - 이상 라벨 제외: JSON과 파일명이 어긋난 행(작물·질병 코드·risk·정상 type), 질병인데 risk 0, 정상인데 risk>0·region 있음, 파일명 규칙 밖.
  - **불균형 상한 (146 신규):** 질병 클래스당 `--dis-cap`장(대상ID 균등 분배 + 같은 대상 안에서 간격 추출), 정상은 작물당 min(질병 합×2, `--normal-cap`).
선별(부위·정상 묶음 균등)·자르기(여백 25%, 긴 변 512, JPEG 90)·manifest 형식은 153·147과 같다 (dataset=146).
"""
import argparse, collections, csv, io, json, os, random, re, time, zipfile
from concurrent.futures import ProcessPoolExecutor

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

CROP_NAME = {1: '배', 2: '사과'}
NAME_CODE = {'배': 1, '사과': 2}
DISEASE_OF_CROP = {1: (1, 2), 2: (3, 4, 5, 6, 7)}
DISEASE_NAME = {0: '정상', 1: '배검은별무늬병', 2: '배과수화상병', 3: '사과갈색무늬병', 4: '사과과수화상병', 5: '사과부란병', 6: '사과점무늬낙엽병', 7: '사과탄저병'}   # AI Hub 설명서 표 (2026-11-19 사용자 제공)
AREA_NAME = {1: '열매', 3: '잎', 4: '가지', 5: '줄기'}
MIN_AREA_SHARE = 0.05
NORMAL_RATIO = 2.0
MARGIN = 0.25
LONG_SIDE = 512
JPEG_Q = 90
MIN_CROP_PX = 128
SPLIT_RATIO = (0.8, 0.1, 0.1)
ORIENT = {5, 6, 7, 8}
TRANSPOSE_OPS = {2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180, 4: Image.Transpose.FLIP_TOP_BOTTOM,
                 5: Image.Transpose.TRANSPOSE, 6: Image.Transpose.ROTATE_270, 7: Image.Transpose.TRANSVERSE, 8: Image.Transpose.ROTATE_90}
EXT = re.compile(r'\.(jpe?g|png)$', re.I)
SEQ_RE = re.compile(r'\d{4}_S\d+(_\d+)?$')      # 정상: 번호_S0n[_n]


def zname(i):
    return i.filename if i.flag_bits & 0x800 else i.filename.encode('cp437').decode('cp949')


# ---------------------------------------------------------------- 1. 라벨 읽기
def read_labels(raw, crops, stats):
    recs, seen = [], set()
    for split in ('Training', 'Validation'):
        for f in sorted(os.listdir(f'{raw}/{split}')):
            if not f.startswith('[라벨]') or '증강' in f: continue
            zip_crop = NAME_CODE['사과' if '사과' in f else '배']; is_dis = '질병' in f
            z = zipfile.ZipFile(f'{raw}/{split}/{f}')
            for info in z.infolist():
                if info.is_dir() or not info.filename.lower().endswith('.json'): continue
                stats['label_files'] += 1
                d = json.loads(z.read(info).decode('utf-8-sig')); a, ds = d['annotations'], d['description']
                name = ds['image']; p = EXT.sub('', name).split('_')
                stats['raw'][(split, zip_crop, 'dis' if is_dis else 'nor')] += 1
                if zip_crop not in crops: continue
                if len(p) < 11 or not p[3].isdigit() or not p[7].isdigit(): stats['irregular_name'] += 1; continue
                disease = a['disease']
                if is_dis:
                    if disease not in DISEASE_OF_CROP[zip_crop]: stats['bad_key'][(zip_crop, disease)] += 1; continue
                    if not (a['crop'] == zip_crop and int(p[3]) == disease and int(p[4]) == zip_crop): stats['mismatch'] += 1; continue
                    if a.get('risk', 0) != int(p[7]): stats['mismatch'] += 1; continue
                    if a.get('risk', 0) == 0: stats['anomaly_disease_risk0'] += 1; continue
                    if not re.fullmatch(r'\d{8}', p[9]): stats['irregular_name'] += 1; continue
                else:
                    if disease != 0 or a['crop'] != zip_crop or int(p[4]) != zip_crop: stats['mismatch'] += 1; continue
                    if ds.get('type') != 0: stats['anomaly_normal_type'] += 1; continue
                    if ds.get('region') not in (None, ''): stats['anomaly_normal_region'] += 1; continue
                    if a.get('risk', 0) != 0 or p[7] != '0': stats['anomaly_normal_risk'] += 1; continue
                    if not (len(p) in (12, 13) and re.fullmatch(r'\d{8}', p[9]) and SEQ_RE.match('_'.join(p[10:]))): stats['irregular_name'] += 1; continue
                if not a.get('points'): stats['no_box'] += 1; continue
                if name in seen: stats['dup'] += 1; continue
                seen.add(name)
                area = int(p[5])        # 파일명 부위 (JSON area는 질병에서 어긋남)
                recs.append(dict(name=name, crop=zip_crop, disease=disease, area=area, risk=a.get('risk', 0), region=ds.get('region') or '', date=ds.get('date') or '',
                                 box=a['points'][0], src_split=split, gid=(f'{zip_crop}_{p[8]}' if is_dis else f'{zip_crop}_{p[8]}_{p[9]}')))
    return recs


def index_images(raw):
    idx = {}
    for split in ('Validation', 'Training'):
        for f in sorted(os.listdir(f'{raw}/{split}')):
            if not f.startswith('[원천]') or '증강' in f: continue
            for info in zipfile.ZipFile(f'{raw}/{split}/{f}').infolist():
                if not info.is_dir(): idx[os.path.basename(zname(info))] = (f'{raw}/{split}/{f}', info.filename)
    return idx


# ---------------------------------------------------------------- 2~3. 부위·상한·정상 선별
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


def pick_by_group(rs, n):
    """묶음(대상ID)마다 균등 분배한 뒤, 묶음 안에서는 이름 순서로 간격을 두고 뽑는다."""
    groups = collections.defaultdict(list)
    for r in rs: groups[r['gid']].append(r)
    gl = sorted(groups); take = fair_share([len(groups[g]) for g in gl], n); out = []
    for g, k in zip(gl, take): out += spaced(sorted(groups[g], key=lambda r: r['name']), k)
    return out


def select(recs, notes, dis_cap, normal_cap):
    by_crop = collections.defaultdict(list)
    for r in recs: by_crop[r['crop']].append(r)
    chosen = []
    for crop, rs in sorted(by_crop.items()):
        dis = [r for r in rs if r['disease'] != 0]; nor = [r for r in rs if r['disease'] == 0]
        area_cnt = collections.Counter(r['area'] for r in dis); tot = sum(area_cnt.values())
        areas = sorted(a for a, n in area_cnt.items() if n / tot >= MIN_AREA_SHARE)
        dis = [r for r in dis if r['area'] in areas]
        kept = []
        for d in sorted({r['disease'] for r in dis}):
            cl = [r for r in dis if r['disease'] == d]; ng = len({r['gid'] for r in cl})
            pick = pick_by_group(cl, dis_cap) if dis_cap else cl
            kept += pick
            notes.append(f'  - {CROP_NAME[crop]}_{d}: 후보 {len(cl)}장(대상 {ng}개) → {len(pick)}장 (상한 {dis_cap or "없음"})')
        chosen += kept
        notes.append(f'- {CROP_NAME[crop]}: 쓰는 부위 {[AREA_NAME.get(a, a) for a in areas]} (질병 비율 ' + ', '.join(f'{AREA_NAME.get(a, a)} {area_cnt[a] / tot:.0%}' for a in sorted(area_cnt)) + f') · 질병 {len(kept)}장')
        if not nor or not kept: continue
        cap = int(NORMAL_RATIO * len(kept)); cap_note = ''
        if normal_cap and cap > normal_cap: cap, cap_note = normal_cap, f' (질병×2={int(NORMAL_RATIO * len(kept))} → 상한 {normal_cap})'
        share = {a: sum(r['area'] == a for r in kept) / len(kept) for a in areas}
        nor = [r for r in nor if r['area'] in areas]; quota = {a: int(round(cap * share[a])) for a in areas}; pick = []
        for a in areas: pick += pick_by_group([r for r in nor if r['area'] == a], quota[a])
        chosen += pick
        notes.append(f'  정상 후보 {len(nor)}장 → {len(pick)}장 (한도 {cap}{cap_note}, 묶음 {len({r["gid"] for r in nor})}개)')
    return chosen


# ---------------------------------------------------------------- 4. 분할 (작물 안에서 같은 대상ID는 같은 분할; 147과 같다)
def assign_split(chosen, seed, notes):
    rng = random.Random(seed); by_crop = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(list)))
    for r in chosen: by_crop[r['crop']][r['disease']][r['gid']].append(r)
    for crop in sorted(by_crop):
        fixed = {}
        classes = sorted(by_crop[crop], key=lambda d: (d == 0, len(by_crop[crop][d])))
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
        fw, fh = (raw_h, raw_w) if orient in ORIENT else (raw_w, raw_h)      # EXIF 회전 뒤 크기. bbox는 이 좌표다
        b = r['box']; bw0, bh0 = b['xbr'] - b['xtl'], b['ybr'] - b['ytl']
        if bw0 < 8 or bh0 < 8: return ('bad_box', r['name'])
        if max(bw0, bh0) * (1 + 2 * MARGIN) < MIN_CROP_PX: return ('too_small', r['name'])
        for s in (8, 4, 2, 1):
            if max(bw0, bh0) * (1 + 2 * MARGIN) / s >= LONG_SIDE: break
        if s > 1: im.draft('RGB', (raw_w // s, raw_h // s))
        im = im.convert('RGB')
        if orient in TRANSPOSE_OPS: im = ImageOps.exif_transpose(im)
        cw, ch = im.size; sx, sy = cw / fw, ch / fh
        oob = b['xbr'] > fw * 1.01 or b['ybr'] > fh * 1.01
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
def write_summary(rows, out, notes, stats, crops, caps):
    L = ['# 146 전처리 요약', '', f'- 처리한 작물: {", ".join(CROP_NAME[c] for c in crops)}', f'- 상한: 질병 클래스당 {caps[0] or "없음"}장, 작물당 정상 min(질병×2, {caps[1] or "없음"})',
         f'- 읽은 라벨 {stats["label_files"]}개 · 코드표 밖 {sum(stats["bad_key"].values())}개({dict(stats["bad_key"])}) · bbox 없음 {stats["no_box"]}개 · 중복 {stats["dup"]}개',
         f'- 이상 라벨 제외: JSON·파일명 어긋남 {stats["mismatch"]}, 질병인데 risk 0 {stats["anomaly_disease_risk0"]}, 정상인데 type≠0 {stats["anomaly_normal_type"]}, 정상인데 region 있음 {stats["anomaly_normal_region"]}, 정상인데 risk>0 {stats["anomaly_normal_risk"]}, 파일명 규칙 밖 {stats["irregular_name"]}',
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
    L += ['', '## 원본 수 (Training+Validation 라벨, 선별 전)', '', '| 작물 | 구분 | Training | Validation |', '|---|---|---:|---:|']
    for crop in crops:
        for kd, nm in (('nor', '정상'), ('dis', '질병')): L.append(f'| {CROP_NAME[crop]} | {nm} | {stats["raw"][("Training", crop, kd)]} | {stats["raw"][("Validation", crop, kd)]} |')
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
                im = Image.open(f'{out}/{r["path"]}').convert('RGB'); k = thumb / max(im.size); im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k)))); dd = ImageDraw.Draw(im)
                dd.rectangle([r['bx0'] * k, r['by0'] * k, r['bx1'] * k - 1, r['by1'] * k - 1], outline=(255, 0, 0), width=2)
                sheet.paste(im, (ci * thumb, ri * H + 22))
        sheet.save(f'{review}/{CROP_NAME[crop]}.jpg', quality=85)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--raw', required=True); ap.add_argument('--out', required=True); ap.add_argument('--review', default=None)
    ap.add_argument('--crops', default='all'); ap.add_argument('--workers', type=int, default=12); ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--dis-cap', type=int, default=1000); ap.add_argument('--normal-cap', type=int, default=3000)
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
    print('2~3. 부위·상한·정상 선별', flush=True); chosen = select(ok, notes, a.dis_cap, a.normal_cap)
    print('4. 분할', flush=True); assign_split(chosen, a.seed, notes)
    tasks = []
    for r in chosen:
        zp, member = idx[r['name']]; stem = EXT.sub('', r['name'])
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
        rows.append(dict(path=r['rel'], dataset=146, crop_code=r['crop'], crop_name=CROP_NAME[r['crop']], disease_code=r['disease'], disease_name=DISEASE_NAME[r['disease']],
                         label=f'{CROP_NAME[r["crop"]]}_{r["disease"]}', group_id=r['gid'], split=r['split'], area=r['area'], risk=r['risk'], region=r['region'], date=r['date'],
                         orig_w=fw, orig_h=fh, img_w=w, img_h=h, bx0=box[0], by0=box[1], bx1=box[2], by1=box[3], exif=int(exif)))
    rows.sort(key=lambda r: r['path'])
    with open(f'{a.out}/manifest.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w_ = csv.DictWriter(f, fieldnames=list(rows[0])); w_.writeheader(); w_.writerows(rows)
    write_summary(rows, a.out, notes, stats, crops, (a.dis_cap, a.normal_cap))
    if a.review: review_sheets(rows, a.out, a.review)
    print(f'끝: {len(rows)}장, {time.time() - t0:.0f}초 → {a.out}', flush=True)


if __name__ == '__main__':
    main()
