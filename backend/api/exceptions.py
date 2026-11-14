"""DRF 예외를 docs/api.md 1.2절의 실패 응답 모양으로 바꾼다 (config/settings.py의 EXCEPTION_HANDLER)."""
from rest_framework import exceptions
from rest_framework.views import exception_handler

from .responses import error


def custom_exception_handler(exc, context):
    # 로그인이 필요한 API를 비로그인으로 부르면 401 (DRF 기본은 403)
    if isinstance(exc, exceptions.NotAuthenticated):
        return error(401, 'NOT_AUTHENTICATED', '로그인이 필요합니다.')

    # CSRF 실패는 PermissionDenied로 오고 메시지가 'CSRF Failed'로 시작한다.
    # 다른 이유의 403과 섞이지 않도록 메시지까지 확인한다.
    if isinstance(exc, exceptions.PermissionDenied) and str(exc.detail).startswith('CSRF Failed'):
        return error(403, 'CSRF_FAILED', 'CSRF 검증에 실패했습니다. 새로고침 후 다시 시도해 주세요.')

    # 그 밖의 오류는 DRF 기본 처리에 맡긴다
    return exception_handler(exc, context)
