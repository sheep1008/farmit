#!/usr/bin/env bash
# Flink SQL 파일을 제출한다. SQL 안의 ${MYSQL_DATABASE}·${MYSQL_USER}·${MYSQL_PASSWORD}를
# 컨테이너 환경 변수(.env)로 바꿔 임시 파일에 쓰고, 제출이 끝나면 임시 파일을 지운다.
# 사용 (레포 루트에서):
#   docker compose -f infra/docker-compose.yml exec flink-jobmanager bash /opt/farmit/streaming/run_sql.sh auction_trade.sql
set -euo pipefail

src="/opt/farmit/streaming/sql/$1"
sql="$(cat "$src")"
# 큰따옴표로 감싸 비밀번호에 &, / 같은 문자가 있어도 그대로 들어가게 한다
sql="${sql//'${MYSQL_DATABASE}'/"$MYSQL_DATABASE"}"
sql="${sql//'${MYSQL_USER}'/"$MYSQL_USER"}"
sql="${sql//'${MYSQL_PASSWORD}'/"$MYSQL_PASSWORD"}"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
printf '%s\n' "$sql" > "$tmp"
/opt/flink/bin/sql-client.sh -f "$tmp"
