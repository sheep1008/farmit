"""예측 작업 전 점검: 지난주까지 가격·날씨·달력·생산량이 빠짐없이 있는가 (K09, REQ-COL-003).

    docker compose -f infra/docker-compose.yml --profile collect run --rm collectors python -m weather.check
    ... python -m weather.check --until 2026-11-08 --since 2026-01-01
    ... python -m weather.check --only price holiday     # 일부만 (주간 예측 DAG, K19)

--only로 쓰는 데이터만 고른다. 운영 모델 v4(K30 공통 피처)는 가격·명절만 쓰고 날씨·생산량은 쓰지 않는다.
주간 예측 DAG(batch/dags/forecast.py)는 예측 앞에서 price·holiday를, 과거 사례(날씨 사건) 앞에서 weather를 본다.

점검 (모두 통과하면 종료 코드 0, 하나라도 빠지면 1 → Airflow 작업이 실패로 멈춘다):
- settle_price (price): 예측 품목(item.is_forecast)마다 until이 끝인 한 주(월~일)에 정산 행이 1건 이상 있다.
  시장 몇 곳이 빠진 것은 괜찮다 (예측이 그 시장만 건너뛰고 경고한다). 한 주가 통째로 비면 예측 기준 주가 밀린다.
- weather_daily: 주산지 관측소마다 since~until 모든 날짜에 행이 있다. 행만 있으면 되고 값이 NULL인 것은 괜찮다
  (관측값이 빠진 날은 기상청 원본에도 없다, erd.md 2.6).
- holiday: since~(until + 4주) 사이의 모든 해에 공휴일이 1건 이상 있다. 예측은 최대 4주 뒤를 보므로 연말에는 다음 해가 필요하다.
- crop_production: 예측 품목(item.is_forecast)마다 (until의 연도 - 2)년 값까지 있다.
  KOSIS는 Y년 값을 Y+1년 10~11월에 공표하므로, 공표 직전에도 확실히 있어야 하는 해는 2년 전이다.
"""
import argparse
import sys
from datetime import date, datetime, timedelta

from common import db
from common.collect_log import KST

SINCE = date(2018, 1, 1)
HORIZON_DAYS = 28  # 예측 최대 4주 뒤 (docs/ml.md)


def last_sunday(today):
    """지난주 일요일. 예측 기준 주(월~일)의 마지막 날이다. 오늘이 일요일이면 그 전 주 일요일."""
    return today - timedelta(days=today.weekday() + 1)


def ranges(days):
    """정렬된 날짜 목록을 이어진 구간 문자열로 줄인다. [11/1, 11/2, 11/5] → '2026-11-01~2026-11-02, 2026-11-05'"""
    out, start, prev = [], None, None
    for d in days:
        if prev and d == prev + timedelta(days=1):
            prev = d
            continue
        if start:
            out.append(f"{start}~{prev}" if start != prev else f"{start}")
        start = prev = d
    if start:
        out.append(f"{start}~{prev}" if start != prev else f"{start}")
    return ", ".join(out)


def query(conn, sql, args=()):
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def check_weather(conn, since, until):
    stations = [r[0] for r in query(conn, "SELECT DISTINCT station_id FROM item_producing_area ORDER BY 1")]
    if not stations:
        return ["weather_daily: item_producing_area에 연결된 관측소가 없다"]
    have = {}
    for stn, d in query(conn, "SELECT station_id, obs_date FROM weather_daily WHERE obs_date BETWEEN %s AND %s",
                        (since, until)):
        have.setdefault(stn, set()).add(d)
    all_days = [since + timedelta(days=i) for i in range((until - since).days + 1)]
    problems = []
    for stn in stations:
        missing = [d for d in all_days if d not in have.get(stn, set())]
        if missing:
            problems.append(f"weather_daily: 관측소 {stn} {len(missing)}일 빠짐 ({ranges(missing)})")
    return problems


def check_holiday(conn, since, until):
    years = range(since.year, (until + timedelta(days=HORIZON_DAYS)).year + 1)
    have = {r[0] for r in query(conn, "SELECT DISTINCT YEAR(holiday_date) FROM holiday")}
    return [f"holiday: {y}년 공휴일이 없다" for y in years if y not in have]


def check_price(conn, until):
    start = until - timedelta(days=6)
    rows = query(conn, "SELECT i.name, COUNT(s.id) FROM item i LEFT JOIN settle_price s "
                       "ON s.item_id = i.item_id AND s.trade_date BETWEEN %s AND %s "
                       "WHERE i.is_forecast GROUP BY i.item_id, i.name", (start, until))
    return [f"settle_price: {name} {start}~{until} 정산이 없다" for name, n in rows if not n]


def check_production(conn, until):
    need = until.year - 2
    rows = query(conn, "SELECT i.name, MAX(c.year) FROM item i LEFT JOIN crop_production c USING (item_id) "
                       "WHERE i.is_forecast GROUP BY i.item_id, i.name")
    return [f"crop_production: {name} {need}년 값이 없다 (마지막 {last or '없음'})"
            for name, last in rows if not last or last < need]


CHECKS = {
    "price": lambda conn, since, until: check_price(conn, until),
    "weather": check_weather,
    "holiday": check_holiday,
    "production": lambda conn, since, until: check_production(conn, until),
}


def check(conn, since, until, only=tuple(CHECKS)):
    """빠진 것 목록. 비어 있으면 통과. only: 볼 점검 이름 (CHECKS의 키)."""
    return [msg for name in only for msg in CHECKS[name](conn, since, until)]


def main(argv=None):
    p = argparse.ArgumentParser(description="예측 전 날씨·달력·생산량 누락 점검")
    p.add_argument("--since", type=date.fromisoformat, default=SINCE)
    p.add_argument("--until", type=date.fromisoformat, help="기본: 지난주 일요일 (한국 날짜)")
    p.add_argument("--only", nargs="+", choices=list(CHECKS), default=list(CHECKS), help="볼 점검 (기본: 전부)")
    a = p.parse_args(argv)
    until = a.until or last_sunday(datetime.now(KST).date())
    conn = db.connect()
    try:
        problems = check(conn, a.since, until, a.only)
    finally:
        conn.close()
    print(f"점검 기간 {a.since} ~ {until}, 점검 {' '.join(a.only)}")
    for msg in problems:
        print("  빠짐  " + msg)
    print("통과" if not problems else f"실패 {len(problems)}건")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
