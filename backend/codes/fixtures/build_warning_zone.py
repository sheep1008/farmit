"""특보구역코드 엑셀 → warning_zone.json (codes 마이그레이션 0006이 읽는다)

원본: 기상청 기상특보 조회서비스 활용가이드 별첨 "특보구역코드안내(YYMMDD).xlsx" (data.go.kr에서 받는다)
실행: pip install openpyxl  후
      python backend/codes/fixtures/build_warning_zone.py <엑셀 경로>
엑셀이 갱신되면 다시 실행해 json을 커밋하고, 바뀐 행을 반영하는 마이그레이션을 추가한다.

규칙 (Sheet2의 REG_UP 상위 구역을 따라 올라간다)
- 최상위(전국 바로 아래)가 시도, 그 바로 아래가 시군구다. 평지·산지·동부 같은 더 아래 구역은 그 시군구에 속한다
- 시도는 프로젝트 표기(정식 명칭, 예: 충청북도·대전광역시)로 바꾼다
- 특별시·광역시의 권역(서울동남권, 부산동부 등)은 시군구가 아니므로 sigungu를 비운다 → 시도 전체로 본다
- 해상 구역(S...)은 sido·sigungu를 비운다 → 알림 대상이 아니다
"""
import json
import re
import sys
from pathlib import Path

import openpyxl

TOP = 'L1000000'  # 전국
# 엑셀의 시도 이름 → 프로젝트 표기. 섬 지역 최상위 구역은 (시도, 시군구)로 바로 정한다
SIDO = {
    '경기도': '경기도', '강원도': '강원특별자치도', '충청남도': '충청남도', '충청북도': '충청북도',
    '전라남도': '전라남도', '전북자치도': '전북특별자치도', '경상북도': '경상북도', '경상남도': '경상남도',
    '제주도': '제주특별자치도', '서울특별시': '서울특별시', '인천광역시': '인천광역시',
    '대전광역시': '대전광역시', '광주광역시': '광주광역시', '대구광역시': '대구광역시',
    '부산광역시': '부산광역시', '울산광역시': '울산광역시', '세종특별자치시': '세종특별자치시',
}
ISLAND_TOP = {
    '서해5도': ('인천광역시', '옹진군'),
    '흑산도.홍도': ('전라남도', '신안군'),
    '울릉도.독도': ('경상북도', '울릉군'),
}
# 시군구 자리에 있지만 이름만으로는 시군구가 아닌 구역
SIGUNGU_FIX = {
    '추자도': '제주시',
    '거문도.초도': '여수시',
    '제주도산지': None,  # 제주시·서귀포시 산지에 걸친다 → 제주 전체
}
METRO = ('특별시', '광역시', '특별자치시')


def load(path):
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True)['Sheet2']
    rows = list(ws.iter_rows(values_only=True))[1:]  # 첫 줄은 머리글
    return {r[0]: {'up': r[4], 'name': r[6]} for r in rows if r[0]}


def resolve(code, zones):
    """구역 코드 → (sido, sigungu). 해상이면 (None, None)"""
    if not code.startswith('L'):
        return None, None
    chain = []  # [자기, 부모, ...] 전국 바로 아래(시도)까지
    c = code
    while c in zones and c != TOP:
        chain.append(zones[c]['name'])
        c = zones[c]['up']
    top = chain[-1]
    if top in ISLAND_TOP:
        return ISLAND_TOP[top]
    sido = SIDO[top]  # 모르는 시도면 KeyError로 멈춘다 (엑셀 형식이 바뀐 것)
    if len(chain) == 1:  # 시도 자체
        return sido, None
    name = chain[-2]
    if name in SIGUNGU_FIX:
        return sido, SIGUNGU_FIX[name]
    name = re.sub(r'\(.*\)', '', name).strip()  # 제주시(산지 제외) → 제주시
    if sido.endswith(METRO) and not name.endswith(('군', '구')):
        return sido, None  # 서울동남권·부산동부·대구중부 같은 권역, 또는 시 전체(인천광역시 등)
    return sido, name


def main():
    zones = load(sys.argv[1])
    out = []
    for code in sorted(zones):
        if code == TOP:
            continue
        sido, sigungu = resolve(code, zones)
        out.append({'region_code': code, 'name': zones[code]['name'], 'sido': sido, 'sigungu': sigungu})
    dest = Path(__file__).with_name('warning_zone.json')
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    land = [z for z in out if z['sido']]
    print(f'{dest}: {len(out)}개 (육상 {len(land)}, 해상 {len(out) - len(land)})')


if __name__ == '__main__':
    main()
