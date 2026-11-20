"""예측 이력: 지난 예측과 실제 주평균을 나란히 보고, 주마다 오차를 MLflow에 기록한다 (REQ-PRD-005, K19).

    python -m farmit_ml.monitor --item 0601                     # 실제 가격이 있는 가장 최근 주를 채점
    python -m farmit_ml.monitor --item 0601 --week 2026-11-09   # 그 주를 다시 채점

- 예측: forecast 테이블의 모든 기준 주 (지난 예측은 지우지 않는다). 접속은 farmit_ml.store와 같은 환경 변수.
- 실제: 피처 CSV(data/weekly_<품목>.csv)의 price_kg. 모델이 맞히려던 정답(target_h)과 같은 정의라 그대로 쓴다
  (등외·하·5등 이하 제외 물량가중, batch/spark/weekly_price.py). DB에서 다시 계산하면 정의가 어긋날 수 있다.
- 결과 1: outputs/monitor_<품목>.csv — 예측 한 행(시장 × 기준 주 × h)마다 실제·오차·80% 구간 안 여부. 실제가 아직 없으면 비어 있다.
- 결과 2: MLflow 실행 "monitor <품목> <주>" (stage=monitor) — 그 주가 대상인 예측들의 h별 NMAE, 기준선(지난주 가격 그대로) NMAE,
  80% 구간 커버리지. docs/ml.md 8.1 운영 감시: 기준선보다 나쁜 시장이 이어지는지, 커버리지가 80%에서 멀어지는지 본다.
"""
from __future__ import annotations

import argparse
import logging

import pandas as pd

from .data import data_hash, load_data
from .metrics import nmae
from .settings import HORIZONS, OUTPUT_DIR, add_config_args, bundle_from_args

log = logging.getLogger("farmit_ml.monitor")

FC_COLS = ["market_cd", "base_week", "horizon", "target_week", "pred_price", "lower80", "upper80",
           "last_week_price", "model_version"]


def read_forecasts(conn, item_code: str) -> pd.DataFrame:
    """forecast 테이블에서 품목의 모든 기준 주 예측."""
    with conn.cursor() as cur:
        cur.execute("SELECT f.market_id, f.base_week, f.horizon, f.target_week, f.pred_price, f.lower80, f.upper80, "
                    "f.last_week_price, f.model_version FROM forecast f JOIN item i ON i.item_id = f.item_id "
                    "WHERE i.at_code = %s", (item_code,))
        rows = cur.fetchall()
    fc = pd.DataFrame(list(rows), columns=FC_COLS)
    for c in ("base_week", "target_week"):
        fc[c] = pd.to_datetime(fc[c])
    for c in ("pred_price", "lower80", "upper80", "last_week_price"):
        fc[c] = pd.to_numeric(fc[c], errors="coerce").astype(float)   # DECIMAL → float, NULL → NaN
    return fc


def this_monday() -> pd.Timestamp:
    """한국 날짜로 이번 주 월요일. 이 주부터는 아직 끝나지 않은 주다."""
    today = pd.Timestamp.now(tz="Asia/Seoul").normalize().tz_localize(None)
    return today - pd.Timedelta(days=today.weekday())


def compare(fc: pd.DataFrame, weekly: pd.DataFrame, until=None) -> pd.DataFrame:
    """예측 행마다 대상 주의 실제 주평균(price_kg)을 붙인다. 실제가 없는 행(아직 안 온 주, 거래 없음)은 actual이 비어 있다.

    until(월요일)부터의 주는 실제로 치지 않는다. 주중에 수집된 피처 CSV에는 진행 중인 주의 며칠치 가격이 들어 있다.
    """
    weekly = weekly if until is None else weekly[weekly["week"] < pd.Timestamp(until)]
    actual = weekly[["market_cd", "market_nm", "week", "price_kg"]].rename(
        columns={"week": "target_week", "price_kg": "actual"})
    out = fc.merge(actual, on=["market_cd", "target_week"], how="left")
    out["actual"] = out["actual"].round(1)   # 예측값과 같은 자리수 (원/kg 소수 첫째 자리)
    out["error"] = (out["pred_price"] - out["actual"]).round(1)
    out["abs_pct_error"] = (out["error"].abs() / out["actual"] * 100).round(2)
    in_80 = (out["lower80"] <= out["actual"]) & (out["actual"] <= out["upper80"])
    out["in_80"] = in_80.astype(float).where(out["actual"].notna())   # 1·0, 실제가 없으면 비움
    return out.sort_values(["target_week", "market_cd", "horizon"]).reset_index(drop=True)


def latest_week(cmp: pd.DataFrame):
    """실제 가격이 붙은 가장 최근 대상 주. 없으면 None (첫 예측의 대상 주가 아직 안 끝났다)."""
    done = cmp.loc[cmp["actual"].notna(), "target_week"]
    return done.max() if not done.empty else None


def week_metrics(cmp: pd.DataFrame, week) -> dict:
    """대상 주 하나의 채점. 기준선 B1 = 기준 시점 지난주 가격 그대로 (last_week_price)."""
    w = cmp[(cmp["target_week"] == pd.Timestamp(week)) & cmp["actual"].notna()]
    m = {"n_rows": len(w), "n_markets": w["market_cd"].nunique()}
    if w.empty:
        return m
    m["nmae"] = nmae(w["actual"], w["pred_price"])
    m["base_nmae"] = nmae(w["actual"], w["last_week_price"])
    m["coverage80"] = float(w["in_80"].mean())
    for h in HORIZONS:
        wh = w[w["horizon"] == h]
        if not wh.empty:
            m[f"nmae_h{h}"] = nmae(wh["actual"], wh["pred_price"])
            m[f"base_nmae_h{h}"] = nmae(wh["actual"], wh["last_week_price"])
    return m


def main(argv=None):
    ap = argparse.ArgumentParser(description="지난 예측 vs 실제 주평균 비교와 주간 오차 기록")
    add_config_args(ap)
    ap.add_argument("--week", help="채점할 대상 주 월요일 (YYYY-MM-DD). 없으면 실제 가격이 있는 가장 최근 주")
    ap.add_argument("--no-mlflow", action="store_true", help="MLflow 기록을 하지 않는다")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    b, data_path = bundle_from_args(a)
    from . import store
    conn = store.connect()
    try:
        fc = read_forecasts(conn, b.item_code)
    finally:
        conn.close()
    if fc.empty:
        log.info("%s 예측이 아직 없다. 채점하지 않는다", b.item_code)
        return

    # 실제는 모든 시장에서 찾는다 (serve 시장이 바뀌어도 지난 예측을 채점). 끝난 주만 실제로 친다
    cmp = compare(fc, load_data(data_path), until=this_monday())
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"monitor_{b.item_code}.csv"
    cmp.assign(base_week=cmp["base_week"].dt.date, target_week=cmp["target_week"].dt.date) \
       .to_csv(out, index=False, encoding="utf-8-sig")
    log.info("예측 %d행 중 실제가 있는 행 %d → %s", len(cmp), int(cmp["actual"].notna().sum()), out)

    week = pd.Timestamp(a.week) if a.week else latest_week(cmp)
    if week is None:
        log.info("실제 가격이 나온 대상 주가 아직 없다. 채점하지 않는다")
        return
    m = week_metrics(cmp, week)
    if not m["n_rows"]:
        log.info("%s 대상 주의 예측·실제가 없다. 채점하지 않는다", week.date())
        return
    log.info("%s 대상 주 채점: %s", week.date(), {k: round(v, 4) for k, v in m.items()})
    if not a.no_mlflow:
        from .tracking import log_run
        log_run(f"monitor {b.item_code} {week.date()}", "monitor", b, data_hash(data_path), metrics=m,
                params={"target_week": str(week.date())}, artifacts=[out])


if __name__ == "__main__":
    main()
