"""collect_log를 Elasticsearch로 옮기는 DAG (K23, REQ-COL-008). Kibana 수집 상태 대시보드가 이 인덱스를 본다.

- collect_log_to_es  10분마다: MySQL collect_log에서 ES에 아직 없는 행(id가 ES의 최대 id보다 큰 행)만 옮긴다.
- collect_log 행은 수집이 끝날 때 한 번 INSERT되고 바뀌지 않는다 (collectors/common/collect_log.py). 그래서 새 id만 보면 된다.
- ES 문서 _id = collect_log.id 라서 같은 행을 다시 보내도 덮어쓸 뿐 문서가 늘지 않는다 (멱등).
- ES는 표준 라이브러리(urllib)로 REST를 부른다. 요청이 인덱스 생성·최대값 조회·_bulk 세 가지뿐이라 클라이언트 라이브러리를 더하지 않는다.
"""
import json
import os
import sys
import urllib.error
import urllib.request

import pendulum
from airflow.sdk import DAG, task

COLLECTORS = "/opt/farmit/collectors"   # common.db(MySQL 연결)를 같이 쓴다
ES_URL = os.environ.get("ES_URL", "http://elasticsearch:9200")
INDEX = "collect_log"
BATCH = 1000                             # MySQL에서 한 번에 읽어 _bulk 한 번으로 보내는 행 수
COLUMNS = ("id", "source", "target_date", "started_at", "finished_at",
           "status", "row_count", "api_calls", "error_msg")
# 매핑을 직접 정한다. 자동 매핑에 맡기면 source·status가 text로 잡혀 Kibana에서 그대로 묶어 세기 불편하다
MAPPING = {"mappings": {"properties": {
    "id": {"type": "long"},
    "source": {"type": "keyword"},
    "target_date": {"type": "date"},
    "started_at": {"type": "date"},
    "finished_at": {"type": "date"},
    "status": {"type": "keyword"},
    "row_count": {"type": "integer"},
    "api_calls": {"type": "integer"},
    "error_msg": {"type": "text"},
}}}


def es(method, path, body=None):
    """ES REST 호출. body가 str이면 _bulk용 NDJSON, dict면 JSON으로 보낸다. 응답 본문이 없으면(HEAD) None."""
    if isinstance(body, str):
        data, ctype = body.encode(), "application/x-ndjson"
    else:
        data, ctype = (json.dumps(body).encode() if body is not None else None), "application/json"
    req = urllib.request.Request(ES_URL + path, data=data, method=method, headers={"Content-Type": ctype})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    return json.loads(raw) if raw else None


def ensure_index():
    """인덱스가 없으면 위 매핑으로 만든다."""
    try:
        es("HEAD", f"/{INDEX}")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        es("PUT", f"/{INDEX}", MAPPING)


def last_id():
    """ES에 이미 옮긴 가장 큰 collect_log.id. 비어 있으면 0."""
    res = es("POST", f"/{INDEX}/_search", {"size": 0, "aggs": {"max_id": {"max": {"field": "id"}}}})
    return int(res["aggregations"]["max_id"]["value"] or 0)


def to_doc(row):
    """MySQL 한 행 → ES 문서. MySQL에는 UTC naive datetime으로 저장돼 있어 'Z'를 붙여 UTC임을 밝힌다."""
    doc = dict(zip(COLUMNS, row))
    doc["target_date"] = doc["target_date"].isoformat()
    for col in ("started_at", "finished_at"):
        if doc[col] is not None:
            doc[col] = doc[col].isoformat() + "Z"
    return doc


def bulk(docs):
    """_bulk로 한 번에 보낸다. 한 건이라도 실패하면 예외를 던져 태스크를 실패시킨다 (다음 실행이 같은 id부터 다시 보낸다)."""
    lines = []
    for d in docs:
        lines.append(json.dumps({"index": {"_index": INDEX, "_id": d["id"]}}))
        lines.append(json.dumps(d, ensure_ascii=False))
    res = es("POST", "/_bulk", "\n".join(lines) + "\n")   # NDJSON은 마지막 줄도 줄바꿈으로 끝나야 한다
    if res["errors"]:
        failed = [i["index"] for i in res["items"] if "error" in i["index"]]
        raise RuntimeError(f"ES _bulk 실패 {len(failed)}건: {failed[:3]}")


with DAG(
    "collect_log_to_es",
    schedule="*/10 * * * *",
    start_date=pendulum.datetime(2026, 11, 1, tz="UTC"),
    catchup=False,                  # 놓친 실행은 다음 실행이 한꺼번에 옮긴다
    max_active_runs=1,              # 두 실행이 같은 id 구간을 동시에 보내지 않게
    is_paused_upon_creation=False,  # 외부 API를 부르지 않으므로 수집 DAG와 달리 바로 켠다
    tags=["collect", "kibana"],
):
    @task
    def sync():
        if COLLECTORS not in sys.path:
            sys.path.insert(0, COLLECTORS)
        from common import db

        ensure_index()
        start = after = last_id()
        conn = db.connect()
        try:
            while True:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT {', '.join(COLUMNS)} FROM collect_log WHERE id > %s ORDER BY id LIMIT %s",
                                (after, BATCH))
                    rows = cur.fetchall()
                if not rows:
                    break
                bulk([to_doc(r) for r in rows])
                after = rows[-1][0]
        finally:
            conn.close()
        print(f"collect_log → ES: id {start} 다음부터 {after}까지 옮김")

    sync()
