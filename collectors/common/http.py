"""지수 백오프 재시도가 있는 GET과, 로그에 API 키가 찍히지 않게 가리는 함수."""
import re
import time
import urllib.error
import urllib.parse
import urllib.request

# 일시적인 오류라 다시 해 볼 만한 HTTP 상태. 4xx(키 오류·잘못된 요청)는 다시 해도 같으므로 바로 실패한다
RETRY_STATUS = {429, 500, 502, 503, 504}
_KEY_RE = re.compile(r"(?i)\b(serviceKey|apiKey|authKey)=[^&\s'\"]+")


class HttpError(Exception):
    """재시도 끝에도 실패. 메시지에는 키가 없다."""


def mask(text):
    """문자열 안의 serviceKey=..., apiKey=... 값을 ***로 바꾼다."""
    return _KEY_RE.sub(r"\1=***", str(text))


def get(url, params, key=None, retries=3, backoff=1.0, timeout=30, on_call=None, encoding="utf-8"):
    """GET 해서 본문 문자열을 돌려준다. JSON·XML 해석은 부르는 쪽이 한다.

    key=(파라미터 이름, 값)은 urlencode를 거치지 않고 붙인다. data.go.kr의 Encoding 키(%가 들어 있음)가
    두 번 인코딩되지 않게 하려는 것으로, collectors/auction·explore와 같은 방식이다.
    실패하면 backoff, 2×backoff, 4×backoff초 … 쉬고 다시 한다 (지수 백오프).
    on_call은 실제 요청을 보내기 직전마다 불린다 (호출 수 세기·한도 확인용, 재시도도 1건으로 센다).
    encoding: 응답 본문 인코딩. 기상청 API허브는 euc-kr이다.
    """
    query = urllib.parse.urlencode(params)
    full = f"{url}?{key[0]}={key[1]}&{query}" if key else f"{url}?{query}"
    for attempt in range(retries):
        if on_call:
            on_call()
        try:
            with urllib.request.urlopen(full, timeout=timeout) as resp:
                return resp.read().decode(encoding)
        except urllib.error.HTTPError as e:
            if e.code not in RETRY_STATUS or attempt == retries - 1:
                # from None: 원래 예외(URL 전체를 들고 있다)를 연결하지 않아 트레이스백에도 키가 남지 않는다
                raise HttpError(f"HTTP {e.code} ({attempt + 1}번 시도) {mask(url)}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == retries - 1:
                reason = getattr(e, "reason", e)
                raise HttpError(f"접속 실패 {type(reason).__name__} ({attempt + 1}번 시도) {mask(url)}") from None
        time.sleep(backoff * 2 ** attempt)
