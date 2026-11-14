from .checklists import checklist_for


def iso(dt):
    return dt.isoformat().replace('+00:00', 'Z') if dt else None


def alert_item(alert):
    """목록용 한 줄"""
    e = alert.special_event
    return {
        'id': alert.id,
        'event_type': e.event_type,
        'title': e.title,
        'sido': e.sido,
        'sigungu': e.sigungu,
        'occurred_at': iso(e.occurred_at),
        'created_at': iso(alert.created_at),
        'read_at': iso(alert.read_at),
        'is_read': alert.read_at is not None,
    }


def alert_detail(alert):
    """상세: 목록 항목 + 상황 상세 + 체크리스트 + 출처"""
    e = alert.special_event
    data = alert_item(alert)
    data.update({
        'item_id': e.item_id,
        'detail': e.detail,
        'source_url': e.source_url,
        'checklist': checklist_for(e),
    })
    return data
