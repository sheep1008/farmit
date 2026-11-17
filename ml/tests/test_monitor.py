"""예측 이력 채점 (farmit_ml.monitor): 실제 붙이기, 가장 최근 채점 주, 주간 지표. 가짜 표를 쓴다."""
from __future__ import annotations

import pandas as pd
import pytest

from farmit_ml import monitor


def _fc(rows):
    """(시장, 기준 주, h, 예측, 하한, 상한, 지난주 가격) → forecast 표."""
    fc = pd.DataFrame(rows, columns=["market_cd", "base_week", "horizon", "pred_price", "lower80", "upper80",
                                     "last_week_price"])
    fc["base_week"] = pd.to_datetime(fc["base_week"])
    fc["target_week"] = fc["base_week"] + pd.to_timedelta((fc["horizon"] - 1) * 7, unit="D")
    fc["model_version"] = "v4-test"
    return fc


WEEKLY = pd.DataFrame({
    "market_cd": ["A", "A", "B"], "market_nm": ["가", "가", "나"],
    "week": pd.to_datetime(["2026-11-02", "2026-11-09", "2026-11-09"]),
    "price_kg": [1000.0, 1100.0, 2000.0],
})


def test_compare_attaches_actual_and_leaves_future_empty():
    fc = _fc([("A", "2026-11-09", 1, 1000.0, 900.0, 1200.0, 1000.0),    # 대상 11/09: 실제 1100, 구간 안
              ("A", "2026-11-09", 2, 1050.0, 900.0, 1200.0, 1000.0)])   # 대상 11/16: 아직 실제 없음
    cmp = monitor.compare(fc, WEEKLY)
    assert cmp.loc[0, "actual"] == 1100.0
    assert cmp.loc[0, "error"] == -100.0
    assert cmp.loc[0, "abs_pct_error"] == pytest.approx(9.09)
    assert cmp.loc[0, "in_80"] == 1.0
    assert pd.isna(cmp.loc[1, "actual"]) and pd.isna(cmp.loc[1, "in_80"])
    assert monitor.latest_week(cmp) == pd.Timestamp("2026-11-09")


def test_unfinished_week_is_not_actual():
    """until(이번 주 월요일) 이후 주의 price_kg는 진행 중인 주의 며칠치라 실제로 치지 않는다."""
    fc = _fc([("A", "2026-11-09", 1, 1000.0, 900.0, 1200.0, 1000.0)])
    cmp = monitor.compare(fc, WEEKLY, until="2026-11-09")
    assert pd.isna(cmp.loc[0, "actual"])
    assert monitor.latest_week(cmp) is None


def test_latest_week_none_before_any_actual():
    cmp = monitor.compare(_fc([("A", "2026-11-16", 1, 1000.0, 900.0, 1200.0, 1100.0)]), WEEKLY)
    assert monitor.latest_week(cmp) is None


def test_week_metrics_vs_baseline_and_coverage():
    """11/09 대상: A h1(오차 100, 구간 안) + B h2(오차 400, 구간 밖). 기준선은 지난주 가격 그대로."""
    fc = _fc([("A", "2026-11-09", 1, 1000.0, 900.0, 1200.0, 1000.0),
              ("B", "2026-11-02", 2, 1600.0, 1500.0, 1900.0, 1800.0),
              ("A", "2026-11-02", 1, 990.0, 900.0, 1100.0, 950.0)])   # 다른 주(11/02) 대상은 섞이지 않는다
    m = monitor.week_metrics(monitor.compare(fc, WEEKLY), "2026-11-09")
    assert m["n_rows"] == 2 and m["n_markets"] == 2
    assert m["nmae"] == pytest.approx((100 + 400) / (1100 + 2000))
    assert m["base_nmae"] == pytest.approx((100 + 200) / (1100 + 2000))
    assert m["nmae_h1"] == pytest.approx(100 / 1100)
    assert m["nmae_h2"] == pytest.approx(400 / 2000)
    assert "nmae_h3" not in m
    assert m["coverage80"] == 0.5


def test_week_metrics_empty_week():
    cmp = monitor.compare(_fc([("A", "2026-11-09", 1, 1000.0, 900.0, 1200.0, 1000.0)]), WEEKLY)
    assert monitor.week_metrics(cmp, "2026-10-26") == {"n_rows": 0, "n_markets": 0}
