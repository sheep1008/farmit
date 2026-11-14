"""data.go.kr 공통: 인증키 붙이는 형태와 응답(response.header/body.items.item) 해석 (docs/data-sources.md 1절).

ASOS·특일처럼 같은 모양으로 응답하는 API가 함께 쓴다.
"""
import json
import os
import urllib.parse

NO_DATA = "03"  # 조회 결과 없음. 오류가 아니라 0건으로 본다


class ApiError(Exception):
    """API가 정상 결과 코드가 아닌 응답을 돌려줬다. 메시지에는 키가 없다 (응답 본문에는 키가 들어 있지 않다)."""


def service_key():
    """환경 변수 DATA_GO_KR_KEY. 포털의 Encoding 키(%가 들어 있음)는 그대로, Decoding 키는 URL 인코딩한다.

    http.get(key=...)는 키를 다시 인코딩하지 않으므로 여기서 한 번만 맞춘다 (collectors/auction/client.py와 같음).
    """
    k = os.environ["DATA_GO_KR_KEY"].strip()
    return k if "%" in k else urllib.parse.quote(k, safe="")


def items(text, ok_code="00"):
    """응답 본문에서 행 목록(dict 리스트)을 꺼낸다.

    - 결과 코드가 ok_code면 행 목록, NO_DATA(03)면 빈 리스트, 그 밖은 ApiError.
    - 결과가 1건이면 item이 리스트가 아니라 객체로 오므로 리스트로 감싼다.
    - 키 오류 등은 JSON을 요청해도 XML로 오므로 JSON이 아니면 앞부분을 담아 ApiError.
    """
    try:
        d = json.loads(text)
    except ValueError:
        raise ApiError(f"JSON이 아닌 응답: {text[:200]}") from None
    r = d.get("response", {})
    header, body = r.get("header", {}), r.get("body") or {}
    code = str(header.get("resultCode"))
    if code == NO_DATA:
        return []
    if code != ok_code:
        raise ApiError(f"resultCode {code} {header.get('resultMsg')}")
    box = body.get("items") or {}
    rows = box.get("item", []) if isinstance(box, dict) else box
    return [rows] if isinstance(rows, dict) else rows
