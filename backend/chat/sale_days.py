"""판매 상담 날짜 추천 (REQ-CHT-002).

가격 예측은 주 단위라 "며칠에 팔까?"에 바로 답할 수 없다. 그래서 추천 주 안의 날짜는
그 시장의 최근 요일별 가격 패턴(요일 가격 ÷ 그 주 평균)으로 고른다. 숫자는 여기서 계산하고 LLM은 설명만 한다.
"""
from collections import defaultdict
from datetime import date, timedelta
from statistics import mean

from prices.models import SettlePrice

LOOKBACK_WEEKS = 12  # 요일 패턴을 볼 최근 주 수
MIN_WEEKS = 6        # 그 요일에 거래가 있던 주가 이보다 적으면 거래하는 요일로 보지 않는다
DAYS = 3             # 추천할 날짜 수
WEEKDAYS = '월화수목금토일'


def monday(d):
    return d - timedelta(days=d.weekday())


def weekday_pattern(item, market_id, today):
    """최근 LOOKBACK_WEEKS개 끝난 주의 요일별 {요일: (가격 ÷ 그 주 물량가중 평균의 평균, 거래가 있던 주 수)}."""
    this_week = monday(today)
    rows = (SettlePrice.objects
            .filter(item=item, market_id=market_id, grade='ALL', volume_kg__gt=0,
                    trade_date__range=(this_week - timedelta(weeks=LOOKBACK_WEEKS), this_week - timedelta(days=1)))
            .values_list('trade_date', 'avg_price', 'volume_kg'))
    weeks = defaultdict(list)
    for d, p, v in rows:
        weeks[monday(d)].append((d.weekday(), float(p), float(v)))
    ratios = defaultdict(list)
    for days in weeks.values():
        if len(days) < 2:  # 하루만 거래한 주는 비교할 평균이 없다
            continue
        avg = sum(p * v for _, p, v in days) / sum(v for _, _, v in days)
        for wd, p, _ in days:
            ratios[wd].append(p / avg)
    return {wd: (mean(r), len(r)) for wd, r in ratios.items() if len(r) >= MIN_WEEKS}


def pick_days(rows, pattern, today, n=DAYS):
    """한 시장의 추천 행(주) × 거래 요일 중 (그 주 예측가 × 요일 비율)이 큰 날짜 n개. 오늘·휴장일은 뺀다."""
    picks = []
    for r in rows:
        week = date.fromisoformat(r['target_week'])
        closed = set(r['closed_dates'])
        for wd, (ratio, weeks) in pattern.items():
            d = week + timedelta(days=wd)
            if d > today and d.isoformat() not in closed:
                picks.append({'date': d, 'ratio': ratio, 'weeks': weeks, 'row': r,
                              'score': r['pred_price'] * ratio})
    picks.sort(key=lambda p: (-p['score'], p['date']))
    return picks[:n]


def days_text(item, market_name, pattern, picks, asked):
    """LLM에 줄 [추천 날짜] 줄들. asked: 농가가 이번 또는 앞 질문에서 판매 날짜(며칠)를 물었는지."""
    head = (f'[추천 날짜] {market_name} 시장. 농가가 날짜를 물었음: {"예" if asked else "아니오"}. '
            f'예측은 주 단위라, 그 주 안의 날짜는 이 시장 {item.name}의 '
            f'최근 {LOOKBACK_WEEKS}주 요일별 가격(요일 가격 ÷ 그 주 평균)으로 골랐습니다. 요일 패턴은 예측이 아닙니다')
    if not picks:
        return [head, '- 최근 거래 기록이 적어 날짜를 고르지 못했습니다.']
    lines = [head]
    for i, p in enumerate(picks, 1):
        wd = WEEKDAYS[p['date'].weekday()]
        r = p['row']
        line = (f"- {i}. {p['date'].isoformat()}({wd}): 그 주({r['target_week']} 주) 예측가 {r['pred_price']}원/kg, "
                f"손에 남는 돈 {r['net_won']:,}원(그 주 기준). 최근 {LOOKBACK_WEEKS}주 중 {p['weeks']}주 {wd}요일 거래, "
                f"{wd}요일 가격은 주 평균보다 평균 {(p['ratio'] - 1) * 100:+.1f}%")
        if r.get('holiday_notice'):
            line += f" / 주의: {r['holiday_notice']}"
        lines.append(line)
    return lines
