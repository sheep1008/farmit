"""합친 모델의 시험셋(또는 검증셋) 점수를 데이터셋(153·147·146)별로 나눠 낸다. manifest의 dataset 열을 쓴다.
  .venv/Scripts/python.exe -I -X utf8 experiments/eval_by_dataset.py --run runs/e5b_all --split test
출력: <run>/eval_by_dataset_<split>.json, 표를 표준출력에 (품목 마스킹, 여백 25%)
"""
import argparse, json, os, sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    import torch
    import train as T
    ap = argparse.ArgumentParser(); ap.add_argument('--run', required=True); ap.add_argument('--split', default='test'); ap.add_argument('--margin', type=float, default=0.25)
    ap.add_argument('--processed', nargs='+', default=['data/processed/153', 'data/processed/147', 'data/processed/146']); ap.add_argument('--workers', type=int, default=8)
    a = ap.parse_args()
    rows, labels, crop_of_cls, crops = T.load_manifests(a.processed)
    saved = json.load(open(f'{a.run}/classes.json', encoding='utf-8')); assert saved['labels'] == labels, '클래스 순서가 학습 때와 다르다'
    rs = [r for r in rows if r['split'] == a.split]; n = len(labels)
    model = T.build_model(n).cuda(); model.load_state_dict(torch.load(f'{a.run}/best.pt', map_location='cuda'))
    mean = torch.tensor(T.MEAN, device='cuda').view(1, 3, 1, 1) * 255; std = torch.tensor(T.STD, device='cuda').view(1, 3, 1, 1) * 255
    dl = torch.utils.data.DataLoader(T.EvalSet(rs, crop_of_cls, a.margin), batch_size=128, shuffle=False, num_workers=a.workers)
    lg, y, _ = T.predict(model, dl, mean, std); p = T.masked_pred(lg, y, crop_of_cls)
    ds = np.array([r['dataset'] for r in rs]); crop = np.array([r['crop_name'] for r in rs]); lab = np.array(labels)
    out = {}

    def score(m):
        yy, pp = y[m], p[m]; f = T.f1_per_class(pp, yy, n)       # 이 부분집합 안의 샘플만으로 클래스별 F1
        return dict(n=int(m.sum()), acc=float((pp == yy).mean()), macro_f1=float(np.nanmean(f)), classes=int((~np.isnan(f)).sum()), f1_per_class={labels[c]: float(f[c]) for c in range(n) if not np.isnan(f[c])})
    print(f'| 구분 | 장수 | 클래스 | 정확도 | macro F1 |\n|---|---:|---:|---:|---:|')
    out['all'] = score(np.ones(len(rs), bool)); print(f'| 전체 | {out["all"]["n"]:,} | {out["all"]["classes"]} | {out["all"]["acc"]:.3f} | {out["all"]["macro_f1"]:.3f} |')
    for d in sorted(set(ds)):
        out[f'dataset_{d}'] = s = score(ds == d); print(f'| 데이터셋 {d} | {s["n"]:,} | {s["classes"]} | {s["acc"]:.3f} | {s["macro_f1"]:.3f} |')
    shared = [c for c in sorted(set(crop)) if len(set(ds[crop == c])) > 1]
    for c in shared:
        for d in sorted(set(ds[crop == c])):
            out[f'{c}_{d}'] = s = score((crop == c) & (ds == d)); print(f'| {c} ({d}) | {s["n"]:,} | {s["classes"]} | {s["acc"]:.3f} | {s["macro_f1"]:.3f} |')
    json.dump(out, open(f'{a.run}/eval_by_dataset_{a.split}.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
