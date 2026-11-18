"""회원별 하루 질문 수 (REQ-NFR-008). 오늘 = 한국 시간 0시부터. 채팅·증상 진단 API와 내 정보(chat_remaining_today)가 함께 쓴다.

관리자(is_staff)는 테스트·시연용으로 한도 없이 쓴다. 이때 남은 횟수는 None(화면에 표시하지 않음).
"""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

KST = ZoneInfo('Asia/Seoul')


def today_start():
    """오늘 0시(한국 시간). DB에는 UTC로 저장돼 있어도 시각 비교는 같다."""
    return datetime.combine(timezone.now().astimezone(KST).date(), time.min, tzinfo=KST)


def used_today(user):
    from chat.models import ChatMessage
    return ChatMessage.objects.filter(session__user=user, role='user', created_at__gte=today_start()).count()


def unlimited(user):
    """한도 없이 쓰는 회원인지 (관리자 = Django is_staff)"""
    return bool(getattr(user, 'is_staff', False))


def over_limit(user):
    """오늘 질문을 더 할 수 없는지"""
    return not unlimited(user) and used_today(user) >= settings.LLM_DAILY_LIMIT


def remaining_today(user):
    """오늘 남은 질문 수. 관리자는 None"""
    return None if unlimited(user) else max(0, settings.LLM_DAILY_LIMIT - used_today(user))


def seconds_to_midnight():
    return int((today_start() + timedelta(days=1) - timezone.now()).total_seconds()) + 1
