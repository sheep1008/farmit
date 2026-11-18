"""시세 상담 근거: "9월 14일 주에 왜 가격이 높았어?" 같은 질문에 쓸 사실을 DB에서 모은다 (REQ-CHT-009).

LLM에게는 이 함수가 만든 사실만 근거로 준다. 숫자는 모두 여기서 계산하고, LLM은 설명만 한다.
근거는 채팅 출처 모양({n, title, source_label, url, source_type, text})이라 [근거 n] 인용·출처 표시를 그대로 쓴다.

모으는 사실 (있는 것만):
1. 물은 주 앞뒤 주간 가격·물량 (질문에 나온 시장 → 화면에서 보던 시장 → 전국 물량가중)
2. 1년 전 같은 시기 가격·물량
3. 가까운 명절 (설날·추석, 대상 주 앞뒤 21일)
4. 물은 주 6주 전~그 주에 주산지에서 있었던 날씨·병해충·수입 사건 (past_case)
5. 그해·전년 생산량 (공표된 것만)
"""
import re
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import F, Q, Sum

from alerts.models import PastCase
from codes.models import Holiday, Market
from prices.forecast_views import HOLIDAY_KEYWORDS, HOLIDAY_NOTICE_DAYS
from prices.models import CropProduction, SettlePrice

WEEKS_BEFORE = 4      # 물은 주 앞으로 볼 주 수
WEEKS_AFTER = 3       # 뒤로 볼 주 수
EVENT_LOOKBACK_DAYS = 42
SOURCE_LABEL = '팜잇 (aT 정산가격)'


def monday(d):
    return d - timedelta(days=d.weekday())


def find_market(question):
    """질문에 나온 시장 이름 (긴 이름부터). 없으면 None. 이름은 market 테이블에서 읽는다."""
    for m in sorted(Market.objects.all(), key=lambda m: len(m.name), reverse=True):
        if m.name in question:
            return m
    return None


def weekly_prices(item, start, end, market=None):
    """[start, end] 주간 가격 {월요일: (원/kg, kg)}. 전 등급(ALL) 물량가중 평균."""
    qs = SettlePrice.objects.filter(item=item, grade='ALL', trade_date__range=(start, end))
    if market:
        qs = qs.filter(market=market)
    weeks = {}
    for r in qs.values('trade_date').annotate(v=Sum('volume_kg'), pv=Sum(F('avg_price') * F('volume_kg'))):
        w = monday(r['trade_date'])
        v, pv = weeks.get(w, (Decimal(0), Decimal(0)))
        weeks[w] = (v + r['v'], pv + r['pv'])
    return {w: (float(pv / v), float(v)) for w, (v, pv) in sorted(weeks.items()) if v}


def _won(v):
    return f'{round(v):,}원/kg'


def _ton(kg):
    return f'{kg / 1000:,.1f}톤'


def _price_lines(weeks, target):
    lines = []
    for w, (p, v) in weeks.items():
        mark = ' ← 물은 주' if w == target else ''
        lines.append(f'- {w.isoformat()} 주: {_won(p)}, 거래 물량 {_ton(v)}{mark}')
    return lines


def _trend_fact(weeks, target, place):
    """물은 주가 앞뒤 주와 비교해 어땠는지 한두 문장 (최고·최저, 앞 4주 평균 대비 %)."""
    if target not in weeks:
        return [f'물은 주({target.isoformat()})에는 {place} 거래 기록이 없습니다.']
    p, v = weeks[target]
    before = [weeks[w][0] for w in weeks if w < target]
    out = []
    prices = [x[0] for x in weeks.values()]
    vols = [x[1] for x in weeks.values()]
    if p == max(prices):
        out.append(f'물은 주의 가격이 앞뒤 {len(weeks)}주 중 가장 높았습니다.')
    if v == max(vols):
        out.append(f'물은 주의 거래 물량도 앞뒤 {len(weeks)}주 중 가장 많았습니다.')
    if before:
        avg = sum(before) / len(before)
        out.append(f'앞 {len(before)}주 평균({_won(avg)})보다 {(p / avg - 1) * 100:+.1f}% 였습니다.')
    after = [weeks[w][0] for w in weeks if w > target]
    if after:
        out.append(f'바로 다음 주 가격은 {_won(after[0])}로 {(after[0] / p - 1) * 100:+.1f}% 바뀌었습니다.')
    return out


def holidays_near(target):
    """물은 주(월~일) 앞뒤 21일 안의 명절 [(이름, 첫날, 끝날)]."""
    lo, hi = target - timedelta(days=HOLIDAY_NOTICE_DAYS), target + timedelta(days=6 + HOLIDAY_NOTICE_DAYS)
    q = Q()
    for word in HOLIDAY_KEYWORDS:
        q |= Q(name__contains=word)
    groups = {}
    for d, name in Holiday.objects.filter(q, holiday_date__range=(lo, hi)).order_by('holiday_date').values_list(
            'holiday_date', 'name'):
        key = '설날' if '설' in name else '추석'
        first, last = groups.get(key, (d, d))
        groups[key] = (min(first, d), max(last, d))
    return [(k, a, b) for k, (a, b) in groups.items()]


def events_before(item, target):
    """물은 주 6주 전 ~ 그 주 끝에 시작한 사건 (시장마다 같은 사건이 들어 있어 사건 단위로 한 번만)."""
    rows = (PastCase.objects.filter(item=item, event_start__range=(target - timedelta(days=EVENT_LOOKBACK_DAYS),
                                                                    target + timedelta(days=6)))
            .order_by('event_start').values('event_type', 'sido', 'event_start', 'event_end', 'detail'))
    seen, out = set(), []
    for r in rows:
        key = (r['event_type'], r['event_start'])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def build(item, target_date, question, today, market=None):
    """시세 상담 근거 목록. 대상 주에 거래가 하나도 없으면 빈 목록.
    시장: 질문에 나온 시장 → 화면에서 보던 시장(market) → 전국 합계."""
    target = monday(target_date)
    market = find_market(question) or market
    place = f'{market.name} 시장' if market else '전국 공영도매시장 합계'
    start, end = target - timedelta(weeks=WEEKS_BEFORE), min(target + timedelta(weeks=WEEKS_AFTER, days=6), today)
    weeks = weekly_prices(item, start, end, market)
    if not weeks:
        return []
    evidence = []

    def add(title, lines):
        evidence.append({'n': len(evidence) + 1, 'title': title, 'source_label': SOURCE_LABEL, 'url': '',
                         'source_type': 'price_fact', 'text': '\n'.join(lines)})

    add(f'{item.name} 주간 가격 · {place} ({start.isoformat()} ~ {end.isoformat()})',
        [f'{place}, 전 등급 물량가중 평균 가격과 거래 물량'] + _price_lines(weeks, target) + _trend_fact(weeks, target, place))

    # 1년 전 같은 시기 (52주 전 = 같은 요일)
    ly = {w + timedelta(weeks=52): x for w, x in
          weekly_prices(item, start - timedelta(weeks=52), end - timedelta(weeks=52), market).items()}
    if target in ly and target in weeks:
        p, v = weeks[target]
        lp, lv = ly[target]
        add(f'{item.name} 1년 전 같은 시기 가격 · {place}',
            [f'1년 전 같은 주({(target - timedelta(weeks=52)).isoformat()} 주): {_won(lp)}, 거래 물량 {_ton(lv)}',
             f'물은 주는 1년 전보다 가격 {(p / lp - 1) * 100:+.1f}%, 거래 물량 {(v / lv - 1) * 100:+.1f}% 였습니다.'])

    hol = holidays_near(target)
    if hol:
        lines = []
        for name, a, b in hol:
            gap = (a - target).days
            when = (f'물은 주 월요일로부터 {gap}일 뒤' if gap > 0 else f'물은 주 월요일로부터 {-gap}일 전')
            lines.append(f'{name} 연휴: {a.isoformat()} ~ {b.isoformat()} ({when})')
        lines.append('명절 앞 2~3주는 선물·차례용 수요로 출하와 거래가 몰리는 시기입니다(팜잇 예측 화면의 명절 주의 기준: 명절 21일 이내).')
        add('가까운 명절', lines)

    evs = events_before(item, target)
    if evs:
        labels = dict(PastCase.EventType.choices)
        lines = []
        for e in evs:
            share = e['detail'].get('share')
            places = ', '.join(e['detail'].get('places', [])[:4])
            extra = f', 주산지 물량 비중 {share}%' if share is not None else ''
            lines.append(f"- {labels.get(e['event_type'], e['event_type'])}: {e['sido']} "
                         f"{e['event_start'].isoformat()} ~ {e['event_end'].isoformat()}{extra}"
                         + (f' (지역: {places})' if places else ''))
        add(f'물은 주 6주 전부터 주산지 날씨·병해충·수입 사건', lines)

    prods = {p.year: p for p in CropProduction.objects.filter(
        item=item, year__in=[target.year - 1, target.year], kosis_updated_on__lte=today)}
    if prods:
        lines = [f'- {y}년 생산량 {p.production_kg / 1_000_000:,.1f}천 톤' for y, p in sorted(prods.items())
                 if p.production_kg]
        if len(lines) == 2:
            a, b = prods[target.year - 1].production_kg, prods[target.year].production_kg
            lines.append(f'{target.year}년 생산량은 전년보다 {(b / a - 1) * 100:+.1f}% 입니다.')
        if lines:
            add(f'{item.name} 생산량 (통계청)', lines)
    return evidence


def default_target(today):
    """물은 날짜가 없으면 지난주 (끝난 가장 최근 주)."""
    return monday(today) - timedelta(weeks=1)


_YEAR_WORDS = re.compile(r'(19|20)\d{2}\s*년|\d{2}년|작년|재작년|지난해|전년')


def parse_target(value, today, question=''):
    """분류기가 준 'YYYY-MM-DD' → date.
    질문에 연도("2025년"·"작년" 등)가 없으면 연도는 분류기를 믿지 않고 올해로 둔다 (분류기가 "9월 14일"을 작년으로 잡은 일이 있다).
    오늘 뒤의 날짜는 1년 전으로."""
    try:
        d = date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if not _YEAR_WORDS.search(question):
        try:
            d = d.replace(year=today.year)
        except ValueError:  # 2월 29일
            return None
    if d > today:
        try:
            d = d.replace(year=d.year - 1)
        except ValueError:
            return None
    return d
