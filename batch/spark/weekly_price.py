"""정산 가격 주간 집계 (K12 2단계, REQ-PRD-001). 예측 대상 품목 × 수집·참고 시장 × 주 한 행.

v3 입력(docs/ml.md 3절)의 가격 기본 컬럼을 만든다. 3단계 피처 테이블이 이 결과에 시차·날씨·명절 등을 붙인다.

- 주: 월요일 시작. trade_date는 aT 정산일자(이미 한국 날짜, DATE 타입)라 시간대 변환 없이 그대로 묶는다.
- price_kg: 주 물량가중 kg당 가격. 등외·하·5등 이하는 뺀다 (docs/ml.md 1절 "등외·하·5등 이하 제외")
- price_kg_allgrade: 전 등급(grade = 'ALL') 물량가중 가격
- qty_kg, n_trade_days: 전 등급 물량, 거래일 수
- price_last1: 그 주 마지막 거래일의 price_kg (주 후반 움직임)
- 거래 없는 주: 첫 주~마지막 주 사이 모든 주를 시장마다 한 행씩 만들고 가격은 비워 둔다 (no_trade = 1).
  시차(1·2·4주 전)를 "행 수"가 아니라 "주"로 세려면 빈 주도 행이 있어야 한다. 예측에서 뺄지는 피처 단계가 정한다.

실행: docker compose -f infra/docker-compose.yml --profile airflow exec airflow-scheduler \
        sh -c "cd /opt/farmit/spark && python -m weekly_price"
"""
from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from common import read, session

# 주 가격(price_kg)에서 뺄 등급. 저품위라 물량은 적고 가격이 크게 낮아 평균을 흔든다
EXCLUDE_GRADES = ["등외", "하", "5등", "6등", "7등", "8등"]   # 사과 정산에 실제로 나온 등급 기준 (2018~2026-11)


def targets(spark: SparkSession):
    """(예측 대상 품목, 집계할 시장). 코드값은 테이블에서 읽는다 (CLAUDE.md 2절)."""
    items = read(spark, "item").where("is_forecast").select("item_id", F.col("at_code").alias("item_code"))
    # 수집 시장 + 참고 시장(가락, 가락 대비 피처용)
    markets = read(spark, "market").where("is_collect OR is_reference") \
        .select(F.col("market_id").alias("market_cd"), F.col("name").alias("market_nm"))
    return items, markets


def daily(spark: SparkSession, item_ids: list[int], market_cds: list[str]) -> DataFrame:
    """대상 품목·시장의 정산 행만 MySQL에서 걸러 읽는다 (settle_price 전체는 수백만 행)."""
    ids = ",".join(str(int(i)) for i in item_ids)                     # 정수로 바꿔 넣는다 (테이블 값, 외부 입력 아님)
    mks = ",".join("'" + m.replace("'", "") + "'" for m in market_cds)
    q = (f"(SELECT trade_date, item_id, market_id AS market_cd, grade, avg_price, volume_kg FROM settle_price "
         f"WHERE item_id IN ({ids}) AND market_id IN ({mks})) AS t")
    return read(spark, q).withColumn("amount", F.col("avg_price") * F.col("volume_kg"))


def weekly(d: DataFrame) -> DataFrame:
    d = d.withColumn("week", F.to_date(F.date_trunc("week", "trade_date")))   # date_trunc('week')는 월요일
    key = ["item_id", "market_cd", "week"]
    allg = d.where(F.col("grade") == "ALL")
    main = d.where((F.col("grade") != "ALL") & ~F.col("grade").isin(EXCLUDE_GRADES))

    a = allg.groupBy(key).agg(F.sum("volume_kg").alias("qty_kg"), F.sum("amount").alias("amt"),
                              F.countDistinct("trade_date").alias("n_trade_days"))
    a = a.withColumn("price_kg_allgrade", F.col("amt") / F.col("qty_kg")).drop("amt")

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


def build(spark: SparkSession) -> DataFrame:
    items, markets = targets(spark)
    item_ids = [r.item_id for r in items.collect()]
    market_cds = [r.market_cd for r in markets.collect()]
    w = weekly(daily(spark, item_ids, market_cds))
    out = full_calendar(w, markets).join(items, "item_id").join(markets, "market_cd")
    return out.select("item_id", "item_code", "market_cd", "market_nm", "week", "price_kg", "price_kg_allgrade",
                      "price_last1", "qty_kg", "n_trade_days", "no_trade").orderBy("item_id", "market_cd", "week")


def main():
    spark = session("weekly_price")
    df = build(spark).cache()
    print("행 수:", df.count())
    df.groupBy("item_code", "market_cd", "market_nm").agg(
        F.count("*").alias("weeks"), F.min("week").alias("first"), F.max("week").alias("last"),
        F.sum("no_trade").alias("no_trade_weeks"), F.round(F.avg("price_kg")).alias("avg_price_kg"),
        F.round(F.avg(F.col("price_kg") / F.col("price_kg_allgrade")), 3).alias("main_vs_all"),
    ).orderBy("item_code", "market_cd").show(truncate=False)
    df.where("market_cd = '250001'").orderBy(F.col("week").desc()).show(5, truncate=False)
    spark.stop()


if __name__ == "__main__":
    main()
