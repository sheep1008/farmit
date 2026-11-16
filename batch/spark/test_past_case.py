"""past_case 사건 추출 테스트 (K18 1단계). DB 없이 작은 DataFrame으로 기준만 확인한다.

실행: docker compose -f infra/docker-compose.yml --profile airflow exec airflow-scheduler \
        sh -c "cd /opt/farmit/spark && python -m unittest test_past_case -v"
"""
import unittest
from datetime import date, datetime, timedelta

from common import session
from past_case import changes, special_events, weather_events

WX = ["item_id", "station_id", "sido", "sigungu", "volume_share", "obs_date", "max_temp", "min_temp", "rain_mm"]
SE = ["event_type", "item_id", "sido", "sigungu", "occurred_at"]
A = (272, "경상북도", "영주시", 25.0)   # 주산지 비중 25% (혼자서도 MIN_SHARE 20%를 넘는다)
B = (127, "충청북도", "충주시", 10.0)
C = (238, "전북특별자치도", "무주군", 12.0)


def days(station, start, temps, rain=0.0, low=10.0):
    """start부터 하루씩, 최고기온 temps인 관측 행 (최저 low, 강수 rain)"""
    st, sido, sgg, share = station
    return [(10, st, sido, sgg, share, start + timedelta(days=i), float(t), low, rain) for i, t in enumerate(temps)]


class WeatherEventsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = session("test_past_case")

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def events(self, rows):
        df = self.spark.createDataFrame(rows, WX)
        return sorted(weather_events(df).collect(), key=lambda r: (r.event_type, r.event_start))

    def test_heat_needs_two_days(self):
        # 33℃ 하루는 사건이 아니고, 34·35℃ 이틀 연속은 사건이다
        rows = days(A, date(2024, 7, 1), [33, 30, 30, 34, 35, 30])
        ev = self.events(rows)
        self.assertEqual([(r.event_type, r.event_start, r.event_end) for r in ev],
                         [("HEAT_WAVE", date(2024, 7, 4), date(2024, 7, 5))])

    def test_missing_day_breaks_run(self):
        # 7/2 관측이 없으면 7/1·7/3은 이어지지 않는다 → 하루짜리 두 번이라 사건 없음
        rows = days(A, date(2024, 7, 1), [34]) + days(A, date(2024, 7, 3), [34])
        self.assertEqual(self.events(rows), [])

    def test_small_share_dropped_and_stations_merged(self):
        # B(10%) 혼자는 기준 미달. B와 C(12%)가 이틀 차이로 걸리면 한 사건, 비중 22%
        self.assertEqual(self.events(days(B, date(2024, 8, 1), [34, 34])), [])
        rows = days(B, date(2024, 8, 1), [34, 34]) + days(C, date(2024, 8, 5), [35, 35])
        ev = self.events(rows)
        self.assertEqual(len(ev), 1)
        r = ev[0]
        self.assertEqual((r.event_start, r.event_end, r.share, r.sido),
                         (date(2024, 8, 1), date(2024, 8, 6), 22.0, "전북특별자치도"))
        self.assertEqual(r.places, ["전북특별자치도 무주군", "충청북도 충주시"])

    def test_far_apart_runs_are_separate(self):
        # 앞 구간 끝(7/2)에서 MERGE_GAP_DAYS(3일)보다 늦게 시작하면 다른 사건
        rows = days(A, date(2024, 7, 1), [34, 34]) + days(A, date(2024, 7, 10), [34, 34])
        self.assertEqual([r.event_start for r in self.events(rows)], [date(2024, 7, 1), date(2024, 7, 10)])

    def test_rain_and_cold(self):
        rain = days(A, date(2023, 7, 15), [25], rain=120.0)                      # 80mm 이상 하루 → 호우
        cold = days(A, date(2023, 1, 20), [0, 0], low=-13.0)                    # −12℃ 이하 이틀 → 한파
        ev = self.events(rain + cold)
        self.assertEqual([(r.event_type, r.event_start) for r in ev],
                         [("COLD_WAVE", date(2023, 1, 20)), ("HEAVY_RAIN", date(2023, 7, 15))])


class ChangesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = session("test_past_case_chg")

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def test_change_from_start_week(self):
        # 사건 2024-07-04(목) 시작 → 기준 주 7/1(월). 1·2주 뒤 +10%·−5%, 3주 뒤 거래 없음, 4주 뒤 +20%
        ev = self.spark.createDataFrame(
            [(10, "HEAT_WAVE", "경상북도", date(2024, 7, 4), date(2024, 7, 5), 25.0, ["경상북도 영주시"])],
            "item_id int, event_type string, sido string, event_start date, event_end date, share double, "
            "places array<string>")
        mon = date(2024, 7, 1)
        prices = [(10, "250001", mon - timedelta(days=7), 999.0), (10, "250001", mon, 1000.0),
                  (10, "250001", mon + timedelta(days=7), 1100.0), (10, "250001", mon + timedelta(days=14), 950.0),
                  (10, "250001", mon + timedelta(days=21), None), (10, "250001", mon + timedelta(days=28), 1200.0),
                  # 기준 주 거래가 없는 시장은 행을 만들지 않는다
                  (10, "340101", mon + timedelta(days=7), 1000.0)]
        w = self.spark.createDataFrame(prices, "item_id int, market_cd string, week date, price_kg double")
        rows = changes(ev, w).collect()
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r.market_cd, r.base_week, r.base_price), ("250001", mon, 1000.0))
        self.assertEqual([r.change_w1, r.change_w2, r.change_w3, r.change_w4], [10.0, -5.0, None, 20.0])
        # 다른 해 자료가 없으니 평년 비교는 비어 있다
        self.assertEqual((r.normal_years, r.normal_w1), (0, None))

    def test_normal_from_other_years_same_week(self):
        # 2024년 27주(7/1) 사건. 2021~2023년 같은 주차에서 1주 뒤 +4%, +6%, +8% → 평년 +6%
        ev = self.spark.createDataFrame(
            [(10, "IMPORT_SURGE", "전국", date(2024, 7, 1), date(2024, 7, 31), None, [])],
            "item_id int, event_type string, sido string, event_start date, event_end date, share double, "
            "places array<string>")
        prices = [(10, "250001", date(2024, 7, 1), 1000.0), (10, "250001", date(2024, 7, 8), 1100.0)]
        for mon, rise in ((date(2021, 7, 5), 1.04), (date(2022, 7, 4), 1.06), (date(2023, 7, 3), 1.08)):
            prices += [(10, "250001", mon, 1000.0), (10, "250001", mon + timedelta(days=7), 1000.0 * rise)]
        w = self.spark.createDataFrame(prices, "item_id int, market_cd string, week date, price_kg double")
        r = changes(ev, w).collect()[0]
        self.assertEqual((r.change_w1, r.normal_years, r.normal_w1, r.normal_w2), (10.0, 3, 6.0, None))

    def test_normal_needs_three_years(self):
        ev = self.spark.createDataFrame(
            [(10, "IMPORT_SURGE", "전국", date(2024, 7, 1), date(2024, 7, 31), None, [])],
            "item_id int, event_type string, sido string, event_start date, event_end date, share double, "
            "places array<string>")
        prices = [(10, "250001", date(2024, 7, 1), 1000.0), (10, "250001", date(2024, 7, 8), 1100.0),
                  (10, "250001", date(2023, 7, 3), 1000.0), (10, "250001", date(2023, 7, 10), 1080.0)]
        w = self.spark.createDataFrame(prices, "item_id int, market_cd string, week date, price_kg double")
        r = changes(ev, w).collect()[0]
        self.assertEqual((r.normal_years, r.normal_w1), (1, None))


class SpecialEventsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = session("test_past_case_se")

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def test_import_month_and_pest_merged_by_date(self):
        rows = [
            # 2025-03 수입 급증: occurred_at = 3/1 00:00 한국 = 2/28 15:00 UTC
            ("IMPORT_SURGE", 93, "전국", None, datetime(2025, 2, 28, 15)),
            # 같은 조사일(6/1 한국)에 두 시군 → 한 사건
            ("PEST_INCREASE", 10, "경상북도", "영주시", datetime(2025, 5, 31, 15)),
            ("PEST_INCREASE", 10, "충청북도", "충주시", datetime(2025, 5, 31, 15)),
            ("WARNING", 10, "경상북도", "영주시", datetime(2025, 7, 1)),          # 기상특보는 쓰지 않는다
        ]
        ev = sorted(special_events(self.spark.createDataFrame(rows, SE)).collect(), key=lambda r: r.event_type)
        self.assertEqual([(r.event_type, r.item_id, r.sido, r.event_start, r.event_end) for r in ev], [
            ("IMPORT_SURGE", 93, "전국", date(2025, 3, 1), date(2025, 3, 31)),
            ("PEST_INCREASE", 10, "경상북도", date(2025, 6, 1), date(2025, 6, 1)),
        ])
        self.assertEqual(ev[1].places, ["경상북도 영주시", "충청북도 충주시"])


if __name__ == "__main__":
    unittest.main()
