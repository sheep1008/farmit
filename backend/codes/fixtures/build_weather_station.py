"""기상청 API허브 지상(ASOS) 지점정보 → weather_station.json (codes 마이그레이션 0008이 읽는다)

원본: 기상청 API허브 "지상관측 지점정보 조회 > 지상" (stn_inf.php?inf=SFC). tm 시각에 운영 중인 지점만 온다.
실행: .env에 KMA_APIHUB_KEY를 넣고 (레포 루트에서)
      docker compose -f infra/docker-compose.yml exec backend python codes/fixtures/build_weather_station.py
지점이 바뀌면 다시 실행해 json을 커밋하고, 바뀐 행을 반영하는 마이그레이션을 추가한다.
키가 없는 팀원은 이 스크립트를 돌릴 필요가 없다 (migrate가 json을 넣는다).
"""
import json
import os
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

URL = 'https://apihub.kma.go.kr/api/typ01/url/stn_inf.php'
KST = timezone(timedelta(hours=9))
# 한 줄: STN LON LAT STN_SP HT HT_PA HT_TA HT_WD HT_RN STN_AD STN_KO STN_EN FCT_ID LAW_ID BASIN LAW_ADDR
# 지점명(영문)·주소에 공백이 있을 수 있어 앞 칸은 공백으로, 뒤는 예보구역·법정동코드 모양으로 자른다
LINE = re.compile(r'^\s*(?P<stn>\d+)\s+(?P<lon>[\d.]+)\s+(?P<lat>[\d.]+)\s+(?:\S+\s+){7}(?P<name>\S+)\s+.*?'
                  r'\s+\S{8}\s+\d{10}\s+\S+\s+(?P<addr>.+?)\s*$')
SIDO = ('특별시', '광역시', '특별자치시', '도', '특별자치도')
# 기상청 주소는 통합 시도 이름을 쓴다. 프로젝트의 다른 코드표(warning_zone)는 아직 광주광역시·전라남도라 맞춘다
MERGED = '전남광주통합특별시'


def fetch(key, tm):
    query = f'inf=SFC&stn=&tm={tm:%Y%m%d%H%M}&help=0&authKey={key}'
    with urllib.request.urlopen(f'{URL}?{query}', timeout=30) as resp:
        return resp.read().decode('euc-kr')


def parse(text):
    """응답 본문 → weather_station 행 목록. #으로 시작하는 줄은 설명이다."""
    out = []
    for line in text.splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        m = LINE.match(line)
        if not m:
            raise ValueError(f'형식이 다른 줄: {line!r}')  # 응답 형식이 바뀐 것 → 멈춘다
        addr = re.sub(r'^\(.*?\)', '', m['addr'])  # (산지)강원특별자치도 ... → 강원특별자치도 ...
        sido, sigungu = addr.split()[:2]
        if sido == MERGED:  # 특보구역(warning_zone)과 같은 옛 표기로 나눈다: 구는 광주, 시·군은 전남
            sido = '광주광역시' if sigungu.endswith('구') else '전라남도'
        if not sido.endswith(SIDO):
            raise ValueError(f'시도를 알 수 없는 주소: {m["addr"]!r}')
        out.append({'station_id': int(m['stn']), 'name': m['name'], 'sido': sido,
                    'lat': f'{float(m["lat"]):.6f}', 'lng': f'{float(m["lon"]):.6f}'})
    return sorted(out, key=lambda r: r['station_id'])


def main():
    key = os.environ['KMA_APIHUB_KEY']
    rows = parse(fetch(key, datetime.now(KST)))
    dest = Path(__file__).with_name('weather_station.json')
    dest.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'{dest}: {len(rows)}곳, 시도 {len({r["sido"] for r in rows})}개')


if __name__ == '__main__':
    main()
