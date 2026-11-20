"""농사로 주간농사정보(weekFarmInfo) 수집 → weekly_farm_info (REQ-RAG-008, REQ-COL-006).

흐름: 목록(weekFarmInfoList)에서 최근 몇 호 → 호마다 PDF 첨부를 받아 '요약' 쪽만 분야별로 자른다 → 글 번호로 UPSERT.
이 API는 본문 없이 첨부(hwpx·pdf)만 준다. 뒤쪽 본문에는 담당자 이름·전화가 있어 요약 쪽만 쓴다.
키는 NONGSARO_WEEKFARM_KEY (서비스마다 따로 발급된다). 결과코드 12는 신청·승인이 안 된 키다.
"""
import datetime
import io
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET

from django.conf import settings
from django.utils import timezone
from pypdf import PdfReader

from farming.models import WeeklyFarmInfo
from rag.sources.http import Fetcher, SourceError

BASE = 'http://api.nongsaro.go.kr/service/weekFarmInfo'
SECTIONS = ['농업정보', '벼', '밭작물', '채소', '과수', '화훼', '특작', '축산', '양봉']   # 요약 표의 분야, 이 순서로 나온다
# 품목 분류(item.category) → 먼저 보여 줄 분야. 주간농사정보는 품목별로 나뉘지 않는다
FOCUS = {
    '과수': ['과실류', '수실류'],
    '채소': ['과일과채류', '과채류', '근채류', '산채류', '양채류', '엽경채류', '조미채소류'],
    '밭작물': ['두류', '맥류', '서류', '잡곡류'],
    '특작': ['버섯류', '약용작물류', '인삼류', '특용작물류'],
    '화훼': ['관엽식물류', '초화류'],
}
SUMMARY_HEAD =re.compile(r'요\s*약\s*분야\s*핵심기술 및 정보')
PERIOD = re.compile(r'(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.?\s*[~∼]\s*(?:(\d{4})\.\s*)?(\d{1,2})\.\s*(\d{1,2})')
SUMMARY_PAGES = 5       # 요약은 표지·목차 바로 뒤에 있다


def _parse(body):
    """(결과코드, item dict 목록)"""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return '', []
    code = (root.findtext('.//resultCode') or '').strip()
    return code, [{c.tag: (c.text or '').strip() for c in it} for it in root.iter('item')]


def parse_period(title):
    """제목의 "(2026.11.23~11.29.)" → (시작일, 끝일). 끝 월이 시작 월보다 작으면 해를 넘는다. 못 읽으면 (None, None)."""
    m = PERIOD.search(title)
    if not m:
        return None, None
    y, sm, sd, ey, em, ed = (int(g) if g else None for g in m.groups())
    try:
        start = datetime.date(y, sm, sd)
        end = datetime.date(ey or (y + 1 if em < sm else y), em, ed)
    except ValueError:
        return None, None
    return (start, end) if start <= end else (None, None)


def parse_summary(text):
    """요약 쪽 글자 → [{'section', 'items'}]. 항목은 '•'로 시작하고, 분야 이름은 앞 항목 끝에 붙어 나온다
    ("...양파벼• (벼 종자 준비)"). 그래서 아직 나오지 않은 분야 이름으로 끝날 때만 분야가 바뀐 것으로 본다
    (순서는 고정이고, 그 주에 없는 분야는 건너뛴다)."""
    m = SUMMARY_HEAD.search(text)
    if not m:
        return []
    body = re.split(r'-\s*1\s*-', text[m.end():])[0]           # 쪽 번호 "- 1 -" 뒤는 본문
    chunks = [re.sub(r'\s+', ' ', c).strip() for c in body.split('•')]
    out, idx = [], 0
    for i, chunk in enumerate(chunks):
        label = None
        if i < len(chunks) - 1:
            label = next((s for s in SECTIONS[idx:] if chunk.endswith(s)), None)
        if label:
            chunk = chunk[:-len(label)].strip()
            idx = SECTIONS.index(label) + 1
        if chunk and out:
            out[-1]['items'].append(chunk)
        if label:
            out.append({'section': label, 'items': []})
    return [s for s in out if s['items']]


def summary_from_pdf(data):
    """PDF 바이트 → 분야별 요약. 요약 쪽을 못 찾거나 PDF를 못 읽으면 []."""
    try:
        pages = PdfReader(io.BytesIO(data)).pages[:SUMMARY_PAGES]
        for page in pages:
            text = page.extract_text() or ''
            if SUMMARY_HEAD.search(text):
                return parse_summary(text)
    except Exception:       # pypdf는 깨진 파일에 여러 종류의 예외를 낸다. 요약 없이 제목·링크만 쓴다
        pass
    return []


def pdf_url(row):
    """fileName·downUrlList("a.hwpx|a.pdf", "주소|주소")에서 PDF 주소. 농사로 주소가 아니거나 없으면 ''."""
    names = row.get('fileName', '').split('|')
    urls = row.get('downUrlList', '').split('|')
    for name, url in zip(names, urls):
        host = urllib.parse.urlsplit(url).hostname or ''
        if name.lower().endswith('.pdf') and (host == 'nongsaro.go.kr' or host.endswith('.nongsaro.go.kr')):
            return url
    return ''


def focus_section(category):
    """품목 분류에 맞는 분야 이름. 없으면 None."""
    return next((section for section, cats in FOCUS.items() if category in cats), None)


def current_issue(today):
    """오늘(한국 날짜)이 기간에 드는 호, 없으면 가장 최근에 등록된 호. 수집된 것이 없으면 None."""
    return (WeeklyFarmInfo.objects.filter(week_start__lte=today, week_end__gte=today).order_by('-registered_on').first()
            or WeeklyFarmInfo.objects.order_by('-registered_on', '-content_no').first())


def collect(count=4, log=print, refresh=False):
    """최근 count개 호를 저장한다. 반환: {'rows': 저장한 호 수, 'calls': 외부 호출 수, 'errors': PDF를 못 받은 호 수,
    'no_summary': 요약이 빈 호 수}. 목록을 못 받으면 SourceError(호출 수 포함)."""
    key = os.environ.get('NONGSARO_WEEKFARM_KEY', '').strip()
    if not key:
        raise SourceError('NONGSARO_WEEKFARM_KEY가 없습니다')
    f = Fetcher('weekfarm', key)
    try:
        return _collect(f, key, count, log, refresh)
    except SourceError as e:
        e.calls = f.calls
        raise


def _collect(f, key, count, log, refresh):
    body = f.get(f'{BASE}/weekFarmInfoList', {'apiKey': key, 'pageNo': 1, 'numOfRows': count})   # 매주 바뀌어 캐시하지 않는다
    code, rows = _parse(body)
    if code == '12':
        raise SourceError('농사로 결과코드 12 (주간농사정보를 신청하지 않았거나 승인 전인 키)')
    if code != '00':
        raise SourceError(f'농사로 주간농사정보 결과코드 {code or "없음"}')
    saved = errors = no_summary = 0
    for row in rows:
        try:
            no = int(row['cntntsNo'])
            registered = datetime.date.fromisoformat(row['regDt'])
            title = row['subject'][:200]
        except (KeyError, ValueError):
            continue
        url = pdf_url(row)
        old = WeeklyFarmInfo.objects.filter(content_no=no).first()
        if old and old.summary and old.pdf_url == url and not refresh:
            summary = old.summary                       # 이미 읽은 호는 PDF를 다시 받지 않는다
        elif url:
            summary = _fetch_summary(f, no, url, refresh, log)
            if summary is None:
                errors += 1
                summary = old.summary if old else []
        else:
            summary = []
        start, end = parse_period(title)
        WeeklyFarmInfo.objects.update_or_create(content_no=no, defaults={
            'title': title, 'week_start': start, 'week_end': end, 'registered_on': registered,
            'pdf_url': url, 'summary': summary, 'collected_at': timezone.now()})
        saved += 1
        no_summary += not summary
    return {'rows': saved, 'calls': f.calls, 'errors': errors, 'no_summary': no_summary}


def _fetch_summary(f, no, url, refresh, log):
    """PDF를 받아 요약을 돌려준다. 못 받으면 None (요약 쪽을 못 찾은 것은 []이고 오류가 아니다)."""
    base, _, query = url.partition('?')
    path = settings.RAG_DATA_DIR / 'raw' / 'weekfarm' / f'{no}.pdf'
    try:
        data = f.get_bytes(base, dict(urllib.parse.parse_qsl(query, keep_blank_values=True)), path, refresh=refresh)
    except SourceError as e:
        log(f'  주간농사정보 {no}: {e}')
        return None
    if not data.startswith(b'%PDF-'):       # 오류 페이지를 파일로 저장했으면 지운다
        path.unlink(missing_ok=True)
        log(f'  주간농사정보 {no}: 첨부가 아닌 응답')
        return None
    return summary_from_pdf(data)
