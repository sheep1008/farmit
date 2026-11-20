"""시군구 중심 좌표 (회원 위치 ~ 시장 거리 계산용).

fixtures/sigungu_coords.json 을 읽는다 (만드는 법은 fixtures/build_sigungu_coords.py).
회원가입·내 정보 수정이 user_profile.lat·lng를 채울 때 쓴다.
"""
import json
from functools import lru_cache
from pathlib import Path

COORDS_FILE = Path(__file__).parent / 'fixtures' / 'sigungu_coords.json'


@lru_cache(maxsize=1)
def _coords():
    return json.loads(COORDS_FILE.read_text(encoding='utf-8'))


def sigungu_coords(sido, sigungu):
    """(위도, 경도). 목록에 없는 시도·시군구면 (None, None) → 거리 없이 계산된다."""
    point = _coords().get(sido, {}).get(sigungu)
    return tuple(point) if point else (None, None)
