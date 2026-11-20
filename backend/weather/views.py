"""날씨 API (docs/api.md 2.9)."""
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated

from api.responses import error, ok
from codes.regions import sigungu_coords

from .current import current_weather


@api_view(['GET'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def current(request):
    """내 위치(시군 중심)의 현재 날씨 (REQ-HOM-002)."""
    profile = getattr(request.user, 'userprofile', None)
    if profile is None:
        return error(404, 'NOT_FOUND', '내 위치가 없습니다. 내 정보에서 위치를 넣어 주세요.')
    lat, lng = profile.lat, profile.lng
    if lat is None or lng is None:
        lat, lng = sigungu_coords(profile.sido, profile.sigungu)
    if lat is None or lng is None:
        return error(404, 'NOT_FOUND', '내 위치의 좌표를 찾지 못했습니다.')
    data = current_weather(lat, lng)
    if data is None:
        # 홈의 덤 정보라 공통 오류 토스트를 띄우지 않는 DATA_NOT_READY로 답한다 (api.md 1.5절)
        return error(503, 'DATA_NOT_READY', '날씨 정보를 아직 불러오지 못했습니다.')
    return ok({'location': f'{profile.sido} {profile.sigungu}', **data})
