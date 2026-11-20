"""내 위치(시군구 중심) → 시장 거리·통행료 (REQ-REC-002).

카카오모빌리티 자동차 길찾기로 도로 거리와 통행료를 받아 market_route에 저장해 두고 다시 쓴다.
길찾기를 쓸 수 없으면(키 없음·조회 실패) 직선거리로 계산한다. 판매 추천과 "지금 팔면"이 함께 쓴다.
"""
import logging
import math
from concurrent.futures import ThreadPoolExecutor

import httpx
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from codes.regions import sigungu_coords

from .models import MarketRoute

logger = logging.getLogger(__name__)

EARTH_RADIUS_KM = 6371.0
KAKAO_URL = 'https://apis-navi.kakaomobility.com/v1/directions'
FETCH_WORKERS = 8               # 처음 조회하는 시군구는 시장 수만큼 부르므로 나눠서 동시에 부른다
RETRY_AFTER_SECONDS = 600       # 조회에 실패한 시군구는 이 시간 동안 다시 부르지 않는다 (요청마다 기다리지 않게)


def has_coords(lat, lng):
    """새 시장 좌표가 0(미입력)이면 거리가 약 1만 km로 계산되므로 좌표 없음으로 본다."""
    return lat is not None and lng is not None and float(lat) != 0 and float(lng) != 0


def straight_km(lat1, lng1, lat2, lng2):
    """두 좌표 사이 직선거리 (km, haversine)."""
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp, dl = p2 - p1, math.radians(float(lng2) - float(lng1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _fetch(origin, market):
    """카카오 길찾기를 한 번 부른다. 반환: (거리 m, 통행료 원, 소요 시간 초) 또는 None(조회 실패).

    차종은 1종(2.5톤 미만 화물차 = 1톤 트럭), 하이패스 아님. 키는 헤더로만 보내 로그에 남지 않는다.
    """
    lat, lng = origin
    params = {'origin': f'{lng},{lat}', 'destination': f'{market.lng},{market.lat}',
              'car_type': 1, 'car_fuel': 'DIESEL', 'car_hipass': 'false', 'summary': 'true'}
    try:
        res = httpx.get(KAKAO_URL, params=params, headers={'Authorization': f'KakaoAK {settings.KAKAO_NAVI_KEY}'},
                        timeout=settings.KAKAO_NAVI_TIMEOUT_SECONDS)
        res.raise_for_status()
        route = res.json()['routes'][0]
        if route['result_code'] != 0:
            logger.warning('카카오 길찾기 경로 없음: 시장 %s, 결과 코드 %s', market.market_id, route['result_code'])
            return None
        summary = route['summary']
        return summary['distance'], summary['fare']['toll'], summary['duration']
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
        logger.warning('카카오 길찾기 실패: 시장 %s, %s', market.market_id, type(e).__name__)
        return None


def road_routes(sido, sigungu, markets):
    """{market_id: MarketRoute}. 저장된 경로가 없는 시장은 카카오에서 받아 저장한다.

    받지 못한 시장은 결과에 없다 → 호출한 쪽이 직선거리로 계산한다 (trip).
    """
    markets = [m for m in markets if has_coords(m.lat, m.lng)]
    found = {r.market_id: r for r in MarketRoute.objects.filter(sido=sido, sigungu=sigungu, market__in=markets)}
    missing = [m for m in markets if m.market_id not in found]
    origin = sigungu_coords(sido, sigungu)
    retry_key = f'market_route_retry:{sido}:{sigungu}'
    if not missing or not settings.KAKAO_NAVI_KEY or origin[0] is None or cache.get(retry_key):
        return found

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        fetched = list(pool.map(lambda m: _fetch(origin, m), missing))
    now = timezone.now()
    rows = [MarketRoute(sido=sido, sigungu=sigungu, market=m, distance_m=f[0], toll_won=f[1], duration_s=f[2],
                        fetched_at=now)
            for m, f in zip(missing, fetched) if f]
    # 같은 시군구를 두 요청이 동시에 처음 조회해도 중복 오류가 나지 않게 (UK가 막고, 뒤에 온 쪽은 건너뛴다)
    MarketRoute.objects.bulk_create(rows, ignore_conflicts=True)
    if len(rows) < len(missing):
        cache.set(retry_key, True, RETRY_AFTER_SECONDS)
    found.update({r.market_id: r for r in rows})
    return found


def trip(profile, market, routes):
    """(거리 km, 통행료 원, 종류). 도로 경로가 있으면 'road', 없으면 직선거리 'straight'(통행료 None)."""
    route = routes.get(market.market_id)
    if route:
        return route.distance_m / 1000, route.toll_won, 'road'
    return straight_km(profile.lat, profile.lng, market.lat, market.lng), None, 'straight'
