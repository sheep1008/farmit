"""특수 상황 판정 (K17). 수집된 통계를 기준과 비교해 special_event를 만든다.

1단계 — 수입량 급증 (REQ-ALT-004). import_monthly의 품목(HS 코드)·달마다:
  ① 이번 달 수입량 ≥ 최근 5년 같은 달 평균 + 2 × 표준편차
  ② 이번 달 수입량 ≥ 전년 같은 달 × 1.3
  ③ 이번 달 수입량 ≥ 100t (MIN_IMPORT_KG). 사과처럼 수입이 거의 0인 품목은 평균·σ가 0이라 몇 kg만 들어와도 ①②를 넘는다
  셋 다 맞으면 급증. 과거 5년 같은 달이 모두 있어야 판정한다 (2018년부터 수집 → 2023년부터 판정).

2단계 — 예찰 증가 (REQ-ALT-005). pest_survey의 (작물, 조사 종류, 시군, 항목)마다, 조사 기준일 하나를:
  ① 최근 5년 "같은 시기" 평균 + 2 × 표준편차 이상. 같은 시기 = 조사 기준일의 월·일이 같은 날
     (회차 번호는 해마다 날짜가 달라서 쓰지 않는다. 사과는 2021년까지 1회차 4/1, 2022년부터 5/16)
  ② 같은 해 직전 조사보다 높음. 그해 첫 조사는 직전이 없어 판정하지 않는다
  ①②를 모두 만족하고, 과거 같은 시기가 3년 이상 있어야 한다. 항목마다 단위(피해율·밀도·트랩 마리수)가 달라 항목끼리만 비교한다.
  (처음 요구사항은 3년 미만이면 ②만 봤다. 2015~2026 사과 주산지로 돌려 보니 걸린 건의 78%가 ②만으로 걸려 거의 조사 때마다 알림이 가서 뺐다)
  주산지(item_producing_area) 시군의 결과만 보고, 품목·시군·조사일 하나에 사건 하나 (걸린 항목은 detail.pests에 모은다).
  사건의 시도는 주산지 표기(프로젝트 표기, 예: 전라남도)로 저장한다. NCPMS의 통합 시도 이름(전남광주통합특별시)으로는 회원 지역과 맞출 수 없다.

3단계 — 회원 알림. 최근 ALERT_DAYS일 안에 일어난 사건을 그 품목을 관심 품목으로 담은 회원에게 alert로 만든다.
  수입량 급증은 전국 소식이라 관심 품목 회원 모두에게, 예찰 증가는 지역 소식이라 프로필 지역(시도·시군)이 그 시군인 회원에게만 보낸다.
  (모두에게 보내면 사과 주산지 7곳 × 항목 약 35개 중 어딘가는 거의 매 조사 기준을 넘어, 조사 10번 중 8~9번 알림이 갔다)
  과거 사건(처음 실행하면 수백 건)까지 알리면 알림 목록이 옛 소식으로 덮인다. 과거 사건은 과거 사례(K18) 재료로만 쓴다.
  UNIQUE(user, special_event)와 INSERT IGNORE로 같은 알림을 두 번 만들지 않는다. 나중에 관심 품목을 담은 회원도 다음 실행에서 받는다.

- 매번 전체 기간을 다시 판정한다. 이미 만든 사건은 UNIQUE(event_type, source_ref)에 걸려 INSERT IGNORE가 건너뛴다 (멱등).
  과거 달의 사건도 남겨 두면 과거 사례(K18)가 같은 기준의 사건 목록을 쓸 수 있다.
- 결과는 품목 수 × 달 수 정도라 드라이버로 모아 PyMySQL로 쓴다 (Spark JDBC 쓰기는 INSERT IGNORE를 못 한다).

실행: docker compose -f infra/docker-compose.yml --profile airflow exec airflow-scheduler \
        sh -c "cd /opt/farmit/spark && python -m alert_rules"
"""
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from common import connect, read, session

KST = ZoneInfo("Asia/Seoul")
YEARS = 5                 # 비교할 과거 연수 (REQ-ALT-004 "최근 5년 같은 달")
SIGMA = 2.0               # 평균 + SIGMA × 표준편차
YOY = 1.3                 # 전년 같은 달 대비 +30%
MIN_IMPORT_KG = 100_000   # 100t. 사과 최대 월 수입이 13.2t(2018~2026-10)이라 사과의 몇 kg 수입은 걸리지 않는다
SOURCE_URL = "https://tradedata.go.kr"   # 출처 표시용 (REQ-NFR-007). 원본: 관세청 품목별 국가별 수출입실적 Open API
PEST_MIN_YEARS = 3        # 과거 같은 시기가 이보다 적으면 판정하지 않는다 (REQ-ALT-005)
PEST_SOURCE_URL = "https://ncpms.rda.go.kr"   # 출처 표시용. 원본: 농촌진흥청 국가농작물병해충관리시스템 예찰 정보
# NCPMS는 2026년 통합 시도 이름을, 주산지(기상청 지점 주소 기준)는 옛 이름을 쓴다. 같은 값으로 맞춰 시군을 잇는다
SIDO_KEY = {"전남광주통합특별시": "전남광주", "전라남도": "전남광주", "광주광역시": "전남광주"}
# 이 기간 안에 일어난 사건만 회원에게 알린다. 수입량은 다음 달 중순에 공표돼 occurred_at(그달 1일)에서 45일쯤 뒤에 들어온다
ALERT_DAYS = 60


def judge_import(imp: DataFrame) -> DataFrame:
    """import_monthly(item_id, hs_code, ym, import_kg) → 급증인 달만 비교 수치와 함께 돌려준다."""
    cur = imp.select("item_id", "hs_code", "ym", "import_kg",
                     F.year("ym").alias("y"), F.month("ym").alias("m"))
    past = imp.select(F.col("hs_code").alias("p_hs"), F.year("ym").alias("p_y"), F.month("ym").alias("p_m"),
                      F.col("import_kg").alias("p_kg"))
    # 같은 HS 코드·같은 달, 1~5년 전 행을 붙인다
    j = cur.join(past, (F.col("hs_code") == F.col("p_hs")) & (F.col("m") == F.col("p_m"))
                 & F.col("p_y").between(F.col("y") - YEARS, F.col("y") - 1))
    s = j.groupBy("item_id", "hs_code", "ym", "import_kg").agg(
        F.count("p_kg").alias("n_years"),
        F.avg("p_kg").alias("avg_kg"),
        F.stddev_samp("p_kg").alias("std_kg"),   # 표본 표준편차 (n-1). 5개뿐이라 모집단 σ보다 조금 크게, 덜 민감하게 잡힌다
        F.max(F.when(F.col("p_y") == F.col("y") - 1, F.col("p_kg"))).alias("prev_kg"),
    ).where(F.col("n_years") == YEARS)
    s = s.withColumn("threshold_kg", F.col("avg_kg") + SIGMA * F.col("std_kg"))
    return s.where(
        (F.col("import_kg") >= F.col("threshold_kg"))
        & (F.col("import_kg") >= F.col("prev_kg") * YOY)
        & (F.col("import_kg") >= MIN_IMPORT_KG)
    )


def to_event(r, item_name: str) -> dict:
    """판정 결과 1행 → special_event 행. 수입은 지역 구분이 없어 sido = '전국'."""
    ym = r["ym"]
    yoy_pct = None if r["prev_kg"] == 0 else round((r["import_kg"] / r["prev_kg"] - 1) * 100, 1)
    return {
        "event_type": "IMPORT_SURGE",
        "item_id": r["item_id"],
        "sido": "전국",
        "sigungu": None,
        # 그달 1일 00:00(한국) → UTC. 공표는 다음 달 중순이지만, 사건이 일어난 때는 그달이다
        "occurred_at": datetime(ym.year, ym.month, 1, tzinfo=KST).astimezone(timezone.utc).replace(tzinfo=None),
        "title": f"{item_name} 수입량 급증 ({ym:%Y-%m})",
        "detail": json.dumps({
            "ym": f"{ym:%Y-%m}", "hs_code": r["hs_code"],
            "import_kg": int(r["import_kg"]), "prev_year_kg": int(r["prev_kg"]), "yoy_pct": yoy_pct,
            "avg_5y_kg": round(r["avg_kg"]), "std_5y_kg": round(r["std_kg"]), "threshold_kg": round(r["threshold_kg"]),
        }, ensure_ascii=False),
        "source_url": SOURCE_URL,
        "source_ref": f"{r['hs_code']}:{ym:%Y-%m}",   # HS 코드·달 하나에 사건 하나
    }


def judge_pest(ps: DataFrame) -> DataFrame:
    """pest_survey 행 → 증가로 판정된 행만 비교 수치와 함께 돌려준다 (주산지 거르기는 하지 않는다)."""
    key = ["ncpms_crop_code", "survey_type", "sigungu_code", "pest_code"]
    cur = ps.withColumn("y", F.year("survey_date")).withColumn("md", F.date_format("survey_date", "MM-dd"))
    # ② 같은 해 직전 조사 값. 그 시군에서 이 항목을 조사한 날만 이어 본다
    w = Window.partitionBy(*key, "y").orderBy("survey_date")
    cur = cur.withColumn("prev_value", F.lag("value").over(w)).where(F.col("prev_value").isNotNull())
    past = ps.select(*[F.col(k).alias("p_" + k) for k in key],
                     F.year("survey_date").alias("p_y"), F.date_format("survey_date", "MM-dd").alias("p_md"),
                     F.col("value").alias("p_value"))
    cond = [F.col(k) == F.col("p_" + k) for k in key] + [
        F.col("md") == F.col("p_md"), F.col("p_y").between(F.col("y") - YEARS, F.col("y") - 1)]
    j = cur.join(past, cond)
    cols = key + ["sido", "sigungu", "survey_date", "pest_name", "value", "prev_value"]
    s = j.groupBy(*cols).agg(F.count("p_value").alias("n_years"), F.avg("p_value").alias("avg_value"),
                             F.stddev_samp("p_value").alias("std_value")).where(F.col("n_years") >= PEST_MIN_YEARS)
    s = s.withColumn("threshold", F.col("avg_value") + SIGMA * F.col("std_value"))
    return s.where((F.col("value") > F.col("prev_value")) & (F.col("value") >= F.col("threshold")))


def sido_key(col):
    """시도 이름 → 주산지와 잇는 값 (SIDO_KEY에 없으면 그대로)"""
    expr = F.col(col)
    for name, k in SIDO_KEY.items():
        expr = F.when(F.col(col) == name, F.lit(k)).otherwise(expr)
    return expr


def in_producing_area(hits: DataFrame, items: DataFrame, areas: DataFrame) -> DataFrame:
    """판정 결과를 품목(item.ncpms_crop_code)에 붙이고, 그 품목의 주산지 시군만 남긴다. 시도는 주산지 표기로 바꾼다."""
    a = areas.select(F.col("item_id").alias("a_item_id"), F.col("sido").alias("a_sido"),
                     sido_key("sido").alias("a_sk"), F.col("sigungu").alias("a_sigungu"))
    h = hits.join(items.select("item_id", "ncpms_crop_code"), "ncpms_crop_code").withColumn("sk", sido_key("sido"))
    j = h.join(a, (h.item_id == a.a_item_id) & (h.sk == a.a_sk) & (h.sigungu == a.a_sigungu))
    return j.withColumn("sido", F.col("a_sido")).drop("sk", "a_item_id", "a_sido", "a_sk", "a_sigungu")


def to_pest_events(rows: list[dict], names: dict) -> list[dict]:
    """품목·시군·조사일 하나에 사건 하나. 걸린 항목은 detail.pests에 모은다."""
    groups = {}
    for r in sorted(rows, key=lambda r: (r["item_id"], r["sigungu_code"], r["survey_date"], r["pest_code"])):
        groups.setdefault((r["item_id"], r["sigungu_code"], r["survey_date"]), []).append(r)
    events = []
    for (item_id, sgg_code, d), rs in groups.items():
        r0 = rs[0]
        events.append({
            "event_type": "PEST_INCREASE",
            "item_id": item_id,
            "sido": r0["sido"],
            "sigungu": r0["sigungu"],
            "occurred_at": datetime(d.year, d.month, d.day, tzinfo=KST).astimezone(timezone.utc).replace(tzinfo=None),
            "title": f"{r0['sigungu']} {names[item_id]} 예찰 증가 ({d:%m-%d} 조사)"[:100],
            "detail": json.dumps({
                "survey_date": f"{d:%Y-%m-%d}", "survey_type": r0["survey_type"], "sigungu_code": sgg_code,
                "pests": [{
                    "pest_code": r["pest_code"], "pest_name": r["pest_name"],   # 이름 괄호 안이 값의 단위
                    "value": float(r["value"]), "prev_value": float(r["prev_value"]), "n_years": r["n_years"],
                    "avg_5y": round(float(r["avg_value"]), 3), "threshold": round(float(r["threshold"]), 3),
                } for r in rs],
            }, ensure_ascii=False),
            "source_url": PEST_SOURCE_URL,
            "source_ref": f"{item_id}:{sgg_code}:{d:%Y-%m-%d}",
        })
    return events


def run_pest_increase(spark: SparkSession, conn) -> tuple[int, int]:
    """(사건 수, 새로 만든 사건 수)"""
    items = read(spark, "item").where("ncpms_crop_code IS NOT NULL").select("item_id", "name", "ncpms_crop_code")
    names = {r.item_id: r.name for r in items.collect()}
    hits = in_producing_area(judge_pest(read(spark, "pest_survey")), items, read(spark, "item_producing_area"))
    events = to_pest_events([r.asDict() for r in hits.collect()], names)
    return len(events), save(conn, events)


def save(conn, events: list[dict]) -> int:
    """special_event에 넣고 새로 들어간 건수를 돌려준다. 이미 있는 사건은 UNIQUE 키에 걸려 건너뛴다."""
    if not events:
        return 0
    cols = list(events[0])
    sql = (f"INSERT IGNORE INTO special_event ({', '.join(cols)}) "
           f"VALUES ({', '.join(['%s'] * len(cols))})")
    with conn.cursor() as cur:
        return cur.executemany(sql, [tuple(e[c] for c in cols) for e in events])


def run_import_surge(spark: SparkSession, conn) -> tuple[int, int]:
    """(판정된 달 수, 새로 만든 사건 수)"""
    names = {r.item_id: r.name for r in read(spark, "item").select("item_id", "name").collect()}
    hits = judge_import(read(spark, "import_monthly")).orderBy("hs_code", "ym").collect()
    events = [to_event(r.asDict(), names[r.item_id]) for r in hits]
    for e in events:
        print(" ", e["title"], e["detail"])
    return len(events), save(conn, events)


def create_alerts(conn, since: datetime) -> int:
    """since(UTC, naive) 이후 사건 → alert. 새로 만든 알림 수를 돌려준다.
    수입량 급증: 관심 품목 회원 모두. 예찰 증가: 관심 품목 회원 중 프로필 시도·시군이 사건 시군과 같은 회원."""
    head = ("INSERT IGNORE INTO alert (user_id, special_event_id, created_at) "
            "SELECT u.user_id, e.id, UTC_TIMESTAMP(6) FROM special_event e "
            "JOIN user_interest_item u ON u.item_id = e.item_id ")
    imports = head + "WHERE e.event_type = 'IMPORT_SURGE' AND e.occurred_at >= %s"
    pests = head + ("JOIN user_profile p ON p.user_id = u.user_id AND p.sido = e.sido AND p.sigungu = e.sigungu "
                    "WHERE e.event_type = 'PEST_INCREASE' AND e.occurred_at >= %s")
    with conn.cursor() as cur:
        return cur.execute(imports, (since,)) + cur.execute(pests, (since,))


def main():
    spark = session("alert_rules")
    conn = connect()
    try:
        hits, new = run_import_surge(spark, conn)
        print(f"수입량 급증: 기준을 넘은 달 {hits}개, 새 사건 {new}건")
        events, new = run_pest_increase(spark, conn)
        print(f"예찰 증가: 사건 {events}개(품목·주산지 시군·조사일), 새 사건 {new}건")
        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=ALERT_DAYS)
        print(f"회원 알림: {since:%Y-%m-%d %H:%M} UTC 이후 사건으로 새 알림 {create_alerts(conn, since)}건")
    finally:
        conn.close()
        spark.stop()


if __name__ == "__main__":
    main()
