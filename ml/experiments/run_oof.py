"""[4단계] OOF(2021~2024)로 피처·시장을 정하고 테스트(2025-01~)로 검증한다. 규칙은 테스트를 보기 전에 고정한다.

사용: python run_oof.py market [상품코드...]   시장별 모델: 공통 vs 공통+날씨, 시장 선별 (기본: dataset.FINAL_ITEMS)
      python run_oof.py region [상품코드...]   시도 단위 모델 (시도 안 모든 시장 합산)
      python run_oof.py pool                   사과: 대전·충청 4개 시장만 학습 vs 전국 학습 (4개 시장 OOF로 비교)
결과: data/results/oof_{mode}_{상품}.json
"""
import json
import sys
import warnings

import numpy as np
import pandas as pd

import dataset as E
import weather as W
from common import RESULTS
from farmit_ml.metrics import nmae

warnings.filterwarnings("ignore")
MODELS = ["rf", "lgbm", "xgb"]
BASE = sum(E.GROUPS.values(), [])
WX = ["wx_ta_avg", "wx_ta_max", "wx_ta_min", "wx_rn_sum", "wx_ss_sum", "wx_rhm_avg", "wx_heat_days", "wx_cold_days",
      "wx_rn_sum_4w", "wx_rn_sum_12w", "wx_heat_days_4w", "wx_cold_days_4w", "wx_ta_avg_dev"]
# 외부 피처는 OOF 평균이 이만큼 넘게 좋아질 때만 넣는다 (사과 v3와 같은 규칙)
MIN_IMPROVE = 0.0005
# 비교용 엄격 규칙 (처음 쓴 기준). 해마다 흔들려서 최종 규칙으로 쓰지 않는다
STRICT = {"max_nmae": 0.12, "min_gain": 0.15}
C4 = ["250001", "250003", "340101", "330101"]


def hm(d, P):
    """h1~h4 NMAE 평균."""
    return float(np.mean([nmae(d[f"target_h{h}"], P[:, j]) for j, h in enumerate(E.H)]))


def base_pred(d):
    return {"B1": np.column_stack([d.price_kg] * 4), "B2": np.column_stack([d.price_ma4] * 4)}


def oof(df, feats, years):
    """연도별 확장 윈도우 OOF 예측. 반환: (fold 열이 붙은 검증 행, 예측 N×4)."""
    parts, preds = [], []
    for y in years:
        trn = df[df.target_week_h4 <= f"{y - 1}-12-31"]
        val = df[(df.week >= f"{y}-01-01") & (df.target_week_h4 <= f"{y}-12-31")]
        preds.append(E.predict(MODELS, feats, trn, val)); parts.append(val.assign(fold=y))
    return pd.concat(parts, ignore_index=True), np.vstack(preds)


def min_wins(years) -> int:
    """최종 선별 규칙: 4개 연도 중 3개 이상, 연도가 더 적으면 전부에서 기준선을 이겨야 한다."""
    return 3 if len(years) >= 4 else len(years)


def unit_table(V, P, years):
    """시장(또는 지역)별 OOF: 연도별 NMAE 평균, 기준선(B1·B2 중 OOF에서 나은 쪽), 기준선을 이긴 연도 수."""
    rows = []
    for k, g in V.groupby("whsl_mrkt_cd"):
        yr = {y: (hm(gy, P[gy.index.values]), {b: hm(gy, Bm) for b, Bm in base_pred(gy).items()})
              for y, gy in g.groupby("fold")}
        m = np.mean([v[0] for v in yr.values()])
        bname = min(("B1", "B2"), key=lambda b: np.mean([v[1][b] for v in yr.values()]))
        b = np.mean([v[1][bname] for v in yr.values()])
        rows.append({"whsl_mrkt_cd": k, "name": g.market_nm.iloc[0], "oof_nmae": m, "oof_base": b, "oof_gain": 1 - m / b,
                     "base_name": bname, "years": len(yr), "wins": sum(v[0] < v[1][bname] for v in yr.values())})
    t = pd.DataFrame(rows)
    t["eligible"] = t.wins >= min_wins(years)
    t["eligible_strict"] = (t.oof_nmae <= STRICT["max_nmae"]) & (t.oof_gain >= STRICT["min_gain"]) & t.eligible
    return t


def test_table(df, feats, elig):
    """2024년까지로 학습해 테스트를 한 번 예측. 시장별 기준선은 OOF에서 고른 쪽."""
    dev = df[df.target_week_h4 <= "2024-12-31"]; te = df[df.week >= E.TEST_START].reset_index(drop=True)
    P = E.predict(MODELS, feats, dev, te)
    bn = elig.set_index("whsl_mrkt_cd").base_name
    rows = []
    for k, g in te.groupby("whsl_mrkt_cd"):
        Bk = base_pred(g)[bn.get(k, "B1")]
        rows.append({"whsl_mrkt_cd": k, "test_nmae": hm(g, P[g.index.values]), "test_base": hm(g, Bk)})
    t = pd.DataFrame(rows); t["test_gain"] = 1 - t.test_nmae / t.test_base
    return t, hm(te, P)


def selected_markets(df):
    sel = E.pick_markets(df)
    return df[df.whsl_mrkt_cd.isin(sel[sel.use].whsl_mrkt_cd)].reset_index(drop=True)


def run_market(item):
    years = E.oof_years(item)
    df = selected_markets(E.build(item))
    df = df.merge(W.weekly_weather(item, W.daily_sido()), left_on="week", right_index=True, how="left")
    res = {}
    for name, feats in (("공통", BASE), ("공통+날씨", BASE + WX)):
        V, P = oof(df, feats, years)
        yr = [hm(g, P[g.index.values]) for _, g in V.groupby("fold")]
        res[name] = {"mean": float(np.mean(yr)), "years": yr, "V": V, "P": P}
        print(f"  {E.ITEMS[item]} {name}: OOF {np.mean(yr):.4f} {np.round(yr, 4).tolist()}", flush=True)
    chosen = "공통+날씨" if res["공통"]["mean"] - res["공통+날씨"]["mean"] > MIN_IMPROVE else "공통"
    feats = BASE + WX if chosen == "공통+날씨" else BASE
    elig = unit_table(res[chosen]["V"], res[chosen]["P"], years)
    tt, test_chosen = test_table(df, feats, elig)
    _, test_other = test_table(df, BASE if chosen == "공통+날씨" else BASE + WX, elig)
    m = elig.merge(tt, on="whsl_mrkt_cd", how="left")
    print(f"  {E.ITEMS[item]} 선택 {chosen} | 테스트 {test_chosen:.4f} (다른 쪽 {test_other:.4f}) | 선별 {int(m.eligible.sum())}/{len(m)}", flush=True)
    return {"item": E.ITEMS[item], "code": item, "oof_years_list": list(years), "chosen": chosen,
            "oof": {k: {"mean": v["mean"], "years": v["years"]} for k, v in res.items()},
            "test_chosen": test_chosen, "test_other": test_other, "markets": m.to_dict("records")}


def run_region(item):
    import run_region as RR
    with RR.as_regions(RR.sido_of):
        df = selected_markets(E.build(item))
    years = E.oof_years(item)
    V, P = oof(df, BASE, years)
    elig = unit_table(V, P, years)
    tt, test_all = test_table(df, BASE, elig)
    m = elig.merge(tt, on="whsl_mrkt_cd")
    print(f"  {E.ITEMS[item]} 시도: 기준선을 3년+ 이긴 지역 {int(m.eligible.sum())}/{len(m)} | 테스트 {test_all:.4f}", flush=True)
    return {"item": E.ITEMS[item], "code": item, "regions": m.to_dict("records"), "test": test_all}


def run_pool():
    out = {}
    for name, mk in (("4개 시장만 학습", C4), ("전국 학습", None)):
        df = E.build("0601", mk)
        if mk is None:
            df = selected_markets(df)
        V, P = oof(df, BASE, E.oof_years("0601"))
        k = V.whsl_mrkt_cd.isin(C4).values
        Vk, Pk = V[k].reset_index(drop=True), P[k]
        yr = {int(y): hm(g, Pk[g.index.values]) for y, g in Vk.groupby("fold")}
        out[name] = {"years": yr, "mean": float(np.mean(list(yr.values())))}
        print(f"  사과 {name}: 4개 시장 OOF {out[name]['mean']:.4f} {np.round(list(yr.values()), 4).tolist()}", flush=True)
    return out


if __name__ == "__main__":
    mode, items = sys.argv[1], sys.argv[2:] or E.FINAL_ITEMS
    if mode == "pool":
        r, fn = run_pool(), "oof_pool.json"
    else:
        f = run_market if mode == "market" else run_region
        r, fn = [f(i) for i in items], f"oof_{mode}_{'_'.join(items)}.json"
    json.dump(r, open(RESULTS / fn, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
    print("saved", RESULTS / fn)
