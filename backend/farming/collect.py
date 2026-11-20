"""농사로 농작업일정(farmWorkingPlanNew) 수집 → farm_schedule (REQ-COL-006).

흐름: 대분류별 일정 목록(workScheduleLst) → 품목 이름과 맞는 일정 찾기 → 품목마다 대표 일정 하나의 시기정보
(workScheduleEraInfoJsonLst)를 받아 그 품목의 행을 통째로 바꾼다. 응답은 rag/sources/http.Fetcher가 캐시한다.
키는 NONGSARO_WORKPLAN_KEY. 결과코드 15(도메인 불일치)는 바로 멈춘다.
"""
import os
import re
import xml.etree.ElementTree as ET

from django.db import transaction

from codes.models import Item
from farming.models import FarmSchedule
from rag import crops
from rag.sources.http import Fetcher, SourceError

BASE = 'http://api.nongsaro.go.kr/service/farmWorkingPlanNew'
# 농사로 대분류 코드 (품목 코드가 아니라 농사로 목록의 구분). 축산·사료작물은 품목이 아니라 뺀다
GROUPS = {'210001': '채소', '210002': '과수', '210003': '화훼', '210004': '논농사', '210005': '밭농사',
          '210008': '버섯', '210009': '약초'}
REP_KEYWORDS = [('보통', 0), ('노지', 1), ('반촉성', 3), ('촉성', 2)]   # '반촉성'에 '촉성'이 들어 있어 순서가 의미 있다


def _parse(body):
    """(결과코드, item dict 목록)"""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return '', []
    code = (root.findtext('.//resultCode') or '').strip()
    return code, [{c.tag: (c.text or '').strip() for c in it} for it in root.iter('item')]


def name_keys(name):
    base = re.sub(r'\(.*?\)', '', name).strip()
    keys = {name, base} | {p.strip() for p in re.split(r'[,，]', base)}
    return {k for k in keys if k}


def rep_rank(crop, schedule):
    n = schedule['name']
    order = next((rank for kw, rank in REP_KEYWORDS if kw in n), len(REP_KEYWORDS))
    return (n != crop, order, int(schedule['id']))


def pick_schedule(crop, schedules):
    """작물 이름과 맞는 일정 중 대표 하나 (이름이 정확히 같음 > 보통 > 노지 > 촉성 > 반촉성 > 그 외). 없으면 None."""
    found = [s for s in schedules if crop in name_keys(s['name'])]
    return min(found, key=lambda s: rep_rank(crop, s)) if found else None


def to_rows(era_items):
    """시기정보 item → FarmSchedule 필드 dict. 월·순이 빠진 행은 버린다."""
    rows = []
    for e in era_items:
        try:
            b, f = int(e['beginMon']), int(e['endMon'])
        except (KeyError, ValueError):
            continue
        if not (1 <= b <= 12 and 1 <= f <= 12 and e.get('beginEra') in ('상', '중', '하')
                and e.get('endEra') in ('상', '중', '하') and e.get('opertNm')):
            continue
        task = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', e['opertNm'])).strip()    # 원문의 <br/> 같은 태그를 지운다
        rows.append({'task_name': task[:100], 'stage': e.get('infoSeCodeNm', '')[:50],
                     'start_month': b, 'start_period': e['beginEra'], 'end_month': f, 'end_period': e['endEra']})
    return rows


def collect(log=print, refresh=False):
    """수집 실행. 반환: {'items': 일정이 연결된 품목 수, 'rows': 저장한 행 수, 'calls': 외부 호출 수, 'skipped': [품목]}"""
    key = os.environ.get('NONGSARO_WORKPLAN_KEY', '').strip()
    if not key:
        raise SourceError('NONGSARO_WORKPLAN_KEY가 없습니다')
    f = Fetcher('workplan', key)
    schedules = []
    for code in GROUPS:
        body = f.get(f'{BASE}/workScheduleLst', {'apiKey': key, 'kidofcomdtySeCode': code},
                     cache_name=f'list_{code}', refresh=refresh)
        result, items = _parse(body)
        if result == '15':
            raise SourceError('농사로 결과코드 15 (도메인 불일치)')
        if result != '00':
            raise SourceError(f'농사로 일정 목록 결과코드 {result or "없음"}')
        f.save(f'list_{code}', body)
        schedules += [{'id': i['cntntsNo'], 'name': i['sj']} for i in items if i.get('cntntsNo') and i.get('sj')]

    saved_items = saved_rows = 0
    skipped, era_cache = [], {}
    for item in Item.objects.order_by('item_id'):
        crop = crops.crop_name(item.name)
        sched = pick_schedule(crop, schedules) if crop else None
        if sched is None:
            skipped.append(item.name)
            continue
        sid = sched['id']
        if sid not in era_cache:
            body = f.get(f'{BASE}/workScheduleEraInfoJsonLst', {'apiKey': key, 'cntntsNo': sid},
                         cache_name=f'era_{sid}', refresh=refresh)
            result, items = _parse(body)
            if result == '15':
                raise SourceError('농사로 결과코드 15 (도메인 불일치)')
            if result != '00':
                log(f'  일정 {sid} 결과코드 {result or "없음"} — 건너뜀')
                era_cache[sid] = None
                skipped.append(item.name)
                continue
            f.save(f'era_{sid}', body)
            era_cache[sid] = to_rows(items)
        rows = era_cache[sid]
        if not rows:        # 앞에서 이미 실패한 일정이면 이 품목도 건너뜀
            skipped.append(item.name)
            continue
        with transaction.atomic():      # 한 품목의 행은 통째로 바꾼다 (중간에 끊겨도 반쪽이 남지 않게)
            FarmSchedule.objects.filter(item=item).delete()
            FarmSchedule.objects.bulk_create([FarmSchedule(item=item, **r) for r in rows])
        saved_items += 1
        saved_rows += len(rows)
    return {'items': saved_items, 'rows': saved_rows, 'calls': f.calls, 'skipped': skipped}
