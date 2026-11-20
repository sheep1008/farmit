"""수박 병 2종(탄저 11, 흰가루 12) 점검: best.pt로 수박 이미지 전체를 예측해 분할·묶음별 정확도를 본다.
  python -X utf8 experiments/watermelon_check.py runs/s8_153 data/processed/153
"""
import collections, csv, json, os, sys
import numpy as np, torch
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import train

if __name__ == '__main__':
    run, proc = sys.argv[1], sys.argv[2]
    cl = json.load(open(f'{run}/classes.json', encoding='utf-8')); labels = cl['labels']; coc = np.array(cl['crop_of_class'])
    rows, _, _, _ = train.load_manifests([proc]); rows = [r for r in rows if r['crop_name'] == '수박']
    for r in rows: r['y'] = labels.index(r['label'])
    model = train.build_model(len(labels)).cuda(); model.load_state_dict(torch.load(f'{run}/best.pt')); model.eval()
    mean = torch.tensor(train.MEAN, device='cuda').view(1, 3, 1, 1) * 255; std = torch.tensor(train.STD, device='cuda').view(1, 3, 1, 1) * 255
    dl = torch.utils.data.DataLoader(train.EvalSet(rows, coc, 0.25), batch_size=128, num_workers=8)
    lg, y, _ = train.predict(model, dl, mean, std); p = train.masked_pred(lg, y, coc)
    prob = torch.softmax(torch.tensor(np.where(coc[None, :] == coc[y][:, None], lg, -1e9)), 1).numpy()
    out = []
    for i, r in enumerate(rows): out.append(dict(path=r['path'], label=r['label'], split=r['split'], group=r['group_id'], pred=labels[p[i]], ok=bool(p[i] == y[i]), p11=float(prob[i, labels.index('수박_11')]), p12=float(prob[i, labels.index('수박_12')])))
    json.dump(out, open(f'{run}/watermelon_pred.json', 'w'), ensure_ascii=False)
    agg = collections.defaultdict(list)
    for o in out:
        if o['label'] != '수박_0': agg[(o['label'], o['split'], o['group'])].append(o['ok'])
    print('분할별 정확도 (병 사진만)')
    for sp in ('train', 'val', 'test'):
        for l in ('수박_11', '수박_12'):
            v = [o['ok'] for o in out if o['label'] == l and o['split'] == sp]
            print(f'  {sp:5s} {l} {np.mean(v):.3f} ({len(v)}장)')
    print('묶음별 (정답률)')
    for k in sorted(agg): print(f'  {k[0]} {k[1]:5s} {k[2]:8s} {np.mean(agg[k]):.2f} ({len(agg[k])}장)')
