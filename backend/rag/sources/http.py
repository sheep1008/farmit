"""공공 API 호출 공통: 재시도, 호출 간격, 키 가리기, 응답 캐시.

NCPMS·농사로 API는 http라서 URL에 키가 평문으로 들어간다. URL·예외 원문은 출력하지 않고, 저장하는 응답에서도 키를 지운다.
응답은 settings.RAG_DATA_DIR/raw/{source}/{name}.json 에 캐시한다 (git 제외). 다시 실행하면 캐시를 쓴다.
"""
import http.client
import json
import time
from dataclasses import dataclass, field
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

CALL_INTERVAL = 0.5     # 초. 한도가 공개되지 않은 API라 천천히 부른다
RETRY_STATUS = {429, 500, 502, 503, 504}


class SourceError(Exception):
    """재시도 끝에도 실패. 메시지에 키·URL이 없다. calls: 실패 전까지 한 외부 호출 수"""
    calls = 0


@dataclass
class CollectResult:
    docs: list
    calls: int                                   # 실제 외부 호출 수
    done_crops: list = field(default_factory=list)  # 오류 없이 끝낸 작물 (이 작물의 문서만 바꾼다)
    errors: int = 0


class Fetcher:
    def __init__(self, source, key, interval=CALL_INTERVAL):
        self.source, self.key, self.interval = source, key, interval
        self.calls = 0          # 실제 외부 호출 수 (캐시 사용은 세지 않는다, REQ-NFR-009)
        self._last = 0.0

    def cache_path(self, name):
        return settings.RAG_DATA_DIR / 'raw' / self.source / f'{name}.json'

    def get(self, url, params, cache_name=None, refresh=False, retries=3):
        """GET 본문 문자열 (키는 ***로 가림). cache_name이 있으면 캐시 우선."""
        path = self.cache_path(cache_name) if cache_name else None
        if path and path.exists() and not refresh:
            return json.loads(path.read_text(encoding='utf-8'))['body']
        query = urllib.parse.urlencode(params)
        for attempt in range(retries):
            wait = self.interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.calls += 1
            try:
                with urllib.request.urlopen(f'{url}?{query}', timeout=30) as resp:
                    body = self.mask(resp.read().decode('utf-8', errors='replace'))
                break
            except urllib.error.HTTPError as e:
                if e.code not in RETRY_STATUS or attempt == retries - 1:
                    raise SourceError(f'{self.source} HTTP {e.code}') from None
            except (urllib.error.URLError, TimeoutError, http.client.HTTPException, ConnectionError) as e:
                if attempt == retries - 1:
                    raise SourceError(f'{self.source} 접속 실패 {type(e).__name__}') from None
            time.sleep(2 ** attempt)
        return body

    def mask(self, text):
        """응답에 키가 그대로 또는 URL 인코딩된 꼴로 들어 있으면 ***로 바꾼다."""
        for k in {self.key, urllib.parse.quote(self.key, safe=''), urllib.parse.quote_plus(self.key)}:
            if k:
                text = text.replace(k, '***')
        return text

    def save(self, cache_name, body):
        """정상 응답만 캐시한다 (오류 응답을 캐시하면 다시 받지 못한다)."""
        path = self.cache_path(cache_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'body': body}, ensure_ascii=False), encoding='utf-8')
