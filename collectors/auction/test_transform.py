"""transform.py 단위 테스트. 실행: python -m unittest (collectors/auction 에서)"""
import unittest
from datetime import datetime

from transform import (
    at_code, is_collect_time, kst_to_utc, new_item, overlap_start, rows_until, source_key, to_message,
)


def row(**over):
    """2026-11-06 실제 응답(광주각화 깻잎)을 본뜬 한 건."""
    base = {
        "auctn_seq": "11", "corp_cd": "24000103", "corp_nm": "광주중앙청과㈜",
        "gds_lclsf_cd": "10", "gds_mclsf_cd": "11", "gds_mclsf_nm": "깻잎",
        "plor_nm": "충남 금산군 금성면  금산위성지구국 ", "qty": "38.000",
        "scsbd_dt": "2026-11-06 13:05:26", "scsbd_prc": "32000.000", "spm_no": "3734",
        "trd_clcln_ymd": "2026-11-06", "unit_nm": "kg", "unit_qty": "2.000",
        "whsl_mrkt_cd": "240001",
    }
    base.update(over)
    return base


class TransformTest(unittest.TestCase):
    def test_at_code_is_large_plus_middle(self):
        self.assertEqual(at_code(row()), "1011")

    def test_source_key_same_row_same_key(self):
        self.assertEqual(source_key(row()), source_key(dict(row())))
        self.assertEqual(len(source_key(row())), 40)

    def test_source_key_split_lot_differs(self):
        # 실제로 본 경우: 같은 원표(spm_no 3701)·경매번호(31)가 7초 차이로 두 번 낙찰
        a = row(spm_no="3701", auctn_seq="31", scsbd_dt="2026-11-06 13:03:04")
        b = row(spm_no="3701", auctn_seq="31", scsbd_dt="2026-11-06 13:02:57")
        self.assertNotEqual(source_key(a), source_key(b))

    def test_kst_to_utc_crosses_date(self):
        self.assertEqual(kst_to_utc("2026-11-06 13:05:26"), "2026-11-06 04:05:26")
        self.assertEqual(kst_to_utc("2026-11-06 08:00:00"), "2026-11-05 23:00:00")

    def test_kg_conversion(self):
        m = to_message(row(), item_id=56, collected_at="2026-11-06 04:30:00")
        self.assertEqual(m["price_per_kg"], 16000.0)   # 32,000원 ÷ 2kg
        self.assertEqual(m["volume_kg"], 76.0)         # 38상자 × 2kg
        self.assertEqual(m["auction_at"], "2026-11-06 04:05:26")
        self.assertEqual(m["grade"], "")
        self.assertEqual(m["origin"], "충남 금산군 금성면 금산위성지구국")  # 공백 정리
        self.assertEqual(m["raw"]["scsbd_prc"], "32000.000")              # 원본 보관

    def test_rounding_one_decimal(self):
        m = to_message(row(scsbd_prc="10000", unit_qty="3"), 1, "t")
        self.assertEqual(m["price_per_kg"], 3333.3)

    def test_non_kg_or_zero_unit_skipped(self):
        self.assertIsNone(to_message(row(unit_nm="개"), 1, "t"))
        self.assertIsNone(to_message(row(unit_qty="0.000"), 1, "t"))

    def test_long_text_cut_to_column(self):
        m = to_message(row(plor_nm="가" * 40, corp_nm="나" * 40), 1, "t")
        self.assertEqual(len(m["origin"]), 30)
        self.assertEqual(len(m["corp_name"]), 30)

    def test_new_item_uses_class_names(self):
        self.assertEqual(new_item(row(gds_lclsf_nm="엽경채류")),
                         {"at_code": "1011", "name": "깻잎", "category": "엽경채류"})
        self.assertEqual(new_item(row())["category"], "")   # 대분류명이 없어도 등록은 한다
        long = new_item(row(gds_mclsf_nm="가" * 60, gds_lclsf_nm="나" * 30))
        self.assertEqual((len(long["name"]), len(long["category"])), (50, 20))   # 컬럼 길이에 맞춰 자른다

    def test_new_item_without_name_is_none(self):
        self.assertIsNone(new_item(row(gds_mclsf_nm="  ")))

    def test_collect_time_window(self):
        self.assertTrue(is_collect_time(datetime(2026, 11, 6, 0, 0)))
        self.assertTrue(is_collect_time(datetime(2026, 11, 6, 11, 59)))
        self.assertFalse(is_collect_time(datetime(2026, 11, 6, 17, 0)))
        self.assertFalse(is_collect_time(datetime(2026, 11, 6, 23, 59)))

    def test_collect_time_afternoon_every_30_minutes(self):
        last = datetime(2026, 11, 6, 11, 57)
        self.assertFalse(is_collect_time(datetime(2026, 11, 6, 12, 0), last))
        self.assertFalse(is_collect_time(datetime(2026, 11, 6, 12, 24), last))
        self.assertTrue(is_collect_time(datetime(2026, 11, 6, 12, 27), last))
        self.assertTrue(is_collect_time(datetime(2026, 11, 6, 16, 59), datetime(2026, 11, 6, 16, 29)))
        self.assertTrue(is_collect_time(datetime(2026, 11, 6, 14, 0)))   # 오후에 새로 켜면 바로 한 번
        self.assertTrue(is_collect_time(datetime(2026, 11, 6, 11, 59), datetime(2026, 11, 6, 11, 57)))   # 오전은 매번

    def test_rows_until_stops_at_older(self):
        rows = [row(scsbd_dt=t) for t in ("2026-11-06 10:00:00", "2026-11-06 09:40:00", "2026-11-06 09:20:00")]
        kept, reached = rows_until(rows, "2026-11-06 09:30:00")
        self.assertEqual([r["scsbd_dt"] for r in kept], ["2026-11-06 10:00:00", "2026-11-06 09:40:00"])
        self.assertTrue(reached)
        self.assertEqual(rows_until(rows, None), (rows, False))

    def test_overlap_start(self):
        self.assertEqual(overlap_start("2026-11-06 10:00:00"), "2026-11-06 09:30:00")
        self.assertIsNone(overlap_start(None))


if __name__ == "__main__":
    unittest.main()
