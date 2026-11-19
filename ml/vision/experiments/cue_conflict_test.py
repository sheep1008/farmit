"""단서 충돌 시험: 모델이 잎을 보는가, 배경을 보는가.

시험 이미지 A의 잎(bbox 안쪽)을 같은 작물의 다른 클래스 이미지 B의 배경(B의 bbox 자리)에 붙여 합성 이미지를 만든다.
정답은 A의 클래스다. 모델이 B의 클래스를 말하면 배경(촬영 환경)을 따른 것이다.
  full   : 합성 이미지 전체를 입력
  crop25 : 합성 이미지에서 붙인 자리 +25% 여백을 잘라 입력 (여백 링은 B의 배경)
  crop0  : 붙인 잎만 입력 (배경 없음. 합성이 필요 없는 하한선)
학습은 preprocess_test.py와 같다 (원본 이미지, 합성 없음). 점수는 품목 마스킹(같은 작물 클래스만)으로 낸다.

실행: python -X utf8 cue_conflict_test.py <153 01.데이터 폴더> <결과 폴더> [시드 수=4]
"""
import json, os, random, sys, time

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from preprocess_test import (CLASSES, CROP_OF, CROPS, SIZE, build, load_records, pick_pool, split_groups, train_logits)  # noqa: E402

GRAY = np.array([124, 116, 104])


def gray_box(img):
    """회색으로 가린 bbox 위치를 찾는다 (x0, y0, x1, y1)."""
    m = (np.abs(img.astype(int) - GRAY).sum(2) <= 12)
    rows, cols = m.sum(1), m.sum(0)
    ys, xs = np.where(rows >= 0.5 * rows.max())[0], np.where(cols >= 0.5 * cols.max())[0]
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def composite(leaf, bg_full, box):
    x0, y0, x1, y1 = box
    out = bg_full.copy()
    out[y0:y1, x0:x1] = np.asarray(Image.fromarray(leaf).resize((x1 - x0, y1 - y0), Image.BILINEAR))
    return out


def crop_resize(img, box, margin):
    x0, y0, x1, y1 = box; w, h = x1 - x0, y1 - y0
    c = img[max(0, int(y0 - margin * h)):min(SIZE, int(y1 + margin * h)), max(0, int(x0 - margin * w)):min(SIZE, int(x1 + margin * w))]
    return np.asarray(Image.fromarray(c).resize((SIZE, SIZE), Image.BILINEAR))


def make_conflicts(X, y, te_idx, seed, per_sample=2):
    """시험 이미지마다 같은 작물·다른 클래스의 배경 per_sample개. 반환: 입력 3종, 정답, 배경 클래스."""
    rng = random.Random(seed); boxes = {}
    out = {'full': [], 'crop25': [], 'crop0': []}; ya, yb = [], []
    for i in te_idx:
        cands = [j for j in te_idx if CROP_OF[y[j]] == CROP_OF[y[i]] and y[j] != y[i]]
        for j in rng.sample(cands, min(per_sample, len(cands))):
            if j not in boxes: boxes[j] = gray_box(X[3][j])
            comp = composite(X[2][i], X[0][j], boxes[j])
            out['full'].append(comp); out['crop25'].append(crop_resize(comp, boxes[j], 0.25)); out['crop0'].append(X[2][i])
            ya.append(y[i]); yb.append(y[j])
    return {k: np.stack(v) for k, v in out.items()}, np.array(ya), np.array(yb)


def follow_rates(logits, ya, yb):
    keep = CROP_OF[None, :] == CROP_OF[ya][:, None]
    p = np.where(keep, logits, -1e9).argmax(1)
    return dict(follow_leaf=float((p == ya).mean()), follow_bg=float((p == yb).mean()), other=float(((p != ya) & (p != yb)).mean()))


def train_with_extra(Xv, y, tr, te, seed, extra, epochs=6):
    """train_logits와 같은 학습 뒤 extra 입력(합성 이미지)의 logits도 낸다. train_logits를 확장하지 않고 입력을 이어 붙여 재사용한다."""
    n = len(Xv)
    Xall = np.concatenate([Xv, extra]); yall = np.concatenate([y, np.zeros(len(extra), int)])
    tr2 = np.concatenate([tr, np.zeros(len(extra), bool)])
    te_idx = np.concatenate([np.where(te)[0], n + np.arange(len(extra))])
    te2 = np.zeros(len(Xall), bool); te2[te_idx] = True
    lg, _ = train_logits(Xall, yall, tr2, te2, seed, epochs)
    k = int(te.sum())
    return lg[:k], lg[k:]


if __name__ == '__main__':
    base, out = sys.argv[1], sys.argv[2]; n_seed = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    os.makedirs(out, exist_ok=True)
    recs = load_records(base); pool = pick_pool(recs, 600); X, y, g, _ = build(pool)
    results = []; t_all = time.time()
    for s in range(n_seed):
        tr, te = split_groups(y, g, s); te_idx = np.where(te)[0]
        conf, ya, yb = make_conflicts(X, y, te_idx, s)
        if s == 0:   # 합성 예시 시트: 행=예시, 열=full/crop25/crop0
            rng = random.Random(3); ids = rng.sample(range(len(ya)), 6)
            Image.fromarray(np.concatenate([np.concatenate([conf[k][i] for k in ('full', 'crop25', 'crop0')], 1) for i in ids], 0)).save(f'{out}/conflict_samples.jpg', quality=88)
        for vn, vi in (('full', 0), ('crop25', 1), ('crop0', 2)):
            t0 = time.time()
            lg_in, lg_cf = train_with_extra(X[vi], y, tr, te, s, conf[vn])
            # 일반 시험 점수 (참고)
            keep = CROP_OF[None, :] == CROP_OF[y[te]][:, None]
            acc = float((np.where(keep, lg_in, -1e9).argmax(1) == y[te]).mean())
            r = dict(seed=s, variant=vn, acc_mask=acc, n_conflict=len(ya), **follow_rates(lg_cf, ya, yb)); results.append(r)
            print(f"[seed {s}] {vn:7s} 일반 acc_mask {acc:.3f} | 충돌 시험: 잎을 따름 {r['follow_leaf']:.3f}, 배경을 따름 {r['follow_bg']:.3f}, 그 외 {r['other']:.3f}  ({time.time() - t0:.0f}s, 누적 {(time.time() - t_all) / 60:.0f}분)", flush=True)
            json.dump(results, open(f'{out}/conflict_results.json', 'w'), ensure_ascii=False)
    print('끝')
