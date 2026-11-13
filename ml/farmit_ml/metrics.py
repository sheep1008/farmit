"""평가 지표와 기준선. NMAE가 주 지표다 (모델 선택·튜닝·비교)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _clean(*arrays):
    arrs = [np.asarray(a, float) for a in arrays]
    m = ~np.any([np.isnan(a) for a in arrs[:2]], axis=0)
    return [a[m] for a in arrs]


def nmae(y, p) -> float:
    """Σ|y − ŷ| / Σy. 가격 수준이 다른 연도·시장을 같은 척도로 비교한다."""
    y, p = _clean(y, p)
    return float(np.abs(y - p).sum() / y.sum())


def mae(y, p) -> float:
    y, p = _clean(y, p)
    return float(np.abs(y - p).mean())


def rmse(y, p) -> float:
    y, p = _clean(y, p)
    return float(np.sqrt(((y - p) ** 2).mean()))


def dir_acc(y, p, last) -> float:
    """sign(예측 − 지난주) == sign(실제 − 지난주) 비율. 예측이 지난주와 같으면 뺀다."""
    y, p, last = _clean(y, p, last)
    m = np.abs(p - last) > 1e-9
    return float((np.sign(y[m] - last[m]) == np.sign(p[m] - last[m])).mean()) if m.any() else float("nan")


def evaluate(df: pd.DataFrame, pred, h: int) -> dict:
    y, last = df[f"target_h{h}"].values, df["price_kg"].values
    return {"nmae": nmae(y, pred), "mae": mae(y, pred), "rmse": rmse(y, pred), "dir_acc": dir_acc(y, pred, last)}


def baseline_pred(df: pd.DataFrame, name: str) -> np.ndarray:
    """B1 직전값(지난주 가격 그대로), B2 4주 이동평균. horizon별로 둘 중 나은 쪽이 넘어야 할 선이다."""
    return {"B1_last": df["price_kg"], "B2_ma4": df["price_ma4"]}[name].values
