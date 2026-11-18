import re
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from django.db.models import DecimalField, F, Max, Min, Avg, Sum
from django.db.models.functions import TruncMonth, TruncWeek
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes

from api.models import CollectLog
from api.responses import error, ok
from codes.models import Item, Market

from .models import RealtimePrice, SettlePrice

KST = ZoneInfo('Asia/Seoul')
# 경매 수집기(collectors/auction)가 쓰는 collect_log.source 값
AUCTION_SOURCE = 'at_auction'
# 한국 시간 이 시각 전까지는 경매 중(live)으로 본다. 경매는 11시쯤 끝나고 API 반영이 약 20분 늦어
# 수집기도 12시까지 돈다 (collectors/auction/transform.py is_collect_time)
AUCTION_END_HOUR = 12
# 정산 수집기(collectors/settle)가 쓰는 collect_log.source 값
SETTLE_SOURCE = 'at_settle'
# 기간 제한 (api.md 2.3): 일 단위는 최대 1년, 주·월 단위는 최대 5년. 윤일에 걸리지 않게 일수가 아니라 연으로 센다
MAX_YEARS = {'day': 1, 'week': 5, 'month': 5}
UNITS = tuple(MAX_YEARS)
# 받아들이는 날짜 범위. 너무 먼 날짜는 전년 계산에서 오류가 나므로 입력에서 막는다
MIN_DATE, MAX_DATE = date(2000, 1, 1), date(2100, 12, 31)
DATE_FORMAT = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}')


def _price(value):
    """Decimal → float (api.md 1.1: 가격은 숫자, 소수 첫째 자리까지). 값이 없으면 None."""
    if value is None:
        return None
    # 사사오입(.x5는 올림). 파이썬 round()는 .x5를 짝수 쪽으로 내려 0.1원 어긋날 수 있다
    return float(Decimal(str(value)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))


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


# ---------------------------------------------------------------------------
# 정산 확정 가격 (settle_price): 기간별 추이, 시장 간 비교
# ---------------------------------------------------------------------------
def _today_kst():
    return timezone.now().astimezone(KST).date()


def _bad(details):
    return error(400, 'VALIDATION_ERROR', '입력값을 확인해 주세요.', details)


def _parse_date(raw):
    """YYYY-MM-DD만 받는다 (api.md 1.1). 형식이 틀리거나 없는 날짜, 허용 범위 밖이면 None."""
    if not DATE_FORMAT.fullmatch(raw):
        return None
    try:
        day = date.fromisoformat(raw)
    except ValueError:
        return None
    return day if MIN_DATE <= day <= MAX_DATE else None


def _get_item(raw, details):
    """item_id를 읽어 품목을 돌려준다. 형식이 틀리면 details에 적고 None, 없는 품목이면 False."""
    if not raw:
        details['item_id'] = ['필수 값입니다.']
        return None
    if not (raw.isascii() and raw.isdecimal()):
        details['item_id'] = ['숫자여야 합니다.']
        return None
    return Item.objects.filter(pk=int(raw)).first() or False


def _add_years(day, years):
    try:
        return day.replace(year=day.year + years)
    except ValueError:                       # 2월 29일 → 없는 해는 28일로
        return day.replace(year=day.year + years, day=28)


def _aggregate(qs, unit):
    """정산 행을 일·주·월 단위로 묶는다. 평균은 물량가중(Σ가격×물량 / Σ물량)이다.

    돌려주는 값: [(period 날짜, avg, min, max, volume), ...] 날짜순. 주는 그 주 월요일, 월은 그 달 1일.
    """
    if unit == 'day':
        rows = qs.order_by('trade_date').values_list(
            'trade_date', 'avg_price', 'min_price', 'max_price', 'volume_kg')
        return list(rows)
    trunc = TruncWeek('trade_date') if unit == 'week' else TruncMonth('trade_date')
    rows = (qs.annotate(period=trunc).values('period')
            .annotate(weighted=Sum(F('avg_price') * F('volume_kg'), output_field=DecimalField()),
                      volume=Sum('volume_kg'), lo=Min('min_price'), hi=Max('max_price'),
                      simple=Avg('avg_price'))
            .order_by('period'))
    # 물량이 0이면 가중 평균을 못 구하므로 단순 평균으로 대신한다
    return [(r['period'], (r['weighted'] / r['volume']) if r['volume'] else r['simple'],
             r['lo'], r['hi'], r['volume']) for r in rows]


def _period_key(day, unit):
    return day.strftime('%Y-%m') if unit == 'month' else day.isoformat()


def _last_year_shift(day, unit):
    """작년 같은 기간 → 올해 기준 날짜. 일은 1년, 주는 52주(요일이 같게), 월은 12개월."""
    return day + timedelta(weeks=52) if unit == 'week' else _add_years(day, 1)


def _last_year_range(start, end, unit):
    if unit == 'week':
        return start - timedelta(weeks=52), end - timedelta(weeks=52)
    return _add_years(start, -1), _add_years(end, -1)


@api_view(['GET'])
@authentication_classes([])
@permission_classes([])
def daily(request):
    """기간별 가격 추이, 정산 확정 (REQ-PRC-001, REQ-PRC-005). 일·주·월 단위, 등급 선택, 전년 비교 선택."""
    params = request.query_params
    details = {}
    item = _get_item(params.get('item_id', ''), details)
    market_id = params.get('market_id', '')
    if not market_id:
        details['market_id'] = ['필수 값입니다.']

    today = _today_kst()
    start = end = None
    for name, default in (('from', today - timedelta(days=90)), ('to', today - timedelta(days=1))):
        raw = params.get(name)
        value = default if raw is None else _parse_date(raw)
        if value is None:
            details[name] = ['2000-01-01~2100-12-31 범위의 YYYY-MM-DD 형식이어야 합니다.']
        elif name == 'from':
            start = value
        else:
            end = value
    if details:
        return _bad(details)

    unit = params.get('unit', 'day')
    if unit not in UNITS:
        return error(400, 'INVALID_PARAMETER', '`unit`은(는) day, week, month 중 하나여야 합니다.')
    compare = params.get('compare_last_year', 'false')
    if compare not in ('true', 'false'):
        return error(400, 'INVALID_PARAMETER', '`compare_last_year`은(는) true 또는 false여야 합니다.')
    if start > end:
        return _bad({'from': ['`to`보다 늦을 수 없습니다.']})
    if end > _add_years(start, MAX_YEARS[unit]):
        return _bad({'from': [f'{unit} 단위는 최대 {MAX_YEARS[unit]}년까지 조회할 수 있습니다.']})

    if item is False:
        return error(404, 'NOT_FOUND', '없는 품목입니다.')
    market = Market.objects.filter(pk=market_id).first()
    if market is None:
        return error(404, 'NOT_FOUND', '없는 시장입니다.')

    grade = params.get('grade', 'ALL')
    base = SettlePrice.objects.filter(item=item, market=market, grade=grade)
    rows = _aggregate(base.filter(trade_date__range=(start, end)), unit)

    last_year = {}
    if compare == 'true':
        ly_start, ly_end = _last_year_range(start, end, unit)
        for period, avg, *_ in _aggregate(base.filter(trade_date__range=(ly_start, ly_end)), unit):
            last_year[_period_key(_last_year_shift(period, unit), unit)] = _price(avg)

    data = []
    for period, avg, lo, hi, volume in rows:
        row = {'period': _period_key(period, unit), 'avg_price': _price(avg),
               'min_price': _price(lo), 'max_price': _price(hi), 'volume_kg': _price(volume)}
        if compare == 'true':
            row['last_year_avg_price'] = last_year.get(row['period'])
        data.append(row)

    last_log = (CollectLog.objects.filter(source=SETTLE_SOURCE, finished_at__isnull=False)
                .exclude(status='fail').order_by('-finished_at').first())
    return ok(data, {'item_id': item.item_id, 'market_id': market.market_id, 'unit': unit, 'grade': grade,
                     'price_unit': '원/kg',
                     'last_updated': _kst_iso(last_log.finished_at) if last_log else None})


def market_prices(item, grade, day=None):
    """같은 날 수집 대상 시장의 정산 가격 (compare와 판매 추천의 시장 비교가 함께 쓴다).

    day가 없으면 그 품목·등급의 가장 최근 정산일. 돌려주는 값: (시장별 행 목록, 쓴 날짜 또는 None).
    """
    # 수집 대상 시장 전체 (전국 32곳, 가락 포함. api.md 2.3)
    markets = list(Market.objects.filter(is_collect=True).order_by('market_id'))
    if day is None:
        # 가장 최근 정산일 = 이 품목·등급의 가장 늦은 거래정산일자
        day = (SettlePrice.objects.filter(item=item, grade=grade, market__in=markets)
               .aggregate(latest=Max('trade_date'))['latest'])
    rows = {}
    if day is not None:
        rows = {r.market_id: r for r in SettlePrice.objects.filter(
            item=item, grade=grade, trade_date=day, market__in=markets)}

    data = []
    for market in markets:
        row = rows.get(market.market_id)
        data.append({'market_id': market.market_id, 'market_name': market.name,
                     'avg_price': _price(row.avg_price) if row else None,
                     'volume_kg': _price(row.volume_kg) if row else 0.0})
    return data, day


@api_view(['GET'])
@authentication_classes([])
@permission_classes([])
def compare(request):
    """같은 날 수집 대상 시장의 가격 비교 (REQ-PRC-003). 거래가 없는 시장도 avg_price null로 넣는다."""
    params = request.query_params
    details = {}
    item = _get_item(params.get('item_id', ''), details)
    day = None
    if params.get('date') is not None:
        day = _parse_date(params['date'])
        if day is None:
            details['date'] = ['2000-01-01~2100-12-31 범위의 YYYY-MM-DD 형식이어야 합니다.']
    if details:
        return _bad(details)
    if item is False:
        return error(404, 'NOT_FOUND', '없는 품목입니다.')

    grade = params.get('grade', 'ALL')
    data, day = market_prices(item, grade, day)
    return ok(data, {'item_id': item.item_id, 'date': day.isoformat() if day else None,
                     'grade': grade, 'price_unit': '원/kg'})
