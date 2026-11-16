"""alert_rules 판정 테스트 (K17). DB 없이 작은 DataFrame으로 기준만 확인한다.

실행: docker compose -f infra/docker-compose.yml --profile airflow exec airflow-scheduler \
        sh -c "cd /opt/farmit/spark && python -m unittest test_alert_rules -v"
"""
import json
import unittest
from datetime import date

from alert_rules import in_producing_area, judge_import, judge_pest, to_event, to_pest_events
from common import session

COLS = ["item_id", "hs_code", "ym", "import_kg"]
PEST_COLS = ["ncpms_crop_code", "survey_type", "sido", "sigungu", "sigungu_code", "pest_code", "pest_name",
             "survey_date", "value"]


def survey(past_by_year, prev, cur, year=2025, sgg=("경상북도", "영주시", "4721"), pest="SS0101"):
    """year-k년 6/1에 past_by_year 값, year년 5/16에 prev, 6/1에 cur인 예찰 행 목록 (값은 float)"""
    def row(d, v):
        return ("FT010601", "기본조사", *sgg, pest, "갈색무늬병(피해잎율)", d, float(v))
    rows = [row(date(year - len(past_by_year) + i, 6, 1), v) for i, v in enumerate(past_by_year)]
    return rows + [row(date(year, 5, 16), prev), row(date(year, 6, 1), cur)]


def history(hs, month, past_kgs, cur_kg, item_id=1, year=2025):
    """year-5 ~ year-1 같은 달에 past_kgs, year에 cur_kg인 행 목록"""
    rows = [(item_id, hs, date(year - len(past_kgs) + i, month, 1), kg) for i, kg in enumerate(past_kgs)]
    return rows + [(item_id, hs, date(year, month, 1), cur_kg)]


class JudgeImportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = session("test_alert_rules")

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def judge(self, rows):
        return judge_import(self.spark.createDataFrame(rows, COLS)).collect()

    def test_surge(self):
        # 평균 200t, 표본 σ ≈ 15.8t → 기준 ≈ 231.6t. 전년 210t × 1.3 = 273t. 300t는 둘 다 넘는다
        hits = self.judge(history("0001", 3, [190_000, 200_000, 180_000, 220_000, 210_000], 300_000))
        self.assertEqual([(r.ym, r.prev_kg) for r in hits], [(date(2025, 3, 1), 210_000)])

    def test_below_sigma(self):
        # 전년 대비 +30%는 넘지만 평균 + 2σ(넓게 흩어진 과거)는 못 넘는다
        self.assertEqual(self.judge(history("0001", 3, [100_000, 500_000, 120_000, 480_000, 150_000], 300_000)), [])

    def test_below_yoy(self):
        # 평균 + 2σ는 넘지만 전년(250t) 대비 +20%뿐이다
        self.assertEqual(self.judge(history("0001", 3, [100_000, 100_000, 100_000, 100_000, 250_000], 300_000)), [])

    def test_min_volume(self):
        # 사과처럼 평소 0이면 몇 kg만 들어와도 ①②를 넘는다 → 100t 미만은 급증이 아니다
        self.assertEqual(self.judge(history("0002", 4, [0, 0, 0, 0, 0], 50)), [])
        self.assertEqual(len(self.judge(history("0002", 4, [0, 0, 0, 0, 0], 100_000))), 1)

    def test_needs_five_years(self):
        # 과거 같은 달이 4년치뿐이면 판정하지 않는다
        self.assertEqual(self.judge(history("0001", 3, [100, 100, 100, 100], 300_000)), [])

    def test_other_month_not_compared(self):
        # 다른 달(4월)의 큰 값은 3월 비교에 섞이지 않는다
        rows = history("0001", 3, [100_000] * 5, 300_000) + history("0001", 4, [900_000] * 5, 900_000)
        self.assertEqual([r.ym for r in self.judge(rows)], [date(2025, 3, 1)])

    def test_to_event(self):
        r = {"item_id": 7, "hs_code": "080610", "ym": date(2024, 6, 1), "import_kg": 554_000, "prev_kg": 100_600,
             "avg_kg": 201_900.0, "std_kg": 133_500.0, "threshold_kg": 468_900.0}
        e = to_event(r, "포도")
        self.assertEqual(e["source_ref"], "080610:2024-06")
        self.assertEqual(e["title"], "포도 수입량 급증 (2024-06)")
        self.assertEqual(str(e["occurred_at"]), "2024-05-31 15:00:00")   # 2024-06-01 00:00 한국 = UTC 전날 15시
        self.assertEqual(json.loads(e["detail"])["yoy_pct"], 450.7)


class JudgePestTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = session("test_alert_rules_pest")

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def judge(self, rows):
        return judge_pest(self.spark.createDataFrame(rows, PEST_COLS)).collect()

    def test_increase(self):
        # 과거 6/1 평균 1.0, 표본 σ ≈ 0.16 → 기준 ≈ 1.32. 직전(5/16) 1.0 → 이번 3.0은 둘 다 넘는다
        hits = self.judge(survey([1.0, 1.2, 0.8, 1.0, 1.0], 1.0, 3.0))
        self.assertEqual([(h.survey_date, h.n_years, h.prev_value) for h in hits], [(date(2025, 6, 1), 5, 1.0)])

    def test_below_sigma(self):
        # 직전보다 높지만 평년 같은 시기 기준을 못 넘는다
        self.assertEqual(self.judge(survey([1.0, 5.0, 0.5, 4.0, 2.0], 1.0, 3.0)), [])

    def test_not_above_prev(self):
        # 기준은 넘지만 직전 조사(4.0)보다 낮다
        self.assertEqual(self.judge(survey([1.0, 1.0, 1.0, 1.0, 1.0], 4.0, 3.0)), [])

    def test_short_history_not_judged(self):
        # 과거 같은 시기가 2년뿐이면 직전보다 높아도 판정하지 않는다 (3년 이상만)
        self.assertEqual(self.judge(survey([0.0, 0.0], 1.0, 9.0)), [])
        self.assertEqual(len(self.judge(survey([0.0, 0.0, 0.0], 1.0, 9.0))), 1)

    def test_first_survey_of_year_not_judged(self):
        # 그해 첫 조사(5/16)는 직전이 없어 판정하지 않는다. 과거 5/16 값이 있어도 마찬가지
        one = survey([], 0, 0)[0][:7]   # 시군·항목 칸만 쓴다
        rows = [one + (date(y, 5, 16), v) for y, v in [(2022, 0.0), (2023, 0.0), (2024, 0.0), (2025, 9.0)]]
        self.assertEqual(self.judge(rows), [])

    def test_other_pest_not_compared(self):
        # 다른 항목(SS0127 트랩 마리수)의 과거 값은 섞이지 않는다 → 갈색무늬병은 과거 0년이라 판정하지 않는다
        rows = survey([], 1.0, 2.0) + [r for r in survey([500.0] * 5, 1.0, 1.5, pest="SS0127") if r[7].year < 2025]
        self.assertEqual(self.judge(rows), [])

    def test_producing_area(self):
        past = [1.0, 1.0, 1.0]
        rows = (survey(past, 1.0, 2.0, sgg=("전남광주통합특별시", "나주시", "4617"))
                + survey(past, 1.0, 2.0, sgg=("강원특별자치도", "고성군", "4282"))
                + survey(past, 1.0, 2.0, sgg=("경상북도", "영주시", "4721")))
        hits = judge_pest(self.spark.createDataFrame(rows, PEST_COLS))
        items = self.spark.createDataFrame([(1, "사과", "FT010601")], ["item_id", "name", "ncpms_crop_code"])
        # 주산지: 전라남도 나주시(옛 시도 이름), 경상남도 고성군(이름만 같은 다른 시도의 군)
        areas = self.spark.createDataFrame([(1, "전라남도", "나주시"), (1, "경상남도", "고성군")],
                                           ["item_id", "sido", "sigungu"])
        got = in_producing_area(hits, items, areas).collect()
        # 시도는 회원 프로필과 맞출 수 있게 주산지 표기(전라남도)로 바뀐다
        self.assertEqual([(r.item_id, r.sido, r.sigungu) for r in got], [(1, "전라남도", "나주시")])

    def test_to_pest_events_groups_pests(self):
        base = {"item_id": 1, "sido": "경상북도", "sigungu": "영주시", "sigungu_code": "4721", "survey_type": "기본조사",
                "survey_date": date(2025, 6, 1), "prev_value": 1.0, "n_years": 5, "avg_value": 1.0, "threshold": 1.3}
        rows = [dict(base, pest_code="SS0101", pest_name="갈색무늬병(피해잎율)", value=3.0),
                dict(base, pest_code="SS0127", pest_name="복숭아순나방(트랩마리수)", value=40.0)]
        events = to_pest_events(rows, {1: "사과"})
        self.assertEqual(len(events), 1)
        e = events[0]
        self.assertEqual(e["source_ref"], "1:4721:2025-06-01")
        self.assertEqual(e["title"], "영주시 사과 예찰 증가 (06-01 조사)")
        self.assertEqual(str(e["occurred_at"]), "2025-05-31 15:00:00")
        self.assertEqual([p["pest_code"] for p in json.loads(e["detail"])["pests"]], ["SS0101", "SS0127"])


if __name__ == "__main__":
    unittest.main()
