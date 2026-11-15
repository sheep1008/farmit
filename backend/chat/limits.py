"""회원별 하루 질문 수 (REQ-NFR-008). 오늘 = 한국 시간 0시부터. 채팅 API와 내 정보(chat_remaining_today)가 함께 쓴다."""
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


def remaining_today(user):
    return max(0, settings.LLM_DAILY_LIMIT - used_today(user))


def seconds_to_midnight():
    return int((today_start() + timedelta(days=1) - timezone.now()).total_seconds()) + 1
