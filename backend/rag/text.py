"""문서를 검색용 조각(chunk)으로 나눈다.

- 줄(문단) 단위로 모아 CHUNK_SIZE자를 넘기 전에 자른다. 문단 중간을 자르지 않아 문장이 끊기지 않는다
- 앞 조각의 끝 몇 줄(CHUNK_OVERLAP자 이내, 줄이 더 길면 그 줄의 끝 CHUNK_OVERLAP자)을 다음 조각 앞에 다시 넣는다.
  경계에 걸친 내용도 찾을 수 있게
- 한 줄이 (CHUNK_SIZE - CHUNK_OVERLAP)보다 길면 문장 끝(다.·요.)에서 나누고, 그래도 길면 글자 수로 자른다
- 조각마다 앞에 "[제목]" 한 줄을 붙인다. 조각만 봐도 무슨 문서인지 알고, 벡터에도 제목 뜻이 들어간다
"""
import hashlib
import re

CHUNK_SIZE = 700
CHUNK_OVERLAP = 120

_SENT_RE = re.compile(r'(?<=[다요음함됨]\.)\s+')


def _split_long(line, size):
    parts, buf = [], ''
    for sent in _SENT_RE.split(line):
        if buf and len(buf) + len(sent) + 1 > size:
            parts.append(buf)
            buf = ''
        buf = f'{buf} {sent}'.strip()
        while len(buf) > size:
            parts.append(buf[:size])
            buf = buf[size:]
    if buf:
        parts.append(buf)
    return parts


def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """본문 → 조각 목록 (제목 머리말 없음)."""
    lines = []
    for line in (text or '').split('\n'):
        line = line.rstrip()
        if not line.strip():
            continue
        # 긴 줄은 겹침 자리를 남기고 자른다 (겹침 + 줄이 size를 넘지 않게)
        limit = size - overlap - 1
        lines.extend(_split_long(line, limit) if len(line) > limit else [line])

    chunks, cur = [], []
    for line in lines:
        if cur and sum(len(x) + 1 for x in cur) + len(line) > size:
            chunks.append('\n'.join(cur))
            # 겹침: 끝에서부터 overlap자 안의 줄만 가져간다
            tail, n = [], 0
            for prev in reversed(cur):
                if n + len(prev) > overlap:
                    break
                tail.insert(0, prev)
                n += len(prev) + 1
            if not tail:  # 마지막 줄이 겹침보다 길면 그 줄의 끝부분만 가져간다
                tail = [cur[-1][-overlap:]]
            elif len(tail) == len(cur):  # 앞 조각 전체가 겹침에 들어가면 다음 조각에 통째로 반복되므로 겹치지 않는다
                tail = []
            cur = tail
        cur.append(line)
    if cur:  # 조각을 내보낸 뒤에는 항상 새 줄을 넣으므로 마지막 cur에는 새 내용이 있다
        chunks.append('\n'.join(cur))
    return chunks


def chunks_for_doc(doc):
    """문서 레코드 → 색인할 조각 dict 목록. chunk_id = {doc_id}:{순번}"""
    out = []
    for i, body in enumerate(chunk_text(doc['text'])):
        out.append({
            'chunk_id': f"{doc['doc_id']}:{i}", 'doc_id': doc['doc_id'], 'chunk_no': i,
            'source_type': doc['source_type'], 'source_label': doc['source_label'],
            'title': doc['title'], 'crop_names': doc.get('crop_names', []),
            'pest_name': doc.get('pest_name', ''), 'url': doc.get('url', ''),
            'license': doc.get('license', ''),
            'text': f"[{doc['title']}]\n{body}",
        })
        out[-1]['text_hash'] = hashlib.sha1(out[-1]['text'].encode()).hexdigest()  # 바뀐 조각만 다시 임베딩
    return out
