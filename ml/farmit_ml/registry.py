"""모델 레지스트리: 설정 묶음(config/<품목>/*.json)을 MLflow 등록 모델 버전으로 관리하고, 백테스트로 승격한다 (K40, REQ-PRD-004).

    python -m farmit_ml.registry register --config config/0601 --champion   # 처음 한 번: 지금 운영 설정을 champion으로
    python -m farmit_ml.registry register --config config/0601_v5           # 새 설정을 challenger로 올린다
    python -m farmit_ml.registry promote --item 0601                        # challenger가 있으면 백테스트 후 승격 판정
    python -m farmit_ml.registry show --item 0601                           # 버전·별칭·판정 결과 보기

- 등록 대상이 모델 파일이 아닌 이유: forecast.py는 저장된 모델을 쓰지 않고 매주 그 설정으로 처음부터 다시 학습한다 (docs/ml.md 8.1).
  같은 설정이면 이번 주 모델과 지난주 모델은 데이터 한 주 차이뿐이라 비교할 것이 없다. 바뀌는 것은 설정(피처·하이퍼파라미터·가중치·시장·구간)이다.
- 등록 모델 이름은 farmit-<품목코드>, 별칭 두 개:
    champion    운영 설정. 주간 예측이 쓴다
    challenger  승격을 기다리는 새 설정. promote가 판정하면 (승격이든 탈락이든) 별칭을 지운다 → 같은 판정을 매주 다시 하지 않는다
- 승격 조건 (docs/ml.md 8.1 "설정 교체 조건"): 최근 WEEKS주 백테스트에서 challenger NMAE가 champion보다 낮고, 기준선(지난주 가격 그대로)보다도 낮다.
  두 설정이 모두 예측을 내는 (시장, 기준 주, h) 행끼리만 비교한다. 노출 시장이 달라도 같은 문제로 채점하기 위해서다.
"""
from __future__ import annotations

import argparse
import logging
import tempfile
from pathlib import Path

import pandas as pd

from . import forecast, monitor
from .data import data_hash, load_data
from .metrics import nmae
from .settings import Bundle, load_bundle

log = logging.getLogger("farmit_ml.registry")

CHAMPION, CHALLENGER = "champion", "challenger"
WEEKS = 8   # 백테스트 기준 주 수. docs/ml.md 8.1 운영 감시의 "최근 8주"와 같게 둔다
KEY = ["market_cd", "base_week", "horizon"]


def model_name(item_code: str) -> str:
    return f"farmit-{item_code}"


def _client():
    from mlflow import MlflowClient

    from .tracking import _mlflow
    _mlflow()   # 추적 URI·실험을 tracking.py와 같게 맞춘다 (SQLite면 레지스트리도 같은 파일에 들어간다)
    return MlflowClient()


def get_version(client, item_code: str, alias: str):
    """별칭이 가리키는 버전. 등록 모델이나 별칭이 없으면 None."""
    from mlflow.exceptions import MlflowException
    try:
        return client.get_model_version_by_alias(model_name(item_code), alias)
    except MlflowException:
        return None


def download(mv, dst: Path | str) -> Path:
    """버전에 담긴 설정 폴더를 dst에 받아 그 경로를 돌려준다. load_bundle()에 그대로 넘긴다."""
    import mlflow
    return Path(mlflow.artifacts.download_artifacts(artifact_uri=mv.source, dst_path=str(dst)))


def champion_config(item_code: str, dst: Path | str) -> tuple[Path, str] | None:
    """champion 설정을 dst에 받아 (설정 폴더, 레지스트리 버전)을 돌려준다. champion이 없으면 None (config/<품목>을 쓴다)."""
    mv = get_version(_client(), item_code, CHAMPION)
    if mv is None:
        return None
    return download(mv, dst), mv.version


def register(config: Path | str, alias: str = CHALLENGER) -> str:
    """설정 폴더의 json을 실행 하나에 올리고 그 산출물을 등록 모델의 새 버전으로 만든다. 버전 번호를 돌려준다."""
    from mlflow.exceptions import MlflowException

    from .tracking import log_run
    config = Path(config)
    b = load_bundle(config)   # 읽히지 않는 설정은 등록하지 않는다
    if not b.markets:
        raise ValueError(f"{config}/markets.json이 없다. 먼저 python -m farmit_ml.selection --item {b.item_code}")
    client = _client()
    name = model_name(b.item_code)
    try:
        client.get_registered_model(name)
    except MlflowException:
        client.create_registered_model(name, description=f"{b.item_code} 주간 가격 예측 설정 묶음 (farmit_ml.registry)")
    dh = data_hash(b.data_path) if b.data_path.exists() else ""
    run_id = log_run(f"register {b.item_code} {b.version}", "register", b, dh, artifacts=sorted(config.glob("*.json")))
    source = client.get_run(run_id).info.artifact_uri
    mv = client.create_model_version(name, source=source, run_id=run_id,
                                     tags={"model_version": b.version, "config_path": config.as_posix()})
    client.set_registered_model_alias(name, alias, mv.version)
    log.info("%s 버전 %s 등록 (%s, %s) → %s", name, mv.version, b.version, config.as_posix(), alias)
    return mv.version


def backtest(b: Bundle, df: pd.DataFrame, until, weeks: int = WEEKS) -> pd.DataFrame:
    """until(월요일) 앞 weeks개 기준 주를 그 시점까지의 데이터로만 다시 예측하고(forecast.run의 as_of) 실제를 붙인다.

    until부터의 주는 진행 중이라 실제로 치지 않는다 (monitor.compare와 같다). 마지막 기준 주들의 h3·h4처럼
    대상 주가 아직 안 끝난 행은 actual이 비어 채점에서 빠진다.
    """
    until = pd.Timestamp(until)
    bases = [until - pd.Timedelta(weeks=k) for k in range(weeks, 0, -1)]
    fc = pd.concat([forecast.run(df, b, base) for base in bases], ignore_index=True)
    fc["base_week"] = pd.to_datetime(fc["base_week"])
    fc["target_week"] = pd.to_datetime(fc["target_week"])
    return monitor.compare(fc, df, until=until)


def decide(champ: pd.DataFrame, chall: pd.DataFrame) -> tuple[bool, dict]:
    """두 백테스트 결과를 같은 행끼리 비교한다. (승격 여부, 지표)."""
    m = champ[KEY + ["actual", "pred_price", "last_week_price"]].merge(
        chall[KEY + ["pred_price"]], on=KEY, suffixes=("_champion", "_challenger"))
    m = m[m["actual"].notna()]
    r = {"n_rows": len(m), "n_markets": m["market_cd"].nunique()}
    if m.empty:
        return False, r
    r["champion_nmae"] = nmae(m["actual"], m["pred_price_champion"])
    r["challenger_nmae"] = nmae(m["actual"], m["pred_price_challenger"])
    r["base_nmae"] = nmae(m["actual"], m["last_week_price"])
    return r["challenger_nmae"] < min(r["champion_nmae"], r["base_nmae"]), r


def promote(item_code: str, until=None, weeks: int = WEEKS) -> bool | None:
    """challenger가 있으면 champion과 백테스트해 승격을 판정한다. challenger가 없으면 None (할 일 없음)."""
    from .tracking import log_run
    client = _client()
    name = model_name(item_code)
    chall = get_version(client, item_code, CHALLENGER)
    if chall is None:
        log.info("%s challenger가 없다. 판정하지 않는다", name)
        return None
    champ = get_version(client, item_code, CHAMPION)
    if champ is None:
        raise SystemExit(f"{name} champion이 없다. 먼저 register --config config/{item_code} --champion")
    until = pd.Timestamp(until) if until else monitor.this_monday()

    with tempfile.TemporaryDirectory() as tmp:
        bc = load_bundle(download(champ, Path(tmp) / "champion"))
        bh = load_bundle(download(chall, Path(tmp) / "challenger"))
        log.info("%s 백테스트: champion v%s(%s) vs challenger v%s(%s), %s 앞 %d주",
                 name, champ.version, bc.version, chall.version, bh.version, until.date(), weeks)
        rows_c = backtest(bc, load_data(bc.data_path, bc.markets), until, weeks)
        rows_h = backtest(bh, load_data(bh.data_path, bh.markets), until, weeks)
        ok, r = decide(rows_c, rows_h)
        log_run(f"promote {item_code} v{chall.version}", "promote", bh, data_hash(bh.data_path), metrics=r,
                params={"champion": champ.version, "challenger": chall.version, "until": str(until.date()),
                        "weeks": weeks, "promoted": ok})

    result = "promoted" if ok else "rejected"
    client.set_model_version_tag(name, chall.version, "promote_result",
                                 f"{result} {until.date()} " + " ".join(f"{k}={v:.4f}" for k, v in r.items()
                                                                        if k.endswith("nmae")))
    if ok:
        client.set_registered_model_alias(name, CHAMPION, chall.version)
    client.delete_registered_model_alias(name, CHALLENGER)
    log.info("%s v%s %s: %s", name, chall.version, result, {k: round(v, 4) for k, v in r.items()})
    return ok


def show(item_code: str) -> None:
    client = _client()
    name = model_name(item_code)
    aliases = {}
    for a in (CHAMPION, CHALLENGER):
        mv = get_version(client, item_code, a)
        if mv is not None:
            aliases[mv.version] = a
    for mv in sorted(client.search_model_versions(f"name='{name}'"), key=lambda v: int(v.version)):
        print(f"v{mv.version:<3} {aliases.get(mv.version, ''):<11} {mv.tags.get('model_version', ''):<6} "
              f"{mv.tags.get('config_path', ''):<20} {mv.tags.get('promote_result', '')}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="설정 묶음 등록·승격 (MLflow 모델 레지스트리)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("register", help="설정 폴더를 새 버전으로 등록 (기본 별칭 challenger)")
    r.add_argument("--config", required=True, help="설정 폴더 (예: config/0601_v5)")
    r.add_argument("--champion", action="store_true", help="판정 없이 바로 champion으로 (처음 등록·되돌리기용)")
    p = sub.add_parser("promote", help="challenger가 있으면 백테스트 후 승격 판정")
    p.add_argument("--item", required=True)
    p.add_argument("--until", help="백테스트 끝(이 월요일 앞까지, YYYY-MM-DD). 없으면 한국 날짜로 이번 주 월요일")
    p.add_argument("--weeks", type=int, default=WEEKS)
    s = sub.add_parser("show", help="버전·별칭·판정 결과")
    s.add_argument("--item", required=True)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if a.cmd == "register":
        register(a.config, CHAMPION if a.champion else CHALLENGER)
    elif a.cmd == "promote":
        promote(a.item, a.until, a.weeks)
    else:
        show(a.item)


if __name__ == "__main__":
    main()
