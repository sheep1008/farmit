"""실험 공통: 경로, API 키, aT 정산정보 조회.

키는 환경 변수 또는 레포 루트 .env에서 읽는다 (DATA_GO_KR_KEY, KOSIS_API_KEY).
키 값은 출력·예외 메시지·파일 어디에도 남기지 않는다.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
ML_ROOT = HERE.parent
REPO = ML_ROOT.parent
DATA = HERE / "data"            # 원천 합계·결과 (커밋하지 않음)
RESULTS = DATA / "results"
for _d in (DATA, RESULTS):
    _d.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ML_ROOT))   # farmit_ml (지표·모델 생성) 재사용

AT_URL = "https://apis.data.go.kr/B552845/katSale/trades"
ALL_MARKETS = {"cond[whsl_mrkt_cd::GTE]": "100000", "cond[whsl_mrkt_cd::LTE]": "999999"}  # 시장 조건이 없으면 0건이 온다
_session = requests.Session()
CALLS = 0


def get_key(name: str) -> str:
    v = os.environ.get(name)
    if not v and (REPO / ".env").exists():
        for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"{name}="):
                v = line.split("=", 1)[1].strip()
    if not v:
        raise SystemExit(f"{name}가 없다. 레포 루트 .env에 넣거나 환경 변수로 준다")
    return v


def redact(text) -> str:
    text = str(text)
    for n in ("DATA_GO_KR_KEY", "KOSIS_API_KEY"):
        v = os.environ.get(n)
        if v:
            text = text.replace(v, "***")
    return text


def at_fetch(cond: dict, page_size: int = 10000) -> tuple[list, int]:
    """aT 정산정보 조회. 날짜는 반드시 cond[trd_clcln_ymd::GTE/LTE]=YYYY-MM-DD (EQ나 YYYYMMDD는 0건)."""
    global CALLS
    key = get_key("DATA_GO_KR_KEY")
    rows, page = [], 1
    while True:
        p = {"serviceKey": key, "pageNo": page, "numOfRows": page_size, "returnType": "json", **cond}
        last = None
        for i in range(4):
            try:
                d = _session.get(AT_URL, params=p, timeout=90).json(); CALLS += 1
                break
            except Exception as e:  # noqa: BLE001
                last = e; time.sleep(2 * (i + 1))
        else:
            raise RuntimeError(redact(last).replace(key, "***"))
        body = d.get("response", {}).get("body")
        if body is None:
            raise RuntimeError(redact(json.dumps(d, ensure_ascii=False)[:300]).replace(key, "***"))
        items = body.get("items") or {}
        items = items.get("item", []) if isinstance(items, dict) else items
        if isinstance(items, dict):
            items = [items]
        rows += items
        total = int(body.get("totalCount", 0))
        if len(rows) >= total or not items:
            return rows, total
        page += 1
