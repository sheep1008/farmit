"""weather 수집기 테스트 (K09).

    docker compose -f infra/docker-compose.yml --profile collect run --rm collectors python -m unittest -v

API는 부르지 않는다 (http.get을 가짜로 바꾼다). DB 테스트는 test_common과 같이 test_<MYSQL_DATABASE>에
필요한 테이블을 복사해 만들고 끝나면 지운다.
"""
import json
import os
import unittest
from datetime import date, timedelta
from decimal import Decimal as D
from unittest import mock

from common import datagokr, db
from weather import asos, check, holiday, kosis, producing_area


def body(code="00", items=None):
    """data.go.kr 모양의 응답 본문."""
    return json.dumps({"response": {"header": {"resultCode": code, "resultMsg": "msg"},
                                    "body": {"items": {"item": items} if items is not None else ""}}})


def asos_item(stn, tm, avg="13.6", rain=""):
    return {"stnId": str(stn), "tm": tm, "avgTa": avg, "maxTa": "20.3", "minTa": "8.1", "sumRn": rain, "avgRhm": "75.4"}


class ItemsTest(unittest.TestCase):
    def test_single_item_object_becomes_list(self):
        self.assertEqual(datagokr.items(body(items={"a": 1})), [{"a": 1}])

    def test_no_data_is_empty(self):
        self.assertEqual(datagokr.items(body("03")), [])

    def test_error_code_raises(self):
        with self.assertRaisesRegex(datagokr.ApiError, "resultCode 99"):
            datagokr.items(body("99"))

    def test_xml_raises(self):
        with self.assertRaisesRegex(datagokr.ApiError, "JSON이 아닌"):
            datagokr.items("<OpenAPI_ServiceResponse><returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR")


class AsosUnitTest(unittest.TestCase):
    def test_blank_is_null_not_zero(self):
        row = asos.to_row(asos_item(133, "2026-10-30", avg="", rain=""))
        self.assertEqual(row, {"station_id": 133, "obs_date": "2026-10-30", "avg_temp": None, "max_temp": "20.3",
                               "min_temp": "8.1", "rain_mm": None, "humidity": "75.4"})

    def test_year_chunks(self):
        self.assertEqual(list(asos.year_chunks(date(2025, 12, 30), date(2027, 1, 2))), [
            (date(2025, 12, 30), date(2025, 12, 31)),
            (date(2026, 1, 1), date(2026, 12, 31)),
            (date(2027, 1, 1), date(2027, 1, 2)),
        ])


class HolidayUnitTest(unittest.TestCase):
    def test_same_day_names_are_joined_and_non_holiday_dropped(self):
        rows = holiday.to_rows([
            {"locdate": 20250505, "dateName": "어린이날", "isHoliday": "Y"},
            {"locdate": 20250505, "dateName": "부처님오신날", "isHoliday": "Y"},
            {"locdate": 20250506, "dateName": "대체공휴일", "isHoliday": "Y"},
            {"locdate": 20250508, "dateName": "어버이날", "isHoliday": "N"},
        ])
        self.assertEqual(rows, [{"holiday_date": "2025-05-05", "name": "어린이날·부처님오신날"},
                                {"holiday_date": "2025-05-06", "name": "대체공휴일"}])


def kosis_row(itm, year, dt, changed="2025-10-29"):
    return {"ITM_NM": itm, "PRD_DE": str(year), "DT": dt, "LST_CHN_DE": changed}


class KosisUnitTest(unittest.TestCase):
    def test_to_rows(self):
        rows, skipped = kosis.to_rows([
            kosis_row("사과:면적", 2024, "33313.288"),
            kosis_row("사과:생산량", 2024, "460088.4145", changed="2025-11-02"),
            kosis_row("사과:10a당 생산량", 2024, "-"),
            kosis_row("기타:생산량", 2024, "100"),
            kosis_row("합계:면적", 2024, "156583.2134"),
        ], {"사과": 10})
        self.assertEqual(rows, [{"item_id": 10, "year": 2024, "area_ha": D("33313.288"),
                                 "production_kg": 460088415,      # 톤 × 1000
                                 "yield_kg_10a": None,            # '-'는 NULL
                                 "kosis_updated_on": "2025-11-02"}])  # 지표 중 가장 늦은 수정일
        self.assertEqual(skipped, {"기타", "합계"})


@unittest.skipUnless(os.environ.get("MYSQL_USER"), "DB 접속 정보가 없다")
class DbTestCase(unittest.TestCase):
    """test_<MYSQL_DATABASE>에 TABLES를 운영 스키마 그대로 복사해 두고, 테스트마다 비운다."""

    TABLES = []

    @classmethod
    def setUpClass(cls):
        main = os.environ["MYSQL_DATABASE"]
        cls.test_db = f"test_{main}"
        cls.conn = db.connect()
        with cls.conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS `{cls.test_db}`")
            cur.execute(f"CREATE DATABASE `{cls.test_db}`")
            cur.execute(f"USE `{cls.test_db}`")
            for t in cls.TABLES:  # Django가 만든 스키마 그대로 (LIKE는 FK를 복사하지 않아 관측소·품목 행이 없어도 된다)
                cur.execute(f"CREATE TABLE `{t}` LIKE `{main}`.`{t}`")

    @classmethod
    def tearDownClass(cls):
        with cls.conn.cursor() as cur:
            cur.execute(f"DROP DATABASE `{cls.test_db}`")
        cls.conn.close()

    def setUp(self):
        for t in self.TABLES:
            self.sql(f"DELETE FROM `{t}`")
        env = mock.patch.dict(os.environ, {"DATA_GO_KR_KEY": "TESTKEY", "KOSIS_API_KEY": "TESTKEY"})
        env.start()
        self.addCleanup(env.stop)

    def sql(self, q, args=()):
        with self.conn.cursor() as cur:
            cur.execute(q, args)
            return cur.fetchall()

    def fake_get(self, respond):
        """respond(params) → 응답 본문. 실제 http.get처럼 요청마다 on_call을 부른다 (호출 수 세기)."""
        def get(url, params, on_call=None, **kw):
            on_call()
            return respond(params)
        return mock.patch("common.http.get", side_effect=get)


class AsosDbTest(DbTestCase):
    """완료 기준: 같은 기간을 두 번 돌려도 weather_daily 행이 늘지 않고, 실패한 관측소만 건너뛴다."""

    TABLES = ["collect_log", "item_producing_area", "weather_daily"]

    def setUp(self):
        super().setUp()
        # 주산지 두 곳이 관측소 133을 같이 쓰고, 한 곳은 136 → 수집 대상은 133·136 두 곳
        self.sql("INSERT INTO item_producing_area (item_id, sido, sigungu, station_id, volume_share) VALUES "
                 "(1, '충북', '충주시', 133, 30), (1, '충남', '예산군', 133, 20), (1, '경북', '안동시', 136, 50)")

    def fake_get(self, responses):
        """관측소 번호 → 응답 본문."""
        return super().fake_get(lambda params: responses[params["stnIds"]])

    def test_run_twice_no_duplicates(self):
        days = ["2026-11-12", "2026-11-13"]
        with self.fake_get({133: body(items=[asos_item(133, d) for d in days]),
                            136: body(items=asos_item(136, days[1], rain="2.5"))}):  # 1건이면 객체로 온다
            asos.collect(date(2026, 11, 12), date(2026, 11, 13), conn=self.conn)
            asos.collect(date(2026, 11, 12), date(2026, 11, 13), conn=self.conn)

        self.assertEqual(self.sql("SELECT station_id, CAST(obs_date AS CHAR), avg_temp, rain_mm FROM weather_daily "
                                  "ORDER BY station_id, obs_date"),
                         ((133, "2026-11-12", D("13.6"), None), (133, "2026-11-13", D("13.6"), None),
                          (136, "2026-11-13", D("13.6"), D("2.5"))))
        self.assertEqual(self.sql("SELECT source, target_date, status, row_count, api_calls FROM collect_log"),
                         (("asos", date(2026, 11, 13), "success", 3, 2),) * 2)

    def test_one_station_fails_partial(self):
        with self.fake_get({133: body(items=[asos_item(133, "2026-11-13")]), 136: body("99")}):
            run = asos.collect(date(2026, 11, 13), date(2026, 11, 13), conn=self.conn)

        self.assertEqual(run.rows, 1)
        (status, msg), = self.sql("SELECT status, error_msg FROM collect_log")
        self.assertEqual(status, "partial")
        self.assertIn("관측소 136", msg)

    def test_no_station_fails(self):
        self.sql("DELETE FROM item_producing_area")
        with self.assertRaisesRegex(RuntimeError, "관측소가 없다"):
            asos.collect(date(2026, 11, 13), date(2026, 11, 13), conn=self.conn)
        self.assertEqual(self.sql("SELECT status FROM collect_log"), (("fail",),))


class HolidayDbTest(DbTestCase):
    TABLES = ["collect_log", "holiday"]

    def test_run_twice_no_duplicates(self):
        items = [{"locdate": 20260924, "dateName": "추석", "isHoliday": "Y"},
                 {"locdate": 20260925, "dateName": "추석", "isHoliday": "Y"}]
        with self.fake_get(lambda params: body(items=items)):
            holiday.collect(2026, conn=self.conn)
            holiday.collect(2026, conn=self.conn)
        self.assertEqual(self.sql("SELECT CAST(holiday_date AS CHAR), name FROM holiday ORDER BY holiday_date"),
                         (("2026-09-24", "추석"), ("2026-09-25", "추석")))
        self.assertEqual(self.sql("SELECT source, target_date, status, row_count, api_calls FROM collect_log"),
                         (("holiday", date(2026, 1, 1), "success", 2, 1),) * 2)


class KosisDbTest(DbTestCase):
    TABLES = ["collect_log", "item", "crop_production"]

    def setUp(self):
        super().setUp()
        self.sql("INSERT INTO item (item_id, at_code, name, category, is_storable, is_forecast) VALUES "
                 "(10, '0601', '사과', '과일', 1, 1), (6, '0399', '기타', '두류', 0, 0), (34, '0699', '기타', '과일', 0, 0)")

    def test_run_twice_no_duplicates_and_error(self):
        data = [kosis_row("사과:생산량", 2024, "460088.4145"), kosis_row("기타:생산량", 2024, "1")]
        with self.fake_get(lambda params: json.dumps(data)):
            kosis.collect(conn=self.conn)
            run = kosis.collect(conn=self.conn)
        self.assertEqual(run.skipped, {"기타"})  # item에 둘이라 어느 것인지 모른다
        self.assertEqual(self.sql("SELECT item_id, year, production_kg FROM crop_production"), ((10, 2024, 460088415),))

        with self.fake_get(lambda params: json.dumps({"err": "11", "errMsg": "유효하지 않은 인증KEY입니다."})):
            with self.assertRaisesRegex(kosis.KosisError, "11"):
                kosis.collect(conn=self.conn)
        self.assertEqual(self.sql("SELECT status FROM collect_log ORDER BY id"), (("success",), ("success",), ("fail",)))

class CheckUnitTest(unittest.TestCase):
    def test_last_sunday(self):
        self.assertEqual(check.last_sunday(date(2026, 11, 14)), date(2026, 11, 8))   # 토 → 지난 일요일
        self.assertEqual(check.last_sunday(date(2026, 11, 16)), date(2026, 11, 15))  # 월 → 어제
        self.assertEqual(check.last_sunday(date(2026, 11, 15)), date(2026, 11, 8))   # 일 → 전 주 일요일

    def test_ranges(self):
        days = [date(2026, 11, 1), date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 5)]
        self.assertEqual(check.ranges(days), "2026-11-01~2026-11-03, 2026-11-05")


class CheckDbTest(DbTestCase):
    """완료 기준(REQ-COL-003): 지난주까지 빠짐없이 있으면 통과, 하나라도 빠지면 무엇이 빠졌는지 알려 준다."""

    TABLES = ["item", "item_producing_area", "weather_daily", "holiday", "crop_production", "settle_price"]
    SINCE, UNTIL = date(2026, 11, 2), date(2026, 11, 8)

    def setUp(self):
        super().setUp()
        self.sql("INSERT INTO item (item_id, at_code, name, category, is_storable, is_forecast) VALUES "
                 "(10, '0601', '사과', '과일', 1, 1), (11, '0602', '배', '과일', 1, 0)")
        self.sql("INSERT INTO item_producing_area (item_id, sido, sigungu, station_id, volume_share) VALUES "
                 "(10, '경북', '안동시', 136, 50), (10, '충북', '충주시', 127, 50)")
        for stn in (136, 127):
            for i in range(7):  # 11/2~11/8 전부. 값이 NULL이어도 행이 있으면 된다
                self.sql("INSERT INTO weather_daily (station_id, obs_date) VALUES (%s, %s)",
                         (stn, self.SINCE + timedelta(days=i)))
        self.sql("INSERT INTO holiday VALUES ('2026-12-25', '기독탄신일'), ('2027-01-01', '1월1일')")
        self.sql("INSERT INTO crop_production (item_id, year, kosis_updated_on) VALUES (10, 2024, '2025-10-29')")
        self.sql("INSERT INTO settle_price (trade_date, grade, avg_price, min_price, max_price, volume_kg, item_id, market_id) "
                 "VALUES ('2026-11-07', '특', 5000, 4000, 6000, 100, 10, '110001')")

    def test_complete_passes(self):
        self.assertEqual(check.check(self.conn, self.SINCE, self.UNTIL), [])

    def test_reports_what_is_missing(self):
        self.sql("DELETE FROM weather_daily WHERE station_id = 127 AND obs_date IN ('2026-11-03', '2026-11-04', '2026-11-08')")
        self.sql("DELETE FROM holiday WHERE YEAR(holiday_date) = 2027")
        self.sql("DELETE FROM crop_production")
        self.assertEqual(check.check(self.conn, self.SINCE, date(2026, 12, 6)), [
            "settle_price: 사과 2026-11-30~2026-12-06 정산이 없다",   # 정산은 11/7에만 있다
            # 12/6까지로 늘리면 두 관측소 모두 11/9~12/6이 비어 있다
            "weather_daily: 관측소 127 31일 빠짐 (2026-11-03~2026-11-04, 2026-11-08~2026-12-06)",
            "weather_daily: 관측소 136 28일 빠짐 (2026-11-09~2026-12-06)",
            "holiday: 2027년 공휴일이 없다",   # 12/6 + 4주 = 2027-01-03이라 2027년이 필요하다
            "crop_production: 사과 2024년 값이 없다 (마지막 없음)",  # 배는 예측 품목이 아니라 보지 않는다
        ])

    def test_price_needs_last_week(self):
        """지난주(월~일)에 정산이 한 건도 없으면 실패. 그 전 주에만 있어도 실패다 (예측 기준 주가 밀린다)."""
        self.sql("UPDATE settle_price SET trade_date = '2026-11-01'")   # 점검 주(11/2~11/8) 바로 전날
        self.assertEqual(check.check(self.conn, self.SINCE, self.UNTIL),
                         ["settle_price: 사과 2026-11-02~2026-11-08 정산이 없다"])

    def test_only_selected(self):
        """--only: 고른 점검만 본다. 주간 예측은 생산량을 쓰지 않아 빠져 있어도 통과해야 한다."""
        self.sql("DELETE FROM crop_production")
        self.assertEqual(check.check(self.conn, self.SINCE, self.UNTIL, ["price", "holiday"]), [])
        self.assertEqual(len(check.check(self.conn, self.SINCE, self.UNTIL, ["production"])), 1)

if __name__ == "__main__":
    unittest.main()


class ProducingAreaUnitTest(unittest.TestCase):
    def test_area(self):
        f = producing_area.area
        self.assertEqual(f("경상북도 영주시"), ("경상북도", "영주시"))
        self.assertEqual(f("(산지)강원특별자치도 평창군 대관령면"), ("강원특별자치도", "평창군"))
        self.assertEqual(f("경기도 수원시권선구 고색동"), ("경기도", "수원시"))   # 구는 시로 묶는다
        self.assertEqual(f("전남광주통합특별시 무안군    "), ("전라남도", "무안군"))  # 통합 시도는 옛 표기로
        self.assertEqual(f("전남광주통합특별시 북구 운암동"), ("광주광역시", "북구"))
        self.assertIsNone(f("미국"))
        self.assertIsNone(f("경상북도"))

    def test_pick_cover_and_min_share(self):
        vol = {("경북", "영주시"): D(50), ("경북", "안동시"): D(20), ("충북", "충주시"): D(15),
               ("전북", "무주군"): D(13), ("경기", "용인시"): D(2)}
        # 50 → 70 → 85(80 넘음)에서 멈춘다. 무주군은 고르지 않는다
        self.assertEqual([(a, b) for a, b, _ in producing_area.pick(vol)],
                         [("경북", "영주시"), ("경북", "안동시"), ("충북", "충주시")])
        self.assertEqual(producing_area.pick({("경북", "영주시"): D(98), ("경기", "용인시"): D(2)})[-1][1], "영주시")
        self.assertEqual(producing_area.pick({}), [])

    def test_nearest(self):
        stations = [(136, 36.57, 128.71), (133, 36.37, 127.37)]   # 안동, 대전
        sid, dist = producing_area.nearest((36.80, 128.62), stations)   # 영주 부근
        self.assertEqual(sid, 136)
        self.assertLess(dist, 30)


def settle_body(rows):
    return json.dumps({"response": {"header": {"resultCode": "0"},
                                    "body": {"totalCount": len(rows), "items": {"item": rows}}}})


def stn_text(lines):
    """기상청 API허브 지점정보 모양. 한 줄: 번호 경도 위도 … 예보구역 법정동코드 수계 주소"""
    head = ["#START7777", "# STN LON LAT ..."]
    return "\n".join(head + [f"  {n}  {lon:.8f}  {lat:.8f} 35100  1.0  1.0  1.0  1.0  1.0  {n} 이름 Name "
                              f"11D20401 5182033035 ---- {addr}" for n, lon, lat, addr in lines] + ["#7777END"])


class ProducingAreaDbTest(DbTestCase):
    """완료 기준: 주산지를 계산해 가장 가까운 관측소와 잇고, 다시 돌려도 행이 늘지 않으며, 빠진 시군구는 지운다."""

    TABLES = ["collect_log", "item_producing_area", "market", "item", "weather_station"]

    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {"KMA_APIHUB_KEY": "TESTKEY"})
        env.start()
        self.addCleanup(env.stop)
        self.sql("INSERT INTO market (market_id, name, sido, lat, lng, is_collect, is_reference) "
                 "VALUES ('110001', '서울가락', '서울', 37.5, 127.1, 0, 1)")
        self.sql("INSERT INTO item (item_id, name, at_code, category, is_storable, is_forecast) "
                 "VALUES (10, '사과', '0601', '과일', 1, 1)")
        self.sql("INSERT INTO weather_station (station_id, name, sido, lat, lng) VALUES "
                 "(136, '안동', '경상북도', 36.57, 128.71), (131, '청주', '충청북도', 36.64, 127.44)")
        self.stn = stn_text([(273, 128.62, 36.80, "경상북도 영주시 풍기읍"), (999, 127.93, 36.97, "충청북도 충주시 안림동")])

    def run_with(self, settle_rows):
        def respond(params):
            return self.stn if "inf" in params else settle_body(settle_rows)
        with self.fake_get(respond):
            return producing_area.collect(["사과"], conn=self.conn)

    def test_run_twice_and_drop(self):
        rows = [{"unit_nm": "kg", "unit_tot_qty": "70", "plor_nm": "경상북도 영주시"},
                {"unit_nm": "kg", "unit_tot_qty": "30", "plor_nm": "충청북도 충주시"},
                {"unit_nm": "상자", "unit_tot_qty": "999", "plor_nm": "경기도 용인시"}]   # kg 아님 → 뺀다
        self.run_with(rows)
        run = self.run_with(rows)
        self.assertEqual(self.sql("SELECT sido, sigungu, station_id, volume_share FROM item_producing_area ORDER BY sigungu"),
                         (("경상북도", "영주시", 136, D("70.00")), ("충청북도", "충주시", 131, D("30.00"))))
        self.assertEqual(run.errors, [])
        # 충주 물량이 거의 없어지면(3% 미만) 그 주산지는 지운다
        self.run_with([rows[0], {"unit_nm": "kg", "unit_tot_qty": "1", "plor_nm": "충청북도 충주시"}])
        self.assertEqual(self.sql("SELECT sigungu FROM item_producing_area"), (("영주시",),))
        self.assertEqual({r[0] for r in self.sql("SELECT status FROM collect_log")}, {"success"})

    def test_area_without_station_is_partial(self):
        self.run_with([{"unit_nm": "kg", "unit_tot_qty": "100", "plor_nm": "경상북도 청송군"}])
        (status, msg), = self.sql("SELECT status, error_msg FROM collect_log")
        self.assertEqual(status, "partial")
        self.assertIn("청송군", msg)

    def test_unknown_item_fails(self):
        with self.assertRaisesRegex(RuntimeError, "배"):
            producing_area.collect(["배"], conn=self.conn)
