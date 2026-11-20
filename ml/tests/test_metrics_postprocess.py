from __future__ import annotations

import numpy as np
import pandas as pd

from farmit_ml import postprocess
from farmit_ml.metrics import dir_acc, nmae
from farmit_ml.settings import HORIZONS

MARKETS = ["250001", "250003", "340101", "330101"]


def test_nmae_ignores_nan():
    assert nmae([100, 200, np.nan], [110, 180, 5]) == (10 + 20) / 300


def test_dir_acc_skips_no_change():
    # 1행: 둘 다 상승(맞음), 2행: 예측 하락·실제 상승(틀림), 3행: 예측 변화 없음(제외)
    assert dir_acc([110, 110, 90], [105, 95, 100], [100, 100, 100]) == 0.5


def _pred(weeks, value):
    rows = [{"week": w, "market_cd": m, **{f"p{h}": value[m] for h in HORIZONS}} for w in weeks for m in MARKETS]
    return pd.DataFrame(rows)


def test_shrink_market_weights():
    weeks = pd.date_range("2024-01-01", periods=30, freq="7D")
    hist = _pred(weeks, {m: 1000.0 for m in MARKETS}).rename(columns={"p1": "price_kg"})  # 시장 간 가격 비율 1
    value = {m: 1000.0 for m in MARKETS}
    value["340101"] = 1400.0
    pred = _pred(weeks[-1:], value)

    same = postprocess.apply(pred, hist, {"340101": 0.0}, MARKETS)
    assert same.equals(pred)

    half = postprocess.apply(pred, hist, {"340101": 0.5}, MARKETS)
    ch = half[half["market_cd"] == "340101"]
    assert np.allclose(ch[[f"p{h}" for h in HORIZONS]].values, 1200.0)       # 0.5·1400 + 0.5·1000
    others = half[half["market_cd"] != "340101"]
    assert np.allclose(others[[f"p{h}" for h in HORIZONS]].values, 1000.0)   # 다른 시장은 그대로
