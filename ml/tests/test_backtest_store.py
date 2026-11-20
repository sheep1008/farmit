"""farmit_ml.backtest_store: 검증 예측 파일 → forecast_backtest 행."""
from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pandas as pd

from farmit_ml import backtest_store


def test_to_rows_serve_markets_only_and_target_week_is_week_plus_h():
    b = SimpleNamespace(version="v4", serve_markets=["110001"], config_path="x", item_code="0601",
                        interval_q={"*": {h: (-0.1, 0.2) for h in (1, 2, 3, 4)}})
    pred = pd.DataFrame([
        {"market_cd": "110001", "week": "2021-01-04", "p1": 1000.0, "p2": 2000.0, "p3": float("nan"), "p4": 4000.0},
        {"market_cd": "999999", "week": "2021-01-04", "p1": 1.0, "p2": 1.0, "p3": 1.0, "p4": 1.0},   # 노출 시장 아님
    ])
    rows = backtest_store.to_rows(pred, b, item_id=10, created=datetime(2026, 11, 20))

    assert [(r["horizon"], r["target_week"]) for r in rows] == [
        (1, date(2021, 1, 11)), (2, date(2021, 1, 18)), (4, date(2021, 2, 1))]   # 빈 예측(h3)은 뺀다
    assert rows[0] == {"item_id": 10, "market_id": "110001", "target_week": date(2021, 1, 11), "horizon": 1,
                       "pred_price": 1000.0, "lower80": 900.0, "upper80": 1200.0,
                       "model_version": "v4-backtest", "created_at": datetime(2026, 11, 20)}


def test_upsert_sql_updates_values_on_duplicate_key():
    sql = backtest_store.upsert_sql(2)
    assert sql.startswith("INSERT INTO `forecast_backtest`") and sql.count("(%s, %s, %s, %s, %s, %s, %s, %s, %s)") == 2
    assert "ON DUPLICATE KEY UPDATE `pred_price` = new.`pred_price`" in sql
