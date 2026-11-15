"""관세청 수입량 수집기 테스트 (K16).

    docker compose -f infra/docker-compose.yml --profile collect run --rm collectors python -m unittest -v

API는 부르지 않는다 (http.get을 가짜로 바꾼다).
"""
import unittest
from datetime import date

from common import datagokr
from imports import customs
from tests.test_weather import DbTestCase


def row(ym, kg, usd, country="CL"):
    return (f"<item><hsCd>0806100000</hsCd><impDlr>{usd}</impDlr><impWgt>{kg}</impWgt>"
            f"<statCd>{country}</statCd><year>{ym}</year></item>")


def xml(*rows, code="00"):
    """관세청 응답 모양. 첫 행은 조회 기간 전체 합계(총계)다."""
    total = "<item><hsCd>-</hsCd><impDlr>999</impDlr><impWgt>999</impWgt><statCd>-</statCd><year>총계</year></item>"
    return (f"<response><header><resultCode>{code}</resultCode><resultMsg>msg</resultMsg></header>"
            f"<body><items>{total if rows else ''}{''.join(rows)}</items></body></response>")


class CustomsUnitTest(unittest.TestCase):
    def test_sum_countries_skip_total(self):
        rows = customs.parse(xml(row("2025.01", 100, 10), row("2025.01", 50, 5, "US"), row("2025.03", 7, 1)))
        self.assertEqual(customs.monthly(rows), {1: (150, 15), 3: (7, 1)})

    def test_missing_months_are_zero_up_to_last_month(self):
        rows = customs.to_rows(10, "080610", 2025, {1: (150, 15), 3: (7, 1)}, last_month=4)
        self.assertEqual([(r["ym"], r["import_kg"]) for r in rows],
                         [(date(2025, 1, 1), 150), (date(2025, 2, 1), 0), (date(2025, 3, 1), 7), (date(2025, 4, 1), 0)])

    def test_error_code_raises(self):
        with self.assertRaisesRegex(datagokr.ApiError, "resultCode 99"):
            customs.parse(xml(code="99"))


class CustomsDbTest(DbTestCase):
    """완료 기준(REQ-COL-005): 같은 해를 두 번 돌려도 행이 늘지 않고, hs_code가 있는 품목만 받는다."""

    TABLES = ["collect_log", "item", "import_monthly"]

    def setUp(self):
        super().setUp()
        self.sql("INSERT INTO item (item_id, at_code, name, category, is_storable, is_forecast, hs_code) VALUES "
                 "(10, '0601', '사과', '과일', 1, 1, '080810'), (12, '0603', '포도', '과일', 0, 0, '080610'), "
                 "(11, '0602', '배', '과일', 1, 0, NULL)")

    def test_run_twice_no_duplicates(self):
        responses = {"080810": xml(),  # 사과: 수입 없음 → 행이 오지 않는다
                     "080610": xml(row("2025.01", 100, 10), row("2025.02", 30, 3))}
        with self.fake_get(lambda params: responses[params["hsSgn"]]):
            customs.collect(2025, conn=self.conn)
            run = customs.collect(2025, conn=self.conn)

        self.assertEqual(run.last_month, 2)  # 포도가 2월까지 왔으므로 사과도 2월까지 0으로 채운다
        self.assertEqual(self.sql("SELECT item_id, hs_code, CAST(ym AS CHAR), import_kg, import_usd FROM import_monthly "
                                  "ORDER BY item_id, ym"),
                         ((10, "080810", "2025-01-01", 0, 0), (10, "080810", "2025-02-01", 0, 0),
                          (12, "080610", "2025-01-01", 100, 10), (12, "080610", "2025-02-01", 30, 3)))
        self.assertEqual(self.sql("SELECT source, target_date, status, row_count, api_calls FROM collect_log"),
                         (("customs", date(2025, 1, 1), "success", 4, 2),) * 2)

    def test_api_error_fails(self):
        with self.fake_get(lambda params: xml(code="99")):
            with self.assertRaises(datagokr.ApiError):
                customs.collect(2025, conn=self.conn)
        self.assertEqual(self.sql("SELECT status FROM collect_log"), (("fail",),))


if __name__ == "__main__":
    unittest.main()
