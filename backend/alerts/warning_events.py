"""기상특보 이벤트 → 특수 상황(special_event) + 회원 알림(alert) (REQ-ALT-001)

입력은 Flink가 weather.warning.event로 보낸 메시지 1건(새로 생기거나 바뀐 특보)이다.
알림 대상: 특보 구역(시도·시군구)에 주산지가 있는 품목을 관심 품목으로 담은 회원.
같은 메시지를 여러 번 받아도 결과가 같다 (special_event·alert의 UNIQUE 제약 + get_or_create).
"""
import logging
from datetime import datetime, timezone

from django.db import transaction

from accounts.models import UserInterestItem
from codes.models import ItemProducingArea, WarningZone

from .models import Alert, SpecialEvent

log = logging.getLogger(__name__)

# 알림을 만드는 특보 상태. 해제·연장·정정·변경해제·취소는 이력(weather_warning)에만 남긴다
ALERT_STATUSES = {'발표', '변경발표'}
SOURCE_URL = 'https://www.weather.go.kr'  # 출처 표시용 (REQ-NFR-007). 원본: 기상청 기상특보 조회서비스

# 주산지 데이터가 옛 시도 이름을 쓸 수도 있어 함께 찾는다
SIDO_ALIASES = {
    '강원특별자치도': ['강원특별자치도', '강원도'],
    '전북특별자치도': ['전북특별자치도', '전라북도'],
    '제주특별자치도': ['제주특별자치도', '제주도'],
}


def parse_utc(value):
    """메시지의 "2026-11-06T03:00:00"(UTC, 시간대 표시 없음) → aware datetime"""
    if not value:
        return None
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def target_user_ids(sido, sigungu):
    """이 지역에 주산지가 있는 품목을 관심 품목으로 담은 회원 id. sigungu가 없으면 시도 전체"""
    areas = ItemProducingArea.objects.filter(sido__in=SIDO_ALIASES.get(sido, [sido]))
    if sigungu:
        areas = areas.filter(sigungu=sigungu)
    return set(
        UserInterestItem.objects.filter(item_id__in=areas.values('item_id'))
        .values_list('user_id', flat=True)
    )


def handle_warning_event(msg):
    """메시지 1건을 처리하고 (결과, 알림 대상 회원 수)를 돌려준다. 결과는 로그용 짧은 설명."""
    status = msg['status']
    if status not in ALERT_STATUSES:
        return f'건너뜀: 상태 {status}', 0

    zone = WarningZone.objects.filter(region_code=msg['region_code']).first()
    if zone is None:
        # 엑셀이 갱신되어 새 구역이 생긴 경우. codes/fixtures/build_warning_zone.py로 다시 만든다
        log.warning('모르는 특보구역 %s(%s): warning_zone 갱신 필요', msg['region_code'], msg['region_name'])
        return f"건너뜀: 모르는 구역 {msg['region_code']}", 0
    if not zone.sido:
        return '건너뜀: 해상 구역', 0

    with transaction.atomic():
        event, _ = SpecialEvent.objects.get_or_create(
            event_type=SpecialEvent.EventType.WARNING,
            source_ref=f"{msg['source_key']}:{status}",
            defaults={
                'sido': zone.sido,
                'sigungu': zone.sigungu,
                'occurred_at': parse_utc(msg['announced_at']),
                'title': f"{msg['region_name']} {msg['warning_type']}{msg['level']} {status}",
                'detail': {
                    'source_key': msg['source_key'],
                    'region_code': msg['region_code'],
                    'region_name': msg['region_name'],
                    'warning_type': msg['warning_type'],
                    'level': msg['level'],
                    'status': status,
                    'announced_at': msg['announced_at'],
                    'effective_at': msg.get('effective_at'),  # 발효 시각 (UTC)
                },
                'source_url': SOURCE_URL,
            },
        )
        user_ids = target_user_ids(zone.sido, zone.sigungu)
        # 이미 만든 알림은 UNIQUE(user, special_event)에 걸려 건너뛴다
        Alert.objects.bulk_create(
            [Alert(user_id=uid, special_event=event) for uid in user_ids], ignore_conflicts=True,
        )
    return f'알림: {event.title}', len(user_ids)
