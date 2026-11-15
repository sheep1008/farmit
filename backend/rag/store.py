"""Elasticsearch rag_docs 인덱스: 만들기, 조각 넣기, 하이브리드 검색 (결정 0011).

- 한국어 형태소 분석기 nori로 키워드(BM25) 검색, dense_vector(코사인)로 의미 검색을 한다
- 두 결과를 RRF(순위 역수 합)로 합친다. 점수 단위가 달라(BM25 0~수십, 코사인 0~1) 점수를 더하지 않고 순위로 합친다
  ES의 rrf retriever는 유료 라이선스 기능이라 파이썬에서 합친다
- 작물 이름(crop_names)으로 거른다. 다른 작물 자료가 근거로 섞이지 않게
"""
import elasticsearch as es_exc
from django.conf import settings

RRF_K = 60  # RRF 상수. 순위 1위와 10위의 가중치 차이를 완만하게 한다 (흔히 쓰는 값)

_es = None


class StoreUnavailable(Exception):
    """ES에 접속할 수 없다 (API는 503 SERVICE_UNAVAILABLE)."""


def get_es():
    global _es
    if _es is None:
        from elasticsearch import Elasticsearch
        _es = Elasticsearch(settings.RAG_ES_URL, request_timeout=10)
    return _es


def index_body():
    return {
        'settings': {
            'number_of_shards': 1, 'number_of_replicas': 0,  # 노드 1대
            'analysis': {
                'tokenizer': {'ko_tok': {'type': 'nori_tokenizer', 'decompound_mode': 'mixed'}},
                'analyzer': {'korean': {
                    'type': 'custom', 'tokenizer': 'ko_tok',
                    # 조사·어미 등 뜻 없는 품사를 빼고, 한자를 한글 읽기로 바꾼다
                    'filter': ['nori_part_of_speech', 'nori_readingform', 'lowercase'],
                }},
            },
        },
        'mappings': {'properties': {
            'chunk_id': {'type': 'keyword'},
            'doc_id': {'type': 'keyword'},
            'chunk_no': {'type': 'integer'},
            'source_type': {'type': 'keyword'},
            'source_label': {'type': 'keyword', 'index': False},
            'title': {'type': 'text', 'analyzer': 'korean'},
            'text': {'type': 'text', 'analyzer': 'korean'},
            'crop_names': {'type': 'keyword'},
            'pest_name': {'type': 'keyword'},
            'url': {'type': 'keyword', 'index': False},
            'text_hash': {'type': 'keyword', 'index': False},
            'license': {'type': 'keyword', 'index': False},
            'vector': {'type': 'dense_vector', 'dims': settings.RAG_EMBED_DIM, 'index': True,
                       'similarity': 'cosine'},
        }},
    }


def ensure_index(recreate=False):
    es = get_es()
    name = settings.RAG_INDEX
    if recreate and es.indices.exists(index=name):
        es.indices.delete(index=name)
    if not es.indices.exists(index=name):
        es.indices.create(index=name, **index_body())


def index_chunks(chunks, vectors):
    """조각과 벡터를 넣는다 (chunk_id가 같으면 덮어쓴다). 반환: 넣은 수"""
    from elasticsearch.helpers import bulk
    actions = [{'_index': settings.RAG_INDEX, '_id': c['chunk_id'], '_source': {**c, 'vector': v}}
               for c, v in zip(chunks, vectors)]
    ok, _ = bulk(get_es(), actions, refresh=False)
    return ok


def delete_stale(source_type, keep_chunk_ids):
    """그 출처의 조각 중 이번 색인에 없는 것(사라진 문서, 짧아진 문서의 뒤쪽 조각)을 한 번에 지운다. 반환: 지운 수"""
    res = get_es().delete_by_query(index=settings.RAG_INDEX, refresh=True, query={'bool': {
        'filter': [{'term': {'source_type': source_type}}],
        'must_not': [{'ids': {'values': list(keep_chunk_ids)}}]}})
    return res.get('deleted', 0)


def existing_hashes(chunk_ids):
    """chunk_id → 색인된 text_hash (없으면 빠짐). 바뀌지 않은 조각의 임베딩을 건너뛰려고 쓴다."""
    out = {}
    for i in range(0, len(chunk_ids), 500):
        res = get_es().mget(index=settings.RAG_INDEX, ids=chunk_ids[i:i + 500], source_includes=['text_hash'])
        for d in res['docs']:
            if d.get('found') and d['_source'].get('text_hash'):
                out[d['_id']] = d['_source']['text_hash']
    return out


def count():
    try:
        return get_es().count(index=settings.RAG_INDEX)['count']
    except Exception:
        return 0


def _filters(crops, source_types):
    f = []
    if crops:
        f.append({'terms': {'crop_names': list(crops)}})
    if source_types:
        f.append({'terms': {'source_type': list(source_types)}})
    return f


def rrf_fuse(ranked_lists, k=RRF_K):
    """여러 순위 목록(각각 chunk_id 순서) → [(chunk_id, 점수)] 점수 큰 순. 점수 = Σ 1/(k + 순위)"""
    scores = {}
    for ranked in ranked_lists:
        for rank, cid in enumerate(ranked, 1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: (-x[1], x[0]))


def hybrid_search(keyword_texts, query_vector, crops=None, source_types=None, size=8, fetch=30):
    """키워드 검색(검색 문장마다 한 번) + 벡터 검색 1번 → RRF로 합친 상위 size개 조각.

    keyword_texts: 질문과 LLM이 만든 검색어들. 반환 조각에는 rrf 점수와 각 방식의 순위(bm25_rank, knn_rank)가 붙는다.
    """
    es = get_es()
    filters = _filters(crops, source_types)
    source = {'excludes': ['vector']}
    try:
        lists, hits = [], {}
        for text in [t for t in keyword_texts if t and t.strip()]:
            res = es.search(index=settings.RAG_INDEX, size=fetch, source=source, query={'bool': {
                'must': {'multi_match': {'query': text, 'fields': ['title^2', 'text']}},
                'filter': filters}})
            ids = []
            for h in res['hits']['hits']:
                hits.setdefault(h['_id'], h['_source'])
                ids.append(h['_id'])
            lists.append(ids)
        # 검색 문장이 여럿이면 키워드 쪽이 여러 표를 갖지 않게, 키워드 결과끼리 먼저 하나의 순위로 합친다
        bm25_ids = [cid for cid, _ in rrf_fuse(lists)][:fetch]
        lists = [bm25_ids]
        knn_ids = []
        if query_vector is not None:
            knn = {'field': 'vector', 'query_vector': query_vector, 'k': fetch, 'num_candidates': max(100, fetch * 3)}
            if filters:
                knn['filter'] = filters
            res = es.search(index=settings.RAG_INDEX, size=fetch, source=source, knn=knn)
            for h in res['hits']['hits']:
                hits.setdefault(h['_id'], h['_source'])
                knn_ids.append(h['_id'])
            lists.append(knn_ids)
    # 접속 실패·시간 초과(TransportError)·인덱스 없음(ApiError). 쿼리 오류(400)도 503으로 가려지는 한계가 있다
    except (es_exc.TransportError, es_exc.ApiError) as exc:
        raise StoreUnavailable(type(exc).__name__) from None
    out = []
    for cid, score in rrf_fuse(lists)[:size]:
        out.append({**hits[cid], 'rrf': round(score, 5),
                    'bm25_rank': bm25_ids.index(cid) + 1 if cid in bm25_ids else None,
                    'knn_rank': knn_ids.index(cid) + 1 if cid in knn_ids else None})
    return out
