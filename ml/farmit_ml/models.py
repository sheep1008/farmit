"""트리 모델: h별 모델과 horizon 통합 모델.

- h별 모델: h1~h4마다 모델을 따로 학습한다.
- horizon 통합 모델: (행, h)를 쌓아 모델 하나로 학습한다. 예측 대상 주의 명절 위치와 horizon을 피처로 주므로
  같은 명절을 네 시점에서 보게 된다 (참고 저장소 08 노트북 C절).
모든 모델은 NMAE에 맞춰 L1(MAE) 계열 손실로 학습한다.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from .data import cv_folds
from .metrics import nmae
from .preprocess import Preprocessor, from_target, to_target
from .settings import HORIZONS, SEED, THREADS

TREE_MODELS = {"lgbm", "xgb", "rf"}
STACK_HSPEC = ["price_yoy", "hol_offset", "hol_in_target"]  # horizon마다 값이 다른 피처. 통합 모델에서는 _h1 자리에 넣는다
N_JOBS = THREADS


def make_model(name: str, params: dict | None = None):
    p = dict(params or {})
    if name == "lgbm":
        import lightgbm as lgb
        base = dict(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8,
                    subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0)
        return lgb.LGBMRegressor(objective="l1", random_state=SEED, verbose=-1, n_jobs=N_JOBS, **{**base, **p})
    if name == "xgb":
        import xgboost as xgb
        base = dict(n_estimators=400, learning_rate=0.03, max_depth=4, min_child_weight=5, subsample=0.8,
                    colsample_bytree=0.8, reg_lambda=1.0)
        return xgb.XGBRegressor(objective="reg:absoluteerror", random_state=SEED, n_jobs=N_JOBS, tree_method="hist",
                                **{**base, **p})
    if name == "rf":
        from sklearn.ensemble import RandomForestRegressor
        base = dict(n_estimators=300, max_depth=None, min_samples_leaf=5, max_features=0.5)
        return RandomForestRegressor(random_state=SEED, n_jobs=N_JOBS, **{**base, **p})
    if name == "huber":
        from sklearn.linear_model import HuberRegressor
        return HuberRegressor(**{**dict(epsilon=1.35, alpha=1.0, max_iter=2000), **p})
    raise ValueError(f"모르는 모델: {name}")


def prep_for(model: str, features: list[str], **kw) -> Preprocessor:
    if model in TREE_MODELS:
        # RandomForest는 결측을 못 받으므로 중앙값으로 채운다
        return Preprocessor(features, fill="none" if model != "rf" else "median", scale=False, **kw)
    return Preprocessor(features, fill="median", scale=True, **kw)


def fit_predict(model: str, features: list[str], trn: pd.DataFrame, tst: pd.DataFrame, h: int,
                mode: str = "logratio", params: dict | None = None, prep_kw: dict | None = None) -> np.ndarray:
    """trn으로 학습해 tst의 h 타깃을 가격(원/kg)으로 예측한다. 타깃이 없는 학습 행은 뺀다."""
    trn = trn[trn[f"target_h{h}"].notna()]
    prep = prep_for(model, features, **(prep_kw or {}))
    Xtr, Xte = prep.fit_transform(trn), prep.transform(tst)
    m = make_model(model, params)
    m.fit(Xtr, to_target(trn, h, mode))
    return from_target(tst, m.predict(Xte), mode)


def predict_per_h(model: str, features: list[str], trn, tst, mode: str, params: dict, prep_kw: dict) -> np.ndarray:
    """h별 모델 → (len(tst), len(HORIZONS)) 가격 배열."""
    return np.column_stack([fit_predict(model, features, trn, tst, h, mode, params, prep_kw) for h in HORIZONS])


# ----------------------------------------------------------------------------- horizon 통합 모델
def stacked_features(features: list[str]) -> list[str]:
    """h2~h4 전용 피처를 빼고 horizon을 더한다."""
    return [f for f in features if not re.search(r"_h[2-4]$", f)] + ["horizon"]


def stack(d: pd.DataFrame) -> pd.DataFrame:
    """(행, h)를 쌓는다. h별 피처와 타깃은 _h1 자리에 넣어 같은 전처리를 그대로 쓴다."""
    parts = []
    for h in HORIZONS:
        s = d.copy()
        for b in STACK_HSPEC:
            s[f"{b}_h1"] = d[f"{b}_h{h}"]
        s["target_h1"], s["horizon"] = d[f"target_h{h}"], float(h)
        parts.append(s)
    return pd.concat(parts, ignore_index=True)


def predict_stacked(model: str, features: list[str], trn, tst, mode: str, params: dict, prep_kw: dict) -> np.ndarray:
    """horizon 통합 모델 → (len(tst), len(HORIZONS)) 가격 배열."""
    sv = stack(tst)
    p = fit_predict(model, stacked_features(features), stack(trn), sv, 1, mode, params, prep_kw)
    return np.column_stack([p[(sv["horizon"] == h).values] for h in HORIZONS])


# ----------------------------------------------------------------------------- 실험용
def cv_eval(dev: pd.DataFrame, features: list[str], model: str = "lgbm", mode: str = "logratio",
            params: dict | None = None, prep_kw: dict | None = None, years=None) -> pd.DataFrame:
    """확장 윈도우 교차검증 NMAE 표 (fold × h). 하이퍼파라미터·피처 실험에 쓴다."""
    rows = []
    for y, trn, val in cv_folds(dev, *([years] if years else [])):
        for h in HORIZONS:
            p = fit_predict(model, features, trn, val, h, mode, params, prep_kw)
            rows.append({"fold": y, "h": h, "nmae": nmae(val[f"target_h{h}"], p)})
    return pd.DataFrame(rows).pivot(index="fold", columns="h", values="nmae")
