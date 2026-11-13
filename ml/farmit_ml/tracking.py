"""MLflow 기록 (REQ-PRD-004). 예측·평가 실행마다 설정·데이터 해시·git 커밋을 남긴다.

기본 저장소는 ml/mlruns/mlflow.db (커밋하지 않음). MLFLOW_TRACKING_URI로 서버를 가리킬 수 있다.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import asdict

import numpy as np

from .settings import ML_ROOT, MLFLOW_EXPERIMENT, MLFLOW_URI, Bundle


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ML_ROOT, capture_output=True,
                              text=True).stdout.strip()
    except OSError:
        return ""


def _mlflow():
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    logging.getLogger("mlflow").setLevel(logging.ERROR)
    import mlflow
    if MLFLOW_URI.startswith("sqlite:///"):
        (ML_ROOT / "mlruns").mkdir(exist_ok=True)
    mlflow.set_tracking_uri(MLFLOW_URI)
    if mlflow.get_experiment_by_name(MLFLOW_EXPERIMENT) is None:
        art = os.environ.get("MLFLOW_ARTIFACT_LOCATION", (ML_ROOT / "mlruns" / "artifacts").as_uri())
        mlflow.create_experiment(MLFLOW_EXPERIMENT, artifact_location=art)
    mlflow.set_experiment(MLFLOW_EXPERIMENT)
    return mlflow


def log_run(run_name: str, stage: str, bundle: Bundle, data_hash: str, metrics: dict | None = None,
            params: dict | None = None, artifacts: list | None = None) -> str:
    """실행 하나를 기록하고 run_id를 돌려준다. stage: forecast | evaluate | experiment."""
    mlflow = _mlflow()
    with mlflow.start_run(run_name=run_name) as run:
        mlflow.set_tags({"stage": stage, "model_version": bundle.version, "data_hash": data_hash,
                         "git_commit": _git_commit()})
        flat = {**{k: v for k, v in asdict(bundle).items()}, **(params or {})}
        mlflow.log_params({k: (json.dumps(v, ensure_ascii=False, default=str)[:6000]
                               if isinstance(v, (list, dict, tuple)) else v) for k, v in flat.items()})
        mlflow.log_metrics({k: float(v) for k, v in (metrics or {}).items() if v is not None and np.isfinite(v)})
        for a in artifacts or []:
            mlflow.log_artifact(str(a))
        return run.info.run_id
