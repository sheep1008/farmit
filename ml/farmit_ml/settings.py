"""경로·상수와 설정(config/<품목>/*.json) 묶음.

모델 구성은 코드가 아니라 설정 폴더에서 바꾼다. 품목마다 폴더가 하나다:
    config/<품목코드>/          그 품목의 운영 설정 (--item <품목코드>)
    config/<품목코드>_<버전>/   이전 버전 보관 (예: config/0601_v3). --config로 가리켜 재현·비교한다
새 방식을 실험할 때는 폴더를 복사해 --config(또는 FARMIT_ML_CONFIG)로 가리키면 기존 설정을 건드리지 않고 비교할 수 있다.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = ML_ROOT / "config"
DATA_DIR = ML_ROOT / "data"
OUTPUT_DIR = Path(os.environ.get("FARMIT_ML_OUTPUT", ML_ROOT / "outputs"))
MLFLOW_URI = os.environ.get("MLFLOW_TRACKING_URI", "sqlite:///" + (ML_ROOT / "mlruns" / "mlflow.db").as_posix())
MLFLOW_EXPERIMENT = os.environ.get("MLFLOW_EXPERIMENT", "apple-price")
# 학습 스레드 수. XGBoost·LSTM은 스레드 수가 바뀌면 결과가 조금 달라진다 → 참고 저장소와 같은 8로 고정
THREADS = int(os.environ.get("FARMIT_ML_THREADS", "8"))

# 모든 품목 공통. forecast 테이블 계약(h1~h4)과 데이터셋 컬럼(target_h1~4)이 이 값에 묶여 있다
HORIZONS: tuple[int, ...] = (1, 2, 3, 4)
SEED = 42

# 트리 모델 약칭 → 앙상블 가중치(final_choice.json)에 쓰는 이름
TREE_NAMES = {"rf": "RandomForest", "lgbm": "LightGBM", "xgb": "XGBoost"}
STACKED_SUFFIX = "(통합)"   # horizon 통합 모델 이름 꼬리표. 예: "LightGBM(통합)"
LSTM_NAME = "LSTM"


def _read(config_dir: Path, name: str):
    return json.loads((config_dir / f"{name}.json").read_text(encoding="utf-8"))


def config_dir(item: str | None = None, config: str | Path | None = None) -> Path:
    """설정 폴더: --config > FARMIT_ML_CONFIG > config/<item>. 셋 다 없으면 멈춘다 (품목을 코드에 고정하지 않는다)."""
    if config or os.environ.get("FARMIT_ML_CONFIG"):
        return Path(config or os.environ["FARMIT_ML_CONFIG"])
    if not item:
        raise ValueError("품목을 정하지 않았다: --item <품목코드> 또는 --config <설정 폴더>")
    return CONFIG_ROOT / item


@dataclass
class Bundle:
    """예측 한 번에 필요한 설정 전부. load_bundle()로 만든다."""
    version: str
    item_code: str
    data_file: str         # 입력 데이터셋 파일 이름 (data/ 아래). 기본 weekly_<품목>.csv
    markets: dict          # 학습 시장 {market_cd: 이름}. 순서가 시장 더미·LSTM 임베딩 순서다
    serve_markets: list    # 예측을 내보내는(forecast 저장) 시장. markets의 부분집합
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
    interval_q: dict       # {market_cd 또는 "*": {h: (하한 상대잔차, 상한 상대잔차)}}. "*"는 모든 시장 공통(대체값)
    interval_level: float
    selection: dict        # 학습·노출 시장 선별 규칙 (model.json의 selection, farmit_ml.selection이 쓴다)
    config_path: str       # 이 설정을 읽은 폴더

    @property
    def data_path(self) -> Path:
        return Path(os.environ.get("FARMIT_ML_DATA", DATA_DIR / self.data_file))


def add_config_args(ap) -> None:
    """forecast·evaluate 공통 인자: 품목(→ 설정 폴더·데이터 파일), 설정 폴더, 데이터 경로, 뺄 구성 모델."""
    ap.add_argument("--item", help="품목 코드 (예: 0601). config/<품목>/ 설정과 data/weekly_<품목>.csv를 쓴다")
    ap.add_argument("--config", help="설정 폴더 (예: config/0601_v3). --item보다 우선")
    ap.add_argument("--data", help="주간 데이터셋 CSV. 없으면 설정의 data_file")
    ap.add_argument("--skip", nargs="*", default=[], help="뺄 구성 모델 이름 (예: LSTM). 나머지 가중치로 다시 나눈다")


def bundle_from_args(a) -> tuple[Bundle, Path]:
    """인자로 설정을 읽고 (설정, 데이터 경로)를 돌려준다. --skip한 모델은 가중치에서 뺀다."""
    b = load_bundle(config_dir(a.item, a.config))
    if a.item and a.item != b.item_code:
        raise ValueError(f"--item {a.item}과 설정의 item_code {b.item_code}가 다르다")
    if not b.markets:
        raise ValueError(f"{b.config_path}/markets.json이 없다. 먼저 python -m farmit_ml.selection --item {b.item_code}")
    for k in a.skip:
        b.weights.pop(k)
    return b, Path(a.data) if a.data else b.data_path


def _interval_q(d: Path, interval: dict) -> dict:
    """80% 구간 분위수. intervals.json(farmit_ml.intervals, 시장 × h)이 있으면 그것을,
    없으면 model.json의 interval.quantiles(h별, 모든 시장 공통 "*")를 쓴다."""
    if (d / "intervals.json").exists():
        q = _read(d, "intervals")["quantiles"]
    elif "quantiles" in interval:
        q = {"*": interval["quantiles"]}
    else:
        return {}   # 아직 없음 (farmit_ml.intervals가 만든다). 예측할 때 멈춘다
    if "*" not in q:
        raise ValueError("80% 구간에 모든 시장 공통 값(\"*\")이 없다")
    return {m: {int(h): tuple(v) for h, v in hq.items()} for m, hq in q.items()}


def load_bundle(d: Path | str) -> Bundle:
    d = Path(d)
    model, pre, fin, pp = (_read(d, n) for n in ("model", "preprocess", "final_choice", "postprocess"))
    # markets.json은 farmit_ml.selection이 만든다. 아직 없으면 비워 두고, 예측·평가에서 멈춘다
    mk = _read(d, "markets") if (d / "markets.json").exists() else {"train": {}, "serve": []}
    w = fin["weights"]
    if abs(sum(w.values()) - 1) > 1e-6:
        raise ValueError(f"final_choice.json 가중치 합이 1이 아니다: {sum(w.values())}")
    if tuple(model["horizons"]) != HORIZONS or model["seed"] != SEED:
        raise ValueError(f"model.json horizons·seed는 {HORIZONS}·{SEED}이어야 한다 (forecast 테이블 계약)")
    extra = sorted(set(mk["serve"]) - set(mk["train"]))
    if extra:
        raise ValueError(f"markets.json serve에 학습하지 않는 시장이 있다: {extra}")
    item = model["item_code"]
    return Bundle(
        version=model["version"], item_code=item, data_file=model.get("data_file", f"weekly_{item}.csv"),
        markets=mk["train"], serve_markets=list(mk["serve"]), lstm_seeds=model["lstm_seeds"],
        target_mode=pre["target_mode"],
        tree_features=pre["tree"]["features"], tree_prep=pre["tree"]["prep"],
        lin_features=pre["linear"]["features"], lin_prep=pre["linear"]["prep"],
        best_params=_read(d, "best_params"), stack_params=_read(d, "stack_params"), lstm_params=_read(d, "lstm_params"),
        weights=w, pp_weights=pp["weights"], pp_n_weeks=pp["n_weeks"],
        interval_q=_interval_q(d, model["interval"]),
        interval_level=model["interval"]["level"],
        selection=model.get("selection", {}), config_path=str(d),
    )
