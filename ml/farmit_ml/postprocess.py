"""후처리: 거래가 적은 시장의 예측을 다른 시장 예측 쪽으로 당긴다 (시장 간 수축).

천안처럼 거래가 적은 시장은 주평균 가격이 잡음에 크게 흔들린다. 같은 주 다른 세 시장의 예측 평균에
최근 가격 비율을 곱한 값(대체 예측)과 섞는다. 비율은 예측 시점까지 알려진 지난 n주 가격으로 매주 다시 계산한다.
시장별 섞는 비율 w는 config/postprocess.json에 있다 (2021~2024 OOF에서 네 해 모두 개선되는 w 중 평균 최대).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .settings import HORIZONS


def market_ratio(hist: pd.DataFrame, target: str, others: list[str], n: int = 26) -> pd.Series:
    """주별 (target 시장 / others 평균) 가격 비율의 지난 n주 이동 중앙값."""
    pk = hist.pivot_table(index="week", columns="market_cd", values="price_kg")
    return (pk[target] / pk[others].mean(axis=1)).rolling(n, min_periods=n // 2).median()


def shrink_market(pred: pd.DataFrame, hist: pd.DataFrame, target: str, w: float, markets: list[str],
                  n: int = 26) -> pd.DataFrame:
    """pred(열: week, market_cd, p1..p4)에서 target 시장 예측을 (1-w)·자기 예측 + w·대체 예측으로 바꾼다.

    대체 예측 = markets 중 target을 뺀 시장들의 예측 평균 × 최근 가격 비율.
    """
    out = pred.copy()
    if w <= 0:
        return out
    mk = out["market_cd"] == target
    others = [m for m in markets if m != target]
    ratio = market_ratio(hist, target, others, n)
    for h in HORIZONS:
        piv = pred.pivot_table(index="week", columns="market_cd", values=f"p{h}")
        if not set(others) <= set(piv.columns):
            continue  # 다른 시장 예측이 없으면 보정하지 않는다
        alt = (ratio * piv[others].mean(axis=1)).reindex(out.loc[mk, "week"]).values
        own = out.loc[mk, f"p{h}"].values
        out.loc[mk, f"p{h}"] = np.where(np.isnan(alt), own, (1 - w) * own + w * alt)
    return out


def apply(pred: pd.DataFrame, hist: pd.DataFrame, weights: dict, markets: list[str], n: int = 26) -> pd.DataFrame:
    """시장별 w를 적용한다 (weights가 비어 있으면 그대로). 대체 예측은 항상 보정 전 예측으로 만든다 (적용 순서와 무관)."""
    out = pred.copy()
    for mc, w in weights.items():
        sel = out["market_cd"] == mc
        out.loc[sel] = shrink_market(pred, hist, mc, w, markets, n).loc[sel]
    return out
