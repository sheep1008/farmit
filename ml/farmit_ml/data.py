"""주간 데이터셋 로드·검사·분할.

입력은 시장 × 주 한 행인 CSV다(컬럼 정의는 docs/ml.md "입력 데이터"). 지금은 참고 저장소의
scripts/build_dataset.py가 만든 apple_weekly.csv를 그대로 쓴다.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from .settings import DATA_PATH, HORIZONS

KEY_COLS = ["market_cd", "market_nm", "week", "pred_date", "price_kg", "price_ma4"]
TARGET_COLS = [f"target_h{h}" for h in HORIZONS] + [f"target_week_h{h}" for h in HORIZONS]
HOLIDAY_COLS = [f"{b}_h{h}" for b in ("hol_offset", "hol_in_target") for h in HORIZONS]

TUNE_YEARS = (2021, 2022, 2023)          # 하이퍼파라미터 조정용 (학습 구간 안)
SELECT_YEARS = (2021, 2022, 2023, 2024)  # 최종 모델·앙상블 선택용 OOF
TEST_START = "2025-01-01"                # 테스트 구간 시작. 최종 평가에 한 번만 쓴다


def load_data(path: Path | str = DATA_PATH) -> pd.DataFrame:
    """시장·주 순으로 정렬하고 인덱스를 0..n-1로 맞춘다 (LSTM 시퀀스가 위치 인덱스를 쓴다)."""
    df = pd.read_csv(path, dtype={"market_cd": str},
                     parse_dates=["week", "pred_date"] + [f"target_week_h{h}" for h in HORIZONS])
    return df.sort_values(["market_cd", "week"]).reset_index(drop=True)


def check_columns(df: pd.DataFrame, features: list[str]) -> None:
    """예측에 필요한 컬럼이 모두 있는지 확인한다. 없으면 무엇이 빠졌는지 알려 준다."""
    need = set(KEY_COLS) | set(TARGET_COLS) | set(HOLIDAY_COLS) | set(features)
    missing = sorted(need - set(df.columns))
    if missing:
        raise ValueError(f"데이터셋에 필요한 컬럼이 없다 ({len(missing)}개): {missing[:20]}")


def data_hash(path: Path | str = DATA_PATH) -> str:
    return hashlib.md5(Path(path).read_bytes()).hexdigest()[:10]


def as_of(df: pd.DataFrame, base_week) -> pd.DataFrame:
    """base_week(예측하는 월요일) 아침에 알 수 있었던 데이터만 남긴다.

    - pred_date가 base_week 이후인 행은 뺀다.
    - 타깃 주가 base_week 이후면(아직 끝나지 않은 주) 타깃을 NaN으로 지운다.
    지난 주차를 다시 예측(백필)해도 미래 정보가 섞이지 않는다. 인덱스는 0..n-1로 다시 매긴다.
    """
    base = pd.Timestamp(base_week)
    out = df[df["pred_date"] <= base].copy()
    for h in HORIZONS:
        out.loc[out[f"target_week_h{h}"] >= base, f"target_h{h}"] = float("nan")
    return out.reset_index(drop=True)


def split(df: pd.DataFrame):
    """학습(타깃 ≤2023) / 검증 2024 / 테스트 2025~. 경계에서 타깃이 겹치지 않게 target_week_h4로 자른다."""
    tr = df[df["target_week_h4"] <= "2023-12-31"]
    va = df[(df["week"] >= "2024-01-01") & (df["target_week_h4"] <= "2024-12-31")]
    te = df[df["week"] >= TEST_START]
    return tr, va, te


def cv_folds(df: pd.DataFrame, years=TUNE_YEARS):
    """확장 윈도우 교차검증. fold마다 (연도, 학습, 검증) — 검증 연도 직전까지 학습."""
    for y in years:
        trn = df[df["target_week_h4"] <= f"{y - 1}-12-31"]
        val = df[(df["week"] >= f"{y}-01-01") & (df["target_week_h4"] <= f"{y}-12-31")]
        yield y, trn, val
