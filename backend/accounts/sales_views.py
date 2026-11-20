"""판매 기록 CRUD와 평균 대비 % (REQ-SAL-001, REQ-SAL-002). 남의 기록은 403이 아니라 404 (api.md 1.5)."""
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Count, Sum
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from alerts.views import MAX_SIZE, positive_int
from api.responses import error, ok
from codes.models import Item, Market
from prices.models import SettlePrice
from prices.views import MIN_DATE, _kst_iso, _parse_date, _today_kst

from .models import SaleRecord

MAX_AMOUNT = 10 ** 13


class SaleSerializer(serializers.Serializer):
    sale_date = serializers.DateField()
    market_id = serializers.CharField(max_length=6)
    item_id = serializers.IntegerField(min_value=1, max_value=2 ** 31 - 1)
    grade = serializers.CharField(max_length=10, default='ALL')
    volume_kg = serializers.DecimalField(max_digits=12, decimal_places=1, min_value=Decimal('0.1'))
    amount_won = serializers.IntegerField(min_value=0, max_value=MAX_AMOUNT)

    def validate_sale_date(self, value):
        if value > _today_kst():
            raise serializers.ValidationError('오늘보다 늦은 날짜는 기록할 수 없습니다.')
        if value < MIN_DATE:
            raise serializers.ValidationError('2000-01-01 이후 날짜여야 합니다.')
        return value

    def validate_market_id(self, value):
        if not Market.objects.filter(pk=value).exists():
            raise serializers.ValidationError('없는 시장입니다.')
        return value

    def validate_item_id(self, value):
        if not Item.objects.filter(pk=value).exists():
            raise serializers.ValidationError('없는 품목입니다.')
        return value


def _pct(unit_price, avg_price):
    """평균 대비 % = (내 단가 / 평균 − 1) × 100, 소수 첫째 자리 사사오입. 평균이 없거나 0이면 None."""
    if avg_price is None or avg_price == 0:
        return None
    pct = (unit_price / Decimal(avg_price) - 1) * 100
    return float(pct.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))


def _averages(records):
    """기록들의 같은 날·시장·품목·등급 정산 평균가를 한 번에 가져온다. {(날짜, 시장, 품목, 등급): 평균}"""
    if not records:
        return {}
    rows = SettlePrice.objects.filter(
        trade_date__in={r.sale_date for r in records}, market_id__in={r.market_id for r in records},
        item_id__in={r.item_id for r in records}, grade__in={r.grade for r in records}
    ).values_list('trade_date', 'market_id', 'item_id', 'grade', 'avg_price')
    return {(d, m, i, g): avg for d, m, i, g, avg in rows}


def sale_data(record, averages):
    unit = Decimal(record.amount_won) / record.volume_kg
    avg = averages.get((record.sale_date, record.market_id, record.item_id, record.grade))
    return {
        'id': record.id, 'sale_date': record.sale_date.isoformat(),
        'market_id': record.market_id, 'market_name': record.market.name,
        'item_id': record.item_id, 'item_name': record.item.name, 'grade': record.grade,
        'volume_kg': float(record.volume_kg), 'amount_won': record.amount_won,
        'unit_price': float(unit.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)),
        'avg_price': float(avg) if avg is not None else None,
        'vs_avg_pct': _pct(unit, avg), 'created_at': _kst_iso(record.created_at),
    }


def _one(record):
    record = SaleRecord.objects.select_related('market', 'item').get(pk=record.pk)
    return sale_data(record, _averages([record]))


def _mine(user, sale_id):
    return SaleRecord.objects.filter(user=user, pk=sale_id).select_related('market', 'item').first()


def _bad(details):
    return error(400, 'VALIDATION_ERROR', '입력값을 확인해 주세요.', details)


@api_view(['GET', 'POST'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def sales(request):
    if request.method == 'POST':
        return create_sale(request)
    return list_sales(request)


def _in_period(request):
    """내 기록을 from·to(기본 전체)로 거른다. (queryset, None) 또는 (None, 400 응답). 목록·리포트 공통."""
    params = request.query_params
    qs = SaleRecord.objects.filter(user=request.user)
    details = {}
    start = end = None
    for name in ('from', 'to'):
        raw = params.get(name)
        if raw is None:
            continue
        value = _parse_date(raw)
        if value is None:
            details[name] = ['2000-01-01~2100-12-31 범위의 YYYY-MM-DD 형식이어야 합니다.']
        elif name == 'from':
            start = value
        else:
            end = value
    if details:
        return None, _bad(details)
    if start and end and start > end:
        return None, _bad({'from': ['`to`보다 늦을 수 없습니다.']})
    if start:
        qs = qs.filter(sale_date__gte=start)
    if end:
        qs = qs.filter(sale_date__lte=end)
    return qs, None


def list_sales(request):
    """내 판매 기록. 기간(from·to, 기본 전체)·페이지, 최신 판매일 순. meta에 기간 전체 합계."""
    params = request.query_params
    page = positive_int(params.get('page'), 1)
    size = positive_int(params.get('size'), 20, MAX_SIZE)
    if page is None or size is None:
        return error(400, 'INVALID_PARAMETER', '쿼리 값이 허용 범위를 벗어났습니다.')
    qs, bad = _in_period(request)
    if bad:
        return bad

    sums = qs.aggregate(total=Count('id'), volume=Sum('volume_kg'), amount=Sum('amount_won'))
    total = sums['total']
    meta = {'page': page, 'size': size, 'total': total,
            'total_volume_kg': float(sums['volume'] or 0), 'total_amount_won': int(sums['amount'] or 0)}
    offset = (page - 1) * size
    if offset >= total:
        return ok([], meta)
    rows = list(qs.select_related('market', 'item').order_by('-sale_date', '-id')[offset:offset + size])
    averages = _averages(rows)
    return ok([sale_data(r, averages) for r in rows], meta)


def _add(groups, key, volume, pct):
    """묶음별 [건수, 물량 합, Σ(물량 × 평균 대비 %)]를 쌓는다."""
    g = groups.setdefault(key, [0, Decimal(0), Decimal(0)])
    g[0] += 1
    g[1] += volume
    g[2] += volume * Decimal(str(pct))


def _group(g):
    count, volume, weighted = g          # 물량은 0.1 이상만 저장되므로 0으로 나눌 일이 없다
    pct = (weighted / volume).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
    return {'count': count, 'volume_kg': float(volume), 'vs_avg_pct': float(pct)}


@api_view(['GET'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def sales_summary(request):
    """내 판매 성적 리포트 (REQ-SAL-005, api.md 2.6). 기간 안 기록 전부를 월별·시장별로 묶어
    목록에 보이는 vs_avg_pct의 물량 가중 평균을 낸다. 정산 평균이 없는 기록은 빼고 pending으로 센다."""
    qs, bad = _in_period(request)
    if bad:
        return bad
    rows = list(qs.select_related('market'))
    averages = _averages(rows)
    overall, months, markets, names = {}, {}, {}, {}
    for r in rows:
        avg = averages.get((r.sale_date, r.market_id, r.item_id, r.grade))
        pct = _pct(Decimal(r.amount_won) / r.volume_kg, avg)
        if pct is None:
            continue
        _add(overall, 'all', r.volume_kg, pct)
        _add(months, r.sale_date.strftime('%Y-%m'), r.volume_kg, pct)   # 판매일은 한국 날짜라 변환 없이 그 달
        _add(markets, r.market_id, r.volume_kg, pct)
        names[r.market_id] = r.market.name
    compared = overall['all'][0] if overall else 0
    total = _group(overall['all']) if overall else None
    return ok({
        'total': len(rows), 'compared': compared, 'pending': len(rows) - compared,
        'overall': {'volume_kg': total['volume_kg'], 'vs_avg_pct': total['vs_avg_pct']} if total else None,
        'by_month': [{'month': m, **_group(g)} for m, g in sorted(months.items())],
        'by_market': [{'market_id': m, 'market_name': names[m], **_group(g)}
                      for m, g in sorted(markets.items(), key=lambda kv: -kv[1][1])],
    })


def create_sale(request):
    serializer = SaleSerializer(data=request.data)
    if not serializer.is_valid():
        return _bad(serializer.errors)
    v = serializer.validated_data
    record = SaleRecord.objects.create(
        user=request.user, sale_date=v['sale_date'], market_id=v['market_id'], item_id=v['item_id'],
        grade=v['grade'], volume_kg=v['volume_kg'], amount_won=v['amount_won'])
    return ok(_one(record), status=201)


@api_view(['PATCH', 'DELETE'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def sale_detail(request, sale_id):
    record = _mine(request.user, sale_id)
    if record is None:
        return error(404, 'NOT_FOUND', '없는 판매 기록입니다.')
    if request.method == 'DELETE':
        record.delete()
        return Response(status=204)
    serializer = SaleSerializer(data=request.data, partial=True)
    if not serializer.is_valid():
        return _bad(serializer.errors)
    for key, value in serializer.validated_data.items():
        setattr(record, key, value)          # market_id·item_id도 그대로 FK 컬럼에 들어간다
    record.save()
    return ok(_one(record))
