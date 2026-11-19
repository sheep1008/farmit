"""K48 주간농사정보 테스트 (REQ-RAG-008, REQ-COL-006).

외부 호출은 하지 않는다: Fetcher.get·get_bytes와 PDF 읽기(summary_from_pdf)를 가짜로 바꾼다.
"""
import io
from datetime import date
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from api.models import CollectLog
from farming import weekly
from farming.models import WeeklyFarmInfo
from rag.sources.http import SourceError

# 실제 제47호 요약 쪽을 줄인 것. 분야 이름이 앞 항목 끝에 붙어 나온다 ("...양파벼•")
SUMMARY_TEXT = (
    '요    약분야핵심기술 및 정보농업정보• (기상) 기온은 평년보다 높겠음\n   * 이동성 고기압의 영향'
    '• (토양 유효수분율) 밭 117.8%  * 기준: 11. 16. 양파벼• (벼 종자 준비) 보급종 특성을 미리 알아봄'
    '밭작물• (보리·밀) 배수로 정비채소• (양파) 이중피복• (딸기) 꽃따기 과수• (과원 정비) 낙엽 제거'
    '• (저장) 환기함 양봉• (월동 준비) 온도 차 관리\n- 1 -\n제1장 농업정보 담당 홍길동 연구관(063-000-0000)')

LIST_XML = '''<response><header><resultCode>00</resultCode></header><body><items>
<item><cntntsNo>271665</cntntsNo><subject>주간농사정보 제 47호 (2026.11.23~11.29.)</subject><regDt>2026-11-19</regDt>
<writerNm>홍길동</writerNm><hitCt>44</hitCt>
<fileName>1117-제47호.hwpx|1117-제47호.pdf</fileName>
<downUrlList>https://www.nongsaro.go.kr/portal/contentsFileDownload.do?ep=aa/b@c|https://www.nongsaro.go.kr/portal/contentsFileDownload.do?ep=dd/e@f</downUrlList></item>
<item><cntntsNo>78396</cntntsNo><subject>주간농사정보 제1호 (2009.12.27 ~ 2010.01.02)</subject><regDt>2010-01-05</regDt>
<writerNm>홍길동</writerNm><fileName></fileName><downUrlList></downUrlList></item>
<item><cntntsNo>x</cntntsNo><subject>번호가 깨진 글</subject><regDt>2026-11-01</regDt></item>
</items></body></response>'''
SECTIONS = [{'section': '과수', 'items': ['(과원 정비) 낙엽 제거']}]


class ParseTests(TestCase):
    def test_period_formats_and_year_wrap(self):
        """제목의 기간 표기가 호마다 조금씩 다르다"""
        self.assertEqual(weekly.parse_period('주간농사정보 제 47호 (2026.11.23~11.29.)'), (date(2026, 11, 23), date(2026, 11, 29)))
        self.assertEqual(weekly.parse_period('제 39호 (2026. 9. 28.~10. 4.)'), (date(2026, 9, 28), date(2026, 10, 4)))
        self.assertEqual(weekly.parse_period('제 46호 (2026.11.16.~11.22.)'), (date(2026, 11, 16), date(2026, 11, 22)))
        self.assertEqual(weekly.parse_period('제 52호 (2026.12.28.~1.3.)'), (date(2026, 12, 28), date(2027, 1, 3)))
        self.assertEqual(weekly.parse_period('제1호 (2009.12.27 ~ 2010.01.02)'), (date(2009, 12, 27), date(2010, 1, 2)))
        self.assertEqual(weekly.parse_period('기간 없는 제목'), (None, None))
        self.assertEqual(weekly.parse_period('제 1호 (2026.2.30.~3.5.)'), (None, None))      # 없는 날짜

    def test_summary_splits_by_section_in_fixed_order(self):
        """REQ-RAG-008: 요약 쪽을 분야별로 자른다. 쪽 번호 뒤 본문(담당자 이름)은 넣지 않는다"""
        got = weekly.parse_summary(SUMMARY_TEXT)
        self.assertEqual([s['section'] for s in got], ['농업정보', '벼', '밭작물', '채소', '과수', '양봉'])
        by = {s['section']: s['items'] for s in got}
        self.assertEqual(by['농업정보'], ['(기상) 기온은 평년보다 높겠음 * 이동성 고기압의 영향',
                                      '(토양 유효수분율) 밭 117.8% * 기준: 11. 16. 양파'])
        self.assertEqual(by['채소'], ['(양파) 이중피복', '(딸기) 꽃따기'])
        self.assertEqual(by['양봉'], ['(월동 준비) 온도 차 관리'])
        self.assertNotIn('홍길동', str(got))

    def test_summary_without_marker_is_empty(self):
        self.assertEqual(weekly.parse_summary('목   차 제1장 농업정보'), [])
        self.assertEqual(weekly.summary_from_pdf(b'not a pdf'), [])

    def test_pdf_url_picks_pdf_on_nongsaro_only(self):
        row = {'fileName': 'a.hwpx|a.PDF', 'downUrlList': 'https://www.nongsaro.go.kr/x?ep=1|https://www.nongsaro.go.kr/x?ep=2'}
        self.assertEqual(weekly.pdf_url(row), 'https://www.nongsaro.go.kr/x?ep=2')
        self.assertEqual(weekly.pdf_url({'fileName': 'a.pdf', 'downUrlList': 'https://evil.example/nongsaro.go.kr/a.pdf'}), '')
        self.assertEqual(weekly.pdf_url({'fileName': '', 'downUrlList': ''}), '')


class CollectTests(TestCase):
    def run_collect(self, summary=SECTIONS, pdf=b'%PDF-1.7 ...', **kw):
        with mock.patch.dict('os.environ', {'NONGSARO_WEEKFARM_KEY': 'k'}), \
                mock.patch('rag.sources.http.Fetcher.get', return_value=LIST_XML), \
                mock.patch('rag.sources.http.Fetcher.get_bytes', return_value=pdf) as gb, \
                mock.patch('farming.weekly.summary_from_pdf', return_value=summary):
            return weekly.collect(log=lambda *_: None, **kw), gb

    def test_saves_issue_with_period_pdf_link_and_summary(self):
        r, gb = self.run_collect()
        self.assertEqual((r['rows'], r['errors'], r['no_summary']), (2, 0, 1))     # 번호가 깨진 글은 건너뜀
        w = WeeklyFarmInfo.objects.get(content_no=271665)
        self.assertEqual((w.week_start, w.week_end, w.registered_on), (date(2026, 11, 23), date(2026, 11, 29), date(2026, 11, 19)))
        self.assertTrue(w.pdf_url.endswith('ep=dd/e@f'))                           # hwpx가 아니라 pdf 주소
        self.assertEqual(w.summary, SECTIONS)
        self.assertEqual(gb.call_args.args[1], {'ep': 'dd/e@f'})                   # 주소의 ep 값을 그대로 넘긴다
        old = WeeklyFarmInfo.objects.get(content_no=78396)                         # 첨부 없는 옛 글: 제목만
        self.assertEqual((old.pdf_url, old.summary, old.week_end), ('', [], date(2010, 1, 2)))

    def test_writer_name_is_not_stored(self):
        """REQ-NFR-007: 작성자 실명은 어느 컬럼에도 없다"""
        self.run_collect()
        for w in WeeklyFarmInfo.objects.all():
            self.assertNotIn('홍길동', ' '.join(str(v) for v in vars(w).values()))

    def test_rerun_has_no_duplicates_and_skips_pdf_already_read(self):
        """REQ-COL-008: 두 번 돌려도 행 수가 같다. 요약을 읽은 호는 PDF를 다시 받지 않는다"""
        self.run_collect()
        _, gb = self.run_collect()
        self.assertEqual(WeeklyFarmInfo.objects.count(), 2)
        gb.assert_not_called()
        _, gb = self.run_collect(refresh=True)
        gb.assert_called_once()

    def test_pdf_failure_keeps_title_and_counts_error(self):
        r, _ = self.run_collect(pdf=b'<html>error</html>')
        self.assertEqual((r['rows'], r['errors']), (2, 1))
        self.assertEqual(WeeklyFarmInfo.objects.get(content_no=271665).summary, [])

    def test_missing_or_unapproved_key_stops(self):
        with mock.patch.dict('os.environ', {'NONGSARO_WEEKFARM_KEY': ''}):
            with self.assertRaises(SourceError):
                weekly.collect(log=print)
        bad = '<response><header><resultCode>12</resultCode></header></response>'
        with mock.patch.dict('os.environ', {'NONGSARO_WEEKFARM_KEY': 'k'}), \
                mock.patch('rag.sources.http.Fetcher.get', return_value=bad):
            with self.assertRaisesMessage(SourceError, '결과코드 12'):
                weekly.collect(log=print)


class CommandTests(TestCase):
    PATH = 'farming.management.commands.collect_weekly_farm_info.collect'

    def test_command_writes_collect_log(self):
        out = io.StringIO()
        with mock.patch(self.PATH, return_value={'rows': 4, 'calls': 5, 'errors': 0, 'no_summary': 1}) as c:
            call_command('collect_weekly_farm_info', '--count', '4', stdout=out, stderr=io.StringIO())
        self.assertEqual(c.call_args.kwargs['count'], 4)
        self.assertIn('4호 저장', out.getvalue())
        log = CollectLog.objects.get(source='weekfarm')
        self.assertEqual((log.status, log.row_count, log.api_calls), ('success', 4, 5))
        self.assertIsNotNone(log.finished_at)

    def test_partial_and_fail_are_logged(self):
        with mock.patch(self.PATH, return_value={'rows': 4, 'calls': 5, 'errors': 2, 'no_summary': 2}):
            call_command('collect_weekly_farm_info', stdout=io.StringIO(), stderr=io.StringIO())
        self.assertEqual(CollectLog.objects.get(source='weekfarm').status, 'partial')
        err = SourceError('농사로 결과코드 12')
        err.calls = 1
        with mock.patch(self.PATH, side_effect=err):
            with self.assertRaises(CommandError):
                call_command('collect_weekly_farm_info', stdout=io.StringIO(), stderr=io.StringIO())
        failed = CollectLog.objects.filter(source='weekfarm', status='fail').get()
        self.assertEqual((failed.api_calls, failed.error_msg), (1, '농사로 결과코드 12'))


class WeeklyApiTests(TestCase):
    URL = '/api/farming/weekly'

    @classmethod
    def setUpTestData(cls):
        from codes.models import Item
        cls.apple = Item.objects.create(at_code='0601', name='사과', category='과실류')
        cls.seaweed = Item.objects.create(at_code='5301', name='미역', category='신선 해조류')

    def issue(self, no, start, end, registered, summary=SECTIONS, url='https://www.nongsaro.go.kr/x?ep=1'):
        from django.utils import timezone
        return WeeklyFarmInfo.objects.create(content_no=no, title=f'주간농사정보 제 {no}호', week_start=start, week_end=end,
                                             registered_on=registered, pdf_url=url, summary=summary,
                                             collected_at=timezone.now())

    def get(self, today, **params):
        with mock.patch('farming.views._today_kst', return_value=today):
            return self.client.get(self.URL, params)

    def test_returns_issue_covering_today_not_the_newest(self):
        """REQ-RAG-008: 다음 주 호가 먼저 올라와도 오늘이 기간에 드는 호를 준다"""
        self.issue(46, date(2026, 11, 16), date(2026, 11, 22), date(2026, 11, 11))
        self.issue(47, date(2026, 11, 23), date(2026, 11, 29), date(2026, 11, 19))
        res = self.get(date(2026, 11, 20))
        self.assertEqual(res.status_code, 200)
        data = res.json()['data']
        self.assertEqual((data['available'], data['title'], data['week_start'], data['week_end'], data['registered_on']),
                         (True, '주간농사정보 제 46호', '2026-11-16', '2026-11-22', '2026-11-11'))
        self.assertEqual((data['url'], data['sections'], data['focus']), ('https://www.nongsaro.go.kr/x?ep=1', SECTIONS, None))
        self.assertEqual(res.json()['meta'], {'source': '농촌진흥청 농사로 주간농사정보', 'license': '공공누리 제1유형 (출처표시)'})

    def test_falls_back_to_newest_when_no_issue_covers_today(self):
        self.issue(45, date(2026, 11, 9), date(2026, 11, 15), date(2026, 11, 5))
        self.issue(44, None, None, date(2026, 10, 29), summary=[], url='')     # 기간·요약·첨부를 못 읽은 호
        self.assertEqual(self.get(date(2026, 12, 25)).json()['data']['title'], '주간농사정보 제 45호')
        WeeklyFarmInfo.objects.filter(content_no=45).delete()
        data = self.get(date(2026, 12, 25)).json()['data']
        self.assertEqual((data['available'], data['url'], data['sections'], data['week_start']), (True, None, [], None))

    def test_focus_follows_item_category(self):
        self.issue(46, date(2026, 11, 16), date(2026, 11, 22), date(2026, 11, 11))
        self.assertEqual(self.get(date(2026, 11, 20), item_id=self.apple.pk).json()['data']['focus'], '과수')
        self.assertIsNone(self.get(date(2026, 11, 20), item_id=self.seaweed.pk).json()['data']['focus'])   # 맞는 분야 없음

    def test_nothing_collected_is_200_with_message(self):
        res = self.get(date(2026, 11, 20), item_id=self.apple.pk)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['data'], {'available': False, 'title': None, 'week_start': None, 'week_end': None,
                                              'registered_on': None, 'url': None, 'focus': '과수', 'sections': []})
        self.assertIn('message', res.json()['meta'])

    def test_bad_or_unknown_item_and_no_login_needed(self):
        self.assertEqual(self.get(date(2026, 11, 20), item_id='abc').json()['error']['code'], 'VALIDATION_ERROR')
        self.assertEqual(self.get(date(2026, 11, 20), item_id='999999').status_code, 404)
        self.issue(46, date(2026, 11, 16), date(2026, 11, 22), date(2026, 11, 11))
        with self.assertNumQueries(1):
            self.get(date(2026, 11, 20))
