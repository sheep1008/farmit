"""전국 시장 "지금 팔면" 실수령액 (REQ-REC-007, REC-002, REC-003).

예측 없이 최근 정산 가격으로 시장별 손에 남는 돈을 비교한다. 계산 본체(compute_sell_now)는
API와 채팅 "어디서 팔까?"(Y13)가 함께 쓸 수 있게 뷰와 분리했다.
"""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.conf import settings
from django.db.models import Max
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.throttling import SimpleRateThrottle

from api.responses import error, ok
from codes.models import Item, Market

from .forecast_views import NO_FORECAST_NOTICE, _distance_km, calculate
from .models import SettlePrice
from .views import _price, _today_kst

PRICE_WINDOW_DAYS = 7       # 가격: 기준일 포함 최근 7일 물량가중평균
ACTIVITY_WINDOW_DAYS = 14   # 거래 활동·최저/최고가: 최근 14일
NO_TRANSPORT_NOTICE = '내 위치 또는 운송비 단가가 없어 운송비를 반영하지 않았습니다.'
NO_COORD_NOTICE = '위치 정보가 없는 시장은 운송비를 반영하지 않았습니다 (순위가 높게 나올 수 있음).'
STALE_NOTICE = '가장 최근 정산일이 오래되어 지금 시세와 다를 수 있습니다.'


class SellNowSerializer(serializers.Serializer):
    item_id = serializers.IntegerField(min_value=1, max_value=2 ** 31 - 1)
    volume_kg = serializers.DecimalField(max_digits=12, decimal_places=1, min_value=Decimal('0.1'))
    grade = serializers.CharField(max_length=10, required=False)
    loss_rate = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100,
                                         required=False)
    transport_cost_per_km = serializers.IntegerField(min_value=0, max_value=10_000_000, required=False)
    commission_rate = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100,
                                               required=False)


def _has_coords(lat, lng):
    """새 시장 좌표가 0(미입력)이면 거리가 약 1만 km로 계산되므로 좌표 없음으로 본다."""
    return lat is not None and lng is not None and float(lat) != 0 and float(lng) != 0


def compute_sell_now(user, item, v):
    """반환: (data, meta). v: 검증된 입력 dict (volume_kg 필수)."""
    grade = v.get('grade', 'ALL')
    profile = getattr(user, 'userprofile', None)

    def pick(name, default):
        if name in v:
            return v[name]
        value = getattr(profile, name, None)
        return default if value is None else value

    loss_rate = Decimal(pick('loss_rate', 0))
    per_km = Decimal(pick('transport_cost_per_km', 0))
    commission_rate = Decimal(v.get('commission_rate', 0))
    volume = Decimal(v['volume_kg'])
    has_location = profile is not None and profile.lat is not None and profile.lng is not None
    transport_applied = has_location and per_km > 0

    markets = list(Market.objects.filter(is_collect=True).order_by('market_id'))
    base = SettlePrice.objects.filter(item=item, grade=grade, market__in=markets)
    base_date = base.aggregate(latest=Max('trade_date'))['latest']

    warnings = []
    if not transport_applied:
        warnings.append(NO_TRANSPORT_NOTICE)
    is_stale = base_date is not None and base_date < _today_kst() - timedelta(days=settings.SELL_NOW_STALE_DAYS)
    if is_stale:
        warnings.append(STALE_NOTICE)

    by_market = {}
    if base_date is not None:
        rows = base.filter(trade_date__gt=base_date - timedelta(days=ACTIVITY_WINDOW_DAYS),
                           trade_date__lte=base_date)
        for r in rows:
            if r.volume_kg > 0:
                by_market.setdefault(r.market_id, []).append(r)

    price_from = base_date - timedelta(days=PRICE_WINDOW_DAYS - 1) if base_date else None
    results = []
    for market in markets:
        rows = by_market.get(market.market_id, [])
        recent = [r for r in rows if r.trade_date >= price_from]
        total7 = sum((r.volume_kg for r in recent), Decimal(0))
        if total7 <= 0:
            continue    # 최근 7일 거래가 없는 시장은 순위에서 뺀다
        price = sum((r.avg_price * r.volume_kg for r in recent), Decimal(0)) / total7
        total14 = sum((r.volume_kg for r in rows), Decimal(0))
        days14 = len({r.trade_date for r in rows})
        # 하루 평균가 중 최저·최고 (경매 한 건 단위 값이 아니다)
        low, high = min(r.avg_price for r in rows), max(r.avg_price for r in rows)

        distance = None
        if has_location and _has_coords(market.lat, market.lng):
            distance = _distance_km(profile.lat, profile.lng, market.lat, market.lng)
        # calculate()는 예측 행(horizon·pred_price·lower80·upper80)을 받는다 → horizon 1 어댑터
        calc = calculate(SimpleNamespace(horizon=1, pred_price=price, lower80=low, upper80=high),
                         distance if transport_applied else None, volume, loss_rate, per_km, Decimal(0),
                         commission_rate)
        calc.pop('storage_won')
        results.append({
            'market_id': market.market_id, 'market_name': market.name, 'price': _price(price),
            'recent_min_price': _price(low), 'recent_max_price': _price(high),
            'recent_volume_kg': _price(total14), 'trade_days': days14,
            'distance_km': round(distance, 1) if distance is not None else None,
            **calc,
            'low_trade': days14 < settings.SELL_NOW_MIN_TRADE_DAYS or total14 < settings.SELL_NOW_MIN_VOLUME_KG,
            'volume_warning': volume > total14 / ACTIVITY_WINDOW_DAYS * Decimal(str(settings.SELL_NOW_VOLUME_WARN_MULTIPLE)),
        })
    if transport_applied and any(r['distance_km'] is None for r in results):
        warnings.append(NO_COORD_NOTICE)
    results.sort(key=lambda x: (-x['net_won'], x['market_id']))
    for rank, row in enumerate(results, 1):
        row['rank'] = rank

    meta = {'item_id': item.item_id, 'grade': grade, 'volume_kg': float(volume),
            'base_date': base_date.isoformat() if base_date else None, 'is_stale': is_stale,
            'price_unit': '원/kg', 'price_window_days': PRICE_WINDOW_DAYS,
            'forecast_available': item.is_forecast,
            'costs': {'loss_rate': float(loss_rate), 'transport_cost_per_km': int(per_km),
                      'commission_rate': float(commission_rate), 'transport_applied': transport_applied},
            'warnings': warnings}
    if not item.is_forecast:
        meta['message'] = NO_FORECAST_NOTICE
    return {'results': results}, meta


class SellNowGuestThrottle(SimpleRateThrottle):
    """비회원만 접속 주소별로 제한한다 (settings SELL_NOW_GUEST_RATE, 기본 20/min). 회원은 제한하지 않는다."""
    scope = 'sell_now_guest'

    def get_cache_key(self, request, view):
        if request.user.is_authenticated:
            return None     # None이면 DRF가 제한을 건너뛴다
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


@api_view(['POST'])
@authentication_classes([SessionAuthentication])   # 회원은 세션으로 식별(CSRF 검사), 비회원은 그대로 통과
@permission_classes([])
@throttle_classes([SellNowGuestThrottle])
def sell_now(request):
    """전국 시장 "지금 팔면" 실수령액 순위 (REQ-REC-007). 비회원은 프로필이 없어 운송비 미반영으로 계산된다."""
    serializer = SellNowSerializer(data=request.data)
    if not serializer.is_valid():
        return error(400, 'VALIDATION_ERROR', '입력값을 확인해 주세요.', serializer.errors)
    v = serializer.validated_data
    item = Item.objects.filter(pk=v['item_id']).first()
    if item is None:
        return error(404, 'NOT_FOUND', '없는 품목입니다.')
    data, meta = compute_sell_now(request.user, item, v)
    return ok(data, meta)
