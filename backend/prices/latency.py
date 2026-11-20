"""당일 경매가 지연 계산 (REQ-NFR-003: aT API 반영 후 5분 이내 화면 반영). DB·Kafka를 쓰지 않는 순수 함수.

지연 구간 (aT API에 낙찰이 반영된 순간부터)
  ① 수집 대기: 프로듀서가 다음 바퀴에 그 건을 가져갈 때까지      최대 = 수집 주기
  ② 수집 소요: 한 바퀴(시장 전부·페이지)를 도는 시간             collect_log finished_at - started_at
  ③ 파이프라인: Kafka → Flink 집계 → MySQL realtime_price        탐침(probe)으로 직접 잰다
  ④ 화면 대기: 프론트가 API를 다시 부를 때까지                   최대 = 화면 갱신 주기
  ⑤ API 응답: DB 한 번 조회 (수십 ms, 무시)
최악 = ① + ② + ③ + ④. aT 자체 반영 지연(낙찰 → API, 약 20분)은 요구사항에서 제외한다.
"""
import math

LIMIT_SECONDS = 300  # REQ-NFR-003


def percentile(values, p):
    """p(0~100) 백분위수. 가장 가까운 순위 방식. 값이 없으면 None."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[rank - 1]


def gaps(times):
    """시각 목록 → 이웃한 시각 사이 간격(초) 목록. 수집 주기를 실제 실행 기록으로 확인한다."""
    ordered = sorted(times)
    return [(b - a).total_seconds() for a, b in zip(ordered, ordered[1:])]


def summary(values):
    """초 단위 값 목록 → {count, p50, p90, max}. 비어 있으면 count 0, 나머지 None."""
    return {
        'count': len(values),
        'p50': percentile(values, 50),
        'p90': percentile(values, 90),
        'max': max(values) if values else None,
    }


def worst_case(poll_seconds, collect_seconds, pipeline_seconds, screen_seconds):
    """구간별 최악값을 더한 최악 지연(초)과 한도 안인지."""
    parts = {
        '① 수집 대기 (수집 주기)': poll_seconds,
        '② 수집 소요': collect_seconds,
        '③ 파이프라인 (Kafka→Flink→MySQL)': pipeline_seconds,
        '④ 화면 대기 (화면 갱신 주기)': screen_seconds,
    }
    total = sum(parts.values())
    return parts, total, total <= LIMIT_SECONDS
