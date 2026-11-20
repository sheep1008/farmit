"""수집 DAG (K11, REQ-COL-001·003·005). collectors/ 수집기를 고치지 않고 그대로 실행한다.

- collect_daily            매일 22:00 UTC(한국 07:00): 어제(한국 날짜) 정산(전국 시장 × 전 품목, K32)·ASOS
                           → 남은 한도로 과거 적재 이어 받기
- collect_customs_monthly  매월 14일 22:00 UTC(한국 15일 07:00): 관세청 수입량 (전월분이 보통 중순에 공표된다)
- collect_ncpms_weekly     매주 화 22:00 UTC(한국 수 07:00): NCPMS 예찰 (예찰은 보통 매월 1일·16일 기준)
  위 두 DAG는 수집 뒤에 alert_rules(수입량 급증·예찰 증가 판정 + 회원 알림, K17)를 돌린다

재시도·기록:
- 수집기가 예외로 끝나면 태스크가 실패하고 retries만큼 다시 돈다. 시도마다 collect_run이 collect_log에 fail 한 줄을 남긴다.
- 시장·관측소 일부만 실패하면 수집기는 partial로 정상 종료한다 → 재시도하지 않는다 (나머지는 이미 저장됐다).
- 모든 수집기가 UPSERT라서 재시도·재실행해도 행이 늘지 않는다.
"""
import sys
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG, Variable, task

COLLECTORS = "/opt/farmit/collectors"   # compose가 collectors/를 읽기 전용으로 붙여 둔 곳
SPARK = "/opt/farmit/spark"             # batch/spark (읽기 전용)
KST = ZoneInfo("Asia/Seoul")
START = pendulum.datetime(2026, 11, 1, tz="UTC")
DEFAULT_ARGS = {"retries": 3, "retry_delay": timedelta(minutes=5), "execution_timeout": timedelta(hours=1)}


def kst_yesterday(run_after):
    """실행 예정 시각(run_after) 기준 한국 날짜의 어제. 정산·ASOS 모두 하루 늦게 제공되고, 수집기도 한국 날짜를 쓴다.

    logical_date가 아니라 run_after를 쓰는 이유: Airflow 3에서 손으로 실행(trigger)한 run은 logical_date가 비어 있다.
    """
    return (run_after.astimezone(KST).date() - timedelta(days=1)).isoformat()


def module(task_id, args, **kw):
    """python -m <args>를 collectors/ 에서 실행하는 태스크. 손으로 돌릴 때와 같은 명령이다."""
    return BashOperator(task_id=task_id, bash_command=f"cd {COLLECTORS} && python -m {args}", **kw)


def alert_rules():
    """수입량 급증·예찰 증가 판정 + 회원 알림 (K17, batch/spark/alert_rules.py). 두 판정을 같이 돌려도 몇십 초다.
    수집이 일부만 실패해도(partial) 받은 자료로 판정하도록 수집 태스크 뒤에 붙인다."""
    return BashOperator(task_id="alert_rules", bash_command=f"cd {SPARK} && python -m alert_rules")


def backfill(name, chunks):  # chunks: 수집기 모듈의 기간 자르기 함수 이름 (month_chunks·year_chunks)
    """과거 적재를 한 덩어리(달·해)씩 받고, 끝난 다음 날짜를 Airflow Variable에 적어 둔다.

    한도에 닿으면(LimitReached) 그날은 거기서 멈추고 성공으로 끝낸다. 다음 날 같은 덩어리부터 다시 받는다
    (덩어리 안에서 이미 받은 부분은 UPSERT라 중복이 생기지 않는다). 다 받으면 Variable이 어제 다음 날을 가리켜 아무것도 하지 않는다.
    """
    if COLLECTORS not in sys.path:
        sys.path.insert(0, COLLECTORS)
    import importlib
    from common.collect_log import LimitReached

    mod = importlib.import_module(name)
    key = f"backfill_next_{mod.SOURCE}"
    start = date.fromisoformat(Variable.get(key, default=mod.BACKFILL_FROM.isoformat()))
    for s, e in getattr(mod, chunks)(start, mod.yesterday()):
        try:
            run = mod.collect(s, e)
        except LimitReached as ex:
            print(f"{mod.SOURCE} 과거 적재 {s}에서 멈춤 (내일 이어서): {ex}")
            return
        Variable.set(key, (e + timedelta(days=1)).isoformat())
        print(f"{mod.SOURCE} {s}~{e}: {run.rows}행, 호출 {run.api_calls}건")


with DAG(
    "collect_daily",
    schedule="0 22 * * *",
    start_date=START,
    catchup=False,           # 놓친 날은 과거 적재 태스크가 채운다
    max_active_runs=1,       # 과거 적재가 Variable을 같이 쓰므로 한 번에 하나만
    default_args=DEFAULT_ARGS,
    user_defined_macros={"kst_yesterday": kst_yesterday},
    tags=["collect"],
):
    day = "{{ kst_yesterday(dag_run.run_after) }}"
    # 전국 시장 × 전 품목 하루치 (K32, 약 4건). 수집 시장 5곳·예측 품목(K31)도 이 응답에 들어 있어 따로 받지 않는다.
    # 예측 품목 전국 과거분은 손으로 한 번 받았다 (--national --backfill, 사과 651건)
    settle = module("at_settle_all", f"settle.at_settle --all-items --start {day} --end {day}")
    asos = module("asos", f"weather.asos --start {day} --end {day}")

    # 하루치를 먼저 받고 남은 한도로 과거를 받는다. 하루치가 실패해도 과거 적재는 돈다
    @task(trigger_rule="all_done", execution_timeout=timedelta(hours=6))
    def backfill_at_settle():
        backfill("settle.at_settle", "month_chunks")

    @task(trigger_rule="all_done", execution_timeout=timedelta(hours=6))
    def backfill_asos():
        backfill("weather.asos", "year_chunks")

    settle >> backfill_at_settle()   # 하루치 뒤에 남은 한도로 과거 적재 (수집 시장 5곳, 2018년부터)
    asos >> backfill_asos()


with DAG(
    "collect_customs_monthly",
    schedule="0 22 14 * *",
    start_date=START,
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["collect"],
):
    module("customs", "imports.customs") >> alert_rules()   # 기본: 작년·올해를 다시 받는다 (1월에도 작년 12월분이 들어온다)


with DAG(
    "collect_ncpms_weekly",
    schedule="0 22 * * 2",
    start_date=START,
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["collect"],
):
    module("ncpms", "pests.ncpms") >> alert_rules()   # 새 회차 + 최근 회차만 다시 받는다 (수집기 안에서 고른다)
