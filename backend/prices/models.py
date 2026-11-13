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
        indexes = [models.Index(fields=['item', 'market', 'trade_date'], name='idx_settle_item_mkt_date')]


# 실시간 경매 낙찰 건 원본 (erd.md 2.3, REQ-COL-002)
class AuctionTrade(models.Model):
    # source_key: 원본 행을 구분하는 값. 5분마다 겹쳐 받아도 같은 건이 두 번 저장되지 않게 막는다 (중복 불가)
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