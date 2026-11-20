from django.db.models import Q
from rest_framework.decorators import api_view, authentication_classes, permission_classes

from api.responses import error, ok

from .models import Item, Market


def _bool_param(request, name, default=None):
    """쿼리의 true/false를 읽는다. 없으면 default, 다른 값이면 ValueError (INVALID_PARAMETER로 응답)."""
    raw = request.query_params.get(name)
    if raw is None:
        return default
    if raw not in ('true', 'false'):
        raise ValueError(name)
    return raw == 'true'


def _invalid(name):
    return error(400, 'INVALID_PARAMETER', f'`{name}`은(는) true 또는 false여야 합니다.')


@api_view(['GET'])
@authentication_classes([])
@permission_classes([])
def markets(request):
    """시장 목록·검색 (REQ-PRC-001, REQ-SRC-001, REQ-NFR-010). 기본은 수집 대상 시장만, collect=false면 전체. q는 이름 일부."""
    try:
        collect = _bool_param(request, 'collect', default=True)
    except ValueError:
        return _invalid('collect')
    qs = Market.objects.order_by('market_id')
    if collect:
        # 시장 코드는 코드에 쓰지 않고 테이블의 표시로 고른다 (CLAUDE.md 전체 규칙).
        # 수집 대상 4곳 + 참고 시장(가락). 경매 수집기도 같은 기준으로 시장을 고른다 (api.md 2.2)
        qs = qs.filter(Q(is_collect=True) | Q(is_reference=True))
    q = request.query_params.get('q', '').strip()
    if q:
        qs = qs.filter(name__icontains=q)
    data = [{'market_id': m.market_id, 'name': m.name, 'sido': m.sido, 'is_reference': m.is_reference}
            for m in qs]
    return ok(data)


@api_view(['GET'])
@authentication_classes([])
@permission_classes([])
def items(request):
    """품목 목록·검색 (REQ-SRC-001). q는 이름 일부, forecast=true면 가격 예측 제공 품목만."""
    try:
        forecast = _bool_param(request, 'forecast')
    except ValueError:
        return _invalid('forecast')
    qs = Item.objects.order_by('item_id')
    q = request.query_params.get('q', '').strip()
    if q:
        qs = qs.filter(name__icontains=q)
    if forecast:
        qs = qs.filter(is_forecast=True)
    data = [{'item_id': i.item_id, 'name': i.name, 'category': i.category,
             'is_storable': i.is_storable, 'is_forecast': i.is_forecast} for i in qs]
    return ok(data)
