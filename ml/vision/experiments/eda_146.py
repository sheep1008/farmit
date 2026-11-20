"""146 EDA 2단계: labels.csv(eda_146_load.py)로 표·그림을 만든다. 이미지는 열지 않는다.
  .venv/Scripts/python.exe -I -X utf8 experiments/eda_146.py
출력: docs/vision/archive/vision-146-eda/tables.md, fig_bbox_ratio.png, fig_imbalance.png
불균형 비교용으로 data/processed/153·147의 manifest.csv를 읽는다.
"""
import collections as C, csv, math, os, re, statistics as S

import numpy as np

LAB = 'data/review/146/labels.csv'
DOC = '../../docs/vision/archive/vision-146-eda'
CROPS = {'배': 1, '사과': 2}
DIS_OF = {'배': (1, 2), '사과': (3, 4, 5, 6, 7)}
AREA_FN = {'01': '열매', '03': '잎', '04': '?04', '05': '?05'}   # 04·05 뜻은 시트로 확인(아래 문서 참고)
c = C.Counter
OUT = []


def md(title, head, rows, note=None):
    OUT.append(f'\n### {title}\n')
    if note: OUT.append(note + '\n')
    OUT.append('| ' + ' | '.join(head) + ' |'); OUT.append('|' + '|'.join('---' for _ in head) + '|')
    for r in rows: OUT.append('| ' + ' | '.join(str(x) for x in r) + ' |')


def pct(a, q): return float(np.percentile(a, q)) if len(a) else float('nan')


def load():
    R = list(csv.DictReader(open(LAB, encoding='utf-8')))
    for r in R:
        for k in ('W', 'H', 'xtl', 'ytl', 'xbr', 'ybr', 'npts'): r[k] = int(r[k])
        r['kind'] = r['zip_kind']; r['dis'] = int(r['disease'])
        m = re.match(r'(\d{4})/(\d{2})/(\d{2})$', r['date'] or ''); r['ym'] = f'{m[1]}-{m[2]}' if m else '결측'
        fd = r['fdate']
        if r['kind'] == '정상' and re.fullmatch(r'\d{6}', fd): fd = '20' + fd           # 201202 → 20201202
        r['gdate'] = r['date'].replace('/', '') if r['date'] else fd
        r['gk'] = f'{r["zip_crop"]}_{r["gid"]}' if r['kind'] == '질병' else f'{r["zip_crop"]}_{r["gid"]}_{r["gdate"]}'
        r['sn'] = int(re.match(r'\d+', r['seq'])[0]) if re.match(r'\d+', r['seq']) else -1
    return R


def issues(r):
    """이상 라벨 사유 목록 (제외 규칙 후보)."""
    out = []
    zc = r['zip_crop']
    if str(CROPS[zc]) != r['crop']: out.append('작물 코드가 zip과 다름')
    if r['kind'] == '정상':
        if r['dis'] != 0 or r['fdis'] != '00': out.append('정상인데 질병 코드')
        if r['type'] == '1': out.append('정상인데 JSON type=1')
        if r['risk'] != '0' or r['frisk'] != '0': out.append('정상인데 risk>0/파일명 risk 이상')
        if r['region']: out.append('정상인데 region 있음')
    else:
        if r['dis'] not in DIS_OF[zc]: out.append('질병 코드가 코드표 밖')
        if str(r['dis']).zfill(2) != r['fdis']: out.append('JSON 질병 코드 ≠ 파일명')
        if r['risk'] in ('0', ''): out.append('질병인데 risk 0')
        if r['risk'] != r['frisk']: out.append('JSON risk ≠ 파일명')
    return out


def regular_name(r):
    p = re.sub(r'\.(jpe?g|png)$', '', r['image'], flags=re.I).split('_')
    if r['kind'] == '질병': return len(p) >= 11 and re.fullmatch(r'\d{8}', p[9]) is not None
    return len(p) in (12, 13) and re.fullmatch(r'\d{8}', p[9]) is not None and re.fullmatch(r'\d{4}', p[10]) is not None and re.fullmatch(r'S\d+', p[11]) is not None


def spaced_n(n_items, n):  # 균등 추출 가능 개수
    return min(n_items, n)


def fair_share(sizes, total):
    out = [0] * len(sizes); left = total; open_ = [i for i, s in enumerate(sizes) if s > 0]
    while left > 0 and open_:
        share = max(1, left // len(open_)); nxt = []
        for i in open_:
            t = min(share, sizes[i] - out[i], left); out[i] += t; left -= t
            if out[i] < sizes[i]: nxt.append(i)
            if left == 0: break
        open_ = nxt
    return out


def main():
    os.makedirs(DOC, exist_ok=True)
    R = load()
    OUT.append('# 146 EDA 표 (자동 생성: ml/vision/experiments/eda_146.py)\n\n라벨 JSON %d개 (zip에서 읽음). 이미지는 열지 않았다.' % len(R))

    # ---- A. 장수
    rows = []
    for crop in CROPS:
        for kind in ('정상', '질병'):
            t = sum(1 for r in R if r['zip_crop'] == crop and r['kind'] == kind and r['split'] == 'Training')
            v = sum(1 for r in R if r['zip_crop'] == crop and r['kind'] == kind and r['split'] == 'Validation')
            rows.append((crop, kind, f'{t:,}', f'{v:,}', f'{t + v:,}'))
    rows.append(('합계', '정상', '49,172', '6,153', '55,325')); rows.append(('합계', '질병', '10,843', '1,358', '12,201'))
    md('A1. 작물 × 정상/질병 × 분할 (라벨 = 원천 수)', ['작물', '구분', 'Training', 'Validation', '합'], rows)

    # ---- B. 코드표
    md('B1. 작물 코드 (JSON crop) × zip 작물', ['zip 작물', 'JSON crop', '파일명 crop', '장수'], [(a, b, d, f'{n:,}') for (a, b, d), n in sorted(c((r['zip_crop'], r['crop'], r['fcrop']) for r in R).items())])
    rows = []
    for (crop, kind, d, fd), n in sorted(c((r['zip_crop'], r['kind'], r['dis'], r['fdis']) for r in R).items()):
        ok = (d == 0 and kind == '정상') or (kind == '질병' and d in DIS_OF[crop] and str(d).zfill(2) == fd)
        rows.append((crop, kind, d, fd, f'{n:,}', '코드표 안' if ok else '**잡음/불일치**'))
    md('B2. 질병 코드 (JSON disease × 파일명 disease)', ['zip 작물', '구분', 'JSON 코드', '파일명 코드', '장수', '판정'], rows)
    tv = c((r['zip_crop'], r['dis'], r['split']) for r in R if r['kind'] == '질병' and r['dis'] in DIS_OF[r['zip_crop']] and str(r['dis']).zfill(2) == r['fdis'])
    md('B3. 질병 클래스별 장수 (코드표 안, JSON=파일명)', ['작물', '질병 코드', 'Training', 'Validation', '합'],
       [(cr, d, f'{tv[(cr, d, "Training")]:,}', f'{tv[(cr, d, "Validation")]:,}', f'{tv[(cr, d, "Training")] + tv[(cr, d, "Validation")]:,}') for cr in CROPS for d in DIS_OF[cr]])

    # ---- C. 이상 라벨
    iss = c(); iss_rows = c(); bad_name = c()
    for r in R:
        ii = issues(r); r['bad'] = ii
        for i in ii: iss[(r['zip_crop'], r['kind'], i)] += 1
        if ii: iss_rows[(r['kind'])] += 1
        if not regular_name(r): bad_name[(r['zip_crop'], r['kind'])] += 1
    md('C1. 라벨 이상 (한 행에 여러 사유 가능)', ['작물', '구분', '사유', '장수'], [(a, b, d, n) for (a, b, d), n in sorted(iss.items())])
    md('C2. 파일명 규칙 밖 (정상: 8자리 날짜+4자리 번호+S0n[_n], 질병: 날짜 8자리)', ['작물', '구분', '장수'], [(a, b, n) for (a, b), n in sorted(bad_name.items())])
    md('C3. JSON type 값 (질병 zip은 전부 null)', ['구분', 'type', '장수'], [(a, b or 'null', n) for (a, b), n in sorted(c((r['kind'], r['type']) for r in R).items())])
    md('C4. 이미지 확장자', ['구분', '확장자', '장수'], [(a, b, f'{n:,}') for (a, b), n in sorted(c((r['kind'], r['fext']) for r in R).items())])
    md('C5. JSON 부위(area) vs 파일명 부위 (질병만 어긋남)', ['작물', '구분', '파일명 area', 'JSON area', '장수'],
       [(cr, k, f, j or '빈값', n) for (cr, k, f, j), n in sorted(c((r['zip_crop'], r['kind'], r['farea'], r['area']) for r in R if r['kind'] == '질병').items(), key=lambda x: (-x[1]))[:20]],
       note='JSON area를 질병에서는 신뢰하기 어렵다 (정상은 JSON area = 파일명 area가 99.9% 일치). 상위 20개 조합만.')

    good = [r for r in R if not r['bad']]
    # ---- D. bbox
    ins = c(); ratio = collections = {}
    ar = {}
    for r in R:
        W, H = r['W'], r['H']; x1, y1 = r['xbr'], r['ybr']
        a = x1 <= W * 1.01 and y1 <= H * 1.01; b = x1 <= H * 1.01 and y1 <= W * 1.01
        r['bb'] = 'in' if a else 'swap' if b else 'out'
        if r['bb'] == 'swap': W, H = H, W
        r['ratio'] = (r['xbr'] - r['xtl']) * (r['ybr'] - r['ytl']) / (W * H)
        r['asp'] = (r['xbr'] - r['xtl']) / max(1, r['ybr'] - r['ytl'])
        ins[(r['zip_crop'], r['kind'], r['bb'])] += 1
    md('D1. bbox가 JSON 해상도 안에 들어가나 (swap = W,H를 바꿔야 들어감 = EXIF 회전 뒤 좌표)', ['작물', '구분', '안', 'swap', '밖'],
       [(cr, k, ins[(cr, k, 'in')], ins[(cr, k, 'swap')], ins[(cr, k, 'out')]) for cr in CROPS for k in ('정상', '질병')])
    rows = []; figd = {}
    for cr in CROPS:
        for k in ('정상', '질병'):
            v = [r['ratio'] for r in R if r['zip_crop'] == cr and r['kind'] == k]; figd[(cr, k)] = v
            asp = [r['asp'] for r in R if r['zip_crop'] == cr and r['kind'] == k]
            rows.append((cr, k, len(v), *(f'{pct(v, q):.2f}' for q in (5, 25, 50, 75, 95)), f'{pct(asp, 50):.2f}', f'{np.mean(np.array(v) < 0.02):.1%}'))
    md('D2. bbox 면적비 / 종횡비 (회전 보정 뒤)', ['작물', '구분', '장수', 'p5', 'p25', '중앙', 'p75', 'p95', '가로/세로 중앙', '<0.02'], rows)
    rows = []
    for cr in CROPS:
        for d in DIS_OF[cr]:
            v = [r['ratio'] for r in R if r['zip_crop'] == cr and r['kind'] == '질병' and r['dis'] == d and not r['bad']]
            rows.append((cr, d, len(v), f'{pct(v, 25):.2f}', f'{pct(v, 50):.2f}', f'{pct(v, 75):.2f}'))
    md('D3. 질병 클래스별 면적비', ['작물', '질병', '장수', 'p25', '중앙', 'p75'], rows)
    try:
        import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
        plt.rcParams['font.family'] = 'Malgun Gothic'; plt.rcParams['axes.unicode_minus'] = False
        fig, ax = plt.subplots(1, 2, figsize=(10, 3.6), sharey=True)
        for i, cr in enumerate(CROPS):
            for k, col in (('정상', '#4c78a8'), ('질병', '#e45756')):
                ax[i].hist(figd[(cr, k)], bins=40, range=(0, 1), alpha=.6, color=col, density=True, label=k)
            ax[i].set_title(f'{cr} bbox 면적비'); ax[i].set_xlabel('bbox 면적 / 이미지 면적'); ax[i].legend()
        fig.tight_layout(); fig.savefig(f'{DOC}/fig_bbox_ratio.png', dpi=110); plt.close(fig)
    except Exception as e:  # noqa: BLE001
        OUT.append(f'\n(그림 실패: {e!r})')

    # ---- E. 부위·위험도·지역·시기·성장단계 (좋은 행만)
    def dist(rs, key, top=8):
        n = len(rs); cc = c(key(r) for r in rs)
        return ' · '.join(f'{k} {v / n:.0%}' for k, v in cc.most_common(top)) if n else '-'
    for title, key in (('E1. 부위 (파일명 area. 01 열매 · 03 잎 · 04·05 = 시트로 확인)', lambda r: r['farea']),
                       ('E2. 위험도 risk', lambda r: r['frisk']), ('E3. 지역 region', lambda r: r['region'] or '빈값'),
                       ('E4. 촬영 월 (JSON date)', lambda r: r['ym']), ('E5. 성장단계 grow', lambda r: r['grow'])):
        md(title, ['작물', '정상', '질병'], [(cr, dist([r for r in good if r['zip_crop'] == cr and r['kind'] == '정상'], key), dist([r for r in good if r['zip_crop'] == cr and r['kind'] == '질병'], key)) for cr in CROPS], note='이상 라벨 제외 뒤 비율.')
    rows = []
    for cr in CROPS:
        for d in DIS_OF[cr]:
            rs = [r for r in good if r['zip_crop'] == cr and r['kind'] == '질병' and r['dis'] == d]
            rows.append((cr, d, len(rs), dist(rs, lambda r: r['farea'], 4), dist(rs, lambda r: r['frisk'], 3), dist(rs, lambda r: r['region'] or '빈값', 4), dist(rs, lambda r: r['ym'], 3)))
    md('E6. 질병 클래스별 부위·위험도·지역·월', ['작물', '질병', '장수', '부위', 'risk', '지역', '월'], rows)
    nrows = []
    for cr in CROPS:
        for ar_ in ('01', '03', '04', '05'):
            n = sum(1 for r in good if r['zip_crop'] == cr and r['kind'] == '정상' and r['farea'] == ar_); m = sum(1 for r in good if r['zip_crop'] == cr and r['kind'] == '질병' and r['farea'] == ar_)
            nrows.append((cr, ar_, f'{n:,}', f'{m:,}'))
    md('E7. 파일명 부위별 정상/질병 장수 (좋은 행)', ['작물', '부위', '정상', '질병'], nrows)
    rows = []
    for cr in CROPS:
        for ar_ in ('01', '03', '04', '05'):
            rn = [r for r in good if r['zip_crop'] == cr and r['kind'] == '정상' and r['farea'] == ar_]; rd = [r for r in good if r['zip_crop'] == cr and r['kind'] == '질병' and r['farea'] == ar_]
            rows.append((cr, ar_, dist(rn, lambda r: r['ym'], 4), dist(rd, lambda r: r['ym'], 4)))
    md('E8. 부위별 촬영 월 (정상 vs 질병): 같은 부위끼리 시기가 다른가', ['작물', '부위', '정상 월', '질병 월'], rows)

    # ---- F. 묶음
    dis = [r for r in good if r['kind'] == '질병']; nor = [r for r in good if r['kind'] == '정상']
    rows = []
    for cr in CROPS:
        for d in DIS_OF[cr]:
            rs = [r for r in dis if r['zip_crop'] == cr and r['dis'] == d]
            g = {r['gk'] for r in rs}; gt = {r['gk'] for r in rs if r['split'] == 'Training'}; gv = {r['gk'] for r in rs if r['split'] == 'Validation'}
            sizes = sorted(c(r['gk'] for r in rs).values())
            rows.append((cr, d, f'{len(rs):,}', len(g), len(gt), len(gv), len(gt & gv), f'{sizes[0]}/{int(S.median(sizes))}/{sizes[-1]}', f'{len(rs) / len(g):.0f}'))
    md('F1. 질병 클래스별 대상ID (좋은 행)', ['작물', '질병', '장수', '대상ID', 'Train', 'Val', '양쪽', '대상당 장수 최소/중앙/최대', '평균 장수/대상'], rows)
    spl = C.defaultdict(set)
    for r in dis: spl[r['gk']].add(r['split'])
    nboth = sum(len(v) == 2 for v in spl.values()); nval = sum(v == {'Validation'} for v in spl.values())
    OUT.append(f'\n- 질병 대상ID {len(spl)}개 중 Training·Validation 양쪽 {nboth}개, Validation에만 {nval}개 (153: 111개 중 109, 147: 85개 중 79).')
    cls_of = C.defaultdict(set)
    for r in dis: cls_of[r['gk']].add(r['dis'])
    multi = {g for g, s in cls_of.items() if len(s) > 1}
    OUT.append(f'- 같은 대상ID가 둘 이상의 질병 클래스에 걸친 것: {len(multi)}/{len(cls_of)}개 ({", ".join(f"{cr} {sum(1 for g in multi if g.startswith(cr + chr(95)))}" for cr in CROPS)}).')
    day = C.defaultdict(set)
    for r in dis: day[(r['gk'], r['gdate'])].add(r['dis'])
    OUT.append(f'- 같은 (대상ID, 날짜)에서 병 둘 이상: {sum(len(s) > 1 for s in day.values())}/{len(day)}개.')
    # 대상 하나당 장수가 큰 편중
    sz = c(r['gk'] for r in dis); top = sz.most_common(5)
    OUT.append(f'- 대상ID당 질병 장수 상위 5: {top}. 대상 수 {len(sz)}, 중앙 {int(S.median(sz.values()))}장, 최대 {max(sz.values())}장.')
    # 연속 프레임: 같은 (gid,date)에서 번호 간격
    byd = C.defaultdict(list)
    for r in dis:
        if r['sn'] >= 0: byd[(r['gk'], r['gdate'])].append(r['sn'])
    gaps = c()
    for v in byd.values():
        v = sorted(set(v))
        for a, b in zip(v, v[1:]): gaps[min(b - a, 6)] += 1
    tg = sum(gaps.values())
    OUT.append(f'- 질병도 (대상, 날짜) 안에서 번호가 이어진다: 번호 간격 1이 {gaps[1] / tg:.0%}, 5 이하 {sum(gaps[k] for k in range(1, 6)) / tg:.0%}. (대상, 날짜) 묶음 {len(byd)}개.')
    rows = []
    for cr in CROPS:
        rs = [r for r in nor if r['zip_crop'] == cr]; gs = c(r['gk'] for r in rs); gid = {r['gid'] for r in rs}
        sp = C.defaultdict(set)
        for r in rs: sp[r['gk']].add(r['split'])
        sizes = sorted(gs.values()); bb = sum(len(v) == 2 for v in sp.values())
        gaps = c(); bg = C.defaultdict(list)
        for r in rs:
            if r['sn'] >= 0: bg[r['gk']].append(r['sn'])
        for v in bg.values():
            v = sorted(set(v))
            for a, b in zip(v, v[1:]): gaps[min(b - a, 6)] += 1
        tg = sum(gaps.values()) or 1
        rows.append((cr, f'{len(rs):,}', len(gs), len(gid), bb, f'{sizes[0]}/{int(S.median(sizes))}/{sizes[-1]}', f'{gaps[1] / tg:.0%}', f'{sum(gaps[k] for k in range(1, 6)) / tg:.0%}'))
    md('F2. 정상 묶음 (gid, 날짜)', ['작물', '정상 장수', '묶음', 'gid 수', 'Train·Val 둘 다인 묶음', '크기 최소/중앙/최대', '번호 간격 1', '간격 ≤5'], rows)
    # 정상 gid가 질병 gid와 겹치나
    dg = {r['gid'] for r in dis}; ng = {r['gid'] for r in nor}
    OUT.append(f'\n- 정상 대상ID(`a01`·`c25` 꼴)와 질병 대상ID(`0093w` 꼴)가 같은 값인 것: {len(dg & ng)}개 → 정상과 질병은 완전히 다른 식물·장소다.')

    # ---- G. 출처 편향 요약 (월)
    rows = []
    for cr in CROPS:
        for k in ('정상', '질병'):
            rs = [r for r in good if r['zip_crop'] == cr and r['kind'] == k]
            rows.append((cr, k, len(rs), dist(rs, lambda r: r['ym'], 6), dist(rs, lambda r: r['grow'], 4), dist(rs, lambda r: r['region'] or '빈값', 5)))
    md('G1. 출처 편향 수치 (월·성장단계·지역)', ['작물', '구분', '장수', '월', 'grow', '지역'], rows)

    # ---- H. 불균형
    def mf(ds):
        M = list(csv.DictReader(open(f'data/processed/{ds}/manifest.csv', encoding='utf-8-sig')))
        d_ = c(r['label'] for r in M if r['disease_code'] != '0'); n_ = c(r['crop_name'] for r in M if r['disease_code'] == '0')
        return len(M), sorted(d_.values()), sorted(n_.values()), len({r['crop_name'] for r in M})
    cmp_rows = []; base = {}
    for ds in ('153', '147'):
        n, d_, n_, nc = mf(ds); base[ds] = (n, d_, n_, nc)
        cmp_rows.append((ds, f'{n:,}', nc, len(d_), f'{d_[0]}/{int(S.median(d_))}/{d_[-1]}', f'{sum(d_):,}', f'{sum(n_):,}', f'{n_[0]}/{int(S.median(n_))}/{n_[-1]}'))
    gcount = {(r['zip_crop'], r['dis']): 0 for r in dis}
    # 선별 시뮬레이션 (질병 부위 5% 이상, 이상 제외 → 이 표본의 good 기준)
    dis_cls = {}
    for cr in CROPS:
        rs_c = [r for r in dis if r['zip_crop'] == cr]; ac = c(r['farea'] for r in rs_c); tot = sum(ac.values())
        areas = sorted(a for a, n in ac.items() if n / tot >= 0.05)
        for d in DIS_OF[cr]:
            g = c(r['gk'] for r in rs_c if r['dis'] == d and r['farea'] in areas); dis_cls[(cr, d)] = sorted(g.values())
        OUT.append(f'\n- {cr}: 질병 쓰는 부위(5% 이상) {areas} ({", ".join(f"{a} {ac[a] / tot:.0%}" for a in sorted(ac))})')
    cmp_sim = []
    pre = {}
    for cap in (None, 1500, 1000, 800, 600):
        d_sizes = {}
        for k, gsz in dis_cls.items():
            d_sizes[k] = sum(gsz) if cap is None else sum(fair_share(gsz, min(cap, sum(gsz))))
        dsum = {cr: sum(v for (c_, _), v in d_sizes.items() if c_ == cr) for cr in CROPS}
        for ncap in (None, 4000, 3000):
            nsum = {cr: (2 * dsum[cr] if ncap is None else min(2 * dsum[cr], ncap)) for cr in CROPS}
            dtot = sum(dsum.values()); ntot = sum(nsum.values()); tot = dtot + ntot; comb = tot + base['153'][0] + base['147'][0]
            cmp_sim.append(('없음' if cap is None else cap, '질병×2' if ncap is None else f'≤{ncap}/작물', f'{dtot:,}', f'{ntot:,}', f'{tot:,}', f'{tot / comb:.0%}', f'{max(d_sizes.values()):,}'))
    md('H1. 153·147 전처리 결과와 같은 척도 비교 (processed manifest 기준)', ['데이터셋', '이미지', '작물', '질병 클래스', '질병 클래스 장수 최소/중앙/최대', '질병 합', '정상 합', '작물당 정상 최소/중앙/최대'], cmp_rows + [('**146 (원본 라벨, 이상 제외·부위 선별 전)**', f'{len(good):,}', 2, 7, '/'.join(str(x) for x in (min(sum(v) for v in dis_cls.values()), int(S.median([sum(v) for v in dis_cls.values()])), max(sum(v) for v in dis_cls.values()))), f'{sum(sum(v) for v in dis_cls.values()):,}', f'{len(nor):,}', '-')])
    md('H2. 146 상한 시나리오 (질병 클래스 상한 = 대상ID 균등 분배, 정상 = 작물당 min(질병×2, 상한))', ['질병 클래스 상한', '정상 규칙', '146 질병', '146 정상', '146 합', '합친 전체 대비(153·147 현재 85,080장 가정)', '질병 최대 클래스'], cmp_sim)
    rows = [(cr, d, len(g), f'{sum(g):,}', g[0], int(S.median(g)), g[-1]) for (cr, d), g in sorted(dis_cls.items())]
    md('H3. 질병 클래스별 대상ID와 장수 (좋은 행, 부위 선별 뒤)', ['작물', '질병', '대상ID', '장수', '대상당 최소', '중앙', '최대'], rows)
    # 그림
    try:
        fig, ax = plt.subplots(1, 2, figsize=(11, 3.8))
        for ds, col in (('153', '#4c78a8'), ('147', '#54a24b')):
            ax[0].bar([f'{ds}-{i}' for i in range(len(base[ds][1]))], base[ds][1], color=col, label=f'{ds} 질병 클래스')
        ax[0].set_xticks([]); ax[0].set_ylabel('장수'); ax[0].set_title('153·147 질병 클래스 장수 (전처리 뒤)')
        ax[0].bar([f'146-{i}' for i in range(len(dis_cls))], sorted(sum(v) for v in dis_cls.values()), color='#e45756', label='146 질병 클래스')
        ax[0].legend()
        ax[1].bar(['153 정상', '147 정상', '146 정상(질병×2)'], [sum(base['153'][2]), sum(base['147'][2]), 2 * sum(sum(v) for v in dis_cls.values())], color=['#4c78a8', '#54a24b', '#e45756'])
        ax[1].set_title('정상 합계'); fig.tight_layout(); fig.savefig(f'{DOC}/fig_imbalance.png', dpi=110); plt.close(fig)
    except Exception as e:  # noqa: BLE001
        OUT.append(f'\n(그림 실패 {e!r})')
    open(f'{DOC}/tables.md', 'w', encoding='utf-8').write('\n'.join(OUT) + '\n')
    print('\n'.join(OUT))


if __name__ == '__main__':
    main()
