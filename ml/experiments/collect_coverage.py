"""[1단계] 전 품목·전국 aT 정산을 날짜마다 (시장, 품목 대·중분류, 단위) 합계로 저장한다 (시장×품목 커버리지 분석용).

사용: python collect_coverage.py 2025-11-01 2026-10-31   (1년 약 1,300회 호출)
"""
import datetime as dt, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pandas as pd
import common
from common import ALL_MARKETS, DATA, at_fetch

OUT = DATA / "daily"; OUT.mkdir(exist_ok=True)
M = ALL_MARKETS
KEYS = ["whsl_mrkt_cd", "whsl_mrkt_nm", "gds_lclsf_cd", "gds_lclsf_nm", "gds_mclsf_cd", "gds_mclsf_nm", "unit_nm"]

def one(d):
    f = OUT / f"{d}.csv"
    if f.exists(): return d, -1
    rows, total = at_fetch({"cond[trd_clcln_ymd::GTE]": d, "cond[trd_clcln_ymd::LTE]": d, **M})
    if len(rows) != total: raise RuntimeError(f"{d} {len(rows)} != {total}")
    if not rows:
        pd.DataFrame(columns=KEYS + ["records", "qty", "amount", "date"]).to_csv(f, index=False); return d, 0
    df = pd.DataFrame(rows)
    df["qty"] = df["unit_tot_qty"].astype(float); df["amount"] = df["totprc"].astype(float)
    g = df.groupby(KEYS).agg(records=("qty", "size"), qty=("qty", "sum"), amount=("amount", "sum")).reset_index()
    g["date"] = d
    g.to_csv(f, index=False, encoding="utf-8-sig"); return d, len(rows)

days = pd.date_range(sys.argv[1], sys.argv[2]).strftime("%Y-%m-%d")
with ThreadPoolExecutor(4) as ex:
    for i, (d, n) in enumerate(ex.map(one, days), 1):
        if i % 30 == 0: print(f"{i}/{len(days)} {d} rows={n} calls={common.CALLS}", flush=True)
print("done calls", common.CALLS, flush=True)
