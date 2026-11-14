"""NCPMS 예찰 수집기 테스트 (K16).

    docker compose -f infra/docker-compose.yml --profile collect run --rm collectors python -m unittest -v

API는 부르지 않는다 (http.get을 가짜로 바꾼다).
"""
import json
import os
import unittest
from datetime import date
from decimal import Decimal
from unittest import mock

from pests import ncpms
from tests.test_weather import DbTestCase


def rnd(key, ymd, round_=1, crop="FT010601"):
    return {"insectKey": key, "kncrCode": crop, "examinSpchcknNm": "기본조사", "examinYear": ymd[:4],
            "examinTmrd": round_, "inputStdrDatetm": ymd}


def service(**body):
    return json.dumps({"service": body})


def struct(sigungu, code, pest="SS0104", value=0.5):
    return {"dbyhsNm": "탄저병(피해과율)", "inqireCnClCode": pest, "inqireValue": value,
            "sigunguNm": sigungu, "sigunguCode": code}


class NcpmsUnitTest(unittest.TestCase):
    def test_wanted_is_missing_or_recent(self):
        rounds = [rnd("A", "20261101"), rnd("B", "20250516"), rnd("C", "20250601")]
        wanted = ncpms.to_wanted(rounds, have={"A", "B"}, today=date(2026, 11, 14))
        self.assertEqual([r["insectKey"] for r in wanted], ["A", "C"])  # A는 있어도 최근이라 다시, C는 없어서

    def test_to_rows(self):
        not_surveyed = {k: v for k, v in struct("양평군", 4183).items() if k != "inqireValue"}
        rows = ncpms.to_rows(rnd("K1", "20261001", 10), "경상북도", [struct("포항시", 4711), not_surveyed])
        self.assertEqual(rows, [{"ncpms_crop_code": "FT010601", "insect_key": "K1", "survey_type": "기본조사",
                                 "survey_year": 2026, "survey_round": 10, "survey_date": date(2026, 10, 1),
                                 "sido": "경상북도", "sigungu": "포항시", "sigungu_code": "4711",
                                 "pest_code": "SS0104", "pest_name": "탄저병(피해과율)", "value": 0.5}])


class NcpmsDbTest(DbTestCase):
    """완료 기준(REQ-COL-005): 회차를 두 번 받아도 행이 늘지 않고, 호출 수가 collect_log에 남는다."""

    TABLES = ["collect_log", "pest_survey"]

    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {"NCPMS_API_KEY": "TESTKEY"})
        env.start()
        self.addCleanup(env.stop)

    def respond(self, params):
        svc = params["serviceCode"]
        if svc == "SVC51":  # 회차 51개 → 50건씩 두 페이지
            all_ = [rnd(f"K{i}", "20200516", i) for i in range(51)]
            start = params["startPoint"] - 1
            return service(totalCount=51, list=all_[start:start + params["displayCount"]])
        if params["insectKey"] == "K1":
            return service(errorCode="ERR_901", errorMsg="시스템 오류\n문의")
        if svc == "SVC52":
            return service(structList=[{"sidoCode": 47, "sidoNm": "경상북도"}, {"sidoCode": 47, "sidoNm": "경상북도"},
                                       {"sidoCode": 43, "sidoNm": "충청북도"}])
        return service(structList={47: [struct("포항시", "4711"), struct("포항시", "4711", "SS0101", 1.02)],
                                   43: [struct("충주시", "4313")]}[params["sidoCode"]])

    def test_run_twice_no_duplicates_and_partial(self):
        with self.fake_get(self.respond):
            first = ncpms.collect("FT010601", conn=self.conn)
            second = ncpms.collect("FT010601", conn=self.conn)

        # 51회차 중 K1만 실패 → 50회차 × 3행
        self.assertEqual(self.sql("SELECT COUNT(*), COUNT(DISTINCT insect_key) FROM pest_survey"), ((150, 50),))
        self.assertEqual(len(first.wanted), 51)
        self.assertEqual(len(second.wanted), 1)  # 두 번째는 실패했던 K1만 다시 받는다 (나머지는 오래된 회차)
        # 첫 실행 호출: 목록 2 + K1(SVC52 1) + 50회차 × (SVC52 1 + 시도 2) = 153
        log = self.sql("SELECT status, row_count, api_calls, error_msg FROM collect_log ORDER BY id")
        self.assertEqual([r[:3] for r in log], [("partial", 150, 153), ("partial", 0, 3)])
        self.assertIn("K1: ERR_901 시스템 오류", log[0][3])
        self.assertEqual(self.sql("SELECT sido, sigungu, value FROM pest_survey "
                                  "WHERE insect_key = 'K2' AND pest_code = 'SS0101'"),
                         (("경상북도", "포항시", Decimal("1.020")),))


if __name__ == "__main__":
    unittest.main()
