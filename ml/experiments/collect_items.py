"""[2단계] 저장성 품목 × 월 단위로 전국 aT 정산을 받아 (날짜, 시장) 합계로 저장한다.
가격 규칙: 사과 데이터셋과 같은 등급 제외(등외·하·5등 이하), 이상치는 품목·월 전국 중앙값의 1/5~5배 밖.

사용: python collect_items.py 2018-01-01 2026-11-08   (8개 품목 약 2,000회 호출)
"""
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np, pandas as pd
import common
from common import ALL_MARKETS, DATA, at_fetch

ITEMS = {"0601": "사과", "0602": "배", "1201": "양파", "1209": "마늘", "0501": "감자", "0502": "고구마", "0605": "단감", "0614": "감귤"}
EXCL = {"등외", "하", "5등", "6등", "7등", "8등", "9등"}
OUT = DATA / "items"; OUT.mkdir(exist_ok=True)
M = ALL_MARKETS

def one(job):
    item, m0 = job
    f = OUT / f"{item}_{m0:%Y-%m}.csv"
    if f.exists(): return job, -1
    m1 = min(m0 + pd.offsets.MonthEnd(0), pd.Timestamp(sys.argv[2]))
    rows, total = at_fetch({"cond[trd_clcln_ymd::GTE]": f"{m0:%Y-%m-%d}", "cond[trd_clcln_ymd::LTE]": f"{m1:%Y-%m-%d}",
                            "cond[gds_lclsf_cd::EQ]": item[:2], "cond[gds_mclsf_cd::EQ]": item[2:], **M})
    if len(rows) != total: raise RuntimeError(f"{job} {len(rows)} != {total}")
    cols = ["date", "whsl_mrkt_cd", "whsl_mrkt_nm", "main", "records", "qty", "amount", "n_raw", "n_drop"]
    if not rows:
        pd.DataFrame(columns=cols).to_csv(f, index=False); return job, 0
    d = pd.DataFrame(rows)
    d = d[d["unit_nm"] == "kg"].copy()
    d["qty"] = d["unit_tot_qty"].astype(float); d["amount"] = d["totprc"].astype(float)
    d = d[(d.qty > 0) & (d.amount > 0)]
    d["p"] = d.amount / d.qty
    med = d["p"].median()
    n_raw = len(d); d = d[d.p.between(med / 5, med * 5)]
    d["main"] = ~d["grd_nm"].isin(EXCL)
    g = d.groupby(["trd_clcln_ymd", "whsl_mrkt_cd", "whsl_mrkt_nm", "main"]).agg(
        records=("qty", "size"), qty=("qty", "sum"), amount=("amount", "sum")).reset_index().rename(columns={"trd_clcln_ymd": "date"})
    g["n_raw"], g["n_drop"] = n_raw, n_raw - len(d)
    g.to_csv(f, index=False, encoding="utf-8-sig"); return job, len(rows)

months = pd.date_range(sys.argv[1], sys.argv[2], freq="MS")
jobs = [(i, m) for i in ITEMS for m in months]
with ThreadPoolExecutor(4) as ex:
    for k, (job, n) in enumerate(ex.map(one, jobs), 1):
        if k % 50 == 0: print(f"{k}/{len(jobs)} {ITEMS[job[0]]} {job[1]:%Y-%m} rows={n} calls={common.CALLS}", flush=True)
print("done calls", common.CALLS, flush=True)
