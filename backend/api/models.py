from django.db import models


# 수집 기록. Kibana 대시보드의 원천 (erd.md 2.5)
class CollectLog(models.Model):
    # source: 수집 출처 (at_settle, at_auction, asos, warning 등)
    source = models.CharField(max_length=30)
    # target_date: 수집 대상 날짜
    target_date = models.DateField()
    # started_at: 실행 시작 시각 (UTC)
    started_at = models.DateTimeField()
    # finished_at: 실행 종료 시각. 아직 실행 중이면 비어 있다
    finished_at = models.DateTimeField(null=True, blank=True)
    # status: 결과 (success, fail, partial)
    status = models.CharField(max_length=10)
    # row_count: 저장한 건수
    row_count = models.IntegerField(default=0)
    # api_calls: API 호출 수 (일일 한도 확인용)
    api_calls = models.IntegerField(default=0)
    # error_msg: 실패 사유. 성공이면 비어 있다
    error_msg = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'collect_log'
