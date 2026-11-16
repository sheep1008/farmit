"""품목 요약용 자료 건수 (REQ-RAG-006): 색인용 문서 파일(data/rag/docs)에서 작물별 병해충·현장기술지원 수를 센다.

ES 없이 파일만 읽는다. 파일이 바뀌면(수정 시각) 다시 센다.
"""
import json

from django.conf import settings

_cache = {'key': None, 'counts': {}}
FILES = {'ncpms.jsonl': 'pests', 'fieldtech.jsonl': 'fieldtech'}


def counts():
    """{작물 이름: {'pests': 병해충 수, 'fieldtech': 현장기술지원 건수}}"""
    base = settings.RAG_DATA_DIR / 'docs'
    paths = [base / n for n in FILES if (base / n).exists()]
    key = tuple((p.name, p.stat().st_mtime_ns) for p in paths)
    if key != _cache['key']:
        out = {}
        for p in paths:
            kind = FILES[p.name]
            seen = set()
            with p.open(encoding='utf-8') as fh:
                for line in fh:
                    try:
                        d = json.loads(line)
                        if not isinstance(d, dict) or not isinstance(d.get('crop_names') or [], list):
                            continue
                        ident_name = d.get('pest_name') or d['doc_id']
                    except (ValueError, KeyError, TypeError):
                        continue            # 깨진 줄은 건너뛴다
                    for crop in d.get('crop_names') or []:
                        ident = (crop, ident_name)
                        if ident not in seen:
                            seen.add(ident)
                            out.setdefault(crop, {'pests': 0, 'fieldtech': 0})[kind] += 1
        _cache.update(key=key, counts=out)
    return _cache['counts']


def for_crop(crop):
    return counts().get(crop, {'pests': 0, 'fieldtech': 0})
