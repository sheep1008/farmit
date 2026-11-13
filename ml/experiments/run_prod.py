"""[4단계] 생산량(KOSIS) 피처 효과: OOF로 판단하고 테스트로 확인한다.

공표 시차 (최신 연도 행의 최종수정일로 확인, 2026-11 조회):
  양파·마늘: 2026년 값이 2026-08-12 이전 공표 → Y년 값을 Y-09-01부터
  봄감자:   2026년 값이 2026-10-13 이전 공표 → Y년 값을 Y-11-01부터
  그 외(감자 전체·고구마·과일): 다음 해 값이 아직 없음 → Y년 값을 Y+1-01-01부터 (사과 v3와 같은 규칙)
피처: 생산량·면적·10a당 생산량, 전년 대비 생산량·면적 비율.
비교 기준: 품목별로 run_oof.py가 고른 피처 (양파는 공통+날씨).
사용: python run_prod.py [상품코드...]   결과: data/results/prod_{상품}.json
"""
import json
import sys
import warnings

import numpy as np
import pandas as pd

import dataset as E
import run_oof as O
import weather as W
from common import DATA, RESULTS

warnings.filterwarnings("ignore")
# 상품 → [(통계표, KOSIS 작물명, 피처 접두어, 사용 가능 규칙)]
SPEC = {
    "0601": [("DT_1ET0292", "사과", "prod", "next")], "0602": [("DT_1ET0292", "배", "prod", "next")],
    "0605": [("DT_1ET0292", "단감", "prod", "next")], "0614N": [("DT_1ET0292", "감귤", "prod", "next")],
    "1201": [("DT_1ET0291", "양파", "prod", "09-01")], "1209K": [("DT_1ET0291", "마늘", "prod", "09-01")],
    "0501": [("DT_1ET0026", "감자", "prod", "next"), ("DT_1ET0026", "일반봄감자", "spring", "11-01")],
    "0502": [("DT_1ET0026", "고구마", "prod", "next")],
}
KIND = {"생산량": "ton", "면적": "area", "10a당 생산량": "yield"}
WX_ITEMS = {"1201"}   # run_oof.py에서 날씨를 채택한 상품


def annual(item):
    out = []
    for tbl, crop, pre, rule in SPEC[item]:
        d = pd.read_csv(DATA / "kosis" / f"{tbl}.csv", dtype=str)
        d = d[d.ITM_NM.str.strip().str.split(":").str[0] == crop].copy()
        d["k"] = d.ITM_NM.str.strip().str.split(":").str[1].map(KIND)
        d = d.dropna(subset=["k"])
        d["v"] = pd.to_numeric(d.DT, errors="coerce")       # 아직 없는 해는 '-' → NaN
        p = d.pivot_table(index=d.PRD_DE.astype(int), columns="k", values="v").sort_index()
        p.columns = [f"{pre}_{c}" for c in p.columns]
        p[f"{pre}_ton_yoy"] = p[f"{pre}_ton"] / p[f"{pre}_ton"].shift(1)
        p[f"{pre}_area_yoy"] = p[f"{pre}_area"] / p[f"{pre}_area"].shift(1)
        p["avail"] = [pd.Timestamp(f"{y + 1}-01-01") if rule == "next" else pd.Timestamp(f"{y}-{rule}") for y in p.index]
        out.append(p.dropna(how="all", subset=[c for c in p.columns if c != "avail"]))
    return out


def add_prod(df, item):
    """예측 시점(week + 7일, 월요일)에 이미 공표된 가장 최근 값을 붙인다."""
    cols = []
    for p in annual(item):
        p = p.sort_values("avail")
        idx = np.searchsorted(p.avail.values, (df.week + pd.Timedelta(days=7)).values, side="right") - 1
        for c in [c for c in p.columns if c != "avail"]:
            df[c] = np.where(idx >= 0, p[c].values[np.clip(idx, 0, None)], np.nan)
            cols.append(c)
    return df, cols


def run(item):
    years = E.oof_years(item)
    df = O.selected_markets(E.build(item))
    base = list(O.BASE)
    if item in WX_ITEMS:
        df = df.merge(W.weekly_weather(item, W.daily_sido()), left_on="week", right_index=True, how="left"); base += O.WX
    df, pc = add_prod(df, item)
    dev = df[df.target_week_h4 <= "2024-12-31"]; te = df[df.week >= E.TEST_START].reset_index(drop=True)
    res = {}
    for name, feats in (("기존", base), ("+생산량", base + pc)):
        V, P = O.oof(df, feats, years)
        yr = [O.hm(g, P[g.index.values]) for _, g in V.groupby("fold")]
        res[name] = {"oof": float(np.mean(yr)), "years": yr, "test": O.hm(te, E.predict(O.MODELS, feats, dev, te))}
    d_oof, d_test = res["+생산량"]["oof"] - res["기존"]["oof"], res["+생산량"]["test"] - res["기존"]["test"]
    adopt = -d_oof > O.MIN_IMPROVE
    print(f"{E.ITEMS[item]:5s} 기존({'공통+날씨' if item in WX_ITEMS else '공통'}) OOF {res['기존']['oof']:.4f} 테스트 {res['기존']['test']:.4f} | "
          f"+생산량 OOF {res['+생산량']['oof']:.4f} ({d_oof:+.4f}) 테스트 {res['+생산량']['test']:.4f} ({d_test:+.4f}) | "
          f"연도별 OOF Δ {np.round(np.array(res['+생산량']['years']) - np.array(res['기존']['years']), 4).tolist()} | 채택 {adopt}", flush=True)
    return {"item": E.ITEMS[item], "code": item, "base": "공통+날씨" if item in WX_ITEMS else "공통", "res": res,
            "d_oof": d_oof, "d_test": d_test, "adopt": adopt, "feats": pc}


if __name__ == "__main__":
    items = sys.argv[1:] or E.FINAL_ITEMS
    out = [run(i) for i in items]
    json.dump(out, open(RESULTS / f"prod_{'_'.join(items)}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
