from django.conf import settings
from django.db import models

from codes.models import Item


# 특수 상황 1건 = 1행. 기상특보·수입량 급증·예찰 증가·정부 발표를 한 테이블에 모은다 (erd.md 3, REQ-ALT-001, 004~006)
class SpecialEvent(models.Model):
    class EventType(models.TextChoices):
        WARNING = 'WARNING', '기상특보'
        IMPORT_SURGE = 'IMPORT_SURGE', '수입량 급증'
        PEST_INCREASE = 'PEST_INCREASE', '예찰 증가'
        GOV_NOTICE = 'GOV_NOTICE', '정부 발표'

    # event_type: 특수 상황 종류
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    # item: 관련 품목 FK. 기상특보처럼 품목과 상관없는 상황은 비어 있다. 품목을 지워도 상황 기록은 남긴다
    item = models.ForeignKey(Item, on_delete=models.SET_NULL, null=True, blank=True)
    # sido: 시도
    sido = models.CharField(max_length=20)
    # sigungu: 시군구. 비어 있으면 시도 전체 (예: 서울동남권 특보)
    sigungu = models.CharField(max_length=20, null=True, blank=True)
    # occurred_at: 발생 시각 (UTC). 기상특보는 발표 시각
    occurred_at = models.DateTimeField()
    # title: 목록에 보일 제목 (예: 가평군 한파주의보 발표)
    title = models.CharField(max_length=100)
    # detail: 상황별 상세 (JSON). 기상특보는 종류·단계·발효 시각 등
    detail = models.JSONField(default=dict)
    # source_url: 출처 링크 (REQ-NFR-007)
    source_url = models.CharField(max_length=300)
    # source_ref: 원본을 구분하는 값. 기상특보는 "source_key:status". 같은 상황을 두 번 만들지 않는다
    source_ref = models.CharField(max_length=100)

    class Meta:
        db_table = 'special_event'
        constraints = [
            models.UniqueConstraint(fields=['event_type', 'source_ref'], name='uq_special_event_source'),
        ]


# 회원별 알림. 특수 상황 1건이 여러 회원에게 간다 (erd.md 3, REQ-ALT-003)
class Alert(models.Model):
    # user: 회원 FK. 탈퇴하면 알림도 함께 삭제된다
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    # special_event: 특수 상황 FK. 상황을 지우면 알림도 함께 삭제된다
    special_event = models.ForeignKey(SpecialEvent, on_delete=models.CASCADE)
    # created_at: 알림을 만든 시각 (UTC)
    created_at = models.DateTimeField(auto_now_add=True)
    # read_at: 읽은 시각. 비어 있으면 안 읽음
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'alert'
        constraints = [
            # 같은 상황으로 같은 회원에게 두 번 알리지 않는다 (컨슈머가 같은 메시지를 다시 읽어도)
            models.UniqueConstraint(fields=['user', 'special_event'], name='uq_alert_user_event'),
        ]
