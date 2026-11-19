"""147 EDA 2단계: labels.csv(eda_147_load.py 출력)로 표를 만든다. 이미지는 열지 않는다.
  .venv/Scripts/python.exe -I -X utf8 experiments/eda_147.py
출력: docs/vision-147-eda/tables.md, bbox_ratio.png, area_risk.csv 등
"""
import csv, collections as C, os, re
import numpy as np

DOC = '../../docs/vision-147-eda'
R = list(csv.DictReader(open('data/review/147/labels.csv', encoding='utf-8')))
ZERO = None
for r in R:
    for k in ('H', 'W', 'xtl', 'ytl', 'xbr', 'ybr', 'type', 'disease', 'area', 'risk', 'grow', 'npts', 'crop'):
        r[k] = int(r[k])
    r['swap'] = False
    if r['W'] * r['H'] > 0 and (r['xbr'] > r['W'] or r['ybr'] > r['H']) and r['xbr'] <= r['H'] and r['ybr'] <= r['W']:
        r['swap'] = True; r['W'], r['H'] = r['H'], r['W']  # bbox가 EXIF 회전 뒤 좌표라서 JSON W,H와 맞지 않는 경우
    r['ratio'] = max(0, r['xbr'] - r['xtl']) * max(0, r['ybr'] - r['ytl']) / (r['W'] * r['H']) if r['W'] * r['H'] > 0 else float('nan')
    r['kind'] = '정상' if r['type'] == 0 else '질병'
    r['cname'] = r['zip_crop']
    r['cls'] = (r['cname'], r['disease'])
    r['regular'] = bool(re.fullmatch(r'\d{8}', r['fdate'])) and (r['type'] == 1 or bool(re.match(r'\d+_S\d+_\d+$', r['seq'])))
    r['month'] = r['date'][:7].replace('/', '') if r['date'] else '결측'
    r['gkey'] = r['gid'] if r['type'] == 1 else (r['gid'] + '|' + r['fdate'] if r['regular'] else '불규칙')
ZERO = [r for r in R if r['W'] * r['H'] == 0]
CROPS = ['고추', '무', '배추', '애호박', '양배추', '오이', '잎마름병(토마토)', '콩', '파', '호박']
SHORT = {'잎마름병(토마토)': '토마토'}
sn = lambda c: SHORT.get(c, c)
out = []
P = out.append


def table(head, rows):
    P('| ' + ' | '.join(head) + ' |'); P('|' + '---|' * len(head))
    for r in rows: P('| ' + ' | '.join(str(x) for x in r) + ' |')
    P('')


def q(v, ps=(5, 25, 50, 75, 95)):
    return [f'{np.percentile(v, p):.2f}' for p in ps] if len(v) else ['-'] * len(ps)


# ---- 1 필드 일치 ----
P('## A. 필드 일치 (JSON 값 vs 파일명 조각)')
mis = {k: sum(1 for r in R if int(r[k]) != int(r[f])) for k, f in [('type', 'ftype'), ('disease', 'fdis'), ('crop', 'fcrop'), ('area', 'farea'), ('grow', 'fgrow'), ('risk', 'frisk')]}
P(str(mis)); P('')
dm = [r for r in R if r['date'].replace('/', '') != r['fdate']]
P(f'date 불일치 {len(dm)}개: 빈 date {sum(1 for r in dm if r["date"]=="")}, 구성 {dict(C.Counter((r["split"], r["cname"], r["kind"]) for r in dm))}'); P('')
bb = C.Counter()
for r in R:
    if r['xbr'] <= r['xtl'] or r['ybr'] <= r['ytl']: bb['뒤집힘/0크기'] += 1
    if r['W'] * r['H'] > 0 and (r['xtl'] < 0 or r['ytl'] < 0 or r['xbr'] > r['W'] or r['ybr'] > r['H']): bb['이미지 밖'] += 1
    if r['ratio'] < 0.02: bb['면적비<2%'] += 1
    if r['W'] * r['H'] == 0: bb['JSON 해상도 0'] += 1
    if r['swap']: bb['bbox가 W,H를 바꿔야 맞음(EXIF 회전 좌표)'] += 1
P('bbox 이상: ' + str(dict(bb))); P('')

# ---- 2 코드표 ----
P('## B. 코드표')
P('작물 코드(JSON crop) ↔ zip 작물 (전 파일 일치):'); P('')
cc = C.Counter((r['crop'], r['cname']) for r in R)
table(['crop 코드', '작물(zip)', '장수'], [(k[0], k[1], v) for k, v in sorted(cc.items())])
P('(작물 코드, 질병 코드) 조합 전부 (type=질병/정상, Training/Validation 합):'); P('')
cd = C.defaultdict(lambda: C.Counter())
for r in R: cd[(r['crop'], r['cname'], r['disease'])][(r['kind'], r['split'])] += 1
rows = []
for k in sorted(cd): c = cd[k]; rows.append((k[0], sn(k[1]), k[2], c[('정상', 'Training')], c[('정상', 'Validation')], c[('질병', 'Training')], c[('질병', 'Validation')], sum(c.values())))
table(['crop', '작물', '질병코드', '정상 T', '정상 V', '질병 T', '질병 V', '합'], rows)

# ---- 3 클래스별 장수 ----
P('## C. 클래스별 장수 (질병 코드 단위, 정상 포함)')
table(['작물', '질병코드', 'Train', 'Val', '합'], [(sn(k[1]), k[2] if k[2] else ('정상' if True else ''), sum(v for kk, v in c.items() if kk[1] == 'Training'), sum(v for kk, v in c.items() if kk[1] == 'Validation'), sum(c.values())) for k, c in sorted(cd.items())])

# ---- 4 bbox ----
P('## D. bbox')
P(f'이미지당 points 개수: {dict(C.Counter(r["npts"] for r in R))}'); P('')
rows = []
for c in CROPS:
    for kd in ('정상', '질병'):
        v = [r['ratio'] for r in R if r['cname'] == c and r['kind'] == kd and r['ratio'] == r['ratio']]
        rows.append([sn(c), kd, len(v)] + q(v))
table(['작물', '구분', 'n', 'p5', 'p25', '중앙값', 'p75', 'p95'], rows)
P('질병 클래스별 면적비 중앙값/p25/p75:'); P('')
rows = []
for k in sorted(cd):
    if k[2] == 0: continue
    v = [r['ratio'] for r in R if r['cls'] == (k[1], k[2]) and r['kind'] == '질병' and r['ratio'] == r['ratio']]
    rows.append([sn(k[1]), k[2], len(v)] + [f'{np.percentile(v,p):.2f}' for p in (25, 50, 75)])
table(['작물', '질병', 'n', 'p25', '중앙값', 'p75'], rows)

P('JSON 해상도(width/height)가 0인 라벨: %d개, 구성 %s' % (len(ZERO), dict(C.Counter((r['split'], sn(r['cname']), r['kind'], r['disease']) for r in ZERO)))); P('')
# ---- 5 area/risk/region/date/grow ----
P('## E. 촬영 부위(area)·위험도(risk)·지역(region)·시기(date)·성장단계(grow)')
P('area 코드는 153 기준 01 열매·02 꽃·03 잎·05 줄기이나 147 설명서로는 확인 못 했다 (분포로만 본다).'); P('')


def dist(field, keyf=None):
    keyf = keyf or (lambda r: r[field])
    P(f'### {field}: 작물×구분별 비율(%) (n은 장수)')
    vals = sorted({keyf(r) for r in R}, key=lambda x: (str(x).zfill(4)))
    rows = []
    for c in CROPS:
        for kd in ('정상', '질병'):
            sub = [keyf(r) for r in R if r['cname'] == c and r['kind'] == kd]
            n = len(sub); cnt = C.Counter(sub)
            rows.append([sn(c), kd, n] + [f'{100*cnt[v]/n:.0f}' if cnt[v] else '' for v in vals])
    table(['작물', '구분', 'n'] + [str(v) if v != '' else '(빈값)' for v in vals], rows)


dist('area'); dist('risk'); dist('grow'); dist('region'); dist('month')

# ---- 6 묶음 ----
P('## F. 묶음 구조')
P('질병: 대상ID(`gid`) 수, Training/Validation 겹침. 정상: (gid, 날짜) 묶음 수와 겹침.'); P('')
rows = []
for k in sorted(cd):
    if k[2] == 0: continue
    sub = [r for r in R if r['cls'] == (k[1], k[2]) and r['kind'] == '질병']
    g = {r['gkey'] for r in sub}; gt = {r['gkey'] for r in sub if r['split'] == 'Training'}; gv = {r['gkey'] for r in sub if r['split'] == 'Validation'}
    rows.append([sn(k[1]), k[2], len(sub), len(g), len(gt), len(gv), len(gt & gv)])
table(['작물', '질병', '장수', '대상ID', 'Train 대상', 'Val 대상', '겹침'], rows)
dis = [r for r in R if r['kind'] == '질병']
gall = C.defaultdict(set)
for r in dis: gall[r['gkey']].add(r['split'])
P(f'질병 대상ID 전체(클래스 무시) {len(gall)}개 중 Training·Validation 둘 다 {sum(1 for s in gall.values() if len(s)==2)}개 (153은 111 중 109). Val에만 있는 대상 {sum(1 for s in gall.values() if s=={"Validation"})}개'); P('')
# 같은 대상ID가 여러 질병 클래스에 걸치는가
gc = C.defaultdict(set)
for r in dis: gc[(r['cname'], r['gid'])].add(r['disease'])
P(f'같은 (작물, 대상ID)가 둘 이상의 질병 클래스에 있음: {sum(1 for s in gc.values() if len(s)>1)}개 / {len(gc)}개 (153 수박 병 2종 문제와 같은 현상인지 확인용)'); P('')
gd = C.defaultdict(set)
for r in dis: gd[(r['cname'], r['gid'], r['fdate'])].add(r['disease'])
multi = C.Counter(sn(k[0]) for k, v in gd.items() if len(v) > 1)
P(f'같은 (작물, 대상ID, 날짜)에 둘 이상의 질병 클래스: {sum(multi.values())}개 / {len(gd)}개, 작물별 {dict(multi)}'); P('')
# 정상 묶음
rows = []
for c in CROPS:
    sub = [r for r in R if r['cname'] == c and r['kind'] == '정상']
    g = C.defaultdict(set)
    for r in sub:
        if r['gkey'] != '불규칙': g[r['gkey']].add(r['split'])
    gid_only = {r['gid'] for r in sub}
    dsub = {r['gid'] for r in R if r['cname'] == c and r['kind'] == '질병'}
    sizes = sorted(v for k, v in C.Counter(r['gkey'] for r in sub).items() if k != '불규칙')
    rows.append([sn(c), len(sub), sum(1 for r in sub if r['gkey'] == '불규칙'), len(g), len(gid_only), sum(1 for s in g.values() if len(s) == 2), f'{sizes[0]}/{int(np.median(sizes))}/{sizes[-1]}'])
table(['작물', '정상 장수', '불규칙 파일명(묶음 제외)', '(gid,날짜) 묶음', 'gid 수', 'Train·Val 둘 다인 묶음', '묶음 크기 최소/중앙/최대'], rows)
# 연속 프레임: 정상 파일명 seq
sq = C.Counter(); gaps = []
P(f'파일명이 규칙(8자리 날짜 + NNNN_Sxx_y)과 다른 라벨: 정상 {sum(1 for r in R if r["kind"]=="정상" and not r["regular"])}개, 질병 {sum(1 for r in R if r["kind"]=="질병" and not r["regular"])}개 (질병은 번호 형식이 다르므로 날짜만 본다)'); P('')
bykey = C.defaultdict(list)
for r in R:
    if r['kind'] != '정상': continue
    m = re.match(r'(\d+)_S(\d+)_(\d+)$', r['seq'])
    if not m: sq['번호형식다름'] += 1; continue
    bykey[(r['cname'], r['gkey'], m.group(2), m.group(3))].append(int(m.group(1)))
for k, v in bykey.items():
    v = sorted(set(v))
    if len(v) > 1: gaps += list(np.diff(v))
P(f'정상 seq 형식 `NNNN_Sxx_y`가 아닌 것: {sq["번호형식다름"]}개. 같은 묶음 안 번호 간격: 1이 {100*np.mean(np.array(gaps)==1):.0f}%, 5 이하 {100*np.mean(np.array(gaps)<=5):.0f}%, 중앙값 {np.median(gaps):.0f} → 연속 촬영 프레임이다.'); P('')
sx = C.Counter(re.search(r'_(S\d+)_', r['seq'] + '_').group(1) if re.search(r'_(S\d+)_', r['seq'] + '_') else '-' for r in R if r['kind'] == '정상')
P(f'정상 S번호 분포: {dict(sx)}'); P('')
sd = C.Counter(r['seq'] for r in R if r['kind'] == '질병')
P(f'질병 seq 값 개수(상위 5): {sd.most_common(5)}, 서로 다른 값 {len(sd)}'); P('')

# ---- 7 출처 편향 (장수 기반 요약) ----
P('## G. 출처 편향 요약 (작물별 정상 vs 질병)')
rows = []
for c in CROPS:
    d = [r for r in R if r['cname'] == c and r['kind'] == '질병']; n = [r for r in R if r['cname'] == c and r['kind'] == '정상']
    if not d: continue
    top = lambda s, f: ', '.join(f'{k}:{100*v/len(s):.0f}%' for k, v in C.Counter(f(r) for r in s).most_common(3))
    rows.append([sn(c), top(d, lambda r: r['area']), top(n, lambda r: r['area']), top(d, lambda r: r['month']), top(n, lambda r: r['month']), top(d, lambda r: r['region']), top(n, lambda r: r['region'] or '빈값')])
table(['작물', '질병 area', '정상 area', '질병 월', '정상 월', '질병 region', '정상 region'], rows)

# ---- 그림: bbox 면적비 ----
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'Malgun Gothic'; plt.rcParams['axes.unicode_minus'] = False
fig, ax = plt.subplots(figsize=(11, 5))
data, lab = [], []
for c in CROPS:
    for kd in ('질병', '정상'):
        data.append([r['ratio'] for r in R if r['cname'] == c and r['kind'] == kd and r['ratio'] == r['ratio']]); lab.append(f'{sn(c)}\n{kd}')
bp = ax.boxplot(data, tick_labels=lab, showfliers=False, patch_artist=True)
for i, b in enumerate(bp['boxes']): b.set_facecolor('#d95f02' if i % 2 == 0 else '#1b9e77'); b.set_alpha(.7)
ax.set_ylabel('bbox 면적 / 이미지 면적'); ax.set_title('147 bbox 면적비 (주황=질병, 초록=정상)'); plt.setp(ax.get_xticklabels(), fontsize=7)
plt.tight_layout(); plt.savefig(f'{DOC}/fig_bbox_ratio.png', dpi=130)

os.makedirs(DOC, exist_ok=True)
open(f'{DOC}/tables.md', 'w', encoding='utf-8').write('\n'.join(out))
print('\n'.join(out))
