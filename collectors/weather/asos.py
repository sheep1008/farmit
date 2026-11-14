"""기상청 ASOS 일자료 수집 → weather_daily (K09, REQ-COL-003).

수집 대상은 item_producing_area(품목 주산지)에 연결된 관측소뿐이다. 관측소를 코드에 적지 않는다.
관측소 하나 · 한 해(최대 366행)를 한 번에 받는다 (numOfRows 999). 같은 기간을 다시 돌려도 UPSERT라 행이 늘지 않는다.

    # 레포 루트에서. 기본은 어제 하루 (ASOS는 D-1까지 제공)
    docker compose -f infra/docker-compose.yml --profile collect run --rm collectors python -m weather.asos
    # 기간 지정
    ... python -m weather.asos --start 2026-11-01 --end 2026-11-13
    # 과거 적재: 2018-01-01부터 어제까지 한 해씩 (collect_log에 해마다 한 줄)
    ... python -m weather.asos --backfill
"""
import argparse
from datetime import date, datetime, timedelta

from common import datagokr
from common.collect_log import KST, collect_run
from common.db import upsert
from common.http import HttpError

URL = "https://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"
SOURCE = "asos"
# data.go.kr 개발계정 기본 한도. 활용신청 현황에서 확인한 값으로 바꾼다 (docs/data-sources.md 6절)
DAILY_LIMIT = 10000
BACKFILL_FROM = date(2018, 1, 1)  # aT 정산정보 시작과 맞춘다
# weather_daily 컬럼 ← 응답 필드. 숫자도 문자열로 오고 관측이 없으면 ""다
FIELDS = {"avg_temp": "avgTa", "max_temp": "maxTa", "min_temp": "minTa", "rain_mm": "sumRn", "humidity": "avgRhm"}


def yesterday():
    """한국 날짜 기준 어제. 관측일(obs_date)은 한국 달력 날짜다."""
    return datetime.now(KST).date() - timedelta(days=1)


def stations(conn):
    """주산지에 연결된 관측소 번호 목록."""
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT station_id FROM item_producing_area ORDER BY station_id")
        return [r[0] for r in cur.fetchall()]


def year_chunks(start, end):
    """[start, end]를 해 단위로 자른다. 한 요청이 한 페이지(999행) 안에 들어가게 하려는 것이다."""
    while start <= end:
        last = min(date(start.year, 12, 31), end)
        yield start, last
        start = last + timedelta(days=1)


def to_row(item):
    """응답 한 행 → weather_daily 한 행. 빈 값은 0이 아니라 NULL로 둔다 (erd.md 3절)."""
    row = {"station_id": int(item["stnId"]), "obs_date": item["tm"]}
    for col, field in FIELDS.items():
        v = (item.get(field) or "").strip()
        row[col] = v or None
    return row


def collect(start, end, conn=None):
    """start~end(포함) 일자료를 주산지 관측소마다 받아 저장한다. collect_log에는 한 줄, target_date는 end."""
    @collect_run(SOURCE, daily_limit=DAILY_LIMIT)
    def run_(run):
        stns = stations(run.conn)
        if not stns:
            raise RuntimeError("item_producing_area에 연결된 관측소가 없다 (주산지 데이터를 먼저 넣어야 한다)")
        for stn in stns:
            for s, e in year_chunks(start, end):
                try:
                    text = run.get(URL, {
                        "dataType": "JSON", "pageNo": 1, "numOfRows": 999, "dataCd": "ASOS", "dateCd": "DAY",
                        "startDt": f"{s:%Y%m%d}", "endDt": f"{e:%Y%m%d}", "stnIds": stn,
                    }, key=("serviceKey", datagokr.service_key()))
                    rows = [to_row(i) for i in datagokr.items(text)]
                except (datagokr.ApiError, HttpError) as ex:
                    # 이 관측소·기간만 건너뛰고 나머지는 계속 받는다 → collect_log 상태 partial
                    # LimitReached는 잡지 않는다: 한도에 닿으면 전체를 멈춘다 (status fail)
                    run.errors.append(f"관측소 {stn} {s}~{e}: {ex}")
                    continue
                run.rows += upsert(run.conn, "weather_daily", rows, list(FIELDS))
    return run_(end, conn=conn)


def main(argv=None):
    p = argparse.ArgumentParser(description="ASOS 일자료 수집 → weather_daily")
    p.add_argument("--start", type=date.fromisoformat)
    p.add_argument("--end", type=date.fromisoformat)
    p.add_argument("--backfill", action="store_true", help=f"{BACKFILL_FROM}부터 어제까지 한 해씩")
    a = p.parse_args(argv)
    end = a.end or yesterday()
    if a.backfill:
        ranges = list(year_chunks(a.start or BACKFILL_FROM, end))
    else:
        ranges = [(a.start or end, end)]
    for s, e in ranges:
        run = collect(s, e)
        print(f"{s}~{e}: {run.rows}행, 호출 {run.api_calls}건" + (f", 실패 {len(run.errors)}건" if run.errors else ""))
        for msg in run.errors:
            print("  " + msg)


if __name__ == "__main__":
    main()
