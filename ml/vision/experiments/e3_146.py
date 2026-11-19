"""146 F3 전략 시험: 153·147의 전략(bbox crop + 배경 교체 증강)이 146(사과·배)에도 맞는지 단서 충돌로 확인한다.
작물 2종(사과 6클래스·배 3클래스 = 9클래스), 클래스당 최대 400장, EfficientNet-B0 224px 6 epoch, 시험은 학습과 겹치지 않는 묶음.

  part1 (입력 변형): full / crop25 / crop0 / bgonly(bbox를 회색으로 가림) / boxshape(이미지 없이 bbox 위치·크기만 그린 대조군)
  part2 (학습 방식 × 단서 충돌): crop25 / mix / crop25+swap / mix+swap, 시험은 clean@0/25/50 + conflict@25/50.
         충돌은 잎 종류별로 나눠 센다: (질병 잎 → 정상 배경), (정상 잎 → 질병 배경), (병 → 다른 병 배경)

실행 (ml/vision에서): .venv/Scripts/python.exe -I -X utf8 experiments/e3_146.py <part1|part2|all> [시드 수=3]
출력: ../../docs/vision-146-f3/*.json, *.log. 캐시: data/review/146/e3_cache.npz (git 제외 폴더)
"""
import collections, csv, io, json, math, os, random, sys, time, zipfile
from concurrent.futures import ProcessPoolExecutor

import numpy as np
from PIL import Image, ImageOps

ROOT = 'data/raw/146/과수화상병 촬영 이미지'
CACHE = 'data/review/146/e3_cache.npz'
OUT = '../../docs/vision-146-f3'
SIZE = 224
USE = {'사과': {'3', '4', '5', '6', '7'}, '배': {'1', '2'}}
CAP = 400
CLASSES = []   # (작물, 질병코드 str, '0'은 정상)
for c, ds in USE.items():
    CLASSES.append((c, '0'))
    for d in sorted(ds, key=int): CLASSES.append((c, d))
CLS_IDX = {k: i for i, k in enumerate(CLASSES)}
CROP_OF = np.array([c for c, _ in CLASSES])
IS_NORMAL = np.array([d == '0' for _, d in CLASSES])
GRAY = (124, 116, 104)
ORIENT = {5, 6, 7, 8}


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


def records():
    """이상 라벨(코드·risk·type 불일치)·규칙 밖 파일명 제외. 정상은 질병 사진과 같은 부위(질병의 5% 이상 부위)만."""
    R = list(csv.DictReader(open('data/review/146/labels.csv', encoding='utf-8')))
    idx = index_images(); rng = random.Random(0); by = collections.defaultdict(lambda: collections.defaultdict(list))
    ok = []
    for r in R:
        c = r['zip_crop']; dis = r['zip_kind'] == '질병'
        if str(int(r['fdis'])) != r['disease'] or r['risk'] != r['frisk']: continue
        if dis and (r['disease'] not in USE[c] or r['risk'] in ('', '0')): continue
        if not dis and (r['disease'] != '0' or r['risk'] != '0' or r['type'] == '1' or r['region']): continue
        if not (len(r['fdate']) == 8 and r['fdate'].isdigit()) or r['image'] not in idx: continue
        ok.append(r)
    area_cnt = collections.defaultdict(collections.Counter)
    for r in ok:
        if r['zip_kind'] == '질병': area_cnt[r['zip_crop']][r['farea']] += 1
    areas = {c: {a for a, n in cnt.items() if n / sum(cnt.values()) >= 0.05} for c, cnt in area_cnt.items()}
    for r in ok:
        c = r['zip_crop']; d = r['disease'] if r['zip_kind'] == '질병' else '0'
        if r['farea'] not in areas[c]: continue
        g = r['gid'] + '|' + r['fdate'] if d == '0' else r['gid']
        zp, member = idx[r['image']]
        by[(c, d)][g].append(dict(split='', crop=c, kind=r['zip_kind'], name=r['image'], gid=g, cls=CLS_IDX[(c, d)], zp=zp, member=member,
                                  box=[int(r['xtl']), int(r['ytl']), int(r['xbr']), int(r['ybr'])]))
    pool = []
    for k, gs in by.items():
        keys = sorted(gs); rng.shuffle(keys)
        for g in keys: rng.shuffle(gs[g])
        sel, i = [], 0
        while len(sel) < CAP and any(gs[g] for g in keys):   # 묶음을 돌아가며 뽑는다
            g = keys[i % len(keys)]
            if gs[g]: sel.append(gs[g].pop())
            i += 1
        pool += sel
    return pool


_Z = {}


def prep(r):
    z = _Z.get(r['zp']) or _Z.setdefault(r['zp'], zipfile.ZipFile(r['zp'])); b = z.read(r['member'])
    im = Image.open(io.BytesIO(b)); rw, rh = im.size; orient = im.getexif().get(274, 1)
    fw, fh = (rh, rw) if orient in ORIENT else (rw, rh)          # 회전 뒤 원래 크기
    im.draft('RGB', (rw // 4, rh // 4)); im = ImageOps.exif_transpose(im.convert('RGB')) if orient in ORIENT else im.convert('RGB')
    cw, ch = im.size; sx, sy = cw / fw, ch / fh
    x0, y0, x1, y1 = r['box']; x0, x1 = x0 * sx, x1 * sx; y0, y1 = y0 * sy, y1 * sy
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(cw, x1), min(ch, y1)
    bw, bh = x1 - x0, y1 - y0
    if bw < 8 or bh < 8: return None

    def crop(m):
        return im.crop((int(max(0, x0 - m * bw)), int(max(0, y0 - m * bh)), int(min(cw, x1 + m * bw)), int(min(ch, y1 + m * bh))))
    masked = im.copy(); masked.paste(GRAY, (int(x0), int(y0), int(x1), int(y1)))
    outs = [np.asarray(v.resize((SIZE, SIZE), Image.BILINEAR), dtype=np.uint8) for v in (im, crop(0.25), crop(0.0), masked)]
    box = [int(x0 / cw * SIZE), int(y0 / ch * SIZE), max(int(x0 / cw * SIZE) + 2, int(x1 / cw * SIZE)), max(int(y0 / ch * SIZE) + 2, int(y1 / ch * SIZE))]
    ob = bool(orient in ORIENT)
    return outs, box, ob


def build():
    if os.path.exists(CACHE):
        d = np.load(CACHE, allow_pickle=True); print('캐시 사용', flush=True)
        return [d[f'X{v}'] for v in range(4)], d['boxes'], d['y'], d['g']
    pool = records(); t = time.time()
    pool.sort(key=lambda p: (p['zp'], p['member']))
    with ProcessPoolExecutor(max_workers=8) as ex: res = list(ex.map(prep, pool, chunksize=16))
    ok = [(p, x) for p, x in zip(pool, res) if x]
    print(f'전처리 {len(ok)}/{len(pool)}장 {time.time() - t:.0f}초, EXIF 회전 {sum(x[2] for _, x in ok)}장', flush=True)
    X = [np.stack([x[0][v] for _, x in ok]) for v in range(4)]
    boxes = np.array([x[1] for _, x in ok]); y = np.array([p['cls'] for p, _ in ok]); g = np.array([p['gid'] for p, _ in ok])
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    np.savez(CACHE, X0=X[0], X1=X[1], X2=X[2], X3=X[3], boxes=boxes, y=y, g=g)
    return X, boxes, y, g


def split_groups(y, g, seed):
    """묶음 단위 분할. 같은 작물에서 병 클래스가 대상ID를 공유하므로 작물 안에서 한 번 정한 배정을 재사용한다."""
    rng = random.Random(seed); side = {}; test = np.zeros(len(y), bool)
    for c in range(len(CLASSES)):
        gs = sorted(set(g[y == c])); rng.shuffle(gs)
        want = max(1, round(0.3 * len(gs))); have = sum(1 for x in gs if side.get((CROP_OF[c], x)) == 'te')
        for x in gs:
            if have >= want: break
            if (CROP_OF[c], x) not in side: side[(CROP_OF[c], x)] = 'te'; have += 1
        if have == 0: side[(CROP_OF[c], gs[0])] = 'te'
        for x in gs: side.setdefault((CROP_OF[c], x), 'tr')
        for i in np.where(y == c)[0]: test[i] = side[(CROP_OF[c], g[i])] == 'te'
    return ~test, test


def cropr(img, box, m):
    x0, y0, x1, y1 = box; w, h = x1 - x0, y1 - y0
    c = img[max(0, int(y0 - m * h)):min(SIZE, int(y1 + m * h)), max(0, int(x0 - m * w)):min(SIZE, int(x1 + m * w))]
    return np.asarray(Image.fromarray(c).resize((SIZE, SIZE), Image.BILINEAR))


def composite(leaf, bg, box):
    x0, y0, x1, y1 = box; out = bg.copy()
    out[y0:y1, x0:x1] = np.asarray(Image.fromarray(leaf).resize((x1 - x0, y1 - y0), Image.BILINEAR)); return out


def boxshape(boxes):
    out = np.full((len(boxes), SIZE, SIZE, 3), 40, np.uint8)
    for i, (x0, y0, x1, y1) in enumerate(boxes): out[i, y0:y1, x0:x1] = 220
    return out


def train_logits(Xall, yall, tr, te, seed, epochs=6):
    import torch, torchvision
    torch.manual_seed(seed); torch.backends.cudnn.benchmark = True; dev = 'cuda'; nc = len(CLASSES)
    m = torchvision.models.efficientnet_b0(weights=torchvision.models.EfficientNet_B0_Weights.IMAGENET1K_V1)
    m.classifier[1] = torch.nn.Linear(1280, nc); m = m.to(dev)
    mean = torch.tensor([0.485, 0.456, 0.406], device=dev).view(1, 3, 1, 1) * 255
    std = torch.tensor([0.229, 0.224, 0.225], device=dev).view(1, 3, 1, 1) * 255
    Xt = torch.from_numpy(Xall).to(dev).permute(0, 3, 1, 2); yt = torch.from_numpy(yall).to(dev)
    tri, tei = torch.from_numpy(np.where(tr)[0]).to(dev), torch.from_numpy(np.where(te)[0]).to(dev)
    cnt = torch.bincount(yt[tri], minlength=nc).float().clamp(min=1); w = cnt.sum() / cnt / nc
    opt = torch.optim.AdamW(m.parameters(), 5e-4, weight_decay=1e-4)
    bs = 64; steps = epochs * (len(tri) // bs); sched = torch.optim.lr_scheduler.OneCycleLR(opt, 5e-4, total_steps=steps)
    sc = torch.amp.GradScaler(); m.train()
    for _ in range(epochs):
        perm = tri[torch.randperm(len(tri), device=dev)]
        for i in range(0, len(perm) - bs + 1, bs):
            idx = perm[i:i + bs]; x = Xt[idx].float().contiguous()     # contiguous 필수, channels_last 금지
            flip = torch.rand(bs, device=dev) < 0.5; x = torch.where(flip.view(-1, 1, 1, 1), x.flip(3), x)
            x = (x * (0.8 + 0.4 * torch.rand(bs, 1, 1, 1, device=dev))).clamp(0, 255)
            with torch.autocast('cuda', dtype=torch.float16):
                loss = torch.nn.functional.cross_entropy(m((x - mean) / std), yt[idx], weight=w)
            opt.zero_grad(set_to_none=True); sc.scale(loss).backward(); sc.step(opt); sc.update(); sched.step()
    m.eval(); out = []
    with torch.no_grad(), torch.autocast('cuda', dtype=torch.float16):
        for i in range(0, len(tei), 128): out.append(m((Xt[tei[i:i + 128]].float().contiguous() - mean) / std).float())
    return torch.cat(out).cpu().numpy()


def mpred(lg, yt):
    keep = CROP_OF[None, :] == CROP_OF[yt][:, None]
    return np.where(keep, lg, -1e9).argmax(1), keep


def f1(p, t):
    f = []
    for c in range(len(CLASSES)):
        tp = ((p == c) & (t == c)).sum(); fp = ((p == c) & (t != c)).sum(); fn = ((p != c) & (t == c)).sum(); f.append(2 * tp / max(1, 2 * tp + fp + fn))
    return float(np.mean(f))


def scores(lg, yt):
    p, keep = mpred(lg, yt); r = dict(acc_mask=float((p == yt).mean()), f1_mask=f1(p, yt))
    dis = ~IS_NORMAL[yt]; p2 = np.where(keep & ~IS_NORMAL[None, :], lg, -1e9).argmax(1)
    r['dis2'] = float((p2[dis] == yt[dis]).mean())            # 병 사진만, 같은 작물의 병끼리 (병 1종인 토마토는 항상 맞아서 제외)
    multi = np.array([sum(1 for k in CLASSES if k[0] == c and k[1] != '0') > 1 for c in CROP_OF[yt]])
    r['dis_multi'] = float((p2[dis & multi] == yt[dis & multi]).mean())
    pn = IS_NORMAL[p]; tn = IS_NORMAL[yt]
    r['normal_vs_disease'] = float((pn == tn).mean())          # 정상/질병 이분 정확도
    r['per_crop'] = {c: float((p[CROP_OF[yt] == c] == yt[CROP_OF[yt] == c]).mean()) for c in USE}
    return r


def part1(X, boxes, y, g, n_seed, log):
    BS = boxshape(boxes); res = []; V = {'full': X[0], 'crop25': X[1], 'crop0': X[2], 'bgonly': X[3], 'boxshape': BS}
    for s in range(n_seed):
        tr, te = split_groups(y, g, s)
        for vn, Xv in V.items():
            t0 = time.time(); lg = train_logits(Xv, y, tr, te, s)[:]; r = dict(seed=s, variant=vn, n_train=int(tr.sum()), n_test=int(te.sum()), **scores(lg, y[te])); res.append(r)
            log(f"[p1 seed {s}] {vn:8s} mask {r['acc_mask']:.3f} f1 {r['f1_mask']:.3f} 정상/병 {r['normal_vs_disease']:.3f} 병끼리(2종 이상) {r['dis_multi']:.3f} | " + ' '.join(f'{c[:2]} {v:.2f}' for c, v in r['per_crop'].items()) + f' ({time.time() - t0:.0f}s)')
            json.dump(res, open(f'{OUT}/part1_results.json', 'w'), ensure_ascii=False)


def conflicts(X, y, boxes, idx, seed, margins, per=2):
    rng = random.Random(seed); sets = {m: [] for m in margins}; ya, yb = [], []
    for i in idx:
        cands = [j for j in idx if CROP_OF[y[j]] == CROP_OF[y[i]] and y[j] != y[i]]
        for j in rng.sample(cands, min(per, len(cands))):
            comp = composite(X[2][i], X[0][j], boxes[j])
            for m in margins: sets[m].append(cropr(comp, boxes[j], m))
            ya.append(y[i]); yb.append(y[j])
    return {m: np.stack(v) for m, v in sets.items()}, np.array(ya), np.array(yb)


def part2(X, boxes, y, g, n_seed, log):
    res = []
    for s in range(n_seed):
        tr, te = split_groups(y, g, s); tr_idx, te_idx = np.where(tr)[0], np.where(te)[0]; yt = y[te_idx]
        evals = {f'clean@{int(m * 100)}': np.stack([cropr(X[0][i], boxes[i], m) for i in te_idx]) for m in (0.0, 0.25, 0.5)}
        cf, ya, yb = conflicts(X, y, boxes, te_idx, s, (0.25, 0.5))
        for m, a in cf.items(): evals[f'conflict@{int(m * 100)}'] = a
        rng = random.Random(s + 100); sw, swy = [], []
        for i in tr_idx:
            j = rng.choice(tr_idx); sw.append(cropr(composite(X[2][i], X[0][j], boxes[j]), boxes[j], 0.25)); swy.append(y[i])
        sw, swy = np.stack(sw), np.array(swy); c25, c0, ytr = X[1][tr_idx], X[2][tr_idx], y[tr_idx]
        sets = {'crop25': (c25, ytr), 'mix': (np.concatenate([c0, c25]), np.concatenate([ytr, ytr])),
                'crop25+swap': (np.concatenate([c25, sw]), np.concatenate([ytr, swy])), 'mix+swap': (np.concatenate([c0, c25, sw]), np.concatenate([ytr, ytr, swy]))}
        kind = lambda a, b: ('병잎→정상배경' if (not IS_NORMAL[a]) and IS_NORMAL[b] else '정상잎→병배경' if IS_NORMAL[a] and not IS_NORMAL[b] else '병잎→다른병배경')
        ktype = np.array([kind(a, b) for a, b in zip(ya, yb)])
        for name, (tx, ty) in sets.items():
            t0 = time.time(); names = list(evals); sizes = [len(evals[k]) for k in names]
            Xall = np.concatenate([tx] + [evals[k] for k in names]); yall = np.concatenate([ty, np.zeros(sum(sizes), int)])
            trm = np.zeros(len(Xall), bool); trm[:len(tx)] = True
            lg = train_logits(Xall, yall, trm, ~trm, s); out, k = {}, 0
            for nm, n in zip(names, sizes): out[nm] = lg[k:k + n]; k += n
            r = dict(seed=s, model=name)
            for m in ('clean@0', 'clean@25', 'clean@50'): r[m] = scores(out[m], yt)['acc_mask']; r[m + '_nd'] = scores(out[m], yt)['normal_vs_disease']
            for m in ('conflict@25', 'conflict@50'):
                p, _ = mpred(out[m], ya); r[m + '_leaf'] = float((p == ya).mean()); r[m + '_bg'] = float((p == yb).mean())
                for kt in set(ktype): sel = ktype == kt; r[f'{m}_{kt}_leaf'] = float((p[sel] == ya[sel]).mean()); r[f'{m}_{kt}_bg'] = float((p[sel] == yb[sel]).mean()); r[f'{m}_{kt}_n'] = int(sel.sum())
            res.append(r)
            log(f"[p2 seed {s}] {name:12s} clean 0/25/50 {r['clean@0']:.3f}/{r['clean@25']:.3f}/{r['clean@50']:.3f} | 충돌@25 잎 {r['conflict@25_leaf']:.3f} 배경 {r['conflict@25_bg']:.3f} | @50 잎 {r['conflict@50_leaf']:.3f} 배경 {r['conflict@50_bg']:.3f} ({time.time() - t0:.0f}s)")
            json.dump(res, open(f'{OUT}/part2_results.json', 'w'), ensure_ascii=False)
        if s == 0:
            ids = random.Random(3).sample(range(len(ya)), 6)
            Image.fromarray(np.concatenate([np.concatenate([cf[0.25][i], cf[0.5][i]], 1) for i in ids], 0)).save(f'{OUT}/conflict_samples.jpg', quality=88)


if __name__ == '__main__':
    what = sys.argv[1]; n_seed = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    os.makedirs(OUT, exist_ok=True); lf = open(f'{OUT}/run_{what}.log', 'a', encoding='utf-8')

    def log(m):
        print(m, flush=True); lf.write(m + '\n'); lf.flush()
    X, boxes, y, g = build()
    log('클래스별 장수 ' + str(dict(zip([f'{c[:2]}{d}' for c, d in CLASSES], np.bincount(y, minlength=len(CLASSES)).tolist()))))
    log('묶음 수 ' + str([len(set(g[y == c])) for c in range(len(CLASSES))]))
    if what in ('part1', 'all'): part1(X, boxes, y, g, n_seed, log)
    if what in ('part2', 'all'): part2(X, boxes, y, g, n_seed, log)
    log('끝')
