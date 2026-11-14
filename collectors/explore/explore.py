"""공공데이터 API 응답 구조 탐색 (K02, REQ-COL-001·003, REQ-NFR-009).

API마다 한 번만 호출해 원본 응답을 data/explore/<이름>.json에 저장하고, 건수와 필드 목록을 출력한다.
수집기가 아니다. 응답 모양을 확인해 docs/data-sources.md를 쓰기 위한 일회성 스크립트다.
호출 방법(주소·파라미터)은 ml/experiments에서 이미 확인한 것을 따른다.

    # 레포 루트에서. .env는 docker가 읽어 환경 변수로 넘긴다 (스크립트는 .env 파일을 열지 않는다)
    docker run --rm --env-file .env -v "$PWD/collectors/explore:/app" -v "$PWD/data:/data" \
        -e OUT_DIR=/data/explore python:3.12-slim python /app/explore.py all

키(DATA_GO_KR_KEY, KOSIS_API_KEY)는 출력·예외·저장 파일 어디에도 남기지 않는다.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(os.environ.get("OUT_DIR", "data/explore"))


def key(name):
    v = os.environ.get(name, "").strip()
    if not v:
        sys.exit(f"{name}가 비어 있다. 레포 루트 .env에 넣어 달라")
    return v


def data_go_kr_key():
    # 포털의 Encoding 키(%가 들어 있음)는 그대로, Decoding 키는 URL 인코딩해서 붙인다 (collectors/auction/client.py와 같음)
    k = key("DATA_GO_KR_KEY")
    return k if "%" in k else urllib.parse.quote(k, safe="")


def get(url, key_param, key_value, params):
    """키는 urlencode를 거치지 않고 붙인다 (이미 인코딩된 키가 두 번 인코딩되지 않게)."""
    full = f"{url}?{key_param}={key_value}&{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(full, timeout=60) as resp:
            text = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}")  # URL에 키가 있으므로 상태 코드만 남긴다
    except urllib.error.URLError as e:
        sys.exit(f"접속 실패: {type(e.reason).__name__}")
    try:
        return json.loads(text)
    except ValueError:
        # data.go.kr은 키 오류 등을 JSON 요청에도 XML로 돌려준다. 앞부분만 보여 준다 (응답 본문에는 키가 없다)
        sys.exit(f"JSON이 아닌 응답: {text[:300]}")


def data_go_kr_items(d):
    """data.go.kr 공통 모양 response.header/body.items.item 에서 (결과코드, 전체 건수, 행 목록)을 꺼낸다."""
    r = d.get("response", {})
    header, body = r.get("header", {}), r.get("body") or {}
    items = body.get("items") or {}
    rows = items.get("item", []) if isinstance(items, dict) else items
    if isinstance(rows, dict):  # 1건이면 리스트가 아니라 객체로 온다
        rows = [rows]
    return f"{header.get('resultCode')} {header.get('resultMsg')}", body.get("totalCount"), rows


def settle():
    # aT 정산정보. 날짜는 GTE/LTE + YYYY-MM-DD 로만 조회된다 (EQ·YYYYMMDD는 0건, ml/experiments/common.py)
    d = get("https://apis.data.go.kr/B552845/katSale/trades", "serviceKey", data_go_kr_key(), {
        "returnType": "json", "pageNo": 1, "numOfRows": 100,
        "cond[trd_clcln_ymd::GTE]": "2026-10-30", "cond[trd_clcln_ymd::LTE]": "2026-10-30",
        "cond[whsl_mrkt_cd::EQ]": "250001",  # 대전오정
    })
    return d, *data_go_kr_items(d)


def asos():
    # 기상청 ASOS 일자료. 대전(133) 하루
    d = get("https://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList", "serviceKey", data_go_kr_key(), {
        "dataType": "JSON", "pageNo": 1, "numOfRows": 10, "dataCd": "ASOS", "dateCd": "DAY",
        "startDt": "20261030", "endDt": "20261030", "stnIds": 133,
    })
    return d, *data_go_kr_items(d)


def holiday():
    # 한국천문연구원 특일 정보 - 공휴일. 2026년 9월(추석) 한 달
    d = get("https://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getRestDeInfo", "ServiceKey",
            data_go_kr_key(), {"_type": "json", "solYear": 2026, "solMonth": "09", "numOfRows": 50})
    return d, *data_go_kr_items(d)


def kosis():
    # KOSIS 과실생산량(DT_1ET0292, 전국, 연). objL2를 넣으면 오류 21 (ml/experiments/collect_kosis.py)
    d = get("https://kosis.kr/openapi/Param/statisticsParameterData.do", "apiKey",
            urllib.parse.quote(key("KOSIS_API_KEY"), safe=""), {
                "method": "getList", "format": "json", "jsonVD": "Y", "prdSe": "Y",
                "startPrdDe": "2024", "endPrdDe": "2025", "orgId": "101", "tblId": "DT_1ET0292",
                "itmId": "ALL", "objL1": "00",
            })
    if not isinstance(d, list):  # 오류면 {"err": ..., "errMsg": ...} 객체가 온다
        return d, f"오류 {d}", None, []
    return d, "ok", len(d), d


APIS = {"settle": settle, "asos": asos, "holiday": holiday, "kosis": kosis}


def main(names):
    OUT.mkdir(parents=True, exist_ok=True)
    for name in names:
        raw, result, total, rows = APIS[name]()
        (OUT / f"{name}.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n== {name}: 결과={result} 전체 건수={total} 받은 행={len(rows)} → {OUT / (name + '.json')}")
        if rows:
            for field, value in rows[0].items():  # 첫 행의 필드와 예시 값
                print(f"  {field:24} {str(value)[:50]}")


if __name__ == "__main__":
    args = sys.argv[1:] or ["all"]
    main(list(APIS) if args == ["all"] else args)
