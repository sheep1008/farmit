"""주간농사정보 수집 → weekly_farm_info (REQ-RAG-008, REQ-COL-006)

사용: python manage.py collect_weekly_farm_info [--count 4] [--refresh]
- 농사로가 매주 수~목요일에 다음 주 호를 올린다. 주 1회 돌리면 된다
- 같은 호는 글 번호로 덮어쓰므로 여러 번 돌려도 중복되지 않는다. 이미 요약을 읽은 호는 PDF를 다시 받지 않는다
- 실행 기록은 collect_log(source=weekfarm)에 남긴다
"""
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from api.models import CollectLog
from farming.weekly import collect
from rag.sources.http import SourceError


class Command(BaseCommand):
    help = '농사로 주간농사정보 최근 호를 받아 weekly_farm_info에 저장한다'

    def add_arguments(self, parser):
        parser.add_argument('--count', type=int, default=4, help='최근 몇 호 (기본 4)')
        parser.add_argument('--refresh', action='store_true', help='받아 둔 PDF를 쓰지 않고 다시 받는다')

    def handle(self, *args, **opts):
        if not 1 <= opts['count'] <= 100:
            raise CommandError('--count는 1~100이어야 합니다.')
        started = timezone.now()
        log = CollectLog(source='weekfarm', target_date=started.astimezone(ZoneInfo('Asia/Seoul')).date(),
                         started_at=started)
        try:
            r = collect(count=opts['count'], log=self.stderr.write, refresh=opts['refresh'])
        except SourceError as e:
            log.status, log.error_msg, log.api_calls, log.finished_at = 'fail', str(e), e.calls, timezone.now()
            log.save()
            raise CommandError(str(e))
        log.status = 'partial' if r['errors'] else 'success'
        log.error_msg = f"PDF를 못 받은 호 {r['errors']}건" if r['errors'] else None
        log.row_count, log.api_calls, log.finished_at = r['rows'], r['calls'], timezone.now()
        log.save()
        self.stdout.write(f"주간농사정보 {r['rows']}호 저장 (외부 호출 {r['calls']}회, PDF 실패 {r['errors']}건, "
                          f"요약 없는 호 {r['no_summary']}건)")
