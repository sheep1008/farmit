"""forecast 테이블 적재: CSV 행 변환(UTC·결측), UPSERT 문, 품목·시장 검사. 가짜 DB 연결을 쓴다."""
from __future__ import annotations

from datetime import datetime

import pytest

from farmit_ml import store


def _row(**kw):
    r = {"item_code": "0601", "market_cd": "250001", "market_nm": "대전오정", "base_week": "2026-11-16", "horizon": "1",
         "target_week": "2026-11-16", "pred_price": "3000.5", "lower80": "2700.0", "upper80": "3400.0",
         "last_week_price": "", "near_holiday": "False", "model_version": "v4-abcd1234",
         "created_at": "2026-11-16T16:52:50+09:00"}
    return {**r, **kw}


class FakeCursor:
    def __init__(self, db):
        self.db, self.result = db, None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, args=()):
        self.db.sql.append((sql, list(args)))
        if sql.startswith("SELECT item_id"):
            self.result = [self.db.items[args[0]]] if args[0] in self.db.items else []
        elif sql.startswith("SELECT market_id"):
            self.result = [(m,) for m in self.db.markets]

    def fetchone(self):
        return self.result[0] if self.result else None

    def fetchall(self):
        return self.result


class FakeConn:
    def __init__(self, items=None, markets=("250001", "330101")):
        self.items = items if items is not None else {"0601": (10, 1)}
        self.markets, self.sql, self.committed, self.rolled_back = markets, [], False, False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def test_to_rows_converts_to_utc_and_blank_to_null():
    r = store.to_rows([_row()], item_id=10)[0]
    assert r["created_at"] == datetime(2026, 11, 16, 7, 52, 50)       # KST 16:52 → UTC 07:52
    assert r["last_week_price"] is None and r["pred_price"] == 3000.5 and r["horizon"] == 1
    assert "near_holiday" not in r and "market_nm" not in r


def test_save_upserts_on_unique_key():
    db = FakeConn()
    n = store.save(db, [_row(), _row(horizon="2", target_week="2026-11-23")])
    sql, args = db.sql[-1]
    assert n == 2 and db.committed
    assert sql.startswith("INSERT INTO `forecast`") and "ON DUPLICATE KEY UPDATE" in sql
    upd = sql.split("ON DUPLICATE KEY UPDATE")[1]
    assert "`pred_price` = new.`pred_price`" in upd and "`base_week`" not in upd   # UK 컬럼은 덮어쓰지 않는다
    assert args[:4] == [10, "250001", "2026-11-16", 1]


@pytest.mark.parametrize("conn, msg", [
    (FakeConn(items={}), "aT 코드"),
    (FakeConn(items={"0601": (10, 0)}), "is_forecast"),
    (FakeConn(markets=("330101",)), "없는 시장"),
])
def test_save_refuses_unknown_or_non_forecast(conn, msg):
    with pytest.raises(ValueError, match=msg):
        store.save(conn, [_row()])
    assert conn.rolled_back and not any(s.startswith("INSERT") for s, _ in conn.sql)
