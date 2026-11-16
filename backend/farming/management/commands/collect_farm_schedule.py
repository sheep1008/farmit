from django.core.management.base import BaseCommand, CommandError

from farming.collect import collect
from rag.sources.http import SourceError


class Command(BaseCommand):
    help = '농사로 농작업일정을 받아 farm_schedule에 저장한다 (REQ-COL-006). 응답은 캐시하고, --refresh면 다시 받는다.'

    def add_arguments(self, parser):
        parser.add_argument('--refresh', action='store_true')

    def handle(self, *args, **opts):
        try:
            r = collect(log=self.stdout.write, refresh=opts['refresh'])
        except SourceError as e:
            raise CommandError(str(e))
        self.stdout.write(f"품목 {r['items']}개, 행 {r['rows']}개 저장 (외부 호출 {r['calls']}회). "
                          f"일정 없는 품목 {len(r['skipped'])}개: {', '.join(r['skipped'][:15])}")
