"""여백·배경 교체 증강 시험 (cue_conflict_test.py의 후속).

서비스에서는 bbox가 없고 가이드 틀로 자르므로 여백이 0~50%까지 흔들린다. 학습 방식 4가지를 같은 분할로 비교한다.
  crop25      : 여백 25% crop만 학습 (현재 규격)
  mix         : 여백 0% + 25% crop을 섞어 학습 (5장 "여백 0~25% 무작위"의 근사)
  crop25+swap : 여백 25% crop + "잎을 다른 이미지 배경에 붙인 합성" 학습 (정답은 잎의 클래스)
  mix+swap    : 위 둘을 합침
시험 (모두 학습에 안 쓴 촬영 대상)
  clean@0/25/50 : 합성 없는 원본을 여백 0/25/50%로 자른 것 (일반 점수)
  conflict@25/50: 잎을 같은 작물 다른 클래스의 배경에 붙이고 여백 25/50%로 자른 것 (잎을 따르는 비율)
배경 교체 증강의 배경은 **학습 이미지에서만** 가져온다 (시험 배경과 섞이지 않게). 학습 합성의 배경은 작물·클래스 상관없이 뽑는다.

실행: python -X utf8 margin_swap_test.py <153 01.데이터 폴더> <결과 폴더> [시드 수=3]
"""
import json, os, random, sys, time

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from cue_conflict_test import composite, crop_resize, gray_box  # noqa: E402
from preprocess_test import CLASSES, CROP_OF, build, load_records, pick_pool, split_groups, train_logits  # noqa: E402


def conflicts(X, y, boxes, idx, seed, margins, per=2):
    rng = random.Random(seed); sets = {m: [] for m in margins}; ya, yb = [], []
    for i in idx:
        cands = [j for j in idx if CROP_OF[y[j]] == CROP_OF[y[i]] and y[j] != y[i]]
        for j in rng.sample(cands, min(per, len(cands))):
            comp = composite(X[2][i], X[0][j], boxes[j])
            for m in margins: sets[m].append(crop_resize(comp, boxes[j], m))
            ya.append(y[i]); yb.append(y[j])
    return {m: np.stack(v) for m, v in sets.items()}, np.array(ya), np.array(yb)


def swap_train(X, y, boxes, tr_idx, seed, margin=0.25):
    """학습 이미지의 잎을 다른 학습 이미지(아무 클래스)의 배경에 붙인 합성. 같은 클래스 배경은 제외하지 않는다 (정답은 잎의 클래스)."""
    rng = random.Random(seed + 100); out, lab = [], []
    for i in tr_idx:
        j = rng.choice(tr_idx)
        out.append(crop_resize(composite(X[2][i], X[0][j], boxes[j]), boxes[j], margin)); lab.append(y[i])
    return np.stack(out), np.array(lab)


def run_model(train_X, train_y, evals, seed):
    """evals: 이름 → 입력 배열. train_logits를 재사용하려고 학습 뒤에 이어 붙여 한 번에 추론한다."""
    sizes = [len(v) for v in evals.values()]
    Xall = np.concatenate([train_X] + list(evals.values())); yall = np.concatenate([train_y, np.zeros(sum(sizes), int)])
    tr = np.zeros(len(Xall), bool); tr[:len(train_X)] = True; te = ~tr
    lg, _ = train_logits(Xall, yall, tr, te, seed)
    out, k = {}, 0
    for name, n in zip(evals, sizes): out[name] = lg[k:k + n]; k += n
    return out


def masked_pred(lg, ytrue_for_crop):
    keep = CROP_OF[None, :] == CROP_OF[ytrue_for_crop][:, None]
    return np.where(keep, lg, -1e9).argmax(1)


if __name__ == '__main__':
    base, out_dir = sys.argv[1], sys.argv[2]; n_seed = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    recs = load_records(base); pool = pick_pool(recs, 600); X, y, g, _ = build(pool)
    boxes = {i: gray_box(X[3][i]) for i in range(len(y))}
    MODELS = ['crop25', 'mix', 'crop25+swap', 'mix+swap']; results = []; t_all = time.time()
    for s in range(n_seed):
        tr, te = split_groups(y, g, s); tr_idx, te_idx = np.where(tr)[0], np.where(te)[0]
        yt = y[te_idx]
        evals = {f'clean@{int(m * 100)}': np.stack([crop_resize(X[0][i], boxes[i], m) for i in te_idx]) for m in (0.0, 0.25, 0.5)}
        cf, ya, yb = conflicts(X, y, boxes, te_idx, s, (0.25, 0.5))
        for m, arr in cf.items(): evals[f'conflict@{int(m * 100)}'] = arr
        sw_X, sw_y = swap_train(X, y, boxes, tr_idx, s)
        c25, c0 = X[1][tr_idx], X[2][tr_idx]; ytr = y[tr_idx]
        train_sets = {'crop25': (c25, ytr), 'mix': (np.concatenate([c0, c25]), np.concatenate([ytr, ytr])),
                      'crop25+swap': (np.concatenate([c25, sw_X]), np.concatenate([ytr, sw_y])),
                      'mix+swap': (np.concatenate([c0, c25, sw_X]), np.concatenate([ytr, ytr, sw_y]))}
        for name in MODELS:
            t0 = time.time(); lg = run_model(*train_sets[name], evals, s)
            r = dict(seed=s, model=name)
            for k in ('clean@0', 'clean@25', 'clean@50'): r[k] = float((masked_pred(lg[k], yt) == yt).mean())
            for k in ('conflict@25', 'conflict@50'):
                p = masked_pred(lg[k], ya); r[k + '_leaf'] = float((p == ya).mean()); r[k + '_bg'] = float((p == yb).mean())
            results.append(r)
            print(f"[seed {s}] {name:12s} clean 0/25/50: {r['clean@0']:.3f}/{r['clean@25']:.3f}/{r['clean@50']:.3f} | 충돌@25 잎 {r['conflict@25_leaf']:.3f} 배경 {r['conflict@25_bg']:.3f} | 충돌@50 잎 {r['conflict@50_leaf']:.3f} 배경 {r['conflict@50_bg']:.3f} ({time.time() - t0:.0f}s, 누적 {(time.time() - t_all) / 60:.0f}분)", flush=True)
            json.dump(results, open(f'{out_dir}/margin_swap_results.json', 'w'), ensure_ascii=False)
    print('끝')
