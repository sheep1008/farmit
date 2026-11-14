"""한국천문연구원 특일 정보(공휴일) 수집 → holiday (K09, REQ-COL-003).

solMonth 없이 solYear만 주면 한 해 공휴일이 한 번에 온다 (2026년 22건, 2026-11-14 확인). 그래서 한 해 = 호출 1건.
collect_log에는 해마다 한 줄 남고 target_date는 그해 1월 1일이다.

    # 기본: 올해와 내년 (내년 공휴일은 보통 전년 하반기에 공표된다. 아직 없으면 0건)
    docker compose -f infra/docker-compose.yml --profile collect run --rm collectors python -m weather.holiday
    # 과거 적재
    ... python -m weather.holiday --from-year 2018
"""
import argparse
from datetime import date, datetime

from common import datagokr
from common.collect_log import KST, collect_run
from common.db import upsert

URL = "https://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getRestDeInfo"
SOURCE = "holiday"
DAILY_LIMIT = 10000  # data.go.kr 개발계정 기본 한도 (asos와 같은 가정)


def to_rows(items):
    """isHoliday=Y인 날만 holiday 행으로. 같은 날 공휴일이 둘이면 이름을 '·'로 합친다.

    holiday_date가 PK라 그대로 넣으면 한쪽 이름이 덮어써진다 (예: 2025-05-05 어린이날·부처님오신날).
    """
    names = {}
    for i in items:
        if i.get("isHoliday") != "Y":
            continue
        d = str(i["locdate"])  # 숫자(20260924)로 온다
        day = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        names.setdefault(day, [])
        if i["dateName"] not in names[day]:
            names[day].append(i["dateName"])
    return [{"holiday_date": day, "name": "·".join(n)[:30]} for day, n in sorted(names.items())]


def collect(year, conn=None):
    @collect_run(SOURCE, daily_limit=DAILY_LIMIT)
    def run_(run):
        text = run.get(URL, {"_type": "json", "solYear": year, "numOfRows": 100},
                       key=("ServiceKey", datagokr.service_key()))  # 이 API만 대문자 S
        run.rows += upsert(run.conn, "holiday", to_rows(datagokr.items(text)), ["name"])
    return run_(date(year, 1, 1), conn=conn)


def main(argv=None):
    this_year = datetime.now(KST).year
    p = argparse.ArgumentParser(description="특일 정보(공휴일) 수집 → holiday")
    p.add_argument("--from-year", type=int, default=this_year)
    p.add_argument("--to-year", type=int, default=this_year + 1)
    a = p.parse_args(argv)
    for y in range(a.from_year, a.to_year + 1):
        print(f"{y}: {collect(y).rows}행")


if __name__ == "__main__":
    main()
