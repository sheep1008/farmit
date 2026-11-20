"""시군구 목록 → sigungu_coords.json (시군구 중심 좌표, 회원 위치 ~ 시장 거리 계산용)

원본: OpenStreetMap Nominatim 검색 (https://nominatim.openstreetmap.org, © OpenStreetMap contributors, ODbL)
      행정구역 경계(boundary/administrative)의 대표 좌표를 쓴다.
대상: frontend/src/constants/regions.js 의 시도·시군구 (회원가입·내 정보에서 고르는 값과 같은 이름)
실행: python backend/codes/fixtures/build_sigungu_coords.py      (레포 루트에서, 약 5분)
      Nominatim 이용 규칙에 따라 1초에 한 번만 부른다.
행정구역이 바뀌어 regions.js를 고치면 다시 실행해 json을 커밋한다.
json이 이미 있으면 거기 없는 시군구만 찾는다. 전부 다시 받으려면 json을 지우고 실행한다.
찾지 못한 시군구는 끝에 목록으로 출력한다 → json에 없으면 그 회원은 거리 없이(운송비 미반영) 계산된다.
"""
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REGIONS_JS = ROOT / 'frontend' / 'src' / 'constants' / 'regions.js'
OUT = Path(__file__).with_name('sigungu_coords.json')
URL = 'https://nominatim.openstreetmap.org/search?'
# 프로젝트 표기와 OpenStreetMap 표기가 다른 곳. 프로젝트는 통합 전 시도 이름을 쓴다 (docs/data-sources.md)
OSM_SIDO = {'광주광역시': '광주, 전남광주통합특별시', '전라남도': '전남광주통합특별시'}
OSM_SIGUNGU = {('인천광역시', '서구'): '서해구'}  # 2026-07-01 행정체제 개편 뒤 이름


def regions():
    """regions.js의 `시도: ['시군구', ...]` 줄을 읽는다."""
    found = {}
    for line in REGIONS_JS.read_text(encoding='utf-8').splitlines():
        m = re.match(r"\s+(\S+): \[(.*)\],?$", line)
        if m:
            found[m.group(1)] = re.findall(r"'([^']+)'", m.group(2))
    return found


def search(sido, sigungu):
    """(위도, 경도) 또는 None. 이름이 같은 다른 곳을 고르지 않게 행정구역 경계이고 시도가 맞는 결과만 쓴다."""
    # 세종은 시군구가 없어 화면에서 '세종시' 하나로 둔다 → 시도 이름으로 찾는다
    osm_sido = OSM_SIDO.get(sido, sido)
    osm_sigungu = OSM_SIGUNGU.get((sido, sigungu), sigungu)
    # 검색어에는 쉼표 앞 이름만 쓴다 ('광주, 전남광주통합특별시' → '광주 광산구')
    query = sido if sido == '세종특별자치시' else f"{osm_sido.split(',')[0]} {osm_sigungu}"
    params = {'q': query, 'countrycodes': 'kr', 'format': 'jsonv2', 'limit': 5, 'accept-language': 'ko'}
    request = urllib.request.Request(URL + urllib.parse.urlencode(params),
                                     headers={'User-Agent': 'farmit-fixture-builder/1.0'})
    with urllib.request.urlopen(request, timeout=30) as response:
        rows = json.load(response)
    for r in rows:
        name = r['display_name']
        if r['category'] == 'boundary' and r['type'] == 'administrative' and osm_sido in name \
                and (sido == '세종특별자치시' or name.startswith(osm_sigungu)):
            return round(float(r['lat']), 4), round(float(r['lon']), 4)
    return None


def main():
    coords = json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else {}
    missing = []
    for sido, names in regions().items():
        coords.setdefault(sido, {})
        for sigungu in names:
            if sigungu in coords[sido]:
                continue
            point = search(sido, sigungu)
            if point:
                coords[sido][sigungu] = point
            else:
                missing.append(f'{sido} {sigungu}')
            time.sleep(1.1)
    OUT.write_text(json.dumps(coords, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'{sum(len(v) for v in coords.values())}곳 저장 → {OUT}')
    if missing:
        print('찾지 못함:', ', '.join(missing))


if __name__ == '__main__':
    main()
