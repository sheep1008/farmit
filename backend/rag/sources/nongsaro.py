"""농사로 현장기술지원(sptTchnlgySport) → RAG 문서.

흐름: 목록(sptTchnlgySportList) 한 번에 받기 → 작물 이름(prdlstCodeNm)이 맞는 글만, 작물마다 최근 max_per_crop건
→ 상세(sptTchnlgySportView) → 본문 HTML 정제(nongsaro_clean: 작성자 실명·읍면 이하 주소 제거, REQ-NFR-007).
응답은 XML. 결과코드 00이 정상이고, 15(도메인 불일치)는 바로 멈춘다.
"""
import os
import xml.etree.ElementTree as ET

from rag.dose_filter import NOTICE, mask_text
from rag.sources.http import CollectResult, Fetcher, SourceError
from rag.sources.nongsaro_clean import to_record

BASE = 'http://api.nongsaro.go.kr/service/sptTchnlgySport'
SOURCE_LABEL = '농촌진흥청 농사로 현장기술지원'
LICENSE = '이용허락범위 제한 없음'
LIST_ROWS = 1500


def _parse(body):
    """(결과코드, item dict 목록)."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return '', []
    code = (root.findtext('.//resultCode') or '').strip()
    items = [{c.tag: (c.text or '').strip() for c in item} for item in root.iter('item')]
    return code, items


def collect(crops, log=print, refresh=False, max_per_crop=8):
    """작물 이름 목록 → CollectResult. 목록을 못 받으면 SourceError(호출 수 포함)."""
    key = os.environ.get('NONGSARO_API_KEY', '').strip()
    if not key:
        raise SourceError('NONGSARO_API_KEY가 없습니다')
    f = Fetcher('nongsaro', key)
    try:
        return _collect(f, key, crops, log, refresh, max_per_crop)
    except SourceError as e:
        e.calls = f.calls
        raise


def _collect(f, key, crops, log, refresh, max_per_crop):
    rows, page = [], 1
    while True:
        cache = f'list_p{page}_n{LIST_ROWS}'
        body = f.get(f'{BASE}/sptTchnlgySportList', {'apiKey': key, 'pageNo': page, 'numOfRows': LIST_ROWS},
                     cache_name=cache, refresh=refresh)
        code, items = _parse(body)
        if code == '15':
            raise SourceError('농사로 결과코드 15 (도메인 불일치)')
        if code != '00':
            raise SourceError(f'농사로 목록 결과코드 {code or "없음"}')
        f.save(cache, body)
        rows += items
        if len(items) < LIST_ROWS:
            break
        page += 1

    wanted = set(crops)
    by_crop, seen = {}, set()
    for r in rows:
        crop = r.get('prdlstCodeNm', '').strip()
        if r.get('cntntsNo') in seen:  # 목록에 같은 글이 두 번 오는 경우가 있다
            continue
        seen.add(r.get('cntntsNo'))
        if crop in wanted:
            by_crop.setdefault(crop, []).append(r)
    docs, done, errors = [], [], 0
    for crop in crops:
        crop_docs, crop_errors = [], 0
        latest = sorted(by_crop.get(crop, []), key=lambda r: r.get('regDt', ''), reverse=True)[:max_per_crop]
        for r in latest:
            no = r['cntntsNo']
            cache = f'view_{no}'
            try:
                body = f.get(f'{BASE}/sptTchnlgySportView', {'apiKey': key, 'cntntsNo': no},
                             cache_name=cache, refresh=refresh)
            except SourceError as e:
                crop_errors += 1
                log(f'  농사로 {no}: {e}')
                continue
            code, items = _parse(body)
            if code != '00' or not items:
                crop_errors += 1
                log(f'  농사로 {no}: 결과코드 {code or "없음"}')
                continue
            f.save(cache, body)
            item = items[0]
            rec = to_record(item)
            writer = item.get('wrterNm', '').strip()
            text = rec['text'].replace(writer, '') if writer else rec['text']  # 본문 속 작성자 실명도 지운다
            text, changes = mask_text(text)
            if changes:
                text += f'\n\n{NOTICE}'
            if len(text) < 50:
                continue
            crop_docs.append({
                'doc_id': f'fieldtech_{no}', 'source_type': 'fieldtech', 'source_label': SOURCE_LABEL,
                'title': rec['title'] or f'{crop} 현장기술지원', 'crop_names': [crop], 'pest_name': '',
                'url': '', 'license': LICENSE, 'text': text,
            })
        errors += crop_errors
        if crop_errors:
            log(f'농사로 {crop}: 오류 {crop_errors}건, 이번에는 반영하지 않음 (누적 호출 {f.calls})')
            continue
        docs += crop_docs
        done.append(crop)
        if latest:
            log(f'농사로 {crop}: 문서 {len(crop_docs)}건 (누적 호출 {f.calls})')
    return CollectResult(docs, f.calls, done, errors)
