from django.db import models

from codes.models import Item


class FarmSchedule(models.Model):
    """농사로 농작업일정 한 줄 (erd.md farm_schedule). 품목마다 대표 일정 하나의 시기정보를 저장한다.

    stage: 농사로 시기정보 구분 (예: 생육과정(주요농작업)). 기간은 월 + 순(상·중·하). 끝 월이 시작 월보다 작으면 해를 넘는다.
    """
    PERIODS = [('상', '상순'), ('중', '중순'), ('하', '하순')]

    item = models.ForeignKey(Item, on_delete=models.CASCADE, db_column='item_id', related_name='farm_schedules')
    task_name = models.CharField(max_length=100)
    stage = models.CharField(max_length=50)
    start_month = models.PositiveSmallIntegerField()
    start_period = models.CharField(max_length=1, choices=PERIODS)
    end_month = models.PositiveSmallIntegerField()
    end_period = models.CharField(max_length=1, choices=PERIODS)

    class Meta:
        db_table = 'farm_schedule'
        indexes = [models.Index(fields=['item', 'start_month'], name='ix_farm_schedule_item')]


class WeeklyFarmInfo(models.Model):
    """농사로 주간농사정보 한 호 (erd.md weekly_farm_info, REQ-RAG-008).

    summary: PDF '요약' 쪽을 분야별로 자른 [{"section": "과수", "items": [...]}]. 못 읽으면 [].
    작성자 실명과 본문은 저장하지 않는다 (REQ-NFR-007).
    """
    content_no = models.PositiveIntegerField()              # 농사로 글 번호 (cntntsNo)
    title = models.CharField(max_length=200)
    week_start = models.DateField(null=True, blank=True)    # 제목의 기간 (한국 날짜). 못 읽으면 NULL
    week_end = models.DateField(null=True, blank=True)
    registered_on = models.DateField()                      # 농사로 등록일
    pdf_url = models.CharField(max_length=500)              # PDF 원문 주소. 첨부가 없으면 ''
    summary = models.JSONField(default=list)
    collected_at = models.DateTimeField()                   # UTC

    class Meta:
        db_table = 'weekly_farm_info'
        constraints = [models.UniqueConstraint(fields=['content_no'], name='uk_weekly_farm_info')]
