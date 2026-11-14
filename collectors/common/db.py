"""DB 연결과 UPSERT.

접속 정보는 환경 변수에서 읽는다. compose가 레포 루트 .env를 env_file로 넘겨 주므로 코드는 .env 파일을 직접 열지 않는다.
테이블 스키마는 Django 마이그레이션이 소유한다. 수집기는 이미 있는 테이블에 쓰기만 한다.
"""
import os

import pymysql

CHUNK = 500  # INSERT 한 문장에 넣는 행 수. 너무 크면 max_allowed_packet에 걸린다


def connect(database=None):
    return pymysql.connect(
        host=os.environ.get("DB_HOST", "mysql"), port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ["MYSQL_USER"], password=os.environ["MYSQL_PASSWORD"],
        database=database or os.environ["MYSQL_DATABASE"], charset="utf8mb4", autocommit=True,
    )


def _q(name):
    """테이블·컬럼 이름을 백틱으로 감싼다. 이름은 코드가 정하는 값이고 외부 입력이 아니다."""
    return f"`{name}`"


def upsert(conn, table, rows, update_cols):
    """rows(dict 목록)를 INSERT ... ON DUPLICATE KEY UPDATE로 쓰고, 넘긴 행 수를 돌려준다.

    같은 행인지는 테이블의 UNIQUE 키(예: settle_price의 uk_settle_price)가 판단한다.
    이미 있으면 update_cols 컬럼만 새 값으로 덮어쓴다. 그래서 같은 날짜를 두 번 돌려도 행이 늘지 않는다 (멱등).
    MySQL 8.0.20부터 VALUES(col) 문법이 폐기 예정이라 행 별칭(AS new)을 쓴다.
    """
    if not rows:
        return 0
    cols = list(rows[0])
    one = "(" + ", ".join(["%s"] * len(cols)) + ")"
    head = f"INSERT INTO {_q(table)} ({', '.join(map(_q, cols))}) VALUES "
    tail = " AS new ON DUPLICATE KEY UPDATE " + ", ".join(f"{_q(c)} = new.{_q(c)}" for c in update_cols)
    with conn.cursor() as cur:
        # 여러 행을 한 문장으로 보낸다 (한 행씩 보내면 수천 건일 때 왕복이 수천 번)
        for i in range(0, len(rows), CHUNK):
            chunk = rows[i:i + CHUNK]
            cur.execute(head + ", ".join([one] * len(chunk)) + tail,
                        [r[c] for r in chunk for c in cols])
    return len(rows)
