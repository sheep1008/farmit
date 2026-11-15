"""주간 피처 DAG (K12, REQ-PRD-001). batch/spark/features.py를 실행해 ml/data/weekly_<품목코드>.csv를 다시 만든다.

- build_features_weekly  매주 일 23:00 UTC(한국 월 08:00)
  collect_daily(일 22:00 UTC = 한국 월 07:00)가 지난주 일요일분 정산·ASOS를 받은 뒤, 월요일 예측(K19) 전에 돈다.
  수집을 기다리는 장치는 없다: 수집이 1시간 넘게 걸리면 일요일분이 빠진 채 만들어진다 (일요일은 대부분 휴장이라 영향이 작다).
- Spark는 이 컨테이너 안에서 local 모드로 돈다 (batch/airflow/Dockerfile). 매번 전체 기간을 다시 계산한다 (수 분 이내).
"""
from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

SPARK = "/opt/farmit/spark"   # compose가 batch/spark를 읽기 전용으로 붙여 둔 곳

with DAG(
    "build_features_weekly",
    schedule="0 23 * * 0",
    start_date=pendulum.datetime(2026, 11, 1, tz="UTC"),
    catchup=False,           # 매번 전체를 다시 만들므로 놓친 주를 따로 돌릴 필요가 없다
    max_active_runs=1,       # 같은 CSV를 쓰므로 한 번에 하나만
    default_args={"retries": 2, "retry_delay": timedelta(minutes=10), "execution_timeout": timedelta(minutes=30)},
    tags=["batch"],
):
    BashOperator(task_id="features", bash_command=f"cd {SPARK} && python -m features")
