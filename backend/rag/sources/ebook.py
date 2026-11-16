"""농업기술길잡이 목차 → 원문 링크용 자료 (Y11, REQ-COL-006·REQ-CHT-007).

원문 PDF는 공공누리 제4유형(변경금지·상업용금지)이라 본문은 받지 않고, 목록·목차 API(이용허락범위 제한 없음)만 쓴다.
작물 이름이 책의 대상 품목(stdItemNm)에 들어 있는 길잡이 중 가장 새 권(ebookCode가 큰 것)의 목차를 작물마다 한 문서로 둔다.
이 문서는 색인하지 않고(rag_index 대상 아님) rag/guide_links.py가 읽는다. 등록자 필드(registerEsntlNm)는 버린다.
"""
import os
import xml.etree.ElementTree as ET

from rag.sources.http import CollectResult, Fetcher, SourceError

BASE = 'http://api.nongsaro.go.kr/service/cropEbook'
LICENSE = '농촌진흥청 농업기술길잡이, 공공누리 제4유형'
INDEX_ROWS = 1000
ALLOWED_URL = ('http://www.nongsaro.go.kr/', 'https://www.nongsaro.go.kr/')
ROW_FIELDS = ('indexName', 'indexLevel', 'indexPage', 'ebookUrl')


def _parse(body):
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return '', []
    code = (root.findtext('.//resultCode') or '').strip()
    return code, [{c.tag: (c.text or '').strip() for c in item} for item in root.iter('item')]


def latest_book(books, crop):
    """대상 품목에 crop이 있는 권 중 가장 새 권. 없으면 None."""
    mine = [b for b in books if crop in [n.strip() for n in b.get('stdItemNm', '').split(',')]
            and b.get('ebookCode', '').isdigit()]
    return max(mine, key=lambda b: int(b['ebookCode']), default=None)


def safe_url(url):
    """원문 링크는 농사로 주소만 (화면이 href로 쓰므로 javascript: 등 차단)."""
    return url if url.startswith(ALLOWED_URL) else ''


def to_doc(crop, book, rows):
    """목차 행 → 문서. 각 행에 속한 1단계 장 이름(chapter)을 붙인다."""
    out, chapter = [], ''
    for r in rows:
        row = {k: r.get(k, '') for k in ROW_FIELDS}
        row['ebookUrl'] = safe_url(row['ebookUrl'])
        if row['indexLevel'] == '1':
            chapter = row['indexName']
        out.append({**row, 'chapter': chapter})
    return {'doc_id': f'guide_{crop}', 'source_type': 'guide', 'source_label': f"농업기술길잡이 {crop}",
            'title': book['ebookName'], 'crop_names': [crop], 'license': LICENSE, 'rows': out}


def collect(crops, log=print, refresh=False, max_per_crop=None):
    key = os.environ.get('NONGSARO_API_KEY', '').strip()
    if not key:
        raise SourceError('NONGSARO_API_KEY가 없습니다')
    f = Fetcher('nongsaro', key)
    try:
        return _collect(f, key, crops, log, refresh)
    except SourceError as e:
        e.calls = f.calls
        raise


def _call(f, key, op, cache, params, refresh):
    body = f.get(f'{BASE}/{op}', {'apiKey': key, **params}, cache_name=cache, refresh=refresh)
    code, items = _parse(body)
    if code != '00':
        raise SourceError(f'농사로 {op} 결과코드 {code or "없음"}')
    f.save(cache, body)
    return items


def _collect(f, key, crops, log, refresh):
    books = _call(f, key, 'ebookList', 'list_cropEbook_ebookList', {}, refresh)
    docs, done, errors = [], [], 0
    for crop in crops:
        book = latest_book(books, crop)
        if not book:
            done.append(crop)  # 길잡이가 없는 작물은 오류가 아니다 (링크를 안 보여 줄 뿐)
            continue
        code, no = book['ebookCode'], book.get('cropsEbookFileNo', '')
        if not no.isdigit():  # 캐시 파일 이름에 들어가므로 숫자만
            errors += 1
            log(f'  길잡이 {crop}: 파일 번호가 숫자가 아님')
            continue
        try:
            rows = _call(f, key, 'cropIndexList', f'ebook_index_{code}_{no}',
                         {'ebookCode': code, 'cropsEbookFileNo': no, 'pageNo': 1, 'numOfRows': INDEX_ROWS}, refresh)
        except SourceError as e:
            errors += 1
            log(f'  길잡이 {crop}: {e}')
            continue
        docs.append(to_doc(crop, book, rows))
        done.append(crop)
        log(f'길잡이 {crop}: {book["ebookName"]} 목차 {len(rows)}행 (누적 호출 {f.calls})')
    return CollectResult(docs, f.calls, done, errors)
