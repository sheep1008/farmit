"""주간 예측 (REQ-PRD-001~004). 매주 월요일 아침 실행한다.

    python -m farmit_ml.forecast --item 0601                         # 데이터의 마지막 주 기준
    python -m farmit_ml.forecast --item 0601 --base-week 2026-10-19  # 지난 주차 다시 예측(백필)
    python -m farmit_ml.forecast --config config/0601_v3 --data data/apple_weekly.csv   # 이전 버전 설정

참고 저장소 08 노트북 G절과 같은 방식이다: 그 시점까지 정답이 있는 모든 행으로 다시 학습하고 예측한다.
학습은 markets.json의 train 시장 전부로 하고, 결과는 serve 시장만 forecast 테이블과 같은 모양(시장 × h 한 행)으로
outputs/forecast_<품목>_<base_week>.csv에 저장한다.
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import ensemble
from .data import as_of, check_columns, data_hash, load_data
from .settings import HORIZONS, OUTPUT_DIR, Bundle, add_config_args, bundle_from_args

log = logging.getLogger("farmit_ml.forecast")

OUTPUT_COLS = ["item_code", "market_cd", "market_nm", "base_week", "horizon", "target_week", "pred_price",
               "lower80", "upper80", "last_week_price", "near_holiday", "model_version", "created_at"]
HOLIDAY_DAYS = 21  # REQ-PRD-003: 대상 주가 명절 3주 이내면 주의 문구


def run(df: pd.DataFrame, b: Bundle, base_week=None, model_version: str | None = None) -> pd.DataFrame:
    """df(학습 시장의 주간 데이터)로 base_week 예측을 만든다. base_week가 없으면 마지막 pred_date.

    학습 시장 전부를 예측한 뒤(후처리가 다른 시장 예측을 쓴다) serve 시장 행만 돌려준다.
    """
    base = pd.Timestamp(base_week) if base_week else df["pred_date"].max()
    hist = as_of(df, base)
    now = hist[hist["pred_date"] == base]
    if now.empty:
        raise ValueError(f"{base.date()} 예측에 쓸 행(pred_date = {base.date()})이 데이터에 없다")
    missing = sorted(set(b.serve_markets) - set(now["market_cd"]))
    if missing:
        log.warning("이번 주 데이터가 없어 예측하지 못한 시장: %s", missing)
    trn = hist[hist["pred_date"] < base]

    wide, _ = ensemble.predict(b, hist, trn, now)
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")   # DB에는 UTC로 저장한다
    rows = []
    for (_, r), (_, w) in zip(now.iterrows(), wide.iterrows()):
        if r["market_cd"] not in b.serve_markets:
            continue
        for h in HORIZONS:
            p = float(w[f"p{h}"])
            lo, hi = ensemble.interval(b, np.array(p), h, r["market_cd"])
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
    ap = argparse.ArgumentParser(description="품목별 serve 시장 h1~h4 주간 가격 예측")
    add_config_args(ap)
    ap.add_argument("--base-week", help="예측 기준 월요일 (YYYY-MM-DD). 없으면 데이터의 마지막 주")
    ap.add_argument("--out", help="결과 CSV 경로. 없으면 outputs/forecast_<품목>_<base_week>.csv")
    ap.add_argument("--no-mlflow", action="store_true", help="MLflow 기록을 하지 않는다")
    ap.add_argument("--to-db", action="store_true", help="결과를 forecast 테이블에 UPSERT한다 (farmit_ml.store, DB 환경 변수 필요)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    b, data_path = bundle_from_args(a)
    df = load_data(data_path, b.markets)
    check_columns(df, b)
    dh = data_hash(data_path)

    version = b.version + "".join(f"-no{k}" for k in a.skip)   # 구성 모델을 뺀 예측은 버전 이름에 남긴다
    fc = run(df, b, a.base_week, model_version=version)
    if fc.empty:
        raise SystemExit("serve 시장 중 이번 주 데이터가 있는 시장이 없어 예측을 만들지 못했다")
    base = fc["base_week"].iloc[0]
    out = a.out or OUTPUT_DIR / f"forecast_{b.item_code}_{base}.csv"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not a.no_mlflow:
        from .tracking import log_run
        fc.to_csv(out, index=False, encoding="utf-8-sig")
        run_id = log_run(f"forecast {b.item_code} {base}", "forecast", b, dh, params={"base_week": str(base), "skip": a.skip},
                         artifacts=[out])
        fc["model_version"] = f"{version}-{run_id[:8]}"
    fc.to_csv(out, index=False, encoding="utf-8-sig")
    log.info("%s 기준 %d행 저장 → %s", base, len(fc), out)
    print(fc.to_string(index=False))
    if a.to_db:
        from . import store
        conn = store.connect()
        try:
            log.info("forecast 테이블 UPSERT %d행", store.save(conn, store.read_csv(out)))
        finally:
            conn.close()


if __name__ == "__main__":
    main()
