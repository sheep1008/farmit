"""정산 가격 주간 집계 (K12 2단계·K30, REQ-PRD-001). 예측 대상 품목 × 전국 시장 × 주 한 행.

공통 피처(docs/ml.md 3.1절)의 가격 기본 컬럼과 전국 합계를 만든다. 피처 테이블(features.py)이 시차·전국 비교·명절 등을 붙인다.

- 주: 월요일 시작. trade_date는 aT 정산일자(이미 한국 날짜, DATE 타입)라 시간대 변환 없이 그대로 묶는다.
- 등급 행만 쓴다 (grade = 'ALL' 합계 행은 쓰지 않는다). 이상치를 등급 행에서 거르므로 전 등급 값도 남은 등급 행으로 다시 더한다.
- 이상치(K30): 품목·월마다 등급 행 kg당 가격의 전국 중앙값을 구해 1/5~5배 밖의 행을 뺀다.
  실험(collect_items.py)은 원본 거래 한 건씩 거르지만 DB에는 (날짜, 시장, 등급) 합계만 있어 그 단위로 거른다.
- price_kg: 주 물량가중 kg당 가격. 등외·하·5등 이하는 뺀다 (docs/ml.md 1절 "등외·하·5등 이하 제외")
- price_allgrade: 전 등급 물량가중 가격 (K12의 price_kg_allgrade에서 이름 변경)
- qty_kg, n_trade_days: 전 등급 물량, 거래일 수
- price_last1: 그 주 마지막 거래일의 price_kg (주 후반 움직임)
- nat_price, nat_qty: 그 주 전국(모든 시장) 주요 등급 물량가중 가격, 전 등급 물량. 모든 시장 행에 같은 값이 붙는다
- 거래 없는 주: 첫 주~마지막 주 사이 모든 주를 시장마다 한 행씩 만들고 가격은 비워 둔다 (no_trade = 1).
  시차(1·2·4주 전)를 "행 수"가 아니라 "주"로 세려면 빈 주도 행이 있어야 한다. 예측에서 뺄지는 피처 단계가 정한다.

실행: docker compose -f infra/docker-compose.yml --profile airflow exec airflow-scheduler \
        sh -c "cd /opt/farmit/spark && python -m weekly_price"
"""
from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from common import read, session

# 주 가격(price_kg)에서 뺄 등급. 저품위라 물량은 적고 가격이 크게 낮아 평균을 흔든다
EXCLUDE_GRADES = ["등외", "하", "5등", "6등", "7등", "8등", "9등"]   # 실험 코드(collect_items.EXCL)와 같다
OUTLIER_RATIO = 5   # 품목·월 전국 중앙값의 1/5배 미만·5배 초과는 이상치 (실험 코드와 같다)


def targets(spark: SparkSession):
    """(예측 대상 품목, 집계할 시장). 코드값은 테이블에서 읽는다 (CLAUDE.md 2절).

    시장은 등록된 전국 시장 전부다 (K30). 예측 품목은 K31이 전국으로 받으므로 전국 합계(nat_)를 낼 수 있다.
    """
    items = read(spark, "item").where("is_forecast").select("item_id", F.col("at_code").alias("item_code"))
    markets = read(spark, "market").select(F.col("market_id").alias("market_cd"), F.col("name").alias("market_nm"))
    return items, markets


def daily(spark: SparkSession, item_ids: list[int], market_cds: list[str]) -> DataFrame:
    """대상 품목·시장의 정산 행만 MySQL에서 걸러 읽는다 (settle_price 전체는 수백만 행)."""
    ids = ",".join(str(int(i)) for i in item_ids)                     # 정수로 바꿔 넣는다 (테이블 값, 외부 입력 아님)
    mks = ",".join("'" + m.replace("'", "") + "'" for m in market_cds)
    q = (f"(SELECT trade_date, item_id, market_id AS market_cd, grade, avg_price, volume_kg FROM settle_price "
         f"WHERE item_id IN ({ids}) AND market_id IN ({mks})) AS t")
    return read(spark, q).withColumn("amount", F.col("avg_price") * F.col("volume_kg"))


def drop_outliers(d: DataFrame) -> DataFrame:
    """등급 행 중 품목·월 전국 중앙값(행 단위, 물량 가중 아님)의 1/5~5배 밖을 뺀다. 'ALL' 행도 빠진다."""
    g = d.where(F.col("grade") != "ALL").withColumn("_month", F.trunc("trade_date", "month"))
    med = F.percentile("avg_price", 0.5).over(Window.partitionBy("item_id", "_month"))
    return (g.withColumn("_med", med)
             .where(F.col("avg_price").between(F.col("_med") / OUTLIER_RATIO, F.col("_med") * OUTLIER_RATIO))
             .drop("_month", "_med"))


def weekly(d: DataFrame) -> DataFrame:
    """등급 행 → (품목, 시장, 주) 가격·물량. 'ALL' 행이 섞여 있어도 쓰지 않는다 (등급 행 합과 같은 값이다)."""
    d = d.where(F.col("grade") != "ALL").withColumn("week", F.to_date(F.date_trunc("week", "trade_date")))   # 월요일
    key = ["item_id", "market_cd", "week"]
    main = d.where(~F.col("grade").isin(EXCLUDE_GRADES))

    a = d.groupBy(key).agg(F.sum("volume_kg").alias("qty_kg"), F.sum("amount").alias("amt"),
                           F.countDistinct("trade_date").alias("n_trade_days"))
    a = a.withColumn("price_allgrade", F.col("amt") / F.col("qty_kg")).drop("amt")

    m_day = main.groupBy(key + ["trade_date"]).agg(F.sum("volume_kg").alias("q"), F.sum("amount").alias("a"))
    m = m_day.groupBy(key).agg((F.sum("a") / F.sum("q")).alias("price_kg"))
    last = Window.partitionBy(*key).orderBy(F.col("trade_date").desc())   # 주 안에서 늦은 날짜가 1번
    l1 = m_day.withColumn("rn", F.row_number().over(last)).where("rn = 1") \
        .select(*key, (F.col("a") / F.col("q")).alias("price_last1"))
    return a.join(m, key, "left").join(l1, key, "left")


def full_calendar(w: DataFrame, markets: DataFrame) -> DataFrame:
    """품목마다 첫 주~마지막 주 × 시장 전체를 만들고 집계를 붙인다. 거래 없는 주는 가격이 비고 no_trade = 1."""
    span = w.groupBy("item_id").agg(F.min("week").alias("s"), F.max("week").alias("e"))
    weeks = span.select("item_id", F.explode(F.sequence("s", "e", F.expr("INTERVAL 7 DAYS"))).alias("week"))
    grid = weeks.crossJoin(markets.select("market_cd"))
    out = grid.join(w, ["item_id", "market_cd", "week"], "left")
    return out.withColumn("no_trade", F.col("price_kg").isNull().cast("int"))


def national(d: DataFrame) -> DataFrame:
    """등급 행 → (품목, 주) 전국 가격(주요 등급 물량가중)·전국 물량(전 등급). dataset.weekly의 nat과 같다."""
    d = d.where(F.col("grade") != "ALL").withColumn("week", F.to_date(F.date_trunc("week", "trade_date")))
    main = d.where(~F.col("grade").isin(EXCLUDE_GRADES))
    p = main.groupBy("item_id", "week").agg((F.sum("amount") / F.sum("volume_kg")).alias("nat_price"))
    q = d.groupBy("item_id", "week").agg(F.sum("volume_kg").alias("nat_qty"))
    return q.join(p, ["item_id", "week"], "left")


def build(spark: SparkSession) -> DataFrame:
    items, markets = targets(spark)
    item_ids = [r.item_id for r in items.collect()]
    market_cds = [r.market_cd for r in markets.collect()]
    d = drop_outliers(daily(spark, item_ids, market_cds)).cache()
    out = full_calendar(weekly(d), markets).join(items, "item_id").join(markets, "market_cd")
    out = out.join(national(d), ["item_id", "week"], "left")   # 전국 거래가 없는 주는 비어 있다
    return out.select("item_id", "item_code", "market_cd", "market_nm", "week", "price_kg", "price_allgrade",
                      "price_last1", "qty_kg", "n_trade_days", "no_trade", "nat_price", "nat_qty") \
        .orderBy("item_id", "market_cd", "week")


def main():
    spark = session("weekly_price")
    df = build(spark).cache()
    print("행 수:", df.count())
    df.groupBy("item_code", "market_cd", "market_nm").agg(
        F.count("*").alias("weeks"), F.min("week").alias("first"), F.max("week").alias("last"),
        F.sum("no_trade").alias("no_trade_weeks"), F.round(F.avg("price_kg")).alias("avg_price_kg"),
        F.round(F.avg(F.col("price_kg") / F.col("price_allgrade")), 3).alias("main_vs_all"),
    ).orderBy("item_code", "market_cd").show(50, truncate=False)
    df.where("market_cd = '250001'").orderBy(F.col("week").desc()).show(5, truncate=False)
    spark.stop()


if __name__ == "__main__":
    main()
