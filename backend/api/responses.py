"""API 공통 응답 모양 (docs/api.md 1.2절).

성공: {"data": ..., "meta": ...}   실패: {"error": {"code", "message", "details"}}
"""
from rest_framework.response import Response


def ok(data, meta=None, status=200):
    """성공 응답. meta가 없으면 키를 넣지 않는다."""
    body = {'data': data}
    if meta is not None:
        body['meta'] = meta
    return Response(body, status=status)


def error(status, code, message, details=None):
    """실패 응답. code는 프론트가 분기에 쓰는 고정 문자열 (api.md 1.5절). details는 입력값 오류일 때만."""
    body = {'code': code, 'message': message}
    if details is not None:
        body['details'] = details
    return Response({'error': body}, status=status)
