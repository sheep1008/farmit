"""collectors/common 테스트 (K03).

    docker compose -f infra/docker-compose.yml run --rm collectors python -m unittest -v

DB 테스트는 test_<MYSQL_DATABASE> DB(Django 테스트와 같은 이름, 권한은 infra/mysql/init)에
collect_log를 복사해 만들고 끝나면 지운다. 운영 DB의 collect_log에는 쓰지 않는다.
DB 접속 정보(MYSQL_USER)가 없으면 DB 테스트는 건너뛴다.
"""
import os
import unittest
import urllib.error
from datetime import date
from unittest import mock

from common import db, http
from common.collect_log import LimitReached, collect_run, utcnow


class MaskTest(unittest.TestCase):
    def test_key_params_are_hidden(self):
        text = "https://x/api?serviceKey=abc%2Bdef&pageNo=1 그리고 apiKey=zzz"
        self.assertEqual(http.mask(text), "https://x/api?serviceKey=***&pageNo=1 그리고 apiKey=***")


def http_error(code):
    return urllib.error.HTTPError("https://x/api?serviceKey=SECRET", code, "err", {}, None)


class RetryTest(unittest.TestCase):
    def setUp(self):
        self.sleeps = []
        patcher = mock.patch("common.http.time.sleep", self.sleeps.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_backoff_doubles_then_succeeds(self):
        ok = mock.MagicMock()
        ok.__enter__.return_value.read.return_value = b'{"ok": 1}'
        calls = []
        with mock.patch("common.http.urllib.request.urlopen", side_effect=[http_error(503), http_error(503), ok]):
            body = http.get("https://x/api", {"pageNo": 1}, key=("serviceKey", "SECRET"),
                            on_call=lambda: calls.append(1))
        self.assertEqual(body, '{"ok": 1}')
        self.assertEqual(self.sleeps, [1.0, 2.0])  # 1초, 2초 (지수 백오프)
        self.assertEqual(len(calls), 3)            # 재시도도 호출 1건으로 센다

    def test_client_error_fails_at_once_without_key(self):
        with mock.patch("common.http.urllib.request.urlopen", side_effect=http_error(401)):
            with self.assertRaises(http.HttpError) as cm:
                http.get("https://x/api", {}, key=("serviceKey", "SECRET"))
        self.assertEqual(self.sleeps, [])
        self.assertNotIn("SECRET", str(cm.exception))
        self.assertIsNone(cm.exception.__cause__)

    def test_key_is_not_reencoded(self):
        with mock.patch("common.http.urllib.request.urlopen", side_effect=http_error(400)) as urlopen:
            with self.assertRaises(http.HttpError):
                http.get("https://x/api", {"a": "b c"}, key=("serviceKey", "ab%2Bcd"))
        self.assertEqual(urlopen.call_args[0][0], "https://x/api?serviceKey=ab%2Bcd&a=b+c")


@unittest.skipUnless(os.environ.get("MYSQL_USER"), "DB 접속 정보가 없다")
class CollectRunTest(unittest.TestCase):
    """완료 기준: 가짜 수집 함수를 두 번 돌려도 데이터는 중복되지 않고 collect_log에 2건이 남는다."""

    @classmethod
    def setUpClass(cls):
        main = os.environ["MYSQL_DATABASE"]
        cls.test_db = f"test_{main}"
        cls.conn = db.connect()
        with cls.conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS `{cls.test_db}`")
            cur.execute(f"CREATE DATABASE `{cls.test_db}`")
            cur.execute(f"USE `{cls.test_db}`")
            cur.execute(f"CREATE TABLE collect_log LIKE `{main}`.collect_log")  # Django가 만든 스키마 그대로
            cur.execute("CREATE TABLE fake_price (trade_date date NOT NULL, item varchar(10) NOT NULL, "
                        "price int NOT NULL, UNIQUE KEY uk_fake (trade_date, item))")

    @classmethod
    def tearDownClass(cls):
        with cls.conn.cursor() as cur:
            cur.execute(f"DROP DATABASE `{cls.test_db}`")
        cls.conn.close()

    def setUp(self):
        self.sql("DELETE FROM collect_log")
        self.sql("DELETE FROM fake_price")

    def sql(self, q, args=()):
        with self.conn.cursor() as cur:
            cur.execute(q, args)
            return cur.fetchall()

    def test_run_twice_no_duplicates_two_logs(self):
        prices = iter([1000, 1200])  # 두 번째 실행에서 가격이 바뀌었다고 가정

        @collect_run("test_fake")
        def fake(run):
            p = next(prices)
            run.api_calls += 1
            run.rows += db.upsert(run.conn, "fake_price", [
                {"trade_date": run.target_date, "item": "apple", "price": p},
                {"trade_date": run.target_date, "item": "pear", "price": 900},
            ], update_cols=["price"])

        fake(date(2026, 11, 13), conn=self.conn)
        fake(date(2026, 11, 13), conn=self.conn)

        self.assertEqual(self.sql("SELECT item, price FROM fake_price ORDER BY item"),
                         (("apple", 1200), ("pear", 900)))  # 2행 그대로, 값만 갱신
        logs = self.sql("SELECT source, target_date, status, row_count, api_calls, error_msg, "
                        "finished_at >= started_at FROM collect_log ORDER BY id")
        self.assertEqual(logs, (("test_fake", date(2026, 11, 13), "success", 2, 1, None, 1),) * 2)

    def test_failure_is_logged_with_key_masked(self):
        @collect_run("test_fake")
        def broken(run):
            run.rows += db.upsert(run.conn, "fake_price",
                                  [{"trade_date": run.target_date, "item": "apple", "price": 1}], ["price"])
            raise RuntimeError("응답 이상 https://x/api?serviceKey=SECRET")

        with self.assertRaises(RuntimeError):
            broken(date(2026, 11, 13), conn=self.conn)
        (status, rows, msg), = self.sql("SELECT status, row_count, error_msg FROM collect_log")
        self.assertEqual((status, rows), ("fail", 1))
        self.assertIn("serviceKey=***", msg)
        self.assertNotIn("SECRET", msg)

    def test_partial(self):
        @collect_run("test_fake")
        def some_failed(run):
            run.errors.append("시장 110001: 시간 초과")

        some_failed(date(2026, 11, 13), conn=self.conn)
        self.assertEqual(self.sql("SELECT status, error_msg FROM collect_log"), (("partial", "시장 110001: 시간 초과"),))

    def test_stops_before_daily_limit(self):
        # 오늘 이미 2건을 썼다
        self.sql("INSERT INTO collect_log (source, target_date, started_at, finished_at, status, row_count, api_calls) "
                 "VALUES ('test_fake', '2026-11-13', %s, %s, 'success', 0, 2)", (utcnow(), utcnow()))

        @collect_run("test_fake", daily_limit=3)
        def calls_three(run):
            for _ in range(3):
                run.count_call()

        with self.assertRaises(LimitReached):
            calls_three(date(2026, 11, 13), conn=self.conn)
        self.assertEqual(self.sql("SELECT status, api_calls FROM collect_log ORDER BY id DESC LIMIT 1"), (("fail", 1),))


if __name__ == "__main__":
    unittest.main()
