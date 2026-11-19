"""농사로 현장애로기술사례(elctrnCvpl: 농가 질문 + 전문가 답변) → RAG 문서. (K49, REQ-COL-006)

현장기술지원(nongsaro.py)과 다른 데이터다. 다른 점:
- 키가 다르다: 주간농사정보와 같은 신청서로 승인받은 NONGSARO_WEEKFARM_KEY
- 품목 분류 필드가 없다 → 제목에서 작물 이름을 찾아 붙인다. 제목에 작물이 없는 글은 넣지 않는다
  (공통 문서로 넣으면 모든 작물 검색에 섞여 나온다. 질문 본문까지 보면 "가지치기"·"말씀" 같은 말이 작물로 잡힌다)
- 오래된 글이 많다 → MIN_YEAR 이후 처리된 글만 쓰고, 처리 연월을 본문 첫 줄에 적는다

흐름: 목록(elctrnCvplList) → MIN_YEAR 이후이고 제목에 작물이 있는 글마다 상세(elctrnCvplView) → HTML 정제
→ 연락처·실명 제거 → 약제 사용량 치환.
저장하지 않는 것(REQ-NFR-007): 작성자(wrterNm), 장소(placeInfo), 연락처가 든 문장 전체, 직함 앞 이름.
--crops로 일부 작물만 받으면 그 작물 이름만 붙는다 (여러 작물을 다룬 글의 나머지 작물 이름은 전체 수집 때 붙는다).
"""
import os
import re

from rag import crops as crop_util
from rag.dose_filter import NOTICE, mask_text
from rag.sources.disaster import EMAIL
from rag.sources.http import CollectResult, Fetcher, SourceError
from rag.sources.nongsaro import _parse
from rag.sources.nongsaro_clean import clean_cn

BASE = 'http://api.nongsaro.go.kr/service/elctrnCvpl'
SOURCE_LABEL = '농촌진흥청 농사로 현장애로기술사례'
LICENSE = '공공누리 제1유형'
LIST_ROWS = 1000
MIN_YEAR = '2017'
# 품목 이름이지만 글 제목에서는 대부분 다른 뜻으로 쓰이는 말 ("차이점", "채소종자") — 작물로 붙이지 않는다
AMBIGUOUS = {'차', '말', '종자', '유지'}

# 연락처가 든 문장은 통째로 지운다 ("자세한 내용은 ○○팀 홍길동(☎063-…)에게 문의" — 번호 옆에 담당자 이름이 붙어 있다)
_CONTACT = re.compile(r'(?<!\d)0\d{1,2}\s*[-)]\s*\d{3,4}\s*-\s*\d{4}(?!\d)|(?<!\d)1\d{3}-\d{4}(?!\d)|[☎☏]|담당자\s*[:：]|'
                      + EMAIL.pattern)
_SENT = re.compile(r'(?<=[가-힣]\.)\s+')
# "김철수연구관께서" → "연구관께서". 직함 바로 앞 2~4글자를 이름으로 보고 지운다. 이름이 아닌 흔한 말은 남긴다.
# 직함 뒤는 한글이 아니거나 조사일 때만 ("공동연구사업"의 "연구사"는 직함이 아니다)
_NAME_TITLE = re.compile(r'([가-힣]{2,4})\s?(연구관|연구사|지도관|지도사|박사|주무관|교수|과장|팀장)'
                         r'(?=[^가-힣]|[께에이가은는을를의와과도님]|$)')
_NOT_NAME = {'담당', '담당자', '농업', '농촌', '전문', '해당', '관련', '기술', '소속', '분야', '대학', '대학원', '하나'}


def strip_private(text, writer=''):
    """연락처(전화·이메일·담당자 줄)가 든 문장, 작성자 이름, 직함 앞 이름을 지운다."""
    lines = []
    for line in text.split('\n'):
        kept = [s for s in _SENT.split(line) if not _CONTACT.search(s)]
        if kept:
            lines.append(' '.join(kept))
    text = '\n'.join(lines)
    if writer:
        text = text.replace(writer, '')
    return _NAME_TITLE.sub(lambda m: m.group(0) if m.group(1) in _NOT_NAME else m.group(2), text)


def title_crops(title, known_crops):
    return [c for c in crop_util.find_crops(title, known_crops) if c not in AMBIGUOUS]


def to_doc(item, known_crops):
    """elctrnCvplView item → 문서 dict. 제목에 작물이 없거나 답변이 너무 짧으면 None."""
    writer = item.get('wrterNm', '').strip()
    title = strip_private(item.get('cntntsSj', '').strip(), writer)
    found = title_crops(title, known_crops)
    question = strip_private(clean_cn(item.get('questDtl', ''))[0], writer)
    answer = strip_private(clean_cn(item.get('answerDtl', ''))[0], writer)
    if not found or len(answer) < 50:
        return None
    text, changes = mask_text(f'({item.get("regDt", "")[:7]} 처리된 상담 사례)\n[질문]\n{question}\n[답변]\n{answer}')
    if changes:
        text += f'\n\n{NOTICE}'
    return {
        'doc_id': f'fieldqna_{item["cntntsNo"]}', 'source_type': 'fieldqna', 'source_label': SOURCE_LABEL,
        'title': title, 'crop_names': found, 'pest_name': '',
        'url': '', 'license': LICENSE, 'text': text,
    }


def collect(crops, log=print, refresh=False, max_per_crop=None):
    """작물 이름 목록 → CollectResult. 목록을 못 받으면 SourceError(호출 수 포함)."""
    key = os.environ.get('NONGSARO_WEEKFARM_KEY', '').strip()
    if not key:
        raise SourceError('NONGSARO_WEEKFARM_KEY가 없습니다')
    f = Fetcher('fieldqna', key)
    try:
        return _collect(f, key, crops, log, refresh, max_per_crop)
    except SourceError as e:
        e.calls = f.calls
        raise


def _collect(f, key, crops, log, refresh, max_per_crop):
    rows, page = [], 1
    while True:
        cache = f'list_p{page}_n{LIST_ROWS}'
        body = f.get(f'{BASE}/elctrnCvplList', {'apiKey': key, 'pageNo': page, 'numOfRows': LIST_ROWS},
                     cache_name=cache, refresh=refresh)
        code, items = _parse(body)
        if code != '00':
            raise SourceError(f'현장애로기술사례 목록 결과코드 {code or "없음"}')
        f.save(cache, body)
        rows += items
        if len(items) < LIST_ROWS:
            break
        page += 1

    # 글 번호는 캐시 파일 이름에 쓰므로 숫자만 받는다. 최근 글부터 본다
    recent = {r['cntntsNo']: r for r in rows
              if r.get('cntntsNo', '').isdigit() and r.get('regDt', '')[:4] >= MIN_YEAR}
    docs, failed, count, errors = [], set(), {}, 0
    for no, row in sorted(recent.items(), key=lambda kv: kv[1].get('regDt', ''), reverse=True):
        found = title_crops(row.get('cntntsSj', ''), crops)
        if not found or (max_per_crop and all(count.get(c, 0) >= max_per_crop for c in found)):
            continue
        cache = f'view_{no}'
        try:
            body = f.get(f'{BASE}/elctrnCvplView', {'apiKey': key, 'cntntsNo': no}, cache_name=cache, refresh=refresh)
            code, items = _parse(body)
            problem = '' if code == '00' and items else f'결과코드 {code or "없음"}'
        except SourceError as e:
            problem = str(e)
        if problem:
            failed |= set(found)
            errors += 1
            log(f'  현장애로기술사례 {no}: {problem}')
            continue
        f.save(cache, body)
        doc = to_doc(items[0], crops)
        if not doc:
            continue
        for c in doc['crop_names']:
            count[c] = count.get(c, 0) + 1
        docs.append(doc)
    # rag_collect는 끝낸 작물(done)과 겹치는 옛 문서를 지우고 새 문서를 넣는다. 끝낸 작물이 하나도 없는 문서는 옛것을 둔다
    done = [c for c in crops if c not in failed]
    docs = [d for d in docs if set(d['crop_names']) & set(done)]
    log(f'현장애로기술사례: 목록 {len(rows)}건 중 {MIN_YEAR}년 이후 {len(recent)}건 → 문서 {len(docs)}건 (누적 호출 {f.calls})')
    return CollectResult(docs, f.calls, done, errors)
