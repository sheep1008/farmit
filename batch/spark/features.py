"""학습·예측용 피처 테이블 (K12 3단계·K30, REQ-PRD-001). 예측 품목 × 전국 시장 × 주 한 행 → ml/data/weekly_<품목코드>.csv

공통 피처(docs/ml.md 3.1절) = ml/experiments/dataset.py의 GROUPS에서 가락 묶음·n_records를 뺀 것. 날씨·생산량은 넣지 않는다.
(K12에서 만든 v3용 날씨·가락 피처는 공통 피처에 없어 K30에서 지웠다. 필요하면 git 이력에서 되살린다)

한 행(week = W)의 뜻: W주(월~일)까지 알던 정보로 pred_date = W + 7일(다음 월요일) 아침에 예측한다.
- 타깃: target_h{h} = W + h주의 price_kg (h = 1이 예측하는 그 주)
- 가격 시차·이동평균: 시장별로 주 달력 순서 (거래 없는 주도 행이 있어 "1주 전"이 정확히 1주 전이다)
- 전국(nat_): 품목별 주 달력 순서. 시장 가격과의 비교(dev_nat 등)는 같은 주끼리
- 명절: pred_date·타깃 주와 설·추석 본날 사이 일수
- 학습 시장 선별은 하지 않는다. 전국 시장 행을 모두 내보내고 ML 쪽(K13)이 고른다

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

# 공통 피처 (dataset.GROUPS와 같은 이름·순서, 가락 묶음·n_records 제외)
GROUPS = {
    "base": ["price_kg", "qty_kg", "price_allgrade", "n_trade_days", "price_last1"],
    "lags": ["price_lag1", "price_lag2", "price_lag4", "price_ma4", "price_ma8", "price_yoy", "qty_lag1", "qty_ma4",
             "chg_1w", "chg_4w"],
    "national": ["nat_price", "nat_price_ma4", "ratio_nat_med26", "dev_nat", "nat_chg_1w"],
    "supply": ["nat_qty", "nat_qty_ma4", "nat_qty_yoy", "qty_share", "qty_yoy"],
    "calendar": ["weekofyear", "month", "days_to_seol", "days_since_seol", "days_to_chuseok", "days_since_chuseok"]
                + [f"hol_offset_h{h}" for h in H] + [f"hol_in_target_h{h}" for h in H],
    "market": ["mkt_id"],
}
ID_COLS = ["item_code", "market_cd", "market_nm", "week", "pred_date"]
TARGET_COLS = [f"target_h{h}" for h in H] + [f"target_week_h{h}" for h in H]


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
           .withColumn("qty_ma4", _rolling("qty_kg", w, 4, 2))
           .withColumn("qty_yoy", F.col("qty_kg") / F.lag("qty_kg", 52).over(w))
           .withColumn("chg_1w", F.log(F.col("price_kg") / F.col("price_lag1")))
           .withColumn("chg_4w", F.log(F.col("price_kg") / F.col("price_lag4"))))
    for h in H:
        out = (out.withColumn(f"target_h{h}", F.lead("price_kg", h).over(w))
                  .withColumn(f"target_week_h{h}", F.date_add("week", 7 * h)))
    return out.withColumn("pred_date", F.date_add("week", 7))


def national_features(wp: DataFrame) -> DataFrame:
    """품목·주 하나에 한 행인 전국 가격·물량의 시차·이동평균. wp는 품목마다 첫 주~마지막 주가 모두 있다 (weekly_price)."""
    n = wp.select("item_id", "week", "nat_price", "nat_qty").distinct()
    w = Window.partitionBy("item_id").orderBy("week")
    return (n.withColumn("nat_price_ma4", _rolling("nat_price", w, 4, 2))
             .withColumn("nat_qty_ma4", _rolling("nat_qty", w, 4, 2))
             .withColumn("nat_qty_yoy", F.col("nat_qty") / F.lag("nat_qty", 52).over(w))
             .withColumn("nat_chg_1w", F.log(F.col("nat_price") / F.lag("nat_price", 1).over(w))))


def vs_national(df: DataFrame) -> DataFrame:
    """시장 가격·물량을 같은 주 전국 값과 비교한다. ratio_nat_med26 = 시장별 dev_nat의 26주 이동 중앙값(8개 이상)."""
    w = Window.partitionBy("item_id", "market_cd").orderBy("week").rowsBetween(-25, 0)
    df = df.withColumn("dev_nat", F.log(F.col("price_kg") / F.col("nat_price")))
    # F.percentile(…, 0.5)는 짝수 개면 가운데 둘의 평균이라 pandas median과 같다. NULL(거래 없는 주)은 빼고 센다
    return (df.withColumn("ratio_nat_med26", F.when(F.count("dev_nat").over(w) >= 8,
                                                    F.percentile("dev_nat", 0.5).over(w)))
              .withColumn("qty_share", F.col("qty_kg") / F.col("nat_qty")))


def main_holidays_of(holiday: DataFrame) -> DataFrame:
    """holiday(holiday_date, name) → 설·추석 본날(kind, hday). 본날 = 연휴 사흘의 가운데 날.

    이름에 '설날'·'추석'이 들어 있고 '대체'가 없는 날을 연휴로 본다. 다른 공휴일과 겹친 날은 이름이 합쳐져 온다
    (2017-10-03 '개천절·추석') → 이름이 정확히 같은 날만 고르면 연휴 첫날이 빠져 본날이 하루 밀린다.
    """
    name = F.col("name")
    h = holiday.where((name.contains("설날") | name.contains("추석")) & ~name.contains("대체")) \
        .withColumn("kind", F.when(name.contains("설날"), "seol").otherwise("chuseok")) \
        .withColumn("year", F.year("holiday_date"))
    return h.groupBy("kind", "year").agg(F.date_add(F.min("holiday_date"), 1).alias("hday")).select("kind", "hday")


def main_holidays(spark: SparkSession) -> DataFrame:
    return main_holidays_of(read(spark, "holiday"))


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
    df = price_features(wp).drop("nat_price", "nat_qty")
    df = df.join(national_features(wp), ["item_id", "week"], "left")
    df = vs_national(df)
    df = df.join(holiday_features(df.select("week").distinct(), main_holidays(spark)), "week", "left")
    df = (df.withColumn("weekofyear", F.weekofyear("week")).withColumn("month", F.month("week"))
            .withColumn("mkt_id", F.col("market_cd").cast("int")))
    feats = [c for g in GROUPS.values() for c in g]
    # 지난주 거래가 없으면 그 주는 예측하지 않는다 (실험 코드와 같음). 시차는 위에서 빈 주까지 넣어 계산했다
    return (df.where(F.col("price_kg").isNotNull())
              .select("item_id", *ID_COLS, *feats, *TARGET_COLS)
              .orderBy("item_id", "market_cd", "week"))


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
