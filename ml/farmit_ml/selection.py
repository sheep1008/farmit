"""학습·노출 시장 선별과 OOF·테스트 평가 (docs/ml.md 7.4, 8.3 "분기 재검증"). 설정을 바꾸거나 분기마다 실행한다.

    python -m farmit_ml.selection --item 0601

1. 학습 시장: 학습 기간(selection.train_end까지)만 보고, 제철 주 커버리지와 주당 거래일 수로 고른다.
2. 2021~2024 OOF(확장 윈도우): 설정의 앙상블로 연도마다 다시 학습해 예측한다.
3. 노출 시장: OOF에서 기준선(B1·B2 중 그 시장 OOF에서 나은 쪽)을 min_wins개 연도 이상 이긴 시장.
4. 테스트(2025-01~): 위 선택을 고정한 뒤 한 번만 본다.
결과: config/<품목>/markets.json(train·serve), outputs/select_<품목>_<버전>.csv(시장별 표),
      outputs/oof_<품목>_<버전>.csv(OOF 예측, 80% 구간 계산용), outputs/test_<품목>_<버전>.csv(테스트 예측,
      구간 커버리지 확인용), MLflow(stage=select). 구간은 다음에 python -m farmit_ml.intervals로 만든다.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import logging
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from . import ensemble
from .data import TEST_START, check_columns, data_hash, load_data
from .metrics import baseline_pred, nmae
from .settings import HORIZONS, OUTPUT_DIR, Bundle, config_dir, load_bundle

log = logging.getLogger("farmit_ml.selection")
BASELINES = ("B1_last", "B2_ma4")


def hmean(d: pd.DataFrame, P: np.ndarray) -> float:
    """h1~h4 NMAE 평균."""
    return float(np.mean([nmae(d[f"target_h{h}"], P[:, j]) for j, h in enumerate(HORIZONS)]))


def base_matrix(d: pd.DataFrame, name: str) -> np.ndarray:
    return np.column_stack([baseline_pred(d, name)] * len(HORIZONS))


def pick_train_markets(df: pd.DataFrame, sel: dict) -> pd.DataFrame:
    """학습 기간만 보고 학습 시장을 고른다 (실험 dataset.pick_markets와 같은 커버리지 기준).

    실험의 "주당 거래 20건 이상"은 거래 건수(n_records)가 정산 테이블에 없어 "주당 거래일 수 중앙값"으로 바꿨다.
    """
    tr = df[df["week"] <= sel["train_end"]]
    nq = tr.drop_duplicates("week").set_index("week")["nat_qty"]
    n_weeks = int((nq >= 0.1 * nq.median()).sum())   # 분모: 전국에서 제철로 거래된 주
    s = tr.groupby(["market_cd", "market_nm"]).agg(weeks=("week", "nunique"),
                                                   trade_days=("n_trade_days", "median")).reset_index()
    s["coverage"] = s["weeks"] / n_weeks
    s["train"] = (s["coverage"] >= sel["min_coverage"]) & (s["trade_days"] >= sel["min_trade_days"])
    return s


def oof_predict(b: Bundle, df: pd.DataFrame, years) -> tuple[pd.DataFrame, np.ndarray]:
    """연도별 확장 윈도우 OOF. 반환: (fold 열이 붙은 검증 행, 예측 N×4)."""
    parts, preds = [], []
    for y in years:
        trn = df[df["target_week_h4"] <= f"{y - 1}-12-31"]
        val = df[(df["week"] >= f"{y}-01-01") & (df["target_week_h4"] <= f"{y}-12-31")]
        wide, _ = ensemble.predict(b, df, trn, val)
        preds.append(wide[[f"p{h}" for h in HORIZONS]].values)
        parts.append(val.assign(fold=y))
        log.info("OOF %d: %d행 NMAE %.4f", y, len(val), hmean(val, preds[-1]))
    return pd.concat(parts, ignore_index=True), np.vstack(preds)


def market_table(V: pd.DataFrame, P: np.ndarray, min_wins: int) -> pd.DataFrame:
    """시장별 OOF: 연도별 NMAE 평균, 기준선(B1·B2 중 OOF 평균이 나은 쪽), 기준선을 이긴 연도 수, 노출 여부."""
    rows = []
    for mc, g in V.groupby("market_cd"):
        yr = {y: (hmean(gy, P[gy.index.values]), {n: hmean(gy, base_matrix(gy, n)) for n in BASELINES})
              for y, gy in g.groupby("fold")}
        bname = min(BASELINES, key=lambda n: np.mean([v[1][n] for v in yr.values()]))
        m, base = np.mean([v[0] for v in yr.values()]), np.mean([v[1][bname] for v in yr.values()])
        rows.append({"market_cd": mc, "market_nm": g["market_nm"].iloc[0], "oof_nmae": m, "oof_base": base,
                     "oof_gain": 1 - m / base, "base_name": bname, "years": len(yr),
                     "wins": int(sum(v[0] < v[1][bname] for v in yr.values()))})
    t = pd.DataFrame(rows)
    t["serve"] = t["wins"] >= min(min_wins, t["years"].max())   # 연도가 더 적으면 전부 이겨야 한다
    return t


def test_table(b: Bundle, df: pd.DataFrame, mt: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """2024년까지로 학습해 테스트(2025-01~)를 한 번 예측. 시장별 기준선은 OOF에서 고른 쪽."""
    trn = df[df["target_week_h4"] <= pd.Timestamp(TEST_START) - pd.Timedelta(days=1)]
    te = df[df["week"] >= TEST_START]
    wide, _ = ensemble.predict(b, df, trn, te)
    P = wide[[f"p{h}" for h in HORIZONS]].values
    te = te.reset_index(drop=True)
    bn = mt.set_index("market_cd")["base_name"]
    rows = [{"market_cd": mc, "test_nmae": hmean(g, P[g.index.values]),
             "test_base": hmean(g, base_matrix(g, bn[mc]))} for mc, g in te.groupby("market_cd")]
    t = pd.DataFrame(rows)
    t["test_gain"] = 1 - t["test_nmae"] / t["test_base"]
    b1, b2 = hmean(te, base_matrix(te, "B1_last")), hmean(te, base_matrix(te, "B2_ma4"))
    overall = {"test_nmae": hmean(te, P), "test_b1": b1, "test_b2": b2,
               **{f"test_nmae_h{h}": nmae(te[f"target_h{h}"], P[:, j]) for j, h in enumerate(HORIZONS)}}
    overall["test_gain"] = 1 - overall["test_nmae"] / min(b1, b2)
    return t, overall, pred_frame(te, P)


def pred_frame(d: pd.DataFrame, P: np.ndarray) -> pd.DataFrame:
    """예측 저장 형식 (80% 구간 계산·커버리지 확인용, farmit_ml.intervals가 읽는다)."""
    cols = ["market_cd", "market_nm", "week"] + (["fold"] if "fold" in d else []) + ["price_kg"]
    return d[cols + [f"target_h{h}" for h in HORIZONS]].assign(**{f"p{h}": P[:, j] for j, h in enumerate(HORIZONS)})


def main(argv=None):
    ap = argparse.ArgumentParser(description="학습·노출 시장 선별, OOF·테스트 평가")
    ap.add_argument("--item", help="품목 코드 (config/<품목>/)")
    ap.add_argument("--config", help="설정 폴더. --item보다 우선")
    ap.add_argument("--data", help="주간 데이터셋 CSV. 없으면 설정의 data_file")
    ap.add_argument("--dry-run", action="store_true", help="markets.json을 쓰지 않는다")
    ap.add_argument("--no-mlflow", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    cdir = config_dir(a.item, a.config)
    b = load_bundle(cdir)
    sel = b.selection
    data_path = Path(a.data) if a.data else b.data_path
    full = load_data(data_path)

    pick = pick_train_markets(full, sel)
    train = pick[pick["train"]].sort_values("market_cd")
    log.info("학습 시장 %d/%d (빠짐: %s)", len(train), len(pick), pick.loc[~pick["train"], "market_nm"].tolist())
    b = dataclasses.replace(b, markets=dict(zip(train["market_cd"], train["market_nm"])),
                            serve_markets=list(train["market_cd"]))
    df = load_data(data_path, b.markets)
    check_columns(df, b)

    years = tuple(sel["oof_years"])
    V, P = oof_predict(b, df, years)
    yr = {int(y): hmean(g, P[g.index.values]) for y, g in V.groupby("fold")}
    oof_mean = float(np.mean(list(yr.values())))
    mt = market_table(V, P, sel["min_wins"])
    serve = sorted(mt.loc[mt["serve"], "market_cd"])
    log.info("OOF %.4f %s | 노출 시장 %d/%d", oof_mean, {k: round(v, 4) for k, v in yr.items()}, len(serve), len(mt))

    # 선택을 고정한 뒤 테스트를 한 번 본다
    tt, overall, test_pred = test_table(b, df, mt)
    res = pick.merge(mt.drop(columns="market_nm"), on="market_cd", how="left").merge(tt, on="market_cd", how="left")
    srv = res[res["serve"] == True]  # noqa: E712 (NaN은 False)
    summary = {
        "oof_nmae": oof_mean, **{f"oof_nmae_{y}": v for y, v in yr.items()}, **overall,
        "n_markets_data": len(pick), "n_train": len(train), "n_serve": len(serve),
        "serve_test_win_rate": float((srv["test_gain"] > 0).mean()),
        "serve_test_gain_median": float(srv["test_gain"].median()),
        "train_test_win_rate": float((res.loc[res["train"], "test_gain"] > 0).mean()),
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = f"{b.item_code}_{b.version}"
    table_out, oof_out, test_out = (OUTPUT_DIR / f"{k}_{tag}.csv" for k in ("select", "oof", "test"))
    res.round(5).to_csv(table_out, index=False, encoding="utf-8-sig")
    pred_frame(V, P).to_csv(oof_out, index=False, encoding="utf-8-sig")
    test_pred.to_csv(test_out, index=False, encoding="utf-8-sig")

    pd.set_option("display.width", 200)
    print(res[["market_cd", "market_nm", "coverage", "trade_days", "train", "oof_nmae", "oof_gain", "base_name",
               "wins", "serve", "test_nmae", "test_gain"]].round(4).to_string(index=False))
    print(json.dumps({k: round(v, 4) if isinstance(v, float) else v for k, v in summary.items()}, ensure_ascii=False))

    if not a.dry_run:
        markets = {
            "train": b.markets, "serve": serve,
            "selection": f"{date.today()} farmit_ml.selection, 데이터 {data_path.name}. {sel['rule']}",
            "summary": {k: round(v, 4) if isinstance(v, float) else v for k, v in summary.items()},
        }
        (cdir / "markets.json").write_text(json.dumps(markets, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        log.info("저장 → %s", cdir / "markets.json")
    if not a.no_mlflow:
        from .tracking import log_run
        log_run(f"select {b.item_code} {b.version}", "select", dataclasses.replace(b, serve_markets=serve),
                data_hash(data_path), metrics=summary, artifacts=[table_out, oof_out, test_out])


if __name__ == "__main__":
    main()
