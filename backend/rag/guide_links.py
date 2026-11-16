"""채팅 답변 아래에 붙일 농업기술길잡이 원문 링크 (REQ-CHT-007, Y11).

rag_collect --source guide 가 저장한 목차(data/rag/docs/guide.jsonl)만 쓴다. 본문은 쓰지 않는다 (공공누리 제4유형).
1. 질문·검색어를 단어로 나누고(품목명·일반 단어 뺌, 동의어 추가) 목차 이름에 들어 있는 항목을 찾는다. 많이 맞은 순 → 쪽 순
2. 병해충·날씨재해는 그 역할의 장 안에서만 찾는다 ("저온저장고 관리"가 저온 질문에 걸리는 것을 막는다)
3. 맞는 항목이 없거나 대표 장 밖이면 대표 장(병해충 방제·기상재해·재배 기술)을 하나 넣는다
최대 2개. 길잡이가 없는 작물이면 빈 목록.
"""
import json
import re
from functools import lru_cache

from django.conf import settings

from rag.sources.ebook import safe_url

LINK_MAX = 2
GENERIC = {'방법', '확인', '예방', '관리', '대책', '요령', '시기', '방제', '대응', '대비', '원인', '증상', '재배', '농작물',
           '정보', '피해', '어떻게', '어떤', '무엇', '해야', '하나요', '있나요', '알려', '주세요', '질문'}
SYNONYMS = {'아주심기': ['정식'], '정식': ['아주심기'], '서리': ['늦서리', '저온', '동해'], '냉해': ['저온', '동해'],
            '동해': ['저온'], '폭염': ['고온', '일소'], '고온': ['일소'], '썩어요': ['부패'], '장마': ['습해', '침수']}
SCOPE = {'병해충': ('병해충', '병해', '해충', '생리장해'), '날씨재해': ('기상', '재해 대책', '재해대책')}
CHAPTER = {'병해충': ('병해충', '병해', '해충'), '날씨재해': ('기상재해', '이상기상', '재해 대책', '재해대책', '기상'),
           '재배': ('재배 기술', '재배기술', '재배 형태', '재배')}
PARTICLES = '은는이가을를의에도로과와'


def _path():
    return settings.RAG_DATA_DIR / 'docs' / 'guide.jsonl'


@lru_cache(maxsize=4)
def _load(path, mtime):
    out = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip():
            d = json.loads(line)
            for crop in d['crop_names']:
                out[crop] = d
    return out


def guides():
    path = _path()
    return _load(path, path.stat().st_mtime) if path.exists() else {}


def query_words(texts, crop):
    words = []
    for text in texts:
        for w in re.split(r'[\s,.?!()]+', text or ''):
            for x in {w, w[:-1] if len(w) >= 3 and w[-1] in PARTICLES else w}:
                if len(x) < 2 or x == crop or x in GENERIC:
                    continue
                for y in [x, *SYNONYMS.get(x, [])]:
                    if y not in words:
                        words.append(y)
    return words


def _num(s, default=0):
    return int(s) if str(s).strip().isdigit() else default


def _has(row, words):
    text = row['indexName'] + ' ' + row['chapter']
    return any(w in text for w in words)


def _link(book, row):
    return {'book': book, 'title': row['indexName'].strip(), 'page': _num(row['indexPage']),
            'url': safe_url(row['ebookUrl']), 'license': '농촌진흥청 농업기술길잡이, 공공누리 제4유형'}


def _role_chapter(rows, intent):
    for w in CHAPTER.get(intent, ()):
        hit = [r for r in rows if w in r['indexName']]
        if hit:
            return min(hit, key=lambda r: (_num(r['indexLevel'], 9), _num(r['indexPage'])))
    return None


def links_for(crop, intent, question, queries=()):
    """[{book, title, page, url, license}] 최대 2개. 길잡이가 없거나 역할이 맞지 않으면 []"""
    doc = guides().get(crop)
    if not doc or intent not in CHAPTER:
        return []
    rows, scope = doc['rows'], SCOPE.get(intent)
    words = query_words([question, *queries], crop)
    hits = []
    for r in rows:
        if scope and not _has(r, scope):
            continue
        m = [w for w in words if w in r['indexName'].replace(' ', '')]
        if m:
            hits.append((len(m), _num(r['indexPage']), r))
    hits.sort(key=lambda h: (-h[0], h[1]))
    picked, pages = [], set()
    for _, page, r in hits:
        if page not in pages:
            pages.add(page)
            picked.append(r)
    picked = picked[:LINK_MAX]
    chap = _role_chapter(rows, intent)
    # 재배는 맞는 항목이 없을 때만, 병해충·날씨재해는 고른 항목이 대표 장 밖이면 대표 장을 하나 넣는다
    need = chap and (not picked if intent == '재배' else not any(_has(r, CHAPTER[intent]) for r in picked))
    if need and _num(chap['indexPage']) not in {_num(r['indexPage']) for r in picked}:
        picked = picked[:LINK_MAX - 1] + [chap]
    return [l for l in (_link(doc['title'], r) for r in picked) if l['url']]
