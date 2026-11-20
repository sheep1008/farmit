"""재배 API (Y14, docs/api.md 2.8). 이번 달 할 일·연간 일정·요약·처음 할 일·조건 탐색·용어 풀이는 로그인 없이, 증상 진단은 회원만.

일정 계산에는 LLM을 쓰지 않는다 (farming/schedule.py).
"""
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import SimpleRateThrottle

from api.responses import error, ok
from chat.limits import over_limit, remaining_today, seconds_to_midnight
from chat.models import ChatMessage, ChatSession
from codes.models import Item
from farming import diagnose as diag
from farming import doc_stats, glossary as gl
from farming import schedule as sch
from farming import weekly as wk
from farming.models import FarmSchedule
from prices.views import _bad, _get_item, _today_kst
from rag import crops as crop_util
from rag.llm import MAX_IMAGE_CHARS, LlmError, parse_image
from rag.store import StoreUnavailable

logger = logging.getLogger(__name__)
SOURCE = {'source': '농촌진흥청 농사로 농작업일정', 'license': '이용허락범위 제한 없음'}
NO_SCHEDULE = '농작업일정 정보가 없는 품목입니다.'
WEEKLY_SOURCE = {'source': '농촌진흥청 농사로 주간농사정보', 'license': '공공누리 제1유형 (출처표시)'}
NO_WEEKLY = '아직 수집된 주간농사정보가 없습니다.'
MAX_SEARCH = 6


class GlossaryThrottle(SimpleRateThrottle):
    """용어 풀이는 로그인 없이 외부 API를 부르므로 접속 주소별로 제한한다 (settings GLOSSARY_RATE, 기본 30/min)."""
    scope = 'glossary'

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


def _public(view):
    return api_view(['GET'])(authentication_classes([])(permission_classes([])(view)))


def _item_or_error(request):
    details = {}
    item = _get_item(request.query_params.get('item_id', ''), details)
    if item is None:
        return None, _bad(details)
    if item is False:
        return None, error(404, 'NOT_FOUND', '없는 품목입니다.')
    return item, None


def _item_data(item):
    return {'item_id': item.item_id, 'name': item.name}


@_public
def monthly(request):
    """이번 달 할 일 (REQ-RAG-002). month 없으면 한국 시간 오늘의 월."""
    item, err = _item_or_error(request)
    if err:
        return err
    raw = request.query_params.get('month')
    month = _today_kst().month
    if raw is not None:
        if not (raw.isascii() and raw.isdecimal() and 1 <= int(raw) <= 12):
            return _bad({'month': ['1~12 사이 숫자여야 합니다.']})
        month = int(raw)
    rows = sch.load_rows(item)
    todo = sch.month_todo(rows, month) if rows else {k: [] for k in ('start', 'continue', 'next', 'growth', 'caution')}
    data = {'item': _item_data(item), 'month': month, 'available': bool(rows), **todo}
    return ok(data, {**SOURCE, **({} if rows else {'message': NO_SCHEDULE})})


@_public
def calendar(request):
    """연간 작업 일정: 월 × 상·중·하순 칸(0~35)의 막대와 오늘 위치 (REQ-RAG-003)."""
    item, err = _item_or_error(request)
    if err:
        return err
    rows = sch.load_rows(item)
    today = _today_kst()
    meta = {**SOURCE, 'today': today.isoformat(), 'today_index': sch.today_index(today), 'slots': 36}
    if not rows:
        meta['message'] = NO_SCHEDULE
    return ok({'item': _item_data(item), 'available': bool(rows), 'bars': sch.gantt_bars(rows)}, meta)


@_public
def summary(request):
    """품목 요약: 주요 병해충 수·현장기술지원 건수·농작업일정 요약 (REQ-RAG-006)."""
    item, err = _item_or_error(request)
    if err:
        return err
    crop = crop_util.crop_name(item.name)
    counts = doc_stats.for_crop(crop) if crop else {'pests': 0, 'fieldtech': 0}
    all_rows = sch.load_rows(item)
    work = sorted((r for r in all_rows if r['kind'] == sch.KIND_WORK),
                  key=lambda r: (sch._key(r['start_month'], r['start_period']), r['task_name']))
    data = {'item': _item_data(item), 'crop_name': crop, 'pest_count': counts['pests'],
            'fieldtech_count': counts['fieldtech'],
            'schedule': {'available': bool(all_rows), 'task_count': len(work),
                         'first_task': sch.entry(work[0]) if work else None,
                         'last_task': sch.entry(work[-1]) if work else None}}
    return ok(data, {**SOURCE, **({} if all_rows else {'message': NO_SCHEDULE})})


@_public
def guide(request):
    """처음 할 일: 농작업을 시작 시기 순으로 (REQ-RAG-004, LLM 없이 농작업일정으로 만든다)."""
    item, err = _item_or_error(request)
    if err:
        return err
    rows = [r for r in sch.load_rows(item) if r['kind'] == sch.KIND_WORK]
    steps = [dict(sch.entry(r), start_month=r['start_month']) for r in
             sorted(rows, key=lambda r: (sch._key(r['start_month'], r['start_period']), r['task_name']))]
    meta = {**SOURCE, **({} if steps else {'message': NO_SCHEDULE})}
    return ok({'item': _item_data(item), 'available': bool(steps), 'steps': steps}, meta)


@_public
def search(request):
    """조건 탐색 (REQ-RAG-005): "봄에 심는 채소" → 맞는 품목 최대 6개. 월·계절·작업·분류를 규칙으로 읽는다."""
    q = request.query_params.get('q', '').strip()
    if not q or len(q) > 100:
        return _bad({'q': ['1~100자로 입력해 주세요.']})
    cond = sch.parse_condition(q)
    if not cond['task'] and not cond['months']:
        return _bad({'q': ['시기(예: 3월, 봄)나 작업(예: 심는, 수확)을 넣어 주세요.']})
    ids = FarmSchedule.objects.values_list('item_id', flat=True).distinct()
    items = list(Item.objects.filter(pk__in=ids).order_by('item_id'))
    if cond['category']:
        items = [i for i in items if i.category in sch.CATEGORY_GROUPS[cond['category']]]
    rows_by_item = sch.load_rows_by_item(i.item_id for i in items)     # 일정은 쿼리 1번으로 (품목마다 읽지 않는다)
    cards, seen = [], set()
    for item in items:
        crop = crop_util.crop_name(item.name) or item.name
        if crop in seen:                      # 풋고추·건고추처럼 같은 작물은 한 번만
            continue
        hit = sch.matches(rows_by_item.get(item.item_id, []), cond)
        if hit:
            seen.add(crop)
            cards.append({'item_id': item.item_id, 'name': item.name, 'category': item.category,
                          'schedule': [{'task': r['task_name'], 'period': r['period']} for r in hit[:3]]})
        if len(cards) == MAX_SEARCH:
            break
    return ok(cards, {**SOURCE, 'condition': {'task': cond['task'], 'months': cond['months'],
                                             'category': cond['category']}})


@_public
def weekly(request):
    """이번 주 농사 정보 (REQ-RAG-008): 주간농사정보 한 호의 분야별 요약. item_id는 선택이고 먼저 보여 줄 분야만 정한다."""
    focus = None
    if request.query_params.get('item_id'):
        item, err = _item_or_error(request)
        if err:
            return err
        focus = wk.focus_section(item.category)
    issue = wk.current_issue(_today_kst())
    if issue is None:
        return ok({'available': False, 'title': None, 'week_start': None, 'week_end': None, 'registered_on': None,
                   'url': None, 'focus': focus, 'sections': []}, {**WEEKLY_SOURCE, 'message': NO_WEEKLY})
    return ok({'available': True, 'title': issue.title, 'week_start': issue.week_start, 'week_end': issue.week_end,
               'registered_on': issue.registered_on, 'url': issue.pdf_url or None, 'focus': focus,
               'sections': issue.summary}, WEEKLY_SOURCE)


@_public
@throttle_classes([GlossaryThrottle])
def glossary(request):
    """용어 풀이 (REQ-RAG-007): 농업용어사전 → 위키백과. 못 찾으면 found=false."""
    q = request.query_params.get('q', '').strip()
    if not q or len(q) > 30:
        return _bad({'q': ['1~30자로 입력해 주세요.']})
    return ok(gl.lookup(q))


class DiagnoseSerializer(serializers.Serializer):
    item_id = serializers.IntegerField(min_value=1, max_value=2 ** 31 - 1)
    symptom = serializers.CharField(max_length=300, trim_whitespace=True, required=False, allow_blank=True)
    # 작물 사진 1장 (REQ-CHT-010). 저장하지 않고 LLM에만 넘긴다
    image = serializers.CharField(required=False, max_length=MAX_IMAGE_CHARS)

    def validate_image(self, value):
        image = parse_image(value)
        if image is None:
            raise serializers.ValidationError('jpeg·png·webp 사진만 올릴 수 있습니다.')
        return image

    def validate(self, attrs):
        if not attrs.get('symptom') and 'image' not in attrs:
            raise serializers.ValidationError({'symptom': ['증상을 적거나 사진을 올려 주세요.']})
        return attrs


def _diagnose(crop, item_name, symptom, image):
    """(결과, [LlmResult]). 사진이 있으면 증상을 읽어 합치고, 자료로 후보가 안 나오면 사진만 보고 후보를 만든다 (REQ-CHT-010)."""
    if not image:
        return diag.diagnose(crop, symptom)
    seen, message, usage = diag.read_photo(crop or item_name, symptom, image)
    if not seen:   # 작물 사진이 아니거나 판단하기 어려운 사진: 안내만
        return diag.no_reading(message), usage
    result = {'candidates': []}
    if crop:
        result, more = diag.diagnose(crop, f'{symptom} {seen}'.strip())
        usage += more
    if not result['candidates']:
        result, more = diag.photo_only(crop or item_name, symptom, seen, image)
        usage += more
    return {**result, 'photo_symptom': seen}, usage


@api_view(['POST'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def diagnose_view(request):
    """증상 진단 (REQ-RAG-001). 채팅 하루 한도에 들어가도록 채팅 기록(질문·답변)으로 남긴다. 실패하면 기록을 지워 한도를 돌려준다."""
    s = DiagnoseSerializer(data=request.data)
    if not s.is_valid():
        return _bad(s.errors)
    item = Item.objects.filter(pk=s.validated_data['item_id']).first()
    if item is None:
        return error(404, 'NOT_FOUND', '없는 품목입니다.')
    crop = crop_util.crop_name(item.name)
    image = s.validated_data.get('image')
    if not crop and not image:   # 자료가 없는 품목은 사진이 있을 때만 진단한다 (사진만 보고 추정)
        return _bad({'item_id': ['증상 진단 자료가 없는 품목입니다.']})
    symptom = s.validated_data.get('symptom', '')
    shown = ('[사진] ' if image else '') + symptom   # 기록용. 사진은 저장하지 않는다
    user = request.user
    with transaction.atomic():
        get_user_model().objects.select_for_update().filter(pk=user.pk).first()   # 동시 요청이 한도를 함께 넘지 않게
        if over_limit(user):
            wait = seconds_to_midnight()
            res = error(429, 'CHAT_DAILY_LIMIT', f'오늘 질문 {settings.LLM_DAILY_LIMIT}회를 모두 썼습니다. 내일 다시 이용해 주세요.',
                        {'retry_after_seconds': wait})
            res['Retry-After'] = str(wait)
            return res
        session = ChatSession.objects.create(user=user, title=f'[증상 진단] {item.name} {shown}'[:40])
        ChatMessage.objects.create(session=session, role='user', content=f'[증상 진단] {item.name}: {shown}')
    try:
        result, usage = _diagnose(crop, item.name, symptom, image)
    except StoreUnavailable:
        session.delete()
        return error(503, 'SERVICE_UNAVAILABLE', '자료 검색을 잠시 쓸 수 없습니다.')
    except LlmError as e:
        session.delete()
        if e.kind == 'timeout':
            return error(504, 'UPSTREAM_TIMEOUT', '진단을 만들지 못했습니다. 잠시 후 다시 시도해 주세요.')
        logger.warning('diagnose llm error kind=%s', e.kind)
        return error(502, 'UPSTREAM_ERROR', '진단을 만들지 못했습니다. 잠시 후 다시 시도해 주세요.')
    except Exception:       # 어떤 실패든 답 없는 기록이 남아 한도만 줄지 않게 한다
        session.delete()
        logger.exception('diagnose failed')
        raise
    if not usage:           # 근거가 없어 LLM을 부르지 않았다: 한도를 쓰지 않는다
        session.delete()
        return ok({'item': _item_data(item), 'symptom': symptom, **result},
                  {'remaining_today': remaining_today(user)})
    names = ', '.join(c['name'] for c in result['candidates']) or '후보 없음'
    ChatMessage.objects.create(
        session=session, role='assistant', content=f'[증상 진단 후보] {names}', intent='병해충',
        sources=result['sources'], input_tokens=sum(r.input_tokens + r.cache_read_tokens + r.cache_write_tokens for r in usage),
        output_tokens=sum(r.output_tokens for r in usage), latency_ms=sum(r.latency_ms for r in usage))
    remaining = remaining_today(user)
    return ok({'item': _item_data(item), 'symptom': symptom, **result}, {'remaining_today': remaining})
