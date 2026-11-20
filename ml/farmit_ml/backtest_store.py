"""검증 예측(백테스트)을 forecast_backtest 테이블에 적재한다 (REQ-PRD-005, 가격 통계 차트의 "지난 예측" 선).

    python -m farmit_ml.backtest_store --item 0601     # outputs/oof_0601_<버전>.csv + test_0601_<버전>.csv

- 서비스가 실제로 내보낸 예측(forecast 테이블)은 2026-10부터라 그 전 구간은 비어 있다. 그 구간을
  farmit_ml.selection이 남긴 검증 예측으로 채운다: OOF(연도별 확장 윈도우, 그 해 이전 데이터로만 학습)와
  테스트(테스트 시작 전 데이터로만 학습). 그때 실제로 보여 준 예측이 아니므로 forecast와 섞지 않고 따로 둔다.
- 80% 구간은 지금 설정(intervals.json)의 분위수를 쓴다. 이 분위수는 같은 OOF 잔차로 만든 것이라
  OOF 구간의 적중률은 실제보다 좋게 보인다.
- UK(item_id, market_id, target_week, horizon)로 UPSERT한다. 다시 돌려도 행이 늘지 않는다.
- 접속 정보는 farmit_ml.store와 같은 환경 변수.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import ensemble, store
from .settings import HORIZONS, OUTPUT_DIR, Bundle, config_dir, load_bundle

TABLE = "forecast_backtest"
KEY_COLS = ("item_id", "market_id", "target_week", "horizon")
VALUE_COLS = ("pred_price", "lower80", "upper80", "model_version", "created_at")


def to_rows(pred: pd.DataFrame, b: Bundle, item_id: int, created: datetime) -> list[dict]:
    """selection의 예측 파일(시장 × 기준 행 week, p1~p4) → 테이블 행. 노출(serve) 시장만, 예측이 빈 칸은 뺀다.

    week는 마지막으로 끝난 주라 h주 앞 대상 주는 week + h주다 (farmit_ml.forecast와 같다).
    """
    rows = []
    for r in pred.itertuples(index=False):
        if r.market_cd not in b.serve_markets:
            continue
        for h in HORIZONS:
            p = getattr(r, f"p{h}")
            if pd.isna(p):
                continue
            lo, hi = ensemble.interval(b, np.array(float(p)), h, r.market_cd)
            rows.append({
                "item_id": item_id, "market_id": r.market_cd,
                "target_week": (pd.Timestamp(r.week) + pd.Timedelta(weeks=h)).date(), "horizon": h,
                "pred_price": round(float(p), 1), "lower80": round(float(lo), 1), "upper80": round(float(hi), 1),
                "model_version": f"{b.version}-backtest", "created_at": created,
            })
    return rows


def upsert_sql(n: int) -> str:
    cols = KEY_COLS + VALUE_COLS
    one = "(" + ", ".join(["%s"] * len(cols)) + ")"
    return (f"INSERT INTO `{TABLE}` ({', '.join(f'`{c}`' for c in cols)}) VALUES " + ", ".join([one] * n)
            + " AS new ON DUPLICATE KEY UPDATE " + ", ".join(f"`{c}` = new.`{c}`" for c in VALUE_COLS))


def save(conn, pred: pd.DataFrame, b: Bundle) -> int:
    """한 트랜잭션으로 UPSERT하고 넣은 행 수를 돌려준다."""
    cols = KEY_COLS + VALUE_COLS
    created = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)   # DB에는 UTC로 저장한다
    try:
        with conn.cursor() as cur:
            rows = to_rows(pred, b, store.item_id_of(cur, b.item_code), created)
            for i in range(0, len(rows), store.CHUNK):
                chunk = rows[i:i + store.CHUNK]
                cur.execute(upsert_sql(len(chunk)), [r[c] for r in chunk for c in cols])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return len(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description="검증 예측(OOF·테스트)을 forecast_backtest 테이블에 UPSERT한다")
    ap.add_argument("--item", required=True, help="품목 코드 (config/<품목>/)")
    a = ap.parse_args(argv)
    b = load_bundle(config_dir(a.item))
    files = [OUTPUT_DIR / f"{kind}_{b.item_code}_{b.version}.csv" for kind in ("oof", "test")]
    pred = pd.concat([pd.read_csv(f, encoding="utf-8-sig", dtype={"market_cd": str}) for f in files], ignore_index=True)
    conn = store.connect()
    try:
        print(f"{b.item_code}: {pred['week'].min()} ~ {pred['week'].max()} 기준 행 {len(pred)}개 → {save(conn, pred, b)}행 적재")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
