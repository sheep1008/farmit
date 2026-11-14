"""aT 정산 수집기 테스트 (Y15, REQ-COL-001).

    docker compose -f infra/docker-compose.yml --profile collect run --rm collectors python -m unittest -v

API는 부르지 않는다 (http.get을 가짜로 바꾼다). DB 테스트는 test_weather의 DbTestCase를 쓴다.
"""
import json
import unittest
from datetime import date
from decimal import Decimal as D
from unittest import mock

from settle import at_settle
from tests.test_weather import DbTestCase


def row(day="2026-10-30", item=("03", "05"), grade="특", unit_nm="kg", unit_qty="4", qty="296", tot="1489500",
        low="15000", high="26000"):
    return {"trd_clcln_ymd": day, "whsl_mrkt_cd": "250001", "gds_lclsf_cd": item[0], "gds_mclsf_cd": item[1],
            "grd_nm": grade, "unit_nm": unit_nm, "unit_qty": unit_qty, "unit_tot_qty": qty, "totprc": tot,
            "lwprc": low, "hgprc": high}


def body(rows, total=None):
    return json.dumps({"response": {"header": {"resultCode": "00"},
                                    "body": {"items": {"item": rows}, "totalCount": len(rows) if total is None else total}}})


class AggUnitTest(unittest.TestCase):
    def agg(self, rows):
        a = at_settle.Agg("250001", {"0305": 5})
        for r in rows:
            a.add(r)
        return a

    def test_weighted_avg_min_max_and_all_grade(self):
        a = self.agg([row(qty="100", tot="1000000", low="8000", high="48000"),      # 10,000원/kg, kg당 2,000~12,000
                      row(qty="300", tot="1500000", low="12000", high="20000")])    # 5,000원/kg, kg당 3,000~5,000
        rows = {r["grade"]: r for r in a.rows()}
        self.assertEqual(set(rows), {"특", "ALL"})
        self.assertEqual(rows["ALL"]["avg_price"], D("6250.0"))   # (1,000,000+1,500,000) ÷ 400kg
        self.assertEqual((rows["ALL"]["min_price"], rows["ALL"]["max_price"]), (D("2000.0"), D("12000.0")))
        self.assertEqual(rows["ALL"]["volume_kg"], D("400.0"))

    def test_grades_split_and_all_sums_them(self):
        a = self.agg([row(grade="특", qty="100", tot="1000000"), row(grade="상", qty="100", tot="500000")])
        rows = {r["grade"]: r for r in a.rows()}
        self.assertEqual((rows["특"]["avg_price"], rows["상"]["avg_price"], rows["ALL"]["avg_price"]),
                         (D("10000.0"), D("5000.0"), D("7500.0")))

    def test_skips_and_counts(self):
        a = self.agg([row(item=("99", "99")), row(unit_nm="개"), row(qty="0"), row(tot="-5"), row(qty="abc"), row()])
        self.assertEqual(dict(a.skipped), {"item_없음": 1, "kg_아님": 1, "물량·금액_0이하": 2, "값_오류": 1})
        self.assertEqual(len(a.rows()), 2)   # 정상 1행 → 등급 + ALL

    def test_month_chunks(self):
        self.assertEqual(list(at_settle.month_chunks(date(2026, 11, 20), date(2027, 1, 3))), [
            (date(2026, 11, 20), date(2026, 11, 30)), (date(2026, 12, 1), date(2026, 12, 31)),
            (date(2027, 1, 1), date(2027, 1, 3))])

    def test_parse_single_item_object_and_error(self):
        rows, total = at_settle.parse(body(row(), total=1))   # 1건이면 리스트가 아니라 객체로 온다
        self.assertEqual((len(rows), total), (1, 1))
        with self.assertRaises(at_settle.datagokr.ApiError):
            at_settle.parse("<xml>serviceKey=ABC</xml>")


class MainTest(unittest.TestCase):
    def test_default_is_yesterday_only(self):
        with mock.patch.object(at_settle, "yesterday", return_value=date(2026, 11, 13)), \
                mock.patch.object(at_settle, "collect") as c:
            c.return_value.rows = c.return_value.api_calls = 0
            c.return_value.skipped = {}
            at_settle.main([])
        c.assert_called_once_with(date(2026, 11, 13), date(2026, 11, 13))


class SettleDbTest(DbTestCase):
    """완료 기준: 같은 기간을 두 번 돌려도 settle_price 행이 늘지 않고, 시장 하나가 실패해도 나머지는 저장된다."""

    TABLES = ["collect_log", "market", "item", "settle_price"]

    def setUp(self):
        super().setUp()
        self.sql("INSERT INTO market (market_id, name, sido, lat, lng, is_collect, is_reference) VALUES "
                 "('250001', '대전오정', '대전', 36.4, 127.4, 1, 0), ('110001', '서울가락', '서울', 37.5, 127.1, 0, 1), "
                 "('999999', '제외', '서울', 37.5, 127.1, 0, 0)")
        self.sql("INSERT INTO item (item_id, at_code, name, category, is_storable, is_forecast) VALUES "
                 "(5, '0305', '강낭콩', '두류', 0, 0)")

    def fake(self, responses):
        """시장 코드 → 응답 본문. 요청에 쓰인 시장을 self.asked에 모은다."""
        self.asked = []

        def respond(params):
            m = params["cond[whsl_mrkt_cd::EQ]"]
            self.asked.append(m)
            return responses[m]
        return self.fake_get(respond)

    def test_run_twice_no_duplicates(self):
        with self.fake({"250001": body([row(), row(grade="상")]), "110001": body([])}):
            at_settle.collect(date(2026, 10, 30), date(2026, 10, 30), conn=self.conn)
            run = at_settle.collect(date(2026, 10, 30), date(2026, 10, 30), conn=self.conn)

        self.assertEqual(sorted(self.asked), ["110001", "110001", "250001", "250001"])   # 제외 시장은 부르지 않는다
        self.assertEqual(self.sql("SELECT CAST(trade_date AS CHAR), market_id, item_id, grade, avg_price, volume_kg "
                                  "FROM settle_price ORDER BY grade"),
                         (("2026-10-30", "250001", 5, "ALL", D("5032.1"), D("592.0")),
                          ("2026-10-30", "250001", 5, "상", D("5032.1"), D("296.0")),
                          ("2026-10-30", "250001", 5, "특", D("5032.1"), D("296.0"))))
        self.assertEqual(run.rows, 3)

    def test_rerun_updates_corrected_values(self):
        with self.fake({"250001": body([row(tot="1000000", qty="100")]), "110001": body([])}):
            at_settle.collect(date(2026, 10, 30), date(2026, 10, 30), conn=self.conn)
        with self.fake({"250001": body([row(tot="2000000", qty="100")]), "110001": body([])}):   # 정정된 값
            at_settle.collect(date(2026, 10, 30), date(2026, 10, 30), conn=self.conn)
        self.assertEqual(self.sql("SELECT COUNT(*), MAX(avg_price) FROM settle_price"), ((2, D("20000.0")),))

    def test_request_uses_dashed_dates_and_market_condition(self):
        sent = []
        with self.fake_get(lambda p: sent.append(p) or body([])):
            at_settle.collect(date(2026, 10, 30), date(2026, 10, 30), conn=self.conn)
        self.assertEqual({(p["cond[trd_clcln_ymd::GTE]"], p["cond[trd_clcln_ymd::LTE]"]) for p in sent},
                         {("2026-10-30", "2026-10-30")})   # YYYYMMDD나 EQ는 오류 없이 0건이 온다
        self.assertTrue(all(p["cond[whsl_mrkt_cd::EQ]"] for p in sent))   # 시장 조건이 없어도 0건

    def test_kg_price_unit(self):
        with self.fake({"250001": body([row()]), "110001": body([])}):
            at_settle.collect(date(2026, 10, 30), date(2026, 10, 30), conn=self.conn)
        # 1,489,500원 ÷ 296kg = 5,032.1원/kg (포장 1개 가격이 아니라 kg당), 최저 15,000÷4kg
        self.assertEqual(self.sql("SELECT avg_price, min_price, max_price FROM settle_price WHERE grade = 'ALL'"),
                         ((D("5032.1"), D("3750.0"), D("6500.0")),))

    def test_pages_are_merged(self):
        pages = [body([row(qty="100", tot="1000000")], total=2), body([row(qty="100", tot="500000")], total=2)]
        with self.fake_get(lambda p: pages[p["pageNo"] - 1] if p["cond[whsl_mrkt_cd::EQ]"] == "250001" else body([])):
            run = at_settle.collect(date(2026, 10, 30), date(2026, 10, 30), conn=self.conn)
        self.assertEqual(self.sql("SELECT avg_price FROM settle_price WHERE grade = 'ALL'"), ((D("7500.0"),),))
        self.assertEqual(run.api_calls, 3)   # 오정 2페이지 + 가락 1

    def test_one_market_fails_partial(self):
        with self.fake({"250001": body([row()]), "110001": "<xml>serviceKey=SECRET</xml>"}):
            run = at_settle.collect(date(2026, 10, 30), date(2026, 10, 30), conn=self.conn)
        self.assertEqual(run.rows, 2)
        (status, msg), = self.sql("SELECT status, error_msg FROM collect_log")
        self.assertEqual(status, "partial")
        self.assertIn("시장 110001", msg)
        self.assertNotIn("SECRET", msg)

    def test_error_result_code_fails_not_zero_rows(self):
        err = json.dumps({"response": {"header": {"resultCode": "30", "resultMsg": "KEY ERROR"}, "body": {"totalCount": 0}}})
        with self.fake({"250001": err, "110001": body([])}):
            at_settle.collect(date(2026, 10, 30), date(2026, 10, 30), conn=self.conn)
        (status, msg), = self.sql("SELECT status, error_msg FROM collect_log")
        self.assertEqual((status, "resultCode 30" in msg), ("partial", True))

    def test_limit_stops_with_resume_point_and_months_finish_first(self):
        """한도에 걸리면 멈춘 달을 알려 주고, 그 달 앞은 모든 시장이 끝나 있다 (--start로 이어 받아도 빈 구간 없음)."""
        from common.collect_log import LimitReached
        self.sql("INSERT INTO collect_log (source, target_date, started_at, finished_at, status, row_count, api_calls) "
                 "VALUES ('at_settle', '2026-10-01', UTC_TIMESTAMP(), UTC_TIMESTAMP(), 'success', 0, %s)",
                 (at_settle.DAILY_LIMIT - 3,))   # 오늘 3건만 더 부를 수 있다 → 9월 2시장 + 10월 첫 시장에서 멈춘다
        with self.fake_get(lambda p: body([row(day=p["cond[trd_clcln_ymd::GTE]"])])):
            with self.assertRaisesRegex(LimitReached, "--start 2026-10-01"):
                at_settle.collect(date(2026, 9, 1), date(2026, 10, 31), conn=self.conn)
        self.assertEqual(self.sql("SELECT DISTINCT CAST(trade_date AS CHAR), market_id FROM settle_price "
                                  "ORDER BY 1, 2"),
                         (("2026-09-01", "110001"), ("2026-09-01", "250001"), ("2026-10-01", "110001")))

    def test_bad_rows_are_skipped_not_fatal(self):
        bad = [row(day="2026-09-01"), {**row(), "trd_clcln_ymd": None}, {k: v for k, v in row().items() if k != "trd_clcln_ymd"}]
        with self.fake({"250001": body(bad), "110001": body([])}):
            at_settle.collect(date(2026, 10, 30), date(2026, 10, 30), conn=self.conn)
        self.assertEqual(self.sql("SELECT status FROM collect_log"), (("success",),))
        self.assertEqual(self.sql("SELECT COUNT(*) FROM settle_price"), ((0,),))   # 기간 밖·누락 행은 저장하지 않는다

    def test_no_market_fails(self):
        self.sql("DELETE FROM market")
        with self.assertRaisesRegex(RuntimeError, "비어 있다"):
            at_settle.collect(date(2026, 10, 30), date(2026, 10, 30), conn=self.conn)
        self.assertEqual(self.sql("SELECT status FROM collect_log"), (("fail",),))


if __name__ == "__main__":
    unittest.main()
