import logging

from django.db import connection
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

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
