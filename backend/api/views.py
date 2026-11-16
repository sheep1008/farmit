import logging

from django.db import connection
from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from api.responses import error, ok
from codes.models import Item, Market
from rag import press_store
from rag.store import StoreUnavailable

logger = logging.getLogger(__name__)


@api_view(['GET'])
@authentication_classes([])
@permission_classes([])
def health(request):
    """서버와 DB가 살아 있는지 확인한다.

    운영 확인용이라 api.md의 {"data": ...} 응답 모양에서 예외로 둔다.
    DB에 연결하지 못하면 503 + 공통 오류 모양으로 응답한다.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except Exception:
        logger.exception('health check: DB 연결 실패')
        return Response(
            {'error': {'code': 'SERVICE_UNAVAILABLE', 'message': '데이터베이스에 연결할 수 없습니다.'}},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response({'status': 'ok'})


SEARCH_TYPES = ('item', 'market', 'press')
SEARCH_DEFAULT_SIZE = 20   # api.md 1.3
SEARCH_MAX_SIZE = 100
SEARCH_MAX_WINDOW = 10000


@api_view(['GET'])
@authentication_classes([])
@permission_classes([])
def search(request):
    """통합 검색 (REQ-SRC-001, REQ-SRC-002). type=item·market은 이름 일부, press는 보도자료 제목·요약 (ES, 최신순 동점 정렬)."""
    q = request.query_params.get('q', '').strip()
    kind = request.query_params.get('type', 'press')
    if not q or len(q) > 100:
        return error(400, 'VALIDATION_ERROR', '검색어(`q`)는 1~100자여야 합니다.', {'q': ['1~100자여야 합니다.']})
    if kind not in SEARCH_TYPES:
        return error(400, 'INVALID_PARAMETER', '`type`은 item, market, press 중 하나여야 합니다.',
                     {'type': ['item, market, press 중 하나']})
    try:
        size = int(request.query_params.get('size', SEARCH_DEFAULT_SIZE))
    except ValueError:
        size = 0
    try:
        page = int(request.query_params.get('page', 1))
    except ValueError:
        page = 0
    details = {}
    if not 1 <= size <= SEARCH_MAX_SIZE:
        details['size'] = [f'1~{SEARCH_MAX_SIZE} 정수']
    if page < 1 or page * size > SEARCH_MAX_WINDOW:   # ES from+size 상한(10,000)을 넘으면 오류가 나므로 미리 막는다
        details['page'] = [f'1 이상 정수, page×size는 {SEARCH_MAX_WINDOW} 이하']
    if details:
        return error(400, 'INVALID_PARAMETER', '`page`·`size` 값이 허용 범위 밖입니다.', details)
    offset = (page - 1) * size
    if kind == 'press':
        try:
            total, hits = press_store.search(q, size=size, offset=offset)
        except StoreUnavailable:
            return error(503, 'SERVICE_UNAVAILABLE', '보도자료 검색을 지금 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.')
        data = [{'title': h['title'], 'summary': h['summary'], 'published_date': h['published_date'],
                 'source': h['source'], 'url': h['url']} for h in hits]
    elif kind == 'item':
        qs = Item.objects.filter(name__icontains=q).order_by('item_id')
        total, data = qs.count(), [{'item_id': i.item_id, 'name': i.name, 'category': i.category}
                                   for i in qs[offset:offset + size]]
    else:
        qs = Market.objects.filter(Q(is_collect=True) | Q(is_reference=True), name__icontains=q).order_by('market_id')
        total, data = qs.count(), [{'market_id': m.market_id, 'name': m.name, 'sido': m.sido}
                                   for m in qs[offset:offset + size]]
    meta = {'type': kind, 'q': q, 'total': total, 'page': page, 'size': size}
    if kind == 'press':
        meta['license'] = '공공누리 제1유형(출처표시) — 정책브리핑 보도자료'
    return ok(data, meta)
