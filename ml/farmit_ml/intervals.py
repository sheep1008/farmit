"""80% 예측 구간 (REQ-PRD-002): OOF 상대잔차의 시장 × h별 분위수. farmit_ml.selection 다음에 실행한다.

    python -m farmit_ml.intervals --item 0601

- 상대잔차 r = (실제 − 예측) / 예측. 하한 = 예측 × (1 + q_lo), 상한 = 예측 × (1 + q_hi) (v3와 같은 꼴).
- 분위수는 2021~2024 OOF(outputs/oof_<품목>_<버전>.csv)로만 만든다. 테스트(outputs/test_…)는 커버리지 확인에만 쓴다.
- 시장 × h 잔차가 min_n개 미만이면 전체 시장을 합친 분위수("*")를 쓴다.
- 구간이 예측값을 꼭 포함하게 q_lo ≤ 0 ≤ q_hi로 자른다.
결과: config/<품목>/intervals.json, outputs/coverage_<품목>_<버전>.csv, MLflow(stage=interval).
"""
from __future__ import annotations

import argparse
import json
from datetime import date

import numpy as np
import pandas as pd

from .settings import HORIZONS, OUTPUT_DIR, config_dir, load_bundle

POOLED = "*"   # 시장 구분 없이 합친 분위수 (잔차가 적은 시장·새 시장에 쓴다)


def rel_resid(d: pd.DataFrame, h: int) -> pd.Series:
    return ((d[f"target_h{h}"] - d[f"p{h}"]) / d[f"p{h}"]).dropna()


def _q(r: pd.Series, level: float) -> list[float]:
    a = (1 - level) / 2
    lo, hi = r.quantile(a), r.quantile(1 - a)
    return [round(float(min(lo, 0.0)), 5), round(float(max(hi, 0.0)), 5)]


def quantiles(oof: pd.DataFrame, level: float = 0.8, min_n: int = 100) -> dict:
    """{시장 또는 "*": {h: [q_lo, q_hi]}}. 잔차가 min_n개 미만인 시장 × h는 넣지 않는다 (→ "*" 사용)."""
    out = {POOLED: {str(h): _q(rel_resid(oof, h), level) for h in HORIZONS}}
    for mc, g in oof.groupby("market_cd"):
        qs = {str(h): _q(r, level) for h in HORIZONS if len(r := rel_resid(g, h)) >= min_n}
        if qs:
            out[str(mc)] = qs
    return out


def bounds(q: dict, market: str, h: int) -> tuple[float, float]:
    lo, hi = q.get(market, {}).get(str(h)) or q[POOLED][str(h)]
    return lo, hi


def coverage(pred: pd.DataFrame, q: dict) -> pd.DataFrame:
    """시장 × h별로 실제값이 구간 안에 든 비율과 구간 폭(상한−하한)/예측."""
    rows = []
    for mc, g in pred.groupby("market_cd"):
        for h in HORIZONS:
            d = g[g[f"target_h{h}"].notna()]
            lo, hi = bounds(q, str(mc), h)
            y, p = d[f"target_h{h}"], d[f"p{h}"]
            inside = (y >= p * (1 + lo)) & (y <= p * (1 + hi))
            rows.append({"market_cd": mc, "market_nm": g["market_nm"].iloc[0], "h": h, "n": len(d),
                         "covered": int(inside.sum()), "width": hi - lo, "own": str(mc) in q})
    return pd.DataFrame(rows)


def summarize(cov: pd.DataFrame) -> dict:
    s = {"coverage": cov["covered"].sum() / cov["n"].sum(), "width_mean": float(cov["width"].mean())}
    for h, g in cov.groupby("h"):
        s[f"coverage_h{h}"] = g["covered"].sum() / g["n"].sum()
    by_m = cov.groupby("market_cd")[["covered", "n"]].sum()
    r = by_m["covered"] / by_m["n"]
    s.update({"market_coverage_min": float(r.min()), "market_coverage_max": float(r.max()),
              "market_coverage_mad": float((r - 0.8).abs().mean()),   # 시장별 커버리지가 80%에서 평균 얼마나 벗어나나
              "markets_70_90": int(((r >= 0.7) & (r <= 0.9)).sum()), "n_markets": len(r)})
    return {k: float(v) for k, v in s.items()}


def main(argv=None):
    ap = argparse.ArgumentParser(description="OOF 잔차로 시장 × h별 80% 구간을 만들고 테스트 커버리지를 확인한다")
    ap.add_argument("--item")
    ap.add_argument("--config")
    ap.add_argument("--min-n", type=int, default=100, help="시장 × h 잔차가 이보다 적으면 전체 분위수를 쓴다")
    ap.add_argument("--dry-run", action="store_true", help="intervals.json을 쓰지 않는다")
    ap.add_argument("--no-mlflow", action="store_true")
    a = ap.parse_args(argv)

    cdir = config_dir(a.item, a.config)
    b = load_bundle(cdir)
    tag = f"{b.item_code}_{b.version}"
    oof = pd.read_csv(OUTPUT_DIR / f"oof_{tag}.csv", dtype={"market_cd": str})
    test = pd.read_csv(OUTPUT_DIR / f"test_{tag}.csv", dtype={"market_cd": str})

    q = quantiles(oof, b.interval_level, a.min_n)
    pooled_only = {POOLED: q[POOLED]}
    cov, cov_pooled = coverage(test, q), coverage(test, pooled_only)
    oof_cov = summarize(coverage(oof, q))
    s, sp = summarize(cov), summarize(cov_pooled)

    pd.set_option("display.width", 200)
    by_m = cov.groupby(["market_cd", "market_nm"]).agg(covered=("covered", "sum"), n=("n", "sum"),
                                                       width=("width", "mean")).reset_index()
    by_m["coverage"] = by_m["covered"] / by_m["n"]
    print(by_m.round(3).to_string(index=False))
    print("시장별 구간 (테스트):", json.dumps({k: round(v, 4) for k, v in s.items()}, ensure_ascii=False))
    print("전체 한 구간 (테스트):", json.dumps({k: round(v, 4) for k, v in sp.items()}, ensure_ascii=False))
    print("시장별 구간 (OOF, 자기 자신):", round(oof_cov["coverage"], 4))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"coverage_{tag}.csv"
    cov.to_csv(out, index=False, encoding="utf-8-sig")
    if not a.dry_run:
        body = {"level": b.interval_level,
                "method": f"{date.today()} farmit_ml.intervals: {tag} 2021~2024 OOF 상대잔차 (실제−예측)/예측의 "
                          f"{(1 - b.interval_level) / 2:.0%}·{(1 + b.interval_level) / 2:.0%} 분위수, 시장 × h별. "
                          f"잔차 {a.min_n}개 미만이면 \"*\"(전체). q_lo ≤ 0 ≤ q_hi로 자름",
                "test_coverage": round(s["coverage"], 4), "quantiles": q}
        (cdir / "intervals.json").write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print("저장 →", cdir / "intervals.json")
    if not a.no_mlflow:
        from .data import data_hash
        from .tracking import log_run
        log_run(f"intervals {b.item_code} {b.version}", "interval", b, data_hash(b.data_path),
                metrics={**{f"test_{k}": v for k, v in s.items()}, **{f"test_pooled_{k}": v for k, v in sp.items()},
                         "oof_coverage": oof_cov["coverage"]},
                params={"min_n": a.min_n}, artifacts=[out])


if __name__ == "__main__":
    main()
