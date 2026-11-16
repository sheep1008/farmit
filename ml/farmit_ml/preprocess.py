"""전처리와 타깃 변환. 통계(중앙값·평균·표준편차)는 fit에 넣은 학습 구간에서만 계산한다 (누수 방지)."""
from __future__ import annotations

import numpy as np
import pandas as pd

# 원/kg 가격 수준 피처 (relative=True면 이번 주 가격 대비 로그비로 바꾼다). 설정에 없는 이름은 쓰이지 않는다
PRICE_LEVEL_COLS = {
    # 공통 피처 (K30, docs/ml.md 3.1)
    "price_allgrade", "price_last1", "price_lag1", "price_lag2", "price_lag4", "price_ma4", "price_ma8", "price_yoy",
    "nat_price", "nat_price_ma4", "garak_price", "garak_price_ma4",
    # v3 데이터셋에만 있는 이름 (config/0601_v3 재현용)
    "price_kg_allgrade", "garak_price_kg", "price_yoy_h1", "price_yoy_h2", "price_yoy_h3", "price_yoy_h4",
    "price_ffill", "price_last2", "retail_10ea", "retail_10ea_national", "retail_10ea_filled",
}


def add_market_dummies(X: pd.DataFrame, df: pd.DataFrame, markets) -> pd.DataFrame:
    d = pd.DataFrame({f"mkt_{k}": (df["market_cd"] == k).astype(float) for k in markets}, index=df.index)
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
    market_dummies + markets: 시장마다 0/1 컬럼 (markets 순서대로). markets가 없으면 만들지 않는다
    log1p: 이 컬럼들을 log(1 + x)로 (물량처럼 시장마다 자릿수가 다른 값)
    na_indicator: fill='median'일 때 결측 표시 컬럼(_isna)을 붙일지 (실험 코드는 붙이지 않는다)
    무한대(0으로 나눈 비율 등)는 결측으로 바꾼다.
    """

    def __init__(self, features: list[str], fill: str = "none", scale: bool = False, pest_zero: bool = True,
                 market_dummies: bool = True, relative: bool = False, clip: float | None = None, markets=None,
                 log1p: list[str] | None = None, na_indicator: bool = True):
        self.features, self.fill, self.scale, self.pest_zero = features, fill, scale, pest_zero
        self.market_dummies, self.relative, self.clip = market_dummies, relative, clip
        self.markets = list(markets or [])
        self.log1p, self.na_indicator = list(log1p or []), na_indicator

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
        for c in [c for c in self.log1p if c in X]:
            X[c] = np.log1p(X[c])
        return X.replace([np.inf, -np.inf], np.nan)

    def fit(self, df: pd.DataFrame):
        X = self._base(df)
        self.med_ = X.median().fillna(0.0)
        self.na_cols_ = [c for c in X if X[c].isna().any()] if self.fill == "median" and self.na_indicator else []
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
        if self.market_dummies and self.markets:
            X = add_market_dummies(X, df, self.markets)
        return X

    def fit_transform(self, df: pd.DataFrame) -> pd.DataFrame:
        return self.fit(df).transform(df)
