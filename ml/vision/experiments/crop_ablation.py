"""전처리 효과 빠른 확인 (153, 작물 3종 9클래스).

같은 이미지로 세 가지 입력을 만들어 EfficientNet-B0를 짧게 학습하고, 촬영 대상(그룹) 단위로 나눈 시험셋 점수를 비교한다.
  A full   : 이미지 전체
  B crop   : bbox를 25% 넓혀 자른 잎
  C bgonly : bbox 영역을 회색으로 가린 이미지 (잎이 없는데도 맞히면 배경에 정답 단서가 있다는 뜻)

실행: python -X utf8 crop_ablation.py <153 01.데이터 폴더> [풀 크기=400] [시드 수=3]
"""
import collections, glob, io, json, os, random, sys, time, zipfile
from concurrent.futures import ProcessPoolExecutor

import numpy as np
from PIL import Image, ImageOps

SIZE = 288
CROPS = {2: '고추', 11: '토마토', 5: '상추'}
FOLDER = {2: '02.고추', 11: '11.토마토', 5: '05.상추'}
CLASSES = [(2, 0), (2, 3), (2, 4), (11, 0), (11, 18), (11, 19), (5, 0), (5, 9), (5, 10)]
CLS_IDX = {c: i for i, c in enumerate(CLASSES)}
TRANSPOSE = {2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180, 4: Image.Transpose.FLIP_TOP_BOTTOM,
             5: Image.Transpose.TRANSPOSE, 6: Image.Transpose.ROTATE_270, 7: Image.Transpose.TRANSVERSE, 8: Image.Transpose.ROTATE_90}


def gid_of(name, disease):
    p = os.path.basename(name).split('_')
    return p[8] if disease else p[8] + '_' + p[9]


def load_records(base):
    recs = collections.defaultdict(list)
    for crop in CROPS:
        for zp in sorted(glob.glob(f'{base}/1.Training/라벨링데이터/{FOLDER[crop]}/*.zip')):
            z = zipfile.ZipFile(zp)
            img_zip = glob.glob(f"{base}/1.Training/원천데이터/{FOLDER[crop]}/{os.path.basename(zp).replace('[라벨]', '')[:-4]}*.zip")
            for i in z.infolist():
                if i.is_dir() or not i.filename.endswith('.json'): continue
                d = json.loads(z.read(i).decode('utf-8')); a, ds = d['annotations'], d['description']
                key = (a['crop'], a['disease'])
                if key not in CLS_IDX or a['area'] != 3 or not a.get('points'): continue
                recs[key].append(dict(name=ds['image'], zips=img_zip, w=ds['width'], h=ds['height'], box=a['points'][0],
                                      gid=gid_of(ds['image'], a['disease'] != 0), cls=CLS_IDX[key]))
    return recs


def pick_pool(recs, per_class, seed=0):
    """클래스마다 그룹을 돌아가며 per_class장까지 뽑는다 (한 그룹이 독점하지 않게)."""
    rng = random.Random(seed); pool = []
    for key, rs in recs.items():
        by = collections.defaultdict(list)
        for r in rs: by[r['gid']].append(r)
        for g in by.values(): rng.shuffle(g)
        groups = list(by.values()); rng.shuffle(groups)
        out = []
        while len(out) < per_class and any(groups):
            for g in groups:
                if g and len(out) < per_class: out.append(g.pop())
        pool += out
        print(f'  {CROPS[key[0]]} 질병코드{key[1]:2d}: 후보 {len(rs):6d}장 / 그룹 {len(by):3d} → 풀 {len(out)}장', flush=True)
    return pool


def _prep_one(args):
    zp_list, r = args
    global _ZIPS
    try: _ZIPS
    except NameError: _ZIPS = {}
    for zp in zp_list:
        if zp not in _ZIPS: _ZIPS[zp] = (zipfile.ZipFile(zp), None)
        z = _ZIPS[zp][0]
        if _ZIPS[zp][1] is None:
            _ZIPS[zp] = (z, {os.path.basename(n.filename): n for n in z.infolist() if not n.is_dir()})
        m = _ZIPS[zp][1].get(r['name'])
        if m is not None: break
    else:
        return None
    im = Image.open(io.BytesIO(z.read(m)))
    raw_w, raw_h = im.size
    orient = im.getexif().get(274, 1)
    im.draft('RGB', (raw_w // 4, raw_h // 4)); im = im.convert('RGB')
    cur_w, cur_h = im.size
    # bbox가 원본 방향 기준인지 회전 적용 후 기준인지: JSON 크기와 맞는 쪽을 쓴다
    raw_frame = (r['w'], r['h']) == (raw_w, raw_h) or orient not in TRANSPOSE
    if not raw_frame and (r['w'], r['h']) != (raw_h, raw_w):
        raw_frame = True
    if not raw_frame:
        im = ImageOps.exif_transpose(im); cur_w, cur_h = im.size
    sx, sy = cur_w / r['w'], cur_h / r['h']
    b = r['box']; x0, y0, x1, y1 = b['xtl'] * sx, b['ytl'] * sy, b['xbr'] * sx, b['ybr'] * sy
    bw, bh = x1 - x0, y1 - y0
    cx0, cy0 = max(0, x0 - 0.25 * bw), max(0, y0 - 0.25 * bh)
    cx1, cy1 = min(cur_w, x1 + 0.25 * bw), min(cur_h, y1 + 0.25 * bh)
    if cx1 - cx0 < 8 or cy1 - cy0 < 8: return None
    crop = im.crop((int(cx0), int(cy0), int(cx1), int(cy1)))
    masked = im.copy(); masked.paste((124, 116, 104), (int(x0), int(y0), int(x1), int(y1)))
    outs = []
    for v in (im, crop, masked):
        if raw_frame and orient in TRANSPOSE: v = v.transpose(TRANSPOSE[orient])
        outs.append(np.asarray(v.resize((SIZE, SIZE), Image.BILINEAR), dtype=np.uint8))
    return outs, r['cls'], r['gid']


def build(pool):
    t = time.time(); tasks = [(r['zips'], r) for r in pool]
    by_zip = collections.defaultdict(list)
    for k, tk in enumerate(tasks): by_zip[tk[0][0] if tk[0] else ''].append(k)
    res = [None] * len(tasks)
    with ProcessPoolExecutor(max_workers=6) as ex:
        futs = {}
        for z, idxs in by_zip.items():
            for k in idxs: futs[k] = ex.submit(_prep_one, tasks[k])
        for k, f in futs.items(): res[k] = f.result()
    ok = [x for x in res if x]
    print(f'전처리 {len(ok)}/{len(pool)}장, {time.time() - t:.0f}초', flush=True)
    X = [np.stack([x[0][v] for x in ok]) for v in range(3)]
    return X, np.array([x[1] for x in ok]), np.array([x[2] for x in ok])


def split_groups(y, g, seed):
    rng = random.Random(seed); test = np.zeros(len(y), bool)
    for c in range(len(CLASSES)):
        gs = sorted(set(g[y == c])); rng.shuffle(gs)
        n_test = max(1, round(0.3 * len(gs)))
        te = set(gs[:n_test]); test |= (y == c) & np.isin(g, list(te))
    return ~test, test


def train_eval(Xv, y, tr, te, seed, epochs=6):
    import torch, torchvision
    torch.manual_seed(seed); torch.backends.cudnn.benchmark = True
    dev = 'cuda'
    m = torchvision.models.efficientnet_b0(weights=torchvision.models.EfficientNet_B0_Weights.IMAGENET1K_V1)
    m.classifier[1] = torch.nn.Linear(1280, len(CLASSES)); m = m.to(dev)
    mean = torch.tensor([0.485, 0.456, 0.406], device=dev).view(1, 3, 1, 1) * 255
    std = torch.tensor([0.229, 0.224, 0.225], device=dev).view(1, 3, 1, 1) * 255
    Xt = torch.from_numpy(Xv).to(dev).permute(0, 3, 1, 2); yt = torch.from_numpy(y).to(dev)
    tri, tei = torch.from_numpy(np.where(tr)[0]).to(dev), torch.from_numpy(np.where(te)[0]).to(dev)
    # 클래스 가중치 (학습셋 기준)
    cnt = torch.bincount(yt[tri], minlength=len(CLASSES)).float().clamp(min=1)
    w = (cnt.sum() / cnt / len(CLASSES))
    opt = torch.optim.AdamW(m.parameters(), 5e-4, weight_decay=1e-4)
    bs = 64; steps = epochs * (len(tri) // bs); sched = torch.optim.lr_scheduler.OneCycleLR(opt, 5e-4, total_steps=steps)
    sc = torch.amp.GradScaler(); step = 0; m.train()
    for ep in range(epochs):
        perm = tri[torch.randperm(len(tri), device=dev)]
        for i in range(0, len(perm) - bs + 1, bs):
            # permute한 텐서는 메모리가 NHWC라 channels_last처럼 동작해 이 PC에서 10배 느려진다 → contiguous로 NCHW를 강제한다
            idx = perm[i:i + bs]; x = Xt[idx].float().contiguous()
            flip = torch.rand(bs, device=dev) < 0.5; x = torch.where(flip.view(-1, 1, 1, 1), x.flip(3), x)
            x = (x * (0.8 + 0.4 * torch.rand(bs, 1, 1, 1, device=dev))).clamp(0, 255)
            with torch.autocast('cuda', dtype=torch.float16):
                loss = torch.nn.functional.cross_entropy(m((x - mean) / std), yt[idx], weight=w)
            opt.zero_grad(set_to_none=True); sc.scale(loss).backward(); sc.step(opt); sc.update(); sched.step()
    m.eval(); preds = []
    with torch.no_grad(), torch.autocast('cuda', dtype=torch.float16):
        for i in range(0, len(tei), 128):
            preds.append(m((Xt[tei[i:i + 128]].float().contiguous() - mean) / std).argmax(1))
    p = torch.cat(preds).cpu().numpy(); t = yt[tei].cpu().numpy()
    f1s = []
    for c in range(len(CLASSES)):
        tp = ((p == c) & (t == c)).sum(); fp = ((p == c) & (t != c)).sum(); fn = ((p != c) & (t == c)).sum()
        f1s.append(2 * tp / max(1, 2 * tp + fp + fn))
    return float((p == t).mean()), float(np.mean(f1s))


if __name__ == '__main__':
    base = sys.argv[1]; per = int(sys.argv[2]) if len(sys.argv) > 2 else 400; n_seed = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    print('라벨 읽기'); recs = load_records(base)
    print('풀 만들기'); pool = pick_pool(recs, per)
    X, y, g = build(pool)
    print('클래스별 장수', np.bincount(y).tolist(), ' 그룹 수', [len(set(g[y == c])) for c in range(len(CLASSES))])
    names = ['A 전체', 'B crop', 'C 배경만']; table = collections.defaultdict(list)
    for s in range(n_seed):
        tr, te = split_groups(y, g, s)
        print(f'[시드 {s}] 학습 {tr.sum()}장 / 시험 {te.sum()}장 (시험 그룹은 학습과 겹치지 않음)', flush=True)
        for v in range(3):
            t0 = time.time(); acc, f1 = train_eval(X[v], y, tr, te, s)
            table[v].append((acc, f1)); print(f'   {names[v]:8s} 정확도 {acc:.3f}  macro-F1 {f1:.3f}  ({time.time() - t0:.0f}초)', flush=True)
    print('\n== 요약 (시험 그룹이 학습과 다른 촬영 대상, 시드 평균 ± 표준편차, 우연 수준 정확도 = 0.111)')
    for v in range(3):
        a = np.array(table[v])
        print(f'{names[v]:8s} 정확도 {a[:, 0].mean():.3f} ± {a[:, 0].std():.3f}   macro-F1 {a[:, 1].mean():.3f} ± {a[:, 1].std():.3f}')
