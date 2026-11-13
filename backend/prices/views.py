from datetime import datetime
from zoneinfo import ZoneInfo

from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes

from api.models import CollectLog
from api.responses import error, ok
from codes.models import Item, Market

from .models import RealtimePrice

KST = ZoneInfo('Asia/Seoul')
# 경매 수집기(collectors/auction)가 쓰는 collect_log.source 값
AUCTION_SOURCE = 'at_auction'
# 한국 시간 이 시각 전까지는 경매 중(live)으로 본다. 경매는 11시쯤 끝나고 API 반영이 약 20분 늦어
# 수집기도 12시까지 돈다 (collectors/auction/transform.py is_collect_time)
AUCTION_END_HOUR = 12


def _price(value):
    """Decimal → float (api.md 1.1: 가격은 숫자). 값이 없으면 None."""
    return float(value) if value is not None else None


def _kst_iso(value):
    """UTC로 저장된 일시를 한국 시간 ISO 8601 문자열로 (api.md 1.1). 값이 없으면 None."""
    return timezone.localtime(value, KST).isoformat() if value is not None else None


@api_view(['GET'])
@authentication_classes([])
@permission_classes([])
def realtime(request):
    """당일 경매 가격 (REQ-PRC-004). Flink가 채우는 realtime_price에서 오늘(정산일자) 행을 읽는다.

    market_id가 없으면 수집 대상 시장을 모두 돌려주고, 거래가 없는 시장도 no_trade 행으로 넣는다.
    """
    item_id = request.query_params.get('item_id')
    if not item_id:
        return error(400, 'VALIDATION_ERROR', '입력값을 확인해 주세요.', {'item_id': ['필수 값입니다.']})
    if not item_id.isdigit():
        return error(400, 'VALIDATION_ERROR', '입력값을 확인해 주세요.', {'item_id': ['숫자여야 합니다.']})
    item = Item.objects.filter(pk=int(item_id)).first()
    if item is None:
        return error(404, 'NOT_FOUND', '없는 품목입니다.')

    market_id = request.query_params.get('market_id')
    if market_id:
        markets = list(Market.objects.filter(pk=market_id))
        if not markets:
            return error(404, 'NOT_FOUND', '없는 시장입니다.')
    else:
        # 시장 코드는 코드에 쓰지 않고 테이블의 수집 대상 표시로 고른다 (CLAUDE.md 2절)
        markets = list(Market.objects.filter(is_collect=True).order_by('market_id'))

    now_kst = timezone.now().astimezone(KST)
    today = now_kst.date()

    # 오늘 정산일자로 한 번이라도 수집이 끝났는지. 없으면 수집기가 아직 돌지 않은 것 (거래 없음과 구분)
    last_log = (CollectLog.objects
                .filter(source=AUCTION_SOURCE, target_date=today, finished_at__isnull=False)
                .exclude(status='fail')
                .order_by('-finished_at')
                .first())
    if last_log is None:
        return error(503, 'DATA_NOT_READY', '오늘 경매 가격을 아직 수집하지 않았습니다.')

    rows = {r.market_id: r for r in RealtimePrice.objects.filter(
        item=item, trade_date=today, market__in=markets)}
    is_live = now_kst.hour < AUCTION_END_HOUR

    data = []
    for market in markets:
        row = rows.get(market.market_id)
        if row is None:
            data.append({
                'market_id': market.market_id, 'market_name': market.name, 'trade_date': today.isoformat(),
                'avg_price': None, 'min_price': None, 'max_price': None,
                'volume_kg': 0.0, 'trade_count': 0, 'last_auction_at': None,
                'status': 'no_trade',
            })
            continue
        data.append({
            'market_id': market.market_id, 'market_name': market.name, 'trade_date': row.trade_date.isoformat(),
            'avg_price': _price(row.avg_price), 'min_price': _price(row.min_price),
            'max_price': _price(row.max_price), 'volume_kg': _price(row.volume_kg),
            'trade_count': row.trade_count, 'last_auction_at': _kst_iso(row.last_auction_at),
            'status': 'live' if is_live else 'closed',
        })

    return ok(data, {'collected_at': _kst_iso(last_log.finished_at), 'price_unit': '원/kg'})
