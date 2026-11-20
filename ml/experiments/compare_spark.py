"""Spark 피처(batch/spark/features.py → ml/data/weekly_<품목>.csv)와 실험 데이터셋(dataset.build)을 같은 (시장, 주)끼리 비교한다 (K30).

운영 피처가 실험과 같은 정의로 만들어졌는지 확인하는 용도다. 이상치를 거르는 단위가 달라(원본 거래 vs DB 합계 행) 완전히 같지는 않다.
사용: python collect_items.py 2018-01-01 2026-11-08 0601   (실험용 사과 데이터, 처음 한 번)
      python compare_spark.py 0601                            결과: data/results/compare_spark_0601.csv
"""
import sys

import numpy as np
import pandas as pd

import dataset as E
from common import ML_ROOT, RESULTS

REL_TOL = 0.005   # 상대 차이 0.5% 이내면 같다고 본다 (가격 반올림·소수점 저장 차이)


def compare(item: str) -> pd.DataFrame:
    exp = E.build(item).rename(columns={"whsl_mrkt_cd": "market_cd"})
    sp = pd.read_csv(ML_ROOT / "data" / f"weekly_{item}.csv", dtype={"market_cd": str}, parse_dates=["week"])
    end = exp.week.max()                       # 실험 데이터는 수집 끝 날짜까지만 있다
    sp = sp[sp.week <= end]
    keys = ["market_cd", "week"]
    m = exp.merge(sp, on=keys, suffixes=("_e", "_s"))
    print(f"행: 실험 {len(exp)}, Spark {len(sp)} (~{end:%Y-%m-%d}), 같은 (시장, 주) {len(m)}")
    only_e = exp.merge(sp[keys], on=keys, how="left", indicator=True).query("_merge == 'left_only'")
    only_s = sp.merge(exp[keys], on=keys, how="left", indicator=True).query("_merge == 'left_only'")
    print(f"  실험에만 {len(only_e)}행, Spark에만 {len(only_s)}행")

    feats = [c for c in sum(E.GROUPS.values(), []) if c in sp.columns] + [f"target_h{h}" for h in E.H]
    rows = []
    for c in feats:
        a, b = m[f"{c}_e"].astype(float), m[f"{c}_s"].astype(float)
        both = a.notna() & b.notna()
        rel = (a[both] - b[both]).abs() / a[both].abs().clip(lower=1e-9)
        same = rel <= REL_TOL
        rows.append({"column": c, "both": int(both.sum()), "na_only_exp": int((a.notna() & b.isna()).sum()),
                     "na_only_spark": int((a.isna() & b.notna()).sum()),
                     "same_pct": round(100 * same.mean(), 2) if both.any() else np.nan,
                     "rel_diff_median": rel.median() if both.any() else np.nan,
                     "rel_diff_p99": rel.quantile(0.99) if both.any() else np.nan,
                     "corr": a[both].corr(b[both]) if both.sum() > 2 else np.nan})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    item = sys.argv[1] if len(sys.argv) > 1 else "0601"
    t = compare(item)
    t.to_csv(RESULTS / f"compare_spark_{item}.csv", index=False, encoding="utf-8-sig")
    with pd.option_context("display.width", 200, "display.max_rows", 100):
        print(t.round(4).to_string(index=False))
