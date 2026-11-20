"""학습 결과 그림 (train.py가 낸 results.json·classes.json·confusion_test.csv → 그림 4장 + 요약 표).

  python -X utf8 plot_results.py runs/s8_153 ../../docs/vision/archive/vision-train-s8_153

그림
  fig_training.png   학습 곡선: 학습 loss / 검증 macro F1·정확도 / 검증 단서 충돌 (epoch별)
  fig_test_summary.png  시험 분할: 일반 점수(여백 0·25%)와 단서 충돌(잎 vs 배경)
  fig_confusion.png  시험 혼동행렬 (행=정답, 열=예측, 행 기준 비율. 품목 마스킹 적용 예측)
  fig_f1_per_class.png  클래스별 F1 (시험, 품목 마스킹)
"""
import csv, json, os, shutil, sys

import numpy as np
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

run, out = sys.argv[1], sys.argv[2]; os.makedirs(out, exist_ok=True)
plt.rcParams.update({'font.family': 'Malgun Gothic', 'axes.unicode_minus': False, 'axes.spines.top': False, 'axes.spines.right': False,
                     'axes.grid': True, 'grid.alpha': 0.25, 'grid.linewidth': 0.6})
LEAF, BG, INK, WARN = '#2a7f62', '#c8553d', '#3a3a3a', '#8a8a8a'     # 잎(성공)=초록, 배경(실패)=주황 (전처리 시험 그림과 같은 색)
R = json.load(open(f'{run}/results.json', encoding='utf-8')); H = R['history']; T = R['test']; labels = R['labels']
ep = [h['epoch'] for h in H]; n = len(labels)
val = lambda k, f: [h['val'][k][f] for h in H]
best_ep = int(np.argmax(val('clean@25', 'f1_mask'))) + 1
stopped = len(H) < R['args']['epochs']

# ---------------------------------------------------------------- 1. 학습 곡선
fig, ax = plt.subplots(1, 3, figsize=(13.5, 3.8))
ax[0].plot(ep, [h['loss'] for h in H], color=INK, lw=2, marker='o', ms=4); ax[0].set_title('학습 loss (증강·배경 교체 포함)'); ax[0].set_xlabel('epoch')
ax[1].plot(ep, val('clean@25', 'f1_mask'), color=LEAF, lw=2, marker='o', ms=4, label='macro F1')
ax[1].plot(ep, val('clean@25', 'acc_mask'), color=WARN, lw=2, marker='o', ms=4, label='정확도')
ax[1].set_title('검증 점수 (품목 마스킹, 여백 25%)'); ax[1].set_xlabel('epoch'); ax[1].legend(frameon=False, loc='lower right')
ax[2].plot(ep, val('conflict@25', 'follow_leaf'), color=LEAF, lw=2, marker='o', ms=4, label='잎을 따름')
ax[2].plot(ep, val('conflict@25', 'follow_bg'), color=BG, lw=2, marker='o', ms=4, label='배경을 따름')
ax[2].set_title('검증 단서 충돌 (여백 25%)'); ax[2].set_xlabel('epoch'); ax[2].set_ylim(0, 1.02); ax[2].legend(frameon=False, loc='center right')
for a in ax[1:]: a.axvline(best_ep, color=WARN, lw=1, ls='--')
ax[1].annotate(f'best epoch {best_ep}', (best_ep, ax[1].get_ylim()[0]), xytext=(4, 6), textcoords='offset points', fontsize=8, color=WARN)
for a in ax: a.set_xticks(ep)
if stopped: fig.suptitle(f'조기 종료: {len(H)}/{R["args"]["epochs"]} epoch에서 중단', fontsize=10, color=WARN, y=1.0)
fig.tight_layout(); fig.savefig(f'{out}/fig_training.png', dpi=140); plt.close(fig)

# ---------------------------------------------------------------- 2. 시험 요약
fig, ax = plt.subplots(1, 2, figsize=(11, 3.8), gridspec_kw={'width_ratios': [1, 1.2]})
c0, c25 = T['clean@0'], T['clean@25']
x = np.arange(2); w = 0.36
for off, key, lab, col in ((-w / 2, 'acc_mask', '정확도', WARN), (w / 2, 'f1_mask', 'macro F1', LEAF)):
    v = [c0[key], c25[key]]; ax[0].bar(x + off, v, w, color=col, label=lab)
    for xi, vi in zip(x + off, v): ax[0].text(xi, vi + 0.01, f'{vi:.3f}', ha='center', fontsize=9)
ax[0].set_xticks(x); ax[0].set_xticklabels(['여백 0%', '여백 25%']); ax[0].set_ylim(0, 1.1); ax[0].set_title('시험: 일반 점수 (품목 마스킹)'); ax[0].legend(frameon=False, loc='upper center', bbox_to_anchor=(0.5, -0.12), ncol=2); ax[0].grid(axis='x', visible=False)
ks = ['conflict@25', 'conflict@10']; x = np.arange(2)
for off, key, lab, col in ((-w / 2, 'follow_leaf', '잎을 따름', LEAF), (w / 2, 'follow_bg', '배경을 따름', BG)):
    v = [T[k][key] for k in ks]; ax[1].bar(x + off, v, w, color=col, label=lab)
    for xi, vi in zip(x + off, v): ax[1].text(xi, vi + 0.01, f'{vi:.3f}', ha='center', fontsize=9)
ax[1].set_xticks(x); ax[1].set_xticklabels([f'여백 25% (합성 {T[ks[0]]["n"]}장)', f'여백 10% (합성 {T[ks[1]]["n"]}장)']); ax[1].set_ylim(0, 1.1); ax[1].set_title('시험: 단서 충돌 (잎을 다른 클래스 배경에 붙임)'); ax[1].legend(frameon=False, loc='center right'); ax[1].grid(axis='x', visible=False)
fig.tight_layout(); fig.savefig(f'{out}/fig_test_summary.png', dpi=140); plt.close(fig)

# ---------------------------------------------------------------- 3. 혼동행렬
rows = list(csv.reader(open(f'{run}/confusion_test.csv', encoding='utf-8'))); cm = np.array([[int(v) for v in r] for r in rows[1:]])
tot = cm.sum(1, keepdims=True).clip(min=1); pct = cm / tot
cmap = LinearSegmentedColormap.from_list('seq', ['#ffffff', '#2a7f62'])           # 단일 색상(잎 초록), 연한 것 → 진한 것
fig, ax = plt.subplots(figsize=(11.5, 10)); ax.grid(False)
im = ax.imshow(pct, cmap=cmap, vmin=0, vmax=1)
for i in range(n):
    for j in range(n):
        if cm[i, j]: ax.text(j, i, f'{pct[i, j] * 100:.0f}', ha='center', va='center', fontsize=6.5, color='white' if pct[i, j] > 0.55 else INK)
ax.set_xticks(range(n)); ax.set_yticks(range(n)); ax.set_xticklabels(labels, rotation=90, fontsize=8); ax.set_yticklabels([f'{l} ({int(t)})' for l, t in zip(labels, tot[:, 0])], fontsize=8)
ax.set_xlabel('예측'); ax.set_ylabel('정답 (시험 장수)'); ax.set_title('시험 혼동행렬 (행 기준 %, 정답 작물의 클래스만 남기고 고른 예측)')
ax.spines[:].set_visible(False); fig.colorbar(im, fraction=0.03, pad=0.02); fig.tight_layout(); fig.savefig(f'{out}/fig_confusion.png', dpi=140); plt.close(fig)

# ---------------------------------------------------------------- 4. 클래스별 F1
f1 = np.array([np.nan if v is None else v for v in c25['f1_per_class']]); order = np.argsort(f1)
fig, ax = plt.subplots(figsize=(7, 8)); y = np.arange(n)
ax.barh(y, f1[order], 0.7, color=[LEAF if f1[i] >= 0.9 else WARN if f1[i] >= 0.7 else BG for i in order])
for yi, i in zip(y, order): ax.text(f1[i] + 0.01, yi, f'{f1[i]:.2f}  (시험 {int(tot[i, 0])}장)', va='center', fontsize=7.5)
ax.set_yticks(y); ax.set_yticklabels([labels[i] for i in order], fontsize=8); ax.set_xlim(0, 1.25); ax.grid(axis='y', visible=False)
ax.axvline(0.7, color=WARN, lw=1, ls='--'); ax.set_title('클래스별 F1 (시험, 품목 마스킹)\n초록 ≥0.9 · 회색 0.7~0.9 · 주황 <0.7 (시험 묶음이 1개뿐인 클래스가 많아 편차 큼)', fontsize=10)
fig.tight_layout(); fig.savefig(f'{out}/fig_f1_per_class.png', dpi=140); plt.close(fig)

# ---------------------------------------------------------------- 원자료 복사 + 요약 표
for f in ('results.json', 'classes.json', 'confusion_test.csv', 'train.log'):
    if os.path.exists(f'{run}/{f}'): shutil.copy(f'{run}/{f}', f'{out}/{f}')
cl = json.load(open(f'{run}/classes.json', encoding='utf-8')); crops = cl['crops']
L = ['| 작물 | 시험 macro F1 (마스킹) |', '|---|---:|'] + [f'| {crops[int(c)]} | {v:.3f} |' for c, v in sorted(c25['f1_per_crop'].items(), key=lambda kv: kv[1])]
open(f'{out}/per_crop_f1.md', 'w', encoding='utf-8').write('\n'.join(L) + '\n')
print(f'best epoch {best_ep}, 중단 {stopped}, 그림 4장 → {out}')
