"""NCPMS 병해충 예찰 결과 수집 → pest_survey (K16, REQ-COL-005).

item.ncpms_crop_code에 있는 작물만 돈다. 작물마다 collect_log 한 줄 (target_date = 오늘, 한국 날짜).
NCPMS는 하루 한도가 공개되지 않아(REQ-NFR-009) 한도로 멈추지 않고, 호출 수를 collect_log.api_calls에 남긴다.

한 작물을 받는 순서 (docs/data-sources.md 8절):
  1. SVC51 조사 회차 목록 (한 번에 최대 50건이라 페이지를 돈다)
  2. 받을 회차 = pest_survey에 아직 없는 회차 + 최근 REFRESH_DAYS일 안의 회차 (늦게 입력되는 시도가 있어 다시 받는다)
  3. 회차마다 SVC52(시도별 결과)로 조사한 시도를 알아내고, 시도마다 SVC53(시군별 결과)를 받아 저장한다

    docker compose -f infra/docker-compose.yml --profile collect run --rm collectors python -m pests.ncpms
"""
import json
import os
import urllib.parse
from datetime import date, datetime, timedelta

from common.collect_log import KST, collect_run
from common.db import connect, upsert

URL = "https://ncpms.rda.go.kr/npmsAPI/service"
SOURCE = "ncpms_survey"
PAGE = 50            # SVC51 displayCount 최대값
REFRESH_DAYS = 30
COLUMNS = ["ncpms_crop_code", "survey_type", "survey_year", "survey_round", "survey_date",
           "sido", "sigungu", "pest_name", "value"]


class NcpmsError(Exception):
    """NCPMS가 HTTP 200에 {"errorCode": "ERR_...", "errorMsg": ...}를 돌려줬다."""


def api_key():
    return urllib.parse.quote(os.environ["NCPMS_API_KEY"].strip(), safe="")


def call(run, **params):
    text = run.get(URL, {"serviceType": "AA003", **params}, key=("apiKey", api_key()))  # AA003 = JSON
    s = json.loads(text)["service"]
    if "errorCode" in s:
        raise NcpmsError(f"{s['errorCode']} {s.get('errorMsg', '').splitlines()[0]}")
    return s


def crop_codes(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT ncpms_crop_code FROM item "
                    "WHERE ncpms_crop_code IS NOT NULL AND ncpms_crop_code <> '' ORDER BY 1")
        return [r[0] for r in cur.fetchall()]


def rounds(run, crop):
    """SVC51 → 이 작물의 조사 회차 전부 (최신순)."""
    out, start = [], 1
    while True:
        s = call(run, serviceCode="SVC51", searchKncrCode=crop, displayCount=PAGE, startPoint=start)
        out += s.get("list", [])
        start += PAGE
        if start > int(s.get("totalCount", 0)):
            return out


def to_date(yyyymmdd):
    return date(int(yyyymmdd[:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:]))


def to_wanted(all_rounds, have, today):
    """받을 회차: DB에 없는 회차 + 조사 기준일이 최근 REFRESH_DAYS일 안인 회차."""
    since = today - timedelta(days=REFRESH_DAYS)
    return [r for r in all_rounds if r["insectKey"] not in have or to_date(r["inputStdrDatetm"]) >= since]


def to_rows(rnd, sido, items):
    """SVC53 structList → pest_survey 행 목록.

    그 시군에서 조사하지 않은 항목은 inqireValue 키가 아예 없다 (0과 다르다) → 건너뛴다.
    sigunguCode는 문자열('4711')이나 숫자(4183)로 온다 → 문자열로 맞춘다.
    """
    return [{"ncpms_crop_code": rnd["kncrCode"], "insect_key": rnd["insectKey"], "survey_type": rnd["examinSpchcknNm"],
             "survey_year": int(rnd["examinYear"]), "survey_round": int(rnd["examinTmrd"]),
             "survey_date": to_date(rnd["inputStdrDatetm"]), "sido": sido, "sigungu": i["sigunguNm"],
             "sigungu_code": str(i["sigunguCode"]), "pest_code": i["inqireCnClCode"], "pest_name": i["dbyhsNm"],
             "value": i["inqireValue"]} for i in items if i.get("inqireValue") is not None]


def collect_round(run, rnd):
    sidos = {(i["sidoCode"], i["sidoNm"]) for i in call(run, serviceCode="SVC52", insectKey=rnd["insectKey"])
             .get("structList", [])}
    for code, name in sorted(sidos):
        items = call(run, serviceCode="SVC53", insectKey=rnd["insectKey"], sidoCode=code).get("structList", [])
        run.rows += upsert(run.conn, "pest_survey", to_rows(rnd, name, items), COLUMNS)


def collect(crop, conn=None):
    today = datetime.now(KST).date()

    @collect_run(SOURCE)
    def run_(run):
        with run.conn.cursor() as cur:
            cur.execute("SELECT DISTINCT insect_key FROM pest_survey WHERE ncpms_crop_code = %s", (crop,))
            have = {r[0] for r in cur.fetchall()}
        run.wanted = to_wanted(rounds(run, crop), have, today)
        for rnd in run.wanted:
            try:
                collect_round(run, rnd)
            except NcpmsError as e:  # 한 회차가 실패해도 나머지는 받는다 (partial)
                run.errors.append(f"{crop} {rnd['insectKey']}: {e}")
    return run_(today, conn=conn)


def main():
    conn = connect()
    try:
        crops = crop_codes(conn)
    finally:
        conn.close()
    for crop in crops:
        r = collect(crop)
        print(f"{crop}: 회차 {len(r.wanted)}개, {r.rows}행, 호출 {r.api_calls}건, 실패 {len(r.errors)}건")


if __name__ == "__main__":
    main()
