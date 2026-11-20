"""[2단계] 소분류로 상품을 다시 정의해 받는다: 깐마늘(1209K), 노지 감귤(0614N, 하우스·수입 제외). 저장 형식은 collect_items와 같다.

사용: python collect_sub.py   (약 400회 호출)
"""
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pandas as pd
import common
from common import ALL_MARKETS, DATA, at_fetch
DEF = {"1209K": ("1209", lambda s: s.str.contains("깐마늘")),
       "0614N": ("0614", lambda s: ~s.str.contains("하우스|수입"))}
EXCL = {"등외", "하", "5등", "6등", "7등", "8등", "9등"}
OUT = DATA / "items"; OUT.mkdir(exist_ok=True)
M = ALL_MARKETS
def one(job):
    key, m0 = job; base, keep = DEF[key]
    f = OUT / f"{key}_{m0:%Y-%m}.csv"
    if f.exists(): return
    m1 = min(m0 + pd.offsets.MonthEnd(0), pd.Timestamp("2026-11-08"))
    rows, total = at_fetch({"cond[trd_clcln_ymd::GTE]": f"{m0:%Y-%m-%d}", "cond[trd_clcln_ymd::LTE]": f"{m1:%Y-%m-%d}",
                            "cond[gds_lclsf_cd::EQ]": base[:2], "cond[gds_mclsf_cd::EQ]": base[2:], **M})
    cols = ["date", "whsl_mrkt_cd", "whsl_mrkt_nm", "main", "records", "qty", "amount"]
    d = pd.DataFrame(rows)
    if d.empty: pd.DataFrame(columns=cols).to_csv(f, index=False); return
    d = d[(d.unit_nm == "kg") & keep(d.gds_sclsf_nm.astype(str))].copy()
    d["qty"] = d.unit_tot_qty.astype(float); d["amount"] = d.totprc.astype(float)
    d = d[(d.qty > 0) & (d.amount > 0)]
    if d.empty: pd.DataFrame(columns=cols).to_csv(f, index=False); return
    p = d.amount / d.qty; med = p.median(); d = d[p.between(med / 5, med * 5)]
    d["main"] = ~d.grd_nm.isin(EXCL)
    d.groupby(["trd_clcln_ymd", "whsl_mrkt_cd", "whsl_mrkt_nm", "main"]).agg(records=("qty", "size"), qty=("qty", "sum"),
        amount=("amount", "sum")).reset_index().rename(columns={"trd_clcln_ymd": "date"}).to_csv(f, index=False, encoding="utf-8-sig")
jobs = [(k, m) for k in DEF for m in pd.date_range("2018-01-01", "2026-11-08", freq="MS")]
with ThreadPoolExecutor(4) as ex: list(ex.map(one, jobs))
print("done calls", common.CALLS)
