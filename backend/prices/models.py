from django.db import models

from codes.models import Item, Market


# 정산 확정 가격. 원본을 Spark로 시장·품목·등급별로 모은 값 (erd.md 2.3, REQ-PRC-001)
class SettlePrice(models.Model):
    # trade_date: 거래정산일자
    trade_date = models.DateField()
    # market: 시장 FK. 가격 이력이 있는 시장은 지울 수 없게 막는다 (PROTECT, DB 컬럼은 market_id)
    market = models.ForeignKey(Market, on_delete=models.PROTECT)
    # item: 품목 FK. 가격 이력이 있는 품목은 지울 수 없게 막는다 (PROTECT, DB 컬럼은 item_id)
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    # grade: 등급. 전 등급 합계는 'ALL'
    grade = models.CharField(max_length=10)
    # avg_price: 물량 가중 평균 가격 (원/kg)
    avg_price = models.DecimalField(max_digits=10, decimal_places=1)
    # min_price: 최저 가격 (원/kg)
    min_price = models.DecimalField(max_digits=10, decimal_places=1)
    # max_price: 최고 가격 (원/kg)
    max_price = models.DecimalField(max_digits=10, decimal_places=1)
    # volume_kg: 거래 물량 (kg)
    volume_kg = models.DecimalField(max_digits=12, decimal_places=1)

    class Meta:
        db_table = 'settle_price'
        # 같은 날짜를 다시 수집해도 같은 (날짜, 시장, 품목, 등급) 행이 두 번 저장되지 않게 막는다 (REQ-COL-008)
        constraints = [models.UniqueConstraint(fields=['trade_date', 'market', 'item', 'grade'], name='uk_settle_price')]
        # 품목·시장별 기간 조회용 (품목 → 시장 → 날짜 순서. 날짜 범위 조건이 맨 뒤에 와야 인덱스가 잘 쓰인다)
        indexes = [models.Index(fields=['item', 'market', 'trade_date'], name='idx_settle_item_mkt_date'),
                   # 품목·등급의 가장 최근 정산일 찾기용 (시장 간 비교, 지금 팔면). 없으면 품목의 모든 행을 읽는다 (T01, REQ-NFR-001)
                   models.Index(fields=['item', 'grade', 'trade_date'], name='idx_settle_item_grade_date')]


# 실시간 경매 낙찰 건 원본 (erd.md 2.3, REQ-COL-002)
class AuctionTrade(models.Model):
    # source_key: 원본 행을 구분하는 값. 주기마다 겹쳐 받아도 같은 건이 두 번 저장되지 않게 막는다 (중복 불가)
    #   무엇을 합쳐서 만들지는 실시간 API 응답을 보고 확정한다
    source_key = models.CharField(max_length=64, unique=True)
    # auction_at: 낙찰 시각 (UTC)
    auction_at = models.DateTimeField()
    # market: 시장 FK. 낙찰 이력이 있는 시장은 지울 수 없게 막는다 (DB 컬럼은 market_id)
    market = models.ForeignKey(Market, on_delete=models.PROTECT)
    # item: 품목 FK. 낙찰 이력이 있는 품목은 지울 수 없게 막는다 (DB 컬럼은 item_id)
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    # corp_name: 법인명
    corp_name = models.CharField(max_length=30)
    # grade: 등급
    grade = models.CharField(max_length=10)
    # origin: 산지
    origin = models.CharField(max_length=30)
    # price_per_kg: 낙찰가 (원/kg)
    price_per_kg = models.DecimalField(max_digits=10, decimal_places=1)
    # volume_kg: 물량 (kg)
    volume_kg = models.DecimalField(max_digits=10, decimal_places=1)
    # collected_at: 수집 시각 (UTC)
    collected_at = models.DateTimeField()

    class Meta:
        db_table = 'auction_trade'
        # 시장·품목별 시간 범위 조회용 (시장 → 품목 → 낙찰 시각 순서)
        indexes = [models.Index(fields=['market', 'item', 'auction_at'], name='idx_auction_mkt_item_at')]


# 당일 경매 집계. Flink(streaming/flink/realtime_price.sql)가 낙찰이 들어올 때마다 UPSERT 한다 (erd.md 3절, REQ-PRC-004)
#   Django는 테이블 구조만 소유하고 값은 쓰지 않는다. 확정 가격은 다음 날 settle_price에서 본다
class RealtimePrice(models.Model):
    # trade_date: 정산일자 (원본 trd_clcln_ymd). 전날 오후 경매분도 포함되며, settle_price.trade_date와 같은 기준
    trade_date = models.DateField()
    # market: 시장 FK (DB 컬럼은 market_id)
    market = models.ForeignKey(Market, on_delete=models.PROTECT)
    # item: 품목 FK (DB 컬럼은 item_id)
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    # avg_price: 물량 가중 평균 낙찰가 (원/kg) = Σ(가격×물량) / Σ물량
    avg_price = models.DecimalField(max_digits=10, decimal_places=1)
    # min_price: 최저 낙찰가 (원/kg)
    min_price = models.DecimalField(max_digits=10, decimal_places=1)
    # max_price: 최고 낙찰가 (원/kg)
    max_price = models.DecimalField(max_digits=10, decimal_places=1)
    # volume_kg: 당일 누적 물량 (kg)
    volume_kg = models.DecimalField(max_digits=12, decimal_places=1)
    # trade_count: 당일 낙찰 건수
    trade_count = models.IntegerField()
    # last_auction_at: 가장 늦은 낙찰 시각 (UTC)
    last_auction_at = models.DateTimeField()
    # updated_at: Flink가 이 행을 마지막으로 쓴 시각 (UTC). 지연 측정(REQ-NFR-003)에 쓴다
    updated_at = models.DateTimeField()

    class Meta:
        db_table = 'realtime_price'
        # Flink JDBC 싱크의 PRIMARY KEY와 같은 키. 이 키로 INSERT ... ON DUPLICATE KEY UPDATE 된다
        constraints = [models.UniqueConstraint(fields=['trade_date', 'market', 'item'], name='uk_realtime_price')]
        # API는 품목으로 찾고 날짜로 거른다 (품목 → 날짜 순서)
        indexes = [models.Index(fields=['item', 'trade_date'], name='idx_realtime_item_date')]

# 과실 생산량. KOSIS 과실생산량(DT_1ET0292) 전국·연 단위. 예측 피처용 (erd.md 3절, REQ-COL-003)
class CropProduction(models.Model):
    # item: 품목 FK. 생산량 이력이 있는 품목은 지울 수 없게 막는다 (PROTECT, DB 컬럼은 item_id)
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    # year: 연도 (KOSIS PRD_DE)
    year = models.SmallIntegerField()
    # area_ha: 재배면적 (ha). KOSIS에 값이 없는 해가 있을 수 있어 비어도 된다
    area_ha = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    # production_kg: 생산량 (kg). KOSIS 단위는 톤이라 1000을 곱해 저장한다 (CLAUDE.md 단위 규칙)
    production_kg = models.BigIntegerField(null=True, blank=True)
    # yield_kg_10a: 10a당 생산량 (kg)
    yield_kg_10a = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)
    # kosis_updated_on: KOSIS 최종 수정일 (LST_CHN_DE). 예측은 이 날짜 뒤에만 그해 값을 쓴다 (공표 전 값 누수 방지)
    kosis_updated_on = models.DateField()

    class Meta:
        db_table = 'crop_production'
        # 같은 해를 다시 수집해도 (품목, 연도) 행이 두 번 저장되지 않게 막는다 (UPSERT 기준)
        constraints = [models.UniqueConstraint(fields=['item', 'year'], name='uk_crop_production')]


# 주간 가격 예측. 김기현의 ml/ 예측 작업이 매주 월요일 시장 × h(1~4) 행을 넣는다 (erd.md 3절, REQ-PRD-001~005)
#   Django는 테이블 구조와 조회 API를 소유한다. 지난 예측도 지우지 않는다 (REQ-PRD-005)
class Forecast(models.Model):
    # item: 품목 FK (DB 컬럼은 item_id). 예측 이력이 있는 품목은 지울 수 없게 막는다
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    # market: 시장 FK (DB 컬럼은 market_id)
    market = models.ForeignKey(Market, on_delete=models.PROTECT)
    # base_week: 예측 기준 월요일. h1의 대상 주가 이 주 (이번 주)
    base_week = models.DateField()
    # horizon: 몇 주 앞인지 (1~4). 대상 주 = base_week + (horizon-1)주
    horizon = models.SmallIntegerField()
    # target_week: 예측 대상 주의 월요일
    target_week = models.DateField()
    # pred_price: 예측 주평균 가격 (원/kg)
    pred_price = models.DecimalField(max_digits=10, decimal_places=1)
    # lower80, upper80: 80% 예측 구간 (원/kg)
    lower80 = models.DecimalField(max_digits=10, decimal_places=1)
    upper80 = models.DecimalField(max_digits=10, decimal_places=1)
    # last_week_price: 기준 시점의 지난주 실제 주평균 가격 (원/kg). 비어도 된다
    last_week_price = models.DecimalField(max_digits=10, decimal_places=1, null=True, blank=True)
    # model_version: 쓴 모델 버전 (MLflow, REQ-PRD-004)
    model_version = models.CharField(max_length=50)
    # created_at: 예측을 만든 시각 (UTC)
    created_at = models.DateTimeField()

    class Meta:
        db_table = 'forecast'
        # 같은 기준 주를 다시 돌려도 행이 두 번 저장되지 않게 막는다
        constraints = [models.UniqueConstraint(
            fields=['item', 'market', 'base_week', 'horizon'], name='uk_forecast')]


# 검증 예측(백테스트): 서비스가 예측을 내보내기 전 기간을 모델 검증 때의 예측으로 채운다 (가격 통계 차트의 지난 예측 선)
#   그 시점 이전 데이터로만 학습한 값이지만 그때 실제로 보여 준 예측은 아니라서 forecast와 섞지 않는다.
#   값 채우기는 ml/farmit_ml/backtest_store.py
class ForecastBacktest(models.Model):
    # item: 품목 FK (DB 컬럼은 item_id)
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    # market: 시장 FK (DB 컬럼은 market_id)
    market = models.ForeignKey(Market, on_delete=models.PROTECT)
    # target_week: 예측 대상 주의 월요일
    target_week = models.DateField()
    # horizon: 몇 주 앞 예측인지 (1~4). 1 = 그 주 월요일에 한 그 주 예측
    horizon = models.SmallIntegerField()
    # pred_price: 예측 주평균 가격 (원/kg)
    pred_price = models.DecimalField(max_digits=10, decimal_places=1)
    # lower80, upper80: 80% 예측 구간 (원/kg)
    lower80 = models.DecimalField(max_digits=10, decimal_places=1)
    upper80 = models.DecimalField(max_digits=10, decimal_places=1)
    # model_version: 검증에 쓴 설정 버전 (예: v4-backtest)
    model_version = models.CharField(max_length=50)
    # created_at: 적재한 시각 (UTC)
    created_at = models.DateTimeField()

    class Meta:
        db_table = 'forecast_backtest'
        # 다시 적재해도 행이 두 번 저장되지 않게 막는다
        constraints = [models.UniqueConstraint(
            fields=['item', 'market', 'target_week', 'horizon'], name='uk_forecast_backtest')]


# 내 위치(시군구 중심) → 시장 도로 경로. 카카오모빌리티 자동차 길찾기 결과를 저장해 다시 쓴다 (REQ-REC-002)
#   처음 그 시군구의 회원이 판매 추천을 열 때 채운다 (prices/routes.py). 시장 좌표를 고치면 그 시장 행을 지워 다시 받는다
class MarketRoute(models.Model):
    # sido, sigungu: 출발지 (user_profile과 같은 표기). 좌표는 codes/fixtures/sigungu_coords.json의 시군구 중심
    sido = models.CharField(max_length=20)
    sigungu = models.CharField(max_length=20)
    # market: 도착 시장 FK (DB 컬럼은 market_id). 시장을 지우면 경로도 지운다
    market = models.ForeignKey(Market, on_delete=models.CASCADE)
    # distance_m: 도로 거리 (m, 카카오 원본 단위)
    distance_m = models.IntegerField()
    # toll_won: 통행료 (원, 1종 차량·하이패스 아님)
    toll_won = models.IntegerField()
    # duration_s: 소요 시간 (초). 조회 시점의 교통 상황 기준이라 참고용
    duration_s = models.IntegerField()
    # fetched_at: 카카오에서 받은 시각 (UTC)
    fetched_at = models.DateTimeField()

    class Meta:
        db_table = 'market_route'
        # 같은 출발지·시장은 한 번만 저장한다
        constraints = [models.UniqueConstraint(fields=['sido', 'sigungu', 'market'], name='uk_market_route')]
