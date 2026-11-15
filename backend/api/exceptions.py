"""예외를 docs/api.md 1.2절의 실패 응답 모양으로 바꾼다 (config/settings.py의 EXCEPTION_HANDLER).

DRF가 아는 예외(405·415·깨진 JSON 등)도, 모르는 예외(500)도 같은 {"error": {...}} 모양으로 보낸다.
"""
import logging
import math

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404, JsonResponse
from rest_framework import exceptions
from rest_framework.views import exception_handler, set_rollback

from .responses import error

logger = logging.getLogger(__name__)

# 상태 코드 → (오류 코드, 기본 메시지). docs/api.md 1.5절
_BY_STATUS = {
    400: ('VALIDATION_ERROR', '입력값을 확인해 주세요.'),
    401: ('NOT_AUTHENTICATED', '로그인이 필요합니다.'),
    403: ('FORBIDDEN', '권한이 없습니다.'),
    404: ('NOT_FOUND', '대상을 찾을 수 없습니다.'),
    405: ('METHOD_NOT_ALLOWED', '허용되지 않는 요청 방식입니다.'),
    415: ('UNSUPPORTED_MEDIA_TYPE', '지원하지 않는 요청 형식입니다. JSON으로 보내 주세요.'),
    429: ('RATE_LIMITED', '요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.'),
    502: ('UPSTREAM_ERROR', '외부 서비스에 문제가 있습니다. 잠시 후 다시 시도해 주세요.'),
    503: ('SERVICE_UNAVAILABLE', '지금은 이용할 수 없습니다. 잠시 후 다시 시도해 주세요.'),
    504: ('UPSTREAM_TIMEOUT', '외부 서비스가 제때 응답하지 않았습니다. 다시 시도해 주세요.'),
}


def custom_exception_handler(exc, context):
    # 로그인이 필요한 API를 비로그인으로 부르면 401 (DRF 기본은 403)
    if isinstance(exc, exceptions.NotAuthenticated):
        return error(401, 'NOT_AUTHENTICATED', '로그인이 필요합니다.')

    # CSRF 실패는 PermissionDenied로 오고 메시지가 'CSRF Failed'로 시작한다.
    # 다른 이유의 403과 섞이지 않도록 메시지까지 확인한다.
    if isinstance(exc, exceptions.PermissionDenied) and str(exc.detail).startswith('CSRF Failed'):
        return error(403, 'CSRF_FAILED', 'CSRF 검증에 실패했습니다. 새로고침 후 다시 시도해 주세요.')

    # Django 예외는 DRF 예외로 바꿔서 같은 길로 보낸다
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = exceptions.PermissionDenied()

    response = exception_handler(exc, context)
    if response is None:
        # DRF가 모르는 예외 = 코드 버그. 내용은 로그에만 남기고 밖에는 알리지 않는다.
        request = context.get('request')
        where = f'{request.method} {request.path}' if request is not None else '(요청 정보 없음)'
        logger.error('처리되지 않은 예외: %s', where, exc_info=exc)
        set_rollback()  # 나중에 ATOMIC_REQUESTS를 켜도 반쯤 쓴 데이터가 커밋되지 않게
        return error(500, 'INTERNAL_ERROR', '서버에 문제가 생겼습니다. 잠시 후 다시 시도해 주세요.')

    status = response.status_code
    if status in _BY_STATUS:
        code, message = _BY_STATUS[status]
    elif status < 500:
        # 표에 없는 4xx(예: 406)는 일반 오류 코드로 보낸다. INTERNAL_ERROR는 500 전용이다.
        code, message = 'VALIDATION_ERROR', '요청을 처리할 수 없습니다.'
    else:
        code, message = 'INTERNAL_ERROR', '요청을 처리하지 못했습니다.'

    # 필드별 오류(raise ValidationError({...}))는 details로 그대로 넘긴다 (프론트가 입력칸 아래에 표시)
    details = None
    if isinstance(exc, exceptions.ValidationError):
        details = response.data if isinstance(response.data, dict) else {'non_field_errors': response.data}

    if isinstance(exc, exceptions.Throttled) and exc.wait is not None:
        wait = math.ceil(exc.wait)
        result = error(status, code, message, {'retry_after_seconds': wait})
        result['Retry-After'] = str(wait)
        return result
    return error(status, code, message, details)


def not_found_handler(request, exception=None):
    """주소가 어디에도 맞지 않을 때 (DRF 뷰에 닿기 전). Django 기본 HTML 404 대신 JSON으로 답한다."""
    return JsonResponse({'error': {'code': 'NOT_FOUND', 'message': '대상을 찾을 수 없습니다.'}}, status=404)


def server_error_handler(request):
    """DRF 밖(미들웨어 등)에서 난 500도 JSON으로 답한다."""
    return JsonResponse({'error': {'code': 'INTERNAL_ERROR',
                                   'message': '서버에 문제가 생겼습니다. 잠시 후 다시 시도해 주세요.'}}, status=500)
