"""테스트용 가짜 주간 데이터와 빠른 설정. 실제 데이터 없이 파이프라인 연결을 확인한다."""
from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from farmit_ml.preprocess import PRICE_LEVEL_COLS
from farmit_ml.settings import HORIZONS, MARKETS, load_bundle

N_WEEKS = 80


@pytest.fixture(scope="session")
def bundle():
    """config/ 그대로에 모델 크기만 줄인 설정."""
    b = load_bundle()
    small = {"lgbm": {"n_estimators": 20}, "xgb": {"n_estimators": 20}, "rf": {"n_estimators": 10}}
    return dataclasses.replace(
        b,
        best_params={m: {**b.best_params[m], **small[m]} for m in small},
        stack_params={m: {**b.stack_params[m], **small[m]} for m in small},
        lstm_params={**b.lstm_params, "epochs": 2},
        lstm_seeds=1,
    )


@pytest.fixture(scope="session")
def weekly(bundle) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    feats = sorted(set(bundle.tree_features) | set(bundle.lin_features))
    weeks = pd.date_range("2022-01-03", periods=N_WEEKS, freq="7D")
    parts = []
    for i, (cd, nm) in enumerate(MARKETS.items()):
        price = 3000 * np.exp(np.cumsum(rng.normal(0, 0.05, N_WEEKS))) * (1 + 0.05 * i)
        d = pd.DataFrame({"market_cd": cd, "market_nm": nm, "week": weeks, "pred_date": weeks + pd.Timedelta(days=7)})
        for c in feats:
            d[c] = price * rng.uniform(0.9, 1.1, N_WEEKS) if c in PRICE_LEVEL_COLS else rng.normal(0, 1, N_WEEKS)
        d["price_kg"] = price
        d["price_ma4"] = pd.Series(price).rolling(4, min_periods=1).mean().values
        for h in HORIZONS:
            d[f"target_h{h}"] = pd.Series(price).shift(-h).values
            d[f"target_week_h{h}"] = d["week"] + pd.Timedelta(weeks=h)
            d[f"hol_offset_h{h}"] = rng.integers(-35, 36, N_WEEKS)
            d[f"hol_in_target_h{h}"] = 0
        parts.append(d)
    return pd.concat(parts).sort_values(["market_cd", "week"]).reset_index(drop=True)
