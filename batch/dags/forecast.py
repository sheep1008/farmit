"""주간 예측 DAG (K19, REQ-PRD-001·004·005). 매주 일 23:00 UTC(한국 월 08:00).

    check ─ features ─┬─ forecast_items ─ forecast ─ monitor (품목마다 한 태스크)
    check_weather ────┴─ past_case

1. check      예측 피처가 쓰는 원천만 본다 (collectors/weather/check.py --only price holiday, K09):
              지난주(월~일, 한국 날짜)에 예측 품목 정산이 있는가, 4주 뒤까지 공휴일이 있는가.
              운영 모델 v4는 날씨·생산량을 쓰지 않아 그것이 빠졌다고 예측을 막지 않는다.
              빠지면 종료 코드 1 → 태스크 실패 → 뒤 태스크는 돌지 않는다 (upstream_failed). 무엇이 빠졌는지는 태스크 로그에 남는다.
              재시도(10분 간격 2번)는 collect_daily(일 22:00 UTC)가 늦게 끝난 경우를 위한 것이다.
   check_weather  주산지 날씨가 빠짐없는가 (--only weather). 과거 사례의 날씨 사건에만 쓰므로 past_case 앞에만 둔다.
2. features   Spark 주간 집계 + 피처 → ml/data/weekly_<품목코드>.csv (batch/spark/features.py, K12·K30)
3. forecast   예측 품목(item.is_forecast)마다 farmit_ml.forecast --to-db (K13). 기준 주까지의 전체 데이터로 다시 학습하고
              serve 시장 × h1~h4를 forecast 테이블에 UPSERT한다. 같은 기준 주를 다시 돌려도 행이 늘지 않고 지난 기준 주는 남는다.
              기준 주(--base-week)를 이번 주 월요일로 꼭 넘긴다: 지난주 정산이 통째로 없으면 데이터의 마지막 주가 한 주 앞이 되는데,
              그대로 두면 지난 기준 주를 조용히 다시 예측한다. 넘기면 "예측에 쓸 행이 없다"로 실패한다.
   monitor    품목마다 farmit_ml.monitor (REQ-PRD-005): 지난 예측 vs 실제 주평균 → ml/outputs/monitor_<품목>.csv,
              지난주가 대상인 예측들의 오차(h별 NMAE·기준선·80% 커버리지)를 MLflow에 기록한다.
              이번 주 예측과 상관없이 채점할 수 있으므로 forecast가 실패해도 돈다 (all_done).
4. past_case  과거 사례 리포트를 통째로 다시 계산 (batch/spark/past_case.py, K18). 예측과는 상관없고 forecast와 나란히 돈다.
              점검이나 피처가 실패하면 이번 주는 돌지 않는다 (지난주 결과가 그대로 남는다).

예전 build_features_weekly DAG(features만, 같은 시각)는 이 DAG에 합쳤다. 시각 차이로 순서를 맞추지 않고 의존성으로 잇는다.
"""
import sys
from datetime import timedelta
from zoneinfo import ZoneInfo

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG, task

COLLECTORS = "/opt/farmit/collectors"   # compose가 붙여 둔 곳 (읽기 전용)
SPARK = "/opt/farmit/spark"             # batch/spark (읽기 전용)
ML = "/opt/farmit/ml"                   # ml/ (config 읽기, data·outputs·mlruns 쓰기)
ML_PYTHON = "/home/airflow/ml-venv/bin/python"   # 예측 전용 가상환경 (batch/airflow/Dockerfile)
KST = ZoneInfo("Asia/Seoul")


def kst_monday(run_after):
    """실행 예정 시각(run_after) 기준 한국 날짜로 이번 주 월요일 = 예측 기준 주(base_week).

    피처 한 행(week = W)은 pred_date = W + 7일에 예측한다 (features.py). 지난주 행의 pred_date가 이번 주 월요일이다.
    logical_date가 아니라 run_after를 쓰는 이유: Airflow 3에서 손으로 실행(trigger)한 run은 logical_date가 비어 있다.
    """
    d = run_after.astimezone(KST).date()
    return (d - timedelta(days=d.weekday())).isoformat()


def kst_last_sunday(run_after):
    """점검 기간의 끝 = 기준 주 바로 전 일요일 (한국 날짜)."""
    d = run_after.astimezone(KST).date()
    return (d - timedelta(days=d.weekday() + 1)).isoformat()


with DAG(
    "forecast_weekly",
    schedule="0 23 * * 0",
    start_date=pendulum.datetime(2026, 11, 1, tz="UTC"),
    catchup=False,           # 놓친 주는 손으로 --base-week를 넘겨 다시 돌린다 (docs/ml.md 5장)
    max_active_runs=1,       # 같은 CSV·forecast 행을 쓰므로 한 번에 하나만
    default_args={"retries": 2, "retry_delay": timedelta(minutes=10), "execution_timeout": timedelta(minutes=30)},
    user_defined_macros={"kst_monday": kst_monday, "kst_last_sunday": kst_last_sunday},
    tags=["batch", "ml"],
):
    base_week = "{{ kst_monday(dag_run.run_after) }}"

    def check_task(task_id, only):
        until = "{{ kst_last_sunday(dag_run.run_after) }}"
        return BashOperator(task_id=task_id,
                            bash_command=f"cd {COLLECTORS} && python -m weather.check --until {until} --only {only}")

    check = check_task("check", "price holiday")                  # 예측 피처가 쓰는 원천 (docs/ml.md 3.1절)
    check_weather = check_task("check_weather", "weather")        # 과거 사례의 날씨 사건
    features = BashOperator(task_id="features", bash_command=f"cd {SPARK} && python -m features")
    past_case = BashOperator(task_id="past_case", bash_command=f"cd {SPARK} && python -m past_case")

    @task
    def forecast_items() -> list[str]:
        """예측할 품목(item.is_forecast) 코드. 품목 코드는 코드에 쓰지 않고 테이블에서 읽는다 (CLAUDE.md 2절)."""
        if COLLECTORS not in sys.path:
            sys.path.insert(0, COLLECTORS)
        from common import db

        conn = db.connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT at_code FROM item WHERE is_forecast ORDER BY at_code")
                codes = [c for (c,) in cur.fetchall()]
        finally:
            conn.close()
        if not codes:
            raise ValueError("item.is_forecast가 true인 품목이 없다")
        print(f"예측 품목 {codes}")
        return codes

    def ml(module_args):
        """ml/ 에서 예측 가상환경으로 python -m farmit_ml.<...>를 실행하는 명령."""
        return f"cd {ML} && {ML_PYTHON} -m farmit_ml.{module_args}"

    items = forecast_items()
    # 품목마다 태스크 하나 (동적 매핑). 한 품목이 실패해도 다른 품목은 저장되고, 실패한 품목만 다시 돌릴 수 있다
    # 기준 주는 템플릿이라 환경 변수(BASE_WEEK)로 넘긴다. append_env: DB 접속 환경 변수를 지우지 않게
    forecast = BashOperator.partial(task_id="forecast", env={"BASE_WEEK": base_week}, append_env=True).expand(
        bash_command=items.map(lambda c: ml(f"forecast --item {c} --base-week $BASE_WEEK --to-db")))
    monitor = BashOperator.partial(task_id="monitor", trigger_rule="all_done").expand(
        bash_command=items.map(lambda c: ml(f"monitor --item {c}")))

    check >> features >> items >> forecast >> monitor
    # past_case도 Spark라 features 뒤에 차례로 돈다 (Spark JVM 둘을 한 컨테이너에 같이 띄우지 않게, docs/infra-memory.md)
    [features, check_weather] >> past_case
