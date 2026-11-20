"""내 위치의 현재 날씨 (REQ-HOM-002). 기상청 초단기실황·초단기예보 (data.go.kr, 격자 nx·ny로 호출).

- 실황(getUltraSrtNcst): 기온·습도·1시간 강수량·풍속·강수 형태. 매시 정각 값이 약 10분 뒤 올라온다
- 예보(getUltraSrtFcst): 실황에는 하늘 상태(맑음·흐림)가 없어 가장 가까운 시각의 예보 값을 쓴다. 실패하면 하늘 상태만 뺀다
- 같은 격자는 10분 동안 캐시한다 (data.go.kr 하루 호출 한도 보호). DB에는 저장하지 않는다
"""
import logging
import math
import urllib.parse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

BASE_URL = 'https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/'
KST = ZoneInfo('Asia/Seoul')
CACHE_SECONDS = 600
FAIL_CACHE_SECONDS = 60      # 조회에 실패한 격자는 이 시간 동안 다시 부르지 않는다
TIMEOUT_SECONDS = 5
PRECIP = {'1': '비', '2': '비/눈', '3': '눈', '5': '빗방울', '6': '빗방울·눈날림', '7': '눈날림'}  # PTY. 0 = 없음
SKY = {'1': '맑음', '3': '구름 많음', '4': '흐림'}


def to_grid(lat, lng):
    """위도·경도 → 기상청 동네예보 격자 (nx, ny). 기상청 가이드의 람베르트 정각원추도법 식 그대로."""
    re, grid, slat1, slat2, olon, olat, xo, yo = 6371.00877 / 5.0, 5.0, 30.0, 60.0, 126.0, 38.0, 43, 136
    rad = math.pi / 180
    sn = math.log(math.cos(slat1 * rad) / math.cos(slat2 * rad)) / math.log(
        math.tan(math.pi / 4 + slat2 * rad / 2) / math.tan(math.pi / 4 + slat1 * rad / 2))
    sf = math.tan(math.pi / 4 + slat1 * rad / 2) ** sn * math.cos(slat1 * rad) / sn
    ro = re * sf / math.tan(math.pi / 4 + olat * rad / 2) ** sn
    ra = re * sf / math.tan(math.pi / 4 + float(lat) * rad / 2) ** sn
    theta = float(lng) * rad - olon * rad
    if theta > math.pi:
        theta -= 2 * math.pi
    if theta < -math.pi:
        theta += 2 * math.pi
    theta *= sn
    return int(ra * math.sin(theta) + xo + 0.5), int(ro - ra * math.cos(theta) + yo + 0.5)


def _call(service, base, nx, ny):
    """행 목록. 실패하면 None. 키는 주소에만 붙이고 로그에는 예외 종류만 남긴다."""
    key = settings.DATA_GO_KR_KEY
    key = key if '%' in key else urllib.parse.quote(key, safe='')  # Decoding 키면 인코딩 (collectors/common/datagokr.py와 같음)
    query = urllib.parse.urlencode({'dataType': 'JSON', 'numOfRows': 100, 'pageNo': 1, 'nx': nx, 'ny': ny,
                                    'base_date': base.strftime('%Y%m%d'), 'base_time': base.strftime('%H%M')})
    try:
        res = httpx.get(f'{BASE_URL}{service}?serviceKey={key}&{query}', timeout=TIMEOUT_SECONDS)
        res.raise_for_status()
        body = res.json()['response']
        if str(body['header']['resultCode']) != '00':
            logger.warning('기상청 %s 결과 코드 %s', service, body['header']['resultCode'])
            return None
        return body['body']['items']['item']
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as e:
        logger.warning('기상청 %s 실패: %s', service, type(e).__name__)
        return None


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fetch(nx, ny, now):
    # 실황: 정각 값이 10분쯤 뒤 올라오므로 15분 전 시각의 정각을 묻는다
    base = (now - timedelta(minutes=15)).replace(minute=0, second=0, microsecond=0)
    rows = _call('getUltraSrtNcst', base, nx, ny)
    if not rows:
        return None
    obs = {r['category']: r['obsrValue'] for r in rows}
    # 예보: 매시 30분 발표, 45분쯤 올라온다. 가장 이른 예보 시각의 하늘 상태만 쓴다
    fbase = (now - timedelta(minutes=45)).replace(minute=30, second=0, microsecond=0)
    sky_rows = [r for r in (_call('getUltraSrtFcst', fbase, nx, ny) or []) if r['category'] == 'SKY']
    sky = SKY.get(min(sky_rows, key=lambda r: (r['fcstDate'], r['fcstTime']))['fcstValue']) if sky_rows else None
    precip = PRECIP.get(str(obs.get('PTY')))
    return {'summary': precip or sky, 'sky': sky, 'precip_type': precip,
            'temp_c': _number(obs.get('T1H')), 'humidity_pct': _number(obs.get('REH')),
            'rain_mm_1h': _number(obs.get('RN1')), 'wind_ms': _number(obs.get('WSD')),
            'observed_at': base.isoformat()}


def current_weather(lat, lng, now=None):
    """현재 날씨 dict 또는 None(키 없음·조회 실패)."""
    if not settings.DATA_GO_KR_KEY:
        return None
    nx, ny = to_grid(lat, lng)
    key = f'weather:current:{nx}:{ny}'
    hit = cache.get(key)
    if hit is not None:
        return hit or None  # False = 방금 실패한 격자
    data = _fetch(nx, ny, now or datetime.now(KST))
    cache.set(key, data or False, CACHE_SECONDS if data else FAIL_CACHE_SECONDS)
    return data
