"""실시간 경매 API 응답 한 건을 auction_trade 메시지로 바꾸는 순수 함수 모음 (DB·네트워크를 쓰지 않는다)."""
import hashlib
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

KST = timezone(timedelta(hours=9))
TIME_FMT = "%Y-%m-%d %H:%M:%S"

# 낙찰 한 건을 구분하는 원본 필드. auctn_seq·spm_no만으로는 겹친다
# (같은 원표가 시각을 달리해 나눠 팔린다) → 낙찰 일시까지 합친다
KEY_FIELDS = ("whsl_mrkt_cd", "corp_cd", "trd_clcln_ymd", "auctn_seq", "spm_no", "scsbd_dt")


def at_code(row):
    """품목 코드 = 대분류 + 중분류 4자리 (docs/erd.md item.at_code)."""
    return row["gds_lclsf_cd"] + row["gds_mclsf_cd"]


def source_key(row):
    """원본 필드를 이어 SHA-1(40자)로 만든다. 같은 건은 다시 받아도 같은 값이고 varchar(64)를 넘지 않는다."""
    raw = "|".join(row[f] for f in KEY_FIELDS)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def kst_to_utc(text):
    """API의 한국 시간 문자열을 UTC 문자열로 바꾼다 (DB는 UTC로 저장)."""
    kst = datetime.strptime(text, TIME_FMT).replace(tzinfo=KST)
    return kst.astimezone(timezone.utc).strftime(TIME_FMT)


def _one_decimal(value):
    """소수 첫째 자리로 반올림 (컬럼이 decimal(10,1))."""
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _clean(text, limit):
    """연속 공백을 하나로 줄이고 컬럼 길이에 맞춰 자른다."""
    return " ".join(text.split())[:limit]


def to_message(row, item_id, collected_at):
    """Kafka로 보낼 메시지(dict). kg 단위가 아니거나 단위물량이 0이면 환산할 수 없으므로 None."""
    if row["unit_nm"] != "kg":
        return None
    unit_qty = Decimal(row["unit_qty"])
    if unit_qty <= 0:
        return None
    return {
        "source_key": source_key(row),
        "auction_at": kst_to_utc(row["scsbd_dt"]),
        "market_id": row["whsl_mrkt_cd"],
        "item_id": item_id,
        "corp_name": _clean(row["corp_nm"], 30),
        "grade": "",  # 실시간 API에는 등급이 없다
        "origin": _clean(row["plor_nm"], 30),
        # scsbd_prc는 단량(예: 2kg 상자) 하나의 가격 → kg당 가격
        "price_per_kg": _one_decimal(Decimal(row["scsbd_prc"]) / unit_qty),
        # qty는 단량 개수 → 총 kg
        "volume_kg": _one_decimal(Decimal(row["qty"]) * unit_qty),
        "collected_at": collected_at,
        "raw": row,  # 원본(포장 단위)도 그대로 보관한다
    }


def new_item(row):
    """item 테이블에 없는 품목을 등록할 때 넣을 값. 이름은 중분류명, 분류는 대분류명 (items.json과 같은 기준).

    이름이 비어 있으면 화면에서 고를 수 없으므로 None (등록하지 않는다).
    """
    name = _clean(row.get("gds_mclsf_nm") or "", 50)
    if not name:
        return None
    return {"at_code": at_code(row), "name": name, "category": _clean(row.get("gds_lclsf_nm") or "", 20)}


def is_collect_time(now_kst, last_collected=None):
    """수집 시간: 한국 시간 00~12시는 매번, 12~17시는 지난 수집(last_collected)에서 30분이 지났을 때만.

    대부분 11시쯤 끝나지만 안동·광주각화·진주 등은 13시 넘어서도 낙찰이 있다 (2026-11-18 정산분 1,834건, 마지막 16:18).
    오후에는 건수가 적어 30분 주기로 호출 수를 아낀다 (32곳 × 10바퀴 = 320건).
    """
    if now_kst.hour < 12:
        return True
    if now_kst.hour < 17:
        return last_collected is None or now_kst - last_collected >= timedelta(minutes=30)
    return False


def rows_until(rows, stop_before):
    """최신순 rows에서 stop_before(낙찰 일시 문자열)보다 오래된 건이 나오기 전까지만 돌려준다.

    돌려주는 값: (남긴 rows, 오래된 건을 만났는지). 만났으면 다음 페이지는 받지 않는다.
    """
    if stop_before is None:
        return rows, False
    for i, row in enumerate(rows):
        if row["scsbd_dt"] < stop_before:
            return rows[:i], True
    return rows, False


def overlap_start(last_seen, minutes=30):
    """지난번 본 가장 최근 낙찰 일시에서 minutes만큼 앞. 늦게 반영되는 건을 놓치지 않으려고 겹쳐 받는다."""
    if last_seen is None:
        return None
    return (datetime.strptime(last_seen, TIME_FMT) - timedelta(minutes=minutes)).strftime(TIME_FMT)
