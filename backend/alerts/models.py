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


# 관세청 월별 수입량. 수입량 급증 알림·과거 사례의 재료 (erd.md 3, REQ-COL-005, REQ-ALT-004)
# collectors/imports/customs.py가 UPSERT한다. 거래가 없는 달도 0으로 저장한다 (같은 달 평균을 낼 때 빠지지 않게)
class ImportMonthly(models.Model):
    # item: 품목 FK. item.hs_code가 있는 품목만 수집한다
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
    # hs_code: 조회한 HS 코드 (item.hs_code 그대로). 6자리면 그 아래 10자리 코드를 모두 더한 값이다
    hs_code = models.CharField(max_length=10)
    # ym: 수입 연월. 그달 1일로 저장한다 (예: 2025-03-01)
    ym = models.DateField()
    # import_kg: 수입 중량 kg (관세청 impWgt를 국가별로 더한 값)
    import_kg = models.BigIntegerField()
    # import_usd: 수입 금액 USD (impDlr 합)
    import_usd = models.BigIntegerField()

    class Meta:
        db_table = 'import_monthly'
        constraints = [
            models.UniqueConstraint(fields=['hs_code', 'ym'], name='uk_import_monthly'),
        ]


# NCPMS 병해충 예찰 결과 (시군·병해충 하나 = 1행). 예찰 증가 알림·과거 사례의 재료 (erd.md 3, REQ-COL-005, REQ-ALT-005)
# collectors/pests/ncpms.py가 UPSERT한다. 품목과는 item.ncpms_crop_code로 잇는다 (한 작물 코드를 여러 품목이 쓸 수 있다)
class PestSurvey(models.Model):
    # ncpms_crop_code: NCPMS 작물 코드 (kncrCode, 예: FT010601 사과)
    ncpms_crop_code = models.CharField(max_length=10)
    # insect_key: NCPMS 조사 회차 키 (연도+조사 종류+작물+회차). 같은 회차를 두 번 받지 않는 기준
    insect_key = models.CharField(max_length=30)
    # survey_type: 조사 종류 (examinSpchcknNm. 기본조사·노지고추·시설고추·여름배추 등). 종류마다 회차가 따로 매겨진다
    survey_type = models.CharField(max_length=20)
    # survey_year·survey_round: 조사 연도·회차. 회차 번호의 날짜는 해마다 다를 수 있다 (사과는 2022년부터 1회차가 4/1 → 5/16)
    survey_year = models.SmallIntegerField()
    survey_round = models.SmallIntegerField()
    # survey_date: 조사 기준일 (inputStdrDatetm). 해마다 같은 시기끼리 비교할 때 회차 번호 대신 이 날짜를 쓴다
    survey_date = models.DateField()
    # sido·sigungu·sigungu_code: 조사 지역 (sigungu_code는 NCPMS 4자리, 앞 2자리가 시도)
    sido = models.CharField(max_length=20)
    sigungu = models.CharField(max_length=20)
    sigungu_code = models.CharField(max_length=10)
    # pest_code·pest_name: 조사 항목 코드(inqireCnClCode)와 이름(dbyhsNm, 예: '탄저병(피해과율)'). 이름 괄호 안이 값의 단위다
    pest_code = models.CharField(max_length=10)
    pest_name = models.CharField(max_length=60)
    # value: 조사 값 (inqireValue). 항목에 따라 피해율(%)·밀도·트랩 마리수
    value = models.DecimalField(max_digits=12, decimal_places=3)

    class Meta:
        db_table = 'pest_survey'
        constraints = [
            models.UniqueConstraint(fields=['insect_key', 'sigungu_code', 'pest_code'], name='uk_pest_survey'),
        ]
        indexes = [models.Index(fields=['ncpms_crop_code', 'survey_date'], name='ix_pest_survey_crop_date')]


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
