"""주간 가격 예측 조회와 판매 추천 계산 (REQ-PRD-001~003, REQ-REC-001~003, REQ-REC-005)."""
import math
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated

from api.responses import error, ok
from codes.models import Holiday, Item, Market, MarketClosure

from .models import Forecast
from .views import _bad, _get_item, _kst_iso, _price, _today_kst, market_prices

# 명절 이름. holiday 테이블에는 공휴일 전체가 들어 있어 이름으로 명절만 고른다 (결정 0009)
HOLIDAY_KEYWORDS = ('설날', '추석')
# 대상 주가 명절에서 이 일수 안이면 주의 문구를 붙인다 (REQ-PRD-003 "명절 3주 이내")
HOLIDAY_NOTICE_DAYS = 21
HOLIDAY_NOTICE = '명절 전후에는 가격이 크게 오를 수 있으나, 이 예측은 명절 급등 폭을 낮게 잡는 경향이 있습니다.'
NO_FORECAST_NOTICE = '이 품목은 아직 가격 예측을 제공하지 않습니다.'
EARTH_RADIUS_KM = 6371.0


def _holiday_dates(weeks):
    """대상 주 목록 앞뒤 21일 안의 명절 날짜들."""
    if not weeks:
        return []
    lo, hi = min(weeks) - timedelta(days=HOLIDAY_NOTICE_DAYS), max(weeks) + timedelta(days=6 + HOLIDAY_NOTICE_DAYS)
    name_q = Q()
    for word in HOLIDAY_KEYWORDS:
        name_q |= Q(name__contains=word)
    return list(Holiday.objects.filter(name_q, holiday_date__range=(lo, hi)).values_list('holiday_date', flat=True))


def _holiday_near(week, holidays):
    """대상 주(월~일)에서 명절까지 거리가 21일 이내인지."""
    end = week + timedelta(days=6)
    return any(week - timedelta(days=HOLIDAY_NOTICE_DAYS) <= d <= end + timedelta(days=HOLIDAY_NOTICE_DAYS)
               for d in holidays)


@api_view(['GET'])
@authentication_classes([])
@permission_classes([])
def forecasts(request):
    """가장 최근 기준 주의 예측 (REQ-PRD-001~003). 예측값·80% 구간·명절 주의 문구.

    예측 대상이 아닌 품목은 200 + forecast_available false (api.md 1.5). 대상인데 예측이 없으면 503.
    """
    params = request.query_params
    details = {}
    item = _get_item(params.get('item_id', ''), details)
    if details:
        return _bad(details)
    if item is False:
        return error(404, 'NOT_FOUND', '없는 품목입니다.')
    market_id = params.get('market_id')
    if market_id and not Market.objects.filter(pk=market_id).exists():
        return error(404, 'NOT_FOUND', '없는 시장입니다.')

    meta = {'item_id': item.item_id, 'price_unit': '원/kg'}
    if not item.is_forecast:
        return ok([], {**meta, 'forecast_available': False, 'message': NO_FORECAST_NOTICE})

    rows = Forecast.objects.filter(item=item)
    if market_id:
        rows = rows.filter(market_id=market_id)
    base_week = rows.order_by('-base_week').values_list('base_week', flat=True).first()
    if base_week is None:
        if market_id:
            # 이 품목의 예측은 있어도 그 시장 것만 없으면(참고 시장 등) 기다려도 생기지 않는다 → 정상 빈 결과
            if Forecast.objects.filter(item=item).exists():
                return ok([], {**meta, 'forecast_available': True})
        return error(503, 'DATA_NOT_READY', '이번 주 가격 예측이 아직 준비되지 않았습니다.')
    rows = list(rows.filter(base_week=base_week).select_related('market')
                .order_by('market_id', 'horizon'))
    holidays = _holiday_dates({r.target_week for r in rows})

    data = []
    for r in rows:
        notice = HOLIDAY_NOTICE if _holiday_near(r.target_week, holidays) else None
        data.append({
            'market_id': r.market_id, 'market_name': r.market.name, 'horizon': r.horizon,
            'target_week': r.target_week.isoformat(), 'pred_price': _price(r.pred_price),
            'lower80': _price(r.lower80), 'upper80': _price(r.upper80),
            'last_week_price': _price(r.last_week_price), 'holiday_notice': notice})
    first = rows[0]
    today = _today_kst()
    return ok(data, {**meta, 'forecast_available': True, 'base_week': base_week.isoformat(),
                     # 이번 주 월요일보다 이른 기준 주면 이번 주 예측 작업이 아직 안 돈 것
                     'is_stale': base_week < today - timedelta(days=today.weekday()),
                     'model_version': first.model_version, 'created_at': _kst_iso(first.created_at)})


class RecommendationSerializer(serializers.Serializer):
    """판매 추천 입력. 비용 값을 보내면 내 기본값(user_profile) 대신 쓴다 (REQ-REC-002)."""
    item_id = serializers.IntegerField(min_value=1, max_value=2 ** 31 - 1)
    volume_kg = serializers.DecimalField(max_digits=12, decimal_places=1, min_value=Decimal('0.1'))
    desired_week = serializers.DateField(required=False)
    loss_rate = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100,
                                         required=False)
    transport_cost_per_km = serializers.IntegerField(min_value=0, max_value=10_000_000, required=False)
    storage_cost_per_week = serializers.IntegerField(min_value=0, max_value=10_000_000, required=False)
    commission_rate = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100,
                                               required=False)


def _distance_km(lat1, lng1, lat2, lng2):
    """두 좌표 사이 직선거리 (km, haversine)."""
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp, dl = p2 - p1, math.radians(float(lng2) - float(lng1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _won(value):
    """원 단위 반올림 (사사오입)."""
    return int(Decimal(str(value)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def calculate(row, distance_km, volume, loss_rate, per_km, per_week, commission_rate):
    """한 시장 × 시점의 손에 남는 돈 (REQ-REC-002).

    예측가격 × (물량 × (1 − 감모율)) − 수수료 − 운송비(거리 × 단가, 한 번) − 보관비(주당 × 보관 주수).
    보관 주수는 이번 주(horizon 1)가 0이고 한 주 늦출 때마다 1주씩 늘어난다.
    """
    sellable = volume * (1 - loss_rate / 100)
    transport = Decimal(str(distance_km)) * per_km if distance_km is not None else Decimal(0)
    storage = per_week * (row.horizon - 1)

    def net(price):
        revenue = price * sellable
        return revenue - revenue * commission_rate / 100 - transport - storage

    revenue = row.pred_price * sellable
    return {
        'sellable_kg': float(sellable.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)),
        'revenue_won': _won(revenue), 'commission_won': _won(revenue * commission_rate / 100),
        'transport_won': _won(transport), 'storage_won': _won(storage),
        'net_won': _won(net(row.pred_price)),
        'net_low_won': _won(net(row.lower80)), 'net_high_won': _won(net(row.upper80)),
    }


@api_view(['POST'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def recommendations(request):
    """판매 추천 계산 (REQ-REC-001~003, 005). 시장 × 시점별 손에 남는 돈을 큰 순서로 돌려준다.

    예측 대상이 아닌 품목은 지금 기준 시장 비교만 돌려준다 (forecast_available false).
    """
    serializer = RecommendationSerializer(data=request.data)
    if not serializer.is_valid():
        return error(400, 'VALIDATION_ERROR', '입력값을 확인해 주세요.', serializer.errors)
    v = serializer.validated_data
    item = Item.objects.filter(pk=v['item_id']).first()
    if item is None:
        return error(404, 'NOT_FOUND', '없는 품목입니다.')
    status, data, meta = compute_recommendation(request.user, item, v)
    if status != 200:
        return error(503, 'DATA_NOT_READY', '이번 주 가격 예측이 아직 준비되지 않았습니다.')
    return ok(data, meta)


def compute_recommendation(user, item, v):
    """추천 계산 본체. API와 채팅 판매 상담(Y13)이 함께 쓴다.

    v: 검증된 입력 dict (volume_kg 필수, desired_week·비용 값은 선택). 반환: (200, data, meta) 또는 (503, None, None)
    """
    if not item.is_forecast:
        comparison, day = market_prices(item, 'ALL')
        return 200, {'forecast_available': False, 'message': NO_FORECAST_NOTICE, 'results': [],
                     'market_comparison': comparison}, \
            {'item_id': item.item_id, 'date': day.isoformat() if day else None, 'price_unit': '원/kg'}

    rows = Forecast.objects.filter(item=item)
    base_week = rows.order_by('-base_week').values_list('base_week', flat=True).first()
    if base_week is None:
        return 503, None, None
    today = _today_kst()
    # 이미 지난 주는 추천하지 않는다 (이번 주 예측 작업이 안 돌아 지난주 예측이 남아 있을 때)
    rows = [r for r in rows.filter(base_week=base_week).select_related('market')
            if r.target_week + timedelta(days=6) >= today]
    if not rows:
        return 503, None, None

    profile = getattr(user, 'userprofile', None)
    use_profile = profile is not None

    def pick(name, default):
        if name in v:
            return v[name]
        value = getattr(profile, name, None) if use_profile else None
        return default if value is None else value

    loss_rate = Decimal(pick('loss_rate', 0))
    per_km = Decimal(pick('transport_cost_per_km', 0))
    per_week = Decimal(pick('storage_cost_per_week', 0))
    commission_rate = Decimal(v.get('commission_rate', 0))
    volume = Decimal(v['volume_kg'])
    has_location = use_profile and profile.lat is not None and profile.lng is not None

    weeks = {r.target_week for r in rows}
    holidays = _holiday_dates(weeks)
    closures = {}
    if rows:
        lo, hi = min(weeks), max(weeks) + timedelta(days=6)
        for market_id, d in (MarketClosure.objects.filter(closure_date__range=(lo, hi), market__in={r.market_id for r in rows})
                             .values_list('market_id', 'closure_date')):
            closures.setdefault(market_id, []).append(d)

    results = []
    for r in rows:
        distance = _distance_km(profile.lat, profile.lng, r.market.lat, r.market.lng) if has_location else None
        calc = calculate(r, distance, volume, loss_rate, per_km, per_week, commission_rate)
        week_end = r.target_week + timedelta(days=6)
        closed = sorted(d for d in closures.get(r.market_id, []) if r.target_week <= d <= week_end)
        results.append({
            'market_id': r.market_id, 'market_name': r.market.name, 'horizon': r.horizon,
            'target_week': r.target_week.isoformat(),
            'is_desired': 'desired_week' in v and r.target_week <= v['desired_week'] <= week_end,
            'pred_price': _price(r.pred_price), 'lower80': _price(r.lower80), 'upper80': _price(r.upper80),
            'last_week_price': _price(r.last_week_price),
            'distance_km': round(distance, 1) if distance is not None else None,
            **calc,
            'is_closed': bool(closed), 'closed_dates': [d.isoformat() for d in closed],
            'holiday_notice': HOLIDAY_NOTICE if _holiday_near(r.target_week, holidays) else None,
        })
    results.sort(key=lambda x: (-x['net_won'], x['market_id'], x['horizon']))
    for rank, row in enumerate(results, 1):
        row['rank'] = rank

    first = rows[0]
    meta = {'item_id': item.item_id, 'volume_kg': float(volume), 'base_week': base_week.isoformat(),
            'model_version': first.model_version, 'created_at': _kst_iso(first.created_at),
            'price_unit': '원/kg',
            'costs': {'loss_rate': float(loss_rate), 'transport_cost_per_km': int(per_km),
                      'storage_cost_per_week': int(per_week), 'commission_rate': float(commission_rate),
                      'transport_applied': has_location}}
    return 200, {'forecast_available': True, 'results': results}, meta
