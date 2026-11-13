"""경로·상수와 설정(config/*.json) 묶음.

모델 구성은 코드가 아니라 config/에서 바꾼다. 새 방식을 실험할 때는 config 폴더를 복사해
FARMIT_ML_CONFIG로 가리키면 기존 설정을 건드리지 않고 비교할 수 있다.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = Path(os.environ.get("FARMIT_ML_CONFIG", ML_ROOT / "config"))
DATA_PATH = Path(os.environ.get("FARMIT_ML_DATA", ML_ROOT / "data" / "apple_weekly.csv"))
OUTPUT_DIR = Path(os.environ.get("FARMIT_ML_OUTPUT", ML_ROOT / "outputs"))
MLFLOW_URI = os.environ.get("MLFLOW_TRACKING_URI", "sqlite:///" + (ML_ROOT / "mlruns" / "mlflow.db").as_posix())
MLFLOW_EXPERIMENT = os.environ.get("MLFLOW_EXPERIMENT", "apple-price")
# 학습 스레드 수. XGBoost·LSTM은 스레드 수가 바뀌면 결과가 조금 달라진다 → 참고 저장소와 같은 8로 고정
THREADS = int(os.environ.get("FARMIT_ML_THREADS", "8"))

# 트리 모델 약칭 → 앙상블 가중치(final_choice.json)에 쓰는 이름
TREE_NAMES = {"rf": "RandomForest", "lgbm": "LightGBM", "xgb": "XGBoost"}
STACKED_SUFFIX = "(통합)"   # horizon 통합 모델 이름 꼬리표. 예: "LightGBM(통합)"
LSTM_NAME = "LSTM"


def _read(config_dir: Path, name: str):
    return json.loads((config_dir / f"{name}.json").read_text(encoding="utf-8"))


_MODEL = _read(CONFIG_DIR, "model")
HORIZONS: tuple[int, ...] = tuple(_MODEL["horizons"])
MARKETS: dict[str, str] = _MODEL["markets"]
SEED: int = _MODEL["seed"]


@dataclass
class Bundle:
    """예측 한 번에 필요한 설정 전부. load_bundle()로 만든다."""
    version: str
    item_code: str
    lstm_seeds: int
    target_mode: str
    tree_features: list[str]
    tree_prep: dict
    lin_features: list[str]
    lin_prep: dict
    best_params: dict      # h별 트리 모델 하이퍼파라미터 {rf|lgbm|xgb: {...}}
    stack_params: dict     # horizon 통합 트리 모델 하이퍼파라미터
    lstm_params: dict
    weights: dict          # 앙상블 가중치 {모델 이름: w}, 합 1
    pp_weights: dict       # 후처리 시장별 w {market_cd: w}
    pp_n_weeks: int
    interval_q: dict       # {h: (하한 상대잔차, 상한 상대잔차)}
    interval_level: float


def load_bundle(config_dir: Path | str = CONFIG_DIR) -> Bundle:
    d = Path(config_dir)
    model, pre, fin, pp = _read(d, "model"), _read(d, "preprocess"), _read(d, "final_choice"), _read(d, "postprocess")
    w = fin["weights"]
    if abs(sum(w.values()) - 1) > 1e-6:
        raise ValueError(f"final_choice.json 가중치 합이 1이 아니다: {sum(w.values())}")
    return Bundle(
        version=model["version"], item_code=model["item_code"], lstm_seeds=model["lstm_seeds"],
        target_mode=pre["target_mode"],
        tree_features=pre["tree"]["features"], tree_prep=pre["tree"]["prep"],
        lin_features=pre["linear"]["features"], lin_prep=pre["linear"]["prep"],
        best_params=_read(d, "best_params"), stack_params=_read(d, "stack_params"), lstm_params=_read(d, "lstm_params"),
        weights=w, pp_weights=pp["weights"], pp_n_weeks=pp["n_weeks"],
        interval_q={int(h): tuple(q) for h, q in model["interval"]["quantiles"].items()},
        interval_level=model["interval"]["level"],
    )
