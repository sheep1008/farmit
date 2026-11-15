"""관세청 품목별 국가별 수출입실적 수집 → import_monthly (K16, REQ-COL-005).

item.hs_code가 있는 품목만 돈다 (품목·코드를 코드에 쓰지 않는다). 조회 기간이 1년 이내라 품목마다 한 해 = 호출 1건.
응답은 XML이고 나라별로 행이 오므로 달마다 더한다 (docs/data-sources.md 7절).
거래가 없는 달은 행이 오지 않는다. 같은 달 평균에서 빠지지 않게 0으로 저장하되,
아직 공표되지 않은 달까지 0으로 채우지 않도록 이번 실행에서 어느 품목이든 값이 온 마지막 달까지만 채운다.

    # 기본: 작년과 올해 (공표 뒤 수정분도 다시 받는다)
    docker compose -f infra/docker-compose.yml --profile collect run --rm collectors python -m imports.customs
    # 과거 적재 (알림 기준이 최근 5년 같은 달이라 그보다 길게)
    ... python -m imports.customs --from-year 2018
"""
import argparse
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from common import datagokr
from common.collect_log import KST, collect_run
from common.db import upsert

URL = "https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList"
SOURCE = "customs"
DAILY_LIMIT = 10000  # data.go.kr 개발계정 기본 한도 (asos·holiday와 같은 가정)
TOTAL = "총계"       # 조회 기간 전체 합계 행. 달별 값이 아니므로 뺀다


def hs_items(conn):
    """수집 대상 [(item_id, hs_code)]."""
    with conn.cursor() as cur:
        cur.execute("SELECT item_id, hs_code FROM item WHERE hs_code IS NOT NULL AND hs_code <> '' ORDER BY item_id")
        return list(cur.fetchall())


def parse(text):
    """XML 응답 → 행 목록(dict). 결과 코드가 00이 아니면 ApiError (예: 99 조회 기간 1년 초과)."""
    root = ET.fromstring(text)
    code = root.findtext(".//resultCode")
    if code != "00":
        raise datagokr.ApiError(f"resultCode {code} {root.findtext('.//resultMsg')}")
    return [{c.tag: (c.text or "").strip() for c in it} for it in root.iter("item")]


def monthly(rows):
    """나라별 행 → {월(1~12): (수입 kg, 수입 USD)}. 6자리로 조회하면 아래 10자리 코드들도 함께 더해진다."""
    sums = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for r in rows:
        if r["year"] == TOTAL:
            continue
        month = int(r["year"].split(".")[1])  # '2025.03'
        sums[month][0] += Decimal(r["impWgt"])
        sums[month][1] += Decimal(r["impDlr"])
    return {m: (int(kg), int(usd)) for m, (kg, usd) in sums.items()}


def to_rows(item_id, hs_code, year, by_month, last_month):
    """1월~last_month를 모두 행으로. 값이 없는 달은 0."""
    return [{"item_id": item_id, "hs_code": hs_code, "ym": date(year, m, 1),
             "import_kg": by_month.get(m, (0, 0))[0], "import_usd": by_month.get(m, (0, 0))[1]}
            for m in range(1, last_month + 1)]


def collect(year, conn=None):
    now = datetime.now(KST)
    end = f"{year}{now.month:02d}" if year == now.year else f"{year}12"

    @collect_run(SOURCE, daily_limit=DAILY_LIMIT)
    def run_(run):
        fetched = []
        for item_id, hs in hs_items(run.conn):
            text = run.get(URL, {"strtYymm": f"{year}01", "endYymm": end, "hsSgn": hs},
                           key=("serviceKey", datagokr.service_key()))
            fetched.append((item_id, hs, monthly(parse(text))))
        # 어느 품목이든 값이 온 마지막 달 = 공표된 마지막 달로 본다
        run.last_month = max((max(m) for _, _, m in fetched if m), default=0)
        rows = [r for item_id, hs, m in fetched for r in to_rows(item_id, hs, year, m, run.last_month)]
        run.rows += upsert(run.conn, "import_monthly", rows, ["item_id", "import_kg", "import_usd"])
    return run_(date(year, 1, 1), conn=conn)


def main(argv=None):
    this_year = datetime.now(KST).year
    p = argparse.ArgumentParser(description="관세청 월별 수입량 수집 → import_monthly")
    p.add_argument("--from-year", type=int, default=this_year - 1)
    p.add_argument("--to-year", type=int, default=this_year)
    a = p.parse_args(argv)
    for y in range(a.from_year, a.to_year + 1):
        r = collect(y)
        print(f"{y}: {r.rows}행 (1~{r.last_month}월), 호출 {r.api_calls}건")


if __name__ == "__main__":
    main()
