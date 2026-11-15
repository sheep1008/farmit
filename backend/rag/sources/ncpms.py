"""NCPMS(국가농작물병해충관리시스템) 병·해충 → RAG 문서.

흐름: 작물 이름으로 병 검색(SVC01)·해충 검색(SVC03) → 키마다 상세(SVC05 병, SVC07 해충) → 문서 1건.
- 검색 결과의 cropName이 찾은 작물 이름과 정확히 같은 것만 쓴다 ("사과"로 찾으면 다른 작물이 섞일 수 있어서)
- 응답은 JSON인데 Content-Type이 xml로 와서 본문을 바로 json.loads한다
- 약제 사용량 표현은 문서 텍스트를 만들 때 "[사용량: 등록 기준 확인]"으로 바꾼다 (REQ-CHT-005)
옛 rag_project의 ncpms_schema.py를 옮겨 왔다.
"""
import html
import json
import os
import re

from rag.dose_filter import NOTICE, mask_text
from rag.sources.http import CollectResult, Fetcher, SourceError

URL = 'http://ncpms.rda.go.kr/npmsAPI/service'
SOURCE_LABEL = '농촌진흥청 국가농작물병해충관리시스템(NCPMS)'
LICENSE = '농촌진흥청 저작물, 출처 표시 (비상업 이용)'
PAGE = 50   # displayCount 최대값

# (검색 서비스, 이름 필드, 키 필드, 상세 서비스, 상세 키 파라미터, 구분)
KINDS = [
    ('SVC01', 'sickNameKor', 'sickKey', 'SVC05', 'sickKey', '병'),
    ('SVC03', 'insectKorName', 'insectKey', 'SVC07', 'insectKey', '해충'),
]
# 공통 필드 → (병 필드, 해충 필드)
FIELD_MAP = {
    'symptom': ('symptoms', 'damageInfo'),
    'condition': ('developmentCondition', 'ecologyInfo'),
    'infection_route': ('infectionRoute', None),
    'prevention': ('preventionMethod', 'preventMethod'),
}
# 문서 텍스트 섹션: (공통 필드, 병 라벨, 해충 라벨)
SECTIONS = [
    ('symptom', '증상', '피해'),
    ('condition', '발생환경', '생태'),
    ('infection_route', '전염경로', None),
    ('prevention', '방제', '방제'),
]
_TAG_RE = re.compile(r'<[^>]+>')


def clean(value):
    """<br/> → 줄바꿈, 태그 제거, 엔티티 복원, 줄별 공백 정리."""
    if not isinstance(value, str):
        return ''
    s = re.sub(r'<br\s*/?>', '\n', value, flags=re.I)
    s = html.unescape(_TAG_RE.sub('', s))
    lines = (re.sub(r'\s+', ' ', line).strip() for line in s.replace('\r', '\n').split('\n'))
    return '\n'.join(line for line in lines if line)


def _service(body):
    try:
        svc = json.loads(body).get('service')
    except (json.JSONDecodeError, AttributeError):
        return None
    if not isinstance(svc, dict) or 'ERR_' in body[:500]:
        return None
    return svc


def to_doc(crop, kind, pest_key, pest_name, svc):
    """상세 응답 → 문서 레코드. 증상·환경·방제가 모두 비면 None (근거로 쓸 내용이 없다)."""
    idx = 0 if kind == '병' else 1
    fields = {}
    for common, names in FIELD_MAP.items():
        if names[idx]:
            value = clean(svc.get(names[idx]))
            if value:
                fields[common] = value
    if not any(fields.get(k) for k in ('symptom', 'condition', 'prevention')):
        return None
    lines = [f'작물: {crop}', f'구분: {kind}', f'병해충명: {pest_name}']
    masked_any = False
    for common, d_label, h_label in SECTIONS:
        label = d_label if kind == '병' else h_label
        if label and fields.get(common):
            masked, changes = mask_text(fields[common])
            masked_any = masked_any or bool(changes)
            lines += ['', f'[{label}]', masked]
    if masked_any:
        lines += ['', NOTICE]
    return {
        'doc_id': f'ncpms_{pest_key}_{crop}', 'source_type': 'ncpms_pest', 'source_label': SOURCE_LABEL,
        'title': f'{crop} {pest_name} ({kind})', 'crop_names': [crop], 'pest_name': pest_name,
        'url': '', 'license': LICENSE, 'text': '\n'.join(lines),
    }


def collect(crops, log=print, refresh=False, max_per_crop=None):
    """작물 이름 목록 → CollectResult. 캐시가 있으면 호출하지 않는다.

    오류 없이 끝낸 작물만 done_crops에 넣는다. 부르는 쪽은 그 작물의 문서만 바꾼다 (오류 난 작물의 기존 문서를 지키려고).
    """
    key = os.environ.get('NCPMS_API_KEY', '').strip()
    if not key:
        raise SourceError('NCPMS_API_KEY가 없습니다')
    f = Fetcher('ncpms', key)
    try:
        return _collect(f, key, crops, log, refresh, max_per_crop)
    except SourceError as e:
        e.calls = f.calls  # 실패 전까지 한 호출 수도 기록하게 (REQ-NFR-009)
        raise


def _collect(f, key, crops, log, refresh, max_per_crop):
    docs, errors, done = [], 0, []
    for crop in crops:
        n_crop, crop_errors = 0, 0
        for search_svc, name_field, key_field, detail_svc, detail_param, kind in KINDS:
            found, start, total = [], 1, None
            while total is None or start <= min(total, 500):
                cache = f'{search_svc}_{crop}_{start}'
                try:  # 검색이 실패해도 그 작물만 건너뛴다 (앞서 끝낸 작물의 문서는 살린다)
                    body = f.get(URL, {'apiKey': key, 'serviceCode': search_svc, 'serviceType': 'AA003',
                                       'cropName': crop, 'displayCount': PAGE, 'startPoint': start},
                                 cache_name=cache, refresh=refresh)
                except SourceError as e:
                    crop_errors += 1
                    log(f'  {crop} 검색: {e}')
                    break
                svc = _service(body)
                if svc is None:
                    crop_errors += 1
                    break
                f.save(cache, body)
                total = int(svc.get('totalCount') or 0)
                rows = svc.get('list') or []
                found += [r for r in rows if (r.get('cropName') or '').strip() == crop]
                if not rows:
                    break
                start += len(rows)
            for row in found:
                if max_per_crop and n_crop >= max_per_crop:
                    break
                pest_key, pest_name = row.get(key_field), (row.get(name_field) or '').strip()
                if not pest_key or not pest_name:
                    continue
                cache = f'{detail_svc}_{pest_key}'
                try:
                    body = f.get(URL, {'apiKey': key, 'serviceCode': detail_svc, 'serviceType': 'AA003',
                                       detail_param: pest_key}, cache_name=cache, refresh=refresh)
                except SourceError as e:
                    crop_errors += 1
                    log(f'  {crop} {pest_name}: {e}')
                    continue
                svc = _service(body)
                if svc is None:
                    crop_errors += 1
                    continue
                f.save(cache, body)
                doc = to_doc(crop, kind, pest_key, pest_name, svc)
                if doc:
                    docs.append(doc)
                    n_crop += 1
        errors += crop_errors
        if crop_errors:
            docs = [d for d in docs if d['crop_names'] != [crop]]  # 일부만 받은 작물은 기존 문서를 그대로 둔다
            log(f'NCPMS {crop}: 오류 {crop_errors}건, 이번에는 반영하지 않음 (누적 호출 {f.calls})')
        else:
            done.append(crop)
            log(f'NCPMS {crop}: 문서 {n_crop}건 (누적 호출 {f.calls})')
        if errors >= 10:
            log('NCPMS 오류가 10번 넘어 멈춘다')
            break
    return CollectResult(docs, f.calls, done, errors)
