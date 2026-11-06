"""수집기 변환 테스트. 실행 (레포 루트): streaming/.venv/Scripts/python -m unittest discover streaming/producers"""
import unittest

from weather_warning import to_message

# getPwnCd 실제 응답 1행 (2026-11-06)
ROW = {
    'allEndTime': 0, 'areaCode': 'S1151100', 'areaName': '강원북부앞바다', 'cancel': '0', 'command': '1',
    'endTime': 0, 'stnId': '108', 'tmFc': 202611061200, 'tmSeq': 35, 'warnVar': 6, 'warnStress': 0,
    'startTime': 202611061500,
}


class ToMessageTests(unittest.TestCase):
    def test_실제_응답_변환(self):
        self.assertEqual(to_message(ROW), {
            'source_key': '202611061200_S1151100_6_0',   # 발표시각(KST 원래 값)_구역_종류_단계
            'announced_at': '2026-11-06T03:00:00',       # KST 12:00 → UTC 03:00
            'region_code': 'S1151100',
            'region_name': '강원북부앞바다',
            'warning_type': '풍랑',
            'level': '주의보',
            'status': '발표',
            'effective_at': '2026-11-06T06:00:00',       # KST 15:00 → UTC
            'ended_at': None,                            # 0 → 없음
        })

    def test_취소된_특보는_상태가_취소(self):
        self.assertEqual(to_message({**ROW, 'cancel': '1'})['status'], '취소')

    def test_단계가_다르면_다른_특보(self):
        self.assertNotEqual(to_message(ROW)['source_key'], to_message({**ROW, 'warnStress': 1})['source_key'])

    def test_모르는_코드는_코드값으로_남긴다(self):
        msg = to_message({**ROW, 'warnVar': 99, 'command': '9'})
        self.assertEqual((msg['warning_type'], msg['status']), ('코드99', '코드9'))


if __name__ == '__main__':
    unittest.main()
