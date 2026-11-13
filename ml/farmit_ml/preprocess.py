"""전처리와 타깃 변환. 통계(중앙값·평균·표준편차)는 fit에 넣은 학습 구간에서만 계산한다 (누수 방지)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .settings import MARKETS

# 원/kg 가격 수준 피처 (relative=True면 이번 주 가격 대비 로그비로 바꾼다)
PRICE_LEVEL_COLS = {"price_kg_allgrade", "price_lag1", "price_lag2", "price_lag4", "price_ma4", "price_ma8",
                    "price_yoy", "price_yoy_h1", "price_yoy_h2", "price_yoy_h3", "price_yoy_h4", "price_ffill",
                    "garak_price_kg", "garak_price_ma4", "retail_10ea", "retail_10ea_national", "retail_10ea_filled",
                    "price_last1", "price_last2"}


def add_market_dummies(X: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    d = pd.DataFrame({f"mkt_{k}": (df["market_cd"] == k).astype(float) for k in MARKETS}, index=df.index)
    return pd.concat([X, d], axis=1)


def to_target(df: pd.DataFrame, h: int, mode: str) -> pd.Series:
    """logratio: log(h 타깃 / 지난주 가격). 연도마다 가격 수준이 달라도 분포가 비슷해진다."""
    y = df[f"target_h{h}"]
    return np.log(y / df["price_kg"]) if mode == "logratio" else y


def from_target(df: pd.DataFrame, pred, mode: str) -> np.ndarray:
    return df["price_kg"].values * np.exp(pred) if mode == "logratio" else np.asarray(pred)


class Preprocessor:
    """결측·스케일 처리.

    fill: 'none'(트리, 결측 유지) | 'median'(RF·LSTM, 중앙값 + 결측 표시 컬럼)
    relative: 가격 수준 피처를 이번 주 가격 대비 로그비로
    pest_zero: 예찰 지표 결측(휴지기)을 0으로
    clip: 표준화 뒤 ±clip으로 자름
    """

    def __init__(self, features: list[str], fill: str = "none", scale: bool = False, pest_zero: bool = True,
                 market_dummies: bool = True, relative: bool = False, clip: float | None = None):
        self.features, self.fill, self.scale, self.pest_zero = features, fill, scale, pest_zero
        self.market_dummies, self.relative, self.clip = market_dummies, relative, clip

    def _base(self, df: pd.DataFrame) -> pd.DataFrame:
        X = df[self.features].astype(float).copy()
        if self.relative:
            ref = df["price_kg"].astype(float)
            for c in [c for c in X if c in PRICE_LEVEL_COLS]:
                X[c] = np.log(X[c] / ref)
            if "price_kg" in X:
                X["price_kg"] = np.log(ref)  # 수준 정보는 로그 가격 하나로만 남긴다
        if self.pest_zero:
            pc = [c for c in X if c.startswith("pest_") and c not in ("pest_age_days", "pest_in_season")]
            X[pc] = X[pc].fillna(0.0)
        return X

    def fit(self, df: pd.DataFrame):
        X = self._base(df)
        self.med_ = X.median().fillna(0.0)
        self.na_cols_ = [c for c in X if X[c].isna().any()] if self.fill == "median" else []
        if self.fill == "median":
            X = X.fillna(self.med_)
        self.mu_, self.sd_ = X.mean(), X.std().replace(0, 1.0).fillna(1.0)
        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        X = self._base(df)
        if self.fill == "median":
            ind = X[self.na_cols_].isna().astype(float).add_suffix("_isna")
            X = pd.concat([X.fillna(self.med_), ind], axis=1)
        if self.scale:
            base = [c for c in X if not c.endswith("_isna")]
            X[base] = (X[base] - self.mu_[base]) / self.sd_[base]
            if self.clip:
                X[base] = X[base].clip(-self.clip, self.clip)
        if self.market_dummies:
            X = add_market_dummies(X, df)
        return X

    def fit_transform(self, df: pd.DataFrame) -> pd.DataFrame:
        return self.fit(df).transform(df)
