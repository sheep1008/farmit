"""예측 결과 형식(forecast 테이블 계약)과 누수 없음, 설정형 시장·피처 확인."""
from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from farmit_ml import ensemble, forecast
from farmit_ml.data import as_of, check_columns, needed_features
from farmit_ml.settings import HORIZONS, LSTM_NAME


def test_forecast_rows_match_table_contract(weekly, bundle):
    fc = forecast.run(weekly, bundle)
    base = weekly["pred_date"].max()

    assert list(fc.columns) == forecast.OUTPUT_COLS
    assert len(fc) == len(bundle.serve_markets) * len(HORIZONS)   # serve 시장 × h 4 (REQ-PRD-001)
    assert not fc.duplicated(["market_cd", "base_week", "horizon"]).any()
    assert (fc["base_week"] == base.date()).all()
    for h in HORIZONS:                                      # h1 = 이번 주(base_week), h4 = 3주 후
        assert (fc.loc[fc["horizon"] == h, "target_week"] == (base + pd.Timedelta(weeks=h - 1)).date()).all()
    assert fc["pred_price"].notna().all() and (fc["pred_price"] > 0).all()
    assert ((fc["lower80"] <= fc["pred_price"]) & (fc["pred_price"] <= fc["upper80"])).all()


def test_forecast_outputs_serve_markets_only(weekly, bundle):
    """학습은 모든 학습 시장으로 하고, 결과는 serve 시장만 낸다."""
    serve = list(bundle.markets)[:1]
    fc = forecast.run(weekly, dataclasses.replace(bundle, serve_markets=serve))
    assert set(fc["market_cd"]) == set(serve)
    assert len(fc) == len(HORIZONS)


def test_as_of_hides_future(weekly):
    base = pd.Timestamp("2022-10-03")
    h = as_of(weekly, base)
    assert h["pred_date"].max() == base
    for k in HORIZONS:
        assert h.loc[h[f"target_week_h{k}"] >= base, f"target_h{k}"].isna().all()


def test_backfill_ignores_future_rows(weekly, bundle):
    """지난 주차를 다시 예측할 때, 그 뒤 데이터가 있든 없든 결과가 같아야 한다."""
    base = pd.Timestamp("2023-03-06")
    full = forecast.run(weekly, bundle, base)
    cut = forecast.run(weekly[weekly["pred_date"] <= base], bundle, base)
    cols = ["pred_price", "lower80", "upper80"]
    np.testing.assert_allclose(full[cols].values, cut[cols].values, rtol=1e-6)


def test_combine_reweights_missing_component():
    a, b = np.array([[100.0], [100.0]]), np.array([[200.0], [np.nan]])
    p = ensemble.combine({"A": a, "B": b}, {"A": 0.5, "B": 0.5})
    assert p[0, 0] == 150 and p[1, 0] == 100


def test_check_columns_follows_config(weekly, bundle):
    """필요한 피처는 가중치가 있는 구성 모델의 preprocess.json 피처뿐이다. 학습 시장이 데이터에 없으면 멈춘다."""
    check_columns(weekly, bundle)
    trees_only = dataclasses.replace(bundle, weights={**bundle.weights, LSTM_NAME: 0.0})
    lstm_only = dataclasses.replace(bundle, weights={k: float(k == LSTM_NAME) for k in bundle.weights})
    assert needed_features(trees_only) == bundle.tree_features     # LSTM 가중치 0 → linear 피처는 검사하지 않는다
    assert needed_features(lstm_only) == bundle.lin_features
    with pytest.raises(ValueError, match="필요한 컬럼"):
        check_columns(weekly.drop(columns=[bundle.tree_features[1]]), bundle)
    with pytest.raises(ValueError, match="데이터에 없는 시장"):
        check_columns(weekly, dataclasses.replace(bundle, markets={**bundle.markets, "999999": "없는시장"}))
