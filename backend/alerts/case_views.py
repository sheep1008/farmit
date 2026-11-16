"""과거 사례 리포트 조회 (K18, REQ-HIS-001·002, api.md 2.4). 값은 batch/spark/past_case.py가 past_case에 채운다."""
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Avg, Count, Max
from rest_framework.decorators import api_view, authentication_classes, permission_classes

from api.responses import error, ok
from codes.models import Market
from prices.views import _bad, _get_item, _kst_iso, _price

from .models import PastCase

CASE_NOTICE = ('과거 사례는 참고 정보입니다. 사건과 가격 변화가 같은 시기에 있었다는 뜻일 뿐, '
               '사건이 가격 변화의 원인이라는 뜻은 아닙니다. 평년 값은 다른 해 같은 시기의 변화로, '
               '설 대목처럼 해마다 오는 계절 움직임과 나란히 보도록 함께 보여 줍니다.')
WEEKS = (1, 2, 3, 4)
FIELDS = [f'change_w{k}' for k in WEEKS] + [f'normal_w{k}' for k in WEEKS]
NAMES = dict(PastCase.EventType.choices)


def _pct(value):
    """변화율(%) → 소수 둘째 자리 숫자. 없으면 None."""
    if value is None:
        return None
    return float(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def _avg(rows):
    """시장 행들의 필드별 평균 (값이 있는 시장만)."""
    out = {}
    for f in FIELDS:
        vals = [getattr(r, f) for r in rows if getattr(r, f) is not None]
        out[f] = _pct(sum(vals) / len(vals)) if vals else None
    return out


@api_view(['GET'])
@authentication_classes([])
@permission_classes([])
def case_list(request):
    """품목의 과거 사례: 사건마다 시장별 기준가·1~4주 뒤 변화율·평년 변화율. 종류별 요약과 참고 문구를 meta에 담는다."""
    params = request.query_params
    details = {}
    item = _get_item(params.get('item_id', ''), details)
    event_type = params.get('event_type')
    if event_type is not None and event_type not in NAMES:
        details['event_type'] = [f'{", ".join(NAMES)} 중 하나여야 합니다.']
    if details:
        return _bad(details)
    if item is False:
        return error(404, 'NOT_FOUND', '없는 품목입니다.')
    market_id = params.get('market_id')
    if market_id and not Market.objects.filter(pk=market_id).exists():
        return error(404, 'NOT_FOUND', '없는 시장입니다.')

    base = PastCase.objects.filter(item=item)
    if market_id:
        base = base.filter(market_id=market_id)
    rows = base.filter(event_type=event_type) if event_type else base
    rows = rows.select_related('market').order_by('-event_start', 'event_type', 'market_id')

    data, index = [], {}
    for r in rows:
        key = (r.event_type, r.event_start)
        if key not in index:
            index[key] = len(data)
            data.append({
                'event_type': r.event_type, 'event_name': NAMES[r.event_type], 'sido': r.sido,
                'places': r.detail.get('places', []), 'share': r.detail.get('share'),
                'event_start': r.event_start.isoformat(), 'event_end': r.event_end.isoformat(),
                'base_week': r.base_week.isoformat(), 'markets': [], '_rows': [],
            })
        case = data[index[key]]
        case['markets'].append({'market_id': r.market_id, 'market_name': r.market.name,
                                'base_price': _price(r.base_price), **{f: _pct(getattr(r, f)) for f in FIELDS}})
        case['_rows'].append(r)
    for case in data:
        case['avg'] = _avg(case.pop('_rows'))

    summary = [
        {'event_type': s['event_type'], 'event_name': NAMES[s['event_type']], 'events': s['events'],
         **{f: _pct(s[f]) for f in FIELDS}}
        for s in base.values('event_type').annotate(events=Count('event_start', distinct=True),
                                                    **{f: Avg(f) for f in FIELDS}).order_by('event_type')
    ]
    computed = base.aggregate(at=Max('computed_at'))['at']
    meta = {'item_id': item.item_id, 'price_unit': '원/kg', 'change_unit': '%', 'computed_at': _kst_iso(computed),
            'notice': CASE_NOTICE, 'summary': summary}
    return ok(data, meta)
