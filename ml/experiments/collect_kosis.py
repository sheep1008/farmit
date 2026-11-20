"""[3단계] KOSIS 생산량 통계표 (전국, 연). 통계표는 KOSIS 통합검색 API로 찾았다.

- DT_1ET0292 과실생산량(성과수+미과수): 사과·배·단감·감귤
- DT_1ET0291 채소생산량(조미채소): 양파·마늘
- DT_1ET0026 서류생산량(생서): 감자(봄·고랭지·가을)·고구마
항목: 생산량·면적·10a당 생산량. LST_CHN_DE(최종수정일)로 최신 연도의 공표 시점을 확인한다 (run_prod.py 참고).
사용: python collect_kosis.py   (3회 호출, KOSIS_API_KEY 필요)
"""
import pandas as pd
import requests

from common import DATA, get_key

URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"
TABLES = ["DT_1ET0292", "DT_1ET0291", "DT_1ET0026"]
OUT = DATA / "kosis"; OUT.mkdir(exist_ok=True)

if __name__ == "__main__":
    for tbl in TABLES:
        # objL1=00(전국). 이 표들은 objL2가 없어 넣으면 오류(21)가 난다
        p = {"method": "getList", "apiKey": get_key("KOSIS_API_KEY"), "format": "json", "jsonVD": "Y", "prdSe": "Y",
             "startPrdDe": "2012", "endPrdDe": str(pd.Timestamp.today().year), "orgId": "101", "tblId": tbl,
             "itmId": "ALL", "objL1": "00"}
        d = requests.get(URL, params=p, timeout=120).json()
        if not isinstance(d, list):
            raise SystemExit(f"KOSIS {tbl}: {d}")
        pd.DataFrame(d).to_csv(OUT / f"{tbl}.csv", index=False, encoding="utf-8-sig")
        print(tbl, len(d), "행")
