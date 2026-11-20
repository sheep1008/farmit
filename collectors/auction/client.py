"""aT 실시간 경매 API(katRealTime2/trades2) 호출. 인증키는 로그·예외 메시지에 남기지 않는다."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

URL = "https://apis.data.go.kr/B552845/katRealTime2/trades2"
PAGE_SIZE = 1000  # API가 한 번에 주는 최대 행 수 (3000을 요청해도 1000)


class ApiError(Exception):
    pass


class AuctionClient:
    def __init__(self, service_key, retries=3, timeout=30):
        # 포털의 Encoding 키(%가 들어 있음)는 그대로, Decoding 키는 URL 인코딩해서 붙인다
        self._key = service_key if "%" in service_key else urllib.parse.quote(service_key, safe="")
        self.retries = retries
        self.timeout = timeout
        self.calls = 0  # 실제로 보낸 요청 수 (재시도 포함, 일일 한도 계산용)

    def fetch(self, date, market_id, page):
        """한 시장·한 날짜의 page번째 1000건 (낙찰 일시 최신순)."""
        query = urllib.parse.urlencode({
            "returnType": "json",
            "pageNo": page,
            "numOfRows": PAGE_SIZE,
            "cond[trd_clcln_ymd::EQ]": date,
            "cond[whsl_mrkt_cd::EQ]": market_id,
        })
        url = f"{URL}?serviceKey={self._key}&{query}"
        last = None
        for attempt in range(1, self.retries + 1):
            self.calls += 1
            try:
                with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                    body = json.loads(resp.read().decode("utf-8"))["response"]
                code = body["header"]["resultCode"]
                if code != "0":
                    raise ApiError(f"resultCode={code} {body['header'].get('resultMsg')}")
                return (body["body"].get("items") or {}).get("item") or []
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError, ApiError) as e:
                # URL에는 키가 들어 있으므로 예외 종류와 짧은 사유만 남긴다
                last = f"{type(e).__name__}: {getattr(e, 'code', '') or str(e)[:100]}"
                if attempt < self.retries:
                    time.sleep(2 ** attempt)
        raise ApiError(f"market={market_id} page={page} 실패 ({self.retries}회): {last}")
