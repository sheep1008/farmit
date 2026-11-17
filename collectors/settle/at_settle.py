"""aT 정산정보 수집 → settle_price (Y15, REQ-COL-001).

한 행 = 날짜·시장·법인·품목·등급·포장… 묶음의 합계라서, (날짜·시장·품목·등급)으로 다시 묶어 원/kg로 저장한다
(계산식은 docs/data-sources.md 2절). 수집 대상 시장은 market 테이블의 is_collect·is_reference, 품목은 item 테이블이다 (코드에 적지 않음).
시장 하나를 한 달씩 끊어 받고(호출 수는 행 수에 비례), 같은 기간을 다시 돌려도 UPSERT라 행이 늘지 않는다.

    # 기본: 어제 하루 (당일분은 다음 날 반영된다)
    docker compose -f infra/docker-compose.yml --profile collect run --rm collectors python -m settle.at_settle
    # 기간 지정
    ... python -m settle.at_settle --start 2026-11-01 --end 2026-11-13
    # 과거 적재: 2018-01-02부터 어제까지. 한도(10,000건)에 닿으면 멈추니 --start로 이어서 받는다
    ... python -m settle.at_settle --backfill

전국 모드(--national, K31): 예측 품목(item.is_forecast)만 market 테이블에 등록된 전국 시장으로 받는다.
가격 예측의 전국 가격·물량 피처(docs/ml.md 7절)용이다. 수집 대상 시장(is_collect)은 실시간 경매·화면이 같이 쓰므로 건드리지 않는다.
품목 하나를 한 달씩 전국 시장 범위로 받아(사과 한 달 3~9건) 응답의 시장 코드별로 묶는다. 등록되지 않은 시장은 건너뛴다.
같은 API라 하루 한도를 같이 쓰도록 collect_log 출처도 at_settle로 같다.

    ... python -m settle.at_settle --national                       # 어제 하루
    ... python -m settle.at_settle --national --backfill            # 2018-01-02부터 (사과 651건)
    ... python -m settle.at_settle --national --backfill --item 0501 --item 0502   # 새로 켠 예측 품목만 (K28)

전 품목 전국 모드(--all-items, K32): 품목 조건 없이 전국 시장 범위로 하루씩 받는다 (하루 원본 약 3.5만 행 = 4건).
전국 시장 "지금 팔면" 실수령액(REQ-REC-007)용이다. 수집 시장 5곳·예측 품목도 이 응답에 다 들어 있어서
매일 수집(collect_daily)은 이 모드 하나로 받는다. item 테이블에 없는 품목은 건너뛴다.

    ... python -m settle.at_settle --all-items                      # 어제 하루
    ... python -m settle.at_settle --all-items --start 2026-09-21   # 최근 8주 (약 220건)
"""
import argparse
import json
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal as D, InvalidOperation

from common import datagokr
from common.collect_log import KST, LimitReached, collect_run
from common.db import upsert
from common.http import HttpError, mask

URL = "https://apis.data.go.kr/B552845/katSale/trades"
SOURCE = "at_settle"
DAILY_LIMIT = 10000  # aT 정산 하루 한도 (실시간 경매와 별도)
PAGE = 10000
BACKFILL_FROM = date(2018, 1, 2)  # 정산정보가 존재하는 첫 날
ONE = D("0.1")
OK_CODES = {"0", "00"}  # aT는 0, 다른 data.go.kr API는 00 (docs/data-sources.md 1절)


def yesterday():
    return datetime.now(KST).date() - timedelta(days=1)


def month_chunks(start, end):
    """[start, end]를 달 단위로 자른다. 실패했을 때 다시 받는 양을 줄이려는 것이다."""
    while start <= end:
        nxt = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
        last = min(nxt - timedelta(days=1), end)
        yield start, last
        start = last + timedelta(days=1)


def parse(text):
    """응답 본문 → (행 목록, totalCount). 행이 1건이면 객체로 오므로 리스트로 감싼다."""
    try:
        resp = json.loads(text).get("response", {})
    except (ValueError, AttributeError):
        raise datagokr.ApiError(f"JSON이 아닌 응답: {mask(text[:200])}") from None
    code = str(resp.get("header", {}).get("resultCode", "0"))
    if code == datagokr.NO_DATA:
        return [], 0
    if code not in OK_CODES:   # 오류가 JSON으로 오면서 body가 비어 있어도 0건 성공으로 보지 않는다
        raise datagokr.ApiError(f"resultCode {code} {resp['header'].get('resultMsg')}")
    body = resp.get("body")
    if body is None:
        raise datagokr.ApiError(f"body가 없는 응답: {mask(text[:200])}")
    box = body.get("items") or {}
    rows = box.get("item", []) if isinstance(box, dict) else box
    rows = [rows] if isinstance(rows, dict) else rows
    try:
        return rows, int(body.get("totalCount") or 0)
    except ValueError:
        raise datagokr.ApiError(f"totalCount가 숫자가 아님: {body.get('totalCount')}") from None


class Agg:
    """페이지마다 들어오는 원본 행을 (날짜, 시장, 품목, 등급)별 합계로 모은다. 원본 전체를 메모리에 두지 않는다.

    market_id를 주면 모든 행을 그 시장으로 본다 (시장 하나씩 받는 기본 모드).
    None이면 행의 whsl_mrkt_cd를 쓰고, markets(등록된 시장 코드)에 없는 시장은 건너뛴다 (전국 모드).
    """

    def __init__(self, market_id, item_ids, start=None, end=None, markets=None):
        self.market_id = market_id
        self.markets = markets
        self.start, self.end = start, end   # 요청한 기간. 밖의 날짜가 오면 건너뛴다
        self.item_ids = item_ids      # {at_code: item_id}
        self.groups = {}              # key → [총금액, 총물량, 최저(kg당), 최고(kg당)]
        self.skipped = Counter()

    def add(self, r):
        market = self.market_id or r.get("whsl_mrkt_cd")
        if self.markets is not None and market not in self.markets:
            self.skipped["시장_없음"] += 1   # settle_price.market_id가 FK라 등록되지 않은 시장은 저장할 수 없다
            return
        item_id = self.item_ids.get(f"{r.get('gds_lclsf_cd')}{r.get('gds_mclsf_cd')}")
        if item_id is None:
            self.skipped["item_없음"] += 1
            return
        if r.get("unit_nm") != "kg":   # 환산하지 않고 건너뛴다 (원본은 aT에 남아 있다)
            self.skipped["kg_아님"] += 1
            return
        try:
            day = date.fromisoformat(r["trd_clcln_ymd"])
            if self.start and not self.start <= day <= self.end:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            self.skipped["날짜_오류"] += 1
            return
        try:
            qty, tot, unit = D(r["unit_tot_qty"]), D(r["totprc"]), D(r["unit_qty"])
            low, high = D(r["lwprc"]), D(r["hgprc"])
        except (KeyError, TypeError, InvalidOperation):
            self.skipped["값_오류"] += 1
            return
        if qty <= 0 or tot <= 0 or unit <= 0:
            self.skipped["물량·금액_0이하"] += 1
            return
        grade = (r.get("grd_nm") or "").strip()[:10] or "."
        for g in (grade, "ALL"):
            key = (r["trd_clcln_ymd"], market, item_id, g)
            a = self.groups.setdefault(key, [D(0), D(0), None, None])
            a[0] += tot
            a[1] += qty
            if low > 0:
                a[2] = low / unit if a[2] is None else min(a[2], low / unit)
            if high > 0:
                a[3] = high / unit if a[3] is None else max(a[3], high / unit)

    def rows(self):
        out = []
        for (day, market, item_id, grade), (tot, qty, low, high) in sorted(self.groups.items()):
            avg = (tot / qty).quantize(ONE)
            out.append({"trade_date": day, "market_id": market, "item_id": item_id, "grade": grade,
                        "avg_price": avg, "min_price": (low if low is not None else avg).quantize(ONE),
                        "max_price": (high if high is not None else avg).quantize(ONE),
                        "volume_kg": qty.quantize(ONE)})
        return out


def targets(conn):
    """(수집 시장 코드 목록, {at_code: item_id})."""
    with conn.cursor() as cur:
        cur.execute("SELECT market_id FROM market WHERE is_collect = 1 OR is_reference = 1 ORDER BY market_id")
        markets = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT at_code, item_id FROM item")
        items = {r[0]: r[1] for r in cur.fetchall()}
    return markets, items


def national_targets(conn):
    """전국 모드: (등록된 전체 시장 코드 집합, 예측 품목 {at_code: item_id})."""
    with conn.cursor() as cur:
        cur.execute("SELECT market_id FROM market")
        markets = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT at_code, item_id FROM item WHERE is_forecast = 1 ORDER BY at_code")
        items = {r[0]: r[1] for r in cur.fetchall()}
    return markets, items


def fetch_into(run, agg, cond, label, s, e):
    """cond 조건으로 s~e 정산을 모든 페이지 받아 agg에 넣고 저장한다.

    API·HTTP 오류는 이 묶음만 건너뛰고(아무것도 쓰지 않음) partial로 남긴다. 한도에 닿으면 이어 받을 날짜를 알려 주고 멈춘다.
    """
    try:
        page, seen = 1, 0
        while True:
            text = run.get(URL, {
                "returnType": "json", "pageNo": page, "numOfRows": PAGE,
                "cond[trd_clcln_ymd::GTE]": s.isoformat(), "cond[trd_clcln_ymd::LTE]": e.isoformat(), **cond,
            }, key=("serviceKey", datagokr.service_key()))
            rows, total = parse(text)
            for r in rows:
                agg.add(r)
            seen += len(rows)
            if not rows or seen >= total:
                break
            page += 1
    except (datagokr.ApiError, HttpError) as ex:
        run.errors.append(f"{label} {s}~{e}: {ex}")
        return
    except LimitReached as ex:
        raise LimitReached(f"{ex}. {label} {s}~{e}에서 멈춤 → 내일 --start {s}로 이어 받는다") from None
    run.skipped += agg.skipped
    run.rows += upsert(run.conn, "settle_price", agg.rows(), ["avg_price", "min_price", "max_price", "volume_kg"])


def collect(start, end, conn=None):
    """start~end(포함) 정산을 수집 시장마다 받아 저장한다. collect_log에는 한 줄, target_date는 end."""
    @collect_run(SOURCE, daily_limit=DAILY_LIMIT)
    def run_(run):
        markets, item_ids = targets(run.conn)
        if not markets or not item_ids:
            raise RuntimeError("market(is_collect·is_reference)이나 item이 비어 있다 (초기 데이터를 먼저 넣어야 한다)")
        run.skipped = Counter()
        # 달이 바깥, 시장이 안쪽: 한도에 걸려 멈춰도 "그 달 앞"은 모든 시장이 끝나 있어 --start로 빈 구간 없이 이어 받는다
        for s, e in month_chunks(start, end):
            for m in markets:
                fetch_into(run, Agg(m, item_ids, s, e), {"cond[whsl_mrkt_cd::EQ]": m},   # 시장 조건이 없으면 0건이 온다
                           f"시장 {m}", s, e)
    return run_(end, conn=conn)


def collect_national(start, end, conn=None, only=None):
    """전국 모드: 예측 품목을 등록된 전국 시장으로 받아 저장한다. 달이 바깥, 품목이 안쪽 (이어 받기는 collect와 같다).

    only(aT 코드 목록)를 주면 예측 품목 중 그 품목만 받는다. 새로 켠 품목의 과거 적재에서 이미 받은 품목을 다시 받지 않으려는 것이다.
    """
    @collect_run(SOURCE, daily_limit=DAILY_LIMIT)
    def run_(run):
        markets, items = national_targets(run.conn)
        if only:
            missing = set(only) - set(items)
            if missing:
                raise RuntimeError(f"예측 품목(item.is_forecast)이 아니다: {sorted(missing)}")
            items = {c: i for c, i in items.items() if c in only}
        if not markets or not items:
            raise RuntimeError("market이나 예측 품목(item.is_forecast)이 비어 있다 (초기 데이터를 먼저 넣어야 한다)")
        run.skipped = Counter()
        for s, e in month_chunks(start, end):
            for code, item_id in items.items():
                cond = {"cond[gds_lclsf_cd::EQ]": code[:2], "cond[gds_mclsf_cd::EQ]": code[2:],
                        "cond[whsl_mrkt_cd::GTE]": "100000", "cond[whsl_mrkt_cd::LTE]": "999999"}   # 전국 시장 범위
                fetch_into(run, Agg(None, {code: item_id}, s, e, markets=markets), cond, f"전국 품목 {code}", s, e)
    return run_(end, conn=conn)


def collect_all(start, end, conn=None):
    """전 품목 전국 모드: 하루씩 품목 조건 없이 전국 시장 범위로 받아 등록된 시장·품목만 저장한다.

    하루 단위인 이유: 호출 수는 행 수에 비례해 달로 묶어도 줄지 않고, 하루씩 끊어야 한도에 걸렸을 때 그날부터 이어 받는다.
    """
    @collect_run(SOURCE, daily_limit=DAILY_LIMIT)
    def run_(run):
        markets, _ = national_targets(run.conn)
        _, items = targets(run.conn)   # 전 품목 {at_code: item_id}
        if not markets or not items:
            raise RuntimeError("market이나 item이 비어 있다 (초기 데이터를 먼저 넣어야 한다)")
        run.skipped = Counter()
        cond = {"cond[whsl_mrkt_cd::GTE]": "100000", "cond[whsl_mrkt_cd::LTE]": "999999"}   # 시장 조건이 없으면 0건
        day = start
        while day <= end:
            fetch_into(run, Agg(None, items, day, day, markets=markets), cond, "전국 전 품목", day, day)
            day += timedelta(days=1)
    return run_(end, conn=conn)


def main(argv=None):
    p = argparse.ArgumentParser(description="aT 정산정보 수집 → settle_price")
    p.add_argument("--start", type=date.fromisoformat)
    p.add_argument("--end", type=date.fromisoformat)
    p.add_argument("--backfill", action="store_true", help=f"{BACKFILL_FROM}부터 받는다 (--start가 있으면 그날부터)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--national", action="store_true", help="예측 품목만 전국 시장으로 받는다 (K31)")
    mode.add_argument("--all-items", action="store_true", help="전 품목을 전국 시장으로 하루씩 받는다 (K32)")
    p.add_argument("--item", action="append", help="--national에서 이 예측 품목(aT 코드)만 받는다. 여러 번 줄 수 있다")
    a = p.parse_args(argv)
    if a.item and not a.national:
        p.error("--item은 --national과 함께 쓴다")
    end = a.end or yesterday()
    start = a.start or (BACKFILL_FROM if a.backfill else end)
    if a.national:
        run = collect_national(start, end, only=a.item)
    else:
        run = (collect_all if a.all_items else collect)(start, end)
    print(f"{start}~{end}: {run.rows}행, API {run.api_calls}건, 건너뜀 {dict(run.skipped)}")


if __name__ == "__main__":
    main()
