"""RAG 문서 수집: NCPMS 병해충 + 농사로 현장기술지원·현장애로기술사례 → data/rag/docs/{source}.jsonl (Y12, REQ-COL-006 일부)

사용: python manage.py rag_collect [--source ncpms|fieldtech|fieldqna|disaster|guide|all] [--crops 사과,배] [--max-per-crop N]
- 작물은 기본으로 item 테이블의 모든 품목을 작물 이름으로 바꿔 쓴다 (rag/crop_names.json)
- API 응답은 data/rag/raw/에 캐시해 다시 실행하면 호출하지 않는다. 실행 기록은 collect_log에 남긴다
- --crops로 일부만 받으면 그 작물 문서만 바꾸고 나머지는 그대로 둔다
"""
import json

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from api.models import CollectLog
from codes.models import Item
from rag import crops as crop_util
from rag.sources import disaster, ebook, fieldqna, ncpms, nongsaro
from rag.sources.http import SourceError

SOURCES = {
    'ncpms': ('rag_ncpms', ncpms.collect, None),
    'fieldtech': ('rag_fieldtech', nongsaro.collect, 8),
    'fieldqna': ('rag_fieldqna', fieldqna.collect, None),   # 현장애로기술사례 (농가 질문·전문가 답변)
    'disaster': ('rag_disaster', disaster.collect, None),
    'guide': ('rag_guide', ebook.collect, None),   # 색인하지 않는 길잡이 목차 (원문 링크용)
}
COMMON = {'disaster'}  # 작물에 묶이지 않는 공통 문서: 작물별로 바꾸지 않고 doc_id로 합친다


def docs_path(source):
    return settings.RAG_DATA_DIR / 'docs' / f'{source}.jsonl'


def read_docs(source):
    path = docs_path(source)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def write_docs(source, docs):
    path = docs_path(source)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(d, ensure_ascii=False) + '\n' for d in docs), encoding='utf-8')


class Command(BaseCommand):
    help = 'RAG 문서를 수집한다 (NCPMS 병해충, 농사로 현장기술지원·현장애로기술사례)'

    def add_arguments(self, parser):
        parser.add_argument('--source', default='all', choices=['all', *SOURCES])
        parser.add_argument('--crops', default='', help='쉼표로 구분한 작물 이름. 비우면 item 전체')
        parser.add_argument('--max-per-crop', type=int, default=None)
        parser.add_argument('--refresh', action='store_true', help='캐시를 무시하고 다시 받는다')

    def handle(self, *args, **opts):
        crops = [c.strip() for c in opts['crops'].split(',') if c.strip()] or \
            crop_util.crop_names_for_items(Item.objects.order_by('item_id'))
        self.stdout.write(f'작물 {len(crops)}개: {", ".join(crops[:15])}{" …" if len(crops) > 15 else ""}')
        failed = False
        for source in (SOURCES if opts['source'] == 'all' else [opts['source']]):
            log_source, collect, default_max = SOURCES[source]
            started = timezone.now()
            # 다른 수집기(collectors/common/collect_log.py)처럼 끝난 뒤 한 줄 남긴다
            log = CollectLog(source=log_source, target_date=timezone.localdate(), started_at=started)
            try:
                result = collect(crops, log=self.stdout.write, refresh=opts['refresh'],
                                 max_per_crop=opts['max_per_crop'] or default_max)
            except SourceError as e:
                log.status, log.error_msg, log.finished_at = 'fail', str(e), timezone.now()
                log.api_calls = e.calls  # 실패 전까지 한 호출도 남긴다 (REQ-NFR-009)
                log.save()
                self.stderr.write(f'{source} 실패: {e}')
                failed = True
                continue
            # 오류 없이 끝낸 작물의 문서만 바꾼다. 오류 난 작물·못 다룬 작물의 기존 문서는 그대로 둔다
            done = set(result.done_crops)
            if source in COMMON and not result.docs:
                # 문서를 하나도 못 만들었으면 옛 문서를 지우지 않는다 (목록이 비어 오거나 전부 건너뛴 경우)
                log.status, log.error_msg, log.finished_at = 'partial', '문서 0건, 기존 문서 유지', timezone.now()
                log.api_calls = result.calls
                log.save()
                self.stderr.write(f'{source}: 문서 0건 — 기존 문서를 그대로 둡니다')
                continue
            if source in COMMON:
                # 공통 문서는 오류 없이 끝나면 통째로 바꾸고, 오류가 있으면 못 받은 문서만 옛것을 남긴다
                new_ids = {d['doc_id'] for d in result.docs}
                kept = [d for d in read_docs(source) if result.errors and d['doc_id'] not in new_ids]
                done = set(crops)
            else:
                kept = [d for d in read_docs(source) if not set(d['crop_names']) & done]
            write_docs(source, kept + result.docs)
            log.status = 'partial' if result.errors else 'success'
            log.error_msg = f'오류 {result.errors}건, 반영 못 한 작물 {len(crops) - len(done)}개' if result.errors else None
            log.row_count, log.api_calls, log.finished_at = len(result.docs), result.calls, timezone.now()
            log.save()
            self.stdout.write(self.style.SUCCESS(
                f'{source}: 문서 {len(result.docs)}건 (전체 {len(kept) + len(result.docs)}건), 작물 {len(done)}/{len(crops)}, '
                f'오류 {result.errors}건, 외부 호출 {result.calls}회, {(log.finished_at - started).total_seconds():.0f}초'))
        if failed:
            raise SystemExit(1)
