"""모델 레지스트리 (farmit_ml.registry): 승격 판정, 백테스트 누수 없음, 등록 → 승격 흐름 (임시 SQLite 레지스트리)."""
from __future__ import annotations

import dataclasses
import json
import shutil

import pandas as pd
import pytest

from farmit_ml import forecast, registry, tracking
from farmit_ml.settings import CONFIG_ROOT, HORIZONS

TREES = {"RandomForest", "LightGBM", "XGBoost"}


def _rows(preds, actual=1000.0, last=1100.0):
    """시장 A·B × 기준 주 1개 × h1 → 백테스트 결과 모양 표. preds: {시장: 예측}."""
    return pd.DataFrame([{"market_cd": m, "base_week": pd.Timestamp("2026-11-02"), "horizon": 1,
                          "pred_price": p, "actual": actual, "last_week_price": last} for m, p in preds.items()])


def test_decide_needs_to_beat_champion_and_baseline():
    champ = _rows({"A": 1080.0, "B": 1080.0})                 # NMAE 0.08, 기준선 0.10
    ok, r = registry.decide(champ, _rows({"A": 1050.0, "B": 1050.0}))
    assert ok and r["challenger_nmae"] == pytest.approx(0.05) and r["base_nmae"] == pytest.approx(0.10)
    assert not registry.decide(champ, _rows({"A": 1090.0, "B": 1090.0}))[0]        # champion보다 나쁨
    good_champ = _rows({"A": 1000.0, "B": 1000.0}, last=1020.0)                     # 기준선 0.02
    assert not registry.decide(_rows({"A": 1200.0, "B": 1200.0}, last=1020.0),
                               _rows({"A": 1030.0, "B": 1030.0}, last=1020.0))[0]   # champion은 이겨도 기준선에 짐
    assert not registry.decide(good_champ, good_champ)[0]                           # 같으면 바꾸지 않는다


def test_decide_compares_common_rows_only():
    """challenger만 예측하는 시장(C)과 실제가 없는 행은 비교에서 빠진다."""
    champ = _rows({"A": 1080.0})
    chall = pd.concat([_rows({"A": 1050.0}), _rows({"C": 5000.0})])
    champ.loc[len(champ)] = {**champ.iloc[0], "horizon": 2, "actual": float("nan")}
    ok, r = registry.decide(champ, chall)
    assert ok and r["n_rows"] == 1 and r["n_markets"] == 1


def test_decide_without_common_rows_keeps_champion():
    ok, r = registry.decide(_rows({"A": 1080.0}), _rows({"B": 1000.0}))
    assert not ok and r["n_rows"] == 0


def test_backtest_scores_past_weeks_only(weekly, bundle):
    # 운영 설정(v4)처럼 h별 트리 3종만 쓴다 (LSTM은 torch가 없는 Airflow 가상환경에서도 돌게 뺀다)
    bundle = dataclasses.replace(bundle, weights={k: (1 / 3 if k in TREES else 0.0) for k in bundle.weights})
    until = pd.Timestamp("2023-03-06")
    rows = registry.backtest(bundle, weekly, until, weeks=2)
    assert sorted(rows["base_week"].unique()) == [until - pd.Timedelta(weeks=2), until - pd.Timedelta(weeks=1)]
    assert len(rows) == 2 * len(bundle.serve_markets) * len(HORIZONS)
    assert rows.loc[rows["target_week"] >= until, "actual"].isna().all()    # 진행 중인 주는 실제로 치지 않는다
    assert rows.loc[rows["target_week"] < until, "actual"].notna().all()


@pytest.fixture
def mlflow_tmp(tmp_path, monkeypatch):
    """임시 SQLite 추적·레지스트리. ml/mlruns를 건드리지 않는다."""
    pytest.importorskip("mlflow")
    monkeypatch.setattr(tracking, "MLFLOW_URI", f"sqlite:///{(tmp_path / 'mlflow.db').as_posix()}")
    monkeypatch.setenv("MLFLOW_ARTIFACT_LOCATION", (tmp_path / "artifacts").as_uri())
    return tmp_path


def _config(tmp_path, name, version):
    d = tmp_path / name
    shutil.copytree(CONFIG_ROOT / "0601_v3", d)
    m = json.loads((d / "model.json").read_text(encoding="utf-8"))
    (d / "model.json").write_text(json.dumps({**m, "version": version}), encoding="utf-8")
    # 운영 설정(v4)처럼 h별 트리 3종만 (torch 없는 환경에서도 돌게), 테스트가 빠르게 트리 크기도 줄인다
    fin = json.loads((d / "final_choice.json").read_text(encoding="utf-8"))
    fin["weights"] = {k: (1 / 3 if k in TREES else 0.0) for k in fin["weights"]}
    (d / "final_choice.json").write_text(json.dumps(fin), encoding="utf-8")
    bp = json.loads((d / "best_params.json").read_text(encoding="utf-8"))
    for m_, n in {"lgbm": 20, "xgb": 20, "rf": 10}.items():
        bp[m_]["n_estimators"] = n
    (d / "best_params.json").write_text(json.dumps(bp), encoding="utf-8")
    return d


def test_forecast_uses_champion_config(mlflow_tmp, weekly, monkeypatch):
    """--item만 주면 champion 설정으로 예측하고, model_version에 레지스트리 버전이 남는다."""
    registry.register(_config(mlflow_tmp, "a", "v4"), registry.CHAMPION)
    registry.register(_config(mlflow_tmp, "b", "v5"), registry.CHAMPION)   # 손으로 바로 champion (되돌리기와 같은 경로)
    data = mlflow_tmp / "weekly.csv"
    weekly.to_csv(data, index=False)
    monkeypatch.delenv("FARMIT_ML_CONFIG", raising=False)
    monkeypatch.setattr(forecast, "OUTPUT_DIR", mlflow_tmp / "out")
    out = mlflow_tmp / "fc.csv"
    forecast.main(["--item", "0601", "--data", str(data), "--out", str(out)])
    assert pd.read_csv(out)["model_version"].str.startswith("v5-r2-").all()


def test_register_and_promote(mlflow_tmp, weekly, monkeypatch):
    """champion·challenger 등록 → 백테스트(가짜) 결과에 따라 별칭이 옮겨지고 challenger 별칭은 지워진다."""
    registry.register(_config(mlflow_tmp, "a", "v4"), registry.CHAMPION)
    registry.register(_config(mlflow_tmp, "b", "v5"))
    client = registry._client()
    assert registry.get_version(client, "0601", registry.CHALLENGER).tags["model_version"] == "v5"

    preds = {"v4": 1080.0, "v5": 1050.0}   # challenger(v5)가 champion·기준선을 모두 이긴다
    monkeypatch.setattr(registry, "load_data", lambda path, markets=None: weekly)
    monkeypatch.setattr(registry, "data_hash", lambda path: "test")
    monkeypatch.setattr(registry, "backtest", lambda b, df, until, weeks: _rows({"A": preds[b.version]}))
    assert registry.promote("0601", until="2026-11-16") is True

    champ = registry.get_version(client, "0601", registry.CHAMPION)
    assert champ.tags["model_version"] == "v5" and champ.tags["promote_result"].startswith("promoted")
    assert registry.get_version(client, "0601", registry.CHALLENGER) is None
    assert registry.promote("0601") is None   # 판정이 끝나면 다시 돌지 않는다

    # 등록한 설정을 그대로 받아 읽을 수 있다 (주간 예측이 champion 설정을 쓰는 경로)
    b = registry.load_bundle(registry.download(champ, mlflow_tmp / "dl"))
    assert b.version == "v5" and b.markets


def test_promote_rejects_worse_challenger(mlflow_tmp, weekly, monkeypatch):
    registry.register(_config(mlflow_tmp, "a", "v4"), registry.CHAMPION)
    registry.register(_config(mlflow_tmp, "b", "v5"))
    preds = {"v4": 1050.0, "v5": 1080.0}
    monkeypatch.setattr(registry, "load_data", lambda path, markets=None: weekly)
    monkeypatch.setattr(registry, "data_hash", lambda path: "test")
    monkeypatch.setattr(registry, "backtest", lambda b, df, until, weeks: _rows({"A": preds[b.version]}))
    assert registry.promote("0601", until="2026-11-16") is False

    client = registry._client()
    assert registry.get_version(client, "0601", registry.CHAMPION).tags["model_version"] == "v4"
    assert registry.get_version(client, "0601", registry.CHALLENGER) is None
