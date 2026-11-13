"""[3단계] 시도별 대표 ASOS 관측소 일자료 수집과 품목별 주간 날씨 피처.

수집: python weather.py   (관측소 53곳 × 10년 = 530회, ASOS API)
날씨 = 시도별 관측소 평균을 품목 원산지 시도 비중(2023년 aT)으로 가중 평균. 시군 단위보다 거칠다.
"""
import glob, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np, pandas as pd, requests
from common import DATA, get_key
OUT = DATA / "asos"; OUT.mkdir(exist_ok=True)
STN = {"강원": [101, 105, 114, 121, 212, 100], "경기": [119, 202, 203, 98], "충북": [127, 131, 221, 226],
       "충남": [129, 232, 235, 236, 177], "전북": [146, 140, 245, 247, 243], "전남": [165, 156, 168, 174, 261, 262],
       "경북": [136, 137, 138, 272, 276, 278, 279, 281], "경남": [155, 192, 284, 288, 295], "제주": [184, 189, 185, 188],
       "대구": [143], "울산": [152], "부산": [159], "서울": [108], "인천": [112], "대전": [133]}
NORM = {"경상북도": "경북", "경상남도": "경남", "전라북도": "전북", "전북특별자치도": "전북", "전라남도": "전남",
        "전남광주통합특별시": "전남", "광주": "전남", "광주광역시": "전남", "충청북도": "충북", "충청남도": "충남", "세종": "충남",
        "세종특별자치시": "충남", "경기도": "경기", "강원도": "강원", "강원특별자치도": "강원", "제주도": "제주",
        "제주특별자치도": "제주", "대구광역시": "대구", "울산광역시": "울산", "부산광역시": "부산", "서울특별시": "서울",
        "인천광역시": "인천", "대전광역시": "대전"}
URL = "https://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"


def fetch(job):
    stn, y = job
    f = OUT / f"{stn}_{y}.csv"
    if f.exists(): return
    key = get_key("DATA_GO_KR_KEY")
    end = min(pd.Timestamp(f"{y}-12-31"), pd.Timestamp("2026-11-08"))
    p = {"serviceKey": key, "pageNo": 1, "numOfRows": 999, "dataType": "JSON", "dataCd": "ASOS", "dateCd": "DAY",
         "startDt": f"{y}0101", "endDt": f"{end:%Y%m%d}", "stnIds": stn}
    for i in range(4):
        try:
            d = requests.get(URL, params=p, timeout=60).json(); break
        except Exception:
            time.sleep(3 * (i + 1))
    else:
        print("fail", stn, y); return
    items = (d.get("response", {}).get("body") or {}).get("items", {}) or {}
    pd.DataFrame(items.get("item", [])).to_csv(f, index=False, encoding="utf-8-sig")


def sido_share(item: str) -> pd.Series:
    d = pd.concat([pd.read_csv(f) for f in glob.glob(str(DATA / "origin" / f"{item[:4]}_*.csv"))])
    s = d.plor_nm.astype(str).str.split().str[0].map(lambda x: NORM.get(x, x))
    d = d[s.isin(STN)].assign(sido=s[s.isin(STN)])
    return d.groupby("sido").qty.sum() / d.qty.sum()


def daily_sido() -> pd.DataFrame:
    fs = [f for f in glob.glob(str(OUT / "*.csv")) if Path(f).stat().st_size > 50]
    d = pd.concat([pd.read_csv(f, usecols=lambda c: c in {"stnId", "tm", "avgTa", "maxTa", "minTa", "sumRn", "sumSsHr", "avgRhm"})
                   for f in fs])
    d["tm"] = pd.to_datetime(d.tm); d["sumRn"] = d.sumRn.fillna(0)
    st2sido = {s: k for k, v in STN.items() for s in v}
    d["sido"] = d.stnId.map(st2sido)
    return d.groupby(["sido", "tm"])[["avgTa", "maxTa", "minTa", "sumRn", "sumSsHr", "avgRhm"]].mean().reset_index()


def weekly_weather(item: str, ds: pd.DataFrame) -> pd.DataFrame:
    """주(월~일) 단위, 원산지 시도 비중 가중. week 값의 날씨는 그 주 일요일까지 → 다음 월요일 예측에 쓸 수 있다."""
    w = sido_share(item)
    d = ds[ds.sido.isin(w.index)].copy()
    d["w"] = d.sido.map(w)
    cols = ["avgTa", "maxTa", "minTa", "sumRn", "sumSsHr", "avgRhm"]
    g = d.groupby("tm").apply(lambda x: pd.Series({c: np.average(x[c].fillna(x[c].mean()), weights=x.w) if x[c].notna().any() else np.nan for c in cols}), include_groups=False)
    g["heat"] = (g.maxTa >= 33).astype(float); g["cold"] = (g.minTa < 0).astype(float)
    g["week"] = g.index - pd.to_timedelta(g.index.weekday, unit="D")
    wk = g.groupby("week").agg(wx_ta_avg=("avgTa", "mean"), wx_ta_max=("maxTa", "max"), wx_ta_min=("minTa", "min"),
                               wx_rn_sum=("sumRn", "sum"), wx_ss_sum=("sumSsHr", "sum"), wx_rhm_avg=("avgRhm", "mean"),
                               wx_heat_days=("heat", "sum"), wx_cold_days=("cold", "sum"))
    wk["wx_rn_sum_4w"] = wk.wx_rn_sum.rolling(4, min_periods=2).sum()
    wk["wx_rn_sum_12w"] = wk.wx_rn_sum.rolling(12, min_periods=6).sum()
    wk["wx_heat_days_4w"] = wk.wx_heat_days.rolling(4, min_periods=2).sum()
    wk["wx_cold_days_4w"] = wk.wx_cold_days.rolling(4, min_periods=2).sum()
    wk["wx_ta_avg_dev"] = wk.wx_ta_avg - wk.groupby(wk.index.isocalendar().week.values).wx_ta_avg.transform(
        lambda s: s.shift(1).expanding().mean())   # 같은 주차 과거 평균 대비 (과거 해만 사용)
    return wk


if __name__ == "__main__":
    jobs = [(s, y) for v in STN.values() for s in v for y in range(2017, 2027)]
    with ThreadPoolExecutor(4) as ex: list(ex.map(fetch, jobs))
    n = len([f for f in glob.glob(str(OUT / "*.csv")) if Path(f).stat().st_size > 50])
    print("files with data", n, "/", len(jobs))
