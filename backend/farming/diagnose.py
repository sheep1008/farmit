"""증상 진단 (REQ-RAG-001): 품목 + 증상 → 병해충 후보 최대 3개 (맞는 증상·구분점·대응 요약·근거).

흐름: 하이브리드 검색(병해충·현장기술지원 자료만) → LLM 1번(JSON) → 근거 번호 검사(근거 없는 후보 제거)
→ 약제 사용량 치환 → 인용된 근거만 출처로. 근거에 없는 말은 쓰지 않게 시킨다.
"""
from chat.prompts import DISCLAIMER, NOT_FOUND
from rag import llm, retrieve
from rag.dose_filter import KEEP_RE, NOTICE, SENT_SPLIT_RE, DOSE_RE, mask_sentence

MAX_CANDIDATES = 3
EVIDENCE_SIZE = 8
SOURCE_TYPES = ['ncpms_pest', 'fieldtech']
FIELDS = ('matching', 'distinguish', 'action')

SYSTEM = f"""\
너는 농촌진흥청 자료로 병해충 후보를 안내하는 농업기술 상담사다. 농사를 막 시작한 농가가 이해하도록 쉬운 말로 쓴다.

규칙:
- [근거]에 있는 내용만 쓴다. 근거에 없는 병해충·증상·시기·수치는 쓰지 않는다
- 후보는 최대 {MAX_CANDIDATES}개. 증상과 가장 잘 맞는 순서로 쓴다. 근거가 부족하면 후보를 줄이거나 빈 목록으로 답한다
- 후보마다 matching(입력한 증상과 맞는 점), distinguish(비슷한 병해충과 구분하는 점. 근거에 없으면 빈 문자열), action(대응 요약)을 각각 1~2문장으로 쓴다
- evidence에는 그 후보의 내용이 실제로 들어 있는 근거 번호만 정수 목록으로 쓴다. [근거] 목록에 없는 번호는 쓰지 않는다
- 농약·약제의 사용량, 희석 배수 같은 수치는 근거에 있어도 쓰지 않는다. 필요하면 "등록된 사용 기준을 확인하세요"라고 쓴다
- 현장기술지원 근거는 특정 농가의 사례다. 일반 원칙처럼 단정하지 않는다
- 다른 작물에 대한 근거를 선택 작물의 내용처럼 쓰지 않는다
- 설명 없이 JSON 객체 하나만 출력한다: {{"candidates": [{{"name": "병해충 이름", "matching": "", "distinguish": "", "action": "", "evidence": [1]}}]}}"""

USER = """\
[작물]
{crop}

[증상]
{symptom}

[근거]
{evidence}"""


def _clean(text):
    """진단 문장은 모두 약제 맥락이라, 사용량 표현(배수·g·L 등)이 있는 문장은 약제 이름이 없어도 치환한다 (KEEP_RE 예외만 둔다)."""
    parts = SENT_SPLIT_RE.split(str(text or '').strip())
    return ''.join(mask_sentence(p) if i % 2 == 0 and DOSE_RE.search(p) and not KEEP_RE.search(p) else p
                   for i, p in enumerate(parts))


def _refs(value, valid):
    """LLM이 준 evidence → 근거 목록에 있는 정수 번호만 (정수 하나·중첩 목록·True 같은 이상한 값도 견딘다)."""
    if isinstance(value, int) and not isinstance(value, bool):
        value = [value]
    if not isinstance(value, list):
        return []
    return [n for n in dict.fromkeys(x for x in value if isinstance(x, int) and not isinstance(x, bool)) if n in valid]


def diagnose(crop, symptom):
    """반환: (결과 dict, [LlmResult]). 결과 = {candidates, sources, notice, disclaimer}.
    LlmError·StoreUnavailable은 그대로 올린다."""
    evidence = retrieve.search(symptom, crop=crop, queries=[f'{crop} {symptom}'], source_types=SOURCE_TYPES,
                               size=EVIDENCE_SIZE)
    base = {'candidates': [], 'sources': [], 'notice': NOTICE, 'disclaimer': DISCLAIMER}
    if not evidence:
        return {**base, 'message': f'{NOT_FOUND}. 증상을 더 자세히 적거나 가까운 농업기술센터에 문의해 주세요.'}, []
    data, results = llm.complete_json(SYSTEM, USER.format(crop=crop, symptom=symptom,
                                                          evidence=retrieve.format_evidence(evidence)), max_tokens=1500)
    valid = {e['n'] for e in evidence}
    candidates, cited = [], []
    for c in (data or {}).get('candidates') or []:
        if not isinstance(c, dict) or not c.get('name'):
            continue
        refs = _refs(c.get('evidence'), valid)
        if not refs:                      # 근거 번호가 없거나 목록 밖이면 그 후보는 믿지 않고 뺀다
            continue
        candidates.append({'name': _clean(c['name']), **{k: _clean(c.get(k)) for k in FIELDS}, 'evidence': refs})
        cited += [n for n in refs if n not in cited]
        if len(candidates) == MAX_CANDIDATES:
            break
    by_n = {e['n']: e for e in evidence}
    sources = [{'n': n, 'title': by_n[n]['title'], 'source_label': by_n[n]['source_label'],
                'url': by_n[n].get('url', ''), 'license': by_n[n].get('license', '')} for n in sorted(cited)]
    result = {**base, 'candidates': candidates, 'sources': sources}
    if not candidates:
        result['message'] = f'{NOT_FOUND}. 증상을 더 자세히 적거나 가까운 농업기술센터에 문의해 주세요.'
    return result, results
