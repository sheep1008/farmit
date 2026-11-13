"""[1단계] 시장 × 품목 커버리지: 1년치 전 품목 합계(collect_coverage.py)로 예측할 만큼 거래가 꾸준한지 본다.

기준은 사과 v3가 실제로 예측해 낸 시장 중 거래가 가장 적은 천안 사과 (53주 연중 거래, 주당 거래 77건).
  A: 연중(50주+) 거래, 주당 77건 이상     B: 연중 거래, 주당 20~76건
  S: 13~49주만 거래(제철), 그 기간 77건+   C: 그 외
품목 목록은 backend/codes/fixtures/items.json(aT 품목 코드 at_code).
사용: python coverage.py   결과: data/results/coverage.csv
"""
import glob
import json

import pandas as pd

from common import DATA, REPO, RESULTS

if __name__ == "__main__":
    df = pd.concat([pd.read_csv(f, dtype=str) for f in glob.glob(str(DATA / "daily" / "*.csv"))], ignore_index=True)
    df = df[df.unit_nm == "kg"]
    for c in ("records", "qty", "amount"):
        df[c] = df[c].astype(float)
    df["date"] = pd.to_datetime(df.date)
    df["item"] = df.gds_lclsf_cd + df.gds_mclsf_cd
    df["week"] = df.date.dt.to_period("W-SUN").dt.start_time
    items = json.load(open(REPO / "backend" / "codes" / "fixtures" / "items.json", encoding="utf-8"))
    it = pd.DataFrame([{"item": i["fields"]["at_code"], "name": i["fields"]["name"]} for i in items])
    w = df.groupby(["whsl_mrkt_cd", "whsl_mrkt_nm", "item", "week"]).agg(records=("records", "sum")).reset_index()
    p = w.groupby(["whsl_mrkt_cd", "whsl_mrkt_nm", "item"]).agg(weeks=("week", "nunique"), rec_med=("records", "median")).reset_index()
    p = p.merge(it, on="item")
    p["tier"] = "C"
    p.loc[(p.weeks >= 13) & (p.weeks < 50) & (p.rec_med >= 77), "tier"] = "S"
    p.loc[(p.weeks >= 50) & (p.rec_med >= 20), "tier"] = "B"
    p.loc[(p.weeks >= 50) & (p.rec_med >= 77), "tier"] = "A"
    p.to_csv(RESULTS / "coverage.csv", index=False, encoding="utf-8-sig")
    print(f"시장 {p.whsl_mrkt_cd.nunique()}곳 × 품목 {p.item.nunique()}개, 주 {w.week.nunique()}주")
    print("조합 등급:", p.tier.value_counts().reindex(list("ABSC")).to_dict())
    a = p[p.tier == "A"].groupby("name").size()
    print("A 등급 시장 수별 품목 수:", pd.cut(a.reindex(it.name, fill_value=0), [-1, 0, 3, 9, 19, 99],
                                     labels=["0곳", "1~3곳", "4~9곳", "10~19곳", "20곳+"]).value_counts().sort_index().to_dict())
    print("시장별 A 등급 품목 수:", p[p.tier == "A"].groupby("whsl_mrkt_nm").size().sort_values(ascending=False).to_dict())
