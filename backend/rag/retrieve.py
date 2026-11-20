"""질문 → 근거 목록 (채팅 답변·점검표가 쓴다).

검색 문장 = 질문 + LLM이 뽑은 검색어들. 키워드 검색은 문장마다, 벡터 검색은 "작물 + 질문" 한 번.
선택 작물로 거르고, 결과에 [근거 n] 번호를 붙인다.
"""
from rag import embed, store

DEFAULT_SIZE = 6


def search(question, crop=None, queries=None, source_types=None, size=DEFAULT_SIZE):
    """반환: [{n, title, source_type, source_label, url, license, text, chunk_id, doc_id, rrf, bm25_rank, knn_rank}]"""
    texts = [question] + [q for q in (queries or []) if q and q != question]
    vector_text = f'{crop} {question}' if crop and crop not in question else question
    hits = store.hybrid_search(texts, embed.embed_query(vector_text), crops=[crop] if crop else None,
                               source_types=source_types, size=size)
    return [{'n': i, **h} for i, h in enumerate(hits, 1)]


def format_evidence(evidence):
    """LLM 입력용: [근거 n] 출처 | 제목 + 본문"""
    return '\n\n'.join(f"[근거 {e['n']}] {e['source_label']} | {e['title']}\n{e['text']}" for e in evidence)
