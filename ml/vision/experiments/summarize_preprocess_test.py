"""preprocess_test.py의 results.json 집계: 변형별 평균±표준편차, 같은 분할끼리의 쌍 차이(crop25 기준·full 기준), 승수."""
import json, sys, collections
import numpy as np
d = json.load(open(sys.argv[1])); R = d['results']
V = ['full', 'crop25', 'crop0', 'bgonly']; M = ['acc9', 'acc_mask', 'f1_mask', 'dis2']
sizes = sorted({r['size'] for r in R}); seeds = sorted({r['seed'] for r in R})
get = lambda n, s, v, m: next(r[m] for r in R if r['size'] == n and r['seed'] == s and r['variant'] == v)
out = []
for m in M:
    out.append(f'\n### {m}\n\n| 풀 크기 | ' + ' | '.join(V) + ' |\n|---|' + '---:|' * len(V))
    for n in sizes:
        cells = []
        for v in V:
            a = np.array([get(n, s, v, m) for s in seeds]); cells.append(f'{a.mean():.3f} ± {a.std():.3f}')
        out.append(f'| {n} | ' + ' | '.join(cells) + ' |')
out.append('\n### 쌍 차이 (같은 분할 기준 변형 − 기준변형, 평균 [최소, 최대], 이긴 시드 수/전체)\n')
out.append('| 점수 | 풀 | crop25−full | crop0−full | crop0−crop25 | full−bgonly |\n|---|---|---|---|---|---|')
for m in ['acc_mask', 'dis2']:
    for n in sizes:
        cells = []
        for a, b in [('crop25', 'full'), ('crop0', 'full'), ('crop0', 'crop25'), ('full', 'bgonly')]:
            x = np.array([get(n, s, a, m) - get(n, s, b, m) for s in seeds])
            cells.append(f'{x.mean():+.3f} [{x.min():+.3f}, {x.max():+.3f}] {int((x > 0).sum())}/{len(x)}')
        out.append(f'| {m} | {n} | ' + ' | '.join(cells) + ' |')
out.append('\n### 시드별 시험 규모 (n=600)\n\n| 시드 | 시험 장수 | 클래스별 시험 그룹 수 |\n|---|---|---|')
for s in seeds:
    r = next(r for r in R if r['size'] == 600 and r['seed'] == s and r['variant'] == 'full')
    out.append(f"| {s} | {r['n_test']} | {r['test_groups']} |")
print('\n'.join(out))
