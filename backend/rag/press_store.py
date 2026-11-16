"""Elasticsearch press_release 인덱스: 보도자료 넣기·검색 (Y10, REQ-SRC-002, REQ-COL-007).

rag_docs와 달리 벡터 없이 한국어 형태소(nori) 키워드 검색만 한다. 보도자료 제목·요약은 짧아 키워드로 충분하다.
문서 _id는 정책브리핑 newsId라 같은 보도자료를 다시 받아도 덮어쓰기라서 중복되지 않는다.
"""
import elasticsearch as es_exc
from django.conf import settings
from django.utils import timezone

from rag.store import StoreUnavailable, get_es


def index_body():
    return {
        'settings': {
            'number_of_shards': 1, 'number_of_replicas': 0,
            'analysis': {
                'tokenizer': {'ko_tok': {'type': 'nori_tokenizer', 'decompound_mode': 'mixed'}},
                'analyzer': {'korean': {'type': 'custom', 'tokenizer': 'ko_tok',
                                        'filter': ['nori_part_of_speech', 'nori_readingform', 'lowercase']}},
            },
        },
        'mappings': {'properties': {
            'news_id': {'type': 'keyword'},
            'title': {'type': 'text', 'analyzer': 'korean'},
            'summary': {'type': 'text', 'analyzer': 'korean'},
            'published_date': {'type': 'date', 'format': 'yyyy-MM-dd'},   # 보도 날짜(한국 날짜 그대로)
            'source': {'type': 'keyword'},
            'url': {'type': 'keyword', 'index': False},
            'license': {'type': 'keyword', 'index': False},
            'collected_at': {'type': 'date'},                              # UTC
        }},
    }


def ensure_index(recreate=False):
    es, name = get_es(), settings.PRESS_INDEX
    if recreate and es.indices.exists(index=name):
        es.indices.delete(index=name)
    if not es.indices.exists(index=name):
        es.indices.create(index=name, **index_body())


def index_docs(docs):
    """보도자료를 넣는다 (news_id가 같으면 덮어쓴다). 반환: 보낸 수"""
    from elasticsearch.helpers import bulk
    now = timezone.now().isoformat()
    actions = [{'_index': settings.PRESS_INDEX, '_id': d['news_id'], '_source': {**d, 'collected_at': now}}
               for d in docs]
    ok, _ = bulk(get_es(), actions, refresh=True)
    return ok


def search(q, size=10, offset=0):
    """제목(가중치 2)·요약에서 q를 찾는다. 점수 같으면 최신순. 반환: (총 건수, [문서])"""
    try:
        res = get_es().search(
            index=settings.PRESS_INDEX, size=size, from_=offset, track_total_hits=True,
            source={'excludes': ['collected_at']},
            query={'multi_match': {'query': q, 'fields': ['title^2', 'summary'], 'operator': 'and'}},
            sort=[{'_score': 'desc'}, {'published_date': 'desc'}])
    except es_exc.NotFoundError:
        return 0, []          # 첫 수집 전에는 인덱스가 없다. 결과 없음과 같게 본다
    except (es_exc.TransportError, es_exc.ApiError):
        raise StoreUnavailable('press_release') from None
    return res['hits']['total']['value'], [h['_source'] for h in res['hits']['hits']]
