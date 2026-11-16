"""농사로 농작물재해예방정보(frcDsstrPrevnt) → RAG 공통 문서 (Y11, REQ-COL-006).

흐름: 목록 한 번에 받기 → 정기 호("관리기술 정보")만, 최근 RECENT_MONTHS개월, pdf·hwpx만 → 첨부 내려받기
→ 글자 추출 → 약제 사용량 치환 → 문서. 호 하나가 여러 작물을 다루므로 crop_names는 비워 "공통 문서"로 둔다
(검색에서 어떤 작물을 골라도 후보가 된다, 결정 0013). 등록자 실명(updusrEsntlNm)은 쓰지 않는다.
"""
import datetime
import os
import re
import xml.etree.ElementTree as ET

from django.conf import settings

from rag.dose_filter import NOTICE, mask_text
from rag.sources.doc_extract import ExtractError, extract
from rag.sources.http import CollectResult, Fetcher, SourceError

BASE = 'http://api.nongsaro.go.kr/service/frcDsstrPrevnt'
DOWNLOAD = 'https://www.nongsaro.go.kr/portal/contentsFileDownload.do'  # 첨부 공개 주소 (키 없음)
SOURCE_LABEL = '농촌진흥청 농사로 농작물재해예방정보'
LICENSE = '공공데이터 이용허락범위 제한 없음 (출처: 농촌진흥청 농사로)'
RECENT_MONTHS = 24
MIN_TEXT = 200
MAGIC = {'pdf': b'%PDF', 'hwpx': b'PK'}
PHONE = re.compile(r'(?<!\d)0\d{1,2}[-)\s]?\d{3,4}[-\s]\d{4}(?!\d)')  # 한글 바로 뒤 번호도 잡도록 \b 대신 숫자 경계
BULLET = re.compile(r'\s*([○●■□【])')   # hwpx·pdf 본문은 줄바꿈 없이 이어져 있어 항목 표시 앞에서 줄을 나눈다
EMAIL = re.compile(r'[\w.+-]+@[\w-]+\.[A-Za-z]{2,}[\w.]*')
SECTION_START = re.compile(r'Ⅱ\s*\.?\s*농작물\s*피해\s*예방')   # 본문의 "Ⅱ. 농작물 피해 예방 관리기술"
SECTION_END = re.compile(r'Ⅲ\s*\.?\s*참고\s*자료')


def _parse(body):
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return '', []
    code = (root.findtext('.//resultCode') or '').strip()
    return code, [{c.tag: (c.text or '').strip() for c in item} for item in root.iter('item')]


def _months_ago(today, months):
    y, m = divmod(today.year * 12 + today.month - 1 - months, 12)
    return datetime.date(y, m + 1, 1)


def valid_row(row):
    """외부 응답 값이 파일 경로·주소에 들어가므로 번호 필드가 숫자인 행만 쓴다 (경로 조작 방지)."""
    return row.get('cntntsNo', '').isdigit() and all(row.get(k, '').isdigit() or row.get(k, '') == ''
                                                    for k in ('rtnFileSeCode', 'rtnFileSn'))


def pick_rows(rows, today):
    """정기 호 중 최근 RECENT_MONTHS개월·지원 형식만, 최신순. (고른 목록, 형식이 안 맞아 건너뛴 수)"""
    cutoff = _months_ago(today, RECENT_MONTHS).isoformat()
    regular = [r for r in rows if '관리기술' in r.get('cntntsSj', '') and r.get('svcDtx', '') >= cutoff]
    picked, skipped = [], 0
    for r in sorted(regular, key=lambda r: r['svcDtx'], reverse=True):
        ext = r.get('rtnOrginlFileNm', '').rsplit('.', 1)[-1].lower()
        if ext in MAGIC:
            picked.append({**r, 'ext': ext})
        else:
            skipped += 1
    return picked, skipped


def section_text(text):
    """한 호 전체 중 "Ⅱ. 농작물 피해 예방 관리기술" 본문만 (목차 뒤의 마지막 시작 표시부터 "Ⅲ. 참고자료"까지).
    앞의 기상 전망은 그 달에만 맞고, 뒤의 집필진·연락처는 개인정보라 뺀다. 시작 표시를 못 찾으면 None (전체를 쓰면 집필진이 들어간다)."""
    starts = [m.start() for m in SECTION_START.finditer(text)]
    if not starts:
        return None
    start = starts[-1]
    ends = [m.start() for m in SECTION_END.finditer(text) if m.start() > start]
    return text[start:ends[-1]] if ends else text[start:]


def to_doc(row, text):
    """내려받은 글자 → 문서. 본문 구간만 남기고 약제 사용량·전화번호·이메일을 가린다. 너무 짧으면 None."""
    section = section_text(text)
    if section is None:
        return None
    text, changes = mask_text(section)
    text = BULLET.sub(r'\n\1', EMAIL.sub('', PHONE.sub('', text)))
    if len(text) < MIN_TEXT:
        return None
    if changes:
        text += f'\n\n{NOTICE}'
    return {
        'doc_id': f"disaster_{row['cntntsNo']}", 'source_type': 'disaster', 'source_label': SOURCE_LABEL,
        'title': f"{row['cntntsSj']} ({row['svcDtx']})", 'crop_names': [], 'pest_name': '',
        'url': f"{DOWNLOAD}?cntntsNo={row['cntntsNo']}&fileSeCode={row.get('rtnFileSeCode', '')}&fileSn={row.get('rtnFileSn', '')}",
        'license': LICENSE, 'text': f"발행일: {row['svcDtx']}\n{text}",
    }


def collect(crops, log=print, refresh=False, max_per_crop=None, today=None):
    """crops는 쓰지 않는다 (공통 문서). 목록을 못 받으면 SourceError(호출 수 포함)."""
    key = os.environ.get('NONGSARO_API_KEY', '').strip()
    if not key:
        raise SourceError('NONGSARO_API_KEY가 없습니다')
    f = Fetcher('nongsaro', key)
    try:
        return _collect(f, key, log, refresh, today or datetime.date.today())
    except SourceError as e:
        e.calls = f.calls
        raise


def _collect(f, key, log, refresh, today):
    cache = 'disaster_list_p1_n500'
    body = f.get(f'{BASE}/frcDsstrPrevntLst', {'apiKey': key, 'pageNo': 1, 'numOfRows': 500},
                 cache_name=cache, refresh=refresh)
    code, rows = _parse(body)
    if code != '00':
        raise SourceError(f'농사로 재해예방정보 결과코드 {code or "없음"}')
    f.save(cache, body)
    picked, skipped = pick_rows([r for r in rows if valid_row(r)], today)
    log(f'재해예방정보: 최근 {RECENT_MONTHS}개월 정기 호 {len(picked)}건 (pdf·hwpx 아닌 {skipped}건 건너뜀)')
    docs, errors = [], 0
    for row in picked:
        path = settings.RAG_DATA_DIR / 'raw' / 'disaster' / f"{row['cntntsNo']}.{row['ext']}"
        try:
            data = f.get_bytes(DOWNLOAD, {'cntntsNo': row['cntntsNo'], 'fileSeCode': row.get('rtnFileSeCode', ''),
                                          'fileSn': row.get('rtnFileSn', '')}, path, refresh=refresh)
            if not data.startswith(MAGIC[row['ext']]):  # 오류 페이지를 파일로 저장했으면 지운다
                path.unlink(missing_ok=True)
                raise SourceError('첨부가 아닌 응답')
            doc = to_doc(row, extract(path, row['ext']))
        except (SourceError, ExtractError) as e:
            errors += 1
            log(f"  재해예방정보 {row['cntntsNo']}: {e}")
            continue
        if doc:
            docs.append(doc)
    return CollectResult(docs, f.calls, [], errors)
