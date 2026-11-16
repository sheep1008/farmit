"""테스트 평가: 2024년까지로 학습하고 2025-01 이후(테스트)를 예측해 지표를 낸다.

    python -m farmit_ml.evaluate --item 0601
    python -m farmit_ml.evaluate --config config/0601_v3 --data data/apple_weekly.csv   # v3 재현

참고 저장소 08 노트북 F절과 같은 계산이다. 옮긴 코드가 원래 결과(v3 + 후처리 NMAE 0.0984)를
재현하는지 확인하거나, config를 바꾼 뒤 비교할 때 쓴다. 테스트를 여러 번 보고 모델을 고르면 안 된다
(모델 선택은 2021~2024 OOF로 한다. docs/ml.md "평가 규칙").
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from . import ensemble
from .data import TEST_START, check_columns, data_hash, load_data
from .metrics import baseline_pred, dir_acc, mae, nmae
from .settings import HORIZONS, OUTPUT_DIR, add_config_args, bundle_from_args


def scores(te: pd.DataFrame, P: np.ndarray) -> dict:
    r = {f"nmae_h{h}": nmae(te[f"target_h{h}"], P[:, j]) for j, h in enumerate(HORIZONS)}
    r["nmae"] = float(np.mean([r[f"nmae_h{h}"] for h in HORIZONS]))
    r["mae"] = float(np.mean([mae(te[f"target_h{h}"], P[:, j]) for j, h in enumerate(HORIZONS)]))
    r["dir_acc"] = float(np.mean([dir_acc(te[f"target_h{h}"], P[:, j], te["price_kg"]) for j, h in enumerate(HORIZONS)]))
    return r


def main(argv=None):
    ap = argparse.ArgumentParser(description="테스트 구간(2025-01~) 평가")
    add_config_args(ap)
    ap.add_argument("--no-mlflow", action="store_true")
    a = ap.parse_args(argv)

    b, data_path = bundle_from_args(a)
    df = load_data(data_path, b.markets)
    check_columns(df, b)
    trn = df[df["target_week_h4"] <= pd.Timestamp(TEST_START) - pd.Timedelta(days=1)]
    te = df[df["week"] >= TEST_START]

    wide_raw, parts = ensemble.predict(b, df, trn, te, use_postprocess=False)
    wide = ensemble.postprocess.apply(wide_raw, df, b.pp_weights, list(b.markets), b.pp_n_weeks)
    cols = [f"p{h}" for h in HORIZONS]
    table = {
        "B1 직전값": scores(te, np.column_stack([baseline_pred(te, "B1_last")] * len(HORIZONS))),
        "B2 4주MA": scores(te, np.column_stack([baseline_pred(te, "B2_ma4")] * len(HORIZONS))),
        **{k: scores(te, p) for k, p in parts.items()},
        f"{b.version} 앙상블": scores(te, wide_raw[cols].values),
        f"{b.version} 앙상블 + 후처리": scores(te, wide[cols].values),
    }
    res = pd.DataFrame(table).T
    line = res.loc[["B1 직전값", "B2 4주MA"], "nmae"].min()
    res["기준선 대비 개선"] = 1 - res["nmae"] / line
    pd.set_option("display.width", 200)
    print(res.round(4).to_string())

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"test_results_{b.item_code}_{b.version}.csv"
    res.round(5).to_csv(out, encoding="utf-8-sig")
    if not a.no_mlflow:
        from .tracking import log_run
        final = table[f"{b.version} 앙상블 + 후처리"]
        log_run(f"evaluate {b.item_code} {b.version}", "evaluate", b, data_hash(data_path),
                metrics={f"test_{k}": v for k, v in final.items()}, params={"skip": a.skip}, artifacts=[out])


if __name__ == "__main__":
    main()
