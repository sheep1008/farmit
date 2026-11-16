"""농작업일정 계산 (LLM 없음, REQ-RAG-002·003·005·006). 옛 rag_project의 features.py 규칙을 DB 행에 맞게 옮겼다.

행 하나 = 작업 하나의 기간(월·순). 같은 작업이 겹치거나 붙은 기간이면 하나로 합치고, 작업 종류(kind)는 작업 이름으로 나눈다.
"""
import re

GROWTH_STAGE_PREFIX = '생육과정'            # 농사로 시기정보 구분. 이달의 할 일·간트에는 이 구분만 쓴다
KIND_WORK, KIND_GROWTH, KIND_CAUTION = '농작업', '생육 단계', '주의 시기'
GROWTH_WORDS = ['발아', '전엽', '개화', '꽃눈분화', '생장비대', '성숙', '착색', '낙엽', '휴면', '생육기']
CAUTION_WORDS = ['병해충 발생', '병해충발생', '장마', '호우', '태풍']
PERIOD_ORDER = {'상': 0, '중': 1, '하': 2}
PERIOD_LABEL = {'상': '상순', '중': '중순', '하': '하순'}
SEASONS = {'봄': [3, 4, 5], '여름': [6, 7, 8], '가을': [9, 10, 11], '겨울': [12, 1, 2]}
# 조건 탐색의 작업 말 → 작업 이름에 들어 있는 낱말 ("심는" = 씨뿌림·아주심기·정식·옮겨심기·묘목심기)
TASK_KEYWORDS = {
    '심기': ['심기', '아주심기', '정식', '옮겨심기', '묘목심기', '파종', '씨뿌림', '씨뿌리기'],
    '파종': ['파종', '씨뿌림', '씨뿌리기'],
    '수확': ['수확'],
    '전정': ['전정', '가지치기', '정지'],
    '시비': ['거름', '시비', '비료'],
    '봉지씌우기': ['봉지'],
    '꽃솎기': ['꽃솎기', '열매솎기', '적화', '적과'],
}
# 질문 속 말 → TASK_KEYWORDS 키 (긴 말부터 본다)
TASK_TRIGGERS = [('봉지', '봉지씌우기'), ('꽃솎기', '꽃솎기'), ('열매솎기', '꽃솎기'), ('솎기', '꽃솎기'), ('가지치기', '전정'),
                 ('전정', '전정'), ('거름', '시비'), ('비료', '시비'), ('시비', '시비'), ('수확', '수확'), ('파종', '파종'),
                 ('씨뿌', '파종'), ('씨 뿌', '파종'), ('심는', '심기'), ('심기', '심기'), ('심어', '심기'), ('정식', '심기')]
# 질문 속 분류 말 → item.category(aT 부류) 목록. 부류 이름은 item 테이블의 값이다
CATEGORY_GROUPS = {
    '과일': ['과실류', '과일과채류', '수실류'], '과수': ['과실류', '과일과채류', '수실류'],
    '채소': ['과채류', '과일과채류', '엽경채류', '근채류', '조미채소류', '양채류', '산채류'],
    '식량작물': ['두류', '잡곡류', '서류'], '특용작물': ['특용작물류', '약용작물류', '버섯류'], '화훼': ['관엽식물류'],
}


def task_kind(task):
    """작업 이름 → 농작업 / 생육 단계 / 주의 시기. 쉼표로 나눈 부분 기준: 모든 부분이 생육 단계 말이면 생육 단계,
    한 부분이라도 주의 시기 말이면 주의 시기, 나머지는 농작업 ("발아기, 모기르기"는 농작업)."""
    parts = [p.strip() for p in task.split(',') if p.strip()] or [task]
    if any(w in p for p in parts for w in CAUTION_WORDS):
        return KIND_CAUTION
    if all(any(w in p for w in GROWTH_WORDS) for p in parts):
        return KIND_GROWTH
    return KIND_WORK


def months_of(row):
    b, e = row['start_month'], row['end_month']
    return list(range(b, e + 1)) if b <= e else list(range(b, 13)) + list(range(1, e + 1))


def period_text(row):
    return f"{row['start_month']}월 {PERIOD_LABEL[row['start_period']]}~{row['end_month']}월 {PERIOD_LABEL[row['end_period']]}"


def _key(month, period):
    return (month, PERIOD_ORDER.get(period, 0))


def merge_same_task(rows):
    """같은 작업이 겹치거나 붙은 기간이면 하나로 합친다. 해를 넘는 행은 그대로 둔다."""
    out = []
    for task in dict.fromkeys(r['task_name'] for r in rows):
        same = sorted((dict(r) for r in rows if r['task_name'] == task),
                      key=lambda r: _key(r['start_month'], r['start_period']))
        merged = [same[0]]
        for r in same[1:]:
            cur = merged[-1]
            wraps = cur['start_month'] > cur['end_month'] or r['start_month'] > r['end_month']
            if not wraps and era_index(r['start_month'], r['start_period']) <= era_index(cur['end_month'], cur['end_period']) + 1:
                if _key(r['end_month'], r['end_period']) > _key(cur['end_month'], cur['end_period']):
                    cur['end_month'], cur['end_period'] = r['end_month'], r['end_period']
            else:
                merged.append(r)
        out += merged
    return out


def prepare(rows):
    """DB 행(dict) → 합친 뒤 kind·period를 붙인 목록."""
    return [dict(r, kind=task_kind(r['task_name']), period=period_text(r)) for r in merge_same_task(rows)]


def _query(**flt):
    from farming.models import FarmSchedule
    return FarmSchedule.objects.filter(stage__startswith=GROWTH_STAGE_PREFIX, **flt).values(
        'item_id', 'task_name', 'stage', 'start_month', 'start_period', 'end_month', 'end_period')


def load_rows(item):
    """품목의 생육과정 행 → 합친 뒤 kind·period를 붙인 dict 목록. 일정이 없으면 []."""
    return prepare(list(_query(item=item)))


def load_rows_by_item(item_ids):
    """여러 품목을 쿼리 1번으로: {item_id: 행 목록} (조건 탐색용)."""
    by_item = {}
    for r in _query(item_id__in=list(item_ids)):
        by_item.setdefault(r['item_id'], []).append(r)
    return {i: prepare(rows) for i, rows in by_item.items()}


def entry(row):
    return {'task': row['task_name'], 'kind': row['kind'], 'period': row['period']}


def month_todo(rows, month):
    """이번 달 카드: 농작업은 이번 달 시작 / 계속 / 다음 달 시작, 생육 단계·주의 시기는 이번 달에 걸친 행."""
    nxt = month % 12 + 1
    ordered = sorted(rows, key=lambda r: (_key(r['start_month'], r['start_period']), r['task_name']))
    work = [r for r in ordered if r['kind'] == KIND_WORK]

    def active(kind):
        return [r for r in ordered if r['kind'] == kind and month in months_of(r)]

    return {'start': [entry(r) for r in work if r['start_month'] == month],
            'continue': [entry(r) for r in work if month in months_of(r) and r['start_month'] != month],
            'next': [entry(r) for r in work if r['start_month'] == nxt],
            'growth': [entry(r) for r in active(KIND_GROWTH)],
            'caution': [entry(r) for r in active(KIND_CAUTION)]}


def era_index(month, period):
    """월·순 → 0~35 (1월 상순 = 0). 간트 차트 가로 칸 번호."""
    return (month - 1) * 3 + PERIOD_ORDER.get(period, 0)


def today_index(day):
    """오늘(날짜) → 간트 칸 번호. 1~10일 상순, 11~20일 중순, 그 밖은 하순."""
    return era_index(day.month, '상' if day.day <= 10 else '중' if day.day <= 20 else '하')


def gantt_bars(rows):
    """[{task, kind, period, start, end}] (end는 그 순의 끝). 해를 넘는 행은 두 막대로 나눈다."""
    bars = []
    for r in sorted(rows, key=lambda r: (_key(r['start_month'], r['start_period']), r['task_name'])):
        start, end = era_index(r['start_month'], r['start_period']), era_index(r['end_month'], r['end_period']) + 1
        spans = [(start, end)] if start < end else [(start, 36), (0, end)]
        bars += [{'task': r['task_name'], 'kind': r['kind'], 'period': r['period'], 'start': s, 'end': e}
                 for s, e in spans]
    return bars


def condition_months(text):
    """조건 문장의 월: "8월", "3~5월", "3월부터 5월", 계절(봄 3~5, 여름 6~8, 가을 9~11, 겨울 12~2)."""
    months = set()
    for a, b in re.findall(r'(\d{1,2})\s*월?\s*(?:~|-|부터)\s*(\d{1,2})\s*월', text):
        a, b = int(a), int(b)
        months |= set(range(a, b + 1)) if a <= b else set(range(a, 13)) | set(range(1, b + 1))
    months |= {int(m) for m in re.findall(r'(\d{1,2})\s*월', text)}
    for name, ms in SEASONS.items():
        if re.search(rf'{name}(?!동)', text):      # "봄동"의 "봄"은 계절이 아니다
            months |= set(ms)
    return sorted(m for m in months if 1 <= m <= 12)


def parse_condition(text):
    """조건 문장 → {task: TASK_KEYWORDS 키 또는 None, months: [월], category: 분류 또는 None}. 규칙만 쓴다."""
    task = next((key for word, key in TASK_TRIGGERS if word in text), None)
    category = next((c for c in CATEGORY_GROUPS if c in text), None)
    return {'task': task, 'months': condition_months(text), 'category': category}


def matches(rows, cond):
    """조건에 맞는 행(작업 이름에 낱말이 있고 기간이 조건 월과 겹침) 목록."""
    words = TASK_KEYWORDS.get(cond['task'], []) if cond['task'] else []
    out = []
    for r in rows:
        if r['kind'] != KIND_WORK:            # 생육 단계·주의 시기는 "할 일"이 아니라 탐색 대상이 아니다
            continue
        if words and not any(w in r['task_name'] for w in words):
            continue
        if cond['months'] and not set(months_of(r)) & set(cond['months']):
            continue
        out.append(r)
    return out
