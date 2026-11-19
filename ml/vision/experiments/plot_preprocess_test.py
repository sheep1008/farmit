"""시험 결과 그래프 2장 (docs/vision-preprocess-test/)."""
import json, sys
import numpy as np
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
out = sys.argv[1]
plt.rcParams.update({'font.family': 'Malgun Gothic', 'axes.unicode_minus': False})
LEAF, BG = '#2a7f62', '#c8553d'

# 그림 1: 단서 충돌 (전체 / crop25 / crop0)
R = json.load(open(f'{out}/conflict_results.json'))
fig, ax = plt.subplots(figsize=(6.4, 3.6)); names = ['전체 이미지', 'crop 25%', 'crop 0%']
for k, v in enumerate(['full', 'crop25', 'crop0']):
    x = [r for r in R if r['variant'] == v]
    for off, key, c, lab in ((-0.18, 'follow_leaf', LEAF, '잎을 따름'), (0.18, 'follow_bg', BG, '배경을 따름')):
        m = np.mean([r[key] for r in x]); s = np.std([r[key] for r in x])
        ax.bar(k + off, m, 0.34, color=c, yerr=s, capsize=3, label=lab if k == 0 else None); ax.text(k + off, m + s + 0.015, f'{m:.2f}', ha='center', fontsize=9)
ax.set_xticks(range(3)); ax.set_xticklabels(names); ax.set_ylim(0, 1.1); ax.set_ylabel('비율'); ax.set_title('단서 충돌 시험: 잎을 다른 배경에 붙였을 때'); ax.legend(frameon=False)
ax.spines[['top', 'right']].set_visible(False); fig.tight_layout(); fig.savefig(f'{out}/fig_cue_conflict.png', dpi=140)

# 그림 2: 학습 방식 4가지 × 여백 (잎을 따르는 비율)
R = json.load(open(f'{out}/margin_swap_results.json')); models = ['crop25', 'mix', 'crop25+swap', 'mix+swap']
fig, ax = plt.subplots(figsize=(6.8, 3.6))
for k, m in enumerate(models):
    x = [r for r in R if r['model'] == m]
    for off, key, c, lab in ((-0.18, 'conflict@25_leaf', '#7fb8a4', '여백 25%'), (0.18, 'conflict@50_leaf', LEAF, '여백 50%')):
        v = np.mean([r[key] for r in x]); s = np.std([r[key] for r in x])
        ax.bar(k + off, v, 0.34, color=c, yerr=s, capsize=3, label=lab if k == 0 else None); ax.text(k + off, v + s + 0.015, f'{v:.2f}', ha='center', fontsize=9)
ax.set_xticks(range(4)); ax.set_xticklabels(['crop25', 'mix\n(0%+25%)', 'crop25\n+배경교체', 'mix\n+배경교체']); ax.set_ylim(0, 1.1)
ax.set_ylabel('잎을 따른 비율'); ax.set_title('학습 방식별 단서 충돌 시험 (높을수록 좋음)'); ax.set_ylim(0, 1.25); ax.legend(frameon=False, loc='upper left', ncol=2)
ax.spines[['top', 'right']].set_visible(False); fig.tight_layout(); fig.savefig(f'{out}/fig_margin_swap.png', dpi=140)
