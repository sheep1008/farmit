"""주간 예측 (REQ-PRD-001~004). 매주 월요일 아침 실행한다.

    python -m farmit_ml.forecast                         # 데이터의 마지막 주 기준
    python -m farmit_ml.forecast --base-week 2026-10-19  # 지난 주차 다시 예측(백필)

참고 저장소 08 노트북 G절과 같은 방식이다: 그 시점까지 정답이 있는 모든 행으로 다시 학습하고 예측한다.
결과는 forecast 테이블과 같은 모양(시장 × h 한 행)으로 outputs/forecast_<base_week>.csv에 저장한다.
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime

import numpy as np
import pandas as pd

from . import ensemble
from .data import as_of, check_columns, data_hash, load_data
from .settings import DATA_PATH, HORIZONS, MARKETS, OUTPUT_DIR, Bundle, load_bundle

log = logging.getLogger("farmit_ml.forecast")

OUTPUT_COLS = ["item_code", "market_cd", "market_nm", "base_week", "horizon", "target_week", "pred_price",
               "lower80", "upper80", "last_week_price", "near_holiday", "model_version", "created_at"]
HOLIDAY_DAYS = 21  # REQ-PRD-003: 대상 주가 명절 3주 이내면 주의 문구


def run(df: pd.DataFrame, b: Bundle, base_week=None, model_version: str | None = None) -> pd.DataFrame:
    """df(전체 주간 데이터)로 base_week 예측을 만든다. base_week가 없으면 마지막 pred_date."""
    base = pd.Timestamp(base_week) if base_week else df["pred_date"].max()
    hist = as_of(df, base)
    now = hist[hist["pred_date"] == base]
    if now.empty:
        raise ValueError(f"{base.date()} 예측에 쓸 행(pred_date = {base.date()})이 데이터에 없다")
    missing = sorted(set(MARKETS) - set(now["market_cd"]))
    if missing:
        log.warning("이번 주 데이터가 없어 예측하지 못한 시장: %s", missing)
    trn = hist[hist["pred_date"] < base]

    wide, _ = ensemble.predict(b, hist, trn, now)
    created = datetime.now().isoformat(timespec="seconds")
    rows = []
    for (_, r), (_, w) in zip(now.iterrows(), wide.iterrows()):
        for h in HORIZONS:
            p = float(w[f"p{h}"])
            lo, hi = ensemble.interval(b, np.array(p), h)
            near = bool(r[f"hol_in_target_h{h}"] == 1 or abs(r[f"hol_offset_h{h}"]) <= HOLIDAY_DAYS)
            rows.append({
                "item_code": b.item_code, "market_cd": r["market_cd"], "market_nm": r["market_nm"],
                "base_week": base.date(), "horizon": h, "target_week": (r["week"] + pd.Timedelta(weeks=h)).date(),
                "pred_price": round(p, 1), "lower80": round(float(lo), 1), "upper80": round(float(hi), 1),
                "last_week_price": round(float(r["price_kg"]), 1), "near_holiday": near,
                "model_version": model_version or b.version, "created_at": created,
            })
    return pd.DataFrame(rows, columns=OUTPUT_COLS)


def main(argv=None):
    ap = argparse.ArgumentParser(description="사과 4개 시장 h1~h4 주간 가격 예측")
    ap.add_argument("--data", default=str(DATA_PATH), help="주간 데이터셋 CSV")
    ap.add_argument("--base-week", help="예측 기준 월요일 (YYYY-MM-DD). 없으면 데이터의 마지막 주")
    ap.add_argument("--out", help="결과 CSV 경로. 없으면 outputs/forecast_<base_week>.csv")
    ap.add_argument("--skip", nargs="*", default=[], help="뺄 구성 모델 이름 (예: LSTM). 나머지 가중치로 다시 나눈다")
    ap.add_argument("--no-mlflow", action="store_true", help="MLflow 기록을 하지 않는다")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    b = load_bundle()
    for k in a.skip:
        b.weights.pop(k)
    df = load_data(a.data)
    check_columns(df, b.tree_features + b.lin_features)
    dh = data_hash(a.data)

    version = b.version + "".join(f"-no{k}" for k in a.skip)   # 구성 모델을 뺀 예측은 버전 이름에 남긴다
    fc = run(df, b, a.base_week, model_version=version)
    base = fc["base_week"].iloc[0]
    out = a.out or OUTPUT_DIR / f"forecast_{base}.csv"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not a.no_mlflow:
        from .tracking import log_run
        fc.to_csv(out, index=False, encoding="utf-8-sig")
        run_id = log_run(f"forecast {base}", "forecast", b, dh, params={"base_week": str(base), "skip": a.skip},
                         artifacts=[out])
        fc["model_version"] = f"{version}-{run_id[:8]}"
    fc.to_csv(out, index=False, encoding="utf-8-sig")
    log.info("%s 기준 %d행 저장 → %s", base, len(fc), out)
    print(fc.to_string(index=False))


if __name__ == "__main__":
    main()
