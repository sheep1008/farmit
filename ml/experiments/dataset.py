"""(시장, 주) 데이터셋과 공통 모델. 모든 run_*.py가 이 모듈을 쓴다.

- 데이터: collect_items.py·collect_sub.py가 만든 data/items/{상품}_{YYYY-MM}.csv (날짜·시장별 합계)
- 피처: aT 가격·물량, 시차·이동평균, 전국·가락 가격, 공급량, 달력(명절), 시장 (GROUPS)
- 모델: RF·LightGBM·XGBoost h별 모델 평균 (ml/config/0601_v3/best_params.json = 사과 v3 하이퍼파라미터),
  타깃 log(h주 뒤 가격 / 지난주 가격). 분할·지표는 사과 v3와 같다 (테스트 2025-01~).
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd

from common import DATA, ML_ROOT, RESULTS  # noqa: F401  (sys.path에 ml/ 추가)
from farmit_ml.metrics import nmae  # noqa: E402
from farmit_ml.models import make_model  # noqa: E402

BP = json.loads((ML_ROOT / "config" / "0601_v3" / "best_params.json").read_text(encoding="utf-8"))
H = (1, 2, 3, 4)
# 상품 코드: aT 대분류+중분류. 뒤에 글자가 붙은 것은 소분류로 다시 정의한 상품 (collect_sub.py)
ITEMS = {"0601": "사과", "0602": "배", "1201": "양파", "1209": "마늘", "0501": "감자", "0502": "고구마", "0605": "단감", "0614": "감귤",
         "1209K": "깐마늘", "0614N": "노지감귤"}
FINAL_ITEMS = ["0601", "0602", "1201", "0501", "0502", "0605", "0614N", "1209K"]   # 최종 검토 대상 (마늘·감귤은 재정의본)
# 소분류 기록이 늦게 시작된 상품: 이 날짜 이후만 쓴다 (깐마늘은 2021년 중반부터 따로 기록됨)
HISTORY_START = {"1209K": "2021-07-01"}
SEOL = ["2017-01-28", "2018-02-16", "2019-02-05", "2020-01-25", "2021-02-12", "2022-02-01", "2023-01-22", "2024-02-10",
        "2025-01-29", "2026-02-17", "2027-02-07"]
CHUSEOK = ["2017-10-04", "2018-09-24", "2019-09-13", "2020-10-01", "2021-09-21", "2022-09-10", "2023-09-29", "2024-09-17",
           "2025-10-06", "2026-09-25", "2027-09-15"]
HOL = sorted(pd.to_datetime(SEOL + CHUSEOK))
GARAK = "110001"
TEST_START = pd.Timestamp("2025-01-01")

PRICE_LEVEL = ["price_allgrade", "price_last1", "price_lag1", "price_lag2", "price_lag4", "price_ma4", "price_ma8",
               "price_yoy", "nat_price", "nat_price_ma4", "garak_price", "garak_price_ma4"]
GROUPS = {
    "base": ["price_kg", "qty_kg", "price_allgrade", "n_trade_days", "n_records", "price_last1"],
    "lags": ["price_lag1", "price_lag2", "price_lag4", "price_ma4", "price_ma8", "price_yoy", "qty_lag1", "qty_ma4",
             "chg_1w", "chg_4w"],
    "national": ["nat_price", "nat_price_ma4", "ratio_nat_med26", "dev_nat", "nat_chg_1w"],
    "garak": ["garak_price", "garak_price_ma4", "dev_garak"],
    "supply": ["nat_qty", "nat_qty_ma4", "nat_qty_yoy", "qty_share", "qty_yoy"],
    "calendar": ["weekofyear", "month", "days_to_seol", "days_since_seol", "days_to_chuseok", "days_since_chuseok"]
                + [f"hol_offset_h{h}" for h in H] + [f"hol_in_target_h{h}" for h in H],
    "market": ["mkt_id"],
}


# ----------------------------------------------------------------------------- 데이터
def load_daily(item: str) -> pd.DataFrame:
    fs = sorted(glob.glob(str(DATA / "items" / f"{item}_*.csv")))
    d = pd.concat([pd.read_csv(f, dtype={"whsl_mrkt_cd": str}) for f in fs if Path(f).stat().st_size > 80], ignore_index=True)
    d["date"] = pd.to_datetime(d["date"])
    d["main"] = d["main"].astype(str) == "True"
    return d


def weekly(item: str):
    d = load_daily(item)
    d["week"] = d["date"] - pd.to_timedelta(d["date"].dt.weekday, unit="D")
    k = ["whsl_mrkt_cd", "week"]
    a = d.groupby(k).agg(qty_kg=("qty", "sum"), amt=("amount", "sum"), n_records=("records", "sum"),
                         n_trade_days=("date", "nunique"))
    m = d[d.main].groupby(k).agg(mq=("qty", "sum"), ma=("amount", "sum"))
    w = a.join(m)
    w["price_kg"] = w.ma / w.mq
    w["price_allgrade"] = w.amt / w.qty_kg
    # 주 마지막 거래일 가격 (주 후반 움직임)
    dm = d[d.main].groupby(["whsl_mrkt_cd", "week", "date"]).agg(q=("qty", "sum"), a=("amount", "sum")).reset_index()
    last = dm.sort_values("date").groupby(k).tail(1).set_index(k)
    w["price_last1"] = last.a / last.q
    w = w.reset_index()
    names = d.drop_duplicates("whsl_mrkt_cd").set_index("whsl_mrkt_cd")["whsl_mrkt_nm"]
    # 전국(물량가중)·가락
    nat = d[d.main].groupby("week").agg(q=("qty", "sum"), a=("amount", "sum"))
    nat = pd.DataFrame({"nat_price": nat.a / nat.q, "nat_qty": d.groupby("week")["qty"].sum()})
    weeks = pd.date_range(w.week.min(), w.week.max(), freq="7D")
    nat = nat.reindex(weeks)
    return w, nat, names


def holiday_feats(week: pd.Series) -> pd.DataFrame:
    pred = week + pd.Timedelta(days=7)
    out = {}
    for nm, lst in (("seol", SEOL), ("chuseok", CHUSEOK)):
        ds = pd.to_datetime(lst).values
        pv = pred.values[:, None]
        diff = (ds[None, :] - pv).astype("timedelta64[D]").astype(int)
        fut = np.where(diff >= 0, diff, 10 ** 6).min(1)
        past = np.where(diff < 0, -diff, 10 ** 6).min(1)
        out[f"days_to_{nm}"], out[f"days_since_{nm}"] = np.minimum(fut, 400), np.minimum(past, 400)
    hv = np.array(HOL, dtype="datetime64[D]")
    for h in H:
        tw = (week + pd.Timedelta(weeks=h)).values.astype("datetime64[D]")
        diff = (hv[None, :] - tw[:, None]).astype(int)          # 명절일 - 타깃 주 월요일
        near = diff[np.arange(len(tw)), np.abs(diff).argmin(1)]
        out[f"hol_offset_h{h}"] = np.clip(near, -35, 35)
        out[f"hol_in_target_h{h}"] = ((diff >= -1) & (diff <= 7)).any(1).astype(int)  # 연휴(전날~다음날)가 타깃 주와 겹침
    return pd.DataFrame(out, index=week.index)


def build(item: str, markets: list[str] | None = None) -> pd.DataFrame:
    w, nat, names = weekly(item)
    weeks = nat.index
    rows = []
    mk_codes = sorted(w.whsl_mrkt_cd.unique())
    for mc in mk_codes:
        g = w[w.whsl_mrkt_cd == mc].set_index("week").reindex(weeks)
        g["whsl_mrkt_cd"], g["market_nm"] = mc, names[mc]
        rows.append(g)
    df = pd.concat(rows).rename_axis("week").reset_index()
    df = df.sort_values(["whsl_mrkt_cd", "week"]).reset_index(drop=True)
    gp = df.groupby("whsl_mrkt_cd")
    df["no_trade"] = df.price_kg.isna().astype(int)
    for L in (1, 2, 4):
        df[f"price_lag{L}"] = gp.price_kg.shift(L)
    df["price_ma4"] = gp.price_kg.transform(lambda s: s.rolling(4, min_periods=2).mean())
    df["price_ma8"] = gp.price_kg.transform(lambda s: s.rolling(8, min_periods=4).mean())
    df["price_yoy"] = gp.price_kg.shift(52)
    df["qty_lag1"] = gp.qty_kg.shift(1)
    df["qty_ma4"] = gp.qty_kg.transform(lambda s: s.rolling(4, min_periods=2).mean())
    df["qty_yoy"] = df.qty_kg / gp.qty_kg.shift(52)
    df["chg_1w"] = np.log(df.price_kg / df.price_lag1)
    df["chg_4w"] = np.log(df.price_kg / df.price_lag4)
    n = nat.copy()
    n["nat_price_ma4"] = n.nat_price.rolling(4, min_periods=2).mean()
    n["nat_qty_ma4"] = n.nat_qty.rolling(4, min_periods=2).mean()
    n["nat_qty_yoy"] = n.nat_qty / n.nat_qty.shift(52)
    n["nat_chg_1w"] = np.log(n.nat_price / n.nat_price.shift(1))
    gk = df[df.whsl_mrkt_cd == GARAK].set_index("week")
    n["garak_price"] = gk.price_kg
    n["garak_price_ma4"] = gk.price_kg.rolling(4, min_periods=2).mean()
    df = df.merge(n, left_on="week", right_index=True, how="left")
    df["dev_nat"] = np.log(df.price_kg / df.nat_price)
    df["dev_garak"] = np.log(df.price_kg / df.garak_price)
    df["ratio_nat_med26"] = df.groupby("whsl_mrkt_cd").dev_nat.transform(lambda s: s.rolling(26, min_periods=8).median())
    df["qty_share"] = df.qty_kg / df.nat_qty
    df["weekofyear"] = df.week.dt.isocalendar().week.astype(int)
    df["month"] = df.week.dt.month
    df = pd.concat([df, holiday_feats(df.week)], axis=1)
    df["mkt_id"] = df.whsl_mrkt_cd.astype(int)
    for h in H:
        df[f"target_h{h}"] = df.groupby("whsl_mrkt_cd").price_kg.shift(-h)
        df[f"target_week_h{h}"] = df.week + pd.Timedelta(weeks=h)
    if markets is not None:
        df = df[df.whsl_mrkt_cd.isin(markets)]
    if item in HISTORY_START:
        df = df[df.week >= HISTORY_START[item]]
    return df[df.price_kg.notna()].reset_index(drop=True)   # 지난주 거래가 없으면 그 주는 예측하지 않는다


def oof_years(item: str) -> tuple[int, ...]:
    """OOF 검증 연도. 이력이 짧은 상품은 학습할 해가 생기는 연도부터."""
    start = pd.Timestamp(HISTORY_START.get(item, "2018-01-01")).year
    return tuple(y for y in (2021, 2022, 2023, 2024) if y >= start + 2)


def pick_markets(df: pd.DataFrame, min_cov=0.8, min_rec=20) -> pd.DataFrame:
    """학습 기간(2018~2023)만 보고 시장을 고른다. 테스트 기간은 보지 않는다."""
    tr = df[df.week <= "2023-12-31"]
    # 분모 = 전국에서 그 상품이 제철로 거래된 주 (전국 물량이 중앙값의 10% 이상). 연중 품목은 거의 모든 주
    nq = tr.drop_duplicates("week").set_index("week").nat_qty
    n_weeks = int((nq >= 0.1 * nq.median()).sum())
    s = tr.groupby(["whsl_mrkt_cd", "market_nm"]).agg(cov=("week", "nunique"), rec=("n_records", "median")).reset_index()
    s["cov"] = s["cov"] / n_weeks
    s["use"] = (s["cov"] >= min_cov) & (s["rec"] >= min_rec)
    return s


# ----------------------------------------------------------------------------- 모델
def X_of(df: pd.DataFrame, feats: list[str]) -> pd.DataFrame:
    X = df[feats].astype(float).copy()
    ref = df.price_kg.astype(float)
    for c in feats:
        if c in PRICE_LEVEL:
            X[c] = np.log(X[c] / ref)
    if "price_kg" in X:
        X["price_kg"] = np.log(ref)
    if "qty_kg" in X:
        X["qty_kg"] = np.log1p(X.qty_kg)
    for c in ("qty_lag1", "qty_ma4", "nat_qty", "nat_qty_ma4"):
        if c in X:
            X[c] = np.log1p(X[c])
    return X.replace([np.inf, -np.inf], np.nan)


def fit_pred(model: str, feats, trn, tst, h) -> np.ndarray:
    t = trn[trn[f"target_h{h}"].notna()]
    Xtr, Xte = X_of(t, feats), X_of(tst, feats)
    if model == "rf":  # RF는 결측을 못 받는다 → 학습 구간 중앙값
        med = Xtr.median().fillna(0)
        Xtr, Xte = Xtr.fillna(med), Xte.fillna(med)
    m = make_model(model, BP[model])
    m.fit(Xtr, np.log(t[f"target_h{h}"] / t.price_kg))
    return tst.price_kg.values * np.exp(m.predict(Xte))


def predict(models, feats, trn, tst) -> np.ndarray:
    return np.mean([np.column_stack([fit_pred(m, feats, trn, tst, h) for h in H]) for m in models], axis=0)


def hmean(df, P) -> float:
    return float(np.mean([nmae(df[f"target_h{h}"], P[:, j]) for j, h in enumerate(H)]))


def cv_score(df, feats, model="lgbm", years=(2021, 2022, 2023)) -> float:
    s = []
    for y in years:
        trn = df[df[f"target_week_h4"] <= f"{y - 1}-12-31"]
        val = df[(df.week >= f"{y}-01-01") & (df.target_week_h4 <= f"{y}-12-31")]
        s.append(hmean(val, predict([model], feats, trn, val)))
    return float(np.mean(s))


def backward(df, log) -> tuple[list[str], list]:
    """사과 때와 같은 규칙: 묶음을 하나씩 빼 보고, 0.0005 넘게 나빠지지 않으면 뺀다 (base는 유지)."""
    keep = [g for g in GROUPS if g != "base"]
    feats = lambda gs: sum((GROUPS[g] for g in ["base"] + gs), [])
    cur = cv_score(df, feats(keep)); hist = [("전체", round(cur, 4))]
    while True:
        trial = {g: cv_score(df, feats([k for k in keep if k != g])) for g in keep}
        g, sc = min(trial.items(), key=lambda kv: kv[1])
        if sc <= cur + 0.0005 and len(keep) > 1:
            keep.remove(g); cur = min(cur, sc); hist.append((f"-{g}", round(sc, 4))); log(f"   제거 {g}: {sc:.4f}")
        else:
            break
    return feats(keep), hist + [("선택", keep)]
