from rest_framework.authentication import SessionAuthentication


class CsrfOnlyAuthentication(SessionAuthentication):
    """로그인 여부와 상관없이 CSRF 토큰만 검사한다.

    DRF의 SessionAuthentication은 비로그인 요청의 CSRF를 검사하지 않는다.
    가입·로그인·로그아웃은 비로그인 상태에서도 부르므로 이 클래스로 검사를 강제한다 (docs/api.md 1.4절).
    회원을 식별하지는 않는다 (authenticate는 항상 None).
    """

    def authenticate(self, request):
        self.enforce_csrf(request)
        return None
