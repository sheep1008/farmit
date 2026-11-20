"""품목별 주산지 계산 → item_producing_area (K29, REQ-COL-003·REQ-ALT-001).

1. aT 정산정보를 최근 1년(어제까지) 수집 대상 시장마다 받아 원산지(plor_nm, "경상북도 영주시")별 물량(kg)을 더한다.
   settle_price는 원산지를 저장하지 않으므로 API를 다시 부른다 (사과 1년·시장 5곳 ≈ 호출 100건 안쪽).
2. 시군구별 물량 비중을 큰 순서로 누적 COVER%까지 고르고, 한 곳이 MIN_SHARE% 미만이면 뺀다.
3. 시군구 위치 = 그 시군구 안 기상청 지점(ASOS+AWS)들의 평균 위경도 (기상청 API허브 지점정보).
   가장 가까운 ASOS 관측소(weather_station)를 잇는다.
4. 그 품목의 주산지를 이번 결과로 바꾼다 (빠진 시군구는 지운다). 다시 돌려도 같은 결과면 행이 늘지 않는다.

    # 레포 루트에서. 기본: 사과
    docker compose -f infra/docker-compose.yml --profile collect run --rm collectors python -m weather.producing_area
    ... python -m weather.producing_area --items 사과 배

환경 변수: DATA_GO_KR_KEY(정산), KMA_APIHUB_KEY(지점 위치).
"""
import argparse
import math
import os
import re
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from common import datagokr
from common.collect_log import collect_run
from common.db import upsert
from settle import at_settle

SOURCE = "producing_area"
DAILY_LIMIT = at_settle.DAILY_LIMIT  # 정산 API를 쓴다. 호출 수는 이 출처로 따로 센다
STN_URL = "https://apihub.kma.go.kr/api/typ01/url/stn_inf.php"
COVER = 80       # 누적 비중(%)이 이만큼 될 때까지 고른다
MIN_SHARE = 3    # 한 시군구 비중(%)이 이보다 작으면 뺀다
# 기상청·aT 주소는 통합 시도 이름을 쓴다. 다른 코드표(warning_zone·weather_station)와 같은 옛 표기로 나눈다
MERGED = "전남광주통합특별시"
SIDO_END = ("특별시", "광역시", "특별자치시", "도", "특별자치도")
# 지점정보 한 줄의 끝: 예보구역코드 법정동코드(10자리) 수계 법정동주소. 앞 칸 수는 SFC·AWS가 달라 끝에서 자른다
STN_TAIL = re.compile(r"\s\S{8}\s+\d{10}\s+\S+\s+(?P<addr>.+?)\s*$")


def area(text):
    """주소·원산지 문자열 → (시도, 시군구). 시군구까지 없거나 국내가 아니면 None.

    "(산지)강원특별자치도 평창군 …" → ("강원특별자치도", "평창군"), "경기도 수원시권선구 …" → ("경기도", "수원시"),
    "전남광주통합특별시 북구 …" → ("광주광역시", "북구").
    """
    parts = re.sub(r"^\(.*?\)", "", text or "").split()
    if len(parts) < 2 or not parts[0].endswith(SIDO_END):
        return None
    sido, sigungu = parts[0], parts[1]
    if sido == MERGED:
        sido = "광주광역시" if sigungu.endswith("구") else "전라남도"
    m = re.match(r"^(.+?[시군])(.+구)$", sigungu)   # 수원시권선구 → 수원시 (원산지는 시 단위로 온다)
    return sido, (m.group(1) if m else sigungu)


def origin_volume(run, at_code, markets, start, end):
    """[start, end] 정산에서 원산지(시도, 시군구)별 kg 합계. 시군구를 알 수 없는 원산지는 따로 더한다."""
    vol, unknown = defaultdict(Decimal), Decimal(0)
    for s, e in at_settle.month_chunks(start, end):
        for m in markets:
            page, seen = 1, 0
            while True:
                text = run.get(at_settle.URL, {
                    "returnType": "json", "pageNo": page, "numOfRows": at_settle.PAGE,
                    "cond[trd_clcln_ymd::GTE]": s.isoformat(), "cond[trd_clcln_ymd::LTE]": e.isoformat(),
                    "cond[whsl_mrkt_cd::EQ]": m,
                    "cond[gds_lclsf_cd::EQ]": at_code[:2], "cond[gds_mclsf_cd::EQ]": at_code[2:],
                }, key=("serviceKey", datagokr.service_key()))
                rows, total = at_settle.parse(text)
                for r in rows:
                    if r.get("unit_nm") != "kg":   # settle_price와 같은 기준 (kg 단위만)
                        continue
                    qty = Decimal(str(r.get("unit_tot_qty") or 0))
                    a = area(r.get("plor_nm"))
                    if a:
                        vol[a] += qty
                    else:
                        unknown += qty
                seen += len(rows)
                if not rows or seen >= total:
                    break
                page += 1
    return vol, unknown


def pick(vol):
    """물량 → [(시도, 시군구, 비중%)]. 큰 순서로 누적 COVER%까지, MIN_SHARE% 미만은 뺀다."""
    total = sum(vol.values())
    if not total:
        return []
    out, cum = [], Decimal(0)
    for a, v in sorted(vol.items(), key=lambda kv: (-kv[1], kv[0])):
        share = v * 100 / total
        if cum >= COVER or share < MIN_SHARE:
            break
        out.append((a[0], a[1], share.quantize(Decimal("0.01"))))
        cum += share
    return out


def stn_locations(run):
    """기상청 지점(ASOS+AWS)을 시군구로 묶은 평균 위치 {(시도, 시군구): (위도, 경도)}."""
    pts = defaultdict(list)
    for inf in ("SFC", "AWS"):
        text = run.get(STN_URL, {"inf": inf, "stn": "", "help": 0},
                       key=("authKey", os.environ["KMA_APIHUB_KEY"]), encoding="euc-kr")
        for line in text.splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            m = STN_TAIL.search(line)
            a = area(m["addr"]) if m else None
            if a:
                _, lon, lat = line.split()[:3]
                pts[a].append((float(lat), float(lon)))
    return {a: (sum(p[0] for p in v) / len(v), sum(p[1] for p in v) / len(v)) for a, v in pts.items()}


def km(p, q):
    """두 (위도, 경도) 사이 거리(km). 하버사인 공식."""
    la1, lo1, la2, lo2 = map(math.radians, (*p, *q))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def nearest(loc, stations):
    """loc에서 가장 가까운 관측소 (station_id, 거리 km). stations: [(station_id, 위도, 경도)]"""
    return min(((sid, km(loc, (lat, lng))) for sid, lat, lng in stations), key=lambda x: x[1])


def collect(names, conn=None):
    """names(품목 이름) 품목마다 주산지를 계산해 바꾼다. collect_log에는 한 줄, target_date는 어제."""
    end = at_settle.yesterday()
    start = end - timedelta(days=364)

    @collect_run(SOURCE, daily_limit=DAILY_LIMIT)
    def run_(run):
        with run.conn.cursor() as cur:
            cur.execute("SELECT market_id FROM market WHERE is_collect = 1 OR is_reference = 1 ORDER BY market_id")
            markets = [r[0] for r in cur.fetchall()]
            cur.execute("SELECT station_id, lat, lng FROM weather_station")
            stations = [(sid, float(lat), float(lng)) for sid, lat, lng in cur.fetchall()]
            cur.execute(f"SELECT item_id, name, at_code FROM item WHERE name IN ({', '.join(['%s'] * len(names))})",
                        names)
            items = cur.fetchall()
        missing = set(names) - {i[1] for i in items}
        if missing or not markets or not stations:
            raise RuntimeError(f"초기 데이터가 없다: 품목 {sorted(missing)}, 시장 {len(markets)}곳, 관측소 {len(stations)}곳")
        locs = stn_locations(run)
        run.report = []
        for item_id, name, at_code in items:
            vol, unknown = origin_volume(run, at_code, markets, start, end)
            rows = []
            for sido, sigungu, share in pick(vol):
                loc = locs.get((sido, sigungu))
                if loc is None:   # 지점이 하나도 없는 시군구 → 이을 관측소를 정할 수 없다
                    run.errors.append(f"{name} {sido} {sigungu}: 기상청 지점이 없어 위치를 모름")
                    continue
                sid, dist = nearest(loc, stations)
                rows.append({"item_id": item_id, "sido": sido, "sigungu": sigungu,
                             "station_id": sid, "volume_share": share})
                run.report.append(f"{name} {sido} {sigungu} {share}% → 관측소 {sid} ({dist:.0f}km)")
            known = sum(vol.values())
            run.report.append(f"{name}: 원산지 {len(vol)}곳 {known:,.0f}kg, 시군구 모름 {unknown:,.0f}kg → 주산지 {len(rows)}곳")
            with run.conn.cursor() as cur:
                keep = [(r["sido"], r["sigungu"]) for r in rows]
                cur.execute("SELECT sido, sigungu FROM item_producing_area WHERE item_id = %s", (item_id,))
                for old in set(cur.fetchall()) - set(keep):   # 이번에 빠진 시군구
                    cur.execute("DELETE FROM item_producing_area WHERE item_id = %s AND sido = %s AND sigungu = %s",
                                (item_id, *old))
            run.rows += upsert(run.conn, "item_producing_area", rows, ["station_id", "volume_share"])
    return run_(end, conn=conn)


def main(argv=None):
    p = argparse.ArgumentParser(description="품목별 주산지 계산 → item_producing_area")
    p.add_argument("--items", nargs="+", default=["사과"], help="item.name (기본: 사과)")
    a = p.parse_args(argv)
    run = collect(a.items)
    print("\n".join(run.report))
    print(f"{run.rows}행, 호출 {run.api_calls}건" + (f", 실패 {len(run.errors)}건" if run.errors else ""))
    for msg in run.errors:
        print("  " + msg)


if __name__ == "__main__":
    main()
