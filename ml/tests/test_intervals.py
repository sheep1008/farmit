"""80% 구간: OOF 잔차 분위수(시장 × h, 적으면 전체), 커버리지 계산, 예측에서 시장별 구간 사용."""
from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd

from farmit_ml import ensemble
from farmit_ml.intervals import POOLED, coverage, quantiles
from farmit_ml.settings import HORIZONS


def _pred(market: str, n: int, spread: float, seed: int) -> pd.DataFrame:
    """예측 1000, 실제 = 1000 × (1 + 균등(−spread, +spread))."""
    rng = np.random.default_rng(seed)
    d = pd.DataFrame({"market_cd": market, "market_nm": market, "week": pd.date_range("2021-01-04", periods=n, freq="7D")})
    for h in HORIZONS:
        d[f"p{h}"] = 1000.0
        d[f"target_h{h}"] = 1000.0 * (1 + rng.uniform(-spread, spread, n))
    return d


def test_quantiles_per_market_with_pooled_fallback():
    oof = pd.concat([_pred("wide", 400, 0.5, 0), _pred("narrow", 400, 0.1, 1), _pred("few", 50, 0.1, 2)])
    q = quantiles(oof, level=0.8, min_n=100)
    assert set(q) == {POOLED, "wide", "narrow"}                      # 잔차 50개인 시장은 전체 값을 쓴다
    lo, hi = q["wide"]["1"]
    assert np.isclose(lo, -0.4, atol=0.05) and np.isclose(hi, 0.4, atol=0.05)   # 균등(−0.5, 0.5)의 10%·90%
    assert q["narrow"]["1"][1] < q["wide"]["1"][1]                    # 오차가 큰 시장은 구간이 넓다


def test_quantiles_always_contain_prediction():
    d = _pred("biased", 200, 0.05, 3)
    for h in HORIZONS:
        d[f"target_h{h}"] += 200.0                                    # 실제가 늘 예측보다 크다
    lo, hi = quantiles(d, min_n=100)["biased"]["1"]
    assert lo == 0.0 and hi > 0


def test_coverage_counts_inside_interval():
    d = _pred("m", 100, 0.5, 4)
    q = quantiles(d, min_n=10)
    cov = coverage(d, q)
    assert (cov["n"] == 100).all()
    assert np.isclose(cov["covered"].sum() / cov["n"].sum(), 0.8, atol=0.03)   # 자기 잔차로 만든 구간 ≈ 80%


def test_interval_uses_market_then_pooled(bundle):
    q = {"*": {h: (-0.1, 0.1) for h in HORIZONS}, "250001": {h: (-0.3, 0.2) for h in HORIZONS}}
    b = dataclasses.replace(bundle, interval_q=q)
    assert np.allclose(ensemble.interval(b, np.array(1000.0), 1, "250001"), (700, 1200))
    assert np.allclose(ensemble.interval(b, np.array(1000.0), 1, "330101"), (900, 1100))
