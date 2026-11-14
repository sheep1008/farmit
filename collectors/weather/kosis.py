"""KOSIS 과실생산량(전국, 연) 수집 → crop_production (K09, REQ-COL-003).

연 1회 공표되는 통계라 한 번 호출로 FROM_YEAR~올해를 모두 받아 UPSERT한다 (호출 1건, docs/data-sources.md 5절).
품목은 item 테이블 이름과 정확히 같고, 그 이름이 item에 하나뿐인 과일만 저장한다 ('기타'는 item에 둘이라 제외).

    docker compose -f infra/docker-compose.yml --profile collect run --rm collectors python -m weather.kosis
"""
import json
import os
import urllib.parse
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from common.collect_log import KST, collect_run
from common.db import upsert

URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"
SOURCE = "kosis"
TABLE_ID = "DT_1ET0292"  # 과실생산량(성과수+미과수)
FROM_YEAR = 2012          # ml/experiments/collect_kosis.py와 같다. 2018년 학습에 전년 값이 필요하다
# ITM_NM '과일:지표'의 지표 → crop_production 컬럼
METRICS = {"면적": "area_ha", "생산량": "production_kg", "10a당 생산량": "yield_kg_10a"}
COLUMNS = list(METRICS.values()) + ["kosis_updated_on"]


class KosisError(Exception):
    """KOSIS가 행 목록 대신 {"err": ..., "errMsg": ...}를 돌려줬다."""


def item_ids(conn):
    """item 이름 → item_id. 이름이 둘 이상인 품목('기타')은 어느 것인지 알 수 없으므로 뺀다."""
    with conn.cursor() as cur:
        cur.execute("SELECT name, MIN(item_id) FROM item GROUP BY name HAVING COUNT(*) = 1")
        return dict(cur.fetchall())


def number(text):
    """'460088.4145' → Decimal. KOSIS는 값이 없으면 '-' 등을 줄 수 있어 숫자가 아니면 None."""
    try:
        return Decimal(text)
    except (InvalidOperation, TypeError):
        return None


def to_rows(data, ids):
    """KOSIS 행 목록 → (crop_production 행 목록, 건너뛴 과일 이름 집합)."""
    rows, skipped = {}, set()
    for r in data:
        fruit, _, metric = r["ITM_NM"].partition(":")
        col = METRICS.get(metric)
        if col is None:
            continue
        if fruit not in ids:
            skipped.add(fruit)
            continue
        row = rows.setdefault((fruit, r["PRD_DE"]), {
            "item_id": ids[fruit], "year": int(r["PRD_DE"]), **{c: None for c in COLUMNS}})
        v = number(r["DT"])
        if col == "production_kg" and v is not None:
            v = int((v * 1000).to_integral_value(ROUND_HALF_UP))  # 톤 → kg (반올림)
        row[col] = v
        # 지표마다 수정일이 다를 수 있어 가장 늦은 날을 그해 값의 공표일로 본다
        row["kosis_updated_on"] = max(filter(None, [row["kosis_updated_on"], r["LST_CHN_DE"]]))
    return list(rows.values()), skipped


def fetch(run):
    text = run.get(URL, {
        "method": "getList", "format": "json", "jsonVD": "Y", "prdSe": "Y",
        "startPrdDe": FROM_YEAR, "endPrdDe": datetime.now(KST).year,
        "orgId": "101", "tblId": TABLE_ID, "itmId": "ALL", "objL1": "00",  # 전국. objL2를 넣으면 오류 21
    }, key=("apiKey", urllib.parse.quote(os.environ["KOSIS_API_KEY"].strip(), safe="")))
    data = json.loads(text)
    if not isinstance(data, list):
        raise KosisError(f"{data.get('err')} {data.get('errMsg')}")
    return data


def collect(conn=None):
    @collect_run(SOURCE)
    def run_(run):
        rows, run.skipped = to_rows(fetch(run), item_ids(run.conn))
        run.rows += upsert(run.conn, "crop_production", rows, COLUMNS)
    return run_(datetime.now(KST).date(), conn=conn)


if __name__ == "__main__":
    r = collect()
    print(f"{r.rows}행 저장, 호출 {r.api_calls}건, item에 없어 건너뜀: {', '.join(sorted(r.skipped)) or '없음'}")
