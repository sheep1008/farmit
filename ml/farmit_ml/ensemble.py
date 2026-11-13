"""앙상블: 구성 모델마다 h1~h4를 예측하고 가중 평균한 뒤 후처리한다.

구성 모델과 가중치는 config/final_choice.json의 weights가 정한다. 이름 규칙:
  "RandomForest" / "LightGBM" / "XGBoost"       h별 트리 모델
  "RandomForest(통합)" 등                        horizon 통합 트리 모델
  "LSTM"                                        LSTM (시드 평균)
새 모델을 넣으려면 COMPONENTS에 이름 → 예측 함수를 등록하고 weights에 이름을 추가한다 (docs/ml.md "확장 방법").
"""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from . import lstm, models, postprocess
from .settings import HORIZONS, LSTM_NAME, STACKED_SUFFIX, TREE_NAMES, Bundle

# 예측 함수: (bundle, df_all, trn, tst) → (len(tst), len(HORIZONS)) 가격 배열
Predictor = Callable[[Bundle, pd.DataFrame, pd.DataFrame, pd.DataFrame], np.ndarray]


def _per_h(m: str) -> Predictor:
    return lambda b, df_all, trn, tst: models.predict_per_h(
        m, b.tree_features, trn, tst, b.target_mode, b.best_params[m], b.tree_prep)


def _stacked(m: str) -> Predictor:
    return lambda b, df_all, trn, tst: models.predict_stacked(
        m, b.tree_features, trn, tst, b.target_mode, b.stack_params[m], b.tree_prep)


def _lstm(b: Bundle, df_all, trn, tst) -> np.ndarray:
    return lstm.predict_avg(b.lstm_params, df_all, trn, tst, b.lin_features, b.lin_prep, b.lstm_seeds)


COMPONENTS: dict[str, Predictor] = {
    **{nm: _per_h(m) for m, nm in TREE_NAMES.items()},
    **{nm + STACKED_SUFFIX: _stacked(m) for m, nm in TREE_NAMES.items()},
    LSTM_NAME: _lstm,
}


def predict_components(b: Bundle, df_all: pd.DataFrame, trn: pd.DataFrame, tst: pd.DataFrame) -> dict[str, np.ndarray]:
    """가중치가 0보다 큰 구성 모델만 학습·예측한다."""
    unknown = [k for k in b.weights if k not in COMPONENTS]
    if unknown:
        raise KeyError(f"등록되지 않은 모델 이름: {unknown}. ensemble.COMPONENTS에 등록한다")
    return {k: COMPONENTS[k](b, df_all, trn, tst) for k, w in b.weights.items() if w > 0}


def combine(preds: dict[str, np.ndarray], weights: dict) -> np.ndarray:
    """가중 평균. 어떤 모델이 특정 행을 예측하지 못했으면(NaN) 그 행은 나머지 가중치로 다시 나눈다."""
    num = sum(weights[k] * np.nan_to_num(p) for k, p in preds.items())
    den = sum(weights[k] * ~np.isnan(p) for k, p in preds.items())
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / den, np.nan)


def predict(b: Bundle, df_all: pd.DataFrame, trn: pd.DataFrame, tst: pd.DataFrame,
            use_postprocess: bool = True) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    """최종 예측(넓은 표: week, market_cd, p1..p4)과 구성 모델별 예측을 돌려준다."""
    parts = predict_components(b, df_all, trn, tst)
    p = combine(parts, b.weights)
    wide = tst[["week", "market_cd"]].assign(**{f"p{h}": p[:, j] for j, h in enumerate(HORIZONS)})
    if use_postprocess:
        # 비율 계산에는 예측 시점까지의 실제 가격(price_kg)만 쓴다
        hist = df_all[df_all["week"] <= tst["week"].max()]
        wide = postprocess.apply(wide, hist, b.pp_weights, b.pp_n_weeks)
    return wide, parts


def interval(b: Bundle, pred: np.ndarray, h: int) -> tuple[np.ndarray, np.ndarray]:
    """80% 구간 (REQ-PRD-002). 테스트 상대잔차 분위수를 예측값에 곱한다."""
    lo, hi = b.interval_q[h]
    return pred * (1 + lo), pred * (1 + hi)
