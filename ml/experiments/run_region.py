"""[4단계] 지역 단위(시도·권역) 예측과, 지역 예측을 개별 시장에 옮겨 쓸 때의 성능 (테스트).

- 지역 가격: 그 지역 모든 시장의 등급 제외 물량가중 kg당 가격 (시장 = 지역으로 바꿔 같은 파이프라인)
- 시장 전환: 시장 예측 = 시장 지난주 가격 × (지역 예측 / 지역 지난주 가격) → 시장별 모델과 같은 시장·같은 주에서 비교
사용: python run_region.py [상품코드...]   (먼저 run_oof.py market 결과가 있어야 한다)
결과: data/results/region_transfer.json
"""
import contextlib
import glob
import json
import sys
import warnings

import numpy as np
import pandas as pd

import dataset as E
from common import RESULTS

warnings.filterwarnings("ignore")
MODELS = ["rf", "lgbm", "xgb"]
FEATS = sum(E.GROUPS.values(), [])
SIDO = {"11": "서울", "21": "부산", "22": "대구", "23": "인천", "24": "광주", "25": "대전", "26": "울산", "31": "경기",
        "32": "강원", "33": "충북", "34": "충남", "35": "전북", "36": "전남", "37": "경북", "38": "경남", "39": "제주"}
MARKET_SIDO = {"380201": "울산"}   # 시장 코드 앞자리와 실제 시도가 다른 시장 (울산 시장 코드는 경남 체계)
GWON = {"서울": "수도권", "인천": "수도권", "경기": "수도권", "대전": "충청", "충북": "충청", "충남": "충청", "광주": "호남",
        "전북": "호남", "전남": "호남", "부산": "영남", "대구": "영남", "울산": "영남", "경북": "영남", "경남": "영남",
        "강원": "강원", "제주": "제주"}
_orig = E.load_daily


def sido_of(code: str) -> str:
    return MARKET_SIDO.get(code, SIDO.get(code[:2]))


def gwon_of(code: str) -> str:
    return GWON[sido_of(code)]


def region_codes(fn):
    names = sorted({fn(c) for c in SIDO_CODES})
    return {n: str(100 + i) for i, n in enumerate(names)}


SIDO_CODES = [k + "0001" for k in SIDO] + list(MARKET_SIDO)


@contextlib.contextmanager
def as_regions(fn):
    """이 블록 안에서는 E.build가 시장 대신 지역(fn: 시장 코드 → 지역 이름) 단위로 데이터를 만든다."""
    code = region_codes(fn)

    def load(item):
        d = _orig(item)
        r = d.whsl_mrkt_cd.map(fn)
        d = d[r.notna()].assign(whsl_mrkt_nm=r[r.notna()])
        d["whsl_mrkt_cd"] = d.whsl_mrkt_nm.map(code)
        return d.groupby(["date", "whsl_mrkt_cd", "whsl_mrkt_nm", "main"], as_index=False)[["records", "qty", "amount"]].sum()

    E.load_daily, E.GARAK = load, code[fn("110001")]
    try:
        yield code
    finally:
        E.load_daily, E.GARAK = _orig, "110001"


def hm(d, P):
    from farmit_ml.metrics import nmae
    return float(np.mean([nmae(d[f"target_h{h}"], P[:, j]) for j, h in enumerate(E.H)]))


def run(item, level, fn, market_res):
    with as_regions(fn) as code:
        df = E.build(item)
    sel = E.pick_markets(df); df = df[df.whsl_mrkt_cd.isin(sel[sel.use].whsl_mrkt_cd)].reset_index(drop=True)
    dev = df[df.target_week_h4 <= "2024-12-31"]; te = df[df.week >= E.TEST_START].reset_index(drop=True)
    P = E.predict(MODELS, FEATS, dev, te)
    ratio = te[["week", "whsl_mrkt_cd"]].rename(columns={"whsl_mrkt_cd": "rcode"})
    for j, h in enumerate(E.H):
        ratio[f"r{h}"] = P[:, j] / te.price_kg.values
    mdf = E.build(item)
    own = {m["whsl_mrkt_cd"]: m for m in market_res["markets"]}
    mdf = mdf[(mdf.week >= E.TEST_START) & mdf.whsl_mrkt_cd.isin(own)].copy()
    mdf["rcode"] = mdf.whsl_mrkt_cd.map(fn).map(code)
    mdf = mdf.merge(ratio, on=["week", "rcode"], how="left")
    trans = []
    for mc, g in mdf.groupby("whsl_mrkt_cd"):
        Pm = np.column_stack([g.price_kg.values * g[f"r{h}"].values for h in E.H])
        trans.append({"market": own[mc]["name"], "region_transfer": hm(g, Pm), "market_model": own[mc]["test_nmae"]})
    t = pd.DataFrame(trans)
    print(f"{E.ITEMS[item]:5s} {level}: 지역 {len(sel[sel.use])}개, 지역 가격 NMAE {hm(te, P):.4f} | 시장 전환 중앙 "
          f"{t.region_transfer.median():.4f} vs 시장별 모델 {t.market_model.median():.4f} | 전환이 더 나은 시장 "
          f"{(t.region_transfer < t.market_model).mean():.0%}", flush=True)
    return {"item": E.ITEMS[item], "level": level, "n_regions": int(sel.use.sum()), "region_nmae": hm(te, P), "transfer": trans}


if __name__ == "__main__":
    mk = {}
    for f in glob.glob(str(RESULTS / "oof_market_*.json")):
        for r in json.load(open(f, encoding="utf-8")):
            mk[r["code"]] = r
    out = []
    for it in sys.argv[1:] or E.FINAL_ITEMS:
        if it not in mk:
            print(f"{it}: run_oof.py market 결과가 없어 건너뜀"); continue
        for level, fn in (("시도", sido_of), ("권역", gwon_of)):
            out.append(run(it, level, fn, mk[it]))
    json.dump(out, open(RESULTS / "region_transfer.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
