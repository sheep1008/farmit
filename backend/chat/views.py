"""채팅 API (Y13). POST /api/chat/messages는 SSE(text/event-stream)로 답한다.

SSE 이벤트 (docs/api.md 2.7): session → status* → intent → delta* → sources → done  (실패하면 error)
요청 단계의 오류(입력·인증·CSRF·한도·없는 대화)는 스트림을 열기 전에 일반 JSON 오류로 답한다.
"""
import json
import logging
import time
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import StreamingHttpResponse
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated

from api.responses import error, ok
from chat import prompts as P
from chat import service
from chat.limits import over_limit, remaining_today, seconds_to_midnight
from chat.models import ChatMessage, ChatSession
from codes.models import Item, Market
from prices.forecast_views import compute_recommendation
from prices.views import _kst_iso, _today_kst
from rag.llm import LlmError
from rag.store import StoreUnavailable

logger = logging.getLogger(__name__)
MAX_QUESTION = 1000


class MessageSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=MAX_QUESTION, trim_whitespace=True)
    session_id = serializers.IntegerField(required=False, min_value=1, max_value=2 ** 63 - 1)
    item_id = serializers.IntegerField(required=False, min_value=1, max_value=2 ** 31 - 1)
    # 화면에서 보던 시장 (시세 상담 근거에 쓴다, 선택)
    market_id = serializers.CharField(required=False, max_length=6)


def _sse(event, data):
    return f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'


def _recommend(user, item, volume, desired):
    """채팅 판매 상담 → 판매 추천 계산 (prices, Y08). 희망 날짜가 있으면 그 주를 표시한다."""
    v = {'volume_kg': Decimal(str(volume))}
    if desired:
        v['desired_week'] = desired
    return compute_recommendation(user, item, v)


@api_view(['POST'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def messages(request):
    """질문 보내기 → SSE 답변 (REQ-CHT-001~005, REQ-NFR-008)."""
    s = MessageSerializer(data=request.data)
    if not s.is_valid():
        return error(400, 'VALIDATION_ERROR', '입력값을 확인해 주세요.', s.errors)
    v = s.validated_data
    user = request.user
    session = None
    if 'session_id' in v:
        session = ChatSession.objects.filter(pk=v['session_id'], user=user).first()
        if session is None:  # 남의 대화도 404 (존재를 숨긴다)
            return error(404, 'NOT_FOUND', '없는 대화입니다.')
    item = None
    if 'item_id' in v:
        item = Item.objects.filter(pk=v['item_id']).first()
        if item is None:
            return error(404, 'NOT_FOUND', '없는 품목입니다.')
    market = None
    if 'market_id' in v:
        market = Market.objects.filter(pk=v['market_id']).first()
        if market is None:
            return error(404, 'NOT_FOUND', '없는 시장입니다.')

    with transaction.atomic():
        # 같은 회원의 동시 요청이 한도를 함께 넘지 않게 회원 행을 잠근다
        get_user_model().objects.select_for_update().filter(pk=user.pk).first()
        if over_limit(user):
            wait = seconds_to_midnight()
            res = error(429, 'CHAT_DAILY_LIMIT',
                        f'오늘 질문 {settings.LLM_DAILY_LIMIT}회를 모두 썼습니다. 내일 다시 이용해 주세요.',
                        {'retry_after_seconds': wait})
            res['Retry-After'] = str(wait)
            return res
        history = []
        if session is None:
            session = ChatSession.objects.create(user=user, title=v['message'][:40])
        else:
            history = [{'role': m.role, 'content': m.content}
                       for m in session.messages.order_by('-created_at', '-id')[:service.HISTORY_TURNS]][::-1]
        ChatMessage.objects.create(session=session, role='user', content=v['message'])
    remaining = remaining_today(user)  # 이번 질문을 뺀 값. 관리자는 None

    def events():
        started = time.monotonic()
        yield _sse('session', {'session_id': session.id, 'remaining_today': remaining})
        try:
            for name, data in service.run(user, v['message'], item, history, _today_kst(), _recommend, market):
                if name != 'final':
                    if name == 'intent':
                        data = {**data, 'intent_label': P.INTENT_LABELS[data['intent']]}
                    yield _sse(name, data)
                    continue
                usage = data['usage']
                msg = ChatMessage.objects.create(
                    session=session, role='assistant', content=data['answer'], intent=data['intent'],
                    sources=data['sources'], input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                    latency_ms=int((time.monotonic() - started) * 1000))
                yield _sse('sources', {'sources': data['sources']})
                done = {'message_id': msg.id, 'session_id': session.id, 'intent': data['intent'],
                        'intent_label': P.INTENT_LABELS[data['intent']], 'answer': data['answer'],
                        'sources': data['sources'], 'remaining_today': remaining, 'cached': data['cached']}
                if 'guide_links' in data:
                    done['guide_links'] = data['guide_links']
                if 'recommendation' in data:
                    done['recommendation'] = data['recommendation']
                yield _sse('done', done)
        except LlmError as e:
            code = 'UPSTREAM_TIMEOUT' if e.kind == 'timeout' else 'UPSTREAM_ERROR'
            logger.warning('chat llm error kind=%s', e.kind)
            yield _sse('error', {'code': code, 'message': '답변을 만들지 못했습니다. 잠시 후 다시 시도해 주세요.'})
        except StoreUnavailable:
            yield _sse('error', {'code': 'SERVICE_UNAVAILABLE', 'message': '자료 검색을 잠시 쓸 수 없습니다.'})
        except Exception:  # 스트림이 열린 뒤라 DRF 예외 처리기가 못 잡는다. 화면이 멈추지 않게 error를 보낸다
            logger.exception('chat stream failed session=%s', session.id)
            yield _sse('error', {'code': 'INTERNAL_ERROR', 'message': '잠시 후 다시 시도해 주세요.'})

    res = StreamingHttpResponse(events(), content_type='text/event-stream; charset=utf-8')
    res['Cache-Control'] = 'no-cache'
    res['X-Accel-Buffering'] = 'no'   # Nginx가 모아 보내지 않게 (배포)
    return res


def _page_params(request):
    try:
        page = int(request.query_params.get('page', 1))
        size = int(request.query_params.get('size', 20))
    except ValueError:
        return None
    if page < 1 or not 1 <= size <= 100:
        return None
    return page, size


@api_view(['GET'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def sessions(request):
    """이전 대화 목록, 최근 순 (REQ-CHT-008)."""
    params = _page_params(request)
    if params is None:
        return error(400, 'INVALID_PARAMETER', 'page는 1 이상, size는 1~100입니다.')
    page, size = params
    qs = ChatSession.objects.filter(user=request.user).order_by('-created_at', '-id')
    total = qs.count()
    rows = [{'id': s.id, 'title': s.title, 'created_at': _kst_iso(s.created_at)}
            for s in qs[(page - 1) * size: page * size]]
    return ok(rows, {'page': page, 'size': size, 'total': total})


def message_data(m):
    return {'id': m.id, 'role': m.role, 'content': m.content, 'intent': m.intent,
            'intent_label': P.INTENT_LABELS.get(m.intent) if m.intent else None,
            'sources': m.sources, 'created_at': _kst_iso(m.created_at)}


@api_view(['GET'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def session_detail(request, session_id):
    """대화 내용 (REQ-CHT-008). 남의 대화는 404."""
    s = ChatSession.objects.filter(pk=session_id, user=request.user).first()
    if s is None:
        return error(404, 'NOT_FOUND', '없는 대화입니다.')
    msgs = [message_data(m) for m in s.messages.order_by('created_at', 'id')]
    return ok({'id': s.id, 'title': s.title, 'created_at': _kst_iso(s.created_at), 'messages': msgs})
