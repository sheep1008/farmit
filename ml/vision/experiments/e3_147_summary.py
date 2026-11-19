"""e3_147.py 결과 집계 (평균 ± 표준편차). 출력: docs/vision-147-e3/summary.md
  .venv/Scripts/python.exe -I -X utf8 experiments/e3_147_summary.py
"""
import json, collections as C
import numpy as np
D = '../../docs/vision-147-e3'
ms = lambda v: f'{np.mean(v):.3f} ± {np.std(v):.3f}'
out = []; P = out.append
r1 = json.load(open(f'{D}/part1_results.json', encoding='utf-8'))
P('## part1 입력 변형 (시드 3, 12클래스, 품목 마스킹)'); P('')
P('| 입력 | 마스킹 정확도 | macro F1 | 정상/병 이분 | 병끼리(병 2종↑ 작물) | 고추 | 토마토 | 콩 | 파 |'); P('|---|---|---|---|---|---|---|---|---|')
for v in ['full', 'crop25', 'crop0', 'bgonly', 'boxshape']:
    rs = [r for r in r1 if r['variant'] == v]
    P(f"| {v} | {ms([r['acc_mask'] for r in rs])} | {ms([r['f1_mask'] for r in rs])} | {ms([r['normal_vs_disease'] for r in rs])} | {ms([r['dis_multi'] for r in rs])} | " + ' | '.join(f"{np.mean([r['per_crop'][c] for r in rs]):.2f}" for c in ['고추', '잎마름병(토마토)', '콩', '파']) + ' |')
P('')
r2 = json.load(open(f'{D}/part2_results.json', encoding='utf-8'))
P('## part2 학습 방식 × 단서 충돌 (시드 3)'); P('')
P('| 학습 | clean@0 | clean@25 | clean@50 | 충돌@25 잎 | 충돌@25 배경 | 충돌@50 잎 | 충돌@50 배경 |'); P('|---|---|---|---|---|---|---|---|')
for m in ['crop25', 'mix', 'crop25+swap', 'mix+swap']:
    rs = [r for r in r2 if r['model'] == m]
    P(f"| {m} | " + ' | '.join(ms([r[k] for r in rs]) for k in ['clean@0', 'clean@25', 'clean@50', 'conflict@25_leaf', 'conflict@25_bg', 'conflict@50_leaf', 'conflict@50_bg']) + ' |')
P('')
P('### 충돌을 잎 종류별로 (여백 25%, 배경을 따른 비율 / 잎을 따른 비율)'); P('')
kinds = sorted({k.split('_')[1] for r in r2 for k in r if k.startswith('conflict@25_') and k.endswith('_n')})
P('| 학습 | ' + ' | '.join(kinds) + ' |'); P('|---|' + '---|' * len(kinds))
for m in ['crop25', 'mix', 'crop25+swap', 'mix+swap']:
    rs = [r for r in r2 if r['model'] == m]
    P(f'| {m} | ' + ' | '.join(f"배경 {np.mean([r[f'conflict@25_{k}_bg'] for r in rs]):.3f} / 잎 {np.mean([r[f'conflict@25_{k}_leaf'] for r in rs]):.3f} (n≈{int(np.mean([r[f'conflict@25_{k}_n'] for r in rs]))})" for k in kinds) + ' |')
P('')
P('### 정상/병 이분 정확도 (clean@25)'); P('')
for m in ['crop25', 'mix', 'crop25+swap', 'mix+swap']:
    rs = [r for r in r2 if r['model'] == m]; P(f"- {m}: {ms([r['clean@25_nd'] for r in rs])}")
open(f'{D}/summary.md', 'w', encoding='utf-8').write('\n'.join(out)); print('\n'.join(out))
