"""보도자료 수집 → ES press_release (Y10, REQ-COL-007)

사용: python manage.py press_collect [--days 3] [--since 2026-11-01] [--recreate]
- 기본은 오늘(한국 날짜)부터 3일 전까지. 매일 돌리면 빠진 날이 생겨도 3일 안에 메워진다
- 같은 보도자료는 newsId로 덮어쓰므로 여러 번 돌려도 중복되지 않는다
- 실행 기록은 collect_log(source=press)에 남긴다
"""
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from api.models import CollectLog
from rag import press_store
from rag.sources import press


class Command(BaseCommand):
    help = '정책브리핑에서 농식품부·농진청 보도자료를 받아 검색 인덱스에 넣는다'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=3, help='오늘 포함 며칠치 (기본 3)')
        parser.add_argument('--since', default=None, help='YYYY-MM-DD부터 (--days보다 우선)')
        parser.add_argument('--recreate', action='store_true', help='인덱스를 지우고 다시 만든다')

    def handle(self, *args, **opts):
        today = timezone.now().astimezone(ZoneInfo('Asia/Seoul')).date()   # 화면 기준(한국) 날짜
        try:
            start = date.fromisoformat(opts['since']) if opts['since'] else today - timedelta(days=opts['days'] - 1)
        except ValueError:
            raise CommandError('--since는 YYYY-MM-DD 형식이어야 합니다.')
        if start > today or opts['days'] < 1:
            raise CommandError('기간이 잘못됐습니다.')
        started = timezone.now()
        log = CollectLog(source='press', target_date=today, started_at=started)
        try:
            result = press.collect(start, today, log=self.stderr.write)
        except Exception as e:  # 예상 못 한 오류도 기록은 남긴다
            log.status, log.error_msg, log.finished_at = 'fail', f'수집 실패 {type(e).__name__}', timezone.now()
            log.save()
            raise CommandError(log.error_msg)
        try:
            press_store.ensure_index(recreate=opts['recreate'])
            saved = press_store.index_docs(result.docs) if result.docs else 0
        except Exception as e:  # ES 장애 등. 기록을 남기고 실패로 끝낸다
            log.status, log.error_msg = 'fail', f'색인 실패 {type(e).__name__}'
            log.api_calls, log.finished_at = result.calls, timezone.now()
            log.save()
            raise CommandError(log.error_msg)
        log.status = ('fail' if not result.docs else 'partial') if result.errors else 'success'
        log.error_msg = f'목록 요청 실패 {result.errors}건' if result.errors else None
        log.row_count, log.api_calls, log.finished_at = saved, result.calls, timezone.now()
        log.save()
        self.stdout.write(self.style.SUCCESS(
            f'보도자료 {saved}건 ({start}~{today}), 요청 {result.calls}회, 실패 {result.errors}건, '
            f'{(log.finished_at - started).total_seconds():.0f}초'))
        if result.errors:
            raise SystemExit(1)
