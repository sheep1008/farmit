"""학습·예측용 피처 테이블 (K12 3단계, REQ-PRD-001). 예측 시장 × 주 한 행 → ml/data/weekly_<품목코드>.csv

ml/farmit_ml v3 입력 형식(docs/ml.md 3절)에 맞춘다. 지금은 정의가 확실한 컬럼만 만든다.
정의는 ml/experiments/dataset.py·weather.py(v3를 만든 실험 코드의 정리본)를 따른다.
아직 없는 컬럼(정의를 양정호에게 확인 중이거나 DB에 원천이 없는 것)은 K12 카드 변경 메모에 적어 둔다.

한 행(week = W)의 뜻: W주(월~일)까지 알던 정보로 pred_date = W + 7일(다음 월요일) 아침에 예측한다.
- 타깃: target_h{h} = W + h주의 price_kg (h = 1이 예측하는 그 주)
- 가격 시차·이동평균: 시장별로 주 달력 순서 (거래 없는 주도 행이 있어 "1주 전"이 정확히 1주 전이다)
- 날씨: 주산지 관측소(item_producing_area) 물량 비중 가중 평균. W주의 날씨는 W주 일요일까지라 다음 월요일에 쓸 수 있다
- 명절: pred_date·타깃 주와 설·추석 본날 사이 일수

실행: docker compose -f infra/docker-compose.yml --profile airflow exec airflow-scheduler \
        sh -c "cd /opt/farmit/spark && python -m features"
"""
import os
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from common import read, session
from weekly_price import build as weekly_price

OUT_DIR = Path(os.environ.get("FARMIT_ML_DATA_DIR", "/opt/farmit/ml-data"))   # compose가 ml/data를 붙여 둔 곳
H = (1, 2, 3, 4)
DAY_CAP = 400        # 명절까지 일수 상한 (실험 코드와 같음)
OFFSET_CLIP = 35     # 타깃 주와 가장 가까운 명절의 일수 차이를 ±35일로 자름


def _rolling(col: str, w: Window, n: int, min_n: int, how=F.avg):
    """pandas rolling(n, min_periods=min_n)과 같다: 값이 있는 칸이 min_n개 미만이면 비운다."""
    win = w.rowsBetween(-(n - 1), 0)
    return F.when(F.count(col).over(win) >= min_n, how(col).over(win))


def price_features(wp: DataFrame) -> DataFrame:
    w = Window.partitionBy("item_id", "market_cd").orderBy("week")
    out = wp
    for L in (1, 2, 4):
        out = out.withColumn(f"price_lag{L}", F.lag("price_kg", L).over(w))
    out = (out
           .withColumn("price_ma4", _rolling("price_kg", w, 4, 2))
           .withColumn("price_ma8", _rolling("price_kg", w, 8, 4))
           .withColumn("price_yoy", F.lag("price_kg", 52).over(w))          # 52주 전 = 전년 같은 주
           .withColumn("qty_lag1", F.lag("qty_kg", 1).over(w))
           .withColumn("qty_ma4", _rolling("qty_kg", w, 4, 2)))
    for h in H:
        out = (out.withColumn(f"target_h{h}", F.lead("price_kg", h).over(w))
                  .withColumn(f"target_week_h{h}", F.date_add("week", 7 * h)))
    return out.withColumn("pred_date", F.date_add("week", 7))


def garak_features(spark: SparkSession, wp: DataFrame) -> DataFrame:
    """참고 시장(가락)의 같은 주 가격·물량. 시장 코드는 market.is_reference로 고른다."""
    ref = [r.market_id for r in read(spark, "market").where("is_reference").select("market_id").collect()]
    if len(ref) != 1:
        raise ValueError(f"참고 시장(is_reference)은 하나여야 한다: {ref}")
    w = Window.partitionBy("item_id").orderBy("week")
    return (wp.where(F.col("market_cd") == ref[0])
            .select("item_id", "week", F.col("price_kg").alias("garak_price_kg"), F.col("qty_kg").alias("garak_qty_kg"))
            .withColumn("garak_price_ma4", _rolling("garak_price_kg", w, 4, 2)))


def weather_features(spark: SparkSession) -> DataFrame:
    """품목별 주간 날씨. 일별로 관측소를 물량 비중으로 가중 평균한 뒤 주로 묶는다 (weather.py와 같은 순서).

    - 그날 값이 빈 관측소는 그날 다른 관측소 평균으로 채운다. 그날 행이 없는 관측소는 가중치에서 빠진다
    - 강수 결측은 0 (비가 오지 않은 날은 값이 비어 온다)
    - 폭염일: 가중 최고기온 33도 이상, 한파일: 가중 최저기온 0도 미만
    """
    area = read(spark, "item_producing_area").select("item_id", "station_id", F.col("volume_share").alias("wt"))
    wd = read(spark, "weather_daily").withColumn("rain_mm", F.coalesce("rain_mm", F.lit(0)))
    d = area.join(wd, "station_id")
    day = Window.partitionBy("item_id", "obs_date")
    cols = {"avg_temp": "ta_avg", "max_temp": "ta_max", "min_temp": "ta_min", "rain_mm": "rn", "humidity": "rhm"}
    for c in cols:
        d = d.withColumn(c, F.coalesce(c, F.avg(c).over(day)))   # 그날 모두 비면 계속 비어 있다
    agg = []
    for c, nm in cols.items():
        # 값이 있는 관측소의 가중치로만 나눈다 (np.average와 같음)
        agg.append((F.sum(F.col(c) * F.col("wt")) / F.sum(F.when(F.col(c).isNotNull(), F.col("wt")))).alias(nm))
    g = d.groupBy("item_id", "obs_date").agg(*agg)
    g = (g.withColumn("heat", (F.col("ta_max") >= 33).cast("int"))
          .withColumn("cold", (F.col("ta_min") < 0).cast("int"))
          .fillna(0, ["heat", "cold"])                                    # 기온이 비면 폭염·한파 아님 (pandas 비교와 같음)
          .withColumn("week", F.to_date(F.date_trunc("week", "obs_date"))))
    wk = g.groupBy("item_id", "week").agg(
        F.avg("ta_avg").alias("wx_ta_avg"), F.max("ta_max").alias("wx_ta_max"), F.min("ta_min").alias("wx_ta_min"),
        F.sum("rn").alias("wx_rn_sum"), F.avg("rhm").alias("wx_rhm_avg"),
        F.sum("heat").alias("wx_heat_days"), F.sum("cold").alias("wx_cold_days"))
    w = Window.partitionBy("item_id").orderBy("week")
    return (wk.withColumn("wx_rn_sum_4w", _rolling("wx_rn_sum", w, 4, 2, F.sum))
              .withColumn("wx_rn_sum_12w", _rolling("wx_rn_sum", w, 12, 6, F.sum))
              .withColumn("wx_heat_days_4w", _rolling("wx_heat_days", w, 4, 2, F.sum))
              .withColumn("wx_cold_days_4w", _rolling("wx_cold_days", w, 4, 2, F.sum)))


def main_holidays(spark: SparkSession) -> DataFrame:
    """설·추석 본날. holiday에는 연휴 사흘이 같은 이름으로 들어 있어 가운데 날(본날)을 고른다. 대체공휴일은 이름이 달라 빠진다."""
    h = read(spark, "holiday").where(F.col("name").isin("설날", "추석")) \
        .withColumn("year", F.year("holiday_date"))
    w = Window.partitionBy("name", "year").orderBy("holiday_date")
    return (h.withColumn("rn", F.row_number().over(w)).where("rn = 2")
             .select(F.when(F.col("name") == "설날", "seol").otherwise("chuseok").alias("kind"),
                     F.col("holiday_date").alias("hday")))


def holiday_features(weeks: DataFrame, hol: DataFrame) -> DataFrame:
    """weeks(주 목록) × 명절을 모두 짝지어 가장 가까운 명절을 찾는다 (명절은 해마다 2개라 짝이 수천 개뿐이다)."""
    x = weeks.crossJoin(hol).withColumn("pred", F.date_add("week", 7))
    x = x.withColumn("diff", F.datediff("hday", "pred"))            # 명절 - 예측일. 0 이상이면 아직 안 옴
    aggs = []
    for k in ("seol", "chuseok"):
        is_k = F.col("kind") == k
        aggs.append(F.least(F.min(F.when(is_k & (F.col("diff") >= 0), F.col("diff"))), F.lit(DAY_CAP)).alias(f"days_to_{k}"))
        aggs.append(F.least(F.min(F.when(is_k & (F.col("diff") < 0), -F.col("diff"))), F.lit(DAY_CAP)).alias(f"days_since_{k}"))
    for h in H:
        dh = F.datediff("hday", F.date_add("week", 7 * h))            # 명절 - 타깃 주 월요일
        # 가장 가까운 명절의 차이: |차이|가 가장 작은 값 (struct 정렬은 첫 필드부터 비교)
        aggs.append(F.min(F.struct(F.abs(dh), dh)).getField("col2").alias(f"_near_h{h}"))
        # 연휴(본날 전날~다음날)가 타깃 주(월~일)와 겹치면 1
        aggs.append(F.max(((dh >= -1) & (dh <= 7)).cast("int")).alias(f"hol_in_target_h{h}"))
    out = x.groupBy("week").agg(*aggs)
    for h in H:
        out = out.withColumn(f"hol_offset_h{h}", F.greatest(F.least(f"_near_h{h}", F.lit(OFFSET_CLIP)), F.lit(-OFFSET_CLIP))) \
                 .drop(f"_near_h{h}")
    # least(NULL, 400)은 400이 된다 → 앞뒤로 명절 데이터가 없으면 상한값 (실험 코드의 10**6 → 400과 같음)
    return out


def build(spark: SparkSession) -> DataFrame:
    wp = weekly_price(spark).cache()
    collect = [r.market_id for r in read(spark, "market").where("is_collect").select("market_id").collect()]
    df = price_features(wp).where(F.col("market_cd").isin(collect))   # 예측 시장만 남긴다 (가락은 피처로만)
    df = df.join(garak_features(spark, wp), ["item_id", "week"], "left")
    df = df.join(weather_features(spark), ["item_id", "week"], "left")
    df = df.join(holiday_features(df.select("week").distinct(), main_holidays(spark)), "week", "left")
    df = (df.withColumn("weekofyear", F.weekofyear("week")).withColumn("month", F.month("week")))
    # 지난주 거래가 없으면 그 주는 예측하지 않는다 (실험 코드와 같음). 시차는 위에서 빈 주까지 넣어 계산했다
    return df.where(F.col("price_kg").isNotNull()).orderBy("item_id", "market_cd", "week")


def summary(pdf) -> None:
    print(f"행 {len(pdf)}, 컬럼 {pdf.shape[1]}, 주 {pdf.week.min()} ~ {pdf.week.max()}")
    print(pdf.groupby(["market_cd", "market_nm"]).size().to_string())
    na = pdf.isna().mean().mul(100).round(1)
    print("결측률(%) 0이 아닌 컬럼:")
    print(na[na > 0].sort_values(ascending=False).to_string())


def main():
    spark = session("features")
    df = build(spark)
    pdf = df.toPandas()   # 수천 행이라 드라이버로 모아 CSV 하나로 쓴다 (Spark 기본 저장은 part 파일 여러 개)
    spark.stop()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for code, g in pdf.groupby("item_code"):
        path = OUT_DIR / f"weekly_{code}.csv"
        g.drop(columns=["item_id"]).to_csv(path, index=False, encoding="utf-8")
        print(f"저장: {path}")
        summary(g)


if __name__ == "__main__":
    main()
