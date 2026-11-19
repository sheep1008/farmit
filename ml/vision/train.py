"""사진 진단 학습 (S8): EfficientNet-B0, 384px, AMP, 클래스 가중치.

  python -X utf8 train.py --processed data/processed/153 [data/processed/147 ...] --out runs/s8_153 [--epochs 12]
  python -X utf8 train.py --processed data/processed/153 --out runs/smoke --smoke     # 코드 확인용 (작은 표본, 2 epoch)

입력 규격 (docs/vision.md 5장, docs/vision-preprocess-test.md 6장)
  - 전처리 결과(512px crop, bbox 25% 여백)에서 **여백을 0~25%로 무작위** 줄여 자르고 384x384로 맞춘다. 이미지 전체는 쓰지 않는다.
  - **배경 교체 증강**: 확률 1/3로 (원본 2 : 합성 1) 잎(bbox 안쪽)을 다른 학습 이미지(작물·클래스 상관없음)의 bbox 자리에 붙인다. 정답은 잎의 클래스.
  - 색·밝기·흐림·JPEG 압축·크기·회전·뒤집기 증강.
  - 이 PC에서 `channels_last`는 10배 느리다 → 쓰지 않는다. 입력 텐서에는 `.contiguous()`를 쓴다.
평가 (시험 분할, 학습에 쓰지 않은 대상ID·묶음)
  - 품목 마스킹(정답 작물의 클래스만 남기고 고름) 정확도·macro F1, 작물별 macro F1, 혼동행렬
  - 단서 충돌 시험 (experiments/cue_conflict_test.py 방식): 시험 이미지 A의 잎을 같은 작물·다른 클래스 이미지 B의 배경에 붙여 정답이 A인지 B인지 본다.
    일반 정확도만으로 판단하지 않는다. 시험 배경은 시험 분할에서만 가져온다.
"""
import argparse, collections, csv, io, json, os, random, time

import numpy as np
from PIL import Image, ImageFilter

SIZE = 384
MARGIN_MAX = 0.25
SWAP_P = 1 / 3
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)


# ------------------------------------------------------------------ 데이터
def load_manifests(dirs, limit_per_class=0, seed=0):
    rows = []
    for d in dirs:
        with open(os.path.join(d, 'manifest.csv'), encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                r['abs'] = os.path.join(d, r['path']); r['box'] = (int(r['bx0']), int(r['by0']), int(r['bx1']), int(r['by1'])); rows.append(r)
    if limit_per_class:    # 코드 확인용: 분할마다 클래스당 최대 N장
        rng = random.Random(seed); by = collections.defaultdict(list)
        for r in rows: by[(r['label'], r['split'])].append(r)
        rows = [r for k in sorted(by) for r in rng.sample(by[k], min(limit_per_class, len(by[k])))]
    labels = sorted({r['label'] for r in rows})
    cls_idx = {l: i for i, l in enumerate(labels)}
    crop_of = {}
    for r in rows: crop_of[cls_idx[r['label']]] = r['crop_name']      # 시설·노지 데이터셋이 달라도 같은 작물이면 같은 품목
    crops = sorted(set(crop_of.values())); crop_id = {c: i for i, c in enumerate(crops)}
    for r in rows: r['y'] = cls_idx[r['label']]
    return rows, labels, np.array([crop_id[crop_of[i]] for i in range(len(labels))]), crops


def crop_margin(img, box, m):
    """bbox를 사방 m(bbox 크기 비율)만큼 넓혀 자른다 (이미지 밖은 자름)."""
    x0, y0, x1, y1 = box; bw, bh = x1 - x0, y1 - y0
    return img.crop((int(max(0, x0 - m * bw)), int(max(0, y0 - m * bh)), int(min(img.width, x1 + m * bw)), int(min(img.height, y1 + m * bh))))


def swap_bg(leaf_img, leaf_box, bg_img, bg_box):
    """leaf_img의 잎(bbox 안쪽)을 bg_img의 bbox 자리에 붙인다. 붙인 이미지와 bbox(= bg_box)를 돌려준다."""
    out = bg_img.copy(); x0, y0, x1, y1 = bg_box
    out.paste(leaf_img.crop(leaf_box).resize((x1 - x0, y1 - y0), Image.BILINEAR), (x0, y0))
    return out


def valid_box(box): return box[2] - box[0] >= 8 and box[3] - box[1] >= 8


def to_tensor_u8(img):
    import torch
    return torch.from_numpy(np.asarray(img.convert('RGB').resize((SIZE, SIZE), Image.BILINEAR), dtype=np.uint8).copy()).permute(2, 0, 1).contiguous()


def augment(img, rng):
    """색·밝기·흐림·JPEG 압축·크기·회전·뒤집기 (PIL, CPU 작업자에서)."""
    from PIL import ImageEnhance
    if rng.random() < 0.5: img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if rng.random() < 0.2: img = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    ang = rng.uniform(-20, 20); sc = rng.uniform(0.85, 1.15)
    if abs(ang) > 1 or abs(sc - 1) > 0.02:
        w, h = img.size; m = (img.getpixel((0, 0)))                       # 회전 후 빈 곳은 가장자리 색
        big = img.resize((max(1, int(w * sc)), max(1, int(h * sc))), Image.BILINEAR).rotate(ang, resample=Image.BILINEAR, fillcolor=m)
        img = big.resize((w, h), Image.BILINEAR) if big.size != (w, h) else big
    for E, lo, hi in ((ImageEnhance.Brightness, 0.7, 1.3), (ImageEnhance.Contrast, 0.7, 1.3), (ImageEnhance.Color, 0.7, 1.3)):
        img = E(img).enhance(rng.uniform(lo, hi))
    if rng.random() < 0.25: img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 1.8)))
    if rng.random() < 0.3:
        buf = io.BytesIO(); img.save(buf, 'JPEG', quality=rng.randint(35, 90)); img = Image.open(io.BytesIO(buf.getvalue())).convert('RGB')
    return img


class TrainSet:
    """매 항목: 여백 0~25% 무작위 crop. 확률 1/3로 배경 교체 합성 (정답은 잎의 클래스)."""
    def __init__(self, rows, seed=0): self.rows = rows; self.seed = seed
    def __len__(self): return len(self.rows)

    def __getitem__(self, i):
        rng = random.Random(f'{self.seed}-{i}-{time.time_ns()}')
        r = self.rows[i]; img = Image.open(r['abs']).convert('RGB'); box = r['box']
        if rng.random() < SWAP_P:
            for _ in range(5):
                b = self.rows[rng.randrange(len(self.rows))]
                if valid_box(b['box']): break
            img = swap_bg(img, box, Image.open(b['abs']).convert('RGB'), b['box']); box = b['box']
        img = crop_margin(img, box, rng.uniform(0, MARGIN_MAX))
        return to_tensor_u8(augment(img, rng)), r['y']


class EvalSet:
    """고정 입력. mode='clean': 합성 없음, 여백 m. mode='conflict': 잎 A를 같은 작물·다른 클래스 B의 배경에 붙임(정답 A), 여백 m. 반환: (이미지, 정답 A, 배경 클래스 B)"""
    def __init__(self, rows, crop_of_cls, margin, mode='clean', seed=0, per_sample=2):
        self.items = []; self.margin = margin; self.rows = rows
        if mode == 'clean':
            self.items = [(i, None) for i in range(len(rows))]
        else:
            rng = random.Random(seed); by = collections.defaultdict(list)
            for j, r in enumerate(rows):
                if valid_box(r['box']): by[crop_of_cls[r['y']]].append(j)
            for i, r in enumerate(rows):
                cands = [j for j in by[crop_of_cls[r['y']]] if rows[j]['y'] != r['y']]
                self.items += [(i, j) for j in rng.sample(cands, min(per_sample, len(cands)))]

    def __len__(self): return len(self.items)

    def __getitem__(self, k):
        i, j = self.items[k]; r = self.rows[i]; img = Image.open(r['abs']).convert('RGB'); box = r['box']
        yb = r['y']
        if j is not None:
            b = self.rows[j]; img = swap_bg(img, box, Image.open(b['abs']).convert('RGB'), b['box']); box = b['box']; yb = b['y']
        return to_tensor_u8(crop_margin(img, box, self.margin)), r['y'], yb


# ------------------------------------------------------------------ 모델·평가
def build_model(n_classes):
    import torch, torchvision
    m = torchvision.models.efficientnet_b0(weights=torchvision.models.EfficientNet_B0_Weights.IMAGENET1K_V1)
    m.classifier = torch.nn.Sequential(torch.nn.Dropout(0.3), torch.nn.Linear(1280, n_classes))
    return m


def normalize(x_u8, mean, std):
    return ((x_u8.float() - mean) / std).contiguous()      # NCHW 유지 (channels_last 금지)


def predict(model, loader, mean, std):
    import torch
    model.eval(); out, ya, yb = [], [], []
    for x, a, b in loader:
        x = x.cuda(non_blocking=True).contiguous()
        with torch.no_grad(), torch.autocast('cuda', dtype=torch.float16): out.append(model(normalize(x, mean, std)).float().cpu())
        ya.append(a); yb.append(b)
    return torch.cat(out).numpy(), torch.cat(ya).numpy(), torch.cat(yb).numpy()


def masked_pred(logits, y_true, crop_of_cls):
    """정답 작물의 클래스만 남기고 고른다 (서비스는 사용자가 품목을 고른다)."""
    keep = crop_of_cls[None, :] == crop_of_cls[y_true][:, None]
    return np.where(keep, logits, -1e9).argmax(1)


def f1_per_class(pred, true, n):
    f = np.zeros(n)
    for c in range(n):
        tp = ((pred == c) & (true == c)).sum(); fp = ((pred == c) & (true != c)).sum(); fn = ((pred != c) & (true == c)).sum()
        f[c] = 2 * tp / max(1, 2 * tp + fp + fn) if (true == c).any() else np.nan
    return f


def clean_scores(logits, y, crop_of_cls, labels):
    p = masked_pred(logits, y, crop_of_cls); f = f1_per_class(p, y, len(labels))
    per_crop = {}
    for c in np.unique(crop_of_cls): per_crop[int(c)] = float(np.nanmean(f[crop_of_cls == c]))
    return dict(acc_mask=float((p == y).mean()), f1_mask=float(np.nanmean(f)), acc_nomask=float((logits.argmax(1) == y).mean()), f1_per_crop=per_crop, f1_per_class=f), p


def conflict_scores(logits, ya, yb, crop_of_cls, n):
    p = masked_pred(logits, ya, crop_of_cls)
    leaf, bg = (p == ya), (p == yb)
    # 클래스별 평균도 같이 (정상 클래스가 장수가 많아 전체 평균을 끌고 가므로)
    cls_leaf = np.array([leaf[ya == c].mean() for c in range(n) if (ya == c).any()])
    return dict(n=int(len(ya)), follow_leaf=float(leaf.mean()), follow_bg=float(bg.mean()), other=float((~leaf & ~bg).mean()), follow_leaf_class_avg=float(cls_leaf.mean()))


def evaluate(model, rows, labels, crop_of_cls, mean, std, workers, tag, seed=0, margins=(0.0, 0.25)):
    import torch
    mk = lambda ds: torch.utils.data.DataLoader(ds, batch_size=128, shuffle=False, num_workers=workers, pin_memory=True, persistent_workers=False)
    res = {}
    for m in margins:
        lg, ya, yb = predict(model, mk(EvalSet(rows, crop_of_cls, m)), mean, std)
        s, p = clean_scores(lg, ya, crop_of_cls, labels); res[f'clean@{int(m * 100)}'] = s
        if m == 0.25: res['_pred25'] = (p, ya)
    for m in (0.25, 0.1):
        lg, ya, yb = predict(model, mk(EvalSet(rows, crop_of_cls, m, 'conflict', seed)), mean, std)
        res[f'conflict@{int(m * 100)}'] = conflict_scores(lg, ya, yb, crop_of_cls, len(labels))
    return res


def report(tag, res, crops):
    c = res['clean@25']
    line = f"[{tag}] 일반(여백25%) 마스킹 acc {c['acc_mask']:.3f} macroF1 {c['f1_mask']:.3f} (마스킹 없음 acc {c['acc_nomask']:.3f}) " + (f"| 여백0% acc {res['clean@0']['acc_mask']:.3f}" if 'clean@0' in res else '')
    for k in ('conflict@25', 'conflict@10'):
        s = res[k]; line += f" | {k} 잎 {s['follow_leaf']:.3f}(클래스평균 {s['follow_leaf_class_avg']:.3f}) 배경 {s['follow_bg']:.3f}"
    return line


def jsonable(x):
    if isinstance(x, dict): return {str(k): jsonable(v) for k, v in x.items() if not str(k).startswith('_')}
    if isinstance(x, (np.ndarray,)): return [None if np.isnan(v) else float(v) for v in x]
    return x


# ------------------------------------------------------------------ 학습
def main():
    import torch
    ap = argparse.ArgumentParser()
    ap.add_argument('--processed', nargs='+', required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--epochs', type=int, default=12); ap.add_argument('--bs', type=int, default=64); ap.add_argument('--lr', type=float, default=1e-3)
    ap.add_argument('--workers', type=int, default=12); ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--patience', type=int, default=4, help='검증 macro F1이 이 epoch 수만큼 연속으로 best를 넘지 못하면 중단 (0이면 끔)')
    ap.add_argument('--min-delta', type=float, default=0.002)
    ap.add_argument('--smoke', action='store_true', help='작은 표본(분할·클래스당 40장)으로 2 epoch만')
    a = ap.parse_args()
    if a.smoke: a.epochs = 2
    os.makedirs(a.out, exist_ok=True); random.seed(a.seed); np.random.seed(a.seed); torch.manual_seed(a.seed)
    torch.backends.cudnn.benchmark = True
    rows, labels, crop_of_cls, crops = load_manifests(a.processed, 40 if a.smoke else 0, a.seed)
    sp = {s: [r for r in rows if r['split'] == s] for s in ('train', 'val', 'test')}
    n = len(labels); print(f'클래스 {n}개, 학습 {len(sp["train"])} / 검증 {len(sp["val"])} / 시험 {len(sp["test"])}장', flush=True)
    json.dump(dict(labels=labels, crop_of_class=crop_of_cls.tolist(), crops=crops), open(f'{a.out}/classes.json', 'w'), ensure_ascii=False, indent=1)

    cnt = np.bincount([r['y'] for r in sp['train']], minlength=n).astype(float).clip(min=1)
    w = torch.tensor((cnt.mean() / cnt) ** 0.5, dtype=torch.float32).cuda()       # 클래스 가중치 (역빈도의 제곱근: 너무 극단적이지 않게)
    mean = torch.tensor(MEAN, device='cuda').view(1, 3, 1, 1) * 255; std = torch.tensor(STD, device='cuda').view(1, 3, 1, 1) * 255
    model = build_model(n).cuda()
    loader = torch.utils.data.DataLoader(TrainSet(sp['train'], a.seed), batch_size=a.bs, shuffle=True, drop_last=True, num_workers=a.workers, pin_memory=True, persistent_workers=True, prefetch_factor=4)
    opt = torch.optim.AdamW(model.parameters(), a.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, a.lr, total_steps=a.epochs * len(loader), pct_start=0.15)
    scaler = torch.amp.GradScaler(); best, history, t0, bad = -1, [], time.time(), 0
    for ep in range(1, a.epochs + 1):
        model.train(); tl, tn, te = 0.0, 0, time.time()
        for x, y in loader:
            x = x.cuda(non_blocking=True).contiguous(); y = y.cuda(non_blocking=True)
            with torch.autocast('cuda', dtype=torch.float16): loss = torch.nn.functional.cross_entropy(model(normalize(x, mean, std)), y, weight=w, label_smoothing=0.05)
            opt.zero_grad(set_to_none=True); scaler.scale(loss).backward(); scaler.step(opt); scaler.update(); sched.step()
            tl += loss.item() * len(y); tn += len(y)
        t_train = time.time() - te
        res = evaluate(model, sp['val'], labels, crop_of_cls, mean, std, a.workers, 'val', a.seed, margins=(0.25,))
        score = res['clean@25']['f1_mask']
        print(f'epoch {ep}/{a.epochs} loss {tl / tn:.3f} (학습 {tn / t_train:.0f} img/s, 평가 포함 {time.time() - te:.0f}초) ' + report('val', res, crops) + f'  [{(time.time() - t0) / 60:.1f}분]', flush=True)
        history.append(dict(epoch=ep, loss=tl / tn, val=jsonable(res)))
        if score > best + a.min_delta: bad = 0
        else: bad += 1
        if score > best: best = score; torch.save(model.state_dict(), f'{a.out}/best.pt')
        if a.patience and bad >= a.patience:
            print(f'조기 종료: 검증 macro F1이 {a.patience} epoch 연속 개선되지 않음 (best {best:.3f}). best 가중치로 시험한다', flush=True); break
    # 시험: 검증 macro F1이 가장 좋았던 가중치로
    model.load_state_dict(torch.load(f'{a.out}/best.pt')); res = evaluate(model, sp['test'], labels, crop_of_cls, mean, std, a.workers, 'test', a.seed)
    print('== ' + report('test', res, crops), flush=True)
    pred, true = res['_pred25']; cm = np.zeros((n, n), int)
    for t, p in zip(true, pred): cm[t, p] += 1
    np.savetxt(f'{a.out}/confusion_test.csv', cm, fmt='%d', delimiter=',', header=','.join(labels), comments='', encoding='utf-8')
    f1c = res['clean@25']['f1_per_class']
    print('클래스별 F1 (품목 마스킹):', {l: (None if np.isnan(f) else round(float(f), 3)) for l, f in zip(labels, f1c)})
    print('작물별 macro F1:', {crops[c]: round(v, 3) for c, v in res['clean@25']['f1_per_crop'].items()})
    json.dump(dict(args=vars(a), n_train=len(sp['train']), test=jsonable(res), history=history, labels=labels), open(f'{a.out}/results.json', 'w'), ensure_ascii=False, indent=1)
    print(f'끝 ({(time.time() - t0) / 60:.1f}분) → {a.out}')


if __name__ == '__main__':
    main()
