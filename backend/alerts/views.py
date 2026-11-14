from django.utils import timezone
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated

from api.responses import error, ok

from .models import Alert
from .serializers import alert_detail, alert_item

MAX_SIZE = 100


def positive_int(value, default, maximum=None):
    """쿼리 값을 양의 정수로. 잘못되면 None"""
    if value is None:
        return default
    # isdigit()는 '²' 같은 유니코드 숫자도 통과시켜 int()에서 500이 난다 → 아스키 숫자만
    if not (value.isascii() and value.isdecimal()) or len(value) > 9:
        return None
    n = int(value)
    return n if n >= 1 and (not maximum or n <= maximum) else None


def get_my_alert(user, alert_id):
    # 남의 알림은 조회 대상에서 빼서 404로 만든다
    return Alert.objects.filter(user=user, id=alert_id).select_related('special_event').first()


@api_view(['GET'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def alert_list(request):
    """내 알림 목록. unread=true면 안 읽은 것만. 최신순, 페이지 나눔."""
    page = positive_int(request.query_params.get('page'), 1)
    size = positive_int(request.query_params.get('size'), 20, MAX_SIZE)
    unread = request.query_params.get('unread', 'false').lower()
    if page is None or size is None or unread not in ('true', 'false'):
        return error(400, 'INVALID_PARAMETER', '쿼리 값이 허용 범위를 벗어났습니다.')

    qs = Alert.objects.filter(user=request.user).select_related('special_event')
    if unread == 'true':
        qs = qs.filter(read_at__isnull=True)
    total = qs.count()
    start = (page - 1) * size
    if start >= total:   # 범위를 넘은 페이지는 DB에 물어보지 않고 빈 배열
        return ok([], {'page': page, 'size': size, 'total': total})
    rows = qs.order_by('-special_event__occurred_at', '-id')[start:start + size]
    return ok([alert_item(a) for a in rows], {'page': page, 'size': size, 'total': total})


@api_view(['GET'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def alert_detail_view(request, alert_id):
    """알림 상세 + 대응 체크리스트 + 출처. 열기만 해서는 읽음 처리하지 않는다."""
    alert = get_my_alert(request.user, alert_id)
    if alert is None:
        return error(404, 'NOT_FOUND', '없는 알림입니다.')
    return ok(alert_detail(alert))


@api_view(['PATCH'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def alert_read(request, alert_id):
    """읽음 처리. 이미 읽은 알림은 처음 읽은 시각을 유지한다."""
    alert = get_my_alert(request.user, alert_id)
    if alert is None:
        return error(404, 'NOT_FOUND', '없는 알림입니다.')
    # 조건부 UPDATE: 동시에 두 번 눌려도 처음 읽은 시각이 유지된다
    Alert.objects.filter(pk=alert.pk, read_at__isnull=True).update(read_at=timezone.now())
    alert.refresh_from_db()
    return ok(alert_item(alert))
