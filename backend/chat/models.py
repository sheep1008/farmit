"""채팅 대화 기록 (Y13, REQ-CHT-008, REQ-NFR-002·008). 회원 탈퇴 시 CASCADE로 함께 지운다."""
from django.conf import settings
from django.db import models


class ChatSession(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='chat_sessions')
    title = models.CharField(max_length=100)          # 첫 질문 앞부분
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'chat_session'
        indexes = [models.Index(fields=['user', 'created_at'], name='idx_chat_session_user')]


class ChatMessage(models.Model):
    ROLE_CHOICES = [('user', '사용자'), ('assistant', '상담')]
    INTENT_CHOICES = [('판매', '판매'), ('병해충', '병해충'), ('날씨재해', '날씨재해'), ('재배', '재배'),
                      ('범위밖', '범위밖')]

    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    # 판단된 역할. 사용자 메시지는 비어 있다
    intent = models.CharField(max_length=10, choices=INTENT_CHOICES, null=True, blank=True)
    # 인용된 근거만 [{n, title, source_label, url, source_type}]
    sources = models.JSONField(default=list, blank=True)
    # 이 답변에 쓴 LLM 토큰 합계와 걸린 시간 (비용·응답 시간 측정, REQ-NFR-002·008)
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    latency_ms = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'chat_message'
        indexes = [models.Index(fields=['session', 'created_at'], name='idx_chat_message_session')]
