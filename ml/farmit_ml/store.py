"""예측 결과를 forecast 테이블에 적재한다 (REQ-PRD-001, 004).

    python -m farmit_ml.store outputs/forecast_0601_2026-11-16.csv      # CSV를 적재
    python -m farmit_ml.forecast --item 0601 --to-db                   # 예측하고 바로 적재

- 테이블 스키마는 Django(prices 앱)가 소유한다. 여기서는 이미 있는 테이블에 쓰기만 한다 (수집기와 같은 방식).
- UK(item_id, market_id, base_week, horizon)로 UPSERT한다. 같은 기준 주를 다시 돌리면 값만 바뀌고 행은 늘지 않는다.
  다른 기준 주(지난 예측)는 건드리지 않는다.
- 품목은 CSV의 aT 코드(item_code)로 item 테이블에서 item_id를 찾는다. item.is_forecast가 false면 멈춘다.
- created_at은 UTC로 저장한다.
- 접속 정보는 환경 변수(MYSQL_USER·MYSQL_PASSWORD·MYSQL_DATABASE, DB_HOST·DB_PORT)에서 읽는다.
  표준 라이브러리 + PyMySQL만 쓴다: 파일 하나를 수집기 컨테이너에서 스크립트로 돌릴 수도 있다.
"""
from __future__ import annotations

import argparse
import csv
import os
from datetime import datetime, timezone

TABLE = "forecast"
KEY_COLS = ("item_id", "market_id", "base_week", "horizon")
VALUE_COLS = ("target_week", "pred_price", "lower80", "upper80", "last_week_price", "model_version", "created_at")
CHUNK = 500


def read_csv(path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _utc(s: str) -> datetime:
    """ISO 시각 → UTC(타임존 없는 값, Django USE_TZ 저장 형식). 타임존이 없는 값은 UTC로 본다."""
    t = datetime.fromisoformat(s)
    return t.astimezone(timezone.utc).replace(tzinfo=None) if t.tzinfo else t


def _num(s: str):
    return None if s in ("", "nan", "NaN", None) else float(s)


def to_rows(csv_rows: list[dict], item_id: int) -> list[dict]:
    """forecast CSV 행 → forecast 테이블 행. near_holiday·market_nm은 테이블에 없어 버린다 (API가 다시 계산)."""
    out = []
    for r in csv_rows:
        out.append({
            "item_id": item_id, "market_id": r["market_cd"], "base_week": r["base_week"], "horizon": int(r["horizon"]),
            "target_week": r["target_week"], "pred_price": _num(r["pred_price"]), "lower80": _num(r["lower80"]),
            "upper80": _num(r["upper80"]), "last_week_price": _num(r["last_week_price"]),
            "model_version": r["model_version"], "created_at": _utc(r["created_at"]),
        })
    return out


def connect():
    import pymysql
    return pymysql.connect(
        host=os.environ.get("DB_HOST", "mysql"), port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ["MYSQL_USER"], password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DATABASE"], charset="utf8mb4", autocommit=False,
    )


def item_id_of(cur, at_code: str) -> int:
    cur.execute("SELECT item_id, is_forecast FROM item WHERE at_code = %s", (at_code,))
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"item 테이블에 aT 코드 {at_code}가 없다")
    if not row[1]:
        raise ValueError(f"item {at_code}는 is_forecast가 false다 (예측 대상 판단은 이 값으로만 한다)")
    return int(row[0])


def upsert_sql(n: int) -> str:
    cols = KEY_COLS + VALUE_COLS
    one = "(" + ", ".join(["%s"] * len(cols)) + ")"
    return (f"INSERT INTO `{TABLE}` ({', '.join(f'`{c}`' for c in cols)}) VALUES " + ", ".join([one] * n)
            + " AS new ON DUPLICATE KEY UPDATE " + ", ".join(f"`{c}` = new.`{c}`" for c in VALUE_COLS))


def save(conn, csv_rows: list[dict]) -> int:
    """한 트랜잭션으로 UPSERT하고 넘긴 행 수를 돌려준다. 품목은 한 파일에 하나여야 한다."""
    codes = {r["item_code"] for r in csv_rows}
    if len(codes) != 1:
        raise ValueError(f"한 파일에 품목이 하나여야 한다: {sorted(codes)}")
    cols = KEY_COLS + VALUE_COLS
    try:
        with conn.cursor() as cur:
            rows = to_rows(csv_rows, item_id_of(cur, codes.pop()))
            cur.execute("SELECT market_id FROM market")
            unknown = sorted({r["market_id"] for r in rows} - {m for (m,) in cur.fetchall()})
            if unknown:
                raise ValueError(f"market 테이블에 없는 시장: {unknown}")
            for i in range(0, len(rows), CHUNK):
                chunk = rows[i:i + CHUNK]
                cur.execute(upsert_sql(len(chunk)), [r[c] for r in chunk for c in cols])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return len(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description="forecast CSV를 forecast 테이블에 UPSERT한다")
    ap.add_argument("csv", nargs="+", help="farmit_ml.forecast가 만든 CSV")
    a = ap.parse_args(argv)
    conn = connect()
    try:
        for p in a.csv:
            print(f"{p}: {save(conn, read_csv(p))}행 적재")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
