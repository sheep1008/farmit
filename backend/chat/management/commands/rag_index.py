"""RAG 색인: data/rag/docs/*.jsonl → 조각 나누기 → 임베딩 → Elasticsearch rag_docs (Y12)

사용: python manage.py rag_index [--recreate] [--source ncpms|fieldtech|disaster]
- --recreate: 인덱스를 지우고 새로 만든다 (임베딩 모델·매핑을 바꿨을 때)
- 조각 id는 {doc_id}:{순번}이라 다시 실행해도 같은 조각은 덮어쓴다 (건수가 늘지 않는다)
- 본문 해시(text_hash)가 같은 조각은 임베딩을 건너뛴다 (2,300개 전체 임베딩은 개발 PC에서 약 22분)
"""
import time

from django.core.management.base import BaseCommand

from chat.management.commands.rag_collect import read_docs
from rag import embed, store
from rag.text import chunks_for_doc

BATCH = 64
SOURCE_TYPES = {'ncpms': 'ncpms_pest', 'fieldtech': 'fieldtech', 'disaster': 'disaster'}  # rag_collect 출처 → 조각의 source_type


class Command(BaseCommand):
    help = 'RAG 문서를 조각내 임베딩과 함께 Elasticsearch에 넣는다'

    def add_arguments(self, parser):
        parser.add_argument('--recreate', action='store_true')
        parser.add_argument('--source', default='all', choices=['all', *SOURCE_TYPES])

    def handle(self, *args, **opts):
        started = time.monotonic()
        store.ensure_index(recreate=opts['recreate'])
        docs, sources = [], (list(SOURCE_TYPES) if opts['source'] == 'all' else [opts['source']])
        for source in sources:
            docs += read_docs(source)
        chunks = [c for doc in docs for c in chunks_for_doc(doc)]
        # 같은 chunk_id가 두 번 나오면 마지막 것만 (문서 중복 방지)
        chunks = list({c['chunk_id']: c for c in chunks}.values())
        old = {} if opts['recreate'] else store.existing_hashes([c['chunk_id'] for c in chunks])
        todo = [c for c in chunks if old.get(c['chunk_id']) != c['text_hash']]
        self.stdout.write(f'문서 {len(docs)}건 → 조각 {len(chunks)}개, 바뀐 조각 {len(todo)}개 임베딩 시작')
        done = 0
        for i in range(0, len(todo), BATCH):
            batch = todo[i:i + BATCH]
            vectors = embed.embed_passages([c['text'] for c in batch])
            done += store.index_chunks(batch, vectors)
            if (i // BATCH) % 10 == 0:
                self.stdout.write(f'  {done}/{len(todo)}')
        store.get_es().indices.refresh(index=store.settings.RAG_INDEX)
        # 이번 색인에 없는 옛 조각을 출처별로 한 번에 지운다 (사라진 문서·짧아진 문서)
        # 문서가 0건이 된 출처도 옛 조각을 지우도록 이번에 읽은 출처 전부를 돈다
        for source_type in sorted({SOURCE_TYPES[s] for s in sources}):
            ids = [c['chunk_id'] for c in chunks if c['source_type'] == source_type]
            deleted = store.delete_stale(source_type, ids)
            if deleted:
                self.stdout.write(f'  {source_type}: 옛 조각 {deleted}개 삭제')
        self.stdout.write(self.style.SUCCESS(
            f'색인 완료: 새로 넣은 조각 {done}개, 그대로 둔 조각 {len(chunks) - len(todo)}개, 인덱스 전체 {store.count()}개, {time.monotonic() - started:.0f}초'))
