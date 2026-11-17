"""운영 설정(config/0601)·전처리 옵션·시장 선별 규칙 확인."""
from __future__ import annotations

import numpy as np
import pandas as pd

from farmit_ml.data import needed_features
from farmit_ml.preprocess import Preprocessor
from farmit_ml.selection import exclusion_reasons, market_table, pick_train_markets
from farmit_ml.settings import CONFIG_ROOT, HORIZONS, load_bundle


def test_item_config_is_common_feature_setup():
    """7장 실험 구성: 공통 피처 40개, h별 트리 3종 같은 비중, 통합 트리·LSTM·후처리 없음."""
    b = load_bundle(CONFIG_ROOT / "0601")
    used = {k for k, w in b.weights.items() if w > 0}
    assert used == {"RandomForest", "LightGBM", "XGBoost"}
    assert np.allclose([b.weights[k] for k in used], 1 / 3)
    assert b.pp_weights == {}
    assert len(b.tree_features) == 40 and "mkt_id" in b.tree_features
    assert not {"n_records", "garak_price", "price_kg_allgrade"} & set(b.tree_features)
    assert needed_features(b) == b.tree_features
    assert b.data_path.name == "weekly_0601.csv"


def test_preprocessor_log1p_inf_and_no_indicator():
    df = pd.DataFrame({"price_kg": [1000.0, 2000.0, 3000.0], "qty_kg": [0.0, 99.0, np.nan],
                       "qty_yoy": [np.inf, 1.0, 2.0], "market_cd": ["a", "b", "a"]})
    p = Preprocessor(["price_kg", "qty_kg", "qty_yoy"], fill="median", relative=True, market_dummies=False,
                     log1p=["qty_kg"], na_indicator=False)
    X = p.fit_transform(df)
    assert list(X.columns) == ["price_kg", "qty_kg", "qty_yoy"]          # 결측 표시·시장 더미 없음
    assert np.isclose(X.loc[1, "qty_kg"], np.log(100))
    assert np.isfinite(X.values).all()                                   # inf → 결측 → 학습 중앙값
    assert X.loc[0, "qty_yoy"] == 1.5


def _weekly(markets: dict[str, tuple[int, float]]) -> pd.DataFrame:
    """{시장: (거래 주 수, 거래일 수)} → 학습 기간 주간 행. 전국 물량은 매주 같다."""
    weeks = pd.date_range("2022-01-03", periods=100, freq="7D")
    rows = [{"market_cd": mc, "market_nm": mc, "week": w, "n_trade_days": days, "nat_qty": 1000.0}
            for mc, (n, days) in markets.items() for w in weeks[:n]]
    return pd.DataFrame(rows)


def test_pick_train_markets_uses_coverage_and_trade_days():
    df = _weekly({"full": (100, 6), "thin": (100, 3), "gappy": (70, 6)})
    sel = {"train_end": "2023-12-31", "min_coverage": 0.8, "min_trade_days": 4}
    s = pick_train_markets(df, sel).set_index("market_cd")
    assert s.loc["full", "train"] and not s.loc["thin", "train"] and not s.loc["gappy", "train"]


def test_market_table_serves_markets_that_beat_baseline_in_enough_years():
    """기준선을 4개 연도 중 3개 이상 이긴 시장만 노출한다."""
    rows, preds = [], []
    for mc, good_years in (("good", {2021, 2022, 2023}), ("bad", {2021, 2022})):
        for y in (2021, 2022, 2023, 2024):
            for k in range(10):
                last = 1000.0
                rows.append({"market_cd": mc, "market_nm": mc, "fold": y, "price_kg": last, "price_ma4": last,
                             **{f"target_h{h}": 1100.0 for h in HORIZONS}})
                preds.append([1090.0 if y in good_years else 1300.0] * len(HORIZONS))
    t = market_table(pd.DataFrame(rows), np.array(preds), min_wins=3).set_index("market_cd")
    assert t.loc["good", "wins"] == 3 and t.loc["good", "serve"]
    assert t.loc["bad", "wins"] == 2 and not t.loc["bad", "serve"]


def test_exclusion_reasons_explain_each_market_not_served():
    """학습에서 빠진 시장(커버리지·거래일)과 노출에서 빠진 시장(기준선) 모두 사유가 남고, 노출 시장은 없다."""
    nan = float("nan")
    res = pd.DataFrame([
        {"market_cd": "1", "market_nm": "가", "coverage": 1.0, "trade_days": 6, "train": True,
         "years": 4, "wins": 4, "base_name": "B1_last", "serve": True},
        {"market_cd": "2", "market_nm": "나", "coverage": 0.799, "trade_days": 3, "train": False,
         "years": nan, "wins": nan, "base_name": nan, "serve": nan},
        {"market_cd": "3", "market_nm": "다", "coverage": 1.0, "trade_days": 6, "train": True,
         "years": 4, "wins": 2, "base_name": "B2_ma4", "serve": False},
    ])
    r = exclusion_reasons(res, {"min_coverage": 0.8, "min_trade_days": 4, "min_wins": 3})
    assert set(r) == {"2", "3"}
    assert "79.9%" in r["2"] and "3일" in r["2"] and r["2"].startswith("나: 학습 제외")
    assert "4개 연도 중 2개" in r["3"] and "B2_ma4" in r["3"]
