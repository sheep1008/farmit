"""153 EDA (사후): 원본 zip이 삭제되어 data/processed/153/manifest.csv와 처리된 이미지로 만든다.
  cd ml/vision && .venv/Scripts/python.exe -I -X utf8 experiments/eda_153.py
주의: manifest는 전처리 '선별 뒤' 목록이다 (정상은 질병 합계의 약 2배·질병 부위에 맞춰 뽑음, 포도 Validation 없음,
코드표 밖 66개 제외, 11장 중복 제거). 그래서 정상의 장수·부위 분포는 선별의 결과이고 원본 분포가 아니다 (표에 명시).
출력: docs/vision-153-eda/tables.md, fig_bbox_ratio.png, sheet_<작물>.jpg
"""
import csv, collections as C, os
import numpy as np
from PIL import Image, ImageDraw, ImageFont

PROC = 'data/processed/153'; DOC = '../../docs/vision-153-eda'
os.makedirs(DOC, exist_ok=True)
R = list(csv.DictReader(open(f'{PROC}/manifest.csv', encoding='utf-8-sig')))
for r in R:
    for k in ('img_w', 'img_h', 'bx0', 'by0', 'bx1', 'by1', 'risk', 'area', 'disease_code'): r[k] = int(r[k])
    r['kind'] = '정상' if r['disease_code'] == 0 else '질병'
    r['ratio'] = (r['bx1'] - r['bx0']) * (r['by1'] - r['by0']) / (r['img_w'] * r['img_h'])
    r['month'] = r['date'][:7].replace('/', '') if r['date'] else '결측'
CROPS = list(dict.fromkeys(r['crop_name'] for r in R))
AREA = {1: '열매', 2: '꽃', 3: '잎', 5: '줄기'}
out = []; P = out.append


def table(head, rows):
    P('| ' + ' | '.join(head) + ' |'); P('|' + '---|' * len(head))
    for r in rows: P('| ' + ' | '.join(str(x) for x in r) + ' |')
    P('')


P('## A. 클래스별 장수 (전처리 선별 뒤, manifest 기준)'); P('')
P('train/val/test는 **우리가 대상ID·묶음 단위로 다시 나눈 것**이다 (AI Hub Training/Validation이 아님). 정상 장수는 질병 합계의 약 2배 한도로 뽑은 결과다.'); P('')
cl = C.defaultdict(C.Counter)
for r in R: cl[(r['crop_name'], r['disease_code'], r['disease_name'])][r['split']] += 1
table(['작물', '질병코드', '이름', 'train', 'val', 'test', '합'], [(k[0], k[1], k[2], c['train'], c['val'], c['test'], sum(c.values())) for k, c in sorted(cl.items(), key=lambda x: (CROPS.index(x[0][0]), x[0][1]))])
P(f'전체 {len(R)}장, 질병 {sum(1 for r in R if r["kind"]=="질병")}장, 정상 {sum(1 for r in R if r["kind"]=="정상")}장. 질병 클래스 장수 범위 {min(sum(c.values()) for k,c in cl.items() if k[1]!=0)}~{max(sum(c.values()) for k,c in cl.items() if k[1]!=0)}.'); P('')

P('## B. bbox: 저장 이미지(여백 25% crop) 안에서 bbox가 차지하는 비율')
P('원본 대비 면적비(vision.md 4.1: 작물별 0.16~0.79)는 원본이 삭제돼 다시 계산하지 못했다. 아래는 **저장 이미지 대비**라서 여백 25%가 포함돼 최대 약 0.64이고, 이미지 가장자리에서 잘린 경우는 더 크다.'); P('')
rows = []
for c in CROPS:
    for kd in ('정상', '질병'):
        v = [r['ratio'] for r in R if r['crop_name'] == c and r['kind'] == kd]
        if v: rows.append([c, kd, len(v)] + [f'{np.percentile(v, p):.2f}' for p in (5, 25, 50, 75, 95)])
table(['작물', '구분', 'n', 'p5', 'p25', '중앙값', 'p75', 'p95'], rows)
P('저장 이미지의 긴 변은 512px이고 bbox 최소 한 변은 8px 이상이다 (실패 1장 제외).'); P('')


def dist(title, keyf, valsort=str):
    P(f'### {title}: 작물×구분별 비율(%)'); P('')
    vals = sorted({keyf(r) for r in R}, key=valsort); rows = []
    for c in CROPS:
        for kd in ('정상', '질병'):
            sub = [keyf(r) for r in R if r['crop_name'] == c and r['kind'] == kd]
            if not sub: continue
            cnt = C.Counter(sub); n = len(sub)
            rows.append([c, kd, n] + [f'{100*cnt[v]/n:.0f}' if cnt[v] else '' for v in vals])
    table(['작물', '구분', 'n'] + [str(v) if v != '' else '(빈값)' for v in vals], rows)


P('## C. 촬영 부위·위험도·지역·시기')
P('**주의:** 정상은 전처리에서 "그 작물 질병 사진에 5% 이상 나오는 부위"만 뽑았다. 그래서 아래 정상의 부위 분포는 선별 결과이고, 원본의 정상 줄기·열매 비율(vision.md 4.1 "정상은 줄기가 많다")은 여기서 볼 수 없다. 지역·시기는 선별과 무관해 원본 경향을 거의 보존한다.'); P('')
dist('area (1 열매·2 꽃·3 잎·5 줄기)', lambda r: r['area'])
dist('risk', lambda r: r['risk'])
dist('region', lambda r: r['region'])
dist('month', lambda r: r['month'])

P('## D. 묶음 구조 (질병 대상ID, 정상 (장소, 날짜))')
P('group_id는 질병 `<작물코드>_<대상ID>`, 정상 `<작물코드>_<장소>_<날짜>`다. 이 표는 선별·분할 뒤라 대상ID 겹침(원본 Training/Validation)은 볼 수 없다 (vision.md 4.1에 111개 중 109개).'); P('')
rows = []
for k, c in sorted(cl.items(), key=lambda x: (CROPS.index(x[0][0]), x[0][1])):
    sub = [r for r in R if r['crop_name'] == k[0] and r['disease_code'] == k[1]]
    gs = {sp: {r['group_id'] for r in sub if r['split'] == sp} for sp in ('train', 'val', 'test')}
    rows.append([k[0], k[1], len(sub), len(set().union(*gs.values())), len(gs['train']), len(gs['val']), len(gs['test'])])
table(['작물', '질병코드', '장수', '묶음', 'train', 'val', 'test'], rows)
dg = C.defaultdict(set)
for r in R:
    if r['kind'] == '질병': dg[(r['crop_name'], r['group_id'])].add(r['disease_code'])
multi = [(k, v) for k, v in dg.items() if len(v) > 1]
P(f'같은 (작물, 대상ID)가 둘 이상의 질병 클래스에 있는 것: **{len(multi)}개 / {len(dg)}개** ({dict(C.Counter(k[0] for k, _ in multi))}). 수박 병 2종이 서로만 헷갈린 것과 같은 현상이다 (vision.md 4.4).'); P('')
leak = sum(1 for k, v in dg.items() if len(v) > 1 and len({r['split'] for r in R if r['crop_name'] == k[0] and r['group_id'] == k[1]}) > 1)
P(f'그 중 같은 식물이 train과 test 등 **서로 다른 분할에 걸친 것: {leak}개** (분할이 클래스별로 이루어져 생김).'); P('')
ns = sorted(C.Counter(r['group_id'] for r in R if r['kind'] == '정상').values())
P(f'정상 묶음 {len(ns)}개, 크기 최소/중앙/최대 {ns[0]}/{int(np.median(ns))}/{ns[-1]} (선별 뒤).'); P('')

P('## E. 출처 편향 요약 (질병 vs 정상, 선별 뒤)')
rows = []
for c in CROPS:
    d = [r for r in R if r['crop_name'] == c and r['kind'] == '질병']; n = [r for r in R if r['crop_name'] == c and r['kind'] == '정상']
    top = lambda s, f: ', '.join(f'{k}:{100*v/len(s):.0f}%' for k, v in C.Counter(f(r) for r in s).most_common(3))
    rows.append([c, top(d, lambda r: r['month']), top(n, lambda r: r['month']), top(d, lambda r: r['region'] or '빈값'), top(n, lambda r: r['region'] or '빈값')])
table(['작물', '질병 월', '정상 월', '질병 region', '정상 region'], rows)
P('## F. 라벨 이상 (코드와 risk·region이 안 맞는 행)'); P('')
bn = [r for r in R if r['disease_code'] == 0 and (int(r['risk']) != 0 or r['region'])]
bd = [r for r in R if r['disease_code'] != 0 and (int(r['risk']) == 0 or not r['region'])]
P(f'정상 코드인데 risk>0 또는 region이 있는 행 **{len(bn)}개**: ' + ', '.join(f"{r['crop_name']} 질병{r['risk']}/지역{r['region']} {r['group_id']}" for r in bn) + ' (모두 train. 질병 식물 사진이 정상 코드로 들어간 것으로 보인다. 시트에서 잎에 병반이 보임)'); P('')
P(f'질병 코드인데 risk 0 또는 region 빈 값인 행 **{len(bd)}개**: ' + str(dict(C.Counter((r['crop_name'], r['disease_code'], 'risk' + str(r['risk']), 'region' + (r['region'] or '없음')) for r in bd))) + ' (정상 사진이 질병 코드로 들어갔을 가능성)'); P('')
open(f'{DOC}/tables.md', 'w', encoding='utf-8').write('\n'.join(out))

# ---- 그림 ----
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'Malgun Gothic'; plt.rcParams['axes.unicode_minus'] = False
fig, ax = plt.subplots(figsize=(12, 5)); data, lab = [], []
for c in CROPS:
    for kd in ('질병', '정상'):
        data.append([r['ratio'] for r in R if r['crop_name'] == c and r['kind'] == kd]); lab.append(f'{c}\n{kd}')
bp = ax.boxplot(data, tick_labels=lab, showfliers=False, patch_artist=True)
for i, b in enumerate(bp['boxes']): b.set_facecolor('#d95f02' if i % 2 == 0 else '#1b9e77'); b.set_alpha(.7)
ax.set_ylabel('bbox 면적 / 저장 이미지(여백 25%) 면적'); ax.set_title('153 bbox 비율 (주황=질병, 초록=정상)'); plt.setp(ax.get_xticklabels(), fontsize=6)
plt.tight_layout(); plt.savefig(f'{DOC}/fig_bbox_ratio.png', dpi=130)

# ---- 시트: 저장 이미지(여백 25% crop)에 bbox ----
import random
random.seed(153); T = 300; N = 6
font = ImageFont.truetype('C:/Windows/Fonts/malgun.ttf', 13)
for c in CROPS:
    dis = [r for r in R if r['crop_name'] == c and r['kind'] == '질병']; nor = [r for r in R if r['crop_name'] == c and r['kind'] == '정상']

    def pick(rows, key):
        by = C.defaultdict(list)
        for r in rows: by[key(r)].append(r)
        ks = sorted(by); random.shuffle(ks); return [random.choice(by[ks[i % len(ks)]]) for i in range(N)]
    sel = [('질병', r) for r in pick(dis, lambda r: (r['disease_code'], r['group_id']))] + [('정상', r) for r in pick(nor, lambda r: r['group_id'])]
    sheet = Image.new('RGB', (N * T, 2 * (T + 34)), 'white'); d = ImageDraw.Draw(sheet)
    for j, (kd, r) in enumerate(sel):
        x, y = (j % N) * T, (j // N) * (T + 34); im = Image.open(f"{PROC}/{r['path']}").convert('RGB'); s = T / max(im.size)
        im = im.resize((int(im.size[0] * s), int(im.size[1] * s))); ImageDraw.Draw(im).rectangle([r['bx0'] * s, r['by0'] * s, r['bx1'] * s, r['by1'] * s], outline='red', width=3)
        sheet.paste(im, (x, y + 34))
        d.text((x + 3, y + 1), f"{kd} {c}-{r['disease_code']} 부위{AREA.get(r['area'], r['area'])} 위험{r['risk']}", fill='black', font=font)
        d.text((x + 3, y + 17), f"{r['date'] or '날짜없음'} {r['group_id']} {'지역' + r['region'] if r['region'] else ''}", fill='black', font=font)
    sheet.save(f'{DOC}/sheet_{c}.jpg', quality=82)
print('\n'.join(out))
