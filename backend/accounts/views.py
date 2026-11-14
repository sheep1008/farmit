from django.contrib.auth import authenticate, get_user_model, login, logout
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated

from api.responses import error, ok

from .authentication import CsrfOnlyAuthentication
from .serializers import ProfileUpdateSerializer, SignupSerializer, me_data, user_data
from .validators import is_valid_username

User = get_user_model()

# 로그인 연속 실패 5회 → 10분 잠금 (docs/api.md 2.1). 실패 횟수는 Django 캐시에 둔다.
MAX_LOGIN_FAILS = 5
LOCK_SECONDS = 600


@api_view(['GET'])
@authentication_classes([])
@permission_classes([])
@ensure_csrf_cookie
def csrf(request):
    """CSRF 쿠키 발급. 프론트가 앱을 처음 열 때 한 번 부른다."""
    return HttpResponse(status=204)


@api_view(['GET'])
@authentication_classes([])
@permission_classes([])
def check_username(request):
    """아이디 중복 확인. 사용 중이어도 오류가 아니라 available=false로 답한다."""
    username = request.query_params.get('username', '')
    if not is_valid_username(username):
        return error(400, 'VALIDATION_ERROR', '입력값을 확인해 주세요.',
                     {'username': ['영문 소문자·숫자 4~20자로 입력해 주세요.']})
    available = not User.objects.filter(username=username).exists()
    return ok({'username': username, 'available': available})


@api_view(['POST'])
@authentication_classes([CsrfOnlyAuthentication])
@permission_classes([])
def signup(request):
    """회원가입. 성공하면 바로 로그인 상태가 된다."""
    serializer = SignupSerializer(data=request.data)
    if not serializer.is_valid():
        return error(400, 'VALIDATION_ERROR', '입력값을 확인해 주세요.', serializer.errors)
    if User.objects.filter(username=serializer.validated_data['username']).exists():
        return error(409, 'DUPLICATE_USERNAME', '이미 사용 중인 아이디입니다.')
    try:
        user = serializer.save()
    except IntegrityError:
        # 위 확인과 저장 사이에 같은 아이디가 먼저 들어간 경우 (DB 유일 제약이 막아 준다)
        return error(409, 'DUPLICATE_USERNAME', '이미 사용 중인 아이디입니다.')
    login(request, user)
    return ok(user_data(user), status=201)


@api_view(['POST'])
@authentication_classes([CsrfOnlyAuthentication])
@permission_classes([])
def login_view(request):
    """로그인. 같은 아이디로 5회 연속 실패하면 10분간 잠근다."""
    username = str(request.data.get('username', ''))
    password = str(request.data.get('password', ''))
    fail_key = f'login_fail:{username}'

    # 잠금 확인이 먼저다. 잠긴 아이디는 비밀번호가 맞아도 막는다.
    if cache.get(fail_key, 0) >= MAX_LOGIN_FAILS:
        return error(429, 'TOO_MANY_LOGIN_ATTEMPTS', '로그인 시도가 너무 많습니다. 10분 후 다시 시도해 주세요.',
                     {'retry_after_seconds': LOCK_SECONDS})

    user = authenticate(request, username=username, password=password)
    if user is None:
        # 없는 아이디도 똑같이 센다 (가입된 아이디를 알아내지 못하게)
        cache.set(fail_key, cache.get(fail_key, 0) + 1, LOCK_SECONDS)
        return error(401, 'INVALID_CREDENTIALS', '아이디 또는 비밀번호가 맞지 않습니다.')
    cache.delete(fail_key)
    login(request, user)
    return ok(me_data(user))


@api_view(['POST'])
@authentication_classes([CsrfOnlyAuthentication])
@permission_classes([])
def logout_view(request):
    """로그아웃. 이미 로그아웃 상태여도 204 (결과가 같으므로 오류로 보지 않는다)."""
    logout(request)
    return HttpResponse(status=204)


@api_view(['GET', 'PATCH', 'DELETE'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def me(request):
    """내 정보 조회(GET)·수정(PATCH)·회원 탈퇴(DELETE). 로그인 필요."""
    if request.method == 'GET':
        return ok(me_data(request.user))
    if request.method == 'PATCH':
        return update_me(request)
    return delete_me(request)


def update_me(request):
    serializer = ProfileUpdateSerializer(request.user, data=request.data)
    if not serializer.is_valid():
        return error(400, 'VALIDATION_ERROR', '입력값을 확인해 주세요.', serializer.errors)
    serializer.save()
    return ok(me_data(request.user))


def delete_me(request):
    user = request.user
    # 실수 방지를 위해 비밀번호를 다시 확인한다
    if not user.check_password(str(request.data.get('password', ''))):
        return error(401, 'INVALID_CREDENTIALS', '비밀번호가 맞지 않습니다.')
    # 프로필·관심 품목·알림은 CASCADE로 함께 삭제된다 (DB가 아니라 Django ORM이 처리하므로 ORM으로 지운다)
    with transaction.atomic():
        logout(request)
        user.delete()
    return HttpResponse(status=204)
