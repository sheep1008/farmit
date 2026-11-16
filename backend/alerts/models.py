from django.conf import settings
from django.db import models

from codes.models import Item, Market


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


# 과거 사례: 사건 전후 가격 변화 (erd.md 3, REQ-HIS-001). 사건 1건 × 시장 1곳 = 1행
# batch/spark/past_case.py가 매번 전부 다시 계산해 통째로 바꿔 쓴다 (사건 기준이 바뀌면 옛 사건이 사라져야 해서)
class PastCase(models.Model):
    class EventType(models.TextChoices):
        HEAT_WAVE = 'HEAT_WAVE', '폭염'
        HEAVY_RAIN = 'HEAVY_RAIN', '호우'
        COLD_WAVE = 'COLD_WAVE', '한파'
        IMPORT_SURGE = 'IMPORT_SURGE', '수입량 급증'
        PEST_INCREASE = 'PEST_INCREASE', '예찰 증가'

    # item·market: 품목·시장 FK. 계산 결과라 다시 만들 수 있어 함께 지운다
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
    market = models.ForeignKey(Market, on_delete=models.CASCADE)
    # event_type: 사건 종류. 날씨 3종은 주산지 ASOS로 판정하고, 수입·예찰은 special_event에서 온다
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    # sido: 사건 시도. 날씨는 걸린 주산지 중 물량 비중이 가장 큰 곳, 수입량 급증은 '전국'
    sido = models.CharField(max_length=20)
    # event_start·event_end: 사건 기간 (한국 날짜). 예찰 증가는 조사 기준일 하루, 수입량 급증은 그달 1일~말일
    event_start = models.DateField()
    event_end = models.DateField()
    # base_week: 기준 주(월요일) = 사건이 시작된 주. base_price: 그 주 kg당 가격 (등외·하·5등 이하 제외 물량가중, 원/kg)
    base_week = models.DateField()
    base_price = models.DecimalField(max_digits=10, decimal_places=1)
    # change_w1~w4: 기준 주 대비 1~4주 뒤 가격 변화율(%). 그 주 거래가 없으면 비어 있다
    change_w1 = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    change_w2 = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    change_w3 = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    change_w4 = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    # normal_w1~w4: 평년 같은 주 변화율(%). 사건이 난 해를 뺀 다른 해들의 같은 주차(기준 주와 같은 weekofyear) 변화율 평균.
    # 계절 움직임(설 대목·단경기 등)과 사건 효과를 나란히 보려고 둔다. 비교할 해가 3년 미만이면 비어 있다
    normal_w1 = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    normal_w2 = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    normal_w3 = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    normal_w4 = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    # detail: 사건 상세 (JSON). share(걸린 주산지 물량 비중 %, 날씨만), places(걸린 주산지 '시도 시군' 목록),
    #   normal_years(평년 변화율에 쓴 해 수)
    detail = models.JSONField(default=dict)
    # computed_at: 계산한 시각 (UTC)
    computed_at = models.DateTimeField()

    class Meta:
        db_table = 'past_case'
        constraints = [
            models.UniqueConstraint(fields=['item', 'market', 'event_type', 'event_start'], name='uk_past_case'),
        ]
        indexes = [models.Index(fields=['item', 'event_type', 'event_start'], name='ix_past_case_item_type')]


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
