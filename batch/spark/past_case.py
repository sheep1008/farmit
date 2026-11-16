"""과거 사례 리포트 (K18, REQ-HIS-001). 사건 전후 몇 주의 가격 변화를 계산한다.

1단계 — 사건 추출. 품목마다 다섯 종류의 사건을 (품목, 종류, 시작일, 끝일) 목록으로 만든다.
  날씨(주산지 ASOS, weather_daily × item_producing_area). 일자료만 있으므로 기상청 통계 정의를 쓴다.
    폭염 HEAT_WAVE   일최고기온 ≥ 33℃가 2일 이상 이어짐 (기상청 폭염일수 기준 33℃, 폭염특보 "2일 이상 지속")
    호우 HEAVY_RAIN  일강수량 ≥ 80mm (기상청 극한기후지수 "호우일수"). 특보 기준(3·12시간 강수량)은 시간자료라 쓸 수 없다
    한파 COLD_WAVE   일최저기온 ≤ −12℃가 2일 이상 이어짐 (한파특보 "아침 최저 −12℃ 이하 2일 이상 지속")
  관측소마다 기준을 넘은 연속 구간을 찾고, 같은 품목의 구간이 MERGE_GAP_DAYS일 안에 붙어 있으면 한 사건으로 합친다.
  합친 사건에 걸린 주산지 물량 비중(volume_share 합)이 MIN_SHARE% 미만이면 버린다. 한 시군만의 날씨는 가격을 움직이기 어렵다.
  (사과 주산지 8곳 2018~2026: 기준 20%로 폭염 22·호우 19·한파 19건, 한 해 2~3건)
  수입 급증·예찰 증가는 K17이 만든 special_event를 그대로 쓴다.
    수입 급증: 그달 1일 ~ 말일, 시도 '전국'
    예찰 증가: 같은 품목·같은 조사일에 여러 시군이 걸렸으면 한 사건으로 합친다 (가격은 시군별로 갈리지 않는다)

2단계 — 전후 가격 변화. 사건 × 시장마다:
  기준 주 = 사건이 시작된 주(월요일), 기준가 = 그 주 kg당 가격 (weekly_price와 같은 정의: 등외·하·5등 이하 제외 물량가중)
  change_wk = (k주 뒤 주 가격 / 기준가 − 1) × 100 (%), k = 1~4. 그 주 거래가 없으면 비운다. 기준 주 거래가 없으면 행을 만들지 않는다.
  normal_wk = 평년 같은 주 변화율: 사건이 난 해를 뺀 다른 해들에서 기준 주와 같은 주차의 change_wk 평균 (3년 미만이면 비움).
    사과 한파 사건 뒤 +10%는 대부분 설 대목 상승이라, 평년과 나란히 봐야 사건 몫을 짐작할 수 있다.
    주차로 맞추므로 해마다 날짜가 바뀌는 명절은 1~3주 어긋날 수 있다.
  시장: 수집·참고 시장(is_collect OR is_reference). 가격 화면·예측과 같은 시장이다.
  결과는 past_case를 통째로 바꿔 쓴다 (한 트랜잭션에서 DELETE 후 INSERT). 사건 기준을 바꾸면 사라진 사건도 지워져야 하고,
  행이 수백 개라 매번 다시 계산해도 몇십 초다.

실행: docker compose -f infra/docker-compose.yml --profile airflow exec airflow-scheduler \
        sh -c "cd /opt/farmit/spark && python -m past_case"
"""
import json
from datetime import datetime, timezone

from pyspark.sql import Column, DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from common import connect, read, session
from weekly_price import daily, weekly

WEEKS_AFTER = (1, 2, 3, 4)
MIN_NORMAL_YEARS = 3   # 평년 변화율에 쓸 다른 해가 이보다 적으면 비운다 (한두 해 평균은 그해 사정에 휘둘린다)

# 종류: (weather_daily 컬럼, 기준 비교, 최소 연속 일수)
WEATHER_RULES = {
    "HEAT_WAVE": ("max_temp", lambda c: c >= 33, 2),
    "HEAVY_RAIN": ("rain_mm", lambda c: c >= 80, 1),
    "COLD_WAVE": ("min_temp", lambda c: c <= -12, 2),
}
MERGE_GAP_DAYS = 3     # 관측소 구간 사이가 이 일수 이하면 같은 사건 (같은 더위·장마가 지역마다 하루 이틀 어긋난다)
MIN_SHARE = 20.0       # 사건에 걸린 주산지 물량 비중 합(%)이 이보다 작으면 버린다
EVENT_COLS = ["item_id", "event_type", "sido", "event_start", "event_end", "share", "places"]


def station_runs(wx: DataFrame) -> DataFrame:
    """wx(item_id, station_id, sido, sigungu, volume_share, obs_date, max_temp, min_temp, rain_mm)
    → 관측소마다 기준을 넘은 연속 구간 (item_id, event_type, station_id, sido, sigungu, volume_share, start, end).

    연속 구간은 "날짜 − 순번"이 같은 날끼리 묶는다 (gaps and islands). 관측이 빠진 날은 구간을 끊는다 (빠진 값을 기준 미달로 본다).
    """
    out = None
    for etype, (col, rule, min_days) in WEATHER_RULES.items():
        hit = wx.where(rule(F.col(col)))   # NULL은 비교 결과가 NULL이라 빠진다
        w = Window.partitionBy("item_id", "station_id").orderBy("obs_date")
        runs = (hit.withColumn("grp", F.date_sub("obs_date", F.row_number().over(w)))
                .groupBy("item_id", "station_id", "sido", "sigungu", "volume_share", "grp")
                .agg(F.min("obs_date").alias("start"), F.max("obs_date").alias("end"), F.count("*").alias("days"))
                .where(F.col("days") >= min_days)
                .select("item_id", F.lit(etype).alias("event_type"), "station_id", "sido", "sigungu",
                        "volume_share", "start", "end"))
        out = runs if out is None else out.unionByName(runs)
    return out


def merge_runs(runs: DataFrame) -> DataFrame:
    """관측소 구간 → 품목 사건. 시작일 순으로 보다가 앞 구간들의 가장 늦은 끝일 + MERGE_GAP_DAYS보다 늦게 시작하면 새 사건."""
    k = ["item_id", "event_type"]
    w = Window.partitionBy(*k).orderBy("start", "station_id")
    prev_end = F.max("end").over(w.rowsBetween(Window.unboundedPreceding, -1))
    r = (runs.withColumn("new", F.when(prev_end.isNull() | (F.col("start") > F.date_add(prev_end, MERGE_GAP_DAYS)), 1)
                         .otherwise(0))
         .withColumn("gid", F.sum("new").over(w.rowsBetween(Window.unboundedPreceding, 0))))
    # 한 사건에 같은 관측소가 두 번 걸려도 비중은 한 번만 더한다
    per_station = r.groupBy(*k, "gid", "station_id", "sido", "sigungu", "volume_share").agg(
        F.min("start").alias("start"), F.max("end").alias("end"))
    ev = per_station.groupBy(*k, "gid").agg(
        F.min("start").alias("event_start"), F.max("end").alias("event_end"),
        F.sum("volume_share").cast("double").alias("share"),
        # 비중이 가장 큰 주산지의 시도를 사건의 시도로 쓴다
        F.max(F.struct("volume_share", "sido")).getField("sido").alias("sido"),
        F.array_sort(F.collect_list(F.concat_ws(" ", "sido", "sigungu"))).alias("places"))
    return ev.where(F.col("share") >= MIN_SHARE).select(*EVENT_COLS)


def weather_events(wx: DataFrame) -> DataFrame:
    return merge_runs(station_runs(wx))


def kst_date(col: str) -> Column:
    """special_event.occurred_at(UTC) → 한국 날짜"""
    return F.to_date(F.from_utc_timestamp(F.col(col), "Asia/Seoul"))


def special_events(se: DataFrame) -> DataFrame:
    """special_event(event_type, item_id, sido, sigungu, occurred_at) 중 수입 급증·예찰 증가 → 사건 목록."""
    day = kst_date("occurred_at")
    imp = (se.where((F.col("event_type") == "IMPORT_SURGE") & F.col("item_id").isNotNull())
           .select("item_id", "event_type", F.lit("전국").alias("sido"), day.alias("event_start"),
                   F.last_day(day).alias("event_end"), F.lit(None).cast("double").alias("share"),
                   F.array().cast("array<string>").alias("places")))
    pest = (se.where(F.col("event_type") == "PEST_INCREASE")
            .withColumn("d", day)
            .groupBy("item_id", "event_type", "d")
            .agg(F.min("sido").alias("sido"),
                 F.array_sort(F.collect_set(F.concat_ws(" ", "sido", "sigungu"))).alias("places"))
            .select("item_id", "event_type", "sido", F.col("d").alias("event_start"), F.col("d").alias("event_end"),
                    F.lit(None).cast("double").alias("share"), "places"))
    return imp.unionByName(pest)


def load_weather(spark: SparkSession) -> DataFrame:
    """주산지 관측소 일자료. 주산지는 item_producing_area에 있는 품목만 (지금은 사과)."""
    areas = read(spark, "item_producing_area").select("item_id", "station_id", "sido", "sigungu", "volume_share")
    wx = read(spark, "weather_daily").select("station_id", "obs_date", "max_temp", "min_temp", "rain_mm")
    return areas.join(wx, "station_id")


def extract_events(spark: SparkSession) -> DataFrame:
    se = read(spark, "special_event").select("event_type", "item_id", "sido", "sigungu", "occurred_at")
    return weather_events(load_weather(spark)).unionByName(special_events(se))


def changes(ev: DataFrame, w: DataFrame) -> DataFrame:
    """사건(EVENT_COLS) × 주간 가격 w(item_id, market_cd, week, price_kg) → 시장별 기준가와 1~4주 뒤 변화율."""
    e = ev.withColumn("base_week", F.to_date(F.date_trunc("week", "event_start")))   # date_trunc('week')는 월요일
    p = w.where(F.col("price_kg").isNotNull()).select("item_id", "market_cd", "week", "price_kg")
    j = e.join(p, (e.item_id == p.item_id) & (p.week >= e.base_week) &
               (p.week <= F.date_add(e.base_week, 7 * max(WEEKS_AFTER)))).drop(p.item_id)
    j = j.withColumn("k", (F.datediff("week", "base_week") / 7).cast("int"))
    key = EVENT_COLS + ["base_week", "market_cd"]
    out = j.groupBy(*key).agg(F.max(F.when(F.col("k") == 0, F.col("price_kg"))).alias("base_price"),
                              *[F.max(F.when(F.col("k") == k, F.col("price_kg"))).alias(f"p{k}") for k in WEEKS_AFTER])
    out = out.where(F.col("base_price").isNotNull())
    for k in WEEKS_AFTER:
        out = out.withColumn(f"change_w{k}", F.round((F.col(f"p{k}") / F.col("base_price") - 1) * 100, 2)).drop(f"p{k}")
    return with_normal(out.withColumn("base_price", F.round("base_price", 1)), w)


def forward_changes(w: DataFrame) -> DataFrame:
    """모든 (품목, 시장, 주)의 1~4주 뒤 변화율(%). 평년 비교의 재료."""
    p = w.where(F.col("price_kg").isNotNull()).select("item_id", "market_cd", "week", "price_kg")
    out = p.withColumn("woy", F.weekofyear("week")).withColumn("year", F.year("week"))
    for k in WEEKS_AFTER:
        later = p.select("item_id", "market_cd", F.date_sub("week", 7 * k).alias("week"), F.col("price_kg").alias(f"p{k}"))
        out = out.join(later, ["item_id", "market_cd", "week"], "left") \
            .withColumn(f"c{k}", (F.col(f"p{k}") / F.col("price_kg") - 1) * 100).drop(f"p{k}")
    return out.drop("price_kg")


def with_normal(cases: DataFrame, w: DataFrame) -> DataFrame:
    """사례마다 평년 같은 주 변화율(normal_w1~w4)과 쓴 해 수(normal_years)를 붙인다.

    평년 = 사건이 난 해를 뺀 다른 해에서, 기준 주와 주차(weekofyear)가 같은 주의 변화율 평균. 같은 품목·시장끼리만 본다.
    다른 해에도 같은 종류 사건이 있었을 수 있지만 그대로 둔다 (사건 해를 모두 빼면 한파·폭염처럼 해마다 오는 사건은 비교할 해가 없다).
    """
    fc = forward_changes(w)
    c = cases.withColumn("woy", F.weekofyear("base_week")).withColumn("year", F.year("base_week"))
    key = ["item_id", "market_cd", "event_type", "event_start"]   # 사례 하나를 가리킨다 (share처럼 NULL인 컬럼으로 잇지 않는다)
    j = c.select(*key, "woy", "year").join(
        fc.withColumnRenamed("year", "f_year"), ["item_id", "market_cd", "woy"]).where(F.col("f_year") != F.col("year"))
    norm = j.groupBy(*key).agg(F.countDistinct("f_year").alias("normal_years"),
                               *[F.round(F.avg(f"c{k}"), 2).alias(f"normal_w{k}") for k in WEEKS_AFTER])
    out = cases.join(norm, key, "left")
    few = F.coalesce(F.col("normal_years"), F.lit(0)) < MIN_NORMAL_YEARS
    for k in WEEKS_AFTER:
        out = out.withColumn(f"normal_w{k}", F.when(few, None).otherwise(F.col(f"normal_w{k}")))
    return out.withColumn("normal_years", F.coalesce("normal_years", F.lit(0)))


def weekly_prices(spark: SparkSession, item_ids: list[int]) -> DataFrame:
    markets = [r.market_id for r in read(spark, "market").where("is_collect OR is_reference").select("market_id").collect()]
    return weekly(daily(spark, item_ids, markets))


def to_rows(cases: list[dict], now: datetime) -> list[tuple]:
    """past_case INSERT 값. detail에 날씨 사건의 주산지 비중·시군을 넣는다."""
    rows = []
    for c in cases:
        detail = {"places": c["places"], "normal_years": c["normal_years"]}
        if c["share"] is not None:
            detail["share"] = round(float(c["share"]), 2)
        rows.append((c["item_id"], c["market_cd"], c["event_type"], c["sido"], c["event_start"], c["event_end"],
                     c["base_week"], c["base_price"], *[c[f"change_w{k}"] for k in WEEKS_AFTER],
                     *[c[f"normal_w{k}"] for k in WEEKS_AFTER], json.dumps(detail, ensure_ascii=False), now))
    return rows


def save(conn, rows: list[tuple]) -> int:
    """past_case를 rows로 통째로 바꾼다. 한 트랜잭션이라 중간에 실패하면 이전 결과가 그대로 남는다."""
    cols = ["item_id", "market_id", "event_type", "sido", "event_start", "event_end", "base_week", "base_price",
            *[f"change_w{k}" for k in WEEKS_AFTER], *[f"normal_w{k}" for k in WEEKS_AFTER], "detail", "computed_at"]
    sql = f"INSERT INTO past_case ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})"
    conn.begin()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM past_case")
            n = cur.executemany(sql, rows) if rows else 0
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return n


def main():
    spark = session("past_case")
    conn = connect()
    try:
        ev = extract_events(spark).cache()
        print("사건 수 (품목·종류별):")
        for r in ev.groupBy("item_id", "event_type").count().orderBy("item_id", "event_type").collect():
            print(f"  item {r.item_id} {r.event_type}: {r['count']}건")
        item_ids = [r.item_id for r in ev.select("item_id").distinct().collect()]
        cases = changes(ev, weekly_prices(spark, item_ids)).cache()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        n = save(conn, to_rows([r.asDict() for r in cases.collect()], now))
        print(f"past_case {n}행 저장 (사건 × 시장)")
        print("종류별 평균 변화율(%, 시장·사건 평균):")
        cases.groupBy("item_id", "event_type").agg(
            F.countDistinct("event_start").alias("events"), F.count("*").alias("rows"),
            *[F.round(F.avg(f"change_w{k}"), 1).alias(f"w{k}") for k in WEEKS_AFTER],
            *[F.round(F.avg(f"normal_w{k}"), 1).alias(f"평년w{k}") for k in WEEKS_AFTER]
        ).orderBy("item_id", "event_type").show(truncate=False)
    finally:
        conn.close()
        spark.stop()


if __name__ == "__main__":
    main()
