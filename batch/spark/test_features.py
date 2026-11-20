"""공통 피처(K30) 테스트. DB 없이 작은 DataFrame으로 dataset.py와 같은 정의인지 확인한다.

실행: docker compose -f infra/docker-compose.yml --profile airflow exec airflow-scheduler \
        sh -c "cd /opt/farmit/spark && python -m unittest test_features -v"
"""
import math
import unittest
from datetime import date, timedelta

from common import session
from features import main_holidays_of, national_features, price_features, vs_national
from weekly_price import drop_outliers, national, weekly

D = "trade_date date, item_id int, market_cd string, grade string, avg_price double, volume_kg double, amount double"
MON = date(2024, 7, 1)


def row(day, market, grade, price, qty):
    return (day, 10, market, grade, float(price), float(qty), float(price) * qty)


class WeeklyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = session("test_features")

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def df(self, rows):
        return self.spark.createDataFrame(rows, D)

    def test_outlier_month_median(self):
        # 7월 등급 행 가격 1000·1100·1200·9000 → 중앙값 1150, 5배(5750) 넘는 9000만 빠진다. ALL 행도 빠진다
        rows = [row(MON, "250001", "특", 1000, 10), row(MON, "250001", "상", 1100, 10),
                row(MON, "340101", "특", 1200, 10), row(MON, "340101", "상", 9000, 1),
                row(MON, "250001", "ALL", 1050, 20)]
        kept = sorted((r.market_cd, r.grade) for r in drop_outliers(self.df(rows)).collect())
        self.assertEqual(kept, [("250001", "상"), ("250001", "특"), ("340101", "특")])

    def test_weekly_and_national_from_grade_rows(self):
        # 250001: 특 1000×10, 등외 400×10 / 340101: 특 2000×30 → 시장 가격은 등외 제외, 전국은 두 시장 합
        rows = [row(MON, "250001", "특", 1000, 10), row(MON, "250001", "등외", 400, 10),
                row(MON + timedelta(days=1), "340101", "특", 2000, 30),
                row(MON, "250001", "ALL", 999999, 1)]   # ALL 행은 쓰지 않는다
        w = {r.market_cd: r for r in weekly(self.df(rows)).collect()}
        self.assertEqual((w["250001"].price_kg, w["250001"].price_allgrade, w["250001"].qty_kg), (1000.0, 700.0, 20.0))
        n = national(self.df(rows)).collect()[0]
        self.assertEqual((n.week, n.nat_price, n.nat_qty), (MON, (10000 + 60000) / 40, 50.0))


class FeatureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = session("test_features_f")

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def wp(self, prices, nat=None):
        """시장 250001의 주별 가격 목록 → weekly_price 모양. nat이 없으면 전국 = 시장의 2배 가격, 물량 4배"""
        rows = []
        for i, p in enumerate(prices):
            n = nat[i] if nat else (None if p is None else p * 2)
            rows.append((10, "250001", MON + timedelta(weeks=i), p, 100.0, n, 400.0))
        return self.spark.createDataFrame(
            rows, "item_id int, market_cd string, week date, price_kg double, qty_kg double, nat_price double, "
                  "nat_qty double")

    def test_chg_and_national(self):
        wp = self.wp([1000.0, 1100.0, 1210.0, 1331.0, 1464.1])
        f = sorted(price_features(wp).collect(), key=lambda r: r.week)
        self.assertAlmostEqual(f[1].chg_1w, math.log(1.1))
        self.assertAlmostEqual(f[4].chg_4w, math.log(1464.1 / 1000))
        n = sorted(national_features(wp).collect(), key=lambda r: r.week)
        self.assertIsNone(n[0].nat_price_ma4)                               # 4주 이동평균은 값 2개부터
        self.assertAlmostEqual(n[1].nat_price_ma4, (2000 + 2200) / 2)
        self.assertAlmostEqual(n[1].nat_chg_1w, math.log(1.1))

    def test_dev_nat_and_rolling_median(self):
        # 시장 가격 / 전국 가격 비: 0.5가 8주 → 8번째 주부터 ratio_nat_med26 = log(0.5). 7주째까지는 비어 있다
        wp = self.wp([1000.0] * 8)
        df = vs_national(wp.withColumn("qty_kg", wp.qty_kg))
        r = sorted(df.collect(), key=lambda r: r.week)
        self.assertAlmostEqual(r[0].dev_nat, math.log(0.5))
        self.assertEqual(r[0].qty_share, 0.25)
        self.assertIsNone(r[6].ratio_nat_med26)
        self.assertAlmostEqual(r[7].ratio_nat_med26, math.log(0.5))

    def test_rolling_median_even_count_averages_middle_two(self):
        # dev_nat 값이 log(0.5) 4개, log(0.25) 4개(전국 4배) → 8개 중앙값은 두 가운데 값의 평균 (pandas median과 같다)
        prices = [1000.0] * 8
        nat = [2000.0] * 4 + [4000.0] * 4
        r = sorted(vs_national(self.wp(prices, nat)).collect(), key=lambda r: r.week)
        self.assertAlmostEqual(r[7].ratio_nat_med26, (math.log(0.5) + math.log(0.25)) / 2)

    def test_main_holiday_with_merged_name(self):
        h = self.spark.createDataFrame([
            (date(2017, 10, 3), "개천절·추석"), (date(2017, 10, 4), "추석"), (date(2017, 10, 5), "추석"),
            (date(2017, 10, 6), "대체공휴일"),
            (date(2024, 2, 9), "설날"), (date(2024, 2, 10), "설날"), (date(2024, 2, 11), "설날"),
            (date(2024, 2, 12), "대체공휴일(설날)"),
        ], "holiday_date date, name string")
        got = sorted((r.kind, r.hday) for r in main_holidays_of(h).collect())
        self.assertEqual(got, [("chuseok", date(2017, 10, 4)), ("seol", date(2024, 2, 10))])


if __name__ == "__main__":
    unittest.main()
