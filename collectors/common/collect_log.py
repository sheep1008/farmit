"""수집 한 번의 결과를 collect_log에 남기는 데코레이터 (REQ-COL-008, REQ-NFR-009).

    @collect_run("asos", daily_limit=10000)
    def collect(run):
        text = run.get(URL, {...}, key=("serviceKey", KEY))   # 호출 수가 run.api_calls에 쌓인다
        run.rows += upsert(run.conn, "weather_daily", rows, ["avg_temp", ...])

    collect(date(2026, 11, 13))   # 성공·실패와 상관없이 collect_log에 한 줄 남는다

시각은 모두 UTC로 저장한다 (MySQL 서버 시간대도 +00:00).
"""
import functools
from datetime import datetime, timedelta, timezone

from . import db, http

KST = timezone(timedelta(hours=9))


class LimitReached(Exception):
    """오늘 API 호출이 한도에 닿아 멈췄다."""


def utcnow():
    # PyMySQL은 시간대 정보를 버리므로 UTC 기준의 naive datetime으로 넘긴다
    return datetime.now(timezone.utc).replace(tzinfo=None)


def calls_today(conn, source):
    """오늘 이 출처로 쓴 API 호출 수 (collect_log.api_calls 합).

    날짜 경계만 한국 자정이다. data.go.kr 일일 한도가 한국 날짜로 초기화되기 때문이다 (collectors/auction과 같음).
    """
    start = datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(SUM(api_calls), 0) FROM collect_log WHERE source = %s AND started_at >= %s",
                    (source, start.replace(tzinfo=None)))
        return int(cur.fetchone()[0])


class Run:
    """수집 한 번의 상태. 수집 함수가 rows를 더하고, 일부만 실패하면 errors에 사유를 넣는다."""

    def __init__(self, conn, source, target_date, daily_limit):
        self.conn = conn
        self.source = source
        self.target_date = target_date
        self.rows = 0
        self.api_calls = 0
        self.errors = []
        self.daily_limit = daily_limit
        self.calls_before = calls_today(conn, source) if daily_limit else 0

    def count_call(self):
        """요청을 보내기 직전에 불린다. 한도에 닿았으면 보내지 않고 멈춘다."""
        if self.daily_limit and self.calls_before + self.api_calls >= self.daily_limit:
            raise LimitReached(f"하루 호출 한도 {self.daily_limit}건에 닿아 멈춤 "
                               f"(오늘 앞서 {self.calls_before}건 + 이번 {self.api_calls}건)")
        self.api_calls += 1

    def get(self, url, params, **kw):
        return http.get(url, params, on_call=self.count_call, **kw)


def collect_run(source, daily_limit=None):
    """수집 함수 fn(run)을 감싸 collect(target_date, conn=None)으로 만든다.

    상태: 예외 없이 끝나면 success, run.errors가 있으면 partial, 예외가 나면 fail(예외는 다시 던진다).
    conn을 넘기지 않으면 환경 변수로 새로 연결하고 끝나면 닫는다 (테스트는 테스트 DB 연결을 넘긴다).
    """
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(target_date, conn=None):
            own = conn is None
            conn = conn or db.connect()
            started = utcnow()
            run = Run(conn, source, target_date, daily_limit)
            status, error = "success", None
            try:
                fn(run)
                if run.errors:
                    status, error = "partial", "\n".join(run.errors)
                return run
            except Exception as e:
                status, error = "fail", "\n".join(run.errors + [f"{type(e).__name__}: {e}"])
                raise
            finally:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO collect_log (source, target_date, started_at, finished_at, status, "
                        "row_count, api_calls, error_msg) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                        (source, target_date, started, utcnow(), status, run.rows, run.api_calls,
                         http.mask(error) if error else None))
                if own:
                    conn.close()
        return wrapper
    return deco
