"""[3단계] 품목별 2023년 전국 원산지 물량 (날씨 가중치용). 학습 기간 안의 정보만 쓴다.

사용: python collect_origin.py   (약 230회 호출)
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pandas as pd
import common
from common import ALL_MARKETS, DATA, at_fetch
ITEMS = ["0601", "0602", "1201", "1209", "0501", "0502", "0605", "0614"]
M = ALL_MARKETS
OUT = DATA / "origin"; OUT.mkdir(exist_ok=True)
def one(job):
    item, m0 = job
    f = OUT / f"{item}_{m0:%Y-%m}.csv"
    if f.exists(): return
    m1 = m0 + pd.offsets.MonthEnd(0)
    rows, total = at_fetch({"cond[trd_clcln_ymd::GTE]": f"{m0:%Y-%m-%d}", "cond[trd_clcln_ymd::LTE]": f"{m1:%Y-%m-%d}",
                            "cond[gds_lclsf_cd::EQ]": item[:2], "cond[gds_mclsf_cd::EQ]": item[2:], **M})
    d = pd.DataFrame(rows)
    if d.empty: pd.DataFrame(columns=["plor_nm", "qty"]).to_csv(f, index=False); return
    d = d[d.unit_nm == "kg"]; d["qty"] = d.unit_tot_qty.astype(float)
    d.groupby("plor_nm", as_index=False).qty.sum().to_csv(f, index=False, encoding="utf-8-sig")
jobs = [(i, m) for i in ITEMS for m in pd.date_range("2023-01-01", "2023-12-01", freq="MS")]
with ThreadPoolExecutor(4) as ex: list(ex.map(one, jobs))
print("calls", common.CALLS)
