"""보도자료 수집: 정책브리핑(korea.kr) 보도자료 목록 → 농림축산식품부·농촌진흥청 것만 (Y10, REQ-COL-007).

- 정책브리핑이 두 부처의 보도자료를 모두 싣는다. 목록 화면의 제목·요약(앞 200자)·날짜·원문 링크만 쓴다.
  본문·사진·첨부파일은 받지 않는다 (공공누리 제1유형: 텍스트에 한해 출처 표시 조건으로 이용).
- robots.txt(2026-11-16 확인): korea.kr은 User-agent * 에 Allow: /. 부처 사이트(mafra·rda)는 직접 수집하지 않는다.
- 서버에 부담을 주지 않게 요청 사이에 1초를 쉬고, 기간·쪽 수를 제한한다.
"""
import html
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

LIST_URL = 'https://www.korea.kr/briefing/pressReleaseList.do'
VIEW_URL = 'https://www.korea.kr/briefing/pressReleaseView.do'
USER_AGENT = 'FarmItBot/1.0 (student project; press title and link search)'   # HTTP 헤더라 ASCII만 가능
DEPTS = {'A00008': '농림축산식품부', 'B00006': '농촌진흥청'}   # 정책브리핑 부처 코드
PAGE_SIZE = 20          # 정책브리핑 목록은 한 쪽에 20건. 20건보다 적게 오면 마지막 쪽이다
MAX_PAGES = 30          # 한 부처·기간당 쪽 수 상한 (안전장치)
INTERVAL = 1.0          # 요청 사이 대기(초)
LICENSE = '공공누리 제1유형(출처표시)'

_ITEM_RE = re.compile(
    r'<a href="/briefing/pressReleaseView\.do\?newsId=(\d+)[^"]*">.*?<strong>(.*?)</strong>'
    r'.*?<span class="lead">(.*?)</span>.*?<span class="source">\s*<span>(.*?)</span>\s*<span>(.*?)</span>',
    re.S)
_TAG_RE = re.compile(r'<[^>]+>')


class PressError(Exception):
    """재시도 끝에도 목록을 받지 못했다. calls: 실패 전까지 한 요청 수"""
    calls = 0


@dataclass
class PressResult:
    docs: list
    calls: int
    errors: int = 0


def _clean(text):
    return re.sub(r'\s+', ' ', html.unescape(_TAG_RE.sub(' ', text))).strip()


def _date(raw):
    """'2026-11-16' 또는 '2026.11.16' → '2026-11-16'. 모르는 꼴이면 None"""
    m = re.search(r'(\d{4})[-.](\d{1,2})[-.](\d{1,2})', raw)
    return f'{int(m[1]):04d}-{int(m[2]):02d}-{int(m[3]):02d}' if m else None


def parse_list(page_html):
    """목록 HTML → [{news_id, title, summary, published_date, source, url}]. 날짜를 못 읽은 항목은 뺀다."""
    out = []
    for news_id, title, lead, day, dept in _ITEM_RE.findall(page_html):
        published = _date(day)
        if not published:
            continue
        out.append({'news_id': news_id, 'title': _clean(title), 'summary': _clean(lead),
                    'published_date': published, 'source': _clean(dept),
                    'url': f'{VIEW_URL}?newsId={news_id}'})
    return out


def _fetch(params, retries=3):
    url = f'{LIST_URL}?{urllib.parse.urlencode(params)}'
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode('utf-8', errors='replace')
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == retries - 1:
                raise PressError(f'정책브리핑 HTTP {e.code}') from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == retries - 1:
                raise PressError(f'정책브리핑 접속 실패 {type(e).__name__}') from None
        time.sleep(2 ** attempt)


def collect(start, end, depts=None, fetch=_fetch, interval=INTERVAL, max_pages=MAX_PAGES, log=None):
    """start~end(date, 양끝 포함) 기간의 부처별 보도자료. 부처 하나가 실패해도 나머지는 계속한다."""
    docs, calls, errors = [], 0, 0
    for code in depts or DEPTS:
        for page in range(1, max_pages + 1):
            if calls:
                time.sleep(interval)
            calls += 1
            try:
                page_html = fetch({'pageIndex': page, 'startDate': start.isoformat(), 'endDate': end.isoformat(),
                                   'repCodeType': 'dept', 'repCode': code})
            except PressError as e:
                errors += 1
                if log:
                    log(f'{DEPTS.get(code, code)} {page}쪽 실패: {e}')
                break
            items = parse_list(page_html)
            if page_html.count('pressReleaseView.do?newsId=') and not items:
                errors += 1   # 링크는 있는데 하나도 못 읽었다: 화면 구조가 바뀌었을 수 있다
                if log:
                    log(f'{DEPTS.get(code, code)} {page}쪽: 목록을 읽지 못했습니다 (화면 구조 변경?)')
                break
            n = len(items)
            items = [i for i in items if i['source'] in DEPTS.values()]   # 부처 필터가 무시돼도 다른 부처는 넣지 않는다
            docs.extend({**i, 'license': LICENSE} for i in items)
            if n < PAGE_SIZE or not items:
                break
    return PressResult(docs=docs, calls=calls, errors=errors)
