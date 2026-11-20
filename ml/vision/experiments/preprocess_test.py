"""전처리 방식 비교 + "이 시험이 믿을 만한가" 검증 (153, 작물 3종 9클래스).

입력 변형 (같은 이미지에서 만든다)
  full    : 이미지 전체
  crop25  : bbox를 25% 넓혀 자름 (현재 규격)
  crop0   : bbox 그대로 자름 (여백 없음)
  bgonly  : bbox 영역을 회색으로 가림 (잎 없이 맞히면 배경 단서가 있다는 뜻, 통제용)

점수
  acc9      : 9클래스 정확도 (품목 마스킹 없음)
  acc_mask  : 정답 작물의 클래스만 남기고 고른 정확도 (서비스와 같은 조건)
  f1_mask   : 위와 같은 조건의 macro-F1
  dis2      : 병 사진만, 같은 작물의 병 2개 중 맞힌 비율 (정상 사진은 출처가 달라 쉬우니 뺀 값, 우연=0.5)

신뢰도 확인: 풀 크기(클래스당 장수)와 시드(분할)를 바꿔 가며 점수가 안정적인지, 변형 간 차이가 분할 편차보다 큰지 본다.

실행: python -X utf8 preprocess_test.py <153 01.데이터 폴더> <결과 폴더> [시드 수=6] [풀 크기들=150,300,600]
"""
import collections, io, json, os, random, sys, time, zipfile
from concurrent.futures import ProcessPoolExecutor

import numpy as np
from PIL import Image, ImageOps

sys.path.insert(0, os.path.dirname(__file__))
from crop_ablation import CROPS, CLASSES, CLS_IDX, TRANSPOSE, load_records, pick_pool  # noqa: E402

SIZE = 224
VARIANTS = ['full', 'crop25', 'crop0', 'bgonly']
CROP_OF = np.array([c for c, _ in CLASSES])           # 클래스 → 작물
IS_NORMAL = np.array([d == 0 for _, d in CLASSES])


def _prep_one(args):
    zp_list, r = args
    global _ZIPS
    try: _ZIPS
    except NameError: _ZIPS = {}
    for zp in zp_list:
        if zp not in _ZIPS:
            z = zipfile.ZipFile(zp); _ZIPS[zp] = (z, {os.path.basename(n.filename): n for n in z.infolist() if not n.is_dir()})
        z, idx = _ZIPS[zp]
        m = idx.get(r['name'])
        if m is not None: break
    else:
        return None
    im = Image.open(io.BytesIO(z.read(m)))
    raw_w, raw_h = im.size; orient = im.getexif().get(274, 1)
    im.draft('RGB', (raw_w // 4, raw_h // 4)); im = im.convert('RGB')
    cur_w, cur_h = im.size
    raw_frame = (r['w'], r['h']) == (raw_w, raw_h) or orient not in TRANSPOSE
    if not raw_frame and (r['w'], r['h']) != (raw_h, raw_w): raw_frame = True
    if not raw_frame:
        im = ImageOps.exif_transpose(im); cur_w, cur_h = im.size
    sx, sy = cur_w / r['w'], cur_h / r['h']
    b = r['box']; x0, y0, x1, y1 = b['xtl'] * sx, b['ytl'] * sy, b['xbr'] * sx, b['ybr'] * sy
    bw, bh = x1 - x0, y1 - y0
    if bw < 8 or bh < 8: return None

    def crop(m_):
        return im.crop((int(max(0, x0 - m_ * bw)), int(max(0, y0 - m_ * bh)), int(min(cur_w, x1 + m_ * bw)), int(min(cur_h, y1 + m_ * bh))))
    masked = im.copy(); masked.paste((124, 116, 104), (int(x0), int(y0), int(x1), int(y1)))
    outs = []
    for v in (im, crop(0.25), crop(0.0), masked):
        if raw_frame and orient in TRANSPOSE: v = v.transpose(TRANSPOSE[orient])
        outs.append(np.asarray(v.resize((SIZE, SIZE), Image.BILINEAR), dtype=np.uint8))
    return outs, r['cls'], r['gid'], r['name']


def build(pool):
    t = time.time(); tasks = [(r['zips'], r) for r in pool]
    with ProcessPoolExecutor(max_workers=8) as ex:
        res = list(ex.map(_prep_one, tasks, chunksize=16))
    ok = [x for x in res if x]
    print(f'전처리 {len(ok)}/{len(pool)}장, {time.time() - t:.0f}초', flush=True)
    X = [np.stack([x[0][v] for x in ok]) for v in range(len(VARIANTS))]
    return X, np.array([x[1] for x in ok]), np.array([x[2] for x in ok]), [x[3] for x in ok]


def split_groups(y, g, seed):
    rng = random.Random(seed); test = np.zeros(len(y), bool)
    for c in range(len(CLASSES)):
        gs = sorted(set(g[y == c])); rng.shuffle(gs)
        te = set(gs[:max(1, round(0.3 * len(gs)))]); test |= (y == c) & np.isin(g, list(te))
    return ~test, test


def train_logits(Xv, y, tr, te, seed, epochs=6):
    import torch, torchvision
    torch.manual_seed(seed); torch.backends.cudnn.benchmark = True; dev = 'cuda'
    m = torchvision.models.efficientnet_b0(weights=torchvision.models.EfficientNet_B0_Weights.IMAGENET1K_V1)
    m.classifier[1] = torch.nn.Linear(1280, len(CLASSES)); m = m.to(dev)
    mean = torch.tensor([0.485, 0.456, 0.406], device=dev).view(1, 3, 1, 1) * 255
    std = torch.tensor([0.229, 0.224, 0.225], device=dev).view(1, 3, 1, 1) * 255
    Xt = torch.from_numpy(Xv).to(dev).permute(0, 3, 1, 2); yt = torch.from_numpy(y).to(dev)
    tri, tei = torch.from_numpy(np.where(tr)[0]).to(dev), torch.from_numpy(np.where(te)[0]).to(dev)
    cnt = torch.bincount(yt[tri], minlength=len(CLASSES)).float().clamp(min=1); w = cnt.sum() / cnt / len(CLASSES)
    opt = torch.optim.AdamW(m.parameters(), 5e-4, weight_decay=1e-4)
    bs = 64; steps = epochs * (len(tri) // bs); sched = torch.optim.lr_scheduler.OneCycleLR(opt, 5e-4, total_steps=steps)
    sc = torch.amp.GradScaler(); m.train()
    for _ in range(epochs):
        perm = tri[torch.randperm(len(tri), device=dev)]
        for i in range(0, len(perm) - bs + 1, bs):
            idx = perm[i:i + bs]; x = Xt[idx].float().contiguous()   # contiguous 필수 (NHWC면 10배 느림)
            flip = torch.rand(bs, device=dev) < 0.5; x = torch.where(flip.view(-1, 1, 1, 1), x.flip(3), x)
            x = (x * (0.8 + 0.4 * torch.rand(bs, 1, 1, 1, device=dev))).clamp(0, 255)
            with torch.autocast('cuda', dtype=torch.float16):
                loss = torch.nn.functional.cross_entropy(m((x - mean) / std), yt[idx], weight=w)
            opt.zero_grad(set_to_none=True); sc.scale(loss).backward(); sc.step(opt); sc.update(); sched.step()
    m.eval(); out = []
    with torch.no_grad(), torch.autocast('cuda', dtype=torch.float16):
        for i in range(0, len(tei), 128):
            out.append(m((Xt[tei[i:i + 128]].float().contiguous() - mean) / std).float())
    return torch.cat(out).cpu().numpy(), y[te]


def macro_f1(p, t, classes):
    f = []
    for c in classes:
        tp = ((p == c) & (t == c)).sum(); fp = ((p == c) & (t != c)).sum(); fn = ((p != c) & (t == c)).sum()
        f.append(2 * tp / max(1, 2 * tp + fp + fn))
    return float(np.mean(f))


def scores(logits, t):
    acc9 = float((logits.argmax(1) == t).mean())
    # 품목 마스킹: 정답 작물의 클래스만 남긴다
    keep = CROP_OF[None, :] == CROP_OF[t][:, None]
    pm = np.where(keep, logits, -1e9).argmax(1)
    # 병끼리: 병 사진만, 같은 작물의 병 클래스만 남긴다
    dis = ~IS_NORMAL[t]; keep2 = keep & ~IS_NORMAL[None, :]
    p2 = np.where(keep2, logits, -1e9).argmax(1)
    return dict(acc9=acc9, acc_mask=float((pm == t).mean()), f1_mask=macro_f1(pm, t, range(len(CLASSES))),
                dis2=float((p2[dis] == t[dis]).mean()))


def sample_sheet(X, y, names, out_dir, per_crop=3):
    """변형별 예시 이미지 (눈으로 확인용). 행=샘플, 열=변형."""
    os.makedirs(out_dir, exist_ok=True)
    rng = random.Random(1)
    for c_idx, (crop, dis) in enumerate(CLASSES):
        if dis == 0: continue
        ids = [i for i in range(len(y)) if y[i] == c_idx]; rng.shuffle(ids); ids = ids[:per_crop]
        rows = [np.concatenate([X[v][i] for v in range(len(VARIANTS))], axis=1) for i in ids]
        Image.fromarray(np.concatenate(rows, axis=0)).save(f'{out_dir}/samples_{CROPS[crop]}_{dis}.jpg', quality=88)


if __name__ == '__main__':
    base, out = sys.argv[1], sys.argv[2]
    n_seed = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    sizes = [int(s) for s in (sys.argv[4] if len(sys.argv) > 4 else '150,300,600').split(',')]
    os.makedirs(out, exist_ok=True)
    print('라벨 읽기'); recs = load_records(base)
    print('풀 만들기'); pool = pick_pool(recs, max(sizes))
    X, y, g, names = build(pool)
    ginfo = [len(set(g[y == c])) for c in range(len(CLASSES))]
    print('클래스별 장수', np.bincount(y).tolist(), ' 그룹 수', ginfo, flush=True)
    sample_sheet(X, y, names, out)
    # 클래스마다 "그룹 돌려 뽑은 순서"의 앞 n장 = 크기 n의 풀
    rank = np.zeros(len(y), int)
    for c in range(len(CLASSES)):
        idx = np.where(y == c)[0]; rank[idx] = np.arange(len(idx))
    results = []; t_all = time.time()
    for n in sizes:
        sel = rank < n
        ys, gs = y[sel], g[sel]
        for s in range(n_seed):
            tr, te = split_groups(ys, gs, s)
            tg = [len(set(gs[te & (ys == c)])) for c in range(len(CLASSES))]
            for v, vn in enumerate(VARIANTS):
                t0 = time.time(); lg, tt = train_logits(X[v][sel], ys, tr, te, s)
                r = dict(size=n, seed=s, variant=vn, n_train=int(tr.sum()), n_test=int(te.sum()), test_groups=tg, **scores(lg, tt))
                results.append(r)
                print(f"[n={n} seed={s}] {vn:7s} acc9 {r['acc9']:.3f} mask {r['acc_mask']:.3f} f1 {r['f1_mask']:.3f} dis2 {r['dis2']:.3f}  ({time.time() - t0:.0f}s, 누적 {(time.time() - t_all) / 60:.0f}분)", flush=True)
                json.dump(dict(group_counts=ginfo, results=results), open(f'{out}/results.json', 'w'), ensure_ascii=False)
    print('끝')
